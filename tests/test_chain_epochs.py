"""Per-epoch key evolution and the v2 chain (issue #315).

The three acceptance criteria, as tests:

(a) A compromised CURRENT epoch key cannot forge a PAST record that still
    verifies — the forward-security claim itself.
(b) A v1 (statically signed) artifact verifies unchanged under the new code.
(c) Predecessor erasure is effective — no epoch key but the current one is
    recoverable from the signer or the artifact.

Plus the negatives AGENTS.md demands for every new check: each of the four
new failure kinds is fed the condition it guards against.
"""
from __future__ import annotations

import hashlib
import secrets
import shutil
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest
import shapely.wkb
from shapely.geometry import box

import reg.graph as graph
from reg import store
from reg.chain import (
    CHAIN_FORMAT_V1,
    CHAIN_FORMAT_V2,
    EPOCH_RECORDS,
    GENESIS_HASH,
    META_CHAIN_FORMAT,
    UNSIGNED_MAC,
    ChainError,
    ChainState,
    EpochSigner,
    Key,
    Keyring,
    TamperSpec,
    chain_hash,
    checkpoint_bytes,
    epoch_key_material,
    key_commitment,
    merkle_root,
    sign,
    tamper,
    verify,
    verify_chain,
)
from reg.declare import Declaration, emit_declarations, sign_declaration
from reg.enforce import Acknowledgment, Enforcer, Verdict
from reg.graph import AttestationRecords
from reg.identity import DPIA_NONE, Disclosures, RunIdentity
from reg.scenarios import SCENARIOS
from reg.sim import provenance
from reg.stream import write_frames

#: Epochs small enough that the fixture spans several, large enough that the
#: epoch structure is exercised rather than degenerate. Production uses
#: `EPOCH_RECORDS` (1024); the count is a parameter of the signer, not of the
#: format, so a small one here tests the same machinery.
TEST_EPOCH_RECORDS = 4

KEYRING = Keyring.from_material(
    policy=bytes(range(32)), enforcement=bytes(range(100, 132))
)
POLICY_KEY = KEYRING.key("policy")
ENFORCEMENT_KEY = KEYRING.key("enforcement")

REPLAN_S = 0.5
HORIZON_S = 0.5
WATCHDOG_S = 1.0
SUBSTEP_DT = 0.05

TEST_IDENTITY = RunIdentity.declare(
    run_start="2026-08-21T09:00:00Z",
    unit_id="unit-test-arm-1",
    operator_id="op-test",
)
TEST_DISCLOSURES = Disclosures.declare(
    worker_notice="not-given",
    dpia_reference=DPIA_NONE,
    operator_id_kind="pseudonym",
)
_FAST = {"horizon": 0.1, "n_samples": 4, "seed": 0, "substep_dt": 0.05}


def _scenario():
    return replace(SCENARIOS["declared_violation"], dt=0.1)


def _v2_records(scn, states, epoch_records, keyring=KEYRING):
    """The record stream, signed under per-epoch keys.

    The producers' own wiring — `emit_declarations` and `Enforcer` — with
    small-epoch signers, so the fixture spans several epochs per chain. The
    signers are closed at the end, as `graph.attestation_from_stream` does.
    """
    policy_key = keyring.key("policy")
    enforcement_key = keyring.key("enforcement")
    policy_signer = EpochSigner(policy_key, epoch_records=epoch_records)
    enforcement_signer = EpochSigner(enforcement_key, epoch_records=epoch_records)
    speaking = [s for s in states if not scn.silent_at(s.t)]
    declarations = emit_declarations(
        speaking,
        scn.world.limits,
        signer=policy_signer,
        replan_interval_s=REPLAN_S,
        horizon_s=HORIZON_S,
        declared_q_bounds=scn.declared_q_bounds,
        declared_margin_m=scn.declared_margin_m,
        id_prefix=scn.name,
    )
    pending = {round(d.t_issued, 9): d for d in declarations}
    enforcer = Enforcer(
        scn.world.limits,
        signer=enforcement_signer,
        policy_key=policy_key,
        watchdog_period_s=WATCHDOG_S,
        t_start=float(states[0].t),
        substep_dt=SUBSTEP_DT,
        id_prefix=scn.name,
        epoch_records=epoch_records,
    )
    verdicts: list = []
    acknowledgments: list = []
    for state in states:
        due = pending.pop(round(state.t, 9), None)
        if due is not None:
            refusal = enforcer.offer(due, state)
            if refusal is not None:
                verdicts.append(refusal)
        verdicts.append(enforcer.adjudicate(state))
    assert not pending, "a declaration was never offered to the enforcer"
    policy_signer.close()
    enforcement_signer.close()
    records = AttestationRecords(
        declarations=tuple(declarations),
        verdicts=tuple(verdicts),
        acknowledgments=tuple(acknowledgments),
        epoch_heads=tuple(policy_signer.epochs) + tuple(enforcement_signer.epochs),
        epoch_records=epoch_records,
    )
    return records, policy_signer, enforcement_signer


def _build(tmp_path: Path, name: str, scn, records) -> Path:
    csv = write_frames(
        scn.states(0), tmp_path / "dv.csv", comments=provenance(scn, 0)
    )
    out = tmp_path / name
    graph.build(
        csv,
        out,
        scn.world.limits,
        identity=TEST_IDENTITY,
        disclosures=TEST_DISCLOSURES,
        human_radius=scn.world.human_radius,
        records=records,
        **_FAST,
    )
    return out


@pytest.fixture(scope="module")
def v2(tmp_path_factory):
    """One v2 artifact spanning several epochs per chain, plus its signers."""
    tmp = tmp_path_factory.mktemp("v2")
    scn = _scenario()
    states = [frame.proprio() for frame in scn.states(0)]
    records, policy_signer, enforcement_signer = _v2_records(
        scn, states, TEST_EPOCH_RECORDS
    )
    assert len(records.declarations) > 2 * TEST_EPOCH_RECORDS, (
        "the fixture must span several policy epochs"
    )
    artifact = _build(tmp, "v2.sqlite", scn, records)
    return artifact, records, policy_signer, enforcement_signer


def _failures(report, kind, state=ChainState.BROKEN):
    return [
        f for f in report.failures if f.kind == kind and f.state is state
    ]


# --------------------------------------------------------------------------
# The baseline: a v2 artifact verifies clean.
# --------------------------------------------------------------------------


def test_v2_artifact_verifies_clean(v2) -> None:
    artifact, records, _, _ = v2
    report = verify_chain(store.connect(artifact), KEYRING)
    assert report.state is ChainState.VERIFIED, (
        f"a freshly built v2 artifact must verify: {report.failures}"
    )


def test_v2_artifact_states_its_format_and_heads(v2) -> None:
    artifact, records, _, _ = v2
    conn = store.connect(artifact)
    assert store.get_meta(conn, META_CHAIN_FORMAT) == CHAIN_FORMAT_V2
    rows = conn.execute(
        "SELECT chain, epoch FROM epoch_heads ORDER BY chain, epoch"
    ).fetchall()
    by_chain: dict[str, list[int]] = {}
    for row in rows:
        by_chain.setdefault(row["chain"], []).append(int(row["epoch"]))
    assert set(by_chain) == {"policy", "enforcement"}
    for chain, epochs in by_chain.items():
        assert epochs == list(range(len(epochs))), (
            f"{chain}: epochs must be contiguous from 0, got {epochs}"
        )
    # Every chain's epochs cover every chain's records.
    assert by_chain["policy"] == list(
        range((len(records.declarations) + TEST_EPOCH_RECORDS - 1) // TEST_EPOCH_RECORDS)
    )
    n_enforcement = len(records.verdicts) + len(records.acknowledgments)
    assert by_chain["enforcement"] == list(
        range((n_enforcement + TEST_EPOCH_RECORDS - 1) // TEST_EPOCH_RECORDS)
    )


# --------------------------------------------------------------------------
# (a) Forward security: the current key forges nothing past.
# --------------------------------------------------------------------------


def test_a_compromised_current_epoch_key_cannot_forge_a_past_record(v2, tmp_path) -> None:
    """NEGATIVE. The forward-security claim itself.

    The attacker takes the machine after the build and learns the signer's
    current key — every epoch key *after* the records. They rewrite an
    epoch-0 declaration and re-MAC it under the only key they have. The
    artifact must not verify: the MAC is under the wrong epoch's key, and
    the epoch's Merkle root still commits to the original bytes.
    """
    artifact, _, policy_signer, _ = v2
    target = store.read_declarations(store.connect(artifact))[3]
    assert int(target.seq) < TEST_EPOCH_RECORDS  # epoch 0, the deep past

    attacker_key = Key(
        role="policy", material=policy_signer.current_key().material
    )
    assert attacker_key.material != POLICY_KEY.material

    tampered = replace(target, horizon=99.5)
    forged_mac = sign(tampered, attacker_key)

    work = tmp_path / "forged.sqlite"
    shutil.copy(artifact, work)
    conn = store.connect(work)
    conn.execute(
        "UPDATE declaration SET horizon = ?, mac = ? "
        "WHERE declaration_key = (SELECT node_key FROM node WHERE node_id = ?)",
        (99.5, forged_mac, target.declaration_id),
    )
    conn.commit()

    report = verify_chain(store.connect(work), KEYRING)
    assert report.state is ChainState.BROKEN
    assert _failures(report, "mac"), (
        "the forged MAC must fail under the epoch-0 key: "
        f"{report.failures}"
    )
    assert _failures(report, "epoch-merkle"), (
        "the epoch's Merkle root must still commit to the original bytes"
    )


def test_resigning_under_the_correct_epoch_key_still_breaks_the_checkpoint(
    v2, tmp_path
) -> None:
    """The operator's tool, with the real keyring, on a v2 artifact.

    `tamper --resign` re-signs under the record's *epoch* key (the point of
    the `tamper` change in this issue): the MAC verifies again, and the
    tamper is still caught — by the epoch checkpoint, which committed to the
    original bytes. Hiding the edit from the MAC does not hide it from the
    epoch.
    """
    artifact, _, _, _ = v2
    work = tmp_path / "resigned.sqlite"
    # Position 10: epoch 2 with TEST_EPOCH_RECORDS=4 — exercises the key
    # derivation, not just the epoch-0 key that equals the static one.
    tamper(
        artifact,
        work,
        TamperSpec(chain="policy", selector="#10", field="horizon", value="9.5"),
        keyring=KEYRING,
        resign=True,
    )

    report = verify_chain(store.connect(work), KEYRING)
    assert report.state is ChainState.BROKEN
    assert not _failures(report, "mac"), (
        "re-signing under the correct epoch key must make the MAC verify: "
        f"{report.failures}"
    )
    assert _failures(report, "epoch-merkle"), (
        "but the checkpoint committed to the original bytes"
    )


# --------------------------------------------------------------------------
# (b) v1 artifacts verify unchanged.
# --------------------------------------------------------------------------


def test_a_v1_artifact_verifies_unchanged(v2, tmp_path) -> None:
    """Epoch 0's key IS the static key, so epoch-0 records are byte-identical
    to what the pre-#315 code signed.

    Take the fixture's first epoch of each chain — every remaining MAC is
    under the epoch-0 (static) key — build it with no epoch heads, and the
    old walk must verify it exactly as it did before this issue existed.
    Truncating the tail keeps every `prev_hash` link intact, and `build`
    writes the FOLLOWS edges for exactly the stream it was handed.
    """
    _, records, _, _ = v2
    first_declarations = records.declarations[:TEST_EPOCH_RECORDS]
    first_enforcement = records.enforcement_chain[:TEST_EPOCH_RECORDS]
    v1_records = AttestationRecords(
        declarations=first_declarations,
        verdicts=tuple(r for r in first_enforcement if isinstance(r, Verdict)),
        acknowledgments=tuple(
            r for r in first_enforcement if isinstance(r, Acknowledgment)
        ),
        # epoch_heads defaults to () → chain-sha256-v1.
    )
    scn = _scenario()
    work = _build(tmp_path, "v1.sqlite", scn, v1_records)
    conn = store.connect(work)
    assert store.get_meta(conn, META_CHAIN_FORMAT) == CHAIN_FORMAT_V1
    assert (
        conn.execute("SELECT COUNT(*) AS n FROM epoch_heads").fetchone()["n"] == 0
    )
    report = verify_chain(conn, KEYRING)
    assert report.state is ChainState.VERIFIED, (
        f"a v1-format artifact must verify under the old walk: {report.failures}"
    )


# --------------------------------------------------------------------------
# (c) Erasure: no predecessor key survives in the signer or the artifact.
# --------------------------------------------------------------------------


def test_erased_predecessors_are_not_recoverable(tmp_path) -> None:
    """With a random keyring (so the byte scan is meaningful), build a
    multi-epoch v2 artifact and assert no epoch key but the signers' current
    one appears in the artifact bytes — and the signers no longer hold the
    epoch-0 keys either.
    """
    keyring = Keyring.from_material(
        policy=secrets.token_bytes(32), enforcement=secrets.token_bytes(32)
    )
    tmp = tmp_path / "erasure"
    tmp.mkdir()
    scn = _scenario()
    states = [frame.proprio() for frame in scn.states(0)]
    records, policy_signer, enforcement_signer = _v2_records(
        scn, states, TEST_EPOCH_RECORDS, keyring=keyring
    )
    assert len(policy_signer.epochs) >= 2, "need several epochs for this test"
    artifact = _build(tmp, "erasure.sqlite", scn, records)

    raw = artifact.read_bytes()
    for role in ("policy", "enforcement"):
        seed = keyring.key(role).material
        for epoch in range(3):
            key = epoch_key_material(seed, epoch)
            assert key not in raw, (
                f"epoch-{epoch} {role} key material is recoverable from the artifact"
            )

    # And the signers themselves no longer hold the epoch-0 keys: after
    # close they hold only the next epoch's key.
    assert policy_signer.current_key().material != keyring.key("policy").material
    assert (
        enforcement_signer.current_key().material
        != keyring.key("enforcement").material
    )
    assert policy_signer.current_key().material == epoch_key_material(
        keyring.key("policy").material, len(policy_signer.epochs)
    )


def test_key_commitment_is_not_the_next_epoch_key() -> None:
    """The domain separation `reg/chain.py` calls load-bearing: plain
    SHA-256(k) would BE k_{i+1} and publish it inside the checkpoint."""
    key = secrets.token_bytes(32)
    assert key_commitment(key) != epoch_key_material(key, 1)
    assert key_commitment(key) == key_commitment(key)  # deterministic


# --------------------------------------------------------------------------
# Negatives for the four new failure kinds.
# --------------------------------------------------------------------------


def test_epoch_census_catches_a_missing_epoch(v2, tmp_path) -> None:
    work = tmp_path / "census.sqlite"
    shutil.copy(v2[0], work)
    conn = store.connect(work)
    conn.execute(
        "DELETE FROM epoch_heads WHERE chain = 'policy' AND epoch = 0"
    )
    conn.commit()
    report = verify_chain(store.connect(work), KEYRING)
    assert report.state is ChainState.BROKEN
    assert _failures(report, "epoch-census")


def test_epoch_checkpoint_catches_a_forged_checkpoint(v2, tmp_path) -> None:
    work = tmp_path / "checkpoint.sqlite"
    shutil.copy(v2[0], work)
    conn = store.connect(work)
    row = conn.execute(
        "SELECT checkpoint_sig FROM epoch_heads WHERE chain = 'policy' AND epoch = 0"
    ).fetchone()
    sig = bytearray(bytes(row["checkpoint_sig"]))
    sig[0] ^= 0xFF
    conn.execute(
        "UPDATE epoch_heads SET checkpoint_sig = ? WHERE chain = 'policy' AND epoch = 0",
        (bytes(sig),),
    )
    conn.commit()
    report = verify_chain(store.connect(work), KEYRING)
    assert report.state is ChainState.BROKEN
    assert _failures(report, "epoch-checkpoint")


def test_v2_without_a_stated_epoch_size_is_could_not_evaluate(
    v2, tmp_path
) -> None:
    """A v2 artifact that does not state its epoch size: the verifier cannot
    know which key signed which record, so every epoch-dependent check is
    could-not-evaluate rather than guessed."""
    work = tmp_path / "nosize.sqlite"
    shutil.copy(v2[0], work)
    conn = store.connect(work)
    conn.execute("DELETE FROM meta WHERE key = 'epoch_records'")
    conn.commit()
    report = verify_chain(store.connect(work), KEYRING)
    assert report.state is ChainState.COULD_NOT_EVALUATE
    assert _failures(report, "epoch-census", ChainState.COULD_NOT_EVALUATE)


def test_no_key_leaves_the_checkpoint_unevaluated_but_checks_the_rest(
    v2,
) -> None:
    """Without a key the Merkle roots and the head chain still check — they
    need no secrets. The checkpoint signature is not checked without a key,
    and no per-epoch failure is reported for that: the v1 `no-key` failure
    already covers every key-dependent check going unchecked.
    """
    artifact = v2[0]
    report = verify_chain(store.connect(artifact), None)
    assert report.state is ChainState.COULD_NOT_EVALUATE
    kinds = {(f.kind, f.state) for f in report.failures}
    assert ("no-key", ChainState.COULD_NOT_EVALUATE) in kinds
    assert not any(k == "epoch-checkpoint" for k, _ in kinds)
    assert not _failures(report, "epoch-merkle", ChainState.BROKEN)
    assert not _failures(report, "epoch-head", ChainState.BROKEN)


# --------------------------------------------------------------------------
# Unit tests for the epoch machinery.
# --------------------------------------------------------------------------


def test_epoch_key_evolution_is_plain_iterated_sha256() -> None:
    """The design doc's k_{i+1} = SHA-256(k_i), literally."""
    seed = secrets.token_bytes(32)
    assert epoch_key_material(seed, 0) == seed
    assert epoch_key_material(seed, 1) == hashlib.sha256(seed).digest()
    assert epoch_key_material(seed, 2) == hashlib.sha256(
        hashlib.sha256(seed).digest()
    ).digest()


def test_epoch_key_material_refuses_garbage() -> None:
    with pytest.raises(ChainError):
        epoch_key_material(b"too short", 0)
    with pytest.raises(ChainError):
        epoch_key_material(secrets.token_bytes(32), -1)


def test_merkle_root_is_deterministic_and_pads_odd_levels() -> None:
    leaves = [hashlib.sha256(bytes([i])).digest() for i in range(5)]
    assert merkle_root(leaves) == merkle_root(leaves)
    assert merkle_root(leaves) != merkle_root(leaves[:-1])
    with pytest.raises(ChainError):
        merkle_root([])


def test_checkpoint_bytes_are_deterministic_and_role_epoch_bound() -> None:
    root = secrets.token_bytes(32)
    commitment = secrets.token_bytes(32)
    a = checkpoint_bytes("policy", 3, root, commitment)
    assert a == checkpoint_bytes("policy", 3, root, commitment)
    assert a != checkpoint_bytes("enforcement", 3, root, commitment)
    assert a != checkpoint_bytes("policy", 4, root, commitment)


def test_signer_closes_epochs_at_the_boundary() -> None:
    """Five records at two per epoch: epochs [0, 1, 2], the last partial,
    sealed by `close()`. A second `close()` seals nothing."""
    wkb = shapely.wkb.dumps(box(0, 0, 1, 1))
    signer = EpochSigner(POLICY_KEY, epoch_records=2)
    prev = GENESIS_HASH
    for i in range(5):
        unsigned = Declaration(
            declaration_id=f"epoch-test-decl-{i}",
            seq=i,
            t_issued=float(i),
            horizon=1.0,
            action_class="reach",
            declared_envelope=wkb,
            prev_hash=prev,
            mac=UNSIGNED_MAC,
        )
        signed = sign_declaration(unsigned, signer.current_key())
        signer.note_signed(signed)
        prev = chain_hash(signed, prev)
    assert [e.epoch for e in signer.epochs] == [0, 1]
    assert signer.epoch == 2
    last = signer.close()
    assert last is not None and last.epoch == 2
    assert [e.epoch for e in signer.epochs] == [0, 1, 2]
    assert signer.close() is None
    assert [e.epoch for e in signer.epochs] == [0, 1, 2]


def test_signer_refuses_a_non_key() -> None:
    with pytest.raises(ChainError):
        EpochSigner("not-a-key")  # type: ignore[arg-type]
