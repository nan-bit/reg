"""Shared types — and the layer boundary the whole argument rests on.

THE STRUCTURAL PROPERTY THIS FILE EXISTS TO ENFORCE
---------------------------------------------------
`reg` makes a claim about which audit questions are answerable from certifiable
evidence. That claim is only worth anything if the certifiable layer *cannot* see
the uncertifiable one — not by convention, but structurally.

    Layer A  (certifiable)    proprioception, actuation limits, declarations,
                              verdicts, the hash chain. Sensors whose failure
                              modes can be characterised.

    Layer B  (uncertifiable)  where anything else in the world is. Ground truth
                              from the simulator here; a perception stack in a
                              real system.

So the envelope computation takes a `ProprioState`, which has no field naming any
entity, obstacle, or human. If it could reach the world, the sufficiency argument
in Claim 3 evaporates and what remains is a visualisation.

That enforcement is by *field name*, and the envelope's second input defeats it:
`Limits` names nothing outside the robot either, and its numbers can still be a
function of what a perceiver measured (ISO/TS 15066 speed-and-separation caps
`qd_max` by the measured separation distance). Names cannot catch a taint that
arrives in a value, so `Limits` carries `source: LimitSource` — required, no
default — and `reg.envelope.envelope_layer` turns it into the layer the
`HAS_ENVELOPE` edge is tagged with. Issue #84; docs/sufficiency.md §7.

Layer A was widened once, and once only: `ProprioState.base_vel` carries the
base's *body-frame* velocity, which a wheel encoder measures and which names
nothing outside the robot — the argument that already admits `qd`. The base's
room-frame *pose* did not come with it: it lives on `StateFrame` as a `BasePose`
and `proprio()` drops it. Issue #150; docs/sufficiency.md §5.7.

A provenance field is not always a layer decision, and `BasePose` is the case
where it is not. `PoseSource` sits beside `LimitSource` and looks like it, but a
room-frame pose is Layer B *structurally* — a statement about the robot's
relationship to a map, landmarks or a frame somebody defined — and no localizer
moves it. So that enum records what the pose inherits and over what horizon, and
there is deliberately no function turning it into a `Layer`. Issue #149;
docs/sufficiency.md §5.6.

The widening did not come free either, and `BaseVelocity.source` is what it
cost. A body-frame rate names nothing outside the robot, and **visual odometry
fills one by looking at the room** — the `Limits` hole again, in the type Layer A
was widened for. So this type carries `source: VelocitySource`, required and with
no inference; unlike `PoseSource` it really does fork a layer, and unlike
`LimitSource` nothing consumes it yet, which is a gap this file names rather than
one it hides. Issue #156; docs/sufficiency.md §5.9, docs/limitations.md §11.

This mirrors established practice rather than inventing it: reachability-based
trajectory design (ARMTD, ARMOUR) computes a manipulator's reachable set offline
and independent of obstacles, then intersects with the scene afterwards. See
docs/prior-art.md §4 — the split is not the contribution; tagging every piece of
evidence with the layer it depends on is.

DETERMINISM
-----------
Every structure here is frozen. An audit artifact that is not reproducible is not
an audit artifact, so nothing that ends up in the record may be mutated after it
is built.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

import numpy as np

# Layer tags. Every graph edge carries one; Claim 3 is a query over these.
Layer = Literal["A", "B"]


class LimitSource(Enum):
    """Where a `Limits` object's numbers came from (issue #84).

    THE HOLE THIS CLOSES
    --------------------
    `ProprioState` keeps the world out of Layer A by *field name*, and that is
    real enforcement. But the envelope has a second input, and this one was
    declared Layer A by fiat — "a property of the robot". Under ISO/TS 15066 and
    ISO 10218-2:2025 **speed-and-separation monitoring**, which docs/plan.md
    cites approvingly, the commanded speed bound is a function of the *measured
    separation distance*: `qd_max` is then perception-derived, and an envelope
    computed from it is Layer B wearing a Layer A tag. The taint arrives in a
    **value**, and nothing that inspects **names** can catch it.

    So the caller states it. There is no default and there is no inference: the
    only party that knows whether a speed cap came off a datasheet or out of a
    safety scanner is whoever assembled the numbers.

    `reg.envelope.envelope_layer` is the one place this maps to a layer, and
    `reg.graph.build` tags the `HAS_ENVELOPE` edge with what it returns.

    WHAT THIS BINARY SIMPLIFIES, SAID OUT LOUD
    ------------------------------------------
    Two values, matching the project's two layers. That is a simplification and
    docs/sufficiency.md §7 records it as one: an IEC 61496 safety scanner rated
    PLd is perception *with characterized failure modes* and still lands in
    `DERIVED`, while an encoder needs ISO 13849 cat-3 dual channel before it
    carries a safety claim and still lands in `PROPRIOCEPTIVE`. A tag plus an
    integrity attribute would model how assurance is actually argued; it was
    considered and rejected for scope (issue #84), because it rewrites what the
    project may claim rather than recording which case a given artifact is in.
    """

    #: A property of the robot: a datasheet limit, a joint stop, a link length.
    PROPRIOCEPTIVE = "proprioceptive"
    #: Computed from something perceived — an SSM speed cap is the case that
    #: matters. Whatever is derived from these bounds inherits the perceiver.
    DERIVED = "derived"


class PoseSource(Enum):
    """What a `BasePose` inherits, and over what horizon (issue #149).

    THIS ENUM DOES NOT SELECT A LAYER, AND THAT IS THE POINT
    -------------------------------------------------------
    `LimitSource` above is the obvious precedent and copying it whole would be
    wrong here. `LimitSource` *decides* a layer — `reg.envelope.envelope_layer`
    maps `PROPRIOCEPTIVE` to `A` and `DERIVED` to `B` — because a bound really
    can be a property of the robot or a function of something perceived, and
    only the caller knows which.

    A room-frame base pose has no such fork. **Both values below are Layer B**,
    structurally: a pose in the room is a statement about the robot's
    relationship to things *outside* the robot — a map, landmarks, a frame
    somebody defined — and that is exactly where this project draws the
    boundary. Not "no rated localizer exists yet", which is a weaker claim that
    someone could answer by building one: even set-theoretic localization, which
    returns a set *guaranteed* to contain the true pose, is guaranteed only
    under a map and bounded-error hypotheses, both exogenous, and a guarantee
    conditioned on a Layer B input is a Layer B guarantee. No localizer of any
    kind moves the base pose to Layer A. docs/sufficiency.md §5.6;
    docs/prior-art.md §25.

    **So there is no `pose_layer()` and there must not be one.** A function
    mapping these members to `Layer` could only be lying in one of the two
    cases, and the lie it would tell — a room-frame pose tagged `A` — is the
    mislabelling `Limits.source` exists to stop, arriving through the door that
    field opened. `tests/test_layer_boundary.py` asserts no such mapping exists
    anywhere in `reg/`, because the precedent makes writing one the obvious next
    move.

    WHAT THE VALUE DOES RECORD
    --------------------------
    The failure modes and the **validity horizon** the pose carries, which the
    binary layer tag cannot express (docs/mobile-base.md §2.2):

    * `DEAD_RECKONED` is derivable from proprioception alone, and is Layer A
      only *relative to a last known pose*. Its error grows with time and is
      unbounded under slip that wheel encoders cannot observe. That is "Layer A
      with a validity horizon", which this project's binary has no value for —
      so it is recorded here rather than resolved.
    * `LOCALIZED` inherits a map and whatever sensing matched against it. No
      drift horizon, a different failure set: a wrong association, a stale or
      wrong map, a symmetric corridor.

    Required, no default, no inference — the `LimitSource` discipline, for the
    same reason. A pose whose provenance nobody stated must not be
    indistinguishable from one somebody did.

    WHAT THIS BINARY SIMPLIFIES, SAID OUT LOUD
    ------------------------------------------
    Two values, and neither carries a magnitude. A set-theoretic localizer
    returns a pose *set*, which composes with the envelope by Minkowski sum and
    would preserve the over-approximation across the frame change that a point
    pose does not — that is the shape in which "how wrong can this be" could be
    carried. It is the same collision with issue #84's deliberate refusal of a
    graded integrity attribute, and it gets the same treatment: recorded here,
    not built (docs/mobile-base.md §2.2, docs/prior-art.md §25).
    """

    #: Integrated from proprioception — `∫(v, ω) dt` from a last known pose.
    #: Layer A relative to that pose; Layer B in the room, with a drift horizon.
    DEAD_RECKONED = "dead_reckoned"
    #: Map-based pose estimation. Layer B in the room for the same structural
    #: reason, with the map and the association as its failure modes.
    LOCALIZED = "localized"


class VelocitySource(Enum):
    """Where a `BaseVelocity`'s numbers came from (issue #156).

    THIS IS ISSUE #84's HOLE, REOPENED FOR A NEW TYPE
    -------------------------------------------------
    `LimitSource` above exists because a **value** can carry a perceiver in past
    a check that inspects **names**: `Limits` names nothing outside the robot,
    and under ISO/TS 15066 speed-and-separation monitoring `qd_max` is still a
    function of a measured separation distance. The same sentence, one type
    over. `BaseVelocity` names nothing outside the robot either — *0.4 m/s
    forward, 0.2 rad/s* is a statement about the machine — and **visual
    odometry** fills that structure by looking at the room.

    So the body-frame *quantity* is Layer A, on exactly the terms `qd` is, and a
    `BaseVelocity` **filled from a perceiver is not**. Those are not in tension:
    a layer is a claim about whose failure modes an answer inherits, and a VO
    estimate inherits texture, lighting, and a scene that was assumed static.
    Only the party that assembled the numbers knows which case a given artifact
    is in, so the caller states it — required, no default, no inference.
    docs/sufficiency.md §5.9.

    WHY THIS ONE FORKS A LAYER AND `PoseSource` DOES NOT
    ---------------------------------------------------
    `PoseSource` sits above and looks like the same shape, and it deliberately
    has no mapping to a `Layer` because **both** its values are Layer B: a
    room-frame pose is a statement about the robot's relationship to a map, and
    no localizer moves it. There is no such collapse here. A wheel encoder is
    proprioception and a camera is not, so this enum is `LimitSource`'s kind and
    not `PoseSource`'s, and a scan that treats the two alike is wrong about one
    of them.

    **Nothing in `reg/` maps a member of this enum to a `Layer` yet, and that is
    a gap rather than a decision.** `reg.envelope.envelope_layer` decides the
    `HAS_ENVELOPE` tag from `Limits.source` alone, so an outer envelope computed
    from a `DERIVED` base velocity — `reg.envelope.base_motion_bounds` reads
    `state.base_vel`, and since issue #163 that displacement is inside the bound
    every VETO for a mobile robot rests on — is still tagged from its bounds
    only. What this field buys today is that the artifact **records** which case
    it is in; what it does not yet buy is the tag following it.
    docs/limitations.md §11 is the entry, in the form that file's entries take.
    Do not close that gap by giving this enum a default or by inferring a
    member: an undecided provenance must never resolve to `PROPRIOCEPTIVE`,
    which is the whole content of issue #84.

    WHAT THIS BINARY SIMPLIFIES, SAID OUT LOUD
    ------------------------------------------
    The same two values, and the same simplification `LimitSource` records: a
    wheel encoder needs ISO 13849 cat-3 dual channel before it carries a safety
    claim and still lands in `PROPRIOCEPTIVE`, while a fused wheel-odometry /
    IMU / VO estimator — which is what a real base runs — is one number with
    three provenances and lands in `DERIVED` as a whole, because a fused value
    inherits the taint of its weakest input. A tag plus an integrity attribute
    would model that; it was considered and rejected for scope under issue #84
    and this type does not reopen it (docs/sufficiency.md §7).
    """

    #: Measured on the robot: wheel encoders, a steering resolver, a drive-shaft
    #: tachometer. The `qd` case, one body down.
    PROPRIOCEPTIVE = "proprioceptive"
    #: Estimated from something perceived — visual or visual-inertial odometry,
    #: a lidar scan match, an external tracker. Whatever is computed from this
    #: velocity inherits that perceiver.
    DERIVED = "derived"


@dataclass(frozen=True)
class Limits:
    """Kinematic and actuation bounds, and where they came from.

    **Not Layer A by fiat.** `source` says which layer the bounds belong to and
    it is required — see `LimitSource` for why a value can smuggle perception
    into a structure whose field names are all innocent.

    `qdd_max` is an acceleration bound standing in for a torque limit. This is
    deliberate — see docs/plan.md, Phase 1. There is no dynamics model here and
    there should not be one.

    **No field here has a default, and that is the point.** `link_radius` had
    one — `0.05` — until issue #115, on the unstated argument that it was only
    geometry. It is not: it is the radius `reg.enforce.computed_bound` VETOes a
    declaration against, the half-width `reg.envelope` dilates the centreline
    union by, and the bound that fixes the sampling step (`h_j * reach[j] <=
    link_radius`). Most call sites already stated it — the default covered the
    remainder, and a figure measured against a value a caller never chose is
    indistinguishable downstream from one it did. The value did not change when
    the default went; what changed is that the distinction is no longer possible.

    THE BASE'S OWN BOUNDS (issue #151)
    ----------------------------------
    Four more fields, with their units written down here rather than left to be
    inferred from a name:

    * `base_v_max` — **m/s**. The magnitude of the base's body-frame
      translational velocity, i.e. of `BaseVelocity`'s `(vx, vy)`.
    * `base_a_max` — **m/s^2**. The magnitude of its body-frame translational
      acceleration.
    * `base_omega_max` — **rad/s**. The magnitude of its yaw rate, i.e. of
      `BaseVelocity.omega`.
    * `base_alpha_max` — **rad/s^2**. The magnitude of its yaw acceleration.

    **The two acceleration bounds stand in for a force and a torque limit
    exactly as `qdd_max` stands in for a joint torque limit** (docs/plan.md,
    Phase 1). There is no mass, no inertia and no wheel model anywhere in this
    package, so `base_a_max` is not evidence of a dynamics model — it is the
    same deliberate stand-in one level up, said here rather than left for a
    reader to infer a model that does not exist.

    **They are magnitude bounds, not a geometry.** `base_v_max` caps
    `hypot(vx, vy)` and says nothing about which directions are attainable. A
    differential-drive base is nonholonomic and cannot move sideways at all, so
    the velocities it can actually command are a strict subset of the disc these
    numbers describe. Bounding the superset is the safe direction — an
    over-approximation of what the base can do — and it is loose; that looseness
    is docs/mobile-base.md §3's subject and Tier 3's problem, and it is a
    property of these fields rather than a defect in whatever consumes them.

    **A bolted-down arm states zeros; it does not omit them.** There is no
    arm-only `Limits`, because an arm-only `Limits` would be a default arriving
    by another route: the caller who never considered the base would produce the
    same object as the one who considered it and wrote down *this base does not
    move*. `reg.world.LIMITS` is the worked example, and
    `tests/test_layer_boundary.py` asserts it states them rather than leaving
    them out.

    `source` governs all four the way it governs `qd_max`. A base speed cap
    computed from a measured separation distance — the ISO/TS 15066 case — makes
    the whole object `DERIVED` and every envelope computed from it Layer B.
    """

    q_min: np.ndarray
    q_max: np.ndarray
    qd_max: np.ndarray
    qdd_max: np.ndarray
    link_lengths: np.ndarray
    #: Required: giving `source` a default would restore exactly the fiat this
    #: field exists to remove, and the caller who did not think about provenance
    #: would be indistinguishable from the one who did.
    source: LimitSource
    #: Required for the same reason (issue #115). The body's half-width, the
    #: sampling bound, and the term added to `sum(link_lengths)` in the disc a
    #: declaration is tested against — a caller who did not choose it would be
    #: indistinguishable from one who did, and the artifact would record the
    #: invented number as a stated one.
    link_radius: float
    #: Base translational speed bound, **m/s**: the largest `hypot(vx, vy)` the
    #: base may command in its own body frame. Required, no default, and zero
    #: for a bolted base — a plausible datasheet number is exactly what the rule
    #: above exists to keep out of an artifact unstated.
    base_v_max: float
    #: Base translational acceleration bound, **m/s^2**. Stands in for a force
    #: limit as `qdd_max` stands in for a torque limit (docs/plan.md, Phase 1).
    base_a_max: float
    #: Base yaw-rate bound, **rad/s**. A magnitude: it bounds `|omega|`.
    base_omega_max: float
    #: Base yaw-acceleration bound, **rad/s^2**. The rotational half of the same
    #: stand-in — a torque limit, not a model of one.
    base_alpha_max: float

    #: The four above, named once. Every loop over them — the validation below,
    #: the meta block in `reg.graph` — has to cover all four, and a list written
    #: out twice is a list that silently exempts whichever one somebody forgot.
    BASE_BOUND_FIELDS = ("base_v_max", "base_a_max", "base_omega_max", "base_alpha_max")

    def __post_init__(self) -> None:
        if not isinstance(self.source, LimitSource):
            raise TypeError(
                f"Limits.source must be a LimitSource, got {self.source!r}. It is "
                "the artifact's record of whether these bounds are a property of "
                "the robot or a function of something perceived, and the layer "
                "tag on every envelope computed from them follows it. A string "
                "or None here is not 'unspecified' — it is a provenance nobody "
                "stated arriving as one somebody did."
            )
        n = len(self.link_lengths)
        for name in ("q_min", "q_max", "qd_max", "qdd_max"):
            got = len(getattr(self, name))
            if got != n:
                raise ValueError(
                    f"{name} has {got} entries but there are {n} links. "
                    "Limits must be stated per joint; a mismatch here would be "
                    "silently broadcast by numpy into a bound nobody wrote."
                )
        for name in self.BASE_BOUND_FIELDS:
            raw = getattr(self, name)
            if isinstance(raw, (str, bytes)):
                # `float("0.5")` succeeds, which is the trap: a string carries
                # no unit and nothing downstream that formats it into the
                # artifact would survive it. Refused here, where the field is
                # named, rather than in whatever writes the meta block.
                raise TypeError(
                    f"Limits.{name} must be a number, got {raw!r}. A string that "
                    "happens to parse as one is not a bound somebody stated in "
                    "these units."
                )
            try:
                value = float(raw)
            except (TypeError, ValueError) as exc:
                raise TypeError(
                    f"Limits.{name} must be a number, got {raw!r}. It bounds "
                    "what the base may command, and something that is not a "
                    "number is not a bound."
                ) from exc
            if not math.isfinite(value):
                raise ValueError(
                    f"Limits.{name} is {raw!r}, which is not finite. An infinite "
                    "or NaN bound is not a permissive bound: it is an unbounded "
                    "workspace written as though somebody had measured one, and "
                    "an unbounded workspace is a could-not-evaluate here "
                    "(docs/mobile-base.md §1)."
                )
            if value < 0.0:
                raise ValueError(
                    f"Limits.{name} must be a non-negative magnitude bound, got "
                    f"{raw!r}. A negative bound has no value that satisfies it — "
                    "the argument qd_max is refused under in "
                    "`reg.kinematics.clamp_to_limits`. A base that does not move "
                    "states 0.0."
                )


@dataclass(frozen=True)
class BaseVelocity:
    """The base's velocity **in its own body frame**. Layer A (issue #150).

    `BasePose` below is this type's sibling and they sit on opposite sides of
    the boundary, which is the whole content of issue #150. The difference is
    not how well either can be sensed — it is what each one is a statement
    *about*:

    * A body-frame rate — *this base is moving 0.4 m/s forward and turning at
      0.2 rad/s* — is a statement about the machine. It mentions no map, no
      landmark and no frame anybody defined, and it is what a wheel encoder
      measures. That is the same argument that admits `qd`, and it is why this
      type may be reached from Layer A.
    * A room-frame pose is a statement about the robot's relationship to
      something outside the robot, and no localizer moves it (`BasePose`,
      `PoseSource`, docs/sufficiency.md §5.6).

    Integrating one into the other is what crosses the boundary: `∫(vx, vy, ω)
    dt` is a pose only *relative to a last known pose*, and its error grows
    without bound under slip an encoder cannot observe. That is the "Layer A
    with a validity horizon" case docs/sufficiency.md §7 records and does not
    resolve, and nothing here integrates anything.

    **The units are kept in separate fields on purpose.** `vx`/`vy` are m/s and
    `omega` is rad/s; a single three-vector would put two units in one array,
    where a norm, or a `clip` against one bound, is a mistake nothing would
    catch.

    **`source` is required, and issue #156 is why it stopped being absent.**
    This type shipped without a provenance field on the argument that it is
    admitted on exactly the terms `qd` is admitted on and that `qd` carries none
    either. The argument does not hold, because the two are not symmetric:
    **nothing plausibly measures a joint velocity by looking at the room, and
    something plausibly measures a base velocity that way.** Visual odometry is
    ordinary on a real vehicle, a `BaseVelocity` filled from it is Layer A
    wearing a tag it did not earn, and that is `Limits.source`'s hole exactly —
    a taint arriving in a **value**, where a field-name check cannot reach it.
    So the caller states it: no default, no inference, `VelocitySource` for the
    argument. docs/sufficiency.md §5.9.

    **`qd` stays untagged, and the reason is written down rather than assumed.**
    It is a *deployment* argument and not a structural one — joint state comes
    off the actuator's own encoders on every arm this project would run on —
    which is the weaker kind of argument by §5.6's own standard, and it is
    recorded as a residual in docs/limitations.md §11 rather than treated as
    settled. What makes it tolerable is that no ordinary system fills `qd` from
    a perceiver, while an ordinary system fills this field from one.

    No field has a default, matching `Limits` since issue #115 and `BasePose`
    since issue #149.
    """

    #: Body-frame linear velocity, m/s. `vx` is along the base's own heading.
    vx: float
    vy: float
    #: Yaw rate, rad/s. Counter-clockwise positive, as everywhere else here.
    omega: float
    #: Required, and unlike `BasePose.source` it *does* decide a layer: an
    #: encoder-measured rate is proprioception and a visually-estimated one is
    #: not. Nothing maps it to a `Layer` yet — see `VelocitySource` and
    #: docs/limitations.md §11 — but a rate whose provenance nobody stated must
    #: not be indistinguishable from one somebody did, which is the part that
    #: cannot wait for the mapping.
    source: VelocitySource

    def __post_init__(self) -> None:
        if not isinstance(self.source, VelocitySource):
            raise TypeError(
                f"BaseVelocity.source must be a VelocitySource, got "
                f"{self.source!r}. It is the artifact's record of whether this "
                "rate was measured on the robot or estimated from something "
                "perceived — wheel encoders against visual odometry. A string "
                "or None here is not 'unspecified': it is a provenance nobody "
                "stated arriving as one somebody did, and the outer bound every "
                "VETO for a mobile robot rests on is computed from this value "
                "(reg.envelope.base_motion_bounds)."
            )


@dataclass(frozen=True)
class ProprioState:
    """Everything the certifiable layer is allowed to know.

    DO NOT ADD A FIELD NAMING ANYTHING OUTSIDE THE ROBOT. Not the human, not an
    obstacle, not a goal pose derived from either. The absence of those fields is
    the enforcement mechanism for the Layer A boundary, and it is the only
    enforcement mechanism — there is no runtime check that can replace it.

    If a computation genuinely needs the world, it belongs in Layer B and its
    results must be tagged accordingly.

    WHAT `base_vel` WIDENED, AND WHAT IT DID NOT (issue #150)
    --------------------------------------------------------
    This type held `{t, q, qd}` from the beginning, and
    `tests/test_layer_boundary.py::test_propriostate_fields_are_exactly_the_allowed_set`
    pins the set so widening it cannot happen quietly. It has been widened once,
    deliberately: `base_vel`, the base's *body-frame* velocity, which a wheel
    encoder measures and which names nothing outside the robot.
    docs/sufficiency.md §5.7 is the record of that decision, and the allowlist
    moved in the same commit because the test requires it.

    **The pose did not come with it.** `x`, `y`, `theta` in the room are Layer B
    structurally (§5.6); they live on `StateFrame` as a `BasePose`, and
    `proprio()` does not pass them through. None of those three names is in the
    word check's `WORLD_WORDS` and none ever will be — the allowlist is the only
    thing standing there, which is why moving it is a decision about what this
    project can claim and not a refactor.
    """

    t: float
    q: np.ndarray
    qd: np.ndarray
    #: Required, no default. `None` means **this state records no base
    #: velocity** — a could-not-evaluate, and never zero. Nothing in `reg/`
    #: produces one yet: the raw stream schema has no columns for it
    #: (`reg.stream`), and `robot_config` stores only `q` and `qd`, so
    #: `reg.graph` reconstructs states with `None` rather than reading the
    #: absence as a base that was standing still. A bolted base's velocity is
    #: zero, but an artifact that did not record it must not be
    #: indistinguishable from one that did.
    base_vel: BaseVelocity | None

    def __post_init__(self) -> None:
        if self.base_vel is not None and not isinstance(self.base_vel, BaseVelocity):
            raise TypeError(
                f"ProprioState.base_vel must be a BaseVelocity or None, got "
                f"{self.base_vel!r}. `None` is the one way to say 'not "
                "recorded'; a tuple or a bare array is a body-frame rate whose "
                "units and ordering nothing checks, and this field is on the "
                "Layer A side of the boundary."
            )


@dataclass(frozen=True)
class BasePose:
    """Where the robot's base sits in the room. **Layer B** (issue #149).

    Layer B **structurally**, not for want of a better estimator. `(x, y,
    theta)` here are room coordinates: a statement about the robot's
    relationship to a frame somebody defined, a map, or landmarks — things
    outside the robot — and that is where this project draws the boundary. The
    sensing-status argument (*nothing safety-rated produces this number*) is the
    weaker one, because a rated localizer would answer it; the structural one
    does not move, and it is why no localizer of any kind — including a
    set-membership estimator returning a set guaranteed to contain the true
    pose — puts this type in Layer A. docs/sufficiency.md §5.6.

    What that costs is stated there and is worth repeating where the type lives:
    for a fixed arm *could the robot have reached (x, y) at t?* is Layer A,
    because base-at-the-origin is a mounting fact. Allow the base to drive and
    the identical question in room coordinates becomes a **conjunction** with
    *the base was where the artifact says it was*, for which this project
    supplies no evidence — so it is Layer B, and the Layer A survivor is the
    narrower body-frame question. Anything computed by transforming a body-frame
    region by one of these inherits that.

    **No field has a default, matching `Limits` since issue #115.** `source` in
    particular: see `PoseSource`, which records what the pose inherits and over
    what horizon and deliberately does *not* select a layer.

    It has a home since issue #150 — `StateFrame.base_pose`, on the Layer B side
    of the frame, where `proprio()` drops it — and nothing in `reg/` constructs
    one yet: the envelope is computed for a base bolted to the origin,
    `reg.enforce.computed_bound` is finite because of it, and the fixed-arm
    fixtures record `None`. `tests/test_layer_boundary.py` is what keeps the
    contract alive with no producer behind it, so the type cannot drift into
    something Layer A before anything fills it in. docs/mobile-base.md §7,
    Tier 2.
    """

    x: float
    y: float
    theta: float
    #: Required, and it selects no layer. Both `PoseSource` values are Layer B;
    #: this records the failure modes and validity horizon inherited, so that a
    #: dead-reckoned pose and a localized one are not the same object in the
    #: record.
    source: PoseSource

    def __post_init__(self) -> None:
        if not isinstance(self.source, PoseSource):
            raise TypeError(
                f"BasePose.source must be a PoseSource, got {self.source!r}. It "
                "is the artifact's record of what the pose inherits and over "
                "what horizon — integration from a last known pose, or a map. A "
                "string or None here is not 'unspecified': it is a provenance "
                "nobody stated arriving as one somebody did. Note that it does "
                "not decide a layer; the pose is Layer B either way."
            )


@dataclass(frozen=True)
class Obstacle:
    """A static entity. Layer B — position is ground truth from the sim."""

    entity_id: str
    kind: str
    cx: float
    cy: float
    radius: float


@dataclass(frozen=True)
class StateFrame:
    """One tick of simulator ground truth.

    Mixed-layer by construction: this is the *raw stream*, the thing the evidence
    graph is compressed from. Nothing in Layer A consumes it directly — the
    envelope takes `proprio()` and never sees the rest.

    THE BASE SITS ON BOTH SIDES OF THE LINE, AND `proprio()` IS WHERE IT SPLITS
    ---------------------------------------------------------------------------
    A moving base contributes two things and they are not the same kind of
    thing (issue #150; docs/sufficiency.md §5.6, §5.7):

    * `base_vel` is body-frame and **Layer A**. `proprio()` passes it through.
    * `base_pose` is room-frame and **Layer B**. `proprio()` drops it, exactly
      as it drops `human_pos`, and
      `tests/test_layer_boundary.py::test_proprio_drops_the_base_pose` fails if
      that stops being true. A pose that survived the narrowing would make every
      envelope computed downstream a room-frame region wearing a Layer A tag.
    """

    t: float
    q: np.ndarray
    qd: np.ndarray
    human_pos: np.ndarray  # Layer B
    human_vel: np.ndarray  # Layer B
    #: Layer A, and narrowed through. Required, no default; `None` is "this
    #: frame records no base velocity" and never "the base was still".
    base_vel: BaseVelocity | None
    #: Layer B, and dropped by `proprio()`. Required, no default; `None` is
    #: "this frame records no base pose". The fixed-arm fixtures in
    #: `reg.scenarios` record `None` rather than `BasePose(0, 0, 0, ...)`,
    #: because for a bolted base *the base is at the origin* is a mounting fact
    #: and not an estimate, and `PoseSource` has no member for a mounting fact —
    #: writing one of the two it does have would put a provenance nobody has on
    #: a number nobody measured.
    base_pose: BasePose | None
    objects: tuple[Obstacle, ...] = field(default=())  # Layer B

    def __post_init__(self) -> None:
        if self.base_vel is not None and not isinstance(self.base_vel, BaseVelocity):
            raise TypeError(
                f"StateFrame.base_vel must be a BaseVelocity or None, got "
                f"{self.base_vel!r}. This field is narrowed into Layer A by "
                "`proprio()`, so what arrives here is what the envelope would "
                "eventually be computed from."
            )
        if self.base_pose is not None and not isinstance(self.base_pose, BasePose):
            raise TypeError(
                f"StateFrame.base_pose must be a BasePose or None, got "
                f"{self.base_pose!r}. A bare `(x, y, theta)` tuple carries no "
                "`PoseSource`, and a room-frame pose whose provenance nobody "
                "stated is the one thing `BasePose` exists to make impossible."
            )

    def proprio(self) -> ProprioState:
        """Narrow to Layer A. The only supported way to feed the envelope.

        What is dropped is the point: `human_pos`, `human_vel`, `objects` — and
        `base_pose`, which is room-frame and therefore Layer B for the same
        structural reason (docs/sufficiency.md §5.6). `base_vel` is body-frame
        and comes through.
        """
        return ProprioState(t=self.t, q=self.q, qd=self.qd, base_vel=self.base_vel)
