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

THE PROVENANCE THAT DECIDES NO LAYER (issue #149)
-------------------------------------------------
`BasePose` and `PoseSource` are new, additive, and nothing constructs one yet.
The precedent above is exactly what makes them dangerous: `Limits.source`
*selects* a layer, so the obvious next move is a `pose_layer` doing the same —
and it would hand back `A` for a dead-reckoned pose, which is a room-frame
answer wearing a Layer A tag. A room-frame pose is Layer B **structurally**
(docs/sufficiency.md §5.6), so the last section of this file asserts that no
such mapping exists anywhere in `reg/`, that the one mapping which does exist
refuses a pose, and that `ProprioState` cannot hold one. With no consumer
behind the type, those tests are the whole contract.

THE ONE WIDENING OF LAYER A (issue #150)
----------------------------------------
`ProprioState` held `{t, q, qd}` from the beginning. It now holds `base_vel` as
well — the base's *body-frame* velocity, which a wheel encoder measures — and
that is a decision about what this project can claim rather than a refactor, so
`LAYER_A_STATE_FIELDS` moved and `docs/sufficiency.md` §5.7 moved with it, in
this commit, because `test_propriostate_fields_are_exactly_the_allowed_set` is
written to make the two impossible to separate.

The base's room-frame **pose** did not come with it, and the tests below are
where that is enforced rather than asserted. It matters more here than anywhere
else in this file because **the word check cannot see it**: `x`, `y`, `theta`,
`base_x` and `base_pose` contain none of `WORLD_WORDS` and never will. So the
allowlist is the whole guard, and an allowlist is exactly the kind of check that
can rot into a tautology — which is why `layer_a_state_offenders` is a function
this file also feeds a state built to offend, and requires it to say no.
"""

from __future__ import annotations

import dataclasses
import importlib
import pkgutil
import re
import sqlite3
from pathlib import Path
from types import ModuleType

import numpy as np
import pytest
from shapely.geometry import Point

import reg
from reg import graph, store
from reg.identity import RunIdentity
from reg.envelope import envelope_hash, envelope_layer
from reg.stream import write_frames
from reg.types import (
    BasePose,
    BaseVelocity,
    Limits,
    LimitSource,
    Obstacle,
    PoseSource,
    ProprioState,
    StateFrame,
)

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
#: `identity` is required by `graph.build` since issue #83 — an artifact that
#: cannot say which robot or which shift cannot be handed to anyone. These
#: tests are about the Layer A/B boundary and not about identity, so they
#: declare one and move on.
_IDENTITY = RunIdentity.declare(
    run_start="2026-08-21T09:00:00Z",
    unit_id="unit-layer-boundary",
    operator_id="op-test",
)
_FAST = {
    "horizon": 0.1,
    "n_samples": 4,
    "seed": 0,
    "substep_dt": 0.05,
    "identity": _IDENTITY,
}
_HUMAN_RADIUS = 0.3


def test_propriostate_cannot_see_the_world() -> None:
    """The negative test: no Layer A field may name anything outside the robot."""
    for f in dataclasses.fields(ProprioState):
        assert not any(w in f.name.lower() for w in WORLD_WORDS), (
            f"ProprioState.{f.name} names something outside the robot. The "
            "envelope is Layer A and must not be able to see the scene; if it "
            "can, the sufficiency argument in Claim 3 does not hold."
        )


#: Everything Layer A is allowed to know, by name. Widened exactly once, in
#: issue #150, to add `base_vel` — a body-frame rate off a wheel encoder, which
#: names nothing outside the robot and is admitted on the argument that already
#: admits `qd`. `docs/sufficiency.md` §5.7 is the record of that decision.
LAYER_A_STATE_FIELDS = {"t", "q", "qd", "base_vel"}

#: Names a room-frame pose would arrive under. None of these is in
#: `WORLD_WORDS` and none can be — a pose is not a *thing in the world*, it is
#: the robot's relationship to one — so this list and the allowlist are the only
#: things standing between a `base_x` and Layer A.
POSE_FIELD_NAMES = frozenset(
    {"x", "y", "theta", "pose", "base_pose", "base_x", "base_y", "base_theta"}
)


def layer_a_state_offenders(state_type: type) -> list[str]:
    """Fields of `state_type` that Layer A may not hold, with the reason.

    A function rather than the body of one test, for the reason
    `pose_layer_offenders` is one: an allowlist checked only against the type it
    was written from can be shown to have *looked*, never to be able to *see*.
    The negative below drives this against states built to offend.

    Three ways in, because the dangerous one is not the obvious one:

    * a field **typed** as a room-frame pose, which the allowlist alone would
      wave through if somebody named it `base_vel`;
    * a field **named** for a pose, which the word check cannot catch;
    * anything else not on the allowlist, which is the catch-all that makes a
      novel name fail rather than a known-bad one.
    """
    offenders: list[str] = []
    for f in dataclasses.fields(state_type):
        where = f"{state_type.__name__}.{f.name}"
        if "BasePose" in str(f.type):
            offenders.append(f"{where}: typed as a room-frame pose")
        elif f.name.lower() in POSE_FIELD_NAMES:
            offenders.append(f"{where}: named for a room-frame pose")
        elif f.name not in LAYER_A_STATE_FIELDS:
            offenders.append(f"{where}: not in LAYER_A_STATE_FIELDS")
    return offenders


def test_propriostate_fields_are_exactly_the_allowed_set() -> None:
    """Stricter than the word check: an allowlist, so a novel name still fails."""
    got = {f.name for f in dataclasses.fields(ProprioState)}
    assert got == LAYER_A_STATE_FIELDS, (
        f"ProprioState fields changed to {sorted(got)}. Widening Layer A is a "
        "decision about what this project can claim, not a refactor — update "
        "docs/sufficiency.md in the same change or revert."
    )
    # Asserted through the function the negative below exercises, so that what
    # passes here is the same code that has been shown able to fail.
    assert layer_a_state_offenders(ProprioState) == []


def test_the_allowlist_catches_a_pose_smuggled_into_layer_a() -> None:
    """**THE NEGATIVE.** The word check cannot see a pose, so this must.

    Both shapes issue #150 names, fed to the scan and required to come back
    refused:

    * `base_x`, `base_y`, `base_theta` — a pose spelled out as floats. Innocent
      names, none of them in `WORLD_WORDS`, and three of them make a room-frame
      pose that every envelope downstream would then be computed against.
    * a `BasePose`-typed field wearing an allowed *name*. This is the one an
      allowlist on its own lets through, and it is not a contrived case: it is
      what a hurried edit to `proprio()` produces when the narrowing is
      "simplified" into passing the frame's pose along under the velocity's
      name.

    Without this test the assertion above is an absence nobody has shown the
    scan can detect: delete a branch of `layer_a_state_offenders` and it passes
    forever while the thing it guards walks in.
    """

    @dataclasses.dataclass(frozen=True)
    class SpelledOutPose:
        t: float
        q: np.ndarray
        qd: np.ndarray
        base_vel: object
        base_x: float
        base_y: float
        base_theta: float

    offenders = layer_a_state_offenders(SpelledOutPose)
    assert [o.split(":")[0] for o in offenders] == [
        "SpelledOutPose.base_x",
        "SpelledOutPose.base_y",
        "SpelledOutPose.base_theta",
    ], f"a pose spelled out as floats was not caught: {offenders}"

    @dataclasses.dataclass(frozen=True)
    class PoseUnderAnAllowedName:
        t: float
        q: np.ndarray
        qd: np.ndarray
        base_vel: BasePose | None  # the name is on the allowlist; the type is not

    offenders = layer_a_state_offenders(PoseUnderAnAllowedName)
    assert offenders == [
        "PoseUnderAnAllowedName.base_vel: typed as a room-frame pose"
    ], (
        "a BasePose-typed field passed the allowlist because its *name* was "
        f"allowed: {offenders}. The name half of this check cannot catch the "
        "type half, and this is the case where only the type is wrong."
    )


def test_the_allowlist_does_not_fire_on_the_field_it_was_widened_for() -> None:
    """And it must not cry wolf: `base_vel` holding a `BaseVelocity` is fine.

    The complement of the negative above. A scan that rejected the very field
    issue #150 added would be switched off within a week, and the widening is
    only meaningful if the type it admits actually gets through.
    """

    @dataclasses.dataclass(frozen=True)
    class WithBaseVelocity:
        t: float
        q: np.ndarray
        qd: np.ndarray
        base_vel: BaseVelocity | None

    assert layer_a_state_offenders(WithBaseVelocity) == []


def test_proprio_narrows_a_frame_and_drops_layer_b() -> None:
    frame = StateFrame(
        t=1.5,
        q=np.array([0.1, 0.2]),
        qd=np.array([0.0, 0.0]),
        human_pos=np.array([1.0, 2.0]),
        human_vel=np.array([0.1, 0.0]),
        base_vel=None,
        base_pose=None,
        objects=(Obstacle("obs_0", "box", 1.0, 1.0, 0.2),),
    )
    p = frame.proprio()
    assert p.t == frame.t
    assert np.array_equal(p.q, frame.q)
    # The point of the narrowing: what comes out cannot reach the human at all.
    assert not hasattr(p, "human_pos")


def test_proprio_drops_the_base_pose() -> None:
    """The same narrowing, for the field the word check cannot see (#150).

    `human_pos` is caught twice over — by name, by the allowlist, and by this —
    so it is the easy half. The base is the hard half, because the frame carries
    *both* halves of it and they go opposite ways: the body-frame velocity is
    Layer A and comes through, the room-frame pose is Layer B and must not.

    A pose that survived this call would not raise anywhere. It would sit on a
    `ProprioState`, be handed to `reg.envelope` with every other Layer A input,
    and produce a region that is correct, useful, and tagged `A` while depending
    on a localizer — the exact mislabelling `Limits.source` exists to stop,
    arriving through a different door (docs/sufficiency.md §5.6).
    """
    frame = StateFrame(
        t=0.5,
        q=np.array([0.1, 0.2]),
        qd=np.array([0.0, 0.0]),
        human_pos=np.array([1.0, 2.0]),
        human_vel=np.array([0.0, 0.0]),
        base_vel=BaseVelocity(vx=0.4, vy=0.0, omega=0.2),
        base_pose=BasePose(x=3.0, y=-1.0, theta=0.7, source=PoseSource.LOCALIZED),
    )
    narrowed = frame.proprio()

    # Layer A comes through, unchanged. Without this half the test would pass
    # for a `proprio()` that dropped the base entirely, which is a different
    # (and wrong) answer to issue #150.
    assert narrowed.base_vel == frame.base_vel

    # Layer B does not, by any route: not as a field, not as an attribute, and
    # not as a value hiding under another name.
    assert not hasattr(narrowed, "base_pose")
    assert "base_pose" not in {f.name for f in dataclasses.fields(narrowed)}
    # `is not`, not `!=`: two of these fields are numpy arrays, so `==` would
    # return an array and the assertion would be about a truth value nobody
    # meant. Identity is also the stronger question here — the pose must not be
    # reachable from the narrowed state at all, under any field's name.
    assert all(
        getattr(narrowed, f.name) is not frame.base_pose
        for f in dataclasses.fields(narrowed)
    )


def test_a_base_velocity_is_frozen_and_has_no_defaults() -> None:
    """The Layer A half of the base, on the same terms as `Limits` and `BasePose`.

    It is admitted to Layer A, which is exactly why it gets the discipline the
    rest of Layer A has rather than less of it: nothing here has a value a
    caller can be assumed to have meant, and a rate that can be edited after the
    fact is not evidence of how fast anything was going.
    """
    defaulted = [
        f.name
        for f in dataclasses.fields(BaseVelocity)
        if f.default is not dataclasses.MISSING
        or f.default_factory is not dataclasses.MISSING
    ]
    assert defaulted == []

    vel = BaseVelocity(vx=0.4, vy=0.0, omega=0.2)
    with pytest.raises(dataclasses.FrozenInstanceError):
        vel.vx = 0.0  # type: ignore[misc]

    # And it names nothing outside the robot — the check `ProprioState` itself
    # gets, applied to the type that is now reachable from it.
    for f in dataclasses.fields(BaseVelocity):
        assert not any(w in f.name.lower() for w in WORLD_WORDS)


@pytest.mark.parametrize(
    "bad", [(0.4, 0.0, 0.2), [0.4, 0.0, 0.2], 0.4, "0.4,0.0,0.2"]
)
def test_a_state_refuses_a_base_velocity_that_is_not_one(bad: object) -> None:
    """Negative test: `None` is the only way to say 'not recorded'.

    A bare triple is the likely wrong thing to arrive here and it is the
    dangerous one: it has the right three numbers in what looks like the right
    order, and nothing downstream would ever check that `vy` and `omega` had not
    been swapped — one is m/s and the other rad/s, and both are plausible.
    """
    with pytest.raises(TypeError, match="BaseVelocity"):
        ProprioState(  # type: ignore[arg-type]
            t=0.0, q=np.zeros(2), qd=np.zeros(2), base_vel=bad
        )


def test_a_state_cannot_be_built_without_saying_whether_it_records_a_base() -> None:
    """Negative test: no default, so omitting `base_vel` is a `TypeError`.

    The `Limits.source` argument once more. The tempting default here is `None`
    itself — it reads as harmless, since it is what every fixed-base call site
    passes. But then the caller who never considered the base produces the same
    state as the one who considered it and recorded that this run has no base
    reading, and the whole content of the widening is that those are different
    facts about an artifact.
    """
    with pytest.raises(TypeError, match="base_vel"):
        ProprioState(t=0.0, q=np.zeros(2), qd=np.zeros(2))  # type: ignore[call-arg]


def test_a_frame_refuses_a_base_pose_that_is_not_one() -> None:
    """Negative test, Layer B side: a bare triple carries no `PoseSource`.

    The room-frame pose is the field with a provenance that must be stated
    (issue #149), so the way it must not be possible to build one is by handing
    `StateFrame` three floats and having them read as a pose nobody sourced.
    """
    with pytest.raises(TypeError, match="BasePose"):
        StateFrame(
            t=0.0,
            q=np.zeros(2),
            qd=np.zeros(2),
            human_pos=np.zeros(2),
            human_vel=np.zeros(2),
            base_vel=None,
            base_pose=(1.0, 2.0, 0.3),  # type: ignore[arg-type]
        )


def test_records_are_frozen() -> None:
    """An audit record that can be mutated after the fact is not evidence."""
    p = ProprioState(t=0.0, q=np.array([0.0]), qd=np.array([0.0]), base_vel=None)
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
            link_radius=0.05,
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


def test_limits_cannot_be_built_without_a_link_radius() -> None:
    """Negative test: the same argument, applied to the field that had a default.

    `link_radius` carried `0.05` until issue #115, which is the one number on
    `Limits` no call site had ever chosen. It is the body's half-width, the
    bound that fixes the sampling step, and the term added to
    `sum(link_lengths)` in the disc `reg.enforce` tests a declaration against —
    so the caller who never considered it produced the same object, and the same
    verdicts, as the caller who considered it and concluded 5 cm. The value did
    not move; the fiat did.
    """
    without_radius = {k: v for k, v in _BOUNDS.items() if k != "link_radius"}
    with pytest.raises(TypeError, match="link_radius"):
        Limits(  # type: ignore[call-arg]
            **without_radius, source=LimitSource.PROPRIOCEPTIVE
        )


def test_no_field_of_limits_has_a_default() -> None:
    """The invariant behind both negative tests above, stated once.

    Naming the two fields individually would not catch the third one somebody
    adds with a plausible number attached. Every field on `Limits` is either a
    property of the robot or the provenance of one, and there is no value for
    any of them that a caller can be assumed to have meant.
    """
    defaulted = [
        f.name
        for f in dataclasses.fields(Limits)
        if f.default is not dataclasses.MISSING
        or f.default_factory is not dataclasses.MISSING
    ]
    assert defaulted == []


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
            base_vel=None,
            base_pose=None,
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
            outer_area=0.5,
            outer_radius=0.95,
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


# --------------------------------------------------------------------------
# The base pose: a provenance that records a horizon and decides no layer (#149)
# --------------------------------------------------------------------------
#
# Nothing in `reg/` constructs a `BasePose` yet — issue #149 is purely additive
# and the three issues after it wire it in. That makes this section the only
# thing holding the contract: an unexercised type drifts, and the direction it
# would drift in is known, because `Limits.source` sits ten lines above it and
# *does* select a layer. These tests are the difference between "Layer B by
# docstring" and "Layer B by something that fails".

_POSE = {"x": 1.2, "y": -0.4, "theta": 0.3}


def test_base_pose_cannot_be_built_without_saying_where_it_came_from() -> None:
    """Negative test: no default, so omitting the provenance is a `TypeError`.

    The `Limits.source` argument, applied unchanged: a default would make the
    caller who never considered provenance produce the same object as the one
    who considered it and concluded "dead reckoning", and nothing downstream
    could tell those apart.
    """
    with pytest.raises(TypeError, match="source"):
        BasePose(**_POSE)  # type: ignore[call-arg]


@pytest.mark.parametrize("bad", ["localized", "dead_reckoned", None, 0, True])
def test_base_pose_refuses_a_source_that_is_not_a_pose_source(bad: object) -> None:
    """Negative test: the string that spells a value is not the value.

    Same failure as `Limits.source` refusing `"proprioceptive"` — it looks right
    in a repr and compares equal to no member — and `None`, which reads as
    "unspecified" when unspecified is the state the field exists to forbid.
    """
    with pytest.raises(TypeError, match="PoseSource"):
        BasePose(**_POSE, source=bad)  # type: ignore[arg-type]


def test_no_field_of_base_pose_has_a_default() -> None:
    """The invariant behind the negative test above, so a fourth field inherits it.

    `Limits` carries the same assertion since issue #115. Naming `source` alone
    would not catch the next field somebody adds with a plausible number
    attached — and for a pose every plausible number is a place the robot was
    not.
    """
    defaulted = [
        f.name
        for f in dataclasses.fields(BasePose)
        if f.default is not dataclasses.MISSING
        or f.default_factory is not dataclasses.MISSING
    ]
    assert defaulted == []


def test_a_base_pose_is_frozen() -> None:
    """A pose that can be edited after the fact is not evidence of where anything was."""
    pose = BasePose(**_POSE, source=PoseSource.LOCALIZED)
    with pytest.raises(dataclasses.FrozenInstanceError):
        pose.x = 0.0  # type: ignore[misc]


def test_pose_source_distinguishes_dead_reckoning_from_localization() -> None:
    """The vocabulary itself: the two provenances with different failure modes.

    They are not interchangeable and the enum exists so the record can tell them
    apart — one drifts without bound under slip and is only meaningful relative
    to a last known pose, the other inherits a map and an association. Both are
    Layer B in the room; that is the next test's business.
    """
    assert {s.name for s in PoseSource} >= {"DEAD_RECKONED", "LOCALIZED"}
    assert PoseSource.DEAD_RECKONED is not PoseSource.LOCALIZED


def _reg_modules() -> list[ModuleType]:
    """Every module in the package, imported, so an attribute scan can see it all."""
    mods = [importlib.import_module("reg")]
    for info in pkgutil.iter_modules(reg.__path__):
        mods.append(importlib.import_module(f"reg.{info.name}"))
    assert len(mods) > 1, (
        "no modules found under reg/ — the scan below would then pass by "
        "looking at nothing, which is a could-not-evaluate and not a pass."
    )
    return mods


#: Anything whose name suggests it answers "which layer is this pose?".
_POSE_LAYER_NAME = re.compile(r"(pose.*layer|layer.*pose)", re.IGNORECASE)


def pose_layer_offenders(modules: list[ModuleType]) -> list[str]:
    """Anything in `modules` that maps a pose provenance to a layer.

    Taken out of the test so the negative below can drive it against a module
    built to offend. A scan whose only input is the real package can be shown to
    have *looked*, never to be able to *see* — and this is the check issue #149
    exists for, so "it passes today" is not evidence about it.
    """
    offenders: list[str] = []
    for module in modules:
        for name, obj in vars(module).items():
            if getattr(obj, "__module__", None) != module.__name__:
                continue  # imported from elsewhere; scanned where it is defined
            if callable(obj) and _POSE_LAYER_NAME.search(name):
                offenders.append(f"{module.__name__}.{name}")
    for module in modules:
        for name, obj in vars(module).items():
            if not isinstance(obj, dict) or not obj:
                continue
            keyed_on_pose = any(isinstance(k, PoseSource) for k in obj)
            holds_layers = any(v in ("A", "B") for v in obj.values())
            if keyed_on_pose and holds_layers:
                offenders.append(f"{module.__name__}.{name}")
    return offenders


def test_no_function_in_reg_maps_a_pose_provenance_to_a_layer() -> None:
    """THE TEST THIS ISSUE IS ABOUT (#149). The mapping must not exist at all.

    `reg.envelope.envelope_layer` and `_LAYER_BY_LIMIT_SOURCE` make writing a
    `pose_layer` the obvious next move, and it would be wrong in a way no other
    test here could see: `DEAD_RECKONED` is derivable from proprioception, so
    the plausible mapping hands back `A` for it, and a room-frame pose tagged
    `A` is precisely the mislabelling this whole mechanism exists to stop.
    Both `PoseSource` values are Layer B (docs/sufficiency.md §5.6), so the
    honest mapping is a constant — and a constant function is a fact for the
    docstring, not an API somebody can be tempted to make interesting later.

    Scanned two ways, because the wrong thing can arrive with an innocent name:
    by name, and by shape — any container keyed on a `PoseSource` whose values
    are layer tags.
    """
    assert pose_layer_offenders(_reg_modules()) == [], (
        f"{offenders} maps a pose provenance to a layer. There is no such "
        "mapping to write: a room-frame pose is Layer B structurally — it is a "
        "statement about the robot's relationship to a map, landmarks or a "
        "frame somebody defined — and no localizer moves it, including a "
        "set-membership estimator returning a guaranteed containing set "
        "(docs/sufficiency.md §5.6, docs/prior-art.md §25). `PoseSource` "
        "records what the pose inherits and over what horizon, not whether it "
        "is certifiable. If this needs to change, it changes what the project "
        "may claim and sufficiency.md moves first."
    )


def _module_that_offends(name: str) -> ModuleType:
    """A module carrying both shapes the scan looks for.

    Written the way somebody would actually write it, which is the point: a
    `pose_layer` returning `A` for a dead-reckoned pose is not a silly mistake,
    it is the reading `LimitSource` invites — dead reckoning *is* derivable from
    proprioception. It is wrong because the pose it describes is in the room.
    """
    module = ModuleType(name)

    def pose_layer(source: PoseSource) -> str:
        return "A" if source is PoseSource.DEAD_RECKONED else "B"

    pose_layer.__module__ = name
    module.pose_layer = pose_layer  # type: ignore[attr-defined]
    module._LAYER_BY_POSE_SOURCE = {  # type: ignore[attr-defined]
        PoseSource.DEAD_RECKONED: "A",
        PoseSource.LOCALIZED: "B",
    }
    return module


def test_the_scan_catches_a_mapping_that_is_there() -> None:
    """**THE NEGATIVE.** Fed a module that maps a pose provenance to a layer,
    the scan must name it — by function and by table, since it looks both ways.

    Without this the check above asserts an absence it has never been shown able
    to detect: a mistyped `_POSE_LAYER_NAME`, or the dict condition inverted,
    and it passes forever while the thing it guards walks in. `CLAUDE.md`: feed a
    check the condition it guards against and assert it says no.
    """
    offenders = pose_layer_offenders([_module_that_offends("reg.fake_offender")])
    assert "reg.fake_offender.pose_layer" in offenders, (
        "the scan did not catch a function named `pose_layer` — the by-name "
        "half is not working, so the absence it asserts is unproven."
    )
    assert "reg.fake_offender._LAYER_BY_POSE_SOURCE" in offenders, (
        "the scan did not catch a dict keyed on PoseSource holding layer tags "
        "— the by-shape half is not working, and that is the half that catches "
        "the mapping arriving under an innocent name."
    )


def test_the_scan_does_not_fire_on_an_innocent_module() -> None:
    """And it must not cry wolf. `envelope_layer` is a real layer mapping that
    is entirely correct — it takes a `Limits` — and a scan that flagged it would
    be switched off within a week."""
    innocent = ModuleType("reg.fake_innocent")

    def envelope_layer(limits: object) -> str:
        return "A"

    envelope_layer.__module__ = "reg.fake_innocent"
    innocent.envelope_layer = envelope_layer  # type: ignore[attr-defined]
    innocent._LAYER_BY_LIMIT_SOURCE = {  # type: ignore[attr-defined]
        LimitSource.PROPRIOCEPTIVE: "A",
        LimitSource.DERIVED: "B",
    }
    assert pose_layer_offenders([innocent]) == []


def test_the_limit_source_mapping_cannot_be_borrowed_for_a_pose() -> None:
    """Negative test: the one layer mapping that exists refuses a `BasePose`.

    Deleting `pose_layer` means nothing if `envelope_layer` will duck-type a
    pose — it reads `.source` and both types have one. It does not: it checks
    for a `Limits` and says so, so the absence asserted above cannot be worked
    around by passing the pose to the function next door.
    """
    pose = BasePose(**_POSE, source=PoseSource.DEAD_RECKONED)
    with pytest.raises(TypeError, match="envelope_layer takes a Limits"):
        envelope_layer(pose)  # type: ignore[arg-type]


def test_propriostate_cannot_hold_a_base_pose() -> None:
    """The boundary this type is on the far side of, asserted with no consumer yet.

    `ProprioState` may gain base *velocity*, which an encoder measures; it may
    not gain base *pose*, which an encoder does not (docs/mobile-base.md §2).
    Issue #150 took the first half of that and not the second, which is why the
    allowlist below is `LAYER_A_STATE_FIELDS` and not the literal `{t, q, qd}`
    this test was written against.
    Note that `x`, `y` and `theta` are not in `WORLD_WORDS` and never will be —
    the word check cannot catch this one, so it is checked by type and by the
    allowlist.

    The allowlist is asserted here as well as in
    `test_propriostate_fields_are_exactly_the_allowed_set` on purpose: issue
    #149 is additive, and *nothing on Layer A moved* is half of what it claims.
    """
    annotations = {f.name: str(f.type) for f in dataclasses.fields(ProprioState)}
    assert not any("BasePose" in t for t in annotations.values()), (
        f"ProprioState fields {annotations} include a BasePose. A room-frame "
        "pose in Layer A makes every envelope built from that state a Layer B "
        "region wearing a Layer A tag — docs/sufficiency.md §5.6."
    )
    assert set(annotations) == LAYER_A_STATE_FIELDS
    pose_fields = [
        f.name
        for f in dataclasses.fields(ProprioState)
        if f.name.lower() in POSE_FIELD_NAMES
    ]
    assert pose_fields == []
