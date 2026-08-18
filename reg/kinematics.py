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

Conventions
-----------
- The base is fixed at the origin, `(0, 0)`.
- Angles are cumulative: joint `i` is measured relative to link `i-1`, so link
  `i` points along `sum(q[:i+1])` in the world frame. `q = 0` is the arm fully
  extended along `+x`.
- A link is a segment; its body is that segment buffered by `link_radius` with
  flat caps, which makes the body of an `n`-link arm exactly `n` rectangles.
"""

from __future__ import annotations

import numpy as np
from shapely.geometry import LineString, Polygon

from reg.types import Limits, ProprioState

__all__ = ["forward_kinematics", "link_polygons", "clamp_to_limits"]


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
    q: ProprioState | np.ndarray, limits: Limits
) -> list[tuple[np.ndarray, np.ndarray]]:
    """Link segments for configuration `q`, base at the origin.

    Returns one `(start, end)` pair per link, in base-to-tip order, each point a
    length-2 float array in the world frame. `forward_kinematics(q, limits)[i][1]`
    is the tip of link `i`, and the last entry's end is the end effector.

    Pure and deterministic: same `q` and `limits` in, bit-identical points out.
    """
    lengths = _link_lengths(limits)
    angles = np.cumsum(_vector(q, "q", lengths.shape[0], "q"))

    # Cumulative sums with an explicit leading zero: the base joint sits at the
    # origin, so point i is the tip of link i-1 and the root of link i.
    xs = np.concatenate(([0.0], np.cumsum(lengths * np.cos(angles))))
    ys = np.concatenate(([0.0], np.cumsum(lengths * np.sin(angles))))

    return [
        (np.array([xs[i], ys[i]]), np.array([xs[i + 1], ys[i + 1]]))
        for i in range(lengths.shape[0])
    ]


def link_polygons(q: ProprioState | np.ndarray, limits: Limits) -> list[Polygon]:
    """The robot's body in configuration `q`: one polygon per link.

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
        for start, end in forward_kinematics(q, limits)
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
