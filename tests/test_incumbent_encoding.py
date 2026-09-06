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
"""

from __future__ import annotations

import csv
import gzip
import inspect
import re
import struct
from pathlib import Path

import pytest

from reg.bench import (
    CDR_ENCAPSULATION,
    GZIP_COMPRESSLEVEL,
    GZIP_MTIME,
    INCUMBENT_CHEAPER,
    INCUMBENT_DEARER,
    INCUMBENT_LEVEL,
    MCAP_MESSAGE_INDEX_PER_MESSAGE,
    MCAP_MESSAGE_RECORD_OVERHEAD,
    MCAP_PRESETS,
    BenchError,
    IncumbentComparison,
    compare_incumbent,
    gzip_bytes_of_columns,
    incumbent_report,
    joint_state_cdr,
    mcap_joint_states_bytes,
    mcap_preset,
    proprioceptive_columns,
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
