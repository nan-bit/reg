"""The paragraph telling an unattended agent what is running it, held to the host.

Issue #132. `CLAUDE.md`'s *How the runner works* pointed at
`nan-bit/issue-runner` for two harness versions after this repository's writer
became `nan-bit/wake-runner`. Nothing failed, because prose does not fail — and
this is the one paragraph in the file whose reader is an agent with no other way
to find out what launched it, so a stale pointer sends it to a repository whose
tags do not include the version this project runs.

The check is not "the file mentions wake-runner somewhere". It is a set of
predicates over that section alone, each of which is **fed the pre-#132 wording
and required to say no**: a substring match against a document that mentions the
harness in four other places is exactly the check that cannot fail.

What is deliberately *not* checked here: that the section stays silent about
what a `.wake/` record contains. Absence of a schema is not a predicate a
substring test can hold — a reviewer holds that one, and the section says why.

Three-valued, per `CLAUDE.md`'s *a check must be able to fail*: a missing
heading and an empty section are COULD-NOT-EVALUATE, and neither resolves to a
pass. Deleting the section is not how this check gets satisfied.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
CLAUDE_MD = REPO / "CLAUDE.md"

HEADING = "## How the runner works"

AGREE = "AGREE"
DISAGREE = "DISAGREE"
COULD_NOT_EVALUATE = "COULD-NOT-EVALUATE"

CURRENT_HARNESS = "https://github.com/nan-bit/wake-runner"
PREDECESSOR = "issue-runner"

# `[`nan-bit/wake-runner`](https://github.com/nan-bit/wake-runner)`.
LINK = re.compile(r"\[`?[\w.-]+/[\w.-]+`?\]\((https://github\.com/[\w.-]+/[\w.-]+)\)")

# The wording in place before #132, kept verbatim. Every predicate below is fed
# this and required to DISAGREE; if one of them passes on it, it would not have
# caught the defect it exists for.
PRE_132 = """See [`nan-bit/issue-runner`](https://github.com/nan-bit/issue-runner) — the harness
lives in its own repo and is installed on the worker host, not vendored here. This
repo's only harness-facing files are `.runner.conf` and
`.github/workflows/epic-advance.yml`.
"""


def section(text: str) -> str | None:
    """The body of *How the runner works*, or None if the heading is absent."""
    if HEADING not in text:
        return None
    after = text.split(HEADING, 1)[1]
    return re.split(r"^## ", after, maxsplit=1, flags=re.MULTILINE)[0]


def sentences(body: str) -> list[str]:
    """Sentences, with line wrapping collapsed. Colons do not end one."""
    flat = re.sub(r"\s+", " ", body).strip()
    return [s for s in re.split(r"(?<=[.!?]) ", flat) if s]


def _evaluable(body: str | None) -> bool:
    return body is not None and bool(body.strip())


def names_the_current_harness(body: str | None) -> tuple[str, str]:
    """The first repository the section links to must be the one that runs it."""
    if not _evaluable(body):
        return COULD_NOT_EVALUATE, "no section to read"
    links = LINK.findall(body)
    if not links:
        return COULD_NOT_EVALUATE, "the section links to no repository at all"
    if links[0] != CURRENT_HARNESS:
        return DISAGREE, f"the section's first harness link is {links[0]}"
    return AGREE, ""


def predecessor_is_labelled(body: str | None) -> tuple[str, str]:
    """Every mention of the old harness must say it is the archived predecessor.

    Not "the section says `predecessor` somewhere" — *every* sentence naming
    `issue-runner`, so re-introducing it as the live harness alongside a correct
    sentence still fails.
    """
    if not _evaluable(body):
        return COULD_NOT_EVALUATE, "no section to read"
    mentions = [s for s in sentences(body) if PREDECESSOR in s]
    if not mentions:
        return COULD_NOT_EVALUATE, "the section does not mention issue-runner"
    unlabelled = [
        s for s in mentions if "predecessor" not in s or "archiv" not in s
    ]
    if unlabelled:
        return DISAGREE, f"names issue-runner without labelling it: {unlabelled[0]!r}"
    return AGREE, ""


def wake_records_are_declared_off_limits(body: str | None) -> tuple[str, str]:
    """`.wake/` must be named, and named as something an agent may not touch."""
    if not _evaluable(body):
        return COULD_NOT_EVALUATE, "no section to read"
    if ".wake/" not in body:
        return DISAGREE, "the section never names .wake/"
    prohibitions = [
        s
        for s in sentences(body)
        if re.search(r"\bdo not\b|\bmust not\b|\bnever\b", s)
        and "edit" in s
        and "delete" in s
    ]
    if not prohibitions:
        return DISAGREE, "no sentence forbids editing and deleting the records"
    return AGREE, ""


def harness_facing_files_still_listed(body: str | None) -> tuple[str, str]:
    """The two config files stay listed, and `.wake/` is not listed as a third."""
    if not _evaluable(body):
        return COULD_NOT_EVALUATE, "no section to read"
    listing = [s for s in sentences(body) if "harness-facing files" in s]
    if not listing:
        return DISAGREE, "the section no longer lists the harness-facing files"
    for expected in ("`.runner.conf`", "epic-advance.yml"):
        if not any(expected in s for s in listing):
            return DISAGREE, f"{expected} dropped from the harness-facing files"
    if any(".wake" in s for s in listing):
        return DISAGREE, ".wake/ is listed as a harness-facing config file"
    return AGREE, ""


# The three predicates that hold what #132 changed. Each is fed the pre-#132
# wording below and required to say no.
CHANGED = (
    names_the_current_harness,
    predecessor_is_labelled,
    wake_records_are_declared_off_limits,
)

# The one that holds what #132 must *not* change. It passed before and has to
# keep passing: the rewrite is allowed to add, not to drop the file list.
PRESERVED = (harness_facing_files_still_listed,)

PREDICATES = CHANGED + PRESERVED


def check(text: str) -> tuple[str, list[str]]:
    """Verdict on the whole section, and the reasons it is not AGREE."""
    body = section(text)
    if not _evaluable(body):
        return COULD_NOT_EVALUATE, [f"CLAUDE.md has no {HEADING!r} section"]
    verdicts = [p(body) for p in PREDICATES]
    reasons = [why for verdict, why in verdicts if verdict != AGREE]
    if any(verdict == DISAGREE for verdict, _ in verdicts):
        return DISAGREE, reasons
    if any(verdict == COULD_NOT_EVALUATE for verdict, _ in verdicts):
        return COULD_NOT_EVALUATE, reasons
    return AGREE, []


def test_the_runner_section_describes_the_harness_that_is_running() -> None:
    verdict, reasons = check(CLAUDE_MD.read_text())
    assert verdict == AGREE, (
        "CLAUDE.md's 'How the runner works' no longer describes the writer that "
        f"runs this repo: {reasons}. The section is what an unattended agent "
        "reads to learn what launched it; fix the section, not this test."
    )


@pytest.mark.parametrize("predicate", CHANGED, ids=lambda p: p.__name__)
def test_every_predicate_rejects_the_wording_it_replaced(predicate) -> None:
    """The pre-#132 paragraph must fail every predicate that #132 is about."""
    verdict, _ = predicate(PRE_132)
    assert verdict != AGREE, (
        f"{predicate.__name__} accepts the wording that issue #132 exists to "
        "replace, so it would not have caught the defect."
    )


@pytest.mark.parametrize("predicate", PRESERVED, ids=lambda p: p.__name__)
def test_what_the_rewrite_had_to_keep_was_already_true(predicate) -> None:
    """The file list passed before #132 too — that is what makes losing it a
    regression this file can see, rather than a new requirement."""
    verdict, why = predicate(PRE_132)
    assert verdict == AGREE, why


def test_the_section_as_a_whole_rejects_the_wording_it_replaced() -> None:
    verdict, reasons = check(f"# reg\n\n{HEADING}\n\n{PRE_132}\n## Next\n")
    assert verdict == DISAGREE, reasons


def test_naming_wake_runner_is_not_enough_on_its_own() -> None:
    """Swap the link and stop there — the records are still undocumented."""
    swapped = PRE_132.replace(PREDECESSOR, "wake-runner")
    verdict, reasons = check(f"{HEADING}\n\n{swapped}\n")
    assert verdict == DISAGREE, reasons
    assert any(".wake/" in why for why in reasons), reasons


def test_describing_the_records_without_forbidding_edits_fails() -> None:
    body = (
        f"{HEADING}\n\nSee "
        "[`nan-bit/wake-runner`](https://github.com/nan-bit/wake-runner) — the "
        "archived predecessor is "
        "[`nan-bit/issue-runner`](https://github.com/nan-bit/issue-runner). This "
        "repo's only harness-facing files are `.runner.conf` and "
        "`.github/workflows/epic-advance.yml`. The harness writes attempt "
        "records to `.wake/` on the branch.\n"
    )
    verdict, reasons = check(body)
    assert verdict == DISAGREE, reasons
    assert any("edit" in why for why in reasons), reasons


def test_listing_wake_as_a_third_config_file_fails() -> None:
    body = (
        f"{HEADING}\n\nSee "
        "[`nan-bit/wake-runner`](https://github.com/nan-bit/wake-runner) — the "
        "archived predecessor is "
        "[`nan-bit/issue-runner`](https://github.com/nan-bit/issue-runner). This "
        "repo's only harness-facing files are `.runner.conf`, `.wake/` and "
        "`.github/workflows/epic-advance.yml`. Do not edit or delete anything "
        "under `.wake/`.\n"
    )
    verdict, reasons = check(body)
    assert verdict == DISAGREE, reasons
    assert any("third" in why or "config" in why for why in reasons), reasons


@pytest.mark.parametrize(
    "text", ["", "# reg\n\nNo such heading here.\n", f"{HEADING}\n\n\n"]
)
def test_a_missing_or_empty_section_is_could_not_evaluate(text: str) -> None:
    """Silence is not a pass, and deleting the section does not satisfy this."""
    verdict, reasons = check(text)
    assert verdict == COULD_NOT_EVALUATE, reasons
    assert verdict != AGREE
