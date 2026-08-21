"""External commitment to the chain heads. **Layer A** — part of the record.

WHAT THIS FILE IS FOR, AND WHAT IT IS HONESTLY NOT
--------------------------------------------------
`reg.chain` proves the records are internally consistent **under keys held by
the record's own author**. It does not prove the history was not re-issued
offline: the party a regulator distrusts most is the OEM, and the OEM is the
signer. Re-running the whole run and re-signing every record produces an
artifact whose chain verifies perfectly. Nothing inside the file can notice.

What notices is a commitment to the two chain heads made **outside** the
author's control at the moment the artifact was closed. That is the difference
between *deters editing* and *deters re-issuance*, and it is the half of issue
#83 this module is.

**Commitment is an interface with no default.** `Committer.__call__(heads) ->
Commitment`. An artifact closed without a supplier does not silently get an
uncommitted chain: `meta[commitment]` is written on **every** build, and it says
`none` in so many words when there was no supplier. Silence must never read as
commitment — that is the same three-valued discipline the rest of the project
runs on, applied to the one fact that would otherwise be inferred from a missing
key.

THE ONE SHIPPED IMPLEMENTATION IS AN ON-SITE WITNESS, AND IT IS WEAKER
-----------------------------------------------------------------------
`WitnessCommitter` is an HMAC over both chain heads under the key of a **second
on-site keyholder**, distinct from the two keys that signed the records. Say
what it proves and no more: *a second party at the same site saw these heads.*
It does **not** prove the heads existed by a given instant to someone with no
relationship to the operator. It is not timestamping and this module will not
describe it as timestamping.

Its independence is the same argument the Layer A / Layer B split and the
policy / enforcement key split make, one level along: a witness whose key is the
key that signed the records is the author witnessing themself, so
`check_witness_is_independent` refuses that arrangement rather than recording it.

DOCUMENTED AND DELIBERATELY NOT IMPLEMENTED
-------------------------------------------
* **RFC 3161 timestamp tokens.** Strictly stronger — a TSA with no relationship
  to the operator asserts the heads existed by an instant. Rejected here for one
  reason only: it needs a network call at artifact close, and the README claims
  air-gapped operation. If that claim is ever dropped, this is the upgrade path,
  and the interface above is what makes it an adapter rather than a rewrite.
* **Transparency-log inclusion** (a Certificate-Transparency-shaped append-only
  log; docs/prior-art.md). Same shape, same reason, and additionally it makes
  *withholding* an artifact detectable, which nothing here does.

Both would be a `Committer` returning a `Commitment` with a different `scheme`
and a different `token`. Nothing else in the project would move.

WHERE THE COMMITMENT LIVES, AND WHY THAT IS SAFE
-------------------------------------------------
In `meta`, which carries no MAC. That is fine and is worth stating rather than
glossing: the commitment records the heads, and `verify_commitment` **recomputes
the heads from the records the artifact actually holds**. Editing the recorded
heads to match a re-issued chain breaks the witness signature; editing the
records breaks the recomputed heads against the recorded ones. The second of
those is detectable **without the witness key at all**, which is the strongest
property here and the reason the heads are stored beside the signature instead
of only inside it.
"""

from __future__ import annotations

import dataclasses
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
from enum import Enum
from pathlib import Path

from reg import chain, store
from reg.stream import ENCODING

__all__ = [
    "COMMITMENT_NONE",
    "COMMITMENT_STATEMENT",
    "META_COMMITMENT",
    "META_COMMITMENT_DECLARATION_HEAD",
    "META_COMMITMENT_SIGNATURE",
    "META_COMMITMENT_STATEMENT",
    "META_COMMITMENT_VERDICT_HEAD",
    "META_COMMITMENT_WITNESS",
    "SCHEMES",
    "WITNESS_KEY_BYTES",
    "WITNESS_SCHEME",
    "ChainHeads",
    "Commitment",
    "CommitmentCheck",
    "CommitmentError",
    "CommitmentState",
    "Witness",
    "WitnessCommitter",
    "chain_heads",
    "check_witness_is_independent",
    "commitment_bytes",
    "generate_witness",
    "load_witness",
    "verify_commitment",
    "write_witness",
]

#: The `meta` key that says whether this artifact's chain heads were committed
#: to anything, and under which scheme. **Written on every build**, so its
#: absence means an artifact from before this interface existed rather than an
#: artifact that was closed without a commitment.
META_COMMITMENT = "commitment"

#: The value of `META_COMMITMENT` for an artifact closed with no supplier. The
#: string is spelled out rather than left implicit for the reason the whole
#: module exists: an uncommitted chain must announce itself.
COMMITMENT_NONE = "none"

#: The one scheme this project implements. Versioned in the name: a change to
#: `commitment_bytes` is a new scheme, and every old signature visibly stops
#: matching rather than quietly re-baselining.
WITNESS_SCHEME = "witness-hmac-sha256-v1"

#: Every scheme a reader of this version understands. A `meta[commitment]`
#: outside this set is a could-not-evaluate — an artifact committed under
#: something newer, which this reader must say it cannot check rather than
#: report as uncommitted.
SCHEMES: tuple[str, ...] = (WITNESS_SCHEME,)

#: Where the rest of the commitment lands in `meta`.
META_COMMITMENT_WITNESS = "commitment_witness_id"
META_COMMITMENT_DECLARATION_HEAD = "commitment_declaration_head"
META_COMMITMENT_VERDICT_HEAD = "commitment_verdict_head"
META_COMMITMENT_SIGNATURE = "commitment_signature"
META_COMMITMENT_STATEMENT = "commitment_statement"

#: What the shipped scheme proves, in the artifact and not only in this module,
#: because the file is the thing handed over. An assessor who reads
#: `commitment: witness-hmac-sha256-v1` and takes it for a timestamp has been
#: misled by this project, so the artifact says plainly that it is not one.
COMMITMENT_STATEMENT = (
    "The two chain heads were signed at artifact close by a second on-site "
    "keyholder whose key did not sign any record in this file. That proves a "
    "second party at the same site saw these heads. It is NOT a third-party "
    "timestamp: it does not prove the heads existed by any given instant to "
    "anyone with no relationship to the operator. An RFC 3161 token or a "
    "transparency-log inclusion proof would; both need a network call at "
    "artifact close, which this project's air-gapped operation rules out."
)

#: Witness key material length, the same 32 bytes `reg.chain` uses and for the
#: same reason: short material is refused rather than stretched.
WITNESS_KEY_BYTES = chain.KEY_BYTES

#: Domain separator for the commitment preimage. Disjoint from the three in
#: `reg.chain` so a commitment can never be replayed as a record MAC or a chain
#: link, and vice versa.
_COMMITMENT_DOMAIN = b"reg-commitment-v1\x00"

_FIELD_SEP = b"\x1f"
_RECORD_SEP = b"\x1e"


class CommitmentError(ValueError):
    """A commitment that will not be made, or a witness file that is not one.

    Always loud, never a substitution. A commitment made under material this
    module invented would verify and mean nothing, which is worse than none at
    all — none at all is at least recorded as `COMMITMENT: NONE`.
    """


@dataclasses.dataclass(frozen=True)
class ChainHeads:
    """The final chain hash of each of the two chains.

    Two heads and not one, because the artifact holds two chains signed by two
    parties (`reg.chain.CHAINS`) and a commitment to one of them leaves the
    other free to be re-issued.

    **A chain with no records has `reg.chain.GENESIS_HASH` as its head**, and
    that is a definition rather than a fallback: committing to "this chain was
    empty when the artifact was closed" is a true and useful statement, and it
    is what stops an empty chain from being silently unconstrained. Whether an
    empty chain is *evidence* is a different question, and `verify_chain`
    already answers it — COULD-NOT-EVALUATE.
    """

    declaration_head: str
    verdict_head: str

    def __post_init__(self) -> None:
        for name in ("declaration_head", "verdict_head"):
            value = getattr(self, name)
            if not chain.is_hash(value):
                raise CommitmentError(
                    f"{name}={value!r} is not {chain.HASH_HEX_LEN} lowercase hex "
                    "characters. A commitment to something that is not a chain "
                    "head commits to nothing, and it would verify."
                )


def chain_heads(conn: sqlite3.Connection) -> ChainHeads:
    """The two chain heads of an artifact, recomputed from its own records.

    Recomputed and never read out of `meta`: the point of the heads is to be
    compared against what the file actually holds, so a function that read them
    back from a stored key would compare a value with itself.

    The fold is `reg.chain.chain_head`, which runs the *running* hash into each
    record rather than the link the record carries. That distinction is
    load-bearing here: folding each record's own `prev_hash` would produce a
    value depending only on the last record, and a commitment that does not move
    when the first of a hundred declarations is rewritten is not a commitment to
    the chain.

    Raises:
        CommitmentError: a chain could not be read or a record could not be
            canonicalized, so this artifact has no computable head. A
            could-not-evaluate, and never a head computed over the records that
            happened to parse.
    """
    heads: dict[str, str] = {}
    for spec in chain.CHAINS:
        try:
            records = getattr(store, spec.reader)(conn)
        except (store.StoreError, ValueError, sqlite3.DatabaseError) as exc:
            raise CommitmentError(
                f"the {spec.role} chain could not be read, so this artifact has "
                f"no computable {spec.kind} head: {exc}"
            ) from None
        try:
            head = chain.chain_head(records)
        except chain.CanonicalizationError as exc:
            raise CommitmentError(
                f"a stored {spec.kind} could not be hashed, so the "
                f"{spec.role} chain has no computable head: {exc}"
            ) from None
        heads[spec.role] = head
    return ChainHeads(
        declaration_head=heads["policy"], verdict_head=heads["enforcement"]
    )


def commitment_bytes(scheme: str, witness_id: str, heads: ChainHeads) -> bytes:
    """The preimage a commitment signature is taken over.

    Domain-separated, type-free and length-prefixed, the same discipline
    `reg.chain.canonical_bytes` uses and for the same reason: two different
    (scheme, witness, heads) triples must not share a preimage, so
    `("ab", "c")` and `("a", "bc")` cannot collide.

    The `witness_id` is inside the preimage rather than only beside it, so a
    signature cannot be re-labelled as a different witness's.
    """
    if not isinstance(scheme, str) or not scheme:
        raise CommitmentError(f"scheme must be a non-empty str, got {scheme!r}.")
    if not isinstance(witness_id, str) or not witness_id.strip():
        raise CommitmentError(
            f"witness_id={witness_id!r}. A commitment nobody can attribute to a "
            "witness attributes it to nobody."
        )
    if not isinstance(heads, ChainHeads):
        raise CommitmentError(
            f"heads must be a ChainHeads, got {type(heads).__name__}."
        )
    parts = [_COMMITMENT_DOMAIN]
    for name, value in (
        ("scheme", scheme),
        ("witness_id", witness_id),
        ("declaration_head", heads.declaration_head),
        ("verdict_head", heads.verdict_head),
    ):
        payload = value.encode(ENCODING)
        parts.append(
            b"".join(
                (
                    name.encode(ENCODING),
                    _FIELD_SEP,
                    str(len(payload)).encode("ascii"),
                    _FIELD_SEP,
                    payload,
                    _RECORD_SEP,
                )
            )
        )
    return b"".join(parts)


@dataclasses.dataclass(frozen=True)
class Commitment:
    """What a `Committer` returns: the heads, who committed to them, and how.

    `token` is the scheme's own proof. For the witness scheme it is an HMAC hex
    digest; for an RFC 3161 adapter it would be the base64 of the timestamp
    token, and nothing else in this project would need to know the difference.
    """

    scheme: str
    witness_id: str
    heads: ChainHeads
    token: str

    def __post_init__(self) -> None:
        if self.scheme not in SCHEMES:
            raise CommitmentError(
                f"scheme {self.scheme!r} is not one this version implements; "
                f"the schemes are {list(SCHEMES)}. A commitment recorded under a "
                "name no reader knows is one every reader reports as unchecked."
            )
        if not isinstance(self.token, str) or not self.token.strip():
            raise CommitmentError(
                f"a {self.scheme} commitment was made with token={self.token!r}. "
                "An empty proof is not a commitment, and it would be written "
                "into the artifact beside a scheme name that says there is one."
            )


@dataclasses.dataclass(frozen=True)
class Witness:
    """The second on-site keyholder: who they are, and their key.

    `repr` redacts the material, exactly as `reg.chain.Key` does — witness keys
    end up in tracebacks and unattended CI logs otherwise, and a witness key in
    a log is a witness anyone can impersonate.
    """

    witness_id: str
    material: bytes

    def __post_init__(self) -> None:
        if not isinstance(self.witness_id, str) or not self.witness_id.strip():
            raise CommitmentError(
                f"witness_id={self.witness_id!r}. The whole content of this "
                "scheme is *which second party* signed the heads, so a witness "
                "with no name commits nothing anybody can check."
            )
        if not isinstance(self.material, bytes):
            raise CommitmentError(
                f"witness key material is a {type(self.material).__name__}, not "
                "bytes."
            )
        if len(self.material) != WITNESS_KEY_BYTES:
            raise CommitmentError(
                f"witness key material is {len(self.material)} bytes; this "
                f"project's keys are exactly {WITNESS_KEY_BYTES}. Short material "
                "is refused rather than stretched — a stretched key is "
                "indistinguishable downstream from a strong one."
            )

    def __repr__(self) -> str:
        return (
            f"Witness(witness_id={self.witness_id!r}, "
            f"material=<{WITNESS_KEY_BYTES} bytes, redacted>)"
        )


def generate_witness(witness_id: str) -> Witness:
    """A fresh witness key from OS entropy. **Deliberately not seeded.**

    The same rule `reg.chain.generate_keyring` states: a seeded secret is not a
    secret, and a witness key recomputable from a number in the artifact would
    let the artifact's own author produce the second party's signature.
    """
    return Witness(
        witness_id=witness_id, material=secrets.token_bytes(WITNESS_KEY_BYTES)
    )


def load_witness(path: str | os.PathLike[str]) -> Witness:
    """Read a witness file: `{"witness_id": ..., "key": <64 hex chars>}`.

    Strict in every direction, like `reg.chain.load_keyring`: a missing field,
    an unknown field, a short key or a non-hex string is a refusal. A witness
    loaded from half a file signs under material nobody can reproduce.
    """
    path = Path(path)
    try:
        raw = path.read_text(encoding=ENCODING)
    except OSError as exc:
        raise CommitmentError(f"{path}: witness file could not be read: {exc}") from None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CommitmentError(f"{path}: witness file is not valid JSON: {exc}") from None
    if not isinstance(payload, dict):
        raise CommitmentError(
            f"{path}: a witness file is a JSON object with 'witness_id' and "
            f"'key', got a {type(payload).__name__}."
        )
    expected = {"witness_id", "key"}
    unknown = sorted(set(payload) - expected)
    if unknown:
        raise CommitmentError(
            f"{path}: witness file carries unknown field(s) {unknown}; it holds "
            f"exactly {sorted(expected)}. Refusing rather than ignoring them — "
            "an extra field is either a typo that leaves a real one missing or a "
            "value nothing will ever read."
        )
    missing = sorted(expected - set(payload))
    if missing:
        raise CommitmentError(f"{path}: witness file is missing {missing}.")
    key = payload["key"]
    if not isinstance(key, str):
        raise CommitmentError(
            f"{path}: witness key is a {type(key).__name__}, not a hex string."
        )
    if len(key) != 2 * WITNESS_KEY_BYTES:
        raise CommitmentError(
            f"{path}: witness key is {len(key)} hex characters, expected "
            f"{2 * WITNESS_KEY_BYTES} ({WITNESS_KEY_BYTES} bytes)."
        )
    try:
        material = bytes.fromhex(key)
    except ValueError:
        raise CommitmentError(f"{path}: witness key is not hexadecimal.") from None
    return Witness(witness_id=str(payload["witness_id"]), material=material)


def write_witness(witness: Witness, path: str | os.PathLike[str]) -> Path:
    """Write a witness file with owner-only permissions. Returns the path.

    Owner-only at creation, through `os.open`, for `reg.chain.write_keyring`'s
    reason: writing first and chmod-ing after leaves a window in which the key
    is world-readable, and a witness key every process on the host can read
    makes the second signature decorative.
    """
    if not isinstance(witness, Witness):
        raise CommitmentError(
            f"write_witness takes a Witness, got {type(witness).__name__}."
        )
    path = Path(path)
    text = (
        json.dumps(
            {"witness_id": witness.witness_id, "key": witness.material.hex()},
            indent=2,
            sort_keys=False,
        )
        + "\n"
    )
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding=ENCODING) as handle:
        handle.write(text)
    return path


def check_witness_is_independent(witness: Witness, keyring: chain.Keyring) -> None:
    """Refuse a witness whose key is one of the keys that signed the records.

    The mechanism of this scheme is that a **second** party saw the heads. A
    witness holding the policy or the enforcement key is the author witnessing
    themself, and the resulting signature verifies exactly as a real one does —
    so it has to be refused where it is made, not reported afterwards. Same
    argument as `reg/enforce.py` not importing from `declare/`: common-cause
    failure is not detectable downstream of itself.

    Raises:
        CommitmentError: the material matches a record-signing key.
    """
    if not isinstance(witness, Witness):
        raise CommitmentError(
            f"check_witness_is_independent takes a Witness, got "
            f"{type(witness).__name__}."
        )
    if not isinstance(keyring, chain.Keyring):
        raise CommitmentError(
            f"check_witness_is_independent takes a Keyring, got "
            f"{type(keyring).__name__}."
        )
    for role in chain.ROLES:
        if hmac.compare_digest(witness.material, keyring.key(role).material):
            raise CommitmentError(
                f"the witness key is the {role!r} record-signing key. A witness "
                "is a *second* party: signing the heads with the key that signed "
                "the records is the author witnessing themself, and the "
                "signature it produces verifies exactly as a real one does. "
                "Refusing here rather than recording it, because nothing "
                "downstream can tell the two apart."
            )


@dataclasses.dataclass(frozen=True)
class WitnessCommitter:
    """The shipped `Committer`: HMAC-SHA256 over both heads, under a witness key.

    Call it with a `ChainHeads` and it returns a `Commitment`. That signature —
    `(heads) -> Commitment` — is the whole interface, which is what makes an RFC
    3161 or transparency-log adapter a new class here rather than a change to
    `reg.graph`.
    """

    witness: Witness

    #: Named on the class so a caller can report which scheme it is about to use
    #: without having to run it.
    scheme: str = WITNESS_SCHEME

    def __post_init__(self) -> None:
        if not isinstance(self.witness, Witness):
            raise CommitmentError(
                f"WitnessCommitter takes a Witness, got "
                f"{type(self.witness).__name__}."
            )
        if self.scheme != WITNESS_SCHEME:
            raise CommitmentError(
                f"a WitnessCommitter is {WITNESS_SCHEME!r}, not {self.scheme!r}. "
                "A different scheme is a different adapter, not this one with a "
                "different label on it."
            )

    def __call__(self, heads: ChainHeads) -> Commitment:
        token = hmac.new(
            self.witness.material,
            commitment_bytes(self.scheme, self.witness.witness_id, heads),
            hashlib.sha256,
        ).hexdigest()
        return Commitment(
            scheme=self.scheme,
            witness_id=self.witness.witness_id,
            heads=heads,
            token=token,
        )


class CommitmentState(Enum):
    """The three outcomes of a commitment check. No fourth, and no bool.

    The same three `reg.chain.ChainState` has, for the same reason: `INVALID` is
    a finding about the artifact, `COULD_NOT_EVALUATE` is a finding about the
    *check* — an absent commitment, an unknown scheme, no witness key — and an
    absent commitment must never be reported as a present one.
    """

    #: The recorded heads are the artifact's own, and the token verifies.
    VALID = "VALID"
    #: A definite fault: the recorded heads are not the ones this artifact's
    #: records produce, or the token does not verify under the witness offered.
    INVALID = "INVALID"
    #: Nothing was learned: no commitment was made, the artifact predates the
    #: interface, the scheme is unknown, or no witness key was offered.
    #: **Never resolves to VALID.**
    COULD_NOT_EVALUATE = "COULD-NOT-EVALUATE"


@dataclasses.dataclass(frozen=True)
class CommitmentCheck:
    """The result of `verify_commitment`: a state, the reason, and the heads.

    `bool(check)` raises, for `reg.chain.MacCheck.__bool__`'s reason: `if
    verify_commitment(...)` reads as "is this artifact committed", and an
    artifact closed with no supplier is neither yes nor no.

    Both sets of heads are carried whatever the verdict, because "INVALID" on
    its own is not usable evidence — an assessor's next question is *which head
    moved*, and a report that cannot answer it sends them back to the file.
    """

    state: CommitmentState
    reason: str
    scheme: str | None = None
    witness_id: str | None = None
    #: What the artifact says it committed to, or `None` if it says nothing.
    recorded: ChainHeads | None = None
    #: What this artifact's records actually produce, or `None` if they could
    #: not be walked.
    computed: ChainHeads | None = None

    def __bool__(self) -> bool:  # pragma: no cover - exercised via pytest.raises
        raise TypeError(
            "a CommitmentCheck has three states and cannot be used as a bool. "
            f"This one is {self.state.value}: {self.reason}. Compare .state "
            "against CommitmentState.VALID / INVALID / COULD_NOT_EVALUATE — and "
            "handle COULD_NOT_EVALUATE explicitly, because an uncommitted "
            "artifact is not a committed one."
        )

    def describe(self) -> str:
        """One line: the verdict, the scheme, and why."""
        scheme = "none" if self.scheme is None else self.scheme
        return f"{self.state.value} [{scheme}]: {self.reason}"


def _recorded_heads(conn: sqlite3.Connection) -> ChainHeads | None:
    declared = store.get_meta(conn, META_COMMITMENT_DECLARATION_HEAD)
    verdict = store.get_meta(conn, META_COMMITMENT_VERDICT_HEAD)
    if declared is None or verdict is None:
        return None
    try:
        return ChainHeads(declaration_head=declared, verdict_head=verdict)
    except CommitmentError:
        return None


def verify_commitment(
    conn: sqlite3.Connection, witness: Witness | None
) -> CommitmentCheck:
    """Check an artifact's commitment against the records it actually holds.

    Two checks, in this order, and the order is the point:

    1. **The recorded heads against the recomputed ones.** This needs no key at
       all. An artifact whose records were re-issued after it was closed has
       heads that no longer match what it committed to, and *anybody* holding
       the file can see it.
    2. **The token, under the witness key.** This needs the second party's key,
       and it is what makes the heads themselves unalterable: editing them to
       match a re-issued chain breaks the signature.

    Args:
        conn: an artifact opened with `reg.store.connect`.
        witness: the witness whose key signed the heads, or `None` for "no
            witness key available". **Required, with no default**, exactly as
            `verify_chain`'s keyring is: a caller who did not think about the
            key would otherwise get a report that looks like a verification and
            checked no signature. `None` is could-not-evaluate for step 2 and
            nothing else — step 1 still runs and is still reported.

    Returns:
        A `CommitmentCheck`. `bool()` on it raises.
    """
    scheme = store.get_meta(conn, META_COMMITMENT)
    if scheme is None:
        return CommitmentCheck(
            CommitmentState.COULD_NOT_EVALUATE,
            "this artifact does not state whether its chain heads were "
            f"committed to anything: it has no meta[{META_COMMITMENT!r}] at all, "
            "so it was written before the commitment interface existed. That is "
            "not the same fact as a build that was given no supplier, which "
            f"records {COMMITMENT_NONE!r} in so many words.",
        )
    if scheme == COMMITMENT_NONE:
        return CommitmentCheck(
            CommitmentState.COULD_NOT_EVALUATE,
            "this artifact was closed with no commitment supplier, and says so. "
            "Its chain deters editing and does not deter re-issuance: the party "
            "that signed the records could have produced the whole history "
            "offline, and nothing in the file bears on that.",
            scheme=COMMITMENT_NONE,
        )
    if scheme not in SCHEMES:
        return CommitmentCheck(
            CommitmentState.COULD_NOT_EVALUATE,
            f"this artifact is committed under scheme {scheme!r}, which this "
            f"version does not implement; it knows {list(SCHEMES)}. Reporting "
            "unchecked rather than uncommitted — the commitment may be perfectly "
            "good and this reader cannot tell.",
            scheme=scheme,
        )

    recorded = _recorded_heads(conn)
    witness_id = store.get_meta(conn, META_COMMITMENT_WITNESS)
    token = store.get_meta(conn, META_COMMITMENT_SIGNATURE)
    if recorded is None or witness_id is None or token is None:
        return CommitmentCheck(
            CommitmentState.COULD_NOT_EVALUATE,
            f"meta[{META_COMMITMENT!r}] says {scheme!r} but the commitment is "
            "incomplete: one of the two heads, the witness id or the signature "
            "is missing or malformed. A partial commitment is checked against "
            "nothing, and it must not read as an absent one either.",
            scheme=scheme,
            witness_id=witness_id,
            recorded=recorded,
        )

    try:
        computed = chain_heads(conn)
    except CommitmentError as exc:
        return CommitmentCheck(
            CommitmentState.COULD_NOT_EVALUATE,
            f"the chain heads could not be recomputed from this artifact, so "
            f"the commitment was not checked against anything: {exc}",
            scheme=scheme,
            witness_id=witness_id,
            recorded=recorded,
        )

    if computed != recorded:
        moved = [
            name
            for name in ("declaration_head", "verdict_head")
            if getattr(computed, name) != getattr(recorded, name)
        ]
        return CommitmentCheck(
            CommitmentState.INVALID,
            "the committed heads are not the heads this artifact's records "
            f"produce ({', '.join(moved)} moved). The record chain was altered "
            "or re-issued after the commitment was made — which is the one "
            "thing a chain under the author's own keys cannot notice, and the "
            "reason this commitment exists.",
            scheme=scheme,
            witness_id=witness_id,
            recorded=recorded,
            computed=computed,
        )

    if witness is None:
        return CommitmentCheck(
            CommitmentState.COULD_NOT_EVALUATE,
            f"the committed heads match this artifact's records, but no witness "
            f"key was offered for {witness_id!r}, so the signature over them was "
            "not checked. The heads could have been rewritten to match a "
            "re-issued chain; only the witness key rules that out.",
            scheme=scheme,
            witness_id=witness_id,
            recorded=recorded,
            computed=computed,
        )
    if witness.witness_id != witness_id:
        return CommitmentCheck(
            CommitmentState.COULD_NOT_EVALUATE,
            f"this artifact was committed by witness {witness_id!r} and the "
            f"witness offered is {witness.witness_id!r}, so there is no key here "
            "for the signature on it. Not a finding about the artifact: a "
            "verifier holding the wrong witness has learned nothing.",
            scheme=scheme,
            witness_id=witness_id,
            recorded=recorded,
            computed=computed,
        )

    expected = hmac.new(
        witness.material,
        commitment_bytes(scheme, witness_id, recorded),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, str(token)):
        return CommitmentCheck(
            CommitmentState.INVALID,
            f"the commitment signature does not verify under witness "
            f"{witness_id!r}. The heads, the signature or the key is not the one "
            "that was committed.",
            scheme=scheme,
            witness_id=witness_id,
            recorded=recorded,
            computed=computed,
        )
    return CommitmentCheck(
        CommitmentState.VALID,
        f"the chain heads match this artifact's records and are signed by "
        f"witness {witness_id!r}. A second on-site party saw these heads; this "
        "is not a third-party timestamp.",
        scheme=scheme,
        witness_id=witness_id,
        recorded=recorded,
        computed=computed,
    )
