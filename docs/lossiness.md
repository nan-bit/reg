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
6. **Every fault, with full attribution** — the fault code from the Phase 4
   taxonomy, the declaration it was raised against, the record that triggered it,
   and which key signed each side. A fault with no attributable origin is a defect,
   not a retained fault.
7. **The complete hash chain** — every `FOLLOWS` link between consecutive records,
   unbroken, so `verify_chain()` is answerable from the graph alone.
8. **Envelope *identity and scalars* at every material change** — whenever the
   envelope hash changes under `GEOM_SIMPLIFY_TOL_M`, the artifact records
   `envelope_hash`, `area`, `horizon`, and `source` (`computed` / `declared` /
   `clamped`). All three sources are retained separately; a clamp is only legible if
   the declared and the computed bound both survive. **The geometry itself is not
   retained at every material change** — see *Discarded* #9, which is the one place
   this contract discards something it can prove is recoverable rather than
   something it can prove is irrelevant.
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

---

## Unanswerable

Questions the artifact cannot answer, and must refuse rather than approximate. A
query that hits one of these returns *could-not-evaluate*; it never returns a
plausible interpolated number.

1. **Exact pose at an arbitrary unsampled instant.** "Where was the end effector at
   t = 12.3471 s?" The graph has the enclosing interval and the configurations at
   its endpoints. It cannot reconstruct the pose between them, and interpolating one
   would produce a number indistinguishable from a recorded one.
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
  is "we discard deliberately" rather than "we compress well". Also **§4**, the
  under-approximation that makes item 3 of *Unanswerable* unanswerable.
