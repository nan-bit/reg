"""The fixtures, tested against what their names claim.

A scenario called `contact` that never produces a contact is worse than no
fixture at all: every downstream test written against it passes for the wrong
reason, and the incident report in Phase 7 gets built on a run where nothing
happened. So the interesting tests here are the paired ones — `contact` must
intersect a link polygon and `static_bystander` must never do so — and they run
across several seeds, because a fixture that only holds for seed 0 is a golden
value in disguise.

The five fault fixtures (issue #46) are held to the same standard and by the
same tests: they are in `EXPECTED_NAMES`, so every invariant here — room
containment, obstacle clearance, joint limits, monotonic time, frozen arrays,
determinism under seed — applies to them unchanged, and none of them is
exempted. What this file cannot check is the half that gives them their names:
whether the fault actually fires needs the real enforcer over the real
declarations, and that lives in `tests/test_enforce.py`. What it checks instead
is the *arrangement* — that each one is one policy behaviour away from a clean
run, that no two share a behaviour, and that the catalogue covers every semantic
fault and no transport one.

Where a name claims something about the *reachable set*, the claim is checked
against `reg.envelope.compute_envelope` itself, not against the workspace disc.
The disc is a superset of the envelope, so asserting a positive claim against it
proves nothing the name says: a human standing in the disc can be a long way
from anywhere the arm can get to inside the horizon. That is the direction the
looseness runs, and it is why three fixtures once passed while overlapping
nothing (issue #22).
"""

from __future__ import annotations

import dataclasses
import itertools

import numpy as np
import pytest
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import unary_union

from reg.enforce import FAULTS
from reg.envelope import compute_envelope, outer_envelope
from reg.scenarios import (
    DEFAULT_DT,
    MOBILE_LIMITS,
    MOBILE_SCENARIOS,
    MOBILE_WORLD,
    SCENARIOS,
    Scenario,
    Waypoint,
    scenario,
)
from reg.kinematics import ORIGIN_FRAME, link_polygons
from reg.types import (
    Limits,
    LimitSource,
    Obstacle,
    PoseSource,
    ProprioState,
    VelocitySource,
)
import reg.world
from reg.world import DEMO_WORLD, LIMITS, ROOM, Room, World

#: Several seeds, fixed. Every semantic claim a scenario name makes must hold for
#: all of them — the seed perturbs waypoints, it does not change the situation.
SEEDS = (0, 1, 7, 123, 20260818)

EXPECTED_NAMES = [
    "approach_and_retreat",
    "near_miss",
    "contact",
    "static_bystander",
    "sustained_overlap",
    "declared_violation",
    # The five fault fixtures (issue #46). Every invariant above applies to them
    # unchanged — they are runs, not exemptions — and the fault each one produces
    # is asserted end to end against the real enforcer in tests/test_enforce.py,
    # which is the only place that can say whether the name is true.
    "no_declaration",
    "stale_declaration",
    "escalation_failure",
    "envelope_overclaim",
    "out_of_vocabulary_action",
]

#: The three mobile fixtures (issue #178), in `MOBILE_SCENARIOS` and
#: deliberately not in `SCENARIOS` — see `test_the_mobile_fixtures_are_a_second
#: _catalogue_and_not_an_addition_to_the_first`. They are held to every generic
#: invariant in this file that is about a *run* rather than about a bolted base:
#: monotonic time, determinism under seed, joint limits, the room, the
#: obstacles, the arm's acceleration bound. A fixture that drove would be a poor
#: place to start relaxing any of those.
MOBILE_NAMES = [
    "mobile_transit",
    "mobile_frozen_arm",
    "mobile_overclaim",
]

#: Every fixture in the package, for the invariants that hold of both kinds.
ALL_NAMES = EXPECTED_NAMES + MOBILE_NAMES

#: The six faults in `reg.enforce.FAULTS` that are about what a declaration
#: *meant*. Each one has a fixture, which is the claim issue #46 makes.
SEMANTIC_FAULTS = {
    "no_declaration",
    "stale_declaration",
    "declaration_action_mismatch",
    "envelope_overclaim",
    "out_of_vocabulary_action",
    "escalation_failure",
}

#: The three that are about the channel. No fixture, deliberately: they are
#: PROFIsafe's (docs/prior-art.md §5) and stay unit-tested, because a fixture
#: producing one would need this module to hold a key and forge a MAC.
TRANSPORT_FAULTS = {"unattributed", "replay_or_reorder", "watchdog_expiry"}


# --------------------------------------------------------------------------
# A local forward-kinematics helper.
#
# reg/kinematics.py (issue #7) will provide this properly. The duplication is
# deliberate and stays: this file must be able to check what the fixtures do
# without depending on a module that does not exist yet, and an independent
# reimplementation is a stronger check of a fixture than calling the same code
# the fixture would eventually call. Nine lines is a cheap price for that.
# --------------------------------------------------------------------------
def link_polygons(q: np.ndarray, limits: Limits) -> list[Polygon]:
    # The bolted base, from `reg.kinematics.ORIGIN_FRAME` rather than from a
    # literal: since issue #184 that is this repository's only statement of
    # where a base that does not move is, and `grep ORIGIN_FRAME` is meant to
    # be the list of places the assumption is made.
    points = [np.array([ORIGIN_FRAME.x, ORIGIN_FRAME.y], dtype=float)]
    angle = 0.0
    for j, length in enumerate(limits.link_lengths):
        angle += float(q[j])
        points.append(points[-1] + length * np.array([np.cos(angle), np.sin(angle)]))
    return [
        LineString([points[i], points[i + 1]]).buffer(limits.link_radius, cap_style=2)
        for i in range(len(points) - 1)
    ]


def human_polygon(pos: np.ndarray) -> Polygon:
    return Point(float(pos[0]), float(pos[1])).buffer(DEMO_WORLD.human_radius)


def touches_body(frame) -> bool:
    """Whether the human disc intersects any link polygon at this frame."""
    human = human_polygon(frame.human_pos)
    return any(human.intersects(p) for p in link_polygons(frame.q, DEMO_WORLD.limits))


def in_workspace_disc(frame) -> bool:
    """Whether the human disc overlaps the disc the robot body can occupy.

    **Negative claims only.** This is the *workspace* disc — every configuration,
    no horizon — so it strictly contains the forward reachable envelope for any
    horizon and any sampling (`reg/world.py`, `World.max_reach`). Clearing it
    therefore clears every envelope inside it, which is a stronger statement than
    clearing the one envelope `in_envelope` computes, and that is why
    `static_bystander` still asserts it.

    In the positive direction it claims nothing a fixture name means: a human
    standing inside the disc may be nowhere near the region the arm can actually
    reach within the horizon. Use `in_envelope` for those.
    """
    reach = DEMO_WORLD.max_reach + DEMO_WORLD.human_radius
    return float(np.hypot(*frame.human_pos)) < reach


# --------------------------------------------------------------------------
# The real envelope, and the arguments it is called with.
#
# Stated here rather than inherited from `compute_envelope`'s defaults: the
# fixtures are hand-tuned against these numbers, so a change to the defaults has
# to surface as a failure in this file rather than silently re-baseline what the
# fixture names mean. `horizon` and `substep_dt` are the Phase 2 / Phase 1
# figures from docs/plan.md.
#
# `n_samples=4` is the 2**2 corner controls of a two-joint arm, which is the
# fewest `compute_envelope` accepts and therefore the *smallest* envelope it will
# return: the sample set for a larger `n_samples` is a strict superset of this
# one (reg/envelope.py, asserted by tests/test_envelope.py), so a claim of the
# form "the human is inside the envelope" proved here holds for every richer
# sampling too. It is also ~250x cheaper than the 1000-sample default, and these
# checks run per frame, per seed. The direction of that looseness is why
# `static_bystander`'s negative claim keeps the workspace disc alongside it: the
# smallest envelope is the weakest thing to be outside of.
# --------------------------------------------------------------------------
ENVELOPE_HORIZON = 0.2
ENVELOPE_SUBSTEP_DT = 0.02
ENVELOPE_SAMPLES = 4
ENVELOPE_SEED = 0


def envelope_of(frame) -> Polygon:
    """The frame's forward reachable set, from `reg.envelope`. Layer A in, only.

    `.proprio()` is the narrowing: the envelope never sees `human_pos`, which is
    the whole point of computing the human's overlap with it afterwards.
    """
    return compute_envelope(
        frame.proprio(),
        DEMO_WORLD.limits,
        horizon=ENVELOPE_HORIZON,
        n_samples=ENVELOPE_SAMPLES,
        seed=ENVELOPE_SEED,
        substep_dt=ENVELOPE_SUBSTEP_DT,
    )


def in_envelope(frame) -> bool:
    """Whether the human disc intersects the arm's forward reachable set.

    This is the check the fixture names are actually about — "reachable within
    the horizon", not "somewhere in the workspace". Bear in mind that
    `compute_envelope` is an under-approximation: a `True` here is sound (that
    region really is reachable), a `False` is not a guarantee of separation.
    """
    return human_polygon(frame.human_pos).intersects(envelope_of(frame))


def frames(name: str, seed: int) -> list:
    return list(scenario(name).states(seed))


# --------------------------------------------------------------------------
# The catalogue
# --------------------------------------------------------------------------


def test_scenarios_are_exactly_the_named_catalogue() -> None:
    assert list(SCENARIOS) == EXPECTED_NAMES, (
        "SCENARIOS is the authoritative list; these names are the fixtures the "
        "whole project is measured against, so adding or dropping one is a "
        "change to what is being claimed."
    )


def test_every_semantic_fault_has_a_fixture_and_no_transport_fault_does() -> None:
    """The catalogue's coverage of the taxonomy, asserted rather than described.

    Both halves are the claim. Every *semantic* fault has a run that produces
    it, because an incident report can only narrate what a run produced and five
    of the six had never occurred in one (issue #46). No *transport* fault has
    one, because those are PROFIsafe's and a fixture that produced one would
    have to forge a MAC or reorder a stream — which would make this module a
    party to the attribution it is supposed to be evidence about.
    """
    covered = {sc.fault for sc in SCENARIOS.values() if sc.fault is not None}
    assert covered == SEMANTIC_FAULTS
    assert covered.isdisjoint(TRANSPORT_FAULTS)
    assert SEMANTIC_FAULTS | TRANSPORT_FAULTS == set(FAULTS), (
        "the taxonomy moved. A fault added to reg.enforce is either semantic — "
        "and needs a fixture here — or transport, and needs a stated reason not "
        "to have one."
    )
    # One fixture per fault, not two arguing about the same one.
    faults = [sc.fault for sc in SCENARIOS.values() if sc.fault is not None]
    assert len(faults) == len(set(faults))


def test_each_fault_fixture_is_named_for_the_fault_it_produces() -> None:
    """`declared_violation` is the one exception, and it predates the taxonomy."""
    for name, sc in SCENARIOS.items():
        if sc.fault is None or name == "declared_violation":
            continue
        assert name == sc.fault, (
            f"fixture {name!r} produces {sc.fault!r}. A fixture whose name and "
            "fault disagree is one every reader has to check twice."
        )


def test_each_scenario_is_keyed_by_its_own_name() -> None:
    for key, sc in SCENARIOS.items():
        assert sc.name == key


def test_scenario_lookup_names_the_alternatives_when_it_fails() -> None:
    """Negative test: an unknown name fails loudly, not with an empty result."""
    with pytest.raises(KeyError, match="unknown scenario"):
        scenario("contakt")


# --------------------------------------------------------------------------
# Frames, timing, determinism
# --------------------------------------------------------------------------


@pytest.mark.parametrize("name", ALL_NAMES)
def test_every_scenario_produces_frames(name: str) -> None:
    got = frames(name, seed=0)
    sc = scenario(name)
    assert len(got) == sc.n_frames > 1
    assert len(got) == int(round(sc.duration / sc.dt)) + 1
    for f in got:
        assert f.q.shape == (len(sc.world.limits.link_lengths),)
        assert f.qd.shape == f.q.shape
        assert f.human_pos.shape == (2,)
        assert f.human_vel.shape == (2,)


@pytest.mark.parametrize("name", ALL_NAMES)
def test_timestamps_are_monotonic_at_the_stated_dt(name: str) -> None:
    sc = scenario(name)
    times = np.array([f.t for f in sc.states(seed=0)])
    assert times[0] == 0.0
    assert np.all(np.diff(times) > 0.0)
    assert np.allclose(np.diff(times), sc.dt, atol=1e-12)
    assert times[-1] == pytest.approx(sc.duration, abs=1e-12)
    assert sc.dt == DEFAULT_DT  # every fixture here runs at the plan's 50 Hz


@pytest.mark.parametrize("name", ALL_NAMES)
@pytest.mark.parametrize("seed", SEEDS)
def test_same_seed_produces_identical_frames(name: str, seed: int) -> None:
    """Same seed, same bytes — compared field by field, not by summary."""
    first = frames(name, seed)
    second = frames(name, seed)
    assert len(first) == len(second)
    for a, b in zip(first, second):
        assert a.t == b.t
        assert np.array_equal(a.q, b.q)
        assert np.array_equal(a.qd, b.qd)
        assert np.array_equal(a.human_pos, b.human_pos)
        assert np.array_equal(a.human_vel, b.human_vel)
        assert a.objects == b.objects
        # The base too, for a fixture that has one. `BasePose` and
        # `BaseVelocity` are frozen dataclasses of floats, so equality is
        # exact — which is what determinism means here — and `None == None`
        # keeps the eleven asserting what they always asserted.
        assert a.base_pose == b.base_pose
        assert a.base_vel == b.base_vel


@pytest.mark.parametrize("name", ALL_NAMES)
def test_a_different_seed_produces_a_different_run(name: str) -> None:
    """Negative test for the seed itself: if it changed nothing, determinism
    would be trivially true and the seed recorded with each run would be
    decoration rather than provenance."""
    a = frames(name, seed=0)
    b = frames(name, seed=1)
    differs = any(
        not np.array_equal(x.q, y.q) or not np.array_equal(x.human_pos, y.human_pos)
        for x, y in zip(a, b)
    )
    assert differs, f"{name}: seed 0 and seed 1 gave identical runs"


@pytest.mark.parametrize("name", ALL_NAMES)
def test_velocity_is_the_slope_of_the_interpolant(name: str) -> None:
    """Within a segment, position must be the integral of the reported velocity.
    A frame whose qd does not match its own trajectory would poison every
    envelope computed from it in Phase 2."""
    got = frames(name, seed=3)
    sc = scenario(name)
    knots = {wp.t for wp in sc.joint_waypoints} | {wp.t for wp in sc.human_waypoints}
    for a, b in zip(got, got[1:]):
        if any(a.t < k < b.t + 1e-12 for k in knots):
            continue  # velocity steps at a knot; the secant spans two segments
        assert np.allclose(b.q - a.q, a.qd * sc.dt, atol=1e-12)
        assert np.allclose(b.human_pos - a.human_pos, a.human_vel * sc.dt, atol=1e-12)


@pytest.mark.parametrize("name", ALL_NAMES)
def test_no_fixture_commands_more_acceleration_than_the_arm_has(name: str) -> None:
    """**THE PLANT THE OUTER BOUND ASSUMES** (issue #96).

    `reg.envelope.outer_envelope` is sound for a saturated double integrator
    obeying `qdd_max`. A fixture that steps its velocity is not that plant, so
    the bound makes it no promise — and three documents claimed "no truthful
    declaration is ever vetoed" on the strength of it.

    Before the rate limit, nine of eleven fixtures violated this, worst 8.3x, at
    one frame each. They never actually escaped the bound, but only because they
    crawl at 6.5-48% of `qd_max`: the guarantee held by luck. An external review
    built a legal `Scenario` where the luck ran out and enforcement vetoed a
    policy telling the literal truth.
    """
    sc = scenario(name)
    got = frames(name, seed=0)
    qd = np.array([f.qd for f in got])
    accel = np.abs(np.diff(qd, axis=0)) / sc.dt
    worst = float((accel / sc.world.limits.qdd_max).max())
    assert worst <= 1.0 + 1e-9, (
        f"{name} commands {worst:.1f}x its own qdd_max. The outer reachable set "
        "is sound only for a plant that respects it, so this fixture is outside "
        "the model every envelope built from it assumes."
    )


@pytest.mark.parametrize("name", EXPECTED_NAMES)
def test_the_outer_bound_contains_the_body_it_promises_to(name: str) -> None:
    """**THE SOUNDNESS TEST THAT WAS MISSING** (issue #96).

    `tests/test_envelope.py` integrates with `compute_envelope`'s own integrator
    on `compute_envelope`'s own grid: it proves the bound covers the model, and
    nothing proved the model covers the fixture. This asks the question the
    other way round — against the frames the simulator actually emits.

    For every frame `i`, the outer set computed from `(q[i], qd[i])` must contain
    the body at every frame the horizon spans. Ship it with #96's rate limit
    reverted and it fails; that is what makes it a test rather than a fixture.
    """
    sc = scenario(name)
    got = frames(name, seed=0)
    horizon = 0.2
    span = int(round(horizon / sc.dt))
    for i in range(0, len(got) - span, max(1, span // 2)):
        state = ProprioState(t=got[i].t, q=got[i].q, qd=got[i].qd, base_vel=None)
        outer = outer_envelope(
            state, sc.world.limits, horizon=horizon, base=ORIGIN_FRAME
        )
        for j in range(i, i + span + 1):
            body = unary_union(link_polygons(got[j].q, sc.world.limits))
            escaped = body.difference(outer).area
            assert escaped == 0.0, (
                f"{name}: body at frame {j} escapes the outer set computed at "
                f"frame {i} by {escaped:.6f} m^2. The bound promises to contain "
                "it and does not."
            )


@pytest.mark.parametrize("name", ALL_NAMES)
def test_frame_arrays_are_read_only(name: str) -> None:
    """A record that can be edited after the fact is not evidence."""
    f = next(scenario(name).states(seed=0))
    for arr in (f.q, f.qd, f.human_pos, f.human_vel):
        with pytest.raises(ValueError):
            arr[0] = 99.0
    with pytest.raises(dataclasses.FrozenInstanceError):
        f.t = 1.0  # type: ignore[misc]


def test_states_requires_a_seed() -> None:
    """No invented default: an artifact whose seed was chosen by a library
    cannot be reproduced by anyone reading the record."""
    with pytest.raises(TypeError):
        scenario("contact").states()  # type: ignore[call-arg]
    with pytest.raises(TypeError, match="seed must be an int"):
        list(scenario("contact").states(seed=0.5))  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# What each name claims. The paired positive/negative case is the point.
# --------------------------------------------------------------------------


@pytest.mark.parametrize("seed", SEEDS)
def test_contact_actually_touches_the_robot(seed: int) -> None:
    got = frames("contact", seed)
    touching = [f.t for f in got if touches_body(f)]
    assert touching, (
        "the contact fixture produced no frame where the human disc intersects a "
        "link polygon. Every incident query in Phase 7 is written against this "
        "run; if nothing happens in it, they all pass vacuously."
    )
    # A single grazing frame would be an accident of the timestep, not a fixture.
    assert len(touching) > 10
    # And it is an interval, not a scatter of unrelated frames.
    assert max(touching) - min(touching) == pytest.approx(
        (len(touching) - 1) * scenario("contact").dt, abs=1e-9
    )


@pytest.mark.parametrize("seed", SEEDS)
def test_a_touched_frame_is_always_an_envelope_frame(seed: int) -> None:
    """The two checks, tied together on the one fixture that does both.

    `compute_envelope` unions in the body at the current pose, so the envelope
    contains it and contact implies overlap. Asserting it here does double duty:
    it would catch an `in_envelope` that has quietly become unable to say yes
    (`static_bystander` covers the other direction), and it would catch a
    fixture where "touched" and "reachable" have drifted apart — which is the
    conflation `near_miss` exists to make visible.
    """
    touched = [f for f in frames("contact", seed) if touches_body(f)]
    assert touched, "no contact frames to check"
    for f in touched:
        assert in_envelope(f), (
            f"contact touched the body at t={f.t} without intersecting the "
            "envelope; the envelope must contain the pose the robot is in."
        )


@pytest.mark.parametrize("seed", SEEDS)
def test_static_bystander_never_touches_and_never_enters(seed: int) -> None:
    """The negative half of the pair: the same checks, asserted to say no.

    This is what establishes that `in_envelope` can fail. Every other envelope
    assertion in this file is positive, and a helper stuck at `True` would
    satisfy all of them.
    """
    for f in frames("static_bystander", seed):
        assert not touches_body(f), f"static_bystander contacted at t={f.t}"
        assert not in_envelope(f), (
            f"static_bystander entered the forward reachable envelope at t={f.t}; "
            "the name claims the human is present throughout and never reachable."
        )
        # Stronger and cheap: the workspace disc contains every envelope, so
        # clearing it clears the arm at any horizon and any sampling.
        assert not in_workspace_disc(f), (
            f"static_bystander entered the workspace disc at t={f.t}."
        )


@pytest.mark.parametrize("seed", SEEDS)
def test_near_miss_overlaps_the_reachable_region_but_never_contacts(seed: int) -> None:
    got = frames("near_miss", seed)
    assert any(in_envelope(f) for f in got), (
        "near_miss never entered the forward reachable envelope. The fixture "
        "exists to separate 'was in the reachable set' from 'was touched'; if "
        "the first never happens there is nothing to separate."
    )
    assert not any(touches_body(f) for f in got), "near_miss made contact"
    gap = min(
        human_polygon(f.human_pos).distance(p)
        for f in got
        for p in link_polygons(f.q, DEMO_WORLD.limits)
    )
    # Near: close enough that conflating "reachable" with "touched" shows up.
    assert 0.0 < gap < 0.15, f"near_miss closest approach was {gap:.3f} m"


@pytest.mark.parametrize("seed", SEEDS)
def test_approach_and_retreat_enters_leaves_and_does_not_touch(seed: int) -> None:
    got = frames("approach_and_retreat", seed)
    inside = [in_envelope(f) for f in got]
    assert not inside[0] and not inside[-1], "the human must start and end clear"
    assert any(inside), "the human never entered the forward reachable envelope"
    # One entry and one exit, not a flicker: the temporal graph should see a
    # single interval, and a fixture that flickers would hide a bug that doesn't.
    transitions = sum(1 for a, b in zip(inside, inside[1:]) if a != b)
    assert transitions == 2, f"expected one entry and one exit, saw {transitions}"
    # An interval wide enough to be an approach rather than a grazing frame that
    # the timestep happened to land on.
    assert sum(inside) > 20, f"only {sum(inside)} frames inside the envelope"
    assert not any(touches_body(f) for f in got)


@pytest.mark.parametrize("seed", SEEDS)
def test_sustained_overlap_overlaps_on_every_frame(seed: int) -> None:
    got = frames("sustained_overlap", seed)
    assert len(got) > 100
    outside = [f.t for f in got if not in_envelope(f)]
    assert not outside, (
        f"sustained_overlap left the forward reachable envelope at t={outside[:5]}"
        f" ({len(outside)} of {len(got)} frames). Every frame must overlap — it "
        "is the fixture the incremental-edge compression claim is tested "
        "against, and a frame outside the envelope emits no edge to compress."
    )
    assert not any(touches_body(f) for f in got), "overlap is not contact"


@pytest.mark.parametrize("seed", SEEDS)
def test_declared_violation_leaves_the_bound_it_declares(seed: int) -> None:
    sc = scenario("declared_violation")
    bounds = sc.declared_q_bounds
    assert bounds is not None, (
        "the fixture must record the bound the policy will declare; without it "
        "the run is indistinguishable from any other and the name is a comment."
    )
    got = frames("declared_violation", seed)
    violating = [
        f.t
        for f in got
        if any(q < lo or q > hi for q, (lo, hi) in zip(f.q, bounds))
    ]
    assert violating, "declared_violation never left its declared bound"
    # ...and the commands stay physically legal, or the fault would be a limit
    # violation rather than a violation of the policy's own statement.
    for f in got:
        assert np.all(f.q >= LIMITS.q_min) and np.all(f.q <= LIMITS.q_max)


#: The fixtures whose policy declares a fixed joint box rather than the region
#: its own configurations sweep. Written out because it is a decision about each
#: fixture, not a property to derive: `declared_violation` uses one so that the
#: claim can be *false*, and the two timing fixtures use one so that their claim
#: stays *true* for the whole run at every seed — a claim that followed the arm
#: around would go stale in the same window the declaration does, and the run
#: would produce a mismatch on top of the fault it exists for.
FIXED_BOX_FIXTURES = {"declared_violation", "stale_declaration", "escalation_failure"}


def test_a_fixture_declares_a_fixed_bound_only_where_it_needs_one() -> None:
    """`None` means not-applicable, and must not be readable as permission."""
    for name, sc in SCENARIOS.items():
        if name in FIXED_BOX_FIXTURES:
            assert sc.declared_q_bounds is not None, name
        else:
            assert sc.declared_q_bounds is None, name


def test_the_policy_fields_are_set_only_on_the_fixture_that_needs_them() -> None:
    """One fixture, one wrong behaviour. A fault fixture with two is untestable.

    Each of these is a way for the policy to be wrong, and the fault fixtures
    are only worth anything if they are one behaviour away from a clean run —
    `tests/test_enforce.py` asserts exactly that by taking the behaviour away
    and getting PERMIT on every frame. If two fixtures shared a behaviour, or
    one fixture had two, that test would stop meaning what it says.
    """
    padded = {n for n, sc in SCENARIOS.items() if sc.declared_margin_m is not None}
    silent = {n for n, sc in SCENARIOS.items() if sc.silent_windows}
    stamped = {n for n, sc in SCENARIOS.items() if sc.declared_action_class is not None}

    assert padded == {"envelope_overclaim"}
    assert silent == {"no_declaration", "stale_declaration", "escalation_failure"}
    assert stamped == {"out_of_vocabulary_action"}
    assert padded.isdisjoint(silent) and padded.isdisjoint(stamped)
    assert silent.isdisjoint(stamped)


def test_the_silent_windows_say_when_the_policy_is_quiet() -> None:
    """`silent_at` is closed on both ends, and the placement is the fault.

    Where the window falls is what separates the three timing fixtures, so it is
    asserted rather than left to the descriptions: covering the run means the
    policy never declares; running to the end means the last declaration
    expires; closing again means it expires *and* the policy then speaks into
    the passivation it caused.
    """
    never = SCENARIOS["no_declaration"]
    assert never.silent_at(0.0) and never.silent_at(never.duration)
    assert all(never.silent_at(t) for t in np.arange(0.0, never.duration, 0.1))

    stale = SCENARIOS["stale_declaration"]
    assert not stale.silent_at(0.0)
    assert stale.silent_at(stale.duration)
    gap_start, gap_end = stale.silent_windows[0]
    assert gap_start > 0.0, "the policy has to declare before it stops"
    assert gap_end == stale.duration, "the policy stops and never resumes"

    escalating = SCENARIOS["escalation_failure"]
    (open_at, close_at) = escalating.silent_windows[0]
    assert close_at < escalating.duration, "the policy has to speak again"
    assert not escalating.silent_at(close_at + escalating.dt)
    # Longer than the horizon a declaration claims, or nothing expires. The
    # horizon itself belongs to the caller (tests/test_enforce.py names it); what
    # this fixture owns is that its silence is long enough to be a gap at all.
    assert close_at - open_at > 0.5


@pytest.mark.parametrize("name", ALL_NAMES)
@pytest.mark.parametrize("seed", SEEDS)
def test_commands_stay_within_the_physical_limits(name: str, seed: int) -> None:
    # The scenario's own limits, not the module's: the mobile fixtures run on a
    # `Limits` whose arm is identical and whose base is not, and a test that
    # reached past the fixture for its bounds would be checking the wrong robot
    # the moment those two arms differ.
    limits = scenario(name).world.limits
    for f in scenario(name).states(seed):
        assert np.all(f.q >= limits.q_min), f"{name}: q below q_min at t={f.t}"
        assert np.all(f.q <= limits.q_max), f"{name}: q above q_max at t={f.t}"


@pytest.mark.parametrize("name", ALL_NAMES)
def test_the_human_stays_in_the_room_and_clear_of_the_obstacles(name: str) -> None:
    """Obstacles are static scenery here; a human walking through one would make
    every separation answer about that entity meaningless."""
    world = scenario(name).world
    for f in scenario(name).states(seed=11):
        x, y = float(f.human_pos[0]), float(f.human_pos[1])
        assert world.room.contains_circle(x, y, world.human_radius)
        for obs in f.objects:
            gap = float(np.hypot(x - obs.cx, y - obs.cy)) - obs.radius - world.human_radius
            assert gap > 0.0, f"{name}: human overlaps {obs.entity_id} at t={f.t}"


@pytest.mark.parametrize("name", ALL_NAMES)
def test_every_frame_carries_the_worlds_obstacles(name: str) -> None:
    """The plan logs static objects per frame on purpose: the raw stream must be
    inflated honestly, or Claim 1 compares against a baseline nobody would log."""
    for f in scenario(name).states(seed=0):
        assert f.objects == scenario(name).world.obstacles
        assert isinstance(f.objects, tuple)


# --------------------------------------------------------------------------
# The world
# --------------------------------------------------------------------------


def test_obstacles_are_clear_of_the_workspace_disc() -> None:
    """world.py promises this rather than enforcing it; here is the enforcement.
    An obstacle inside reach would make "did the robot contact something"
    ambiguous in every fixture at once."""
    for obs in DEMO_WORLD.obstacles:
        clearance = float(np.hypot(obs.cx, obs.cy)) - obs.radius - DEMO_WORLD.max_reach
        assert clearance > 0.0, f"{obs.entity_id} sits inside the workspace disc"


def test_room_rejects_degenerate_bounds() -> None:
    with pytest.raises(ValueError, match="x_max"):
        Room(x_min=1.0, y_min=0.0, x_max=1.0, y_max=1.0)
    with pytest.raises(ValueError, match="y_max"):
        Room(x_min=0.0, y_min=1.0, x_max=1.0, y_max=0.5)


def test_room_contains_circle_is_inclusive_of_the_wall() -> None:
    assert ROOM.contains_circle(0.0, 0.0, 0.5)
    assert ROOM.contains_circle(ROOM.x_max - 0.25, 0.0, 0.25)
    assert not ROOM.contains_circle(ROOM.x_max - 0.1, 0.0, 0.25)


def test_a_world_the_robot_is_not_in_is_not_the_worlds_to_refuse() -> None:
    """**The check moved, and this pins where it did not stay** (issue #184).

    `World.__post_init__` used to refuse this. It cannot: the question is
    whether the robot stays in the room *over the run*, a driven base has a
    path, and a `World` never sees a trajectory. Constructing one is now legal
    and says nothing either way — what refuses it is `Scenario`, over every
    pose the run records, and the two tests below are that refusal.

    Written as an assertion rather than deleted so that a future
    `World.__post_init__` growing the check back has something to fail.
    """
    stranded = World(
        room=Room(x_min=5.0, y_min=5.0, x_max=6.0, y_max=6.0),
        obstacles=(),
        limits=LIMITS,
        human_radius=0.25,
    )
    assert stranded.room_excursion(0.0, 0.0, slack=0.0) is not None


def test_the_world_module_no_longer_states_where_the_base_is() -> None:
    """**`BASE_XY` is gone, and this is what keeps it gone** (issue #184).

    It was a module constant restating a mounting fact that
    `reg.kinematics.ORIGIN_FRAME` already stated, read in two places and
    parameterising nothing — and a fact written down twice is a fact two places
    can disagree about. `grep ORIGIN_FRAME` is meant to be the whole list of
    places this repository assumes a base that does not move
    ([`docs/mobile-base.md`](../docs/mobile-base.md) §4), which it stops being
    the moment a second statement exists.

    Asserted rather than left implicit because nothing else fails when the
    constant comes back: it would simply be a second answer, agreeing with the
    first until someone changes one of them.
    """
    assert not hasattr(reg.world, "BASE_XY"), (
        "reg.world.BASE_XY is back. Where a bolted base is is "
        "reg.kinematics.ORIGIN_FRAME's to say, and saying it twice is how the "
        "two drift apart."
    )


def test_room_excursion_names_which_part_of_the_robot_left_and_by_how_much() -> None:
    """The geometry the two refusals are made of, and its message.

    A refusal that says only "outside the room" makes a fixture author bisect by
    hand, so the excursion carries the wall, the overshoot and — the distinction
    that decides which fixture bug it is — whether the *base* crossed the wall
    or only the disc its body can occupy.
    """
    inside = DEMO_WORLD.room_excursion(0.0, 0.0, slack=0.0)
    assert inside is None

    # Base inside the room, arm sweeping out of it: x_max is 3.0 and the body
    # can occupy 0.95 m about the base, so 2.5 is 0.45 m too close to the wall.
    sweeps_out = DEMO_WORLD.room_excursion(2.5, 0.0, slack=0.0)
    assert sweeps_out is not None
    assert sweeps_out.wall == "x_max"
    assert sweeps_out.wall_value == ROOM.x_max
    assert sweeps_out.base_outside is False
    assert sweeps_out.overshoot_m == pytest.approx(0.45)
    assert "arm sweeps out of the room" in sweeps_out.describe()

    # The base itself past the same wall. Both parts are outside, and the
    # message has to say the stronger of the two things.
    base_out = DEMO_WORLD.room_excursion(3.2, 0.0, slack=0.0)
    assert base_out is not None
    assert base_out.base_outside is True
    assert base_out.base_overshoot_m == pytest.approx(0.2)
    assert "the base itself is outside the room" in base_out.describe()

    # `slack` is what a caller checking a *scripted* knot leaves for the jitter,
    # and it is the difference between fitting and not.
    assert DEMO_WORLD.room_excursion(2.05, 0.0, slack=0.0) is None
    assert DEMO_WORLD.room_excursion(2.05, 0.0, slack=0.02) is not None


def test_room_excursion_refuses_a_slack_that_shrinks_the_robot() -> None:
    """**NEGATIVE.** A negative slack is a smaller robot, which passes a fixture
    that does not fit — the one direction this may not be wrong in."""
    with pytest.raises(ValueError, match="negative slack"):
        DEMO_WORLD.room_excursion(0.0, 0.0, slack=-0.1)
    with pytest.raises(ValueError, match="not finite"):
        DEMO_WORLD.room_excursion(float("nan"), 0.0, slack=0.0)


def test_world_rejects_an_obstacle_outside_the_room() -> None:
    with pytest.raises(ValueError, match="not wholly inside the room"):
        World(
            room=ROOM,
            obstacles=(Obstacle("obs_gone", "crate", 9.0, 9.0, 0.2),),
            limits=LIMITS,
            human_radius=0.25,
        )


def test_world_rejects_duplicate_entity_ids() -> None:
    """Two entities sharing an id merge two histories into an answer about
    neither — and the graph is keyed on entity_id."""
    twin = Obstacle("obs_same", "crate", 1.6, 1.2, 0.25)
    with pytest.raises(ValueError, match="duplicate entity_id"):
        World(room=ROOM, obstacles=(twin, twin), limits=LIMITS, human_radius=0.25)


def test_world_rejects_a_human_of_no_extent() -> None:
    with pytest.raises(ValueError, match="human_radius"):
        World(room=ROOM, obstacles=(), limits=LIMITS, human_radius=0.0)


def test_world_rejects_a_mutable_obstacle_list() -> None:
    with pytest.raises(TypeError, match="must be a tuple"):
        World(
            room=ROOM,
            obstacles=[Obstacle("obs_crate", "crate", 1.6, 1.2, 0.25)],  # type: ignore[arg-type]
            limits=LIMITS,
            human_radius=0.25,
        )


def test_max_reach_covers_the_whole_body() -> None:
    assert DEMO_WORLD.max_reach == pytest.approx(
        float(np.sum(LIMITS.link_lengths)) + LIMITS.link_radius
    )


# --------------------------------------------------------------------------
# Construction-time negative tests: a malformed fixture must fail loudly at
# definition, not produce a plausible trajectory nobody wrote.
# --------------------------------------------------------------------------


def _scenario(**overrides) -> Scenario:
    kwargs = dict(
        name="probe",
        description="constructed by a test",
        world=DEMO_WORLD,
        duration=2.0,
        joint_waypoints=(Waypoint(0.0, (0.0, 0.0)), Waypoint(2.0, (0.5, 0.5))),
        human_waypoints=(Waypoint(0.0, (2.0, 0.0)), Waypoint(2.0, (2.0, 0.5))),
        q_jitter=0.0,
        human_jitter=0.0,
    )
    kwargs.update(overrides)
    return Scenario(**kwargs)  # type: ignore[arg-type]


def test_the_probe_scenario_is_otherwise_valid() -> None:
    """Guards the negative tests below: if the baseline were already invalid,
    each of them would pass for the wrong reason."""
    assert len(list(_scenario().states(seed=0))) == 101


def test_rejects_waypoint_times_that_do_not_advance() -> None:
    with pytest.raises(ValueError, match="strictly increasing"):
        _scenario(
            joint_waypoints=(
                Waypoint(0.0, (0.0, 0.0)),
                Waypoint(1.0, (0.2, 0.0)),
                Waypoint(1.0, (0.4, 0.0)),
                Waypoint(2.0, (0.5, 0.5)),
            )
        )


def test_rejects_a_waypoint_set_that_does_not_span_the_duration() -> None:
    with pytest.raises(ValueError, match="duration"):
        _scenario(
            human_waypoints=(Waypoint(0.0, (2.0, 0.0)), Waypoint(1.5, (2.0, 0.5)))
        )
    with pytest.raises(ValueError, match="not 0.0"):
        _scenario(
            human_waypoints=(Waypoint(0.5, (2.0, 0.0)), Waypoint(2.0, (2.0, 0.5)))
        )


def test_rejects_a_waypoint_of_the_wrong_width() -> None:
    """numpy would broadcast a one-joint waypoint across two joints."""
    with pytest.raises(ValueError, match="expected 2"):
        _scenario(
            joint_waypoints=(Waypoint(0.0, (0.0,)), Waypoint(2.0, (0.5,)))
        )


def test_rejects_a_duration_that_is_not_a_whole_number_of_steps() -> None:
    with pytest.raises(ValueError, match="whole number"):
        _scenario(
            duration=2.005,
            joint_waypoints=(Waypoint(0.0, (0.0, 0.0)), Waypoint(2.005, (0.5, 0.5))),
            human_waypoints=(Waypoint(0.0, (2.0, 0.0)), Waypoint(2.005, (2.0, 0.5))),
        )


def test_rejects_a_command_outside_the_physical_limits() -> None:
    with pytest.raises(ValueError, match=r"\[q_min, q_max\]"):
        _scenario(
            joint_waypoints=(Waypoint(0.0, (0.0, 0.0)), Waypoint(2.0, (0.5, 3.0)))
        )


def test_rejects_a_command_that_only_jitter_pushes_out_of_limits() -> None:
    """The bound has to hold for every seed, not for the nominal waypoints."""
    edge = float(LIMITS.q_max[1])
    _scenario(
        joint_waypoints=(Waypoint(0.0, (0.0, 0.0)), Waypoint(2.0, (0.5, edge))),
        q_jitter=0.0,
    )
    with pytest.raises(ValueError, match="q_jitter"):
        _scenario(
            joint_waypoints=(Waypoint(0.0, (0.0, 0.0)), Waypoint(2.0, (0.5, edge))),
            q_jitter=0.01,
        )


def test_rejects_a_human_who_walks_through_the_wall() -> None:
    with pytest.raises(ValueError, match="outside the room"):
        _scenario(
            human_waypoints=(Waypoint(0.0, (2.0, 0.0)), Waypoint(2.0, (2.95, 0.0)))
        )


def test_rejects_negative_jitter() -> None:
    with pytest.raises(ValueError, match="human_jitter must be >= 0"):
        _scenario(human_jitter=-0.01)


def test_rejects_an_empty_declared_bound() -> None:
    with pytest.raises(ValueError, match="is empty"):
        _scenario(declared_q_bounds=((0.5, 0.5), (-1.0, 1.0)))
    with pytest.raises(ValueError, match="declared_q_bounds has"):
        _scenario(declared_q_bounds=((-1.0, 1.0),))


def test_rejects_a_margin_that_pads_nothing() -> None:
    """Zero is not `None`: the two are different statements about the claim."""
    with pytest.raises(ValueError, match="declared_margin_m"):
        _scenario(declared_margin_m=0.0)
    with pytest.raises(ValueError, match="declared_margin_m"):
        _scenario(declared_margin_m=-0.1)
    with pytest.raises(ValueError, match="declared_margin_m"):
        _scenario(declared_margin_m=float("nan"))
    assert _scenario(declared_margin_m=0.25).declared_margin_m == 0.25


@pytest.mark.parametrize(
    ("windows", "match"),
    [
        (((1.0, 0.5),), "non-empty interval"),
        (((1.0, 1.0),), "non-empty interval"),
        (((-0.5, 1.0),), "non-empty interval"),
        (((0.5, 2.5),), "non-empty interval"),  # the probe scenario runs 2.0 s
        (((0.2, 1.0), (0.8, 1.5)), "before the end of the previous"),
        (((1.0, 1.5), (0.2, 0.5)), "before the end of the previous"),
        ((("a", 1.0),), "not a"),
        (((0.5,),), "not a"),
    ],
)
def test_rejects_a_silence_that_says_nothing_about_the_run(
    windows: tuple, match: str
) -> None:
    """NEGATIVE. A window outside the run silences nothing, and a fixture that
    declared one would produce no fault while claiming one."""
    with pytest.raises((ValueError, TypeError), match=match):
        _scenario(silent_windows=windows)


def test_rejects_a_mutable_silence() -> None:
    with pytest.raises(TypeError, match="must be a tuple"):
        _scenario(silent_windows=[(0.5, 1.0)])  # type: ignore[arg-type]


def test_the_probe_scenario_accepts_a_well_formed_silence() -> None:
    """The positive control for the four negatives above."""
    sc = _scenario(silent_windows=((0.2, 0.5), (1.0, 2.0)))
    assert sc.silent_at(0.2) and sc.silent_at(0.5) and sc.silent_at(2.0)
    assert not sc.silent_at(0.0) and not sc.silent_at(0.75)


@pytest.mark.parametrize("field", ["declared_action_class", "fault"])
@pytest.mark.parametrize("value", ["", "has space", "has\nnewline", 17])
def test_rejects_a_vocabulary_word_that_is_not_one(field: str, value: object) -> None:
    """NEGATIVE. Both fields end up in a record or a query filter, not in prose.

    `declared_action_class` is deliberately *not* checked against
    `ACTION_CLASSES` — the fixture that needs it needs a word outside the
    vocabulary — so the shape is all this can check, and it checks it.
    """
    with pytest.raises(ValueError, match=field):
        _scenario(**{field: value})


def test_an_out_of_vocabulary_action_class_is_allowed_and_is_the_point() -> None:
    """The positive control: the refusals above are about shape, not vocabulary."""
    assert _scenario(declared_action_class="lunge").declared_action_class == "lunge"


def test_scenarios_are_frozen() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        scenario("contact").duration = 1.0  # type: ignore[misc]


# --------------------------------------------------------------------------
# THE BASE (issue #177, docs/mobile-base.md §7 Tier 4)
#
# A scenario can express a driven base, and no scenario in `SCENARIOS` does. So
# the fixture this section is written against is built here, on a `Limits` whose
# four base bounds are positive — `reg.world.LIMITS` states four zeros, which is
# the bolted arm every registered fixture runs on, and driving one is refused.
#
# The two halves are asserted together on purpose. What is easy to get right is
# that a driving scenario produces poses; what is easy to get wrong is that a
# fixed-base one keeps producing exactly what it produced before, and the second
# is the half every published figure in this repository depends on.
# --------------------------------------------------------------------------

# `MOBILE_LIMITS` and `MOBILE_WORLD` are imported from `reg.scenarios` rather
# than built here (issue #178). They were built here while nothing in the
# package drove; the three mobile fixtures now run on exactly this robot, and a
# second copy of its four base numbers in the test file would let the probe
# scenario below and the shipped fixtures drift into two different vehicles
# without anything going red.


def _driving(**overrides) -> Scenario:
    """The probe scenario with a base that drives. Overridable like `_scenario`."""
    kwargs = dict(
        name="probe_drives",
        description="constructed by a test",
        world=MOBILE_WORLD,
        duration=2.0,
        joint_waypoints=(Waypoint(0.0, (0.0, 0.0)), Waypoint(2.0, (0.5, 0.5))),
        human_waypoints=(Waypoint(0.0, (2.0, 0.0)), Waypoint(2.0, (2.0, 0.5))),
        q_jitter=0.0,
        human_jitter=0.0,
        base_waypoints=(
            Waypoint(0.0, (0.0, 0.0, 0.0)),
            Waypoint(1.0, (0.4, 0.2, 0.3)),
            Waypoint(2.0, (0.8, 0.0, 0.0)),
        ),
        base_pose_source=PoseSource.DEAD_RECKONED,
        base_vel_source=VelocitySource.PROPRIOCEPTIVE,
        base_jitter=(0.01, 0.005),
    )
    kwargs.update(overrides)
    return Scenario(**kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize("name", EXPECTED_NAMES)
def test_every_registered_fixture_is_fixed_base_and_records_no_base(name: str) -> None:
    """**The half that must not move.** Claim 1 is priced on eleven bolted arms.

    Two statements, and the second is the one a reader should not have to take
    on trust: none of the eleven drives, and *therefore* every frame records
    `base_pose=None` and `base_vel=None` — which is what keeps their streams at
    `expected_header(2, 3)`'s 24 columns and every published figure where it
    was. `None` here is "this run recorded no base", not "the base was at the
    origin": for a bolted base that is a mounting fact and `PoseSource` has no
    member for one (issue #150).
    """
    scn = scenario(name)
    assert scn.drives is False
    assert scn.base_waypoints is None
    assert (scn.base_pose_source, scn.base_vel_source, scn.base_jitter) == (
        None,
        None,
        None,
    )
    frames = list(scn.states(seed=0))
    assert all(f.base_pose is None and f.base_vel is None for f in frames)


def test_a_driving_scenario_carries_a_pose_and_a_rate_on_every_frame() -> None:
    """The positive this issue exists for, and both provenances survive it."""
    scn = _driving()
    assert scn.drives is True
    frames = list(scn.states(seed=0))
    assert len(frames) == scn.n_frames
    assert all(f.base_pose is not None and f.base_vel is not None for f in frames)
    assert {f.base_pose.source for f in frames} == {PoseSource.DEAD_RECKONED}
    assert {f.base_vel.source for f in frames} == {VelocitySource.PROPRIOCEPTIVE}
    # It actually goes somewhere: a "driving" fixture whose base never leaves
    # its first knot would satisfy every assertion above.
    assert abs(frames[-1].base_pose.x - frames[0].base_pose.x) > 0.5


def test_the_base_velocity_is_the_one_that_carries_the_base_to_the_next_frame() -> None:
    """`base_vel[k]` is the rate that reaches frame k+1, in the base's own frame.

    The exact counterpart of `test_velocity_is_the_slope_of_the_interpolant` for
    the arm, and it is load-bearing for the same reason: since issue #163
    `reg.envelope.base_motion_bounds` reads this rate to bound where the base
    can get to, so a frame reporting the velocity it *arrived* with would poison
    every outer envelope built from it — and since issue #164 that outer set is
    the only term a mobile robot is VETOed against.

    The rotation is the other half of the statement. `BaseVelocity` is
    body-frame; rotating it by the pose's own heading has to land exactly on the
    next pose, or the two halves of the frame describe different runs.
    """
    frames = list(_driving().states(seed=0))
    dt = _driving().dt
    for a, b in zip(frames, frames[1:]):
        theta = a.base_pose.theta
        vx = np.cos(theta) * a.base_vel.vx - np.sin(theta) * a.base_vel.vy
        vy = np.sin(theta) * a.base_vel.vx + np.cos(theta) * a.base_vel.vy
        assert b.base_pose.x == pytest.approx(a.base_pose.x + vx * dt, abs=1e-12)
        assert b.base_pose.y == pytest.approx(a.base_pose.y + vy * dt, abs=1e-12)
        assert b.base_pose.theta == pytest.approx(
            a.base_pose.theta + a.base_vel.omega * dt, abs=1e-12
        )


@pytest.mark.parametrize("seed", SEEDS)
def test_the_executed_base_trajectory_obeys_the_bases_own_bounds(seed: int) -> None:
    """The base is rate-limited, as the arm has been since issue #96.

    A base that teleported along its script would be a base the outer envelope
    makes no promise about, and `reg.enforce` has no second bound to fall back
    on for a robot that drives (`computed_bound` refuses; docs/mobile-base.md
    §1). So what the frames record is the trajectory the base *executed*, and
    all four bounds hold on it — including the two accelerations, which are what
    a script with a corner in it would otherwise violate at the corner.
    """
    scn = _driving()
    limits = scn.world.limits
    frames = list(scn.states(seed))
    speeds = [float(np.hypot(f.base_vel.vx, f.base_vel.vy)) for f in frames]
    assert max(speeds) <= limits.base_v_max + 1e-12
    assert max(abs(f.base_vel.omega) for f in frames) <= limits.base_omega_max + 1e-12

    for a, b in zip(frames, frames[1:]):
        # Body frame and room frame agree on the *magnitude* of the step, which
        # is what the bound bounds, so this compares the two body-frame vectors
        # after rotating both into the room.
        va = _room_frame(a)
        vb = _room_frame(b)
        assert float(np.hypot(*(vb - va))) <= limits.base_a_max * scn.dt + 1e-12
        assert abs(b.base_vel.omega - a.base_vel.omega) <= (
            limits.base_alpha_max * scn.dt + 1e-12
        )


def _room_frame(frame) -> np.ndarray:
    """A frame's body-frame base velocity, rotated into the room."""
    theta = frame.base_pose.theta
    return np.array(
        [
            np.cos(theta) * frame.base_vel.vx - np.sin(theta) * frame.base_vel.vy,
            np.sin(theta) * frame.base_vel.vx + np.cos(theta) * frame.base_vel.vy,
        ]
    )


def test_the_seed_perturbs_the_base_path_and_reproduces_it() -> None:
    """`base_jitter` is a real input, and the run is still a function of the seed.

    Both halves matter: a jitter that changed nothing would be a fixture
    parameter that is decoration, and a base path that differed between two runs
    of one seed would make the artifact irreproducible in the one dimension this
    issue added.
    """
    first = [f.base_pose.x for f in _driving().states(seed=0)]
    again = [f.base_pose.x for f in _driving().states(seed=0)]
    other = [f.base_pose.x for f in _driving().states(seed=7)]
    assert first == again
    assert first != other
    unperturbed = [f.base_pose.x for f in _driving(base_jitter=(0.0, 0.0)).states(0)]
    assert unperturbed != first
    # And a base path nobody perturbs is still a function of the seed only
    # through the arm and the human, so two seeds agree on it.
    assert unperturbed == [
        f.base_pose.x for f in _driving(base_jitter=(0.0, 0.0)).states(7)
    ]


def test_the_base_knots_draw_from_their_own_stream() -> None:
    """Adding a base waypoint must not shift the arm or the human.

    `_knots` gives every scripted path its own generator for this reason: two
    runs of "the same" scenario that differ in the human's walk because someone
    added a base knot are incomparable for a reason invisible in the diff.
    """
    short = [
        (f.q.tolist(), f.human_pos.tolist()) for f in _driving().states(seed=0)
    ]
    longer = _driving(
        base_waypoints=(
            Waypoint(0.0, (0.0, 0.0, 0.0)),
            Waypoint(0.5, (0.2, 0.1, 0.15)),
            Waypoint(1.0, (0.4, 0.2, 0.3)),
            Waypoint(2.0, (0.8, 0.0, 0.0)),
        )
    )
    assert [
        (f.q.tolist(), f.human_pos.tolist()) for f in longer.states(seed=0)
    ] == short


# --- the negatives ----------------------------------------------------------


@pytest.mark.parametrize(
    ("field", "match"),
    [
        ("base_pose_source", "no base_pose_source"),
        ("base_vel_source", "no base_vel_source"),
        ("base_jitter", "no base_jitter"),
    ],
)
def test_a_base_trajectory_missing_its_companion_is_refused(
    field: str, match: str
) -> None:
    """**NEGATIVE, and the one this issue is named for.**

    A simulator's base pose is ground truth, exactly as `human_pos` is. Writing
    it with no provenance would put an unlabelled room-frame pose into the
    stream and leave every reader to assume one, and there is no value to guess:
    only whoever produced a pose knows whether it was dead-reckoned or
    localized. `Limits.source`'s argument (issue #84), one type over — so the
    refusal names what is missing rather than filling it in.
    """
    with pytest.raises(ValueError, match=match):
        _driving(**{field: None})


@pytest.mark.parametrize(
    "field", ["base_pose_source", "base_vel_source", "base_jitter"]
)
def test_a_companion_with_no_base_trajectory_is_refused(field: str) -> None:
    """**NEGATIVE.** The contradiction in the other direction.

    A `PoseSource` on a fixture whose base never moves is the provenance of a
    pose nothing writes. Two things could have been meant — a trajectory that
    was not written, or a field that should not be there — and both repairs
    change what the run is, so neither is guessed at.
    """
    value = {
        "base_pose_source": PoseSource.LOCALIZED,
        "base_vel_source": VelocitySource.DERIVED,
        "base_jitter": (0.01, 0.005),
    }[field]
    with pytest.raises(ValueError, match=f"states {field}="):
        _scenario(**{field: value})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("base_pose_source", "dead_reckoned"),
        ("base_vel_source", "proprioceptive"),
    ],
)
def test_a_provenance_that_is_a_string_is_refused(field: str, value: str) -> None:
    """**NEGATIVE.** The string is the value the enum member *writes*, which is
    what makes it the plausible mistake: it would reach `reg.stream` looking
    like a provenance somebody stated and be the one thing nobody checked."""
    with pytest.raises(TypeError, match=field):
        _driving(**{field: value})


def test_a_trajectory_on_a_bolted_base_is_refused() -> None:
    """**NEGATIVE.** `reg.world.LIMITS` states four zeros, and `states` integrates
    the base under them — so a fixture scripted on it would record a base parked
    at its first knot while its name and waypoints say it drove. The refusal
    names the fields, because which of the four is zero is what the author fixes.
    """
    with pytest.raises(ValueError, match="base_v_max=0.0"):
        _driving(world=DEMO_WORLD)


@pytest.mark.parametrize(
    "field", ["base_v_max", "base_a_max", "base_omega_max", "base_alpha_max"]
)
def test_each_base_bound_is_checked_and_not_just_the_speed(field: str) -> None:
    """**NEGATIVE, one bound at a time.** A zero speed bound pins the base
    outright; a zero acceleration bound pins it at rest, which is the same
    outcome one derivative up. A check that only looked at the two speeds would
    pass a fixture whose base can never start moving."""
    with pytest.raises(ValueError, match=f"{field}=0.0"):
        _driving(
            world=dataclasses.replace(
                MOBILE_WORLD,
                limits=dataclasses.replace(MOBILE_LIMITS, **{field: 0.0}),
            )
        )


def test_a_base_waypoint_of_the_wrong_width_is_refused() -> None:
    """**NEGATIVE.** `(x, y)` is the human's shape, not the base's: a base
    waypoint is a *pose*, and numpy would broadcast the short one into a
    trajectory nobody wrote."""
    with pytest.raises(ValueError, match="expected 3"):
        _driving(
            base_waypoints=(Waypoint(0.0, (0.0, 0.0)), Waypoint(2.0, (0.8, 0.0)))
        )


def test_a_base_path_that_does_not_span_the_run_is_refused() -> None:
    """**NEGATIVE.** The base path is held to every rule the joint path is: it
    starts at 0.0, ends at `duration`, and its knots advance."""
    with pytest.raises(ValueError, match="duration"):
        _driving(
            base_waypoints=(
                Waypoint(0.0, (0.0, 0.0, 0.0)),
                Waypoint(1.5, (0.8, 0.0, 0.0)),
            )
        )


@pytest.mark.parametrize(
    ("value", "match"),
    [
        (0.01, "must be a \\(metres, radians\\) pair"),
        ((0.01,), "must be a \\(metres, radians\\) pair"),
        ((0.01, 0.01, 0.01), "must be a \\(metres, radians\\) pair"),
        ((-0.01, 0.0), "must be finite and >= 0"),
        ((0.0, float("nan")), "must be finite and >= 0"),
    ],
)
def test_a_base_jitter_that_is_not_two_bounds_is_refused(
    value: object, match: str
) -> None:
    """**NEGATIVE.** One number would bound metres and radians together, which is
    the mistake `reg.types.BaseVelocity` keeps its fields apart to prevent — and
    nothing downstream could catch it, because both are floats."""
    with pytest.raises(ValueError, match=match):
        _driving(base_jitter=value)


# --------------------------------------------------------------------------
# THE ROOM HOLDS THE WHOLE ROBOT, FOR THE WHOLE RUN (issue #184)
#
# `World.__post_init__` used to assert that the room contained `BASE_XY` as a
# point of zero radius. That check could not answer its own question once a base
# can drive — a `World` never sees a trajectory — and it was checking the wrong
# subject even for a bolted arm, because an arm sweeping through a wall passes a
# point test. It is `Scenario`'s now, in two halves, and both halves are here:
# the scripted knots at construction, and the *executed* pose per frame.
#
# The second half is the one that cannot be folded into the first. The room is
# convex and `contains_circle` is a convex condition, so a straight line between
# two knots that both fit cannot leave the room — checking the interpolated
# script would be the waypoint check written at greater length. What leaves the
# room between two waypoints is the trajectory the base *executes*, which lags
# its reference and overshoots every corner under `base_a_max`.
# --------------------------------------------------------------------------


@pytest.mark.parametrize("name", EXPECTED_NAMES)
def test_every_registered_fixture_holds_its_whole_robot(name: str) -> None:
    """**The half that must not move.** The eleven still construct, unchanged.

    They are built at import, so a refusal would already have been a collection
    error — this asserts the geometry the widened check now rests on rather than
    the fact that the import worked: the demo room holds the whole workspace
    disc about the bolted base, not merely the mounting point.
    """
    scn = scenario(name)
    assert scn.drives is False
    assert scn.world.room_excursion(ORIGIN_FRAME.x, ORIGIN_FRAME.y, slack=0.0) is None


def test_a_fixed_base_scenario_whose_room_excludes_the_base_is_refused() -> None:
    """**NEGATIVE.** The refusal `World` used to make, where it lives now.

    A fixed-base scenario has one pose for the whole run and it is
    `ORIGIN_FRAME`, so the whole question is answerable at construction — and a
    room that does not contain it describes a robot mounted outside its own
    room, which is a fixture bug and not a runtime condition.
    """
    stranded = World(
        room=Room(x_min=1.0, y_min=-1.5, x_max=6.0, y_max=2.0),
        obstacles=(),
        limits=LIMITS,
        human_radius=0.25,
    )
    with pytest.raises(ValueError, match="the base itself is outside the room"):
        _scenario(world=stranded)


def test_a_fixed_base_scenario_whose_arm_sweeps_out_of_the_room_is_refused() -> None:
    """**NEGATIVE, and the widening this issue is half named for.**

    The base is inside this room and the old point-of-zero-radius check passed
    it. The arm does not fit: `x_max` is 0.5 m from the base and the body can
    occupy 0.95 m about it, so the links sweep through the wall.
    """
    narrow = World(
        room=Room(x_min=-2.0, y_min=-1.5, x_max=0.5, y_max=2.0),
        obstacles=(),
        limits=LIMITS,
        human_radius=0.25,
    )
    with pytest.raises(ValueError, match="arm sweeps out of the room"):
        _scenario(
            world=narrow,
            human_waypoints=(Waypoint(0.0, (0.0, 0.0)), Waypoint(2.0, (0.0, 0.5))),
        )


def test_a_base_waypoint_whose_arm_sweeps_out_of_the_room_is_refused() -> None:
    """**NEGATIVE.** The same widening, for a knot on a driven path.

    2.5 m is 0.5 m from `x_max`, so the base is well inside the room and the arm
    is not. The refusal names the knot's time, because which one to move is what
    the author has to know.
    """
    with pytest.raises(ValueError, match=r"base waypoint at t=1.0 leaves the room"):
        _driving(
            base_waypoints=(
                Waypoint(0.0, (0.0, 0.0, 0.0)),
                Waypoint(1.0, (2.5, 0.0, 0.0)),
                Waypoint(2.0, (0.0, 0.0, 0.0)),
            )
        )


def test_a_base_waypoint_only_the_jitter_pushes_out_is_refused() -> None:
    """**NEGATIVE.** The bound has to hold for every seed, not for the nominal
    knots — the argument `test_rejects_a_command_that_only_jitter_pushes_out_of_limits`
    makes for the arm, one path over. 2.05 m puts the workspace disc exactly on
    `x_max`; any jitter in metres takes it through."""
    grazing = (
        Waypoint(0.0, (0.0, 0.0, 0.0)),
        Waypoint(1.0, (1.0, 0.0, 0.0)),
        Waypoint(2.0, (2.05, 0.0, 0.0)),
    )
    _driving(base_waypoints=grazing, base_jitter=(0.0, 0.05))
    with pytest.raises(ValueError, match="base_jitter"):
        _driving(base_waypoints=grazing, base_jitter=(0.02, 0.05))


#: A base sluggish enough to overshoot visibly: `MOBILE_LIMITS` with
#: `base_a_max` cut to 0.25 m/s^2. Stated as a fixture parameter, like every
#: other number in this file.
#:
#: The overshoot is *lag paid back*, not braking distance, and the difference
#: matters because a reader who expects the latter will not believe the numbers.
#: `states` steers the base at the reference one frame ahead, so while 0.25
#: m/s^2 keeps it behind a 0.4 m/s script the error accumulates; by the time the
#: loop has closed it, the base is carrying 0.755 m/s into a corner where the
#: script reverses. Measured: it crosses its own reference at about t=3.4 s and
#: coasts to x=2.528 at t=6.34 s, half a metre past a knot at x=2.0, before
#: coming back.
SLOW_TO_STOP_LIMITS = dataclasses.replace(MOBILE_LIMITS, base_a_max=0.25)
SLOW_TO_STOP_WORLD = dataclasses.replace(MOBILE_WORLD, limits=SLOW_TO_STOP_LIMITS)

#: There and back, turning round at x=2.0 — a knot 0.05 m inside what the room
#: holds, so every knot fits and what the base does between them is what does
#: not.
OVERSHOOTING_BASE_PATH = (
    Waypoint(0.0, (0.0, 0.0, 0.0)),
    Waypoint(5.0, (2.0, 0.0, 0.0)),
    Waypoint(10.0, (0.0, 0.0, 0.0)),
)

#: The same robot in a room far too large to refuse it, so that the executed
#: path can be *watched* rather than only refused: `states` raises at the first
#: offending frame, which is exactly the frame after which there is nothing left
#: to observe.
PERMISSIVE_WORLD = dataclasses.replace(
    SLOW_TO_STOP_WORLD, room=Room(x_min=-50.0, y_min=-50.0, x_max=50.0, y_max=50.0)
)


def _overshooting(**overrides) -> Scenario:
    kwargs = dict(
        duration=10.0,
        world=SLOW_TO_STOP_WORLD,
        joint_waypoints=(Waypoint(0.0, (0.0, 0.0)), Waypoint(10.0, (0.5, 0.5))),
        human_waypoints=(Waypoint(0.0, (2.0, 0.0)), Waypoint(10.0, (2.0, 0.5))),
        base_waypoints=OVERSHOOTING_BASE_PATH,
        base_jitter=(0.0, 0.0),
    )
    kwargs.update(overrides)
    return _driving(**kwargs)


def test_every_knot_of_the_overshooting_path_is_inside_the_room() -> None:
    """Guards the two tests below: if a knot were already out, each would pass
    for the wrong reason — as a waypoint check, which is the thing that is not
    enough."""
    scn = _overshooting()
    for wp in scn.base_waypoints:
        x, y, _ = wp.value
        assert scn.world.room_excursion(x, y, slack=0.0) is None


def test_the_overshooting_path_leaves_the_room_and_comes_back() -> None:
    """**The situation the refusal below is a refusal of**, shown rather than
    asserted about a message.

    Run in a room that holds the whole manoeuvre, then measured against the demo
    room's geometry: the executed path is inside, then outside, then inside
    again — an excursion that begins and ends between the same two waypoints and
    is invisible to every check on the knots. That is the criterion in issue
    #184 stated as a trajectory. `states` raises at the first offending frame,
    so the refusal test cannot show the *return*; this one can, and without it
    "leaves the room and returns" would be a claim no test makes.
    """
    scn = _overshooting(world=PERMISSIVE_WORLD)
    outside = [
        SLOW_TO_STOP_WORLD.room_excursion(f.base_pose.x, f.base_pose.y, slack=0.0)
        is not None
        for f in scn.states(seed=0)
    ]
    assert not outside[0], "it starts inside"
    assert not outside[-1], "and it ends inside"
    assert any(outside), "and it is outside in between — otherwise nothing to catch"
    # Exactly one contiguous excursion: leaves once, returns once. `groupby`
    # over the booleans is the run-length encoding.
    runs = [flag for flag, _ in itertools.groupby(outside)]
    assert runs == [False, True, False], f"expected one excursion, got {runs}"


def test_a_base_that_leaves_the_room_between_two_waypoints_is_refused() -> None:
    """**NEGATIVE, and the one this issue is named for.**

    Every knot of this path is inside the room and the fixture therefore
    constructs. What leaves it is the trajectory the base *executes* — the
    excursion the test above watches, half a metre past a knot with 0.05 m of
    clearance. No check on the waypoints can see that, and no check on the
    interpolated *script* can either: the room is convex, so a straight line
    between two knots that both fit cannot leave it.

    The refusal has to name the instant and the part. A fixture author holding
    "outside the room" and 501 frames is bisecting by hand.
    """
    scn = _overshooting()
    with pytest.raises(ValueError, match="the base leaves the room at t=") as caught:
        list(scn.states(seed=0))
    message = str(caught.value)
    # Which part: here the base is well inside and its reach is not, which is a
    # different fixture bug from a base mounted outside its room.
    assert "arm sweeps out of the room" in message
    assert "seed 0" in message
    # Which instant: strictly inside the run and not on a knot. Deliberately not
    # a fixed time — pinning 4.4 s would make this a golden value for the
    # integrator rather than a statement about the check. It fires *before* the
    # turn at t=5.0, because the base overtakes its own reference on the
    # approach; the refusal only has to be mid-interpolation, not late.
    moment = float(message.split("at t=")[1].split(" s")[0])
    assert 0.0 < moment < scn.duration
    knots = [wp.t for wp in scn.base_waypoints]
    assert all(abs(moment - knot) > 1e-9 for knot in knots), (
        f"{moment} is a knot of {knots}; a refusal landing on one would be a "
        "waypoint check reporting itself late, which is not what this rests on"
    )


def test_a_driving_fixture_that_stays_in_the_room_runs_to_the_end() -> None:
    """**The positive the negative above needs.** A check that only ever refuses
    is not a check.

    The same room, the same integrator and the same shape of manoeuvre, with the
    overshoot inside the clearance instead of past it: `MOBILE_LIMITS` brakes at
    1.2 m/s^2, and the turn is at x=1.5 rather than 2.0, so the base runs a few
    centimetres past a knot with 0.55 m to spare. Every frame is produced and
    every one of them holds the whole robot.
    """
    scn = _overshooting(
        world=MOBILE_WORLD,
        base_waypoints=(
            Waypoint(0.0, (0.0, 0.0, 0.0)),
            Waypoint(5.0, (1.5, 0.0, 0.0)),
            Waypoint(10.0, (0.0, 0.0, 0.0)),
        ),
    )
    frames = list(scn.states(seed=0))
    assert len(frames) == scn.n_frames
    assert max(f.base_pose.x for f in frames) > 1.5, "it does reach the turn"
    for f in frames:
        assert scn.world.room_excursion(f.base_pose.x, f.base_pose.y, slack=0.0) is None


# --------------------------------------------------------------------------
# THE THREE MOBILE FIXTURES (issue #178, docs/mobile-base.md §7 Tier 4)
#
# Everything above this point tests a base that *can* drive against a scenario
# built inside this file. These are the shipped ones, and the difference is the
# whole of Tier 4: a claim demonstrated against a fixture constructed by its own
# test is a claim about the test.
#
# What is asserted here is what each fixture's own comment says it is for, plus
# the two halves that hold of all three: the catalogue is a second one rather
# than an addition to the first (which is what keeps Claim 1 a fixed-arm claim),
# and the executed base trajectory obeys the bounds the outer envelope's
# soundness argument assumes.
#
# The fault each one does or does not produce needs the real enforcer over the
# real declarations and lives in `tests/test_enforce.py`, as it does for the
# eleven.
# --------------------------------------------------------------------------


def test_the_mobile_catalogue_is_exactly_the_three_named_fixtures() -> None:
    """Three, each named for the claim it exercises, each keyed by its own name."""
    assert list(MOBILE_SCENARIOS) == MOBILE_NAMES
    for key, scn in MOBILE_SCENARIOS.items():
        assert scn.name == key
        assert scn.drives is True
        assert scn.world is MOBILE_WORLD
        # Resolvable by name, or a stream naming one could not be rebuilt:
        # the robot's `Limits` and the human's radius are not columns
        # (`reg.graph._resolve_world`).
        assert scenario(key) is scn


def test_the_mobile_fixtures_are_a_second_catalogue_and_not_an_addition_to_the_first() -> None:
    """**The half every published figure depends on** (docs/mobile-base.md §5).

    `SCENARIOS` is what `reg.bench --all` prices and what docs/retention.md is
    measured over, and Claim 1 stays a fixed-arm claim. A mobile fixture in that
    mapping would be priced beside the eleven by arithmetic rather than by
    argument — and it writes a wider stream besides, so the gzip baseline every
    ratio is divided by would move too.

    Both directions are asserted. The eleven are still the eleven and none of
    them drives; the three are resolvable and none of them is registered.
    """
    assert list(SCENARIOS) == EXPECTED_NAMES
    assert set(SCENARIOS) & set(MOBILE_SCENARIOS) == set()
    assert not any(scenario(name).drives for name in EXPECTED_NAMES)
    assert all(scenario(name).drives for name in MOBILE_NAMES)


def test_the_benchmark_refuses_to_price_a_mobile_fixture(capsys) -> None:
    """**NEGATIVE, and the one that keeps Claim 1 a fixed-arm claim.**

    Keeping the three out of `SCENARIOS` is only worth something if the thing
    that iterates `SCENARIOS` also refuses them by name — otherwise
    `reg.bench --scenario mobile_transit` would produce a row in the same table
    as the eleven, and a mobile artifact's bytes would have been reported beside
    figures they are not comparable to (a driving run writes the two optional
    base blocks, so the gzipped baseline every ratio is divided by is a
    different file).

    The control is the other half: a fixed-base name is still accepted, so this
    is a refusal of *these* fixtures and not a benchmark that has stopped
    accepting `--scenario` at all.
    """
    from reg import bench

    parser = bench._parser()
    with pytest.raises(SystemExit):
        bench._selected(parser.parse_args(["--scenario", "mobile_transit"]), parser)
    err = capsys.readouterr().err
    assert "unknown scenario" in err, err

    accepted = bench._selected(parser.parse_args(["--scenario", "contact"]), parser)
    assert accepted == ["contact"], (
        "the benchmark no longer accepts a fixed-base fixture either, so the "
        "refusal above says nothing about the mobile ones"
    )


def test_an_unknown_name_names_the_mobile_fixtures_too() -> None:
    """A typo in a mobile name must not read as 'that fixture does not exist'."""
    with pytest.raises(KeyError, match="unknown scenario") as refusal:
        scenario("mobile_transt")
    message = refusal.value.args[0]
    for name in MOBILE_NAMES:
        assert name in message, message


@pytest.mark.parametrize("name", MOBILE_NAMES)
@pytest.mark.parametrize("seed", SEEDS)
def test_every_mobile_fixture_records_a_pose_and_a_rate_on_every_frame(
    name: str, seed: int
) -> None:
    """A driving fixture writes both blocks, with both provenances, throughout.

    A run that recorded a pose on some frames and not others is refused by
    `reg.stream` and again by `reg.graph.build` (issue #191), because where a
    run recorded a pose is a whole-run fact. Nothing here should ever produce
    one, and this is where that is checked at the source.
    """
    scn = scenario(name)
    got = list(scn.states(seed))
    assert len(got) == scn.n_frames
    for f in got:
        assert f.base_pose is not None and f.base_vel is not None
        assert f.base_pose.source is scn.base_pose_source
        assert f.base_vel.source is scn.base_vel_source


@pytest.mark.parametrize("name", MOBILE_NAMES)
@pytest.mark.parametrize("seed", SEEDS)
def test_every_mobile_fixture_executes_a_trajectory_its_base_could_execute(
    name: str, seed: int
) -> None:
    """All four base bounds, on the trajectory the frames actually record.

    The same property `test_the_executed_base_trajectory_obeys_the_bases_own_
    bounds` asserts of the probe scenario, on the shipped ones — and it is
    load-bearing here for the reason issue #164 makes it load-bearing: since
    `computed_bound` refuses a robot that drives, every VETO in a mobile run
    rests on `reg.envelope.outer_envelope`, whose soundness argument assumes a
    plant that respects exactly these four numbers.
    """
    scn = scenario(name)
    limits = scn.world.limits
    got = list(scn.states(seed))
    assert max(np.hypot(f.base_vel.vx, f.base_vel.vy) for f in got) <= (
        limits.base_v_max + 1e-12
    )
    assert max(abs(f.base_vel.omega) for f in got) <= limits.base_omega_max + 1e-12
    for a, b in zip(got, got[1:]):
        step = float(np.hypot(*(_room_frame(b) - _room_frame(a))))
        assert step <= limits.base_a_max * scn.dt + 1e-12
        assert abs(b.base_vel.omega - a.base_vel.omega) <= (
            limits.base_alpha_max * scn.dt + 1e-12
        )


@pytest.mark.parametrize("name", MOBILE_NAMES)
@pytest.mark.parametrize("seed", SEEDS)
def test_no_mobile_fixture_drives_at_its_own_speed_cap(name: str, seed: int) -> None:
    """**The trap this tier walked into, kept shut.**

    A base capped at exactly `base_v_max` is legal in memory and unbuildable on
    disk: `reg.stream` writes at `FLOAT_PRECISION` decimals, so a rate at the cap
    can round back a fraction over it, and `reg.envelope.base_motion_bounds`
    then refuses the state — correctly, because its displacement bound is an
    upper bound only while `|v0| <= v_max`. The first draft of `mobile_transit`
    saturated, wrote a clean stream, and could not be built from it.

    So the margin is asserted against the quantum the stream is written at
    rather than against a number chosen here: half an ulp of the last written
    decimal is the most the round trip can move a component, and a fixture with
    a hundred of those in hand cannot be pushed over its own cap by rounding.
    """
    from reg.stream import FLOAT_PRECISION

    scn = scenario(name)
    limits = scn.world.limits
    quantum = 0.5 * 10.0 ** (-FLOAT_PRECISION)
    speed = max(float(np.hypot(f.base_vel.vx, f.base_vel.vy)) for f in scn.states(seed))
    assert limits.base_v_max - speed > 100.0 * quantum, (
        f"{name} at seed {seed} peaks at {speed} m/s against a cap of "
        f"{limits.base_v_max}; that is inside the rounding of the stream it "
        "will be written to, and the build will refuse the state it reads back"
    )


@pytest.mark.parametrize("name", MOBILE_NAMES)
def test_the_outer_bound_contains_the_driven_body_it_promises_to(name: str) -> None:
    """**The soundness test that matters most for a robot that drives** (#164).

    `test_the_outer_bound_contains_the_body_it_promises_to` asks this of the
    eleven, where the bound is floored by a workspace disc anyway. Here there is
    no floor: `computed_bound` refuses this robot, so the outer set is the only
    thing standing between a declaration and a VETO, and the promise it makes is
    that the body cannot leave it within the horizon.

    The comparison is in the body frame of the frame the bound was computed at,
    because that is the frame `outer_envelope` returns its set in: the body at a
    later frame is placed at that frame's *room* pose and then carried back
    through the earlier pose. Both halves of the base's motion are in that
    transform — the metres it drove and the radians it turned — so a bound that
    had forgotten either would fail here.
    """
    scn = scenario(name)
    got = list(scn.states(seed=0))
    horizon = 0.2
    span = int(round(horizon / scn.dt))
    for i in range(0, len(got) - span, max(1, span // 2)):
        outer = outer_envelope(
            got[i].proprio(), scn.world.limits, horizon=horizon, base=ORIGIN_FRAME
        )
        for j in range(i, i + span + 1):
            body = _in_the_frame_of(got[j], got[i], scn.world.limits)
            escaped = body.difference(outer).area
            assert escaped == 0.0, (
                f"{name}: the body at frame {j} escapes the outer set computed "
                f"at frame {i} by {escaped:.6f} m^2. For this robot that set is "
                "the whole bound (issue #164), so what escapes it is what a "
                "VETO would have failed to catch."
            )


def _in_the_frame_of(later, earlier, limits) -> Polygon:
    """`later`'s body, in the body frame `earlier`'s outer envelope is stated in.

    Room-frame placement of the later configuration, then the inverse of the
    earlier pose. Written out rather than taken from `reg.graph._place` and
    inverted, because the point of the test is to compose the transform from the
    poses the *frames* record.
    """
    from shapely.affinity import affine_transform

    body = unary_union(link_polygons(np.asarray(later.q, dtype=float), limits))
    for pose, sign in ((later.base_pose, +1.0), (earlier.base_pose, -1.0)):
        theta = sign * float(pose.theta)
        cos, sin = float(np.cos(theta)), float(np.sin(theta))
        if sign > 0.0:
            body = affine_transform(
                body, (cos, -sin, sin, cos, float(pose.x), float(pose.y))
            )
        else:
            body = affine_transform(body, (1.0, 0.0, 0.0, 1.0, -float(pose.x), -float(pose.y)))
            body = affine_transform(body, (cos, -sin, sin, cos, 0.0, 0.0))
    return body


# --- mobile_transit: the room-frame answer is Layer B -----------------------


@pytest.mark.parametrize("seed", SEEDS)
def test_the_transit_fixture_reaches_a_coordinate_its_starting_base_could_not(
    seed: int,
) -> None:
    """**The claim `mobile_transit` exists for** (docs/sufficiency.md §5.6).

    Three statements about one stationary person, and the middle one is the
    fixture:

    1. From the base pose the run *starts* at, they are outside the workspace
       disc — the set of every configuration of the arm with no horizon in it —
       so no Layer A question asked at t=0 puts the robot near them.
    2. From the base pose the run *ends* at, they are inside the arm's forward
       reachable set, computed from proprioception and placed at the pose.
    3. Nothing touches them, so this is a reachability claim and not a contact
       one.

    What changed between 1 and 2 is a room-frame pose the robot did not measure,
    which is exactly why the room-frame answer is Layer B and the body-frame one
    is not.
    """
    scn = scenario("mobile_transit")
    got = list(scn.states(seed))
    first, last = got[0], got[-1]

    start_gap = (
        float(np.hypot(first.human_pos[0] - first.base_pose.x,
                       first.human_pos[1] - first.base_pose.y))
        - scn.world.max_reach
        - scn.world.human_radius
    )
    assert start_gap > 0.0, (
        "the person is inside the workspace disc at the first frame, so the run "
        "does not begin from a pose that could not reach them"
    )

    inside = _human_in_the_envelope(last, scn)
    assert inside, (
        "the person is not inside the reachable envelope at the last frame, so "
        "the drive did not change the answer and the fixture claims nothing"
    )
    assert not _human_in_the_envelope(first, scn), (
        "the person is already inside the envelope at the first frame"
    )

    for f in got:
        assert _body_clearance(f, scn) > 0.0, (
            f"mobile_transit contacts the person at t={f.t}; it is a "
            "reachability fixture and `contact` is a different one"
        )


def _human_in_the_envelope(frame, scn) -> bool:
    """Whether the human disc meets the room-frame envelope at one frame.

    The envelope is the body-frame set `compute_envelope` returns placed at the
    frame's own pose — `reg.graph` does exactly this and for the reason
    docs/mobile-base.md §2 gives. Four samples, which is the corner count for
    this arm: the sampled set only grows with more, so a positive found here is
    a positive at any resolution the builder uses.
    """
    from shapely.affinity import affine_transform

    env = compute_envelope(
        frame.proprio(), scn.world.limits, horizon=0.2, n_samples=4, seed=0
    )
    pose = frame.base_pose
    cos, sin = float(np.cos(pose.theta)), float(np.sin(pose.theta))
    env = affine_transform(env, (cos, -sin, sin, cos, float(pose.x), float(pose.y)))
    return env.intersects(_human_disc(frame, scn))


def _human_disc(frame, scn) -> Polygon:
    return Point(float(frame.human_pos[0]), float(frame.human_pos[1])).buffer(
        scn.world.human_radius
    )


def _body_clearance(frame, scn) -> float:
    """Metres between the robot's placed body and the human disc at one frame."""
    from shapely.affinity import affine_transform

    body = unary_union(
        link_polygons(np.asarray(frame.q, dtype=float), scn.world.limits)
    )
    pose = frame.base_pose
    cos, sin = float(np.cos(pose.theta)), float(np.sin(pose.theta))
    body = affine_transform(body, (cos, -sin, sin, cos, float(pose.x), float(pose.y)))
    return float(body.distance(_human_disc(frame, scn)))


# --- mobile_frozen_arm: driving is not reaching -----------------------------


@pytest.mark.parametrize("seed", SEEDS)
def test_the_frozen_arm_fixture_freezes_its_arm_and_drives_its_base(seed: int) -> None:
    """The arrangement, checked at the source. Both halves, because one is not it.

    A run whose arm crept would not be a frozen arm, and a run whose base sat
    still would not be driving. `q_jitter=0.0` is what makes the first true and
    it is stated on the fixture rather than left to be noticed here.
    """
    scn = scenario("mobile_frozen_arm")
    assert scn.q_jitter == 0.0
    got = list(scn.states(seed))
    for f in got:
        assert np.array_equal(f.q, got[0].q), f"the arm moved at t={f.t}"
        assert not np.any(f.qd), f"the arm has a velocity at t={f.t}"
    assert abs(got[-1].base_pose.x - got[0].base_pose.x) > 0.9
    assert abs(got[-1].base_pose.theta - got[0].base_pose.theta) > 0.5


@pytest.mark.parametrize("seed", SEEDS)
def test_driving_is_not_reaching_over_a_run_that_actually_drove(seed: int) -> None:
    """**The claim `mobile_frozen_arm` exists for** (issue #165, §4 item 6).

    `reg.declare._classify` reads `reach` against `retract` off the arm's own
    extension, measured in the body frame and blind to the base. Before issue
    #165 it measured from the room origin, which is the same number for a bolted
    arm and a different one for a vehicle: drive forward with a frozen arm and
    the tip's distance from the origin grows, so the interval was recorded as a
    `reach` the robot never made.

    This is that regression put to a run rather than to a constructed pair of
    frames — the base poses handed to the classifier are the ones the fixture
    recorded. The tip travels most of a metre through the room; the extension
    does not move by one bit; the classification is `traverse`, which is what
    the vocabulary has for a body that moved and an arm that did not.
    """
    import reg.declare
    from reg.kinematics import BaseFrame, forward_kinematics

    scn = scenario("mobile_frozen_arm")
    limits = scn.world.limits
    got = list(scn.states(seed))
    configs = np.array([np.asarray(f.q, dtype=float) for f in got])
    bases = tuple(
        BaseFrame(x=f.base_pose.x, y=f.base_pose.y, theta=f.base_pose.theta)
        for f in got
    )

    # The room really did move the end effector, or there is nothing to be blind
    # to. Measured from the origin, which is what the defective version used.
    from_origin = [
        float(np.linalg.norm(forward_kinematics(f.q, limits, base)[-1][1]))
        for f, base in zip(got, bases)
    ]
    assert from_origin[-1] - from_origin[0] > 0.5

    # And the arm's own extension did not, to the bit.
    extensions = {reg.declare._extension(config, limits) for config in configs}
    assert len(extensions) == 1

    assert reg.declare._classify(configs, limits, bases) == "traverse", (
        "a frozen arm on a driving base is a traverse; `reach` here would mean "
        "the classifier is reading the base's motion as the arm's"
    )
