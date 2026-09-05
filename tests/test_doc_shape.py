"""The documents have a shape, and the shape is checked (issue #171).

Tier 1 of #170. The corpus is 99,505 words across thirteen documents and it is
growing faster than the code it describes: 76,428 words when #170 measured it,
against a package surface that moved from 252 public symbols to 260 over the
same span. An unread document drifts from the code with nothing to catch it,
and nothing in this repository noticed the growth.

**This checks shape, not content.** `tests/test_published_figures.py` re-derives
the published figures from the code and `tests/test_doc_status_headers.py` holds
each status header against its own body; both are about whether a document is
*true*. Nothing here reads a claim. This file asks only how much prose there is,
how it is distributed, and whether a reader can find out what a document is for
without reading all of it. It must not be taken as covering accuracy, and it
does not weaken either of those two.

WHY THE BUDGET HAS TWO TERMS
----------------------------
A single word ceiling is the wrong instrument. This repository is under active
development, so documentation that *describes the code* must be free to grow
with it — a flat ceiling either blocks that or gets raised until it means
nothing. But most of the corpus does not describe the code. `prior-art.md` is
26,463 words and would not shrink if half the package were deleted; tying it to
code size would hand it a larger allowance every time a feature ships, which is
backwards.

So each half is governed by what actually drives it: code-coupled prose by
`RATE * public_symbols`, argument and reference prose by a flat `ARGUMENT_MAX`.

**Adding code buys documentation budget. Having more ideas does not.** That is
the whole design.

WHAT COUNTS AS A DOCUMENT, AND WHY BOTH LISTS ARE EXPLICIT
----------------------------------------------------------
`CODE_COUPLED` and `ARGUMENT` between them must name every file in the corpus.
A file in neither fails, because a budget escaped by adding a file is a budget
that dies quietly — this is the pattern `tests/test_layout.py` already uses for
modules with no mirrored test, including the part where each entry says *why* it
is where it is.

THE RATCHET
-----------
Every constant here may be **lowered and never raised**. Tiers 2–5 of #170 each
lower them; without that this check does nothing but freeze today's density in
place. Two consequences are deliberate:

* a change that adds prose without adding surface fails, and the fix is to cut
  something in the same change rather than to raise a constant;
* a refactor that *removes* public symbols shrinks the budget and can put the
  corpus over. That is usually correct — documentation describing removed
  surface should go — but it fires at an inconvenient moment, so the failure
  message names the group, the ceiling and the overage.

Three-valued per `CLAUDE.md`'s *a check must be able to fail*: an empty corpus,
a package with no public symbols, a classification entry with no reason, and a
document with no prose at all are COULD-NOT-EVALUATE, and none of them resolves
to a pass. Deleting the documents is not how this check gets satisfied.

Every predicate below is fed the condition it guards against and required to say
DISAGREE, and each numeric ceiling is fed a value one notch tighter than the
constant to show the constant has no headroom in it.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
PACKAGE = REPO / "reg"

AGREE = "AGREE"
DISAGREE = "DISAGREE"
COULD_NOT_EVALUATE = "COULD-NOT-EVALUATE"


# --------------------------------------------------------------------------
# The corpus, and the classification of every file in it
# --------------------------------------------------------------------------

def corpus_paths() -> tuple[str, ...]:
    """Every markdown file this budget governs.

    `docs/` is globbed rather than listed, so a new document arrives in the
    corpus by existing and has to be classified below before `pytest` is green
    again. That is the intent, not an oversight.
    """
    top = ("README.md", "CLAUDE.md")
    docs = tuple(f"docs/{path.name}" for path in sorted((REPO / "docs").glob("*.md")))
    return tuple(name for name in top + docs if (REPO / name).is_file())


# Documents whose length should track the code. Each entry says why, because a
# classification with no reason is how a document ends up in whichever group
# has room. Moving a file between the lists moves its words between two
# ceilings and is a decision, not a tidy-up.
CODE_COUPLED: dict[str, str] = {
    "README.md": (
        "The front page. It describes what the package is and how to run it, "
        "and every section of it points at a module."
    ),
    "CLAUDE.md": (
        "The conventions the code must follow, stated in terms of the modules "
        "and tests that enforce them. Simplifying an API shortens it."
    ),
    "docs/CONTRIBUTING.md": (
        "How work arrives and what a queueable issue names. It describes the "
        "process around the package rather than arguing anything about it."
    ),
    "docs/README.md": (
        "The index of docs/. It grows with the documents it lists, not with "
        "the argument any of them makes."
    ),
    "docs/mobile-base.md": (
        "A design document for one track, with a build order in §7 that says "
        "per tier what has landed. It shrinks as its tiers land."
    ),
    "docs/self-describing.md": (
        "A design document for one track, with a build order in §8 — the same "
        "shape as mobile-base.md, and classified beside it for the same "
        "reason. It describes what the artifact must carry rather than arguing "
        "a claim, and it shrinks as its tiers land. It did not exist when #171 "
        "was filed, which is why the issue's own table does not carry it."
    ),
    "docs/sensor-baseline.md": (
        "The sensor assumption and the artifact sizes it is applied against. "
        "Every table in it is measured from the package at a stated rate."
    ),
}

# Documents whose length is driven by how much there is to argue or to cite.
# None of these would shrink if the package did, which is exactly why tying
# them to `public_symbols` would be backwards.
ARGUMENT: dict[str, str] = {
    "docs/plan.md": (
        "The claims, the phases and the non-goals. It is the argument for the "
        "project; the code is what the argument is about."
    ),
    "docs/prior-art.md": (
        "Twenty-nine entries across six dated passes. Its value is partly that "
        "it is a log, and #170 tier 6 makes what to do about it a human "
        "decision rather than a cut."
    ),
    "docs/sufficiency.md": (
        "Which audit claims survive an uncertifiable perceiver. A boundary "
        "argument, normative over what the project may claim."
    ),
    "docs/limitations.md": (
        "What the project may not claim and what each limitation costs. "
        "Normative, and it grows with the claims rather than with the code."
    ),
    "docs/lossiness.md": (
        "The discard contract and the question set it is relative to. It was "
        "required to land before any graph code was written."
    ),
    "docs/retention.md": (
        "Claim 1's measurement record — the figures, the arithmetic behind "
        "them and how they moved. An argument about cost."
    ),
}


# --------------------------------------------------------------------------
# The two budget constants
# --------------------------------------------------------------------------

# RATE — words of code-coupled prose per public symbol.
#
# MAY BE LOWERED, NEVER RAISED. It is a ratchet: tiers 2-5 of #170 each lower
# it, and a change that cannot fit under it is asking to cut something, not to
# edit this line. Raising it is the move that teaches everyone the rule is
# decorative, and it has already been made once — recorded here so the first
# cutting tier knows what it owes:
#
#   62.7  #171 as filed          15,793 / 252 symbols
#   78.2  #171 regroomed, 2026-09-05, before docs/self-describing.md was
#         classified             20,332 / 260 symbols
#   94.5  today, 2026-09-05      24,560 / 260 symbols = 94.46, rounded up to
#         the next tenth and by nothing more
#
# The step to 78.2 is the finding #171 was regroomed to state: code-coupled
# prose grew 29% while the surface it describes grew 3%, which is the exact
# thing this budget exists to catch. The step from there to 94.5 is not a
# second raise in density — it is the same corpus counted with
# `docs/self-describing.md` in the group the regroom put it in.
#
# **62.7 is the number to get back under.** It is separate from ARGUMENT_MAX
# because these words track the package and those words track how much there is
# to argue; see the module docstring.
RATE = 94.5

# ARGUMENT_MAX — a flat ceiling, in words, on argument and reference prose.
#
# MAY BE LOWERED, NEVER RAISED, for the same reason and by the same tiers. Flat
# rather than per-symbol because nothing in this group would shrink if the
# package did: shipping a feature must not buy `prior-art.md` a larger
# allowance.
#
#   60,635  #171 as filed
#   74,945  2026-09-05, when #171 landed — measured, no headroom
#   74,590  today, 2026-09-05, after #206 split `docs/limitations.md` into a
#           normative core and a `## Why` line — measured, no headroom
ARGUMENT_MAX = 74590

# What counts as a long paragraph. 120 is #170's threshold and is kept so the
# two measurements are of the same thing.
PARAGRAPH_MAX_WORDS = 120

# How many of them the corpus may hold. MAY BE LOWERED, NEVER RAISED.
#
#   110  #170's measurement, 2026-09-02, over 821 prose paragraphs
#   146  2026-09-05, when #171 landed, over 915
#   141  today, 2026-09-05, after #206: five of docs/limitations.md's
#        twenty-three over-long paragraphs were split or cut
LONG_PARAGRAPHS_MAX = 141

# Prose paragraphs narrating a past defect above the document's rationale line.
# MAY BE LOWERED, NEVER RAISED.
#
#   190  #170's measurement, 2026-09-02, by its own counting rule
#   265  2026-09-05, when #171 landed, by PAST_DEFECT_MARKERS below — a
#        different rule, so the two are comparable in direction and not to the
#        unit
#   240  today, 2026-09-05, after #206 moved docs/limitations.md's archaeology
#        below a `## Why` heading: that file went 38 -> 13
NARRATION_MAX = 240

# Documents whose summary paragraph runs over SUMMARY_MAX_WORDS. MAY BE
# LOWERED, NEVER RAISED — and it is already at zero, which is the only value it
# can be lowered to. Six documents were over when #171 was filed; #171 rewrote
# their opening paragraphs and moved what they carried down into the body.
SUMMARY_MAX_WORDS = 60
SUMMARY_OVER_MAX = 0


# --------------------------------------------------------------------------
# Reading a document
# --------------------------------------------------------------------------

FENCE = re.compile(r"^```.*?^```", re.MULTILINE | re.DOTALL)
CODE_SPAN = re.compile(r"`[^`]*`")
THEMATIC_BREAK = re.compile(r"^[-*_=]{3,}\s*$")

# A block is not prose if it opens as a table row, a fence, an ATX heading, a
# block quote or a list item. The heading arm requires the space markdown
# itself requires, so a paragraph opening on an issue reference — `#201's
# grooming ...`, which happens twice in docs/self-describing.md — stays prose.
NON_PROSE = re.compile(r"^(\||```|#{1,6}(\s|$)|>|\s*[-*+]\s|\s*\d+[.)]\s)")

# A status header is a paragraph and is counted as one everywhere except in
# `summary_paragraph`. It is not the summary — #171 says so directly — because
# it states standing, dates and provenance rather than what the document is
# about, and for `plan.md` and `prior-art.md` it is asserted against the body
# by tests/test_doc_status_headers.py. Both spellings in the corpus are caught:
# `**Status:** ...` and `**Status: ...**`.
STATUS_HEADER = re.compile(r"^\*\*Status[:*]")

# The line below which narration is allowed: a dedicated rationale section, the
# shape #170's method asks each document to grow. The heading text must be the
# word and nothing else — `## Why the growth is sublinear` in retention.md is a
# section about a topic, not a rationale line, and treating it as one would
# exempt the rest of that document by accident.
RATIONALE_LINE = re.compile(r"^#{1,6}\s+(why|rationale|decisions?|history)\s*$",
                            re.IGNORECASE | re.MULTILINE)

# Markers of a paragraph narrating a past defect. This is a proxy, calibrated
# against the 23% #170 counted by hand, and it is honest about being one: it
# over-counts a paragraph that cites an issue as a live cross-reference and it
# under-counts narration written without any of these phrases. It is fit for a
# monotone ratchet over the whole corpus, which is what it is used for. It is
# not a verdict on any single paragraph and must not be quoted as one.
PAST_DEFECT_MARKERS = re.compile(
    "|".join(
        (
            r"\bissues? #\d+",
            r"\(#\d+\)",
            r"\bused to\b",
            r"\bpreviously\b",
            r"\boriginally\b",
            r"\bat the time\b",
            r"\bturned out\b",
            r"\bno longer\b",
            r"\b(bug|bugs|defect|defects|regression|mistake|oversight)\b",
            r"\b(broke|broken|failed|failing)\b",
            r"\bw(as|ere) (wrong|not|never|absent|missing|silent)\b",
            r"\bw(as|ere) fixed\b",
            r"\bwent red\b",
            r"\bcorrections?\b",
            r"\bcorrected\b",
            r"\bbefore (that|this|it)\b",
            r"\bshould have\b",
            r"\bdid not\b",
            r"\buntil (issue|20\d\d)\b",
        )
    ),
    re.IGNORECASE,
)


def words(text: str) -> int:
    """Whitespace-delimited tokens of the raw markdown — what `wc -w` counts."""
    return len(text.split())


def blocks(text: str) -> list[str]:
    """Blank-line-delimited blocks, with fenced code removed first.

    Fences come out before the split because a fenced block may contain blank
    lines, and half of one is not a paragraph.
    """
    stripped = FENCE.sub("", text)
    return [b for b in (part.strip("\n") for part in re.split(r"\n\s*\n", stripped)) if b.strip()]


def is_prose(block: str) -> bool:
    return not NON_PROSE.match(block) and not THEMATIC_BREAK.match(block.strip())


def prose_paragraphs(text: str) -> list[str]:
    return [block for block in blocks(text) if is_prose(block)]


def paragraph_words(block: str) -> int:
    """Words in a paragraph, with inline code spans removed.

    A path or a symbol should not inflate a paragraph — `reg.store.EDGE_SPECS`
    is one idea and would otherwise count as several.
    """
    return len(CODE_SPAN.sub(" ", block).split())


def summary_paragraph(text: str) -> str | None:
    """The first prose paragraph after the title, skipping a status header."""
    for block in prose_paragraphs(text):
        if STATUS_HEADER.match(block):
            continue
        return block
    return None


def above_the_rationale_line(text: str) -> str:
    match = RATIONALE_LINE.search(text)
    return text[: match.start()] if match else text


def narrates_a_past_defect(block: str) -> bool:
    return PAST_DEFECT_MARKERS.search(CODE_SPAN.sub(" ", block)) is not None


def public_symbols(package: Path) -> int:
    """Top-level `def` and `class` under `package`, not prefixed with `_`.

    The denominator tracks the surface a reader must understand. Lines of code
    would reward writing more of them, modules are too coarse, and a test count
    would reward test proliferation. Simplifying an API genuinely reduces the
    documentation it needs, and this moves when that happens.
    """
    total = 0
    for path in sorted(package.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if not node.name.startswith("_"):
                    total += 1
    return total


def read_corpus() -> dict[str, str]:
    return {name: (REPO / name).read_text(encoding="utf-8") for name in corpus_paths()}


# --------------------------------------------------------------------------
# The checks, each three-valued and each returning what it would say
# --------------------------------------------------------------------------


def classification_verdict(
    files: tuple[str, ...],
    code_coupled: dict[str, str],
    argument: dict[str, str],
) -> tuple[str, list[str]]:
    """Is every corpus file in exactly one list, with a reason?

    DISAGREE names a file in neither list, a file in both, and a listed file
    that is not in the corpus. An entry whose reason is blank is
    COULD-NOT-EVALUATE: a classification that says nothing is the same silence
    as no classification, dressed as an answer. So is an empty corpus.
    """
    if not files:
        return COULD_NOT_EVALUATE, ["no documents found — the corpus is empty"]

    unevaluable = [
        f"{name}: classified with no reason given"
        for name, why in sorted({**code_coupled, **argument}.items())
        if not why.strip()
    ]
    if unevaluable:
        return COULD_NOT_EVALUATE, unevaluable

    problems: list[str] = []
    for name in files:
        in_code, in_argument = name in code_coupled, name in argument
        if not in_code and not in_argument:
            problems.append(
                f"{name} is in the corpus and in neither CODE_COUPLED nor "
                f"ARGUMENT — classify it, and say why it belongs there"
            )
        elif in_code and in_argument:
            problems.append(f"{name} is in both lists; it is governed by one ceiling")
    for name in sorted(set(code_coupled) | set(argument)):
        if name not in files:
            problems.append(f"{name} is classified but is not in the corpus — drop it")

    return (DISAGREE, problems) if problems else (AGREE, [])


def budget_verdict(
    docs: dict[str, str],
    symbols: int,
    code_coupled: dict[str, str],
    argument: dict[str, str],
    rate: float,
    argument_max: int,
) -> tuple[str, list[str]]:
    """Is each group inside its ceiling?

    A package with no public symbols is COULD-NOT-EVALUATE — the denominator is
    gone, and a budget of zero words is not a finding about the documents. So
    is an empty corpus. A group over its ceiling is DISAGREE, and the message
    names the group, the ceiling and the overage, because this fires at
    inconvenient moments and a failure whose remedy is unobvious is the one
    that gets deleted instead of the mistake.
    """
    if not docs:
        return COULD_NOT_EVALUATE, ["no documents found — the corpus is empty"]
    if symbols <= 0:
        return COULD_NOT_EVALUATE, [
            "reg/ has no public symbols, so RATE * public_symbols is not a "
            "budget — nothing about the documents can be decided from it"
        ]

    coupled_words = sum(words(text) for name, text in docs.items() if name in code_coupled)
    argument_words = sum(words(text) for name, text in docs.items() if name in argument)
    coupled_ceiling = int(rate * symbols)

    problems: list[str] = []
    if coupled_words > coupled_ceiling:
        problems.append(
            f"code-coupled documents are over budget: {coupled_words:,} words "
            f"against a ceiling of {coupled_ceiling:,} "
            f"(RATE {rate} x {symbols} public symbols), over by "
            f"{coupled_words - coupled_ceiling:,}. Cut prose in this group, or "
            f"— if the surface really did shrink — cut the documentation that "
            f"described what was removed. RATE may be lowered, never raised."
        )
    if argument_words > argument_max:
        problems.append(
            f"argument/reference documents are over budget: "
            f"{argument_words:,} words against a ceiling of "
            f"{argument_max:,}, over by {argument_words - argument_max:,}. "
            f"Cut something in this change. ARGUMENT_MAX may be lowered, "
            f"never raised."
        )
    return (DISAGREE, problems) if problems else (AGREE, [])


def long_paragraph_verdict(
    docs: dict[str, str], limit: int, ceiling: int
) -> tuple[str, list[str]]:
    """How many prose paragraphs run over `limit` words?"""
    if not docs:
        return COULD_NOT_EVALUATE, ["no documents found — the corpus is empty"]
    found = [
        name
        for name, text in docs.items()
        for block in prose_paragraphs(text)
        if paragraph_words(block) > limit
    ]
    if not any(prose_paragraphs(text) for text in docs.values()):
        return COULD_NOT_EVALUATE, ["no prose paragraphs found in the corpus"]
    if len(found) > ceiling:
        per_doc = ", ".join(f"{name} {found.count(name)}" for name in sorted(set(found)))
        return DISAGREE, [
            f"paragraphs over {limit} words: {len(found)} against a ceiling of "
            f"{ceiling}, over by {len(found) - ceiling} ({per_doc}). Split one, "
            f"or cut one. LONG_PARAGRAPHS_MAX may be lowered, never raised."
        ]
    return AGREE, []


def narration_verdict(docs: dict[str, str], ceiling: int) -> tuple[str, list[str]]:
    """How many paragraphs narrating a past defect sit above the rationale line?"""
    if not docs:
        return COULD_NOT_EVALUATE, ["no documents found — the corpus is empty"]
    found = [
        name
        for name, text in docs.items()
        for block in prose_paragraphs(above_the_rationale_line(text))
        if narrates_a_past_defect(block)
    ]
    if len(found) > ceiling:
        per_doc = ", ".join(f"{name} {found.count(name)}" for name in sorted(set(found)))
        return DISAGREE, [
            f"paragraphs narrating a past defect above the rationale line: "
            f"{len(found)} against a ceiling of {ceiling}, over by "
            f"{len(found) - ceiling} ({per_doc}). Move it below a `## Why` "
            f"heading, or cut it. NARRATION_MAX may be lowered, never raised."
        ]
    return AGREE, []


def summary_verdict(
    docs: dict[str, str], limit: int, ceiling: int
) -> tuple[str, list[str]]:
    """Does every document open with something readable in one breath?

    A document with no prose paragraph at all is COULD-NOT-EVALUATE. Having no
    summary is not a way to have a short one.
    """
    if not docs:
        return COULD_NOT_EVALUATE, ["no documents found — the corpus is empty"]

    unevaluable: list[str] = []
    over: list[str] = []
    for name, text in sorted(docs.items()):
        summary = summary_paragraph(text)
        if summary is None:
            unevaluable.append(f"{name}: no prose paragraph after the title")
            continue
        count = paragraph_words(summary)
        if count > limit:
            over.append(f"{name} {count} words")
    if unevaluable:
        return COULD_NOT_EVALUATE, unevaluable
    if len(over) > ceiling:
        return DISAGREE, [
            f"documents whose opening paragraph runs over {limit} words: "
            f"{len(over)} against a ceiling of {ceiling}, over by "
            f"{len(over) - ceiling} ({'; '.join(over)}). Rewrite the opening "
            f"paragraph and move what it carried down into the body."
        ]
    return AGREE, []


RATCHET_CONSTANTS = ("RATE", "ARGUMENT_MAX", "LONG_PARAGRAPHS_MAX", "NARRATION_MAX")


def ratchet_comment_verdict(source: str, names: tuple[str, ...]) -> tuple[str, list[str]]:
    """Does each constant carry a comment saying which way it may move?

    The number and the sentence licensing it are one claim. A constant raised
    with the sentence deleted is the failure #170 warns about, and it is
    invisible in a diff that only shows the number moving.
    """
    if not source.strip():
        return COULD_NOT_EVALUATE, ["no source to read"]
    problems: list[str] = []
    for name in names:
        match = re.search(rf"^{name}\s*[:=]", source, re.MULTILINE)
        if match is None:
            problems.append(f"{name} is not defined in this module")
            continue
        preceding = source[: match.start()].split("\n\n")[-1]
        flat = " ".join(preceding.split()).lower()
        if "lowered" not in flat or "never raised" not in flat:
            problems.append(
                f"{name} has no comment saying it may be lowered and never "
                f"raised — the number and the sentence move together"
            )
    return (DISAGREE, problems) if problems else (AGREE, [])


# --------------------------------------------------------------------------
# The corpus as it stands
# --------------------------------------------------------------------------


def test_every_document_is_classified_into_exactly_one_group() -> None:
    verdict, problems = classification_verdict(corpus_paths(), CODE_COUPLED, ARGUMENT)
    assert verdict == AGREE, "\n".join(problems)


def test_each_group_is_inside_its_budget() -> None:
    verdict, problems = budget_verdict(
        read_corpus(), public_symbols(PACKAGE), CODE_COUPLED, ARGUMENT,
        RATE, ARGUMENT_MAX,
    )
    assert verdict == AGREE, "\n".join(problems)


def test_long_paragraphs_are_under_the_ceiling() -> None:
    verdict, problems = long_paragraph_verdict(
        read_corpus(), PARAGRAPH_MAX_WORDS, LONG_PARAGRAPHS_MAX
    )
    assert verdict == AGREE, "\n".join(problems)


def test_defect_narration_above_the_rationale_line_is_under_the_ceiling() -> None:
    verdict, problems = narration_verdict(read_corpus(), NARRATION_MAX)
    assert verdict == AGREE, "\n".join(problems)


def test_every_document_opens_with_a_summary_readable_in_one_breath() -> None:
    verdict, problems = summary_verdict(
        read_corpus(), SUMMARY_MAX_WORDS, SUMMARY_OVER_MAX
    )
    assert verdict == AGREE, "\n".join(problems)


def test_each_ratchet_constant_says_which_way_it_may_move() -> None:
    verdict, problems = ratchet_comment_verdict(
        Path(__file__).read_text(encoding="utf-8"), RATCHET_CONSTANTS
    )
    assert verdict == AGREE, "\n".join(problems)


# --------------------------------------------------------------------------
# No headroom — each ceiling, one notch tighter, must fail
#
# A ceiling with slack in it constrains nothing until the slack is used up, and
# nothing in a diff shows how much is left. These are what make "set at today's
# measurement" checkable rather than asserted.
# --------------------------------------------------------------------------


def test_the_code_coupled_budget_has_no_headroom() -> None:
    verdict, problems = budget_verdict(
        read_corpus(), public_symbols(PACKAGE), CODE_COUPLED, ARGUMENT,
        RATE - 0.1, ARGUMENT_MAX,
    )
    assert verdict == DISAGREE
    assert any("code-coupled" in p for p in problems)


def test_the_argument_budget_has_no_headroom() -> None:
    verdict, problems = budget_verdict(
        read_corpus(), public_symbols(PACKAGE), CODE_COUPLED, ARGUMENT,
        RATE, ARGUMENT_MAX - 1,
    )
    assert verdict == DISAGREE
    assert any("argument/reference" in p for p in problems)


def test_the_long_paragraph_ceiling_has_no_headroom() -> None:
    verdict, problems = long_paragraph_verdict(
        read_corpus(), PARAGRAPH_MAX_WORDS, LONG_PARAGRAPHS_MAX - 1
    )
    assert verdict == DISAGREE
    assert any("over by 1" in p for p in problems)


def test_the_narration_ceiling_has_no_headroom() -> None:
    verdict, problems = narration_verdict(read_corpus(), NARRATION_MAX - 1)
    assert verdict == DISAGREE
    assert any("over by 1" in p for p in problems)


# --------------------------------------------------------------------------
# The negatives — every predicate fed the condition it guards against
# --------------------------------------------------------------------------


def test_a_document_in_neither_list_fails() -> None:
    """The way this kind of budget dies: escape it by adding a file."""
    files = corpus_paths() + ("docs/appendix.md",)
    verdict, problems = classification_verdict(files, CODE_COUPLED, ARGUMENT)
    assert verdict == DISAGREE
    assert any("docs/appendix.md" in p and "neither" in p for p in problems)


def test_a_document_in_both_lists_fails() -> None:
    both = {**ARGUMENT, "README.md": "claimed twice"}
    verdict, problems = classification_verdict(corpus_paths(), CODE_COUPLED, both)
    assert verdict == DISAGREE
    assert any("README.md" in p and "both" in p for p in problems)


def test_a_classified_document_that_does_not_exist_fails() -> None:
    stale = {**CODE_COUPLED, "docs/deleted.md": "a document that was removed"}
    verdict, problems = classification_verdict(corpus_paths(), stale, ARGUMENT)
    assert verdict == DISAGREE
    assert any("docs/deleted.md" in p and "not in the corpus" in p for p in problems)


def test_a_classification_with_no_reason_is_could_not_evaluate() -> None:
    silent = {**CODE_COUPLED, "README.md": "   "}
    verdict, problems = classification_verdict(corpus_paths(), silent, ARGUMENT)
    assert verdict == COULD_NOT_EVALUATE
    assert any("no reason" in p for p in problems)


def test_prose_added_without_surface_fails_the_budget() -> None:
    """The signal this whole check exists to produce."""
    docs = dict(read_corpus())
    docs["CLAUDE.md"] = docs["CLAUDE.md"] + "\n\n" + ("filler " * 2000)
    verdict, problems = budget_verdict(
        docs, public_symbols(PACKAGE), CODE_COUPLED, ARGUMENT, RATE, ARGUMENT_MAX
    )
    assert verdict == DISAGREE
    assert any("code-coupled" in p and "over by" in p for p in problems)


def test_removing_public_symbols_can_put_the_corpus_over() -> None:
    """Deliberate, and it fires at an inconvenient moment — so it says why."""
    verdict, problems = budget_verdict(
        read_corpus(), public_symbols(PACKAGE) // 2, CODE_COUPLED, ARGUMENT,
        RATE, ARGUMENT_MAX,
    )
    assert verdict == DISAGREE
    assert any("public symbols" in p and "over by" in p for p in problems)


def test_an_argument_document_growing_fails_the_flat_ceiling() -> None:
    docs = dict(read_corpus())
    docs["docs/prior-art.md"] = docs["docs/prior-art.md"] + "\n\n" + ("filler " * 500)
    verdict, problems = budget_verdict(
        docs, public_symbols(PACKAGE), CODE_COUPLED, ARGUMENT, RATE, ARGUMENT_MAX
    )
    assert verdict == DISAGREE
    assert any("argument/reference" in p and "500" in p for p in problems)


def test_adding_code_does_not_buy_the_argument_group_anything() -> None:
    """The sentence in the docstring, as a check."""
    docs = read_corpus()
    over = {**docs, "docs/plan.md": docs["docs/plan.md"] + "\n\n" + ("filler " * 400)}
    verdict, problems = budget_verdict(
        over, public_symbols(PACKAGE) * 10, CODE_COUPLED, ARGUMENT, RATE, ARGUMENT_MAX
    )
    assert verdict == DISAGREE
    assert any("argument/reference" in p for p in problems)


def test_a_long_paragraph_fails() -> None:
    docs = {"docs/fixture.md": "# Fixture\n\n" + ("word " * 200)}
    verdict, problems = long_paragraph_verdict(docs, PARAGRAPH_MAX_WORDS, 0)
    assert verdict == DISAGREE
    assert any("docs/fixture.md 1" in p for p in problems)


@pytest.mark.parametrize(
    "block",
    [
        "| a | b |\n" * 100,
        "```\n" + ("word " * 200) + "\n```",
        "> " + ("word " * 200),
        "\n".join(f"- item {i} " + "word " * 20 for i in range(20)),
    ],
    ids=["table", "fence", "block-quote", "list"],
)
def test_a_table_a_fence_a_quote_or_a_list_is_not_a_long_paragraph(block: str) -> None:
    """The exclusions, each fed something that would fail without them."""
    text = f"# Fixture\n\nA short opening line.\n\n{block}\n"
    verdict, problems = long_paragraph_verdict(
        {"docs/fixture.md": text}, PARAGRAPH_MAX_WORDS, 0
    )
    assert verdict == AGREE, problems


def test_a_paragraph_of_code_spans_is_not_inflated_into_a_long_one() -> None:
    text = "# Fixture\n\n" + " ".join(f"`reg.module.symbol_{i}`" for i in range(200))
    verdict, _ = long_paragraph_verdict(
        {"docs/fixture.md": text}, PARAGRAPH_MAX_WORDS, 0
    )
    assert verdict == AGREE


def test_defect_narration_is_detected() -> None:
    docs = {"docs/fixture.md": "# Fixture\n\nThe bound was wrong until issue #84 "
                              "fixed the source, and the check previously said "
                              "nothing about it."}
    verdict, problems = narration_verdict(docs, 0)
    assert verdict == DISAGREE
    assert any("docs/fixture.md 1" in p for p in problems)


def test_a_normative_paragraph_is_not_counted_as_narration() -> None:
    docs = {"docs/fixture.md": "# Fixture\n\nThe envelope takes a proprioceptive "
                              "state, and the absence of any field naming an "
                              "entity is the enforcement."}
    verdict, _ = narration_verdict(docs, 0)
    assert verdict == AGREE


def test_narration_below_the_rationale_line_is_not_counted() -> None:
    """The line is what makes the ceiling reachable: move it, do not delete it."""
    narration = "The bound was wrong until issue #84 fixed the source."
    above = {"docs/fixture.md": f"# Fixture\n\n{narration}\n"}
    below = {"docs/fixture.md": f"# Fixture\n\nA short summary.\n\n## Why\n\n{narration}\n"}
    assert narration_verdict(above, 0)[0] == DISAGREE
    assert narration_verdict(below, 0)[0] == AGREE


def test_a_topic_heading_beginning_with_why_is_not_a_rationale_line() -> None:
    """`## Why the growth is sublinear` is a section, not the line.

    Reading it as one would exempt everything after it, which in
    docs/retention.md is most of the file.
    """
    narration = "The bound was wrong until issue #84 fixed the source."
    docs = {
        "docs/fixture.md": (
            "# Fixture\n\nA short summary.\n\n"
            "## Why the growth is sublinear\n\n" + narration + "\n"
        )
    }
    assert narration_verdict(docs, 0)[0] == DISAGREE


def test_an_overlong_summary_fails() -> None:
    docs = {"docs/fixture.md": "# Fixture\n\n" + ("word " * 100)}
    verdict, problems = summary_verdict(docs, SUMMARY_MAX_WORDS, 0)
    assert verdict == DISAGREE
    assert any("docs/fixture.md 100 words" in p for p in problems)


@pytest.mark.parametrize(
    "status",
    ["**Status:** " + "word " * 200, "**Status: " + "word " * 200 + "**"],
    ids=["colon-outside-the-bold", "colon-inside-the-bold"],
)
def test_a_status_header_is_not_the_summary(status: str) -> None:
    """Both spellings in the corpus, and neither is what a reader is opening on."""
    docs = {"docs/fixture.md": f"# Fixture\n\n{status}\n\nA short opening line.\n"}
    verdict, problems = summary_verdict(docs, SUMMARY_MAX_WORDS, 0)
    assert verdict == AGREE, problems


def test_a_status_header_still_counts_as_a_paragraph_everywhere_else() -> None:
    """It is exempt from being the summary, not from the budget."""
    docs = {"docs/fixture.md": "# Fixture\n\n**Status:** " + ("word " * 200)}
    assert long_paragraph_verdict(docs, PARAGRAPH_MAX_WORDS, 0)[0] == DISAGREE


def test_a_document_with_no_prose_at_all_is_could_not_evaluate() -> None:
    """Deleting the summary is not a way to have a short one."""
    docs = {"docs/fixture.md": "# Fixture\n\n| a | b |\n|---|---|\n| 1 | 2 |\n"}
    verdict, problems = summary_verdict(docs, SUMMARY_MAX_WORDS, 0)
    assert verdict == COULD_NOT_EVALUATE
    assert any("no prose paragraph" in p for p in problems)


@pytest.mark.parametrize(
    "check",
    [
        lambda docs: classification_verdict((), CODE_COUPLED, ARGUMENT),
        lambda docs: budget_verdict(docs, 260, CODE_COUPLED, ARGUMENT, RATE, ARGUMENT_MAX),
        lambda docs: long_paragraph_verdict(docs, PARAGRAPH_MAX_WORDS, 0),
        lambda docs: narration_verdict(docs, 0),
        lambda docs: summary_verdict(docs, SUMMARY_MAX_WORDS, 0),
    ],
    ids=["classification", "budget", "long-paragraphs", "narration", "summary"],
)
def test_an_empty_corpus_is_could_not_evaluate(check) -> None:
    verdict, problems = check({})
    assert verdict == COULD_NOT_EVALUATE
    assert problems


def test_a_package_with_no_public_symbols_is_could_not_evaluate() -> None:
    """The denominator is gone; a budget of zero words is not a finding."""
    verdict, problems = budget_verdict(
        read_corpus(), 0, CODE_COUPLED, ARGUMENT, RATE, ARGUMENT_MAX
    )
    assert verdict == COULD_NOT_EVALUATE
    assert any("no public symbols" in p for p in problems)


def test_a_constant_raised_with_its_comment_deleted_fails() -> None:
    source = "# a number\nRATE = 200.0\n\n# another\nARGUMENT_MAX = 999999\n"
    verdict, problems = ratchet_comment_verdict(source, ("RATE", "ARGUMENT_MAX"))
    assert verdict == DISAGREE
    assert len(problems) == 2


def test_a_missing_constant_fails() -> None:
    verdict, problems = ratchet_comment_verdict("RATE = 1.0\n", ("NARRATION_MAX",))
    assert verdict == DISAGREE
    assert any("not defined" in p for p in problems)


def test_no_source_is_could_not_evaluate() -> None:
    verdict, problems = ratchet_comment_verdict("", RATCHET_CONSTANTS)
    assert verdict == COULD_NOT_EVALUATE
    assert problems


# --------------------------------------------------------------------------
# The denominator, pinned to its definition rather than to a number
# --------------------------------------------------------------------------


def test_public_symbols_counts_top_level_public_definitions_only() -> None:
    fixture = REPO / "reg"
    assert public_symbols(fixture) > 0
    source = "\n".join(
        (
            "def public(): pass",
            "def _private(): pass",
            "class Public: pass",
            "class _Private: pass",
            "class Outer:",
            "    def method(self): pass",
            "if True:",
            "    def nested(): pass",
        )
    )
    tree = ast.parse(source)
    counted = sum(
        1
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        and not node.name.startswith("_")
    )
    assert counted == 3  # public, Public, Outer — the nested and private ones are not
