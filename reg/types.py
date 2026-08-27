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

That enforcement is by *field name*, and the envelope's second input defeats it:
`Limits` names nothing outside the robot either, and its numbers can still be a
function of what a perceiver measured (ISO/TS 15066 speed-and-separation caps
`qd_max` by the measured separation distance). Names cannot catch a taint that
arrives in a value, so `Limits` carries `source: LimitSource` — required, no
default — and `reg.envelope.envelope_layer` turns it into the layer the
`HAS_ENVELOPE` edge is tagged with. Issue #84; docs/sufficiency.md §7.

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
from enum import Enum
from typing import Literal

import numpy as np

# Layer tags. Every graph edge carries one; Claim 3 is a query over these.
Layer = Literal["A", "B"]


class LimitSource(Enum):
    """Where a `Limits` object's numbers came from (issue #84).

    THE HOLE THIS CLOSES
    --------------------
    `ProprioState` keeps the world out of Layer A by *field name*, and that is
    real enforcement. But the envelope has a second input, and this one was
    declared Layer A by fiat — "a property of the robot". Under ISO/TS 15066 and
    ISO 10218-2:2025 **speed-and-separation monitoring**, which docs/plan.md
    cites approvingly, the commanded speed bound is a function of the *measured
    separation distance*: `qd_max` is then perception-derived, and an envelope
    computed from it is Layer B wearing a Layer A tag. The taint arrives in a
    **value**, and nothing that inspects **names** can catch it.

    So the caller states it. There is no default and there is no inference: the
    only party that knows whether a speed cap came off a datasheet or out of a
    safety scanner is whoever assembled the numbers.

    `reg.envelope.envelope_layer` is the one place this maps to a layer, and
    `reg.graph.build` tags the `HAS_ENVELOPE` edge with what it returns.

    WHAT THIS BINARY SIMPLIFIES, SAID OUT LOUD
    ------------------------------------------
    Two values, matching the project's two layers. That is a simplification and
    docs/sufficiency.md §7 records it as one: an IEC 61496 safety scanner rated
    PLd is perception *with characterized failure modes* and still lands in
    `DERIVED`, while an encoder needs ISO 13849 cat-3 dual channel before it
    carries a safety claim and still lands in `PROPRIOCEPTIVE`. A tag plus an
    integrity attribute would model how assurance is actually argued; it was
    considered and rejected for scope (issue #84), because it rewrites what the
    project may claim rather than recording which case a given artifact is in.
    """

    #: A property of the robot: a datasheet limit, a joint stop, a link length.
    PROPRIOCEPTIVE = "proprioceptive"
    #: Computed from something perceived — an SSM speed cap is the case that
    #: matters. Whatever is derived from these bounds inherits the perceiver.
    DERIVED = "derived"


@dataclass(frozen=True)
class Limits:
    """Kinematic and actuation bounds, and where they came from.

    **Not Layer A by fiat.** `source` says which layer the bounds belong to and
    it is required — see `LimitSource` for why a value can smuggle perception
    into a structure whose field names are all innocent.

    `qdd_max` is an acceleration bound standing in for a torque limit. This is
    deliberate — see docs/plan.md, Phase 1. There is no dynamics model here and
    there should not be one.

    **No field here has a default, and that is the point.** `link_radius` had
    one — `0.05` — until issue #115, on the unstated argument that it was only
    geometry. It is not: it is the radius `reg.enforce.computed_bound` VETOes a
    declaration against, the half-width `reg.envelope` dilates the centreline
    union by, and the bound that fixes the sampling step (`h_j * reach[j] <=
    link_radius`). Most call sites already stated it — the default covered the
    remainder, and a figure measured against a value a caller never chose is
    indistinguishable downstream from one it did. The value did not change when
    the default went; what changed is that the distinction is no longer possible.
    """

    q_min: np.ndarray
    q_max: np.ndarray
    qd_max: np.ndarray
    qdd_max: np.ndarray
    link_lengths: np.ndarray
    #: Required: giving `source` a default would restore exactly the fiat this
    #: field exists to remove, and the caller who did not think about provenance
    #: would be indistinguishable from the one who did.
    source: LimitSource
    #: Required for the same reason (issue #115). The body's half-width, the
    #: sampling bound, and the term added to `sum(link_lengths)` in the disc a
    #: declaration is tested against — a caller who did not choose it would be
    #: indistinguishable from one who did, and the artifact would record the
    #: invented number as a stated one.
    link_radius: float

    def __post_init__(self) -> None:
        if not isinstance(self.source, LimitSource):
            raise TypeError(
                f"Limits.source must be a LimitSource, got {self.source!r}. It is "
                "the artifact's record of whether these bounds are a property of "
                "the robot or a function of something perceived, and the layer "
                "tag on every envelope computed from them follows it. A string "
                "or None here is not 'unspecified' — it is a provenance nobody "
                "stated arriving as one somebody did."
            )
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
