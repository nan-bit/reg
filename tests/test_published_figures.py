"""The published retention figures, pinned to what the code measures (issue #90).

WHAT WAS MISSING
----------------
Four guards surrounded the published figures and none of them caught a **code
change that moves the measured value away from what the documents publish**.
`tests/test_readme.py` checks a README figure is also in `docs/plan.md`; the
drift check in `tests/test_bench.py` checks a figure names the control rate it
assumes; `scripts/check_bench_determinism.py` checks that *the same code*
produces the same bytes twice, which a change carried by both runs passes by
construction. The worked example is issue #86: three `META_TIME_BASE_*` keys, one
of them 1,412 bytes of prose where every other meta value is 8, tipped the meta
table onto a new SQLite page and moved every level of the curve by +1,024 B —
0.1%, materially harmless, and green in all four guards. It surfaced because a
reviewer ran the benchmark by hand. Nothing bounded how large the next one would
be.

THIS IS A GOLDEN VALUE, AND THAT IS THE POINT
---------------------------------------------
CLAUDE.md says prefer invariants to golden values, and `tests/test_bench.py`
opens with the argument for why almost nothing there asserts a live number. Both
still hold — for a *ratio*, which moves with every legitimate change to the
schema, the envelope parameters and the float precision, and which no document
quotes as a fact.

The three retention figures are the other case. `docs/plan.md` Claim 1 quotes
them as a purchasing decision (263 GB per robot per six months),
`docs/sufficiency.md` prices its question set against them and
`docs/sensor-baseline.md` derives a sensitivity table from them. **A figure whose
entire claim is that it is reproducible is a figure for which the pin is the
invariant**: the property under test is not "the artifact is 1,000,448 bytes", it
is "the number this repository publishes is the number this repository measures".

Two things follow, and they are what make the pin cheap to live with:

* **There is no constant in this file.** Every expected value is parsed out of
  the documents, so the pin fails in *both* directions — a code change that moves
  the measurement fails it, and a document edited to match a regression fails it
  too. There is no "golden" to update; the only ways to green are to fix the code
  or to re-measure and republish. `divergences` says exactly that in its failure
  message, because a check whose remedy is unobvious is a check the next person
  deletes instead of the mistake.
* **Re-measuring is one command**, the one the documents already name:
  `python -m reg.bench --resolution --seed 0`.

WHY THE FIXTURE IS THE PUBLISHED ONE, AND WHAT THAT COSTS
---------------------------------------------------------
Issue #90 asks for a short fixture if a short one can carry the same property.
**It cannot, and the reason is not incidental.** `bytes_per_hour` is
`size_bytes * 3600 / run_seconds`, and the artifact's cost is a near-constant
schema-and-index term plus a per-frame term — which is precisely why
`reg.bench --scaling` exists as a separate study. A 30-frame run therefore
produces a *different number*, not a scaled one, and pinning it would pin a
figure no document publishes. Deriving the published figure from a short run
would mean fitting the two terms and evaluating the fit at 3,000 frames, which is
the extrapolation `reg.bench` refuses everywhere else.

So this module measures the published curve: `long_run` at 3,000 frames, ~2
minutes of wall clock on the machine that wrote it, **once** per test session —
one build, three views, shared by every test below through a module-scoped
fixture. The published run's `timing_repeats` is the one parameter not
reproduced: timings are wall clock, they are not deterministic, and no figure
pinned here is a function of them (`reg.bench.WALL_CLOCK_COLUMNS`). Dropping the
repeats to 1 removes two replays of a 3,000-frame CSV and moves no byte.

WHAT THIS DOES NOT COVER
------------------------
* **Prose restatements.** The figures also appear in sentences —
  "60.05, 149.47 and 217.32 MB/h" — where nothing mechanically attributes a
  number to a level, and where a neighbouring figure may belong to an entirely
  different fixture (`docs/prior-art.md` quotes 47.3 MB/hour, which is the 30,000
  frame scaling run). Only the three **tables** are parsed, and the roster below
  pins which they are. A document whose table is right and whose prose is wrong
  is an internal inconsistency this cannot see.
* **The derived six-month totals** (263 GB, 26.3 TB) and the ratios against the
  assumed sensor log. They are arithmetic over a retention floor stated in prose;
  pinning the `MB/h` they are computed from is what stops them drifting silently,
  and re-deriving them here would be a second definition of that arithmetic.
* **The rows for control rates other than 50 Hz.** They come from
  `--control-rate-hz 50,100,250,1000`, a study four times the length of this one;
  its 50 Hz row is the published curve, and that row is what is pinned here.
  **Issue #98 asked for this exclusion to be decided rather than left implicit**,
  because `README.md` was leading with the 1 kHz figure. It is decided and it
  stands: the 1 kHz point alone is twenty times the frames of the fixture below,
  for rows that can only move when the 50 Hz row moves, since every one of them is
  the same curve at a different `dt`. What changed is that the documents now say
  so where they quote it — `docs/plan.md`, *The control rate*, carries the
  decision, and the front page no longer leads with an unpinned figure.

WHAT ISSUE #98 ADDED
--------------------
Two things, both at the bottom of this module and both free of any new build:

* **The Layer-A-carrying comparison against the stream.** `docs/plan.md` published
  `~13x larger than a gzipped copy of the stream` measured with `records=None` —
  the scaling ladder's parameterization — and `README.md` repeated it with no
  qualifier at all. The artifact the retention claim actually prices carries the
  record stream and is `~41x`. That figure is now published in `docs/plan.md` and
  pinned here against `curve.source`, which the fixture below already builds: the
  comparison costs nothing to check and was wrong by a factor of three.
* **The condition on the `13x`.** A figure a reader can take away without its
  condition is the defect, not the arithmetic. Every table row and every paragraph
  in `README.md` and `docs/plan.md` that quotes `13x` has to name the absence of
  Layer A in that same unit of text — checked mechanically, three-valued, with the
  documents that quote it pinned so deleting the figure is not a way to pass.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import pytest

from reg import bench
from reg.scenarios import DEFAULT_DT

REPO = Path(__file__).resolve().parent.parent
DOCS = REPO / "docs"
README = REPO / "README.md"

#: The command every document names as the one that produced these figures.
#: Quoted in the failure message rather than described, so the remedy is
#: copy-pasteable from a red CI log.
MEASURING_COMMAND = "python -m reg.bench --resolution --seed 0"

# --------------------------------------------------------------------------
# Reading the figures out of the documents.
#
# These regexes parse **table cells for attribution** — which level a number
# belongs to. That is a different job from the drift check in
# `tests/test_bench.py`, which asks whether a *paragraph* naming a figure also
# names the control rate; its `PER_HOUR` captures the number and discards the
# unit, and the unit is exactly what has to survive here. Neither is a restated
# copy of the other: they answer different questions about the same corpus.
# --------------------------------------------------------------------------

#: A retention figure with its unit attached: `60.05 MB/h`, `1.04 GB/h`.
PER_HOUR = re.compile(r"\d[\d,]*(?:\.\d+)?\s*[kMGT]?B/h(?:our)?\b")

#: A control rate: `50 Hz`, `1 kHz`, `1,000 Hz`.
RATE = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(k?)Hz\b")

#: Decimal, like `reg.bench._bytes_per_hour_text`. A retention policy is written
#: in MB, not MiB, and the documents are rendered from that function.
UNITS = {"B": 1.0, "kB": 1e3, "MB": 1e6, "GB": 1e9, "TB": 1e12}

#: The columns of a level-per-row table this module pins, as
#: `header substring -> the name used in failure messages`. Every one is a
#: **measured** output of the curve. `ts res` is deliberately absent: it is an
#: input to the measurement, and pinning inputs is the parameter block's job.
ROW_TABLE_COLUMNS: tuple[tuple[str, str], ...] = (
    ("sqlite b", "SQLite B"),
    ("bytes/hour", "bytes/hour"),
    ("nodes", "nodes"),
    ("edges", "edges"),
    ("occ", "occurrences"),
    ("records", "records"),
)

#: The one quantity a level-per-column rate table carries per level.
COLUMN_TABLE_QUANTITY = "bytes/hour"


@dataclass(frozen=True)
class Figure:
    """One published number, attributed to a level and a quantity."""

    doc: str
    quantity: str
    level: str
    #: Exactly as the document renders it, `**bold**` stripped: `60.05 MB/h`.
    text: str


def _cell(raw: str) -> str:
    """A table cell with markdown emphasis and code ticks removed."""
    return raw.replace("**", "").replace("*", "").replace("`", "").strip()


def _tables(text: str) -> list[tuple[list[str], list[list[str]]]]:
    """Every markdown table in `text`, as `(header cells, body rows)`."""
    tables: list[tuple[list[str], list[list[str]]]] = []
    block: list[str] = []
    for line in [*text.splitlines(), ""]:
        if line.lstrip().startswith("|"):
            block.append(line)
            continue
        # A table is a header, a delimiter row of dashes, and at least one body
        # row. Anything shorter is a fragment, and a fragment with no delimiter
        # is not a table at all.
        if len(block) >= 3 and set(_cell(block[1])) <= set("-:| "):
            header = [_cell(c) for c in block[0].strip().strip("|").split("|")]
            rows = [
                [_cell(c) for c in row.strip().strip("|").split("|")]
                for row in block[2:]
            ]
            tables.append((header, rows))
        block = []
    return tables


def _rates_hz(text: str) -> set[float]:
    """Every control rate named in `text`, normalised to Hz."""
    return {
        float(number.replace(",", "")) * (1_000.0 if kilo else 1.0)
        for number, kilo in RATE.findall(text)
    }


def published_figures(doc: str, text: str) -> tuple[Figure, ...]:
    """Every level-attributed measured figure `text` publishes.

    Two table shapes carry them, and both are read here rather than one being
    normalised into the other — the normalisation would be a place for a figure
    to be dropped silently:

    * **level per row** (`docs/sufficiency.md`, *The measured curve*): the first
      cell names a level and the columns named in `ROW_TABLE_COLUMNS` carry its
      measurements.
    * **level per column** (`docs/plan.md` and `docs/sensor-baseline.md`, the
      control-rate ladders): the header names the three levels and the row whose
      first cell names **only** the base control rate is the published curve.
      A row naming two rates — `x, 50 Hz -> 1 kHz` — is a comparison, not a
      measurement, and is not one of these.

    A table that is neither yields nothing. That is the common case and it has to
    be silent: `docs/sufficiency.md`'s question table has the three levels as
    column headings and `AGREE` in every cell, and reading a verdict as a figure
    would be worse than missing one.
    """
    found: list[Figure] = []
    for header, rows in _tables(text):
        columns = {
            index: cell
            for index, cell in enumerate(header)
            if cell in bench.RESOLUTION_LEVELS
        }
        if set(columns.values()) == set(bench.RESOLUTION_LEVELS):
            for row in rows:
                if not row or _rates_hz(row[0]) != {bench.BASE_CONTROL_RATE_HZ}:
                    continue
                for index, level in columns.items():
                    if index >= len(row):
                        continue
                    figure = PER_HOUR.search(row[index])
                    if figure is None:
                        continue
                    found.append(
                        Figure(doc, COLUMN_TABLE_QUANTITY, level, figure.group(0))
                    )
            continue

        quantities = {
            index: name
            for index, cell in enumerate(header)
            for key, name in ROW_TABLE_COLUMNS
            if key in cell.lower()
        }
        for row in rows:
            if not row or row[0] not in bench.RESOLUTION_LEVELS:
                continue
            for index, name in quantities.items():
                if index < len(row) and row[index]:
                    found.append(Figure(doc, name, row[0], row[index]))
    return tuple(found)


# --------------------------------------------------------------------------
# THE ROSTER. Pinned for the reason `tests/test_bench.py`'s
# `DOCS_WITH_RETENTION_FIGURES` is pinned: the comparison below is satisfied by a
# document with nothing in it to compare, so on its own it would go green if
# every table in the repository were deleted. This names where the figures are
# published today. It fails in both directions, and both are worth a look — a
# document that lost its table, and one that gained a new publication site for a
# number that now has to stay in step with the code.
# --------------------------------------------------------------------------

#: `(document, quantity)` -> the table that publishes it. Every site publishes
#: all three levels; `test_every_site_publishes_all_three_levels` is what stops a
#: table that quietly lost a row from reading as a table that never had it.
PUBLICATION_SITES: frozenset[tuple[str, str]] = frozenset(
    {
        # docs/plan.md, "The control rate" — its 50 Hz row is the published curve.
        ("plan.md", "bytes/hour"),
        # docs/sensor-baseline.md, the same ladder beside the sensor assumption.
        ("sensor-baseline.md", "bytes/hour"),
        # docs/sufficiency.md, "The measured curve" — the full row per level.
        ("sufficiency.md", "SQLite B"),
        ("sufficiency.md", "bytes/hour"),
        ("sufficiency.md", "nodes"),
        ("sufficiency.md", "edges"),
        ("sufficiency.md", "occurrences"),
        ("sufficiency.md", "records"),
    }
)


def corpus() -> tuple[Figure, ...]:
    """Every published figure in `docs/`, discovered by glob rather than listed.

    Globbed for the reason issue #78 gives: a hand-maintained roster of documents
    drifts exactly the way the prose it guards does, and the document written next
    milestone is inside this check on the day it is written.
    """
    return tuple(
        figure
        for path in sorted(DOCS.glob("*.md"))
        for figure in published_figures(path.name, path.read_text(encoding="utf-8"))
    )


# --------------------------------------------------------------------------
# The measurement, and the comparison against it.
# --------------------------------------------------------------------------


def measured_parameters() -> dict[str, object]:
    """The parameterization `MEASURING_COMMAND` runs at, read off its own parser.

    **Not restated here.** Every figure pinned below is a function of these, so a
    literal `16` in this file would be a second definition of the published
    parameterization and the two would drift — which is the shape of the defect
    this module exists to catch, committed by its own fixture. A parser default
    that went missing is a refusal rather than a number invented at this call
    site (CLAUDE.md, "never invent a default").
    """
    parser = bench._parser()
    wanted = {
        "seed": "seed",
        "horizon": "horizon",
        "n_samples": "resolution_n_samples",
        "envelope_seed": "envelope_seed",
        "substep_dt": "substep_dt",
        "occurrence_resolution_s": "occurrence_resolution",
        "replan_interval_s": "resolution_replan_interval",
        "declaration_horizon_s": "resolution_declaration_horizon",
        "watchdog_period_s": "resolution_watchdog_period",
    }
    parameters = {name: parser.get_default(flag) for name, flag in wanted.items()}
    parameters["frames"] = parser.get_default("resolution_frames")
    missing = sorted(name for name, value in parameters.items() if value is None)
    if missing:
        raise AssertionError(
            f"`{MEASURING_COMMAND}` no longer has a default for {missing}, so "
            "what the published figures were measured at cannot be recovered "
            "from the command that produced them. Nothing here may pick a value: "
            "state it in the CLI or the figures are unreproducible."
        )
    return parameters


@pytest.fixture(scope="module")
def curve(tmp_path_factory) -> bench.ResolutionCurve:
    """The published curve, measured once. ~2 minutes; see the module docstring.

    `timing_repeats=1` is the only departure from `MEASURING_COMMAND`, and it
    moves no figure pinned here: the repeats decide the precision of the wall
    clock columns, which are the only fields in the whole report that two runs at
    one seed may legitimately differ in.
    """
    parameters = dict(measured_parameters())
    frames = parameters.pop("frames")
    return bench.run_resolution_curve(
        frames,
        tmp_path_factory.mktemp("published-curve"),
        timing_repeats=1,
        **parameters,  # type: ignore[arg-type]
    )


def measured_figures(curve: bench.ResolutionCurve) -> dict[tuple[str, str], str]:
    """`(quantity, level)` -> the figure, rendered the way the report renders it.

    Rendered rather than compared numerically, and that is the whole comparison:
    a document publishes `60.05 MB/h`, which is `reg.bench._bytes_per_hour_text`
    of a measurement, so the pin is that the same function of today's measurement
    is the same string. Comparing the underlying floats would need a tolerance,
    and a tolerance on a published figure is a licence for it to drift by less
    than the tolerance every milestone.
    """
    return {
        (quantity, point.level): text
        for point in curve.points
        for quantity, text in (
            ("SQLite B", bench._int_text(point.size_bytes)),
            ("bytes/hour", bench._bytes_per_hour_text(point.bytes_per_hour)),
            ("nodes", bench._int_text(point.nodes)),
            ("edges", bench._int_text(point.edges)),
            ("occurrences", bench._int_text(point.occurrences)),
            ("records", bench._int_text(point.records)),
        )
    }


def _as_number(text: str) -> float | None:
    """A published figure as a plain number, or `None` if it cannot be read.

    Used only to say *how far* a figure moved. `None` is not a pass: an
    unparseable figure is reported as a divergence with the delta missing rather
    than skipped, because a figure nobody can read is not a figure anybody can
    check.
    """
    match = re.fullmatch(
        r"(\d[\d,]*(?:\.\d+)?)\s*([kMGT]?B)?(?:/h(?:our)?)?", text.strip()
    )
    if match is None:
        return None
    scale = UNITS.get(match.group(2) or "B", 1.0)
    return float(match.group(1).replace(",", "")) * scale


def _delta_text(published: str, measured: str) -> str:
    """How far the figure moved, as the reader of a red log needs it.

    In the units of the figure itself, which the sentence around it names: a
    `bytes/hour` figure moves by bytes/hour and a row count by rows. Both the
    absolute move and the fraction, because 0.1% and +1,024 B are the same fact
    and neither one alone says whether to worry.
    """
    was, now = _as_number(published), _as_number(measured)
    if was is None or now is None:
        return (
            "a move of an amount that could not be computed — one of the two is "
            "not a number"
        )
    if was == 0.0:
        return f"a move of {now - was:+,.0f}"
    return f"a move of {now - was:+,.0f} ({(now - was) / was:+.2%})"


def divergences(
    published: Sequence[Figure], measured: Mapping[tuple[str, str], str]
) -> list[str]:
    """One line per published figure that is no longer what the code measures.

    The message is the deliverable as much as the verdict is. It names the
    figure, says how far it moved, and states the two remedies — because the
    third one, editing the number in the test, is what a golden value invites and
    it is not available here: the expected values are the documents.
    """
    lines: list[str] = []
    for figure in published:
        key = (figure.quantity, figure.level)
        if key not in measured:
            lines.append(
                f"docs/{figure.doc} publishes a `{figure.level}` {figure.quantity} "
                f"of {figure.text}, and the curve measured no such figure — so it "
                "could not be checked at all. That is a could-not-evaluate, not a "
                "pass."
            )
            continue
        if figure.text == measured[key]:
            continue
        lines.append(
            f"docs/{figure.doc} publishes `{figure.level}` {figure.quantity} as "
            f"{figure.text}; the code now measures {measured[key]} — "
            f"{_delta_text(figure.text, measured[key])}."
        )
    if lines:
        lines.append(
            "Either the change that moved the measurement is a regression to fix, "
            "or the measurement is the new truth and every document above must be "
            f"re-measured and republished with `{MEASURING_COMMAND}`. Do not edit "
            "a number into this test to make it green: it holds none — every "
            "value it compares against is read out of those documents."
        )
    return lines


# --------------------------------------------------------------------------
# THE PIN.
# --------------------------------------------------------------------------


def test_every_published_figure_is_the_one_the_code_measures(
    curve: bench.ResolutionCurve,
) -> None:
    """**THE TEST THIS MODULE EXISTS FOR** — issue #86, caught by hand, mechanised.

    Fails in both directions by construction. A code change that moves the
    measurement fails it; a document edited to match a regression fails it too,
    because the expected value *is* the document.
    """
    published = corpus()
    assert published, (
        "no published figure was found in docs/ at all, so this comparison had "
        "nothing to compare. An empty corpus is a could-not-evaluate and must "
        "not read as agreement — see the roster test below."
    )
    problems = divergences(published, measured_figures(curve))
    assert not problems, "\n".join(problems)


def test_the_curve_was_measured_at_the_published_parameterization(
    curve: bench.ResolutionCurve,
) -> None:
    """The figures above are only the published ones if the run was.

    Every parameter comes from `MEASURING_COMMAND`'s own parser, so this asserts
    the properties the documents state in prose beside the tables — 3,000 frames,
    60.0 s of robot time at 50 Hz, 16 envelope samples, occurrence resolution
    1.0 s. If the fixture is re-parameterized these fail here, next to the
    figures, rather than silently making the pin a pin on something else.
    """
    parameters = measured_parameters()
    assert curve.frames == parameters["frames"]
    assert curve.n_samples == parameters["n_samples"]
    assert curve.occurrence_resolution_s == parameters["occurrence_resolution_s"]
    assert curve.replan_interval_s == parameters["replan_interval_s"]
    assert curve.declaration_horizon_s == parameters["declaration_horizon_s"]
    assert curve.watchdog_period_s == parameters["watchdog_period_s"]
    # The control rate the documents put in the column heading, from the fixture
    # rather than restated — `reg.bench.BASE_CONTROL_RATE_HZ` is the same
    # derivation and issue #68 is why it is one.
    assert curve.frame_period_s == DEFAULT_DT
    assert 1.0 / curve.frame_period_s == bench.BASE_CONTROL_RATE_HZ
    assert {point.level for point in curve.points} == set(bench.RESOLUTION_LEVELS)


def test_the_documents_that_publish_the_curve_are_the_ones_expected() -> None:
    """**SILENCE IS NOT A PASS, AT THE CORPUS LEVEL.**

    The pin is satisfied by a document with no table in it, so this names where
    the figures are published. A loss means a publication site was deleted — the
    one way a check of this shape is defeated without anything going red. A gain
    is not a problem, it is a new place a rate-linear measured number is quoted;
    add it here once it is in step.
    """
    sites = {(figure.doc, figure.quantity) for figure in corpus()}
    assert sites == set(PUBLICATION_SITES), (
        "the set of documents publishing a measured figure from the resolution "
        f"curve has moved: gained {sorted(sites - PUBLICATION_SITES)}, lost "
        f"{sorted(PUBLICATION_SITES - sites)}. A gain needs adding to "
        "PUBLICATION_SITES; a loss means the figures this module pins are no "
        "longer being published there."
    )


def test_every_site_publishes_all_three_levels() -> None:
    """A table that lost a row is not a table that never had one.

    Without this, deleting the `per-frame` row from a published table would leave
    the roster above intact and the pin green over two levels.
    """
    published = corpus()
    for doc, quantity in sorted(PUBLICATION_SITES):
        levels = {
            figure.level
            for figure in published
            if (figure.doc, figure.quantity) == (doc, quantity)
        }
        assert levels == set(bench.RESOLUTION_LEVELS), (
            f"docs/{doc} publishes {quantity} for {sorted(levels)} and the curve "
            f"has {sorted(bench.RESOLUTION_LEVELS)}. A missing level is a figure "
            "that stopped being published, not a figure that agrees."
        )


# --------------------------------------------------------------------------
# THE NEGATIVES. A check fed only healthy input has not been shown able to fail.
#
# Hand-worked against `divergences`, which is the whole comparison: the fixture
# above is the *input* to it, and re-measuring a 3,000-frame curve to produce a
# deliberately wrong number would cost two minutes to learn what a dict already
# says. The end-to-end demonstration — issue #86's own defect, a >1 KB constant
# written into `meta` — is in the PR body, where it can be run against the real
# fixture without leaving a mutation in the tree.
# --------------------------------------------------------------------------

#: A published figure and the measurement it came from, in agreement.
_HEALTHY = (Figure("plan.md", "bytes/hour", "occurrence", "60.05 MB/h"),)
_MEASURED = {("bytes/hour", "occurrence"): "60.05 MB/h"}


def test_a_figure_that_agrees_is_not_reported() -> None:
    """The positive control: the check is not one that can only say no."""
    assert divergences(_HEALTHY, _MEASURED) == []


def test_a_measurement_that_moved_is_caught() -> None:
    """**THE NEGATIVE THIS MODULE EXISTS FOR**, in miniature: issue #86's defect
    is +1,024 B on a 1,000,448 B artifact, which is 60.05 MB/h becoming 60.11."""
    problems = divergences(_HEALTHY, {("bytes/hour", "occurrence"): "60.11 MB/h"})
    assert len(problems) == 2  # the finding, and what to do about it
    assert "docs/plan.md publishes `occurrence` bytes/hour as 60.05 MB/h" in problems[0]
    assert "the code now measures 60.11 MB/h" in problems[0]


def test_a_document_edited_to_match_a_regression_is_caught() -> None:
    """The other direction, and the one the pin would be worthless without: a
    figure republished to agree with a measurement nobody re-measured is exactly
    as caught as the measurement moving under a figure nobody republished."""
    edited = (Figure("plan.md", "bytes/hour", "occurrence", "60.11 MB/h"),)
    assert divergences(edited, _MEASURED)


def test_the_failure_message_says_which_figure_by_how_much_and_what_to_do() -> None:
    """The message is the deliverable. A golden value whose remedy is unobvious
    is a golden value the next person deletes instead of the mistake."""
    problems = divergences(_HEALTHY, {("bytes/hour", "occurrence"): "60.11 MB/h"})
    finding, remedy = problems
    assert "occurrence" in finding and "bytes/hour" in finding  # which figure
    assert "+60,000 (+0.10%)" in finding  # by how much
    assert "regression to fix" in remedy
    assert "re-measured and republished" in remedy
    assert MEASURING_COMMAND in remedy
    assert "Do not edit a number into this test" in remedy


def test_a_figure_the_curve_does_not_measure_is_a_refusal_not_a_pass() -> None:
    """A published figure with nothing to compare it to is a could-not-evaluate,
    and the third verdict never resolves to the first: it is reported."""
    problems = divergences(_HEALTHY, {})
    assert problems
    assert "could not be checked at all" in problems[0]


def test_an_unreadable_figure_is_reported_rather_than_skipped() -> None:
    """A figure that is not a number is still a figure that does not match. The
    delta is what goes missing, not the finding."""
    problems = divergences(
        (Figure("plan.md", "bytes/hour", "occurrence", "about sixty"),), _MEASURED
    )
    assert "could not be computed" in problems[0]


# --- the parser, fed shapes it has to get right and shapes it must ignore ---


def test_a_level_per_row_table_is_read_by_row() -> None:
    """`docs/sufficiency.md`'s shape, in miniature."""
    figures = published_figures(
        "d.md",
        "| level | ts res | SQLite B | bytes/hour @ 50 Hz | nodes |\n"
        "|---|---|---|---|---|\n"
        "| `occurrence` | 1.0 s | 1,000,448 | **60.05 MB/h** | 3,166 |\n",
    )
    assert {(f.quantity, f.level, f.text) for f in figures} == {
        ("SQLite B", "occurrence", "1,000,448"),
        ("bytes/hour", "occurrence", "60.05 MB/h"),
        ("nodes", "occurrence", "3,166"),
    }


def test_a_level_per_column_table_is_read_at_the_base_rate_row_only() -> None:
    """`docs/plan.md`'s shape. The other rows are measurements of other rates and
    a pin that read them would fail on a table that is entirely correct."""
    figures = published_figures(
        "d.md",
        "| control rate | occurrence | transition | per-frame |\n"
        "|---|---|---|---|\n"
        "| **50 Hz (this simulator)** | **60.05 MB/h → 263 GB** | 149.47 MB/h |"
        " 217.32 MB/h |\n"
        "| **1 kHz (a real manipulator)** | 950.55 MB/h | 1.94 GB/h | 4.26 GB/h |\n",
    )
    assert {(f.level, f.text) for f in figures} == {
        ("occurrence", "60.05 MB/h"),
        ("transition", "149.47 MB/h"),
        ("per-frame", "217.32 MB/h"),
    }
    assert {f.quantity for f in figures} == {"bytes/hour"}


def test_a_row_comparing_two_rates_is_not_a_measurement_at_either() -> None:
    """`docs/sensor-baseline.md` carries an `x, 50 Hz -> 1 kHz` row. Reading its
    multiples as figures at 50 Hz would be a pin on a ratio."""
    figures = published_figures(
        "d.md",
        "| control rate | occurrence | transition | per-frame |\n"
        "|---|---|---|---|\n"
        "| *x, 50 Hz → 1 kHz* | *15.8x* | *13.0x* | *19.6x* |\n",
    )
    assert figures == ()


def test_a_table_of_verdicts_under_the_level_names_yields_no_figures() -> None:
    """`docs/sufficiency.md`'s question table has the three levels as column
    headings. Reading `AGREE` as a measurement would be worse than missing one."""
    figures = published_figures(
        "d.md",
        "| question | layer | `occurrence` | `transition` | `per-frame` |\n"
        "|---|---|---|---|---|\n"
        "| `min_separation` | B | AGREE | AGREE | AGREE |\n",
    )
    assert figures == ()


def test_prose_that_is_not_a_table_yields_nothing() -> None:
    """The stated limit of this parser, asserted so it stays a known one: the
    figures also appear in sentences, and nothing there attributes a number to a
    level. The roster test is what stops that from becoming a hiding place."""
    assert (
        published_figures(
            "d.md",
            "Each is the measured `bytes/hour` for that level — 60.05, 149.47 "
            "and 217.32 MB/h — times the 4,380 hours in the retention floor.\n",
        )
        == ()
    )


# --------------------------------------------------------------------------
# THE LAYER-A-CARRYING COMPARISON AGAINST THE STREAM (issue #98).
#
# `docs/plan.md`'s scaling ladder answers "is the graph smaller than the stream
# it replaces" with `0.08x`, i.e. ~13x larger — and it answers it for an artifact
# built with `records=None`. That is the correct parameterization for a study
# whose variable is run length, and the wrong number to quote as the cost of the
# artifact this project ships: with the record stream in it the same fixture at
# the same length is ~41x larger. `README.md` quoted the 13x with no qualifier at
# all, on the front page, months after issue #59 corrected the same error in the
# resolution curve.
#
# WHY IT IS PINNED HERE AND NOT SOMEWHERE CHEAPER. The build it is measured on is
# the one the fixture above already makes — `curve.source` is the artifact
# `reg.graph.build` produced before any view was materialized from it — so this
# whole section adds no measurement, only a comparison. Everything it compares is
# rendered by the same `reg.bench` functions the rest of the module uses, for the
# same reason: a document publishes a string, and the pin is that the same
# function of today's measurement is that string.
# --------------------------------------------------------------------------

#: The level slot `divergences` reports these under. They are not a resolution
#: level — they are properties of the source artifact — so the slot names the
#: build instead, and the failure message reads as a sentence either way.
LAYER_A_BUILD = "the build Claim 1 prices"

#: Every row of the table, so a table that quietly lost one does not read as a
#: table that never had it. This is the same property
#: `test_every_site_publishes_all_three_levels` gives the curve.
LAYER_A_COMPARISON_ROWS: tuple[str, ...] = (
    "declarations",
    "verdicts",
    "faults",
    "chain records",
    "artifact on disk",
    "gzipped CSV baseline",
    "x gz CSV",
    "how much larger",
)


def plan_text() -> str:
    """`docs/plan.md`, read at call time so no test holds a stale copy."""
    return (DOCS / "plan.md").read_text(encoding="utf-8")


def layer_a_comparison(text: str) -> dict[str, str]:
    """The `label -> figure` table `docs/plan.md` publishes the comparison in.

    Identified by its first header cell rather than by position: a table found by
    counting tables from the top of a document is a table that moves the first
    time somebody adds another one above it.
    """
    found: dict[str, str] = {}
    for header, rows in _tables(text):
        if not header or LAYER_A_BUILD not in header[0]:
            continue
        for row in rows:
            if len(row) >= 2 and row[0]:
                found[row[0]] = row[1]
    return found


def measured_layer_a_comparison(curve: bench.ResolutionCurve) -> dict[str, str]:
    """The same eight figures, measured, rendered as the documents render them.

    `how much larger` is the one quantity `reg.bench` has no renderer for — it
    publishes the ratio, not its reciprocal — so the arithmetic is here, once, and
    the document states what this produces. It is not a tolerance: `~41x` is
    `f"~{40.68:.0f}x"`, and a measurement that moved far enough to round
    differently is a measurement the document has to be re-measured for.
    """
    sizes = curve.source.sizes
    counts = curve.attestation_counts
    return {
        "declarations": bench._int_text(counts["declarations"]),
        "verdicts": bench._int_text(counts["verdicts"]),
        "faults": bench._int_text(counts["faults"]),
        "chain records": bench._int_text(counts["chain_records"]),
        "artifact on disk": f"{bench._int_text(sizes.sqlite)} B",
        "gzipped CSV baseline": f"{bench._int_text(sizes.gzip_csv)} B",
        "x gz CSV": bench._ratio_text(sizes.ratio_vs_gzip_csv),
        "how much larger": f"~{sizes.sqlite / sizes.gzip_csv:.0f}x",
    }


def _as_layer_a_figures(doc: str, published: Mapping[str, str]) -> tuple[Figure, ...]:
    """The published table as `Figure`s, so `divergences` compares it.

    Reused rather than reimplemented: the failure message, the delta and the two
    remedies are the deliverable of that function, and a second comparison here
    would be a second definition of what a divergence is.
    """
    return tuple(
        Figure(doc, label, LAYER_A_BUILD, text) for label, text in published.items()
    )


def test_the_layer_a_comparison_is_the_one_the_code_measures(
    curve: bench.ResolutionCurve,
) -> None:
    """**THE PIN ISSUE #98 ADDED.** `~41x`, not `13x`, and re-measured every run.

    Fails in both directions for the same reason the curve's pin does: the
    expected values are the document.
    """
    published = layer_a_comparison(plan_text())
    assert published, (
        "docs/plan.md publishes no Layer-A-carrying comparison table at all, so "
        "this had nothing to compare. That is a could-not-evaluate — the figure "
        "it guards was wrong by a factor of three on the front page for months."
    )
    measured = {
        (label, LAYER_A_BUILD): text
        for label, text in measured_layer_a_comparison(curve).items()
    }
    problems = divergences(_as_layer_a_figures("plan.md", published), measured)
    assert not problems, "\n".join(problems)


def test_the_layer_a_comparison_publishes_every_row() -> None:
    """A table that lost a row is not a table that never had one.

    Without this, deleting `how much larger` would leave the pin above green over
    seven rows and the `~41x` unpublished.
    """
    published = set(layer_a_comparison(plan_text()))
    assert published == set(LAYER_A_COMPARISON_ROWS), (
        "the Layer-A-carrying comparison in docs/plan.md publishes "
        f"{sorted(published)}; this pin covers {sorted(LAYER_A_COMPARISON_ROWS)}. "
        "A missing row is a figure that stopped being published, not a figure "
        "that agrees; a new one needs adding here and to "
        "`measured_layer_a_comparison`, or it is published and unchecked."
    )


# --- the negatives for the pin above ---

#: The published table and the measurement it came from, in agreement.
_LAYER_A_HEALTHY = {"artifact on disk": "2,580,480 B", "how much larger": "~41x"}
_LAYER_A_MEASURED = {
    ("artifact on disk", LAYER_A_BUILD): "2,580,480 B",
    ("how much larger", LAYER_A_BUILD): "~41x",
}


def test_a_layer_a_comparison_that_agrees_is_not_reported() -> None:
    """The positive control: the check is not one that can only say no."""
    healthy = _as_layer_a_figures("plan.md", _LAYER_A_HEALTHY)
    assert divergences(healthy, _LAYER_A_MEASURED) == []


def test_the_13x_republished_as_the_layer_a_figure_is_caught() -> None:
    """**THE NEGATIVE THIS SECTION EXISTS FOR**, and it is issue #98's own defect:
    the `records=None` ladder's number standing where the Layer-A one belongs."""
    problems = divergences(
        _as_layer_a_figures("plan.md", {"artifact on disk": "818,176 B"}),
        {("artifact on disk", LAYER_A_BUILD): "2,580,480 B"},
    )
    assert len(problems) == 2  # the finding, and what to do about it
    assert "818,176 B" in problems[0] and "2,580,480 B" in problems[0]
    assert "+1,762,304" in problems[0]


def test_a_layer_a_figure_the_build_does_not_measure_is_a_refusal() -> None:
    """A row published under a label nothing measures is a could-not-evaluate, and
    the third verdict never resolves to the first."""
    problems = divergences(
        _as_layer_a_figures("plan.md", {"bytes per frame": "860 B"}), _LAYER_A_MEASURED
    )
    assert problems and "could not be checked at all" in problems[0]


def test_the_layer_a_parser_reads_the_table_by_its_header() -> None:
    """The shape it has to get right, in miniature."""
    assert layer_a_comparison(
        f"| {LAYER_A_BUILD}, at 3,000 frames | measured |\n"
        "|---|---|\n"
        "| artifact on disk | 2,580,480 B |\n"
        "| how much larger | **~41x** |\n"
    ) == {"artifact on disk": "2,580,480 B", "how much larger": "~41x"}


def test_the_layer_a_parser_ignores_every_other_table() -> None:
    """The scaling ladder is two-column and sits in the same section. Reading its
    rungs as this comparison would pin the number this issue exists to correct."""
    assert (
        layer_a_comparison(
            "| frames | robot time | x gz CSV |\n"
            "|---|---|---|\n"
            "| 3,000 | 60 s | 0.08x |\n"
        )
        == {}
    )


# --------------------------------------------------------------------------
# THE CONDITION ON THE `13x` (issue #98).
#
# The arithmetic was never the defect. `docs/plan.md` measured 13x correctly and
# said, three sentences away, that the ladder holds no Layer A; `README.md` then
# quoted the number with the condition left behind. **A figure a reader can take
# away without its condition is the figure being wrong**, and no amount of
# correctness elsewhere in the document repairs it.
#
# So this checks proximity, mechanically, in the unit a reader actually takes a
# number away in: a markdown table row on its own, and a paragraph otherwise. It
# cannot check that the wording is honest — a reviewer still has to — but it can
# check that the words are there.
# --------------------------------------------------------------------------

AGREE = "AGREE"
DISAGREE = "DISAGREE"
COULD_NOT_EVALUATE = "COULD-NOT-EVALUATE"

#: The figure whose condition may not be dropped. `13.0x` in
#: `docs/sensor-baseline.md`'s rate-comparison row is a different number and is
#: deliberately not matched.
THIRTEEN_X = re.compile(r"~?13x\b")

#: The condition, in any of the forms the documents state it in. Every one of
#: them names an *absence*, which is what the reader has to be told.
NO_LAYER_A = re.compile(r"no (?:record stream|layer\s+a|declaration)", re.IGNORECASE)

#: The documents that quote the figure today. Pinned because deleting it is the
#: one way a check of this shape goes green without the condition being stated.
DOCS_QUOTING_THE_13X: frozenset[str] = frozenset({"README.md", "plan.md"})


def _quotation_units(text: str) -> list[str]:
    """The spans a figure is read in: a table row alone, a paragraph otherwise.

    A markdown table row is its own unit because a reader takes a row away whole
    and leaves the rest of the table behind — `README.md`'s Claim 1 row is one
    such row and is where this defect lived. Everything else is a paragraph,
    joined into one line so a condition split across a line break still counts.
    """
    units: list[str] = []
    paragraph: list[str] = []

    def flush() -> None:
        if paragraph:
            units.append(" ".join(paragraph))
            paragraph.clear()

    for line in [*text.splitlines(), ""]:
        if line.lstrip().startswith("|"):
            flush()
            units.append(line)
        elif line.strip():
            paragraph.append(line.strip())
        else:
            flush()
    return units


def condition_travels_with_the_13x(text: str) -> tuple[str, list[str]]:
    """Verdict on whether every `13x` in `text` names the condition beside it.

    Three-valued, and the third does not resolve to the first: a document that
    quotes the figure nowhere is `COULD-NOT-EVALUATE`, because deleting the figure
    is otherwise a way to pass. Returns the verdict and the offending spans.
    """
    checked = 0
    missing: list[str] = []
    for unit in _quotation_units(text):
        if not THIRTEEN_X.search(unit):
            continue
        checked += 1
        if not NO_LAYER_A.search(unit):
            missing.append(unit)
    if not checked:
        return COULD_NOT_EVALUATE, []
    return (DISAGREE if missing else AGREE), missing


CORPUS_QUOTING_FIGURES: tuple[tuple[str, Path], ...] = (
    ("README.md", README),
    *((path.name, path) for path in sorted(DOCS.glob("*.md"))),
)


@pytest.mark.parametrize("doc,path", CORPUS_QUOTING_FIGURES)
def test_the_13x_is_never_quoted_without_its_condition(doc: str, path: Path) -> None:
    """**THE DOCUMENT CHECK ISSUE #98 EXISTS FOR.**

    `README.md:77` carried `roughly 13x larger per frame than a gzipped copy of
    the nine-float stream` with nothing attached, in the file most readers open
    first, while `docs/plan.md` stated the condition for the same number.
    """
    verdict, missing = condition_travels_with_the_13x(
        path.read_text(encoding="utf-8")
    )
    assert verdict != DISAGREE, (
        f"{doc} quotes 13x in {len(missing)} place(s) that never say the "
        "artifact it was measured on holds no Layer A:\n"
        + "\n".join(f"  - {unit[:160]}" for unit in missing)
        + "\nThat figure is ~41x for the artifact Claim 1 prices. Either quote "
        "~41x, or state the condition in the same paragraph or table row."
    )


def test_the_documents_that_quote_the_13x_are_the_ones_expected() -> None:
    """**SILENCE IS NOT A PASS.** The check above passes on a document with the
    figure removed, so this names where it is quoted. A loss is worth a look: the
    number is a bounded engineering finding this project deliberately publishes."""
    quoting = {
        doc
        for doc, path in CORPUS_QUOTING_FIGURES
        if condition_travels_with_the_13x(path.read_text(encoding="utf-8"))[0]
        != COULD_NOT_EVALUATE
    }
    assert quoting == set(DOCS_QUOTING_THE_13X), (
        "the set of documents quoting the 13x has moved: gained "
        f"{sorted(quoting - DOCS_QUOTING_THE_13X)}, lost "
        f"{sorted(DOCS_QUOTING_THE_13X - quoting)}. A gain needs adding here — it "
        "is a new place a conditional figure is published; a loss means the "
        "finding stopped being published where this check was guarding it."
    )


# --- the negatives for the check above ---


def test_a_bare_13x_is_caught() -> None:
    """**The negative this check exists for**, and it is the README's own sentence
    as it stood before this change."""
    verdict, missing = condition_travels_with_the_13x(
        "roughly 13x *larger* per frame than a gzipped copy of the nine-float\n"
        "stream, published beside it because that is the comparison a skeptic runs.\n"
    )
    assert verdict == DISAGREE
    assert len(missing) == 1


def test_the_condition_three_paragraphs_away_does_not_cover_the_figure() -> None:
    """The exact defect: correct elsewhere in the document, absent here."""
    verdict, missing = condition_travels_with_the_13x(
        "This ladder holds no Layer A at any rung.\n"
        "\n"
        "Some other paragraph entirely.\n"
        "\n"
        "The artifact is roughly 13x larger than the stream it replaces.\n"
    )
    assert verdict == DISAGREE
    assert missing == [
        "The artifact is roughly 13x larger than the stream it replaces."
    ]


def test_the_condition_in_the_same_paragraph_passes() -> None:
    """The positive control, across a line break, since the documents wrap."""
    verdict, missing = condition_travels_with_the_13x(
        "**With no record stream in it** — the artifact is roughly 13x\n"
        "*larger* than a gzipped copy of the stream it replaces.\n"
    )
    assert (verdict, missing) == (AGREE, [])


def test_a_table_row_is_its_own_unit() -> None:
    """`README.md`'s Claim 1 row is one row of a table whose other rows say
    nothing about Layer A. A condition in a neighbouring row is not a condition a
    reader of this row sees."""
    verdict, missing = condition_travels_with_the_13x(
        "| claim | status |\n"
        "|---|---|\n"
        "| **3** | the build carries no record stream |\n"
        "| **1** | the artifact is roughly 13x larger |\n"
    )
    assert verdict == DISAGREE
    assert missing == ["| **1** | the artifact is roughly 13x larger |"]


def test_a_document_that_never_quotes_the_figure_is_not_a_pass() -> None:
    """Three-valued: nothing to check is could-not-evaluate, and the roster test
    above is what stops that from becoming a hiding place."""
    verdict, missing = condition_travels_with_the_13x("no figures here at all\n")
    assert (verdict, missing) == (COULD_NOT_EVALUATE, [])


def test_the_rate_comparison_row_is_not_this_figure() -> None:
    """`docs/sensor-baseline.md` publishes `13.0x` — the transition level's growth
    from 50 Hz to 1 kHz. Demanding a Layer A condition beside it would be noise."""
    verdict, _ = condition_travels_with_the_13x(
        "| *x, 50 Hz → 1 kHz* | *15.8x* | *13.0x* | *19.6x* |\n"
    )
    assert verdict == COULD_NOT_EVALUATE
