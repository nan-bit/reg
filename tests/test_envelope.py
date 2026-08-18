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
import pathlib
import subprocess
import sys
import textwrap

import numpy as np
import pytest
from shapely.geometry import Polygon
from shapely.ops import unary_union

import reg.envelope
from reg.envelope import (
    HASH_COORD_PRECISION,
    SUBSTEP_DT,
    compute_envelope,
    envelope_area,
    envelope_hash,
)
from reg.kinematics import link_polygons
from reg.types import Limits, Obstacle, ProprioState, StateFrame

# A two-link arm, stated here rather than imported from reg.world: these tests
# are about the envelope, and coupling them to a Layer B fixture would make a
# change to the demo world look like an envelope regression.
LIMITS = Limits(
    q_min=np.array([-np.pi, -2.6]),
    q_max=np.array([np.pi, 2.6]),
    qd_max=np.array([2.0, 2.5]),
    qdd_max=np.array([8.0, 10.0]),
    link_lengths=np.array([0.5, 0.4]),
    link_radius=0.05,
)
N_CORNERS = 2 ** len(LIMITS.link_lengths)

MOVING = ProprioState(t=0.0, q=np.array([0.2, 0.4]), qd=np.array([0.5, -0.3]))
STATIONARY = ProprioState(t=0.0, q=np.array([0.2, 0.4]), qd=np.array([0.0, 0.0]))

# Small enough to keep the suite quick; the invariants below do not depend on it.
N = 16


def body(q: ProprioState | np.ndarray) -> Polygon:
    """The robot's body in one configuration, as a single geometry."""
    return unary_union(link_polygons(q, LIMITS))


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
        from reg.types import Limits, ProprioState

        limits = Limits(
            q_min=np.array([-np.pi, -2.6]),
            q_max=np.array([np.pi, 2.6]),
            qd_max=np.array([2.0, 2.5]),
            qdd_max=np.array([8.0, 10.0]),
            link_lengths=np.array([0.5, 0.4]),
            link_radius=0.05,
        )
        state = ProprioState(t=0.0, q=np.array([0.2, 0.4]), qd=np.array([0.5, -0.3]))
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
    beyond_q = ProprioState(t=0.0, q=np.array([0.2, 3.0]), qd=np.array([0.0, 0.0]))
    with pytest.raises(ValueError, match="state.q is outside limits"):
        compute_envelope(beyond_q, LIMITS, n_samples=N)

    beyond_qd = ProprioState(t=0.0, q=np.array([0.2, 0.4]), qd=np.array([9.0, 0.0]))
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
        link_radius=LIMITS.link_radius,
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
