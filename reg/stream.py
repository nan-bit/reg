"""The raw state stream — CSV in, CSV out.

WHY THIS FILE MATTERS MORE THAN A SERIALIZER USUALLY DOES
---------------------------------------------------------
This is the *baseline Claim 1 is measured against*. The compression number the
whole commercial argument rests on is `graph bytes / this file's bytes`, so the
format is part of the argument rather than an implementation detail:

* **CSV, not parquet.** docs/plan.md chose it deliberately — a more legible
  baseline, and it drops `pyarrow`. Do not "improve" this to a binary format.
* **Obstacles are written every frame** even though they are static. That
  inflates the raw stream, which is the honest direction: pre-compressing the
  thing we intend to beat would make the ratio a statement about our encoder
  rather than about the evidence graph.
* **Fixed decimal precision** (`FLOAT_PRECISION`). `repr(float)` is
  shortest-round-trip, so it varies in width with the value and the same
  trajectory recorded twice can differ in bytes. A benchmark measured against a
  file whose size depends on which digits happened to come out is not a
  benchmark. Same frames in, byte-identical file out.

LAYER
-----
The stream is mixed-layer by construction (see `reg.types.StateFrame`): it holds
the human and the obstacles, which are Layer B. Nothing in Layer A reads it —
the envelope takes `StateFrame.proprio()`. This module is a codec and makes no
claim of its own.

FAILURE POSTURE
---------------
Every deviation from the schema raises `StreamFormatError`. A mis-parsed column
would not surface as a crash, it would surface as a compression ratio and an
audit answer computed from the wrong numbers, so there is no lenient path here:
no coercion, no skipped rows, no filled-in blanks.
"""

from __future__ import annotations

import csv
import math
import os
from collections.abc import Iterable, Iterator
from pathlib import Path

import numpy as np

from reg.types import Obstacle, StateFrame

# Decimal places every float in the stream is written with. Chosen, not
# defaulted: the raw stream is the fine-grained end of the pipeline (the graph
# quantizes hard, to cm and 2 sig figs — docs/plan.md Phase 5), so this only has
# to be finer than anything downstream cares about. Six places is micrometres
# and microseconds in the units this sim uses. Changing it changes the size of
# the file every compression ratio is divided by, so it is a versioned property
# of the artifact, not a knob.
FLOAT_PRECISION = 6

# Byte-identity also depends on these two. csv defaults to CRLF; pinning the
# terminator and the encoding is what makes "same seed, same bytes" hold across
# the machine that produced a run and the machine auditing it.
LINE_TERMINATOR = "\n"
ENCODING = "utf-8"

_HUMAN_COLUMNS = ("human_x", "human_y", "human_vx", "human_vy")

# Per-obstacle block. `x`, `y`, `r` are the three the schema is specified around;
# `id` and `kind` are carried because `Obstacle` has them and a round trip that
# silently drops them is not a round trip — reconstructing a `kind` on read would
# mean inventing a value indistinguishable downstream from a recorded one.
_OBSTACLE_COLUMNS = ("id", "kind", "x", "y", "r")


class StreamFormatError(ValueError):
    """A stream could not be written or read as the schema says it should be.

    Deliberately not a warning and never a silent fallback: the third outcome of
    a check is *could-not-evaluate*, and could-not-evaluate must not resolve to
    a parsed frame.
    """


def expected_header(n_joints: int, n_obstacles: int) -> list[str]:
    """The one definition of the column layout. Writer and reader both use it."""
    if n_joints < 0 or n_obstacles < 0:
        raise ValueError(
            f"n_joints={n_joints}, n_obstacles={n_obstacles}: both must be >= 0"
        )
    columns = ["t"]
    columns += [f"q_{i}" for i in range(n_joints)]
    columns += [f"qd_{i}" for i in range(n_joints)]
    columns += list(_HUMAN_COLUMNS)
    for j in range(n_obstacles):
        columns += [f"obs_{j}_{name}" for name in _OBSTACLE_COLUMNS]
    return columns


def write_frames(frames: Iterable[StateFrame], path: str | os.PathLike[str]) -> Path:
    """Write a state stream to CSV. Returns the path, for `read_frames(write_frames(x))`.

    The schema comes from the frames: joint count and obstacle count are read off
    the first frame and every later frame must agree. A stream whose shape changes
    mid-run cannot be described by one header, and quietly padding it would put
    numbers under column names they do not belong to.
    """
    frames = tuple(frames)
    if not frames:
        raise StreamFormatError(
            "no frames to write: the header (joint count, obstacle count) is "
            "derived from the frames, so an empty stream has no schema. Nothing "
            "was written — pass at least one StateFrame."
        )

    n_joints = len(frames[0].q)
    n_obstacles = len(frames[0].objects)
    header = expected_header(n_joints, n_obstacles)

    rows = [_row(frame, index, n_joints, n_obstacles) for index, frame in enumerate(frames)]

    path = Path(path)
    with path.open("w", newline="", encoding=ENCODING) as handle:
        writer = csv.writer(handle, lineterminator=LINE_TERMINATOR)
        writer.writerow(header)
        writer.writerows(rows)
    return path


def read_frames(path: str | os.PathLike[str]) -> Iterator[StateFrame]:
    """Read a state stream back. Header is validated eagerly, rows lazily.

    Eagerly on purpose: a generator that only rejects a bad header once someone
    iterates it hands the caller a wrong answer at a distance from the cause.
    """
    handle = Path(path).open("r", newline="", encoding=ENCODING)
    try:
        reader = csv.reader(handle)
        header = next(reader, None)
        if header is None:
            raise StreamFormatError(
                f"{path}: file is empty. An empty file is a stream that could "
                "not be read, not a stream of zero frames."
            )
        n_joints, n_obstacles = _schema_from_header(header, path)
    except BaseException:
        handle.close()
        raise
    return _iter_frames(handle, reader, n_joints, n_obstacles, path)


def _schema_from_header(
    header: list[str], path: str | os.PathLike[str]
) -> tuple[int, int]:
    """Derive (n_joints, n_obstacles) from a header, or refuse it.

    Derivation is only a guess at the shape; the check is the exact comparison
    against `expected_header`, which is what catches a renamed, reordered, or
    dropped column instead of reading the next column's numbers into it.
    """
    n_joints = 0
    while 1 + n_joints < len(header) and header[1 + n_joints] == f"q_{n_joints}":
        n_joints += 1

    fixed = 1 + 2 * n_joints + len(_HUMAN_COLUMNS)
    remaining = len(header) - fixed
    if remaining < 0 or remaining % len(_OBSTACLE_COLUMNS) != 0:
        raise StreamFormatError(
            f"{path}: header has {len(header)} columns, which is not a valid "
            f"stream schema. With {n_joints} joint column(s) the layout needs "
            f"{fixed} columns plus a multiple of {len(_OBSTACLE_COLUMNS)} for "
            f"the obstacle blocks; got {remaining} left over. Header: {header}"
        )
    n_obstacles = remaining // len(_OBSTACLE_COLUMNS)

    expected = expected_header(n_joints, n_obstacles)
    if header != expected:
        raise StreamFormatError(
            f"{path}: header does not match the stream schema.\n"
            f"  {_first_difference(expected, header)}\n"
            f"  expected: {expected}\n"
            f"  got:      {header}\n"
            "Refusing to read: the columns are positional, so parsing a header "
            "that names them differently would put values in the wrong fields "
            "without erroring anywhere downstream."
        )
    return n_joints, n_obstacles


def _first_difference(expected: list[str], got: list[str]) -> str:
    for i, (e, g) in enumerate(zip(expected, got)):
        if e != g:
            return f"column {i}: expected {e!r}, got {g!r}"
    return f"column count: expected {len(expected)}, got {len(got)}"


def _iter_frames(
    handle,
    reader,
    n_joints: int,
    n_obstacles: int,
    path: str | os.PathLike[str],
) -> Iterator[StateFrame]:
    width = 1 + 2 * n_joints + len(_HUMAN_COLUMNS) + n_obstacles * len(_OBSTACLE_COLUMNS)
    try:
        for row in reader:
            line = reader.line_num
            if len(row) != width:
                raise StreamFormatError(
                    f"{path} line {line}: {len(row)} field(s), header declares "
                    f"{width}. A short or long row cannot be aligned to the "
                    "columns; it is not read."
                )
            # Offsets rather than a cursor: the column layout is positional, so
            # reading it positionally keeps reader and `expected_header` in step.
            q_at = 1
            qd_at = q_at + n_joints
            human_at = qd_at + n_joints
            obs_at = human_at + len(_HUMAN_COLUMNS)

            t = _number(row[0], "t", line, path)
            q = np.array(
                [
                    _number(row[q_at + i], f"q_{i}", line, path)
                    for i in range(n_joints)
                ],
                dtype=float,
            )
            qd = np.array(
                [
                    _number(row[qd_at + i], f"qd_{i}", line, path)
                    for i in range(n_joints)
                ],
                dtype=float,
            )
            human_pos = np.array(
                [
                    _number(row[human_at + 0], "human_x", line, path),
                    _number(row[human_at + 1], "human_y", line, path),
                ],
                dtype=float,
            )
            human_vel = np.array(
                [
                    _number(row[human_at + 2], "human_vx", line, path),
                    _number(row[human_at + 3], "human_vy", line, path),
                ],
                dtype=float,
            )
            objects = []
            for j in range(n_obstacles):
                block = obs_at + j * len(_OBSTACLE_COLUMNS)
                entity_id, kind, cx, cy, radius = row[
                    block : block + len(_OBSTACLE_COLUMNS)
                ]
                objects.append(
                    Obstacle(
                        entity_id=entity_id,
                        kind=kind,
                        cx=_number(cx, f"obs_{j}_x", line, path),
                        cy=_number(cy, f"obs_{j}_y", line, path),
                        radius=_number(radius, f"obs_{j}_r", line, path),
                    )
                )
            yield StateFrame(
                t=t,
                q=q,
                qd=qd,
                human_pos=human_pos,
                human_vel=human_vel,
                objects=tuple(objects),
            )
    finally:
        handle.close()


def _number(raw: str, column: str, line: int, path: str | os.PathLike[str]) -> float:
    try:
        value = float(raw)
    except ValueError:
        raise StreamFormatError(
            f"{path} line {line}, column {column}: {raw!r} is not a number."
        ) from None
    if not math.isfinite(value):
        # float() happily accepts 'nan' and 'inf'. A NaN read back as a position
        # propagates into every geometric result as a silently empty polygon.
        raise StreamFormatError(
            f"{path} line {line}, column {column}: {raw!r} is not finite. The "
            "raw stream is ground truth; a non-finite value in it is a fault "
            "upstream, not a value to carry forward."
        )
    return value


def _row(frame: StateFrame, index: int, n_joints: int, n_obstacles: int) -> list[str]:
    where = f"frame {index} (t={frame.t})"
    if len(frame.q) != n_joints or len(frame.qd) != n_joints:
        raise StreamFormatError(
            f"{where}: q has {len(frame.q)} and qd has {len(frame.qd)} entries, "
            f"but the stream header declares {n_joints} joint(s) from frame 0. "
            "One header cannot describe a stream whose shape changes."
        )
    if len(frame.human_pos) != 2 or len(frame.human_vel) != 2:
        raise StreamFormatError(
            f"{where}: human_pos has {len(frame.human_pos)} and human_vel has "
            f"{len(frame.human_vel)} entries; this is a 2D world and both must "
            "have exactly 2."
        )
    if len(frame.objects) != n_obstacles:
        raise StreamFormatError(
            f"{where}: {len(frame.objects)} obstacle(s), but the stream header "
            f"declares {n_obstacles} from frame 0. Obstacles are static and are "
            "written every frame; a changing count means the header is a lie."
        )

    cells = [_fixed(frame.t, "t", where)]
    cells += [_fixed(v, f"q_{i}", where) for i, v in enumerate(frame.q)]
    cells += [_fixed(v, f"qd_{i}", where) for i, v in enumerate(frame.qd)]
    cells += [
        _fixed(frame.human_pos[0], "human_x", where),
        _fixed(frame.human_pos[1], "human_y", where),
        _fixed(frame.human_vel[0], "human_vx", where),
        _fixed(frame.human_vel[1], "human_vy", where),
    ]
    for j, obstacle in enumerate(frame.objects):
        cells += [
            obstacle.entity_id,
            obstacle.kind,
            _fixed(obstacle.cx, f"obs_{j}_x", where),
            _fixed(obstacle.cy, f"obs_{j}_y", where),
            _fixed(obstacle.radius, f"obs_{j}_r", where),
        ]
    return cells


def _fixed(value: float, column: str, where: str) -> str:
    value = float(value)
    if not math.isfinite(value):
        raise StreamFormatError(
            f"{where}, column {column}: value is {value!r}. A non-finite number "
            "would be written as 'nan'/'inf' and read back as a value no "
            "comparison downstream can reject; refusing to record it."
        )
    # `+ 0.0` normalises -0.0, which formats as '-0.000000' and would otherwise
    # make two runs that agree numerically differ in bytes.
    return f"{value + 0.0:.{FLOAT_PRECISION}f}"
