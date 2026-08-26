"""The hash chain and the keyed MACs. **Layer A** — this is part of the record.

WHAT THIS FILE IS FOR
---------------------
Every `Declaration` (Phase 3) and every `Verdict` (Phase 4) carries a `prev_hash`
linking it to its predecessor and a `mac` under the key of the party that issued
it. Together those give the record two properties an audit needs and a log file
does not have: a reader can tell that no record was altered, and a reader can
tell *which side* issued each one.

WHERE THIS CONSTRUCTION COMES FROM — IT IS NOT THIS PROJECT'S
-------------------------------------------------------------
A per-record MAC plus a per-record hash link to the predecessor, over one
canonical preimage, walked by a verifier that checks both, is **Schneier, B. and
Kelsey, J., "Cryptographic Support for Secure Logs on Untrusted Machines"**, 7th
USENIX Security Symposium, 1998 — journal version, "Secure Audit Logs to Support
Computer Forensics", ACM TISSEC 2(2), 1999; forward integrity for logs is due to
Bellare and Yee. This module is that scheme **minus its forward security**: the
1998 construction evolves the secret after every entry and deletes the old value,
so an attacker who takes the machine cannot forge anything written before the
compromise, and `reg`'s keys are static for the life of a run. That absence is
deliberate and is written down as a limitation, not left here as a footnote —
`docs/limitations.md` §7, and `docs/prior-art.md` §14 for what the comparison
costs the project's claims. Nothing about this chain is novel; two things about
it are not in the ancestor (two chains under role-typed keys, and a verifier with
three outcomes) and both are below.

THE CRUX IS THE SERIALIZATION, NOT THE HASH
-------------------------------------------
SHA-256 and HMAC are stdlib and uninteresting. The part that can actually be got
wrong is `canonical_bytes`: a chain over a serialization that varies between
processes is a chain over nothing, because the auditor recomputing it months
later gets different bytes and therefore a different hash for a record nobody
touched. So:

* **Field order is the dataclass definition order.** Not `vars()`, not a dict,
  not `json.dumps` over a mapping — those are stable in CPython today and were
  not always, and `PYTHONHASHSEED` still moves set iteration.
* **Floats are fixed-precision decimal**, at `reg.stream.FLOAT_PRECISION`. That
  is deliberately the same discipline the raw stream is written with rather than
  a second float format: a record commits to values at the resolution the
  artifact states, and `repr(float)` is shortest-round-trip, so it varies in
  width with the value.
* **Every field is length-prefixed and type-tagged.** `("ab", "c")` and
  `("a", "bc")` must not have the same preimage, and the string `"1"` must not
  have the same preimage as the integer `1`.
* **Encoding is explicit** (`reg.stream.ENCODING`, UTF-8), never the platform
  default.
* **Domain separators** (`_RECORD_DOMAIN`, `_SIGNING_DOMAIN`, `_LINK_DOMAIN`)
  keep the three preimages disjoint, so a MAC over a record can never be
  replayed as a chain link or vice versa, and a change to what is hashed is a
  visible version bump rather than a silent re-baseline.

A consequence worth stating plainly: because floats are committed at
`FLOAT_PRECISION`, a change to a float field smaller than that resolution does
not change the record's hash. The record is a statement at the artifact's stated
precision, and everything downstream — the raw stream, the graph's quantization
— is coarser than it.

THE TWO KEYS
------------
The policy signs declarations; enforcement signs verdicts. The whole argument of
Phase 4 is that those are different parties, so this module refuses to let one
stand in for the other: a `Key` carries its `role`, each record class names the
`SIGNING_ROLE` that may sign it, and `sign`/`verify` raise `KeyRoleError` on a
mismatch rather than producing a MAC that would verify. `Keyring` holds both, but
the only way out of it is `.key(role)`.

**Honesty note, which also lives in the README:** both keys live in the same
process here. That demonstrates the *structure* of non-repudiation, not
non-repudiation. A real deployment needs the enforcement key in hardware the
policy vendor cannot reach — the same independence argument as the layer
separation, one level down.

THREE STATES, NOT A BOOL
------------------------
`verify` returns a `MacCheck`, never a bool. A record whose MAC cannot be checked
— no key available, an unsigned or malformed `mac`, a field that will not
serialize — is neither valid nor invalid, and the third state must not collapse
into either. `MacCheck.__bool__` raises for exactly that reason: `if verify(...)`
is a bug this module refuses to let compile into behaviour.

THE VERIFICATION HALF: `verify_chain` AND `tamper` (issue #49)
--------------------------------------------------------------
Everything above produces a chain. `verify_chain(conn, keyring)` is the thing an
assessor actually runs over one: it walks **both** chains a `reg.store` artifact
holds — declarations under the policy key, verdicts under the enforcement key,
kept separate because they are two parties — and reports, per chain, how many
records it walked, how many links and MACs it checked, and every failure with the
record it belongs to.

`ChainState` has the same three values `MacCheck` has, for the same reason, and
`ChainReport.__bool__` raises for the same reason. **An artifact with nothing in
it is not a verified artifact**: no record stream, no stated count, an empty
chain, an unreadable row and an absent key are all COULD-NOT-EVALUATE, and none
of them is VERIFIED. A verifier that reported an empty file as verified would be
the check-that-cannot-fail this repository is built against.

`tamper` is the demonstration that it *can* fail, and it is not a convenience:
a tamper-evidence mechanism never shown to detect tampering is worth nothing. It
mutates exactly one record — a field, a `mac`, a `prev_hash`, or the record
itself — in a **copy**, reports what it changed, and refuses to write anywhere
near the original. The artifact under audit is the evidence; a tool that edits it
in place is a tool that destroys what it was pointed at.

Neither of them repairs anything. There is no code path here that rewrites a
record to make a chain verify: a verifier that can fix is a verifier that can
forge. `tamper` can re-sign, and that is the opposite — it exists so the
**re-signed record is still BROKEN** at its successor, which is the case that
shows the chain is doing work the MAC alone cannot.

WHAT TRUNCATION COSTS, AND THE HONEST LIMIT OF DETECTING IT
------------------------------------------------------------
Deleting the *last* record of a chain breaks no link: every record that remains
still commits to its predecessor. Two witnesses in the artifact catch it anyway —
the record counts `reg.graph` writes into `meta`, and the `FOLLOWS` edges, one of
which is left pointing at a record the file no longer holds. **Neither is covered
by a MAC**, so an attacker who edits the count and drops the edge as well is not
detected by this walk, and that is stated here rather than left to be discovered.
What defeats it is an external commitment to the final chain hash, which is a
deployment question (the same one the honesty note above is about) and not
something this file can solve on its own.

**This is a named attack against this exact construction, and it has a published
answer this module does not implement.** It is the *truncation attack*, named
against Schneier–Kelsey by **Ma, D. and Tsudik, G., "A New Approach to Secure
Logging"** (IACR ePrint 2008/185): the adversary erases a contiguous run of
tail-end entries, no `Yᵢ` protects anything written after `i`, and nothing detects
it unless a trusted party knows the current record count. Their answer is a
forward-secure *aggregate* MAC, which makes verification all-or-nothing without a
trusted server. The structural answer is older and is a different data structure:
**Crosby, S. and Wallach, D., "Efficient Data Structures for Tamper-Evident
Logging"** (USENIX Security 2009) — the *history tree* — and its deployed
descendant, **Certificate Transparency** (Laurie, Langley & Kasper, RFC 6962,
2013; RFC 9162, 2021). In a Merkle-tree log a *consistency proof* against any
previously published head shows that the tree is a prefix extension of the earlier
one, so removing anything committed before it is detected, and an *inclusion
proof* needs a logarithmic number of hashes rather than the records in between.
A chain gives neither. Arriving independently at a correct statement of a known
limitation is fine; presenting it as though it were peculiar to this artifact is
not, which is why the citations are here. `docs/prior-art.md` §14 and §18 hold the
comparison in full, and whether the chain should become a tree is a Phase 6 design
question, not something to decide in a module header.
"""

from __future__ import annotations

import dataclasses
import hashlib
import hmac
import json
import math
import os
import secrets
import sqlite3
from collections.abc import Iterable
from enum import Enum
from pathlib import Path
from typing import Literal, get_args

from reg import store
from reg.stream import ENCODING, FLOAT_PRECISION

__all__ = [
    "ATTESTATION_PRESENT",
    "CHAINS",
    "FAILURE_KINDS",
    "GENESIS_HASH",
    "HASH_HEX_LEN",
    "KEY_BYTES",
    "MAC_FIELD",
    "META_ATTESTATION_RECORDS",
    "META_DECLARATION_COUNT",
    "META_VERDICT_COUNT",
    "ROLES",
    "TAMPER_DELETE",
    "UNSIGNED_MAC",
    "CanonicalizationError",
    "ChainFailure",
    "ChainReport",
    "ChainResult",
    "ChainSpec",
    "ChainState",
    "Key",
    "KeyRoleError",
    "Keyring",
    "KeyringError",
    "MacCheck",
    "MacState",
    "Role",
    "TamperError",
    "TamperReport",
    "TamperSpec",
    "canonical_bytes",
    "chain_hash",
    "chain_head",
    "generate_keyring",
    "is_hash",
    "load_keyring",
    "sign",
    "signing_bytes",
    "tamper",
    "verify",
    "verify_chain",
    "write_keyring",
]

#: Hex characters in a SHA-256 digest. Every `prev_hash` and every `mac` in the
#: record is exactly this long, and anything else is refused rather than padded.
HASH_HEX_LEN = 64

#: The link the first record of a chain commits to. This is a *definition* of
#: where a chain starts, not a chosen value: a record claiming any other
#: predecessor is claiming a predecessor, and the verifier must be able to tell
#: the two apart.
GENESIS_HASH = "0" * HASH_HEX_LEN

#: Key material length in bytes. 32 is the SHA-256 block-independent full-entropy
#: size HMAC-SHA256 is specified against; shorter keys are refused rather than
#: stretched, because a stretched key looks identical downstream to a strong one.
KEY_BYTES = 32

#: The field every chained record carries its MAC in. It is the one field the
#: MAC itself cannot cover.
MAC_FIELD = "mac"

#: The value of `mac` on a record that has not been signed yet. Explicit and
#: named: an empty string here is "no attribution", which is a
#: could-not-evaluate, and it must never read as "checked and fine".
UNSIGNED_MAC = ""

Role = Literal["policy", "enforcement"]

#: The two parties. Order is fixed — it is the order `write_keyring` emits.
ROLES: tuple[Role, ...] = get_args(Role)

# Domain separators. Three preimages that must never collide: the bytes a MAC is
# taken over, the bytes a record's own hash is taken over, and the bytes a chain
# link is taken over. Versioned, so a change to the serialization is a new
# constant and every old digest visibly stops matching instead of quietly
# re-baselining.
_SIGNING_DOMAIN = b"reg-chain-signing-v1\x00"
_RECORD_DOMAIN = b"reg-chain-record-v1\x00"
_LINK_DOMAIN = b"reg-chain-link-v1\x00"

# Field and record separators, ASCII unit/record separator. They are not
# load-bearing on their own — every field is length-prefixed, which is what makes
# the encoding unambiguous — but they keep a hexdump of a preimage readable when
# someone is working out why two digests differ.
_FIELD_SEP = b"\x1f"
_RECORD_SEP = b"\x1e"


class CanonicalizationError(ValueError):
    """A record could not be serialized canonically, so it cannot be hashed.

    Always a could-not-evaluate, never a fallback: a record with a field this
    module does not know how to commit to must not receive a digest computed over
    some other rendering of it.
    """


class KeyRoleError(ValueError):
    """A key of the wrong role was offered for a record.

    Not a verification failure — a caller error, and loud. Enforcement signing a
    declaration with the policy key would produce a MAC that verifies, and the
    attribution the whole phase exists to establish would be false.
    """


class KeyringError(ValueError):
    """A keyring file could not be read as a keyring.

    Missing, short, non-hex or extra material — all refusals. A partially read
    keyring would make every MAC taken under it unattributable in a way nothing
    downstream reports.
    """


class MacState(Enum):
    """The three outcomes of a MAC check. There is no fourth and no bool."""

    #: The MAC matches the record under the key offered.
    VALID = "valid"
    #: The MAC does not match. The record, the MAC or the key is not the one
    #: that was signed.
    INVALID = "invalid"
    #: The check could not be performed at all: no key, no MAC, a malformed MAC,
    #: or a record that will not serialize. **Never resolves to VALID.**
    COULD_NOT_EVALUATE = "could-not-evaluate"


@dataclasses.dataclass(frozen=True)
class MacCheck:
    """The result of `verify`: a state and the reason for it.

    `bool(check)` raises. That is the point — the third state exists precisely
    because callers write `if verify(...)`, and a could-not-evaluate that is
    falsy reads as "tampered" while one that is truthy reads as "fine". Both are
    wrong. Compare `check.state` against `MacState`.
    """

    state: MacState
    reason: str

    def __bool__(self) -> bool:  # pragma: no cover - exercised via pytest.raises
        raise TypeError(
            "a MacCheck has three states and cannot be used as a bool. "
            f"This one is {self.state.value}: {self.reason}. Compare .state "
            "against MacState.VALID / INVALID / COULD_NOT_EVALUATE — and handle "
            "COULD_NOT_EVALUATE explicitly, because it is neither of the others."
        )


@dataclasses.dataclass(frozen=True)
class Key:
    """One party's HMAC key, carrying the role it is allowed to act in.

    The role is part of the key rather than a convention at the call site, so
    "sign this declaration with the enforcement key" is a `KeyRoleError` and not
    a silently valid MAC attributing the policy's statement to enforcement.

    `repr` redacts the material: keys end up in tracebacks, pytest output and
    unattended CI logs otherwise.
    """

    role: Role
    material: bytes

    def __post_init__(self) -> None:
        if self.role not in ROLES:
            raise KeyRoleError(
                f"unknown key role {self.role!r}; the roles are {list(ROLES)}. "
                "A record is attributed to a party by the role of the key that "
                "signed it, so a role nothing recognises attributes it to nobody."
            )
        if not isinstance(self.material, bytes):
            raise KeyringError(
                f"key material for role {self.role!r} is a "
                f"{type(self.material).__name__}, not bytes."
            )
        if len(self.material) != KEY_BYTES:
            raise KeyringError(
                f"key material for role {self.role!r} is {len(self.material)} "
                f"bytes; this project's keys are exactly {KEY_BYTES}. Short "
                "material is refused rather than stretched — a stretched key is "
                "indistinguishable downstream from a strong one."
            )

    def __repr__(self) -> str:
        return f"Key(role={self.role!r}, material=<{KEY_BYTES} bytes, redacted>)"


@dataclasses.dataclass(frozen=True)
class Keyring:
    """Both keys, reachable only one at a time and only by role.

    It holds both because in this prototype both live in the same process — see
    the honesty note in the module docstring and in the README. What it does not
    do is offer an attribute a caller can pass the wrong key out of: `.key(role)`
    is the whole interface, and what comes back is a `Key` that knows its own
    role and will be refused by `sign` if it is the wrong one.
    """

    keys: tuple[Key, ...]

    def __post_init__(self) -> None:
        roles = tuple(k.role for k in self.keys)
        if sorted(roles) != sorted(ROLES):
            raise KeyringError(
                f"a keyring holds exactly one key per role {list(ROLES)}, got "
                f"{list(roles)}. A keyring missing a role would make every "
                "record signed by that party a could-not-evaluate, and one with "
                "a duplicate role has no defined answer for `key()`."
            )

    @classmethod
    def from_material(cls, *, policy: bytes, enforcement: bytes) -> Keyring:
        """Build a keyring from raw material. Both are required and named."""
        return cls(
            keys=(
                Key(role="policy", material=policy),
                Key(role="enforcement", material=enforcement),
            )
        )

    def key(self, role: Role) -> Key:
        """The key for `role`. Raises `KeyRoleError` for anything else."""
        for k in self.keys:
            if k.role == role:
                return k
        raise KeyRoleError(
            f"no key for role {role!r} in this keyring; the roles are {list(ROLES)}."
        )


def generate_keyring() -> Keyring:
    """A fresh keyring from OS entropy. **Deliberately not seeded.**

    Everything else in this project takes a seed so a run can be reproduced
    byte-for-byte. Key material is the one thing that must not: a seeded secret
    is not a secret, and a keyring recomputable from a number in the record would
    make every MAC in that record forgeable by its reader.

    The keyring is therefore an *input* to a run, not a product of one. Generate
    it once, `write_keyring` it, and pass the path.
    """
    return Keyring.from_material(
        policy=secrets.token_bytes(KEY_BYTES),
        enforcement=secrets.token_bytes(KEY_BYTES),
    )


def load_keyring(path: str | os.PathLike[str]) -> Keyring:
    """Read a keyring file: a JSON object of `role -> 64 hex characters`.

    Strict in every direction — a missing role, an unknown role, a short key or a
    non-hex string is a `KeyringError`. There is no partial keyring: a verifier
    holding half a keyring reports could-not-evaluate for half the record, and
    that is a state someone has to see rather than one to paper over.
    """
    path = Path(path)
    try:
        raw = path.read_text(encoding=ENCODING)
    except OSError as exc:
        raise KeyringError(f"{path}: keyring could not be read: {exc}") from None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise KeyringError(f"{path}: keyring is not valid JSON: {exc}") from None
    if not isinstance(payload, dict):
        raise KeyringError(
            f"{path}: keyring must be a JSON object of role -> hex key, got a "
            f"{type(payload).__name__}."
        )

    unknown = sorted(set(payload) - set(ROLES))
    if unknown:
        raise KeyringError(
            f"{path}: keyring names role(s) {unknown}, which this project does "
            f"not have; the roles are {list(ROLES)}. Refusing to load rather "
            "than ignore them — an extra role is either a typo that leaves a "
            "real role missing, or a key nothing will ever check."
        )
    missing = [role for role in ROLES if role not in payload]
    if missing:
        raise KeyringError(
            f"{path}: keyring is missing role(s) {missing}; the roles are "
            f"{list(ROLES)}."
        )

    material: dict[str, bytes] = {}
    for role in ROLES:
        value = payload[role]
        if not isinstance(value, str):
            raise KeyringError(
                f"{path}: key for role {role!r} is a {type(value).__name__}, not "
                "a hex string."
            )
        if len(value) != 2 * KEY_BYTES:
            raise KeyringError(
                f"{path}: key for role {role!r} is {len(value)} hex characters, "
                f"expected {2 * KEY_BYTES} ({KEY_BYTES} bytes)."
            )
        try:
            material[role] = bytes.fromhex(value)
        except ValueError:
            raise KeyringError(
                f"{path}: key for role {role!r} is not hexadecimal."
            ) from None

    return Keyring.from_material(
        policy=material["policy"], enforcement=material["enforcement"]
    )


def write_keyring(keyring: Keyring, path: str | os.PathLike[str]) -> Path:
    """Write a keyring to `path` as JSON. Returns the path.

    Byte-identical for the same keyring: fixed role order, two-space indent, a
    trailing newline. The file is written with owner-only permissions — it is
    secret material, and a keyring readable by every process on the host makes
    the attribution in the record decorative.
    """
    if not isinstance(keyring, Keyring):
        raise TypeError(f"write_keyring takes a Keyring, got {type(keyring).__name__}.")
    path = Path(path)
    payload = {role: keyring.key(role).material.hex() for role in ROLES}
    text = json.dumps(payload, indent=2, sort_keys=False) + "\n"
    # Opened through os.open so the mode applies at creation: writing first and
    # chmod-ing after leaves a window in which the keys are world-readable.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding=ENCODING) as handle:
        handle.write(text)
    return path


def is_hash(value: object) -> bool:
    """True for a lowercase 64-character hex digest, the only form used here."""
    return (
        isinstance(value, str)
        and len(value) == HASH_HEX_LEN
        and all(c in "0123456789abcdef" for c in value)
    )


def _require_hash(value: object, name: str) -> str:
    if not is_hash(value):
        raise ValueError(
            f"{name} must be {HASH_HEX_LEN} lowercase hex characters, got "
            f"{value!r}. A chain link that is not a digest links to nothing, and "
            f"a verifier comparing it would report a mismatch for the wrong "
            "reason."
        )
    return str(value)


def _fields(record: object) -> tuple[dataclasses.Field, ...]:
    """The record's fields in definition order, or a refusal.

    Definition order is the canonical order. It is a property of the class, so it
    is identical in every process, which `vars()`, `__dict__` iteration and any
    mapping-based encoding are not guaranteed to be.
    """
    if not dataclasses.is_dataclass(record) or isinstance(record, type):
        raise CanonicalizationError(
            f"a chained record must be a dataclass instance, got "
            f"{type(record).__name__}. The canonical field order is the "
            "dataclass definition order; there is no other order this module "
            "will invent for an arbitrary object."
        )
    fields = dataclasses.fields(record)
    names = {f.name for f in fields}
    if MAC_FIELD not in names:
        raise CanonicalizationError(
            f"{type(record).__name__} has no {MAC_FIELD!r} field, so it is not a "
            "chained record. Every record in this chain carries its own MAC."
        )
    return fields


def _encode_value(name: str, value: object) -> bytes:
    """One field, type-tagged and length-prefixed.

    The tag is what stops `"1"` and `1` sharing a preimage; the length prefix is
    what stops two adjacent fields being re-split. `bool` is checked before `int`
    because it is a subclass of it and `True` must not serialize as `1`.
    """
    if value is None:
        tag, payload = b"n", b""
    elif isinstance(value, bool):
        tag, payload = b"b", (b"true" if value else b"false")
    elif isinstance(value, int):
        tag, payload = b"i", str(value).encode(ENCODING)
    elif isinstance(value, float):
        tag, payload = b"f", _fixed(name, value).encode(ENCODING)
    elif isinstance(value, str):
        tag, payload = b"s", value.encode(ENCODING)
    elif isinstance(value, bytes):
        tag, payload = b"x", value.hex().encode("ascii")
    else:
        raise CanonicalizationError(
            f"field {name!r} is a {type(value).__name__}, which this module has "
            "no canonical encoding for. Encoding it as its repr or its str would "
            "commit the record to a rendering that is not stable across "
            "versions of Python or of the library that produced it — so the "
            "record does not get a digest at all. Convert it at the record "
            "boundary (geometry as WKB, arrays as bytes) and state the "
            "conversion there."
        )
    return b"".join(
        (
            name.encode(ENCODING),
            _FIELD_SEP,
            tag,
            _FIELD_SEP,
            str(len(payload)).encode("ascii"),
            _FIELD_SEP,
            payload,
            _RECORD_SEP,
        )
    )


def _fixed(name: str, value: float) -> str:
    """A float at `reg.stream.FLOAT_PRECISION`. Same discipline as the stream."""
    value = float(value)
    if not math.isfinite(value):
        raise CanonicalizationError(
            f"field {name!r} is {value!r}. A non-finite number in a record is a "
            "fault upstream, and committing to it would put 'nan' in a digest "
            "that later compares equal to another 'nan' from a different fault."
        )
    # `+ 0.0` normalises -0.0, which formats as '-0.000000' and would otherwise
    # give two numerically equal records two different digests.
    return f"{value + 0.0:.{FLOAT_PRECISION}f}"


def _body(record: object, *, include_mac: bool) -> bytes:
    parts = [type(record).__name__.encode(ENCODING), _RECORD_SEP]
    for f in _fields(record):
        if f.name == MAC_FIELD and not include_mac:
            continue
        parts.append(_encode_value(f.name, getattr(record, f.name)))
    return b"".join(parts)


def signing_bytes(record: object) -> bytes:
    """The preimage a MAC is taken over: every field except `mac` itself.

    Includes the class name, so a `Declaration` and a `Verdict` that happened to
    carry the same field values could never share a MAC.
    """
    return _SIGNING_DOMAIN + _body(record, include_mac=False)


def canonical_bytes(record: object) -> bytes:
    """The preimage the record's own hash is taken over: **every** field.

    The MAC is included here and excluded from `signing_bytes` — that is the
    difference between the two. A chain that hashed the record without its MAC
    would let someone swap one record's signature for another's without breaking
    a single link, which is exactly the attribution the chain exists to protect.
    """
    return _RECORD_DOMAIN + _body(record, include_mac=True)


def chain_hash(record: object, prev_hash: str) -> str:
    """SHA-256 over the record and its predecessor's hash. Hex, lowercase.

    `prev_hash` is passed explicitly even though a chained record carries it as a
    field: the argument is what the *caller* believes the predecessor was, and
    the two disagreeing is a caller error rather than a tamper finding, so it is
    raised rather than returned. For the first record of a chain, pass
    `GENESIS_HASH`.

    Raises:
        ValueError: `prev_hash` is not a digest, or the record's own `prev_hash`
            field disagrees with it.
        CanonicalizationError: the record cannot be serialized canonically.
    """
    prev = _require_hash(prev_hash, "prev_hash")
    own = getattr(record, "prev_hash", None)
    if own is not None and own != prev:
        raise ValueError(
            f"{type(record).__name__} carries prev_hash={own!r} but chain_hash "
            f"was asked for {prev!r}. One of the two is wrong and guessing which "
            "would produce a digest for a chain that does not exist."
        )
    return hashlib.sha256(
        _LINK_DOMAIN + bytes.fromhex(prev) + canonical_bytes(record)
    ).hexdigest()


def chain_head(records: Iterable[object]) -> str:
    """The running hash over a whole chain. `GENESIS_HASH` for an empty one.

    **Not** the same thing as `chain_hash(last, last.prev_hash)`, and the
    difference is the entire reason this function exists (issue #83). Every
    record carries its own predecessor link, so folding `chain_hash` over the
    list with each record's *carried* link produces a value that depends only on
    the final record: alter the first record of a hundred and that value does
    not move. A head is meant to summarise the chain, so the fold runs the
    **running** hash into each record instead.

    `canonical_bytes` covers every field including `prev_hash` and `mac`, so an
    edited link and a swapped signature both move the head too. On an intact
    chain the result is exactly the last record's `chain_hash`, which is what
    makes it the natural thing to commit to.

    Raises:
        CanonicalizationError: a record could not be serialized. There is no
            head over the records that happened to parse.
    """
    head = GENESIS_HASH
    for record in records:
        head = hashlib.sha256(
            _LINK_DOMAIN + bytes.fromhex(head) + canonical_bytes(record)
        ).hexdigest()
    return head


def _signing_role(record: object) -> Role:
    role = getattr(record, "SIGNING_ROLE", None)
    if role not in ROLES:
        raise KeyRoleError(
            f"{type(record).__name__} does not declare a SIGNING_ROLE in "
            f"{list(ROLES)} (got {role!r}). A record type that does not say which "
            "party signs it cannot be attributed to one."
        )
    return role  # type: ignore[return-value]


def _checked_key(record: object, key: object) -> Key:
    if not isinstance(key, Key):
        raise KeyRoleError(
            f"expected a Key, got {type(key).__name__}. Raw bytes are refused: "
            "the role travels with the key, and that is what makes signing a "
            "declaration with the enforcement key an error rather than a MAC "
            "that verifies."
        )
    role = _signing_role(record)
    if key.role != role:
        raise KeyRoleError(
            f"a {type(record).__name__} is signed by the {role!r} key; this key "
            f"is the {key.role!r} one. The two parties are the whole point of "
            "Phase 4 — see the independence argument in docs/plan.md. Refusing "
            "rather than producing a MAC that would verify and attribute the "
            "record to the wrong side."
        )
    return key


def sign(record: object, key: Key) -> str:
    """HMAC-SHA256 over `signing_bytes(record)`. Hex, lowercase.

    Raises:
        KeyRoleError: `key` is not a `Key`, or its role is not the one the
            record's class declares in `SIGNING_ROLE`.
        CanonicalizationError: the record cannot be serialized canonically — an
            unsigned record is the correct outcome there, not a MAC over some
            other rendering of it.
    """
    checked = _checked_key(record, key)
    return hmac.new(checked.material, signing_bytes(record), hashlib.sha256).hexdigest()


def verify(record: object, mac: object, key: Key | None) -> MacCheck:
    """Check `mac` against `record` under `key`. Three states, never a bool.

    Args:
        record: the record as it stands now. If any field has been altered since
            it was signed, the MAC will not match — that is the whole mechanism.
        mac: the MAC being checked, normally `record.mac`. Passed separately so a
            caller can check a MAC carried elsewhere (a sidecar, a store row)
            against the record it claims to cover.
        key: the key to check under, or `None` for "no key available". `None` is
            **could-not-evaluate**, not invalid: a verifier without the key has
            learned nothing about the record, and reporting that as tampering
            would be a false accusation with a signature on it.

    Returns:
        A `MacCheck`. `VALID` only when the record serialized, the MAC is
        well-formed, and the comparison succeeded.

    Raises:
        KeyRoleError: the key is of the wrong role for this record type. A
            caller error, not a verification outcome — see `sign`.
    """
    if key is None:
        return MacCheck(
            MacState.COULD_NOT_EVALUATE,
            f"no key available for role {_signing_role(record)!r}; the MAC was "
            "not checked. This is not a finding about the record.",
        )
    checked = _checked_key(record, key)

    if mac == UNSIGNED_MAC:
        return MacCheck(
            MacState.COULD_NOT_EVALUATE,
            "the record carries no MAC. An unsigned record is unattributed, "
            "which is a state to report, not a signature that failed.",
        )
    if not is_hash(mac):
        return MacCheck(
            MacState.COULD_NOT_EVALUATE,
            f"mac {mac!r} is not {HASH_HEX_LEN} lowercase hex characters, so "
            "there is nothing well-formed to compare against.",
        )

    try:
        preimage = signing_bytes(record)
    except CanonicalizationError as exc:
        return MacCheck(
            MacState.COULD_NOT_EVALUATE,
            f"the record could not be serialized canonically, so its MAC could "
            f"not be recomputed: {exc}",
        )

    expected = hmac.new(checked.material, preimage, hashlib.sha256).hexdigest()
    if hmac.compare_digest(expected, str(mac)):
        return MacCheck(MacState.VALID, f"MAC matches under the {checked.role!r} key.")
    return MacCheck(
        MacState.INVALID,
        f"MAC does not match under the {checked.role!r} key: the record, the "
        "MAC, or the key is not the one that was signed.",
    )


# --------------------------------------------------------------------------
# THE WALK (issue #49)
#
# The `meta` keys below are named here rather than imported from `reg.graph`,
# for the reason `reg.query` names its own: `reg.graph` imports this module, so
# importing it back would be a cycle, and it reaches the raw stream besides.
# `tests/test_chain.py::test_the_meta_keys_this_module_reads_are_the_ones_the_
# builder_writes` compares the two sides and fails on a rename — otherwise a
# renamed key turns every chain in every artifact into a could-not-evaluate,
# months later and in somebody else's terminal.
# --------------------------------------------------------------------------

#: Whether the build that wrote an artifact was handed a record stream at all.
#: `absent` and a run that produced no records are different facts and this key
#: is what separates them (`reg.graph.META_ATTESTATION_RECORDS`).
META_ATTESTATION_RECORDS = "attestation_records"

#: How many records the build says it stored, per chain. **This is the only
#: thing a walk can compare its own length against**, and it is what makes a
#: truncated chain detectable at all — see the module header for what that
#: costs, because these keys carry no MAC.
META_DECLARATION_COUNT = "declaration_count"
META_VERDICT_COUNT = "verdict_count"

#: The value of `META_ATTESTATION_RECORDS` that means a record stream was
#: supplied. Anything else — including the key being absent — is an artifact
#: nobody asked to store records in, which is a refusal and not an empty chain.
ATTESTATION_PRESENT = "present"


class ChainState(Enum):
    """The three verdicts a chain walk can reach. There is no fourth, no bool.

    The same three states as `MacState`, one level up, and they mean the same
    things: `BROKEN` is a finding about the artifact, `COULD_NOT_EVALUATE` is a
    finding about the *walk* — it says nothing was learned — and the two must
    never be reported as each other. Not having checked is not the same as
    having found a fault; an empty artifact is not a verified one.
    """

    #: Every record walked, every link held, every MAC matched.
    VERIFIED = "VERIFIED"
    #: A definite fault: a link that does not hold, a MAC that does not match, a
    #: record the artifact says it holds and does not.
    BROKEN = "BROKEN"
    #: The walk could not be performed, or could not be completed: no record
    #: stream, no stated count, no records, an unreadable row, no key.
    #: **Never resolves to VERIFIED.**
    COULD_NOT_EVALUATE = "COULD-NOT-EVALUATE"


#: What a failure is *about*. Fixed and small, like every other vocabulary here,
#: so a report can be filtered on it and an unknown kind is a detectable fault
#: rather than a category invented at a call site.
FAILURE_KINDS: tuple[str, ...] = (
    #: The record's MAC does not match under its party's key.
    "mac",
    #: The record's `prev_hash` is not its predecessor's chain hash.
    "link",
    #: The first record of the chain does not start at `GENESIS_HASH`.
    "genesis",
    #: The walk found a different number of records than the artifact states.
    "count",
    #: A `FOLLOWS` edge names a record this artifact no longer holds.
    "dangling-link",
    #: A chain of N records is not joined by N-1 `FOLLOWS` edges. Distinct from
    #: `dangling-link`, which reports edges that exist and point at nothing:
    #: deleting the edges too leaves none to dangle, and only a census sees that.
    "link-census",
    #: The `FOLLOWS` edges could not be read, so the census was not taken.
    "link-census-unreadable",
    #: A record names another record this artifact no longer holds, in a field
    #: covered by its own MAC. Unlike every other witness here, this one cannot
    #: be edited around without the signing key.
    "cross-reference",
    #: The referenced table could not be read, so the references were not checked.
    "cross-reference-unreadable",
    #: A stored row could not be read back as the record it claims to be.
    "unreadable",
    #: This chain holds no records, so nothing was checked.
    "no-records",
    #: The build was handed no record stream, so there is no chain to walk.
    "no-record-stream",
    #: No key for this chain's party, so no MAC on it was checked.
    "no-key",
    #: The artifact does not state how many records this chain should have.
    "no-count",
)


@dataclasses.dataclass(frozen=True)
class ChainSpec:
    """One of the two chains: which party signs it and where it is stored.

    Two chains and not one interleaved stream — `reg.graph` keeps them separate
    because they are two parties, and a walker that merged them would check the
    policy's links under the enforcement key.
    """

    #: The party whose key signs every record in this chain.
    role: Role
    #: The record class name, as `reg.store.RECORD_KINDS` spells it. It is also
    #: the `src_kind` of this chain's `FOLLOWS` edges.
    kind: str
    #: The table the records live in, the name of the record's own id field, and
    #: the surrogate key column that field resolves to (issue #55). The row is
    #: addressed by the surrogate; the *record* is still named by its id
    #: everywhere a person reads one, and `_row_key` is the single place the two
    #: meet.
    table: str
    id_field: str
    key_column: str
    #: The `reg.store` reader for this chain, by name. By name because the
    #: import is deferred (see `_read_records`).
    reader: str
    #: The `meta` key stating how many records this chain should hold.
    count_key: str


#: The two chains, in the order a report walks them.
CHAINS: tuple[ChainSpec, ...] = (
    ChainSpec(
        role="policy",
        kind="Declaration",
        table="declaration",
        id_field="declaration_id",
        key_column="declaration_key",
        reader="read_declarations",
        count_key=META_DECLARATION_COUNT,
    ),
    ChainSpec(
        role="enforcement",
        kind="Verdict",
        table="verdict",
        id_field="verdict_id",
        key_column="verdict_key",
        reader="read_verdicts",
        count_key=META_VERDICT_COUNT,
    ),
)


def _spec(role: Role) -> ChainSpec:
    for spec in CHAINS:
        if spec.role == role:
            return spec
    raise KeyRoleError(
        f"no chain for role {role!r}; the chains are {[s.role for s in CHAINS]}."
    )


@dataclasses.dataclass(frozen=True)
class ChainFailure:
    """One thing wrong, and **which record it belongs to**.

    The record id is the field this class exists for. An assessor's next question
    after "is the chain intact" is always *which one, and what changed*; a
    boolean cannot answer it, and a report that cannot answer it is not usable
    evidence. `record_id` is `None` only for a failure about the chain as a whole
    — a missing count, an absent key — and never because the failure is about a
    record the report declined to name.
    """

    chain: Role
    kind: str
    state: ChainState
    reason: str
    record_id: str | None = None
    seq: int | None = None
    #: For a `link` failure: the record whose chain hash the `prev_hash` above
    #: should have been. Named because a break has two ends and an assessor
    #: needs both — the successor is where it is *detected*, the predecessor is
    #: usually where it was *done*.
    predecessor_id: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in FAILURE_KINDS:
            raise ValueError(
                f"failure kind {self.kind!r} is not in {list(FAILURE_KINDS)}. "
                "The vocabulary is fixed so a report can be filtered on it."
            )
        if self.state is ChainState.VERIFIED:
            raise ValueError(
                "a ChainFailure is BROKEN or COULD-NOT-EVALUATE. A failure "
                "recorded as VERIFIED would be counted as a finding and "
                "reported as none."
            )

    def describe(self) -> str:
        """One line: what is wrong, and with which record."""
        where = "" if self.record_id is None else f" [{self.record_id}]"
        if self.seq is not None:
            where += f" (seq {self.seq})"
        if self.predecessor_id is not None:
            where += f" -> predecessor [{self.predecessor_id}]"
        return f"{self.state.value} {self.kind}{where}: {self.reason}"


@dataclasses.dataclass(frozen=True)
class ChainResult:
    """One chain's walk: what was checked, and everything that was wrong.

    The three counts are reported whatever the verdict, because "VERIFIED over
    zero links" and "VERIFIED over two hundred" are not the same statement and a
    verdict on its own does not distinguish them. `records_walked` against
    `stated_records` is the truncation check written out where a reader can see
    both numbers.

    `links_checked` counts the genesis link too, so it equals `records_walked` on
    an intact chain: a first record that claims a predecessor is a check that can
    fail, and leaving it out of the count would report N records held together by
    N-1 checks when N were made.
    """

    chain: Role
    kind: str
    state: ChainState
    records_walked: int
    links_checked: int
    macs_checked: int
    #: What the artifact says this chain holds, or `None` if it does not say.
    stated_records: int | None
    failures: tuple[ChainFailure, ...]


@dataclasses.dataclass(frozen=True)
class ChainReport:
    """Both chains. `bool(report)` raises — there are three states.

    Exactly `MacCheck.__bool__`'s reason, one level up: `if verify_chain(...)`
    reads as "is this artifact fine", and a could-not-evaluate is neither yes nor
    no. Compare `.state` against `ChainState`.
    """

    chains: tuple[ChainResult, ...]

    @property
    def state(self) -> ChainState:
        """The whole artifact's verdict.

        BROKEN if any chain is broken — a definite fault anywhere is a fault,
        and it outranks a chain that could not be evaluated, because the fault
        was actually found. VERIFIED only if **every** chain verified.
        """
        states = {result.state for result in self.chains}
        if ChainState.BROKEN in states:
            return ChainState.BROKEN
        if ChainState.COULD_NOT_EVALUATE in states or not states:
            return ChainState.COULD_NOT_EVALUATE
        return ChainState.VERIFIED

    @property
    def failures(self) -> tuple[ChainFailure, ...]:
        """Every failure from every chain, in walk order."""
        return tuple(f for result in self.chains for f in result.failures)

    def __bool__(self) -> bool:  # pragma: no cover - exercised via pytest.raises
        raise TypeError(
            "a ChainReport has three states and cannot be used as a bool. "
            f"This one is {self.state.value}. Compare .state against "
            "ChainState.VERIFIED / BROKEN / COULD_NOT_EVALUATE — and handle "
            "COULD_NOT_EVALUATE explicitly: an artifact that could not be "
            "checked is not an artifact that passed."
        )


def _read_records(conn: sqlite3.Connection, spec: ChainSpec) -> list:
    """This chain's records, in stored order.

    Order is `reg.store`'s — `(seq, id)` — which is the order the chain was
    written in and the only one two readers of one artifact are guaranteed to
    agree on. A stream whose `seq` was reordered by tampering is not re-sorted
    here into the order that would verify: the links are checked against the
    order the artifact presents, and a reorder breaks them, which is the
    `replay_or_reorder` fault being visible rather than repaired.
    """
    return getattr(store, spec.reader)(conn)


def _walk(
    conn: sqlite3.Connection, spec: ChainSpec, keyring: Keyring | None
) -> ChainResult:
    """One chain, end to end. Never raises for a fault it can report."""
    failures: list[ChainFailure] = []

    stated: int | None = None
    stated_text = store.get_meta(conn, spec.count_key)
    if stated_text is None:
        failures.append(
            ChainFailure(
                chain=spec.role,
                kind="no-count",
                state=ChainState.COULD_NOT_EVALUATE,
                reason=(
                    f"the artifact states no {spec.count_key!r}, so the walk has "
                    "nothing to compare its own length against and cannot tell a "
                    "complete chain from one with its tail removed."
                ),
            )
        )
    else:
        try:
            stated = int(stated_text)
        except ValueError:
            failures.append(
                ChainFailure(
                    chain=spec.role,
                    kind="no-count",
                    state=ChainState.COULD_NOT_EVALUATE,
                    reason=(
                        f"meta[{spec.count_key!r}] is {stated_text!r}, which is "
                        "not a count. Refusing to guess what it meant."
                    ),
                )
            )

    try:
        records = _read_records(conn, spec)
    except (store.StoreError, ValueError, sqlite3.DatabaseError) as exc:
        failures.append(
            ChainFailure(
                chain=spec.role,
                kind="unreadable",
                state=ChainState.COULD_NOT_EVALUATE,
                reason=(
                    f"a stored {spec.kind} could not be read back as the record "
                    f"it claims to be, so this chain was not walked: {exc}"
                ),
            )
        )
        return _result(spec, 0, 0, 0, stated, failures)

    if not records:
        failures.append(
            ChainFailure(
                chain=spec.role,
                kind="no-records",
                state=ChainState.COULD_NOT_EVALUATE,
                reason=(
                    f"this artifact holds no {spec.kind} at all, so nothing was "
                    "checked. An artifact with nothing in it is not a verified "
                    "artifact — and if the run genuinely produced none, that is "
                    "a fact about the run and not a chain that passed."
                ),
            )
        )
        return _result(spec, 0, 0, 0, stated, failures)

    key: Key | None = None
    if keyring is None:
        failures.append(
            ChainFailure(
                chain=spec.role,
                kind="no-key",
                state=ChainState.COULD_NOT_EVALUATE,
                reason=(
                    f"no key for the {spec.role!r} party, so none of the "
                    f"{len(records)} MACs on this chain was checked. This is not "
                    "a finding about the records: the links below were still "
                    "walked, and an unchecked MAC is unchecked, not invalid."
                ),
            )
        )
    else:
        key = keyring.key(spec.role)

    links_checked = 0
    macs_checked = 0
    previous_hash: str | None = None
    previous_id: str | None = None
    walked_ids: set[str] = set()

    for record in records:
        record_id = str(getattr(record, spec.id_field))
        seq = int(record.seq)
        walked_ids.add(record_id)

        if key is not None:
            check = verify(record, record.mac, key)
            if check.state is MacState.VALID:
                macs_checked += 1
            elif check.state is MacState.INVALID:
                macs_checked += 1
                failures.append(
                    ChainFailure(
                        chain=spec.role,
                        kind="mac",
                        state=ChainState.BROKEN,
                        reason=check.reason,
                        record_id=record_id,
                        seq=seq,
                    )
                )
            else:
                failures.append(
                    ChainFailure(
                        chain=spec.role,
                        kind="mac",
                        state=ChainState.COULD_NOT_EVALUATE,
                        reason=check.reason,
                        record_id=record_id,
                        seq=seq,
                    )
                )

        expected = GENESIS_HASH if previous_hash is None else previous_hash
        links_checked += 1
        if record.prev_hash != expected:
            if previous_id is None:
                failures.append(
                    ChainFailure(
                        chain=spec.role,
                        kind="genesis",
                        state=ChainState.BROKEN,
                        reason=(
                            f"the first {spec.kind} of this chain carries "
                            f"prev_hash={record.prev_hash!r}, not the genesis "
                            f"hash. It claims a predecessor, and this artifact "
                            "holds none — either a record was removed from the "
                            "front of the chain or this one was not the first."
                        ),
                        record_id=record_id,
                        seq=seq,
                    )
                )
            else:
                failures.append(
                    ChainFailure(
                        chain=spec.role,
                        kind="link",
                        state=ChainState.BROKEN,
                        reason=(
                            f"prev_hash={record.prev_hash!r} is not the chain "
                            f"hash of the record before it ({expected!r}). "
                            "Either this record's link was altered or the record "
                            "it commits to was altered after it was signed."
                        ),
                        record_id=record_id,
                        seq=seq,
                        predecessor_id=previous_id,
                    )
                )

        # The running hash is computed from the link the record *carries*, not
        # from the one it should have carried. Recomputing it from `expected`
        # would silently re-base the rest of the chain onto the tampered record
        # and report one break where there is one break — which is right — but
        # it would do it by asserting a link nobody made.
        try:
            previous_hash = chain_hash(record, record.prev_hash)
        except (ValueError, CanonicalizationError) as exc:
            failures.append(
                ChainFailure(
                    chain=spec.role,
                    kind="unreadable",
                    state=ChainState.COULD_NOT_EVALUATE,
                    reason=(
                        f"this record's own hash could not be computed, so every "
                        f"link after it is unchecked: {exc}"
                    ),
                    record_id=record_id,
                    seq=seq,
                )
            )
            previous_hash = None
        previous_id = record_id

    if stated is not None and stated != len(records):
        failures.append(
            ChainFailure(
                chain=spec.role,
                kind="count",
                state=ChainState.BROKEN,
                reason=(
                    f"the artifact states {stated} {spec.kind} record(s) in "
                    f"meta[{spec.count_key!r}] and the walk found "
                    f"{len(records)}. Records were removed from — or added to — "
                    "this artifact after it was built; deleting the last record "
                    "of a chain breaks no link, so this count is one of the two "
                    "things that can notice it."
                ),
            )
        )

    failures.extend(_dangling_links(conn, spec, walked_ids))
    failures.extend(_link_edge_census(conn, spec, walked_ids))
    failures.extend(_cross_referenced_records(conn, spec, records))
    return _result(spec, len(records), links_checked, macs_checked, stated, failures)


def _link_edge_census(
    conn: sqlite3.Connection, spec: ChainSpec, walked_ids: set[str]
) -> list[ChainFailure]:
    """A chain of N records must be joined by exactly N-1 `FOLLOWS` edges.

    `_dangling_links` reports edges that **exist and point at nothing**, which
    means deleting the edges too leaves nothing to dangle and reads as a pass.
    `DELETE FROM edge WHERE type='FOLLOWS'` verified clean before this existed.
    An empty witness list rendering as a pass is the inversion CLAUDE.md forbids,
    so the count is asserted rather than the survivors inspected.

    The edge rows are not covered by any MAC, so this is a *witness* and not
    proof — an attacker who edits records and edges consistently defeats it.
    `_cross_referenced_records` is the check that does not have that property.
    """
    walked = len(walked_ids)
    if walked < 1:
        return []
    expected = walked - 1
    try:
        rows = store.read_edges(conn, edge_type="FOLLOWS")
    except (store.StoreError, sqlite3.DatabaseError) as exc:
        return [
            ChainFailure(
                chain=spec.role,
                kind="link-census-unreadable",
                state=ChainState.COULD_NOT_EVALUATE,
                reason=(
                    "the FOLLOWS edges could not be read, so the walk cannot "
                    f"say whether this chain's {expected} link edge(s) are present: {exc}"
                ),
            )
        ]
    # A COARSENED VIEW HAS NO EDGE LAYER, AND THAT IS NOT TAMPERING.
    # `reg.bench.materialize_level` builds the occurrence view with a bare
    # `DELETE FROM edge`: the level retains events and not relationships, and it
    # says so in its own retention rule. A census run against it would report
    # every link edge missing and call a correct projection broken.
    #
    # The artifact carries the distinction without needing a flag. Dropping the
    # edge layer takes *every* edge; removing the link edges alone leaves the
    # others behind. So no edges at all is could-not-evaluate — this view cannot
    # be asked — and edges present with the links missing is the finding.
    # `rows` being empty is NOT the test: deleting every FOLLOWS edge also empties
    # it, and that is the attack. What separates a coarsened view from a tampered
    # one is whether the edge layer is gone *entirely*.
    try:
        any_edge = conn.execute("SELECT 1 FROM edge LIMIT 1").fetchone() is not None
    except sqlite3.DatabaseError:
        any_edge = True
    if not any_edge:
        return [
            ChainFailure(
                chain=spec.role,
                kind="link-census-unreadable",
                state=ChainState.COULD_NOT_EVALUATE,
                reason=(
                    "this artifact holds no edges at all, so its link edges could "
                    "not be counted. A view that dropped the edge layer is not a "
                    "chain with its links removed, and this is not a pass: what "
                    "the census would have checked went unchecked."
                ),
            )
        ]
    found = sum(1 for r in rows if str(r["src_id"]) in walked_ids)
    if found == expected:
        return []
    return [
        ChainFailure(
            chain=spec.role,
            kind="link-census",
            state=ChainState.BROKEN,
            reason=(
                f"{walked} {spec.kind} record(s) must be joined by {expected} "
                f"FOLLOWS edge(s); the artifact holds {found}. Edges were "
                "removed after the build. Deleting every link edge leaves none to "
                "dangle, so counting them is what notices it."
            ),
        )
    ]


def _cross_referenced_records(
    conn: sqlite3.Connection, spec: ChainSpec, records: list[object]
) -> list[ChainFailure]:
    """A record naming another record the artifact no longer holds.

    **This is the check that cannot be edited around.** A `Verdict` carries
    `declaration_id`, and `signing_bytes` covers every field except the MAC, so
    the reference is *inside the enforcement signature*. Delete the declaration,
    fix `meta[declaration_count]`, drop the link edges — all unauthenticated, all
    editable — and the surviving verdict still names the record that is gone, in
    a field nobody can change without invalidating a MAC they cannot forge.

    The artifact held that evidence all along and did not look at it.
    """
    if spec.role != "enforcement":
        return []
    try:
        held = {d.declaration_id for d in store.read_declarations(conn)}
    except (store.StoreError, ValueError, sqlite3.DatabaseError) as exc:
        return [
            ChainFailure(
                chain=spec.role,
                kind="cross-reference-unreadable",
                state=ChainState.COULD_NOT_EVALUATE,
                reason=(
                    "the declarations could not be read, so the verdicts' "
                    f"references to them were not checked: {exc}"
                ),
            )
        ]
    out: list[ChainFailure] = []
    for record in records:
        named = getattr(record, "declaration_id", None)
        if named is None or named in held:
            continue
        out.append(
            ChainFailure(
                chain=spec.role,
                kind="cross-reference",
                state=ChainState.BROKEN,
                reason=(
                    f"this verdict adjudicates {named!r} and the artifact holds no "
                    "such declaration. The reference is inside the enforcement "
                    "MAC, so it is evidence the record was removed that nobody "
                    "could edit without the enforcement key."
                ),
                record_id=getattr(record, "verdict_id", None),
            )
        )
    return out


def _dangling_links(
    conn: sqlite3.Connection, spec: ChainSpec, walked_ids: set[str]
) -> list[ChainFailure]:
    """`FOLLOWS` edges naming a record this artifact no longer holds.

    The second witness to a deleted record, and the one that does not depend on
    the `meta` counts: `reg.graph` writes an edge per link, so a record removed
    from either end of the chain leaves an edge pointing into nothing. Like the
    counts it is not covered by any MAC — see the module header.
    """
    rows = store.read_edges(conn, edge_type="FOLLOWS")
    out: list[ChainFailure] = []
    for row in rows:
        for end, kind_column, id_column in (
            ("source", "src_kind", "src_id"),
            ("target", "dst_kind", "dst_id"),
        ):
            if str(row[kind_column]) != spec.kind:
                continue
            record_id = str(row[id_column])
            if record_id in walked_ids:
                continue
            out.append(
                ChainFailure(
                    chain=spec.role,
                    kind="dangling-link",
                    state=ChainState.BROKEN,
                    reason=(
                        f"a FOLLOWS edge names this record as its {end}, and the "
                        f"{spec.table} table does not hold it. The link was "
                        "written when the record was there, so the record was "
                        "removed afterwards."
                    ),
                    record_id=record_id,
                )
            )
    return out


def _result(
    spec: ChainSpec,
    records_walked: int,
    links_checked: int,
    macs_checked: int,
    stated: int | None,
    failures: list[ChainFailure],
) -> ChainResult:
    """Assemble a `ChainResult` and derive its state from its failures.

    Derived rather than passed in, so there is no call site at which a chain
    with failures could be reported as verified.
    """
    states = {f.state for f in failures}
    if ChainState.BROKEN in states:
        state = ChainState.BROKEN
    elif ChainState.COULD_NOT_EVALUATE in states:
        state = ChainState.COULD_NOT_EVALUATE
    else:
        state = ChainState.VERIFIED
    return ChainResult(
        chain=spec.role,
        kind=spec.kind,
        state=state,
        records_walked=records_walked,
        links_checked=links_checked,
        macs_checked=macs_checked,
        stated_records=stated,
        failures=tuple(failures),
    )


def verify_chain(conn: sqlite3.Connection, keyring: Keyring | None) -> ChainReport:
    """Walk both record chains in an artifact and report on each.

    This is what an assessor runs. It reads only the artifact and the keyring:
    nothing is recomputed from a stream, nothing is repaired, and no record is
    written back under any circumstances.

    Args:
        conn: an artifact opened with `reg.store.connect` (its `row_factory`
            is what the record readers need).
        keyring: the keyring the records were signed under, or `None` for "no
            key available". **Required, with no default** — a caller that did
            not think about the key would otherwise get a report that looks like
            a verification and checked no signature. `None` is
            **could-not-evaluate for the MACs and nothing else**: the links are
            still walked and still reported, and a
            chain whose links hold but whose MACs were not checked comes back
            COULD-NOT-EVALUATE rather than VERIFIED. Not having checked is not
            the same as having found a fault, and it is not the same as having
            found none either.

    Returns:
        A `ChainReport`, one `ChainResult` per chain. `bool()` on it raises.

    Raises:
        sqlite3.DatabaseError: the connection is not an artifact at all. That is
            a caller error rather than a finding about a chain — `reg.store.
            connect` is what refuses a file that is not one.
    """
    records_meta = store.get_meta(conn, META_ATTESTATION_RECORDS)
    if records_meta != ATTESTATION_PRESENT:
        stated = (
            "this build was given no record stream at all"
            if records_meta is None or records_meta == "absent"
            else f"meta[{META_ATTESTATION_RECORDS!r}] is {records_meta!r}"
        )
        return ChainReport(
            chains=tuple(
                _result(
                    spec,
                    0,
                    0,
                    0,
                    None,
                    [
                        ChainFailure(
                            chain=spec.role,
                            kind="no-record-stream",
                            state=ChainState.COULD_NOT_EVALUATE,
                            reason=(
                                f"{stated}, so there is no {spec.kind} chain in "
                                "it to walk. That is a different fact from a run "
                                "that produced no records, and it is emphatically "
                                "not a chain that verified."
                            ),
                        )
                    ],
                )
                for spec in CHAINS
            )
        )
    return ChainReport(chains=tuple(_walk(conn, spec, keyring) for spec in CHAINS))


# --------------------------------------------------------------------------
# THE PROOF THAT THE WALK CAN SAY NO (issue #49)
# --------------------------------------------------------------------------

#: The tamper operation that removes a record rather than changing a field.
#: Spelled out because "delete the last record" is the easiest attack there is
#: and the one a walk over links alone cannot see.
TAMPER_DELETE = "delete"

#: SQLite declared type -> how a `--tamper` value is read off a command line.
#: A `BLOB` column is absent on purpose: a WKB geometry cannot be given as a
#: string, and coercing one would write bytes nobody typed.
_TAMPER_TYPES = {"INTEGER": int, "REAL": float, "TEXT": str}


class TamperError(ValueError):
    """A tamper request that will not be carried out as asked.

    Loud, and never a partial edit: an unparseable spec, a record that is not
    there, a column that does not exist, a value of the wrong type, a
    destination that already exists — or a request to write to the artifact
    itself, which is refused absolutely.
    """


@dataclasses.dataclass(frozen=True)
class TamperSpec:
    """Which record to alter, and how. Parsed from `CHAIN:SELECTOR:OP`.

        declaration:first:horizon=9.5      a field of a declaration
        verdict:#3:t=1.25                  a field of a verdict
        declaration:last:mac=0000...       the signature itself
        verdict:d_007:prev_hash=aaaa...    the link
        verdict:last:delete                remove the record

    `SELECTOR` is `first`, `last`, `#N` (position in chain order, from 0), or a
    record id. A position is offered because the interesting record is usually
    "not the last one" — a re-signed record only breaks its **successor**, so a
    tamper on the final record of a chain is the one case that proves nothing.
    """

    chain: Role
    selector: str
    field: str | None
    value: str | None
    #: Re-sign the record after altering it, under the key of the party that
    #: owns this chain. The point is not to hide the tamper — it is to show that
    #: hiding it from the MAC does not hide it from the chain.
    resign: bool = False

    def __post_init__(self) -> None:
        _spec(self.chain)  # refuses an unknown chain, naming the two
        if not self.selector:
            raise TamperError(
                "a tamper spec must say which record: first, last, #N, or an id."
            )
        if (self.field is None) != (self.value is None):
            raise TamperError(
                "a field tamper needs both a field and a value; "
                f"got field={self.field!r} value={self.value!r}."
            )
        if self.field is None and self.resign:
            raise TamperError(
                "re-signing a deleted record is not a thing. Re-signing exists "
                "to show that a record whose MAC was made to verify again still "
                "breaks the chain at its successor."
            )

    @property
    def deletes(self) -> bool:
        return self.field is None

    @classmethod
    def parse(cls, text: str, *, resign: bool = False) -> TamperSpec:
        """`CHAIN:SELECTOR:FIELD=VALUE` or `CHAIN:SELECTOR:delete`."""
        parts = str(text).split(":", 2)
        if len(parts) != 3:
            raise TamperError(
                f"tamper spec {text!r} is not CHAIN:SELECTOR:OP — for example "
                "'declaration:first:horizon=9.5', 'verdict:#3:mac=" + "0" * 64 + "' "
                f"or 'verdict:last:{TAMPER_DELETE}'."
            )
        chain, selector, op = parts
        if chain not in {spec.role for spec in CHAINS} | {
            spec.table for spec in CHAINS
        }:
            raise TamperError(
                f"tamper spec {text!r} names chain {chain!r}; the chains are "
                + ", ".join(f"{s.table} ({s.role})" for s in CHAINS)
                + "."
            )
        role = next(
            s.role for s in CHAINS if chain in (s.role, s.table)
        )
        if op == TAMPER_DELETE:
            # `resign` is passed through rather than dropped: a flag silently
            # ignored reads as one that was applied, and `__post_init__` is
            # where the combination is refused.
            return cls(
                chain=role,
                selector=selector,
                field=None,
                value=None,
                resign=resign,
            )
        if "=" not in op:
            raise TamperError(
                f"tamper spec {text!r} ends in {op!r}, which is neither "
                f"FIELD=VALUE nor {TAMPER_DELETE!r}."
            )
        field, _, value = op.partition("=")
        if not field:
            raise TamperError(f"tamper spec {text!r} names no field before '='.")
        return cls(chain=role, selector=selector, field=field, value=value, resign=resign)


@dataclasses.dataclass(frozen=True)
class TamperReport:
    """What was changed, where, and in which copy. **Not** a verdict.

    Reported rather than returned as a bool because the whole purpose is to be
    able to say, beside a BROKEN chain report, exactly which single edit
    produced it. A demonstration nobody can read the inputs of demonstrates
    nothing.
    """

    source: Path
    copy: Path
    chain: Role
    kind: str
    record_id: str
    seq: int
    field: str | None
    before: object
    after: object
    resigned: bool

    def describe(self) -> str:
        if self.field is None:
            what = f"deleted the {self.kind} record"
        else:
            what = f"set {self.field} {self.before!r} -> {self.after!r}"
            if self.resigned:
                what += ", and re-signed the record so its MAC verifies again"
        return (
            f"tampered {self.copy} (a copy of {self.source}): "
            f"{self.chain} chain, record [{self.record_id}] (seq {self.seq}) — "
            f"{what}."
        )


def _select(records: list, spec: ChainSpec, selector: str):
    """The one record a selector names, or a `TamperError` naming what is there."""
    if selector == "first":
        return records[0]
    if selector == "last":
        return records[-1]
    if selector.startswith("#"):
        try:
            index = int(selector[1:])
        except ValueError:
            raise TamperError(
                f"selector {selector!r} is not a position; write #0, #1, ..."
            ) from None
        if not -len(records) <= index < len(records):
            raise TamperError(
                f"selector {selector!r} is out of range: this chain holds "
                f"{len(records)} {spec.kind} record(s)."
            )
        return records[index]
    for record in records:
        if str(getattr(record, spec.id_field)) == selector:
            return record
    raise TamperError(
        f"this artifact holds no {spec.kind} with {spec.id_field}={selector!r}. "
        f"The first few are: "
        f"{[str(getattr(r, spec.id_field)) for r in records[:5]]}."
    )


def _row_key(conn: sqlite3.Connection, spec: ChainSpec, record_id: str) -> int:
    """The surrogate key of one record's row (issue #55).

    The tamper tool addresses rows by `node_key`, because that is what the record
    tables are keyed on since the identifiers moved into `node`. It refuses
    rather than guesses: a tamper that silently matched no row would report
    itself as applied and leave an untouched artifact behind, which is the one
    outcome a tamper demonstration must never produce.
    """
    key = store.node_key(conn, record_id)
    if key is None:
        raise TamperError(
            f"this artifact holds no node with id {record_id!r}, so there is no "
            f"{spec.kind} row to alter."
        )
    return key


def _column_type(conn: sqlite3.Connection, table: str, column: str) -> str:
    """The declared type of a column, or a `TamperError` naming the columns."""
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()  # noqa: S608
    columns = {str(row["name"]): str(row["type"]).upper() for row in rows}
    if column not in columns:
        raise TamperError(
            f"the {table} table has no column {column!r}; it has "
            f"{sorted(columns)}."
        )
    return columns[column]


def tamper(
    artifact: str | os.PathLike[str],
    out: str | os.PathLike[str],
    spec: TamperSpec | str,
    *,
    keyring: Keyring | None = None,
    resign: bool = False,
) -> TamperReport:
    """Alter exactly one record in a **copy** of an artifact. Never in place.

    The evidence is the artifact. So this copies it byte for byte, opens the
    copy, changes one value in one row, and reports what it changed — and
    refuses to write to the original, to an existing file, or to the same path
    it was given. There is no flag that turns any of those off.

    Args:
        artifact: the artifact to copy. It is opened read-only in effect: this
            function reads its bytes and never writes to it.
        out: where the tampered copy goes. Must not exist, and must not be the
            artifact.
        spec: a `TamperSpec`, or a `CHAIN:SELECTOR:OP` string to parse.
        keyring: needed only for `resign`. Absent, a re-sign is refused rather
            than performed under a key invented here.
        resign: re-sign the altered record under its own party's key, so its MAC
            verifies. Applied when the spec asks for it or when this argument
            does. **This makes the MAC pass and the chain still break**, at the
            successor, which is the case that shows the chain does work the MAC
            alone cannot.

    Returns:
        A `TamperReport` naming the copy, the record and the change.

    Raises:
        TamperError: anything about the request that will not be carried out —
            a bad spec, a missing record, an unknown column, a value of the
            wrong type, a destination that exists, a re-sign with no key.
    """
    source = Path(artifact)
    copy = Path(out)
    if not source.exists():
        raise TamperError(f"{source}: no such artifact. Nothing was copied.")
    if copy.resolve() == source.resolve():
        raise TamperError(
            f"{copy} is the artifact itself. A tamper is never applied in "
            "place: the artifact under audit is the evidence, and a tool that "
            "edits it destroys the thing it was pointed at."
        )
    if copy.exists():
        raise TamperError(
            f"{copy} already exists. Refusing to overwrite it — the one file "
            "this tool writes is a new copy, so that nothing it is pointed at "
            "can be lost by pointing it at the wrong path."
        )

    if isinstance(spec, str):
        spec = TamperSpec.parse(spec, resign=resign)
    elif resign:
        spec = dataclasses.replace(spec, resign=True)

    chain_spec = _spec(spec.chain)
    copy.write_bytes(source.read_bytes())

    conn = store.connect(copy)
    try:
        records = _read_records(conn, chain_spec)
        if not records:
            raise TamperError(
                f"{source} holds no {chain_spec.kind} to tamper with. A "
                "demonstration on an empty chain would demonstrate nothing."
            )
        record = _select(records, chain_spec, spec.selector)
        record_id = str(getattr(record, chain_spec.id_field))
        seq = int(record.seq)
        row_key = _row_key(conn, chain_spec, record_id)

        if spec.deletes:
            before = record_id
            # The record row goes and its `node` row stays (issue #55). That is
            # what a deletion from the record table actually looks like, and it
            # is what keeps the second witness readable: the FOLLOWS edge left
            # pointing at this record can still say *which* record is gone.
            conn.execute(
                f"DELETE FROM {chain_spec.table} "  # noqa: S608
                f"WHERE {chain_spec.key_column} = ?",
                (row_key,),
            )
            after: object = None
            field = None
        else:
            field = str(spec.field)
            declared = _column_type(conn, chain_spec.table, field)
            cast = _TAMPER_TYPES.get(declared)
            if cast is None:
                raise TamperError(
                    f"{chain_spec.table}.{field} is a {declared} column, and a "
                    "value for one cannot be given as text. The fields this "
                    f"tool can set are the {sorted(_TAMPER_TYPES)} ones."
                )
            try:
                after = cast(str(spec.value))
            except ValueError:
                raise TamperError(
                    f"{spec.value!r} is not a value for "
                    f"{chain_spec.table}.{field}, which is {declared}."
                ) from None
            row = conn.execute(
                f"SELECT {field} AS v FROM {chain_spec.table} "  # noqa: S608
                f"WHERE {chain_spec.key_column} = ?",
                (row_key,),
            ).fetchone()
            before = None if row is None else row["v"]
            conn.execute(
                f"UPDATE {chain_spec.table} SET {field} = ? "  # noqa: S608
                f"WHERE {chain_spec.key_column} = ?",
                (after, row_key),
            )

        resigned = False
        if spec.resign:
            if keyring is None:
                raise TamperError(
                    "re-signing needs the keyring the records were signed "
                    "under, and none was given. There is no key to invent here: "
                    "a MAC under made-up material would fail for the wrong "
                    "reason and prove nothing."
                )
            conn.commit()
            altered = _select(
                _read_records(conn, chain_spec), chain_spec, record_id
            )
            fresh = sign(altered, keyring.key(chain_spec.role))
            conn.execute(
                f"UPDATE {chain_spec.table} SET {MAC_FIELD} = ? "  # noqa: S608
                f"WHERE {chain_spec.key_column} = ?",
                (fresh, row_key),
            )
            resigned = True

        conn.commit()
    except Exception:
        # The half-tampered copy is deleted rather than left behind. A file
        # whose provenance is "something went wrong partway through altering
        # it" is the one artifact nobody should ever be handed.
        conn.close()
        copy.unlink(missing_ok=True)
        raise
    else:
        conn.close()

    return TamperReport(
        source=source,
        copy=copy,
        chain=chain_spec.role,
        kind=chain_spec.kind,
        record_id=record_id,
        seq=seq,
        field=field,
        before=before,
        after=after,
        resigned=resigned,
    )
