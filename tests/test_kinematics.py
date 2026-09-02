"""Forward kinematics: hand-computable configurations, invariants, and refusals.

The positive cases here are deliberately ones a reader can check with a pencil —
`q = [0, 0]` on unit links puts the tip at `(2, 0)`, a right angle puts it at
`(1, 1)`. The rest are invariants (a rigid arm has a constant reach; a buffered
segment has area `2 r l`) rather than golden numbers, and every check that can
gate something downstream is paired with the input it is supposed to reject.

THE BASE FRAME (issue #152)
---------------------------
The base used to be a literal `0.0` inside the cumulative sums; it is a required
`BaseFrame` argument now, and nothing became mobile. That leaves this file two
jobs it did not have. The first is the failure mode a required-but-unused
argument has — accepted and ignored, which no test written at the origin can
see — so there is a section of off-origin tests: a translation moves every
segment by exactly the offset, a rotation turns them about the base, and the two
compose in that order. The second is that no published figure may move, so there
is a table of `float.hex()` coordinates taken from the commit *before* the
change, compared byte for byte, with a negative that feeds it a base one
millimetre away and requires it to disagree.
"""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest
from shapely.geometry import LineString

from reg.kinematics import (
    ORIGIN_FRAME,
    BaseFrame,
    clamp_to_limits,
    forward_kinematics,
    link_polygons,
)
from reg.types import (
    BasePose,
    Limits,
    LimitSource,
    Obstacle,
    PoseSource,
    ProprioState,
    StateFrame,
)
from reg.world import LIMITS as DEMO_LIMITS


def two_link(link_radius: float = 0.05) -> Limits:
    """A two-link unit arm, every bound stated.

    `link_radius` is this fixture's one knob — 0.05 m unless a test needs a
    different half-width — and it is stated here, in the file that uses it.
    `Limits` itself defaults nothing since issue #115.
    """
    return Limits(
        q_min=np.array([-np.pi, -np.pi]),
        q_max=np.array([np.pi, np.pi]),
        qd_max=np.array([2.0, 1.5]),
        qdd_max=np.array([10.0, 8.0]),
        link_lengths=np.array([1.0, 1.0]),
        source=LimitSource.PROPRIOCEPTIVE,
        link_radius=link_radius,
        base_v_max=0.0,
        base_a_max=0.0,
        base_omega_max=0.0,
        base_alpha_max=0.0,
    )


# --------------------------------------------------------------------------
# Configurations computable by hand
# --------------------------------------------------------------------------


def test_straight_arm_reaches_two_along_x() -> None:
    segments = forward_kinematics(np.array([0.0, 0.0]), two_link(), ORIGIN_FRAME)

    assert len(segments) == 2
    np.testing.assert_allclose(segments[0][0], [0.0, 0.0], atol=1e-12)
    np.testing.assert_allclose(segments[0][1], [1.0, 0.0], atol=1e-12)
    np.testing.assert_allclose(segments[1][0], [1.0, 0.0], atol=1e-12)
    np.testing.assert_allclose(segments[1][1], [2.0, 0.0], atol=1e-12)


def test_right_angle_puts_the_tip_at_one_one() -> None:
    """q = [0, pi/2]: first link along +x, second turned a quarter turn left."""
    segments = forward_kinematics(np.array([0.0, np.pi / 2]), two_link(), ORIGIN_FRAME)

    np.testing.assert_allclose(segments[0][1], [1.0, 0.0], atol=1e-12)
    np.testing.assert_allclose(segments[1][1], [1.0, 1.0], atol=1e-12)


def test_angles_are_cumulative_not_absolute() -> None:
    """q = [pi/2, pi/2] doubles back: absolute angles would give (0, 1)."""
    segments = forward_kinematics(np.array([np.pi / 2, np.pi / 2]), two_link(), ORIGIN_FRAME)

    np.testing.assert_allclose(segments[0][1], [0.0, 1.0], atol=1e-12)
    np.testing.assert_allclose(segments[1][1], [-1.0, 1.0], atol=1e-12)


def three_link() -> Limits:
    """A three-link arm, every bound stated. Shared by the base-frame tests."""
    return Limits(
        q_min=np.array([-np.pi] * 3),
        q_max=np.array([np.pi] * 3),
        qd_max=np.array([1.0, 1.0, 1.0]),
        qdd_max=np.array([5.0, 5.0, 5.0]),
        link_lengths=np.array([0.5, 0.4, 0.3]),
        source=LimitSource.PROPRIOCEPTIVE,
        link_radius=0.05,
        base_v_max=0.0,
        base_a_max=0.0,
        base_omega_max=0.0,
        base_alpha_max=0.0,
    )


@pytest.mark.parametrize(
    "base",
    [
        ORIGIN_FRAME,
        BaseFrame(x=1.5, y=-0.75, theta=0.0),
        BaseFrame(x=0.0, y=0.0, theta=0.9),
        BaseFrame(x=-2.0, y=3.25, theta=-1.7),
    ],
)
def test_the_first_segment_starts_at_the_base_frame_and_links_are_connected(
    base: BaseFrame,
) -> None:
    """The property `test_base_is_fixed_at_the_origin_...` asserted, where it now lives.

    It used to read `segments[0][0] == [0, 0]`, which was true because the base
    was a literal `0.0` inside the cumulative sums. The base is an argument
    since issue #152, so the same property is now *the first segment starts at
    the base frame that was passed* — and it is checked for a base away from the
    origin as well, because at `ORIGIN_FRAME` alone it cannot tell a threaded
    argument from an ignored one.
    """
    segments = forward_kinematics(np.array([0.3, -1.1, 2.0]), three_link(), base)

    np.testing.assert_allclose(segments[0][0], [base.x, base.y], atol=1e-12)
    for (_, end), (next_start, _) in zip(segments, segments[1:]):
        np.testing.assert_allclose(end, next_start, atol=1e-12)


def test_link_lengths_are_preserved_for_any_configuration() -> None:
    """The invariant behind the hand cases: the arm is rigid."""
    limits = two_link()
    rng = np.random.default_rng(20260818)  # seeded: same bytes on every run
    for q in rng.uniform(-np.pi, np.pi, size=(50, 2)):
        for (start, end), length in zip(
            forward_kinematics(q, limits, ORIGIN_FRAME), limits.link_lengths
        ):
            assert np.linalg.norm(end - start) == pytest.approx(length, abs=1e-12)


def test_accepts_a_propriostate_and_agrees_with_the_bare_array() -> None:
    limits = two_link()
    q = np.array([0.4, -0.9])
    state = ProprioState(t=0.0, q=q, qd=np.array([0.0, 0.0]), base_vel=None)

    for from_state, from_array in zip(
        forward_kinematics(state, limits, ORIGIN_FRAME),
        forward_kinematics(q, limits, ORIGIN_FRAME),
    ):
        np.testing.assert_array_equal(from_state[0], from_array[0])
        np.testing.assert_array_equal(from_state[1], from_array[1])


def test_forward_kinematics_is_deterministic_across_repeated_calls() -> None:
    """Same input, same bytes — not merely the same to within a tolerance."""
    limits = two_link()
    q = np.array([0.37, -1.24])

    first = forward_kinematics(q, limits, ORIGIN_FRAME)
    for _ in range(5):
        again = forward_kinematics(q, limits, ORIGIN_FRAME)
        for (s0, e0), (s1, e1) in zip(first, again):
            assert s0.tobytes() == s1.tobytes()
            assert e0.tobytes() == e1.tobytes()


def test_forward_kinematics_does_not_mutate_its_input() -> None:
    q = np.array([0.2, 0.3])
    before = q.copy()
    forward_kinematics(q, two_link(), ORIGIN_FRAME)
    np.testing.assert_array_equal(q, before)


# --------------------------------------------------------------------------
# The base frame (issue #152)
#
# The base used to be a literal `0.0` inside the cumulative sums. It is an
# argument now, and nothing became mobile: every caller in `reg/` passes
# `ORIGIN_FRAME` and every result is unchanged. What that leaves is exactly the
# failure mode a required-but-unused argument has — accepted and ignored, which
# no test written at the origin can see — so the tests below are all off-origin.
# --------------------------------------------------------------------------


def _rotate(points: np.ndarray, theta: float) -> np.ndarray:
    """Rotate row-vectors about the origin. Written out rather than imported:
    a check that reuses the code under test cannot fail when that code is wrong."""
    c, sn = np.cos(theta), np.sin(theta)
    return points @ np.array([[c, sn], [-sn, c]])


@pytest.mark.parametrize("offset", [(1.5, -0.75), (-2.0, 3.25), (0.0, 0.4)])
def test_a_translated_base_translates_every_segment_by_exactly_that_offset(
    offset: tuple[float, float],
) -> None:
    """**THE NEGATIVE.** Without this the change is a rename.

    A parameter that is accepted and then dropped on the floor passes every
    other test in this file, because every other test passes `ORIGIN_FRAME` and
    a dropped origin is indistinguishable from a used one. The invariant is
    exact rather than approximate on purpose: a pure translation of a cumulative
    sum is an addition, not an approximation.
    """
    limits = three_link()
    q = np.array([0.3, -1.1, 2.0])
    at_origin = forward_kinematics(q, limits, ORIGIN_FRAME)
    moved = forward_kinematics(
        q, limits, BaseFrame(x=offset[0], y=offset[1], theta=0.0)
    )

    assert len(moved) == len(at_origin)
    for (s0, e0), (s1, e1) in zip(at_origin, moved):
        np.testing.assert_allclose(s1, s0 + np.asarray(offset), atol=1e-12)
        np.testing.assert_allclose(e1, e0 + np.asarray(offset), atol=1e-12)


@pytest.mark.parametrize("theta", [0.9, -1.7, np.pi])
def test_a_rotated_base_rotates_every_segment_about_the_base(theta: float) -> None:
    """The other half of the negative: a base frame is a frame, not an offset.

    A parameter threaded as `(x, y)` only — the plausible half-implementation —
    passes the translation test above and fails here, which is why both ship.
    """
    limits = three_link()
    q = np.array([0.3, -1.1, 2.0])
    at_origin = forward_kinematics(q, limits, ORIGIN_FRAME)
    turned = forward_kinematics(q, limits, BaseFrame(x=0.0, y=0.0, theta=theta))

    for (s0, e0), (s1, e1) in zip(at_origin, turned):
        np.testing.assert_allclose(s1, _rotate(s0, theta), atol=1e-12)
        np.testing.assert_allclose(e1, _rotate(e0, theta), atol=1e-12)


def test_a_rotation_about_a_translated_base_is_the_rotation_then_the_offset() -> None:
    """Order matters, and getting it backwards is a silent, plausible geometry.

    `theta` turns the arm about *its own base*, not about the room's origin. A
    transform composed the other way round places the arm somewhere entirely
    different while still being a rigid motion, so nothing about the link
    lengths or the connectivity would catch it.
    """
    limits = three_link()
    q = np.array([0.3, -1.1, 2.0])
    base = BaseFrame(x=-0.8, y=1.25, theta=0.6)
    at_origin = forward_kinematics(q, limits, ORIGIN_FRAME)
    placed = forward_kinematics(q, limits, base)

    for (s0, e0), (s1, e1) in zip(at_origin, placed):
        offset = np.array([base.x, base.y])
        np.testing.assert_allclose(s1, _rotate(s0, base.theta) + offset, atol=1e-12)
        np.testing.assert_allclose(e1, _rotate(e0, base.theta) + offset, atol=1e-12)


def test_link_polygons_move_with_the_base_too() -> None:
    """The wrapper has to express the base, not merely accept one.

    `link_polygons` is where every consumer of the robot's *body* comes through
    — the envelope sweep, every separation distance, the viz — so a base it
    silently dropped would be a base none of them could use.
    """
    limits = three_link()
    q = np.array([0.3, -1.1, 2.0])
    base = BaseFrame(x=1.5, y=-0.75, theta=0.0)

    for at_origin, moved in zip(
        link_polygons(q, limits, ORIGIN_FRAME),
        link_polygons(q, limits, base),
    ):
        assert moved.area == pytest.approx(at_origin.area)
        np.testing.assert_allclose(
            np.array(moved.centroid.coords[0]),
            np.array(at_origin.centroid.coords[0]) + np.array([base.x, base.y]),
            atol=1e-12,
        )


def test_the_base_frame_is_required_with_no_default() -> None:
    """The rule this signature is shaped by (CLAUDE.md; issues #115 and #151).

    A base frame defaulting to the origin would be a frame nobody chose, and
    every figure measured against it would be indistinguishable downstream from
    one a caller stated. So the parameter carries no default, and the fixed-base
    call sites say `ORIGIN_FRAME` out loud.
    """
    import inspect

    for fn in (forward_kinematics, link_polygons):
        param = inspect.signature(fn).parameters["base"]
        assert param.default is inspect.Parameter.empty, (
            f"{fn.__name__} gives `base` a default. An unstated base frame must "
            "not be indistinguishable from a stated one."
        )
    with pytest.raises(TypeError):
        forward_kinematics(np.array([0.0, 0.0]), two_link())  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        link_polygons(np.array([0.0, 0.0]), two_link())  # type: ignore[call-arg]


def test_the_origin_frame_is_the_origin_unrotated() -> None:
    """The constant every fixed-base caller passes says what it claims to say."""
    assert (ORIGIN_FRAME.x, ORIGIN_FRAME.y, ORIGIN_FRAME.theta) == (0.0, 0.0, 0.0)


def test_a_base_frame_is_frozen() -> None:
    """It reaches the geometry, so it cannot move after it is stated."""
    with pytest.raises(dataclasses.FrozenInstanceError):
        ORIGIN_FRAME.x = 1.0  # type: ignore[misc]


def test_no_field_of_base_frame_has_a_default() -> None:
    for f in dataclasses.fields(BaseFrame):
        assert f.default is dataclasses.MISSING, f"BaseFrame.{f.name} has a default"
        assert f.default_factory is dataclasses.MISSING


@pytest.mark.parametrize("name", ["x", "y", "theta"])
@pytest.mark.parametrize("bad", [np.nan, np.inf, -np.inf])
def test_a_non_finite_base_frame_is_refused(name: str, bad: float) -> None:
    """Negative test: a non-finite base is an invalid geometry downstream, and an
    invalid geometry reads as 'no reachable area' rather than as the fault it is."""
    with pytest.raises(ValueError, match="not finite"):
        BaseFrame(**{**{"x": 0.0, "y": 0.0, "theta": 0.0}, name: bad})


@pytest.mark.parametrize("name", ["x", "y", "theta"])
def test_a_base_frame_coordinate_that_is_a_string_is_refused(name: str) -> None:
    """Negative test: `float("0.5")` succeeds, and that is the trap.

    The same argument `Limits` refuses a stringly-typed base bound under: a
    string that happens to parse carries no units and no frame.
    """
    with pytest.raises(TypeError, match=name):
        BaseFrame(**{**{"x": 0.0, "y": 0.0, "theta": 0.0}, name: "0.5"})  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# Bit-identity with the fixed-base results this change replaced
#
# Computed by running `forward_kinematics(q, reg.world.LIMITS)` on the commit
# *before* the base became an argument, and written down as hex float literals
# so that "same value" here means the same 64 bits and not the same number to
# within a tolerance. Re-running the new code to regenerate this table would
# make the test agree with whatever the code does, which is the one thing it
# must not do.
# --------------------------------------------------------------------------

#: (q, ((start, end) per link,)) — every coordinate a `float.hex()` string.
DEMO_WORLD_SEGMENTS_BEFORE = (
    (
        ("0x0.0p+0", "0x0.0p+0"),
        (
            (("0x0.0p+0", "0x0.0p+0"), ("0x1.0000000000000p-1", "0x0.0p+0")),
            (
                ("0x1.0000000000000p-1", "0x0.0p+0"),
                ("0x1.ccccccccccccdp-1", "0x0.0p+0"),
            ),
        ),
    ),
    (
        ("0x1.3333333333333p-2", "-0x1.199999999999ap+0"),
        (
            (
                ("0x0.0p+0", "0x0.0p+0"),
                ("0x1.e921dd42f09bap-2", "0x1.2e9cd95baba33p-3"),
            ),
            (
                ("0x1.e921dd42f09bap-2", "0x1.2e9cd95baba33p-3"),
                ("0x1.83406dcab5b6cp-1", "-0x1.1d0ba084543e3p-3"),
            ),
        ),
    ),
    (
        ("0x1.921fb54442d18p+0", "0x1.921fb54442d18p+0"),
        (
            (
                ("0x0.0p+0", "0x0.0p+0"),
                ("0x1.1a62633145c07p-55", "0x1.0000000000000p-1"),
            ),
            (
                ("0x1.1a62633145c07p-55", "0x1.0000000000000p-1"),
                ("-0x1.9999999999999p-2", "0x1.0000000000000p-1"),
            ),
        ),
    ),
    (
        ("-0x1.3333333333333p+1", "0x1.4cccccccccccdp+1"),
        (
            (
                ("0x0.0p+0", "0x0.0p+0"),
                ("-0x1.798bab490d185p-2", "-0x1.59d64f5c3d19bp-2"),
            ),
            (
                ("-0x1.798bab490d185p-2", "-0x1.59d64f5c3d19bp-2"),
                ("0x1.7e3c29684a100p-6", "-0x1.0876521eaa774p-2"),
            ),
        ),
    ),
    (
        ("0x1.3c0c9539b8887p+0", "-0x1.87e6b7599e010p-1"),
        (
            (
                ("0x0.0p+0", "0x0.0p+0"),
                ("0x1.51d92576a34f6p-3", "0x1.e354ae0df010ap-2"),
            ),
            (
                ("0x1.51d92576a34f6p-3", "0x1.e354ae0df010ap-2"),
                ("0x1.0b22aa6deefdap-1", "0x1.4e422d6cadd3cp-1"),
            ),
        ),
    ),
)


@pytest.mark.parametrize("q_hex,segments_hex", DEMO_WORLD_SEGMENTS_BEFORE)
def test_the_demo_arm_at_the_origin_is_bit_identical_to_before_the_base_moved(
    q_hex: tuple[str, str],
    segments_hex: tuple[tuple[tuple[str, str], tuple[str, str]], ...],
) -> None:
    """No published figure moves, checked at the source of every one of them.

    `docs/retention.md`'s figures, `reg.enforce`'s bound and every envelope in
    every artifact are downstream of these coordinates. Threading a base frame
    through is only a refactor if the numbers do not change — and "do not
    change" has to mean the bytes, because a 1-ulp drift in a link tip would
    move an area in the last digit and nothing here would say so.
    """
    q = np.array([float.fromhex(v) for v in q_hex])
    got = forward_kinematics(q, DEMO_LIMITS, ORIGIN_FRAME)

    assert len(got) == len(segments_hex)
    for (start, end), (start_hex, end_hex) in zip(got, segments_hex):
        for point, expected_hex in ((start, start_hex), (end, end_hex)):
            expected = np.array([float.fromhex(v) for v in expected_hex])
            assert point.tobytes() == expected.tobytes(), (
                f"forward_kinematics moved: got {point.tolist()!r}, the commit "
                f"before the base became an argument gave {expected.tolist()!r}."
            )


def test_a_negative_zero_configuration_is_the_only_thing_the_offset_changes() -> None:
    """The one exception to the byte-for-byte claim above, written down.

    Adding a base coordinate of `+0.0` maps a coordinate of `-0.0` to `+0.0` —
    that is what IEEE-754 addition does, and `q = -0.0` is the only input that
    reaches it. The two compare equal and no area, distance or containment test
    in this repository distinguishes them; 6933 frames across every scenario at
    three seeds, and 20000 random configurations, are byte-identical. It is
    recorded here rather than special-cased in `forward_kinematics`, because a
    branch on a value would be a worse thing to have than an exactly stated
    claim.
    """
    segments = forward_kinematics(np.array([-0.0, -0.0]), DEMO_LIMITS, ORIGIN_FRAME)
    for _, end in segments:
        assert end[1] == 0.0
        assert not np.signbit(end[1])


def test_the_bit_identity_table_would_notice_a_moved_base() -> None:
    """**THE NEGATIVE for the table above.** It has to be able to disagree.

    A golden table compared with `assert_allclose`, or built from a re-run of
    the code it checks, agrees with anything. This feeds the same comparison a
    base one millimetre away and requires it to fail — 1 mm being small enough
    that a tolerance-based check would wave it through.
    """
    q_hex, segments_hex = DEMO_WORLD_SEGMENTS_BEFORE[1]
    q = np.array([float.fromhex(v) for v in q_hex])
    got = forward_kinematics(q, DEMO_LIMITS, BaseFrame(x=0.001, y=0.0, theta=0.0))

    expected = np.array([float.fromhex(v) for v in segments_hex[0][1]])
    assert got[0][1].tobytes() != expected.tobytes()


# --------------------------------------------------------------------------
# Link polygons
# --------------------------------------------------------------------------


def test_each_link_is_a_flat_capped_rectangle() -> None:
    limits = two_link(link_radius=0.1)
    polygons = link_polygons(np.array([0.0, np.pi / 2]), limits, ORIGIN_FRAME)

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
        link_polygons(q, limits, ORIGIN_FRAME),
        forward_kinematics(q, limits, ORIGIN_FRAME),
    ):
        assert polygon.covers(LineString([start, end]))


def test_polygons_of_a_straight_arm_are_disjoint_apart_from_the_shared_cap() -> None:
    """Flat caps meeting end to end: the overlap is a line, not an area."""
    polygons = link_polygons(
        np.array([0.0, 0.0]), two_link(link_radius=0.1), ORIGIN_FRAME
    )
    assert polygons[0].intersection(polygons[1]).area == pytest.approx(0.0)


def test_link_polygons_reject_a_non_positive_radius() -> None:
    """Negative test: a bodyless robot must fail, not read as 'clear'."""
    limits = two_link(link_radius=0.0)
    with pytest.raises(ValueError, match="link_radius"):
        link_polygons(np.array([0.0, 0.0]), limits, ORIGIN_FRAME)


def test_kinematics_reject_a_zero_length_link() -> None:
    limits = Limits(
        q_min=np.array([-1.0, -1.0]),
        q_max=np.array([1.0, 1.0]),
        qd_max=np.array([1.0, 1.0]),
        qdd_max=np.array([1.0, 1.0]),
        link_lengths=np.array([1.0, 0.0]),
        source=LimitSource.PROPRIOCEPTIVE,
        link_radius=0.05,
        base_v_max=0.0,
        base_a_max=0.0,
        base_omega_max=0.0,
        base_alpha_max=0.0,
    )
    with pytest.raises(ValueError, match="strictly positive"):
        forward_kinematics(np.array([0.0, 0.0]), limits, ORIGIN_FRAME)


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
        forward_kinematics(q, two_link(), ORIGIN_FRAME)


def test_wrong_length_q_raises_in_link_polygons_too() -> None:
    with pytest.raises(ValueError, match="entries but there are 2 links"):
        link_polygons(np.array([0.0]), two_link(), ORIGIN_FRAME)


def test_two_dimensional_q_raises() -> None:
    with pytest.raises(ValueError, match="one-dimensional"):
        forward_kinematics(np.array([[0.0, 0.0]]), two_link(), ORIGIN_FRAME)


@pytest.mark.parametrize("bad", [np.nan, np.inf])
def test_non_finite_q_raises(bad: float) -> None:
    with pytest.raises(ValueError, match="non-finite"):
        forward_kinematics(np.array([0.0, bad]), two_link(), ORIGIN_FRAME)


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
        base_vel=None,
        base_pose=None,
        objects=(Obstacle("obs_0", "box", 1.0, 1.0, 0.2),),
    )
    with pytest.raises(TypeError, match="Layer A"):
        forward_kinematics(frame, two_link(), ORIGIN_FRAME)  # type: ignore[arg-type]

    # ...and the narrowed view is accepted, so the refusal is about the layer.
    assert len(forward_kinematics(frame.proprio(), two_link(), ORIGIN_FRAME)) == 2


def test_an_obstacle_cannot_be_passed_in() -> None:
    with pytest.raises(TypeError, match="Layer A"):
        forward_kinematics(
            Obstacle("obs_0", "box", 1.0, 1.0, 0.2), two_link(), ORIGIN_FRAME
        )  # type: ignore[arg-type]


def test_a_base_pose_cannot_be_passed_as_the_base_frame() -> None:
    """`BasePose` duck-types as a base frame. Layer A must still refuse it.

    It has `x`, `y` and `theta`, so any structural reading of the argument would
    take one — and a room-frame pose is Layer B *structurally*
    (docs/sufficiency.md §5.6). Transforming the arm by one would produce a
    room-frame region wearing a Layer A tag, which is the mislabelling this
    module's front door exists to stop, arriving through the door issue #152
    opened. Placing a body-frame set in the room is Tier 3's decision
    (docs/mobile-base.md §7), taken in the open with `sufficiency.md` moving in
    the same commit — not something a `getattr` should be able to do quietly.
    """
    pose = BasePose(x=1.0, y=2.0, theta=0.3, source=PoseSource.DEAD_RECKONED)
    with pytest.raises(TypeError, match="BaseFrame"):
        forward_kinematics(np.array([0.0, 0.0]), two_link(), pose)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="BaseFrame"):
        link_polygons(np.array([0.0, 0.0]), two_link(), pose)  # type: ignore[arg-type]


def test_kinematics_does_not_import_a_room_frame_pose() -> None:
    """Structural: the refusal above is only as good as the module's imports.

    `reg/kinematics.py` naming `BasePose` at all would be the first step to
    accepting one, and it does not need to — `isinstance(base, BaseFrame)` is
    the whole check. The docstrings may *mention* the type, and do; what must
    not exist is an import binding it.
    """
    import reg.kinematics as kin

    for name, obj in vars(kin).items():
        assert obj is not BasePose, (
            f"reg.kinematics binds BasePose as `{name}`. That type is Layer B; "
            "this module is Layer A and takes a BaseFrame the caller states."
        )


@pytest.mark.parametrize("bad", [(0.0, 0.0, 0.0), [0.0, 0.0, 0.0], None, 0.0])
def test_a_bare_triple_is_not_a_base_frame(bad: object) -> None:
    """Negative test: the frame has to be stated as one.

    A three-tuple carries no type, so nothing distinguishes it from a `BasePose`
    somebody splatted in — which is exactly the crossing the test above refuses.
    `None` is the other: it reads as 'unspecified', and unspecified is what the
    required argument exists to make impossible.
    """
    with pytest.raises(TypeError, match="BaseFrame"):
        forward_kinematics(np.array([0.0, 0.0]), two_link(), bad)  # type: ignore[arg-type]


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
        base_v_max=0.0,
        base_a_max=0.0,
        base_omega_max=0.0,
        base_alpha_max=0.0,
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
    state = ProprioState(t=0.0, q=np.array([4.0, 0.0]), qd=np.array([0.0, 9.0]), base_vel=None)
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
        base_v_max=0.0,
        base_a_max=0.0,
        base_omega_max=0.0,
        base_alpha_max=0.0,
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
        base_v_max=0.0,
        base_a_max=0.0,
        base_omega_max=0.0,
        base_alpha_max=0.0,
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
        base_vel=None,
        base_pose=None,
    )
    with pytest.raises(TypeError, match="Layer A"):
        clamp_to_limits(frame, frame, two_link())  # type: ignore[arg-type]
