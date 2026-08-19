"""Enforcement: the independent bound, the `Verdict`, and the nine faults.

Four things this file is really about.

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
"""

from __future__ import annotations

import ast
import dataclasses
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
    sign_acknowledgment,
    sign_verdict,
    verify_acknowledgment,
    verify_verdict,
)
from reg.envelope import HASH_COORD_PRECISION, compute_envelope, envelope_area
from reg.kinematics import link_polygons
from reg.scenarios import SCENARIOS
from reg.types import Limits, Obstacle, ProprioState, StateFrame
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


def proprio(q: tuple[float, float], t: float, qd: tuple[float, float] = (0.0, 0.0)):
    return ProprioState(t=t, q=np.asarray(q, dtype=float), qd=np.asarray(qd, dtype=float))


def body_at(q: tuple[float, float]) -> Polygon:
    region = unary_union(list(link_polygons(np.asarray(q, dtype=float), LIMITS)))
    assert isinstance(region, Polygon)
    return region


def declared_around(q: tuple[float, float]) -> bytes:
    """A declared envelope that honestly covers the body at `q`, with margin."""
    return envelope_wkb(body_at(q).buffer(DECL_MARGIN_M))


HOME_WKB = declared_around(Q_HOME)

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
    id_prefix: str = "fixture",
) -> Enforcer:
    return Enforcer(
        LIMITS,
        key=ENFORCEMENT_KEY,
        policy_key=policy_key,
        watchdog_period_s=watchdog_period_s,
        t_start=t_start,
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
        enforcer().offer(LooksLikeOne())  # type: ignore[arg-type]


# ==========================================================================
# The independently computed bound.
# ==========================================================================


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
    assert e.offer(tight) is None
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
        link_radius=0.05,
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
    assert e.offer(declaration(envelope=envelope_wkb(region))) is None
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
    assert e.offer(declaration(t_issued=0.5)) is None
    v = e.adjudicate(proprio(Q_HOME, 0.25))
    assert (v.outcome, v.fault) == ("VETO", "no_declaration")


def test_a_declaration_permits_the_action_it_covers() -> None:
    """The positive control for `no_declaration`."""
    e = enforcer()
    assert e.offer(declaration()) is None
    v = e.adjudicate(proprio(Q_HOME, 0.1))
    assert (v.outcome, v.fault, v.clamped_envelope) == ("PERMIT", None, None)
    assert v.declaration_id == "fixture-decl-00000"
    assert not e.is_passivated


def test_stale_declaration_is_a_veto() -> None:
    e = enforcer()
    e.offer(declaration(t_issued=0.0, horizon=0.5))
    assert e.adjudicate(proprio(Q_HOME, 0.5)).outcome == "PERMIT"  # boundary is covered
    v = e.adjudicate(proprio(Q_HOME, 0.51))
    assert (v.outcome, v.fault) == ("VETO", "stale_declaration")
    assert v.declaration_id == "fixture-decl-00000"
    assert e.is_passivated


def test_declaration_action_mismatch_clamps_to_the_declared_bound() -> None:
    e = enforcer()
    d = declaration()
    e.offer(d)
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
    v = e.offer(declaration(envelope=HUGE_WKB))
    assert v is not None
    assert (v.outcome, v.fault) == ("VETO", "envelope_overclaim")
    assert v.declaration_id == "fixture-decl-00000"
    assert e.open_declaration is None
    assert e.is_passivated
    assert f"{computed_bound(LIMITS):.4f}" in (e.reason(v.verdict_id) or "")


def test_an_enormous_declaration_does_not_widen_what_is_permitted() -> None:
    """NEGATIVE — the *computed* bound constrains the verdict, not the declared one.

    The action below sits comfortably inside the enormous declared envelope. If
    enforcement believed the declaration it would PERMIT; it computes its own
    bound instead, so nothing here is ever permitted.
    """
    huge = shapely.from_wkb(HUGE_WKB)
    assert huge.covers(body_at(Q_HOME)), "the action is inside the declared claim"

    e = enforcer()
    e.offer(declaration(envelope=HUGE_WKB))
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
    v = e.offer(d)
    assert v is not None
    assert (v.outcome, v.fault) == ("VETO", "out_of_vocabulary_action")
    assert e.is_passivated


def test_every_action_class_in_the_vocabulary_is_accepted() -> None:
    """The positive control for `out_of_vocabulary_action`."""
    for i, action_class in enumerate(ACTION_CLASSES):
        e = enforcer()
        assert e.offer(declaration(seq=i, action_class=action_class)) is None
        assert e.open_declaration is not None


def test_unattributed_when_the_mac_does_not_match() -> None:
    e = enforcer()
    v = e.offer(declaration(key=OTHER_KEYRING.key("policy")))
    assert v is not None
    assert (v.outcome, v.fault) == ("VETO", "unattributed")
    assert e.is_passivated


def test_unattributed_when_the_declaration_is_not_signed_at_all() -> None:
    e = enforcer()
    v = e.offer(declaration(signed=False))
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
    v = e.offer(declaration())
    assert v is not None
    assert (v.outcome, v.fault) == ("VETO", "unattributed")
    assert "no key" in (e.reason(v.verdict_id) or "")

    for t in (0.1, 0.2, 0.3):
        e.adjudicate(proprio(Q_HOME, t))
    assert "PERMIT" not in {rec.outcome for rec in e.verdicts}


def test_replay_and_reorder_are_vetoed() -> None:
    for bad_seq in (3, 2):  # reuse, then regression
        e = enforcer()
        assert e.offer(declaration(seq=3, t_issued=0.0)) is None
        v = e.offer(declaration(seq=bad_seq, t_issued=0.1))
        assert v is not None, f"seq={bad_seq} was accepted after seq=3"
        assert (v.outcome, v.fault) == ("VETO", "replay_or_reorder")
        assert e.is_passivated


def test_an_advancing_seq_is_accepted() -> None:
    """The positive control for `replay_or_reorder`. Gaps are not reordering."""
    e = enforcer()
    assert e.offer(declaration(seq=0, t_issued=0.0)) is None
    assert e.offer(declaration(seq=4, t_issued=0.1)) is None
    assert e.open_declaration is not None
    assert e.open_declaration.seq == 4


def test_watchdog_expiry_drives_to_a_safe_state() -> None:
    """The liveness check: the declaration channel has gone quiet."""
    e = enforcer(watchdog_period_s=0.25)
    e.offer(declaration(t_issued=0.0, horizon=10.0))
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
    e.offer(declaration(seq=0, t_issued=0.0, envelope=HUGE_WKB))  # refused, but heard
    e.acknowledge(t=0.05, reason="operator cleared the overclaim")
    assert e.offer(declaration(seq=1, t_issued=0.1)) is None
    v = e.adjudicate(proprio(Q_HOME, 0.3))
    assert v.outcome == "PERMIT", "the channel was heard from at t=0.1"


def test_escalation_failure_when_the_policy_replans_instead_of_escalating() -> None:
    """The condition `reg.enforce` defines: passivated, unacknowledged, no escalate."""
    e = enforcer()
    e.adjudicate(proprio(Q_HOME, 0.1))  # VETO no_declaration -> passivated
    assert e.is_passivated

    v = e.offer(declaration(seq=1, t_issued=0.2, action_class="reach"))
    assert v is not None
    assert (v.outcome, v.fault) == ("SAFE_STATE", "escalation_failure")
    assert e.is_passivated
    assert e.open_declaration is None


def test_an_escalate_declaration_is_not_an_escalation_failure() -> None:
    """The positive control — and it still does not resume anything."""
    e = enforcer()
    e.adjudicate(proprio(Q_HOME, 0.1))
    assert e.offer(declaration(seq=1, t_issued=0.2, action_class="escalate")) is None
    assert e.escalated
    assert e.is_passivated
    assert "escalation_failure" not in {v.fault for v in e.verdicts}
    assert e.adjudicate(proprio(Q_HOME, 0.3)).outcome == "SAFE_STATE"


# ==========================================================================
# Passivation and reintegration.
# ==========================================================================


def test_after_a_veto_every_action_is_a_safe_state_carrying_the_fault() -> None:
    e = enforcer()
    e.offer(declaration(t_issued=0.0, horizon=0.5))
    assert e.adjudicate(proprio(Q_HOME, 0.51)).fault == "stale_declaration"
    for t in (0.6, 0.7, 0.8):
        v = e.adjudicate(proprio(Q_HOME, t))
        assert (v.outcome, v.fault) == ("SAFE_STATE", "stale_declaration")
    assert e.passivation_fault == "stale_declaration"


def test_a_fresh_declaration_alone_does_not_resume() -> None:
    """NEGATIVE — reintegration is gated. This is the half people omit."""
    e = enforcer()
    e.offer(declaration(seq=0, t_issued=0.0, horizon=0.5))
    e.adjudicate(proprio(Q_HOME, 0.51))  # VETO stale -> passivated

    refusal = e.offer(declaration(seq=1, t_issued=0.6))
    assert refusal is not None, "a fresh declaration alone resumed the run"
    assert e.is_passivated
    assert e.open_declaration is None
    assert e.adjudicate(proprio(Q_HOME, 0.7)).outcome == "SAFE_STATE"


def test_an_acknowledgment_alone_does_not_resume() -> None:
    """The other half: the acknowledgment needs a fresh declaration behind it."""
    e = enforcer()
    e.offer(declaration(seq=0, t_issued=0.0, horizon=0.5))
    e.adjudicate(proprio(Q_HOME, 0.51))

    ack = e.acknowledge(t=0.6, reason="operator inspected the cell")
    assert ack.fault == "stale_declaration"
    assert e.is_passivated
    v = e.adjudicate(proprio(Q_HOME, 0.7))
    assert (v.outcome, v.fault) == ("SAFE_STATE", "stale_declaration")


def test_acknowledgment_then_a_fresh_declaration_resumes() -> None:
    e = enforcer()
    e.offer(declaration(seq=0, t_issued=0.0, horizon=0.5))
    passivating = e.adjudicate(proprio(Q_HOME, 0.51))

    ack = e.acknowledge(t=0.6, reason="operator inspected the cell")
    assert ack.verdict_id == passivating.verdict_id, (
        "the acknowledgment names the verdict it clears, so acknowledging one "
        "fault cannot clear a different one later"
    )
    assert e.offer(declaration(seq=1, t_issued=0.7)) is None
    assert not e.is_passivated
    assert e.adjudicate(proprio(Q_HOME, 0.8)).outcome == "PERMIT"


def test_a_new_passivation_invalidates_an_earlier_acknowledgment() -> None:
    """Acknowledging a stale declaration did not clear a forged one."""
    e = enforcer()
    e.offer(declaration(seq=0, t_issued=0.0, horizon=0.5))
    e.adjudicate(proprio(Q_HOME, 0.51))
    e.acknowledge(t=0.6, reason="operator inspected the cell")

    # A forged declaration arrives before the reintegrating one.
    forged = e.offer(declaration(seq=1, t_issued=0.7, key=OTHER_KEYRING.key("policy")))
    assert forged is not None and forged.fault == "unattributed"
    assert e.passivation_fault == "unattributed"

    resumed = e.offer(declaration(seq=2, t_issued=0.8))
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
    e.offer(declaration(seq=0, t_issued=0.0, horizon=0.5))
    e.adjudicate(proprio(Q_HOME, 0.1))
    e.adjudicate(proprio(Q_HOME, 0.51))
    ack = e.acknowledge(t=0.6, reason="cleared")
    e.offer(declaration(seq=1, t_issued=0.7))
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
    e.offer(declaration(seq=17, t_issued=0.0))
    verdicts = e.adjudicate_all(proprio(Q_HOME, t) for t in (0.1, 0.2, 0.3))
    assert [v.seq for v in verdicts] == [0, 1, 2]
    assert {v.declaration_id for v in verdicts} == {"fixture-decl-00017"}


def test_ids_are_deterministic_and_prefixed() -> None:
    e = enforcer(id_prefix="contact")
    e.offer(declaration())
    v = e.adjudicate(proprio(Q_HOME, 0.1))
    assert v.verdict_id == "contact-verdict-00000"


def test_an_action_that_runs_backwards_is_a_caller_error_not_a_fault() -> None:
    """Absorbing it would silently reset the watchdog."""
    e = enforcer()
    e.offer(declaration())
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
            id_prefix="x",
        )
    with pytest.raises(TypeError, match="t_start"):
        Enforcer(  # type: ignore[call-arg]
            LIMITS,
            key=ENFORCEMENT_KEY,
            policy_key=POLICY_KEY,
            watchdog_period_s=1.0,
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
            id_prefix="x",
        )
    with pytest.raises(EnforcementError, match="policy Key or None"):
        Enforcer(
            LIMITS,
            key=ENFORCEMENT_KEY,
            policy_key=ENFORCEMENT_KEY,
            watchdog_period_s=1.0,
            t_start=0.0,
            id_prefix="x",
        )


# ==========================================================================
# The real fixture: a verdict is per commanded action, not per declaration.
# ==========================================================================

#: The policy's parameters for the fixture run, stated because
#: `emit_declarations` refuses to invent them.
FIXTURE_REPLAN_S = 0.5
FIXTURE_HORIZON_S = 0.5
FIXTURE_WATCHDOG_S = 1.0


def run_declared_violation(seed: int) -> tuple[Enforcer, tuple[Declaration, ...], list[Verdict]]:
    """Adjudicate the `declared_violation` fixture, declarations and all."""
    scenario = SCENARIOS["declared_violation"]
    states = [frame.proprio() for frame in scenario.states(seed)]
    declarations = emit_declarations(
        states,
        LIMITS,
        key=POLICY_KEY,
        replan_interval_s=FIXTURE_REPLAN_S,
        horizon_s=FIXTURE_HORIZON_S,
        declared_q_bounds=scenario.declared_q_bounds,
        id_prefix=scenario.name,
    )
    pending = {round(d.t_issued, 9): d for d in declarations}
    e = Enforcer(
        LIMITS,
        key=ENFORCEMENT_KEY,
        policy_key=POLICY_KEY,
        watchdog_period_s=FIXTURE_WATCHDOG_S,
        t_start=0.0,
        id_prefix=scenario.name,
    )
    verdicts: list[Verdict] = []
    for state in states:
        due = pending.pop(round(state.t, 9), None)
        if due is not None:
            assert e.offer(due) is None, "the fixture's own declarations are honest"
        verdicts.append(e.adjudicate(state))
    return e, declarations, verdicts


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


@pytest.mark.parametrize(
    "name", [n for n, s in SCENARIOS.items() if s.declared_q_bounds is None]
)
def test_a_compliant_fixture_is_permitted_throughout(name: str) -> None:
    """The positive control for the whole taxonomy, on every compliant fixture.

    These five declare exactly the region their own configurations sweep
    (`declared_q_bounds=None`), which is a true statement about themselves.
    Nothing in the taxonomy should fire on any of them — this is the test that
    would catch a bound that cries wolf, and if it goes red the bound is wrong,
    not the fixture and not the tolerance.
    """
    scenario = SCENARIOS[name]
    assert scenario.declared_q_bounds is None
    states = [frame.proprio() for frame in scenario.states(0)]
    declarations = emit_declarations(
        states,
        LIMITS,
        key=POLICY_KEY,
        replan_interval_s=FIXTURE_REPLAN_S,
        horizon_s=FIXTURE_HORIZON_S,
        declared_q_bounds=None,
        id_prefix=scenario.name,
    )
    pending = {round(d.t_issued, 9): d for d in declarations}
    e = Enforcer(
        LIMITS,
        key=ENFORCEMENT_KEY,
        policy_key=POLICY_KEY,
        watchdog_period_s=FIXTURE_WATCHDOG_S,
        t_start=0.0,
        id_prefix=scenario.name,
    )
    for state in states:
        due = pending.pop(round(state.t, 9), None)
        if due is not None:
            assert e.offer(due) is None
        v = e.adjudicate(state)
        assert v.outcome == "PERMIT", (
            f"{scenario.name} t={state.t}: an honest declaration produced "
            f"{v.outcome}/{v.fault}. Do not widen a tolerance to fix this — the "
            "bound is wrong."
        )
    assert not e.is_passivated
