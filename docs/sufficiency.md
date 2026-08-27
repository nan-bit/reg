# Sufficiency boundary — which audit claims survive an uncertifiable perceiver

**Status:** normative for what this project may claim · written 2026-08-19 ·
[`docs/plan.md`](plan.md) Phase 9, Claim 3's deliverable · written for
Milestone 2, re-measured 2026-08-20 after Milestone 3, §7 reconciled against the
measured tables 2026-08-21 · keep current

The mechanism this document argues from already exists. Every edge in the
artifact carries a `layer` column, `A` or `B`, and so does every occurrence; the
value is never supplied by a caller but derived from the type in
`reg.store.EDGE_SPECS` and `reg.store.OCCURRENCE_SPECS`, and
`tests/test_graph.py::test_layer_b_is_exactly_the_entity_naming_edges` derives
the *expected* value from whether the type touches an `Entity`, so an edge type
added without a layer decision fails there rather than in somebody's query months
later.

What did not exist until this file is the argument that turns that column into a
claim: **which audit questions this artifact answers on its own authority, and
which it answers only as well as whatever supplied the entity positions.**

The obstacle-independent envelope itself is not the contribution and this document
does not present it as one — computing a reachable set from the robot and only
then intersecting it with the scene is how reachability-based trajectory design
has worked for years ([`docs/prior-art.md` §4](prior-art.md), ARMTD/ARMOUR). What
is worth stating is downstream of it: the graph tags every relationship with the
layer it depends on, so the boundary below is a property of the *record* rather
than a paragraph in a README.

---

## 1. The finding

**A volume derived from perception inherits perception's failure modes. You
cannot ground a certifiable envelope in an uncertifiable perceiver.**

This is not a statement about how good a perceiver is. Take any claim this
artifact can be asked for about the world — *the human was never inside the
reachable set*, *the closest the robot came was 7 cm*, *no contact occurred*. Each
decomposes into two conjuncts:

1. where the reachable set was, which comes from `q`, `q̇` and the actuation
   limits — proprioception and nothing else; and
2. where the entity was, which in this prototype is simulator ground truth and in
   any real system is the output of a perception stack.

A conjunction is no stronger than its weaker conjunct. Improving (1) — a tighter
envelope, a finer quantum, an outer approximation instead of an inner one — moves
nothing about the strength of the composite claim, because the composite claim
was never limited by (1). The layered structure does not repair this. **Nothing
repairs it**; a perception stack's assurance case is the only thing that can, and
this project does not attempt one. What the structure does is make the dependence
*visible per edge, and therefore per answer*, so that a claim which is conditional
looks conditional in the artifact rather than in a caveat somebody has to remember
to attach.

## 2. The asymmetry — the half that is worth the trouble

**Every attestation query is Layer A.** Whether the policy honoured its own
declaration is answerable from certifiable evidence, independently of whether
perception was right. A declaration is a statement the policy made about a region
it computed from its own state; a verdict is what an independent enforcement layer
computed from proprioception and actuation limits; the chain is a hash and a MAC
over those records. Not one of them names an entity, and no perceptual error can
make a policy that exceeded its declared bound look like one that did not.

That is a materially stronger claim than anything about the world, and it is
exactly what the black-channel pattern buys ([`docs/plan.md`](plan.md), standards
baseline; IEC 61784-3). The pattern's usual application declares the *transport*
uncertifiable and moves all assurance to the endpoints. Here it is applied twice:
the policy is one uncertifiable middle, and the perceiver is a second. The
attestation questions route around both.

Two honest bounds on that sentence, stated here rather than buried:

- The asymmetry was a claim about **structure** only, when this was written in
  Milestone 2: `reg.declare` and `reg.chain` existed but no artifact carried a
  declaration, a verdict or a chain, so rows 2–4 read *unmeasured*. **Milestone 3
  closed that gap** — the artifact carries them, and `reg.bench --resolution`
  prices four of the attestation questions against the record stream the run
  emitted (§5.4). What remains structural rather than measured is row 1, and for
  a different reason: its only available ground truth is `reg.envelope` itself,
  and a check whose ground truth reruns the code under test cannot fail.
- Layer A is certifiable *in the sense that its failure modes are characterizable*
  — not in the sense that this prototype has characterized them. §7 lists what a
  Layer A answer here still inherits.

## 3. Two axes, not one

[`docs/plan.md`](plan.md) Phase 9 describes a single taxonomy: Layer A alone
versus needs Layer B. That was written before issue #35 added a second and
orthogonal axis — **resolution** — and before issue #36 measured it.

| Axis | What it decides | Where the answer comes from |
|---|---|---|
| **Layer** | Whose failure modes an answer inherits | The `layer` column, derived from the type in `reg.store.EDGE_SPECS` / `OCCURRENCE_SPECS` |
| **Resolution** | Whether the answer survives what the artifact discarded | The measured curve, `python -m reg.bench --resolution` |

They are independent, and both directions of the independence occur below. A
Layer A question can be unanswerable at a coarse level: the occurrence view holds
**zero** edge rows, so nothing about the envelope survives into it and the
reachability question dies there despite being certifiable. A Layer B question can
be perfectly answerable at the coarsest level: *did the robot contact the human*
is answered from a DSSAD-shaped occurrence flag in a level costing 60.29 MB/h —
a figure **at a 50 Hz control rate**, which the level's attestation stream and
not its occurrence flags is what buys (98.5% of its rows are records,
[`plan.md`](plan.md) Claim 1, issue #116) — and is still only as strong as
whatever said where the human was.

The three levels are defined in [`docs/lossiness.md`](lossiness.md), *The three
resolution levels*: **occurrence** (DSSAD-aligned, timestamps at ±1.0 s),
**transition** (the edge layer, endpoints at `TIME_TOL_S` = 10 ms), and
**per-frame**. All three are views of one build.

### The measured curve

`long_run` at 3,000 frames (60.0 s of robot time) **at a 50 Hz control rate**,
`n_samples=16`, seed 0, occurrence resolution 1.0 s — reproduced for this document
with `python -m reg.bench --resolution`:

> **Re-measured 2026-08-20.** This table predated issues #59, #60 and #61 and was
> wrong in every column. It measured an artifact holding **no Layer A at all**
> (`bench._measure` never passed `records=`), so its byte counts were a third of
> the truth and it could price only four questions; and it recorded `occurrence`
> as **DISAGREE** on `time_of_closest_approach`, because the check graded every
> level against `TIME_TOL_S` without consulting the level's own quantum. A ±1.0 s
> level answered within 0.02 s and was marked wrong for it. Both are fixed; the
> figures below come from one execution on the merged code.

| level | ts res | SQLite B | bytes/hour @ 50 Hz | nodes | edges | occ | records |
|---|---|---|---|---|---|---|---|
| `occurrence` | 1.0 s | 1,004,544 | **60.29 MB/h** | 3,166 | 0 | 42 | 3,120 |
| `transition` | 0.01 s | 2,494,464 | **149.72 MB/h** | 5,870 | 9,724 | 0 | 3,120 |
| `per-frame` | 0.01 s | 3,624,960 | **217.57 MB/h** | 5,870 | 18,428 | 0 | 3,120 |

The rate is in the column heading because the column **moves with it**:
enforcement emits one verdict and one chain record per commanded action and no
resolution level coarsens them. The *record layer* is linear in the rate; the
*file* is not, and a real 1 kHz manipulator pays **15.8x** these figures at the
occurrence level rather than the twenty times a linear reading gives — measured,
with the bytes attributed table by table, in [`plan.md`](plan.md), *The control
rate*, which is also where the curve at four control rates is.

**5 of the 9 supported questions are priced**, shown below as eight columns:
`min_separation`, `time_of_closest_approach` and `did_contact_occur` are scalar
reductions of `separation_timeline` and count as that one question. The other
four questions are `EXCLUDED` with a stated reason, and an exclusion is a
could-not-evaluate, never a pass.

| question | layer | `occurrence` | `transition` | `per-frame` |
|---|---|---|---|---|
| `min_separation` | B | AGREE | AGREE | AGREE |
| `time_of_closest_approach` | B | **CNE** | AGREE | AGREE |
| `separation_timeline` | B | **CNE** | AGREE | AGREE |
| `did_contact_occur` | B | AGREE | AGREE | AGREE |
| `declared_bound` | A | **CNE** | AGREE | AGREE |
| `violations` | A | AGREE | AGREE | AGREE |
| `verdicts` | A | **CNE** | AGREE | AGREE |
| `verify_chain` | A | AGREE | AGREE | AGREE |
| **level verdict** | | **CNE** | **AGREE** | **AGREE** |

**2.5x the bytes buys four questions**, and the ratio used to read twelve because
the artifact was missing the layer that does not coarsen. The declaration,
verdict and chain records are emitted per action and **no level coarsens them**:
at ±1 s they are 3,120 of `occurrence`'s 3,166 node rows. Coarsening the scene
now has much less left to work on, which is the finding and not a defect in it.
That is the entire content of the resolution axis, and the rows below cite it
rather than restating it.

---

## 4. The taxonomy

Each row's layer is the value the schema assigns, and each row's resolution is a
verdict from the curve above — or the word **unmeasured**, where nothing in this
project has measured it yet. A row nothing supports is marked unmeasured; it is
not omitted, and it is not softened into a claim.

**How to read the strength column.**

- **certifiable** — answerable from Layer A evidence alone. Inherits no perceptual
  failure mode. Still inherits this project's own stated limitations (§7).
- **certifiable, and measured** — Layer A by the schema's vocabulary, *and* the
  artifact carries the records, *and* the curve prices the question against the
  stream the run emitted. Rows 2–4 earned this in Milestone 3.
- **certifiable in structure, unmeasured** — Layer A by the schema's own
  vocabulary, but no artifact holds the records, so nothing has been measured. The
  honest reading is "this is what the structure will support", not "this is
  supported". **No row carries this label any more**; it is kept because the
  distinction is the one this document exists to hold, and the next unbuilt Layer
  A question will need it again.
- **only as strong as perception** — the answer is a conjunction with *the entity
  was where the artifact says it was*, and this project supplies no evidence for
  that conjunct. It is the finding, not a caveat.

| # | Question (query) | Layer, and the evidence for it | Minimum resolution, and the evidence for it | Claim strength |
|---|---|---|---|---|
| 1 | Could the robot have reached (x, y) at t? (`reg.graph.envelope_at`) | **A** — `HAS_ENVELOPE` is `EdgeSpec("A", "RobotConfig", "Envelope", …)`; it is the only Layer A edge type, and the only one naming no `Entity` | **transition** — the occurrence view holds **0 edges** (curve above) and, by the projection's own rule, no `envelope` and no `robot_config` rows either, so the question has no substrate there. Agreement at the transition level is **unmeasured, deliberately**: the only available ground truth is `reg.envelope` itself, and a check whose ground truth reruns the code under test cannot fail | **certifiable**, in the positive direction only |
| 2 | Did the policy exceed its declared bound? (`violations(window)`) | **A** — [`docs/lossiness.md`](lossiness.md) supported-question set, query 6. No entity is named by a declaration or a verdict | **occurrence** — AGREE at every level. The record tables survive all three views intact, so this is the rare question the coarsest artifact answers in full | **certifiable**, and measured |
| 3 | What did the policy declare at t? (`declared_bound(t)`) | **A** — same, query 5 | **transition** — occurrence: **COULD-NOT-EVALUATE** ("this level states no declaration in force at t=30.0"), because the region a declaration names lives in the `edge` and `envelope` tables the occurrence view empties; transition and per-frame: AGREE | **certifiable**, and measured |
| 4 | Was the record tampered with? (`verify_chain()`) | **A** — same, query 8. A hash chain and a MAC over records that name no entity | **occurrence** — AGREE at every level, walked under `measurement_keyring` over 3,120 chain records. Negative tests feed it a truncated chain, an altered record and a missing key | **certifiable**, and measured |
| 5 | Did the robot contact the human? (`did_contact_occur`) | **B** — `CONTACT` is `EdgeSpec("B", "RobotConfig", "Entity", …)`; `contact_began` / `contact_ended` are `OccurrenceSpec("B", "entity", …)` | **occurrence** — AGREE at 1.0 s and 60.29 MB/h at 50 Hz. Caveat kept attached: in this fixture that is **agreement on a negative** (the run contains no contact); `tests/test_bench.py::test_the_contact_check_says_no_when_the_occurrence_layer_is_wrong` is where the check is shown able to say no | **only as strong as perception** |
| 6 | How close did the robot get to the human? (`min_separation`) | **B** — `SEPARATION` is `EdgeSpec("B", "RobotConfig", "Entity", "min_distance")`; `closest_approach` is `OccurrenceSpec("B", "entity", "min_distance_m")` | **occurrence** — AGREE, Δ 0.0007 m against a 0.01 m (`DISTANCE_TOL_M`) predicate | **only as strong as perception** |
| 7 | Was the human inside the reachable set, and when did it first enter? (`first_envelope_intersection`) | **B** — `INTERSECTS` is `EdgeSpec("B", "Envelope", "Entity", "overlap_area")` | **transition** — `reg.query` declares it `answerable_from={edge}`: the occurrence layer locates entry only to ±1.0 s and carries no overlap area, so it cannot produce the intervals this query returns. Agreement **unmeasured**, for the same envelope-ground-truth reason as row 1 | **only as strong as perception** |
| 8 | Which entities were inside the envelope during [t₀, t₁]? (`reachable_entities`) | **B** — `INTERSECTS`, as above | **transition** — `answerable_from={edge}`. The predicate is exact set equality with no tolerance to spend, and membership derived from ±1.0 s events would be exact-looking and wrong at the edges. Agreement **unmeasured**, as row 1 | **only as strong as perception** |
| 9 | Which intervals had the human within a threshold? (`frames_at_risk`) | **B** — `SEPARATION`, as row 6 | **transition** — `answerable_from={edge}`: a threshold test is a per-frame question about a metric, and the occurrence layer retains no metric between events. `EXCLUDED` from the curve — it takes a threshold and nothing supplies one — so **unmeasured** as an agreement verdict | **only as strong as perception** |
| 10 | What was the separation at every frame? (`separation_timeline`) | **B** — `SEPARATION`, as row 6 | **transition** — occurrence: **COULD-NOT-EVALUATE** ("this level holds no per-frame separation"); transition: AGREE, worst frame Δ 0.0096 m over 3,000 frames against 0.01 m | **only as strong as perception** |
| 11 | When exactly was the closest approach? (`time_of_closest_approach`) | **B** — as row 6 | **transition** — occurrence: **COULD-NOT-EVALUATE**, 46.0000 s against 5 frames within 0.01 m of the minimum, nearest at 45.9800 s, Δ 0.0200 s — inside that level's own 1.0 s quantum, so imprecise rather than wrong; transition: AGREE, Δ 0.0000 s | **only as strong as perception, *and* needs 10 ms** |

Rows 1 and 5–11 were the questions **Milestone 2** could be asked, and of those
exactly one was Layer A — the one saying what the machine could have done rather
than what happened to anyone. That imbalance is what Milestone 3 corrected: rows
2–4 are answerable and measured now, so four of the eleven are Layer A — and
**two** of those four are answerable at the coarsest level in the project. Rows 2
and 4 are; row 3 is COULD-NOT-EVALUATE there, and row 1 has no substrate there at
all. The certifiable layer survives coarsening better than the scene layer does,
which is §5.4's finding, but "better" is not "entirely".

---

## 5. Worked examples

### 5.1 Certifiable: "could the robot have reached (x, y) at t?"

The envelope at `t` is computed by `reg.envelope.compute_envelope`, whose only
inputs are a `ProprioState` and a `Limits`. `ProprioState` has no field naming an
entity, and `tests/test_layer_boundary.py::test_propriostate_fields_are_exactly_
the_allowed_set` fails if one appears — *that absence is the enforcement*
(CLAUDE.md rule 1). `reg.graph._observe` computes the envelope first and only then
intersects it with the scene, which is why `HAS_ENVELOPE` can be tagged `A` while
every edge naming an entity is tagged `B`.

So the answer inherits nothing from perception. A perception stack that was wrong
about every entity in the room changes no bit of this answer.

**What it does not license, and this is not a footnote.** The envelope whose
geometry this answer is read off is a sampling-based *under*-approximation. "The
robot **could have** reached (x, y)" is supported at any resolution;
"**could not have**" is supported only *radially*, and only since issue #82: every
`computed` envelope row carries `outer_radius`, the radius of a horizon-limited
**outer** reachable set, and a point beyond it is one the robot could not have
reached. Between that radius and the sampled boundary the artifact says nothing,
and no query may be read as though it did ([`docs/lossiness.md`](lossiness.md)
*Unanswerable* #3, [`docs/limitations.md`](limitations.md) §2 and §3,
[`docs/prior-art.md` §4](prior-art.md) for the zonotope machinery a *tight* claim
in the negative direction would need). A certifiable claim in the wrong direction
is not a safety claim, and a bracket is not a boundary.

**And it dies first under coarsening.** The occurrence view holds 0 edges, and
this question's substrate is edges. The Layer A rows that view *does* hold are
`run_began` and `run_ended` — *this run happened, between these two instants,
under this software version* — plus, since Milestone 3, the 3,120 declaration and
verdict records no level coarsens (§3, §5.4). Those are the attestation half: they
say what the policy claimed and what enforcement did about it. Not one of them
says what the machine could have reached, and the geometry that would is in the
`edge` and `envelope` tables this view empties. That is worth saying to anyone who
reads "occurrence-level evidence is enough" as a general conclusion — it is enough
for four of the eight questions the curve prices as columns (contact and closest
distance from the scene half; `violations` and `verify_chain` from the attestation
half), and it is the level at which the certifiable *reachability* question stops
being answerable.

### 5.2 Layer B, and occurrence resolution is enough: contact, and how close

*Did the robot contact the human?* is answered at the coarsest level in the
project — one occurrence flag, timestamped to ±1.0 s, in a 1,004,544-byte artifact —
and it AGREEs with ground truth recomputed from the raw stream by forward
kinematics. *How close did it get?* likewise, to within 0.0007 m of a 0.01 m
budget, carried on the `closest_approach` occurrence's `min_distance_m`.

Two things have to be said about that agreement and neither weakens the other.
(Three, counting the one the report says about itself: `long_run` contains no
contact, so the contact row is **agreement on a negative** at every level, and the
check is shown able to say no in `tests/test_bench.py` rather than here.)

**It is a real result about resolution.** These are the two questions an incident
report leads with, and they survive a 2.5x reduction in retained bytes. That is
Claim 1's replacement doing its job: the questions this project cares about mostly
do *not* need the resolution `reg` chose without noticing it was choosing.

**It is still only as strong as perception.** The occurrence layer's closed-world
reading — *no `contact_began` row means no contact* — is legitimate only because
the retention rule in `meta` says one would have been written
([`docs/lossiness.md`](lossiness.md), Level 1). That rule is a promise about the
*builder*, not about the perceiver. If the entity's position was wrong, a contact
that happened produces no row and the artifact's silence reads, correctly by its
own rule and wrongly in fact, as "no contact". No amount of resolution or chain
integrity touches this.

### 5.3 Layer B, and it needs transition resolution: the timeline, and *when*

`separation_timeline` is COULD-NOT-EVALUATE at occurrence level, and the report
says why in the artifact's own words: *this level holds no per-frame separation*.
That is a refusal, and [`docs/lossiness.md`](lossiness.md) requires that it never
resolve into agreement —
`tests/test_bench.py::test_a_level_that_could_not_evaluate_does_not_summarise_as_
agree` is the gate. An empty answer is not a matching answer.

`time_of_closest_approach` is the more interesting refusal, because the coarse
level *does* produce an answer: 46.0000 s, where the nearest instant whose
separation is within one distance quantum of the minimum is 45.9800 s.
Δ 0.0200 s, against a 0.01 s tolerance.

**This read `DISAGREE` until issue #61, and the paragraph that stood here argued
the verdict was fine because "the occurrence layer never promised better than
±1.0 s."** That argument is right and it is an argument against the verdict, not
for it. A level graded against a precision twenty times finer than it advertises
is not answering wrongly; the check was asking a question the level had already
said it could not take. `ResolutionPoint.verdict` then propagated `DISAGREE`
upward and the whole DSSAD-aligned level — the one Claim 1 rests on — read as
broken in a document about what it can be trusted for.

The comparison now consults the level's own quantum, and
[`docs/lossiness.md`](lossiness.md) carries the rule beside *Unanswerable* #4
where the principle it specialises already lived: inside `TIME_TOL_S` is `AGREE`,
outside it but inside the quantum is `COULD-NOT-EVALUATE`, and outside the
quantum too is still `DISAGREE` — a level that misplaces an event by more than
its own resolution *is* wrong, and that verdict has to stay reachable.

So the measurement says a question phrased *when exactly* cannot be **put** to a
record whose timestamps are seconds wide — not that such a record answers it
falsely. And note the conditional this row is easy to over-read: `occurrence`
locates events **sustained longer than its quantum** and refuses brief ones.
`tests/test_bench.py::test_a_sustained_minimum_is_locatable_even_at_one_second`
measures the sustained case coming back `AGREE` at the same 1.0 s. Whether a
coarse timestamp suffices is a property of the event, not of the recorder.

So this row carries both qualifiers: it is conditional on perception **and** it is
conditional on retaining 149.72 MB/h instead of 60.29 — both figures **at a 50 Hz
control rate**, and both linear in it, so the retention this row asks for scales
with the loop the robot runs. The two qualifiers are independent, and a deployment
could fail either one on its own.

### 5.4 Layer A, certifiable and now measured

Rows 2–4 — *did the policy exceed its declared bound*, *what did it declare*, *was
the record tampered with* — are the asymmetry of §2 and the reason this project
exists. **This section used to say nothing in the project could measure them, and
that it would change by measurement when Milestone 3 landed. It landed, and this
is that change.**

The artifact carries the records now: 120 declarations, 3,000 verdicts, 24 faults
and 3,120 chain records over 60 s of robot time. `reg.bench --resolution` prices
four of them — `declared_bound`, `violations`, `verdicts`, `verify_chain` —
against **the record stream the run emitted**, held in memory and never read back
out of the artifact under test. Ground truth that rereads the artifact cannot
fail, which is the same trap `first_envelope_intersection` is still excluded for
(row 1: its only available ground truth is `reg.envelope` itself).

The resolution finding is not the one this section anticipated. **Layer A is very
nearly resolution-independent**: no level coarsens the record tables, so
`violations` and `verify_chain` are `AGREE` at ±1.0 s. The two that do degrade
degrade for a Layer B reason — `declared_bound` and the clamped bound inside
`verdicts` name regions that live in the `edge` and `envelope` tables the
occurrence view empties. The certifiable layer survives coarsening; what it says
*about the scene* does not.

### 5.5 The trap: `SEPARATION` is Layer B

The distance from the arm to an entity feels proprioceptive. It is computed from
the robot's own body — forward kinematics on `q`, one `unary_union` of link
polygons — and the temptation is to call it Layer A and pick up the strongest
claim in the project for free.

It is Layer B, and the schema already says so:
`EdgeSpec("B", "RobotConfig", "Entity", "min_distance")`. A distance has two
endpoints. One of them is the entity, and where the entity is comes from
perception in any real system, so the number inherits perception's failure modes
exactly as `CONTACT` does. `min_separation` and `time_of_closest_approach`, which
are its two most quotable outputs, inherit them too.

This is not a convention that a careful reviewer enforces. `store.layer_of` reads
the layer off `EDGE_SPECS` and refuses a type that is not in it — there is no
"unknown layer" and no default — `store.open_edge` never takes a layer from its
caller, the schema carries `CHECK (layer IN ('A', 'B'))`, and
`test_layer_b_is_exactly_the_entity_naming_edges` asserts that an entity-naming
edge is Layer B and can be nothing else. Retagging `SEPARATION` as A to make a
claim read better requires editing a test whose docstring says why not.

One qualification, and it does not touch `SEPARATION`. Naming an entity is
*sufficient* for Layer B; since issue #84 it is no longer *necessary*, because
`HAS_ENVELOPE` names no entity and is still Layer B when the `Limits` it was
computed from were perception-derived (§7). So that one edge type is the
exception to "the layer never comes from the caller" — `open_edge` requires it to
be stated and `layer_of` refuses to answer for it — and the exception runs in the
conservative direction: an omission is a refusal, never an `A`.

---

## 6. What a real deployment changes

**Here, Layer B is simulator ground truth, and it is therefore perfect.** The
human's position in the raw stream is the position the simulator used to move it.
There is no detection, no association, no latency, no occlusion, and no false
negative. Every Layer B agreement measured in §3 was measured against a perceiver
that cannot be wrong, which is exactly the perceiver a real system does not have.

In a real system the entity positions come from a perception stack with its own
failure modes: missed detections, identity switches, depth error, motion blur,
latency between the observation and the timestamp it is recorded against,
degradation outside the conditions it was validated in, and adversarial or merely
unlucky inputs. **Every Layer B claim in the table above inherits an assurance
case that this project does not attempt.** Concretely, that assurance case would
have to establish, at minimum:

- a characterized detection performance for the entity classes that matter, with
  the operating conditions it holds in stated;
- a bound on position error, and a bound on *timestamp* error — a separation is a
  distance between two things at one instant, and a perceptual latency shifts the
  instant;
- a treatment of the missing entity, which is the failure this artifact is
  structurally blind to. [`docs/lossiness.md`](lossiness.md) *Unanswerable* #2 says
  it already: absence of an entity from the graph is not evidence of its absence
  from the room. A person nobody detected leaves an artifact that answers *no
  contact* with total confidence;
- and evidence, retained, that the stack running at the time was the one that was
  validated. DSSAD's `R157SWIN` element is the shape of that requirement, and
  **this project does not meet it** (issue #109): what the occurrence layer
  carries is `recorder_version`, the build of `reg` that was *watching* and the
  envelope parameters it watched with. That is the evidence tool, not the stack
  under investigation, and it is not offered as the element
  ([`prior-art.md` §9](prior-art.md)). A real deployment has to bind a policy
  build, as a required caller-supplied input; a simulator with no policy vendor
  has nothing to bind, and filling the column anyway would be a fiction.

Two consequences worth stating plainly.

**The Layer A rows do not move.** That is the point of the boundary. An incident
report's attestation half — what the policy declared, what enforcement did, that
the record is intact — is answerable at the same strength in a real deployment as
here, because the perception stack is not in its dependency set.

**The Layer B rows move all the way down to that assurance case, and no further
work on `reg` raises them.** A finer quantum, a better envelope, a longer chain:
none of it touches the conjunct that limits them. That asymmetry is the deliverable
of Claim 3, and it is why the layered structure earns its complexity.

**What that deliverable claims, narrowly.** Conditional assurance is not new and
this document should not imply it is. **ConSerts** (Schneider & Trapp) formalised
guarantees that hold conditional on runtime evidence supplied by components
carrying their own assurance, and **dynamic safety cases** (Denney & Pai) update
the argument as that evidence arrives — [`docs/prior-art.md`](prior-art.md) §13.
Against that, two things here are narrow enough to survive:

1. **The conditionality is retained with the answer.** A ConSert resolves at
   runtime and the resolution is a control decision — *may I act*. Here the
   dependency is a column on the record, so the question *what did this answer
   depend on* can be put to the artifact months later, by someone the robot never
   met. That is a different question — *what may be concluded afterwards* — and it
   is the one this project exists for.
2. **The case handled is the one with no assured component.** A ConSert demand is
   discharged by a component that carries its own assurance; when none can, the
   guarantee is withdrawn. `reg` has no such component to appeal to and does not
   withdraw the answer — it answers and marks what the answer rests on, which is
   the only option available when the perceiver is a learned model that will never
   carry an assurance argument.

Neither is a claim to have invented conditional assurance. Both are claims about
what happens to the condition **after** the robot has stopped, which is where this
document's asymmetry lives.

---

## 7. What this document does not claim

- **Not that Layer A is unconditionally trustworthy.** A Layer A answer here still
  inherits: the envelope is an inner approximation
  ([`docs/limitations.md`](limitations.md) §2), envelope geometry on non-evidence
  frames is recomputed rather than stored and that recomputation assumes the same
  code and the same shapely ([`docs/limitations.md`](limitations.md) §1), and both
  chain keys live in one process — *the structure of non-repudiation, not
  non-repudiation* ([`docs/plan.md`](plan.md) Phase 6). Milestone 3 landed and did
  not change that last one: `reg.chain.Keyring` holds both roles, `reg.chain`'s
  own honesty note says so, and the independence the pattern needs is an
  enforcement key in hardware the policy vendor cannot reach. **Still holds, in
  the present tense.** "Certifiable" here means *its failure modes are
  characterizable from proprioception*, not *they have been characterized*.
- **Not that a Layer A envelope is Layer A whatever its `Limits` are.** The
  envelope has two inputs and only one of them is kept out of the world by
  structure. `ProprioState` names no entity and cannot, but `Limits` names none
  either and its *values* can still be perception-derived: under **ISO/TS 15066 /
  ISO 10218-2:2025 speed-and-separation monitoring** — which
  [`docs/plan.md`](plan.md) §67 cites approvingly — the commanded speed bound is
  a function of the measured separation distance, so `qd_max` comes from a
  perceiver and everything integrated under it inherits that perceiver. A
  field-name test cannot catch a taint that arrives in a number. **The artifact
  now records which case it is in**: `Limits.source` is required with no default,
  `reg.envelope.envelope_layer` maps it to a layer, and the `HAS_ENVELOPE` edge
  is tagged from that — proprioceptive bounds give a Layer A edge, derived bounds
  give a Layer B one, and `meta['limits_source']` carries the provenance so a
  recomputed envelope inherits it too. An artifact that does not carry the key is
  a **could-not-evaluate**, not a proprioceptive one: nothing reads its absence as
  the clean case. What this closes is the *mislabelling*; an SSM deployment's
  envelopes are as dependent on perception as they always were, and the change is
  that the dependence is now in the column Claim 3 queries instead of nowhere.
  *Recorded 2026-08-21, issue #84.*
- **Not that a two-value provenance is how assurance is actually argued.** The
  binary above matches this project's two layers and it is a simplification, said
  out loud here because the alternative was considered rather than unseen. An
  external regulatory review argued the binary is wrong in **both** directions: an
  IEC 61496 safety scanner rated PLd is perception *with characterized failure
  modes* and still lands in `DERIVED`, while Layer A's encoders need ISO 13849
  cat-3 dual channel before they carry a safety claim at all and still land in
  `PROPRIOCEPTIVE`. The better model is a tag **plus an integrity attribute** —
  one more column, and the taxonomy becomes legible to people who already work
  this way. It was rejected for **scope, not for correctness**: it rewrites this
  document, and this document is normative for what the project may claim, so it
  is a decision and not an implementation. *Issue #84.*
- **Not that the layer tag makes a Layer B answer safe to quote.** It makes it
  legibly conditional. Quoting a Layer B answer without its condition is the
  failure this document exists to prevent, which is why the strength column says
  *only as strong as perception* and not *subject to perception error*.
- **Not that the occurrence level is sufficient.** Row by row against the curve in
  §3: it answers rows 2, 4, 5 and 6; it **refuses** rows 3, 10 and 11 with a stated
  COULD-NOT-EVALUATE; it holds no substrate at all for rows 1, 7 and 8, whose
  answers live in the `edge` and `envelope` tables it empties; and row 9 is
  `EXCLUDED` from the curve entirely, because a threshold test needs a threshold
  and nothing supplies one. *Amended 2026-08-21: this bullet used to read "It is
  sufficient for rows 5 and 6, refuses row 10, answers row 11 outside tolerance,
  and holds no substrate at all for rows 1, 7 and 8." Two things had moved under
  it. Row 11 is a refusal now, not an answer outside tolerance — issue #61 stopped
  grading a level against a precision twenty times finer than it advertises
  (§5.3). And rows 2, 3 and 4 were absent because nothing had measured them; two
  of the three are now the coarsest level's strongest answers.* "How coarse can
  evidence get" has a measured answer and the answer is *it depends on the
  question* — which is the taxonomy, not a disappointment.
- **Not a novelty claim about obstacle-independent reachability.** See
  [`docs/prior-art.md` §4](prior-art.md): that is standard practice, and this
  document borrows it rather than announcing it.
- **~~Not a completed Claim 3 for the attestation half.~~ Retired by measurement
  on 2026-08-20 (issue #63); recorded here 2026-08-21.**
  This bullet read: *"Rows 2–4 are structure awaiting measurement, and they say
  so."* They no longer say so, and the sentence is kept rather than deleted
  because what this document used to claim is part of what it is for. Milestone 3
  landed the records and issue #63 measured them: §4 marks rows 2–4 *certifiable,
  and measured*, §5.4 prices four attestation questions against the record stream
  the run emitted, and the curve in §3 puts `violations` and `verify_chain` at
  AGREE on every level. What replaces the bullet is narrower and lives above it:
  the measured chain was walked under `reg.bench.measurement_keyring`, which is
  derived from the run seed and **attests to nothing** — it shows `verify_chain`
  survives coarsening, not that anything was attested — and both keys are still in
  one process.
- **Not that every row's agreement has been measured.** Four rows carry
  **unmeasured** as an agreement verdict in §4, and for two distinct reasons. Rows
  1, 7 and 8 are unmeasured *deliberately*: their only available ground truth is
  `reg.envelope` itself, and a check whose ground truth reruns the code under test
  cannot fail. Row 9 is unmeasured because it takes a threshold and this project
  will not invent one. Neither reason is a measurement that came back clean.

---

## 8. Reproducing the evidence in this table

```bash
pip install -e ".[dev]"

# The resolution verdicts in §3 and in rows 2, 3, 4, 5, 6, 10 and 11.
python -m reg.bench --resolution --out bench/results.md

# The layer values in every row. Derived from the type, never from a caller —
# except HAS_ENVELOPE, whose layer follows Limits.source (issue #84) and so
# prints as both. Not a default either way: `open_edge` refuses to write that
# edge with no layer stated, and `layer_of` refuses to answer for its type.
python -c "from reg import store; print(store.EDGE_SPECS); print(store.OCCURRENCE_SPECS)"

# Where this artifact's limits came from. A missing key is could-not-evaluate.
python -c "from reg import store, graph; c = store.connect('runs/long_run.sqlite'); print(store.get_meta(c, graph.META_LIMITS_SOURCE))"

# The tags as invariants, including the one that fails on an untagged edge type.
pytest tests/test_graph.py -k layer tests/test_layer_boundary.py
```

`bench/results.md` is gitignored deliberately: the numbers are regenerated from
the seeds in the report header, and a committed copy would make measurements look
like fixtures. The run above is `long_run` at 3,000 frames, seed 0, `n_samples=16`,
occurrence resolution 1.0 s.

---

## See also

- [`docs/lossiness.md`](lossiness.md) — **what is discarded**, the supported
  question set every row of the taxonomy is drawn from, the three resolution
  levels, and *Unanswerable* #7: whether perception was correct is a question the
  artifact contains no evidence bearing on. This document states the dependence;
  it does not discharge it.
- [`docs/limitations.md`](limitations.md) — **the under-approximation** (§2) that
  restricts row 1 to the positive direction, and the recomputation dependency (§1)
  that a Layer A answer still inherits.
- [`docs/prior-art.md` §4](prior-art.md) — **why the obstacle-independent envelope
  is standard practice, not a contribution** (ARMTD, ARMOUR), and the
  over-/under-approximation vocabulary this document uses. Also **§9**, DSSAD's
  data elements, which the occurrence level is shaped from.
- [`docs/plan.md`](plan.md) — **Phase 9**, the single-axis taxonomy this document
  supersedes with two; **Claim 1, "What replaces it"**, the resolution question;
  **Phases 3, 4 and 6**, which built the attestation records rows 2–4 rest on.
