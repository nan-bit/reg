"""Build the evidence graph from a raw state stream. **The incremental rule.**

    python -m reg.graph build runs/contact.csv --out runs/contact.sqlite

WHAT MAKES THIS COMPRESS
------------------------
Not an encoder. docs/plan.md Phase 5, and docs/lossiness.md in full: the graph is
a **deliberate discard of everything provably irrelevant to a fixed, enumerated
question set**, and the only mechanism is the incremental rule —

    a relationship unchanged within tolerance extends the existing edge's t_end;
    a relationship that changed opens a new edge at the instant it changed.

"A robot holding still for 3 seconds at 50 Hz should produce ~1 node, not 150."
Everything else in this file is bookkeeping around that sentence.
`tests/test_graph.py` tests it as an invariant rather than a golden ratio: a
stream in which nothing changes produces the *same number of edge rows* whether
it is 5 frames long or 200.

"Unchanged within tolerance" means *the quantized value did not change*, and the
quantizers live in `reg.tolerances` — the only module allowed to assign the four
constants (docs/lossiness.md, "One definition"). A literal `0.01` in this file
would be a defect even if it were the right number.

THE INCREMENTAL RULE DOES NOT REACH ENVELOPE GEOMETRY
-----------------------------------------------------
It cannot: when the arm moves, the envelope genuinely *is* different every frame,
so every hash differs and emit-on-change emits every frame. Issue #28 measured
the consequence — the polygons were the artifact, and the artifact was 20-30x
*larger* than a gzipped CSV of the stream it replaced.

So the geometry is discarded on a stated rule (`GEOMETRY_RETENTION`,
docs/lossiness.md Discarded #9) and recovered by recomputation
(`envelope_at`). This is the lossiness contract's own logic applied where it had
not been: the polygon is a deterministic function of `(q, qd, horizon,
n_samples, seed, substep_dt)`, every one of which the artifact already stores, so
storing it per frame was storing the same information twice — once cheaply and
once expensively. What stays per frame is what queries actually read and what
costs almost nothing: `envelope_hash`, `area`, `horizon`, `source`.

The precondition is real and belongs beside the mechanism: recomputation
reproduces the polygon **exactly for the same code and the same shapely
version**, and not necessarily for an assessor opening the file in five years.
docs/limitations.md states it as the cost of the trade.

NOR DOES IT REACH ENVELOPE *IDENTITY*, WHICH IS ISSUE #29
---------------------------------------------------------
#28 moved the polygons out and left the scalars: one `envelope` row and one
`Timestep` row per frame, because the hash a row is keyed on genuinely differs
every frame when the arm moves. That is linear in the frame count by
construction, and linear-in, linear-out caps the compression ratio in single
digits however small the rows are made. Emit-on-change had been applied to edges
and not to nodes.

The fix is not a harder quantizer — widening a tolerance to make more things
"unchanged" buys the ratio by discarding resolution the lossiness contract
advertises, which is that contract's own named failure mode. It is to stop
treating "the envelope changed" as a reason to write a row. **A row is written
where it anchors something the artifact retains**, which is the rule
`RobotConfig` has followed since issue #14 (docs/lossiness.md Discarded #1),
applied to `Envelope` as well:

    ENVELOPE_RETENTION, below. An envelope row exists at a frame iff an
    INTERSECTS edge names it, or an entity relationship transitions there, or it
    is one of the two ends of the run.

and `Timestep` is gone entirely — every edge already carries `t_start`/`t_end`,
so a node per instant was a second and denser representation of time beside the
interval representation that does the work. docs/plan.md Phase 5's node table
lists it; Phase 7's query set does not need it. The two queries that name frames
at all — `frames_at_risk` and the incident report's "(27 frames)" — divide an
interval by `meta[frame_period_s]`, which is recorded once and checked uniform
at build time, and which is a *better* answer than counting rows: a row count
would depend on which frames happened to anchor an edge.

WHAT A FRAME WITH NO ROW MEANS
------------------------------
It means the artifact does not retain that frame's envelope, and `envelope_at`
**refuses** it. That is not new lossiness arriving at this line; it is
docs/lossiness.md Unanswerable #1 reaching where it always applied. The envelope
is a deterministic function of `(q, qd)` and the graph has never stored `q` at
every frame, so an envelope at every frame was only ever available by storing a
configuration per frame — which is the linearity being removed. Answering such a
frame with the neighbouring interval's polygon would be interpolation: a region
the robot demonstrably could reach, reported for an instant at which it could
not. docs/lossiness.md Discarded #10 states the rule and the artifact carries it
in `meta` under `envelope_row_retention`.

WHAT IS NOT HERE
----------------
Declarations and verdicts. They are Milestone 3, and the `DECLARED`,
`ADJUDICATED`, `ENFORCED` and `FOLLOWS` edge types are absent from
`reg.store.EDGE_SPECS` rather than present and never written — an edge type
nothing emits makes "no declarations in this run" indistinguishable from "this
build does not do declarations".

Also not here: `CONTAINS`. docs/plan.md lists it beside `INTERSECTS`, issue #14
scopes this milestone to `INTERSECTS`, and containment is recoverable from
`overlap_area` against the entity's own area at query time.

LAYERS
------
This module is mixed-layer — it reads the raw stream, which holds the human — and
it is careful about the one direction that matters. `compute_envelope` is given
`frame.proprio()` and `limits`, and nothing else; the world reaches it through no
argument. The envelope is computed *first*, independent of every entity, and only
then intersected with the scene. That order is not stylistic: it mirrors ARMTD
(docs/prior-art.md §4) and it is what lets `HAS_ENVELOPE` be tagged Layer A while
every edge naming an entity is tagged Layer B.

DETERMINISM
-----------
Same stream and same envelope parameters in, byte-identical SQLite file out. Node
ids are content hashes, not counters seeded by anything ambient; no path, clock
or hostname enters the artifact. `tests/test_graph.py` builds one stream twice
and compares bytes.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from shapely.geometry import Point
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from reg import __version__, store
from reg.envelope import SUBSTEP_DT, compute_envelope, envelope_hash
from reg.kinematics import link_polygons
from reg.stream import FLOAT_PRECISION, read_comments, read_frames
from reg.tolerances import (
    AREA_QUANT_SIGFIGS,
    DISTANCE_TOL_M,
    GEOM_SIMPLIFY_TOL_M,
    TIME_TOL_S,
    distance_bucket,
    quantize_area,
    quantize_distance,
    quantize_time,
    simplify_geometry,
)
from reg.types import Limits, Obstacle, ProprioState, StateFrame

__all__ = [
    "ENVELOPE_HORIZON",
    "ENVELOPE_N_SAMPLES",
    "ENVELOPE_RETENTION",
    "ENVELOPE_SEED",
    "ENVELOPE_SOURCE",
    "GEOMETRY_EVIDENCE_EDGES",
    "GEOMETRY_RETENTION",
    "HUMAN_ENTITY_ID",
    "HUMAN_KIND",
    "META_ENVELOPE_RETENTION",
    "META_GEOMETRY_RETENTION",
    "BuildResult",
    "GraphBuildError",
    "GraphQueryError",
    "build",
    "envelope_at",
    "main",
]

EXIT_OK = 0
EXIT_USAGE = 2

#: The raw stream has one human and no column naming it, because there is only
#: ever one. The graph keys every edge on an entity id, so it has to have one;
#: this is a schema fact stated once, not a parameter inferred per run. It is
#: written into the artifact's meta table so a reader never has to guess which
#: id the human got, and it collides loudly with an obstacle of the same id
#: rather than merging two histories.
HUMAN_ENTITY_ID = "human"
HUMAN_KIND = "human"

#: Only `computed` envelopes exist in this milestone. `declared` and `clamped`
#: arrive with `declare/` and `enforce/`; all three are retained separately
#: because "a clamp is only legible if the declared and the computed bound both
#: survive" (docs/lossiness.md Retained #8).
ENVELOPE_SOURCE = "computed"

# --------------------------------------------------------------------------
# Envelope parameters.
#
# `reg.envelope.compute_envelope` says, in its own docstring: "A caller computing
# an envelope per frame should say what it can afford rather than inherit these
# numbers by accident — and record what it said." This is that caller, and these
# three lines are it saying so.
#
# The honest test for a default (CLAUDE.md: never invent one) is whether an
# invented number would be indistinguishable downstream from a supplied one.
# Every value below is written into the artifact's meta table, so nothing
# downstream ever has to guess which one produced a given file — the same
# argument `reg.sim` makes for `--seed`.
# --------------------------------------------------------------------------

#: 200 ms, from docs/plan.md Phase 2. Stated there, not chosen here.
ENVELOPE_HORIZON: float = 0.2

#: The bottom of docs/plan.md Phase 2's stated 500-2000 range. The bottom
#: specifically, because this builder computes one envelope per *frame* where
#: `compute_envelope`'s own default targets a single call: 512 samples over a
#: 300-frame scenario is minutes, 2000 would be tens of minutes, and the
#: envelope is an under-approximation whose area moves by well under a percent
#: across that range (the 2**n corner controls dominate it). Offline batch is
#: fine — docs/plan.md non-goals — but "fine" is not "unbounded".
ENVELOPE_N_SAMPLES: int = 512

#: Sampling seed for the interior control draws. Not the scenario seed: this one
#: selects control samples, `reg.sim --seed` perturbs waypoints. Both are
#: recorded, under distinct meta keys, because a run reproduced with the wrong
#: one produces a different envelope and no error.
ENVELOPE_SEED: int = 0


# --------------------------------------------------------------------------
# The envelope-geometry retention rule (issue #28, docs/lossiness.md Discarded
# #9). Written down here and in the artifact, never left implicit in the code
# that applies it: a reader meeting a NULL geometry has to be able to tell
# "discarded on the rule" from "this build forgot", and the pattern of NULLs
# does not distinguish them.
# --------------------------------------------------------------------------

#: The edge types whose endpoints an incident report cites, and therefore the
#: ones whose transitions are worth a polygon. `SEPARATION` is deliberately not
#: among them: it changes on every centimetre of a walking human, so keeping
#: geometry at its transitions would keep it nearly everywhere, and its own
#: metric already travels on the edge. `HAS_ENVELOPE` is not among them either —
#: the envelope's own change is not evidence *about an entity*, and it is the
#: quantity that moves every frame.
GEOMETRY_EVIDENCE_EDGES: frozenset[str] = frozenset({"INTERSECTS", "CONTACT"})

# WHAT "STARTS OR ENDS" IS COUNTED OVER. The *relationship*, not the edge row.
# An INTERSECTS edge also closes and reopens whenever the overlap moves a
# quantum, and those are metric changes rather than topological ones: the overlap
# an incident report wants is already on the edge, and the polygon at one such
# frame is the polygon at the next with a slightly different area.
#
# This is measured, not a preference. On `sustained_overlap` at the benchmark's
# own parameters the human is inside the envelope for a single continuous
# interval carried by 79 INTERSECTS rows: counting every row's endpoints keeps
# geometry on 150 of 301 frames, counting the relationship's keeps it on 2. A
# rule whose retention scales with how much the arm moved is the defect issue #28
# exists to remove, reintroduced one level up. The issue's acceptance text says
# "an INTERSECTS or CONTACT edge starts or ends" and its parenthesis says "the
# transitions an incident report cites"; where those two readings differ this
# takes the second, and says so here rather than in a commit message.

#: The rule, in one sentence, as it is recorded in the artifact's meta table.
#: Prose rather than a code reference, because the artifact is the thing handed
#: to an assessor and `reg.graph.GEOMETRY_EVIDENCE_EDGES` means nothing to
#: someone holding only the file.
GEOMETRY_RETENTION = (
    "envelope geometry is stored on the first and last frame of the run and on "
    "every frame at which an INTERSECTS or CONTACT relationship with an entity "
    "begins or ceases to hold; on every other frame the envelope row carries its "
    "hash, area, horizon and source with a NULL geometry_wkb, and the polygon is "
    "recomputed from config_id and the envelope parameters in this meta table "
    "(reg.graph.envelope_at, docs/lossiness.md Discarded #9). Exact "
    "recomputation assumes the same code and the same shapely version — "
    "docs/limitations.md."
)

#: Where `GEOMETRY_RETENTION` lands in `meta`.
META_GEOMETRY_RETENTION = "envelope_geometry_retention"


# --------------------------------------------------------------------------
# The envelope-row retention rule (issue #29, docs/lossiness.md Discarded #10).
# The outer of the two rules: GEOMETRY_RETENTION decides which retained rows
# carry a polygon, this one decides which frames get a row at all.
#
# Both are in the artifact for the same reason. A reader meeting a run of frames
# with no envelope row has to be able to tell "not retained, on a stated rule"
# from "this build stopped writing", and the pattern of absences does not
# distinguish them — an artifact whose gaps mean nothing in particular is an
# artifact whose silences cannot be read at all.
# --------------------------------------------------------------------------

#: The rule, in one sentence, as it is recorded in the artifact's meta table.
#: Prose rather than a code reference: the artifact is what an assessor holds,
#: and `reg.graph.ENVELOPE_RETENTION` means nothing to someone holding the file.
ENVELOPE_RETENTION = (
    "an envelope row is stored on the first and last frame of the run, on every "
    "frame at which an INTERSECTS or CONTACT relationship with an entity begins "
    "or ceases to hold, and on every frame at which an INTERSECTS edge opens. On "
    "every other frame no envelope and no robot_config row is written, and the "
    "frame is addressed by the intervals that span it; there is no per-frame "
    "node in this schema. A frame the HAS_ENVELOPE intervals do not cover is a "
    "frame whose envelope this artifact does not retain, and reg.graph."
    "envelope_at refuses it rather than returning a neighbouring frame's polygon "
    "(docs/lossiness.md Discarded #10, Unanswerable #1). A HAS_ENVELOPE interval "
    "that spans several frames asserts the envelope was unchanged across all of "
    "them: the builder computes it at every frame and compares the hash, and "
    "only extends where the hash held."
)

#: Where `ENVELOPE_RETENTION` lands in `meta`.
META_ENVELOPE_RETENTION = "envelope_row_retention"

#: The `meta` keys `envelope_at` reads back to recompute a discarded polygon.
#: Named constants because the writer and the reader are one contract now: a key
#: spelled differently on one side turns every recomputable envelope into a
#: could-not-evaluate, and it surfaces in somebody's query rather than in a build.
META_N_SAMPLES = "envelope_n_samples"
META_ENVELOPE_SEED = "envelope_seed"
META_SUBSTEP_DT = "envelope_substep_dt_s"
META_LIMITS_LINK_LENGTHS = "limits_link_lengths"
META_LIMITS_LINK_RADIUS = "limits_link_radius"
META_LIMITS_Q_MIN = "limits_q_min"
META_LIMITS_Q_MAX = "limits_q_max"
META_LIMITS_QD_MAX = "limits_qd_max"
META_LIMITS_QDD_MAX = "limits_qdd_max"


class GraphBuildError(Exception):
    """The stream could not be turned into an evidence graph.

    Always a refusal with a named cause and never a partial artifact: a graph
    built from a stream this module did not fully understand would answer audit
    questions, and the answers would be wrong in ways no downstream check sees.
    """


class GraphQueryError(Exception):
    """A question the artifact cannot answer, named rather than approximated.

    `envelope_at` raises it when there is no envelope at the instant asked
    about, or when there is one whose geometry was discarded and whose
    recomputation inputs the artifact does not carry. Both are
    could-not-evaluate, and the alternative to raising is returning some other
    frame's polygon — which is a region of the plane the robot demonstrably
    could reach, at a time it could not.
    """


@dataclass(frozen=True)
class BuildResult:
    """What a build produced. Returned so callers do not re-query to find out."""

    path: Path
    frames: int
    #: Rows per edge type, all four keys always present. A zero is a fact ("no
    #: contact in this run"); a missing key would be indistinguishable from one.
    edges: dict[str, int]
    nodes: dict[str, int]
    size_bytes: int

    @property
    def total_edges(self) -> int:
        return sum(self.edges.values())


@dataclass
class _Active:
    """An edge currently being extended, and the quantized value it holds at.

    `edge_type` is carried because closing an edge is what tells the builder the
    *previous* frame was a transition, and the retention rule only keeps geometry
    for some edge types.
    """

    edge_id: int
    compare: object
    edge_type: str


@dataclass(frozen=True)
class _Observation:
    """One relationship observed at one frame, already quantized.

    `src` and `dst` are callables rather than ids because materializing the node
    is the expensive, *lossy-in-reverse* half: a `RobotConfig` row is only
    written when it anchors an edge that actually opens (docs/lossiness.md
    Discarded #1), and calling these is what writes it. Extending an existing
    edge calls neither, which is why a 300-frame hold leaves one config row.
    """

    edge_type: str
    src: Callable[[], str]
    dst: Callable[[], str]
    compare: object
    overlap_area: float | None = None
    min_distance: float | None = None


# --------------------------------------------------------------------------
# Formatting: every value that reaches the artifact goes through one of these,
# so two runs cannot differ in digits.
# --------------------------------------------------------------------------


def _joint_text(values: np.ndarray) -> str:
    """`q` or `qd` as text, at the raw stream's own precision.

    docs/plan.md says RobotConfig holds `q`, `qd` "(quantized)". docs/lossiness.md
    names four tolerances and **none of them is a joint-angle quantum**, so there
    is no quantization to apply here and inventing one would put a bound in the
    artifact that no document states. What the graph discards about joint state
    is *when it is recorded* — only at configurations anchoring a retained
    relationship — not how many digits it keeps.
    """
    return ",".join(f"{float(v):.{FLOAT_PRECISION}f}" for v in np.asarray(values))


def _digest(*parts: str) -> str:
    return hashlib.sha256("\x00".join(parts).encode("utf-8")).hexdigest()[:16]


def _float_text(value: float) -> str:
    """A float for the meta table. `repr` round-trips exactly; `str` may not."""
    return repr(float(value))


def _already(node_id: str) -> Callable[[], str]:
    """An `_Observation` endpoint that is already in the store.

    Entity nodes are written once, before the loop; the per-frame nodes are not.
    Wrapping the id keeps both kinds of endpoint the same shape at the call site,
    so nothing has to remember which ones cost a write.
    """
    return lambda: node_id


def _array_text(values: np.ndarray) -> str:
    return ",".join(_float_text(v) for v in np.asarray(values, dtype=float))


# --------------------------------------------------------------------------
# Per-frame node materialization
# --------------------------------------------------------------------------


class _FrameNodes:
    """Lazily writes the nodes one frame *would* need, if an edge anchors one.

    Nothing here is written on construction, and that is the whole compression
    mechanism on the node side (`ENVELOPE_RETENTION`, issue #29). A frame at
    which no relationship transitions and no `INTERSECTS` edge opens must leave
    **no rows at all** — not an `Envelope`, not a `RobotConfig` — and that only
    holds if every write happens at edge-anchor time and nowhere else. A frame
    over which `HAS_ENVELOPE` merely extends writes nothing either: extending is
    an `UPDATE` to one edge row.

    The ids are derived on construction, which is not a write: a content hash of
    values already in hand costs nothing, and the builder has to be able to name
    a row it may never write.
    """

    def __init__(
        self,
        conn,
        *,
        t: float,
        envelope: BaseGeometry,
        envelope_digest: str,
        horizon: float,
        q_text: str,
        qd_text: str,
    ) -> None:
        self._conn = conn
        self._t = t
        self._envelope = envelope
        self._envelope_digest = envelope_digest
        self._horizon = horizon
        self._q_text = q_text
        self._qd_text = qd_text
        self._envelope_id = "env_" + _digest(
            ENVELOPE_SOURCE, f"{horizon:.9f}", envelope_digest
        )
        self._config_id = "cfg_" + _digest(q_text, qd_text)
        self._keep_geometry = False
        self._retained = False

    @property
    def t(self) -> float:
        """This frame's timestamp, already quantized to `TIME_TOL_S`."""
        return self._t

    @property
    def digest(self) -> str:
        """The envelope's identity at this frame. What `HAS_ENVELOPE` compares."""
        return self._envelope_digest

    @property
    def retained(self) -> bool:
        """Whether this frame's `Envelope` row was written.

        `False` means the frame anchors nothing and the artifact keeps no node
        for it — the state `ENVELOPE_RETENTION` describes and `envelope_at`
        refuses. It is read rather than predicted: the frame's own edges decide
        it, and they are opened by the caller.
        """
        return self._retained

    def envelope_node(self) -> str:
        """The `Envelope` row for this frame, with the config it came from.

        Calling this is what makes the frame *retained*: an envelope row is the
        artifact's record that this instant existed, and `HAS_ENVELOPE` is
        emitted for exactly the frames that have one.

        The config is written alongside it and not only when a `SEPARATION` or
        `CONTACT` edge anchors one: it is what `envelope_at` recomputes the
        discarded polygon from, so an envelope row whose config is missing is a
        frame whose envelope nobody can reconstruct. It is also the cheap half of
        that information — joint text against a WKB polygon.
        """
        self._retained = True
        config_id = self.config()
        return store.insert_envelope(
            self._conn,
            self._envelope_id,
            envelope_hash=self._envelope_digest,
            area=quantize_area(self._envelope.area),
            geometry=self._envelope if self._keep_geometry else None,
            config_id=config_id,
            horizon=self._horizon,
            source=ENVELOPE_SOURCE,
        )

    def config(self) -> str:
        return store.insert_robot_config(
            self._conn, self._config_id, self._q_text, self._qd_text
        )

    def keep_geometry(self) -> None:
        """This frame is one `GEOMETRY_RETENTION` keeps the polygon for.

        Retention of the polygon implies retention of the row: a frame worth a
        polygon is a frame worth an `Envelope`, and there is no way to store the
        first without the second. So this writes the row if nothing else has.

        Idempotent, and callable *after* the row has been written — a
        relationship's last instant is only known one frame later, so the builder
        reaches back to the previous frame and says so then. `insert_envelope`
        attaches the polygon to a row that already exists without one, which is
        why the two orders end in the same file.
        """
        self._keep_geometry = True
        self.envelope_node()


# --------------------------------------------------------------------------
# Stream checks
# --------------------------------------------------------------------------


def _frame_period(frames: Sequence[StateFrame], csv_path: object) -> float:
    """The stream's frame period, checked for uniformity. A refusal if it is not.

    docs/lossiness.md is explicit that `TIME_TOL_S` is a quantum and not a
    promise: "If the simulator runs below 100 Hz, transitions are only locatable
    to the frame period, and the graph must record the frame period in its
    provenance and never report finer." A stream whose gaps vary has no single
    frame period, so recording one would be the fabricated digit that sentence
    forbids — and interval endpoints derived from it would claim a resolution the
    stream never had.
    """
    if len(frames) < 2:
        raise GraphBuildError(
            f"{csv_path}: {len(frames)} frame(s). A stream needs at least two "
            "for the frame period to exist, and without a frame period the "
            "artifact cannot state the resolution its interval endpoints are "
            "good to — which docs/lossiness.md requires it to record."
        )

    gaps = np.diff([float(f.t) for f in frames])
    period = float(gaps[0])
    if period <= 0.0:
        raise GraphBuildError(
            f"{csv_path}: the first two frames are {period}s apart. Time must "
            "advance; a stream that stands still or runs backwards has no "
            "interval structure to record."
        )
    worst = int(np.argmax(np.abs(gaps - period)))
    if abs(gaps[worst] - period) > TIME_TOL_S:
        raise GraphBuildError(
            f"{csv_path}: frame period is not uniform. Frames 0-1 are {period}s "
            f"apart but frames {worst}-{worst + 1} are {float(gaps[worst])}s "
            f"apart, a difference above TIME_TOL_S={TIME_TOL_S}. The artifact "
            "records one frame period and reports nothing finer than it; there "
            "is no single honest value to record here."
        )
    return period


def _entity_set(
    frames: Sequence[StateFrame], csv_path: object
) -> tuple[Obstacle, ...]:
    """The static obstacles, verified static across the whole stream.

    The raw stream logs obstacles every frame deliberately, to inflate the
    baseline honestly (`reg.stream`), and the graph stores them once
    (docs/lossiness.md Discarded #6). That collapse is only sound if they really
    do not move, so it is checked rather than assumed: an obstacle that moved
    would be recorded at its first-frame position and every separation to it
    afterwards would be measured against a place it no longer is.
    """
    first = frames[0].objects
    seen: set[str] = set()
    for obstacle in first:
        if obstacle.entity_id in seen:
            raise GraphBuildError(
                f"{csv_path}: duplicate entity_id {obstacle.entity_id!r} in frame "
                "0. Entity ids key every edge; two entities sharing one merge two "
                "histories into an answer about neither."
            )
        seen.add(obstacle.entity_id)
    if HUMAN_ENTITY_ID in seen:
        raise GraphBuildError(
            f"{csv_path}: an obstacle already uses the entity id "
            f"{HUMAN_ENTITY_ID!r}, which is the id the graph gives the human "
            "(reg.graph.HUMAN_ENTITY_ID). Their edges would merge."
        )

    for frame_id, frame in enumerate(frames[1:], start=1):
        if frame.objects != first:
            raise GraphBuildError(
                f"{csv_path}: the obstacle set changed at frame {frame_id} "
                f"(t={frame.t}). Obstacles are static by the stream's own schema "
                "and the graph stores their geometry once; a moving one would be "
                "recorded where it started and every separation measured against "
                "a place it is not."
            )
    return first


# --------------------------------------------------------------------------
# The build
# --------------------------------------------------------------------------


def build(
    csv_path: str | os.PathLike[str],
    out_path: str | os.PathLike[str],
    limits: Limits,
    *,
    human_radius: float,
    horizon: float = ENVELOPE_HORIZON,
    n_samples: int = ENVELOPE_N_SAMPLES,
    seed: int = ENVELOPE_SEED,
    substep_dt: float = SUBSTEP_DT,
) -> BuildResult:
    """Turn a raw CSV stream into a SQLite evidence graph. Overwrites `out_path`.

    Args:
        csv_path: a stream written by `reg.stream.write_frames`.
        out_path: the artifact to write. Replaced if it exists.
        limits: the robot's kinematic and actuation bounds — Layer A, and the
            only thing besides `frame.proprio()` that reaches the envelope.
        human_radius: **required, and there is no default.** The raw stream
            carries the human's position and velocity and *not* its extent
            (`reg.stream._HUMAN_COLUMNS`), so every separation and contact
            involving the human depends on a number that is not in the file. A
            plausible 0.25 m invented here would be indistinguishable downstream
            from the value that actually produced the run, and every Layer B
            answer in the artifact would inherit it silently. The CLI resolves it
            from the scenario named in the stream's own provenance block.
        horizon, n_samples, seed, substep_dt: envelope parameters. All four are
            recorded in the artifact's meta table, so no consumer has to guess
            which produced a given file — and `envelope_at` reads them back to
            recompute the envelope geometry `GEOMETRY_RETENTION` discards.

    Returns:
        A `BuildResult` with the row counts and the artifact's size.
        `nodes["Envelope"]` counts envelope *rows*, one per frame the artifact
        retains (`ENVELOPE_RETENTION`) and **not** one per frame nor one per
        material change; most of them carry no polygon (`GEOMETRY_RETENTION`),
        so it is not a count of stored geometries either.

    Raises:
        GraphBuildError: the stream could not be understood — too short, a
            non-uniform frame period, or an obstacle that moved. Each is a
            could-not-evaluate, and none of them writes a usable artifact.
    """
    frames = tuple(read_frames(csv_path))
    period = _frame_period(frames, csv_path)
    obstacles = _entity_set(frames, csv_path)

    human_radius = float(human_radius)
    if not np.isfinite(human_radius) or human_radius <= 0.0:
        raise GraphBuildError(
            f"human_radius={human_radius!r}. A human of zero or negative extent "
            "can never contact anything, so every contact question in the "
            "artifact would answer 'no' for a reason nobody wrote down."
        )

    conn = store.create(out_path)
    try:
        _write_provenance(
            conn,
            csv_path=csv_path,
            frames=frames,
            period=period,
            limits=limits,
            human_radius=human_radius,
            horizon=horizon,
            n_samples=n_samples,
            seed=seed,
            substep_dt=substep_dt,
        )

        # Entity set, once. Static geometry is simplified because
        # docs/lossiness.md Discarded #2 says entity boundaries are, and because
        # every overlap and distance below is then measured against exactly the
        # boundary the artifact stores.
        static_geoms: dict[str, BaseGeometry] = {}
        for obstacle in obstacles:
            geometry = simplify_geometry(
                Point(obstacle.cx, obstacle.cy).buffer(obstacle.radius)
            )
            store.insert_entity(
                conn, obstacle.entity_id, obstacle.kind, geometry=geometry
            )
            static_geoms[obstacle.entity_id] = geometry
        store.insert_entity(conn, HUMAN_ENTITY_ID, HUMAN_KIND, geometry=None)

        active: dict[tuple[str, str], _Active] = {}
        has_envelope: _Active | None = None
        previous: _FrameNodes | None = None
        last_frame_id = len(frames) - 1

        def envelope_timeline(nodes: _FrameNodes) -> None:
            """One frame's entry in the envelope's own timeline. Layer A.

            Deliberately *not* an `_Observation`: unlike every relationship, this
            one opens only where the artifact retains a node to hang it on
            (`ENVELOPE_RETENTION`), so it is emitted a frame late — a frame's
            retention is not final until the frame after it has been read and
            the relationships that ended there have reached back.

            Three cases, and the third is the one that does the compressing:

            * the envelope is the one already on the open interval -> extend it.
              No row is written; a robot holding still leaves one HAS_ENVELOPE
              edge whether it holds for 6 frames or 600.
            * it changed and this frame is retained -> close and open a new
              interval at the instant it changed.
            * it changed and this frame is not retained -> close, and open
              nothing. The gap is the artifact saying it does not hold this
              frame's envelope, which `envelope_at` reports as a refusal.

            The extend case is safe against an envelope that changes and later
            comes back: `has_envelope` is cleared on any frame whose digest
            differs from it, and this runs once per frame in order, so a
            non-`None` `has_envelope` always names the immediately preceding
            frame. An interval therefore never spans a frame it did not hold at.
            """
            nonlocal has_envelope
            if has_envelope is not None and has_envelope.compare == nodes.digest:
                store.extend_edge(conn, has_envelope.edge_id, nodes.t)
                return
            has_envelope = None
            if not nodes.retained:
                return
            edge_id = store.open_edge(
                conn,
                "HAS_ENVELOPE",
                nodes.config(),
                nodes.envelope_node(),
                nodes.t,
            )
            has_envelope = _Active(edge_id, nodes.digest, "HAS_ENVELOPE")

        for frame_id, frame in enumerate(frames):
            t = quantize_time(frame.t)
            nodes, observations = _observe(
                conn,
                frame=frame,
                t=t,
                limits=limits,
                human_radius=human_radius,
                static_geoms=static_geoms,
                horizon=horizon,
                n_samples=n_samples,
                seed=seed,
                substep_dt=substep_dt,
            )

            # GEOMETRY_RETENTION, clause 2: the ends of the run. The first frame
            # is where an incident report starts reading and the last is the
            # state the run finished in, and neither is a transition, so nothing
            # else in this loop would keep them.
            if frame_id == 0 or frame_id == last_frame_id:
                nodes.keep_geometry()

            # A relationship that stopped holding closes its edge. Closing is the
            # absence of an extension, not an edit: t_end already names the last
            # instant it was observed — which is the previous frame, and which is
            # why GEOMETRY_RETENTION's "ends" clause reaches backwards.
            for key in [k for k in active if k not in observations]:
                cited = active[key].edge_type in GEOMETRY_EVIDENCE_EDGES
                if cited and previous is not None:
                    previous.keep_geometry()
                del active[key]

            # ...and that backward reach is the last thing that can retain the
            # previous frame, so its timeline entry is settled now and not
            # before. Emitted here rather than after this frame's own edges so
            # that edge ids stay in time order.
            if previous is not None:
                envelope_timeline(previous)

            for key, observation in observations.items():
                current = active.get(key)
                if current is not None and current.compare == observation.compare:
                    store.extend_edge(conn, current.edge_id, t)
                    continue
                # GEOMETRY_RETENTION, clause 1: the frame a contact-relevant
                # relationship begins to hold. `current is None` is what makes it
                # a beginning rather than a metric step — an edge that replaces
                # one still open is the same relationship with a different
                # overlap quantum, and its area is already on the edge row.
                cited = observation.edge_type in GEOMETRY_EVIDENCE_EDGES
                if current is None and cited:
                    nodes.keep_geometry()
                edge_id = store.open_edge(
                    conn,
                    observation.edge_type,
                    observation.src(),
                    observation.dst(),
                    t,
                    overlap_area=observation.overlap_area,
                    min_distance=observation.min_distance,
                )
                active[key] = _Active(
                    edge_id, observation.compare, observation.edge_type
                )

            previous = nodes

        # The last frame has no successor to settle it; `_frame_period` has
        # already refused a stream too short to have one.
        if previous is not None:  # pragma: no branch - >= 2 frames, checked above
            envelope_timeline(previous)

        conn.commit()
        result = _summarize(conn, Path(out_path), len(frames))
    except BaseException:
        # A half-written artifact is the worst outcome available here: it opens,
        # it queries, and every interval after the failure is simply missing —
        # which reads as "the relationship stopped holding". Nothing distinguishes
        # that from the truth, so the file does not survive the failure.
        conn.close()
        Path(out_path).unlink(missing_ok=True)
        raise
    finally:
        conn.close()
    return result


def _observe(
    conn,
    *,
    frame: StateFrame,
    t: float,
    limits: Limits,
    human_radius: float,
    static_geoms: dict[str, BaseGeometry],
    horizon: float,
    n_samples: int,
    seed: int,
    substep_dt: float,
) -> tuple[_FrameNodes, dict[tuple[str, str], _Observation]]:
    """Every entity relationship at one frame, quantized, in a fixed order.

    Fixed order because insertion order decides `edge_id`, and `edge_id` is the
    tie-break in every ordered read (`reg.store.read_edges`). Two builds of one
    stream must produce identical files, so nothing here may iterate a set.

    `HAS_ENVELOPE` is **not** among the observations, and that absence is issue
    #29. Every relationship here is a fact about an entity and is emitted by the
    same rule; the envelope's own timeline is emitted by a different one — only
    at frames the artifact retains a node for — so it cannot be decided here,
    where nothing yet knows which edges will open.

    The frame's `_FrameNodes` comes back with the observations for the same
    reason: whether this frame is one `GEOMETRY_RETENTION` keeps a polygon for
    depends on which edges open and close, which is the caller's decision, and
    on where the frame sits in the run.
    """
    proprio = frame.proprio()

    # Layer A, first, and blind to everything below. `compute_envelope` takes a
    # ProprioState; the world reaches it through no argument.
    envelope = simplify_geometry(
        compute_envelope(
            proprio,
            limits,
            horizon=horizon,
            n_samples=n_samples,
            seed=seed,
            substep_dt=substep_dt,
        )
    )
    digest = envelope_hash(envelope)

    # The robot body is deliberately *not* simplified. The error budget in
    # docs/lossiness.md allows one simplified boundary per distance
    # (GEOM_SIMPLIFY_TOL_M + DISTANCE_TOL_M/2 <= DISTANCE_TOL_M), and the entity
    # boundary is already spending it. Simplifying both would put reported
    # distances outside the 1 cm the artifact advertises.
    body = unary_union(link_polygons(proprio, limits))

    nodes = _FrameNodes(
        conn,
        t=t,
        envelope=envelope,
        envelope_digest=digest,
        horizon=horizon,
        q_text=_joint_text(frame.q),
        qd_text=_joint_text(frame.qd),
    )

    observations: dict[tuple[str, str], _Observation] = {}

    geometries: list[tuple[str, BaseGeometry]] = [
        (entity_id, static_geoms[entity_id]) for entity_id in static_geoms
    ]
    geometries.append(
        (
            HUMAN_ENTITY_ID,
            simplify_geometry(
                Point(float(frame.human_pos[0]), float(frame.human_pos[1])).buffer(
                    human_radius
                )
            ),
        )
    )

    for entity_id, geometry in geometries:
        # WHAT AN INTERVAL IS AN INTERVAL *OF*. The comparison value is the
        # quantized overlap, not the envelope's identity, so an INTERSECTS edge
        # extends across frames in which the envelope changed but the overlap did
        # not. That is deliberate and it is where the compression on this edge
        # type lives — keying it on the envelope hash as well would emit one row
        # per frame for any moving arm, which is the thing the incremental rule
        # exists to avoid. docs/lossiness.md Retained #1 and #2 make the interval
        # a property of the *relationship*.
        #
        # The consequence, stated so nobody has to infer it: `src` names the
        # envelope in force at `t_start`, not throughout. The envelope's own
        # timeline is the HAS_ENVELOPE edges, and that is the only thing that
        # answers "which envelope was in force at t".
        overlap = envelope.intersection(geometry)
        if not overlap.is_empty and overlap.area > 0.0:
            area = quantize_area(overlap.area)
            observations[("INTERSECTS", entity_id)] = _Observation(
                edge_type="INTERSECTS",
                src=nodes.envelope_node,
                dst=_already(entity_id),
                compare=area,
                overlap_area=area,
            )

        # Same for SEPARATION and CONTACT: `src` is the RobotConfig at t_start,
        # and the joint path between two of them is gone (docs/lossiness.md
        # Discarded #1, Unanswerable #1).
        distance = float(body.distance(geometry))
        observations[("SEPARATION", entity_id)] = _Observation(
            edge_type="SEPARATION",
            src=nodes.config,
            dst=_already(entity_id),
            # Compared on the integer bucket index, not on the rounded float:
            # float equality after two different roundings is not a thing to
            # rely on when the answer decides whether a row is emitted.
            compare=distance_bucket(distance),
            min_distance=quantize_distance(distance),
        )

        if body.intersects(geometry):
            observations[("CONTACT", entity_id)] = _Observation(
                edge_type="CONTACT",
                src=nodes.config,
                dst=_already(entity_id),
                # Contact has no metric: it either holds or it does not, so the
                # comparison value is constant and the edge extends for as long
                # as it holds.
                compare=True,
            )

    return nodes, observations


def _write_provenance(
    conn,
    *,
    csv_path: object,
    frames: Sequence[StateFrame],
    period: float,
    limits: Limits,
    human_radius: float,
    horizon: float,
    n_samples: int,
    seed: int,
    substep_dt: float,
) -> None:
    """Everything needed to say what produced this artifact, and nothing else.

    docs/lossiness.md Retained #10: "scenario name, seed, tolerance constants in
    force, and the schema version, once per artifact. Determinism is only
    checkable if the artifact says what produced it."

    Nothing that varies between two runs of the same command may enter here — no
    path, no clock, no hostname. The source stream's own provenance block is
    copied in verbatim, which is where the scenario name and the simulator seed
    come from; if the stream carries none, the key is *absent* rather than empty,
    because "the source said nothing" and "the source said nothing useful" are
    both could-not-evaluate and neither is a default.
    """
    store.put_meta(conn, "reg_version", __version__)
    store.put_meta(conn, "frame_count", str(len(frames)))
    store.put_meta(conn, store.META_FRAME_PERIOD, _float_text(period))
    store.put_meta(conn, "t_first", _float_text(quantize_time(frames[0].t)))
    store.put_meta(conn, "t_last", _float_text(quantize_time(frames[-1].t)))

    store.put_meta(conn, "envelope_source", ENVELOPE_SOURCE)
    store.put_meta(conn, "envelope_horizon_s", _float_text(horizon))
    store.put_meta(conn, META_N_SAMPLES, str(int(n_samples)))
    store.put_meta(conn, META_ENVELOPE_SEED, str(int(seed)))
    store.put_meta(conn, META_SUBSTEP_DT, _float_text(substep_dt))

    # The two retention rules, in the artifact and not only in this module,
    # because the file is the thing handed over. A NULL geometry has to read as
    # "discarded on a stated rule and recomputable" rather than as "this build
    # wrote nothing there", and a frame with no row at all has to read as "not
    # retained, on a stated rule" rather than as "the build stopped".
    store.put_meta(conn, META_ENVELOPE_RETENTION, ENVELOPE_RETENTION)
    store.put_meta(conn, META_GEOMETRY_RETENTION, GEOMETRY_RETENTION)

    store.put_meta(conn, "tolerance_distance_tol_m", _float_text(DISTANCE_TOL_M))
    store.put_meta(conn, "tolerance_area_quant_sigfigs", str(AREA_QUANT_SIGFIGS))
    store.put_meta(conn, "tolerance_time_tol_s", _float_text(TIME_TOL_S))
    store.put_meta(
        conn, "tolerance_geom_simplify_tol_m", _float_text(GEOM_SIMPLIFY_TOL_M)
    )

    # The limits are what every envelope and every separation in the file was
    # computed from. Without them the geometry cannot be recomputed, and a
    # separation nobody can recompute is not evidence (docs/lossiness.md's whole
    # "how to tell if this contract is being violated" section needs them).
    store.put_meta(conn, META_LIMITS_LINK_LENGTHS, _array_text(limits.link_lengths))
    store.put_meta(conn, META_LIMITS_LINK_RADIUS, _float_text(limits.link_radius))
    store.put_meta(conn, META_LIMITS_Q_MIN, _array_text(limits.q_min))
    store.put_meta(conn, META_LIMITS_Q_MAX, _array_text(limits.q_max))
    store.put_meta(conn, META_LIMITS_QD_MAX, _array_text(limits.qd_max))
    store.put_meta(conn, META_LIMITS_QDD_MAX, _array_text(limits.qdd_max))

    store.put_meta(conn, "human_entity_id", HUMAN_ENTITY_ID)
    store.put_meta(conn, "human_radius_m", _float_text(human_radius))

    comments = read_comments(csv_path)
    if comments:
        store.put_meta(conn, "source_provenance", "\n".join(comments))


def _summarize(conn, path: Path, frames: int) -> BuildResult:
    edges = {
        edge_type: int(
            conn.execute(
                "SELECT count(*) AS n FROM edge WHERE type = ?", (edge_type,)
            ).fetchone()["n"]
        )
        for edge_type in store.EDGE_SPECS
    }
    nodes = {
        kind: int(
            conn.execute(
                f"SELECT count(*) AS n FROM {table}"  # noqa: S608
            ).fetchone()["n"]
        )
        for kind, (table, _) in store.NODE_TABLES.items()
    }
    return BuildResult(
        path=path,
        frames=frames,
        edges=edges,
        nodes=nodes,
        size_bytes=path.stat().st_size,
    )


# --------------------------------------------------------------------------
# Reading an envelope back. The other half of GEOMETRY_RETENTION: a discard is
# only a discard rather than a deletion if something can still answer the
# question, and this is that something.
# --------------------------------------------------------------------------


def _meta_required(conn, key: str) -> str:
    """One `meta` value, or a refusal naming the key that is missing.

    Never a default. Every value read through here changes the polygon that comes
    back — a substituted `n_samples` produces a different region with no error
    anywhere, and it would be indistinguishable from the region that was actually
    computed at build time.
    """
    value = store.get_meta(conn, key)
    if value is None:
        raise GraphQueryError(
            f"the artifact has no meta[{key!r}], so it does not say what the "
            "envelope was computed with. The geometry of this frame was "
            "discarded as recomputable (docs/lossiness.md Discarded #9) and "
            "recomputing it needs that value; a plausible one invented here "
            "would return a region nobody can tell from the recorded one."
        )
    return value


def _meta_float(conn, key: str) -> float:
    raw = _meta_required(conn, key)
    try:
        return float(raw)
    except ValueError as exc:
        raise GraphQueryError(f"meta[{key!r}] is {raw!r}, not a number.") from exc


def _meta_int(conn, key: str) -> int:
    """A meta value that must be a whole number. `512.5` is refused, not floored.

    Flooring would run the recomputation at a sample count the build never used,
    and produce a polygon that differs from the recorded one for a reason nothing
    in the file records.
    """
    raw = _meta_required(conn, key)
    try:
        return int(raw)
    except ValueError as exc:
        raise GraphQueryError(f"meta[{key!r}] is {raw!r}, not an integer.") from exc


def _floats(text: str, what: str) -> np.ndarray:
    try:
        return np.array([float(part) for part in str(text).split(",")], dtype=float)
    except ValueError as exc:
        raise GraphQueryError(
            f"{what} is {text!r}, not a comma-separated list of numbers."
        ) from exc


def _meta_array(conn, key: str) -> np.ndarray:
    return _floats(_meta_required(conn, key), f"meta[{key!r}]")


def _limits_from_meta(conn) -> Limits:
    """The robot the artifact was built for, from its own provenance block.

    docs/lossiness.md Retained #10 records the limits precisely so this is
    possible: "without them the geometry cannot be recomputed, and a separation
    nobody can recompute is not evidence".
    """
    try:
        return Limits(
            q_min=_meta_array(conn, META_LIMITS_Q_MIN),
            q_max=_meta_array(conn, META_LIMITS_Q_MAX),
            qd_max=_meta_array(conn, META_LIMITS_QD_MAX),
            qdd_max=_meta_array(conn, META_LIMITS_QDD_MAX),
            link_lengths=_meta_array(conn, META_LIMITS_LINK_LENGTHS),
            link_radius=_meta_float(conn, META_LIMITS_LINK_RADIUS),
        )
    except ValueError as exc:  # Limits itself refuses a per-joint mismatch
        raise GraphQueryError(
            f"the limits recorded in this artifact are not self-consistent: {exc}"
        ) from exc


def envelope_at(conn, t: float) -> BaseGeometry:
    """The envelope in force at `t`: read back, or recomputed. Same answer.

    A caller cannot tell which happened, except by timing. That is the whole
    claim of `GEOMETRY_RETENTION`: the polygon is stored where it is evidence in
    its own right and recomputed everywhere else, and
    `tests/test_graph.py::test_envelope_at_recomputes_the_stored_polygon_exactly`
    is the gate on "same answer" — it blanks a stored geometry and asserts the
    recomputed polygon is identical, at zero tolerance. If that ever fails, the
    discard is not lossless and this whole approach is wrong.

    Args:
        conn: an open artifact (`reg.store.connect`).
        t: seconds. Quantized to `TIME_TOL_S` on the way in, because that is the
            resolution the artifact's interval endpoints were recorded at and
            nothing here may report finer.

    Returns:
        The simplified envelope polygon — the same geometry `build` hashed and
        would have stored.

    Raises:
        GraphQueryError: no `HAS_ENVELOPE` interval covers `t` — the gaps
            *between* frames, and, since issue #29, the frames the artifact does
            not retain a node for (`ENVELOPE_RETENTION`, docs/lossiness.md
            Discarded #10 and Unanswerable #1); two intervals cover it and their
            order is not retained (Unanswerable #5); or the geometry was
            discarded and something needed to recompute it is not in the file.
            Every one is a could-not-evaluate, and none of them resolves to some
            other frame's polygon.
    """
    t = quantize_time(t)
    edges = store.read_edges(conn, edge_type="HAS_ENVELOPE")
    covering = [row for row in edges if row["t_start"] <= t <= row["t_end"]]
    if not covering:
        raise GraphQueryError(
            f"no envelope is recorded as being in force at t={t}. The artifact "
            f"holds {len(edges)} HAS_ENVELOPE interval(s)"
            + (
                f" spanning [{min(r['t_start'] for r in edges)}, "
                f"{max(r['t_end'] for r in edges)}]"
                if edges
                else ""
            )
            + ". Two kinds of instant fall outside them and neither is answered "
            "here: one between two frames, which belongs to neither, and one at "
            "a frame the artifact retains no node for. The second is the rule in "
            f"meta[{META_ENVELOPE_RETENTION!r}] — the envelope is a function of "
            "the configuration, the graph stores configurations only where they "
            "anchor something, and the envelope at a frame whose configuration "
            "is gone is not something this artifact holds. The neighbouring "
            "interval's polygon is a region the robot could reach at a different "
            "instant, which is not an answer to this question."
        )
    if len(covering) > 1:
        raise GraphQueryError(
            f"{len(covering)} envelopes are recorded as in force at t={t}. Two "
            "transitions inside one TIME_TOL_S quantum have no retained order "
            "(docs/lossiness.md Unanswerable #5), so there is no way to say "
            "which of them this instant belongs to."
        )

    envelope_id = str(covering[0]["dst_id"])
    row = store.envelope_row(conn, envelope_id)
    if row is None:  # pragma: no cover - open_edge refuses a dangling endpoint
        raise GraphQueryError(
            f"the HAS_ENVELOPE edge covering t={t} points at envelope "
            f"{envelope_id!r}, which is not in this artifact."
        )
    if row["geometry_wkb"] is not None:
        return store.from_wkb(row["geometry_wkb"])

    # Discarded, so recompute it. Everything below is a stated input of
    # `compute_envelope`, read from the artifact and never assumed.
    source = str(row["source"])
    if source != ENVELOPE_SOURCE:
        raise GraphQueryError(
            f"envelope {envelope_id!r} has source={source!r} and no stored "
            f"geometry. Only {ENVELOPE_SOURCE!r} envelopes are recomputable — a "
            "declared or clamped bound came from a policy, not from a "
            "configuration, and there is nothing in the file to derive it from."
        )
    config_id = row["config_id"]
    if config_id is None:  # pragma: no cover - the schema CHECK forbids it
        raise GraphQueryError(
            f"envelope {envelope_id!r} stores neither geometry nor the config it "
            "was computed from."
        )
    config = conn.execute(
        "SELECT q, qd FROM robot_config WHERE config_id = ?", (str(config_id),)
    ).fetchone()
    if config is None:
        raise GraphQueryError(
            f"envelope {envelope_id!r} names config {str(config_id)!r}, which is "
            "not in this artifact. The polygon was discarded as recomputable and "
            "the thing it was to be recomputed from is missing."
        )

    state = ProprioState(
        t=t,
        q=_floats(config["q"], f"robot_config[{str(config_id)!r}].q"),
        qd=_floats(config["qd"], f"robot_config[{str(config_id)!r}].qd"),
    )
    return simplify_geometry(
        compute_envelope(
            state,
            _limits_from_meta(conn),
            horizon=float(row["horizon"]),
            n_samples=_meta_int(conn, META_N_SAMPLES),
            seed=_meta_int(conn, META_ENVELOPE_SEED),
            substep_dt=_meta_float(conn, META_SUBSTEP_DT),
        )
    )


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def _resolve_world(csv_path: str | os.PathLike[str]):
    """The world that produced a stream, from the stream's own provenance block.

    This is the CLI's answer to the two Layer B parameters `build` refuses to
    invent — the robot's `Limits` and the human's radius. Neither is in the CSV's
    columns, and guessing either would put a number in the artifact that nobody
    supplied. The stream *does* say which scenario produced it (`reg.sim` writes
    `scenario=` into the `#` block), and a scenario names exactly one world, so
    the chain from artifact to parameters is closed and auditable.

    A stream with no provenance block, or one naming a scenario this build does
    not have, is a refusal. It is precisely the could-not-evaluate case: the file
    does not say what produced it, and "the defaults were used" is not a reading
    of silence (`reg.sim.parse_provenance` says the same).
    """
    from reg.scenarios import SCENARIOS, scenario
    from reg.sim import parse_provenance

    fields = parse_provenance(csv_path)
    name = fields.get("scenario")
    if name is None:
        raise GraphBuildError(
            f"{csv_path} has no 'scenario=' line in its provenance block, so it "
            "does not say what produced it. The robot's limits and the human's "
            "radius are not columns in the stream and cannot be recovered from "
            "it; there is nothing here to build a graph from without inventing "
            "both. Regenerate the stream with `python -m reg.sim`."
        )
    if name not in SCENARIOS:
        raise GraphBuildError(
            f"{csv_path} says scenario={name!r}, which this build does not know. "
            f"Known scenarios: {', '.join(SCENARIOS)}."
        )
    return scenario(name).world


def _positive_float(raw: str) -> float:
    try:
        value = float(raw)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{raw!r} is not a number") from None
    if not np.isfinite(value) or value <= 0.0:
        raise argparse.ArgumentTypeError(f"{value}: must be finite and positive")
    return value


def _non_negative_int(raw: str) -> int:
    try:
        value = int(raw)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{raw!r} is not an integer") from None
    if value < 0:
        raise argparse.ArgumentTypeError(f"{value}: must be >= 0")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m reg.graph",
        description=(
            "Build the evidence graph for a raw state stream. Same stream and "
            "same envelope parameters, same bytes."
        ),
    )
    subparsers = parser.add_subparsers(dest="command")
    build_parser = subparsers.add_parser(
        "build",
        help="build a SQLite evidence graph from a CSV stream",
        description=(
            "Reads the stream, computes one proprioception-only envelope per "
            "frame, and writes the relationships as intervals. The robot limits "
            "and the human radius are resolved from the scenario named in the "
            "stream's provenance block; a stream without one is refused rather "
            "than guessed at. Expect minutes on a full scenario: an envelope per "
            "frame is the cost, and this is offline batch work."
        ),
    )
    build_parser.add_argument("csv", metavar="CSV", help="the raw stream to read")
    build_parser.add_argument(
        "--out",
        metavar="PATH",
        help="SQLite artifact to write; replaced if it exists. No default.",
    )
    build_parser.add_argument(
        "--horizon",
        type=_positive_float,
        default=ENVELOPE_HORIZON,
        metavar="SECONDS",
        help=(
            f"envelope horizon (default: {ENVELOPE_HORIZON}, docs/plan.md Phase "
            "2). Recorded in the artifact either way."
        ),
    )
    build_parser.add_argument(
        "--n-samples",
        type=_non_negative_int,
        default=ENVELOPE_N_SAMPLES,
        metavar="N",
        help=(
            f"control sequences per envelope (default: {ENVELOPE_N_SAMPLES}). "
            "Cost is linear in this; the envelope is an under-approximation and "
            "grows monotonically with it."
        ),
    )
    build_parser.add_argument(
        "--envelope-seed",
        type=_non_negative_int,
        default=ENVELOPE_SEED,
        metavar="N",
        help=(
            f"seed for the interior control samples (default: {ENVELOPE_SEED}). "
            "Not the scenario seed — that one is in the stream's provenance."
        ),
    )
    build_parser.add_argument(
        "--substep-dt",
        type=_positive_float,
        default=SUBSTEP_DT,
        metavar="SECONDS",
        help=f"envelope integration resolution (default: {SUBSTEP_DT}).",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)

    if args.command != "build":
        parser.error("a subcommand is required. The only one is `build`.")
    if args.out is None:
        parser.error(
            "--out is required and has no default: writing an audit artifact to "
            "a path nobody named is how runs get lost."
        )

    try:
        world = _resolve_world(args.csv)
        result = build(
            args.csv,
            args.out,
            world.limits,
            human_radius=world.human_radius,
            horizon=args.horizon,
            n_samples=args.n_samples,
            seed=args.envelope_seed,
            substep_dt=args.substep_dt,
        )
    except GraphBuildError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except store.StoreError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE

    counts = " ".join(f"{name}={n}" for name, n in sorted(result.edges.items()))
    nodes = " ".join(f"{name}={n}" for name, n in sorted(result.nodes.items()))
    print(
        f"wrote {result.path}: frames={result.frames} "
        f"edges={result.total_edges} ({counts}) nodes ({nodes}) "
        f"bytes={result.size_bytes}"
    )
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
