"""Tests for reg.anchor_tsa — the RFC 3161 timestamp adapter (issue #316).

**No network in CI.** Every test that touches a TSA uses either the committed
fixture response (`tests/fixtures/tsa_response.der` — a real openssl-minted
RFC 3161 token whose messageImprint is SHA-256 over the fixture head below,
with the fixture CA at `tests/fixtures/tsa_ca.crt`) or a `FakeTsaClient`
returning those bytes. The one `HttpTsaClient` test only checks its
constructor refuses a non-https URL — it never sends a request.

The fixture head is `sha256(b"reg-anchor-tsa-fixture-v1")`, and the fixture
token's messageImprint is `sha256(fixture_head)` — exactly what
`rfc3161-client`'s request builder produces for `data=head`, which is what the
committer sends.
"""

from __future__ import annotations

import base64
import hashlib
import sqlite3
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.serialization import Encoding
from cryptography.x509 import load_pem_x509_certificate

from reg import anchor_tsa, chain, commit, query, store
from reg.anchor_tsa import (
    AnchorError,
    AnchorState,
    HttpTsaClient,
    Rfc3161Committer,
    TsaClient,
    verify_anchors,
)
from reg.commit import TSA_SCHEME

FIXTURES = Path(__file__).parent / "fixtures"
FIXTURE_HEAD = hashlib.sha256(b"reg-anchor-tsa-fixture-v1").digest()
TSA_NAME = "fixture-test-tsa"


def _fixture_response() -> bytes:
    return (FIXTURES / "tsa_response.der").read_bytes()


def _fixture_ca_der() -> bytes:
    pem = (FIXTURES / "tsa_ca.crt").read_bytes()
    return load_pem_x509_certificate(pem).public_bytes(Encoding.DER)


class FakeTsaClient(TsaClient):
    """A TSA that returns canned bytes and records what it was sent.

    The only thing that may leave the operator boundary is the 32-byte head,
    so the recording is the assertion surface for that: every digest handed
    over must be 32 bytes, and the test says which ones it expected.
    """

    def __init__(self, response: bytes) -> None:
        self._response = response
        self.seen: list[bytes] = []

    def timestamp(self, digest: bytes) -> bytes:
        if not isinstance(digest, bytes) or len(digest) != 32:
            raise AnchorError(f"fake TSA was sent {digest!r}, not 32 bytes")
        self.seen.append(digest)
        return self._response


def _epoch_db(tmp_path: Path, heads: dict[tuple[str, int], bytes]) -> sqlite3.Connection:
    """An artifact-shaped DB holding exactly the given epoch heads."""
    conn = store.create(tmp_path / "anchor.db", record_tables=True)
    for (role, epoch), head in sorted(heads.items()):
        store.insert_epoch_head(
            conn,
            chain.EpochHead(
                chain=role,  # type: ignore[arg-type]
                epoch=epoch,
                merkle_root=b"\x11" * 32,
                checkpoint_sig=b"\x22" * 64,
                key_id="33" * 32,
                head=head,
            ),
        )
    conn.commit()
    return conn


def _anchor_one(
    conn: sqlite3.Connection, role: str, epoch: int, receipt: bytes | None = None
) -> None:
    store.store_anchor_receipt(
        conn, role, epoch, TSA_SCHEME, receipt if receipt is not None else _fixture_response()
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Acceptance criterion: valid token verifies offline; tampered head fails;
# missing anchor reports cleanly.
# ---------------------------------------------------------------------------


def test_valid_token_verifies_offline(tmp_path: Path) -> None:
    conn = _epoch_db(tmp_path, {("policy", 0): FIXTURE_HEAD})
    _anchor_one(conn, "policy", 0)
    check = verify_anchors(conn, [_fixture_ca_der()])
    assert check.state is AnchorState.VALID, check.reason
    assert len(check.epochs) == 1
    assert check.epochs[0].state is AnchorState.VALID
    assert "witnessed" in check.epochs[0].reason


def test_tampered_head_fails(tmp_path: Path) -> None:
    """The receipt is the fixture's, but the epoch head is not the fixture's:
    the token's messageImprint is SHA-256 over a different head — INVALID."""
    conn = _epoch_db(tmp_path, {("policy", 0): b"\x99" * 32})
    _anchor_one(conn, "policy", 0)
    check = verify_anchors(conn, [_fixture_ca_der()])
    assert check.state is AnchorState.INVALID, check.reason
    assert "messageImprint" in check.reason


def test_tampered_receipt_fails(tmp_path: Path) -> None:
    """A receipt whose bytes were flipped no longer verifies — INVALID, not a
    shrug. Flipping the last byte breaks the CMS signature."""
    conn = _epoch_db(tmp_path, {("policy", 0): FIXTURE_HEAD})
    bad = bytearray(_fixture_response())
    bad[-1] ^= 0xFF
    _anchor_one(conn, "policy", 0, receipt=bytes(bad))
    check = verify_anchors(conn, [_fixture_ca_der()])
    assert check.state is AnchorState.INVALID, check.reason


def test_missing_anchor_reports_cleanly(tmp_path: Path) -> None:
    """Epoch heads, no receipts at all: COULD-NOT-EVALUATE, saying so."""
    conn = _epoch_db(tmp_path, {("policy", 0): FIXTURE_HEAD})
    check = verify_anchors(conn, [_fixture_ca_der()])
    assert check.state is AnchorState.COULD_NOT_EVALUATE
    assert "no" in check.reason and "receipt" in check.reason


def test_epoch_without_receipt_reports_cleanly(tmp_path: Path) -> None:
    """Two closed epochs, one receipt: the anchored one can be VALID while
    the bare one is COULD-NOT-EVALUATE — and the overall check is not VALID."""
    conn = _epoch_db(
        tmp_path, {("policy", 0): FIXTURE_HEAD, ("policy", 1): FIXTURE_HEAD}
    )
    _anchor_one(conn, "policy", 0)
    check = verify_anchors(conn, [_fixture_ca_der()])
    assert check.state is AnchorState.COULD_NOT_EVALUATE
    by_epoch = {e.epoch: e for e in check.epochs}
    assert by_epoch[0].state is AnchorState.VALID
    assert by_epoch[1].state is AnchorState.COULD_NOT_EVALUATE


def test_no_roots_offered_is_could_not_evaluate(tmp_path: Path) -> None:
    """The imprint matches but no trust roots were offered: the signature is
    unchecked, so the finding is COULD-NOT-EVALUATE — never VALID."""
    conn = _epoch_db(tmp_path, {("policy", 0): FIXTURE_HEAD})
    _anchor_one(conn, "policy", 0)
    check = verify_anchors(conn, [])
    assert check.state is AnchorState.COULD_NOT_EVALUATE
    assert "no TSA trust roots were offered" in check.reason


def test_unparseable_token_is_could_not_evaluate(tmp_path: Path) -> None:
    """Bytes that are not a TimeStampResp: the artifact may carry a good token
    this reader cannot read — COULD-NOT-EVALUATE, not INVALID."""
    conn = _epoch_db(tmp_path, {("policy", 0): FIXTURE_HEAD})
    _anchor_one(conn, "policy", 0, receipt=b"definitely not DER")
    check = verify_anchors(conn, [_fixture_ca_der()])
    assert check.state is AnchorState.COULD_NOT_EVALUATE
    assert "does not parse" in check.reason


def test_wrong_root_is_invalid_not_valid(tmp_path: Path) -> None:
    """A trust root the TSA chain does not lead to: the signature check
    fails — INVALID. The negative the scheme's honesty depends on."""
    import datetime

    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509 import (
        BasicConstraints,
        CertificateBuilder,
        Name,
        NameAttribute,
        random_serial_number,
    )
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = Name([NameAttribute(NameOID.COMMON_NAME, "wrong-root")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    conn = _epoch_db(tmp_path, {("policy", 0): FIXTURE_HEAD})
    _anchor_one(conn, "policy", 0)
    check = verify_anchors(conn, [cert.public_bytes(Encoding.DER)])
    assert check.state is AnchorState.INVALID, check.reason


def test_anchor_check_is_not_a_bool(tmp_path: Path) -> None:
    conn = _epoch_db(tmp_path, {("policy", 0): FIXTURE_HEAD})
    with pytest.raises(TypeError):
        bool(verify_anchors(conn, []))


# ---------------------------------------------------------------------------
# The committer: anchors every epoch head at close, behind the seam.
# ---------------------------------------------------------------------------


def test_committer_anchors_each_epoch_head_at_close(tmp_path: Path) -> None:
    """Two chains, one epoch each: two TSA exchanges, two receipts, and the
    only bytes that left the boundary are the two 32-byte heads."""
    conn = _epoch_db(
        tmp_path,
        {("policy", 0): FIXTURE_HEAD, ("enforcement", 0): FIXTURE_HEAD},
    )
    tsa = FakeTsaClient(_fixture_response())
    heads = commit.ChainHeads(
        declaration_head="ab" * 32, verdict_head="cd" * 32
    )
    made = Rfc3161Committer(tsa, conn, tsa_name=TSA_NAME)(heads)

    assert made.scheme == TSA_SCHEME
    assert made.witness_id == TSA_NAME
    assert made.heads == heads
    # The meta token is the last anchored token, base64.
    assert base64.b64decode(made.token) == _fixture_response()

    # Only the heads crossed the boundary, one exchange each.
    assert tsa.seen == [FIXTURE_HEAD, FIXTURE_HEAD]
    assert all(len(d) == 32 for d in tsa.seen)

    receipts = anchor_tsa.anchor_receipts(conn)
    assert [(c, e) for c, e, _ in receipts] == [
        ("enforcement", 0),
        ("policy", 0),
    ]
    assert all(r == _fixture_response() for _, _, r in receipts)


def test_committer_refuses_a_token_for_a_different_digest(
    tmp_path: Path,
) -> None:
    """The TSA answered, but not for the digest it was sent: the build must
    not persist that as an anchor."""
    conn = _epoch_db(tmp_path, {("policy", 0): b"\x99" * 32})
    tsa = FakeTsaClient(_fixture_response())
    heads = commit.ChainHeads(
        declaration_head="ab" * 32, verdict_head="cd" * 32
    )
    with pytest.raises(AnchorError, match="messageImprint"):
        Rfc3161Committer(tsa, conn, tsa_name=TSA_NAME)(heads)
    assert anchor_tsa.anchor_receipts(conn) == []


def test_committer_refuses_garbage_response(tmp_path: Path) -> None:
    conn = _epoch_db(tmp_path, {("policy", 0): FIXTURE_HEAD})
    tsa = FakeTsaClient(b"not a timestamp response")
    heads = commit.ChainHeads(
        declaration_head="ab" * 32, verdict_head="cd" * 32
    )
    with pytest.raises(AnchorError, match="does not parse"):
        Rfc3161Committer(tsa, conn, tsa_name=TSA_NAME)(heads)
    assert anchor_tsa.anchor_receipts(conn) == []


def test_committer_refuses_no_epoch_heads(tmp_path: Path) -> None:
    """Anchoring zero epochs would verify and mean nothing — refused."""
    conn = _epoch_db(tmp_path, {})
    tsa = FakeTsaClient(_fixture_response())
    heads = commit.ChainHeads(
        declaration_head="ab" * 32, verdict_head="cd" * 32
    )
    with pytest.raises(AnchorError, match="no epoch heads"):
        Rfc3161Committer(tsa, conn, tsa_name=TSA_NAME)(heads)
    assert tsa.seen == []


def test_committer_validates_its_arguments() -> None:
    conn = sqlite3.connect(":memory:")
    tsa = FakeTsaClient(_fixture_response())
    with pytest.raises(AnchorError, match="TsaClient"):
        Rfc3161Committer("not a client", conn, tsa_name=TSA_NAME)  # type: ignore[arg-type]
    with pytest.raises(AnchorError, match="sqlite3.Connection"):
        Rfc3161Committer(tsa, "not a conn", tsa_name=TSA_NAME)  # type: ignore[arg-type]
    with pytest.raises(AnchorError, match="tsa_name"):
        Rfc3161Committer(tsa, conn, tsa_name="  ")
    with pytest.raises(AnchorError, match="different scheme"):
        Rfc3161Committer(tsa, conn, tsa_name=TSA_NAME, scheme="witness-hmac-sha256-v1")


def test_http_client_refuses_cleartext() -> None:
    with pytest.raises(AnchorError, match="https://"):
        HttpTsaClient("http://tsa.example.com/tsa")


def test_http_client_refuses_non_32_byte_digest() -> None:
    client = HttpTsaClient("https://tsa.example.com/tsa")
    with pytest.raises(AnchorError, match="32-byte"):
        client.timestamp(b"too short")


# ---------------------------------------------------------------------------
# Scheme registration and statements.
# ---------------------------------------------------------------------------


def test_scheme_is_registered() -> None:
    assert TSA_SCHEME in commit.SCHEMES
    assert commit.META_COMMITMENT == query._META_COMMITMENT


def test_tsa_statement_is_a_third_party_timestamp() -> None:
    text = commit.commitment_statement(TSA_SCHEME, "Example TSA")
    assert "Example TSA" in text
    assert "IS a third-party timestamp" in text
    assert "only 32-byte heads left the boundary" in text
    # The witness sentence still says what it is not.
    assert "NOT a third-party timestamp" in commit.COMMITMENT_STATEMENT


def test_commitment_statement_refuses_unknown_scheme() -> None:
    with pytest.raises(commit.CommitmentError, match="not one this version implements"):
        commit.commitment_statement("nope-v1", "x")


# ---------------------------------------------------------------------------
# Cold read: anchor status per artifact.
# ---------------------------------------------------------------------------


def test_cold_read_reports_anchored_epochs(tmp_path: Path) -> None:
    conn = _epoch_db(tmp_path, {("policy", 0): FIXTURE_HEAD})
    _anchor_one(conn, "policy", 0)
    report = query.cold_read(conn)
    row = report[query.CLAIM_ANCHOR]
    assert row.state == query.CHECKABLE_WITH_A_KEY
    assert TSA_SCHEME in row.detail
    assert "1 epoch heads" in row.detail


def test_cold_read_reports_commitment_none(tmp_path: Path) -> None:
    """No receipts and meta[commitment] == 'none': the row says so."""
    conn = _epoch_db(tmp_path, {("policy", 0): FIXTURE_HEAD})
    store.put_meta(conn, commit.META_COMMITMENT, commit.COMMITMENT_NONE)
    conn.commit()
    report = query.cold_read(conn)
    row = report[query.CLAIM_ANCHOR]
    assert row.state == query.ABSENT
    assert "commitment: none" in row.detail


def test_cold_read_anchor_row_covers_the_claims_tuple() -> None:
    assert query.COLD_READ_CLAIMS[-1] == query.CLAIM_ANCHOR
    assert query.CLAIM_ANCHOR in query.COLD_READ_QUESTIONS


# ---------------------------------------------------------------------------
# verify_commitment under the TSA scheme.
# ---------------------------------------------------------------------------


def _witness_meta_for_tsa(
    conn: sqlite3.Connection, heads: commit.ChainHeads
) -> None:
    """The meta block _write_commitment would have written for a TSA commit."""
    store.put_meta(conn, commit.META_COMMITMENT, TSA_SCHEME)
    store.put_meta(conn, commit.META_COMMITMENT_WITNESS, TSA_NAME)
    store.put_meta(
        conn, commit.META_COMMITMENT_DECLARATION_HEAD, heads.declaration_head
    )
    store.put_meta(
        conn, commit.META_COMMITMENT_VERDICT_HEAD, heads.verdict_head
    )
    store.put_meta(
        conn,
        commit.META_COMMITMENT_SIGNATURE,
        base64.b64encode(_fixture_response()).decode("ascii"),
    )
    conn.commit()


def test_verify_commitment_tsa_scheme_catches_moved_heads(
    tmp_path: Path,
) -> None:
    """The recorded heads are not what this artifact's records produce
    (empty tables walk to the genesis hashes): INVALID before any token is
    looked at — the heads check runs first and needs no key, no roots."""
    conn = _epoch_db(tmp_path, {("policy", 0): FIXTURE_HEAD})
    _anchor_one(conn, "policy", 0)
    heads = commit.ChainHeads(
        declaration_head="ab" * 32, verdict_head="cd" * 32
    )
    _witness_meta_for_tsa(conn, heads)
    check = commit.verify_commitment(conn, None, tsa_roots=[_fixture_ca_der()])
    assert check.state is commit.CommitmentState.INVALID
    assert "moved" in check.reason


def test_store_anchor_receipt_refuses_a_different_second_receipt(
    tmp_path: Path,
) -> None:
    conn = _epoch_db(tmp_path, {("policy", 0): FIXTURE_HEAD})
    _anchor_one(conn, "policy", 0)
    with pytest.raises(store.StoreError, match="different receipt"):
        store.store_anchor_receipt(
            conn, "policy", 0, TSA_SCHEME, b"a different token"
        )
    # The identical bytes are a no-op, not a fault (retry after failed close).
    store.store_anchor_receipt(conn, "policy", 0, TSA_SCHEME, _fixture_response())


def test_store_anchor_receipt_validates_its_arguments(tmp_path: Path) -> None:
    conn = _epoch_db(tmp_path, {})
    with pytest.raises(store.StoreError, match="policy.*enforcement"):
        store.store_anchor_receipt(conn, "sideways", 0, TSA_SCHEME, b"x")
    with pytest.raises(store.StoreError, match="non-negative int"):
        store.store_anchor_receipt(conn, "policy", -1, TSA_SCHEME, b"x")
    with pytest.raises(store.StoreError, match="non-empty bytes"):
        store.store_anchor_receipt(conn, "policy", 0, TSA_SCHEME, b"")
