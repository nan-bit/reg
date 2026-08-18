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
