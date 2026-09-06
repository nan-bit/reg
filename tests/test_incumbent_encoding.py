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

Three profiles are priced because rosbag2 ships them: `none`, which is what a
practitioner gets without choosing, and `zstd_fast` and `zstd_small`, which are
the two like-for-likes against a gzipped baseline. Pricing one of them is how a
comparison comes out whichever way its author wanted, so the tests below hold
all three — and hold the names to what `--storage-preset-profile` accepts, since
the two this module published before issue #232 were names rosbag2 answers with
an error.

The reporter has a negative of its own: fed an incumbent cheaper than the
baseline, it must say so in words. A comparison that can only flatter is not a
measurement, and that case is the one no fixture in this repository produces.

Issue #233 moved the whole-content figures again, and this time off the
projection entirely: the bags of the 2026-09-06 rosbag2 run are what the
documents publish against the incumbent, the uncompressed one keeping its value
and changing its status, the compressed one becoming a **pair** because rosbag2
ships two compressed profiles and one projection cannot be right about both. So
the document checks below read `ROSBAG2_SIZE_MEASUREMENTS`, and half a pair is a
failure with a negative under it.

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
    MCAP_NON_PROFILE_CONFIGURATIONS,
    MCAP_PRESETS,
    MCAP_PRICED_CONFIGURATIONS,
    MCAP_SIZE_MEASUREMENTS,
    MCAP_STRUCTURAL_CHECKS,
    MCAP_VALIDATION_PROVENANCE,
    MCAP_VALIDATION_TOLERANCE,
    NOT_BANDED,
    NOT_PROJECTED,
    OUTSIDE_TOLERANCE,
    PROJECTION_DRIFTED,
    PROJECTION_HOLDS,
    ROSBAG2_PROVENANCE,
    ROSBAG2_SIZE_MEASUREMENTS,
    ROSBAG2_STORAGE_PRESET_PROFILES,
    ROSBAG2_UNCOMPRESSED_TOLERANCE,
    WITHIN_TOLERANCE,
    BenchError,
    FullContentComparison,
    IncumbentComparison,
    LayerBTopicOption,
    McapPreset,
    McapSizeMeasurement,
    McapStructuralCheck,
    Rosbag2Measurement,
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
    rosbag2_index_bytes_per_message,
    rosbag2_measurement,
    rosbag2_projection_drift,
    stream_frames,
    stream_entities,
    tf_message_cdr,
    uncharged_layer_b_columns,
)

REPO = Path(__file__).resolve().parents[1]

#: rosbag2's uncompressed profile, which is also what a bag costs when nobody
#: passes `--storage-preset-profile`.
DEFAULT = "none"

#: One of the two compressed profiles. `reg.bench` computes a single compressed
#: projection and applies it to both, so this name stands for that projection
#: wherever a test is about the arithmetic rather than about the profile —
#: `test_the_two_compressed_profiles_share_one_projection` is what keeps the
#: substitution honest, and the measured bags are what say it matches neither.
COMPRESSED = "zstd_fast"

#: The other one, and the reason a single compressed figure was never going to
#: be right about "the compressed preset".
COMPRESSED_SMALL = "zstd_small"

#: The names this module published before issue #232, neither of which rosbag2
#: accepts. Kept as the negative: they are what `mcap_preset` must refuse.
RETIRED_PRESET_NAMES = ("mcap_default", "mcap_compressed_nocrc")

#: A real rosbag2 profile that is deliberately not priced: it writes no message
#: index, and this encoder charges one per message.
UNPRICED_PROFILE = "fastwrite"

#: The configuration the reference-writer run of issue #221 encoded under, which
#: is not a profile and cannot be passed to `ros2 bag record`.
REFERENCE_ZSTD = "reference_zstd_l3"

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


def test_every_priced_profile_is_a_name_rosbag2_accepts() -> None:
    """**THE FINDING ISSUE #232 CARRIES.** The names have to be runnable ones.

    A preset name is the one part of this projection a practitioner types. The
    two this module published before — `mcap_default`, `mcap_compressed_nocrc` —
    were mcap.dev's benchmark vocabulary, and `ros2 bag record` answers both
    with *unknown MCAP storage preset profile*. So every name priced is checked
    against the list rosbag2 accepts, and the retired pair is checked to be
    gone: a figure published under a name nobody can pass is a figure nobody can
    reproduce.
    """
    names = [p.name for p in MCAP_PRESETS]
    assert names == [DEFAULT, COMPRESSED, COMPRESSED_SMALL]
    for preset in MCAP_PRESETS:
        assert preset.name in ROSBAG2_STORAGE_PRESET_PROFILES, (
            f"{preset.name!r} is priced as a rosbag2 profile and is not one of "
            f"{list(ROSBAG2_STORAGE_PRESET_PROFILES)}"
        )
    priced = [p.name for p in MCAP_PRICED_CONFIGURATIONS]
    for retired in RETIRED_PRESET_NAMES:
        assert retired not in priced, (
            f"{retired!r} is a name rosbag2 rejects and it is still priced "
            "under. It may appear in prose that says it is retired; it may not "
            "be a configuration this module will resolve."
        )
    assert mcap_preset(DEFAULT).compressed is False
    assert mcap_preset(COMPRESSED).compressed is True
    assert mcap_preset(COMPRESSED_SMALL).compressed is True


def test_each_priced_configuration_says_what_it_is_and_where_that_came_from() -> None:
    """A claim about somebody else's software carries its citation, or it is silence.

    Both halves are required and the negative is here rather than in a separate
    test: an entry constructed with an empty `source` is refused, so the field
    cannot become decoration by being left blank one row at a time.
    """
    for preset in MCAP_PRICED_CONFIGURATIONS:
        assert preset.what.strip(), f"{preset.name} says nothing about itself"
        assert preset.source.strip(), f"{preset.name} cites no source"
    with pytest.raises(BenchError, match="empty source"):
        McapPreset(name="none", compressed=False, what="something", source="  ")
    with pytest.raises(BenchError, match="empty what"):
        McapPreset(name="none", compressed=False, what="", source="somewhere")


def test_the_one_configuration_that_is_not_a_profile_is_kept_out_of_the_profiles(
) -> None:
    """The reference-writer run encoded under something nobody can pass.

    Its rows are real measurements and they are not measurements of `zstd_fast`
    or of `zstd_small` — python-zstandard's default level is neither. Filing
    them under either name would put a real byte count under the name of a
    configuration nobody encoded, which is the failure this issue is fixing one
    layer up. So the configuration keeps its own name, stays out of
    `MCAP_PRESETS`, and says in `what` that it cannot be run.
    """
    assert [p.name for p in MCAP_NON_PROFILE_CONFIGURATIONS] == [REFERENCE_ZSTD]
    profile_names = {p.name for p in MCAP_PRESETS}
    for config in MCAP_NON_PROFILE_CONFIGURATIONS:
        assert config.name not in profile_names
        assert config.name not in ROSBAG2_STORAGE_PRESET_PROFILES
        assert "NOT a rosbag2 profile" in config.what
    assert {m.preset for m in MCAP_SIZE_MEASUREMENTS} == {DEFAULT, REFERENCE_ZSTD}


def test_the_two_compressed_profiles_share_one_projection(stream: Path) -> None:
    """What separates `zstd_fast` from `zstd_small` here is measured, not projected.

    This module runs gzip -9 in place of zstd and has no model of a zstd level,
    so the two profiles come out at the same byte count. That is stated rather
    than hidden: both are reported, the equality is asserted here, and
    `ROSBAG2_SIZE_MEASUREMENTS` is where the real bags put them 43% apart with
    the projection between them, matching neither.
    """
    fast = mcap_joint_states_bytes(stream, preset=COMPRESSED)
    small = mcap_joint_states_bytes(stream, preset=COMPRESSED_SMALL)
    assert fast == small, (
        "the two compressed profiles came out at different byte counts, so this "
        "module has grown a model of the zstd level. That is the thing the "
        "compressed figures are marked for lacking, and it needs the marks "
        "revisited rather than this assertion updated."
    )
    report = incumbent_report(stream)
    for name in (DEFAULT, COMPRESSED, COMPRESSED_SMALL):
        assert name in report, f"the report drops {name}"


def test_the_preset_has_no_default_and_an_unknown_one_is_refused(
    stream: Path,
) -> None:
    """THE NEGATIVE for the configuration. Neither call may guess.

    Compressed and uncompressed differ by a factor of three on the same
    messages, so a default would let this module pick its own answer, and a
    near-miss name silently resolving to a compressed profile would publish a
    real number under the name of a configuration nobody encoded.

    Two refusals, because they are two different things to whoever reads them. A
    name rosbag2 rejects cannot be run at all, and the error says so by listing
    what `--storage-preset-profile` takes. `fastwrite` is a name rosbag2 accepts
    and this module does not price, and telling a practitioner that one is
    *unknown* would send them looking for a typo they did not make.
    """
    for func in (mcap_joint_states_bytes, compare_incumbent):
        assert inspect.signature(func).parameters["preset"].default is (
            inspect.Parameter.empty
        ), f"{func.__name__} invented a default preset"
    with pytest.raises(BenchError, match="not an MCAP preset"):
        mcap_joint_states_bytes(stream, preset="mcap_compressed")
    for retired in RETIRED_PRESET_NAMES:
        with pytest.raises(BenchError, match="not a profile rosbag2 accepts"):
            mcap_joint_states_bytes(stream, preset=retired)
    with pytest.raises(BenchError, match="is a rosbag2 storage preset profile"):
        mcap_preset(UNPRICED_PROFILE)
    assert UNPRICED_PROFILE in ROSBAG2_STORAGE_PRESET_PROFILES, (
        "the unpriced profile is not one rosbag2 accepts, so the refusal above "
        "is no longer telling the two cases apart"
    )


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
#: the documents differ — `README.md` carries the ratios against the artifact and
#: not the encoding ratios behind them, `sensor-baseline.md` carries the encoding
#: and hands the artifact comparison to `retention.md`, and `prior-art.md` carries
#: exactly what its dated corrections needed to state.
#:
#: **One set per family rather than one per profile, and that is the pair rule
#: in the pin** (issue #233). rosbag2 ships two compressed profiles and the
#: measured bags are 43% apart, so a document may publish all three writer
#: settings or none of them, never whichever suits it.
#: `compressed_pair_verdict` is the same rule with a negative under it.
DOCS_PUBLISHING: dict[str, frozenset[str]] = {
    "artifact_over_bag": frozenset(
        {"README.md", "plan.md", "prior-art.md", "retention.md"}
    ),
    "bag_over_gzip": frozenset(
        {"plan.md", "prior-art.md", "retention.md", "sensor-baseline.md"}
    ),
    "artifact_over_gzip": frozenset({"plan.md", "prior-art.md", "retention.md"}),
}

#: The whole-stream byte counts the *projection* computes, and the one document
#: that publishes them. It is one document since issue #233 and was two before:
#: a projected byte count is the arithmetic behind a figure and stays where the
#: arithmetic is, and what travels to `retention.md` is the bag rosbag2 wrote.
DOCS_PUBLISHING_THE_FULL_BYTES = frozenset({"sensor-baseline.md"})
DOCS_PUBLISHING_THE_HALVES = frozenset({"sensor-baseline.md"})

#: The fixture the published incumbent figures are measured on: the 3,000-frame
#: run `ros2 bag record` wrote bags of, which is what every document publishes
#: against the incumbent since issue #233. The byte counts stay in
#: `reg.bench.ROSBAG2_SIZE_MEASUREMENTS`; nothing here restates one.
MEASURED_FIXTURE = "long_run_3000"

#: The three writer settings the documents publish, in publication order: the
#: uncompressed default and the two compressed profiles. `None` is a value and
#: not an omission — it is the bag written with no `--storage-preset-profile`
#: passed, which is what a practitioner keeps without choosing anything, and it
#: is a different measurement from the `none` bag beside it.
PUBLISHED_PROFILES: tuple[str | None, ...] = (None, COMPRESSED, COMPRESSED_SMALL)

#: The measured bag sizes, and the two documents that publish them: the record
#: of the run, and the document where the artifact meets it.
DOCS_PUBLISHING_THE_MEASURED_BYTES = frozenset(
    {"retention.md", "sensor-baseline.md"}
)

#: The compressed figures issue #233 retired, and the one document they may
#: still stand in. `prior-art.md` is a dated survey corrected by addition, so the
#: number a pass was given stays where that pass is; anywhere else it is simply
#: the figure of a projection that models neither profile rosbag2 ships.
RETIRED_COMPRESSED = ("4.75x", "8.42x")
DOCS_KEEPING_THE_RETIRED_COMPRESSED = frozenset({"prior-art.md"})

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


def measured_comparison(
    profile: str | None, *, artifact_bytes: int, gzip_csv_bytes: int
) -> FullContentComparison:
    """The artifact against one bag rosbag2 wrote, as the documents publish it.

    Constructed from `ROSBAG2_SIZE_MEASUREMENTS` rather than from the
    projection: since issue #233 the whole-content incumbent figures are
    measurements, and a comparison built from the projection would recompute the
    number the documents no longer quote. The measurement is frozen and the
    artifact side is read out of the document that publishes it, so nothing here
    invents either side.
    """
    row = rosbag2_measurement(MEASURED_FIXTURE, profile)
    return FullContentComparison(
        preset=row.label, option=TF, artifact_bytes=artifact_bytes,
        incumbent_bytes=row.measured_bytes, gzip_csv_bytes=gzip_csv_bytes,
        messages=row.messages, uncharged=(),
    )


def test_every_document_quoting_the_whole_stream_figures_quotes_the_measured_ones(
    full_stream: Path,
) -> None:
    """**THE ACCEPTANCE CRITERION FOR ISSUE #233.** Every published incumbent
    ratio, re-derived from a measured bag on every run.

    No constant is compared against another constant: the strings searched for
    are formatted from the recorded bags, a live gzip of the fixture and a
    document-published artifact size, so a document edited to match a regression
    fails exactly as a regression does, and one left behind when a figure moves
    fails too.

    All three writer settings are checked in one loop against one set of
    documents per family, which is what makes *published as a pair* a property
    of this pin rather than a sentence in a document.
    """
    artifact = published_artifact_bytes()
    gzip_csv = gzip_bytes(full_stream)
    for profile in PUBLISHED_PROFILES:
        c = measured_comparison(
            profile, artifact_bytes=artifact, gzip_csv_bytes=gzip_csv
        )
        ratios = {
            "artifact_over_bag": c.corrected_ratio,
            "bag_over_gzip": c.incumbent_over_gzip,
            "artifact_over_gzip": c.gzip_ratio,
        }
        for key, ratio in ratios.items():
            rendered = f"{ratio:.2f}x"
            assert _quoting(rendered) == set(DOCS_PUBLISHING[key]), (
                f"the documents quoting {rendered} for {key} at profile "
                f"{profile!r} are {sorted(_quoting(rendered))}, not "
                f"{sorted(DOCS_PUBLISHING[key])}. A document that gained the "
                "figure belongs in DOCS_PUBLISHING; one that lost it either "
                "dropped the comparison or is quoting a stale number."
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


# --- the measured bag, published as a pair (issue #233) ---------------------
#
# WHAT CHANGED AND WHAT DID NOT. The uncompressed figures keep their values: the
# projection came in 0.002% from the bag, so 25.34x and 1.58x are the same
# strings and a different kind of claim. The compressed figure was one
# projection of a configuration rosbag2 does not offer under that name, and it
# sits between the two profiles it does offer, matching neither — so it is
# replaced by a pair rather than re-measured, and the pair is what the checks
# below hold the documents to.

#: The verdicts of `compressed_pair_verdict`. Three-valued, and the third is a
#: could-not-evaluate that never resolves to the first: a document quoting
#: neither profile has published no compressed figure, which is not the same
#: thing as having published both.
PAIR_PUBLISHED = "PAIR PUBLISHED"
PAIR_HALF_PUBLISHED = "PAIR HALF PUBLISHED"
PAIR_ABSENT = "PAIR ABSENT"


def compressed_pair_verdict(
    text: str, fast: str, small: str
) -> tuple[str, list[str]]:
    """Verdict on whether `text` publishes the compressed pair as a pair.

    Half a pair is the failure this exists for, and it is the failure that looks
    like success: rosbag2 ships two compressed profiles whose bags are 43%
    apart, so a document quoting the one that suits it has published a real byte
    count under a choice it did not disclose. That is the error the gzipped
    baseline already makes one layer down, which is why it is checked here
    rather than left to a reviewer.
    """
    quoted = [figure for figure in (fast, small) if figure in text]
    if not quoted:
        return PAIR_ABSENT, []
    if len(quoted) == 2:
        return PAIR_PUBLISHED, []
    return PAIR_HALF_PUBLISHED, quoted


def test_no_document_publishes_one_compressed_profile_without_the_other(
    full_stream: Path,
) -> None:
    """**Issue #233's third criterion**, over the whole corpus.

    Not a restatement of `DOCS_PUBLISHING`: that pins which documents carry the
    family, this asks of each document separately whether what it carries is a
    pair. A corpus where every document had gone silent would satisfy the first
    and say nothing, so at least one document is required to publish both.
    """
    artifact = published_artifact_bytes()
    gzip_csv = gzip_bytes(full_stream)
    fast, small = (
        measured_comparison(
            profile, artifact_bytes=artifact, gzip_csv_bytes=gzip_csv
        )
        for profile in (COMPRESSED, COMPRESSED_SMALL)
    )
    families = (
        (f"{fast.corrected_ratio:.2f}x", f"{small.corrected_ratio:.2f}x"),
        (f"{fast.incumbent_over_gzip:.2f}x", f"{small.incumbent_over_gzip:.2f}x"),
    )
    published = 0
    for doc, path in CORPUS:
        text = path.read_text(encoding="utf-8")
        for one, other in families:
            verdict, quoted = compressed_pair_verdict(text, one, other)
            assert verdict != PAIR_HALF_PUBLISHED, (
                f"{doc} quotes {quoted} and not the other half of the pair. "
                f"rosbag2 ships both compressed profiles and the measured bags "
                "are 43% apart, so one of them alone is a figure chosen rather "
                "than measured."
            )
            published += verdict == PAIR_PUBLISHED
    assert published, (
        "no document publishes the compressed pair at all. That is a "
        "could-not-evaluate about the whole corpus, not a clean run: every "
        "check above is satisfied by a document that stopped quoting the "
        "incumbent."
    )


def test_half_a_pair_is_caught_and_silence_does_not_read_as_a_pair() -> None:
    """**THE NEGATIVE.** Fed the condition it guards against, it must say no.

    Both could-not-evaluate cases are here with it: a text quoting neither
    figure comes back `PAIR_ABSENT`, and `PAIR_ABSENT` is asserted not to be
    `PAIR_PUBLISHED`, because the one way a check of this shape dies is by
    grading silence as agreement.
    """
    assert compressed_pair_verdict(
        "the artifact is 7.16x a zstd_fast bag and 10.25x a zstd_small one",
        "7.16x", "10.25x",
    ) == (PAIR_PUBLISHED, [])
    verdict, quoted = compressed_pair_verdict(
        "the artifact is 10.25x the bag", "7.16x", "10.25x"
    )
    assert (verdict, quoted) == (PAIR_HALF_PUBLISHED, ["10.25x"])
    assert compressed_pair_verdict("no figures here", "7.16x", "10.25x") == (
        PAIR_ABSENT, []
    )
    assert PAIR_ABSENT != PAIR_PUBLISHED


def test_the_measured_bags_are_published_beside_the_ratios_taken_from_them() -> None:
    """The byte counts behind the published ratios, held to the record.

    A ratio with no byte count beside it cannot be recomputed by a reader, and
    these three came from a run this host cannot repeat. `retention.md` carries
    them because it is where the artifact meets them; `sensor-baseline.md`
    carries them because it is where the run is recorded.
    """
    for profile in PUBLISHED_PROFILES:
        row = rosbag2_measurement(MEASURED_FIXTURE, profile)
        assert _quoting(f"{row.measured_bytes:,}") == set(
            DOCS_PUBLISHING_THE_MEASURED_BYTES
        ), (
            f"{row.measured_bytes:,} B is published in "
            f"{sorted(_quoting(f'{row.measured_bytes:,}'))}, not "
            f"{sorted(DOCS_PUBLISHING_THE_MEASURED_BYTES)}."
        )


def test_the_retired_compressed_projection_stands_only_in_the_dated_record() -> None:
    """**Issue #233's first criterion, as a negative.** 4.75x and 8.42x may not travel.

    They were one projection of `mcap_compressed_nocrc`, a preset name
    `ros2 bag record` answers with an error, and the measured bags bracket them.
    `prior-art.md` keeps them because a dated pass is evidence of what was
    believed on its date and is corrected by addition; everywhere else they are
    the figure of a projection that models neither profile rosbag2 ships, and a
    reader meeting one has to meet the word `superseded` in the same document.
    """
    for figure in RETIRED_COMPRESSED:
        assert _quoting(figure) == set(DOCS_KEEPING_THE_RETIRED_COMPRESSED), (
            f"{figure} is quoted in {sorted(_quoting(figure))}, not "
            f"{sorted(DOCS_KEEPING_THE_RETIRED_COMPRESSED)}. Republish it from "
            "the measured bags, or leave it where the dated pass that was given "
            "it stands."
        )
    for doc, path in CORPUS:
        text = path.read_text(encoding="utf-8")
        if any(figure in text for figure in RETIRED_COMPRESSED):
            assert RETIRED_IS_MARKED.search(text), (
                f"{doc} quotes a compressed figure issue #233 retired without "
                "saying anywhere that it is superseded."
            )
    assert not _quoting("mcap_compressed_nocrc") - set(
        DOCS_KEEPING_THE_RETIRED_COMPRESSED
    ), (
        "a preset name `ros2 bag record` refuses is published outside the dated "
        f"record: {sorted(_quoting('mcap_compressed_nocrc'))}."
    )


def test_a_retired_figure_republished_without_its_marking_is_caught() -> None:
    """THE NEGATIVE for the marking. The check must fail on the case it guards.

    Constructed rather than found, because no document in the corpus is in this
    state — which is the point: a check nothing exercises is a check nobody
    knows the sense of.
    """
    unmarked = "the artifact is 8.42x that bag, over the same 24 columns\n"
    assert any(figure in unmarked for figure in RETIRED_COMPRESSED)
    assert RETIRED_IS_MARKED.search(unmarked) is None
    marked = unmarked + "That figure is superseded by the measured bags.\n"
    assert RETIRED_IS_MARKED.search(marked) is not None


def test_the_uncompressed_figures_keep_their_values_as_they_become_measurements(
    full_stream: Path,
) -> None:
    """**Issue #233's second criterion.** Projection and bag render the same strings.

    The uncompressed projection came in 0.002% from the bag rosbag2 wrote, which
    is inside the band issue #232 fixed ahead of the run. So the two ratios
    round to the same published figure and what moved is their status, not their
    value — and that is asserted rather than assumed, because the whole
    republication rests on it: if the two ever stopped rounding together, one of
    the documents would be quoting the other side's number.
    """
    artifact = published_artifact_bytes()
    gzip_csv = gzip_bytes(full_stream)
    projected = compare_full_content(
        full_stream, preset=DEFAULT, artifact_bytes=artifact
    )
    measured = measured_comparison(
        None, artifact_bytes=artifact, gzip_csv_bytes=gzip_csv
    )
    assert measured.incumbent_bytes != projected.incumbent_bytes, (
        "the recorded bag and the projection came out at the same byte count, "
        "so this test is comparing a number against itself."
    )
    for from_bag, from_projection in (
        (measured.corrected_ratio, projected.corrected_ratio),
        (measured.incumbent_over_gzip, projected.incumbent_over_gzip),
    ):
        assert f"{from_bag:.2f}x" == f"{from_projection:.2f}x", (
            f"the measured bag gives {from_bag:.2f}x and the projection "
            f"{from_projection:.2f}x. They are published as one figure, so a "
            "divergence here is a republication, not a rounding."
        )


def test_claim_1s_status_line_is_licensed_by_every_measured_bag(
    full_stream: Path,
) -> None:
    """**Issue #233's sixth criterion**, asserted rather than assumed.

    `landed, reframed` rests on one measured fact — the artifact is not smaller
    than what it would replace — and this issue re-measures that fact against
    three bags rather than two projections, the smallest of which is 10x cheaper
    than the artifact. It stands only while every one of them says
    `ARTIFACT LARGER`, and the reporter's own negative above — fed an artifact
    smaller than the bag — is what the other outcome reads like.
    """
    artifact = published_artifact_bytes()
    gzip_csv = gzip_bytes(full_stream)
    for profile in PUBLISHED_PROFILES:
        c = measured_comparison(
            profile, artifact_bytes=artifact, gzip_csv_bytes=gzip_csv
        )
        assert c.verdict == ARTIFACT_LARGER, c.sentence()
        assert c.claim_1_status == CLAIM_1_STATUS_STANDS, c.sentence()
    row = next(
        line
        for line in (REPO / "README.md").read_text(encoding="utf-8").splitlines()
        if line.startswith("| **1** |")
    )
    assert "`landed, reframed`" in row, (
        "README.md's Claim 1 status is no longer `landed, reframed`, and the "
        "artifact is still larger than every bag rosbag2 wrote — which is the "
        "fact that wording states."
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
            preset=RETIRED_PRESET_NAMES[0], projected_bytes=1, measured_bytes=1,
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


# ==========================================================================
# THE ROSBAG2 RUN (issue #232).
#
# Everything above this line is a projection, validated once against a second
# implementation of the MCAP specification. What it could not validate is the
# thing this module got wrong twice: the *profile*. `mcap_default` and
# `mcap_compressed_nocrc` are names `ros2 bag record` answers with an error, so
# the procedure `docs/sensor-baseline.md` publishes could not be run as written.
#
# WHAT THE ROWS ARE. Ten bags rosbag2 wrote on 2026-09-06, whole files, two
# fixtures at five writer settings each. They are given data: there is no ROS 2
# on the host that runs these tests, so nothing here can regenerate them and
# nothing here tries. What the tests hold is the half that *can* move — the
# projection each row is set beside — and the discipline around the comparison.
#
# WHAT THEY HAVE TO HOLD, BEYOND THE BYTES. One row carries a band, fixed by the
# issue rather than by the result, and it is the only row that can read as a
# pass. The rest are recorded with their deltas and no verdict in this project's
# favour, and the negatives below feed each check the condition it guards
# against: a projection outside the band, a band on a row with no projection, a
# profile rosbag2 does not accept, and a measurement compared against a stream
# of a different fixture.
# ==========================================================================

#: One row of the rosbag2 block, read out of the document that publishes it.
#: Anchored on the fixture name and the profile column, so a row added anywhere
#: in the block is read rather than counted past.
ROSBAG2_ROW = re.compile(
    r"^(declared_violation|long_run_3000)\s+([\d,]+)\s+"
    r"(unset|none|fastwrite|zstd_fast|zstd_small)\s+"
    r"([\d,]+)\s+([\d,]+|-)\s+([-+][\d.]+%|-)\s+(\S+)\s*$",
    re.MULTILINE,
)

#: How each verdict is spelled in the published table. A row with no band and a
#: row that passed one must not read the same on the page, which is the whole
#: reason `NOT_BANDED` is a separate value rather than a blank cell.
ROSBAG2_VERDICT_WORDS = {
    WITHIN_TOLERANCE: "stands",
    OUTSIDE_TOLERANCE: "DOES-NOT-STAND",
    NOT_BANDED: "no-band",
    NOT_PROJECTED: "not-projected",
}


def _rosbag2_published() -> list[tuple]:
    text = VALIDATION_DOC.read_text(encoding="utf-8")
    rows = []
    for m in ROSBAG2_ROW.finditer(text):
        rows.append((
            m.group(1),
            int(m.group(2).replace(",", "")),
            m.group(3),
            int(m.group(4).replace(",", "")),
            None if m.group(5) == "-" else int(m.group(5).replace(",", "")),
            None if m.group(6) == "-" else float(m.group(6).rstrip("%")),
            m.group(7),
        ))
    return rows


def _rosbag2_stream(row: Rosbag2Measurement, stream: Path,
                    full_stream: Path) -> Path:
    return stream if row.fixture == "declared_violation" else full_stream


# --- the band, which one row carries and the rest are honest about ----------


def test_the_uncompressed_projection_is_inside_the_band_the_issue_fixed() -> None:
    """**THE ACCEPTANCE CRITERION.** 1% on `long_run_3000`, uncompressed.

    The band is `ROSBAG2_UNCOMPRESSED_TOLERANCE` and it was written into the
    issue before the rows were written into this repository, which is what makes
    it a tolerance rather than a description of the result. The projection comes
    in at -0.002% of a bag rosbag2 actually wrote.
    """
    row = rosbag2_measurement("long_run_3000", "none")
    assert row.tolerance == ROSBAG2_UNCOMPRESSED_TOLERANCE == 0.01
    assert row.verdict == WITHIN_TOLERANCE, row.sentence()
    assert abs(row.delta) < 0.01
    banded = [r for r in ROSBAG2_SIZE_MEASUREMENTS if r.tolerance is not None]
    assert banded == [row], (
        "a second row has acquired a band. Issue #232 banded exactly one, and a "
        "band added to another after its measurement was known is a band chosen "
        "by the result."
    )


def test_a_projection_that_missed_the_band_does_not_stand() -> None:
    """THE NEGATIVE for the band. Feed it a projection 2% out and it must say no.

    A check that only ever passes is not a check. The measurement is frozen, so
    the half moved here is the projection — which is also the half that can
    really move, because `reg.bench` recomputes it on every run.
    """
    row = rosbag2_measurement("long_run_3000", "none")
    missed = replace(row, projected_bytes=int(row.measured_bytes * 0.98))
    assert missed.verdict == OUTSIDE_TOLERANCE, missed.sentence()
    assert "DOES-NOT-STAND" == ROSBAG2_VERDICT_WORDS[missed.verdict]
    just_inside = replace(row, projected_bytes=int(row.measured_bytes / 1.009))
    assert just_inside.verdict == WITHIN_TOLERANCE, (
        "a projection 0.9% out came back outside a 1% band, so the band is not "
        "the number it says it is"
    )


def test_a_row_with_no_band_never_reads_as_a_pass() -> None:
    """COULD-NOT-EVALUATE DOES NOT RESOLVE TO PASS, on the record itself.

    Nine of the ten rows have no band. Four of those carry a compressed
    projection that the measured bags put 43% apart from itself, and the
    temptation is to let a small-looking delta stand in for a verdict. It cannot:
    `NOT_BANDED` is its own value, it is what the page prints, and no input to a
    row without a tolerance produces `WITHIN_TOLERANCE`.
    """
    unbanded = [r for r in ROSBAG2_SIZE_MEASUREMENTS if r.tolerance is None]
    assert len(unbanded) == 9
    for row in unbanded:
        assert row.verdict in (NOT_BANDED, NOT_PROJECTED), row.sentence()
        assert row.verdict != WITHIN_TOLERANCE
    exact = replace(
        rosbag2_measurement("long_run_3000", "zstd_fast"),
        projected_bytes=rosbag2_measurement(
            "long_run_3000", "zstd_fast"
        ).measured_bytes,
    )
    assert exact.delta == 0.0
    assert exact.verdict == NOT_BANDED, (
        "a row with no tolerance reported a pass when its delta happened to be "
        "zero. A band nobody set is not a band every number is inside."
    )


def test_a_band_on_a_row_with_no_projection_is_refused() -> None:
    """THE NEGATIVE for the record's own shape.

    `fastwrite` and the unset bags have no projection: one writes no message
    index and the other names no profile. A tolerance set on either would be a
    verdict about nothing, computed from a number that is not there.
    """
    row = rosbag2_measurement("long_run_3000", "fastwrite")
    assert row.projected_bytes is None
    assert row.delta is None
    assert row.verdict == NOT_PROJECTED
    with pytest.raises(BenchError, match="nothing for the band to judge"):
        replace(row, tolerance=0.01)
    with pytest.raises(BenchError, match="projection of zero"):
        replace(rosbag2_measurement("long_run_3000", "none"), projected_bytes=0)


def test_a_profile_rosbag2_does_not_accept_is_refused_by_the_record() -> None:
    """THE NEGATIVE for the names, on the measurement side.

    A bag cannot have been written under a profile rosbag2 rejects, so a row
    filed under one is a byte count nobody can reproduce. `None` is the only
    non-profile value the record takes, and it means one specific thing: the run
    that passed no profile at all.
    """
    row = rosbag2_measurement("declared_violation", "none")
    for name in RETIRED_PRESET_NAMES:
        with pytest.raises(BenchError, match="not a profile rosbag2 accepts"):
            replace(row, profile=name)
    assert replace(row, profile=None).label == "unset"
    for profile in ROSBAG2_STORAGE_PRESET_PROFILES:
        assert replace(row, profile=profile).label == profile


def test_an_unrecorded_pair_is_refused_rather_than_answered_by_the_nearest_row(
) -> None:
    """The run happened once and cannot be repeated here.

    A lookup that fell back to the nearest row would set one writer setting's
    bytes beside another's projection and publish the delta between two
    different bags — with both numbers real and the label on them false.
    """
    with pytest.raises(BenchError, match="no bag was recorded"):
        rosbag2_measurement("long_run_3000", "zstd_medium")
    with pytest.raises(BenchError, match="no bag was recorded"):
        rosbag2_measurement("no_such_fixture", "none")
    assert rosbag2_measurement("declared_violation", None).profile is None


# --- the pair, and that it cannot come apart quietly ------------------------


def test_every_recorded_rosbag2_projection_is_still_what_reg_bench_computes(
    stream: Path, full_stream: Path
) -> None:
    """The measurement is frozen; the projection is not, so it is recomputed.

    Six of the ten rows carry a projection and all six are recomputed here from
    the fixture the bag was recorded from. If one moves, the published delta
    describes a comparison between a bag that was written and an encoder this
    module no longer has — and nothing else would say so, because every other
    test holds the projection to its own constants.
    """
    checked = 0
    for row in ROSBAG2_SIZE_MEASUREMENTS:
        if row.projected_bytes is None:
            continue
        path = _rosbag2_stream(row, stream, full_stream)
        assert rosbag2_projection_drift(row, path) == PROJECTION_HOLDS, (
            f"{row.sentence()} — the recorded projection is not what reg.bench "
            f"computes for {row.fixture} today."
        )
        checked += 1
    assert checked == 6, f"{checked} rows carried a projection, not 6"


def test_a_projection_that_moved_away_from_the_rosbag2_record_is_drift(
    stream: Path,
) -> None:
    """THE NEGATIVE for the pair. One byte of movement is reported, not absorbed."""
    row = rosbag2_measurement("declared_violation", "zstd_fast")
    moved = replace(row, projected_bytes=row.projected_bytes + 1)
    assert rosbag2_projection_drift(moved, stream) == PROJECTION_DRIFTED, (
        "a projection one byte from the recorded one was reported as holding"
    )
    assert rosbag2_projection_drift(row, stream) == PROJECTION_HOLDS


def test_a_record_compared_against_another_fixtures_stream_is_refused(
    stream: Path, full_stream: Path
) -> None:
    """**THE NEGATIVE THE ISSUE NAMES.** A row is only about its own fixture.

    Handed the 3,000-frame stream, the 251-frame record would report drift that
    is nothing but the caller having passed the wrong file — and handed the
    other way round it would report a projection for a bag nobody recorded. The
    frame count is what tells them apart, so it is checked rather than assumed.
    """
    long_row = rosbag2_measurement("long_run_3000", "none")
    short_row = rosbag2_measurement("declared_violation", "none")
    with pytest.raises(BenchError, match="different fixture"):
        rosbag2_projection_drift(long_row, stream)
    with pytest.raises(BenchError, match="different fixture"):
        rosbag2_projection_drift(short_row, full_stream)
    assert stream_frames(stream) == short_row.frames
    assert stream_frames(full_stream) == long_row.frames


def test_a_row_with_no_projection_cannot_be_drift_checked(
    full_stream: Path,
) -> None:
    """THE OTHER REFUSAL. There is nothing to hold a `fastwrite` row to.

    Computing one now would invent exactly the number the row exists to say
    nobody has — the projection for a profile whose defining cost this encoder
    does not model.
    """
    for profile in (None, "fastwrite"):
        row = rosbag2_measurement("long_run_3000", profile)
        with pytest.raises(BenchError, match="no projection|carries a projection"):
            rosbag2_projection_drift(row, full_stream)


# --- what the run settles, each derived from the rows rather than asserted --


def test_the_message_index_width_is_confirmed_from_the_measured_bags() -> None:
    """`MCAP_MESSAGE_INDEX_PER_MESSAGE` from a second direction.

    16 was read off the specification. `none` minus `fastwrite` over the same
    messages isolates it from a real bag, because the index is the one thing
    those two profiles differ by. It comes back a fraction above 16 on both
    fixtures — the excess is the per-chunk fixed part this projection excludes,
    which is a larger share of fewer messages — so the two derivations agree to
    the byte and disagree in the direction the exclusions predict.
    """
    for fixture in ("declared_violation", "long_run_3000"):
        measured = rosbag2_index_bytes_per_message(fixture)
        assert round(measured) == MCAP_MESSAGE_INDEX_PER_MESSAGE, (
            f"{fixture}: the measured index is {measured:.2f} B per message and "
            f"the spec constant is {MCAP_MESSAGE_INDEX_PER_MESSAGE}. Those "
            "round to different integers, so one of the two derivations is "
            "wrong and the projection is charging the wrong per-message term."
        )
        assert measured >= MCAP_MESSAGE_INDEX_PER_MESSAGE, (
            f"{fixture}: the bag's index is cheaper than the spec constant, "
            "which is the direction that would make this projection overcharge "
            "the incumbent. The excluded per-chunk part can only add."
        )
    assert rosbag2_index_bytes_per_message("long_run_3000") == pytest.approx(
        16.06, abs=0.005
    )


def test_the_index_cannot_be_isolated_from_bags_of_different_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE NEGATIVE for the derivation. Two bags of different content subtract to nothing.

    The whole argument is that the two bags hold the same messages and differ by
    one term. Take that away — different message counts, or an indexed bag that
    is somehow the smaller of the two — and the difference divided by either
    count is a number about nothing. The record is doctored rather than the
    arithmetic, because the arithmetic is what is being checked.
    """
    with pytest.raises(BenchError, match="no bag was recorded"):
        rosbag2_index_bytes_per_message("declared_violation_2")
    indexed = rosbag2_measurement("long_run_3000", "none")
    plain = rosbag2_measurement("long_run_3000", "fastwrite")
    for doctored, expected in (
        (replace(indexed, messages=5_999), "cannot isolate a per-message term"),
        (replace(indexed, measured_bytes=1), "not the larger of the two"),
    ):
        monkeypatch.setattr(
            bench, "ROSBAG2_SIZE_MEASUREMENTS", (doctored, plain)
        )
        with pytest.raises(BenchError, match=expected):
            rosbag2_index_bytes_per_message("long_run_3000")


def test_the_default_is_uncompressed_and_that_is_measured() -> None:
    """*The default is uncompressed* stops being a citation.

    The bag written with no `--storage-preset-profile` and the bag written with
    `none` come out 4 B apart on both fixtures — under one message of framing,
    so they are the same encoding rather than two that happen to be close. A
    compressed default would have shown as a factor, not as four bytes.
    """
    for fixture in ("declared_violation", "long_run_3000"):
        unset = rosbag2_measurement(fixture, None)
        named = rosbag2_measurement(fixture, "none")
        gap = abs(unset.measured_bytes - named.measured_bytes)
        assert gap < MCAP_MESSAGE_RECORD_OVERHEAD, (
            f"{fixture}: the unset bag and the `none` bag are {gap} B apart, "
            "which is more than one message of framing. They are no longer "
            "evidence that the two are the same encoding."
        )
        compressed = rosbag2_measurement(fixture, "zstd_fast")
        assert compressed.measured_bytes < unset.measured_bytes / 2, (
            f"{fixture}: the compressed bag is not dramatically smaller than "
            "the default one, so this fixture cannot tell a compressed default "
            "from an uncompressed one and the check has nothing to say"
        )


def test_the_compressed_projection_matches_neither_profile() -> None:
    """The second finding: there is no single compressed preset to be right about.

    rosbag2 ships two compressed profiles and this module has one compressed
    projection, which lands between them. That is why neither compressed figure
    is claimed to project a profile, and it is why both measurements are
    published instead of the nearer one.
    """
    fast = rosbag2_measurement("long_run_3000", "zstd_fast")
    small = rosbag2_measurement("long_run_3000", "zstd_small")
    assert fast.projected_bytes == small.projected_bytes
    assert small.measured_bytes < fast.projected_bytes < fast.measured_bytes, (
        "the compressed projection no longer sits between the two profiles. If "
        "it has come to match one of them, the figures marked as not standing "
        "need re-deciding rather than this assertion updating."
    )
    spread = fast.measured_bytes / small.measured_bytes - 1
    assert spread > 0.4, (
        f"the two compressed profiles are {spread:.0%} apart, and the argument "
        "for publishing both rests on their being far apart"
    )


# --- what the document publishes, held to the record ------------------------


def test_the_document_publishes_every_rosbag2_row_and_its_delta() -> None:
    """The table and the record, cell by cell, in both directions.

    Neither is allowed to be the other's summary. A row edited on the page
    fails, a row recorded and not published fails, and a delta typed by hand
    that does not follow from its own two byte counts fails.
    """
    published = _rosbag2_published()
    assert len(published) == len(ROSBAG2_SIZE_MEASUREMENTS), (
        f"{VALIDATION_DOC.name} publishes {len(published)} rosbag2 rows and "
        f"reg.bench records {len(ROSBAG2_SIZE_MEASUREMENTS)}. A recorded bag "
        "that is not on the page is a measurement nobody outside this "
        "repository can see, which is the whole point of taking it."
    )
    for row, m in zip(published, ROSBAG2_SIZE_MEASUREMENTS):
        fixture, frames, profile, measured, projected, delta, verdict = row
        assert (fixture, frames, profile) == (m.fixture, m.frames, m.label), (
            f"{VALIDATION_DOC.name} row {row!r} is not {m.sentence()}"
        )
        assert (measured, projected) == (m.measured_bytes, m.projected_bytes)
        if m.delta is None:
            assert delta is None, (
                f"{VALIDATION_DOC.name} publishes a delta for {m.label} on "
                f"{m.fixture}, which has no projection to take one from."
            )
        else:
            assert delta == pytest.approx(round(m.delta * 100, 3), abs=0.0005), (
                f"{VALIDATION_DOC.name} publishes {delta:+.3f}% for {m.fixture} "
                f"{m.label}, and the two byte counts beside it give "
                f"{m.delta * 100:+.3f}%. A delta typed rather than derived is a "
                "number with nothing behind it."
            )
        assert verdict == ROSBAG2_VERDICT_WORDS[m.verdict], (
            f"{VALIDATION_DOC.name} calls {m.fixture} {m.label} {verdict!r}, "
            f"and its own numbers make it {m.verdict}."
        )


def test_the_rosbag2_provenance_states_the_host_and_what_cannot_be_rerun() -> None:
    """The date, the versions, the host — and the part easiest to leave out.

    This measurement cannot be regenerated by the machine that writes this
    repository's unattended changes, so a record that omits that reads as
    something a later run could check by re-running it. It cannot; it checks it
    by reading the procedure and doing it somewhere with a ROS 2 on it.
    """
    for needed in ("2026-09-06", "ros:jazzy", "Docker 29.4.0", "arm64 Darwin",
                   "rosbag2_py", "/joint_states", "/tf"):
        assert needed in ROSBAG2_PROVENANCE, f"provenance omits {needed}"
    assert "NO ROS 2" in ROSBAG2_PROVENANCE, (
        "the provenance does not say that the host running these tests cannot "
        "write another bag. A record that omits it reads as reproducible here."
    )
    text = VALIDATION_DOC.read_text(encoding="utf-8")
    for needed in ("ros:jazzy", "Docker 29.4.0", "arm64 Darwin", "rosbag2_py",
                   "unknown MCAP storage preset profile"):
        assert needed in text, f"{VALIDATION_DOC.name} omits {needed}"


def test_the_document_names_every_profile_rosbag2_accepts() -> None:
    """The names on the page are the names a practitioner types.

    The error rosbag2 raises lists all four, and the page quotes it. A document
    that named only the three priced here would leave a reader to guess what
    `fastwrite` is and why no figure is published under it.
    """
    text = VALIDATION_DOC.read_text(encoding="utf-8")
    for profile in ROSBAG2_STORAGE_PRESET_PROFILES:
        assert f"`{profile}`" in text or f"'{profile}'" in text, (
            f"{VALIDATION_DOC.name} does not name the {profile!r} profile"
        )
    for retired in RETIRED_PRESET_NAMES:
        for line in text.splitlines():
            if line.startswith("|") and retired in line:
                raise AssertionError(
                    f"{VALIDATION_DOC.name} still publishes a table row under "
                    f"{retired!r}, which rosbag2 answers with an error."
                )
