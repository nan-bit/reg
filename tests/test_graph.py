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

Envelopes are computed with deliberately coarse parameters throughout (`_FAST`).
Cost is linear in `n_samples * horizon / substep_dt` and these tests are about
interval bookkeeping, not about envelope fidelity — `tests/test_envelope.py` owns
that. The parameters are passed explicitly at every call so that no test here
depends on a default staying put.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pytest
import shapely
from shapely.geometry import Point, Polygon
from shapely.ops import unary_union

from reg import graph, store
from reg.envelope import compute_envelope
from reg.graph import HUMAN_ENTITY_ID, GraphBuildError, build
from reg.kinematics import link_polygons
from reg.stream import write_frames
from reg.tolerances import (
    DISTANCE_TOL_M,
    distance_bucket,
    quantize_time,
    simplify_geometry,
)
from reg.types import Obstacle, StateFrame
from reg.world import DEMO_WORLD

LIMITS = DEMO_WORLD.limits
HUMAN_RADIUS = DEMO_WORLD.human_radius

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
    # And the nodes those edges anchor, once each — not per frame.
    assert result.nodes["Timestep"] == 1
    assert result.nodes["Envelope"] == 1
    assert result.nodes["RobotConfig"] == 1
    assert result.nodes["Entity"] == 2


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
    precondition on the HAS_ENVELOPE count is asserted, because if the envelope
    ever stopped changing this test would pass while proving nothing.
    """
    n_frames = 12
    frames = [
        _frame(i, (2.0, 0.0), q=(1e-6 * i, 0.0), qd=(0.0, 0.0))
        for i in range(n_frames)
    ]
    csv = _write_stream(tmp_path / "creep.csv", frames)
    out = tmp_path / "creep.sqlite"
    _build(csv, out)

    assert len(_edges(out, edge_type="HAS_ENVELOPE")) == n_frames, (
        "precondition failed: the envelope did not change every frame, so this "
        "test says nothing about relationships outliving envelopes."
    )
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
    store.insert_timestep(conn, "ts_0", 0, 0.0)
    store.insert_envelope(
        conn,
        "env_0",
        envelope_hash="abc",
        area=0.25,
        geometry=Point(0.0, 0.0).buffer(0.5),
        horizon=0.2,
        source="computed",
    )
    store.insert_entity(conn, "obs_a", "crate", geometry=Point(2.0, 0.0).buffer(0.25))
    store.insert_robot_config(conn, "cfg_0", "0.000000,0.000000", "0.000000,0.000000")
    yield conn
    conn.close()


def test_a_backwards_interval_is_refused(seeded) -> None:
    with pytest.raises(store.StoreError, match="backwards"):
        store.open_edge(seeded, "HAS_ENVELOPE", "ts_0", "env_0", 1.0, t_end=0.5)


def test_the_schema_itself_refuses_a_backwards_interval(seeded) -> None:
    """Not only the Python guard: an interval that runs backwards matches no
    time window, so it must be impossible to get into the file at all."""
    with pytest.raises(sqlite3.IntegrityError):
        seeded.execute(
            "INSERT INTO edge (type, layer, src_kind, src_id, dst_kind, dst_id, "
            "t_start, t_end) VALUES ('HAS_ENVELOPE','A','Timestep','ts_0',"
            "'Envelope','env_0', 1.0, 0.0)"
        )


def test_the_schema_refuses_an_untagged_layer(seeded) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        seeded.execute(
            "INSERT INTO edge (type, layer, src_kind, src_id, dst_kind, dst_id, "
            "t_start, t_end) VALUES ('HAS_ENVELOPE','?','Timestep','ts_0',"
            "'Envelope','env_0', 0.0, 1.0)"
        )


def test_extending_an_edge_backwards_is_refused(seeded) -> None:
    edge_id = store.open_edge(seeded, "HAS_ENVELOPE", "ts_0", "env_0", 0.0)
    store.extend_edge(seeded, edge_id, 2.0)
    with pytest.raises(store.StoreError, match="backwards"):
        store.extend_edge(seeded, edge_id, 1.0)


def test_an_unknown_edge_type_is_refused(seeded) -> None:
    """Not a default layer and not a silent skip: adding an edge type is a
    decision about which layer it belongs to."""
    with pytest.raises(store.StoreError, match="not an edge type"):
        store.layer_of("DECLARED")
    with pytest.raises(store.StoreError, match="not an edge type"):
        store.open_edge(seeded, "DECLARED", "ts_0", "env_0", 0.0)


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
            horizon=0.2,
            source="guessed",
        )


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
