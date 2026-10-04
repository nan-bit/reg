"""Tests for reg.anchor_rekor — the Rekor v2 transparency-log adapter (issue #317).

**No network in CI.** The log is a `FakeRekorClient` that builds a valid
fixture `TransparencyLogEntry` around whatever envelope the committer
submits: a two-leaf RFC 6962 tree, a C2SP checkpoint signed by the fixture
log key, and the log key itself pinned through an injected `key_pinner` —
never through TUF. The one `HttpRekorClient` test only checks its
constructor refuses a non-https URL — it never sends a request.

The fixture log key is generated per test module run: no test asserts on its
bytes, only on what verification says about receipts made under it.
"""

from __future__ import annotations

import base64
import dataclasses
import hashlib
import json
import sqlite3
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from reg import anchor_rekor, chain, commit, query, store
from reg.anchor_rekor import (
    AnchorState,
    HttpRekorClient,
    PinnedLogKey,
    RekorClient,
    RekorError,
    RekorV2Committer,
    verify_anchors,
)
from reg.commit import REKOR_SCHEME

FIXTURE_HEAD = hashlib.sha256(b"reg-anchor-rekor-fixture-v1").digest()
REKOR_NAME = "rekor.example.test"
BASE_URL = "https://rekor.example.test"


def _canonical(obj: object) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


@dataclasses.dataclass(frozen=True)
class _FixtureLog:
    """The fixture transparency log: a keypair, its C2SP key id, an origin."""

    private_key: ec.EllipticCurvePrivateKey
    public_der: bytes
    key_id: bytes  # sha256(public_der) — the non-truncated C2SP key id
    origin: str = "rekor.example.test"


def _fixture_log() -> _FixtureLog:
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_der = private_key.public_key().public_bytes(
        Encoding.DER, PublicFormat.SubjectPublicKeyInfo
    )
    return _FixtureLog(private_key, public_der, hashlib.sha256(public_der).digest())


def _leaf(body: bytes) -> bytes:
    return hashlib.sha256(b"\x00" + body).digest()


def _node(left: bytes, right: bytes) -> bytes:
    return hashlib.sha256(b"\x01" + left + right).digest()


def _checkpoint_envelope(log: _FixtureLog, root: bytes, tree_size: int) -> str:
    """A C2SP signed note over a checkpoint, the way a log would emit it."""
    note = (
        f"{log.origin}\n{tree_size}\n{_b64(root)}\n"
        "Timestamp: 1750000000000000000\n"
    )
    signature = log.private_key.sign(note.encode("utf-8"), ec.ECDSA(hashes.SHA256()))
    sig_line = (
        "\u2014 " + log.origin + " " + _b64(log.key_id[:4] + signature) + "\n"
    )
    return note + "\n" + sig_line


def _pinned(log: _FixtureLog) -> PinnedLogKey:
    return PinnedLogKey(
        base_url=BASE_URL,
        operator="example",
        key_id_hex=log.key_id.hex(),
        public_key_der=log.public_der,
        key_details="PKIX_ECDSA_P256_SHA_256",
    )


class FakeRekorClient(RekorClient):
    """A Rekor v2 log that integrates whatever it is sent, and remembers it.

    Builds the fixture `TransparencyLogEntry` around the submitted request's
    digest: a two-leaf RFC 6962 tree (a filler leaf plus the entry), the
    inclusion proof for the entry, and a checkpoint signed by the fixture log
    key. `digest_override` makes it answer for a different digest than the
    one it was sent — the committer must refuse that response.
    """

    def __init__(self, log: _FixtureLog, *, digest_override: bytes | None = None) -> None:
        self._log = log
        self._digest_override = digest_override
        self.seen: list[bytes] = []

    @property
    def base_url(self) -> str:
        return BASE_URL

    def submit(self, request: bytes) -> bytes:
        if not isinstance(request, bytes) or not request:
            raise RekorError("fake log was sent an empty request")
        self.seen.append(request)
        req = json.loads(request)
        asked = req["hashedRekordRequestV002"]
        digest = self._digest_override or base64.b64decode(asked["digest"])
        body = _canonical(
            {
                "kind": "hashedrekord",
                "apiVersion": "0.0.2",
                "spec": {
                    "hashedRekordV002": {
                        "data": {
                            "digest": _b64(digest),
                            "algorithm": "SHA2_256",
                        },
                        "signature": asked["signature"],
                    }
                },
            }
        )
        filler = _leaf(b"fake-other-leaf")
        ours = _leaf(body)
        root = _node(filler, ours)
        response = {
            "logIndex": "1",
            "logId": {"keyId": _b64(self._log.key_id)},
            "kindVersion": {"kind": "hashedrekord", "version": "0.0.2"},
            "inclusionProof": {
                "logIndex": "1",
                "rootHash": _b64(root),
                "treeSize": "2",
                "hashes": [_b64(filler)],
                "checkpoint": {
                    "envelope": _checkpoint_envelope(self._log, root, 2)
                },
            },
            "canonicalizedBody": _b64(body),
        }
        return json.dumps(response).encode("utf-8")


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


def _committer(
    conn: sqlite3.Connection, log: _FixtureLog, client: RekorClient | None = None
) -> RekorV2Committer:
    client = client if client is not None else FakeRekorClient(log)
    return RekorV2Committer(
        client, conn, REKOR_NAME, key_pinner=lambda url: _pinned(log)
    )


def _anchor_all(conn: sqlite3.Connection, log: _FixtureLog) -> None:
    heads = commit.ChainHeads(declaration_head="ab" * 32, verdict_head="cd" * 32)
    _committer(conn, log)(heads)
    conn.commit()


def _receipt(conn: sqlite3.Connection, role: str, epoch: int) -> dict:
    row = conn.execute(
        "SELECT receipt FROM anchor_receipts WHERE chain = ? AND epoch = ? "
        "AND scheme = ?",
        (role, epoch, REKOR_SCHEME),
    ).fetchone()
    assert row is not None
    return json.loads(bytes(row["receipt"]))


def _rewrite_receipt(conn: sqlite3.Connection, role: str, epoch: int, doc: dict) -> None:
    conn.execute(
        "UPDATE anchor_receipts SET receipt = ? WHERE chain = ? AND epoch = ? "
        "AND scheme = ?",
        (_canonical(doc), role, epoch, REKOR_SCHEME),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Acceptance criterion: inclusion proof verifies offline; tampered head fails.
# ---------------------------------------------------------------------------


def test_valid_proof_verifies_offline(tmp_path: Path) -> None:
    log = _fixture_log()
    conn = _epoch_db(tmp_path, {("policy", 0): FIXTURE_HEAD})
    _anchor_all(conn, log)
    check = verify_anchors(conn)
    assert check.state is AnchorState.VALID, check.reason
    assert len(check.epochs) == 1
    assert "rekor.example.test" in check.epochs[0].reason


def test_tampered_head_fails(tmp_path: Path) -> None:
    """The epoch head was rewritten after anchoring: the receipt's statement
    no longer names this artifact's head."""
    log = _fixture_log()
    conn = _epoch_db(tmp_path, {("policy", 0): FIXTURE_HEAD})
    _anchor_all(conn, log)
    conn.execute(
        "UPDATE epoch_heads SET head = ? WHERE chain = 'policy' AND epoch = 0",
        (hashlib.sha256(b"something-else").digest(),),
    )
    conn.commit()
    check = verify_anchors(conn)
    assert check.state is AnchorState.INVALID, check.reason
    assert "does not name this artifact's epoch head" in check.reason


def test_tampered_envelope_fails(tmp_path: Path) -> None:
    """The receipt's envelope was swapped: the entry's digest no longer
    matches it."""
    log = _fixture_log()
    conn = _epoch_db(tmp_path, {("policy", 0): FIXTURE_HEAD})
    _anchor_all(conn, log)
    doc = _receipt(conn, "policy", 0)
    envelope = json.loads(base64.b64decode(doc["envelope"]))
    statement = json.loads(base64.b64decode(envelope["payload"]))
    statement["subject"][0]["digest"]["sha256"] = "ff" * 32
    envelope["payload"] = _b64(_canonical(statement))
    doc["envelope"] = _b64(_canonical(envelope))
    _rewrite_receipt(conn, "policy", 0, doc)
    check = verify_anchors(conn)
    assert check.state is AnchorState.INVALID, check.reason
    assert "not SHA-256 over this receipt's envelope" in check.reason


def test_tampered_proof_fails(tmp_path: Path) -> None:
    """A flipped byte in the inclusion proof's hashes: the proof no longer
    chains to its root."""
    log = _fixture_log()
    conn = _epoch_db(tmp_path, {("policy", 0): FIXTURE_HEAD})
    _anchor_all(conn, log)
    doc = _receipt(conn, "policy", 0)
    proof = doc["entry"]["inclusionProof"]
    raw = bytearray(base64.b64decode(proof["hashes"][0]))
    raw[0] ^= 0xFF
    proof["hashes"][0] = _b64(bytes(raw))
    _rewrite_receipt(conn, "policy", 0, doc)
    check = verify_anchors(conn)
    assert check.state is AnchorState.INVALID, check.reason
    assert "inclusion proof" in check.reason


def test_tampered_checkpoint_signature_fails(tmp_path: Path) -> None:
    """The checkpoint was re-signed by nobody: the pinned key rejects it."""
    log = _fixture_log()
    conn = _epoch_db(tmp_path, {("policy", 0): FIXTURE_HEAD})
    _anchor_all(conn, log)
    doc = _receipt(conn, "policy", 0)
    envelope = doc["entry"]["inclusionProof"]["checkpoint"]["envelope"]
    lines = envelope.split("\n")
    # The signature line is the last non-empty line; corrupt its signature.
    assert lines[-1] == ""
    name, sig = lines[-2].split(" ", 1)[1], lines[-2].split(" ", 2)[2]
    raw = bytearray(base64.b64decode(sig))
    raw[-1] ^= 0xFF
    lines[-2] = "\u2014 " + name + " " + _b64(bytes(raw))
    doc["entry"]["inclusionProof"]["checkpoint"]["envelope"] = "\n".join(lines)
    _rewrite_receipt(conn, "policy", 0, doc)
    check = verify_anchors(conn)
    assert check.state is AnchorState.INVALID, check.reason
    assert "checkpoint" in check.reason


def test_missing_anchor_reports_cleanly(tmp_path: Path) -> None:
    """Epoch heads, no receipts: could-not-evaluate, never valid."""
    conn = _epoch_db(tmp_path, {("policy", 0): FIXTURE_HEAD})
    check = verify_anchors(conn)
    assert check.state is AnchorState.COULD_NOT_EVALUATE
    assert "no Rekor anchor receipts" in check.reason


def test_epoch_without_receipt_reports_cleanly(tmp_path: Path) -> None:
    log = _fixture_log()
    conn = _epoch_db(
        tmp_path, {("policy", 0): FIXTURE_HEAD, ("policy", 1): FIXTURE_HEAD}
    )
    _anchor_all(conn, log)
    conn.execute(
        "DELETE FROM anchor_receipts WHERE chain = 'policy' AND epoch = 1 "
        "AND scheme = ?",
        (REKOR_SCHEME,),
    )
    conn.commit()
    check = verify_anchors(conn)
    assert check.state is AnchorState.COULD_NOT_EVALUATE
    assert "no Rekor receipt" in check.reason


def test_receipt_without_pinned_key_is_could_not_evaluate(tmp_path: Path) -> None:
    log = _fixture_log()
    conn = _epoch_db(tmp_path, {("policy", 0): FIXTURE_HEAD})
    _anchor_all(conn, log)
    doc = _receipt(conn, "policy", 0)
    del doc["log"]
    _rewrite_receipt(conn, "policy", 0, doc)
    check = verify_anchors(conn)
    assert check.state is AnchorState.COULD_NOT_EVALUATE
    assert "pins no log key" in check.reason


def test_unknown_entry_kind_is_could_not_evaluate(tmp_path: Path) -> None:
    """A receipt whose entry is not a hashedrekord: this reader was built for
    one kind, and the client specification says to fail gracefully."""
    log = _fixture_log()
    conn = _epoch_db(tmp_path, {("policy", 0): FIXTURE_HEAD})
    _anchor_all(conn, log)
    doc = _receipt(conn, "policy", 0)
    body = json.loads(base64.b64decode(doc["entry"]["canonicalizedBody"]))
    body["kind"] = "dsse"
    doc["entry"]["canonicalizedBody"] = _b64(_canonical(body))
    _rewrite_receipt(conn, "policy", 0, doc)
    check = verify_anchors(conn)
    assert check.state is AnchorState.COULD_NOT_EVALUATE
    assert "not 'hashedrekord' '0.0.2'" in check.reason


def test_unparseable_receipt_is_could_not_evaluate(tmp_path: Path) -> None:
    log = _fixture_log()
    conn = _epoch_db(tmp_path, {("policy", 0): FIXTURE_HEAD})
    _anchor_all(conn, log)
    conn.execute(
        "UPDATE anchor_receipts SET receipt = ? WHERE chain = 'policy' "
        "AND epoch = 0 AND scheme = ?",
        (b"not json", REKOR_SCHEME),
    )
    conn.commit()
    check = verify_anchors(conn)
    assert check.state is AnchorState.COULD_NOT_EVALUATE


def test_anchor_check_is_not_a_bool(tmp_path: Path) -> None:
    conn = _epoch_db(tmp_path, {("policy", 0): FIXTURE_HEAD})
    check = verify_anchors(conn)
    with pytest.raises(TypeError, match="three states"):
        bool(check)  # noqa: B018


# ---------------------------------------------------------------------------
# The committer.
# ---------------------------------------------------------------------------


def test_committer_anchors_each_epoch_head_at_close(tmp_path: Path) -> None:
    """Two chains, one epoch each: two log submissions, two receipts, and the
    only thing the log learned is the envelopes' digests."""
    log = _fixture_log()
    conn = _epoch_db(
        tmp_path,
        {("policy", 0): FIXTURE_HEAD, ("enforcement", 0): FIXTURE_HEAD},
    )
    client = FakeRekorClient(log)
    heads = commit.ChainHeads(declaration_head="ab" * 32, verdict_head="cd" * 32)
    made = _committer(conn, log, client)(heads)

    assert made.scheme == REKOR_SCHEME
    assert made.witness_id == REKOR_NAME
    assert made.heads == heads
    # The meta token is the last anchored receipt, base64.
    assert base64.b64decode(made.token) == _receipt_bytes(conn, "policy", 0)

    # One submission per epoch head, in (chain, epoch) order.
    assert len(client.seen) == 2
    receipts = anchor_rekor.anchor_receipts(conn)
    assert [(c, e) for c, e, _ in receipts] == [
        ("enforcement", 0),
        ("policy", 0),
    ]
    for _, _, receipt in receipts:
        doc = json.loads(receipt)
        assert doc["scheme"] == REKOR_SCHEME
        # The receipt carries the entry, the envelope and the pinned log key —
        # everything verification needs, and nothing else leaves the file.
        assert set(doc) == {"scheme", "entry", "envelope", "log"}
        assert doc["log"]["key_id"] == log.key_id.hex()
        envelope = json.loads(base64.b64decode(doc["envelope"]))
        statement = json.loads(base64.b64decode(envelope["payload"]))
        assert statement["_type"] == "https://in-toto.io/Statement/v1"
        assert statement["subject"][0]["digest"]["sha256"] == FIXTURE_HEAD.hex()


def _receipt_bytes(conn: sqlite3.Connection, role: str, epoch: int) -> bytes:
    row = conn.execute(
        "SELECT receipt FROM anchor_receipts WHERE chain = ? AND epoch = ? "
        "AND scheme = ?",
        (role, epoch, REKOR_SCHEME),
    ).fetchone()
    assert row is not None
    return bytes(row["receipt"])


def test_committer_refuses_a_response_for_a_different_digest(tmp_path: Path) -> None:
    """The log answered, but not for the digest it was sent: the build must
    not persist that as an anchor."""
    log = _fixture_log()
    conn = _epoch_db(tmp_path, {("policy", 0): FIXTURE_HEAD})
    other = hashlib.sha256(b"another-digest").digest()
    client = FakeRekorClient(log, digest_override=other)
    heads = commit.ChainHeads(declaration_head="ab" * 32, verdict_head="cd" * 32)
    with pytest.raises(RekorError, match="not SHA-256 over this receipt's envelope"):
        _committer(conn, log, client)(heads)
    assert anchor_rekor.anchor_receipts(conn) == []


def test_committer_refuses_garbage_response(tmp_path: Path) -> None:
    class GarbageClient(FakeRekorClient):
        def submit(self, request: bytes) -> bytes:
            return b"not json"

    log = _fixture_log()
    conn = _epoch_db(tmp_path, {("policy", 0): FIXTURE_HEAD})
    heads = commit.ChainHeads(declaration_head="ab" * 32, verdict_head="cd" * 32)
    with pytest.raises(RekorError, match="not JSON"):
        _committer(conn, log, GarbageClient(log))(heads)
    assert anchor_rekor.anchor_receipts(conn) == []


def test_committer_refuses_no_epoch_heads(tmp_path: Path) -> None:
    log = _fixture_log()
    conn = _epoch_db(tmp_path, {})
    heads = commit.ChainHeads(declaration_head="ab" * 32, verdict_head="cd" * 32)
    with pytest.raises(RekorError, match="no epoch heads"):
        _committer(conn, log)(heads)


def test_committer_validates_its_arguments(tmp_path: Path) -> None:
    log = _fixture_log()
    conn = _epoch_db(tmp_path, {("policy", 0): FIXTURE_HEAD})
    client = FakeRekorClient(log)
    with pytest.raises(RekorError, match="takes a RekorClient"):
        RekorV2Committer("not a client", conn, REKOR_NAME, key_pinner=lambda u: _pinned(log))  # type: ignore[arg-type]
    with pytest.raises(RekorError, match="takes a sqlite3.Connection"):
        RekorV2Committer(client, "not a connection", REKOR_NAME, key_pinner=lambda u: _pinned(log))  # type: ignore[arg-type]
    with pytest.raises(RekorError, match="rekor_name="):
        RekorV2Committer(client, conn, "  ", key_pinner=lambda u: _pinned(log))
    with pytest.raises(RekorError, match="key_pinner"):
        RekorV2Committer(client, conn, REKOR_NAME, key_pinner="not callable")  # type: ignore[arg-type]
    bad_args = dict(
        rekor=client,
        conn=conn,
        rekor_name=REKOR_NAME,
        key_pinner=lambda u: _pinned(log),
        scheme="something-else",
    )
    with pytest.raises(RekorError, match="not this one with"):
        RekorV2Committer(**bad_args)  # type: ignore[arg-type]


def test_http_client_refuses_cleartext() -> None:
    with pytest.raises(RekorError, match="https://"):
        HttpRekorClient("http://rekor.example.test")


def test_http_client_refuses_an_empty_request() -> None:
    client = HttpRekorClient("https://rekor.example.test")
    with pytest.raises(RekorError, match="non-empty"):
        client.submit(b"")


def test_scheme_is_registered() -> None:
    assert REKOR_SCHEME in commit.SCHEMES
    assert REKOR_SCHEME == "rekor-v2-inclusion-v1"


def test_rekor_statement_is_about_publication() -> None:
    text = commit.commitment_statement(REKOR_SCHEME, "Example Log")
    assert "transparency log" in text
    assert "publication" in text
    assert "Example Log" in text
    assert "only" in text and "32-byte heads" in text


def test_only_the_head_leaves_the_boundary(tmp_path: Path) -> None:
    """The log learns the envelope digest and nothing else: the request
    carries no record, no statement content beyond the head, no identity."""
    log = _fixture_log()
    conn = _epoch_db(tmp_path, {("policy", 0): FIXTURE_HEAD})
    client = FakeRekorClient(log)
    heads = commit.ChainHeads(declaration_head="ab" * 32, verdict_head="cd" * 32)
    _committer(conn, log, client)(heads)
    assert len(client.seen) == 1
    req = json.loads(client.seen[0])
    asked = req["hashedRekordRequestV002"]
    assert set(req) == {"hashedRekordRequestV002"}
    assert set(asked) == {"digest", "signature"}
    # The digest is 32 bytes; the statement content stays in the envelope,
    # which never leaves the operator boundary.
    assert len(base64.b64decode(asked["digest"])) == 32


# ---------------------------------------------------------------------------
# Cold read: anchor status per artifact.
# ---------------------------------------------------------------------------


def test_cold_read_reports_rekor_receipts_as_checkable(tmp_path: Path) -> None:
    """Rekor receipts carry everything their check needs, so the row is
    CHECKABLE — the file alone settles it."""
    log = _fixture_log()
    conn = _epoch_db(tmp_path, {("policy", 0): FIXTURE_HEAD})
    _anchor_all(conn, log)
    report = query.cold_read(conn)
    row = report[query.CLAIM_ANCHOR]
    assert row.state == query.CHECKABLE
    assert REKOR_SCHEME in row.detail
    assert "1 epoch heads" in row.detail


def test_cold_read_names_both_schemes_when_layered(tmp_path: Path) -> None:
    log = _fixture_log()
    conn = _epoch_db(tmp_path, {("policy", 0): FIXTURE_HEAD})
    _anchor_all(conn, log)
    store.store_anchor_receipt(conn, "policy", 0, "rfc3161-sha256-v1", b"fake-token")
    conn.commit()
    report = query.cold_read(conn)
    row = report[query.CLAIM_ANCHOR]
    assert row.state == query.CHECKABLE
    assert REKOR_SCHEME in row.detail
    assert "rfc3161-sha256-v1" in row.detail


# ---------------------------------------------------------------------------
# verify_commitment under the Rekor scheme, alone and layered.
# ---------------------------------------------------------------------------


def _rekor_meta(
    conn: sqlite3.Connection, heads: commit.ChainHeads, *, layered: bool = False
) -> None:
    """The meta block _write_commitment would have written for a Rekor commit."""
    schemes = (
        ["rfc3161-sha256-v1", REKOR_SCHEME] if layered else [REKOR_SCHEME]
    )
    store.put_meta(conn, commit.META_COMMITMENT, ",".join(schemes))
    for scheme in schemes:
        name = "fixture-test-tsa" if scheme != REKOR_SCHEME else REKOR_NAME
        store.put_meta(conn, f"{commit.META_COMMITMENT_WITNESS}:{scheme}", name)
        store.put_meta(
            conn, f"{commit.META_COMMITMENT_SIGNATURE}:{scheme}", "dG9rZW4="
        )
        store.put_meta(
            conn,
            f"{commit.META_COMMITMENT_STATEMENT}:{scheme}",
            commit.commitment_statement(scheme, name),
        )
    if not layered:
        # The historical un-suffixed keys a single-scheme build also writes.
        store.put_meta(conn, commit.META_COMMITMENT_WITNESS, REKOR_NAME)
        store.put_meta(conn, commit.META_COMMITMENT_SIGNATURE, "dG9rZW4=")
    store.put_meta(
        conn, commit.META_COMMITMENT_DECLARATION_HEAD, heads.declaration_head
    )
    store.put_meta(conn, commit.META_COMMITMENT_VERDICT_HEAD, heads.verdict_head)
    conn.commit()


# ---------------------------------------------------------------------------
# The layered seam: _write_commitment with several suppliers.
# ---------------------------------------------------------------------------


def _fake_supplier(scheme: str, witness_id: str):
    def run(heads: commit.ChainHeads) -> commit.Commitment:
        return commit.Commitment(
            scheme=scheme, witness_id=witness_id, heads=heads, token="dG9rZW4="
        )

    return run


def test_write_commitment_layers_schemes_in_canonical_order(tmp_path: Path) -> None:
    """Two suppliers, given in non-canonical order: meta[commitment] still
    lists them in SCHEMES order, with per-scheme keys and no un-suffixed
    keys for an old reader to misread."""
    from reg import graph

    conn = _epoch_db(tmp_path, {("policy", 0): FIXTURE_HEAD})
    graph._write_commitment(
        conn,
        [
            _fake_supplier(REKOR_SCHEME, REKOR_NAME),
            _fake_supplier("rfc3161-sha256-v1", "fixture-test-tsa"),
        ],
    )
    conn.commit()
    meta = dict(
        conn.execute("SELECT key, value FROM meta").fetchall()
    )
    assert meta[commit.META_COMMITMENT] == f"rfc3161-sha256-v1,{REKOR_SCHEME}"
    for scheme in ("rfc3161-sha256-v1", REKOR_SCHEME):
        assert f"{commit.META_COMMITMENT_WITNESS}:{scheme}" in meta
        assert f"{commit.META_COMMITMENT_SIGNATURE}:{scheme}" in meta
        assert f"{commit.META_COMMITMENT_STATEMENT}:{scheme}" in meta
    assert commit.META_COMMITMENT_WITNESS not in meta
    assert commit.META_COMMITMENT_SIGNATURE not in meta


def test_write_commitment_single_scheme_keeps_historical_keys(
    tmp_path: Path,
) -> None:
    """One supplier: the historical un-suffixed keys are written alongside
    the suffixed ones, so readers from before the per-scheme keys keep
    working on single-scheme artifacts."""
    from reg import graph

    conn = _epoch_db(tmp_path, {("policy", 0): FIXTURE_HEAD})
    graph._write_commitment(conn, [_fake_supplier(REKOR_SCHEME, REKOR_NAME)])
    conn.commit()
    meta = dict(conn.execute("SELECT key, value FROM meta").fetchall())
    assert meta[commit.META_COMMITMENT] == REKOR_SCHEME
    assert meta[commit.META_COMMITMENT_WITNESS] == REKOR_NAME
    assert meta[f"{commit.META_COMMITMENT_WITNESS}:{REKOR_SCHEME}"] == REKOR_NAME


def test_verify_commitment_rekor_scheme_catches_moved_heads(tmp_path: Path) -> None:
    """The recorded heads are not what this artifact's records produce:
    INVALID before any proof is looked at."""
    log = _fixture_log()
    conn = _epoch_db(tmp_path, {("policy", 0): FIXTURE_HEAD})
    _anchor_all(conn, log)
    heads = commit.ChainHeads(declaration_head="ab" * 32, verdict_head="cd" * 32)
    _rekor_meta(conn, heads)
    check = commit.verify_commitment(conn, None)
    assert check.state is commit.CommitmentState.INVALID
    assert "moved" in check.reason


def test_verify_commitment_rekor_scheme_verifies_offline(tmp_path: Path) -> None:
    log = _fixture_log()
    conn = _epoch_db(tmp_path, {("policy", 0): FIXTURE_HEAD})
    _anchor_all(conn, log)
    heads = commit.ChainHeads(
        declaration_head=chain.GENESIS_HASH, verdict_head=chain.GENESIS_HASH
    )
    _rekor_meta(conn, heads)
    check = commit.verify_commitment(conn, None)
    assert check.state is commit.CommitmentState.VALID, check.reason
    assert REKOR_SCHEME in (check.scheme or "")


def test_verify_commitment_layered_checks_both_schemes(tmp_path: Path) -> None:
    """A layered artifact names both schemes; each is checked independently."""
    log = _fixture_log()
    conn = _epoch_db(tmp_path, {("policy", 0): FIXTURE_HEAD})
    _anchor_all(conn, log)
    heads = commit.ChainHeads(
        declaration_head=chain.GENESIS_HASH, verdict_head=chain.GENESIS_HASH
    )
    _rekor_meta(conn, heads, layered=True)
    # The TSA receipt is a fake token that does not parse: the TSA leg is
    # could-not-evaluate, the Rekor leg is valid, so the whole is
    # could-not-evaluate — never valid while a leg is unchecked.
    store.store_anchor_receipt(conn, "policy", 0, "rfc3161-sha256-v1", b"fake-token")
    conn.commit()
    check = commit.verify_commitment(conn, None, tsa_roots=[])
    assert check.state is commit.CommitmentState.COULD_NOT_EVALUATE
    assert "rfc3161-sha256-v1" in check.scheme
    assert REKOR_SCHEME in check.scheme


def test_verify_commitment_layered_invalid_if_either_leg_is_invalid(
    tmp_path: Path,
) -> None:
    log = _fixture_log()
    conn = _epoch_db(tmp_path, {("policy", 0): FIXTURE_HEAD})
    _anchor_all(conn, log)
    conn.execute(
        "UPDATE epoch_heads SET head = ? WHERE chain = 'policy' AND epoch = 0",
        (hashlib.sha256(b"something-else").digest(),),
    )
    heads = commit.ChainHeads(
        declaration_head=chain.GENESIS_HASH, verdict_head=chain.GENESIS_HASH
    )
    _rekor_meta(conn, heads, layered=True)
    check = commit.verify_commitment(conn, None, tsa_roots=[])
    assert check.state is commit.CommitmentState.INVALID
