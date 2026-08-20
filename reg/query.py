"""The audit queries — **Claim 2** — and the module the raw stream cannot reach.

    python -m reg.query runs/contact.sqlite --list
    python -m reg.query runs/contact.sqlite --separation-timeline human
    python -m reg.query runs/contact.sqlite --frames-at-risk human 0.5
    python -m reg.query runs/dv.sqlite --incident 3.5 --keyring runs/keyring.json

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

THE ATTESTATION QUERIES, AND WHY THEY ARE THE STRONGER HALF (ISSUE #50)
------------------------------------------------------------------------
`declared_bound(t)`, `violations(window)`, `verdicts(declaration_id)` and
`verify_chain(conn, keyring)` read the record layer — the declarations the
policy signed, the verdicts enforcement signed back, the regions each named, and
the chain links between them. **Every one of them is Layer A**, and that is the
asymmetry docs/sufficiency.md §2 is about: whether the policy honoured its own
declaration is answerable from certifiable evidence, independently of whether
perception was right. Not one of these queries touches an `Entity`-bearing edge,
and `tests/test_query.py::test_no_attestation_query_touches_an_entity` holds the
line, because that property is the strongest claim the project makes.

They read the record tables with SQL and **never** through
`reg.store.read_declarations` / `read_verdicts`, which reconstruct the record
dataclasses and therefore import `reg.declare` and `reg.enforce` — and through
them `reg.stream`. The only function here that reaches those is `verify_chain`,
which has to: recomputing a MAC means recomputing the preimage, and a second
copy of the canonicalization here would be a second definition of what every
signature in the record covers.

`incident_report(t_incident, keyring)` composes them into docs/plan.md Phase 7's
demo sentence, and emits GSN-compatible field names beside the prose
(docs/prior-art.md §7): `goal`, `strategy`, `solution`, `assumption`,
`justification`. Field names only — there is no renderer and no new dependency.
Three honesty rules travel with it, each with a test that feeds it the condition
it guards against:

* **A run with no incident is not an error.** It reports that there was none. A
  query that raised on a clean run could not be used to check whether a run was
  clean.
* **A `t_incident` no declaration covers is a could-not-evaluate**, not an empty
  report — the same distinction every query above draws.
* **If the chain does not verify, the report says so first.** Every other line
  in it is a claim about a record whose integrity is in question, and a report
  that buried that at the bottom would be misleading in exactly the way this
  project exists to prevent.

The `assumption` slot is where Claim 3 is paid out: the report cites a Layer B
fact only when there is one to cite, and when it does, `assumption` names the
dependence. A report whose evidence is all Layer A carries no assumption, and
its attestation clauses are unchanged — which is the asymmetry, visible in the
output rather than in a paragraph somebody has to remember.

What the report does **not** do: read the CSV to fill a gap, invent a severity,
or draw a recommendation. It states what the record holds; an assessor draws
conclusions.

`--verify-chain` and `--tamper` (issue #49) are here, and they are not queries:
they return a `reg.chain.ChainReport`, not an `Answer`, because a chain walk is
not a question about the scene and has three verdicts of its own. The CLI exits
`0` VERIFIED, `3` BROKEN, `1` COULD-NOT-EVALUATE — three codes because those are
three different facts, and a script that treated "could not check" as "checked
and fine" is the failure mode the whole three-state discipline exists to
prevent.

LAYER
-----
Split, and it says so per query. Every *scene* question names an entity, and
where an entity is comes from perception in any real system (docs/plan.md Phase
9), so those are Layer B. Every *attestation* question is Layer A. The layer tag
travels on every edge and this module never invents one.
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
    "ATTESTATION_LAYER",
    "ATTESTATION_PRESENT",
    "CHAIN_VERIFIED",
    "CLAUSES",
    "CLAUSE_DECLARED",
    "CLAUSE_ENFORCEMENT",
    "CLAUSE_INTEGRITY",
    "CLAUSE_SCENE",
    "CLAUSE_VIOLATION",
    "COULD_NOT_EVALUATE",
    "EDGE_LAYER",
    "EXIT_BROKEN",
    "EXIT_COULD_NOT_EVALUATE",
    "EXIT_OK",
    "EXIT_USAGE",
    "GSN_FIELDS",
    "LAYER_A",
    "LAYER_B",
    "META_ATTESTATION_RECORDS",
    "META_ATTESTATION_RETENTION",
    "META_DECLARATION_COUNT",
    "META_FRAME_COUNT",
    "META_OCCURRENCE_RESOLUTION",
    "META_OCCURRENCE_RETENTION",
    "META_T_FIRST",
    "META_T_LAST",
    "META_VERDICT_COUNT",
    "OCCURRENCE_LAYER",
    "PERMITTED_OUTCOME",
    "QUERIES",
    "Adjudication",
    "Answer",
    "Clause",
    "DeclarationVerdicts",
    "DeclaredBound",
    "DeclaredBounds",
    "EnvelopeIntersection",
    "Evidence",
    "FramesAtRisk",
    "IncidentReport",
    "OverlapInterval",
    "QueryError",
    "QuerySpec",
    "ReachableEntities",
    "RiskInterval",
    "SceneVisit",
    "SeparationTimeline",
    "ViolatingAction",
    "Violations",
    "attestation_state",
    "available_layers",
    "declared_bound",
    "declaration_ids",
    "did_contact_occur",
    "entity_ids",
    "first_envelope_intersection",
    "frame_period",
    "frame_times",
    "frames_at_risk",
    "incident_report",
    "main",
    "min_separation",
    "reachable_entities",
    "render",
    "render_chain_report",
    "render_incident",
    "run_interval",
    "separation_timeline",
    "time_of_closest_approach",
    "verdicts",
    "verify_chain",
    "violations",
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

#: The record: the `declaration` and `verdict` tables, the regions those records
#: named, and the four Layer A edges between them (issue #45).
#:
#: **Deliberately not part of `available_layers`.** That function answers "which
#: of the two resolutions of the *scene* does this artifact hold", and
#: `reg.bench` subtracts its result from the level a view claims to be — a third
#: member would make every attested artifact look like a contaminated view. The
#: record layer is not a resolution of the scene at all: it is beside both, it is
#: never coarsened, and whether it is present is a different question with a
#: different reader (`attestation_state`).
ATTESTATION_LAYER = "attestation"

#: The two evidence layers of docs/plan.md Phase 9, as the artifact spells them.
#: `A` is proprioception, actuation limits and the record; `B` is anything whose
#: answer depends on where something else in the world was.
LAYER_A = "A"
LAYER_B = "B"

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

#: Whether the build that wrote this artifact was handed a record stream at all,
#: and the value of that key meaning it was. `absent` and a run that genuinely
#: produced no records are different facts, and this key is the only thing that
#: separates them: an empty `declaration` table on its own does not say which
#: (`reg.graph.ATTESTATION_RETENTION`). Spelled here rather than imported for the
#: reason the four keys above are, and checked against the writer by
#: `tests/test_query.py::test_the_meta_keys_this_module_reads_are_the_ones_the_
#: builder_writes`.
META_ATTESTATION_RECORDS = "attestation_records"
ATTESTATION_PRESENT = "present"

#: The record-layer retention rule, in prose, in the artifact. It is what makes
#: the *negative* answers below legible: "no verdict in this window refused an
#: action" means no such action only because the file says every verdict the run
#: produced is stored. Without the rule the absence of a row is silence, and
#: silence is not a negative — the same argument `did_contact_occur` makes about
#: `occurrence_retention`, one layer over.
META_ATTESTATION_RETENTION = "attestation_retention"

#: How many records the build says each chain holds. Read by the report only to
#: quote the record count beside the chain verdict — the walk itself compares
#: them (`reg.chain`), and this module never re-derives that comparison.
META_DECLARATION_COUNT = "declaration_count"
META_VERDICT_COUNT = "verdict_count"

#: The one outcome that is not a finding against the commanded action. Named
#: here rather than imported from `reg.enforce.OUTCOMES`, which is the
#: vocabulary's single definition, because importing it would pull `reg.declare`
#: and `reg.chain` — and through them the raw stream — into this module at import
#: time. `tests/test_query.py::test_the_outcome_vocabulary_is_the_enforcers`
#: compares the two sides and fails on a rename, which is the same bargain the
#: `meta` keys above are held to.
PERMITTED_OUTCOME = "PERMIT"

#: `reg.chain.ChainState.VERIFIED`'s value, for the same reason and under the
#: same test. A report that compared against a misspelled state would report
#: every intact chain as unverified — or, far worse, the reverse.
CHAIN_VERIFIED = "VERIFIED"

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


_SCENE_LAYER = LAYER_B

#: Every attestation query's evidence layer, and it is not a coincidence that it
#: is the same letter for all three: a declaration is a statement the policy made
#: about a region it computed from its own state, a verdict is what an
#: independent enforcement layer computed from proprioception and actuation
#: limits, and the chain is a hash and a MAC over those records. None of them
#: names an entity (docs/sufficiency.md §2).
_RECORD_LAYER = LAYER_A

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
    # The attestation half (docs/plan.md Phase 7, queries 5-7; issue #50). No
    # numeric tolerance on any of the three, and that is docs/lossiness.md's
    # agreement table rather than an omission: they are Layer A and exact by
    # construction, and a tolerance on them would mean the record is fuzzy about
    # what the policy declared — the one thing this artifact must be certain of.
    "declared_bound": QuerySpec(
        name="declared_bound",
        question="what the policy claimed, and signed, was in force at time t",
        answerable_from=frozenset({ATTESTATION_LAYER}),
        arguments=("T",),
        tolerance=(
            "none — exact field equality. Record timestamps are stored as the "
            "record carries them and are not quantized to TIME_TOL_S: the MAC "
            "covers the instant the policy signed, and a rounded version of it "
            "is an instant nobody signed"
        ),
        why_not=(
            "Neither scene layer holds a declaration. The edge layer records "
            "where the reachable set was, which is a fact about the robot; what "
            "the policy *claimed* about it is a signed record, and an artifact "
            "built without one holds no answer at any resolution."
        ),
        layer_tag=_RECORD_LAYER,
    ),
    "violations": QuerySpec(
        name="violations",
        question=(
            "every commanded action in a window that enforcement did not permit "
            "as issued, with its fault code"
        ),
        answerable_from=frozenset({ATTESTATION_LAYER}),
        arguments=("T_START", "T_END"),
        tolerance=(
            "none — the exact set of (t, fault_code) the record holds. A missed "
            "or invented fault is a failure, not a near miss"
        ),
        why_not=(
            "A fault is a finding an independent enforcement layer signed. It "
            "is in the verdict stream or it is nowhere; no density of scene "
            "edges reconstructs one."
        ),
        layer_tag=_RECORD_LAYER,
    ),
    "verdicts": QuerySpec(
        name="verdicts",
        question=(
            "every adjudication of one declaration — what enforcement did about "
            "it, and why. Many, not one"
        ),
        answerable_from=frozenset({ATTESTATION_LAYER}),
        arguments=("DECLARATION_ID",),
        tolerance="none — exact field equality against the stored record",
        why_not=(
            "The verdict stream is the answer and the scene layers hold none of "
            "it."
        ),
        layer_tag=_RECORD_LAYER,
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
# The attestation answer shapes (issue #50). Every one of them is Layer A and
# not one carries an entity id — the property `tests/test_query.py` asserts
# against the dataclasses as well as against the SQL, because a field added here
# that named an entity would widen Layer A silently.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class DeclaredBound:
    """One declaration and the region it claimed, as the record carries them.

    `t_issued` and `horizon` are **not** quantized: they are values the MAC
    covers, and the artifact stores them as signed (`reg.graph`, module header).
    `area` is the stored area of the declared region, which is retained in full
    — `GEOMETRY_RETENTION` discards a polygon only where the artifact could
    recompute it from a configuration it holds, and a bound that came from a
    policy is not a function of any configuration in the file.
    """

    declaration_id: str
    seq: int
    t_issued: float
    horizon: float
    action_class: str
    envelope_id: str
    area: float

    @property
    def t_expires(self) -> float:
        """The last instant the policy claimed this statement was good for."""
        return self.t_issued + self.horizon


@dataclass(frozen=True)
class DeclaredBounds:
    """docs/plan.md Phase 7, query 5 — what the policy claimed at time `t`.

    **A tuple, not one bound.** A run whose declaration horizon exceeds its
    replan interval has overlapping validity windows, so more than one signed
    claim is genuinely in force at some instants. That is a fact about the
    record, and picking one of them here — the newest, the tightest, the
    first — would be this module inventing a precedence rule nobody signed.

    An empty `bounds` never reaches a caller: no declaration in force at `t` is
    a `COULD-NOT-EVALUATE` one level up, because "the policy claimed nothing
    here" and "this artifact cannot say what the policy claimed here" are the
    same row count and different facts.
    """

    t: float
    bounds: tuple[DeclaredBound, ...]

    @property
    def window(self) -> tuple[float, float]:
        """The union span of every claim in force: `(earliest, latest)`."""
        return (
            min(b.t_issued for b in self.bounds),
            max(b.t_expires for b in self.bounds),
        )


@dataclass(frozen=True)
class ViolatingAction:
    """One commanded action enforcement did not permit as issued.

    `declaration_id` is `None` when the verdict named none, and that `None` is
    the finding rather than a gap: it is what `no_declaration` and
    `watchdog_expiry` look like in the record (`reg.enforce`).

    `applied_envelope_id` is the bound the verdict actually applied, and exists
    only for a CLAMP — a VETO or a SAFE_STATE permits no action to bound, and a
    bound reported beside one would read as though something had been allowed
    inside it.
    """

    verdict_id: str
    seq: int
    t: float
    outcome: str
    fault: str | None
    declaration_id: str | None
    applied_envelope_id: str | None
    applied_area: float | None


@dataclass(frozen=True)
class Violations:
    """docs/plan.md Phase 7, query 6, over a window.

    **Every outcome that is not `PERMIT`**, and not only the mismatch fault. The
    question is "every commanded action outside its declared bound", and an
    action adjudicated against a *stale* declaration, or against none at all, was
    not inside a valid declared bound either — narrowing this to one fault code
    would report "no violations" for a run that was passivated from end to end,
    which is the worst false negative this query could produce. The fault code
    travels on every row, so a caller wanting exactly the mismatches filters for
    them and can see what it filtered out.

    An empty `actions` **is** an answer — "no commanded action in this window was
    refused" — and it is legitimate only because the artifact carries
    `attestation_retention` in its own `meta` saying every verdict the run
    produced is stored. An artifact missing that rule refuses instead.
    """

    t_start: float
    t_end: float
    actions: tuple[ViolatingAction, ...]
    #: Every fault code present in `actions`, sorted. A vocabulary summary a
    #: caller can test against without walking the rows.
    faults: tuple[str, ...]
    #: How many verdicts the window holds in total, permitted ones included. The
    #: denominator: "3 refused" is not a reading without it.
    adjudications: int

    @property
    def began(self) -> float | None:
        """The instant of the earliest refused action, or `None` if there were
        none. This is the demo sentence's second clause."""
        return self.actions[0].t if self.actions else None


@dataclass(frozen=True)
class Adjudication:
    """One verdict against one declaration: what enforcement did, and why."""

    verdict_id: str
    seq: int
    t: float
    outcome: str
    fault: str | None
    applied_envelope_id: str | None
    applied_area: float | None


@dataclass(frozen=True)
class DeclarationVerdicts:
    """docs/plan.md Phase 7, query 7. **Many verdicts, not one.**

    A verdict is per commanded action, not per declaration (#43), so one
    declaration is routinely adjudicated PERMIT dozens of times and then CLAMP —
    and `outcomes` carrying more than one value is exactly the case a
    one-row-per-declaration schema would have destroyed, along with the ability
    to say *when* the violation began.

    An empty `adjudications` is "this declaration was never adjudicated", which
    is a legitimate answer under `attestation_retention` and a finding in its own
    right: a signed claim nothing ever checked.
    """

    declaration_id: str
    adjudications: tuple[Adjudication, ...]

    @property
    def outcomes(self) -> tuple[str, ...]:
        """Every distinct outcome this declaration received, sorted."""
        return tuple(sorted({a.outcome for a in self.adjudications}))


@dataclass(frozen=True)
class SceneVisit:
    """One entity inside the computed envelope for one span. **Layer B.**

    The only shape in this section that names an entity, and it is the only one
    that is not Layer A. It exists so that the incident report can carry
    docs/plan.md Phase 7's fourth prose line — and so that carrying it obliges
    the report to populate `assumption`.
    """

    entity_id: str
    t_start: float
    t_end: float
    frames: int


# --------------------------------------------------------------------------
# The incident report (docs/plan.md Phase 7's money query, docs/prior-art.md §7).
#
# GSN-compatible field names alongside the prose, and **field names only**: no
# diagram, no renderer, no new dependency. The payoff is that the output drops
# into a UL 4600 safety case rather than needing transcription.
# --------------------------------------------------------------------------

#: The GSN elements this report emits, in the order docs/prior-art.md §7 lists
#: them. Named so a consumer can enumerate them rather than hard-coding five
#: attribute names, and so a field added without a mapping fails a test here.
GSN_FIELDS: tuple[str, ...] = (
    "goal",
    "strategy",
    "solution",
    "assumption",
    "justification",
)

#: The report's clauses. The four content ones are in the order the issue states
#: — what was declared, where the action left it, what enforcement did, and the
#: scene context — and `integrity` moves to the **front** whenever the chain did
#: not verify, because every other clause is a claim about a record whose
#: integrity is then in question.
CLAUSE_INTEGRITY = "integrity"
CLAUSE_DECLARED = "declared"
CLAUSE_VIOLATION = "violation"
CLAUSE_ENFORCEMENT = "enforcement"
CLAUSE_SCENE = "scene"

#: Every clause name, in content order. `integrity` is listed last because that
#: is where it sits on a verified record; `_ordered_clauses` is what moves it.
CLAUSES: tuple[str, ...] = (
    CLAUSE_DECLARED,
    CLAUSE_VIOLATION,
    CLAUSE_ENFORCEMENT,
    CLAUSE_SCENE,
    CLAUSE_INTEGRITY,
)


@dataclass(frozen=True)
class Evidence:
    """A GSN **solution**: one evidence item, and the layer it is read from.

    `layer` is `A` or `B` and is never invented here — it comes from what the
    item *is*: a record, a region a record named, or a chain segment is Layer A;
    a relationship with an entity is Layer B. It is the field `assumption` is
    derived from, so an item mislabelled here would quote a conditional claim as
    certifiable, which is the one thing this report exists not to do.
    """

    kind: str
    ref: str
    layer: str
    detail: str


@dataclass(frozen=True)
class Clause:
    """One ordered clause of the report: what it says, and whether it could say it.

    `verdict` is per clause on purpose. The Layer B clause can be a
    could-not-evaluate — an artifact with no relationship to an entity holds
    nothing to cite — while every attestation clause beside it answers, and that
    is docs/sufficiency.md §2 visible in the output rather than asserted in a
    paragraph.

    Two vocabularies meet in this field and they agree where it matters. A
    content clause carries `ANSWERED` or `COULD-NOT-EVALUATE`; the integrity
    clause carries `reg.chain.ChainState`'s value — `VERIFIED`, `BROKEN` or
    `COULD-NOT-EVALUATE` — because a chain that broke *answered* the question,
    with a no. The third state is spelled identically in both
    (`tests/test_query.py::test_the_could_not_evaluate_spelling_is_one_string`),
    which is what lets `answered` below be one rule rather than two.
    """

    name: str
    verdict: str
    layer: str
    text: str
    solution: tuple[Evidence, ...] = ()

    @property
    def answered(self) -> bool:
        """Whether this clause reached a finding at all.

        `BROKEN` is a finding — the record was altered — and it is emphatically
        not a pass; what it is not is a *failure to look*. The one verdict that
        means nothing was learned is `COULD-NOT-EVALUATE`, and it never resolves
        to either of the others.
        """
        return self.verdict != COULD_NOT_EVALUATE


@dataclass(frozen=True)
class IncidentReport:
    """docs/plan.md Phase 7's demo sentence, as structured output.

    Structured, not prose: `render_incident` formats and this holds fields a
    caller can test against. The GSN names (`goal`, `strategy`, `solution`,
    `assumption`, `justification`) are docs/prior-art.md §7's, so the object
    drops into an assurance case without transcription.

    Three states, and they are separate fields because they are separate facts.
    `verdict` is whether the attestation question could be answered at all;
    `integrity` is what the chain walk said about the record those answers are
    read from; `incident` is whether anything was found. A run with no incident
    is `ANSWERED`, `VERIFIED` and `incident=False` — not an error, because a
    query that raised on a clean run could not be used to check whether a run was
    clean.
    """

    t_incident: float
    verdict: str
    reason: str
    #: `reg.chain.ChainState`'s value, as a string. Never a bool: an unchecked
    #: chain is not a checked one, and neither is a broken one.
    integrity: str
    clauses: tuple[Clause, ...]

    # --- GSN (docs/prior-art.md §7). Field names only; no renderer. ---
    goal: str
    strategy: str
    solution: tuple[Evidence, ...]
    assumption: tuple[str, ...]
    justification: str

    #: What was found, or `None` where nothing was or nothing could be. The
    #: earliest refused action inside the window this report is scoped to, which
    #: is the demo sentence's second clause.
    violation: ViolatingAction | None = None
    #: The earliest refused action in the **whole** record, which is where the
    #: sequence this incident belongs to began — often before the declaration in
    #: force at `t_incident` was even issued. Reported beside `violation` rather
    #: than instead of it, and with no claim that the two are the same incident:
    #: whether an earlier fault caused a later one is an inference, and this
    #: report states what the record holds.
    first_refusal: ViolatingAction | None = None
    bounds: tuple[DeclaredBound, ...] = ()
    scene: tuple[SceneVisit, ...] = ()

    @property
    def answered(self) -> bool:
        return self.verdict == ANSWERED

    @property
    def integrity_verified(self) -> bool:
        return self.integrity == CHAIN_VERIFIED

    @property
    def incident(self) -> bool:
        """Whether the record holds a refused action in the window. `False` is an
        answer — "there was none" — and never a failure to look."""
        return self.violation is not None

    def clause(self, name: str) -> Clause:
        """One clause by name, or a `QueryError` naming the clauses present."""
        for item in self.clauses:
            if item.name == name:
                return item
        raise QueryError(
            f"this report has no {name!r} clause; it has "
            f"{[c.name for c in self.clauses]}."
        )


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
    """Every entity the artifact declares, in id order.

    Through `node`, which is where a readable identifier lives since issue #55 —
    an inner join, so an `entity` row whose identity is gone is *not* silently
    reported as an entity nobody can name. The entity set is what every negative
    scene answer is read against (docs/lossiness.md *Unanswerable* #2), and a
    nameless member of it would be an entity a caller could never ask about.
    """
    rows = conn.execute(
        "SELECT n.node_id AS entity_id FROM entity e "
        "JOIN node n ON n.node_key = e.entity_key ORDER BY n.node_id"
    ).fetchall()
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
    key = store.node_key(conn, str(entity_id))
    if key is None:
        return False
    row = conn.execute(
        "SELECT 1 FROM edge WHERE dst_key = ? LIMIT 1", (key,)
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
# The attestation queries. docs/plan.md Phase 7, queries 5-8 (issue #50).
#
# All Layer A. Read with SQL over the record tables and the four Layer A edges,
# and **never** through `reg.store.read_declarations` / `read_verdicts`: those
# reconstruct the record dataclasses and therefore import `reg.declare` and
# `reg.enforce`, which reach `reg.stream`. `verify_chain` is the one function
# below that does reach them, and it has to — see the module header.
# --------------------------------------------------------------------------


def attestation_state(conn: sqlite3.Connection) -> str | None:
    """What the artifact says about being handed a record stream, or `None`.

    `None` is a build from before the record layer existed, or one that was
    given no stream and did not say so. Either way it is not `present`, and
    nothing below will read an empty table as a run that produced nothing.
    """
    return store.get_meta(conn, META_ATTESTATION_RECORDS)


def declaration_ids(conn: sqlite3.Connection) -> tuple[str, ...]:
    """Every declaration this artifact holds, in chain order."""
    rows = conn.execute(
        "SELECT n.node_id AS declaration_id FROM declaration d "
        "JOIN node n ON n.node_key = d.declaration_key ORDER BY d.seq, n.node_id"
    ).fetchall()
    return tuple(str(row["declaration_id"]) for row in rows)


def _refuse_record(spec: QuerySpec, detail: str) -> Answer:
    """A `COULD-NOT-EVALUATE` about the record layer, naming what is missing."""
    return Answer(
        query=spec.name,
        verdict=COULD_NOT_EVALUATE,
        layer=None,
        value=None,
        tolerances={},
        reason=(
            f"{spec.name} is answerable from the {ATTESTATION_LAYER} layer. "
            f"{detail}"
        ),
    )


def _no_record_layer(conn: sqlite3.Connection, spec: QuerySpec) -> Answer | None:
    """The refusal owed by an artifact with no record layer, or `None`.

    Two distinct refusals, and they are two sentences because they are two
    facts. `meta[attestation_records]` absent or not `present` means this build
    was never handed a record stream — the tables are empty because nothing was
    ever offered to them. The retention rule missing means the artifact does not
    state that every record was kept, and without that statement an empty result
    is silence rather than a negative.
    """
    state = attestation_state(conn)
    if state != ATTESTATION_PRESENT:
        return _refuse_record(
            spec,
            f"meta[{META_ATTESTATION_RECORDS!r}] is {state!r}: this build was "
            "given no record stream at all, so it holds no declarations and no "
            "verdicts to read. That is a different fact from a run that produced "
            "none, and an empty answer here would be indistinguishable from one. "
            "Build with `python -m reg.graph build ... --keyring` to store one.",
        )
    if store.get_meta(conn, META_ATTESTATION_RETENTION) is None:
        return _refuse_record(
            spec,
            f"this artifact does not state meta[{META_ATTESTATION_RETENTION!r}], "
            "so it does not say that every declaration and every verdict the run "
            "produced was stored. Without that rule the absence of a row is "
            "silence, and silence is not a negative.",
        )
    return None


def _declaration_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Every declaration with the region it claimed, in chain order.

    A `LEFT JOIN` rather than an inner one, deliberately: a declaration whose
    `DECLARED` edge is missing has to come back and be *refused*, because an
    inner join would drop it and the caller would be told the policy claimed
    nothing at an instant where it claimed something this artifact has lost.

    The joins run on `node_key` and the readable ids come off `node` (issue
    #55). The report cites `dn.node_id`, never the surrogate — an incident
    report naming an integer is worse evidence than one that costs a few bytes.
    """
    return list(
        conn.execute(
            """
            SELECT dn.node_id     AS declaration_id,
                   d.seq          AS seq,
                   d.t_issued     AS t_issued,
                   d.horizon      AS horizon,
                   d.action_class AS action_class,
                   en.node_id     AS envelope_id,
                   v.area         AS area
            FROM declaration d
            JOIN node dn
              ON dn.node_key = d.declaration_key
            LEFT JOIN edge e
                   ON e.type = 'DECLARED' AND e.src_key = d.declaration_key
            LEFT JOIN envelope v
                   ON v.envelope_key = e.dst_key
            LEFT JOIN node en
                   ON en.node_key = e.dst_key
            ORDER BY d.seq, dn.node_id
            """
        ).fetchall()
    )


def _verdict_rows(
    conn: sqlite3.Connection, *, declaration_id: str | None = None
) -> list[sqlite3.Row]:
    """Every verdict with the bound it applied, in chain order.

    The bound comes off the `ENFORCED` edge, which exists only for a CLAMP: a
    PERMIT bounds nothing and a VETO or SAFE_STATE permits no action to bound, so
    a NULL here is the record's own silence and not a lost row.
    """
    clause = "" if declaration_id is None else "WHERE dn.node_id = ?"
    params: tuple[object, ...] = () if declaration_id is None else (declaration_id,)
    return list(
        conn.execute(
            f"""
            SELECT vn.node_id AS verdict_id,
                   dn.node_id AS declaration_id,
                   v.seq      AS seq,
                   v.t        AS t,
                   v.outcome  AS outcome,
                   v.fault    AS fault,
                   en.node_id AS envelope_id,
                   p.area     AS area
            FROM verdict v
            JOIN node vn
              ON vn.node_key = v.verdict_key
            LEFT JOIN node dn
                   ON dn.node_key = v.declaration_key
            LEFT JOIN edge e
                   ON e.type = 'ENFORCED' AND e.src_key = v.verdict_key
            LEFT JOIN envelope p
                   ON p.envelope_key = e.dst_key
            LEFT JOIN node en
                   ON en.node_key = e.dst_key
            {clause}
            ORDER BY v.seq, vn.node_id
            """,  # noqa: S608 - `clause` is a literal, the id is a bound param
            params,
        ).fetchall()
    )


def _violating(row: sqlite3.Row) -> ViolatingAction:
    return ViolatingAction(
        verdict_id=str(row["verdict_id"]),
        seq=int(row["seq"]),
        t=float(row["t"]),
        outcome=str(row["outcome"]),
        fault=None if row["fault"] is None else str(row["fault"]),
        declaration_id=(
            None if row["declaration_id"] is None else str(row["declaration_id"])
        ),
        applied_envelope_id=(
            None if row["envelope_id"] is None else str(row["envelope_id"])
        ),
        applied_area=None if row["area"] is None else float(row["area"]),
    )


def _adjudication(row: sqlite3.Row) -> Adjudication:
    return Adjudication(
        verdict_id=str(row["verdict_id"]),
        seq=int(row["seq"]),
        t=float(row["t"]),
        outcome=str(row["outcome"]),
        fault=None if row["fault"] is None else str(row["fault"]),
        applied_envelope_id=(
            None if row["envelope_id"] is None else str(row["envelope_id"])
        ),
        applied_area=None if row["area"] is None else float(row["area"]),
    )


def declared_bound(conn: sqlite3.Connection, t: float) -> Answer:
    """Query 5 — what the policy claimed, and signed, was in force at time `t`.

    **Layer A.** A declaration is a statement the policy made about a region it
    computed from its own state; no perceptual error can change what it said.

    Returns every claim in force at `t`, because a run whose horizon exceeds its
    replan interval genuinely has more than one — see `DeclaredBounds`. No
    declaration in force is a `COULD-NOT-EVALUATE` and not an empty tuple: "the
    policy claimed nothing about this instant" is a serious finding and it must
    not arrive looking like an empty list, which is what an unbuilt query
    returns.

    The window test is `t_issued <= t <= t_issued + horizon` on the values the
    record carries, with **no tolerance**. docs/lossiness.md's agreement table
    gives the attestation queries none: they are exact by construction, and a
    tolerance here would mean the record is fuzzy about what the policy declared.
    """
    spec = QUERIES["declared_bound"]
    t = _finite(t, "t")
    refusal = _no_record_layer(conn, spec)
    if refusal is not None:
        return refusal

    rows = _declaration_rows(conn)
    if not rows:
        return _refuse_record(
            spec,
            "this artifact was built with a record stream and holds no "
            "declaration in it, so there is nothing at any instant to read. A "
            "policy that never declared is a finding the verdict stream "
            "records as no_declaration; it is not something this query can "
            "report as a bound.",
        )

    covering = [
        row
        for row in rows
        if float(row["t_issued"]) <= t <= float(row["t_issued"]) + float(row["horizon"])
    ]
    if not covering:
        first = min(float(r["t_issued"]) for r in rows)
        last = max(float(r["t_issued"]) + float(r["horizon"]) for r in rows)
        return _refuse_record(
            spec,
            f"no declaration in this artifact is in force at t={t}. Its "
            f"{len(rows)} declaration(s) span [{first}, {last}], and a claim "
            "that had lapsed is not a claim: reporting the nearest one would "
            "report a statement the policy had stopped standing behind.",
        )

    missing = [
        str(row["declaration_id"]) for row in covering if row["envelope_id"] is None
    ]
    if missing:
        return _refuse_record(
            spec,
            f"declaration(s) {missing} are in force at t={t} and this artifact "
            "holds no DECLARED edge to the region they claimed. The claim is a "
            "region; without it there is nothing to report, and reporting the "
            "declaration's other fields would answer a smaller question in the "
            "shape of this one.",
        )

    bounds = tuple(
        DeclaredBound(
            declaration_id=str(row["declaration_id"]),
            seq=int(row["seq"]),
            t_issued=float(row["t_issued"]),
            horizon=float(row["horizon"]),
            action_class=str(row["action_class"]),
            envelope_id=str(row["envelope_id"]),
            area=float(row["area"]),
        )
        for row in covering
    )
    return Answer(
        query=spec.name,
        verdict=ANSWERED,
        layer=ATTESTATION_LAYER,
        value=DeclaredBounds(t=t, bounds=bounds),
        tolerances={},
        reason=(
            f"{len(bounds)} signed declaration(s) in force at t={t}, of "
            f"{len(rows)} in the record"
        ),
    )


def violations(conn: sqlite3.Connection, window: tuple[float, float]) -> Answer:
    """Query 6 — every commanded action in `window` that was not permitted.

    **Layer A**, and the window is a pair rather than two arguments because
    docs/plan.md Phase 7 spells the query `violations(window)`.

    The window is **not** checked against the run interval, unlike
    `reachable_entities`. A record's instants are not observations: a
    declaration's validity window can legitimately run past the last frame, and
    a verdict is a statement about an action rather than a sample of the scene.
    What is checked is that the window is a window — finite, and not backwards,
    which would match no record and come back as "nothing was refused".

    An empty result is an answer, licensed by `meta[attestation_retention]`, and
    an artifact without that rule refuses instead. See `Violations` for why the
    filter is "not PERMIT" rather than one fault code.
    """
    spec = QUERIES["violations"]
    t_start = _finite(window[0], "t_start")
    t_end = _finite(window[1], "t_end")
    if t_end < t_start:
        raise QueryError(
            f"the window [{t_start}, {t_end}] runs backwards. A backwards window "
            "matches no verdict, so it would come back as 'no action was "
            "refused' rather than as the mistake it is."
        )
    refusal = _no_record_layer(conn, spec)
    if refusal is not None:
        return refusal

    rows = [
        row for row in _verdict_rows(conn) if t_start <= float(row["t"]) <= t_end
    ]
    refused = [row for row in rows if str(row["outcome"]) != PERMITTED_OUTCOME]
    actions = tuple(_violating(row) for row in refused)
    return Answer(
        query=spec.name,
        verdict=ANSWERED,
        layer=ATTESTATION_LAYER,
        value=Violations(
            t_start=t_start,
            t_end=t_end,
            actions=actions,
            faults=tuple(sorted({a.fault for a in actions if a.fault is not None})),
            adjudications=len(rows),
        ),
        tolerances={},
        reason=(
            f"{len(refused)} of {len(rows)} adjudication(s) in "
            f"[{t_start}, {t_end}] were not permitted as issued, read "
            f"closed-world under meta[{META_ATTESTATION_RETENTION!r}]"
        ),
    )


def verdicts(conn: sqlite3.Connection, declaration_id: str) -> Answer:
    """Query 7 — what enforcement did about one declaration, and why. **Many.**

    A verdict is per commanded action, not per declaration (#43), so this
    routinely returns tens of them against one claim and `DeclarationVerdicts.
    outcomes` routinely holds more than one value. That is the point: the
    instant a run of PERMITs becomes a CLAMP is when the violation began, and a
    query that collapsed to one verdict per declaration could not say it.

    A `declaration_id` this artifact does not hold is a `QueryError` naming what
    it does hold — a caller error, not an empty answer, for exactly the reason
    `_require_entity` gives: an empty adjudication list for a declaration nobody
    signed would read as a claim that was never checked.
    """
    spec = QUERIES["verdicts"]
    declaration_id = str(declaration_id)
    refusal = _no_record_layer(conn, spec)
    if refusal is not None:
        return refusal

    known = declaration_ids(conn)
    if declaration_id not in known:
        if not known:
            raise QueryError(
                f"{declaration_id!r} is not in this artifact, which holds no "
                "declarations at all. Nothing was ever signed into its record "
                "layer, so it holds no adjudication of anything."
            )
        raise QueryError(
            f"{declaration_id!r} is not a declaration in this artifact. It holds "
            f"{len(known)}, beginning {list(known[:5])}. An empty adjudication "
            "list for a record nobody signed would read as a claim enforcement "
            "never checked, which is a finding and not an absence."
        )

    rows = _verdict_rows(conn, declaration_id=declaration_id)
    adjudications = tuple(_adjudication(row) for row in rows)
    return Answer(
        query=spec.name,
        verdict=ANSWERED,
        layer=ATTESTATION_LAYER,
        value=DeclarationVerdicts(
            declaration_id=declaration_id, adjudications=adjudications
        ),
        tolerances={},
        reason=(
            f"{len(adjudications)} adjudication(s) of {declaration_id!r}, read "
            f"closed-world under meta[{META_ATTESTATION_RETENTION!r}]"
        ),
    )


def verify_chain(conn: sqlite3.Connection, keyring: object) -> object:
    """Query 8 — integrity over the full record. `reg.chain.verify_chain`, here.

    A thin re-export and deliberately nothing more: the walk is `reg.chain`'s
    and a second implementation of it here would be a second definition of the
    preimage every MAC in the record is taken over. What this adds is that the
    query API's caller does not have to know which module the walk lives in —
    docs/plan.md Phase 7 lists `verify_chain()` beside the other three, so it is
    reachable beside them.

    **The import is inside this function and must stay there.** `reg.chain`
    reaches `reg.stream` for the float precision its canonical serialization
    commits to, and hoisting it would put the raw stream one attribute away from
    every scene query — see the module header and
    `tests/test_query.py::test_the_chain_import_is_deferred`.

    Args:
        conn: an artifact opened with `reg.store.connect`.
        keyring: the keyring the records were signed under, or `None`.
            **Required, with no default**: `None` is could-not-evaluate for
            every MAC, and a caller that had not thought about the key would
            otherwise get something that looks like a verification and checked no
            signature.

    Returns:
        A `reg.chain.ChainReport`. Annotated `object` because naming the type
        would mean importing `reg.chain` at module level.
    """
    from reg import chain

    return chain.verify_chain(conn, keyring)


# --------------------------------------------------------------------------
# The money query. docs/plan.md Phase 7, and docs/prior-art.md §7 for the shape.
# --------------------------------------------------------------------------

#: The GSN **justification** every report carries: why proprioception-only
#: evidence suffices for the claim being audited. Constant because it is an
#: argument about the artifact's structure rather than about one run, and a
#: sentence assembled per report would be one an assessor could not diff.
_JUSTIFICATION = (
    "Every clause above except the scene clause is Layer A. A declaration is a "
    "statement the policy made about a region it computed from its own state; a "
    "verdict is what an independent enforcement layer computed from "
    "proprioception and actuation limits alone, importing from the policy no "
    "further than the record; the chain is a hash and a MAC over both. Not one "
    "of them names an entity, so no perceptual error can make a policy that "
    "exceeded its declared bound look like one that did not "
    "(docs/sufficiency.md §2). The independence is structural: enforcement "
    "computes its own bound and does not trust the declared one. Its honest "
    "limit is that both keys live in one process in this prototype, which "
    "demonstrates the structure of non-repudiation and not non-repudiation "
    "(reg/chain.py, README)."
)

_STRATEGY = (
    "Argue over the signed record: read what the policy declared and was in "
    "force at the instant asked about, then every commanded action an "
    "independent enforcement layer adjudicated inside that declaration's own "
    "validity window, then the bound enforcement actually applied — and walk "
    "both hash chains to establish that neither party's record was altered "
    "after it was signed."
)


def _integrity_clause(report: object) -> tuple[Clause, str]:
    """The chain walk as a clause, and the state it reached.

    A report whose record may have been altered is a report of claims about a
    record whose integrity is in question, so the text says so in its first line
    rather than in a footnote, and `_ordered_clauses` puts it first.

    The state is returned beside the clause rather than parsed back out of its
    prose: an `IncidentReport.integrity` recovered by splitting a sentence would
    change meaning the next time somebody reworded the sentence.
    """
    state = report.state.value
    walked = sum(result.records_walked for result in report.chains)
    failures = report.failures
    evidence = tuple(
        Evidence(
            kind="chain",
            ref=result.chain,
            layer=LAYER_A,
            detail=(
                f"{result.kind} chain: {result.state.value}, "
                f"{result.records_walked} record(s) walked, "
                f"{result.links_checked} link(s) and {result.macs_checked} "
                f"MAC(s) checked, {len(result.failures)} failure(s)"
            ),
        )
        for result in report.chains
    )

    if state == CHAIN_VERIFIED:
        return (
            Clause(
                name=CLAUSE_INTEGRITY,
                verdict=state,
                layer=LAYER_A,
                text=f"Chain verified: {walked:,} records, 0 breaks",
                solution=evidence,
            ),
            state,
        )

    lines = [
        f"INTEGRITY {state} — READ THIS FIRST. Every other claim in this report "
        "is a claim about this record, and the walk over it did not come back "
        "verified.",
        f"  {walked:,} record(s) walked, {len(failures)} failure(s):",
    ]
    lines.extend(f"    - {failure.describe()}" for failure in failures)
    return (
        Clause(
            # The chain's own state, verbatim. BROKEN is a finding about the
            # record and COULD-NOT-EVALUATE is a finding about the walk, and
            # collapsing the two would let "could not check" read as "checked
            # and found a fault" — or, far worse, the reverse.
            name=CLAUSE_INTEGRITY,
            verdict=state,
            layer=LAYER_A,
            text="\n".join(lines),
            solution=evidence,
        ),
        state,
    )


def _scene_clause(
    conn: sqlite3.Connection, t_start: float, t_end: float
) -> tuple[Clause, tuple[SceneVisit, ...]]:
    """docs/plan.md Phase 7's fourth prose line. **Layer B, and it says so.**

    Three outcomes, and they are three because they are three different facts:

    * entities were inside the computed envelope in this window -> a Layer B
      claim, cited as Layer B evidence, and the report's `assumption` is
      populated from it;
    * the edge layer holds relationships and none of them is an intersection in
      this window -> **no Layer B fact is cited**, which is a statement about the
      report rather than about the world, and `assumption` stays empty. That is
      what makes the assumption check able to fail;
    * there is no edge layer -> could-not-evaluate. An artifact holding only the
      record cannot say where anybody was, and an empty visit list from one would
      read as "nobody was near the robot".
    """
    # `layer = 'B'` and not merely "the edge table has rows in it". An artifact
    # holding only the record still has DECLARED, ADJUDICATED, ENFORCED and
    # FOLLOWS edges — all Layer A — so `available_layers` would call its edge
    # layer present and this clause would report "no entity intersected the
    # envelope" for a file that holds no relationship with an entity at all.
    # That is silence read as a negative, which is the one reading every query
    # here refuses.
    if conn.execute(
        f"SELECT 1 FROM edge WHERE layer = '{LAYER_B}' LIMIT 1"  # noqa: S608
    ).fetchone() is None:
        return (
            Clause(
                name=CLAUSE_SCENE,
                verdict=COULD_NOT_EVALUATE,
                layer=LAYER_B,
                text=(
                    "This artifact holds no Layer B edge, so it cannot say which "
                    "entities were inside the computed envelope during the "
                    "window. That is a could-not-evaluate and not 'none were': "
                    "the attestation clauses above are unaffected by it, which "
                    "is the asymmetry docs/sufficiency.md §2 states."
                ),
            ),
            (),
        )

    try:
        period = frame_period(conn)
    except QueryError as exc:
        return (
            Clause(
                name=CLAUSE_SCENE,
                verdict=COULD_NOT_EVALUATE,
                layer=LAYER_B,
                text=(
                    "The scene clause counts frames by dividing an interval by "
                    f"the frame period, and this artifact does not state one: "
                    f"{exc}"
                ),
            ),
            (),
        )

    rows = [
        row
        for row in store.read_edges(conn, edge_type="INTERSECTS")
        if float(row["t_start"]) <= t_end and float(row["t_end"]) >= t_start
    ]
    visits: list[SceneVisit] = []
    for entity_id in sorted({str(row["dst_id"]) for row in rows}):
        for group in _merge_adjacent(
            [row for row in rows if str(row["dst_id"]) == entity_id], period
        ):
            start = float(group[0]["t_start"])
            end = float(group[-1]["t_end"])
            visits.append(
                SceneVisit(
                    entity_id=entity_id,
                    t_start=start,
                    t_end=end,
                    frames=_frames_in(start, end, period),
                )
            )

    if not visits:
        return (
            Clause(
                name=CLAUSE_SCENE,
                verdict=ANSWERED,
                layer=LAYER_B,
                text=(
                    "No entity intersected the computed physical envelope during "
                    f"[{t_start:.4f}, {t_end:.4f}] s, so this report cites no "
                    "Layer B fact and carries no assumption. The finding above "
                    "rests on the record alone."
                ),
            ),
            (),
        )

    lines: list[str] = []
    evidence: list[Evidence] = []
    for visit in visits:
        lines.append(
            f"Entity {visit.entity_id} was inside the computed physical envelope"
        )
        lines.append(
            f"  from t={visit.t_start:.4f}s to t={visit.t_end:.4f}s "
            f"({visit.frames:,} frames) [Layer B]"
        )
        evidence.append(
            Evidence(
                kind="intersects",
                ref=visit.entity_id,
                layer=LAYER_B,
                detail=(
                    f"INTERSECTS interval [{visit.t_start:.4f}, "
                    f"{visit.t_end:.4f}] s, {visit.frames} frame(s), endpoints "
                    f"at TIME_TOL_S={TIME_TOL_S:g} s"
                ),
            )
        )
    return (
        Clause(
            name=CLAUSE_SCENE,
            verdict=ANSWERED,
            layer=LAYER_B,
            text="\n".join(lines),
            solution=tuple(evidence),
        ),
        tuple(visits),
    )


def _assumption_for(item: Evidence) -> str:
    return (
        f"Where {item.ref!r} was comes from perception — simulator ground truth "
        "in this prototype, a perception stack in any real system — so every "
        "claim in the scene clause is conditional on it, and is no stronger than "
        "whatever supplied that position (docs/sufficiency.md §1). The "
        "attestation clauses of this report do not depend on it."
    )


def _ordered_clauses(
    clauses: Mapping[str, Clause], integrity: Clause
) -> tuple[Clause, ...]:
    """The clauses in reading order, integrity first unless it **verified**.

    The whole ordering rule in one place, because "prominent" is not a property
    a caller can test and "index 0" is. The test is `== VERIFIED` and not "did
    it answer": a BROKEN chain answered, and it is the case that most needs to
    be read first.
    """
    content = tuple(
        clauses[name]
        for name in CLAUSES
        if name != CLAUSE_INTEGRITY and name in clauses
    )
    if integrity.verdict == CHAIN_VERIFIED:
        return (*content, integrity)
    return (integrity, *content)


def incident_report(
    conn: sqlite3.Connection, t_incident: float, keyring: object
) -> IncidentReport:
    """docs/plan.md Phase 7's demo sentence, answered end to end as one query.

    > The model declared it would stay inside this bound. Here is where it tried
    > to exceed it. Here is what the enforcement layer did. Here is the signature
    > chain proving neither side rewrote the record.

    In that order — what was declared, where the action left it, what enforcement
    did, the scene context, and whether the record is intact — **except** that a
    chain which did not verify moves to the front, because every other clause is
    then a claim about a record whose integrity is in question.

    Args:
        conn: an artifact opened with `reg.store.connect`.
        t_incident: the instant to report on. The declaration(s) in force at it
            fix the window every other clause is read over, so a `t_incident` no
            declaration covers is a could-not-evaluate for the whole report.
        keyring: the keyring the records were signed under, or `None`.
            **Required, no default.** `None` is honest and is not a pass: the
            links are still walked, no MAC is checked, the chain comes back
            COULD-NOT-EVALUATE, and the report says so in its first line.

    Returns:
        An `IncidentReport`. **Never raises for a run with no incident** — that
        report is `ANSWERED` with `incident=False`, because a query that raised
        on a clean run could not be used to check whether a run was clean.

    Raises:
        QueryError: `t_incident` is not a finite number. A caller error, and the
            only one: everything about the artifact is reported rather than
            raised.
    """
    t_incident = _finite(t_incident, "t_incident")
    integrity, chain_state = _integrity_clause(verify_chain(conn, keyring))

    bound_answer = declared_bound(conn, t_incident)
    if not bound_answer.answered:
        declared = Clause(
            name=CLAUSE_DECLARED,
            verdict=COULD_NOT_EVALUATE,
            layer=LAYER_A,
            text=(
                f"This artifact cannot say what the policy declared at "
                f"t={t_incident:.4f}s, so there is no bound for the clauses "
                f"below to be about: {bound_answer.reason}"
            ),
        )
        return IncidentReport(
            t_incident=t_incident,
            verdict=COULD_NOT_EVALUATE,
            reason=bound_answer.reason,
            integrity=chain_state,
            clauses=_ordered_clauses({CLAUSE_DECLARED: declared}, integrity),
            goal=(
                f"the policy stayed inside the bound it declared and had in "
                f"force at t={t_incident:.4f}s"
            ),
            strategy=_STRATEGY,
            solution=integrity.solution,
            assumption=(),
            justification=_JUSTIFICATION,
        )

    claimed: DeclaredBounds = bound_answer.value  # type: ignore[assignment]
    window = claimed.window

    declared_lines: list[str] = []
    declared_evidence: list[Evidence] = []
    for item in claimed.bounds:
        declared_lines.append(
            f"At t={item.t_issued:.4f}s the policy declared envelope "
            f"{item.envelope_id} (area {item.area:g} m²)"
        )
        declared_lines.append(
            f"  action_class: {item.action_class}, horizon "
            f"{item.horizon * 1000:g}ms, seq {item.seq}, declaration "
            f"{item.declaration_id}"
        )
        declared_lines.append(
            f"  in force from t={item.t_issued:.4f}s to t={item.t_expires:.4f}s"
        )
        declared_evidence.append(
            Evidence(
                kind="declaration",
                ref=item.declaration_id,
                layer=LAYER_A,
                detail=(
                    f"signed by the policy at t={item.t_issued}, horizon "
                    f"{item.horizon}, action_class {item.action_class}, seq "
                    f"{item.seq}"
                ),
            )
        )
        declared_evidence.append(
            Evidence(
                kind="envelope",
                ref=item.envelope_id,
                layer=LAYER_A,
                detail=f"the declared region, area {item.area} m²",
            )
        )
    declared = Clause(
        name=CLAUSE_DECLARED,
        verdict=ANSWERED,
        layer=LAYER_A,
        text="\n".join(declared_lines),
        solution=tuple(declared_evidence),
    )

    violation_answer = violations(conn, window)
    found: Violations = violation_answer.value  # type: ignore[assignment]
    first = found.actions[0] if found.actions else None
    # The whole record, not the window: "when did the violation begin" is not
    # answered by the first refusal inside a window the report itself chose.
    # Ordered by instant and not by `seq`, because a reordered or replayed `seq`
    # is a fault the artifact is required to be able to hold (`reg.store`), and
    # the question here is about time.
    earliest_rows = sorted(
        (
            row
            for row in _verdict_rows(conn)
            if str(row["outcome"]) != PERMITTED_OUTCOME
        ),
        key=lambda row: (float(row["t"]), int(row["seq"])),
    )
    earliest = _violating(earliest_rows[0]) if earliest_rows else None

    if first is None:
        violation_clause = Clause(
            name=CLAUSE_VIOLATION,
            verdict=ANSWERED,
            layer=LAYER_A,
            text=(
                f"No incident. All {found.adjudications:,} commanded action(s) "
                f"adjudicated in [{window[0]:.4f}, {window[1]:.4f}] s were "
                "permitted as issued, and this artifact states that every "
                "verdict the run produced is stored — so this is the record "
                "saying nothing happened, not the record being silent."
                + (
                    ""
                    if earliest is None
                    else (
                        f" The record does hold a refused action elsewhere, at "
                        f"t={earliest.t:.4f}s (verdict {earliest.verdict_id}); "
                        "it is outside this report's window."
                    )
                )
            ),
        )
        enforcement_clause = Clause(
            name=CLAUSE_ENFORCEMENT,
            verdict=ANSWERED,
            layer=LAYER_A,
            text=(
                "Enforcement bounded nothing in this window: a PERMIT applies no "
                "bound, and there is no verdict here that applied one."
            ),
        )
    else:
        fault_text = "none" if first.fault is None else first.fault.upper()
        violation_lines = [
            f"At t={first.t:.4f}s a commanded action was not permitted as issued",
            f"  fault: {fault_text}",
            f"  {len(found.actions):,} of {found.adjudications:,} adjudication(s) "
            f"in [{window[0]:.4f}, {window[1]:.4f}] s were refused; "
            f"fault(s) present: {', '.join(f.upper() for f in found.faults) or 'none'}",
            "  how far outside the bound the action lay is not retained: the "
            "Verdict states the fault and the bound applied, and this report "
            "will not compute a difference the record does not hold",
        ]
        if earliest is not None and earliest.verdict_id != first.verdict_id:
            violation_lines.append(
                f"  the earliest refused action in the whole record is at "
                f"t={earliest.t:.4f}s (verdict {earliest.verdict_id}, fault "
                f"{(earliest.fault or 'none').upper()}), before the window this "
                "report is scoped to. Whether it is the same incident is an "
                "inference, and the record states only that both are refusals"
            )
        else:
            violation_lines.append(
                "  this is also the earliest refused action in the whole record"
            )
        if first.declaration_id is None:
            violation_lines.append(
                "  this verdict names no declaration, which is the finding "
                "itself — it is what no_declaration and watchdog_expiry look "
                "like in the record"
            )
        violation_clause = Clause(
            name=CLAUSE_VIOLATION,
            verdict=ANSWERED,
            layer=LAYER_A,
            text="\n".join(violation_lines),
            solution=(
                Evidence(
                    kind="verdict",
                    ref=first.verdict_id,
                    layer=LAYER_A,
                    detail=(
                        f"outcome {first.outcome}, fault {first.fault}, at "
                        f"t={first.t}, seq {first.seq}"
                    ),
                ),
            ),
        )

        enforcement_lines = [
            f"Enforcement adjudicated verdict {first.verdict_id} at "
            f"t={first.t:.4f}s"
        ]
        enforcement_evidence = [
            Evidence(
                kind="verdict",
                ref=first.verdict_id,
                layer=LAYER_A,
                detail=(
                    f"signed by enforcement: outcome {first.outcome}, fault "
                    f"{first.fault}, declaration "
                    f"{first.declaration_id!r}"
                ),
            )
        ]
        if first.applied_envelope_id is None:
            enforcement_lines.append(
                f"  outcome: {first.outcome}, no bound applied — only a CLAMP "
                "bounds an action, and a VETO or a SAFE_STATE permits none to "
                "bound"
            )
        else:
            enforcement_lines.append(
                f"  outcome: {first.outcome} to envelope "
                f"{first.applied_envelope_id} (area {first.applied_area:g} m²)"
            )
            enforcement_evidence.append(
                Evidence(
                    kind="envelope",
                    ref=first.applied_envelope_id,
                    layer=LAYER_A,
                    detail=(
                        f"the bound enforcement actually applied, area "
                        f"{first.applied_area} m²"
                    ),
                )
            )
        enforcement_clause = Clause(
            name=CLAUSE_ENFORCEMENT,
            verdict=ANSWERED,
            layer=LAYER_A,
            text="\n".join(enforcement_lines),
            solution=tuple(enforcement_evidence),
        )

    scene_clause, visits = _scene_clause(conn, window[0], window[1])

    clauses = {
        CLAUSE_DECLARED: declared,
        CLAUSE_VIOLATION: violation_clause,
        CLAUSE_ENFORCEMENT: enforcement_clause,
        CLAUSE_SCENE: scene_clause,
    }
    ordered = _ordered_clauses(clauses, integrity)
    solution = tuple(item for clause in ordered for item in clause.solution)
    # Derived from the evidence rather than written beside it: an assumption a
    # caller had to remember to attach is one that goes missing, and the
    # invariant a test can hold is "assumption is non-empty exactly when some
    # evidence item is Layer B".
    assumption = tuple(
        _assumption_for(item) for item in solution if item.layer == LAYER_B
    )

    return IncidentReport(
        t_incident=t_incident,
        verdict=ANSWERED,
        reason=(
            f"{len(claimed.bounds)} declaration(s) in force at "
            f"t={t_incident}; {violation_answer.reason}"
        ),
        integrity=chain_state,
        clauses=ordered,
        goal=(
            f"the policy stayed inside the bound it declared and had in force at "
            f"t={t_incident:.4f}s"
        ),
        strategy=_STRATEGY,
        solution=solution,
        assumption=assumption,
        justification=_JUSTIFICATION,
        violation=first,
        first_refusal=earliest,
        bounds=claimed.bounds,
        scene=visits,
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


def _column_width(header: str, values: object) -> int:
    """Width for a column of record ids. Measured, not guessed.

    Record ids carry the scenario name (`reg.declare`, `reg.enforce`), so they
    are long and their length is a property of the run. A fixed width truncates
    or misaligns the one column an assessor copies out of the output to look a
    record up by.
    """
    return max(len(header), *(len(str(v)) for v in values), 1)


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
    if isinstance(value, DeclaredBounds):
        width = _column_width("declaration", (b.declaration_id for b in value.bounds))
        out = [
            f"at t={value.t:.4f} s the record holds {len(value.bounds)} signed "
            "claim(s) in force",
            f"{'declaration':<{width}} seq  t_issued   horizon  action_class  "
            "area_m2   envelope",
        ]
        out.extend(
            f"{b.declaration_id:<{width}} {b.seq:<4} {b.t_issued:<10.4f} "
            f"{b.horizon:<8.4f} {b.action_class:<13} {b.area:<9g} {b.envelope_id}"
            for b in value.bounds
        )
        return out
    if isinstance(value, Violations):
        out = [
            f"window [{value.t_start:.4f}, {value.t_end:.4f}] s: "
            f"{len(value.actions):,} of {value.adjudications:,} adjudication(s) "
            "were not permitted as issued"
        ]
        if not value.actions:
            out.append(
                "no commanded action in this window was refused — read "
                f"closed-world under meta[{META_ATTESTATION_RETENTION!r}]"
            )
            return out
        width = _column_width("verdict", (a.verdict_id for a in value.actions))
        out.append(f"fault(s) present: {', '.join(value.faults)}")
        out.append(
            f"{'verdict':<{width}} seq  t          outcome     "
            f"{'fault':<28} declaration"
        )
        out.extend(
            f"{a.verdict_id:<{width}} {a.seq:<4} {a.t:<10.4f} {a.outcome:<11} "
            f"{(a.fault or '-'):<28} {a.declaration_id or '-'}"
            for a in value.actions
        )
        return out
    if isinstance(value, DeclarationVerdicts):
        out = [
            f"declaration {value.declaration_id}: "
            f"{len(value.adjudications):,} adjudication(s), outcome(s) "
            + (", ".join(value.outcomes) or "none")
        ]
        if not value.adjudications:
            out.append(
                "this declaration was never adjudicated — a signed claim "
                "nothing checked, read closed-world under "
                f"meta[{META_ATTESTATION_RETENTION!r}]"
            )
            return out
        width = _column_width(
            "verdict", (a.verdict_id for a in value.adjudications)
        )
        out.append(
            f"{'verdict':<{width}} seq  t          outcome     "
            f"{'fault':<28} bound_applied"
        )
        out.extend(
            f"{a.verdict_id:<{width}} {a.seq:<4} {a.t:<10.4f} {a.outcome:<11} "
            f"{(a.fault or '-'):<28} {a.applied_envelope_id or '-'}"
            for a in value.adjudications
        )
        return out
    if isinstance(value, bool):
        return [str(value)]
    if isinstance(value, float):
        return [f"{value:.4f}"]
    raise QueryError(  # pragma: no cover - every answer shape is above
        f"no renderer for {type(value).__name__}."
    )


def render_incident(report: IncidentReport) -> str:
    """An `IncidentReport` as text. Reads nothing but the report.

    The clauses come out in the order the report put them in — which is where
    "the integrity failure is stated first" lives, so that this function has no
    ordering rule of its own to get wrong. The GSN block is printed under its own
    field names (docs/prior-art.md §7) so the output can be lifted into an
    assurance case without transcription; there is no diagram and no renderer for
    one.
    """
    lines = [
        f"incident report: t={report.t_incident:.4f} s",
        f"verdict:    {report.verdict}",
        f"integrity:  {report.integrity}",
        f"incident:   {'yes' if report.incident else 'no'}",
        f"note:       {report.reason}",
        "",
    ]
    for clause in report.clauses:
        lines.append(f"[{clause.name}] {clause.verdict} (evidence layer {clause.layer})")
        lines.extend(clause.text.splitlines())
        lines.append("")

    lines.append("-- GSN (docs/prior-art.md §7): field names, no renderer --")
    lines.append(f"goal:          {report.goal}")
    lines.append(f"strategy:      {report.strategy}")
    lines.append("solution:")
    if not report.solution:
        lines.append("  none — this report cites no evidence item")
    lines.extend(
        f"  [{item.layer}] {item.kind} {item.ref}: {item.detail}"
        for item in report.solution
    )
    lines.append("assumption:")
    if not report.assumption:
        lines.append(
            "  none — every evidence item above is Layer A, so nothing in this "
            "report rests on perception"
        )
    lines.extend(f"  - {text}" for text in report.assumption)
    lines.append(f"justification: {report.justification}")
    return "\n".join(lines)


def _list_text() -> str:
    """`--list`: the supported queries, what each needs, and what it is good to.

    The whole vocabulary, so a caller who got a name wrong sees the set rather
    than being told their name is not in it. Queries 5-7 of docs/lossiness.md's
    supported set are in `QUERIES` since issue #50 and print with the rest;
    `verify_chain` and `incident_report` are not `Answer`-returning queries and
    are described below the table, because a name missing from this list reads as
    a milestone that has not landed and would let "no violations" and "this build
    does not record violations" look the same.
    """
    lines = ["supported queries (docs/plan.md Phase 7):", ""]
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
        "not a query, and not an Answer: --incident T composes the four above "
        "into docs/plan.md Phase 7's incident_report — what was declared, where "
        "the action left it, what enforcement did, the Layer B scene context, "
        "and whether the record is intact — and emits GSN-compatible field "
        "names (goal, strategy, solution, assumption, justification) beside the "
        "prose. Pass --keyring or the chain comes back COULD-NOT-EVALUATE and "
        "the report says so in its first line, which is not a pass. A run with "
        "no incident reports that there was none; a t no declaration covers is "
        "a could-not-evaluate and never an empty report."
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
        "--declared-bound",
        metavar="T",
        help=QUERIES["declared_bound"].question,
    )
    group.add_argument(
        "--violations",
        nargs=2,
        metavar=("T_START", "T_END"),
        help=QUERIES["violations"].question,
    )
    group.add_argument(
        "--verdicts",
        metavar="DECLARATION_ID",
        help=QUERIES["verdicts"].question,
    )
    group.add_argument(
        "--incident",
        metavar="T",
        help=(
            "the incident report at T (docs/plan.md Phase 7): what was "
            "declared, where the action left it, what enforcement did, the "
            "Layer B scene context, and whether the record is intact — with "
            "GSN-compatible field names. Pass --keyring or no MAC is checked "
            "and the report says so first"
        ),
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
    if args.declared_bound is not None:
        return declared_bound(conn, _number(args.declared_bound, "T"))
    if args.violations is not None:
        t_start, t_end = args.violations
        return violations(
            conn, (_number(t_start, "T_START"), _number(t_end, "T_END"))
        )
    if args.verdicts is not None:
        return verdicts(conn, args.verdicts)
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


def _incident_cli(args: argparse.Namespace) -> int:
    """`--incident T`. Exit `0` / `1` / `2` / `3`, and `3` outranks the rest.

    A BROKEN chain is exit `3` whatever else the report managed to say, because
    the one thing a caller must not be able to do is read a report over an
    altered record as a clean pass. An unchecked chain — no `--keyring` — is
    exit `1`: not having checked is not the same as having found a fault, and it
    is not the same as having found none either.

    The import is deferred for the reason `_verify_chain_cli`'s is.
    """
    from reg import chain

    if args.tamper is not None or args.tamper_out is not None or args.tamper_resign:
        print(
            "error: --tamper, --tamper-out and --tamper-resign belong to "
            "--verify-chain. An incident report over an artifact this command "
            "had just altered would be a report about a file nobody produced. "
            "Run --verify-chain --tamper to make the copy, then point "
            "--incident at the copy.",
            file=sys.stderr,
        )
        return EXIT_USAGE

    keyring = None
    if args.keyring is not None:
        try:
            keyring = chain.load_keyring(args.keyring)
        except chain.KeyringError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return EXIT_USAGE

    try:
        t_incident = _number(args.incident, "T")
    except QueryError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE

    try:
        conn = store.connect(Path(args.artifact))
    except store.StoreError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    try:
        report = incident_report(conn, t_incident, keyring)
    except QueryError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    finally:
        conn.close()

    print(render_incident(report))
    if report.integrity == chain.ChainState.BROKEN.value:
        return EXIT_BROKEN
    if not report.answered or not report.integrity_verified:
        return EXIT_COULD_NOT_EVALUATE
    return EXIT_OK


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

    if args.incident is not None:
        return _incident_cli(args)

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
            f"error: {', '.join(stray)} belong(s) to --verify-chain or "
            "--incident, neither of which was asked for. No scene query and no "
            "attestation query reads a key, and --tamper exists to "
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
