"""The chain: canonical bytes, links, MACs, the two keys, and the walk over both.

Most of this file is negative. That is the point of the phase — a chain whose
tests only show that untouched records verify has demonstrated nothing, because
a `verify` that returns VALID unconditionally would pass every one of them. So
each mechanism is tested by breaking it: a mutated field, a swapped link, the
wrong key, no key, a malformed MAC, a field that will not serialize.

THE SECOND HALF OF THIS FILE IS THE SAME ARGUMENT ABOUT `verify_chain`
-----------------------------------------------------------------------
Issue #49. A tamper-evidence mechanism that has never been shown to detect
tampering is exactly the check-that-cannot-fail CLAUDE.md forbids, so the
deliverable is not "an untampered artifact verifies" — that would pass for a
walker that returns VERIFIED unconditionally. It is one test per way of altering
a real artifact: a declaration field, a verdict field, a `mac`, a `prev_hash`, a
deleted record, and a record altered *and re-signed* so its MAC verifies and the
chain must break anyway. Plus the two states that are not findings: an empty
artifact and an absent key are COULD-NOT-EVALUATE, never VERIFIED and never
BROKEN.

Those tests run against a **real artifact**, built by `reg.graph` from a real
scenario with real signed records, because the thing being tested is a walk over
what the builder actually writes — the record tables, the `FOLLOWS` edges and the
`meta` counts. A hand-assembled SQLite file would test a shape nothing produces.
`declared_violation` at a tenth of its frame rate is that artifact: 11
declarations, 51 verdicts, under a second to build.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import textwrap
from dataclasses import replace
from pathlib import Path

import pytest
import shapely
from shapely.geometry import Polygon

from reg import graph, store
from reg.chain import (
    ATTESTATION_PRESENT,
    CHAINS,
    GENESIS_HASH,
    HASH_HEX_LEN,
    KEY_BYTES,
    META_ATTESTATION_RECORDS,
    META_DECLARATION_COUNT,
    META_VERDICT_COUNT,
    ROLES,
    UNSIGNED_MAC,
    CanonicalizationError,
    ChainFailure,
    ChainReport,
    ChainResult,
    ChainState,
    Key,
    KeyRoleError,
    Keyring,
    KeyringError,
    MacState,
    TamperError,
    TamperSpec,
    canonical_bytes,
    chain_hash,
    chain_head,
    generate_keyring,
    is_hash,
    load_keyring,
    sign,
    signing_bytes,
    tamper,
    verify,
    verify_chain,
    write_keyring,
)
from reg.declare import Declaration, envelope_wkb, sign_declaration
from reg.graph import AttestationRecords
from reg.identity import RunIdentity
from reg.scenarios import SCENARIOS
from reg.sim import provenance
from reg.stream import FLOAT_PRECISION, write_frames

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
# `chain_head` — the value a commitment is made over (issue #83).
# --------------------------------------------------------------------------


def test_an_empty_chain_has_the_genesis_hash_as_its_head() -> None:
    """A definition of where a chain starts, not a chosen value."""
    assert chain_head([]) == GENESIS_HASH


def test_the_head_of_an_intact_chain_is_its_last_records_chain_hash() -> None:
    """Which is what makes it the natural thing to commit to: on a chain that
    holds, the head an assessor computes is the link the next record would
    carry."""
    records = chain_of(4)
    assert links_hold(records) == [True] * 4
    assert chain_head(records) == chain_hash(records[-1], records[-1].prev_hash)


def test_altering_the_first_record_moves_the_head() -> None:
    """THE REGRESSION. This is what `chain_head` exists for and the reason it is
    not `chain_hash` folded down the list.

    Every record carries its own predecessor link, so folding each record's
    *carried* link gives a value that depends only on the last record: rewrite
    the first of a hundred declarations and it does not move. A head that does
    not move is a commitment to nothing, and an external witness signing it
    would be signing a value the whole history could be re-issued underneath.
    """
    records = chain_of(4)
    altered = [dataclasses.replace(records[0], horizon=9.5), *records[1:]]

    naive = chain_hash(altered[-1], altered[-1].prev_hash)
    assert naive == chain_hash(records[-1], records[-1].prev_hash), (
        "precondition: the last record's own chain hash is blind to this edit — "
        "which is exactly why the head is not computed that way"
    )
    assert chain_head(altered) != chain_head(records)


def test_editing_a_link_or_a_mac_moves_the_head() -> None:
    """`canonical_bytes` covers every field, so both are inside the head."""
    records = chain_of(3)
    relinked = [
        records[0],
        dataclasses.replace(records[1], prev_hash="a" * HASH_HEX_LEN),
        records[2],
    ]
    resigned = [
        records[0],
        dataclasses.replace(records[1], mac="b" * HASH_HEX_LEN),
        records[2],
    ]
    assert chain_head(relinked) != chain_head(records)
    assert chain_head(resigned) != chain_head(records)


def test_a_head_over_a_record_that_will_not_serialize_is_refused() -> None:
    """No head over "the records that happened to parse"."""
    with pytest.raises(CanonicalizationError):
        chain_head([object()])


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


# --------------------------------------------------------------------------
# THE WALK OVER A PERSISTED ARTIFACT (issue #49)
#
# Everything below runs against an artifact `reg.graph` built, with records
# `reg.declare` and `reg.enforce` signed. The fixture is `declared_violation`
# sampled at a tenth of its frame rate — the same run, looked at less often —
# because what is being tested is the walk and not the scenario.
# --------------------------------------------------------------------------

#: The fixture's policy and enforcement parameters. Stated rather than defaulted,
#: for the reason `emit_declarations` and `Enforcer` refuse to invent them.
FIXTURE_DT = 0.1
FIXTURE_REPLAN_S = 0.5
FIXTURE_HORIZON_S = 0.5
FIXTURE_WATCHDOG_S = 1.0
FIXTURE_SEED = 0

#: The fixture's declared run identity. Required by `graph.build` and stated
#: once here for the same reason the four parameters above are: a value that
#: varied per call would make two artifacts in this file two different runs.
TEST_IDENTITY = RunIdentity.declare(
    run_start="2026-08-21T09:00:00Z",
    unit_id="unit-test-arm-1",
    operator_id="op-test",
)

#: Envelope parameters coarse enough that the build is under a second. Nothing
#: here is about envelope fidelity — `tests/test_envelope.py` owns that — and
#: they are passed explicitly so no test here depends on a default staying put.
_FAST = {"horizon": 0.1, "n_samples": 4, "seed": 0, "substep_dt": 0.05}


def _stream(tmp_path: Path):
    """The stream and its scenario, resampled at `FIXTURE_DT`."""
    scn = replace(SCENARIOS["declared_violation"], dt=FIXTURE_DT)
    csv = write_frames(
        scn.states(FIXTURE_SEED),
        tmp_path / "dv.csv",
        comments=provenance(scn, FIXTURE_SEED),
    )
    return csv, scn


def _records(csv: Path, scn, tmp_path: Path) -> AttestationRecords:
    """The record stream, through the CLI's own producer.

    Through `graph.attestation_from_stream` rather than a second copy of the
    policy/enforcer wiring, for the reason `tests/test_graph.py` gives: a fixture
    that assembled the records differently from the way the CLI does would be
    verifying a chain nobody can produce.
    """
    return graph.attestation_from_stream(
        csv,
        scn,
        keyring_path=write_keyring(KEYRING, tmp_path / "keyring.json"),
        replan_interval_s=FIXTURE_REPLAN_S,
        declaration_horizon_s=FIXTURE_HORIZON_S,
        watchdog_period_s=FIXTURE_WATCHDOG_S,
        # The grid `_build` hands `graph.build` below, not the module default:
        # one run, one discretisation (issue #106).
        substep_dt=_FAST["substep_dt"],
    )


def _build(tmp_path: Path, name: str, records) -> Path:
    csv, scn = _stream(tmp_path)
    out = tmp_path / name
    graph.build(
        csv,
        out,
        scn.world.limits,
        identity=TEST_IDENTITY,
        human_radius=scn.world.human_radius,
        records=records if records is not _PRODUCE else _records(csv, scn, tmp_path),
        **_FAST,
    )
    return out


#: Sentinel for "build the real record stream", distinct from `None`, which is
#: the meaningful value "this build was handed no record stream".
_PRODUCE = object()


@pytest.fixture(scope="module")
def attested(tmp_path_factory) -> Path:
    """One artifact with both chains in it. Module-scoped: every test reads it."""
    return _build(tmp_path_factory.mktemp("attested"), "dv.sqlite", _PRODUCE)


@pytest.fixture(scope="module")
def unattested(tmp_path_factory) -> Path:
    """The same run, built with no record stream at all."""
    return _build(tmp_path_factory.mktemp("unattested"), "none.sqlite", None)


@pytest.fixture(scope="module")
def attested_empty(tmp_path_factory) -> Path:
    """A build handed a record stream that holds nothing.

    A different fact from the one above — `reg.graph` records which — and this
    file asserts the two are told apart by the reason and not only by the state.
    """
    return _build(
        tmp_path_factory.mktemp("empty"),
        "empty.sqlite",
        AttestationRecords(declarations=(), verdicts=()),
    )


def _report(artifact: Path, keyring: Keyring | None = KEYRING) -> ChainReport:
    conn = store.connect(artifact)
    try:
        return verify_chain(conn, keyring)
    finally:
        conn.close()


def _chain(report: ChainReport, role: str) -> ChainResult:
    return next(result for result in report.chains if result.chain == role)


def _kinds(result: ChainResult) -> list[str]:
    return [failure.kind for failure in result.failures]


def _named(result: ChainResult, kind: str) -> list[str | None]:
    """The record ids the failures of one kind name."""
    return [f.record_id for f in result.failures if f.kind == kind]


def _tamper_to(artifact: Path, tmp_path: Path, spec, **kwargs):
    """Tamper into a fresh path under `tmp_path`. Returns `(report, copy)`."""
    out = tmp_path / "tampered.sqlite"
    return tamper(artifact, out, spec, **kwargs), out


# --- the artifact that is intact ------------------------------------------


def test_an_untampered_artifact_verifies(attested: Path) -> None:
    """Both chains, every link, every MAC. The precondition for every negative
    below: if this did not verify, none of them would mean anything."""
    report = _report(attested)
    assert report.state is ChainState.VERIFIED
    assert not report.failures
    for result in report.chains:
        assert result.state is ChainState.VERIFIED
        assert result.records_walked == result.stated_records > 0
        assert result.links_checked == result.records_walked
        assert result.macs_checked == result.records_walked


def test_the_report_walks_both_chains_separately(attested: Path) -> None:
    """Two chains, not one merged stream: the policy signs one and enforcement
    the other, and a walker that merged them would check the policy's links
    under the enforcement key."""
    report = _report(attested)
    assert [result.chain for result in report.chains] == [s.role for s in CHAINS]
    policy = _chain(report, "policy")
    enforcement = _chain(report, "enforcement")
    assert policy.kind == "Declaration"
    assert enforcement.kind == "Verdict"
    # A verdict is per commanded action, so the two chains are different lengths
    # on any real run. Equal counts would mean the fixture is not exercising the
    # separation at all.
    assert enforcement.records_walked > policy.records_walked > 0


def test_a_chain_report_cannot_be_used_as_a_bool(attested: Path) -> None:
    """`if verify_chain(...)` is the bug this refuses to compile into behaviour —
    exactly `MacCheck.__bool__`'s reason, one level up."""
    report = _report(attested)
    with pytest.raises(TypeError, match="three states"):
        bool(report)


# --- THE FOUR TAMPER MODES. Each is a negative and each is the deliverable. -


def test_a_tampered_declaration_field_is_broken_and_named(
    attested: Path, tmp_path: Path
) -> None:
    """NEGATIVE. One field of one declaration, and the walk must say which."""
    tampered, copy = _tamper_to(
        attested, tmp_path, "declaration:first:horizon=9.5", keyring=KEYRING
    )
    assert tampered.field == "horizon"
    assert tampered.before != tampered.after

    result = _chain(_report(copy), "policy")
    assert result.state is ChainState.BROKEN
    # The MAC names the altered record; the link names its successor and the
    # predecessor it should have committed to. Both point at the same edit.
    assert tampered.record_id in _named(result, "mac")
    assert any(
        f.predecessor_id == tampered.record_id for f in result.failures if f.kind == "link"
    )
    assert _chain(_report(copy), "enforcement").state is ChainState.VERIFIED


def test_a_tampered_verdict_field_is_broken_and_named(
    attested: Path, tmp_path: Path
) -> None:
    """NEGATIVE. The other chain, under the other party's key."""
    tampered, copy = _tamper_to(
        attested, tmp_path, "verdict:#3:t=99.5", keyring=KEYRING
    )
    result = _chain(_report(copy), "enforcement")
    assert result.state is ChainState.BROKEN
    assert tampered.record_id in _named(result, "mac")
    assert _chain(_report(copy), "policy").state is ChainState.VERIFIED


def test_a_tampered_mac_is_broken_and_named(attested: Path, tmp_path: Path) -> None:
    """NEGATIVE. The signature alone, on the **last** record — where no link
    covers it, so the MAC check is the only thing that can catch it."""
    tampered, copy = _tamper_to(
        attested, tmp_path, "declaration:last:mac=" + "a" * HASH_HEX_LEN
    )
    result = _chain(_report(copy), "policy")
    assert result.state is ChainState.BROKEN
    assert _named(result, "mac") == [tampered.record_id]
    assert "link" not in _kinds(result), (
        "a MAC swapped on the last record breaks no link; if this reports one, "
        "the walk is not checking what it says it is"
    )


def test_a_tampered_prev_hash_is_broken_and_named(
    attested: Path, tmp_path: Path
) -> None:
    """NEGATIVE. The link itself, mid-chain."""
    tampered, copy = _tamper_to(
        attested, tmp_path, "verdict:#5:prev_hash=" + "b" * HASH_HEX_LEN
    )
    result = _chain(_report(copy), "enforcement")
    assert result.state is ChainState.BROKEN
    assert tampered.record_id in _named(result, "link")


# --- the three that the four above would not catch ------------------------


def test_a_truncated_chain_is_broken_not_verified(
    attested: Path, tmp_path: Path
) -> None:
    """NEGATIVE. Deleting the last record breaks no link — every record that
    remains still commits to its predecessor — so a walk over links alone would
    verify a shorter chain happily. Deleting evidence is the easiest attack
    there is, and the artifact's own count and its `FOLLOWS` edges are what
    notice."""
    tampered, copy = _tamper_to(attested, tmp_path, "verdict:last:delete")
    intact = _chain(_report(attested), "enforcement").records_walked

    result = _chain(_report(copy), "enforcement")
    assert result.state is ChainState.BROKEN
    assert result.records_walked == intact - 1
    assert result.stated_records == intact
    assert "count" in _kinds(result)
    assert tampered.record_id in _named(result, "dangling-link")
    assert "link" not in _kinds(result), (
        "the surviving records still link to each other; if a link failed, this "
        "test is passing for the wrong reason"
    )


def test_a_resigned_record_is_still_broken(attested: Path, tmp_path: Path) -> None:
    """NEGATIVE, and the one that shows the chain does work the MAC cannot.

    Alter a field *and* re-sign it with the correct key: the MAC verifies again,
    every MAC on the chain is checked and none fails — and the chain still breaks
    at the successor, because `prev_hash` commits to the record as it was signed
    the first time.
    """
    tampered, copy = _tamper_to(
        attested,
        tmp_path,
        "declaration:first:horizon=9.5",
        keyring=KEYRING,
        resign=True,
    )
    assert tampered.resigned

    result = _chain(_report(copy), "policy")
    assert result.state is ChainState.BROKEN
    assert result.macs_checked == result.records_walked
    assert "mac" not in _kinds(result), (
        "the point of this test is that the MAC was made to verify again; if it "
        "fails, the re-sign did not happen and the link break proves less"
    )
    links = [f for f in result.failures if f.kind == "link"]
    assert [f.predecessor_id for f in links] == [tampered.record_id]


def test_an_unreadable_record_is_could_not_evaluate_not_broken(
    attested: Path, tmp_path: Path
) -> None:
    """NEGATIVE. A value that reached a column without passing a record — which
    means raw SQL, which means tampering — is a loud could-not-evaluate on the
    way out. Not BROKEN: nothing about the chain was checked."""
    _, copy = _tamper_to(attested, tmp_path, "declaration:first:action_class=nonsense")
    result = _chain(_report(copy), "policy")
    assert result.state is ChainState.COULD_NOT_EVALUATE
    assert _kinds(result) == ["unreadable"]
    assert result.records_walked == 0


# --- the two states that are not findings ---------------------------------


def test_an_empty_artifact_is_could_not_evaluate_not_verified(
    unattested: Path,
) -> None:
    """NEGATIVE. An artifact with nothing in it is not a verified artifact."""
    report = _report(unattested)
    assert report.state is ChainState.COULD_NOT_EVALUATE
    for result in report.chains:
        assert result.state is ChainState.COULD_NOT_EVALUATE
        assert _kinds(result) == ["no-record-stream"]
        assert result.records_walked == result.links_checked == result.macs_checked == 0


def test_no_record_stream_and_no_records_are_told_apart(
    unattested: Path, attested_empty: Path
) -> None:
    """Both refuse — and the reasons differ, because the two are different facts
    and `reg.graph` went to the trouble of recording which."""
    absent = _chain(_report(unattested), "policy")
    empty = _chain(_report(attested_empty), "policy")
    assert absent.state is empty.state is ChainState.COULD_NOT_EVALUATE
    assert _kinds(absent) == ["no-record-stream"]
    assert _kinds(empty) == ["no-records"]
    assert empty.stated_records == 0


def test_a_missing_key_is_could_not_evaluate_not_broken(attested: Path) -> None:
    """NEGATIVE. Not having checked is not the same as having found a fault.

    The links are still walked and still reported — the walk learned something —
    but a chain whose MACs were never checked is not VERIFIED either.
    """
    report = _report(attested, keyring=None)
    assert report.state is ChainState.COULD_NOT_EVALUATE
    for result in report.chains:
        assert result.state is ChainState.COULD_NOT_EVALUATE
        assert _kinds(result) == ["no-key"]
        assert result.macs_checked == 0
        assert result.links_checked == result.records_walked > 0
        assert not [f for f in result.failures if f.state is ChainState.BROKEN]


def test_a_broken_chain_outranks_a_key_that_is_missing(
    attested: Path, tmp_path: Path
) -> None:
    """A definite fault found without a key is still a definite fault. The
    reverse — reporting an unchecked MAC as a break — is the false accusation
    the third state exists to prevent."""
    _, copy = _tamper_to(
        attested, tmp_path, "verdict:#5:prev_hash=" + "b" * HASH_HEX_LEN
    )
    report = _report(copy, keyring=None)
    assert report.state is ChainState.BROKEN
    assert _chain(report, "policy").state is ChainState.COULD_NOT_EVALUATE


def test_a_missing_count_is_could_not_evaluate(attested: Path, tmp_path: Path) -> None:
    """NEGATIVE. Without the stated count the walk cannot tell a complete chain
    from one with its tail removed, and it says so rather than verifying."""
    copy = tmp_path / "no-count.sqlite"
    copy.write_bytes(attested.read_bytes())
    conn = store.connect(copy)
    try:
        conn.execute("DELETE FROM meta WHERE key = ?", (META_VERDICT_COUNT,))
        conn.commit()
    finally:
        conn.close()
    result = _chain(_report(copy), "enforcement")
    assert result.state is ChainState.COULD_NOT_EVALUATE
    assert _kinds(result) == ["no-count"]
    assert result.stated_records is None


# --- the tamper tool itself -----------------------------------------------


def test_tamper_leaves_the_original_untouched(attested: Path, tmp_path: Path) -> None:
    """The artifact under audit is the evidence. Byte for byte, and it still
    verifies afterwards."""
    before = hashlib.sha256(attested.read_bytes()).hexdigest()
    _tamper_to(attested, tmp_path, "declaration:first:horizon=9.5")
    assert hashlib.sha256(attested.read_bytes()).hexdigest() == before
    assert _report(attested).state is ChainState.VERIFIED


def test_tamper_refuses_to_write_over_the_artifact(attested: Path) -> None:
    """NEGATIVE. In place is never available, under any flag."""
    with pytest.raises(TamperError, match="is the artifact itself"):
        tamper(attested, attested, "declaration:first:horizon=9.5")


def test_tamper_refuses_a_destination_that_exists(
    attested: Path, tmp_path: Path
) -> None:
    """NEGATIVE. The one file it writes is a new one, so nothing it is pointed
    at can be lost by pointing it at the wrong path."""
    taken = tmp_path / "taken.sqlite"
    taken.write_bytes(b"someone else's evidence")
    with pytest.raises(TamperError, match="already exists"):
        tamper(attested, taken, "declaration:first:horizon=9.5")
    assert taken.read_bytes() == b"someone else's evidence"


def test_tamper_refuses_to_resign_without_a_key(
    attested: Path, tmp_path: Path
) -> None:
    """NEGATIVE. No key is invented — a MAC under made-up material would fail
    for the wrong reason and prove nothing."""
    with pytest.raises(TamperError, match="no key to invent"):
        tamper(
            attested,
            tmp_path / "out.sqlite",
            "declaration:first:horizon=9.5",
            resign=True,
        )
    assert not (tmp_path / "out.sqlite").exists()


def test_tamper_refuses_a_record_that_is_not_there(
    attested: Path, tmp_path: Path
) -> None:
    """NEGATIVE, and it names what is there rather than only saying no."""
    with pytest.raises(TamperError, match="holds no Declaration"):
        tamper(attested, tmp_path / "out.sqlite", "declaration:no-such-id:horizon=1.0")
    with pytest.raises(TamperError, match="out of range"):
        tamper(attested, tmp_path / "out.sqlite", "declaration:#9999:horizon=1.0")


def test_tamper_refuses_a_column_it_cannot_type(
    attested: Path, tmp_path: Path
) -> None:
    """NEGATIVE. A WKB geometry cannot be given as a string, and coercing one
    would write bytes nobody typed."""
    with pytest.raises(TamperError, match="BLOB column"):
        tamper(
            attested,
            tmp_path / "out.sqlite",
            "declaration:first:declared_envelope_wkb=circle",
        )
    with pytest.raises(TamperError, match="has no column"):
        tamper(attested, tmp_path / "out.sqlite", "declaration:first:nonesuch=1")
    with pytest.raises(TamperError, match="not a value for"):
        tamper(attested, tmp_path / "out.sqlite", "declaration:first:horizon=soon")
    assert not (tmp_path / "out.sqlite").exists(), (
        "a refused tamper leaves no half-altered copy behind"
    )


def test_tamper_refuses_an_empty_chain(attested_empty: Path, tmp_path: Path) -> None:
    """NEGATIVE. A demonstration on an empty chain demonstrates nothing."""
    with pytest.raises(TamperError, match="holds no Declaration"):
        tamper(attested_empty, tmp_path / "out.sqlite", "declaration:first:horizon=1.0")


@pytest.mark.parametrize(
    "spec, match",
    [
        ("declaration:first", "not CHAIN:SELECTOR:OP"),
        ("nonsense:first:horizon=1", "names chain"),
        ("declaration:first:horizon", "neither FIELD=VALUE"),
        ("declaration:first:=1", "names no field"),
        ("declaration::horizon=1", "which record"),
    ],
)
def test_a_tamper_spec_that_is_not_one_is_refused(spec: str, match: str) -> None:
    """NEGATIVE. Every defect in a spec is a refusal, never a guess."""
    with pytest.raises(TamperError, match=match):
        TamperSpec.parse(spec)


def test_a_delete_spec_cannot_be_resigned() -> None:
    """NEGATIVE. Re-signing a deleted record is not a thing."""
    with pytest.raises(TamperError, match="deleted record"):
        TamperSpec.parse("verdict:last:delete", resign=True)


def test_a_tamper_spec_takes_either_name_for_a_chain() -> None:
    """`declaration` is the table, `policy` is the party that signs it."""
    assert TamperSpec.parse("declaration:first:horizon=1").chain == "policy"
    assert TamperSpec.parse("policy:first:horizon=1").chain == "policy"
    assert TamperSpec.parse("verdict:last:delete").chain == "enforcement"
    assert TamperSpec.parse("enforcement:last:delete").chain == "enforcement"


# --- the report's own vocabulary ------------------------------------------


# --------------------------------------------------------------------------
# THE TRUNCATION TABLE (issue #97)
#
# An external review reported that `verify_chain` returned VERIFIED on several
# tampers. Two mattered, and only one of them reproduced — which is recorded here
# rather than quietly dropped, because a test suite that only keeps the findings
# that held is a suite that cannot tell you when a reviewer was wrong.
# --------------------------------------------------------------------------


def _copy(src: Path, dst: Path) -> Path:
    shutil.copyfile(src, dst)
    return dst


def test_deleting_every_link_edge_is_not_a_verified_artifact(
    attested: Path, tmp_path: Path
) -> None:
    """**THE ONE THAT REPRODUCED.**

    `_dangling_links` reports `FOLLOWS` edges that exist and point at nothing, so
    deleting them all leaves nothing to dangle and the artifact verified clean.
    An empty witness list reading as a pass is the inversion CLAUDE.md forbids.
    The census asserts the count instead of inspecting the survivors.
    """
    out = _copy(attested, tmp_path / "no-links.sqlite")
    conn = sqlite3.connect(out)
    conn.execute("DELETE FROM edge WHERE type = 'FOLLOWS'")
    conn.commit()
    conn.close()

    report = verify_chain(store.connect(out), KEYRING)
    assert report.state is ChainState.BROKEN, (
        "every link edge was removed and the artifact still verified. Counting "
        "them is what notices it; inspecting the ones that remain cannot."
    )
    kinds = {f.kind for chain in report.chains for f in chain.failures}
    assert "link-census" in kinds, f"expected a link-census failure, got {kinds}"


def test_a_view_that_dropped_the_edge_layer_is_not_a_tampered_chain(
    attested: Path, tmp_path: Path
) -> None:
    """**THE NEGATIVE FOR THE CENSUS**, and it caught a bug in the census itself.

    `reg.bench.materialize_level` builds the occurrence view with a bare
    `DELETE FROM edge`: that level retains events and not relationships, and says
    so in its own retention rule. The first version of the census called that a
    broken chain, and the second — guarding on "are there any FOLLOWS edges" —
    was worse, because deleting every FOLLOWS edge is exactly the attack.

    Dropping the edge layer takes *every* edge. Removing the links alone leaves
    the others behind. That is the difference, and it is in the artifact.
    """
    out = _copy(attested, tmp_path / "coarsened.sqlite")
    conn = sqlite3.connect(out)
    conn.execute("DELETE FROM edge")
    conn.commit()
    conn.close()

    report = verify_chain(store.connect(out), KEYRING)
    kinds = {f.kind for chain in report.chains for f in chain.failures}
    assert "link-census" not in kinds, (
        "a view with no edge layer was reported as a chain with its links "
        "removed. Those are different facts about the artifact."
    )
    assert report.state is not ChainState.VERIFIED, (
        "a census that could not run must not read as a pass"
    )


def test_deleting_a_declaration_a_verdict_names_is_caught(
    attested: Path, tmp_path: Path
) -> None:
    """**THE ONE THAT DID NOT REPRODUCE**, kept because the reason matters.

    The review reported this as VERIFIED. It is not, and was not before issue #97
    touched anything: since issue #55 a `Verdict` stores `declaration_id` as a key
    into `node`, so deleting the declaration's node row changes the verdict's
    *reconstructed* reference and breaks its MAC.

    The relational storage supplies the integrity the review said was absent —
    which is worth a test, because the day the record tables stop being
    relational that protection disappears silently. `_cross_referenced_records`
    now checks the reference directly, so the finding is legible rather than
    arriving as a confusing MAC mismatch.
    """
    out = _copy(attested, tmp_path / "orphaned.sqlite")
    conn = sqlite3.connect(out)
    key, = conn.execute(
        "SELECT declaration_key FROM declaration ORDER BY seq DESC LIMIT 1"
    ).fetchone()
    held, = conn.execute("SELECT count(*) FROM declaration").fetchone()
    conn.execute("DELETE FROM declaration WHERE declaration_key = ?", (key,))
    conn.execute("DELETE FROM node WHERE node_key = ?", (key,))
    # Fix the count and drop the edges: both are unauthenticated, both editable.
    conn.execute(
        "UPDATE meta SET value = ? WHERE key = 'declaration_count'", (str(held - 1),)
    )
    conn.execute(
        "DELETE FROM edge WHERE type = 'FOLLOWS' AND (src_key = ? OR dst_key = ?)",
        (key, key),
    )
    conn.commit()
    conn.close()

    report = verify_chain(store.connect(out), KEYRING)
    assert report.state is ChainState.BROKEN, (
        "a declaration was removed while a verdict still names it, and every "
        "unauthenticated witness was repaired to match. The reference is inside "
        "the enforcement MAC; it is the one thing here that cannot be edited."
    )


def test_an_untampered_artifact_still_verifies(attested: Path) -> None:
    """The control. Three checks were added; none may fire on a clean artifact."""
    assert verify_chain(store.connect(attested), KEYRING).state is ChainState.VERIFIED


def test_a_failure_cannot_be_recorded_as_verified() -> None:
    """NEGATIVE. A failure that is not a finding would be counted as one and
    reported as none."""
    with pytest.raises(ValueError, match="BROKEN or COULD-NOT-EVALUATE"):
        ChainFailure(
            chain="policy", kind="mac", state=ChainState.VERIFIED, reason="fine"
        )
    with pytest.raises(ValueError, match="not in"):
        ChainFailure(
            chain="policy", kind="vibes", state=ChainState.BROKEN, reason="bad"
        )


def test_the_report_state_is_the_worst_of_its_chains() -> None:
    """A definite fault anywhere is a fault; VERIFIED needs every chain."""

    def result(state: ChainState) -> ChainResult:
        return ChainResult(
            chain="policy",
            kind="Declaration",
            state=state,
            records_walked=1,
            links_checked=1,
            macs_checked=1,
            stated_records=1,
            failures=(),
        )

    worst = {
        (ChainState.VERIFIED, ChainState.VERIFIED): ChainState.VERIFIED,
        (ChainState.VERIFIED, ChainState.BROKEN): ChainState.BROKEN,
        (ChainState.VERIFIED, ChainState.COULD_NOT_EVALUATE): (
            ChainState.COULD_NOT_EVALUATE
        ),
        (ChainState.COULD_NOT_EVALUATE, ChainState.BROKEN): ChainState.BROKEN,
    }
    for (left, right), expected in worst.items():
        assert ChainReport(chains=(result(left), result(right))).state is expected
    assert ChainReport(chains=()).state is ChainState.COULD_NOT_EVALUATE


def test_the_meta_keys_this_module_reads_are_the_ones_the_builder_writes(
    attested: Path,
) -> None:
    """The drift guard. `reg.chain` names these keys instead of importing them
    from `reg.graph` — which imports this module, and reaches the raw stream
    besides — so the two spellings are compared here rather than diverging into
    a chain that silently stops being checkable."""
    assert META_ATTESTATION_RECORDS == graph.META_ATTESTATION_RECORDS
    assert META_DECLARATION_COUNT == graph.META_DECLARATION_COUNT
    assert META_VERDICT_COUNT == graph.META_VERDICT_COUNT
    conn = store.connect(attested)
    try:
        meta = store.all_meta(conn)
    finally:
        conn.close()
    for key in (META_ATTESTATION_RECORDS, META_DECLARATION_COUNT, META_VERDICT_COUNT):
        assert key in meta, f"the builder writes no {key!r}"
    assert meta[META_ATTESTATION_RECORDS] == ATTESTATION_PRESENT
