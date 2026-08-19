"""The audit queries — **Claim 2** — and the module the raw stream cannot reach.

    python -m reg.query runs/contact.sqlite --list
    python -m reg.query runs/contact.sqlite --separation-timeline human
    python -m reg.query runs/contact.sqlite --frames-at-risk human 0.5

Claim 2 is *"audit questions answered from the graph alone, no access to the
original stream."* The word doing the work in that sentence is **alone**, and a
claim that rests on a module's good manners is not a claim. So the enforcement
here is structural, the same way the Layer A boundary is structural:

**This module imports `reg.store` and `reg.tolerances` and nothing else from
this package at module level.** Not `reg.stream`, not `reg.scenarios`, not
`reg.sim`, not `reg.world` — and not `reg.graph` or `reg.bench` either, because
both of those import the first four and an import is one attribute lookup away
from a call. Its only inputs are an open SQLite artifact and query arguments. If
a question needs something the artifact does not hold, that is a
**could-not-evaluate**, not a reason to open the CSV.
`tests/test_query.py::test_importing_reg_query_does_not_import_the_stream` is
the gate: it imports this module in a fresh interpreter and fails if any of
those modules landed in `sys.modules`.

THE ONE DEFERRED IMPORT, AND WHY IT IS DEFERRED
------------------------------------------------
`--verify-chain` (issue #49) calls `reg.chain.verify_chain`, and `reg.chain`
reaches `reg.stream` for the float precision its canonical serialization commits
to. So that import is **inside the function that needs it**, and
`tests/test_query.py::test_the_chain_import_is_deferred` fails if anyone hoists
it to the top of the file. The alternative was a second copy of the
canonicalization here, which would be a second definition of the preimage every
MAC in the record is taken over — the one thing `reg.chain`'s header says must
never exist. `reg.store` does the same thing for the same reason
(`reg.store._record_types`).

Nothing about that softens the claim: chain verification reads the artifact and
a keyring file, and no scene query can reach the deferred module either, because
it is bound inside a call and never at module scope.

WHAT A QUERY RETURNS, AND WHY IT IS NOT PROSE
---------------------------------------------
Every function here returns an `Answer`: a verdict, the layer it was read from,
a structured value, and the tolerances in force on that value. The CLI formats;
the function returns. A query that printed its answer would make the tolerance a
sentence in a terminal rather than a field a caller can test against, and every
downstream comparison would have to re-derive it — which is how two callers end
up disagreeing about what "0.42" was accurate to.

THE THIRD VERDICT NEVER RESOLVES TO THE FIRST
----------------------------------------------
`ANSWERED` and `COULD-NOT-EVALUATE`, and they are different facts from an empty
result:

* *"the entity was never inside the envelope"* is an **answer**. It is a
  closed-world reading of a layer that retains every relationship that held, and
  it is only legitimate where the artifact carries the rule saying so.
* *"this artifact holds no layer that could tell you"* is a **refusal**, and it
  comes back as `COULD-NOT-EVALUATE` with a reason naming what is missing.
* *"there is no such entity"* is a **usage error** — `QueryError`, naming the
  entities that are present. It is not an empty list, because "absence of an
  entity from the graph is not evidence of its absence from the room"
  (docs/lossiness.md *Unanswerable* #2) and an empty timeline would read as
  evidence.

EVERY QUERY DECLARES THE LAYER IT NEEDS
----------------------------------------
Issue #36 measured this exactly: at the DSSAD-aligned occurrence resolution,
`min_separation` and `did_contact_occur` still answer, and `separation_timeline`
does not — the occurrence layer holds events, not states, and the intervals
between events are precisely what it discarded. That finding lived in the
benchmark, where only the benchmark got it. `QUERIES` states it per query, and
`available_layers` reads what a given artifact actually holds, so **any** caller
gets the refusal rather than a plausible answer assembled from the wrong layer.

WHAT IS NOT HERE
----------------
The attestation *queries* of docs/plan.md Phase 7 — `declared_bound`,
`violations`, `verdicts` — and `incident_report`, which composes them. A stub
returning an empty list would make "no violation occurred" indistinguishable
from "this build does not record violations", which is the one confusion this
whole project is about, so they are absent rather than empty.

`--verify-chain` and `--tamper` (issue #49) are here, and they are not queries:
they return a `reg.chain.ChainReport`, not an `Answer`, because a chain walk is
not a question about the scene and has three verdicts of its own. The CLI exits
`0` VERIFIED, `3` BROKEN, `1` COULD-NOT-EVALUATE — three codes because those are
three different facts, and a script that treated "could not check" as "checked
and fine" is the failure mode the whole three-state discipline exists to
prevent.

LAYER
-----
Layer B, mostly, and it says so per query: every scene question names an entity,
and where an entity is comes from perception in any real system (docs/plan.md
Phase 9). The layer tag travels on every edge and this module never invents one.
"""

from __future__ import annotations

import argparse
import math
import sqlite3
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from reg import store
from reg.tolerances import (
    AREA_QUANT_SIGFIGS,
    DISTANCE_TOL_M,
    TIME_TOL_S,
    quantize_time,
)

__all__ = [
    "ANSWERED",
    "COULD_NOT_EVALUATE",
    "EDGE_LAYER",
    "EXIT_BROKEN",
    "EXIT_COULD_NOT_EVALUATE",
    "EXIT_OK",
    "EXIT_USAGE",
    "META_FRAME_COUNT",
    "META_OCCURRENCE_RESOLUTION",
    "META_OCCURRENCE_RETENTION",
    "META_T_FIRST",
    "META_T_LAST",
    "OCCURRENCE_LAYER",
    "QUERIES",
    "Answer",
    "EnvelopeIntersection",
    "FramesAtRisk",
    "OverlapInterval",
    "QueryError",
    "QuerySpec",
    "ReachableEntities",
    "RiskInterval",
    "SeparationTimeline",
    "available_layers",
    "did_contact_occur",
    "entity_ids",
    "first_envelope_intersection",
    "frame_period",
    "frame_times",
    "frames_at_risk",
    "main",
    "min_separation",
    "reachable_entities",
    "render",
    "render_chain_report",
    "run_interval",
    "separation_timeline",
    "time_of_closest_approach",
]

#: The query was answered from the artifact.
ANSWERED = "ANSWERED"

#: The artifact does not hold what the question needs. Spelled exactly as
#: `reg.bench` spells it — `reg.bench` imports this name rather than defining a
#: second string with the same meaning, because a verdict vocabulary with two
#: definitions is a verdict vocabulary that can drift.
COULD_NOT_EVALUATE = "COULD-NOT-EVALUATE"

EXIT_OK = 0

#: The query ran and the artifact could not answer it. Distinct from `EXIT_OK`
#: because a refusal is not an answer, and distinct from `EXIT_USAGE` because
#: nothing about the invocation was wrong — the file is what could not say.
EXIT_COULD_NOT_EVALUATE = 1
EXIT_USAGE = 2

#: `--verify-chain` walked a chain and found a fault in it. Distinct from
#: `EXIT_COULD_NOT_EVALUATE` because a chain that broke and a chain that could
#: not be checked are different facts, and a CI job that collapsed the two would
#: treat a missing keyring as a tampered artifact — or, far worse, the reverse.
EXIT_BROKEN = 3

# --------------------------------------------------------------------------
# The two layers.
#
# NOT `reg.bench`'s three *resolution levels*. `transition` and `per-frame` are
# two densities of one layer and no query can tell them apart — an interval and
# the per-frame rows it expands into assert the same thing. What a query can
# tell apart, and must, is whether the artifact holds relationships-over-
# intervals or only events-at-instants.
# --------------------------------------------------------------------------

#: Relationships as intervals, with their metrics, endpoints at `TIME_TOL_S`.
#: The `edge` table.
EDGE_LAYER = "edge"

#: DSSAD-shaped events at the artifact's stated occurrence resolution. The
#: `occurrence` table.
OCCURRENCE_LAYER = "occurrence"

# --------------------------------------------------------------------------
# The `meta` keys this module reads.
#
# Named here rather than imported from `reg.graph`, and that is the one place
# this module pays for its own isolation: importing the writer would put
# `reg.stream` and `reg.world` one attribute away from every function below,
# which is exactly what this module exists not to have.
#
# The drift that buys is caught rather than tolerated. `tests/test_query.py::
# test_the_meta_keys_this_module_reads_are_the_ones_the_builder_writes` builds a
# real artifact and asserts every key below is in it — the same discipline
# `tests/test_tolerances.py` uses on docs/lossiness.md, and it fails on a rename
# instead of turning every query into a could-not-evaluate months later.
# --------------------------------------------------------------------------

#: The first frame's timestamp, at `TIME_TOL_S`.
META_T_FIRST = "t_first"

#: The last frame's timestamp, at `TIME_TOL_S`.
META_T_LAST = "t_last"

#: How many frames the run had. With `t_first` and `reg.store.META_FRAME_PERIOD`
#: this reconstructs every frame time exactly, which is how the two questions
#: that name *frames* are answered — the artifact deliberately does not mark
#: every frame with a row (docs/lossiness.md *Discarded* #10), so a row count
#: would answer a different and smaller question.
META_FRAME_COUNT = "frame_count"

#: The occurrence layer's retention rule, in prose. Its presence is what makes
#: the closed-world reading of that layer legible: "no `contact_began` row"
#: means no contact only because the file says one would have been written.
META_OCCURRENCE_RETENTION = "occurrence_retention"

#: What occurrence timestamps were rounded to, in seconds. It is the tolerance
#: reported on any answer read from that layer, and it is read from the file
#: rather than assumed — the whole point of the layer is that the resolution is
#: a parameter of the build.
META_OCCURRENCE_RESOLUTION = "occurrence_time_resolution_s"

#: Slack for deciding whether two intervals are frame-adjacent. Half a frame
#: period, so one frame's gap merges and two frames' gap does not, whatever the
#: period is. It is a rounding allowance on values the artifact already
#: quantized, not a tolerance: no answer here is accurate to it, and widening it
#: would merge two separate visits into one.
_ADJACENCY_SLACK_FRAMES = 0.5


class QueryError(Exception):
    """The question, as asked, cannot be put to this artifact.

    A caller error, and distinct from a `COULD-NOT-EVALUATE` verdict on purpose:
    an entity that is not in the entity set, a time outside the run, or a
    threshold that is not a distance are all things the *asker* got wrong, and
    the artifact would answer them for some other question if it answered them
    at all. Every message names what is available, because an error that says
    only "no" leaves the caller guessing at the vocabulary.
    """


# --------------------------------------------------------------------------
# The query set. docs/plan.md Phase 7's scene half, and docs/lossiness.md's
# supported question set 1-4, plus the three scalars issue #36 measured the
# occurrence layer against.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class QuerySpec:
    """One supported question: what it asks, what it needs, what it is good to.

    `answerable_from` is the declaration the issue asks for — the resolution
    level(s) at which the question has an answer at all. A query whose artifact
    holds none of them refuses; it does not assemble something from whatever
    else is in the file.
    """

    name: str
    #: The question in one line, for `--list` and for a reader of the output.
    question: str
    #: The layers this query can be answered from. Refuses without one of them.
    answerable_from: frozenset[str]
    #: Arguments beyond the artifact, in CLI order.
    arguments: tuple[str, ...]
    #: The tolerance in force on the answer, quoted from docs/lossiness.md's
    #: agreement table where it has one. Prose; the numbers travel on `Answer`.
    tolerance: str
    #: Why the layers outside `answerable_from` cannot answer it. Printed in the
    #: refusal, so a caller holding a coarse artifact is told what is missing
    #: rather than that something is.
    why_not: str
    #: `A` or `B`, per docs/plan.md Phase 9. Every scene query is B.
    layer_tag: str


_SCENE_LAYER = "B"

QUERIES: dict[str, QuerySpec] = {
    "separation_timeline": QuerySpec(
        name="separation_timeline",
        question="the minimum robot-to-entity distance at every frame of the run",
        answerable_from=frozenset({EDGE_LAYER}),
        arguments=("ENTITY_ID",),
        tolerance="per frame, |d_graph - d_csv| <= DISTANCE_TOL_M",
        why_not=(
            "The occurrence layer holds events, not states. There is no "
            "per-frame separation in it at any resolution and no honest way to "
            "produce one: the intervals between occurrences are exactly what "
            "that layer discarded (docs/lossiness.md, Level 1, 'Cannot "
            "answer')."
        ),
        layer_tag=_SCENE_LAYER,
    ),
    "first_envelope_intersection": QuerySpec(
        name="first_envelope_intersection",
        question=(
            "when the entity first entered the robot's computed reachable "
            "envelope, and every interval it was inside for"
        ),
        answerable_from=frozenset({EDGE_LAYER}),
        arguments=("ENTITY_ID",),
        tolerance=(
            "|t_graph - t_csv| <= TIME_TOL_S, interval endpoints likewise; "
            "overlap areas at AREA_QUANT_SIGFIGS significant figures"
        ),
        why_not=(
            "The occurrence layer records envelope_entered and envelope_left "
            "at its own resolution and carries no overlap area at all, so it "
            "can locate the entry to that resolution but cannot produce the "
            "intervals this query returns."
        ),
        layer_tag=_SCENE_LAYER,
    ),
    "frames_at_risk": QuerySpec(
        name="frames_at_risk",
        question=(
            "every interval in which the robot-to-entity separation was at or "
            "below a threshold, and how many frames each covers"
        ),
        answerable_from=frozenset({EDGE_LAYER}),
        arguments=("ENTITY_ID", "THRESHOLD_M"),
        tolerance=(
            "interval endpoints to TIME_TOL_S; the threshold test is made on "
            "distances stored to DISTANCE_TOL_M, so a frame whose true "
            "separation is within one quantum of the threshold may fall either "
            "side of it"
        ),
        why_not=(
            "A threshold test is a per-frame question about a metric, and the "
            "occurrence layer retains no metric between events."
        ),
        layer_tag=_SCENE_LAYER,
    ),
    "reachable_entities": QuerySpec(
        name="reachable_entities",
        question=(
            "which entities were ever inside the reachable envelope during a "
            "time window"
        ),
        answerable_from=frozenset({EDGE_LAYER}),
        arguments=("T_START", "T_END"),
        tolerance=(
            "exact set equality — no tolerance; a missing or extra entity is a "
            "failure. The window endpoints are read at TIME_TOL_S"
        ),
        why_not=(
            "The occurrence layer's envelope_entered and envelope_left rows are "
            "timestamped to the occurrence resolution, which is coarser than "
            "the window a caller asks about; set membership derived from them "
            "would be exact-looking and wrong at the edges."
        ),
        layer_tag=_SCENE_LAYER,
    ),
    "min_separation": QuerySpec(
        name="min_separation",
        question="the smallest robot-to-entity separation over the whole run",
        answerable_from=frozenset({EDGE_LAYER, OCCURRENCE_LAYER}),
        arguments=("ENTITY_ID",),
        tolerance="|d_graph - d_csv| <= DISTANCE_TOL_M",
        why_not="",
        layer_tag=_SCENE_LAYER,
    ),
    "time_of_closest_approach": QuerySpec(
        name="time_of_closest_approach",
        question="when the smallest separation of the run was first observed",
        answerable_from=frozenset({EDGE_LAYER, OCCURRENCE_LAYER}),
        arguments=("ENTITY_ID",),
        tolerance=(
            "TIME_TOL_S from the edge layer, the artifact's stated occurrence "
            "resolution from the occurrence layer — two orders of magnitude "
            "apart, and the answer says which one it is"
        ),
        why_not="",
        layer_tag=_SCENE_LAYER,
    ),
    "did_contact_occur": QuerySpec(
        name="did_contact_occur",
        question="whether the robot body and the entity ever intersected",
        answerable_from=frozenset({EDGE_LAYER, OCCURRENCE_LAYER}),
        arguments=("ENTITY_ID",),
        tolerance="exact — a missed or invented contact is a failure",
        why_not="",
        layer_tag=_SCENE_LAYER,
    ),
}


# --------------------------------------------------------------------------
# The answer shapes. Structured values; the CLI formats them and they carry no
# formatting of their own.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Answer:
    """One query's answer, with everything needed to read it.

    `value` is `None` exactly when `verdict` is `COULD-NOT-EVALUATE`, and that
    `None` is a refusal — never a zero, an empty list or a `False`. A separation
    of zero reads as contact and an empty interval set reads as safety; both are
    answers this artifact would have to have earned.

    `tolerances` maps a name to the number in force, and every one of them comes
    from `reg.tolerances` or from the artifact's own `meta`. There is no literal
    tolerance anywhere in this module: docs/lossiness.md makes `reg/tolerances.py`
    the only place any of the four may be assigned.
    """

    query: str
    verdict: str
    #: The layer the answer was read from, or `None` where none could answer.
    layer: str | None
    value: object | None
    tolerances: Mapping[str, float] = field(default_factory=dict)
    #: One line: what was read, or why nothing could be. Never empty — an answer
    #: whose provenance is blank is one nobody can check.
    reason: str = ""

    @property
    def answered(self) -> bool:
        return self.verdict == ANSWERED


@dataclass(frozen=True)
class SeparationTimeline:
    """docs/lossiness.md query 1, in full: one distance per frame of the run.

    `samples` is `(t, min_distance)` in frame order and covers **every** frame,
    not every retained row. The artifact stores intervals and deliberately does
    not mark each frame (*Discarded* #10); the frame times come from
    `t_first`, `frame_period_s` and `frame_count` in `meta`, and a frame no
    interval covers makes the whole query a could-not-evaluate rather than a
    short list — a short list compared elementwise against anything else would
    silently line frame 40 up against frame 41.
    """

    entity_id: str
    samples: tuple[tuple[float, float], ...]
    frame_period_s: float

    @property
    def frames(self) -> int:
        return len(self.samples)


@dataclass(frozen=True)
class OverlapInterval:
    """One span during which an entity was inside the envelope.

    `max_overlap_area` is the largest overlap on any edge row in the span — a
    maximum over values the artifact retains, not an average of them or an
    integral over the gaps. An `INTERSECTS` edge closes and reopens whenever the
    overlap crosses an `AREA_QUANT_SIGFIGS` boundary, so a single visit is
    carried by many rows; those are metric steps and this merges them back into
    the relationship they belong to.
    """

    t_start: float
    t_end: float
    frames: int
    max_overlap_area: float


@dataclass(frozen=True)
class EnvelopeIntersection:
    """docs/lossiness.md query 2.

    `t_first is None` with an empty `intervals` is the **negative answer** — the
    entity was never inside — and it is legitimate only because the edge layer
    retains every relationship that held (*Retained* #1). The refusal for an
    artifact with no edge layer is the `Answer`'s verdict, one level up, and the
    two must not be read as the same thing.
    """

    entity_id: str
    t_first: float | None
    intervals: tuple[OverlapInterval, ...]


@dataclass(frozen=True)
class RiskInterval:
    """One span at or below the threshold, with the worst separation in it."""

    t_start: float
    t_end: float
    frames: int
    min_distance: float


@dataclass(frozen=True)
class FramesAtRisk:
    """docs/lossiness.md query 3.

    `frames` counts frames, and it counts them by dividing each interval by
    `frame_period_s` from `meta` rather than by counting rows. That is the
    better answer and not merely the available one: a row count would depend on
    which frames happened to anchor an edge, which is a fact about the retention
    rule and not about the run (docs/lossiness.md *Discarded* #10).

    The intervals span the whole run and are **not** truncated at the first
    contact. docs/plan.md Phase 7 words this query as "before a contact event";
    truncating here would silently drop time in which the separation really was
    below the threshold, so the whole set is returned and `did_contact_occur`
    answers the other half.
    """

    entity_id: str
    threshold_m: float
    intervals: tuple[RiskInterval, ...]
    frames: int
    frame_period_s: float


@dataclass(frozen=True)
class ReachableEntities:
    """docs/lossiness.md query 4. **Exact set equality, no tolerance.**

    `declared` is every entity in the artifact's entity set, so an empty
    `entity_ids` reads as "none of these was inside" rather than as "this file
    knows of nothing". Absence of an entity from the entity set is not evidence
    of its absence from the room (*Unanswerable* #2), and the two sentences have
    to be distinguishable in the output.
    """

    t_start: float
    t_end: float
    entity_ids: tuple[str, ...]
    declared: tuple[str, ...]


# --------------------------------------------------------------------------
# Reading the artifact's own account of itself
# --------------------------------------------------------------------------


def _meta(conn: sqlite3.Connection, key: str) -> str:
    value = store.get_meta(conn, key)
    if value is None:
        raise QueryError(
            f"this artifact has no meta[{key!r}], so it does not state a fact "
            "every answer below depends on. Substituting one would put a number "
            "in an audit answer that nothing in the file produced."
        )
    return value


def _meta_float(conn: sqlite3.Connection, key: str) -> float:
    raw = _meta(conn, key)
    try:
        return float(raw)
    except ValueError as exc:
        raise QueryError(f"meta[{key!r}] is {raw!r}, not a number.") from exc


def frame_period(conn: sqlite3.Connection) -> float:
    """The stream's frame period, in seconds, from the artifact's provenance.

    `reg.graph` refuses a stream whose period is not uniform to `TIME_TOL_S`, so
    this one number plus `t_first` and `frame_count` reconstructs the sampling
    exactly. It is what the two frame-counting questions divide by.
    """
    period = _meta_float(conn, store.META_FRAME_PERIOD)
    if not period > 0.0:
        raise QueryError(
            f"meta[{store.META_FRAME_PERIOD!r}] is {period}. A run whose frames "
            "are zero seconds apart has no timeline, and every frame count "
            "below would be a division by it."
        )
    return period


def run_interval(conn: sqlite3.Connection) -> tuple[float, float]:
    """`(t_first, t_last)` — the interval this artifact has any evidence about.

    A question about an instant outside it is refused rather than answered from
    the nearest interval: the artifact says nothing about that instant, and the
    neighbouring answer is an answer about a different time.
    """
    t_first = _meta_float(conn, META_T_FIRST)
    t_last = _meta_float(conn, META_T_LAST)
    if t_last < t_first:
        raise QueryError(
            f"this artifact says the run ran from {t_first} to {t_last}, which "
            "is backwards. No window can be checked against it."
        )
    return t_first, t_last


def frame_times(conn: sqlite3.Connection) -> tuple[float, ...]:
    """Every frame's timestamp, quantized, in order.

    From `t_first`, `frame_period_s` and `frame_count` rather than from the
    rows: since issue #29 the rows deliberately do not mark every frame, so a
    read off the rows would say how many frames anchored something — a different
    question, and a smaller number.
    """
    period = frame_period(conn)
    t_first = _meta_float(conn, META_T_FIRST)
    count = int(_meta_float(conn, META_FRAME_COUNT))
    if count < 1:
        raise QueryError(
            f"meta[{META_FRAME_COUNT!r}] is {count}. A run of no frames is a "
            "build that did not happen, not a run in which nothing was observed."
        )
    return tuple(quantize_time(t_first + i * period) for i in range(count))


def entity_ids(conn: sqlite3.Connection) -> tuple[str, ...]:
    """Every entity the artifact declares, in id order."""
    rows = conn.execute("SELECT entity_id FROM entity ORDER BY entity_id").fetchall()
    return tuple(str(row["entity_id"]) for row in rows)


def available_layers(conn: sqlite3.Connection) -> frozenset[str]:
    """Which layers this artifact actually holds rows in.

    Read off the file rather than inferred from the schema version: a view with
    its edge table emptied has the column but not the evidence, and a query that
    trusted the schema would return an empty answer where it owes a refusal.
    """
    found: set[str] = set()
    for layer, table in ((EDGE_LAYER, "edge"), (OCCURRENCE_LAYER, "occurrence")):
        if conn.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone() is not None:  # noqa: S608
            found.add(layer)
    return frozenset(found)


def _require_entity(conn: sqlite3.Connection, entity_id: str) -> str:
    """`entity_id`, or a `QueryError` naming every entity that is present.

    Never an empty answer. "Absence of an entity from the graph is not evidence
    of its absence from the room" (docs/lossiness.md *Unanswerable* #2), so a
    timeline of no frames for an entity nobody declared would be evidence of
    something that was never recorded.
    """
    entity_id = str(entity_id)
    known = entity_ids(conn)
    if entity_id in known:
        return entity_id
    if not known:
        raise QueryError(
            f"{entity_id!r} is not in this artifact, which declares no entities "
            "at all. Nothing was ever entered into its entity set, so it holds "
            "no evidence about anything in the scene."
        )
    raise QueryError(
        f"{entity_id!r} is not an entity in this artifact. It declares "
        f"{list(known)}. An entity that was never declared leaves no trace, so "
        "an empty answer for it would read as evidence that it was not there "
        "(docs/lossiness.md Unanswerable #2)."
    )


def _in_edge_layer(conn: sqlite3.Connection, entity_id: str) -> bool:
    """Whether the edge layer holds any relationship at all with this entity.

    The precondition for every *negative* answer below. With no edge naming the
    entity the layer is silent about it, and silence is not "the relationship
    never held" — the builder emits a `SEPARATION` interval for every entity at
    every frame, so an entity with no edges is a filtered or broken artifact,
    not a quiet run.
    """
    row = conn.execute(
        "SELECT 1 FROM edge WHERE dst_id = ? LIMIT 1", (str(entity_id),)
    ).fetchone()
    return row is not None


# --------------------------------------------------------------------------
# Interval arithmetic
# --------------------------------------------------------------------------


def _frames_in(t_start: float, t_end: float, period: float) -> int:
    """How many sampled frames an interval covers. Never a row count."""
    span = round((float(t_end) - float(t_start)) / period)
    return int(span) + 1


def _merge_adjacent(
    rows: Sequence[sqlite3.Row], period: float
) -> list[list[sqlite3.Row]]:
    """Group rows into runs of frame-adjacent intervals, in time order.

    An edge closes and a new one opens whenever a *metric* crosses a
    quantization boundary, and the new one starts at the very next frame. Those
    are steps within one relationship, and an audit answer that listed them
    separately would report 79 visits where the human made one. A relationship
    that genuinely ceased leaves a gap of at least two frame periods, which is
    what `_ADJACENCY_SLACK_FRAMES` distinguishes — half a period, so one frame's
    gap merges and two frames' gap does not, at any frame rate.
    """
    groups: list[list[sqlite3.Row]] = []
    limit = period * (1.0 + _ADJACENCY_SLACK_FRAMES)
    for row in sorted(rows, key=lambda r: (float(r["t_start"]), int(r["edge_id"]))):
        if groups and float(row["t_start"]) - float(groups[-1][-1]["t_end"]) <= limit:
            groups[-1].append(row)
        else:
            groups.append([row])
    return groups


def _covering_values(
    rows: Sequence[sqlite3.Row], times: Sequence[float], column: str
) -> tuple[tuple[float, float], ...] | None:
    """The value in force at each of `times`, or `None` if one is uncovered.

    `None` rather than a shorter list, for the reason `SeparationTimeline` gives:
    a timeline missing frames is a could-not-evaluate for the whole query, and a
    short list is silently misaligned rather than visibly incomplete.
    """
    intervals = sorted(
        ((float(r["t_start"]), float(r["t_end"]), r[column]) for r in rows),
        key=lambda item: item[0],
    )
    out: list[tuple[float, float]] = []
    index = 0
    for t in times:
        while index < len(intervals) and intervals[index][1] < t:
            index += 1
        if index >= len(intervals) or intervals[index][0] > t:
            return None
        value = intervals[index][2]
        if value is None:  # pragma: no cover - the schema CHECKs metric presence
            return None
        out.append((t, float(value)))
    return tuple(out)


def _refuse(spec: QuerySpec, layers: frozenset[str], detail: str) -> Answer:
    """A `COULD-NOT-EVALUATE` that names what is missing and what is present."""
    have = ", ".join(sorted(layers)) if layers else "no layer at all"
    return Answer(
        query=spec.name,
        verdict=COULD_NOT_EVALUATE,
        layer=None,
        value=None,
        tolerances={},
        reason=(
            f"{spec.name} is answerable from the "
            f"{' or '.join(sorted(spec.answerable_from))} layer; this artifact "
            f"holds {have}. {detail}"
        ),
    )


def _no_layer(spec: QuerySpec, layers: frozenset[str]) -> Answer:
    return _refuse(spec, layers, spec.why_not or "")


def _layer_for(spec: QuerySpec, layers: frozenset[str]) -> str | None:
    """Which layer answers this query in this artifact, or `None` for neither.

    The finest layer the artifact holds that the query declares — **and there is
    no fallback from it to a coarser one within a single file**. A query that
    dropped to the occurrence layer because the edge layer had no row for this
    entity would answer at a resolution decided by which rows happened to be
    missing, and the tolerance it reported would be a fact about the damage
    rather than about the build. An edge layer that is present and silent about
    an entity is silent, and silence is a refusal.
    """
    for layer in (EDGE_LAYER, OCCURRENCE_LAYER):
        if layer in spec.answerable_from and layer in layers:
            return layer
    return None


def _occurrence_resolution(conn: sqlite3.Connection) -> float:
    """What the occurrence layer's timestamps were rounded to, from the file.

    Read, never assumed. UN R157's ±1.0 s is the *builder's* default and the
    build records what it was actually given; an answer that quoted the
    regulation's figure for an artifact built at a different resolution would
    state a precision the file does not have.
    """
    resolution = _meta_float(conn, META_OCCURRENCE_RESOLUTION)
    if not resolution > 0.0:
        raise QueryError(
            f"meta[{META_OCCURRENCE_RESOLUTION!r}] is {resolution}. A resolution "
            "of zero would claim the occurrence timestamps are exact, which is "
            "the one thing that layer does not promise."
        )
    return resolution


# --------------------------------------------------------------------------
# The scene queries. docs/plan.md Phase 7, queries 1-4, plus the three scalars
# issue #36 measured the occurrence layer against.
# --------------------------------------------------------------------------


def separation_timeline(conn: sqlite3.Connection, entity_id: str) -> Answer:
    """Query 1 — the minimum robot-to-entity distance at every frame.

    **Edge layer only, and that is the finding issue #36 measured.** The
    occurrence layer holds events; the intervals between them are exactly what
    it discarded, and there is no honest way to produce a per-frame series from
    it. That refusal used to live in the benchmark. It lives here now, so every
    caller gets it.
    """
    spec = QUERIES["separation_timeline"]
    entity_id = _require_entity(conn, entity_id)
    layers = available_layers(conn)
    if EDGE_LAYER not in layers:
        return _no_layer(spec, layers)

    rows = store.read_edges(conn, edge_type="SEPARATION", dst_id=entity_id)
    if not rows:
        return _refuse(
            spec,
            layers,
            f"the edge layer holds no SEPARATION interval for {entity_id!r}. An "
            "artifact silent about a separation has not observed a large one.",
        )
    times = frame_times(conn)
    samples = _covering_values(rows, times, "min_distance")
    if samples is None:
        return _refuse(
            spec,
            layers,
            f"the {len(rows)} SEPARATION interval(s) for {entity_id!r} do not "
            f"cover all {len(times)} frames of the run. A partial timeline is "
            "not a timeline.",
        )
    return Answer(
        query=spec.name,
        verdict=ANSWERED,
        layer=EDGE_LAYER,
        value=SeparationTimeline(
            entity_id=entity_id,
            samples=samples,
            frame_period_s=frame_period(conn),
        ),
        tolerances={"distance_m": DISTANCE_TOL_M, "time_s": TIME_TOL_S},
        reason=(
            f"read from {len(rows)} SEPARATION interval(s) covering all "
            f"{len(times)} frames"
        ),
    )


def first_envelope_intersection(conn: sqlite3.Connection, entity_id: str) -> Answer:
    """Query 2 — first entry into the reachable set, plus the overlap intervals.

    The intervals are the *relationship's*, not the edge rows': an `INTERSECTS`
    edge also closes and reopens on every `AREA_QUANT_SIGFIGS` step of the
    overlap, and those are metric steps rather than the entity leaving and
    coming back. `_merge_adjacent` puts them back together and the peak overlap
    of each visit travels on the merged interval.
    """
    spec = QUERIES["first_envelope_intersection"]
    entity_id = _require_entity(conn, entity_id)
    layers = available_layers(conn)
    if EDGE_LAYER not in layers:
        return _no_layer(spec, layers)
    if not _in_edge_layer(conn, entity_id):
        return _refuse(
            spec,
            layers,
            f"the edge layer holds no relationship of any kind with "
            f"{entity_id!r}, so its silence about an intersection is silence "
            "and not a negative.",
        )

    period = frame_period(conn)
    rows = store.read_edges(conn, edge_type="INTERSECTS", dst_id=entity_id)
    intervals = tuple(
        OverlapInterval(
            t_start=float(group[0]["t_start"]),
            t_end=float(group[-1]["t_end"]),
            frames=_frames_in(
                float(group[0]["t_start"]), float(group[-1]["t_end"]), period
            ),
            max_overlap_area=max(float(r["overlap_area"]) for r in group),
        )
        for group in _merge_adjacent(rows, period)
    )
    return Answer(
        query=spec.name,
        verdict=ANSWERED,
        layer=EDGE_LAYER,
        value=EnvelopeIntersection(
            entity_id=entity_id,
            t_first=intervals[0].t_start if intervals else None,
            intervals=intervals,
        ),
        tolerances={"time_s": TIME_TOL_S, "area_sigfigs": float(AREA_QUANT_SIGFIGS)},
        reason=(
            f"{len(rows)} INTERSECTS row(s) merged into {len(intervals)} "
            "visit(s)"
            if rows
            else (
                "the edge layer records relationships with this entity and no "
                "INTERSECTS interval among them, so it was never inside the "
                "computed envelope"
            )
        ),
    )


def frames_at_risk(
    conn: sqlite3.Connection, entity_id: str, threshold: float
) -> Answer:
    """Query 3 — every interval at or below `threshold` metres of separation.

    `threshold` is required and there is no default. What counts as risk is a
    property of the deployment, not of this artifact, and a plausible 0.5 m
    invented here would be indistinguishable downstream from one an operator
    supplied — which is the whole failure mode this project is about.

    The comparison is made on distances the artifact stores to `DISTANCE_TOL_M`,
    so a frame whose true separation sits within a quantum of the threshold may
    fall either side of it. That is the resolution the artifact advertises
    (docs/lossiness.md *Unanswerable* #4), and the tolerance travels on the
    answer rather than being discovered later.
    """
    spec = QUERIES["frames_at_risk"]
    entity_id = _require_entity(conn, entity_id)
    threshold = _positive_distance(threshold, "threshold")
    layers = available_layers(conn)
    if EDGE_LAYER not in layers:
        return _no_layer(spec, layers)

    rows = store.read_edges(conn, edge_type="SEPARATION", dst_id=entity_id)
    if not rows:
        return _refuse(
            spec,
            layers,
            f"the edge layer holds no SEPARATION interval for {entity_id!r}, so "
            "there is nothing to compare against the threshold. An empty "
            "interval set here would read as 'never at risk'.",
        )

    period = frame_period(conn)
    breached = [r for r in rows if float(r["min_distance"]) <= threshold]
    intervals = tuple(
        RiskInterval(
            t_start=float(group[0]["t_start"]),
            t_end=float(group[-1]["t_end"]),
            frames=_frames_in(
                float(group[0]["t_start"]), float(group[-1]["t_end"]), period
            ),
            min_distance=min(float(r["min_distance"]) for r in group),
        )
        for group in _merge_adjacent(breached, period)
    )
    return Answer(
        query=spec.name,
        verdict=ANSWERED,
        layer=EDGE_LAYER,
        value=FramesAtRisk(
            entity_id=entity_id,
            threshold_m=threshold,
            intervals=intervals,
            frames=sum(i.frames for i in intervals),
            frame_period_s=period,
        ),
        tolerances={"distance_m": DISTANCE_TOL_M, "time_s": TIME_TOL_S},
        reason=(
            f"{len(breached)} of {len(rows)} SEPARATION interval(s) are at or "
            f"below {threshold} m, merged into {len(intervals)} span(s)"
        ),
    )


def reachable_entities(
    conn: sqlite3.Connection, t_start: float, t_end: float
) -> Answer:
    """Query 4 — which entities were ever inside the envelope in a window.

    **Exact set equality, no tolerance** (docs/lossiness.md's agreement table): a
    missing or extra entity is a failure, not a near miss. The window endpoints
    are read at `TIME_TOL_S`, which is the resolution the artifact's interval
    endpoints were recorded at and the finest anything here may report.

    A window outside the run is refused rather than clamped. Clamping would
    answer a question about a different window and say nothing about having done
    so.
    """
    spec = QUERIES["reachable_entities"]
    t_start = _finite(t_start, "t_start")
    t_end = _finite(t_end, "t_end")
    if t_end < t_start:
        raise QueryError(
            f"the window [{t_start}, {t_end}] runs backwards. A backwards window "
            "matches no interval, so it would come back as 'no entity was "
            "inside' rather than as the mistake it is."
        )
    first, last = run_interval(conn)
    if t_start < first - TIME_TOL_S or t_end > last + TIME_TOL_S:
        raise QueryError(
            f"the window [{t_start}, {t_end}] is not inside this run, which "
            f"spans [{first}, {last}]. The artifact holds no evidence outside "
            "that interval, and answering from the nearest one would answer "
            "about a different time."
        )

    layers = available_layers(conn)
    if EDGE_LAYER not in layers:
        return _no_layer(spec, layers)

    window_start = quantize_time(t_start)
    window_end = quantize_time(t_end)
    rows = store.read_edges(conn, edge_type="INTERSECTS")
    inside = sorted(
        {
            str(row["dst_id"])
            for row in rows
            if float(row["t_start"]) <= window_end
            and float(row["t_end"]) >= window_start
        }
    )
    declared = entity_ids(conn)
    return Answer(
        query=spec.name,
        verdict=ANSWERED,
        layer=EDGE_LAYER,
        value=ReachableEntities(
            t_start=window_start,
            t_end=window_end,
            entity_ids=tuple(inside),
            declared=declared,
        ),
        tolerances={"time_s": TIME_TOL_S},
        reason=(
            f"{len(rows)} INTERSECTS interval(s) tested against "
            f"[{window_start}, {window_end}]; {len(declared)} entity/entities "
            "declared"
        ),
    )


def min_separation(conn: sqlite3.Connection, entity_id: str) -> Answer:
    """The smallest robot-to-entity separation over the run, in metres.

    Answerable from either layer at the same tolerance — the occurrence row was
    derived from the same observations the edge rows carry, so the two agree by
    construction rather than by luck. Which one answers is decided by what the
    artifact holds (`_layer_for`), never by which one happens to have a row.
    """
    spec = QUERIES["min_separation"]
    entity_id = _require_entity(conn, entity_id)
    layers = available_layers(conn)
    layer = _layer_for(spec, layers)
    if layer is None:
        return _no_layer(spec, layers)

    if layer == EDGE_LAYER:
        rows = store.read_edges(conn, edge_type="SEPARATION", dst_id=entity_id)
        if not rows:
            return _refuse(
                spec,
                layers,
                f"the edge layer holds no SEPARATION interval for {entity_id!r}. "
                "An artifact silent about a separation has not observed one of "
                "zero, and must not be read as having observed a large one.",
            )
        return Answer(
            query=spec.name,
            verdict=ANSWERED,
            layer=EDGE_LAYER,
            value=min(float(r["min_distance"]) for r in rows),
            tolerances={"distance_m": DISTANCE_TOL_M},
            reason=f"smallest of {len(rows)} SEPARATION interval(s)",
        )

    rows = store.read_occurrences(
        conn, occurrence_type="closest_approach", entity_id=entity_id
    )
    if not rows:
        return _refuse(
            spec,
            layers,
            f"no closest_approach occurrence names {entity_id!r}, and this "
            "artifact holds no edge layer to fall back on.",
        )
    return Answer(
        query=spec.name,
        verdict=ANSWERED,
        layer=OCCURRENCE_LAYER,
        value=float(rows[0]["value"]),
        tolerances={"distance_m": DISTANCE_TOL_M},
        reason="from the closest_approach occurrence",
    )


def time_of_closest_approach(conn: sqlite3.Connection, entity_id: str) -> Answer:
    """When the run's smallest separation to `entity_id` was first observed.

    The tolerance on this answer is **two orders of magnitude** apart between
    the layers — `TIME_TOL_S` from the edges, the artifact's stated occurrence
    resolution from the occurrences — so the answer carries which layer it came
    from and what that layer's timestamps are good to. Quoting one figure for
    both is how a ±1 s event ends up in a report reading as ±10 ms.
    """
    spec = QUERIES["time_of_closest_approach"]
    entity_id = _require_entity(conn, entity_id)
    layers = available_layers(conn)
    layer = _layer_for(spec, layers)
    if layer is None:
        return _no_layer(spec, layers)

    if layer == EDGE_LAYER:
        rows = store.read_edges(conn, edge_type="SEPARATION", dst_id=entity_id)
        if not rows:
            return _refuse(
                spec,
                layers,
                f"the edge layer holds no SEPARATION interval for {entity_id!r}, "
                "so there is no closest approach in it to locate.",
            )
        smallest = min(float(r["min_distance"]) for r in rows)
        earliest = min(
            float(r["t_start"])
            for r in rows
            if float(r["min_distance"]) == smallest
        )
        return Answer(
            query=spec.name,
            verdict=ANSWERED,
            layer=EDGE_LAYER,
            value=earliest,
            tolerances={"time_s": TIME_TOL_S, "distance_m": DISTANCE_TOL_M},
            reason=(
                f"earliest SEPARATION interval whose min_distance is the run's "
                f"smallest ({smallest} m)"
            ),
        )

    rows = store.read_occurrences(
        conn, occurrence_type="closest_approach", entity_id=entity_id
    )
    if not rows:
        return _refuse(
            spec,
            layers,
            f"no closest_approach occurrence names {entity_id!r}, and this "
            "artifact holds no edge layer to fall back on.",
        )
    return Answer(
        query=spec.name,
        verdict=ANSWERED,
        layer=OCCURRENCE_LAYER,
        value=float(rows[0]["t"]),
        tolerances={
            "time_s": _occurrence_resolution(conn),
            "distance_m": DISTANCE_TOL_M,
        },
        reason=(
            "from the closest_approach occurrence, at this artifact's stated "
            "occurrence resolution"
        ),
    )


def did_contact_occur(conn: sqlite3.Connection, entity_id: str) -> Answer:
    """Whether the robot body and the entity ever intersected.

    **Two closed-world readings, and each one is licensed by something in the
    file rather than by convenience.**

    From the edge layer: the layer retains every relationship that held
    (docs/lossiness.md *Retained* #1), so no `CONTACT` interval means no contact
    — but only for an entity the layer holds *some* relationship with. An entity
    it says nothing at all about is a filtered artifact, and that is a refusal.

    From the occurrence layer: no `contact_began` row means no contact, and this
    is legitimate *only* because the artifact carries `occurrence_retention` in
    its own `meta` saying one would have been written. That is the same reason
    DSSAD's absent occurrence flag is readable. Without the rule in the file it
    is silence, and silence is not agreement — so a file missing it refuses.
    """
    spec = QUERIES["did_contact_occur"]
    entity_id = _require_entity(conn, entity_id)
    layers = available_layers(conn)
    layer = _layer_for(spec, layers)
    if layer is None:
        return _no_layer(spec, layers)

    if layer == EDGE_LAYER:
        if not _in_edge_layer(conn, entity_id):
            return _refuse(
                spec,
                layers,
                f"the edge layer holds no relationship of any kind with "
                f"{entity_id!r}. Its silence about a contact is silence, not a "
                "negative.",
            )
        rows = store.read_edges(conn, edge_type="CONTACT", dst_id=entity_id)
        return Answer(
            query=spec.name,
            verdict=ANSWERED,
            layer=EDGE_LAYER,
            value=bool(rows),
            tolerances={},
            reason=(
                f"{len(rows)} CONTACT interval(s); the edge layer retains every "
                "relationship that held, so none means none"
            ),
        )

    if store.get_meta(conn, META_OCCURRENCE_RETENTION) is None:
        return _refuse(
            spec,
            layers,
            f"this artifact does not state meta[{META_OCCURRENCE_RETENTION!r}], "
            "so it does not say that a contact would have been recorded. "
            "Without that rule the absence of a contact_began row is silence, "
            "and silence is not a negative.",
        )
    rows = store.read_occurrences(
        conn, occurrence_type="contact_began", entity_id=entity_id
    )
    return Answer(
        query=spec.name,
        verdict=ANSWERED,
        layer=OCCURRENCE_LAYER,
        value=bool(rows),
        tolerances={},
        reason=(
            f"{len(rows)} contact_began occurrence(s), read closed-world under "
            f"meta[{META_OCCURRENCE_RETENTION!r}]"
        ),
    )


# --------------------------------------------------------------------------
# Argument validation. Every refusal names the value it refused.
# --------------------------------------------------------------------------


def _finite(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise QueryError(f"{name} must be a number, got {value!r}.")
    out = float(value)
    if not math.isfinite(out):
        raise QueryError(
            f"{name} is {out!r}. A non-finite bound compares true against every "
            "interval in the file, which is not a question about this run."
        )
    return out


def _positive_distance(value: object, name: str) -> float:
    out = _finite(value, name)
    if not out > 0.0:
        raise QueryError(
            f"{name} is {out}, which is not a positive distance. A threshold of "
            "zero asks which frames had a separation at or below zero — that is "
            "the contact question, and `did_contact_occur` answers it without "
            "pretending to be a distance test."
        )
    return out


# --------------------------------------------------------------------------
# Rendering. Pure: an `Answer` in, text out. The functions above return values;
# this is the only place any of them becomes prose.
# --------------------------------------------------------------------------


def _tolerance_text(tolerances: Mapping[str, float]) -> str:
    if not tolerances:
        return "none — this answer is exact or is not a number"
    return " ".join(f"{name}={value:g}" for name, value in sorted(tolerances.items()))


def render(answer: Answer) -> str:
    """One answer as text. Every line is derived from the `Answer`; nothing here
    reads the artifact, so a caller can format an answer it did not fetch."""
    spec = QUERIES[answer.query]
    lines = [
        f"query:      {answer.query}",
        f"question:   {spec.question}",
        f"verdict:    {answer.verdict}",
        f"layer:      {answer.layer if answer.layer is not None else 'n/a'} "
        f"(evidence layer {spec.layer_tag})",
        f"tolerances: {_tolerance_text(answer.tolerances)}",
        f"note:       {answer.reason}",
    ]
    if not answer.answered:
        return "\n".join(lines)
    lines.append("")
    lines.extend(_render_value(answer.value))
    return "\n".join(lines)


def render_chain_report(report: object) -> str:
    """A `reg.chain.ChainReport` as text. Reads nothing but the report.

    Every failure gets a line naming the record it belongs to, and the counts
    are printed for every chain including a broken one. "BROKEN" on its own is
    not usable evidence: an assessor's next question is *which record, and what
    changed*, and this is where that question is answered.

    Annotated `object` rather than `ChainReport` for one reason: naming the type
    would mean importing `reg.chain` at module level, which is exactly what the
    module header says this file does not do.
    """
    lines = [f"verify-chain: {report.state.value}", ""]
    for result in report.chains:
        stated = (
            "the artifact states no count"
            if result.stated_records is None
            else f"{result.stated_records} stated"
        )
        lines.extend(
            [
                f"chain:           {result.chain} ({result.kind})",
                f"  state:         {result.state.value}",
                f"  records:       {result.records_walked} walked; {stated}",
                f"  links checked: {result.links_checked}",
                f"  MACs checked:  {result.macs_checked}",
            ]
        )
        if not result.failures:
            lines.append("  failures:      none")
        else:
            lines.append(f"  failures:      {len(result.failures)}")
            lines.extend(f"    - {failure.describe()}" for failure in result.failures)
        lines.append("")
    return "\n".join(lines).rstrip()


def _render_value(value: object) -> list[str]:
    if isinstance(value, SeparationTimeline):
        out = [
            f"entity {value.entity_id}: {value.frames:,} frame(s) at "
            f"{value.frame_period_s:g} s",
            "t_s        min_distance_m",
        ]
        out.extend(f"{t:<10.4f} {d:.4f}" for t, d in value.samples)
        return out
    if isinstance(value, EnvelopeIntersection):
        if value.t_first is None:
            return [
                f"entity {value.entity_id} was never inside the computed "
                "envelope during this run"
            ]
        out = [
            f"entity {value.entity_id} first entered at t={value.t_first:.4f} s",
            "t_start_s  t_end_s    frames  max_overlap_area_m2",
        ]
        out.extend(
            f"{i.t_start:<10.4f} {i.t_end:<10.4f} {i.frames:<7,} "
            f"{i.max_overlap_area:g}"
            for i in value.intervals
        )
        return out
    if isinstance(value, FramesAtRisk):
        out = [
            f"entity {value.entity_id} at or below {value.threshold_m:g} m: "
            f"{value.frames:,} frame(s) in {len(value.intervals):,} interval(s)"
        ]
        if not value.intervals:
            out.append(
                "no interval in this run is at or below that separation"
            )
            return out
        out.append("t_start_s  t_end_s    frames  min_distance_m")
        out.extend(
            f"{i.t_start:<10.4f} {i.t_end:<10.4f} {i.frames:<7,} "
            f"{i.min_distance:.4f}"
            for i in value.intervals
        )
        return out
    if isinstance(value, ReachableEntities):
        out = [
            f"window [{value.t_start:.4f}, {value.t_end:.4f}] s",
            f"declared entities: {', '.join(value.declared)}",
        ]
        out.append(
            "inside the envelope: " + ", ".join(value.entity_ids)
            if value.entity_ids
            else "inside the envelope: none of them"
        )
        return out
    if isinstance(value, bool):
        return [str(value)]
    if isinstance(value, float):
        return [f"{value:.4f}"]
    raise QueryError(  # pragma: no cover - every answer shape is above
        f"no renderer for {type(value).__name__}."
    )


def _list_text() -> str:
    """`--list`: the supported queries, what each needs, and what it is good to.

    The whole vocabulary, so a caller who got a name wrong sees the set rather
    than being told their name is not in it. Queries 5-8 of
    docs/lossiness.md's supported set are named as *absent* at the bottom: an
    attestation query missing from this list is a milestone that has not landed,
    and leaving it unmentioned would let "no violations" and "this build does
    not record violations" look the same.
    """
    lines = ["supported queries (docs/plan.md Phase 7, scene half):", ""]
    for spec in QUERIES.values():
        flag = "--" + spec.name.replace("_", "-")
        args = " ".join(spec.arguments)
        lines.append(f"  {flag} {args}".rstrip())
        lines.append(f"      {spec.question}")
        lines.append(
            f"      answerable from: {', '.join(sorted(spec.answerable_from))} "
            f"layer(s); evidence layer {spec.layer_tag}"
        )
        lines.append(f"      tolerance: {spec.tolerance}")
        lines.append("")
    lines.append(
        "not a query, and not an Answer: --verify-chain walks the two record "
        "chains this artifact holds and reports VERIFIED, BROKEN or "
        "COULD-NOT-EVALUATE per chain (exit 0, 3, 1). --keyring names the "
        "keyring the records were signed under; without one the links are "
        "still walked and no MAC is checked, which is a COULD-NOT-EVALUATE and "
        "never a pass. --tamper CHAIN:SELECTOR:OP alters one record in a copy "
        "of the artifact and verifies the copy, so that the walk can be seen "
        "to say no; it never writes to the artifact."
    )
    lines.append("")
    lines.append(
        "not implemented, and absent rather than empty: declared_bound, "
        "violations, verdicts and incident_report (docs/lossiness.md queries "
        "5-9). A stub returning an empty list would make 'it did not happen' "
        "indistinguishable from 'this build does not record it'."
    )
    return "\n".join(lines)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m reg.query",
        description=(
            "Answer an audit question from an evidence graph — and from nothing "
            "else. This module cannot read the raw stream: it imports neither "
            "the stream reader nor any module that does, and a test asserts it."
        ),
    )
    parser.add_argument(
        "artifact",
        metavar="ARTIFACT",
        nargs="?",
        help="a SQLite artifact from `python -m reg.graph build`",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--list",
        action="store_true",
        help="name every supported query and the layer it needs, then exit",
    )
    group.add_argument(
        "--separation-timeline",
        metavar="ENTITY_ID",
        help=QUERIES["separation_timeline"].question,
    )
    group.add_argument(
        "--first-envelope-intersection",
        metavar="ENTITY_ID",
        help=QUERIES["first_envelope_intersection"].question,
    )
    group.add_argument(
        "--frames-at-risk",
        nargs=2,
        metavar=("ENTITY_ID", "THRESHOLD_M"),
        help=(
            QUERIES["frames_at_risk"].question
            + " — the threshold is required and has no default"
        ),
    )
    group.add_argument(
        "--reachable-entities",
        nargs=2,
        metavar=("T_START", "T_END"),
        help=QUERIES["reachable_entities"].question,
    )
    group.add_argument(
        "--min-separation",
        metavar="ENTITY_ID",
        help=QUERIES["min_separation"].question,
    )
    group.add_argument(
        "--time-of-closest-approach",
        metavar="ENTITY_ID",
        help=QUERIES["time_of_closest_approach"].question,
    )
    group.add_argument(
        "--did-contact-occur",
        metavar="ENTITY_ID",
        help=QUERIES["did_contact_occur"].question,
    )
    group.add_argument(
        "--verify-chain",
        action="store_true",
        help=(
            "walk both record chains and report VERIFIED / BROKEN / "
            "COULD-NOT-EVALUATE per chain (exit 0 / 3 / 1)"
        ),
    )
    parser.add_argument(
        "--keyring",
        metavar="PATH",
        help=(
            "the keyring the records were signed under "
            "(reg.chain.write_keyring). Without it no MAC is checked, which is "
            "a could-not-evaluate and not a pass — there is no default key and "
            "none is invented"
        ),
    )
    parser.add_argument(
        "--tamper",
        metavar="SPEC",
        help=(
            "CHAIN:SELECTOR:OP — alter one record in a COPY of the artifact and "
            "verify the copy, to show the walk can fail. CHAIN is declaration "
            "or verdict; SELECTOR is first, last, #N or a record id; OP is "
            "FIELD=VALUE or delete. Requires --verify-chain and --tamper-out. "
            "The artifact itself is never written to"
        ),
    )
    parser.add_argument(
        "--tamper-out",
        metavar="PATH",
        help=(
            "where the tampered copy goes. Required with --tamper, must not "
            "exist, and has no default: a path invented here could name a file "
            "somebody else's evidence is in"
        ),
    )
    parser.add_argument(
        "--tamper-resign",
        action="store_true",
        help=(
            "re-sign the altered record under its own party's key, so its MAC "
            "verifies again and the chain breaks at its successor instead. "
            "Needs --keyring"
        ),
    )
    return parser


def _number(raw: str, name: str) -> float:
    try:
        return float(raw)
    except ValueError:
        raise QueryError(
            f"{name} is {raw!r}, which is not a number. It is a "
            + ("distance in metres." if "THRESHOLD" in name else "time in seconds.")
        ) from None


def _dispatch(conn: sqlite3.Connection, args: argparse.Namespace) -> Answer:
    """The one place a CLI flag becomes a call. Refuses if none was given."""
    if args.separation_timeline is not None:
        return separation_timeline(conn, args.separation_timeline)
    if args.first_envelope_intersection is not None:
        return first_envelope_intersection(conn, args.first_envelope_intersection)
    if args.frames_at_risk is not None:
        entity, threshold = args.frames_at_risk
        return frames_at_risk(conn, entity, _number(threshold, "THRESHOLD_M"))
    if args.reachable_entities is not None:
        t_start, t_end = args.reachable_entities
        return reachable_entities(
            conn, _number(t_start, "T_START"), _number(t_end, "T_END")
        )
    if args.min_separation is not None:
        return min_separation(conn, args.min_separation)
    if args.time_of_closest_approach is not None:
        return time_of_closest_approach(conn, args.time_of_closest_approach)
    if args.did_contact_occur is not None:
        return did_contact_occur(conn, args.did_contact_occur)
    raise QueryError(
        "no query was named. Nothing is answered by default — a query layer "
        "that picked one for you would answer a question nobody asked.\n"
        + _list_text()
    )


def _verify_chain_cli(args: argparse.Namespace) -> int:
    """`--verify-chain`, and `--tamper` before it. Exit `0` / `3` / `1` / `2`.

    The import of `reg.chain` is inside this function and must stay there — see
    the module header, and `tests/test_query.py::test_the_chain_import_is_
    deferred`, which fails if it moves to the top of the file.
    """
    from reg import chain

    keyring = None
    if args.keyring is not None:
        try:
            keyring = chain.load_keyring(args.keyring)
        except chain.KeyringError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return EXIT_USAGE

    target = Path(args.artifact)
    if args.tamper is not None:
        if args.tamper_out is None:
            print(
                "error: --tamper needs --tamper-out PATH. The tampered copy has "
                "nowhere to go and this tool will not pick a path — the "
                "artifact is never written to, and a path invented here could "
                "name a file somebody else's evidence is in.",
                file=sys.stderr,
            )
            return EXIT_USAGE
        try:
            tampered = chain.tamper(
                target,
                args.tamper_out,
                args.tamper,
                keyring=keyring,
                resign=args.tamper_resign,
            )
        except (chain.TamperError, store.StoreError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return EXIT_USAGE
        # Printed before the verdict, because the verdict is only evidence of
        # anything if the reader can see exactly which single edit produced it.
        print(tampered.describe())
        print()
        target = tampered.copy
    elif args.tamper_out is not None or args.tamper_resign:
        print(
            "error: --tamper-out and --tamper-resign say what to do with a "
            "tamper, and no --tamper was given. Refusing rather than ignoring "
            "them: a flag that is silently dropped reads as one that was "
            "applied.",
            file=sys.stderr,
        )
        return EXIT_USAGE

    try:
        conn = store.connect(target)
    except store.StoreError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    try:
        report = chain.verify_chain(conn, keyring)
    finally:
        conn.close()

    print(render_chain_report(report))
    return {
        chain.ChainState.VERIFIED: EXIT_OK,
        chain.ChainState.BROKEN: EXIT_BROKEN,
        chain.ChainState.COULD_NOT_EVALUATE: EXIT_COULD_NOT_EVALUATE,
    }[report.state]


def main(argv: Sequence[str] | None = None) -> int:
    """Exit `0` answered, `1` could-not-evaluate, `2` refused, `3` chain broken.

    Never silent, and never one code for two facts.
    """
    args = _parser().parse_args(argv)

    if args.list:
        print(_list_text())
        return EXIT_OK

    if args.artifact is None:
        print(
            "error: an artifact is required. Every query here reads one file "
            "and nothing else.\n" + _list_text(),
            file=sys.stderr,
        )
        return EXIT_USAGE

    if args.verify_chain:
        return _verify_chain_cli(args)

    stray = [
        flag
        for flag, given in (
            ("--keyring", args.keyring is not None),
            ("--tamper", args.tamper is not None),
            ("--tamper-out", args.tamper_out is not None),
            ("--tamper-resign", args.tamper_resign),
        )
        if given
    ]
    if stray:
        print(
            f"error: {', '.join(stray)} belong(s) to --verify-chain, which was "
            "not asked for. No scene query reads a key, and --tamper exists to "
            "show the chain walk saying no — on its own it would alter a copy "
            "of an artifact and report nothing about the result. Refusing "
            "rather than ignoring them: a flag that is silently dropped reads "
            "as one that was applied.",
            file=sys.stderr,
        )
        return EXIT_USAGE

    try:
        conn = store.connect(Path(args.artifact))
    except store.StoreError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE

    try:
        answer = _dispatch(conn, args)
    except QueryError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    finally:
        conn.close()

    print(render(answer))
    return EXIT_OK if answer.answered else EXIT_COULD_NOT_EVALUATE


if __name__ == "__main__":
    sys.exit(main())
