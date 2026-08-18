"""The layer boundary, tested rather than asserted in a comment.

docs/plan.md calls the Layer A / Layer B split the single most important
structural property in the codebase. A property that important gets a test that
fails when it is broken — otherwise the first agent in a hurry adds `human_pos`
to `ProprioState` and every claim in Claim 3 quietly becomes false while every
other test stays green.
"""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from reg.types import Limits, Obstacle, ProprioState, StateFrame

# Anything matching one of these in a Layer A structure means the world leaked in.
WORLD_WORDS = ("human", "obstacle", "object", "entity", "goal", "target", "scene")


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
        )
