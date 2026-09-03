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

from reg import stream as stream_module

# `_schema_from_header` is private and imported anyway: it is the function that
# decides which robot wrote a header, and the properties this file has to assert
# about it — every writable header reads back as its own schema, no two schemas
# share one, a stray base column is refused — are properties of the derivation
# itself. Driving them only through `read_frames` would mean writing a file per
# shape and would test the file plumbing as much as the schema.
from reg.stream import (
    FLOAT_PRECISION,
    LINE_TERMINATOR,
    StreamFormatError,
    StreamSchema,
    _schema_from_header,
    expected_header,
    read_comments,
    read_frames,
    write_frames,
)
from reg.types import (
    BasePose,
    BaseVelocity,
    Obstacle,
    PoseSource,
    StateFrame,
    VelocitySource,
)

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


def assert_base_matches(got, want, numeric: tuple[str, ...]) -> None:
    """One half of the base, compared as recorded-or-not first and values second.

    Presence is checked before any field is, because the failure this is here for
    is not a wrong number: it is a run whose base was never written coming back
    as zeros, or a recorded one coming back as `None`. Both read as a perfectly
    ordinary frame downstream.
    """
    assert (got is None) == (want is None), (
        f"one side records a base and the other does not: got={got!r}, "
        f"want={want!r}. `None` is 'not recorded' and a value is 'recorded'; "
        "they are different facts about the run."
    )
    if want is None:
        return
    for field in numeric:
        assert getattr(got, field) == pytest.approx(
            getattr(want, field), abs=TOLERANCE
        ), field
    if hasattr(want, "source"):
        # Identity, not equality of the string: reconstructing a `PoseSource`
        # that is merely equal-looking is how a provenance nobody stated becomes
        # indistinguishable from one somebody did.
        assert got.source is want.source


def assert_frames_close(got: list[StateFrame], want: tuple[StateFrame, ...]) -> None:
    """`==` on a StateFrame raises — numpy fields — so equality is spelled out."""
    assert len(got) == len(want)
    for a, b in zip(got, want):
        assert a.t == pytest.approx(b.t, abs=TOLERANCE)
        assert np.allclose(a.q, b.q, atol=TOLERANCE, rtol=0)
        assert np.allclose(a.qd, b.qd, atol=TOLERANCE, rtol=0)
        assert np.allclose(a.human_pos, b.human_pos, atol=TOLERANCE, rtol=0)
        assert np.allclose(a.human_vel, b.human_vel, atol=TOLERANCE, rtol=0)
        # Whether each half of the base was recorded has to survive the round
        # trip as a *fact about the run*, not as a number. A stream written from
        # frames that record no base must read back `None` and never zeros — a
        # zero says the base was measured and found still (issue #150) — and a
        # stream that does record one must come back with the same values and
        # the same `PoseSource` (issue #176). `assert_base_matches` refuses both
        # directions, so a codec that started inventing either fails here.
        assert_base_matches(a.base_vel, b.base_vel, ("vx", "vy", "omega"))
        assert_base_matches(a.base_pose, b.base_pose, ("x", "y", "theta"))
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


def test_a_frame_that_gains_a_base_mid_stream_is_refused(tmp_path) -> None:
    """**Negative test.** The header is derived from frame 0, so a later frame
    that gained a base is a stream one header cannot describe.

    Until issue #176 this schema had no base columns at all and refused every
    frame carrying either half. It has them now, and the refusal moved rather
    than went: what is still not allowed is writing the base **nowhere** and
    saying nothing. The frame would round-trip into a run with no base — same
    header, same width, every existing check green — and the fact that the base
    was moving would be gone with no record that it had ever been there. A
    could-not-evaluate must not resolve to a pass.

    Both halves, separately, because they are dropped by different halves of the
    same omission and a check that only looked at one would let the other
    through.
    """
    base = frames(n=2)[0]

    def gained(**base_fields) -> StateFrame:
        return StateFrame(
            t=base.t,
            q=base.q,
            qd=base.qd,
            human_pos=base.human_pos,
            human_vel=base.human_vel,
            objects=base.objects,
            **{"base_vel": None, "base_pose": None, **base_fields},
        )

    moving = gained(
        base_vel=BaseVelocity(
            vx=0.4, vy=0.0, omega=0.2, source=VelocitySource.PROPRIOCEPTIVE
        )
    )
    with pytest.raises(StreamFormatError, match="no columns for one"):
        write_frames([base, moving], tmp_path / "moving.csv")

    posed = gained(
        base_pose=BasePose(x=1.0, y=2.0, theta=0.3, source=PoseSource.LOCALIZED)
    )
    with pytest.raises(StreamFormatError, match="no columns for one"):
        write_frames([base, posed], tmp_path / "posed.csv")

    # And the refusal is about the shape changing and not about the writer being
    # unusable: the same frames with neither field recorded write, as every
    # fixed-arm fixture does.
    assert write_frames([base, base], tmp_path / "fixed.csv").exists()


def test_a_frame_that_loses_a_base_mid_stream_is_refused(tmp_path) -> None:
    """**The other negative, and the one with no honest fallback.**

    Frame 0 recorded a base, so the header has columns for it; a later frame
    that recorded none leaves cells with nothing true to put in them. Zeros are
    the tempting answer and they are the wrong one — *the base was measured and
    found still* is a different fact from *the base was not recorded* — and a
    blank cell reads back through `_number` as a value that is not one.
    """
    fixed = frames(n=2)[0]
    mobile = StateFrame(
        t=fixed.t,
        q=fixed.q,
        qd=fixed.qd,
        human_pos=fixed.human_pos,
        human_vel=fixed.human_vel,
        base_vel=BaseVelocity(
            vx=0.4, vy=0.0, omega=0.2, source=VelocitySource.PROPRIOCEPTIVE
        ),
        base_pose=BasePose(x=1.0, y=2.0, theta=0.3, source=PoseSource.DEAD_RECKONED),
        objects=fixed.objects,
    )
    with pytest.raises(StreamFormatError, match="records no base velocity"):
        write_frames([mobile, fixed], tmp_path / "lost.csv")

    dropped_pose = StateFrame(
        t=fixed.t,
        q=fixed.q,
        qd=fixed.qd,
        human_pos=fixed.human_pos,
        human_vel=fixed.human_vel,
        base_vel=mobile.base_vel,
        base_pose=None,
        objects=fixed.objects,
    )
    with pytest.raises(StreamFormatError, match="records no base pose"):
        write_frames([mobile, dropped_pose], tmp_path / "lost-pose.csv")


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
        base_vel=BaseVelocity(
            vx=0.1, vy=0.0, omega=0.0, source=VelocitySource.PROPRIOCEPTIVE
        ),
        base_pose=None,
        objects=good[0].objects,
    )
    path = tmp_path / "partial.csv"
    with pytest.raises(StreamFormatError, match="no columns for one"):
        write_frames([*good, bad], path)
    assert not path.exists()


# --- the base blocks (issue #176) -------------------------------------------
#
# The constraint the whole design is shaped by is that Claim 1 stays a fixed-arm
# claim: `expected_header(2, 3)` is the 24 columns the priced fixture's published
# figures are measured on, and a base column that arrived unconditionally would
# move the gzipped baseline for eleven robots bolted to the origin. So the base
# is two optional blocks — and the price of an optional block is that a reader
# has to be able to tell which robot wrote a header. These tests are that price:
# every header the writer can write reads back as the schema that wrote it, no
# two schemas share a header, and a base column in a position no block accounts
# for is refused rather than guessed at.

#: Every shape the writer can produce, small enough to enumerate exhaustively.
#: Enumerated rather than sampled: injectivity is a property of the whole map,
#: and a sampled one is a property of the sample.
SHAPES = [
    (n_joints, n_obstacles, base_vel, base_pose)
    for n_joints in (0, 1, 2, 6)
    for n_obstacles in (0, 1, 3, 12)
    for base_vel in (False, True)
    for base_pose in (False, True)
]


def test_the_priced_fixtures_header_is_the_twenty_four_columns_it_has_always_been() -> None:
    """**The constraint, asserted directly rather than derived.**

    `docs/retention.md` publishes `264 GB`, `~40x` and a gzipped baseline in
    bytes, all measured against a stream with this header. Spelled out in full
    here — not `len(...) == 24`, and not rebuilt from the same constants the
    function is built from — so that a base column arriving unconditionally
    fails on the column that appeared and names it, rather than on a count.
    """
    assert expected_header(2, 3) == [
        "t",
        "q_0",
        "q_1",
        "qd_0",
        "qd_1",
        "human_x",
        "human_y",
        "human_vx",
        "human_vy",
        "obs_0_id", "obs_0_kind", "obs_0_x", "obs_0_y", "obs_0_r",
        "obs_1_id", "obs_1_kind", "obs_1_x", "obs_1_y", "obs_1_r",
        "obs_2_id", "obs_2_kind", "obs_2_x", "obs_2_y", "obs_2_r",
    ]


def test_the_base_blocks_sit_between_the_joints_and_the_human() -> None:
    """Layer A first and contiguous — `t`, the joints, then the body-frame rates
    — with the room-frame pose behind them and the world behind that. The
    ordering is not cosmetic: `reg.bench.proprioceptive_columns` returns the
    Layer A subset in header order, and the split is what Claim 1's
    like-for-like comparison is computed over."""
    header = expected_header(2, 1, base_vel=True, base_pose=True)
    assert header[:5] == ["t", "q_0", "q_1", "qd_0", "qd_1"]
    # `base_vel_source` is inside the Layer A run and not appended after the
    # pose: it is the provenance of the three rates before it, and a provenance
    # column separated from the block it describes is one a reader has to guess
    # the owner of (issue #156).
    assert header[5:9] == ["base_vx", "base_vy", "base_omega", "base_vel_source"]
    assert header[9:13] == [
        "base_pose_x",
        "base_pose_y",
        "base_pose_theta",
        "base_pose_source",
    ]
    assert header[13:17] == ["human_x", "human_y", "human_vx", "human_vy"]


@pytest.mark.parametrize(("n_joints", "n_obstacles", "base_vel", "base_pose"), SHAPES)
def test_every_header_the_writer_can_write_reads_back_as_the_schema_that_wrote_it(
    n_joints: int, n_obstacles: int, base_vel: bool, base_pose: bool
) -> None:
    """Round trip at the level of the *schema*, not the values.

    An optional block whose presence the reader cannot recover is a stream
    nobody can read back, and it fails silently: the reader would take a base
    block for an obstacle block, or the other way round, and every number after
    it would land in the wrong field with no exception anywhere.
    """
    header = expected_header(
        n_joints, n_obstacles, base_vel=base_vel, base_pose=base_pose
    )
    assert _schema_from_header(header, "<test>") == StreamSchema(
        n_joints=n_joints,
        n_obstacles=n_obstacles,
        base_vel=base_vel,
        base_pose=base_pose,
    )
    assert len(header) == StreamSchema(
        n_joints=n_joints,
        n_obstacles=n_obstacles,
        base_vel=base_vel,
        base_pose=base_pose,
    ).width()


def test_no_two_distinct_robots_produce_the_same_header() -> None:
    """Injectivity, over every shape the writer can produce.

    This is the property an optional block puts at risk and the one the reader's
    correctness rests on. Asserted as a set comparison so a collision names both
    schemas rather than reporting a count that is one short.
    """
    headers: dict[tuple[str, ...], tuple[int, int, bool, bool]] = {}
    for shape in SHAPES:
        n_joints, n_obstacles, base_vel, base_pose = shape
        key = tuple(
            expected_header(
                n_joints, n_obstacles, base_vel=base_vel, base_pose=base_pose
            )
        )
        assert key not in headers, (
            f"{shape} and {headers[key]} produce the same header, so a file "
            "written by one reads back as the other."
        )
        headers[key] = shape


def test_no_combination_of_base_blocks_is_a_multiple_of_the_obstacle_block() -> None:
    """The arithmetic backstop behind the name comparison.

    Presence is decided by matching names at a fixed offset, so this is not what
    keeps the reader correct today. It is what keeps a *future* careless edit
    from making it wrong: were an optional block's width a multiple of the
    obstacle block's, a reader that lost the name comparison could read the base
    as an extra obstacle and the header would still satisfy the remainder check.
    A block widened to 5 or 10 columns fails here, which is the point.
    """
    obstacle_block = len(stream_module._OBSTACLE_COLUMNS)
    vel, pose = (
        len(stream_module._BASE_VEL_COLUMNS),
        len(stream_module._BASE_POSE_COLUMNS),
    )
    for width in (vel, pose, vel + pose):
        assert width % obstacle_block != 0, (
            f"a base block combination of {width} column(s) is a whole number "
            f"of {obstacle_block}-column obstacle blocks"
        )


# --- negative: a base column where no block could have put it ---------------


@pytest.mark.parametrize(
    ("what", "header"),
    [
        (
            "a truncated velocity block",
            ["t", "q_0", "qd_0", "base_vx", "base_vy",
             "human_x", "human_y", "human_vx", "human_vy"],
        ),
        (
            "a truncated pose block",
            ["t", "q_0", "qd_0", "base_pose_x", "base_pose_y", "base_pose_theta",
             "human_x", "human_y", "human_vx", "human_vy"],
        ),
        (
            "the blocks in the wrong order",
            ["t", "q_0", "qd_0",
             "base_pose_x", "base_pose_y", "base_pose_theta", "base_pose_source",
             "base_vx", "base_vy", "base_omega", "base_vel_source",
             "human_x", "human_y", "human_vx", "human_vy"],
        ),
        (
            "a block after the human columns",
            ["t", "q_0", "qd_0", "human_x", "human_y", "human_vx", "human_vy",
             "base_vx", "base_vy", "base_omega", "base_vel_source"],
        ),
        (
            "a velocity block with its provenance column missing",
            ["t", "q_0", "qd_0", "base_vx", "base_vy", "base_omega",
             "human_x", "human_y", "human_vx", "human_vy"],
        ),
        (
            "a duplicated base column",
            ["t", "q_0", "qd_0", "base_vx", "base_vy", "base_omega", "base_vx",
             "human_x", "human_y", "human_vx", "human_vy"],
        ),
    ],
)
def test_a_header_whose_base_columns_are_not_a_block_is_refused(
    what: str, header: list[str]
) -> None:
    """**The negative the optional block buys.** A base column outside a whole
    block in the position the schema puts one is refused by name.

    Guessing is the failure mode being ruled out, and it is available in each of
    these: drop the odd column and the remainder arithmetic works out, so a
    lenient reader would hand back a schema and read every row under it. The
    refusal has to name the columns, because with the blocks out of place the
    shape of the rest of the header no longer says which robot wrote the file —
    there is nothing left to infer it from.
    """
    with pytest.raises(StreamFormatError, match="not a complete") as excinfo:
        _schema_from_header(header, "<test>")
    assert "base_" in str(excinfo.value), what


def test_the_refusal_names_the_offending_columns_not_only_that_there_are_some() -> None:
    """A header usually goes wrong by a block, and a message that says only
    *something is wrong* sends whoever is fixing it back to count columns."""
    header = ["t", "q_0", "qd_0", "base_vx", "base_vy",
              "human_x", "human_y", "human_vx", "human_vy"]
    with pytest.raises(StreamFormatError) as excinfo:
        _schema_from_header(header, "<test>")
    message = str(excinfo.value)
    for column in ("base_vx", "base_vy"):
        assert column in message


def test_a_stray_base_column_is_refused_by_the_reader_end_to_end(tmp_path) -> None:
    """Through `read_frames`, not only through the derivation — the refusal has
    to reach the caller who opened a file, and it has to happen eagerly rather
    than on the first row somebody iterates."""
    path = write_frames(frames(), tmp_path / "run.csv")
    lines = path.read_text().split(LINE_TERMINATOR)
    columns = lines[0].split(",")
    columns.insert(columns.index("human_x"), "base_vx")
    lines[0] = ",".join(columns)
    bad = tmp_path / "stray.csv"
    bad.write_text(LINE_TERMINATOR.join(lines))
    with pytest.raises(StreamFormatError, match="base_vx"):
        read_frames(bad)


# --- the mobile round trip --------------------------------------------------


def mobile_frames(
    n: int = 4, *, with_vel: bool = True, with_pose: bool = True
) -> tuple[StateFrame, ...]:
    """The same hand-authored trajectory as `frames`, with a base on it."""
    out = []
    for i, frame in enumerate(frames(n=n)):
        out.append(
            StateFrame(
                t=frame.t,
                q=frame.q,
                qd=frame.qd,
                human_pos=frame.human_pos,
                human_vel=frame.human_vel,
                base_vel=(
                    # `DERIVED` deliberately: it is the case the reader could
                    # get wrong invisibly. A codec that substituted a member
                    # for the cell it read would substitute `PROPRIOCEPTIVE` —
                    # the value every fixture in this repository would carry —
                    # so a fixture written with that value could not tell a
                    # recorded provenance from an invented one (issue #156).
                    BaseVelocity(
                        vx=0.4 - 0.05 * i,
                        vy=-0.125,
                        omega=0.2 * i,
                        source=VelocitySource.DERIVED,
                    )
                    if with_vel
                    else None
                ),
                base_pose=(
                    BasePose(
                        x=1.5 + 0.25 * i,
                        y=-0.75,
                        theta=0.125 * i,
                        source=PoseSource.DEAD_RECKONED,
                    )
                    if with_pose
                    else None
                ),
                objects=frame.objects,
            )
        )
    return tuple(out)


def test_a_mobile_stream_round_trips_to_identical_values(tmp_path) -> None:
    """**The positive this issue exists for.** A mobile scenario can be written
    to disk and read back as the run it was, values and provenance intact."""
    want = mobile_frames()
    got = list(read_frames(write_frames(want, tmp_path / "mobile.csv")))
    assert_frames_close(got, want)
    assert [f.base_pose.source for f in got] == [PoseSource.DEAD_RECKONED] * len(want)
    # Both provenances survive, and this one is the half issue #156 added: a
    # visually-estimated base velocity must not read back as an encoder-measured
    # one, which is the whole content of the column.
    assert [f.base_vel.source for f in got] == [VelocitySource.DERIVED] * len(want)


@pytest.mark.parametrize(
    ("with_vel", "with_pose"), [(True, False), (False, True), (True, True)]
)
def test_each_half_of_the_base_is_optional_on_its_own(
    tmp_path, with_vel: bool, with_pose: bool
) -> None:
    """A base with wheel encoders and no localizer is the ordinary case, so the
    two blocks are independent. Folded into one block, that robot's stream would
    have to carry a pose nobody measured and a `PoseSource` nobody stated."""
    want = mobile_frames(n=2, with_vel=with_vel, with_pose=with_pose)
    path = write_frames(want, tmp_path / "half.csv")
    got = list(read_frames(path))
    assert_frames_close(got, want)
    assert (got[0].base_vel is not None) == with_vel
    assert (got[0].base_pose is not None) == with_pose


def test_a_fixed_base_stream_still_reads_back_as_not_recorded(tmp_path) -> None:
    """The other side of the same statement, and the one issue #150 fixed: a
    stream with no base blocks says *nothing was recorded*, which must not
    resolve into a base that was measured and found still."""
    got = list(read_frames(write_frames(frames(), tmp_path / "fixed.csv")))
    assert all(f.base_vel is None and f.base_pose is None for f in got)


def test_a_mobile_stream_is_byte_identical_on_two_writes(tmp_path) -> None:
    """The base columns are floats written through the same fixed-precision path
    as every other one, so *same frames in, same bytes out* has to hold for them
    too — a compression baseline measured on a mobile fixture is not a baseline
    otherwise."""
    a = write_frames(mobile_frames(), tmp_path / "a.csv")
    b = write_frames(mobile_frames(), tmp_path / "b.csv")
    assert a.read_bytes() == b.read_bytes()


def test_an_unwritable_pose_source_is_refused_rather_than_defaulted(tmp_path) -> None:
    """**Negative test.** A `base_pose_source` cell the reader cannot resolve is
    a could-not-evaluate, and it must not resolve to a member.

    `BasePose.source` is required with no default precisely so that a pose whose
    provenance nobody stated cannot be told apart from one somebody did. Picking
    a member here — or reading the pose and leaving the provenance out — would
    reintroduce that one layer down, in the file rather than in the type.
    """
    path = write_frames(mobile_frames(n=2), tmp_path / "mobile.csv")
    lines = path.read_text().rstrip(LINE_TERMINATOR).split(LINE_TERMINATOR)
    at = lines[0].split(",").index("base_pose_source")
    cells = lines[1].split(",")
    cells[at] = "gps"
    lines[1] = ",".join(cells)
    bad = tmp_path / "bad-source.csv"
    bad.write_text(LINE_TERMINATOR.join(lines) + LINE_TERMINATOR)
    with pytest.raises(StreamFormatError, match="not a PoseSource"):
        list(read_frames(bad))


def test_an_unwritable_velocity_source_is_refused_rather_than_defaulted(
    tmp_path,
) -> None:
    """**Negative test, the Layer A half (issue #156).**

    The pose case above is the same shape, and this one is worse, which is why
    it is asserted separately rather than parametrized alongside it. A
    `base_pose_source` nobody can resolve at least belongs to a value already
    tagged Layer B. `base_vel_source` decides whether the three Layer A-shaped
    rates beside it came off wheel encoders or out of visual odometry, and the
    substitution a lenient reader would make — `proprioceptive`, the value every
    fixture here carries — is precisely the mislabelling the field exists to
    stop. So an unreadable cell is a could-not-evaluate and the frame is not
    read.
    """
    path = write_frames(mobile_frames(n=2), tmp_path / "mobile.csv")
    lines = path.read_text().rstrip(LINE_TERMINATOR).split(LINE_TERMINATOR)
    at = lines[0].split(",").index("base_vel_source")
    cells = lines[1].split(",")
    cells[at] = "visual_odometry"
    lines[1] = ",".join(cells)
    bad = tmp_path / "bad-vel-source.csv"
    bad.write_text(LINE_TERMINATOR.join(lines) + LINE_TERMINATOR)
    with pytest.raises(StreamFormatError, match="not a VelocitySource"):
        list(read_frames(bad))

    # And an empty cell is not "unspecified" either — the reader has to refuse
    # it for the same reason, rather than treating a blank as an absent block.
    cells[at] = ""
    lines[1] = ",".join(cells)
    blank = tmp_path / "blank-vel-source.csv"
    blank.write_text(LINE_TERMINATOR.join(lines) + LINE_TERMINATOR)
    with pytest.raises(StreamFormatError, match="not a VelocitySource"):
        list(read_frames(blank))


def test_a_non_numeric_base_cell_is_refused(tmp_path) -> None:
    """The base columns go through the same `_number` gate as every other float:
    a NaN read back as a base velocity propagates into the outer envelope, which
    is the only bound a mobile robot's VETO rests on (docs/mobile-base.md §1)."""
    path = write_frames(mobile_frames(n=2), tmp_path / "mobile.csv")
    lines = path.read_text().rstrip(LINE_TERMINATOR).split(LINE_TERMINATOR)
    at = lines[0].split(",").index("base_omega")
    cells = lines[1].split(",")
    cells[at] = "nan"
    lines[1] = ",".join(cells)
    bad = tmp_path / "nan.csv"
    bad.write_text(LINE_TERMINATOR.join(lines) + LINE_TERMINATOR)
    with pytest.raises(StreamFormatError, match="not finite"):
        list(read_frames(bad))
