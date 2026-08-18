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

The robot base is at the **origin** of room coordinates. That is not a choice
made here: `reg/kinematics.py` fixes the base at the origin, and a `World` whose
room does not contain the origin describes a robot mounted outside its own room.
`World.__post_init__` rejects it rather than letting the fixtures drift.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from shapely.geometry import Point, Polygon, box

from reg.types import Limits, Obstacle

# The robot base, in room coordinates. Fixed by reg/kinematics.py, restated here
# because the room and the obstacle placements are only meaningful relative to it.
BASE_XY: tuple[float, float] = (0.0, 0.0)


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
        bx, by = BASE_XY
        if not self.room.contains_circle(bx, by, 0.0):
            raise ValueError(
                f"the robot base {BASE_XY} is outside the room {self.room}. The "
                "base is fixed at the origin by reg/kinematics.py, so the room "
                "must be expressed in coordinates that contain it."
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
LIMITS = Limits(
    q_min=np.array([-np.pi, -2.6]),
    q_max=np.array([np.pi, 2.6]),
    qd_max=np.array([2.0, 2.5]),
    qdd_max=np.array([8.0, 10.0]),
    link_lengths=np.array([0.5, 0.4]),
    link_radius=0.05,
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
