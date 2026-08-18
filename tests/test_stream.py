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
    read_frames,
    write_frames,
)
from reg.types import Obstacle, StateFrame

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
            t=f.t, q=f.q, qd=f.qd, human_pos=f.human_pos, human_vel=f.human_vel
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
        objects=f.objects,
    )
    with pytest.raises(StreamFormatError, match="finite"):
        write_frames([wrong], tmp_path / "run.csv")
