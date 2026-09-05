# The mobile base — what moving the robot does to the argument

**Status:** a design document, and no longer entirely one · written 2026-08-31 ·
**Tiers 1, 2, 3 and 4 have landed; §3's construction landed 2026-09-02 (issue
#163), §1's refusal landed 2026-09-02 (issue #164), §4's two `declare.py`
defects were fixed 2026-09-02 (issue #165) and §4's schema work landed
2026-09-02 (issue #166); a scenario can express a driven
base since 2026-09-04 (issue #177), and since 2026-09-04 (issue #184) the room
containment check follows that base's whole executed path and covers the arm
sweeping over it, and since 2026-09-04 (issue #189) an `Enforcer` constructs for
a driven base and adjudicates one, resting on `horizon_bound` alone, and since
2026-09-05 (issue #191) the pose reaches `robot_config` and a run whose base
moved retains its geometry; Tier 4 completed 2026-09-05 (issue #178) with the
three mobile fixtures, so this repository has runs in which a robot drives and
an artifact built from one — but they are a second catalogue and none of them is
priced, so `SCENARIOS` is still the eleven bolted arms and Claim 1 is still a
fixed-arm claim** — the build order in §7 says per
tier which is which and what the track still does not support, and it is the
authority, not this line ·
normative for the mobile track only; where it touches what the project may
claim, it defers to [`sufficiency.md`](sufficiency.md) and
[`limitations.md`](limitations.md) until those files carry the change themselves
— **§2.1 and §2.2 now do**, carried into `sufficiency.md` §2, §5.1, §5.6 and §7
on 2026-09-01 (issue #139); **§3's looseness now does**, carried into
`limitations.md` §10 on 2026-09-02 (issue #163); and **§1's refusal now does**,
carried into `limitations.md` §3 and §9 and into
[`../CLAUDE.md`](../CLAUDE.md) rule 3 on 2026-09-02 (issue #164); **and §4 item
4's schema work now does**, carried into `sufficiency.md` §5.8 and
[`lossiness.md`](lossiness.md) on 2026-09-02 (issue #166); those files are
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

*Half of that condition was met by issue #166 and the other half by issue #191,
and what the refusal guards has moved rather than gone.* #166 put the **pose** on
the row and not the velocity, and added a second refusal at the *read* —
`envelope_at` will not recompute a discarded polygon for a configuration that
states a pose — so the two absences could not compound into a fixed-base region
returned as a mobile one. #191 then made a mobile artifact writable, so the
sentence above — *a mobile artifact cannot be written at all* — no longer holds
and the guarantee it stood for is carried differently:

- The **velocity** is still not on `robot_config`, and this refusal still fires
  where it always did. `reg.graph.build` reads `base_vel` off the *stream*, which
  has carried it since issue #176, so a driven run whose stream records no base
  velocity is refused by `outer_envelope` at build time — with fixed-base numbers
  never reaching the file, which is what the refusal is for.
- The **read** no longer needs a recomputation to refuse: `GEOMETRY_RETENTION`
  keeps the polygon on every posed configuration, so `envelope_at` returns the
  retained region and reaches its refusal only for a row that should not exist —
  and one that does not, because the build refuses to write it.

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

*`BASE_XY` is gone — removed 2026-09-04, issue #184, and the count above is why
it could be.* Two read sites and no parameter is a symbol whose only job was to
restate a mounting fact, and restating a fact in a second place is how the two
drift. [`reg.kinematics.ORIGIN_FRAME`](../reg/kinematics.py) is the statement
now, and `grep ORIGIN_FRAME` is meant to be the list of places this repository
assumes a base that does not move — which is the list this section was written
to produce. What follows is the survey as written on 2026-08-31.

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
4. `reg/store.py` — **fixed 2026-09-02, issue #166.** The envelope-recompute
   argument stopped holding. `geometry_wkb` may be NULL because the polygon is a
   deterministic function of the `robot_config` a row names plus four `meta`
   numbers; with a moving base that function is incomplete, and `envelope_at`
   would recompute an envelope at the origin for a robot that was elsewhere.
   Worse, the retained `outer_radius` was a radius **about an unstated centre** —
   globally known then, meaningless once a row can say otherwise. That was the
   decisive argument for putting the pose on the `robot_config` row, and it
   needed a `SCHEMA_VERSION` bump.

   It has one. `robot_config` carries `base_pose` and `base_pose_source`, `meta`
   carries `base_frame` for a run whose base was bolted, `SCHEMA_VERSION` is 10
   and the gate names what changed. `envelope_at` **refuses** a posed
   configuration rather than recomputing it at the origin, and a retained
   `outer_radius` requires the config that states its frame. The claim change
   came with it and it is the part that was not in the issue title: an edge
   resting on a posed configuration is Layer B though it names no `Entity`, and
   the four attestation edges — layer `A` by type — are **refused** over one
   rather than relabelled, because relabelling them is
   [`sufficiency.md`](sufficiency.md) §2's asymmetry and not a call site's
   decision. Where this list and [`sufficiency.md`](sufficiency.md) §5.8 differ
   from here on, **§5.8 is right**: it is normative for what the project may
   claim and this is a design document.

   *Since 2026-09-05 and issue #191 this repository does write a posed
   configuration*, and the sentence that stood here — *the base velocity is
   still not on the row, so §3's refusal still stands and a mobile artifact
   still cannot be built* — no longer holds. §3's refusal is unchanged and still
   fires where it fired: it is `outer_envelope` refusing a state whose
   `base_vel` is `None` for a robot that can drive, and the builder reads that
   velocity off the *stream*, which has carried it since issue #176. What the
   row does not hold is the velocity, which is why `envelope_at` reconstructs
   states with `base_vel=None` — and why it refuses a posed configuration before
   reaching that line, so the two absences still cannot compound. What replaces
   the recomputation for a posed row is the retained polygon, not a looser
   recomputation: see §7 Tier 4.
5. `reg/declare.py` — **fixed 2026-09-02, issue #165.** `declared_region`
   *raised* on a disconnected union, on the argument that every configuration's
   first link contains the base. A declaration spanning base motion can be
   legitimately disconnected, so a correct region would be refused. The argument
   was true and was an argument about the *base*: it holds because every first
   link contained the same point. `declared_region` now takes the frame each
   configuration is measured from — one `BaseFrame` for a base that did not move,
   one per configuration when it did — and refuses a `MultiPolygon` only in the
   first case, where a disconnected union is still a broken grid or broken
   kinematics. The record did **not** widen with it: `envelope_wkb` and
   `Declaration` still take a single `Polygon`, so a disconnected region is a
   loud could-not-evaluate at the boundary where the bytes are made, and the
   multi-part declared bound is part of the schema work below and not of this.
6. `reg/declare.py` — **fixed 2026-09-02, issue #165.** `_classify` read `reach`
   versus `retract` off the end effector's distance to the origin. A robot
   driving forward with a frozen arm classified as a `reach`, and there is no
   tolerance anywhere to absorb it. The comparison is now the end effector's
   distance from **its own base**, which base translation and yaw cannot enter,
   and the `hold` branch asks whether the base moved as well — driving with a
   frozen arm is a `traverse`, which is what that class already meant for an arm
   rotating about a fixed base. Every fixture is fixed-base and every published
   classification is unchanged, asserted in
   `tests/test_declare.py::test_every_fixture_classification_is_unchanged`.
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

**Tier 3 — the envelope and the bound. Complete, 2026-09-02; the enforcer over a
driven base followed on 2026-09-04 (issue #189).** The body-frame outer envelope with the
base states and a rewritten soundness argument — **done, 2026-09-02, issue
#163**, and its looseness is [`limitations.md`](limitations.md) §10;
`computed_bound` refusing and `horizon_bound` on the outer envelope alone —
**done, 2026-09-02, issue #164**, and the normative statements are
[`limitations.md`](limitations.md) §3 and §9 and
[`../CLAUDE.md`](../CLAUDE.md) rule 3; the two `declare.py` defects — **done,
2026-09-02, issue #165**, §4 items 5 and 6, and neither changed a classification
or a declared envelope byte in any fixture, because for a base at one point the
old measurement and the new one are the same number; and the pose on
`robot_config` with the schema bump — **done, 2026-09-02, issue #166**, §4 item
4, and the normative statement of what it decided is
[`sufficiency.md`](sufficiency.md) §5.8, with
[`lossiness.md`](lossiness.md)'s recomputation clause restated in the same
change. Every existing artifact holds the same rows it did, because every
fixture here is bolted down and writes `base_pose` NULL — but it is **not**
byte-identical and **the published figures moved**, by +0.20% to +0.29%. Two
nullable columns cost one SQLite record-header byte each on every
`robot_config` row that exists, whether or not anything is written into them, so
a schema that can hold a base pose cannot also leave the byte counts still. The
measurement, the attribution and the list of documents re-measured with
`python -m reg.bench --resolution --seed 0` are in
[`lossiness.md`](lossiness.md) *Retained* #8; the issue asked for no movement and
that part of it could not be met.

*The claim change that tier made, in one sentence, because it is the one thing
here a reader should not have to find in a subsection.* A base pose is the first
dependency on something outside the robot that reaches an edge naming **no
`Entity`**, so `reg.store.open_edge` reads the pose off the endpoint and refuses
a Layer A tag on an edge resting on one. That closes the gap §2.1 records and
[`sufficiency.md`](sufficiency.md) §5.6 predicted:
`tests/test_graph.py::test_layer_b_is_exactly_the_entity_naming_edges` now
constructs that edge and requires the refusal, so the layer boundary is enforced
for the one case this whole track is about rather than for the four edge types
that existed before it.

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

*The enforcer runs on a robot that drives — done, 2026-09-04, issue #189.* This
entry previously read "what Tier 3's refusal does **not** buy: `Enforcer` refuses
to construct for a driven base, because it names the workspace disc in every
`envelope_overclaim` reason it writes and there is no honest number to put
there." The first clause was true and the second was the wrong reason for it.
The disc is **not** the bound `Enforcer.offer` refuses declarations against —
that is `horizon_bound(state, limits, window, substep_dt)`, recomputed per offer
and resting on `outer_envelope` alone for a vehicle since #164. The disc appeared
in one place: the parenthetical an `envelope_overclaim` reason ends with. So the
constructor stopped asking `computed_bound` for a disc the robot does not have,
`Enforcer.bound` became `float | None` with `None` meaning *no horizon-free
radius exists for this robot*, and the parenthetical was **rewritten** for the
mobile case rather than dropped — it names the fields that made the workspace
unbounded, in the shape §1's refusal already uses, because a mobile VETO that
simply went quiet about the disc would read like a fixed-base one whose disc went
unmentioned and an operator cannot tell those apart. #164's refusal is untouched
and is not caught anywhere: `computed_bound` is not called for a driven base at
all, which `tests/test_enforce.py::test_no_code_path_catches_the_computed_bound_refusal`
asserts against the source of every module in `reg/`. Nothing in this repository
changed behaviour — every fixture is still bolted down, every fixed-base reason
string is byte-identical and pinned as an equality, and no published figure
moved. What it buys is the thing Tier 4 needs: a mobile scenario can now produce
a verdict, so a mobile fault fixture is a fixture and not a wish.

**Tier 4 — fixtures. Complete, 2026-09-05.** Mobile scenarios beside the
eleven arm fixtures — and *beside* is literal: a second catalogue, not an
addition to the first.

*A scenario can drive, and states where its pose came from — done, 2026-09-04,
issue #177.* `Scenario` carries `base_waypoints`, knots of `(x, y, theta)`
interpolated as the joint ones are and integrated under `base_v_max`,
`base_a_max`, `base_omega_max` and `base_alpha_max` exactly as the joints are
integrated under `qdd_max` — the issue #96 argument one frame out, and it
matters more here than it did there, because since #164 the outer envelope is
the *only* term a mobile robot is VETOed against. Beside the trajectory the
fixture states **three things it is not allowed to omit**: a
[`PoseSource`](../reg/types.py) for the poses it writes, a `VelocitySource` for
the body-frame rates, and a `(metres, radians)` jitter pair. A simulator's base
pose is ground truth, which is the status `human_pos` already has; writing it
without a provenance would put an unlabelled room-frame pose into the stream and
leave every reader to assume one, and the only party that knows whether a pose
was dead-reckoned or localized is whoever produced it — issue #84's argument,
one type over. Stating a provenance with no trajectory is refused as the
contradiction it is, and a scenario with no trajectory is a **fixed-base
scenario**, said by `Scenario.drives` rather than by a pose at the origin, which
is a mounting fact no `PoseSource` describes (#150).

*What that change cost elsewhere, because it is a refusal and not a feature.*
`reg.graph.build` **refused a stream whose frames state a base pose**, from
2026-09-04 until issue #191 replaced the refusal with the thing it stood in for
(below). It wrote `base_pose` NULL on every `robot_config` row it produced, so
building one of these would have turned a run whose base drove into an artifact
saying no base pose was recorded — same row count, every check green, and every
envelope in it readable as the region a robot at `meta[base_frame]` could reach.
Issue #166 built the refusal for the half of that path it could see (`_recompute`
refuses a config that states a pose); that was the half in front of it, which
never fired before because nothing wrote the pose. `base_vel` was not refused: it
is body-frame, Layer A, and `outer_envelope` reads it correctly (#163).

*The room holds the whole robot, for the whole run — done, 2026-09-04, issue
#184.* `World.__post_init__` used to assert that the room contained the module
constant `BASE_XY` as a point of zero radius, and both halves of that stopped
working at once. **The subject** was wrong even for a bolted arm: a point test
passes a robot whose links sweep through a wall, which is the fixture bug the
check exists to catch, and it was only tolerable while the fixtures were
hand-placed against a stated 1.20 m reach. **The place** was wrong for a base
that drives: the question is whether the robot stays in the room *over the run*,
a driven base has a path, and a `World` never sees a trajectory — a constructor
answering the question it can reach rather than the one that matters is a check
that has stopped checking. So the geometry stays in `World` as
`room_excursion`, which tests the disc the body can occupy and *reports* rather
than raises, and the check is `Scenario`'s, in two halves that are not the same
half written twice:

- **At construction**, the scripted knots — inflated by the metres half of
  `base_jitter`, because the seed moves each knot by up to that much and a
  fixture has to hold for every seed. A fixed-base fixture is finished here: it
  has one pose for the whole run and it is `ORIGIN_FRAME`.
- **Per frame, in `states`**, the pose that frame records. This is the half the
  acceptance criterion is about, and it cannot be folded into the first: the room
  is convex, so a straight line between two knots that both fit cannot leave it,
  and checking the interpolated *script* would be the waypoint check written at
  greater length. What leaves the room between two waypoints is the trajectory
  the base **executes**, which lags its reference and overshoots every corner
  under `base_a_max` and `base_alpha_max` (the §7 Tier 4 integrator, above).

The refusal names the instant and the part — which frame, which second, which
seed, which wall, and whether the *base* crossed it or only the disc its body can
occupy, which are different fixture bugs with different repairs. None of the
eleven arm fixtures is refused by the widened check and every artifact is
byte-identical; no published figure moved.

*The pose reaches `robot_config` for real — done, 2026-09-05, issue #191.* This
is what turns the refusal above back into a build, and it is four decisions that
travel together.

- **The pose is written from the frame**, and `None` only where the frame states
  none. `meta[base_frame]` is then **absent**, because *bolted here* and
  *localized there* are two claims about one run and
  `reg.store.insert_robot_config` refuses a file making both; `envelope_frame`
  reads the centre off the row's own `base_pose` instead. Where a run recorded a
  pose is a whole-run fact, so a stream that records one on some frames and not
  others is refused — `reg.stream` will not write such a stream either, and two
  guards on the same condition is the right number when the second one is what
  decides a `meta` key.
- **`GEOMETRY_RETENTION` retains the polygon on every frame whose configuration
  states a pose**, and the rule text in `meta` says that condition out loud. This
  is the load-bearing half. The discard rule is licensed by recomputability;
  §4 item 4's refusal is the statement that for a posed configuration there is
  none, so retaining nothing and refusing on read would make every envelope query
  on a mobile artifact a could-not-evaluate — a file that parses and answers
  nothing. It retains the *polygon*, not the *row*: a posed frame that anchors
  nothing is still a frame `ENVELOPE_RETENTION` keeps no node for, because
  forcing a row per posed frame would put issue #29's linear-in, linear-out shape
  back for exactly the runs this tier is about. A posed row with a NULL geometry
  is refused at build rather than written, and the check reads the file rather
  than the builder's own bookkeeping.
- **The polygon retained is the room-frame envelope** — the body-frame set
  rigidly placed at the pose, which is the third row of §2's table and Layer B
  for the reason that row gives. Retaining the *body-frame* set would have
  reintroduced §4 item 4's failure one door along: a region about the origin
  handed back for a robot that was elsewhere, arriving from storage instead of
  from a recomputation and looking exactly as much like a right answer. It is
  also what makes the rest of the artifact true, because every `INTERSECTS`
  overlap and `SEPARATION` distance in the file is measured against entities in
  room coordinates. `compute_envelope` gained no frame argument and must not:
  the placement happens in `reg.graph`, on the answer, which is where the world
  already is.
- **The layer tag follows**, as §5.8 of [`sufficiency.md`](sufficiency.md)
  already said it must: every `HAS_ENVELOPE` edge over a posed configuration is
  `B`, whatever `Limits.source` says. `reg.store.open_edge` refusing an `A` is
  the guard and stays the guard; the builder states the `B` rather than being
  told about it one row too late.

*And no published figure moved.* `GEOMETRY_RETENTION`'s text lands in `meta` in
every artifact, including the eleven fixed-base ones, so their bytes are not
identical — #166 is the precedent for expecting movement. It was re-measured with
`python -m reg.bench --resolution --seed 0` and the report is byte-identical to
the one before the change: 1,006,592 B / 2,501,632 B / 3,632,128 B, which at this
fixture's 50 Hz control rate is 60.42 / 150.15 / 218.00 MB/h. One longer string
in one `meta` row does not cross a page
boundary, where #166's two nullable columns cost a record-header byte on every
one of 2,560 `robot_config` rows. The control-rate ladder
[`sensor-baseline.md`](sensor-baseline.md) publishes — all four rungs, including
the three CI does not pin — was re-measured too, with
`python -m reg.bench --control-rate-hz 50,100,250,1000 --seed 0`, and that report
is byte-identical as well.

*The fixtures, and with them the tier — done, 2026-09-05, issue #178.* Three
scenarios drive: `mobile_transit`, `mobile_frozen_arm` and `mobile_overclaim`.
They are the first runs in this repository in which anything has moved a robot,
and each exists to make one claim of this track exercisable rather than to cover
a motion:

- **`mobile_transit` — the room-frame answer is Layer B, and the pose is in the
  artifact** (§2, [`sufficiency.md`](sufficiency.md) §5.6, issue #191). A person
  stands still for five seconds. From the pose the run starts at they are
  outside the *workspace disc* — the set of every configuration of the arm, with
  no horizon in it — so no question about the arm asked at t=0 puts the robot
  near them; after a 0.79 m transit they are inside the arm's forward reachable
  set, bodies clear by about 6 cm. One question, one coordinate, two answers in
  one run, and what changed is a pose nothing on the robot measured. Built into
  an artifact it is also the demonstration that a mobile run survives the
  builder: `reachable_entities` names nobody over the first second and names the
  human over the last.
- **`mobile_frozen_arm` — driving is not reaching** (§4 item 6, issue #165). The
  arm holds one configuration, `q_jitter=0.0` so that no seed unfreezes it,
  while the base drives a metre and turns 0.6 rad. The end effector crosses most
  of a metre of room and the arm's extension does not move by one bit. Handed
  the poses the run recorded, `reg.declare._classify` says `traverse`.
- **`mobile_overclaim` — the bound rests on the outer envelope alone** (§1,
  issue #164), and it is this tier's **fault** in the taxonomy sense. The policy
  pads every declared region by 60 cm. On a bolted arm that padding is refuted
  by `computed_bound`'s 0.95 m workspace disc; for this robot that function
  *refuses*, naming the base bounds that made the workspace unbounded, so the
  only bound left is the radial projection of the horizon-limited outer
  reachable set — 1.12 m at rest and up to 1.34 m at speed over this run, larger
  than the arm's disc because the vehicle can drive out of it, and not a
  constant because its speed is not one. Every declaration in the run is VETOed
  against that and against nothing else. A mobile fixture set in which nothing
  ever went wrong would exercise the happy path of a mechanism whose entire
  purpose is the unhappy one.

*They are a second catalogue, not an addition to the first, and that is the half
every published figure depends on.* They live in
`reg.scenarios.MOBILE_SCENARIOS`; `SCENARIOS` is still exactly the eleven.
`reg.scenarios.scenario()` resolves both, because a stream's provenance block
records a *name* and a name nothing can resolve is a run whose world cannot be
recovered from the file — but nothing that **iterates** `SCENARIOS` sees a
mobile fixture, so `reg.bench --all` prices the eleven it always priced and
`reg.bench --scenario mobile_transit` is refused by name. `reg.sim --list`
prints both groups under headings, because a fixture nothing lists is a fixture
nobody can run. **Claim 1 stays a fixed-arm claim**: no mobile artifact is
priced, benchmarked or reported beside the fixed-arm figures, and
[`retention.md`](retention.md)'s figures were neither re-measured nor extended.
Every one of the eleven writes the 24-column `expected_header(2, 3)` it always
wrote, every artifact built from one is byte-identical to what it was before
this change, and **no published figure moved**.

*What the track supports now that this has landed.* A robot that drives can be
simulated, streamed, built, adjudicated and queried end to end: `python -m
reg.sim --scenario mobile_transit --out runs/mobile.csv` writes a stream with
both base blocks in it, `reg.graph.build` turns it into an artifact whose every
`robot_config` row states the pose its frame stated and whose every
`HAS_ENVELOPE` edge is Layer B, and `reg.query` answers the standard questions
against that artifact — separation, closest approach, contact, the timeline,
frames at risk, the first envelope intersection and the reachable set — with no
could-not-evaluate among them. An `Enforcer` adjudicates the run, and a VETO in
it rests on `outer_envelope` alone.

*What it still does not, and the first one is a gap this tier surfaced rather
than a decision it took.*

- **The scripted policy cannot say `traverse`.** `reg.declare.emit_declarations`
  passes `ORIGIN_FRAME` to the classifier for every run, because a policy sees a
  `ProprioState` and a base pose is Layer B — so over `mobile_frozen_arm` every
  declaration comes back `hold`, which is exactly what §4 item 6 says a driving
  robot is not doing. Nothing here is wrong to fix it in the fixture: the honest
  repair is for the policy to dead-reckon its own frames from `base_vel`, a
  Layer A quantity it does hold, and that is a decision about what the scripted
  policy *is*.
  `tests/test_enforce.py::test_no_declaration_over_a_driving_base_is_a_reach`
  pins the half that is settled — no declaration in that run is a `reach` — and
  records the rest.
- **No perceiver is built** (§5). The fixtures state
  `PoseSource.DEAD_RECKONED`, which is the honest label for a simulator that
  localizes nothing, and there is no localization error model behind it: the
  `(metres, radians)` jitter is fixture noise, not a drift process, so nothing
  here supports a claim about how far a dead-reckoned pose has drifted by the
  end of a run.
- **No mobile figure is published.** These three are not benchmarked, and the
  size of a mobile artifact is not a number this repository reports beside the
  fixed-arm curve. It is not comparable: a driving run writes the two optional
  base blocks, so the gzipped baseline every ratio is divided by is a different
  file.
- **The bound is still radially incomplete** ([`limitations.md`](limitations.md)
  §2 and §3), and a mobile run does not change that — it detects a declaration
  reaching further than the robot can get in the window, not one pointing where
  the robot cannot turn in time.

## See also

- [`sufficiency.md`](sufficiency.md) — §5.1, the question this reclassifies, and
  §2's asymmetry that §2.1 reaches into.
- [`limitations.md`](limitations.md) — §2 and §3, the under-approximation and the
  radial overclaim check that §3 above makes harder to leave alone.
- [`plan.md`](plan.md) — the non-goals table §5 defers to, and Phase 2's envelope.
- [`retention.md`](retention.md) — the figures §5 declines to disturb.
- [`prior-art.md`](prior-art.md) — where §6's entries live properly.
