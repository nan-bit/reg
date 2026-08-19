"""The eleven named scenario fixtures, and one generated long run. **Layer B** —
this is simulator ground truth.

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

from reg.types import StateFrame
from reg.world import DEMO_WORLD, World

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
        """
        if isinstance(seed, bool) or not isinstance(seed, (int, np.integer)):
            raise TypeError(
                f"seed must be an int, got {type(seed).__name__}. It is recorded "
                "alongside the run and has to round-trip exactly."
            )
        q_times, q_values = self._knots(self.joint_waypoints, self.q_jitter, seed, 0)
        h_times, h_values = self._knots(self.human_waypoints, self.human_jitter, seed, 1)

        for k in range(self.n_frames):
            t = k * self.dt
            q, qd = _sample(q_times, q_values, t)
            pos, vel = _sample(h_times, h_values, t)
            yield StateFrame(
                t=t,
                q=q,
                qd=qd,
                human_pos=pos,
                human_vel=vel,
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
        if jitter > 0.0:
            rng = np.random.default_rng([seed, stream])
            values = values + rng.uniform(-jitter, jitter, size=values.shape)
        return times, values


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


def scenario(name: str) -> Scenario:
    """Look up a scenario, failing with the list of names rather than a KeyError.

    A caller that mistypes a name should not get an empty result set that reads
    like 'nothing happened in that run'.

    `long_run_<n>` resolves to `long_run(n)` even though it is not in
    `SCENARIOS`: a stream's provenance block records the scenario *name*, and a
    name nothing can resolve would make a long run the one kind of stream whose
    world cannot be recovered from the file (`reg.graph._resolve_world`).
    """
    try:
        return SCENARIOS[name]
    except KeyError:
        pass
    generated = _long_run_from_name(name)
    if generated is not None:
        return generated
    raise KeyError(
        f"unknown scenario {name!r}; known scenarios are {list(SCENARIOS)}, plus "
        f"the generated {LONG_RUN_PREFIX}<frames> (e.g. {LONG_RUN_PREFIX}3000)"
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
            "cannot be tested."
        ),
        world=DEMO_WORLD,
        duration=duration,
        joint_waypoints=_pattern_knots(LONG_RUN_ARM_PERIOD_S / 2.0, duration, arm),
        human_waypoints=_pattern_knots(LONG_RUN_HUMAN_PERIOD_S / 2.0, duration, human),
        q_jitter=LONG_RUN_Q_JITTER,
        human_jitter=LONG_RUN_HUMAN_JITTER,
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
