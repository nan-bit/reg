# The mobile base — what moving the robot does to the argument

**Status:** a design document with most of its track built · written 2026-08-31 ·
**Tiers 1 to 4 have landed**, so this repository has runs in which a robot drives
and artifacts built from them; none of them is priced, so `SCENARIOS` is still
the eleven bolted arms and Claim 1 is still a fixed-arm claim · the build order
in §7 says per tier what is built and what the track still does not support, and
it is the authority, not this line · normative for the mobile track only; where
this document touches what the project may claim,
[`sufficiency.md`](sufficiency.md) and [`limitations.md`](limitations.md) are the
normative statement, and `## Why` records which section of which carries what ·
keep current

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

`reg.enforce.computed_bound` refuses a `Limits` with any nonzero base bound,
naming the field, and `horizon_bound` rests on `reg.envelope.outer_envelope`
alone for that robot. The normative statements are
[`limitations.md`](limitations.md) §3 and §9 and
[`../CLAUDE.md`](../CLAUDE.md) rule 3; what follows is the argument they state.

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

**`horizon_bound` has no floor under it.** For a fixed base it is
`min(computed_bound(limits), outer_radius(outer_envelope(state, limits, ...)))`,
where the first term is sound by a trivial argument and the second is a
tightening. For a mobile robot the first term is gone and the second is the
**only** bound — so every VETO rests on the outer envelope's soundness argument,
and `tests/test_envelope.py::test_no_bang_bang_trajectory_escapes_the_outer_envelope`
is the load-bearing test rather than merely a good one.
[`CLAUDE.md`](../CLAUDE.md) rule 3 names which case each term applies to, and
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
verified action ([`prior-art.md`](prior-art.md) §23).

`reg` cannot take that answer, for two reasons that are architectural rather than
preferences. The guarantee lives in the *planner*, which is the common-cause
structure [`CLAUDE.md`](../CLAUDE.md) rule 3 refuses; and this project's
enforcement layer VETOes a declaration and commands nothing, while the one thing
in the tree that resembles a fail-safe — passivation — is a *record about* a stop
and not a stop: it reaches a table, an edge and a query, and none of the three
commands anything. A project that cannot command a stop cannot rest a bound on
having one.

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
where this project draws the layer boundary.

Even set-theoretic localization, which returns a set **guaranteed** to contain
the true pose rather than a distribution over it, is guaranteed only under
bounded-error hypotheses and a map, both exogenous; a guarantee conditioned on a
Layer B input is a Layer B guarantee ([`prior-art.md`](prior-art.md) §25). **No
localizer of any kind moves the base pose to Layer A.** State it in that form,
because the sensing-status form invites someone to go and build the localizer.

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
by what the vehicle can do before stopping, and switch it with speed: a
horizon-limited body-frame reachable set, arrived at by a standards committee for
the same reason it is arrived at here ([`prior-art.md`](prior-art.md) §22). Two
independent derivations agreeing is worth more than the derivation was.

But *protective field* is a term of art carrying a conformance meaning — a rated
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

[`sufficiency.md`](sufficiency.md) is where that is recorded and that copy is the
normative one: §5.6 carries the three-row split and this subsection's loss, §5.1
states its own verdict as conditional on a fixed base and names the Layer A
survivor, and §2 reconciles the paragraph below against `reg/store.py`. Where the
two files differ, **`sufficiency.md` is right** — it is normative for what the
project may claim and this is a design document.

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
[`sufficiency.md`](sufficiency.md) §7 carries it as a bullet beside the two
already there, on the same terms it is put here: recorded, not resolved.

**Reuse the precedent `Limits.source` set.** It is a two-value tag with the
simplification stated out loud rather than a graded integrity attribute. A pose
provenance enum beside `LimitSource`, with no default and no inference, and the
drift horizon recorded rather than modelled. Do not build a graded scheme here;
that decision is taken and its reasons have not changed.

A second nuance of the same kind, recorded for the same reason. A set-theoretic
localizer returns a **pose set**, not a point, and a set composes with §3's
construction directly: the room-frame envelope becomes the body-frame set
Minkowski-summed with the pose set instead of rigidly transformed by a point,
which preserves the over-approximation across the frame change where a point does
not ([`prior-art.md`](prior-art.md) §25).

Today's Layer B tag is binary — it says the answer inherited the perceiver and
says nothing about how wrong it can be — and a pose set is the shape in which a
magnitude could be carried. It is the same collision with the paragraph above's
precedent, so it gets the same treatment: recorded here, decided in the same
change as the provenance enum or not at all.

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

So the base is handled **analytically and composed with the arm**, not gridded
beside it: a body-frame translation bound over the horizon, Minkowski-summed with
the arm's own body-frame outer set. That is deliberately loose, it is **published
as loose**, and [`limitations.md`](limitations.md) §10 is the normative statement
of the looseness. Where this section and §10 differ, **§10 is right**: it is
normative for what the project may claim and this is a design document.

**The construction.** `reg.envelope.base_motion_bounds` returns the two scalars,
the yaw folds into the first joint's angular interval — exactly, because turning
the vehicle about the base point and turning joint 0 produce the same body — and
the translation is one `buffer` on the arm's set. `MAX_OUTER_GRID_CONFIGS` is not
raised for it, which is the test of whether the construction is the right one,
and `tests/test_envelope.py::test_no_bang_bang_trajectory_escapes_the_outer_envelope_with_a_driven_base`
drives the vehicle as well as the joints.

**`outer_envelope` refuses a state whose `base_vel` is `None` when the base can
move.** *Not recorded* is a could-not-evaluate, and reading it as a base standing
still would produce an outer bound that is too small — the one direction it may
not be wrong in. Two things follow, and between them they are what stops a mobile
artifact carrying fixed-base numbers:

- The **velocity** is not on `robot_config`. `reg.graph.build` reads `base_vel`
  off the *stream*, which carries it, so a driven run whose stream records no
  base velocity is refused by `outer_envelope` at build time — with fixed-base
  numbers never reaching the file, which is what the refusal is for.
- The **read** needs no recomputation to refuse: `GEOMETRY_RETENTION` keeps the
  polygon on every posed configuration, so `envelope_at` returns the retained
  region and reaches its refusal only for a row that should not exist — and one
  that does not, because the build refuses to write it.

The tighter construction has a name and a literature — RTD and REFINE compute
exactly this forward reachable set for ground robots with zonotopes, and CORA's
conservative linearization gives a large convex over-approximation of a Dubins
car where polynomial zonotopes capture the non-convexity. `reg` must not build
it: *no new dependencies* is a standing rule and *an HJ reachability solver* is a
stated non-goal in [`plan.md`](plan.md).

**What is loose, and why, in the terms that literature uses.** Conservative
linearization is what makes a nonlinear model analysable at all — linearize, then
add a set-valued abstraction-error term covering everything the linearization
dropped. It is not what makes the answer convex; the **representation** is, and a
zonotope is convex and centrally symmetric where the true set of a Dubins-like
model curves. Polynomial zonotopes are the same tool's other representation and
capture the curvature ([`prior-art.md`](prior-art.md) §24).

The Minkowski sum above is that literature's primitive — zonotopes exist partly
because the operation is exact and cheap on them, and on a `shapely` polygon it
is a buffer whose error compounds with every step. So the looseness this section
publishes is a **representation cost**, paid for not taking a dependency this
project has already refused, and *how much* it costs has not been computed for
this construction by anyone.

**This makes the open decision about radial containment harder to defer.** The
overclaim check is radial. For a nonholonomic base a radial bound is very weak —
a robot that cannot turn is nowhere near the rim of its own disc — so radial-only
containment, already incomplete for the arm
([`limitations.md`](limitations.md) §2 and §3), is close to useless for a base.

## 4. Blast radius

[`reg.kinematics.ORIGIN_FRAME`](../reg/kinematics.py) is this repository's single
statement of the mounting fact, and `grep ORIGIN_FRAME` is the list of places
that assume a base which does not move — which is the list this section was
written to produce.

Two pieces survive untouched and they bound the work: `_sector` already takes an
explicit centre, and `reachable_joint_box` and `_reach` are pure joint-space. The
base-relative half of the envelope construction is reusable as it stands.

What breaks, worst first — every item but the last is now taken by a tier, and
each is stated as it behaves rather than as the survey found it. `## Why` dates
the survey.

1. `reg/kinematics.py` — **built.** The explicit leading `0.0` in the cumulative
   sums **is** the base, and everything else is downstream of those two lines.
   `forward_kinematics(q, limits, base)` takes the frame, required and with no
   default; a bolted arm passes `ORIGIN_FRAME`.
2. `reg/envelope.py` — **built.** The disc intersected into the outer bound is
   centred on the frame the bound is computed at rather than on the origin.
   Silently unsound if missed (§1).
3. `reg/enforce.py`'s `_furthest_vertex` and `reg/envelope.py`'s `outer_radius` —
   **built.** Both measure distance from a `BaseFrame`, required and with no
   default, and it must be the frame the bound they are compared against was
   computed at. Both are on the VETO path, which is why neither may invent one.
4. `reg/store.py` — **built.** The envelope-recompute argument stops holding.
   `geometry_wkb` may be NULL because the polygon is a deterministic function of
   the `robot_config` a row names plus four `meta` numbers; with a moving base
   that function is incomplete, and a recomputation would return an envelope at
   the origin for a robot that was elsewhere. Worse, a retained `outer_radius` is
   a radius **about a centre** — globally known while every base is bolted,
   meaningless once a row can say otherwise. That is the decisive argument for
   putting the pose on the `robot_config` row, and it needed a `SCHEMA_VERSION`
   bump.

   `robot_config` carries `base_pose` and `base_pose_source`, `envelope_at`
   **refuses** a posed configuration rather than recomputing it at the origin,
   and a retained `outer_radius` requires the config that states its frame. Four
   decisions travel with that, and none of them is separable from it:

   - **The pose is written from the frame**, and `None` only where the frame
     states none. `meta[base_frame]` is then **absent**, because *bolted here*
     and *localized there* are two claims about one run and
     `reg.store.insert_robot_config` refuses a file making both; `envelope_frame`
     reads the centre off the row's own `base_pose` instead. Where a run recorded
     a pose is a whole-run fact, so a stream that records one on some frames and
     not others is refused — `reg.stream` will not write such a stream either,
     and two guards on the same condition is the right number when the second one
     is what decides a `meta` key.
   - **`GEOMETRY_RETENTION` retains the polygon on every frame whose
     configuration states a pose**, and the rule text in `meta` says that
     condition out loud. This is the load-bearing half. The discard rule is
     licensed by recomputability; the refusal above is the statement that for a
     posed configuration there is none, so retaining nothing and refusing on read
     would make every envelope query on a mobile artifact a could-not-evaluate —
     a file that parses and answers nothing. It retains the *polygon*, not the
     *row*: a posed frame that anchors nothing is still a frame
     `ENVELOPE_RETENTION` keeps no node for, because forcing a row per posed
     frame would put the linear-in, linear-out shape back for exactly the runs
     this tier is about. A posed row with a NULL geometry is refused at build
     rather than written, and the check reads the file rather than the builder's
     own bookkeeping.
   - **The polygon retained is the room-frame envelope** — the body-frame set
     rigidly placed at the pose, which is the third row of §2's table and Layer B
     for the reason that row gives. Retaining the *body-frame* set would
     reintroduce this item's failure one door along: a region about the origin
     handed back for a robot that was elsewhere, arriving from storage instead of
     from a recomputation and looking exactly as much like a right answer. It is
     also what makes the rest of the artifact true, because every `INTERSECTS`
     overlap and `SEPARATION` distance in the file is measured against entities
     in room coordinates. `compute_envelope` gains no frame argument and must
     not: the placement happens in `reg.graph`, on the answer, which is where the
     world already is.
   - **The layer tag follows.** An edge resting on a posed configuration is
     Layer B though it names no `Entity`, so every `HAS_ENVELOPE` edge over one
     is `B` whatever `Limits.source` says, and the four attestation edges — layer
     `A` by type — are **refused** over a posed configuration rather than
     relabelled, because relabelling them is
     [`sufficiency.md`](sufficiency.md) §2's asymmetry and not a call site's
     decision. `reg.store.open_edge` refusing an `A` is the guard and stays the
     guard; the builder states the `B` rather than being told about it one row
     too late. Where this item and [`sufficiency.md`](sufficiency.md) §5.8
     differ, **§5.8 is right**: it is normative for what the project may claim
     and this is a design document.
5. `reg/declare.py`, `declared_region` — **built.** A declaration spanning base
   motion can be legitimately disconnected, so refusing a `MultiPolygon`
   unconditionally refuses a correct region. The argument for that refusal — that
   every configuration's first link contains the base — is true and is an
   argument about the *base*: it holds because every first link contains the same
   point. `declared_region` takes the frame each configuration is measured from —
   one `BaseFrame` for a base that does not move, one per configuration when it
   does — and refuses a `MultiPolygon` only in the first case, where a
   disconnected union is still a broken grid or broken kinematics. The record
   does not widen with it: `envelope_wkb` and `Declaration` still take a single
   `Polygon`, so a disconnected region is a loud could-not-evaluate at the
   boundary where the bytes are made.
6. `reg/declare.py`, `_classify` — **built.** `reach` versus `retract` is the end
   effector's distance from **its own base**, which base translation and yaw
   cannot enter, and the `hold` branch asks whether the base moved as well —
   driving with a frozen arm is a `traverse`, which is what that class already
   meant for an arm rotating about a fixed base. Read off the distance to the
   *origin* instead, a robot driving forward with a frozen arm would classify as
   a `reach`, and there is no tolerance anywhere to absorb it. Every fixture is
   fixed-base and every published classification is unchanged, asserted in
   `tests/test_declare.py::test_every_fixture_classification_is_unchanged`.
7. `reg/world.py` — **built.** The room-contains-origin check has to become a
   check that the base's whole *path* stays in the room, which a constructor
   that never sees a trajectory cannot perform, so it moved to the scenario.
   §7.1 states the two halves it moved into.
8. `reg/bench.py` — **built.** A prefix match over `t`, `q_*` and `qd_*` treats a
   base column as Layer B **silently**, so `proprioceptive_columns` refuses a
   column carrying no rule in `COLUMN_RULES`, by name.
9. `reg/graph.py` — **built, by not quantizing.** The distance error budget is
   exactly saturated, so a quantized base pose would be a third error source in
   it. The pose is written at the raw stream's own precision with no quantum of
   its own, which is what keeps it out of that budget; the four tolerances are
   not quanta for a pose and inventing one would put a bound in the artifact no
   document states ([`lossiness.md`](lossiness.md) *Discarded* #9).
10. `reg/scenarios.py` — every fixed-base fixture's waypoints are hand-tuned
    against a distance from a base at the origin. Still true of the eleven, and
    it is why the mobile fixtures are a second catalogue rather than a
    re-tuning of the first (§7.2).

## 5. What this does not change

**Claim 1 stays a fixed-arm claim.** The mobile track is exploratory and
unbenchmarked. No published figure is re-measured, retired or moved by any of
this.

**No perceiver is built.** *Perception / vision / SLAM* is a binding non-goal in
[`plan.md`](plan.md) and stays one. The simulator supplies the base pose as
ground truth, tagged Layer B, exactly as it supplies the human's position.
Nothing localizes anything; the Layer B tag records that in a real system
something would have to.

## 6. Prior art, and what it was read from

Entered in [`prior-art.md`](prior-art.md) as the **fifth pass, 2026-09-01**,
§21–§25; summarised here so this document stands on its own. **Where this table
and the pass differ, the pass is right.**

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

| Tier | What it is | State |
|---|---|---|
| **0** | The fixed base as a limitations entry; `proprioceptive_columns` refusing an unclassifiable column (§5) | **built** |
| **1** | The argument: the fifth prior-art pass (§6), then [`sufficiency.md`](sufficiency.md) carrying §2.1's shrink of the certifiable question set | **built** |
| **2** | Types and the boundary: base velocity on `ProprioState`; a Layer B pose type; base actuation bounds on `Limits` under the existing no-default rule; pose provenance beside `LimitSource`; an explicit base frame in `forward_kinematics` | **built** |
| **3** | The envelope and the bound: the body-frame outer envelope with the base states (§3); `computed_bound` refusing and `horizon_bound` on the outer envelope alone (§1); the two `declare.py` seams (§4 items 5 and 6); the pose on `robot_config` with the schema bump (§4 item 4); an `Enforcer` that constructs for a driven base and adjudicates one | **built** |
| **4** | Fixtures: mobile scenarios **beside** the eleven arm fixtures, *beside* being literal — a second catalogue, not an addition to the first | **built** |

The layer-boundary allowlist and `sufficiency.md` move in the same commit as
Tier 2's first type change, because
`test_propriostate_fields_are_exactly_the_allowed_set` requires it. That is why
Tier 1 exists: the argument is settled before a type moves, rather than in the
same PR as one.

Tier 3's normative statements live elsewhere and this document defers to all of
them: [`limitations.md`](limitations.md) §10 for the outer envelope's looseness,
§3 and §9 plus [`../CLAUDE.md`](../CLAUDE.md) rule 3 for the bound,
[`sufficiency.md`](sufficiency.md) §5.8 for the schema work, and
[`lossiness.md`](lossiness.md) for the recomputation clause.

### 7.1 What Tier 4 ships

A scenario drives by carrying `base_waypoints`, knots of `(x, y, theta)`
interpolated as the joint ones are and integrated under `base_v_max`,
`base_a_max`, `base_omega_max` and `base_alpha_max` exactly as the joints are
integrated under `qdd_max`. It matters more here than it does for the joints,
because the outer envelope is the *only* term a mobile robot is VETOed against.

Beside the trajectory the fixture states **three things it is not allowed to
omit**: a [`PoseSource`](../reg/types.py) for the poses it writes, a
`VelocitySource` for the body-frame rates, and a `(metres, radians)` jitter pair.
A simulator's base pose is ground truth, which is the status `human_pos` already
has; writing it without a provenance would put an unlabelled room-frame pose into
the stream and leave every reader to assume one, and the only party that knows
whether a pose was dead-reckoned or localized is whoever produced it.

Stating a provenance with no trajectory is refused as the contradiction it is,
and a scenario with no trajectory is a **fixed-base scenario**, said by
`Scenario.drives` rather than by a pose at the origin, which is a mounting fact
no `PoseSource` describes.

**The room holds the whole robot, for the whole run.** The geometry is `World`'s,
as `room_excursion`, which tests the disc the body can occupy and *reports*
rather than raises; the check is `Scenario`'s, in two halves that are not the
same half written twice:

- **At construction**, the scripted knots — inflated by the metres half of
  `base_jitter`, because the seed moves each knot by up to that much and a
  fixture has to hold for every seed. A fixed-base fixture is finished here: it
  has one pose for the whole run and it is `ORIGIN_FRAME`.
- **Per frame, in `states`**, the pose that frame records. It cannot be folded
  into the first: the room is convex, so a straight line between two knots that
  both fit cannot leave it, and checking the interpolated *script* would be the
  waypoint check written at greater length. What leaves the room between two
  waypoints is the trajectory the base **executes**, which lags its reference and
  overshoots every corner under `base_a_max` and `base_alpha_max`.

The refusal names the instant and the part — which frame, which second, which
seed, which wall, and whether the *base* crossed it or only the disc its body can
occupy, which are different fixture faults with different repairs.

### 7.2 The four mobile fixtures

`reg.scenarios.MOBILE_SCENARIOS` holds four: `mobile_transit`,
`mobile_frozen_arm`, `mobile_overclaim` and `mobile_derived_velocity`. They are
the runs in this repository in which anything has moved a robot, and each exists
to make one claim of this track exercisable rather than to cover a motion.

- **`mobile_transit` — the room-frame answer is Layer B, and the pose is in the
  artifact** (§2, [`sufficiency.md`](sufficiency.md) §5.6). A person stands still
  for five seconds. From the pose the run starts at they are outside the
  *workspace disc* — the set of every configuration of the arm, with no horizon
  in it — so no question about the arm asked at t=0 puts the robot near them;
  after a 0.79 m transit they are inside the arm's forward reachable set, bodies
  clear by about 6 cm. One question, one coordinate, two answers in one run, and
  what changed is a pose nothing on the robot measured. Built into an artifact it
  is also the demonstration that a mobile run survives the builder:
  `reachable_entities` names nobody over the first second and names the human
  over the last.
- **`mobile_frozen_arm` — driving is not reaching** (§4 item 6). The arm holds
  one configuration, `q_jitter=0.0` so that no seed unfreezes it, while the base
  drives a metre and turns 0.6 rad. The end effector crosses most of a metre of
  room and the arm's extension does not move by one bit. Handed the poses the run
  recorded, `reg.declare._classify` says `traverse`.
- **`mobile_overclaim` — the bound rests on the outer envelope alone** (§1), and
  it is this tier's **fault** in the taxonomy sense. The policy pads every
  declared region by 60 cm. On a bolted arm that padding is refuted by
  `computed_bound`'s 0.95 m workspace disc; for this robot that function
  *refuses*, naming the base bounds that made the workspace unbounded, so the
  only bound left is the radial projection of the horizon-limited outer reachable
  set — 1.12 m at rest and up to 1.34 m at speed over this run, larger than the
  arm's disc because the vehicle can drive out of it, and not a constant because
  its speed is not one. Every declaration in the run is VETOed against that and
  against nothing else. A mobile fixture set in which nothing ever went wrong
  would exercise the happy path of a mechanism whose entire purpose is the
  unhappy one.
- **`mobile_derived_velocity` — a base velocity out of a perceiver, and a layer
  tag that does not follow it** ([`limitations.md`](limitations.md) §11). The
  fourth, and the only one whose claim is a defect: `mobile_transit`'s run with
  `base_vel_source` changed to `VelocitySource.DERIVED`, visual odometry rather
  than wheel encoders. The other three state `PROPRIOCEPTIVE`, so the gap §11
  records was real in the code and in no run. `envelope_layer` answers `A` for
  this robot's limits while every frame states a perceiver, and the built
  artifact's `HAS_ENVELOPE` edges are `B` anyway — from the pose, not the
  velocity — so the tag is right by coincidence and nothing in the file says
  which of the two facts it followed. It makes the gap observable; closing it is
  issue #227 and changes this tag deliberately.

**They are a second catalogue, not an addition to the first, and that is the half
every published figure depends on.** They live in
`reg.scenarios.MOBILE_SCENARIOS`; `SCENARIOS` is still exactly the eleven.
`reg.scenarios.scenario()` resolves both, because a stream's provenance block
records a *name* and a name nothing can resolve is a run whose world cannot be
recovered from the file — but nothing that **iterates** `SCENARIOS` sees a mobile
fixture, so `reg.bench --all` prices the eleven it always priced and
`reg.bench --scenario mobile_transit` is refused by name. `reg.sim --list` prints
both groups under headings, because a fixture nothing lists is a fixture nobody
can run.

**Claim 1 stays a fixed-arm claim**: no mobile artifact is priced, benchmarked or
reported beside the fixed-arm figures, and [`retention.md`](retention.md)'s
figures are neither re-measured nor extended for one. Every one of the eleven
writes the 24-column `expected_header(2, 3)` it always wrote, and **no published
figure moved** for any of this tier.

### 7.3 What the track supports, and what it does not

A robot that drives can be simulated, streamed, built, adjudicated and queried
end to end: `python -m reg.sim --scenario mobile_transit --out runs/mobile.csv`
writes a stream with both base blocks in it, `reg.graph.build` turns it into an
artifact whose every `robot_config` row states the pose its frame stated and
whose every `HAS_ENVELOPE` edge is Layer B, and `reg.query` answers the standard
questions against that artifact — separation, closest approach, contact, the
timeline, frames at risk, the first envelope intersection and the reachable set —
with no could-not-evaluate among them. An `Enforcer` adjudicates the run, and a
VETO in it rests on `outer_envelope` alone.

What it does not support, and the first one is a gap this tier surfaced rather
than a decision it took:

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
- **No perceiver is built** (§5). The fixtures state `PoseSource.DEAD_RECKONED`,
  which is the honest label for a simulator that localizes nothing, and there is
  no localization error model behind it: the `(metres, radians)` jitter is
  fixture noise, not a drift process, so nothing here supports a claim about how
  far a dead-reckoned pose has drifted by the end of a run.
- **No mobile figure is published.** These three are not benchmarked, and the
  size of a mobile artifact is not a number this repository reports beside the
  fixed-arm curve. It is not comparable: a driving run writes the two optional
  base blocks, so the gzipped baseline every ratio is divided by is a different
  file.
- **The bound is still radially incomplete** ([`limitations.md`](limitations.md)
  §2 and §3), and a mobile run does not change that.

## See also

- [`sufficiency.md`](sufficiency.md) — §5.1, the question this reclassifies, and
  §2's asymmetry that §2.1 reaches into.
- [`limitations.md`](limitations.md) — §2 and §3, the under-approximation and the
  radial overclaim check that §3 above makes harder to leave alone.
- [`plan.md`](plan.md) — the non-goals table §5 defers to, and Phase 2's envelope.
- [`retention.md`](retention.md) — the figures §5 declines to disturb.
- [`prior-art.md`](prior-art.md) — where §6's entries live properly.

## Why

Nothing below is normative. It is the provenance of the sections above: which
issue each part arrived with, what each superseded, and what the two
re-measurements moved. A design document whose tiers have all landed is worth
least once nobody remembers which sentence was written before the code and which
after.

### When each part of the track landed

| Section | What landed | Issue | Dated |
|---|---|---|---|
| §1 | `computed_bound` refuses a nonzero base bound; `horizon_bound` on `outer_envelope` alone | #164 | 2026-09-02 |
| §2, §2.1, §2.2 | The argument carried into `sufficiency.md` §2, §5.1, §5.6 and §7 | #139 | 2026-09-01 |
| §3 | `base_motion_bounds` and the base in the outer set; looseness into `limitations.md` §10 | #163 | 2026-09-02 |
| §4 item 4 | The pose on `robot_config`, `SCHEMA_VERSION` 10, `sufficiency.md` §5.8 and `lossiness.md` | #166 | 2026-09-02 |
| §4 items 5 and 6 | The two `declare.py` defects | #165 | 2026-09-02 |
| §4 item 7, §7.1 | `BASE_XY` removed; the room check moved to `Scenario` | #184 | 2026-09-04 |
| §6 | The fifth prior-art pass, `prior-art.md` §21–§25 | #138 | 2026-09-01 |
| §7 Tier 3 | `Enforcer` constructs for and adjudicates a driven base | #189 | 2026-09-04 |
| §7.1 | `Scenario.base_waypoints`, `PoseSource`, `VelocitySource`, the jitter pair | #177 | 2026-09-04 |
| §7.1, §4 item 4 | The pose written to `robot_config`; `GEOMETRY_RETENTION` on posed frames | #191 | 2026-09-05 |
| §7.2 | The first three mobile fixtures | #178 | 2026-09-05 |
| §7.2 | `mobile_derived_velocity`, the fixture §11's gap is observable in | #229 | 2026-09-07 |
| §1 | The passivation clause: the record reaches a table, an edge and a query | #247 | 2026-09-07 |

Tiers 0 and 2 are absent from the table because this document never recorded the
issues they arrived on. That is a gap in the record, and a plausible number
written in here would be indistinguishable from a remembered one.

### §1's refusal, and the rule it rewrote

`CLAUDE.md` rule 3 described the bound as the smaller of two sound bounds. For a
mobile robot that sentence is false, so it was rewritten rather than amended — it
now names which case each term applies to, and `limitations.md` §3 carries the
same split. The argument §1 states is the one those three rewrites were made
from, kept as written.

Refusal is where that argument *ended* rather than where it started: the
fail-safe manoeuvre was read and declined for the two reasons §1 gives, and
recording that is worth more than concluding refusal as though nothing else had
been tried.

### §2.1 and the question a reader is entitled to ask

Why did a project whose whole thesis is tagging evidence with the layer it
depends on not already say that the room-frame question is Layer B? Because the
fixed base hid the distinction by making the two frames the same frame. That is
the kind of thing `sufficiency.md` exists to record, and it is the strongest
thing to come out of this work.

Nothing was reclassified when it moved there: no layer tag changed, no figure
moved, and `ProprioState` was not touched.

### §3's refusal, and the condition it was written against

`outer_envelope` refusing a `None` base velocity was written to stop §4 item 4
from arriving quietly: until the pose *and* the base velocity were on
`robot_config`, a mobile artifact could not be written at all rather than being
written with fixed-base numbers in it. Half of that condition was met by #166 and
the other half by #191, and what the refusal guards moved rather than went.

#166 put the **pose** on the row and not the velocity, and added a second refusal
at the *read* — `_recompute` refuses a config that states a pose — so the two
absences could not compound into a fixed-base region returned as a mobile one.
That was the half in front of it, and it never fired before, because nothing
wrote the pose. `base_vel` was not refused: it is body-frame, Layer A, and
`outer_envelope` reads it correctly.

#191 then made a mobile artifact writable, so *a mobile artifact cannot be
written at all* stopped holding and the guarantee it stood for is carried by the
two bullets §3 now lists instead.

### §4's survey, as written on 2026-08-31

On the day this document was written there was no model of a robot pose anywhere
in the tree: `affine_transform`, `base_pose`, `SE2`, `mobile` and `AMR` returned
nothing across `reg/`, `tests/` and `docs/`, and `reg.world.BASE_XY` was read in
two places and was documentation rather than a parameter.

`BASE_XY` is gone, and that count is why it could go. Two read sites and no
parameter is a symbol whose only job was to restate a mounting fact, and
restating a fact in a second place is how the two drift. `ORIGIN_FRAME` is the
statement now.

Item 7's check moved for two reasons at once. `World.__post_init__` used to
assert that the room contained `BASE_XY` as a point of zero radius. **The
subject** was wrong even for a bolted arm: a point test passes a robot whose
links sweep through a wall, which is the fixture fault the check exists to catch,
and it was only tolerable while the fixtures were hand-placed against a stated
1.20 m reach. **The place** was wrong for a base that drives: a driven base has a
path and a `World` never sees a trajectory, and a constructor answering the
question it can reach rather than the one that matters is a check that has
stopped checking.

Widening it refused none of the eleven arm fixtures, every artifact stayed
byte-identical, and no published figure moved.

### §4 item 4's schema bump, and what it cost

`SCHEMA_VERSION` went to 10 and the gate names what changed;
`reg.store.SCHEMA_VERSION` is where the current one is. Every existing
artifact holds the same rows it did, because every fixture here is bolted down
and writes `base_pose` NULL — but it is **not** byte-identical and **the
published figures moved**, by +0.20% to +0.29%. Two nullable columns cost one
SQLite record-header byte each on every `robot_config` row that exists, whether
or not anything is written into them, so a schema that can hold a base pose
cannot also leave the byte counts still. The measurement, the attribution and the
list of documents re-measured with `python -m reg.bench --resolution --seed 0`
are in [`lossiness.md`](lossiness.md) *Retained* #8; the issue asked for no
movement and that part of it could not be met.

`reg.graph.build` **refused a stream whose frames state a base pose** from
2026-09-04 until #191 replaced the refusal with the thing it stood in for. It
wrote `base_pose` NULL on every `robot_config` row it produced, so building one
of these would have turned a run whose base drove into an artifact saying no base
pose was recorded — same row count, every check green, and every envelope in it
readable as the region a robot at `meta[base_frame]` could reach.

### The claim change Tier 3 made

A base pose is the first dependency on something outside the robot that reaches
an edge naming **no `Entity`**, so `reg.store.open_edge` reads the pose off the
endpoint and refuses a Layer A tag on an edge resting on one. That closes the gap
§2.1 records and `sufficiency.md` §5.6 predicted:
`tests/test_graph.py::test_layer_b_is_exactly_the_entity_naming_edges` now
constructs that edge and requires the refusal, so the layer boundary is enforced
for the one case this whole track is about rather than for the four edge types
that existed before.

### The pins Tier 3 rewrote rather than deleted

With the base in the outer set, `horizon_bound` was `min(computed_bound,
outer_radius)` where the first term is a fixed-base disc and the second grows
with the vehicle — so for a mobile robot the minimum was pinned at a bound §1
says does not exist.
`tests/test_enforce.py::test_the_horizon_bound_is_still_floored_by_a_fixed_base_disc`
recorded that and was written to go red when `computed_bound` started refusing;
it did, and it is now
`test_the_horizon_bound_rests_on_the_outer_envelope_alone_for_a_driven_base`,
asserting the identity rather than the gap.

The two Tier 2 pins in front of the same change went the same way.
`test_the_demo_worlds_bound_is_the_workspace_disc_it_has_always_been` still
holds, narrowed to the fixed-base half it was always true of, and
`test_the_computed_bound_does_not_read_the_base_bounds` is replaced by
`test_the_computed_bound_refuses_a_robot_whose_base_can_drive`, parametrised over
all four fields. No fixture changed behaviour: every one states four zeros.

### What the enforcer entry used to say

Before #189 this document recorded "what Tier 3's refusal does **not** buy:
`Enforcer` refuses to construct for a driven base, because it names the workspace
disc in every `envelope_overclaim` reason it writes and there is no honest number
to put there." The first clause was true and the second was the wrong reason for
it. The disc is **not** the bound `Enforcer.offer` refuses declarations against —
that is `horizon_bound(state, limits, window, substep_dt)`, recomputed per offer.
It appeared in one place: the parenthetical an `envelope_overclaim` reason ends
with.

So the constructor stopped asking `computed_bound` for a disc the robot does not
have, `Enforcer.bound` became `float | None` with `None` meaning *no horizon-free
radius exists for this robot*, and the parenthetical was **rewritten** for the
mobile case rather than dropped — a mobile VETO that simply went quiet about the
disc would read like a fixed-base one whose disc went unmentioned, and an
operator cannot tell those apart.

#164's refusal is caught nowhere: `computed_bound` is not called for a driven
base at all, which
`tests/test_enforce.py::test_no_code_path_catches_the_computed_bound_refusal`
asserts against the source of every module in `reg/`. Every fixed-base reason
string stayed byte-identical and pinned as an equality, and no published figure
moved.

### The two re-measurements Tier 4 forced

`GEOMETRY_RETENTION`'s text lands in `meta` in every artifact, including the
eleven fixed-base ones, so their bytes are not identical — #166 is the precedent
for expecting movement. It was re-measured with `python -m reg.bench --resolution
--seed 0` and the report is byte-identical to the one before the change:
1,008,640 B / 2,503,680 B / 3,634,176 B, which at this fixture's 50 Hz control
rate was 60.54 / 150.27 / 218.12 MB/h — the figures published then, since
republished by issue #252.

One longer string in one `meta` row does not cross a page boundary, where #166's
two nullable columns cost a record-header byte on every one of 2,560
`robot_config` rows. The control-rate ladder
[`sensor-baseline.md`](sensor-baseline.md) publishes — all four rungs, including
the three CI does not pin — was re-measured too, with `python -m reg.bench
--control-rate-hz 50,100,250,1000 --seed 0`, and that report is byte-identical as
well.

### Where the precedents cited above live

`Limits.source` as a two-value tag with the simplification stated out loud is
issue #84, and §2.2 reuses it twice: once for pose provenance and once for the
set-valued pose. `Scenario.drives` rather than a pose at the origin is issue
#150. The base velocity on the stream is issue #176. The linear-in, linear-out
shape §4 item 4 refuses to put back is issue #29. The radial containment decision
§3 makes harder to defer is issue #82. The interpolate-then-integrate argument
§7.1 reuses one frame out is issue #96.
