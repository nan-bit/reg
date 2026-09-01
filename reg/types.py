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

A provenance field is not always a layer decision, and `BasePose` is the case
where it is not. `PoseSource` sits beside `LimitSource` and looks like it, but a
room-frame pose is Layer B *structurally* — a statement about the robot's
relationship to a map, landmarks or a frame somebody defined — and no localizer
moves it. So that enum records what the pose inherits and over what horizon, and
there is deliberately no function turning it into a `Layer`. Issue #149;
docs/sufficiency.md §5.6.

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


class PoseSource(Enum):
    """What a `BasePose` inherits, and over what horizon (issue #149).

    THIS ENUM DOES NOT SELECT A LAYER, AND THAT IS THE POINT
    -------------------------------------------------------
    `LimitSource` above is the obvious precedent and copying it whole would be
    wrong here. `LimitSource` *decides* a layer — `reg.envelope.envelope_layer`
    maps `PROPRIOCEPTIVE` to `A` and `DERIVED` to `B` — because a bound really
    can be a property of the robot or a function of something perceived, and
    only the caller knows which.

    A room-frame base pose has no such fork. **Both values below are Layer B**,
    structurally: a pose in the room is a statement about the robot's
    relationship to things *outside* the robot — a map, landmarks, a frame
    somebody defined — and that is exactly where this project draws the
    boundary. Not "no rated localizer exists yet", which is a weaker claim that
    someone could answer by building one: even set-theoretic localization, which
    returns a set *guaranteed* to contain the true pose, is guaranteed only
    under a map and bounded-error hypotheses, both exogenous, and a guarantee
    conditioned on a Layer B input is a Layer B guarantee. No localizer of any
    kind moves the base pose to Layer A. docs/sufficiency.md §5.6;
    docs/prior-art.md §25.

    **So there is no `pose_layer()` and there must not be one.** A function
    mapping these members to `Layer` could only be lying in one of the two
    cases, and the lie it would tell — a room-frame pose tagged `A` — is the
    mislabelling `Limits.source` exists to stop, arriving through the door that
    field opened. `tests/test_layer_boundary.py` asserts no such mapping exists
    anywhere in `reg/`, because the precedent makes writing one the obvious next
    move.

    WHAT THE VALUE DOES RECORD
    --------------------------
    The failure modes and the **validity horizon** the pose carries, which the
    binary layer tag cannot express (docs/mobile-base.md §2.2):

    * `DEAD_RECKONED` is derivable from proprioception alone, and is Layer A
      only *relative to a last known pose*. Its error grows with time and is
      unbounded under slip that wheel encoders cannot observe. That is "Layer A
      with a validity horizon", which this project's binary has no value for —
      so it is recorded here rather than resolved.
    * `LOCALIZED` inherits a map and whatever sensing matched against it. No
      drift horizon, a different failure set: a wrong association, a stale or
      wrong map, a symmetric corridor.

    Required, no default, no inference — the `LimitSource` discipline, for the
    same reason. A pose whose provenance nobody stated must not be
    indistinguishable from one somebody did.

    WHAT THIS BINARY SIMPLIFIES, SAID OUT LOUD
    ------------------------------------------
    Two values, and neither carries a magnitude. A set-theoretic localizer
    returns a pose *set*, which composes with the envelope by Minkowski sum and
    would preserve the over-approximation across the frame change that a point
    pose does not — that is the shape in which "how wrong can this be" could be
    carried. It is the same collision with issue #84's deliberate refusal of a
    graded integrity attribute, and it gets the same treatment: recorded here,
    not built (docs/mobile-base.md §2.2, docs/prior-art.md §25).
    """

    #: Integrated from proprioception — `∫(v, ω) dt` from a last known pose.
    #: Layer A relative to that pose; Layer B in the room, with a drift horizon.
    DEAD_RECKONED = "dead_reckoned"
    #: Map-based pose estimation. Layer B in the room for the same structural
    #: reason, with the map and the association as its failure modes.
    LOCALIZED = "localized"


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
class BasePose:
    """Where the robot's base sits in the room. **Layer B** (issue #149).

    Layer B **structurally**, not for want of a better estimator. `(x, y,
    theta)` here are room coordinates: a statement about the robot's
    relationship to a frame somebody defined, a map, or landmarks — things
    outside the robot — and that is where this project draws the boundary. The
    sensing-status argument (*nothing safety-rated produces this number*) is the
    weaker one, because a rated localizer would answer it; the structural one
    does not move, and it is why no localizer of any kind — including a
    set-membership estimator returning a set guaranteed to contain the true
    pose — puts this type in Layer A. docs/sufficiency.md §5.6.

    What that costs is stated there and is worth repeating where the type lives:
    for a fixed arm *could the robot have reached (x, y) at t?* is Layer A,
    because base-at-the-origin is a mounting fact. Allow the base to drive and
    the identical question in room coordinates becomes a **conjunction** with
    *the base was where the artifact says it was*, for which this project
    supplies no evidence — so it is Layer B, and the Layer A survivor is the
    narrower body-frame question. Anything computed by transforming a body-frame
    region by one of these inherits that.

    **No field has a default, matching `Limits` since issue #115.** `source` in
    particular: see `PoseSource`, which records what the pose inherits and over
    what horizon and deliberately does *not* select a layer.

    Nothing in `reg/` constructs one of these yet — the envelope is computed for
    a base bolted to the origin, and `reg.enforce.computed_bound` is finite
    because of it. `tests/test_layer_boundary.py` is what keeps the contract
    alive with no consumer behind it, so the type cannot drift into something
    Layer A before anything uses it. docs/mobile-base.md §7, Tier 2.
    """

    x: float
    y: float
    theta: float
    #: Required, and it selects no layer. Both `PoseSource` values are Layer B;
    #: this records the failure modes and validity horizon inherited, so that a
    #: dead-reckoned pose and a localized one are not the same object in the
    #: record.
    source: PoseSource

    def __post_init__(self) -> None:
        if not isinstance(self.source, PoseSource):
            raise TypeError(
                f"BasePose.source must be a PoseSource, got {self.source!r}. It "
                "is the artifact's record of what the pose inherits and over "
                "what horizon — integration from a last known pose, or a map. A "
                "string or None here is not 'unspecified': it is a provenance "
                "nobody stated arriving as one somebody did. Note that it does "
                "not decide a layer; the pose is Layer B either way."
            )


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
