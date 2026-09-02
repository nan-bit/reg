"""The declaration record and the scripted policy that emits it.

Three things this file is really about:

* **An invalid declaration cannot be signed**, because it cannot be constructed.
  Every refusal is tested at construction, which is the only place a producer
  gets to refuse — after that the record is in the chain.
* **Declarations are coarse.** One per replan interval, not one per frame, for
  every fixture.
* **The policy is deliberately imperfect.** `declared_violation` declares a bound
  and then commands outside it, and the test asserts the excursion is real at the
  artifact's own stated distance resolution. Its opposite is asserted too: a
  fixture that declares what it will actually do stays inside its bound. Without
  both, the fault taxonomy in Phase 4 has nothing to be demonstrated against.
"""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest
import shapely
from shapely.geometry import MultiPolygon, Point, Polygon
from shapely.ops import unary_union

import reg.declare
from reg.chain import (
    GENESIS_HASH,
    HASH_HEX_LEN,
    KEY_BYTES,
    UNSIGNED_MAC,
    KeyRoleError,
    Keyring,
    MacState,
    chain_hash,
)
from reg.declare import (
    ACTION_CLASSES,
    MAX_GRID_CONFIGS,
    Declaration,
    DeclarationError,
    box_grid,
    declared_region,
    emit_declarations,
    envelope_wkb,
    sign_declaration,
    verify_declaration,
)
from reg.kinematics import ORIGIN_FRAME, BaseFrame, forward_kinematics, link_polygons
from reg.scenarios import SCENARIOS, Scenario
from reg.tolerances import DISTANCE_TOL_M
from reg.types import BasePose, Limits, Obstacle, PoseSource, ProprioState, StateFrame
from reg.world import DEMO_WORLD

KEYRING = Keyring.from_material(
    policy=bytes(range(KEY_BYTES)), enforcement=bytes(range(100, 100 + KEY_BYTES))
)
POLICY_KEY = KEYRING.key("policy")
ENFORCEMENT_KEY = KEYRING.key("enforcement")

LIMITS: Limits = DEMO_WORLD.limits
SEED = 0

# The policy's parameters, stated by the caller because `emit_declarations`
# refuses to invent either of them. Half a second of intent at a 50 Hz stream is
# 25 frames per declaration, which is what "coarse" means here.
REPLAN_S = 0.5
HORIZON_S = 0.5

SQUARE_WKB = envelope_wkb(Polygon([(0, 0), (1, 0), (1, 1), (0, 1)]))


def declaration(**overrides: object) -> Declaration:
    base: dict[str, object] = dict(
        declaration_id="fixture-decl-00000",
        seq=0,
        t_issued=0.0,
        horizon=HORIZON_S,
        action_class="reach",
        declared_envelope=SQUARE_WKB,
        prev_hash=GENESIS_HASH,
        mac=UNSIGNED_MAC,
    )
    base.update(overrides)
    return Declaration(**base)  # type: ignore[arg-type]


def states_of(scenario: Scenario) -> list[ProprioState]:
    """The run, narrowed to Layer A at the call site. See `reg/types.py`."""
    return [frame.proprio() for frame in scenario.states(SEED)]


def emit(scenario: Scenario, **overrides: object) -> tuple[Declaration, ...]:
    kwargs: dict[str, object] = dict(
        key=POLICY_KEY,
        replan_interval_s=REPLAN_S,
        horizon_s=HORIZON_S,
        declared_q_bounds=scenario.declared_q_bounds,
        declared_margin_m=scenario.declared_margin_m,
        id_prefix=scenario.name,
    )
    kwargs.update(overrides)
    return emit_declarations(
        states_of(scenario), scenario.world.limits, **kwargs  # type: ignore[arg-type]
    )


@pytest.fixture(scope="module")
def runs() -> dict[str, tuple[list[ProprioState], tuple[Declaration, ...]]]:
    """Every fixture's states and declarations, emitted once for the module."""
    return {
        name: (states_of(scenario), emit(scenario))
        for name, scenario in SCENARIOS.items()
    }


def body_at(state: ProprioState, limits: Limits) -> Polygon:
    return unary_union(link_polygons(state.q, limits, ORIGIN_FRAME))


def open_at(declarations: tuple[Declaration, ...], t: float) -> Declaration:
    """The declaration in force at `t`: the last one issued at or before it."""
    return [d for d in declarations if d.t_issued <= t][-1]


# --------------------------------------------------------------------------
# The vocabulary, and refusing everything outside it.
# --------------------------------------------------------------------------


def test_the_vocabulary_is_the_five_and_lives_in_one_place() -> None:
    assert ACTION_CLASSES == ("reach", "hold", "retract", "traverse", "escalate")
    assert len(set(ACTION_CLASSES)) == len(ACTION_CLASSES)


@pytest.mark.parametrize(
    "action_class", ["fly", "REACH", "reach ", "", None, 0, "hold\n"]
)
def test_an_out_of_vocabulary_action_class_is_rejected_at_construction(
    action_class: object,
) -> None:
    """NEGATIVE. The producer cannot create one, so it cannot sign one.

    Out-of-vocabulary is a fault Phase 4 detects in records that arrive from
    elsewhere. This side refuses to be the source of one.
    """
    with pytest.raises(DeclarationError, match="not in the vocabulary"):
        declaration(action_class=action_class)


def test_every_vocabulary_word_is_actually_accepted() -> None:
    """The positive half: the refusal above is about the vocabulary, not a typo."""
    for action_class in ACTION_CLASSES:
        assert declaration(action_class=action_class).action_class == action_class


# --------------------------------------------------------------------------
# Construction: an invalid declaration must not exist long enough to be signed.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("declaration_id", "", "non-empty str"),
        ("declaration_id", 17, "non-empty str"),
        ("declaration_id", "has space", "whitespace"),
        ("declaration_id", "has\nnewline", "whitespace"),
        ("seq", -1, "must be >= 0"),
        ("seq", 1.5, "must be an int"),
        ("seq", True, "must be an int"),
        ("t_issued", float("nan"), "non-finite"),
        ("t_issued", "soon", "must be a number"),
        ("horizon", 0.0, "strictly positive"),
        ("horizon", -0.5, "strictly positive"),
        ("horizon", float("inf"), "non-finite"),
        ("declared_envelope", b"", "empty"),
        ("declared_envelope", b"not wkb at all", "not readable as WKB"),
        ("declared_envelope", "a polygon, honest", "must be WKB bytes"),
        ("prev_hash", "nope", "not a SHA-256 hex digest"),
        ("prev_hash", GENESIS_HASH[:-1], "not a SHA-256 hex digest"),
        ("mac", "nope", "neither UNSIGNED_MAC nor"),
        ("mac", "F" * HASH_HEX_LEN, "neither UNSIGNED_MAC nor"),
    ],
)
def test_a_malformed_field_is_refused_at_construction(
    field: str, value: object, match: str
) -> None:
    """NEGATIVE, one per field. Each of these would be unfixable once signed."""
    with pytest.raises(DeclarationError, match=match):
        declaration(**{field: value})


def test_a_declared_envelope_that_is_not_one_region_is_refused() -> None:
    """NEGATIVE. A point, an empty polygon and a self-intersecting one."""
    with pytest.raises(DeclarationError, match="not a Polygon"):
        declaration(declared_envelope=shapely.to_wkb(Point(0, 0)))
    with pytest.raises(DeclarationError, match="empty polygon"):
        declaration(declared_envelope=shapely.to_wkb(Polygon()))
    bowtie = Polygon([(0, 0), (1, 1), (1, 0), (0, 1)])
    assert not bowtie.is_valid
    with pytest.raises(DeclarationError, match="invalid polygon"):
        declaration(declared_envelope=shapely.to_wkb(bowtie))


def test_a_declaration_is_frozen() -> None:
    """An audit record that can be edited after it is signed is not evidence."""
    signed = sign_declaration(declaration(), POLICY_KEY)
    with pytest.raises(dataclasses.FrozenInstanceError):
        signed.t_issued = 9.0  # type: ignore[misc]


def test_the_envelope_round_trips_through_the_record() -> None:
    square = Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])
    assert declaration().envelope().equals(square)
    # Same polygon, same bytes — the WKB goes straight into a hash chain.
    assert envelope_wkb(square) == envelope_wkb(shapely.normalize(square))


@pytest.mark.parametrize("geometry", [Polygon(), Point(0, 0), "square"])
def test_envelope_wkb_refuses_what_is_not_a_usable_polygon(geometry: object) -> None:
    with pytest.raises(DeclarationError):
        envelope_wkb(geometry)  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# Signing.
# --------------------------------------------------------------------------


def test_signing_attaches_a_mac_that_verifies_and_leaves_the_original_alone() -> None:
    unsigned = declaration()
    signed = sign_declaration(unsigned, POLICY_KEY)
    assert not unsigned.is_signed
    assert signed.is_signed
    assert verify_declaration(signed, POLICY_KEY).state is MacState.VALID
    assert verify_declaration(unsigned, POLICY_KEY).state is MacState.COULD_NOT_EVALUATE


def test_re_signing_is_refused() -> None:
    """NEGATIVE. Re-signing replaces one attribution with another that verifies."""
    signed = sign_declaration(declaration(), POLICY_KEY)
    with pytest.raises(DeclarationError, match="already signed"):
        sign_declaration(signed, POLICY_KEY)


def test_the_enforcement_key_cannot_sign_a_declaration() -> None:
    """NEGATIVE. Independence is the mechanism — see docs/plan.md Phase 4."""
    with pytest.raises(KeyRoleError, match="signed by the 'policy' key"):
        sign_declaration(declaration(), ENFORCEMENT_KEY)
    with pytest.raises(KeyRoleError, match="signed by the 'policy' key"):
        emit(SCENARIOS["contact"], key=ENFORCEMENT_KEY)


# --------------------------------------------------------------------------
# The declared region.
# --------------------------------------------------------------------------


def test_a_declared_region_covers_the_bodies_it_was_built_from() -> None:
    configs = np.array([[0.0, 0.0], [0.2, -0.1]])
    region = declared_region(configs, LIMITS, ORIGIN_FRAME)
    assert isinstance(region, Polygon)
    for config in configs:
        assert region.covers(unary_union(link_polygons(config, LIMITS, ORIGIN_FRAME)))


def test_a_declared_region_needs_at_least_one_configuration() -> None:
    """NEGATIVE. An empty bound passes every containment test vacuously."""
    with pytest.raises(DeclarationError, match="non-empty"):
        declared_region(np.zeros((0, 2)), LIMITS, ORIGIN_FRAME)


# --------------------------------------------------------------------------
# A base that moved. Nothing in this repository has one — every fixture states
# four zero base bounds — so these build the frames explicitly, which is the
# only way the seam docs/mobile-base.md §7 cut is exercised at all.
# --------------------------------------------------------------------------

#: Two frames far enough apart that the arm at one cannot touch the arm at the
#: other: this arm reaches 0.9 m and its body 0.95 m. Not a tolerance — the
#: distance is chosen so the disconnection is a fact about the geometry rather
#: than a near miss.
DRIVEN_BASES = (ORIGIN_FRAME, BaseFrame(x=3.0, y=0.0, theta=0.0))


def broken_link_polygons(config, limits, base):  # type: ignore[no-untyped-def]
    """Kinematics that has lost the base: two bodies, neither containing it.

    This is the failure the `MultiPolygon` refusal is against, and there is no
    honest way to produce it from `reg.kinematics` — every configuration's first
    link contains the base, which is exactly the argument. So it is injected.
    """
    x = 10.0 * float(config[0])
    return [Point(x, 0.0).buffer(0.1), Point(x + 5.0, 0.0).buffer(0.1)]


def test_a_declared_region_spanning_a_moved_base_is_the_union_actually_swept() -> None:
    """The vehicle drove, the two arms do not touch, and that region is correct.

    docs/mobile-base.md §4 item 5: the connectedness argument was an argument
    about the base being one point, and it does not survive the base moving. The
    assertion is the region rather than the type alone — it covers the body at
    each frame and claims nothing over the ground the vehicle drove across.
    """
    configs = np.array([[0.3, -0.4], [0.3, -0.4]])
    region = declared_region(configs, LIMITS, DRIVEN_BASES)

    assert isinstance(region, MultiPolygon)
    assert len(region.geoms) == 2
    for config, frame in zip(configs, DRIVEN_BASES, strict=True):
        assert region.covers(unary_union(link_polygons(config, LIMITS, frame)))
    # And nothing wider: the gap between the two poses is not part of the claim.
    assert not region.intersects(Point(1.5, 0.0))
    assert region.area == pytest.approx(
        sum(
            unary_union(link_polygons(config, LIMITS, frame)).area
            for config, frame in zip(configs, DRIVEN_BASES, strict=True)
        )
    )


def test_a_moved_base_whose_poses_do_overlap_is_still_one_polygon() -> None:
    """The base moving is permission, not a mode: a connected union stays one."""
    configs = np.array([[0.3, -0.4], [0.3, -0.4]])
    nearby = (ORIGIN_FRAME, BaseFrame(x=0.1, y=0.0, theta=0.0))
    assert isinstance(declared_region(configs, LIMITS, nearby), Polygon)


def test_a_disconnected_region_is_refused_when_the_base_did_not_move(
    monkeypatch,
) -> None:
    """NEGATIVE. The refusal is conditioned on the base, not dropped.

    With one frame the connectedness argument still holds, so a disconnected
    union is still a broken grid or broken kinematics and is still refused —
    fed here the geometry it guards against. The same broken geometry under a
    base that moved is accepted, which is what makes the distinction the *base*
    rather than a property of the polygons.
    """
    monkeypatch.setattr(reg.declare, "link_polygons", broken_link_polygons)
    one = np.zeros((1, 2))

    with pytest.raises(DeclarationError, match="under a base that did not move"):
        declared_region(one, LIMITS, ORIGIN_FRAME)
    # A sequence of identical frames is the same statement, and is refused too.
    with pytest.raises(DeclarationError, match="under a base that did not move"):
        declared_region(one, LIMITS, (ORIGIN_FRAME,))

    two = np.zeros((2, 2))
    accepted = declared_region(two, LIMITS, DRIVEN_BASES)
    assert isinstance(accepted, MultiPolygon)


def test_a_disconnected_region_cannot_be_signed_into_the_record() -> None:
    """NEGATIVE. The record did not widen with `declared_region`, and says so.

    A multi-part declared bound changes what every containment test in Phase 4
    means, so it is refused loudly where the bytes are made rather than absorbed
    — a could-not-evaluate a reader can see, not a bound nobody can test.
    """
    region = declared_region(np.array([[0.3, -0.4], [0.3, -0.4]]), LIMITS, DRIVEN_BASES)
    with pytest.raises(DeclarationError, match="takes a Polygon"):
        envelope_wkb(region)
    with pytest.raises(DeclarationError, match="not a single valid polygon|MultiPolygon"):
        declaration(declared_envelope=shapely.to_wkb(region))


@pytest.mark.parametrize(
    ("bases", "match"),
    [
        (None, "must be a BaseFrame or a sequence"),
        ("origin", "must be a BaseFrame or a sequence"),
        ((ORIGIN_FRAME,), "1 base frames for 2 configurations"),
        ((ORIGIN_FRAME, ORIGIN_FRAME, ORIGIN_FRAME), "3 base frames for 2"),
        ((ORIGIN_FRAME, None), r"bases\[1\] is a NoneType"),
        (
            (ORIGIN_FRAME, BasePose(x=1.0, y=0.0, theta=0.0, source=PoseSource.LOCALIZED)),
            r"bases\[1\] is a BasePose",
        ),
    ],
)
def test_a_base_frame_nobody_stated_is_refused(bases: object, match: str) -> None:
    """NEGATIVE. No default frame, and no room-frame pose through the back door.

    The last case is the one with teeth: a `BasePose` has `x`, `y` and `theta`
    too, so anything structural would accept it and a Layer B room pose would
    place a region tagged Layer A. `reg.kinematics._base_frame` refuses it for
    the same reason, and this refuses it before the geometry is touched.
    """
    with pytest.raises(DeclarationError, match=match):
        declared_region(np.zeros((2, 2)), LIMITS, bases)  # type: ignore[arg-type]


def test_the_box_grid_resolution_is_derived_from_the_geometry() -> None:
    """Adjacent grid poses must overlap, or the union is a comb of slabs.

    The criterion is `dq * reach <= link_radius`, so the assertion is the
    property itself rather than a sample count: consecutive configurations along
    a joint have overlapping bodies.
    """
    grid = box_grid(((-0.4, 0.8), (0.0, 0.0)), LIMITS)
    assert grid.shape[1] == 2
    assert len(grid) > 2
    bodies = [unary_union(link_polygons(config, LIMITS, ORIGIN_FRAME)) for config in grid]
    assert all(a.intersects(b) for a, b in zip(bodies, bodies[1:]))
    # A wider box is sampled at the same resolution, so it needs more of them.
    assert len(box_grid(((-0.8, 1.6), (0.0, 0.0)), LIMITS)) > len(grid)
    # A degenerate box is one configuration, not zero and not an error.
    assert len(box_grid(((0.5, 0.5), (0.25, 0.25)), LIMITS)) == 1


def test_a_box_too_wide_to_sample_is_refused_not_sampled_coarser() -> None:
    """NEGATIVE. A coarser grid would silently return a region with gaps in it."""
    with pytest.raises(DeclarationError, match=f"over the {MAX_GRID_CONFIGS}"):
        box_grid(((-1000.0, 1000.0), (-1000.0, 1000.0)), LIMITS)


@pytest.mark.parametrize(
    ("box", "match"),
    [
        (((0.0, 1.0),), "one \\(lo, hi\\) pair per joint"),
        (((0.0, 1.0), (0.0, 1.0), (0.0, 1.0)), "one \\(lo, hi\\) pair per joint"),
        (((0.0, 1.0), (1.0, 0.0)), "inverted"),
        (((0.0, 1.0), (0.0, float("nan"))), "non-finite"),
        (((0.0, 1.0), 0.5), "is not \\(lo, hi\\)"),
    ],
)
def test_a_malformed_joint_box_is_refused(box: object, match: str) -> None:
    with pytest.raises(DeclarationError, match=match):
        box_grid(box, LIMITS)  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# The scripted policy.
# --------------------------------------------------------------------------


def test_declarations_are_coarse_for_every_fixture(runs) -> None:
    """One per replan interval, not one per frame — for all six, not one.

    The assertion is the ratio rather than a count: at 50 Hz and a 0.5 s replan
    interval there are 25 frames per declaration, so an implementation that
    slipped to one per frame, or to one per second, fails here.
    """
    for name, (states, declarations) in runs.items():
        scenario = SCENARIOS[name]
        expected = int(scenario.duration / REPLAN_S) + 1
        assert len(declarations) == expected, name
        assert len(declarations) * 10 < len(states), name


def test_a_run_is_a_chain_of_signed_monotonic_declarations(runs) -> None:
    for name, (_states, declarations) in runs.items():
        assert [d.seq for d in declarations] == list(range(len(declarations))), name
        assert len({d.declaration_id for d in declarations}) == len(declarations), name
        assert all(d.horizon == HORIZON_S for d in declarations), name
        assert all(d.action_class in ACTION_CLASSES for d in declarations), name

        times = [d.t_issued for d in declarations]
        assert times == sorted(times) and len(set(times)) == len(times), name

        expected = GENESIS_HASH
        for d in declarations:
            assert d.prev_hash == expected, name
            assert verify_declaration(d, POLICY_KEY).state is MacState.VALID, name
            expected = chain_hash(d, d.prev_hash)


def test_declarations_cover_the_run_without_a_gap(runs) -> None:
    """Consecutive declarations are issued within their own validity window.

    A gap would be a stale-declaration fault manufactured by the producer, which
    would make Phase 4's real one indistinguishable from this module's bug.
    """
    for name, (states, declarations) in runs.items():
        for earlier, later in zip(declarations, declarations[1:]):
            assert later.t_issued <= earlier.t_issued + earlier.horizon, name
        last = declarations[-1]
        assert states[-1].t <= last.t_issued + last.horizon, name


def test_emission_is_deterministic_and_the_seed_still_does_something() -> None:
    scenario = SCENARIOS["near_miss"]
    first = emit(scenario)
    assert first == emit(scenario)

    other = emit_declarations(
        [f.proprio() for f in scenario.states(1)],
        scenario.world.limits,
        key=POLICY_KEY,
        replan_interval_s=REPLAN_S,
        horizon_s=HORIZON_S,
        declared_q_bounds=scenario.declared_q_bounds,
        declared_margin_m=scenario.declared_margin_m,
        id_prefix=scenario.name,
    )
    assert [d.mac for d in other] != [d.mac for d in first]


def test_a_declared_margin_widens_the_claim_and_nothing_else() -> None:
    """The padded claim, and the two things that make it a claim rather than a bug.

    It has to be strictly wider than the unpadded one — a margin that changed
    nothing would be a fixture parameter with no effect, and
    `reg.scenarios.ENVELOPE_OVERCLAIM` would produce no fault while claiming
    one. And it has to leave the rest of the record alone: same count, same
    times, same classes, same sequence, so a padded declaration is
    indistinguishable from an honest one to every reader except one that
    recomputes what the robot can reach.
    """
    scenario = SCENARIOS["contact"]
    honest = emit(scenario, declared_margin_m=None)
    padded = emit(scenario, declared_margin_m=0.25)

    assert len(padded) == len(honest)
    for wide, plain in zip(padded, honest, strict=True):
        assert wide.envelope().area > plain.envelope().area
        assert wide.envelope().covers(plain.envelope())
        assert (wide.seq, wide.t_issued, wide.horizon, wide.action_class) == (
            plain.seq,
            plain.t_issued,
            plain.horizon,
            plain.action_class,
        )
    # ...and the padding is the *only* difference, so the MACs must differ: a
    # padded run that chained identically would be one no auditor could tell
    # apart from the honest one.
    assert [d.mac for d in padded] != [d.mac for d in honest]


def test_the_declared_violation_fixture_really_violates_its_declaration(runs) -> None:
    """The fixture Phase 4 exists to catch, and the reason it has to be wired.

    The policy declares `DECLARED_VIOLATION.declared_q_bounds` — the same fixed
    bound in every interval, independent of what it then does — and later
    commands q0 out to 1.5 rad. The excursion is asserted at `DISTANCE_TOL_M`,
    the resolution this artifact advertises, so it is a real excursion and not a
    boundary artefact of the geometry.
    """
    scenario = SCENARIOS["declared_violation"]
    states, declarations = runs[scenario.name]
    limits = scenario.world.limits

    # One fixed claim, not a claim that follows the arm around.
    assert len({d.declared_envelope for d in declarations}) == 1

    outside = [
        state
        for state in states
        if not open_at(declarations, state.t)
        .envelope()
        .buffer(DISTANCE_TOL_M)
        .covers(body_at(state, limits))
    ]
    assert outside, "the fixture no longer violates its declaration"
    assert max(float(state.q[0]) for state in outside) > scenario.declared_q_bounds[0][1]


def test_a_policy_that_declares_what_it_will_do_stays_inside_its_bound(runs) -> None:
    """The other half. Without it, the test above could pass on a broken region.

    `contact` declares no fixed box, so the policy declares the region its own
    upcoming configurations sweep — and every commanded pose is then inside the
    declaration in force at that instant.
    """
    scenario = SCENARIOS["contact"]
    states, declarations = runs[scenario.name]
    limits = scenario.world.limits
    for state in states:
        region = open_at(declarations, state.t).envelope()
        assert region.buffer(DISTANCE_TOL_M).covers(body_at(state, limits)), state.t


def test_the_action_class_follows_the_motion() -> None:
    """Crude on purpose, and therefore easy to state: no threshold anywhere."""

    def classes(q_of_t) -> list[str]:
        states = [
            ProprioState(
                t=k * 0.02,
                q=np.asarray(q_of_t(k), dtype=float),
                qd=np.zeros(2),
                base_vel=None,
            )
            for k in range(26)
        ]
        return [
            d.action_class
            for d in emit_declarations(
                states,
                LIMITS,
                key=POLICY_KEY,
                replan_interval_s=REPLAN_S,
                horizon_s=HORIZON_S,
                declared_q_bounds=None,
                declared_margin_m=None,
                id_prefix="synthetic",
            )
        ]

    # Not moving at all is a hold — exact equality, not "moved less than x".
    assert classes(lambda k: (0.3, 0.6))[0] == "hold"
    # Unfolding the elbow puts the tip further from the base; folding it back
    # brings it closer.
    assert classes(lambda k: (0.0, 1.6 - 0.02 * k))[0] == "reach"
    assert classes(lambda k: (0.0, 0.6 + 0.02 * k))[0] == "retract"
    # Rotating the whole arm about the base changes neither.
    assert classes(lambda k: (0.02 * k, 1.0))[0] == "traverse"


def test_driving_the_base_is_not_reaching() -> None:
    """NEGATIVE, docs/mobile-base.md §4 item 6. The arm did not extend at all.

    The frozen arm is carried forward by the vehicle, so the end effector's
    distance from the **origin** grows — asserted here, because that growth is
    the defect, and a test that only checked the answer would still pass if the
    measurement quietly went back to the origin. In the body frame the extension
    is unchanged, which is a `traverse` by the existing tie rule.

    It is not a `hold` either: a `hold` is a robot that is not moving, and this
    one is. That is why the `hold` branch asks about the base as well.
    """
    frozen = np.array([[0.2, 0.6]] * 3)
    driving = tuple(BaseFrame(x=0.4 * k, y=0.0, theta=0.0) for k in range(3))

    from_origin = [
        float(np.linalg.norm(forward_kinematics(q, LIMITS, frame)[-1][1]))
        for q, frame in zip(frozen, driving, strict=True)
    ]
    assert from_origin[-1] > from_origin[0], (
        "the fixture no longer drives the base away from the origin, so it no "
        "longer exercises the defect"
    )

    assert reg.declare._classify(frozen, LIMITS, driving) == "traverse"
    # The same frozen arm on a base that did not move is still a hold.
    assert reg.declare._classify(frozen, LIMITS, ORIGIN_FRAME) == "hold"
    assert reg.declare._classify(frozen, LIMITS, (driving[0],) * 3) == "hold"


def test_the_extension_is_bit_identical_under_every_base_frame() -> None:
    """**The test the first version of `_extension` needed and did not have.**

    That version measured the tip in the room frame and subtracted the base
    back, asserting in its docstring that translating or rotating the base
    "moves both ends of the subtraction and leaves this number alone". True in
    exact arithmetic; false in floating point, because a rotated base sends the
    tip through `cos` and `sin` first. The classification compares extensions
    exactly, so an ULP decided `traverse` against `retract` — and it tied on the
    machine that wrote it and lost in CI.

    An invariant a docstring claims and nothing checks is the defect. This
    asserts bit-identity, not closeness: `assert_allclose` would have passed the
    broken version, which is why it is `==` on the raw float.
    """
    config = np.array([0.2, 0.6])
    reference = reg.declare._extension(config, LIMITS)
    for frame in (
        ORIGIN_FRAME,
        BaseFrame(x=3.0, y=-2.0, theta=0.0),
        BaseFrame(x=0.0, y=0.0, theta=0.5),
        BaseFrame(x=-7.25, y=11.5, theta=2.3),
    ):
        # The signature no longer accepts a frame at all — that absence is the
        # point — so the invariance is asserted where it can still be observed:
        # the same configuration under any base is the same declared extension.
        moved = np.array([[0.2, 0.6]] * 3)
        assert reg.declare._classify(moved, LIMITS, frame) == "hold"
        assert reg.declare._extension(config, LIMITS) == reference


def test_base_rotation_does_not_enter_the_classification_either() -> None:
    """Yaw moves the end effector in the room and changes no extension."""
    frozen = np.array([[0.2, 0.6]] * 3)
    turning = tuple(BaseFrame(x=0.0, y=0.0, theta=0.5 * k) for k in range(3))
    assert reg.declare._classify(frozen, LIMITS, turning) == "traverse"


@pytest.mark.parametrize(
    ("configs", "base_x", "expected"),
    [
        (((0.0, 1.6), (0.0, 0.6)), -0.9, "reach"),
        (((0.0, 0.6), (0.0, 1.6)), 2.0, "retract"),
    ],
)
def test_the_arm_is_classified_by_its_own_extension_while_the_base_drives(
    configs: tuple[tuple[float, float], ...], base_x: float, expected: str
) -> None:
    """The other half: base motion must not *mask* a real reach or retract.

    The base drives far enough that the end effector's distance from the origin
    moves the opposite way from the arm's own extension — so the measurement
    this replaces would return the wrong one of the two, not merely a spurious
    one. Asserted, so the fixture cannot decay into agreeing with both.
    """
    array = np.asarray(configs, dtype=float)
    driving = (ORIGIN_FRAME, BaseFrame(x=base_x, y=0.0, theta=0.0))
    from_origin = [
        float(np.linalg.norm(forward_kinematics(q, LIMITS, frame)[-1][1]))
        for q, frame in zip(array, driving, strict=True)
    ]
    assert (from_origin[-1] > from_origin[0]) is not (expected == "reach"), (
        "the base no longer drives against the arm's own extension"
    )
    assert reg.declare._classify(array, LIMITS, driving) == expected


#: Every fixture's `action_class` sequence, as this repository has published it.
#: Recorded rather than derived, because the point of the entry is that the
#: body-frame measurement did not move a single one of them: every fixture is a
#: **fixed base** — four zero base bounds, asserted below — and for a base at
#: one point the extension from the base and the distance from the origin are
#: the same number. docs/mobile-base.md §5: no published figure moves.
FIXTURE_ACTION_CLASSES: dict[str, tuple[str, ...]] = {
    "approach_and_retreat": (
        "reach", "reach", "reach", "reach", "reach", "reach",
        "retract", "retract", "retract", "retract", "retract", "retract",
        "hold",
    ),
    "near_miss": (
        "reach", "reach", "reach", "reach", "reach",
        "retract", "retract", "retract", "retract", "retract",
        "hold",
    ),
    "contact": (
        "reach", "reach", "reach", "reach", "reach", "reach",
        "retract", "retract", "retract", "retract",
        "hold",
    ),
    "static_bystander": (
        "reach", "reach", "reach", "retract", "retract", "retract",
        "reach", "reach", "reach", "retract", "retract", "retract",
        "hold",
    ),
    "sustained_overlap": (
        "retract", "retract", "retract", "retract", "retract", "retract",
        "reach", "reach", "reach", "reach", "reach", "reach",
        "hold",
    ),
    "declared_violation": (
        "reach", "reach", "reach", "reach", "reach", "reach", "reach",
        "retract", "retract", "retract",
        "hold",
    ),
    "no_declaration": ("reach", "reach", "retract", "retract", "hold"),
    "stale_declaration": (
        "reach", "reach", "reach", "reach", "reach", "reach", "hold",
    ),
    "escalation_failure": (
        "reach", "reach", "reach", "reach", "reach", "reach", "reach", "reach",
        "hold",
    ),
    "envelope_overclaim": ("reach", "reach", "retract", "retract", "hold"),
    "out_of_vocabulary_action": ("reach", "reach", "retract", "retract", "hold"),
}


def test_every_fixture_classification_is_unchanged(runs) -> None:
    """Asserted rather than assumed — the whole claim of the change above.

    The table is exhaustive over `SCENARIOS`, so a fixture added without a
    recorded sequence fails here rather than being classified silently.
    """
    assert set(FIXTURE_ACTION_CLASSES) == set(SCENARIOS)
    for name, (_states, declarations) in runs.items():
        limits = SCENARIOS[name].world.limits
        assert all(
            float(getattr(limits, field)) == 0.0
            for field in type(limits).BASE_BOUND_FIELDS
        ), (
            f"{name} has a base that can drive, so the table below is no longer "
            "a table of fixed-base classifications"
        )
        assert tuple(d.action_class for d in declarations) == (
            FIXTURE_ACTION_CLASSES[name]
        ), name


def test_the_scripted_policy_never_escalates(runs) -> None:
    """Deliberate: Phase 4's escalation-failure fault needs a policy that doesn't.

    Not an accident of these fixtures — the emitter has no branch that can
    produce it, and this is the test that fails if someone adds one.
    """
    for name, (_states, declarations) in runs.items():
        assert "escalate" not in {d.action_class for d in declarations}, name


# --------------------------------------------------------------------------
# What the policy refuses to be handed.
# --------------------------------------------------------------------------


def test_the_policy_takes_proprioception_and_refuses_a_state_frame() -> None:
    """The Layer boundary, at the one place a run's frames enter this module.

    A `StateFrame` has `.q` and `.qd` and would duck-type straight through,
    carrying `human_pos` and the obstacle set into the module that builds a
    Layer A record.
    """
    frame = StateFrame(
        t=0.0,
        q=np.zeros(2),
        qd=np.zeros(2),
        human_pos=np.array([1.0, 1.0]),
        human_vel=np.zeros(2),
        base_vel=None,
        base_pose=None,
        objects=(Obstacle("obs_0", "box", 1.0, 1.0, 0.2),),
    )
    with pytest.raises(DeclarationError, match=r"narrow a StateFrame with .proprio"):
        emit_declarations(
            [frame],
            LIMITS,
            key=POLICY_KEY,
            replan_interval_s=REPLAN_S,
            horizon_s=HORIZON_S,
            declared_q_bounds=None,
            declared_margin_m=None,
            id_prefix="leak",
        )


def test_the_declare_module_holds_no_layer_b_type() -> None:
    """Nothing in `reg.declare`'s namespace names anything outside the robot.

    Same check `tests/test_envelope.py` makes for the envelope. The policy is
    the black channel and could in principle see the world; this record builder
    is not where that would be allowed to happen.
    """
    import reg.declare as module

    forbidden = {"Obstacle", "StateFrame", "World", "Scenario"}
    assert forbidden.isdisjoint(vars(module))


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"replan_interval_s": 0.0}, "strictly positive"),
        ({"replan_interval_s": -1.0}, "strictly positive"),
        ({"replan_interval_s": float("nan")}, "non-finite"),
        ({"horizon_s": REPLAN_S / 2}, "shorter than replan_interval_s"),
        ({"id_prefix": ""}, "non-empty str"),
        ({"declared_q_bounds": ((0.0, 1.0),)}, "one \\(lo, hi\\) pair per joint"),
        ({"declared_q_bounds": ((1.0, 0.0), (0.0, 1.0))}, "inverted"),
        ({"declared_margin_m": 0.0}, "strictly positive"),
        ({"declared_margin_m": -0.1}, "strictly positive"),
        ({"declared_margin_m": float("nan")}, "non-finite"),
    ],
)
def test_the_policy_refuses_parameters_it_cannot_act_on(
    overrides: dict, match: str
) -> None:
    """NEGATIVE. None of these has a default; each is named when it is wrong."""
    with pytest.raises(DeclarationError, match=match):
        emit(SCENARIOS["contact"], **overrides)


def test_the_policy_refuses_a_run_that_is_not_a_run() -> None:
    with pytest.raises(DeclarationError, match="no states to declare over"):
        emit_declarations(
            [],
            LIMITS,
            key=POLICY_KEY,
            replan_interval_s=REPLAN_S,
            horizon_s=HORIZON_S,
            declared_q_bounds=None,
            declared_margin_m=None,
            id_prefix="empty",
        )

    backwards = [
        ProprioState(t=0.0, q=np.zeros(2), qd=np.zeros(2), base_vel=None),
        ProprioState(t=0.0, q=np.zeros(2), qd=np.zeros(2), base_vel=None),
    ]
    with pytest.raises(DeclarationError, match="does not follow"):
        emit_declarations(
            backwards,
            LIMITS,
            key=POLICY_KEY,
            replan_interval_s=REPLAN_S,
            horizon_s=HORIZON_S,
            declared_q_bounds=None,
            declared_margin_m=None,
            id_prefix="backwards",
        )


def test_a_replan_interval_longer_than_the_run_yields_exactly_one_declaration() -> None:
    scenario = SCENARIOS["contact"]
    declarations = emit(
        scenario, replan_interval_s=scenario.duration * 2, horizon_s=scenario.duration * 2
    )
    assert len(declarations) == 1
    assert declarations[0].seq == 0
    assert declarations[0].prev_hash == GENESIS_HASH
