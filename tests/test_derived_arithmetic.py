"""The sensitivity table is arithmetic over a pinned figure, and nothing checked it.

WHAT WAS MISSING
----------------
`tests/test_published_figures.py` pins every *published* figure to what the code
measures, in both directions. It is structurally blind to a second class of
number: one **derived** from a published figure by arithmetic inside a document.
`docs/sensor-baseline.md`'s sensitivity table is exactly that — each cell is a
sensor-log size divided by a retention size — so when the occurrence figure was
republished from 263 GB to 264 GB the bold row and the column header were
updated and three rows underneath were not. `14,780x` only reproduces from the
superseded 263 GB; against the 264 GB published then it was `14,724x`. The figure
pin was green throughout, because no published figure had moved.

The sizes moved again in issue #166, which put the base pose on the
`robot_config` row: 264 -> 265, 656 -> 658 and 953 -> 955 GB. **The two negatives
below quote cells of the live table, so they move with it** — a fixture naming a
row the table no longer has is a `replace` that does nothing, and a negative that
mutates nothing asserts nothing. Each now says so itself rather than leaving that
to be noticed.

Found by an external technical review, on a branch that never landed; this is
that fix carried onto `main` with the check that would have caught it.

WHAT THIS ASSERTS
-----------------
There is no constant here either. The retention sizes come out of the table's own
column headers, the retention window comes out of the row the document marks as
published, and every ratio is recomputed from those. So the check fails in both
directions: a republished size that leaves a row behind fails it, and a row
edited to something the arithmetic does not produce fails it too.

`round` is the tie-break, matching the table's own presentation, and the
derivation runs from the **rate** rather than from the rounded `log at 6 months`
column, because deriving from a displayed rounding compounds it — 91.25 TB is
346x and the displayed 91.2 TB is 345x, and the table says 346x.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

BASELINE = Path(__file__).resolve().parents[1] / "docs" / "sensor-baseline.md"

#: The sensitivity table's header, which names the size each column divides by.
_HEADER = re.compile(
    r"\|\s*sensor rate\s*\|\s*log at 6 months\s*\|(?P<cols>.+?)\|\s*\n", re.IGNORECASE
)
_COL_SIZE = re.compile(r"vs\s+[\w-]+\s+\((?P<gb>[\d,]+)\s*GB\)")
#: A data row: rate, log size, then one ratio per column.
_ROW = re.compile(
    r"^\|\s*\**(?P<rate>[\d.]+)\s*TB/day[^|]*\|\s*\**[\d,.]+\s*TB\**\s*\|"
    r"(?P<ratios>(?:\s*\**[\d,]+x\**\s*\|)+)\s*$",
    re.MULTILINE,
)


def _int(text: str) -> int:
    return int(text.replace(",", "").replace("x", "").replace("*", "").strip())


def parse_table(markdown: str) -> tuple[list[int], list[tuple[float, list[int]]]]:
    """The column sizes in GB, and each row as (rate TB/day, published ratios).

    Raises rather than returning empty: a table this cannot find is a
    could-not-evaluate, and a could-not-evaluate must not read as a pass.
    """
    header = _HEADER.search(markdown)
    if header is None:
        raise AssertionError("no sensitivity table header in docs/sensor-baseline.md")
    sizes = [_int(m.group("gb")) for m in _COL_SIZE.finditer(header.group("cols"))]
    if not sizes:
        raise AssertionError("sensitivity table header names no retention sizes")

    rows: list[tuple[float, list[int]]] = []
    for m in _ROW.finditer(markdown[header.end() :]):
        ratios = [_int(cell) for cell in m.group("ratios").split("|") if cell.strip()]
        if len(ratios) != len(sizes):
            raise AssertionError(
                f"row {m.group('rate')} TB/day has {len(ratios)} ratios "
                f"against {len(sizes)} columns"
            )
        rows.append((float(m.group("rate")), ratios))
    if not rows:
        raise AssertionError("sensitivity table has no data rows")
    return sizes, rows


def window_days(rows: list[tuple[float, list[int]]], markdown: str) -> float:
    """The retention window, read off the row the document marks as published.

    At 1 TB/day the `log at 6 months` column *is* the window in days, which is
    why the constant does not have to be written down here.
    """
    m = re.search(r"\|\s*\*\*1 TB/day \(published\)\*\*\s*\|\s*\*\*([\d.]+)\s*TB", markdown)
    if m is None:
        raise AssertionError("no published 1 TB/day row to read the window from")
    return float(m.group(1))


def divergences() -> list[str]:
    text = BASELINE.read_text()
    sizes, rows = parse_table(text)
    days = window_days(rows, text)
    out: list[str] = []
    for rate, published in rows:
        log_gb = rate * days * 1000
        for size_gb, got in zip(sizes, published):
            want = round(log_gb / size_gb)
            if want != got:
                out.append(
                    f"{rate} TB/day vs {size_gb} GB: document says {got:,}x, "
                    f"{log_gb:,.0f} GB / {size_gb} GB is {want:,}x"
                )
    return out


def test_every_sensitivity_ratio_reproduces_from_the_published_sizes() -> None:
    bad = divergences()
    assert not bad, "sensitivity rows no longer reproduce:\n  " + "\n  ".join(bad)


def test_the_worked_example_uses_a_published_size() -> None:
    """The prose crossover example divides by a retention size; it must be current."""
    text = BASELINE.read_text()
    sizes, _ = parse_table(text)
    m = re.search(r"occurrence at two orders is `(?P<gb>[\d]+) \* 100", text)
    if m is None:
        raise AssertionError("no worked crossover example to check")
    assert int(m.group("gb")) == sizes[0], (
        f"worked example divides by {m.group('gb')} GB, but the table publishes "
        f"{sizes[0]} GB"
    )


# --------------------------------------------------------------------------
# THE NEGATIVES. Each is the condition the check exists to catch, fed to it.
# --------------------------------------------------------------------------


def test_a_row_left_behind_by_a_republish_is_caught(monkeypatch: pytest.MonkeyPatch) -> None:
    """The actual defect: the size moved 263 -> 264 and a row kept 263's answer.

    The cell replaced is the live table's 21.3 TB/day occurrence ratio, re-quoted
    whenever the sizes are republished — `14,724x` under 264 GB, `14,669x` under
    the 265 GB issue #166 left. What it is replaced with is the stale value the
    original defect left behind.
    """
    published = BASELINE.read_text()
    text = published.replace("| 14,669x |", "| 14,780x |")
    assert text != published, (
        "`| 14,669x |` is no longer a cell of the sensitivity table, so this "
        "negative mutated nothing and would pass against any document at all. "
        "Re-quote it from the table the republish left."
    )
    monkeypatch.setattr(Path, "read_text", lambda self, *a, **k: text)
    bad = divergences()
    assert bad and "14,780" in bad[0]


def test_a_moved_column_size_with_stale_rows_is_caught(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The other direction: republish the header and leave every row alone."""
    published = BASELINE.read_text()
    text = published.replace("vs occurrence (265 GB)", "vs occurrence (300 GB)")
    assert text != published, (
        "the sensitivity table no longer publishes `vs occurrence (265 GB)`, so "
        "this negative mutated nothing. Re-quote the header the republish left."
    )
    monkeypatch.setattr(Path, "read_text", lambda self, *a, **k: text)
    assert len(divergences()) >= 5


def test_a_table_that_cannot_be_found_is_not_a_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Silence is a could-not-evaluate, and it must not resolve to a pass."""
    monkeypatch.setattr(Path, "read_text", lambda self, *a, **k: "# nothing here\n")
    with pytest.raises(AssertionError):
        divergences()
