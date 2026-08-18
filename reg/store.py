"""The evidence graph's persistence layer: SQLite schema and write primitives.

    from reg import store
    conn = store.create("runs/contact.sqlite")
    store.insert_entity(conn, "obs_crate", "crate", geometry=disc)
    edge_id = store.open_edge(conn, "SEPARATION", cfg_id, "obs_crate", t_start=0.0,
                              min_distance=0.41)
    store.extend_edge(conn, edge_id, t_end=2.98)

WHY SQLITE AND WHY WKB
----------------------
docs/plan.md, Phase 5: the tables are small, the queries are interval joins and
chain walks, and `sqlite3` is stdlib. That last part is not convenience — a
single portable file with no external runtime is more credible as a thing handed
to an assessor in three years than a format requiring a specific engine to be
still installed. Geometry is stored as **WKB blobs** and every geometric
operation happens in Python via shapely; SQLite is a container here, not a
spatial database, and no query should ever try to reason about a blob.

THE EDGE TABLE IS ONE TABLE ON PURPOSE
--------------------------------------
Every edge type lands in `edge` with a `type` and a `layer`. Claim 3 is a query
over the layer tag across *all* edges ("which of these answers depend on an
uncertifiable perceiver"), and that query has to be one `WHERE layer = 'B'`
rather than a union over however many tables exist by then. docs/lossiness.md
Retained #9: "an untagged edge is an unusable edge."

The caller never supplies the layer. It is derived from the edge type through
`EDGE_SPECS` below, so a Layer B relationship cannot be written as Layer A by a
caller in a hurry — which is precisely the mistake that would make Claim 3 read
better than the truth.

WHAT THE SCHEMA REFUSES
-----------------------
The `CHECK` constraints are not belt and braces; each one is a wrong answer that
would otherwise be indistinguishable from a right one:

* `t_end >= t_start` — a backwards interval matches no time window and would
  silently drop out of every timeline query.
* `layer IN ('A', 'B')` — see above.
* metric presence keyed to edge type — an `INTERSECTS` with no `overlap_area`
  answers "how much overlap" with `NULL`, and `NULL` compares false against every
  threshold, so an incident reads as a non-incident.
* geometry present exactly for entities whose geometry is time-invariant — see
  `insert_entity`.

DETERMINISM
-----------
Same inserts in the same order produce the same file, byte for byte. Nothing here
writes a clock, a path, a hostname or a `rowid` derived from anything but
insertion order, and `tests/test_graph.py` builds the same stream twice and
compares bytes. If you add a column, add one whose value is a function of the
input stream.
"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import shapely
from shapely.geometry.base import BaseGeometry

from reg.types import Layer

__all__ = [
    "SCHEMA_VERSION",
    "META_SCHEMA_VERSION",
    "META_FRAME_PERIOD",
    "ENVELOPE_SOURCES",
    "EDGE_SPECS",
    "NODE_TABLES",
    "StoreError",
    "create",
    "connect",
    "layer_of",
    "put_meta",
    "get_meta",
    "all_meta",
    "insert_timestep",
    "insert_envelope",
    "insert_entity",
    "insert_robot_config",
    "open_edge",
    "extend_edge",
    "read_edges",
    "to_wkb",
    "from_wkb",
]

#: Bumped whenever a table, column or constraint changes. It is written into
#: `meta` so a reader that meets an unfamiliar artifact can say it does not
#: understand it, rather than querying a column that has since changed meaning
#: and getting a confident wrong answer.
SCHEMA_VERSION = 1

#: `meta` keys this module owns. Everything else in `meta` belongs to whoever
#: wrote it; these are the ones a reader may rely on.
META_SCHEMA_VERSION = "schema_version"
META_FRAME_PERIOD = "frame_period_s"

#: Envelope `source` vocabulary, from docs/plan.md Phase 5. Fixed and small, so
#: an out-of-vocabulary source is a detectable fault rather than a new category
#: nobody agreed to. Only `computed` is produced in this milestone; `declared`
#: and `clamped` arrive with `declare/` and `enforce/`, and all three are
#: retained separately because "a clamp is only legible if the declared and the
#: computed bound both survive" (docs/lossiness.md Retained #8).
ENVELOPE_SOURCES = ("computed", "declared", "clamped")


@dataclass(frozen=True)
class EdgeSpec:
    """What one edge type is: its layer, its endpoints, and its metric column.

    This table is the single definition of the edge vocabulary. `open_edge`
    reads the layer and the endpoint kinds off it rather than taking them from
    the caller, so there is no call site at which they can be got wrong.
    """

    layer: Layer
    src_kind: str
    dst_kind: str
    #: The one metric column this edge type carries, or `None` if it carries
    #: none. Presence is enforced both here and by a `CHECK` in the schema.
    metric: str | None


#: The edge vocabulary for this milestone (docs/plan.md Phase 5, issue #14).
#: `DECLARED`, `ADJUDICATED`, `ENFORCED` and `FOLLOWS` are Milestone 3 and are
#: deliberately absent — an edge type in the vocabulary that nothing ever emits
#: makes an empty result indistinguishable from an unimplemented one.
#:
#: `HAS_ENVELOPE` is Layer A: an envelope is computed from proprioception and
#: actuation limits alone (`reg.envelope`). The other three are Layer B without
#: exception, because each one names an entity, and where an entity is comes
#: from perception in any real system.
EDGE_SPECS: dict[str, EdgeSpec] = {
    "HAS_ENVELOPE": EdgeSpec("A", "Timestep", "Envelope", None),
    "INTERSECTS": EdgeSpec("B", "Envelope", "Entity", "overlap_area"),
    "SEPARATION": EdgeSpec("B", "RobotConfig", "Entity", "min_distance"),
    "CONTACT": EdgeSpec("B", "RobotConfig", "Entity", None),
}

#: Node kind -> (table, primary key column). Used to check that an edge's
#: endpoints exist before the edge is written.
NODE_TABLES: dict[str, tuple[str, str]] = {
    "Timestep": ("timestep", "timestep_id"),
    "Envelope": ("envelope", "envelope_id"),
    "Entity": ("entity", "entity_id"),
    "RobotConfig": ("robot_config", "config_id"),
}

_SQL_EDGE_TYPES = ", ".join(f"'{name}'" for name in EDGE_SPECS)
_SQL_NODE_KINDS = ", ".join(f"'{name}'" for name in NODE_TABLES)
_SQL_ENVELOPE_SOURCES = ", ".join(f"'{name}'" for name in ENVELOPE_SOURCES)

SCHEMA = f"""
CREATE TABLE meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- An instant that anchors at least one interval. NOT one row per frame: the
-- incremental principle (docs/plan.md Phase 5) is the entire compression story,
-- and a Timestep per frame would put 150 rows back where the graph promises ~1.
CREATE TABLE timestep (
    timestep_id TEXT    PRIMARY KEY,
    frame_id    INTEGER NOT NULL UNIQUE,
    t           REAL    NOT NULL
);

-- Stored on material change only, keyed on `envelope_hash` (reg.envelope).
CREATE TABLE envelope (
    envelope_id   TEXT PRIMARY KEY,
    envelope_hash TEXT NOT NULL,
    area          REAL NOT NULL,
    geometry_wkb  BLOB NOT NULL,
    horizon       REAL NOT NULL,
    source        TEXT NOT NULL CHECK (source IN ({_SQL_ENVELOPE_SOURCES})),
    UNIQUE (envelope_hash, source, horizon)
);

-- `geometry_wkb` is the entity's world-frame boundary and is present exactly
-- when that boundary does not move. See `insert_entity` for why a moving
-- entity's per-frame position is not stored rather than stored badly.
CREATE TABLE entity (
    entity_id    TEXT    PRIMARY KEY,
    kind         TEXT    NOT NULL,
    is_static    INTEGER NOT NULL CHECK (is_static IN (0, 1)),
    geometry_wkb BLOB,
    CHECK ((is_static = 1) = (geometry_wkb IS NOT NULL))
);

-- Created only when it anchors a retained relationship (docs/lossiness.md
-- Discarded #1). The interpolated path between two of these is gone.
CREATE TABLE robot_config (
    config_id TEXT PRIMARY KEY,
    q         TEXT NOT NULL,
    qd        TEXT NOT NULL
);

CREATE TABLE edge (
    edge_id      INTEGER PRIMARY KEY,
    type         TEXT NOT NULL CHECK (type  IN ({_SQL_EDGE_TYPES})),
    layer        TEXT NOT NULL CHECK (layer IN ('A', 'B')),
    src_kind     TEXT NOT NULL CHECK (src_kind IN ({_SQL_NODE_KINDS})),
    src_id       TEXT NOT NULL,
    dst_kind     TEXT NOT NULL CHECK (dst_kind IN ({_SQL_NODE_KINDS})),
    dst_id       TEXT NOT NULL,
    t_start      REAL NOT NULL,
    t_end        REAL NOT NULL,
    overlap_area REAL,
    min_distance REAL,
    CHECK (t_end >= t_start),
    CHECK ((type = 'INTERSECTS') = (overlap_area IS NOT NULL)),
    CHECK ((type = 'SEPARATION') = (min_distance IS NOT NULL))
);

-- Claim 3 is `WHERE layer = ?`; queries 1-4 are `WHERE type = ? AND dst_id = ?`
-- over an interval. Index what the supported question set actually asks.
CREATE INDEX edge_by_layer     ON edge (layer);
CREATE INDEX edge_by_type_dst  ON edge (type, dst_id);
CREATE INDEX edge_by_interval  ON edge (t_start, t_end);
"""


class StoreError(Exception):
    """A write the schema or the edge vocabulary refuses.

    Distinct from `sqlite3.IntegrityError` only in that it names what the caller
    got wrong. Both are failures; neither is recoverable by retrying with a
    substituted value.
    """


def layer_of(edge_type: str) -> Layer:
    """The layer an edge type belongs to. Refuses a type not in the vocabulary.

    There is no "unknown layer" and no default. An edge whose layer nobody can
    state is exactly the unusable edge docs/lossiness.md Retained #9 rules out,
    so a new edge type is a decision recorded in `EDGE_SPECS`, not something a
    call site can improvise.
    """
    spec = EDGE_SPECS.get(edge_type)
    if spec is None:
        raise StoreError(
            f"{edge_type!r} is not an edge type. Known types: "
            f"{sorted(EDGE_SPECS)}. Adding one means deciding its layer, its "
            "endpoints and its metric in reg.store.EDGE_SPECS — Claim 3 is a "
            "query over the layer tag, so an edge nobody tagged is unusable."
        )
    return spec.layer


# --------------------------------------------------------------------------
# Opening and creating
# --------------------------------------------------------------------------


def create(path: str | os.PathLike[str]) -> sqlite3.Connection:
    """Create a fresh artifact at `path` and return an open connection.

    An existing file is **replaced**, matching `reg.sim`: re-running a build over
    its own output is the normal case, and merging new rows into a stale schema
    would produce an artifact describing two runs at once. Parent directories are
    created — the caller named the path, this only makes it writable.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    put_meta(conn, META_SCHEMA_VERSION, str(SCHEMA_VERSION))
    conn.commit()
    return conn


def connect(path: str | os.PathLike[str]) -> sqlite3.Connection:
    """Open an existing artifact read-write. Refuses a file that is not one.

    "Not one" means: no `meta` table, or a `schema_version` this build does not
    understand. Both are could-not-evaluate — reading a v2 artifact with v1's
    column meanings returns numbers, and they are the wrong numbers.
    """
    path = Path(path)
    if not path.exists():
        raise StoreError(f"{path}: no such file. Nothing was created.")

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        version = get_meta(conn, META_SCHEMA_VERSION)
    except sqlite3.DatabaseError as exc:
        conn.close()
        raise StoreError(
            f"{path} is not a reg evidence graph: {exc}."
        ) from exc
    if version is None:
        conn.close()
        raise StoreError(
            f"{path} has no {META_SCHEMA_VERSION} in its meta table, so it does "
            "not say which schema it was written against. Refusing to guess."
        )
    if version != str(SCHEMA_VERSION):
        conn.close()
        raise StoreError(
            f"{path} was written against schema version {version}; this build "
            f"understands version {SCHEMA_VERSION}. The column meanings may have "
            "changed, and a query against the wrong ones returns answers rather "
            "than errors."
        )
    return conn


# --------------------------------------------------------------------------
# Geometry codec
# --------------------------------------------------------------------------


def to_wkb(geometry: BaseGeometry) -> bytes:
    """A geometry as a WKB blob. Refuses empty and invalid input.

    An empty geometry stored as an entity boundary reads downstream as "nothing
    was there", and an invalid one has an area that is not the area of any
    region. Neither is a small mistake with a loud symptom; both are silent.
    """
    if not isinstance(geometry, BaseGeometry):
        raise StoreError(
            f"to_wkb takes a shapely geometry, got {type(geometry).__name__}."
        )
    if geometry.is_empty:
        raise StoreError(
            "refusing to store an empty geometry. Read back it is a region of no "
            "extent, which clears every intersection test that meets it."
        )
    if not geometry.is_valid:
        raise StoreError(
            f"refusing to store an invalid geometry: "
            f"{shapely.is_valid_reason(geometry)}."
        )
    return shapely.to_wkb(geometry)


def from_wkb(blob: bytes) -> BaseGeometry:
    """A WKB blob back to a shapely geometry. The exact inverse of `to_wkb`."""
    if not isinstance(blob, (bytes, bytearray, memoryview)):
        raise StoreError(
            f"from_wkb takes a WKB blob, got {type(blob).__name__}. A NULL "
            "geometry column is an entity whose boundary was never stored, "
            "which is a could-not-evaluate and not an empty polygon."
        )
    return shapely.from_wkb(bytes(blob))


# --------------------------------------------------------------------------
# meta
# --------------------------------------------------------------------------


def put_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    """Record one provenance fact. Values are text; interpreting them is the
    reader's decision, exactly as in `reg.sim.parse_provenance`.

    Re-writing a key with a *different* value is refused. Provenance describes
    one run; a key that changed during the build means two runs are being
    conflated, and the last writer would win silently.
    """
    if not isinstance(key, str) or not key:
        raise StoreError(f"meta key must be a non-empty str, got {key!r}.")
    if not isinstance(value, str):
        raise StoreError(
            f"meta[{key!r}] must be a str, got {type(value).__name__}. Values are "
            "text so that reading them back is never a silent coercion."
        )
    existing = get_meta(conn, key)
    if existing is not None and existing != value:
        raise StoreError(
            f"meta[{key!r}] is already {existing!r} and would be overwritten with "
            f"{value!r}. One artifact describes one run."
        )
    conn.execute(
        "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value)
    )


def get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    """One provenance fact, or `None` if the artifact does not state it.

    `None` means the artifact is silent, which is a could-not-evaluate for every
    question about that fact. It never means "the usual value was used".
    """
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return None if row is None else str(row["value"])


def all_meta(conn: sqlite3.Connection) -> dict[str, str]:
    """The whole provenance block, in key order."""
    rows = conn.execute("SELECT key, value FROM meta ORDER BY key").fetchall()
    return {str(r["key"]): str(r["value"]) for r in rows}


# --------------------------------------------------------------------------
# Nodes
#
# Every insert is "insert, or verify what is already there is identical". The
# graph builder derives node ids from a hash of the node's contents, so a
# collision between two different nodes would merge two histories into an answer
# about neither -- the same failure `reg.world` refuses duplicate entity ids for.
# --------------------------------------------------------------------------


def _insert_node(
    conn: sqlite3.Connection,
    table: str,
    key_column: str,
    row: dict[str, object],
) -> str:
    node_id = str(row[key_column])
    existing = conn.execute(
        f"SELECT * FROM {table} WHERE {key_column} = ?", (node_id,)  # noqa: S608
    ).fetchone()
    if existing is not None:
        clash = {
            column: (existing[column], value)
            for column, value in row.items()
            if existing[column] != value
        }
        if clash:
            raise StoreError(
                f"{table}.{key_column}={node_id!r} already exists with different "
                f"contents: {clash}. Node ids are content-derived, so this is "
                "either a hash collision or two different things given one id; "
                "either way the two histories would merge into an answer about "
                "neither."
            )
        return node_id

    columns = ", ".join(row)
    placeholders = ", ".join("?" for _ in row)
    conn.execute(
        f"INSERT INTO {table} ({columns}) VALUES ({placeholders})",  # noqa: S608
        tuple(row.values()),
    )
    return node_id


def insert_timestep(
    conn: sqlite3.Connection, timestep_id: str, frame_id: int, t: float
) -> str:
    """An instant that anchors at least one interval. Idempotent."""
    return _insert_node(
        conn,
        "timestep",
        "timestep_id",
        {"timestep_id": str(timestep_id), "frame_id": int(frame_id), "t": float(t)},
    )


def insert_envelope(
    conn: sqlite3.Connection,
    envelope_id: str,
    *,
    envelope_hash: str,
    area: float,
    geometry: BaseGeometry,
    horizon: float,
    source: str,
) -> str:
    """An envelope at a material change. Idempotent on `envelope_id`.

    `area` is expected already quantized (`reg.tolerances.quantize_area`) and the
    geometry already simplified — this module stores what it is given and does
    not quantize on the caller's behalf, because a store that silently rounds
    makes the tolerance in force a property of the writer rather than of the
    contract.
    """
    if source not in ENVELOPE_SOURCES:
        raise StoreError(
            f"envelope source {source!r} is not in the vocabulary "
            f"{ENVELOPE_SOURCES}. docs/plan.md Phase 5 fixes it; an unrecognised "
            "source would make a clamped bound indistinguishable from a declared "
            "one."
        )
    return _insert_node(
        conn,
        "envelope",
        "envelope_id",
        {
            "envelope_id": str(envelope_id),
            "envelope_hash": str(envelope_hash),
            "area": float(area),
            "geometry_wkb": to_wkb(geometry),
            "horizon": float(horizon),
            "source": str(source),
        },
    )


def insert_entity(
    conn: sqlite3.Connection,
    entity_id: str,
    kind: str,
    *,
    geometry: BaseGeometry | None,
) -> str:
    """An entity in the entity set. `geometry=None` means it moves.

    WHY A MOVING ENTITY STORES NO GEOMETRY. docs/lossiness.md enumerates what is
    Retained, and an entity's absolute position per frame is not on the list: the
    supported question set asks for separations, overlaps, intersection intervals
    and set membership, all of which are edge attributes here. Storing one frame's
    disc as though it were the entity's boundary would answer "where was the
    human at t?" with a number that is right once and wrong everywhere else,
    which is worse than the refusal `NULL` produces. Discarded #8 covers it.

    "Absence of an entity from the graph is not evidence of its absence from the
    room" (Unanswerable #2) — an entity has to be *declared* into the entity set
    to leave any trace at all, which is what this call does.
    """
    return _insert_node(
        conn,
        "entity",
        "entity_id",
        {
            "entity_id": str(entity_id),
            "kind": str(kind),
            "is_static": 1 if geometry is not None else 0,
            "geometry_wkb": None if geometry is None else to_wkb(geometry),
        },
    )


def insert_robot_config(
    conn: sqlite3.Connection, config_id: str, q: str, qd: str
) -> str:
    """A joint configuration that anchors a retained relationship.

    `q` and `qd` are text, formatted by the caller. Text rather than a float
    column per joint because the joint count is a property of the robot and not
    of the schema, and because the artifact should read back exactly the digits
    the raw stream carried rather than whatever a float column round-trips to.
    """
    return _insert_node(
        conn,
        "robot_config",
        "config_id",
        {"config_id": str(config_id), "q": str(q), "qd": str(qd)},
    )


# --------------------------------------------------------------------------
# Edges
# --------------------------------------------------------------------------


def _require_node(conn: sqlite3.Connection, kind: str, node_id: str) -> None:
    table, key_column = NODE_TABLES[kind]
    row = conn.execute(
        f"SELECT 1 FROM {table} WHERE {key_column} = ?", (node_id,)  # noqa: S608
    ).fetchone()
    if row is None:
        raise StoreError(
            f"no {kind} node with id {node_id!r}. An edge to a node that does not "
            "exist is a dangling reference: every join over it returns nothing, "
            "and nothing is indistinguishable from 'the relationship never held'."
        )


def open_edge(
    conn: sqlite3.Connection,
    edge_type: str,
    src_id: str,
    dst_id: str,
    t_start: float,
    *,
    t_end: float | None = None,
    overlap_area: float | None = None,
    min_distance: float | None = None,
) -> int:
    """Insert an edge and return its `edge_id`. `t_end` defaults to `t_start`.

    That default is not an invented value: an interval observed at exactly one
    instant *is* `[t, t]`, and `extend_edge` is how it grows. It is the only
    honest starting point — an open-ended `t_end` would have to be `NULL` or an
    invented horizon, and both read as "still true" long after the relationship
    stopped holding.

    The layer and the endpoint kinds come from `EDGE_SPECS`, never from the
    caller. The metric argument for the edge type is required and the other one
    must be absent: an `INTERSECTS` with no `overlap_area` answers "how much"
    with `NULL`, which compares false against every threshold and turns an
    incident into a non-incident.
    """
    spec = EDGE_SPECS.get(edge_type)
    if spec is None:
        layer_of(edge_type)  # raises with the full vocabulary
        raise AssertionError  # pragma: no cover - layer_of always raises here

    metrics = {"overlap_area": overlap_area, "min_distance": min_distance}
    for name, value in metrics.items():
        if name == spec.metric:
            if value is None:
                raise StoreError(
                    f"a {edge_type} edge carries {name} and none was supplied. "
                    "Writing it as NULL would answer every question about the "
                    "quantity with 'no', not with 'unknown'."
                )
        elif value is not None:
            raise StoreError(
                f"a {edge_type} edge does not carry {name}, but {value!r} was "
                f"supplied. Its metric is {spec.metric!r}."
            )

    _require_node(conn, spec.src_kind, str(src_id))
    _require_node(conn, spec.dst_kind, str(dst_id))

    t_start = float(t_start)
    t_end = t_start if t_end is None else float(t_end)
    if t_end < t_start:
        raise StoreError(
            f"{edge_type} edge would span [{t_start}, {t_end}], which runs "
            "backwards. A backwards interval matches no time window, so it "
            "disappears from every timeline query instead of erroring."
        )

    cursor = conn.execute(
        """
        INSERT INTO edge (type, layer, src_kind, src_id, dst_kind, dst_id,
                          t_start, t_end, overlap_area, min_distance)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            edge_type,
            spec.layer,
            spec.src_kind,
            str(src_id),
            spec.dst_kind,
            str(dst_id),
            t_start,
            t_end,
            overlap_area,
            min_distance,
        ),
    )
    edge_id = cursor.lastrowid
    if edge_id is None:  # pragma: no cover - sqlite3 always sets it on INSERT
        raise StoreError("sqlite did not return an edge_id for the inserted edge.")
    return int(edge_id)


def extend_edge(conn: sqlite3.Connection, edge_id: int, t_end: float) -> None:
    """Extend an edge's interval to `t_end`. This is the incremental principle.

    Refuses to move `t_end` **backwards**. Shrinking an interval would silently
    delete time in which the relationship was observed to hold, and there is no
    situation in the incremental rule that calls for it — a relationship that
    stops holding gets a *new* edge, it does not retract the old one.
    """
    row = conn.execute(
        "SELECT t_start, t_end FROM edge WHERE edge_id = ?", (int(edge_id),)
    ).fetchone()
    if row is None:
        raise StoreError(f"no edge with edge_id={edge_id}.")

    t_end = float(t_end)
    if t_end < float(row["t_end"]):
        raise StoreError(
            f"edge {edge_id} already spans [{row['t_start']}, {row['t_end']}] and "
            f"extending it to {t_end} would move t_end backwards, discarding time "
            "in which the relationship was observed to hold."
        )
    conn.execute(
        "UPDATE edge SET t_end = ? WHERE edge_id = ?", (t_end, int(edge_id))
    )


def read_edges(
    conn: sqlite3.Connection,
    *,
    edge_type: str | None = None,
    layer: Literal["A", "B"] | None = None,
    dst_id: str | None = None,
) -> list[sqlite3.Row]:
    """Edges matching the filters, ordered by `(t_start, edge_id)`.

    Ordering is total and deterministic: `t_start` alone is not, because several
    relationships can transition in the same time quantum and docs/lossiness.md
    Unanswerable #5 says their *order* is not retained. `edge_id` breaks the tie
    by insertion order so that two reads of one artifact agree, without implying
    the tie-break means anything about time.
    """
    if edge_type is not None:
        layer_of(edge_type)  # refuses an unknown type rather than returning []
    clauses: list[str] = []
    params: list[object] = []
    for column, value in (("type", edge_type), ("layer", layer), ("dst_id", dst_id)):
        if value is not None:
            clauses.append(f"{column} = ?")
            params.append(value)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    return list(
        conn.execute(
            f"SELECT * FROM edge{where} ORDER BY t_start, edge_id",  # noqa: S608
            params,
        ).fetchall()
    )
