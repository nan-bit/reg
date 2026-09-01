"""What the retention benchmark is priced against, as the documents describe it.

THE DEFECT THIS EXISTS FOR (issue #123)
---------------------------------------
For four milestones every document that introduced Claim 1's baseline called it a
**nine-float proprioception stream**. It is neither. `reg.stream.expected_header`
for the fixture the benchmark prices (`declared_violation`: two joints, three
obstacles) is **24 columns, 19 of them Layer B** — the human's ground-truth pose
and velocity, and each obstacle's id, kind and pose. "Nine" counted a scene with
no obstacles in it, and four of the nine it did count were `human_*`.

The label is the worse half. This project's whole argument is a boundary between
what a robot can attest to about itself and what it can only assert about the
world, and the file it measured its own retention argument against was described
as proprioception while carrying the entity state that boundary exists to
separate. `tests/test_layer_boundary.py` keeps the boundary out of the code;
nothing kept it out of the prose, because prose does not fail.

WHAT IS PINNED, AND TO WHAT
---------------------------
Nothing here is a constant. The counts are derived from
`reg.scenarios.scenario("declared_violation")` through `reg.stream.expected_header`
and `reg.bench.proprioceptive_columns`, so adding an obstacle to the fixture fails
these tests until the documents are re-read rather than silently making them
wrong; and the two byte figures are parsed out of the documents and compared
against a live measurement of the fixture, so a document edited to match a
regression fails as loudly as a regression does. That is the same posture as
`tests/test_published_figures.py`, for the same reason.

THREE CHECKS, EACH WITH ITS NEGATIVE
------------------------------------
1. **No document misdescribes the stream.** `nine-float`, `proprioception CSV`,
   `proprioceptive stream` — the names for a file that carries `human_*`.
2. **Where a description states a count, it is the schema's count**, and every
   document that names the baseline states what the stream holds somewhere in it.
   Three-valued: a document that never names the baseline is COULD-NOT-EVALUATE,
   and `test_the_documents_describing_the_baseline_are_the_ones_expected` is why
   deleting the description is not a way to pass.
3. **The published byte figures are the measured ones.** ~21 B/frame is the full
   24-column stream and does not move; the proprioception-only slice, which is the
   only part a time-series compressor is the incumbent for, is measured beside it.
"""

from __future__ import annotations

import csv
import re
import subprocess
import sys
from pathlib import Path

import pytest

from reg.bench import gzip_bytes, gzip_bytes_of_columns, proprioceptive_columns
from reg.scenarios import scenario
from reg.stream import expected_header

REPO = Path(__file__).resolve().parents[1]
DOCS = REPO / "docs"
README = REPO / "README.md"

AGREE = "AGREE"
DISAGREE = "DISAGREE"
COULD_NOT_EVALUATE = "COULD-NOT-EVALUATE"

#: The fixture every published per-frame figure is measured on, and the seed it
#: is measured at. Named here because a count is only true of a schema, and a
#: schema is only true of a fixture — "the stream" has no column count.
PRICED_FIXTURE = "declared_violation"
PRICED_SEED = 0


def _priced_header() -> list[str]:
    """The schema of the stream the benchmark prices, from the fixture itself."""
    fixture = scenario(PRICED_FIXTURE)
    return expected_header(
        len(fixture.joint_waypoints[0].value), len(fixture.world.obstacles)
    )


HEADER = _priced_header()
PROPRIOCEPTIVE = proprioceptive_columns(HEADER)
LAYER_B = [c for c in HEADER if c not in PROPRIOCEPTIVE]

#: The three counts a document is allowed to state about this stream: the whole
#: schema, the proprioceptive subset, and the Layer B remainder.
LEGITIMATE_COUNTS = frozenset(
    {len(HEADER), len(PROPRIOCEPTIVE), len(LAYER_B)}
)


# --- the corpus -------------------------------------------------------------

#: `docs/README.md` is labelled distinctly from the front page. Both are
#: `README.md` by basename, and this corpus is keyed on that name — so until the
#: docs index was added on 2026-08-31 the two would have been indistinguishable
#: here, and a roster comparing sets of names could not have said which of them
#: gained or lost a figure.
CORPUS: tuple[tuple[str, Path], ...] = (
    ("README.md", README),
    *(
        ("README.md (docs/)" if path.name == "README.md" else path.name, path)
        for path in sorted(DOCS.glob("*.md"))
    ),
)

#: The documents that name the baseline today. Pinned because every check below
#: passes on a document that stopped describing it, and a repository that quietly
#: stopped saying what it measured against would pass all of them.
DOCS_DESCRIBING_THE_BASELINE: frozenset[str] = frozenset(
    {
        "README.md",
        "limitations.md",
        "lossiness.md",
        "plan.md",
        "prior-art.md",
        # Claim 1's measurement record, extracted from `plan.md` on 2026-08-31.
        # It introduces the baseline where it prices the artifact against it;
        # `plan.md` still names it too, so both are here.
        "retention.md",
        "sensor-baseline.md",
    }
)


# --- the patterns -----------------------------------------------------------

#: A unit is about the priced stream if it names it as the thing the artifact is
#: compared against, or as the thing the simulator emits.
BASELINE_SUBJECT = re.compile(
    r"gzipped\s+(?:copy of|CSV|nine|proprioception)"
    r"|(?:raw )?state (?:stream|CSV)"
    r"|the stream it replace[sd]"
    rf"|{len(HEADER)}-column stream",
    re.IGNORECASE,
)

#: The names for this file that are false. Each one describes a stream carrying
#: no entity state; this one carries the human's pose and velocity every frame.
MISDESCRIBED = re.compile(
    r"nine[-\s]*floats?"
    r"|proprioception(?:[-\s]only)?[-\s](?:CSV|stream|baseline)"
    r"|proprioceptive[-\s](?:CSV|stream|baseline)",
    re.IGNORECASE,
)

_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20,
}

#: `24 columns`, `nine floats`, `24-column` — a width asserted about the stream.
#: Adjacency is required: `a frame's four joint values` is a true statement about
#: the same stream and a different quantity, and a check that cannot tell the two
#: apart would be answered by rewording rather than by re-measuring. Only counted
#: inside a unit that is about the stream; the corpus states plenty of other
#: column counts about other tables.
COUNT_CLAIM = re.compile(
    r"\b([0-9]+|" + "|".join(_NUMBER_WORDS) + r")[-\s](?:column|float|value)s?\b",
    re.IGNORECASE,
)

#: What the stream holds, stated with both counts: `24 columns, 19 of them Layer
#: B`. Built from the schema, so a fixture that gains an obstacle invalidates
#: every document stating the old pair.
COMPOSITION = re.compile(
    rf"\b{len(HEADER)}\b[^.]{{0,140}}?\b{len(LAYER_B)}\b[^.]{{0,40}}?Layer B",
    re.IGNORECASE,
)

#: The proprioception-only figure, as the documents publish it.
SLICE_FIGURE = re.compile(
    r"([\d,]+)\s*B\s+gzipped over\s+([\d,]+)\s+frames\s*=\s*([\d.]+)\s*B/frame",
    re.IGNORECASE,
)

#: The published full-stream figure. `~21 B/frame`, in any of its markdown skins.
FULL_STREAM_FIGURE = re.compile(r"~\s*([\d.]+)\s*B/frame", re.IGNORECASE)


def normalise(text: str) -> str:
    """Drop markdown emphasis and collapse whitespace. Nothing else."""
    return re.sub(r"\s+", " ", re.sub(r"[*_`>]", "", text))


def units(text: str) -> list[str]:
    """The spans a description is read in: a table row alone, a paragraph
    otherwise. A row is its own unit because a reader takes one row away and
    leaves the rest of the table — `README.md`'s Claim 1 row is such a row."""
    out: list[str] = []
    paragraph: list[str] = []

    def flush() -> None:
        if paragraph:
            out.append(normalise(" ".join(paragraph)))
            paragraph.clear()

    for line in [*text.splitlines(), ""]:
        if line.lstrip().startswith("|"):
            flush()
            out.append(normalise(line))
        elif line.strip():
            paragraph.append(line.strip())
        else:
            flush()
    return out


def _as_int(token: str) -> int:
    return _NUMBER_WORDS.get(token.lower(), 0) or int(token)


# --- check 1: the name ------------------------------------------------------


def misdescriptions(text: str) -> list[str]:
    """Every span calling the priced stream something it is not.

    Deliberately scanned over the whole document rather than only over spans that
    name the benchmark: the sentence this check was written for —
    *the simulator emits a nine-float proprioception stream* — was in the
    document's opening argument and mentioned no benchmark at all.
    """
    return [unit for unit in units(text) if MISDESCRIBED.search(unit)]


@pytest.mark.parametrize("doc,path", CORPUS)
def test_no_document_calls_the_priced_stream_proprioception(
    doc: str, path: Path
) -> None:
    """**THE CHECK ISSUE #123 EXISTS FOR.** A stream carrying `human_x`,
    `human_y`, `human_vx`, `human_vy` every frame is not proprioception, and this
    repository is the last place that should blur it."""
    offenders = misdescriptions(path.read_text(encoding="utf-8"))
    assert not offenders, (
        f"{doc} describes the benchmark's input as a nine-float or "
        f"proprioception-only stream in {len(offenders)} place(s):\n"
        + "\n".join(f"  - {unit[:180]}" for unit in offenders)
        + f"\nIt is {len(HEADER)} columns for the {PRICED_FIXTURE} fixture, "
        f"{len(LAYER_B)} of them Layer B: {', '.join(LAYER_B[:6])}, ... . Say "
        "that instead."
    )


def test_the_sentence_this_check_was_written_for_is_caught() -> None:
    """**The negative**, and it is `docs/sensor-baseline.md`'s own line as it
    stood at 1fffca3."""
    offenders = misdescriptions(
        "Nothing in this repository measures, or can measure, that figure — the\n"
        "simulator emits a nine-float proprioception stream and that is the whole\n"
        "of its input.\n"
    )
    assert len(offenders) == 1


def test_the_other_two_names_are_caught_as_well() -> None:
    """`nine-float CSV` and `proprioceptive stream` name the same wrong thing."""
    assert misdescriptions("compared against a gzipped nine-float CSV.\n")
    assert misdescriptions("the artifact against a proprioceptive stream.\n")


def test_naming_the_proprioceptive_columns_is_not_a_misdescription() -> None:
    """**The positive control.** The subset genuinely is proprioception — the
    incumbent comparison prices exactly it, on both sides — so the check must not
    fire on a document saying so."""
    assert not misdescriptions(
        "A /joint_states bag holds the five proprioceptive columns; the gzipped\n"
        "CSV holds all 24. This comparison prices proprioception only, on both\n"
        "sides, and Claim 3 is about proprioception-only evidence.\n"
    )


# --- check 2: the counts, and the disclosure --------------------------------


def counts_are_the_schemas(text: str) -> tuple[str, list[str]]:
    """Verdict on whether every count `text` states about the stream is real.

    Three-valued, and the third does not resolve to the first: a document that
    never names the baseline is COULD-NOT-EVALUATE, because deleting the
    description would otherwise be the cheapest way to green.
    """
    checked = 0
    wrong: list[str] = []
    for unit in units(text):
        if not BASELINE_SUBJECT.search(unit):
            continue
        checked += 1
        claimed = {_as_int(token) for token in COUNT_CLAIM.findall(unit)}
        if claimed - LEGITIMATE_COUNTS:
            wrong.append(unit)
    if not checked:
        return COULD_NOT_EVALUATE, []
    return (DISAGREE if wrong else AGREE), wrong


def states_what_the_stream_holds(text: str) -> str:
    """Verdict on whether a document that names the baseline says what it holds."""
    if not any(BASELINE_SUBJECT.search(unit) for unit in units(text)):
        return COULD_NOT_EVALUATE
    return AGREE if COMPOSITION.search(normalise(text)) else DISAGREE


@pytest.mark.parametrize("doc,path", CORPUS)
def test_every_count_stated_about_the_priced_stream_is_the_schemas(
    doc: str, path: Path
) -> None:
    """A count is a fact about a schema, and this repository has the schema."""
    verdict, wrong = counts_are_the_schemas(path.read_text(encoding="utf-8"))
    assert verdict != DISAGREE, (
        f"{doc} states a count for the priced stream that is not the schema's "
        f"in {len(wrong)} place(s):\n"
        + "\n".join(f"  - {unit[:180]}" for unit in wrong)
        + f"\nThe {PRICED_FIXTURE} schema is {len(HEADER)} columns: "
        f"{len(PROPRIOCEPTIVE)} proprioceptive and {len(LAYER_B)} Layer B."
    )


@pytest.mark.parametrize("doc,path", CORPUS)
def test_a_document_naming_the_baseline_says_what_it_holds(
    doc: str, path: Path
) -> None:
    """The Layer B content travels with the baseline, in every document that
    names it. Naming the file without naming what is in it is how the wrong
    label survived four milestones."""
    assert states_what_the_stream_holds(path.read_text(encoding="utf-8")) != DISAGREE, (
        f"{doc} names the stream the artifact is priced against but never says "
        f"what it holds. State it: {len(HEADER)} columns for the "
        f"{PRICED_FIXTURE} fixture, {len(LAYER_B)} of them Layer B."
    )


def test_the_documents_describing_the_baseline_are_the_ones_expected() -> None:
    """**SILENCE IS NOT A PASS.** Both checks above go green on a document that
    stopped describing the baseline, so this names where it is described. A loss
    needs a look: the baseline is what a published ratio is a ratio *against*."""
    describing = {
        doc
        for doc, path in CORPUS
        if states_what_the_stream_holds(path.read_text(encoding="utf-8"))
        != COULD_NOT_EVALUATE
    }
    assert describing == set(DOCS_DESCRIBING_THE_BASELINE), (
        "the set of documents describing the baseline has moved: gained "
        f"{sorted(describing - DOCS_DESCRIBING_THE_BASELINE)}, lost "
        f"{sorted(DOCS_DESCRIBING_THE_BASELINE - describing)}. A gain needs "
        "adding here — it is a new place the baseline is introduced, and it has "
        "to say what the stream holds; a loss means a document stopped saying "
        "what its ratio is against."
    )


# --- the negatives for check 2 ----------------------------------------------


def test_a_wrong_column_count_is_caught() -> None:
    """**The negative this check exists for**: the count that described an empty
    scene, attached to a fixture that has three obstacles in it."""
    verdict, wrong = counts_are_the_schemas(
        "The artifact is ~40x larger than a gzipped copy of the raw state\n"
        "stream — nine floats, four of them the human's.\n"
    )
    assert verdict == DISAGREE
    assert len(wrong) == 1


def test_the_schemas_counts_pass() -> None:
    """The positive control, across a line break, since the documents wrap."""
    verdict, wrong = counts_are_the_schemas(
        "compared against a gzipped copy of the raw state CSV — 24 columns for\n"
        "the priced fixture, 19 of them Layer B, beside 5 proprioceptive ones.\n"
    )
    assert (verdict, wrong) == (AGREE, [])


def test_a_document_that_never_names_the_baseline_is_could_not_evaluate() -> None:
    """The third outcome, and it stays third."""
    assert counts_are_the_schemas("The chain is append-only.\n")[0] == (
        COULD_NOT_EVALUATE
    )
    assert states_what_the_stream_holds("The chain is append-only.\n") == (
        COULD_NOT_EVALUATE
    )


def test_naming_the_baseline_without_its_content_is_caught() -> None:
    """**The negative for the disclosure check.** True, measured, and silent
    about the fact that most of what it measures is Layer B."""
    assert states_what_the_stream_holds(
        "The artifact is ~40x larger than a gzipped copy of the state stream.\n"
    ) == DISAGREE


def test_the_composition_must_be_both_counts_together() -> None:
    """Half the statement is not the statement: a document that says how wide the
    stream is without saying how much of it is Layer B has disclosed nothing the
    label got wrong."""
    assert states_what_the_stream_holds(
        "The artifact is ~40x larger than a gzipped copy of the 24-column state\n"
        "stream.\n"
    ) == DISAGREE


# --- check 3: the figures ---------------------------------------------------


@pytest.fixture(scope="module")
def priced_stream(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The fixture stream itself, at the seed the documents quote.

    Generated rather than checked in, and generated by the CLI the documents name,
    so this test measures what a reader running that command would measure.
    """
    out = tmp_path_factory.mktemp("priced") / f"{PRICED_FIXTURE}.csv"
    subprocess.run(
        [
            sys.executable, "-m", "reg.sim",
            "--scenario", PRICED_FIXTURE,
            "--seed", str(PRICED_SEED),
            "--out", str(out),
        ],
        check=True,
        capture_output=True,
    )
    return out


def _measured(stream: Path) -> tuple[int, int, int]:
    """(frames, full-stream gzipped bytes, proprioception-only gzipped bytes)."""
    rows = [
        line
        for line in stream.read_text(encoding="utf-8").splitlines()
        if not line.startswith("#")
    ]
    header = next(csv.reader(rows))
    assert header == HEADER, (
        "the fixture stream's header is not the schema these tests derived from "
        f"the scenario:\n  measured: {header}\n  derived:  {HEADER}"
    )
    return (
        len(rows) - 1,
        gzip_bytes(stream),
        gzip_bytes_of_columns(stream, proprioceptive_columns(header)),
    )


def test_the_published_proprioception_only_figure_is_the_measured_one(
    priced_stream: Path,
) -> None:
    """The figure added beside Gorilla's 1.37 B/point, pinned to a measurement.

    No constant here either: bytes, frames and B/frame are all read out of the
    documents, so a document edited to match a regression fails exactly as a
    regression does.
    """
    frames, _, slice_bytes = _measured(priced_stream)
    quoted = {
        doc: SLICE_FIGURE.findall(normalise(path.read_text(encoding="utf-8")))
        for doc, path in CORPUS
    }
    quoting = {doc for doc, found in quoted.items() if found}
    assert quoting, (
        "no document publishes the proprioception-only figure any more. It is "
        "the only like-for-like against a time-series compressor, and dropping "
        "it leaves the ~21 B/frame full-stream figure beside Gorilla's "
        "per-point one with nothing saying they are different measurements."
    )
    for doc, found in quoted.items():
        for raw_bytes, raw_frames, raw_per_frame in found:
            assert int(raw_bytes.replace(",", "")) == slice_bytes, (
                f"{doc} publishes {raw_bytes} B for the proprioception-only "
                f"slice; measured {slice_bytes} B."
            )
            assert int(raw_frames.replace(",", "")) == frames, (
                f"{doc} publishes {raw_frames} frames; measured {frames}."
            )
            assert float(raw_per_frame) == round(slice_bytes / frames, 1), (
                f"{doc} publishes {raw_per_frame} B/frame; measured "
                f"{slice_bytes / frames:.4f}."
            )


def test_the_published_full_stream_figure_still_measures_what_it_says(
    priced_stream: Path,
) -> None:
    """~21 B/frame does not move — issue #123 changed the sentence around it, not
    the number. It is the whole 24-column stream, which is the point: it is not a
    per-value figure and does not sit beside one."""
    frames, full_bytes, slice_bytes = _measured(priced_stream)
    quoted = {
        float(value)
        for _, path in CORPUS
        for value in FULL_STREAM_FIGURE.findall(
            normalise(path.read_text(encoding="utf-8"))
        )
    }
    measured = round(full_bytes / frames)
    assert measured in {round(value) for value in quoted}, (
        f"the full 24-column stream measures {full_bytes / frames:.2f} B/frame "
        f"and no document publishes that figure; they publish {sorted(quoted)}."
    )
    assert slice_bytes < full_bytes, (
        "the proprioceptive subset gzips to at least what the whole stream does, "
        "which would mean the 19 Layer B columns cost nothing — check "
        "proprioceptive_columns, not the documents."
    )
