"""The declaration record, and the scripted policy that emits it. **Phase 3.**

WHAT A DECLARATION IS
---------------------
A machine-readable statement of intent, issued *before* actuating: "over the next
`horizon` seconds I intend to do a `reach`, and I will keep my body inside this
region." It is signed with the policy key and linked to its predecessor, so a
reader months later can tell both that the statement was not edited afterwards
and which side made it.

The record is Layer A — a declaration, like a verdict and like the chain, is
certifiable evidence. The *policy* that emits it is not. That asymmetry is the
whole design: the black channel of IEC 61784-3 applied to semantics rather than
transport (docs/plan.md, Phase 3).

NOT NOVEL, AND SAY SO
---------------------
docs/prior-art.md §10: there is a 2026 line of work on cryptographic runtime
governance where software agents declare intent before acting, receive signed
authority tokens, and leave a tamper-evident log. That is recognisably this
shape and this project must not claim an empty field. What is distinct is the
domain — a *physical* control policy, where the bound is a region of space a body
may occupy and the failure is contact with a person — and the lineage, which is
industrial functional safety (IEC 61784-3, PROFIsafe's fault taxonomy) rather
than zero-trust.

THE POLICY IS DELIBERATELY IMPERFECT AND DELIBERATELY DUMB
----------------------------------------------------------
`emit_declarations` is the black channel side. It is scripted, it has no feedback
from enforcement, and it must never gain any: enforcement does not exist yet, and
the premise of the whole argument is that the policy is uncertified and out of
scope. It also does not have to be *right* — given a fixed declared box (the
`declared_q_bounds` of `reg.scenarios.DECLARED_VIOLATION`) it will happily
declare one bound and then command outside it. A policy that never violates its
own declaration would make Phase 4's fault taxonomy undemonstrable.

Two consequences of the same rule, stated because they look like omissions:

* This module imports nothing from `reg.world` or `reg.scenarios`, and it will
  import nothing from `reg.enforce`. It takes `ProprioState`s. That keeps the
  Layer B world out of the module that builds a Layer A record — the caller
  narrows a `StateFrame` with `.proprio()`, and the narrowing is visible at the
  call site (`reg/types.py`).
* The scripted policy never emits `escalate`. The vocabulary has it because
  Phase 4 needs to detect an *escalation failure* — conditions met and no
  `escalate` declaration issued — and a policy that emitted one would remove the
  fixture that fault is demonstrated against.

DECLARATIONS ARE COARSE
-----------------------
One per replan interval, not one per frame. That is part of the compression story
and part of the argument: a declaration is a statement about an interval of
intent, so there are tens of them in a run of hundreds of frames, and none is
ever summarised or dropped (docs/lossiness.md).
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from typing import ClassVar

import numpy as np
import shapely
from shapely.geometry import Polygon
from shapely.ops import unary_union

from reg.chain import (
    GENESIS_HASH,
    UNSIGNED_MAC,
    Key,
    MacCheck,
    Role,
    chain_hash,
    is_hash,
    sign,
    verify,
)
from reg.kinematics import forward_kinematics, link_polygons
from reg.types import Limits, ProprioState

__all__ = [
    "ACTION_CLASSES",
    "MAX_GRID_CONFIGS",
    "Declaration",
    "DeclarationError",
    "box_grid",
    "declared_region",
    "emit_declarations",
    "envelope_wkb",
    "sign_declaration",
    "verify_declaration",
]

#: The whole `action_class` vocabulary, from docs/plan.md Phase 3. Fixed, small,
#: and defined **here only** — enforcement imports this tuple rather than
#: restating it, because two copies of a vocabulary is how an out-of-vocabulary
#: declaration becomes undetectable on one side and a fault on the other.
ACTION_CLASSES: tuple[str, ...] = ("reach", "hold", "retract", "traverse", "escalate")

#: Upper bound on the number of joint configurations `declared_region` will
#: sample for one declaration. A resource guard, not a physical threshold: the
#: grid resolution below is *derived* from the geometry, so a box wide enough to
#: exceed this is a box covering most of the workspace, and a declaration that
#: expensive is no longer the cheap coarse record this phase is about. Exceeding
#: it is a loud refusal, never a silently coarser grid.
MAX_GRID_CONFIGS = 50_000


class DeclarationError(ValueError):
    """A declaration could not be constructed or emitted as specified.

    Construction-time, on purpose: an invalid declaration must not exist long
    enough to be signed. An out-of-vocabulary `action_class` is a fault Phase 4
    detects *in a record someone else produced* — it is not a state this
    producer is allowed to reach.
    """


@dataclass(frozen=True)
class Declaration:
    """The policy's statement of intent. Fields exactly as docs/plan.md Phase 3.

    Frozen, like everything that reaches the record: a declaration that can be
    edited after it is signed is not evidence. `sign_declaration` returns a new
    instance rather than filling in `mac`.

    Args:
        declaration_id: unique within a run and deterministic. Not a UUID —
            same seed, same bytes (CLAUDE.md rule 2), and a random id would make
            two runs of the same command produce different records.
        seq: monotonic within a run, from 0. Reuse or regression is the
            replay/reorder fault in Phase 4's taxonomy, which is only detectable
            because this is here.
        t_issued: seconds, the instant the policy issued it.
        horizon: seconds of validity. `t > t_issued + horizon` is the stale
            declaration fault.
        action_class: one of `ACTION_CLASSES`. Anything else is refused here.
        declared_envelope: WKB of the polygon the policy claims it will stay
            within. WKB rather than a geometry object because the record is
            bytes: a shapely object cannot be hashed, chained or stored.
        prev_hash: the previous record's `chain_hash`, or `GENESIS_HASH` for the
            first.
        mac: HMAC over every other field under the **policy** key, or
            `UNSIGNED_MAC` before signing.
    """

    #: Only the policy signs declarations. `reg.chain.sign` refuses any other
    #: key, so the enforcement key cannot be used to fabricate one.
    SIGNING_ROLE: ClassVar[Role] = "policy"

    declaration_id: str
    seq: int
    t_issued: float
    horizon: float
    action_class: str
    declared_envelope: bytes
    prev_hash: str
    mac: str

    def __post_init__(self) -> None:
        if not isinstance(self.declaration_id, str) or not self.declaration_id:
            raise DeclarationError(
                f"declaration_id must be a non-empty str, got "
                f"{self.declaration_id!r}. It is how a verdict names the "
                "declaration it adjudicated."
            )
        if any(c.isspace() or ord(c) < 0x20 for c in self.declaration_id):
            raise DeclarationError(
                f"declaration_id {self.declaration_id!r} contains whitespace or a "
                "control character. It is an identifier that ends up in a "
                "canonical serialization and in a store key; a newline in it "
                "would make the record's text form ambiguous."
            )
        if isinstance(self.seq, bool) or not isinstance(self.seq, (int, np.integer)):
            raise DeclarationError(
                f"seq must be an int, got {self.seq!r}. It is what makes replay "
                "and reorder detectable."
            )
        object.__setattr__(self, "seq", int(self.seq))
        if self.seq < 0:
            raise DeclarationError(f"seq must be >= 0, got {self.seq}.")

        object.__setattr__(self, "t_issued", _finite(self.t_issued, "t_issued"))
        object.__setattr__(self, "horizon", _finite(self.horizon, "horizon"))
        if self.horizon <= 0.0:
            raise DeclarationError(
                f"horizon must be strictly positive, got {self.horizon}. A "
                "declaration with a zero or negative validity window is stale "
                "the instant it is issued, which is a fault to detect and not a "
                "record to produce."
            )

        if self.action_class not in ACTION_CLASSES:
            raise DeclarationError(
                f"action_class {self.action_class!r} is not in the vocabulary "
                f"{list(ACTION_CLASSES)}. The vocabulary is fixed and small so "
                "that an out-of-vocabulary action is a *detectable fault* in a "
                "record that arrives from elsewhere — this producer refuses to "
                "create one, so an invalid declaration cannot be signed into the "
                "chain in the first place."
            )

        _parse_wkb(self.declared_envelope)

        if not is_hash(self.prev_hash):
            raise DeclarationError(
                f"prev_hash {self.prev_hash!r} is not a SHA-256 hex digest. The "
                f"first record of a chain links to GENESIS_HASH; every other "
                "links to its predecessor's chain_hash."
            )
        if self.mac != UNSIGNED_MAC and not is_hash(self.mac):
            raise DeclarationError(
                f"mac {self.mac!r} is neither UNSIGNED_MAC nor a SHA-256 hex "
                "digest. A malformed MAC is a could-not-evaluate for every "
                "reader, and one produced here would be this side's fault."
            )

    @property
    def is_signed(self) -> bool:
        """Whether a MAC is present. Says nothing about whether it is correct."""
        return self.mac != UNSIGNED_MAC

    def envelope(self) -> Polygon:
        """The declared region as a polygon. Parsed fresh; the record is the WKB."""
        return _parse_wkb(self.declared_envelope)


def _finite(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(
        value, (int, float, np.integer, np.floating)
    ):
        raise DeclarationError(f"{name} must be a number, got {value!r}.")
    out = float(value)
    if not math.isfinite(out):
        raise DeclarationError(
            f"{name} is {out!r}. A non-finite time or window in a record makes "
            "every staleness comparison downstream vacuously true or vacuously "
            "false, with nothing reporting which."
        )
    return out


def _parse_wkb(payload: object) -> Polygon:
    """The declared envelope as a polygon, or a construction-time refusal."""
    if not isinstance(payload, bytes):
        raise DeclarationError(
            f"declared_envelope must be WKB bytes, got {type(payload).__name__}. "
            "The record is bytes: a shapely object cannot be hashed, chained or "
            "stored, and converting one here would hide where the conversion "
            "happened."
        )
    if not payload:
        raise DeclarationError(
            "declared_envelope is empty. An empty declared bound is not 'no "
            "claim' — every containment test against it passes vacuously."
        )
    try:
        geometry = shapely.from_wkb(payload)
    except Exception as exc:  # shapely raises several types for bad WKB
        raise DeclarationError(
            f"declared_envelope is not readable as WKB: {exc}. Refusing to "
            "construct: a declaration whose bound cannot be read is one Phase 4 "
            "can only report as could-not-evaluate, and it must not be signed "
            "into the chain by this side."
        ) from None
    if not isinstance(geometry, Polygon):
        raise DeclarationError(
            f"declared_envelope is a {type(geometry).__name__}, not a Polygon. "
            "A declared bound is one connected region the body will stay inside."
        )
    if geometry.is_empty:
        raise DeclarationError(
            "declared_envelope is an empty polygon, which every containment "
            "test reads as 'the body may be nowhere' rather than as the failed "
            "computation it is."
        )
    if not geometry.is_valid:
        raise DeclarationError(
            f"declared_envelope is an invalid polygon: "
            f"{shapely.is_valid_reason(geometry)}. Containment against an "
            "invalid polygon is not meaningful."
        )
    return geometry


def envelope_wkb(polygon: Polygon) -> bytes:
    """Canonical WKB for a declared region. Same polygon, same bytes.

    Normalised first (canonical ring order and orientation) and written with
    every option pinned — 2 dimensions, little-endian, no SRID — because the
    bytes go straight into a hash chain. A WKB whose byte order followed the host
    would give the same region two different digests on two machines.
    """
    if not isinstance(polygon, Polygon):
        raise DeclarationError(
            f"envelope_wkb takes a Polygon, got {type(polygon).__name__}."
        )
    if polygon.is_empty or not polygon.is_valid:
        raise DeclarationError(
            "envelope_wkb was given an empty or invalid polygon; that is a "
            "failed computation and must not become a declared bound."
        )
    return shapely.to_wkb(
        shapely.normalize(polygon),
        output_dimension=2,
        byte_order=1,
        include_srid=False,
        flavor="iso",
    )


def sign_declaration(declaration: Declaration, key: Key) -> Declaration:
    """Return a copy carrying its MAC under the policy key.

    Refuses a declaration that is already signed: re-signing would overwrite one
    party's attribution with another's, and the second MAC would verify.
    """
    if not isinstance(declaration, Declaration):
        raise TypeError(
            f"sign_declaration takes a Declaration, got {type(declaration).__name__}."
        )
    if declaration.is_signed:
        raise DeclarationError(
            f"declaration {declaration.declaration_id!r} is already signed. "
            "Re-signing would replace an existing attribution with a new one "
            "that verifies, which is precisely the edit the chain exists to make "
            "visible."
        )
    return replace(declaration, mac=sign(declaration, key))


def verify_declaration(declaration: Declaration, key: Key | None) -> MacCheck:
    """Check a declaration's MAC. Three states — see `reg.chain.verify`.

    An unsigned declaration is `COULD_NOT_EVALUATE`, not `INVALID`: it is
    unattributed, which is a state a reader has to see rather than an accusation.
    """
    if not isinstance(declaration, Declaration):
        raise TypeError(
            f"verify_declaration takes a Declaration, got "
            f"{type(declaration).__name__}."
        )
    return verify(declaration, declaration.mac, key)


# --------------------------------------------------------------------------
# The declared region: a set of joint configurations, rendered as the workspace
# polygon the policy is claiming its body will stay inside.
#
# A declaration has to be a region of *space* — that is what enforcement can
# check a body against, and what a reader can put on a plot. So the region is
# the union of the arm's body over a set of configurations, and the two ways of
# choosing that set are the two things a policy can be doing:
#
#   the configurations it is about to occupy   -> a true statement about itself
#   a grid over a joint box it has declared    -> a claim it can then violate
#
# `emit_declarations` uses the first when the caller passes no fixed box and the
# second when it does. `reg.scenarios.DECLARED_VIOLATION` passes one.
#
# THE GRID RESOLUTION IS DERIVED, NOT PICKED. Rotating joint `i` by `dq` moves
# any point of the body it carries by at most `dq * reach[i]`, where `reach[i]`
# is the length of everything from joint `i` outwards. Step the grid so that
# distance is at most one `link_radius` and the bodies at adjacent grid poses
# overlap, so their union is a covering of the box rather than a comb of
# disjoint slabs. There is no tolerance to invent.
#
# WHAT THE REGION IS NOT. It is the union of bodies at *sampled* configurations,
# not the continuous swept set: between two adjacent samples the body bulges
# outside their union by the arc-versus-chord sagitta, of order
# `reach * dq**2 / 8` — sub-millimetre at the resolution above. Stated rather
# than hidden. Everything in this artifact is sampled at the run's frame rate,
# including the poses Phase 4 will check against this bound, so the declaration
# is a statement at the same resolution as the evidence it will be judged by.
# --------------------------------------------------------------------------


def _reach(limits: Limits) -> np.ndarray:
    """`reach[i]` = the length of the arm from joint `i` outwards, in metres."""
    lengths = np.asarray(limits.link_lengths, dtype=float)
    return np.cumsum(lengths[::-1])[::-1]


def _grid_steps(box: Sequence[tuple[float, float]], limits: Limits) -> tuple[int, ...]:
    """Samples per joint, from the geometry. See the block comment above."""
    radius = float(limits.link_radius)
    if not math.isfinite(radius) or radius <= 0.0:
        raise DeclarationError(
            f"limits.link_radius must be finite and positive, got {radius!r}; it "
            "is what the grid resolution is derived from."
        )
    reach = _reach(limits)
    steps: list[int] = []
    for i, (lo, hi) in enumerate(box):
        width = hi - lo
        if width == 0.0:
            steps.append(1)
            continue
        steps.append(int(math.ceil(width * reach[i] / radius)) + 1)
    return tuple(steps)


def _check_box(box: object, limits: Limits, where: str) -> tuple[tuple[float, float], ...]:
    n = int(np.asarray(limits.link_lengths).shape[0])
    if not isinstance(box, (tuple, list)) or len(box) != n:
        raise DeclarationError(
            f"{where}: a joint box needs one (lo, hi) pair per joint; this arm "
            f"has {n} and the box is {box!r}."
        )
    out: list[tuple[float, float]] = []
    for i, pair in enumerate(box):
        if not isinstance(pair, (tuple, list)) or len(pair) != 2:
            raise DeclarationError(f"{where}: joint {i} bound {pair!r} is not (lo, hi).")
        lo = _finite(pair[0], f"{where} joint {i} lower bound")
        hi = _finite(pair[1], f"{where} joint {i} upper bound")
        if hi < lo:
            raise DeclarationError(
                f"{where}: joint {i} bound ({lo}, {hi}) is inverted; there is no "
                "configuration inside it, so the declared region would be empty "
                "and every containment test against it would pass vacuously."
            )
        out.append((lo, hi))
    return tuple(out)


def box_grid(box: Sequence[tuple[float, float]], limits: Limits) -> np.ndarray:
    """The configurations a declared joint box is sampled at. `(m, n_joints)`.

    Args:
        box: one `(lo, hi)` pair per joint, radians. A degenerate pair
            (`lo == hi`) contributes a single value.
        limits: the robot. `link_lengths` and `link_radius` set the resolution;
            see the block comment above.

    Raises:
        DeclarationError: the box is malformed, or sampling it at the derived
            resolution would need more than `MAX_GRID_CONFIGS` configurations.
    """
    checked = _check_box(box, limits, "box_grid")
    steps = _grid_steps(checked, limits)
    # math.prod, not np.prod: the product of a wide box's step counts overflows
    # int64 and comes back negative, which would slip straight past the guard.
    total = math.prod(steps)
    if total > MAX_GRID_CONFIGS:
        raise DeclarationError(
            f"declaring this box would sample {total} configurations "
            f"({' x '.join(str(s) for s in steps)}), over the "
            f"{MAX_GRID_CONFIGS} guard. The resolution is derived from the arm's "
            "geometry, so this is a box spanning most of the workspace — a bound "
            "that wide is not a claim worth signing. Refusing rather than "
            "sampling coarser: a coarser grid would silently return a region "
            "with gaps in it."
        )
    axes = [np.linspace(lo, hi, n) for (lo, hi), n in zip(checked, steps, strict=True)]
    return np.asarray(list(itertools.product(*axes)), dtype=float).reshape(total, -1)


def declared_region(configs: np.ndarray | Sequence[Sequence[float]], limits: Limits) -> Polygon:
    """The workspace polygon for a set of configurations: the union of the bodies.

    Args:
        configs: `(m, n_joints)` joint configurations, radians. Either the poses
            the policy is about to occupy or `box_grid` of a box it is claiming.
        limits: the robot, for forward kinematics.

    Returns:
        A single `Polygon`. Connected by construction — every configuration's
        first link contains the base — so a `MultiPolygon` here would mean the
        geometry is wrong and is refused rather than reported.

    Raises:
        DeclarationError: `configs` is empty or malformed, or the union is empty
            or disconnected. Each is a could-not-evaluate, never a small region.
    """
    array = np.asarray(configs, dtype=float)
    if array.ndim != 2 or array.shape[0] == 0:
        raise DeclarationError(
            f"declared_region takes a non-empty (m, n_joints) array of "
            f"configurations, got shape {array.shape}. A declaration over no "
            "configuration is an empty bound, and every containment test against "
            "an empty bound passes vacuously."
        )

    polygons: list[Polygon] = []
    for config in array:
        polygons.extend(link_polygons(config, limits))

    region = unary_union(polygons)
    if region.is_empty:
        raise DeclarationError(
            "the declared region came out empty. That is a failed computation, "
            "not a policy that intends to occupy nowhere."
        )
    if not isinstance(region, Polygon):
        raise DeclarationError(
            f"the declared region is a {type(region).__name__}, not a Polygon. "
            "Every sampled configuration's first link contains the base, so the "
            "union is connected by construction; a disconnected result means the "
            "grid or the kinematics is wrong, and signing it would put that in "
            "the record."
        )
    return region


# --------------------------------------------------------------------------
# The scripted policy.
# --------------------------------------------------------------------------


def _classify(configs: np.ndarray, limits: Limits) -> str:
    """The `action_class` for one interval. Deliberately crude — see the header.

    No tolerance anywhere: a configuration set that does not move at all is a
    `hold`, and the reach comparison between the first and last configuration is
    exact, with the tie going to `traverse`. A threshold here ("moved less than
    x") would be an invented number in a field of the record, which is the one
    place this project refuses to put one.
    """
    if np.array_equal(configs.min(axis=0), configs.max(axis=0)):
        return "hold"
    start = float(np.linalg.norm(forward_kinematics(configs[0], limits)[-1][1]))
    end = float(np.linalg.norm(forward_kinematics(configs[-1], limits)[-1][1]))
    if end > start:
        return "reach"
    if end < start:
        return "retract"
    return "traverse"


def _intervals(states: Sequence[ProprioState], replan_interval_s: float) -> list[tuple[int, int]]:
    """`(first, last)` index pairs, one per replan interval, ends inclusive.

    A new declaration is issued at the first state at or after
    `replan_interval_s` since the last one was issued. Consecutive intervals
    **share their boundary state**: the declaration issued at `t` has to cover
    the motion up to the instant the next one is issued, and a half-open
    interval would leave the boundary pose declared by nobody — which Phase 4
    would correctly report as actuation with no open declaration.
    """
    intervals: list[tuple[int, int]] = []
    issued_at = 0
    for i in range(1, len(states)):
        if states[i].t - states[issued_at].t >= replan_interval_s:
            intervals.append((issued_at, i))
            issued_at = i
    intervals.append((issued_at, len(states) - 1))
    return intervals


def emit_declarations(
    states: Iterable[ProprioState],
    limits: Limits,
    *,
    key: Key,
    replan_interval_s: float,
    horizon_s: float,
    declared_q_bounds: Sequence[tuple[float, float]] | None,
    id_prefix: str,
) -> tuple[Declaration, ...]:
    """The scripted policy: one signed, chained declaration per replan interval.

    The policy is the black channel. It sees proprioception because that is all
    this fixture needs, it has no feedback from enforcement, and it must never
    acquire any — see the module header.

    Args:
        states: the run's proprioceptive states, in time order. Narrow a
            `StateFrame` with `.proprio()` at the call site.
        limits: the robot, for the forward kinematics of the declared region.
        key: the **policy** key. `reg.chain.sign` refuses any other role.
        replan_interval_s: seconds between declarations. Required and with no
            default — docs/plan.md fixes neither a replan rate nor a watchdog
            period, and a plausible invented one would be indistinguishable
            downstream from a stated one, in a number that sets how coarse the
            entire declaration stream is.
        horizon_s: the validity window each declaration claims. Required, and
            must be at least `replan_interval_s`, or the run contains instants
            covered by no valid declaration.
        declared_q_bounds: the fixed joint box the policy declares for **every**
            interval, or `None` to declare exactly the region its own upcoming
            configurations sweep. Required — no default, because the two are
            different statements and neither is a safe assumption about a
            policy. The fixed box is the interesting case: it is a claim the
            policy makes independently of what it then does, so it can be false,
            which is what `reg.scenarios.DECLARED_VIOLATION` exists to produce.
        id_prefix: prefix for the deterministic `declaration_id`s, normally the
            scenario name.

    Returns:
        The declarations in issue order, each signed and each linked to its
        predecessor. The first links to `GENESIS_HASH`.

    Raises:
        DeclarationError: any argument is malformed, the states are not in
            strictly increasing time order, or a declared region cannot be built.
        KeyRoleError: `key` is not the policy key.
    """
    states = tuple(states)
    if not states:
        raise DeclarationError(
            "no states to declare over. An empty run produces no declarations, "
            "which is indistinguishable downstream from a policy that declared "
            "nothing — so it is refused here instead."
        )
    for i, state in enumerate(states):
        if not isinstance(state, ProprioState):
            raise DeclarationError(
                f"states[{i}] is a {type(state).__name__}, not a ProprioState. "
                "The policy takes proprioception; narrow a StateFrame with "
                ".proprio() at the call site — that narrowing is the Layer "
                "boundary and it is visible on purpose (reg/types.py)."
            )
        _finite(state.t, f"states[{i}].t")
        if i and not state.t > states[i - 1].t:
            raise DeclarationError(
                f"states[{i}].t = {state.t} does not follow states[{i - 1}].t = "
                f"{states[i - 1].t}. Declarations are issued against elapsed "
                "time; a run whose time does not advance would put several of "
                "them at one instant, which is the replay fault, self-inflicted."
            )

    replan_interval_s = _finite(replan_interval_s, "replan_interval_s")
    horizon_s = _finite(horizon_s, "horizon_s")
    if replan_interval_s <= 0.0:
        raise DeclarationError(
            f"replan_interval_s must be strictly positive, got "
            f"{replan_interval_s}."
        )
    if horizon_s < replan_interval_s:
        raise DeclarationError(
            f"horizon_s={horizon_s} is shorter than replan_interval_s="
            f"{replan_interval_s}. Each declaration would expire before its "
            "successor was issued, leaving instants in the run covered by no "
            "valid declaration — a stale-declaration fault manufactured by the "
            "producer rather than committed by the policy."
        )
    if not isinstance(id_prefix, str) or not id_prefix:
        raise DeclarationError(
            f"id_prefix must be a non-empty str, got {id_prefix!r}; it is what "
            "makes declaration_id readable and unique to a run."
        )

    # The fixed box, if there is one, is the same claim in every interval, so
    # its region is computed once. Nothing is approximated by the reuse: the
    # same configurations have the same union by construction.
    fixed_wkb: bytes | None = None
    if declared_q_bounds is not None:
        box = _check_box(declared_q_bounds, limits, "declared_q_bounds")
        fixed_wkb = envelope_wkb(declared_region(box_grid(box, limits), limits))

    declarations: list[Declaration] = []
    prev_hash = GENESIS_HASH
    for seq, (first, last) in enumerate(_intervals(states, replan_interval_s)):
        configs = np.asarray(
            [np.asarray(s.q, dtype=float) for s in states[first : last + 1]],
            dtype=float,
        )
        wkb = (
            fixed_wkb
            if fixed_wkb is not None
            else envelope_wkb(declared_region(configs, limits))
        )

        unsigned = Declaration(
            declaration_id=f"{id_prefix}-decl-{seq:05d}",
            seq=seq,
            t_issued=float(states[first].t),
            horizon=horizon_s,
            action_class=_classify(configs, limits),
            declared_envelope=wkb,
            prev_hash=prev_hash,
            mac=UNSIGNED_MAC,
        )
        signed = sign_declaration(unsigned, key)
        declarations.append(signed)
        prev_hash = chain_hash(signed, prev_hash)

    return tuple(declarations)
