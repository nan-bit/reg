"""The incumbent encoding, and whether it can be got wrong quietly.

`reg.bench` prices the artifact against a gzipped CSV. Nobody retains a gzipped
CSV; practitioners retain rosbag2, in MCAP. Issue #117 added a second baseline so
the published comparison is not against a format no one runs.

The encoder is a **projection computed from specification** — no `mcap` library,
no `zstd`, because this project adds no dependency for a baseline. That makes it
exactly the kind of number that can drift without anyone noticing, so these tests
hold it to the two figures an independent hand-built encoder produced, and to the
failure modes that would each have made the incumbent look cheaper than it is.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from reg.bench import (
    CDR_ENCAPSULATION,
    MCAP_MESSAGE_RECORD_OVERHEAD,
    BenchError,
    gzip_bytes_of_columns,
    joint_state_cdr,
    mcap_joint_states_bytes,
    proprioceptive_columns,
)


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


# --- the two figures, held to an independent implementation -----------------


def test_the_cdr_payload_is_the_size_the_idl_says(stream: Path) -> None:
    """96 bytes for a two-joint arm: derived from the IDL, field by field.

    4 encapsulation + 8 Time + 5->8 empty frame_id + name[2] + position[2] +
    velocity[2] + empty effort, with CDR's own alignment. A change here is a
    change to what the incumbent costs per message and must be deliberate.
    """
    payload = joint_state_cdr(1.0, [0.1, 0.2], [0.3, 0.4], ["joint_0", "joint_1"])
    assert len(payload) == 96
    assert payload[:CDR_ENCAPSULATION] == b"\x00\x01\x00\x00"


def test_the_incumbent_costs_more_than_the_baseline_it_replaces(stream: Path) -> None:
    """The finding, and the reason #117 exists.

    Held to the byte against a hand-built encoder written independently of
    `reg.bench`. If this moves, either the encoder changed or the fixture did,
    and both are findings rather than numbers to update.
    """
    mcap = mcap_joint_states_bytes(stream)
    gz = gzip_bytes_of_columns(stream, proprioceptive_columns(_header(stream)))
    assert mcap == 7669, f"MCAP message records are {mcap} B, expected 7669"
    assert gz == 3053, f"gzipped proprioception is {gz} B, expected 3053"
    assert mcap > gz, (
        "the incumbent encoding came out cheaper than the gzipped CSV. That "
        "would retire the finding this comparison was built to publish, and it "
        "should be read as a bug in the encoder before it is read as a result."
    )


# --- the ways it could go wrong quietly, each of which flatters the incumbent


def test_uncompressed_message_records_are_not_the_comparison(stream: Path) -> None:
    """THE NEGATIVE. Comparing raw MCAP against gzipped CSV is a category error.

    It is also the first bug this encoder had: the message stream was returned
    uncompressed and the ratio came out 10.44x instead of 2.51x. rosbag2 writes
    chunk-compressed, so uncompressed here against gzipped there does not
    overstate the incumbent by a little — it prices two different things.
    """
    mcap = mcap_joint_states_bytes(stream)
    raw_estimate = 251 * (MCAP_MESSAGE_RECORD_OVERHEAD + 96)
    assert mcap < raw_estimate, (
        f"{mcap} B is at or above the {raw_estimate} B the same records occupy "
        "uncompressed, so the chunk compression rosbag2 applies is not being "
        "applied here."
    )


def test_the_framing_is_not_written_as_zero_bytes(stream: Path) -> None:
    """THE SECOND NEGATIVE, and the second bug this encoder had.

    Writing the 31 framing bytes as nulls dropped the compressed total from
    7,669 B to 5,354 B and the ratio from 2.51x to 1.75x, because a run of zeros
    compresses to nothing while a sequence number and two advancing timestamps
    do not. A bag never gets that discount.
    """
    mcap = mcap_joint_states_bytes(stream)
    assert mcap > 6000, (
        f"{mcap} B is close to what this stream costs when the MCAP framing is "
        "written as null bytes. Real framing carries a sequence number and two "
        "timestamps that advance, and they do not compress away."
    )


# --- could-not-evaluate never resolves to a pass ----------------------------


def test_a_stream_with_no_joint_columns_is_refused(tmp_path: Path) -> None:
    """Silence is could-not-evaluate. A zero would read as a free encoding."""
    p = tmp_path / "noq.csv"
    p.write_text("t,human_x,human_y\n0.0,1.0,2.0\n0.02,1.1,2.1\n")
    with pytest.raises(BenchError, match="no q_. columns"):
        mcap_joint_states_bytes(p)


def test_an_empty_stream_is_refused(tmp_path: Path) -> None:
    """A stream with a header and no frames is a step that did not run."""
    p = tmp_path / "empty.csv"
    p.write_text("t,q_0,qd_0\n")
    with pytest.raises(BenchError, match="no frames"):
        mcap_joint_states_bytes(p)


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
