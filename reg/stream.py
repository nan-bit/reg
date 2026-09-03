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
* **An optional `#` provenance block above the header**, written by the producer
  and skipped by the reader (`COMMENT_PREFIX`, `read_comments`). docs/lossiness.md
  retains the run's provenance once per artifact, and a sidecar file is
  provenance that can be separated from the artifact it describes.

LAYER
-----
The stream is mixed-layer by construction (see `reg.types.StateFrame`): it holds
the human and the obstacles, which are Layer B. Nothing in Layer A reads it —
the envelope takes `StateFrame.proprio()`. This module is a codec and makes no
claim of its own.

THE BASE, AND WHY IT IS TWO OPTIONAL BLOCKS RATHER THAN EIGHT COLUMNS (#176)
----------------------------------------------------------------------------
`StateFrame` gained `base_vel` and `base_pose` in issue #150 and this format had
columns for neither, so it refused to write a frame carrying either — reading
absence as *not recorded* rather than writing a mobile run out as a fixed-base
one. It can now carry both, and the shape of that addition is set by one
constraint: **Claim 1 stays a fixed-arm claim** (#140). `expected_header(2, 3)`
is the 24 columns the priced fixture is measured on, and adding base columns
unconditionally would grow every fixture's header, move the gzipped baseline,
and move `265 GB`, `~40x` and every other figure `docs/retention.md` publishes —
for eleven robots that are bolted to the origin. So the base is **two optional
blocks**, present only in a stream whose frames carry them, and a header with
neither is exactly the header it has always been.

**They are two blocks and not one because the Layer A / Layer B line runs
between them** (issue #150, docs/sufficiency.md §5.6):

* `base_vx`, `base_vy`, `base_omega`, `base_vel_source` are body-frame rates and
  the provenance of those rates — a statement about the machine, **Layer A** on
  the terms `qd` is. The provenance column is not decoration: a rate estimated by
  visual odometry came from a perceiver, and since issue #156 the artifact says
  which case it is in rather than leaving it to be assumed.
* `base_pose_x`, `base_pose_y`, `base_pose_theta`, `base_pose_source` are a
  room-frame pose — a statement about the robot's relationship to a map or a
  frame somebody defined, **Layer B**, structurally and not for want of a better
  estimator.

A robot can have one without the other (a base with encoders and no localizer is
the ordinary case), and folding them into one block would mean writing the half
nobody recorded — zeros for a pose nobody measured, or a `PoseSource` nobody
stated. Each block carries its own provenance column for the same reason
(`base_vel_source`, `base_pose_source`): the two are separate claims about the
run, and neither can be inferred from the other. Each block is present or absent on its own for that reason.
`reg.bench.COLUMN_RULES` carries one rule per block, on opposite sides of the
boundary, or the Layer A / Layer B column split Claim 1's like-for-like
comparison is computed over would move with nothing going red
(docs/mobile-base.md §5).

**WHY AN OPTIONAL BLOCK DOES NOT MAKE A HEADER AMBIGUOUS.** Two robots that
differ must not produce the same header, or the stream is one nobody can read
back. Block presence is decided by **comparing names at a fixed offset**, never
by arithmetic over the column count, so `(n_joints, base_vel, base_pose,
n_obstacles)` is recovered exactly and the map from it to a header is injective.
The arithmetic is a backstop rather than the mechanism: no subset of the optional
blocks — 4, 4 or 8 columns — is a multiple of the 5-column obstacle block, so
even a reader that lost the name comparison could not read a base block as an
extra obstacle. Anything else carrying base column *names* — a truncated block, a
block after the human columns, a duplicated one — is refused by name rather than
guessed at, because with the blocks out of place the rest of the header no longer
identifies the robot that wrote it. `tests/test_stream.py` asserts all three.

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
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from itertools import chain
from pathlib import Path

import numpy as np

from reg.types import (
    BasePose,
    BaseVelocity,
    Obstacle,
    PoseSource,
    StateFrame,
    VelocitySource,
)

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

# A stream may carry a block of provenance lines above the header, each marked
# with this prefix. docs/lossiness.md retains "the run's provenance — scenario
# name, seed, ... once per artifact. Determinism is only checkable if the
# artifact says what produced it", and a sidecar file is provenance that can be
# separated from the thing it describes. CSV has no comment convention, so this
# is one, and it lives here rather than in the producer because the reader has
# to agree with the writer about it or the artifact stops being readable by the
# codec that wrote it. Only the leading block is treated as comments; after the
# header every line is a row.
COMMENT_PREFIX = "#"

_HUMAN_COLUMNS = ("human_x", "human_y", "human_vx", "human_vy")

# The base's body-frame velocity — **Layer A**, the same terms `qd` is admitted
# on (`reg.types.BaseVelocity`). Optional: present only in a stream whose frames
# carry one.
#
# `base_vel_source` is carried for the reason `base_pose_source` below is:
# `BaseVelocity.source` is required with no default since issue #156, so
# reconstructing one on read would mean inventing a provenance indistinguishable
# downstream from a recorded one. It is the column that says whether these three
# rates came off wheel encoders or out of visual odometry, and a stream that
# carries the rates without it is refused rather than read as the encoder case.
_BASE_VEL_COLUMNS = ("base_vx", "base_vy", "base_omega", "base_vel_source")

# The base's room-frame pose — **Layer B**, structurally (`reg.types.BasePose`,
# docs/sufficiency.md §5.6). `source` is carried for the reason an obstacle's
# `kind` is: `BasePose.source` is required and has no default, so reconstructing
# one on read would mean inventing a provenance indistinguishable downstream from
# a recorded one. Deliberately **not** named `base_x`/`base_y`/`base_theta`: those
# three are the columns `reg.bench.COLUMN_RULES` has no rule for, and
# `tests/test_bench.py` requires them to stay unclassifiable, because a column
# nobody has thought about must not be absorbed by a rule written for a different
# one.
_BASE_POSE_COLUMNS = (
    "base_pose_x",
    "base_pose_y",
    "base_pose_theta",
    "base_pose_source",
)

# Per-obstacle block. `x`, `y`, `r` are the three the schema is specified around;
# `id` and `kind` are carried because `Obstacle` has them and a round trip that
# silently drops them is not a round trip — reconstructing a `kind` on read would
# mean inventing a value indistinguishable downstream from a recorded one.
_OBSTACLE_COLUMNS = ("id", "kind", "x", "y", "r")

#: Every column name that belongs to one of the two base blocks. Used to catch a
#: base column sitting somewhere no block could have put it; see
#: `_stray_base_columns`.
_BASE_COLUMN_NAMES = frozenset(_BASE_VEL_COLUMNS) | frozenset(_BASE_POSE_COLUMNS)


class StreamFormatError(ValueError):
    """A stream could not be written or read as the schema says it should be.

    Deliberately not a warning and never a silent fallback: the third outcome of
    a check is *could-not-evaluate*, and could-not-evaluate must not resolve to
    a parsed frame.
    """


@dataclass(frozen=True)
class StreamSchema:
    """What one header says the stream holds. The writer derives it from the
    frames; the reader recovers it from the header; they must be the same thing.

    Four fields and no more, and that is the readability property: a header is a
    function of exactly these, and this is recoverable from exactly that header
    (`_schema_from_header`). Two robots that differ in any one of them produce
    different headers — the module docstring says why that is a property of the
    layout rather than a hope.

    `base_vel` and `base_pose` are *whether the stream records them*, which is
    not the same statement as *whether the base moved*. False means the file says
    nothing about that half of the base, and `read_frames` renders it as `None`.
    """

    n_joints: int
    n_obstacles: int
    #: True if the stream carries the Layer A body-frame velocity block.
    base_vel: bool
    #: True if the stream carries the Layer B room-frame pose block.
    base_pose: bool

    def header(self) -> list[str]:
        """The columns this schema writes, in order."""
        return expected_header(
            self.n_joints,
            self.n_obstacles,
            base_vel=self.base_vel,
            base_pose=self.base_pose,
        )

    def width(self) -> int:
        """How many fields a data row has under this schema."""
        return (
            1
            + 2 * self.n_joints
            + (len(_BASE_VEL_COLUMNS) if self.base_vel else 0)
            + (len(_BASE_POSE_COLUMNS) if self.base_pose else 0)
            + len(_HUMAN_COLUMNS)
            + self.n_obstacles * len(_OBSTACLE_COLUMNS)
        )


def expected_header(
    n_joints: int,
    n_obstacles: int,
    *,
    base_vel: bool = False,
    base_pose: bool = False,
) -> list[str]:
    """The one definition of the column layout. Writer and reader both use it.

    `base_vel` and `base_pose` say whether the stream **records** each half of
    the base. They are the one pair of arguments here with a default, and the
    default is not an invented value: `False` is the statement a header with no
    base columns already makes — *this file records no base* — which is what
    `read_frames` renders as `None` and has meant since issue #150. Nothing in
    the writer takes the default, either: `write_frames` derives both from the
    frames it was handed, so a mobile run cannot become a fixed-base file by
    omission. What the default buys is that `expected_header(2, 3)` is still the
    24 columns Claim 1's published figures are measured on, byte for byte.
    """
    if n_joints < 0 or n_obstacles < 0:
        raise ValueError(
            f"n_joints={n_joints}, n_obstacles={n_obstacles}: both must be >= 0"
        )
    columns = ["t"]
    columns += [f"q_{i}" for i in range(n_joints)]
    columns += [f"qd_{i}" for i in range(n_joints)]
    if base_vel:
        columns += list(_BASE_VEL_COLUMNS)
    if base_pose:
        columns += list(_BASE_POSE_COLUMNS)
    columns += list(_HUMAN_COLUMNS)
    for j in range(n_obstacles):
        columns += [f"obs_{j}_{name}" for name in _OBSTACLE_COLUMNS]
    return columns


def write_frames(
    frames: Iterable[StateFrame],
    path: str | os.PathLike[str],
    *,
    comments: Sequence[str] = (),
) -> Path:
    """Write a state stream to CSV. Returns the path, for `read_frames(write_frames(x))`.

    The schema comes from the frames: joint count, obstacle count and whether
    each half of the base is recorded are read off the first frame, and every
    later frame must agree. A stream whose shape changes mid-run cannot be
    described by one header, and quietly padding it would put numbers under
    column names they do not belong to.

    `comments` is written above the header as a `#`-prefixed block — the run's
    provenance, and nothing that varies between two runs of the same command. A
    wall-clock time or an output path in here would make "same seed, same bytes"
    a statement about the clock instead of about the simulator.
    """
    frames = tuple(frames)
    if not frames:
        raise StreamFormatError(
            "no frames to write: the header (joint count, obstacle count, "
            "whether the base is recorded) is derived from the frames, so an "
            "empty stream has no schema. Nothing was written — pass at least "
            "one StateFrame."
        )

    schema = StreamSchema(
        n_joints=len(frames[0].q),
        n_obstacles=len(frames[0].objects),
        base_vel=frames[0].base_vel is not None,
        base_pose=frames[0].base_pose is not None,
    )
    header = schema.header()

    rows = [_row(frame, index, schema) for index, frame in enumerate(frames)]
    # Built before the file is opened, so a rejected comment leaves no partial
    # artifact behind — same posture as the row checks above.
    banner = [_comment(text, index) for index, text in enumerate(comments)]

    path = Path(path)
    with path.open("w", newline="", encoding=ENCODING) as handle:
        handle.writelines(banner)
        writer = csv.writer(handle, lineterminator=LINE_TERMINATOR)
        writer.writerow(header)
        writer.writerows(rows)
    return path


def read_frames(path: str | os.PathLike[str]) -> Iterator[StateFrame]:
    """Read a state stream back. Header is validated eagerly, rows lazily.

    Eagerly on purpose: a generator that only rejects a bad header once someone
    iterates it hands the caller a wrong answer at a distance from the cause.

    A leading `#` block is provenance and is skipped; `read_comments` is how you
    get at it. Skipping it here is not leniency — the block is part of the format
    (see `COMMENT_PREFIX`), and line numbers in errors below still refer to lines
    in the file, not to lines after the block.
    """
    handle = Path(path).open("r", newline="", encoding=ENCODING)
    try:
        n_comments, first = _skip_comments(handle)
        if first is None:
            raise StreamFormatError(
                f"{path}: file is empty. An empty file is a stream that could "
                "not be read, not a stream of zero frames."
                if n_comments == 0
                else f"{path}: {n_comments} provenance line(s) and no header row. "
                "A file that says what produced it but carries no stream is a "
                "stream that could not be read, not a stream of zero frames."
            )
        reader = csv.reader(chain([first], handle))
        header = next(reader, None)
        if header is None:  # pragma: no cover - `first` is a line, so there is one
            raise StreamFormatError(f"{path}: file is empty.")
        schema = _schema_from_header(header, path)
    except BaseException:
        handle.close()
        raise
    return _iter_frames(handle, reader, schema, path, n_comments)


def read_comments(path: str | os.PathLike[str]) -> list[str]:
    """The provenance block above the header, prefixes stripped. Order preserved.

    An empty list means the file states nothing about what produced it. That is a
    could-not-evaluate for every question about provenance — in particular it does
    not mean the run used whatever seed the caller would have used.
    """
    out: list[str] = []
    with Path(path).open("r", newline="", encoding=ENCODING) as handle:
        for line in handle:
            if not line.startswith(COMMENT_PREFIX):
                break
            out.append(_uncomment(line))
    return out


def _skip_comments(handle) -> tuple[int, str | None]:
    """Consume the leading comment block. Returns (how many, first line after)."""
    n_comments = 0
    for line in handle:
        if line.startswith(COMMENT_PREFIX):
            n_comments += 1
            continue
        return n_comments, line
    return n_comments, None


def _comment(text: str, index: int) -> str:
    if not isinstance(text, str):
        raise StreamFormatError(
            f"comment {index} is a {type(text).__name__}, not a str: {text!r}"
        )
    if "\n" in text or "\r" in text:
        raise StreamFormatError(
            f"comment {index} contains a line break: {text!r}. It would be written "
            "as two lines, the second of which is neither a comment nor a valid "
            "row — a file that no longer parses as the stream it claims to be."
        )
    return f"{COMMENT_PREFIX} {text}{LINE_TERMINATOR}"


def _uncomment(line: str) -> str:
    """Exact inverse of `_comment`: drop the prefix, one space, and the newline."""
    text = line[len(COMMENT_PREFIX) :].rstrip("\r\n")
    return text[1:] if text.startswith(" ") else text


def _stray_base_columns(
    header: Sequence[str], block_start: int, block_end: int
) -> list[str]:
    """Base column names sitting outside the blocks that were recognised.

    A block is recognised by an exact name match at the offset the layout puts it
    at, so anything left over is a base column in a position no writer of this
    schema could have produced: a truncated block, a misordered one, a block after
    the human columns, a duplicate. Returned as `index: name` rather than counted,
    because the remedy is to look at that column.
    """
    return [
        f"column {i}: {name!r}"
        for i, name in enumerate(header)
        if name in _BASE_COLUMN_NAMES and not (block_start <= i < block_end)
    ]


def _schema_from_header(
    header: list[str], path: str | os.PathLike[str]
) -> StreamSchema:
    """Derive the schema from a header, or refuse it.

    Derivation is only a guess at the shape; the check is the exact comparison
    against `expected_header`, which is what catches a renamed, reordered, or
    dropped column instead of reading the next column's numbers into it.

    The two base blocks are detected by **name at a fixed offset** and never by
    arithmetic over the column count — see the module docstring. A base column
    that no block accounts for is refused before the arithmetic runs, so the
    reader says *these base columns are not where a base block goes* rather than
    the obstacle-block remainder message, which describes the symptom and not the
    cause.
    """
    n_joints = 0
    while 1 + n_joints < len(header) and header[1 + n_joints] == f"q_{n_joints}":
        n_joints += 1

    base_at = 1 + 2 * n_joints
    at = base_at
    base_vel = list(header[at : at + len(_BASE_VEL_COLUMNS)]) == list(
        _BASE_VEL_COLUMNS
    )
    if base_vel:
        at += len(_BASE_VEL_COLUMNS)
    base_pose = list(header[at : at + len(_BASE_POSE_COLUMNS)]) == list(
        _BASE_POSE_COLUMNS
    )
    if base_pose:
        at += len(_BASE_POSE_COLUMNS)

    stray = _stray_base_columns(header, base_at, at)
    if stray:
        raise StreamFormatError(
            f"{path}: header carries base column(s) that are not a complete "
            f"base block in the position the schema puts one: {stray}. The base "
            f"is two whole blocks — {list(_BASE_VEL_COLUMNS)} (Layer A) and "
            f"{list(_BASE_POSE_COLUMNS)} (Layer B) — immediately after the joint "
            "columns, each present or absent as a unit. Refusing rather than "
            "guessing which of them was meant: with the blocks out of place the "
            "shape of the rest of the header no longer says which robot wrote "
            f"it. Header: {header}"
        )

    fixed = at + len(_HUMAN_COLUMNS)
    remaining = len(header) - fixed
    if remaining < 0 or remaining % len(_OBSTACLE_COLUMNS) != 0:
        raise StreamFormatError(
            f"{path}: header has {len(header)} columns, which is not a valid "
            f"stream schema. With {n_joints} joint column(s), "
            f"{'a' if base_vel else 'no'} base-velocity block and "
            f"{'a' if base_pose else 'no'} base-pose block the layout needs "
            f"{fixed} columns plus a multiple of {len(_OBSTACLE_COLUMNS)} for "
            f"the obstacle blocks; got {remaining} left over. Header: {header}"
        )
    schema = StreamSchema(
        n_joints=n_joints,
        n_obstacles=remaining // len(_OBSTACLE_COLUMNS),
        base_vel=base_vel,
        base_pose=base_pose,
    )

    expected = schema.header()
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
    return schema


def _first_difference(expected: list[str], got: list[str]) -> str:
    for i, (e, g) in enumerate(zip(expected, got)):
        if e != g:
            return f"column {i}: expected {e!r}, got {g!r}"
    return f"column count: expected {len(expected)}, got {len(got)}"


def _iter_frames(
    handle,
    reader,
    schema: StreamSchema,
    path: str | os.PathLike[str],
    line_offset: int = 0,
) -> Iterator[StateFrame]:
    n_joints = schema.n_joints
    n_obstacles = schema.n_obstacles
    width = schema.width()
    try:
        for row in reader:
            # The reader never saw the provenance block, so its line numbers are
            # short by exactly that many. An error that names a line the reader
            # counted rather than a line of the file sends someone to the wrong
            # row of a 300-row artifact.
            line = reader.line_num + line_offset
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
            base_vel_at = qd_at + n_joints
            base_pose_at = base_vel_at + (
                len(_BASE_VEL_COLUMNS) if schema.base_vel else 0
            )
            human_at = base_pose_at + (
                len(_BASE_POSE_COLUMNS) if schema.base_pose else 0
            )
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
            # No block means the file records nothing about that half of the
            # base, and `None` is that statement. Zeros would be an invented
            # reading: they say the base was measured and found still, which is
            # what a mobile stream earns a column to claim (#150, #176).
            base_vel = (
                BaseVelocity(
                    vx=_number(row[base_vel_at + 0], "base_vx", line, path),
                    vy=_number(row[base_vel_at + 1], "base_vy", line, path),
                    omega=_number(row[base_vel_at + 2], "base_omega", line, path),
                    source=_velocity_source(row[base_vel_at + 3], line, path),
                )
                if schema.base_vel
                else None
            )
            base_pose = (
                BasePose(
                    x=_number(row[base_pose_at + 0], "base_pose_x", line, path),
                    y=_number(row[base_pose_at + 1], "base_pose_y", line, path),
                    theta=_number(
                        row[base_pose_at + 2], "base_pose_theta", line, path
                    ),
                    source=_pose_source(row[base_pose_at + 3], line, path),
                )
                if schema.base_pose
                else None
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
                base_vel=base_vel,
                base_pose=base_pose,
                objects=tuple(objects),
            )
    finally:
        handle.close()


def _velocity_source(
    raw: str, line: int, path: str | os.PathLike[str]
) -> VelocitySource:
    """`VelocitySource` for a written provenance string, or a refusal.

    Not defaulted and not coerced, and the temptation here is stronger than it
    is for a pose: `PROPRIOCEPTIVE` is what a bolted base's stream would say and
    substituting it for an unreadable cell would look harmless in every fixture
    in this repository. It is not harmless — this is the one column saying
    whether the rates beside it came from a perceiver, and a substituted value
    is exactly the mislabelling `reg.types.VelocitySource` exists to stop
    (issue #156, issue #84).
    """
    try:
        return VelocitySource(raw)
    except ValueError:
        raise StreamFormatError(
            f"{path} line {line}, column base_vel_source: {raw!r} is not a "
            f"VelocitySource. Valid values: {[m.value for m in VelocitySource]}. "
            "The velocity is not read with a substituted provenance — whether "
            "these rates were measured on the robot or estimated from something "
            "perceived is the whole content of this field."
        ) from None


def _pose_source(
    raw: str, line: int, path: str | os.PathLike[str]
) -> PoseSource:
    """`PoseSource` for a written provenance string, or a refusal.

    Not defaulted and not coerced. `BasePose.source` is required with no default
    because a pose whose provenance nobody stated must not be indistinguishable
    from one somebody did (`reg.types.PoseSource`); picking a member here for an
    unreadable cell would reintroduce exactly that, one layer down.
    """
    try:
        return PoseSource(raw)
    except ValueError:
        raise StreamFormatError(
            f"{path} line {line}, column base_pose_source: {raw!r} is not a "
            f"PoseSource. Valid values: {[m.value for m in PoseSource]}. The "
            "pose is not read with a substituted provenance — what the pose "
            "inherits and over what horizon is the whole content of this field."
        ) from None


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


def _row(frame: StateFrame, index: int, schema: StreamSchema) -> list[str]:
    where = f"frame {index} (t={frame.t})"
    n_joints = schema.n_joints
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
    _check_base_agrees(frame.base_vel, schema.base_vel, "base velocity", where)
    _check_base_agrees(frame.base_pose, schema.base_pose, "base pose", where)
    if len(frame.objects) != schema.n_obstacles:
        raise StreamFormatError(
            f"{where}: {len(frame.objects)} obstacle(s), but the stream header "
            f"declares {schema.n_obstacles} from frame 0. Obstacles are static "
            "and are written every frame; a changing count means the header is "
            "a lie."
        )

    cells = [_fixed(frame.t, "t", where)]
    cells += [_fixed(v, f"q_{i}", where) for i, v in enumerate(frame.q)]
    cells += [_fixed(v, f"qd_{i}", where) for i, v in enumerate(frame.qd)]
    if schema.base_vel:
        cells += [
            _fixed(frame.base_vel.vx, "base_vx", where),
            _fixed(frame.base_vel.vy, "base_vy", where),
            _fixed(frame.base_vel.omega, "base_omega", where),
            frame.base_vel.source.value,
        ]
    if schema.base_pose:
        cells += [
            _fixed(frame.base_pose.x, "base_pose_x", where),
            _fixed(frame.base_pose.y, "base_pose_y", where),
            _fixed(frame.base_pose.theta, "base_pose_theta", where),
            frame.base_pose.source.value,
        ]
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


def _check_base_agrees(
    value: object, declared: bool, what: str, where: str
) -> None:
    """Refuse a frame whose base differs in *shape* from the header's.

    The header is derived from frame 0, so a later frame that gained or lost a
    base is a stream one header cannot describe. Both directions are refusals and
    for different reasons, which is why the message says which one happened:

    * **Carries one, header has no columns for it.** Writing it would drop the
      base, and the file would read back as a fixed-base run — same header, same
      width, every check downstream green, and the fact that the base was there
      gone with no record of it.
    * **Header has columns, frame records none.** There is nothing honest to put
      in the cells. Zeros would say the base was measured and found still, and a
      blank would be read back as a number that is not one.
    """
    if (value is not None) == declared:
        return
    if value is not None:
        raise StreamFormatError(
            f"{where}: carries a {what} ({value!r}) and this stream has no "
            f"columns for one — the header is derived from frame 0, which "
            "recorded none. Writing it would drop the value and the file would "
            "read back as a run that never had it, which nothing downstream "
            "could detect. One header cannot describe a stream whose shape "
            "changes."
        )
    raise StreamFormatError(
        f"{where}: records no {what}, but frame 0 did, so this stream has "
        "columns for one. There is no honest cell to write: zeros would say the "
        "base was measured and found still, which is a different fact from not "
        "having been recorded. One header cannot describe a stream whose shape "
        "changes."
    )


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
