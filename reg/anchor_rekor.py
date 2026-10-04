"""Rekor v2 transparency-log anchoring for epoch heads. **Layer A** — part of the record.

WHAT THIS MODULE IS
-------------------
`reg.commit` proves a second on-site party saw the chain heads.
`reg.anchor_tsa` proves the epoch heads existed by a real instant, to a
timestamp authority with no relationship to the operator. This module proves
the epoch heads were **published**: at artifact close, every closed epoch
head — 32 bytes, and the only thing that ever leaves the operator boundary —
is named as the subject of an in-toto v1 statement, wrapped in a DSSE
envelope, and the envelope's SHA-256 digest is submitted to a Rekor v2
transparency log as a hashedrekord entry. Rekor v2 answers only once the
entry is integrated, so the response already carries the signed inclusion
proof; the proof is persisted in the artifact's `anchor_receipts` table as
canonical JSON.

WHY A LOG, GIVEN THE TIMESTAMP
------------------------------
The TSA says "this head existed by this instant" — a private attestation
between the operator and the authority. The log says "this head was
published": anyone holding the log can see the entry, and a history re-issued
offline cannot retroactively insert itself into a log whose checkpoints the
world already saw. The two are layered, not alternative — an artifact may
carry both, each independently verifiable — and `docs/limitations.md` §6 says
where each stops.

WHAT IT NEEDS FROM THE WORLD, AND WHEN
--------------------------------------
One log submission per epoch head, at artifact close only, through a
`RekorClient`. Verification is file I/O plus crypto: each receipt carries the
log's entry, the DSSE envelope it was built from, and the log's public key —
pinned from the TUF trusted root at anchor time and stored with the proof, per
the design doc's §7. No service, no network, ever, at verify time: the
artifact must check years later with nothing still running, so anchoring is a
close-time operation and nothing about verification phones home.

A NOTE ON THE SUBMITTER KEY
---------------------------
Rekor v2's hashedrekord entries carry a signature and a verifier key, and the
envelope they are built from is a signed DSSE envelope. This adapter signs
each envelope with an **ephemeral ECDSA P-256 key generated at close** — pure
Ed25519 has no externalized prehash and cannot back a hashedrekord entry
(rekor-v2-spec §6.1.4, enforced by sigstore's own client). The key is
discarded after the build; it carries no identity claim. What the anchor
proves does not depend on it: the log's inclusion proof and checkpoint are
what defeat the re-issuer, and the receipt lets a verifier check the whole
chain — envelope signature against the entry's verifier key, entry digest
against the envelope, inclusion proof against the checkpoint, checkpoint
against the pinned log key.

A NOTE ON THE SHAPE OF THE ENTRY
--------------------------------
Rekor v2 speaks only hashedrekord (`HashedRekordLogEntryV002`); there is no
DSSE entry type. The adapter follows the client specification
(sigstore/rekor-tiles CLIENTS.md): the request carries `digest =
SHA-256(PAE(envelope))` with the envelope's own signature, and the response's
`canonicalizedBody` is the entry the log stored — kind `hashedrekord`,
apiVersion `0.0.2` — whose leaf hash the inclusion proof is over. A response
that does not parse as that shape is refused at anchor time and reported as
could-not-evaluate at verify time, never silently accepted.

A NOTE ON WIRING
----------------
`RekorV2Committer` implements the `(ChainHeads) -> Commitment` seam from
`reg.commit`, but like `Rfc3161Committer` it needs the artifact connection to
read the epoch heads it anchors and to persist the receipts. It is built at
close time by `reg.graph.build`, which takes `rekor_client=` / `rekor_name=`
beside the TSA's `tsa_client=` / `tsa_name=`; the two anchor adapters compose,
and passing `commitment=` with either is refused — `meta[commitment]` names
every scheme that ran, and the witness is a different kind of claim.

OPERATIONAL NOTES
-----------------
* **Rate limits.** Rekor v2 blocks each submission until the entry is
  integrated under a published checkpoint, so a close anchors one epoch at a
  time and each request can take tens of seconds — longer under load. The
  client's default timeout is two minutes per epoch; a close over many epochs
  is slow, and that is the log's pacing, not this adapter's.
* **Shard rotation.** Rekor v2 shards rotate roughly every six months, each
  shard with its own URL and checkpoint key. The adapter pins the key of the
  shard it wrote to, from the TUF trusted root, at anchor time; a verifier
  years later checks the proof against the pinned key, never against a live
  root. If the pin cannot be made — the TUF root names no log at the client's
  URL — the build is refused rather than anchoring to a log nobody can name.
* **Self-hosted logs.** The client takes any Rekor v2 base URL, and the pin
  takes any TUF repository URL; a sovereign deployment points both at its own
  infrastructure and the artifact stays verifiable the same way.

THE THREE STATES
----------------
`verify_anchors` reports per epoch and overall, the same three outcomes
`reg.anchor_tsa` reports and for the same reason:

* **VALID** — every closed epoch's receipt parses, its entry's digest is
  SHA-256 over the PAE of the receipt's envelope, the envelope's statement
  names this artifact's epoch head, the envelope signature verifies against
  the entry's verifier key, the inclusion proof chains to its root hash, and
  the checkpoint signature verifies against the pinned log key with the
  checkpoint's root hash equal to the proof's.
* **INVALID** — a definite fault: any of the checks above fails on bytes that
  parsed.
* **COULD-NOT-EVALUATE** — the check could not run: no receipts at all, an
  epoch with no receipt, a receipt or entry that does not parse, an entry of
  an unknown kind, or no log key pinned in the receipt. Never resolves to
  VALID.

A verifier that does not trust the artifact's word for the log key compares
the pinned key against the published TUF trusted root out of band: the entry's
log id binds the proof to the key id, so a receipt that borrowed the real
log's identity without its signature fails the checkpoint check rather than
passing under a substituted key.
"""

from __future__ import annotations

import abc
import base64
import dataclasses
import hashlib
import json
import sqlite3
import urllib.request
from enum import Enum
from pathlib import Path
from typing import Callable

from reg import store
from reg.commit import REKOR_SCHEME, ChainHeads, Commitment

__all__ = [
    "REKOR_SCHEME",
    "AnchorCheck",
    "AnchorState",
    "EpochAnchor",
    "HttpRekorClient",
    "PinnedLogKey",
    "RekorClient",
    "RekorError",
    "RekorV2Committer",
    "anchor_receipts",
    "pin_log_key",
    "verify_anchors",
]

#: The in-toto statement type every envelope carries. The statement is
#: reg's own shape — the log stores only its digest — and the type URI is
#: what makes the anchored thing legible as an epoch-head attestation rather
#: than an opaque 32 bytes.
_STATEMENT_TYPE = "https://in-toto.io/Statement/v1"
_PREDICATE_TYPE = "https://reg.dev/attestations/epoch-head/v1"
_PAYLOAD_TYPE = "application/vnd.in-toto+json"

#: The entry kind this adapter writes and the only one it reads. A receipt
#: naming another kind is one this reader was not built for.
_ENTRY_KIND = "hashedrekord"
_ENTRY_API_VERSION = "0.0.2"

#: Key algorithms this reader can verify a checkpoint against — the set
#: sigstore's own keyring loads, by enum name so no import is needed to name
#: them. A pinned key under any other algorithm is a check that cannot run,
#: not a failed check.
_KEYRING_ALGORITHMS = frozenset(
    {
        "PKIX_RSA_PKCS1V15_2048_SHA256",
        "PKIX_RSA_PKCS1V15_3072_SHA256",
        "PKIX_RSA_PKCS1V15_4096_SHA256",
        "PKIX_ECDSA_P256_SHA_256",
        "PKIX_ECDSA_P384_SHA_384",
        "PKIX_ECDSA_P521_SHA_512",
        "PKIX_ED25519",
    }
)


class RekorError(Exception):
    """An anchor that will not be made, or a log exchange that failed.

    Always loud, never a substitution — the same rule `reg.anchor_tsa`
    states: an artifact carrying a receipt nobody can check is worse than
    one carrying none, because only the second says so. A failed submission
    refuses the build rather than recording a gap as an anchor.
    """


class _CannotCheck(RekorError):
    """The anchor check could not run, as opposed to failing.

    A receipt that parses but names something this reader cannot evaluate —
    an unknown key algorithm, a missing pinned key — is a finding about the
    check, and `verify_anchors` reports it as COULD-NOT-EVALUATE, never as
    INVALID and never as VALID.
    """


def _canonical(obj: object) -> bytes:
    """Canonical JSON: sorted keys, no whitespace. Deterministic bytes for
    every receipt the artifact stores."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _statement_bytes(chain: str, epoch: int, head: bytes) -> bytes:
    """The in-toto v1 statement naming one epoch head, as canonical bytes."""
    return _canonical(
        {
            "_type": _STATEMENT_TYPE,
            "predicateType": _PREDICATE_TYPE,
            "subject": [{"name": "epoch-head", "digest": {"sha256": head.hex()}}],
            "predicate": {
                "chain": chain,
                "epoch": epoch,
                "epochHead": head.hex(),
                "commitmentScheme": REKOR_SCHEME,
            },
        }
    )


def _pae(payload_type: str, payload: bytes) -> bytes:
    """The DSSE Pre-Authentication Encoding over a payload type and payload.

    `"DSSEv1" || len(type) || type || len(payload) || payload`, lengths as
    ASCII decimal — the same encoding sigstore's client hashes for the
    hashedrekord digest, so the digest this adapter submits is the digest the
    log's own clients would compute.
    """
    return (
        b"DSSEv1 "
        + str(len(payload_type)).encode("ascii")
        + b" "
        + payload_type.encode("ascii")
        + b" "
        + str(len(payload)).encode("ascii")
        + b" "
        + payload
    )


def _sign_envelope(statement: bytes) -> tuple[bytes, bytes, bytes]:
    """Sign a statement's PAE with an ephemeral ECDSA P-256 key.

    Returns `(envelope_json, signature, public_key_der)`: the DSSE envelope as
    canonical JSON bytes, the raw signature over the PAE, and the signer's
    DER SubjectPublicKeyInfo. The key is generated here and discarded on
    return — it authenticates the submission to the log and nothing else;
    see the module docstring's note on the submitter key.
    """
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.serialization import (
        Encoding,
        PublicFormat,
    )

    private_key = ec.generate_private_key(ec.SECP256R1())
    pae = _pae(_PAYLOAD_TYPE, statement)
    signature = private_key.sign(pae, ec.ECDSA(hashes.SHA256()))
    public_der = private_key.public_key().public_bytes(
        Encoding.DER, PublicFormat.SubjectPublicKeyInfo
    )
    envelope = _canonical(
        {
            "payload": base64.b64encode(statement).decode("ascii"),
            "payloadType": _PAYLOAD_TYPE,
            "signatures": [{"sig": base64.b64encode(signature).decode("ascii")}],
        }
    )
    return envelope, signature, public_der


def _entry_request(digest: bytes, signature: bytes, public_der: bytes) -> bytes:
    """The Rekor v2 `CreateEntryRequest` for one envelope, as JSON bytes.

    Built through sigstore's own request models, so a malformed request is a
    local `ValueError` rather than a confusing rejection from the log.
    """
    from sigstore_models.common import v1 as common_v1
    from sigstore_models.rekor import v2 as rekor_v2

    request = rekor_v2.entry.CreateEntryRequest(
        hashed_rekord_request_v002=rekor_v2.hashedrekord.HashedRekordRequestV002(
            # ProtoBytes takes base64 on the way in and gives raw bytes back.
            digest=base64.b64encode(digest).decode("ascii"),
            signature=rekor_v2.verifier.Signature(
                content=base64.b64encode(signature).decode("ascii"),
                verifier=rekor_v2.verifier.Verifier(
                    public_key=rekor_v2.verifier.PublicKey(
                        raw_bytes=base64.b64encode(public_der).decode("ascii")
                    ),
                    key_details=common_v1.PublicKeyDetails.PKIX_ECDSA_P256_SHA_256,
                ),
            ),
        )
    )
    return request.to_json().encode("utf-8")


class RekorClient(abc.ABC):
    """The one log submission, behind an interface so tests never make it.

    `submit` takes a hashedrekord `CreateEntryRequest` (JSON) and returns the
    response body — the integrated `TransparencyLogEntry` (JSON). Rekor v2
    blocks until the entry is under a published checkpoint, so a returned
    response already carries the inclusion proof; the committer still verifies
    every byte of it before anything is persisted.
    """

    @property
    @abc.abstractmethod
    def base_url(self) -> str:
        """The log's base URL, e.g. `https://rekor.sigstore.dev`."""

    @abc.abstractmethod
    def submit(self, request: bytes) -> bytes:
        """Submit one entry request; return the entry response body.

        Raises:
            RekorError: the exchange failed, or the response is empty.
        """


class HttpRekorClient(RekorClient):
    """A `RekorClient` over HTTPS to a real Rekor v2 log.

    POSTs the request to `{base_url}/api/v2/log/entries` and returns the
    response body untouched — validation happens in the committer, against the
    parsed entry, not against the HTTP layer. The default timeout is two
    minutes: the log blocks each submission until the entry is integrated,
    and the client specification tells clients to allow at least twenty
    seconds.
    """

    def __init__(self, url: str, *, timeout_s: float = 120.0) -> None:
        if not isinstance(url, str) or not url.startswith("https://"):
            raise RekorError(
                f"Rekor url must be an https:// URL, got {url!r}. An entry "
                "submitted over cleartext is submitted to whoever answered."
            )
        if not isinstance(timeout_s, (int, float)) or timeout_s <= 0:
            raise RekorError(f"timeout_s must be positive, got {timeout_s!r}.")
        self._url = url.rstrip("/")

    @property
    def base_url(self) -> str:
        return self._url

    def submit(self, request: bytes) -> bytes:
        if not isinstance(request, bytes) or not request:
            raise RekorError(
                "a Rekor submission is non-empty request JSON, got "
                f"{type(request).__name__}."
            )
        http_request = urllib.request.Request(
            f"{self._url}/api/v2/log/entries",
            data=request,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(http_request, timeout=self._timeout_s) as resp:
                body = resp.read()
        except Exception as exc:  # noqa: BLE001 - transport failure is transport failure
            raise RekorError(
                f"the Rekor exchange with {self._url} failed: {exc}. Refusing "
                "rather than recording a gap as an anchor."
            ) from None
        if not body:
            raise RekorError(f"the Rekor log at {self._url} returned an empty response.")
        return body


@dataclasses.dataclass(frozen=True)
class PinnedLogKey:
    """A transparency log's checkpoint key, pinned at anchor time.

    Carried in every receipt so verification needs no live trusted root: the
    key id binds the entry's log id to this key, and the checkpoint signature
    is checked against it years later. A verifier that does not trust the
    artifact's word for the key compares these bytes against the published
    TUF trusted root out of band.
    """

    #: The log's base URL, as the TUF trusted root states it.
    base_url: str
    #: The operator named by the trusted root, if it names one.
    operator: str | None
    #: Hex of the log's key id — the non-truncated C2SP checkpoint key id the
    #: entry's log id must equal.
    key_id_hex: str
    #: DER SubjectPublicKeyInfo of the checkpoint key.
    public_key_der: bytes
    #: sigstore algorithm name, e.g. `PKIX_ECDSA_P256_SHA_256`.
    key_details: str


def pin_log_key(base_url: str, *, tuf_url: str | None = None) -> PinnedLogKey:
    """Pin a Rekor v2 log's checkpoint key from the TUF trusted root.

    Fetches the trusted root over TUF (network, at anchor time — never at
    verify time) and returns the key of the transparency-log instance whose
    base URL matches. If the root names no such log, the build is refused:
    anchoring to a log nobody can name would write receipts no verifier could
    place.

    The import is local so that importing this module never requires sigstore:
    reading an artifact — including a cold read of its anchor rows — must work
    where no Rekor dependency is installed.
    """
    from sigstore._internal.tuf import DEFAULT_TUF_URL, TrustUpdater
    from sigstore_models.trustroot import v1 as trustroot_v1

    if not isinstance(base_url, str) or not base_url.startswith("https://"):
        raise RekorError(
            f"cannot pin a log key for {base_url!r}: not an https:// URL."
        )
    try:
        updater = TrustUpdater(tuf_url or DEFAULT_TUF_URL)
        path = updater.get_trusted_root_path()
    except Exception as exc:  # noqa: BLE001 - TUF fetch failed
        raise RekorError(
            f"the TUF trusted root could not be fetched: {exc}. Without it "
            "there is no key to pin, and an unpinned anchor is refused."
        ) from None
    try:
        root = trustroot_v1.TrustedRoot.from_json(Path(path).read_bytes())
    except Exception as exc:  # noqa: BLE001 - malformed trusted root
        raise RekorError(
            f"the fetched trusted root does not parse: {exc}."
        ) from None
    want = base_url.rstrip("/")
    for tlog in root.tlogs:
        if tlog.base_url.rstrip("/") != want:
            continue
        public_key = tlog.public_key
        if not public_key.raw_bytes:
            continue
        key_id = tlog.checkpoint_key_id or tlog.log_id
        return PinnedLogKey(
            base_url=tlog.base_url,
            operator=tlog.operator,
            key_id_hex=key_id.key_id.hex(),
            public_key_der=public_key.raw_bytes,
            key_details=public_key.key_details.name,
        )
    raise RekorError(
        f"the TUF trusted root names no transparency log at {base_url!r}. "
        "Refusing: a receipt for a log nobody can name is a receipt nobody "
        "can check."
    )


def _parse_entry(response: bytes):
    """Parse a log response into sigstore's `TransparencyLogEntry`.

    Raises `RekorError` — at anchor time a response that does not parse is a
    refused submission; at verify time the caller maps it to
    could-not-evaluate.
    """
    from sigstore.models import TransparencyLogEntry
    from sigstore_models.rekor.v1 import TransparencyLogEntry as _Inner

    try:
        payload = json.loads(response)
    except (ValueError, UnicodeDecodeError) as exc:
        raise RekorError(f"the log response is not JSON: {exc}.") from None
    if not isinstance(payload, dict):
        raise RekorError(
            "the log response is not a JSON object, so it is not a "
            "TransparencyLogEntry."
        )
    try:
        return TransparencyLogEntry(_Inner.from_dict(payload))
    except Exception as exc:  # noqa: BLE001 - pydantic validation
        raise RekorError(
            f"the log response does not parse as a TransparencyLogEntry: {exc}."
        ) from None


def _entry_digest(entry) -> bytes:
    """The hashedrekord digest the log stored for this entry.

    Parsed out of the entry's `canonicalizedBody` — the entry the log
    actually stored, which is what the inclusion proof's leaf hash is over.
    Anything that is not a hashedrekord v0.0.2 entry is refused: this reader
    was built for one kind, and the client specification says to fail
    gracefully on any other.
    """
    from sigstore_models.rekor import v2 as rekor_v2

    body = entry._inner.canonicalized_body
    try:
        stored = rekor_v2.entry.Entry.from_json(body)
    except Exception as exc:  # noqa: BLE001 - pydantic validation
        raise RekorError(
            f"the entry's canonicalized body does not parse: {exc}."
        ) from None
    if stored.kind != _ENTRY_KIND or stored.api_version != _ENTRY_API_VERSION:
        raise _CannotCheck(
            f"the entry is kind {stored.kind!r} version "
            f"{stored.api_version!r}, not {_ENTRY_KIND!r} "
            f"{_ENTRY_API_VERSION!r}. This reader was built for one kind, "
            "and the client specification says to fail gracefully on any "
            "other."
        )
    record = stored.spec.hashed_rekord_v002
    if record is None:  # pragma: no cover - the kind check above excludes this
        raise RekorError("the entry has no hashedrekord v0.0.2 body.")
    from sigstore_models.common import v1 as common_v1

    if record.data.algorithm != common_v1.HashAlgorithm.SHA2_256:
        raise RekorError(
            f"the entry's digest is under {record.data.algorithm}, not "
            "SHA2_256. This adapter submits SHA-256 and reads SHA-256."
        )
    return record.data.digest


def _check_entry_binds_envelope(entry, envelope: bytes, head: bytes) -> None:
    """Refuse an entry that is not an anchor for this epoch's head.

    Three bindings, each checked: the entry's stored digest is SHA-256 over
    the PAE of the envelope the receipt carries; the envelope's statement
    names this artifact's epoch head; the envelope's signature verifies
    against the entry's own verifier key. Raises `RekorError`.
    """
    digest = _entry_digest(entry)
    try:
        envelope_doc = json.loads(envelope)
    except (ValueError, UnicodeDecodeError) as exc:
        raise RekorError(f"the receipt's envelope is not JSON: {exc}.") from None
    if not isinstance(envelope_doc, dict):
        raise RekorError("the receipt's envelope is not a JSON object.")
    try:
        payload = base64.b64decode(envelope_doc["payload"])
        payload_type = envelope_doc["payloadType"]
        signature = base64.b64decode(envelope_doc["signatures"][0]["sig"])
    except (KeyError, IndexError, ValueError, TypeError) as exc:
        raise RekorError(
            f"the receipt's envelope is not a DSSE envelope: {exc}."
        ) from None
    if payload_type != _PAYLOAD_TYPE:
        raise RekorError(
            f"the envelope's payload type is {payload_type!r}, not "
            f"{_PAYLOAD_TYPE!r}."
        )
    if digest != hashlib.sha256(_pae(payload_type, payload)).digest():
        raise RekorError(
            "the entry's digest is not SHA-256 over this receipt's envelope. "
            "The envelope, the entry, or the receipt row is not the one that "
            "was anchored."
        )
    try:
        statement = json.loads(payload)
    except (ValueError, UnicodeDecodeError) as exc:
        raise RekorError(f"the envelope's payload is not JSON: {exc}.") from None
    if (
        not isinstance(statement, dict)
        or statement.get("_type") != _STATEMENT_TYPE
        or statement.get("predicateType") != _PREDICATE_TYPE
    ):
        raise RekorError(
            "the envelope does not carry this adapter's in-toto statement."
        )
    subjects = statement.get("subject")
    if (
        not isinstance(subjects, list)
        or not subjects
        or not isinstance(subjects[0], dict)
        or subjects[0].get("digest", {}).get("sha256") != head.hex()
    ):
        raise RekorError(
            "the envelope's statement does not name this artifact's epoch "
            "head. The head, the envelope, or the receipt row is not the one "
            "that was anchored."
        )
    _check_envelope_signature(entry, signature, _pae(payload_type, payload))


def _check_envelope_signature(entry, signature: bytes, pae: bytes) -> None:
    """The envelope's signature verifies against the entry's verifier key."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.serialization import load_der_public_key
    from sigstore_models.common import v1 as common_v1

    body = entry._inner.canonicalized_body
    from sigstore_models.rekor import v2 as rekor_v2

    stored = rekor_v2.entry.Entry.from_json(body)
    verifier = stored.spec.hashed_rekord_v002.signature.verifier
    if verifier.public_key is None or verifier.public_key.raw_bytes is None:
        raise RekorError(
            "the entry's verifier is not a raw public key. This adapter "
            "submits raw-key verifiers and reads raw-key verifiers."
        )
    if (
        verifier.key_details
        != common_v1.PublicKeyDetails.PKIX_ECDSA_P256_SHA_256
    ):
        raise RekorError(
            f"the entry's verifier key is {verifier.key_details}, not "
            "PKIX_ECDSA_P256_SHA_256. This adapter submits ECDSA P-256 and "
            "reads ECDSA P-256."
        )
    try:
        public_key = load_der_public_key(verifier.public_key.raw_bytes)
    except Exception as exc:  # noqa: BLE001 - malformed key
        raise RekorError(
            f"the entry's verifier key does not parse: {exc}."
        ) from None
    if not isinstance(public_key, ec.EllipticCurvePublicKey):
        raise RekorError("the entry's verifier key is not an EC public key.")
    try:
        public_key.verify(signature, pae, ec.ECDSA(hashes.SHA256()))
    except InvalidSignature as exc:
        raise RekorError(
            "the envelope's signature does not verify against the entry's "
            "verifier key."
        ) from None


def _check_inclusion_proof(entry) -> None:
    """The inclusion proof chains the entry's leaf to its root hash.

    Pure Merkle math (RFC 6962) — no trust involved. Raises `RekorError`.
    """
    from sigstore._internal.merkle import verify_merkle_inclusion
    from sigstore.errors import VerificationError

    try:
        verify_merkle_inclusion(entry)
    except VerificationError as exc:
        raise RekorError(
            f"the entry's inclusion proof does not chain to its root hash: "
            f"{exc}"
        ) from None


def _check_checkpoint(entry, log_key: PinnedLogKey) -> None:
    """The checkpoint signature verifies against the pinned log key.

    Raises `RekorError` on a bad signature (a finding about the artifact)
    and `_CannotCheck` where the check cannot run (a finding about the
    check).
    """
    from sigstore._internal.rekor.checkpoint import verify_checkpoint
    from sigstore._internal.trust import Keyring, RekorKeyring
    from sigstore.errors import VerificationError
    from sigstore_models.common import v1 as common_v1

    try:
        key_details = common_v1.PublicKeyDetails[log_key.key_details]
    except KeyError as exc:  # defensive: _pinned_key_from_receipt checks this
        raise _CannotCheck(
            f"the pinned log key names an unknown algorithm "
            f"{log_key.key_details!r}."
        ) from None
    if key_details.name not in _KEYRING_ALGORITHMS:
        raise _CannotCheck(
            f"the pinned log key is {key_details}, which this reader cannot "
            "verify signatures against."
        )
    try:
        public_key = common_v1.PublicKey(
            # ProtoBytes takes base64 on the way in.
            raw_bytes=base64.b64encode(log_key.public_key_der).decode("ascii"),
            key_details=key_details,
        )
        keyring = RekorKeyring(Keyring([public_key]))
    except Exception as exc:  # noqa: BLE001 - malformed key
        raise _CannotCheck(
            f"the pinned log key does not parse: {exc}."
        ) from None
    try:
        verify_checkpoint(keyring, entry)
    except VerificationError as exc:
        raise RekorError(
            f"the entry's checkpoint does not verify against the pinned log "
            f"key: {exc}"
        ) from None


@dataclasses.dataclass(frozen=True)
class RekorV2Committer:
    """The Rekor `Committer`: one log entry per closed epoch head.

    Call it with a `ChainHeads` and it anchors every epoch head the artifact
    holds — `(chain, epoch)` rows from `epoch_heads`, in `(chain, epoch)`
    order — persists each inclusion proof to `anchor_receipts` as canonical
    JSON, and returns a `Commitment` under `rekor-v2-inclusion-v1`. The
    `token` on that commitment is the base64 of the *last* anchored receipt;
    per-epoch verification reads `anchor_receipts`, where every proof lives.

    `conn` is the artifact connection the build is writing: the committer
    reads the epoch heads it anchors from it and persists the receipts to it,
    in the build's own transaction, so a failed anchor refuses the build
    rather than leaving a half-anchored file.

    `key_pinner` resolves the log's checkpoint key from the TUF trusted root
    at close time; it is a parameter (defaulting to the real fetch) so tests
    pin a fixture key without touching the network.
    """

    rekor: RekorClient
    conn: sqlite3.Connection
    rekor_name: str
    key_pinner: Callable[[str], PinnedLogKey] = pin_log_key

    #: Named on the class so a caller can report which scheme it is about to
    #: use without having to run it.
    scheme: str = REKOR_SCHEME

    def __post_init__(self) -> None:
        if not isinstance(self.rekor, RekorClient):
            raise RekorError(
                f"RekorV2Committer takes a RekorClient, got "
                f"{type(self.rekor).__name__}."
            )
        if not isinstance(self.conn, sqlite3.Connection):
            raise RekorError(
                f"RekorV2Committer takes a sqlite3.Connection, got "
                f"{type(self.conn).__name__}."
            )
        if not isinstance(self.rekor_name, str) or not self.rekor_name.strip():
            raise RekorError(
                f"rekor_name={self.rekor_name!r}. The whole content of this "
                "scheme is *which transparency log* the heads were published "
                "to, so a committer with no name commits nothing anybody can "
                "check."
            )
        if not callable(self.key_pinner):
            raise RekorError(
                f"key_pinner={self.key_pinner!r} is not callable."
            )
        if self.scheme != REKOR_SCHEME:
            raise RekorError(
                f"a RekorV2Committer is {REKOR_SCHEME!r}, not {self.scheme!r}. "
                "A different scheme is a different adapter, not this one with "
                "a different label on it."
            )

    def __call__(self, heads: ChainHeads) -> Commitment:
        rows = self.conn.execute(
            "SELECT chain, epoch, head FROM epoch_heads ORDER BY chain, epoch"
        ).fetchall()
        if not rows:
            raise RekorError(
                "the artifact holds no epoch heads, so there is nothing to "
                "anchor. A commitment over zero epochs would verify and mean "
                "nothing."
            )
        log_key = self.key_pinner(self.rekor.base_url)
        receipts: list[bytes] = []
        for row in rows:
            chain = str(row["chain"])
            epoch = int(row["epoch"])
            head = bytes(row["head"])
            if len(head) != 32:
                raise RekorError(
                    f"epoch {epoch} of the {chain!r} chain holds a "
                    f"{len(head)}-byte head. Only 32-byte heads leave the "
                    "operator boundary."
                )
            receipt = self._anchor_one(chain, epoch, head, log_key)
            receipts.append(receipt)
        return Commitment(
            scheme=self.scheme,
            witness_id=self.rekor_name,
            heads=heads,
            token=base64.b64encode(receipts[-1]).decode("ascii"),
        )

    def _anchor_one(
        self, chain: str, epoch: int, head: bytes, log_key: PinnedLogKey
    ) -> bytes:
        """Anchor one epoch head: submit, verify the response, persist."""
        statement = _statement_bytes(chain, epoch, head)
        envelope, signature, public_der = _sign_envelope(statement)
        digest = hashlib.sha256(_pae(_PAYLOAD_TYPE, statement)).digest()
        request = _entry_request(digest, signature, public_der)
        response = self.rekor.submit(request)
        entry = _parse_entry(response)
        _check_entry_binds_envelope(entry, envelope, head)
        _check_inclusion_proof(entry)
        _check_checkpoint(entry, log_key)
        receipt = _canonical(
            {
                "scheme": REKOR_SCHEME,
                "entry": json.loads(response),
                "envelope": base64.b64encode(envelope).decode("ascii"),
                "log": {
                    "base_url": log_key.base_url,
                    "operator": log_key.operator,
                    "key_id": log_key.key_id_hex,
                    "public_key_der": base64.b64encode(
                        log_key.public_key_der
                    ).decode("ascii"),
                    "key_details": log_key.key_details,
                },
            }
        )
        store.store_anchor_receipt(self.conn, chain, epoch, REKOR_SCHEME, receipt)
        return receipt


@dataclasses.dataclass(frozen=True)
class EpochAnchor:
    """One epoch's anchor, as checked: which epoch, what was found."""

    chain: str
    epoch: int
    state: "AnchorState"
    reason: str


class AnchorState(Enum):
    """The three outcomes of an anchor check. No fourth, and no bool.

    The same three `reg.commit.CommitmentState` has, for the same reason:
    `INVALID` is a finding about the artifact, `COULD_NOT_EVALUATE` is a
    finding about the *check*, and an unchecked anchor must never read as a
    checked one.
    """

    #: Every closed epoch's proof parses, names this artifact's epoch head,
    #: and chains to a checkpoint signed by the pinned log key.
    VALID = "VALID"
    #: A definite fault: an entry's digest is not this artifact's envelope, a
    #: statement does not name its head, or a proof or checkpoint does not
    #: verify.
    INVALID = "INVALID"
    #: Nothing was learned: no receipts, an epoch with no receipt, a receipt
    #: or entry that does not parse, an entry of an unknown kind, or no log
    #: key pinned in the receipt. **Never resolves to VALID.**
    COULD_NOT_EVALUATE = "COULD-NOT-EVALUATE"


@dataclasses.dataclass(frozen=True)
class AnchorCheck:
    """The result of `verify_anchors`: a state, the reason, and the per-epoch
    findings.

    `bool(check)` raises, for `reg.commit.CommitmentCheck.__bool__`'s reason:
    `if verify_anchors(...)` reads as "is this artifact anchored", and an
    artifact whose proofs nobody checked is neither yes nor no.
    """

    state: AnchorState
    reason: str
    epochs: tuple[EpochAnchor, ...] = ()

    def __bool__(self) -> bool:  # pragma: no cover - exercised via pytest.raises
        raise TypeError(
            "an AnchorCheck has three states and cannot be used as a bool. "
            f"This one is {self.state.value}: {self.reason}. Compare .state "
            "against AnchorState.VALID / INVALID / COULD_NOT_EVALUATE."
        )

    def describe(self) -> str:
        """One line: the verdict and why."""
        return f"{self.state.value} [{REKOR_SCHEME}]: {self.reason}"


def anchor_receipts(
    conn: sqlite3.Connection, *, scheme: str = REKOR_SCHEME
) -> list[tuple[str, int, bytes]]:
    """Every anchor receipt under `scheme`: `(chain, epoch, receipt JSON)`."""
    try:
        rows = conn.execute(
            "SELECT chain, epoch, receipt FROM anchor_receipts "
            "WHERE scheme = ? ORDER BY chain, epoch",
            (scheme,),
        ).fetchall()
    except sqlite3.OperationalError:
        # An artifact from before the table existed holds no receipts, which
        # is a fact about the file and not a fault in it.
        return []
    return [(str(r["chain"]), int(r["epoch"]), bytes(r["receipt"])) for r in rows]


def _pinned_key_from_receipt(receipt: dict) -> PinnedLogKey:
    """The log key a receipt pins, or raise.

    A missing or malformed pinned key is `_CannotCheck`: the receipt parses
    but the check cannot run without the key it was supposed to carry.
    """
    from sigstore_models.common import v1 as common_v1

    log = receipt.get("log")
    if not isinstance(log, dict):
        raise _CannotCheck("the receipt pins no log key.")
    try:
        public_key_der = base64.b64decode(log["public_key_der"])
        key = PinnedLogKey(
            base_url=str(log["base_url"]),
            operator=log.get("operator"),
            key_id_hex=str(log["key_id"]),
            public_key_der=public_key_der,
            key_details=str(log["key_details"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise _CannotCheck(
            f"the receipt's pinned log key is malformed: {exc}."
        ) from None
    if not key.public_key_der or not key.key_id_hex or not key.key_details:
        raise _CannotCheck("the receipt's pinned log key is incomplete.")
    if key.operator is not None and not isinstance(key.operator, str):
        raise _CannotCheck("the receipt's pinned log key operator is not a string.")
    try:
        common_v1.PublicKeyDetails[key.key_details]
    except KeyError as exc:
        raise _CannotCheck(
            f"the pinned log key names an unknown algorithm "
            f"{key.key_details!r}."
        ) from None
    return key


def verify_anchors(conn: sqlite3.Connection) -> AnchorCheck:
    """Check every closed epoch's Rekor anchor against the artifact it is in.

    For each `(chain, epoch)` head the artifact holds, the receipt must exist
    and parse, its entry must name this artifact's epoch head (through the
    envelope the receipt carries), the inclusion proof must chain to its root
    hash, and the checkpoint must verify against the log key the receipt
    pins. No network, no live trusted root: everything the check needs is in
    the file.

    Args:
        conn: an artifact opened with `reg.store.connect`.

    Returns:
        An `AnchorCheck`. `bool()` on it raises.
    """
    try:
        heads = [
            (str(r["chain"]), int(r["epoch"]), bytes(r["head"]))
            for r in conn.execute(
                "SELECT chain, epoch, head FROM epoch_heads ORDER BY chain, epoch"
            ).fetchall()
        ]
    except sqlite3.OperationalError:
        return AnchorCheck(
            AnchorState.COULD_NOT_EVALUATE,
            "this artifact has no epoch_heads table, so it was written before "
            "epoch anchoring existed. That is not the same fact as a build "
            "that anchored nothing, which carries the table and no receipts.",
        )
    if not heads:
        return AnchorCheck(
            AnchorState.COULD_NOT_EVALUATE,
            "this artifact holds no epoch heads, so there is nothing an "
            "anchor could have published.",
        )
    receipts = {
        (chain, epoch): receipt
        for chain, epoch, receipt in anchor_receipts(conn)
    }
    if not receipts:
        return AnchorCheck(
            AnchorState.COULD_NOT_EVALUATE,
            "this artifact holds no Rekor anchor receipts. Its chain deters "
            "editing and does not deter re-issuance.",
        )

    findings: list[EpochAnchor] = []
    for chain, epoch, head in heads:
        label = f"epoch {epoch} of the {chain!r} chain"
        receipt_bytes = receipts.get((chain, epoch))
        if receipt_bytes is None:
            findings.append(
                EpochAnchor(
                    chain,
                    epoch,
                    AnchorState.COULD_NOT_EVALUATE,
                    f"{label} has no Rekor receipt. Its published-ness could "
                    "not be established, which is not the same as established "
                    "absent.",
                )
            )
            continue
        try:
            receipt = json.loads(receipt_bytes)
            if not isinstance(receipt, dict) or receipt.get("scheme") != REKOR_SCHEME:
                raise RekorError("not a Rekor anchor receipt.")
            entry = _parse_entry(_canonical(receipt["entry"]))
            envelope = base64.b64decode(receipt["envelope"])
            log_key = _pinned_key_from_receipt(receipt)
        except (ValueError, UnicodeDecodeError, KeyError, TypeError) as exc:
            findings.append(
                EpochAnchor(
                    chain,
                    epoch,
                    AnchorState.COULD_NOT_EVALUATE,
                    f"{label}'s receipt does not parse: {exc} The artifact "
                    "may carry a good receipt this reader cannot read.",
                )
            )
            continue
        except RekorError as exc:
            findings.append(
                EpochAnchor(
                    chain,
                    epoch,
                    AnchorState.COULD_NOT_EVALUATE,
                    f"{label}'s receipt does not parse: {exc} The artifact "
                    "may carry a good receipt this reader cannot read.",
                )
            )
            continue
        try:
            _check_entry_binds_envelope(entry, envelope, head)
            _check_inclusion_proof(entry)
            _check_checkpoint(entry, log_key)
        except _CannotCheck as exc:
            findings.append(
                EpochAnchor(
                    chain,
                    epoch,
                    AnchorState.COULD_NOT_EVALUATE,
                    f"{label}: {exc}",
                )
            )
            continue
        except RekorError as exc:
            findings.append(
                EpochAnchor(
                    chain, epoch, AnchorState.INVALID, f"{label}: {exc}"
                )
            )
            continue
        findings.append(
            EpochAnchor(
                chain,
                epoch,
                AnchorState.VALID,
                f"{label}'s head was published to {log_key.base_url} under "
                f"log key {log_key.key_id_hex[:16]}….",
            )
        )

    invalid = [f for f in findings if f.state is AnchorState.INVALID]
    unknown = [f for f in findings if f.state is AnchorState.COULD_NOT_EVALUATE]
    if invalid:
        return AnchorCheck(
            AnchorState.INVALID,
            "; ".join(f.reason for f in invalid),
            tuple(findings),
        )
    if unknown:
        return AnchorCheck(
            AnchorState.COULD_NOT_EVALUATE,
            "; ".join(f.reason for f in unknown),
            tuple(findings),
        )
    return AnchorCheck(
        AnchorState.VALID,
        f"{len(findings)} epoch heads published, every entry naming this "
        "artifact's head and chaining to a checkpoint signed by the pinned "
        "log key.",
        tuple(findings),
    )
