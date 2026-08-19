"""The hash chain and the keyed MACs. **Layer A** — this is part of the record.

WHAT THIS FILE IS FOR
---------------------
Every `Declaration` (Phase 3) and every `Verdict` (Phase 4) carries a `prev_hash`
linking it to its predecessor and a `mac` under the key of the party that issued
it. Together those give the record two properties an audit needs and a log file
does not have: a reader can tell that no record was altered, and a reader can
tell *which side* issued each one.

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
"""

from __future__ import annotations

import dataclasses
import hashlib
import hmac
import json
import math
import os
import secrets
from enum import Enum
from pathlib import Path
from typing import Literal, get_args

from reg.stream import ENCODING, FLOAT_PRECISION

__all__ = [
    "GENESIS_HASH",
    "HASH_HEX_LEN",
    "KEY_BYTES",
    "MAC_FIELD",
    "ROLES",
    "UNSIGNED_MAC",
    "CanonicalizationError",
    "Key",
    "KeyRoleError",
    "Keyring",
    "KeyringError",
    "MacCheck",
    "MacState",
    "Role",
    "canonical_bytes",
    "chain_hash",
    "generate_keyring",
    "is_hash",
    "load_keyring",
    "sign",
    "signing_bytes",
    "verify",
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
