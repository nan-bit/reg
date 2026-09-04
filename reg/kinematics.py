"""Planar arm forward kinematics. Layer A.

Everything here is a pure function of joint state and `Limits` — proprioception
and a property of the robot, nothing else. There is deliberately no argument by
which a caller can hand these functions an `Obstacle`, a `StateFrame`, or any
other view of the world: see the Layer A rule in CLAUDE.md and the docstring at
the top of `reg/types.py`. The envelope, the viz and every separation
computation build on this module, so the boundary has to hold here first.

Because the world cannot get in, the only way to misuse these functions is to
feed them a malformed *robot*: a `q` of the wrong length, a non-finite angle, a
zero-length link. Every one of those is rejected loudly rather than absorbed —
numpy would happily broadcast a one-element `q` across a three-link arm, and the
resulting geometry would be wrong in a way that no downstream check can see.

THE BASE IS AN ARGUMENT (issue #152)
------------------------------------
It used to be a literal. `forward_kinematics` built its cumulative sums from an
explicit leading `0.0`, and *that literal was the base* — the single line the
whole fixed-base assumption rested on (docs/limitations.md §9,
docs/mobile-base.md §4, item 1). Nothing else in the tree named a base at all,
so the assumption was not a thing a reader could see; it was the frame every
other line was written in.

It is now a required `BaseFrame` argument, and **nothing here has become
mobile**. Every caller in this repository passes `ORIGIN_FRAME`, every result is
identical, and no envelope, bound or published figure moves. What changed is
that the assumption is stated at each site instead of being implicit in one, and
that Tier 3 has a seam to cut at (docs/mobile-base.md §7).

**Required, with no default, on the rule this repository already applies to
`link_radius` (issue #115) and to the base bounds on `Limits` (issue #151).** A
base frame defaulting to the origin would be a frame nobody chose, and every
figure measured against it would be indistinguishable downstream from one a
caller stated. `ORIGIN_FRAME` is not that default arriving by another door: it is
a value a caller has to write, and `grep ORIGIN_FRAME` is now the list of places
this repository assumes a bolted-down base.

Conventions
-----------
- The base sits at the `BaseFrame` the caller passes. `ORIGIN_FRAME` is the one
  every caller here passes, and it is `(0, 0)` with no rotation.
- Angles are cumulative *from the base's heading*: joint `i` is measured
  relative to link `i-1`, so link `i` points along `base.theta + sum(q[:i+1])`.
  `q = 0` at `ORIGIN_FRAME` is the arm fully extended along `+x`.
- A link is a segment; its body is that segment buffered by `link_radius` with
  flat caps, which makes the body of an `n`-link arm exactly `n` rectangles.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from shapely.geometry import LineString, Polygon

from reg.types import Limits, ProprioState

__all__ = [
    "BaseFrame",
    "ORIGIN_FRAME",
    "forward_kinematics",
    "link_polygons",
    "clamp_to_limits",
]


@dataclass(frozen=True)
class BaseFrame:
    """The frame the arm's links are measured from. Layer A, and it is a *frame*.

    `(x, y)` is where the base joint sits and `theta` is the heading the first
    link's angle is measured from, so `forward_kinematics(q, limits, base)`
    returns the same arm, rigidly placed. Frozen, like everything that can reach
    the record.

    WHY THIS IS NOT `BasePose`, AND WHY IT MAY NOT BECOME IT
    -------------------------------------------------------
    `reg.types.BasePose` is a room-frame pose: **Layer B structurally**, because
    it is a statement about the robot's relationship to a map, landmarks or a
    frame somebody defined, and no localizer of any kind moves it
    (docs/sufficiency.md §5.6). This module is Layer A and may not import it.

    A `BaseFrame` says less, on purpose. It carries no `PoseSource`, because it
    claims nothing about where in a room anything is and therefore inherits no
    perceiver — it is the frame the caller is asking the question in. For every
    caller in this repository that frame is `ORIGIN_FRAME`, which is a **mounting
    fact** rather than a measurement: the arm is bolted there, and nobody sensed
    it (docs/limitations.md §9).

    So the refusal below is structural and not a type-safety courtesy.
    `BasePose` has `x`, `y` and `theta` too and would duck-type straight through
    a `getattr`, which is exactly how `StateFrame` would have got into `_vector`.
    A room-frame pose arriving here would make every envelope computed
    downstream a room-frame region wearing a Layer A tag — and *transforming a
    body-frame region by a Layer B pose* is a decision for Tier 3 of
    docs/mobile-base.md §7, made in the open, with `docs/sufficiency.md` moving
    in the same commit. It is not something a duck-type should be able to do
    quietly.

    **No field has a default**, matching `Limits` since issue #115. A frame
    nobody stated must not be indistinguishable from one somebody did.
    """

    x: float
    y: float
    theta: float

    def __post_init__(self) -> None:
        for name in ("x", "y", "theta"):
            raw = getattr(self, name)
            if isinstance(raw, (str, bytes)):
                # `float("0.5")` succeeds, which is the trap: a string carries
                # no units and no frame. Refused where the field is named.
                raise TypeError(
                    f"BaseFrame.{name} must be a number, got {raw!r}. A string "
                    "that happens to parse as one is not a coordinate somebody "
                    "stated."
                )
            try:
                value = float(raw)
            except (TypeError, ValueError) as exc:
                raise TypeError(
                    f"BaseFrame.{name} must be a number, got {raw!r}. It places "
                    "the whole arm, and something that is not a number does not "
                    "place anything."
                ) from exc
            if not math.isfinite(value):
                raise ValueError(
                    f"BaseFrame.{name} is {raw!r}, which is not finite. A "
                    "non-finite base frame propagates into every link segment "
                    "and every polygon downstream as an empty or invalid "
                    "geometry, which reads as 'no reachable area' rather than "
                    "as the fault it is."
                )
            # Frozen, so this is the only way to normalise: store a real float,
            # not a numpy scalar whose repr would reach the record differently.
            object.__setattr__(self, name, value)


#: The frame every caller in this repository passes: the arm bolted at the
#: origin, unrotated. **Not a default.** It is written out at each call site on
#: purpose, so that `grep ORIGIN_FRAME` is the list of places this repository
#: assumes a base that does not move — which is what docs/mobile-base.md §4
#: says did not exist, and what Tier 3 has to visit. Since issue #184 it is the
#: *only* statement of it: `reg.world.BASE_XY` was a room-coordinate restatement
#: of the same mounting fact, read in two places and parameterising nothing, and
#: a fact restated in a second place is a fact two places can disagree about.
ORIGIN_FRAME = BaseFrame(x=0.0, y=0.0, theta=0.0)


def _base_frame(base: BaseFrame, argname: str = "base") -> BaseFrame:
    """Accept a `BaseFrame` and nothing else — in particular not a `BasePose`.

    The whole content of the check is the `isinstance`. `reg.types.BasePose` has
    `x`, `y` and `theta`, so any structural reading of this argument would
    accept one and carry a room-frame, Layer B pose into a Layer A computation
    without anything saying so. See `BaseFrame` for why that is Tier 3's
    decision and not a duck-type's.
    """
    if not isinstance(base, BaseFrame):
        raise TypeError(
            f"{argname} must be a BaseFrame, got {type(base).__name__}. "
            "Kinematics is Layer A: the frame it measures the links from is one "
            "the caller states, not a pose read from anywhere. A "
            "`reg.types.BasePose` is refused here even though it has the same "
            "three fields — it is a room-frame pose and therefore Layer B "
            "(docs/sufficiency.md §5.6), and transforming the arm by one would "
            "produce a room-frame region wearing a Layer A tag. A bolted-down "
            "arm passes `reg.kinematics.ORIGIN_FRAME`."
        )
    return base


def _vector(value: ProprioState | np.ndarray, field: str, n: int, argname: str) -> np.ndarray:
    """Coerce a Layer A joint vector, or refuse.

    Accepts a `ProprioState` (narrowed to `field`) or a plain array-like. It
    accepts nothing else — in particular not a `StateFrame`, which also has `.q`
    and `.qd` and would therefore duck-type straight through a `getattr`,
    carrying `human_pos` into Layer A behind it.
    """
    if isinstance(value, ProprioState):
        arr = np.asarray(getattr(value, field), dtype=float)
    elif isinstance(value, (np.ndarray, list, tuple)):
        arr = np.asarray(value, dtype=float)
    else:
        raise TypeError(
            f"{argname} must be a ProprioState or an array of joint values, got "
            f"{type(value).__name__}. Kinematics is Layer A: it takes "
            "proprioception and actuation limits and nothing that names the "
            "world. If you are holding a StateFrame, call .proprio() first — "
            "that narrowing is the enforcement mechanism, not a formality."
        )

    if arr.ndim != 1:
        raise ValueError(
            f"{argname} must be one-dimensional, got shape {arr.shape}."
        )
    if arr.shape[0] != n:
        raise ValueError(
            f"{argname} has {arr.shape[0]} entries but there are {n} links. "
            "A mismatch here would be silently broadcast by numpy into a "
            "configuration nobody wrote."
        )
    if not np.all(np.isfinite(arr)):
        raise ValueError(
            f"{argname} contains a non-finite value: {arr!r}. Non-finite joint "
            "state propagates into every polygon downstream as an empty or "
            "invalid geometry, which reads as 'no reachable area' rather than "
            "as the fault it is."
        )
    return arr


def _link_lengths(limits: Limits) -> np.ndarray:
    """The link lengths, checked. Zero-length links are a fault, not a corner."""
    lengths = np.asarray(limits.link_lengths, dtype=float)
    if lengths.ndim != 1 or lengths.shape[0] == 0:
        raise ValueError(
            f"limits.link_lengths must be a non-empty 1-D array, got shape "
            f"{lengths.shape}."
        )
    if not np.all(np.isfinite(lengths)) or np.any(lengths <= 0.0):
        raise ValueError(
            f"limits.link_lengths must all be finite and strictly positive, got "
            f"{lengths!r}. A zero-length link buffers to an empty polygon, which "
            "would silently remove a piece of the robot's body from every "
            "separation and envelope computation built on this."
        )
    return lengths


def forward_kinematics(
    q: ProprioState | np.ndarray, limits: Limits, base: BaseFrame
) -> list[tuple[np.ndarray, np.ndarray]]:
    """Link segments for configuration `q`, measured from `base`.

    Returns one `(start, end)` pair per link, in base-to-tip order, each point a
    length-2 float array in `base`'s frame. `forward_kinematics(q, limits,
    base)[i][1]` is the tip of link `i`, and the last entry's end is the end
    effector. The first segment starts at `(base.x, base.y)`.

    `base` is required and has no default — see the module docstring, and
    `BaseFrame` for what it may and may not be. A bolted-down arm passes
    `ORIGIN_FRAME`, which is what every caller in this repository does.

    Pure and deterministic: same `q`, `limits` and `base` in, bit-identical
    points out.
    """
    lengths = _link_lengths(limits)
    base = _base_frame(base)
    # The base's heading is where the first link's angle is measured from, so it
    # offsets the cumulative sum rather than rotating the points afterwards.
    angles = base.theta + np.cumsum(_vector(q, "q", lengths.shape[0], "q"))

    # Cumulative sums starting at the base: point i is the tip of link i-1 and
    # the root of link i. This leading entry used to be a literal `0.0`, and
    # that literal *was* the fixed base (issue #152). At ORIGIN_FRAME the
    # arithmetic below is the identity and the results are byte-identical to
    # that version, with one stated exception: `+0.0 + -0.0` is `+0.0`, so a
    # coordinate that came out a negative zero comes out a positive one. The
    # two compare equal and nothing downstream distinguishes them; it is said
    # here rather than branched around, and
    # `tests/test_kinematics.py::test_a_negative_zero_configuration_...` is
    # where it is pinned.
    xs = np.concatenate(([base.x], base.x + np.cumsum(lengths * np.cos(angles))))
    ys = np.concatenate(([base.y], base.y + np.cumsum(lengths * np.sin(angles))))

    return [
        (np.array([xs[i], ys[i]]), np.array([xs[i + 1], ys[i + 1]]))
        for i in range(lengths.shape[0])
    ]


def link_polygons(
    q: ProprioState | np.ndarray, limits: Limits, base: BaseFrame
) -> list[Polygon]:
    """The robot's body in configuration `q`, measured from `base`: one polygon
    per link.

    `base` is required here for the same reason it is required next door, and
    not only because this is a thin wrapper: a base this function cannot express
    is a base its callers cannot use, and every consumer of the robot's *body* —
    the envelope sweep, every separation distance, the viz — comes through here
    rather than through `forward_kinematics`.

    Each link is its segment buffered by `limits.link_radius` with flat caps, so
    a link of length `l` is a rectangle of area `2 * link_radius * l`. Flat caps
    rather than round: the caps of adjacent links would otherwise overlap at
    every joint, and the union of these polygons is what the envelope sweeps.
    This under-covers the joints themselves by a half-disc — noted here because
    it is a modelling choice, not an approximation the caller can see.
    """
    radius = float(limits.link_radius)
    if not np.isfinite(radius) or radius <= 0.0:
        raise ValueError(
            f"limits.link_radius must be finite and strictly positive, got "
            f"{limits.link_radius!r}. A non-positive radius buffers each link to "
            "an empty polygon — a robot with no body, which every intersection "
            "test downstream would report as clear."
        )
    return [
        LineString([start, end]).buffer(radius, cap_style="flat")
        for start, end in forward_kinematics(q, limits, base)
    ]


def clamp_to_limits(
    q: ProprioState | np.ndarray,
    qd: ProprioState | np.ndarray,
    limits: Limits,
) -> tuple[np.ndarray, np.ndarray]:
    """Clip `(q, qd)` into the box the robot is actually capable of.

    `q` is clipped to `[q_min, q_max]` per joint; `qd` to `[-qd_max, +qd_max]`,
    `qd_max` being a magnitude bound. Returns fresh arrays and mutates nothing —
    callers hold frozen `ProprioState`s and a clamp that wrote through them would
    edit the record after the fact.

    This is the kinematic clip only. It is *not* the CLAMP verdict in
    docs/plan.md: that one compares a commanded action against a declared
    envelope and is enforcement's job, not kinematics'.
    """
    n = _link_lengths(limits).shape[0]
    q_arr = _vector(q, "q", n, "q")
    qd_arr = _vector(qd, "qd", n, "qd")

    q_min = np.asarray(limits.q_min, dtype=float)
    q_max = np.asarray(limits.q_max, dtype=float)
    qd_max = np.asarray(limits.qd_max, dtype=float)

    if np.any(q_min > q_max):
        raise ValueError(
            f"limits.q_min exceeds limits.q_max at joint(s) "
            f"{np.flatnonzero(q_min > q_max).tolist()}. np.clip would silently "
            "return q_max for those joints, i.e. a bound nobody stated."
        )
    if np.any(qd_max < 0.0):
        raise ValueError(
            f"limits.qd_max must be a non-negative magnitude bound, got "
            f"{qd_max!r}. A negative bound has no clipped value that satisfies it."
        )

    return np.clip(q_arr, q_min, q_max), np.clip(qd_arr, -qd_max, qd_max)
