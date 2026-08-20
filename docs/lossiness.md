# Lossiness contract

**Status:** normative · written 2026-08-18, before the graph exists · keep current

This document is a **design constraint on the evidence graph, not a description of
it**. [`docs/plan.md`](plan.md) Phase 5 requires it to land before any graph code
is written, for the obvious reason: a lossiness contract written afterwards
describes whatever the implementation happened to keep, which is not a contract at
all.

The graph is **not a compression of the raw stream**. It is a deliberate discard of
everything provably irrelevant to a fixed, enumerated question set. The difference
matters: a compressor is judged by ratio, and a discard is judged by whether the
questions it promised to answer still get the right answers. This file is what makes
that judgement possible instead of convenient.

The same conclusion — that an *event-level* record, not continuous state, is the
right retention granularity for an autonomous system — was already reached by
regulation for automated driving. See [`docs/prior-art.md` §1](prior-art.md), on
UNECE **DSSAD** under UN R157: it records discrete events (activation, deactivation,
partial failure, transition demand, minimal-risk manoeuvre) precisely so that months
later someone can reconstruct who was driving. `reg` is not inventing the retention
principle; it is applying it to a manipulator and stating the loss explicitly.

**One thing this document said only implicitly until 2026-08-19.** The *Retained*,
*Discarded* and *Unanswerable* lists below describe one resolution — the finest
one — and issue #35 added two more beside it. Read
[The three resolution levels](#the-three-resolution-levels) before reading the
lists as the whole contract: the levels are why "how much resolution does this
answer actually need" is now a measured question rather than an assumption.

---

## The supported question set

"Provably irrelevant" is meaningless without saying *to what*. Everything below is
relative to this list, which is [`docs/plan.md`](plan.md) Phase 7's query set and
nothing else:

| # | Query | Layer |
|---|---|---|
| 1 | `separation_timeline(entity_id)` — min distance robot-to-entity over time | B |
| 2 | `first_envelope_intersection(entity_id)` — first entry into the reachable set, plus overlap intervals | B |
| 3 | `frames_at_risk(entity_id, threshold)` — intervals exceeding threshold before a contact event | B |
| 4 | `reachable_entities(t_start, t_end)` — entities ever inside the envelope in a window | B |
| 5 | `declared_bound(t)` — what the policy claimed at time `t` | A |
| 6 | `violations(window)` — commanded actions outside their declared bound, with fault code | A |
| 7 | `verdicts(declaration_id)` — what enforcement did, and why | A |
| 8 | `verify_chain()` — integrity over the full record | A |
| 9 | `incident_report(t_incident)` — 1–8 composed into one structured answer | A + B |

**Adding a query to this list is a change to this contract.** If a new question
needs something currently in *Discarded*, the discard is what has to change, and it
changes here first — before the graph is taught to retain it. Answering a new
question out of whatever the graph happens to still contain is exactly the failure
this document exists to prevent.

---

## Retained

Each entry is a claim that the graph can be tested against.

1. **Every topological relationship between the reachable set and every entity in
   the entity set** — for each `(envelope, entity)` pair, whether it was disjoint,
   intersecting, or containing — as an interval `[t_start, t_end]`, at the
   resolution in [Quantization tolerances](#quantization-tolerances).
2. **The metric relationships alongside them** — `min_distance` per
   `(RobotConfig, entity)` pair and `overlap_area` per `INTERSECTS` edge, quantized
   as stated below, for every interval in which the relationship held.
3. **Exact timing of every relationship transition** — the timestamp at which a pair
   changed topological class, or at which a metric quantity crossed a quantization
   boundary, to `TIME_TOL_S`. Transitions are the events; the intervals between them
   are the compression.
4. **Every `Declaration`, in full** — `declaration_id`, `seq`, `t_issued`,
   `horizon`, `action_class`, the declared envelope geometry, `prev_hash`, `mac`.
   Declarations are coarse and cheap; none is ever summarised or dropped.
5. **Every `Verdict`, in full** — `verdict_id`, `declaration_id`, `seq`, `t`,
   `outcome`, `fault`, the clamped envelope where one was applied, `prev_hash`,
   `mac`.

   **Verbatim, and stored 2026-08-19 (issue #45).** "In full" is stronger than it
   reads: every field goes into the artifact exactly as the record was signed, and
   nothing is re-signed or re-hashed on the way in. A record read back verifies —
   or fails to — precisely as it did before it was written, because a store that
   could recompute a MAC is a store that can quietly repair a broken chain. The
   two record timestamps are stored unquantized for the same reason: `TIME_TOL_S`
   is the resolution *observations* are reported at, and a record's `t_issued` is
   a value the MAC covers.

   **One verdict per commanded action, never one per declaration.** The `Verdict`
   table and the `ADJUDICATED` edges hold as many rows as there were
   adjudications: at a 0.5 s replan interval `declared_violation` produces 251
   verdicts — 122 PERMIT and 129 CLAMP — against 11 declarations that all carry
   an identical `declared_envelope`, and two of those declarations are
   adjudicated both ways. Collapsing them would discard *when the violation
   began*, which is the second clause of the demo sentence.
6. **Every fault, with full attribution** — the fault code from the Phase 4
   taxonomy, the declaration it was raised against, the record that triggered it,
   and which key signed each side. A fault with no attributable origin is a defect,
   not a retained fault.
7. **The complete hash chain** — every `FOLLOWS` link between consecutive records,
   unbroken, so `verify_chain()` is answerable from the graph alone.

   There are **two** chains, not one: declarations link to declarations under the
   policy key and verdicts to verdicts under the enforcement key, each beginning
   at the genesis hash. "Unbroken" is enforced at build time — a record whose
   `prev_hash` is not its predecessor's chain hash is refused, artifact and all,
   because a `FOLLOWS` edge written across a break would let a chain walk cleanly
   over records nobody ever saw.

   **`Acknowledgment` is not stored yet, and the gap is a refusal rather than a
   hole.** Acknowledgments share the verdict chain, so a run containing one has a
   verdict whose `prev_hash` names a record the artifact would not hold — and that
   stream is refused rather than stored with a link written over it. The fixtures
   that produce a passivation arrive with issue #46, and so does the row it needs.
8. **Envelope *identity and scalars* on every envelope the artifact keeps** — every
   `envelope` row records `envelope_hash`, `area`, `horizon`, and `source`
   (`computed` / `declared` / `clamped`). There is no such thing here as a row that
   says less. All three sources are retained separately; a clamp is only legible if
   the declared and the computed bound both survive.

   Two narrower clauses sit under this one and both are in *Discarded*, because both
   are things the contract could have kept and does not: **which frames get a row at
   all** is #10, and **which of those rows carry the polygon** is #9.

   This clause read "at every material change" until 2026-08-18, when issue #29
   replaced it. A moving arm has a materially different envelope on *every* frame,
   so that reading put one row per frame into the artifact for exactly the runs this
   project exists to record — linear in the frame count, and no amount of shrinking a
   row changes the shape of linear-in, linear-out. The replacement narrows *when a
   row exists*; it does not narrow what a row says.
9. **The layer tag on every edge** — `A` or `B`, per Phase 9. Claim 3 is a query
   over these tags, so an untagged edge is an unusable edge.
10. **The run's provenance** — scenario name, seed, tolerance constants in force,
    and the schema version, once per artifact. Determinism is only checkable if the
    artifact says what produced it.

---

## Discarded

Deliberately not stored. Each is a thing the graph *could* have kept and does not.

1. **Exact joint trajectories between transitions.** `q` and `q̇` are stored only in
   the `RobotConfig` nodes that anchor a retained relationship. The interpolated path
   between two transitions is gone; a robot holding still for 3 s at 50 Hz produces
   ~1 node, not 150.
2. **Sub-centimetre geometry.** Envelope and entity boundaries pass through
   `shapely.simplify(GEOM_SIMPLIFY_TOL_M)`. Boundary detail finer than that is
   discarded and cannot be recovered.
3. **Distance and area detail below the quantum.** Distances below `DISTANCE_TOL_M`
   resolution and area digits beyond `AREA_QUANT_SIGFIGS` are not stored — a
   relationship whose metric drifts within the quantum extends the existing edge
   rather than emitting a new one.
4. **Timing detail below `TIME_TOL_S`.** Transition timestamps are quantized; the
   sub-quantum instant of a crossing is discarded.
5. **Raw sensor data — all of it.** There is none in the artifact, by construction.
   In this prototype entity positions are simulator ground truth; in a real system
   they would come from perception, and the raw frames would still not be here.
   That is the entire point of the artifact being retainable.
6. **Per-frame duplication of static facts.** Static obstacle geometry is logged
   per-frame in the raw CSV (deliberately, to inflate the baseline honestly) and
   stored once in the graph.
7. **Intermediate envelope samples.** The N sampled control sequences and their
   swept polygons are discarded; only their union survives. The envelope is an
   inner approximation and the graph does not preserve evidence of how loose it is.
8. **Anything not affecting an answer to a query in the supported set.** This is the
   general clause and it is subordinate to the specific ones: it licenses discarding
   a *new* quantity nobody queries, never re-litigating something listed as
   Retained.
9. **Envelope geometry, except where it is evidence — because it is recomputable.**
   Added 2026-08-18 (issue #28); it comes last because it is the only item here
   discarded for *recoverability* rather than for irrelevance, and the two must not
   be confused.

   **The rule.** Geometry is stored on the first and last frame of the run, and on
   every frame at which an `INTERSECTS` or `CONTACT` relationship with an entity
   begins or ceases to hold. On every other frame the `envelope` row carries its
   hash, area, horizon and source with `geometry_wkb = NULL`. The rule is written
   into every artifact's `meta` table under `envelope_geometry_retention`, so a
   reader holding only the file can tell a discard on a stated rule from a build
   that wrote nothing.

   **Relationships, not edge rows.** An `INTERSECTS` edge also closes and reopens
   whenever the overlap area crosses an `AREA_QUANT_SIGFIGS` boundary. Those are
   metric steps, and the metric is already on the edge. Counting them as transitions
   keeps geometry on 150 of `sustained_overlap`'s 301 frames (measured at the
   benchmark's parameters); counting the relationship's own beginning and end keeps
   it on 2. A retention rule whose cost scales with how much the arm moved is the
   defect this item exists to remove.

   **The recomputation contract.** `compute_envelope` is a deterministic function of
   `(q, qd, horizon, n_samples, seed, substep_dt)`. The artifact stores every one of
   them — `q` and `qd` in the `robot_config` row each `envelope` row now names, the
   four parameters in `meta` — so `reg.graph.envelope_at(conn, t)` returns the
   stored polygon where there is one and recomputes it where there is not, and a
   caller cannot tell which happened except by timing.
   `tests/test_graph.py::test_envelope_at_recomputes_the_stored_polygon_exactly`
   is the gate: it blanks a stored polygon and asserts the recomputed one is
   identical at **zero tolerance**. If that ever fails, the discard is not lossless
   and this item is wrong rather than merely expensive.

   **Its precondition, stated rather than assumed.** Recomputation is exact for the
   same code and the same shapely version. An artifact handed to an assessor years
   later may not reproduce byte-identical geometry, and on the frames where the
   polygon was discarded there is then nothing to fall back on. That is a real cost
   of this trade and it is recorded in [`docs/limitations.md`](limitations.md), not
   here, because it is a limitation of the project and not a clause of the contract.

   **What it does not license.** Discarding the scalars (Retained #8), discarding
   the `config_id` that makes recomputation possible (the schema refuses an
   `envelope` row with neither geometry nor a config), or lowering `n_samples` to
   make the polygons smaller — that changes what the envelope *is* in order to move
   a storage number, which is the move this whole document forbids.

   **It reaches computed envelopes only.** A `declared` or a `clamped` bound is
   stored with its polygon, always. The discard above is licensed by
   recomputability and by nothing else, and those two regions came from a policy
   rather than from a configuration in this file: there is nothing here to
   recompute them from, so discarding one would not be a discard but a deletion.
   Added 2026-08-19 with issue #45.

10. **The envelope at frames that anchor nothing, and the per-frame node itself.**
    Added 2026-08-18 (issue #29). #9 stopped storing the polygon on every frame and
    left the row; this stops storing the row.

    **The rule.** An `envelope` row is written on the first and last frame of the
    run, on every frame at which an `INTERSECTS` or `CONTACT` relationship with an
    entity begins or ceases to hold, and on every frame at which an `INTERSECTS`
    edge opens. On every other frame **no `envelope` and no `robot_config` row is
    written at all**. There is no per-frame node type either: the `Timestep` node in
    [`docs/plan.md`](plan.md) Phase 5's table is gone, `HAS_ENVELOPE` runs
    `RobotConfig → Envelope`, and time exists in this artifact only as the
    `t_start`/`t_end` carried by every edge. The rule is written into every
    artifact's `meta` table under `envelope_row_retention`, so a reader holding only
    the file can tell a discard on a stated rule from a build that stopped writing —
    the pattern of absences does not distinguish them.

    **What a frame with no row means.** That the artifact does not hold that frame's
    envelope. Not that the robot had none, and not that nothing happened.

    One qualification, because it is the difference between the two rules doing
    different work: a `HAS_ENVELOPE` interval **extends** across frames at which the
    envelope hash did not change, and every frame it covers *is* retained — the
    builder computes the envelope at every frame and compares, so the interval is an
    assertion about each frame under it. A robot holding still for 3 s at 50 Hz
    therefore leaves one row covering 150 frames, which is the sentence in
    [`docs/plan.md`](plan.md) Phase 5 that started all of this. The frames with
    nothing are the ones a *moving* arm leaves between transitions, where the
    envelope was different and the artifact kept no record of it.

    **How a question about such a frame is answered.** Two different ways, and the
    split is the whole point:

    * *Every query in the supported set above answers normally.* All nine are
      interval queries over edges, and the intervals cover the whole run — a
      relationship that held at an unretained frame is inside an edge that spans it,
      with its metric on the edge. Nothing in queries 1–9 reads a per-frame node,
      which is why removing it is a discard rather than a change of what the
      artifact can say. `tests/test_graph.py::test_the_separation_timeline_answers_
      every_frame_within_tolerance` is the gate: query 1, at every frame of a real
      scenario, against the raw stream, under this document's own predicate.
    * *The two questions that name frames* — `frames_at_risk` and the incident
      report's "27 frames" — divide an interval by `frame_period_s` in `meta`, which
      is recorded once per artifact and refused at build time unless the stream's
      period is uniform to `TIME_TOL_S`. That is a better answer than counting node
      rows would have been: a row count would depend on which frames happened to
      anchor an edge.
    * *`reg.graph.envelope_at(conn, t)` refuses*, naming the rule. It does not
      return the neighbouring interval's polygon. See *Unanswerable* #1 — this is
      that item reaching a sampled frame rather than an instant between two, and for
      the same reason: the envelope is a function of the configuration, `q` has never
      been stored at every frame (*Discarded* #1), so an envelope at every frame was
      only ever available by storing a configuration at every frame. That is the
      linearity being removed.

    **Why it is a discard and not a deletion.** The test that distinguishes them is
    whether a run in which something genuinely changes every frame still costs a row
    every frame. It does: a human walking steadily across the scene crosses a
    `DISTANCE_TOL_M` bucket at every frame and gets a `SEPARATION` interval and a
    `robot_config` row at every frame; a human sliding out of the envelope crosses an
    `AREA_QUANT_SIGFIGS` boundary at every frame and gets an `envelope` row at every
    frame. `tests/test_graph.py::test_a_stream_that_changes_every_frame_still_emits_
    a_row_per_frame` and its envelope counterpart assert exactly that. A rule that
    capped the row count instead of tracking the transitions would pass every
    sub-linearity measurement in this project and would be dropping evidence.

    **What it does not license.** Widening `DISTANCE_TOL_M`, `TIME_TOL_S` or
    `AREA_QUANT_SIGFIGS` so that more things count as unchanged. That buys the row
    count by discarding resolution this contract advertises, which is its own named
    failure mode — see *What the tolerances do not license* below, and the sentence
    about editing a constant to make a red test go green.

---

## The three resolution levels

**Added 2026-08-19 (issue #35), amended the same day.** Everything above this
section describes the **finest** level and was written as though it were the only
one. It is not, and saying so is the point.

This section was originally motivated by a refutation: `docs/plan.md` Claim 1's
original form — the graph is orders of magnitude smaller than the stream — was
measured against a gzipped proprioception CSV and came out 14x *worse* (issue
#30). That refutation has since been withdrawn; the CSV was never the baseline
the claim was about. The sensor-log baseline is stated in the README and in the
original plan — both predate the benchmark by hours on 2026-08-18, and the plan's
own limitations section already flagged the terabytes/day figure as "imported
context, not a result". The CSV was a substitute this simulator forced, not a
restatement of the claim. But the question it provoked is the durable part and it
outlived its own premise: *how coarse can the evidence get before it stops
answering the question?* The resolution levels below are what answer it, and
they turn out to be **where the compression argument actually lives** — a
provisional 18.9 GB (issue #59: Layer A is missing from that measurement)
per robot per six months at occurrence resolution against a projected 182.5 TB of
sensor log (`docs/plan.md` Claim 1; the sensor rate is an assumption with a
sourced range and a sensitivity table, [`sensor-baseline.md`](sensor-baseline.md)).

The coarsest level is not invented here. UN R157's **DSSAD** is the only mandated
evidence recorder for autonomy that exists, and it stores **occurrences**: an
occurrence flag, a reason, a date, a timestamp accurate to **±1.0 second**, and
the software version identifier present at the event
([`docs/prior-art.md` §9](prior-art.md)). `reg` chose cm / 10 ms, every frame —
two orders of magnitude finer than the only comparable thing required by law —
and chose it without noticing it was choosing.

All three levels are **views of one artifact**, not three artifacts. `reg.graph`
writes both layers; `python -m reg.bench --resolution` projects the build into
each level, measures what each costs in bytes/hour, and reports whether each
still answers the supported questions within the tolerances above. The fine layer
is not deleted to make the coarse number better — a single coarse artifact would
not be a measurement.

### Level 1 — occurrence (DSSAD-aligned, ±1.0 s by default)

**Retains.** One row per semantically material event, from a fixed vocabulary
(`reg.store.OCCURRENCE_SPECS`): `run_began`, `run_ended`, `envelope_entered`,
`envelope_left`, `contact_began`, `contact_ended`, one `closest_approach` per
entity carrying the smallest separation of the run, and — added 2026-08-19 with
issue #45 — the five enforcement events, `declaration_vetoed`, `action_clamped`,
`safe_state_entered`, `reintegrated` and `escalation_failed`. Each row carries DSSAD's
elements — the flag (the type), the reason, the timestamp, and a provenance stamp
binding the event to the `reg` version and the envelope parameters that produced
it, which is `R157SWIN` in this project's terms. The entity set and the run's
provenance stay, because an occurrence naming an entity the file does not contain
is not a record of anything. The rule itself is written into `meta` under
`occurrence_retention`.

**Discards.** Every interval, every metric between events, every timestamp digit
finer than the stated resolution, and the order of two events inside one quantum.
Nothing is emitted when a metric crosses a quantization boundary — those are the
transitions level 2 records, and recording them here would reintroduce the
per-frame cost this level exists to be measured against. A relationship still
holding at the last frame gets no `..._left` or `..._ended`; `run_ended` bounds
it. A PERMIT verdict emits nothing at all, and a SAFE_STATE emitted while the
enforcer is already passivated emits nothing either — both would be one row per
frame, the first for a run that went well and the second for a robot that was
not moving.

**The first attestation question this level can answer.** Until issue #45 every
occurrence type was Layer B and about an entity, so the coarse layer could say
who came near the robot and nothing about what the robot was authorised to do.
The five enforcement events are Layer A: at ±1.0 s the artifact now answers *was
an action ever clamped, and roughly when* without the edge layer and without a
perceiver. What it still cannot answer is which declaration, which bound, or by
how much — those are `declaration`, `verdict` and the four attestation edges,
all of them level 2.

**There is no date element, and that is a deviation stated rather than hidden.**
DSSAD records `yyyy/mm/dd` because a recorder in a car has a clock. This artifact
must be byte-reproducible from its seeds, and a wall-clock date is exactly the
ambient value that would break it. What stands in for it is the run's own time
base plus the source stream's provenance block: an assessor gets *when in this
run* and *which run*, not *which afternoon*.

**Cannot answer.** Anything per-frame. The separation timeline, the envelope in
force at `t`, `frames_at_risk`, and every metric between two events are outside
this level — and `reg.bench --resolution` reports them as *could-not-evaluate*,
never as agreement. "When did it happen" is answerable only to the stated
resolution, which for a short event is two orders of magnitude worse than
`TIME_TOL_S`.

**One closed-world reading, and it is load-bearing.** The absence of a
`contact_began` row means no contact occurred, not "unknown" — but *only* because
the retention rule in `meta` says one would have been written. That is the same
reason DSSAD's absent occurrence flag is readable. Without the rule in the file
it is silence, and silence is not agreement.

### Level 2 — transition (the edge layer, `TIME_TOL_S` endpoints)

**Retains.** Everything under *Retained* above: one interval per relationship per
quantized value, with its metric, its layer tag and its endpoints at
`TIME_TOL_S`, plus the nodes those intervals anchor under *Discarded* #9 and #10.

**Discards.** Everything under *Discarded* above — the joint path between
transitions, sub-quantum geometry, metric detail below the quantum, and the
frames that anchor nothing.

**Cannot answer.** Everything under [*Unanswerable*](#unanswerable), which follows
this section rather than preceding it — it is the finest level's refusal list, and
levels 1 and 3 inherit it.

This level is what the rest of this document specifies, and it is the one the
agreement table at the bottom is written against.

### Level 3 — per-frame (the incremental rule run backwards)

**Retains.** One row per frame per relationship: the same facts as level 2, with
the intervals expanded. It invents nothing — an interval already asserts that the
relationship held at every frame under it — and it exists so that the cost of
*not* having the incremental rule is a measurement in the same table rather than
an argument.

**Discards.** The same quantization as level 2. Per-frame rows do not restore
resolution; they restore *redundancy*, which is why the rule that removes them is
a discard of duplication rather than of evidence.

**Cannot answer.** The same questions as level 2, for the same reasons. That is
the finding: the finest level in this project answers nothing the transition
level does not, and `reg.bench --resolution` prices the difference.

**What the benchmark's per-frame row is not.** It expands the retained intervals;
it cannot restore the per-frame `robot_config` and `envelope` rows *Discarded*
#10 removed, because those were discarded at build time. So the measured
per-frame cost is a **lower bound**, and the direction matters: it understates
what the fine layer costs, which makes the coarser levels look *less* good rather
than more.

### What the levels do not license

**Widening `DISTANCE_TOL_M`, `TIME_TOL_S` or `AREA_QUANT_SIGFIGS`.** The
resolution parameter is the occurrence timestamp granularity and what qualifies
as material — not the tolerances this contract advertises. Loosening those
changes what the artifact *claims*; the levels change what it *costs*, and cost
is the variable under study. `reg.graph.OCCURRENCE_TIME_RESOLUTION_S` is
deliberately **not** in `reg/tolerances.py` for exactly this reason: it is a
parameter of a measurement, not one of the four constants above.

**Deleting the fine layer.** The occurrence layer is additive: not one edge row
exists or fails to exist because of it, and `tests/test_graph.py::test_the_
occurrence_layer_is_additive` is the gate on that.

---

## Unanswerable

Questions the artifact cannot answer, and must refuse rather than approximate. A
query that hits one of these returns *could-not-evaluate*; it never returns a
plausible interpolated number.

1. **Exact pose at an instant the graph retains no configuration for.** "Where was
   the end effector at t = 12.3471 s?" The graph has the enclosing interval and the
   configurations at its endpoints. It cannot reconstruct the pose between them, and
   interpolating one would produce a number indistinguishable from a recorded one.

   This covers instants *between* two frames and, since issue #29, sampled frames
   that anchor no relationship (*Discarded* #10) — the same refusal for the same
   reason, since a frame whose `robot_config` was never written is exactly as
   unreconstructable as an instant between two that were. The envelope inherits it:
   `reg.graph.envelope_at` refuses both.
2. **Anything about entities outside the entity set.** An object nobody declared as
   an entity leaves no trace. Absence of an entity from the graph is not evidence of
   its absence from the room.
3. **Whether the *true* reachable set contained a point the computed envelope
   excluded.** The envelope is a sampling-based **under-approximation**
   ([`docs/prior-art.md` §4](prior-art.md)); "the robot could not have reached
   (x, y)" is not a claim this artifact supports. Only the positive direction —
   "the robot could have reached it" — is.
4. **Metric differences finer than the tolerances.** "Was the human 4 mm closer at
   t₁ than at t₂?" is below `DISTANCE_TOL_M` and unanswerable, not false.
5. **Ordering of two transitions within the same time quantum.** Two transitions
   that quantize to the same `TIME_TOL_S` bucket have no retained order.
6. **Why the policy declared what it declared.** The policy is the black channel.
   The graph records what it declared and whether it honoured it, never its
   reasoning.
7. **Whether perception was correct.** Every Layer B answer is conditional on the
   entity positions being right, and the artifact contains no evidence bearing on
   that. `reg` states the dependence (Phase 9); it does not discharge it.
8. **Anything about a run whose records are not in the artifact.** The chain proves
   the retained records were not altered. It cannot prove that no record was
   withheld before the artifact was written.

---

## Quantization tolerances

These four constants are the whole quantitative content of this contract. They are
named here so that the doc and the code cannot drift.

| Constant | Value | Governs |
|---|---|---|
| `DISTANCE_TOL_M` | `0.01` (1 cm) | separation and all distance-valued edges |
| `AREA_QUANT_SIGFIGS` | `2` | envelope `area`, `overlap_area` |
| `TIME_TOL_S` | `0.010` (10 ms) | transition timestamps, interval endpoints |
| `GEOM_SIMPLIFY_TOL_M` | `0.005` (5 mm) | `shapely.simplify()` on stored geometry |

**One definition.** `reg/tolerances.py` holds these four names as module-level
constants and is the *only* place any of them may be assigned. Every module — graph
construction, query, benchmark, test — imports them from there; a literal `0.01` in
graph or query code is a defect even when it is the right number, because the next
person to change the tolerance will not find it. `tests/test_tolerances.py` asserts
the module's values equal the table above, so an edit to either side that is not
mirrored in the other fails CI. That test and that module are Phase 5 work; this
issue is prose only, and the table is normative until they exist.

### Where the values come from

`DISTANCE_TOL_M`, `AREA_QUANT_SIGFIGS` and `TIME_TOL_S` are the cm / 2-sig-fig /
10 ms figures stated in [`docs/plan.md`](plan.md) Phase 5. They are inputs to this
document, not derived by it.

`GEOM_SIMPLIFY_TOL_M` is derived, and the derivation is the reason it is not simply
1 cm. Douglas–Peucker simplification displaces a boundary by up to the tolerance,
and cm-quantization of a distance contributes up to half a quantum. Those errors
add. For the total to stay within the 1 cm resolution this contract advertises:

```
GEOM_SIMPLIFY_TOL_M + DISTANCE_TOL_M / 2  ≤  DISTANCE_TOL_M
0.005                     + 0.005         =  0.010
```

Half the quantum to each. Raising the simplification tolerance to 1 cm would mean
reported distances are good to 1.5 cm while the artifact claims 1 cm — the failure
mode this contract is written to prevent.

### What the tolerances do *not* license

- **`TIME_TOL_S` is a quantum, not a promise of resolution.** If the simulator runs
  below 100 Hz, transitions are only locatable to the frame period, and the graph
  must record the frame period in its provenance and never report finer. Claiming
  10 ms resolution over 20 ms frames is a fabricated digit.
- **`AREA_QUANT_SIGFIGS` is relative.** Two significant figures is worst-case ~5%
  near the bottom of a decade (1.0 vs 1.05 m²) and ~0.5% near the top. Say the
  relative figure in the writeup; do not quote an absolute area tolerance that
  happens to hold for one scenario's numbers.
- **Areas inherit the geometry error.** An `overlap_area` is computed from already
  simplified boundaries, so its error also carries a term of up to
  `perimeter × GEOM_SIMPLIFY_TOL_M`, which dominates for long thin slivers. The
  agreement predicate below states this explicitly; it is part of the budget as
  written, not an allowance to be discovered later.

---

## How to tell if this contract is being violated

**The check.** For every query in the supported question set, and for every
scenario fixture, compute the answer twice: once from the graph alone, and once as
ground truth from the raw CSV. The two must agree within the tolerances above.

**Disagreement outside tolerance is a bug in the graph, not a tolerance to widen.**
If a check fails, the permitted responses are: fix the graph, or change this
document *and say why* — which means changing what the project claims. Editing a
constant to make a red test go green is the one move this contract exists to
forbid.

| Query | Ground truth from the CSV | Agreement predicate |
|---|---|---|
| 1 `separation_timeline` | FK per frame → min distance to entity | per sampled frame, \|d_graph − d_csv\| ≤ `DISTANCE_TOL_M` |
| 2 `first_envelope_intersection` | recompute envelope per frame, first frame intersecting | \|t_graph − t_csv\| ≤ `TIME_TOL_S`; interval endpoints likewise |
| 3 `frames_at_risk` | per-frame threshold test | interval sets match to `TIME_TOL_S` at every endpoint |
| 4 `reachable_entities` | per-frame envelope ∩ entity over the window | **exact set equality** — no tolerance; a missing or extra entity is a failure |
| 5 `declared_bound` | the declaration open at `t` in the declaration stream | exact field equality; geometry within `GEOM_SIMPLIFY_TOL_M` (Hausdorff) |
| 6 `violations` | replay declarations vs. commanded actions | **exact** set of `(t, fault_code)` — a missed or invented fault is a failure |
| 7 `verdicts` | the verdict stream | exact field equality |
| 8 `verify_chain` | recompute hashes and MACs over the record | exact — pass, or a named break at a named record |
| 9 `incident_report` | composition of the above | each component under its own predicate |
| — overlap areas | envelope ∩ entity per frame | \|A_graph − A_csv\| ≤ max(half-ulp at `AREA_QUANT_SIGFIGS`, perimeter × `GEOM_SIMPLIFY_TOL_M`) |

Attestation queries (5–8) get **no numeric tolerance**. They are Layer A, they are
exact by construction, and a tolerance on them would mean the record is fuzzy about
what the policy declared — which is the one thing this artifact must be certain
about.

**The check must be able to fail.** Every comparison reports *pass*, *fail*, or
*could-not-evaluate*, and the third never resolves to the first. A query returning
an empty list, a scenario with no fixture, an entity absent from the graph, and an
unparsed CSV row are all *could-not-evaluate*. Silence is not agreement.

**The recomputation check.** *Discarded* #9 adds one more, because it is the only
discard whose soundness is a claim about *equality* rather than about relevance: on
every frame where geometry was stored, `reg.graph.envelope_at` must reproduce the
stored polygon **exactly** — `shapely.equals_exact(..., tolerance=0.0)`, no budget,
because `GEOM_SIMPLIFY_TOL_M` is already spent on the stored boundary and a second
helping of it here would hide the drift the check exists to find. A disagreement
means the polygons on the discarded frames are not the polygons that were computed,
and the response is to stop discarding, not to widen anything.

**Ship the negative test.** The comparison harness is itself a check, so it must be
shown capable of saying no: feed it a graph with a deliberately perturbed edge —
one distance shifted by more than `DISTANCE_TOL_M`, one transition moved by more
than `TIME_TOL_S`, one fault deleted — and assert it reports *fail*, naming the
query and the record. A harness that has only ever been run against a healthy graph
has not been shown to be able to fail at all. The `--tamper` flag in
[`docs/plan.md`](plan.md) Phase 6 is the same discipline applied to the chain.

---

## See also

- [`docs/plan.md`](plan.md) — **Phase 5**, the evidence graph and the incremental
  principle this contract bounds; **Phase 7**, the query set it is defined against.
- [`docs/prior-art.md`](prior-art.md) — **§1**, UNECE DSSAD: event-level retention
  as an already-mandated conclusion for automated driving, and why the framing here
  is "we discard deliberately" rather than "we compress well". **§9**, DSSAD's
  actual data elements and how far this project overshot them — the source of the
  occurrence level above. Also **§4**, the under-approximation that makes item 3 of
  *Unanswerable* unanswerable.
