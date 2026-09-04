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

import numpy as np
import pytest
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import unary_union

from reg.enforce import FAULTS
from reg.envelope import compute_envelope, outer_envelope
from reg.scenarios import (
    DEFAULT_DT,
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

#: A `Limits` that can drive, identical to `reg.world.LIMITS` in its arm. The
#: four base numbers are fixture parameters stated here, not measurements: this
#: file needs a base that can execute a script, and `Scenario` refuses one that
#: cannot (`test_a_trajectory_on_a_bolted_base_is_refused`).
MOBILE_LIMITS = Limits(
    q_min=np.array([-np.pi, -2.6]),
    q_max=np.array([np.pi, 2.6]),
    qd_max=np.array([2.0, 2.5]),
    qdd_max=np.array([8.0, 10.0]),
    link_lengths=np.array([0.5, 0.4]),
    source=LimitSource.PROPRIOCEPTIVE,
    link_radius=0.05,
    base_v_max=0.8,
    base_a_max=1.2,
    base_omega_max=1.0,
    base_alpha_max=2.0,
)

MOBILE_WORLD = World(
    room=ROOM,
    obstacles=DEMO_WORLD.obstacles,
    limits=MOBILE_LIMITS,
    human_radius=DEMO_WORLD.human_radius,
)


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
