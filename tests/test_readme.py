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
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
README = REPO / "README.md"
PLAN = REPO / "docs" / "plan.md"
LOSSINESS = REPO / "docs" / "lossiness.md"

# A retention size (`263 GB`) or a ratio (`694x`, `13x`). The tilde, the
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
    # 265 GB is deliberately not a figure this project publishes. It was 264 GB
    # here until issue #83 made 264 the real one, at which point this negative
    # test started asserting that a true figure was drift. A negative whose
    # fixture drifts into the truth stops testing anything, so the value has to
    # be one nothing can legitimately produce.
    verdict, missing = check(
        "the artifact is **265 GB** per robot for six months", PLAN.read_text()
    )
    assert verdict == DISAGREE
    assert missing == ["265 GB"]


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


def agree_about_acknowledgment(readme: str, lossiness: str) -> tuple[str, list[str]]:
    """Verdict on whether the two documents say the same thing about passivation.

    An acknowledgment is not stored, and `graph.build` refuses a run containing
    one (`tests/test_graph.py`). Both documents have to say so, and the front
    page's status word may not be a bare `landed` over a half nobody can
    exercise. A README with no Claim 4 row, or a lossiness file with no #7, is
    COULD-NOT-EVALUATE: this check is meaningless if it cannot find what it
    compares, and silence must not read as agreement.
    """
    row, clause = claim_4(readme), retained_7(lossiness)
    if row is None or clause is None:
        return COULD_NOT_EVALUATE, []

    disagreements = []
    if "acknowledg" not in row.lower():
        disagreements.append(
            "README.md's Claim 4 row does not mention the acknowledgment"
        )
    if "acknowledg" not in clause.lower():
        disagreements.append(
            "docs/lossiness.md Retained #7 does not mention the acknowledgment"
        )
    status = STATUS.search(row.split("|")[3]) if row.count("|") > 3 else None
    if status is not None and status.group(1).strip() == "landed":
        disagreements.append(
            "README.md's Claim 4 status is a bare `landed` over a half that is "
            "implemented only in reg/enforce.py"
        )
    return (DISAGREE if disagreements else AGREE), disagreements


def test_the_front_page_and_the_lossiness_contract_agree_about_passivation() -> None:
    verdict, disagreements = agree_about_acknowledgment(
        README.read_text(), LOSSINESS.read_text()
    )
    assert verdict == AGREE, (
        f"{disagreements}. Passivation and reintegration are implemented in "
        "reg/enforce.py and reach no artifact; graph.build refuses a run "
        "containing an Acknowledgment. Both documents state that gap, or issue "
        "#112 closed it and both should stop stating it — not one each."
    )


def test_a_bare_landed_on_claim_4_is_caught() -> None:
    """The negative test: the exact row this check was written against (#110)."""
    verdict, disagreements = agree_about_acknowledgment(
        "| **4** | **Attestation** | `landed` — the chain and the taxonomy |",
        LOSSINESS.read_text(),
    )
    assert verdict == DISAGREE
    assert any("bare `landed`" in d for d in disagreements)
    assert any("does not mention the acknowledgment" in d for d in disagreements)


def test_a_lossiness_clause_that_dropped_the_concession_is_caught() -> None:
    """The other direction: the artifact half lands in one document only."""
    verdict, disagreements = agree_about_acknowledgment(
        README.read_text(),
        "7. **The complete hash chain** — every link, unbroken.\n8. next\n",
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
    verdict, _ = agree_about_acknowledgment(readme, lossiness)
    assert verdict == COULD_NOT_EVALUATE
