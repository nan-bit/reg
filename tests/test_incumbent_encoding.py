"""The incumbent encoding, and whether it can be got wrong quietly.

`reg.bench` prices the artifact against a gzipped CSV. Nobody retains a gzipped
CSV; practitioners retain rosbag2, in MCAP. Issue #117 added a second baseline so
the published comparison is not against a format no one runs.

The encoder is a **projection computed from specification** — no `mcap` library,
no `zstd`, because this project adds no dependency for a baseline. That makes it
exactly the kind of number that can drift without anyone noticing, so these tests
hold both presets to their published figures, to the arithmetic the constants
state, and to the failure modes that would each have made the incumbent look
cheaper than it is.

Two presets are priced because rosbag2 has two: `mcap_default`, which is what a
practitioner gets without choosing, and `mcap_compressed_nocrc`, which is the
like-for-like against a gzipped baseline. Pricing one of them is how a comparison
comes out whichever way its author wanted, so the tests below hold both.

The reporter has a negative of its own: fed an incumbent cheaper than the
baseline, it must say so in words. A comparison that can only flatter is not a
measurement, and that case is the one no fixture in this repository produces.

Issue #220 added the second half of the file, and the difference is what is being
priced rather than how. The comparison above covers five of the fixture's
twenty-four columns; the retention headline is measured over all twenty-four, so
the two ratios cover different content and do not divide. The tests from *THE
SAME INCUMBENT, OVER THE WHOLE STREAM* down price the same encoder over the other
nineteen columns and hold the one ratio that replaces both — including the
arrangement decision behind it, which is chosen by measurement and chosen to be
the cheapest, because the cheapest bag is the one this project's ratio is largest
against.
"""

from __future__ import annotations

import csv
import gzip
import inspect
import re
import struct
from dataclasses import replace
from pathlib import Path

import pytest

from reg import bench
from reg.bench import (
    ARTIFACT_LARGER,
    ARTIFACT_LEVEL,
    ARTIFACT_SMALLER,
    CDR_ENCAPSULATION,
    CLAIM_1_STATUS_MUST_CHANGE,
    CLAIM_1_STATUS_STANDS,
    CLAIM_1_STATUS_UNDECIDED,
    GZIP_COMPRESSLEVEL,
    GZIP_MTIME,
    INCUMBENT_CHEAPER,
    INCUMBENT_DEARER,
    INCUMBENT_LEVEL,
    LAYER_B_OPTIONS,
    MCAP_MESSAGE_INDEX_PER_MESSAGE,
    MCAP_MESSAGE_RECORD_OVERHEAD,
    MCAP_PRESETS,
    MCAP_SIZE_MEASUREMENTS,
    MCAP_STRUCTURAL_CHECKS,
    MCAP_VALIDATION_PROVENANCE,
    MCAP_VALIDATION_TOLERANCE,
    OUTSIDE_TOLERANCE,
    PROJECTION_DRIFTED,
    PROJECTION_HOLDS,
    WITHIN_TOLERANCE,
    BenchError,
    FullContentComparison,
    IncumbentComparison,
    LayerBTopicOption,
    McapSizeMeasurement,
    McapStructuralCheck,
    StreamEntity,
    cheapest_layer_b_option,
    compare_full_content,
    compare_incumbent,
    full_content_mcap_bytes,
    full_content_report,
    gzip_bytes,
    gzip_bytes_of_columns,
    incumbent_report,
    joint_state_cdr,
    layer_b_columns,
    layer_b_mcap_bytes,
    layer_b_option,
    marker_cdr,
    mcap_joint_states_bytes,
    mcap_preset,
    mcap_size_measurement,
    pose_stamped_cdr,
    project_for_topics,
    projection_drift,
    proprioceptive_columns,
    stream_entities,
    tf_message_cdr,
    uncharged_layer_b_columns,
)

REPO = Path(__file__).resolve().parents[1]

DEFAULT = "mcap_default"
COMPRESSED = "mcap_compressed_nocrc"

#: What the fixture holds. 251 frames of the two-joint `declared_violation` run
#: at 50 Hz, one `/joint_states` message each, 96 B of CDR payload per message.
MESSAGES = 251
PAYLOAD = 96

#: The published figures, republished by issue #117 from the corrected
#: configuration. `docs/sensor-baseline.md` carries them and their arithmetic.
DEFAULT_BYTES = 35893
COMPRESSED_BYTES = 11685
BASELINE_BYTES = 3053


def _header(path: Path) -> list[str]:
    rows = [l for l in path.read_text().splitlines() if not l.startswith("#")]
    return next(csv.reader(rows))


@pytest.fixture(scope="module")
def stream(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A real fixture stream, not a synthetic one.

    The joint values have to be real: the whole comparison turns on how well
    each encoding compresses slowly-varying floats, and made-up values would
    price a stream no robot produces.
    """
    import subprocess
    import sys

    out = tmp_path_factory.mktemp("incumbent") / "dv.csv"
    subprocess.run(
        [sys.executable, "-m", "reg.sim", "--scenario", "declared_violation",
         "--seed", "0", "--out", str(out)],
        check=True, capture_output=True,
    )
    return out


def _message_records(path: Path) -> bytes:
    """The Message records alone, assembled here rather than read out of `reg`.

    The point of writing it a second time is that the index arithmetic below is
    then checked against something, rather than against the same expression that
    produced it.
    """
    rows = [l for l in path.read_text().splitlines() if not l.startswith("#")]
    reader = csv.reader(rows)
    header = next(reader)
    joints = sorted(
        {c.split("_", 1)[1] for c in proprioceptive_columns(header)
         if c.startswith("q_")},
        key=int,
    )
    names = [f"joint_{j}" for j in joints]
    ti = header.index("t")
    qi = [header.index(f"q_{j}") for j in joints]
    di = [header.index(f"qd_{j}") for j in joints]
    out = bytearray()
    for seq, row in enumerate(reader):
        t_s = float(row[ti])
        payload = joint_state_cdr(
            t_s, [float(row[i]) for i in qi], [float(row[i]) for i in di], names
        )
        ns = int(t_s * 1_000_000_000)
        record = struct.pack("<HIQQ", 0, seq, ns, ns) + payload
        out += b"\x05" + struct.pack("<Q", len(record)) + record
    return bytes(out)


def _gz(data: bytes) -> int:
    return len(gzip.compress(data, compresslevel=GZIP_COMPRESSLEVEL,
                             mtime=GZIP_MTIME))


# --- both presets, and neither of them chosen for us ------------------------


def test_the_cdr_payload_is_the_size_the_idl_says(stream: Path) -> None:
    """96 bytes for a two-joint arm: derived from the IDL, field by field.

    4 encapsulation + 8 Time + 5->8 empty frame_id + name[2] + position[2] +
    velocity[2] + empty effort, with CDR's own alignment. A change here is a
    change to what the incumbent costs per message and must be deliberate.
    """
    payload = joint_state_cdr(1.0, [0.1, 0.2], [0.3, 0.4], ["joint_0", "joint_1"])
    assert len(payload) == PAYLOAD
    assert payload[:CDR_ENCAPSULATION] == b"\x00\x01\x00\x00"


def test_both_rosbag2_presets_are_priced_and_each_cites_its_source() -> None:
    """Two presets, named after rosbag2's, each carrying what it claims.

    The default preset is the one that decides whether this comparison is about
    what practitioners retain. An entry whose `what` says nothing is a claim
    about somebody else's software with no source, which is the same silence as
    no entry.
    """
    names = [p.name for p in MCAP_PRESETS]
    assert names == [DEFAULT, COMPRESSED]
    assert mcap_preset(DEFAULT).compressed is False
    assert mcap_preset(COMPRESSED).compressed is True
    for preset in MCAP_PRESETS:
        assert "mcap.dev" in preset.what, f"{preset.name} cites no source"


def test_the_preset_has_no_default_and_an_unknown_one_is_refused(
    stream: Path,
) -> None:
    """THE NEGATIVE for the configuration. Neither call may guess.

    The two presets differ by a factor of three on the same messages, so a
    default would let this module pick its own answer, and a near-miss name
    silently resolving to the compressed preset would publish a real number
    under the name of a configuration nobody encoded.
    """
    for func in (mcap_joint_states_bytes, compare_incumbent):
        assert inspect.signature(func).parameters["preset"].default is (
            inspect.Parameter.empty
        ), f"{func.__name__} invented a default preset"
    with pytest.raises(BenchError, match="not an MCAP preset"):
        mcap_joint_states_bytes(stream, preset="mcap_compressed")
    with pytest.raises(BenchError, match="not an MCAP preset"):
        mcap_preset("zstd_fast")


# --- the figures, held to the arithmetic the constants state ----------------


def test_the_two_presets_and_the_baseline_are_the_published_figures(
    stream: Path,
) -> None:
    """The finding, and the reason #117 exists.

    Held to the byte. If any of these moves, either the encoder changed or the
    fixture did, and both are findings rather than numbers to update.
    """
    default = mcap_joint_states_bytes(stream, preset=DEFAULT)
    compressed = mcap_joint_states_bytes(stream, preset=COMPRESSED)
    gz = gzip_bytes_of_columns(stream, proprioceptive_columns(_header(stream)))
    assert default == DEFAULT_BYTES, f"mcap_default is {default} B"
    assert compressed == COMPRESSED_BYTES, f"mcap_compressed_nocrc is {compressed} B"
    assert gz == BASELINE_BYTES, f"gzipped proprioception is {gz} B"
    assert default > compressed > gz, (
        "the incumbent encoding came out cheaper than the gzipped CSV. That "
        "would retire the finding this comparison was built to publish, and it "
        "should be read as a bug in the encoder before it is read as a result."
    )


def test_the_default_preset_is_the_records_and_the_index_and_nothing_else(
    stream: Path,
) -> None:
    """The uncompressed preset stated as arithmetic, not as a golden number.

    251 x (31 framing + 96 payload) + 251 x 16 of message index. Both terms are
    per-message and both are named constants, so this fails if either constant
    moves and it fails if the index term is dropped.
    """
    records = MESSAGES * (MCAP_MESSAGE_RECORD_OVERHEAD + PAYLOAD)
    index = MESSAGES * MCAP_MESSAGE_INDEX_PER_MESSAGE
    assert len(_message_records(stream)) == records
    assert mcap_joint_states_bytes(stream, preset=DEFAULT) == records + index


def test_the_message_index_is_charged_at_full_width_under_compression(
    stream: Path,
) -> None:
    """THE INDEX NEGATIVE. MessageIndex records sit outside the chunk.

    The spec puts them after the chunk they index so a reader can seek without
    decompressing, so they are not compressed with the messages. Folding them
    inside the compressed body instead would come to 9,209 B against the 11,685
    B they actually cost — a 21% discount on the incumbent, from an arrangement
    the format does not have.
    """
    records = _message_records(stream)
    index = MESSAGES * MCAP_MESSAGE_INDEX_PER_MESSAGE
    compressed = mcap_joint_states_bytes(stream, preset=COMPRESSED)
    assert compressed == _gz(records) + index
    inside = _gz(records + b"\x00" * index)
    assert inside < compressed, (
        "compressing the index with the body did not come out cheaper, so this "
        "test is no longer checking anything"
    )
    assert compressed != inside


# --- the ways it could go wrong quietly, each of which flatters the incumbent


def test_compression_is_applied_to_exactly_one_preset(stream: Path) -> None:
    """THE NEGATIVE that started this file, now pointed at both presets.

    It was the first bug the encoder had: the message stream was returned
    uncompressed and the ratio came out 10.44x instead of 2.51x. Compressing
    the default preset is the mirror of it — the one rosbag2 actually writes is
    uncompressed, and gzipping it here would have understated the incumbent by
    two thirds while looking like the careful choice.
    """
    raw_records = MESSAGES * (MCAP_MESSAGE_RECORD_OVERHEAD + PAYLOAD)
    compressed = mcap_joint_states_bytes(stream, preset=COMPRESSED)
    default = mcap_joint_states_bytes(stream, preset=DEFAULT)
    assert compressed < raw_records, (
        f"{compressed} B is at or above the {raw_records} B the same records "
        "occupy uncompressed, so the compression this preset opts into is not "
        "being applied."
    )
    assert default > raw_records, (
        f"{default} B is at or below the {raw_records} B of uncompressed "
        "records, so something is compressing the preset that rosbag2 writes "
        "uncompressed."
    )


def test_the_framing_is_not_written_as_zero_bytes(stream: Path) -> None:
    """THE SECOND NEGATIVE, and the second bug this encoder had.

    Writing the 31 framing bytes as nulls drops the compressed preset to 9,370 B
    from 11,685 B, because a run of zeros compresses to nothing while a sequence
    number and two advancing timestamps do not. A bag never gets that discount.
    """
    compressed = mcap_joint_states_bytes(stream, preset=COMPRESSED)
    assert compressed > 10000, (
        f"{compressed} B is at or below what this stream costs when the MCAP "
        "framing is written as null bytes. Real framing carries a sequence "
        "number and two timestamps that advance, and they do not compress away."
    )


# --- the reporter, and the case that comes out against this project ---------


def test_the_reporter_says_the_incumbent_is_dearer_when_it_is(
    stream: Path,
) -> None:
    """The healthy case, on both presets, in words rather than only in a ratio."""
    report = incumbent_report(stream)
    for preset in (DEFAULT, COMPRESSED):
        comparison = compare_incumbent(stream, preset=preset)
        assert comparison.verdict == INCUMBENT_DEARER
        assert comparison.messages == MESSAGES
        assert "DEARER" in comparison.sentence()
        assert preset in report
    assert f"{DEFAULT_BYTES:,}" in report and f"{COMPRESSED_BYTES:,}" in report


def test_the_reporter_says_it_in_words_when_the_baseline_is_smaller() -> None:
    """THE NEGATIVE THIS COMPARISON EXISTS FOR (#117 acceptance criterion 4).

    Fed an incumbent cheaper than the baseline this project loses against, the
    reporter must say *cheaper* in words. No fixture here produces that case, so
    it is constructed: 1,000 B of bag against the 3,053 B of gzipped CSV.

    A ratio alone would not do it. `0.33x` and `3.83x` look alike at a glance
    and mean opposite things about whether the published baseline is soft, and a
    reader who has to work out the direction from a number is a reader who will
    quote the number without it.
    """
    against = IncumbentComparison(
        preset=DEFAULT, incumbent_bytes=1000,
        baseline_bytes=BASELINE_BYTES, messages=MESSAGES,
    )
    assert against.verdict == INCUMBENT_CHEAPER
    assert against.ratio < 1.0
    sentence = against.sentence()
    assert "CHEAPER" in sentence
    assert "result against this project" in sentence
    assert "1,000 B" in sentence and "3,053 B" in sentence


def test_a_tie_is_not_rounded_towards_the_finding() -> None:
    """Equal bytes is neither dearer nor a rounding error in this project's favour."""
    level = IncumbentComparison(
        preset=COMPRESSED, incumbent_bytes=BASELINE_BYTES,
        baseline_bytes=BASELINE_BYTES, messages=MESSAGES,
    )
    assert level.verdict == INCUMBENT_LEVEL
    assert "SAME" in level.sentence()
    assert "does not stand" in level.sentence()


# --- could-not-evaluate never resolves to a pass ----------------------------


def test_a_comparison_over_nothing_is_refused() -> None:
    """A side that came out at zero is an encoding that did not run."""
    with pytest.raises(BenchError, match="did not run"):
        IncumbentComparison(preset=DEFAULT, incumbent_bytes=0,
                            baseline_bytes=BASELINE_BYTES, messages=MESSAGES)
    with pytest.raises(BenchError, match="did not run"):
        IncumbentComparison(preset=DEFAULT, incumbent_bytes=DEFAULT_BYTES,
                            baseline_bytes=0, messages=MESSAGES)
    with pytest.raises(BenchError, match="prices nothing"):
        IncumbentComparison(preset=DEFAULT, incumbent_bytes=DEFAULT_BYTES,
                            baseline_bytes=BASELINE_BYTES, messages=0)


def test_a_stream_with_no_joint_columns_is_refused(tmp_path: Path) -> None:
    """Silence is could-not-evaluate. A zero would read as a free encoding."""
    p = tmp_path / "noq.csv"
    p.write_text("t,human_x,human_y\n0.0,1.0,2.0\n0.02,1.1,2.1\n")
    with pytest.raises(BenchError, match="no q_. columns"):
        mcap_joint_states_bytes(p, preset=DEFAULT)


def test_an_empty_stream_is_refused(tmp_path: Path) -> None:
    """A stream with a header and no frames is a step that did not run."""
    p = tmp_path / "empty.csv"
    p.write_text("t,q_0,qd_0\n")
    with pytest.raises(BenchError, match="no frames"):
        mcap_joint_states_bytes(p, preset=COMPRESSED)
    with pytest.raises(BenchError, match="no frames"):
        compare_incumbent(p, preset=COMPRESSED)


def test_a_narrowed_subset_is_refused_rather_than_silently_shrunk(
    stream: Path,
) -> None:
    """Asking for columns a stream lacks must fail, not price what is present.

    Narrowing to the intersection would compare proprioception on one side
    against whatever survived on the other and call them the same measurement.
    """
    with pytest.raises(BenchError, match="missing"):
        gzip_bytes_of_columns(stream, ["t", "q_0", "q_99"])


def test_mismatched_joint_arrays_are_refused() -> None:
    """A JointState no robot publishes prices nothing."""
    with pytest.raises(BenchError, match="velocity"):
        joint_state_cdr(0.0, [0.1, 0.2], [0.3], ["joint_0", "joint_1"])
    with pytest.raises(BenchError, match="joint name"):
        joint_state_cdr(0.0, [0.1, 0.2], [0.3, 0.4], ["joint_0"])


def test_the_proprioceptive_subset_excludes_every_entity_column(
    stream: Path,
) -> None:
    """The Layer B asymmetry, enforced rather than described.

    The stream carries the human's ground-truth position and velocity. No
    robot's `/joint_states` does. If an entity column ever enters this subset
    the comparison stops being like-for-like and starts flattering the artifact.
    """
    prop = proprioceptive_columns(_header(stream))
    assert prop, "no proprioceptive columns found; the check cannot evaluate"
    leaked = [c for c in prop if c.startswith(("human_", "obs_", "entity"))]
    assert not leaked, f"entity columns leaked into the proprioceptive subset: {leaked}"


# --- the documents that quote it --------------------------------------------

#: Every document in the corpus, keyed the way the failure messages read.
CORPUS: tuple[tuple[str, Path], ...] = (
    ("README.md", REPO / "README.md"),
    *((path.name, path) for path in sorted((REPO / "docs").glob("*.md"))),
)

#: Where the incumbent ratio is published. Pinned, because every check below
#: goes green on a document that quietly stopped quoting it, and a figure that
#: disappears from the front page is a bigger change than one that moves.
DOCS_PUBLISHING_THE_RATIO = frozenset(
    {"README.md", "plan.md", "prior-art.md", "retention.md", "sensor-baseline.md"}
)

#: Where the byte figures behind it are published, which is fewer places: a
#: ratio travels, an arithmetic does not.
DOCS_PUBLISHING_THE_BYTES = frozenset({"retention.md", "sensor-baseline.md"})

#: The figures this issue retired. They are not banned — `prior-art.md` is a
#: dated survey and its passes are corrected by addition, so the old number has
#: to survive where the correction is — but a document quoting one without
#: saying it is retired is publishing it.
RETIRED = re.compile(r"2\.51x|7,669")
RETIRED_IS_MARKED = re.compile(r"supersed", re.IGNORECASE)


def _quoting(pattern: str) -> set[str]:
    return {
        doc for doc, path in CORPUS if pattern in path.read_text(encoding="utf-8")
    }


def test_every_document_quoting_the_incumbent_quotes_the_measured_figure(
    stream: Path,
) -> None:
    """The published ratios, re-derived from the encoder on every run.

    No constant is compared against another constant here: the strings searched
    for are formatted from a live measurement of the fixture, so a document
    edited to match a regression fails exactly as a regression does, and a
    document left behind when the encoder moves fails too.
    """
    gz = gzip_bytes_of_columns(stream, proprioceptive_columns(_header(stream)))
    ratios = {
        preset: mcap_joint_states_bytes(stream, preset=preset) / gz
        for preset in (DEFAULT, COMPRESSED)
    }
    for preset, ratio in ratios.items():
        assert _quoting(f"{ratio:.2f}x") == set(DOCS_PUBLISHING_THE_RATIO), (
            f"the documents quoting {ratio:.2f}x for {preset} are not the ones "
            f"expected: {sorted(_quoting(f'{ratio:.2f}x'))}. A document that "
            "gained the figure belongs in DOCS_PUBLISHING_THE_RATIO; one that "
            "lost it either dropped the comparison or is quoting a stale number."
        )
    for preset, published in (
        (DEFAULT, DEFAULT_BYTES), (COMPRESSED, COMPRESSED_BYTES)
    ):
        measured = mcap_joint_states_bytes(stream, preset=preset)
        assert _quoting(f"{measured:,} B") == set(DOCS_PUBLISHING_THE_BYTES), (
            f"{preset} measures {measured:,} B and the documents publishing "
            f"that are {sorted(_quoting(f'{measured:,} B'))}, not "
            f"{sorted(DOCS_PUBLISHING_THE_BYTES)}."
        )


def test_the_retired_figure_is_quoted_only_where_it_is_marked_retired() -> None:
    """THE NEGATIVE for the republication. 2.51x may stand, unlabelled it may not.

    `prior-art.md` keeps it because a dated pass is evidence of what was believed
    on its date and is corrected by addition. Everywhere else it is simply the
    wrong number, and either way a reader meeting it has to meet the word
    `superseded` in the same document.
    """
    for doc, path in CORPUS:
        text = path.read_text(encoding="utf-8")
        if RETIRED.search(text):
            assert RETIRED_IS_MARKED.search(text), (
                f"{doc} quotes 2.51x or 7,669 B — the incumbent figures issue "
                "#117 retired — without saying anywhere that they are "
                "superseded. Republish it from the measurement, or mark it."
            )


# ==========================================================================
# THE SAME INCUMBENT, OVER THE WHOLE STREAM (issue #220).
#
# Everything above prices five of the fixture's twenty-four columns, and the
# retention headline is measured against a gzipped CSV of all twenty-four. Two
# ratios over different content do not compose: `~40x` divided by `3.83x` is a
# number about nothing. So the same encoder is run over the other nineteen
# columns and the three figures then divide — `artifact / gzipped CSV` over
# `MCAP / gzipped CSV` is `artifact / MCAP`, all of them over the same stream.
#
# WHAT THE TESTS BELOW HAVE TO HOLD, BEYOND THE BYTES. The number moves with a
# *decision* — what a ROS 2 system publishes for the world half — and a decision
# with a number attached is exactly the thing that can be made quietly in the
# direction its author wanted. So the arrangement is chosen by measurement and
# the choice is the **cheapest**, which is the one most favourable to the
# incumbent and therefore the one hardest for this project. Three of the tests
# below exist only to keep that true: the chosen arrangement is the minimum, a
# tie is refused rather than broken, and the rejected `MarkerArray` alternative
# is measured against the chosen one rather than argued away.
#
# WHERE THE ARTIFACT SIZE COMES FROM, AND WHY IT IS NOT MEASURED HERE. The
# corrected ratio needs the build `~40x` is measured on, which is a 3,000-frame
# `reg.graph.build` — two minutes of wall clock. `tests/test_published_figures.py`
# already pays that cost once per session and pins `docs/retention.md`'s
# `artifact on disk` row against it, in both directions. So this module reads the
# artifact side out of that row rather than rebuilding it: the number is held to
# the code by the module whose job that is, and the incumbent side, which is what
# issue #220 actually adds, is measured live here on every run.
# ==========================================================================

TF = "tf_tree"
POSE = "pose_per_entity"

#: The Layer B half, under each preset and each arrangement. `tf_tree` is smaller
#: at both, which is why it is chosen at both.
TF_BYTES = {DEFAULT: 1209000, COMPRESSED: 170628}
POSE_BYTES = {DEFAULT: 1476000, COMPRESSED: 315225}

#: The `/joint_states` half over the same 3,000-frame stream, and the whole bag.
JOINT_STATES_BYTES = {DEFAULT: 429000, COMPRESSED: 136500}
FULL_BYTES = {DEFAULT: 1638000, COMPRESSED: 307128}

#: The headline's own baseline: a gzipped CSV of all 24 columns of the same run.
FULL_GZIP_CSV_BYTES = 64652

#: The human and three obstacles. One `/tf` message a frame holds all four; the
#: per-entity arrangement needs four messages for the same content.
ENTITIES = 4
FULL_FRAMES = 3000

#: Which document publishes which figure. Pinned for the reason
#: `DOCS_PUBLISHING_THE_RATIO` is: every check below goes green on a document
#: that quietly stopped quoting the number, and a figure that vanishes from the
#: front page is a larger change than one that moves. The sets differ because
#: the documents differ — `README.md` carries the ratio against the artifact and
#: not the encoding ratios behind it, `sensor-baseline.md` carries the encoding
#: and hands the artifact comparison to `retention.md`, and `prior-art.md` carries
#: exactly what its dated correction needed to state.
DOCS_PUBLISHING: dict[str, frozenset[str]] = {
    "artifact_over_bag_compressed": frozenset(
        {"README.md", "plan.md", "prior-art.md", "retention.md"}
    ),
    "artifact_over_bag_default": frozenset({"README.md", "plan.md", "retention.md"}),
    "bag_over_gzip_default": frozenset(
        {"plan.md", "retention.md", "sensor-baseline.md"}
    ),
    "bag_over_gzip_compressed": frozenset(
        {"plan.md", "prior-art.md", "retention.md", "sensor-baseline.md"}
    ),
    "artifact_over_gzip": frozenset({"plan.md", "prior-art.md", "retention.md"}),
}

#: The whole-stream byte counts, and the shorter list of documents that publish
#: them: a ratio travels, an arithmetic does not.
DOCS_PUBLISHING_THE_FULL_BYTES = frozenset({"retention.md", "sensor-baseline.md"})
DOCS_PUBLISHING_THE_HALVES = frozenset({"sensor-baseline.md"})

#: `docs/retention.md`'s Layer-A comparison row, which is where the artifact side
#: of the corrected ratio is read from. Anchored on the label rather than on
#: position: a row found by counting rows moves the first time somebody adds one.
ARTIFACT_ON_DISK = re.compile(
    r"^\|\s*artifact on disk\s*\|\s*\**([\d,]+)\s*B\**\s*\|", re.MULTILINE
)


def published_artifact_bytes() -> int:
    """The build `~40x` is measured on, read out of the document that publishes it.

    Not a constant in this file and not a second build. A missing row raises
    rather than falling back to a plausible number: an invented artifact size
    would produce a corrected ratio for a build nobody made, and the corrected
    ratio is the figure this issue exists to publish.
    """
    match = ARTIFACT_ON_DISK.search(
        (REPO / "docs" / "retention.md").read_text(encoding="utf-8")
    )
    assert match is not None, (
        "docs/retention.md publishes no `artifact on disk` row, so the artifact "
        "side of the corrected ratio cannot be read. That is a "
        "could-not-evaluate, not a licence to pick a number: "
        "tests/test_published_figures.py is what holds that row to the code, and "
        "with the row gone nothing here is comparing against a measurement."
    )
    return int(match.group(1).replace(",", ""))


@pytest.fixture(scope="module")
def full_stream(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The 3,000-frame `long_run` stream the retention figures are measured on.

    A different fixture from `stream` above, and deliberately: the encoding ratio
    is a ratio of per-message costs and any fixture shows it, but the corrected
    ratio is against an artifact whose fixed schema-and-index cost only stops
    dominating at this length. Pricing the incumbent on the 251-frame fixture and
    dividing it into a 3,000-frame artifact would be the composition error this
    section exists to fix, committed one level down.
    """
    import subprocess
    import sys

    out = tmp_path_factory.mktemp("full") / "long_run.csv"
    subprocess.run(
        [sys.executable, "-m", "reg.sim", "--scenario", "long_run_3000",
         "--seed", "0", "--out", str(out)],
        check=True, capture_output=True,
    )
    return out


def _entities(path: Path) -> tuple[StreamEntity, ...]:
    rows = [l for l in path.read_text().splitlines() if not l.startswith("#")]
    reader = csv.reader(rows)
    header = next(reader)
    return stream_entities(header, next(reader))


# --- the decision, and that it was made by measurement ----------------------


def test_both_layer_b_arrangements_are_priced_and_each_cites_its_source() -> None:
    """Two arrangements, each carrying the claim it makes about somebody's stack.

    An entry whose `what` says nothing is a decision with no reason attached,
    which is the same silence as no entry — and this decision moves the published
    ratio by a fifth.
    """
    names = [o.name for o in LAYER_B_OPTIONS]
    assert names == [TF, POSE]
    assert layer_b_option(TF).per_entity is False
    assert layer_b_option(POSE).per_entity is True
    for option in LAYER_B_OPTIONS:
        assert "docs.ros.org" in option.what, f"{option.name} cites no source"


def test_neither_the_preset_nor_the_arrangement_has_a_default(
    full_stream: Path,
) -> None:
    """THE NEGATIVE for both decisions. Neither call may guess at either.

    A near-miss arrangement name silently resolving to the other would publish a
    real number under the name of a topic layout nobody encoded, which is the
    invented default in its most expensive form: the figure would be real and its
    label false.
    """
    parameters = inspect.signature(layer_b_mcap_bytes).parameters
    for name in ("preset", "option"):
        assert parameters[name].default is inspect.Parameter.empty, (
            f"layer_b_mcap_bytes invented a default {name}"
        )
    assert (
        inspect.signature(compare_full_content).parameters["artifact_bytes"].default
        is inspect.Parameter.empty
    ), "compare_full_content invented an artifact size"
    with pytest.raises(BenchError, match="not a Layer B topic option"):
        layer_b_mcap_bytes(full_stream, preset=DEFAULT, option="tf")
    with pytest.raises(BenchError, match="not an MCAP preset"):
        layer_b_mcap_bytes(full_stream, preset="mcap", option=TF)
    with pytest.raises(BenchError, match="not a Layer B topic option"):
        layer_b_option("markers")


def test_the_arrangement_chosen_is_the_cheapest_one_priced(
    full_stream: Path,
) -> None:
    """**The property the whole comparison rests on**, under both presets.

    *Most favourable to the incumbent* is the smallest bag, because the smallest
    bag is the one this project's corrected ratio is largest against. If the
    chosen arrangement ever stopped being the minimum, the published ratio would
    be against a comparator picked to lose and the finding would be worthless.
    """
    for preset in (DEFAULT, COMPRESSED):
        priced = {
            option.name: layer_b_mcap_bytes(
                full_stream, preset=preset, option=option.name
            )
            for option in LAYER_B_OPTIONS
        }
        assert priced == {TF: TF_BYTES[preset], POSE: POSE_BYTES[preset]}
        chosen, size = cheapest_layer_b_option(full_stream, preset=preset)
        assert size == min(priced.values()), (
            f"{preset}: {chosen} at {size:,} B is not the smallest of {priced}"
        )
        assert chosen == TF


def test_a_tie_between_arrangements_is_refused_rather_than_broken(
    full_stream: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE NEGATIVE for the choice. Two arrangements at one price name no winner.

    No pair in `LAYER_B_OPTIONS` ties, so the case is constructed: the same
    encoding under two names. Picking either would put a decision nobody made
    behind a published figure, and picking silently is how it would happen.
    """
    tf = layer_b_option(TF)
    monkeypatch.setattr(
        bench,
        "LAYER_B_OPTIONS",
        (tf, LayerBTopicOption(
            name="tf_tree_twin", per_entity=tf.per_entity,
            carries=tf.carries, what=tf.what,
        )),
    )
    with pytest.raises(BenchError, match="no single arrangement most favourable"):
        cheapest_layer_b_option(full_stream, preset=DEFAULT)


def test_the_marker_alternative_is_dearer_per_entity_than_the_one_chosen(
    full_stream: Path,
) -> None:
    """The rejected third candidate, measured rather than argued away.

    `docs/sensor-baseline.md` says a `MarkerArray` cannot be the most favourable
    arrangement because a Marker carries the same Header and Pose as a
    `TransformStamped` and adds a namespace, an id, a type, an action, a scale, a
    colour, a lifetime, a flag, two arrays and two strings. Both put one message
    per control period on one topic, so per-entity payload decides it, and this is
    that comparison on a real obstacle rather than the sentence alone.
    """
    obstacle = next(e for e in _entities(full_stream) if e.radius is not None)
    one_transform = tf_message_cdr(
        1.0, [obstacle], frame_id=bench.LAYER_B_PARENT_FRAME
    )
    one_marker = (
        b"\x00\x01\x00\x00"
        + struct.pack("<I", 1)
        + marker_cdr(
            1.0, obstacle, frame_id=bench.LAYER_B_PARENT_FRAME,
            namespace="", marker_id=0,
        )
    )
    assert len(one_marker) > len(one_transform), (
        f"a one-entity MarkerArray is {len(one_marker)} B against a "
        f"{len(one_transform)} B TFMessage, so the rejected alternative is no "
        "longer the dearer one and the arrangement chosen is not the most "
        "favourable to the incumbent."
    )


def test_a_marker_for_an_entity_the_stream_gives_no_extent_is_refused(
    full_stream: Path,
) -> None:
    """THE NEGATIVE that keeps the third candidate out of the priced set.

    A Marker states an extent in `scale`. The stream carries one for every
    obstacle and none for the human, and a plausible metre written there would
    sit inside a published byte count looking exactly like a measured one — and
    would change the compressed figure, since what is written is what compresses.
    """
    human = _entities(full_stream)[0]
    assert human.name == "human" and human.radius is None
    with pytest.raises(BenchError, match="no radius in the stream"):
        marker_cdr(
            1.0, human, frame_id=bench.LAYER_B_PARENT_FRAME,
            namespace="", marker_id=0,
        )


# --- the figures, held to arithmetic rather than to golden values -----------


def test_the_whole_stream_price_is_the_two_halves_and_nothing_else(
    full_stream: Path,
) -> None:
    """`/joint_states` plus the chosen Layer B arrangement, with no third term.

    Stated as arithmetic over the two halves this module already prices, so it
    fails if either half moves and it fails if a term is quietly added between
    them.
    """
    for preset in (DEFAULT, COMPRESSED):
        option, total = full_content_mcap_bytes(full_stream, preset=preset)
        assert option == TF
        assert total == (
            mcap_joint_states_bytes(full_stream, preset=preset)
            + layer_b_mcap_bytes(full_stream, preset=preset, option=TF)
        )
        assert total == JOINT_STATES_BYTES[preset] + TF_BYTES[preset]
        assert total == FULL_BYTES[preset]


def test_the_layer_b_half_is_the_records_and_the_index_and_nothing_else(
    full_stream: Path,
) -> None:
    """The uncompressed arrangement as arithmetic: 3,000 messages, 356 B payload.

    31 B of framing and 16 B of message index per message, both named constants
    shared with the `/joint_states` half, so this fails if either moves and it
    fails if the index term is dropped from this half alone.
    """
    entities = _entities(full_stream)
    assert len(entities) == ENTITIES
    payload = len(tf_message_cdr(0.0, entities, frame_id=bench.LAYER_B_PARENT_FRAME))
    per_message = MCAP_MESSAGE_RECORD_OVERHEAD + payload
    assert layer_b_mcap_bytes(full_stream, preset=DEFAULT, option=TF) == (
        FULL_FRAMES * (per_message + MCAP_MESSAGE_INDEX_PER_MESSAGE)
    )


def test_the_per_entity_arrangement_pays_the_framing_once_per_entity(
    full_stream: Path,
) -> None:
    """Why `/tf` is smaller, as arithmetic rather than as a claim in the document.

    Four entities, so the per-entity arrangement writes four messages a frame and
    pays 31 B of framing and 16 B of index four times where `/tf` pays them once.
    That is the whole of the difference at the uncompressed preset.
    """
    fixed = MCAP_MESSAGE_RECORD_OVERHEAD + MCAP_MESSAGE_INDEX_PER_MESSAGE
    tf_messages = FULL_FRAMES
    pose_messages = FULL_FRAMES * ENTITIES
    assert POSE_BYTES[DEFAULT] - TF_BYTES[DEFAULT] == (
        (pose_messages - tf_messages) * fixed
        + FULL_FRAMES * (
            ENTITIES * len(pose_stamped_cdr(0.0, 0.0, 0.0,
                                            frame_id=bench.LAYER_B_PARENT_FRAME))
            - len(tf_message_cdr(0.0, _entities(full_stream),
                                 frame_id=bench.LAYER_B_PARENT_FRAME))
        )
    )


def test_the_published_whole_stream_figures_are_the_measured_ones(
    full_stream: Path,
) -> None:
    """The finding, and the reason this issue exists. Held to the byte.

    If any of these moves, either the encoder changed or the fixture did, and
    both are findings rather than numbers to update in place.
    """
    for preset in (DEFAULT, COMPRESSED):
        assert full_content_mcap_bytes(full_stream, preset=preset)[1] == (
            FULL_BYTES[preset]
        )
    assert gzip_bytes(full_stream) == FULL_GZIP_CSV_BYTES
    assert FULL_BYTES[DEFAULT] > FULL_BYTES[COMPRESSED] > FULL_GZIP_CSV_BYTES, (
        "the whole-stream bag came out at or below the gzipped CSV of the same "
        "24 columns. That would retire the finding this comparison publishes and "
        "should be read as a bug in the encoder before it is read as a result."
    )


def test_the_two_ratios_compose(full_stream: Path) -> None:
    """**THE ACCEPTANCE CRITERION**, as an identity rather than as a sentence.

    `artifact / gzipped CSV` divided by `bag / gzipped CSV` is `artifact / bag`,
    and it holds only because all three cover the same 24 columns of the same
    run. Before this issue the encoding ratio covered five of them and the
    division was meaningless; this is what makes the single corrected ratio a
    ratio of the same thing on both sides.
    """
    for preset in (DEFAULT, COMPRESSED):
        c = compare_full_content(
            full_stream, preset=preset, artifact_bytes=published_artifact_bytes()
        )
        assert c.gzip_ratio / c.incumbent_over_gzip == pytest.approx(
            c.corrected_ratio, rel=1e-12
        )
        assert c.gzip_csv_bytes == FULL_GZIP_CSV_BYTES
        assert c.messages == FULL_FRAMES * 2  # one /joint_states, one /tf a frame


def test_the_discount_to_the_incumbent_is_itemised_rather_than_left_implicit(
    full_stream: Path,
) -> None:
    """The eight columns the bag is charged nothing per frame for.

    The gzipped CSV pays for them on all 3,000 rows and the bag pays for them on
    none, so the ratio is generous to the incumbent by an amount a reader is
    entitled to see. An empty list here would mean the encoder had silently
    started charging for content it does not carry, or that the itemisation had
    stopped working — and both read as *no discount* to anyone downstream.
    """
    header = _header(full_stream)
    uncharged = uncharged_layer_b_columns(header, option=TF)
    assert uncharged == [
        "human_vx", "human_vy",
        "obs_0_kind", "obs_0_r", "obs_1_kind", "obs_1_r", "obs_2_kind", "obs_2_r",
    ]
    # The per-entity arrangement is charged for even less: it carries no entity
    # name in the payload at all, because the name is its topic.
    assert set(uncharged) < set(uncharged_layer_b_columns(header, option=POSE))
    sentence = compare_full_content(
        full_stream, preset=DEFAULT, artifact_bytes=published_artifact_bytes()
    ).sentence()
    assert "discount to the incumbent" in sentence
    for column in uncharged:
        assert column in sentence


def test_the_two_column_halves_are_the_whole_header(full_stream: Path) -> None:
    """5 + 19 = 24, and no column is in both halves or in neither.

    This is what *priced over the same content as the baseline* means
    mechanically. A column that fell out of both halves would be paid for by the
    gzipped CSV and by nothing on the incumbent side, which is a discount handed
    over by omission — the one direction of error nothing downstream could see.
    """
    header = _header(full_stream)
    prop = proprioceptive_columns(header)
    layer_b = layer_b_columns(header)
    assert len(prop) == 5 and len(layer_b) == 19
    assert sorted(prop + layer_b) == sorted(header)
    assert not set(prop) & set(layer_b)


# --- could-not-evaluate never resolves to a pass ----------------------------


def test_a_column_with_no_rule_is_refused_by_the_layer_b_half_too(
    tmp_path: Path,
) -> None:
    """THE NEGATIVE for the split. A column nobody classified is not Layer B.

    `proprioceptive_columns` has refused an unknown column since issue #137;
    `layer_b_columns` is the other half of the same split and refuses through the
    same classifier, or a column added to the stream would be priced on one side
    of the corrected ratio and not the other.
    """
    with pytest.raises(BenchError, match="matches no rule"):
        layer_b_columns(["t", "q_0", "qd_0", "lidar_points"])


def test_a_stream_with_no_entity_columns_is_refused(tmp_path: Path) -> None:
    """Silence is could-not-evaluate. A bag priced over no entities is cheap."""
    p = tmp_path / "noentity.csv"
    p.write_text("t,q_0,qd_0\n0.0,0.1,0.2\n0.02,0.11,0.21\n")
    with pytest.raises(BenchError, match="no entity for a Layer B topic"):
        layer_b_mcap_bytes(p, preset=DEFAULT, option=TF)


def test_an_empty_stream_is_refused_by_both_whole_stream_calls(
    tmp_path: Path,
) -> None:
    """A header and no frames is a step of the pipeline that did not run."""
    p = tmp_path / "empty.csv"
    p.write_text("t,q_0,qd_0,human_x,human_y,human_vx,human_vy\n")
    with pytest.raises(BenchError, match="no frames"):
        layer_b_mcap_bytes(p, preset=DEFAULT, option=TF)
    with pytest.raises(BenchError, match="no frames"):
        compare_full_content(p, preset=DEFAULT, artifact_bytes=1)


def test_a_whole_stream_comparison_with_a_side_at_zero_is_refused() -> None:
    """Any of the three sides at zero is an encoding that did not run."""
    healthy = dict(
        preset=DEFAULT, option=TF, artifact_bytes=2_584_576,
        incumbent_bytes=FULL_BYTES[DEFAULT], gzip_csv_bytes=FULL_GZIP_CSV_BYTES,
        messages=FULL_FRAMES * 2, uncharged=(),
    )
    for side in ("artifact_bytes", "incumbent_bytes", "gzip_csv_bytes"):
        with pytest.raises(BenchError, match="did not run"):
            FullContentComparison(**{**healthy, side: 0})
    with pytest.raises(BenchError, match="prices nothing"):
        FullContentComparison(**{**healthy, "messages": 0})


# --- the reporter, and the case that would move Claim 1's status ------------


def test_the_reporter_says_the_artifact_is_larger_when_it_is(
    full_stream: Path,
) -> None:
    """The healthy case, on both presets, with the content in the same sentence.

    A ratio without its content clause is what made `~40x` and `3.83x` look like
    numbers about one thing, so the sentence has to carry both denominators.
    """
    artifact = published_artifact_bytes()
    report = full_content_report(full_stream, artifact_bytes=artifact)
    for preset in (DEFAULT, COMPRESSED):
        c = compare_full_content(
            full_stream, preset=preset, artifact_bytes=artifact
        )
        assert c.verdict == ARTIFACT_LARGER
        assert c.claim_1_status == CLAIM_1_STATUS_STANDS
        assert "LARGER" in c.sentence()
        assert "whole stream" in c.sentence()
        assert preset in report
        assert f"{FULL_BYTES[preset]:,} B" in report
    assert f"{artifact:,} B" in report and f"{FULL_GZIP_CSV_BYTES:,} B" in report


def test_the_reporter_says_it_in_words_when_the_artifact_is_smaller() -> None:
    """**THE NEGATIVE THIS COMPARISON EXISTS FOR** (issue #220's fifth criterion).

    Fed an artifact smaller than the bag, the reporter must say so in words *and*
    say that Claim 1's status has to change — because `landed, reframed` is
    written on the premise that the artifact is not smaller than what it would
    replace, and a ratio below 1 retires that premise in this project's favour.
    No fixture here produces the case, so it is constructed.

    A ratio alone would not do it. `0.63x` and `1.58x` look alike at a glance and
    mean opposite things about whether the reframing away from compression was
    the right call.
    """
    against = FullContentComparison(
        preset=DEFAULT, option=TF, artifact_bytes=100_000,
        incumbent_bytes=FULL_BYTES[DEFAULT], gzip_csv_bytes=FULL_GZIP_CSV_BYTES,
        messages=FULL_FRAMES * 2, uncharged=(),
    )
    assert against.verdict == ARTIFACT_SMALLER
    assert against.corrected_ratio < 1.0
    sentence = against.sentence()
    assert "SMALLER" in sentence
    assert CLAIM_1_STATUS_MUST_CHANGE in sentence
    assert against.claim_1_status == CLAIM_1_STATUS_MUST_CHANGE


def test_a_tie_does_not_resolve_to_the_status_standing() -> None:
    """The third verdict, and it is not folded into the first.

    At a tie the artifact is not smaller and it is not larger. `landed, reframed`
    is written on the first of those, so a tie does not sustain it — and rounding
    a knife-edge towards the conclusion the project already published is exactly
    what this section was built to avoid.
    """
    level = FullContentComparison(
        preset=COMPRESSED, option=TF, artifact_bytes=FULL_BYTES[COMPRESSED],
        incumbent_bytes=FULL_BYTES[COMPRESSED],
        gzip_csv_bytes=FULL_GZIP_CSV_BYTES, messages=FULL_FRAMES * 2, uncharged=(),
    )
    assert level.verdict == ARTIFACT_LEVEL
    assert level.claim_1_status == CLAIM_1_STATUS_UNDECIDED
    assert "SAME" in level.sentence()
    assert CLAIM_1_STATUS_UNDECIDED in level.sentence()
    assert CLAIM_1_STATUS_STANDS not in level.sentence()


# --- the documents that quote it --------------------------------------------


def test_claim_1s_status_line_is_the_one_the_measurement_licenses(
    full_stream: Path,
) -> None:
    """**Issue #220's fourth criterion, made checkable rather than asserted.**

    `README.md` carries Claim 1's status and it says `landed, reframed`. That
    wording is licensed by one measured fact — the artifact is larger than what it
    would replace — and this issue re-measures that fact against a comparator five
    times cheaper than the one the status was written against. So the status is
    held to the measurement here: it stands only while the comparison says
    `ARTIFACT LARGER`, at **both** presets, and the negative above is what the
    other outcome reads like.
    """
    artifact = published_artifact_bytes()
    for preset in (DEFAULT, COMPRESSED):
        assert compare_full_content(
            full_stream, preset=preset, artifact_bytes=artifact
        ).claim_1_status == CLAIM_1_STATUS_STANDS
    row = next(
        line
        for line in (REPO / "README.md").read_text(encoding="utf-8").splitlines()
        if line.startswith("| **1** |")
    )
    assert "`landed, reframed`" in row, (
        "README.md's Claim 1 status is no longer `landed, reframed`, and the "
        "whole-stream comparison still says the artifact is larger than the bag "
        "at both presets — which is the fact that wording states. A status that "
        "moved without the measurement moving is one this pin cannot license."
    )


def test_every_document_quoting_the_whole_stream_figures_quotes_the_measured_ones(
    full_stream: Path,
) -> None:
    """The published ratios, re-derived from the encoder on every run.

    No constant is compared against another constant: the strings searched for
    are formatted from a live measurement of the fixture and a document-published
    artifact size, so a document edited to match a regression fails exactly as a
    regression does, and one left behind when the encoder moves fails too.
    """
    artifact = published_artifact_bytes()
    default = compare_full_content(
        full_stream, preset=DEFAULT, artifact_bytes=artifact
    )
    compressed = compare_full_content(
        full_stream, preset=COMPRESSED, artifact_bytes=artifact
    )
    ratios = {
        "artifact_over_bag_default": default.corrected_ratio,
        "artifact_over_bag_compressed": compressed.corrected_ratio,
        "bag_over_gzip_default": default.incumbent_over_gzip,
        "bag_over_gzip_compressed": compressed.incumbent_over_gzip,
        "artifact_over_gzip": default.gzip_ratio,
    }
    for key, ratio in ratios.items():
        rendered = f"{ratio:.2f}x"
        assert _quoting(rendered) == set(DOCS_PUBLISHING[key]), (
            f"the documents quoting {rendered} for {key} are "
            f"{sorted(_quoting(rendered))}, not {sorted(DOCS_PUBLISHING[key])}. "
            "A document that gained the figure belongs in DOCS_PUBLISHING; one "
            "that lost it either dropped the comparison or is quoting a stale "
            "number."
        )
    for preset in (DEFAULT, COMPRESSED):
        measured = full_content_mcap_bytes(full_stream, preset=preset)[1]
        assert _quoting(f"{measured:,} B") == set(DOCS_PUBLISHING_THE_FULL_BYTES)
        for half in (
            mcap_joint_states_bytes(full_stream, preset=preset),
            layer_b_mcap_bytes(full_stream, preset=preset, option=TF),
            layer_b_mcap_bytes(full_stream, preset=preset, option=POSE),
        ):
            assert _quoting(f"{half:,} B") == set(DOCS_PUBLISHING_THE_HALVES), (
                f"{half:,} B is published in {sorted(_quoting(f'{half:,} B'))}, "
                f"not {sorted(DOCS_PUBLISHING_THE_HALVES)}. The halves are the "
                "arithmetic behind the whole-stream figures and one document "
                "carries them."
            )


# ==========================================================================
# THE OUT-OF-BAND VALIDATION (issue #221).
#
# Everything above prices an encoder written here from the MCAP specification.
# Issue #221 wrote real `.mcap` files once, outside this repository, and recorded
# what they cost. That turns two of the figures above into measurements and
# refutes two others, and it creates a new failure mode with it: the recorded
# pair can come apart. The measurement is frozen — the bag was written once and
# cannot be rewritten here — so the half that can move is the projection, and
# these tests are what makes it move loudly.
#
# WHAT THEY HAVE TO HOLD, BEYOND THE BYTES. A validation that can only confirm is
# not a validation, so the verdict is computed from the two byte counts rather
# than stored beside them, the tolerance is read off the preset rather than
# supplied by a caller, and the negatives below feed each check the condition it
# guards against and assert it says no.
# ==========================================================================

#: The document that carries the validation. One document, because the record is
#: the arithmetic behind the figures rather than a figure that travels.
VALIDATION_DOC = REPO / "docs" / "sensor-baseline.md"

#: One row of the published measurement block. Anchored on the fixture name in
#: the first column rather than on position: a table read by counting rows moves
#: the first time somebody adds one.
VALIDATION_ROW = re.compile(
    r"^(declared_violation|long_run_3000)\s+([\d,]+)\s+(\S+)\s+(\w+)\s+"
    r"([\d,]+)\s+([\d,]+)\s+([-+][\d.]+)%\s+(\S+)\s*$",
    re.MULTILINE,
)


def _published_rows() -> list[tuple]:
    """The measurement block as tuples, read out of the document that publishes it."""
    rows = []
    for m in VALIDATION_ROW.finditer(VALIDATION_DOC.read_text(encoding="utf-8")):
        rows.append((
            m.group(1), int(m.group(2).replace(",", "")),
            tuple(m.group(3).split("+")), m.group(4),
            int(m.group(5).replace(",", "")), int(m.group(6).replace(",", "")),
            float(m.group(7)), m.group(8),
        ))
    return rows


def _fixture_for(measurement: McapSizeMeasurement, stream: Path,
                 full_stream: Path) -> Path:
    return stream if measurement.fixture == "declared_violation" else full_stream


# --- the pair, and that it cannot come apart quietly ------------------------


def test_the_recorded_projection_is_still_what_reg_bench_computes(
    stream: Path, full_stream: Path
) -> None:
    """**THE ACCEPTANCE CRITERION.** Every recorded row, recomputed live.

    The measurement half is frozen. If the projection half moves, the published
    delta describes a comparison between a bag that was written and an encoder
    that no longer exists — and nothing else in this repository would say so,
    because every other test holds the projection to its own constants rather
    than to what a real encoder produced.
    """
    assert MCAP_SIZE_MEASUREMENTS, (
        "no measurement is recorded at all. An empty validation is a "
        "could-not-evaluate that reads exactly like a clean one."
    )
    for m in MCAP_SIZE_MEASUREMENTS:
        path = _fixture_for(m, stream, full_stream)
        assert projection_drift(m, path) == PROJECTION_HOLDS, (
            f"{m.sentence()} — but reg.bench now computes "
            f"{project_for_topics(path, topics=m.topics, preset=m.preset):,} B "
            "for that stream. The validated pair has come apart: either the "
            "encoder changed or the fixture did, and the published delta is "
            "against a projection nobody can reproduce."
        )


def test_a_projection_that_moved_away_from_the_record_is_reported_as_drift(
    stream: Path,
) -> None:
    """THE NEGATIVE for the drift check. One byte is enough.

    A check that only ever sees the matching case proves nothing about whether
    it can fail, and this one guards the only half of the validated pair that is
    able to move.
    """
    recorded = mcap_size_measurement("declared_violation", ("/joint_states",), DEFAULT)
    assert projection_drift(recorded, stream) == PROJECTION_HOLDS
    moved = replace(recorded, projected_bytes=recorded.projected_bytes + 1)
    assert projection_drift(moved, stream) == PROJECTION_DRIFTED


def test_the_arrangement_has_no_fallback_and_an_unmeasured_one_is_refused(
    stream: Path,
) -> None:
    """THE NEGATIVE for the lookup and the dispatch. Neither may guess.

    A topic set resolving to the nearest priced arrangement would set the whole
    bag's measurement beside half of it and publish the difference as a delta,
    which is the one error a validation must not be able to make.
    """
    with pytest.raises(BenchError, match="not an arrangement this module projects"):
        project_for_topics(stream, topics=("/odom",), preset=DEFAULT)
    with pytest.raises(BenchError, match="nothing was measured"):
        mcap_size_measurement("declared_violation", ("/tf",), DEFAULT)
    with pytest.raises(BenchError, match="nothing was measured"):
        mcap_size_measurement("long_run", ("/joint_states",), DEFAULT)


# --- the verdict, and that it can come out either way -----------------------


def test_the_verdict_is_computed_from_the_two_byte_counts(stream: Path) -> None:
    """Not stored beside them. A stored verdict can disagree with its own numbers.

    Both sides of the band are reached from the same constructor, so the check
    that says *stands* is demonstrably the same one that can say *does not*.
    """
    base = dict(fixture="long_run_3000", seed=0, frames=3_000,
                topics=("/tf",), preset=COMPRESSED, projected_bytes=100_000)
    inside = McapSizeMeasurement(**base, measured_bytes=96_000)    # -4.0%
    outside = McapSizeMeasurement(**base, measured_bytes=94_000)   # -6.0%
    assert inside.tolerance == MCAP_VALIDATION_TOLERANCE
    assert inside.verdict == WITHIN_TOLERANCE
    assert outside.verdict == OUTSIDE_TOLERANCE
    # And symmetrically above the projection: a bag that came back *dearer* than
    # projected fails the same way. A one-sided band would pass every error in
    # the direction that flatters this project.
    assert McapSizeMeasurement(**base, measured_bytes=106_000).verdict == (
        OUTSIDE_TOLERANCE
    )
    assert McapSizeMeasurement(**base, measured_bytes=104_000).verdict == (
        WITHIN_TOLERANCE
    )


def test_the_uncompressed_preset_is_held_exactly_and_one_byte_fails_it() -> None:
    """THE NEGATIVE for the preset-dependent tolerance.

    `mcap_default` contains no compressor, so there is no substitution in it to
    be approximately right about. A shared +/-5% band would have let a 5% error in
    a sum of exact per-message terms through as a pass.
    """
    base = dict(fixture="long_run_3000", seed=0, frames=3_000,
                topics=("/tf",), preset=DEFAULT, projected_bytes=1_209_000)
    assert McapSizeMeasurement(**base, measured_bytes=1_209_000).tolerance == 0.0
    assert McapSizeMeasurement(**base, measured_bytes=1_209_000).verdict == (
        WITHIN_TOLERANCE
    )
    assert McapSizeMeasurement(**base, measured_bytes=1_209_001).verdict == (
        OUTSIDE_TOLERANCE
    )


def test_the_tolerance_cannot_be_supplied_by_whoever_wants_a_verdict() -> None:
    """The band is read off the preset, never passed in.

    A tolerance that arrives with the comparison is one that can be chosen after
    the number is known, which is the failure the registered threshold exists to
    prevent. It is a property with no setter and a constructor with no field.
    """
    fields = inspect.signature(McapSizeMeasurement).parameters
    assert "tolerance" not in fields, (
        "McapSizeMeasurement gained a tolerance field. A recorded row that "
        "carries its own band can be made to pass by editing the band."
    )
    assert isinstance(MCAP_VALIDATION_TOLERANCE, float)
    assert 0.0 < MCAP_VALIDATION_TOLERANCE < 1.0


def test_the_recorded_validation_reached_both_verdicts() -> None:
    """A validation that can only confirm is not one, and this one did not.

    Six rows stand and two do not. If a future re-measurement makes every row
    pass, this assertion is the place to record that deliberately — but it must
    not go green by the verdict quietly losing its other value.
    """
    verdicts = {m.verdict for m in MCAP_SIZE_MEASUREMENTS}
    assert verdicts == {WITHIN_TOLERANCE, OUTSIDE_TOLERANCE}, (
        f"the recorded validation reaches only {sorted(verdicts)}. A comparison "
        "with one reachable outcome is not evidence about the projection; it is "
        "evidence about the comparison."
    )
    failing = [m for m in MCAP_SIZE_MEASUREMENTS if m.verdict == OUTSIDE_TOLERANCE]
    assert all(mcap_preset(m.preset).compressed for m in failing), (
        "an uncompressed figure failed its exact comparison. That is a misread "
        "specification rather than a compressor substitution, and it retires "
        "the section rather than footnoting it."
    )


def test_a_measurement_with_an_impossible_byte_count_is_refused() -> None:
    """THE NEGATIVE for the record itself. A zero reads as a free encoding.

    Every other check here compares two numbers; this is what stops one of them
    being a step of the pipeline that did not run.
    """
    base = dict(fixture="long_run_3000", seed=0, frames=3_000,
                topics=("/tf",), preset=COMPRESSED)
    with pytest.raises(BenchError, match="measured_bytes is 0"):
        McapSizeMeasurement(**base, projected_bytes=1, measured_bytes=0)
    with pytest.raises(BenchError, match="projected_bytes is -1"):
        McapSizeMeasurement(**base, projected_bytes=-1, measured_bytes=1)
    with pytest.raises(BenchError, match="prices nothing"):
        McapSizeMeasurement(
            fixture="long_run_3000", seed=0, frames=3_000, topics=(),
            preset=COMPRESSED, projected_bytes=1, measured_bytes=1,
        )
    with pytest.raises(BenchError, match="not an MCAP preset"):
        McapSizeMeasurement(
            fixture="long_run_3000", seed=0, frames=3_000, topics=("/tf",),
            preset="zstd_fast", projected_bytes=1, measured_bytes=1,
        )


# --- the per-message terms, which are held exactly --------------------------


def test_the_structural_terms_measured_are_the_constants_this_module_encodes_with(
    stream: Path, full_stream: Path
) -> None:
    """The five per-message terms, and that the record is about *these* constants.

    A structural table whose projected column had drifted away from
    `MCAP_MESSAGE_RECORD_OVERHEAD` would still show five green ticks while
    describing an encoder this module no longer has.
    """
    by_what = {c.what: c for c in MCAP_STRUCTURAL_CHECKS}
    assert all(c.matches for c in MCAP_STRUCTURAL_CHECKS), (
        f"{[c.what for c in MCAP_STRUCTURAL_CHECKS if not c.matches]} came back "
        "from a real encoder at a different width. These are byte counts read "
        "off a specification, so a mismatch is a misread spec."
    )
    assert by_what["Message record framing, per message"].projected == (
        MCAP_MESSAGE_RECORD_OVERHEAD
    )
    assert by_what["MessageIndex entry, per message"].projected == (
        MCAP_MESSAGE_INDEX_PER_MESSAGE
    )
    assert by_what["sensor_msgs/msg/JointState CDR payload, 2 joints"].projected == (
        len(joint_state_cdr(1.0, [0.1, 0.2], [0.3, 0.4], ["joint_0", "joint_1"]))
    )
    entities = _entities(full_stream)
    assert by_what["tf2_msgs/msg/TFMessage CDR payload, 4 entities"].projected == (
        len(tf_message_cdr(0.0, entities, frame_id=bench.LAYER_B_PARENT_FRAME))
    )
    assert len(entities) == ENTITIES


def test_a_structural_term_that_came_back_different_does_not_match() -> None:
    """THE NEGATIVE for the exact comparison. There is no band on a spec constant."""
    assert McapStructuralCheck("a payload", 96, 96).matches is True
    assert McapStructuralCheck("a payload", 96, 97).matches is False
    with pytest.raises(BenchError, match="measured is 0"):
        McapStructuralCheck("a payload", 96, 0)


# --- what the document publishes, held to the record ------------------------


def test_the_document_publishes_every_recorded_row_and_its_delta() -> None:
    """The table and the record, cell by cell, in both directions.

    Neither is allowed to be the other's summary. A row edited in the document
    fails, a row added to the record and not published fails, and a delta typed
    by hand that does not follow from its own two byte counts fails.
    """
    published = _published_rows()
    assert len(published) == len(MCAP_SIZE_MEASUREMENTS), (
        f"{VALIDATION_DOC.name} publishes {len(published)} measured rows and "
        f"reg.bench records {len(MCAP_SIZE_MEASUREMENTS)}. A recorded row that "
        "is not on the page is a measurement nobody outside this repository can "
        "see, which is the whole point of taking it."
    )
    for row, m in zip(published, MCAP_SIZE_MEASUREMENTS):
        fixture, frames, topics, preset, projected, measured, delta, verdict = row
        assert (fixture, frames, topics, preset) == (
            m.fixture, m.frames, m.topics, m.preset
        ), f"{VALIDATION_DOC.name} row {row!r} is not {m.sentence()}"
        assert (projected, measured) == (m.projected_bytes, m.measured_bytes)
        assert delta == pytest.approx(round(m.delta * 100, 2), abs=0.005), (
            f"{VALIDATION_DOC.name} publishes {delta:+.2f}% for {m.fixture} "
            f"{m.topics} {m.preset}, and the two byte counts beside it give "
            f"{m.delta * 100:+.2f}%. A delta typed rather than derived is a "
            "number with nothing behind it."
        )
        expected = "DOES-NOT-STAND" if m.verdict == OUTSIDE_TOLERANCE else "stands"
        assert verdict == expected, (
            f"{VALIDATION_DOC.name} calls {m.fixture} {m.topics} {m.preset} "
            f"{verdict!r}, and its own numbers make it {m.verdict}."
        )


def test_a_figure_that_failed_is_marked_where_the_document_publishes_it() -> None:
    """The registered consequence, enforced rather than remembered.

    *Outside tolerance* was defined in advance as *marked as not standing at
    every place this document publishes it*. A figure that fails its own
    tolerance and stays on the page unmarked is the failure the whole subsection
    exists to prevent, and it is exactly the kind that nothing else would catch.
    """
    text = VALIDATION_DOC.read_text(encoding="utf-8")
    failing = [m for m in MCAP_SIZE_MEASUREMENTS if m.verdict == OUTSIDE_TOLERANCE]
    assert failing, "nothing failed, so this check has nothing to enforce"
    assert "does not stand" in text
    for m in failing:
        published = f"{m.projected_bytes:,} B"
        for line in text.splitlines():
            if line.startswith("|") and published in line:
                assert "[^v]" in line, (
                    f"{VALIDATION_DOC.name} publishes {published} on the line "
                    f"{line!r} with no mark, and that figure is "
                    f"{m.delta * 100:+.2f}% from the measurement against a "
                    f"+/-{m.tolerance * 100:.0f}% band. It does not stand and "
                    "the page has to say so where it says the number."
                )
        assert f"{m.measured_bytes:,} B" in text, (
            f"the measurement {m.measured_bytes:,} B is not published beside the "
            "projection it refutes. The delta is stated, not absorbed."
        )


def test_the_procedure_names_what_a_third_party_needs() -> None:
    """The other half of the acceptance criterion: repeatable by somebody else.

    Not a prose check for its own sake. `prior-art.md` §27's finding is that
    reproducibility is relative to a stated environment, so a procedure missing
    the seed, the message type or the preset leaves a reader to invent it — and
    an invented input is what produced the wrong preset in issue #117.
    """
    text = VALIDATION_DOC.read_text(encoding="utf-8")
    start = text.index("### Validating the projection against a real bag")
    end = text.index("### What would retire this section")
    section = text[start:end]
    for needed in (
        "--scenario declared_violation", "--scenario long_run_3000", "--seed 0",
        "/joint_states", "/tf",
        "sensor_msgs/msg/JointState", "tf2_msgs/msg/TFMessage",
        DEFAULT, COMPRESSED, "768 KiB", "XCDR1", "LAYER_B_PARENT_FRAME",
        "log_time", "sequence",
    ):
        assert needed in section, (
            f"the procedure does not name {needed!r}. A third party would have "
            "to choose it, and a chosen input is the failure issue #117 found."
        )
    for m in MCAP_SIZE_MEASUREMENTS:
        assert str(m.frames) in section or f"{m.frames:,}" in section


def test_the_provenance_states_what_was_not_run() -> None:
    """The date, the versions, and the part that is easiest to leave out.

    Every tool that ran is recorded, and so is the one that did not: rosbag2's
    own writer. A provenance listing only what ran reads as a complete
    validation, and this one is not — *rosbag2 writes this preset* is still a
    citation.
    """
    text = VALIDATION_DOC.read_text(encoding="utf-8")
    for needed in ("2026-09-06", "mcap 1.4.0", "mcap-ros2-support 0.5.7",
                   "zstandard 0.25.0"):
        assert needed in MCAP_VALIDATION_PROVENANCE, f"provenance omits {needed}"
    assert "NOT run" in MCAP_VALIDATION_PROVENANCE, (
        "the provenance does not say what was not exercised. rosbag2's own "
        "writer was not installed, and a record that omits that reads as a "
        "measurement of rosbag2 rather than of a second implementation of the "
        "same specification."
    )
    assert "rosbag2" in MCAP_VALIDATION_PROVENANCE
    assert "2026-09-06" in text and "mcap-ros2-support` 0.5.7" in text
