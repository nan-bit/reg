"""The world the scenarios happen in. **Layer B, in its entirety.**

Everything in this module is simulator ground truth: where the room is, where
the obstacles are, how big the human is. In a real system this information comes
from a perception stack, which is exactly why it is uncertifiable — a volume
derived from perception inherits perception's failure modes (docs/plan.md,
Phase 9).

Nothing in Layer A may read a `World`. The envelope takes a `ProprioState`
(`reg/types.py`), which cannot name any of this. If you find yourself wanting to
pass a `World` into `envelope/` or `enforce/`, that is the sufficiency argument
being dismantled, not a convenience.

WHERE THE BASE IS, AND WHY THIS MODULE NO LONGER SAYS (issue #184)
-----------------------------------------------------------------
`World.__post_init__` used to assert that the room contained a module constant
`BASE_XY`, and that constant was this repository's statement of where the base
is. Both are gone. The statement belongs to `reg.kinematics.ORIGIN_FRAME` — the
frame every caller here places a bolted arm at, and `grep ORIGIN_FRAME` is the
list of places that assumption is made — and the check belongs where a base can
have a *path*: a `World` never sees a trajectory, so it cannot answer whether a
driven base stays in the room, and a constructor answering the question it can
reach rather than the one that matters is a check that has stopped checking. It
is `reg.scenarios.Scenario`'s now, over every interpolated pose the run records.

What the check is *for* is unchanged: a room that does not contain the robot
describes a robot mounted outside its own room, which is a fixture bug rather
than a runtime condition. What this module keeps is the geometry — see
`World.room_excursion`, which the scenario calls — and it now covers the whole
robot rather than the base as a point of zero radius.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from shapely.geometry import Point, Polygon, box

from reg.types import Limits, LimitSource, Obstacle


@dataclass(frozen=True)
class Room:
    """Rectangular bounds. Frozen — it reaches the record, so it cannot move."""

    x_min: float
    y_min: float
    x_max: float
    y_max: float

    def __post_init__(self) -> None:
        if not self.x_max > self.x_min:
            raise ValueError(
                f"room x_max ({self.x_max}) must exceed x_min ({self.x_min}); "
                "a room with no width is not a degenerate case worth supporting."
            )
        if not self.y_max > self.y_min:
            raise ValueError(
                f"room y_max ({self.y_max}) must exceed y_min ({self.y_min}); "
                "a room with no height is not a degenerate case worth supporting."
            )

    @property
    def polygon(self) -> Polygon:
        return box(self.x_min, self.y_min, self.x_max, self.y_max)

    def contains_circle(self, cx: float, cy: float, radius: float) -> bool:
        """Whether a disc of `radius` at `(cx, cy)` lies wholly inside the room."""
        return (
            cx - radius >= self.x_min
            and cx + radius <= self.x_max
            and cy - radius >= self.y_min
            and cy + radius <= self.y_max
        )


@dataclass(frozen=True)
class RoomExcursion:
    """A robot standing somewhere, and the wall it does not fit inside.

    Returned by `World.room_excursion`, which reports rather than raises: the
    caller that has the *path* is the one that can say **when** it happened, and
    a check whose message cannot name the instant makes a fixture author bisect
    by hand (issue #184).

    `wall` is the field of `Room` that was crossed and `overshoot_m` is how far
    past it the robot's workspace disc reaches. `base_overshoot_m` is how far the
    base *point* is past that same wall, and it is negative when the base is
    inside — that sign is the whole distinction between *the robot is mounted
    outside its room* and *the robot is in the room and its arm is not*, which
    are different fixture bugs with different repairs.
    """

    wall: str
    wall_value: float
    overshoot_m: float
    base_overshoot_m: float
    radius_m: float
    base_xy: tuple[float, float]

    @property
    def base_outside(self) -> bool:
        """Whether the base itself crossed the wall, rather than only its reach."""
        return self.base_overshoot_m > 0.0

    def describe(self) -> str:
        """One sentence naming which part of the robot left the room, and where.

        Deliberately not a `ValueError`: what is missing from it is the *when*,
        which only the caller holding the trajectory knows, and every caller
        prefixes it with one.
        """
        x, y = self.base_xy
        if self.base_outside:
            return (
                f"the base itself is outside the room — it is at ({x:.4f}, "
                f"{y:.4f}), {self.base_overshoot_m:.4f} m past {self.wall}="
                f"{self.wall_value}, and the {self.radius_m:.4f} m disc its body "
                f"can occupy crosses that wall by {self.overshoot_m:.4f} m"
            )
        return (
            f"the base is at ({x:.4f}, {y:.4f}) and inside the room, but the "
            f"{self.radius_m:.4f} m disc its body can occupy crosses {self.wall}="
            f"{self.wall_value} by {self.overshoot_m:.4f} m — the arm sweeps out "
            "of the room even though the base does not"
        )


@dataclass(frozen=True)
class World:
    """Room, static obstacles, robot limits, human size. All Layer B except the
    limits, which are a property of the robot and therefore Layer A — they live
    here because a scenario needs one object to hand around, not because the
    boundary is soft. `Limits` is what crosses into Layer A; `World` never does.
    """

    room: Room
    obstacles: tuple[Obstacle, ...]
    limits: Limits
    human_radius: float

    def __post_init__(self) -> None:
        if not self.human_radius > 0.0:
            raise ValueError(
                f"human_radius is {self.human_radius}; a human of zero extent "
                "can never contact anything and would make the contact "
                "scenarios silently vacuous."
            )
        if not isinstance(self.obstacles, tuple):
            raise TypeError(
                "World.obstacles must be a tuple. A list is mutable, and an "
                "audit record that can be edited after the fact is not evidence."
            )
        seen: set[str] = set()
        for obs in self.obstacles:
            if obs.entity_id in seen:
                raise ValueError(
                    f"duplicate entity_id {obs.entity_id!r}. Entity ids key every "
                    "edge in the evidence graph; two entities sharing one would "
                    "merge two histories into an answer about neither."
                )
            seen.add(obs.entity_id)
            if not self.room.contains_circle(obs.cx, obs.cy, obs.radius):
                raise ValueError(
                    f"obstacle {obs.entity_id!r} at ({obs.cx}, {obs.cy}) r={obs.radius} "
                    f"is not wholly inside the room {self.room}."
                )

    @property
    def max_reach(self) -> float:
        """Furthest point of the robot body from the base, arm fully extended.

        This is the *workspace* disc — every configuration, no horizon — not the
        forward reachable envelope of Phase 2, which is a subset of it bounded by
        `qd_max`/`qdd_max` over `H`. Do not use it as an envelope: it is a far
        looser bound, and using it would make the Claim 1 numbers wrong in the
        flattering direction.
        """
        return float(np.sum(self.limits.link_lengths) + self.limits.link_radius)

    def room_excursion(
        self, x: float, y: float, *, slack: float
    ) -> RoomExcursion | None:
        """How the robot standing at `(x, y)` fails to fit in the room, or `None`.

        **The subject is the whole robot, not the base.** The disc tested has
        radius `max_reach + slack`: `contains_circle(x, y, 0.0)` — what
        `World.__post_init__` asked until issue #184 — passes a robot whose links
        sweep through a wall, which is precisely the fixture bug the check exists
        to catch. `max_reach` is the workspace disc, so this over-covers: it
        refuses a fixture whose arm *could* leave the room in some configuration,
        not only one whose scripted `q` does. That is the direction to be wrong
        in, it is yaw-invariant (the disc is centred on the base and a base that
        turns does not move it), and it costs no forward kinematics per frame.

        `slack` is required and has no default. It is the room a caller has to
        leave for what it cannot see: a construction-time caller checking
        *scripted* knots passes the jitter bound, because the seed moves each
        knot by up to that much and the check has to hold for every seed; a
        caller holding an already-perturbed pose passes `0.0`. A default here
        would be a margin nobody chose applied to every fixture at once.

        Reports rather than raises. The message a fixture author needs names the
        *instant*, and this method does not know one — see `RoomExcursion`.

        The wall reported is the one the robot is furthest past, so a robot out
        of two of them is described by the worse; ties resolve in `Room` field
        order, which keeps the message a function of the geometry alone.
        """
        for name, value in (("x", x), ("y", y), ("slack", slack)):
            if not np.isfinite(float(value)):
                raise ValueError(
                    f"room_excursion: {name} is {value!r}, which is not finite. A "
                    "non-finite coordinate compares false against every wall, so "
                    "the robot would be reported as inside a room it has no "
                    "position in."
                )
        if float(slack) < 0.0:
            raise ValueError(
                f"room_excursion: slack is {slack!r}. A negative slack shrinks the "
                "robot, which would pass a fixture that does not fit."
            )
        x, y = float(x), float(y)
        radius = self.max_reach + float(slack)
        room = self.room
        crossings = (
            ("x_min", room.x_min, room.x_min - (x - radius), room.x_min - x),
            ("x_max", room.x_max, (x + radius) - room.x_max, x - room.x_max),
            ("y_min", room.y_min, room.y_min - (y - radius), room.y_min - y),
            ("y_max", room.y_max, (y + radius) - room.y_max, y - room.y_max),
        )
        wall, wall_value, overshoot, base_overshoot = max(
            crossings, key=lambda crossing: crossing[2]
        )
        if overshoot <= 0.0:
            return None
        return RoomExcursion(
            wall=wall,
            wall_value=float(wall_value),
            overshoot_m=float(overshoot),
            base_overshoot_m=float(base_overshoot),
            radius_m=float(radius),
            base_xy=(x, y),
        )

    def human_polygon(self, pos: np.ndarray) -> Polygon:
        """The human as a disc at `pos`. Layer B: ground truth from the sim."""
        if len(pos) != 2:
            raise ValueError(f"human position must be planar (2 values), got {len(pos)}")
        return Point(float(pos[0]), float(pos[1])).buffer(self.human_radius)


# --------------------------------------------------------------------------
# The demo world. One room, one arm, three obstacles — shared by all six
# scenarios so that the compression numbers in Claim 1 compare like with like.
# Hand-authored and small on purpose (docs/plan.md: randomised scenarios make
# the compression numbers unfalsifiable).
# --------------------------------------------------------------------------

#: 5 m x 3.5 m room, robot mounted at the origin, off-centre so there is a long
#: side for the human to approach along.
ROOM = Room(x_min=-2.0, y_min=-1.5, x_max=3.0, y_max=2.0)

#: Two revolute links, 0.5 m and 0.4 m: 0.9 m of reach, 0.95 m of body.
#: `qdd_max` stands in for a torque limit — there is no dynamics model here and
#: there should not be one (docs/plan.md, Phase 1).
#:
#: `PROPRIOCEPTIVE`, stated rather than assumed (issue #84): these are the
#: fixture robot's own numbers, hand-authored here and a function of nothing
#: measured, so every `HAS_ENVELOPE` edge in every artifact this repository
#: builds is Layer A. A deployment running ISO/TS 15066 speed-and-separation
#: monitoring would cap `qd_max` by a measured separation distance and write
#: `DERIVED` instead, and its envelopes would be tagged Layer B — which is what
#: they would have been all along.
LIMITS = Limits(
    q_min=np.array([-np.pi, -2.6]),
    q_max=np.array([np.pi, 2.6]),
    qd_max=np.array([2.0, 2.5]),
    qdd_max=np.array([8.0, 10.0]),
    link_lengths=np.array([0.5, 0.4]),
    source=LimitSource.PROPRIOCEPTIVE,
    link_radius=0.05,
    # The base is bolted down, and that is stated rather than omitted (issue
    # #151). Zero is a fact about this fixture — `reg.kinematics.ORIGIN_FRAME`
    # is where a bolted arm is placed, and every fixture here passes it — and
    # writing it here keeps it distinguishable from a `Limits` whose author never
    # considered the base at all. There is no arm-only `Limits` to fall back on,
    # because that would be the same default arriving through a different door.
    base_v_max=0.0,
    base_a_max=0.0,
    base_omega_max=0.0,
    base_alpha_max=0.0,
)

#: Static, and all clear of the workspace disc: the fixtures are about the human,
#: and an obstacle inside reach would make "did the robot contact something"
#: ambiguous. `tests/test_scenarios.py` asserts the clearance rather than
#: `World` enforcing it, because a different world may legitimately want one.
OBSTACLES: tuple[Obstacle, ...] = (
    Obstacle(entity_id="obs_crate", kind="crate", cx=1.6, cy=1.2, radius=0.25),
    Obstacle(entity_id="obs_pillar", kind="pillar", cx=-1.2, cy=0.9, radius=0.30),
    Obstacle(entity_id="obs_pallet", kind="pallet", cx=2.2, cy=-0.8, radius=0.20),
)

#: 0.25 m radius: a standing adult's plan-view cross-section, near enough for a
#: 2D fixture. It is a stated fixture parameter, not a measurement.
HUMAN_RADIUS = 0.25

DEMO_WORLD = World(
    room=ROOM,
    obstacles=OBSTACLES,
    limits=LIMITS,
    human_radius=HUMAN_RADIUS,
)
