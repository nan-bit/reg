"""What `CLAUDE.md` tells an unattended agent about the thing running it.

THE DEFECT THIS EXISTS FOR (issue #132)
---------------------------------------
`CLAUDE.md`'s "How the runner works" pointed at `nan-bit/issue-runner` as the
harness that writes changes in this repository. That stopped being true: the
writer is `nan-bit/wake-runner`, and `issue-runner` is its archived predecessor,
still named in older commit messages here. A wrong pointer in ordinary prose
costs a reader a click. This paragraph is the one an agent reads to learn what is
running it and which files are not its to touch, so the wrong pointer sends it to
the wrong repository's documentation about its own execution.

The harness also now writes a record of every attempt into `.wake/` on the
branch. An agent that finds those files and does not know what they are will
either tidy them away or edit them, and either one destroys the record of the
attempt it is part of. So the section has to name them — as *output*, not as a
third config file beside `.runner.conf` and the workflow.

WHAT IS CHECKED, AND WHY EACH ONE CAN FAIL
------------------------------------------
1. **The current harness is named and linked**, and `issue-runner` is not the
   repository the section presents as the writer.
2. **`issue-runner` is marked as the predecessor** where it is mentioned, so a
   reader meeting the name in an old commit message is not left guessing.
3. **`.wake/` is named as harness-written attempt records, and put off limits** —
   both halves, because "the harness writes `.wake/`" without "do not edit it"
   reads as a description rather than an instruction.
4. **The two harness-facing files stay listed, and `.wake/` is not enumerated as
   a third one.** The distinction is the point: one set is configuration you may
   not edit, the other is a record you may not edit; conflating them is how
   `.wake/` ends up in a denylist that is about config.
5. **No claim here about what a record contains.** That belongs to wake-runner's
   docs. A schema duplicated in two repositories drifts, and the copy nobody runs
   is the one that goes stale.

Three-valued, per `CLAUDE.md`'s own *a check must be able to fail*: a file with
no such section is COULD-NOT-EVALUATE for every predicate, and
`test_the_section_exists_to_be_checked` is why deleting the section is not a way
to pass. **Every predicate is also fed the pre-#132 paragraph** — the exact
wording at 894bb1e — and required to say no, because a substring probe against a
document that mentions both repositories somewhere is the easiest check in this
family to accidentally assert away.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
CONVENTIONS = REPO / "CLAUDE.md"
FRONT_PAGE = REPO / "README.md"

AGREE = "AGREE"
DISAGREE = "DISAGREE"
COULD_NOT_EVALUATE = "COULD-NOT-EVALUATE"

#: The heading whose body is the subject of every predicate below. Read by
#: heading rather than by line number so that reordering the file is not a
#: failure and deleting the section is.
HEADING = "How the runner works"

#: The README's equivalent section. Issue #132 corrected `CLAUDE.md` and left
#: this one saying "the harness itself is `nan-bit/issue-runner`" — the same
#: defect, on the page more people read, surviving because the check below was
#: scoped to one file. The predicates are properties of the paragraph, so
#: pointing them at a second one costs nothing and closes the gap.
README_HEADING = "How work happens"

#: The harness that writes unattended changes in this repository today.
HARNESS = "nan-bit/wake-runner"

#: Its predecessor. Named in commit messages already in this repository's
#: history, which is why the section has to place it rather than drop it.
PREDECESSOR = "nan-bit/issue-runner"

#: The files this repository holds *for* the harness. Both are configuration and
#: both are off limits; `.wake/` is neither of those things and must not be
#: listed as if it were.
HARNESS_FACING = ("`.runner.conf`", "`.github/workflows/epic-advance.yml`")

#: The directory of attempt records.
RECORDS = ".wake/"

#: The paragraph as it stood before issue #132, kept verbatim as the negative
#: every predicate is fed. It names both repositories' URLs, so a check that
#: merely greps for the right string passes on it.
PRE_132 = """## How the runner works

See [`nan-bit/issue-runner`](https://github.com/nan-bit/issue-runner) — the harness
lives in its own repo and is installed on the worker host, not vendored here. This
repo's only harness-facing files are `.runner.conf` and
`.github/workflows/epic-advance.yml`.
"""


# --- locating the section ---------------------------------------------------


def section(text: str, heading: str = HEADING) -> str | None:
    """The body of `heading`'s section, or `None` if absent.

    `None` is the COULD-NOT-EVALUATE input for every predicate below: a file
    that no longer has this section has not satisfied any of these criteria, and
    must not read as though it had.

    `heading` is a parameter because the same defect had two sites. The
    predicates below are properties of a *paragraph that points at the harness*,
    not of `CLAUDE.md`, and the README carried the pre-#132 wording for five days
    after `CLAUDE.md` was corrected — see `README_HEADING`.
    """
    match = re.search(
        rf"^#+\s*{re.escape(heading)}\s*$(.*?)(?=^#+\s|\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    return match.group(1) if match else None


def normalise(text: str) -> str:
    """Collapse whitespace so a predicate is not defeated by a line wrap."""
    return re.sub(r"\s+", " ", text)


@pytest.fixture(scope="module")
def conventions() -> str:
    return CONVENTIONS.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def front_page() -> str:
    return FRONT_PAGE.read_text(encoding="utf-8")


# --- check 1: the harness that is actually running --------------------------

#: `nan-bit/wake-runner` given as a markdown link to its own URL. The link is
#: required, not just the name: the section exists to send a reader somewhere.
HARNESS_LINK = re.compile(
    rf"\[`?{re.escape(HARNESS)}`?\]\(https://github\.com/{re.escape(HARNESS)}/?\)"
)

#: The predecessor presented as the harness — the exact shape of the defect.
#: "issue-runner — the harness lives in its own repo", in any wrapping.
PREDECESSOR_AS_HARNESS = re.compile(
    rf"{re.escape(PREDECESSOR)}[^.]{{0,80}}?\bthe harness\b", re.IGNORECASE
)


def names_the_running_harness(body: str | None) -> str:
    """Verdict on whether the section points at the harness that runs this repo."""
    if body is None:
        return COULD_NOT_EVALUATE
    flat = normalise(body)
    if PREDECESSOR_AS_HARNESS.search(flat):
        return DISAGREE
    return AGREE if HARNESS_LINK.search(flat) else DISAGREE


def test_the_section_names_and_links_the_harness_that_runs_this_repo(
    conventions: str,
) -> None:
    """**THE CHECK ISSUE #132 EXISTS FOR.** An agent that follows this pointer
    lands in the documentation for the thing that is actually executing it."""
    assert names_the_running_harness(section(conventions)) == AGREE, (
        f"CLAUDE.md's '{HEADING}' does not link {HARNESS} as the harness. It is "
        "the paragraph an unattended agent reads to find out what is running it."
    )


def test_the_pre_132_paragraph_is_caught(conventions: str) -> None:
    """**The negative**, and it is the file's own wording at 894bb1e. It links a
    real repository, so nothing but reading *which* one distinguishes it."""
    assert names_the_running_harness(section(PRE_132)) == DISAGREE


def test_the_front_page_names_and_links_the_running_harness(front_page: str) -> None:
    """The same check, on the page a reader arrives at first.

    `CLAUDE.md` was corrected by issue #132 and the README was not, because this
    file read one of them. The README is where someone who has never opened
    `CLAUDE.md` learns what writes the code here, so it is the worse of the two
    places to leave pointing at an archived repository.
    """
    assert names_the_running_harness(section(front_page, README_HEADING)) == AGREE, (
        f"README.md's '{README_HEADING}' does not link {HARNESS} as the harness. "
        f"It said {PREDECESSOR} was 'the harness itself' for as long as this "
        "check was scoped to CLAUDE.md."
    )


def test_the_front_page_says_what_issue_runner_is(front_page: str) -> None:
    """And the predecessor is placed there too, for the same reason it is placed
    in `CLAUDE.md`: the name outlives the pointer, in commit messages and issues
    that already shipped."""
    assert predecessor_is_placed(section(front_page, README_HEADING)) == AGREE, (
        f"README.md's '{README_HEADING}' does not say that {PREDECESSOR} is the "
        "archived predecessor."
    )


def test_a_missing_front_page_section_is_could_not_evaluate() -> None:
    """Deleting the section is not how either check goes green."""
    assert names_the_running_harness(section("# reg\n\nNothing.\n", README_HEADING)) == (
        COULD_NOT_EVALUATE
    )
    assert predecessor_is_placed(section("# reg\n\nNothing.\n", README_HEADING)) == (
        COULD_NOT_EVALUATE
    )


def test_naming_the_harness_without_linking_it_is_caught() -> None:
    """A name is not a pointer. The section's job is to send a reader there."""
    assert names_the_running_harness(
        f"\nThe writer is {HARNESS}, installed on the worker host.\n"
    ) == DISAGREE


# --- check 2: where the old name is placed ----------------------------------

#: The predecessor marked as what it is, within a sentence of its own name.
#: Both orders, because "the archived predecessor is issue-runner" says it too.
PREDECESSOR_MARKED = re.compile(
    rf"{re.escape(PREDECESSOR)}[^.]{{0,120}}?\b(?:archived|predecessor|superseded"
    rf"|retired|no longer)\b"
    rf"|\b(?:archived|predecessor|superseded|retired)\b[^.]{{0,120}}?"
    rf"{re.escape(PREDECESSOR)}",
    re.IGNORECASE,
)


def predecessor_is_placed(body: str | None) -> str:
    """Verdict on whether `issue-runner` is identified as the old harness.

    DISAGREE covers both failures: never mentioning it, which leaves a reader of
    an older commit message with nothing, and mentioning it unmarked, which is
    the defect itself.
    """
    if body is None:
        return COULD_NOT_EVALUATE
    return AGREE if PREDECESSOR_MARKED.search(normalise(body)) else DISAGREE


def test_the_section_says_what_issue_runner_is(conventions: str) -> None:
    """History in this repository names `issue-runner` — three commits pin a
    version of it. A reader meeting that name needs this sentence."""
    assert predecessor_is_placed(section(conventions)) == AGREE, (
        f"CLAUDE.md's '{HEADING}' does not say that {PREDECESSOR} is the "
        "archived predecessor. Commit messages here still name it."
    )


def test_the_pre_132_paragraph_does_not_place_the_predecessor(
    conventions: str,
) -> None:
    """**The negative.** It mentions `issue-runner` more than any other text in
    the repository, and marks it as nothing."""
    assert predecessor_is_placed(section(PRE_132)) == DISAGREE


def test_dropping_the_old_name_entirely_is_caught() -> None:
    """Silence about the predecessor is not the fix: the name outlives the
    pointer, in every commit message that already shipped."""
    assert predecessor_is_placed(
        f"\nSee [`{HARNESS}`](https://github.com/{HARNESS}) — the harness lives "
        "in its own repo.\n"
    ) == DISAGREE


# --- check 3: the attempt records -------------------------------------------

#: `.wake/` described as something the harness writes, per attempt.
RECORDS_ARE_WRITTEN = re.compile(
    rf"{re.escape(RECORDS)}[^.]{{0,200}}?\b(?:record|written|writes)\b"
    rf"|\b(?:record|written|writes)\b[^.]{{0,200}}?{re.escape(RECORDS)}",
    re.IGNORECASE,
)

#: The instruction: hands off. Both verbs, because deleting a record and editing
#: one destroy it equally.
RECORDS_ARE_OFF_LIMITS = re.compile(
    r"\bdo not\b[^.]{0,160}?\b(?:hand-edit|edit)\b[^.]{0,160}?\bdelete\b"
    r"|\b(?:never|do not)\b[^.]{0,80}?\bdelete\b[^.]{0,160}?\b(?:hand-)?edit\b",
    re.IGNORECASE,
)


def records_are_explained(body: str | None) -> str:
    """Verdict on whether `.wake/` is both introduced and put off limits."""
    if body is None:
        return COULD_NOT_EVALUATE
    flat = normalise(body)
    if RECORDS not in flat:
        return DISAGREE
    if not RECORDS_ARE_WRITTEN.search(flat):
        return DISAGREE
    return AGREE if RECORDS_ARE_OFF_LIMITS.search(flat) else DISAGREE


def test_the_section_explains_the_attempt_records(conventions: str) -> None:
    """An agent will find `.wake/` in its worktree. It has to arrive already
    knowing that the directory is not its to tidy."""
    assert records_are_explained(section(conventions)) == AGREE, (
        f"CLAUDE.md's '{HEADING}' does not say that {RECORDS} holds attempt "
        "records written by the harness and must not be edited or deleted."
    )


def test_the_pre_132_paragraph_says_nothing_about_the_records(
    conventions: str,
) -> None:
    """**The negative.** It predates them entirely."""
    assert records_are_explained(section(PRE_132)) == DISAGREE


def test_describing_the_records_without_forbidding_edits_is_caught() -> None:
    """**The half-statement.** Saying what a file is does not tell an agent to
    leave it alone, and a tidy-minded agent deletes it in good faith."""
    assert records_are_explained(
        f"\nThe harness writes a record of each attempt to {RECORDS} on the "
        "branch.\n"
    ) == DISAGREE


def test_forbidding_edits_without_saying_what_the_directory_is_caught() -> None:
    """The other half. A prohibition with no subject is the kind of rule an
    agent talks itself out of."""
    assert records_are_explained(
        f"\nDo not hand-edit or delete anything under {RECORDS}.\n"
    ) == DISAGREE


# --- check 4: config is still config ----------------------------------------

#: The sentence that enumerates harness-facing files. Sentences are split on a
#: full stop *followed by a space*, because every name in that list has a dot in
#: it and a `[^.]` span would stop inside `.runner.conf`.
ENUMERATION = re.compile(r"harness-facing files?", re.IGNORECASE)


def sentences(text: str) -> list[str]:
    """`text` split into sentences, tolerating dotted filenames."""
    return re.split(r"(?<=\.)\s+", normalise(text))


def harness_facing_files_are_intact(body: str | None) -> tuple[str, list[str]]:
    """Verdict on the file list, plus whichever entries went missing.

    Two ways to fail, and they pull in opposite directions: dropping one of the
    two files an agent must not edit, or adding `.wake/` to the list and turning
    a record into a config file.
    """
    if body is None:
        return COULD_NOT_EVALUATE, []
    flat = normalise(body)
    missing = [name for name in HARNESS_FACING if name not in flat]
    if missing:
        return DISAGREE, missing
    listed_as_config = [
        sentence
        for sentence in sentences(body)
        if ENUMERATION.search(sentence) and RECORDS in sentence
    ]
    if listed_as_config:
        return DISAGREE, [RECORDS]
    return AGREE, []


def test_the_two_harness_facing_files_are_still_listed(conventions: str) -> None:
    """They were listed before #132 and the change was not about them. This is
    the regression guard for the edit itself."""
    verdict, missing = harness_facing_files_are_intact(section(conventions))
    assert verdict == AGREE, (
        f"CLAUDE.md's '{HEADING}' no longer lists {missing} as harness-facing."
    )


def test_listing_the_records_as_a_third_config_file_is_caught() -> None:
    """**The negative for the distinction.** Configuration you may not edit and
    a record you may not edit are different things; the second is evidence."""
    verdict, offenders = harness_facing_files_are_intact(
        "\nThis repo's only harness-facing files are `.runner.conf`, "
        f"`.github/workflows/epic-advance.yml` and {RECORDS}.\n"
    )
    assert (verdict, offenders) == (DISAGREE, [RECORDS])


def test_dropping_one_of_the_two_files_is_caught() -> None:
    """The other direction: a shorter list is a file that stopped being named as
    off limits."""
    verdict, missing = harness_facing_files_are_intact(
        "\nThis repo's only harness-facing file is `.runner.conf`.\n"
    )
    assert verdict == DISAGREE
    assert missing == ["`.github/workflows/epic-advance.yml`"]


# --- check 5: no schema, kept in one place ----------------------------------

#: A claim about what is *inside* a record: a field list, a format, a count.
#: Not a claim: that records exist, that the harness writes them per attempt.
SCHEMA_CLAIM = re.compile(
    r"\b(?:record|records|\.wake/?)\b[^.]{0,120}?\b(?:contains?|holds the|"
    r"consists of|fields?|schema|JSON|YAML|keys?|columns?|format)\b"
    r"|\b(?:each|every)\s+record\s+(?:is|has)\b",
    re.IGNORECASE,
)


def keeps_the_schema_elsewhere(body: str | None) -> tuple[str, list[str]]:
    """Verdict on whether the section stays out of wake-runner's documentation."""
    if body is None:
        return COULD_NOT_EVALUATE, []
    offenders = [
        sentence.strip()
        for sentence in normalise(body).split(". ")
        if SCHEMA_CLAIM.search(sentence)
    ]
    return (DISAGREE if offenders else AGREE), offenders


def test_the_section_does_not_restate_the_record_format(conventions: str) -> None:
    """The schema lives in wake-runner. A second copy here is one nothing in
    this repository can hold to the first, so it drifts silently."""
    verdict, offenders = keeps_the_schema_elsewhere(section(conventions))
    assert verdict == AGREE, (
        f"CLAUDE.md's '{HEADING}' describes what an attempt record contains:\n"
        + "\n".join(f"  - {sentence[:180]}" for sentence in offenders)
        + "\nThat belongs to wake-runner's docs; this file names the directory."
    )


def test_a_restated_schema_is_caught() -> None:
    """**The negative.** Plausible, helpful, and the first half of a drift."""
    verdict, offenders = keeps_the_schema_elsewhere(
        f"\nThe harness writes a record of each attempt to {RECORDS}. Each "
        "record is a JSON file with fields for the issue, the commit and what "
        "the agent could not read.\n"
    )
    assert verdict == DISAGREE
    assert offenders


# --- the third outcome, and why it is not a way to pass ---------------------


def test_a_file_without_the_section_is_could_not_evaluate() -> None:
    """COULD-NOT-EVALUATE, for every predicate, and it never resolves to a
    pass — `test_the_section_exists_to_be_checked` is the other half."""
    body = section("# reg — conventions\n\n## Scope\n\nSee docs/plan.md.\n")
    assert body is None
    assert names_the_running_harness(body) == COULD_NOT_EVALUATE
    assert predecessor_is_placed(body) == COULD_NOT_EVALUATE
    assert records_are_explained(body) == COULD_NOT_EVALUATE
    assert harness_facing_files_are_intact(body) == (COULD_NOT_EVALUATE, [])
    assert keeps_the_schema_elsewhere(body) == (COULD_NOT_EVALUATE, [])


def test_the_section_exists_to_be_checked(conventions: str) -> None:
    """**SILENCE IS NOT A PASS.** Deleting the section would make four of the
    five predicates above unevaluable and none of them fail. An agent with no
    paragraph about the harness is worse off than one with a stale pointer: it
    does not know `.wake/` exists at all."""
    assert section(conventions) is not None, (
        f"CLAUDE.md has no '{HEADING}' section. It is where an unattended agent "
        "learns what is running it and which files are not its to touch."
    )
