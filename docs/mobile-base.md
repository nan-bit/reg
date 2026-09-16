# The mobile base — what moving the robot does to the argument

**Status:** a design document whose track is built · written 2026-08-31 ·
**every tier in §7 has landed**, so this repository has runs in which a robot
drives and artifacts built from them; none of them is priced, so `SCENARIOS` is
still the eleven bolted arms and Claim 1 is still a fixed-arm claim · §7.3 is the
authority on what the track supports and what it does not · normative for the
mobile track only; where this document touches what the project may claim,
[`sufficiency.md`](sufficiency.md) and [`limitations.md`](limitations.md) are the
normative statement · keep current

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
alone for that robot — so every VETO a mobile robot is given rests on that
function's soundness argument, which makes
`tests/test_envelope.py::test_no_bang_bang_trajectory_escapes_the_outer_envelope`
load-bearing rather than merely good. The normative statements are
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

For a fixed arm, *the base is at the origin* is a mounting fact rather than a
measurement. For a mobile robot, where the base *is* comes from localization —
and the reason that is Layer B is structural rather than a fact about what
today's sensing is rated for. A room-frame pose is a statement about the robot's
relationship to things *outside* the robot: a map, landmarks, a frame somebody
defined.

**No localizer of any kind moves the base pose to Layer A.** State it in that
form, because the sensing-status form invites someone to go and build the
localizer. [`sufficiency.md`](sufficiency.md) §5.6 is the normative copy of the
split below, and where the two files differ it is right.

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
the same reason it is arrived at here ([`prior-art.md`](prior-art.md) §22).

But *protective field* is a term of art carrying a conformance meaning — a rated
device, a stated performance level, a validation procedure, an assessment
somebody signed — and `reg`'s envelope is a `shapely` polygon computed by unrated
Python from a simulator. Say the body-frame set **is what a protective field is**;
do not say it is one — name the ladder and claim no rung, which is the refusal
[`prior-art.md`](prior-art.md) §12 records against IEEE 7001's investigator
levels.

### 2.1 What this costs, stated as a loss

This **shrinks the set of certifiable questions**, and saying so plainly is more
valuable than any of the geometry below.

- Fixed arm — *could the robot have reached (x, y) at t?* is **Layer A**.
- Mobile robot — the same question is **Layer B**. Its Layer A survivor is
  *could the robot have reached a point 1.2 m ahead-left of its own base at t?*

[`sufficiency.md`](sufficiency.md) is where that is recorded and that copy is the
normative one: §5.6 carries the three-row split and this subsection's loss, §5.1
states its own verdict as conditional on a fixed base, and §2 carries the
asymmetry a room-frame pose reaches into — a Layer A attestation edge that
depends on something outside the robot while naming no `Entity`.

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
beside it: `reg.envelope.base_motion_bounds` returns a translation bound and a
yaw bound, the yaw folds into the first joint's angular interval exactly, and the
translation is one `buffer` on the arm's own body-frame set. That is deliberately
loose and it is published as loose;
[`limitations.md`](limitations.md) §10 is the normative statement of the
looseness and of what the representation costs, and where this section and §10
differ, **§10 is right**. `MAX_OUTER_GRID_CONFIGS` stays where it stands for the
base, which is the test of whether the construction is the right one, and
`tests/test_envelope.py::test_the_grid_guard_is_not_raised_for_the_base` holds it.

**`outer_envelope` refuses a state whose `base_vel` is `None` when the base can
move.** *Not recorded* is a could-not-evaluate, and reading it as a base standing
still would produce an outer bound that is too small — the one direction it may
not be wrong in. `reg.graph.build` reads `base_vel` off the *stream*, so a driven
run whose stream records none is refused at build time, with fixed-base numbers
never reaching the file.

**This makes the open decision about radial containment harder to defer.** The
overclaim check is radial. For a nonholonomic base a radial bound is very weak —
a robot that cannot turn is nowhere near the rim of its own disc — so radial-only
containment, already incomplete for the arm
([`limitations.md`](limitations.md) §2 and §3), is close to useless for a base.

## 4. Blast radius

[`reg.kinematics.ORIGIN_FRAME`](../reg/kinematics.py) is this repository's single
statement of the mounting fact, and `grep ORIGIN_FRAME` is the list of places
that assume a base which does not move. Every item is built; each names the test
that holds it.

1. `reg/kinematics.py` — the explicit leading `0.0` in the cumulative sums **is**
   the base, so `forward_kinematics(q, limits, base)` takes the frame, required
   and with no default.
   `tests/test_kinematics.py::test_the_base_frame_is_required_with_no_default`.
2. `reg/envelope.py` — the disc intersected into the outer bound is centred on
   the frame the bound is computed at rather than on the origin, which is
   silently unsound if missed (§1).
   `tests/test_envelope.py::test_a_base_a_millimetre_away_moves_the_outer_set_by_exactly_that_much`.
3. `reg/enforce.py`'s `_furthest_vertex` and `reg/envelope.py`'s `outer_radius` —
   both measure from a `BaseFrame`, required and with no default, and both are on
   the VETO path, which is why neither may invent one.
   `tests/test_enforce.py::test_the_excess_is_measured_from_the_base_it_is_given`
   and `tests/test_envelope.py::test_the_radius_is_measured_from_the_base_it_is_given`.
4. `reg/store.py` — a polygon recomputed from a `robot_config` row would come
   back at the origin for a robot that was elsewhere, and a retained
   `outer_radius` is a radius **about a centre**, so the row carries `base_pose`
   and `base_pose_source` under a `SCHEMA_VERSION` bump, `envelope_at` refuses a
   posed configuration rather than recomputing it, `GEOMETRY_RETENTION` keeps the
   room-frame polygon on every posed frame — nothing being left to recompute it
   from, and a mobile artifact that parses and answers nothing being what the
   retention prevents — and the layer tag follows the pose.
   The decisions that travel with that are
   [`sufficiency.md`](sufficiency.md) §5.8's, which is normative where it and
   this document differ.
   `tests/test_graph.py::test_a_posed_configuration_states_its_own_frame`.
5. `reg/declare.py`, `declared_region` — a declaration spanning base motion can
   be legitimately disconnected, so the function takes the frame each
   configuration is measured from and refuses a `MultiPolygon` only for a base
   that did not move, where a disconnected union is still a broken grid.
   `tests/test_declare.py::test_a_disconnected_region_is_refused_when_the_base_did_not_move`.
6. `reg/declare.py`, `_classify` — `reach` versus `retract` is the end effector's
   distance from **its own base**, and driving with a frozen arm is a `traverse`;
   read off the distance to the origin instead, a robot driving forward with a
   frozen arm would classify as a `reach`.
   `tests/test_declare.py::test_the_arm_is_classified_by_its_own_extension_while_the_base_drives`.
7. `reg/world.py` — the room-contains-origin check has to become a check that the
   base's whole *path* stays in the room, which a constructor that never sees a
   trajectory cannot perform, so it is `World.room_excursion` reported by
   `Scenario` (§7.1).
   `tests/test_scenarios.py::test_room_excursion_names_which_part_of_the_robot_left_and_by_how_much`.
8. `reg/bench.py` — a prefix match over `t`, `q_*` and `qd_*` treats a base
   column as Layer B **silently**, so `proprioceptive_columns` refuses a column
   carrying no rule in `COLUMN_RULES`, by name.
   `tests/test_bench.py::test_a_header_with_an_unknown_column_is_refused`.
9. `reg/graph.py` — the distance error budget is exactly saturated, so the pose
   is written at the raw stream's own precision with no quantum of its own rather
   than becoming a third error source in it
   ([`lossiness.md`](lossiness.md) *Discarded* #9).
   `tests/test_graph.py::test_the_pose_reads_back_the_digits_it_was_given`.
10. `reg/scenarios.py` — every fixed-base fixture's waypoints are hand-tuned
    against a distance from a base at the origin, which is why the mobile
    fixtures are a second catalogue rather than a re-tuning of the first (§7.2).
    `tests/test_scenarios.py::test_every_registered_fixture_is_fixed_base_and_records_no_base`.

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

The five bodies of work behind this design are the **fifth pass, 2026-09-01** in
[`prior-art.md`](prior-art.md), §21–§25: Marvel & Bostelman on the unbounded work
volume (§21), ISO 3691-4 and ANSI/A3 R15.08 on the speed-dependent protective
field in the vehicle frame (§22), RTD and REFINE on the forward reachable set and
the fail-safe manoeuvre (§23), CORA on zonotopes and conservative linearization
(§24), and set-theoretic localization (§25). Each entry states what it was read
from — for §22, secondary sources and vendor summaries, because both standards
are paywalled — and the pass is right where this document and it differ.

## 7. Build order

Small, independent, and argument before code — a bad attempt should cost a closed
PR. Every tier is built; `## Why` dates each one.

| Tier | What it is |
|---|---|
| **0** | The fixed base as a limitations entry; `proprioceptive_columns` refusing an unclassifiable column (§4 item 8) |
| **1** | The argument: the fifth prior-art pass (§6), then [`sufficiency.md`](sufficiency.md) carrying §2.1's shrink of the certifiable question set |
| **2** | Types and the boundary: base velocity on `ProprioState`; a Layer B pose type; base actuation bounds on `Limits` under the existing no-default rule; pose provenance beside `LimitSource`; an explicit base frame in `forward_kinematics` |
| **3** | The envelope and the bound: the body-frame outer envelope with the base states (§3); `computed_bound` refusing and `horizon_bound` on the outer envelope alone (§1); the two `declare.py` seams (§4 items 5 and 6); the pose on `robot_config` with the schema bump (§4 item 4); an `Enforcer` that constructs for a driven base and adjudicates one |
| **4** | Fixtures: mobile scenarios **beside** the eleven arm fixtures, *beside* being literal — a second catalogue, not an addition to the first |

Tier 3's normative statements live elsewhere and this document defers to all of
them: [`limitations.md`](limitations.md) §10 for the outer envelope's looseness,
§3 and §9 plus [`../CLAUDE.md`](../CLAUDE.md) rule 3 for the bound,
[`sufficiency.md`](sufficiency.md) §5.8 for the schema work, and
[`lossiness.md`](lossiness.md) for the recomputation clause.

### 7.1 What a mobile fixture states

A scenario drives by carrying `base_waypoints`, knots of `(x, y, theta)`
interpolated as the joint ones are and integrated under the four base bounds
exactly as the joints are integrated under `qdd_max`. Beside the trajectory it
states three things it may not omit — a [`PoseSource`](../reg/types.py) for the
poses it writes, a `VelocitySource` for the body-frame rates, and a
`(metres, radians)` jitter pair — because the only party that knows whether a
pose was dead-reckoned or localized is whoever produced it.

`Scenario` refuses a provenance with no trajectory, and a scenario with no
trajectory is a **fixed-base scenario**, said by `Scenario.drives` rather than by
a pose at the origin — a mounting fact no `PoseSource` describes. The room holds
the whole robot for the whole run, checked twice: at construction against the
scripted knots inflated by the jitter, and per frame against the pose that frame
records, because what leaves the room between two waypoints is the trajectory the
base **executes**, not its reference.

### 7.2 The four mobile fixtures

`reg.scenarios.MOBILE_SCENARIOS` holds `mobile_transit`, `mobile_frozen_arm`,
`mobile_overclaim` and `mobile_derived_velocity` — the runs in this repository in
which anything has moved a robot. Each exists to make one claim of this track
exercisable rather than to cover a motion, and `python -m reg.sim --list` prints
what each one is:

- **`mobile_transit`** — the room-frame answer is Layer B, and the pose is in the
  artifact (§2, [`sufficiency.md`](sufficiency.md) §5.6).
- **`mobile_frozen_arm`** — driving is not reaching (§4 item 6).
- **`mobile_overclaim`** — the bound rests on the outer envelope alone (§1), and
  it is this tier's **fault** in the taxonomy sense. A mobile fixture set in
  which nothing ever went wrong would exercise the happy path of a mechanism
  whose entire purpose is the unhappy one.
- **`mobile_derived_velocity`** — a base velocity out of a perceiver, and a layer
  tag that follows it ([`limitations.md`](limitations.md) §11). Since #252
  `reg.envelope.envelope_layer` is the weakest of its inputs, so it answers `B`
  for this robot on the bounds alone; both this run and `mobile_transit` tag
  every `HAS_ENVELOPE` edge `B` because the base drove, and what separates them
  is the basis under the tag — this run's `edge_layer_basis` rows say
  `base_vel_source=derived → B` where `mobile_transit`'s say
  `proprioceptive → A`.

**They are a second catalogue, not an addition to the first, and that is the half
every published figure depends on.** `SCENARIOS` is still exactly the eleven.
`reg.scenarios.scenario()` resolves both, because a stream's provenance block
records a *name* and a name nothing can resolve is a run whose world cannot be
recovered from the file — but nothing that **iterates** `SCENARIOS` sees a mobile
fixture, so `reg.bench --all` prices the eleven it always priced and
`reg.bench --scenario mobile_transit` is refused by name.

### 7.3 What the track supports, and what it does not

A robot that drives can be simulated, streamed, built, adjudicated and queried
end to end, with no could-not-evaluate among the standard queries, and a VETO in
such a run rests on `outer_envelope` alone. What it does not support, and the
first one is a gap this track surfaced rather than a decision it took:

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
  which is the honest label for a simulator that localizes nothing, and the
  jitter pair is fixture noise rather than a drift process, so nothing here
  supports a claim about how far a dead-reckoned pose has drifted by the end of a
  run.
- **No mobile figure is published.** None of the four is benchmarked, and the
  size of a mobile artifact is not comparable to the fixed-arm curve: a driving
  run writes the two optional base blocks, so the gzipped baseline every ratio is
  divided by is a different file.
- **The bound is still radially incomplete** ([`limitations.md`](limitations.md)
  §2 and §3), and a mobile run does not change that.

## See also

- [`sufficiency.md`](sufficiency.md) — §5.6 and §5.8, normative over what §2,
  §2.1 and §4 item 4 may claim; §5.1, the question this reclassifies; §2, the
  asymmetry a room-frame pose reaches into.
- [`limitations.md`](limitations.md) — §9 and §10, normative over the bound and
  over the base's contribution to the outer set; §2 and §3, the radial overclaim
  check §3 above makes harder to leave alone; §11, the gap
  `mobile_derived_velocity` makes observable.
- [`plan.md`](plan.md) — the non-goals table §5 defers to, and Phase 2's envelope.
- [`retention.md`](retention.md) — the figures §5 declines to disturb.
- [`prior-art.md`](prior-art.md) — §21–§25, where §6's entries live properly.

## Why

Nothing below is normative. It is the provenance of the sections above: which
issue each part of the track arrived on, and where the precedents it reuses were
set.

### When each part of the track landed

| Section | What landed | Issue | Dated |
|---|---|---|---|
| §7 Tier 0 | The fixed base as a `limitations.md` entry, §9 | #136 | 2026-09-01 |
| §6 | The fifth prior-art pass, `prior-art.md` §21–§25 | #138 | 2026-09-01 |
| §2, §2.1, §2.2 | The argument carried into `sufficiency.md` §2, §5.1, §5.6 and §7 | #139 | 2026-09-01 |
| §7 Tier 2 | A Layer B pose type, with a provenance that selects no layer | #149 | 2026-09-01 |
| §7 Tier 2, §2 | `base_vel` on `ProprioState` and not a pose; `Scenario.drives` rather than a pose at the origin | #150 | 2026-09-02 |
| §7 Tier 2 | Base actuation bounds on `Limits`, under the no-default rule | #151 | 2026-09-02 |
| §4 item 1 | `forward_kinematics` takes an explicit base frame | #152 | 2026-09-02 |
| §3 | `base_motion_bounds` and the base in the outer set; looseness into `limitations.md` §10 | #163 | 2026-09-02 |
| §1 | `computed_bound` refuses a nonzero base bound; `horizon_bound` on `outer_envelope` alone | #164 | 2026-09-02 |
| §4 items 5 and 6 | The two `declare.py` defects | #165 | 2026-09-02 |
| §4 item 4 | The pose on `robot_config`, `SCHEMA_VERSION` 10, `sufficiency.md` §5.8 and `lossiness.md` | #166 | 2026-09-02 |
| §4 item 3 | The outer bound measured from a `BaseFrame` rather than from the origin | #162 | 2026-09-02 |
| §7.1 | The raw stream carries a base, without moving the priced fixture | #176 | 2026-09-03 |
| §7 Tier 2, §2.2 | `VelocitySource` required on `BaseVelocity` — the value a perceiver can fill | #156 | 2026-09-03 |
| §4 item 7, §7.1 | `BASE_XY` removed; the room check moved to `Scenario` | #184 | 2026-09-04 |
| §7.1 | `Scenario.base_waypoints`, `PoseSource`, `VelocitySource`, the jitter pair | #177 | 2026-09-04 |
| §7 Tier 3 | `Enforcer` constructs for and adjudicates a driven base | #189 | 2026-09-04 |
| §7.1, §4 item 4 | The pose written to `robot_config`; `GEOMETRY_RETENTION` on posed frames | #191 | 2026-09-05 |
| §7.2 | The first three mobile fixtures | #178 | 2026-09-05 |
| §7.2 | `mobile_derived_velocity`, the fixture §11's gap is observable in | #229 | 2026-09-07 |
| §1 | The passivation clause: the record reaches a table, an edge and a query | #247 | 2026-09-07 |
| §7.2 | `envelope_layer` became the weakest of its inputs, and `edge_layer_basis` records which input the tag followed | #252 | 2026-09-08 |

**Where the precedents these sections reuse were set.** `Limits.source` as a
two-value tag with the simplification stated out loud is issue #84, and §2.2
reuses it twice: once for pose provenance and once for the set-valued pose. The
linear-in, linear-out shape §4 item 4 refuses to put back is issue #29. The
radial containment decision §3 makes harder to defer is issue #82. The
interpolate-then-integrate argument §7.1 reuses one frame out is issue #96.
