# Limitations

**Status:** normative for what this project may claim · started 2026-08-18 · keep
current

[`docs/plan.md`](plan.md) Phase 10 lists this file as a deliverable and names what
it must eventually cover: inner-approximation sampling, 2D only, ground-truth
perception, no dynamics, a scripted policy, and both chain keys in one process.
Those land with the phases that create them; adding one here is part of finishing
that phase, not a separate decision. **This file exists early because a limitation
is worth least once nobody remembers it was a choice.**

Each entry says what the limitation *is*, what it costs, and what a claim would
need in order not to inherit it. None of them is a bug: a bug is a defect against
an intent, and every one of these is an intent stated out loud.

---

## 1. Recomputed envelope geometry assumes the same code and the same shapely

**What.** Most `envelope` rows in an artifact carry `geometry_wkb = NULL`. The
polygon was discarded because it is a deterministic function of things the artifact
does store — the `robot_config` the row names, plus `horizon`, `n_samples`,
`envelope_seed` and `substep_dt` in `meta` — and
`reg.graph.envelope_at(conn, t)` recomputes it on demand. The rule for which frames
keep their geometry is [`docs/lossiness.md`](lossiness.md) *Discarded* #9, and it is
recorded in each artifact under `meta['envelope_geometry_retention']`.

**The cost.** "Deterministic" is deterministic *for the same code and the same
shapely version*. `reg.envelope.compute_envelope` unions sampled link polygons and
`reg.tolerances.simplify_geometry` runs Douglas–Peucker over the result; both are
GEOS operations, and GEOS is entitled to change its output in a release. So an
assessor opening a five-year-old artifact against a newer shapely may get a polygon
that differs from the one that was computed at build time — and on a discarded frame
there is nothing in the file to notice the difference against. The frames that
*kept* their geometry are the exception: there the stored polygon is authoritative
and a recomputation that disagrees with it is detectable, which is exactly what
`tests/test_graph.py::test_envelope_at_recomputes_the_stored_polygon_exactly`
checks. Those frames are the ends of the run and the transitions an incident report
cites, so the geometry a report quotes is stored rather than recomputed — but the
frames *between* them are recomputed, and their fidelity is conditional.

Two consequences worth being precise about, because they are not the same:

- **`envelope_hash` still detects the drift, on every frame.** The hash was computed
  at build time over the polygon as it then was. A recomputation that disagrees can
  be caught by rehashing it, on a stored frame or a discarded one. What the artifact
  cannot do is *repair* the disagreement on a discarded frame — it can only report
  it.
- **It does not touch the attestation layer.** Declarations, verdicts and the hash
  chain (Layer A) are stored in full and hash nothing that a geometry library
  computes. `verify_chain()` is unaffected by this limitation.

**What a claim would need instead.** Retaining every polygon — which is what this
project did until issue #28 measured the artifact at 20–30x *larger* than a gzipped
CSV of the stream it replaced — or an exact, versioned geometry kernel whose output
is specified rather than implementation-defined. Neither is in scope for a
prototype. The mitigation actually taken is to name the dependency: every artifact
records `reg_version` and the retention rule, and this section is the statement that
`reg_version` alone is not sufficient — **the shapely and GEOS versions that built
an artifact are not currently recorded in it, and recording them would let a future
reader know whether to trust a recomputation rather than having to assume.** That is
a small, obvious follow-up and it is deliberately not smuggled in here.

**What this limitation is not.** It is not a reason to distrust the *retained*
answers. Every `INTERSECTS`, `SEPARATION` and `CONTACT` interval, every
`overlap_area` and `min_distance`, and every envelope `area` and `envelope_hash` was
computed at build time and is stored. Nothing in the supported question set
([`docs/lossiness.md`](lossiness.md)) is answered by recomputing a polygon; the
polygon is what a reader draws, inspects, or re-intersects when going beyond that
set.

---

## 2. The envelope is an under-approximation, not an over-approximation

Stated here because [`docs/prior-art.md` §4](prior-art.md) requires it to be, in the
right vocabulary, and because a reader who meets the word "envelope" will assume the
safety-relevant direction.

`reg.envelope.compute_envelope` samples a finite set of constant-acceleration
control sequences, forward-integrates each, and unions the bodies they pass through.
A finite sample can only **under-cover** the true forward reachable set. So:

- "the robot **could have** reached (x, y)" is supported;
- "the robot **could not have** reached (x, y)" is **not**, and no query in this
  project may be read that way.

A safety guarantee needs the opposite direction — an over-approximation (outer
approximation), where the true reachable set is contained in the computed one — and
getting it requires the zonotope and polynomial-zonotope machinery of **ARMTD** and
**ARMOUR** rather than sampling ([`docs/prior-art.md` §4](prior-art.md)).
[`docs/plan.md`](plan.md) de-scopes an outer-approximative solver deliberately: this
is a demonstration of the *evidence structure*, and every claim built on the
envelope inherits this limitation. `reg.envelope`'s module docstring lists three
further sources of under-coverage (substep sampling, flat link caps,
constant-accelerations only) and is the authority on them.

---

## 3. The bound enforcement checks declarations against is the whole workspace

Stated here because a reader meets the phrase "the independently computed physical
bound" in [`docs/plan.md`](plan.md) Phase 4 and in `reg.enforce`'s fault taxonomy,
and will reasonably read it as *what this robot could reach from here* — a
reachable set. It is not one.

**What.** `reg.enforce.computed_bound(limits)` is the radius of the **workspace
disc**: `sum(link_lengths) + link_radius`, centred on the base, which
`reg.kinematics` fixes at the origin. Its argument is `Limits`, a property of the
robot rather than of its state, so the bound reads no `q`, no `qd` and no horizon,
and is the same scalar at every frame of every scenario.
`reg.enforce.envelope_excess` tests a declared region against that disc, exactly —
a disc is convex, so a polygon lies inside it iff every vertex does.

**The cost.** The `envelope_overclaim` fault fires only on a declaration that
exceeds the **entire workspace**. A policy that declares a region it could never
occupy within the declaration's horizon — the fault a Simplex / ASTM F3269 runtime
monitor exists to catch — passes the check as long as the region fits inside the
disc, and enforcement emits PERMIT. The fixture is built accordingly: a 0.88 m
body padded to 1.13 m against a 0.95 m disc
(`reg/scenarios.py`, `envelope_overclaim`). What the check demonstrates is the
*structure* — an independent bound, computed from Layer A alone, that can veto a
declaration and leave signed evidence of the refusal — not a tight one.

Two things this limitation is **not**:

- **It is not a weakness in the independence.** Enforcement computes this bound
  itself from `Limits` and the origin, imports from `reg.declare` no further than
  `Declaration` and `ACTION_CLASSES`, and imports nothing from Layer B at all;
  both restrictions are asserted against the module's own AST in
  `tests/test_enforce.py`. It is the *capability* that is limited, not the
  separation. Softening the import rule to buy a tighter bound would trade the
  mechanism for the measurement.
- **It is not unsound.** The disc over-covers the true reachable set, so no
  truthful declaration is ever vetoed by this check — the error is entirely in the
  permissive direction, which is the correct direction for something whose
  response is VETO. Comparing against `reg.envelope.compute_envelope` instead
  would be the tempting move and the wrong one: §2 above is an
  *under*-approximation, and a declaration larger than a sampled envelope is the
  expected result for an honest policy, so vetoing on it would cry wolf.
  The other eight faults in the taxonomy — staleness, replay, MAC, vocabulary,
  watchdog, no-declaration, escalation failure and the declaration/action mismatch
  — are decided against the record, not against a reachability bound, and none of
  them inherits this.

**What a claim would need instead.** A horizon-limited **outer** approximation of
the reachable set: the zonotope and polynomial-zonotope machinery of ARMTD and
ARMOUR ([`docs/prior-art.md` §4](prior-art.md)), the same thing §2 needs and for
the same reason. With one, `envelope_overclaim` would become a meaningful check
and §2's restriction on *could not have reached* would lift together with it.
Without one, the supportable claim is exactly: **an overclaim is detected iff the
declared region leaves the workspace disc.** `reg/enforce.py`'s module header is
the authority on why the loose bound was chosen over an unsound tight one.

---

## 4. A Layer A envelope is Layer A only if its `Limits` are

Stated here because §3 above calls `Limits` "a property of the robot rather than
of its state", and that is true of its *shape* and not guaranteed of its numbers.

**What.** `compute_envelope` has two inputs. The first, `ProprioState`, is kept
out of Layer B by structure: it has no field naming an entity and
`tests/test_layer_boundary.py` fails if one appears. The second is `Limits`, and
that enforcement does not reach it — not because `Limits` is trusted, but because
the mechanism inspects **field names** and the problem arrives in a **value**.
`qd_max` is an innocent name whatever produced the number in it. Under **ISO/TS
15066 / ISO 10218-2:2025 speed-and-separation monitoring** — the practice
[`docs/plan.md`](plan.md) cites approvingly, and how collaborative robots actually
run — the commanded speed bound *is* a function of a measured separation
distance. Feed one in and the envelope integrated under it depends on a perceiver.

**The cost, and what issue #84 changed about it.** The dependence is real either
way; what was wrong was that nothing recorded it, so an SSM-derived envelope
carried a Layer A tag and no query, no `CHECK` constraint and no field-name test
could tell it from a datasheet one. `Limits` now carries `source: LimitSource`,
required and with no default, `reg.envelope.envelope_layer` maps it to a layer,
and the `HAS_ENVELOPE` edge is tagged from that rather than from its type —
`PROPRIOCEPTIVE` gives `A`, `DERIVED` gives `B`. The provenance is persisted in
`meta['limits_source']` so a recomputed envelope (§1) inherits it too, and an
artifact that does not carry the key is a **could-not-evaluate**: nothing reads
its absence as the clean case, and `reg.graph._limits_from_meta` refuses rather
than reconstructing a `Limits` nobody vouched for.

Two things this **is not**:

- **It is not a claim that a Layer B envelope is worth less.** The geometry is
  identical under either provenance — the same polygon, the same hash — and
  `tests/test_layer_boundary.py::test_the_layer_moved_and_the_geometry_did_not`
  is the gate on that. What differs is whose failure modes the answer inherits,
  which is the only thing the layer tag ever meant.
- **It is not inherited by §3's enforcement bound.** `computed_bound` reads
  `link_lengths` and `link_radius` and nothing else: link geometry is
  proprioceptive under SSM as much as anywhere, because the arm does not get
  shorter when a human walks in. So the independence argument in §3 stands
  unchanged for a derived-limits run, and the veto is as strong — or as loose —
  as it is for any other.

**What a claim would need instead.** Nothing further for the *labelling*; that
part is closed. What remains open is the taxonomy itself: two values is a
simplification, an IEC 61496 PLd safety scanner is perception with characterized
failure modes and still lands in `DERIVED`, and modelling that honestly needs a
tag **plus an integrity attribute** rather than a binary.
[`docs/sufficiency.md`](sufficiency.md) §7 records why that was considered and
deferred — it rewrites what the project may claim, which is a decision and not an
implementation.
