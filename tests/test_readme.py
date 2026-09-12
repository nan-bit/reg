"""The front page restates measured figures, and restated figures go stale.

Issue #66: `README.md` spent two milestones saying Claim 1 was *not yet
measured* while `docs/plan.md` carried the measurement. Nothing failed, because
prose does not fail. This is the cheapest check that would have caught it: every
size and every ratio quoted on the front page must appear **verbatim** in
`docs/plan.md`, which is where those numbers are measured and published.

It catches drift in both directions. Re-measure the curve and leave the README
alone, and the README's old figure is no longer in `plan.md` — fail. Invent a
figure for the front page that was never measured — fail. It cannot check that
the *prose around* a figure is honest; a reviewer still has to do that.

The verdict is three-valued on purpose (docs/CONTRIBUTING.md, CLAUDE.md): a
README with no figures in it at all is COULD-NOT-EVALUATE, not a pass, because
silence is how a check of this shape would otherwise be defeated.

**The chain gained a second link on 2026-08-31**, when Claim 1's measurement
record was extracted into `docs/retention.md`. Containment against `plan.md`
alone stopped being enough that day: `plan.md` became a document that *restates*
figures measured elsewhere, so `README.md` ⊆ `plan.md` could hold while both
drifted away from the measurement together. That was demonstrated, not assumed —
setting both to `999 GB` while `retention.md` and `reg.bench` still said the
measured figure of the day left the whole suite green. So the second link closes it: **Claim 1's own figures must
appear in `docs/retention.md`**, the document that publishes them.

**What that does and does not buy, stated precisely, because the first version of
this paragraph overstated it.** It said `README ⊆ plan ⊆ retention == code`. The
last equality is false: `tests/test_published_figures.py` re-derives the
`bytes/hour` tables, `sufficiency.md`'s counts, the coarsest level's label, the
byte attribution and the Layer-A comparison — and of the figures Claim 1 quotes,
`267 GB`, `~684x`, `182.5 TB` and `1 TB` are still not re-derived by anything. So this chain keeps the three documents *consistent with
each other*, which is what stops the drift demonstrated above; it does not anchor
them to a measurement. The anchor is one table, and the totals are arithmetic
over it stated in prose.

Two further limits, so nobody reads more into a green run than is there:

* **It is containment, not attribution.** `check` asks whether the token appears
  anywhere in the target. Claim 1 could relabel the transition level's `656 GB`
  as the occurrence headline and pass, because the token exists in
  `retention.md`. For a section whose job is *restating* figures, mislabelling is
  the live failure mode and this does not catch it.
* **It sees eight tokens.** `FIGURE` matches sizes and ratios only, so `98.5%`,
  `3,120`, `3,166` and `50 Hz` — the composition condition the same section calls
  load-bearing — are outside it.

Scoped to Claim 1's section rather than the whole of `plan.md`, because the other
claims and the phases quote figures of their own that this record does not
publish and should not have to. Note the transitivity is not airtight either:
link 1 checks the README against the whole of `plan.md`, so a README figure
satisfied out of Phase 8 would never reach link 2. It holds today because all
seven README figures fall inside the Claim 1 span; that is a property of the
current text, not of the check.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
README = REPO / "README.md"
PLAN = REPO / "docs" / "plan.md"
RETENTION = REPO / "docs" / "retention.md"
LOSSINESS = REPO / "docs" / "lossiness.md"

# A retention size (`263 GB`) or a ratio (`694x`, `51x`). The tilde, the
# asterisks and the surrounding markdown are stripped before matching, so
# `**~694x**` and `~694x smaller` normalise to the same token.
FIGURE = re.compile(r"(?<![\d.])(\d[\d,]*(?:\.\d+)?)\s*(MB|GB|TB|PB|x)\b")

AGREE = "AGREE"
DISAGREE = "DISAGREE"
COULD_NOT_EVALUATE = "COULD-NOT-EVALUATE"


def normalise(text: str) -> str:
    """Strip the markdown emphasis and collapse whitespace, nothing else."""
    return re.sub(r"\s+", " ", re.sub(r"[*_`~]", "", text))


def figures(text: str) -> list[str]:
    """Every size and ratio quoted in `text`, normalised to `263 GB` / `694x`."""
    out = []
    for number, unit in FIGURE.findall(normalise(text)):
        out.append(f"{number}{unit}" if unit == "x" else f"{number} {unit}")
    return out


def check(readme: str, plan: str) -> tuple[str, list[str]]:
    """Verdict on whether the README's figures are the plan's figures.

    Returns the verdict and the figures that are not in the plan. A README with
    no figures, or a plan that could not be read, is COULD-NOT-EVALUATE — this
    check is only meaningful when there is something to compare.
    """
    quoted = figures(readme)
    if not quoted or not plan.strip():
        return COULD_NOT_EVALUATE, []
    published = normalise(plan)
    missing = [f for f in quoted if f not in published]
    return (DISAGREE if missing else AGREE), missing


def test_every_figure_on_the_front_page_is_published_in_the_plan() -> None:
    verdict, missing = check(README.read_text(), PLAN.read_text())
    assert verdict == AGREE, (
        f"README.md quotes {missing}, which docs/plan.md does not publish. "
        "Either the plan was re-measured and the front page was not updated, "
        "or the front page is quoting a number nobody measured. Quote the "
        "plan's figures verbatim; do not re-derive or round them."
    )


def claim_1(plan: str) -> str:
    """`docs/plan.md`'s Claim 1 section, or `""` if it cannot be located.

    Bounded by the next `###` heading, so it stops at Claim 2. Claim 1 has no
    `###` subsections today; if it gained one the match would end there, which
    would silently narrow this check — so a subsection under Claim 1 is a reason
    to revisit this function, not a free addition. The empty string is the
    COULD-NOT-EVALUATE input below: a plan whose Claim 1 cannot be found has not
    satisfied this check, and deleting the heading is not a way to pass it.
    """
    match = re.search(
        r"^###\s+Claim 1\b.*?(?=^###\s|\Z)", plan, re.MULTILINE | re.DOTALL
    )
    return match.group(0) if match else ""


def test_every_figure_claim_1_quotes_is_published_in_the_retention_record() -> None:
    """**The second link in the chain.** See the module docstring.

    `plan.md` Claim 1 restates figures it does not measure. Without this, it and
    `README.md` can drift away from `retention.md` together and stay green.
    """
    section = claim_1(PLAN.read_text())
    assert section.strip(), (
        "docs/plan.md has no `### Claim 1` section, so the figures it quotes "
        "cannot be checked against the record that measures them. That is a "
        "could-not-evaluate, not a pass."
    )
    verdict, missing = check(section, RETENTION.read_text())
    assert verdict == AGREE, (
        f"docs/plan.md Claim 1 quotes {missing}, which docs/retention.md does "
        "not publish. Claim 1 restates figures; retention.md measures them and "
        "tests/test_published_figures.py pins its tables against the code. A "
        "figure here that is not there is one nothing re-derives."
    )


def test_a_plan_figure_absent_from_the_record_is_caught() -> None:
    """**The negative.** The exact drift this was added for: a Claim 1 that has
    been left behind by a re-measurement."""
    verdict, missing = check(
        "### Claim 1 — Retention\n\nThe artifact costs **999 GB** per robot.\n",
        RETENTION.read_text(),
    )
    assert verdict == DISAGREE
    assert missing == ["999 GB"]


def test_a_claim_1_that_cannot_be_located_is_not_a_pass() -> None:
    """Deleting the heading must not be a way to satisfy the check."""
    assert claim_1("# A plan\n\nNo claims here.\n") == ""


# ==========================================================================
# THE DOCS INDEX QUOTES A FIGURE TOO, AND NOTHING HELD IT (issue #217)
#
# `docs/README.md` names `267 GB` where it tells a reader which of this
# repository's figures are re-derived and which are arithmetic in prose. Issue
# #217 cut the entry points by mutation rather than by a green run, and this is
# what that method found: setting that figure to `999 GB` left the whole suite
# green. It is a Claim 1 figure restated on a second index page, which is the
# same shape as the drift `plan.md` was pinned for on 2026-08-31 — one document
# restating a measurement, with the measurement free to move underneath it.
#
# So it gets the same link the front page has, against the same target:
# `retention.md`, the document that publishes Claim 1's figures. Containment,
# with the limits the module docstring already states — it says the two
# documents agree, not that either is anchored to a measurement.
# ==========================================================================

DOCS_INDEX = REPO / "docs" / "README.md"


def test_every_figure_the_docs_index_quotes_is_published_in_the_record() -> None:
    verdict, missing = check(DOCS_INDEX.read_text(), RETENTION.read_text())
    assert verdict == AGREE, (
        f"docs/README.md quotes {missing}, which docs/retention.md does not "
        "publish. The index restates Claim 1's figures to say which of them are "
        "machine-checked; a figure here that is not there is one the sentence "
        "about checking is wrong about."
    )


def test_the_docs_index_still_quotes_a_figure() -> None:
    """**SILENCE IS NOT A PASS.** `check` returns COULD-NOT-EVALUATE on a
    document with no figures in it, so deleting the number is otherwise the way
    to satisfy the test above — and the number is the whole point of the
    sentence it sits in, which is about what is and is not re-derived."""
    assert figures(DOCS_INDEX.read_text()), (
        "docs/README.md quotes no figure at all. Its *To check a number* entry "
        "names a derived total to show what the pin does not cover; without one "
        "the entry has nothing to be concrete about."
    )


def test_a_drifted_figure_in_the_docs_index_is_caught() -> None:
    """**The negative**, and it is the mutation issue #217 ran: the index's own
    sentence with the figure moved to one no measurement of this artifact
    reaches. Before this check it was green."""
    verdict, missing = check(
        "The six-month totals computed from them — `999 GB` among them — are "
        "**not** re-derived.",
        RETENTION.read_text(),
    )
    assert verdict == DISAGREE
    assert missing == ["999 GB"]


def test_the_front_page_still_quotes_a_retention_size_and_a_ratio() -> None:
    """The check above passes trivially on a README with the numbers removed."""
    quoted = figures(README.read_text())
    assert any(f.endswith((" GB", " TB", " PB")) for f in quoted), (
        "README.md quotes no retention size. Claim 1 is measured; the front "
        "page said otherwise for two milestones (issue #66)."
    )
    assert any(f.endswith("x") for f in quoted), (
        "README.md quotes no compression ratio."
    )


def test_a_drifted_figure_is_caught() -> None:
    """The negative test: feed it the condition it guards against."""
    # 999 GB is deliberately not a figure this project publishes, and it is the
    # third value this fixture has held: 264 GB until issue #83 made 264 real,
    # then 265 GB until issue #166 made 265 real. A negative whose fixture drifts
    # into the truth stops testing anything, so the value is now one no
    # measurement of this artifact can reach rather than the next size up —
    # `test_a_plan_figure_absent_from_the_record_is_caught` uses the same 999 GB
    # for the same reason. The assertion below fails loudly if it ever lands in a
    # document, because then `missing` comes back empty.
    verdict, missing = check(
        "the artifact is **999 GB** per robot for six months", PLAN.read_text()
    )
    assert verdict == DISAGREE
    assert missing == ["999 GB"]


def test_a_drifted_ratio_is_caught() -> None:
    verdict, missing = check("**~695x** smaller", PLAN.read_text())
    assert verdict == DISAGREE
    assert missing == ["695x"]


@pytest.mark.parametrize(
    ("readme", "plan"),
    [
        ("no figures on this page at all", "263 GB"),
        ("the artifact is 263 GB per robot", ""),
    ],
)
def test_nothing_to_compare_is_not_a_pass(readme: str, plan: str) -> None:
    """Silence and an empty document are could-not-evaluate, never AGREE."""
    verdict, _ = check(readme, plan)
    assert verdict == COULD_NOT_EVALUATE


# ==========================================================================
# The claim statuses restate what the code can do, and those go stale too.
#
# Issue #110: `README.md` said Claim 4 was `landed` while passivation and
# reintegration existed only in `reg/enforce.py` and reached no artifact, and
# `docs/lossiness.md` *Retained* #7 conceded exactly that gap. Two documents,
# one repository, opposite claims, and nothing failed. This is the same shape of
# check as the one above: the front page may not be more confident than the
# lossiness contract about what the artifact holds.
#
# ISSUE #247 CLOSED THAT GAP, AND THE CHECK IS NOT DELETED WITH IT. The first
# version of this check asserted the gap: both documents had to state that an
# acknowledgment is not stored, and a bare `landed` on Claim 4 was the failure.
# Written that way it would now have to be deleted to go green, and deleting a
# check because the fact it pinned changed is how the next drift goes unnoticed.
#
# So the fact is read off the **code** instead of written into this module, and
# the check is that both documents agree with it. `reg.store.EDGE_SPECS` holding
# `ACKNOWLEDGED` and `reg.query.QUERIES` holding `acknowledgments` is what "the
# artifact can be asked" means, and either side missing is a
# could-not-evaluate rather than a licence to read the documents freely. It now
# fails in both directions: a document still conceding the old gap after the
# schema grew a table for the record, and — if the record ever stopped reaching
# the artifact — a front page still claiming it does.
# ==========================================================================

#: The Claim 4 row of the README's claims table. Anchored on the row's number
#: cell, which `README.md` states is an identifier and does not move.
CLAIM_4_ROW = re.compile(r"^\|\s*\*\*4\*\*\s*\|.*$", re.M)

#: *Retained* #7, the hash-chain clause, up to the start of #8.
RETAINED_7 = re.compile(r"^7\. \*\*The complete hash chain\*\*.*?(?=^8\. )", re.M | re.S)

#: The status word, the first backticked token of the row's third cell.
STATUS = re.compile(r"`([^`]+)`")


def claim_4(readme: str) -> str | None:
    """The Claim 4 row, or `None` if the table no longer has one."""
    found = CLAIM_4_ROW.search(readme)
    return found.group(0) if found else None


def retained_7(lossiness: str) -> str | None:
    """The *Retained* #7 clause, or `None` if it has been renumbered away."""
    found = RETAINED_7.search(lossiness)
    return found.group(0) if found else None


#: Phrases that concede the pre-#247 gap. A document carrying one is claiming
#: the artifact cannot be asked whether a passivation was acknowledged, whatever
#: else it says around it, so they are what the check reads rather than a
#: sentiment nobody can evaluate.
GAP_PHRASES: tuple[str, ...] = (
    "cannot be asked",
    "no artifact answers",
    "is not stored",
    "reaches no table",
    "not exercisable",
)


def artifact_holds_the_acknowledgment() -> bool | None:
    """Whether the artifact can be asked, read off the code. `None` = unreadable.

    Two halves and both are required: a place to store the record
    (`reg.store.EDGE_SPECS`) and a question to ask of it (`reg.query.QUERIES`).
    One without the other is a structural claim rather than an answer, which is
    the specific defect issue #247 exists to close. `None` on an import error is
    a could-not-evaluate — the documents are not read against a fact nobody
    could establish.
    """
    try:
        from reg import query, store
    except Exception:  # pragma: no cover - an unimportable package fails louder
        return None
    return "ACKNOWLEDGED" in store.EDGE_SPECS and "acknowledgments" in query.QUERIES


def agree_about_acknowledgment(
    readme: str, lossiness: str, holds: bool | None
) -> tuple[str, list[str]]:
    """Verdict on whether the two documents say what the code does about
    passivation.

    `holds` is `artifact_holds_the_acknowledgment()`, passed in so the negative
    tests can pin both directions. A README with no Claim 4 row, a lossiness file
    with no #7, or a `holds` of `None` is COULD-NOT-EVALUATE: this check is
    meaningless if it cannot find what it compares, and silence must not read as
    agreement.
    """
    row, clause = claim_4(readme), retained_7(lossiness)
    if row is None or clause is None or holds is None:
        return COULD_NOT_EVALUATE, []

    disagreements = []
    for name, text in (("README.md's Claim 4 row", row), ("docs/lossiness.md Retained #7", clause)):
        if "acknowledg" not in text.lower():
            disagreements.append(f"{name} does not mention the acknowledgment")
            continue
        conceded = [phrase for phrase in GAP_PHRASES if phrase in text.lower()]
        if holds and conceded:
            disagreements.append(
                f"{name} still concedes the pre-#247 gap ({conceded}) while the "
                "artifact holds the record and reg.query can be asked about it"
            )
        if not holds and not conceded:
            disagreements.append(
                f"{name} does not state the gap, and nothing in the code stores "
                "an acknowledgment or answers a question about one"
            )
    status = STATUS.search(row.split("|")[3]) if row.count("|") > 3 else None
    if not holds and status is not None and status.group(1).strip() == "landed":
        disagreements.append(
            "README.md's Claim 4 status is a bare `landed` over a half that is "
            "implemented only in reg/enforce.py"
        )
    return (DISAGREE if disagreements else AGREE), disagreements


def test_the_front_page_and_the_lossiness_contract_agree_about_passivation() -> None:
    holds = artifact_holds_the_acknowledgment()
    assert holds is not None, (
        "reg.store or reg.query could not be imported, so what the two documents "
        "are checked against could not be established. That is a "
        "could-not-evaluate for this check, not a pass for either document."
    )
    verdict, disagreements = agree_about_acknowledgment(
        README.read_text(), LOSSINESS.read_text(), holds
    )
    assert verdict == AGREE, (
        f"{disagreements}. The artifact "
        f"{'holds' if holds else 'does not hold'} the acknowledgment "
        "(reg.store.EDGE_SPECS, reg.query.QUERIES), and both documents say so or "
        "both state the gap — not one each."
    )


def test_the_code_is_what_the_documents_are_checked_against() -> None:
    """Issue #247's own precondition, asserted rather than assumed.

    The check above is only worth its message while both halves are really
    there. A schema that grew the edge and a query module that never gained the
    question would make it read the documents against a structural claim.
    """
    from reg import query, store

    assert store.EDGE_SPECS["ACKNOWLEDGED"].layer == "A"
    assert query.QUERIES["acknowledgments"].arguments == ()
    assert artifact_holds_the_acknowledgment() is True


def test_a_document_still_conceding_the_closed_gap_is_caught() -> None:
    """THE NEGATIVE, in the direction issue #247 created.

    The front page as it read before this issue, against a build that holds the
    record: the row is not wrong about the acknowledgment existing, it is wrong
    about what the artifact can be asked, and the phrase is what says so.
    """
    verdict, disagreements = agree_about_acknowledgment(
        '| **4** | **Attestation** | `landed, minus the passivation half` — '
        '"was the passivation acknowledged" is a question this artifact '
        "cannot be asked |",
        LOSSINESS.read_text(),
        holds=True,
    )
    assert verdict == DISAGREE
    assert any("still concedes" in d for d in disagreements)


def test_a_bare_landed_on_claim_4_is_caught() -> None:
    """The negative test in the other direction: the exact row this check was
    written against (#110), against a build with no acknowledgment in it."""
    verdict, disagreements = agree_about_acknowledgment(
        "| **4** | **Attestation** | `landed` — the chain and the taxonomy |",
        LOSSINESS.read_text(),
        holds=False,
    )
    assert verdict == DISAGREE
    assert any("bare `landed`" in d for d in disagreements)
    assert any("does not mention the acknowledgment" in d for d in disagreements)


def test_an_unreadable_code_side_is_not_a_pass() -> None:
    """COULD-NOT-EVALUATE, and it does not resolve to AGREE."""
    verdict, disagreements = agree_about_acknowledgment(
        README.read_text(), LOSSINESS.read_text(), holds=None
    )
    assert verdict == COULD_NOT_EVALUATE
    assert disagreements == []


def test_a_lossiness_clause_that_dropped_the_concession_is_caught() -> None:
    """The other direction: the artifact half lands in one document only."""
    verdict, disagreements = agree_about_acknowledgment(
        README.read_text(),
        "7. **The complete hash chain** — every link, unbroken.\n8. next\n",
        holds=True,
    )
    assert verdict == DISAGREE
    assert disagreements == [
        "docs/lossiness.md Retained #7 does not mention the acknowledgment"
    ]


@pytest.mark.parametrize(
    ("readme", "lossiness"),
    [
        ("a front page with no claims table", "7. **The complete hash chain**\n8. x\n"),
        ("| **4** | x | `landed, minus the acknowledgment` |", "no retained list here"),
    ],
)
def test_a_missing_claim_row_or_clause_is_not_a_pass(readme: str, lossiness: str) -> None:
    """Silence is could-not-evaluate. A renamed heading must not read as AGREE."""
    verdict, _ = agree_about_acknowledgment(readme, lossiness, holds=True)
    assert verdict == COULD_NOT_EVALUATE


# ==========================================================================
# THE DEMO ON THE FRONT PAGE MUST RUN (issue #271)
#
# `reg.graph build` has required `--worker-notice`, `--dpia-reference` and
# `--operator-id-kind` since #125, and both of the README's builds omitted
# them. The page had been telling readers to run a command that exits 2 and
# writes no artifact, and nothing in the suite noticed, because nothing in the
# suite ran it. Prose does not fail; a command does.
#
# So the commands are **extracted from `README.md`** rather than copied here.
# A copy is what went stale in `docs/plan.md` Phase 5, whose deliverable is now
# a pointer at this section for that reason. Two adaptations, and they are the
# only ones:
#
#   * `python` becomes `sys.executable`, because the interpreter running the
#     suite is the one the demo must work under;
#   * `PYTHONPATH` names the repository, so the demo exercises this working
#     tree rather than whatever `reg` happens to be installed.
#
# **What a command is expected to exit with is the README's own statement of
# it** — a trailing `# exit N` comment, which the page already carried on the
# tampered query. Absent one, the command must succeed. That keeps the
# expectation on the page a reader follows rather than in a table only this
# file holds.
#
# THE COST: the two builds are ~5 minutes each on the machine this was written
# on, so this module roughly triples the wall-clock of `pytest`. That is the
# price of the front page being executable, and it is paid once per suite —
# the demo runs in a single module-scoped directory, in the order the page
# gives, because the *Committing the chain heads* build reuses the `dv.csv`
# and `keyring.json` the first block wrote.
# ==========================================================================

import os
import shlex
import subprocess
import sys
from typing import NamedTuple

#: The headings whose fenced `bash` blocks are the demo, in the order the page
#: runs them. Nothing else on the page is executed: `## How to run` would
#: install the package and re-enter `pytest`, and `## How work happens` would
#: label a GitHub issue.
DEMO_SECTIONS: tuple[str, ...] = ("Reading an incident", "Committing the chain heads")

HEADING = re.compile(r"^#{1,6} +(.*?)\s*$", re.M)
FENCED = re.compile(r"^```([a-z]*)\n(.*?)^```", re.M | re.S)
EXIT_ANNOTATION = re.compile(r"\s+#\s*exit\s+(\d+)\s*$")

#: The README's abridgement marker. A line that is only this stands for lines
#: elided wholesale; a line ending in it is shown with its tail cut off.
ELISION = "…"


class Command(NamedTuple):
    """A shell command from the page, and what the page says it exits with."""

    text: str
    expected_exit: int


def section(markdown: str, heading: str) -> str:
    """The body under `heading`, to the next heading of any level.

    `""` when the heading is not there — which is COULD-NOT-EVALUATE at every
    call site below, never a pass. Renaming a section must not be a way to stop
    running it.
    """
    for match in HEADING.finditer(markdown):
        if match.group(1).strip() == heading:
            following = HEADING.search(markdown, match.end())
            return markdown[match.end() : following.start() if following else len(markdown)]
    return ""


def fenced(text: str, language: str) -> list[str]:
    """The bodies of the fenced blocks tagged `language`, in order.

    `""` is the untagged fence, which on this page is shown output.
    """
    return [body for tag, body in FENCED.findall(text) if tag == language]


def commands(block: str) -> list[Command]:
    """One `Command` per shell command in `block`, continuations joined."""
    found: list[Command] = []
    pending = ""
    for line in block.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.endswith("\\"):
            pending += stripped[:-1].rstrip() + " "
            continue
        text = pending + stripped
        pending = ""
        annotation = EXIT_ANNOTATION.search(text)
        found.append(
            Command(
                EXIT_ANNOTATION.sub("", text),
                int(annotation.group(1)) if annotation else 0,
            )
        )
    if pending.strip():
        # A block whose last line is a continuation is malformed markdown. Keep
        # it rather than dropping it, so the run reports the mess instead of
        # quietly executing one command fewer than the page shows.
        found.append(Command(pending.strip(), 0))
    return found


def run(cmds: list[Command], cwd) -> list[subprocess.CompletedProcess]:
    """Run `cmds` in order in `cwd`, with the two adaptations named above."""
    env = dict(os.environ, PYTHONPATH=str(REPO))
    results = []
    for cmd in cmds:
        argv = shlex.split(cmd.text)
        if argv and argv[0] == "python":
            argv[0] = sys.executable
        results.append(
            subprocess.run(argv, cwd=str(cwd), env=env, capture_output=True, text=True)
        )
    return results


def exit_verdict(
    cmds: list[Command], results: list[subprocess.CompletedProcess]
) -> tuple[str, list[str]]:
    """Did each command exit with what the page says it does?

    No commands, or a result per command missing, is COULD-NOT-EVALUATE: an
    empty block is how a check of this shape is otherwise defeated, and it must
    not read as a page whose demo runs.
    """
    if not cmds or len(cmds) != len(results):
        return COULD_NOT_EVALUATE, []
    problems = [
        f"`{cmd.text}` exited {result.returncode}, not {cmd.expected_exit}"
        f"{(': ' + result.stderr.strip().splitlines()[-1]) if result.stderr.strip() else ''}"
        for cmd, result in zip(cmds, results)
        if result.returncode != cmd.expected_exit
    ]
    return (DISAGREE if problems else AGREE), problems


def output_verdict(shown: str, printed: str) -> tuple[str, list[str]]:
    """Does `printed` carry every line the README shows?

    A line that is only `…` stands for lines elided wholesale and is skipped. A
    line ending in `…` is checked as a prefix, because the page cut its tail.
    Every other line must appear verbatim — which is what makes the envelope
    hashes, the record count and the *51 of 51* count checked rather than
    decorative. Key material is generated fresh on every run, so no MAC and no
    chain head is among the lines the page shows.

    An empty block, or no output, is COULD-NOT-EVALUATE. Deleting the shown
    output is not a way to satisfy this.
    """
    if not shown.strip() or not printed.strip():
        return COULD_NOT_EVALUATE, []
    actual = [line.rstrip() for line in printed.splitlines()]
    missing = []
    for raw in shown.splitlines():
        line = raw.rstrip()
        if not line.strip() or line.strip() == ELISION:
            continue
        if line.endswith(ELISION):
            if not any(out.startswith(line[: -len(ELISION)].rstrip()) for out in actual):
                missing.append(line)
        elif line not in actual:
            missing.append(line)
    return (DISAGREE if missing else AGREE), missing


def demo_blocks(readme: str) -> list[tuple[str, list[Command]]]:
    """Every demo block on the page, as `(heading, commands)`, in page order."""
    return [
        (heading, commands(block))
        for heading in DEMO_SECTIONS
        for block in fenced(section(readme, heading), "bash")
    ]


@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    """The whole demo, run once, in one directory, in the order the page gives.

    Module-scoped because the two builds take minutes each. The second section
    reuses the first section's `dv.csv` and `keyring.json`, so the shared
    directory is the page's own arrangement rather than a shortcut.
    """
    readme = README.read_text()
    cwd = tmp_path_factory.mktemp("readme-demo")
    return [(heading, cmds, run(cmds, cwd)) for heading, cmds in demo_blocks(readme)]


def test_the_front_page_still_carries_a_demo_to_run() -> None:
    """**SILENCE IS NOT A PASS.** Every check below is vacuous on a page whose
    demo blocks have been renamed, retagged or deleted."""
    blocks = demo_blocks(README.read_text())
    assert len(blocks) == 3, (
        f"README.md's {DEMO_SECTIONS} hold {len(blocks)} fenced bash blocks, "
        "not the three the demo is made of. A section renamed or a fence "
        "retagged silently stops the demo being run at all."
    )
    texts = [cmd.text for _, cmds in blocks for cmd in cmds]
    assert any("reg.graph build" in text for text in texts), (
        "no `reg.graph build` among the extracted commands — the build is what "
        "issue #271 exists to keep runnable."
    )
    assert not any(
        text.startswith(("pip ", "pytest", "gh ", "journalctl")) for text in texts
    ), (
        f"{texts} reaches outside the demo: `## How to run` installs the "
        "package and re-enters pytest, and `## How work happens` labels a "
        "GitHub issue. Neither belongs in a demo run."
    )


def test_every_command_in_the_demo_exits_as_the_front_page_says(demo) -> None:
    """The acceptance criterion of issue #271: both builds run **as written**."""
    for heading, cmds, results in demo:
        verdict, problems = exit_verdict(cmds, results)
        assert verdict == AGREE, (
            f"README.md's *{heading}* does not run as written: {problems}. The "
            "page is the instruction a reader follows; a command on it that "
            "exits differently is a defect in the page, not in this test."
        )


def test_the_incident_report_the_front_page_shows_is_what_it_prints(demo) -> None:
    """The second criterion: the printed output still matches the page.

    The block compared is the untagged fence under *Reading an incident*, and
    the output is the last command of that section's first block — the incident
    query.
    """
    shown = fenced(section(README.read_text(), "Reading an incident"), "")
    assert shown, (
        "README.md's *Reading an incident* shows no output block, so there is "
        "nothing to hold the demo's output against. That is a "
        "could-not-evaluate, not a pass."
    )
    verdict, missing = output_verdict(shown[0], demo[0][2][-1].stdout)
    assert verdict == AGREE, (
        f"the incident report on README.md shows {missing}, which the command "
        "beside it does not print. Either the report drifted from the code or "
        "the page was never updated; paste what it prints."
    )


def test_a_demo_build_without_the_disclosure_flags_is_caught(tmp_path) -> None:
    """**THE NEGATIVE**, and it is the exact state of the page before this
    issue: the build as it read between #125 and now.

    Only the build is run — it refuses at argument parsing, before it reads
    `dv.csv` or the keyring, so neither has to exist for this to say no.
    """
    block = fenced(section(README.read_text(), "Reading an incident"), "bash")[0]
    without = re.sub(r"\s*\\\n\s*--worker-notice\b[^\n]*", "", block)
    assert "--worker-notice" not in without, (
        "the flags could not be stripped from the README's build command, so "
        "this negative did not test what it claims to. Its pattern tracks the "
        "line the flags sit on and has to move with it."
    )
    cmds = [cmd for cmd in commands(without) if "reg.graph build" in cmd.text]
    assert cmds, "no build command survived the strip"
    results = run(cmds, tmp_path)
    verdict, problems = exit_verdict(cmds, results)
    assert verdict == DISAGREE, (
        "a build with --worker-notice, --dpia-reference and --operator-id-kind "
        "removed was reported as running. This check cannot say no, so its "
        "green run above establishes nothing."
    )
    assert any("exited 2" in problem for problem in problems)
    assert any("--worker-notice" in result.stderr for result in results)


def test_an_output_line_the_demo_does_not_print_is_caught(demo) -> None:
    """The negative for the output half: a page whose report drifted.

    `51 of 51` moved to a count the run cannot reach, in the line the issue
    names, and the abridged tail left in place so the prefix rule is what is
    being exercised.
    """
    verdict, missing = output_verdict(
        "note:       2 declaration(s) in force at t=3.5; 999 of 999 "
        "adjudication(s) in [3.0, 4.0] were not permitted …\n",
        demo[0][2][-1].stdout,
    )
    assert verdict == DISAGREE
    assert missing and "999 of 999" in missing[0]


@pytest.mark.parametrize(
    ("shown", "printed"),
    [
        ("", "incident report: t=3.5000 s\n"),
        ("incident report: t=3.5000 s\n", ""),
    ],
)
def test_nothing_to_compare_in_the_demo_output_is_not_a_pass(
    shown: str, printed: str
) -> None:
    """An empty block and a command that printed nothing are both
    COULD-NOT-EVALUATE, and neither resolves to AGREE."""
    verdict, _ = output_verdict(shown, printed)
    assert verdict == COULD_NOT_EVALUATE


def test_a_renamed_demo_section_is_not_a_pass() -> None:
    """`section` returns `""` for a heading that is gone, and an empty section
    yields no commands — which `exit_verdict` reports as could-not-evaluate
    rather than as a demo that ran."""
    assert section("# A page\n\nNo demo here.\n", "Reading an incident") == ""
    assert commands("") == []
    verdict, problems = exit_verdict([], [])
    assert verdict == COULD_NOT_EVALUATE
    assert problems == []


def test_the_page_states_what_a_command_exits_with_rather_than_this_file() -> None:
    """The expectation is read off the page, both branches.

    The tampered query exits 3 by design and the README says so in the comment
    beside it. If that annotation were ever dropped, the command would be held
    to 0 and the demo would fail loudly — which is the intended direction: the
    page has to state it.
    """
    assert commands("python -m reg.query x --incident 1  # exit 3\n") == [
        Command("python -m reg.query x --incident 1", 3)
    ]
    assert commands("python -m reg.sim --out a.csv\n") == [
        Command("python -m reg.sim --out a.csv", 0)
    ]
    tamper = [
        cmd
        for _, cmds in demo_blocks(README.read_text())
        for cmd in cmds
        if "--tamper" in cmd.text or "tampered.sqlite" in cmd.text
    ]
    assert tamper and all(cmd.expected_exit == 3 for cmd in tamper), (
        f"{tamper}: the tamper demonstration must say on the page what it "
        "exits with. A tampered artifact that reported success would otherwise "
        "read as a demo that ran."
    )


def test_a_continuation_line_joins_into_one_command() -> None:
    """The builds are three and four lines long on the page; run as four
    commands they would each be nonsense, and `--out` would go missing."""
    assert commands("python -m reg.graph build a.csv \\\n    --out a.sqlite\n") == [
        Command("python -m reg.graph build a.csv --out a.sqlite", 0)
    ]
