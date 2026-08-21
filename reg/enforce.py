"""Enforcement: the independent bound, the `Verdict`, and the nine faults. **Phase 4.**

WHAT THIS IS, AND WHOSE ARCHITECTURE IT IS
------------------------------------------
This is the **Simplex architecture** — Seto, Krogh, Sha & Chutinan, *"The Simplex
Architecture for Safe Online Control System Upgrades"*, ACC 1998 — in the
vocabulary **ASTM F3269-21** gives it (docs/prior-art.md §3):

    Complex Function   the policy (`reg.declare`) — capable, insufficiently
                       verifiable, out of scope, and never told what happened here
    Recovery Function  this module — bounded, verifiable, and holding the authority
    Run-time monitor   the fault detection below

None of that is novel and this file must not be described as though it were.
Neither is declare-intent-then-attest: docs/prior-art.md §10 records an active
2026 line of work in which software agents declare intent, receive a signed
authority token and leave a tamper-evident log. That is recognisably this shape.

**The claim is the fault taxonomy applied to *semantic* faults rather than
transport ones.** IEC 61784-3 / PROFIsafe enumerates the ways a safety telegram
can be corrupted, lost, duplicated, reordered or delayed, and specifies a
detection and a response for each. The nine faults below are the same discipline
pointed at what the message *means*: a declaration that expired, a declaration
nobody signed, a declared bound the robot could not physically honour, an action
outside the region the policy said it would stay in. `escalation_failure` has no
PROFIsafe analogue at all, because a learned policy can fail by *not acting* and
a transport protocol never has to consider that.

INDEPENDENCE IS THE MECHANISM, NOT A STYLE PREFERENCE
-----------------------------------------------------
A constraint layer supplied by the same party as the policy has common-cause
failure with it. So this module imports from `reg.declare` **no further than the
`Declaration` dataclass and `ACTION_CLASSES`** — the vocabulary is imported
rather than restated because two copies of it is how an out-of-vocabulary action
becomes a fault on one side and invisible on the other. Everything else it needs
it computes: the bound comes from `Limits` and `reg.kinematics`, both Layer A,
and `declared_envelope` is *checked*, never believed. `tests/test_enforce.py`
asserts the import restriction, so widening it fails CI rather than review.

The layer boundary holds here too. `adjudicate` takes a `ProprioState`, which has
no field naming anything outside the robot, and this module imports neither
`World` nor `Obstacle` nor `Scenario`. Enforcement decides what the robot may do
from what the robot knows about itself.

A VERDICT IS PER COMMANDED ACTION, NOT PER DECLARATION
------------------------------------------------------
`declared_q_bounds` is a fixed box for a whole run, so every declaration in
`declared_violation` carries an identical `declared_envelope` and differs only in
`seq`, `t_issued` and `prev_hash` — while the violation begins partway through.
A declaration is therefore not "good" or "bad": it is **adjudicated repeatedly**,
once per action taken under it, and the same declaration yields PERMIT verdicts
and then CLAMP verdicts. `Verdict` carries both `declaration_id` and `t` so that
this is expressible, and Phase 5's `ADJUDICATED` edge must not collapse it into
one verdict per declaration.

`offer` emits a verdict too, but only when it *refuses* a declaration — "VETO the
declaration itself", in the words of docs/plan.md Phase 4. A refusal has to leave
evidence; an acceptance is not an adjudication of anything yet.

THE TWO ENVELOPE FAULTS DIFFER IN DIRECTION
-------------------------------------------
| fault | test | why the direction matters |
|---|---|---|
| declaration/action mismatch | commanded body polygon ⊄ `declared_envelope` | exact: both are polygons, and the comparison is at the resolution the artifact commits to |
| envelope overclaim | `declared_envelope` ⊄ `horizon_bound(state, limits, window)` | needs a bound that is sound in the **conservative** direction |

**The resolution the mismatch test is performed at, and why it is not a widened
tolerance.** Both sides are polygons the artifact commits to at
`reg.envelope.HASH_COORD_PRECISION` — nine decimal places, a nanometre, chosen
there because it is "far below any change in a reachable set that could matter,
and coarse enough that last-bit floating-point noise cannot change the digest".
Asking a containment question at *finer* resolution than that asks something the
record cannot answer, and shapely obliges with nonsense: on a fixture whose
declared envelope is by construction the union of the very bodies being tested,
`Polygon.covers` reports an escape on 280 frames of 301 and a raw `difference`
reports slivers of about 1e-18 m² — a square a nanometre on a side. Those are not
excursions; they are two floating-point renderings of the same boundary. So the
test dilates the declared bound by one nanometre and asks whether any of the body
survives outside it. The smallest genuine excursion in `declared_violation` is
0.6 mm, six orders of magnitude above the dilation, and no compliant fixture
produces a mismatch at any seed. That is a resolution, stated and imported from
where the artifact already states it — not a tolerance widened until a fixture
went green.

**Why this does not use `reg.envelope.compute_envelope` as the bound** — the one
thing it takes from that module is the coordinate resolution above. That
function is an *under*-approximation and says so at length: sampling can only
under-cover the true forward reachable set. A declared region larger than the
sampled one is therefore **not** evidence of an overclaim — it is the expected
result for an honest declaration, and vetoing on it would produce false VETOs on
truthful policies, which is the "check that cries wolf" failure this project has
an issue open about. Comparing against a bound that under-covers is the one way
to get this check wrong, so it is not done.

**The bound that is used, stated plainly.** Two bounds, and the check takes the
smaller:

    computed_bound(limits)          the radius of the **workspace disc**,
                                    `sum(link_lengths) + link_radius`, centred on
                                    the base that `reg.kinematics` fixes at the
                                    origin. Every point of the robot's body, in
                                    every configuration, at every instant, lies
                                    within it — by the triangle inequality over
                                    the link chain, with no horizon and no
                                    sampling involved.

    horizon_bound(state, limits, w) the radial projection of
                                    `reg.envelope.outer_envelope` — the
                                    horizon-limited **outer** reachable set, the
                                    joint box pushed through the kinematics as an
                                    interval (issue #82). Floored by the disc, so
                                    it is never the worse of the two.

Both are sound in the conservative direction: they *over*-cover, so nothing
inside them is ever falsely accused, and the minimum of two sound bounds is
sound. The containment test is exact rather than approximate — a polygon lies
inside a disc iff all of its vertices do, because a disc is convex — so no
polygonal rendering of a circle enters the comparison.

**What the second bound closed, and what is still open.** The disc alone has no
`q`, no `qd` and no horizon in it, so `envelope_overclaim` fired only on a
declaration exceeding the *entire workspace*: the fault a Simplex / ASTM F3269
monitor exists to catch — the policy declared more than it could occupy within
the horizon — was undetectable. `horizon_bound` detects the **radial** half of
it: an arm folded at the elbow, or one whose velocity bound will not carry it to
full extension within the window, has a bound well inside the disc. What remains
undetected is the **angular** half — a region of a reachable radius in a
direction the robot cannot turn to in time. `reg.envelope.outer_envelope` is the
polygon that catches those, it is retained beside every envelope in the artifact
as its area and radius, and using it for *containment* here is a decision issue
#82 leaves open rather than an oversight: measured against the fixtures, the
polygon test re-labels three of the five fault runs as overclaims, which changes
what a fault in the nine-fault taxonomy means. That is not a refactor.

ESCALATION FAILURE, DEFINED HERE
--------------------------------
Nothing in docs/plan.md says what obliges an escalation, so this module states
the condition rather than leaving the fault undemonstrable:

    **Escalation is obliged from the moment enforcement passivates until the
    passivation is acknowledged. A declaration issued in that window whose
    `action_class` is not `escalate` is an escalation failure.**

That is "escalation conditions met, no `escalate` declaration emitted" with the
condition pinned to the one event enforcement can observe from Layer A alone,
and it is why `reg.declare` puts `escalate` in the vocabulary while its scripted
policy never emits one. Response: flag and safe state, per the taxonomy. See the
PR for the design question this leaves open.

PASSIVATION AND REINTEGRATION
-----------------------------
After **any** VETO or SAFE_STATE the enforcer passivates, and recovery is not
automatic: it needs a fresh accepted declaration **and** an `Acknowledgment` naming
the verdict that caused the passivation. Either alone resumes nothing. That
asymmetry is the part people omit when they copy the pattern, and the
acknowledgment is signed with the **enforcement** key precisely so that the
policy cannot clear its own fault — the gate would otherwise be decorative.

NO DEFAULTS
-----------
`watchdog_period_s` and `t_start` are required arguments with no default.
docs/plan.md fixes neither a watchdog period nor an epoch, and
`reg.declare.emit_declarations` already refuses to invent `replan_interval_s` for
the same reason: a plausible invented number is indistinguishable downstream from
a stated one, and this one decides whether the watchdog ever fires.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass, replace
from typing import ClassVar, Literal, get_args

import numpy as np
import shapely
from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from reg.chain import (
    GENESIS_HASH,
    UNSIGNED_MAC,
    Key,
    MacCheck,
    MacState,
    Role,
    chain_hash,
    is_hash,
    sign,
    verify,
)

# The one import from the policy side, and it stops here: the dataclass and the
# vocabulary. Anything more would give enforcement common-cause failure with the
# thing it is checking. `tests/test_enforce.py` asserts this.
from reg.declare import ACTION_CLASSES, Declaration
from reg.envelope import HASH_COORD_PRECISION, outer_envelope, outer_radius
from reg.kinematics import link_polygons
from reg.types import Limits, ProprioState

__all__ = [
    "FAULTS",
    "MISMATCH_RESOLUTION_M",
    "OUTCOMES",
    "Acknowledgment",
    "EnforcementError",
    "Enforcer",
    "Outcome",
    "Verdict",
    "body_polygon",
    "computed_bound",
    "declared_bound",
    "envelope_excess",
    "escape_region",
    "horizon_bound",
    "horizon_excess",
    "sign_acknowledgment",
    "sign_verdict",
    "verify_acknowledgment",
    "verify_verdict",
]

#: The resolution the declaration/action mismatch test is performed at, metres.
#: One nanometre — `10 ** -reg.envelope.HASH_COORD_PRECISION`, the resolution the
#: artifact already commits envelope geometry to and states its reason for. It is
#: **not** a tolerance on the fault: see the module header for the measurement
#: that fixes it here and nowhere coarser.
MISMATCH_RESOLUTION_M: float = 10.0**-HASH_COORD_PRECISION

Outcome = Literal["PERMIT", "CLAMP", "VETO", "SAFE_STATE"]

#: The four responses, from docs/plan.md Phase 4. Order is severity order and it
#: is fixed: a reader sorting verdicts by outcome should get the benign ones first.
OUTCOMES: tuple[str, ...] = get_args(Outcome)

#: The nine faults, in the order docs/plan.md's taxonomy table lists them. The
#: names are the record's vocabulary — a fault outside this tuple cannot be put
#: in a `Verdict`, for the same reason an out-of-vocabulary `action_class` cannot
#: be put in a `Declaration`: a fault nothing recognises is a fault nothing can
#: query for, and Phase 7's incident report is a query over exactly these.
FAULTS: tuple[str, ...] = (
    "no_declaration",
    "stale_declaration",
    "declaration_action_mismatch",
    "envelope_overclaim",
    "out_of_vocabulary_action",
    "unattributed",
    "replay_or_reorder",
    "watchdog_expiry",
    "escalation_failure",
)

#: Faults whose response passivates. That is every one of them: `docs/plan.md`
#: responds to eight with VETO or safe state, and CLAMP — the ninth — is the only
#: graceful degradation in the taxonomy. Stated as a set rather than implied by
#: the branch structure so that "which faults stop the robot" is one line to read.
PASSIVATING_FAULTS: frozenset[str] = frozenset(FAULTS) - {"declaration_action_mismatch"}


class EnforcementError(ValueError):
    """Enforcement could not be performed as specified, so it was not performed.

    Never a verdict. A verdict is a *finding about the robot*; this is a finding
    about the caller — a malformed record, a key of the wrong role, an action
    offered out of time order. Returning PERMIT for any of them would be a
    could-not-evaluate resolving to a pass, and returning VETO would be an
    accusation with a signature on it about something the policy did not do.
    """


# --------------------------------------------------------------------------
# The records.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Verdict:
    """Enforcement's finding about one commanded action. Fields exactly as
    docs/plan.md Phase 4.

    Frozen, like every record here: a verdict that can be edited after it is
    signed is not evidence. `sign_verdict` returns a new instance rather than
    filling in `mac`.

    Args:
        verdict_id: unique within a run and deterministic — same seed, same
            bytes. Not a UUID, for the reason `reg.declare` gives.
        declaration_id: the declaration this action was adjudicated against, or
            `None` when there was none to adjudicate against. `None` is a
            finding, not a gap: it is what `no_declaration` and `watchdog_expiry`
            look like in the record.
        seq: the **verdict's own** monotonic counter within a run, from 0 — not
            the declaration's. Two verdicts against one declaration is the normal
            case (see the module header), so borrowing the declaration's `seq`
            would make the verdict stream's own reordering undetectable.
        t: seconds, the instant of the commanded action being adjudicated.
        outcome: one of `OUTCOMES`.
        fault: one of `FAULTS`, or `None` for PERMIT. The two are tied together
            below and neither is free to vary alone.
        clamped_envelope: WKB of the bound actually applied, and **only** on a
            CLAMP. A VETO or a SAFE_STATE applies no bound because it permits no
            action, and a PERMIT clamps nothing.
        prev_hash: the previous record's `chain_hash`, or `GENESIS_HASH` first.
        mac: HMAC over every other field under the **enforcement** key.
    """

    #: Only enforcement signs verdicts. `reg.chain.sign` refuses any other key,
    #: so the policy key structurally cannot fabricate one — the mirror of
    #: `Declaration.SIGNING_ROLE`, and the reason the two parties are separable
    #: in the record rather than by convention.
    SIGNING_ROLE: ClassVar[Role] = "enforcement"

    verdict_id: str
    declaration_id: str | None
    seq: int
    t: float
    outcome: str
    fault: str | None
    clamped_envelope: bytes | None
    prev_hash: str
    mac: str

    def __post_init__(self) -> None:
        _check_id(self.verdict_id, "verdict_id")
        if self.declaration_id is not None:
            _check_id(self.declaration_id, "declaration_id")

        if isinstance(self.seq, bool) or not isinstance(self.seq, (int, np.integer)):
            raise EnforcementError(
                f"seq must be an int, got {self.seq!r}. It is what makes a "
                "reordered verdict stream detectable."
            )
        object.__setattr__(self, "seq", int(self.seq))
        if self.seq < 0:
            raise EnforcementError(f"seq must be >= 0, got {self.seq}.")

        object.__setattr__(self, "t", _finite(self.t, "t"))

        if self.outcome not in OUTCOMES:
            raise EnforcementError(
                f"outcome {self.outcome!r} is not one of {list(OUTCOMES)}. The "
                "four responses are the taxonomy's, and an outcome nothing "
                "recognises is one no query can filter on."
            )
        if self.fault is not None and self.fault not in FAULTS:
            raise EnforcementError(
                f"fault {self.fault!r} is not in the taxonomy {list(FAULTS)}. "
                "The nine are the contribution; a tenth invented at a call site "
                "would be a finding nothing downstream knows how to read."
            )

        # A PERMIT with a fault, or a non-PERMIT without one, is a record that
        # cannot be acted on: the first says "allowed, and here is what went
        # wrong", the second says "stopped, and I will not say why". Both are
        # could-not-evaluate wearing a decision's clothes.
        if (self.outcome == "PERMIT") != (self.fault is None):
            raise EnforcementError(
                f"outcome {self.outcome!r} with fault {self.fault!r}: PERMIT is "
                "the outcome with no fault and the only one. Every other outcome "
                "names the fault from the taxonomy that produced it."
            )

        if self.clamped_envelope is not None:
            _parse_wkb(self.clamped_envelope, "clamped_envelope")
        if (self.outcome == "CLAMP") != (self.clamped_envelope is not None):
            raise EnforcementError(
                f"outcome {self.outcome!r} with clamped_envelope="
                f"{'set' if self.clamped_envelope is not None else 'None'}. "
                "`clamped_envelope` is the bound actually applied: a CLAMP has "
                "one by definition, and PERMIT, VETO and SAFE_STATE do not — a "
                "veto that carried a bound would read as though something had "
                "been allowed inside it."
            )

        if not is_hash(self.prev_hash):
            raise EnforcementError(
                f"prev_hash {self.prev_hash!r} is not a SHA-256 hex digest. The "
                "first record of a chain links to GENESIS_HASH."
            )
        if self.mac != UNSIGNED_MAC and not is_hash(self.mac):
            raise EnforcementError(
                f"mac {self.mac!r} is neither UNSIGNED_MAC nor a SHA-256 hex "
                "digest. A malformed MAC is a could-not-evaluate for every reader."
            )

    @property
    def is_signed(self) -> bool:
        """Whether a MAC is present. Says nothing about whether it is correct."""
        return self.mac != UNSIGNED_MAC

    def envelope(self) -> Polygon | None:
        """The applied bound as a polygon, or `None` when no bound was applied."""
        if self.clamped_envelope is None:
            return None
        return _parse_wkb(self.clamped_envelope, "clamped_envelope")


@dataclass(frozen=True)
class Acknowledgment:
    """The record that unlocks reintegration after a passivation.

    docs/plan.md Phase 4: recovery after VETO or SAFE_STATE "requires a fresh
    declaration plus an explicit acknowledgment record". This is that record, and
    it is signed with the **enforcement** key — the policy acknowledging its own
    fault would make the gate decorative, and `reg.chain.sign` refuses the wrong
    role rather than producing a MAC that verifies.

    It names `verdict_id`, not just the fault: an acknowledgment of a stale
    declaration at t=3 must not silently clear a different stale declaration at
    t=9. `Enforcer.acknowledge` binds it to the verdict that actually passivated.

    Args:
        ack_id: deterministic and unique within a run.
        t: seconds, when the acknowledgment was made.
        fault: the fault being acknowledged, from `FAULTS`.
        verdict_id: the verdict that passivated the enforcer.
        reason: free text saying why it is safe to resume. Required and
            non-empty — an acknowledgment with no stated reason is a rubber
            stamp, and the whole point of the record is that somebody had to say
            something a reader can later disagree with.
        prev_hash: previous record's `chain_hash`. Acknowledgments share the
            verdict chain: they are enforcement's records and interleave with
            verdicts in time.
        mac: HMAC under the enforcement key.
    """

    SIGNING_ROLE: ClassVar[Role] = "enforcement"

    ack_id: str
    t: float
    fault: str
    verdict_id: str
    reason: str
    prev_hash: str
    mac: str

    def __post_init__(self) -> None:
        _check_id(self.ack_id, "ack_id")
        object.__setattr__(self, "t", _finite(self.t, "t"))
        if self.fault not in FAULTS:
            raise EnforcementError(
                f"fault {self.fault!r} is not in the taxonomy {list(FAULTS)}; an "
                "acknowledgment of something that is not a fault clears nothing."
            )
        _check_id(self.verdict_id, "verdict_id")
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise EnforcementError(
                f"reason {self.reason!r} is empty. An acknowledgment is a human "
                "statement that it is safe to resume; without one the record "
                "shows a passivation clearing itself."
            )
        if not is_hash(self.prev_hash):
            raise EnforcementError(
                f"prev_hash {self.prev_hash!r} is not a SHA-256 hex digest."
            )
        if self.mac != UNSIGNED_MAC and not is_hash(self.mac):
            raise EnforcementError(
                f"mac {self.mac!r} is neither UNSIGNED_MAC nor a SHA-256 hex digest."
            )

    @property
    def is_signed(self) -> bool:
        return self.mac != UNSIGNED_MAC


def _check_id(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise EnforcementError(
            f"{name} must be a non-empty str, got {value!r}. It is how one record "
            "names another."
        )
    if any(c.isspace() or ord(c) < 0x20 for c in value):
        raise EnforcementError(
            f"{name} {value!r} contains whitespace or a control character. It ends "
            "up in a canonical serialization and in a store key; a newline in it "
            "would make the record's text form ambiguous."
        )
    return value


def _finite(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(
        value, (int, float, np.integer, np.floating)
    ):
        raise EnforcementError(f"{name} must be a number, got {value!r}.")
    out = float(value)
    if not math.isfinite(out):
        raise EnforcementError(
            f"{name} is {out!r}. A non-finite time in a record makes every "
            "staleness and watchdog comparison downstream vacuously true or "
            "vacuously false, with nothing reporting which."
        )
    return out


def _parse_wkb(payload: object, name: str) -> Polygon:
    """A polygon field of a record, or a construction-time refusal."""
    if not isinstance(payload, bytes):
        raise EnforcementError(
            f"{name} must be WKB bytes, got {type(payload).__name__}. The record "
            "is bytes: a shapely object cannot be hashed, chained or stored."
        )
    if not payload:
        raise EnforcementError(
            f"{name} is empty. An empty bound is not 'no bound' — every "
            "containment test against it passes vacuously."
        )
    try:
        geometry = shapely.from_wkb(payload)
    except Exception:  # shapely raises several types for bad WKB
        raise EnforcementError(
            f"{name} is not readable as WKB. Refusing to construct: a verdict "
            "whose applied bound cannot be read is one no auditor can check."
        ) from None
    if not isinstance(geometry, Polygon):
        raise EnforcementError(
            f"{name} is a {type(geometry).__name__}, not a Polygon."
        )
    if geometry.is_empty:
        raise EnforcementError(
            f"{name} is an empty polygon, which every containment test reads as "
            "'the body may be nowhere' rather than as the failed computation it is."
        )
    if not geometry.is_valid:
        raise EnforcementError(
            f"{name} is an invalid polygon: {shapely.is_valid_reason(geometry)}."
        )
    return geometry


def sign_verdict(verdict: Verdict, key: Key) -> Verdict:
    """Return a copy carrying its MAC under the **enforcement** key.

    Refuses a verdict that is already signed: re-signing would replace one
    party's attribution with another's, and the second MAC would verify.
    """
    if not isinstance(verdict, Verdict):
        raise TypeError(f"sign_verdict takes a Verdict, got {type(verdict).__name__}.")
    if verdict.is_signed:
        raise EnforcementError(
            f"verdict {verdict.verdict_id!r} is already signed. Re-signing would "
            "replace an existing attribution with a new one that verifies, which "
            "is precisely the edit the chain exists to make visible."
        )
    return replace(verdict, mac=sign(verdict, key))


def verify_verdict(verdict: Verdict, key: Key | None) -> MacCheck:
    """Check a verdict's MAC. Three states — see `reg.chain.verify`, never a bool."""
    if not isinstance(verdict, Verdict):
        raise TypeError(
            f"verify_verdict takes a Verdict, got {type(verdict).__name__}."
        )
    return verify(verdict, verdict.mac, key)


def sign_acknowledgment(ack: Acknowledgment, key: Key) -> Acknowledgment:
    """Return a copy carrying its MAC under the **enforcement** key."""
    if not isinstance(ack, Acknowledgment):
        raise TypeError(
            f"sign_acknowledgment takes an Acknowledgment, got {type(ack).__name__}."
        )
    if ack.is_signed:
        raise EnforcementError(f"acknowledgment {ack.ack_id!r} is already signed.")
    return replace(ack, mac=sign(ack, key))


def verify_acknowledgment(ack: Acknowledgment, key: Key | None) -> MacCheck:
    """Check an acknowledgment's MAC. Three states, never a bool."""
    if not isinstance(ack, Acknowledgment):
        raise TypeError(
            f"verify_acknowledgment takes an Acknowledgment, got {type(ack).__name__}."
        )
    return verify(ack, ack.mac, key)


# --------------------------------------------------------------------------
# The independently computed bound. Layer A only: `Limits` and the base at the
# origin, which `reg.kinematics` fixes. See the module header for why this is the
# workspace disc rather than `reg.envelope.compute_envelope`.
# --------------------------------------------------------------------------


def computed_bound(limits: Limits) -> float:
    """Radius of the workspace disc, metres. The bound enforcement computes itself.

    `sum(link_lengths) + link_radius`, centred on the base at the origin. Every
    point of the robot's body in every configuration lies within it: walking the
    link chain, the tip of link `i` is at most `sum(link_lengths[:i+1])` from the
    base by the triangle inequality, and the body of a link is its segment
    buffered by `link_radius`.

    **Sound in the conservative direction.** It over-covers the true reachable
    set — by a lot, since it has no horizon in it — which is what makes it safe
    to VETO on. It is the floor under `horizon_bound`, which tightens it with the
    state and a window (issue #82) and can never be worse than it: an enforcer
    with a state to work from uses the smaller of the two, and this one is what
    remains true when the arm is extended and fast enough to reach the rim of the
    workspace inside the window anyway.

    Raises:
        EnforcementError: `limits` has a malformed link geometry. A bound derived
            from a zero-length link or a non-finite radius is not a bound.
    """
    if not isinstance(limits, Limits):
        raise EnforcementError(
            f"computed_bound takes a Limits, got {type(limits).__name__}."
        )
    lengths = np.asarray(limits.link_lengths, dtype=float)
    if lengths.ndim != 1 or lengths.shape[0] == 0:
        raise EnforcementError(
            f"limits.link_lengths must be a non-empty 1-D array, got shape "
            f"{lengths.shape}."
        )
    if not np.all(np.isfinite(lengths)) or np.any(lengths <= 0.0):
        raise EnforcementError(
            f"limits.link_lengths must all be finite and strictly positive, got "
            f"{lengths!r}. A bound computed from one that is not would be smaller "
            "than the robot, and everything it cleared would be cleared wrongly."
        )
    radius = float(limits.link_radius)
    if not math.isfinite(radius) or radius <= 0.0:
        raise EnforcementError(
            f"limits.link_radius must be finite and strictly positive, got "
            f"{limits.link_radius!r}."
        )
    return float(lengths.sum() + radius)


def horizon_bound(state: ProprioState, limits: Limits, horizon: float) -> float:
    """Radius of the bound for **this instant and this horizon**, metres (#82).

    `min(computed_bound(limits), outer_radius(outer_envelope(state, limits,
    horizon)))` — the radial projection of the horizon-limited outer reachable
    set, floored by the workspace disc so it can never be worse than the bound it
    tightens. Both terms are sound in the conservative direction, and the minimum
    of two sound bounds is sound.

    **What this buys, and what it does not.** `computed_bound` has no `q`, no
    `qd` and no horizon in it, so it fires only on a declaration exceeding the
    *entire workspace*. This one closes part of that gap: an arm folded at the
    elbow, or one whose velocity bound will not carry it to full extension inside
    the horizon, has a radius well under the workspace disc's, and a declaration
    reaching between the two is now detected where it was not before. What it
    still does not detect is an overclaim that is *angular* rather than radial —
    a region of the right radius in a direction the robot cannot turn to in time.
    `reg.envelope.outer_envelope` is the polygon that would catch those; using it
    for containment rather than for its radius is a live decision, not an
    oversight, and issue #82 records why (it re-labels three of the five fault
    fixtures, which changes what a fault in the taxonomy means).

    The check built on this stays **exact**: the bound is a radius, a disc is
    convex, and a polygon lies inside a disc iff every vertex does. No polygonal
    rendering of a circle enters the comparison.

    Args:
        state: Layer A proprioception at the instant the bound starts from.
        limits: the robot. The outer set is a function of these and the state,
            and of nothing the robot cannot see about itself.
        horizon: seconds the bound covers. Required, no default — a bound
            enforcement VETOes on must not be computed over a window nobody
            stated.

    Raises:
        EnforcementError: `state` is not a `ProprioState`, or the outer set
            cannot be computed. Each is a could-not-evaluate, and falling back to
            the looser disc without saying so would let a failed computation read
            as a weaker check that ran.
    """
    if not isinstance(state, ProprioState):
        raise EnforcementError(
            f"horizon_bound takes a ProprioState, got {type(state).__name__}. "
            "This is the Layer A boundary: enforcement computes its bound from "
            "what the robot knows about itself. If you hold a StateFrame, call "
            ".proprio()."
        )
    try:
        region = outer_envelope(state, limits, horizon)
    except (TypeError, ValueError) as exc:
        raise EnforcementError(
            f"the horizon-limited outer reachable set could not be computed: "
            f"{exc}. That is a could-not-evaluate; silently falling back to the "
            "workspace disc would report a check that ran when it did not."
        ) from None
    return min(computed_bound(limits), outer_radius(region))


def _furthest_vertex(region: BaseGeometry, fn: str) -> float:
    """The greatest distance from the base over a region, metres.

    Exact for a polygon — the maximum of a convex function over a polygon is
    attained at a vertex — which is what makes every containment test against a
    disc-shaped bound exact rather than approximate.
    """
    if not isinstance(region, BaseGeometry):
        raise EnforcementError(
            f"{fn} takes a shapely geometry, got {type(region).__name__}."
        )
    if region.is_empty:
        raise EnforcementError(
            f"{fn} was given an empty geometry. That is a could-not-evaluate, "
            "not a region that trivially fits."
        )
    if not region.is_valid:
        raise EnforcementError(
            f"{fn} was given an invalid geometry: {shapely.is_valid_reason(region)}."
        )
    coords = shapely.get_coordinates(region)
    if coords.size == 0:
        raise EnforcementError(f"{fn} was given a geometry with no coordinates.")
    return float(np.hypot(coords[:, 0], coords[:, 1]).max())


def envelope_excess(region: BaseGeometry, limits: Limits) -> float:
    """How far a declared region reaches beyond `computed_bound`, metres.

    Positive means overclaim; zero or negative means the region lies inside the
    disc. The test is **exact**, not an approximation of one: a disc is convex,
    so a polygon lies inside it iff every vertex does, and the greatest distance
    from the base over the region is attained at a vertex. No polygonal rendering
    of a circle is ever constructed, which matters because `shapely`'s buffered
    circle is *inscribed* — using it would shrink the bound and manufacture the
    false VETOs this whole check is arranged to avoid.

    This is the static half of the overclaim check and it is what an enforcer
    with no state to work from can compute. `horizon_excess` is the same test
    against the tighter, state-dependent bound.

    Raises:
        EnforcementError: the region is not a geometry, or is empty or invalid.
            Each is a could-not-evaluate, and returning 0.0 ("fits") for any of
            them would clear a bound nobody could read.
    """
    return _furthest_vertex(region, "envelope_excess") - computed_bound(limits)


def horizon_excess(
    region: BaseGeometry, state: ProprioState, limits: Limits, horizon: float
) -> float:
    """How far a declared region reaches beyond `horizon_bound`, metres (#82).

    Positive means overclaim. Never smaller than `envelope_excess` for the same
    region, because `horizon_bound` is never larger than `computed_bound` — so
    every declaration the static check refused this one refuses too, and the
    fault only ever gains cases.

    Raises:
        EnforcementError: as `envelope_excess` and `horizon_bound`.
    """
    return _furthest_vertex(region, "horizon_excess") - horizon_bound(
        state, limits, horizon
    )


def declared_bound(declaration: Declaration) -> Polygon:
    """The declared region, dilated by `MISMATCH_RESOLUTION_M`, ready to test against.

    Computed once per declaration rather than once per action: the dilation is a
    `buffer` over a region of several hundred vertices, and a declaration is
    adjudicated against tens of actions.

    Raises:
        EnforcementError: the declared envelope cannot be read, or dilating it
            produced an empty or invalid region. Each is a could-not-evaluate,
            and a bound nobody can test against must not silently become one
            every action passes.
    """
    if not isinstance(declaration, Declaration):
        raise EnforcementError(
            f"declared_bound takes a Declaration, got {type(declaration).__name__}."
        )
    try:
        region = declaration.envelope()
    except Exception as exc:  # a record built elsewhere may not parse
        raise EnforcementError(
            f"declaration {declaration.declaration_id!r} carries a "
            f"declared_envelope that cannot be read: {exc}."
        ) from None
    dilated = region.buffer(MISMATCH_RESOLUTION_M)
    if dilated.is_empty or not dilated.is_valid:
        raise EnforcementError(
            f"dilating the declared envelope of "
            f"{declaration.declaration_id!r} by {MISMATCH_RESOLUTION_M} m "
            "produced an empty or invalid region, so there is nothing to "
            "adjudicate against."
        )
    return dilated


def escape_region(body: BaseGeometry, bound: BaseGeometry) -> BaseGeometry:
    """The part of `body` lying outside `bound`. Empty means no escape.

    `bound` is expected to be a `declared_bound` — already dilated. The set
    difference is used rather than `Polygon.covers` because `covers` answers a
    question about exact coordinates and the two polygons here are different
    floating-point renderings of boundaries that partly coincide: on a compliant
    fixture it reports an escape on most frames. The difference of the dilated
    pair reports none, on every compliant fixture at every seed.

    Raises:
        EnforcementError: either argument is not a geometry, or the overlay
            failed. A failed overlay is a could-not-evaluate — returning an empty
            geometry for it would read as "no escape", which is a pass.
    """
    for name, geometry in (("body", body), ("bound", bound)):
        if not isinstance(geometry, BaseGeometry):
            raise EnforcementError(
                f"escape_region {name} must be a shapely geometry, got "
                f"{type(geometry).__name__}."
            )
        if geometry.is_empty:
            raise EnforcementError(
                f"escape_region was given an empty {name}. An empty body is "
                "inside every bound and an empty bound contains nothing; both "
                "are failed computations, not answers."
            )
    try:
        return body.difference(bound)
    except Exception as exc:
        raise EnforcementError(
            f"the overlay of the commanded body against the declared bound "
            f"failed: {exc}. That is a could-not-evaluate; reporting no escape "
            "would let it pass as a PERMIT."
        ) from None


def body_polygon(state: ProprioState, limits: Limits) -> Polygon:
    """The robot's body at `state.q`: the union of its links. Layer A.

    This is what a commanded action *is*, for the purposes of the
    declaration/action mismatch check — the region the body occupies at the
    instant being adjudicated, not a forecast of where it might go. Both sides of
    that check are then exact polygons and the fault has no approximation in it.

    Raises:
        EnforcementError: `state` is not a `ProprioState` (a `StateFrame` is
            refused rather than narrowed — the narrowing belongs at the call
            site, where it is visible), or the union is empty or disconnected.
    """
    if not isinstance(state, ProprioState):
        raise EnforcementError(
            f"body_polygon takes a ProprioState, got {type(state).__name__}. This "
            "is the Layer A boundary: enforcement decides from what the robot "
            "knows about itself. If you hold a StateFrame, call .proprio()."
        )
    region = unary_union(list(link_polygons(state.q, limits)))
    if region.is_empty:
        raise EnforcementError(
            "the robot body came out empty. That is a failed computation, not a "
            "robot with no extent — an empty body is inside every declared bound."
        )
    if not isinstance(region, Polygon):
        raise EnforcementError(
            f"the robot body is a {type(region).__name__}, not a Polygon. "
            "Consecutive links share a joint, so the union is connected by "
            "construction; a disconnected result means the kinematics is wrong, "
            "and adjudicating against it would put that in the record."
        )
    return region


# --------------------------------------------------------------------------
# The enforcer.
# --------------------------------------------------------------------------


class Enforcer:
    """The Recovery Function: adjudicates every commanded action, emits verdicts.

    Stateful on purpose — six of the nine faults are about *history* (has a
    declaration arrived at all, has this `seq` been seen, has the channel gone
    quiet, are we passivated, has anyone acknowledged it) and a stateless check
    could detect none of them.

    Two inputs and one output. `offer(declaration)` takes what the policy says;
    `adjudicate(state)` takes what the robot is about to do; verdicts come back.
    Nothing goes the other way: enforcement never returns anything to the policy,
    because the black channel is the premise (docs/plan.md Phase 3). A caller
    that wires a verdict back into the policy has dismantled the argument, not
    closed the loop.

    Args:
        limits: the robot. The bound is computed from this and nothing else.
        key: the **enforcement** key. Signs verdicts and acknowledgments;
            `reg.chain.sign` refuses any other role.
        policy_key: the key declarations are verified under, or `None` for "no
            key available". `None` is explicit rather than omitted: a verifier
            without the key learns nothing about a record, and every declaration
            then reads as `unattributed` — which is a VETO, never a PERMIT.
        watchdog_period_s: seconds of silence from the declaration channel after
            which the robot is driven to a safe state. **Required, no default** —
            docs/plan.md fixes no watchdog period, and an invented one decides
            whether this check ever fires.
        t_start: the instant enforcement came up. **Required, no default** — the
            watchdog is measured from here until the first declaration arrives,
            and a run assumed to start at zero would have a watchdog that fired
            or did not for a reason nobody stated.
        id_prefix: prefix for the deterministic record ids, normally the scenario
            name. Same inputs, same ids, same MACs.

    Raises:
        EnforcementError: any argument is malformed or a key has the wrong role.
    """

    def __init__(
        self,
        limits: Limits,
        *,
        key: Key,
        policy_key: Key | None,
        watchdog_period_s: float,
        t_start: float,
        id_prefix: str,
    ) -> None:
        if not isinstance(limits, Limits):
            raise EnforcementError(
                f"limits must be a Limits, got {type(limits).__name__}."
            )
        if not isinstance(key, Key) or key.role != "enforcement":
            raise EnforcementError(
                f"key must be the enforcement Key, got {key!r}. Verdicts signed "
                "with the policy key would attribute enforcement's findings to "
                "the party they are findings about."
            )
        if policy_key is not None and (
            not isinstance(policy_key, Key) or policy_key.role != "policy"
        ):
            raise EnforcementError(
                f"policy_key must be the policy Key or None, got {policy_key!r}. "
                "None means 'no key available', which is could-not-evaluate; it "
                "is not a way to skip the check."
            )
        watchdog_period_s = _finite(watchdog_period_s, "watchdog_period_s")
        if watchdog_period_s <= 0.0:
            raise EnforcementError(
                f"watchdog_period_s must be strictly positive, got "
                f"{watchdog_period_s}. A zero or negative period expires at the "
                "instant enforcement starts, which is a safe state manufactured "
                "by the configuration rather than observed in the run."
            )
        _check_id(id_prefix, "id_prefix")

        self._limits = limits
        self._key = key
        self._policy_key = policy_key
        self._watchdog_period_s = watchdog_period_s
        self._id_prefix = id_prefix
        self._bound = computed_bound(limits)

        self._t_start = _finite(t_start, "t_start")
        #: When the declaration channel was last heard from. Receipt, not
        #: validity: the watchdog is a *liveness* check on the channel, so an
        #: invalid declaration still proves the policy is alive, and the fault it
        #: contains is reported by its own check rather than by this one.
        self._last_heard_t = self._t_start
        self._last_action_t: float | None = None

        self._open: Declaration | None = None
        #: The open declaration's region, dilated once at acceptance rather than
        #: per action. Always `None` exactly when `_open` is.
        self._open_bound: Polygon | None = None
        self._last_declaration_seq: int | None = None

        self._passivating_verdict_id: str | None = None
        self._passivation_fault: str | None = None
        self._acknowledged_verdict_id: str | None = None
        self._escalated = False

        self._prev_hash = GENESIS_HASH
        self._seq = 0
        self._verdicts: list[Verdict] = []
        self._acknowledgments: list[Acknowledgment] = []
        #: `verdict_id -> prose reason`. Beside the run, never in the record —
        #: see `reason()`.
        self._reasons: dict[str, str] = {}

    # -- read-only views -------------------------------------------------

    @property
    def verdicts(self) -> tuple[Verdict, ...]:
        """Every verdict emitted, in order. The stream Phase 5 builds edges from."""
        return tuple(self._verdicts)

    @property
    def acknowledgments(self) -> tuple[Acknowledgment, ...]:
        return tuple(self._acknowledgments)

    @property
    def head_hash(self) -> str:
        """`chain_hash` of the last record emitted, or `GENESIS_HASH` if none."""
        return self._prev_hash

    @property
    def is_passivated(self) -> bool:
        return self._passivation_fault is not None

    @property
    def passivation_fault(self) -> str | None:
        """The fault holding the enforcer passivated, or `None`."""
        return self._passivation_fault

    @property
    def open_declaration(self) -> Declaration | None:
        """The accepted declaration actions are adjudicated against, if any."""
        return self._open

    @property
    def bound(self) -> float:
        """The independently computed bound, metres. See `computed_bound`."""
        return self._bound

    @property
    def escalated(self) -> bool:
        """Whether an `escalate` declaration was received since passivating."""
        return self._escalated

    # -- declarations ----------------------------------------------------

    def offer(self, declaration: Declaration, state: ProprioState) -> Verdict | None:
        """Present a declaration. Returns a verdict **only if it is refused**.

        Four of the nine faults are properties of the declaration itself and are
        detected here, in this order — attribution first, because the other
        fields of a record nobody signed are not worth interpreting:

        1. **unattributed** — the MAC does not verify, or cannot be checked at
           all. Response: VETO. `reg.chain.verify` returns three states and
           `MacCheck` refuses to be used as a bool; both non-VALID states refuse
           the declaration, and the branch below is written as an explicit
           three-way so that COULD_NOT_EVALUATE cannot fall through to accept.
        2. **out_of_vocabulary_action** — `action_class` outside `ACTION_CLASSES`.
           Response: VETO. `Declaration.__post_init__` refuses to *construct* one,
           so this can only arrive in a record built elsewhere — which is exactly
           the case enforcement exists for, and why the check is here anyway.
        3. **replay_or_reorder** — `seq` reused or regressed against the highest
           accepted so far. Response: VETO.
        4. **envelope_overclaim** — the declared region reaches outside
           `horizon_bound(state, limits, ...)`. Response: VETO the declaration
           itself.

        Then the escalation obligation (see the module header): while passivated
        and unacknowledged, a declaration that is not an `escalate` is an
        **escalation_failure**, flagged and answered with a safe state.

        Args:
            declaration: what the policy says it will do. Checked, never
                believed.
            state: Layer A proprioception at the instant the bound is computed
                from. **Required, no default** (issue #82): the overclaim check
                is against the region the robot can reach within the
                declaration's own validity window, and that region is a function
                of where the arm is and how fast it is moving. An enforcer that
                invented a state here would compute a plausible bound for a robot
                that was somewhere else. Normally the frame at `t_issued`; an
                earlier one is accepted and the window is stretched to cover the
                gap, because reaching further back can only widen the bound.

        Returns:
            The refusing `Verdict`, or `None` when the declaration is accepted
            and becomes the open one. `None` is not "fine" in the sense a bool
            would be — accepting a declaration adjudicates no action, and
            adjudication is what a verdict is a record of.

        Raises:
            EnforcementError: `declaration` or `state` is of the wrong type, or
                `state` is *after* `t_issued` — the declaration's window has
                already left that pose, so a bound integrated forward from it
                would not cover the start of the interval being claimed.
        """
        if not isinstance(declaration, Declaration):
            raise EnforcementError(
                f"offer takes a Declaration, got {type(declaration).__name__}. "
                "Enforcement reads the record, not an object that resembles it."
            )
        if not isinstance(state, ProprioState):
            raise EnforcementError(
                f"offer takes a ProprioState as its second argument, got "
                f"{type(state).__name__}. This is the Layer A boundary: the "
                "bound is computed from what the robot knows about itself. If "
                "you hold a StateFrame, call .proprio()."
            )
        state_t = _finite(state.t, "state.t")
        if state_t > declaration.t_issued:
            raise EnforcementError(
                f"the state offered with declaration "
                f"{declaration.declaration_id!r} is at t={state_t}, after the "
                f"declaration was issued at t={declaration.t_issued}. The bound "
                "is integrated forward from this pose, so a pose the claimed "
                "interval has already left would bound a window that does not "
                "contain the interval — an unsound bound with a sound one's shape."
            )

        # Liveness is receipt, and receipt is unconditional: the policy sending
        # something wrong still proves the channel is alive, and conflating that
        # with validity would report a silent policy and a faulty one as the
        # same fault.
        self._last_heard_t = max(self._last_heard_t, declaration.t_issued)

        check = verify(declaration, declaration.mac, self._policy_key)
        if check.state is MacState.INVALID:
            return self._refuse(declaration, "unattributed", check.reason)
        if check.state is MacState.COULD_NOT_EVALUATE:
            # The consumer side of `MacCheck.__bool__` raising. A declaration
            # whose MAC nobody can check is unattributed — the record does not
            # say who made the claim — and the response is the same VETO as a
            # MAC that failed. What must never happen is either resolving to a
            # PERMIT, so there is no third branch here that accepts.
            return self._refuse(declaration, "unattributed", check.reason)
        if check.state is not MacState.VALID:  # pragma: no cover - MacState is closed
            raise EnforcementError(
                f"unhandled MAC state {check.state!r}; refusing to guess whether "
                "this record is attributed."
            )

        if declaration.action_class not in ACTION_CLASSES:
            return self._refuse(
                declaration,
                "out_of_vocabulary_action",
                f"action_class {declaration.action_class!r} is not in "
                f"{list(ACTION_CLASSES)}",
            )

        if (
            self._last_declaration_seq is not None
            and declaration.seq <= self._last_declaration_seq
        ):
            return self._refuse(
                declaration,
                "replay_or_reorder",
                f"seq {declaration.seq} does not advance on the highest accepted "
                f"seq {self._last_declaration_seq}",
            )

        # An unreadable bound raises rather than returning a verdict: it is a
        # could-not-evaluate, and neither PERMIT nor any of the nine faults would
        # be a true statement about it. `Declaration.__post_init__` makes it
        # unreachable for a record built here, which is the point.
        bound = declared_bound(declaration)
        # The window the declared region is a claim about, measured from the
        # pose the bound is integrated from. Equal to the declaration's own
        # horizon when the state is the frame at `t_issued`, which is the normal
        # case; stretched when the state is older, so the bound still covers the
        # whole of the interval being claimed.
        window = declaration.t_issued + declaration.horizon - state_t
        radius = horizon_bound(state, self._limits, window)
        # `horizon_excess` spelled out, so the bound is computed once and can be
        # named in the reason: an operator reading a VETO has to be able to see
        # which of the two bounds refused the declaration and by how much.
        excess = _furthest_vertex(declaration.envelope(), "offer") - radius
        if excess > 0.0:
            return self._refuse(
                declaration,
                "envelope_overclaim",
                f"the declared region reaches {excess:.4f} m beyond the "
                f"independently computed bound of {radius:.4f} m for a "
                f"{window:.4f} s window from this pose (the workspace disc, "
                f"which has no horizon in it, is {self._bound:.4f} m)",
            )

        if self.is_passivated and not self._is_acknowledged():
            if declaration.action_class == "escalate":
                # The policy did what it was obliged to do. Recorded, and it
                # still does not resume anything: reintegration needs the
                # acknowledgment as well.
                self._escalated = True
                return None
            return self._emit(
                declaration_id=declaration.declaration_id,
                t=declaration.t_issued,
                outcome="SAFE_STATE",
                fault="escalation_failure",
                clamped_envelope=None,
                reason=(
                    f"passivated by {self._passivation_fault!r} and not yet "
                    f"acknowledged, so an 'escalate' declaration was obliged; "
                    f"this one is a {declaration.action_class!r}"
                ),
            )

        self._open = declaration
        self._open_bound = bound
        self._last_declaration_seq = declaration.seq
        if self.is_passivated:
            # Reintegration: a fresh accepted declaration *and* an acknowledgment
            # naming the verdict that passivated us. Both, and in that order —
            # `acknowledge` refuses when nothing is passivated.
            self._passivating_verdict_id = None
            self._passivation_fault = None
            self._acknowledged_verdict_id = None
            self._escalated = False
        return None

    def _refuse(self, declaration: Declaration, fault: str, reason: str) -> Verdict:
        """VETO a declaration itself, as docs/plan.md's taxonomy specifies."""
        return self._emit(
            declaration_id=declaration.declaration_id,
            t=declaration.t_issued,
            outcome="VETO",
            fault=fault,
            clamped_envelope=None,
            reason=reason,
        )

    # -- actions ---------------------------------------------------------

    def adjudicate(self, state: ProprioState) -> Verdict:
        """Adjudicate one commanded action. Always returns a verdict.

        The remaining faults, in this order — the strongest response first, so
        that a robot already being driven to a safe state is not reported as
        merely lacking a declaration:

        1. **already passivated** — SAFE_STATE, carrying the fault that caused
           it. Recovery is not automatic (module header).
        2. **watchdog_expiry** — nothing heard from the declaration channel
           within `watchdog_period_s`. Response: drive to safe state. This is the
           *liveness* check and it is distinct from `no_declaration`, which is
           the *safety* one: a policy that has gone quiet and a policy that never
           declared are different failures with different remedies.
        3. **no_declaration** — no open declaration, or one that does not yet
           cover this instant. Response: VETO.
        4. **stale_declaration** — `t > t_issued + horizon`. Response: VETO, and
           the policy must re-declare.
        5. **declaration_action_mismatch** — the commanded body polygon is not
           covered by the declared envelope. Response: CLAMP to the declared
           bound, which is the only fault in the taxonomy that does not passivate.

        Otherwise PERMIT.

        Args:
            state: Layer A proprioception at the instant of the action. A
                `StateFrame` is refused rather than narrowed.

        Raises:
            EnforcementError: `state` is not a `ProprioState`, its `t` is not
                finite, or it precedes the previous action or `t_start`. Actions
                arriving out of order is a caller error, not a fault of the
                policy — the taxonomy's replay/reorder is about the *declaration*
                stream — and silently accepting one would make every watchdog and
                staleness comparison after it meaningless.
        """
        if not isinstance(state, ProprioState):
            raise EnforcementError(
                f"adjudicate takes a ProprioState, got {type(state).__name__}. "
                "This is the Layer A boundary and it is the whole argument: "
                "enforcement may not see the world. If you hold a StateFrame, "
                "call .proprio() — the narrowing belongs at the call site."
            )
        t = _finite(state.t, "state.t")
        if t < self._t_start:
            raise EnforcementError(
                f"action at t={t} precedes t_start={self._t_start}. The watchdog "
                "is measured from t_start; an action before it would be judged "
                "against a window that had not opened."
            )
        if self._last_action_t is not None and t < self._last_action_t:
            raise EnforcementError(
                f"action at t={t} precedes the previous action at "
                f"t={self._last_action_t}. Enforcement adjudicates a run "
                "forwards; time running backwards here is a caller error, and "
                "absorbing it would silently reset the watchdog."
            )
        self._last_action_t = t

        if self.is_passivated:
            assert self._passivation_fault is not None
            return self._emit(
                declaration_id=None,
                t=t,
                outcome="SAFE_STATE",
                fault=self._passivation_fault,
                clamped_envelope=None,
                reason=(
                    f"still passivated by verdict "
                    f"{self._passivating_verdict_id!r}; recovery needs a fresh "
                    "declaration and an acknowledgment"
                ),
                continuation=True,
            )

        if t - self._last_heard_t > self._watchdog_period_s:
            return self._emit(
                declaration_id=None,
                t=t,
                outcome="SAFE_STATE",
                fault="watchdog_expiry",
                clamped_envelope=None,
                reason=(
                    f"the declaration channel was last heard from at "
                    f"t={self._last_heard_t}, more than "
                    f"{self._watchdog_period_s} s ago"
                ),
            )

        declaration = self._open
        if declaration is None or t < declaration.t_issued:
            return self._emit(
                declaration_id=None if declaration is None else declaration.declaration_id,
                t=t,
                outcome="VETO",
                fault="no_declaration",
                clamped_envelope=None,
                reason=(
                    "no declaration has been accepted"
                    if declaration is None
                    else f"the open declaration was issued at "
                    f"t={declaration.t_issued}, after this action"
                ),
            )

        if t > declaration.t_issued + declaration.horizon:
            return self._emit(
                declaration_id=declaration.declaration_id,
                t=t,
                outcome="VETO",
                fault="stale_declaration",
                clamped_envelope=None,
                reason=(
                    f"the open declaration expired at "
                    f"t={declaration.t_issued + declaration.horizon}"
                ),
            )

        # Both sides are exact polygons, compared at the resolution the artifact
        # commits geometry to. `self._open_bound` is the declared region dilated
        # by one nanometre — see `escape_region` and the module header.
        assert self._open_bound is not None
        escape = escape_region(body_polygon(state, self._limits), self._open_bound)
        if not escape.is_empty:
            return self._emit(
                declaration_id=declaration.declaration_id,
                t=t,
                outcome="CLAMP",
                fault="declaration_action_mismatch",
                # The bound actually applied, verbatim from the record rather
                # than re-serialized: the overclaim check above has already
                # established that this region lies inside the independently
                # computed bound, so clamping to it is safe *because* of that
                # check and not because the declaration said so.
                clamped_envelope=declaration.declared_envelope,
                reason=(
                    f"{escape.area:.3e} m^2 of the commanded body lies outside "
                    "the declared envelope"
                ),
            )

        return self._emit(
            declaration_id=declaration.declaration_id,
            t=t,
            outcome="PERMIT",
            fault=None,
            clamped_envelope=None,
        )

    def adjudicate_all(self, states: Iterable[ProprioState]) -> tuple[Verdict, ...]:
        """`adjudicate` over a run, in order. Convenience, with no other behaviour."""
        return tuple(self.adjudicate(state) for state in states)

    # -- passivation and reintegration -----------------------------------

    def acknowledge(self, *, t: float, reason: str) -> Acknowledgment:
        """Record an acknowledgment of the current passivation. Half of recovery.

        The other half is a fresh declaration that passes every check in `offer`.
        Neither alone resumes anything, and this one is refused outright when
        nothing is passivated — a pre-emptive acknowledgment would let an
        operator clear a fault that has not happened yet, which is the same
        automatic recovery the asymmetry exists to prevent.

        Args:
            t: seconds, when the acknowledgment was made. Required.
            reason: why it is safe to resume. Required and non-empty.

        Returns:
            The signed, chained `Acknowledgment`.

        Raises:
            EnforcementError: nothing is passivated, or this passivation has
                already been acknowledged.
        """
        if not self.is_passivated:
            raise EnforcementError(
                "there is nothing to acknowledge: the enforcer is not "
                "passivated. An acknowledgment recorded now would sit in the "
                "chain ready to clear the next fault before it happened."
            )
        assert self._passivating_verdict_id is not None
        assert self._passivation_fault is not None
        if self._is_acknowledged():
            raise EnforcementError(
                f"verdict {self._passivating_verdict_id!r} has already been "
                "acknowledged; it is waiting on a fresh declaration, not on a "
                "second acknowledgment."
            )

        ack = Acknowledgment(
            ack_id=f"{self._id_prefix}-ack-{len(self._acknowledgments):05d}",
            t=_finite(t, "t"),
            fault=self._passivation_fault,
            verdict_id=self._passivating_verdict_id,
            reason=reason,
            prev_hash=self._prev_hash,
            mac=UNSIGNED_MAC,
        )
        signed = sign_acknowledgment(ack, self._key)
        self._acknowledgments.append(signed)
        self._prev_hash = chain_hash(signed, self._prev_hash)
        self._acknowledged_verdict_id = self._passivating_verdict_id
        return signed

    def _is_acknowledged(self) -> bool:
        """Whether *this* passivation has been acknowledged.

        Bound to the verdict id, not to a flag: acknowledging a stale declaration
        at t=3 must not clear a different fault raised at t=9, and a new
        passivation therefore invalidates an acknowledgment that named the old one.
        """
        return (
            self._passivating_verdict_id is not None
            and self._acknowledged_verdict_id == self._passivating_verdict_id
        )

    # -- record emission -------------------------------------------------

    def reason(self, verdict_id: str) -> str | None:
        """Why a verdict came out the way it did, in prose. **Not in the record.**

        The `Verdict` schema in docs/plan.md carries the fault and no free-text
        field, deliberately: the taxonomy is the vocabulary a query filters on,
        and a prose column becomes the place findings go to be unqueryable. But a
        check whose response is VETO has to be diagnosable by whoever it stopped,
        so the sentence is kept here, beside the run, and goes no further.

        Returns `None` for a PERMIT and for an id this enforcer did not issue.
        """
        return self._reasons.get(verdict_id)

    def _emit(
        self,
        *,
        declaration_id: str | None,
        t: float,
        outcome: str,
        fault: str | None,
        clamped_envelope: bytes | None,
        reason: str = "",
        continuation: bool = False,
    ) -> Verdict:
        """Build, sign and chain one verdict, and passivate if the fault demands it.

        `continuation=True` marks a verdict that merely *reports* an existing
        passivation rather than raising a new fault. Without the distinction,
        every SAFE_STATE emitted while passivated would look like a fresh fault,
        supersede the passivation it was reporting, and discard the
        acknowledgment that had just been recorded against it — so recovery
        would be impossible for exactly as long as the robot kept trying to move.
        """
        verdict = Verdict(
            verdict_id=f"{self._id_prefix}-verdict-{self._seq:05d}",
            declaration_id=declaration_id,
            seq=self._seq,
            t=t,
            outcome=outcome,
            fault=fault,
            clamped_envelope=clamped_envelope,
            prev_hash=self._prev_hash,
            mac=UNSIGNED_MAC,
        )
        signed = sign_verdict(verdict, self._key)
        self._verdicts.append(signed)
        self._prev_hash = chain_hash(signed, self._prev_hash)
        self._seq += 1
        if reason:
            self._reasons[signed.verdict_id] = reason

        if fault is not None and fault in PASSIVATING_FAULTS and not continuation:
            # A new passivation supersedes an old one and drops any
            # acknowledgment that named the old one: an operator who cleared a
            # stale declaration did not thereby clear a forged one.
            self._passivating_verdict_id = signed.verdict_id
            self._passivation_fault = fault
            self._acknowledged_verdict_id = None
            self._open = None
            self._open_bound = None
        return signed
