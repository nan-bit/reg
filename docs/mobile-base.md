# The mobile base — what moving the robot does to the argument

**Status:** a design document, and no longer entirely one · written 2026-08-31 ·
**Tiers 1 and 2 have landed; §3's construction landed 2026-09-02 (issue #163)
and §1's refusal landed 2026-09-02 (issue #164); §4's schema work and Tier 4's
fixtures have not, and no robot in this repository moves** — the build order in
§7 says per tier which is which, and it is the authority, not this line ·
normative for the mobile track only; where it touches what the project may
claim, it defers to [`sufficiency.md`](sufficiency.md) and
[`limitations.md`](limitations.md) until those files carry the change themselves
— **§2.1 and §2.2 now do**, carried into `sufficiency.md` §2, §5.1, §5.6 and §7
on 2026-09-01 (issue #139); **§3's looseness now does**, carried into
`limitations.md` §10 on 2026-09-02 (issue #163); and **§1's refusal now does**,
carried into `limitations.md` §3 and §9 and into
[`../CLAUDE.md`](../CLAUDE.md) rule 3 on 2026-09-02 (issue #164); those files are
the normative statement of them · keep current

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

**Built 2026-09-02, issue #164.** `reg.enforce.computed_bound` now refuses a
`Limits` with any nonzero base bound, naming the field, and `horizon_bound` rests
on `reg.envelope.outer_envelope` alone for that robot. The normative statements
are [`limitations.md`](limitations.md) §3 and §9 and
[`../CLAUDE.md`](../CLAUDE.md) rule 3, all three rewritten in the same change;
what follows is the argument they were rewritten from, kept as written.

`reg.enforce.computed_bound` is `sum(link_lengths) + link_radius`, a disc centred
on the base. It is finite **because the base is bolted down**. A driven base has
an unbounded workspace: given enough time it reaches everywhere, so there is no
horizon-free radius to compute. Marvel & Bostelman (NIST, IEEE ROSE 2013)
describe the work volume of a mobile manipulator as effectively unbounded and not
predictable in advance — which is precisely the property a horizon-free bound
needs to *not* have. (Paraphrase, not quotation: §6 records that the paper was
read from its abstract and from secondary sources.)

**Cite that paper for the work volume and not for the standards gap.** The same
2013 argument continues that a mobile manipulator inherits neither parent
standard, and that half of it has since been overtaken: ANSI/A3 R15.08 defines the
category, and ISO 3691-4 owns the driverless vehicle under it
([`prior-art.md`](prior-art.md) §21 and §22). The unbounded work volume is a
property of the machine and is unaffected; *nobody has written a standard for
this* is a statement about 2013.

That has three consequences, in increasing order of how easy they are to miss.

**The floor under `horizon_bound` goes.** `horizon_bound` was
`min(computed_bound(limits), outer_radius(outer_envelope(state, limits, ...)))`.
For a fixed base the first term is sound by a trivial argument and the second is
a tightening. For a mobile robot the first term is gone and the second is the
**only** bound — so every VETO rests on the outer envelope's soundness argument,
and `tests/test_envelope.py::test_no_bang_bang_trajectory_escapes_the_outer_envelope`
stops being a good test and becomes the load-bearing one.
[`CLAUDE.md`](../CLAUDE.md) rule 3 described the bound as the smaller of two
sound bounds; for a mobile robot that sentence is false, so it was rewritten
rather than amended — it now names which case each term applies to, and
[`limitations.md`](limitations.md) §3 carries the same split.

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

**Refusal is right here, and it is not the only answer to the same fact.** The
reachability literature stops needing a horizon-free bound instead: RTD carries a
**fail-safe manoeuvre**, verified offline in the same reachable set as every
trajectory it plans, so the robot is never in a state from which it has no
verified action ([`prior-art.md`](prior-art.md) §23). `reg` cannot take that
answer, for two reasons that are architectural rather than preferences. The
guarantee lives in the *planner*, which is the common-cause structure
[`CLAUDE.md`](../CLAUDE.md) rule 3 refuses; and this project's enforcement layer
VETOes a declaration and commands nothing, while the one thing in the tree that
resembles a fail-safe — passivation — reaches no table, no edge type and no query
and is documented as not exercisable. A project that cannot represent a stop
cannot rest a bound on having one. That is why `computed_bound` refuses, and it
is a better sentence than concluding refusal as though nothing else had been
tried.

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

**And the pose is Layer B for a stronger reason than that.** The paragraph above
argues from what today's sensing is rated for, which is an argument a
safety-rated localizer would answer. The structural argument does not move: a
room-frame pose is a statement about the robot's relationship to things *outside*
the robot — a map, landmarks, a frame somebody defined — and that is exactly
where this project draws the layer boundary. Even set-theoretic localization,
which returns a set **guaranteed** to contain the true pose rather than a
distribution over it, is guaranteed only under bounded-error hypotheses and a
map, both exogenous; a guarantee conditioned on a Layer B input is a Layer B
guarantee ([`prior-art.md`](prior-art.md) §25). **No localizer of any kind moves
the base pose to Layer A.** State it in that form, because the sensing-status
form invites someone to go and build the localizer.

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

**The body-frame row is what a protective field is — and this document may not
call it one.** ISO 3691-4 and R15.08 size a monitored region in the vehicle frame
by what the vehicle can do before it stops, and switch it with speed: a
horizon-limited body-frame reachable set, arrived at by a standards committee for
the same reason it is arrived at here ([`prior-art.md`](prior-art.md) §22). Two
independent derivations agreeing is worth more than the derivation was. But
*protective field* is a term of art carrying a conformance meaning — a rated
device, a stated performance level, a validation procedure, an assessment
somebody signed — and `reg`'s envelope is a `shapely` polygon computed by unrated
Python from a simulator. Say the body-frame set **is what a protective field is**;
do not say it is one. That is the same refusal §12 of the survey records against
IEEE 7001's investigator levels: name the ladder, claim no rung.

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

**It is recorded there now, and that copy is the normative one.**
[`sufficiency.md`](sufficiency.md) §5.6 carries the three-row split and this
subsection's loss, §5.1 states its own verdict as conditional on a fixed base and
names the Layer A survivor, and §2 reconciles the paragraph below against
`reg/store.py` (issue #139, 2026-09-01). Where the two files differ from here on,
**`sufficiency.md` is right** — it is normative for what the project may claim
and this is a design document. Nothing was reclassified in the move: no layer tag
changed, no figure moved, and `ProprioState` was not touched.

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

[`sufficiency.md`](sufficiency.md) §7 carries this as a bullet beside issue
#84's two, on the same terms it is put here: recorded, not resolved.

Issue #84 set the precedent for exactly this shape of problem: `Limits.source` is
a two-value tag with the simplification stated out loud rather than a graded
integrity attribute. Reuse it. A pose provenance enum beside `LimitSource`, with
no default and no inference, and the drift horizon recorded rather than modelled.
Do not build a graded scheme here; that decision was already taken and its
reasons have not changed.

A second nuance of the same kind, recorded for the same reason. A set-theoretic
localizer returns a **pose set**, not a point, and a set composes with §3's
construction directly: the room-frame envelope becomes the body-frame set
Minkowski-summed with the pose set instead of rigidly transformed by a point,
which preserves the over-approximation across the frame change where a point does
not ([`prior-art.md`](prior-art.md) §25). Today's Layer B tag is binary — it says
the answer inherited the perceiver and says nothing about how wrong it can be —
and a pose set is the shape in which a magnitude could be carried. It is the same
collision with issue #84 as the paragraph above, so it gets the same treatment:
recorded here, decided in the same change as the provenance enum or not at all.

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
literature — see below.

**This paragraph is built, 2026-09-02 (issue #163), and `limitations.md` §10 is
now the normative statement of its looseness.** `reg.envelope.base_motion_bounds`
returns the two scalars, the yaw folds into the first joint's angular interval —
exactly, because turning the vehicle about the base point and turning joint 0
produce the same body — and the translation is one `buffer` on the arm's set.
`MAX_OUTER_GRID_CONFIGS` was not raised, which was the test of whether the
construction was the right one. The soundness argument in `reg/envelope.py` was
rewritten rather than extended, because the set it describes changed, and
`tests/test_envelope.py::test_no_bang_bang_trajectory_escapes_the_outer_envelope_with_a_driven_base`
drives the vehicle as well as the joints. Where this section and
[`limitations.md`](limitations.md) §10 differ from here on, **§10 is right**: it
is normative for what the project may claim and this is a design document.

One thing the build settled that this section did not anticipate. `outer_envelope`
now **refuses** a state whose `base_vel` is `None` when the base can move —
"not recorded" is a could-not-evaluate and reading it as a base standing still
would produce an outer bound that is too small, which is the one direction it may
not be wrong in. That refusal is what stops item 4 of §4 from arriving quietly:
until the pose and the base velocity are on `robot_config`, a mobile artifact
cannot be written at all rather than being written with fixed-base numbers in it.

The tighter construction has a name and a
literature — RTD and REFINE compute exactly this forward reachable set for ground
robots with zonotopes, and CORA's conservative linearization gives a large convex
over-approximation of a Dubins car where polynomial zonotopes capture the
non-convexity. `reg` must not build it: *no new dependencies* is a standing rule
and *an HJ reachability solver* is a stated non-goal in
[`plan.md`](plan.md).

**What is loose, and why, in the terms that literature uses.** Conservative
linearization is what makes a nonlinear model analysable at all — linearize, then
add a set-valued abstraction-error term covering everything the linearization
dropped. It is not what makes the answer convex; the **representation** is, and a
zonotope is convex and centrally symmetric where the true set of a Dubins-like
model curves. Polynomial zonotopes are the same tool's other representation and
capture the curvature ([`prior-art.md`](prior-art.md) §24). The Minkowski sum
proposed above is that literature's primitive — zonotopes exist partly because
the operation is exact and cheap on them, and on a `shapely` polygon it is a
buffer whose error compounds with every step. So the looseness this section
promises to publish is a **representation cost**, paid for not taking a
dependency this project has already refused, and *how much* it costs has not been
computed for this construction by anyone.

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

Entered in [`prior-art.md`](prior-art.md) as the **fifth pass, 2026-09-01**,
§21–§25; summarised here so this document stands on its own. **Where this table
and the pass differ, the pass is right** — it is normative over `plan.md` and it
is where the reasons are written down, and this table is a summary that has to
move. Three rows below were moved by it.

| Work | Bearing on this design | Read from |
|---|---|---|
| Marvel & Bostelman, *Towards Mobile Manipulator Safety Standards*, IEEE ROSE 2013 (§21) | The unbounded work volume. **Not** *the fixed-arm and AGV standards do not compose*: that was true in 2013 and R15.08 has since defined the category, so the paper is cited for the machine and not for the gap | abstract and secondary sources; the paper PDF did not extract |
| **ISO 3691-4**, **ANSI/A3 R15.08** (§22) | Safety is a speed-dependent protective field in the vehicle frame plus a guaranteed stop; localization is a navigation function. The field **is the same object** as §2's body-frame set — and the term carries a conformance rating this project may not claim | secondary sources and vendor summaries — both standards are **paywalled**, and the entry cites no clause number for that reason |
| **RTD** / **REFINE** (Kousik et al.) (§23) | The forward reachable set for ground robots, computed with zonotopes and with tracking error inside it — and the **fail-safe manoeuvre** that is this literature's alternative to §1's refusal | published preprints; no implementation run |
| **CORA** (Althoff) (§24) | Zonotopes are the representation and conservative linearization is what makes a nonlinear model analysable; the Minkowski sum §3 proposes is this literature's primitive and its looseness is a representation cost | published preprints and the tool documentation; CORA was not run |
| Set-theoretic localization (§25) | Bounded-error pose sets — which do **not** make the pose Layer A, because the guarantee is conditional on a map and on bounded-error hypotheses, both exogenous. The pose is Layer B structurally, not for want of an estimator | published preprints and textbook summaries |

The reading status is stated per row for the reason
[`prior-art.md`](prior-art.md) states it everywhere: an entry that implies a full
read of a paywalled standard is the kind of claim this file exists to prevent.

## 7. Build order

Small, independent, and argument before code — a bad attempt should cost a closed
PR.

**Tier 0 — say what is true today.** The fixed base as a limitations entry; and
`proprioceptive_columns` refusing an unclassifiable column (§5).

**Tier 1 — the argument. Done, 2026-09-01.** The fifth prior-art pass —
[`prior-art.md`](prior-art.md) §21–§25, issue #138 — then
[`sufficiency.md`](sufficiency.md) carrying §2.1's shrink of the certifiable
question set, which the pass's §25 restates as a structural claim rather than a
sensing-status one: issue #139, landed in that file's §2, §5.1, §5.6 and §7.
*Everything downstream depended on the second one and no longer waits on it.*
Tier 2 still moves `sufficiency.md` again, because
`test_propriostate_fields_are_exactly_the_allowed_set` requires it in the same
commit as the first type change; what Tier 1 bought is that the argument is
settled before a type moves, rather than in the same PR as one.

**Tier 2 — types and the boundary.** Base velocity on `ProprioState`; a Layer B
pose type; base actuation bounds on `Limits` under the existing no-default rule;
pose provenance beside `LimitSource`; an explicit base frame in
`forward_kinematics`. The layer-boundary allowlist and `sufficiency.md` move in
the same commit as the first of these, because the test requires it.

**Tier 3 — the envelope and the bound.** The body-frame outer envelope with the
base states and a rewritten soundness argument — **done, 2026-09-02, issue
#163**, and its looseness is [`limitations.md`](limitations.md) §10;
`computed_bound` refusing and `horizon_bound` on the outer envelope alone —
**done, 2026-09-02, issue #164**, and the normative statements are
[`limitations.md`](limitations.md) §3 and §9 and
[`../CLAUDE.md`](../CLAUDE.md) rule 3; the pose on `robot_config` with the schema
bump; the two `declare.py` defects.

*The gap the previous entry recorded is closed, and the pin that recorded it was
rewritten rather than deleted.* With the base in the outer set,
`horizon_bound` was `min(computed_bound, outer_radius)` where the first term is a
fixed-base disc and the second grows with the vehicle — so for a mobile robot the
minimum was pinned at a bound §1 says does not exist.
`tests/test_enforce.py::test_the_horizon_bound_is_still_floored_by_a_fixed_base_disc`
recorded that and was written to go red when `computed_bound` started refusing;
it did, and it is now
`test_the_horizon_bound_rests_on_the_outer_envelope_alone_for_a_driven_base`,
asserting the identity rather than the gap. The two Tier 2 pins in front of the
same change —
`test_the_demo_worlds_bound_is_the_workspace_disc_it_has_always_been` and
`test_the_computed_bound_does_not_read_the_base_bounds` — went the same way: the
first still holds, narrowed to the fixed-base half it was always true of, and the
second is replaced by
`test_the_computed_bound_refuses_a_robot_whose_base_can_drive`, parametrised over
all four fields. Nothing in this repository changed behaviour: every fixture
states four zeros, and no published figure moved.

*What Tier 3's refusal does **not** buy.* `Enforcer` refuses to construct for a
driven base, because it names the workspace disc in every `envelope_overclaim`
reason it writes and there is no honest number to put there. The bound itself is
available for one — `horizon_bound`, `horizon_excess` — so what is missing is the
enforcer around it, and that needs the pose on `robot_config` (this tier) and
mobile fixtures (Tier 4) before it means anything.

**Tier 4 — fixtures.** Mobile scenarios beside the eleven arm fixtures.

## See also

- [`sufficiency.md`](sufficiency.md) — §5.1, the question this reclassifies, and
  §2's asymmetry that §2.1 reaches into.
- [`limitations.md`](limitations.md) — §2 and §3, the under-approximation and the
  radial overclaim check that §3 above makes harder to leave alone.
- [`plan.md`](plan.md) — the non-goals table §5 defers to, and Phase 2's envelope.
- [`retention.md`](retention.md) — the figures §5 declines to disturb.
- [`prior-art.md`](prior-art.md) — where §6's entries live properly.
