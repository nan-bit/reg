"""The fixtures, tested against what their names claim.

A scenario called `contact` that never produces a contact is worse than no
fixture at all: every downstream test written against it passes for the wrong
reason, and the incident report in Phase 7 gets built on a run where nothing
happened. So the interesting tests here are the paired ones — `contact` must
intersect a link polygon and `static_bystander` must never do so — and they run
across several seeds, because a fixture that only holds for seed 0 is a golden
value in disguise.

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

import numpy as np
import pytest
from shapely.geometry import LineString, Point, Polygon

from reg.envelope import compute_envelope
from reg.scenarios import (
    DEFAULT_DT,
    SCENARIOS,
    Scenario,
    Waypoint,
    scenario,
)
from reg.types import Limits, Obstacle
from reg.world import BASE_XY, DEMO_WORLD, LIMITS, ROOM, Room, World

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
]


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
    points = [np.asarray(BASE_XY, dtype=float)]
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


def test_scenarios_are_exactly_the_six_named() -> None:
    assert list(SCENARIOS) == EXPECTED_NAMES, (
        "SCENARIOS is the authoritative list; the six names are fixtures the "
        "whole project is measured against, so adding or dropping one is a "
        "change to what is being claimed."
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


@pytest.mark.parametrize("name", EXPECTED_NAMES)
def test_every_scenario_produces_frames(name: str) -> None:
    got = frames(name, seed=0)
    sc = scenario(name)
    assert len(got) == sc.n_frames > 1
    assert len(got) == int(round(sc.duration / sc.dt)) + 1
    for f in got:
        assert f.q.shape == (len(DEMO_WORLD.limits.link_lengths),)
        assert f.qd.shape == f.q.shape
        assert f.human_pos.shape == (2,)
        assert f.human_vel.shape == (2,)


@pytest.mark.parametrize("name", EXPECTED_NAMES)
def test_timestamps_are_monotonic_at_the_stated_dt(name: str) -> None:
    sc = scenario(name)
    times = np.array([f.t for f in sc.states(seed=0)])
    assert times[0] == 0.0
    assert np.all(np.diff(times) > 0.0)
    assert np.allclose(np.diff(times), sc.dt, atol=1e-12)
    assert times[-1] == pytest.approx(sc.duration, abs=1e-12)
    assert sc.dt == DEFAULT_DT  # all six fixtures run at the plan's 50 Hz


@pytest.mark.parametrize("name", EXPECTED_NAMES)
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


@pytest.mark.parametrize("name", EXPECTED_NAMES)
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


@pytest.mark.parametrize("name", EXPECTED_NAMES)
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


@pytest.mark.parametrize("name", EXPECTED_NAMES)
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


def test_only_declared_violation_declares_a_bound() -> None:
    """`None` means not-applicable, and must not be readable as permission."""
    for name, sc in SCENARIOS.items():
        if name == "declared_violation":
            assert sc.declared_q_bounds is not None
        else:
            assert sc.declared_q_bounds is None


@pytest.mark.parametrize("name", EXPECTED_NAMES)
@pytest.mark.parametrize("seed", SEEDS)
def test_commands_stay_within_the_physical_limits(name: str, seed: int) -> None:
    for f in scenario(name).states(seed):
        assert np.all(f.q >= LIMITS.q_min), f"{name}: q below q_min at t={f.t}"
        assert np.all(f.q <= LIMITS.q_max), f"{name}: q above q_max at t={f.t}"


@pytest.mark.parametrize("name", EXPECTED_NAMES)
def test_the_human_stays_in_the_room_and_clear_of_the_obstacles(name: str) -> None:
    """Obstacles are static scenery here; a human walking through one would make
    every separation answer about that entity meaningless."""
    for f in scenario(name).states(seed=11):
        x, y = float(f.human_pos[0]), float(f.human_pos[1])
        assert ROOM.contains_circle(x, y, DEMO_WORLD.human_radius)
        for obs in f.objects:
            gap = float(np.hypot(x - obs.cx, y - obs.cy)) - obs.radius - DEMO_WORLD.human_radius
            assert gap > 0.0, f"{name}: human overlaps {obs.entity_id} at t={f.t}"


@pytest.mark.parametrize("name", EXPECTED_NAMES)
def test_every_frame_carries_the_worlds_obstacles(name: str) -> None:
    """The plan logs static objects per frame on purpose: the raw stream must be
    inflated honestly, or Claim 1 compares against a baseline nobody would log."""
    for f in scenario(name).states(seed=0):
        assert f.objects == DEMO_WORLD.obstacles
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


def test_world_rejects_a_world_the_robot_is_not_in() -> None:
    """The base is fixed at the origin by reg/kinematics.py; a room that does not
    contain it describes a robot mounted outside its own room."""
    with pytest.raises(ValueError, match="robot base"):
        World(
            room=Room(x_min=5.0, y_min=5.0, x_max=6.0, y_max=6.0),
            obstacles=(),
            limits=LIMITS,
            human_radius=0.25,
        )


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


def test_scenarios_are_frozen() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        scenario("contact").duration = 1.0  # type: ignore[misc]
