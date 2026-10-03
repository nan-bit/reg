"""The docs/adopting.md worked example, running end to end.

A non-robot domain on the real domain-general machinery: an agent with a
tool-call and token budget. The policy declares the budget as a rectangle in
(calls, kilotokens) space; enforcement checks each action's cumulative usage
with the real containment check; verdicts are real records, chained under real
keys into a real store; a cold read over the record tables names the action
that broke the budget.

What this reuses and what it does not (docs/adopting.md states the boundary):
reused — reg.declare.Declaration, reg.enforce.Verdict and sign_verdict,
reg.enforce.declared_bound and escape_region, reg.chain keyring / sign /
chain_hash, reg.store's record tables. Not reused — reg.enforce.Enforcer,
which derives the observed region from proprioception; the small
``_adjudicate_usage`` check below plays its role for this domain. The record
vocabularies (ACTION_CLASSES, the nine faults) are the robot case's, reused
here as labels — a real adoption would define its own.
"""

from __future__ import annotations

from pathlib import Path

from shapely.geometry import box

from reg import chain, declare, enforce, store


#: The declared bound: at most 8 tool calls and 40 kilotokens in the run.
#: A 2D region, like every declared envelope — the domain's own space,
#: not a robot's workspace.
BUDGET_CALLS = 8.0
BUDGET_KTOKENS = 40.0

#: Scripted actions: (tool calls, kilotokens) each one spends. Cumulative use
#: after the fourth action is (9, 47) — outside the declared rectangle.
ACTIONS: tuple[tuple[float, float], ...] = (
    (2.0, 5.0),
    (3.0, 12.0),
    (2.0, 10.0),
    (2.0, 20.0),
)


def _adjudicate_usage(
    declaration: declare.Declaration,
    cumulative: tuple[float, float],
    prev_hash: str,
    seq: int,
) -> enforce.Verdict:
    """The toy's enforcement layer: the check that plays Enforcer's role.

    The region the agent has consumed so far is the rectangle from the origin
    to its cumulative usage; the real ``reg.enforce.escape_region`` reports
    the part of it lying outside the declared bound. Empty means the action
    stayed inside — PERMIT. Anything else is the declaration/action mismatch
    the robot taxonomy already names, with the declared bound as the bound
    actually applied.
    """
    bound = enforce.declared_bound(declaration)
    used = box(0.0, 0.0, cumulative[0], cumulative[1])
    escape = enforce.escape_region(used, bound)
    if escape.is_empty:
        outcome, fault, clamped = "PERMIT", None, None
    else:
        outcome, fault = "CLAMP", "declaration_action_mismatch"
        clamped = declaration.declared_envelope
    return enforce.Verdict(
        verdict_id=f"budget-verdict-{seq}",
        declaration_id=declaration.declaration_id,
        seq=seq,
        t=float(seq),
        outcome=outcome,
        fault=fault,
        clamped_envelope=clamped,
        prev_hash=prev_hash,
        mac=chain.UNSIGNED_MAC,
    )


def _run_budget_audit(path: Path) -> list:
    """Declaration → per-action verdicts → chained records in a store."""
    keyring = chain.generate_keyring()
    budget = box(0.0, 0.0, BUDGET_CALLS, BUDGET_KTOKENS)
    declaration = declare.sign_declaration(
        declare.Declaration(
            declaration_id="budget-decl-0",
            seq=0,
            t_issued=0.0,
            horizon=3600.0,
            action_class="reach",
            declared_envelope=declare.envelope_wkb(budget),
            prev_hash=chain.GENESIS_HASH,
            mac=chain.UNSIGNED_MAC,
        ),
        keyring.key("policy"),
    )
    conn = store.create(path, record_tables=True)
    store.insert_declaration(conn, declaration)
    prev_hash = chain.chain_hash(declaration, chain.GENESIS_HASH)
    calls, ktokens = 0.0, 0.0
    for seq, (dcalls, dktokens) in enumerate(ACTIONS):
        calls += dcalls
        ktokens += dktokens
        verdict = enforce.sign_verdict(
            _adjudicate_usage(declaration, (calls, ktokens), prev_hash, seq),
            keyring.key("enforcement"),
        )
        store.insert_verdict(conn, verdict)
        prev_hash = chain.chain_hash(verdict, prev_hash)
    conn.commit()
    conn.close()
    return keyring


def test_budget_audit_runs_end_to_end_and_names_the_violating_action(
    tmp_path: Path,
) -> None:
    """The worked example: declare, adjudicate, chain, then a cold read."""
    keyring = _run_budget_audit(tmp_path / "budget.sqlite")

    # Cold read: a fresh connection, no service running — the whole point.
    conn = store.connect(tmp_path / "budget.sqlite")
    declarations = store.read_declarations(conn)
    verdicts = store.read_verdicts(conn)
    conn.close()

    assert [d.declaration_id for d in declarations] == ["budget-decl-0"]
    assert [v.outcome for v in verdicts] == ["PERMIT", "PERMIT", "PERMIT", "CLAMP"]
    assert [v.fault for v in verdicts] == [
        None,
        None,
        None,
        "declaration_action_mismatch",
    ]

    # Every record verifies under the key of the side that signed it.
    assert declare.verify_declaration(
        declarations[0], keyring.key("policy")
    ).state == chain.MacState.VALID
    for verdict in verdicts:
        assert enforce.verify_verdict(
            verdict, keyring.key("enforcement")
        ).state == chain.MacState.VALID

    # The chain walks without a break, recomputed from the cold records.
    prev_hash = chain.GENESIS_HASH
    for record in [*declarations, *verdicts]:
        assert record.prev_hash == prev_hash
        prev_hash = chain.chain_hash(record, prev_hash)

    # The money question, answered from the store alone: which action broke
    # the declared budget?
    assert [v.verdict_id for v in verdicts if v.outcome != "PERMIT"] == [
        "budget-verdict-3"
    ]
