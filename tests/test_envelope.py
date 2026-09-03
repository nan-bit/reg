"""The proprioception-only envelope: the boundary, the invariants, the refusals.

Three kinds of test live here, and the second two are the ones that matter.

*The boundary.* `reg.envelope` must not be able to see Layer B. That is asserted
against the module's own source, not against a comment, because the failure mode
is an agent in a hurry adding `from reg.world import Obstacle` to make one thing
work.

*The invariants.* The envelope is an under-approximation built by sampling, so
the properties worth testing are structural rather than numeric: more sampling
cannot shrink it, a longer horizon cannot shrink it, the current body is always
inside it, and the same seed gives the same bytes — in a fresh process, not just
a fresh call.

*The refusals.* Everything here that gates something downstream is fed the
condition it guards against and asserted to say no: an empty geometry, a state
outside its own limits, a sample count too small to hold the corner controls, a
`StateFrame`, `seed=None`.
"""

from __future__ import annotations

import ast
import dataclasses
import math
import pathlib
import subprocess
import sys
import textwrap

import numpy as np
import pytest
from shapely.geometry import Point, Polygon
from shapely.ops import unary_union

import reg.envelope
from reg.envelope import (
    HASH_COORD_PRECISION,
    MAX_OUTER_GRID_CONFIGS,
    SUBSTEP_DT,
    base_motion_bounds,
    compute_envelope,
    envelope_area,
    envelope_hash,
    outer_envelope,
    outer_envelope_looseness,
    outer_radius,
    reachable_joint_box,
)
from reg.kinematics import ORIGIN_FRAME, BaseFrame, link_polygons
from reg.types import (
    BaseVelocity,
    Limits,
    LimitSource,
    Obstacle,
    ProprioState,
    StateFrame,
    VelocitySource,
)

# A two-link arm, stated here rather than imported from reg.world: these tests
# are about the envelope, and coupling them to a Layer B fixture would make a
# change to the demo world look like an envelope regression.
LIMITS = Limits(
    q_min=np.array([-np.pi, -2.6]),
    q_max=np.array([np.pi, 2.6]),
    qd_max=np.array([2.0, 2.5]),
    qdd_max=np.array([8.0, 10.0]),
    link_lengths=np.array([0.5, 0.4]),
    source=LimitSource.PROPRIOCEPTIVE,
    link_radius=0.05,
    base_v_max=0.0,
    base_a_max=0.0,
    base_omega_max=0.0,
    base_alpha_max=0.0,
)
N_CORNERS = 2 ** len(LIMITS.link_lengths)

MOVING = ProprioState(t=0.0, q=np.array([0.2, 0.4]), qd=np.array([0.5, -0.3]), base_vel=None)
STATIONARY = ProprioState(t=0.0, q=np.array([0.2, 0.4]), qd=np.array([0.0, 0.0]), base_vel=None)

# Small enough to keep the suite quick; the invariants below do not depend on it.
N = 16


def body(q: ProprioState | np.ndarray) -> Polygon:
    """The robot's body in one configuration, as a single geometry."""
    return unary_union(link_polygons(q, LIMITS, ORIGIN_FRAME))


# --------------------------------------------------------------------------
# The Layer A boundary
# --------------------------------------------------------------------------


def test_envelope_module_imports_nothing_from_layer_b() -> None:
    """The signature is the enforcement; this is the test that keeps it one.

    Parsed from source rather than sniffed from the module namespace, so an
    import inside a function body is caught too.
    """
    source = pathlib.Path(reg.envelope.__file__).read_text()
    forbidden_modules = {"reg.world", "reg.scenarios"}
    forbidden_names = {"World", "Room", "Obstacle", "StateFrame"}

    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom):
            assert node.module not in forbidden_modules, (
                f"reg.envelope imports from {node.module} at line {node.lineno}. "
                "The envelope is Layer A: if it can see the world, the "
                "sufficiency argument in Claim 3 does not hold and what is left "
                "is a visualisation."
            )
            for alias in node.names:
                assert alias.name not in forbidden_names, (
                    f"reg.envelope imports {alias.name} at line {node.lineno}. "
                    "Layer B may not enter the envelope by any door."
                )
        elif isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name not in forbidden_modules, (
                    f"reg.envelope imports {alias.name} at line {node.lineno}."
                )


def test_envelope_namespace_holds_no_layer_b_type() -> None:
    """Belt to the source scan's braces: nothing Layer B ended up bound here."""
    leaked = [
        name
        for name, value in vars(reg.envelope).items()
        if isinstance(value, type) and value.__name__ in {"World", "Room", "Obstacle", "StateFrame"}
    ]
    assert not leaked, f"Layer B types bound in reg.envelope: {leaked}"


def test_compute_envelope_refuses_a_stateframe() -> None:
    """The negative test for the boundary: a mixed-layer frame is not narrowed.

    `StateFrame` has `.q` and `.qd` and would duck-type straight through, so the
    refusal has to be explicit — and it has to be a refusal rather than a silent
    `.proprio()`, because the narrowing is what a reader of the calling code
    sees.
    """
    frame = StateFrame(
        t=0.0,
        q=np.array([0.2, 0.4]),
        qd=np.array([0.0, 0.0]),
        human_pos=np.array([1.0, 0.5]),
        human_vel=np.array([0.0, 0.0]),
        base_vel=None,
        base_pose=None,
        objects=(Obstacle("obs_0", "box", 1.0, 1.0, 0.2),),
    )
    with pytest.raises(TypeError, match="ProprioState"):
        compute_envelope(frame, LIMITS, n_samples=N)  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# What the envelope contains
# --------------------------------------------------------------------------


def test_returns_a_single_polygon() -> None:
    poly = compute_envelope(MOVING, LIMITS, n_samples=N)
    assert isinstance(poly, Polygon)
    assert poly.is_valid and not poly.is_empty


def test_stationary_envelope_contains_the_current_body() -> None:
    """A robot at rest can always be where it already is."""
    poly = compute_envelope(STATIONARY, LIMITS, n_samples=N)
    now = body(STATIONARY)
    assert now.difference(poly).area == pytest.approx(0.0, abs=1e-12)
    # And it is more than the current pose: a robot at rest can still accelerate.
    assert envelope_area(poly) > now.area


def test_moving_envelope_contains_the_current_body_too() -> None:
    """Not only at rest — t=0 is on every sampled trajectory."""
    poly = compute_envelope(MOVING, LIMITS, n_samples=N)
    assert body(MOVING).difference(poly).area == pytest.approx(0.0, abs=1e-12)


def test_corner_controls_are_included() -> None:
    """Every combination of ±qdd_max must actually be in the sample.

    The expected configuration comes from the closed form
    `q(H) = q0 + qd0*H + 0.5*u*H**2`, i.e. from the physics rather than from a
    re-run of the integrator, and the horizon is short enough that no joint or
    velocity bound is active over it — so if a corner were missing from the
    sample, this body would stick out of the envelope.
    """
    horizon = 4 * SUBSTEP_DT
    poly = compute_envelope(MOVING, LIMITS, horizon=horizon, n_samples=N_CORNERS)

    qdd_max = np.asarray(LIMITS.qdd_max, dtype=float)
    for sx in (-1.0, 1.0):
        for sy in (-1.0, 1.0):
            u = np.array([sx, sy]) * qdd_max
            q_end = MOVING.q + MOVING.qd * horizon + 0.5 * u * horizon**2
            assert np.all(np.abs(MOVING.qd + u * horizon) <= LIMITS.qd_max)
            assert np.all(q_end >= LIMITS.q_min) and np.all(q_end <= LIMITS.q_max)
            outside = body(q_end).difference(poly).area
            assert outside == pytest.approx(0.0, abs=1e-12), (
                f"the body reached by the corner control {u.tolist()} is not in "
                "the envelope, so that corner was never sampled"
            )


# --------------------------------------------------------------------------
# Monotonicity — an inner approximation may not shrink
# --------------------------------------------------------------------------


def test_area_is_monotone_in_the_horizon() -> None:
    """More time cannot mean less reachable region.

    The substep grid has a fixed resolution rather than a fixed count, so the
    sample times of a short horizon are a prefix of those of a long one and the
    containment is exact; 0.13 s is in the list because it is deliberately not a
    whole number of substeps.
    """
    areas = [
        envelope_area(compute_envelope(MOVING, LIMITS, horizon=h, n_samples=N))
        for h in (0.05, 0.1, 0.13, 0.2, 0.4)
    ]
    for shorter, longer in zip(areas, areas[1:]):
        assert longer >= shorter - 1e-12, (
            f"a longer horizon gave a smaller envelope ({longer} < {shorter}). "
            "The reachable set of a superset of trajectories cannot be smaller."
        )
    assert areas[-1] > areas[0], "the envelope did not grow with the horizon at all"


def test_more_samples_never_shrinks_the_envelope() -> None:
    """The negative test for the union: an inner approximation must not shrink.

    Sample sets are nested by construction — corners first, then interior draws
    consumed from the generator in a fixed row-major order — so a larger
    `n_samples` unions a superset of bodies. If the area ever falls, the union
    is dropping geometry, which is a bug that would otherwise show up only as an
    envelope that is quietly too small: exactly the direction that makes an
    under-approximation dangerous.
    """
    counts = [N_CORNERS, 8, 16, 32, 64]
    areas = [envelope_area(compute_envelope(MOVING, LIMITS, n_samples=c)) for c in counts]
    for (c_lo, a_lo), (c_hi, a_hi) in zip(zip(counts, areas), zip(counts[1:], areas[1:])):
        assert a_hi >= a_lo - 1e-12, (
            f"n_samples={c_hi} gave a smaller envelope than n_samples={c_lo} "
            f"({a_hi} < {a_lo})"
        )
    assert areas[-1] > areas[0], "more samples covered nothing new at all"


# --------------------------------------------------------------------------
# Determinism
# --------------------------------------------------------------------------


def test_same_seed_same_bytes() -> None:
    a = compute_envelope(MOVING, LIMITS, n_samples=N, seed=7)
    b = compute_envelope(MOVING, LIMITS, n_samples=N, seed=7)
    assert envelope_hash(a) == envelope_hash(b)
    assert envelope_area(a) == envelope_area(b)


def test_a_different_seed_draws_different_interior_controls() -> None:
    """Determinism is not constancy: the seed has to actually do something."""
    a = compute_envelope(MOVING, LIMITS, n_samples=64, seed=0)
    b = compute_envelope(MOVING, LIMITS, n_samples=64, seed=1)
    assert envelope_hash(a) != envelope_hash(b)


def test_hash_is_stable_in_a_fresh_process() -> None:
    """Same seed, same bytes — across runs, which is the claim that matters.

    A digest that is only stable inside one interpreter cannot support Phase 5:
    the comparison there is between an envelope computed now and one recorded
    days ago by another process.
    """
    script = textwrap.dedent(
        """
        import numpy as np
        from reg.envelope import compute_envelope, envelope_hash
        from reg.types import Limits, LimitSource, ProprioState

        limits = Limits(
            q_min=np.array([-np.pi, -2.6]),
            q_max=np.array([np.pi, 2.6]),
            qd_max=np.array([2.0, 2.5]),
            qdd_max=np.array([8.0, 10.0]),
            link_lengths=np.array([0.5, 0.4]),
            source=LimitSource.PROPRIOCEPTIVE,
            link_radius=0.05,
            base_v_max=0.0,
            base_a_max=0.0,
            base_omega_max=0.0,
            base_alpha_max=0.0,
        )
        state = ProprioState(
            t=0.0, q=np.array([0.2, 0.4]), qd=np.array([0.5, -0.3]), base_vel=None
        )
        print(envelope_hash(compute_envelope(state, limits, n_samples=16, seed=7)))
        """
    )
    out = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=True
    )
    here = envelope_hash(compute_envelope(MOVING, LIMITS, n_samples=16, seed=7))
    assert out.stdout.strip() == here


def test_hash_ignores_representation_but_not_geometry() -> None:
    """What the digest is for: material change, and only material change."""
    square = Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])
    # Same region, different ring start vertex and winding order.
    same = Polygon([(1, 1), (1, 0), (0, 0), (0, 1)])
    assert envelope_hash(square) == envelope_hash(same)

    moved = Polygon([(0, 0), (1.5, 0), (1.5, 1), (0, 1)])
    assert envelope_hash(square) != envelope_hash(moved)

    # Below the stated coordinate resolution, nothing has changed as far as the
    # record is concerned. The resolution is a documented constant, not a
    # threshold picked here.
    jitter = 10.0 ** -(HASH_COORD_PRECISION + 3)
    nudged = Polygon([(0, 0), (1 + jitter, 0), (1 + jitter, 1), (0, 1)])
    assert envelope_hash(square) == envelope_hash(nudged)


def test_horizon_changes_the_hash() -> None:
    a = compute_envelope(MOVING, LIMITS, horizon=0.1, n_samples=N)
    b = compute_envelope(MOVING, LIMITS, horizon=0.2, n_samples=N)
    assert envelope_hash(a) != envelope_hash(b)


# --------------------------------------------------------------------------
# Refusals — a check that cannot fail is not a check
# --------------------------------------------------------------------------


def test_seed_none_is_refused() -> None:
    """`None` is not a seed. It is OS entropy wearing the word 'default'."""
    with pytest.raises(TypeError, match="seed"):
        compute_envelope(MOVING, LIMITS, n_samples=N, seed=None)  # type: ignore[arg-type]


@pytest.mark.parametrize("horizon", [0.0, -0.1, float("nan"), float("inf")])
def test_a_horizon_that_is_not_a_duration_is_refused(horizon: float) -> None:
    with pytest.raises(ValueError, match="horizon"):
        compute_envelope(MOVING, LIMITS, horizon=horizon, n_samples=N)


@pytest.mark.parametrize("substep_dt", [0.0, -0.02, float("nan")])
def test_a_substep_that_is_not_a_duration_is_refused(substep_dt: float) -> None:
    with pytest.raises(ValueError, match="substep_dt"):
        compute_envelope(MOVING, LIMITS, n_samples=N, substep_dt=substep_dt)


def test_too_few_samples_to_hold_the_corners_is_refused() -> None:
    """Silently dropping corner controls would shrink the envelope invisibly."""
    with pytest.raises(ValueError, match="corner"):
        compute_envelope(MOVING, LIMITS, n_samples=N_CORNERS - 1)


def test_a_state_outside_its_own_limits_is_refused() -> None:
    """Clamping the current pose would produce an envelope missing the robot."""
    beyond_q = ProprioState(t=0.0, q=np.array([0.2, 3.0]), qd=np.array([0.0, 0.0]), base_vel=None)
    with pytest.raises(ValueError, match="state.q is outside limits"):
        compute_envelope(beyond_q, LIMITS, n_samples=N)

    beyond_qd = ProprioState(t=0.0, q=np.array([0.2, 0.4]), qd=np.array([9.0, 0.0]), base_vel=None)
    with pytest.raises(ValueError, match="state.qd exceeds"):
        compute_envelope(beyond_qd, LIMITS, n_samples=N)


@pytest.mark.parametrize(
    "qdd_max", [np.array([-1.0, 10.0]), np.array([np.nan, 10.0])]
)
def test_an_unusable_acceleration_bound_is_refused(qdd_max: np.ndarray) -> None:
    """The whole envelope derives from this bound; a bad one is not absorbable."""
    limits = Limits(
        q_min=LIMITS.q_min,
        q_max=LIMITS.q_max,
        qd_max=LIMITS.qd_max,
        qdd_max=qdd_max,
        link_lengths=LIMITS.link_lengths,
        source=LimitSource.PROPRIOCEPTIVE,
        link_radius=LIMITS.link_radius,
        base_v_max=0.0,
        base_a_max=0.0,
        base_omega_max=0.0,
        base_alpha_max=0.0,
    )
    with pytest.raises(ValueError, match="qdd_max"):
        compute_envelope(MOVING, limits, n_samples=N)


def test_area_and_hash_refuse_an_empty_geometry() -> None:
    """could-not-evaluate must not resolve to 'zero area' or 'nothing changed'."""
    empty = Polygon()
    with pytest.raises(ValueError, match="empty"):
        envelope_area(empty)
    with pytest.raises(ValueError, match="empty"):
        envelope_hash(empty)


def test_area_and_hash_refuse_an_invalid_geometry() -> None:
    bowtie = Polygon([(0, 0), (1, 1), (1, 0), (0, 1)])
    assert not bowtie.is_valid
    with pytest.raises(ValueError, match="invalid"):
        envelope_area(bowtie)
    with pytest.raises(ValueError, match="invalid"):
        envelope_hash(bowtie)


def test_area_and_hash_refuse_something_that_is_not_a_geometry() -> None:
    with pytest.raises(TypeError):
        envelope_area(0.25)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        envelope_hash("a polygon, honest")  # type: ignore[arg-type]


def test_area_of_a_known_region_is_its_area() -> None:
    """One anchor against the unit, so a metres/millimetres slip would show."""
    assert envelope_area(Polygon([(0, 0), (2, 0), (2, 3), (0, 3)])) == pytest.approx(6.0)


# ==========================================================================
# The OUTER approximation (issue #82). A different set for a different job.
#
# `compute_envelope` above is an inner approximation and every test before this
# point is about that. The tests here are about the opposite direction, and the
# one that matters is the first: a bound that is not actually conservative is
# worse than no bound at all, because the fault it exists to catch then fails
# silently. So it is fed the extremal case — bang-bang controls, the ones that
# reach furthest — and it ships with the negative that proves the test can fail.
# ==========================================================================

QD_MAX = np.asarray(LIMITS.qd_max, dtype=float)
QDD_MAX = np.asarray(LIMITS.qdd_max, dtype=float)

#: Starting states the soundness sweep runs from. Extended and folded, at rest
#: and at the velocity bound, and one already pressed against a joint stop —
#: the clamp is part of the model the outer set claims to bound, so a state that
#: exercises it has to be in here.
SOUNDNESS_STATES = (
    ProprioState(t=0.0, q=np.array([0.0, 0.0]), qd=np.array([0.0, 0.0]), base_vel=None),
    ProprioState(t=0.0, q=np.array([0.0, 2.6]), qd=np.array([0.0, 0.0]), base_vel=None),
    ProprioState(t=0.0, q=np.array([0.2, 0.4]), qd=np.array([2.0, -2.5]), base_vel=None),
    ProprioState(t=0.0, q=np.array([-2.5, 1.0]), qd=np.array([-2.0, 2.5]), base_vel=None),
    ProprioState(t=0.0, q=np.array([1.5, -1.5]), qd=np.array([1.0, 1.2]), base_vel=None),
)


#: The same arm on a base that can drive (issue #163). Numbers a small AMR
#: could plausibly carry, stated here rather than derived from anything: the
#: point is that they are nonzero, and every assertion below is about the
#: *difference* the base makes rather than about these values.
MOBILE_LIMITS = dataclasses.replace(
    LIMITS,
    base_v_max=0.8,
    base_a_max=1.5,
    base_omega_max=1.2,
    base_alpha_max=2.5,
)


def _mobile(state: ProprioState, vx: float, vy: float, omega: float) -> ProprioState:
    """The same joint state on a base that is moving. Body frame, m/s and rad/s.

    `PROPRIOCEPTIVE` is stated rather than defaulted (issue #156): these tests
    model a base with wheel encoders, and the soundness argument they hold up is
    about the geometry, which is identical whichever provenance the rates carry.
    """
    return dataclasses.replace(
        state,
        base_vel=BaseVelocity(
            vx=vx, vy=vy, omega=omega, source=VelocitySource.PROPRIOCEPTIVE
        ),
    )


def _swept_body(
    state: ProprioState,
    control,
    horizon: float,
    limits: Limits = LIMITS,
    base_control=None,
) -> Polygon:
    """The body swept by one control law, integrated exactly as the model is.

    The integrator is `compute_envelope`'s, restated here on purpose: the outer
    set is a claim about the trajectories this project's model can produce, and a
    test that generated them some other way would be checking a different claim.
    `control(t)` returns the acceleration in force at `t`, so a control that
    switches sign inside the horizon — which no constant acceleration is — is
    expressible.

    `base_control(t)` returns `(ax, ay, alpha)` — a **body-frame** translational
    acceleration and a yaw acceleration — and drives the vehicle the arm is
    bolted to (issue #163). It is integrated on the same midpoint rule as the
    joints, for the same reason: that rule is what
    `reg.envelope._displacement_bound`'s `substep_dt` term exists to cover, so a
    test that advanced the base on its pre-step velocity would be probing a
    trajectory the bound does not claim to hold for. `None` is a bolted-down
    base, which is what every test before issue #163 assumed without saying so.
    """
    qd_max = np.asarray(limits.qd_max, dtype=float)
    q = np.asarray(state.q, dtype=float).copy()
    qd = np.asarray(state.qd, dtype=float).copy()

    x, y, theta = 0.0, 0.0, 0.0
    if base_control is None:
        vx = vy = omega = 0.0
    else:
        assert state.base_vel is not None, (
            "driving the base in a test whose state records no base velocity "
            "would assert containment for a trajectory the bound is not "
            "computed over"
        )
        vx, vy, omega = (
            state.base_vel.vx,
            state.base_vel.vy,
            state.base_vel.omega,
        )

    def frame() -> BaseFrame:
        return BaseFrame(x=x, y=y, theta=theta)

    polygons = list(link_polygons(q, limits, frame()))
    t = 0.0
    dt = SUBSTEP_DT
    while t < horizon - 1e-12:
        step = min(dt, horizon - t)
        u = control(t)
        q = q + np.clip(qd + 0.5 * u * step, -qd_max, qd_max) * step
        qd = np.clip(qd + u * step, -qd_max, qd_max)
        q = np.clip(q, limits.q_min, limits.q_max)

        if base_control is not None:
            ax, ay, alpha = base_control(t)
            # Yaw first, on the mid-step rate, then the heading it produces is
            # what the body-frame velocity is resolved through.
            omega_mid = float(
                np.clip(omega + 0.5 * alpha * step, -limits.base_omega_max, limits.base_omega_max)
            )
            theta += omega_mid * step
            omega = float(
                np.clip(omega + alpha * step, -limits.base_omega_max, limits.base_omega_max)
            )
            # The translational velocity is a magnitude bound, so it is the
            # *norm* that is clipped and not the components — `base_v_max` caps
            # `hypot(vx, vy)` (reg.types.Limits).
            mid_x, mid_y = vx + 0.5 * ax * step, vy + 0.5 * ay * step
            mid_x, mid_y = _clip_norm(mid_x, mid_y, limits.base_v_max)
            x += (mid_x * math.cos(theta) - mid_y * math.sin(theta)) * step
            y += (mid_x * math.sin(theta) + mid_y * math.cos(theta)) * step
            vx, vy = _clip_norm(vx + ax * step, vy + ay * step, limits.base_v_max)

        polygons.extend(link_polygons(q, limits, frame()))
        t += step
    return unary_union(polygons)


def _clip_norm(x: float, y: float, cap: float) -> tuple[float, float]:
    """`(x, y)` scaled down to length `cap` if it is longer. Direction preserved."""
    norm = math.hypot(x, y)
    if norm <= cap or norm == 0.0:
        return float(x), float(y)
    return float(x) * cap / norm, float(y) * cap / norm


def _bang_bang_base_controls(seed: int, n: int, limits: Limits = MOBILE_LIMITS):
    """Saturated base accelerations with a fixed direction and a yaw sign.

    The extremal controls for the vehicle, matching `_bang_bang_controls` for
    the joints: a translational acceleration at `base_a_max` in a drawn
    direction and a yaw acceleration at `±base_alpha_max`. Held constant through
    the horizon rather than switched, because for the base the furthest points
    are reached by driving straight and the bound is a magnitude bound in any
    case — a switching base travels strictly less far.
    """
    rng = np.random.default_rng(seed)
    for _ in range(n):
        heading = float(rng.uniform(0.0, 2.0 * math.pi))
        sign = float(rng.choice((-1.0, 1.0)))
        ax = limits.base_a_max * math.cos(heading)
        ay = limits.base_a_max * math.sin(heading)
        alpha = sign * limits.base_alpha_max

        def base_control(t: float, ax=ax, ay=ay, alpha=alpha):
            return ax, ay, alpha

        yield base_control


def _bang_bang_controls(horizon: float, seed: int, n: int):
    """Controls saturated at `±qdd_max` throughout, with switching times drawn.

    Bang-bang is the extremal case for a double integrator: the configurations
    furthest from the start are reached by controls that are always saturated,
    and the ones that get *around* an obstacle in configuration space are the
    ones that switch. Both are here; the zero-switch members are the corner
    controls `compute_envelope` samples.
    """
    rng = np.random.default_rng(seed)
    for _ in range(n):
        n_switch = int(rng.integers(0, 4))
        times = np.sort(rng.uniform(0.0, horizon, size=n_switch))
        signs = rng.choice((-1.0, 1.0), size=(n_switch + 1, QDD_MAX.shape[0]))

        def control(t: float, times=times, signs=signs) -> np.ndarray:
            return signs[int(np.searchsorted(times, t, side="right"))] * QDD_MAX

        yield control


@pytest.mark.parametrize("horizon", (0.05, 0.2, 0.5))
def test_no_bang_bang_trajectory_escapes_the_outer_envelope(horizon: float) -> None:
    """**The criterion that matters.** Everything else in this section is plumbing.

    If a reachable body can lie outside this region then the region is not an
    outer bound, `envelope_overclaim` can VETO a declaration the robot could have
    honoured, and the whole point of computing it is gone. Asserted as *exact*
    containment rather than within a tolerance: the construction is
    circumscribed at every step precisely so that no tolerance is needed here.

    **The base is driven too since issue #163, and since issue #164 this test is
    load-bearing rather than merely good.** `reg.enforce.computed_bound` is
    finite only because the base is bolted down (docs/mobile-base.md §1), so it
    now refuses a `Limits` whose base bounds are nonzero and
    `reg.enforce.horizon_bound` rests on the outer envelope alone for that
    robot: the workspace disc is no longer available as a floor, and this test
    is the *only* thing holding every mobile VETO up. The mobile half runs the
    same joint-space bang-bang controls with the vehicle saturating its own
    translational and yaw accelerations underneath them.
    """
    for seed, state in enumerate(SOUNDNESS_STATES):
        outer = outer_envelope(state, LIMITS, horizon, ORIGIN_FRAME)
        for control in _bang_bang_controls(horizon, seed=seed, n=12):
            escape = _swept_body(state, control, horizon).difference(outer)
            assert escape.is_empty, (
                f"q={state.q}, qd={state.qd}, horizon={horizon}: a bang-bang "
                f"trajectory left {escape.area:.3e} m^2 of body outside the "
                "outer envelope. The bound is not conservative, so every "
                "overclaim verdict built on it is an accusation about a "
                "declaration the robot could have kept."
            )


@pytest.mark.parametrize("horizon", (0.05, 0.2, 0.5))
def test_no_bang_bang_trajectory_escapes_the_outer_envelope_with_a_driven_base(
    horizon: float,
) -> None:
    """The same criterion for a robot that drives (issue #163).

    Joints saturated by `_bang_bang_controls` *and* the vehicle saturating
    `base_a_max` in a drawn direction and `±base_alpha_max` in yaw, integrated
    on the same midpoint rule the bound's `substep_dt` term is derived for. The
    base starts at a range of velocities including the speed bound itself, so
    the `min(|v0| + a*s, v_max)` cap in `base_motion_bounds` is exercised rather
    than assumed.

    A failure here means the Minkowski sum does not cover the vehicle — which is
    the same silent unsoundness `outer_envelope`'s block comment names, one level
    up: the region would still look exactly like a sound outer bound.
    """
    starts = ((0.0, 0.0, 0.0), (0.8, 0.0, 1.2), (-0.4, 0.3, -0.5), (0.0, 0.0, 1.2))
    for seed, state in enumerate(SOUNDNESS_STATES):
        for vx, vy, omega in starts:
            mobile = _mobile(state, vx, vy, omega)
            outer = outer_envelope(mobile, MOBILE_LIMITS, horizon, ORIGIN_FRAME)
            joint_controls = list(_bang_bang_controls(horizon, seed=seed, n=6))
            base_controls = list(_bang_bang_base_controls(seed=seed, n=6))
            for control, base_control in zip(joint_controls, base_controls):
                swept = _swept_body(
                    mobile, control, horizon, MOBILE_LIMITS, base_control
                )
                escape = swept.difference(outer)
                assert escape.is_empty, (
                    f"q={state.q}, qd={state.qd}, base_vel=({vx}, {vy}, "
                    f"{omega}), horizon={horizon}: a bang-bang trajectory left "
                    f"{escape.area:.3e} m^2 of body outside the outer envelope "
                    "of a driven base. The Minkowski sum does not cover the "
                    "vehicle, so the bound is not an outer bound at all."
                )


def test_a_shrunk_outer_bound_does_not_survive_the_soundness_test() -> None:
    """The negative. A test that only ever passes proves nothing about the bound.

    Erodes the outer envelope by a millimetre — far less than the slack the
    construction carries — and asserts that some bang-bang trajectory then
    escapes it. If this fails, the test above is not measuring containment and
    would go on passing for a bound with a hole in it.
    """
    horizon = 0.2
    state = SOUNDNESS_STATES[2]
    shrunk = outer_envelope(state, LIMITS, horizon, ORIGIN_FRAME).buffer(-0.001)
    escaped = any(
        not _swept_body(state, control, horizon).difference(shrunk).is_empty
        for control in _bang_bang_controls(horizon, seed=0, n=12)
    )
    assert escaped, (
        "no trajectory escaped a bound that had been eroded by a millimetre, so "
        "the soundness test above cannot distinguish an outer bound from a "
        "region that merely looks like one."
    )


def test_an_outer_bound_that_forgot_the_base_does_not_survive_the_mobile_test() -> None:
    """The negative for the mobile half, and it is the one that would have shipped.

    The failure this guards is not a subtly eroded polygon — it is the obvious
    one: computing the arm's outer set and never reading the base's bounds at
    all, which is exactly what this module did before issue #163 and which
    produces a perfectly valid-looking region. Fed the *fixed-base* bound and a
    driven base, some trajectory must escape. If none does, the mobile test
    above would go on passing for a construction that ignores the vehicle.
    """
    horizon = 0.2
    state = _mobile(SOUNDNESS_STATES[2], 0.8, 0.0, 0.0)
    # The arm-only bound is computed from the arm-only `Limits`, and therefore
    # from a state that records no base velocity — a driving state is refused
    # against zero bounds, which is a separate and correct refusal.
    arm_only = outer_envelope(SOUNDNESS_STATES[2], LIMITS, horizon, ORIGIN_FRAME)
    escaped = any(
        not _swept_body(state, control, horizon, MOBILE_LIMITS, base_control)
        .difference(arm_only)
        .is_empty
        for control, base_control in zip(
            _bang_bang_controls(horizon, seed=0, n=6),
            _bang_bang_base_controls(seed=0, n=6),
        )
    )
    assert escaped, (
        "a driven base escaped no part of the arm-only outer bound, so the "
        "mobile soundness test cannot tell a construction that reads the base "
        "bounds from one that ignores them."
    )


def test_the_sampled_envelope_is_inside_the_outer_one() -> None:
    """The two-sided bracket: inner ⊆ true reachable set ⊆ outer.

    The inner set is what the evidence graph records and the outer one is what
    enforcement checks against, so this is the relationship that makes reporting
    both of them an *answer* — "how good is the sampled envelope" — rather than
    two unrelated numbers.
    """
    for state in SOUNDNESS_STATES:
        inner = compute_envelope(state, LIMITS, horizon=0.2, n_samples=N, seed=0)
        outer = outer_envelope(state, LIMITS, 0.2, ORIGIN_FRAME)
        assert inner.difference(outer).is_empty, (
            f"q={state.q}: the sampled envelope reaches outside the outer bound, "
            "so one of the two is wrong about the same robot."
        )
        assert envelope_area(inner) <= envelope_area(outer)


def test_the_outer_envelope_never_exceeds_the_workspace_disc() -> None:
    """It is floored by the bound it tightens, so it can never be the worse one.

    **For a base that cannot move**, which `LIMITS` is and every fixture here is.
    A driven base carries the disc with it — `outer_envelope` adds the vehicle's
    translation to the disc's radius (issue #163) — and there is then no
    `computed_bound` to compare against at all, because it refuses (issue #164).
    So this is a fixed-base property asserted on a fixed-base robot, and the
    arithmetic below is spelled out rather than called through `computed_bound`
    for exactly that reason.

    Up to the rendering: the region is intersected with a *polygon* that
    circumscribes the disc, and a circumscribed polygon exceeds its circle by
    `1 / cos(pi / (4 * quad_segs)) - 1`, well under a tenth of a millimetre at
    the resolution used. `reg.enforce.horizon_bound` takes the exact minimum
    with `computed_bound` on top of this for such a robot, so no check ever sees
    even that much.
    """
    disc = float(np.sum(LIMITS.link_lengths) + LIMITS.link_radius)
    for state in SOUNDNESS_STATES:
        for horizon in (0.05, 0.5, 5.0):
            radius = outer_radius(
                outer_envelope(state, LIMITS, horizon, ORIGIN_FRAME), ORIGIN_FRAME
            )
            assert radius <= disc * 1.001, (
                f"q={state.q}, horizon={horizon}: the outer envelope reaches "
                f"{radius} m, past the {disc} m workspace disc. Tightening a "
                "bound must not be able to loosen it."
            )


def test_a_folded_arm_is_bounded_well_inside_the_workspace_disc() -> None:
    """The whole point: the bound has the state and the horizon in it.

    A workspace disc is the same scalar at every frame of every run, which is
    why `envelope_overclaim` could only ever fire on a declaration exceeding the
    entire workspace (issue #82). This asserts the gap is genuinely closed for a
    pose the arm cannot straighten out of in time — not merely that the number
    is different.
    """
    disc = float(np.sum(LIMITS.link_lengths) + LIMITS.link_radius)
    folded = ProprioState(t=0.0, q=np.array([0.0, 2.6]), qd=np.array([0.0, 0.0]), base_vel=None)
    radius = outer_radius(outer_envelope(folded, LIMITS, 0.5, ORIGIN_FRAME), ORIGIN_FRAME)
    assert radius < 0.8 * disc, (
        f"a folded arm at rest is bounded at {radius} m against a {disc} m "
        "workspace disc; if these are close the tightening buys nothing."
    )


def test_the_outer_envelope_is_monotone_in_the_horizon() -> None:
    """More time cannot mean less reach. A shrinking bound is losing geometry.

    Asserted on area and radius rather than as set containment, and the
    difference is worth stating: the ancestor grid's resolution is derived from
    the *width of the joint box*, so two horizons are covered at two
    resolutions and their polygons are not nested even though the reachable sets
    they bound are. Each is separately sound — that is what the bang-bang test
    above establishes — and a bound that got *smaller* with more time would mean
    the construction was losing geometry, which is what this catches.
    """
    for state in SOUNDNESS_STATES:
        regions = [
            outer_envelope(state, LIMITS, h, ORIGIN_FRAME)
            for h in (0.05, 0.1, 0.2, 0.4, 0.5)
        ]
        areas = [envelope_area(region) for region in regions]
        radii = [outer_radius(region, ORIGIN_FRAME) for region in regions]
        assert areas == sorted(areas), f"q={state.q}: areas {areas} are not monotone"
        assert radii == sorted(radii), f"q={state.q}: radii {radii} are not monotone"


def test_the_outer_envelope_is_deterministic_and_unseeded() -> None:
    """No sampling, so nothing to seed — and the same inputs give the same bytes."""
    state = SOUNDNESS_STATES[0]
    first = outer_envelope(state, LIMITS, 0.2, ORIGIN_FRAME)
    second = outer_envelope(state, LIMITS, 0.2, ORIGIN_FRAME)
    assert envelope_hash(first) == envelope_hash(second)


def test_the_reachable_joint_box_contains_every_trajectory_it_bounds() -> None:
    """Step 1 of the construction, checked on its own.

    Everything the outer set claims rests on this box, so it is asserted
    directly rather than only through the geometry it produces — a box that was
    too small would still yield a plausible-looking polygon.
    """
    horizon = 0.2
    for state in SOUNDNESS_STATES:
        lo, hi = reachable_joint_box(state, LIMITS, horizon)
        for control in _bang_bang_controls(horizon, seed=0, n=8):
            q = np.asarray(state.q, dtype=float).copy()
            qd = np.asarray(state.qd, dtype=float).copy()
            t = 0.0
            while t < horizon - 1e-12:
                step = min(SUBSTEP_DT, horizon - t)
                u = control(t)
                q = q + np.clip(qd + 0.5 * u * step, -QD_MAX, QD_MAX) * step
                qd = np.clip(qd + u * step, -QD_MAX, QD_MAX)
                q = np.clip(q, LIMITS.q_min, LIMITS.q_max)
                assert np.all(q >= lo - 1e-12) and np.all(q <= hi + 1e-12), (
                    f"q={q} left the reachable joint box [{lo}, {hi}] at t={t}."
                )
                t += step


def test_outer_envelope_refuses_a_stateframe() -> None:
    """The Layer A boundary holds for the outer set exactly as for the inner one."""
    frame = StateFrame(
        t=0.0,
        q=np.array([0.2, 0.4]),
        qd=np.array([0.0, 0.0]),
        human_pos=np.array([1.0, 1.0]),
        human_vel=np.array([0.0, 0.0]),
        base_vel=None,
        base_pose=None,
        objects=(Obstacle(entity_id="e", kind="crate", cx=1.0, cy=1.0, radius=0.2),),
    )
    with pytest.raises(TypeError, match="ProprioState"):
        outer_envelope(frame, LIMITS, 0.2, ORIGIN_FRAME)  # type: ignore[arg-type]


@pytest.mark.parametrize("horizon", (0.0, -0.1, float("nan"), float("inf")))
def test_an_outer_horizon_that_is_not_a_duration_is_refused(horizon: float) -> None:
    with pytest.raises(ValueError):
        outer_envelope(STATIONARY, LIMITS, horizon, ORIGIN_FRAME)


def test_an_outer_horizon_that_is_none_is_refused() -> None:
    """No default, and `None` is not one either: the bound is a function of it."""
    with pytest.raises(TypeError):
        outer_envelope(STATIONARY, LIMITS, None, ORIGIN_FRAME)  # type: ignore[arg-type]


def test_a_state_outside_its_own_limits_is_refused_by_the_outer_set() -> None:
    """The displacement bound assumes `|qd| <= qd_max`; without it, it is too small.

    This is the one refusal in this section that is about soundness rather than
    hygiene. Integrating `min(|qd0| + qdd*s, qd_max)` from a state that already
    exceeds `qd_max` under-counts the displacement, so the box — and every
    polygon built on it — would come out too small, in the direction that clears
    declarations it should refuse.
    """
    too_fast = ProprioState(t=0.0, q=np.array([0.2, 0.4]), qd=np.array([9.0, 0.0]), base_vel=None)
    with pytest.raises(ValueError, match="qd_max"):
        outer_envelope(too_fast, LIMITS, 0.2, ORIGIN_FRAME)
    with pytest.raises(ValueError, match="qd_max"):
        reachable_joint_box(too_fast, LIMITS, 0.2)


def test_an_ancestor_grid_too_large_to_evaluate_is_refused() -> None:
    """A resource guard that refuses rather than silently sampling coarser.

    A coarser grid under a dilation sized for a finer one is an unsound bound
    wearing a sound one's shape, so the guard must not degrade into one.
    """
    many = 8
    long_arm = Limits(
        q_min=np.full(many, -np.pi),
        q_max=np.full(many, np.pi),
        qd_max=np.full(many, 3.0),
        qdd_max=np.full(many, 10.0),
        link_lengths=np.full(many, 0.5),
        source=LimitSource.PROPRIOCEPTIVE,
        link_radius=0.05,
        base_v_max=0.0,
        base_a_max=0.0,
        base_omega_max=0.0,
        base_alpha_max=0.0,
    )
    state = ProprioState(t=0.0, q=np.zeros(many), qd=np.zeros(many), base_vel=None)
    with pytest.raises(ValueError, match=str(reg.envelope.MAX_OUTER_GRID_CONFIGS)):
        outer_envelope(state, long_arm, 0.5, ORIGIN_FRAME)


def test_outer_radius_refuses_what_it_cannot_measure() -> None:
    with pytest.raises(ValueError, match="empty"):
        outer_radius(Polygon(), ORIGIN_FRAME)
    with pytest.raises(TypeError):
        outer_radius(0.95, ORIGIN_FRAME)  # type: ignore[arg-type]


def test_outer_radius_is_the_furthest_vertex() -> None:
    """Exact for a polygon: the maximum of a convex function is at a vertex."""
    square = Polygon([(0, 0), (3, 0), (3, 4), (0, 4)])
    assert outer_radius(square, ORIGIN_FRAME) == pytest.approx(5.0)


# --------------------------------------------------------------------------
# The base frame the outer set is measured from (issue #162)
#
# `outer_envelope` and `outer_radius` took the base from an implicit origin
# until this change: `Point(0.0, 0.0)` for the disc the set is intersected with,
# and `hypot(x, y)` for the radius. Both now take a `BaseFrame` and nothing in
# this repository has become mobile — every caller passes `ORIGIN_FRAME`.
#
# That makes this a refactor, and a refactor is only one if the numbers do not
# move. The table below is the pin, and the two tests after it are what stop the
# argument from being a rename: a required argument that is *ignored* passes
# every test a refactor would otherwise ship with.
# --------------------------------------------------------------------------

#: The demo world's limits, imported rather than restated for this section only.
#: Everything above deliberately uses the local `LIMITS` so that a change to the
#: fixture cannot look like an envelope regression. Here the coupling is the
#: point: this section asserts that *the published figures did not move*, and
#: the published figures are computed from these numbers. If the demo world's
#: limits change, this table is stale and must fail rather than quietly track it.
from reg.world import LIMITS as DEMO_LIMITS  # noqa: E402

#: `(q, qd, horizon, outer_radius, area)` — every value a `float.hex()` string,
#: computed on the commit *before* the base became an argument, with
#: `substep_dt` left at `SUBSTEP_DT`. Hex float literals rather than decimals
#: because the claim is bit-identity: a table compared with a tolerance agrees
#: with anything, and re-running the new code to regenerate this would make it
#: agree with whatever the code does. `outer_radius` and `area` are the two
#: scalars `reg.graph` retains per frame (issue #82), so between them they are
#: what any artifact built from this function would show.
DEMO_WORLD_OUTER_BEFORE = (
    (
        ("0x0.0p+0", "0x0.0p+0"),
        ("0x0.0p+0", "0x0.0p+0"),
        "0x1.999999999999ap-3",
        "0x1.e66fc6d6a26bcp-1",
        "0x1.4ba3994a903fbp-2",
    ),
    (
        ("0x1.999999999999ap-3", "0x1.999999999999ap-2"),
        ("0x1.0000000000000p-1", "-0x1.3333333333333p-2"),
        "0x1.999999999999ap-3",
        "0x1.e66fc6d6a26bcp-1",
        "0x1.b8725f7bff37fp-2",
    ),
    (
        ("0x1.999999999999ap-3", "0x1.999999999999ap-2"),
        ("0x0.0p+0", "0x0.0p+0"),
        "0x1.0000000000000p-1",
        "0x1.e66fc6d6a26bcp-1",
        "0x1.05d1db54c7681p+0",
    ),
    (
        ("-0x1.3333333333333p+1", "0x1.4cccccccccccdp+1"),
        ("-0x1.0000000000000p+0", "0x1.999999999999ap-1"),
        "0x1.3333333333333p-2",
        "0x1.277305423816ep-1",
        "0x1.866ba2e8e9b6bp-2",
    ),
    (
        ("0x1.921fb54442d18p+0", "-0x1.3333333333333p+0"),
        ("0x1.0000000000000p+1", "0x1.4000000000000p+1"),
        "0x1.999999999999ap-2",
        "0x1.e66fc6d6a26bcp-1",
        "0x1.10413935edf3fp+0",
    ),
)


def _state_from_hex(q_hex: tuple[str, str], qd_hex: tuple[str, str]) -> ProprioState:
    return ProprioState(
        t=0.0,
        q=np.array([float.fromhex(v) for v in q_hex]),
        qd=np.array([float.fromhex(v) for v in qd_hex]),
        base_vel=None,
    )


@pytest.mark.parametrize(
    "q_hex,qd_hex,horizon_hex,radius_hex,area_hex", DEMO_WORLD_OUTER_BEFORE
)
def test_the_outer_set_at_the_origin_is_bit_identical_to_before_the_base_moved(
    q_hex: tuple[str, str],
    qd_hex: tuple[str, str],
    horizon_hex: str,
    radius_hex: str,
    area_hex: str,
) -> None:
    """No published figure moves, checked at the source of the ones that could.

    Every `outer_area_m2` and `outer_radius_m` in every artifact, and the bound
    `reg.enforce.horizon_bound` VETOes on, are these two numbers. "Did not
    change" has to mean the bytes: a one-ulp drift in the intersected disc would
    move an area in its last digit and nothing else here would say so.

    **This table now pins two changes, not one.** Issue #162 made the base an
    argument; issue #163 put the vehicle's own motion into the set. The demo
    world states `base_v_max = base_a_max = base_omega_max = base_alpha_max =
    0.0`, so `reg.envelope.base_motion_bounds` returns `(0.0, 0.0)` and both new
    terms are skipped rather than applied as zero — which is the difference
    between these hex digits holding and drifting, because `buffer(0.0)` re-nodes
    a ring in GEOS and does not return it unchanged. That makes this table the
    regression guard for the whole mobile tier, and it is why it is checked with
    `.hex()` rather than with `pytest.approx`.
    """
    state = _state_from_hex(q_hex, qd_hex)
    region = outer_envelope(
        state, DEMO_LIMITS, float.fromhex(horizon_hex), ORIGIN_FRAME
    )

    for got, expected_hex, name in (
        (outer_radius(region, ORIGIN_FRAME), radius_hex, "outer_radius"),
        (region.area, area_hex, "area"),
    ):
        expected = float.fromhex(expected_hex)
        assert got.hex() == expected.hex(), (
            f"{name} moved: got {got!r} ({got.hex()}), the commit before the "
            f"base became an argument gave {expected!r} ({expected_hex})."
        )


def test_a_base_a_millimetre_away_moves_the_outer_set_by_exactly_that_much() -> None:
    """**THE NEGATIVE for the table above**, and the point of issue #162.

    A required argument that is accepted and then ignored passes the bit-identity
    table, passes every existing test, and leaves the change a rename across nine
    files. So the argument is fed a base one millimetre from the origin — small
    enough that a tolerance-based check would wave it through — and the returned
    region is required to be the origin region *translated by exactly that*:
    different from it, and identical to it once translated back.
    """
    from shapely.affinity import translate

    state = _state_from_hex(*DEMO_WORLD_OUTER_BEFORE[1][:2])
    at_origin = outer_envelope(state, DEMO_LIMITS, 0.2, ORIGIN_FRAME)
    moved = outer_envelope(
        state, DEMO_LIMITS, 0.2, BaseFrame(x=0.001, y=0.0, theta=0.0)
    )

    assert at_origin.symmetric_difference(moved).area > 1e-6, (
        "a base a millimetre away returned the same region, so `base` is "
        "accepted and ignored and this change is a rename."
    )
    assert at_origin.symmetric_difference(
        translate(moved, xoff=-0.001)
    ).area < 1e-12, (
        "the region moved, but not by the millimetre it was given — so some "
        "term of the construction is still measured from the origin."
    )


def test_the_radius_is_measured_from_the_base_it_is_given() -> None:
    """The same negative for `outer_radius`, which has its own origin to lose.

    Two halves, and both are needed. *Exact*: a 3-4-5 square is 5 m from the
    origin, and a base a millimetre away **along that diagonal** puts it at
    exactly 5.001 m — a golden value that is exact arithmetic rather than a
    rounded observation. *Consistent*: the outer set of a base-frame arm is the
    same region rigidly moved, so its radius about its own base is unchanged,
    while its radius about the origin is not. A `base` ignored here fails the
    first; a `base` honoured in `outer_envelope` and dropped in `outer_radius`
    fails the second, and that pair is the live failure mode.
    """
    square = Polygon([(0, 0), (3, 0), (3, 4), (0, 4)])
    # (-0.0006, -0.0008) is 1 mm from the origin, directly away from (3, 4).
    assert outer_radius(
        square, BaseFrame(x=-0.0006, y=-0.0008, theta=0.0)
    ) == pytest.approx(5.001, abs=1e-12)

    state = _state_from_hex(*DEMO_WORLD_OUTER_BEFORE[1][:2])
    base = BaseFrame(x=0.001, y=0.0, theta=0.0)
    at_origin = outer_envelope(state, DEMO_LIMITS, 0.2, ORIGIN_FRAME)
    moved = outer_envelope(state, DEMO_LIMITS, 0.2, base)

    assert outer_radius(moved, base) == pytest.approx(
        outer_radius(at_origin, ORIGIN_FRAME), abs=1e-12
    )
    assert outer_radius(moved, ORIGIN_FRAME) != pytest.approx(
        outer_radius(at_origin, ORIGIN_FRAME), abs=1e-6
    )


@pytest.mark.parametrize(
    "base",
    [
        BaseFrame(x=0.6, y=0.3, theta=0.5),
        BaseFrame(x=0.4, y=-0.2, theta=-0.3),
        BaseFrame(x=-0.7, y=0.9, theta=2.4),
    ],
)
def test_the_outer_set_still_contains_the_body_at_a_base_away_from_the_origin(
    base: BaseFrame,
) -> None:
    """**THE NEGATIVE FOR THE DANGEROUS CASE** — the disc is a subtraction.

    Steps 1-3 of the construction build the set up; step 4 intersects it with a
    workspace disc, and an intersection can only remove. A disc left centred on
    the origin while the body is measured from `base` clips away part of the
    true outer set and returns something that looks exactly like a sound outer
    bound — clears declarations it should refuse, and nothing downstream can
    tell (docs/mobile-base.md §1).

    The containment asserted here is the cheapest thing that catches it, and it
    catches it *as what it is*: the arm's own body at `base` is inside the true
    reachable set at every horizon by definition, so a piece of it outside the
    returned region says "this bound is unsound" and not "this bound moved".
    Leaving the disc at the origin leaves 4-9 cm² of body outside the region at
    these frames, and further out than the workspace disc it returns nothing at
    all. The translation test above would also notice a millimetre's worth of
    clipped rim, but it reports a *displacement*, which is the finding somebody
    talks themselves past; this one reports the arm being outside its own outer
    bound, which is not.
    """
    state = _state_from_hex(*DEMO_WORLD_OUTER_BEFORE[1][:2])
    region = outer_envelope(state, DEMO_LIMITS, 0.2, base)
    body = unary_union(link_polygons(state.q, DEMO_LIMITS, base))

    escape = body.difference(region)
    assert escape.is_empty, (
        f"{base}: {escape.area:.4e} m^2 of the arm's own body lies outside the "
        "outer set computed for that frame. Something in the construction is "
        "still measured from the origin, and an outer bound with a piece "
        "missing clears what it should refuse."
    )
    # ...and the set was moved rigidly rather than clipped: a rigid motion
    # preserves area exactly, a mis-centred intersection removes most of it.
    at_origin = outer_envelope(state, DEMO_LIMITS, 0.2, ORIGIN_FRAME)
    assert region.area == pytest.approx(at_origin.area, rel=1e-5)


def test_the_outer_set_refuses_a_base_that_is_not_a_frame() -> None:
    """No default, and no duck-type either — `reg.kinematics._base_frame`'s rule.

    A three-tuple carries no type and `None` reads as 'unspecified', which is
    what a required argument exists to make impossible. `reg.types.BasePose` is
    refused by the test in `tests/test_layer_boundary.py`, where the layer
    argument for refusing it lives.
    """
    for bad in ((0.0, 0.0, 0.0), [0.0, 0.0, 0.0], None, 0.0):
        with pytest.raises(TypeError, match="BaseFrame"):
            outer_envelope(STATIONARY, LIMITS, 0.2, bad)  # type: ignore[arg-type]
        with pytest.raises(TypeError, match="BaseFrame"):
            outer_radius(Polygon([(0, 0), (1, 0), (1, 1)]), bad)  # type: ignore[arg-type]


def test_the_outer_set_cannot_be_computed_without_a_base() -> None:
    """It is positional and required: omitting it is a `TypeError`, not a guess."""
    with pytest.raises(TypeError):
        outer_envelope(STATIONARY, LIMITS, 0.2)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        outer_radius(Polygon([(0, 0), (1, 0), (1, 1)]))  # type: ignore[call-arg]


# --------------------------------------------------------------------------
# The base's own motion in the outer set (issue #163)
#
# `Limits` has carried `base_v_max`, `base_a_max`, `base_omega_max` and
# `base_alpha_max` since issue #151 and nothing read them. They are read here
# now, analytically and composed by Minkowski sum rather than by gridding, and
# the tests below are in three groups:
#
#   * that a base which cannot move changes nothing — the regression guard for
#     the whole tier, whose sharpest form is
#     `test_the_outer_set_at_the_origin_is_bit_identical_to_before_the_base_moved`
#     above, which this section does not duplicate;
#   * that a base which can move makes the set strictly larger, and larger in
#     the right place — a point the vehicle can reach and the arm alone cannot;
#   * the refusals, because `base_vel is None` is a could-not-evaluate and must
#     never resolve to a base standing still.
#
# The soundness of the enlarged set is not asserted here. It is asserted where
# it belongs, in
# `test_no_bang_bang_trajectory_escapes_the_outer_envelope_with_a_driven_base`
# and its negative, against trajectories that actually drive.
# --------------------------------------------------------------------------


@pytest.mark.parametrize("horizon", (0.05, 0.2, 0.5, 5.0))
def test_a_base_that_cannot_move_contributes_exactly_zero(horizon: float) -> None:
    """`(0.0, 0.0)` to the bit, at every horizon and from every state.

    Not `approx`. The bit-identity of every published outer figure rests on
    these two numbers being exactly zero so that `outer_envelope` skips both
    terms; a value that were merely tiny would be applied, and `buffer(1e-18)`
    is not the identity in GEOS.
    """
    for state in SOUNDNESS_STATES:
        assert base_motion_bounds(state, LIMITS, horizon) == (0.0, 0.0), (
            f"q={state.q}, horizon={horizon}: a base with all four bounds at "
            "zero contributed something to the outer set."
        )


def test_a_base_that_cannot_move_needs_no_base_velocity() -> None:
    """`base_vel=None` is fine for a bolted base and refused for a driven one.

    Both halves matter. Every fixture in this repository records no base
    velocity (`reg.graph` reconstructs states from `robot_config`, which has no
    columns for one), so refusing `None` outright would refuse the entire
    existing corpus. Accepting it for a robot that can drive would read "not
    recorded" as "standing still", which is the could-not-evaluate resolving to
    the permissive answer that `CLAUDE.md` forbids.
    """
    state = SOUNDNESS_STATES[2]
    assert state.base_vel is None
    assert base_motion_bounds(state, LIMITS, 0.2) == (0.0, 0.0)

    with pytest.raises(ValueError, match="base_vel is None"):
        base_motion_bounds(state, MOBILE_LIMITS, 0.2)
    with pytest.raises(ValueError, match="base_vel is None"):
        outer_envelope(state, MOBILE_LIMITS, 0.2, ORIGIN_FRAME)


@pytest.mark.parametrize(
    "field,value",
    (
        ("base_v_max", 0.8),
        ("base_a_max", 1.5),
        ("base_omega_max", 1.2),
        ("base_alpha_max", 2.5),
    ),
)
def test_any_one_nonzero_base_bound_is_enough_to_require_a_base_velocity(
    field: str, value: float
) -> None:
    """Each of the four on its own, because "can the base move" is an `any`.

    A robot that can only turn still moves the arm; a robot that can only
    accelerate from rest still travels. Testing the four together would pass for
    an implementation that read `base_v_max` and ignored the other three.
    """
    limits = dataclasses.replace(LIMITS, **{field: value})
    with pytest.raises(ValueError, match="base_vel is None"):
        base_motion_bounds(SOUNDNESS_STATES[0], limits, 0.2)


def test_a_base_velocity_outside_its_own_limits_is_refused() -> None:
    """The same refusal `_check_state_within_limits` makes for a joint.

    The displacement bound integrates `min(|v0| + a*s, v_max)`, which is an
    upper bound only while `|v0| <= v_max`. A state that violates its own limit
    would therefore produce a bound that is too *small* — the one direction an
    outer bound may not be wrong in — so it is a fault in whatever produced the
    state and is reported as one.
    """
    state = SOUNDNESS_STATES[0]
    with pytest.raises(ValueError, match="base_v_max"):
        base_motion_bounds(_mobile(state, 0.9, 0.0, 0.0), MOBILE_LIMITS, 0.2)
    # The norm, not the components: (0.6, 0.6) is under the bound on each axis
    # and 0.85 m/s in total. `base_v_max` caps `hypot(vx, vy)`.
    with pytest.raises(ValueError, match="base_v_max"):
        base_motion_bounds(_mobile(state, 0.6, 0.6, 0.0), MOBILE_LIMITS, 0.2)
    with pytest.raises(ValueError, match="base_omega_max"):
        base_motion_bounds(_mobile(state, 0.0, 0.0, -1.3), MOBILE_LIMITS, 0.2)
    # ...and the ones that are inside it are accepted, so the check above is
    # discriminating rather than refusing everything.
    assert base_motion_bounds(_mobile(state, 0.6, 0.5, 1.2), MOBILE_LIMITS, 0.2)


def test_a_non_finite_base_velocity_is_refused_rather_than_propagated() -> None:
    """NaN compares False against every bound, so it would reach the geometry."""
    for bad in (float("nan"), float("inf")):
        with pytest.raises(ValueError, match="finite"):
            base_motion_bounds(
                _mobile(SOUNDNESS_STATES[0], bad, 0.0, 0.0), MOBILE_LIMITS, 0.2
            )
        with pytest.raises(ValueError, match="finite"):
            base_motion_bounds(
                _mobile(SOUNDNESS_STATES[0], 0.0, 0.0, bad), MOBILE_LIMITS, 0.2
            )


def test_the_base_bounds_are_the_integral_they_claim_to_be() -> None:
    """The arithmetic, stated rather than eyeballed off a polygon.

    Two regimes and the boundary between them. While the speed cap is slack the
    bound is `|v0|*H + a*H^2/2` — with the `substep_dt/2` term
    `reachable_joint_box` argues for, which is why the comparison carries it
    explicitly rather than hiding it in a tolerance. Once the cap engages the
    bound is strictly less than the uncapped parabola, which is the whole reason
    the cap is in there: without it a 5 s horizon would report a base travelling
    19 m under a bound of 0.8 m/s.
    """
    state = SOUNDNESS_STATES[0]
    v0, h = 0.4, 0.05
    v_max, a_max = MOBILE_LIMITS.base_v_max, MOBILE_LIMITS.base_a_max
    speed = min(v0 + 0.5 * a_max * SUBSTEP_DT, v_max)
    assert speed + a_max * h <= v_max, "this leg is meant to keep the cap slack"

    d_trans, _ = base_motion_bounds(_mobile(state, v0, 0.0, 0.0), MOBILE_LIMITS, h)
    assert d_trans == pytest.approx(speed * h + 0.5 * a_max * h**2, rel=1e-12)

    # ...and the capped regime, against the parabola it must undercut and the
    # constant-speed line it must not exceed.
    long_h = 5.0
    capped, _ = base_motion_bounds(
        _mobile(state, v0, 0.0, 0.0), MOBILE_LIMITS, long_h
    )
    assert capped < speed * long_h + 0.5 * a_max * long_h**2
    assert capped <= v_max * long_h


def test_the_base_bounds_are_monotone_in_the_horizon() -> None:
    """More time cannot mean less travel, in either the metres or the radians."""
    state = _mobile(SOUNDNESS_STATES[2], 0.3, -0.2, 0.4)
    trans = []
    yaw = []
    for h in (0.05, 0.1, 0.2, 0.4, 0.5, 1.0):
        d_trans, d_yaw = base_motion_bounds(state, MOBILE_LIMITS, h)
        trans.append(d_trans)
        yaw.append(d_yaw)
    assert trans == sorted(trans), f"translation bounds {trans} are not monotone"
    assert yaw == sorted(yaw), f"yaw bounds {yaw} are not monotone"


def test_a_driven_base_gives_a_strictly_larger_outer_set() -> None:
    """**The positive half of the negative the issue asks for.**

    Same arm, same state, same horizon; the only difference is four numbers on
    `Limits` that were dead until issue #163. The fixed-base set must be a
    strict subset — contained, and smaller in both area and radius. Anything
    less means the base bounds are being read and discarded.
    """
    state = SOUNDNESS_STATES[2]
    fixed = outer_envelope(state, LIMITS, 0.2, ORIGIN_FRAME)
    driven = outer_envelope(
        _mobile(state, 0.5, 0.0, 0.3), MOBILE_LIMITS, 0.2, ORIGIN_FRAME
    )

    assert fixed.difference(driven).is_empty, (
        "the fixed-base outer set is not inside the driven one, so the two are "
        "not bounds on the same arm."
    )
    assert envelope_area(driven) > envelope_area(fixed)
    assert outer_radius(driven, ORIGIN_FRAME) > outer_radius(fixed, ORIGIN_FRAME)


def test_a_point_the_base_can_reach_and_the_arm_cannot_is_inside_the_set() -> None:
    """The negative the issue names, as a point rather than as an area.

    A larger area is satisfied by a construction that dilates the arm's set by
    something arbitrary. This asserts the enlargement is in the right *place*
    and of the right *size*: a point straight ahead of the fully extended arm,
    further out than the fixed-base workspace disc by most of the base's own
    travel, is outside the fixed-base set and inside the driven one. And a point
    beyond even the driven bound is outside both — otherwise this would pass for
    a set that had simply been made enormous.
    """
    bolted = ProprioState(
        t=0.0, q=np.array([0.0, 0.0]), qd=np.array([0.0, 0.0]), base_vel=None
    )
    state = _mobile(bolted, 0.8, 0.0, 0.0)
    horizon = 0.5
    fixed = outer_envelope(bolted, LIMITS, horizon, ORIGIN_FRAME)
    driven = outer_envelope(state, MOBILE_LIMITS, horizon, ORIGIN_FRAME)
    d_trans, _ = base_motion_bounds(state, MOBILE_LIMITS, horizon)
    assert d_trans > 0.1, "the fixture is meant to let the base travel a long way"

    disc = float(np.sum(LIMITS.link_lengths) + LIMITS.link_radius)
    reachable_only_by_driving = Point(disc + 0.5 * d_trans, 0.0)
    assert not fixed.contains(reachable_only_by_driving), (
        "the point is inside the fixed-base set, so it does not distinguish the "
        "two and this test proves nothing."
    )
    assert driven.contains(reachable_only_by_driving), (
        "a point the vehicle can drive to is outside the outer set computed for "
        "a vehicle that can drive."
    )
    assert not driven.contains(Point(disc + 2.0 * d_trans, 0.0)), (
        "a point beyond the base's own travel is inside the set, so the "
        "enlargement is not bounded by anything and the assertion above is "
        "satisfied by an arbitrarily large region."
    )


def test_yaw_alone_enlarges_the_set_without_translating_it() -> None:
    """The yaw term is separately load-bearing, so it is separately tested.

    A base that can turn but not translate — `base_v_max = base_a_max = 0` —
    still sweeps the arm through a wider arc. The set must grow, and it must
    stay inside the *unchanged* workspace disc while doing it: turning on the
    spot moves nothing further from the base, so a construction that folded the
    yaw in as a translation would push the rim outside a disc that still holds.
    """
    state = _mobile(SOUNDNESS_STATES[1], 0.0, 0.0, 1.0)
    turning = dataclasses.replace(
        LIMITS, base_omega_max=1.2, base_alpha_max=2.5
    )
    assert turning.base_v_max == 0.0 and turning.base_a_max == 0.0

    fixed = outer_envelope(SOUNDNESS_STATES[1], LIMITS, 0.5, ORIGIN_FRAME)
    spun = outer_envelope(state, turning, 0.5, ORIGIN_FRAME)

    assert envelope_area(spun) > envelope_area(fixed)
    disc = float(np.sum(LIMITS.link_lengths) + LIMITS.link_radius)
    assert outer_radius(spun, ORIGIN_FRAME) <= disc * 1.001, (
        "a base that only turns pushed the outer set past the workspace disc, "
        "so the yaw is being applied as a displacement rather than a rotation."
    )


def test_a_yaw_span_past_a_full_turn_is_capped_at_one() -> None:
    """Exact, not conservative: the geometry depends on the angle modulo 2 pi.

    Two bases that can both spin more than a full turn inside the horizon reach
    the same set from the same pose, so the polygons must be *identical* and not
    merely similar. It is also what keeps the ancestor grid finite — without the
    cap, a fast enough yaw widens the first joint's interval until
    `MAX_OUTER_GRID_CONFIGS` refuses a bound that is in fact a disc.
    """
    state_slow = _mobile(SOUNDNESS_STATES[0], 0.0, 0.0, 0.0)
    slow = dataclasses.replace(LIMITS, base_omega_max=8.0, base_alpha_max=40.0)
    fast = dataclasses.replace(LIMITS, base_omega_max=40.0, base_alpha_max=400.0)

    a = outer_envelope(state_slow, slow, 1.0, ORIGIN_FRAME)
    b = outer_envelope(state_slow, fast, 1.0, ORIGIN_FRAME)
    assert base_motion_bounds(state_slow, slow, 1.0)[1] > 2.0 * math.pi
    assert a.area.hex() == b.area.hex(), (
        "two bases that can each spin more than a full turn returned different "
        "outer sets, so the 2 pi cap is not exact."
    )


def test_the_grid_guard_is_not_raised_for_the_base() -> None:
    """`MAX_OUTER_GRID_CONFIGS` stays where it was, and still refuses.

    The construction is analytic precisely so that the guard does not have to
    move (docs/mobile-base.md §3): three more gridded dimensions would trip it on
    the first frame. Asserted as the constant's value, plus a fast-yawing base
    at a long horizon evaluating rather than refusing — which is what the 2 pi
    cap buys.
    """
    assert MAX_OUTER_GRID_CONFIGS == 50_000
    state = _mobile(SOUNDNESS_STATES[0], 0.0, 0.0, 0.0)
    quick = dataclasses.replace(
        LIMITS, base_v_max=2.0, base_a_max=4.0, base_omega_max=20.0, base_alpha_max=100.0
    )
    assert isinstance(outer_envelope(state, quick, 2.0, ORIGIN_FRAME), Polygon)


def test_the_looseness_a_caller_must_publish_changes_when_the_base_can_drive() -> None:
    """The caveat is a value, not a docstring — `envelope_layer`'s shape.

    A reader of a mobile artifact taking the outer area for an estimate of where
    the robot can get is the failure this exists to stop, and it is not stopped
    by anything written in a docstring they will not open. So the sentence is
    returned, it differs between the two robots, and the mobile one names the
    thing that makes it loose.
    """
    fixed = outer_envelope_looseness(LIMITS)
    mobile = outer_envelope_looseness(MOBILE_LIMITS)

    assert fixed != mobile, (
        "the same sentence is published for a bolted-down arm and for a "
        "vehicle, so it says nothing about the difference between them."
    )
    assert "nonholonomic" in mobile and "disc" in mobile.lower()
    assert "nonholonomic" not in fixed, (
        "the fixed-base sentence carries the mobile caveat, which would make it "
        "wrong about the arm every artifact in this repository is built from."
    )
    # Both halves say the direction, because that is the part a reader acts on.
    assert "outer approximation" in fixed and "outer approximation" in mobile

    for field in Limits.BASE_BOUND_FIELDS:
        one = dataclasses.replace(LIMITS, **{field: 1.0})
        assert outer_envelope_looseness(one) == mobile, (
            f"a base with only {field} nonzero published the fixed-base "
            "sentence; the caveat has to fire on any of the four."
        )

    with pytest.raises(TypeError, match="Limits"):
        outer_envelope_looseness(MOBILE_LIMITS.base_v_max)  # type: ignore[arg-type]


def test_base_motion_bounds_refuse_a_state_frame_and_a_guessed_horizon() -> None:
    """The Layer A boundary and the no-default rule, on the new entry point."""
    frame = StateFrame(
        t=0.0,
        q=np.array([0.0, 0.0]),
        qd=np.array([0.0, 0.0]),
        human_pos=np.array([1.0, 1.0]),
        human_vel=np.array([0.0, 0.0]),
        base_vel=None,
        base_pose=None,
        objects=(Obstacle(entity_id="e", kind="crate", cx=1.0, cy=1.0, radius=0.2),),
    )
    with pytest.raises(TypeError, match="ProprioState"):
        base_motion_bounds(frame, MOBILE_LIMITS, 0.2)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        base_motion_bounds(SOUNDNESS_STATES[0], LIMITS)  # type: ignore[call-arg]
    with pytest.raises(ValueError, match="strictly positive"):
        base_motion_bounds(SOUNDNESS_STATES[0], LIMITS, 0.0)


def test_the_outer_set_of_a_driven_base_is_still_a_single_polygon() -> None:
    """Connectedness survives the Minkowski sum, which is not automatic.

    The union is connected by construction because consecutive links share a
    joint; dilating a connected set keeps it connected, and intersecting with a
    disc centred on the base does not cut it because every piece touches the
    base. A `MultiPolygon` out of here is a could-not-evaluate that
    `outer_envelope` refuses, and this is the case where it would first show up.
    """
    for horizon in (0.05, 0.5, 2.0):
        region = outer_envelope(
            _mobile(SOUNDNESS_STATES[3], 0.4, -0.3, 0.9),
            MOBILE_LIMITS,
            horizon,
            ORIGIN_FRAME,
        )
        assert isinstance(region, Polygon) and region.is_valid
