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
once expensively. **Every one of those terms is body-frame, which is why the
argument is now stated with its condition** (issue #166): it holds for a base
that did not move, and a `robot_config` row that states a `base_pose` is one it
does not hold for — the same six inputs then describe the same arm somewhere
else, so `envelope_at` refuses such a row rather than handing back the region a
robot at the origin could reach.

**So a run whose base moved retains its geometry** (issue #191). The refusal
above is only half an answer: an artifact that discarded the polygon and then
refused to recompute it would answer every envelope query on a mobile run with a
could-not-evaluate — a file that parses and says nothing. `GEOMETRY_RETENTION`
therefore keeps the polygon on every frame whose configuration states a pose,
the rule text in `meta` says so, and the polygon kept is the **room-frame**
envelope: the body-frame set `compute_envelope` returns, rigidly placed at the
pose the frame states (docs/mobile-base.md §2, the third row of its table).
Retaining the body-frame set instead would reintroduce the very failure the
refusal exists to stop, one door along — a region about the origin handed back
for a robot that was elsewhere, indistinguishable from a right answer — and
every `INTERSECTS` overlap and `SEPARATION` distance in the file is measured
against entities in room coordinates, so a body-frame region would make those
edges statements about no run at all. The region inherits the pose and therefore
the perceiver, which is why every `HAS_ENVELOPE` edge over a posed configuration
is Layer **B** — `reg.store.open_edge` refuses an `A` on one, and this builder
states the `B` rather than being told about it a row too late.

What stays per frame is what queries actually read and what costs almost
nothing: `envelope_hash`, `area`, `horizon`, `source`, and — since issue #82 — `outer_area` and `outer_radius`, the same two projections of the
*outer* reachable set for that frame, which bracket the sampled area from the
side it cannot bound itself. The outer region's geometry is discarded under this
same rule and for this same reason.

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

AND BESIDE ALL OF IT, A COARSER LAYER — ISSUE #35
--------------------------------------------------
Everything above makes the fine layer cheaper without changing its resolution,
and issue #30 measured what that resolution still costs: 51.5 MB/hour, ~14x
larger per frame than a gzipped copy of the stream. The resolution itself was
never justified. UN R157's DSSAD — the only mandated evidence recorder for
autonomy that exists — records **occurrences**: a flag, a reason, a date, a
timestamp good to ±1.0 s, and the software version present at the event. Two
orders of magnitude coarser than cm / 10 ms every frame.

So this builder also emits an `Occurrence` layer (`OCCURRENCE_RETENTION`,
`OCCURRENCE_MATERIAL_EDGES`) at a stated, settable timestamp resolution, and
`reg.bench --resolution` measures what each layer costs and which questions each
can still answer. The layer is **additive** — not one edge row exists or fails
to exist because of it — because the deliverable is a curve over views of one
run, and three different builds would not be one.

AND THE ATTESTATION LAYER BESIDE BOTH — ISSUE #45
--------------------------------------------------
Everything above is about the *scene*: where the reachable set was and who was
in it. The other half of docs/plan.md Phase 5 is the record — the declarations
the policy signed, the verdicts enforcement signed back, and the chain links
between them — and until it is persisted, Milestone 3 exists only in memory and
none of it is queryable evidence.

`build` takes an `AttestationRecords` and writes four things: the two record
tables, an `Envelope` node per distinct region claimed or applied, the four
edges (`DECLARED`, `ADJUDICATED`, `ENFORCED`, `FOLLOWS`), and one occurrence per
enforcement event. Three properties are load-bearing and each has a test:

* **Nothing is re-signed or re-hashed.** The records go in verbatim and come
  back out of `reg.store.read_declarations` still verifying — or still failing
  to — under the key they were signed with. A store that could recompute a MAC
  could quietly repair a broken chain.
* **`ADJUDICATED` does not flatten.** A verdict is per *commanded action*, not
  per declaration: `declared_violation` produces 251 verdicts against 11
  declarations that all carry an identical `declared_envelope`, and two of those
  declarations are adjudicated PERMIT and then CLAMP. A one-row-per-declaration
  schema would pass every other test here while destroying the ability to say
  *when* the violation began — which is the demo sentence's second clause.
* **Every one of these edges is Layer A**, and not one names an `Entity`. That
  asymmetry is docs/sufficiency.md §2 and it is stated at the schema
  (`reg.store.EDGE_SPECS`) rather than here, where it would be a comment about
  someone else's table.

Record timestamps are stored as the record carries them, **not** quantized to
`TIME_TOL_S`. The scene layer's endpoints are observations and are good to the
frame period; a record's `t_issued` is a value the MAC covers, and reporting a
rounded version of it would be reporting an instant nobody signed.

AND ONE AXIS NONE OF THEM COVERS — ISSUE #77
---------------------------------------------
All three rules above are about *what is kept*. None of them says what the kept
timestamps can **address**, and that turned out to be the binding constraint at a
real control rate. Every endpoint written here is `quantize_time`d, so this
artifact has `1/TIME_TOL_S` = 100 addressable instants per second however fast
the stream was sampled. At 1 kHz eleven frames land on one instant, a per-frame
read-back returns the value of whichever of them opened the covering interval,
and `separation_timeline` misses its own `DISTANCE_TOL_M` budget by up to 0.0140
m (`near_miss`, seed 0).

It is a **quantization** limit and not a sampling one, and the two have different
fixes so the distinction is measured rather than asserted: the builder still sees
every frame, still emits the same 269 SEPARATION intervals at 1 kHz as at 100 Hz,
and every value it reports is within budget of a true frame *within `TIME_TOL_S`*
of the instant it is reported at. Nothing was sampled away; what is missing is
the address. `TIME_BASE_DOMAIN` states it in every artifact,
`tests/test_graph.py::test_the_time_base_miss_is_quantization_and_not_sampling`
is the evidence, and docs/limitations.md §5 is what a claim has to inherit.

WHAT IS NOT HERE
----------------
`verify_chain()` and `--tamper`. The `FOLLOWS` edges are written here from the
links the records already carry, and walking them to check every hash and every
MAC is the next issue's; so are the attestation queries. What this module does
check is that the stream it was handed *is* a chain — a record whose `prev_hash`
does not match its predecessor is a refusal, because a `FOLLOWS` edge written
across a break would assert a link that is not there.

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

The order settles the *state* side and it does not settle the bounds side, which
is issue #84: `limits` reaches the envelope untouched by the scene, but its
numbers can still be a function of what a perceiver measured. So this module does
not decide `HAS_ENVELOPE`'s layer either — `reg.envelope.envelope_layer(limits)`
does, once per build, and the answer goes on the edge and into
`meta['limits_source']`.

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
from shapely.affinity import affine_transform
from shapely.geometry import Point
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from reg import __version__, store
from reg.chain import GENESIS_HASH, KeyringError, chain_hash, load_keyring
from reg.commit import (
    COMMITMENT_NONE,
    COMMITMENT_STATEMENT,
    META_COMMITMENT,
    META_COMMITMENT_DECLARATION_HEAD,
    META_COMMITMENT_SIGNATURE,
    META_COMMITMENT_STATEMENT,
    META_COMMITMENT_VERDICT_HEAD,
    META_COMMITMENT_WITNESS,
    ChainHeads,
    Commitment,
    CommitmentError,
    WitnessCommitter,
    chain_heads,
    check_witness_is_independent,
    load_witness,
)
from reg.declare import Declaration, DeclarationError
from reg.enforce import PASSIVATING_FAULTS, EnforcementError, Verdict
from reg.envelope import (
    SUBSTEP_DT,
    compute_envelope,
    envelope_hash,
    envelope_layer,
    outer_envelope,
    outer_radius,
)
from reg.identity import IdentityError, RunIdentity
from reg.kinematics import ORIGIN_FRAME, BaseFrame, link_polygons
from reg.stream import FLOAT_PRECISION, read_comments, read_frames
from reg.tolerances import (
    AREA_QUANT_SIGFIGS,
    DISTANCE_TOL_M,
    GEOM_SIMPLIFY_TOL_M,
    TIME_BASE_MAX_RATE_HZ,
    TIME_TOL_S,
    addressable_instants,
    distance_bucket,
    quantize_area,
    quantize_distance,
    quantize_time,
    simplify_geometry,
)
from reg.types import (
    BasePose,
    Limits,
    LimitSource,
    Obstacle,
    PoseSource,
    ProprioState,
    StateFrame,
)

__all__ = [
    "ATTESTATION_RETENTION",
    "CLAMPED_ENVELOPE_SOURCE",
    "DECLARED_ENVELOPE_SOURCE",
    "ENVELOPE_HORIZON",
    "ENVELOPE_N_SAMPLES",
    "ENVELOPE_RETENTION",
    "ENVELOPE_SEED",
    "ENVELOPE_SOURCE",
    "GEOMETRY_EVIDENCE_EDGES",
    "GEOMETRY_RETENTION",
    "HUMAN_ENTITY_ID",
    "HUMAN_KIND",
    "META_ATTESTATION_RECORDS",
    "META_ATTESTATION_RETENTION",
    "META_DECLARATION_COUNT",
    "META_ENVELOPE_RETENTION",
    "META_GEOMETRY_RETENTION",
    "META_OCCURRENCE_RECORDER_VERSION",
    "META_OCCURRENCE_RESOLUTION",
    "META_OCCURRENCE_RETENTION",
    "META_OPERATOR_ID",
    "META_RUN_START",
    "META_TIME_BASE_DOMAIN",
    "META_TIME_BASE_INSTANTS",
    "META_TIME_BASE_RESOLVES",
    "META_UNIT_ID",
    "META_VERDICT_COUNT",
    "OCCURRENCE_MATERIAL_EDGES",
    "OCCURRENCE_RETENTION",
    "OCCURRENCE_TIME_RESOLUTION_S",
    "OCCURRENCE_VERDICT_EVENTS",
    "TIME_BASE_COLLAPSED",
    "TIME_BASE_DOMAIN",
    "TIME_BASE_RESOLVED",
    "AttestationRecords",
    "BuildResult",
    "GraphBuildError",
    "GraphQueryError",
    "attestation_from_stream",
    "build",
    "envelope_at",
    "envelope_frame",
    "main",
    "quantize_occurrence_time",
    "recorded_environment",
    "recorder_version",
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

#: The source every envelope computed from proprioception carries. The other two
#: arrive with the record stream below. All three are retained separately because
#: "a clamp is only legible if the declared and the computed bound both survive"
#: (docs/lossiness.md Retained #8) — and they are separate *rows*, never one row
#: with three meanings, so a query for "what the policy claimed" cannot come back
#: with what the arm could actually reach.
ENVELOPE_SOURCE = "computed"

#: The region a `Declaration` claimed its body would stay inside.
DECLARED_ENVELOPE_SOURCE = "declared"

#: The bound a CLAMP verdict actually applied.
CLAMPED_ENVELOPE_SOURCE = "clamped"

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
    "envelope geometry is stored on the first and last frame of the run, on "
    "every frame at which an INTERSECTS or CONTACT relationship with an entity "
    "begins or ceases to hold, and on every frame whose robot_config states a "
    "base_pose; on every other frame the envelope row carries its hash, area, "
    "horizon and source with a NULL geometry_wkb, and the polygon is recomputed "
    "from config_id and the envelope parameters in this meta table "
    "(reg.graph.envelope_at, docs/lossiness.md Discarded #9). The posed clause "
    "is not a preference: every term of that recomputation is body-frame, so "
    "for a configuration that states a pose it would return the region a robot "
    "at the origin could reach, and reg.graph.envelope_at refuses it. A row "
    "whose configuration states a pose and whose geometry_wkb is NULL is "
    "therefore an envelope this artifact cannot produce, and the build refuses "
    "to write one. Exact recomputation assumes the same code and the same "
    "shapely version — docs/limitations.md."
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

# --------------------------------------------------------------------------
# The occurrence layer (issue #35, docs/prior-art.md §9, docs/retention.md
# "What replaces it"). A second, much coarser view of the same run, in the shape
# UN R157's DSSAD mandates — and the reason it exists is that issue #30 measured
# what the fine view costs: 51.5 MB/hour, ~14x larger per frame than a gzipped
# copy of the stream, at a resolution (cm / 10 ms, every frame) that no standard
# asks for. This layer is what the question "how coarse can the evidence get
# before it stops answering the question?" is asked *with*.
#
# It is additive. Nothing above changed, and `reg.bench --resolution` compares
# the two as views of one build rather than as two different artifacts.
# --------------------------------------------------------------------------

#: DSSAD's stated timestamp accuracy, **±1.0 second** (UN R157; docs/prior-art.md
#: §9 has the element list). Imported from the regulation, not chosen here — the
#: same standing as `ENVELOPE_HORIZON`, which comes from docs/plan.md Phase 2.
#:
#: It is a *default*, not a constant: `build` takes it as an argument and records
#: what it was given in `meta`, because the whole point of this layer is
#: measuring what a resolution costs, and a resolution welded shut measures one
#: point rather than a curve. It is deliberately **not** in `reg.tolerances`:
#: that module owns the four constants docs/lossiness.md makes normative, and
#: this is not one of them. Confusing the two would make "coarsen the occurrence
#: timestamps" look like permission to widen `TIME_TOL_S`, which is the move the
#: contract exists to forbid.
OCCURRENCE_TIME_RESOLUTION_S: float = 1.0

#: Edge type -> (the occurrence when the relationship begins, the occurrence when
#: it ceases). **Only these two edge types produce occurrences**, and the absence
#: of the other two is the rule "material events, not quantization boundaries":
#: `SEPARATION` closes and reopens every time a distance crosses a
#: `DISTANCE_TOL_M` bucket — which for a walking human is every frame — and
#: `HAS_ENVELOPE` changes whenever the arm moves at all. Occurrences at those
#: would be the per-frame cost this layer exists to escape, wearing a coarser
#: timestamp.
#:
#: Counted over the *relationship*, not the edge row, for the reason
#: `GEOMETRY_EVIDENCE_EDGES` is: an `INTERSECTS` edge also closes and reopens on
#: every overlap-area quantum, and those are metric steps rather than the human
#: entering or leaving the reachable set.
OCCURRENCE_MATERIAL_EDGES: dict[str, tuple[str, str]] = {
    "INTERSECTS": ("envelope_entered", "envelope_left"),
    "CONTACT": ("contact_began", "contact_ended"),
}

#: Verdict outcome -> the occurrence it produces. The enforcement half of
#: `OCCURRENCE_MATERIAL_EDGES` (issue #45), and the first Layer A occurrences
#: that record something *happening*.
#:
#: `PERMIT` is deliberately absent, and it is the same rule the two missing edge
#: types above follow: a permitted action is the run proceeding normally, and one
#: row per permitted action is one row per frame — the per-frame cost this layer
#: exists to escape, wearing a coarser timestamp. The two events that are not in
#: this table are in `_OccurrenceLog.verdict_recorded`, because neither is a
#: property of one verdict: `escalation_failed` is a SAFE_STATE distinguished by
#: its fault, and `reintegrated` is the *absence* of a passivation that was there
#: a verdict ago.
OCCURRENCE_VERDICT_EVENTS: dict[str, str] = {
    "VETO": "declaration_vetoed",
    "CLAMP": "action_clamped",
    "SAFE_STATE": "safe_state_entered",
}

#: The reason element, per occurrence type. DSSAD records "the reason for the
#: occurrence, where applicable" beside the flag; these are this project's, in
#: prose, because the artifact is what an assessor holds and `envelope_entered`
#: alone does not say what it means.
OCCURRENCE_REASONS: dict[str, str] = {
    "run_began": "the first frame of the recorded run",
    "run_ended": "the last frame of the recorded run",
    "envelope_entered": (
        "the entity began to intersect the robot's computed reachable envelope"
    ),
    "envelope_left": (
        "the entity ceased to intersect the robot's computed reachable envelope"
    ),
    "contact_began": "the robot body and the entity began to intersect",
    "contact_ended": "the robot body and the entity ceased to intersect",
    "closest_approach": (
        "the smallest robot-to-entity separation observed in the run, at the "
        "earliest frame it was observed at"
    ),
    "declaration_vetoed": (
        "enforcement refused a declaration outright; the verdict of the same "
        "instant names which of the nine faults it was refused for"
    ),
    "action_clamped": (
        "a commanded action lay outside the declared envelope and was bounded to "
        "it rather than permitted as issued"
    ),
    "safe_state_entered": (
        "enforcement passivated the robot; recovery needs a fresh accepted "
        "declaration and an acknowledgment, and is not automatic"
    ),
    "reintegrated": (
        "enforcement resumed adjudicating commanded actions after a passivation"
    ),
    "escalation_failed": (
        "a declaration was issued while passivated and unacknowledged and was "
        "not an escalation, which is the one fault in the taxonomy with no "
        "transport-protocol analogue"
    ),
}

#: The occurrence retention rule, in one sentence, as it is recorded in the
#: artifact's meta table — the same discipline as `ENVELOPE_RETENTION` and for
#: the same reason. A reader meeting an occurrence layer with three rows in it
#: has to be able to tell "three things happened" from "this build only records
#: three kinds of thing", and the rows do not distinguish them.
OCCURRENCE_RETENTION = (
    "an occurrence row is written for a semantically material event and for "
    "nothing else: run_began and run_ended at the two ends of the run; "
    "envelope_entered and envelope_left at the frames an INTERSECTS "
    "relationship with an entity begins and ceases to hold; contact_began and "
    "contact_ended likewise for CONTACT; one closest_approach per entity, "
    "at the earliest frame at which the run's smallest quantized separation to "
    "that entity was observed, carrying that separation in metres; and one "
    "enforcement event per verdict that decided something — declaration_vetoed "
    "per VETO, action_clamped per CLAMP, escalation_failed per SAFE_STATE "
    "raised for an escalation failure, safe_state_entered at the verdict that "
    "passivated the enforcer, and reintegrated at the first action adjudicated "
    "after a passivation ended. A PERMIT produces none: a permitted action is "
    "the run proceeding, and one row per permitted action is one row per frame. "
    "A SAFE_STATE emitted while already passivated produces none either — it "
    "reports a passivation this layer has already recorded, and repeating it "
    "would count the frames a stopped robot did not move. Nothing is "
    "written when a metric merely crosses a quantization boundary — those are "
    "the transitions the edge layer records, and recording them here would "
    "reintroduce the per-frame cost this layer exists to measure against. Every "
    "timestamp is rounded to the nearest occurrence_time_resolution_s in this "
    "meta table, so this layer locates an event only to that resolution and "
    "nothing may report finer from it. A relationship still holding at the last "
    "frame gets no envelope_left or contact_ended; run_ended bounds it. The "
    "vocabulary is fixed (reg.store.OCCURRENCE_SPECS): an occurrence type "
    "outside it is a fault, not a new kind of row, and the absence of a type "
    "from this artifact means the event did not happen rather than that this "
    "build had no name for it. Every row carries DSSAD's date element and an "
    "absolute t_utc beside the run-relative t, both derived from the "
    "run_start_utc in this meta table by adding the row's own quantized t — so "
    "the resolution above is an accuracy on a wall clock, which is what the "
    "requirement is about, and not on a float with no clock behind it. That "
    "start is declared by the caller and never read from the building host's "
    "clock, so the artifact stays byte-reproducible: same seed and same "
    "declared start, same bytes. It is a claim by whoever built this file, "
    "exactly as the records are, and it is what makes the run correlatable with "
    "the other logs in the cell. DSSAD's R157SWIN element is NOT implemented "
    "here: it identifies the system under investigation, and nothing in this "
    "prototype has a policy version to bind, so no row carries one. The "
    "recorder_version column is the evidence tool's own build and envelope "
    "digest — a different piece of software — and must not be read as it."
)

#: Where the occurrence-layer facts land in `meta`.
META_OCCURRENCE_RETENTION = "occurrence_retention"
META_OCCURRENCE_RESOLUTION = "occurrence_time_resolution_s"
META_OCCURRENCE_RECORDER_VERSION = "occurrence_recorder_version"

# --------------------------------------------------------------------------
# The attestation layer (issue #45, docs/plan.md Phase 5's other half).
#
# The same discipline as the two retention rules above and for the same reason:
# a reader holding only the file has to be able to tell "this run produced no
# verdicts" from "this build does not store verdicts", and an empty table does
# not distinguish them. So the rule is in the artifact, and so is whether a
# record stream was supplied at all.
# --------------------------------------------------------------------------

#: The rule, as it is recorded in the artifact's meta table.
ATTESTATION_RETENTION = (
    "every Declaration and every Verdict the run produced is stored in full and "
    "verbatim — every field, including prev_hash and mac, exactly as the record "
    "was signed. Nothing is summarised, sampled or dropped (docs/lossiness.md "
    "Retained #4 and #5), and nothing is re-signed or re-hashed on the way in: "
    "this artifact cannot repair a record and cannot launder one, and a record "
    "read back out of it verifies, or fails to, exactly as it did before it was "
    "written. A DECLARED edge runs from each declaration to the region it "
    "claimed, spanning that declaration's own validity window [t_issued, "
    "t_issued + horizon]. An ADJUDICATED edge runs from each verdict to the "
    "declaration it adjudicated, at the instant of the commanded action: there "
    "is one per verdict and NOT one per declaration, because a verdict is per "
    "commanded action and one declaration is routinely adjudicated PERMIT and "
    "later CLAMP, so a count of ADJUDICATED edges is a count of adjudications. "
    "A verdict naming no declaration — which is what no_declaration and "
    "watchdog_expiry look like in the record — has no ADJUDICATED edge, and that "
    "absence is the finding. An ENFORCED edge runs from a verdict to the bound "
    "it actually applied and exists only for a CLAMP: a PERMIT bounds nothing, "
    "and a VETO or a SAFE_STATE permits no action to bound. A FOLLOWS edge links "
    "each record to its predecessor in its own chain; declarations chain under "
    "the policy key and verdicts under the enforcement key, so this artifact "
    "holds two chains and each begins at the genesis hash. Record timestamps are "
    "stored as the record carries them and are NOT quantized to the tolerance "
    "the edge layer's endpoints use — the record commits to its own instants and "
    "the MAC covers them. Declared and clamped envelope geometry is always "
    "stored: the envelope_geometry_retention rule discards a polygon only where "
    "it can be recomputed from a robot_config in this file, and a bound that came "
    "from a policy is not a function of any configuration here. The absence of "
    "the declaration_count key from this meta table means this build was given "
    "no record stream at all, which is not the same fact as a run that produced "
    "no records."
)

#: Where the attestation-layer facts land in `meta`.
META_ATTESTATION_RETENTION = "attestation_retention"

#: `present` or `absent` — whether this build was handed a record stream. The
#: counts below are written only when it was, so their absence is the same fact
#: said twice; this key is here so a reader does not have to infer it from a
#: missing one.
META_ATTESTATION_RECORDS = "attestation_records"
META_DECLARATION_COUNT = "declaration_count"
META_VERDICT_COUNT = "verdict_count"

# --------------------------------------------------------------------------
# The time base, and the rate range in which this artifact's own tolerances
# hold (issue #77).
#
# The three rules above say what this build *kept*. This one says what its
# timestamps can *address*, which is a different question and had never been
# answered in the file. Every interval endpoint here is quantized to
# `TIME_TOL_S`, so the artifact has exactly `TIME_BASE_MAX_RATE_HZ` = 100
# addressable instants per second however fast the control loop ran. Above that
# rate several frames land on one instant, and a per-frame value read back is the
# value of whichever of them opened the covering interval — which is how
# docs/lossiness.md's `separation_timeline` predicate came to miss its own 1 cm
# budget at 250 Hz and 1 kHz.
#
# WHY THIS IS RECORDED AND NOT REFUSED. A build above 100 Hz is not wrong, it is
# out of the range its own contract was written for, and those are different
# facts. Refusing would delete the measurement that found this (`reg.bench
# --control-rate-hz` builds at 1 kHz on purpose) and would tell a real
# manipulator, which runs at 1 kHz, that it may not have an evidence artifact at
# all. So the artifact carries the answer and a reader holding only the file can
# tell which case they have — the same discipline as the two retention rules,
# applied to the axis nobody had written down.
# --------------------------------------------------------------------------

#: The rule, in one sentence, as it is recorded in the artifact's meta table.
TIME_BASE_DOMAIN = (
    f"{TIME_BASE_MAX_RATE_HZ:g} addressable instants per second, whatever rate "
    "the stream was sampled at. The per-frame predicates of docs/lossiness.md "
    "hold exactly when time_base_addressable_instants == frame_count; "
    "docs/limitations.md \u00a75 is what a claim inherits when it does not."
)

#: Where the three time-base facts land in `meta`.
META_TIME_BASE_DOMAIN = "time_base_domain"
META_TIME_BASE_INSTANTS = "time_base_addressable_instants"
META_TIME_BASE_RESOLVES = "time_base_resolves_frames"

#: The two values `meta[time_base_resolves_frames]` may take. Words rather than
#: `1`/`0` for the reason `attestation_records` holds `present`/`absent`: the
#: file is read by a person, and a bare `0` in a column of counts reads as a
#: count of something.
TIME_BASE_RESOLVED = "yes"
TIME_BASE_COLLAPSED = "no"

#: Absolute time and identity (issue #83). Three keys, all written on every
#: build from a `RunIdentity` the caller supplies and none of them defaulted:
#: the run's declared start as a UTC instant, the unit that ran it, and the
#: operator responsible for it. Until they existed the artifact could not say
#: *which robot* or *which shift*, so it could not be correlated with any other
#: log in the cell — which is how an incident is actually reconstructed — and
#: DSSAD's ±1.0 s, an accuracy requirement on a wall clock, had been copied onto
#: a run-relative float with no wall clock behind it.
META_RUN_START = "run_start_utc"
META_UNIT_ID = "unit_id"
META_OPERATOR_ID = "operator_id"

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

#: The base's own actuation bounds (issue #151): one row for one body, in the
#: order `Limits.BASE_BOUND_FIELDS` states — `base_v_max` (m/s), `base_a_max`
#: (m/s^2), `base_omega_max` (rad/s), `base_alpha_max` (rad/s^2). Three units in
#: one value, which `limits_qd_max` above never has to carry, so the order is
#: read off `Limits` rather than restated here and `_base_bounds_from_meta`
#: refuses a value of any other length: four numbers whose meaning depends on
#: position is exactly the payload where a silent off-by-one is available.
#:
#: **One row, not four, and the reason is measured.** `meta` has a single row of
#: page headroom in the artifacts `reg.bench` publishes; a second spills onto a
#: new page and moves every byte figure in docs/retention.md by 2,048 B. Issue
#: #151 says no published figure moves, and one row per body is the layout that
#: is both true to the object and inside that budget. Whoever adds meta key
#: number two here should expect to re-measure and republish — that is a real
#: cost of a key, and it is better paid knowingly than discovered.
#:
#: `_limits_from_meta` refuses a file that lacks the key rather than reading the
#: absence as a base that was standing still — zero is what a bolted base
#: *states*, and an artifact that states nothing is a could-not-evaluate.
META_LIMITS_BASE_BOUNDS = "limits_base_bounds"

#: Where those limits came from (issue #84). The same contract as the six above
#: and one more thing besides: it is what the `HAS_ENVELOPE` edges in this file
#: were tagged from, so an artifact that does not carry it cannot say whether its
#: Layer A envelopes are Layer A. `_limits_from_meta` refuses a file with no such
#: key rather than reading it as `PROPRIOCEPTIVE` — an unrecorded provenance is a
#: could-not-evaluate, and resolving it to the clean case is exactly the
#: mislabelling this key exists to make visible.
META_LIMITS_SOURCE = "limits_source"


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
class AttestationRecords:
    """One run's signed record stream, as the producers emitted it.

    Both fields are required and neither has a default. `AttestationRecords((),
    ())` is a run that produced nothing, and passing `records=None` to `build` is
    a build that was not given a record stream; those are different facts, the
    artifact records which one it holds, and a default here would collapse them
    at the one place where the distinction is still available.

    The two tuples are two chains, not one interleaved stream: declarations link
    to declarations under the policy key and verdicts to verdicts under the
    enforcement key, each starting at `GENESIS_HASH`. Both must be in chain
    order — `build` refuses a stream whose links do not hold, because a FOLLOWS
    edge written across a break asserts a link that is not there.

    Acknowledgments are not here, and that is a **deliberate refusal, not an
    omission** (issue #110). They share the verdict chain, so a run that contains
    one has a verdict whose `prev_hash` names a record this artifact does not
    hold; `build` refuses that stream rather than writing a FOLLOWS edge over the
    gap. Two checks do it and both must keep doing it while the schema has no row
    for the record: the type check below refuses an `Acknowledgment` offered as a
    `Verdict`, and `_check_link` refuses the verdict that follows one. The cost is
    that no artifact can be asked whether a passivation was acknowledged — stated
    in `docs/lossiness.md` *Retained* #7 and in `README.md`'s Claim 4 row, and
    issue #112 is where it would change. Until then, removing either check is not
    a widening; it is a chain that walks cleanly over a record nobody ever saw.
    """

    declarations: tuple[Declaration, ...]
    verdicts: tuple[Verdict, ...]

    def __post_init__(self) -> None:
        for name, expected in (
            ("declarations", Declaration),
            ("verdicts", Verdict),
        ):
            values = getattr(self, name)
            if not isinstance(values, tuple):
                raise GraphBuildError(
                    f"AttestationRecords.{name} must be a tuple, got "
                    f"{type(values).__name__}. A generator would be consumed by "
                    "the first pass over it and the second would see an empty "
                    "run."
                )
            for i, value in enumerate(values):
                if not isinstance(value, expected):
                    raise GraphBuildError(
                        f"AttestationRecords.{name}[{i}] is a "
                        f"{type(value).__name__}, not a {expected.__name__}. The "
                        "record is what is stored; an object that resembles one "
                        "has not been through the validation that makes it a "
                        "record."
                    )


@dataclass(frozen=True)
class BuildResult:
    """What a build produced. Returned so callers do not re-query to find out."""

    path: Path
    frames: int
    #: Rows per edge type, all four keys always present. A zero is a fact ("no
    #: contact in this run"); a missing key would be indistinguishable from one.
    edges: dict[str, int]
    #: Rows per node kind, all six keys always present, for the same reason.
    #: `Declaration` and `Verdict` count 0 on a build handed no record stream —
    #: whose artifact has no such tables at all (issue #54) — and 0 is the count
    #: of rows written either way. Whether a stream was offered is
    #: `meta[attestation_records]`, not a row count, in both versions of the
    #: schema: an empty table counts zero too.
    nodes: dict[str, int]
    size_bytes: int
    #: How many distinct instants this run's frames quantized onto — the size of
    #: the artifact's time base (issue #77). Equal to `frames` when every frame
    #: has its own address and smaller when the stream was sampled faster than
    #: `TIME_BASE_MAX_RATE_HZ`. Returned rather than left in `meta` alone so the
    #: CLI can say so without reopening the file it just wrote.
    addressable_instants: int

    @property
    def total_edges(self) -> int:
        return sum(self.edges.values())

    @property
    def time_base_resolves_frames(self) -> bool:
        """Whether every frame of this run has its own address in the artifact.

        `False` means the build is outside the rate range docs/lossiness.md's
        per-frame predicates are written for (`TIME_BASE_DOMAIN`). It is not a
        failed build and nothing here treats it as one — the artifact holds the
        same intervals either way — but a caller that reports per-frame numbers
        off such a file is reporting them to the timestamp quantum and not to the
        frame.
        """
        return self.addressable_instants == self.frames


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


def _frame_text(base: BaseFrame) -> str:
    """A base frame as `x,y,theta`, at the raw stream's own precision.

    The same rendering as `_joint_text` and for the same reason: none of the four
    tolerances is a length quantum for a *frame*, so there is nothing to quantize
    here and inventing a quantum would put a bound in the artifact that no
    document states. It is also what keeps the pose out of the distance error
    budget — see the note beside `outer_radius` in `_frame_observations`.
    """
    return ",".join(
        f"{float(v):.{FLOAT_PRECISION}f}" for v in (base.x, base.y, base.theta)
    )


def _pose_columns(
    base_pose: BasePose | None, where: str
) -> tuple[str | None, str | None]:
    """The two `robot_config` columns a frame's base pose writes (issue #191).

    `(None, None)` for a frame that states no pose, and that pair is the whole of
    what the artifact then says: *nobody recorded where the base was*, on the
    same terms `base_vel=None` says it. It is not the origin — a base bolted at
    the origin is `meta[base_frame]`, a mounting fact about the run, and the two
    absences must not be one column.

    Both, or a refusal. `reg.types.BasePose` requires a `PoseSource` and refuses
    anything else, so a pose here with no provenance cannot arrive through the
    type — but *cannot occur* is not a reason to write `NULL` if it does. A
    `base_pose` with a `NULL` `base_pose_source` is the row
    `reg.store.insert_robot_config` and the schema `CHECK` both refuse, and
    silently dropping the pose instead would put a run whose base drove into an
    artifact that says it recorded no pose. So this refuses, loudly, naming the
    frame.

    The rendering is `_frame_text`'s and `_joint_text`'s: `x,y,theta` at the raw
    stream's own precision, with no quantum of its own. None of the four
    tolerances is a quantum for a pose, inventing one would put a bound in the
    artifact no document states, and it is what keeps the pose out of the
    distance error budget — see the note beside `outer_radius` in
    `_observe`, and docs/lossiness.md Discarded #9.
    """
    if base_pose is None:
        return None, None
    if not isinstance(base_pose, BasePose):
        raise GraphBuildError(
            f"{where} states a base pose of type "
            f"{type(base_pose).__name__}, which is not a reg.types.BasePose. "
            "Three numbers that happen to place a base carry no provenance, and "
            "the provenance is half of what the artifact records about a "
            "room-frame pose."
        )
    source = base_pose.source
    if not isinstance(source, PoseSource):
        raise GraphBuildError(
            f"{where} states base_pose=({base_pose.x!r}, {base_pose.y!r}, "
            f"{base_pose.theta!r}) whose source is {source!r} and not a "
            "reg.types.PoseSource. A room-frame pose whose provenance nobody "
            "stated is what BasePose exists to make impossible; writing the "
            "pose with a NULL base_pose_source is refused by the schema and "
            "dropping the pose instead would make a run whose base drove "
            "indistinguishable from one that recorded none. This is a "
            "could-not-evaluate."
        )
    text = ",".join(
        f"{float(v):.{FLOAT_PRECISION}f}"
        for v in (base_pose.x, base_pose.y, base_pose.theta)
    )
    return text, source.value


def _frame_base(frame: StateFrame, where: str) -> BaseFrame:
    """The frame this run's geometry is measured in, for one stream frame.

    `ORIGIN_FRAME` for a frame that states no pose — the mounting fact every
    fixture in this repository has, and the reason `grep ORIGIN_FRAME` is the
    list of places this project assumes a base that does not move.

    For a frame that states one, the pose it states, as a `BaseFrame`. It is a
    *frame* and deliberately not the `BasePose` itself, for
    `reg.kinematics.BaseFrame`'s reason: Layer A may not import a room-frame
    pose, so the pose is converted here — in `reg.graph`, which is where the
    world already is — and what crosses into `link_polygons` and
    `outer_envelope` is the frame the caller is asking the question in. The
    provenance does not cross with it and does not need to: it stays on the
    `robot_config` row beside the pose, where `reg.store.config_base_pose` reads
    it off the thing it is a provenance of, and every edge that rests on that row
    is Layer B whichever `PoseSource` it names (docs/sufficiency.md §5.6).
    """
    if frame.base_pose is None:
        return ORIGIN_FRAME
    _pose_columns(frame.base_pose, where)  # refuse a pose with no provenance
    pose = frame.base_pose
    return BaseFrame(x=pose.x, y=pose.y, theta=pose.theta)


def _place(geometry: BaseGeometry, base: BaseFrame) -> BaseGeometry:
    """A body-frame region rigidly placed at `base`. The room-frame envelope.

    docs/mobile-base.md §2, third row of its table: the room-frame envelope *is*
    the body-frame set transformed by the pose, and it is Layer B because it
    inherits whatever supplied the pose. `compute_envelope` takes no frame and
    must not — it is Layer A and a frame argument on it would be a room-frame
    pose reaching Layer A through the door `reg.kinematics.BaseFrame` refuses —
    so the placement happens here, on the answer, rather than inside the
    computation.

    A rigid transform and nothing else: rotation by `theta` about the body
    origin then translation by `(x, y)`, which is `forward_kinematics`' own
    convention for the same three numbers, so the placed envelope and the placed
    links agree about where the robot is. Distances and areas are invariant under
    it, which is why `outer_area` and `outer_radius` are the same numbers about
    the placed centre as about the origin.

    `ORIGIN_FRAME` short-circuits rather than transforming by the identity. The
    identity matrix would rebuild every coordinate through a multiply-add and
    return a polygon that is the same region and not the same bytes, and every
    fixed-base artifact in this repository would move for a run in which nothing
    happened.
    """
    if base == ORIGIN_FRAME:
        return geometry
    cos, sin = float(np.cos(base.theta)), float(np.sin(base.theta))
    return affine_transform(geometry, (cos, -sin, sin, cos, base.x, base.y))


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
        outer_area: float,
        outer_radius: float,
        q_text: str,
        qd_text: str,
        base_pose: BasePose | None,
    ) -> None:
        self._conn = conn
        self._t = t
        self._envelope = envelope
        self._envelope_digest = envelope_digest
        self._horizon = horizon
        #: The other side of the bracket (issue #82): the horizon-limited outer
        #: reachable set for this frame, as its area and its radius. The region
        #: itself is not carried — it is recomputable from the config and the
        #: horizon this frame already names, and a polygon a frame would undo the
        #: retention work the incremental rule exists for.
        self._outer_area = outer_area
        self._outer_radius = outer_radius
        self._q_text = q_text
        self._qd_text = qd_text
        #: Where the base was, as the two columns `robot_config` holds, or two
        #: `None`s for a frame that states none (issue #191). Resolved on
        #: construction because the id below is derived from it, and a refusal
        #: for a pose with no provenance belongs before any row is written.
        self._pose_text, self._pose_source_text = _pose_columns(
            base_pose, f"the frame at t={t}"
        )
        self._envelope_id = "env_" + _digest(
            ENVELOPE_SOURCE, f"{horizon:.9f}", envelope_digest
        )
        #: AND THE POSE IS PART OF THE CONFIGURATION'S IDENTITY. A vehicle
        #: driving with a frozen arm has the same `q` and `qd` at every frame
        #: and is in a different place at each of them, so hashing the joints
        #: alone would give every one of those frames the same `config_id` —
        #: and `reg.store` refuses the second write as a content clash, which
        #: is the good outcome; the bad one is two frames' evidence merging
        #: into a row about neither. Omitted entirely when there is no pose, so
        #: every fixed-base artifact keeps the ids it had.
        self._config_id = "cfg_" + _digest(
            q_text,
            qd_text,
            *(
                ()
                if self._pose_text is None
                else (self._pose_text, str(self._pose_source_text))
            ),
        )
        #: GEOMETRY_RETENTION's posed clause (issue #191), and it is set here
        #: rather than called for by the loop. `keep_geometry()` also *retains
        #: the row*, which is right for a transition and wrong for this: a
        #: posed frame that anchors nothing is still a frame `ENVELOPE_RETENTION`
        #: keeps no node for, and forcing one would put a row on every frame of
        #: every mobile run — the linear-in, linear-out shape issue #29 exists
        #: to remove. What the rule requires is narrower and is exactly this: if
        #: this frame's row is written *at all*, it carries its polygon, because
        #: `envelope_at` cannot recompute one for a configuration that states a
        #: pose.
        self._keep_geometry = self._pose_text is not None
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
    def posed(self) -> bool:
        """Whether this frame's configuration states a room-frame base pose.

        What it decides, in one place so the two decisions cannot drift: the
        polygon is retained (`GEOMETRY_RETENTION`'s posed clause) and the
        `HAS_ENVELOPE` edge over this frame is Layer **B**. Both follow from the
        same fact and neither is a property of the run's `Limits`.
        """
        return self._pose_text is not None

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
        # GEOMETRY_RETENTION, the posed clause, asserted where the row is made
        # (issue #191). Unreachable while the constructor sets `_keep_geometry`
        # from the pose — which is the point: a rule stated in `meta` that
        # nothing checks is a rule the next change can quietly stop honouring,
        # and the row this would write is one `envelope_at` refuses to read and
        # nothing in the file can recover. A could-not-evaluate at write time is
        # cheaper than one at every read.
        if self.posed and not self._keep_geometry:
            raise GraphBuildError(
                f"the envelope row for the frame at t={self._t} would be "
                f"written with a NULL geometry_wkb, and its configuration "
                f"{self._config_id!r} states base_pose={self._pose_text!r}. "
                "Every term of the recomputation that NULL promises is "
                "body-frame, so reg.graph.envelope_at refuses such a row rather "
                "than handing back the region a robot at the origin could "
                "reach — which would leave the polygon recoverable from "
                "nothing. GEOMETRY_RETENTION keeps the geometry on every frame "
                "whose configuration states a pose, and this row would break "
                "the rule this artifact's own meta table states."
            )
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
            outer_area=self._outer_area,
            outer_radius=self._outer_radius,
        )

    def config(self) -> str:
        """The `RobotConfig` row for this frame, with the base pose it states.

        **The pose is written from the frame, and `None` only when the frame
        states none** (issue #191). Until this issue the two columns were
        `None` unconditionally and `build` refused a posed stream outright,
        because writing one would have turned a run whose base drove into an
        artifact saying *no base pose was recorded* — the same row count, every
        check downstream green (issue #177). The refusal is gone because the
        thing it stood in for is here.

        `None` is still not the origin (issue #166). It says *nobody recorded
        where the base was*, on the same terms `base_vel=None` says it, and for
        a run whose base was bolted the mounting fact is `meta[base_frame]` —
        written once, because it is a fact about the run and not a per-frame
        estimate. The two are exclusive and `reg.store.insert_robot_config`
        refuses an artifact claiming both: `_write_provenance` writes no
        `meta[base_frame]` for a run that states poses.

        A pose with no `PoseSource` is a refusal and not a `NULL` — see
        `_pose_columns`, which is where that decision is made and where the
        message names the frame.
        """
        return store.insert_robot_config(
            self._conn,
            self._config_id,
            self._q_text,
            self._qd_text,
            base_pose=self._pose_text,
            base_pose_source=self._pose_source_text,
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
# The occurrence layer
# --------------------------------------------------------------------------


def quantize_occurrence_time(t: float, resolution: float) -> float:
    """An instant rounded to the nearest multiple of `resolution`.

    Deliberately *not* in `reg.tolerances`: that module owns the four constants
    docs/lossiness.md makes normative and this resolution is not one of them
    (`OCCURRENCE_TIME_RESOLUTION_S`). The rounding rule is the same one — nearest
    multiple, `round`'s banker's tie-break — so the invariant the contract's
    quantizers are chosen for holds here too: two instants more than one
    resolution apart cannot land on the same occurrence timestamp.

    Raises:
        GraphBuildError: `resolution` is not finite and positive. There is no
            fallback: a zero or negative resolution has no nearest multiple, and
            substituting one would put timestamps in the artifact at a
            granularity nobody asked for and nothing records.
    """
    resolution = float(resolution)
    if not np.isfinite(resolution) or resolution <= 0.0:
        raise GraphBuildError(
            f"occurrence_resolution_s={resolution!r}. A timestamp resolution has "
            "to be finite and positive to have a nearest multiple. This is the "
            "parameter the resolution curve varies, so it is stated by the "
            "caller and never inferred."
        )
    t = float(t)
    if not np.isfinite(t):
        raise GraphBuildError(
            f"an occurrence at t={t!r} cannot be timestamped. A non-finite "
            "instant has no place in the run, and rounding it would produce a "
            "timestamp no comparison downstream can reject."
        )
    return round(t / resolution) * resolution


def recorder_version(
    *, horizon: float, n_samples: int, seed: int, substep_dt: float
) -> str:
    """The **recorder's** build and envelope parameters. Not DSSAD's `R157SWIN`.

    THE NAME IS THE FIX (issue #109). This value was called `sw_version` and the
    schema comment in `reg.store` presented it as UN R157's **R157SWIN**. It is
    not that element and cannot be. R157SWIN identifies *the automated driving
    system whose behaviour is under investigation*, so that an occurrence can be
    attributed to the build that produced the behaviour. This returns the version
    of `reg` — the evidence tool that was *watching* — plus a digest over the
    envelope parameters. Those are two different pieces of software, and offering
    one where the regulation asks for the other is worse than offering nothing: a
    column that reads as satisfied is not looked at twice.

    Nothing in this prototype has a policy version to bind. The simulator has no
    policy vendor and `reg.declare.Declaration` carries no version field, so the
    element is recorded as **not implemented** — in the schema comment, in
    `OCCURRENCE_RETENTION` so the artifact itself says so, and in
    `docs/prior-art.md` §9. Filling it with a plausible string would be the
    invented default CLAUDE.md forbids, one layer up from a parameter.

    What the value *is* good for stands unchanged, and is why it is kept rather
    than dropped: the same code with a different horizon computes a different
    envelope and therefore a different set of `envelope_entered` occurrences, so
    an occurrence is interpretable only beside the parameters that produced it.

    A digest rather than the parameters spelled out, because the parameters are
    already in `meta` in full and an occurrence row is not the place to keep a
    second copy of them (docs/lossiness.md Discarded #6, one layer up). The
    digest is what makes the two checkable against each other: an artifact whose
    occurrences carry a stamp its own `meta` does not reproduce is one whose
    events and whose parameters came from different runs.
    """
    return "reg-" + __version__ + "+env-" + _digest(
        _float_text(horizon),
        str(int(n_samples)),
        str(int(seed)),
        _float_text(substep_dt),
    )[:8]


class _OccurrenceLog:
    """Emits the occurrence layer as the build walks the stream, in order.

    Holds exactly two pieces of state, and both are the minimum for the rule:
    `_seq`, so two events inside one timestamp quantum stay two rows, and the
    running closest approach per entity, which cannot be emitted until the run
    ends because "the closest" is a fact about the whole run.

    Everything else it needs — which relationships are open, when they began — is
    already the builder's state, so it is told about transitions rather than
    working them out a second time. A second implementation of "did this
    relationship begin here" would be a second answer to it.
    """

    def __init__(
        self, conn, *, resolution: float, stamp: str, identity: RunIdentity
    ) -> None:
        # Validated here rather than at the first emission: a run with no
        # occurrences at all must still refuse a resolution nobody can round to,
        # or the parameter would be checked only on the runs that happen to
        # contain events.
        quantize_occurrence_time(0.0, resolution)
        self._conn = conn
        self._resolution = float(resolution)
        self._stamp = stamp
        #: The run's declared start. Every occurrence's DSSAD `date` and
        #: absolute timestamp is derived from it, which is what makes the ±1.0 s
        #: resolution above an accuracy on a wall clock rather than on a float.
        #: It is *declared*, never read from a clock here — see `reg.identity`.
        self._identity = identity
        self._seq = 0
        #: entity_id -> (distance bucket, quantized distance, t of the earliest
        #: frame at which that bucket was observed). Keyed on the bucket index
        #: and not on the float, for the reason `_Observation.compare` is:
        #: comparing two roundings of a float decides whether a row is written.
        self._closest: dict[str, tuple[int, float, float]] = {}
        #: Whether the verdict stream has passivated the enforcer and not yet
        #: resumed. Derived from the verdicts alone — see `verdict_recorded` —
        #: because the enforcer is not here and a second source for it would be a
        #: second answer to "was the robot stopped at t".
        self._passivated = False

    @property
    def count(self) -> int:
        """How many occurrences have been emitted. Zero is a legitimate answer
        only before `run_began`; every run has at least two."""
        return self._seq

    def _emit(
        self,
        occurrence_type: str,
        *,
        t: float,
        entity_id: str | None = None,
        value: float | None = None,
    ) -> None:
        reason = OCCURRENCE_REASONS.get(occurrence_type)
        if reason is None:  # pragma: no cover - the vocabulary is checked in CI
            raise GraphBuildError(
                f"no reason is stated for occurrence type {occurrence_type!r}. "
                "DSSAD records a reason beside every flag, and inventing one "
                "here would put prose in the artifact that nobody wrote down."
            )
        seq = self._seq
        self._seq += 1
        t_q = quantize_occurrence_time(t, self._resolution)
        occurrence_id = "occ_" + _digest(
            str(seq),
            occurrence_type,
            "" if entity_id is None else entity_id,
            _float_text(t_q),
            "" if value is None else _float_text(value),
        )
        store.insert_occurrence(
            self._conn,
            occurrence_id,
            seq=seq,
            occurrence_type=occurrence_type,
            reason=reason,
            t=t_q,
            # Derived from the *quantized* instant, not the raw one, so the
            # three timestamp columns on a row all name the same moment. Rounding
            # `t` to ±1.0 s and then placing the row on the wall clock from the
            # unrounded value would give one occurrence two answers to "when",
            # differing by up to half a quantum, and a reader comparing the
            # artifact against another log in the cell would be comparing the
            # wrong one.
            date=self._identity.date(t_q),
            t_utc=self._identity.timestamp_utc(t_q),
            entity_id=entity_id,
            value=value,
            recorder_version=self._stamp,
        )

    def run_began(self, t: float) -> None:
        self._emit("run_began", t=t)

    def run_ended(self, t: float) -> None:
        self._emit("run_ended", t=t)

    def relationship_began(self, edge_type: str, entity_id: str, t: float) -> None:
        """A relationship that was not holding now holds. Ignores the rest.

        `edge_type not in OCCURRENCE_MATERIAL_EDGES` is the rule, not an
        oversight: `SEPARATION` opens whenever a distance crosses a quantum, and
        an occurrence there would be one per frame for a walking human.
        """
        pair = OCCURRENCE_MATERIAL_EDGES.get(edge_type)
        if pair is not None:
            self._emit(pair[0], t=t, entity_id=entity_id)

    def relationship_ended(self, edge_type: str, entity_id: str, t: float) -> None:
        """A relationship that was holding no longer does.

        `t` is the last instant it *was* observed to hold — the closing edge's
        own `t_end` — so the two layers name the same instant for the same event
        and a reader comparing them is not comparing two conventions.
        """
        pair = OCCURRENCE_MATERIAL_EDGES.get(edge_type)
        if pair is not None:
            self._emit(pair[1], t=t, entity_id=entity_id)

    def separation_observed(
        self, entity_id: str, *, bucket: int, distance: float, t: float
    ) -> None:
        """One frame's separation to one entity. Emits nothing; tracks the least.

        Strictly less than, so the *earliest* frame attaining the minimum wins.
        That matters because the timestamp is the answer to "when was the closest
        approach", and a run that sits at its minimum for a second would
        otherwise report whichever frame happened to be read last.
        """
        current = self._closest.get(entity_id)
        if current is None or bucket < current[0]:
            self._closest[entity_id] = (int(bucket), float(distance), float(t))

    def verdict_recorded(self, verdict: Verdict) -> None:
        """One verdict's entry in the event layer, or nothing. Layer A.

        The mapping is `OCCURRENCE_VERDICT_EVENTS` plus two events that are not
        properties of a single verdict:

        * **escalation_failed** — a SAFE_STATE whose fault is the escalation
          failure. It is recorded every time, unlike the plain safe state,
          because each one is a distinct declaration that arrived when an
          `escalate` was obliged.
        * **reintegrated** — a PERMIT or a CLAMP arriving while this log believes
          the enforcer is passivated. `reg.enforce.Enforcer.adjudicate` returns
          SAFE_STATE for every action for as long as it is passivated, so an
          action that came back permitted or clamped is proof that a fresh
          declaration and an acknowledgment cleared it. Derived rather than
          reported: the enforcer is not here, and the verdict stream is the
          evidence a reader would have to work from too.

        A SAFE_STATE emitted while already passivated writes nothing. That is
        `reg.enforce`'s *continuation* — a verdict reporting the passivation it
        is already in rather than raising a new fault — and one row per frame of
        a robot that is not moving is exactly the per-frame cost this layer
        exists to escape. A VETO, a CLAMP and an escalation failure each write
        one every time, because each is a decision about a *distinct* record or
        commanded action and collapsing a run of them would lose which
        declarations were refused and which actions were bounded.
        """
        outcome = str(verdict.outcome)
        fault = None if verdict.fault is None else str(verdict.fault)
        t = float(verdict.t)

        if self._passivated and outcome in ("PERMIT", "CLAMP"):
            self._emit("reintegrated", t=t)
            self._passivated = False

        if outcome == "SAFE_STATE" and fault == "escalation_failure":
            self._emit("escalation_failed", t=t)
        elif outcome == "SAFE_STATE":
            if not self._passivated:
                self._emit("safe_state_entered", t=t)
        else:
            event = OCCURRENCE_VERDICT_EVENTS.get(outcome)
            if event is not None:
                self._emit(event, t=t)

        # Read off the taxonomy rather than off the outcome: which faults stop
        # the robot is `reg.enforce`'s decision and is stated there in one line,
        # and a second copy of it here would be a second answer to it.
        if fault is not None and fault in PASSIVATING_FAULTS:
            self._passivated = True

    def closest_approaches(self) -> None:
        """One `closest_approach` per entity observed, in first-seen order.

        Emitted at the end because it is the only occurrence here that is a fact
        about the whole run rather than about an instant in it. An entity with no
        separation observed at all gets no row — that is the entity set being
        empty, not a separation of zero.
        """
        for entity_id, (_, distance, t) in self._closest.items():
            self._emit("closest_approach", t=t, entity_id=entity_id, value=distance)


# --------------------------------------------------------------------------
# The attestation layer: the records, their regions, and the four edges.
# --------------------------------------------------------------------------


def _record_id(record: Declaration | Verdict) -> str:
    return (
        record.declaration_id
        if isinstance(record, Declaration)
        else record.verdict_id
    )


def _check_link(
    record: Declaration | Verdict, previous: Declaration | Verdict | None
) -> None:
    """Refuse a record that does not link to the one before it. No repair.

    The `FOLLOWS` edge asserts that one record commits to another, and it is only
    true if the successor's `prev_hash` *is* the predecessor's chain hash. So it
    is checked against `reg.chain.chain_hash` before the edge is written, and a
    break is a refusal of the whole build.

    Two things this deliberately does not do. It does not touch the `mac` — the
    hash it computes is over the record as it stands, MAC included, so a record
    whose MAC was altered breaks its successor's link and is *caught* here rather
    than repaired. And it writes nothing derived into the artifact: the chain
    hash is recomputed to check a claim and then discarded, because storing it
    would put a value in the file that a reader would have to trust instead of
    recompute.

    Raises:
        GraphBuildError: the first record of a chain does not link to
            `GENESIS_HASH`, or a later one does not link to its predecessor.
            Writing the edges anyway would produce a chain that walks cleanly
            over a break, which is the one thing `verify_chain` must never be
            able to do.
    """
    kind = type(record).__name__
    if previous is None:
        if record.prev_hash != GENESIS_HASH:
            raise GraphBuildError(
                f"the first {kind} in the stream, {_record_id(record)!r}, links "
                f"to prev_hash={record.prev_hash!r} and not to the genesis hash. "
                "It claims a predecessor this artifact does not hold, so the "
                "chain stored here would begin mid-way with nothing saying so — "
                "and a verifier walking it would report an unbroken chain over "
                "records it never saw."
            )
        return
    expected = chain_hash(previous, previous.prev_hash)
    if record.prev_hash != expected:
        raise GraphBuildError(
            f"{kind} {_record_id(record)!r} carries prev_hash="
            f"{record.prev_hash!r}, but the chain hash of its predecessor "
            f"{_record_id(previous)!r} is {expected!r}. These two records are not "
            "consecutive links of one chain: either the stream was assembled out "
            "of order or from two runs, or a record between them is missing, or "
            "one of them has been altered since it was signed. A FOLLOWS edge "
            "written across that is an assertion nobody checked."
        )


def _attestation_envelope(
    conn,
    geometry: BaseGeometry,
    *,
    source: str,
    horizon: float | None,
) -> str:
    """The `Envelope` row for a region a record names. Returns its id.

    The geometry is **always stored**, and neither simplified nor quantized on
    the way in. `GEOMETRY_RETENTION` discards a polygon only where the artifact
    can recompute it from a `robot_config` it holds; a bound that came from a
    policy is not a function of any configuration in this file, so discarding it
    would not be a discard but a deletion. Simplifying it would be worse — the
    stored region would no longer be the region the record's MAC covers.

    Two records naming the same region share one row: the id is a content hash,
    so the five identical declarations of `declared_violation` produce one
    envelope row and five `DECLARED` edges pointing at it.
    """
    digest = envelope_hash(geometry)
    envelope_id = "env_" + _digest(
        source, "" if horizon is None else f"{horizon:.9f}", digest
    )
    return store.insert_envelope(
        conn,
        envelope_id,
        envelope_hash=digest,
        area=quantize_area(geometry.area),
        geometry=geometry,
        config_id=None,
        horizon=horizon,
        source=source,
        # A declared region and a clamped bound are not reachable sets, so
        # neither has an outer approximation. `insert_envelope` refuses a number
        # here rather than accepting an invented one.
        outer_area=None,
        outer_radius=None,
    )


def _write_attestation(
    conn, records: AttestationRecords, occurrences: _OccurrenceLog
) -> None:
    """The record tables, the regions they name, and the four edges.

    Declarations first, and not for tidiness: `reg.store.insert_verdict` refuses
    a verdict naming a declaration the artifact does not hold, so the order is
    what turns "this verdict adjudicated something not in the file" from a
    dangling edge into a refusal.

    Edge times come from the records and are not quantized — see the module
    header.
    """
    previous_declaration: Declaration | None = None
    for declaration in records.declarations:
        _check_link(declaration, previous_declaration)
        store.insert_declaration(conn, declaration)
        envelope_id = _attestation_envelope(
            conn,
            declaration.envelope(),
            source=DECLARED_ENVELOPE_SOURCE,
            horizon=declaration.horizon,
        )
        # The interval is the claim's own validity window: what the policy said
        # it would do, for exactly as long as it said the statement was good
        # for. That is what `declared_bound(t)` reads (docs/plan.md Phase 7,
        # query 5), and it is why a stale declaration is answerable from the
        # artifact rather than only from the verdict that caught it.
        store.open_edge(
            conn,
            "DECLARED",
            declaration.declaration_id,
            envelope_id,
            declaration.t_issued,
            t_end=declaration.t_issued + declaration.horizon,
        )
        if previous_declaration is not None:
            _open_follows(conn, declaration, previous_declaration, "Declaration")
        previous_declaration = declaration

    previous_verdict: Verdict | None = None
    for verdict in records.verdicts:
        _check_link(verdict, previous_verdict)
        store.insert_verdict(conn, verdict)

        # One ADJUDICATED edge per verdict, at the instant of the commanded
        # action. **Not one per declaration** — see ATTESTATION_RETENTION and
        # `reg.enforce`'s module header: on `declared_violation` a single
        # declaration is adjudicated PERMIT dozens of times and then CLAMP, and
        # collapsing that would destroy the ability to say when the violation
        # began.
        if verdict.declaration_id is not None:
            store.open_edge(
                conn,
                "ADJUDICATED",
                verdict.verdict_id,
                verdict.declaration_id,
                verdict.t,
            )

        clamped = verdict.envelope()
        if clamped is not None:
            store.open_edge(
                conn,
                "ENFORCED",
                verdict.verdict_id,
                _attestation_envelope(
                    conn,
                    clamped,
                    source=CLAMPED_ENVELOPE_SOURCE,
                    # The Verdict record states no horizon for the bound it
                    # applied, and there is none to be had: it is the region one
                    # action was held inside, not a window. NULL is that silence
                    # carried through rather than a number invented here.
                    horizon=None,
                ),
                verdict.t,
            )

        if previous_verdict is not None:
            _open_follows(conn, verdict, previous_verdict, "Verdict")
        previous_verdict = verdict

        occurrences.verdict_recorded(verdict)


def _open_follows(
    conn,
    record: Declaration | Verdict,
    previous: Declaration | Verdict,
    kind: str,
) -> None:
    """One chain link, from a record to the record it commits to.

    The interval is the span between the two records, so a query over a time
    window sees the links that were made inside it. `min`/`max` rather than the
    pair in order because the chain's order is `seq` and `prev_hash` and not the
    clock: a verdict raised against a declaration issued earlier can carry the
    earlier timestamp, and an interval that ran backwards would drop out of every
    timeline query instead of erroring.
    """
    a = _record_time(record)
    b = _record_time(previous)
    store.open_edge(
        conn,
        "FOLLOWS",
        _record_id(record),
        _record_id(previous),
        min(a, b),
        t_end=max(a, b),
        src_kind=kind,
        dst_kind=kind,
    )


def _record_time(record: Declaration | Verdict) -> float:
    return float(
        record.t_issued if isinstance(record, Declaration) else record.t
    )


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


def _refuse_a_stream_whose_pose_recording_is_partial(
    frames: tuple[StateFrame, ...], csv_path: str | os.PathLike[str]
) -> bool:
    """All the frames state a base pose, or none do. Anything else is refused.

    Returns whether this run's base pose is recorded — which is what decides
    `meta[base_frame]`, and it is returned rather than recomputed by the caller
    so that the check and the decision cannot disagree.

    **This replaces the refusal issue #177 put here, and it is a different
    check.** That one said *this builder cannot carry a pose*, which stopped
    being true with issue #191: the pose now reaches `robot_config` and a run
    whose base moved retains its geometry, so a posed stream builds. What cannot
    be carried is a stream that records a pose on some frames and not others.

    Whole-run, because the two things a reader places a region against are
    whole-run facts. `meta[base_frame]` says the base was bolted *for the run*
    and `reg.store.insert_robot_config` refuses an artifact that states it beside
    any posed row, so a mixed stream produces a file with no `base_frame` at all
    — and then every unposed row in it names no centre, `envelope_frame` reports
    a could-not-evaluate for each, and half the artifact is unreadable while
    parsing perfectly. That is not a partial answer; it is an artifact whose
    silences mean two different things in the same file.

    It cannot arrive from anything in this repository — `reg.scenarios.Scenario`
    either drives for the whole run or is a fixed-base scenario (`Scenario.drives`,
    issue #177) — which is why it is a refusal rather than a repair: there is no
    honest way to fill in a pose nobody recorded, and dropping the ones that were
    recorded would be the issue #177 failure with extra steps.
    """
    posed = [i for i, frame in enumerate(frames) if frame.base_pose is not None]
    if not posed:
        return False
    if len(posed) == len(frames):
        return True
    missing = next(i for i in range(len(frames)) if frames[i].base_pose is None)
    raise GraphBuildError(
        f"{csv_path}: {len(posed)} of {len(frames)} frame(s) state a base pose "
        f"(first at frame {posed[0]}, t={frames[posed[0]].t}) and the rest do "
        f"not (first at frame {missing}, t={frames[missing].t}). Where the base "
        "was is a whole-run fact in this schema: an artifact states "
        f"meta[{store.META_BASE_FRAME!r}] for a base that was bolted for the "
        "run, or a base_pose on every configuration for one that drove, and "
        "reg.store.insert_robot_config refuses a file that claims both. Building "
        "this would produce an artifact with neither, in which every unposed "
        "row's outer_radius is a radius about a centre nothing names. Refusing "
        "instead: a pose recording that stopped part way through is a "
        "could-not-evaluate about the frames it stopped on, not a run whose "
        "base went back to the origin."
    )


def _refuse_a_posed_envelope_row_with_no_geometry(
    conn, csv_path: str | os.PathLike[str]
) -> None:
    """`GEOMETRY_RETENTION`'s posed clause, checked against the file it describes.

    The rule text lands in `meta` and says the polygon is kept on every frame
    whose configuration states a pose. This is what makes that a *check* rather
    than a claim: it asks the artifact, after every row is written, whether any
    `envelope` row states a pose and carries a NULL `geometry_wkb`, and refuses
    the build if one does.

    Such a row is unrecoverable, and quietly. `envelope_at` refuses to recompute
    a posed configuration — every term of the recomputation is body-frame — so
    the polygon is neither in the file nor derivable from it, and the row still
    parses, still carries its hash, area, horizon and source, and still answers
    every scalar question. The artifact would look complete and hold a region
    nobody can get back.

    Written as one query over the file rather than as a counter kept during the
    loop, deliberately: a counter checks that the builder did what the builder
    thinks it did, and this checks what the bytes say. Its negative is
    `tests/test_graph.py::test_a_posed_envelope_row_with_no_geometry_is_refused`,
    which hands it exactly that row.
    """
    offending = conn.execute(
        """
        SELECT n.node_id AS envelope_id,
               c.node_id AS config_id,
               rc.base_pose AS base_pose
        FROM envelope e
        JOIN node n ON n.node_key = e.envelope_key
        JOIN robot_config rc ON rc.config_key = e.config_key
        JOIN node c ON c.node_key = rc.config_key
        WHERE e.geometry_wkb IS NULL AND rc.base_pose IS NOT NULL
        ORDER BY e.envelope_key
        """
    ).fetchall()
    if not offending:
        return
    first = offending[0]
    raise GraphBuildError(
        f"{csv_path}: {len(offending)} envelope row(s) state a base pose and "
        f"carry no geometry (first: envelope {str(first['envelope_id'])!r} over "
        f"config {str(first['config_id'])!r}, "
        f"base_pose={str(first['base_pose'])!r}). A NULL geometry_wkb is a "
        "promise that the polygon can be recomputed from the configuration and "
        "the envelope parameters in meta, and every one of those terms is "
        "body-frame: for a configuration that states a pose the recomputation "
        "would return the region a robot at the origin could reach, so "
        "reg.graph.envelope_at refuses it and the region is recoverable from "
        f"nothing. meta[{META_GEOMETRY_RETENTION!r}] states the rule this "
        "would break; the artifact is not written."
    )


def build(
    csv_path: str | os.PathLike[str],
    out_path: str | os.PathLike[str],
    limits: Limits,
    *,
    identity: RunIdentity,
    human_radius: float,
    horizon: float = ENVELOPE_HORIZON,
    n_samples: int = ENVELOPE_N_SAMPLES,
    seed: int = ENVELOPE_SEED,
    substep_dt: float = SUBSTEP_DT,
    occurrence_resolution_s: float = OCCURRENCE_TIME_RESOLUTION_S,
    records: AttestationRecords | None = None,
    commitment: Callable[[ChainHeads], Commitment] | None = None,
) -> BuildResult:
    """Turn a raw CSV stream into a SQLite evidence graph. Overwrites `out_path`.

    Args:
        csv_path: a stream written by `reg.stream.write_frames`.
        out_path: the artifact to write. Replaced if it exists.
        limits: the robot's kinematic and actuation bounds — Layer A, and the
            only thing besides `frame.proprio()` that reaches the envelope.
        identity: **required, and there is no default** (issue #83). The run's
            declared UTC start, the unit that ran it and the operator
            responsible — the three facts that make the artifact locatable and
            correlatable, and none of which is recoverable from the file
            afterwards. The start is *declared* by the caller and never read
            from a clock here, so determinism is preserved exactly: same seed
            **and** same declared start, same bytes. Every occurrence's DSSAD
            `date` and absolute timestamp is derived from it.
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
        occurrence_resolution_s: the resolution every occurrence timestamp is
            rounded to, in seconds. Defaults to DSSAD's stated ±1.0 s
            (`OCCURRENCE_TIME_RESOLUTION_S`) and is recorded in `meta` either
            way. It is an argument rather than a constant because measuring what
            a resolution costs is the point of the layer (docs/retention.md,
            "What replaces it"); it does **not** touch the edge layer, whose
            resolution is `TIME_TOL_S` and is not a parameter of anything.
        records: the run's signed declarations and verdicts, or `None` for a
            build that was given none. The two are different facts and the
            artifact records which one it holds (`ATTESTATION_RETENTION`): an
            empty `AttestationRecords` is a run that produced nothing, `None` is
            a build that was not asked to store anything, and an empty
            `declaration` table on its own does not say which. The record stream
            is stored verbatim — see `_write_attestation` and `_check_link`.
        commitment: a `reg.commit` supplier — anything callable with the two
            chain heads that returns a `Commitment` — or `None` for a build
            given no supplier. **`None` does not silently produce an
            uncommitted chain**: `meta[commitment]` is written on every build
            and says `none` in so many words, because silence must not read as
            commitment. Supplying one without `records` is refused: there is no
            chain to commit to, and a commitment to two genesis hashes would
            verify and mean nothing.

    Returns:
        A `BuildResult` with the row counts and the artifact's size.
        `nodes["Envelope"]` counts envelope *rows*, one per frame the artifact
        retains (`ENVELOPE_RETENTION`) and **not** one per frame nor one per
        material change; most of them carry no polygon (`GEOMETRY_RETENTION`),
        so it is not a count of stored geometries either.
        `nodes["Occurrence"]` counts the event layer (`OCCURRENCE_RETENTION`),
        which is additive: no edge row exists or fails to exist because of it.
        `addressable_instants` is how many distinct instants the run's frames
        quantized onto (`TIME_BASE_DOMAIN`); it equals `frames` for a stream
        sampled at or below `TIME_BASE_MAX_RATE_HZ` and is smaller above it. A
        stream sampled faster is built, not refused — see `TIME_BASE_DOMAIN` —
        and the artifact says which case it is.

    Raises:
        GraphBuildError: the stream could not be understood — too short, a
            non-uniform frame period, or an obstacle that moved — or the record
            stream is not one unbroken chain. Each is a could-not-evaluate, and
            none of them writes a usable artifact.
    """
    if records is not None and not isinstance(records, AttestationRecords):
        raise GraphBuildError(
            f"records must be an AttestationRecords or None, got "
            f"{type(records).__name__}. `None` means this build was given no "
            "record stream; a run that produced none is AttestationRecords((), "
            "()), and the artifact says which of the two it holds."
        )
    if not isinstance(identity, RunIdentity):
        raise GraphBuildError(
            f"identity must be a RunIdentity, got {type(identity).__name__}. "
            "The run's declared start, unit and operator have no defaults: an "
            "artifact that cannot say which robot it describes, or when, cannot "
            "be handed to anyone, and neither fact is recoverable from the file "
            "afterwards."
        )
    if commitment is not None and records is None:
        raise GraphBuildError(
            "a commitment supplier was given and no record stream was. There is "
            "no chain in this build to commit to, and committing to two genesis "
            "hashes would produce a signature that verifies and says nothing."
        )
    if commitment is not None and not callable(commitment):
        raise GraphBuildError(
            f"commitment must be callable with the chain heads, got "
            f"{type(commitment).__name__}. The interface is "
            "`(ChainHeads) -> Commitment` — see reg.commit.WitnessCommitter, "
            "and the RFC 3161 and transparency-log adapters that interface "
            "exists to make cheap."
        )
    frames = tuple(read_frames(csv_path))
    # Whether this run's base pose is recorded, and a refusal if the stream
    # records it on some frames and not others (issue #191). One answer for the
    # whole run: it decides `meta[base_frame]` and the layer of every
    # HAS_ENVELOPE edge below, and both are whole-run facts.
    drives = _refuse_a_stream_whose_pose_recording_is_partial(frames, csv_path)
    period = _frame_period(frames, csv_path)
    # How many distinct instants this run's frames can be addressed at, which is
    # `len(frames)` at or below `TIME_BASE_MAX_RATE_HZ` and fewer above it. Not a
    # refusal — see `TIME_BASE_DOMAIN` for why a fast stream is recorded rather
    # than rejected — but it is written into the artifact and returned to the
    # caller, so nothing downstream has to infer it from the frame period.
    instants = addressable_instants([f.t for f in frames])
    obstacles = _entity_set(frames, csv_path)

    human_radius = float(human_radius)
    if not np.isfinite(human_radius) or human_radius <= 0.0:
        raise GraphBuildError(
            f"human_radius={human_radius!r}. A human of zero or negative extent "
            "can never contact anything, so every contact question in the "
            "artifact would answer 'no' for a reason nobody wrote down."
        )

    stamp = recorder_version(
        horizon=horizon, n_samples=n_samples, seed=seed, substep_dt=substep_dt
    )

    # `record_tables` is exactly the fact `meta[attestation_records]` records,
    # and it is stated here rather than always creating the two tables: a build
    # given no record stream used to carry them, and their two automatic
    # indexes, holding nothing (issue #54). Which of the two facts this artifact
    # holds stays in `meta`, where every reader already looks for it.
    conn = store.create(out_path, record_tables=records is not None)
    try:
        _write_provenance(
            conn,
            csv_path=csv_path,
            frames=frames,
            period=period,
            instants=instants,
            limits=limits,
            identity=identity,
            human_radius=human_radius,
            horizon=horizon,
            n_samples=n_samples,
            seed=seed,
            substep_dt=substep_dt,
            occurrence_resolution_s=occurrence_resolution_s,
            stamp=stamp,
            records=records,
            drives=drives,
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

        # The layer every HAS_ENVELOPE edge in this build carries, decided once
        # from the provenance of the limits (issue #84). `Limits` is frozen and
        # one object drives the whole run, so this is a property of the build and
        # not of a frame — an envelope does not become certifiable halfway
        # through. Computed here rather than at the call site so that a build
        # whose limits have no layer decision fails before it writes a row.
        envelope_edge_layer = envelope_layer(limits)
        if drives:
            # ...unless the base drove, and then it is `B` whatever the limits
            # say (issue #191). A HAS_ENVELOPE edge over a posed configuration
            # rests on a room-frame pose, which is Layer B structurally and for
            # which no localizer is an argument (docs/sufficiency.md §5.6), and
            # the region on the far end of the edge is that pose applied to a
            # body-frame set. `reg.store.open_edge` refuses an `A` on such an
            # edge and names the pose; this states the `B` rather than being
            # told about it one row too late, because the refusal is the guard
            # and not the specification. The limits' own provenance cannot
            # loosen this: `B` is the weaker tag and `envelope_layer` returning
            # `B` already agrees with it.
            envelope_edge_layer = "B"

        active: dict[tuple[str, str], _Active] = {}
        has_envelope: _Active | None = None
        previous: _FrameNodes | None = None
        last_frame_id = len(frames) - 1

        # The occurrence layer walks the same loop (issue #35). It is told about
        # transitions the builder has already decided on rather than deciding
        # them again: two implementations of "did this relationship begin here"
        # is two answers to it, and the layers would drift apart on exactly the
        # runs a reader would compare them on.
        occurrences = _OccurrenceLog(
            conn,
            resolution=occurrence_resolution_s,
            stamp=stamp,
            identity=identity,
        )
        occurrences.run_began(quantize_time(frames[0].t))

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
                layer=envelope_edge_layer,
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
                # The occurrence is timestamped at the last instant the
                # relationship held, which is the previous frame and is the
                # closing edge's own `t_end`. `previous is None` cannot happen
                # here — nothing is active before the first frame is read — and
                # the guard is for the type checker rather than for a case.
                if previous is not None:  # pragma: no branch - see above
                    edge_type, entity_id = key
                    occurrences.relationship_ended(edge_type, entity_id, previous.t)
                del active[key]

            # ...and that backward reach is the last thing that can retain the
            # previous frame, so its timeline entry is settled now and not
            # before. Emitted here rather than after this frame's own edges so
            # that edge ids stay in time order.
            if previous is not None:
                envelope_timeline(previous)

            for key, observation in observations.items():
                # The occurrence layer's other input: the running closest
                # approach per entity. Read off the observation the edge layer
                # is about to store, so the two layers cannot disagree about
                # what the smallest separation of the run was.
                if observation.edge_type == "SEPARATION":
                    occurrences.separation_observed(
                        key[1],
                        bucket=int(observation.compare),  # type: ignore[arg-type]
                        distance=float(observation.min_distance),  # type: ignore[arg-type]
                        t=t,
                    )

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
                if current is None:
                    # `current is None` is what makes this the *relationship*
                    # beginning rather than its metric stepping a quantum — the
                    # same distinction GEOMETRY_RETENTION draws one line up, and
                    # the reason an occurrence is not emitted per overlap
                    # quantum.
                    occurrences.relationship_began(
                        observation.edge_type, key[1], t
                    )
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

        # The record layer, after the scene layer and before the two occurrences
        # that are facts about the whole run. Its edges do not participate in the
        # incremental rule at all — a declaration is already coarse, and there is
        # no relationship here to extend — so it is written in one pass rather
        # than woven into the frame loop.
        if records is not None:
            _write_attestation(conn, records, occurrences)

        # A relationship still holding at the last frame gets no `..._left` or
        # `..._ended` occurrence — it did not end, the recording did, and
        # `run_ended` is what says so. `OCCURRENCE_RETENTION` states it in the
        # artifact, because "no contact_ended" would otherwise read as contact
        # continuing after the last frame this run has any evidence about.
        occurrences.closest_approaches()
        occurrences.run_ended(quantize_time(frames[-1].t))

        # GEOMETRY_RETENTION's posed clause, asked of the file rather than of
        # the builder (issue #191). Everything above has run, so every envelope
        # row that will exist exists and every polygon that will be attached is
        # attached; a row that states a pose and holds no geometry now is one
        # nothing downstream can recover.
        _refuse_a_posed_envelope_row_with_no_geometry(conn, csv_path)

        # Last, because a commitment is made at artifact *close*: the heads it
        # signs are recomputed from the records this file actually holds, so
        # every record has to be in it first.
        _write_commitment(conn, commitment)

        conn.commit()
        result = _summarize(
            conn, Path(out_path), len(frames), instants=instants
        )
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

    # Where this frame's regions are measured from: `ORIGIN_FRAME` for a base
    # nobody recorded a pose for, and the pose the frame states for one that
    # drove (issue #191). Nothing below reads `frame.base_pose` again — the
    # `BaseFrame` is what the geometry is placed with and the two `robot_config`
    # columns are what the artifact records, and neither is derived from the
    # other twice.
    base = _frame_base(frame, f"the frame at t={frame.t}")

    # Layer A, first, and blind to everything below. `compute_envelope` takes a
    # ProprioState; the world reaches it through no argument — including the
    # pose, which is why the placement is a second step on the answer and not an
    # argument to the computation (`_place`, docs/mobile-base.md §2).
    envelope = _place(
        simplify_geometry(
            compute_envelope(
                proprio,
                limits,
                horizon=horizon,
                n_samples=n_samples,
                seed=seed,
                substep_dt=substep_dt,
            )
        ),
        base,
    )
    digest = envelope_hash(envelope)

    # ...and the outer approximation of the same instant, Layer A on the same
    # terms (issue #82). Two sets for two jobs: `compute_envelope` above is the
    # region the robot demonstrably swept and is what the graph records as its
    # geometry; this one is the region it provably cannot leave, and only its
    # area and radius are retained. Not simplified — simplification may move a
    # boundary either way, and an outer bound that moved inward would stop being
    # one — and computed on the same `substep_dt` grid the inner one was
    # integrated on, because that is the grid its soundness argument covers.
    #
    # Measured about `ORIGIN_FRAME` even for a base that drove, and that is not
    # an oversight: the two things retained off it are an area and a radius
    # about the base, both invariant under the rigid placement `_place` applies,
    # so placing this set would change nothing but the last bits of two numbers
    # the artifact rounds anyway. What the radius is a radius *about* is the
    # frame the row states — its own `base_pose`, or `meta[base_frame]` — and
    # `envelope_frame` is the reader that says so (issue #166).
    outer = outer_envelope(proprio, limits, horizon, ORIGIN_FRAME, substep_dt)

    # The robot body is deliberately *not* simplified. The error budget in
    # docs/lossiness.md allows one simplified boundary per distance
    # (GEOM_SIMPLIFY_TOL_M + DISTANCE_TOL_M/2 <= DISTANCE_TOL_M), and the entity
    # boundary is already spending it. Simplifying both would put reported
    # distances outside the 1 cm the artifact advertises.
    #
    # AND THE BASE FRAME IS NOT A THIRD TERM IN THAT BUDGET (issue #166). It
    # would be if it were rounded, because the equality above is exact and has
    # no room in it. It is not rounded. The budget's two terms are the two
    # places this builder *rounds a length* — Douglas–Peucker on a stored
    # boundary, and `quantize_distance` on a reported one — and a base frame
    # goes through neither: `_frame_text` writes it at the raw stream's own
    # precision, exactly as `_joint_text` writes `q`, and for the reason stated
    # there. `q` is the precedent and it is a strong one: every distance this
    # artifact reports is computed from geometry built out of `q`, and `q` has
    # never been in the budget, because none of the four tolerances is a quantum
    # for it. The centre is written down *after* `outer_radius` is measured
    # about it, so nothing the artifact reports is computed through the digits;
    # they say what the retained radius is a radius about. Retain a frame with a
    # quantum of its own and this comment stops being true — that is what "no
    # headroom for a third error term" means, and the discipline it asks for is
    # to keep the frame out of the rounding path rather than to shave the
    # budget.
    #
    # AND THE BODY IS PLACED, NOT REBUILT (issue #191). `link_polygons(proprio,
    # limits, base)` would put the same robot in the same place to within float
    # noise; `_place` on the body-frame body puts it there under the *same*
    # transform the envelope above got, which is what keeps `body` inside
    # `envelope` exactly rather than to within an ulp — and at `ORIGIN_FRAME` it
    # is the identity, so every fixed-base artifact in this repository holds the
    # bytes it held before.
    body = _place(unary_union(link_polygons(proprio, limits, ORIGIN_FRAME)), base)

    nodes = _FrameNodes(
        conn,
        t=t,
        envelope=envelope,
        envelope_digest=digest,
        horizon=horizon,
        outer_area=quantize_area(outer.area),
        outer_radius=quantize_distance(outer_radius(outer, ORIGIN_FRAME)),
        q_text=_joint_text(frame.q),
        qd_text=_joint_text(frame.qd),
        base_pose=frame.base_pose,
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
    instants: int,
    limits: Limits,
    identity: RunIdentity,
    human_radius: float,
    horizon: float,
    n_samples: int,
    seed: int,
    substep_dt: float,
    occurrence_resolution_s: float,
    stamp: str,
    records: AttestationRecords | None,
    drives: bool,
) -> None:
    """Everything needed to say what produced this artifact, and nothing else.

    docs/lossiness.md Retained #10: "scenario name, seed, tolerance constants in
    force, and the schema version, once per artifact. Determinism is only
    checkable if the artifact says what produced it."

    Nothing that varies between two runs of the same command may enter here — no
    path, no clock, no hostname. The environment block (issue #200) is not an
    exception to that either: two runs of the same command on one machine record
    the same six strings, and what it deliberately does *not* record is the
    hostname, the path and the user, all of which differ between two checkouts on
    one machine while nothing about the geometry differs. The source stream's own
    provenance block is copied in verbatim, which is where the scenario name and
    the simulator seed come from; if the stream carries none, the key is *absent*
    rather than empty, because "the source said nothing" and "the source said
    nothing useful" are both could-not-evaluate and neither is a default.

    The run start is the one absolute time in the file and it is not an
    exception to that rule (issue #83): it is **declared by the caller**, not
    read from a clock, so two runs of the same command with the same declared
    start still produce identical bytes. That is the same treatment key material
    already gets — a required input rather than an omission — and it is why the
    "no date element" deviation could be closed without giving anything up.
    """
    store.put_meta(conn, "reg_version", __version__)

    # ...and what it ran on (issue #200). `reg_version` says which code computed
    # the geometry; these six say what that code was computing *with*, which is
    # the other half of the retention argument for a discarded polygon: it is a
    # deterministic function of the row and four numbers in meta, and issue #175
    # measured that the function is the platform's. Without them an auditor who
    # recomputes and disagrees cannot tell "wrong machine" from "the geometry
    # moved", and those are opposite findings. Read from the running interpreter
    # by `reg.store.build_environment`, never passed in — see there for the
    # buildinfo this is adopted from, the in-meta placement stated as a
    # deviation from it, and the C library it cannot record.
    for key, value in store.build_environment().items():
        store.put_meta(conn, key, value)

    # Absolute time and identity, first, because they are what tells a reader
    # *which* run everything below belongs to.
    store.put_meta(conn, META_RUN_START, identity.run_start_text)
    store.put_meta(conn, META_UNIT_ID, identity.unit_id)
    store.put_meta(conn, META_OPERATOR_ID, identity.operator_id)

    store.put_meta(conn, "frame_count", str(len(frames)))
    store.put_meta(conn, store.META_FRAME_PERIOD, _float_text(period))
    store.put_meta(conn, "t_first", _float_text(quantize_time(frames[0].t)))
    store.put_meta(conn, "t_last", _float_text(quantize_time(frames[-1].t)))

    # The time base and its domain of validity (issue #77). `instants` is
    # measured off this run's own frame times rather than derived from `period`,
    # because `quantize_time` breaks ties to even and whether a period of exactly
    # `TIME_TOL_S` separates every frame depends on the stream's phase — see
    # `reg.tolerances.addressable_instants`. It is computed once, in `build`, and
    # threaded here and into `BuildResult`: two computations would be two answers
    # to whether the file a caller is holding is inside its own contract.
    store.put_meta(conn, META_TIME_BASE_DOMAIN, TIME_BASE_DOMAIN)
    store.put_meta(conn, META_TIME_BASE_INSTANTS, str(instants))
    store.put_meta(
        conn,
        META_TIME_BASE_RESOLVES,
        TIME_BASE_RESOLVED if instants == len(frames) else TIME_BASE_COLLAPSED,
    )

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

    # The occurrence layer's rule, its resolution and its software stamp. The
    # resolution especially: an occurrence timestamp read without it is a number
    # that looks like a time and is good to nobody knows what, and a reader
    # holding only the file has no other way to find out. The stamp is repeated
    # here so the digest on every occurrence row can be checked against the
    # parameters above rather than taken on faith.
    store.put_meta(conn, META_OCCURRENCE_RETENTION, OCCURRENCE_RETENTION)
    store.put_meta(
        conn, META_OCCURRENCE_RESOLUTION, _float_text(occurrence_resolution_s)
    )
    store.put_meta(conn, META_OCCURRENCE_RECORDER_VERSION, stamp)

    # The attestation layer's rule, and whether this build was given anything to
    # store under it. The counts are written only when it was, so an artifact
    # with no `declaration_count` is one nobody handed a record stream — which is
    # a different fact from a run that produced no records, and the empty table
    # is the same in both cases.
    store.put_meta(conn, META_ATTESTATION_RETENTION, ATTESTATION_RETENTION)
    store.put_meta(
        conn, META_ATTESTATION_RECORDS, "absent" if records is None else "present"
    )
    if records is not None:
        store.put_meta(conn, META_DECLARATION_COUNT, str(len(records.declarations)))
        store.put_meta(conn, META_VERDICT_COUNT, str(len(records.verdicts)))

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
    # ...including the base's, which for every fixture in this repository are
    # the zeros a bolted base states (issue #151). They are written even so: an
    # artifact whose base bounds are absent cannot be told from one whose base
    # was standing still, and that is the distinction the required fields on
    # `Limits` exist to keep.
    store.put_meta(
        conn,
        META_LIMITS_BASE_BOUNDS,
        ",".join(
            _float_text(getattr(limits, name)) for name in Limits.BASE_BOUND_FIELDS
        ),
    )
    # ...and where they came from, which is what every HAS_ENVELOPE edge in this
    # file was tagged from (issue #84). One short string: a reader can tell a run
    # whose speed bound came off a datasheet from one whose speed bound came off
    # a safety scanner, and the layer column already says which without them
    # having to know the difference.
    store.put_meta(conn, META_LIMITS_SOURCE, limits.source.value)

    # Where the base was, once, for the whole run (issue #166) — **and only for a
    # run whose base did not move** (issue #191). Every fixture in this
    # repository is bolted down, so what lands here is `ORIGIN_FRAME` written
    # out: the same mounting fact `grep ORIGIN_FRAME` lists, said in the artifact
    # instead of only in the source. It is what makes every retained
    # `outer_radius` in the file a radius about a centre somebody named; a file
    # missing it is a could-not-evaluate, and `envelope_frame` refuses rather
    # than resolving the absence to the origin.
    #
    # For a run whose frames state a pose the key is **absent**, and that is not
    # an omission: the two are different claims about one run — *the base is
    # bolted here*, a mounting fact, against *the base was there at this
    # instant*, a room-frame estimate that inherits a perceiver — and
    # `reg.store.insert_robot_config` refuses a file making both, because every
    # retained `outer_radius` in it would be a radius about whichever centre the
    # reader picked. `envelope_frame` reads the centre off the row's own
    # `base_pose` there, and `_refuse_a_stream_whose_pose_recording_is_partial`
    # is what guarantees every row has one.
    if not drives:
        store.put_meta(conn, store.META_BASE_FRAME, _frame_text(ORIGIN_FRAME))

    store.put_meta(conn, "human_entity_id", HUMAN_ENTITY_ID)
    store.put_meta(conn, "human_radius_m", _float_text(human_radius))

    comments = read_comments(csv_path)
    if comments:
        store.put_meta(conn, "source_provenance", "\n".join(comments))


def _write_commitment(
    conn, commitment: Callable[[ChainHeads], Commitment] | None
) -> None:
    """Commit the two chain heads at artifact close, or record that nobody did.

    `meta[commitment]` is written on **every** build. That is the whole point of
    the key: an artifact closed with no supplier says `none` in so many words,
    so an absent commitment is a fact a reader is told rather than one they
    infer from a missing key — and `reg.commit.verify_commitment` can then tell
    "this build had no witness" apart from "this file predates the interface",
    which are different things to say to an assessor.

    The heads are recomputed from the records the file holds rather than tracked
    as the build writes them: what a commitment is *for* is being compared
    against the artifact afterwards, and a head carried forward from the writer
    would commit to what the build believed it stored.

    Raises:
        GraphBuildError: the heads could not be computed, or the supplier did
            not return a `Commitment` over the heads it was given. All three are
            refusals that unlink the artifact — an artifact carrying a
            commitment nobody can check is worse than one carrying none, because
            only the second says so.
    """
    if commitment is None:
        store.put_meta(conn, META_COMMITMENT, COMMITMENT_NONE)
        return

    try:
        heads = chain_heads(conn)
    except CommitmentError as exc:
        raise GraphBuildError(
            f"the chain heads could not be computed, so this build has nothing "
            f"to commit to: {exc}"
        ) from None

    made = commitment(heads)
    if not isinstance(made, Commitment):
        raise GraphBuildError(
            f"the commitment supplier returned a {type(made).__name__}, not a "
            "Commitment. The interface is `(ChainHeads) -> Commitment`."
        )
    if made.heads != heads:
        raise GraphBuildError(
            "the commitment supplier returned a commitment over different heads "
            "than it was given. Refusing to record it: a commitment to heads "
            "that are not this artifact's would verify against itself and fail "
            "against the file it is in."
        )

    store.put_meta(conn, META_COMMITMENT, made.scheme)
    store.put_meta(conn, META_COMMITMENT_STATEMENT, COMMITMENT_STATEMENT)
    store.put_meta(conn, META_COMMITMENT_WITNESS, made.witness_id)
    store.put_meta(
        conn, META_COMMITMENT_DECLARATION_HEAD, made.heads.declaration_head
    )
    store.put_meta(conn, META_COMMITMENT_VERDICT_HEAD, made.heads.verdict_head)
    store.put_meta(conn, META_COMMITMENT_SIGNATURE, made.token)


def _summarize(conn, path: Path, frames: int, *, instants: int) -> BuildResult:
    edges = {
        edge_type: int(
            conn.execute(
                "SELECT count(*) AS n FROM edge WHERE type = ?", (edge_type,)
            ).fetchone()["n"]
        )
        for edge_type in store.EDGE_SPECS
    }
    # Through `store.node_counts` rather than a `SELECT count(*)` per table: a
    # build handed no record stream has no `declaration` or `verdict` table to
    # count (issue #54), and the count of rows it wrote to them is 0 either way.
    nodes = store.node_counts(conn)
    return BuildResult(
        path=path,
        frames=frames,
        edges=edges,
        nodes=nodes,
        size_bytes=path.stat().st_size,
        addressable_instants=instants,
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


def _meta_limit_source(conn) -> LimitSource:
    """Where this artifact's limits came from. A refusal if it does not say.

    **A missing key is could-not-evaluate, not `PROPRIOCEPTIVE`** (issue #84).
    An artifact written before provenance was recorded, or one somebody removed
    the key from, does not know whether its bounds were a datasheet limit or an
    ISO/TS 15066 speed cap derived from a perceiver — and a `Limits` reconstructed
    with the clean value would recompute geometry that reads as certifiable
    evidence on the strength of a value nobody wrote. That is the one failure
    this key exists to make visible, so it may not be the failure's own default.
    """
    raw = store.get_meta(conn, META_LIMITS_SOURCE)
    if raw is None:
        raise GraphQueryError(
            f"the artifact has no meta[{META_LIMITS_SOURCE!r}], so it does not "
            "say where the limits its envelopes were computed from came from. "
            "That is a could-not-evaluate and it does not resolve to "
            f"{LimitSource.PROPRIOCEPTIVE.value!r}: bounds derived from a "
            "perceiver (an ISO/TS 15066 speed-and-separation cap on qd_max) "
            "make every envelope here Layer B, and an artifact whose provenance "
            "is unknown must not read as a clean Layer A one (issue #84). The "
            "layer column on the HAS_ENVELOPE edges records what this build "
            "decided; nothing recomputes it."
        )
    try:
        return LimitSource(raw)
    except ValueError as exc:
        raise GraphQueryError(
            f"meta[{META_LIMITS_SOURCE!r}] is {raw!r}, which is not a limit "
            f"source. Known: {[s.value for s in LimitSource]}."
        ) from exc


def _base_bounds_from_meta(conn) -> dict[str, float]:
    """The base's four actuation bounds, as keyword arguments for `Limits`.

    **A missing key is could-not-evaluate, not a base that was standing still**
    (issue #151). Zero is what a bolted-down base *states* — `reg.world.LIMITS`
    writes it — so it is the one value an absent key must not resolve to. Every
    artifact this repository builds today would even be right, which is exactly
    what makes the substitution invisible: an artifact written before this key
    existed, or one somebody deleted the row from, does not know whether its
    base could drive, and a `Limits` reconstructed with zeros would recompute a
    mobile robot's geometry as a bolted one's.

    The value is positional — four numbers in three units — so a value of any
    other length is refused rather than zipped against a shorter field list. A
    partial read would silently reassign `base_omega_max`'s rad/s to
    `base_a_max`'s m/s^2, and nothing downstream carries a unit that could
    notice.
    """
    names = Limits.BASE_BOUND_FIELDS
    values = _floats(
        _meta_required(conn, META_LIMITS_BASE_BOUNDS),
        f"meta[{META_LIMITS_BASE_BOUNDS!r}]",
    )
    if values.shape != (len(names),):
        raise GraphQueryError(
            f"meta[{META_LIMITS_BASE_BOUNDS!r}] holds {values.size} numbers and "
            f"the base states {len(names)}: {list(names)}, in that order. The "
            "value is positional and its entries are in three different units, "
            "so a short or long one is a could-not-evaluate — there is no "
            "prefix of it that can be trusted to mean what it is read as."
        )
    return dict(zip(names, (float(v) for v in values)))


def _limits_from_meta(conn) -> Limits:
    """The robot the artifact was built for, from its own provenance block.

    docs/lossiness.md Retained #10 records the limits precisely so this is
    possible: "without them the geometry cannot be recomputed, and a separation
    nobody can recompute is not evidence".

    Provenance travels with them (issue #84): `Limits.source` is required, so a
    file that does not record it cannot produce a `Limits` at all — which is
    what stops a recomputed envelope from being quoted as Layer A evidence on an
    artifact that never said its bounds were proprioceptive.
    """
    try:
        return Limits(
            q_min=_meta_array(conn, META_LIMITS_Q_MIN),
            q_max=_meta_array(conn, META_LIMITS_Q_MAX),
            qd_max=_meta_array(conn, META_LIMITS_QD_MAX),
            qdd_max=_meta_array(conn, META_LIMITS_QDD_MAX),
            link_lengths=_meta_array(conn, META_LIMITS_LINK_LENGTHS),
            source=_meta_limit_source(conn),
            link_radius=_meta_float(conn, META_LIMITS_LINK_RADIUS),
            **_base_bounds_from_meta(conn),
        )
    except ValueError as exc:  # Limits itself refuses a per-joint mismatch
        raise GraphQueryError(
            f"the limits recorded in this artifact are not self-consistent: {exc}"
        ) from exc


def envelope_frame(conn, envelope_id: str) -> BaseFrame:
    """The frame this envelope's `outer_radius` is measured about (issue #166).

    `outer_radius` is a distance from the base to the furthest point the robot
    can reach inside the horizon — a radius **about a centre**, and until the
    schema could say where the base was, that centre was the origin by the fact
    that there was no other possibility rather than by anything the artifact
    said. This is the reader that makes it a measurement: the radius and the
    point it is measured from, together, or a refusal.

    Two ways an artifact states the frame, and they are exclusive:

    * the configuration the envelope names states a `base_pose` — a room-frame
      pose, **Layer B**, and everything measured about it inherits whatever
      supplied it (docs/sufficiency.md §5.6);
    * the artifact states `meta[base_frame]` — where the base was bolted for the
      whole run, a mounting fact and Layer A, which is what every fixture in this
      repository has.

    Returns:
        The centre as a `BaseFrame`. It is a *frame* and deliberately not a
        `BasePose` even when it came from one: `reg.kinematics` is Layer A and
        may not import a room-frame pose, and a caller that needs the provenance
        reads it off `reg.store.config_base_pose`, where it is still attached to
        the thing it is a provenance of.

    Raises:
        GraphQueryError: the artifact holds no such envelope; the row retains no
            `outer_radius`, so there is no radius for a frame to belong to; or it
            states neither a pose nor a base frame, which is a
            could-not-evaluate. **The absence never resolves to the origin.** A
            radius silently attributed to `(0, 0)` for a robot that was elsewhere
            is the failure this whole reader exists to make impossible, and it is
            worse than no answer because it is one.
    """
    row = store.envelope_row(conn, str(envelope_id))
    if row is None:
        raise GraphQueryError(
            f"this artifact holds no envelope {str(envelope_id)!r}, so there is "
            "no radius here and no frame to measure one from."
        )
    if row["outer_radius"] is None:
        raise GraphQueryError(
            f"envelope {str(envelope_id)!r} has source={str(row['source'])!r} "
            "and retains no outer_radius. A declared region is the policy's "
            "claim and a clamped bound is what a verdict applied; neither is a "
            "reachable set, so neither has an outer radius and neither has a "
            "frame one would be measured about."
        )
    if row["base_pose"] is not None:
        pose, source = str(row["base_pose"]), str(row["base_pose_source"])
        values = _floats(
            pose, f"robot_config[{str(row['config_id'])!r}].base_pose"
        )
        if len(values) != 3:
            raise GraphQueryError(
                f"robot_config {str(row['config_id'])!r} states "
                f"base_pose={pose!r}, which is not the three numbers x,y,theta. "
                "A pose this reader cannot parse is a frame nobody stated, and "
                f"the radius on envelope {str(envelope_id)!r} is about a point "
                "that cannot be placed. Its provenance says "
                f"{source!r}, which does not help."
            )
        return BaseFrame(x=values[0], y=values[1], theta=values[2])

    frame = store.get_meta(conn, store.META_BASE_FRAME)
    if frame is None:
        raise GraphQueryError(
            f"envelope {str(envelope_id)!r} retains "
            f"outer_radius={float(row['outer_radius'])!r}, and this artifact "
            f"states neither a base_pose on config {str(row['config_id'])!r} nor "
            f"meta[{store.META_BASE_FRAME!r}]. That radius is a length in metres "
            "about a point nothing in the file names. Reading it as a radius "
            "about the origin is exactly what an artifact that can hold a moving "
            "base may not let a reader do, so it is a could-not-evaluate."
        )
    values = _floats(frame, f"meta[{store.META_BASE_FRAME!r}]")
    if len(values) != 3:
        raise GraphQueryError(
            f"meta[{store.META_BASE_FRAME!r}] is {frame!r}, which is not the "
            "three numbers x,y,theta. A base frame this reader cannot parse "
            "places nothing, and every retained outer_radius in the file is "
            "about a point it names."
        )
    return BaseFrame(x=values[0], y=values[1], theta=values[2])


def recorded_environment(conn) -> dict[str, str]:
    """The environment this artifact says its geometry was computed in (#200).

    The reader half of `reg.store.build_environment`. It reports what the file
    states and it decides nothing: comparing this against the environment of
    whoever is recomputing — and reporting a could-not-evaluate when the two
    differ — is the guard that depends on this issue and is deliberately not
    here. `envelope_at` behaves exactly as it did before these keys existed.

    Args:
        conn: an open artifact (`reg.store.connect`).

    Returns:
        Every key in `reg.store.ENVIRONMENT_KEYS` to the value the file states,
        in that order. Comparable directly against `store.build_environment()`.

    Raises:
        GraphQueryError: the artifact states no environment, states only part of
            one, or states an empty value for a key. All three are
            **could-not-evaluate**, and the third is why an empty string is
            refused rather than returned: a file whose machine is `''` would
            compare unequal to every recomputing environment and would read as a
            mismatch — a *finding* about the artifact — when what is true is that
            the file never said. The absence never resolves to the reader's own
            environment, which is the failure this reader exists to make
            impossible: it would turn "built somewhere else" into "built here".
    """
    stated = store.all_meta(conn)
    missing = [key for key in store.ENVIRONMENT_KEYS if key not in stated]
    if missing:
        present = [key for key in store.ENVIRONMENT_KEYS if key in stated]
        raise GraphQueryError(
            f"this artifact states no {missing} in its meta table, so it does "
            "not say what its geometry was computed with"
            + (f" (it states {present})" if present else "")
            + ". A discarded polygon is recomputable on an argument that holds "
            "within one architecture and was measured not to hold across them "
            "(issue #175), so an environment nobody recorded is a "
            "could-not-evaluate. Reading it as this reader's own environment "
            "would turn a recomputation somewhere else into one made here."
        )
    empty = [key for key in store.ENVIRONMENT_KEYS if not stated[key].strip()]
    if empty:
        raise GraphQueryError(
            f"this artifact states {empty} as empty text. An environment key "
            "that says nothing is not an environment: it compares unequal to "
            "every recomputing environment, so it would read as a machine "
            "mismatch — a finding about the artifact — when the fact is that "
            "the file never said. reg.store.build_environment refuses to write "
            "one, so this file was not written by it."
        )
    return {key: stated[key] for key in store.ENVIRONMENT_KEYS}


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
    # By the envelope's own `config_key` rather than by re-resolving the readable
    # id (issue #55): the surrogate is what the row stores, and going back
    # through the identifier would look up a *second* time something the row has
    # already said once.
    config = conn.execute(
        "SELECT q, qd, base_pose FROM robot_config WHERE config_key = ?",
        (row["config_key"],),
    ).fetchone()
    if config is None:
        raise GraphQueryError(
            f"envelope {envelope_id!r} names config {str(config_id)!r}, which is "
            "not in this artifact. The polygon was discarded as recomputable and "
            "the thing it was to be recomputed from is missing."
        )
    if config["base_pose"] is not None:
        # THE RECOMPUTE ARGUMENT'S CONDITION, ENFORCED (issue #166). Everything
        # below is body-frame: `q`, `qd`, the limits and the four numbers in
        # `meta`. Where the body *was* is not in it, so for a configuration that
        # states a pose these inputs describe the same arm in a different place,
        # and the polygon that came back would be the region a robot at the
        # origin could reach. That is not a looser answer than the right one; it
        # is an answer about somewhere else, and it would look exactly like a
        # stored polygon to every caller. docs/lossiness.md Discarded #9.
        raise GraphQueryError(
            f"envelope {envelope_id!r} was discarded as recomputable, but the "
            f"config {str(config_id)!r} it names states "
            f"base_pose={str(config['base_pose'])!r} — the base was not at the "
            "frame this recomputation would place it at. The envelope is a "
            "function of q, qd and the horizon *in the base's own frame*, so "
            "recomputing it here would return the region a robot at "
            f"meta[{store.META_BASE_FRAME!r}] could reach and report it as the "
            "region in force. A run whose base moved has to retain the polygon "
            "(GEOMETRY_RETENTION); this artifact did not, and there is nothing "
            "in the file to recover it from."
        )

    state = ProprioState(
        t=t,
        q=_floats(config["q"], f"robot_config[{str(config_id)!r}].q"),
        qd=_floats(config["qd"], f"robot_config[{str(config_id)!r}].qd"),
        # `robot_config` stores the base's *pose* since issue #166 and still no
        # base velocity, so this artifact records none. `None` says that; zero
        # would say the base was standing still, which is a different claim and
        # one no row here supports (issue #150). The refusal above is what stops
        # the two absences compounding: a configuration that states a pose never
        # reaches this line, so a `None` velocity here is only ever a bolted
        # base's (docs/mobile-base.md §3 and §4 item 4).
        base_vel=None,
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


def _resolve_scenario(csv_path: str | os.PathLike[str]):
    """The scenario that produced a stream, from the stream's own provenance block.

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
    from reg.scenarios import scenario
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
    # Through `scenario()` rather than a `SCENARIOS` membership test, because
    # since issue #30 not every scenario is a registered one: the scaling
    # fixture is generated per length and `scenario()` resolves its names.
    # Testing membership here would leave a long-run stream as the one kind of
    # file whose own provenance block names something this build cannot resolve.
    try:
        return scenario(name)
    except KeyError as exc:
        raise GraphBuildError(
            f"{csv_path} says scenario={name!r}, which this build does not "
            f"know: {exc.args[0]}"
        ) from None


def _resolve_world(csv_path: str | os.PathLike[str]):
    """The world that produced a stream. `_resolve_scenario`, narrowed."""
    return _resolve_scenario(csv_path).world


def attestation_from_stream(
    csv_path: str | os.PathLike[str],
    scenario,
    *,
    keyring_path: str | os.PathLike[str],
    replan_interval_s: float,
    declaration_horizon_s: float,
    watchdog_period_s: float,
    substep_dt: float,
) -> AttestationRecords:
    """Run the scripted policy and the enforcer over a stream, and return both.

    **Public since issue #59**, which is when it gained a second caller. It was
    `_attestation_from_stream` while the CLI was the only one; `reg.bench` now
    needs a record stream too, and the alternative to naming this is a second
    copy of the wiring — which would be a second answer to "what did this run's
    policy declare", with the benchmark quietly measuring one of them.

    This is the CLI's producer, and it is the same wiring `tests/test_enforce.py`
    does by hand: the policy issues a declaration per replan interval, each is
    offered to the enforcer at the instant it was issued, and every frame is
    adjudicated. Nothing goes back the other way — the black channel is the
    premise (docs/plan.md Phase 3), so a verdict never reaches the policy.

    The keyring is a file the caller names. It is **not** generated here: key
    material is the one thing in this project that must not be reproducible from
    a seed (`reg.chain.generate_keyring`), and a keyring made up per build would
    give the same run a different set of MACs every time — which would break
    determinism and be worthless as attribution besides.

    Args:
        csv_path: the stream, read a second time for its proprioception. The
            envelope pass in `build` reads it too; this one is cheap beside it.
        scenario: the scenario named in the stream's own provenance block. Its
            `declared_q_bounds` is what the policy declares — the fixed box that
            makes `declared_violation` a policy that can be caught.
        replan_interval_s, declaration_horizon_s, watchdog_period_s: stated by
            the caller and never invented. docs/plan.md fixes none of the three,
            and each decides how much of the taxonomy can fire at all.
        substep_dt: the envelope integration grid, seconds. **Required, no
            default** (issue #106), and it must be the same number the caller
            gives `build` — the enforcer's overclaim bound has to cover the
            trajectories the artifact stores geometry for, and an enforcement
            bound taken on a finer grid than the build's is two numbers in one
            file disagreeing about the discretisation they describe. `main`
            passes `--substep-dt` to both; `tests/test_enforce.py::
            test_the_artifact_and_its_enforcement_bound_share_one_substep_dt`
            is what keeps that true.

    Raises:
        GraphBuildError: a declaration was issued at an instant no frame carries,
            so it could never be offered. That is a producer this module does not
            understand, and dropping it would silently shorten the chain.
        EnforcementError: the overclaim bound could not be computed for a frame —
            most often a state whose `|qd|` is above `limits.qd_max`. It
            propagates: `reg.enforce` raises rather than emitting a verdict for
            an unevaluable input (issue #106), and this run writes no artifact
            either way, because `reg.envelope.compute_envelope` refuses the same
            state in the geometry pass below.
    """
    from reg.chain import load_keyring
    from reg.declare import emit_declarations
    from reg.enforce import Enforcer

    keyring = load_keyring(keyring_path)
    states = [frame.proprio() for frame in read_frames(csv_path)]

    # THE FIXTURE'S POLICY FIELDS, ALL OF THEM. A scenario says three things about
    # what its policy does, and reading only some of them builds an attestation
    # layer that disagrees with the fixture it was built from:
    #
    #   silent_windows      instants the policy did not see. Filtered out here, so
    #                       the timing faults (no declaration, stale) reproduce in
    #                       the artifact instead of being papered over by a
    #                       declaration this build invented.
    #   declared_margin_m   how far past its own region the policy claims. It is
    #                       the ONLY way a run produces an envelope overclaim
    #                       (reg/scenarios.py), so dropping it silently removes a
    #                       fault from the graph.
    #   declared_action_class  NOT read here, deliberately. Producing an
    #                       out-of-vocabulary declaration means bypassing
    #                       `Declaration.__post_init__`, which refuses one at
    #                       construction — correctly. A library that offers a way
    #                       to build an invalid record is a library that will be
    #                       used to build one, so that fixture's fault is
    #                       exercised in tests/test_enforce.py and does not
    #                       reproduce in an artifact. See issue for the full fix.
    speaking = [state for state in states if not scenario.silent_at(state.t)]
    if not speaking:
        # A policy that never declares at all. `emit_declarations` refuses an
        # empty run and is right to; the artifact records a stream with no
        # declarations rather than a build that failed.
        declarations: tuple[Declaration, ...] = ()
    else:
        declarations = emit_declarations(
            speaking,
            scenario.world.limits,
            key=keyring.key("policy"),
            replan_interval_s=replan_interval_s,
            horizon_s=declaration_horizon_s,
            declared_q_bounds=scenario.declared_q_bounds,
            declared_margin_m=scenario.declared_margin_m,
            id_prefix=scenario.name,
        )

    # Keyed on the rounded instant, matching the fixture harness: `t_issued` is
    # copied from a state's own `t`, so equality holds, and the rounding is
    # against a float that made one round trip through the CSV.
    pending = {round(d.t_issued, 9): d for d in declarations}
    enforcer = Enforcer(
        scenario.world.limits,
        key=keyring.key("enforcement"),
        policy_key=keyring.key("policy"),
        watchdog_period_s=watchdog_period_s,
        # Enforcement comes up at the stream's first frame. Stated rather than
        # defaulted to zero: the watchdog is measured from here, and a t_start
        # before the run would fire it on the first action of a stream that
        # simply does not begin at the epoch.
        t_start=float(states[0].t),
        # The build's grid, not the module default (issue #106). The overclaim
        # bound covers the discrete trajectories, and those are integrated at
        # whatever `build` was given; taking `reg.envelope.SUBSTEP_DT` here would
        # compute one of the artifact's two numbers on a grid the artifact does
        # not record.
        substep_dt=substep_dt,
        id_prefix=scenario.name,
    )

    verdicts: list[Verdict] = []
    for state in states:
        due = pending.pop(round(state.t, 9), None)
        if due is not None:
            # The frame at `t_issued` goes with the declaration: the overclaim
            # bound is integrated forward from the pose the policy was in when
            # it made the claim (issue #82). The key this was popped from is
            # that instant, so the two are the same frame by construction.
            refusal = enforcer.offer(due, state)
            # `offer` returns a verdict only when it refuses. An acceptance
            # adjudicates no action, so there is nothing to record for it.
            if refusal is not None:
                verdicts.append(refusal)
        verdicts.append(enforcer.adjudicate(state))

    if pending:
        raise GraphBuildError(
            f"{sorted(pending)}: the policy issued declaration(s) at instants no "
            "frame of the stream carries, so they could never be offered to "
            "enforcement. Storing them would put records in the artifact that "
            "nothing in the run ever adjudicated; dropping them would shorten "
            "the chain with nothing saying so."
        )
    return AttestationRecords(
        declarations=tuple(declarations), verdicts=tuple(verdicts)
    )


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
    # Absolute time and identity (issue #83). All three are required and none
    # has a default, for the reason `--out` has none: there is no correct guess.
    # A run start read from the host clock would also make two runs of the same
    # command differ, which is the property CI checks.
    build_parser.add_argument(
        "--run-start",
        metavar="INSTANT",
        help=(
            "the UTC instant this run began, RFC 3339 — e.g. "
            "2026-08-21T09:00:00Z, or with an explicit offset. Required, no "
            "default: it is what places every occurrence on a wall clock, which "
            "is what DSSAD's ±1.0 s is an accuracy requirement about. Declared "
            "rather than read from a clock, so same seed and same declared "
            "start still gives the same bytes."
        ),
    )
    build_parser.add_argument(
        "--unit-id",
        metavar="ID",
        help=(
            "which robot this artifact describes. Required, no default: an "
            "artifact that cannot say which unit it is about cannot be handed "
            "to anyone, and nothing recovers it from the file later."
        ),
    )
    build_parser.add_argument(
        "--operator-id",
        metavar="ID",
        help=(
            "the operator responsible for the run. Required, no default — the "
            "other half of 'which robot, which shift'."
        ),
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
    build_parser.add_argument(
        "--occurrence-resolution",
        type=_positive_float,
        default=OCCURRENCE_TIME_RESOLUTION_S,
        metavar="SECONDS",
        help=(
            "the resolution every occurrence timestamp is rounded to (default: "
            f"{OCCURRENCE_TIME_RESOLUTION_S}, UN R157 DSSAD's stated accuracy). "
            "Recorded in the artifact either way. It does not touch the edge "
            "layer, whose interval endpoints are at TIME_TOL_S."
        ),
    )
    # The attestation layer. Off unless a keyring is named, and then all four
    # are required together: there is no default replan interval, declaration
    # horizon or watchdog period anywhere in docs/plan.md, and each of the three
    # decides which of the nine faults can fire at all. A plausible number
    # invented here would be indistinguishable downstream from a stated one.
    build_parser.add_argument(
        "--keyring",
        metavar="PATH",
        help=(
            "a keyring file (reg.chain.write_keyring). Supplying one runs the "
            "scripted policy and the enforcer over the stream and stores the "
            "declarations, the verdicts and the chain. Without it the artifact "
            "holds no attestation layer and says so in its meta table. Key "
            "material is never generated here — a keyring made up per build "
            "would give one run a different set of MACs every time."
        ),
    )
    build_parser.add_argument(
        "--replan-interval",
        type=_positive_float,
        metavar="SECONDS",
        help=(
            "seconds between declarations. Required with --keyring and has no "
            "default: it sets how coarse the entire declaration stream is."
        ),
    )
    build_parser.add_argument(
        "--declaration-horizon",
        type=_positive_float,
        metavar="SECONDS",
        help=(
            "the validity window each declaration claims, at least "
            "--replan-interval. Required with --keyring and has no default: it "
            "is what makes a declaration stale."
        ),
    )
    build_parser.add_argument(
        "--watchdog-period",
        type=_positive_float,
        metavar="SECONDS",
        help=(
            "seconds of silence from the declaration channel before enforcement "
            "drives to a safe state. Required with --keyring and has no default: "
            "it decides whether that check ever fires."
        ),
    )
    build_parser.add_argument(
        "--witness",
        metavar="PATH",
        help=(
            "a witness file (reg.commit.write_witness): a second on-site "
            "keyholder who signs both chain heads when the artifact is closed. "
            "Only meaningful with --keyring — without a record stream there is "
            "no chain to commit to. Without it the artifact records "
            f"'{META_COMMITMENT}: {COMMITMENT_NONE}' explicitly, because an "
            "uncommitted chain must announce itself rather than be inferred "
            "from a missing key. This is NOT a timestamp: it proves a second "
            "party at the same site saw these heads, not that they existed by "
            "any instant to anyone outside the operator."
        ),
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

    # Named individually rather than as a group, so the error says which of the
    # three is missing. Not `required=True` for the reason `--out` is not: the
    # message argparse produces for that says only that a flag is absent, and
    # what a reader needs to know here is why there is no default for it.
    identity_args = {
        "--run-start": args.run_start,
        "--unit-id": args.unit_id,
        "--operator-id": args.operator_id,
    }
    absent = [name for name, value in identity_args.items() if value is None]
    if absent:
        parser.error(
            f"{', '.join(absent)} {'is' if len(absent) == 1 else 'are'} required, "
            "with no default. An artifact with no absolute time and nothing "
            "naming the unit cannot be placed against any other log in "
            "the cell, and an EU AI Act Art. 73 clock cannot be started from it. "
            "The start is declared, not read from this host's clock, so passing "
            "the same one twice still gives byte-identical output."
        )

    attestation_args = {
        "--replan-interval": args.replan_interval,
        "--declaration-horizon": args.declaration_horizon,
        "--watchdog-period": args.watchdog_period,
    }
    supplied = [name for name, value in attestation_args.items() if value is not None]
    if args.keyring is None and supplied:
        parser.error(
            f"{', '.join(supplied)} only mean something with --keyring, which "
            "was not given. Without a keyring nothing signs a declaration, so "
            "there is no record stream for these to parameterise."
        )
    if args.keyring is not None:
        missing = [name for name, value in attestation_args.items() if value is None]
        if missing:
            parser.error(
                f"--keyring was given, so {', '.join(missing)} "
                f"{'is' if len(missing) == 1 else 'are'} required. None of the "
                "three has a default: docs/plan.md fixes no replan rate, no "
                "declaration horizon and no watchdog period, and each decides "
                "which of the nine faults can fire at all. A plausible number "
                "invented here would be indistinguishable downstream from one "
                "somebody stated."
            )
    if args.keyring is None and args.witness is not None:
        parser.error(
            "--witness only means something with --keyring, which was not given. "
            "A commitment is over the two chain heads, and a build with no "
            "record stream has no chain — committing to two genesis hashes "
            "would produce a signature that verifies and says nothing."
        )

    try:
        identity = RunIdentity.declare(
            run_start=args.run_start,
            unit_id=args.unit_id,
            operator_id=args.operator_id,
        )
    except IdentityError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE

    try:
        scenario = _resolve_scenario(args.csv)
        world = scenario.world
        records = None
        committer = None
        if args.keyring is not None:
            records = attestation_from_stream(
                args.csv,
                scenario,
                keyring_path=args.keyring,
                replan_interval_s=args.replan_interval,
                declaration_horizon_s=args.declaration_horizon,
                watchdog_period_s=args.watchdog_period,
                # The same `--substep-dt` the build below is given, and the same
                # object: one grid per run (issue #106).
                substep_dt=args.substep_dt,
            )
            if args.witness is not None:
                witness = load_witness(args.witness)
                # Refused here rather than reported later: a witness holding a
                # record-signing key produces a signature indistinguishable from
                # a real one, so nothing downstream can tell the author
                # witnessing themself from a second party.
                check_witness_is_independent(witness, load_keyring(args.keyring))
                committer = WitnessCommitter(witness)
        result = build(
            args.csv,
            args.out,
            world.limits,
            identity=identity,
            human_radius=world.human_radius,
            horizon=args.horizon,
            n_samples=args.n_samples,
            seed=args.envelope_seed,
            substep_dt=args.substep_dt,
            occurrence_resolution_s=args.occurrence_resolution,
            records=records,
            commitment=committer,
        )
    except GraphBuildError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except store.StoreError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except CommitmentError as exc:
        # An unreadable witness file, or one whose key is a record-signing key.
        # Same exit as the rest — a could-not-evaluate that wrote no artifact,
        # and emphatically not a build that quietly went ahead uncommitted.
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except (KeyringError, DeclarationError, EnforcementError) as exc:
        # The record stream could not be produced: an unreadable keyring, or a
        # policy or enforcement parameter the producers refuse. Same exit as the
        # rest — a could-not-evaluate that wrote no artifact.
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE

    counts = " ".join(f"{name}={n}" for name, n in sorted(result.edges.items()))
    nodes = " ".join(f"{name}={n}" for name, n in sorted(result.nodes.items()))
    print(
        f"wrote {result.path}: frames={result.frames} "
        f"edges={result.total_edges} ({counts}) nodes ({nodes}) "
        f"bytes={result.size_bytes}"
    )
    if not result.time_base_resolves_frames:
        # Not an error and not a non-zero exit: the artifact is complete and
        # every question in the supported set still answers off it. It is said on
        # stderr because a person who builds a 1 kHz run and then reads per-frame
        # numbers out of the result needs to know they are good to the timestamp
        # quantum, and `meta[time_base_domain]` is not somewhere anyone looks
        # unprompted. See docs/limitations.md section 4.
        print(
            f"note: {result.frames} frames landed on "
            f"{result.addressable_instants} addressable instants. This stream was "
            f"sampled faster than {TIME_BASE_MAX_RATE_HZ:g} Hz, which is "
            "1/TIME_TOL_S and the rate above which the artifact's timestamps "
            "stop separating frames. Per-frame answers off this file are good to "
            f"TIME_TOL_S={TIME_TOL_S} s and not to the frame — see "
            f"meta[{META_TIME_BASE_DOMAIN}] and docs/limitations.md section 4. "
            "No tolerance was widened and nothing was dropped.",
            file=sys.stderr,
        )
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
