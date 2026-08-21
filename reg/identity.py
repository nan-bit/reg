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

__all__ = [
    "DATE_FORMAT",
    "IdentityError",
    "RunIdentity",
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
