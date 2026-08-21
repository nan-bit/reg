"""The layer boundary, tested rather than asserted in a comment.

docs/plan.md calls the Layer A / Layer B split the single most important
structural property in the codebase. A property that important gets a test that
fails when it is broken — otherwise the first agent in a hurry adds `human_pos`
to `ProprioState` and every claim in Claim 3 quietly becomes false while every
other test stays green.

THE SECOND INPUT (issue #84)
----------------------------
Those field-name tests guard the envelope's *state* argument, and the envelope
has two arguments. `Limits` names nothing outside the robot either — `qd_max` is
as innocent a field name as there is — and under ISO/TS 15066 speed-and-separation
monitoring its value is a function of a *measured* separation distance. A taint
that arrives in a value cannot be caught by a test that reads names, so the
provenance is carried explicitly as `Limits.source` and the tests for it are the
back half of this file: the mapping, the edge tag it produces end to end, and the
two refusals — a `Limits` that does not say where it came from, and an artifact
that does not either.
"""

from __future__ import annotations

import dataclasses
import sqlite3
from pathlib import Path

import numpy as np
import pytest
from shapely.geometry import Point

from reg import graph, store
from reg.envelope import envelope_hash, envelope_layer
from reg.stream import write_frames
from reg.types import Limits, LimitSource, Obstacle, ProprioState, StateFrame

# Anything matching one of these in a Layer A structure means the world leaked in.
WORLD_WORDS = ("human", "obstacle", "object", "entity", "goal", "target", "scene")

#: The fixture arm, twice: identical numbers, opposite provenance. Identical on
#: purpose — it is what makes the tests below differential. Any layer difference
#: they find cannot be a difference in geometry, because there is none.
_BOUNDS = {
    "q_min": np.array([-np.pi, -2.6]),
    "q_max": np.array([np.pi, 2.6]),
    "qd_max": np.array([2.0, 2.5]),
    "qdd_max": np.array([8.0, 10.0]),
    "link_lengths": np.array([0.5, 0.4]),
    "link_radius": 0.05,
}
DATASHEET_LIMITS = Limits(**_BOUNDS, source=LimitSource.PROPRIOCEPTIVE)
#: The ISO/TS 15066 case: the same `qd_max`, but arrived at by capping the
#: commanded speed with a separation distance somebody's perceiver measured.
SSM_LIMITS = Limits(**_BOUNDS, source=LimitSource.DERIVED)

#: Coarse envelope parameters — 4 samples is the corner count for a two-link
#: arm. These tests are about the layer tag, not envelope fidelity.
_FAST = {"horizon": 0.1, "n_samples": 4, "seed": 0, "substep_dt": 0.05}
_HUMAN_RADIUS = 0.3


def test_propriostate_cannot_see_the_world() -> None:
    """The negative test: no Layer A field may name anything outside the robot."""
    for f in dataclasses.fields(ProprioState):
        assert not any(w in f.name.lower() for w in WORLD_WORDS), (
            f"ProprioState.{f.name} names something outside the robot. The "
            "envelope is Layer A and must not be able to see the scene; if it "
            "can, the sufficiency argument in Claim 3 does not hold."
        )


def test_propriostate_fields_are_exactly_the_allowed_set() -> None:
    """Stricter than the word check: an allowlist, so a novel name still fails."""
    got = {f.name for f in dataclasses.fields(ProprioState)}
    assert got == {"t", "q", "qd"}, (
        f"ProprioState fields changed to {sorted(got)}. Widening Layer A is a "
        "decision about what this project can claim, not a refactor — update "
        "docs/sufficiency.md in the same change or revert."
    )


def test_proprio_narrows_a_frame_and_drops_layer_b() -> None:
    frame = StateFrame(
        t=1.5,
        q=np.array([0.1, 0.2]),
        qd=np.array([0.0, 0.0]),
        human_pos=np.array([1.0, 2.0]),
        human_vel=np.array([0.1, 0.0]),
        objects=(Obstacle("obs_0", "box", 1.0, 1.0, 0.2),),
    )
    p = frame.proprio()
    assert p.t == frame.t
    assert np.array_equal(p.q, frame.q)
    # The point of the narrowing: what comes out cannot reach the human at all.
    assert not hasattr(p, "human_pos")


def test_records_are_frozen() -> None:
    """An audit record that can be mutated after the fact is not evidence."""
    p = ProprioState(t=0.0, q=np.array([0.0]), qd=np.array([0.0]))
    with pytest.raises(dataclasses.FrozenInstanceError):
        p.t = 1.0  # type: ignore[misc]


def test_limits_reject_a_per_joint_mismatch() -> None:
    """Negative test: a wrong-length bound must fail loudly, not broadcast."""
    with pytest.raises(ValueError, match="per joint"):
        Limits(
            q_min=np.array([-3.14]),  # one joint
            q_max=np.array([3.14]),
            qd_max=np.array([2.0]),
            qdd_max=np.array([10.0]),
            link_lengths=np.array([0.5, 0.4]),  # but two links
            source=LimitSource.PROPRIOCEPTIVE,
        )


# --------------------------------------------------------------------------
# The envelope's second input: where the bounds came from (issue #84)
# --------------------------------------------------------------------------


def test_limits_cannot_be_built_without_saying_where_they_came_from() -> None:
    """Negative test: no default, so omitting it is a `TypeError` and not an `A`.

    The whole mechanism is that a caller has to write the provenance down. A
    default — any default — makes the caller who never considered it produce the
    same object as the one who considered it and concluded "datasheet", and no
    reader downstream can tell those apart.
    """
    with pytest.raises(TypeError, match="source"):
        Limits(**_BOUNDS)  # type: ignore[call-arg]


@pytest.mark.parametrize("bad", ["proprioceptive", None, 0, True])
def test_limits_refuse_a_source_that_is_not_a_limit_source(bad: object) -> None:
    """Negative test: the string that spells the clean value is not the clean value.

    `"proprioceptive"` is the most likely wrong thing to arrive here, and it is
    the most dangerous, because it looks right in a repr and compares equal to
    nothing. `None` is the other: it reads as "unspecified", and unspecified is
    exactly the state this field exists to make impossible.
    """
    with pytest.raises(TypeError, match="LimitSource"):
        Limits(**_BOUNDS, source=bad)  # type: ignore[arg-type]


def test_envelope_layer_follows_the_provenance_of_the_bounds() -> None:
    """The mapping, in one place: datasheet bounds are A, derived bounds are B."""
    assert envelope_layer(DATASHEET_LIMITS) == "A"
    assert envelope_layer(SSM_LIMITS) == "B"


def test_every_limit_source_has_a_layer_decision() -> None:
    """A new `LimitSource` with no layer decided must not fall through to 'A'.

    `envelope_layer` refuses an undecided source rather than guessing, but a
    refusal at runtime is a build that dies in the field. This is the same fact
    checked at the vocabulary level, so adding an enum member fails here first.
    """
    for source in LimitSource:
        assert envelope_layer(Limits(**_BOUNDS, source=source)) in ("A", "B")


def test_layer_of_refuses_the_edge_type_whose_layer_is_not_its_type() -> None:
    """Negative test: the type-only question has no answer for `HAS_ENVELOPE`.

    This is the shape of the original bug. A function that maps edge type to
    layer would answer "A" here, confidently and wrongly, for every artifact
    built under an SSM speed cap. It refuses instead, and `possible_layers`
    answers the question that *is* well-posed.
    """
    with pytest.raises(store.StoreError, match="not a property of its type"):
        store.layer_of("HAS_ENVELOPE")
    assert store.possible_layers("HAS_ENVELOPE") == {"A", "B"}
    # The types whose layer really is a property of the type still answer.
    assert store.layer_of("SEPARATION") == "B"
    assert store.possible_layers("SEPARATION") == {"B"}


# --------------------------------------------------------------------------
# End to end: the tag that lands in the artifact
# --------------------------------------------------------------------------


def _stream(path: Path) -> Path:
    """Six frames of a robot holding still, well clear of one obstacle."""
    frames = [
        StateFrame(
            t=i * 0.02,
            q=np.array([0.0, 0.0]),
            qd=np.array([0.0, 0.0]),
            human_pos=np.array([2.0, 0.0]),
            human_vel=np.array([0.0, 0.0]),
            objects=(Obstacle("obs_a", "crate", 1.6, 1.2, 0.25),),
        )
        for i in range(6)
    ]
    return write_frames(frames, path)


def _envelope_edges(artifact: Path) -> list[sqlite3.Row]:
    conn = store.connect(artifact)
    try:
        return store.read_edges(conn, edge_type="HAS_ENVELOPE")
    finally:
        conn.close()


def test_derived_limits_produce_a_layer_b_envelope_edge(tmp_path: Path) -> None:
    """THE TEST THIS ISSUE IS ABOUT (#84). Same robot, same run, opposite tag.

    Two builds differing in exactly one thing — whether the speed bound came off
    a datasheet or out of a perceiver — and the `HAS_ENVELOPE` edge changes
    layer. Before this, both builds wrote 'A' and the second one was a Layer B
    region carrying a Layer A tag, which no query, no `CHECK` constraint and no
    field-name test could see.

    Asserted as a difference rather than as two absolutes on purpose: a
    `layer` column hard-wired to either value passes half of this and fails the
    other half.
    """
    csv = _stream(tmp_path / "run.csv")

    clean = tmp_path / "datasheet.sqlite"
    graph.build(csv, clean, DATASHEET_LIMITS, human_radius=_HUMAN_RADIUS, **_FAST)
    tainted = tmp_path / "ssm.sqlite"
    graph.build(csv, tainted, SSM_LIMITS, human_radius=_HUMAN_RADIUS, **_FAST)

    clean_rows = _envelope_edges(clean)
    tainted_rows = _envelope_edges(tainted)
    assert clean_rows and tainted_rows
    assert {r["layer"] for r in clean_rows} == {"A"}
    assert {r["layer"] for r in tainted_rows} == {"B"}


def test_the_layer_moved_and_the_geometry_did_not(tmp_path: Path) -> None:
    """Provenance changes whose failure modes the answer inherits, not the answer.

    The gate on "no published figure moves": the two artifacts hold the same
    envelope, so a retention or compression number computed over either is the
    same number. If this ever fails, the provenance field has started changing
    geometry and the claim that it is bookkeeping is false.
    """
    csv = _stream(tmp_path / "run.csv")
    clean = tmp_path / "datasheet.sqlite"
    graph.build(csv, clean, DATASHEET_LIMITS, human_radius=_HUMAN_RADIUS, **_FAST)
    tainted = tmp_path / "ssm.sqlite"
    graph.build(csv, tainted, SSM_LIMITS, human_radius=_HUMAN_RADIUS, **_FAST)

    digests = []
    for artifact in (clean, tainted):
        conn = store.connect(artifact)
        try:
            digests.append(envelope_hash(graph.envelope_at(conn, 0.0)))
        finally:
            conn.close()
    assert digests[0] == digests[1]


def test_the_artifact_records_where_its_limits_came_from(tmp_path: Path) -> None:
    """It round-trips: `meta` says it, and the reconstructed `Limits` carries it.

    docs/lossiness.md Retained #10 keeps the limits so the geometry can be
    recomputed. The provenance has to travel with them for the same reason — a
    recomputed envelope inherits whatever the bounds inherited.
    """
    csv = _stream(tmp_path / "run.csv")
    for limits in (DATASHEET_LIMITS, SSM_LIMITS):
        artifact = tmp_path / f"{limits.source.value}.sqlite"
        graph.build(csv, artifact, limits, human_radius=_HUMAN_RADIUS, **_FAST)
        conn = store.connect(artifact)
        try:
            raw = store.get_meta(conn, graph.META_LIMITS_SOURCE)
            assert raw == limits.source.value
            assert graph._limits_from_meta(conn).source is limits.source
        finally:
            conn.close()


def test_an_artifact_that_does_not_record_its_provenance_is_could_not_evaluate(
    tmp_path: Path,
) -> None:
    """Negative test: a missing key is a refusal, never `PROPRIOCEPTIVE`.

    An artifact written before this key existed does not know whether its speed
    bound was a datasheet number or an SSM cap. Reading the absence as the clean
    value would let the one case this whole issue is about — a Layer B envelope
    quoted as Layer A evidence — be produced by *deleting a row*, which is the
    cheapest tamper there is.

    Both halves are asserted: that it refuses, and that what comes back is not a
    proprioceptive `Limits`. A refusal that some caller later wraps in a
    `try/except` returning a default would pass the first half alone.
    """
    csv = _stream(tmp_path / "run.csv")
    artifact = tmp_path / "run.sqlite"
    graph.build(csv, artifact, DATASHEET_LIMITS, human_radius=_HUMAN_RADIUS, **_FAST)

    conn = store.connect(artifact)
    try:
        conn.execute("DELETE FROM meta WHERE key = ?", (graph.META_LIMITS_SOURCE,))
        conn.commit()
        assert store.get_meta(conn, graph.META_LIMITS_SOURCE) is None

        with pytest.raises(graph.GraphQueryError, match=graph.META_LIMITS_SOURCE):
            graph._limits_from_meta(conn)
        # And through the query a reader actually calls, not only the helper.
        # Blanking the retained polygon is what puts `envelope_at` on the
        # recompute path — the path that needs the limits, and so the one where
        # a provenance nobody recorded would otherwise be invented.
        conn.execute("UPDATE envelope SET geometry_wkb = NULL")
        conn.commit()
        with pytest.raises(graph.GraphQueryError, match=graph.META_LIMITS_SOURCE):
            graph.envelope_at(conn, 0.0)
    finally:
        conn.close()


def test_an_unknown_provenance_string_is_refused(tmp_path: Path) -> None:
    """Negative test: a key nobody can parse is could-not-evaluate too.

    The sibling of the missing key. An unparsed payload is not a pass — a value
    like `"unknown"` sitting in the column must not resolve to anything, least of
    all to the permissive answer.
    """
    csv = _stream(tmp_path / "run.csv")
    artifact = tmp_path / "run.sqlite"
    graph.build(csv, artifact, DATASHEET_LIMITS, human_radius=_HUMAN_RADIUS, **_FAST)

    conn = store.connect(artifact)
    try:
        # Written past `put_meta`, which refuses to overwrite one artifact's
        # provenance with another's. The failure being modelled is a file that
        # arrived holding this value, not a build that wrote it.
        conn.execute(
            "UPDATE meta SET value = 'unknown' WHERE key = ?",
            (graph.META_LIMITS_SOURCE,),
        )
        conn.commit()
        with pytest.raises(graph.GraphQueryError, match="not a limit source"):
            graph._limits_from_meta(conn)
    finally:
        conn.close()


def test_an_envelope_edge_may_not_be_written_without_stating_its_layer(
    tmp_path: Path,
) -> None:
    """Negative test at the storage layer: the omission has no fallback.

    This is the last place the failure could be reintroduced. A caller that
    forgets the layer must get a refusal rather than an 'A' — if `open_edge`
    defaulted, every guarantee above would hold only for callers who remembered.
    """
    conn = store.create(tmp_path / "hand.sqlite", record_tables=False)
    try:
        store.insert_robot_config(
            conn, "cfg_0", "0.000000,0.000000", "0.000000,0.000000"
        )
        store.insert_envelope(
            conn,
            "env_0",
            envelope_hash="a1" * 32,
            area=0.25,
            geometry=Point(0.0, 0.0).buffer(0.5),
            config_id="cfg_0",
            horizon=0.1,
            source="computed",
        )

        with pytest.raises(store.StoreError, match="no default to fall back on"):
            store.open_edge(conn, "HAS_ENVELOPE", "cfg_0", "env_0", 0.0)
        with pytest.raises(store.StoreError, match="cannot be layer"):
            store.open_edge(conn, "HAS_ENVELOPE", "cfg_0", "env_0", 0.0, layer="C")
        # Both legal answers are accepted, so the refusal above is about the
        # omission and not about the argument being unusable.
        for layer in ("A", "B"):
            assert store.open_edge(
                conn, "HAS_ENVELOPE", "cfg_0", "env_0", 0.0, layer=layer
            )
    finally:
        conn.close()
