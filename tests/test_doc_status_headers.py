"""A document's status header describes the document, and prose does not fail.

Issue #103. `docs/plan.md` is cited by the README nine times as *the argument*
and as the source of every published figure, and its own header called it an
unreconciled brainstorm. `docs/prior-art.md` is normative over `plan.md` — the
README's own rule is *prior art wins* — and its header called it a first pass
when it had four. Neither is a stale-date nit: each tells a reader the document
is less settled than the repository treats it as being, and the reader this
project is written for checks.

The fix is not "delete the disclaimer". A header may say the document is
unreconciled; what it may not do is say it of the whole document without saying
*what*. So the check here is not that `plan.md`'s header is confident. It is
that **the header's list of what is unreconciled is exactly what the body is
missing** — which fails in both directions:

* an item still listed as outstanding that has since landed in the body, and
* an item quietly dropped from the list while still absent from the body.

That is the only form of this check that keeps working. A header asserting its
own confidence is prose about prose; a header enumerating absences can be held
against the file it is the header of.

**Every predicate is fed the pre-#103 header and required to say no.** The
defect being guarded is a *description*, which is the easiest thing to
accidentally assert away with a substring match against a document that mentions
the topic somewhere else — so the negatives below feed each predicate the exact
wording that was there on 2026-08-26, and a mutated body, and require DISAGREE.

Three-valued, per `CLAUDE.md`'s *a check must be able to fail*: a header with no
status line, a body whose section cannot be located, and an empty list are all
COULD-NOT-EVALUATE, and none of them resolves to a pass. Deleting the table is
not how this check gets satisfied.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

PLAN = REPO / "docs" / "plan.md"
PRIOR_ART = REPO / "docs" / "prior-art.md"

AGREE = "AGREE"
DISAGREE = "DISAGREE"
COULD_NOT_EVALUATE = "COULD-NOT-EVALUATE"

NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
}


# --------------------------------------------------------------------------
# Splitting a document into its header and its body. Every presence probe runs
# against the body alone, because the header now *names* the things it says are
# missing — a probe over the whole file would find "SOTER" in the very sentence
# saying SOTER is absent and report the item as landed.
# --------------------------------------------------------------------------


def normalise(text: str) -> str:
    """Strip markdown emphasis and collapse whitespace, nothing else."""
    return re.sub(r"\s+", " ", re.sub(r"[*_`]", "", text))


def header_of(text: str) -> str:
    """Everything above the first horizontal rule — the status block."""
    parts = re.split(r"^---\s*$", text, maxsplit=1, flags=re.MULTILINE)
    return parts[0] if len(parts) == 2 else ""


def body_of(text: str) -> str:
    """Everything below the first horizontal rule — the document itself."""
    parts = re.split(r"^---\s*$", text, maxsplit=1, flags=re.MULTILINE)
    return parts[1] if len(parts) == 2 else ""


def has_status_line(header: str) -> bool:
    return re.search(r"\*\*Status:\*\*", header) is not None


def section(text: str, heading: re.Pattern[str]) -> str:
    """The block introduced by the first heading matching `heading`.

    Runs to the next heading of the same depth or shallower, so a section with
    subheadings comes back whole.
    """
    blocks = re.split(r"\n(?=#{1,6} )", text)
    for index, block in enumerate(blocks):
        first_line = block.split("\n", 1)[0]
        match = re.match(r"(#{1,6}) ", first_line)
        if match is None or not heading.search(first_line):
            continue
        depth = len(match.group(1))
        out = [block]
        for following in blocks[index + 1 :]:
            deeper = re.match(r"(#{1,6}) ", following)
            if deeper is not None and len(deeper.group(1)) <= depth:
                break
            out.append(following)
        return "\n".join(out)
    return ""


def paragraph(text: str, pattern: re.Pattern[str]) -> str:
    """The first blank-line-delimited paragraph matching `pattern`."""
    for block in re.split(r"\n\s*\n", text):
        if pattern.search(normalise(block)):
            return block
    return ""


def verdict(located: str, holds: bool | None) -> str:
    """Three-valued. Nothing located, or nothing decidable, is not a pass."""
    if not located.strip() or holds is None:
        return COULD_NOT_EVALUATE
    return AGREE if holds else DISAGREE


# --------------------------------------------------------------------------
# `docs/plan.md` — the seven changes the four passes ordered into it and it has
# not made. Each probe answers one question of the body it is handed: has this
# change landed? `None` means the place it would live could not be located,
# which is COULD-NOT-EVALUATE and never a pass.
# --------------------------------------------------------------------------


def gap_is_rewritten_around_dssad(body: str) -> bool | None:
    """§1: *The gap this addresses*, in the mandate-versus-proposal form.

    Landed when the section names DSSAD (or the mandate/proposal distinction)
    and no longer ends on the flat claim that the interface is unoccupied
    space — the wording the second pass narrowed everywhere else.
    """
    gap = section(body, re.compile(r"gap this addresses", re.IGNORECASE))
    if not gap.strip():
        return None
    flat = normalise(gap)
    names_it = re.search(r"DSSAD|mandate", flat, re.IGNORECASE) is not None
    return names_it and re.search(r"unoccupied space", flat) is None


def crc_seed_is_the_codename(body: str) -> bool | None:
    """§5: PROFIsafe's CRC seed is the Codename, not "a known value"."""
    deviation = paragraph(body, re.compile(r"PROFIsafe's CRC", re.IGNORECASE))
    if not deviation.strip():
        return None
    return re.search(r"Codename", normalise(deviation), re.IGNORECASE) is not None


def _mentions(pattern: str, flags: int = 0):
    compiled = re.compile(pattern, flags)

    def probe(body: str) -> bool | None:
        return compiled.search(normalise(body)) is not None

    return probe


#: Every change a pass ordered into `plan.md` that `plan.md`'s header currently
#: lists as not made, keyed by the `prior-art.md` section that ordered it. The
#: header is required to list *exactly* the ones whose probe says no.
PLAN_ORDERED_CHANGES = {
    1: gap_is_rewritten_around_dssad,
    5: crc_seed_is_the_codename,
    6: _mentions(r"Hydra|Kimera", re.IGNORECASE),
    11: _mentions(r"ethical black box|Winfield", re.IGNORECASE),
    12: _mentions(r"\b7001\b"),
    17: _mentions(r"\bSOTER\b"),
    19: _mentions(r"SOTIF|\b21448\b"),
}

#: What the same header claims *has* landed. Pinned so the paragraph naming
#: them cannot go on saying so after one is deleted from the body.
PLAN_LANDED_CITATIONS = {
    "DSSAD": re.compile(r"\bDSSAD\b"),
    "EU AI Act Art. 12": re.compile(r"AI Act Art(?:icle)?\.? 12"),
    "ASTM F3269": re.compile(r"F3269"),
    "ARMTD / ARMOUR": re.compile(r"ARMTD|ARMOUR"),
    "Schneier–Kelsey": re.compile(r"Schneier"),
    "ConSerts": re.compile(r"ConSerts"),
    "rosbag2 / MCAP": re.compile(r"rosbag2|MCAP"),
}


def listed_as_outstanding(header: str) -> set[int]:
    """The `prior-art.md` section numbers the header's table names."""
    return {int(n) for n in re.findall(r"^\|\s*§(\d+)\s*\|", header, re.MULTILINE)}


def missing_from_body(body: str) -> tuple[set[int], set[int]]:
    """`(absent, undecidable)` over `PLAN_ORDERED_CHANGES`."""
    absent, undecidable = set(), set()
    for number, probe in PLAN_ORDERED_CHANGES.items():
        landed = probe(body)
        if landed is None:
            undecidable.add(number)
        elif not landed:
            absent.add(number)
    return absent, undecidable


def outstanding_list_matches_the_body(header: str, body: str) -> str:
    """Verdict: does the header's table name exactly what the body lacks?"""
    if not has_status_line(header) or not body.strip():
        return COULD_NOT_EVALUATE
    listed = listed_as_outstanding(header)
    if not listed:
        return COULD_NOT_EVALUATE
    absent, undecidable = missing_from_body(body)
    if undecidable:
        return COULD_NOT_EVALUATE
    return AGREE if listed == absent else DISAGREE


def stated_count(header: str, noun: str) -> int | None:
    """The number word the header gives for `noun`, as an integer."""
    match = re.search(
        rf"\b({'|'.join(NUMBER_WORDS)})\b\s+{noun}\b",
        normalise(header),
        re.IGNORECASE,
    )
    return NUMBER_WORDS[match.group(1).lower()] if match else None


#: Words that describe a whole document as less settled than the repository
#: treats it as being. Permitted only beside an enumeration of what they refer
#: to — which is the distinction issue #103 turns on.
WHOLESALE_DISCLAIMERS = re.compile(
    r"brainstorm|first pass|\bdraft\b|provisional|unreconciled|not yet reconciled",
    re.IGNORECASE,
)


def disclaimer_is_enumerated(header: str) -> str:
    """Verdict: if the header disclaims the document, does it say what of it?"""
    if not has_status_line(header):
        return COULD_NOT_EVALUATE
    if WHOLESALE_DISCLAIMERS.search(normalise(header)) is None:
        return AGREE
    return AGREE if listed_as_outstanding(header) else DISAGREE


# --------------------------------------------------------------------------
# `docs/prior-art.md` — the count of its passes, and its standing over the plan.
# --------------------------------------------------------------------------


PASS_HEADING = re.compile(
    rf"^# ({'|'.join(NUMBER_WORDS)}|first|second|third|fourth|fifth|sixth|seventh)"
    r" pass\b",
    re.IGNORECASE | re.MULTILINE,
)


def passes_in(text: str) -> int:
    return len(PASS_HEADING.findall(text))


def claims_normative_standing(header: str) -> bool | None:
    """Does the header state the standing the README already gives this file?

    Two halves, and both are needed: it has to name `plan.md`, and it has to
    say it wins where they disagree. The old header named `plan.md` and
    subordinated itself to it — *run before Phase 1, as `plan.md` requires* —
    which is the case this predicate exists to separate.
    """
    if not has_status_line(header):
        return None
    flat = normalise(header)
    if re.search(r"plan\.md", flat) is None:
        return False
    return (
        re.search(r"\bnormative\b", flat, re.IGNORECASE) is not None
        or re.search(r"prior art wins", flat, re.IGNORECASE) is not None
    )


# --------------------------------------------------------------------------
# THE CHECKS, against the files as they stand.
# --------------------------------------------------------------------------


def read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:  # pragma: no cover - a missing doc is not a pass
        return ""


def test_the_plan_header_does_not_disclaim_the_document_wholesale() -> None:
    """The README cites this file nine times as the argument.

    Issue #103: a reader who checks the authority finds the authority
    disclaiming itself. The header may still use the word — it does — but only
    beside the list of what the word refers to.
    """
    header = header_of(read(PLAN))
    assert disclaimer_is_enumerated(header) == AGREE, (
        "docs/plan.md's header describes the document as less settled than the "
        "repository treats it as being, and does not say which part. Say what "
        "is unreconciled — the table of ordered-but-unmade changes — rather "
        "than labelling the whole file."
    )


def test_the_plan_headers_outstanding_list_is_exactly_what_the_body_lacks() -> None:
    """**THE CHECK THIS ISSUE EXISTS FOR.**

    Both directions. An item that has since landed and is still listed makes
    the header understate the file; an item dropped from the list while still
    absent makes it overstate it. Only the equality is the property.
    """
    text = read(PLAN)
    header, body = header_of(text), body_of(text)
    result = outstanding_list_matches_the_body(header, body)
    assert result != COULD_NOT_EVALUATE, (
        "docs/plan.md's header carries no table of outstanding changes, or a "
        "probe could not locate the section it asks about. That is "
        "COULD-NOT-EVALUATE, not a pass: deleting the table is not a way to "
        "have nothing outstanding."
    )
    listed = listed_as_outstanding(header)
    absent, _ = missing_from_body(body)
    assert result == AGREE, (
        "docs/plan.md's header lists "
        f"{sorted(listed)} as unreconciled, and the body is actually missing "
        f"{sorted(absent)}. Landed since: {sorted(listed - absent)}. Missing "
        f"and unlisted: {sorted(absent - listed)}. The header is the only "
        "place a reader is told which it is."
    )


def test_the_plan_header_counts_the_items_it_lists() -> None:
    """The prose count and the table are one claim, so they move together."""
    header = header_of(read(PLAN))
    count = stated_count(header, "items")
    assert count is not None, (
        "docs/plan.md's header gives no count of outstanding items. "
        "COULD-NOT-EVALUATE — the sentence a reader takes the number from is "
        "the one that has to be checkable."
    )
    assert count == len(listed_as_outstanding(header)), (
        f"docs/plan.md's header says {count} outstanding items and tabulates "
        f"{len(listed_as_outstanding(header))}."
    )


@pytest.mark.parametrize("citation", sorted(PLAN_LANDED_CITATIONS))
def test_each_citation_the_plan_header_claims_landed_is_in_the_body(
    citation: str,
) -> None:
    """The other half of the header's claim, and the easier one to rot."""
    body = normalise(body_of(read(PLAN)))
    assert body.strip(), "docs/plan.md could not be split into header and body"
    assert PLAN_LANDED_CITATIONS[citation].search(body), (
        f"docs/plan.md's header says {citation} is in this file and it is not. "
        "Either it was removed or it never landed; either way the header is "
        "now claiming a reconciliation that did not happen."
    )


def test_the_prior_art_header_counts_the_passes_the_file_has() -> None:
    """*First pass* stood while the file grew to four.

    The count is derived from the file's own pass headings, so a fifth pass
    added without touching the header fails here rather than in front of a
    reader.
    """
    text = read(PRIOR_ART)
    header = header_of(text)
    actual = passes_in(body_of(text))
    assert actual, (
        "docs/prior-art.md has no `# Nth pass` headings to count. "
        "COULD-NOT-EVALUATE: the header's claim about its own structure cannot "
        "be checked against a file that no longer has that structure."
    )
    claimed = stated_count(header, "passes")
    assert claimed is not None, (
        "docs/prior-art.md's header does not say how many passes it has. It "
        "said *first pass* for three of them."
    )
    assert claimed == actual, (
        f"docs/prior-art.md's header claims {claimed} passes; the file has "
        f"{actual}."
    )


def test_the_prior_art_header_states_its_standing_over_the_plan() -> None:
    """*Prior art wins* is the README's rule; the header said *first pass*.

    A header that describes this file as a preliminary of `plan.md` contradicts
    the standing it is given everywhere else, and the contradiction costs the
    reader's confidence in whichever of the two they read second.
    """
    header = header_of(read(PRIOR_ART))
    assert verdict(header, claims_normative_standing(header)) == AGREE, (
        "docs/prior-art.md's header does not state that it is normative where "
        "it disagrees with docs/plan.md. That is the README's stated rule and "
        "this file has exercised it four times."
    )


# --------------------------------------------------------------------------
# THE NEGATIVES. Every predicate above, fed the wording that was actually there
# before issue #103 — and a mutated body — and required to say no.
# --------------------------------------------------------------------------


#: `docs/plan.md`'s header exactly as it stood on 2026-08-26.
BEFORE_PLAN_HEADER = """# Reachability Evidence Graph — prototype plan

**Status:** brainstorm, v2 · captured 2026-08-18 · not yet reconciled against `prior-art.md`

This is the source document for `reg`. It is a brainstorm, not a specification:
where it and `docs/prior-art.md` disagree, prior art wins and this file gets
edited. Phases are cut when research shows they reinvent something with a name.
"""

#: `docs/prior-art.md`'s header exactly as it stood on 2026-08-26.
BEFORE_PRIOR_ART_HEADER = """# Prior art — what exists, what this borrows, what it must not claim

**Status:** first pass, 2026-08-18 · run before Phase 1, as `plan.md` requires

The purpose of this pass was to find where the plan reinvents something with a
name. It found four things that change the plan and one that sharpens the
positioning considerably.
"""


def test_the_pre_issue_plan_header_is_a_wholesale_disclaimer() -> None:
    """Fed what was there, the enumeration check must say no."""
    assert disclaimer_is_enumerated(BEFORE_PLAN_HEADER) == DISAGREE


def test_the_pre_issue_plan_header_lists_nothing_to_check() -> None:
    """And the equality check must refuse to pass it.

    COULD-NOT-EVALUATE rather than DISAGREE, and deliberately: the old header
    made no claim about *which* changes were unmade, so there is nothing to
    compare the body against. The point is that it does not resolve to AGREE.
    """
    body = body_of(read(PLAN))
    assert (
        outstanding_list_matches_the_body(BEFORE_PLAN_HEADER, body)
        == COULD_NOT_EVALUATE
    )


def test_a_header_that_disclaims_without_a_status_line_is_undecidable() -> None:
    """An empty header is not a confident one."""
    assert disclaimer_is_enumerated("# Title\n\nsome prose\n") == COULD_NOT_EVALUATE


def test_an_item_that_has_landed_but_is_still_listed_fails() -> None:
    """The first direction: the body gains SOTER, the header does not notice."""
    text = read(PLAN)
    header, body = header_of(text), body_of(text)
    assert outstanding_list_matches_the_body(header, body) == AGREE
    landed = body + "\n\nPhase 4 is Simplex, as SOTER implemented it in 2019.\n"
    assert outstanding_list_matches_the_body(header, landed) == DISAGREE


def test_an_item_dropped_from_the_list_while_still_absent_fails() -> None:
    """The second, and the one a tidy-up would cause: the row is deleted."""
    text = read(PLAN)
    header, body = header_of(text), body_of(text)
    trimmed = re.sub(r"^\|\s*§17\s*\|.*\n", "", header, flags=re.MULTILINE)
    assert listed_as_outstanding(trimmed) == listed_as_outstanding(header) - {17}
    assert outstanding_list_matches_the_body(trimmed, body) == DISAGREE


def test_a_body_whose_gap_section_is_gone_is_undecidable() -> None:
    """Deleting the section a probe asks about is not a way to satisfy it."""
    body = body_of(read(PLAN))
    without = re.sub(
        r"### The gap this addresses", "### Something else entirely", body
    )
    assert gap_is_rewritten_around_dssad(without) is None
    assert (
        outstanding_list_matches_the_body(header_of(read(PLAN)), without)
        == COULD_NOT_EVALUATE
    )


def test_the_crc_probe_says_no_to_the_wording_that_is_there() -> None:
    """§5's correction is genuinely unmade, and the probe has to see that."""
    body = body_of(read(PLAN))
    assert crc_seed_is_the_codename(body) is False
    corrected = body.replace(
        "PROFIsafe's CRC is seeded with a known value",
        "PROFIsafe's CRC is seeded with the Codename, a configured per-device value",
    )
    assert corrected != body, (
        "docs/plan.md no longer carries the wording §5 corrected. If deviation "
        "1 was rewritten, §5 belongs off the header's outstanding list."
    )
    assert crc_seed_is_the_codename(corrected) is True


def test_the_pre_issue_prior_art_header_does_not_count_its_passes() -> None:
    """*first pass* is not a count, so the check cannot resolve to a pass."""
    assert stated_count(BEFORE_PRIOR_ART_HEADER, "passes") is None


def test_the_pre_issue_prior_art_header_claims_no_standing() -> None:
    """It names `plan.md` — and subordinates itself to it.

    This is the discriminating case for the predicate: a substring match on
    `plan.md` alone would have called the old header correct.
    """
    assert re.search(r"plan\.md", BEFORE_PRIOR_ART_HEADER) is not None
    assert claims_normative_standing(BEFORE_PRIOR_ART_HEADER) is False


def test_a_prior_art_header_with_a_stale_count_fails() -> None:
    """A header still claiming the count the file had one pass ago.

    Derived from the file's own count rather than written as a literal. The
    fixture said *four passes, a header still saying three* until the fifth
    pass landed (issue #138) and then failed — on the arithmetic, not on the
    defect — which is a negative test that has to be edited every time the
    thing it guards happens. The defect is the header lagging the body, and it
    is the same defect at any number.
    """
    header, body = header_of(read(PRIOR_ART)), body_of(read(PRIOR_ART))
    current = passes_in(body)
    assert current >= 2, "a one-pass file has no stale count to construct"
    assert stated_count(header, "passes") == current
    word = {number: name for name, number in NUMBER_WORDS.items()}
    stale = header.replace(
        f"{word[current]} passes", f"{word[current - 1]} passes"
    )
    assert stale != header, (
        "the header does not spell its count as a number word, so the stale "
        "fixture could not be built — COULD-NOT-EVALUATE, not a pass"
    )
    assert stated_count(stale, "passes") == current - 1
    assert stated_count(stale, "passes") != passes_in(body)
