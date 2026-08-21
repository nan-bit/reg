"""`reg.commit` — the external commitment to the two chain heads.

Issue #83, the second half. `reg.chain` proves the records were not edited under
the keys that signed them; it cannot see a history re-issued offline by their
author, and the author is the party a regulator distrusts most. These tests are
about the two things that change that, and about the two things that must never
be confused with it:

* **A commitment that does not match the artifact fails**, and it fails without
  the witness key — the recorded heads are compared against the ones this
  artifact's own records produce, so anyone holding the file can see a re-issued
  chain.
* **An absent commitment never reads as a present one.** `COMMITMENT: NONE`,
  a missing key, an unknown scheme and a missing witness key are four different
  could-not-evaluates, and not one of them is VALID.

Both directions have a negative. A commitment check that has only ever been run
against a good artifact is the check-that-cannot-fail this repository is built
against.
"""

from __future__ import annotations

import os
import sqlite3
import stat
from dataclasses import replace
from pathlib import Path

import pytest

from reg import chain, commit, graph, store
from reg.chain import GENESIS_HASH, generate_keyring, write_keyring
from reg.commit import (
    COMMITMENT_NONE,
    META_COMMITMENT,
    META_COMMITMENT_DECLARATION_HEAD,
    META_COMMITMENT_SIGNATURE,
    META_COMMITMENT_STATEMENT,
    META_COMMITMENT_VERDICT_HEAD,
    META_COMMITMENT_WITNESS,
    WITNESS_KEY_BYTES,
    WITNESS_SCHEME,
    ChainHeads,
    Commitment,
    CommitmentError,
    CommitmentState,
    Witness,
    WitnessCommitter,
    chain_heads,
    check_witness_is_independent,
    commitment_bytes,
    generate_witness,
    load_witness,
    verify_commitment,
    write_witness,
)
from reg.identity import RunIdentity
from reg.scenarios import SCENARIOS
from reg.sim import provenance
from reg.stream import write_frames

#: The same coarse fixture `tests/test_chain.py` walks: `declared_violation` at
#: a tenth of its frame rate. The run is not what is under test here.
FIXTURE_DT = 0.1
FIXTURE_REPLAN_S = 0.5
FIXTURE_HORIZON_S = 0.5
FIXTURE_WATCHDOG_S = 1.0
FIXTURE_SEED = 0

_FAST = {"horizon": 0.1, "n_samples": 4, "seed": 0, "substep_dt": 0.05}

TEST_IDENTITY = RunIdentity.declare(
    run_start="2026-08-21T09:00:00Z",
    unit_id="unit-test-arm-1",
    operator_id="op-test",
)

WITNESS_ID = "site-safety-officer"


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


def _stream(tmp_path: Path):
    scn = replace(SCENARIOS["declared_violation"], dt=FIXTURE_DT)
    csv = write_frames(
        scn.states(FIXTURE_SEED),
        tmp_path / "dv.csv",
        comments=provenance(scn, FIXTURE_SEED),
    )
    return csv, scn


def _records(csv, scn, tmp_path: Path):
    keyring_path = tmp_path / "keyring.json"
    if not keyring_path.exists():
        write_keyring(generate_keyring(), keyring_path)
    return graph.attestation_from_stream(
        csv,
        scn,
        keyring_path=keyring_path,
        replan_interval_s=FIXTURE_REPLAN_S,
        declaration_horizon_s=FIXTURE_HORIZON_S,
        watchdog_period_s=FIXTURE_WATCHDOG_S,
    )


def _build(tmp_path: Path, name: str, *, witness: Witness | None, records=True) -> Path:
    csv, scn = _stream(tmp_path)
    out = tmp_path / name
    graph.build(
        csv,
        out,
        scn.world.limits,
        identity=TEST_IDENTITY,
        human_radius=scn.world.human_radius,
        records=_records(csv, scn, tmp_path) if records else None,
        commitment=None if witness is None else WitnessCommitter(witness),
        **_FAST,
    )
    return out


@pytest.fixture(scope="module")
def witness() -> Witness:
    return generate_witness(WITNESS_ID)


@pytest.fixture(scope="module")
def committed(tmp_path_factory, witness: Witness) -> Path:
    """One artifact whose heads a witness signed at close."""
    return _build(tmp_path_factory.mktemp("committed"), "dv.sqlite", witness=witness)


@pytest.fixture(scope="module")
def uncommitted(tmp_path_factory) -> Path:
    """The same build with no supplier. It must *say* so, not merely omit it."""
    return _build(tmp_path_factory.mktemp("uncommitted"), "dv.sqlite", witness=None)


def _meta(path: Path, key: str) -> str | None:
    conn = store.connect(path)
    try:
        return store.get_meta(conn, key)
    finally:
        conn.close()


def _check(path: Path, witness: Witness | None):
    conn = store.connect(path)
    try:
        return verify_commitment(conn, witness)
    finally:
        conn.close()


def _set_meta(path: Path, key: str, value: str) -> None:
    """Rewrite one `meta` value in place. Only ever used on a copy."""
    conn = sqlite3.connect(path)
    try:
        conn.execute("UPDATE meta SET value = ? WHERE key = ?", (value, key))
        conn.commit()
    finally:
        conn.close()


# --------------------------------------------------------------------------
# The heads themselves
# --------------------------------------------------------------------------


def test_the_heads_are_the_fold_of_the_chain(committed: Path) -> None:
    """`chain_heads` is `reg.chain`'s own walk, not a second implementation."""
    conn = store.connect(committed)
    try:
        heads = chain_heads(conn)
        for records, expected in (
            (store.read_declarations(conn), heads.declaration_head),
            (store.read_verdicts(conn), heads.verdict_head),
        ):
            assert records, "precondition: this fixture holds both chains"
            head = GENESIS_HASH
            for record in records:
                head = chain.chain_hash(record, record.prev_hash)
            assert head == expected
    finally:
        conn.close()


def test_an_empty_chain_has_the_genesis_hash_as_its_head(tmp_path: Path) -> None:
    """A definition, not a fallback: committing to "this chain was empty" is a
    true statement, and it leaves an empty chain constrained rather than free."""
    csv, scn = _stream(tmp_path)
    out = tmp_path / "empty.sqlite"
    graph.build(
        csv,
        out,
        scn.world.limits,
        identity=TEST_IDENTITY,
        human_radius=scn.world.human_radius,
        records=graph.AttestationRecords(declarations=(), verdicts=()),
        **_FAST,
    )
    conn = store.connect(out)
    try:
        assert chain_heads(conn) == ChainHeads(
            declaration_head=GENESIS_HASH, verdict_head=GENESIS_HASH
        )
    finally:
        conn.close()


def test_a_head_that_is_not_a_digest_is_refused() -> None:
    with pytest.raises(CommitmentError, match="lowercase hex"):
        ChainHeads(declaration_head="nope", verdict_head=GENESIS_HASH)


# --------------------------------------------------------------------------
# The preimage
# --------------------------------------------------------------------------


def test_two_different_commitments_do_not_share_a_preimage() -> None:
    """Length-prefixed, so no field boundary can be moved without changing it."""
    a = ChainHeads(declaration_head="a" * 64, verdict_head="b" * 64)
    b = ChainHeads(declaration_head="b" * 64, verdict_head="a" * 64)
    assert commitment_bytes(WITNESS_SCHEME, "ab", a) != commitment_bytes(
        WITNESS_SCHEME, "ab", b
    )
    assert commitment_bytes(WITNESS_SCHEME, "ab", a) != commitment_bytes(
        WITNESS_SCHEME, "a", replace(a, declaration_head="b" + "a" * 63)
    )
    assert commitment_bytes(WITNESS_SCHEME, "ab", a) != commitment_bytes(
        "other-scheme", "ab", a
    )


def test_the_commitment_domain_is_disjoint_from_the_chains() -> None:
    """A commitment must never be replayable as a record MAC or a chain link."""
    heads = ChainHeads(declaration_head="a" * 64, verdict_head="b" * 64)
    preimage = commitment_bytes(WITNESS_SCHEME, WITNESS_ID, heads)
    assert not preimage.startswith(b"reg-chain-signing-v1\x00")
    assert not preimage.startswith(b"reg-chain-record-v1\x00")
    assert not preimage.startswith(b"reg-chain-link-v1\x00")


@pytest.mark.parametrize(
    ("scheme", "witness_id", "match"),
    [
        ("", WITNESS_ID, "non-empty"),
        (WITNESS_SCHEME, "  ", "witness_id"),
    ],
)
def test_a_preimage_over_nothing_is_refused(
    scheme: str, witness_id: str, match: str
) -> None:
    heads = ChainHeads(declaration_head="a" * 64, verdict_head="b" * 64)
    with pytest.raises(CommitmentError, match=match):
        commitment_bytes(scheme, witness_id, heads)


# --------------------------------------------------------------------------
# The happy path, and what it is allowed to claim
# --------------------------------------------------------------------------


def test_a_committed_artifact_verifies_under_its_witness(
    committed: Path, witness: Witness
) -> None:
    check = _check(committed, witness)
    assert check.state is CommitmentState.VALID
    assert check.scheme == WITNESS_SCHEME
    assert check.witness_id == WITNESS_ID
    assert check.recorded == check.computed


def test_the_artifact_says_what_the_witness_scheme_does_not_prove(
    committed: Path,
) -> None:
    """The honesty note is in the file, not only in the module docstring.

    An assessor reading `commitment: witness-hmac-sha256-v1` and taking it for a
    timestamp has been misled by this project. The artifact is the thing handed
    over, so the disclaimer travels in it.
    """
    statement = _meta(committed, META_COMMITMENT_STATEMENT)
    assert statement is not None
    assert "NOT a third-party timestamp" in statement
    assert "RFC 3161" in statement


def test_the_check_has_three_states_and_is_not_a_bool(
    committed: Path, witness: Witness
) -> None:
    with pytest.raises(TypeError, match="three states"):
        bool(_check(committed, witness))


def test_the_check_describes_itself_in_one_line(
    committed: Path, witness: Witness
) -> None:
    assert WITNESS_SCHEME in _check(committed, witness).describe()


# --------------------------------------------------------------------------
# THE NEGATIVES. Each one is a way the check must be able to say no.
# --------------------------------------------------------------------------


def test_a_tampered_chain_no_longer_matches_the_heads_it_committed_to(
    committed: Path, witness: Witness, tmp_path: Path
) -> None:
    """The whole point, in one test.

    One record altered and **re-signed**, so its MAC verifies again. That is the
    strongest form of the attack the commitment exists for: the author, holding
    every key, rewriting the record. The chain still breaks at the successor
    here — but re-issuing the *whole* history would not break even that, and the
    committed heads are what would still not match.
    """
    copy = tmp_path / "tampered.sqlite"
    keyring = chain.load_keyring(committed.parent / "keyring.json")
    chain.tamper(
        committed, copy, "declaration:first:horizon=9.5", keyring=keyring, resign=True
    )

    check = _check(copy, witness)
    assert check.state is CommitmentState.INVALID
    assert "declaration_head" in check.reason
    assert check.recorded != check.computed
    assert check.recorded.verdict_head == check.computed.verdict_head


def test_a_re_issued_chain_is_caught_without_the_witness_key_at_all(
    committed: Path, tmp_path: Path
) -> None:
    """The strongest property here, and the reason the heads are stored beside
    the signature rather than only inside it: *anybody* holding the file can
    compare the committed heads against the records it contains."""
    copy = tmp_path / "tampered-nokey.sqlite"
    keyring = chain.load_keyring(committed.parent / "keyring.json")
    chain.tamper(
        committed, copy, "verdict:#1:t=99.5", keyring=keyring, resign=True
    )
    check = _check(copy, None)
    assert check.state is CommitmentState.INVALID


def test_rewriting_the_recorded_heads_to_match_breaks_the_signature(
    committed: Path, witness: Witness, tmp_path: Path
) -> None:
    """The other half of the pincer, and the step the previous test leaves open.

    An author who alters the records and then rewrites the recorded heads to
    match makes step 1 agree again. Step 2 is what still says no, and producing
    a signature that passes it needs the second party's key — which is the whole
    mechanism, stated as a test rather than as a claim.
    """
    copy = tmp_path / "reheaded.sqlite"
    keyring = chain.load_keyring(committed.parent / "keyring.json")
    chain.tamper(
        committed, copy, "declaration:#1:horizon=9.5", keyring=keyring, resign=True
    )

    conn = store.connect(copy)
    try:
        moved = chain_heads(conn)
    finally:
        conn.close()
    _set_meta(copy, META_COMMITMENT_DECLARATION_HEAD, moved.declaration_head)
    _set_meta(copy, META_COMMITMENT_VERDICT_HEAD, moved.verdict_head)

    # Step 1 now agrees — and the verdict is still INVALID, on step 2.
    check = _check(copy, witness)
    assert check.recorded == check.computed
    assert check.state is CommitmentState.INVALID
    assert "does not verify" in check.reason


def test_a_forged_signature_does_not_verify(
    committed: Path, witness: Witness, tmp_path: Path
) -> None:
    copy = tmp_path / "resigned.sqlite"
    copy.write_bytes(committed.read_bytes())
    _set_meta(copy, META_COMMITMENT_SIGNATURE, "0" * 64)
    check = _check(copy, witness)
    assert check.state is CommitmentState.INVALID
    assert "does not verify" in check.reason


def test_an_artifact_closed_with_no_supplier_says_so_and_is_not_a_pass(
    uncommitted: Path,
) -> None:
    """THE NEGATIVE for "silence must not read as commitment".

    Two assertions, and the second is the one that matters: the key is present
    and says `none`, so a reader is *told* the chain is uncommitted rather than
    left to infer it from an absence — and the verdict is could-not-evaluate,
    never VALID.
    """
    assert _meta(uncommitted, META_COMMITMENT) == COMMITMENT_NONE
    check = _check(uncommitted, None)
    assert check.state is CommitmentState.COULD_NOT_EVALUATE
    assert "no commitment supplier" in check.reason
    assert "re-issuance" in check.reason


def test_an_uncommitted_artifact_is_not_a_pass_even_with_a_witness_in_hand(
    uncommitted: Path, witness: Witness
) -> None:
    """Holding a key does not make an artifact nobody committed a committed one."""
    assert _check(uncommitted, witness).state is CommitmentState.COULD_NOT_EVALUATE


def test_an_artifact_predating_the_interface_is_distinguishable_from_an_uncommitted_one(
    uncommitted: Path, tmp_path: Path
) -> None:
    """A missing key and `none` are different facts and get different reasons.

    "This build had no witness" is a statement about the run. "This file was
    written before commitments existed" is a statement about the reader's
    situation. Collapsing them would tell an assessor the first when the truth
    is the second.
    """
    copy = tmp_path / "old.sqlite"
    copy.write_bytes(uncommitted.read_bytes())
    conn = sqlite3.connect(copy)
    try:
        conn.execute("DELETE FROM meta WHERE key = ?", (META_COMMITMENT,))
        conn.commit()
    finally:
        conn.close()

    check = _check(copy, None)
    assert check.state is CommitmentState.COULD_NOT_EVALUATE
    assert "before the commitment interface existed" in check.reason
    assert "no commitment supplier" not in check.reason


def test_a_scheme_this_version_does_not_implement_is_unchecked_not_uncommitted(
    committed: Path, tmp_path: Path
) -> None:
    """An adapter from a newer version — RFC 3161, a transparency log — must
    come back could-not-evaluate. Reporting it as uncommitted would be a finding
    about an artifact that may be committed better than this one can check."""
    copy = tmp_path / "future.sqlite"
    copy.write_bytes(committed.read_bytes())
    _set_meta(copy, META_COMMITMENT, "rfc3161-v1")
    check = _check(copy, None)
    assert check.state is CommitmentState.COULD_NOT_EVALUATE
    assert "does not implement" in check.reason


def test_a_partial_commitment_is_could_not_evaluate(
    committed: Path, tmp_path: Path
) -> None:
    """Half a commitment is checked against nothing, and is not an absent one."""
    copy = tmp_path / "partial.sqlite"
    copy.write_bytes(committed.read_bytes())
    _set_meta(copy, META_COMMITMENT_VERDICT_HEAD, "not-a-digest")
    check = _check(copy, None)
    assert check.state is CommitmentState.COULD_NOT_EVALUATE
    assert "incomplete" in check.reason


def test_matching_heads_with_no_witness_key_is_not_a_pass(committed: Path) -> None:
    """Not having checked the signature is not having checked it."""
    check = _check(committed, None)
    assert check.state is CommitmentState.COULD_NOT_EVALUATE
    assert "no witness key was offered" in check.reason
    assert check.recorded == check.computed


def test_the_wrong_witness_is_could_not_evaluate_rather_than_a_finding(
    committed: Path
) -> None:
    """A verifier holding somebody else's key has learned nothing about this
    artifact, and reporting that as tampering would be a false accusation."""
    other = generate_witness("someone-else")
    check = _check(committed, other)
    assert check.state is CommitmentState.COULD_NOT_EVALUATE
    assert "someone-else" in check.reason


# --------------------------------------------------------------------------
# Independence: a witness is a *second* party
# --------------------------------------------------------------------------


def test_a_witness_holding_a_record_signing_key_is_refused() -> None:
    """THE NEGATIVE for the independence argument.

    A witness who is the signer produces a signature indistinguishable from a
    real one, so it has to be refused where it is made — nothing downstream of
    a common-cause failure can detect it. Same shape as `reg/enforce.py` not
    importing from `declare/`.
    """
    keyring = generate_keyring()
    for role in chain.ROLES:
        impostor = Witness(
            witness_id="the-author", material=keyring.key(role).material
        )
        with pytest.raises(CommitmentError, match="record-signing key"):
            check_witness_is_independent(impostor, keyring)


def test_an_independent_witness_passes_the_check() -> None:
    """The check is only meaningful if it also says yes to a real witness."""
    check_witness_is_independent(generate_witness(WITNESS_ID), generate_keyring())


def test_the_independence_check_refuses_the_wrong_types() -> None:
    with pytest.raises(CommitmentError, match="takes a Witness"):
        check_witness_is_independent("not a witness", generate_keyring())
    with pytest.raises(CommitmentError, match="takes a Keyring"):
        check_witness_is_independent(generate_witness(WITNESS_ID), "not a keyring")


# --------------------------------------------------------------------------
# The witness file
# --------------------------------------------------------------------------


def test_a_witness_file_round_trips_and_is_owner_only(tmp_path: Path) -> None:
    original = generate_witness(WITNESS_ID)
    path = write_witness(original, tmp_path / "witness.json")
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600, (
        "a witness key every process on the host can read makes the second "
        "signature decorative"
    )
    assert load_witness(path) == original


def test_a_witness_key_is_never_in_its_repr() -> None:
    witness = generate_witness(WITNESS_ID)
    assert witness.material.hex() not in repr(witness)
    assert "redacted" in repr(witness)


@pytest.mark.parametrize(
    ("payload", "match"),
    [
        ("not json", "not valid JSON"),
        ('["a"]', "JSON object"),
        ('{"witness_id": "w"}', "missing"),
        ('{"witness_id": "w", "key": "ab", "extra": 1}', "unknown field"),
        ('{"witness_id": "w", "key": 7}', "not a hex string"),
        ('{"witness_id": "w", "key": "ab"}', "hex characters"),
        ('{"witness_id": "w", "key": "' + "z" * 64 + '"}', "not hexadecimal"),
    ],
)
def test_a_witness_file_that_is_not_one_is_refused(
    tmp_path: Path, payload: str, match: str
) -> None:
    path = tmp_path / "bad.json"
    path.write_text(payload, encoding="utf-8")
    with pytest.raises(CommitmentError, match=match):
        load_witness(path)


def test_a_missing_witness_file_is_refused(tmp_path: Path) -> None:
    with pytest.raises(CommitmentError, match="could not be read"):
        load_witness(tmp_path / "nope.json")


def test_a_short_witness_key_is_refused_rather_than_stretched() -> None:
    with pytest.raises(CommitmentError, match="refused rather than stretched"):
        Witness(witness_id="w", material=b"\x00" * (WITNESS_KEY_BYTES - 1))


def test_a_witness_with_no_name_is_refused() -> None:
    with pytest.raises(CommitmentError, match="witness with no name"):
        Witness(witness_id="  ", material=b"\x00" * WITNESS_KEY_BYTES)


def test_write_witness_refuses_something_that_is_not_a_witness(tmp_path: Path) -> None:
    with pytest.raises(CommitmentError, match="takes a Witness"):
        write_witness("not a witness", tmp_path / "w.json")


def test_a_generated_witness_key_is_not_seeded() -> None:
    """A seeded secret is not a secret: a witness key recomputable from the
    artifact would let its own author produce the second party's signature."""
    assert generate_witness(WITNESS_ID) != generate_witness(WITNESS_ID)


# --------------------------------------------------------------------------
# The interface itself
# --------------------------------------------------------------------------


def test_a_commitment_under_an_unknown_scheme_cannot_be_constructed() -> None:
    heads = ChainHeads(declaration_head="a" * 64, verdict_head="b" * 64)
    with pytest.raises(CommitmentError, match="not one this version implements"):
        Commitment(
            scheme="rfc3161-v1", witness_id="w", heads=heads, token="deadbeef"
        )


def test_a_commitment_with_an_empty_proof_is_refused() -> None:
    heads = ChainHeads(declaration_head="a" * 64, verdict_head="b" * 64)
    with pytest.raises(CommitmentError, match="empty proof"):
        Commitment(scheme=WITNESS_SCHEME, witness_id="w", heads=heads, token="  ")


def test_the_committer_is_callable_with_heads_and_nothing_else(
    witness: Witness,
) -> None:
    """The interface is `(ChainHeads) -> Commitment`, which is what makes an RFC
    3161 or transparency-log adapter a new class rather than a rewrite."""
    heads = ChainHeads(declaration_head="a" * 64, verdict_head="b" * 64)
    made = WitnessCommitter(witness)(heads)
    assert isinstance(made, Commitment)
    assert made.heads == heads
    assert made.scheme == WITNESS_SCHEME
    assert made.witness_id == witness.witness_id


def test_a_committer_over_something_that_is_not_a_witness_is_refused() -> None:
    with pytest.raises(CommitmentError, match="takes a Witness"):
        WitnessCommitter("not a witness")


def test_a_committer_cannot_be_relabelled_as_another_scheme(
    witness: Witness,
) -> None:
    with pytest.raises(CommitmentError, match="different adapter"):
        WitnessCommitter(witness, scheme="rfc3161-v1")


# --------------------------------------------------------------------------
# What `build` does with a supplier
# --------------------------------------------------------------------------


def test_a_commitment_without_a_record_stream_is_refused(tmp_path: Path) -> None:
    """There is no chain to commit to, and a signature over two genesis hashes
    would verify and say nothing."""
    with pytest.raises(graph.GraphBuildError, match="no record stream"):
        _build(tmp_path, "no-records.sqlite", witness=generate_witness("w"), records=False)


def test_a_supplier_that_is_not_callable_is_refused(tmp_path: Path) -> None:
    csv, scn = _stream(tmp_path)
    with pytest.raises(graph.GraphBuildError, match="must be callable"):
        graph.build(
            csv,
            tmp_path / "bad.sqlite",
            scn.world.limits,
            identity=TEST_IDENTITY,
            human_radius=scn.world.human_radius,
            records=_records(csv, scn, tmp_path),
            commitment="not a committer",
            **_FAST,
        )


def test_a_supplier_that_commits_to_other_heads_is_refused(tmp_path: Path) -> None:
    """A commitment over heads that are not this artifact's would verify against
    itself and fail against the file it is in — which is the one failure mode
    that looks like tampering and is not."""
    csv, scn = _stream(tmp_path)
    liar = generate_witness("liar")

    def wrong(_heads: ChainHeads) -> Commitment:
        return WitnessCommitter(liar)(
            ChainHeads(declaration_head="a" * 64, verdict_head="b" * 64)
        )

    with pytest.raises(graph.GraphBuildError, match="different heads"):
        graph.build(
            csv,
            tmp_path / "liar.sqlite",
            scn.world.limits,
            identity=TEST_IDENTITY,
            human_radius=scn.world.human_radius,
            records=_records(csv, scn, tmp_path),
            commitment=wrong,
            **_FAST,
        )
    assert not (tmp_path / "liar.sqlite").exists(), (
        "a refused build must leave no artifact behind"
    )


def test_the_committed_heads_are_written_into_the_artifact(
    committed: Path, witness: Witness
) -> None:
    conn = store.connect(committed)
    try:
        heads = chain_heads(conn)
        assert store.get_meta(conn, META_COMMITMENT) == WITNESS_SCHEME
        assert store.get_meta(conn, META_COMMITMENT_WITNESS) == WITNESS_ID
        assert (
            store.get_meta(conn, META_COMMITMENT_DECLARATION_HEAD)
            == heads.declaration_head
        )
        assert store.get_meta(conn, META_COMMITMENT_VERDICT_HEAD) == heads.verdict_head
    finally:
        conn.close()


def test_a_committed_build_is_still_byte_reproducible(
    tmp_path: Path, witness: Witness
) -> None:
    """Same stream, same declared start, same witness key — same bytes. The
    commitment is a deterministic function of the heads, so it does not become
    the one thing in the artifact that moves between two runs."""
    a = _build(tmp_path, "a.sqlite", witness=witness)
    b = _build(tmp_path, "b.sqlite", witness=witness)
    assert a.read_bytes() == b.read_bytes()
