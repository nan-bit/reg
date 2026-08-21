"""Forward kinematics: hand-computable configurations, invariants, and refusals.

The positive cases here are deliberately ones a reader can check with a pencil —
`q = [0, 0]` on unit links puts the tip at `(2, 0)`, a right angle puts it at
`(1, 1)`. The rest are invariants (a rigid arm has a constant reach; a buffered
segment has area `2 r l`) rather than golden numbers, and every check that can
gate something downstream is paired with the input it is supposed to reject.
"""

from __future__ import annotations

import numpy as np
import pytest
from shapely.geometry import LineString

from reg.kinematics import clamp_to_limits, forward_kinematics, link_polygons
from reg.types import Limits, LimitSource, Obstacle, ProprioState, StateFrame


def two_link(link_radius: float = 0.05) -> Limits:
    """A two-link unit arm. Every bound stated; nothing defaulted."""
    return Limits(
        q_min=np.array([-np.pi, -np.pi]),
        q_max=np.array([np.pi, np.pi]),
        qd_max=np.array([2.0, 1.5]),
        qdd_max=np.array([10.0, 8.0]),
        link_lengths=np.array([1.0, 1.0]),
        source=LimitSource.PROPRIOCEPTIVE,
        link_radius=link_radius,
    )


# --------------------------------------------------------------------------
# Configurations computable by hand
# --------------------------------------------------------------------------


def test_straight_arm_reaches_two_along_x() -> None:
    segments = forward_kinematics(np.array([0.0, 0.0]), two_link())

    assert len(segments) == 2
    np.testing.assert_allclose(segments[0][0], [0.0, 0.0], atol=1e-12)
    np.testing.assert_allclose(segments[0][1], [1.0, 0.0], atol=1e-12)
    np.testing.assert_allclose(segments[1][0], [1.0, 0.0], atol=1e-12)
    np.testing.assert_allclose(segments[1][1], [2.0, 0.0], atol=1e-12)


def test_right_angle_puts_the_tip_at_one_one() -> None:
    """q = [0, pi/2]: first link along +x, second turned a quarter turn left."""
    segments = forward_kinematics(np.array([0.0, np.pi / 2]), two_link())

    np.testing.assert_allclose(segments[0][1], [1.0, 0.0], atol=1e-12)
    np.testing.assert_allclose(segments[1][1], [1.0, 1.0], atol=1e-12)


def test_angles_are_cumulative_not_absolute() -> None:
    """q = [pi/2, pi/2] doubles back: absolute angles would give (0, 1)."""
    segments = forward_kinematics(np.array([np.pi / 2, np.pi / 2]), two_link())

    np.testing.assert_allclose(segments[0][1], [0.0, 1.0], atol=1e-12)
    np.testing.assert_allclose(segments[1][1], [-1.0, 1.0], atol=1e-12)


def test_base_is_fixed_at_the_origin_and_links_are_connected() -> None:
    limits = Limits(
        q_min=np.array([-np.pi] * 3),
        q_max=np.array([np.pi] * 3),
        qd_max=np.array([1.0, 1.0, 1.0]),
        qdd_max=np.array([5.0, 5.0, 5.0]),
        link_lengths=np.array([0.5, 0.4, 0.3]),
        source=LimitSource.PROPRIOCEPTIVE,
        link_radius=0.05,
    )
    segments = forward_kinematics(np.array([0.3, -1.1, 2.0]), limits)

    np.testing.assert_allclose(segments[0][0], [0.0, 0.0], atol=1e-12)
    for (_, end), (next_start, _) in zip(segments, segments[1:]):
        np.testing.assert_allclose(end, next_start, atol=1e-12)


def test_link_lengths_are_preserved_for_any_configuration() -> None:
    """The invariant behind the hand cases: the arm is rigid."""
    limits = two_link()
    rng = np.random.default_rng(20260818)  # seeded: same bytes on every run
    for q in rng.uniform(-np.pi, np.pi, size=(50, 2)):
        for (start, end), length in zip(
            forward_kinematics(q, limits), limits.link_lengths
        ):
            assert np.linalg.norm(end - start) == pytest.approx(length, abs=1e-12)


def test_accepts_a_propriostate_and_agrees_with_the_bare_array() -> None:
    limits = two_link()
    q = np.array([0.4, -0.9])
    state = ProprioState(t=0.0, q=q, qd=np.array([0.0, 0.0]))

    for from_state, from_array in zip(
        forward_kinematics(state, limits), forward_kinematics(q, limits)
    ):
        np.testing.assert_array_equal(from_state[0], from_array[0])
        np.testing.assert_array_equal(from_state[1], from_array[1])


def test_forward_kinematics_is_deterministic_across_repeated_calls() -> None:
    """Same input, same bytes — not merely the same to within a tolerance."""
    limits = two_link()
    q = np.array([0.37, -1.24])

    first = forward_kinematics(q, limits)
    for _ in range(5):
        again = forward_kinematics(q, limits)
        for (s0, e0), (s1, e1) in zip(first, again):
            assert s0.tobytes() == s1.tobytes()
            assert e0.tobytes() == e1.tobytes()


def test_forward_kinematics_does_not_mutate_its_input() -> None:
    q = np.array([0.2, 0.3])
    before = q.copy()
    forward_kinematics(q, two_link())
    np.testing.assert_array_equal(q, before)


# --------------------------------------------------------------------------
# Link polygons
# --------------------------------------------------------------------------


def test_each_link_is_a_flat_capped_rectangle() -> None:
    limits = two_link(link_radius=0.1)
    polygons = link_polygons(np.array([0.0, np.pi / 2]), limits)

    assert len(polygons) == 2
    for polygon, length in zip(polygons, limits.link_lengths):
        assert polygon.is_valid
        # Flat caps: a rectangle, so exactly 2 r l. Round caps would add a disc.
        assert polygon.area == pytest.approx(2 * limits.link_radius * length)
        # 4 corners, plus the repeated closing point.
        assert len(polygon.exterior.coords) == 5


def test_polygons_straddle_their_segment() -> None:
    limits = two_link(link_radius=0.1)
    q = np.array([0.0, np.pi / 2])
    for polygon, (start, end) in zip(
        link_polygons(q, limits), forward_kinematics(q, limits)
    ):
        assert polygon.covers(LineString([start, end]))


def test_polygons_of_a_straight_arm_are_disjoint_apart_from_the_shared_cap() -> None:
    """Flat caps meeting end to end: the overlap is a line, not an area."""
    polygons = link_polygons(np.array([0.0, 0.0]), two_link(link_radius=0.1))
    assert polygons[0].intersection(polygons[1]).area == pytest.approx(0.0)


def test_link_polygons_reject_a_non_positive_radius() -> None:
    """Negative test: a bodyless robot must fail, not read as 'clear'."""
    limits = two_link(link_radius=0.0)
    with pytest.raises(ValueError, match="link_radius"):
        link_polygons(np.array([0.0, 0.0]), limits)


def test_kinematics_reject_a_zero_length_link() -> None:
    limits = Limits(
        q_min=np.array([-1.0, -1.0]),
        q_max=np.array([1.0, 1.0]),
        qd_max=np.array([1.0, 1.0]),
        qdd_max=np.array([1.0, 1.0]),
        link_lengths=np.array([1.0, 0.0]),
        source=LimitSource.PROPRIOCEPTIVE,
        link_radius=0.05,
    )
    with pytest.raises(ValueError, match="strictly positive"):
        forward_kinematics(np.array([0.0, 0.0]), limits)


# --------------------------------------------------------------------------
# Refusals: malformed robot state
# --------------------------------------------------------------------------


@pytest.mark.parametrize("q", [np.array([0.0]), np.array([0.0, 0.0, 0.0])])
def test_wrong_length_q_raises_rather_than_broadcasting(q: np.ndarray) -> None:
    """The negative test the whole module is built around.

    numpy would broadcast a one-element `q` across both links without a murmur,
    and the resulting geometry is wrong in a way nothing downstream can detect.
    """
    with pytest.raises(ValueError, match="entries but there are 2 links"):
        forward_kinematics(q, two_link())


def test_wrong_length_q_raises_in_link_polygons_too() -> None:
    with pytest.raises(ValueError, match="entries but there are 2 links"):
        link_polygons(np.array([0.0]), two_link())


def test_two_dimensional_q_raises() -> None:
    with pytest.raises(ValueError, match="one-dimensional"):
        forward_kinematics(np.array([[0.0, 0.0]]), two_link())


@pytest.mark.parametrize("bad", [np.nan, np.inf])
def test_non_finite_q_raises(bad: float) -> None:
    with pytest.raises(ValueError, match="non-finite"):
        forward_kinematics(np.array([0.0, bad]), two_link())


# --------------------------------------------------------------------------
# The layer boundary, at this module's own front door
# --------------------------------------------------------------------------


def test_a_state_frame_cannot_be_passed_in_even_though_it_has_a_q() -> None:
    """`StateFrame` duck-types as proprioception. Layer A must still refuse it.

    A `getattr(x, "q")` would accept this object and carry `human_pos` into a
    Layer A computation with it — the exact erosion tests/test_layer_boundary.py
    exists to prevent, arriving through a different door.
    """
    frame = StateFrame(
        t=0.0,
        q=np.array([0.0, 0.0]),
        qd=np.array([0.0, 0.0]),
        human_pos=np.array([1.0, 1.0]),
        human_vel=np.array([0.0, 0.0]),
        objects=(Obstacle("obs_0", "box", 1.0, 1.0, 0.2),),
    )
    with pytest.raises(TypeError, match="Layer A"):
        forward_kinematics(frame, two_link())  # type: ignore[arg-type]

    # ...and the narrowed view is accepted, so the refusal is about the layer.
    assert len(forward_kinematics(frame.proprio(), two_link())) == 2


def test_an_obstacle_cannot_be_passed_in() -> None:
    with pytest.raises(TypeError, match="Layer A"):
        forward_kinematics(Obstacle("obs_0", "box", 1.0, 1.0, 0.2), two_link())  # type: ignore[arg-type]


def test_no_kinematics_function_accepts_a_world_argument() -> None:
    """Structural: the signatures themselves must not name the world."""
    import inspect

    world_words = ("human", "obstacle", "object", "entity", "goal", "target", "scene")
    for fn in (forward_kinematics, link_polygons, clamp_to_limits):
        for name, param in inspect.signature(fn).parameters.items():
            assert not any(w in name.lower() for w in world_words), (
                f"{fn.__name__} takes a parameter named {name}"
            )
            assert param.annotation not in (Obstacle, StateFrame), (
                f"{fn.__name__}({name}) is annotated with a Layer B type"
            )


# --------------------------------------------------------------------------
# clamp_to_limits
# --------------------------------------------------------------------------


def test_clamp_clips_position_and_velocity_to_the_stated_bounds() -> None:
    limits = Limits(
        q_min=np.array([-1.0, -0.5]),
        q_max=np.array([1.0, 0.5]),
        qd_max=np.array([2.0, 1.0]),
        qdd_max=np.array([10.0, 10.0]),
        link_lengths=np.array([1.0, 1.0]),
        source=LimitSource.PROPRIOCEPTIVE,
        link_radius=0.05,
    )
    q, qd = clamp_to_limits(np.array([5.0, -3.0]), np.array([-9.0, 0.25]), limits)

    np.testing.assert_allclose(q, [1.0, -0.5])
    np.testing.assert_allclose(qd, [-2.0, 0.25])  # magnitude bound, both signs


def test_clamp_leaves_an_in_bounds_state_untouched() -> None:
    limits = two_link()
    q_in, qd_in = np.array([0.1, -0.2]), np.array([0.5, -0.5])
    q, qd = clamp_to_limits(q_in, qd_in, limits)

    np.testing.assert_array_equal(q, q_in)
    np.testing.assert_array_equal(qd, qd_in)


def test_clamp_is_pure() -> None:
    """No writing through the caller's arrays: a record edited after the fact."""
    limits = two_link()
    q_in, qd_in = np.array([9.0, -9.0]), np.array([9.0, -9.0])
    q_before, qd_before = q_in.copy(), qd_in.copy()

    q, qd = clamp_to_limits(q_in, qd_in, limits)

    np.testing.assert_array_equal(q_in, q_before)
    np.testing.assert_array_equal(qd_in, qd_before)
    assert not np.shares_memory(q, q_in)
    assert not np.shares_memory(qd, qd_in)


def test_clamp_is_idempotent() -> None:
    limits = two_link()
    once = clamp_to_limits(np.array([4.0, -4.0]), np.array([4.0, -4.0]), limits)
    twice = clamp_to_limits(once[0], once[1], limits)
    np.testing.assert_array_equal(once[0], twice[0])
    np.testing.assert_array_equal(once[1], twice[1])


def test_clamp_accepts_a_propriostate() -> None:
    limits = two_link()
    state = ProprioState(t=0.0, q=np.array([4.0, 0.0]), qd=np.array([0.0, 9.0]))
    q, qd = clamp_to_limits(state, state, limits)

    np.testing.assert_allclose(q, [np.pi, 0.0])
    np.testing.assert_allclose(qd, [0.0, 1.5])


def test_clamp_rejects_a_wrong_length_state() -> None:
    with pytest.raises(ValueError, match="entries but there are 2 links"):
        clamp_to_limits(np.array([0.0]), np.array([0.0, 0.0]), two_link())
    with pytest.raises(ValueError, match="entries but there are 2 links"):
        clamp_to_limits(np.array([0.0, 0.0]), np.array([0.0]), two_link())


def test_clamp_rejects_inverted_position_bounds() -> None:
    """Negative test: np.clip would return q_max, a bound nobody stated."""
    limits = Limits(
        q_min=np.array([1.0, 0.0]),
        q_max=np.array([-1.0, 0.0]),  # inverted
        qd_max=np.array([1.0, 1.0]),
        qdd_max=np.array([1.0, 1.0]),
        link_lengths=np.array([1.0, 1.0]),
        source=LimitSource.PROPRIOCEPTIVE,
        link_radius=0.05,
    )
    with pytest.raises(ValueError, match="q_min exceeds"):
        clamp_to_limits(np.array([0.0, 0.0]), np.array([0.0, 0.0]), limits)


def test_clamp_rejects_a_negative_velocity_bound() -> None:
    limits = Limits(
        q_min=np.array([-1.0, -1.0]),
        q_max=np.array([1.0, 1.0]),
        qd_max=np.array([1.0, -0.5]),  # no clipped value satisfies this
        qdd_max=np.array([1.0, 1.0]),
        link_lengths=np.array([1.0, 1.0]),
        source=LimitSource.PROPRIOCEPTIVE,
        link_radius=0.05,
    )
    with pytest.raises(ValueError, match="non-negative magnitude"):
        clamp_to_limits(np.array([0.0, 0.0]), np.array([0.0, 0.0]), limits)


def test_clamp_rejects_a_state_frame() -> None:
    frame = StateFrame(
        t=0.0,
        q=np.array([0.0, 0.0]),
        qd=np.array([0.0, 0.0]),
        human_pos=np.array([1.0, 1.0]),
        human_vel=np.array([0.0, 0.0]),
    )
    with pytest.raises(TypeError, match="Layer A"):
        clamp_to_limits(frame, frame, two_link())  # type: ignore[arg-type]
