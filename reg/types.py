"""Shared types — and the layer boundary the whole argument rests on.

THE STRUCTURAL PROPERTY THIS FILE EXISTS TO ENFORCE
---------------------------------------------------
`reg` makes a claim about which audit questions are answerable from certifiable
evidence. That claim is only worth anything if the certifiable layer *cannot* see
the uncertifiable one — not by convention, but structurally.

    Layer A  (certifiable)    proprioception, actuation limits, declarations,
                              verdicts, the hash chain. Sensors whose failure
                              modes can be characterised.

    Layer B  (uncertifiable)  where anything else in the world is. Ground truth
                              from the simulator here; a perception stack in a
                              real system.

So the envelope computation takes a `ProprioState`, which has no field naming any
entity, obstacle, or human. If it could reach the world, the sufficiency argument
in Claim 3 evaporates and what remains is a visualisation.

This mirrors established practice rather than inventing it: reachability-based
trajectory design (ARMTD, ARMOUR) computes a manipulator's reachable set offline
and independent of obstacles, then intersects with the scene afterwards. See
docs/prior-art.md §4 — the split is not the contribution; tagging every piece of
evidence with the layer it depends on is.

DETERMINISM
-----------
Every structure here is frozen. An audit artifact that is not reproducible is not
an audit artifact, so nothing that ends up in the record may be mutated after it
is built.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import numpy as np

# Layer tags. Every graph edge carries one; Claim 3 is a query over these.
Layer = Literal["A", "B"]


@dataclass(frozen=True)
class Limits:
    """Kinematic and actuation bounds. Layer A: a property of the robot.

    `qdd_max` is an acceleration bound standing in for a torque limit. This is
    deliberate — see docs/plan.md, Phase 1. There is no dynamics model here and
    there should not be one.
    """

    q_min: np.ndarray
    q_max: np.ndarray
    qd_max: np.ndarray
    qdd_max: np.ndarray
    link_lengths: np.ndarray
    link_radius: float = 0.05

    def __post_init__(self) -> None:
        n = len(self.link_lengths)
        for name in ("q_min", "q_max", "qd_max", "qdd_max"):
            got = len(getattr(self, name))
            if got != n:
                raise ValueError(
                    f"{name} has {got} entries but there are {n} links. "
                    "Limits must be stated per joint; a mismatch here would be "
                    "silently broadcast by numpy into a bound nobody wrote."
                )


@dataclass(frozen=True)
class ProprioState:
    """Everything the certifiable layer is allowed to know.

    DO NOT ADD A FIELD NAMING ANYTHING OUTSIDE THE ROBOT. Not the human, not an
    obstacle, not a goal pose derived from either. The absence of those fields is
    the enforcement mechanism for the Layer A boundary, and it is the only
    enforcement mechanism — there is no runtime check that can replace it.

    If a computation genuinely needs the world, it belongs in Layer B and its
    results must be tagged accordingly.
    """

    t: float
    q: np.ndarray
    qd: np.ndarray


@dataclass(frozen=True)
class Obstacle:
    """A static entity. Layer B — position is ground truth from the sim."""

    entity_id: str
    kind: str
    cx: float
    cy: float
    radius: float


@dataclass(frozen=True)
class StateFrame:
    """One tick of simulator ground truth.

    Mixed-layer by construction: this is the *raw stream*, the thing the evidence
    graph is compressed from. Nothing in Layer A consumes it directly — the
    envelope takes `proprio()` and never sees the rest.
    """

    t: float
    q: np.ndarray
    qd: np.ndarray
    human_pos: np.ndarray  # Layer B
    human_vel: np.ndarray  # Layer B
    objects: tuple[Obstacle, ...] = field(default=())  # Layer B

    def proprio(self) -> ProprioState:
        """Narrow to Layer A. The only supported way to feed the envelope."""
        return ProprioState(t=self.t, q=self.q, qd=self.qd)
