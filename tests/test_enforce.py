"""Enforcement: the independent bound, the `Verdict`, and the nine faults.

Five things this file is really about.

* **Every fault has a negative test.** One per taxonomy entry, each feeding the
  condition the check guards against and asserting the named fault *and* the
  response docs/plan.md specifies. A fault with only a happy-path test is
  described, not implemented — so each negative is paired with the positive
  control that must *not* trip it.
* **Enforcement never trusts the declaration.** The import restriction is
  asserted against the source, and a declaration claiming an enormous envelope
  is refused by the independently computed bound rather than believed.
* **Could-not-evaluate is not PERMIT.** `reg.chain.MacCheck` refuses to be used
  as a bool; this is the consumer side of that, and the assertion is the strong
  one — not "the third state is handled" but "no PERMIT is ever emitted".
* **The bound does not cry wolf.** `compute_envelope` under-approximates, so a
  declared region larger than the sampled one is *not* an overclaim. There is a
  test that an honest declaration bigger than the sampled envelope is accepted,
  because getting that wrong is how this check would fail in the direction
  nobody notices.
* **Every semantic fault has occurred in a run, not only in a unit test.** The
  last section adjudicates the fault fixtures of `reg.scenarios` end to end —
  real declarations, real enforcer, several seeds — because a detector that
  works on a record built three lines earlier says nothing about whether the
  fault can happen. Each of those fixtures is one policy behaviour away from a
  clean run, and taking the behaviour away has to leave PERMIT on every frame.
"""

from __future__ import annotations

import ast
import dataclasses
import math
import pathlib
from collections import Counter

import numpy as np
import pytest
import shapely
from shapely.geometry import Polygon, box
from shapely.ops import unary_union

import reg.enforce
from reg.chain import (
    GENESIS_HASH,
    HASH_HEX_LEN,
    KEY_BYTES,
    UNSIGNED_MAC,
    KeyRoleError,
    Keyring,
    MacState,
    chain_hash,
    sign,
)
from reg.declare import (
    ACTION_CLASSES,
    Declaration,
    box_grid,
    declared_region,
    emit_declarations,
    envelope_wkb,
    sign_declaration,
    verify_declaration,
)
from reg.enforce import (
    FAULTS,
    MISMATCH_RESOLUTION_M,
    OUTCOMES,
    Acknowledgment,
    EnforcementError,
    Enforcer,
    Verdict,
    body_polygon,
    computed_bound,
    declared_bound,
    envelope_excess,
    escape_region,
    horizon_bound,
    horizon_excess,
    sign_acknowledgment,
    sign_verdict,
    verify_acknowledgment,
    verify_verdict,
)
from reg.envelope import (
    HASH_COORD_PRECISION,
    compute_envelope,
    envelope_area,
    outer_envelope,
    outer_radius,
)
from reg.kinematics import ORIGIN_FRAME, BaseFrame, link_polygons
from reg.scenarios import SCENARIOS, Scenario
from reg.types import (
    BaseVelocity,
    Limits,
    LimitSource,
    Obstacle,
    ProprioState,
    StateFrame,
)
from reg.world import DEMO_WORLD

KEYRING = Keyring.from_material(
    policy=bytes(range(KEY_BYTES)), enforcement=bytes(range(100, 100 + KEY_BYTES))
)
POLICY_KEY = KEYRING.key("policy")
ENFORCEMENT_KEY = KEYRING.key("enforcement")

#: A second, unrelated keyring. Used to produce a declaration whose MAC is
#: well-formed and simply not this verifier's — the INVALID half of unattributed.
OTHER_KEYRING = Keyring.from_material(
    policy=bytes(range(200, 200 + KEY_BYTES)),
    enforcement=bytes(range(300 % 256, 300 % 256 + KEY_BYTES)),
)

LIMITS: Limits = DEMO_WORLD.limits

# The enforcer's parameters, stated by the test because `Enforcer` refuses to
# invent either of them. Both are far longer than the intervals the synthetic
# cases use, so a fault in one of these tests is the fault the test is about.
WATCHDOG_S = 1.0
T_START = 0.0
HORIZON_S = 0.5

#: The integration grid this file's enforcers compute their overclaim bound on,
#: seconds. Stated here for the reason the two above are (issue #106):
#: `Enforcer` refuses to invent one, and a test that reached for
#: `reg.envelope.SUBSTEP_DT` would be asserting against whatever that constant
#: happens to be rather than against a grid this file chose. 0.02 is the grid the
#: shipped builds run at, so the bounds these tests compare against are the ones
#: a real artifact carries.
SUBSTEP_DT_S = 0.02

#: How much room a synthetic declared envelope leaves around the body it is
#: built from, metres. Stated here rather than in `reg.enforce`: a test fixture
#: may pick its own margin, a check may not.
DECL_MARGIN_M = 0.05

#: Two configurations far enough apart that the body at one is nowhere near the
#: declared envelope built around the other. Both are folded rather than fully
#: extended, so that a declared envelope built around them with `DECL_MARGIN_M`
#: of slack still fits inside the workspace disc — the arm straight out reaches
#: 0.903 m against a 0.95 m bound, and 0.05 m of margin on *that* is a genuine
#: overclaim, which `test_envelope_overclaim_vetoes_the_declaration_itself`
#: exercises deliberately rather than by accident.
Q_HOME = (0.0, 1.8)
Q_FAR = (1.5, -1.5)

#: Inside `declared_violation`'s declared joint box, for the test that compares
#: the enforcement bound against the sampled envelope.
Q_IN_BOX = (0.0, 1.0)

#: The arm straight out along `+x`, at rest. Every test in this file that is
#: *not* about the horizon-limited bound offers its declarations against this
#: pose, and the choice is load-bearing rather than arbitrary: the arm is already
#: at full extension here, so `horizon_bound` equals `computed_bound` exactly —
#: 0.95 m — for any window whatsoever (issue #82). Those tests therefore exercise
#: the check they are named for and not the tightening, and the tightening gets
#: its own tests, which pick a folded pose on purpose.
Q_EXTENDED = (0.0, 0.0)

#: Folded hard at the elbow and at rest: the pose the tightened bound is visible
#: at. From here the elbow cannot reach 0 rad within a declaration horizon, so
#: the arm cannot straighten, and the bound is well inside the workspace disc.
Q_FOLDED = (0.0, 2.6)


def proprio(q: tuple[float, float], t: float, qd: tuple[float, float] = (0.0, 0.0)):
    return ProprioState(
        t=t,
        q=np.asarray(q, dtype=float),
        qd=np.asarray(qd, dtype=float),
        base_vel=None,
    )


def body_at(q: tuple[float, float]) -> Polygon:
    region = unary_union(list(link_polygons(np.asarray(q, dtype=float), LIMITS, ORIGIN_FRAME)))
    assert isinstance(region, Polygon)
    return region


def declared_around(q: tuple[float, float]) -> bytes:
    """A declared envelope that honestly covers the body at `q`, with margin."""
    return envelope_wkb(body_at(q).buffer(DECL_MARGIN_M))


HOME_WKB = declared_around(Q_HOME)

#: The state offered alongside every declaration in this file except where the
#: test is about the pose. See `Q_EXTENDED`: at this one the horizon-limited
#: bound and the workspace disc coincide.
AT_EXTENDED = proprio(Q_EXTENDED, 0.0)

#: A declared bound reaching far outside anything the robot can occupy: 10 m
#: square against a 0.95 m workspace disc.
HUGE_WKB = envelope_wkb(box(-5.0, -5.0, 5.0, 5.0))


def declaration(
    *,
    seq: int = 0,
    t_issued: float = 0.0,
    horizon: float = HORIZON_S,
    action_class: str = "reach",
    envelope: bytes = HOME_WKB,
    prev_hash: str = GENESIS_HASH,
    key=POLICY_KEY,
    signed: bool = True,
) -> Declaration:
    unsigned = Declaration(
        declaration_id=f"fixture-decl-{seq:05d}",
        seq=seq,
        t_issued=t_issued,
        horizon=horizon,
        action_class=action_class,
        declared_envelope=envelope,
        prev_hash=prev_hash,
        mac=UNSIGNED_MAC,
    )
    return sign_declaration(unsigned, key) if signed else unsigned


def enforcer(
    *,
    policy_key=POLICY_KEY,
    watchdog_period_s: float = WATCHDOG_S,
    t_start: float = T_START,
    substep_dt: float = SUBSTEP_DT_S,
    id_prefix: str = "fixture",
) -> Enforcer:
    return Enforcer(
        LIMITS,
        key=ENFORCEMENT_KEY,
        policy_key=policy_key,
        watchdog_period_s=watchdog_period_s,
        t_start=t_start,
        substep_dt=substep_dt,
        id_prefix=id_prefix,
    )


def verdict(**overrides: object) -> Verdict:
    base: dict[str, object] = dict(
        verdict_id="fixture-verdict-00000",
        declaration_id="fixture-decl-00000",
        seq=0,
        t=0.0,
        outcome="PERMIT",
        fault=None,
        clamped_envelope=None,
        prev_hash=GENESIS_HASH,
        mac=UNSIGNED_MAC,
    )
    base.update(overrides)
    return Verdict(**base)  # type: ignore[arg-type]


# ==========================================================================
# The record: fields, invariants, attribution.
# ==========================================================================


def test_verdict_fields_are_exactly_the_plan_phase_4_schema() -> None:
    """The record schema is a contract; a field added here changes Phase 5 too."""
    got = [f.name for f in dataclasses.fields(Verdict)]
    assert got == [
        "verdict_id",
        "declaration_id",
        "seq",
        "t",
        "outcome",
        "fault",
        "clamped_envelope",
        "prev_hash",
        "mac",
    ], (
        f"Verdict fields are {got}. Definition order is the canonical "
        "serialization order (reg/chain.py), so reordering them silently "
        "re-baselines every MAC and every chain link in the artifact."
    )


def test_the_taxonomy_is_all_nine_faults() -> None:
    assert set(FAULTS) == {
        "no_declaration",
        "stale_declaration",
        "declaration_action_mismatch",
        "envelope_overclaim",
        "out_of_vocabulary_action",
        "unattributed",
        "replay_or_reorder",
        "watchdog_expiry",
        "escalation_failure",
    }
    assert len(FAULTS) == 9
    assert set(OUTCOMES) == {"PERMIT", "CLAMP", "VETO", "SAFE_STATE"}


def test_a_verdict_is_signed_by_enforcement_and_the_policy_key_is_refused() -> None:
    """The mirror of `Declaration.SIGNING_ROLE`. Structure, not convention."""
    assert Verdict.SIGNING_ROLE == "enforcement"
    signed = sign_verdict(verdict(), ENFORCEMENT_KEY)
    assert verify_verdict(signed, ENFORCEMENT_KEY).state is MacState.VALID

    with pytest.raises(KeyRoleError, match="enforcement"):
        sign_verdict(verdict(), POLICY_KEY)


def test_verify_verdict_reports_three_states_and_never_a_bool() -> None:
    signed = sign_verdict(verdict(), ENFORCEMENT_KEY)
    assert verify_verdict(signed, None).state is MacState.COULD_NOT_EVALUATE
    assert verify_verdict(verdict(), ENFORCEMENT_KEY).state is MacState.COULD_NOT_EVALUATE
    with pytest.raises(TypeError, match="three states"):
        bool(verify_verdict(signed, ENFORCEMENT_KEY))


def test_the_mac_covers_every_field_of_the_verdict() -> None:
    """Negative: edit a signed verdict and its MAC stops matching."""
    signed = sign_verdict(verdict(t=1.0), ENFORCEMENT_KEY)
    for field, value in (
        ("t", 2.0),
        ("outcome", "VETO"),
        ("declaration_id", "fixture-decl-00001"),
        ("seq", 7),
    ):
        edited = object.__new__(Verdict)
        for f in dataclasses.fields(Verdict):
            object.__setattr__(edited, f.name, getattr(signed, f.name))
        object.__setattr__(edited, field, value)
        assert verify_verdict(edited, ENFORCEMENT_KEY).state is MacState.INVALID, (
            f"editing {field} left the MAC valid; the record would be editable "
            "after signing, which is the whole thing the chain exists to prevent."
        )


def test_resigning_a_verdict_is_refused() -> None:
    signed = sign_verdict(verdict(), ENFORCEMENT_KEY)
    with pytest.raises(EnforcementError, match="already signed"):
        sign_verdict(signed, ENFORCEMENT_KEY)


def test_permit_is_the_outcome_with_no_fault_and_the_only_one() -> None:
    """Negative, both directions: the outcome and the fault cannot vary alone."""
    with pytest.raises(EnforcementError, match="PERMIT is"):
        verdict(outcome="PERMIT", fault="no_declaration")
    with pytest.raises(EnforcementError, match="PERMIT is"):
        verdict(outcome="VETO", fault=None)
    with pytest.raises(EnforcementError, match="PERMIT is"):
        verdict(outcome="SAFE_STATE", fault=None)


def test_a_fault_outside_the_taxonomy_cannot_reach_the_record() -> None:
    with pytest.raises(EnforcementError, match="taxonomy"):
        verdict(outcome="VETO", fault="vibes")
    with pytest.raises(EnforcementError, match="not one of"):
        verdict(outcome="SHRUG", fault=None)


def test_clamped_envelope_is_present_exactly_on_a_clamp() -> None:
    """Negative, both directions. `clamped_envelope` is the bound applied."""
    ok = verdict(
        outcome="CLAMP", fault="declaration_action_mismatch", clamped_envelope=HOME_WKB
    )
    assert isinstance(ok.envelope(), Polygon)
    assert verdict().envelope() is None

    with pytest.raises(EnforcementError, match="bound actually applied"):
        verdict(outcome="CLAMP", fault="declaration_action_mismatch")
    with pytest.raises(EnforcementError, match="bound actually applied"):
        verdict(outcome="VETO", fault="no_declaration", clamped_envelope=HOME_WKB)
    with pytest.raises(EnforcementError, match="bound actually applied"):
        verdict(clamped_envelope=HOME_WKB)


def test_a_malformed_clamped_envelope_is_refused_at_construction() -> None:
    """An unreadable bound is a could-not-evaluate, never an empty region."""
    with pytest.raises(EnforcementError, match="empty"):
        verdict(outcome="CLAMP", fault="declaration_action_mismatch", clamped_envelope=b"")
    with pytest.raises(EnforcementError, match="WKB"):
        verdict(
            outcome="CLAMP",
            fault="declaration_action_mismatch",
            clamped_envelope=b"not wkb at all",
        )
    line = shapely.to_wkb(shapely.LineString([(0, 0), (1, 1)]))
    with pytest.raises(EnforcementError, match="not a Polygon"):
        verdict(outcome="CLAMP", fault="declaration_action_mismatch", clamped_envelope=line)


def test_verdict_and_acknowledgment_are_frozen() -> None:
    v = verdict()
    with pytest.raises(dataclasses.FrozenInstanceError):
        v.outcome = "VETO"  # type: ignore[misc]


def test_an_acknowledgment_is_signed_by_enforcement_not_the_policy() -> None:
    """The gate would be decorative if the policy could clear its own fault."""
    ack = Acknowledgment(
        ack_id="fixture-ack-00000",
        t=1.0,
        fault="stale_declaration",
        verdict_id="fixture-verdict-00003",
        reason="operator confirmed the cell is clear",
        prev_hash=GENESIS_HASH,
        mac=UNSIGNED_MAC,
    )
    assert Acknowledgment.SIGNING_ROLE == "enforcement"
    signed = sign_acknowledgment(ack, ENFORCEMENT_KEY)
    assert verify_acknowledgment(signed, ENFORCEMENT_KEY).state is MacState.VALID
    with pytest.raises(KeyRoleError, match="enforcement"):
        sign_acknowledgment(ack, POLICY_KEY)


def test_an_acknowledgment_with_no_stated_reason_is_refused() -> None:
    with pytest.raises(EnforcementError, match="reason"):
        Acknowledgment(
            ack_id="a",
            t=0.0,
            fault="stale_declaration",
            verdict_id="v",
            reason="   ",
            prev_hash=GENESIS_HASH,
            mac=UNSIGNED_MAC,
        )


# ==========================================================================
# Independence: enforcement must not be able to inherit the policy's failures.
# ==========================================================================


def _enforce_imports() -> tuple[dict[str, set[str]], set[str]]:
    """`{module: names}` for `from x import y`, and the set of plain `import x`."""
    source = pathlib.Path(reg.enforce.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    from_imports: dict[str, set[str]] = {}
    plain: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            from_imports.setdefault(node.module, set()).update(a.name for a in node.names)
        elif isinstance(node, ast.Import):
            plain.update(a.name for a in node.names)
    return from_imports, plain


def test_enforce_imports_from_declare_no_further_than_the_dataclass() -> None:
    """The independence rule, asserted against the source rather than reviewed.

    A constraint layer supplied by the same party as the policy has common-cause
    failure with it. `ACTION_CLASSES` is allowed *because* sharing it is the
    safer direction: two copies of a vocabulary is how an out-of-vocabulary
    action becomes a fault on one side and invisible on the other.
    """
    from_imports, plain = _enforce_imports()
    names = from_imports.get("reg.declare", set())
    assert names, "reg.enforce must import the Declaration dataclass to read one"
    assert names <= {"Declaration", "ACTION_CLASSES"}, (
        f"reg.enforce imports {sorted(names)} from reg.declare. Widening this is "
        "not a refactor: enforcement that reuses the policy's helpers fails the "
        "same way the policy does, and the independence argument in "
        "docs/plan.md Phase 4 is the mechanism, not a style preference."
    )
    assert not any(m.startswith("reg.declare") for m in plain)


def test_enforce_cannot_see_layer_b() -> None:
    """No world, no scenario, no persisted artifact. Layer A decides for itself."""
    from_imports, plain = _enforce_imports()
    forbidden = {
        "reg.world",
        "reg.scenarios",
        "reg.sim",
        "reg.graph",
        "reg.query",
        "reg.store",
        "reg.viz",
        "reg.bench",
    }
    assert not (set(from_imports) & forbidden)
    assert not (plain & forbidden)
    for name in ("World", "Obstacle", "StateFrame", "Room", "Scenario"):
        assert not hasattr(reg.enforce, name), (
            f"reg.enforce exposes {name}; the enforcement layer decides what the "
            "robot may do from what the robot knows about itself."
        )


def test_adjudicate_refuses_a_stateframe() -> None:
    """The narrowing belongs at the call site, where it is visible."""
    frame = StateFrame(
        t=0.0,
        q=np.array([0.0, 0.0]),
        qd=np.array([0.0, 0.0]),
        human_pos=np.array([1.0, 0.0]),
        human_vel=np.array([0.0, 0.0]),
        base_vel=None,
        base_pose=None,
        objects=(Obstacle("obs_0", "box", 1.0, 1.0, 0.2),),
    )
    e = enforcer()
    with pytest.raises(EnforcementError, match="ProprioState"):
        e.adjudicate(frame)  # type: ignore[arg-type]
    with pytest.raises(EnforcementError, match="ProprioState"):
        body_polygon(frame, LIMITS)  # type: ignore[arg-type]


def test_offer_refuses_anything_that_is_not_a_declaration() -> None:
    """Duck typing is how a record 'arrives' with fields nobody validated."""

    class LooksLikeOne:
        declaration_id = "x"
        seq = 0
        t_issued = 0.0
        horizon = 1.0
        action_class = "reach"
        declared_envelope = HOME_WKB
        prev_hash = GENESIS_HASH
        mac = UNSIGNED_MAC

    with pytest.raises(EnforcementError, match="Declaration"):
        enforcer().offer(LooksLikeOne(), AT_EXTENDED)  # type: ignore[arg-type]


# ==========================================================================
# The independently computed bound.
# ==========================================================================


def test_the_demo_worlds_bound_is_the_workspace_disc_it_has_always_been() -> None:
    """`computed_bound` is unchanged by the base bounds on `Limits` (issue #151).

    The base's actuation bounds joined `Limits` so that Tier 3 has something to
    bound a base *with*. Tier 3 is where the bound itself changes, and it does
    not change quietly: `computed_bound` refusing an unbounded workspace
    (docs/mobile-base.md §1) re-labels what a VETO means, so it carries its own
    reasoning and its own issue.

    Until then this is the pin. The bound for the demo world is
    `sum(link_lengths) + link_radius` and nothing else, stated as the arithmetic
    rather than as a number, so it fails if either the fields it reads or the
    formula moves.
    """
    assert computed_bound(LIMITS) == pytest.approx(
        float(np.sum(LIMITS.link_lengths) + LIMITS.link_radius), abs=1e-12
    )


def test_the_computed_bound_does_not_read_the_base_bounds() -> None:
    """The negative half: a base that can drive does not widen the arm's disc.

    A `computed_bound` that silently grew with `base_v_max` would be a bound
    over a workspace that is unbounded given enough time — the failure
    docs/mobile-base.md §1 calls the worst available here, because it VETOes and
    looks principled while doing it. Today the disc is arm-only and this asserts
    it, so the Tier 3 change cannot arrive as a side effect of somebody stating
    a mobile base's datasheet.
    """
    mobile = dataclasses.replace(
        LIMITS,
        base_v_max=1.5,
        base_a_max=2.0,
        base_omega_max=3.0,
        base_alpha_max=4.0,
    )
    assert computed_bound(mobile) == computed_bound(LIMITS)


def test_the_computed_bound_contains_every_body_of_every_fixture() -> None:
    """Soundness, in the conservative direction, on real runs across seeds."""
    bound = computed_bound(LIMITS)
    for scenario in SCENARIOS.values():
        for seed in (0, 1):
            for frame in scenario.states(seed):
                coords = shapely.get_coordinates(body_at(tuple(frame.q)))
                furthest = float(np.hypot(coords[:, 0], coords[:, 1]).max())
                assert furthest <= bound, (
                    f"{scenario.name} seed {seed} t={frame.t}: the body reaches "
                    f"{furthest} m, outside the bound of {bound} m. A bound that "
                    "does not contain the robot would clear things wrongly."
                )


def test_envelope_excess_is_negative_inside_and_positive_outside() -> None:
    bound = computed_bound(LIMITS)
    assert envelope_excess(body_at(Q_HOME), LIMITS) < 0.0
    assert envelope_excess(shapely.from_wkb(HUGE_WKB), LIMITS) > 0.0
    # Exact, not approximate: the disc is convex, so the check is a comparison
    # against the furthest vertex and nothing renders the circle as a polygon.
    # The furthest vertex here is at (bound + 0.25, 0), so the answer is 0.25 to
    # the last bit rather than to a tolerance.
    spike = Polygon([(0.0, 0.0), (bound + 0.25, 0.0), (0.0, 0.001)])
    assert envelope_excess(spike, LIMITS) == pytest.approx(0.25, abs=1e-12)


def test_envelope_excess_refuses_a_geometry_it_cannot_evaluate() -> None:
    """Negative: empty and invalid are could-not-evaluate, never 'it fits'."""
    with pytest.raises(EnforcementError, match="empty"):
        envelope_excess(Polygon(), LIMITS)
    bowtie = Polygon([(0, 0), (1, 1), (1, 0), (0, 1)])
    assert not bowtie.is_valid
    with pytest.raises(EnforcementError, match="invalid"):
        envelope_excess(bowtie, LIMITS)
    with pytest.raises(EnforcementError, match="shapely geometry"):
        envelope_excess("a polygon, honest", LIMITS)  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# The base frame the excess is measured from (issue #162)
# --------------------------------------------------------------------------


def test_the_excess_is_measured_from_the_base_it_is_given() -> None:
    """`_furthest_vertex` took its centre from an implicit origin; now it is told.

    Both bounds in this module are discs **about the base joint**, so the
    distance the declared region is compared against has to be measured from the
    same point the bound is. This is the negative for the argument being
    accepted and ignored: a base a millimetre out along the spike's own axis has
    to move the excess by exactly a millimetre — 1 mm being small enough that a
    tolerance-based check would wave it through, and exactly the size of drift
    "make this a parameter" produces when the parameter is never read.
    """
    bound = computed_bound(LIMITS)
    spike = Polygon([(0.0, 0.0), (bound + 0.25, 0.0), (0.0, 0.001)])
    at_origin = reg.enforce._furthest_vertex(spike, ORIGIN_FRAME, "test")

    assert at_origin == pytest.approx(bound + 0.25, abs=1e-12)
    assert reg.enforce._furthest_vertex(
        spike, BaseFrame(x=-0.001, y=0.0, theta=0.0), "test"
    ) == pytest.approx(at_origin + 0.001, abs=1e-12)
    assert reg.enforce._furthest_vertex(
        spike, BaseFrame(x=0.001, y=0.0, theta=0.0), "test"
    ) == pytest.approx(at_origin - 0.001, abs=1e-12)


def test_the_excess_refuses_a_base_that_is_not_a_frame() -> None:
    """Negative: no default, no duck-type, and it reports in this module's currency.

    A three-tuple carries no type and `None` reads as 'unspecified'. The refusal
    arrives as an `EnforcementError` because that is what "the check could not be
    performed as specified" is called here — a could-not-evaluate about the
    caller, never a verdict. `reg.types.BasePose` is refused by the same check;
    the layer argument for refusing it lives in `tests/test_layer_boundary.py`.
    """
    square = Polygon([(0, 0), (1, 0), (1, 1)])
    for bad in ((0.0, 0.0, 0.0), [0.0, 0.0, 0.0], None, 0.0):
        with pytest.raises(EnforcementError, match="BaseFrame"):
            reg.enforce._furthest_vertex(square, bad, "test")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        reg.enforce._furthest_vertex(square, "test")  # type: ignore[call-arg]


def test_the_mismatch_resolution_is_the_artifacts_own_and_is_not_a_tolerance() -> None:
    """The comparison happens at the resolution the artifact commits geometry to.

    Two halves, and the second is the one that matters. A declared bound that
    *is* the commanded body must produce no escape — `Polygon.covers` fails that
    on most frames of every compliant fixture, which is why it is not the
    predicate. And an escape of one micron, a thousand times the resolution,
    must still be caught: the dilation is a floating-point noise floor, not a
    tolerance the fault can hide under.
    """
    assert MISMATCH_RESOLUTION_M == 10.0**-HASH_COORD_PRECISION
    body = body_at(Q_HOME)

    exact = declaration(envelope=envelope_wkb(body))
    assert escape_region(body, declared_bound(exact)).is_empty

    eroded = body.buffer(-1e-6)
    assert eroded.is_valid and not eroded.is_empty
    tight = declaration(envelope=envelope_wkb(eroded))
    assert not escape_region(body, declared_bound(tight)).is_empty

    e = enforcer()
    assert e.offer(tight, AT_EXTENDED) is None
    v = e.adjudicate(proprio(Q_HOME, 0.1))
    assert (v.outcome, v.fault) == ("CLAMP", "declaration_action_mismatch")


def test_escape_region_refuses_what_it_cannot_evaluate() -> None:
    """Negative: an empty operand is a could-not-evaluate, never 'no escape'."""
    body = body_at(Q_HOME)
    with pytest.raises(EnforcementError, match="empty body"):
        escape_region(Polygon(), body)
    with pytest.raises(EnforcementError, match="empty bound"):
        escape_region(body, Polygon())
    with pytest.raises(EnforcementError, match="shapely geometry"):
        escape_region(body, HOME_WKB)  # type: ignore[arg-type]


def test_computed_bound_refuses_a_malformed_robot() -> None:
    broken = Limits(
        q_min=np.array([-3.0]),
        q_max=np.array([3.0]),
        qd_max=np.array([1.0]),
        qdd_max=np.array([1.0]),
        link_lengths=np.array([0.0]),
        source=LimitSource.PROPRIOCEPTIVE,
        link_radius=0.05,
        base_v_max=0.0,
        base_a_max=0.0,
        base_omega_max=0.0,
        base_alpha_max=0.0,
    )
    with pytest.raises(EnforcementError, match="strictly positive"):
        computed_bound(broken)


def test_the_bound_is_not_the_sampled_envelope_so_honest_declarations_survive() -> None:
    """The direction that matters: `compute_envelope` **under**-covers.

    A declared region larger than the sampled forward envelope is the normal
    case for an honest declaration, not evidence of an overclaim. Comparing
    against the sampled envelope would VETO `declared_violation`'s own bound —
    the check that cries wolf. This asserts the declared region is genuinely
    larger than the sampled envelope *and* is still accepted.
    """
    scenario = SCENARIOS["declared_violation"]
    assert scenario.declared_q_bounds is not None
    region = declared_region(box_grid(scenario.declared_q_bounds, LIMITS), LIMITS)

    first = next(iter(scenario.states(0))).proprio()
    sampled = compute_envelope(first, LIMITS, horizon=0.2, n_samples=64, seed=0)
    assert envelope_area(region) > envelope_area(sampled), (
        "the fixture no longer exercises the direction this test is about"
    )

    e = enforcer()
    assert e.offer(declaration(envelope=envelope_wkb(region)), AT_EXTENDED) is None
    assert not e.is_passivated
    assert e.adjudicate(proprio(Q_IN_BOX, 0.0)).outcome == "PERMIT"


# ==========================================================================
# One negative per fault, each with the positive control beside it.
# ==========================================================================


def test_no_declaration_is_a_veto() -> None:
    e = enforcer()
    v = e.adjudicate(proprio(Q_HOME, 0.1))
    assert (v.outcome, v.fault) == ("VETO", "no_declaration")
    assert v.declaration_id is None
    assert e.is_passivated


def test_an_action_before_its_declaration_was_issued_is_no_declaration() -> None:
    """The open declaration does not cover this instant, and is not yet stale."""
    e = enforcer()
    assert e.offer(declaration(t_issued=0.5), AT_EXTENDED) is None
    v = e.adjudicate(proprio(Q_HOME, 0.25))
    assert (v.outcome, v.fault) == ("VETO", "no_declaration")


def test_a_declaration_permits_the_action_it_covers() -> None:
    """The positive control for `no_declaration`."""
    e = enforcer()
    assert e.offer(declaration(), AT_EXTENDED) is None
    v = e.adjudicate(proprio(Q_HOME, 0.1))
    assert (v.outcome, v.fault, v.clamped_envelope) == ("PERMIT", None, None)
    assert v.declaration_id == "fixture-decl-00000"
    assert not e.is_passivated


def test_stale_declaration_is_a_veto() -> None:
    e = enforcer()
    e.offer(declaration(t_issued=0.0, horizon=0.5), AT_EXTENDED)
    assert e.adjudicate(proprio(Q_HOME, 0.5)).outcome == "PERMIT"  # boundary is covered
    v = e.adjudicate(proprio(Q_HOME, 0.51))
    assert (v.outcome, v.fault) == ("VETO", "stale_declaration")
    assert v.declaration_id == "fixture-decl-00000"
    assert e.is_passivated


def test_declaration_action_mismatch_clamps_to_the_declared_bound() -> None:
    e = enforcer()
    d = declaration()
    e.offer(d, AT_EXTENDED)
    v = e.adjudicate(proprio(Q_FAR, 0.1))
    assert (v.outcome, v.fault) == ("CLAMP", "declaration_action_mismatch")
    assert v.clamped_envelope == d.declared_envelope, (
        "the bound actually applied is the declared bound, verbatim from the "
        "record — the overclaim check has already established it lies inside "
        "the independently computed bound."
    )
    # The only fault in the taxonomy that does not passivate: it is a graceful
    # degradation, and the run continues.
    assert not e.is_passivated
    assert e.adjudicate(proprio(Q_HOME, 0.2)).outcome == "PERMIT"


def test_envelope_overclaim_vetoes_the_declaration_itself() -> None:
    """The negative the whole 'never trust the declaration' rule is about."""
    e = enforcer()
    v = e.offer(declaration(envelope=HUGE_WKB), AT_EXTENDED)
    assert v is not None
    assert (v.outcome, v.fault) == ("VETO", "envelope_overclaim")
    assert v.declaration_id == "fixture-decl-00000"
    assert e.open_declaration is None
    assert e.is_passivated
    assert f"{computed_bound(LIMITS):.4f}" in (e.reason(v.verdict_id) or "")


# --------------------------------------------------------------------------
# The horizon-limited half of the overclaim check (issue #82).
#
# Before it, `computed_bound` was the same scalar at every frame of every run —
# no `q`, no `qd`, no horizon — so `envelope_overclaim` could only fire on a
# declaration exceeding the *entire workspace*, and the fault a Simplex / ASTM
# F3269 monitor exists to catch was undetectable. These tests are about the case
# that was undetectable, and the first one is the fixture the issue asks for: a
# declared region that fits comfortably inside the workspace disc and still
# claims more than the robot can occupy in the window it declared.
# --------------------------------------------------------------------------


def reachable_looking_declaration() -> bytes:
    """A declared region entirely inside the workspace disc, and a lie anyway.

    The policy claims it will sweep its elbow from 0.5 rad out to 2.6 rad. Every
    configuration in that claim is one the arm can hold, and the union of their
    bodies reaches 0.887 m against a 0.95 m workspace disc — so the static check
    passes it, correctly, because nothing about it exceeds the workspace. What
    it *cannot* do is get the elbow anywhere near 0.5 rad within half a second
    from a standing fold, which is the claim `horizon_bound` is against.
    """
    box = ((-0.2, 0.2), (0.5, 2.6))
    return envelope_wkb(declared_region(box_grid(box, LIMITS), LIMITS))


def test_envelope_overclaim_fires_on_a_region_inside_the_workspace_disc() -> None:
    """**The fault that was undetectable.** Issue #82's acceptance criterion.

    Both halves are asserted, because either alone would be misleading: the
    static bound accepts this declaration (so the region genuinely is inside the
    workspace), and the horizon-limited one refuses it (so the tightening is
    what caught it, not a bound that got looser somewhere else).
    """
    region = shapely.from_wkb(reachable_looking_declaration())
    assert envelope_excess(region, LIMITS) < 0.0, (
        "the fixture is supposed to fit inside the workspace disc; if it does "
        "not, the old check catches it and this test proves nothing new."
    )

    folded = proprio(Q_FOLDED, 0.0)
    e = enforcer()
    v = e.offer(declaration(envelope=reachable_looking_declaration()), folded)
    assert v is not None
    assert (v.outcome, v.fault) == ("VETO", "envelope_overclaim")
    assert e.is_passivated
    reason = e.reason(v.verdict_id) or ""
    assert f"{HORIZON_S:.4f} s window" in reason, reason
    assert f"{computed_bound(LIMITS):.4f}" in reason, (
        "the reason has to name both bounds; an operator reading a VETO has to "
        f"be able to see which one refused it. Got: {reason}"
    )


def test_the_same_declaration_is_accepted_from_a_pose_that_can_honour_it() -> None:
    """POSITIVE CONTROL. The check must not be refusing the *region*.

    Same declaration, same bound, an arm already extended — from which the
    claimed region is reachable within the window. A check that refused this too
    would be the workspace disc with extra steps, refusing on geometry rather
    than on what the robot can do with it.
    """
    e = enforcer()
    assert e.offer(declaration(envelope=reachable_looking_declaration()), AT_EXTENDED) is None
    assert e.open_declaration is not None
    assert not e.is_passivated


def test_the_horizon_bound_is_never_worse_than_the_workspace_disc() -> None:
    """The floor. Tightening a bound must not be able to loosen it anywhere."""
    disc = computed_bound(LIMITS)
    for q in (Q_EXTENDED, Q_FOLDED, Q_HOME, Q_FAR, Q_IN_BOX):
        for qd in ((0.0, 0.0), (2.0, 2.5), (-2.0, -2.5)):
            for window in (0.05, 0.5, 5.0):
                state = proprio(q, 0.0, qd)
                assert (
                    horizon_bound(state, LIMITS, window, SUBSTEP_DT_S) <= disc + 1e-12
                )


#: The demo arm on a base that can drive. Not a fixture anything runs on —
#: `reg.world.LIMITS` states four zeros and Tier 4 of docs/mobile-base.md §7 is
#: where mobile scenarios arrive. It exists so the two tests below can ask what
#: the *bound* does for a robot that moves, which is a question the fixtures
#: cannot ask.
MOBILE_LIMITS = dataclasses.replace(
    LIMITS,
    base_v_max=0.8,
    base_a_max=1.5,
    base_omega_max=1.2,
    base_alpha_max=2.5,
)


def test_a_mobile_robot_with_no_recorded_base_velocity_aborts_rather_than_binds() -> None:
    """A could-not-evaluate reaching the VETO path as a could-not-evaluate.

    `ProprioState.base_vel is None` means *this state records no base velocity*,
    and every state in this repository is one: `reg.graph` reconstructs frames
    from `robot_config`, which has no columns for it. For a bolted-down base
    that is fine — the vehicle cannot move, so there is nothing to record. For a
    robot that can drive it is a hole, and since issue #163 the outer set says
    so instead of computing a standing-still bound.

    It arrives here as an `EnforcementError` rather than as a wider bound, which
    is the rule issue #106 settled for this path: falling back to the workspace
    disc would report a check that ran when it did not.
    """
    state = proprio(Q_EXTENDED, 0.0)
    assert state.base_vel is None
    with pytest.raises(EnforcementError) as excinfo:
        horizon_bound(state, MOBILE_LIMITS, HORIZON_S, SUBSTEP_DT_S)
    assert "base_vel" in str(excinfo.value), str(excinfo.value)

    # The same state against the fixed-base limits is a bound like any other, so
    # the refusal above is about the robot and not about the state.
    assert horizon_bound(state, LIMITS, HORIZON_S, SUBSTEP_DT_S) > 0.0


def test_the_horizon_bound_is_still_floored_by_a_fixed_base_disc() -> None:
    """**A gap recorded, not a property asserted.** Issue #164 is what closes it.

    Issue #163 put the vehicle's motion into `reg.envelope.outer_envelope`, and
    that makes the outer term of `horizon_bound` grow with the base's bounds
    while `computed_bound` — correctly — does not
    (`test_the_computed_bound_does_not_read_the_base_bounds`). So for a robot
    that drives, `min(computed_bound, outer_radius)` is pinned at the workspace
    disc, and the workspace disc is finite **only because the base is bolted
    down** (docs/mobile-base.md §1, docs/limitations.md §9). The minimum of a
    sound bound and an unsound one is not a sound bound.

    Nothing in this repository is affected: `reg.world.LIMITS` states four zeros
    and the fixtures are fixed-base runs, so the floor is the floor it always
    was. This asserts the shape of the gap — the outer term does exceed the disc
    for a driven base, and the disc does win — so that #164's change to
    `computed_bound` cannot land without a test in front of it going red and
    saying which sentence stopped being true.
    """
    state = dataclasses.replace(
        proprio(Q_EXTENDED, 0.0), base_vel=BaseVelocity(vx=0.8, vy=0.0, omega=0.0)
    )
    region = outer_envelope(state, MOBILE_LIMITS, HORIZON_S, ORIGIN_FRAME)
    disc = computed_bound(MOBILE_LIMITS)

    assert outer_radius(region, ORIGIN_FRAME) > disc, (
        "the outer set of a driven base does not exceed the arm's workspace "
        "disc, so either the base bounds are not being read or this fixture is "
        "too slow to distinguish them."
    )
    assert horizon_bound(state, MOBILE_LIMITS, HORIZON_S, SUBSTEP_DT_S) == disc, (
        "the floor is no longer the binding term for a driven base. If issue "
        "#164 has landed, `computed_bound` should be refusing an unbounded "
        "workspace and this test is what has to be rewritten, not the bound."
    )


def test_horizon_excess_is_never_less_than_envelope_excess() -> None:
    """So the fault only ever gains cases; nothing the static check caught is lost."""
    region = shapely.from_wkb(reachable_looking_declaration())
    for q in (Q_EXTENDED, Q_FOLDED, Q_HOME):
        state = proprio(q, 0.0)
        assert horizon_excess(
            region, state, LIMITS, HORIZON_S, SUBSTEP_DT_S
        ) >= envelope_excess(region, LIMITS) - 1e-12


def test_an_extended_arm_leaves_the_static_bound_exactly_where_it_was() -> None:
    """The tightening is additive: at full extension the two bounds coincide.

    Load-bearing for every other test in this file — they all offer against
    `AT_EXTENDED` precisely so that the tightening cannot silently change what
    they are measuring.
    """
    for window in (0.02, 0.5, 5.0):
        assert horizon_bound(
            AT_EXTENDED, LIMITS, window, SUBSTEP_DT_S
        ) == pytest.approx(computed_bound(LIMITS), abs=1e-9)


def test_offer_refuses_a_state_that_is_not_proprioception() -> None:
    """The Layer A boundary, on the argument the bound is computed from."""
    frame = StateFrame(
        t=0.0,
        q=np.asarray(Q_EXTENDED, dtype=float),
        qd=np.zeros(2),
        human_pos=np.array([1.0, 1.0]),
        human_vel=np.zeros(2),
        base_vel=None,
        base_pose=None,
        objects=(),
    )
    with pytest.raises(EnforcementError, match="ProprioState"):
        enforcer().offer(declaration(), frame)  # type: ignore[arg-type]
    with pytest.raises(EnforcementError, match="ProprioState"):
        enforcer().offer(declaration(), None)  # type: ignore[arg-type]


def test_offer_refuses_a_state_from_after_the_declaration_was_issued() -> None:
    """NEGATIVE. A bound integrated from a pose the claimed window has left.

    It would not cover the start of the interval being claimed, so it would be
    an unsound bound with a sound one's shape — the one failure mode this whole
    construction exists to avoid. A state from *before* `t_issued` is fine and
    the window stretches to cover the gap, which the next test asserts.
    """
    with pytest.raises(EnforcementError, match="after the declaration"):
        enforcer().offer(declaration(t_issued=0.0), proprio(Q_EXTENDED, 0.1))


def test_an_older_state_widens_the_window_rather_than_narrowing_it() -> None:
    """A bound reaching further back covers more, so it can only accept more."""
    folded_now = proprio(Q_FOLDED, 0.5)
    folded_earlier = proprio(Q_FOLDED, 0.0)
    d = declaration(t_issued=0.5, envelope=reachable_looking_declaration())

    assert enforcer().offer(d, folded_now) is not None, (
        "from the pose at t_issued this declaration overclaims; if it does not, "
        "the comparison below is between two accepting bounds and says nothing."
    )
    # Same claim, judged from a pose half a second older: the window the bound
    # covers is 1.0 s rather than 0.5 s, which is enough for the arm to unfold.
    assert enforcer().offer(d, folded_earlier) is None


def test_a_declaration_the_arm_can_reach_by_moving_is_accepted() -> None:
    """POSITIVE CONTROL for the velocity term: the bound is not just about pose.

    The same folded arm, but already turning at its velocity bound. It sweeps a
    region a standing fold cannot, and a declaration covering the sweep it is
    actually making has to be accepted — a bound that ignored `qd` would refuse
    it and cry wolf on an honest policy.
    """
    turning = proprio(Q_FOLDED, 0.0, qd=(2.0, 0.0))
    swept = declared_region(
        box_grid(((-0.2, 1.0), (2.2, 2.6)), LIMITS), LIMITS
    )
    assert enforcer().offer(declaration(envelope=envelope_wkb(swept)), turning) is None


def test_an_enormous_declaration_does_not_widen_what_is_permitted() -> None:
    """NEGATIVE — the *computed* bound constrains the verdict, not the declared one.

    The action below sits comfortably inside the enormous declared envelope. If
    enforcement believed the declaration it would PERMIT; it computes its own
    bound instead, so nothing here is ever permitted.
    """
    huge = shapely.from_wkb(HUGE_WKB)
    assert huge.covers(body_at(Q_HOME)), "the action is inside the declared claim"

    e = enforcer()
    e.offer(declaration(envelope=HUGE_WKB), AT_EXTENDED)
    outcomes = {e.adjudicate(proprio(Q_HOME, t)).outcome for t in (0.1, 0.2, 0.3)}
    assert outcomes == {"SAFE_STATE"}
    assert "PERMIT" not in {v.outcome for v in e.verdicts}


def test_out_of_vocabulary_action_is_a_veto() -> None:
    """A record built elsewhere: signed, well-formed, and not in the vocabulary.

    `Declaration.__post_init__` refuses to *construct* one, so the only way this
    arrives is from another producer — which is exactly the case enforcement
    exists for. The fixture edits the frozen record and re-signs it, so the MAC
    is valid and this fault, not `unattributed`, is what is being tested.
    """
    d = declaration()
    object.__setattr__(d, "action_class", "levitate")
    object.__setattr__(d, "mac", sign(d, POLICY_KEY))
    assert "levitate" not in ACTION_CLASSES

    e = enforcer()
    v = e.offer(d, AT_EXTENDED)
    assert v is not None
    assert (v.outcome, v.fault) == ("VETO", "out_of_vocabulary_action")
    assert e.is_passivated


def test_every_action_class_in_the_vocabulary_is_accepted() -> None:
    """The positive control for `out_of_vocabulary_action`."""
    for i, action_class in enumerate(ACTION_CLASSES):
        e = enforcer()
        assert e.offer(declaration(seq=i, action_class=action_class), AT_EXTENDED) is None
        assert e.open_declaration is not None


def test_unattributed_when_the_mac_does_not_match() -> None:
    e = enforcer()
    v = e.offer(declaration(key=OTHER_KEYRING.key("policy")), AT_EXTENDED)
    assert v is not None
    assert (v.outcome, v.fault) == ("VETO", "unattributed")
    assert e.is_passivated


def test_unattributed_when_the_declaration_is_not_signed_at_all() -> None:
    e = enforcer()
    v = e.offer(declaration(signed=False), AT_EXTENDED)
    assert v is not None
    assert (v.outcome, v.fault) == ("VETO", "unattributed")


def test_could_not_evaluate_is_not_permit() -> None:
    """NEGATIVE — the consumer side of `MacCheck` refusing to be a bool.

    A verifier holding no key has learned nothing about the record. That is
    neither valid nor invalid, and the one outcome it must never become is
    PERMIT — so the assertion is over the whole verdict stream, not over one
    branch being handled.
    """
    e = enforcer(policy_key=None)
    v = e.offer(declaration(), AT_EXTENDED)
    assert v is not None
    assert (v.outcome, v.fault) == ("VETO", "unattributed")
    assert "no key" in (e.reason(v.verdict_id) or "")

    for t in (0.1, 0.2, 0.3):
        e.adjudicate(proprio(Q_HOME, t))
    assert "PERMIT" not in {rec.outcome for rec in e.verdicts}


def test_replay_and_reorder_are_vetoed() -> None:
    for bad_seq in (3, 2):  # reuse, then regression
        e = enforcer()
        assert e.offer(declaration(seq=3, t_issued=0.0), AT_EXTENDED) is None
        v = e.offer(declaration(seq=bad_seq, t_issued=0.1), AT_EXTENDED)
        assert v is not None, f"seq={bad_seq} was accepted after seq=3"
        assert (v.outcome, v.fault) == ("VETO", "replay_or_reorder")
        assert e.is_passivated


def test_an_advancing_seq_is_accepted() -> None:
    """The positive control for `replay_or_reorder`. Gaps are not reordering."""
    e = enforcer()
    assert e.offer(declaration(seq=0, t_issued=0.0), AT_EXTENDED) is None
    assert e.offer(declaration(seq=4, t_issued=0.1), AT_EXTENDED) is None
    assert e.open_declaration is not None
    assert e.open_declaration.seq == 4


def test_watchdog_expiry_drives_to_a_safe_state() -> None:
    """The liveness check: the declaration channel has gone quiet."""
    e = enforcer(watchdog_period_s=0.25)
    e.offer(declaration(t_issued=0.0, horizon=10.0), AT_EXTENDED)
    assert e.adjudicate(proprio(Q_HOME, 0.25)).outcome == "PERMIT"
    v = e.adjudicate(proprio(Q_HOME, 0.26))
    assert (v.outcome, v.fault) == ("SAFE_STATE", "watchdog_expiry")
    assert v.declaration_id is None
    assert e.is_passivated


def test_the_watchdog_fires_before_any_declaration_arrives() -> None:
    """Measured from `t_start`, which is why `t_start` has no default."""
    e = enforcer(watchdog_period_s=0.25, t_start=0.0)
    v = e.adjudicate(proprio(Q_HOME, 1.0))
    assert (v.outcome, v.fault) == ("SAFE_STATE", "watchdog_expiry")


def test_the_watchdog_is_liveness_not_validity() -> None:
    """A refused declaration still proves the channel is alive.

    Conflating the two would report a silent policy and a faulty one as the same
    fault. The refusal below has its own verdict; what it must not also do is
    leave the watchdog ticking from before it arrived.
    """
    e = enforcer(watchdog_period_s=0.25)
    e.offer(declaration(seq=0, t_issued=0.0, envelope=HUGE_WKB), AT_EXTENDED)  # refused, but heard
    e.acknowledge(t=0.05, reason="operator cleared the overclaim")
    assert e.offer(declaration(seq=1, t_issued=0.1), AT_EXTENDED) is None
    v = e.adjudicate(proprio(Q_HOME, 0.3))
    assert v.outcome == "PERMIT", "the channel was heard from at t=0.1"


def test_escalation_failure_when_the_policy_replans_instead_of_escalating() -> None:
    """The condition `reg.enforce` defines: passivated, unacknowledged, no escalate."""
    e = enforcer()
    e.adjudicate(proprio(Q_HOME, 0.1))  # VETO no_declaration -> passivated
    assert e.is_passivated

    v = e.offer(declaration(seq=1, t_issued=0.2, action_class="reach"), AT_EXTENDED)
    assert v is not None
    assert (v.outcome, v.fault) == ("SAFE_STATE", "escalation_failure")
    assert e.is_passivated
    assert e.open_declaration is None


def test_an_escalate_declaration_is_not_an_escalation_failure() -> None:
    """The positive control — and it still does not resume anything."""
    e = enforcer()
    e.adjudicate(proprio(Q_HOME, 0.1))
    assert e.offer(declaration(seq=1, t_issued=0.2, action_class="escalate"), AT_EXTENDED) is None
    assert e.escalated
    assert e.is_passivated
    assert "escalation_failure" not in {v.fault for v in e.verdicts}
    assert e.adjudicate(proprio(Q_HOME, 0.3)).outcome == "SAFE_STATE"


# ==========================================================================
# Passivation and reintegration.
# ==========================================================================


def test_after_a_veto_every_action_is_a_safe_state_carrying_the_fault() -> None:
    e = enforcer()
    e.offer(declaration(t_issued=0.0, horizon=0.5), AT_EXTENDED)
    assert e.adjudicate(proprio(Q_HOME, 0.51)).fault == "stale_declaration"
    for t in (0.6, 0.7, 0.8):
        v = e.adjudicate(proprio(Q_HOME, t))
        assert (v.outcome, v.fault) == ("SAFE_STATE", "stale_declaration")
    assert e.passivation_fault == "stale_declaration"


def test_a_fresh_declaration_alone_does_not_resume() -> None:
    """NEGATIVE — reintegration is gated. This is the half people omit."""
    e = enforcer()
    e.offer(declaration(seq=0, t_issued=0.0, horizon=0.5), AT_EXTENDED)
    e.adjudicate(proprio(Q_HOME, 0.51))  # VETO stale -> passivated

    refusal = e.offer(declaration(seq=1, t_issued=0.6), AT_EXTENDED)
    assert refusal is not None, "a fresh declaration alone resumed the run"
    assert e.is_passivated
    assert e.open_declaration is None
    assert e.adjudicate(proprio(Q_HOME, 0.7)).outcome == "SAFE_STATE"


def test_an_acknowledgment_alone_does_not_resume() -> None:
    """The other half: the acknowledgment needs a fresh declaration behind it."""
    e = enforcer()
    e.offer(declaration(seq=0, t_issued=0.0, horizon=0.5), AT_EXTENDED)
    e.adjudicate(proprio(Q_HOME, 0.51))

    ack = e.acknowledge(t=0.6, reason="operator inspected the cell")
    assert ack.fault == "stale_declaration"
    assert e.is_passivated
    v = e.adjudicate(proprio(Q_HOME, 0.7))
    assert (v.outcome, v.fault) == ("SAFE_STATE", "stale_declaration")


def test_acknowledgment_then_a_fresh_declaration_resumes() -> None:
    e = enforcer()
    e.offer(declaration(seq=0, t_issued=0.0, horizon=0.5), AT_EXTENDED)
    passivating = e.adjudicate(proprio(Q_HOME, 0.51))

    ack = e.acknowledge(t=0.6, reason="operator inspected the cell")
    assert ack.verdict_id == passivating.verdict_id, (
        "the acknowledgment names the verdict it clears, so acknowledging one "
        "fault cannot clear a different one later"
    )
    assert e.offer(declaration(seq=1, t_issued=0.7), AT_EXTENDED) is None
    assert not e.is_passivated
    assert e.adjudicate(proprio(Q_HOME, 0.8)).outcome == "PERMIT"


def test_a_new_passivation_invalidates_an_earlier_acknowledgment() -> None:
    """Acknowledging a stale declaration did not clear a forged one."""
    e = enforcer()
    e.offer(declaration(seq=0, t_issued=0.0, horizon=0.5), AT_EXTENDED)
    e.adjudicate(proprio(Q_HOME, 0.51))
    e.acknowledge(t=0.6, reason="operator inspected the cell")

    # A forged declaration arrives before the reintegrating one.
    forged = e.offer(declaration(seq=1, t_issued=0.7, key=OTHER_KEYRING.key("policy")), AT_EXTENDED)
    assert forged is not None and forged.fault == "unattributed"
    assert e.passivation_fault == "unattributed"

    resumed = e.offer(declaration(seq=2, t_issued=0.8), AT_EXTENDED)
    assert resumed is not None, "the stale-declaration acknowledgment cleared a forgery"
    assert e.is_passivated


def test_acknowledge_is_refused_when_nothing_is_passivated() -> None:
    """Negative: a pre-emptive acknowledgment would clear a future fault."""
    e = enforcer()
    with pytest.raises(EnforcementError, match="nothing to acknowledge"):
        e.acknowledge(t=0.0, reason="just in case")


def test_acknowledge_twice_is_refused() -> None:
    e = enforcer()
    e.adjudicate(proprio(Q_HOME, 0.1))
    e.acknowledge(t=0.2, reason="first")
    with pytest.raises(EnforcementError, match="already been acknowledged"):
        e.acknowledge(t=0.3, reason="second")


# ==========================================================================
# The chain, the ids and determinism.
# ==========================================================================


def test_verdicts_and_acknowledgments_share_one_chain() -> None:
    e = enforcer()
    e.offer(declaration(seq=0, t_issued=0.0, horizon=0.5), AT_EXTENDED)
    e.adjudicate(proprio(Q_HOME, 0.1))
    e.adjudicate(proprio(Q_HOME, 0.51))
    ack = e.acknowledge(t=0.6, reason="cleared")
    e.offer(declaration(seq=1, t_issued=0.7), AT_EXTENDED)
    e.adjudicate(proprio(Q_HOME, 0.8))

    # PERMIT, VETO(stale), then the acknowledgment, then PERMIT again: the two
    # record types interleave in one chain because they are both enforcement's.
    assert [v.outcome for v in e.verdicts] == ["PERMIT", "VETO", "PERMIT"]
    records: list[object] = [e.verdicts[0], e.verdicts[1], ack, e.verdicts[2]]

    prev = GENESIS_HASH
    for record in records:
        assert record.prev_hash == prev  # type: ignore[attr-defined]
        check = (
            verify_verdict(record, ENFORCEMENT_KEY)
            if isinstance(record, Verdict)
            else verify_acknowledgment(record, ENFORCEMENT_KEY)  # type: ignore[arg-type]
        )
        assert check.state is MacState.VALID
        prev = chain_hash(record, prev)
    assert e.head_hash == prev
    assert len(e.head_hash) == HASH_HEX_LEN


def test_verdict_seq_is_the_verdicts_own_counter() -> None:
    """Not the declaration's: two verdicts against one declaration is normal."""
    e = enforcer()
    e.offer(declaration(seq=17, t_issued=0.0), AT_EXTENDED)
    verdicts = e.adjudicate_all(proprio(Q_HOME, t) for t in (0.1, 0.2, 0.3))
    assert [v.seq for v in verdicts] == [0, 1, 2]
    assert {v.declaration_id for v in verdicts} == {"fixture-decl-00017"}


def test_ids_are_deterministic_and_prefixed() -> None:
    e = enforcer(id_prefix="contact")
    e.offer(declaration(), AT_EXTENDED)
    v = e.adjudicate(proprio(Q_HOME, 0.1))
    assert v.verdict_id == "contact-verdict-00000"


def test_an_action_that_runs_backwards_is_a_caller_error_not_a_fault() -> None:
    """Absorbing it would silently reset the watchdog."""
    e = enforcer()
    e.offer(declaration(), AT_EXTENDED)
    e.adjudicate(proprio(Q_HOME, 0.3))
    with pytest.raises(EnforcementError, match="precedes the previous action"):
        e.adjudicate(proprio(Q_HOME, 0.2))
    with pytest.raises(EnforcementError, match="precedes t_start"):
        enforcer(t_start=1.0).adjudicate(proprio(Q_HOME, 0.5))


def test_the_watchdog_period_and_t_start_have_no_default() -> None:
    """docs/plan.md fixes neither; an invented one decides whether a check fires."""
    with pytest.raises(TypeError, match="watchdog_period_s"):
        Enforcer(  # type: ignore[call-arg]
            LIMITS,
            key=ENFORCEMENT_KEY,
            policy_key=POLICY_KEY,
            t_start=0.0,
            substep_dt=SUBSTEP_DT_S,
            id_prefix="x",
        )
    with pytest.raises(TypeError, match="t_start"):
        Enforcer(  # type: ignore[call-arg]
            LIMITS,
            key=ENFORCEMENT_KEY,
            policy_key=POLICY_KEY,
            watchdog_period_s=1.0,
            substep_dt=SUBSTEP_DT_S,
            id_prefix="x",
        )
    with pytest.raises(EnforcementError, match="strictly positive"):
        enforcer(watchdog_period_s=0.0)


def test_the_enforcer_refuses_keys_of_the_wrong_role() -> None:
    with pytest.raises(EnforcementError, match="enforcement Key"):
        Enforcer(
            LIMITS,
            key=POLICY_KEY,
            policy_key=POLICY_KEY,
            watchdog_period_s=1.0,
            t_start=0.0,
            substep_dt=SUBSTEP_DT_S,
            id_prefix="x",
        )
    with pytest.raises(EnforcementError, match="policy Key or None"):
        Enforcer(
            LIMITS,
            key=ENFORCEMENT_KEY,
            policy_key=ENFORCEMENT_KEY,
            watchdog_period_s=1.0,
            t_start=0.0,
            substep_dt=SUBSTEP_DT_S,
            id_prefix="x",
        )


# ==========================================================================
# ISSUE #106. Two findings about the same function, and they pull opposite ways.
#
#   (2) `horizon_bound` took the module's `SUBSTEP_DT` while the build passed its
#       own, so an artifact built at `--substep-dt 0.05` had its enforcement
#       bound computed on a *finer* grid than the trajectories it was checking.
#       Fixed: the grid is a required argument all the way down, and the run
#       states it once.
#
#   (1) A state whose `|qd|` exceeds `qd_max` — by a rad/s or by one ulp — makes
#       the bound uncomputable, and `offer` raises rather than emitting a
#       verdict. Kept, and the tests below pin the reasons rather than the
#       behaviour alone, because a bare `pytest.raises` would read as an
#       oversight nobody had looked at.
# ==========================================================================


def test_substep_dt_has_no_default_anywhere_the_bound_is_computed() -> None:
    """A bound taken on a grid nobody named is #68's defect in another place.

    Signatures, not just call behaviour: a default reintroduced on any of the
    three would let the enforcement bound and the artifact's geometry drift
    apart again without a single call site changing.
    """
    import inspect

    for fn in (reg.enforce.horizon_bound, reg.enforce.horizon_excess):
        param = inspect.signature(fn).parameters["substep_dt"]
        assert param.default is inspect.Parameter.empty, (
            f"{fn.__name__} has a default substep_dt of {param.default!r}. The "
            "bound would then be computed on a grid the artifact never records."
        )
    init = inspect.signature(Enforcer.__init__).parameters["substep_dt"]
    assert init.default is inspect.Parameter.empty

    with pytest.raises(TypeError, match="substep_dt"):
        Enforcer(  # type: ignore[call-arg]
            LIMITS,
            key=ENFORCEMENT_KEY,
            policy_key=POLICY_KEY,
            watchdog_period_s=1.0,
            t_start=0.0,
            id_prefix="x",
        )
    with pytest.raises(TypeError):
        horizon_bound(AT_EXTENDED, LIMITS, HORIZON_S)  # type: ignore[call-arg]


def test_a_grid_with_no_steps_in_it_is_refused_rather_than_replaced() -> None:
    """THE NEGATIVE. Feed the check the condition it guards against.

    Zero and negative are not a coarser grid, they are no grid; the soundness
    argument is stated over a positive step and there is nothing to fall back
    to that would not be an invented default.
    """
    for bad in (0.0, -0.02):
        with pytest.raises(EnforcementError, match="strictly positive"):
            enforcer(substep_dt=bad)
        with pytest.raises(EnforcementError, match="strictly positive"):
            horizon_bound(AT_EXTENDED, LIMITS, HORIZON_S, bad)
    with pytest.raises(EnforcementError, match="substep_dt"):
        horizon_bound(AT_EXTENDED, LIMITS, HORIZON_S, float("nan"))


def test_the_enforcer_computes_its_bound_on_the_grid_it_was_given() -> None:
    """The plumbing, asserted at the one place it was broken.

    A spy on `outer_envelope` rather than on the returned number: the bound is
    floored by the workspace disc, so at many poses two grids give the *same*
    metre value and an assertion on the result alone would pass while the
    argument was still being dropped.
    """
    seen: list[float] = []
    real = reg.enforce.outer_envelope

    def spy(state, limits, horizon, base, substep_dt):
        seen.append(substep_dt)
        return real(state, limits, horizon, base, substep_dt)

    for grid in (0.02, 0.05):
        seen.clear()
        original = reg.enforce.outer_envelope
        reg.enforce.outer_envelope = spy
        try:
            e = enforcer(substep_dt=grid)
            assert e.substep_dt == grid
            e.offer(declaration(envelope=reachable_looking_declaration()), AT_EXTENDED)
        finally:
            reg.enforce.outer_envelope = original
        assert seen == [grid], (
            f"the enforcer was built with substep_dt={grid} and the bound was "
            f"computed on {seen}. Two numbers in one run disagreeing about the "
            "discretisation they describe is exactly issue #106."
        )


def test_substep_dt_widens_the_reachable_joint_box_it_enters_through() -> None:
    """The direction the parameter actually has, on the term that actually has it.

    `substep_dt` reaches the bound through one place —
    `reg.envelope.reachable_joint_box` raises the initial speed by half a step
    of acceleration so the box covers the *discrete* trajectory as well as the
    continuous one — and there it is monotone: a coarser grid can only widen the
    box. That is what makes the old behaviour a defect rather than a wash. An
    enforcer on the module's 0.02 grid was bounding a run integrated at 0.05
    with a box built for a finer discretisation than the one the artifact
    records.

    **The radial projection of the outer set is not monotone, and that is not a
    contradiction.** `reg.envelope._ancestor_grid` picks its sampling resolution
    from the box it is given, so a wider box can be swept on a differently
    spaced grid and come out with a radius up to about 3.6 mm *smaller* — a
    discretisation artefact of the polygon construction, measured over the poses
    below, against genuine widenings of up to 1.1 cm. Each grid's bound is sound
    for its own trajectories, which is the property that matters; "coarser is
    always looser" is not true of the radius and is deliberately not asserted
    here. Issue #106.
    """
    from reg.envelope import reachable_joint_box

    strictly_wider = 0
    for q in (Q_EXTENDED, Q_FOLDED, Q_HOME, Q_FAR, Q_IN_BOX):
        for qd in ((0.0, 0.0), (2.0, 2.5), (-2.0, -2.5)):
            for window in (0.05, 0.2, 0.5):
                state = proprio(q, 0.0, qd)
                lo_fine, hi_fine = reachable_joint_box(state, LIMITS, window, 0.02)
                lo_coarse, hi_coarse = reachable_joint_box(state, LIMITS, window, 0.05)
                assert np.all(lo_coarse <= lo_fine + 1e-15), (
                    f"q={q} qd={qd} window={window}: the coarser grid's box does "
                    "not contain the finer one's, so the term that covers the "
                    "discretisation is not covering it."
                )
                assert np.all(hi_coarse >= hi_fine - 1e-15)
                strictly_wider += bool(
                    np.any(hi_coarse - hi_fine > 1e-12)
                    or np.any(lo_fine - lo_coarse > 1e-12)
                )
    assert strictly_wider, (
        "no box was widened at all, so this test would pass on code that "
        "ignored substep_dt entirely."
    )


def test_the_grid_changes_the_bound_by_more_than_rounding() -> None:
    """Non-vacuity for the whole of finding (2): the parameter is not decorative.

    If the two grids gave the same metre value everywhere, computing the bound
    on one and the trajectories on the other would be an inconsistency nobody
    could observe, and threading the argument through would be ceremony. They do
    not: over the poses below the bounds differ by up to about a centimetre,
    which is the resolution `docs/lossiness.md` advertises for distances.
    """
    spread = 0.0
    for q in (Q_FOLDED, Q_HOME, Q_FAR, Q_IN_BOX):
        for window in (0.05, 0.2, 0.5):
            state = proprio(q, 0.0)
            fine = horizon_bound(state, LIMITS, window, 0.02)
            coarse = horizon_bound(state, LIMITS, window, 0.05)
            spread = max(spread, abs(coarse - fine))
    assert spread > 1e-3, (
        f"the two grids agree to {spread} m everywhere tested, so this file "
        "cannot tell which one a bound was computed on."
    )


#: The three identity flags as argv. Required with no default (issue #83), so a
#: CLI test that omitted them would exercise that refusal instead of the grid.
_IDENTITY_ARGV = [
    "--run-start",
    "2026-08-21T09:00:00Z",
    "--unit-id",
    "unit-test-arm-1",
    "--operator-id",
    "op-test",
]


def _held_stream(path: pathlib.Path, n_frames: int) -> pathlib.Path:
    """A stream in which nothing moves, written through the real codec.

    Short and static on purpose: this fixture is about which `substep_dt` the
    two producers were given, not about what the arm did, and a full scenario
    would spend minutes computing envelopes to say the same thing. The
    provenance block names a scenario `reg.graph` can resolve, because a build
    refuses a stream whose world it cannot look up rather than guessing one.
    """
    from reg.stream import write_frames

    frames = [
        StateFrame(
            t=i * 0.05,
            q=np.asarray(Q_EXTENDED, dtype=float),
            qd=np.zeros(2),
            human_pos=np.array([2.0, 0.0]),
            human_vel=np.zeros(2),
            base_vel=None,
            base_pose=None,
            objects=(),
        )
        for i in range(n_frames)
    ]
    return write_frames(
        frames,
        path,
        comments=["reg-sim provenance v1", "scenario=contact", "seed=0"],
    )


def test_the_artifact_and_its_enforcement_bound_share_one_substep_dt(
    tmp_path: pathlib.Path,
) -> None:
    """THE ACCEPTANCE CRITERION, end to end and through the CLI.

    `--substep-dt` is stated once and has to reach both producers: the geometry
    pass in `reg.graph` and the overclaim bound in `reg.enforce`. Both are
    spied on, and both are checked against what the artifact itself records as
    the grid it was built on — reading the number back out of the file rather
    than comparing two constants the test wrote, because the artifact is what a
    later reader has.

    A grid deliberately not equal to `reg.envelope.SUBSTEP_DT`: on the module
    default this test would pass on the code that had the defect.
    """
    from reg import graph, store
    from reg.envelope import SUBSTEP_DT as _MODULE_DEFAULT

    grid = 0.05
    assert grid != _MODULE_DEFAULT

    from reg.chain import write_keyring

    csv = _held_stream(tmp_path / "held.csv", 8)
    out = tmp_path / "held.sqlite"
    keyring_path = write_keyring(KEYRING, tmp_path / "keyring.json")

    build_grids: list[float] = []
    enforce_grids: list[float] = []

    def spy(sink, real):
        def wrapped(state, limits, horizon, base, substep_dt):
            sink.append(substep_dt)
            return real(state, limits, horizon, base, substep_dt)

        return wrapped

    graph_real, enforce_real = graph.outer_envelope, reg.enforce.outer_envelope
    graph.outer_envelope = spy(build_grids, graph_real)
    reg.enforce.outer_envelope = spy(enforce_grids, enforce_real)
    try:
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
                str(grid),
                "--keyring",
                str(keyring_path),
                "--replan-interval",
                str(FIXTURE_REPLAN_S),
                "--declaration-horizon",
                str(FIXTURE_HORIZON_S),
                "--watchdog-period",
                str(FIXTURE_WATCHDOG_S),
                *_IDENTITY_ARGV,
            ]
        )
    finally:
        graph.outer_envelope = graph_real
        reg.enforce.outer_envelope = enforce_real

    assert code == 0
    conn = store.connect(out)
    try:
        recorded = float(store.all_meta(conn)[graph.META_SUBSTEP_DT])
        assert store.read_verdicts(conn), (
            "no verdicts, so enforcement never ran and this test would assert "
            "nothing about the bound."
        )
    finally:
        conn.close()

    assert enforce_grids, "the overclaim bound was never computed"
    assert build_grids, "no envelope was built"
    assert set(build_grids) == set(enforce_grids) == {recorded} == {grid}, (
        f"the artifact records substep_dt={recorded}, the geometry pass used "
        f"{sorted(set(build_grids))} and the enforcement bound used "
        f"{sorted(set(enforce_grids))}. One run, one discretisation (#106)."
    )


# --- (1): an out-of-limits state aborts, and here is why -------------------


def _one_ulp_over_the_velocity_limit() -> ProprioState:
    """At rest but for one joint, whose velocity is the smallest float above `qd_max`.

    The original trigger was the piecewise-linear interpolant producing
    2.5000000000000004 against a 2.5 limit; #96 clips it away, so the condition
    is reproduced here on purpose rather than waited for.
    """
    qd = np.zeros(len(LIMITS.qd_max))
    qd[-1] = math.nextafter(float(LIMITS.qd_max[-1]), math.inf)
    return ProprioState(t=0.0, q=np.asarray(Q_EXTENDED, dtype=float), qd=qd, base_vel=None)


def test_a_state_exactly_at_the_velocity_limit_is_a_bound_like_any_other() -> None:
    """POSITIVE CONTROL, and it is the boundary case, not a comfortable interior one.

    Without this the refusal below could be a check that rejects fast states
    generally rather than impossible ones.
    """
    qd = np.zeros(len(LIMITS.qd_max))
    qd[-1] = float(LIMITS.qd_max[-1])
    at_limit = ProprioState(t=0.0, q=np.asarray(Q_EXTENDED, dtype=float), qd=qd, base_vel=None)
    radius = horizon_bound(at_limit, LIMITS, HORIZON_S, SUBSTEP_DT_S)
    assert 0.0 < radius <= computed_bound(LIMITS) + 1e-12
    assert enforcer().offer(declaration(), at_limit) is None


def test_a_state_over_its_own_velocity_limit_is_refused_and_says_which_joint() -> None:
    """THE NEGATIVE. One ulp over is over: there is no tolerance band here.

    A bound integrated from a velocity the robot cannot have is a bound for a
    different robot, and `reg.envelope` refuses to produce one. What this
    asserts beyond the raise is that the message names the joint and the limit —
    an abort whose reason nobody can read is the failure mode issue #106 opens
    with.
    """
    over = _one_ulp_over_the_velocity_limit()
    with pytest.raises(EnforcementError) as excinfo:
        horizon_bound(over, LIMITS, HORIZON_S, SUBSTEP_DT_S)
    message = str(excinfo.value)
    assert "qd_max" in message and "joint" in message, message
    assert "issue #106" in message, (
        "the abort has to point at the decision that made it an abort, or the "
        "next reader files the same issue again. Got: " + message
    )


def test_an_out_of_limits_state_leaves_the_verdict_chain_untouched() -> None:
    """The decision, asserted as a decision: no verdict, and nothing half-emitted.

    If this ever becomes a verdict the assertions here are the ones that have to
    change, which is the point of writing them down: the enforcer emits nothing,
    its chain head is where it was, and the caller is the one holding the
    problem.
    """
    e = enforcer()
    assert e.offer(declaration(seq=0), AT_EXTENDED) is None
    head_before = e.head_hash
    count_before = len(e.verdicts)

    with pytest.raises(EnforcementError, match="could not be computed"):
        e.offer(declaration(seq=1, t_issued=0.1), _one_ulp_over_the_velocity_limit())

    assert e.head_hash == head_before
    assert len(e.verdicts) == count_before
    assert not e.is_passivated, (
        "an unevaluable input is not a fault of the policy, so it must not "
        "passivate the enforcer the way the nine faults do."
    )


def test_an_out_of_limits_state_is_refused_by_the_envelope_pass_too() -> None:
    """Reason 3 for keeping it a raise, checked rather than asserted in a comment.

    `reg.graph._observe` computes `compute_envelope` for every frame, so a run
    holding this state produces no artifact whatever `offer` returns. A verdict
    here would change which exception the operator sees and nothing else — and
    if that ever stops being true, this test fails and the decision in
    `reg/enforce.py`'s header is due for another look.
    """
    over = _one_ulp_over_the_velocity_limit()
    with pytest.raises(ValueError, match="qd_max"):
        compute_envelope(over, LIMITS, horizon=0.1, n_samples=4, seed=0, substep_dt=0.05)


def test_no_fault_in_the_taxonomy_names_an_unevaluable_input() -> None:
    """Reason 1, and the thing that would have to change first.

    The nine are about what the *policy* did. A verdict must name one of them
    (`Verdict.__post_init__` refuses a tenth), so emitting one for a state the
    stream and the limits table disagree about would be a signed accusation
    against a party that did nothing. This test is a tripwire on that argument:
    add a fault for an unevaluable input and it fails, which is the moment to
    revisit `offer`.
    """
    assert len(FAULTS) == 9
    assert not [f for f in FAULTS if "evaluate" in f or "limit" in f]
    assert "COULD_NOT_EVALUATE" not in OUTCOMES


# ==========================================================================
# The real fixture: a verdict is per commanded action, not per declaration.
# ==========================================================================

#: The policy's parameters for the fixture run, stated because
#: `emit_declarations` refuses to invent them.
FIXTURE_REPLAN_S = 0.5
FIXTURE_HORIZON_S = 0.5
FIXTURE_WATCHDOG_S = 1.0


@dataclasses.dataclass(frozen=True)
class FixtureRun:
    """One fixture, adjudicated end to end: what the policy said and what came back.

    `refusals` and `actions` are kept apart because they answer different
    questions — a refusal is a finding about a *declaration* and an action
    verdict is a finding about a commanded action — and both are in
    `enforcer.verdicts`, in the order they were emitted.
    """

    scenario: Scenario
    seed: int
    enforcer: Enforcer
    declarations: tuple[Declaration, ...]
    refusals: tuple[Verdict, ...]
    actions: tuple[Verdict, ...]

    @property
    def verdicts(self) -> tuple[Verdict, ...]:
        return self.enforcer.verdicts

    @property
    def faults(self) -> set[str]:
        return {v.fault for v in self.verdicts if v.fault is not None}


def nonconforming_declarations(
    declarations: tuple[Declaration, ...], action_class: str
) -> tuple[Declaration, ...]:
    """Re-issue a stream from a producer that does not share the vocabulary.

    `reg.declare` refuses to *construct* a declaration whose `action_class` is
    outside `ACTION_CLASSES`, which is why `reg.scenarios.OUT_OF_VOCABULARY_ACTION`
    cannot be produced by it and why this exists here rather than there — a
    producer that could emit one would make that module's refusal decorative.

    The whole chain is re-issued rather than the field edited in place: the MAC
    covers every field and `prev_hash` covers the MAC, so a stream with one
    record rewritten would be an unattributed one, and the fault under test
    would be the wrong one. What arrives at enforcement is therefore a
    well-formed, correctly signed, correctly linked stream whose only defect is
    a word nothing downstream knows.
    """
    out: list[Declaration] = []
    prev_hash = GENESIS_HASH
    for d in declarations:
        forged = Declaration(
            declaration_id=d.declaration_id,
            seq=d.seq,
            t_issued=d.t_issued,
            horizon=d.horizon,
            # Constructed in vocabulary, then stamped: this producer is the one
            # that never asked what the vocabulary was.
            action_class="hold",
            declared_envelope=d.declared_envelope,
            prev_hash=prev_hash,
            mac=UNSIGNED_MAC,
        )
        object.__setattr__(forged, "action_class", action_class)
        object.__setattr__(forged, "mac", sign(forged, POLICY_KEY))
        out.append(forged)
        prev_hash = chain_hash(forged, prev_hash)
    return tuple(out)


def declarations_for(
    scenario: Scenario, states: list[ProprioState]
) -> tuple[Declaration, ...]:
    """The declaration stream this fixture's policy emits over `states`.

    Three fixture fields decide what the policy does and none of them has a
    default: it is silent inside `silent_windows`, it pads its region by
    `declared_margin_m`, and it stamps `declared_action_class` if the fixture
    says it has one. Everything else is `reg.declare.emit_declarations`.
    """
    speaking = [state for state in states if not scenario.silent_at(state.t)]
    if not speaking:
        # A policy that never says anything. Not an empty stream to paper over —
        # `emit_declarations` refuses an empty run, and it is right to: this is
        # the fixture, not a degenerate call.
        return ()
    declarations = emit_declarations(
        speaking,
        LIMITS,
        key=POLICY_KEY,
        replan_interval_s=FIXTURE_REPLAN_S,
        horizon_s=FIXTURE_HORIZON_S,
        declared_q_bounds=scenario.declared_q_bounds,
        declared_margin_m=scenario.declared_margin_m,
        id_prefix=scenario.name,
    )
    if scenario.declared_action_class is None:
        return declarations
    return nonconforming_declarations(declarations, scenario.declared_action_class)


def run_scenario(scenario: Scenario, seed: int) -> FixtureRun:
    """Adjudicate a whole fixture: real declarations, real enforcer, in time order.

    Nobody acknowledges anything. An acknowledgment is an operator saying it is
    safe to resume, and inserting one here would be this harness deciding that —
    which is exactly the decision `escalation_failure` is about the absence of.
    """
    states = [frame.proprio() for frame in scenario.states(seed)]
    declarations = declarations_for(scenario, states)
    pending = {round(d.t_issued, 9): d for d in declarations}

    e = Enforcer(
        LIMITS,
        key=ENFORCEMENT_KEY,
        policy_key=POLICY_KEY,
        watchdog_period_s=FIXTURE_WATCHDOG_S,
        t_start=0.0,
        substep_dt=SUBSTEP_DT_S,
        id_prefix=scenario.name,
    )
    refusals: list[Verdict] = []
    actions: list[Verdict] = []
    for state in states:
        due = pending.pop(round(state.t, 9), None)
        if due is not None:
            refused = e.offer(due, state)
            if refused is not None:
                refusals.append(refused)
        actions.append(e.adjudicate(state))
    assert not pending, (
        f"{scenario.name}: {len(pending)} declarations were issued at instants "
        "that are not frames of the run, so they were never offered."
    )
    return FixtureRun(
        scenario=scenario,
        seed=seed,
        enforcer=e,
        declarations=declarations,
        refusals=tuple(refusals),
        actions=tuple(actions),
    )


def run_declared_violation(seed: int) -> tuple[Enforcer, tuple[Declaration, ...], list[Verdict]]:
    """Adjudicate the `declared_violation` fixture, declarations and all."""
    run = run_scenario(SCENARIOS["declared_violation"], seed)
    assert not run.refusals, "the fixture's own declarations are honest"
    return run.enforcer, run.declarations, list(run.actions)


def test_declared_violation_permits_then_clamps_against_identical_declarations() -> None:
    """The per-action property, on the real fixture rather than a synthetic one.

    Every declaration in this run carries the *same* `declared_envelope` — the
    box is fixed for the whole run — and differs only in `seq`, `t_issued` and
    `prev_hash`. The violation begins partway through, so a declaration is not
    good or bad: one of them is adjudicated PERMIT and then CLAMP.
    """
    e, declarations, verdicts = run_declared_violation(seed=0)

    assert len({d.declared_envelope for d in declarations}) == 1
    assert len({d.seq for d in declarations}) == len(declarations)
    assert not e.is_passivated, "an honest fixture must not trip any check"

    counts = Counter(v.outcome for v in verdicts)
    assert counts["PERMIT"] > 0 and counts["CLAMP"] > 0
    assert set(counts) == {"PERMIT", "CLAMP"}

    first_clamp = next(i for i, v in enumerate(verdicts) if v.outcome == "CLAMP")
    assert first_clamp > 0
    assert all(v.outcome == "PERMIT" for v in verdicts[:first_clamp])
    assert all(v.fault is None for v in verdicts[:first_clamp])

    # The property the ADJUDICATED edge must not flatten: one declaration_id
    # carrying both outcomes.
    by_declaration: dict[str | None, set[str]] = {}
    for v in verdicts:
        by_declaration.setdefault(v.declaration_id, set()).add(v.outcome)
    both = [k for k, outcomes in by_declaration.items() if outcomes == {"PERMIT", "CLAMP"}]
    assert both, (
        "no declaration was adjudicated both ways. A verdict is per commanded "
        "action, not per declaration — one verdict per declaration cannot "
        "express this run."
    )

    for v in verdicts:
        if v.outcome == "CLAMP":
            assert v.fault == "declaration_action_mismatch"
            assert v.clamped_envelope == declarations[0].declared_envelope


def test_declared_violation_verdicts_are_all_attributed_to_enforcement() -> None:
    e, _, verdicts = run_declared_violation(seed=0)
    assert len(verdicts) == len(e.verdicts)
    for v in verdicts:
        assert verify_verdict(v, ENFORCEMENT_KEY).state is MacState.VALID
        assert verify_verdict(v, None).state is MacState.COULD_NOT_EVALUATE


def test_the_verdict_stream_is_deterministic() -> None:
    """Same seed, same verdicts, same MACs, same chain head. CLAUDE.md rule 2."""
    a_enforcer, _, a = run_declared_violation(seed=0)
    b_enforcer, _, b = run_declared_violation(seed=0)
    assert a == b
    assert a_enforcer.head_hash == b_enforcer.head_hash

    _, _, other = run_declared_violation(seed=1)
    assert len(other) == len(a)


#: The fixtures that must produce nothing: no silence, no padding, no borrowed
#: vocabulary, and a claim that is true of the run. Selected by `fault is None`
#: rather than by name, so a fixture added later is included or excluded by what
#: it says about itself.
COMPLIANT = [name for name, s in SCENARIOS.items() if s.fault is None]

#: The fixtures that must produce exactly one named fault, and the response
#: docs/plan.md's taxonomy specifies for it. Written out rather than derived:
#: the response is the taxonomy's decision, and a table computed from the code
#: under test would agree with it by construction.
FAULT_RESPONSE: dict[str, str] = {
    "declared_violation": "CLAMP",
    "no_declaration": "VETO",
    "stale_declaration": "VETO",
    "envelope_overclaim": "VETO",
    "out_of_vocabulary_action": "VETO",
    "escalation_failure": "SAFE_STATE",
}

FAULT_FIXTURES = [name for name, s in SCENARIOS.items() if s.fault is not None]

#: Three seeds for the end-to-end fault tests. The seed perturbs the waypoints,
#: so a fault that only fires at seed 0 is a fixture tuned to one draw.
FIXTURE_SEEDS = (0, 1, 7)


@pytest.mark.parametrize("name", COMPLIANT)
def test_a_compliant_fixture_is_permitted_throughout(name: str) -> None:
    """The positive control for the whole taxonomy, on every compliant fixture.

    These five declare exactly the region their own configurations sweep
    (`declared_q_bounds=None`), which is a true statement about themselves.
    Nothing in the taxonomy should fire on any of them — this is the test that
    would catch a bound that cries wolf, and if it goes red the bound is wrong,
    not the fixture and not the tolerance.

    Adding the fault fixtures of issue #46 must not disturb it: they are
    excluded because each states the fault it exists to produce, not because
    they were listed out here.
    """
    scenario = SCENARIOS[name]
    assert scenario.fault is None
    assert scenario.declared_q_bounds is None
    assert scenario.declared_margin_m is None
    assert scenario.declared_action_class is None
    assert scenario.silent_windows == ()

    run = run_scenario(scenario, 0)
    assert not run.refusals
    for v in run.actions:
        assert v.outcome == "PERMIT", (
            f"{scenario.name} t={v.t}: an honest declaration produced "
            f"{v.outcome}/{v.fault}. Do not widen a tolerance to fix this — the "
            "bound is wrong."
        )
    assert not run.enforcer.is_passivated


# ==========================================================================
# One fixture per semantic fault (issue #46).
#
# The synthetic cases above (issue #43) already demonstrate all nine against
# declarations built in this file, which tests the detector and says nothing
# about whether the fault can occur. These run the real enforcer over the real
# declarations of a real fixture: a fault that has never appeared in a run
# cannot reach the graph, the occurrence layer, or an incident report.
#
# The three transport faults — `unattributed`, `replay_or_reorder`,
# `watchdog_expiry` — deliberately have no fixture and keep their synthetic
# tests above. They are PROFIsafe's (docs/prior-art.md §5), and forging a MAC
# inside a fixture would mean the fixture generator holding a key it should not
# have.
# ==========================================================================


def test_the_fault_table_covers_every_fault_fixture() -> None:
    """Guards every test below: a fixture missing from the table is untested.

    Without this, adding a fixture and forgetting to say what its response is
    would silently shrink the parametrization, and the suite would go green over
    a fault nobody adjudicated.
    """
    assert set(FAULT_FIXTURES) == set(FAULT_RESPONSE)
    assert set(FAULT_RESPONSE.values()) <= set(OUTCOMES)
    for name in FAULT_FIXTURES:
        assert SCENARIOS[name].fault in FAULTS
    assert set(COMPLIANT) & set(FAULT_FIXTURES) == set()
    assert len(COMPLIANT) + len(FAULT_FIXTURES) == len(SCENARIOS)


@pytest.mark.parametrize("name", FAULT_FIXTURES)
@pytest.mark.parametrize("seed", FIXTURE_SEEDS)
def test_a_fault_fixture_produces_the_fault_it_is_named_for(name: str, seed: int) -> None:
    """The whole point of the fixtures. Real declarations, real enforcer.

    Asserted with the response as well as the fault: a fixture that produced
    `stale_declaration` as a CLAMP would be evidence that the taxonomy's
    response had drifted, and a report written against it would say the robot
    was allowed to continue when it was not.
    """
    scenario = SCENARIOS[name]
    run = run_scenario(scenario, seed)
    hits = [v for v in run.verdicts if v.fault == scenario.fault]
    assert hits, (
        f"{name} produced no {scenario.fault!r} verdict at seed {seed}; it "
        f"produced {sorted(run.faults) or 'nothing'}. A fixture named for a "
        "fault that does not fire is a green test asserting nothing — the "
        "fixture is wrong, not the detector (#22)."
    )
    assert hits[0].outcome == FAULT_RESPONSE[name], (
        f"{name}: {scenario.fault} came back as {hits[0].outcome}, not the "
        f"{FAULT_RESPONSE[name]} the taxonomy specifies."
    )
    for v in run.verdicts:
        assert verify_verdict(v, ENFORCEMENT_KEY).state is MacState.VALID


@pytest.mark.parametrize("name", FAULT_FIXTURES)
@pytest.mark.parametrize("seed", FIXTURE_SEEDS)
def test_a_fault_fixture_produces_no_transport_fault(name: str, seed: int) -> None:
    """The fixtures are about semantics; the channel in them is clean.

    `unattributed`, `replay_or_reorder` and `watchdog_expiry` have no fixture on
    purpose. One of them firing here would mean a fixture is producing its fault
    by breaking the channel — a MAC that does not verify, a sequence that goes
    backwards, a policy that simply stopped — and the run would be evidence
    about transport rather than about what the declaration meant.
    """
    faults = run_scenario(SCENARIOS[name], seed).faults
    assert faults.isdisjoint({"unattributed", "replay_or_reorder", "watchdog_expiry"})


@pytest.mark.parametrize(
    "name", [n for n in FAULT_FIXTURES if n != "escalation_failure"]
)
@pytest.mark.parametrize("seed", FIXTURE_SEEDS)
def test_the_named_fault_is_the_first_thing_that_goes_wrong(name: str, seed: int) -> None:
    """Nothing else catches it — asserted, not claimed in the description.

    The first verdict that is not a PERMIT has to be the fault the fixture is
    named for. If something else fires first, the fixture is producing its fault
    as a consequence of a different one and the incident it narrates is not the
    incident it says it is.

    `escalation_failure` is excluded and has its own test below: by definition
    its window is opened by another fault passivating the enforcer, so it is the
    one fixture where the named fault is not the first.
    """
    scenario = SCENARIOS[name]
    run = run_scenario(scenario, seed)
    first = next((v for v in run.verdicts if v.outcome != "PERMIT"), None)
    assert first is not None, f"{name} produced no fault at all"
    assert first.fault == scenario.fault, (
        f"{name}: the first thing to fire at seed {seed} was {first.fault!r} at "
        f"t={first.t}, not the {scenario.fault!r} the fixture is named for."
    )
    assert run.faults == {scenario.fault}, (
        f"{name} produced {sorted(run.faults)}; a fixture that produces two "
        "faults cannot be the fixture either of them is demonstrated against."
    )


@pytest.mark.parametrize("name", FAULT_FIXTURES)
@pytest.mark.parametrize("seed", FIXTURE_SEEDS)
def test_arranging_the_fault_away_leaves_a_run_that_is_permitted_throughout(
    name: str, seed: int
) -> None:
    """NEGATIVE, and the strongest thing these fixtures assert.

    Each fault fixture is one policy behaviour away from a clean run: take away
    the silence, the padding, the borrowed vocabulary or the fixed box and the
    same trajectory, the same seed and the same enforcer produce PERMIT on every
    frame. So the fault is caused by the thing the fixture's description says
    causes it, and not by the geometry, the human, the timestep or the seed.

    It is also the negative half of the checks themselves: a detector stuck at
    'fault' would pass every test above and fail this one.
    """
    scenario = SCENARIOS[name]
    compliant = dataclasses.replace(
        scenario,
        declared_q_bounds=None,
        declared_margin_m=None,
        declared_action_class=None,
        silent_windows=(),
        fault=None,
    )
    run = run_scenario(compliant, seed)
    assert not run.refusals
    assert run.faults == set(), (
        f"{name} with its fault arranged away still produced "
        f"{sorted(run.faults)} at seed {seed}."
    )
    assert all(v.outcome == "PERMIT" for v in run.actions)


def test_the_no_declaration_fixture_declares_nothing_at_all() -> None:
    """The arrangement, checked at the source rather than inferred from the verdict."""
    scenario = SCENARIOS["no_declaration"]
    run = run_scenario(scenario, 0)
    assert run.declarations == ()
    assert run.enforcer.open_declaration is None
    first = run.actions[0]
    assert (first.outcome, first.fault) == ("VETO", "no_declaration")
    assert first.t == 0.0, "the veto is on the first commanded action, not a later one"
    assert first.declaration_id is None, (
        "there is no declaration to name, and `None` is the finding rather than "
        "a gap in the record."
    )
    # And it stays a safe state: recovery needs a fresh declaration and an
    # acknowledgment, and this run has neither.
    assert {v.outcome for v in run.actions[1:]} == {"SAFE_STATE"}


def test_the_stale_fixture_expires_one_horizon_after_the_last_declaration() -> None:
    """Staleness is about the horizon, and it is not the watchdog.

    The two are different failures with different remedies — a policy that has
    gone quiet versus a claim that has run out — so the instant is asserted
    against the horizon, and the watchdog is asserted not to have fired. The
    fixture's silence is longer than the horizon and shorter than the watchdog
    period on purpose, and this is where that arithmetic is checked rather than
    trusted.
    """
    scenario = SCENARIOS["stale_declaration"]
    run = run_scenario(scenario, 0)
    last = run.declarations[-1]
    assert last.t_issued < scenario.silent_windows[0][0]

    stale = [v for v in run.verdicts if v.fault == "stale_declaration"]
    first_stale = stale[0]
    assert first_stale.outcome == "VETO"
    assert first_stale.declaration_id == last.declaration_id
    expiry = last.t_issued + last.horizon
    assert first_stale.t == pytest.approx(expiry + scenario.dt, abs=1e-9), (
        "the first stale verdict must be the first frame past the horizon; "
        "earlier means the boundary is being excluded, later means a frame was "
        "adjudicated against an expired claim and permitted."
    )
    assert all(v.outcome == "PERMIT" for v in run.actions if v.t <= expiry)
    assert first_stale.t < last.t_issued + FIXTURE_WATCHDOG_S, (
        "the horizon has to expire before the watchdog period, or this fixture "
        "is a watchdog fixture wearing a staleness label."
    )
    assert "watchdog_expiry" not in run.faults


def test_the_overclaim_fixture_declares_past_the_independently_computed_bound() -> None:
    """The claim is refuted by `Limits` alone, and no joint box could make it.

    Both halves matter. The padded region has to reach measurably outside the
    workspace disc — otherwise the fixture is riding on a rounding difference —
    and the *unpadded* claim has to lie inside it, or the fixture would be
    demonstrating that the arm itself is out of bounds.
    """
    scenario = SCENARIOS["envelope_overclaim"]
    assert scenario.declared_margin_m is not None
    run = run_scenario(scenario, 0)
    assert run.declarations, "no declaration to overclaim with"

    for d in run.declarations:
        excess = envelope_excess(d.envelope(), LIMITS)
        assert excess > 0.01, (
            f"{d.declaration_id} reaches only {excess:.4f} m past the "
            f"{computed_bound(LIMITS):.4f} m bound; that is close enough to the "
            "boundary that the fault would turn on floating point rather than on "
            "the claim."
        )
    assert len(run.refusals) == len(run.declarations), (
        "every declaration in this run overclaims, so every one is refused; a "
        "run where some got through would be adjudicating two different things."
    )

    # The honest half: the region the arm actually sweeps is inside the bound,
    # so what is out of bounds is the padding and only the padding.
    honest = declarations_for(
        dataclasses.replace(scenario, declared_margin_m=None),
        [f.proprio() for f in scenario.states(0)],
    )
    for d in honest:
        assert envelope_excess(d.envelope(), LIMITS) < 0.0


def test_the_out_of_vocabulary_fixture_is_well_formed_but_for_one_word() -> None:
    """Everything else about the declaration is correct, which is the point.

    If the record were also unsigned, or out of sequence, or geometrically
    dishonest, the VETO would prove nothing about the vocabulary — one of the
    other checks would have caught it first, and `offer` checks attribution
    before it checks anything else.
    """
    scenario = SCENARIOS["out_of_vocabulary_action"]
    assert scenario.declared_action_class not in ACTION_CLASSES
    run = run_scenario(scenario, 0)

    for d in run.declarations:
        assert d.action_class == scenario.declared_action_class
        assert verify_declaration(d, POLICY_KEY).state is MacState.VALID
        assert envelope_excess(d.envelope(), LIMITS) < 0.0
    assert [d.seq for d in run.declarations] == list(range(len(run.declarations)))
    assert run.declarations[0].prev_hash == GENESIS_HASH
    for previous, nxt in zip(run.declarations, run.declarations[1:]):
        assert nxt.prev_hash == chain_hash(previous, previous.prev_hash)

    assert [v.fault for v in run.refusals] == [
        "out_of_vocabulary_action" for _ in run.declarations
    ]


def test_escalation_failure_is_an_ordinary_declaration_inside_a_passivation() -> None:
    """The sequence, in the order `reg/enforce.py` defines the obligation in.

    A passivation opens the window; the window stays open until an
    acknowledgment; a declaration issued inside it that is not an `escalate` is
    the fault. So this asserts all four: the window was opened by an earlier
    fault, nothing acknowledged it, the late declaration is an ordinary one from
    the vocabulary, and the verdict lands at the instant it was issued.
    """
    scenario = SCENARIOS["escalation_failure"]
    run = run_scenario(scenario, 0)

    opening = next(v for v in run.verdicts if v.fault is not None)
    assert opening.outcome == "VETO", "the window is opened by a passivation"
    assert opening.fault != "escalation_failure"

    failures = [v for v in run.verdicts if v.fault == "escalation_failure"]
    assert failures, "the policy never declared again, so nothing was obliged"
    first = failures[0]
    assert first.outcome == "SAFE_STATE", "flag and safe state, per the taxonomy"
    assert first.t > opening.t

    late = next(d for d in run.declarations if d.declaration_id == first.declaration_id)
    assert late.t_issued == pytest.approx(first.t, abs=1e-9)
    assert late.action_class in ACTION_CLASSES
    assert late.action_class != "escalate", (
        "an `escalate` here would be the policy doing what it was obliged to do"
    )
    assert run.enforcer.acknowledgments == (), "nothing acknowledged the passivation"
    assert not run.enforcer.escalated


def test_an_acknowledged_passivation_makes_the_same_declaration_lawful() -> None:
    """NEGATIVE for `escalation_failure`: the window closes, and the check says no.

    The same fixture, the same seed, the same declarations — with one
    acknowledgment recorded before the policy speaks again. The obligation to
    escalate ends at the acknowledgment, so the declaration that was a fault a
    moment ago is now accepted and the robot is reintegrated. Without this, a
    check that reported `escalation_failure` for *every* declaration after a
    passivation would pass every other test in this file.
    """
    scenario = SCENARIOS["escalation_failure"]
    states = [frame.proprio() for frame in scenario.states(0)]
    declarations = declarations_for(scenario, states)
    pending = {round(d.t_issued, 9): d for d in declarations}

    e = Enforcer(
        LIMITS,
        key=ENFORCEMENT_KEY,
        policy_key=POLICY_KEY,
        watchdog_period_s=FIXTURE_WATCHDOG_S,
        t_start=0.0,
        substep_dt=SUBSTEP_DT_S,
        id_prefix=scenario.name,
    )
    acknowledged = False
    faults: list[str] = []
    for state in states:
        # The operator acknowledges as soon as the enforcer passivates, which is
        # the difference between this run and the fixture's own.
        if e.is_passivated and not acknowledged:
            e.acknowledge(t=state.t, reason="operator inspected the cell and cleared it")
            acknowledged = True
        due = pending.pop(round(state.t, 9), None)
        if due is not None:
            refused = e.offer(due, state)
            if refused is not None:
                faults.append(refused.fault or "")
        v = e.adjudicate(state)
        if v.fault is not None:
            faults.append(v.fault)

    assert acknowledged, "the run never passivated, so there was nothing to close"
    assert "escalation_failure" not in faults, (
        "an acknowledged passivation obliges no escalation; reporting one here "
        "would make the acknowledgment record decorative."
    )
    assert not e.is_passivated, "a fresh declaration plus an acknowledgment resumes"
    assert e.acknowledgments and e.acknowledgments[0].fault == "stale_declaration"


@pytest.mark.parametrize("name", FAULT_FIXTURES)
def test_a_fault_fixtures_verdict_stream_is_deterministic(name: str) -> None:
    """Same seed, same verdicts, same MACs, same chain head. CLAUDE.md rule 2."""
    first = run_scenario(SCENARIOS[name], 0)
    second = run_scenario(SCENARIOS[name], 0)
    assert first.verdicts == second.verdicts
    assert first.enforcer.head_hash == second.enforcer.head_hash
    assert first.declarations == second.declarations
