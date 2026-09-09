"""`reg.identity` — the declared run start, the unit, the operator, and what
the deployer states about the obligations that block creates.

Issue #83. The artifact carried no absolute time and nothing naming the robot,
and the reason given for the first was determinism. These tests are mostly about
that argument: the run start is a **declared input**, so it buys the wall clock
without costing byte-reproducibility, and every route by which an ambient value
could sneak in — a naive timestamp read as UTC, a clock call in this module — is
a refusal with a test on it.

The negatives outnumber the positives on purpose. A parser that accepts
`2026-08-21T09:00:00` and assumes UTC produces a perfectly well-formed artifact
that is wrong by up to fourteen hours, and nothing downstream can see it.

Issue #125 added `Disclosures` beside them and the tests below have the same
shape, because the argument is the same one: `docs/limitations.md` §8 names
obligations this project does not discharge, and an artifact silent about them
reads exactly like one built where none of them was done. So every value is
required, every negative is a word rather than an absence, and each rule about
what a status carries beside it is a refusal with a test on it. None of these
tests asserts that anything stated is *enough* — nothing in the module decides
that, and a test that implied otherwise would be claiming what §8 refuses to.
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
    DPIA_NONE,
    Disclosures,
    IdentityError,
    OperatorIdKind,
    RunIdentity,
    WorkerNotice,
    WorkerNoticeStatus,
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


# --------------------------------------------------------------------------
# Disclosures (issue #125)
# --------------------------------------------------------------------------


def _disclosures(**overrides) -> Disclosures:
    fields = {
        "worker_notice": "not-given",
        "dpia_reference": DPIA_NONE,
        "operator_id_kind": "pseudonym",
    }
    fields.update(overrides)
    return Disclosures.declare(**fields)


@pytest.mark.parametrize(
    "stated",
    [
        "given 2026/08/01",
        "not-given",
        "not-applicable this cell runs unstaffed",
    ],
)
def test_every_worker_notice_answer_round_trips_through_its_text_form(
    stated: str,
) -> None:
    """What goes into the artifact is what the deployer wrote.

    `parse` and `text` are one contract: the value in `meta` is the value a CLI
    was handed, so nothing between the two can quietly re-word an answer about
    an obligation. All three answers, because the two negatives are the ones
    this key exists for.
    """
    assert WorkerNotice.parse(stated).text == stated
    assert _disclosures(worker_notice=stated).worker_notice.text == stated


def test_the_negatives_are_values_rather_than_absences() -> None:
    """`not-given` and `none` are answers; nothing here may be omitted.

    The whole argument for these three fields: a file that says *not-given* and
    a file that says nothing are different facts, and only the first can be
    assessed. So the negatives are ordinary values that construct, and the
    absences below refuse.
    """
    stated = _disclosures()
    assert stated.worker_notice.status is WorkerNoticeStatus.NOT_GIVEN
    assert stated.dpia_reference == DPIA_NONE
    assert stated.operator_id_kind is OperatorIdKind.PSEUDONYM


def test_disclosures_are_frozen() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        _disclosures().dpia_reference = "DPIA-1"  # type: ignore[misc]


@pytest.mark.parametrize("blank", ["", "   ", "\t"])
def test_a_blank_worker_notice_is_refused(blank: str) -> None:
    """THE NEGATIVE for "required, no default".

    A blank value is the worst one available for the same reason a blank
    `unit_id` is: it reads as absent in a `meta` dump while having been
    supplied, so the artifact looks like one nobody was asked rather than one
    that answered.
    """
    with pytest.raises(IdentityError, match="26\\(7\\)|empty"):
        _disclosures(worker_notice=blank)


@pytest.mark.parametrize("blank", ["", "   ", "\t"])
def test_a_blank_dpia_reference_is_refused(blank: str) -> None:
    with pytest.raises(IdentityError, match="dpia_reference"):
        _disclosures(dpia_reference=blank)


@pytest.mark.parametrize(
    "status", ["informed", "GIVEN", "yes", "not applicable", "none"]
)
def test_a_worker_notice_status_outside_the_vocabulary_is_refused(
    status: str,
) -> None:
    """The vocabulary is closed, and near-misses are the cases that matter.

    `yes` and `not applicable` are what somebody writes when they mean an
    answer this project defines; storing either verbatim would put a status in
    the record that every reader has to guess at, and guessing is what a closed
    vocabulary exists to stop.
    """
    with pytest.raises(IdentityError, match="worker-notice status"):
        _disclosures(worker_notice=status)


@pytest.mark.parametrize("kind", ["", "anonymous", "pseudonymous", "direct"])
def test_an_operator_id_kind_outside_the_vocabulary_is_refused(kind: str) -> None:
    """And nothing is inferred from the id itself — it is opaque either way."""
    with pytest.raises(IdentityError, match="operator_id_kind"):
        _disclosures(operator_id_kind=kind)


@pytest.mark.parametrize(
    "notice",
    ["given", "given soon", "given 2026-08-01", "given 01/08/2026", "given 2026/8/1"],
)
def test_a_notice_given_without_a_readable_date_is_refused(notice: str) -> None:
    """A `given` with no date states nothing an assessor can place.

    The date is `DATE_FORMAT`, DSSAD's spelling and the one every occurrence in
    an artifact already carries. `2026-08-01` and `01/08/2026` are the two
    near-misses: both are dates, neither is this artifact's, and a second
    spelling in one file is a reader's problem forever.
    """
    with pytest.raises(IdentityError, match="date"):
        _disclosures(worker_notice=notice)


def test_a_notice_that_was_never_given_carries_nothing_beside_it() -> None:
    """Two facts inside one value, disagreeing, is worse than either alone.

    A `not-given` with a date is either a wrong status or a wrong date, and
    nothing downstream can say which — so it is refused rather than stored with
    the surplus dropped, which would silently discard whichever half was right.
    """
    with pytest.raises(IdentityError, match="not-given"):
        WorkerNotice(status=WorkerNoticeStatus.NOT_GIVEN, detail="2026/08/01")


def test_a_not_applicable_notice_without_a_reason_is_refused() -> None:
    """The member closest to an adjudication, held to stating why.

    `not-applicable` on its own is a determination wearing a record's clothes.
    With a reason it is what the rest of this module is: the deployer's
    statement, carried unexamined — nothing here checks the reason, because
    there is no registry of good ones and a check that only ever passes is not
    a check.
    """
    with pytest.raises(IdentityError, match="not applicable|reason"):
        _disclosures(worker_notice="not-applicable")
    stated = _disclosures(worker_notice="not-applicable this cell runs unstaffed")
    assert stated.worker_notice.detail == "this cell runs unstaffed"


@pytest.mark.parametrize("bad", ["none\nnone", "none\x00", "none\rnone"])
def test_a_dpia_reference_that_would_be_unreadable_in_meta_is_refused(
    bad: str,
) -> None:
    with pytest.raises(IdentityError, match="unreadable"):
        _disclosures(dpia_reference=bad)


@pytest.mark.parametrize(
    "field, value",
    [
        ("worker_notice", 7),
        ("dpia_reference", 7),
        ("operator_id_kind", 7),
    ],
)
def test_a_disclosure_that_is_not_text_is_refused(field: str, value: object) -> None:
    with pytest.raises(IdentityError):
        _disclosures(**{field: value})


def test_constructing_disclosures_from_the_wrong_types_is_refused() -> None:
    """The dataclass is reachable directly, so it checks rather than assumes."""
    with pytest.raises(IdentityError, match="WorkerNotice"):
        Disclosures(
            worker_notice="not-given",  # type: ignore[arg-type]
            dpia_reference=DPIA_NONE,
            operator_id_kind=OperatorIdKind.PSEUDONYM,
        )
    with pytest.raises(IdentityError, match="OperatorIdKind"):
        Disclosures(
            worker_notice=WorkerNotice(
                status=WorkerNoticeStatus.NOT_GIVEN, detail=""
            ),
            dpia_reference=DPIA_NONE,
            operator_id_kind="pseudonym",  # type: ignore[arg-type]
        )
    with pytest.raises(IdentityError, match="WorkerNoticeStatus"):
        WorkerNotice(status="given", detail="2026/08/01")  # type: ignore[arg-type]


def test_no_disclosure_value_is_a_number_or_a_bare_boolean() -> None:
    """Every value a reader meets in `meta` is a word they can read.

    `commitment: none` is the precedent — words rather than `1`/`0`, because a
    bare `0` in a column of counts reads as a count of something. The same
    argument applies here with more force: a `meta` value that read `0` against
    a key about a worker notice would be unreadable in exactly the place it
    matters most.
    """
    for member in (*WorkerNoticeStatus, *OperatorIdKind):
        assert isinstance(member.value, str) and member.value.strip()
        assert not member.value.isdigit()
    assert DPIA_NONE == "none"
