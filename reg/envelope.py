"""The obstacle-independent forward reachable set. Layer A when its bounds are.

What this computes: given where the arm is (`q`), how fast it is moving (`qd`)
and what it is capable of (`Limits`), the region of the plane its body can
occupy within `horizon` seconds. Nothing else goes in. The signature is the
enforcement — `compute_envelope` takes a `ProprioState`, which has no field
naming anything outside the robot, and this module imports neither `World` nor
`Obstacle`. `tests/test_envelope.py` fails if either changes.

That enforcement covers the state and not the bounds, and the bounds are the
other input. `Limits.source` says whether they are a property of the robot or a
function of something perceived — an ISO/TS 15066 speed cap is the latter — and
`envelope_layer` turns it into the layer this region's edge is tagged with. The
geometry is identical either way; what changes is whose failure modes the answer
inherits, which is the only thing the layer tag ever meant (issue #84).

THIS IS AN UNDER-APPROXIMATION (INNER APPROXIMATION)
----------------------------------------------------
The method is sampling: a finite set of constant-acceleration control sequences
is forward-integrated and the bodies they pass through are unioned. A finite
sample can only ever *under-cover* the true reachable set, so the polygon
returned here is an **under-approximation** — the true set contains it, and
there are reachable configurations outside it.

That is the wrong direction for a safety claim. A safety guarantee needs an
**over-approximation** (outer approximation): the true reachable set must be
contained in the computed one, so that "the envelope does not intersect the
human" implies "the robot cannot reach the human". `outer_envelope` in this
module is that set (issue #82) — the joint box pushed through the kinematics as
an interval, which is ARMTD's construction with the zonotope replaced by
something looser and cheaper (docs/prior-art.md §4). It is a **separate
function** and `compute_envelope` is unchanged: the evidence graph records the
region the robot demonstrably swept, and enforcement checks against the region
it provably cannot leave. Two sets for two jobs; collapsing them would silently
change what every published envelope means. Say "under-approximation" out loud
wherever *this* polygon is reported, and "outer" wherever that one is.

Three further sources of under-coverage, none of which the caller can see from
the polygon alone:

- The body is sampled at substeps of `substep_dt`, not swept continuously.
  Motion *between* substeps is not covered. (Filling those gaps with convex
  hulls would cover a little more, but a hull can also bulge outside the true
  swept region of a rotating link, which would break the inner-approximation
  property. Under-cover deliberately rather than approximate in both
  directions.)
- Links are rectangles with flat caps (`reg.kinematics.link_polygons`), which
  under-covers each joint by a half-disc.
- Only constant accelerations are sampled. A control that switches sign inside
  the horizon can reach configurations no constant acceleration reaches.

WHAT IS AND IS NOT NEW HERE
---------------------------
An obstacle-independent reachable set is standard practice, not a contribution:
ARMTD computes the reachable set offline and independent of any obstacle and
intersects with the scene afterwards, for the same reason (the reachable set is
a property of the robot). See docs/prior-art.md §4. What `reg` claims is
elsewhere — tagging every piece of evidence with the layer it depends on.

DETERMINISM
-----------
`seed` is required to be an integer and is the only source of randomness. Same
seed, same controls, same polygon, same `envelope_hash`. The interior control
samples are drawn in one `Generator.uniform` call in a fixed order, which makes
the sample set for a larger `n_samples` a strict superset of the set for a
smaller one: raising `n_samples` can therefore only grow the envelope. That is
not a coincidence to preserve by luck — `tests/test_envelope.py` asserts it,
because an inner approximation that shrinks as sampling increases means the
union is dropping geometry.
"""

from __future__ import annotations

import hashlib
import itertools
import math

import numpy as np
import shapely
from shapely.geometry import Point, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from reg.kinematics import ORIGIN_FRAME, clamp_to_limits, link_polygons
from reg.types import Layer, Limits, LimitSource, ProprioState

__all__ = [
    "ARC_QUAD_SEGS",
    "MAX_OUTER_GRID_CONFIGS",
    "SUBSTEP_DT",
    "HASH_COORD_PRECISION",
    "compute_envelope",
    "envelope_area",
    "envelope_hash",
    "envelope_layer",
    "outer_envelope",
    "outer_radius",
    "reachable_joint_box",
]

#: Integration and body-sampling grid, seconds. 50 Hz — the frame rate the
#: scenarios are generated at (docs/plan.md, Phase 1), restated here rather than
#: imported, because importing `reg.scenarios` would pull `reg.world` into
#: Layer A. It is a keyword argument on `compute_envelope` so a caller that
#: wants a different resolution states it and it lands in the record.
SUBSTEP_DT: float = 0.02

#: Coordinate decimal places the hash is taken over. 9 places is a nanometre:
#: far below any change in a reachable set that could matter, and coarse enough
#: that last-bit floating-point noise cannot change the digest. Phase 5 uses
#: this hash to detect *material* change, so the resolution is stated here
#: rather than left implicit in whatever `to_wkb` happens to emit.
HASH_COORD_PRECISION: int = 9

#: Domain separator, so an envelope digest can never be confused with a digest
#: of anything else that ends up in the chain, and so a change to what is
#: hashed is a visible version bump rather than a silent re-baseline.
_HASH_DOMAIN = b"reg-envelope-v1\x00"


def _require_int(value: object, name: str) -> int:
    """Accept a genuine integer, refuse everything else — `None` included."""
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
        raise TypeError(
            f"{name} must be an int, got {value!r}. In particular {name}=None is "
            "not 'unspecified': for a seed it means OS entropy, and an envelope "
            "that cannot be recomputed from the record is not evidence."
        )
    return int(value)


def _require_positive_float(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, np.floating, np.integer)):
        raise TypeError(f"{name} must be a number, got {value!r}.")
    out = float(value)
    if not np.isfinite(out) or out <= 0.0:
        raise ValueError(
            f"{name} must be finite and strictly positive, got {out!r}. A "
            "non-positive value here yields an envelope of the current pose "
            "alone, which reads as 'the robot cannot move'."
        )
    return out


def _qdd_max(limits: Limits, n: int) -> np.ndarray:
    """The acceleration bound, checked. It is what bounds the whole envelope."""
    qdd_max = np.asarray(limits.qdd_max, dtype=float)
    if qdd_max.shape != (n,):
        raise ValueError(
            f"limits.qdd_max has shape {qdd_max.shape} but there are {n} links."
        )
    if not np.all(np.isfinite(qdd_max)) or np.any(qdd_max < 0.0):
        raise ValueError(
            f"limits.qdd_max must be finite and non-negative, got {qdd_max!r}. "
            "It is the bound the entire envelope derives from; a negative or "
            "non-finite entry produces a region with no physical meaning."
        )
    return qdd_max


def _control_samples(limits: Limits, n_samples: int, seed: int, n: int) -> np.ndarray:
    """`(n_samples, n)` constant accelerations: every corner, then interior draws.

    Corners first and in `itertools.product` order, so the extreme controls are
    present for any `n_samples` and their order does not depend on the seed.
    The interior samples come from a single `uniform` call, filled row-major:
    the first `m` rows of a draw of `m + k` rows are exactly the `m` rows of a
    draw of `m`, which is what makes a larger `n_samples` a superset.
    """
    qdd_max = _qdd_max(limits, n)

    corners = np.array(
        list(itertools.product(*[(-a, +a) for a in qdd_max])), dtype=float
    ).reshape(-1, n)
    n_corners = corners.shape[0]

    if n_samples < n_corners:
        raise ValueError(
            f"n_samples={n_samples} is fewer than the {n_corners} corner "
            f"controls of a {n}-joint arm (2**{n}). The corners are the extreme "
            "accelerations and therefore the extremes of the envelope; dropping "
            "some of them silently shrinks the region without any sign that it "
            f"happened. Ask for at least {n_corners} samples."
        )

    rng = np.random.default_rng(seed)
    interior = rng.uniform(-1.0, 1.0, size=(n_samples - n_corners, n)) * qdd_max
    return np.vstack((corners, interior))


def _substep_times(horizon: float, substep_dt: float) -> np.ndarray:
    """`0, dt, 2dt, ...` up to and including `horizon`.

    A fixed grid *resolution* rather than a fixed grid *count*: the times for a
    short horizon are then a prefix of the times for a long one, so a longer
    horizon samples a superset of the bodies and the envelope cannot shrink as
    the horizon grows. A fixed count would rescale every sample time and lose
    that. If `horizon` is not a whole number of substeps the final partial step
    is sampled at exactly `horizon`.
    """
    n_full = int(np.floor(horizon / substep_dt))
    times = [substep_dt * k for k in range(n_full + 1)]
    if times[-1] < horizon:
        times.append(horizon)
    return np.asarray(times, dtype=float)


def _check_state_within_limits(
    q: np.ndarray, qd: np.ndarray, limits: Limits
) -> None:
    """Refuse a state the robot's own limits say is impossible.

    Clamping the *current* state instead would be worse than useless: the
    envelope would not contain the body the robot is actually in, so it would
    not even be an under-approximation of reality, and nothing downstream could
    tell that from a legitimate small envelope. A state outside its own limits
    is a fault in whatever produced it — report it, do not absorb it.
    """
    q_min = np.asarray(limits.q_min, dtype=float)
    q_max = np.asarray(limits.q_max, dtype=float)
    qd_max = np.asarray(limits.qd_max, dtype=float)

    bad_q = np.flatnonzero((q < q_min) | (q > q_max))
    if bad_q.size:
        raise ValueError(
            f"state.q is outside limits at joint(s) {bad_q.tolist()}: "
            f"q={q[bad_q].tolist()} against [{q_min[bad_q].tolist()}, "
            f"{q_max[bad_q].tolist()}]. The envelope must contain the pose the "
            "robot is in; it cannot be computed for a pose the limits say is "
            "unreachable."
        )
    bad_qd = np.flatnonzero(np.abs(qd) > qd_max)
    if bad_qd.size:
        raise ValueError(
            f"state.qd exceeds limits.qd_max at joint(s) {bad_qd.tolist()}: "
            f"qd={qd[bad_qd].tolist()} against ±{qd_max[bad_qd].tolist()}. "
            "Integrating from a velocity the robot cannot have would produce an "
            "envelope for a different robot."
        )


def compute_envelope(
    state: ProprioState,
    limits: Limits,
    horizon: float = 0.2,
    n_samples: int = 1000,
    seed: int = 0,
    substep_dt: float = SUBSTEP_DT,
) -> Polygon:
    """The region the body can occupy within `horizon`, from proprioception alone.

    **This is an under-approximation (inner approximation).** Sampling can only
    under-cover the true forward reachable set: every configuration in the
    returned polygon is reachable, but reachable configurations exist outside
    it. A real safety claim needs an over-approximation — the zonotope methods
    of ARMTD / ARMOUR, docs/prior-art.md §4. See the module docstring for the
    other three sources of under-coverage.

    Method (docs/plan.md, Phase 2): sample `n_samples` constant-acceleration
    control sequences within `limits.qdd_max` — every combination of
    `±qdd_max` plus random interior draws — forward-integrate each on a
    `substep_dt` grid, clamping `q` to `[q_min, q_max]` and `qd` to `±qd_max`,
    take the link polygons at every substep, and union them.

    Args:
        state: Layer A proprioception. A `StateFrame` is refused rather than
            narrowed: `.proprio()` at the call site is what makes the narrowing
            visible in the caller's code.
        limits: the robot's kinematic and actuation bounds. Their provenance
            decides the layer of the answer, not of the geometry: the polygon is
            the same either way, and `envelope_layer(limits)` is what a caller
            storing it must tag it with (issue #84).
        horizon: seconds ahead. Defaults to the 200 ms of docs/plan.md Phase 2.
        n_samples: control sequences, including the `2**n` corners. Defaults to
            the middle of the 500–2000 range docs/plan.md Phase 2 states.
        seed: required to be an int; `None` is refused. Same seed, same bytes.
        substep_dt: integration and sampling resolution, seconds.

    Returns:
        A single `shapely` `Polygon`. It is connected by construction — every
        sampled trajectory starts from the current pose, so every swept body
        overlaps every other.

    Cost is linear in `n_samples * horizon / substep_dt`: the defaults union
    roughly 20 000 link rectangles and take a couple of seconds. A caller
    computing an envelope per frame should say what it can afford rather than
    inherit these numbers by accident — and record what it said.

    Raises:
        TypeError: `state` is not a `ProprioState`, or a numeric argument is
            not numeric.
        ValueError: a bound is malformed, `state` is outside its own limits,
            `n_samples` is below the corner count, or the union comes out empty
            or disconnected — each a could-not-evaluate, never a small envelope.
    """
    if not isinstance(state, ProprioState):
        raise TypeError(
            f"compute_envelope takes a ProprioState, got {type(state).__name__}. "
            "This is the Layer A boundary and it is the whole argument: the "
            "envelope may not see the world. If you are holding a StateFrame, "
            "call .proprio() — the narrowing is the enforcement, not a "
            "formality (reg/types.py)."
        )

    horizon = _require_positive_float(horizon, "horizon")
    substep_dt = _require_positive_float(substep_dt, "substep_dt")
    n_samples = _require_int(n_samples, "n_samples")
    seed = _require_int(seed, "seed")
    if n_samples <= 0:
        raise ValueError(f"n_samples must be positive, got {n_samples}.")

    # clamp_to_limits validates the shapes of q, qd and every bound and returns
    # fresh arrays. For a state inside its own limits it is the identity, and
    # _check_state_within_limits is what establishes that — the initial pose is
    # the one place a clamp would be a lie rather than a model of the hardware.
    q0, qd0 = clamp_to_limits(state, state, limits)
    _check_state_within_limits(
        np.asarray(state.q, dtype=float), np.asarray(state.qd, dtype=float), limits
    )
    n = q0.shape[0]

    qd_max = np.asarray(limits.qd_max, dtype=float)
    controls = _control_samples(limits, n_samples, seed, n)
    times = _substep_times(horizon, substep_dt)

    # The current body, once: it belongs to every trajectory, and it is what
    # makes the union connected.
    polys: list[Polygon] = list(link_polygons(q0, limits, ORIGIN_FRAME))

    for u in controls:
        q = q0.copy()
        qd = qd0.copy()
        for step in range(1, times.shape[0]):
            dt = float(times[step] - times[step - 1])
            # Mid-step average velocity, clipped: exactly the constant-
            # acceleration solution q += qd*dt + 0.5*u*dt**2 while the velocity
            # bound is slack, and never a step longer than qd_max*dt once it is
            # tight. Advancing on the pre-step velocity instead would overshoot
            # qd_max inside the step, i.e. sample a configuration this robot
            # cannot actually reach.
            q = q + np.clip(qd + 0.5 * u * dt, -qd_max, qd_max) * dt
            qd = qd + u * dt
            q, qd = clamp_to_limits(q, qd, limits)
            polys.extend(link_polygons(q, limits, ORIGIN_FRAME))

    region = unary_union(polys)

    if region.is_empty:
        raise ValueError(
            "the envelope union came out empty. That is a failed computation, "
            "not a robot that cannot move — an empty region read as an envelope "
            "clears every separation test downstream."
        )
    if not isinstance(region, Polygon):
        raise ValueError(
            f"the envelope union is a {type(region).__name__}, not a Polygon. "
            "Every sampled trajectory starts from the current pose, so the "
            "union is connected by construction; a disconnected result means "
            "the geometry is wrong, and reporting its area would hide that."
        )
    return region


# --------------------------------------------------------------------------
# THE OUTER APPROXIMATION (issue #82). A different set for a different job.
#
# `compute_envelope` above is what the *evidence graph* records: the region the
# robot demonstrably swept, an under-approximation, and it is unchanged by this
# section and must stay that way. `outer_envelope` below is what *enforcement*
# needs: a region the robot provably cannot leave within the horizon. Two sets,
# two jobs, each labelled — collapsing them would silently change what every
# published envelope means.
#
# WHY THE OUTER ONE IS SOUND, IN FOUR STEPS. Nothing here is a heuristic; each
# step over-covers, and the composition of over-coverings over-covers.
#
# 1. THE JOINT BOX. Joints are independent double integrators in configuration
#    space under a box acceleration bound, so the reachable configuration set is
#    exactly a per-joint interval:
#
#        |q_i(t) - q_i(0)| <= integral_0^H min(|qd_i(0)| + qdd_i,max * s,
#                                             qd_i,max) ds
#
#    — the inner `min` is the velocity bound, which is what keeps this from
#    degenerating to the workspace disc at the horizons this project declares
#    over (at H = 0.5 s the acceleration term alone is 2 rad on the demo arm).
#    Intersected with `[q_min, q_max]`, which the integrator respects at every
#    step (`clamp_to_limits`). Widening the box is always sound; this one is the
#    exact reachable box, so nothing is given away here at all.
#
# 2. THE LAST JOINT, EXACTLY. With every ancestor joint fixed, the centreline of
#    link `k` sweeps exactly a circular sector: centre at the link's base joint,
#    radius `link_lengths[k]`, spanning the interval of its cumulative angle. No
#    approximation, and `_sector` renders it *circumscribed* rather than
#    inscribed, so the polygon contains the arc rather than cutting its corners.
#
# 3. THE ANCESTORS, ON A GRID PLUS A LIPSCHITZ BUFFER. Rotating joint `j` by `d`
#    moves any point the joint carries by at most `d * reach[j]`, where
#    `reach[j]` is the length of the arm from joint `j` outwards. So sampling the
#    ancestors on a grid of spacing `h_j` and dilating the result by
#    `sum_j (h_j / 2) * reach[j]` covers every configuration *between* the grid
#    nodes. The grid resolution is derived from the arm's geometry, not picked:
#    `h_j * reach[j] <= link_radius`, the same rule `reg.declare` derives its
#    declared-region grid from, restated here rather than imported so that
#    enforcement's bound does not travel through the policy's module.
#
# 4. THE BODY. The centreline union is dilated by `link_radius`, again
#    circumscribed, and intersected with the **workspace disc** — the bound this
#    replaces. Intersecting two sound outer bounds is sound, and it means this
#    set is never worse than `reg.enforce.computed_bound`, which matters because
#    the grid buffer in step 3 can otherwise push the rim a few centimetres past
#    a disc that was already correct.
#
# WHAT IT IS NOT. It is not ARMTD or ARMOUR (docs/prior-art.md §4): the joint box
# is pushed through the kinematics as an interval rather than as a zonotope, so
# this is looser than either, and it is a *kinematic* bound with no dynamics or
# torque model behind it — `qdd_max` stands in for one (docs/plan.md Phase 1).
# What it has is soundness in the direction a safety claim needs, which sampling
# can never have however many samples are drawn.
# --------------------------------------------------------------------------

#: Segments per quadrant used to render every arc in the outer set, matching the
#: `quad_segs` shapely renders its own buffered arcs at. It is a *resolution*,
#: not a threshold: every arc here is circumscribed rather than inscribed, so a
#: coarser rendering only ever makes the bound looser, never unsound.
ARC_QUAD_SEGS: int = 8

#: The factor that turns an inscribed polygonal arc at `ARC_QUAD_SEGS` into a
#: circumscribed one. A chord between two points at radius `R` separated by
#: `dtheta` passes within `R * cos(dtheta / 2)` of the centre, so placing the
#: vertices at `radius / cos(dtheta / 2)` puts the whole chord outside the true
#: arc. Used for the sectors and for every `buffer` distance below, because
#: shapely's buffer is inscribed and an inscribed body is not an outer bound.
_CIRCUMSCRIBE: float = 1.0 / math.cos(math.pi / (4 * ARC_QUAD_SEGS))

#: Upper bound on the ancestor grid one link's sweep will be sampled at. A
#: resource guard, not a physical threshold — the resolution above is *derived*
#: from the geometry, so exceeding this means an arm with enough joints that the
#: product of their grids is no longer something to evaluate per declaration.
#: Breaching it is a loud refusal, never a silently coarser grid: a coarser grid
#: with the buffer computed from the resolution that was *asked for* would be an
#: unsound bound wearing a sound one's shape.
MAX_OUTER_GRID_CONFIGS: int = 50_000


def _reach(limits: Limits) -> np.ndarray:
    """`reach[i]`: the length of the arm from joint `i` outwards, in metres.

    The Lipschitz constant of step 3 above — rotating joint `i` by `d` moves any
    centreline point it carries by at most `d * reach[i]`, because no such point
    is further than `reach[i]` from the joint.
    """
    lengths = np.asarray(limits.link_lengths, dtype=float)
    return np.cumsum(lengths[::-1])[::-1]


def reachable_joint_box(
    state: ProprioState,
    limits: Limits,
    horizon: float,
    substep_dt: float = SUBSTEP_DT,
) -> tuple[np.ndarray, np.ndarray]:
    """`(lo, hi)`: the joint interval reachable within `horizon`. Step 1 above.

    For the continuous-time system this is *exact* rather than conservative:
    under a box acceleration bound and a box velocity bound the joints are
    independent double integrators, so the reachable configuration set is
    precisely this box intersected with `[q_min, q_max]`. Every claim the outer
    set makes rests on it.

    WHY `substep_dt` IS IN HERE, WHICH IS NOT OBVIOUS
    ------------------------------------------------
    The exact continuous box is **not** a bound on the trajectories this project
    actually integrates. `compute_envelope` advances `q` on the mid-step
    velocity, which is the midpoint rule; the velocity bound makes the integrand
    concave, and the midpoint rule *overestimates* the integral of a concave
    function. So a discrete trajectory can end a few ten-thousandths of a radian
    outside the exact continuous box, at the one instant the velocity bound
    engages — small, and enough to make an exact bound fail its own soundness
    test at the base joint, where the construction carries no other slack.

    Covering it costs one term. Per step the displacement is at most
    `clip(|qd0| + qdd_max * (t + substep_dt/2)) * substep_dt`, and that function
    is non-decreasing, so summing it over the grid is at most the integral of the
    same expression — which is this formula with the initial speed raised by half
    a step of acceleration. Sending `substep_dt` to zero recovers the exact
    continuous box, which is the sense in which the extra term is numerical
    rather than physical.

    Args:
        state: Layer A proprioception. Refused outright if it is outside its own
            limits — the displacement bound integrates `min(|qd0| + qdd*s,
            qd_max)`, which is only an upper bound while `|qd0| <= qd_max`, so a
            state that violates its own velocity limit would silently produce a
            box that is too *small*.
        limits: the robot's bounds.
        horizon: seconds ahead.
        substep_dt: the integration grid the bound must cover as well as the
            continuous system. Defaults to `SUBSTEP_DT`, the same grid
            `compute_envelope` defaults to; a caller integrating on a coarser one
            must say so here too, or the bound will not cover its trajectories.

    Returns:
        Two `(n,)` arrays, `lo <= hi` per joint.
    """
    if not isinstance(state, ProprioState):
        raise TypeError(
            f"reachable_joint_box takes a ProprioState, got "
            f"{type(state).__name__}. This is the Layer A boundary: the "
            "reachable set may not see the world. If you hold a StateFrame, "
            "call .proprio()."
        )
    horizon = _require_positive_float(horizon, "horizon")
    substep_dt = _require_positive_float(substep_dt, "substep_dt")

    q0 = np.asarray(state.q, dtype=float)
    qd0 = np.asarray(state.qd, dtype=float)
    n = q0.shape[0]
    qdd_max = _qdd_max(limits, n)
    _check_state_within_limits(q0, qd0, limits)

    qd_max = np.asarray(limits.qd_max, dtype=float)
    speed = np.minimum(np.abs(qd0) + 0.5 * qdd_max * substep_dt, qd_max)

    # The velocity bound is reached at t_star and holds after it. `np.where`
    # guards the division rather than the result: a joint with qdd_max == 0
    # never accelerates, so it never reaches qd_max from below and the whole
    # horizon is spent at |qd0|.
    accelerating = qdd_max > 0.0
    t_star = np.where(
        accelerating,
        (qd_max - speed) / np.where(accelerating, qdd_max, 1.0),
        float(horizon),
    )
    t_star = np.clip(t_star, 0.0, horizon)
    delta = speed * t_star + 0.5 * qdd_max * t_star**2 + qd_max * (horizon - t_star)

    lo = np.maximum(q0 - delta, np.asarray(limits.q_min, dtype=float))
    hi = np.minimum(q0 + delta, np.asarray(limits.q_max, dtype=float))
    return lo, hi


def _sector(
    cx: float, cy: float, radius: float, start: float, end: float
) -> Polygon:
    """A polygon **containing** the pie slice of `radius` from `start` to `end`.

    Circumscribed, so the returned region contains the true sector rather than
    being contained by it. A span of a full turn or more is the whole disc.
    """
    span = end - start
    if span >= 2.0 * math.pi:
        return Point(cx, cy).buffer(radius * _CIRCUMSCRIBE, quad_segs=ARC_QUAD_SEGS)
    n_seg = max(1, math.ceil(span / (math.pi / (2 * ARC_QUAD_SEGS))))
    dtheta = span / n_seg
    r = radius / math.cos(dtheta / 2.0)
    points = [(cx, cy)]
    points.extend(
        (cx + r * math.cos(start + i * dtheta), cy + r * math.sin(start + i * dtheta))
        for i in range(n_seg + 1)
    )
    return Polygon(points)


def _ancestor_grid(
    lo: np.ndarray, hi: np.ndarray, reach: np.ndarray, link_radius: float, k: int
) -> tuple[np.ndarray, float]:
    """The grid over joints `0..k-1`, and the dilation that covers between it.

    Step 3 above. `steps[j]` is chosen so `h_j * reach[j] <= link_radius`; the
    dilation returned is `sum_j (h_j / 2) * reach[j]`, computed from the spacing
    actually used rather than from the one asked for.
    """
    steps: list[int] = []
    for j in range(k):
        width = float(hi[j] - lo[j])
        steps.append(
            1 if width == 0.0 else math.ceil(width * reach[j] / link_radius) + 1
        )
    total = math.prod(steps) if steps else 1
    if total > MAX_OUTER_GRID_CONFIGS:
        raise ValueError(
            f"the outer set for link {k} would sample {total} ancestor "
            f"configurations ({' x '.join(str(s) for s in steps)}), over the "
            f"{MAX_OUTER_GRID_CONFIGS} guard. The resolution is derived from the "
            "arm's geometry, so this is an arm with more joints than this "
            "construction can carry at a resolution worth having. Refusing "
            "rather than sampling coarser: a coarser grid under a buffer sized "
            "for a finer one is an unsound bound that looks exactly like a sound "
            "one."
        )

    dilation = 0.0
    for j in range(k):
        if steps[j] > 1:
            dilation += 0.5 * float(hi[j] - lo[j]) / (steps[j] - 1) * float(reach[j])
    axes = [np.linspace(lo[j], hi[j], steps[j]) for j in range(k)]
    grid = (
        np.asarray(list(itertools.product(*axes)), dtype=float).reshape(total, k)
        if k
        else np.zeros((1, 0), dtype=float)
    )
    return grid, dilation


def outer_envelope(
    state: ProprioState,
    limits: Limits,
    horizon: float,
    substep_dt: float = SUBSTEP_DT,
) -> Polygon:
    """The region the body **cannot leave** within `horizon`. An outer bound.

    **This is an over-approximation, and it is the opposite of
    `compute_envelope`.** Every configuration the robot can reach within
    `horizon` has its body inside this polygon; there are points inside it the
    robot cannot reach. That is the direction a safety claim needs — "the
    envelope does not intersect the human" implies "the robot cannot reach the
    human" — and it is why enforcement may VETO on it. See the block comment
    above for the four steps and why each over-covers.

    `compute_envelope` is untouched by this and stays the inner approximation:
    the evidence graph records the set the robot demonstrably swept, and
    enforcement checks against the set it provably cannot leave. Reporting the
    two together is the two-sided bracket — the honest answer to "how good is the
    sampled envelope", with the true reachable set between them.

    Deterministic and unseeded: there is no sampling here, so unlike
    `compute_envelope` there is nothing to seed. Same inputs, same polygon.

    Args:
        state: Layer A proprioception. A `StateFrame` is refused rather than
            narrowed, for the reason `compute_envelope` gives.
        limits: the robot's kinematic and actuation bounds. Their provenance
            decides the layer of the answer exactly as it does for the inner
            envelope — `envelope_layer(limits)`, issue #84.
        horizon: seconds ahead. **Required, no default.** The bound is a
            function of it and a plausible invented horizon would produce a
            plausible invented bound, which is the one failure mode a bound
            enforcement VETOes on must not have.
        substep_dt: the integration grid the bound must cover as well as the
            continuous system — see `reachable_joint_box` for why a numerical
            parameter appears in a physical bound at all.

    Returns:
        A single `shapely` `Polygon`, connected by construction: every link's
        swept region touches its neighbour's at their shared joint.

    Raises:
        TypeError: `state` is not a `ProprioState`, or `horizon` is not a number.
        ValueError: a bound is malformed, `state` is outside its own limits, the
            ancestor grid exceeds `MAX_OUTER_GRID_CONFIGS`, or the union comes
            out empty or disconnected — each a could-not-evaluate, and an empty
            outer bound would read as "the robot can be nowhere", which clears
            every containment test built on it.
    """
    lo, hi = reachable_joint_box(state, limits, horizon, substep_dt)
    lengths = np.asarray(limits.link_lengths, dtype=float)
    n = lengths.shape[0]
    radius = float(limits.link_radius)
    if not math.isfinite(radius) or radius <= 0.0:
        raise ValueError(
            f"limits.link_radius must be finite and strictly positive, got "
            f"{limits.link_radius!r}. It is both the body's half-width and what "
            "the grid resolution is derived from."
        )
    reach = _reach(limits)

    bodies: list[Polygon] = []
    for k in range(n):
        grid, dilation = _ancestor_grid(lo, hi, reach, radius, k)
        sweeps: list[Polygon] = []
        for ancestors in grid:
            # The base of link k and the cumulative angle at it, for these
            # ancestors. Written out rather than routed through
            # `forward_kinematics` because only the k-th joint's frame is wanted
            # and the cumulative angle has to come back out with it.
            base_x = base_y = angle = 0.0
            for j in range(k):
                angle += float(ancestors[j])
                base_x += float(lengths[j]) * math.cos(angle)
                base_y += float(lengths[j]) * math.sin(angle)
            sweeps.append(
                _sector(
                    base_x,
                    base_y,
                    float(lengths[k]),
                    angle + float(lo[k]),
                    angle + float(hi[k]),
                )
            )
        centrelines = unary_union(sweeps)
        bodies.append(
            centrelines.buffer(
                (dilation + radius) * _CIRCUMSCRIBE, quad_segs=ARC_QUAD_SEGS
            )
        )

    # The workspace disc, circumscribed at a fine resolution: the bound this one
    # replaces, and still correct. Intersecting two sound outer bounds is sound,
    # and it keeps the rim the grid dilation adds from reaching outside a disc
    # that already held.
    disc = Point(0.0, 0.0).buffer(
        (float(lengths.sum()) + radius) * (1.0 / math.cos(math.pi / 256.0)),
        quad_segs=64,
    )
    region = unary_union(bodies).intersection(disc)

    if region.is_empty:
        raise ValueError(
            "the outer envelope came out empty. That is a failed computation, "
            "not a robot that can occupy nowhere — an empty outer bound contains "
            "no declared region at all, so every overclaim check against it fires."
        )
    if not isinstance(region, Polygon):
        raise ValueError(
            f"the outer envelope is a {type(region).__name__}, not a Polygon. "
            "Consecutive links share a joint, so the union is connected by "
            "construction; a disconnected result means the geometry is wrong."
        )
    return region


def outer_radius(poly: Polygon) -> float:
    """The furthest any point of an outer envelope lies from the base, metres.

    The radial projection of the region — the smallest disc centred on the base
    that contains it — and the scalar the artifact retains beside its area. It is
    exact for a polygon: the greatest distance from the origin over a polygon is
    attained at a vertex.

    Sound in the same direction as the region it comes from: the true reachable
    set lies inside the outer envelope, which lies inside this disc.
    """
    region = _checked_region(poly, "outer_radius")
    coords = shapely.get_coordinates(region)
    if coords.size == 0:
        raise ValueError("outer_radius was given a geometry with no coordinates.")
    return float(np.hypot(coords[:, 0], coords[:, 1]).max())


#: The layer an envelope inherits from the provenance of its bounds (issue #84).
#: Exhaustive over `LimitSource` on purpose and checked to be: a member added
#: without a layer decision must reach `envelope_layer` as a refusal, because the
#: alternative — falling through to `A` — is the mislabelling this whole
#: mechanism exists to stop.
_LAYER_BY_LIMIT_SOURCE: dict[LimitSource, Layer] = {
    LimitSource.PROPRIOCEPTIVE: "A",
    LimitSource.DERIVED: "B",
}


def envelope_layer(limits: Limits) -> Layer:
    """The layer an envelope computed from `limits` belongs to.

    `A` when the bounds are a property of the robot, `B` when they are derived
    from something perceived. The state side of the computation is Layer A by
    construction — `compute_envelope` takes a `ProprioState` and that structure
    cannot name the world — so the provenance of the bounds is the only thing
    left that decides this, and `Limits.source` is where it is written down.

    The case that makes it matter is ISO/TS 15066 speed-and-separation
    monitoring: `qd_max` capped by a measured separation distance is
    perception-derived, so the envelope integrated under it is Layer B and the
    `HAS_ENVELOPE` edge in the artifact says so. That is not a downgrade — it is
    what the edge always was, now visible to the `WHERE layer = 'B'` query Claim
    3 is (docs/sufficiency.md §7).

    Raises:
        TypeError: `limits` is not a `Limits`.
        ValueError: its `source` has no layer decision — a could-not-evaluate,
            never the permissive answer.
    """
    if not isinstance(limits, Limits):
        raise TypeError(
            f"envelope_layer takes a Limits, got {type(limits).__name__}."
        )
    try:
        return _LAYER_BY_LIMIT_SOURCE[limits.source]
    except KeyError:  # pragma: no cover - unreachable while the map is exhaustive
        raise ValueError(
            f"no layer is decided for LimitSource {limits.source!r}. Adding a "
            "limit source means deciding which layer an envelope computed from "
            "it belongs to, in reg.envelope._LAYER_BY_LIMIT_SOURCE — an "
            "undecided source must not resolve to 'A', which is the whole point "
            "of issue #84."
        ) from None


def _checked_region(poly: object, fn: str) -> Polygon:
    """A geometry an envelope answer may be derived from, or a loud refusal."""
    if not isinstance(poly, BaseGeometry):
        raise TypeError(f"{fn} takes a shapely geometry, got {type(poly).__name__}.")
    if poly.is_empty:
        raise ValueError(
            f"{fn} was given an empty geometry. An empty envelope is a "
            "could-not-evaluate: reporting zero area or a stable digest for it "
            "would let a failed computation pass as 'the robot cannot move' or "
            "as 'nothing changed'."
        )
    if not poly.is_valid:
        raise ValueError(
            f"{fn} was given an invalid geometry: "
            f"{shapely.is_valid_reason(poly)}. Area and digest of an invalid "
            "polygon are not meaningful."
        )
    return poly  # type: ignore[return-value]


def envelope_area(poly: Polygon) -> float:
    """Area of an envelope, m². Refuses an empty or invalid geometry.

    Bear in mind what the number means: it is the area of an
    under-approximation, so it is a lower bound on the area of the true
    reachable set, never an upper one.
    """
    return float(_checked_region(poly, "envelope_area").area)


def envelope_hash(poly: Polygon, precision: int = HASH_COORD_PRECISION) -> str:
    """A stable digest of an envelope: hex SHA-256, what Phase 5 diffs on.

    Stability is the point. The same polygon hashes to the same digest in any
    run and any process — the geometry is normalised to a canonical ring order
    and orientation first, and coordinates are rounded to `precision` decimal
    places (default `HASH_COORD_PRECISION`, a nanometre) so that last-bit
    floating-point noise cannot change the digest while any geometric change
    worth calling material does.

    The digest covers only the geometry. It is not a MAC and carries no
    authentication: the chain in Phase 5 is what makes an envelope
    tamper-evident, and this is the value that chain commits to.
    """
    region = _checked_region(poly, "envelope_hash")
    precision = _require_int(precision, "precision")
    if precision < 0:
        raise ValueError(f"precision must be non-negative, got {precision}.")

    canonical = shapely.to_wkt(
        shapely.normalize(region), rounding_precision=precision, trim=True
    )
    return hashlib.sha256(_HASH_DOMAIN + canonical.encode("utf-8")).hexdigest()
