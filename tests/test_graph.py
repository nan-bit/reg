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
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
import shapely
from shapely.geometry import Point, Polygon
from shapely.ops import unary_union

from reg import graph, store
from reg.envelope import compute_envelope, envelope_hash
from reg.graph import HUMAN_ENTITY_ID, GraphBuildError, build
from reg.kinematics import link_polygons
from reg.scenarios import SCENARIOS
from reg.sim import provenance, simulate
from reg.stream import read_frames, write_frames
from reg.tolerances import (
    DISTANCE_TOL_M,
    distance_bucket,
    quantize_area,
    quantize_time,
    simplify_geometry,
)
from reg.types import Obstacle, StateFrame
from reg.world import DEMO_WORLD

LIMITS = DEMO_WORLD.limits
HUMAN_RADIUS = DEMO_WORLD.human_radius

#: The seed every scenario stream in this file is generated at. Stated once
#: rather than passed as a literal: `reg.sim` records it in the provenance block
#: and a test that used a different one per call would be comparing two runs.
SIM_SEED = 0

#: 50 Hz, the rate the scenarios are generated at.
DT = 0.02

#: One static obstacle, well clear of the arm's 0.95 m of body.
OBSTACLE = Obstacle(entity_id="obs_a", kind="crate", cx=1.6, cy=1.2, radius=0.25)

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
    params = {**_FAST, **overrides}
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
    # INTERSECTS and no CONTACT: both are far outside a 0.1 s envelope.
    assert result.edges == {
        "HAS_ENVELOPE": 1,
        "INTERSECTS": 0,
        "SEPARATION": 2,
        "CONTACT": 0,
    }
    # And the nodes those edges anchor, once each — not per frame. There is no
    # `Timestep` kind to check: issue #29 removed it, and its absence from
    # `store.NODE_TABLES` is asserted in `test_there_is_no_per_frame_node_kind`.
    assert result.nodes == {"Envelope": 1, "RobotConfig": 1, "Entity": 2}


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
    # at 12 frames and at 240.
    assert result.nodes == {"Envelope": 2, "RobotConfig": 2, "Entity": 2}
    assert result.edges == {
        "HAS_ENVELOPE": 2,
        "INTERSECTS": 0,
        "SEPARATION": 2,
        "CONTACT": 0,
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
        human_radius=scn.world.human_radius,
        **_FAST,
    )
    b = build(
        fine,
        tmp_path / f"{name}_fine.sqlite",
        scn.world.limits,
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

    `HAS_ENVELOPE` is Layer A because an envelope comes from proprioception and
    actuation limits alone. Everything naming an entity is Layer B, because where
    an entity is comes from perception in any real system.
    """
    frames = [_frame(i, (2.4 - 0.1 * i, 0.0)) for i in range(15)]
    csv = _write_stream(tmp_path / "walk.csv", frames)
    _build(csv, tmp_path / "walk.sqlite")

    rows = _edges(tmp_path / "walk.sqlite")
    assert rows
    for row in rows:
        assert row["layer"] in ("A", "B")
        assert row["layer"] == store.layer_of(row["type"])
    assert {r["type"] for r in rows if r["layer"] == "A"} == {"HAS_ENVELOPE"}
    assert {r["type"] for r in rows if r["layer"] == "B"} <= {
        "INTERSECTS",
        "SEPARATION",
        "CONTACT",
    }


def test_layer_b_is_exactly_the_entity_naming_edges() -> None:
    """The vocabulary itself, independent of any run. A new edge type added
    without a layer decision fails here rather than in a query months later."""
    for edge_type, spec in store.EDGE_SPECS.items():
        expected = "B" if "Entity" in (spec.src_kind, spec.dst_kind) else "A"
        assert spec.layer == expected, (
            f"{edge_type} touches {spec.src_kind}->{spec.dst_kind} but is tagged "
            f"layer {spec.layer}. An edge naming an entity depends on perception."
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
        entity_row = conn.execute(
            "SELECT * FROM entity WHERE entity_id = ?", (OBSTACLE.entity_id,)
        ).fetchone()
        human_row = conn.execute(
            "SELECT * FROM entity WHERE entity_id = ?", (HUMAN_ENTITY_ID,)
        ).fetchone()
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
        build(csv, tmp_path / "held.sqlite", LIMITS, human_radius=bad_radius, **_FAST)


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
    conn = store.create(tmp_path / "store.sqlite")
    store.insert_robot_config(conn, "cfg_0", "0.000000,0.000000", "0.000000,0.000000")
    store.insert_envelope(
        conn,
        "env_0",
        envelope_hash="abc",
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
        store.open_edge(seeded, "HAS_ENVELOPE", "cfg_0", "env_0", 1.0, t_end=0.5)


def test_the_schema_itself_refuses_a_backwards_interval(seeded) -> None:
    """Not only the Python guard: an interval that runs backwards matches no
    time window, so it must be impossible to get into the file at all."""
    with pytest.raises(sqlite3.IntegrityError):
        seeded.execute(
            "INSERT INTO edge (type, layer, src_kind, src_id, dst_kind, dst_id, "
            "t_start, t_end) VALUES ('HAS_ENVELOPE','A','RobotConfig','cfg_0',"
            "'Envelope','env_0', 1.0, 0.0)"
        )


def test_the_schema_refuses_an_untagged_layer(seeded) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        seeded.execute(
            "INSERT INTO edge (type, layer, src_kind, src_id, dst_kind, dst_id, "
            "t_start, t_end) VALUES ('HAS_ENVELOPE','?','RobotConfig','cfg_0',"
            "'Envelope','env_0', 0.0, 1.0)"
        )


def test_extending_an_edge_backwards_is_refused(seeded) -> None:
    edge_id = store.open_edge(seeded, "HAS_ENVELOPE", "cfg_0", "env_0", 0.0)
    store.extend_edge(seeded, edge_id, 2.0)
    with pytest.raises(store.StoreError, match="backwards"):
        store.extend_edge(seeded, edge_id, 1.0)


def test_an_unknown_edge_type_is_refused(seeded) -> None:
    """Not a default layer and not a silent skip: adding an edge type is a
    decision about which layer it belongs to."""
    with pytest.raises(store.StoreError, match="not an edge type"):
        store.layer_of("DECLARED")
    with pytest.raises(store.StoreError, match="not an edge type"):
        store.open_edge(seeded, "DECLARED", "cfg_0", "env_0", 0.0)


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
            envelope_hash="def",
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
    conn = store.connect(path)
    try:
        return list(conn.execute("SELECT * FROM envelope").fetchall())
    finally:
        conn.close()


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
            "FROM edge JOIN envelope e ON e.envelope_id = edge.dst_id "
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
                "SELECT t_start FROM edge WHERE type = 'HAS_ENVELOPE' AND dst_id = ?",
                (envelope_id,),
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
                "edge.dst_id = e.envelope_id WHERE edge.type = 'HAS_ENVELOPE' "
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
        csv, out, world.limits, human_radius=world.human_radius, **_FAST
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
    build(csv, out, scn.world.limits, human_radius=scn.world.human_radius, **_FAST)

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
    # Every endpoint kind in the vocabulary must be a table that exists.
    for edge_type, spec in store.EDGE_SPECS.items():
        assert spec.src_kind in store.NODE_TABLES, edge_type
        assert spec.dst_kind in store.NODE_TABLES, edge_type


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
            "SELECT t_start FROM edge WHERE type = 'HAS_ENVELOPE' AND dst_id IN "
            "(SELECT envelope_id FROM envelope WHERE geometry_wkb IS NULL) "
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
            "SELECT edge.t_start AS t_start, e.config_id AS config_id FROM envelope e "
            "JOIN edge ON edge.dst_id = e.envelope_id "
            "WHERE e.geometry_wkb IS NULL AND edge.type = 'HAS_ENVELOPE' "
            "ORDER BY edge.t_start"
        ).fetchone()
        assert row is not None, "precondition failed: nothing was discarded"
        conn.execute(
            "DELETE FROM robot_config WHERE config_id = ?", (row["config_id"],)
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
            envelope_hash="fed",
            area=0.25,
            geometry=None,
            config_id=None,
            horizon=0.2,
            source="computed",
        )
    with pytest.raises(sqlite3.IntegrityError):
        seeded.execute(
            "INSERT INTO envelope (envelope_id, envelope_hash, area, horizon, "
            "source) VALUES ('env_empty', 'fed', 0.25, 0.2, 'computed')"
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
        envelope_hash="late",
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
    conn = store.create(path)
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
    relationships occurred'."""
    with pytest.raises(store.StoreError, match="not an edge type"):
        store.read_edges(seeded, edge_type="FOLLOWS")


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
        ]
    )
    assert code == 0
    assert out.exists()
    assert "frames=8" in capsys.readouterr().out
    assert _edges(out)


def test_cli_refuses_a_stream_that_does_not_say_what_produced_it(
    tmp_path: Path, capsys
) -> None:
    """The limits and the human radius are not in the stream's columns. Without
    the provenance block there is nothing to build a graph from without
    inventing both, and silence is not a reading of 'the defaults were used'."""
    csv = _write_stream(
        tmp_path / "bare.csv", [_frame(i, (2.0, 0.0)) for i in range(4)], scenario=None
    )
    code = graph.main(["build", str(csv), "--out", str(tmp_path / "bare.sqlite")])
    assert code == graph.EXIT_USAGE
    assert "provenance" in capsys.readouterr().err


def test_cli_refuses_an_unknown_scenario(tmp_path: Path, capsys) -> None:
    csv = _write_stream(
        tmp_path / "odd.csv",
        [_frame(i, (2.0, 0.0)) for i in range(4)],
        scenario="not_a_scenario",
    )
    code = graph.main(["build", str(csv), "--out", str(tmp_path / "odd.sqlite")])
    assert code == graph.EXIT_USAGE
    assert "does not know" in capsys.readouterr().err


def test_cli_requires_an_output_path(tmp_path: Path) -> None:
    csv = _held_stream(tmp_path / "held.csv", 4)
    with pytest.raises(SystemExit) as excinfo:
        graph.main(["build", str(csv)])
    assert excinfo.value.code == graph.EXIT_USAGE
