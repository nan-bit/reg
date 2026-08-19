"""The chain: canonical bytes, links, MACs, and the two keys.

Most of this file is negative. That is the point of the phase — a chain whose
tests only show that untouched records verify has demonstrated nothing, because
a `verify` that returns VALID unconditionally would pass every one of them. So
each mechanism is tested by breaking it: a mutated field, a swapped link, the
wrong key, no key, a malformed MAC, a field that will not serialize.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import subprocess
import sys
import textwrap

import pytest
import shapely
from shapely.geometry import Polygon

from reg.chain import (
    GENESIS_HASH,
    HASH_HEX_LEN,
    KEY_BYTES,
    ROLES,
    UNSIGNED_MAC,
    CanonicalizationError,
    Key,
    KeyRoleError,
    Keyring,
    KeyringError,
    MacState,
    canonical_bytes,
    chain_hash,
    generate_keyring,
    is_hash,
    load_keyring,
    sign,
    signing_bytes,
    verify,
    write_keyring,
)
from reg.declare import Declaration, envelope_wkb, sign_declaration
from reg.stream import FLOAT_PRECISION

POLICY_MATERIAL = bytes(range(KEY_BYTES))
ENFORCEMENT_MATERIAL = bytes(range(100, 100 + KEY_BYTES))
OTHER_POLICY_MATERIAL = bytes(range(200, 200 + KEY_BYTES))

KEYRING = Keyring.from_material(
    policy=POLICY_MATERIAL, enforcement=ENFORCEMENT_MATERIAL
)
POLICY_KEY = KEYRING.key("policy")
ENFORCEMENT_KEY = KEYRING.key("enforcement")
OTHER_POLICY_KEY = Key(role="policy", material=OTHER_POLICY_MATERIAL)

SQUARE_WKB = envelope_wkb(Polygon([(0, 0), (1, 0), (1, 1), (0, 1)]))
BIGGER_WKB = envelope_wkb(Polygon([(0, 0), (2, 0), (2, 1), (0, 1)]))


# A record type of this module's own, so the chain can be tested without
# depending on the shape of anything in declare.py — and so every supported
# field type (None, bool, int, float, str, bytes) is exercised somewhere.
@dataclasses.dataclass(frozen=True)
class ToyRecord:
    SIGNING_ROLE = "enforcement"

    left: str
    right: str
    count: int
    flag: bool
    when: float
    payload: bytes
    absent: str | None
    prev_hash: str
    mac: str


def toy(**overrides: object) -> ToyRecord:
    base: dict[str, object] = dict(
        left="ab",
        right="c",
        count=7,
        flag=True,
        when=1.5,
        payload=b"\x00\x01",
        absent=None,
        prev_hash=GENESIS_HASH,
        mac=UNSIGNED_MAC,
    )
    base.update(overrides)
    return ToyRecord(**base)  # type: ignore[arg-type]


def declaration(**overrides: object) -> Declaration:
    base: dict[str, object] = dict(
        declaration_id="fixture-decl-00000",
        seq=0,
        t_issued=0.25,
        horizon=0.5,
        action_class="reach",
        declared_envelope=SQUARE_WKB,
        prev_hash=GENESIS_HASH,
        mac=UNSIGNED_MAC,
    )
    base.update(overrides)
    return Declaration(**base)  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# Canonical serialization — the crux. A chain over a serialization that is not
# canonical is a chain over nothing.
# --------------------------------------------------------------------------


def test_canonical_bytes_are_stable_in_a_fresh_process() -> None:
    """Same record, same bytes, in another interpreter with another hash seed.

    Not just across calls: `PYTHONHASHSEED` and dict ordering bite exactly once,
    in the field, months later, when the auditor recomputes the chain. Same
    discipline as `tests/test_envelope.py::test_hash_is_stable_in_a_fresh_process`.
    """
    script = textwrap.dedent(
        """
        import hashlib
        from shapely.geometry import Polygon
        from reg.chain import GENESIS_HASH, UNSIGNED_MAC, canonical_bytes, chain_hash, signing_bytes
        from reg.declare import Declaration, envelope_wkb

        d = Declaration(
            declaration_id="fixture-decl-00000",
            seq=0,
            t_issued=0.25,
            horizon=0.5,
            action_class="reach",
            declared_envelope=envelope_wkb(Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])),
            prev_hash=GENESIS_HASH,
            mac=UNSIGNED_MAC,
        )
        print(hashlib.sha256(canonical_bytes(d)).hexdigest())
        print(hashlib.sha256(signing_bytes(d)).hexdigest())
        print(chain_hash(d, GENESIS_HASH))
        """
    )
    env = dict(os.environ, PYTHONHASHSEED="1")
    out = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    here = declaration()
    assert out.stdout.split() == [
        hashlib.sha256(canonical_bytes(here)).hexdigest(),
        hashlib.sha256(signing_bytes(here)).hexdigest(),
        chain_hash(here, GENESIS_HASH),
    ]


def test_every_field_is_covered_by_the_signature() -> None:
    """Changing any field but `mac` changes the preimage a MAC is taken over.

    An invariant rather than a golden value: a field added to `Declaration`
    later is covered by this test the day it is added, and one quietly excluded
    from the serialization fails it.
    """
    base = declaration()
    alternatives: dict[str, object] = {
        "declaration_id": "fixture-decl-00001",
        "seq": 1,
        "t_issued": 0.5,
        "horizon": 0.75,
        "action_class": "hold",
        "declared_envelope": BIGGER_WKB,
        "prev_hash": "a" * HASH_HEX_LEN,
    }
    covered = {f.name for f in dataclasses.fields(Declaration)} - {"mac"}
    assert set(alternatives) == covered, (
        "Declaration's fields changed; this test has to state a different value "
        "for every one of them or it stops proving they are all covered."
    )
    for name, value in alternatives.items():
        assert signing_bytes(dataclasses.replace(base, **{name: value})) != signing_bytes(
            base
        ), f"{name} does not affect the signing preimage"


def test_the_mac_is_in_the_record_hash_but_not_in_its_own_preimage() -> None:
    """The one asymmetry: a MAC cannot cover itself, but the chain covers it.

    If the chain hashed the record without its MAC, one record's signature could
    be swapped for another's without breaking a single link.
    """
    unsigned = declaration()
    signed = sign_declaration(unsigned, POLICY_KEY)
    assert signing_bytes(signed) == signing_bytes(unsigned)
    assert canonical_bytes(signed) != canonical_bytes(unsigned)
    assert chain_hash(signed, GENESIS_HASH) != chain_hash(unsigned, GENESIS_HASH)


def test_field_boundaries_cannot_be_re_split() -> None:
    """`("ab", "c")` and `("a", "bc")` must not share a preimage."""
    assert signing_bytes(toy(left="ab", right="c")) != signing_bytes(
        toy(left="a", right="bc")
    )


def test_a_number_and_its_text_do_not_share_a_preimage() -> None:
    """Type tags: `7` is not `"7"`, and `True` is not `1`."""
    assert signing_bytes(toy(count=7)) != signing_bytes(toy(count=True))
    assert signing_bytes(toy(left="7", count=7)) != signing_bytes(
        toy(left="7", count=77)
    )
    assert signing_bytes(toy(absent=None)) != signing_bytes(toy(absent=""))


def test_the_three_preimages_are_domain_separated() -> None:
    """A MAC preimage, a record preimage and a link preimage never collide."""
    record = toy()
    assert signing_bytes(record) != canonical_bytes(record)
    assert not canonical_bytes(record).startswith(signing_bytes(record)[:20])


def test_floats_are_fixed_precision_not_repr() -> None:
    """The stream's discipline, reused: same value, same width, every time."""
    assert f"{1 / 3:.{FLOAT_PRECISION}f}".encode() in signing_bytes(toy(when=1 / 3))
    # -0.0 and 0.0 are the same instant; they must not be two different records.
    assert signing_bytes(toy(when=-0.0)) == signing_bytes(toy(when=0.0))
    # And the stated consequence: the record commits to values at the artifact's
    # precision, so a difference below it is not a difference in the record.
    below = 10.0 ** -(FLOAT_PRECISION + 2)
    assert signing_bytes(toy(when=1.5 + below)) == signing_bytes(toy(when=1.5))
    above = 10.0 ** -(FLOAT_PRECISION - 1)
    assert signing_bytes(toy(when=1.5 + above)) != signing_bytes(toy(when=1.5))


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_a_non_finite_float_cannot_be_committed_to(value: float) -> None:
    with pytest.raises(CanonicalizationError, match="non-finite"):
        signing_bytes(toy(when=value))


def test_a_field_with_no_canonical_encoding_is_refused() -> None:
    """Could-not-evaluate: no digest at all, rather than a digest over a repr."""
    with pytest.raises(CanonicalizationError, match="no canonical encoding"):
        signing_bytes(toy(payload=[1, 2, 3]))  # type: ignore[arg-type]


def test_a_non_record_is_refused() -> None:
    with pytest.raises(CanonicalizationError, match="dataclass"):
        canonical_bytes({"declaration_id": "x"})

    @dataclasses.dataclass(frozen=True)
    class NoMac:
        SIGNING_ROLE = "policy"
        value: int

    with pytest.raises(CanonicalizationError, match="no 'mac' field"):
        canonical_bytes(NoMac(value=1))


# --------------------------------------------------------------------------
# The links.
# --------------------------------------------------------------------------


def chain_of(n: int) -> list[Declaration]:
    """`n` signed declarations, correctly linked. The fixture the walk uses."""
    out: list[Declaration] = []
    prev = GENESIS_HASH
    for seq in range(n):
        signed = sign_declaration(
            declaration(
                declaration_id=f"fixture-decl-{seq:05d}",
                seq=seq,
                t_issued=0.5 * seq,
                prev_hash=prev,
            ),
            POLICY_KEY,
        )
        out.append(signed)
        prev = chain_hash(signed, prev)
    return out


def links_hold(records: list[Declaration]) -> list[bool]:
    """Walk a chain: does each record link to the one actually before it?

    Deliberately written out here rather than imported: the verifier is the next
    issue's deliverable, and a test that used it would be testing that module
    against itself.
    """
    expected = GENESIS_HASH
    out: list[bool] = []
    for record in records:
        out.append(record.prev_hash == expected)
        expected = chain_hash(record, record.prev_hash)
    return out


def test_a_correct_chain_walks() -> None:
    records = chain_of(3)
    assert links_hold(records) == [True, True, True]
    assert records[0].prev_hash == GENESIS_HASH
    assert all(is_hash(r.prev_hash) for r in records)


def test_a_reordered_chain_is_detected() -> None:
    """NEGATIVE. Swap two records' links and the walk must not accept them."""
    a, b, c = chain_of(3)
    swapped = [a, dataclasses.replace(b, prev_hash=c.prev_hash), dataclasses.replace(c, prev_hash=b.prev_hash)]
    assert links_hold(swapped) != [True, True, True]
    # Order alone, without touching the links, is caught too: the third record
    # claims a predecessor that is no longer in front of it.
    assert links_hold([a, c, b]) != [True, True, True]


def test_a_dropped_record_is_detected() -> None:
    """NEGATIVE. Removing a record from the middle breaks the next one's link."""
    a, _b, c = chain_of(3)
    assert links_hold([a, c]) == [True, False]


def test_chain_hash_refuses_a_link_that_is_not_a_digest() -> None:
    with pytest.raises(ValueError, match="lowercase hex"):
        chain_hash(declaration(), "not-a-hash")
    with pytest.raises(ValueError, match="lowercase hex"):
        chain_hash(declaration(), ("ab" * (HASH_HEX_LEN // 2)).upper())
    with pytest.raises(ValueError, match="lowercase hex"):
        chain_hash(declaration(), "a" * (HASH_HEX_LEN - 1))


def test_chain_hash_refuses_to_disagree_with_the_record() -> None:
    """A caller error, and loud: two different beliefs about the predecessor."""
    with pytest.raises(ValueError, match="but chain_hash was asked for"):
        chain_hash(declaration(prev_hash="a" * HASH_HEX_LEN), GENESIS_HASH)


# --------------------------------------------------------------------------
# The MACs.
# --------------------------------------------------------------------------


def test_a_signed_record_verifies() -> None:
    signed = sign_declaration(declaration(), POLICY_KEY)
    assert is_hash(signed.mac)
    assert verify(signed, signed.mac, POLICY_KEY).state is MacState.VALID


def test_a_mutated_record_fails_its_mac() -> None:
    """NEGATIVE, and the test the whole phase exists for.

    Every field is mutated in turn, so this fails if any of them stops being
    covered — and the geometry is mutated by flipping a byte inside the WKB
    rather than by swapping in a different polygon, because a coordinate edited
    in place is what tampering with a declared bound would actually look like.
    """
    signed = sign_declaration(declaration(), POLICY_KEY)

    # WKB layout: 1 byte order + 4 type + 4 rings + 4 points, then 16 bytes per
    # point. Byte 29 is the low byte of the second point's x — an interior
    # vertex, so the ring still closes and the polygon is still valid, which is
    # what makes this a tamper rather than a corruption anyone would notice.
    payload = bytearray(signed.declared_envelope)
    payload[29] ^= 0x01
    mutations: list[Declaration] = [
        dataclasses.replace(signed, declared_envelope=bytes(payload)),
        dataclasses.replace(signed, declared_envelope=BIGGER_WKB),
        dataclasses.replace(signed, declaration_id="fixture-decl-00001"),
        dataclasses.replace(signed, seq=1),
        dataclasses.replace(signed, t_issued=signed.t_issued + 0.01),
        dataclasses.replace(signed, horizon=signed.horizon * 2),
        dataclasses.replace(signed, action_class="hold"),
        dataclasses.replace(signed, prev_hash="b" * HASH_HEX_LEN),
    ]
    for mutated in mutations:
        assert verify(mutated, mutated.mac, POLICY_KEY).state is MacState.INVALID

    # The flipped WKB really is a different polygon, not a no-op edit.
    assert shapely.from_wkb(bytes(payload)) != shapely.from_wkb(
        signed.declared_envelope
    )


def test_a_swapped_mac_fails() -> None:
    """NEGATIVE. One record's signature does not verify on another record."""
    a, b = chain_of(2)
    assert verify(a, b.mac, POLICY_KEY).state is MacState.INVALID


def test_the_wrong_key_is_refused() -> None:
    """NEGATIVE, both flavours: wrong material is invalid, wrong role is an error."""
    signed = sign_declaration(declaration(), POLICY_KEY)
    assert verify(signed, signed.mac, OTHER_POLICY_KEY).state is MacState.INVALID

    with pytest.raises(KeyRoleError, match="signed by the 'policy' key"):
        verify(signed, signed.mac, ENFORCEMENT_KEY)
    with pytest.raises(KeyRoleError, match="signed by the 'policy' key"):
        sign(declaration(), ENFORCEMENT_KEY)
    with pytest.raises(KeyRoleError, match="expected a Key"):
        sign(declaration(), POLICY_MATERIAL)  # type: ignore[arg-type]


def test_a_missing_key_is_could_not_evaluate_not_invalid() -> None:
    """NEGATIVE, and the distinction the third state exists for.

    A verifier without the key has learned nothing about the record. Reporting
    that as tampering would be a false accusation with a signature on it.
    """
    signed = sign_declaration(declaration(), POLICY_KEY)
    check = verify(signed, signed.mac, None)
    assert check.state is MacState.COULD_NOT_EVALUATE
    assert "no key" in check.reason


def test_an_unsigned_record_is_could_not_evaluate() -> None:
    unsigned = declaration()
    assert not unsigned.is_signed
    check = verify(unsigned, unsigned.mac, POLICY_KEY)
    assert check.state is MacState.COULD_NOT_EVALUATE


@pytest.mark.parametrize(
    "mac",
    ["deadbeef", "z" * HASH_HEX_LEN, "A" * HASH_HEX_LEN, 12345, None],
)
def test_a_malformed_mac_is_could_not_evaluate(mac: object) -> None:
    """NEGATIVE. Nothing well-formed to compare against is not 'does not match'."""
    signed = sign_declaration(declaration(), POLICY_KEY)
    assert verify(signed, mac, POLICY_KEY).state is MacState.COULD_NOT_EVALUATE


def test_an_unserializable_record_is_could_not_evaluate() -> None:
    """NEGATIVE. A record that will not canonicalize has an unchecked MAC."""
    record = toy(when=float("nan"), mac="a" * HASH_HEX_LEN)
    check = verify(record, record.mac, ENFORCEMENT_KEY)
    assert check.state is MacState.COULD_NOT_EVALUATE
    assert "could not be serialized" in check.reason


def test_a_mac_check_cannot_be_used_as_a_bool() -> None:
    """The third state is only load-bearing if `if verify(...)` cannot compile.

    Falsy would read as 'tampered' and truthy as 'fine'; both are wrong for
    could-not-evaluate, so the answer is neither.
    """
    signed = sign_declaration(declaration(), POLICY_KEY)
    for key in (POLICY_KEY, OTHER_POLICY_KEY, None):
        check = verify(signed, signed.mac, key)
        with pytest.raises(TypeError, match="three states"):
            bool(check)


def test_a_record_type_without_a_signing_role_cannot_be_signed() -> None:
    @dataclasses.dataclass(frozen=True)
    class Anonymous:
        value: int
        mac: str

    with pytest.raises(KeyRoleError, match="SIGNING_ROLE"):
        sign(Anonymous(value=1, mac=UNSIGNED_MAC), POLICY_KEY)


# --------------------------------------------------------------------------
# The keys, and keeping them apart.
# --------------------------------------------------------------------------


def test_a_keyring_yields_one_key_per_role_and_the_key_knows_its_role() -> None:
    assert sorted(ROLES) == ["enforcement", "policy"]
    for role in ROLES:
        assert KEYRING.key(role).role == role
    with pytest.raises(KeyRoleError, match="no key for role"):
        KEYRING.key("auditor")  # type: ignore[arg-type]


def test_a_key_does_not_print_its_material() -> None:
    """Keys reach tracebacks, pytest output and unattended CI logs."""
    text = repr(POLICY_KEY)
    assert "redacted" in text
    assert POLICY_MATERIAL.hex()[:8] not in text


@pytest.mark.parametrize(
    "material", [b"", b"short", bytes(KEY_BYTES - 1), bytes(KEY_BYTES + 1)]
)
def test_short_or_long_key_material_is_refused(material: bytes) -> None:
    """NEGATIVE. Stretched material is indistinguishable downstream from strong."""
    with pytest.raises(KeyringError, match="bytes"):
        Key(role="policy", material=material)


def test_an_unknown_role_is_refused() -> None:
    with pytest.raises(KeyRoleError, match="unknown key role"):
        Key(role="auditor", material=bytes(KEY_BYTES))  # type: ignore[arg-type]


def test_a_keyring_missing_or_duplicating_a_role_is_refused() -> None:
    """NEGATIVE. Half a keyring silently makes half the record unattributable."""
    only_policy = (Key(role="policy", material=POLICY_MATERIAL),)
    with pytest.raises(KeyringError, match="exactly one key per role"):
        Keyring(keys=only_policy)
    with pytest.raises(KeyringError, match="exactly one key per role"):
        Keyring(keys=only_policy * 2)


def test_a_keyring_round_trips_through_a_file(tmp_path) -> None:
    path = write_keyring(KEYRING, tmp_path / "keys.json")
    loaded = load_keyring(path)
    for role in ROLES:
        assert loaded.key(role).material == KEYRING.key(role).material
    # Byte-identical for the same keyring: fixed role order, fixed formatting.
    again = write_keyring(loaded, tmp_path / "again.json")
    assert path.read_bytes() == again.read_bytes()
    # Secret material, so not world-readable.
    assert (path.stat().st_mode & 0o077) == 0


@pytest.mark.parametrize(
    ("text", "match"),
    [
        ("not json at all", "not valid JSON"),
        ('["policy", "enforcement"]', "must be a JSON object"),
        (json.dumps({"policy": "00" * KEY_BYTES}), "missing role"),
        (
            json.dumps(
                {
                    "policy": "00" * KEY_BYTES,
                    "enforcement": "11" * KEY_BYTES,
                    "auditor": "22" * KEY_BYTES,
                }
            ),
            "does not have",
        ),
        (
            json.dumps({"policy": "00" * 4, "enforcement": "11" * KEY_BYTES}),
            "hex characters",
        ),
        (
            json.dumps({"policy": "zz" * KEY_BYTES, "enforcement": "11" * KEY_BYTES}),
            "not hexadecimal",
        ),
        (
            json.dumps({"policy": 1234, "enforcement": "11" * KEY_BYTES}),
            "not a hex string",
        ),
    ],
)
def test_a_malformed_keyring_file_is_refused(tmp_path, text: str, match: str) -> None:
    """NEGATIVE. There is no partial keyring — every defect is a refusal."""
    path = tmp_path / "keys.json"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(KeyringError, match=match):
        load_keyring(path)


def test_a_missing_keyring_file_is_refused(tmp_path) -> None:
    with pytest.raises(KeyringError, match="could not be read"):
        load_keyring(tmp_path / "nothing-here.json")


def test_generated_keys_are_full_length_and_different_from_each_other() -> None:
    """The one thing in this project that is deliberately not seeded."""
    ring = generate_keyring()
    policy = ring.key("policy").material
    enforcement = ring.key("enforcement").material
    assert len(policy) == len(enforcement) == KEY_BYTES
    assert policy != enforcement
    assert generate_keyring().key("policy").material != policy
