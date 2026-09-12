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

THE COLD READ, AND WHY IT IS NOT A QUERY EITHER (ISSUE #231)
-------------------------------------------------------------
`cold_read(conn)` asks docs/self-describing.md §2's question — *open an artifact
with the code that reads artifacts and no document; for every claim the file
makes, either it can be checked from the file or it cannot* — and answers it as
a row per claim, in five states. It ships here rather than in `tests/` because
the audience for it is an assessor holding a file, and a check they cannot run
tells them nothing. It closes no gap. Since issue #242 it covers docs/plan.md
Claim 4 as well, in two rows: *has this record been altered since it was
written* is checkable **with a key the file does not contain**, which is the
fifth state and the only claim here whose verification is deliberately gated;
*was the passivation acknowledged, and by whom* is checkable from the file
alone. Since issue #262 a seventh row reads back what the artifact states about
the obligations its own existence creates — the three keys issue #125 made the
build write and nothing read — in the five states that already exist, because
that is one more claim and not one more state. See the section above `cold_read`
for the states, for why nothing here imports `reg.graph` or `reg.chain` to
compute them, and for what is pinned to `schema_version` 14.

LAYER
-----
Split, and it says so per query. Every *scene* question names an entity, and
where an entity is comes from perception in any real system (docs/plan.md Phase
9), so those are Layer B. Every *attestation* question is Layer A. The layer tag
travels on every edge and this module never invents one.

`reached_point` is the one question in neither half: it names no entity and
reads no signed record, only the outer boundary the artifact retains. Its spec
carries the **weaker** of the two letters that question can have and the answer
carries the one this file actually holds — see `_ROOM_FRAME_LAYER`.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import math
import sqlite3
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from shapely.geometry import Point

from reg import store
from reg.envelope import outer_radius
from reg.tolerances import (
    AREA_QUANT_SIGFIGS,
    DISTANCE_TOL_M,
    TIME_TOL_S,
    quantize_time,
)

__all__ = [
    "ABSENT",
    "ACKNOWLEDGING_PARTY",
    "ANSWERED",
    "ATTESTATION_LAYER",
    "ATTESTATION_PRESENT",
    "CHAIN_VERIFIED",
    "CHECKABLE",
    "CHECKABLE_WITH_A_KEY",
    "CLAUSES",
    "CLAUSE_DECLARED",
    "CLAUSE_ENFORCEMENT",
    "CLAUSE_INTEGRITY",
    "CLAUSE_SCENE",
    "CLAUSE_VIOLATION",
    "CLAIM_ACKNOWLEDGMENT",
    "CLAIM_CHAIN_INTACT",
    "CLAIM_DISCLOSURES",
    "CLAIM_ENVIRONMENT",
    "CLAIM_LAYER_BASIS",
    "CLAIM_REACHED_POINT",
    "CLAIM_RECOMPUTE",
    "COLD_READ_CLAIMS",
    "COLD_READ_DISCLOSURE_KEYS",
    "COLD_READ_QUESTIONS",
    "COLD_READ_RECOMPUTE_KEYS",
    "COLD_READ_RECORD_CHAINS",
    "COLD_READ_RECORDED_ONLY_KEYS",
    "COLD_READ_SCHEMA_VERSION",
    "COLD_READ_STATES",
    "COULD_NOT_EVALUATE",
    "DPIA_NONE",
    "EDGE_LAYER",
    "EXIT_BROKEN",
    "EXIT_COULD_NOT_EVALUATE",
    "EXIT_OK",
    "EXIT_USAGE",
    "GSN_FIELDS",
    "LAYER_A",
    "LAYER_B",
    "META_ACKNOWLEDGMENT_COUNT",
    "META_ATTESTATION_RECORDS",
    "META_ATTESTATION_RETENTION",
    "META_DECLARATION_COUNT",
    "META_DPIA_REFERENCE",
    "META_ENVELOPE_RETENTION",
    "META_FRAME_COUNT",
    "META_GEOMETRY_RETENTION",
    "META_OCCURRENCE_RESOLUTION",
    "META_OCCURRENCE_RETENTION",
    "META_T_FIRST",
    "META_T_LAST",
    "META_OPERATOR_ID",
    "META_OPERATOR_ID_KIND",
    "META_VERDICT_COUNT",
    "META_WORKER_NOTICE",
    "OCCURRENCE_LAYER",
    "OPERATOR_ID_KINDS",
    "OUTER_BOUNDARY_COLUMN",
    "PASSIVATING_OUTCOMES",
    "PERMITTED_OUTCOME",
    "QUERIES",
    "READABLE_NOT_CHECKABLE",
    "Acknowledged",
    "Adjudication",
    "Answer",
    "Clause",
    "ColdRead",
    "ColdReadClaim",
    "DeclarationVerdicts",
    "DeclaredBound",
    "DeclaredBounds",
    "EnvelopeIntersection",
    "Evidence",
    "FramesAtRisk",
    "IncidentReport",
    "OverlapInterval",
    "Passivation",
    "Passivations",
    "PointwiseCoverage",
    "QueryError",
    "QuerySpec",
    "ReachableEntities",
    "ReachedPoint",
    "RiskInterval",
    "SceneVisit",
    "SeparationTimeline",
    "ViolatingAction",
    "Violations",
    "WORKER_NOTICE_DATE_FORMAT",
    "WORKER_NOTICE_GIVEN",
    "WORKER_NOTICE_NOT_APPLICABLE",
    "WORKER_NOTICE_NOT_GIVEN",
    "WORKER_NOTICE_STATUSES",
    "acknowledgments",
    "attestation_state",
    "available_layers",
    "cold_read",
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
    "pointwise_coverage",
    "reachable_entities",
    "reached_point",
    "render",
    "render_chain_report",
    "render_cold_read",
    "render_commitment_check",
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

#: Which frames get an envelope row at all, in prose, in the artifact. It is
#: what makes a *no envelope in force at t* refusal legible: the instant belongs
#: either between two frames or to a frame this rule retained no configuration
#: for, and the file says which rule that is rather than leaving a reader to
#: infer it from the pattern of gaps.
META_ENVELOPE_RETENTION = "envelope_row_retention"

#: Which of those rows keep a polygon — and, since issue #257, which keep the
#: **outer** boundary, that being the same rule and not a second one. It is the
#: rule `reached_point` refuses under, so the refusal quotes the key rather than
#: describing the rule in prose the file cannot be checked against.
META_GEOMETRY_RETENTION = "envelope_geometry_retention"

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
#: them (`reg.chain`), and this module never re-derives that comparison. The
#: third arrived with the `Acknowledgment` (issue #247) and is read for the same
#: reason and nothing more: the cold read quotes what the artifact states its
#: chains should hold, and a count this module compared itself would be a second
#: opinion about a chain it does not walk.
META_DECLARATION_COUNT = "declaration_count"
META_VERDICT_COUNT = "verdict_count"
META_ACKNOWLEDGMENT_COUNT = "acknowledgment_count"

#: Who the build said was responsible for the run (issue #83). Read only by
#: `acknowledgments`, and read as *the operator this artifact names* and never as
#: *the person who acknowledged*: the record is signed under the enforcement key
#: and carries no human field, so these are two facts and the answer keeps them
#: apart. Absent is `None` — an artifact that names no operator is not one whose
#: operator this module may guess.
META_OPERATOR_ID = "operator_id"

#: This module's copy of the three keys a build writes from a `Disclosures`
#: (issue #125): what the deployer states about the obligations
#: `docs/limitations.md` §8 names. Spelled here rather than imported from
#: `reg.graph` for the reason every `meta` key above is, and held to the writer
#: by `tests/test_query.py::test_the_meta_keys_this_module_reads_are_the_ones_
#: the_builder_writes`. Read only by `_disclosures_claim`, which reads them back
#: verbatim and interprets none of them.
META_WORKER_NOTICE = "worker_notice"
META_DPIA_REFERENCE = "dpia_reference"
META_OPERATOR_ID_KIND = "operator_id_kind"

#: The three together, in the order the row reports them. A tuple because the
#: claim is about the block and not about any one key: all three stated is a
#: statement, none stated is silence, and some stated is neither — which is the
#: distinction the row would lose if it read them one at a time.
COLD_READ_DISCLOSURE_KEYS = (
    META_WORKER_NOTICE,
    META_DPIA_REFERENCE,
    META_OPERATOR_ID_KIND,
)

#: The two values a deployer says *nothing was done* with:
#: `reg.identity.WorkerNoticeStatus.NOT_GIVEN.value` and
#: `reg.identity.DPIA_NONE`. Named here rather than imported for
#: `PERMITTED_OUTCOME`'s reason — this module names its own copy of another
#: module's vocabulary and pays for it with a test — and
#: `tests/test_query.py::test_the_stated_negatives_are_the_ones_reg_identity_
#: writes` compares the two sides. The row needs them to say what the ABSENT
#: state is *not*: an artifact carrying either has stated a negative, and a
#: report that could not point at the difference would leave silence and a
#: stated *no* reading the same, which is the inversion issue #125 closed at
#: the writing end.
WORKER_NOTICE_NOT_GIVEN = "not-given"
DPIA_NONE = "none"

#: The rest of the writer's grammar for two of the three keys (issue #268), on
#: the same terms as the two negatives above: spelled a second time because this
#: module cannot import `reg.identity` without contradicting its own header, and
#: held to the writer by
#: `tests/test_query.py::test_the_disclosure_grammar_is_the_one_reg_identity_
#: enforces` — which compares **behaviour** over a table of candidate values
#: rather than constants, because equal enum values would leave the date and
#: reason rules free to drift apart in silence.
#:
#: `reg.identity` refuses a build on anything outside this, so a `meta` value
#: outside it was written by something else or edited since. The row reports
#: that as a could-not-evaluate rather than reading it back as the deployer's
#: statement.
#:
#: **`dpia_reference` is not here and gets no grammar.** It is free text by
#: design — any text that locates the assessment, or `DPIA_NONE` — and a
#: vocabulary acquired by accident on the reading side would refuse artifacts
#: the writer accepts, which is the inversion of what this check is for.
WORKER_NOTICE_GIVEN = "given"
WORKER_NOTICE_NOT_APPLICABLE = "not-applicable"
WORKER_NOTICE_STATUSES = (
    WORKER_NOTICE_GIVEN,
    WORKER_NOTICE_NOT_GIVEN,
    WORKER_NOTICE_NOT_APPLICABLE,
)
WORKER_NOTICE_DATE_FORMAT = "%Y/%m/%d"
OPERATOR_ID_KINDS = ("pseudonym", "direct-identifier")

#: `reg.identity._NOTICE_SEPARATOR`: one space between a worker-notice status
#: and whatever the status requires beside it, so the value splits in one
#: partition and the status is the first thing a reader's eye lands on.
_NOTICE_SEPARATOR = " "

#: `reg.identity._FORBIDDEN_ID_CHARS`, applied where the writer applies it — the
#: reason a `not-applicable` carries. `meta` is text, and a newline splits one
#: value across lines while a NUL truncates it, so a value carrying either is
#: not one the writer would have stored.
_FORBIDDEN_DISCLOSURE_CHARS = ("\n", "\r", "\t", "\x00")

#: The party an acknowledgment is attributable to: the role whose key signed it,
#: which is `reg.enforce.Acknowledgment.SIGNING_ROLE`. Spelled here rather than
#: imported for the reason the `meta` keys above are, and
#: `tests/test_query.py::test_the_acknowledging_party_is_the_signing_role`
#: compares the two sides. It is a **party and not a person**, and that is the
#: honest limit of what the file can attribute: the policy cannot clear its own
#: fault (`reg.enforce`), which is what the role being *enforcement* records.
ACKNOWLEDGING_PARTY = "enforcement"

#: The one outcome that is not a finding against the commanded action. Named
#: here rather than imported from `reg.enforce.OUTCOMES`, which is the
#: vocabulary's single definition, because importing it would pull `reg.declare`
#: and `reg.chain` — and through them the raw stream — into this module at import
#: time. `tests/test_query.py::test_the_outcome_vocabulary_is_the_enforcers`
#: compares the two sides and fails on a rename, which is the same bargain the
#: `meta` keys above are held to.
PERMITTED_OUTCOME = "PERMIT"

#: The two outcomes that stop the robot, so a verdict carrying one opens a
#: **passivation** (issue #247). Named here rather than imported from
#: `reg.enforce.PASSIVATING_FAULTS` for `PERMITTED_OUTCOME`'s reason, and
#: `tests/test_query.py::test_the_passivating_outcomes_are_the_enforcers`
#: compares the two sides: enforcement passivates on every fault except
#: `declaration_action_mismatch`, whose response is the CLAMP, so *outcome is
#: VETO or SAFE_STATE* and *fault passivates* pick out the same verdicts. Two
#: definitions that must agree is a thing this module already lives with; a
#: definition that reached into `reg.enforce` would cost Claim 2's import
#: property, which is the more expensive of the two.
PASSIVATING_OUTCOMES: tuple[str, ...] = ("VETO", "SAFE_STATE")

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

#: `reached_point`'s evidence layer, and it is deliberately *not* `_SCENE_LAYER`
#: under a second name — that constant means "this question names an entity",
#: and this one names none (issue #258).
#:
#: **It is the weaker of the two letters the question can have, and the reason
#: is that a spec cannot carry a condition.** docs/sufficiency.md §5.1 classifies
#: *could the robot have reached (x, y) at t* as **Layer A** — `HAS_ENVELOPE` is
#: the one Layer A edge type naming no `Entity` — and states a condition in the
#: same breath: the `(x, y)` is a **room** coordinate, so the answer is only as
#: strong as whatever put the robot in the room (§5.6). The retained boundary is
#: the placed, room-frame region, so on a run whose base drove it inherits the
#: localizer that supplied the pose, and `reg.store.open_edge` tags that edge `B`.
#: A static `A` here would print "evidence layer A" over an answer the file
#: itself tags `B`, which is the one direction that must not happen: under-
#: claiming never turns a Layer B answer into a certifiable one, over-claiming
#: does the reverse. The letter the *file* holds travels on the answer, as
#: `ReachedPoint.envelope_layer`, read off the covering edge and never inferred.
_ROOM_FRAME_LAYER = LAYER_B

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
    # The pointwise reachability question (issue #258), and the reason it sits
    # between the two halves rather than in either: it names no entity, so it is
    # not a scene question, and it reads no signed record, so it is not an
    # attestation one. What it reads is the retained *outer* boundary — the one
    # thing in this artifact that is a region the robot could not leave.
    "reached_point": QuerySpec(
        name="reached_point",
        question=(
            "whether the robot could have reached the room-frame point (x, y) "
            "at time t, tested against the outer boundary the file retains"
        ),
        answerable_from=frozenset({EDGE_LAYER}),
        arguments=("X_M", "Y_M", "T"),
        tolerance=(
            "t is quantized to TIME_TOL_S, because that is the resolution the "
            "HAS_ENVELOPE endpoints were recorded at; the containment test "
            "itself is exact and has no tolerance at all. The retained outer "
            "boundary is the one polygon in this artifact that is **not** "
            "simplified (reg.graph, issue #257), so no length in this answer "
            "has been rounded and DISTANCE_TOL_M is not spent here"
        ),
        why_not=(
            "The occurrence layer holds events at instants. It retains no "
            "envelope row, so there is no boundary in it to test a point "
            "against, and no robot_config row either, so there is nothing to "
            "recompute one from (docs/lossiness.md, Level 1)."
        ),
        layer_tag=_ROOM_FRAME_LAYER,
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
    "acknowledgments": QuerySpec(
        name="acknowledgments",
        question=(
            "every passivation of the run, and for each one whether it was "
            "acknowledged, by which party, when and why"
        ),
        answerable_from=frozenset({ATTESTATION_LAYER}),
        arguments=(),
        tolerance=(
            "none — exact field equality against the stored records. The "
            "instants are the ones the acknowledgment and the verdict were "
            "signed at and are not quantized"
        ),
        why_not=(
            "An acknowledgment is a signed record of what a party stated. It is "
            "in the enforcement chain or it is nowhere; no density of scene "
            "edges reconstructs a party clearing a fault."
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


@dataclass(frozen=True)
class PointwiseCoverage:
    """How much of a run *could the robot have reached (x, y)* can be put to.

    **The answer states its own coverage because a `no` here is worthless
    without it** (issue #258). `reg.graph.GEOMETRY_RETENTION` keeps the outer
    boundary at the frames the artifact already says something happened at — the
    two ends of the run, every relationship transition, every posed frame — and
    at no others, so most frames have no region to test a point against. A
    caller who reads *this artifact cannot answer at t* as *the robot could not
    have been there* has drawn the one conclusion the retention rule does not
    support, and the numbers below are what stops that reading being available.

    `pointwise_rows` is envelope rows carrying `outer_wkb`; `radial_rows` is
    rows carrying `outer_radius`, which is every computed one. `frames` is the
    run's frame count from `meta`, not a row count: the ratio a reader wants is
    *answerable frames over frames*, and a row count would quietly answer a
    smaller question with a larger-looking number.
    """

    frames: int
    envelope_rows: int
    pointwise_rows: int
    radial_rows: int


@dataclass(frozen=True)
class ReachedPoint:
    """Whether one room-frame point was inside the retained outer set at `t`.

    **`could_have_reached` is not symmetric, and the asymmetry is the answer.**
    `reg.envelope.outer_envelope` over-approximates: every configuration the
    robot can reach within the horizon has its body inside that region, and
    there are points inside it the robot cannot reach. So `False` is a **sound
    exclusion** — the robot could not have been there — and `True` is *this
    artifact does not exclude it*, which is what the word "could" in the
    question is doing. A reader who inverts the two has turned an outer bound
    into an inner one.

    `envelope_layer` is the `layer` column on the `HAS_ENVELOPE` edge that put
    this envelope in force, read off the row and never inferred. It is `A` for
    the fixed-base runs in this repository and `B` for a run whose bound or base
    velocity came out of a perceiver, or whose configuration states a pose
    (`reg.store.open_edge`, docs/sufficiency.md §5.6) — see `_ROOM_FRAME_LAYER`
    for why the spec's own letter is the weaker one.

    `outer_radius_m` travels beside the exact answer rather than instead of it.
    Issue #258 added a question and removed none: the radius is still on the row
    and still answers *not at that distance*, about the centre
    `reg.graph.envelope_frame` names. The boundary answers *not at that point*,
    and needs no centre to do it, being already placed in the room.
    """

    x: float
    y: float
    t: float
    could_have_reached: bool
    envelope_id: str
    envelope_layer: str
    outer_area_m2: float
    outer_radius_m: float
    coverage: PointwiseCoverage


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
class Acknowledged:
    """One acknowledgment as the artifact holds it: who, when and why.

    **`party` is the honest answer to "by whom", and it is a party and not a
    person.** The record is signed under the enforcement key, so what the
    artifact can attribute is the key-holding role; the human who decided is not
    a field of `reg.enforce.Acknowledgment` and is not invented here.
    `operator_id` is the run's own `meta` value — the operator the build was told
    was responsible for the run (issue #83) — and it is `None` when the artifact
    states none. Between them they say as much as the file holds and no more,
    which is why they are two fields and not one blended attribution.
    """

    ack_id: str
    seq: int
    t: float
    fault: str
    reason: str
    #: The signing role of the enforcement chain. A constant of the record's
    #: class rather than a column, carried here so a reader of an `Answer` does
    #: not have to know which key signs what.
    party: str
    #: `meta[operator_id]`, or `None` if the artifact states none.
    operator_id: str | None


@dataclass(frozen=True)
class Passivation:
    """One stretch of the run in which enforcement had the robot stopped.

    `verdict_id` is the verdict that opened it — the one an `Acknowledgment` may
    name. `t_end` is the instant of the first verdict that resumed adjudicating,
    or `None` for a passivation the run never came out of, which is a fact about
    the run and not a missing value.

    `acknowledgment` is `None` when this artifact holds no acknowledgment naming
    the opening verdict. That is **not** a statement that nobody acknowledged it:
    the record is of what enforcement was told, and an operator who cleared the
    cell without telling it leaves the same absence. `Passivations.answered` is
    what turns that into the query's three-valued verdict.
    """

    verdict_id: str
    seq: int
    fault: str
    t_start: float
    t_end: float | None
    #: Verdicts emitted while this passivation was in force, including the one
    #: that opened it. Every one after the first is enforcement *reporting* the
    #: stop rather than raising a new fault.
    verdicts: int
    acknowledgment: Acknowledged | None

    @property
    def acknowledged(self) -> bool:
        return self.acknowledgment is not None


@dataclass(frozen=True)
class Passivations:
    """docs/plan.md Phase 4's asymmetry, answered from the file (issue #247).

    An empty `passivations` is a run enforcement never stopped, and it is an
    **answer**: nothing needed acknowledging, so the question is closed rather
    than unanswerable. That is the one case where an empty list here is not
    silence, and it is why `answered` is a property of this shape rather than a
    count somewhere else.
    """

    passivations: tuple[Passivation, ...]
    #: Acknowledgments the artifact holds that name no passivation this walk
    #: found. Empty in any artifact `reg.graph` wrote — it is here because the
    #: alternative to carrying them is dropping them, and a record nobody can
    #: see is worse than one nobody expected.
    unmatched: tuple[Acknowledged, ...]

    @property
    def unacknowledged(self) -> tuple[Passivation, ...]:
        return tuple(p for p in self.passivations if not p.acknowledged)

    @property
    def answered(self) -> bool:
        """Whether *and by whom* has an answer for every passivation of the run."""
        return not self.unacknowledged and not self.unmatched


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
# The pointwise reachability question (issue #258, option C of #228).
#
# `outer_wkb` arrived at `SCHEMA_VERSION` 14 and this is what reads it. The one
# rule everything below is arranged around:
#
#   **A RADIAL ANSWER MUST NEVER BE RETURNED WEARING A POINTWISE ONE'S CLOTHES.**
#
# At a frame the retention rule kept no boundary for, `outer_radius` is right
# there on the row and would produce a plausible `True`/`False` for the point.
# It would be an answer to a different question — *not at that distance* rather
# than *not at that point* — arriving in the shape of this one, and nothing
# downstream could tell the two apart. So a frame with no boundary is a
# could-not-evaluate that names the rule, and the radius is reported as a datum
# beside an answer and never as one.
# --------------------------------------------------------------------------

#: The column the whole question rests on. Named once, because it is quoted in
#: three refusals and a constant is what keeps them saying the same thing.
OUTER_BOUNDARY_COLUMN = "outer_wkb"


def _has_outer_boundary_column(conn: sqlite3.Connection) -> bool:
    """Whether the `envelope` table has an `outer_wkb` column at all.

    The pre-#257 arm, and it is reachable for the reason `cold_read`'s
    older-schema arm is: `reg.store.connect` refuses a `schema_version` this
    build does not understand, so an assessor holding an archived artifact meets
    this through whatever `sqlite3` they have. A file written against schema 13
    is not a file that retained no boundary — it is one written before the rule
    existed, and the two must not report the same way.
    """
    return any(
        str(row["name"]) == OUTER_BOUNDARY_COLUMN
        for row in conn.execute("PRAGMA table_info(envelope)").fetchall()
    )


def pointwise_coverage(conn: sqlite3.Connection) -> PointwiseCoverage:
    """How many of this run's frames `reached_point` can be asked about.

    Public, and not merely a field on the answer, because a caller has to be
    able to learn it **before** and **without** asking about a point — a refusal
    at one instant says nothing about how much of the run is covered, and the
    number that makes the refusal readable must not be reachable only through an
    answer that exists.

    Raises:
        QueryError: the `envelope` table has no `outer_wkb` column, so this file
            predates the retention rule the numbers would be about. Returning
            zero would report an archive as an artifact that chose to retain
            nothing, which is the distinction issue #257 put in the schema.
    """
    if not _has_outer_boundary_column(conn):
        raise QueryError(
            f"this artifact's envelope table has no {OUTER_BOUNDARY_COLUMN!r} "
            f"column, so it was written against a schema older than "
            f"{store.SCHEMA_VERSION} and the outer boundary had nowhere to go "
            "(issue #257). Reporting zero covered frames would say this build "
            "retained no boundary, which is a decision somebody would have had "
            "to take; nobody took it here."
        )
    row = conn.execute(
        "SELECT count(*)             AS envelope_rows, "
        f"      count({OUTER_BOUNDARY_COLUMN}) AS pointwise, "
        "       count(outer_radius)  AS radial "
        "FROM envelope"
    ).fetchone()
    return PointwiseCoverage(
        frames=int(_meta_float(conn, META_FRAME_COUNT)),
        envelope_rows=int(row["envelope_rows"]),
        pointwise_rows=int(row["pointwise"]),
        radial_rows=int(row["radial"]),
    )


def _coverage_text(coverage: PointwiseCoverage) -> str:
    """The coverage sentence, on every answer and on every refusal alike."""
    return (
        f"{coverage.pointwise_rows} of this run's {coverage.frames} frame(s) "
        "are pointwise-answerable: of the "
        f"{coverage.envelope_rows} envelope row(s) retained, "
        f"{coverage.radial_rows} carry an outer_radius and "
        f"{coverage.pointwise_rows} carry the boundary that radius projects "
        f"(the rule meta[{META_GEOMETRY_RETENTION!r}] states in this "
        "artifact's own words). A frame with no answer here is a frame no "
        "region was retained "
        "at, and never a point the robot could not have reached."
    )


def reached_point(
    conn: sqlite3.Connection, x: float, y: float, t: float
) -> Answer:
    """Could the robot have reached the room-frame point `(x, y)` at `t`?

    **Answered exactly where it is answered at all**: the point is tested
    against the outer boundary the row retains, which is the placed, room-frame
    region and is not simplified. Where the row retains none the answer is a
    could-not-evaluate that names the retention rule — never the radius, and
    never a bare *no*.

    **A boundary its own row contradicts is a could-not-evaluate too.** No
    digest covers the blob, so a smaller region swapped in leaves the chain
    VERIFIED and turns a point the robot could reach into an exclusion — a
    false accusation, the direction this answer must not get wrong. What the
    file can still check is itself, against **both** figures the row carries: a
    blob whose area disagrees with `outer_area` by more than that figure's
    quantum is refused, and so is one whose furthest point from the envelope's
    own centre disagrees with `outer_radius` by more than `DISTANCE_TOL_M`
    (issue #265). The second is what catches the correct region *moved*, which
    keeps its area and every point of which has shifted. The centre comes from
    `reg.store.envelope_base_frame`; where the artifact states none, the check
    cannot run and this answer refuses rather than skipping it.

    **What the pair still does not catch, stated rather than implied.** A region
    **rotated about its own centre** keeps both its area and its radius, and so
    does any replacement matching both figures — a spiral, an annulus sector, a
    region of the right size somewhere else about the same centre. Two scalars
    constrain two numbers and not a shape. This is the file agreeing with
    itself, and it is never the region shown to be the one the build computed;
    a digest over `outer_wkb` is what that would take and this artifact has
    none.

    The direction of the answer is `ReachedPoint.could_have_reached`'s: the
    outer set over-covers, so `False` excludes soundly and `True` says only that
    this artifact does not exclude it. `covers` rather than `contains`, so a
    point exactly on the boundary answers *not excluded*; an over-approximation
    that refused its own edge would be reporting an exclusion it has not earned.

    Args:
        conn: an open artifact.
        x, y: the point, in the **room** frame — the frame the retained region
            is already in, so the containment test itself spends no tolerance
            and needs no centre. The *agreement check* does need one, which is
            why a file stating no frame refuses here.
        t: seconds, quantized to `TIME_TOL_S` on the way in.

    Returns:
        An `Answer` whose `value` is a `ReachedPoint`, or a `COULD-NOT-EVALUATE`
        with `value=None`. Every refusal carries `_coverage_text`, so a reader
        who meets one learns how much of the run is covered at the same moment
        they learn this instant is not.

    Raises:
        QueryError: `x`, `y` or `t` is not a finite number. A caller error, and
            distinct from every refusal above it.
    """
    spec = QUERIES["reached_point"]
    x = _finite(x, "x")
    y = _finite(y, "y")
    t = quantize_time(_finite(t, "t"))

    layers = available_layers(conn)
    if _layer_for(spec, layers) is None:
        return _no_layer(spec, layers)
    if not _has_outer_boundary_column(conn):
        return _refuse(
            spec,
            layers,
            f"Its envelope table has no {OUTER_BOUNDARY_COLUMN!r} column, so it "
            f"was written against a schema older than {store.SCHEMA_VERSION} "
            "and the outer boundary had nowhere to go (issue #257). That is a "
            "fact about when this file was built and not an absence anybody "
            "chose, so it is reported as one and not as *no region was "
            "retained*.",
        )

    coverage = pointwise_coverage(conn)
    edges = store.read_edges(conn, edge_type="HAS_ENVELOPE")
    covering = [row for row in edges if row["t_start"] <= t <= row["t_end"]]
    if not covering:
        span = (
            f" spanning [{min(r['t_start'] for r in edges)}, "
            f"{max(r['t_end'] for r in edges)}]"
            if edges
            else ""
        )
        return _refuse(
            spec,
            layers,
            f"No envelope is recorded as being in force at t={t}. It holds "
            f"{len(edges)} HAS_ENVELOPE interval(s){span}, and an instant "
            "outside them belongs either between two frames or to a frame "
            f"meta[{META_ENVELOPE_RETENTION!r}] retained no configuration "
            "for. The neighbouring frame's region is a region the robot could "
            f"reach at a different instant. {_coverage_text(coverage)}",
        )
    if len(covering) > 1:
        return _refuse(
            spec,
            layers,
            f"{len(covering)} envelopes are recorded as in force at t={t}. Two "
            "transitions inside one TIME_TOL_S quantum have no retained order "
            "(docs/lossiness.md Unanswerable #5), so there is no way to say "
            "which region this instant belongs to — and testing the point "
            f"against either would pick one. {_coverage_text(coverage)}",
        )

    edge = covering[0]
    envelope_id = str(edge["dst_id"])
    row = store.envelope_row(conn, envelope_id)
    if row is None:  # pragma: no cover - open_edge refuses a dangling endpoint
        return _refuse(
            spec,
            layers,
            f"The HAS_ENVELOPE edge covering t={t} points at envelope "
            f"{envelope_id!r}, which is not in this artifact. "
            f"{_coverage_text(coverage)}",
        )
    if row[OUTER_BOUNDARY_COLUMN] is None:
        return _refuse(
            spec,
            layers,
            f"Envelope {envelope_id!r} is in force at t={t} and retains no "
            f"{OUTER_BOUNDARY_COLUMN}: meta[{META_GEOMETRY_RETENTION!r}] keeps "
            "the outer boundary wherever it keeps the inner polygon and nowhere "
            "else, and this is a frame that rule excludes. The row's "
            f"outer_radius={row['outer_radius']!r} m is still there and still "
            "answers *not at that distance*, about the centre "
            "reg.graph.envelope_frame reads off the row — but that is a "
            "different question, and returning its answer here would put a "
            "radial verdict in a pointwise answer's shape, where nothing "
            f"downstream could tell them apart. {_coverage_text(coverage)}",
        )

    region = store.from_wkb(row[OUTER_BOUNDARY_COLUMN])
    # The row's area was quantized before the region was placed, so the two can
    # differ by the rounding and by a rigid transform's float noise and by
    # nothing else. One quantum of the stored figure covers both — half of it is
    # the rounding — and is the builder's own tolerance rather than a new one.
    # Re-quantizing the blob and demanding equality would flag a clean file
    # whose area sits on a rounding edge. What this catches is a boundary that
    # disagrees with its row by more than the row's precision; a replacement of
    # equal area, or the right region moved, passes it.
    stored_area = float(row["outer_area"])
    quantum = 10.0 ** (
        math.floor(math.log10(stored_area)) - (AREA_QUANT_SIGFIGS - 1)
    )
    if abs(region.area - stored_area) > quantum:
        return _refuse(
            spec,
            layers,
            f"Envelope {envelope_id!r} retains a boundary that disagrees with "
            f"the row carrying it: the stored geometry has area "
            f"{region.area:.6g} m2 and the row states outer_area={stored_area} "
            f"m2, a difference larger than that figure's {quantum:g} m2 "
            "quantum. "
            "The builder writes the two from one region, so a file where they "
            "differ is one whose account of that region has stopped being "
            "self-consistent, and nothing here can say which of them is the "
            "region this build computed. Answering anyway would rest an "
            "exclusion — the strongest claim this query makes, and the one "
            "that accuses — on bytes the row itself contradicts. No digest "
            "covers the boundary: reg.envelope.envelope_hash is over the inner "
            "geometry and is not a MAC, and the chain commits to records "
            "rather than to envelope rows, so this is where the file stops "
            "agreeing with itself and not where it is shown to be wrong. "
            f"{_coverage_text(coverage)}",
        )
    # The second half of the same agreement check, and the half that catches
    # the correct region *moved* (issue #265). A translation keeps the area, so
    # everything above passes it, and every point of the region has shifted:
    # points the robot could reach fall outside and come back **excluded**,
    # which is the false accusation this answer must never make. The row's
    # `outer_radius` is the furthest point of the region from the envelope's own
    # centre, and a translation changes it.
    #
    # The centre comes from `reg.store.envelope_base_frame`, which is the one
    # reader of it in this package — `reg.graph.envelope_frame` delegates to the
    # same function. A copy here would be a second reader of the fact that
    # decides where every radius in the file is measured from.
    try:
        centre = store.envelope_base_frame(conn, envelope_id)
    except store.StoreError as exc:
        return _refuse(
            spec,
            layers,
            f"Envelope {envelope_id!r} retains a boundary, and this artifact "
            "does not say where the radius beside it is measured from, so the "
            "check that the two agree cannot be run: "
            f"{exc} The containment test itself needs no centre — the retained "
            "region is already in the room frame — but an answer given here "
            "would be one whose integrity check was skipped rather than "
            "passed, and a check that could not run must not resolve to one "
            f"that did. {_coverage_text(coverage)}",
        )
    stored_radius = float(row["outer_radius"])
    try:
        measured_radius = outer_radius(region, centre)
    except (TypeError, ValueError) as exc:
        # A geometry `reg.store.to_wkb` refuses to write: empty, or invalid.
        # It reaches here only on a file something else wrote, and only when
        # its area happens to agree with the row above. Refused rather than
        # raised, because a caller asking about a point is owed an answer or a
        # reason and a traceback is neither.
        return _refuse(
            spec,
            layers,
            f"Envelope {envelope_id!r} retains a boundary no radius can be "
            f"measured from: {exc} So the outer_radius on the row cannot be "
            "checked against it, and the containment test would be run over a "
            "region whose own extent is not well defined. "
            "reg.store.to_wkb refuses to write such a geometry, so this file "
            f"was not written by it. {_coverage_text(coverage)}",
        )
    if abs(measured_radius - stored_radius) > DISTANCE_TOL_M:
        return _refuse(
            spec,
            layers,
            f"Envelope {envelope_id!r} retains a boundary whose radius "
            "disagrees with the row carrying it: the stored geometry reaches "
            f"{measured_radius:.6g} m from the centre ({centre.x:g}, "
            f"{centre.y:g}) this artifact states, and the row states "
            f"outer_radius={stored_radius} m, a difference larger than the "
            f"{DISTANCE_TOL_M:g} m the radius is quantized to. A region of the "
            "right area in the wrong place passes the area comparison above and "
            "turns points the robot could reach into exclusions, which is the "
            "one direction this answer must not get wrong. The builder writes "
            "the radius and the boundary from one region, so a file where they "
            "differ has stopped giving one account of it, and nothing here can "
            f"say which is the region this build computed. {_coverage_text(coverage)}",
        )
    inside = bool(region.covers(Point(x, y)))
    return Answer(
        query=spec.name,
        verdict=ANSWERED,
        layer=EDGE_LAYER,
        value=ReachedPoint(
            x=x,
            y=y,
            t=t,
            could_have_reached=inside,
            envelope_id=envelope_id,
            # Off the edge, never inferred: the tag is what this artifact says
            # its own answer rests on, and this module invents no layer.
            envelope_layer=str(edge["layer"]),
            outer_area_m2=float(row["outer_area"]),
            outer_radius_m=float(row["outer_radius"]),
            coverage=coverage,
        ),
        tolerances={"time_s": TIME_TOL_S},
        reason=(
            f"({x}, {y}) is "
            + ("inside" if inside else "outside")
            + f" the outer reachable set envelope {envelope_id} retains for "
            f"t={t}, tested against the stored boundary itself. That set "
            "over-covers, so *outside* excludes soundly and *inside* is *not "
            f"excluded* rather than *reached*. {_coverage_text(coverage)}"
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


def _acknowledgment_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Every acknowledgment with the verdict it names, in chain order."""
    return list(
        conn.execute(
            """
            SELECT an.node_id AS ack_id,
                   vn.node_id AS verdict_id,
                   a.seq      AS seq,
                   a.t        AS t,
                   a.fault    AS fault,
                   a.reason   AS reason
            FROM acknowledgment a
            JOIN node an ON an.node_key = a.acknowledgment_key
            JOIN node vn ON vn.node_key = a.verdict_key
            ORDER BY a.seq, an.node_id
            """
        ).fetchall()
    )


def _acknowledged(row: sqlite3.Row, operator_id: str | None) -> Acknowledged:
    return Acknowledged(
        ack_id=str(row["ack_id"]),
        seq=int(row["seq"]),
        t=float(row["t"]),
        fault=str(row["fault"]),
        reason=str(row["reason"]),
        party=ACKNOWLEDGING_PARTY,
        operator_id=operator_id,
    )


def acknowledgments(conn: sqlite3.Connection) -> Answer:
    """Was the passivation acknowledged, and by whom (issue #247).

    **Not one of the nine.** `docs/lossiness.md`'s supported question set is
    `docs/plan.md` Phase 7's and nothing else, and this is a tenth question
    arriving after it. It is deliberately outside that set rather than quietly
    inside it: the set is what the *discard contract* is measured against, and
    `reg.bench.SUPPORTED_QUESTIONS` prices coverage over it, so a question added
    here without being priced there would widen the denominator of a published
    coverage figure by claiming an answer nobody measured the cost of. What this
    question needs is `docs/lossiness.md` *Retained* #7, which is retained at
    every level, so nothing in the discard contract has to move for it.

    **Layer A.** An acknowledgment is attestation-shaped, not perception-shaped:
    a signed record of what a party stated, whose failure modes are the chain's
    — who held the key, whether the record was truncated, whether it was
    reordered. A person is involved in one, and that is deliberately not the
    argument for its layer; the argument is in `docs/sufficiency.md` §5.10 and in
    `reg.store.EDGE_SPECS`.

    It takes no arguments, unlike `verdicts`. The question is about the run:
    *were the stops cleared, and by whom*, and a caller who had to name the
    passivating verdict first would have to have answered half of it already.

    THE THREE-VALUED PART, WHICH IS THE POINT
    -----------------------------------------
    * **ANSWERED, with an empty list** — enforcement never stopped the robot, so
      nothing needed clearing. A closed question, not an unanswerable one.
    * **ANSWERED, with every passivation carrying its acknowledgment** — the
      case the `stale_declaration` fixture ships.
    * **COULD-NOT-EVALUATE** — the run holds a passivation this artifact holds no
      acknowledgment of. That is **not** "nobody acknowledged it", and the
      distinction is the whole reason this query exists rather than a `WHERE
      acknowledgment IS NULL`. What the artifact records is what *enforcement was
      told*: an operator who inspected the cell and never told the enforcer
      leaves exactly this absence, and so does an operator who did nothing. The
      question has two halves and the second — *by whom* — has no answer here, so
      the answer is that it could not be evaluated, naming which passivation.

    A passivation is derived from the verdict stream in chain order and by the
    rule `reg.graph._OccurrenceLog` records with: a VETO or a SAFE_STATE arriving
    while enforcement is already stopped is that stop being *reported* again, not
    a new one, and the first PERMIT or CLAMP after it is the resumption. Derived
    rather than read off a column because the record carries no "this one
    passivated" flag — and cross-checked against the `safe_state_entered`
    occurrences by `tests/test_query.py`, so the two derivations of one fact in
    this repository are held against each other rather than trusted apart.
    """
    spec = QUERIES["acknowledgments"]
    refusal = _no_record_layer(conn, spec)
    if refusal is not None:
        return refusal

    operator_id = store.get_meta(conn, META_OPERATOR_ID)
    by_verdict = {
        str(row["verdict_id"]): _acknowledged(row, operator_id)
        for row in _acknowledgment_rows(conn)
    }
    matched: set[str] = set()

    found: list[Passivation] = []
    open_at: dict[str, object] | None = None
    for row in _verdict_rows(conn):
        outcome = str(row["outcome"])
        if outcome in PASSIVATING_OUTCOMES:
            if open_at is None:
                verdict_id = str(row["verdict_id"])
                open_at = {
                    "verdict_id": verdict_id,
                    "seq": int(row["seq"]),
                    "fault": str(row["fault"]) if row["fault"] is not None else "",
                    "t_start": float(row["t"]),
                    "verdicts": 1,
                }
            else:
                open_at["verdicts"] = int(open_at["verdicts"]) + 1
            continue
        if open_at is not None:
            found.append(_passivation(open_at, float(row["t"]), by_verdict, matched))
            open_at = None
    if open_at is not None:
        found.append(_passivation(open_at, None, by_verdict, matched))

    unmatched = tuple(
        ack for verdict_id, ack in by_verdict.items() if verdict_id not in matched
    )
    value = Passivations(passivations=tuple(found), unmatched=unmatched)

    if value.answered:
        return Answer(
            query=spec.name,
            verdict=ANSWERED,
            layer=ATTESTATION_LAYER,
            value=value,
            tolerances={},
            reason=(
                f"{len(found)} passivation(s), every one of them acknowledged "
                f"under the {ACKNOWLEDGING_PARTY} key, read closed-world under "
                f"meta[{META_ATTESTATION_RETENTION!r}]"
                if found
                else "enforcement stopped the robot at no point in this run, so "
                "there was no passivation to acknowledge, read closed-world "
                f"under meta[{META_ATTESTATION_RETENTION!r}]"
            ),
        )

    if value.unmatched:
        return _refuse_record(
            spec,
            f"this artifact holds {len(value.unmatched)} acknowledgment(s) "
            f"naming a verdict that opened no passivation in it — "
            f"{[a.ack_id for a in value.unmatched]}. An acknowledgment of "
            "something the verdict stream does not show being stopped is a "
            "record this walk cannot place, and placing it anyway would report "
            "a passivation nobody made.",
        )
    return _refuse_record(
        spec,
        f"{len(value.unacknowledged)} of {len(found)} passivation(s) in this run "
        f"are named by no acknowledgment — "
        f"{[p.verdict_id for p in value.unacknowledged]}. That is not 'nobody "
        "acknowledged them': this artifact records what enforcement was told, "
        "and an operator who cleared the cell without telling it leaves the same "
        "absence as one who did nothing. The question asks *and by whom*, and "
        "for these there is nobody to name.",
    )


def _passivation(
    open_at: dict[str, object],
    t_end: float | None,
    by_verdict: dict[str, Acknowledged],
    matched: set[str],
) -> Passivation:
    verdict_id = str(open_at["verdict_id"])
    ack = by_verdict.get(verdict_id)
    if ack is not None:
        matched.add(verdict_id)
    return Passivation(
        verdict_id=verdict_id,
        seq=int(open_at["seq"]),
        fault=str(open_at["fault"]),
        t_start=float(open_at["t_start"]),
        t_end=t_end,
        verdicts=int(open_at["verdicts"]),
        acknowledgment=ack,
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
# THE COLD READ (issue #231, docs/self-describing.md §2 and §8 tier 3).
#
# "Open an artifact with the code that reads artifacts and **no document**. For
# every claim the file makes, either it can be checked from the file or it
# cannot." That sentence is the acceptance criterion for the whole
# self-describing track, and it ships here rather than in `tests/` because the
# audience for it is an assessor holding a file, and a check they cannot run
# tells them nothing.
#
# FIVE STATES, AND THE LAST THREE NEVER RESOLVE TO THE FIRST.
#
#   CHECKABLE                the file carries what is needed to verify the claim
#   CHECKABLE-WITH-A-KEY-…   the file carries the record and the verification is
#                            deliberately gated on a key it does not contain
#   READABLE-NOT-CHECKABLE   the claim is present and the file does not support
#                            verifying it
#   ABSENT                   the claim is not in this file
#   COULD-NOT-EVALUATE       the file was written against a schema these states
#                            were not derived against
#
# `READABLE-NOT-CHECKABLE` is a distinct state and not a soft pass. **No
# artifact this repository builds reports it today**, and that is a fact about
# these files rather than about the state: `reached-point` was the last row that
# did, and issue #258 moved it to `CHECKABLE` when the outer boundary started
# being retained. Every row below can still reach it, and each one is a file
# that lost something an assessor would have needed — an artifact stating no
# environment, a tagged edge with no basis row under it, a frame the retention
# rule kept no outer boundary for, a record whose `mac` or `prev_hash` is blank.
# Reporting it is the point: it is what lets a gap be judged by something other
# than a PR body, and a report with no fixture reaching it is a report whose
# negative lives in `tests/test_query.py` rather than in the catalogue.
#
# THE FIFTH STATE, AND WHY IT IS ONE (ISSUE #242).
# `chain-intact` — *has this record been altered since it was written?* — is the
# claim the other rows exist to support, and none of the four above fits it.
# Not `CHECKABLE`: `reg.chain.verify_chain(conn, keyring)` needs a keyring, and
# no key is in the artifact. Not `READABLE-NOT-CHECKABLE`: it *is* checkable, by
# whoever holds the key, and calling it unverifiable would understate the file.
# Not `ABSENT`: the chain is there. Not `COULD-NOT-EVALUATE`: nothing failed to
# be established. It is the only claim here whose verification is *deliberately*
# gated — a MAC anyone could verify without a key is not worth taking — so
# flattening it into either neighbour would report the design as a defect or the
# defect as a design. The state is named for exactly that and the name is long
# on purpose: it is printed verbatim, and an assessor reading one word would
# have to be told the rest.
#
# This report **does not run the walk**. `verify_chain` is the one
# implementation of it, and a second here would be free to disagree with the one
# under test — the same rule the environment row is held to.
#
# WHY THIS DOES NOT IMPORT `reg.graph`, AND WHAT HOLDS IT TO IT INSTEAD.
# `reg.graph.recorded_environment` and `reg.graph.RECOMPUTE_ENVIRONMENT_KEYS`
# are the one implementation of issue #201's comparison, and the module header
# above forbids reaching them: importing the writer — at module level or inside
# a function — puts `reg.stream` one attribute away from every scene query, and
# `tests/test_query.py::test_reg_query_imports_no_stream_or_layer_b_module`
# walks the whole AST rather than the top level, so a deferred import would not
# get past it either. The discipline this repository uses instead is already
# here: `reg.query` **names its own copy** of what it needs from the builder and
# a test asserts the two spellings are one contract
# (`test_the_meta_keys_this_module_reads_are_the_ones_the_builder_writes`).
# `COLD_READ_RECOMPUTE_KEYS` and `COLD_READ_RECORDED_ONLY_KEYS` are that copy —
# both halves of the split, because a report that named only the compared keys
# would leave an assessor to work out the rest by subtraction — held equal to
# `reg.graph.RECOMPUTE_ENVIRONMENT_KEYS` and
# `reg.graph.RECORDED_ONLY_ENVIRONMENT_KEYS` by a test, and the report's
# `recompute_permitted` is held to agree with `reg.graph.envelope_at` on both
# sides — matching environment and mismatched — by another. A disagreement is a
# bug in this report and it fails there rather than in an assessor's hands.
#
# WHAT IS PINNED TO SCHEMA 14, AND WHY THE WHOLE FILE IS.
# Every state below is a property of a particular set of columns and `meta`
# keys. Against another set they would be states about columns this reader
# cannot place, so an artifact stating any other `schema_version` is a
# could-not-evaluate — in both directions and for every claim. Older is issue
# #200's case: the six `env_*` keys arrived at schema 11, so a file older than
# that carries no environment, and that is a fact about a schema rather than an
# absence somebody chose. Newer is the deliberate-update case: a newer schema is
# where a gap gets closed, and a report that went on calling a closed gap
# "readable, not checkable" would be exactly the trusted-because-nobody-rechecked
# sentence this whole track exists to remove.
# `tests/test_query.py::test_the_cold_read_is_pinned_to_this_build_s_schema` is
# what makes that update deliberate: it fails the moment `store.SCHEMA_VERSION`
# moves, and closing #227 or #228 moves it.
#
# Schema 12 is the worked example of a bump that moves the constant and **no
# state** (issue #247). It added the `acknowledgment` table, the `ACKNOWLEDGED`
# edge and `meta[acknowledgment_count]`; none of the four claims below is a
# property of any of them, so each was re-derived against the new columns and
# each came back where it was. Re-deriving and finding nothing moved is the
# work this gate asks for — the failure it exists to prevent is the constant
# moving *without* that pass, not the constant moving.
#
# Schema 13 is the other kind, and the one this gate was built for (issue #252).
# `edge_layer_basis` arrived, so `layer-tag-basis` moved from
# `READABLE-NOT-CHECKABLE` to `CHECKABLE` — the first of the four rows to move
# since the report shipped, and it moved because a gap closed rather than
# because a row was relabelled. The other three were re-derived against the new
# table and came back where they were: the basis is not an environment, it is
# not a polygon, and it is not a reachable-set boundary.
#
# Schema 14 is the second of that kind (issues #257 and #258). The outer
# reachable set's boundary arrived as `envelope.outer_wkb`, retained wherever
# `reg.graph.GEOMETRY_RETENTION` already keeps the inner polygon — so
# `reached-point` moved from `READABLE-NOT-CHECKABLE` to `CHECKABLE` on a file
# that retains one, and the row now reports *radially only* for a file that
# retains none rather than for every file. That was the last row of the seven
# reporting `READABLE-NOT-CHECKABLE` on a shipped fixture. The others were
# re-derived against the new column and came back where they were: a boundary
# is not an environment, it is not a basis, and it is not a record chain.
# --------------------------------------------------------------------------

#: The file carries what is needed to verify the claim.
CHECKABLE = "CHECKABLE"

#: The file carries the record and the check on it is gated on a key the file
#: does not contain (issue #242). **Not a weaker `CHECKABLE` and not a stronger
#: `READABLE_NOT_CHECKABLE`**: the verification exists, it succeeds or fails,
#: and what it needs is a keyring rather than another column. The gate is the
#: design — a MAC verifiable with nothing but the file it sits in attests to
#: nobody — so a report that flattened this into either neighbour would describe
#: the design as a defect or the defect as a design. The string is a sentence
#: because it is printed verbatim.
CHECKABLE_WITH_A_KEY = "CHECKABLE-WITH-A-KEY-THE-FILE-DOES-NOT-CONTAIN"

#: The claim is present in the file and the file does not support verifying it.
#: **Not a soft pass**, and it must never be reported as one: a record whose MAC
#: is blank is readable and unverifiable by anyone, key or no key, and an
#: assessor who read that as a pass would be trusting exactly the assertion
#: docs/self-describing.md §2 is about.
READABLE_NOT_CHECKABLE = "READABLE-NOT-CHECKABLE"

#: The claim is not in this file. Distinct from the three above and from
#: `COULD_NOT_EVALUATE`: an artifact that never made a claim has not failed to
#: support one, and a file that predates the schema carrying it has not chosen
#: to leave it out.
ABSENT = "ABSENT"

#: The five states, in decreasing order of what the file supports. Spelled once
#: here so a caller can check a state it was handed is one this module produces;
#: `COULD_NOT_EVALUATE` is the module's existing third verdict rather than a
#: sixth string with the same meaning.
COLD_READ_STATES = (
    CHECKABLE,
    CHECKABLE_WITH_A_KEY,
    READABLE_NOT_CHECKABLE,
    ABSENT,
    COULD_NOT_EVALUATE,
)

#: The `schema_version` the states above were derived against. See the section
#: header: an artifact stating anything else is a could-not-evaluate in both
#: directions, and this constant moving is a decision about every claim below
#: rather than a version bump.
COLD_READ_SCHEMA_VERSION = 14

CLAIM_ENVIRONMENT = "recording-environment"
CLAIM_RECOMPUTE = "recompute-discarded-polygon"
CLAIM_LAYER_BASIS = "layer-tag-basis"
CLAIM_REACHED_POINT = "reached-point"
CLAIM_CHAIN_INTACT = "chain-intact"
CLAIM_ACKNOWLEDGMENT = "passivation-acknowledged"
CLAIM_DISCLOSURES = "disclosures-stated"

#: The claims an artifact makes about itself, in the order the report lists
#: them. One row each, and the set is closed: a claim nobody put here is a claim
#: the cold read is silent about, which is why adding one is how this report
#: grows rather than widening an existing row's meaning.
#:
#: The last two are docs/plan.md **Claim 4**'s, added by issue #242, and they
#: are the reason the other four are worth reading: an assessor arrives asking
#: whether the record was altered, and a report that covered everything except
#: that would answer around the question. They are two rows rather than one
#: because the two halves of Claim 4 land in different states — the first is
#: gated on a key and the second is not.
#:
#: The seventh is about the artifact rather than about the run (issue #262). It
#: is a **claim and not a state**: the file states what the deployer said about
#: the obligations `docs/limitations.md` §8 names, and the row reads it back in
#: the five states that already exist rather than earning a sixth. A state is a
#: relationship between a claim and a pass; this is one more claim, and giving
#: it a state of its own would route around the refusal in `ColdReadClaim` that
#: makes adding one a deliberate act.
COLD_READ_CLAIMS = (
    CLAIM_ENVIRONMENT,
    CLAIM_RECOMPUTE,
    CLAIM_LAYER_BASIS,
    CLAIM_REACHED_POINT,
    CLAIM_CHAIN_INTACT,
    CLAIM_ACKNOWLEDGMENT,
    CLAIM_DISCLOSURES,
)

#: What each claim asks, in the words an assessor would ask it in. Carried
#: beside the state because a claim id is a key and not a question.
COLD_READ_QUESTIONS: Mapping[str, str] = {
    CLAIM_ENVIRONMENT: "what environment was this artifact's geometry computed in?",
    CLAIM_RECOMPUTE: "can a discarded polygon be recomputed and the result trusted?",
    CLAIM_LAYER_BASIS: "what was this edge's layer tag computed from?",
    CLAIM_REACHED_POINT: "could the robot have reached (x, y)?",
    CLAIM_CHAIN_INTACT: "has this record been altered since it was written?",
    CLAIM_ACKNOWLEDGMENT: "was the passivation acknowledged, and by whom?",
    CLAIM_DISCLOSURES: (
        "what does this artifact state about the obligations its existence "
        "creates?"
    ),
}

#: This module's copy of `reg.chain.CHAINS` — the party each record chain is
#: signed by, the table its records live in, and the `meta` key stating how many
#: it should hold. Copied rather than imported for the reason the recompute keys
#: below are: `reg.chain` reaches `reg.stream`, so this module may only name it
#: inside `verify_chain`, and a cold read that imported it would put the stream
#: one attribute away from every claim in this report.
#: `tests/test_query.py::test_the_cold_read_names_the_record_chains_reg_chain_
#: walks` holds the two lists equal, which is what the copy is paid for with.
#:
#: One entry per (party, table) and not per chain: enforcement signs verdicts
#: and acknowledgments into **one** chain over two tables (issue #247), and a
#: report that counted only the first would say a file held no acknowledgment
#: chain when what it holds is one chain with acknowledgments in it.
COLD_READ_RECORD_CHAINS: tuple[tuple[str, str, str], ...] = (
    ("policy", "declaration", META_DECLARATION_COUNT),
    ("enforcement", "verdict", META_VERDICT_COUNT),
    ("enforcement", "acknowledgment", META_ACKNOWLEDGMENT_COUNT),
)

#: This module's copy of `reg.graph.RECOMPUTE_ENVIRONMENT_KEYS` — the five keys
#: of the six recorded that `reg.graph.envelope_at` refuses a recomputation on.
#: Named from `reg.store`'s constants, so the *spellings* are one definition;
#: what is copied is the choice of subset, and
#: `tests/test_query.py::test_the_cold_read_names_the_same_recompute_keys_the_
#: builder_refuses_on` holds the two lists equal. Copied rather than imported
#: for the reason in the section header, and the copy is not free: it is paid
#: for with that test.
COLD_READ_RECOMPUTE_KEYS = (
    store.META_ENV_PLATFORM_SYSTEM,
    store.META_ENV_PLATFORM_MACHINE,
    store.META_ENV_SHAPELY,
    store.META_ENV_GEOS,
    store.META_ENV_NUMPY,
)

#: This module's copy of `reg.graph.RECORDED_ONLY_ENVIRONMENT_KEYS` — the
#: recorded keys that do *not* make `reg.graph.envelope_at` refuse. Copied for
#: the same reason and paid for by the same test as the tuple above, and it is
#: here rather than spelled into a sentence because the report has to name this
#: set: "the compared keys agree" is a pass whose reach an assessor cannot see
#: without being told which recorded keys were left out of it. A prose word
#: would go stale the next time the split moves, which is exactly what issue
#: #241 found had happened.
COLD_READ_RECORDED_ONLY_KEYS = (store.META_ENV_PYTHON,)


@dataclass(frozen=True)
class ColdReadClaim:
    """One claim the artifact makes about itself, and what the file supports.

    `detail` is never empty and never a restatement of `state`: it names what
    was read — which keys, which columns, how many rows — because a state with
    no basis under it is the same trusted assertion the cold read exists to
    find.
    """

    claim: str
    question: str
    state: str
    detail: str

    def __post_init__(self) -> None:
        if self.claim not in COLD_READ_CLAIMS:
            raise QueryError(
                f"{self.claim!r} is not one of the claims this report covers "
                f"({', '.join(COLD_READ_CLAIMS)}). A row nobody declared would "
                "be a claim the report is silent about while appearing to cover."
            )
        if self.state not in COLD_READ_STATES:
            raise QueryError(
                f"{self.claim} was given state {self.state!r}, which is not one "
                f"of {', '.join(COLD_READ_STATES)}. A sixth state is a state "
                "nobody defined the relationship of to a pass. The fifth was "
                "added deliberately, by issue #242, because tamper-evidence is "
                "checkable with a key the file does not contain and none of the "
                "four before it could say that."
            )
        if not self.detail.strip():
            raise QueryError(
                f"{self.claim} was given no detail. A state with nothing under "
                "it is an assertion, which is the thing being measured."
            )

    @property
    def checkable(self) -> bool:
        """Exactly `CHECKABLE` — *from the file, by this reader, now*. The other
        four are not degrees of it, and `CHECKABLE_WITH_A_KEY` least of all: it
        is `False` here because the file alone does not settle the claim, which
        is a different sentence from *this claim cannot be settled*. The row's
        own `state` is where that difference is read."""
        return self.state == CHECKABLE

    @property
    def message(self) -> str:
        """The claim, the state and why — the line a failure quotes."""
        return f"{self.claim} [{self.state}] {self.question} — {self.detail}"


@dataclass(frozen=True)
class ColdRead:
    """What an artifact says about itself, read with no document open.

    `recompute_permitted` is the one field here that is about **the reader** and
    not about the file, and it is separated deliberately. A `state` says what
    the artifact carries and does not move when it is read on another machine; a
    recomputation is refused or allowed by where it is being asked from, and
    issue #201 made that a property of the running interpreter. Three values,
    the same three `reg.graph.envelope_at` has:

    * `True` — the compared keys agree, and a discarded polygon recomputes;
    * `False` — one or more differ, and it is refused with the key named;
    * `None` — nothing was compared, and it is refused *differently*. An
      artifact that states no environment is in this state, and so is a reader
      that cannot say what environment it is running in.

    `None` is not a weaker `False`: the first is a fact about the file, the
    second about two machines, and collapsing them would report "built somewhere
    else" for a file that never said where it was built.
    """

    #: What the artifact states as its `schema_version`, verbatim, or `None`
    #: where it states none. Raw text rather than an int: a value this reader
    #: cannot parse is a thing to report, not to normalise away.
    schema_version: str | None
    claims: tuple[ColdReadClaim, ...]
    recompute_permitted: bool | None

    def __post_init__(self) -> None:
        found = tuple(claim.claim for claim in self.claims)
        if found != COLD_READ_CLAIMS:
            raise QueryError(
                f"a cold read covers {COLD_READ_CLAIMS} in that order and this "
                f"one carries {found}. A missing row and a row reporting ABSENT "
                "are different facts, and a report that could omit one would "
                "make them look the same."
            )

    def __getitem__(self, claim: str) -> ColdReadClaim:
        for row in self.claims:
            if row.claim == claim:
                return row
        raise QueryError(
            f"this report carries no claim {claim!r}. It covers "
            f"{', '.join(COLD_READ_CLAIMS)}."
        )

    def state(self, claim: str) -> str:
        """The state of one claim, by id. Raises rather than returning a
        default: an unknown claim reported as `ABSENT` would read as a finding
        about the artifact."""
        return self[claim].state

    @property
    def checkable(self) -> tuple[str, ...]:
        return tuple(row.claim for row in self.claims if row.checkable)

    @property
    def not_checkable(self) -> tuple[str, ...]:
        """Every claim the file does not support checking, in report order.

        The four states this collects are not one state. They are kept apart
        in `claims` and gathered here only for a caller asking the cold read's
        own question — *is there anything in this file that cannot be checked
        from it* — whose answer is the empty tuple or a list of names.
        `chain-intact` is in here on an artifact holding records, and that is
        the question being answered literally: it is not checkable *from the
        file*, it is checkable from the file and a key. A caller who wants the
        distinction reads the row's `state`, which is why the state string says
        so in full.
        """
        return tuple(row.claim for row in self.claims if not row.checkable)


def _schema_version_text(conn: sqlite3.Connection) -> str | None:
    """The artifact's stated `schema_version`, or `None` if it states none.

    Read through `store.get_meta` rather than `_meta`, because a file with no
    version is something this report says rather than refuses over: the cold
    read is the one function here whose subject is the file's own claims, and
    "it does not say which schema it was written against" is one of them.
    """
    return store.get_meta(conn, store.META_SCHEMA_VERSION)


def _unpinned_claims(stated: str | None) -> tuple[ColdReadClaim, ...]:
    """Every claim as `COULD-NOT-EVALUATE`, with the direction named.

    Three shapes of file reach this: one stating no version, one stating a
    version older than the states were derived against, and one stating a newer.
    All three are could-not-evaluate and none of them resolves to any of the
    other states — an unreadable schema is not an absence, and a newer schema is
    where a gap gets closed rather than a file that failed to carry one.
    """
    if stated is None:
        why = (
            f"this artifact states no meta[{store.META_SCHEMA_VERSION!r}], so it "
            "does not say which schema it was written against and this reader "
            "cannot place any column or key in it."
        )
    else:
        try:
            version = int(stated)
        except (TypeError, ValueError):
            version = None
        if version is None:
            why = (
                f"this artifact states schema_version={stated!r}, which is not a "
                "version number this reader can place against the schema the "
                "states below were derived against "
                f"({COLD_READ_SCHEMA_VERSION})."
            )
        elif version < COLD_READ_SCHEMA_VERSION:
            why = (
                f"this artifact states schema_version={version} and these states "
                f"were derived against {COLD_READ_SCHEMA_VERSION}. The six env_* "
                "keys arrived at schema 11 (issue #200), so a file older than "
                "that carries no environment — which is a fact about a schema "
                "and not an absence somebody chose, and it must not be reported "
                "as one."
            )
        else:
            why = (
                f"this artifact states schema_version={version} and these states "
                f"were derived against {COLD_READ_SCHEMA_VERSION}. A newer "
                "schema is where a gap gets closed, so a claim this reader would "
                "still call readable-not-checkable may have become checkable. "
                "Re-derive each state against the new columns and move "
                "reg.query.COLD_READ_SCHEMA_VERSION deliberately."
            )
    return tuple(
        ColdReadClaim(
            claim=claim,
            question=COLD_READ_QUESTIONS[claim],
            state=COULD_NOT_EVALUATE,
            detail=why,
        )
        for claim in COLD_READ_CLAIMS
    )


def _environment_claim(stated: Mapping[str, str]) -> ColdReadClaim:
    """Does the file state the environment its geometry was computed in?

    The same three conditions `reg.graph.recorded_environment` refuses on —
    missing keys, a partial block, an empty value — and the same reading of
    them: an environment is the six keys or it is nothing, because a block with
    a key missing or blank compares unequal to every recomputing environment and
    would read as a mismatch, which is a *finding* about a file that never said.
    All of that is `ABSENT` here; the schema case never reaches this function.
    """
    missing = [key for key in store.ENVIRONMENT_KEYS if key not in stated]
    empty = [
        key
        for key in store.ENVIRONMENT_KEYS
        if key in stated and not stated[key].strip()
    ]
    if not missing and not empty:
        recorded = ", ".join(f"{key}={stated[key]}" for key in store.ENVIRONMENT_KEYS)
        return ColdReadClaim(
            claim=CLAIM_ENVIRONMENT,
            question=COLD_READ_QUESTIONS[CLAIM_ENVIRONMENT],
            state=CHECKABLE,
            detail=(
                f"all {len(store.ENVIRONMENT_KEYS)} env_* keys are stated and "
                f"non-empty: {recorded}. A reader compares them against its own "
                "interpreter with no document open. The C library is not among "
                "them, so two files agreeing on all six may still have been "
                "linked against different libms — matching is necessary for a "
                "bit-identical recomputation and is not sufficient."
            ),
        )
    faults = []
    if missing:
        faults.append(f"{len(missing)} key(s) not stated at all: {', '.join(missing)}")
    if empty:
        faults.append(f"{len(empty)} key(s) stated as empty text: {', '.join(empty)}")
    return ColdReadClaim(
        claim=CLAIM_ENVIRONMENT,
        question=COLD_READ_QUESTIONS[CLAIM_ENVIRONMENT],
        state=ABSENT,
        detail=(
            f"this file does not state an environment — {'; '.join(faults)}. An "
            "environment is all six keys or it is none: a partial or blank block "
            "compares unequal to every recomputing interpreter, so reading it as "
            "an environment would turn a file that never said into a machine "
            "mismatch. The file states the schema these keys arrived in (issue "
            "#200) and does not carry them, which is why this is ABSENT and not "
            "a could-not-evaluate."
        ),
    )


def _running_environment() -> tuple[Mapping[str, str] | None, str]:
    """What this interpreter would recompute in, or why it cannot say.

    A reader that cannot state its own environment has not found a mismatch —
    that is the `None` arm of `recompute_permitted`, and it is why the failure
    is caught here rather than allowed to surface as a `StoreError` from a
    function whose subject is the file.
    """
    try:
        return store.build_environment(), ""
    except store.StoreError as exc:
        return None, str(exc)


def _recompute_claim(
    stated: Mapping[str, str],
    environment: ColdReadClaim,
    discarded: int,
    total: int,
) -> tuple[ColdReadClaim, bool | None]:
    """Can a discarded polygon be recomputed, and would it be permitted here?

    The state is about the file and `recompute_permitted` is about the reader,
    and the two are computed together because they are read off the same keys.
    A file with no environment leaves the claim **readable, not checkable**
    rather than absent: the file does make the claim — it discarded polygons
    under its own retention rule and says so in the row — and what it does not
    carry is what would let a reader check the recomputation.
    """
    retention = f"{discarded} of {total} envelope row(s) store no geometry"
    if not environment.checkable:
        return (
            ColdReadClaim(
                claim=CLAIM_RECOMPUTE,
                question=COLD_READ_QUESTIONS[CLAIM_RECOMPUTE],
                state=READABLE_NOT_CHECKABLE,
                detail=(
                    f"{retention}, so the file claims those polygons are a "
                    "deterministic function of the row and four numbers in "
                    "meta — and it states no environment to reproduce them in. "
                    "Issue #175 measured that the function is the platform's, "
                    "so a recomputation that disagreed here would be *the "
                    "geometry moved* and *this is a different machine* at once. "
                    "reg.graph.envelope_at refuses on every machine, including "
                    "the one that wrote the file, and the refusal is a "
                    "could-not-evaluate about the file rather than a mismatch."
                ),
            ),
            None,
        )
    running, why_not = _running_environment()
    if running is None:
        return (
            ColdReadClaim(
                claim=CLAIM_RECOMPUTE,
                question=COLD_READ_QUESTIONS[CLAIM_RECOMPUTE],
                state=CHECKABLE,
                detail=(
                    f"{retention}, and the file names the environment that "
                    "would reproduce them, which is what makes the claim "
                    "checkable. Whether a recomputation is permitted *here* "
                    "could not be decided: this interpreter cannot say what it "
                    f"would recompute in — {why_not} That is a "
                    "could-not-evaluate about the reader and not a finding "
                    "about the file, so the state above is unchanged."
                ),
            ),
            None,
        )
    differences = tuple(
        (key, stated[key], running[key])
        for key in COLD_READ_RECOMPUTE_KEYS
        if stated[key] != running[key]
    )
    if differences:
        named = "; ".join(
            f"{key}: file {recorded!r}, here {actual!r}"
            for key, recorded, actual in differences
        )
        return (
            ColdReadClaim(
                claim=CLAIM_RECOMPUTE,
                question=COLD_READ_QUESTIONS[CLAIM_RECOMPUTE],
                state=CHECKABLE,
                detail=(
                    f"{retention}, and the file names the environment that "
                    "would reproduce them, which is what makes the claim "
                    "checkable and is a property of the file rather than of "
                    "this machine. Checked here, a recomputation would be "
                    f"refused: {named}. Naming which key differs is not naming "
                    "which difference would move the geometry — a version list "
                    "is not a differ — and no geometry has been compared."
                ),
            ),
            False,
        )
    return (
        ColdReadClaim(
            claim=CLAIM_RECOMPUTE,
            question=COLD_READ_QUESTIONS[CLAIM_RECOMPUTE],
            state=CHECKABLE,
            detail=(
                f"{retention}, and the file names the environment that would "
                "reproduce them. Checked here, all "
                f"{len(COLD_READ_RECOMPUTE_KEYS)} compared keys agree "
                f"({', '.join(COLD_READ_RECOMPUTE_KEYS)}), so a recomputation "
                "is permitted on this interpreter. That is a pass on this check "
                "and not a guarantee of bit-identity: the C library is not "
                "among the recorded keys, and of the recorded ones "
                f"{', '.join(COLD_READ_RECORDED_ONLY_KEYS)} is recorded and not "
                "compared."
            ),
        ),
        True,
    )


def _layer_basis_claim(conn: sqlite3.Connection) -> ColdReadClaim:
    """Can a `layer` tag be checked against what it was computed from?

    Since schema 13, yes — and this row is the one place in the report that
    reports the *result* of running the check rather than only the file's
    ability to support it (issue #252, docs/limitations.md §12 gap 1). Every
    tagged edge carries a basis in `edge_layer_basis`: one row per input, each
    naming what that input said and the layer it alone admits. The tag is the
    weakest of them, `reg.store.layer_from_basis` is that arithmetic, and this
    function runs it over the whole file with no document open.

    Three states and the last never resolves to the first:

    * every tagged edge has a basis and every tag equals it — **CHECKABLE**,
      with the count checked and the inputs it was checked over.
    * some tagged edge has no basis row — **READABLE-NOT-CHECKABLE**, which is
      what a file written before schema 13 would be if it could reach here at
      all, and what a file this reader cannot vouch for looks like.
    * a tag and its basis disagree — **COULD-NOT-EVALUATE**. The file states
      two answers to one question and does not settle which is its own, so
      *what was this tag computed from* has no answer here. It must not be
      reported as a pass, and it must not be reported as a missing basis
      either: a basis that is present and contradicted is a finding.
    """
    counts = conn.execute(
        "SELECT layer, count(*) AS n FROM edge GROUP BY layer ORDER BY layer"
    ).fetchall()
    tagged = sum(int(row["n"]) for row in counts)
    if not tagged:
        return ColdReadClaim(
            claim=CLAIM_LAYER_BASIS,
            question=COLD_READ_QUESTIONS[CLAIM_LAYER_BASIS],
            state=ABSENT,
            detail=(
                "no edge in this file carries a layer tag, so the file makes no "
                "claim about one. This is not the same as a file whose tags "
                "cannot be checked."
            ),
        )
    breakdown = ", ".join(f"{row['layer']}={row['n']}" for row in counts)

    unbacked = int(
        conn.execute(
            f"SELECT count(*) AS n FROM edge e WHERE NOT EXISTS ("  # noqa: S608
            f"SELECT 1 FROM {store.EDGE_BASIS_TABLE} b WHERE b.edge_id = e.edge_id)"
        ).fetchone()["n"]
    )
    if unbacked:
        return ColdReadClaim(
            claim=CLAIM_LAYER_BASIS,
            question=COLD_READ_QUESTIONS[CLAIM_LAYER_BASIS],
            state=READABLE_NOT_CHECKABLE,
            detail=(
                f"{tagged} edge(s) carry a layer tag ({breakdown}) and every one "
                f"of them is readable, but {unbacked} of them has no row in "
                f"{store.EDGE_BASIS_TABLE} — so for those the file says what the "
                "tag is and not what it was computed from. A tag with no basis "
                "under it is an assertion, and a reader who trusts it is "
                "trusting exactly what this row exists to measure."
            ),
        )

    inputs_seen: set[str] = set()
    disagreements: list[str] = []
    for edge_id, layer in conn.execute(
        "SELECT edge_id, layer FROM edge ORDER BY edge_id"
    ).fetchall():
        basis = store.edge_basis(conn, int(edge_id))
        inputs_seen.update(item.name for item in basis)
        derived = store.layer_from_basis(basis)
        if derived != str(layer):
            disagreements.append(
                f"edge {int(edge_id)} is tagged {str(layer)!r} and its basis "
                + "("
                + "; ".join(f"{i.name}={i.value}->{i.layer}" for i in basis)
                + f") admits {derived!r}"
            )
    named = ", ".join(sorted(inputs_seen))
    if disagreements:
        shown = "; ".join(disagreements[:3])
        more = (
            f" and {len(disagreements) - 3} more" if len(disagreements) > 3 else ""
        )
        return ColdReadClaim(
            claim=CLAIM_LAYER_BASIS,
            question=COLD_READ_QUESTIONS[CLAIM_LAYER_BASIS],
            state=COULD_NOT_EVALUATE,
            detail=(
                f"{tagged} edge(s) carry a layer tag ({breakdown}) and each one "
                f"carries a basis over {named}, so the check could be run — and "
                f"it says no on {len(disagreements)} of them: {shown}{more}. The "
                "file states two answers to what this tag was computed from and "
                "settles neither, which is a could-not-evaluate about the tag "
                "and never a pass. Nothing this repository writes can produce "
                "it: reg.store.open_edge refuses such an edge rather than "
                "storing it."
            ),
        )
    return ColdReadClaim(
        claim=CLAIM_LAYER_BASIS,
        question=COLD_READ_QUESTIONS[CLAIM_LAYER_BASIS],
        state=CHECKABLE,
        detail=(
            f"{tagged} edge(s) carry a layer tag ({breakdown}) and every one of "
            f"them carries its basis in {store.EDGE_BASIS_TABLE} — one row per "
            f"input, over {named}, each naming what that input said in this "
            "build and the layer it alone admits. Checked here, all "
            f"{tagged} tags equal the weakest of their own inputs, so a reader "
            "holding this file checks the tag instead of trusting it (issue "
            "#252). That is a pass on this check and not a claim that the inputs "
            "are the right ones: which inputs decide a tag is a decision "
            "recorded in reg.envelope and reg.store, and this file states the "
            "ones that build derived."
        ),
    )


def _reached_point_claim(
    conn: sqlite3.Connection, radial: int, total: int, stored: int
) -> ColdReadClaim:
    """Can the file answer *could the robot have reached (x, y)?*

    **CHECKABLE at schema 14 since issue #258, and the row moved because a
    check arrived rather than because the file changed.** #257 put the outer
    boundary in the artifact wherever the inner polygon is — the two ends of the
    run, every `INTERSECTS` or `CONTACT` transition, every posed frame — which
    made the region *readable*. What was missing was a query that took a point
    and tested it against one, so an assessor's only route was to read the WKB
    and run their own containment. `reached_point` is that query, and this row
    **runs it**, twice, for `_acknowledgment_claim`'s reason: a state asserted
    about a check nobody invoked is the same assertion this whole report exists
    to replace.

    Twice, and in opposite directions, because *it answered* is not the property
    worth reporting. The two points come out of the retained region itself and
    neither is invented: `representative_point()` is inside it by construction,
    and the region's bounding box translated by its own width and height is
    outside it by construction. A file whose check says *not excluded* to the
    first and *excluded* to the second has been shown able to say both things;
    one that agrees with itself on both has a containment test that cannot fail,
    and that is a could-not-evaluate rather than a pass.

    Four states, and the last three never resolve to the first:

    * no row carries an `outer_radius` — **ABSENT**. The file states no
      reachable-set bound at all, radial or pointwise.
    * rows carry a radius and none carries a boundary — **READABLE-NOT-
      CHECKABLE**. That is every artifact this project built before schema 14,
      and it is the state this row spent its whole life in: the radius is
      readable and answers *not at that distance*, and no region in the file
      answers *not at that point*.
    * the boundary is there and the check says both things — **CHECKABLE**.
    * the boundary is there and the check refuses, or agrees with itself in both
      directions — **COULD-NOT-EVALUATE**, carrying what the query said.

    docs/limitations.md §2 and §3, issues #228, #257 and #258.
    """
    if not radial:
        return ColdReadClaim(
            claim=CLAIM_REACHED_POINT,
            question=COLD_READ_QUESTIONS[CLAIM_REACHED_POINT],
            state=ABSENT,
            detail=(
                f"none of this file's {total} envelope row(s) carries an "
                "outer_radius, so the file states no reachable-set bound at all "
                "— not one that answers the question radially and not one that "
                "answers it pointwise."
            ),
        )
    frame = store.get_meta(conn, store.META_BASE_FRAME)
    about = (
        f"meta[{store.META_BASE_FRAME}]={frame}"
        if frame is not None
        else f"a base frame this file does not state in meta[{store.META_BASE_FRAME}]"
    )
    preamble = (
        f"{radial} of {total} envelope row(s) carry outer_radius — a scalar "
        f"about {about} — and {stored} of them also carry "
        f"{OUTER_BOUNDARY_COLUMN}, the boundary that scalar projects, retained "
        f"wherever the inner polygon is, on the rule "
        f"meta[{META_GEOMETRY_RETENTION!r}] states in this file's own words. "
    )
    if not stored:
        return ColdReadClaim(
            claim=CLAIM_REACHED_POINT,
            question=COLD_READ_QUESTIONS[CLAIM_REACHED_POINT],
            state=READABLE_NOT_CHECKABLE,
            detail=(
                preamble + "So the question is answerable **radially only**: "
                "this file says *not at that distance* and holds no region to "
                "say *not at that point*, and the region that would answer it "
                "is recomputable, which routes the question straight back "
                "through the recompute claim above (issue #228)."
            ),
        )

    probe = conn.execute(
        "SELECT e.t_start AS t, n.node_id AS envelope_id, "
        f"       v.{OUTER_BOUNDARY_COLUMN} AS boundary "  # noqa: S608
        "FROM edge e "
        "JOIN node n ON n.node_key = e.dst_key "
        "JOIN envelope v ON v.envelope_key = e.dst_key "
        f"WHERE e.type = 'HAS_ENVELOPE' AND v.{OUTER_BOUNDARY_COLUMN} IS NOT NULL "  # noqa: S608
        "ORDER BY e.t_start, e.edge_id LIMIT 1"
    ).fetchone()
    if probe is None:
        return ColdReadClaim(
            claim=CLAIM_REACHED_POINT,
            question=COLD_READ_QUESTIONS[CLAIM_REACHED_POINT],
            state=COULD_NOT_EVALUATE,
            detail=(
                preamble + f"But no HAS_ENVELOPE edge in this file points at a "
                f"row carrying one, so there is no instant at which the check "
                "could be put to the region — the boundaries are in the file "
                "and nothing says when any of them was in force."
            ),
        )

    region = store.from_wkb(probe["boundary"])
    minx, miny, maxx, maxy = region.bounds
    inside = region.representative_point()
    at = float(probe["t"])
    yes = reached_point(conn, inside.x, inside.y, at)
    no = reached_point(
        conn, maxx + (maxx - minx), maxy + (maxy - miny), at
    )
    refused = [answer for answer in (yes, no) if answer.verdict != ANSWERED]
    if refused:
        return ColdReadClaim(
            claim=CLAIM_REACHED_POINT,
            question=COLD_READ_QUESTIONS[CLAIM_REACHED_POINT],
            state=COULD_NOT_EVALUATE,
            detail=(
                preamble + "reg.query.reached_point refuses at t="
                f"{at}, where {str(probe['envelope_id'])!r} is in force and "
                f"retains a boundary: {refused[0].reason}"
            ),
        )
    if not (yes.value.could_have_reached and not no.value.could_have_reached):
        return ColdReadClaim(
            claim=CLAIM_REACHED_POINT,
            question=COLD_READ_QUESTIONS[CLAIM_REACHED_POINT],
            state=COULD_NOT_EVALUATE,
            detail=(
                preamble + "reg.query.reached_point answers at t="
                f"{at} and gives the same verdict to a point inside the "
                "retained region and to one outside its bounding box "
                f"({yes.value.could_have_reached} and "
                f"{no.value.could_have_reached}). A containment test that has "
                "not been seen to say both things is not a check, and reporting "
                "it as one would credit this file with an answer nothing has "
                "shown can fail."
            ),
        )
    cover = yes.value.coverage
    return ColdReadClaim(
        claim=CLAIM_REACHED_POINT,
        question=COLD_READ_QUESTIONS[CLAIM_REACHED_POINT],
        state=CHECKABLE,
        detail=(
            preamble + "So reg.query.reached_point answers it from the region "
            f"at those rows, and it was run here to say so: at t={at}, with "
            f"envelope {str(probe['envelope_id'])!r} in force, a point inside "
            "the retained boundary comes back *not excluded* and one outside it "
            "comes back *excluded* — the check said both things, with no "
            f"document open and no keyring. Coverage travels on the answer: "
            f"{cover.pointwise_rows} of this run's {cover.frames} frame(s) are "
            f"pointwise-answerable and the other {radial - stored} envelope "
            "row(s) answer **radially only**, where the file says *not at that "
            "distance*, cannot say *not at that point*, and refuses rather than "
            "substituting the radius. The region that would answer those is "
            "recomputable, which routes that remainder back through the "
            "recompute claim above (issues #228, #257, #258)."
        ),
    )


def _chain_intact_claim(
    conn: sqlite3.Connection, stated: Mapping[str, str]
) -> ColdReadClaim:
    """Has this record been altered since it was written (issue #242)?

    **This does not walk the chain.** `reg.chain.verify_chain(conn, keyring)` is
    the one implementation of that walk and this report does not have a keyring
    to run it with; a second walk here would be a second definition of the
    preimage every MAC in the record is taken over, free to disagree with the
    one under test. What this reads is what the *file* carries towards the
    question: how many records are in each chain, whether every one of them
    carries the `prev_hash` that links it to its predecessor and the `mac` its
    party signed it with, and what the artifact states those counts should be.

    Three states, and the middle one is the fifth state this report gained:

    * no record in any of `COLD_READ_RECORD_CHAINS` — **ABSENT**. There is no
      chain in this file to have been altered, which is not the same fact as a
      chain nobody can check. A build handed no record stream does not carry the
      tables at all (`reg.store.create(record_tables=False)`), so a missing
      table is read here as the artifact holding no records of that kind and
      **not** as a fault: it is the same decision, taken at build time, that
      `meta[attestation_records]` states in prose.
    * every record carries a link and a MAC — **CHECKABLE-WITH-A-KEY-THE-FILE-
      DOES-NOT-CONTAIN**. The check exists and is gated on a keyring, and the
      detail names both the keyring and what `verify_chain` would then say.
    * a record carrying a blank `mac` or `prev_hash` — **READABLE-NOT-CHECKABLE**.
      That one is unverifiable by *anyone*, key or no key, so it is not the
      state above with a key missing; it is the file holding a record and not
      the signature the record would be checked against.
    """
    present = {
        str(row["name"])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    held: list[tuple[str, str, str, int]] = []
    unsigned: list[str] = []
    for role, table, count_key in COLD_READ_RECORD_CHAINS:
        if table not in present:
            continue
        row = conn.execute(
            "SELECT count(*) AS held, "
            "count(nullif(trim(mac), '')) AS macs, "
            "count(nullif(trim(prev_hash), '')) AS links "
            f"FROM {table}"  # noqa: S608
        ).fetchone()
        rows, macs, links = (
            int(row["held"]),
            int(row["macs"]),
            int(row["links"]),
        )
        if not rows:
            continue
        held.append((role, table, count_key, rows))
        if macs < rows or links < rows:
            unsigned.append(
                f"{table}: {rows} row(s), {macs} carrying a mac and {links} a "
                "prev_hash"
            )

    if not held:
        recorded = attestation_state(conn)
        return ColdReadClaim(
            claim=CLAIM_CHAIN_INTACT,
            question=COLD_READ_QUESTIONS[CLAIM_CHAIN_INTACT],
            state=ABSENT,
            detail=(
                "this file holds no record in "
                + ", ".join(
                    f"{table} ({'empty' if table in present else 'no such table'})"
                    for _, table, _ in COLD_READ_RECORD_CHAINS
                )
                + f", and meta[{META_ATTESTATION_RECORDS!r}] is "
                + (f"{recorded!r}" if recorded is not None else "not stated")
                + ". There is no chain here to have been altered, so the file "
                "makes no claim rather than making one nobody can check. A "
                "build handed no record stream does not create the tables, so "
                "their absence is that decision and not a loss. A build is "
                "handed one with `python -m reg.graph build ... --keyring`."
            ),
        )

    summary = "; ".join(
        f"{table} ({role} chain): {rows} record(s), the artifact "
        + (
            f"states meta[{count_key!r}]={stated[count_key]}"
            if count_key in stated
            else f"states no meta[{count_key!r}]"
        )
        for role, table, count_key, rows in held
    )
    if unsigned:
        return ColdReadClaim(
            claim=CLAIM_CHAIN_INTACT,
            question=COLD_READ_QUESTIONS[CLAIM_CHAIN_INTACT],
            state=READABLE_NOT_CHECKABLE,
            detail=(
                f"{summary}. But {'; '.join(unsigned)} — so for those the file "
                "holds the record and not the signature a reader would check it "
                "against. A record whose mac or prev_hash is blank is "
                "unverifiable by anyone, holding the key or not, which is a "
                "different fact from a check gated on a key this file does not "
                "carry. Nothing this repository writes can produce it: both "
                "columns are NOT NULL and reg.chain writes both."
            ),
        )
    return ColdReadClaim(
        claim=CLAIM_CHAIN_INTACT,
        question=COLD_READ_QUESTIONS[CLAIM_CHAIN_INTACT],
        state=CHECKABLE_WITH_A_KEY,
        detail=(
            f"{summary}. Every one of those records carries the prev_hash "
            "linking it to its predecessor and the mac its party signed it "
            "with, so the walk that answers this question is runnable — and "
            "what it needs beyond this file is **the key**. No key is in the "
            "artifact and none should be: a MAC verifiable with nothing but the "
            "file it sits in attests to nobody. A reader brings a keyring "
            "naming the "
            + " and ".join(sorted({role for role, _, _, _ in held}))
            + " key(s), and reg.query.verify_chain(conn, keyring) then reports "
            "VERIFIED, BROKEN or COULD-NOT-EVALUATE per chain, naming the "
            "record and what changed. Without a keyring the links are still "
            "walked and no MAC is checked, which is a could-not-evaluate and "
            "never a pass. This report does not run that walk: verify_chain is "
            "the one implementation of it, and a second here would be free to "
            "disagree with the one under test."
        ),
    )


def _acknowledgment_claim(conn: sqlite3.Connection) -> ColdReadClaim:
    """Was the passivation acknowledged, and by whom (issues #247, #242)?

    Claim 4's second question, and the one half of it the file answers **alone**
    — `acknowledgments(conn)` takes a connection and no keyring. So this row
    runs that query and reads its verdict; it does not re-derive the passivation
    walk, for the reason the row above does not re-walk the chain.

    Three states and the third never resolves to the first:

    * the build was handed no record stream — **ABSENT**. It holds no verdict
      that could have stopped the robot and no acknowledgment that could have
      cleared one.
    * the query answers — **CHECKABLE**, whether the answer is *every
      passivation was acknowledged* or *enforcement never stopped the robot*.
      Both are closed answers about this run.
    * the query refuses — **COULD-NOT-EVALUATE**, carrying its own reason. A
      passivation this artifact holds no acknowledgment of is never a *no*: the
      record holds what enforcement was *told*, and an operator who cleared the
      cell without telling it leaves the same absence as one who did nothing.
      Flattening that into ABSENT would undo the distinction issue #247 exists
      for.
    """
    recorded = attestation_state(conn)
    if recorded != ATTESTATION_PRESENT:
        return ColdReadClaim(
            claim=CLAIM_ACKNOWLEDGMENT,
            question=COLD_READ_QUESTIONS[CLAIM_ACKNOWLEDGMENT],
            state=ABSENT,
            detail=(
                f"meta[{META_ATTESTATION_RECORDS!r}] is "
                + (f"{recorded!r}" if recorded is not None else "not stated")
                + ": this build was handed no record stream, so it holds no "
                "verdict that could have stopped the robot and no "
                "acknowledgment that could have cleared one. The file makes no "
                "claim here rather than making one it cannot support."
            ),
        )
    answer = acknowledgments(conn)
    if answer.verdict != ANSWERED:
        return ColdReadClaim(
            claim=CLAIM_ACKNOWLEDGMENT,
            question=COLD_READ_QUESTIONS[CLAIM_ACKNOWLEDGMENT],
            state=COULD_NOT_EVALUATE,
            detail=(
                "reg.query.acknowledgments refuses on this file: "
                f"{answer.reason} That is a could-not-evaluate and never a "
                "*no*; the second half of the question — *and by whom* — has "
                "nobody to name here."
            ),
        )
    return ColdReadClaim(
        claim=CLAIM_ACKNOWLEDGMENT,
        question=COLD_READ_QUESTIONS[CLAIM_ACKNOWLEDGMENT],
        state=CHECKABLE,
        detail=(
            "reg.query.acknowledgments answers from this file and takes no "
            f"keyring to do it: {answer.reason}. Checked here with nothing but "
            "the connection, which is what separates this half of Claim 4 from "
            "the chain row above. It answers *and by whom* with the signing "
            f"party — {ACKNOWLEDGING_PARTY} — and never with a person: no field "
            "of the record holds one, and meta[operator_id] names who the build "
            "said was responsible for the run rather than who cleared the stop."
        ),
    )


#: What the row says in every state, because it is true in every state. Two
#: sentences, spelled once: the second fact §8 asks for and does not have a key
#: for, and the limit on what reading three values can mean.
_DISCLOSURE_CAVEAT = (
    "The fourth fact docs/limitations.md §8 asks for — the retention basis, "
    "the instrument a six-month window is claimed under — is not among these "
    "keys and has no key anywhere in the file: naming it is a legal "
    "determination this project has no standing to make, so §8 keeps it as an "
    "open gap and this row does not read as though §8 closed. Recording is not "
    "discharging: nothing in this module adjudicates what is stated, and this "
    "row is a reading of a block of text rather than a finding about the "
    "deployment it describes."
)


def _stated_text_refusal(value: str) -> str | None:
    """`reg.identity._stated_text`, minus the blank rule the caller has run.

    A reason or an identifier is text the deployer states and this project
    records without interpreting, so the only thing refused about it is that it
    would be unreadable where it is stored.
    """
    for char in _FORBIDDEN_DISCLOSURE_CHARS:
        if char in value:
            return f"it contains {char!r}, which `meta` cannot hold readably"
    return None


def _worker_notice_refusal(value: str) -> str | None:
    """Why `reg.identity.WorkerNotice.parse` would refuse `value`, or `None`.

    The reader's copy of the writer's grammar, in the order `parse` and
    `WorkerNotice.__post_init__` apply it: a status from a closed vocabulary,
    then whatever that status requires beside it — a `WORKER_NOTICE_DATE_FORMAT`
    date after `given`, a stated reason after `not-applicable`, and nothing at
    all after `not-given`.

    It returns a reason rather than a bool because the row quotes what it
    refuses: *the value is not readable* tells an assessor nothing they can act
    on, and *the status is known but the date beside it is not the format this
    artifact writes dates in* tells them where to look.
    """
    head, _, rest = value.strip().partition(_NOTICE_SEPARATOR)
    detail = rest.strip()
    if head not in WORKER_NOTICE_STATUSES:
        return (
            f"{head!r} is not a worker-notice status; the vocabulary is "
            f"{list(WORKER_NOTICE_STATUSES)} and it is closed"
        )
    if head == WORKER_NOTICE_GIVEN:
        if not detail:
            return (
                f"{head!r} carries no date, and the writer requires one in "
                f"{WORKER_NOTICE_DATE_FORMAT}"
            )
        try:
            parsed = _dt.datetime.strptime(detail, WORKER_NOTICE_DATE_FORMAT)
        except ValueError:
            return f"the date {detail!r} is not {WORKER_NOTICE_DATE_FORMAT}"
        if parsed.strftime(WORKER_NOTICE_DATE_FORMAT) != detail:
            return (
                f"the date {detail!r} does not round-trip through "
                f"{WORKER_NOTICE_DATE_FORMAT}"
            )
        return None
    if head == WORKER_NOTICE_NOT_APPLICABLE:
        if not detail:
            return f"{head!r} carries no stated reason, and the writer requires one"
        return _stated_text_refusal(detail)
    if detail:
        return (
            f"{head!r} carries {detail!r} beside it, and the writer allows "
            "nothing there"
        )
    return None


def _operator_id_kind_refusal(value: str) -> str | None:
    """Why `reg.identity.OperatorIdKind(value)` would refuse, or `None`.

    A closed two-member vocabulary, matched exactly: the writer takes the value
    straight to the enum, so neither surrounding space nor a case variant is a
    value any artifact can carry.
    """
    if value not in OPERATOR_ID_KINDS:
        return (
            f"{value!r} is not an operator-id kind; the vocabulary is "
            f"{list(OPERATOR_ID_KINDS)} and it is closed"
        )
    return None


#: Which of the three keys this module holds a grammar for, and which it does
#: not. `META_DPIA_REFERENCE` is absent on purpose — see `OPERATOR_ID_KINDS`.
_DISCLOSURE_GRAMMARS = {
    META_WORKER_NOTICE: _worker_notice_refusal,
    META_OPERATOR_ID_KIND: _operator_id_kind_refusal,
}


def _disclosure_grammar_refusal(key: str, value: str) -> str | None:
    """Why `reg.graph.build` would not have written `value` under `key`, or `None`.

    `None` is *this reader can read it back*, and it is also what a key with no
    grammar gets: `META_DPIA_REFERENCE` is free text, and a reader that invented
    a vocabulary for it would refuse artifacts the writer accepts.
    """
    check = _DISCLOSURE_GRAMMARS.get(key)
    return None if check is None else check(value)


def _disclosures_claim(stated: Mapping[str, str]) -> ColdReadClaim:
    """What does this artifact state about the obligations its existence creates?

    Issue #125 gave the build three keys — `reg.graph.META_WORKER_NOTICE`,
    `META_DPIA_REFERENCE` and `META_OPERATOR_ID_KIND` — each required with no
    default, so a build that was told nothing fails rather than recording
    something that reads like an answer. Nothing read them back, and a reader
    holding the file still could not separate *built before the keys existed*
    from *built by something that skipped them*. This row is that reader.

    Three conditions and the third never resolves to the first:

    * **all three stated — CHECKABLE.** The row quotes them verbatim. A
      paraphrase would be this module interpreting a statement the deployer
      made, which is exactly what `reg.identity` refuses to do at the writing
      end.
    * **none stated — ABSENT.** The file makes no statement. That is not a *no*
      and it is not compliance: a build predating the keys and a build that
      skipped them leave the same silence here, and the row says so rather than
      resolving it. An artifact *can* state the negative — `worker_notice`
      carries `not-given` and `dpia_reference` carries `none` — and an artifact
      that did is in the state above, which is the whole difference issue #125
      built at the writing end and this row keeps at the reading end.
    * **some but not all — COULD-NOT-EVALUATE**, naming the ones that are
      missing. A partial block is neither the silence of a file that states
      nothing nor a statement that can be read back, and reporting it as either
      would invent the half that is not there. This is the rule
      `meta['limits_source']` is already held to one subject over.

    **A value the writer's grammar would refuse is the third state too** (issue
    #268). `reg.identity` holds `worker_notice` and `operator_id_kind` to closed
    vocabularies and refuses the build on anything else, so `worker_notice =
    'yes probably'` is the same evidence a missing key is: written by something
    else, or edited since, and which of those is not in the file. It is not
    ABSENT — the key is here, so the file is not silent — and it is not
    CHECKABLE either, because CHECKABLE tells an assessor the block reads back
    as the deployer's statement, and a value the deployer's tooling cannot
    produce is not that. The value is still quoted exactly, so nothing about it
    is restated; it is read no further. `_disclosure_grammar_refusal` is where
    the reader's copy of that grammar lives, and `dpia_reference` is not in it.

    **A key stated as empty text is neither.** `reg.identity` refuses a blank
    value at the writing end, because it reads as absent in every `meta` dump
    while having been supplied, and quoting an empty string back at an assessor
    would present it as a statement. So a blank key is not read back — and it
    is not counted as silence either, which is where this parts company with
    `_environment_claim`: there a blank `env_*` key is ABSENT because the
    consequence of taking it at face value is a *machine mismatch* against a
    file that never said. Here the key is present, so something wrote it, and
    reporting that as *the file makes no statement* would lose the one fact
    that is in the file. A block with any blank in it is the third state.
    """
    absent = [key for key in COLD_READ_DISCLOSURE_KEYS if key not in stated]
    blank = [
        key
        for key in COLD_READ_DISCLOSURE_KEYS
        if key in stated and not stated[key].strip()
    ]
    refused: list[tuple[str, str, str]] = []
    for key in COLD_READ_DISCLOSURE_KEYS:
        if key in absent or key in blank:
            continue
        why = _disclosure_grammar_refusal(key, stated[key])
        if why is not None:
            refused.append((key, stated[key], why))

    if not absent and not blank and not refused:
        quoted = "; ".join(
            f"meta[{key!r}] = {stated[key]!r}" for key in COLD_READ_DISCLOSURE_KEYS
        )
        return ColdReadClaim(
            claim=CLAIM_DISCLOSURES,
            question=COLD_READ_QUESTIONS[CLAIM_DISCLOSURES],
            state=CHECKABLE,
            detail=(
                f"all {len(COLD_READ_DISCLOSURE_KEYS)} disclosure keys are "
                f"stated, and here they are as the file holds them — {quoted}. "
                "Quoted rather than summarised: what the deployer stated is "
                "what an assessor reads, and a paraphrase would be this "
                "reader interpreting it. A value here can state that nothing "
                f"was done — {META_WORKER_NOTICE}={WORKER_NOTICE_NOT_GIVEN!r} "
                f"and {META_DPIA_REFERENCE}={DPIA_NONE!r} are the stated "
                "negatives — so a file in this state has made a statement, "
                "which is a different fact from the silence an artifact "
                f"stating none of them reports as ABSENT. {_DISCLOSURE_CAVEAT}"
            ),
        )

    if len(absent) == len(COLD_READ_DISCLOSURE_KEYS):
        return ColdReadClaim(
            claim=CLAIM_DISCLOSURES,
            question=COLD_READ_QUESTIONS[CLAIM_DISCLOSURES],
            state=ABSENT,
            detail=(
                "this file states none of "
                f"{', '.join(COLD_READ_DISCLOSURE_KEYS)}, so it makes no "
                "statement about the obligations its own identity block "
                "creates. Silence, and silence is not a *no*: a build written "
                "before these keys existed (issue #125) and a build that "
                "skipped them leave the same absence here, and this reader "
                "cannot tell them apart from the file. It is not the stated "
                "negative either — a deployer states that with "
                f"{META_WORKER_NOTICE}={WORKER_NOTICE_NOT_GIVEN!r} and "
                f"{META_DPIA_REFERENCE}={DPIA_NONE!r}, and this file "
                f"states neither. {_DISCLOSURE_CAVEAT}"
            ),
        )

    faults = []
    if absent:
        faults.append(f"not stated at all: {', '.join(absent)}")
    if blank:
        faults.append(f"stated as empty text: {', '.join(blank)}")
    if refused:
        faults.append(
            "stated in a form reg.identity would refuse: "
            + "; ".join(
                f"meta[{key!r}] = {value!r} ({why})" for key, value, why in refused
            )
        )
    grammar_note = (
        (
            " A value outside that grammar is quoted above exactly as the file "
            "holds it and is read no further: what the deployer's own tooling "
            "cannot produce is not a statement this reader can hand back as "
            "the deployer's."
        )
        if refused
        else ""
    )
    readable = (
        len(COLD_READ_DISCLOSURE_KEYS) - len(absent) - len(blank) - len(refused)
    )
    return ColdReadClaim(
        claim=CLAIM_DISCLOSURES,
        question=COLD_READ_QUESTIONS[CLAIM_DISCLOSURES],
        state=COULD_NOT_EVALUATE,
        detail=(
            f"this file carries {readable} of the "
            f"{len(COLD_READ_DISCLOSURE_KEYS)} disclosure keys in a form this "
            f"reader can read back — {'; '.join(faults)}. That is a "
            "could-not-evaluate and it resolves to neither neighbour: it is "
            "not the silence an artifact carrying none of the keys reports as "
            "ABSENT, because part of the block is here, and it is not a "
            "statement that can be read back, because part of it is not. "
            f"reg.graph.build writes all {len(COLD_READ_DISCLOSURE_KEYS)}, each "
            "one inside the grammar reg.identity holds it to, or refuses the "
            "build (issues #125, #268), so this file was written by something "
            "else or has been edited since, and which of those it was is not "
            f"in the file.{grammar_note} {_DISCLOSURE_CAVEAT}"
        ),
    )


def cold_read(conn: sqlite3.Connection) -> ColdRead:
    """What this artifact says about itself, checked against itself alone.

    docs/self-describing.md §2's acceptance criterion, as a thing that runs. It
    opens nothing but the artifact it is handed — no document, no stream, no
    second file — and reports one row per claim in `COLD_READ_CLAIMS`, each with
    one of `COLD_READ_STATES`.

    **It closes no gap.** It makes the gaps legible from the file, which is what
    lets issue #228 be judged by something other than a PR body. Rows leave
    `READABLE-NOT-CHECKABLE` when the work that closes them lands and never
    because this function was edited — `reached-point` was the last of the four
    still in that state and moved with issue #258, which added the query that
    tests a point against the retained boundary. The state is still one this
    report reaches on its own evidence: strip the boundaries out of a file and
    the row goes back.

    **It reports and does not re-verify.** The environment comparison is issue
    #201's, spelled over `COLD_READ_RECOMPUTE_KEYS`, and `recompute_permitted`
    is held to agree with `reg.graph.envelope_at` by `tests/test_query.py` on
    both sides. The chain row goes further and runs *nothing*: it has no
    keyring, and `reg.chain.verify_chain` is the one implementation of that walk
    (issue #242). If any of them disagrees with its reader that is a bug here,
    not a second opinion.

    *Two rows do run a query, and it is the same rule rather than an exception
    to it.* `passivation-acknowledged` runs `acknowledgments` and `reached-point`
    runs `reached_point`, in both directions, because for those two the check is
    **in this module** — running it is reading the one implementation rather than
    writing a second one, which is exactly what the chain row refuses to do.

    Args:
        conn: an open artifact. `reg.store.connect` refuses a `schema_version`
            this build does not understand, so the older-schema arm below is
            reachable only through a raw `sqlite3` connection — which is exactly
            how an assessor with an archived file would meet it, and why it is
            handled rather than assumed away.

    Returns:
        A `ColdRead`. Never a partial one: every claim in `COLD_READ_CLAIMS` gets
        a row, because a row omitted and a row reporting `ABSENT` are different
        facts and a report that could omit one would make them look the same.
    """
    stated_version = _schema_version_text(conn)
    if stated_version != str(COLD_READ_SCHEMA_VERSION):
        return ColdRead(
            schema_version=stated_version,
            claims=_unpinned_claims(stated_version),
            recompute_permitted=None,
        )

    stated = store.all_meta(conn)
    environment = _environment_claim(stated)
    envelopes = conn.execute(
        "SELECT count(*) AS total, "
        "       count(*) - count(geometry_wkb) AS discarded, "
        "       count(outer_radius) AS radial, "
        f"      count({OUTER_BOUNDARY_COLUMN}) AS stored "  # noqa: S608
        "FROM envelope"
    ).fetchone()
    recompute, permitted = _recompute_claim(
        stated,
        environment,
        int(envelopes["discarded"]),
        int(envelopes["total"]),
    )
    return ColdRead(
        schema_version=stated_version,
        claims=(
            environment,
            recompute,
            _layer_basis_claim(conn),
            _reached_point_claim(
                conn,
                int(envelopes["radial"]),
                int(envelopes["total"]),
                int(envelopes["stored"]),
            ),
            _chain_intact_claim(conn, stated),
            _acknowledgment_claim(conn),
            _disclosures_claim(stated),
        ),
        recompute_permitted=permitted,
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


def render_commitment_check(check: object) -> str:
    """A `reg.commit.CommitmentCheck` as text. Reads nothing but the check.

    Printed beside every `--verify-chain`, including — especially — when the
    answer is that no commitment was made. A chain report on its own reads as
    the whole integrity story, and it is not: it says the records were not
    edited, and says nothing about whether the entire history was re-issued
    offline by the party that signed it.

    When the heads moved, both are printed. "INVALID" without them sends an
    assessor back to the file to work out *which* chain was re-issued, and the
    check already knows.

    Annotated `object` rather than `CommitmentCheck` for `render_chain_report`'s
    reason: naming the type would mean importing `reg.commit` — and through it
    `reg.chain` — at module level, which the module header says this file does
    not do.
    """
    lines = [f"commitment: {check.state.value}", ""]
    lines.append(f"  scheme:    {'none' if check.scheme is None else check.scheme}")
    if check.witness_id is not None:
        lines.append(f"  witness:   {check.witness_id}")
    if check.recorded is not None and check.computed is not None:
        for name, label in (
            ("declaration_head", "declaration"),
            ("verdict_head", "verdict"),
        ):
            recorded = getattr(check.recorded, name)
            computed = getattr(check.computed, name)
            if recorded == computed:
                lines.append(f"  {label} head: {recorded}")
            else:
                lines.append(f"  {label} head: committed {recorded}")
                lines.append(f"  {' ' * len(label)}       artifact  {computed}")
    lines.append(f"  reason:    {check.reason}")
    return "\n".join(lines)


def render_cold_read(report: ColdRead) -> str:
    """A `ColdRead` as text. Reads nothing but the report.

    Every row prints its state *and* its detail, and the detail is not
    abbreviated. "READABLE-NOT-CHECKABLE" on its own is not usable evidence: an
    assessor's next question is *what did you read, and what is missing*, and
    the report already knows.
    """
    permitted = {
        True: "yes — the compared keys agree with this interpreter",
        False: "no — a compared key differs from this interpreter",
        None: "could not be decided — nothing was compared",
    }[report.recompute_permitted]
    lines = [
        "cold read: what this artifact says about itself, with no document open",
        "",
        f"  schema_version:      "
        f"{report.schema_version if report.schema_version is not None else 'not stated'}"
        f" (states derived against {COLD_READ_SCHEMA_VERSION})",
        f"  recompute permitted: {permitted}",
        "",
    ]
    for row in report.claims:
        lines.append(f"  {row.claim}: {row.state}")
        lines.append(f"    question: {row.question}")
        lines.append(f"    detail:   {row.detail}")
        lines.append("")
    lines.append(
        f"  checkable from the file:     "
        f"{', '.join(report.checkable) if report.checkable else 'none'}"
    )
    lines.append(
        f"  not checkable from the file: "
        f"{', '.join(report.not_checkable) if report.not_checkable else 'none'}"
    )
    return "\n".join(lines)


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
    if isinstance(value, ReachedPoint):
        cover = value.coverage
        return [
            f"({value.x:g}, {value.y:g}) at t={value.t:.4f} s: "
            + (
                "NOT EXCLUDED — the point is inside the outer reachable set, "
                "which over-covers, so this is not *the robot was there*"
                if value.could_have_reached
                else "EXCLUDED — the point is outside the outer reachable set, "
                "so the robot could not have reached it"
            ),
            f"tested against the retained boundary of envelope "
            f"{value.envelope_id} (outer_area {value.outer_area_m2:g} m2, "
            f"outer_radius {value.outer_radius_m:g} m, HAS_ENVELOPE tagged "
            f"layer {value.envelope_layer})",
            f"pointwise coverage: {cover.pointwise_rows:,} of "
            f"{cover.frames:,} frame(s); {cover.envelope_rows:,} envelope "
            f"row(s) retained, {cover.radial_rows:,} of them with a radius",
        ]
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
    lines.append("")
    lines.append(
        "not a query, and not an Answer: --cold-read asks docs/self-describing."
        "md \u00a72's question of the file itself — for every claim this artifact "
        "makes about itself, can it be checked from the file or not. One row "
        f"per claim in {', '.join(COLD_READ_STATES)}; the last three never "
        "resolve to the first, and READABLE-NOT-CHECKABLE is a state of its own "
        "rather than a soft pass. "
        + CHECKABLE_WITH_A_KEY
        + " is the tamper-evidence row: the chain is checkable and the key is "
        "deliberately not in the file, so --cold-read reads no key and reports "
        "what --verify-chain would tell a reader who brought one. It closes no "
        "gap and it opens no document. Exit 0, or 1 if a row could not be "
        "evaluated."
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
        "--reached-point",
        nargs=3,
        metavar=("X_M", "Y_M", "T"),
        help=(
            QUERIES["reached_point"].question
            + " — a frame the file retains no boundary at is a "
            "could-not-evaluate, never the radius in this answer's place"
        ),
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
    group.add_argument(
        "--cold-read",
        action="store_true",
        # THE FIVE STATES, ALL OF THEM, AND A TEST HOLDS THEM TO
        # `COLD_READ_STATES` (issue #272). This string listed four for as long
        # as there were five: `CHECKABLE-WITH-A-KEY-THE-FILE-DOES-NOT-CONTAIN`
        # arrived with issue #242 and was never added here, so the one state
        # whose name a reader could not guess was the one --help left out — and
        # a help text that names four of five reads as a complete set rather
        # than as a stale one. `tests/test_query.py::
        # test_the_cold_read_help_names_every_state_the_report_can_report` is
        # what makes the next one impossible to leave out quietly.
        help=(
            "what this artifact says about itself, with no document open "
            "(docs/self-describing.md §2): one row per claim, each CHECKABLE, "
            "CHECKABLE-WITH-A-KEY-THE-FILE-DOES-NOT-CONTAIN, "
            "READABLE-NOT-CHECKABLE, ABSENT or COULD-NOT-EVALUATE (exit 0 "
            "unless a row could not be evaluated, which is exit 1)"
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
        "--witness",
        metavar="PATH",
        help=(
            "the witness file whose key signed this artifact's chain heads "
            "(reg.commit.write_witness). Only read by --verify-chain. Without "
            "it the recorded heads are still checked against the artifact's own "
            "records — which is what catches a re-issued chain — but the "
            "signature over them is not, and that is a could-not-evaluate"
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
            + ("distance in metres." if name.endswith("_M") else "time in seconds.")
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
    if args.reached_point is not None:
        x, y, t = args.reached_point
        return reached_point(
            conn, _number(x, "X_M"), _number(y, "Y_M"), _number(t, "T")
        )
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
    from reg import chain, commit

    keyring = None
    if args.keyring is not None:
        try:
            keyring = chain.load_keyring(args.keyring)
        except chain.KeyringError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return EXIT_USAGE

    witness = None
    if args.witness is not None:
        try:
            witness = commit.load_witness(args.witness)
        except commit.CommitmentError as exc:
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
        commitment_check = commit.verify_commitment(conn, witness)
    finally:
        conn.close()

    print(render_chain_report(report))
    print()
    print(render_commitment_check(commitment_check))
    exit_code = {
        chain.ChainState.VERIFIED: EXIT_OK,
        chain.ChainState.BROKEN: EXIT_BROKEN,
        chain.ChainState.COULD_NOT_EVALUATE: EXIT_COULD_NOT_EVALUATE,
    }[report.state]
    # A definite commitment fault outranks a chain that walked cleanly, and it
    # has to: a chain whose links all hold and whose committed heads do not
    # match it is precisely a **re-issued** history, which is the fault the
    # chain alone cannot see. It does not work in the other direction — an
    # absent or unchecked commitment leaves the chain's own verdict exactly
    # where it was, because `verify_chain`'s contract is published and an
    # artifact built before this interface existed did not get worse.
    if commitment_check.state is commit.CommitmentState.INVALID:
        return EXIT_BROKEN
    return exit_code


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
    if args.witness is not None:
        print(
            "error: --witness belongs to --verify-chain. The incident report's "
            "integrity clause is the chain walk, and folding a commitment "
            "verdict into it would change what that clause has meant since "
            "issue #49. Run --verify-chain --witness for the commitment.",
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


def _cold_read_cli(args: argparse.Namespace) -> int:
    """`--cold-read`. Exit `0` if every claim got a state, `1` if one could not.

    A `COULD-NOT-EVALUATE` row exits `1` for the reason every other exit code
    here exists: a script that read "could not check" as "checked and fine" is
    the failure the three-state discipline exists to prevent.
    `READABLE-NOT-CHECKABLE` exits `0` — it is not a failure of the run, it is
    the report saying what it was asked to say, and an exit code that treated it
    as one would be red on every artifact this project has ever built.
    """
    try:
        conn = store.connect(Path(args.artifact))
    except store.StoreError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    try:
        report = cold_read(conn)
    finally:
        conn.close()
    print(render_cold_read(report))
    unevaluated = [
        row.claim for row in report.claims if row.state == COULD_NOT_EVALUATE
    ]
    return EXIT_COULD_NOT_EVALUATE if unevaluated else EXIT_OK


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
            ("--witness", args.witness is not None),
            ("--tamper", args.tamper is not None),
            ("--tamper-out", args.tamper_out is not None),
            ("--tamper-resign", args.tamper_resign),
        )
        if given
    ]
    if stray:
        print(
            f"error: {', '.join(stray)} belong(s) to --verify-chain or "
            "--incident, neither of which was asked for. No scene query, no "
            "attestation query and no cold read reads a key, and --tamper "
            "exists to "
            "show the chain walk saying no — on its own it would alter a copy "
            "of an artifact and report nothing about the result. Refusing "
            "rather than ignoring them: a flag that is silently dropped reads "
            "as one that was applied.",
            file=sys.stderr,
        )
        return EXIT_USAGE

    # AFTER the stray-flag check, deliberately. `--cold-read --keyring K` reads
    # no key, and a flag that is silently dropped reads as one that was applied.
    if args.cold_read:
        return _cold_read_cli(args)

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
