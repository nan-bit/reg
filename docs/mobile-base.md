# The mobile base — what moving the robot does to the argument

**Status:** a design document, not a description of anything built · written
2026-08-31 · **no code in this repository implements any of it** · normative for
the mobile track only; where it touches what the project may claim, it defers to
[`sufficiency.md`](sufficiency.md) and [`limitations.md`](limitations.md) until
those files carry the change themselves · keep current

Every figure, every envelope and the bound enforcement VETOes on are computed for
a planar arm with its base bolted to the origin. This document is what happens
when the base is allowed to drive, and it exists because that is not a parameter
change. The short version:

> **A fixed base is not a simplification of the mobile case. It is the special
> case in which the certifiable and uncertifiable layers coincide.**

Three things break, and only the third is geometry. The first is that the bound
enforcement computes for itself stops existing. The second is that the envelope
stops being answerable in room coordinates without perception — which shrinks the
set of questions this artifact can answer on its own authority, and is the
finding worth publishing.

---

## 1. `computed_bound` stops existing

`reg.enforce.computed_bound` is `sum(link_lengths) + link_radius`, a disc centred
on the base. It is finite **because the base is bolted down**. A driven base has
an unbounded workspace: given enough time it reaches everywhere, so there is no
horizon-free radius to compute. Marvel & Bostelman (NIST, IEEE ROSE 2013) make the
same point the reason mobile manipulators do not inherit either parent standard:
their work volume is described there as effectively unbounded and not
predictable in advance — which is precisely the property a horizon-free bound
needs to *not* have. (Paraphrase, not quotation: §6 records that the paper was
read from its abstract and from secondary sources.)

That has three consequences, in increasing order of how easy they are to miss.

**The floor under `horizon_bound` goes.** `horizon_bound` is
`min(computed_bound(limits), outer_radius(outer_envelope(state, limits, ...)))`.
Today the first term is sound by a trivial argument and the second is a
tightening. For a mobile robot the first term is gone and the second is the
**only** bound — so every VETO rests on the outer envelope's soundness argument,
and `tests/test_envelope.py::test_no_bang_bang_trajectory_escapes_the_outer_envelope`
stops being a good test and becomes the load-bearing one.
[`CLAUDE.md`](../CLAUDE.md) rule 3 describes the bound as the smaller of two
sound bounds; for a mobile robot that sentence is false and has to be rewritten
rather than amended.

**The disc is also used *inside* the outer envelope, and that is the easy one to
miss.** `reg/envelope.py` ends `outer_envelope` on
`unary_union(bodies).intersection(disc)`, where `disc` is the same origin-centred
workspace disc — there to stop the grid dilation's rim reaching outside a bound
that already held. If the base moves and that term does not move with it, the
intersection silently clips away most of the true outer set. The result is an
**unsound outer bound that looks exactly like a sound one**, which is the single
worst failure available in this codebase: everything it clears is cleared
wrongly, and nothing downstream can tell.

**The right behaviour is refusal.** [`CLAUDE.md`](../CLAUDE.md)'s *a check must
be able to fail* says a check reports pass, fail, or could-not-evaluate, and that
the third never resolves to the first. An unbounded workspace is a
could-not-evaluate. `computed_bound` must say so for a mobile model rather than
return a large plausible number — a bound nobody can justify is worse than no
bound, because it VETOes and looks principled while doing it.

## 2. The base pose is Layer B, so the envelope is a body-frame object

For a fixed arm, *the base is at the origin* is free. It is a mounting fact, not
a measurement, and it is why
[`sufficiency.md`](sufficiency.md) §5.1 can say of *could the robot have reached
(x, y) at t?* that **"the answer inherits nothing from perception"**.

For a mobile robot, where the base *is* comes from localization. And localization
is not a safety function. Mobile-robot safety under ISO 3691-4 and
ANSI/A3 R15.08 is built on safety-rated scanners monitoring **protective fields
in the vehicle frame**; map-based pose estimation runs on non-safety-rated
sensing and is a navigation function. The proprioceptive alternative — wheel
odometry — drifts without bound and is defeated by slip that wheel encoders
cannot observe. Neither route delivers a room-frame pose with characterized
failure modes.

So the envelope splits in two, and the split is exactly the project's existing
one:

| | What it is | Layer | Why |
|---|---|---|---|
| **Body-frame reachable set** | the region the robot can occupy *relative to its own base* within the horizon | **A** | computed from `q`, `qd`, base body-frame velocities off wheel encoders, and actuation limits. Nothing outside the robot enters it. This is what a protective field *is*. |
| **Base pose** `(x, y, θ)` | where that region sits in the room | **B** | simulator ground truth here; a localizer in a real system. The same status `human_pos` has today. |
| **Room-frame envelope** | the body-frame set rigidly transformed by the pose | **B** | it inherits the pose, and therefore the perceiver. |

**`ProprioState` must not gain `x`, `y`, `θ`.** That is the erosion
`tests/test_layer_boundary.py::test_propriostate_fields_are_exactly_the_allowed_set`
exists to catch — and note that it would *not* be caught by the word check, since
none of those names is in `WORLD_WORDS`. The allowlist is what catches it, and
its failure message already states the remedy: widening Layer A is a decision
about what the project can claim, and `sufficiency.md` moves in the same change.
What `ProprioState` may gain is base **velocity**, which an encoder measures.
What it may not gain is base **pose**, which an encoder does not.

### 2.1 What this costs, stated as a loss

This **shrinks the set of certifiable questions**, and saying so plainly is more
valuable than any of the geometry below.

- Fixed arm — *could the robot have reached (x, y) at t?* is **Layer A**.
- Mobile robot — the same question is **Layer B**. Its Layer A survivor is
  *could the robot have reached a point 1.2 m ahead-left of its own base at t?*

A reader is entitled to ask why a project whose whole thesis is tagging evidence
with the layer it depends on did not already say this. The answer is that the
fixed base hid the distinction by making the two frames the same frame. That is
the kind of thing [`sufficiency.md`](sufficiency.md) exists to record, and it is
the strongest thing to come out of this work.

It also reaches somewhere the layer boundary has never had to reach.
`reg/store.py` asserts of the four attestation edges that they are Layer A and
that not one of them names an `Entity` — *"None of it needs to know where anybody
is standing."* A mobile base is the first thing that would make a Layer A
attestation edge depend on a pose **in the room**, which is the asymmetry
[`sufficiency.md`](sufficiency.md) §2 is built on.

### 2.2 The nuance to record rather than resolve

A dead-reckoned pose — `∫(v, ω) dt` from the last known pose — is derivable from
proprioception alone. But it is only Layer A *relative to that last pose*, and
its error grows with time and is unbounded under slip. That is **Layer A with a
validity horizon**, which is not a value this project's binary has.

Issue #84 set the precedent for exactly this shape of problem: `Limits.source` is
a two-value tag with the simplification stated out loud rather than a graded
integrity attribute. Reuse it. A pose provenance enum beside `LimitSource`, with
no default and no inference, and the drift horizon recorded rather than modelled.
Do not build a graded scheme here; that decision was already taken and its
reasons have not changed.

## 3. The geometry stops being a disc

A differential-drive base is nonholonomic — it cannot move sideways — so its
horizon-limited reachable set is a curved, non-convex, Dubins-shaped region, not
a disc. Interval-propagating `(x, y, θ)` through the trigonometry, which is the
trick `outer_envelope` uses on the joint box, wraps badly and is very loose.

**Why the base cannot simply join the existing construction.** `outer_envelope`
enumerates an *ancestor grid* over the joint box and sweeps a sector per link,
guarded by `MAX_OUTER_GRID_CONFIGS = 50_000` — a guard that already raises a
could-not-evaluate rather than degrade quietly. Adding three more gridded
dimensions multiplies that enumeration and trips the guard on the first frame.

So the base must be handled **analytically and composed with the arm**, not
gridded beside it: a body-frame translation bound over the horizon, Minkowski-
summed with the arm's own body-frame outer set. That is deliberately loose, it
must be **published as loose**, and what a tighter construction would buy belongs
in [`limitations.md`](limitations.md). The tighter construction has a name and a
literature — RTD and REFINE compute exactly this forward reachable set for ground
robots with zonotopes, and CORA's conservative linearization gives a large convex
over-approximation of a Dubins car where polynomial zonotopes capture the
non-convexity. `reg` must not build it: *no new dependencies* is a standing rule
and *an HJ reachability solver* is a stated non-goal in
[`plan.md`](plan.md).

**This makes issue #82's open decision harder to defer.** The overclaim check is
radial. For a nonholonomic base a radial bound is very weak — a robot that cannot
turn is nowhere near the rim of its own disc — so radial-only containment,
already incomplete for the arm ([`limitations.md`](limitations.md) §3), is close
to useless for a base.

## 4. Blast radius

There is no model of a robot pose anywhere in the tree today: `affine_transform`,
`base_pose`, `SE2`, `mobile` and `AMR` return nothing across `reg/`, `tests/` and
`docs/`. `reg.world.BASE_XY` is read in two places and is documentation, not a
parameter.

Two pieces survive untouched and they bound the work: `_sector` already takes an
explicit centre, and `reachable_joint_box` and `_reach` are pure joint-space. The
base-relative half of the envelope construction is reusable as it stands.

What breaks, worst first:

1. `reg/kinematics.py` — the explicit leading `0.0` in the cumulative sums **is**
   the base. Everything else is downstream of those two lines.
2. `reg/envelope.py` — the literal origin-centred disc intersected into the outer
   bound. Silently unsound if missed (§1).
3. `reg/enforce.py`'s `_furthest_vertex` and `reg/envelope.py`'s `outer_radius` —
   both measure distance from an implicit origin, both are on the VETO path, both
   need a centre.
4. `reg/store.py` — the envelope-recompute argument stops holding. `geometry_wkb`
   may be NULL because the polygon is a deterministic function of the
   `robot_config` a row names plus four `meta` numbers; with a moving base that
   function is incomplete, and `envelope_at` would recompute an envelope at the
   origin for a robot that was elsewhere. Worse, the retained `outer_radius` is a
   radius **about an unstated centre** — today globally known, tomorrow
   meaningless. This is the decisive argument for putting the pose on the
   `robot_config` row, and it needs a `SCHEMA_VERSION` bump.
5. `reg/declare.py` — `declared_region` *raises* on a disconnected union, on the
   argument that every configuration's first link contains the base. A
   declaration spanning base motion can be legitimately disconnected, so a
   correct region would be refused.
6. `reg/declare.py` — `_classify` reads `reach` versus `retract` off the end
   effector's distance to the origin. A robot driving forward with a frozen arm
   classifies as a `reach`, and there is no tolerance anywhere to absorb it.
7. `reg/world.py` — the room-contains-origin check has to become a check that the
   base's whole *path* stays in the room, which a constructor that never sees a
   trajectory cannot perform. It moves to the scenario or the sim.
8. `reg/bench.py` — `proprioceptive_columns` matches `t`, `q_*` and `qd_*`, so a
   base column is **silently** treated as Layer B. See §5.
9. `reg/graph.py` — the distance error budget is exactly saturated today. A
   quantized base pose is a third error source in it.
10. `reg/scenarios.py` — every fixture's waypoints are hand-tuned against a
    distance from a base at the origin.

## 5. What this does not change

**Claim 1 stays a fixed-arm claim.** The mobile track is exploratory and
unbenchmarked. No published figure is re-measured, retired or moved by any of
this, and [`retention.md`](retention.md) says in its own header that its figures
are fixed-base figures at 50 Hz.

That is a thing to **enforce, not assume**, and item 8 above is why.
`proprioceptive_columns` selects columns by prefix, so the moment a base column
exists it is counted as Layer B without anything going red — moving the Layer A
and Layer B column split that Claim 1's comparison rests on. The fix belongs in
the house style: a function that classifies a column should refuse one it has no
rule for rather than default it. That is a small, independent change and it
should land **before** any mobile schema work, not after.

**No perceiver is built.** *Perception / vision / SLAM* is a binding non-goal in
[`plan.md`](plan.md) and stays one. The simulator supplies the base pose as
ground truth, tagged Layer B, exactly as it supplies the human's position.
Nothing localizes anything; the Layer B tag records that in a real system
something would have to.

## 6. Prior art, and what it was read from

Entered properly in [`prior-art.md`](prior-art.md) as a fifth pass; summarised
here so this document stands on its own.

| Work | Bearing on this design | Read from |
|---|---|---|
| Marvel & Bostelman, *Towards Mobile Manipulator Safety Standards*, IEEE ROSE 2013 | The unbounded work volume, and why the fixed-arm and AGV standards do not compose | abstract and secondary sources; the paper PDF did not extract |
| **ISO 3691-4**, **ANSI/A3 R15.08** | Safety is a protective field in the vehicle frame; localization is a navigation function | secondary sources and vendor summaries — both standards are **paywalled** |
| **RTD** / **REFINE** (Kousik et al.) | The forward reachable set for ground robots, computed with zonotopes | published preprints |
| **CORA** (Althoff) | Conservative linearization; a Dubins car's reachable set is non-convex and a zonotope over-approximates it loosely | published preprints |
| Set-theoretic localization | Bounded-error pose sets as an alternative to a probabilistic estimate | published preprints |

The reading status is stated per row for the reason
[`prior-art.md`](prior-art.md) states it everywhere: an entry that implies a full
read of a paywalled standard is the kind of claim this file exists to prevent.

## 7. Build order

Small, independent, and argument before code — a bad attempt should cost a closed
PR.

**Tier 0 — say what is true today.** The fixed base as a limitations entry; and
`proprioceptive_columns` refusing an unclassifiable column (§5).

**Tier 1 — the argument.** The fifth prior-art pass; then
[`sufficiency.md`](sufficiency.md) carrying §2.1's shrink of the certifiable
question set. *Everything downstream depends on the second one.*

**Tier 2 — types and the boundary.** Base velocity on `ProprioState`; a Layer B
pose type; base actuation bounds on `Limits` under the existing no-default rule;
pose provenance beside `LimitSource`; an explicit base frame in
`forward_kinematics`. The layer-boundary allowlist and `sufficiency.md` move in
the same commit as the first of these, because the test requires it.

**Tier 3 — the envelope and the bound.** The body-frame outer envelope with the
base states and a rewritten soundness argument; `computed_bound` refusing;
`horizon_bound` on the outer envelope alone; the pose on `robot_config` with the
schema bump; the two `declare.py` defects.

**Tier 4 — fixtures.** Mobile scenarios beside the eleven arm fixtures.

## See also

- [`sufficiency.md`](sufficiency.md) — §5.1, the question this reclassifies, and
  §2's asymmetry that §2.1 reaches into.
- [`limitations.md`](limitations.md) — §2 and §3, the under-approximation and the
  radial overclaim check that §3 above makes harder to leave alone.
- [`plan.md`](plan.md) — the non-goals table §5 defers to, and Phase 2's envelope.
- [`retention.md`](retention.md) — the figures §5 declines to disturb.
- [`prior-art.md`](prior-art.md) — where §6's entries live properly.
