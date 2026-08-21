"""`reg.identity` — the declared run start, the unit and the operator.

Issue #83. The artifact carried no absolute time and nothing naming the robot,
and the reason given for the first was determinism. These tests are mostly about
that argument: the run start is a **declared input**, so it buys the wall clock
without costing byte-reproducibility, and every route by which an ambient value
could sneak in — a naive timestamp read as UTC, a clock call in this module — is
a refusal with a test on it.

The negatives outnumber the positives on purpose. A parser that accepts
`2026-08-21T09:00:00` and assumes UTC produces a perfectly well-formed artifact
that is wrong by up to fourteen hours, and nothing downstream can see it.
"""

from __future__ import annotations

import ast
import dataclasses
import datetime as dt
import re
from pathlib import Path

import pytest

from reg.identity import (
    DATE_FORMAT,
    IdentityError,
    RunIdentity,
    format_instant,
    parse_instant,
)

MODULE = Path(__file__).resolve().parent.parent / "reg" / "identity.py"

#: The rendering every instant in an artifact uses. Asserted as a shape rather
#: than as one golden string: what matters is that it is UTC, fixed width and
#: unambiguous, not which afternoon a test happened to pick.
INSTANT = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z")


# --------------------------------------------------------------------------
# parse_instant
# --------------------------------------------------------------------------


def test_a_utc_instant_parses_to_itself() -> None:
    moment = parse_instant("2026-08-21T09:00:00Z")
    assert moment == dt.datetime(2026, 8, 21, 9, 0, tzinfo=dt.timezone.utc)
    assert moment.utcoffset() == dt.timedelta(0)


def test_an_offset_instant_is_normalised_rather_than_refused() -> None:
    """One instant, one spelling in the artifact.

    An offset is part of the value, so `+02:00` names a real instant and there
    is nothing to guess. Normalising rather than storing it verbatim is what
    keeps two callers who write the same moment differently producing the same
    bytes — which is the determinism property, not a formatting preference.
    """
    assert parse_instant("2026-08-21T11:00:00+02:00") == parse_instant(
        "2026-08-21T09:00:00Z"
    )


def test_a_naive_instant_is_refused_rather_than_assumed_to_be_utc() -> None:
    """THE NEGATIVE this module exists for.

    Assuming UTC here would produce a complete, plausible, byte-reproducible
    artifact placing the run up to fourteen hours from where it happened, and
    every correlation an assessor drew from it would be wrong in a way nothing
    in the file reports.
    """
    with pytest.raises(IdentityError, match="no UTC offset"):
        parse_instant("2026-08-21T09:00:00")


@pytest.mark.parametrize(
    "text", ["", "   ", "yesterday", "2026-13-45T99:99:99Z", "2026/08/21 09:00Z"]
)
def test_a_run_start_that_is_not_an_instant_is_refused(text: str) -> None:
    with pytest.raises(IdentityError):
        parse_instant(text)


def test_a_run_start_that_is_not_text_is_refused() -> None:
    with pytest.raises(IdentityError, match="as text"):
        parse_instant(1_755_766_800)  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# format_instant
# --------------------------------------------------------------------------


def test_an_instant_is_rendered_at_fixed_width() -> None:
    """Six fractional digits whether or not there are any.

    A format that drops `.000000` makes the column's width a property of the
    value, and two readers comparing two `meta` dumps would have to discount
    that difference before finding a real one.
    """
    assert format_instant(parse_instant("2026-08-21T09:00:00Z")) == (
        "2026-08-21T09:00:00.000000Z"
    )
    assert INSTANT.fullmatch(
        format_instant(parse_instant("2026-08-21T09:00:00.5Z"))
    )


def test_formatting_a_naive_datetime_is_refused() -> None:
    with pytest.raises(IdentityError, match="naive"):
        format_instant(dt.datetime(2026, 8, 21, 9, 0))


def test_formatting_something_that_is_not_a_datetime_is_refused() -> None:
    with pytest.raises(IdentityError, match="takes a datetime"):
        format_instant("2026-08-21T09:00:00Z")  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# RunIdentity
# --------------------------------------------------------------------------


def _identity(**overrides) -> RunIdentity:
    fields = {
        "run_start": "2026-08-21T09:00:00Z",
        "unit_id": "unit-7",
        "operator_id": "op-3",
    }
    fields.update(overrides)
    return RunIdentity.declare(**fields)


def test_a_declared_identity_round_trips_through_its_text_form() -> None:
    identity = _identity()
    assert identity.run_start_text == "2026-08-21T09:00:00.000000Z"
    assert parse_instant(identity.run_start_text) == identity.run_start
    assert identity.unit_id == "unit-7"
    assert identity.operator_id == "op-3"


def test_an_identity_is_frozen() -> None:
    """An audit record that can be mutated after the fact is not evidence."""
    with pytest.raises(dataclasses.FrozenInstanceError):
        _identity().unit_id = "unit-8"  # type: ignore[misc]


@pytest.mark.parametrize("blank", ["", "   ", "\t"])
@pytest.mark.parametrize("field", ["unit_id", "operator_id"])
def test_a_blank_identifier_is_refused(field: str, blank: str) -> None:
    """THE NEGATIVE for "which robot, which shift".

    A blank identifier is the worst available value: it reads as *absent* in
    every `meta` dump while having been supplied, so the artifact looks like one
    nobody was asked to identify rather than one somebody identified as nothing.
    """
    with pytest.raises(IdentityError, match=field):
        _identity(**{field: blank})


@pytest.mark.parametrize("bad", ["unit\n7", "unit\r7", "unit\x007"])
def test_an_identifier_that_would_be_unreadable_in_meta_is_refused(bad: str) -> None:
    with pytest.raises(IdentityError, match="unreadable"):
        _identity(unit_id=bad)


def test_an_identifier_that_is_not_text_is_refused() -> None:
    with pytest.raises(IdentityError, match="not a string"):
        _identity(unit_id=7)


def test_constructing_one_from_a_naive_datetime_is_refused() -> None:
    with pytest.raises(IdentityError, match="naive"):
        RunIdentity(
            run_start=dt.datetime(2026, 8, 21, 9, 0),
            unit_id="unit-7",
            operator_id="op-3",
        )


def test_constructing_one_from_something_that_is_not_a_datetime_is_refused() -> None:
    with pytest.raises(IdentityError, match="not a"):
        RunIdentity(
            run_start="2026-08-21T09:00:00Z",  # type: ignore[arg-type]
            unit_id="unit-7",
            operator_id="op-3",
        )


# --------------------------------------------------------------------------
# The two derived elements: where the run-relative float meets the wall clock
# --------------------------------------------------------------------------


def test_an_instant_in_the_run_lands_on_the_wall_clock() -> None:
    identity = _identity()
    assert identity.timestamp_utc(0.0) == "2026-08-21T09:00:00.000000Z"
    assert identity.timestamp_utc(3.5) == "2026-08-21T09:00:03.500000Z"
    assert identity.timestamp_utc(3600.0) == "2026-08-21T10:00:00.000000Z"


def test_the_date_element_is_dssads_and_follows_the_instant_over_midnight() -> None:
    """`yyyy/mm/dd`, and it is derived rather than fixed for the whole run.

    A shift that crosses midnight is the case that distinguishes "the date this
    run started" from "the date this event happened", and DSSAD's element is the
    second one — it is recorded per occurrence.
    """
    identity = _identity(run_start="2026-08-21T23:59:30Z")
    assert identity.date(0.0) == "2026/08/21"
    assert identity.date(60.0) == "2026/08/22"
    assert dt.datetime.strptime(identity.date(60.0), DATE_FORMAT).day == 22


def test_the_date_and_the_timestamp_agree_on_the_same_instant() -> None:
    """Two renderings of one moment, not two moments."""
    identity = _identity(run_start="2026-08-21T23:59:59Z")
    for t in (0.0, 0.5, 1.0, 2.0, 86_400.0):
        assert identity.timestamp_utc(t).split("T")[0].replace("-", "/") == (
            identity.date(t)
        )


@pytest.mark.parametrize("t", [float("nan"), float("inf"), float("-inf")])
def test_a_non_finite_offset_into_the_run_is_refused(t: float) -> None:
    with pytest.raises(IdentityError, match="not finite"):
        _identity().at(t)


def test_an_offset_that_leaves_the_representable_range_is_refused() -> None:
    """Refused rather than clamped: a timestamp pinned to `datetime.max` is a
    wall-clock time in the record that no event happened at."""
    with pytest.raises(IdentityError, match="outside the range"):
        _identity().at(1e18)


def test_something_that_is_not_a_number_of_seconds_is_refused() -> None:
    with pytest.raises(IdentityError, match="not a number"):
        _identity().at("later")  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# The structural property: nothing here reads a clock
# --------------------------------------------------------------------------


def test_this_module_never_reads_a_clock() -> None:
    """Asserted against the source, like `tests/test_enforce.py`'s import check.

    The whole design is that the run start is *declared*. One `datetime.now()`
    added here for convenience would make two runs of the same command differ,
    and would do it silently — the artifact would still be well-formed, still
    verify, and simply no longer be reproducible. That is not a property a unit
    test of the return value can protect, so it is protected at the source.
    """
    forbidden = {"now", "utcnow", "today", "time", "fromtimestamp", "monotonic"}
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    called = {
        node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, (ast.Attribute, ast.Name))
    }
    leaked = sorted(called & forbidden)
    assert not leaked, (
        f"reg/identity.py calls {leaked}. The run start is declared by the "
        "caller and never read from a clock: an ambient one is "
        "indistinguishable downstream from a declared one, and it would break "
        "the determinism property CI checks while leaving a perfectly "
        "well-formed artifact behind."
    )


def test_the_clock_check_can_fail() -> None:
    """The negative for the check above: feed it a module that does read one."""
    tree = ast.parse("import datetime\n\ndef start():\n    return datetime.now()\n")
    called = {
        node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, (ast.Attribute, ast.Name))
    }
    assert called & {"now", "utcnow", "today", "time", "fromtimestamp", "monotonic"}
