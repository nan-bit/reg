"""The proprioception-only forward reachable set. Layer A.

What this computes: given where the arm is (`q`), how fast it is moving (`qd`)
and what it is capable of (`Limits`), the region of the plane its body can
occupy within `horizon` seconds. Nothing else goes in. The signature is the
enforcement — `compute_envelope` takes a `ProprioState`, which has no field
naming anything outside the robot, and this module imports neither `World` nor
`Obstacle`. `tests/test_envelope.py` fails if either changes.

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
human" implies "the robot cannot reach the human". Getting that requires the
zonotope / polynomial-zonotope machinery of ARMTD and ARMOUR (docs/prior-art.md
§4), not sampling. docs/plan.md de-scopes an outer-approximative solver
deliberately; this module is a demo of the evidence structure, and any claim
built on it inherits this limitation. Say "under-approximation" out loud
wherever this polygon is reported.

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

import numpy as np
import shapely
from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from reg.kinematics import clamp_to_limits, link_polygons
from reg.types import Limits, ProprioState

__all__ = [
    "SUBSTEP_DT",
    "HASH_COORD_PRECISION",
    "compute_envelope",
    "envelope_area",
    "envelope_hash",
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
        limits: the robot's kinematic and actuation bounds.
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
    polys: list[Polygon] = list(link_polygons(q0, limits))

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
            polys.extend(link_polygons(q, limits))

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
