"""The raw stream codec — round trip, byte-identity, and refusal.

This file is the baseline Claim 1 divides by, so two of these tests are really
about the compression number rather than about CSV: `test_two_writes_are_byte_
identical` (a benchmark measured against a file whose bytes vary is not a
benchmark) and `test_obstacles_are_written_every_frame` (pre-compressing the
thing we intend to beat would make the ratio a statement about our encoder).

The negative tests are the point of the rest. A codec that only ever gets shown
well-formed input proves nothing about whether it can reject anything — and the
failure mode here is not a crash, it is columns read into the wrong fields and a
plausible wrong answer months later.
"""

from __future__ import annotations

import numpy as np
import pytest

from reg.stream import (
    FLOAT_PRECISION,
    LINE_TERMINATOR,
    StreamFormatError,
    expected_header,
    read_comments,
    read_frames,
    write_frames,
)
from reg.types import BasePose, BaseVelocity, Obstacle, PoseSource, StateFrame

# Round-trip tolerance follows directly from the written precision: a value is
# stored as a decimal string with FLOAT_PRECISION places, so it can move by at
# most half a unit in the last place.
TOLERANCE = 0.5 * 10 ** (-FLOAT_PRECISION)

OBSTACLES = (
    Obstacle(entity_id="obs_0", kind="box", cx=1.25, cy=-0.5, radius=0.2),
    Obstacle(entity_id="obs_1", kind="pillar", cx=-2.0, cy=3.125, radius=0.35),
)


def frames(n: int = 4, n_joints: int = 3) -> tuple[StateFrame, ...]:
    """Hand-authored, not randomized. docs/plan.md: randomized fixtures make the
    compression numbers unfalsifiable, and they make a round-trip test a lottery."""
    out = []
    for i in range(n):
        out.append(
            StateFrame(
                t=round(i * 0.02, 6),
                q=np.array([0.1 * i, -0.25 * i, 1.0 + i][:n_joints], dtype=float),
                qd=np.array([0.0, 0.5, -0.5][:n_joints], dtype=float),
                human_pos=np.array([2.0 - 0.1 * i, 0.75], dtype=float),
                human_vel=np.array([-0.1, 0.0], dtype=float),
                base_vel=None,
                base_pose=None,
                objects=OBSTACLES,
            )
        )
    return tuple(out)


def assert_frames_close(got: list[StateFrame], want: tuple[StateFrame, ...]) -> None:
    """`==` on a StateFrame raises — numpy fields — so equality is spelled out."""
    assert len(got) == len(want)
    for a, b in zip(got, want):
        assert a.t == pytest.approx(b.t, abs=TOLERANCE)
        assert np.allclose(a.q, b.q, atol=TOLERANCE, rtol=0)
        assert np.allclose(a.qd, b.qd, atol=TOLERANCE, rtol=0)
        assert np.allclose(a.human_pos, b.human_pos, atol=TOLERANCE, rtol=0)
        assert np.allclose(a.human_vel, b.human_vel, atol=TOLERANCE, rtol=0)
        # The schema has no base columns, so a frame read back from it records
        # no base — and that must come back as `None` rather than as a zero
        # reading nobody took (issue #150). Asserted on both sides: the frames
        # this file writes carry no base either, so a codec that started
        # inventing zeros would fail here and not silently agree.
        assert a.base_vel is None and b.base_vel is None
        assert a.base_pose is None and b.base_pose is None
        assert len(a.objects) == len(b.objects)
        for x, y in zip(a.objects, b.objects):
            assert x.entity_id == y.entity_id
            assert x.kind == y.kind
            assert x.cx == pytest.approx(y.cx, abs=TOLERANCE)
            assert x.cy == pytest.approx(y.cy, abs=TOLERANCE)
            assert x.radius == pytest.approx(y.radius, abs=TOLERANCE)


# --- round trip ------------------------------------------------------------


def test_round_trip(tmp_path) -> None:
    want = frames()
    got = list(read_frames(write_frames(want, tmp_path / "run.csv")))
    assert_frames_close(got, want)


def test_round_trip_with_no_obstacles(tmp_path) -> None:
    """Zero obstacles is a schema, not a missing one — the blocks are just empty."""
    want = tuple(
        StateFrame(
            t=f.t,
            q=f.q,
            qd=f.qd,
            human_pos=f.human_pos,
            human_vel=f.human_vel,
            base_vel=None,
            base_pose=None,
        )
        for f in frames()
    )
    got = list(read_frames(write_frames(want, tmp_path / "bare.csv")))
    assert_frames_close(got, want)


def test_round_trip_is_a_fixed_point(tmp_path) -> None:
    """write(read(write(x))) is byte-identical to write(x).

    Stronger than the round trip: it says the codec loses nothing on the second
    pass either, so an artifact can be re-exported without drifting.
    """
    once = write_frames(frames(), tmp_path / "a.csv")
    twice = write_frames(read_frames(once), tmp_path / "b.csv")
    assert once.read_bytes() == twice.read_bytes()


# --- determinism -----------------------------------------------------------


def test_two_writes_are_byte_identical(tmp_path) -> None:
    """Same frames in, same bytes out. This is the one that guards the benchmark."""
    data = frames()
    a = write_frames(data, tmp_path / "a.csv")
    b = write_frames(data, tmp_path / "b.csv")
    assert a.read_bytes() == b.read_bytes()


def test_floats_are_written_at_fixed_width(tmp_path) -> None:
    """The mechanism behind byte-identity: no shortest-repr, no exponent form."""
    path = write_frames(frames(), tmp_path / "run.csv")
    body = path.read_text().split(LINE_TERMINATOR)[1]
    numeric = [c for c in body.split(",") if not c.startswith("obs_") and c not in ("box", "pillar")]
    assert numeric, "expected numeric cells in the first data row"
    for cell in numeric:
        assert "e" not in cell.lower(), f"{cell!r} is in exponent form"
        assert len(cell.split(".")[1]) == FLOAT_PRECISION, f"{cell!r}"


def test_negative_zero_does_not_change_the_bytes(tmp_path) -> None:
    """-0.0 == 0.0 numerically but formats as '-0.000000'. Two runs that agree
    must not differ in bytes because of which side of zero a value came from."""
    base = frames(n=1)[0]
    positive = write_frames([base], tmp_path / "pos.csv")
    negated = write_frames(
        [
            StateFrame(
                t=base.t,
                q=base.q,
                qd=np.array([-0.0 if v == 0.0 else v for v in base.qd]),
                human_pos=base.human_pos,
                human_vel=np.array([base.human_vel[0], -0.0]),
                base_vel=None,
                base_pose=None,
                objects=base.objects,
            )
        ],
        tmp_path / "neg.csv",
    )
    assert positive.read_bytes() == negated.read_bytes()


def test_line_terminator_is_pinned(tmp_path) -> None:
    """csv defaults to CRLF; a platform-dependent artifact is not an artifact."""
    path = write_frames(frames(), tmp_path / "run.csv")
    assert b"\r\n" not in path.read_bytes()


# --- header ----------------------------------------------------------------


def test_header_names_match_the_column_count(tmp_path) -> None:
    n_joints, n_obstacles = 3, len(OBSTACLES)
    path = write_frames(frames(n_joints=n_joints), tmp_path / "run.csv")
    lines = path.read_text().rstrip(LINE_TERMINATOR).split(LINE_TERMINATOR)
    header = lines[0].split(",")

    assert header == expected_header(n_joints, n_obstacles)
    # 1 time + q + qd + 4 human + 5 per obstacle.
    assert len(header) == 1 + 2 * n_joints + 4 + 5 * n_obstacles
    for i, row in enumerate(lines[1:]):
        assert len(row.split(",")) == len(header), f"data row {i}"


def test_header_carries_the_specified_columns() -> None:
    header = expected_header(2, 2)
    assert header[:1] == ["t"]
    assert header[1:5] == ["q_0", "q_1", "qd_0", "qd_1"]
    assert header[5:9] == ["human_x", "human_y", "human_vx", "human_vy"]
    for j in range(2):
        assert {f"obs_{j}_x", f"obs_{j}_y", f"obs_{j}_r"} <= set(header)


def test_obstacles_are_written_every_frame(tmp_path) -> None:
    """Static, but logged per frame — docs/plan.md inflates the raw stream on
    purpose rather than pre-compressing the baseline it means to beat."""
    path = write_frames(frames(n=4), tmp_path / "run.csv")
    rows = path.read_text().rstrip(LINE_TERMINATOR).split(LINE_TERMINATOR)[1:]
    assert len(rows) == 4
    for row in rows:
        assert "obs_0" in row and "obs_1" in row


# --- negative: the reader must be able to say no ---------------------------


def corrupt_header(tmp_path, path, mutate) -> object:
    lines = path.read_text().split(LINE_TERMINATOR)
    lines[0] = ",".join(mutate(lines[0].split(",")))
    bad = tmp_path / "bad.csv"
    bad.write_text(LINE_TERMINATOR.join(lines))
    return bad


def rename(columns: list[str]) -> list[str]:
    out = list(columns)
    out[out.index("human_vx")] = "human_dx"
    return out


def swap(columns: list[str]) -> list[str]:
    out = list(columns)
    i, j = out.index("q_0"), out.index("qd_0")
    out[i], out[j] = out[j], out[i]
    return out


def drop(columns: list[str]) -> list[str]:
    return [c for c in columns if c != "human_y"]


def add(columns: list[str]) -> list[str]:
    return columns + ["extra"]


def reorder_obstacle(columns: list[str]) -> list[str]:
    out = list(columns)
    i, j = out.index("obs_0_x"), out.index("obs_0_y")
    out[i], out[j] = out[j], out[i]
    return out


@pytest.mark.parametrize(
    "mutate", [rename, swap, drop, add, reorder_obstacle], ids=lambda f: f.__name__
)
def test_a_header_that_is_not_the_schema_is_refused(tmp_path, mutate) -> None:
    """THE negative test. Every one of these mutations leaves a file that parses
    perfectly well as CSV — the reader would hand back frames whose fields came
    from the wrong columns. It has to refuse instead."""
    good = write_frames(frames(), tmp_path / "run.csv")
    bad = corrupt_header(tmp_path, good, mutate)
    with pytest.raises(StreamFormatError):
        list(read_frames(bad))


def test_the_header_is_checked_before_any_row_is_yielded(tmp_path) -> None:
    """Eager validation: calling read_frames is enough to raise. A generator that
    only complains once iterated reports the fault far from its cause."""
    good = write_frames(frames(), tmp_path / "run.csv")
    bad = corrupt_header(tmp_path, good, rename)
    with pytest.raises(StreamFormatError):
        read_frames(bad)  # not wrapped in list() — no iteration happens


def test_mismatched_joint_columns_are_refused(tmp_path) -> None:
    """q_0..q_2 with only qd_0..qd_1 has no consistent joint count."""
    good = write_frames(frames(n_joints=3), tmp_path / "run.csv")
    bad = corrupt_header(tmp_path, good, lambda cols: [c for c in cols if c != "qd_2"])
    with pytest.raises(StreamFormatError):
        read_frames(bad)


def test_an_empty_file_is_an_error_not_zero_frames(tmp_path) -> None:
    """Could-not-evaluate must not resolve to pass: a truncated stream is not an
    empty one, and a compression baseline of 'no frames' would be silently huge."""
    empty = tmp_path / "empty.csv"
    empty.write_text("")
    with pytest.raises(StreamFormatError, match="empty"):
        read_frames(empty)


def test_a_short_row_is_refused(tmp_path) -> None:
    good = write_frames(frames(), tmp_path / "run.csv")
    lines = good.read_text().rstrip(LINE_TERMINATOR).split(LINE_TERMINATOR)
    lines[2] = ",".join(lines[2].split(",")[:-3])
    bad = tmp_path / "short.csv"
    bad.write_text(LINE_TERMINATOR.join(lines) + LINE_TERMINATOR)
    with pytest.raises(StreamFormatError, match="field"):
        list(read_frames(bad))


def test_a_non_numeric_cell_is_refused(tmp_path) -> None:
    good = write_frames(frames(), tmp_path / "run.csv")
    bad = tmp_path / "text.csv"
    bad.write_text(good.read_text().replace("0.750000", "left"))
    with pytest.raises(StreamFormatError, match="not a number"):
        list(read_frames(bad))


def test_a_non_finite_cell_is_refused(tmp_path) -> None:
    """float('nan') parses. A NaN position propagates into every geometric
    result as an empty polygon and never raises anywhere downstream."""
    good = write_frames(frames(), tmp_path / "run.csv")
    bad = tmp_path / "nan.csv"
    bad.write_text(good.read_text().replace("0.750000", "nan"))
    with pytest.raises(StreamFormatError, match="finite"):
        list(read_frames(bad))


# --- negative: the writer must be able to say no ---------------------------


def test_writing_zero_frames_names_what_is_missing(tmp_path) -> None:
    """No frames means no schema. Emitting a header of guessed width would put an
    invented joint count into the artifact."""
    with pytest.raises(StreamFormatError, match="no frames"):
        write_frames([], tmp_path / "run.csv")
    assert not (tmp_path / "run.csv").exists()


def test_a_changing_joint_count_is_refused(tmp_path) -> None:
    a, b = frames(n=2, n_joints=3)
    wrong = StateFrame(
        t=b.t,
        q=b.q[:2],
        qd=b.qd[:2],
        human_pos=b.human_pos,
        human_vel=b.human_vel,
        base_vel=None,
        base_pose=None,
        objects=b.objects,
    )
    with pytest.raises(StreamFormatError, match="joint"):
        write_frames([a, wrong], tmp_path / "run.csv")


def test_a_changing_obstacle_count_is_refused(tmp_path) -> None:
    a, b = frames(n=2)
    wrong = StateFrame(
        t=b.t,
        q=b.q,
        qd=b.qd,
        human_pos=b.human_pos,
        human_vel=b.human_vel,
        base_vel=None,
        base_pose=None,
        objects=b.objects[:1],
    )
    with pytest.raises(StreamFormatError, match="obstacle"):
        write_frames([a, wrong], tmp_path / "run.csv")


def test_a_non_2d_human_is_refused(tmp_path) -> None:
    f = frames(n=1)[0]
    wrong = StateFrame(
        t=f.t,
        q=f.q,
        qd=f.qd,
        human_pos=np.array([1.0, 2.0, 3.0]),
        human_vel=f.human_vel,
        base_vel=None,
        base_pose=None,
        objects=f.objects,
    )
    with pytest.raises(StreamFormatError, match="exactly 2"):
        write_frames([wrong], tmp_path / "run.csv")


def test_a_non_finite_value_is_not_recorded(tmp_path) -> None:
    f = frames(n=1)[0]
    wrong = StateFrame(
        t=f.t,
        q=np.array([np.nan, *f.q[1:]]),
        qd=f.qd,
        human_pos=f.human_pos,
        human_vel=f.human_vel,
        base_vel=None,
        base_pose=None,
        objects=f.objects,
    )
    with pytest.raises(StreamFormatError, match="finite"):
        write_frames([wrong], tmp_path / "run.csv")


# --- the provenance block ---------------------------------------------------
#
# `reg.sim` writes the scenario and seed above the header (docs/lossiness.md
# retains the run's provenance once per artifact). The codec has to agree with
# the producer about that block, or the artifact stops being readable by the
# thing that wrote it — so both directions are tested here rather than only in
# tests/test_sim_cli.py.


def test_comments_round_trip(tmp_path) -> None:
    lines = ["reg-sim provenance v1", "scenario=contact", "seed=0"]
    path = write_frames(frames(), tmp_path / "run.csv", comments=lines)
    assert read_comments(path) == lines


def test_comments_do_not_disturb_the_frames(tmp_path) -> None:
    want = frames()
    path = write_frames(want, tmp_path / "run.csv", comments=["seed=0"])
    assert_frames_close(list(read_frames(path)), want)


def test_a_stream_without_comments_reports_none(tmp_path) -> None:
    """Absence is could-not-evaluate: no block means the file says nothing about
    what produced it, which must not read as an empty-but-present block."""
    path = write_frames(frames(), tmp_path / "run.csv")
    assert read_comments(path) == []


def test_the_block_only_changes_the_bytes_it_adds(tmp_path) -> None:
    """The compression baseline divides by these bytes, so the block must be the
    only difference — not a reformatting of the rows."""
    bare = write_frames(frames(), tmp_path / "bare.csv").read_text()
    with_block = write_frames(
        frames(), tmp_path / "block.csv", comments=["seed=0"]
    ).read_text()
    assert with_block == f"# seed=0{LINE_TERMINATOR}{bare}"


def test_a_hash_after_the_header_is_a_row_not_a_comment(tmp_path) -> None:
    """Only the leading block is provenance. A `#` line among the rows is a
    malformed row, and skipping it would silently drop a frame from the record."""
    good = write_frames(frames(), tmp_path / "run.csv")
    lines = good.read_text().rstrip(LINE_TERMINATOR).split(LINE_TERMINATOR)
    lines.insert(2, "# not provenance")
    bad = tmp_path / "mid.csv"
    bad.write_text(LINE_TERMINATOR.join(lines) + LINE_TERMINATOR)
    with pytest.raises(StreamFormatError):
        list(read_frames(bad))


def test_row_errors_name_the_line_in_the_file_not_after_the_block(tmp_path) -> None:
    """Line numbers are for a human opening the file. Counting from the header
    would send them to the wrong row of a 300-row artifact."""
    path = write_frames(frames(), tmp_path / "run.csv", comments=["a", "b", "c"])
    lines = path.read_text().rstrip(LINE_TERMINATOR).split(LINE_TERMINATOR)
    lines[5] = ",".join(lines[5].split(",")[:-2])  # 3 comments + header + 1 row before
    bad = tmp_path / "short.csv"
    bad.write_text(LINE_TERMINATOR.join(lines) + LINE_TERMINATOR)
    with pytest.raises(StreamFormatError, match="line 6"):
        list(read_frames(bad))


def test_provenance_alone_is_not_a_stream(tmp_path) -> None:
    """A file that says what produced it and carries no rows is a
    could-not-evaluate, not a stream of zero frames."""
    path = tmp_path / "banner-only.csv"
    path.write_text(f"# scenario=contact{LINE_TERMINATOR}# seed=0{LINE_TERMINATOR}")
    with pytest.raises(StreamFormatError, match="provenance"):
        read_frames(path)


def test_a_comment_containing_a_newline_is_refused(tmp_path) -> None:
    """It would be written as two lines, the second of which is neither a comment
    nor a row — an artifact that no longer parses as what it claims to be."""
    path = tmp_path / "run.csv"
    with pytest.raises(StreamFormatError, match="line break"):
        write_frames(frames(), path, comments=["seed=0\nsomething,else"])
    assert not path.exists(), "a rejected comment must not leave a partial file"


def test_a_non_string_comment_is_refused(tmp_path) -> None:
    with pytest.raises(StreamFormatError, match="not a str"):
        write_frames(frames(), tmp_path / "run.csv", comments=[0])


def test_a_frame_carrying_base_motion_is_refused(tmp_path) -> None:
    """Negative test: this schema has no base columns, so it will not pretend to.

    Issue #150 put `base_vel` and `base_pose` on `StateFrame` and deliberately
    left this format alone — these bytes are the denominator of every
    compression figure Claim 1 quotes, and a new column also needs a
    `reg.bench.COLUMN_RULES` entry saying which layer it is or the Layer A /
    Layer B column split moves with nothing going red (docs/mobile-base.md §5).

    That leaves the codec one thing it must not do: write the base nowhere and
    say nothing. The frame would round-trip into a *fixed-base* run — same
    header, same width, every existing check green — and the fact that the base
    was moving would be gone with no record that it had ever been there. A
    could-not-evaluate must not resolve to a pass, so this refuses.

    Both fields, separately, because they are dropped by different halves of the
    same omission and a check that only looked at one would let the other
    through.
    """
    base = frames(n=1)[0]

    moving = StateFrame(
        t=base.t,
        q=base.q,
        qd=base.qd,
        human_pos=base.human_pos,
        human_vel=base.human_vel,
        base_vel=BaseVelocity(vx=0.4, vy=0.0, omega=0.2),
        base_pose=None,
        objects=base.objects,
    )
    with pytest.raises(StreamFormatError, match="no columns"):
        write_frames([moving], tmp_path / "moving.csv")

    posed = StateFrame(
        t=base.t,
        q=base.q,
        qd=base.qd,
        human_pos=base.human_pos,
        human_vel=base.human_vel,
        base_vel=None,
        base_pose=BasePose(x=1.0, y=2.0, theta=0.3, source=PoseSource.LOCALIZED),
        objects=base.objects,
    )
    with pytest.raises(StreamFormatError, match="no columns"):
        write_frames([posed], tmp_path / "posed.csv")

    # And the refusal is about the base and not about the writer being unusable:
    # the same frame with neither field recorded writes, as every fixture does.
    assert write_frames([base], tmp_path / "fixed.csv").exists()


def test_the_refusal_leaves_no_partial_file(tmp_path) -> None:
    """A rejected frame must not leave a truncated stream behind.

    `write_frames` builds every row before it opens the file for exactly this
    reason, and the base check is on that path. If it were not, a run whose
    tenth frame carried a base pose would leave nine frames on disk under a
    valid header — a readable artifact that is a silently shortened run, which
    is worse than no file at all.
    """
    good = frames(n=3)
    bad = StateFrame(
        t=0.06,
        q=good[0].q,
        qd=good[0].qd,
        human_pos=good[0].human_pos,
        human_vel=good[0].human_vel,
        base_vel=BaseVelocity(vx=0.1, vy=0.0, omega=0.0),
        base_pose=None,
        objects=good[0].objects,
    )
    path = tmp_path / "partial.csv"
    with pytest.raises(StreamFormatError, match="no columns"):
        write_frames([*good, bad], path)
    assert not path.exists()
