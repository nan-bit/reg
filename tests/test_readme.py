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
