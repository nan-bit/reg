"""The six named scenario fixtures. **Layer B** — this is simulator ground truth.

These are the fixtures everything downstream is measured against, so they come
first (docs/plan.md, Phase 1). They are hand-authored and small on purpose:
randomised scenarios would make the compression numbers in Claim 1
unfalsifiable — you cannot argue about a ratio nobody can regenerate.

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
    """

    name: str
    description: str
    world: World
    duration: float
    joint_waypoints: tuple[Waypoint, ...]
    human_waypoints: tuple[Waypoint, ...]
    q_jitter: float
    human_jitter: float
    #: The joint-space bound the scripted policy will declare in Phase 3, when
    #: `declare/` exists. `None` means this scenario declares nothing, which is
    #: not the same as declaring an unbounded one — a consumer must treat it as
    #: not-applicable rather than as permission.
    declared_q_bounds: tuple[tuple[float, float], ...] | None = None
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
# The six. Each one exists to make a specific downstream question answerable;
# the comment above each says which, because a fixture whose purpose is only in
# its name drifts until it no longer tests what it claims.
#
# Geometry to keep in your head while reading: base at the origin, links 0.5 +
# 0.4, body radius 0.05 (so 0.95 m of workspace), human disc radius 0.25. The
# human's disc therefore overlaps the workspace disc below 1.20 m from the base,
# and touches the arm below 0.30 m from a link segment.
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
    # Arm works up and to the left throughout, away from the approach line.
    joint_waypoints=(
        Waypoint(0.0, (2.00, 0.40)),
        Waypoint(3.0, (2.40, 0.20)),
        Waypoint(6.0, (2.00, 0.40)),
    ),
    # In from 2.4 m (clear), to 0.85 m (well inside the workspace disc), back out.
    human_waypoints=(
        Waypoint(0.0, (2.40, 0.00)),
        Waypoint(3.0, (0.85, 0.00)),
        Waypoint(6.0, (2.40, 0.00)),
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
        "Human standing inside the workspace disc for the whole run while the arm "
        "works away from them. Every frame overlaps, so the incremental graph "
        "should emit one long edge rather than 300 short ones — this is the "
        "fixture the compression claim is most exposed to."
    ),
    world=DEMO_WORLD,
    duration=6.0,
    # Arm points down and to the right for the entire run.
    joint_waypoints=(
        Waypoint(0.0, (-1.30, 0.50)),
        Waypoint(3.0, (-1.70, 0.90)),
        Waypoint(6.0, (-1.30, 0.50)),
    ),
    # 0.93 m from the base: inside the workspace disc, far from the arm.
    human_waypoints=(
        Waypoint(0.0, (0.75, 0.55)),
        Waypoint(3.0, (0.78, 0.50)),
        Waypoint(6.0, (0.75, 0.55)),
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
)

_ALL: tuple[Scenario, ...] = (
    APPROACH_AND_RETREAT,
    NEAR_MISS,
    CONTACT,
    STATIC_BYSTANDER,
    SUSTAINED_OVERLAP,
    DECLARED_VIOLATION,
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
    """
    try:
        return SCENARIOS[name]
    except KeyError:
        raise KeyError(
            f"unknown scenario {name!r}; known scenarios are {list(SCENARIOS)}"
        ) from None
