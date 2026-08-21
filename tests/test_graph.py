"""The evidence graph: the incremental rule, the schema, and what both refuse.

THE ONE TEST THIS FILE EXISTS FOR
---------------------------------
`test_edge_rows_do_not_grow_with_frame_count`. Claim 1 — the commercial argument
— is that the graph is orders of magnitude smaller than the raw stream, and
docs/plan.md says where that comes from: "the compression ratio comes almost
entirely from this", *this* being emit-on-change. So the claim is tested as an
invariant rather than as a ratio: a stream in which nothing changes produces the
same number of edge rows whether it is 6 frames long or 120. A golden ratio would
go green for a graph that quietly stopped compressing and started deduplicating,
or for one that dropped rows it should have kept.

Its negative is `test_a_change_larger_than_the_tolerance_is_not_collapsed`. A
compressor that collapses everything also passes the test above; what
distinguishes a discard from a lossy mess is that a relationship which moved by
more than `DISTANCE_TOL_M` is *never* folded into the previous interval.

WHAT THAT TEST DOES NOT COVER, AND WHERE THE REST OF IT IS
----------------------------------------------------------
It builds from a robot holding still, so the envelope is one polygon for the
whole run. That is the easy case for both halves of the rule, and the two issues
after it were both about the *moving* arm, where the envelope genuinely differs
every frame:

* issue #28 — the polygon was stored per frame. `test_geometry_rows_are_far_
  fewer_than_frames_in_a_moving_scenario` measures it and
  `test_envelope_at_recomputes_the_stored_polygon_exactly` is the gate on the
  discard being lossless.
* issue #29 — the *rows* were still per frame, so the artifact stayed linear in
  the frame count whatever the rows contained.
  `test_node_rows_do_not_grow_with_frame_count` and
  `test_node_rows_are_sub_linear_for_every_fixture` are the invariant, and
  `test_a_stream_that_changes_every_frame_still_emits_a_row_per_frame` is the
  negative that separates compression from deletion: a run in which something
  genuinely changes every frame must still cost a row every frame.
  `test_the_separation_timeline_answers_every_frame_within_tolerance` is the
  gate — the supported query still agrees with the raw stream frame by frame,
  which is what makes the missing rows a discard and not a hole.

Envelopes are computed with deliberately coarse parameters throughout (`_FAST`).
Cost is linear in `n_samples * horizon / substep_dt` and these tests are about
interval bookkeeping, not about envelope fidelity — `tests/test_envelope.py` owns
that. The parameters are passed explicitly at every call so that no test here
depends on a default staying put.
"""

from __future__ import annotations

import sqlite3
from collections import Counter
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
import shapely
from shapely.geometry import Point, Polygon
from shapely.ops import unary_union

from reg import graph, store
from reg.chain import (
    GENESIS_HASH,
    UNSIGNED_MAC,
    Keyring,
    MacState,
    chain_hash,
    write_keyring,
)
from reg.declare import Declaration, envelope_wkb, verify_declaration
from reg.enforce import Verdict, sign_verdict, verify_verdict
from reg.envelope import compute_envelope, envelope_hash
from reg.graph import (
    HUMAN_ENTITY_ID,
    AttestationRecords,
    GraphBuildError,
    build,
)
from reg.identity import RunIdentity
from reg.kinematics import link_polygons
from reg.scenarios import SCENARIOS
from reg.sim import provenance, simulate
from reg.stream import read_frames, write_frames
from reg.tolerances import (
    DISTANCE_TOL_M,
    TIME_BASE_MAX_RATE_HZ,
    TIME_TOL_S,
    distance_bucket,
    quantize_area,
    quantize_time,
    simplify_geometry,
)
from reg.types import Obstacle, StateFrame
from reg.world import DEMO_WORLD

LIMITS = DEMO_WORLD.limits
HUMAN_RADIUS = DEMO_WORLD.human_radius

#: The run identity every build in this file declares (issue #83). Stated once
#: for `SIM_SEED`'s reason: `build` records it in the artifact, and a test that
#: passed a different instant per call would be comparing two runs.
TEST_IDENTITY = RunIdentity.declare(
    run_start="2026-08-21T09:00:00Z",
    unit_id="unit-test-arm-1",
    operator_id="op-test",
)

#: The three identity flags as argv. Every CLI test that expects to get past
#: argument checking passes them: they are required with no default (issue #83),
#: and a test that omitted them would be exercising that refusal instead of
#: whatever it says it is exercising. `test_cli_refuses_a_build_with_no_identity`
#: is the one that omits them on purpose.
IDENTITY_ARGV = [
    "--run-start",
    TEST_IDENTITY.run_start_text,
    "--unit-id",
    TEST_IDENTITY.unit_id,
    "--operator-id",
    TEST_IDENTITY.operator_id,
]

#: The seed every scenario stream in this file is generated at. Stated once
#: rather than passed as a literal: `reg.sim` records it in the provenance block
#: and a test that used a different one per call would be comparing two runs.
SIM_SEED = 0

#: 50 Hz, the rate the scenarios are generated at.
DT = 0.02

#: One static obstacle, well clear of the arm's 0.95 m of body.
OBSTACLE = Obstacle(entity_id="obs_a", kind="crate", cx=1.6, cy=1.2, radius=0.25)

#: Stand-in envelope digests for the hand-built store fixtures below. Full-width
#: lowercase SHA-256 hex, because that is what `reg.envelope.envelope_hash`
#: produces and what `reg.store` stores as 32 raw bytes since issue #55 — a
#: three-character placeholder is refused now, and the test that feeds it one is
#: `test_a_short_envelope_hash_is_refused`.
_HASH_A = "a1" * 32
_HASH_B = "b2" * 32
_HASH_C = "c3" * 32
_HASH_D = "d4" * 32

#: Coarse but legal envelope parameters: 4 samples is exactly the corner count
#: for a two-link arm, so `compute_envelope` accepts it and the result is still
#: the union of the extreme controls.
_FAST = {"horizon": 0.1, "n_samples": 4, "seed": 0, "substep_dt": 0.05}

#: The arm laid along +x: body from (0, 0) to (0.9, 0), buffered to x <= 0.95.
Q_HELD = (0.0, 0.0)
QD_HELD = (0.0, 0.0)


# --------------------------------------------------------------------------
# Fixtures: synthetic streams, written through the real codec
# --------------------------------------------------------------------------


def _frame(frame_id: int, human_xy: tuple[float, float], q=Q_HELD, qd=QD_HELD):
    return StateFrame(
        t=frame_id * DT,
        q=np.array(q, dtype=float),
        qd=np.array(qd, dtype=float),
        human_pos=np.array(human_xy, dtype=float),
        human_vel=np.array([0.0, 0.0], dtype=float),
        objects=(OBSTACLE,),
    )


def _write_stream(
    path: Path, frames, *, scenario: str | None = "contact"
) -> Path:
    """Write a synthetic stream through `reg.stream`, not by hand.

    Through the real codec on purpose: a fixture built by string concatenation
    tests the graph against a format the rest of the project does not use.
    """
    comments = [] if scenario is None else ["reg-sim provenance v1", f"scenario={scenario}", "seed=0"]
    return write_frames(frames, path, comments=comments)


def _held_stream(path: Path, n_frames: int, human_xy=(2.0, 0.0)) -> Path:
    """`n_frames` in which absolutely nothing changes."""
    return _write_stream(path, [_frame(i, human_xy) for i in range(n_frames)])


def _build(csv: Path, out: Path, **overrides):
    # `identity` is overridable like every other parameter — the tests that vary
    # the declared start are the ones that show it reaches the artifact — but it
    # defaults to the one identity this file declares, so a test that is not
    # about time does not have to name an instant to say anything.
    params = {"identity": TEST_IDENTITY, **_FAST, **overrides}
    return build(csv, out, LIMITS, human_radius=HUMAN_RADIUS, **params)


def _edges(path: Path, **filters) -> list[sqlite3.Row]:
    conn = store.connect(path)
    try:
        return store.read_edges(conn, **filters)
    finally:
        conn.close()


def _scenario_stream(scn, dt: float, path: Path) -> Path:
    """One scenario's stream at a stated frame period. The same run, resampled.

    `Scenario` is frozen and carries `dt` as a field, so a copy at half the
    period is the same waypoints interpolated twice as often — the same
    trajectory and the same human walk, sampled finer. That is what makes the
    two builds comparable: nothing about the run changed, only how often it was
    looked at.
    """
    scn = replace(scn, dt=dt)
    return write_frames(scn.states(SIM_SEED), path, comments=provenance(scn, SIM_SEED))


def _envelope_digests(frames) -> list[str]:
    """The envelope's identity at each frame, computed the way `build` does.

    Several tests need "the envelope changed materially every frame" to be true
    before they say anything, and since issue #29 that fact can no longer be read
    off the row count — the artifact deliberately no longer keeps a row per
    frame. Reading it off the rows would also mean inferring the precondition
    from the thing under test.
    """
    return [
        envelope_hash(simplify_geometry(compute_envelope(f.proprio(), LIMITS, **_FAST)))
        for f in frames
    ]


# --------------------------------------------------------------------------
# The compression claim, and its negative
# --------------------------------------------------------------------------


@pytest.mark.parametrize("n_frames", [6, 25, 120])
def test_edge_rows_do_not_grow_with_frame_count(tmp_path: Path, n_frames: int) -> None:
    """The incremental principle, tested directly. THIS IS CLAIM 1.

    docs/plan.md: "A robot holding still for 3 seconds at 50Hz should produce ~1
    node, not 150." Nothing in this stream changes, so the row count must be a
    property of the *relationships* and not of the frame count.
    """
    csv = _held_stream(tmp_path / f"held_{n_frames}.csv", n_frames)
    result = _build(csv, tmp_path / f"held_{n_frames}.sqlite")

    assert result.frames == n_frames
    # One HAS_ENVELOPE, and one SEPARATION per entity (obstacle + human). No
    # INTERSECTS and no CONTACT: both are far outside a 0.1 s envelope. The four
    # attestation edges are zero because this build was given no record stream —
    # a zero here and a missing key in `meta` are two different facts and the
    # artifact carries both (issue #45, `META_ATTESTATION_RECORDS`).
    assert result.edges == {
        "HAS_ENVELOPE": 1,
        "INTERSECTS": 0,
        "SEPARATION": 2,
        "CONTACT": 0,
        "DECLARED": 0,
        "ADJUDICATED": 0,
        "ENFORCED": 0,
        "FOLLOWS": 0,
    }
    # And the nodes those edges anchor, once each — not per frame. There is no
    # `Timestep` kind to check: issue #29 removed it, and its absence from
    # `store.NODE_TABLES` is asserted in `test_there_is_no_per_frame_node_kind`.
    #
    # `Occurrence` is four (issue #35) and is also constant in the frame count:
    # the two ends of the run and one closest approach per entity. Nothing else
    # happens in a stream where nothing changes, which is the point — the event
    # layer counts events, and holding still is not one.
    assert result.nodes == {
        "Envelope": 1,
        "RobotConfig": 1,
        "Entity": 2,
        "Occurrence": 4,
        "Declaration": 0,
        "Verdict": 0,
    }


@pytest.mark.parametrize("n_frames", [12, 24, 240])
def test_node_rows_do_not_grow_with_frame_count(tmp_path: Path, n_frames: int) -> None:
    """The same invariant one level down, on the case that used to fail it.

    THIS IS ISSUE #29. The test above holds the arm still, so the envelope is one
    polygon and one row for the whole run whatever the rule is. Here the arm
    creeps: every frame is a materially different envelope, which under
    "emit on material change" meant a `Timestep` row and an `envelope` row per
    frame — linear in the frame count however small the rows were made, and a
    single-digit ceiling on the compression ratio by construction.

    Nothing about the *relationships* changes across these frames, so the node
    count must be a property of the relationships. Asserted as equality across a
    twentyfold range rather than as a ratio: a bound like "fewer than half the
    frames" would go green for a rule that still scaled, just more slowly.
    """
    frames = _creep_frames(n_frames, lambda i: (2.4, 0.0))
    assert len(set(_envelope_digests(frames))) == n_frames, (
        "precondition failed: the envelope did not change every frame, so this "
        "is the held-still case again and says nothing about issue #29."
    )
    csv = _write_stream(tmp_path / f"creep_{n_frames}.csv", frames)
    result = _build(csv, tmp_path / f"creep_{n_frames}.sqlite")

    assert result.frames == n_frames
    # Two envelopes and two configurations — the two ends of the run, which
    # `GEOMETRY_RETENTION` keeps and nothing else here anchors. The same numbers
    # at 12 frames and at 240, and the same four occurrences: the arm creeping
    # changes the envelope every frame and enters nothing, so no event happens.
    assert result.nodes == {
        "Envelope": 2,
        "RobotConfig": 2,
        "Entity": 2,
        "Occurrence": 4,
        "Declaration": 0,
        "Verdict": 0,
    }
    assert result.edges == {
        "HAS_ENVELOPE": 2,
        "INTERSECTS": 0,
        "SEPARATION": 2,
        "CONTACT": 0,
        "DECLARED": 0,
        "ADJUDICATED": 0,
        "ENFORCED": 0,
        "FOLLOWS": 0,
    }


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_node_rows_are_sub_linear_for_every_fixture(tmp_path: Path, name: str) -> None:
    """Every fixture, sampled twice as fast: same trajectory, twice the frames.

    The acceptance shape issue #14 used for edges, applied to nodes. Doubling the
    sample rate changes nothing about the run — the arm follows the same path and
    the human walks the same walk — so it changes nothing about which
    relationships hold or when they transition. A node count that tracked the
    frame count would double; one that is a property of the motion must not.

    The bar is **strictly slower than the frames**, not a fixed number, and the
    two reasons it cannot be tighter are both real. Doubling the rate genuinely
    does add transitions at the margin: a metric that crossed a quantum between
    two old frames now crosses it at a frame in between, and a quantity that
    drifted over a boundary and back inside one old frame period is now seen
    doing it. And a human walking steadily across the scene crosses a
    `DISTANCE_TOL_M` bucket every frame at either rate — that is the case
    `test_a_stream_that_changes_every_frame_still_emits_a_row_per_frame` exists
    to protect, so a bound that forbade it here would forbid the artifact from
    recording what happened.

    What must not happen is the count *following* the frames. Before this change
    it followed them exactly — one `Timestep` and one `envelope` row per frame,
    2.0x for 2.0x — so the strict inequality is the assertion that would have
    gone red, and it is the one the issue's acceptance criterion names.
    """
    scn = SCENARIOS[name]
    coarse = _scenario_stream(scn, scn.dt, tmp_path / f"{name}_coarse.csv")
    fine = _scenario_stream(scn, scn.dt / 2.0, tmp_path / f"{name}_fine.csv")

    a = build(
        coarse,
        tmp_path / f"{name}_coarse.sqlite",
        scn.world.limits,
        identity=TEST_IDENTITY,
        human_radius=scn.world.human_radius,
        **_FAST,
    )
    b = build(
        fine,
        tmp_path / f"{name}_fine.sqlite",
        scn.world.limits,
        identity=TEST_IDENTITY,
        human_radius=scn.world.human_radius,
        **_FAST,
    )

    assert b.frames == 2 * a.frames - 1, (
        "precondition failed: halving dt did not roughly double the frame count, "
        "so there is no frame-count increase to be sub-linear in."
    )
    total_a = sum(a.nodes.values())
    total_b = sum(b.nodes.values())
    frame_growth = b.frames / a.frames
    node_growth = total_b / total_a
    assert node_growth < frame_growth, (
        f"{name}: {total_a} nodes at {a.frames} frames and {total_b} at "
        f"{b.frames} — {node_growth:.2f}x for {frame_growth:.2f}x more frames. "
        "The node count is tracking the frame count, which is the linearity "
        "issue #29 exists to remove."
    )
    # The `Envelope` row is what issue #29 moved, so it is asserted on its own
    # rather than left to hide inside a total that the entity rows and the
    # separation-anchoring configs also contribute to.
    assert b.nodes["Envelope"] / a.nodes["Envelope"] < frame_growth, (
        f"{name}: {a.nodes['Envelope']} envelope rows at {a.frames} frames and "
        f"{b.nodes['Envelope']} at {b.frames}."
    )


def test_the_single_interval_spans_the_whole_hold(tmp_path: Path) -> None:
    """Constant row count is only compression if the interval still covers the
    run. One row spanning [0, 0] would pass the count test and lose 119 frames."""
    n_frames = 120
    csv = _held_stream(tmp_path / "held.csv", n_frames)
    _build(csv, tmp_path / "held.sqlite")

    for row in _edges(tmp_path / "held.sqlite"):
        assert row["t_start"] == pytest.approx(0.0)
        assert row["t_end"] == pytest.approx(quantize_time((n_frames - 1) * DT))


def test_a_change_larger_than_the_tolerance_is_not_collapsed(tmp_path: Path) -> None:
    """THE NEGATIVE TEST. Feed the incremental rule the condition it guards
    against and assert it says no.

    The human jumps far enough that the separation must land in a different
    `DISTANCE_TOL_M` bucket. A rule that collapsed this would be a rule that
    collapses everything, and the count test above would not notice.
    """
    switch = 10
    n_frames = 20
    near, far = (1.6, 0.0), (2.4, 0.0)
    frames = [
        _frame(i, near if i < switch else far) for i in range(n_frames)
    ]
    csv = _write_stream(tmp_path / "step.csv", frames)
    _build(csv, tmp_path / "step.sqlite")

    rows = _edges(tmp_path / "step.sqlite", edge_type="SEPARATION", dst_id=HUMAN_ENTITY_ID)
    assert len(rows) == 2, (
        "the human moved 0.8 m, which is 80 quanta; the separation edge must "
        "have been closed and a new one opened, not extended."
    )
    assert abs(rows[0]["min_distance"] - rows[1]["min_distance"]) > DISTANCE_TOL_M

    # ...and the new row starts at the frame the change happened, not at the
    # frame after it and not at the start of the run.
    assert rows[0]["t_start"] == pytest.approx(0.0)
    assert rows[0]["t_end"] == pytest.approx(quantize_time((switch - 1) * DT))
    assert rows[1]["t_start"] == pytest.approx(quantize_time(switch * DT))
    assert rows[1]["t_end"] == pytest.approx(quantize_time((n_frames - 1) * DT))


def test_a_drift_inside_one_quantum_extends_the_edge(tmp_path: Path) -> None:
    """The positive half of the same rule: sub-quantum drift must not emit a row.

    The precondition is asserted rather than assumed. Two positions a fraction of
    a millimetre apart *usually* share a bucket but can straddle a boundary, and a
    test that silently passed in the straddling case would be testing nothing.
    """
    drift = 1e-5
    a, b = (2.0, 0.0), (2.0 + drift, 0.0)
    body = unary_union(link_polygons(np.array(Q_HELD), LIMITS))
    buckets = {
        distance_bucket(
            body.distance(simplify_geometry(Point(*xy).buffer(HUMAN_RADIUS)))
        )
        for xy in (a, b)
    }
    assert len(buckets) == 1, (
        "precondition failed: the two human positions do not share a distance "
        "bucket, so this test cannot say anything about sub-quantum drift."
    )

    frames = [_frame(i, a if i % 2 else b) for i in range(20)]
    csv = _write_stream(tmp_path / "drift.csv", frames)
    _build(csv, tmp_path / "drift.sqlite")

    rows = _edges(
        tmp_path / "drift.sqlite", edge_type="SEPARATION", dst_id=HUMAN_ENTITY_ID
    )
    assert len(rows) == 1


def test_an_interval_is_an_interval_of_the_relationship_not_the_envelope(
    tmp_path: Path,
) -> None:
    """A relationship edge extends across frames in which the envelope changed.

    This is the semantic decision `reg.graph._observe` documents, and it is where
    the compression on `INTERSECTS` and `SEPARATION` lives: keying those on the
    envelope hash as well would emit a row per frame for any moving arm.

    The arm here moves by 1e-6 rad per frame — the finest step the raw stream's
    own `FLOAT_PRECISION` can carry, and far above the 1 nm resolution
    `envelope_hash` distinguishes, so every frame is a material envelope change,
    and far below `DISTANCE_TOL_M`, so no separation moves a bucket. The
    precondition that the envelope really did change every frame is asserted,
    because if it ever stopped changing this test would pass while proving
    nothing.
    """
    n_frames = 12
    frames = [
        _frame(i, (2.0, 0.0), q=(1e-6 * i, 0.0), qd=(0.0, 0.0))
        for i in range(n_frames)
    ]
    assert len(set(_envelope_digests(frames))) == n_frames, (
        "precondition failed: the envelope did not change every frame, so this "
        "test says nothing about relationships outliving envelopes."
    )
    csv = _write_stream(tmp_path / "creep.csv", frames)
    out = tmp_path / "creep.sqlite"
    _build(csv, out)

    assert len(_edges(out, edge_type="SEPARATION")) == 2


def test_a_relationship_that_stops_holding_does_not_extend(tmp_path: Path) -> None:
    """An interval must end when the relationship ends, not run to the last frame.

    The human is inside the envelope for the first half of the run and outside it
    for the second. `INTERSECTS` therefore exists only over the first half — an
    edge extended to the end of the stream would report the robot could have
    reached someone who had left.
    """
    switch = 8
    n_frames = 16
    inside, outside = (0.6, 0.0), (2.4, 0.0)
    frames = [_frame(i, inside if i < switch else outside) for i in range(n_frames)]
    csv = _write_stream(tmp_path / "leave.csv", frames)
    _build(csv, tmp_path / "leave.sqlite")

    rows = _edges(
        tmp_path / "leave.sqlite", edge_type="INTERSECTS", dst_id=HUMAN_ENTITY_ID
    )
    assert rows, "precondition failed: the human never intersected the envelope"
    assert max(r["t_end"] for r in rows) < quantize_time((n_frames - 1) * DT)
    assert max(r["t_end"] for r in rows) == pytest.approx(
        quantize_time((switch - 1) * DT)
    )


def test_contact_is_recorded_as_an_interval_and_ends(tmp_path: Path) -> None:
    """`CONTACT` has no metric, so it extends for exactly as long as it holds."""
    n_frames = 12
    touching, clear = (0.5, 0.0), (2.4, 0.0)
    frames = [_frame(i, touching if 3 <= i < 7 else clear) for i in range(n_frames)]
    csv = _write_stream(tmp_path / "contact.csv", frames)
    _build(csv, tmp_path / "contact.sqlite")

    rows = _edges(
        tmp_path / "contact.sqlite", edge_type="CONTACT", dst_id=HUMAN_ENTITY_ID
    )
    assert len(rows) == 1
    assert rows[0]["t_start"] == pytest.approx(quantize_time(3 * DT))
    assert rows[0]["t_end"] == pytest.approx(quantize_time(6 * DT))
    assert rows[0]["min_distance"] is None  # CONTACT carries no metric


# --------------------------------------------------------------------------
# Schema invariants
# --------------------------------------------------------------------------


def test_every_edge_has_a_non_backwards_interval(tmp_path: Path) -> None:
    frames = [_frame(i, (2.4 - 0.1 * i, 0.0)) for i in range(15)]
    csv = _write_stream(tmp_path / "walk.csv", frames)
    _build(csv, tmp_path / "walk.sqlite")

    rows = _edges(tmp_path / "walk.sqlite")
    assert rows
    for row in rows:
        assert row["t_end"] >= row["t_start"]


def test_every_edge_carries_the_layer_its_type_implies(tmp_path: Path) -> None:
    """Claim 3 is a query over this column; an untagged edge is unusable.

    `HAS_ENVELOPE` is Layer A *when its limits are* — an envelope comes from
    proprioception and actuation limits alone, and the limits are the half whose
    provenance can be perception (issue #84). `LIMITS` here is a datasheet, so
    this build's envelopes are Layer A. Everything naming an entity is Layer B
    without that caveat, because where an entity is comes from perception in any
    real system.
    """
    frames = [_frame(i, (2.4 - 0.1 * i, 0.0)) for i in range(15)]
    csv = _write_stream(tmp_path / "walk.csv", frames)
    _build(csv, tmp_path / "walk.sqlite")

    rows = _edges(tmp_path / "walk.sqlite")
    assert rows
    for row in rows:
        assert row["layer"] in ("A", "B")
        assert row["layer"] in store.possible_layers(row["type"])
    assert {r["type"] for r in rows if r["layer"] == "A"} == {"HAS_ENVELOPE"}
    assert {r["type"] for r in rows if r["layer"] == "B"} <= {
        "INTERSECTS",
        "SEPARATION",
        "CONTACT",
    }


def test_layer_b_is_exactly_the_entity_naming_edges() -> None:
    """The vocabulary itself, independent of any run. A new edge type added
    without a layer decision fails here rather than in a query months later.

    Naming an entity is *sufficient* for Layer B and it is no longer necessary
    (issue #84): `HAS_ENVELOPE` names none and can still be Layer B, because an
    envelope inherits the provenance of the `Limits` it was integrated under.
    So the direction that still holds absolutely is the one asserted here — an
    entity-naming edge is Layer B and can be nothing else — and the type whose
    layer varies is enumerated rather than derived, so adding a second one is a
    decision somebody has to make here.
    """
    varies_with_provenance = {"HAS_ENVELOPE"}
    for edge_type, spec in store.EDGE_SPECS.items():
        layers = store.possible_layers(edge_type)
        if "Entity" in (spec.src_kind, spec.dst_kind):
            assert layers == {"B"}, (
                f"{edge_type} touches {spec.src_kind}->{spec.dst_kind} but may "
                f"be layer {sorted(layers)}. An edge naming an entity depends on "
                "perception, with no case in which it does not."
            )
        elif edge_type in varies_with_provenance:
            assert layers == {"A", "B"}, (
                f"{edge_type} is the edge type whose layer follows Limits.source "
                f"rather than its type, but it may only be {sorted(layers)}."
            )
        else:
            assert layers == {"A"}, (
                f"{edge_type} names no entity and is not in "
                f"{sorted(varies_with_provenance)}, so it is Layer A and only "
                f"Layer A — it may be {sorted(layers)}. A type whose layer varies "
                "needs a reason recorded, not a widened set."
            )


def test_geometry_round_trips_through_wkb(tmp_path: Path) -> None:
    """Stored geometry must come back as the geometry that was stored.

    Checked against a *recomputation*, not against a value carried in the test:
    the envelope is recomputed from the same proprioception and parameters and
    must be the same polygon the artifact holds.
    """
    csv = _held_stream(tmp_path / "held.csv", 6)
    out = tmp_path / "held.sqlite"
    _build(csv, out)

    expected_envelope = simplify_geometry(
        compute_envelope(
            _frame(0, (2.0, 0.0)).proprio(),
            LIMITS,
            horizon=_FAST["horizon"],
            n_samples=_FAST["n_samples"],
            seed=_FAST["seed"],
            substep_dt=_FAST["substep_dt"],
        )
    )
    expected_obstacle = simplify_geometry(
        Point(OBSTACLE.cx, OBSTACLE.cy).buffer(OBSTACLE.radius)
    )

    conn = store.connect(out)
    try:
        envelope_row = conn.execute("SELECT * FROM envelope").fetchone()
        entity_row = _entity_row(conn, OBSTACLE.entity_id)
        human_row = _entity_row(conn, HUMAN_ENTITY_ID)
    finally:
        conn.close()

    stored = store.from_wkb(envelope_row["geometry_wkb"])
    assert shapely.equals_exact(stored, expected_envelope, tolerance=0.0)
    assert store.from_wkb(entity_row["geometry_wkb"]).equals(expected_obstacle)

    # A moving entity stores no boundary: NULL is a refusal to answer "where was
    # the human at t", not an empty polygon that would clear every test it meets.
    assert human_row["geometry_wkb"] is None
    assert human_row["is_static"] == 0


def test_the_artifact_records_what_produced_it(tmp_path: Path) -> None:
    """docs/lossiness.md Retained #10. Determinism is only checkable if the
    artifact says what produced it — including the tolerances in force."""
    csv = _held_stream(tmp_path / "held.csv", 6)
    out = tmp_path / "held.sqlite"
    _build(csv, out)

    conn = store.connect(out)
    try:
        meta = store.all_meta(conn)
    finally:
        conn.close()

    assert meta["schema_version"] == str(store.SCHEMA_VERSION)
    assert float(meta["tolerance_distance_tol_m"]) == DISTANCE_TOL_M
    assert float(meta[store.META_FRAME_PERIOD]) == pytest.approx(DT)
    assert int(meta["envelope_n_samples"]) == _FAST["n_samples"]
    assert float(meta["human_radius_m"]) == HUMAN_RADIUS
    assert meta["human_entity_id"] == HUMAN_ENTITY_ID
    # The source stream's own provenance travels into the artifact, so the
    # scenario and simulator seed are recoverable from the graph alone.
    assert "scenario=contact" in meta["source_provenance"]
    # Nothing that varies between two runs of the same command may be in here.
    assert not any(str(tmp_path) in value for value in meta.values())


def test_a_stream_with_no_provenance_leaves_the_key_absent(tmp_path: Path) -> None:
    """Silence is a could-not-evaluate, never an empty string that reads as a
    provenance block saying nothing in particular."""
    csv = _write_stream(
        tmp_path / "bare.csv", [_frame(i, (2.0, 0.0)) for i in range(4)], scenario=None
    )
    out = tmp_path / "bare.sqlite"
    _build(csv, out)

    conn = store.connect(out)
    try:
        assert store.get_meta(conn, "source_provenance") is None
    finally:
        conn.close()


def test_two_builds_of_one_stream_are_byte_identical(tmp_path: Path) -> None:
    """Determinism is non-negotiable (CLAUDE.md rule 2). CI compares two runs."""
    csv = _held_stream(tmp_path / "held.csv", 20)
    a, b = tmp_path / "a.sqlite", tmp_path / "b.sqlite"
    _build(csv, a)
    _build(csv, b)
    assert a.read_bytes() == b.read_bytes()


def test_two_builds_of_a_moving_stream_are_byte_identical(tmp_path: Path) -> None:
    """The held-still stream never exercises the writes `GEOMETRY_RETENTION`
    added: an envelope row written without a polygon and updated with one a
    frame later. An `UPDATE` lands differently in a SQLite file than an
    `INSERT` does, so the determinism claim has to be made against a stream that
    does both."""
    inside, outside = (0.55, 0.0), (2.4, 0.0)
    frames = _creep_frames(12, lambda i: inside if 3 <= i <= 6 else outside)
    csv = _write_stream(tmp_path / "creep.csv", frames)
    a, b = tmp_path / "a.sqlite", tmp_path / "b.sqlite"
    _build(csv, a)
    _build(csv, b)
    assert a.read_bytes() == b.read_bytes()


def test_building_over_an_existing_artifact_replaces_it(tmp_path: Path) -> None:
    """Merging into a stale schema would describe two runs at once."""
    out = tmp_path / "out.sqlite"
    short = _held_stream(tmp_path / "short.csv", 6)
    long_stream = _write_stream(
        tmp_path / "long.csv", [_frame(i, (2.4 - 0.05 * i, 0.0)) for i in range(12)]
    )
    _build(long_stream, out)
    result = _build(short, out)
    assert result.edges["SEPARATION"] == 2


# --------------------------------------------------------------------------
# What the builder refuses. Each one is a could-not-evaluate.
# --------------------------------------------------------------------------


def test_a_one_frame_stream_is_refused(tmp_path: Path) -> None:
    """Without a frame period the artifact cannot state the resolution its
    interval endpoints are good to, which docs/lossiness.md requires it to."""
    csv = _write_stream(tmp_path / "one.csv", [_frame(0, (2.0, 0.0))])
    with pytest.raises(GraphBuildError, match="frame period"):
        _build(csv, tmp_path / "one.sqlite")


def test_a_non_uniform_frame_period_is_refused(tmp_path: Path) -> None:
    """`TIME_TOL_S` is a quantum, not a promise of resolution. A stream with no
    single frame period has no honest value to record, and claiming one would be
    the fabricated digit docs/lossiness.md names."""
    frames = [
        _frame(0, (2.0, 0.0)),
        _frame(1, (2.0, 0.0)),
        StateFrame(
            t=1.0,  # a 0.96 s gap where the rest are 0.02 s
            q=np.array(Q_HELD),
            qd=np.array(QD_HELD),
            human_pos=np.array([2.0, 0.0]),
            human_vel=np.array([0.0, 0.0]),
            objects=(OBSTACLE,),
        ),
    ]
    csv = _write_stream(tmp_path / "jitter.csv", frames)
    with pytest.raises(GraphBuildError, match="not uniform"):
        _build(csv, tmp_path / "jitter.sqlite")


def test_a_failed_build_leaves_no_artifact_behind(tmp_path: Path) -> None:
    """A half-written graph opens, queries, and answers every question after the
    failure with "the relationship stopped holding". Nothing distinguishes that
    from the truth, so the file must not survive the failure."""
    csv = _held_stream(tmp_path / "held.csv", 6)
    out = tmp_path / "partial.sqlite"
    with pytest.raises(ValueError):
        # n_samples below the 2**n corner count: compute_envelope refuses on the
        # first frame, after the artifact has been created and provenance written.
        _build(csv, out, n_samples=1)
    assert not out.exists()


def test_a_moving_obstacle_is_refused(tmp_path: Path) -> None:
    """The graph stores static geometry once. That collapse is only sound if the
    obstacle really is static, so it is checked rather than assumed."""
    moved = Obstacle(entity_id="obs_a", kind="crate", cx=1.7, cy=1.2, radius=0.25)
    frames = [_frame(i, (2.0, 0.0)) for i in range(4)]
    frames[2] = StateFrame(
        t=frames[2].t,
        q=frames[2].q,
        qd=frames[2].qd,
        human_pos=frames[2].human_pos,
        human_vel=frames[2].human_vel,
        objects=(moved,),
    )
    csv = _write_stream(tmp_path / "moved.csv", frames)
    with pytest.raises(GraphBuildError, match="obstacle set changed"):
        _build(csv, tmp_path / "moved.sqlite")


def test_an_obstacle_named_like_the_human_is_refused(tmp_path: Path) -> None:
    """Two entities sharing an id merge two histories into an answer about
    neither — the same failure `reg.world` refuses duplicate ids for."""
    clash = Obstacle(entity_id=HUMAN_ENTITY_ID, kind="crate", cx=1.6, cy=1.2, radius=0.25)
    frames = [
        StateFrame(
            t=i * DT,
            q=np.array(Q_HELD),
            qd=np.array(QD_HELD),
            human_pos=np.array([2.0, 0.0]),
            human_vel=np.array([0.0, 0.0]),
            objects=(clash,),
        )
        for i in range(4)
    ]
    csv = _write_stream(tmp_path / "clash.csv", frames)
    with pytest.raises(GraphBuildError, match="already uses the entity id"):
        _build(csv, tmp_path / "clash.sqlite")


@pytest.mark.parametrize("bad_radius", [0.0, -0.25])
def test_a_non_positive_human_radius_is_refused(
    tmp_path: Path, bad_radius: float
) -> None:
    """A human of no extent can never contact anything, so every contact
    question would answer 'no' for a reason nobody wrote down."""
    csv = _held_stream(tmp_path / "held.csv", 4)
    with pytest.raises(GraphBuildError, match="human_radius"):
        build(
            csv,
            tmp_path / "held.sqlite",
            LIMITS,
            identity=TEST_IDENTITY,
            human_radius=bad_radius,
            **_FAST,
        )


def test_human_radius_has_no_default() -> None:
    """It is not a column in the raw stream, so there is no correct guess.

    A plausible 0.25 m invented in `build` would be indistinguishable downstream
    from the value that actually produced the run, and every Layer B answer in
    the artifact would inherit it silently.
    """
    with pytest.raises(TypeError, match="human_radius"):
        build("nowhere.csv", "nowhere.sqlite", LIMITS)  # type: ignore[call-arg]


# --------------------------------------------------------------------------
# What the store refuses. The schema is a check, so it must be able to fail.
# --------------------------------------------------------------------------


@pytest.fixture()
def seeded(tmp_path: Path):
    """A store with one node of each kind, so edge tests have endpoints."""
    conn = store.create(tmp_path / "store.sqlite", record_tables=True)
    store.insert_robot_config(conn, "cfg_0", "0.000000,0.000000", "0.000000,0.000000")
    store.insert_envelope(
        conn,
        "env_0",
        envelope_hash=_HASH_A,
        area=0.25,
        geometry=Point(0.0, 0.0).buffer(0.5),
        config_id="cfg_0",
        horizon=0.2,
        source="computed",
    )
    store.insert_entity(conn, "obs_a", "crate", geometry=Point(2.0, 0.0).buffer(0.25))
    yield conn
    conn.close()


def test_a_backwards_interval_is_refused(seeded) -> None:
    with pytest.raises(store.StoreError, match="backwards"):
        store.open_edge(
            seeded, "HAS_ENVELOPE", "cfg_0", "env_0", 1.0, t_end=0.5, layer="A"
        )


def test_the_schema_itself_refuses_a_backwards_interval(seeded) -> None:
    """Not only the Python guard: an interval that runs backwards matches no
    time window, so it must be impossible to get into the file at all."""
    with pytest.raises(sqlite3.IntegrityError):
        seeded.execute(
            "INSERT INTO edge (type, layer, src_kind, src_key, dst_kind, "
            "dst_key, t_start, t_end) VALUES "
            "('HAS_ENVELOPE','A','RobotConfig',?,'Envelope',?, 1.0, 0.0)",
            (store.node_key(seeded, "cfg_0"), store.node_key(seeded, "env_0")),
        )


def test_the_schema_refuses_an_untagged_layer(seeded) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        seeded.execute(
            "INSERT INTO edge (type, layer, src_kind, src_key, dst_kind, "
            "dst_key, t_start, t_end) VALUES "
            "('HAS_ENVELOPE','?','RobotConfig',?,'Envelope',?, 0.0, 1.0)",
            (store.node_key(seeded, "cfg_0"), store.node_key(seeded, "env_0")),
        )


def test_extending_an_edge_backwards_is_refused(seeded) -> None:
    edge_id = store.open_edge(seeded, "HAS_ENVELOPE", "cfg_0", "env_0", 0.0, layer="A")
    store.extend_edge(seeded, edge_id, 2.0)
    with pytest.raises(store.StoreError, match="backwards"):
        store.extend_edge(seeded, edge_id, 1.0)


def test_an_unknown_edge_type_is_refused(seeded) -> None:
    """Not a default layer and not a silent skip: adding an edge type is a
    decision about which layer it belongs to.

    `DECLARED` was the example here until issue #45 made it a real edge type, so
    the example is now one that is still not in the vocabulary: `CONTAINS`,
    which docs/plan.md lists beside `INTERSECTS` and issue #14 de-scoped.
    """
    with pytest.raises(store.StoreError, match="not an edge type"):
        store.layer_of("CONTAINS")
    with pytest.raises(store.StoreError, match="not an edge type"):
        store.open_edge(seeded, "CONTAINS", "cfg_0", "env_0", 0.0)


def test_a_missing_metric_is_refused(seeded) -> None:
    """An INTERSECTS with a NULL overlap_area compares false against every
    threshold, so an incident reads as a non-incident."""
    with pytest.raises(store.StoreError, match="overlap_area"):
        store.open_edge(seeded, "INTERSECTS", "env_0", "obs_a", 0.0)
    with pytest.raises(store.StoreError, match="min_distance"):
        store.open_edge(seeded, "SEPARATION", "cfg_0", "obs_a", 0.0)


def test_a_metric_on_an_edge_that_does_not_carry_one_is_refused(seeded) -> None:
    with pytest.raises(store.StoreError, match="does not carry"):
        store.open_edge(
            seeded, "CONTACT", "cfg_0", "obs_a", 0.0, min_distance=0.5
        )


def test_an_edge_to_a_missing_node_is_refused(seeded) -> None:
    """A dangling reference returns nothing from every join, and nothing is
    indistinguishable from 'the relationship never held'."""
    with pytest.raises(store.StoreError, match="no Entity node"):
        store.open_edge(
            seeded, "SEPARATION", "cfg_0", "obs_nope", 0.0, min_distance=0.5
        )


def test_a_content_id_reused_for_different_contents_is_refused(seeded) -> None:
    """Node ids are content hashes. A collision would merge two histories."""
    with pytest.raises(store.StoreError, match="different"):
        store.insert_robot_config(seeded, "cfg_0", "9.999999,0.000000", "0.0,0.0")


def test_reinserting_an_identical_node_is_a_no_op(seeded) -> None:
    store.insert_robot_config(seeded, "cfg_0", "0.000000,0.000000", "0.000000,0.000000")
    assert seeded.execute("SELECT count(*) AS n FROM robot_config").fetchone()["n"] == 1


def test_storing_an_empty_geometry_is_refused(seeded) -> None:
    """Read back it is a region of no extent, which clears every intersection
    test that meets it."""
    with pytest.raises(store.StoreError, match="empty"):
        store.to_wkb(Polygon())


def test_storing_an_invalid_geometry_is_refused(seeded) -> None:
    with pytest.raises(store.StoreError, match="invalid"):
        store.to_wkb(Polygon([(0, 0), (1, 1), (1, 0), (0, 1)]))


def test_an_out_of_vocabulary_envelope_source_is_refused(seeded) -> None:
    """An unrecognised source would make a clamped bound indistinguishable from
    a declared one."""
    with pytest.raises(store.StoreError, match="vocabulary"):
        store.insert_envelope(
            seeded,
            "env_1",
            envelope_hash=_HASH_B,
            area=0.25,
            geometry=Point(0.0, 0.0).buffer(0.5),
            config_id="cfg_0",
            horizon=0.2,
            source="guessed",
        )


# --------------------------------------------------------------------------
# GEOMETRY_RETENTION: envelope geometry is stored where it is evidence and
# recomputed everywhere else (issue #28, docs/lossiness.md Discarded #9).
# --------------------------------------------------------------------------


def _envelope_rows(path: Path) -> list[sqlite3.Row]:
    """Every envelope row, with `envelope_id` and `config_id` resolved.

    Since issue #55 the readable identifiers live in `node` and the payload
    tables are keyed on an INTEGER surrogate, so a bare `SELECT * FROM envelope`
    no longer names anything a reader can cite. This is the same join
    `store.envelope_row` makes, over the whole table.
    """
    conn = store.connect(path)
    try:
        return list(
            conn.execute(
                # The columns are named rather than `e.*`-ed: `sqlite3.Row`
                # resolves a duplicate column name to the first one, so `e.*`
                # beside an aliased `envelope_hash` would hand back the raw
                # bytes and the alias would be unreachable.
                "SELECT e.envelope_key AS envelope_key, "
                "n.node_id AS envelope_id, "
                "lower(hex(e.envelope_hash)) AS envelope_hash, "
                "e.area AS area, e.geometry_wkb AS geometry_wkb, "
                "e.config_key AS config_key, c.node_id AS config_id, "
                "e.horizon AS horizon, e.source AS source "
                "FROM envelope e JOIN node n ON n.node_key = e.envelope_key "
                "LEFT JOIN node c ON c.node_key = e.config_key "
                "ORDER BY e.envelope_key"
            ).fetchall()
        )
    finally:
        conn.close()


def _entity_row(conn: sqlite3.Connection, entity_id: str) -> sqlite3.Row | None:
    """One entity row by its readable id, through `node` (issue #55)."""
    return conn.execute(
        "SELECT e.*, n.node_id AS entity_id FROM entity e "
        "JOIN node n ON n.node_key = e.entity_key WHERE n.node_id = ?",
        (entity_id,),
    ).fetchone()


def _frames_with_geometry(path: Path) -> set[int]:
    """Frame ids whose envelope row holds a polygon, via the HAS_ENVELOPE edges.

    Through the edges rather than off the `envelope` table's row order, because
    the retention rule is stated in terms of *frames* and the correspondence
    between a frame and an envelope row is exactly what the edges record.
    """
    conn = store.connect(path)
    try:
        rows = conn.execute(
            "SELECT edge.t_start AS t_start, e.geometry_wkb AS geometry_wkb "
            "FROM edge JOIN envelope e ON e.envelope_key = edge.dst_key "
            "WHERE edge.type = 'HAS_ENVELOPE' ORDER BY edge.t_start"
        ).fetchall()
    finally:
        conn.close()
    return {
        int(round(row["t_start"] / DT))
        for row in rows
        if row["geometry_wkb"] is not None
    }


def _frames_with_envelope(path: Path) -> set[int]:
    """Frame ids the artifact retains an `Envelope` row for, via HAS_ENVELOPE.

    Every other frame of the run is one `ENVELOPE_RETENTION` keeps nothing for,
    and `envelope_at` refuses it. An interval spanning several frames retains all
    of them: it asserts the envelope was unchanged throughout, which is a
    statement about each frame it covers.
    """
    conn = store.connect(path)
    try:
        rows = conn.execute(
            "SELECT t_start, t_end FROM edge WHERE type = 'HAS_ENVELOPE'"
        ).fetchall()
    finally:
        conn.close()
    return {
        frame_id
        for row in rows
        for frame_id in range(
            int(round(row["t_start"] / DT)), int(round(row["t_end"] / DT)) + 1
        )
    }


def _creep_frames(n_frames: int, human_at: Callable[[int], tuple[float, float]]):
    """A stream whose envelope changes materially every frame.

    The arm creeps by 1e-6 rad per frame — above the raw stream's own float
    precision and far above the nanometre `envelope_hash` resolves, so every
    frame is a distinct envelope. Without that, a single row would serve every
    frame and nothing below would be measuring per-frame retention at all.
    """
    return [
        _frame(i, human_at(i), q=(1e-6 * i, 0.0), qd=(0.0, 0.0))
        for i in range(n_frames)
    ]


def _sliding_frames(n_frames: int):
    """A creeping arm with the human inside the envelope, sliding out of it.

    The overlap area crosses an `AREA_QUANT_SIGFIGS` boundary every frame, so
    `INTERSECTS` reopens every frame and every frame is therefore one the
    artifact retains an `Envelope` row for — while `GEOMETRY_RETENTION` still
    keeps a polygon on only two of them. It is the one shape in this file where
    a retained row with a *discarded* polygon exists, which is what the
    recomputation refusals need in order to have anything to refuse about.
    """
    return _creep_frames(n_frames, lambda i: (0.95 - 0.03 * i, 0.0))


def test_geometry_is_stored_only_at_transitions_and_the_ends(tmp_path: Path) -> None:
    """The rule, asserted as the exact set of frames it names.

    `reg.graph.GEOMETRY_RETENTION`: the first and last frame of the run, and
    every frame at which an `INTERSECTS` or `CONTACT` relationship begins or
    ceases to hold — `test_an_overlap_that_moves_a_quantum_is_not_a_transition`
    is the other half of that distinction and the reason it is drawn there. The
    human here is inside the envelope for frames 3-6 and clear of it otherwise,
    so the transitions are 3 (start) and 6 (last instant it held), and the ends
    are 0 and 11. Every other frame's envelope row must hold a NULL geometry —
    an assertion on the *set* rather than on a count, because a rule that kept
    the right number of polygons at the wrong frames would answer an incident
    report about a different moment.
    """
    n_frames = 12
    inside, outside = (0.55, 0.0), (2.4, 0.0)
    frames = _creep_frames(n_frames, lambda i: inside if 3 <= i <= 6 else outside)
    csv = _write_stream(tmp_path / "creep.csv", frames)
    out = tmp_path / "creep.sqlite"
    _build(csv, out)

    intersects = _edges(out, edge_type="INTERSECTS", dst_id=HUMAN_ENTITY_ID)
    assert len(intersects) == 1, (
        "precondition failed: the human was expected to intersect the envelope "
        "over exactly one interval, so that the transition frames are 3 and 6."
    )
    assert intersects[0]["t_start"] == pytest.approx(quantize_time(3 * DT))
    assert intersects[0]["t_end"] == pytest.approx(quantize_time(6 * DT))

    assert len(set(_envelope_digests(frames))) == n_frames, (
        "precondition failed: the envelope did not change every frame, so a "
        "single row could serve several of them and the frame a polygon belongs "
        "to would be ambiguous."
    )
    assert _frames_with_geometry(out) == {0, 3, 6, n_frames - 1}

    # ...and since issue #29 those are also the only frames with a row at all:
    # nothing else in this run anchors one, and a polygon is only storable on a
    # row that exists. The two sets coinciding here is the narrow case, not the
    # rule — `test_a_stream_that_changes_every_frame_still_emits_a_row_per_frame`
    # is the run where rows far outnumber polygons.
    assert _frames_with_envelope(out) == {0, 3, 6, n_frames - 1}


def test_an_overlap_that_moves_a_quantum_is_not_a_transition(tmp_path: Path) -> None:
    """The rule counts *relationships* starting and ending, not edge rows.

    An `INTERSECTS` edge also closes and reopens whenever the overlap area moves
    a quantum, and the human here never leaves the envelope while doing exactly
    that. Counting those endpoints is the reading that keeps geometry on half of
    `sustained_overlap` (150 of 301 frames, measured — `reg.graph`); counting the
    relationship's keeps it on the two ends of the run, which is what this
    asserts. Without this test the two readings are indistinguishable on any
    fixture where the overlap happens to hold steady.
    """
    n_frames = 12
    frames = _sliding_frames(n_frames)
    csv = _write_stream(tmp_path / "slide.csv", frames)
    out = tmp_path / "slide.sqlite"
    _build(csv, out)

    rows = _edges(out, edge_type="INTERSECTS", dst_id=HUMAN_ENTITY_ID)
    assert len(rows) > 2, (
        "precondition failed: the overlap area did not move enough quanta to "
        "reopen the INTERSECTS edge, so this test cannot distinguish the two "
        "readings of 'an edge starts or ends'."
    )
    assert rows[0]["t_start"] == pytest.approx(0.0), (
        "precondition failed: the human was expected to be inside the envelope "
        "from the first frame, so that no relationship begins mid-run."
    )
    assert max(r["t_end"] for r in rows) == pytest.approx(
        quantize_time((n_frames - 1) * DT)
    ), "precondition failed: the relationship ceased to hold before the run ended"

    assert _frames_with_geometry(out) == {0, n_frames - 1}


def test_every_retained_envelope_carries_its_scalars(tmp_path: Path) -> None:
    """The half of the rule that is easy to lose: the scalars are not discarded.

    `envelope_hash`, `area`, `horizon` and `source` are what queries read and
    they cost a few dozen bytes; deleting them along with the polygon would make
    the artifact smaller and answerless. Issue #29 changed *which frames* get a
    row — it did not license a row that says less. Asserted over the sliding
    fixture, where rows outnumber polygons ten to one, so the rows being checked
    are mostly the geometry-less ones.
    """
    n_frames = 12
    frames = _sliding_frames(n_frames)
    csv = _write_stream(tmp_path / "scalars.csv", frames)
    out = tmp_path / "scalars.sqlite"
    _build(csv, out)

    rows = _envelope_rows(out)
    assert len(rows) > len(_frames_with_geometry(out)), (
        "precondition failed: every retained row kept its polygon, so this says "
        "nothing about what a row without one still carries."
    )
    # Content-derived ids, so distinct rows are distinct envelopes.
    assert len({row["envelope_hash"] for row in rows}) == len(rows)
    for row in rows:
        assert row["envelope_hash"]
        assert row["area"] > 0.0
        assert row["horizon"] == pytest.approx(_FAST["horizon"])
        assert row["source"] == graph.ENVELOPE_SOURCE
        # ...and every row can still be turned back into a region, which is the
        # only thing that makes the discard a discard rather than a deletion.
        assert row["geometry_wkb"] is not None or row["config_id"] is not None


def test_envelope_at_recomputes_the_stored_polygon_exactly(tmp_path: Path) -> None:
    """**THE GATE.** If recomputation and storage disagree, the discard is not
    lossless and the whole approach fails.

    The frames where geometry *was* stored are the only ones where both answers
    exist, so they are where the two can be compared at all. The stored blob is
    blanked in a copy of the artifact and `envelope_at` is asked the same
    question again; the polygon must come back identical at zero tolerance, not
    merely equal within a tolerance — `GEOM_SIMPLIFY_TOL_M` is already spent on
    the stored boundary and a second helping of it here would hide exactly the
    drift this test exists to catch.
    """
    n_frames = 12
    inside, outside = (0.55, 0.0), (2.4, 0.0)
    frames = _creep_frames(n_frames, lambda i: inside if 3 <= i <= 6 else outside)
    csv = _write_stream(tmp_path / "creep.csv", frames)
    out = tmp_path / "creep.sqlite"
    _build(csv, out)

    stored = {
        str(row["envelope_id"]): store.from_wkb(row["geometry_wkb"])
        for row in _envelope_rows(out)
        if row["geometry_wkb"] is not None
    }
    assert stored, "precondition failed: no geometry was stored at all"

    blanked = tmp_path / "blanked.sqlite"
    blanked.write_bytes(out.read_bytes())
    conn = store.connect(blanked)
    try:
        conn.execute("UPDATE envelope SET geometry_wkb = NULL")
        conn.commit()
        for envelope_id, polygon in stored.items():
            edge = conn.execute(
                "SELECT t_start FROM edge WHERE type = 'HAS_ENVELOPE' "
                "AND dst_key = ?",
                (store.node_key(conn, envelope_id),),
            ).fetchone()
            assert edge is not None
            recomputed = graph.envelope_at(conn, edge["t_start"])
            assert shapely.equals_exact(recomputed, polygon, tolerance=0.0), (
                "recomputation did not reproduce the polygon the artifact stored "
                f"at t={edge['t_start']}; the discard is not lossless."
            )
    finally:
        conn.close()


def test_envelope_at_answers_the_same_way_whether_stored_or_recomputed(
    tmp_path: Path,
) -> None:
    """A caller cannot tell which happened, except by timing.

    Every frame the artifact *retains* is asked for, including the ones whose
    geometry was discarded, and every answer is a non-empty polygon of the right
    area. A version of this that only queried the stored frames would pass
    against an `envelope_at` that could not recompute at all.

    The sliding fixture, because it is the one where retained rows and stored
    polygons come apart: `INTERSECTS` reopens every frame so every frame is
    retained, and `GEOMETRY_RETENTION` keeps a polygon on two of them.
    """
    n_frames = 8
    frames = _sliding_frames(n_frames)
    csv = _write_stream(tmp_path / "slide.csv", frames)
    out = tmp_path / "slide.sqlite"
    _build(csv, out)

    retained = _frames_with_envelope(out)
    conn = store.connect(out)
    try:
        discarded = conn.execute(
            "SELECT count(*) AS n FROM envelope WHERE geometry_wkb IS NULL"
        ).fetchone()["n"]
        assert discarded > 0, "precondition failed: nothing was discarded"
        assert len(retained) > discarded > 0, (
            "precondition failed: the retained frames and the stored polygons "
            "are the same set, so recomputation is never exercised."
        )
        for frame_id in sorted(retained):
            polygon = graph.envelope_at(conn, quantize_time(frame_id * DT))
            row = conn.execute(
                "SELECT e.area AS area FROM envelope e JOIN edge ON "
                "edge.dst_key = e.envelope_key WHERE edge.type = 'HAS_ENVELOPE' "
                "AND edge.t_start = ?",
                (quantize_time(frame_id * DT),),
            ).fetchone()
            assert not polygon.is_empty
            # The area the artifact reports is the quantized area of this exact
            # polygon, so they must agree after quantization.
            assert quantize_area(polygon.area) == pytest.approx(row["area"])
    finally:
        conn.close()


def test_geometry_rows_are_far_fewer_than_frames_in_a_moving_scenario(
    tmp_path: Path,
) -> None:
    """THE MEASUREMENT, on the case the held-still test cannot speak for.

    `test_edge_rows_do_not_grow_with_frame_count` builds from a robot that never
    moves, so it says nothing about the artifact issue #28 measured: a real
    scenario in continuous motion, where every frame is a material envelope
    change. Here the scalar rows do track the frame count — they are meant to —
    and the geometry rows must not.

    A real scenario rather than a synthetic one, at coarse envelope parameters:
    the number of envelope *rows* is a property of the motion, and the motion is
    what `reg.scenarios` defines.

    Since issue #29 both counts are held down, and they are asserted separately
    because they are two different rules failing in two different ways: rows back
    in step with the frame count is emit-on-change not reaching the nodes, and
    polygons back in step with the rows is issue #28 returning.
    """
    csv = tmp_path / "sustained_overlap.csv"
    simulate("sustained_overlap", SIM_SEED, csv)
    out = tmp_path / "sustained_overlap.sqlite"
    world = SCENARIOS["sustained_overlap"].world
    result = build(
        csv,
        out,
        world.limits,
        identity=TEST_IDENTITY,
        human_radius=world.human_radius,
        **_FAST,
    )

    rows = _envelope_rows(out)
    with_geometry = [row for row in rows if row["geometry_wkb"] is not None]

    # A fraction of the frame count, not a golden count: the exact numbers are
    # properties of this scenario's transitions and would go red on any harmless
    # change to it. Halving is a low bar for the rows and deliberately so — the
    # invariant that node counts do not *scale* with the frame count is
    # `test_node_rows_are_sub_linear_for_every_fixture`, and this is the
    # measurement on one real fixture beside it.
    assert len(rows) * 2 < result.frames, (
        f"{len(rows)} envelope rows for {result.frames} frames; emit-on-change "
        "is not reaching the nodes (issue #29)."
    )
    assert len(with_geometry) * 10 < result.frames, (
        f"{len(with_geometry)} of {result.frames} frames kept their envelope "
        "geometry; the per-frame storage issue #28 measured is back."
    )
    # Every retained envelope can still be answered, stored or not.
    conn = store.connect(out)
    try:
        for row in _edges(out, edge_type="HAS_ENVELOPE"):
            assert not graph.envelope_at(conn, row["t_start"]).is_empty
    finally:
        conn.close()


@pytest.mark.parametrize("n_frames", [12, 30])
def test_a_stream_that_changes_every_frame_still_emits_a_row_per_frame(
    tmp_path: Path, n_frames: int
) -> None:
    """**THE NEGATIVE TEST FOR ISSUE #29.** Fewer rows must mean less happened.

    Without this, "the artifact shrank" and "the artifact stopped recording
    transitions" are indistinguishable — a rule that emitted a fixed number of
    rows however much moved would pass every sub-linearity assertion in this file
    and would be a cap rather than a compression, silently dropping the
    transitions an incident report is made of.

    So the condition the rule guards against is constructed deliberately. The
    human walks steadily at 3 cm per frame, which is three `DISTANCE_TOL_M`
    quanta, so the quantized separation is different at every frame and no
    `SEPARATION` interval may extend across two of them. The arm creeps at the
    same time, so every frame's configuration is distinct too. The row counts
    must track the frame count here, exactly.
    """
    frames = [
        _frame(i, (2.4 - 0.03 * i, 0.0), q=(1e-6 * i, 0.0), qd=(0.0, 0.0))
        for i in range(n_frames)
    ]
    csv = _write_stream(tmp_path / f"walk_{n_frames}.csv", frames)
    result = _build(csv, tmp_path / f"walk_{n_frames}.sqlite")

    human = _edges(tmp_path / f"walk_{n_frames}.sqlite", edge_type="SEPARATION",
                   dst_id=HUMAN_ENTITY_ID)
    assert len(human) == n_frames, (
        f"the human moved 3 cm per frame — three quanta — over {n_frames} frames "
        f"and the artifact holds {len(human)} separation intervals. Transitions "
        "are being folded away, which is deletion and not compression."
    )
    # Each of those intervals is a single instant, and every one names its own
    # configuration: the RobotConfig rows track the frames too.
    assert all(row["t_start"] == row["t_end"] for row in human)
    assert result.nodes["RobotConfig"] == n_frames


@pytest.mark.parametrize("n_frames", [8, 12])
def test_envelope_rows_track_the_frames_when_the_overlap_changes_every_frame(
    tmp_path: Path, n_frames: int
) -> None:
    """The same negative for the `Envelope` row, which is what issue #29 moved.

    `test_a_stream_that_changes_every_frame_still_emits_a_row_per_frame` shows
    the separation edges and their configurations still costing a row a frame; it
    does not show it for the envelope, because a human walking *outside* the
    envelope never opens an `INTERSECTS` edge. Here the human is inside it and
    sliding out, so the overlap area crosses a quantum boundary every frame and
    every frame is a frame the artifact must retain.
    """
    frames = _sliding_frames(n_frames)
    csv = _write_stream(tmp_path / f"slide_{n_frames}.csv", frames)
    out = tmp_path / f"slide_{n_frames}.sqlite"
    result = _build(csv, out)

    assert result.edges["INTERSECTS"] == n_frames, (
        "precondition failed: the overlap did not move a quantum every frame, so "
        "this fixture is not the every-frame-changes case."
    )
    assert result.nodes["Envelope"] == n_frames
    assert _frames_with_envelope(out) == set(range(n_frames))


def test_the_separation_timeline_answers_every_frame_within_tolerance(
    tmp_path: Path,
) -> None:
    """**THE GATE ON ISSUE #29.** The supported query still answers, frame by frame.

    Issue #29's acceptance criterion: whatever the graph could answer before must
    still answer identically after, because that is the whole difference between
    compression and deletion. Query 1 of docs/lossiness.md's supported set, under
    that document's own agreement predicate — "per sampled frame,
    |d_graph - d_csv| <= DISTANCE_TOL_M" — over a real scenario at every frame of
    it, including all the frames the artifact now keeps no node for.

    Two things are asserted and the first is the one that catches a hole: **every
    frame must be covered** by some `SEPARATION` interval. A dropped interval
    makes a frame unanswerable, and an unanswerable frame is exactly what
    dropping rows too eagerly produces — it would not show up as a wrong distance
    anywhere.
    """
    scn = SCENARIOS["sustained_overlap"]
    csv = tmp_path / "sustained_overlap.csv"
    simulate(scn.name, SIM_SEED, csv)
    out = tmp_path / "sustained_overlap.sqlite"
    build(
        csv,
        out,
        scn.world.limits,
        identity=TEST_IDENTITY,
        human_radius=scn.world.human_radius,
        **_FAST,
    )

    intervals = _edges(out, edge_type="SEPARATION", dst_id=HUMAN_ENTITY_ID)
    assert intervals, "precondition failed: no separation intervals for the human"

    for frame in read_frames(csv):
        t = quantize_time(frame.t)
        covering = [r for r in intervals if r["t_start"] <= t <= r["t_end"]]
        assert covering, (
            f"no SEPARATION interval covers t={t}. The graph cannot answer query "
            "1 at a frame of the run it was built from; a row that should have "
            "been kept was dropped."
        )
        body = unary_union(link_polygons(frame.proprio(), scn.world.limits))
        truth = float(body.distance(scn.world.human_polygon(frame.human_pos)))
        assert abs(float(covering[0]["min_distance"]) - truth) <= DISTANCE_TOL_M, (
            f"at t={t} the graph says {covering[0]['min_distance']} m and the raw "
            f"stream says {truth} m, outside the {DISTANCE_TOL_M} m budget "
            "docs/lossiness.md allocates for query 1."
        )


# --- the time base, and the rate range the test above holds in (issue #77) --
#
# The gate above builds at 50 Hz, which is what this simulator runs at and is
# inside the range docs/lossiness.md's per-frame predicates hold in. A real
# manipulator runs at 1 kHz, and there the same gate fails — not because the
# graph drops anything, but because every interval endpoint is quantized to
# `TIME_TOL_S` and above `1/TIME_TOL_S` several frames share one address. These
# three tests are the positive at the documented bound, the negative above it,
# and the evidence that the miss is quantization rather than sampling.
#
# Deliberately *not* a test that the build refuses a fast stream: it does not,
# and it must not — see `reg.graph.TIME_BASE_DOMAIN`. What is asserted is that
# the artifact states which side of the range it is on, and that the statement
# can come out `no`.


#: 100 Hz — `TIME_BASE_MAX_RATE_HZ`, the documented bound itself and therefore
#: the interesting side of it: a test at 50 Hz would pass with a bound anywhere
#: from 51 Hz upward.
_RESOLVED_DT = 1.0 / TIME_BASE_MAX_RATE_HZ

#: 200 Hz. Twice the bound, which is the cheapest rate that is unambiguously
#: outside it; the finding is not rate-proportional (docs/lossiness.md, "The rate
#: range these hold in") so 1 kHz would cost five times the build and show the
#: same thing.
_COLLAPSED_DT = 1.0 / (2.0 * TIME_BASE_MAX_RATE_HZ)


def _rate_build(tmp_path_factory, dt: float) -> tuple[Path, Path, object]:
    """`near_miss` resampled at `dt`, built. Same waypoints, same human walk.

    `near_miss` because the effect is bounded by how far things move inside one
    `TIME_TOL_S` window: on a fixture where the separation barely changes there
    is nothing for a shared address to lose, and a test built on one would pass
    for a reason that has nothing to do with the time base.
    """
    scn = replace(SCENARIOS["near_miss"], dt=dt)
    tmp = tmp_path_factory.mktemp(f"rate-{1.0 / dt:g}hz")
    csv = _scenario_stream(scn, dt, tmp / "near_miss.csv")
    out = tmp / "near_miss.sqlite"
    build(
        csv,
        out,
        scn.world.limits,
        human_radius=scn.world.human_radius,
        # Required since issue #83; this helper predates it. The same
        # TEST_IDENTITY every other build in this file uses, so runs stay
        # comparable rather than differing in a field nobody set on purpose.
        identity=TEST_IDENTITY,
        **_FAST,
    )
    return csv, out, scn


@pytest.fixture(scope="module")
def resolved_rate(tmp_path_factory):
    """The run at `TIME_BASE_MAX_RATE_HZ`. Module-scoped: it is a full scenario."""
    return _rate_build(tmp_path_factory, _RESOLVED_DT)


@pytest.fixture(scope="module")
def collapsed_rate(tmp_path_factory):
    """The same run at twice `TIME_BASE_MAX_RATE_HZ`."""
    return _rate_build(tmp_path_factory, _COLLAPSED_DT)


def _timeline_error(csv: Path, out: Path, scn) -> tuple[float, float]:
    """`(worst per-frame Δ, worst Δ allowing ±TIME_TOL_S)` for query 1.

    The first is docs/lossiness.md's per-frame predicate, read off the artifact
    exactly as `test_the_separation_timeline_answers_every_frame_within_tolerance`
    reads it. The second is the same comparison with the *time* the answer is
    attached to allowed to be wrong by one quantum, and the gap between them is
    what separates "the artifact holds the wrong value" from "the artifact holds
    the right value and cannot say which frame it belongs to".
    """
    intervals = sorted(
        (float(r["t_start"]), float(r["t_end"]), float(r["min_distance"]))
        for r in _edges(out, edge_type="SEPARATION", dst_id=HUMAN_ENTITY_ID)
    )
    assert intervals, "precondition failed: no separation intervals for the human"

    truth: list[tuple[float, float]] = []
    for frame in read_frames(csv):
        body = unary_union(link_polygons(frame.proprio(), scn.world.limits))
        truth.append(
            (
                float(frame.t),
                float(body.distance(scn.world.human_polygon(frame.human_pos))),
            )
        )

    worst = 0.0
    worst_with_slack = 0.0
    for t_raw, d_raw in truth:
        t = quantize_time(t_raw)
        covering = [iv for iv in intervals if iv[0] <= t <= iv[1]]
        assert covering, f"no SEPARATION interval covers t={t}"
        answered = covering[0][2]
        worst = max(worst, abs(answered - d_raw))
        near = [
            abs(answered - d)
            for t_other, d in truth
            if abs(t_other - t) <= TIME_TOL_S + 1e-12
        ]
        worst_with_slack = max(worst_with_slack, min(near))
    return worst, worst_with_slack


def test_at_the_documented_rate_the_time_base_addresses_every_frame(
    resolved_rate,
) -> None:
    """The positive, at the bound itself: 100 Hz still answers frame by frame.

    Two claims and they are not the same one. The artifact *says* every frame has
    its own address, and query 1 *is* within `DISTANCE_TOL_M` at every frame. A
    build that reported `yes` and missed the budget would be lying about its own
    domain, which is the failure this pair exists to catch.
    """
    csv, out, scn = resolved_rate
    meta = _meta(out)

    assert meta[graph.META_TIME_BASE_RESOLVES] == graph.TIME_BASE_RESOLVED
    assert int(meta[graph.META_TIME_BASE_INSTANTS]) == int(meta["frame_count"])
    assert meta[graph.META_TIME_BASE_DOMAIN] == graph.TIME_BASE_DOMAIN

    worst, _ = _timeline_error(csv, out, scn)
    assert worst <= DISTANCE_TOL_M, (
        f"at {TIME_BASE_MAX_RATE_HZ:g} Hz the worst per-frame separation error is "
        f"{worst} m against a {DISTANCE_TOL_M} m budget. This is the rate "
        "docs/lossiness.md says its per-frame predicates hold to, so either the "
        "graph regressed or the documented range is wrong — not a tolerance to "
        "widen either way."
    )


def test_above_the_documented_rate_the_artifact_says_its_time_base_collapsed(
    collapsed_rate,
) -> None:
    """**THE NEGATIVE.** The check is shown able to say no, on both halves.

    At twice `TIME_BASE_MAX_RATE_HZ` the artifact must report that it cannot
    address every frame, *and* query 1 must actually miss its own budget. Only
    asserting the flag would leave a build that always says `no` passing; only
    asserting the error would leave a build that misses the budget silently
    passing. The two together are what makes the flag mean something.
    """
    csv, out, scn = collapsed_rate
    meta = _meta(out)
    frames = int(meta["frame_count"])
    instants = int(meta[graph.META_TIME_BASE_INSTANTS])

    assert meta[graph.META_TIME_BASE_RESOLVES] == graph.TIME_BASE_COLLAPSED
    assert instants < frames
    # Two frames per addressable instant, because the rate is exactly twice the
    # bound. Derived from the rates rather than typed, so the assertion says why.
    assert instants == pytest.approx(frames / 2.0, abs=1.0)

    worst, _ = _timeline_error(csv, out, scn)
    assert worst > DISTANCE_TOL_M, (
        f"at {2.0 * TIME_BASE_MAX_RATE_HZ:g} Hz the worst per-frame separation "
        f"error is {worst} m, inside the {DISTANCE_TOL_M} m budget. Either the "
        "time base stopped collapsing frames — in which case the range in "
        "docs/lossiness.md is now wrong in the artifact's favour and should be "
        "re-measured — or this check has stopped being able to fail."
    )


def test_the_time_base_miss_is_quantization_and_not_sampling(
    resolved_rate, collapsed_rate
) -> None:
    """Which of the two diagnoses it is, as an assertion rather than as prose.

    They have different fixes — a finer time base against retaining more frames —
    so docs/limitations.md §5 is not allowed to guess. Two measurements decide it:

    * **Nothing was sampled away.** Doubling the rate stores the same number of
      `SEPARATION` intervals. The builder sees every frame at both rates and emits
      an interval per quantized change at both; there is nothing more it *could*
      retain, because the time base has no more addresses to hang it on. A
      sampling limit would show the faster run retaining more and still missing.
    * **Every value it holds is a true one.** Allow the *time* an answer is
      attached to to be wrong by one `TIME_TOL_S`, and the error falls back inside
      `DISTANCE_TOL_M` at the collapsed rate. The value is right; the frame it
      belongs to is what the artifact cannot say.
    """
    fast_csv, fast_out, fast_scn = collapsed_rate
    _, slow_out, _ = resolved_rate

    fast_rows = _edges(fast_out, edge_type="SEPARATION", dst_id=HUMAN_ENTITY_ID)
    slow_rows = _edges(slow_out, edge_type="SEPARATION", dst_id=HUMAN_ENTITY_ID)
    assert len(fast_rows) == len(slow_rows), (
        f"{len(fast_rows)} SEPARATION intervals at "
        f"{2.0 * TIME_BASE_MAX_RATE_HZ:g} Hz against {len(slow_rows)} at "
        f"{TIME_BASE_MAX_RATE_HZ:g} Hz. If the faster run retains more, the miss "
        "is not purely a limit of the time base and docs/limitations.md §5's "
        "diagnosis needs redoing."
    )

    worst, worst_with_slack = _timeline_error(fast_csv, fast_out, fast_scn)
    assert worst > DISTANCE_TOL_M >= worst_with_slack, (
        f"per-frame error {worst} m, error allowing ±TIME_TOL_S "
        f"{worst_with_slack} m, budget {DISTANCE_TOL_M} m. The diagnosis in "
        "docs/limitations.md §5 is that the values are right and their instants "
        "are ambiguous; if the slack column also leaves the budget, some value in "
        "the artifact is not a separation this run ever had, and that is a "
        "different defect."
    )


# --- the negatives: what envelope_at refuses rather than approximates ------


def test_envelope_at_refuses_an_instant_with_no_envelope(tmp_path: Path) -> None:
    """THE NEGATIVE TEST for the reader. An instant the artifact says nothing
    about must not be answered with the neighbouring frame's polygon: that is a
    region the robot could reach, reported for a time it could not."""
    n_frames = 8
    frames = _creep_frames(n_frames, lambda i: (2.4, 0.0))
    csv = _write_stream(tmp_path / "creep.csv", frames)
    out = tmp_path / "creep.sqlite"
    _build(csv, out)

    conn = store.connect(out)
    try:
        # Well past the end of the run...
        with pytest.raises(graph.GraphQueryError, match="no envelope"):
            graph.envelope_at(conn, 99.0)
        # ...and between two frames: the period is 20 ms and the graph's own
        # quantum is 10 ms, so t = 0.01 s falls in the gap between frame 0 and
        # frame 1 and belongs to neither.
        with pytest.raises(graph.GraphQueryError, match="no envelope"):
            graph.envelope_at(conn, 0.01)
    finally:
        conn.close()


def test_envelope_at_refuses_a_frame_the_artifact_does_not_retain(
    tmp_path: Path,
) -> None:
    """THE NEGATIVE TEST FOR ISSUE #29'S READER SIDE.

    A frame with no node is a frame whose envelope the artifact does not hold,
    and the failure mode of the whole change is answering it anyway with the
    neighbouring interval's polygon — a region the robot could reach, reported
    for an instant at which it could not, and indistinguishable from a recorded
    one. The arm creeps every frame, so the envelope at frame 5 is genuinely
    unlike the envelope at frame 0, and the artifact retains only the two ends.
    """
    n_frames = 12
    frames = _creep_frames(n_frames, lambda i: (2.4, 0.0))
    assert len(set(_envelope_digests(frames))) == n_frames, (
        "precondition failed: the envelope did not change every frame, so an "
        "unretained frame's envelope would be the retained one's and this test "
        "could not tell a refusal from a correct answer."
    )
    csv = _write_stream(tmp_path / "creep.csv", frames)
    out = tmp_path / "creep.sqlite"
    _build(csv, out)

    retained = _frames_with_envelope(out)
    assert retained == {0, n_frames - 1}, (
        "precondition failed: this run was expected to retain only its two ends"
    )

    conn = store.connect(out)
    try:
        for frame_id in range(1, n_frames - 1):
            with pytest.raises(graph.GraphQueryError, match="no envelope"):
                graph.envelope_at(conn, quantize_time(frame_id * DT))
        # ...and the frames it does retain still answer, so the refusal above is
        # the rule biting rather than `envelope_at` being broken.
        for frame_id in sorted(retained):
            assert not graph.envelope_at(
                conn, quantize_time(frame_id * DT)
            ).is_empty
    finally:
        conn.close()


def test_the_artifact_states_the_rule_its_absences_follow(tmp_path: Path) -> None:
    """A reader holding only the file must be able to read the gaps.

    The pattern of missing frames does not distinguish "not retained, on a stated
    rule" from "this build stopped writing", so the rule travels in `meta` — the
    same discipline `GEOMETRY_RETENTION` follows for a NULL polygon, one level
    out. A key that is absent, or present and empty, is the failure.
    """
    csv = _held_stream(tmp_path / "held.csv", 6)
    out = tmp_path / "held.sqlite"
    _build(csv, out)

    conn = store.connect(out)
    try:
        meta = store.all_meta(conn)
    finally:
        conn.close()

    assert meta[graph.META_ENVELOPE_RETENTION] == graph.ENVELOPE_RETENTION
    assert meta[graph.META_GEOMETRY_RETENTION] == graph.GEOMETRY_RETENTION
    # It has to name what a reader would otherwise have to guess at.
    assert "envelope_at" in meta[graph.META_ENVELOPE_RETENTION]


def test_there_is_no_per_frame_node_kind() -> None:
    """The vocabulary itself, independent of any run (issue #29).

    `Timestep` is gone: every edge already carries `t_start`/`t_end`, so a node
    per instant was a denser second representation of time, and docs/plan.md
    Phase 7's query set needs no per-frame anchor. Asserted against the schema
    rather than against a build, so re-adding it is a decision someone has to
    make here and not something that creeps back through a call site.
    """
    assert "Timestep" not in store.NODE_TABLES
    assert not hasattr(store, "insert_timestep")
    assert store.EDGE_SPECS["HAS_ENVELOPE"].src_kind == "RobotConfig"
    # Every endpoint kind in the vocabulary must be a table that exists. An
    # endpoint may be a set of kinds — `FOLLOWS` joins two declarations in one
    # chain and two verdicts in the other (issue #45) — and then every kind in
    # the set has to be one, because `open_edge` will store whichever the caller
    # states and an edge stored against a table that is not there is a dangling
    # reference every join reads as "the relationship never held".
    for edge_type, spec in store.EDGE_SPECS.items():
        for kind in (spec.src_kind, spec.dst_kind):
            for one in {kind} if isinstance(kind, str) else kind:
                assert one in store.NODE_TABLES, edge_type


def test_envelope_at_refuses_when_a_parameter_it_needs_is_missing(
    tmp_path: Path,
) -> None:
    """THE NEGATIVE TEST for the recomputation contract, and it is the
    never-invent-a-default rule in its most dangerous form.

    A missing `envelope_n_samples` does not stop `compute_envelope` from
    returning a polygon; it stops it from returning *this* polygon. A plausible
    value substituted here would produce a region indistinguishable from the
    recorded one at every point downstream.
    """
    n_frames = 8
    frames = _sliding_frames(n_frames)
    csv = _write_stream(tmp_path / "slide.csv", frames)
    out = tmp_path / "slide.sqlite"
    _build(csv, out)

    conn = store.connect(out)
    try:
        discarded = conn.execute(
            "SELECT t_start FROM edge WHERE type = 'HAS_ENVELOPE' AND dst_key "
            "IN (SELECT envelope_key FROM envelope WHERE geometry_wkb IS NULL) "
            "ORDER BY t_start"
        ).fetchone()
        assert discarded is not None, "precondition failed: nothing was discarded"
        conn.execute("DELETE FROM meta WHERE key = ?", (graph.META_N_SAMPLES,))
        conn.commit()
        with pytest.raises(graph.GraphQueryError, match=graph.META_N_SAMPLES):
            graph.envelope_at(conn, discarded["t_start"])
    finally:
        conn.close()


def test_envelope_at_refuses_when_the_config_it_names_is_gone(tmp_path: Path) -> None:
    """The other half of the same refusal: the inputs are recorded, but the
    configuration they apply to is not."""
    n_frames = 8
    frames = _sliding_frames(n_frames)
    csv = _write_stream(tmp_path / "slide.csv", frames)
    out = tmp_path / "slide.sqlite"
    _build(csv, out)

    conn = store.connect(out)
    try:
        row = conn.execute(
            "SELECT edge.t_start AS t_start, e.config_key AS config_key "
            "FROM envelope e JOIN edge ON edge.dst_key = e.envelope_key "
            "WHERE e.geometry_wkb IS NULL AND edge.type = 'HAS_ENVELOPE' "
            "ORDER BY edge.t_start"
        ).fetchone()
        assert row is not None, "precondition failed: nothing was discarded"
        conn.execute(
            "DELETE FROM robot_config WHERE config_key = ?", (row["config_key"],)
        )
        conn.commit()
        with pytest.raises(graph.GraphQueryError, match="not in this artifact"):
            graph.envelope_at(conn, row["t_start"])
    finally:
        conn.close()


def test_an_envelope_with_neither_geometry_nor_config_is_refused(seeded) -> None:
    """A row that holds no region and names nothing to recompute one from
    answers every query with "there was no envelope", which is what a frame
    without one looks like. Refused in Python and by the schema."""
    with pytest.raises(store.StoreError, match="neither geometry nor"):
        store.insert_envelope(
            seeded,
            "env_empty",
            envelope_hash=_HASH_C,
            area=0.25,
            geometry=None,
            config_id=None,
            horizon=0.2,
            source="computed",
        )
    with pytest.raises(sqlite3.IntegrityError):
        seeded.execute(
            "INSERT INTO envelope (envelope_key, envelope_hash, area, horizon, "
            "source) VALUES (99, X'" + _HASH_C.upper() + "', 0.25, 0.2, "
            "'computed')"
        )


def test_attaching_a_different_geometry_to_one_envelope_id_is_refused(
    seeded,
) -> None:
    """The id is content-derived from the envelope hash, so two distinct
    polygons under it is a collision, not an update — and an update would leave
    the artifact holding whichever was written last."""
    store.attach_envelope_geometry(seeded, "env_0", Point(0.0, 0.0).buffer(0.5))
    with pytest.raises(store.StoreError, match="different geometry"):
        store.attach_envelope_geometry(seeded, "env_0", Point(1.0, 0.0).buffer(0.5))
    with pytest.raises(store.StoreError, match="no envelope"):
        store.attach_envelope_geometry(seeded, "env_nope", Point(0.0, 0.0).buffer(0.5))


def test_geometry_attached_later_fills_a_row_written_without_it(seeded) -> None:
    """The write order the retention rule forces: a row exists before the run
    knows whether its frame is a transition."""
    store.insert_envelope(
        seeded,
        "env_late",
        envelope_hash=_HASH_D,
        area=0.25,
        geometry=None,
        config_id="cfg_0",
        horizon=0.2,
        source="computed",
    )
    assert store.envelope_row(seeded, "env_late")["geometry_wkb"] is None
    store.attach_envelope_geometry(seeded, "env_late", Point(0.0, 0.0).buffer(0.5))
    assert store.envelope_row(seeded, "env_late")["geometry_wkb"] is not None
    assert store.envelope_row(seeded, "env_missing") is None


def test_conflicting_provenance_is_refused(seeded) -> None:
    """One artifact describes one run; the last writer must not win silently."""
    store.put_meta(seeded, "seed", "0")
    store.put_meta(seeded, "seed", "0")
    with pytest.raises(store.StoreError, match="already"):
        store.put_meta(seeded, "seed", "1")


def test_connect_refuses_a_file_that_is_not_an_evidence_graph(tmp_path: Path) -> None:
    """Reading a foreign file with this schema's column meanings returns
    numbers, and they are the wrong numbers."""
    stray = tmp_path / "stray.sqlite"
    stray.write_bytes(b"not a database")
    with pytest.raises(store.StoreError):
        store.connect(stray)
    with pytest.raises(store.StoreError, match="no such file"):
        store.connect(tmp_path / "absent.sqlite")


def test_connect_refuses_an_unknown_schema_version(tmp_path: Path) -> None:
    path = tmp_path / "future.sqlite"
    conn = store.create(path, record_tables=False)
    conn.execute(
        "UPDATE meta SET value = ? WHERE key = ?",
        (str(store.SCHEMA_VERSION + 1), store.META_SCHEMA_VERSION),
    )
    conn.commit()
    conn.close()
    with pytest.raises(store.StoreError, match="schema version"):
        store.connect(path)


def test_read_edges_refuses_an_unknown_type_rather_than_returning_nothing(
    seeded,
) -> None:
    """An empty list is a could-not-evaluate and must not read as 'no such
    relationships occurred'.

    `FOLLOWS` was the example until issue #45 made it a real edge type;
    `CONTAINS` is still out of the vocabulary and takes its place.
    """
    with pytest.raises(store.StoreError, match="not an edge type"):
        store.read_edges(seeded, edge_type="CONTAINS")


# --------------------------------------------------------------------------
# The CLI — the issue's deliverable
# --------------------------------------------------------------------------


def test_cli_builds_end_to_end(tmp_path: Path, capsys) -> None:
    csv = _held_stream(tmp_path / "held.csv", 8)
    out = tmp_path / "held.sqlite"
    code = graph.main(
        [
            "build",
            str(csv),
            "--out",
            str(out),
            "--horizon",
            "0.1",
            "--n-samples",
            "4",
            "--substep-dt",
            "0.05",
            *IDENTITY_ARGV,
        ]
    )
    assert code == 0
    assert out.exists()
    captured = capsys.readouterr()
    assert "frames=8" in captured.out
    # 50 Hz is inside the range docs/lossiness.md's per-frame predicates hold in,
    # so there is nothing to warn about — and the note below must not be the kind
    # that prints on every build and is therefore read by nobody.
    assert captured.err == ""
    assert _edges(out)


def test_cli_says_so_when_the_stream_is_faster_than_the_time_quantum(
    tmp_path: Path, capsys
) -> None:
    """The `no` case of `TIME_BASE_DOMAIN`, said where a person will see it.

    Exit 0 and a complete artifact: a stream above `TIME_BASE_MAX_RATE_HZ` is
    built, not refused (`reg.graph.TIME_BASE_DOMAIN`). What it is not is silent —
    a reader who builds a 1 kHz run and then quotes per-frame numbers off it needs
    to know they are good to the quantum and not to the frame, and
    `meta[time_base_domain]` is not somewhere anybody looks unprompted.
    """
    dt = _COLLAPSED_DT
    frames = [replace(_frame(i, (2.0, 0.0)), t=i * dt) for i in range(8)]
    csv = _write_stream(tmp_path / "fast.csv", frames)
    out = tmp_path / "fast.sqlite"
    code = graph.main(
        ["build", str(csv), "--out", str(out), "--horizon", "0.1",
         "--n-samples", "4", "--substep-dt", "0.05", *IDENTITY_ARGV]
    )
    assert code == 0
    assert out.exists()
    captured = capsys.readouterr()
    assert "frames=8" in captured.out
    assert graph.META_TIME_BASE_DOMAIN in captured.err
    assert f"{TIME_BASE_MAX_RATE_HZ:g} Hz" in captured.err
    assert _meta(out)[graph.META_TIME_BASE_RESOLVES] == graph.TIME_BASE_COLLAPSED


def test_cli_refuses_a_stream_that_does_not_say_what_produced_it(
    tmp_path: Path, capsys
) -> None:
    """The limits and the human radius are not in the stream's columns. Without
    the provenance block there is nothing to build a graph from without
    inventing both, and silence is not a reading of 'the defaults were used'."""
    csv = _write_stream(
        tmp_path / "bare.csv", [_frame(i, (2.0, 0.0)) for i in range(4)], scenario=None
    )
    code = graph.main(
        ["build", str(csv), "--out", str(tmp_path / "bare.sqlite"), *IDENTITY_ARGV]
    )
    assert code == graph.EXIT_USAGE
    assert "provenance" in capsys.readouterr().err


def test_cli_refuses_an_unknown_scenario(tmp_path: Path, capsys) -> None:
    csv = _write_stream(
        tmp_path / "odd.csv",
        [_frame(i, (2.0, 0.0)) for i in range(4)],
        scenario="not_a_scenario",
    )
    code = graph.main(
        ["build", str(csv), "--out", str(tmp_path / "odd.sqlite"), *IDENTITY_ARGV]
    )
    assert code == graph.EXIT_USAGE
    assert "does not know" in capsys.readouterr().err


def test_cli_requires_an_output_path(tmp_path: Path) -> None:
    csv = _held_stream(tmp_path / "held.csv", 4)
    with pytest.raises(SystemExit) as excinfo:
        graph.main(["build", str(csv)])
    assert excinfo.value.code == graph.EXIT_USAGE


# --------------------------------------------------------------------------
# The occurrence layer (issue #35). DSSAD-aligned events beside the edges.
#
# The claim it exists to support is not "the artifact got smaller" — issue #30
# settled that the fine layer is larger than the stream and no layer added here
# changes it. It is that a *coarser* record, in the shape UN R157 actually
# mandates, still answers some of the questions. So the tests here are about
# three things and nothing else: what counts as material, what a row must carry,
# and what the layer refuses to record.
# --------------------------------------------------------------------------


def _occurrences(path: Path, **filters) -> list[sqlite3.Row]:
    conn = store.connect(path)
    try:
        return store.read_occurrences(conn, **filters)
    finally:
        conn.close()


@pytest.mark.parametrize("n_frames", [12, 40, 200])
def test_occurrence_rows_do_not_grow_with_frame_count(
    tmp_path: Path, n_frames: int
) -> None:
    """THE INVARIANT THIS LAYER EXISTS FOR, and it is the strong form.

    The stream is the one that *defeats* the edge layer: a human walking steadily
    crosses a `DISTANCE_TOL_M` bucket at every frame, so `SEPARATION` emits a row
    per frame by design (`test_a_stream_that_changes_every_frame_still_emits_a_
    row_per_frame` protects exactly that). The occurrence layer must not follow
    it, because a bucket crossing is a quantization boundary and not an event.

    Asserted as equality across a sixteenfold range rather than as a bound: a
    rule that still scaled, only more slowly, would pass "fewer than the frames".
    The precondition — that the edge layer really is emitting per frame here — is
    asserted too, or this says nothing.
    """
    # The human shuffles back and forth 3 cm at a time — three `DISTANCE_TOL_M`
    # quanta, so the quantized separation differs at every frame — while staying
    # well outside the envelope, and the arm creeps so every configuration is
    # distinct too. Bounded rather than walking in a straight line, so that the
    # *same* situation holds at 12 frames and at 200: a human who kept walking
    # would eventually reach the arm and the run would contain different events
    # at different lengths, which is not what this is measuring.
    frames = [
        _frame(i, (2.4 - 0.03 * (i % 5), 0.0), q=(1e-6 * i, 0.0), qd=(0.0, 0.0))
        for i in range(n_frames)
    ]
    csv = _write_stream(tmp_path / f"shuffle_{n_frames}.csv", frames)
    out = tmp_path / f"shuffle_{n_frames}.sqlite"
    result = _build(csv, out)

    human = _edges(out, edge_type="SEPARATION", dst_id=HUMAN_ENTITY_ID)
    assert len(human) == n_frames, (
        "precondition failed: the edge layer is not emitting per frame on this "
        "stream, so there is no per-frame growth for the occurrence layer to "
        "not have."
    )
    assert result.nodes["RobotConfig"] == n_frames

    # Four, at 12 frames and at 200: the two ends of the run and one closest
    # approach per entity. Nothing in this run is an *event* — a metric stepping
    # a quantum is what the edge layer above is for.
    kinds = [str(row["type"]) for row in _occurrences(out)]
    assert sorted(kinds) == [
        "closest_approach",
        "closest_approach",
        "run_began",
        "run_ended",
    ]


def test_an_overlap_that_moves_a_quantum_is_not_an_occurrence(
    tmp_path: Path,
) -> None:
    """The negative of the rule above, on the relationship it is easiest to lose.

    `_sliding_frames` reopens the `INTERSECTS` edge on every frame because the
    overlap area crosses an `AREA_QUANT_SIGFIGS` boundary every frame. Those are
    metric steps, and the human enters the envelope exactly once. An
    implementation that emitted `envelope_entered` per edge row rather than per
    *relationship* would put one per frame here, which is the per-frame cost this
    layer exists to be measured against.
    """
    n_frames = 30
    csv = _write_stream(tmp_path / "slide.csv", _sliding_frames(n_frames))
    out = tmp_path / "slide.sqlite"
    result = _build(csv, out)

    assert result.edges["INTERSECTS"] > 1, (
        "precondition failed: the INTERSECTS edge did not reopen, so there are "
        "no metric steps here to wrongly count as entries."
    )
    entered = _occurrences(out, occurrence_type="envelope_entered")
    assert len(entered) == 1, [dict(r) for r in entered]


def test_the_contact_occurrences_name_the_same_instants_as_the_edge(
    tmp_path: Path,
) -> None:
    """The two layers must agree about when the same event happened.

    Same instant, at each layer's own resolution: the occurrence timestamp is the
    edge's `t_start` (or `t_end`) rounded to the artifact's occurrence
    resolution. A layer that timestamped the *next* frame instead would be off by
    one frame period, which no assertion about coarse timing would ever catch.
    """
    resolution = 0.05
    # The human walks onto the arm, stays a while, and walks off it again.
    frames = [
        _frame(i, (0.5, 0.0) if 4 <= i <= 9 else (2.4, 0.0)) for i in range(16)
    ]
    csv = _write_stream(tmp_path / "touch.csv", frames)
    out = tmp_path / "touch.sqlite"
    _build(csv, out, occurrence_resolution_s=resolution)

    contact = _edges(out, edge_type="CONTACT", dst_id=HUMAN_ENTITY_ID)
    assert len(contact) == 1, "precondition failed: no single contact interval"

    began = _occurrences(out, occurrence_type="contact_began")
    ended = _occurrences(out, occurrence_type="contact_ended")
    assert len(began) == 1 and len(ended) == 1
    assert began[0]["t"] == pytest.approx(
        graph.quantize_occurrence_time(contact[0]["t_start"], resolution)
    )
    assert ended[0]["t"] == pytest.approx(
        graph.quantize_occurrence_time(contact[0]["t_end"], resolution)
    )
    assert began[0]["entity_id"] == HUMAN_ENTITY_ID


def test_a_relationship_still_holding_at_the_end_gets_no_ended_occurrence(
    tmp_path: Path,
) -> None:
    """Silence with a stated meaning, rather than a fabricated end.

    The human is still touching the arm when the recording stops. Emitting
    `contact_ended` at the last frame would record an event that did not happen;
    omitting it is what `run_ended` is for, and `OCCURRENCE_RETENTION` in the
    artifact says so, so the absence is readable rather than ambiguous.
    """
    frames = [_frame(i, (0.5, 0.0) if i >= 4 else (2.4, 0.0)) for i in range(10)]
    csv = _write_stream(tmp_path / "hold.csv", frames)
    out = tmp_path / "hold.sqlite"
    _build(csv, out)

    assert _occurrences(out, occurrence_type="contact_began")
    assert _occurrences(out, occurrence_type="contact_ended") == []
    assert _occurrences(out, occurrence_type="run_ended")
    conn = store.connect(out)
    try:
        rule = store.get_meta(conn, graph.META_OCCURRENCE_RETENTION)
    finally:
        conn.close()
    assert rule is not None and "run_ended bounds it" in rule


def test_the_closest_approach_agrees_with_the_edge_layers_minimum(
    tmp_path: Path,
) -> None:
    """One number, two layers, and they must be the same number.

    The occurrence layer's whole claim to answering `min_separation` is this row.
    If it disagreed with the `SEPARATION` edges by so much as a quantum, the
    coarse layer would be answering a different question cheaply rather than the
    same question cheaply.
    """
    n_frames = 24
    csv = _write_stream(
        tmp_path / "walk.csv",
        _creep_frames(n_frames, lambda i: (2.4 - 0.05 * i, 0.0)),
    )
    out = tmp_path / "walk.sqlite"
    _build(csv, out)

    edges = _edges(out, edge_type="SEPARATION", dst_id=HUMAN_ENTITY_ID)
    smallest = min(float(r["min_distance"]) for r in edges)
    earliest = min(
        float(r["t_start"]) for r in edges if float(r["min_distance"]) == smallest
    )

    closest = _occurrences(
        out, occurrence_type="closest_approach", entity_id=HUMAN_ENTITY_ID
    )
    assert len(closest) == 1
    assert float(closest[0]["value"]) == pytest.approx(smallest)
    # The timestamp is the *earliest* frame the minimum was seen at, rounded.
    # Not the last: a run that sits at its minimum reports when it got there.
    assert float(closest[0]["t"]) == pytest.approx(
        graph.quantize_occurrence_time(earliest, graph.OCCURRENCE_TIME_RESOLUTION_S)
    )


def test_every_occurrence_carries_the_dssad_elements(tmp_path: Path) -> None:
    """The data model, per UN R157 and docs/prior-art.md §9.

    The flag, the reason, the timestamp, the **date**, and the software version
    present at the event (`R157SWIN`).

    The date was deliberately absent until issue #83, on the argument that a
    wall-clock date is the ambient value that would break byte reproducibility.
    It is here now because that argument did not survive: the start is a
    *declared* input, like key material, so the artifact gains the datum and
    keeps the property. This asserts every element is present and that the two
    time bases agree — a `date` that did not follow `t` would be a wall-clock
    date the run did not happen on.
    """
    csv = _write_stream(
        tmp_path / "walk.csv", _creep_frames(12, lambda i: (0.95 - 0.03 * i, 0.0))
    )
    out = tmp_path / "walk.sqlite"
    _build(csv, out)

    conn = store.connect(out)
    try:
        rows = store.read_occurrences(conn)
        meta = store.all_meta(conn)
    finally:
        conn.close()

    assert rows, "precondition failed: this run produced no occurrences at all"
    expected = graph.sw_version(**_FAST)
    for row in rows:
        assert str(row["type"]) in store.OCCURRENCE_SPECS
        assert str(row["reason"]).strip()
        assert row["t"] is not None
        assert str(row["sw_version"]) == expected
        assert str(row["layer"]) == store.occurrence_layer(str(row["type"]))
        # The two time bases name one moment. Derived from the row's own
        # quantized `t`, so the three timestamp columns cannot disagree by up
        # to half a quantum — see `_OccurrenceLog.emit`.
        assert str(row["date"]) == TEST_IDENTITY.date(float(row["t"]))
        assert str(row["t_utc"]) == TEST_IDENTITY.timestamp_utc(float(row["t"]))

    # The stamp is checkable against the parameters it binds, both of which the
    # artifact carries: an occurrence whose digest its own meta cannot reproduce
    # would be an event and a parameter set from two different runs.
    assert meta[graph.META_OCCURRENCE_SW_VERSION] == expected
    assert meta[graph.META_OCCURRENCE_RESOLUTION] == repr(
        float(graph.OCCURRENCE_TIME_RESOLUTION_S)
    )
    assert meta[graph.META_OCCURRENCE_RETENTION] == graph.OCCURRENCE_RETENTION
    # The rule the artifact carries has to describe the artifact. It advertised
    # "there is no date element" until issue #83, and a row now carries one —
    # a retention rule that still denied it would be the file lying about
    # itself to the only reader who has nothing else to go on.
    assert "no date element" not in meta[graph.META_OCCURRENCE_RETENTION]
    assert "date element" in meta[graph.META_OCCURRENCE_RETENTION]
    assert meta[graph.META_RUN_START] == TEST_IDENTITY.run_start_text


def test_the_software_stamp_changes_when_the_envelope_parameters_do() -> None:
    """`R157SWIN`'s negative. A stamp that never moved would bind nothing.

    The regulation's point is that a recorded event can be attributed to the
    software that produced it. Here that includes the envelope parameters,
    because the same code at a different horizon computes a different envelope
    and therefore records a different set of `envelope_entered` events.
    """
    base = graph.sw_version(**_FAST)
    assert base != graph.sw_version(**{**_FAST, "horizon": 0.2})
    assert base != graph.sw_version(**{**_FAST, "n_samples": 8})
    assert base != graph.sw_version(**{**_FAST, "seed": 1})
    assert base == graph.sw_version(**_FAST)


@pytest.mark.parametrize("resolution", [1.0, 0.5, 0.02])
def test_the_timestamp_resolution_is_a_parameter_and_it_bites(
    tmp_path: Path, resolution: float
) -> None:
    """Settable, and settable to something that changes the record.

    The whole point of the layer is measuring what a resolution costs, so a
    resolution that were welded to 1.0 s would give one point and no curve. Every
    timestamp must land on a multiple of whatever was asked for — asserted as a
    property of every row rather than as a golden value for one.
    """
    frames = [
        _frame(i, (0.5, 0.0) if 7 <= i <= 15 else (2.4, 0.0)) for i in range(30)
    ]
    csv = _write_stream(tmp_path / "touch.csv", frames)
    out = tmp_path / f"touch_{resolution}.sqlite"
    _build(csv, out, occurrence_resolution_s=resolution)

    rows = _occurrences(out)
    assert rows
    for row in rows:
        t = float(row["t"])
        assert abs(t / resolution - round(t / resolution)) < 1e-9, (
            f"occurrence at t={t} is not a multiple of the {resolution} s "
            "resolution this artifact records itself as having."
        )
    conn = store.connect(out)
    try:
        assert store.get_meta(conn, graph.META_OCCURRENCE_RESOLUTION) == repr(
            float(resolution)
        )
    finally:
        conn.close()


def test_a_finer_resolution_locates_an_event_a_coarse_one_cannot(
    tmp_path: Path,
) -> None:
    """The cost of the coarse timestamp, made visible as a disagreement.

    Two builds of *one stream* differing in nothing but the occurrence
    resolution. At the frame period the contact is located exactly; at DSSAD's
    ±1 s it is a second away from where it happened. That gap is the measurement
    `reg.bench --resolution` reports, and this is the unit-level version of it.
    """
    frames = [
        _frame(i, (0.5, 0.0) if 42 <= i <= 60 else (2.4, 0.0)) for i in range(90)
    ]
    csv = _write_stream(tmp_path / "touch.csv", frames)
    fine = tmp_path / "fine.sqlite"
    coarse = tmp_path / "coarse.sqlite"
    _build(csv, fine, occurrence_resolution_s=DT)
    _build(csv, coarse, occurrence_resolution_s=1.0)

    t_fine = float(_occurrences(fine, occurrence_type="contact_began")[0]["t"])
    t_coarse = float(_occurrences(coarse, occurrence_type="contact_began")[0]["t"])
    assert t_fine == pytest.approx(42 * DT)
    assert t_coarse == pytest.approx(1.0)
    assert abs(t_coarse - t_fine) > TIME_TOL_S, (
        "the coarse build landed within TIME_TOL_S of the fine one, so this "
        "fixture is not exercising the resolution at all."
    )


@pytest.mark.parametrize("resolution", [0.0, -1.0, float("nan")])
def test_a_resolution_nobody_can_round_to_is_refused(
    tmp_path: Path, resolution: float
) -> None:
    """THE NEGATIVE for the parameter. No fallback to DSSAD's 1.0 s.

    A substituted resolution would timestamp every occurrence at a granularity
    the caller did not ask for and — since the artifact records what it was
    *given* — would then be recorded as though it had been asked for.
    """
    csv = _held_stream(tmp_path / "held.csv", 6)
    with pytest.raises(GraphBuildError, match="resolution"):
        _build(csv, tmp_path / "held.sqlite", occurrence_resolution_s=resolution)


def test_the_occurrence_layer_is_additive(tmp_path: Path) -> None:
    """It must not have moved one edge, one envelope row or one config.

    Issue #35: "the occurrence layer is additive. It does not replace the edge
    layer, and the existing tables and queries keep working." Asserted against a
    build made with the layer's own emission suppressed — the same stream, the
    same everything else — rather than against numbers copied from before the
    change, which would go stale the first time an unrelated tolerance moved.
    """
    frames = _sliding_frames(20)
    csv = _write_stream(tmp_path / "slide.csv", frames)
    with_layer = _build(csv, tmp_path / "with.sqlite")

    without = tmp_path / "without.sqlite"
    log = graph._OccurrenceLog
    try:
        graph._OccurrenceLog = _SilentOccurrenceLog
        result = _build(csv, without)
    finally:
        graph._OccurrenceLog = log

    assert result.edges == with_layer.edges
    assert result.nodes["Envelope"] == with_layer.nodes["Envelope"]
    assert result.nodes["RobotConfig"] == with_layer.nodes["RobotConfig"]
    assert result.nodes["Entity"] == with_layer.nodes["Entity"]
    assert result.nodes["Occurrence"] == 0
    assert with_layer.nodes["Occurrence"] > 0

    # And the rows themselves, not only their counts: every edge identical.
    #
    # Every column *except* the two surrogate keys (issue #55). `node_key` is
    # allocated in insertion order from one space shared by every kind, so a
    # build that also writes occurrence nodes numbers its envelopes differently
    # — the same nodes with different integers on them. What must not move is
    # the identity: `src_id`, `dst_id`, the kinds, the interval and the metrics,
    # which is what an edge actually asserts and what every query reads. A test
    # that compared the surrogates would fail on a renumbering that changed no
    # answer, and would say "the occurrence layer is not additive" when it is.
    _SURROGATES = ("src_key", "dst_key")

    def rows(path: Path):
        return [
            {k: row[k] for k in row.keys() if k not in _SURROGATES}
            for row in _edges(path)
        ]

    assert rows(without) == rows(tmp_path / "with.sqlite")


class _SilentOccurrenceLog:
    """A drop-in `_OccurrenceLog` that records nothing.

    Used by the additivity test only. It exists because the honest way to ask
    "did the occurrence layer change the edge layer" is to build the same stream
    with it and without it, and there is no flag to turn it off — the layer is
    not optional in the product, it is only optional in this one comparison.
    """

    def __init__(
        self, conn, *, resolution: float, stamp: str, identity: RunIdentity
    ) -> None:
        graph.quantize_occurrence_time(0.0, resolution)

    def run_began(self, t: float) -> None: ...

    def run_ended(self, t: float) -> None: ...

    def relationship_began(self, edge_type: str, entity_id: str, t: float) -> None: ...

    def relationship_ended(self, edge_type: str, entity_id: str, t: float) -> None: ...

    def separation_observed(self, entity_id: str, **kwargs) -> None: ...

    def closest_approaches(self) -> None: ...


def test_no_edge_type_points_at_an_occurrence() -> None:
    """Additive in the vocabulary too, and asserted against the schema.

    An edge to an `Occurrence` would make the coarse layer a participant in the
    fine one's joins, and the two would stop being separable views of one run —
    which is what `reg.bench --resolution` measures over.
    """
    assert "Occurrence" in store.NODE_TABLES
    for edge_type, spec in store.EDGE_SPECS.items():
        assert spec.src_kind != "Occurrence", edge_type
        assert spec.dst_kind != "Occurrence", edge_type


# --- the negatives: what the occurrence layer refuses ----------------------


def _occurrence_kwargs(**overrides):
    fields = {
        "seq": 0,
        "occurrence_type": "closest_approach",
        "reason": "the smallest separation observed",
        "t": 1.0,
        "date": TEST_IDENTITY.date(1.0),
        "t_utc": TEST_IDENTITY.timestamp_utc(1.0),
        "entity_id": "obs_a",
        "value": 0.4,
        "sw_version": "reg-test",
    }
    fields.update(overrides)
    return fields


def test_an_out_of_vocabulary_occurrence_is_refused(seeded) -> None:
    """The vocabulary is fixed and small, so an unknown type is a fault.

    Not a new row type: an artifact that accepted one would record an event
    whose meaning is nowhere written down, and the absence of a *known* type
    would stop meaning "it did not happen".
    """
    with pytest.raises(store.StoreError, match="not an occurrence type"):
        store.insert_occurrence(
            seeded, "occ_0", **_occurrence_kwargs(occurrence_type="escalation_failure")
        )
    with pytest.raises(store.StoreError, match="not an occurrence type"):
        store.occurrence_layer("veto")


def test_the_schema_itself_refuses_an_unknown_occurrence_type(seeded) -> None:
    """Not only the Python guard. The vocabulary is a CHECK in the file."""
    with pytest.raises(sqlite3.IntegrityError):
        seeded.execute(
            "INSERT INTO occurrence (occurrence_key, seq, type, layer, reason, "
            "t, date, t_utc, sw_version) VALUES (99, 0, 'veto', 'A', 'because', "
            "1.0, '2026/08/21', '2026-08-21T09:00:01.000000Z', 'v')"
        )


def test_an_occurrence_with_no_reason_is_refused(seeded) -> None:
    """DSSAD records the reason beside the flag. A blank one is not a record."""
    for blank in ("", "   "):
        with pytest.raises(store.StoreError, match="reason"):
            store.insert_occurrence(
                seeded, "occ_0", **_occurrence_kwargs(reason=blank)
            )


def test_an_occurrence_with_no_software_version_is_refused(seeded) -> None:
    """`R157SWIN`. An event nobody can attribute to a build is not evidence."""
    with pytest.raises(store.StoreError, match="R157SWIN"):
        store.insert_occurrence(seeded, "occ_0", **_occurrence_kwargs(sw_version=""))


def test_an_entity_occurrence_without_an_entity_is_refused(seeded) -> None:
    with pytest.raises(store.StoreError, match="names an entity"):
        store.insert_occurrence(
            seeded, "occ_0", **_occurrence_kwargs(entity_id=None)
        )


def test_a_run_occurrence_that_names_an_entity_is_refused(seeded) -> None:
    with pytest.raises(store.StoreError, match="names no entity"):
        store.insert_occurrence(
            seeded,
            "occ_0",
            **_occurrence_kwargs(
                occurrence_type="run_began", entity_id="obs_a", value=None
            ),
        )


def test_an_occurrence_naming_an_entity_that_is_not_there_is_refused(seeded) -> None:
    """The same dangling-reference refusal edges get: an occurrence about an
    entity the artifact does not contain is an event about nobody."""
    with pytest.raises(store.StoreError, match="no Entity node"):
        store.insert_occurrence(
            seeded, "occ_0", **_occurrence_kwargs(entity_id="obs_nowhere")
        )


def test_a_missing_occurrence_metric_is_refused(seeded) -> None:
    with pytest.raises(store.StoreError, match="min_distance_m"):
        store.insert_occurrence(seeded, "occ_0", **_occurrence_kwargs(value=None))


def test_a_metric_on_an_occurrence_that_carries_none_is_refused(seeded) -> None:
    with pytest.raises(store.StoreError, match="carries no value"):
        store.insert_occurrence(
            seeded,
            "occ_0",
            **_occurrence_kwargs(
                occurrence_type="envelope_entered", value=0.4
            ),
        )


def test_read_occurrences_refuses_an_unknown_type_rather_than_returning_nothing(
    seeded,
) -> None:
    """An empty list for a mistyped type reads as "no such event in this run"."""
    with pytest.raises(store.StoreError, match="not an occurrence type"):
        store.read_occurrences(seeded, occurrence_type="contact_begun")


@pytest.mark.parametrize("bad_date", ["", "2026-08-21", "21/08/2026", "  ", None])
def test_an_occurrence_date_that_is_not_dssads_is_refused(seeded, bad_date) -> None:
    """THE NEGATIVE for the date column (issue #83).

    The store checks shape and not value — it cannot know which afternoon the
    run happened on, and a check that knew would be a second source for it. What
    it can refuse is a column that ends up holding two formats, which is a column
    nobody can sort, compare or hand to an assessor. Includes the ISO spelling
    `2026-08-21`, because that is the one a contributor would reach for by habit
    and it is not the element UN R157 names.
    """
    with pytest.raises(store.StoreError, match="yyyy/mm/dd"):
        store.insert_occurrence(seeded, "occ_0", **_occurrence_kwargs(date=bad_date))


@pytest.mark.parametrize(
    "bad_instant",
    [
        "",
        "2026-08-21T09:00:01Z",  # no fractional digits
        "2026-08-21T09:00:01.000000",  # no offset at all
        "2026-08-21T09:00:01.000000+02:00",  # an offset, but not normalised
        "2026/08/21",
        None,
    ],
)
def test_an_occurrence_timestamp_that_is_not_a_utc_instant_is_refused(
    seeded, bad_instant
) -> None:
    """THE NEGATIVE for `t_utc`, and the interesting cases are the near misses.

    A timestamp with no offset is an instant only for a reader who already knows
    which zone the operator was in, and one carrying `+02:00` is a real instant
    written the way this artifact does not write them — two spellings in one
    column defeat the byte-comparison the whole project rests on. Both are
    refused rather than normalised here: `reg.identity.format_instant` is the
    one place that decides the rendering, and a store that also decided it would
    be a second answer to the same question.
    """
    with pytest.raises(store.StoreError, match="t_utc"):
        store.insert_occurrence(
            seeded, "occ_0", **_occurrence_kwargs(t_utc=bad_instant)
        )


# --------------------------------------------------------------------------
# Absolute time and identity (issue #83).
#
# WHAT THESE TESTS ARE ABOUT. Not that three strings reach `meta` — that is the
# easy half. They are about the two properties the issue turns on: that the
# identity is **required with no default**, because a plausible invented run
# start is indistinguishable downstream from a declared one; and that supplying
# it **preserved determinism exactly**, because the reason it was omitted for so
# long was the belief that it could not.
#
# The second needs both directions to mean anything. Same declared start giving
# the same bytes, on its own, is what a build that ignored the parameter
# entirely would also do.
# --------------------------------------------------------------------------


def test_the_artifact_says_which_robot_and_which_shift(tmp_path: Path) -> None:
    """"Hand it to an assessor" requires both, and neither is recoverable later.

    Before issue #83 every key in `meta` was an envelope parameter or a retention
    rule, so an artifact could not be correlated with any other log in the cell —
    which is how an incident is actually reconstructed — and an EU AI Act Art. 73
    clock could not be started from it.
    """
    csv = _held_stream(tmp_path / "held.csv", 4)
    out = tmp_path / "held.sqlite"
    _build(csv, out)

    meta = _meta(out)
    assert meta[graph.META_RUN_START] == TEST_IDENTITY.run_start_text
    assert meta[graph.META_UNIT_ID] == TEST_IDENTITY.unit_id
    assert meta[graph.META_OPERATOR_ID] == TEST_IDENTITY.operator_id


def test_the_same_seed_and_the_same_declared_start_give_the_same_bytes(
    tmp_path: Path,
) -> None:
    """CLAUDE.md rule 2, over the input that was supposed to make it impossible.

    This is the property the issue's whole argument rests on: absolute time was
    left out because a wall clock is "exactly the ambient value that would break
    determinism", and it does not break it when it is *declared* rather than
    read. Nothing in `reg.identity` reads a clock and
    `test_identity.py::test_this_module_never_reads_a_clock` asserts that against
    the source; this asserts the consequence at the artifact.
    """
    csv = _held_stream(tmp_path / "held.csv", 6)
    a = tmp_path / "a.sqlite"
    b = tmp_path / "b.sqlite"
    _build(csv, a)
    _build(csv, b)
    assert a.read_bytes() == b.read_bytes()


def test_a_different_declared_start_gives_different_bytes(tmp_path: Path) -> None:
    """THE OTHER HALF, and without it the test above proves nothing.

    A build that accepted `identity` and dropped it on the floor would produce
    identical bytes for identical inputs too — perfectly deterministic, and
    carrying no absolute time at all. So the parameter has to be shown to reach
    the artifact: two runs of one stream, differing in nothing but the declared
    instant, must not be the same file.
    """
    csv = _held_stream(tmp_path / "held.csv", 6)
    morning = tmp_path / "morning.sqlite"
    afternoon = tmp_path / "afternoon.sqlite"
    _build(csv, morning)
    _build(
        csv,
        afternoon,
        identity=RunIdentity.declare(
            run_start="2026-08-21T15:30:00Z",
            unit_id=TEST_IDENTITY.unit_id,
            operator_id=TEST_IDENTITY.operator_id,
        ),
    )

    assert morning.read_bytes() != afternoon.read_bytes()
    assert _meta(morning)[graph.META_RUN_START] != _meta(afternoon)[graph.META_RUN_START]
    # And it reached the rows, not only `meta`. An identity recorded in the
    # header while every occurrence still carried an unanchored float would be
    # the element-shaped alignment issue #83 is about.
    assert {str(r["t_utc"]) for r in _occurrences(morning)}.isdisjoint(
        {str(r["t_utc"]) for r in _occurrences(afternoon)}
    )


def test_the_declared_start_is_not_the_hosts_clock(tmp_path: Path) -> None:
    """The artifact records what it was told, not when it was built.

    Stated as a test rather than left to the module-level source check, because
    this is the property an assessor depends on: a `run_start_utc` quietly
    replaced by build time would be a wall-clock instant in the record that the
    run did not happen at, and it would look exactly as plausible.
    """
    csv = _held_stream(tmp_path / "held.csv", 4)
    out = tmp_path / "held.sqlite"
    declared = RunIdentity.declare(
        run_start="1999-12-31T23:59:59Z",
        unit_id="unit-7",
        operator_id="op-night",
    )
    _build(csv, out, identity=declared)

    assert _meta(out)[graph.META_RUN_START] == "1999-12-31T23:59:59.000000Z"
    assert all(str(r["date"]).startswith("1999/12/31") for r in _occurrences(out))


def test_a_build_with_no_identity_is_refused(tmp_path: Path) -> None:
    """No default, and the refusal names what is missing.

    `identity` is keyword-only and has no default, so omitting it is a
    `TypeError` from Python itself; passing something that is not a
    `RunIdentity` is the case the builder has to catch, and it refuses rather
    than coercing three strings out of whatever it was handed.
    """
    csv = _held_stream(tmp_path / "held.csv", 4)
    with pytest.raises(TypeError, match="identity"):
        build(csv, tmp_path / "a.sqlite", LIMITS, human_radius=HUMAN_RADIUS, **_FAST)

    for wrong in (None, "2026-08-21T09:00:00Z", ("unit", "op")):
        with pytest.raises(GraphBuildError, match="RunIdentity"):
            build(
                csv,
                tmp_path / "b.sqlite",
                LIMITS,
                identity=wrong,
                human_radius=HUMAN_RADIUS,
                **_FAST,
            )


# --------------------------------------------------------------------------
# The attestation layer (issue #45). Declarations, verdicts and the four edges.
#
# WHAT THESE TESTS ARE ABOUT. Not that the rows arrive — that is the easy half
# and a schema that flattened every verdict into its declaration would pass it.
# Three things:
#
# * **`ADJUDICATED` does not flatten.** `test_adjudicated_keeps_every_verdict`
#   is the one this section exists for, and it runs on the real
#   `declared_violation` fixture rather than a synthetic pair, because the
#   property is a fact about that run: the box is fixed for the whole scenario,
#   so five declarations carry an identical `declared_envelope` and one of them
#   is adjudicated PERMIT and later CLAMP. A one-row-per-declaration schema
#   passes every other test here and silently destroys the ability to say *when*
#   the violation began.
# * **Persistence does not launder a record.** The store holds no keys, so it
#   cannot check a MAC and must not be able to fix one.
#   `test_the_store_does_not_launder_a_bad_mac` feeds it the condition it guards
#   against and asserts the record still fails verification on the way out.
# * **What is refused.** A verdict naming a declaration the artifact does not
#   hold, and a record stream that is not one unbroken chain. Both would produce
#   an artifact that answers an audit question with something nobody can check.
# --------------------------------------------------------------------------

#: The keyring the fixtures here sign with. Fixed material, because these tests
#: compare artifacts byte for byte and `generate_keyring` is deliberately not
#: seeded — see `reg.chain.generate_keyring`. It is not a secret and is not
#: pretending to be one.
FIXTURE_KEYRING = Keyring.from_material(
    policy=bytes(range(32)), enforcement=bytes(range(32, 64))
)

#: The policy and enforcement parameters for these runs. Stated here because
#: `emit_declarations` and `Enforcer` refuse to invent any of the three, and
#: because a test that passed a different one per call would be comparing two
#: runs. They match `tests/test_enforce.py`'s fixture parameters, so the record
#: stream this file stores is the one that file adjudicates.
FIXTURE_REPLAN_S = 0.5
FIXTURE_HORIZON_S = 0.5
FIXTURE_WATCHDOG_S = 1.0


def _keyring_file(tmp_path: Path) -> Path:
    return write_keyring(FIXTURE_KEYRING, tmp_path / "keyring.json")


def _records_for(csv: Path, scn, tmp_path: Path) -> AttestationRecords:
    """The record stream for a stream, through the CLI's own producer.

    Through `graph.attestation_from_stream` rather than a second copy of the
    policy/enforcer wiring: a fixture that assembled the records differently
    from the way the CLI does would be testing a run nobody can produce.
    """
    return graph.attestation_from_stream(
        csv,
        scn,
        keyring_path=_keyring_file(tmp_path),
        replan_interval_s=FIXTURE_REPLAN_S,
        declaration_horizon_s=FIXTURE_HORIZON_S,
        watchdog_period_s=FIXTURE_WATCHDOG_S,
    )


@pytest.fixture(scope="module")
def attested(tmp_path_factory) -> tuple[Path, AttestationRecords]:
    """`declared_violation`, built with its own record stream. One build, shared.

    Module-scoped because it is the expensive fixture in this file — a full
    scenario, an envelope per frame — and every test below reads the same
    artifact rather than rebuilding it.
    """
    tmp = tmp_path_factory.mktemp("attested")
    scn = SCENARIOS["declared_violation"]
    csv = _scenario_stream(scn, scn.dt, tmp / "dv.csv")
    records = _records_for(csv, scn, tmp)
    out = tmp / "dv.sqlite"
    build(
        csv,
        out,
        scn.world.limits,
        identity=TEST_IDENTITY,
        human_radius=scn.world.human_radius,
        records=records,
        **_FAST,
    )
    return out, records


def _held_attested(tmp_path: Path, n_frames: int = 8) -> tuple[Path, AttestationRecords]:
    """A short held stream and its record stream. The cheap fixture."""
    csv = _held_stream(tmp_path / "held.csv", n_frames)
    return csv, _records_for(csv, SCENARIOS["contact"], tmp_path)


def _rows(path: Path, sql: str) -> list[sqlite3.Row]:
    conn = store.connect(path)
    try:
        return list(conn.execute(sql).fetchall())
    finally:
        conn.close()


def _meta(path: Path) -> dict[str, str]:
    conn = store.connect(path)
    try:
        return store.all_meta(conn)
    finally:
        conn.close()


# --- the property this issue exists for -----------------------------------


def test_adjudicated_keeps_every_verdict(attested) -> None:
    """THE TEST OF THIS ISSUE, on the real fixture and not a synthetic pair.

    A verdict is per **commanded action**, not per declaration (#43): the
    declared box is fixed for the whole of `declared_violation`, so every
    declaration carries an identical `declared_envelope` and the violation
    begins partway through. One declaration is therefore adjudicated PERMIT and
    then CLAMP, and the artifact has to be able to say so.

    Asserted three ways, because the failure this guards against is a schema
    that looks right: one `ADJUDICATED` edge per verdict that named a
    declaration, at least one declaration carrying more than one outcome, and
    strictly more edges than declarations.
    """
    out, records = attested

    outcomes = Counter(v.outcome for v in records.verdicts)
    assert outcomes["PERMIT"] and outcomes["CLAMP"], (
        f"precondition failed: {outcomes}. This fixture is supposed to be "
        "permitted and then clamped; without both, the property below is not "
        "being tested at all."
    )

    edges = _edges(out, edge_type="ADJUDICATED")
    named = [v for v in records.verdicts if v.declaration_id is not None]
    assert len(edges) == len(named), (
        f"{len(edges)} ADJUDICATED edges for {len(named)} verdicts that named a "
        "declaration. One per verdict, never one per declaration."
    )
    assert len(edges) > len(records.declarations)

    by_declaration: dict[str, set[str]] = {}
    verdict_outcomes = {v.verdict_id: v.outcome for v in records.verdicts}
    for row in edges:
        by_declaration.setdefault(str(row["dst_id"]), set()).add(
            verdict_outcomes[str(row["src_id"])]
        )
    both = sorted(k for k, o in by_declaration.items() if len(o) > 1)
    assert both, (
        "no declaration in the artifact is adjudicated more than one way. The "
        "run contains one; a schema that cannot express it has lost when the "
        "violation began, which is the demo sentence's second clause."
    )
    assert {"PERMIT", "CLAMP"} <= by_declaration[both[0]]


def test_the_records_survive_persistence_byte_for_byte(attested) -> None:
    """A record read back out of SQLite is the record that was signed.

    Equality of the dataclasses is the strong form of it: every field, including
    the WKB bytes and both hashes. If this fails, the canonical serialization is
    not surviving persistence and every MAC in the artifact is unverifiable for
    a reason nothing in the file records.
    """
    out, records = attested
    conn = store.connect(out)
    try:
        assert store.read_declarations(conn) == list(records.declarations)
        assert store.read_verdicts(conn) == list(records.verdicts)
    finally:
        conn.close()


def test_the_records_still_verify_under_the_keys_that_signed_them(attested) -> None:
    """The point of storing the MAC at all, per record type.

    And the third state beside it: with no key the check is
    COULD_NOT_EVALUATE, never VALID. A verifier without the key has learned
    nothing about the record.
    """
    out, _ = attested
    conn = store.connect(out)
    try:
        declarations = store.read_declarations(conn)
        verdicts = store.read_verdicts(conn)
    finally:
        conn.close()

    assert declarations and verdicts
    for declaration in declarations:
        assert (
            verify_declaration(declaration, FIXTURE_KEYRING.key("policy")).state
            is MacState.VALID
        )
        assert verify_declaration(declaration, None).state is MacState.COULD_NOT_EVALUATE
    for verdict in verdicts:
        assert (
            verify_verdict(verdict, FIXTURE_KEYRING.key("enforcement")).state
            is MacState.VALID
        )
        assert verify_verdict(verdict, None).state is MacState.COULD_NOT_EVALUATE


def test_record_timestamps_are_not_quantized_on_the_way_in(attested) -> None:
    """The edge layer's endpoints are observations; a record's `t` is signed.

    `TIME_TOL_S` is the resolution the artifact reports *transitions* at. A
    declaration's `t_issued` is a value the MAC covers, so rounding it would
    store an instant nobody signed — and the DECLARED edge would then name a
    window the record does not.
    """
    out, records = attested
    edges = {str(r["src_id"]): r for r in _edges(out, edge_type="DECLARED")}
    for declaration in records.declarations:
        row = edges[declaration.declaration_id]
        assert row["t_start"] == declaration.t_issued
        assert row["t_end"] == declaration.t_issued + declaration.horizon


def test_every_attestation_edge_is_layer_a_and_names_no_entity(attested) -> None:
    """docs/sufficiency.md §2, asserted on a real artifact rather than argued.

    Every declaration, every verdict, every bound and every chain link in this
    file is answerable without trusting a perceiver. `Entity` appears at neither
    end of any of the four types — which is why the attestation half of the
    artifact survives an uncertifiable perceiver and the scene half does not.
    """
    out, _ = attested
    attestation = ("DECLARED", "ADJUDICATED", "ENFORCED", "FOLLOWS")
    seen = 0
    for edge_type in attestation:
        rows = _edges(out, edge_type=edge_type)
        seen += len(rows)
        for row in rows:
            assert row["layer"] == "A", edge_type
            assert row["src_kind"] != "Entity"
            assert row["dst_kind"] != "Entity"
    assert seen, "no attestation edges were written; this test proved nothing"

    # And the other direction, so the assertion above is not vacuous for a
    # build that simply tagged everything A: the entity-naming edges are B.
    for row in _edges(out, layer="B"):
        assert "Entity" in (row["src_kind"], row["dst_kind"])


def test_follows_links_two_chains_and_not_one(attested) -> None:
    """Declarations chain under the policy key, verdicts under enforcement's.

    So the artifact holds two chains, each beginning at the genesis hash, and a
    `FOLLOWS` edge never crosses between them — a link from a verdict to a
    declaration would assert that one signed over the other, which neither did.
    """
    out, records = attested
    rows = _edges(out, edge_type="FOLLOWS")
    assert len(rows) == (len(records.declarations) - 1) + (len(records.verdicts) - 1)
    kinds = Counter((str(r["src_kind"]), str(r["dst_kind"])) for r in rows)
    assert set(kinds) == {("Declaration", "Declaration"), ("Verdict", "Verdict")}
    assert kinds[("Declaration", "Declaration")] == len(records.declarations) - 1

    # Every link is the one the record itself carries, resolved to a row.
    by_id = {d.declaration_id: d for d in records.declarations}
    by_id.update({v.verdict_id: v for v in records.verdicts})
    for row in rows:
        successor = by_id[str(row["src_id"])]
        predecessor = by_id[str(row["dst_id"])]
        assert successor.prev_hash == chain_hash(predecessor, predecessor.prev_hash)


def test_the_declared_and_the_clamped_bound_are_separate_rows(attested) -> None:
    """docs/lossiness.md Retained #8: "a clamp is only legible if the declared
    and the computed bound both survive".

    On this fixture the clamp is *to* the declared envelope, so the two rows
    hold the same region — and they are still two rows, because "what the policy
    claimed" and "what enforcement applied" are different answers that happen to
    coincide here. Collapsing them would make a clamp to something narrower
    indistinguishable from a clamp to the declaration.
    """
    out, records = attested
    rows = {str(r["source"]): r for r in _envelope_rows(out)}
    assert {"computed", "declared", "clamped"} <= set(rows)
    assert rows["declared"]["envelope_hash"] == rows["clamped"]["envelope_hash"]
    assert rows["declared"]["envelope_id"] != rows["clamped"]["envelope_id"]

    # The declared bound carries the declaration's validity window; the clamped
    # one carries no horizon, because the Verdict record states none.
    assert rows["declared"]["horizon"] == FIXTURE_HORIZON_S
    assert rows["clamped"]["horizon"] is None

    # Both store their polygon: GEOMETRY_RETENTION discards only what can be
    # recomputed from a config in this file, and a policy's bound cannot be.
    for source in ("declared", "clamped"):
        assert rows[source]["geometry_wkb"] is not None
        assert rows[source]["config_id"] is None
    stored = store.from_wkb(rows["declared"]["geometry_wkb"])
    assert stored.equals(records.declarations[0].envelope())


def test_enforced_exists_for_a_clamp_and_for_nothing_else(attested) -> None:
    """A PERMIT bounds nothing; a VETO and a SAFE_STATE permit no action to
    bound. An ENFORCED edge to a region on a PERMIT would read as though
    something had been allowed inside it."""
    out, records = attested
    rows = _edges(out, edge_type="ENFORCED")
    clamps = [v for v in records.verdicts if v.outcome == "CLAMP"]
    assert clamps, "precondition failed: this fixture produced no clamp"
    assert {str(r["src_id"]) for r in rows} == {v.verdict_id for v in clamps}


def test_the_artifact_says_whether_it_was_given_a_record_stream(
    tmp_path: Path,
) -> None:
    """An empty `declaration` table is two different facts and it has to say
    which. `None` is "this build stored no record stream"; an empty
    `AttestationRecords` is "this run produced no records"."""
    csv, records = _held_attested(tmp_path)

    with_records = tmp_path / "with.sqlite"
    _build(csv, with_records, records=records)
    meta = _meta(with_records)
    assert meta[graph.META_ATTESTATION_RECORDS] == "present"
    assert meta[graph.META_DECLARATION_COUNT] == str(len(records.declarations))
    assert meta[graph.META_VERDICT_COUNT] == str(len(records.verdicts))
    assert graph.ATTESTATION_RETENTION == meta[graph.META_ATTESTATION_RETENTION]

    none_given = tmp_path / "none.sqlite"
    _build(csv, none_given)
    meta = _meta(none_given)
    assert meta[graph.META_ATTESTATION_RECORDS] == "absent"
    assert graph.META_DECLARATION_COUNT not in meta

    produced_none = tmp_path / "empty.sqlite"
    result = _build(
        csv, produced_none, records=AttestationRecords(declarations=(), verdicts=())
    )
    meta = _meta(produced_none)
    assert meta[graph.META_ATTESTATION_RECORDS] == "present"
    assert meta[graph.META_DECLARATION_COUNT] == "0"
    assert result.nodes["Declaration"] == 0


def test_the_attestation_layer_is_deterministic(tmp_path: Path) -> None:
    """CLAUDE.md rule 2, over the half of the artifact that carries MACs.

    Same stream, same keyring, same parameters, same bytes. A record stream is
    the easiest place for an artifact to stop being reproducible — a clock, a
    UUID or an unordered iteration would all show up here first.
    """
    csv, records = _held_attested(tmp_path)
    again = _records_for(csv, SCENARIOS["contact"], tmp_path)
    assert again == records, "the producer is not deterministic; the build cannot be"

    a = tmp_path / "a.sqlite"
    b = tmp_path / "b.sqlite"
    _build(csv, a, records=records)
    _build(csv, b, records=again)
    assert a.read_bytes() == b.read_bytes()


# --- the enforcement occurrences ------------------------------------------


def _verdict_chain(specs) -> tuple[Verdict, ...]:
    """A signed, chained verdict stream from `(t, outcome, fault)` triples.

    Synthetic, and deliberately so: the five enforcement occurrences include
    four that no *scenario* yet drives (issue #46 adds the fixtures). These are
    real `Verdict` records all the same — constructed, signed with the
    enforcement key and chained — so what is being tested is the builder's
    mapping and not a mock of it.
    """
    clamped = envelope_wkb(Point(0.0, 0.0).buffer(0.5))
    out: list[Verdict] = []
    prev = GENESIS_HASH
    for i, (t, outcome, fault) in enumerate(specs):
        verdict = Verdict(
            verdict_id=f"synthetic-verdict-{i:05d}",
            declaration_id=None,
            seq=i,
            t=t,
            outcome=outcome,
            fault=fault,
            clamped_envelope=clamped if outcome == "CLAMP" else None,
            prev_hash=prev,
            mac=UNSIGNED_MAC,
        )
        signed = sign_verdict(verdict, FIXTURE_KEYRING.key("enforcement"))
        out.append(signed)
        prev = chain_hash(signed, prev)
    return tuple(out)


#: One verdict stream that reaches every enforcement occurrence, and the rows it
#: must produce. The two things being pinned are what *does not* produce a row:
#: a PERMIT while running, which is the run proceeding normally and would be one
#: row per frame; and a SAFE_STATE while already passivated, which reports a
#: passivation this layer has already recorded.
_OCCURRENCE_WALK = (
    (0.00, "PERMIT", None),
    (0.02, "SAFE_STATE", "watchdog_expiry"),
    (0.04, "SAFE_STATE", "watchdog_expiry"),
    (0.06, "PERMIT", None),
    (0.08, "CLAMP", "declaration_action_mismatch"),
    (0.10, "VETO", "unattributed"),
    (0.12, "SAFE_STATE", "escalation_failure"),
    (0.14, "PERMIT", None),
)
_OCCURRENCE_WALK_EXPECTED = (
    "safe_state_entered",
    "reintegrated",
    "action_clamped",
    "declaration_vetoed",
    "escalation_failed",
    "reintegrated",
)


def test_the_five_enforcement_occurrences_are_emitted(tmp_path: Path) -> None:
    """Every verdict-derived occurrence type, and the two suppressions.

    Eight verdicts, six rows. The three PERMITs produce one row between them and
    it is a `reintegrated`, not a permission; the second consecutive SAFE_STATE
    produces nothing at all.
    """
    csv = _held_stream(tmp_path / "held.csv", 8)
    out = tmp_path / "held.sqlite"
    _build(
        csv,
        out,
        records=AttestationRecords(
            declarations=(), verdicts=_verdict_chain(_OCCURRENCE_WALK)
        ),
    )

    enforcement = {
        name
        for name, spec in store.OCCURRENCE_SPECS.items()
        if name
        in (
            "declaration_vetoed",
            "action_clamped",
            "safe_state_entered",
            "reintegrated",
            "escalation_failed",
        )
    }
    got = tuple(
        str(row["type"])
        for row in _occurrences(out)
        if str(row["type"]) in enforcement
    )
    assert got == _OCCURRENCE_WALK_EXPECTED
    assert enforcement <= set(got), "a type in the vocabulary was never reachable"

    # Layer A, every one of them: an enforcement event names no entity, and the
    # schema ties the two together.
    for row in _occurrences(out):
        if str(row["type"]) in enforcement:
            assert row["layer"] == "A"
            assert row["entity_id"] is None
            assert str(row["reason"]).strip()


def test_a_permitted_run_produces_no_enforcement_occurrence(tmp_path: Path) -> None:
    """THE NEGATIVE for the rule above, on a stream where nothing goes wrong.

    A row per permitted action is a row per frame wearing a coarser timestamp,
    which is the cost this layer exists to escape. So a run in which the policy
    kept its word must leave the occurrence layer exactly as it was.
    """
    csv, records = _held_attested(tmp_path)
    assert {v.outcome for v in records.verdicts} == {"PERMIT"}, (
        "precondition failed: this fixture was supposed to be compliant"
    )

    without = tmp_path / "without.sqlite"
    with_records = tmp_path / "with.sqlite"
    _build(csv, without)
    _build(csv, with_records, records=records)
    assert Counter(str(r["type"]) for r in _occurrences(without)) == Counter(
        str(r["type"]) for r in _occurrences(with_records)
    )


# --- the negatives ---------------------------------------------------------


def test_the_store_does_not_launder_a_bad_mac(tmp_path: Path) -> None:
    """THE NEGATIVE TEST: persistence must not make a broken record verify.

    **It is stored, not refused, and that is the deliberate half.** This module
    holds no keys and cannot tell a good MAC from a bad one; a store that could
    would be a store that can quietly repair a chain. What it must never do is
    make the record come back out clean — so the same declaration is asserted
    VALID before and INVALID after, both through the artifact.
    """
    csv, records = _held_attested(tmp_path)
    good = records.declarations[0]
    assert (
        verify_declaration(good, FIXTURE_KEYRING.key("policy")).state is MacState.VALID
    )

    # A well-formed digest that is not this record's. Well-formed on purpose:
    # `Declaration` refuses to construct with a malformed one, so the
    # interesting case — a MAC that looks entirely fine — is this one.
    flipped = ("0" if good.mac[0] != "0" else "1") + good.mac[1:]
    tampered = replace(good, mac=flipped)

    conn = store.create(tmp_path / "laundry.sqlite", record_tables=True)
    try:
        store.insert_declaration(conn, tampered)
        conn.commit()
        read_back = store.read_declarations(conn)
    finally:
        conn.close()

    assert len(read_back) == 1
    assert read_back[0] == tampered
    assert (
        verify_declaration(read_back[0], FIXTURE_KEYRING.key("policy")).state
        is MacState.INVALID
    )


def test_a_verdict_naming_a_declaration_that_is_not_there_is_refused(
    tmp_path: Path,
) -> None:
    """THE NEGATIVE: an ADJUDICATED edge to nothing is an answer nobody can
    check, so the verdict is refused before the edge can be written."""
    csv, records = _held_attested(tmp_path)
    verdict = next(v for v in records.verdicts if v.declaration_id is not None)

    conn = store.create(tmp_path / "dangling.sqlite", record_tables=True)
    try:
        with pytest.raises(store.StoreError, match="no Declaration node"):
            store.insert_verdict(conn, verdict)
    finally:
        conn.close()


def test_a_verdict_naming_no_declaration_is_stored_and_gets_no_edge(
    tmp_path: Path,
) -> None:
    """The other side of it: `declaration_id=None` is a *finding*, not a gap.

    It is what `no_declaration` and `watchdog_expiry` look like in the record,
    and the absent ADJUDICATED edge is what says so.
    """
    csv = _held_stream(tmp_path / "held.csv", 8)
    out = tmp_path / "held.sqlite"
    verdicts = _verdict_chain([(0.0, "SAFE_STATE", "watchdog_expiry")])
    result = _build(
        csv, out, records=AttestationRecords(declarations=(), verdicts=verdicts)
    )
    assert result.nodes["Verdict"] == 1
    assert result.edges["ADJUDICATED"] == 0
    conn = store.connect(out)
    try:
        assert store.read_verdicts(conn) == list(verdicts)
    finally:
        conn.close()


@pytest.mark.parametrize("drop", [0, 1])
def test_a_record_stream_that_is_not_one_chain_is_refused(
    tmp_path: Path, drop: int
) -> None:
    """THE NEGATIVE for `FOLLOWS`: no edge is written across a break.

    Two ways to break it, and both are refusals rather than a shorter chain.
    Dropping the first record leaves a stream whose head links to a predecessor
    the artifact does not hold; dropping a later one leaves two records that are
    not consecutive. A `FOLLOWS` edge written over either would let a chain walk
    cleanly across records nobody ever saw.
    """
    csv, records = _held_attested(tmp_path, n_frames=60)
    assert len(records.verdicts) > 3
    broken = tuple(v for i, v in enumerate(records.verdicts) if i != drop)

    with pytest.raises(GraphBuildError, match="genesis|consecutive"):
        _build(
            csv,
            tmp_path / "broken.sqlite",
            records=AttestationRecords(
                declarations=records.declarations, verdicts=broken
            ),
        )
    assert not (tmp_path / "broken.sqlite").exists(), (
        "a refused build must leave no artifact: a half-written one queries "
        "cleanly and is missing everything after the failure."
    )


def test_a_record_that_was_altered_after_signing_breaks_its_successors_link(
    tmp_path: Path,
) -> None:
    """The same check, doing the job it is really there for.

    `_check_link` recomputes the *predecessor's* chain hash over the record as
    it stands, MAC included. So a record edited after it was signed no longer
    matches what its successor committed to, and the build refuses rather than
    storing a chain that walks over the edit.
    """
    csv, records = _held_attested(tmp_path, n_frames=60)
    altered = list(records.verdicts)
    altered[1] = replace(altered[1], t=altered[1].t + 1.0)

    with pytest.raises(GraphBuildError, match="consecutive"):
        _build(
            csv,
            tmp_path / "altered.sqlite",
            records=AttestationRecords(
                declarations=records.declarations, verdicts=tuple(altered)
            ),
        )


def test_records_must_be_records(tmp_path: Path) -> None:
    """An object that resembles a record has not been through the validation
    that makes it one, and `build` refuses the whole stream rather than storing
    part of it."""
    with pytest.raises(GraphBuildError, match="not a Declaration"):
        AttestationRecords(declarations=("decl-0",), verdicts=())
    with pytest.raises(GraphBuildError, match="must be a tuple"):
        AttestationRecords(declarations=[], verdicts=())
    csv = _held_stream(tmp_path / "held.csv", 4)
    with pytest.raises(GraphBuildError, match="AttestationRecords or None"):
        _build(csv, tmp_path / "held.sqlite", records=("not", "records"))


def test_a_clamped_envelope_carrying_a_horizon_is_refused(seeded) -> None:
    """THE NEGATIVE for the nullable column: the two directions are tied.

    A clamped bound with a horizon reports a validity window the `Verdict`
    record does not state, and a declared or computed one without drops the
    interval its region is a claim about. Neither is a value to invent.
    """
    disc = Point(0.0, 0.0).buffer(0.4)
    with pytest.raises(store.StoreError, match="clamped bound"):
        store.insert_envelope(
            seeded,
            "env_clamped",
            envelope_hash=_HASH_B,
            area=0.5,
            geometry=disc,
            config_id=None,
            horizon=0.2,
            source="clamped",
        )
    with pytest.raises(store.StoreError, match="clamped bound"):
        store.insert_envelope(
            seeded,
            "env_declared",
            envelope_hash=_HASH_B,
            area=0.5,
            geometry=disc,
            config_id=None,
            horizon=None,
            source="declared",
        )


def test_a_follows_edge_must_say_which_records_it_joins(seeded) -> None:
    """THE NEGATIVE for the one polymorphic edge type. No likeliest kind.

    `FOLLOWS` is the only edge whose endpoints vary, so the kind is the caller's
    to state and out-of-vocabulary is a refusal. An edge stored against the
    wrong table is a dangling reference, and every join over it returns nothing
    — which reads as "these records do not follow one another".
    """
    with pytest.raises(store.StoreError, match="has to be stated"):
        store.open_edge(seeded, "FOLLOWS", "a", "b", 0.0)
    with pytest.raises(store.StoreError, match="cannot run from"):
        store.open_edge(
            seeded, "FOLLOWS", "a", "b", 0.0, src_kind="Envelope", dst_kind="Envelope"
        )
    # And the converse: a fixed-endpoint type does not take one either.
    with pytest.raises(store.StoreError, match="always runs from"):
        store.open_edge(
            seeded, "HAS_ENVELOPE", "cfg_0", "env_0", 0.0, src_kind="Verdict"
        )


# --- the CLI ---------------------------------------------------------------


def test_cli_builds_the_attestation_layer(tmp_path: Path, capsys) -> None:
    """The deliverable end to end: a stream and a keyring in, records out."""
    csv = _held_stream(tmp_path / "held.csv", 8)
    out = tmp_path / "held.sqlite"
    code = graph.main(
        [
            "build",
            str(csv),
            "--out",
            str(out),
            "--horizon",
            "0.1",
            "--n-samples",
            "4",
            "--substep-dt",
            "0.05",
            "--keyring",
            str(_keyring_file(tmp_path)),
            "--replan-interval",
            str(FIXTURE_REPLAN_S),
            "--declaration-horizon",
            str(FIXTURE_HORIZON_S),
            "--watchdog-period",
            str(FIXTURE_WATCHDOG_S),
            *IDENTITY_ARGV,
        ]
    )
    assert code == 0
    conn = store.connect(out)
    try:
        assert store.read_declarations(conn)
        assert store.read_verdicts(conn)
    finally:
        conn.close()
    assert _meta(out)[graph.META_ATTESTATION_RECORDS] == "present"


@pytest.mark.parametrize(
    "omit",
    ["--replan-interval", "--declaration-horizon", "--watchdog-period"],
)
def test_cli_refuses_a_keyring_without_the_parameters_it_needs(
    tmp_path: Path, omit: str
) -> None:
    """THE NEGATIVE for the never-invent-a-default rule at the CLI.

    docs/plan.md fixes no replan rate, no declaration horizon and no watchdog
    period, and each of the three decides which of the nine faults can fire. A
    plausible number substituted here would be indistinguishable downstream from
    one somebody stated — so the missing one is named and nothing is built.
    """
    csv = _held_stream(tmp_path / "held.csv", 4)
    argv = [
        "build",
        str(csv),
        "--out",
        str(tmp_path / "held.sqlite"),
        "--keyring",
        str(_keyring_file(tmp_path)),
        "--replan-interval",
        "0.5",
        "--declaration-horizon",
        "0.5",
        "--watchdog-period",
        "1.0",
        *IDENTITY_ARGV,
    ]
    at = argv.index(omit)
    del argv[at : at + 2]
    with pytest.raises(SystemExit) as excinfo:
        graph.main(argv)
    assert excinfo.value.code == graph.EXIT_USAGE
    assert not (tmp_path / "held.sqlite").exists()


def test_cli_refuses_the_parameters_without_a_keyring(tmp_path: Path) -> None:
    """The other direction: nothing signs a declaration without a keyring, so
    there is no record stream for the three to parameterise."""
    csv = _held_stream(tmp_path / "held.csv", 4)
    with pytest.raises(SystemExit) as excinfo:
        graph.main(
            [
                "build",
                str(csv),
                "--out",
                str(tmp_path / "held.sqlite"),
                "--replan-interval",
                "0.5",
                *IDENTITY_ARGV,
            ]
        )
    assert excinfo.value.code == graph.EXIT_USAGE


@pytest.mark.parametrize(
    "omit", ["--run-start", "--unit-id", "--operator-id"]
)
def test_cli_refuses_a_build_with_no_identity(
    tmp_path: Path, capsys, omit: str
) -> None:
    """THE NEGATIVE for "required, no default" (issue #83).

    One case per flag, and each asserts the message **names the flag it is
    missing**. That is the part worth testing: the whole reason the three are
    checked by hand rather than with `required=True` is that argparse's message
    says a flag is absent without saying why there is no default for it, and a
    reader who does not know why will supply a plausible instant.

    No artifact is written either. A build that refused and left a partial file
    would leave behind an artifact with no absolute time — the exact object this
    issue exists to stop.
    """
    csv = _held_stream(tmp_path / "held.csv", 4)
    out = tmp_path / "held.sqlite"
    argv = ["build", str(csv), "--out", str(out), *IDENTITY_ARGV]
    at = argv.index(omit)
    del argv[at : at + 2]

    with pytest.raises(SystemExit) as excinfo:
        graph.main(argv)
    assert excinfo.value.code == graph.EXIT_USAGE
    assert omit in capsys.readouterr().err
    assert not out.exists()


def test_cli_refuses_a_run_start_that_is_not_an_instant(
    tmp_path: Path, capsys
) -> None:
    """Supplied but unusable is its own outcome, and it is not a pass.

    `2026-08-21T09:00:00` is the case that matters: it looks like a run start,
    and it names an instant only for a reader who already knows which zone the
    operator was in. Refused rather than assumed to be UTC — an assumed offset
    is indistinguishable downstream from a stated one and is wrong by up to
    fourteen hours.
    """
    csv = _held_stream(tmp_path / "held.csv", 4)
    out = tmp_path / "held.sqlite"
    code = graph.main(
        [
            "build",
            str(csv),
            "--out",
            str(out),
            "--run-start",
            "2026-08-21T09:00:00",
            "--unit-id",
            "unit-7",
            "--operator-id",
            "op-day",
        ]
    )
    assert code == graph.EXIT_USAGE
    assert "offset" in capsys.readouterr().err
    assert not out.exists()


def test_cli_refuses_a_blank_identifier(tmp_path: Path, capsys) -> None:
    """A blank id reads as an absent one in every `meta` dump, having been
    supplied. That is worse than the flag being missing, because nothing
    downstream can tell the two apart."""
    csv = _held_stream(tmp_path / "held.csv", 4)
    out = tmp_path / "held.sqlite"
    code = graph.main(
        [
            "build",
            str(csv),
            "--out",
            str(out),
            "--run-start",
            "2026-08-21T09:00:00Z",
            "--unit-id",
            "   ",
            "--operator-id",
            "op-day",
        ]
    )
    assert code == graph.EXIT_USAGE
    assert "unit_id" in capsys.readouterr().err
    assert not out.exists()


def test_cli_refuses_a_keyring_it_cannot_read(tmp_path: Path, capsys) -> None:
    """A could-not-evaluate, named, and no artifact written."""
    csv = _held_stream(tmp_path / "held.csv", 4)
    bad = tmp_path / "not-a-keyring.json"
    bad.write_text("{}\n", encoding="utf-8")
    code = graph.main(
        [
            "build",
            str(csv),
            "--out",
            str(tmp_path / "held.sqlite"),
            "--keyring",
            str(bad),
            "--replan-interval",
            "0.5",
            "--declaration-horizon",
            "0.5",
            "--watchdog-period",
            "1.0",
            *IDENTITY_ARGV,
        ]
    )
    assert code == graph.EXIT_USAGE
    assert "keyring" in capsys.readouterr().err
    assert not (tmp_path / "held.sqlite").exists()


# --------------------------------------------------------------------------
# ENCODING (issue #54). Two decisions about how the file is written, and the
# things they are not allowed to change.
#
# `PAGE_SIZE` and the conditional `RECORD_SCHEMA` alter no column, no row, no
# answer and no tolerance. The tests here are the ones that hold that line at
# the schema level; `tests/test_query.py` holds it at the answer level, by
# building the same stream under both encodings and comparing every query.
# --------------------------------------------------------------------------


def test_the_artifact_is_written_at_the_page_size_the_store_states(
    tmp_path: Path,
) -> None:
    """The header says what `reg.store.PAGE_SIZE` says, on a real build.

    SQLite fixes the page size at file creation, so this is also the assertion
    that nothing writes to the file before the schema does.
    """
    csv = _held_stream(tmp_path / "held.csv", 6)
    out = tmp_path / "held.sqlite"
    _build(csv, out)

    conn = store.connect(out)
    try:
        assert int(conn.execute("PRAGMA page_size").fetchone()[0]) == store.PAGE_SIZE
    finally:
        conn.close()

    # SQLite accepts a power of two in [512, 65536] and *silently ignores*
    # anything else, so a constant outside the range would leave every artifact
    # at the default with nothing to show for the change.
    assert 512 <= store.PAGE_SIZE <= 65536
    assert store.PAGE_SIZE & (store.PAGE_SIZE - 1) == 0


def test_create_refuses_a_page_size_that_did_not_take(
    tmp_path: Path, monkeypatch
) -> None:
    """THE NEGATIVE for the check above. Feed it a page size SQLite will not use.

    1000 is not a power of two, so SQLite ignores the PRAGMA and creates the
    file at its own default — no error, no warning, and an artifact that is
    perfectly readable while being nothing like the one that was measured.
    That silence is the whole reason `create` reads the value back.
    """
    monkeypatch.setattr(store, "PAGE_SIZE", 1000)
    with pytest.raises(store.StoreError, match="page size"):
        store.create(tmp_path / "wrong-page-size.sqlite", record_tables=False)


def test_a_store_created_without_the_record_tables_does_not_have_them(
    tmp_path: Path,
) -> None:
    conn = store.create(tmp_path / "none.sqlite", record_tables=False)
    try:
        assert store.has_record_tables(conn) is False
        tables = {
            str(row["name"])
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert not tables & store.RECORD_TABLE_NAMES
        # Everything else is still there: this is two tables, not a level.
        assert {
            "meta",
            "node",
            "envelope",
            "entity",
            "robot_config",
            "edge",
            "occurrence",
        } <= tables
    finally:
        conn.close()

    with_records = store.create(tmp_path / "with.sqlite", record_tables=True)
    try:
        assert store.has_record_tables(with_records) is True
    finally:
        with_records.close()


def test_half_a_record_layer_is_a_could_not_evaluate(tmp_path: Path) -> None:
    """NEGATIVE. One table without the other is neither state, so it is refused.

    A verdict whose `declaration` table is gone names a record nobody can look
    up, and a chain walked over half a record layer comes back shorter with no
    break in it — which is the one thing the chain exists to make impossible.
    """
    conn = store.create(tmp_path / "half.sqlite", record_tables=True)
    try:
        conn.execute("DROP TABLE declaration")
        conn.commit()
        with pytest.raises(store.StoreError, match="both tables or neither"):
            store.has_record_tables(conn)
    finally:
        conn.close()


def test_the_record_layer_refuses_rather_than_answering_from_a_missing_table(
    tmp_path: Path,
) -> None:
    """NEGATIVE. Every way into the record tables says what is missing.

    An empty list from `read_declarations` would read as "this run declared
    nothing", and a bare `no such table: declaration` out of SQLite names the
    encoding rather than the fact. Both are refused with the sentence that
    points at `meta[attestation_records]`.
    """
    csv, records = _held_attested(tmp_path)
    conn = store.create(tmp_path / "none.sqlite", record_tables=False)
    try:
        for call in (
            lambda: store.read_declarations(conn),
            lambda: store.read_verdicts(conn),
            lambda: store.insert_declaration(conn, records.declarations[0]),
            lambda: store.insert_verdict(conn, records.verdicts[0]),
        ):
            with pytest.raises(store.StoreError, match="attestation_records"):
                call()

        # And the edge layer, which is the other way in: a FOLLOWS or a DECLARED
        # edge resolves its endpoints through the same tables.
        store.insert_envelope(
            conn,
            "env_0",
            envelope_hash=_HASH_A,
            area=0.25,
            geometry=Point(0.0, 0.0).buffer(0.5),
            config_id=None,
            horizon=0.2,
            source="computed",
        )
        with pytest.raises(store.StoreError, match="attestation_records"):
            store.open_edge(conn, "DECLARED", "dec_0", "env_0", 0.0)
    finally:
        conn.close()


def test_node_counts_names_every_kind_even_where_the_table_is_absent(
    tmp_path: Path,
) -> None:
    """A missing key is indistinguishable from a genuine zero, so there are none.

    The fact a zero here does *not* carry — whether a record stream was offered
    — is not carried by a row count in either encoding, because an empty table
    counts zero too. `meta[attestation_records]` carries it, and the assertion
    below is that it still does.
    """
    csv, records = _held_attested(tmp_path)

    without = _build(csv, tmp_path / "without.sqlite")
    assert set(without.nodes) == set(store.NODE_TABLES)
    assert without.nodes["Declaration"] == 0
    assert without.nodes["Verdict"] == 0
    assert _meta(tmp_path / "without.sqlite")[graph.META_ATTESTATION_RECORDS] == "absent"

    with_records = _build(csv, tmp_path / "with.sqlite", records=records)
    assert set(with_records.nodes) == set(store.NODE_TABLES)
    assert with_records.nodes["Declaration"] == len(records.declarations)
    assert with_records.nodes["Verdict"] == len(records.verdicts)
    assert _meta(tmp_path / "with.sqlite")[graph.META_ATTESTATION_RECORDS] == "present"


def test_the_record_tables_follow_the_record_stream_and_nothing_else(
    tmp_path: Path,
) -> None:
    """`record_tables` is exactly `records is not None`, on both sides.

    Including the case that is *not* a saving and must not become one: a build
    handed an empty record stream keeps its tables, because "produced none" is a
    statement the artifact makes and an absent table is not that statement.
    """
    csv, records = _held_attested(tmp_path)
    cases = {
        "absent.sqlite": (None, False),
        "empty.sqlite": (AttestationRecords(declarations=(), verdicts=()), True),
        "full.sqlite": (records, True),
    }
    for name, (given, expected) in cases.items():
        out = tmp_path / name
        _build(csv, out, records=given)
        conn = store.connect(out)
        try:
            assert store.has_record_tables(conn) is expected, name
        finally:
            conn.close()


# --------------------------------------------------------------------------
# THE SURROGATE KEYS (issue #55).
#
# Node identity moved into the `node` table, every join and index carries the
# INTEGER surrogate, and `envelope_hash` is 32 raw bytes rather than 64 hex
# characters. It is a *storage* change, and the tests below are the ones that
# fail if it ever stops being only that: the canonical serialization, the four
# tamper modes, and the readable identifiers every report cites.
# --------------------------------------------------------------------------


def test_a_record_signed_before_the_change_still_verifies_after_it(
    tmp_path: Path,
) -> None:
    """**THE NEGATIVE FOR THE WHOLE CHANGE.** The MAC preimage must not move.

    A declaration and a verdict are signed, persisted through the new encoding,
    read back and verified under the keys that signed them. If the surrogate
    keys, the BLOB hash or the `declaration_key` join had disturbed a single
    field of either record — a re-rendered float, a re-serialized polygon, a
    `declaration_id` reconstructed from the wrong side of a join — the MAC would
    be over different bytes and this would say INVALID.

    It is checked field by field as well as by the MAC, because the two failures
    are different: a MAC that still verifies over a record whose fields moved
    would mean the signature covers less than it claims to.
    """
    csv, records = _held_attested(tmp_path)
    declaration = records.declarations[0]
    verdict = next(v for v in records.verdicts if v.declaration_id is not None)
    clamp = next(
        (v for v in records.verdicts if v.clamped_envelope is not None), None
    )

    conn = store.create(tmp_path / "signed.sqlite", record_tables=True)
    try:
        for record in records.declarations:
            store.insert_declaration(conn, record)
        for record in records.verdicts:
            store.insert_verdict(conn, record)
        conn.commit()
        read_declarations = store.read_declarations(conn)
        read_verdicts = store.read_verdicts(conn)
    finally:
        conn.close()

    by_id = {d.declaration_id: d for d in read_declarations}
    assert by_id[declaration.declaration_id] == declaration
    assert (
        verify_declaration(
            by_id[declaration.declaration_id], FIXTURE_KEYRING.key("policy")
        ).state
        is MacState.VALID
    )

    verdicts_by_id = {v.verdict_id: v for v in read_verdicts}
    assert verdicts_by_id[verdict.verdict_id] == verdict
    # The one field that now travels through a join rather than a column.
    assert (
        verdicts_by_id[verdict.verdict_id].declaration_id == verdict.declaration_id
    )
    assert (
        verify_verdict(
            verdicts_by_id[verdict.verdict_id], FIXTURE_KEYRING.key("enforcement")
        ).state
        is MacState.VALID
    )

    # Every record of both chains, not only the two named above: one record
    # surviving the round trip says nothing about the field a rarer one carries.
    assert len(read_declarations) == len(records.declarations)
    assert len(read_verdicts) == len(records.verdicts)
    assert read_declarations == sorted(
        records.declarations, key=lambda d: (d.seq, d.declaration_id)
    )
    assert read_verdicts == sorted(
        records.verdicts, key=lambda v: (v.seq, v.verdict_id)
    )
    if clamp is not None:
        # The WKB the record was signed with, byte for byte — not a second
        # rendering of the same region, which is the same polygon and a
        # different preimage.
        assert (
            verdicts_by_id[clamp.verdict_id].clamped_envelope
            == clamp.clamped_envelope
        )


def test_the_four_tamper_modes_are_still_detected(tmp_path: Path) -> None:
    """**THE NEGATIVE FOR THE ENCODING.** Issue #49's four faults, after #55.

    An encoding change is exactly where a tamper check quietly stops working:
    the tool now addresses rows by surrogate key, the record ids come out of a
    join, and `--delete` removes a record row while deliberately leaving its
    identity behind. Each of the four is applied to a copy of a real attested
    artifact and the walk must come back BROKEN — the point is not that the
    tool runs, it is that verification says no.

    `tests/test_chain.py` owns these four faults in full detail. This is the
    same four asserted against the *storage* change, and it lives here because
    what it is guarding is the schema.
    """
    from reg.chain import ChainState, tamper, verify_chain

    csv, records = _held_attested(tmp_path, n_frames=12)
    out = tmp_path / "attested.sqlite"
    _build(csv, out, records=records)

    conn = store.connect(out)
    try:
        assert verify_chain(conn, FIXTURE_KEYRING).state is ChainState.VERIFIED, (
            "precondition failed: the untampered artifact does not verify, so a "
            "BROKEN verdict below would prove nothing"
        )
    finally:
        conn.close()

    faults = {
        "field": "declaration:first:horizon=9.5",
        "mac": f"declaration:first:mac={'0' * 64}",
        "prev_hash": f"verdict:last:prev_hash={'0' * 64}",
        "delete": "verdict:last:delete",
    }
    for name, spec in faults.items():
        copy = tmp_path / f"tampered-{name}.sqlite"
        report = tamper(out, copy, spec)
        conn = store.connect(copy)
        try:
            result = verify_chain(conn, FIXTURE_KEYRING)
        finally:
            conn.close()
        assert result.state is ChainState.BROKEN, f"{name} went undetected"
        # And the failure names the record, which is what makes it usable. The
        # deleted record is the one that depends on `node` outliving the row:
        # its identity is gone from `verdict` and the FOLLOWS edge left pointing
        # at it can still say which record is missing.
        named = {f.record_id for f in result.failures if f.record_id is not None}
        assert report.record_id in named, f"{name} did not name the record"


def test_the_edge_table_holds_no_identifier_text(tmp_path: Path) -> None:
    """The change, asserted structurally rather than assumed from a byte count.

    Every edge endpoint is an INTEGER, and the identifier it resolves to is in
    `node` exactly once. A regression that put the text back would still pass
    every query test in this file — the answers would be identical — and would
    silently undo the whole of issue #55, so the shape is checked directly.
    """
    csv, records = _held_attested(tmp_path)
    out = tmp_path / "shape.sqlite"
    _build(csv, out, records=records)

    conn = store.connect(out)
    try:
        columns = {
            str(row["name"]): str(row["type"]).upper()
            for row in conn.execute("PRAGMA table_info(edge)")
        }
        assert columns["src_key"] == "INTEGER"
        assert columns["dst_key"] == "INTEGER"
        assert "src_id" not in columns and "dst_id" not in columns

        # Nothing of any width but an integer reached the endpoint columns.
        assert conn.execute(
            "SELECT count(*) AS n FROM edge WHERE typeof(src_key) != 'integer' "
            "OR typeof(dst_key) != 'integer'"
        ).fetchone()["n"] == 0

        # Every endpoint resolves, so no join over this table can come back
        # empty for a reason nobody can see.
        assert conn.execute(
            "SELECT count(*) AS n FROM edge e "
            "LEFT JOIN node s ON s.node_key = e.src_key "
            "LEFT JOIN node d ON d.node_key = e.dst_key "
            "WHERE s.node_id IS NULL OR d.node_id IS NULL"
        ).fetchone()["n"] == 0

        # And the three indexes issue #55 must not drop are all still there.
        indexes = {
            str(row["name"])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index' "
                "AND tbl_name = 'edge'"
            )
        }
        assert {"edge_by_layer", "edge_by_type_dst", "edge_by_interval"} <= indexes
    finally:
        conn.close()


def test_the_envelope_hash_is_thirty_two_bytes_and_reads_back_as_hex(
    tmp_path: Path,
) -> None:
    """Stored narrow, handed back wide. The digest on the wire does not change.

    `reg.envelope.envelope_hash` returns hex, `insert_envelope` takes hex,
    `envelope_row` returns hex — and the column holds 32 bytes in between. The
    equality against a freshly computed digest is what makes this a round trip
    rather than an assertion that two spellings of an unknown value agree.
    """
    csv = _held_stream(tmp_path / "held.csv", 6)
    out = tmp_path / "held.sqlite"
    _build(csv, out)

    conn = store.connect(out)
    try:
        raw = conn.execute(
            "SELECT envelope_hash FROM envelope LIMIT 1"
        ).fetchone()["envelope_hash"]
        assert isinstance(raw, bytes)
        assert len(raw) == store.HASH_BYTES
    finally:
        conn.close()

    rows = _envelope_rows(out)
    assert rows
    for row in rows:
        digest = row["envelope_hash"]
        assert isinstance(digest, str)
        assert len(digest) == 2 * store.HASH_BYTES
        assert store.to_hash(digest).hex() == digest
        if row["geometry_wkb"] is not None:
            assert digest == envelope_hash(store.from_wkb(row["geometry_wkb"]))


def test_a_hash_that_is_not_a_full_width_digest_is_refused(seeded) -> None:
    """THE NEGATIVE for the codec. Each of these compares unequal to a real
    digest, so each one would read as "the envelope changed" on every frame and
    turn the retention rule off without erroring anywhere."""
    for bad, why in (
        ("abc", "not 32 bytes"),
        ("a1" * 16, "half width"),
        ("a1" * 33, "over width"),
        ("zz" * 32, "not hex"),
        (("a1" * 32).upper(), "uppercase, so it would not survive the round trip"),
    ):
        with pytest.raises(store.StoreError):
            store.to_hash(bad)
        with pytest.raises(store.StoreError):
            store.insert_envelope(
                seeded,
                f"env_{why}",
                envelope_hash=bad,
                area=0.25,
                geometry=Point(0.0, 0.0).buffer(0.5),
                config_id="cfg_0",
                horizon=0.2,
                source="computed",
            )
    with pytest.raises(store.StoreError, match="32"):
        store.from_hash(b"\x00" * 16)
    with pytest.raises(store.StoreError, match="from_hash"):
        store.from_hash("a1" * 32)  # type: ignore[arg-type]

    # And the schema refuses it too, not only the Python guard.
    with pytest.raises(sqlite3.IntegrityError):
        seeded.execute(
            "INSERT INTO envelope (envelope_key, envelope_hash, area, horizon, "
            "source, geometry_wkb) VALUES (98, X'00FF', 0.25, 0.2, 'computed', "
            "X'00')"
        )


def test_one_id_cannot_name_two_different_kinds_of_node(seeded) -> None:
    """THE NEGATIVE for the shared identity table.

    `node_id` is unique across every kind since issue #55, and it has to be: an
    edge endpoint resolves an id to one key, so two different things behind one
    id would merge two histories into an answer about neither. The refusal is
    loud; the state it prevents is silent.
    """
    with pytest.raises(store.StoreError, match="already the id of a"):
        store.insert_entity(seeded, "cfg_0", "crate", geometry=Point(3.0, 0.0).buffer(0.2))
    with pytest.raises(store.StoreError, match="already the id of a"):
        store.insert_robot_config(seeded, "env_0", "0.0,0.0", "0.0,0.0")
    # And nothing was half-written: the RobotConfig is still a RobotConfig.
    assert store.node_key(seeded, "cfg_0") is not None
    assert (
        seeded.execute(
            "SELECT count(*) AS n FROM entity WHERE entity_key = ?",
            (store.node_key(seeded, "cfg_0"),),
        ).fetchone()["n"]
        == 0
    )


def test_node_key_refuses_to_resolve_an_id_the_artifact_never_held(seeded) -> None:
    """`None`, and never a plausible integer. `0` is a usable `node_key`, so an
    unresolved id that fell back to it would attach an edge to whichever node
    happened to be first."""
    assert store.node_key(seeded, "nothing_here") is None
    assert store.node_id_of(seeded, 999_999) is None
    assert store.node_key(seeded, "cfg_0") == store.node_key(seeded, "cfg_0")
    assert store.node_id_of(seeded, store.node_key(seeded, "cfg_0")) == "cfg_0"


def test_dropping_a_node_kind_takes_its_identity_with_it(tmp_path: Path) -> None:
    """`drop_nodes` is for `reg.bench`'s coarser views, and it must not leave
    identity rows behind for nodes the view no longer holds — a view that did
    would measure as larger than the view is, which is the one number the
    resolution curve exists to report."""
    csv = _held_stream(tmp_path / "held.csv", 6)
    out = tmp_path / "held.sqlite"
    _build(csv, out)

    conn = store.connect(out)
    try:
        before = conn.execute("SELECT count(*) AS n FROM node").fetchone()["n"]
        envelopes = store.node_counts(conn)["Envelope"]
        assert envelopes > 0, "precondition failed: nothing to drop"
        conn.execute("DELETE FROM edge")
        store.drop_nodes(conn, "Envelope")
        after = conn.execute("SELECT count(*) AS n FROM node").fetchone()["n"]
        assert after == before - envelopes
        assert store.node_counts(conn)["Envelope"] == 0
        with pytest.raises(store.StoreError, match="not a node kind"):
            store.drop_nodes(conn, "Timestep")
    finally:
        conn.close()
