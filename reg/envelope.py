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
something looser and cheaper (docs/prior-art.md §4), Minkowski-summed since
issue #163 with what the base's own actuation bounds let the vehicle do over the
same horizon. It is a **separate function** and `compute_envelope` is unchanged:
the evidence graph records the region the robot demonstrably swept, and
enforcement checks against the region it provably cannot leave. Two sets for two
jobs; collapsing them would silently change what every published envelope means.
Say "under-approximation" out loud wherever *this* polygon is reported, and
"outer" wherever that one is.

`compute_envelope` does not sweep the base and is not going to. It integrates
`q` alone, so for a robot that drives it under-covers by the base's whole
displacement — which is the *sound* direction for an inner approximation and a
fourth entry in the list below, not a defect. The set that has to grow when the
base can drive is the outer one, because that is the set a VETO rests on.

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
- The base does not move. `q` is integrated and `Limits`' four base bounds are
  not read here at all, so for a robot that drives this polygon under-covers by
  the base's displacement on top of everything above.

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

from reg.kinematics import (
    ORIGIN_FRAME,
    BaseFrame,
    _base_frame,
    clamp_to_limits,
    link_polygons,
)
from reg.types import Layer, Limits, LimitSource, ProprioState

__all__ = [
    "ARC_QUAD_SEGS",
    "MAX_OUTER_GRID_CONFIGS",
    "SUBSTEP_DT",
    "HASH_COORD_PRECISION",
    "base_motion_bounds",
    "compute_envelope",
    "envelope_area",
    "envelope_hash",
    "envelope_layer",
    "outer_envelope",
    "outer_envelope_looseness",
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


def _require_finite_float(value: object, name: str) -> float:
    """A number a bound may be computed from. Zero and negatives are fine here.

    `_require_positive_float` is the wrong check for a velocity component: `vx =
    0.0` is a base standing still and `vx = -0.4` is one reversing, both of which
    are states. What is not a state is a NaN — it would propagate through every
    comparison below as a silent False and out into a polygon.
    """
    if isinstance(value, bool) or not isinstance(
        value, (int, float, np.floating, np.integer)
    ):
        raise TypeError(f"{name} must be a number, got {value!r}.")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(
            f"{name} must be finite, got {out!r}. A NaN compares False against "
            "every bound it is tested against, so it would not be caught by the "
            "limit checks below — it would reach the geometry."
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
# WHAT THE SET IS. Issue #163 changed it, so the argument below is a rewrite and
# not an amendment. The region is now
#
#     ( the arm's swept body, measured from `base`, with the base's own yaw
#       folded into the first joint's angle )   (+)   disc(0, d_trans)
#
# where `(+)` is the Minkowski sum and `d_trans` is how far the vehicle itself
# can translate inside the horizon. For a base that cannot move — every fixture
# in this repository — `d_trans` and the yaw term are exactly zero and every line
# below reduces to the arm-only construction issue #82 shipped.
#
# WHY IT IS SOUND, IN SIX STEPS. Nothing here is a heuristic; each step
# over-covers, and the composition of over-coverings over-covers.
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
# 2. THE BASE, ANALYTICALLY AND NOT ON THE GRID. The vehicle contributes two
#    scalars over the horizon and nothing else: a translation bound `d_trans`
#    metres and a yaw bound `d_yaw` radians. Each is the *same integral as step
#    1* with `(base_v_max, base_a_max)` and `(base_omega_max, base_alpha_max)`
#    in place of a joint's pair — a magnitude bound on a double integrator under
#    a rate cap — so `d_trans <= |v0| * H + a * H^2 / 2` and is tighter than that
#    once the speed cap engages. `base_motion_bounds` computes them.
#
#    Analytically, because the alternative does not fit. Adding `(x, y, theta)`
#    to the ancestor grid of step 5 multiplies its enumeration by three more
#    dimensions and trips `MAX_OUTER_GRID_CONFIGS` on the first frame, and that
#    guard refuses rather than degrades. Minkowski summation is the composition
#    the reachability literature uses for exactly this reason — zonotopes exist
#    partly because the operation is exact and cheap on them (docs/prior-art.md
#    §24, §25) — and on a `shapely` polygon it is one `buffer`.
#
#    `base_vel` is **required** here whenever any of the four bounds is nonzero.
#    `ProprioState.base_vel is None` means *this state records no base velocity*,
#    which is a could-not-evaluate; substituting zero would compute a
#    standing-still bound for a vehicle that was driving, which is unsound in the
#    one place unsoundness is invisible. A base velocity exceeding its own bounds
#    is refused for the reason `_check_state_within_limits` refuses a joint one.
#
# 3. THE YAW FOLDS INTO THE FIRST JOINT, EXACTLY. Turning the base by `tb` about
#    the base point rotates the entire arm about that same point, and joint 0's
#    angle is measured from the base heading — so the body at base yaw `tb` with
#    joint 0 at `q0` is the identical body at yaw 0 with joint 0 at `tb + q0`.
#    The reachable set of that sum is the Minkowski sum of the two intervals,
#    `[lo0 - d_yaw, hi0 + d_yaw]`, and the base yaw is independent of the joint,
#    so the sum is exact and not merely a cover. Three consequences, each of
#    which is a decision:
#
#      * The widened interval is **not** re-clamped to `[q_min[0], q_max[0]]`. A
#        joint stop bounds the joint; it does not bound the vehicle, and clamping
#        here would delete real reach.
#      * The widening is capped at `pi` per side, which is exact — the joint's
#        own interval is never negative in width, so `pi` each way already spans
#        a full turn, and the geometry depends on the angle modulo `2*pi`. It is
#        what keeps a fast-yawing base from inflating step 5's grid without
#        limit.
#      * Widening the interval does widen that grid, at the resolution step 5
#        derives. A base that can spin far enough inside the horizon therefore
#        reaches `MAX_OUTER_GRID_CONFIGS` and is refused, which is the intended
#        answer: the guard is not raised for the base, because a construction
#        that needs it raised is the wrong construction (issue #163).
#
# 4. THE LAST JOINT, EXACTLY. With every ancestor joint fixed, the centreline of
#    link `k` sweeps exactly a circular sector: centre at the link's base joint,
#    radius `link_lengths[k]`, spanning the interval of its cumulative angle. No
#    approximation, and `_sector` renders it *circumscribed* rather than
#    inscribed, so the polygon contains the arc rather than cutting its corners.
#
# 5. THE ANCESTORS, ON A GRID PLUS A LIPSCHITZ BUFFER. Rotating joint `j` by `d`
#    moves any point the joint carries by at most `d * reach[j]`, where
#    `reach[j]` is the length of the arm from joint `j` outwards. So sampling the
#    ancestors on a grid of spacing `h_j` and dilating the result by
#    `sum_j (h_j / 2) * reach[j]` covers every configuration *between* the grid
#    nodes. The grid resolution is derived from the arm's geometry, not picked:
#    `h_j * reach[j] <= link_radius`, the same rule `reg.declare` derives its
#    declared-region grid from, restated here rather than imported so that
#    enforcement's bound does not travel through the policy's module.
#
# 6. THE BODY, THEN THE TRANSLATION. The centreline union is dilated by
#    `link_radius`, again circumscribed. That set — call it `S` — contains every
#    body the robot can present *relative to where its base started*, because
#    steps 1 and 3 cover every (yaw, joint) pair it can be in. A body point at
#    time `t` is then
#
#        p(t) = base(0) + delta(t) + R(tb(t)) . offset(q(t)),   |delta(t)| <= d_trans
#
#    and the second and third terms are covered by `S`, so `p(t)` lies in
#    `S (+) disc(0, d_trans)` — a `buffer` by `d_trans`, circumscribed like every
#    other arc here. The sum treats `delta`, `tb` and `q` as independent when one
#    trajectory couples them, which over-covers; that is the sound direction and
#    it is most of §7's looseness below.
#
#    Finally the union is intersected with the **workspace disc** about `base`,
#    of radius `sum(link_lengths) + link_radius + d_trans` — the bound this
#    replaces, with the base's own travel added to it because otherwise the
#    intersection would clip away reach the vehicle genuinely has. Intersecting
#    two sound outer bounds is sound, and for a bolted-down base it means this
#    set is never worse than `reg.enforce.computed_bound`, which matters because
#    the grid buffer in step 5 can otherwise push the rim a few centimetres past
#    a disc that was already correct.
#
#    Every step above is measured from the `BaseFrame` the caller passes, and
#    this one is where getting that wrong is silent. Steps 1-5 build the set up
#    and a mis-placed frame moves it somewhere visibly wrong; the intersection
#    *subtracts*, so a disc centred anywhere but on the base clips the true set
#    and the result still looks like a sound outer bound. That is the failure
#    docs/mobile-base.md §1 names as the worst available here, and it is why
#    `base` is required rather than defaulted (issue #162).
#
# 7. HOW LOOSE, AND WHY IT IS PUBLISHED AS LOOSE. `d_trans` is a **disc**, and a
#    differential-drive base is nonholonomic: it cannot move sideways at all, so
#    its true horizon-limited reachable set is a curved, non-convex Dubins-shaped
#    region that the disc over-covers by a wide margin. The literature that
#    computes the tighter set does it with zonotopes and polynomial zonotopes
#    (RTD, REFINE, CORA — docs/prior-art.md §23, §24), and `reg` may not: *no new
#    dependencies* is a standing rule and *an HJ reachability solver* is a stated
#    non-goal (docs/plan.md). So the looseness is a representation cost, paid
#    deliberately, and how much it costs has not been computed for this
#    construction by anyone. **The returned area is not an estimate of where the
#    robot can get**, and a caller reporting it must say so —
#    `outer_envelope_looseness(limits)` is that sentence, in a form that changes
#    when the base can drive. docs/limitations.md §10 is the entry.
#
# WHAT IT IS NOT. It is not ARMTD or ARMOUR (docs/prior-art.md §4): the joint box
# is pushed through the kinematics as an interval rather than as a zonotope, so
# this is looser than either, and it is a *kinematic* bound with no dynamics or
# torque model behind it — `qdd_max` stands in for one, and `base_a_max` and
# `base_alpha_max` stand in for a force and a torque limit the same way
# (docs/plan.md Phase 1). What it has is soundness in the direction a safety
# claim needs, which sampling can never have however many samples are drawn.
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


def _displacement_bound(
    rate0: np.ndarray,
    acc_max: np.ndarray,
    rate_max: np.ndarray,
    horizon: float,
    substep_dt: float,
) -> np.ndarray:
    """`integral_0^H min(|rate0| + acc_max * (s + dt/2), rate_max) ds`, elementwise.

    How far a magnitude-bounded double integrator can travel in `horizon`,
    starting at speed `rate0`, under acceleration bound `acc_max` and rate cap
    `rate_max`. Written once because it is used twice on different quantities:
    `reachable_joint_box` applies it per joint in radians, and
    `base_motion_bounds` applies it to the vehicle in metres and in radians.
    Two copies of this formula would be two places for the `substep_dt` term to
    drift out of one of them.

    The `dt/2` inside the integrand is the discrete-integrator correction —
    `reachable_joint_box` is where it is argued, and the argument is about a
    midpoint rule rather than about joints, so it carries over unchanged.

    Everything is a magnitude: the caller passes non-negative bounds and the
    result is the non-negative distance travelled, not a signed displacement.
    """
    speed = np.minimum(np.abs(rate0) + 0.5 * acc_max * substep_dt, rate_max)

    # The rate bound is reached at t_star and holds after it. `np.where` guards
    # the division rather than the result: an axis with acc_max == 0 never
    # accelerates, so it never reaches rate_max from below and the whole horizon
    # is spent at |rate0|.
    accelerating = acc_max > 0.0
    t_star = np.where(
        accelerating,
        (rate_max - speed) / np.where(accelerating, acc_max, 1.0),
        float(horizon),
    )
    t_star = np.clip(t_star, 0.0, horizon)
    return speed * t_star + 0.5 * acc_max * t_star**2 + rate_max * (horizon - t_star)


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
    delta = _displacement_bound(qd0, qdd_max, qd_max, horizon, substep_dt)

    lo = np.maximum(q0 - delta, np.asarray(limits.q_min, dtype=float))
    hi = np.minimum(q0 + delta, np.asarray(limits.q_max, dtype=float))
    return lo, hi


def base_motion_bounds(
    state: ProprioState,
    limits: Limits,
    horizon: float,
    substep_dt: float = SUBSTEP_DT,
) -> tuple[float, float]:
    """`(d_trans, d_yaw)`: how far the *vehicle* can move in `horizon`. Step 2.

    `d_trans` is metres and `d_yaw` is radians, and they are magnitudes: the
    base can translate at most `d_trans` in **any** direction and turn at most
    `d_yaw` either way. Both are the same integral `reachable_joint_box` takes
    per joint, with `(base_v_max, base_a_max)` and `(base_omega_max,
    base_alpha_max)` standing in for a joint's rate and acceleration pair, so
    `d_trans <= |v0| * H + base_a_max * H**2 / 2` and is smaller than that once
    the speed cap engages.

    **A bolted-down base returns `(0.0, 0.0)` exactly**, not approximately: all
    four bounds are zero, so `speed` is zero, `t_star` is the horizon and every
    term of the sum is a product with zero. That is what makes `outer_envelope`
    bit-identical to its arm-only predecessor for every fixture in this
    repository, which is the regression guard for this whole change.

    WHY THE DISC IS LOOSE, SAID HERE AS WELL AS AT THE POLYGON
    ---------------------------------------------------------
    `d_trans` bounds `hypot(vx, vy)` and says nothing about direction, so it
    describes a disc. A differential-drive base is nonholonomic and cannot move
    sideways at all, so the set it can actually reach is a curved, non-convex
    Dubins-shaped region strictly inside that disc, and by a wide margin.
    Bounding the superset is the sound direction and it is the direction this
    project can afford; the tighter construction needs zonotopes
    (docs/prior-art.md §23, §24) and therefore a dependency this project has
    refused. docs/limitations.md §10.

    Args:
        state: Layer A proprioception. `state.base_vel` is **required whenever
            any of the four base bounds is nonzero** and refused when it
            disagrees with them — see Raises.
        limits: the robot's bounds, including the base's four.
        horizon: seconds ahead. Required, no default, for the reason
            `outer_envelope` gives.
        substep_dt: the integration grid the bound must cover as well as the
            continuous system, as in `reachable_joint_box`.

    Returns:
        `(d_trans_m, d_yaw_rad)`, both non-negative.

    Raises:
        TypeError: `state` is not a `ProprioState`, or a numeric argument is not
            numeric.
        ValueError: `state.base_vel` is `None` while the base can move — a
            could-not-evaluate, because "not recorded" is not "standing still"
            — or the recorded base velocity exceeds the bounds it is measured
            against, which would make this an upper bound on a different robot.
    """
    if not isinstance(state, ProprioState):
        raise TypeError(
            f"base_motion_bounds takes a ProprioState, got "
            f"{type(state).__name__}. The base's *body-frame* velocity is Layer "
            "A and its room-frame pose is not (reg.types.BaseVelocity, "
            "reg.types.BasePose); if you hold a StateFrame, call .proprio()."
        )
    horizon = _require_positive_float(horizon, "horizon")
    substep_dt = _require_positive_float(substep_dt, "substep_dt")

    v_max = float(limits.base_v_max)
    a_max = float(limits.base_a_max)
    omega_max = float(limits.base_omega_max)
    alpha_max = float(limits.base_alpha_max)
    can_move = any(b > 0.0 for b in (v_max, a_max, omega_max, alpha_max))

    if state.base_vel is None:
        if can_move:
            raise ValueError(
                "state.base_vel is None but limits say the base can move "
                f"(base_v_max={v_max}, base_a_max={a_max}, "
                f"base_omega_max={omega_max}, base_alpha_max={alpha_max}). "
                "`None` records that this state has no base velocity in it, "
                "which is a could-not-evaluate; reading it as zero would "
                "compute a standing-still outer bound for a vehicle that was "
                "driving, and an outer bound that is too small clears "
                "declarations it should refuse while looking exactly like a "
                "sound one. Supply a BaseVelocity, or state a base that cannot "
                "move by setting all four bounds to 0.0."
            )
        return 0.0, 0.0

    vx = _require_finite_float(state.base_vel.vx, "state.base_vel.vx")
    vy = _require_finite_float(state.base_vel.vy, "state.base_vel.vy")
    omega = _require_finite_float(state.base_vel.omega, "state.base_vel.omega")

    speed = math.hypot(vx, vy)
    if speed > v_max:
        raise ValueError(
            f"state.base_vel is moving at {speed} m/s against a base_v_max of "
            f"{v_max} m/s. The displacement bound integrates min(|v0| + a*s, "
            "v_max), which is only an upper bound while |v0| <= v_max, so a "
            "state that violates its own speed limit would silently produce a "
            "bound that is too small. A state outside its own limits is a fault "
            "in whatever produced it (reg.envelope._check_state_within_limits "
            "refuses the joint-space version for the same reason)."
        )
    if abs(omega) > omega_max:
        raise ValueError(
            f"state.base_vel is turning at {abs(omega)} rad/s against a "
            f"base_omega_max of {omega_max} rad/s. Same argument as the speed "
            "bound above: the yaw bound is only an upper bound while the state "
            "satisfies the limit it is measured against."
        )

    d_trans = float(
        _displacement_bound(
            np.float64(speed),
            np.float64(a_max),
            np.float64(v_max),
            horizon,
            substep_dt,
        )
    )
    d_yaw = float(
        _displacement_bound(
            np.float64(omega),
            np.float64(alpha_max),
            np.float64(omega_max),
            horizon,
            substep_dt,
        )
    )
    return d_trans, d_yaw


#: The sentence a caller reporting a fixed-base outer set has to carry with it.
#: Every entry in this repository's artifacts is one of these.
_LOOSENESS_ARM = (
    "outer approximation: the true reachable set is inside this region and "
    "there are points inside it the robot cannot reach. Its area is an upper "
    "bound on the reachable area, never an estimate of it."
)

#: ...and the one for a base that can drive, which is a different and much
#: weaker statement. It names the nonholonomic gap explicitly, because the
#: failure this exists to prevent is a reader taking the area of a disc for the
#: area of a Dubins region.
_LOOSENESS_MOBILE = (
    _LOOSENESS_ARM
    + " The base's own motion is added as a DISC of radius base_motion_bounds()"
    " (Minkowski sum), and a nonholonomic base cannot move sideways, so this"
    " region over-covers a differential-drive vehicle by a wide and uncomputed"
    " margin. Do not read the area as where the robot can get."
    " docs/limitations.md §10."
)


def outer_envelope_looseness(limits: Limits) -> str:
    """What a caller publishing an outer set's area or radius must say about it.

    The same shape as `envelope_layer` and for the same reason: a property of
    the answer that is decided by the `Limits` it was computed from, returned as
    a value so that whoever stores the number stores the caveat with it rather
    than leaving it in a docstring nobody reading the artifact will open.

    Two answers, and the difference between them is the point. For a base that
    cannot move the region is the arm's and over-covers it by the grid buffer and
    the circumscribed arcs — real looseness, small and bounded. For a base that
    can drive it also carries a **disc** where the true set is a Dubins-shaped
    region (see the block comment above, step 7), which is looseness of a
    different order and is not quantified anywhere. A caller that printed the
    same sentence for both would be telling a reader of a mobile artifact
    something true of a fixed-base one.

    Raises:
        TypeError: `limits` is not a `Limits`.
    """
    if not isinstance(limits, Limits):
        raise TypeError(
            f"outer_envelope_looseness takes a Limits, got "
            f"{type(limits).__name__}. Which sentence is true is decided by the "
            "base bounds, so there is no answer without them."
        )
    if any(float(getattr(limits, name)) > 0.0 for name in Limits.BASE_BOUND_FIELDS):
        return _LOOSENESS_MOBILE
    return _LOOSENESS_ARM


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
    base: BaseFrame,
    substep_dt: float = SUBSTEP_DT,
) -> Polygon:
    """The region the body **cannot leave** within `horizon`. An outer bound.

    **This is an over-approximation, and it is the opposite of
    `compute_envelope`.** Every configuration the robot can reach within
    `horizon` has its body inside this polygon; there are points inside it the
    robot cannot reach. That is the direction a safety claim needs — "the
    envelope does not intersect the human" implies "the robot cannot reach the
    human" — and it is why enforcement may VETO on it. See the block comment
    above for the six steps and why each over-covers.

    **The base's own motion is in it since issue #163.** The arm's set is built
    with the vehicle's yaw bound folded into the first joint's interval and is
    then Minkowski-summed with a disc of radius `base_motion_bounds(...)[0]` —
    analytically, because gridding three more dimensions would trip
    `MAX_OUTER_GRID_CONFIGS` on the first frame (docs/mobile-base.md §3). For a
    base that cannot move all four bounds are zero, both terms are exactly zero,
    and the polygon is bit-identical to the arm-only one.

    **That disc is loose and must be reported as loose.** A nonholonomic base
    cannot move sideways, so its true reachable set is a Dubins-shaped region far
    inside the disc, and the returned area is not an estimate of where the robot
    can get. `outer_envelope_looseness(limits)` is the sentence to publish
    alongside the area or the radius; docs/limitations.md §10 is the entry.

    `compute_envelope` is untouched by this and stays the inner approximation:
    the evidence graph records the set the robot demonstrably swept, and
    enforcement checks against the set it provably cannot leave. Reporting the
    two together is the two-sided bracket — the honest answer to "how good is the
    sampled envelope", with the true reachable set between them.

    Deterministic and unseeded: there is no sampling here, so unlike
    `compute_envelope` there is nothing to seed. Same inputs, same polygon.

    Args:
        state: Layer A proprioception. A `StateFrame` is refused rather than
            narrowed, for the reason `compute_envelope` gives. Its `base_vel` is
            **required whenever the base can move** — `None` records that the
            state carries no base velocity, which is a could-not-evaluate and
            never a base standing still (`base_motion_bounds`).
        limits: the robot's kinematic and actuation bounds, the base's four
            included. Their provenance decides the layer of the answer exactly
            as it does for the inner envelope — `envelope_layer(limits)`, issue
            #84 — and a base speed cap derived from a measured separation
            distance makes the whole object `DERIVED` the same way `qd_max` does.
        horizon: seconds ahead. **Required, no default.** The bound is a
            function of it and a plausible invented horizon would produce a
            plausible invented bound, which is the one failure mode a bound
            enforcement VETOes on must not have.
        base: the frame the whole set is measured from — where the base joint
            sits and the heading the first link's angle is measured from.
            **Required, no default, and typed `BaseFrame`** (issue #162). Every
            caller in this repository passes `ORIGIN_FRAME`, which is a mounting
            fact rather than a measurement; `grep ORIGIN_FRAME` is the list of
            places this repository assumes a base that does not move. A
            `reg.types.BasePose` has the same three fields and is refused, for
            the reason `reg.kinematics._base_frame` gives: it is a room-frame,
            Layer B pose, and transforming this set by one would produce a
            room-frame region wearing a Layer A tag.

            **This argument reaches the intersected disc below, and that is why
            it may not be guessed.** The disc is an outer bound centred on the
            base; centre it anywhere else and the intersection clips away part
            of the true outer set, which is an unsound outer bound that looks
            exactly like a sound one (docs/mobile-base.md §1).
        substep_dt: the integration grid the bound must cover as well as the
            continuous system — see `reachable_joint_box` for why a numerical
            parameter appears in a physical bound at all.

    Returns:
        A single `shapely` `Polygon`, connected by construction: every link's
        swept region touches its neighbour's at their shared joint.

    Raises:
        TypeError: `state` is not a `ProprioState`, or `horizon` is not a number.
        ValueError: a bound is malformed, `state` is outside its own limits, the
            state records no base velocity for a base that can move, the
            ancestor grid exceeds `MAX_OUTER_GRID_CONFIGS`, or the union comes
            out empty or disconnected — each a could-not-evaluate, and an empty
            outer bound would read as "the robot can be nowhere", which clears
            every containment test built on it.
    """
    base = _base_frame(base)
    lo, hi = reachable_joint_box(state, limits, horizon, substep_dt)
    d_trans, d_yaw = base_motion_bounds(state, limits, horizon, substep_dt)
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

    # STEP 3. The base's yaw folds into the first joint's interval, exactly:
    # turning the vehicle by `tb` about the base point is indistinguishable from
    # adding `tb` to joint 0's angle, and the two are independent, so the
    # reachable set of the sum is the sum of the intervals. Deliberately *not*
    # re-clamped to `[q_min[0], q_max[0]]` — a joint stop bounds the joint and
    # not the vehicle — and capped at a full turn, which is exact because the
    # geometry depends on the angle modulo 2*pi and is what stops a fast-yawing
    # base from inflating the ancestor grid without limit.
    #
    # Guarded on `d_yaw > 0.0` so that a base which cannot turn leaves `lo` and
    # `hi` as the identical objects `reachable_joint_box` returned. `x - 0.0` is
    # `x` for every finite float, so this is a readability guard rather than a
    # numerical one — but the bit-identity of every fixture's outer envelope is
    # the regression guard for this whole change and it should not rest on the
    # reader recalling that.
    if n and d_yaw > 0.0:
        # Capped at pi *per side*, not at a total span of 2*pi. Both are exact —
        # the joint's own interval is non-negative in width, so a widening of pi
        # each way already spans a full turn and the geometry is 2*pi-periodic —
        # but this one is exact in floating point too. Centring the interval on
        # a total span of exactly 2*pi would leave `_sector` comparing a
        # difference of two large angles against `2*pi` and taking its
        # not-quite-a-full-turn branch on a one-ulp shortfall.
        yaw = min(d_yaw, math.pi)
        lo = lo.copy()
        hi = hi.copy()
        lo[0] -= yaw
        hi[0] += yaw

    bodies: list[Polygon] = []
    for k in range(n):
        grid, dilation = _ancestor_grid(lo, hi, reach, radius, k)
        sweeps: list[Polygon] = []
        for ancestors in grid:
            # The base of link k and the cumulative angle at it, for these
            # ancestors. Written out rather than routed through
            # `forward_kinematics` because only the k-th joint's frame is wanted
            # and the cumulative angle has to come back out with it. It starts
            # at `base` for the same reason the leading `0.0` in
            # `forward_kinematics` became one (issue #152): that literal *was*
            # the fixed base. At ORIGIN_FRAME every term below is unchanged.
            base_x, base_y, angle = base.x, base.y, base.theta
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

    region = unary_union(bodies)

    # STEP 6, the Minkowski sum. `region` above is every body the robot can
    # present relative to where its base *started*; the vehicle can then be
    # anywhere within `d_trans` of that start, in any direction, so the room-frame
    # set is `region (+) disc(0, d_trans)` — which on a polygon is one `buffer`,
    # circumscribed like every other arc here. Skipped entirely when the base
    # cannot translate, so a fixed-base envelope is not routed through a
    # zero-distance buffer that GEOS is free to re-node.
    if d_trans > 0.0:
        region = region.buffer(d_trans * _CIRCUMSCRIBE, quad_segs=ARC_QUAD_SEGS)

    # The workspace disc, circumscribed at a fine resolution: the bound this one
    # replaces, and still correct. Intersecting two sound outer bounds is sound,
    # and it keeps the rim the grid dilation adds from reaching outside a disc
    # that already held.
    #
    # `d_trans` is added to its radius because the vehicle carries the whole arm
    # with it: without that term the intersection would clip away reach the base
    # genuinely has, which is the same unsound-bound-that-looks-sound failure as
    # mis-centring it. For a bolted-down base the term is exactly 0.0 and the
    # disc is the one issue #82 shipped, so this set is still never worse than
    # `reg.enforce.computed_bound` for the robot that bound is true of.
    #
    # CENTRED ON `base`, AND THAT IS THE WHOLE DANGER OF THIS FUNCTION. Every
    # link's centreline is within `sum(lengths)` of the base joint and every
    # body point within a further `radius`, so a disc of that radius *about the
    # base* over-covers and the intersection removes nothing true. About any
    # other point it removes something true — and an outer set with a piece
    # missing clears declarations it should refuse while looking exactly like a
    # sound one. docs/mobile-base.md §1.
    disc = Point(base.x, base.y).buffer(
        (float(lengths.sum()) + radius + d_trans) * (1.0 / math.cos(math.pi / 256.0)),
        quad_segs=64,
    )
    region = region.intersection(disc)

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


def outer_radius(poly: Polygon, base: BaseFrame) -> float:
    """The furthest any point of an outer envelope lies from `base`, metres.

    The radial projection of the region — the smallest disc centred on the base
    that contains it — and the scalar the artifact retains beside its area. It is
    exact for a polygon: the greatest distance from a point over a polygon is
    attained at a vertex.

    Sound in the same direction as the region it comes from: the true reachable
    set lies inside the outer envelope, which lies inside this disc. Publish it
    with `outer_envelope_looseness(limits)` beside it — for a base that can drive
    this number is the radius of a disc over a Dubins-shaped set and a reader
    must not take it for a reach.

    `base` is **required and has no default** (issue #162). "Distance from the
    base" was previously "distance from the origin" because the two were the
    same point; they are the same point only while the base is bolted down, and
    a radius measured from a centre nobody stated is indistinguishable
    downstream from one measured from the centre a caller meant. It must be the
    frame the region was computed at — pass `outer_envelope`'s `base`, which for
    every caller in this repository is `ORIGIN_FRAME`.
    """
    base = _base_frame(base)
    region = _checked_region(poly, "outer_radius")
    coords = shapely.get_coordinates(region)
    if coords.size == 0:
        raise ValueError("outer_radius was given a geometry with no coordinates.")
    return float(np.hypot(coords[:, 0] - base.x, coords[:, 1] - base.y).max())


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

    Given an `outer_envelope` it is the opposite — an upper bound — and it is a
    loose one in a way that depends on the robot. `outer_envelope_looseness` is
    the sentence to carry with it, and for a base that can drive the sentence
    changes.
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
