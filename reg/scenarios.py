"""The eleven named scenario fixtures, three mobile ones and one generated long
run. **Layer B** — this is simulator ground truth.

These are the fixtures everything downstream is measured against, so they come
first (docs/plan.md, Phase 1). They are hand-authored and small on purpose:
randomised scenarios would make the compression numbers in Claim 1
unfalsifiable — you cannot argue about a ratio nobody can regenerate.

The catalogue is in two halves. The **six situations** — approach, near miss,
contact, bystander, sustained overlap, declared violation — are what the
compression and query claims are measured against. The **five fault fixtures**
after them (issue #46) each produce exactly one of the semantic faults in
`reg.enforce.FAULTS` when the real enforcer is run over their real declarations;
they exist because an incident report can only narrate what a run produced, and
five of the six semantic faults had never occurred in one. Their geometry is
deliberately dull: the human is parked in a corner and the arm does something
unremarkable, because what is wrong with those runs is what the *policy* said.

The seventh, `long_run(n_frames)`, is generated rather than hand-authored,
because the question it exists for is a question about *length* (issue #30:
"does the compression ratio improve with run length?"). It is still not
randomised: the same frame count produces the same waypoints, and its shape is
fixed by the module constants below rather than drawn. It is not in `SCENARIOS`
— there is no single frame count that would be the right one to register — but
`scenario()` resolves its generated names, so a stream that says
`scenario=long_run_3000` in its provenance block can still be rebuilt.

The **three mobile fixtures** (issue #178, docs/mobile-base.md §7 Tier 4) are
the first runs here in which the robot drives, and each one exists to make one
claim of that track exercisable: `mobile_transit` that the room-frame answer is
Layer B and the base pose reaches the artifact, `mobile_frozen_arm` that driving
is not reaching, and `mobile_overclaim` that for a robot with no workspace disc
a VETO rests on the outer reachable set and on nothing else. They are in
`MOBILE_SCENARIOS` rather than in `SCENARIOS`, and the block comment above
`MOBILE_LIMITS` is where that split is argued — in one line, **Claim 1 stays a
fixed-arm claim** and a mobile run is not priced beside the eleven.

What a scenario is: a fixed set of joint waypoints and a fixed human path,
linearly interpolated at a fixed timestep. **No planner, no controller, no
dynamics** (docs/plan.md non-goals). Joint velocity is the slope of the
interpolant, which means it steps at waypoint boundaries. That is honest for a
scripted fixture — there is no controller here to smooth it, and inventing one
would be a dynamics model by the back door.

What the seed does: it perturbs the waypoints, once, by a per-scenario bounded
amount that each scenario states explicitly. Same seed, same bytes; different
seed, a slightly different run of the same situation. The bounds are far smaller
than the margins the scenario names depend on, so `contact` contacts and
`static_bystander` does not for every seed — `tests/test_scenarios.py` asserts
exactly that across several seeds, because a fixture that only holds for seed 0
is a golden value wearing a costume.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

import numpy as np

from reg.kinematics import ORIGIN_FRAME
from reg.types import (
    BasePose,
    BaseVelocity,
    Limits,
    LimitSource,
    PoseSource,
    StateFrame,
    VelocitySource,
)
from reg.world import DEMO_WORLD, HUMAN_RADIUS, OBSTACLES, ROOM, World

#: 50 Hz, from docs/plan.md Phase 1. Stated there, not invented here — and it is
#: a field on `Scenario`, so a caller that needs another rate says so.
DEFAULT_DT = 0.02


def _is_number(value: object) -> bool:
    """Whether `value` is a real number. `True` is not one — it is a flag."""
    return not isinstance(value, bool) and isinstance(
        value, (int, float, np.integer, np.floating)
    )


@dataclass(frozen=True)
class Waypoint:
    """One scripted knot: a time and the values held at it.

    Used for both joint waypoints (`value` is `q`, radians) and the human path
    (`value` is `(x, y)`, metres).
    """

    t: float
    value: tuple[float, ...]


@dataclass(frozen=True)
class Scenario:
    """A named, deterministic situation. Frozen: it reaches the record.

    `q_jitter` and `human_jitter` are the bounded per-waypoint perturbation the
    seed applies, in radians and metres. Both are required — a scenario that did
    not state its own jitter would be claiming an invented number as a fixture
    parameter, and every compression figure downstream would inherit it.

    Five fields describe the **policy** rather than the motion:
    `declared_q_bounds`, `declared_margin_m`, `silent_windows`,
    `declared_action_class` and `fault`. A fixture is a *run*, and a run includes
    what the policy said while it happened — a trajectory alone cannot express a
    declaration that expired, one that was never issued, or one that claimed
    space the robot cannot reach. Each defaults to the not-applicable value and
    none of them is a threshold: they say what this fixture's policy does, in the
    same way `declared_q_bounds` already says what `declared_violation`'s does.

    THE BASE (issue #177, docs/mobile-base.md §7 Tier 4)
    ----------------------------------------------------
    Four more fields describe the **base**, and they arrive or are absent
    together: `base_waypoints` and, required whenever it is present,
    `base_pose_source`, `base_vel_source` and `base_jitter`. A scenario with a
    base trajectory **drives**; one without is a **fixed-base scenario**, and
    the `drives` property is what says so, rather than a pose at the origin
    standing in for the statement (see `states`).

    **The two provenances are required and neither is inferred.** A simulator's
    base pose is ground truth, which is exactly the status `human_pos` has, and
    writing it without a provenance would put an unlabelled room-frame pose into
    the stream and leave every reader to assume one. There is no correct value
    to guess: only the party that produced a pose knows whether it was
    dead-reckoned or localized, and only the party that produced a rate knows
    whether it came off wheel encoders or out of visual odometry. That is
    `Limits.source`'s argument (issue #84) for `reg.types.PoseSource` and
    `reg.types.VelocitySource` — the fixture states which case it is modelling,
    and `reg.stream` carries both into the artifact.

    **Stating one without a trajectory is a contradiction and is refused.** A
    `base_pose_source` on a fixture whose base never moves describes the
    provenance of a pose nothing writes; guessing which half the author meant is
    how a fixture silently stops being the run its fields describe.
    """

    name: str
    description: str
    world: World
    duration: float
    joint_waypoints: tuple[Waypoint, ...]
    human_waypoints: tuple[Waypoint, ...]
    q_jitter: float
    human_jitter: float
    #: The fixed joint-space bound the scripted policy declares in every replan
    #: interval of this run, independent of what it then commands
    #: (`reg.declare.emit_declarations`). That independence is what lets the
    #: claim be *false*, which is the whole purpose of `declared_violation`.
    #:
    #: `None` means this scenario states no fixed bound — not that it declares an
    #: unbounded one, and not permission for anything. Read as a field it is
    #: not-applicable; the policy handed a `None` declares exactly the region its
    #: own upcoming configurations sweep, which is a true statement about itself
    #: and therefore a compliant run.
    declared_q_bounds: tuple[tuple[float, float], ...] | None = None
    #: Metres the policy dilates its declared region by before signing it
    #: (`reg.declare.emit_declarations`). `None` means it declares the region
    #: itself and pads nothing.
    #:
    #: This is the only way a run can produce an **envelope overclaim**, and the
    #: reason is geometric: every region built from the arm's own kinematics lies
    #: inside the workspace disc `reg.enforce.computed_bound` compares against,
    #: for any joint box whatsoever, so no `declared_q_bounds` can overclaim. A
    #: padded claim can — it is the policy claiming authority over space the
    #: robot cannot physically occupy, which is a claim enforcement can refute
    #: from `Limits` alone.
    declared_margin_m: float | None = None
    #: Closed time windows `(t0, t1)`, seconds, in which the policy issues no
    #: declaration: a state at `t0 <= t <= t1` is one the policy did not see.
    #: Empty means it declares throughout.
    #:
    #: Where the window falls is what distinguishes the two timing faults, and it
    #: is a property of the run rather than of the party reading it. A window
    #: covering the whole run is a policy that never declares at all
    #: (**no declaration**); one that opens mid-run and never closes leaves the
    #: last declaration to expire (**stale declaration**); one that closes again
    #: does that *and* then offers an ordinary declaration into the passivation
    #: it caused (**escalation failure**).
    silent_windows: tuple[tuple[float, float], ...] = ()
    #: The `action_class` this run's policy stamps on every declaration instead
    #: of classifying the motion, or `None` to let it classify.
    #:
    #: A value outside `reg.declare.ACTION_CLASSES` cannot be produced by
    #: `reg.declare` at all — that module refuses to construct one, so an invalid
    #: declaration is never signed by the conforming producer. A run using one is
    #: therefore a run whose declarations came from a producer that does not
    #: share enforcement's vocabulary, which is exactly the case enforcement
    #: exists for. Not validated against the vocabulary here: the fixture that
    #: needs this field needs a word that is *not* in it.
    declared_action_class: str | None = None
    #: The semantic fault this fixture exists to produce, spelled as
    #: `reg.enforce.FAULTS` spells it, or `None` for a run in which nothing in
    #: the taxonomy should fire.
    #:
    #: A fixture named for a fault that does not produce it is worse than no
    #: fixture — it is a green test asserting nothing — so this field is what
    #: `tests/test_enforce.py` runs the real enforcer against, one fixture at a
    #: time. It is a claim about the run, not a switch: nothing here changes what
    #: the fixture does.
    fault: str | None = None
    #: The base's scripted room-frame path: knots of `(x, y, theta)` in metres
    #: and radians, interpolated exactly as `joint_waypoints` is and integrated
    #: under the base's own bounds exactly as the joints are (see `states`).
    #:
    #: `None` is **this is a fixed-base scenario** — the eleven fixtures, whose
    #: base is bolted to the origin. It is not "the base was at the origin": for
    #: a bolted base that is a mounting fact rather than a pose anybody
    #: estimated, `reg.types.PoseSource` has no member for a mounting fact, and
    #: the frames record `base_pose=None` accordingly (issue #150).
    base_waypoints: tuple[Waypoint, ...] | None = None
    #: What the base poses this fixture writes inherit, and over what horizon
    #: (`reg.types.PoseSource`). **Required when `base_waypoints` is present, no
    #: default, no inference** — and refused when it is absent, because a
    #: provenance for a pose nothing writes describes nothing.
    base_pose_source: PoseSource | None = None
    #: Whether the body-frame rates this fixture writes were measured on the
    #: robot or estimated from something perceived (`reg.types.VelocitySource`).
    #: Required and refused on exactly the terms `base_pose_source` is: the two
    #: are separate claims about the run and neither can be inferred from the
    #: other, which is why `reg.stream` gives each block its own column.
    base_vel_source: VelocitySource | None = None
    #: The bounded per-waypoint perturbation the seed applies to the base path,
    #: as `(metres, radians)`: the first bounds `x` and `y`, the second `theta`.
    #:
    #: A **pair** and not one number, for the reason `reg.types.BaseVelocity`
    #: keeps its units in separate fields: a single jitter would put metres and
    #: radians under one bound, where nothing would catch the mistake. Required
    #: alongside a trajectory for the reason `q_jitter` and `human_jitter` are
    #: required — a fixture that did not state its own jitter would be claiming
    #: an invented number as a fixture parameter.
    base_jitter: tuple[float, float] | None = None
    dt: float = DEFAULT_DT

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("a scenario without a name cannot key SCENARIOS")
        if not self.dt > 0.0:
            raise ValueError(f"{self.name}: dt must be positive, got {self.dt}")
        if not self.duration > 0.0:
            raise ValueError(
                f"{self.name}: duration must be positive, got {self.duration}"
            )
        steps = self.duration / self.dt
        if abs(steps - round(steps)) > 1e-9:
            raise ValueError(
                f"{self.name}: duration {self.duration} is not a whole number of "
                f"dt={self.dt} steps. Rounding it here would silently change the "
                "frame count, and the frame count is a denominator in Claim 1."
            )
        n_joints = len(self.world.limits.link_lengths)
        self._check_waypoints("joint_waypoints", self.joint_waypoints, n_joints)
        self._check_waypoints("human_waypoints", self.human_waypoints, 2)
        for label, jitter in (("q_jitter", self.q_jitter), ("human_jitter", self.human_jitter)):
            if jitter < 0.0:
                raise ValueError(f"{self.name}: {label} must be >= 0, got {jitter}")

        limits = self.world.limits
        for wp in self.joint_waypoints:
            q = np.asarray(wp.value, dtype=float)
            if np.any(q - self.q_jitter < limits.q_min) or np.any(
                q + self.q_jitter > limits.q_max
            ):
                raise ValueError(
                    f"{self.name}: joint waypoint at t={wp.t} is outside "
                    f"[q_min, q_max] once q_jitter={self.q_jitter} is applied. A "
                    "fixture that commands a physically impossible configuration "
                    "would make every envelope computed from it meaningless."
                )
        for wp in self.human_waypoints:
            x, y = wp.value
            if not self.world.room.contains_circle(
                x, y, self.world.human_radius + self.human_jitter
            ):
                raise ValueError(
                    f"{self.name}: human waypoint at t={wp.t} puts the human "
                    f"({x}, {y}) partly outside the room once "
                    f"human_jitter={self.human_jitter} is applied."
                )
        if self.declared_q_bounds is not None:
            if len(self.declared_q_bounds) != n_joints:
                raise ValueError(
                    f"{self.name}: declared_q_bounds has "
                    f"{len(self.declared_q_bounds)} entries for {n_joints} joints"
                )
            for j, (lo, hi) in enumerate(self.declared_q_bounds):
                if not hi > lo:
                    raise ValueError(
                        f"{self.name}: declared_q_bounds[{j}] = ({lo}, {hi}) is empty"
                    )

        self._check_policy()
        self._check_base()
        self._check_room()

    @property
    def drives(self) -> bool:
        """Whether this fixture's base moves. `False` is a **fixed-base scenario**.

        Stated as a property rather than left to be inferred from a pose at the
        origin, because those are different facts and only one of them is in the
        artifact: a fixed-base run records `base_pose=None`, which says *this
        run recorded no base pose*, and a run whose base is at the origin
        throughout would say the pose was estimated and found to be there. The
        eleven fixtures are the first case (issue #150, issue #177).
        """
        return self.base_waypoints is not None

    def _check_base(self) -> None:
        """The base trajectory and its two provenances, or their joint absence.

        Nothing here is inferred in either direction. A trajectory without a
        `PoseSource` would put an unlabelled room-frame pose into the stream —
        the thing `reg.types.BasePose` exists to make impossible, arriving one
        layer up — and a `PoseSource` without a trajectory is a provenance for a
        pose nothing writes, which is a fixture whose author meant one of two
        things nobody can recover.
        """
        companions = (
            ("base_pose_source", self.base_pose_source),
            ("base_vel_source", self.base_vel_source),
            ("base_jitter", self.base_jitter),
        )
        if self.base_waypoints is None:
            for label, value in companions:
                if value is not None:
                    raise ValueError(
                        f"{self.name}: states {label}={value!r} and no "
                        "base_waypoints. A base this fixture never drives has no "
                        "pose in the stream for that to be a statement about, so "
                        "one of the two is wrong and guessing which is worse: "
                        "dropping the field would lose a trajectory somebody "
                        "meant to write, and inventing a trajectory would make "
                        "the run a different one."
                    )
            return

        self._check_waypoints("base_waypoints", self.base_waypoints, 3)

        for label, value, enum in (
            ("base_pose_source", self.base_pose_source, PoseSource),
            ("base_vel_source", self.base_vel_source, VelocitySource),
        ):
            if value is None:
                raise ValueError(
                    f"{self.name}: drives the base and states no {label}. It is "
                    f"required with no default: a {enum.__name__} is what the "
                    "artifact records about where these numbers came from, and "
                    "the only party that knows is whoever produced them. "
                    f"Valid values: {[m.value for m in enum]}."
                )
            if not isinstance(value, enum):
                raise TypeError(
                    f"{self.name}: {label} must be a {enum.__name__}, got "
                    f"{value!r}. A string is not a provenance somebody stated — "
                    "it is one nobody checked, reaching the stream as one "
                    "somebody did."
                )

        if self.base_jitter is None:
            raise ValueError(
                f"{self.name}: drives the base and states no base_jitter. It is "
                "required for the reason q_jitter and human_jitter are: the "
                "seed perturbs every scripted path in this fixture, and a bound "
                "nobody stated would be an invented fixture parameter every "
                "figure downstream inherits. State (metres, radians); (0.0, "
                "0.0) is a base path this fixture does not perturb, said out "
                "loud."
            )
        if (
            not isinstance(self.base_jitter, tuple)
            or len(self.base_jitter) != 2
            or not all(_is_number(v) for v in self.base_jitter)
        ):
            raise ValueError(
                f"{self.name}: base_jitter must be a (metres, radians) pair, got "
                f"{self.base_jitter!r}. One number would put two units under one "
                "bound, which is the mistake `reg.types.BaseVelocity` keeps its "
                "fields apart to prevent."
            )
        for label, value in (
            ("base_jitter[0] (metres)", float(self.base_jitter[0])),
            ("base_jitter[1] (radians)", float(self.base_jitter[1])),
        ):
            if not np.isfinite(value) or value < 0.0:
                raise ValueError(
                    f"{self.name}: {label} must be finite and >= 0, got {value}"
                )

        # A SCRIPT THE ROBOT'S OWN LIMITS SAY IT CANNOT EXECUTE (issue #177).
        #
        # `states` integrates the base under these four bounds exactly as it
        # integrates the arm under `qdd_max`, so a zero anywhere in them does
        # not produce a refusal downstream — it produces a base that never
        # leaves its first knot while the fixture's name and waypoints say it
        # drove somewhere. Both speed bounds pin the base outright; both
        # acceleration bounds pin it at rest, which is the same thing arriving
        # one derivative up. All four are named because which one is zero is
        # what the author has to fix, and a bolted base states four zeros
        # (`reg.world.LIMITS`) and carries no trajectory at all.
        limits = self.world.limits
        bolted = [
            name
            for name in limits.BASE_BOUND_FIELDS
            if float(getattr(limits, name)) == 0.0
        ]
        if bolted:
            raise ValueError(
                f"{self.name}: carries base_waypoints, but this world's Limits "
                f"state {', '.join(f'{n}=0.0' for n in bolted)} — a base that "
                "cannot execute the script. A zero speed bound pins the base and "
                "a zero acceleration bound pins it at rest, so the run would "
                "record a base parked at its first knot under a fixture that "
                "says it drove. A bolted base states four zeros and no "
                "base_waypoints; a driving one states four positive bounds."
            )

    def _check_room(self) -> None:
        """The whole robot is in the room — the check `World` used to make.

        `World.__post_init__` asserted that the room contained `BASE_XY`, a
        module constant, as a point of zero radius. Both halves of that were
        wrong once a base can drive (issue #184), and they were wrong in
        different ways.

        **The subject.** A point of zero radius passes a robot whose links sweep
        through a wall. `World.room_excursion` tests the disc the body can
        occupy instead, so what is checked is the robot rather than its mounting
        point, and a fixture whose arm leaves the room is refused.

        **The place.** A `World` never sees a trajectory, so a constructor
        cannot ask whether a driven base's whole *path* stays inside. Here it
        can — but only half of it can be answered at construction, and the split
        below is not tidiness:

        - A **fixed-base** fixture has one pose for the whole run, and it is
          `reg.kinematics.ORIGIN_FRAME` — the frame this repository places a
          bolted arm at. One check, at construction, covering every frame.
        - A **driving** fixture's scripted knots are checked here, inflated by
          the metres half of `base_jitter` because the seed moves each knot by
          up to that much and the fixture has to hold for every seed. That is
          all a constructor can do, and it is **not** the acceptance criterion:
          the room is convex and `contains_circle` is a convex condition, so a
          straight line between two knots that both fit cannot leave the room.
          Checking the interpolated *scripted* path would therefore be exactly
          this waypoint check written at greater length.

        The path that can leave the room between two knots is the **executed**
        one, which lags and overshoots its script under the base's own
        acceleration bounds, and which is a function of the seed. `states`
        checks that one, per frame, and it is the half that catches a base
        leaving the room and returning between two waypoints.
        """
        if not self.drives:
            excursion = self.world.room_excursion(
                ORIGIN_FRAME.x, ORIGIN_FRAME.y, slack=0.0
            )
            if excursion is not None:
                raise ValueError(
                    f"{self.name}: this is a fixed-base scenario, so its robot is "
                    f"bolted at {ORIGIN_FRAME} for the whole run — and "
                    f"{excursion.describe()}. A room that does not contain the "
                    "robot describes a robot mounted outside its own room; the "
                    "room has to be expressed in coordinates that hold it."
                )
            return

        jitter_m = float(self.base_jitter[0])
        for wp in self.base_waypoints:
            x, y, _theta = (float(v) for v in wp.value)
            excursion = self.world.room_excursion(x, y, slack=jitter_m)
            if excursion is not None:
                raise ValueError(
                    f"{self.name}: base waypoint at t={wp.t} leaves the room once "
                    f"base_jitter={jitter_m} m is applied — {excursion.describe()}. "
                    "This is the scripted knot; the trajectory the base executes "
                    "is checked per frame in `states`, and overshoots this one."
                )

    def _check_policy(self) -> None:
        """The policy-behaviour fields. Each refusal is a fixture nobody could read.

        Nothing here is a threshold and nothing is defaulted into: a malformed
        window or a margin of zero is a fixture whose author meant something,
        and guessing which is how a fault fixture silently stops producing its
        fault.
        """
        if self.declared_margin_m is not None:
            if not _is_number(self.declared_margin_m) or not (
                np.isfinite(float(self.declared_margin_m))
                and float(self.declared_margin_m) > 0.0
            ):
                raise ValueError(
                    f"{self.name}: declared_margin_m must be finite and strictly "
                    f"positive, got {self.declared_margin_m}. Zero is not 'no "
                    "padding' — that is `None`, and the two are different "
                    "statements about what the policy claimed."
                )

        if not isinstance(self.silent_windows, tuple):
            raise TypeError(
                f"{self.name}: silent_windows must be a tuple, not "
                f"{type(self.silent_windows)}. It reaches the record with the "
                "fixture, and a record that can be edited after the fact is not "
                "evidence."
            )
        previous_end = None
        for k, window in enumerate(self.silent_windows):
            if (
                not isinstance(window, tuple)
                or len(window) != 2
                or not all(_is_number(v) for v in window)
            ):
                raise ValueError(
                    f"{self.name}: silent_windows[{k}] = {window!r} is not a "
                    "(t0, t1) pair of seconds."
                )
            t0, t1 = float(window[0]), float(window[1])
            if not (0.0 <= t0 < t1 <= self.duration):
                raise ValueError(
                    f"{self.name}: silent window {k} ({t0}, {t1}) is not a "
                    f"non-empty interval inside [0.0, {self.duration}]. A window "
                    "outside the run silences nothing, and the fixture that "
                    "declared it would produce no fault while claiming one."
                )
            if previous_end is not None and t0 <= previous_end:
                raise ValueError(
                    f"{self.name}: silent window {k} starts at {t0}, at or before "
                    f"the end of the previous one ({previous_end}). Overlapping "
                    "or unordered windows describe one silence written twice, "
                    "and which one a reader is looking at changes the answer."
                )
            previous_end = t1

        for label, value in (
            ("declared_action_class", self.declared_action_class),
            ("fault", self.fault),
        ):
            if value is None:
                continue
            if not isinstance(value, str) or not value:
                raise ValueError(
                    f"{self.name}: {label} must be a non-empty str or None, got "
                    f"{value!r}."
                )
            if any(c.isspace() or ord(c) < 0x20 for c in value):
                raise ValueError(
                    f"{self.name}: {label} {value!r} contains whitespace or a "
                    "control character. It is a vocabulary word that ends up in a "
                    "record and in a query filter, not free text."
                )

    def silent_at(self, t: float) -> bool:
        """Whether the policy of this fixture issues nothing at `t`.

        Closed windows on both ends: a state at the exact boundary is one the
        policy did not see. Half-open would put the boundary frame's declaration
        on one side of the gap for reasons no reader could recover from the
        fixture.
        """
        return any(t0 <= t <= t1 for t0, t1 in self.silent_windows)

    def _check_waypoints(
        self, label: str, waypoints: tuple[Waypoint, ...], width: int
    ) -> None:
        if not isinstance(waypoints, tuple):
            raise TypeError(f"{self.name}: {label} must be a tuple, not {type(waypoints)}")
        if len(waypoints) < 2:
            raise ValueError(
                f"{self.name}: {label} needs at least two knots to interpolate "
                f"between, got {len(waypoints)}"
            )
        if waypoints[0].t != 0.0:
            raise ValueError(
                f"{self.name}: {label} starts at t={waypoints[0].t}, not 0.0. The "
                "first frame would then be extrapolated from a segment that does "
                "not cover it."
            )
        if waypoints[-1].t != self.duration:
            raise ValueError(
                f"{self.name}: {label} ends at t={waypoints[-1].t} but duration is "
                f"{self.duration}. Whichever is wrong, guessing which is worse."
            )
        for prev, nxt in zip(waypoints, waypoints[1:]):
            if not nxt.t > prev.t:
                raise ValueError(
                    f"{self.name}: {label} times are not strictly increasing "
                    f"({prev.t} then {nxt.t}); the interpolant would divide by zero "
                    "or run backwards."
                )
        for wp in waypoints:
            if len(wp.value) != width:
                raise ValueError(
                    f"{self.name}: {label} at t={wp.t} has {len(wp.value)} values, "
                    f"expected {width}. numpy would broadcast this into a "
                    "trajectory nobody wrote."
                )

    @property
    def n_frames(self) -> int:
        return int(round(self.duration / self.dt)) + 1

    def states(self, seed: int) -> Iterator[StateFrame]:
        """Yield `n_frames` ground-truth frames at `dt`, deterministically.

        `seed` is required and has no default: an audit artifact whose seed was
        chosen for it by a library is not reproducible in any way that matters,
        because nothing downstream can tell which seed it was.

        **The base, for a fixture that drives one (issue #177).** Every frame
        carries a `BasePose` — room-frame, Layer B, stamped with this
        scenario's `base_pose_source` — and a `BaseVelocity`, which is
        body-frame, Layer A, and stamped with its `base_vel_source`. A
        fixed-base fixture carries `None` for both, and that is the statement
        *this run recorded no base*, not *the base was at the origin*: for a
        bolted base that is a mounting fact rather than a pose anybody
        estimated, and `PoseSource` has no member for a mounting fact
        (issue #150).
        """
        if isinstance(seed, bool) or not isinstance(seed, (int, np.integer)):
            raise TypeError(
                f"seed must be an int, got {type(seed).__name__}. It is recorded "
                "alongside the run and has to round-trip exactly."
            )
        q_times, q_values = self._knots(self.joint_waypoints, self.q_jitter, seed, 0)
        h_times, h_values = self._knots(self.human_waypoints, self.human_jitter, seed, 1)
        b_times = b_values = None
        if self.drives:
            # Stream 2, its own generator: adding a base knot must not shift the
            # arm or the human, for the reason `_knots` gives.
            b_times, b_values = self._knots(
                self.base_waypoints,
                (self.base_jitter[0], self.base_jitter[0], self.base_jitter[1]),
                seed,
                2,
            )

        # THE ARM IS RATE-LIMITED; THE HUMAN IS NOT (issue #96).
        #
        # `_sample` is piecewise-linear, so the velocity it returns *steps* at
        # every knot and the implied acceleration is an impulse. Nine of the
        # eleven fixtures stepped by up to 8.3x `qdd_max` at one frame each.
        # That is not a trajectory any arm can execute, and it is the plant
        # `reg.envelope.outer_envelope` assumes: the outer bound is sound for a
        # saturated double integrator obeying `qdd_max`, so a scenario that
        # violates it is a scenario the bound makes no promise about. The three
        # "no truthful declaration is ever vetoed" sentences were true of the
        # shipped fixtures only because they crawl at 6.5-48% of `qd_max` — true
        # by luck rather than by construction, and an external review built a
        # legal `Scenario` that produced a VETO against a policy telling the
        # literal truth.
        #
        # So the arm integrates the script under its own limits instead of
        # teleporting along it: `want` is the velocity that would reach the next
        # scripted pose, and the step toward it is clipped to `qdd_max * dt`.
        # This makes the recorded trajectory the *executed* one rather than the
        # *scripted* one, which is what an evidence artifact should hold, and it
        # reverses this module's earlier "no filtering, no controller" — stated
        # here rather than quietly, because it changes what a fixture means.
        # Verified before adopting: every fixture keeps its fault, with minimum
        # separations identical to four decimal places.
        #
        # The human is left alone. `human_pos` is Layer B ground truth about the
        # world, not something the robot actuates, and giving it an acceleration
        # limit would invent a physics for a person.
        # The velocity reported at frame k is the one that carries the arm to
        # frame k+1, so `q[k+1] - q[k] == qd[k] * dt` holds exactly. That is not
        # a stylistic choice: `reg.envelope` computes the envelope at frame k
        # from (q[k], qd[k]) and it must predict where the arm actually goes, so
        # a frame whose qd is the velocity it *arrived* with would poison every
        # envelope built from it. `test_velocity_is_the_slope_of_the_interpolant`
        # is the gate, and it caught this integrator the first time round.
        #
        # THE BASE IS RATE-LIMITED TOO, AND FOR THE SAME REASON (issue #177).
        #
        # The paragraph above is about `qdd_max`; every word of it holds one
        # frame out, for `base_a_max` and `base_alpha_max`. Since issue #163 the
        # base's own motion is inside `reg.envelope.outer_envelope`, and since
        # issue #164 that envelope is the *only* term in the bound a mobile
        # robot is VETOed against — `reg.enforce.computed_bound` refuses for a
        # base that can drive, because a workspace disc is finite only while the
        # base is bolted down. So a fixture whose base teleports along its script
        # is a fixture the bound makes no promise about, and it would produce
        # VETOes against policies telling the literal truth. The base integrates
        # its script instead, and what the frames record is the trajectory the
        # base *executed*.
        #
        # It integrates in the room frame and reports body-frame rates, which is
        # exact rather than approximate: `base_v_max`, `base_a_max`,
        # `base_omega_max` and `base_alpha_max` are magnitude bounds
        # (`reg.types.Limits`), magnitudes are invariant under rotation, and
        # `omega` is the same number in both frames. Clipping `(vx, vy)`
        # radially is the nearest-point projection onto a disc, which is
        # non-expansive, so capping the speed after capping the acceleration
        # cannot push the step back over `base_a_max * dt`.
        limits = self.world.limits
        q_ref0, _ = _sample(q_times, q_values, 0.0)
        q_cur = np.array(q_ref0, dtype=float)
        qd_cur = np.zeros(len(limits.qd_max), dtype=float)
        if self.drives:
            base_ref0, _ = _sample(b_times, b_values, 0.0)
            pose_cur = np.array(base_ref0, dtype=float)
            v_cur = np.zeros(2, dtype=float)
            omega_cur = 0.0

        for k in range(self.n_frames):
            t = k * self.dt
            nxt = min(t + self.dt, (self.n_frames - 1) * self.dt)
            q_ref_next, _ = _sample(q_times, q_values, nxt)
            want = (q_ref_next - q_cur) / self.dt
            step = np.clip(
                want - qd_cur, -limits.qdd_max * self.dt, limits.qdd_max * self.dt
            )
            qd_cur = np.clip(qd_cur + step, -limits.qd_max, limits.qd_max)
            q = np.array(q_cur, dtype=float)
            qd = np.array(qd_cur, dtype=float)
            q_cur = q_cur + qd_cur * self.dt
            q.setflags(write=False)
            qd.setflags(write=False)
            pos, vel = _sample(h_times, h_values, t)

            base_pose = base_vel = None
            if self.drives:
                # THE ROOM CHECK, ON THE POSE THIS FRAME RECORDS (issue #184).
                #
                # `_check_room` checked the scripted knots at construction, and
                # that is not this: the base integrates its script under
                # `base_a_max` and `base_alpha_max`, so the executed path lags
                # its reference and overshoots at every corner. A base that
                # leaves the room and comes back between two waypoints is
                # invisible to any check on the waypoints — the room is convex,
                # so a straight line between two knots that fit cannot leave it
                # — and it is exactly what this catches, at the frame it
                # happens on. `slack=0.0`: the jitter is already in `pose_cur`.
                excursion = self.world.room_excursion(
                    float(pose_cur[0]), float(pose_cur[1]), slack=0.0
                )
                if excursion is not None:
                    raise ValueError(
                        f"{self.name}: the base leaves the room at t={t:g} s "
                        f"(frame {k} of {self.n_frames}, seed {seed}) — "
                        f"{excursion.describe()}. Every scripted knot is inside "
                        "the room, or this fixture would not have constructed; "
                        "what leaves it is the trajectory the base *executes*, "
                        "which lags its script and overshoots the corners under "
                        "base_a_max and base_alpha_max. Move the knot, slow the "
                        "script, or state a room that holds the manoeuvre."
                    )
                pose_ref_next, _ = _sample(b_times, b_values, nxt)
                v_cur = _cap(
                    v_cur
                    + _cap(
                        (pose_ref_next[:2] - pose_cur[:2]) / self.dt - v_cur,
                        limits.base_a_max * self.dt,
                    ),
                    limits.base_v_max,
                )
                want_omega = (pose_ref_next[2] - pose_cur[2]) / self.dt
                omega_cur = float(
                    np.clip(
                        omega_cur
                        + np.clip(
                            want_omega - omega_cur,
                            -limits.base_alpha_max * self.dt,
                            limits.base_alpha_max * self.dt,
                        ),
                        -limits.base_omega_max,
                        limits.base_omega_max,
                    )
                )
                theta = float(pose_cur[2])
                base_pose = BasePose(
                    x=float(pose_cur[0]),
                    y=float(pose_cur[1]),
                    theta=theta,
                    source=self.base_pose_source,
                )
                # Room-frame rate rotated into the body frame by -theta: the
                # velocity a wheel encoder on *this* base would read while the
                # base is pointing where the pose above says it is. The pose the
                # rotation uses is the one being reported, so
                # `pose[k+1] == pose[k] + R(theta[k]) @ v_body[k] * dt` holds
                # exactly — the base's half of the invariant the arm's `qd`
                # carries, and the reason `reg.envelope.base_motion_bounds` can
                # read this rate and predict where the base actually goes.
                cos_t, sin_t = np.cos(theta), np.sin(theta)
                base_vel = BaseVelocity(
                    vx=float(cos_t * v_cur[0] + sin_t * v_cur[1]),
                    vy=float(-sin_t * v_cur[0] + cos_t * v_cur[1]),
                    omega=omega_cur,
                    source=self.base_vel_source,
                )
                pose_cur = pose_cur + np.array(
                    [v_cur[0] * self.dt, v_cur[1] * self.dt, omega_cur * self.dt]
                )

            yield StateFrame(
                t=t,
                q=q,
                qd=qd,
                human_pos=pos,
                human_vel=vel,
                # A fixed-base fixture is a fixed arm: there is no base to have
                # a velocity, and *the base is at the origin* is a mounting fact
                # rather than a pose anybody estimated, so there is no
                # `PoseSource` that would honestly describe one. Both are
                # recorded as not-recorded (issue #150). A fixture that drives
                # fills both, above, and `reg.stream` grows the two optional
                # blocks that carry them (issue #176).
                base_vel=base_vel,
                base_pose=base_pose,
                objects=self.world.obstacles,
            )

    def _knots(
        self, waypoints: tuple[Waypoint, ...], jitter: float, seed: int, stream: int
    ) -> tuple[np.ndarray, np.ndarray]:
        """Waypoint times and seed-perturbed values.

        Each waypoint set draws from its own generator (`stream`), so adding a
        joint waypoint cannot silently shift the human path — which would make
        two runs of "the same" scenario incomparable for reasons invisible in
        the diff.
        """
        times = np.array([wp.t for wp in waypoints], dtype=float)
        values = np.array([wp.value for wp in waypoints], dtype=float)
        scale = np.asarray(jitter, dtype=float)
        if scale.ndim == 0:
            # The scalar path, untouched. `rng.uniform` dispatches on whether
            # its bounds are scalars, so routing the joint and human draws
            # through the array branch below could move the numbers every
            # published figure is measured on — for a change that is supposed
            # to leave the eleven fixtures byte-identical.
            if jitter > 0.0:
                rng = np.random.default_rng([seed, stream])
                values = values + rng.uniform(-jitter, jitter, size=values.shape)
            return times, values
        # Per-column bounds, for a path whose columns are not all in the same
        # unit — the base's `(x, y, theta)`. One number would bound metres and
        # radians together (`Scenario.base_jitter`).
        if np.any(scale > 0.0):
            rng = np.random.default_rng([seed, stream])
            values = values + rng.uniform(-scale, scale, size=values.shape)
        return times, values


def _cap(vector: np.ndarray, bound: float) -> np.ndarray:
    """`vector`, scaled down radially until its length is at most `bound`.

    The nearest point of the disc of radius `bound`, which is what makes it
    composable: projection onto a convex set is non-expansive, so applying this
    twice — once to an acceleration step and once to the speed that results —
    cannot violate the first bound in service of the second. `bound` is a
    magnitude and is never negative (`reg.types.Limits` refuses one).
    """
    length = float(np.hypot(vector[0], vector[1]))
    if length <= bound or length == 0.0:
        return np.asarray(vector, dtype=float)
    return np.asarray(vector, dtype=float) * (bound / length)


def _sample(times: np.ndarray, values: np.ndarray, t: float) -> tuple[np.ndarray, np.ndarray]:
    """Piecewise-linear value and its slope at `t`. Both arrays are read-only.

    The slope *is* the velocity: no filtering, no controller. It steps at knots.
    """
    i = int(np.searchsorted(times, t, side="right")) - 1
    i = min(max(i, 0), len(times) - 2)
    span = times[i + 1] - times[i]
    slope = (values[i + 1] - values[i]) / span
    value = values[i] + slope * (t - times[i])
    # Read-only: these land in a frozen StateFrame, and a record that can be
    # mutated after the fact is not evidence.
    value.setflags(write=False)
    slope.setflags(write=False)
    return value, slope


# --------------------------------------------------------------------------
# The six situations. Each one exists to make a specific downstream question
# answerable;
# the comment above each says which, because a fixture whose purpose is only in
# its name drifts until it no longer tests what it claims.
#
# Geometry to keep in your head while reading: base at the origin, links 0.5 +
# 0.4, body radius 0.05 (so 0.95 m of workspace), human disc radius 0.25. The
# human's disc therefore overlaps the workspace disc below 1.20 m from the base,
# and touches the arm below 0.30 m from a link segment.
#
# The forward reachable envelope is much tighter than the workspace disc, and
# that is what the overlap fixtures are placed against. Over the 200 ms horizon
# of docs/plan.md Phase 2, and at the joint speeds these scripted trajectories
# actually command, the envelope extends only about 0.1-0.25 m beyond the body,
# mostly tangentially — the arm sweeps, it does not lunge. So a human who is
# inside the envelope without being touched sits in a band roughly 0.30-0.45 m
# from a link segment. `approach_and_retreat`, `near_miss` and
# `sustained_overlap` are all positioned in that band; standing merely inside
# the workspace disc is not the same claim and does not imply it.
# --------------------------------------------------------------------------

APPROACH_AND_RETREAT = Scenario(
    name="approach_and_retreat",
    description=(
        "Human enters the reachable region, dwells, and leaves again. No contact. "
        "The transition case: two edge boundaries and an interval between them, "
        "which is what the temporal graph has to get right."
    ),
    world=DEMO_WORLD,
    duration=6.0,
    # Arm works up and to the left throughout; the elbow is out around
    # (-0.37, 0.34) and the tip around (-0.70, 0.55) at the midpoint.
    joint_waypoints=(
        Waypoint(0.0, (2.00, 0.40)),
        Waypoint(3.0, (2.40, 0.20)),
        Waypoint(6.0, (2.00, 0.40)),
    ),
    # Straight down onto the outside of that sweep and back out: 1.65 m from the
    # base (clear of the envelope, and clear of the workspace disc too) to
    # 0.95 m, which puts the disc inside the envelope with ~0.11 m of body
    # clearance left. Not along the +x axis: an approach from the right would
    # have to cross the arm to reach the band the envelope occupies.
    human_waypoints=(
        Waypoint(0.0, (-0.41, 1.60)),
        Waypoint(3.0, (-0.41, 0.86)),
        Waypoint(6.0, (-0.41, 1.60)),
    ),
    q_jitter=0.01,
    human_jitter=0.01,
)

NEAR_MISS = Scenario(
    name="near_miss",
    description=(
        "The arm reaches out as the human passes; envelope and human overlap, "
        "bodies clear by roughly 7 cm. The case that separates 'was in the "
        "reachable set' from 'was touched' — if a query conflates those, this is "
        "the fixture that catches it."
    ),
    world=DEMO_WORLD,
    duration=5.0,
    # Elbow unfolds from 1.6 rad to 0.75 rad at the moment of closest approach.
    joint_waypoints=(
        Waypoint(0.0, (0.00, 1.60)),
        Waypoint(2.5, (0.00, 0.75)),
        Waypoint(5.0, (0.00, 1.60)),
    ),
    human_waypoints=(
        Waypoint(0.0, (2.20, 0.00)),
        Waypoint(2.5, (1.05, 0.00)),
        Waypoint(5.0, (2.20, 0.00)),
    ),
    q_jitter=0.01,
    human_jitter=0.01,
)

CONTACT = Scenario(
    name="contact",
    description=(
        "Body intersection: the arm is straight out and the human walks onto it. "
        "The incident case — the one the incident report in Phase 7 is written "
        "against."
    ),
    world=DEMO_WORLD,
    duration=5.0,
    # Straight out (q = [0, 0], tip at 0.9 m) and held there through the crossing.
    joint_waypoints=(
        Waypoint(0.0, (0.00, 1.80)),
        Waypoint(2.0, (0.00, 0.00)),
        Waypoint(3.5, (0.00, 0.00)),
        Waypoint(5.0, (0.00, 1.80)),
    ),
    human_waypoints=(
        Waypoint(0.0, (2.20, 0.00)),
        Waypoint(2.75, (0.70, 0.00)),
        Waypoint(5.0, (2.20, 0.00)),
    ),
    q_jitter=0.01,
    human_jitter=0.01,
)

STATIC_BYSTANDER = Scenario(
    name="static_bystander",
    description=(
        "Human present for every frame, never inside the envelope, while the arm "
        "sweeps its full range. The negative control: an entity that is always in "
        "the scene and never in an answer."
    ),
    world=DEMO_WORLD,
    duration=6.0,
    joint_waypoints=(
        Waypoint(0.0, (-0.80, 0.90)),
        Waypoint(3.0, (1.20, -0.90)),
        Waypoint(6.0, (-0.80, 0.90)),
    ),
    # 2.6 m from the base — outside the 1.20 m overlap distance by a wide margin.
    human_waypoints=(
        Waypoint(0.0, (2.20, 1.40)),
        Waypoint(6.0, (2.20, 1.40)),
    ),
    q_jitter=0.01,
    human_jitter=0.01,
)

SUSTAINED_OVERLAP = Scenario(
    name="sustained_overlap",
    description=(
        "Human standing inside the arm's forward reachable set for the whole run, "
        "shifting slightly as the arm sweeps past them, and never touched. Every "
        "frame overlaps, so the incremental graph should emit one long edge rather "
        "than 300 short ones — this is the fixture the compression claim is most "
        "exposed to."
    ),
    world=DEMO_WORLD,
    duration=6.0,
    # Arm points down and to the right for the entire run.
    joint_waypoints=(
        Waypoint(0.0, (-1.30, 0.50)),
        Waypoint(3.0, (-1.70, 0.90)),
        Waypoint(6.0, (-1.30, 0.50)),
    ),
    # Just outside the arm on the far side of the tip, drifting with it: the tip
    # runs (0.41, -0.77) -> (0.21, -0.78) -> back, and the human tracks that with
    # a 0.16 m shuffle. ~0.84 m from the base, so inside the workspace disc, but
    # the claim this fixture makes is the tighter one — inside the 200 ms
    # envelope on every frame, with ~0.08 m of body clearance left over.
    human_waypoints=(
        Waypoint(0.0, (0.69, -0.48)),
        Waypoint(3.0, (0.53, -0.55)),
        Waypoint(6.0, (0.69, -0.48)),
    ),
    q_jitter=0.01,
    human_jitter=0.01,
)

DECLARED_VIOLATION = Scenario(
    name="declared_violation",
    description=(
        "The arm commands q0 out to 1.5 rad after declaring it would stay within "
        "0.8. Physically legal, so no other fixture catches it: the violation is "
        "of the policy's own statement, which is the whole point of Layer A "
        "attestation. The human is parked far away so the run isolates the fault."
    ),
    world=DEMO_WORLD,
    duration=5.0,
    joint_waypoints=(
        Waypoint(0.0, (0.00, 1.00)),
        Waypoint(2.0, (0.75, 0.60)),
        Waypoint(3.5, (1.50, 0.30)),
        Waypoint(5.0, (0.60, 1.00)),
    ),
    human_waypoints=(
        Waypoint(0.0, (2.70, -1.10)),
        Waypoint(5.0, (2.70, -1.10)),
    ),
    q_jitter=0.01,
    human_jitter=0.01,
    # Narrower than the physical limits by design: the policy under-claims, then
    # exceeds its own claim. Phase 3 emits this as a Declaration; Phase 4's
    # enforcement recomputes the physical bound and never trusts this number.
    declared_q_bounds=((-0.40, 0.80), (-1.60, 1.60)),
    # The one semantic fault that had a fixture before issue #46. Stated rather
    # than left implicit now that the other five have one: the geometry above is
    # untouched, and this field only writes down what the run already produced.
    fault="declaration_action_mismatch",
)

# --------------------------------------------------------------------------
# The five fault fixtures (issue #46).
#
# WHY THEY EXIST AT ALL, GIVEN THAT `tests/test_enforce.py` ALREADY TESTS THE
# NINE. Issue #43 demonstrated every fault against a synthetic declaration built
# in the test, which is the right way to test detection logic and says nothing
# about whether the fault can occur. A fault that has never appeared in a run
# cannot reach the graph, the occurrence layer, or an incident report — and an
# incident report can only narrate what a run produced. So each of these is a
# run: a trajectory, a policy that behaves in one specific wrong way, and the
# real enforcer over the real declarations.
#
# THE HUMAN IS PARKED IN THE CORNER IN ALL FIVE, at the spot `declared_violation`
# uses. These fixtures are about Layer A — what the policy claimed and when — and
# a person wandering into the reachable set would put a second story in the run
# for no reason. The seed still perturbs both the arm and the human, because a
# fixture that only holds for seed 0 is a golden value in disguise.
#
# THE THREE TRANSPORT FAULTS GET NO FIXTURE, DELIBERATELY. `unattributed`,
# `replay_or_reorder` and `watchdog_expiry` are PROFIsafe's (docs/prior-art.md
# §5) and stay unit-tested: forging a MAC inside a fixture would mean this
# module holding a key it has no business holding, and a reordered stream is a
# property of a channel rather than of a run. `tests/test_scenarios.py` asserts
# the split rather than leaving it to this comment.
# --------------------------------------------------------------------------

#: Where the human stands in every fault fixture: the far corner, clear of the
#: room's walls, of all three obstacles and of the workspace disc by a wide
#: margin. Shared so that "the human is not what this fixture is about" is one
#: line rather than five separate placements to re-verify.
_PARKED_HUMAN: tuple[Waypoint, ...] = (
    Waypoint(0.0, (2.70, -1.10)),
    Waypoint(2.0, (2.70, -1.10)),
)


def _parked(duration: float) -> tuple[Waypoint, ...]:
    """`_PARKED_HUMAN`, ending exactly on `duration` as `Scenario` requires."""
    x, y = _PARKED_HUMAN[0].value
    return (Waypoint(0.0, (x, y)), Waypoint(duration, (x, y)))


NO_DECLARATION = Scenario(
    name="no_declaration",
    description=(
        "The arm reaches out and back and the policy never declares anything at "
        "all — the declaration channel was never wired up, or the policy came up "
        "without it. Actuation before the first declaration, which is the fault: "
        "enforcement VETOes the very first commanded action and passivates, and "
        "every frame after it is a safe state carrying the same fault. Nothing "
        "else catches it, because there is nothing else to catch: the motion is "
        "physically legal, the arm never approaches the human, and every other "
        "check in the taxonomy is a check on a record that this run does not "
        "contain. It is the fixture for the case where the evidence is missing "
        "rather than wrong."
    ),
    world=DEMO_WORLD,
    duration=2.0,
    joint_waypoints=(
        Waypoint(0.0, (0.20, 1.40)),
        Waypoint(1.0, (0.20, 0.70)),
        Waypoint(2.0, (0.20, 1.40)),
    ),
    human_waypoints=_parked(2.0),
    q_jitter=0.01,
    human_jitter=0.01,
    # The whole run. The policy is not late; it is absent.
    silent_windows=((0.0, 2.0),),
    fault="no_declaration",
)

STALE_DECLARATION = Scenario(
    name="stale_declaration",
    description=(
        "The policy declares for the first two seconds of a sweep and then stops, "
        "while the arm keeps moving. Its last declaration expires one horizon "
        "later and enforcement VETOes: the robot is acting under a statement of "
        "intent that has run out. Nothing else catches it — the declarations are "
        "signed, in sequence, in vocabulary, and honest about the region the arm "
        "occupies, so the only thing wrong with the run is *when* it stopped "
        "saying so. Distinct from the watchdog, which is the liveness check on "
        "the channel and is a transport fault: this run's channel is not being "
        "checked for silence, it is being checked for a claim that has expired, "
        "and the horizon is the shorter of the two by construction."
    ),
    world=DEMO_WORLD,
    duration=3.0,
    # A slow sweep across the front of the robot: ~0.4 rad/s at the shoulder,
    # well inside qd_max, and continuing right through the silence so that the
    # run is a robot in motion under an expired claim rather than a parked one.
    joint_waypoints=(
        Waypoint(0.0, (-0.60, 1.20)),
        Waypoint(3.0, (0.60, 0.80)),
    ),
    human_waypoints=_parked(3.0),
    q_jitter=0.01,
    human_jitter=0.01,
    # A fixed box, generously around the sweep: the claim stays true for the whole
    # run at every seed, so no declaration/action mismatch can fire and the run
    # isolates the expiry. The trajectory is 0.2 rad inside it on both joints,
    # which is far more than the grid step `reg.declare` derives for it.
    declared_q_bounds=((-0.80, 0.80), (0.60, 1.40)),
    # From t=2.0 to the end. The policy stops and never resumes, so the run
    # contains an expiry and nothing after it.
    silent_windows=((2.0, 3.0),),
    fault="stale_declaration",
)

ESCALATION_FAILURE = Scenario(
    name="escalation_failure",
    description=(
        "`stale_declaration`'s silence, and then the policy starts talking again "
        "as though nothing had happened. Enforcement has passivated on the expiry "
        "and nobody has acknowledged it, so the next declaration is obliged to be "
        "an `escalate` (reg/enforce.py states the condition). It is an ordinary "
        "`traverse`, which is the fault: escalation conditions met, no escalation "
        "emitted. The most sequenced of the five, and the one with no PROFIsafe "
        "analogue — a transport protocol never has to consider a party that fails "
        "by *not acting*. Nothing else catches it: the late declaration is signed, "
        "in sequence, in vocabulary and honest, so every other check in the "
        "taxonomy passes it. It arrives while the robot is in a safe state it has "
        "not been told about, which is exactly what a black channel means."
    ),
    world=DEMO_WORLD,
    duration=4.0,
    joint_waypoints=(
        Waypoint(0.0, (-0.60, 1.20)),
        Waypoint(4.0, (0.60, 0.80)),
    ),
    human_waypoints=_parked(4.0),
    q_jitter=0.01,
    human_jitter=0.01,
    declared_q_bounds=((-0.80, 0.80), (0.60, 1.40)),
    # One second of silence, then the policy resumes. Long enough to expire the
    # open declaration (0.5 s horizon), short enough that the run continues for a
    # second afterwards with declarations landing inside the passivation.
    silent_windows=((2.0, 3.0),),
    fault="escalation_failure",
)

ENVELOPE_OVERCLAIM = Scenario(
    name="envelope_overclaim",
    description=(
        "The arm works near full extension and the policy pads every declared "
        "region by 25 cm 'to be safe'. Padding a claim is not conservatism — the "
        "declared envelope is the region the robot is being authorised to sweep, "
        "and 25 cm around a 0.90 m arm claims authority over space no "
        "configuration of it can reach. Enforcement recomputes the workspace disc "
        "from `Limits` and VETOes the declaration itself. Nothing else catches "
        "it, and no joint box could produce it: every region built from the arm's "
        "own kinematics lies inside that disc, so the overclaim has to come from "
        "a claim the policy made about *space* rather than about configurations. "
        "It is the fixture for a policy whose model of the robot is wrong."
    ),
    world=DEMO_WORLD,
    duration=2.0,
    # Near-straight throughout: the elbow stays inside [0.20, 0.40] rad, so the
    # body reaches about 0.88 m and the padded claim about 1.13 m against a
    # 0.95 m bound. Every declaration in the run overclaims, not just some.
    joint_waypoints=(
        Waypoint(0.0, (-0.30, 0.40)),
        Waypoint(1.0, (0.30, 0.20)),
        Waypoint(2.0, (-0.30, 0.40)),
    ),
    human_waypoints=_parked(2.0),
    q_jitter=0.01,
    human_jitter=0.01,
    declared_margin_m=0.25,
    fault="envelope_overclaim",
)

OUT_OF_VOCABULARY_ACTION = Scenario(
    name="out_of_vocabulary_action",
    description=(
        "An ordinary sweep, declared as a `lunge` — a sixth action class that "
        "exists on the policy side and was never agreed with the constraint "
        "layer. Enforcement VETOes: it holds one copy of the vocabulary, imported "
        "rather than restated, and a word outside it is a claim nothing "
        "downstream can read. Nothing else catches it, and that is the point — "
        "the record is well-formed, correctly signed, in sequence, and its "
        "geometry is honest, so every check that looks at the run rather than at "
        "the word passes it. `reg.declare` refuses to *build* one, so this run's "
        "declarations necessarily come from a producer that does not share the "
        "vocabulary, which is the case enforcement exists for."
    ),
    world=DEMO_WORLD,
    duration=2.0,
    # A pure shoulder sweep at a fixed elbow: the arm's reach never changes, so
    # the conforming policy would have classified this `traverse`.
    joint_waypoints=(
        Waypoint(0.0, (0.00, 1.20)),
        Waypoint(1.0, (0.60, 1.20)),
        Waypoint(2.0, (0.00, 1.20)),
    ),
    human_waypoints=_parked(2.0),
    q_jitter=0.01,
    human_jitter=0.01,
    declared_action_class="lunge",
    fault="out_of_vocabulary_action",
)

_ALL: tuple[Scenario, ...] = (
    APPROACH_AND_RETREAT,
    NEAR_MISS,
    CONTACT,
    STATIC_BYSTANDER,
    SUSTAINED_OVERLAP,
    DECLARED_VIOLATION,
    NO_DECLARATION,
    STALE_DECLARATION,
    ESCALATION_FAILURE,
    ENVELOPE_OVERCLAIM,
    OUT_OF_VOCABULARY_ACTION,
)

#: Name to definition. `list(SCENARIOS)` is the authoritative list, and its order
#: is the declaration order above — benchmark tables are keyed off it.
SCENARIOS: dict[str, Scenario] = {s.name: s for s in _ALL}

if len(SCENARIOS) != len(_ALL):  # pragma: no cover - construction-time invariant
    raise RuntimeError(
        "two scenarios share a name; one silently replaced the other in SCENARIOS"
    )


# --------------------------------------------------------------------------
# THE THREE MOBILE FIXTURES (issue #178, docs/mobile-base.md §7 Tier 4)
#
# The eleven above are bolted to the origin. These three drive, and they are the
# first runs in this repository in which anything does.
#
# WHY THEY ARE NOT IN `SCENARIOS`, WHICH IS THE FIRST THING TO EXPLAIN.
# `SCENARIOS` is what `reg.bench --all` prices and what every published figure
# in docs/retention.md is measured over, and **Claim 1 stays a fixed-arm claim**
# (docs/mobile-base.md §5): the mobile track is exploratory and unbenchmarked.
# A mobile run also writes a wider stream — `reg.stream` derives the header from
# the frames, so a driving run grows the two optional base blocks and stops
# being the 24-column `expected_header(2, 3)` that Claim 1's gzip baseline is
# divided by. Registering these beside the eleven would therefore move published
# figures by arithmetic rather than by argument. So they live in their own
# mapping, `scenario()` resolves them, and nothing that iterates `SCENARIOS`
# sees them — the same split `long_run` already uses, for a different reason.
#
# WHAT THAT COSTS AND WHERE IT IS PAID. A reader of `reg.sim --list` sees both
# groups, labelled, because a fixture nothing lists is a fixture nobody runs.
#
# THE FIXTURE LIST IS ARGUED, NOT ENUMERATED. Each of the three exists to make
# one claim of this track exercisable, and the comment above it says which. A
# fourth motion nobody can name a reason for would not be a fixture.
#
# Geometry to keep in your head, as for the eleven: the arm and the room are
# unchanged — links 0.5 + 0.4, body radius 0.05, human disc 0.25, room
# x in [-2, 3] and y in [-1.5, 2]. What is new is that the base is somewhere,
# so every distance below is stated from *the base at that instant* and the
# workspace disc travels with it.
# --------------------------------------------------------------------------

#: The same arm on a base that can drive. Identical to `reg.world.LIMITS` in
#: every arm field — same links, same `qd_max`, same `qdd_max` — so that a
#: difference between a mobile run and a fixed-base one is the base and not a
#: second robot.
#:
#: The four base numbers are **fixture parameters stated here, not
#: measurements**, exactly as `reg.world.LIMITS`'s four zeros are: a bolted arm
#: states four zeros because that is a fact about its mounting, and this vehicle
#: states four positive bounds because that is a fact about this fixture's
#: robot. They are of the order a small indoor differential-drive base has —
#: walking pace, a metre per second per second — and nothing downstream may read
#: them as a datasheet.
#:
#: `PROPRIOCEPTIVE` for the reason `reg.world.LIMITS` gives (issue #84): these
#: are the robot's own numbers and a function of nothing measured, so every
#: `HAS_ENVELOPE` edge computed from them is Layer A *as far as the limits are
#: concerned*. That is not the whole story for a mobile run and must not be read
#: as one — an envelope over a configuration that states a base pose is Layer B
#: whatever this field says, because the pose came from outside the robot
#: (docs/sufficiency.md §5.8, issue #191).
MOBILE_LIMITS = Limits(
    q_min=np.array([-np.pi, -2.6]),
    q_max=np.array([np.pi, 2.6]),
    qd_max=np.array([2.0, 2.5]),
    qdd_max=np.array([8.0, 10.0]),
    link_lengths=np.array([0.5, 0.4]),
    source=LimitSource.PROPRIOCEPTIVE,
    link_radius=0.05,
    base_v_max=0.8,
    base_a_max=1.2,
    base_omega_max=1.0,
    base_alpha_max=2.0,
)

#: `reg.world.DEMO_WORLD` with the vehicle in it: the same room, the same three
#: obstacles, the same human. Only `limits` differs, so the mobile fixtures and
#: the eleven share a scene and a difference between them is the robot.
#:
#: **Built here rather than in `reg.world`** because `DEMO_WORLD` is the world
#: every published figure is measured in and a second world beside it invites
#: the two to be compared; this one belongs with the three fixtures that use it
#: and with the comment above saying why they are not priced.
MOBILE_WORLD = World(
    room=ROOM,
    obstacles=OBSTACLES,
    limits=MOBILE_LIMITS,
    human_radius=HUMAN_RADIUS,
)

# THE CLAIM: the room-frame answer is Layer B, and the base pose is in the
# artifact (docs/sufficiency.md §5.6, issue #191).
#
# A person stands still in the room for five seconds and never moves. At the
# pose the run starts from they are 1.51 m from the base — 0.31 m outside the
# 1.20 m at which the *workspace disc* and their own disc first touch, and the
# workspace disc is the whole set the arm could occupy in any configuration
# with no horizon in it — so no question about the arm, asked at t=0, puts the
# robot anywhere near them. The base then drives 0.79 m, the arm unfolds, and
# the same person is inside the arm's forward reachable set for the last 1.5 s
# of the run with the bodies clear by 6 cm.
#
# That is the distinction §5.6 is about, made concrete: *can the robot reach
# this configuration* is Layer A and unchanged by the drive, and *can the robot
# reach this room coordinate* has two different answers in one run and both of
# them depend on a pose the robot did not measure. It is also the fixture that
# proves an artifact built from a mobile run can be read back and queried — the
# poses are on `robot_config`, the retained geometry is the room-frame envelope,
# and the INTERSECTS edge exists because of where the base drove.
MOBILE_TRANSIT = Scenario(
    name="mobile_transit",
    description=(
        "A person stands still and the robot drives to them, arm folded, then "
        "unfolds it. At the base pose the run starts from they are outside the "
        "workspace disc entirely — no configuration of the arm reaches them, at "
        "any horizon — and after a 0.79 m transit they are inside the arm's "
        "forward reachable set for the last third of the run, bodies clear by "
        "about 6 cm. The room-frame case: the same question about the same "
        "coordinate has two answers in one run, and what changed is a pose "
        "nothing on the robot measured."
    ),
    world=MOBILE_WORLD,
    duration=5.0,
    # Folded for the transit, then unfolded and held. THE FOLD IS LOAD-BEARING
    # and was not the first draft: with the arm out throughout, its bearing from
    # the base sweeps one way while the human's bearing sweeps the other, the
    # two cross halfway through the drive, and the fixture makes contact — a
    # `contact` fixture with a mobile base, which is not what this one claims.
    # Carrying the arm in and presenting it on arrival is also what a vehicle
    # does, and it puts the whole approach in the base's motion where this
    # fixture's claim is.
    #
    # The presenting pose is `approach_and_retreat`'s midpoint mirrored about
    # the y-axis — that fixture reaches up and to the *left* and this base
    # drives to the right — which is where the (0.41, 0.86) relative placement
    # of the human below comes from. A mirrored arm has a mirrored geometry, so
    # the 0.11 m of body clearance that placement was chosen for is the same
    # number here.
    joint_waypoints=(
        Waypoint(0.0, (1.20, -2.20)),
        Waypoint(2.5, (1.20, -2.20)),
        Waypoint(3.5, (0.74, -0.20)),
        Waypoint(5.0, (0.74, -0.20)),
    ),
    # Parked at (1.02, 0.60) for the whole run: 1.51 m from the starting base
    # and 1.01 m from where it settles, which is (0.43, 0.90) in the base's own
    # frame at the end — the mirrored placement above, a few centimetres out.
    # Measured across five seeds: the bodies never come closer than 6 cm and the
    # person is inside the envelope on the last 75 frames of the run.
    human_waypoints=(
        Waypoint(0.0, (1.02, 0.60)),
        Waypoint(5.0, (1.02, 0.60)),
    ),
    q_jitter=0.01,
    human_jitter=0.01,
    # Straight along +x: a trapezoid, easing in over the first second and out
    # over the last. THE SHAPE IS NOT DECORATION AND IT IS NOT TASTE.
    #
    # The base integrates this script under `base_a_max` rather than following
    # it (see `states`), so a reference that starts or stops abruptly builds a
    # position lag the integrator then closes at full acceleration — which
    # overshoots in *speed* until it hits `base_v_max`, and leaves the executed
    # path ringing about the target for the rest of the run. Both halves of that
    # are a problem here and the first is the one that bites:
    #
    # **A base at exactly `base_v_max` writes a stream that will not build.**
    # `reg.stream` writes at `FLOAT_PRECISION` decimals, so a body-frame rate
    # capped at exactly 0.8 m/s can round back a fraction of a micrometre per
    # second *over* it, and `reg.envelope.base_motion_bounds` correctly refuses
    # a state outside its own limits — its displacement bound is an upper bound
    # only while `|v0| <= v_max`. That refusal is right and the fixture is what
    # has to change: a mobile fixture keeps clear of its own speed cap, and the
    # margin has to be much larger than the quantum rather than merely nonzero.
    # This profile peaks at 0.56 m/s against a cap of 0.80.
    #
    # And with it the base settles within a centimetre of 0.59 m and stays,
    # which is what makes "it arrived, and then the person was reachable"
    # something a reader can see rather than infer.
    base_waypoints=(
        Waypoint(0.0, (-0.20, -0.30, 0.0)),
        Waypoint(1.0, (-0.05, -0.30, 0.0)),
        Waypoint(2.5, (0.50, -0.30, 0.0)),
        Waypoint(3.0, (0.59, -0.30, 0.0)),
        Waypoint(5.0, (0.59, -0.30, 0.0)),
    ),
    # Dead reckoning, because that is what a base with wheel encoders and no
    # map has and it is the weaker of the two — an artifact built from this run
    # says its poses drift, which is the honest claim for a simulator that
    # localizes nothing (docs/mobile-base.md §5: no perceiver is built).
    base_pose_source=PoseSource.DEAD_RECKONED,
    # The rates are the vehicle's own, off its wheels: Layer A, and what
    # `reg.envelope.base_motion_bounds` reads.
    base_vel_source=VelocitySource.PROPRIOCEPTIVE,
    # A centimetre and five milliradians, the same order as the arm's 0.01 rad.
    # Far smaller than the 0.31 m the claim above has in hand, so the fixture is
    # the same fixture at every seed.
    base_jitter=(0.01, 0.005),
)

# THE CLAIM: driving is not reaching (issue #165, docs/mobile-base.md §4 item 6).
#
# The arm holds one configuration for the whole run — `q_jitter=0.0`, said out
# loud, because a seed that perturbed the two knots independently would unfreeze
# it and there would be no frozen arm to make the claim about. The base drives a
# metre and turns 0.6 rad under it, so the end effector's distance from the
# *room origin* nearly doubles while the arm's own extension does not change by
# one bit.
#
# `reg.declare._extension` is the measurement that has to be blind to that, and
# it was not until issue #165: it took the base frame and subtracted it back,
# which is exact in real arithmetic and not in floating point, so the same
# frozen arm classified `traverse` on one machine and `retract` on another.
# This run is what makes that regression visible in a *fixture* rather than in a
# constructed pair of base frames — a run where the base really drove, whose
# poses a test can hand straight to the classifier.
#
# AND IT SURFACES A GAP, WHICH IS WHAT A FIRST FIXTURE IS FOR. Run the scripted
# policy over this run and every declaration comes back `hold`, not `traverse`.
# That is not this fixture drifting: `reg.declare.emit_declarations` passes
# `ORIGIN_FRAME` to `_classify` for every run, because a policy sees a
# `ProprioState` and a base *pose* is Layer B — so with the configurations
# identical the classifier takes its `hold` branch, and `hold` is exactly what
# that function's own docstring says a driving robot is not. Nothing here is
# wrong to fix it: the honest repair is for the policy to dead-reckon its own
# frames from `base_vel`, which is a Layer A quantity it does hold, and that is
# a decision about what the scripted policy is, not a fixture parameter. It is
# recorded in docs/mobile-base.md §7 as something this tier does not support,
# and the test beside this fixture asserts the claim that *is* true of the run —
# no declaration in it is a `reach`, at any seed.
MOBILE_FROZEN_ARM = Scenario(
    name="mobile_frozen_arm",
    description=(
        "The arm holds one configuration — straight out along the body's own "
        "+x — while the base drives a metre and turns 0.6 rad under it. The end "
        "effector travels most of a metre through the room and the arm extends "
        "by nothing, which is the whole distinction: driving is not reaching, "
        "and an action class read off the tip's distance from the room origin "
        "would call this run a `reach` it never made."
    ),
    world=MOBILE_WORLD,
    duration=3.0,
    # Straight out and held. Two identical knots, which is what a frozen arm is.
    joint_waypoints=(
        Waypoint(0.0, (0.00, 0.00)),
        Waypoint(3.0, (0.00, 0.00)),
    ),
    human_waypoints=_parked(3.0),
    # ZERO, AND IT IS A STATEMENT RATHER THAN AN OMISSION. Every other fixture
    # here perturbs its joint knots; this one must not, because `_knots` draws
    # per knot and a perturbed pair would leave the arm creeping between two
    # slightly different configurations — a fixture named for a frozen arm whose
    # arm is not frozen. The seed is still a real input to this run: it moves
    # the human and it moves the base path, and two seeds give two different
    # runs (`base_jitter` below).
    q_jitter=0.0,
    human_jitter=0.01,
    # Forward and turning at the same time, because the two halves of "the tip
    # moved and the arm did not" are translation and rotation and a fixture that
    # only translated would leave the second untested.
    base_waypoints=(
        Waypoint(0.0, (0.00, -0.30, 0.00)),
        Waypoint(1.5, (0.55, -0.30, 0.30)),
        Waypoint(3.0, (1.00, -0.30, 0.60)),
    ),
    base_pose_source=PoseSource.DEAD_RECKONED,
    base_vel_source=VelocitySource.PROPRIOCEPTIVE,
    base_jitter=(0.01, 0.005),
)

# THE CLAIM, AND THE FAULT: every VETO for a mobile robot rests on
# `reg.envelope.outer_envelope` alone (issue #164, docs/mobile-base.md §1).
#
# `envelope_overclaim` above is the same policy behaviour on a bolted arm, and
# there the refutation is cheap: `reg.enforce.computed_bound` returns the
# 0.95 m workspace disc from `Limits` alone, with no `q`, no `qd` and no horizon
# in it, and a padded claim past it is refused on arithmetic nobody can argue
# with. For this robot that function **refuses**, naming the base bounds that
# made the workspace unbounded, so the 0.95 m disc does not exist to refute
# anything: the only bound left is the radial projection of the horizon-limited
# outer reachable set, which over this run measures 1.12 m at rest and up to
# 1.34 m at speed — bigger than the arm's disc, because the vehicle can drive
# out of it, and not a constant, because the vehicle's speed is not one.
#
# So this fixture is the one that makes #164's refusal more than an assertion.
# The policy pads its declared region by 60 cm, the padded claim reaches about
# 1.50 m from the base, and the VETO that follows rests on `outer_envelope`'s
# soundness argument and on nothing else. It is also the taxonomy negative this
# tier needs: a mobile fixture set in which nothing ever goes wrong would
# exercise the happy path of a mechanism whose entire purpose is the unhappy
# one.
MOBILE_OVERCLAIM = Scenario(
    name="mobile_overclaim",
    description=(
        "A driving robot whose policy pads every declared region by 60 cm 'to "
        "be safe'. On a bolted arm the padding is refuted by the workspace disc; "
        "this robot has no workspace disc — its base can drive, so given enough "
        "time it reaches everywhere — and `reg.enforce.computed_bound` refuses "
        "to invent one. The declaration is refused against the radial "
        "projection of the horizon-limited outer reachable set and against "
        "nothing else, which is the first VETO in this repository that rests on "
        "that argument alone."
    ),
    world=MOBILE_WORLD,
    duration=2.0,
    # `envelope_overclaim`'s arm, unchanged: near-straight throughout, so the
    # unpadded region is honest about what the arm sweeps and what is out of
    # bounds is the padding and only the padding.
    joint_waypoints=(
        Waypoint(0.0, (-0.30, 0.40)),
        Waypoint(1.0, (0.30, 0.20)),
        Waypoint(2.0, (-0.30, 0.40)),
    ),
    human_waypoints=_parked(2.0),
    q_jitter=0.01,
    human_jitter=0.01,
    # A short straight transit. The base is beside the point here — what this
    # fixture is about is what the policy claimed — but it has to be driving,
    # because a base at rest with four positive bounds is still a robot
    # `computed_bound` refuses and the fixture would then be making its claim
    # about a vehicle that never moved.
    base_waypoints=(
        Waypoint(0.0, (0.00, -0.30, 0.0)),
        Waypoint(2.0, (0.70, -0.30, 0.0)),
    ),
    base_pose_source=PoseSource.DEAD_RECKONED,
    base_vel_source=VelocitySource.PROPRIOCEPTIVE,
    base_jitter=(0.01, 0.005),
    # 60 cm. Measured rather than picked: over this run the bound this robot is
    # refused against runs 1.12-1.34 m — it is a function of where the arm is
    # and how fast the base is going, so it moves declaration to declaration —
    # and the unpadded region reaches about 0.90 m. At 60 cm every declaration
    # in the run overclaims, by 0.16 to 0.38 m at every seed tried, which is far
    # enough from the boundary that the fault turns on the claim rather than on
    # floating point. `envelope_overclaim`'s 25 cm would not do: it clears the
    # 0.95 m disc a bolted arm is refused against, but against a bound that is
    # larger and moving it lands at 1.15 m — over the first declaration's 1.12 m
    # and under every later one's — so the run would refuse one declaration and
    # accept four. That is itself the point being made: the two bounds are
    # different objects, and the mobile one is neither the arm's disc nor a
    # constant.
    declared_margin_m=0.60,
    fault="envelope_overclaim",
)

_MOBILE: tuple[Scenario, ...] = (
    MOBILE_TRANSIT,
    MOBILE_FROZEN_ARM,
    MOBILE_OVERCLAIM,
)

#: The mobile fixtures, name to definition. **Deliberately not merged into
#: `SCENARIOS`** — see the block comment above. `scenario()` resolves both, so a
#: stream whose provenance block says `scenario=mobile_transit` can be rebuilt,
#: and nothing that iterates `SCENARIOS` prices a run that drove.
MOBILE_SCENARIOS: dict[str, Scenario] = {s.name: s for s in _MOBILE}

if len(MOBILE_SCENARIOS) != len(_MOBILE):  # pragma: no cover - construction-time
    raise RuntimeError(
        "two mobile scenarios share a name; one silently replaced the other"
    )

_shared = set(SCENARIOS) & set(MOBILE_SCENARIOS)
if _shared:  # pragma: no cover - construction-time invariant
    raise RuntimeError(
        f"{sorted(_shared)}: a name is in both SCENARIOS and MOBILE_SCENARIOS. "
        "`scenario()` resolves the first, so the second would be unreachable by "
        "name and a stream naming it would rebuild as the wrong run."
    )
del _shared


def scenario(name: str) -> Scenario:
    """Look up a scenario, failing with the list of names rather than a KeyError.

    A caller that mistypes a name should not get an empty result set that reads
    like 'nothing happened in that run'.

    **Three registries, one lookup.** `MOBILE_SCENARIOS` and the generated
    `long_run_<n>` resolve here even though neither is in `SCENARIOS`, and for
    one reason: a stream's provenance block records the scenario *name*, so a
    name this function cannot resolve is a stream whose world — the robot's
    `Limits` and the human's radius, neither of which is a column — cannot be
    recovered from the file (`reg.graph._resolve_world`). Keeping the mobile
    fixtures out of `SCENARIOS` is about what is *priced* (see the block comment
    above `MOBILE_LIMITS`); it must not be about what can be rebuilt.
    """
    for registry in (SCENARIOS, MOBILE_SCENARIOS):
        try:
            return registry[name]
        except KeyError:
            pass
    generated = _long_run_from_name(name)
    if generated is not None:
        return generated
    raise KeyError(
        f"unknown scenario {name!r}; known scenarios are {list(SCENARIOS)}, the "
        f"mobile fixtures {list(MOBILE_SCENARIOS)}, plus the generated "
        f"{LONG_RUN_PREFIX}<frames> (e.g. {LONG_RUN_PREFIX}3000)"
    )


# --------------------------------------------------------------------------
# The long run (issue #30). One scenario at any frame count.
#
# WHY IT IS GENERATED AND THE OTHER SIX ARE NOT. The six answer questions about
# a *situation* — contact, near miss, bystander — and a situation is a thing you
# write down. This one answers a question about *length*: Claim 1 is a claim
# about scaling and the six all run for five or six seconds, which is the one
# regime where the answer cannot be read off (fixed schema cost dominates
# everything at 300 frames). So the length is the parameter, and the fixture is
# a function of it.
#
# WHAT IT MUST NOT BE. A short loop repeated exactly. Every cycle would produce
# byte-identical frames, gzip would collapse the baseline in a way no real run
# compresses, and the incremental rule would see one transition set repeated —
# both sides of the ratio would be measuring the fixture's periodicity rather
# than the graph. So the cycles *drift*: the arm's sweep and the human's closest
# approach are offset each cycle by `_drift`, an irrational rotation, which
# takes a different value on every cycle for any run length. The motion stays
# periodic in character and never repeats in fact.
#
# WHAT IT IS. A robot doing repetitive work while a person walks past it now and
# then, which is the run an operator would actually have on disk at the end of a
# shift. The arm cycles between two poses; the human patrols in and out on a
# longer period, so their closest approach lands at a different point in the
# arm's cycle each time and some approaches enter the reachable set while others
# do not. Nothing here is tuned to make the compression number look good, and
# the honest consequence is stated: an arm that moves continuously changes its
# distance to every entity continuously, so SEPARATION edges emit at a rate set
# by how fast the arm moves. That is what the scaling table is measuring.
# --------------------------------------------------------------------------

#: Prefix of the generated names. `long_run_3000` is 3000 frames.
LONG_RUN_PREFIX = "long_run_"

#: Seconds for one full out-and-back of the arm. Two knots per cycle.
LONG_RUN_ARM_PERIOD_S = 4.0

#: The two poses the arm works between, in radians. The elbow unfolds from 1.60
#: to 0.75 — `near_miss`'s reach, which is the one the human's patrol line is
#: placed against — and the shoulder holds near zero so the arm works to the +x
#: side, where the patrol line is.
LONG_RUN_ARM_PICK: tuple[float, float] = (0.00, 1.60)
LONG_RUN_ARM_PLACE: tuple[float, float] = (0.00, 0.75)

#: Per-cycle drift applied to each joint knot, in radians: the sweep is not the
#: same sweep twice. Well inside `DEMO_WORLD.limits` at both poses.
LONG_RUN_ARM_DRIFT: tuple[float, float] = (0.25, 0.10)

#: Seconds for one full approach-and-retreat of the human. Deliberately not a
#: multiple of the arm period (20:27 against it), so the closest approach lands
#: at a different phase of the arm's cycle each time. Short enough that even the
#: shortest length in the scaling ladder contains a whole approach: a 300-frame
#: row in which the human never gets near the robot would not be measuring the
#: same fixture as the 30,000-frame row above it.
LONG_RUN_HUMAN_PERIOD_S = 5.4

#: The patrol line, in metres. Far end well outside the workspace disc; near end
#: at 1.00 m from the base, just inside `near_miss`'s 1.05 m closest approach.
#:
#: Measured, not argued, at 16 envelope samples and seed 0: over 300 frames the
#: closest the bodies come is 0.139 m and the person is inside the reachable set
#: at that frame; the run's furthest frame is 1.43 m away and outside it, so the
#: fixture is not trivially always-overlapping. **Contact does happen at length**
#: — none in 3,000 frames, 9 frames of 10,000 — which is left in rather than
#: tuned out: rare events are what a long run is retained for, and a fixture
#: that could never produce one would make the graph's contact machinery
#: untested over exactly the lengths this study is about.
LONG_RUN_HUMAN_FAR: tuple[float, float] = (2.30, 0.00)
LONG_RUN_HUMAN_NEAR: tuple[float, float] = (1.00, 0.00)

#: Per-cycle drift on the human knots, in metres, along the patrol line.
LONG_RUN_HUMAN_DRIFT = 0.10

#: The same bounded seed perturbation the six use, stated here for the same
#: reason: a fixture that did not state its own jitter would put an invented
#: number under every figure measured from it.
LONG_RUN_Q_JITTER = 0.01
LONG_RUN_HUMAN_JITTER = 0.01

#: The joint box this run's policy declares, added 2026-08-20 with issue #59.
#:
#: **Why the long run needs one at all.** `reg.bench --resolution` prices what
#: each resolution level can still answer, and until issue #59 it measured an
#: artifact built with `records=None` — so every Layer A question came back
#: could-not-evaluate for a reason that had nothing to do with resolution. The
#: curve's fixture is this one, so this is where Layer A has to enter the
#: measurement.
#:
#: **Why this box.** Measured over the trajectory rather than picked: at every
#: seed tried the run commands `q0` inside [-0.13, 0.13] and `q1` inside
#: [0.69, 1.65], so `((-0.20, 0.20), (0.60, 1.70))` strictly contains **every
#: configuration the run visits**. The policy is therefore telling the truth
#: about where the arm *is*, at every frame of the run.
#:
#: **And enforcement still refuses on some of them, which is the point.**
#: `reg.enforce` does not compare the declared box against the commanded
#: configuration; it computes the region reachable over the declaration's own
#: horizon from the arm's state and actuation limits, and checks the declared
#: region contains it. A moving arm can reach outside a box it never statically
#: enters, so the claim is honest about position and wrong about reachability —
#: which is exactly the distinction an attestation layer exists to record, and
#: it is `declaration_action_mismatch` in the Phase 4 taxonomy.
#:
#: **Measured, at 0.5 s replan and 0.5 s horizon** (the parameterization
#: `reg.bench` states and `tests/test_chain.py` and `tests/test_enforce.py`
#: already use): over 3,000 frames the run produces 120 declarations, 3,000
#: verdicts and 24–72 clamped actions at seeds 0–7 — a startup episode plus one
#: to three mid-run ones, under 2.5% of frames. Rare, seed-robust and non-zero,
#: which is what a fixture for a *long* run should produce: a fault that only
#: fires at one seed is a golden value in disguise, and one that fires on most
#: frames is a robot that is never doing what it said.
LONG_RUN_DECLARED_Q_BOUNDS: tuple[tuple[float, float], ...] = (
    (-0.20, 0.20),
    (0.60, 1.70),
)

#: Golden-ratio conjugate. `k * _DRIFT_ROTATION mod 1` is equidistributed and
#: never returns the same value twice, which is exactly the property wanted: the
#: cycles differ from each other at every run length, with no random draw and no
#: seed involved. (The seed's job is the per-run perturbation; the drift is part
#: of the fixture and must be identical across seeds.)
_DRIFT_ROTATION = 0.6180339887498949

#: Absolute tolerance, in seconds, for "this knot lands on the run's end". Only
#: used to decide whether the final knot is generated or interpolated; both
#: paths produce the same trajectory, so it never moves a number.
_KNOT_EPS_S = 1e-9


def _drift(k: int) -> float:
    """A bounded per-cycle offset in [-0.5, 0.5), different for every `k`."""
    return ((k * _DRIFT_ROTATION) % 1.0) - 0.5


def _pattern_knots(
    half_period: float, duration: float, value_at
) -> tuple[Waypoint, ...]:
    """Knots every `half_period`, with a last one landing exactly on `duration`.

    `Scenario` requires the final knot at `duration` exactly, and a run length
    is not in general a whole number of cycles. The final knot is therefore the
    pattern's own value *interpolated within the segment it falls in*, not the
    next pattern value moved backwards: the second would change the trajectory's
    slope over the last segment, which would make the run's final velocity a
    function of where the run happened to be cut.
    """
    knots: list[Waypoint] = []
    k = 0
    while k * half_period < duration - _KNOT_EPS_S:
        knots.append(Waypoint(k * half_period, value_at(k)))
        k += 1
    last = knots[-1]
    span = k * half_period - last.t
    frac = (duration - last.t) / span
    nxt = value_at(k)
    knots.append(
        Waypoint(
            duration,
            tuple(a + (b - a) * frac for a, b in zip(last.value, nxt)),
        )
    )
    return tuple(knots)


def long_run(n_frames: int, *, dt: float = DEFAULT_DT) -> Scenario:
    """The long-run fixture at `n_frames` frames. Deterministic in the count.

    Args:
        n_frames: how many frames the run is. No default: the frame count *is*
            the parameter this fixture exists to vary, and a fixture that picked
            one would answer the scaling question at a length nobody chose.
        dt: the frame period, 50 Hz as everywhere else in this module.

    Returns:
        A `Scenario` named `long_run_<n_frames>`, resolvable by `scenario()`.

    Raises:
        TypeError: `n_frames` is not an integer.
        ValueError: fewer than two frames, so there is no run.
    """
    if isinstance(n_frames, bool) or not isinstance(n_frames, (int, np.integer)):
        raise TypeError(
            f"n_frames must be an int, got {type(n_frames).__name__}. It names "
            "the fixture and is recorded in the stream's provenance block."
        )
    n_frames = int(n_frames)
    if n_frames < 2:
        raise ValueError(
            f"n_frames={n_frames}: a run needs at least two frames for a frame "
            "period to exist, and `reg.graph` refuses a stream without one."
        )
    duration = (n_frames - 1) * dt

    def arm(k: int) -> tuple[float, ...]:
        base = LONG_RUN_ARM_PICK if k % 2 == 0 else LONG_RUN_ARM_PLACE
        return tuple(
            value + drift * _drift(k)
            for value, drift in zip(base, LONG_RUN_ARM_DRIFT)
        )

    def human(k: int) -> tuple[float, ...]:
        base = LONG_RUN_HUMAN_FAR if k % 2 == 0 else LONG_RUN_HUMAN_NEAR
        return (base[0] + LONG_RUN_HUMAN_DRIFT * _drift(k), base[1])

    return Scenario(
        name=f"{LONG_RUN_PREFIX}{n_frames}",
        description=(
            f"{n_frames} frames of repetitive work: the arm cycles between two "
            f"poses every {LONG_RUN_ARM_PERIOD_S} s while a person patrols in "
            f"and out every {LONG_RUN_HUMAN_PERIOD_S} s. Every cycle differs "
            "slightly from the last, so no two frames of the run are identical. "
            "Approaches enter the reachable set often and reach contact rarely, "
            "and how rarely is a function of how long the run is. "
            "Generated at any length, for the scaling half of Claim 1 "
            "(issue #30) — the six hand-authored fixtures all run for about six "
            "seconds, which is the one length at which a claim about scaling "
            "cannot be tested. Its policy declares the joint box it works "
            "within and is occasionally refused for a reachable set that leaves "
            "it, so the run carries Layer A as well (issue #59)."
        ),
        world=DEMO_WORLD,
        duration=duration,
        joint_waypoints=_pattern_knots(LONG_RUN_ARM_PERIOD_S / 2.0, duration, arm),
        human_waypoints=_pattern_knots(LONG_RUN_HUMAN_PERIOD_S / 2.0, duration, human),
        q_jitter=LONG_RUN_Q_JITTER,
        human_jitter=LONG_RUN_HUMAN_JITTER,
        # The two policy fields, added by issue #59. Neither touches the motion
        # and neither reaches the stream's provenance block, so no byte count
        # measured before this change moves: a build handed `records=None` is
        # byte-identical to what it was. What they change is that a build handed
        # a keyring now has declarations, verdicts, faults and two chains in it.
        declared_q_bounds=LONG_RUN_DECLARED_Q_BOUNDS,
        fault="declaration_action_mismatch",
        dt=dt,
    )


def _long_run_from_name(name: str) -> Scenario | None:
    """`long_run(n)` for a generated name, or `None` if this is not one.

    `None` rather than a raise: the caller is `scenario()`, and a name this
    function does not recognise has to reach that function's own error message
    with the full list of known names, not a message about frame counts.

    A name that *is* one of these and still cannot be built — `long_run_1` — is
    a `KeyError` like every other unresolvable name, carrying the reason.
    `scenario()` has one failure mode and callers catch one exception type.
    """
    text = str(name)
    if not text.startswith(LONG_RUN_PREFIX):
        return None
    suffix = text[len(LONG_RUN_PREFIX) :]
    if not suffix.isdigit():
        return None
    try:
        return long_run(int(suffix))
    except ValueError as exc:
        raise KeyError(f"unknown scenario {name!r}: {exc}") from None
