"""Absolute time and identity for a run. **Layer A** — this is part of the record.

WHAT THIS FILE IS FOR
---------------------
Until issue #83 the artifact carried no absolute time and nothing naming the
robot it described. Every timestamp in it was seconds-since-run-start, and every
key in `meta` was an envelope parameter or a retention rule. Three things follow
from that, and all three are why this module exists:

* **DSSAD's ±1.0 s is an accuracy requirement on a wall-clock timestamp**, not a
  quantization of a run-relative float. `reg` had copied the number and dropped
  the datum, which is the tell that an alignment is element-shaped rather than
  requirement-shaped.
* *"Hand it to an assessor"* requires **which robot, which shift**. Neither was
  in the file, and neither is recoverable from it afterwards.
* EU AI Act Art. 73 serious-incident reporting runs on a 15-day clock (10 for a
  death). A record that cannot be placed in time cannot start that clock.

DETERMINISM IS PRESERVED EXACTLY, AND THAT IS THE WHOLE DESIGN
--------------------------------------------------------------
The reason the date was omitted was determinism: a wall-clock date is "exactly
the ambient value that would break it". The project's own design already refutes
that. **Key material is likewise not derivable from a seed**, and the project
handles it by making it a **required caller-supplied input** rather than by
dropping it. A run-start instant is the same kind of input.

So nothing here reads a clock. There is no `datetime.now()` in this module and
there must never be one: the run start is *declared* by the caller, recorded in
the artifact, and the property CI checks becomes **same seed and same declared
start, same bytes**. An ambient default would be indistinguishable downstream
from a declared one, which is the failure mode CLAUDE.md's "never invent a
default" names — so `RunIdentity` has no default for any of its three fields and
`--run-start` has none either.

WHAT AN IDENTIFIER HERE IS AND IS NOT
-------------------------------------
`unit_id` and `operator_id` are opaque strings this module does not interpret.
It refuses blank, whitespace-only and control-character-bearing values, because
those are the ones that read as *absent* in a `meta` dump while having been
supplied — and an artifact that cannot say which robot it describes cannot be
handed to anyone. It does **not** validate them against a registry: there is no
registry here, and a check that only ever passes is not a check.

WHAT ELSE IS DECLARED HERE, AND WHY IT SITS BESIDE THE IDENTIFIERS
------------------------------------------------------------------
`operator_id` with `run_start_utc` selects a shift, and a shift resolves against
a roster to a person — so the identity block is what makes the artifact carry
personal data (`docs/limitations.md` §8). That section named obligations this
project does not discharge, and the file itself said nothing about them: an
assessor holding an artifact could not separate *a worker notice was given and
no key recorded it* from *none was given*. Silence reading as a stated negative
is the inversion this repository refuses everywhere else — `commitment: none` is
written in so many words, `Limits.source` is required with no default,
`verify_chain` returns a could-not-evaluate rather than a pass.

So `Disclosures` carries three facts the deployer **states** and this project
**records**: the Art. 26(7) worker notice, a reference to where a DPIA lives,
and whether `operator_id` is a pseudonym. Each is required with no default, and
each can say *not done* in words — `not-given`, `none`, and either kind of
identifier are answers; absence is not.

**Recording is not discharging, and nothing here adjudicates.** These keys are
the same shape as `Limits.source` and `PoseSource`: the caller states a fact,
the artifact carries it, no code here decides whether the fact is enough. An
artifact carrying them is not thereby lawful to retain and nothing in this
module should be read as saying it is. The vocabulary is deliberately free of
any term that reads as a compliance claim, and
`tests/test_personal_data.py` asserts that against the enums below.

**The fourth fact — the retention basis — is not here**, and its absence is
stated rather than quiet: naming the instrument a six-month window is claimed
under is a legal determination this project has no standing to make. An artifact
that cannot say what basis it was retained under cannot be assessed against
either bound, which `docs/limitations.md` §8 carries as an open gap.

WHAT THIS DOES NOT GIVE YOU
---------------------------
A declared start is a claim by the party writing the artifact, exactly as the
records are. It places the run on a wall clock *if that party is honest*; it
proves nothing on its own about when the file was written. That is what
`reg.commit` is for, and even there the shipped implementation is an on-site
witness rather than a third-party timestamp. See `docs/limitations.md`.
"""

from __future__ import annotations

import dataclasses
import datetime as _dt
from enum import Enum

__all__ = [
    "DATE_FORMAT",
    "DPIA_NONE",
    "Disclosures",
    "IdentityError",
    "OperatorIdKind",
    "RunIdentity",
    "WorkerNotice",
    "WorkerNoticeStatus",
    "format_instant",
    "parse_instant",
]

#: DSSAD's `date` element, `yyyy/mm/dd` (UN R157; docs/prior-art.md §9). The
#: separator is the regulation's, not this project's preference — the element is
#: being *implemented*, not re-spelled.
DATE_FORMAT = "%Y/%m/%d"

#: How an instant is written into the artifact. Always UTC, always six
#: fractional digits, always `Z`. Fixed width on purpose: a format that omits
#: `.000000` when the microseconds happen to be zero makes the column's width a
#: property of the value, and two readers eyeballing a `meta` dump for a
#: difference should not have to discount that one.
_INSTANT_FORMAT = "%Y-%m-%dT%H:%M:%S.%f"

#: The characters an identifier may not contain. Not a charset allowlist — this
#: module does not know what an operator's naming scheme is — but a refusal of
#: the ones that make a value unreadable in the artifact: a newline splits a
#: `meta` value across lines, and a NUL truncates it in half the tools that
#: would open it.
_FORBIDDEN_ID_CHARS = ("\n", "\r", "\t", "\x00")


class IdentityError(ValueError):
    """A run start or an identifier that will not be recorded as given.

    Always a refusal, never a substitution. Every one of these is a value the
    caller has to state, and a plausible one invented here would be
    indistinguishable downstream from the one that actually produced the run.
    """


def parse_instant(text: str) -> _dt.datetime:
    """An RFC 3339 instant, normalised to UTC. **Naive input is refused.**

    Accepts `2026-08-21T09:00:00Z` and `2026-08-21T11:00:00+02:00` and treats
    them as the same instant, because they are one — an offset is part of the
    value, and normalising is what keeps one instant to one spelling in the
    artifact. Refuses `2026-08-21T09:00:00`: a timestamp with no offset is a
    timestamp in whatever zone the reader assumes, and "the operator's local
    time" is exactly the ambient value this project does not put in a record.

    Raises:
        IdentityError: not a string, not RFC 3339, or carrying no offset.
    """
    if not isinstance(text, str):
        raise IdentityError(
            f"a run start is an RFC 3339 UTC instant as text, got a "
            f"{type(text).__name__}."
        )
    raw = text.strip()
    if not raw:
        raise IdentityError(
            "a run start was given as an empty string. There is no default: the "
            "instant is a required input, the same way key material is (README, "
            "'not derivable from a seed'), and an artifact that cannot be placed "
            "in time cannot start an EU AI Act Art. 73 clock."
        )
    try:
        moment = _dt.datetime.fromisoformat(raw)
    except ValueError:
        raise IdentityError(
            f"run start {text!r} is not an RFC 3339 instant. Write it as "
            "'2026-08-21T09:00:00Z', or with an explicit offset such as "
            "'2026-08-21T11:00:00+02:00'."
        ) from None
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise IdentityError(
            f"run start {text!r} carries no UTC offset, so it names an instant "
            "only for a reader who already knows which zone the operator was "
            "in. Refusing rather than assuming UTC: an assumed offset is "
            "indistinguishable downstream from a stated one, and it is wrong by "
            "up to fourteen hours."
        )
    return moment.astimezone(_dt.timezone.utc)


def format_instant(moment: _dt.datetime) -> str:
    """An aware datetime as this project writes it: UTC, microseconds, `Z`.

    Raises:
        IdentityError: the datetime is naive. A naive instant has no single
            rendering, and picking one would put a time in the artifact that is
            wrong by an offset nothing records.
    """
    if not isinstance(moment, _dt.datetime):
        raise IdentityError(
            f"format_instant takes a datetime, got {type(moment).__name__}."
        )
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise IdentityError(
            "a naive datetime cannot be formatted as a UTC instant; it names no "
            "point on any clock without the offset that was dropped."
        )
    return moment.astimezone(_dt.timezone.utc).strftime(_INSTANT_FORMAT) + "Z"


def _identifier(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise IdentityError(
            f"{name} is a {type(value).__name__}, not a string. It is an opaque "
            "identifier this project does not interpret, but it has to be one."
        )
    if not value.strip():
        raise IdentityError(
            f"{name} is {value!r}. An artifact that cannot say which robot it "
            "describes, or who was operating it, cannot be handed to anyone — "
            "and a blank identifier reads as an absent one in every `meta` dump "
            "while having been supplied. There is no default for it."
        )
    for char in _FORBIDDEN_ID_CHARS:
        if char in value:
            raise IdentityError(
                f"{name}={value!r} contains {char!r}, which makes the value "
                "unreadable where it is stored: `meta` is text, and a newline "
                "splits one value across lines while a NUL truncates it."
            )
    return value


@dataclasses.dataclass(frozen=True)
class RunIdentity:
    """When the run started, which unit ran it, and who was operating.

    All three are **required and have no default**. Together they are what makes
    the artifact locatable and correlatable: an assessor holding the file can
    say *which afternoon* and *which robot*, and a reconstruction can line the
    file up against every other log in the cell — which is how an incident is
    actually put back together.

    `run_start` is stored as the parsed, UTC-normalised instant, so two callers
    who spell one instant differently produce byte-identical artifacts.
    """

    run_start: _dt.datetime
    unit_id: str
    operator_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.run_start, _dt.datetime):
            raise IdentityError(
                f"run_start is a {type(self.run_start).__name__}, not a "
                "datetime. Use RunIdentity.declare(...) to take it as text."
            )
        if self.run_start.tzinfo is None or self.run_start.utcoffset() is None:
            raise IdentityError(
                "run_start is naive. An instant with no offset places the run on "
                "nobody's clock; see parse_instant."
            )
        object.__setattr__(
            self, "run_start", self.run_start.astimezone(_dt.timezone.utc)
        )
        object.__setattr__(self, "unit_id", _identifier(self.unit_id, "unit_id"))
        object.__setattr__(
            self, "operator_id", _identifier(self.operator_id, "operator_id")
        )

    @classmethod
    def declare(
        cls, *, run_start: str, unit_id: str, operator_id: str
    ) -> RunIdentity:
        """Build one from the three strings a CLI takes. All keyword, all required."""
        return cls(
            run_start=parse_instant(run_start),
            unit_id=unit_id,
            operator_id=operator_id,
        )

    @property
    def run_start_text(self) -> str:
        """The declared start as it is written into the artifact."""
        return format_instant(self.run_start)

    def at(self, t: float) -> _dt.datetime:
        """The wall-clock instant `t` seconds into the run.

        `t` is the run-relative float every layer of this artifact already uses.
        This is the one place the two time bases meet, so that there is one
        answer to "what wall-clock time is t=3.5" rather than one per reader.

        Raises:
            IdentityError: `t` is not a finite number, or the sum is outside the
                range `datetime` can represent. Both are refusals — a timestamp
                clamped to `datetime.max` would be a wall-clock time in the
                record that no event happened at.
        """
        try:
            seconds = float(t)
        except (TypeError, ValueError):
            raise IdentityError(
                f"t={t!r} is not a number of seconds into the run."
            ) from None
        if seconds != seconds or seconds in (float("inf"), float("-inf")):
            raise IdentityError(
                f"t={t!r} is not finite, so it names no instant in the run and "
                "cannot be placed on a wall clock."
            )
        try:
            return self.run_start + _dt.timedelta(seconds=seconds)
        except (OverflowError, OSError, ValueError):
            raise IdentityError(
                f"t={t!r} seconds after {self.run_start_text} is outside the "
                "range a date can represent. Refusing rather than clamping: a "
                "clamped timestamp is a wall-clock time nothing happened at."
            ) from None

    def timestamp_utc(self, t: float) -> str:
        """`t` as an absolute UTC instant, in this project's fixed rendering."""
        return format_instant(self.at(t))

    def date(self, t: float) -> str:
        """DSSAD's `date` element for `t`: `yyyy/mm/dd`, UTC.

        UTC and not the operator's local date, deliberately: the artifact holds
        one offset — the one the run start was normalised from — and deriving a
        local date would need a zone that is not in the file. The element is a
        date *for the recorded instant*, and the instant is beside it.
        """
        return self.at(t).strftime(DATE_FORMAT)


#: What `dpia_reference` says when there is no DPIA. Written in words, exactly
#: as `reg.graph.COMMITMENT_NONE` is: a build that was given no reference and a
#: deployment that has no assessment must not produce the same artifact, and a
#: key that could be absent would make them identical.
DPIA_NONE = "none"

#: The separator between a worker-notice status and whatever the status
#: requires beside it. One space, so `meta[worker_notice]` splits into exactly
#: two parts and a reader eyeballing the value sees the status first.
_NOTICE_SEPARATOR = " "


class WorkerNoticeStatus(Enum):
    """Whether the AI Act Art. 26(7) notice was given, as the deployer states it.

    Art. 26(7): a deployer who is an employer must inform workers'
    representatives and the affected workers **before** putting a high-risk AI
    system into service at the workplace. `docs/limitations.md` §8 names that
    obligation and states that this project does not discharge it. What the
    artifact could not do was say which of the two cases it was built in, and a
    file that cannot separate *given and unrecorded* from *never given* answers
    the assessor's question with silence.

    Three members and no fourth. There is deliberately no `unknown`: a build
    that was told nothing must **fail** rather than record a value that reads
    like an answer, which is what `Disclosures` having no default is for.

    `NOT_APPLICABLE` carries a stated reason and is required to — it is the
    member closest to an adjudication, and a reason is what keeps it a statement
    by the deployer rather than a determination by this project. Nothing here
    checks the reason: there is no registry of good ones, and a check that only
    ever passes is not a check.
    """

    #: The notice was given, on a stated date.
    GIVEN = "given"
    #: It was not. The explicit negative, and the reason this enum exists.
    NOT_GIVEN = "not-given"
    #: The deployer states the obligation does not reach this deployment, and
    #: says why. Recording that is not agreeing with it.
    NOT_APPLICABLE = "not-applicable"


class OperatorIdKind(Enum):
    """What kind of identifier `meta[operator_id]` is (issue #125).

    A pseudonymous id whose roster mapping is held outside the artifact and a
    payroll or badge number are a materially different disclosure, and an
    assessor holding the file cannot tell which one it is: both are opaque
    strings, and `reg.identity` interprets neither. So the deployer states it.

    **This is a statement about the identifier, not a claim about the data.**
    An artifact whose operator id is a pseudonym still contains personal data —
    the roster that resolves it exists, which is exactly what makes the id an
    identifier at all — and neither member says anything about anonymisation.
    `docs/limitations.md` §8 keeps the minimisation contract; this only records
    which of the two identifiers the contract is holding.
    """

    #: An id the deployer states is a pseudonym, with the mapping to a person
    #: held outside the artifact.
    PSEUDONYM = "pseudonym"
    #: An id that is the identifier itself: nothing held outside the artifact
    #: has to be consulted to read it as far as it reads. A payroll or badge
    #: number is the case that matters.
    DIRECT_IDENTIFIER = "direct-identifier"


def _stated_text(value: object, name: str) -> str:
    """A caller-stated string that will be readable in `meta`, or a refusal.

    The identifier rules, for a value that is not an identifier: blank is a
    refusal because it reads as absent in a `meta` dump while having been
    supplied, and the control characters are refused because `meta` is text.
    """
    if not isinstance(value, str):
        raise IdentityError(
            f"{name} is a {type(value).__name__}, not a string. It is text the "
            "deployer states and this project records without interpreting it."
        )
    if not value.strip():
        raise IdentityError(
            f"{name} is {value!r}. A blank value reads as an absent one in every "
            "`meta` dump while having been supplied, which is the confusion this "
            "key exists to end. There is no default for it: say what is true, "
            "including that nothing was done."
        )
    for char in _FORBIDDEN_ID_CHARS:
        if char in value:
            raise IdentityError(
                f"{name}={value!r} contains {char!r}, which makes the value "
                "unreadable where it is stored: `meta` is text, and a newline "
                "splits one value across lines while a NUL truncates it."
            )
    return value


@dataclasses.dataclass(frozen=True)
class WorkerNotice:
    """The Art. 26(7) notice as the deployer states it: a status and its detail.

    One value in the artifact, `status` then `detail` separated by one space, so
    that `meta[worker_notice]` reads as a sentence and parses in one split:

    * `given 2026/08/01` — given, on that date. The date is
      `DATE_FORMAT`, the one spelling of a date this artifact uses.
    * `not-given` — the explicit negative, and it carries nothing else.
    * `not-applicable <reason>` — the deployer states the obligation does not
      reach this deployment and says why, in their own words.

    What `detail` must be is decided by `status` and each rule is a refusal
    rather than a substitution: a `GIVEN` with no date states nothing an
    assessor can check, a `NOT_APPLICABLE` with no reason is an adjudication
    wearing a record's clothes, and a `NOT_GIVEN` carrying a date is two facts
    disagreeing inside one value.
    """

    status: WorkerNoticeStatus
    detail: str

    def __post_init__(self) -> None:
        if not isinstance(self.status, WorkerNoticeStatus):
            raise IdentityError(
                f"WorkerNotice.status must be a WorkerNoticeStatus, got "
                f"{self.status!r}. The vocabulary is {[m.value for m in WorkerNoticeStatus]} "
                "and there is no fourth value: a build that was told nothing "
                "fails rather than recording something that reads like an answer."
            )
        if not isinstance(self.detail, str):
            raise IdentityError(
                f"WorkerNotice.detail is a {type(self.detail).__name__}, not a "
                "string. It is a date, a reason, or empty, depending on the "
                "status beside it."
            )
        if self.status is WorkerNoticeStatus.GIVEN:
            _parse_date(self.detail)
        elif self.status is WorkerNoticeStatus.NOT_APPLICABLE:
            _stated_text(self.detail, "the reason Art. 26(7) is not applicable")
        elif self.detail:
            raise IdentityError(
                f"a {self.status.value!r} worker notice carries {self.detail!r} "
                "beside it. A notice that was not given has no date and no "
                "reason to state; write the empty string, so that the value in "
                "the artifact is the bare negative and nothing reads as a "
                "justification this project would then be recording as one."
            )

    @property
    def text(self) -> str:
        """The value as it is written into the artifact, and as `parse` reads it."""
        if not self.detail:
            return self.status.value
        return self.status.value + _NOTICE_SEPARATOR + self.detail

    @classmethod
    def parse(cls, text: str) -> WorkerNotice:
        """One string — `given <yyyy/mm/dd>`, `not-given`, `not-applicable <why>`.

        The inverse of `text`, so what a CLI is handed is what the artifact
        carries. Raises `IdentityError` on anything else, naming the vocabulary:
        a status this module does not know is a value nobody can read back, and
        guessing which member was meant would put a fact in the record that the
        deployer did not state.
        """
        if not isinstance(text, str):
            raise IdentityError(
                f"a worker notice is text, got a {type(text).__name__}."
            )
        raw = text.strip()
        if not raw:
            raise IdentityError(
                "the worker notice is empty. There is no default: EU AI Act "
                "Art. 26(7) requires a deployer who is an employer to inform "
                "workers' representatives and the affected workers before the "
                "system enters service, and an artifact that is silent about it "
                "cannot be told from one built where no notice was given. Say "
                f"{[m.value for m in WorkerNoticeStatus]} — the negative is an "
                "answer, silence is not."
            )
        head, _, rest = raw.partition(_NOTICE_SEPARATOR)
        try:
            status = WorkerNoticeStatus(head)
        except ValueError:
            raise IdentityError(
                f"{head!r} is not a worker-notice status. The vocabulary is "
                f"{[m.value for m in WorkerNoticeStatus]}, and it is closed: a "
                "status invented at a call site would be indistinguishable "
                "downstream from one this project defined."
            ) from None
        return cls(status=status, detail=rest.strip())


def _parse_date(value: object) -> str:
    """A `DATE_FORMAT` date as text, or a refusal naming the format."""
    if not isinstance(value, str) or not value.strip():
        raise IdentityError(
            "a worker notice that was given carries the date it was given on, "
            f"written as {_dt.datetime(2026, 8, 1).strftime(DATE_FORMAT)!r} "
            f"({DATE_FORMAT}, the spelling every date in this artifact uses). "
            f"Got {value!r}: a notice with no date states nothing an assessor "
            "can place against the day the system entered service."
        )
    try:
        parsed = _dt.datetime.strptime(value, DATE_FORMAT)
    except ValueError:
        raise IdentityError(
            f"the worker-notice date {value!r} is not {DATE_FORMAT}. One "
            "spelling of a date per artifact: DSSAD's, which is what every "
            "occurrence in this file already carries."
        ) from None
    if parsed.strftime(DATE_FORMAT) != value:
        raise IdentityError(
            f"the worker-notice date {value!r} does not round-trip through "
            f"{DATE_FORMAT}; write it zero-padded, as "
            f"{parsed.strftime(DATE_FORMAT)!r}."
        )
    return value


@dataclasses.dataclass(frozen=True)
class Disclosures:
    """What the deployer states about the obligations `limitations.md` §8 names.

    Three fields, **all required and none with a default**, and each able to say
    *not done* in words. They are recorded and never adjudicated: this project
    has no standing to decide whether a notice was adequate, whether a DPIA was
    needed or whether a pseudonym is enough, and it makes no such decision. What
    it refuses to do is let the file be silent, because silence and a stated
    negative are different facts and an assessor cannot recover which one a
    quiet artifact was built from.

    The fourth fact §8 asks for — **the retention basis**, which instrument the
    six-month window is claimed under — is deliberately absent. Naming it is a
    legal determination, and this type would turn one into a `meta` key that
    read as settled. §8 carries it as an open gap instead; an artifact still
    cannot say what basis it was retained under, and that remains true here.
    """

    worker_notice: WorkerNotice
    dpia_reference: str
    operator_id_kind: OperatorIdKind

    def __post_init__(self) -> None:
        if not isinstance(self.worker_notice, WorkerNotice):
            raise IdentityError(
                f"Disclosures.worker_notice must be a WorkerNotice, got "
                f"{self.worker_notice!r}. Build one with WorkerNotice.parse — "
                "EU AI Act Art. 26(7) is the obligation, and the artifact has to "
                "say which case it was built in."
            )
        if not isinstance(self.operator_id_kind, OperatorIdKind):
            raise IdentityError(
                f"Disclosures.operator_id_kind must be an OperatorIdKind, got "
                f"{self.operator_id_kind!r}. The vocabulary is "
                f"{[m.value for m in OperatorIdKind]}: a pseudonym whose roster "
                "is held elsewhere and a payroll number are a different "
                "disclosure, and both are opaque strings in `meta`."
            )
        object.__setattr__(
            self,
            "dpia_reference",
            _stated_text(self.dpia_reference, "dpia_reference"),
        )

    @classmethod
    def declare(
        cls, *, worker_notice: str, dpia_reference: str, operator_id_kind: str
    ) -> Disclosures:
        """Build one from the three strings a CLI takes. All keyword, all required.

        `dpia_reference` is opaque text — a document id, a URL, a records-of-
        processing entry — and `DPIA_NONE` is the stated negative. Nothing here
        resolves the reference or checks that what it points at exists: there is
        nothing in this repository that could, and a check that only ever passes
        is not a check.
        """
        try:
            kind = OperatorIdKind(operator_id_kind)
        except ValueError:
            raise IdentityError(
                f"operator_id_kind={operator_id_kind!r} is not one of "
                f"{[m.value for m in OperatorIdKind]}. There is no default and "
                "nothing is inferred from the id itself: an opaque string looks "
                "the same either way, and only the deployer knows whether a "
                "roster resolves it."
            ) from None
        return cls(
            worker_notice=WorkerNotice.parse(worker_notice),
            dpia_reference=dpia_reference,
            operator_id_kind=kind,
        )
