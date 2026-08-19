# Sufficiency boundary — which audit claims survive an uncertifiable perceiver

**Status:** normative for what this project may claim · written 2026-08-19 ·
[`docs/plan.md`](plan.md) Phase 9, Claim 3's deliverable, and the last piece of
Milestone 2 · keep current

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

- The asymmetry is a claim about **structure**, and in Milestone 2 the structure
  is all that exists. `reg.declare` and `reg.chain` landed with issues #39/#40, but
  no artifact carries declarations or verdicts yet: the schema (v4) has no
  declaration or verdict table, `EDGE_SPECS` has no `DECLARED`, `ADJUDICATED`,
  `ENFORCED` or `FOLLOWS`, and `reg.query.QUERIES` has none of queries 5–8. Rows
  9–11 of the taxonomy below are therefore marked **unmeasured**, not asserted.
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
is answered from a DSSAD-shaped occurrence flag at 4.43 MB/h, and is still only as
strong as whatever said where the human was.

The three levels are defined in [`docs/lossiness.md`](lossiness.md), *The three
resolution levels*: **occurrence** (DSSAD-aligned, timestamps at ±1.0 s),
**transition** (the edge layer, endpoints at `TIME_TOL_S` = 10 ms), and
**per-frame**. All three are views of one build.

### The measured curve

`long_run` at 3,000 frames (60.0 s of robot time), `n_samples=16`, seed 0,
occurrence resolution 1.0 s — reproduced for this document with
`python -m reg.bench --resolution`:

| level | timestamp resolution | SQLite B | bytes/hour | nodes | edges | occurrences | `min_separation` | `time_of_closest_approach` | `separation_timeline` | `did_contact_occur` |
|---|---|---|---|---|---|---|---|---|---|---|
| `occurrence` | 1.0 s | 73,728 | **4.43 MB/h** | 22 | 0 | 18 | AGREE | **DISAGREE** | **COULD-NOT-EVALUATE** | AGREE |
| `transition` | 0.01 s | 897,024 | **53.84 MB/h** | 2,747 | 3,461 | 0 | AGREE | AGREE | AGREE | AGREE |
| `per-frame` | 0.01 s | 2,301,952 | **138.16 MB/h** | 2,747 | 12,168 | 0 | AGREE | AGREE | AGREE | AGREE |

Twelve times the bytes buys two questions and no others. That is the entire
content of the resolution axis, and the rows below cite it rather than restating
it.

---

## 4. The taxonomy

Each row's layer is the value the schema assigns, and each row's resolution is a
verdict from the curve above — or the word **unmeasured**, where nothing in this
project has measured it yet. A row nothing supports is marked unmeasured; it is
not omitted, and it is not softened into a claim.

**How to read the strength column.**

- **certifiable** — answerable from Layer A evidence alone. Inherits no perceptual
  failure mode. Still inherits this project's own stated limitations (§7).
- **certifiable in structure, unmeasured** — Layer A by the schema's own
  vocabulary, but no artifact in this milestone holds the records, so nothing has
  been measured. The honest reading is "this is what the structure will support",
  not "this is supported".
- **only as strong as perception** — the answer is a conjunction with *the entity
  was where the artifact says it was*, and this project supplies no evidence for
  that conjunct. It is the finding, not a caveat.

| # | Question (query) | Layer, and the evidence for it | Minimum resolution, and the evidence for it | Claim strength |
|---|---|---|---|---|
| 1 | Could the robot have reached (x, y) at t? (`reg.graph.envelope_at`) | **A** — `HAS_ENVELOPE` is `EdgeSpec("A", "RobotConfig", "Envelope", …)`; it is the only Layer A edge type, and the only one naming no `Entity` | **transition** — the occurrence view holds **0 edges** (curve above) and, by the projection's own rule, no `envelope` and no `robot_config` rows either, so the question has no substrate there. Agreement at the transition level is **unmeasured, deliberately**: the only available ground truth is `reg.envelope` itself, and a check whose ground truth reruns the code under test cannot fail | **certifiable**, in the positive direction only |
| 2 | Did the policy exceed its declared bound? (`violations(window)`) | **A** — [`docs/lossiness.md`](lossiness.md) supported-question set, query 6. No entity is named by a declaration or a verdict | **unmeasured** — no declaration or verdict table in schema v4, no `DECLARED`/`ADJUDICATED`/`ENFORCED` in `EDGE_SPECS`, no such query in `reg.query.QUERIES`. Milestone 3 | **certifiable in structure, unmeasured** |
| 3 | What did the policy declare at t? (`declared_bound(t)`) | **A** — same, query 5 | **unmeasured** — same. `reg.declare.Declaration` exists (#39/#40); nothing writes one into an artifact | **certifiable in structure, unmeasured** |
| 4 | Was the record tampered with? (`verify_chain()`) | **A** — same, query 8. A hash chain and a MAC over records that name no entity | **unmeasured** — `reg.chain.verify` checks a record's link and MAC today, but no artifact carries a chain and there is no `verify_chain()` query | **certifiable in structure, unmeasured** |
| 5 | Did the robot contact the human? (`did_contact_occur`) | **B** — `CONTACT` is `EdgeSpec("B", "RobotConfig", "Entity", …)`; `contact_began` / `contact_ended` are `OccurrenceSpec("B", "entity", …)` | **occurrence** — AGREE at 1.0 s and 4.43 MB/h. Caveat kept attached: in this fixture that is **agreement on a negative** (the run contains no contact); `tests/test_bench.py::test_the_contact_check_says_no_when_the_occurrence_layer_is_wrong` is where the check is shown able to say no | **only as strong as perception** |
| 6 | How close did the robot get to the human? (`min_separation`) | **B** — `SEPARATION` is `EdgeSpec("B", "RobotConfig", "Entity", "min_distance")`; `closest_approach` is `OccurrenceSpec("B", "entity", "min_distance_m")` | **occurrence** — AGREE, Δ 0.0007 m against a 0.01 m (`DISTANCE_TOL_M`) predicate | **only as strong as perception** |
| 7 | Was the human inside the reachable set, and when did it first enter? (`first_envelope_intersection`) | **B** — `INTERSECTS` is `EdgeSpec("B", "Envelope", "Entity", "overlap_area")` | **transition** — `reg.query` declares it `answerable_from={edge}`: the occurrence layer locates entry only to ±1.0 s and carries no overlap area, so it cannot produce the intervals this query returns. Agreement **unmeasured**, for the same envelope-ground-truth reason as row 1 | **only as strong as perception** |
| 8 | Which entities were inside the envelope during [t₀, t₁]? (`reachable_entities`) | **B** — `INTERSECTS`, as above | **transition** — `answerable_from={edge}`. The predicate is exact set equality with no tolerance to spend, and membership derived from ±1.0 s events would be exact-looking and wrong at the edges. Agreement **unmeasured**, as row 1 | **only as strong as perception** |
| 9 | Which intervals had the human within a threshold? (`frames_at_risk`) | **B** — `SEPARATION`, as row 6 | **transition** — `answerable_from={edge}`: a threshold test is a per-frame question about a metric, and the occurrence layer retains no metric between events. Not among the curve's four questions, so **unmeasured** as an agreement verdict | **only as strong as perception** |
| 10 | What was the separation at every frame? (`separation_timeline`) | **B** — `SEPARATION`, as row 6 | **transition** — occurrence: **COULD-NOT-EVALUATE** ("this level holds no per-frame separation"); transition: AGREE, worst frame Δ 0.0096 m over 3,000 frames against 0.01 m | **only as strong as perception** |
| 11 | When exactly was the closest approach? (`time_of_closest_approach`) | **B** — as row 6 | **transition** — occurrence: **DISAGREE**, 46.0000 s against 5 frames within 0.01 m of the minimum, nearest at 45.9800 s, Δ 0.0200 s against `TIME_TOL_S` = 0.01 s; transition: AGREE, Δ 0.0000 s | **only as strong as perception, *and* needs 10 ms** |

Rows 1 and 5–11 are the questions Milestone 2 can actually be asked. Of those,
**exactly one is Layer A** — and it is the one that says what the machine could
have done, not what happened to anyone.

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

**What it does not license, and this is not a footnote.** The envelope is a
sampling-based *under*-approximation. "The robot **could have** reached (x, y)" is
supported; "**could not have**" is not, at any resolution and by any query
([`docs/lossiness.md`](lossiness.md) *Unanswerable* #3,
[`docs/limitations.md`](limitations.md) §2, [`docs/prior-art.md` §4](prior-art.md)
for the outer-approximation machinery a real claim in the negative direction would
need). A certifiable claim in the wrong direction is not a safety claim.

**And it dies first under coarsening.** The occurrence view holds 0 edges: the
only Layer A rows available to it at all are `run_began` and `run_ended`, i.e.
*this run happened, between these two instants, under this software version*. The
DSSAD-aligned level records that the run existed and what happened to the human in
it; it records nothing whatever about what the machine could have done. That is
worth saying to anyone who reads "occurrence-level evidence is enough" as a
general conclusion — it is enough for two of the questions measured here, and it
is the level at which the certifiable question stops being answerable.

### 5.2 Layer B, and occurrence resolution is enough: contact, and how close

*Did the robot contact the human?* is answered at the coarsest level in the
project — one occurrence flag, timestamped to ±1.0 s, in a 73,728-byte artifact —
and it AGREEs with ground truth recomputed from the raw stream by forward
kinematics. *How close did it get?* likewise, to within 0.0007 m of a 0.01 m
budget, carried on the `closest_approach` occurrence's `min_distance_m`.

Two things have to be said about that agreement and neither weakens the other.
(Three, counting the one the report says about itself: `long_run` contains no
contact, so the contact row is **agreement on a negative** at every level, and the
check is shown able to say no in `tests/test_bench.py` rather than here.)

**It is a real result about resolution.** These are the two questions an incident
report leads with, and they survive a 12x reduction in retained bytes. That is
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

`time_of_closest_approach` is the more interesting failure, because the coarse
level *does* answer it and the answer is wrong under the predicate the fine level
advertises: 46.0000 s where the nearest instant whose separation is within one
distance quantum of the minimum is 45.9800 s. Δ 0.0200 s, against a 0.01 s
tolerance. The DISAGREE is not a defect to fix — the occurrence layer never
promised better than ±1.0 s, and it happened to land 20 ms out. It is the
measurement saying that a question phrased *when exactly* cannot be answered from
a record whose timestamps are seconds wide, and that this is visible only because
the fine layer is still there to be compared against.

So this row carries both qualifiers: it is conditional on perception **and** it is
conditional on retaining 53.84 MB/h instead of 4.43. The two are independent, and
a deployment could fail either one on its own.

### 5.4 Layer A, structurally certifiable, and not yet measurable

Rows 2–4 — *did the policy exceed its declared bound*, *what did it declare*, *was
the record tampered with* — are the asymmetry of §2 and the reason this project
exists. They are also the rows nothing in this milestone can measure, and the
correct thing to write in that cell is so.

What exists: `reg.declare` builds and signs a `Declaration`; `reg.chain` produces
the hash links and the keyed MACs and verifies both. What does not exist: any
artifact containing them. Schema v4 has no declaration or verdict table;
`EDGE_SPECS` has four edge types and none of them is `DECLARED`, `ADJUDICATED`,
`ENFORCED` or `FOLLOWS` — and that absence is deliberate, because *"an edge type
nothing emits makes 'no declarations in this run' indistinguishable from 'this
build does not do declarations'"* (`reg.graph`). `reg.bench --resolution` excludes
queries 5–8 for the same reason: they would print COULD-NOT-EVALUATE at every
level for a reason that has nothing to do with resolution.

The claim these rows will support is strong and the evidence for it is currently a
design, so the table says **certifiable in structure, unmeasured**. When Milestone
3 lands, that cell is what has to change, and it changes by measurement.

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
`test_layer_b_is_exactly_the_entity_naming_edges` re-derives every expected value
from `"Entity" in (spec.src_kind, spec.dst_kind)`. Retagging `SEPARATION` as A to
make a claim read better requires editing a test whose docstring says why not.

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
  validated. DSSAD's `R157SWIN` element is the shape of that requirement, and the
  occurrence layer carries this project's analogue (`sw_version`) for the builder —
  not for a perceiver, because there is none.

Two consequences worth stating plainly.

**The Layer A rows do not move.** That is the point of the boundary. An incident
report's attestation half — what the policy declared, what enforcement did, that
the record is intact — is answerable at the same strength in a real deployment as
here, because the perception stack is not in its dependency set.

**The Layer B rows move all the way down to that assurance case, and no further
work on `reg` raises them.** A finer quantum, a better envelope, a longer chain:
none of it touches the conjunct that limits them. That asymmetry is the deliverable
of Claim 3, and it is why the layered structure earns its complexity.

---

## 7. What this document does not claim

- **Not that Layer A is unconditionally trustworthy.** A Layer A answer here still
  inherits: the envelope is an inner approximation
  ([`docs/limitations.md`](limitations.md) §2), envelope geometry on non-evidence
  frames is recomputed rather than stored and that recomputation assumes the same
  code and the same shapely ([`docs/limitations.md`](limitations.md) §1), and in
  Milestone 3 both chain keys will live in one process — *the structure of
  non-repudiation, not non-repudiation* ([`docs/plan.md`](plan.md) Phase 6).
  "Certifiable" here means *its failure modes are characterizable from
  proprioception*, not *they have been characterized*.
- **Not that the layer tag makes a Layer B answer safe to quote.** It makes it
  legibly conditional. Quoting a Layer B answer without its condition is the
  failure this document exists to prevent, which is why the strength column says
  *only as strong as perception* and not *subject to perception error*.
- **Not that the occurrence level is sufficient.** It is sufficient for rows 5 and
  6, refuses row 10, answers row 11 outside tolerance, and holds no substrate at
  all for rows 1, 7 and 8. "How coarse can evidence get" has a measured answer and
  the answer is *it depends on the question* — which is the taxonomy, not a
  disappointment.
- **Not a novelty claim about obstacle-independent reachability.** See
  [`docs/prior-art.md` §4](prior-art.md): that is standard practice, and this
  document borrows it rather than announcing it.
- **Not a completed Claim 3 for the attestation half.** Rows 2–4 are structure
  awaiting measurement, and they say so.

---

## 8. Reproducing the evidence in this table

```bash
pip install -e ".[dev]"

# The resolution verdicts in §3 and in rows 5, 6, 10 and 11.
python -m reg.bench --resolution --out bench/results.md

# The layer values in every row. Derived from the type, never from a caller.
python -c "from reg import store; print(store.EDGE_SPECS); print(store.OCCURRENCE_SPECS)"

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
  **Phases 3, 4 and 6**, the attestation records rows 2–4 are waiting on.
