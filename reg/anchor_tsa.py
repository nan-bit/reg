"""RFC 3161 timestamp anchoring for epoch heads. **Layer A** — part of the record.

WHAT THIS MODULE IS
-------------------
`reg.commit` proves a second on-site party saw the chain heads. This module
proves the epoch heads existed by a real instant to a party with no
relationship to the operator: at artifact close, every closed epoch head — 32
bytes, and the only thing that ever leaves the operator boundary — is sent to
an RFC 3161 Time Stamp Authority, and the returned timestamp tokens are
persisted in the artifact's `anchor_receipts` table as DER bytes.

WHAT IT NEEDS FROM THE WORLD, AND WHEN
--------------------------------------
One timestamp request per epoch head, at artifact close only, through a `TsaClient`.
Verification is file I/O plus crypto: each token carries the TSA's certificate
chain, the artifact carries the token, and the verifier supplies the trust
roots. No service, no network, ever, at verify time — the artifact must check
years later with nothing still running, so anchoring is a close-time operation
and nothing about verification phones home.

THE THREE STATES
----------------
`verify_anchors` reports per epoch and overall:

* **VALID** — every closed epoch's token parses, its messageImprint is SHA-256
  over this artifact's epoch head, and its CMS signature chains to a supplied
  root, with every certificate valid at the token's own genTime (not
  at verification time — a token from a TSA whose certificate has since expired
  is still good evidence of *that instant*).
* **INVALID** — a definite fault: a token's messageImprint is not this
  artifact's epoch head, or a token's signature does not verify.
* **COULD-NOT-EVALUATE** — the check could not run: no receipts at all, an
  epoch with no receipt, a token whose bytes do not parse, a signature chain
  that does not reach a supplied root, or no roots offered at all. Never
  resolves to VALID.

A NOTE ON THE PARSER
--------------------
`rfc3161-client` parses DER strictly — a SET OF whose elements are not in DER
order is a parse error, and some real-world encoders are liberal about exactly
that. A token whose bytes do not parse is COULD-NOT-EVALUATE, not INVALID: the
artifact may carry a perfectly good token this reader cannot read, and the
reader must say so rather than report a fault it did not establish.

A NOTE ON WIRING
----------------
`Rfc3161Committer` implements the `(ChainHeads) -> Commitment` seam from
`reg.commit`, but it needs the artifact connection to read the epoch heads it
anchors and to persist the receipts. A committer is built *before* `reg.graph`
`build()` opens that connection, so the committer takes it in its constructor
and `build()` accepts `tsa_client=` / `tsa_name=` to construct one at close
time, when the connection is live. Passing both `commitment=` and `tsa_client=`
is refused: two suppliers would be two schemes in `meta[commitment]`, and the
key holds one.
"""

from __future__ import annotations

import abc
import base64
import dataclasses
import hashlib
import sqlite3
import urllib.request
from enum import Enum
from typing import Sequence

from reg import store
from reg.commit import TSA_SCHEME, ChainHeads, Commitment

__all__ = [
    "TSA_SCHEME",
    "AnchorCheck",
    "AnchorError",
    "AnchorState",
    "EpochAnchor",
    "HttpTsaClient",
    "Rfc3161Committer",
    "TsaClient",
    "anchor_receipts",
    "verify_anchors",
]

#: The hash this scheme timestamps under, in the scheme name and enforced on
#: every token this module verifies. A token under another digest algorithm is
#: not this scheme's token.
_SHA256_OID = "2.16.840.1.101.3.4.2.1"


class AnchorError(Exception):
    """An anchor that will not be made, or a TSA exchange that failed.

    Always loud, never a substitution. An artifact carrying a receipt nobody can
    check is worse than one carrying none, because only the second says so —
    so a failed timestamp exchange refuses the build rather than recording a
    gap as an anchor.
    """


class TsaClient(abc.ABC):
    """The one timestamp request, behind an interface so tests never make it.

    `timestamp` takes the 32-byte epoch head to be witnessed and returns the
    raw DER bytes of the TSA's TimeStampResp. The request's messageImprint is
    SHA-256 over the head — the standard RFC 3161 shape, where the imprint is
    always a hash of the document and here the document is the head itself.
    The caller never sends a record, a head's preimage, or anything but the
    head, and the response is validated before anything is persisted.
    """

    @abc.abstractmethod
    def timestamp(self, digest: bytes) -> bytes:
        """Witness `digest`; return the DER TimeStampResp.

        Raises:
            AnchorError: the exchange failed, or `digest` is not 32 bytes.
        """


class HttpTsaClient(TsaClient):
    """A `TsaClient` over HTTPS to a real RFC 3161 TSA.

    Builds the request with `rfc3161-client`, POSTs it with
    `Content-Type: application/timestamp-query`, and returns the response body
    untouched — validation happens in the committer, against the parsed token,
    not against the HTTP layer.
    """

    def __init__(self, url: str, *, timeout_s: float = 30.0) -> None:
        if not isinstance(url, str) or not url.startswith("https://"):
            raise AnchorError(
                f"TSA url must be an https:// URL, got {url!r}. A timestamp "
                "fetched over cleartext is fetched from whoever answered."
            )
        if not isinstance(timeout_s, (int, float)) or timeout_s <= 0:
            raise AnchorError(f"timeout_s must be positive, got {timeout_s!r}.")
        self._url = url
        self._timeout_s = float(timeout_s)

    @property
    def url(self) -> str:
        return self._url

    def timestamp(self, digest: bytes) -> bytes:
        if not isinstance(digest, bytes) or len(digest) != 32:
            raise AnchorError(
                f"a TSA witnesses a 32-byte digest, got "
                f"{type(digest).__name__} of length "
                f"{len(digest) if isinstance(digest, bytes) else '?'}."
            )
        from rfc3161_client import HashAlgorithm, TimestampRequestBuilder

        request = (
            TimestampRequestBuilder()
            .data(digest)
            .hash_algorithm(HashAlgorithm.SHA256)
            .cert_request(cert_request=True)
            .build()
        )
        http_request = urllib.request.Request(
            self._url,
            data=request.as_bytes(),
            headers={"Content-Type": "application/timestamp-query"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(http_request, timeout=self._timeout_s) as resp:
                body = resp.read()
        except Exception as exc:  # noqa: BLE001 - transport failure is transport failure
            raise AnchorError(
                f"the TSA exchange with {self._url} failed: {exc}. Refusing "
                "rather than recording a gap as an anchor."
            ) from None
        if not body:
            raise AnchorError(
                f"the TSA at {self._url} returned an empty response."
            )
        return body


def _parse_response(resp_der: bytes):
    """Parse DER into a `TimeStampResponse`, or raise `AnchorError`.

    The import is local so that importing this module never requires the TSA
    library: reading an artifact — including a cold read of its anchor rows —
    must work where no TSA dependency is installed.
    """
    from rfc3161_client import decode_timestamp_response

    try:
        return decode_timestamp_response(resp_der)
    except Exception as exc:  # noqa: BLE001 - the Rust parser raises ValueError
        raise AnchorError(
            f"the TSA response does not parse as a TimeStampResp: {exc}."
        ) from None


def _check_response_is_an_anchor(response, digest: bytes) -> None:
    """Refuse a response that does not witness `digest`.

    A granted response whose messageImprint is not the digest we sent is not an
    anchor for this epoch — persisting it would write a receipt that verifies
    against nothing. Raises `AnchorError`.
    """
    from rfc3161_client import PKIStatus

    if int(response.status) != int(PKIStatus.GRANTED):
        raise AnchorError(
            f"the TSA did not grant the timestamp: status "
            f"{PKIStatus(int(response.status)).name}."
        )
    imprint = response.tst_info.message_imprint
    if imprint.hash_algorithm.dotted_string != _SHA256_OID:
        raise AnchorError(
            f"the TSA answered under hash algorithm "
            f"{imprint.hash_algorithm.dotted_string}, not SHA-256 "
            f"({_SHA256_OID}). This adapter is {TSA_SCHEME}; a token under "
            "another algorithm is not its token."
        )
    if imprint.message != hashlib.sha256(digest).digest():
        raise AnchorError(
            "the TSA's messageImprint is not SHA-256 over the digest it "
            "was sent. A token over something else is not an anchor for "
            "this epoch."
        )


@dataclasses.dataclass(frozen=True)
class Rfc3161Committer:
    """The TSA `Committer`: one timestamp token per closed epoch head.

    Call it with a `ChainHeads` and it anchors every epoch head the artifact
    holds — `(chain, epoch)` rows from `epoch_heads`, in `(chain, epoch)`
    order — persists each DER token to `anchor_receipts`, and returns a
    `Commitment` under `rfc3161-sha256-v1`. The `token` on that commitment is
    the base64 of the *last* anchored token; per-epoch verification reads
    `anchor_receipts`, where every token lives.

    `conn` is the artifact connection the build is writing: the committer reads
    the epoch heads it anchors from it and persists the receipts to it, in the
    build's own transaction, so a failed anchor refuses the build rather than
    leaving a half-anchored file.
    """

    tsa: TsaClient
    conn: sqlite3.Connection
    tsa_name: str

    #: Named on the class so a caller can report which scheme it is about to
    #: use without having to run it.
    scheme: str = TSA_SCHEME

    def __post_init__(self) -> None:
        if not isinstance(self.tsa, TsaClient):
            raise AnchorError(
                f"Rfc3161Committer takes a TsaClient, got "
                f"{type(self.tsa).__name__}."
            )
        if not isinstance(self.conn, sqlite3.Connection):
            raise AnchorError(
                f"Rfc3161Committer takes a sqlite3.Connection, got "
                f"{type(self.conn).__name__}."
            )
        if not isinstance(self.tsa_name, str) or not self.tsa_name.strip():
            raise AnchorError(
                f"tsa_name={self.tsa_name!r}. The whole content of this scheme "
                "is *which third party* witnessed the heads, so a committer "
                "with no name commits nothing anybody can check."
            )
        if self.scheme != TSA_SCHEME:
            raise AnchorError(
                f"a Rfc3161Committer is {TSA_SCHEME!r}, not {self.scheme!r}. A "
                "different scheme is a different adapter, not this one with a "
                "different label on it."
            )

    def __call__(self, heads: ChainHeads) -> Commitment:
        rows = self.conn.execute(
            "SELECT chain, epoch, head FROM epoch_heads ORDER BY chain, epoch"
        ).fetchall()
        if not rows:
            raise AnchorError(
                "the artifact holds no epoch heads, so there is nothing to "
                "anchor. A commitment over zero epochs would verify and mean "
                "nothing."
            )
        tokens: list[bytes] = []
        for row in rows:
            digest = bytes(row["head"])
            if len(digest) != 32:
                raise AnchorError(
                    f"epoch {int(row['epoch'])} of the {row['chain']!r} chain "
                    f"holds a {len(digest)}-byte head. Only 32-byte heads "
                    "leave the operator boundary."
                )
            resp_der = self.tsa.timestamp(digest)
            response = _parse_response(resp_der)
            _check_response_is_an_anchor(response, digest)
            store.store_anchor_receipt(
                self.conn,
                str(row["chain"]),
                int(row["epoch"]),
                TSA_SCHEME,
                resp_der,
            )
            tokens.append(resp_der)
        return Commitment(
            scheme=self.scheme,
            witness_id=self.tsa_name,
            heads=heads,
            token=base64.b64encode(tokens[-1]).decode("ascii"),
        )


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

    #: Every closed epoch's token parses, names this artifact's epoch head,
    #: and chains to a supplied root.
    VALID = "VALID"
    #: A definite fault: a token's messageImprint is not this artifact's epoch
    #: head, or a token's signature does not verify.
    INVALID = "INVALID"
    #: Nothing was learned: no receipts, an epoch with no receipt, a token
    #: that does not parse, a chain that does not reach a supplied root, or no
    #: roots offered. **Never resolves to VALID.**
    COULD_NOT_EVALUATE = "COULD-NOT-EVALUATE"


@dataclasses.dataclass(frozen=True)
class AnchorCheck:
    """The result of `verify_anchors`: a state, the reason, and the per-epoch
    findings.

    `bool(check)` raises, for `reg.commit.CommitmentCheck.__bool__`'s reason:
    `if verify_anchors(...)` reads as "is this artifact anchored", and an
    artifact whose tokens nobody checked is neither yes nor no.
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
        return f"{self.state.value} [{TSA_SCHEME}]: {self.reason}"


def anchor_receipts(
    conn: sqlite3.Connection, *, scheme: str = TSA_SCHEME
) -> list[tuple[str, int, bytes]]:
    """Every anchor receipt under `scheme`: `(chain, epoch, receipt DER)`."""
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


def _load_roots(roots: Sequence[bytes]) -> list:
    """DER trust roots into `cryptography` certificates, or raise AnchorError."""
    import cryptography.x509

    loaded = []
    for i, raw in enumerate(roots):
        if not isinstance(raw, bytes) or not raw:
            raise AnchorError(
                f"trust root {i} is not non-empty bytes. A root nobody can "
                "parse anchors nothing."
            )
        try:
            loaded.append(cryptography.x509.load_der_x509_certificate(raw))
        except Exception as exc:  # noqa: BLE001 - malformed certificate
            raise AnchorError(
                f"trust root {i} does not parse as a DER certificate: {exc}."
            ) from None
    return loaded


def verify_anchors(
    conn: sqlite3.Connection, roots: Sequence[bytes]
) -> AnchorCheck:
    """Check every closed epoch's TSA anchor against the artifact it is in.

    For each `(chain, epoch)` head the artifact holds, the receipt must exist,
    parse as a granted RFC 3161 response, carry SHA-256 over this artifact's
    head in its messageImprint, and — where `roots` are offered — its CMS
    signature must chain to one of them, with certificates valid at the
    token's own genTime.

    Args:
        conn: an artifact opened with `reg.store.connect`.
        roots: DER-encoded trust roots the TSA chain is built against. Empty
            means "no roots offered": imprints are still checked, signatures
            are not, and no epoch can report better than COULD-NOT-EVALUATE.

    Returns:
        An `AnchorCheck`. `bool()` on it raises.
    """
    from rfc3161_client import PKIStatus, VerificationError, VerifierBuilder

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
            "this artifact holds no epoch heads, so there is nothing an anchor "
            "could witness.",
        )
    receipts = {
        (chain, epoch): receipt
        for chain, epoch, receipt in anchor_receipts(conn)
    }
    if not receipts:
        return AnchorCheck(
            AnchorState.COULD_NOT_EVALUATE,
            "this artifact holds no RFC 3161 anchor receipts. Its chain "
            "deters editing and does not deter re-issuance.",
        )

    trust_roots = _load_roots(roots) if roots else []
    import cryptography.x509

    findings: list[EpochAnchor] = []
    for chain, epoch, head in heads:
        label = f"epoch {epoch} of the {chain!r} chain"
        receipt = receipts.get((chain, epoch))
        if receipt is None:
            findings.append(
                EpochAnchor(
                    chain, epoch, AnchorState.COULD_NOT_EVALUATE,
                    f"{label} has no anchor receipt. Its witnessed-ness could "
                    "not be established, which is not the same as established "
                    "absent.",
                )
            )
            continue
        try:
            response = _parse_response(receipt)
        except AnchorError as exc:
            findings.append(
                EpochAnchor(
                    chain, epoch, AnchorState.COULD_NOT_EVALUATE,
                    f"{label}'s token does not parse: {exc} The artifact may "
                    "carry a good token this reader cannot read.",
                )
            )
            continue
        if int(response.status) != int(PKIStatus.GRANTED):
            findings.append(
                EpochAnchor(
                    chain, epoch, AnchorState.COULD_NOT_EVALUATE,
                    f"{label}'s token has status "
                    f"{PKIStatus(int(response.status)).name}, not GRANTED. A "
                    "rejection witnesses nothing.",
                )
            )
            continue
        imprint = response.tst_info.message_imprint
        if imprint.hash_algorithm.dotted_string != _SHA256_OID:
            findings.append(
                EpochAnchor(
                    chain, epoch, AnchorState.INVALID,
                    f"{label}'s token is under hash algorithm "
                    f"{imprint.hash_algorithm.dotted_string}, not SHA-256. "
                    f"This scheme is {TSA_SCHEME}.",
                )
            )
            continue
        if imprint.message != hashlib.sha256(head).digest():
            findings.append(
                EpochAnchor(
                    chain, epoch, AnchorState.INVALID,
                    f"{label}'s token does not name this artifact's epoch "
                    "head: its messageImprint is not SHA-256 over this "
                    "artifact's head. The head, the token, or the receipt row "
                    "is not the one that was anchored.",
                )
            )
            continue
        if not trust_roots:
            findings.append(
                EpochAnchor(
                    chain, epoch, AnchorState.COULD_NOT_EVALUATE,
                    f"{label}'s token names this artifact's epoch head, but "
                    "no TSA trust roots were offered, so its signature was "
                    "not checked. An unchecked token is not a checked one.",
                )
            )
            continue
        builder = VerifierBuilder()
        for cert_der in response.signed_data.certificates:
            try:
                builder = builder.add_intermediate_certificate(
                    cryptography.x509.load_der_x509_certificate(cert_der)
                )
            except Exception:  # noqa: BLE001 - one bad embedded cert, keep going
                continue
        for root in trust_roots:
            builder = builder.add_root_certificate(root)
        try:
            builder.build().verify(response, hashlib.sha256(head).digest())
        except VerificationError as exc:
            findings.append(
                EpochAnchor(
                    chain, epoch, AnchorState.INVALID,
                    f"{label}'s token signature does not verify: {exc}",
                )
            )
            continue
        except Exception as exc:  # noqa: BLE001 - verifier refused the input
            findings.append(
                EpochAnchor(
                    chain, epoch, AnchorState.COULD_NOT_EVALUATE,
                    f"{label}'s token could not be verified: {exc}",
                )
            )
            continue
        findings.append(
            EpochAnchor(
                chain, epoch, AnchorState.VALID,
                f"{label}'s head was witnessed at "
                f"{response.tst_info.gen_time.isoformat()} under policy "
                f"{response.tst_info.policy.dotted_string}.",
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
        f"{len(findings)} epoch heads witnessed, every token naming this "
        "artifact's head and chaining to a supplied root.",
        tuple(findings),
    )
