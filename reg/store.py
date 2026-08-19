"""The evidence graph's persistence layer: SQLite schema and write primitives.

    from reg import store
    conn = store.create("runs/contact.sqlite")
    store.insert_entity(conn, "obs_crate", "crate", geometry=disc)
    cfg_id = store.insert_robot_config(conn, "cfg_0", "0.0,0.0", "0.0,0.0")
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
* an envelope with neither geometry nor a `config_id` — an envelope row that
  stores no polygon and does not say what it was computed from is a row nobody
  can turn back into a region, and `reg.graph.envelope_at` would have to answer
  "no envelope" for a frame that had one. See `insert_envelope`.
* an occurrence outside the vocabulary, or one whose entity or metric does not
  match what its type is — see `OCCURRENCE_SPECS` and `insert_occurrence`.

THE RECORD TABLES STORE WHAT THE RECORD CARRIES, AND NOTHING DERIVED
--------------------------------------------------------------------
`declaration` and `verdict` (issue #45) hold the Milestone 3 records verbatim:
every field, including `prev_hash` and `mac`, exactly as the record was signed.
This module **never re-signs and never re-hashes**. It holds no keys, so it
cannot check a MAC at all — and that is the property that matters, because a
store that could recompute a MAC is a store that can quietly repair a broken
chain, which is precisely what the chain exists to make visible. A record whose
MAC does not match is stored, and `read_declarations` / `read_verdicts` hand back
a record that still fails verification under the key that signed the original.
`tests/test_graph.py` asserts that persistence does not launder it.

Reconstruction is therefore byte-exact by construction: text columns for the
hashes and the ids, `REAL` for the two floats (an IEEE-754 double round-trips
through SQLite unchanged), and the WKB stored as the record's own bytes rather
than re-serialized through shapely — a second rendering of the same polygon is
the same region and a different preimage.

THE OCCURRENCE TABLE IS A SECOND RESOLUTION, NOT A SECOND ARTIFACT
------------------------------------------------------------------
Issue #35 added `occurrence` beside `edge`. It is the same run at DSSAD's
event-level granularity — a flag, a reason, a timestamp good to a stated
resolution, and the software version present at the event (docs/prior-art.md
§9) — and it is **additive**: nothing above it changed, and every query that
read the edge layer before still reads it. `reg.bench --resolution` measures
what each of the two costs and which questions each can still answer, which is
what Claim 1 became after issue #30 refuted its original form.

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
    "OCCURRENCE_SPECS",
    "RECORD_KINDS",
    "StoreError",
    "create",
    "connect",
    "layer_of",
    "occurrence_layer",
    "put_meta",
    "get_meta",
    "all_meta",
    "insert_declaration",
    "insert_envelope",
    "attach_envelope_geometry",
    "envelope_row",
    "insert_entity",
    "insert_occurrence",
    "insert_robot_config",
    "insert_verdict",
    "open_edge",
    "extend_edge",
    "read_declarations",
    "read_edges",
    "read_occurrences",
    "read_verdicts",
    "to_wkb",
    "from_wkb",
]

#: Bumped whenever a table, column or constraint changes. It is written into
#: `meta` so a reader that meets an unfamiliar artifact can say it does not
#: understand it, rather than querying a column that has since changed meaning
#: and getting a confident wrong answer.
#:
#: 2: `envelope.geometry_wkb` became nullable and `envelope.config_id` arrived.
#: A v1 reader meeting a v2 file would read a NULL geometry as "no envelope"
#: rather than as "recompute it" (issue #28, docs/lossiness.md Discarded #9),
#: which is exactly the confident wrong answer the version exists to prevent.
#:
#: 3: the `timestep` table is gone and `HAS_ENVELOPE` runs `RobotConfig ->
#: Envelope` (issue #29, docs/lossiness.md Discarded #10). A v2 reader meeting a
#: v3 file would find `HAS_ENVELOPE` intervals covering only part of the run and
#: read the gaps as "the robot had no envelope then" rather than as "that frame
#: is not retained"; same confident wrong answer, one level up.
#:
#: 4: the `occurrence` table arrived (issue #35) — the DSSAD-aligned event layer,
#: additive beside the edges and replacing none of them. A v3 reader meeting a v4
#: file cannot see it at all, so every question the occurrence layer answers
#: would come back "this artifact records no such thing" rather than "this reader
#: does not understand this artifact".
#:
#: 5: the `declaration` and `verdict` tables arrived with the `DECLARED`,
#: `ADJUDICATED`, `ENFORCED` and `FOLLOWS` edges and the five enforcement
#: occurrence types (issue #45) — Milestone 3's records become queryable
#: evidence. `envelope.horizon` became nullable in the same change, because a
#: clamped bound is the region a verdict applied at an instant and the `Verdict`
#: record states no horizon for it. A v4 reader meeting a v5 file would read
#: `horizon` as always present and would not see the attestation layer at all,
#: so "this run had no verdicts" and "this reader cannot see verdicts" would be
#: the same answer.
SCHEMA_VERSION = 5

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


#: The node kinds a chain link may join. `FOLLOWS` is the one edge type whose
#: endpoints are polymorphic: declarations chain among themselves under the
#: policy key and verdicts among themselves under the enforcement key, so the
#: same edge type runs `Declaration -> Declaration` in one chain and
#: `Verdict -> Verdict` in the other. A separate edge type per chain would make
#: "walk the record chain" two queries that have to be kept in step.
RECORD_KINDS: frozenset[str] = frozenset({"Declaration", "Verdict"})


@dataclass(frozen=True)
class EdgeSpec:
    """What one edge type is: its layer, its endpoints, and its metric column.

    This table is the single definition of the edge vocabulary. `open_edge`
    reads the layer and the endpoint kinds off it rather than taking them from
    the caller, so there is no call site at which they can be got wrong.

    An endpoint may be a `frozenset` of kinds instead of one kind, for an edge
    type whose endpoints genuinely vary — `FOLLOWS`, and only `FOLLOWS`. The
    caller then states the kind and `open_edge` refuses anything outside the
    set; the *layer* still comes from here and is never the caller's to supply.
    """

    layer: Layer
    src_kind: str | frozenset[str]
    dst_kind: str | frozenset[str]
    #: The one metric column this edge type carries, or `None` if it carries
    #: none. Presence is enforced both here and by a `CHECK` in the schema.
    metric: str | None


#: The edge vocabulary (docs/plan.md Phase 5, issues #14 and #45).
#:
#: `HAS_ENVELOPE` is Layer A: an envelope is computed from proprioception and
#: actuation limits alone (`reg.envelope`). `INTERSECTS`, `SEPARATION` and
#: `CONTACT` are Layer B without exception, because each one names an entity, and
#: where an entity is comes from perception in any real system.
#:
#: **The four attestation edges are Layer A, every one of them, and not one names
#: an `Entity`.** That is not a coincidence and it is not a convenience: it is
#: the asymmetry docs/sufficiency.md §2 is about. A declaration is a statement
#: the policy made about itself, a verdict is enforcement's finding about a
#: commanded action, the bound in each case is a region computed from `Limits`
#: and proprioception, and the chain link is a fact about the record. None of it
#: needs to know where anybody is standing — so every attestation answer in this
#: artifact survives an uncertifiable perceiver, while every answer about who was
#: near the robot does not. `tests/test_graph.py::
#: test_layer_b_is_exactly_the_entity_naming_edges` holds the line: an edge that
#: names an `Entity` is Layer B whatever its author intended.
#:
#: `HAS_ENVELOPE` runs `RobotConfig -> Envelope` and not `Timestep -> Envelope`
#: (issue #29). docs/plan.md Phase 5's table originally said `Timestep`; it now
#: records the change, and so does this line, because it is a decision and not a
#: slip. The envelope is a deterministic function of the configuration it was
#: computed from, so the configuration is the thing it *has an envelope of*, and
#: the edge's own `t_start`/`t_end` are where time lives. A `Timestep` node was a
#: second, denser representation of time sitting beside the interval
#: representation that does the work — one row per frame, which is exactly what
#: the incremental principle forbids.
EDGE_SPECS: dict[str, EdgeSpec] = {
    "HAS_ENVELOPE": EdgeSpec("A", "RobotConfig", "Envelope", None),
    "INTERSECTS": EdgeSpec("B", "Envelope", "Entity", "overlap_area"),
    "SEPARATION": EdgeSpec("B", "RobotConfig", "Entity", "min_distance"),
    "CONTACT": EdgeSpec("B", "RobotConfig", "Entity", None),
    "DECLARED": EdgeSpec("A", "Declaration", "Envelope", None),
    "ADJUDICATED": EdgeSpec("A", "Verdict", "Declaration", None),
    "ENFORCED": EdgeSpec("A", "Verdict", "Envelope", None),
    "FOLLOWS": EdgeSpec("A", RECORD_KINDS, RECORD_KINDS, None),
}


@dataclass(frozen=True)
class OccurrenceSpec:
    """What one occurrence type is: its layer, its subject, and its metric.

    The occurrence vocabulary's single definition, the same way `EDGE_SPECS` is
    the edge vocabulary's. `insert_occurrence` reads the layer off it rather than
    taking it from the caller, so a Layer B event naming an entity cannot be
    written as Layer A by a call site in a hurry.
    """

    layer: Layer
    #: `entity` — the occurrence is about the robot's relationship to one entity
    #: and names it. `run` — it is about the record itself and names none.
    #: Presence of `entity_id` is enforced against this both here and by a
    #: `CHECK`: an `envelope_entered` with no entity says something entered
    #: something, which is not evidence about anything.
    subject: Literal["entity", "run"]
    #: What this occurrence type's `value` column holds, or `None` if it holds
    #: nothing. Presence is enforced both ways, like an edge's metric.
    metric: str | None


#: The occurrence vocabulary (issue #35, docs/prior-art.md §9). **Fixed and
#: small, like `ENVELOPE_SOURCES` and `EDGE_SPECS`**: an out-of-vocabulary
#: occurrence is a detectable fault rather than a new category nobody agreed to.
#:
#: The layers split exactly where the project's does: the run's own ends are
#: Layer A (they are facts about the record), and everything naming an entity is
#: Layer B without exception, because where an entity is comes from perception in
#: any real system.
#:
#: The five enforcement types arrived with issue #45 and are the **first Layer A
#: occurrences that are about something happening**, which is what lets the
#: coarse layer answer an attestation question at all. Issue #35 left them out
#: because no fixture produced a verdict; `reg.enforce` produces them now.
#: `action_clamped` is emitted by the `declared_violation` fixture today; the
#: other four are emitted by verdict streams the enforcer produces but that no
#: *scenario* yet drives, which is issue #46's subject — so they are covered by
#: `tests/test_graph.py` against real signed verdicts rather than by a fixture,
#: and the distinction is written here rather than left to be inferred from a
#: zero count.
OCCURRENCE_SPECS: dict[str, OccurrenceSpec] = {
    "run_began": OccurrenceSpec("A", "run", None),
    "run_ended": OccurrenceSpec("A", "run", None),
    "envelope_entered": OccurrenceSpec("B", "entity", None),
    "envelope_left": OccurrenceSpec("B", "entity", None),
    "contact_began": OccurrenceSpec("B", "entity", None),
    "contact_ended": OccurrenceSpec("B", "entity", None),
    "closest_approach": OccurrenceSpec("B", "entity", "min_distance_m"),
    "declaration_vetoed": OccurrenceSpec("A", "run", None),
    "action_clamped": OccurrenceSpec("A", "run", None),
    "safe_state_entered": OccurrenceSpec("A", "run", None),
    "reintegrated": OccurrenceSpec("A", "run", None),
    "escalation_failed": OccurrenceSpec("A", "run", None),
}

#: Node kind -> (table, primary key column). Used to check that an edge's
#: endpoints exist before the edge is written.
#:
#: `Occurrence` is in here so it is counted, attributed and checked like every
#: other node kind, and **not** because any edge points at one: no `EdgeSpec`
#: names it. The occurrence layer is additive (issue #35) — it sits beside the
#: edges rather than joining them, and giving it an edge type would be inventing
#: a relationship the fixtures do not produce.
NODE_TABLES: dict[str, tuple[str, str]] = {
    "Envelope": ("envelope", "envelope_id"),
    "Entity": ("entity", "entity_id"),
    "RobotConfig": ("robot_config", "config_id"),
    "Occurrence": ("occurrence", "occurrence_id"),
    "Declaration": ("declaration", "declaration_id"),
    "Verdict": ("verdict", "verdict_id"),
}

_SQL_EDGE_TYPES = ", ".join(f"'{name}'" for name in EDGE_SPECS)
_SQL_NODE_KINDS = ", ".join(f"'{name}'" for name in NODE_TABLES)
_SQL_ENVELOPE_SOURCES = ", ".join(f"'{name}'" for name in ENVELOPE_SOURCES)
_SQL_OCCURRENCE_TYPES = ", ".join(f"'{name}'" for name in OCCURRENCE_SPECS)
_SQL_OCCURRENCE_ENTITY_TYPES = ", ".join(
    f"'{name}'" for name, spec in OCCURRENCE_SPECS.items() if spec.subject == "entity"
)
_SQL_OCCURRENCE_VALUED_TYPES = ", ".join(
    f"'{name}'" for name, spec in OCCURRENCE_SPECS.items() if spec.metric is not None
)

SCHEMA = f"""
CREATE TABLE meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- THERE IS NO `timestep` TABLE. Every edge carries `t_start` and `t_end`, so
-- time is already an interval here; a node per instant would be a second and
-- denser representation of it, one row per frame, which is the thing the
-- incremental principle (docs/plan.md Phase 5) exists to prevent. Nothing in
-- docs/plan.md Phase 7's query set needs a per-frame anchor: the two questions
-- that name frames at all ("frames at risk", "27 frames") divide an interval by
-- `frame_period_s` in `meta`, which is recorded once and checked uniform at
-- build time. Issue #29; docs/lossiness.md Discarded #10.

-- Created only when it anchors a retained relationship (docs/lossiness.md
-- Discarded #1), or when an envelope the artifact retains was computed from it.
-- The interpolated path between two of these is gone.
CREATE TABLE robot_config (
    config_id TEXT PRIMARY KEY,
    q         TEXT NOT NULL,
    qd        TEXT NOT NULL
);

-- A row per envelope the artifact retains, keyed on `envelope_hash`
-- (reg.envelope). NOT one per frame and not one per material change: a moving
-- arm has a materially different envelope on every frame, so "on material
-- change" is "on every frame" for exactly the runs that matter, and it put the
-- node count back in step with the frame count (issue #29). The rule is
-- `reg.graph.ENVELOPE_RETENTION`, it is recorded in `meta`, and it keeps the
-- envelope where it anchors something — where an `INTERSECTS` edge names it,
-- where an entity relationship transitions, and at the two ends of the run.
-- `geometry_wkb` is retained on a second and narrower rule again
-- (docs/lossiness.md Discarded #9, issue #28).
--
-- WHY THE GEOMETRY MAY BE NULL. The polygon is a deterministic function of
-- `(q, qd, horizon, n_samples, envelope_seed, substep_dt)` — the config this
-- row names plus four numbers in `meta` — so storing it on every frame stores
-- the same information twice, once cheaply and once expensively. It is retained
-- only where it is evidence in its own right: `reg.graph.GEOMETRY_RETENTION`
-- states the rule, `reg.graph.envelope_at` is the reader that makes the absence
-- invisible, and the artifact records the rule in `meta` so nothing has to
-- infer it from the pattern of NULLs.
--
-- `config_id` is what makes that recoverable, so the CHECK requires one or the
-- other: a row with neither stores no region and names nothing to recompute one
-- from, and a query hitting it could only answer "no envelope at t", which is
-- indistinguishable from a frame that genuinely had none.
--
-- WHY THE HORIZON MAY BE NULL, AND ONLY FOR A CLAMP. A `computed` envelope was
-- integrated over one, and a `declared` envelope carries the declaration's
-- validity window — the interval the policy claimed its body would stay inside
-- the region. A `clamped` envelope has neither: it is the bound enforcement
-- applied to one commanded action at one instant, and the `Verdict` record
-- states no horizon for it (docs/plan.md Phase 4). NULL is that record's silence
-- carried through rather than a plausible number invented at the write.
CREATE TABLE envelope (
    envelope_id   TEXT PRIMARY KEY,
    envelope_hash TEXT NOT NULL,
    area          REAL NOT NULL,
    geometry_wkb  BLOB,
    config_id     TEXT REFERENCES robot_config (config_id),
    horizon       REAL,
    source        TEXT NOT NULL CHECK (source IN ({_SQL_ENVELOPE_SOURCES})),
    UNIQUE (envelope_hash, source, horizon),
    CHECK (geometry_wkb IS NOT NULL OR config_id IS NOT NULL),
    CHECK ((horizon IS NULL) = (source = 'clamped'))
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

-- THE ATTESTATION RECORDS (issue #45). Milestone 3's `Declaration` and
-- `Verdict`, stored field for field as `reg.declare` and `reg.enforce` signed
-- them. Columns are the dataclass fields, so that reading a row back and
-- reconstructing the record is a rename and nothing else — a store that had to
-- transform a field on the way out would be a store whose output is a different
-- preimage from the one the MAC covers.
--
-- `mac` and `prev_hash` are stored and never recomputed. This module holds no
-- keys; it cannot tell a good MAC from a bad one, and that is the correct
-- capability for it to have. What it must never do is make a bad one verify.
--
-- `seq` is NOT unique here, unlike `occurrence.seq`. Reuse or regression of a
-- declaration's `seq` is the `replay_or_reorder` fault in Phase 4's taxonomy —
-- an artifact that could not hold the record that triggered a fault could not
-- hold the evidence for it either.
--
-- WHY THERE IS NO `CHECK (action_class IN (...))`, AND NONE ON `outcome` OR
-- `fault` BELOW. The three vocabularies are defined once, in
-- `reg.declare.ACTION_CLASSES` and `reg.enforce.OUTCOMES` / `FAULTS`, and
-- restating them here would be a second copy — which is how a value becomes a
-- detectable fault on one side and invisible on the other. Importing them is
-- what this module cannot do: `reg.declare` reaches `reg.stream` through
-- `reg.chain`, `reg.query` imports this module, and Claim 2's "answered from
-- the graph alone" is enforced as a property of the import graph
-- (`tests/test_query.py`). So the vocabulary check lives at both ends of the
-- record's life instead: the dataclasses refuse an out-of-vocabulary value at
-- construction, and `read_declarations` / `read_verdicts` refuse to reconstruct
-- a row carrying one. A value that reached these columns without passing a
-- record — which means raw SQL, which means tampering — is a loud
-- could-not-evaluate on the way out and never a quietly accepted row.
CREATE TABLE declaration (
    declaration_id        TEXT PRIMARY KEY,
    seq                   INTEGER NOT NULL CHECK (seq >= 0),
    t_issued              REAL    NOT NULL,
    horizon               REAL    NOT NULL CHECK (horizon > 0),
    action_class          TEXT    NOT NULL,
    declared_envelope_wkb BLOB    NOT NULL,
    prev_hash             TEXT    NOT NULL,
    mac                   TEXT    NOT NULL
);

-- `declaration_id` is nullable and its absence is a *finding*, not a gap: it is
-- what `no_declaration` and `watchdog_expiry` look like in the record. A verdict
-- that does name one names a declaration this artifact holds — `insert_verdict`
-- refuses a dangling reference, because an `ADJUDICATED` edge pointing at
-- nothing is an audit answer nobody can check.
CREATE TABLE verdict (
    verdict_id           TEXT    PRIMARY KEY,
    declaration_id       TEXT    REFERENCES declaration (declaration_id),
    seq                  INTEGER NOT NULL CHECK (seq >= 0),
    t                    REAL    NOT NULL,
    outcome              TEXT    NOT NULL,
    fault                TEXT,
    clamped_envelope_wkb BLOB,
    prev_hash            TEXT    NOT NULL,
    mac                  TEXT    NOT NULL,
    -- The two invariants `Verdict.__post_init__` enforces, restated where the
    -- rows live: a PERMIT with a fault says "allowed, and here is what went
    -- wrong", and a CLAMP with no bound says "I limited it to nothing in
    -- particular". Both are could-not-evaluate wearing a decision's clothes.
    -- These name two outcomes rather than enumerating the four — the invariant
    -- is what is being stated, not the vocabulary, which is `reg.enforce`'s.
    CHECK ((outcome = 'PERMIT') = (fault IS NULL)),
    CHECK ((outcome = 'CLAMP') = (clamped_envelope_wkb IS NOT NULL))
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

-- THE OCCURRENCE LAYER (issue #35). An event-level view of the same run, in the
-- shape UN R157's DSSAD mandates for automated driving — the only mandated
-- evidence recorder for autonomy that exists (docs/prior-art.md §9). It is
-- **additive**: the edge layer above is unchanged, every existing query still
-- reads it, and the two are two resolutions of one run rather than two builds.
--
-- The columns are DSSAD's data elements, named so the mapping is legible to a
-- reader who knows the regulation:
--
--   `type`        the occurrence flag — which listed event this is
--   `reason`      DSSAD's "reason for the occurrence, where applicable"
--   `t`           the timestamp, at the resolution recorded in
--                 meta[occurrence_time_resolution_s] (DSSAD states ±1.0 s)
--   `sw_version`  DSSAD's **R157SWIN**, the software version identifier present
--                 when the event occurred, in this project's terms: the `reg`
--                 version plus a digest binding the envelope parameters that
--                 produced the run, both of which are also in `meta` in full.
--
-- **There is no `date` column, and the omission is deliberate.** DSSAD records
-- `yyyy/mm/dd` because a car's recorder has a clock. This artifact must be
-- byte-reproducible from its seeds (docs/plan.md, determinism), and a wall-clock
-- date is exactly the ambient value that would break that. What replaces it is
-- the run's own time base plus the source stream's provenance block, both in
-- `meta`. An assessor gets "when in this run" and "which run"; they do not get
-- "which afternoon", and this comment is where that is said rather than left to
-- be discovered as a missing column.
--
-- `seq` is emission order, and it is what keeps two events inside one resolution
-- quantum two rows. Coarsening the timestamp loses *when* they happened relative
-- to each other, which is the cost being measured; it must not silently lose one
-- of them, which would be a different and much worse thing.
CREATE TABLE occurrence (
    occurrence_id TEXT    PRIMARY KEY,
    seq           INTEGER NOT NULL UNIQUE,
    type          TEXT    NOT NULL CHECK (type IN ({_SQL_OCCURRENCE_TYPES})),
    layer         TEXT    NOT NULL CHECK (layer IN ('A', 'B')),
    reason        TEXT    NOT NULL,
    t             REAL    NOT NULL,
    entity_id     TEXT    REFERENCES entity (entity_id),
    value         REAL,
    sw_version    TEXT    NOT NULL,
    CHECK ((type IN ({_SQL_OCCURRENCE_ENTITY_TYPES})) = (entity_id IS NOT NULL)),
    CHECK ((type IN ({_SQL_OCCURRENCE_VALUED_TYPES})) = (value IS NOT NULL))
);

-- Claim 3 is `WHERE layer = ?`; queries 1-4 are `WHERE type = ? AND dst_id = ?`
-- over an interval. Index what the supported question set actually asks.
CREATE INDEX edge_by_layer     ON edge (layer);
CREATE INDEX edge_by_type_dst  ON edge (type, dst_id);
CREATE INDEX edge_by_interval  ON edge (t_start, t_end);

-- The occurrence layer is asked "which events of this type, for this entity",
-- which is the same shape as `edge_by_type_dst` one layer up.
CREATE INDEX occurrence_by_type ON occurrence (type, entity_id);
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


def occurrence_layer(occurrence_type: str) -> Layer:
    """The layer an occurrence type belongs to. Refuses one not in the vocabulary.

    The same rule as `layer_of`, for the same reason, plus one specific to this
    layer: the occurrence vocabulary is the artifact's claim about *what kinds of
    event it would have recorded had they happened*. A type invented at a call
    site makes the absence of that event unreadable — nobody can tell "it did not
    happen" from "this build had no name for it".
    """
    spec = OCCURRENCE_SPECS.get(occurrence_type)
    if spec is None:
        raise StoreError(
            f"{occurrence_type!r} is not an occurrence type. Known types: "
            f"{sorted(OCCURRENCE_SPECS)}. The vocabulary is fixed and small on "
            "purpose (docs/prior-art.md §9): an out-of-vocabulary occurrence is "
            "a detectable fault, not a new row type. Adding one means deciding "
            "its layer, its subject and its metric in "
            "reg.store.OCCURRENCE_SPECS — and having a fixture that produces it."
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


def insert_envelope(
    conn: sqlite3.Connection,
    envelope_id: str,
    *,
    envelope_hash: str,
    area: float,
    geometry: BaseGeometry | None,
    config_id: str | None,
    horizon: float | None,
    source: str,
) -> str:
    """An envelope the artifact retains. Idempotent on `envelope_id`.

    `area` is expected already quantized (`reg.tolerances.quantize_area`) and the
    geometry already simplified — this module stores what it is given and does
    not quantize on the caller's behalf, because a store that silently rounds
    makes the tolerance in force a property of the writer rather than of the
    contract.

    `geometry` and `config_id` are both required arguments and either may be
    `None`, but not both. Neither has a default: "store the polygon" and
    "recompute it from this configuration" are different retention decisions with
    different costs, and a caller that did not state which one it made would have
    the schema make it silently. Passing both is normal — the geometry is what a
    reader gets, the config is what makes the *next* build able to check it.

    `horizon` is `None` for exactly one source: `clamped`. The `Verdict` record
    states no horizon for the bound it applied, so there is none to store, and
    the schema's `CHECK` ties the two together in both directions — a clamped
    bound carrying a horizon would be reporting a validity window nobody wrote
    down, and a computed or declared envelope missing one would be silently
    dropping the interval its region is a claim about.

    Re-inserting an id whose row already exists fills in a geometry or a
    `config_id` the first insert left `NULL`, and refuses a *different* value for
    any scalar column. A second `config_id` for a row that already has one is
    kept out rather than refused: the id is derived from the envelope hash, so
    two configurations reaching it produce the same polygon to
    `reg.envelope.HASH_COORD_PRECISION`, and recomputation from either yields it.
    """
    if source not in ENVELOPE_SOURCES:
        raise StoreError(
            f"envelope source {source!r} is not in the vocabulary "
            f"{ENVELOPE_SOURCES}. docs/plan.md Phase 5 fixes it; an unrecognised "
            "source would make a clamped bound indistinguishable from a declared "
            "one."
        )
    if geometry is None and config_id is None:
        raise StoreError(
            f"envelope {envelope_id!r} would be stored with neither geometry nor "
            "a config_id. Then it holds no region and names nothing to recompute "
            "one from, so every query for the envelope in force at that time "
            "answers 'there was none' — which is what a frame with no envelope "
            "at all looks like."
        )
    if (horizon is None) != (source == "clamped"):
        raise StoreError(
            f"envelope {envelope_id!r} has source={source!r} and "
            f"horizon={horizon!r}. A clamped bound is the region applied to one "
            "commanded action and the Verdict record states no horizon for it, so "
            "it is stored as NULL; a computed or a declared envelope has one and "
            "storing it without would drop the interval its region is a claim "
            "about. Neither direction is a value to invent here."
        )

    envelope_id = str(envelope_id)
    scalars = {
        "envelope_id": envelope_id,
        "envelope_hash": str(envelope_hash),
        "area": float(area),
        "horizon": None if horizon is None else float(horizon),
        "source": str(source),
    }

    existing = conn.execute(
        "SELECT * FROM envelope WHERE envelope_id = ?", (envelope_id,)
    ).fetchone()
    if existing is None:
        row = {
            **scalars,
            "geometry_wkb": None if geometry is None else to_wkb(geometry),
            "config_id": None if config_id is None else str(config_id),
        }
        columns = ", ".join(row)
        placeholders = ", ".join("?" for _ in row)
        conn.execute(
            f"INSERT INTO envelope ({columns}) VALUES ({placeholders})",  # noqa: S608
            tuple(row.values()),
        )
        return envelope_id

    clash = {
        column: (existing[column], value)
        for column, value in scalars.items()
        if existing[column] != value
    }
    if clash:
        raise StoreError(
            f"envelope.envelope_id={envelope_id!r} already exists with different "
            f"contents: {clash}. Node ids are content-derived, so this is either "
            "a hash collision or two different things given one id; either way "
            "the two histories would merge into an answer about neither."
        )
    if config_id is not None and existing["config_id"] is None:
        conn.execute(
            "UPDATE envelope SET config_id = ? WHERE envelope_id = ?",
            (str(config_id), envelope_id),
        )
    if geometry is not None:
        attach_envelope_geometry(conn, envelope_id, geometry)
    return envelope_id


def attach_envelope_geometry(
    conn: sqlite3.Connection, envelope_id: str, geometry: BaseGeometry
) -> None:
    """Store the polygon on an envelope row that was written without one.

    The retention rule (`reg.graph.GEOMETRY_RETENTION`) marks a frame as evidence
    for a reason that is only known one frame later — an interval ends at the
    last instant it held — so the row is written when the envelope changes and
    the geometry is attached when the run turns out to need it. Doing it the
    other way round would mean holding the whole stream in memory to decide.

    Refuses an unknown id, and refuses to *replace* a geometry that is already
    stored. Two different polygons under one content-derived id is a collision;
    overwriting would leave the artifact holding whichever one was written last,
    with nothing to say the other existed.
    """
    envelope_id = str(envelope_id)
    row = conn.execute(
        "SELECT geometry_wkb FROM envelope WHERE envelope_id = ?", (envelope_id,)
    ).fetchone()
    if row is None:
        raise StoreError(
            f"no envelope with envelope_id={envelope_id!r} to attach geometry to. "
            "An envelope row is written when the envelope changes; attaching to "
            "an id that was never written means the geometry belongs to a frame "
            "the artifact has no record of."
        )
    blob = to_wkb(geometry)
    if row["geometry_wkb"] is not None:
        if bytes(row["geometry_wkb"]) != blob:
            raise StoreError(
                f"envelope {envelope_id!r} already stores a different geometry. "
                "The id is derived from the envelope hash, so two distinct "
                "polygons under it is a collision, not an update."
            )
        return
    conn.execute(
        "UPDATE envelope SET geometry_wkb = ? WHERE envelope_id = ?",
        (blob, envelope_id),
    )


def envelope_row(
    conn: sqlite3.Connection, envelope_id: str
) -> sqlite3.Row | None:
    """One envelope row, or `None` if the artifact has no such envelope.

    `None` is a could-not-evaluate — the artifact holds no envelope under that
    id — and is never an empty region. Readers get the row rather than the
    geometry because `geometry_wkb` being `NULL` is a fact about *how the
    artifact was written*, and the decision of what to do about it belongs to
    `reg.graph.envelope_at`, which can recompute.
    """
    return conn.execute(
        "SELECT * FROM envelope WHERE envelope_id = ?", (str(envelope_id),)
    ).fetchone()


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


def insert_occurrence(
    conn: sqlite3.Connection,
    occurrence_id: str,
    *,
    seq: int,
    occurrence_type: str,
    reason: str,
    t: float,
    entity_id: str | None,
    value: float | None,
    sw_version: str,
) -> str:
    """One DSSAD-shaped occurrence. Every element required, none defaulted.

    `entity_id` and `value` are required *arguments* and either may be `None`
    where the type says so — `insert_envelope`'s discipline, for the same reason:
    "this event names no entity" and "I forgot to say which entity" must not be
    the same call.

    `layer` is never taken from the caller; it comes from `OCCURRENCE_SPECS`.

    Args:
        seq: emission order, unique within the artifact. It is what keeps two
            events inside one timestamp quantum two rows.
        reason: DSSAD's reason element, as prose. Non-empty: an occurrence whose
            reason is blank records that something happened and nothing about
            what, which is the row an assessor cannot use.
        t: the timestamp, **already rounded to the artifact's occurrence
            resolution by the caller**. This module stores what it is given and
            does not quantize on anyone's behalf, exactly as it does not round
            `area` — a store that silently coarsens makes the resolution in force
            a property of the writer rather than of the record.
        sw_version: DSSAD's `R157SWIN` in this project's terms — the software
            version identifier present when the event occurred.

    Raises:
        StoreError: an unknown type, a blank reason or `sw_version`, an entity
            named by a type that has no subject (or missing from one that does),
            a value on a type that carries none (or missing from one that does),
            or an `entity_id` no `entity` row matches.
    """
    spec = OCCURRENCE_SPECS.get(occurrence_type)
    if spec is None:
        occurrence_layer(occurrence_type)  # raises with the full vocabulary
        raise AssertionError  # pragma: no cover - occurrence_layer always raises

    if not isinstance(reason, str) or not reason.strip():
        raise StoreError(
            f"a {occurrence_type} occurrence was written with reason={reason!r}. "
            "DSSAD records the reason for an occurrence alongside the flag; a "
            "blank one leaves a row saying an event happened and nothing about "
            "which condition produced it."
        )
    if not isinstance(sw_version, str) or not sw_version.strip():
        raise StoreError(
            f"a {occurrence_type} occurrence was written with "
            f"sw_version={sw_version!r}. That is DSSAD's R157SWIN element: an "
            "occurrence not bound to the software that produced it cannot be "
            "attributed to a build, which is the one thing the element exists "
            "for."
        )

    if spec.subject == "entity":
        if entity_id is None:
            raise StoreError(
                f"a {occurrence_type} occurrence names an entity and none was "
                "supplied. It is an event *about* something, and one that names "
                "nothing says something happened to somebody."
            )
        _require_node(conn, "Entity", str(entity_id))
    elif entity_id is not None:
        raise StoreError(
            f"a {occurrence_type} occurrence is about the run and names no "
            f"entity, but entity_id={entity_id!r} was supplied. Recording it "
            "would put an event in that entity's history that is not about it."
        )

    if spec.metric is not None and value is None:
        raise StoreError(
            f"a {occurrence_type} occurrence carries {spec.metric} and none was "
            "supplied. Writing it as NULL would answer every question about the "
            "quantity with 'no', not with 'unknown'."
        )
    if spec.metric is None and value is not None:
        raise StoreError(
            f"a {occurrence_type} occurrence carries no value, but {value!r} was "
            "supplied. A number in a column nobody can name the units of is not "
            "evidence."
        )

    return _insert_node(
        conn,
        "occurrence",
        "occurrence_id",
        {
            "occurrence_id": str(occurrence_id),
            "seq": int(seq),
            "type": str(occurrence_type),
            "layer": spec.layer,
            "reason": str(reason),
            "t": float(t),
            "entity_id": None if entity_id is None else str(entity_id),
            "value": None if value is None else float(value),
            "sw_version": str(sw_version),
        },
    )


def read_occurrences(
    conn: sqlite3.Connection,
    *,
    occurrence_type: str | None = None,
    entity_id: str | None = None,
    layer: Literal["A", "B"] | None = None,
) -> list[sqlite3.Row]:
    """Occurrences matching the filters, ordered by `(t, seq)`.

    `t` alone is not a total order at this layer and is much further from being
    one than at the edge layer: the whole point of the occurrence timestamp is
    that it is coarse, so several events routinely share one. `seq` breaks the
    tie by emission order so two reads of one artifact agree — without implying
    that the tie-break carries timing information the record does not have.
    """
    if occurrence_type is not None:
        occurrence_layer(occurrence_type)  # refuses an unknown type, not []
    clauses: list[str] = []
    params: list[object] = []
    for column, value in (
        ("type", occurrence_type),
        ("entity_id", entity_id),
        ("layer", layer),
    ):
        if value is not None:
            clauses.append(f"{column} = ?")
            params.append(value)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    return list(
        conn.execute(
            f"SELECT * FROM occurrence{where} ORDER BY t, seq",  # noqa: S608
            params,
        ).fetchall()
    )


# --------------------------------------------------------------------------
# The attestation records (issue #45).
#
# Two functions in and two out, and the only thing that happens in between is a
# rename. Everything that could make a stored record differ from the record that
# was signed — a re-serialized polygon, a reformatted float, a recomputed MAC —
# is a thing this module deliberately does not do. See the module header.
# --------------------------------------------------------------------------


def _record_types() -> tuple[type, type]:
    """`(Declaration, Verdict)`, imported here and not at module scope.

    `reg.declare` reaches `reg.stream` through `reg.chain` — the canonical
    serialization commits floats at the raw stream's own precision, deliberately
    (`reg/chain.py`). `reg.query` imports *this* module, and Claim 2's "answered
    from the graph alone" is held as a property of the import graph rather than
    as a promise: `tests/test_query.py` fails if `import reg.query` puts the
    stream reader in `sys.modules` by any route, including this one.

    So the record classes are imported where they are used. It is the same move
    `reg.graph._resolve_world` makes for the same kind of reason, and it costs
    one dict lookup per call.
    """
    from reg.declare import Declaration
    from reg.enforce import Verdict

    return Declaration, Verdict


def insert_declaration(conn: sqlite3.Connection, declaration: object) -> str:
    """Store one `Declaration` verbatim. Idempotent on `declaration_id`.

    **This does not check the MAC, and it cannot.** The store holds no keys. A
    declaration whose MAC does not match is stored exactly as it arrived and
    comes back out of `read_declarations` still failing verification under the
    key that signed the original — persistence is not an opportunity to launder
    a record, and a store able to recompute a MAC is a store able to repair a
    chain nobody should be able to repair.

    Raises:
        StoreError: the argument is not a `Declaration`, or an id already in the
            artifact carries different contents. The second is either a hash
            collision or two records given one id, and either way the two
            histories would merge into an answer about neither.
    """
    declaration_type, _ = _record_types()
    if not isinstance(declaration, declaration_type):
        raise StoreError(
            f"insert_declaration takes a reg.declare.Declaration, got "
            f"{type(declaration).__name__}. The record is what is stored; an "
            "object that resembles one has not been through the validation that "
            "makes it a record."
        )
    return _insert_node(
        conn,
        "declaration",
        "declaration_id",
        {
            "declaration_id": declaration.declaration_id,
            "seq": int(declaration.seq),
            "t_issued": float(declaration.t_issued),
            "horizon": float(declaration.horizon),
            "action_class": declaration.action_class,
            "declared_envelope_wkb": declaration.declared_envelope,
            "prev_hash": declaration.prev_hash,
            "mac": declaration.mac,
        },
    )


def insert_verdict(conn: sqlite3.Connection, verdict: object) -> str:
    """Store one `Verdict` verbatim. Idempotent on `verdict_id`.

    A verdict naming a declaration is refused unless that declaration is already
    in the artifact: an `ADJUDICATED` edge to a record nobody holds is an audit
    answer nobody can check, and the join that would read it returns nothing —
    which is indistinguishable from "this declaration was never adjudicated".
    Store the declarations of a run before its verdicts.

    A verdict naming *no* declaration is stored as it stands. `None` there is a
    finding rather than a gap: it is what `no_declaration` and `watchdog_expiry`
    look like in the record.

    Like `insert_declaration`, this checks no MAC and recomputes no hash.

    Raises:
        StoreError: the argument is not a `Verdict`, it names a declaration this
            artifact does not hold, or an id already present carries different
            contents.
    """
    _, verdict_type = _record_types()
    if not isinstance(verdict, verdict_type):
        raise StoreError(
            f"insert_verdict takes a reg.enforce.Verdict, got "
            f"{type(verdict).__name__}."
        )
    if verdict.declaration_id is not None:
        _require_node(conn, "Declaration", verdict.declaration_id)
    return _insert_node(
        conn,
        "verdict",
        "verdict_id",
        {
            "verdict_id": verdict.verdict_id,
            "declaration_id": verdict.declaration_id,
            "seq": int(verdict.seq),
            "t": float(verdict.t),
            "outcome": verdict.outcome,
            "fault": verdict.fault,
            "clamped_envelope_wkb": verdict.clamped_envelope,
            "prev_hash": verdict.prev_hash,
            "mac": verdict.mac,
        },
    )


def _record_bytes(value: object, column: str, record_id: str) -> bytes:
    if not isinstance(value, (bytes, bytearray, memoryview)):
        raise StoreError(
            f"{column} of record {record_id!r} is a {type(value).__name__}, not a "
            "WKB blob. The record's geometry is bytes and is stored as the bytes "
            "it was signed with; anything else here means the row was not written "
            "by this module."
        )
    return bytes(value)


def read_declarations(conn: sqlite3.Connection) -> list:
    """Every stored declaration, reconstructed, ordered by `(seq, declaration_id)`.

    `seq` is the chain's own order and is what the record commits to; the id
    breaks a tie, because a replayed `seq` is a fault this artifact is required
    to be able to hold rather than a state it may refuse. The order is total, so
    two reads of one artifact agree.

    What comes back is the record as it was signed, so
    `reg.declare.verify_declaration` gives the same answer it gave before the
    record was written. That round trip is the whole reason the columns are the
    dataclass fields.

    Raises:
        StoreError: a row cannot be reconstructed — a malformed MAC, an
            unreadable envelope, a value outside a vocabulary. Each is a
            could-not-evaluate about a record this artifact holds, and it is
            raised rather than skipped: a reader that silently dropped it would
            report a shorter chain with no break in it.
    """
    declaration_type, _ = _record_types()
    rows = conn.execute(
        "SELECT * FROM declaration ORDER BY seq, declaration_id"
    ).fetchall()
    out: list = []
    for row in rows:
        record_id = str(row["declaration_id"])
        try:
            out.append(
                declaration_type(
                    declaration_id=record_id,
                    seq=int(row["seq"]),
                    t_issued=float(row["t_issued"]),
                    horizon=float(row["horizon"]),
                    action_class=str(row["action_class"]),
                    declared_envelope=_record_bytes(
                        row["declared_envelope_wkb"],
                        "declared_envelope_wkb",
                        record_id,
                    ),
                    prev_hash=str(row["prev_hash"]),
                    mac=str(row["mac"]),
                )
            )
        except ValueError as exc:
            raise StoreError(
                f"declaration row {record_id!r} cannot be reconstructed as the "
                f"record it claims to be: {exc}"
            ) from None
    return out


def read_verdicts(conn: sqlite3.Connection) -> list:
    """Every stored verdict, reconstructed, ordered by `(seq, verdict_id)`.

    The same contract as `read_declarations`, under the enforcement key. Note
    that this is **not** one row per declaration: a verdict is per commanded
    action, so one declaration is adjudicated repeatedly and a run routinely
    holds tens of verdicts naming the same `declaration_id` with different
    outcomes (`reg.enforce`, module header).
    """
    _, verdict_type = _record_types()
    rows = conn.execute("SELECT * FROM verdict ORDER BY seq, verdict_id").fetchall()
    out: list = []
    for row in rows:
        record_id = str(row["verdict_id"])
        clamped = row["clamped_envelope_wkb"]
        try:
            out.append(
                verdict_type(
                    verdict_id=record_id,
                    declaration_id=(
                        None
                        if row["declaration_id"] is None
                        else str(row["declaration_id"])
                    ),
                    seq=int(row["seq"]),
                    t=float(row["t"]),
                    outcome=str(row["outcome"]),
                    fault=None if row["fault"] is None else str(row["fault"]),
                    clamped_envelope=(
                        None
                        if clamped is None
                        else _record_bytes(
                            clamped, "clamped_envelope_wkb", record_id
                        )
                    ),
                    prev_hash=str(row["prev_hash"]),
                    mac=str(row["mac"]),
                )
            )
        except ValueError as exc:
            raise StoreError(
                f"verdict row {record_id!r} cannot be reconstructed as the record "
                f"it claims to be: {exc}"
            ) from None
    return out


def insert_robot_config(
    conn: sqlite3.Connection, config_id: str, q: str, qd: str
) -> str:
    """A joint configuration that anchors a retained relationship, or an envelope.

    "Or an envelope" is issue #28: an envelope whose geometry was discarded is
    recomputed from the configuration it was computed from, so that configuration
    has to survive. It is the cheaper half of the same information — a few dozen
    characters of joint text against a WKB polygon.

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


def _endpoint_kind(
    spec_kind: str | frozenset[str], given: str | None, edge_type: str, side: str
) -> str:
    """The node kind for one end of an edge. From the spec unless it says to ask.

    A fixed kind is not the caller's to state: passing one that disagrees is
    refused rather than honoured, because the spec is the vocabulary's single
    definition. A polymorphic one — `FOLLOWS`, and only `FOLLOWS` — must be
    stated, and must be inside the set. There is no fallback to a first or a
    likeliest kind: an edge stored against the wrong table is a dangling
    reference that every join reads as "the relationship never held".
    """
    if isinstance(spec_kind, str):
        if given is not None and given != spec_kind:
            raise StoreError(
                f"a {edge_type} edge always runs from a {spec_kind} on the "
                f"{side} side, but {given!r} was supplied. The endpoint kinds "
                "come from EDGE_SPECS, not from the call site."
            )
        return spec_kind
    if given is None:
        raise StoreError(
            f"a {edge_type} edge joins any of {sorted(spec_kind)} on the {side} "
            f"side, so {side}_kind has to be stated and there is no default to "
            "fall back on. A chain link stored against the wrong table points at "
            "nothing, and a join over it returns nothing — which reads as 'these "
            "records do not follow one another'."
        )
    if given not in spec_kind:
        raise StoreError(
            f"a {edge_type} edge cannot run from a {given!r} on the {side} side; "
            f"the record kinds are {sorted(spec_kind)}."
        )
    return given


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
    src_kind: str | None = None,
    dst_kind: str | None = None,
) -> int:
    """Insert an edge and return its `edge_id`. `t_end` defaults to `t_start`.

    That default is not an invented value: an interval observed at exactly one
    instant *is* `[t, t]`, and `extend_edge` is how it grows. It is the only
    honest starting point — an open-ended `t_end` would have to be `NULL` or an
    invented horizon, and both read as "still true" long after the relationship
    stopped holding.

    The layer comes from `EDGE_SPECS` and never from the caller. So do the
    endpoint kinds, except for the one edge type whose endpoints genuinely vary:
    `src_kind` and `dst_kind` are required for `FOLLOWS`, which joins two
    declarations in one chain and two verdicts in the other, and are refused for
    every other type.

    The metric argument for the edge type is required and the other one must be
    absent: an `INTERSECTS` with no `overlap_area` answers "how much" with
    `NULL`, which compares false against every threshold and turns an incident
    into a non-incident.
    """
    spec = EDGE_SPECS.get(edge_type)
    if spec is None:
        layer_of(edge_type)  # raises with the full vocabulary
        raise AssertionError  # pragma: no cover - layer_of always raises here

    resolved_src = _endpoint_kind(spec.src_kind, src_kind, edge_type, "src")
    resolved_dst = _endpoint_kind(spec.dst_kind, dst_kind, edge_type, "dst")

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

    _require_node(conn, resolved_src, str(src_id))
    _require_node(conn, resolved_dst, str(dst_id))

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
            resolved_src,
            str(src_id),
            resolved_dst,
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
