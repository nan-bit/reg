"""The compression benchmark — **Claim 1, the commercial argument**.

    python -m reg.bench --all --scaling --out bench/results.md

Claim 1 is the number a skeptic attacks first, so this file is written to be
harder on itself than a reader would be. Five rules follow from that, and they
are the whole design:

**1. The headline ratio is measured against *gzipped* CSV, not raw CSV.** The
first question anyone asks is whether the evidence graph is merely beating an
uncompressed text format. The answer is in the headline rather than in a footnote,
and the baseline is gzipped at the *maximum* level (`GZIP_COMPRESSLEVEL`), which
is the setting most favourable to the thing being beaten. The headline divides
that best-case baseline by the SQLite artifact **as it sits on disk**, not by a
gzipped copy of it — of the three ratios in the table that is the smallest, and
the smallest true number is worth more here than the largest one.

**2. A projection is labelled a projection, in the output.** docs/plan.md's
terabytes/day figure for a real humanoid is imported context; nothing in this
simulator measures it. If `--sensor-multiplier` is supplied the table carries a
projected column computed from that stated multiplier and labelled PROJECTION on
the same line as the number. If it is not supplied there is no projected column
and the report says why — an invented "conservative 100x" would be
indistinguishable from a measurement two pages later.

**3. Compression is only a result if the answers survive it.** A ratio on its own
is a statement about an encoder. Every scenario therefore also answers one fixed
audit question — the minimum robot-to-human separation over the run, query 1 of
docs/lossiness.md's supported set, reduced to a scalar — twice: from the graph
alone, and from the raw CSV as ground truth. The report carries both answers, the
verdict (`AGREE` / `DISAGREE` / `COULD-NOT-EVALUATE`), and the wall-clock cost of
each path. A `DISAGREE` is a bug in the graph, not a tolerance to widen
(docs/lossiness.md, "How to tell if this contract is being violated").

**4. Determinism, and an honest boundary around it.** Every byte count, ratio,
row count and answer here is a deterministic function of (scenario, seed,
envelope parameters) — `tests/test_bench.py` runs a scenario twice and compares.
Wall-clock timings are *not*, they are measurements of a machine, and the report
says so on the table that carries them rather than letting a reader assume the
whole file is reproducible bit for bit.

**5. A ratio at one run length is not a claim about scaling** (issue #30). Claim
1 is a claim about retaining evidence from runs that produce terabytes a day, and
the six scenarios are six seconds each — the one regime where the answer cannot
be read off, because a near-constant schema-and-index cost dominates everything.
`--scaling` therefore measures one fixture at a ladder of lengths and reports the
ratio as a function of run length, plus the length at which it passes 1.0 — or
says plainly that it does not, within the range actually executed. **Nothing is
extrapolated.** The marginal columns are arithmetic between two measured points,
never a fitted curve, and a crossover that was not measured is not quoted.

**6. Since issue #30 answered the ratio question — no — the measured variable is
resolution** (issue #35). `--scaling` established that the artifact is ~14x
*larger* per frame than a gzipped copy of the stream at every length up to 30,000
frames, and that this is structural rather than an encoding detail. What that
exposed is that `reg` chose cm / 10 ms, every frame, while UN R157's DSSAD — the
only mandated evidence recorder for autonomy — stores occurrences at ±1.0 s. So
`--resolution` prices the choice: the occurrence layer, the transition layer and
a per-frame expansion, **as three views of one build**, reporting bytes/hour and
whether each level still answers the supported questions within their stated
tolerances. It reports the divergence rather than tuning it away, and it quotes
**no ratio against the CSV** — docs/plan.md Claim 1 forbids one while the
measured ratio is below 1.

WHAT THIS BENCHMARK DOES NOT CLAIM
----------------------------------
* The raw stream is a *simulator state stream*, not a sensor log. It is the
  baseline docs/plan.md chose (CSV, obstacles re-logged every frame precisely so
  the baseline is not quietly pre-compressed), and the measured claim is
  graph-vs-logged-state. Nothing else.
* The envelope is a sampling-based **under-approximation** (`reg.envelope`). A
  looser envelope would intersect more entities and produce *more* rows, so the
  compression number is not flattered by it — but no claim here upgrades it.
* Bytes are bytes on disk. No claim is made about what either format would cost
  in a different container, at a different float precision, or after a schema
  change; `reg.stream.FLOAT_PRECISION` and `reg.store.SCHEMA_VERSION` are both in
  the report header because both move this number.

LAYER
-----
Mixed-layer, like `reg.graph`: it reads the raw CSV, which carries the human. The
Layer A boundary is not weakened here — the ground-truth path recomputes the
robot body from `frame.proprio()` and `limits`, and the envelope is never
recomputed outside `reg.graph`.
"""

from __future__ import annotations

import argparse
import bisect
import gzip
import math
import shutil
import sqlite3
import statistics
import sys
import tempfile
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from shapely.ops import unary_union

from reg import __version__, graph, store
from reg.envelope import SUBSTEP_DT
from reg.kinematics import link_polygons

# The query layer, imported by name rather than as a module (issue #37). Several
# functions below take a `ResolutionQuery` parameter called `query`, and a module
# of the same name sitting in the global scope is a shadowing bug waiting for the
# first person who reaches for it inside one of them.
from reg.query import (
    COULD_NOT_EVALUATE,
    EDGE_LAYER,
    OCCURRENCE_LAYER,
    QueryError,
    available_layers,
    did_contact_occur,
    frame_period,
    frame_times,
    min_separation,
    separation_timeline,
    time_of_closest_approach,
)
from reg.scenarios import SCENARIOS, Scenario, long_run, scenario
from reg.sim import DEFAULT_SEED, provenance
from reg.stream import FLOAT_PRECISION, read_frames, write_frames
from reg.tolerances import (
    DISTANCE_TOL_M,
    TIME_TOL_S,
    distance_bucket,
    quantize_distance,
    quantize_time,
)
from reg.world import World

__all__ = [
    "AGREE",
    "CLAIM_1_SUCCESS_RATIO",
    "COULD_NOT_EVALUATE",
    "DISAGREE",
    "GZIP_COMPRESSLEVEL",
    "INDEX_LABEL",
    "MET",
    "NOT_MET",
    "OCCURRENCE_LEVEL",
    "PER_FRAME_LEVEL",
    "QUESTION",
    "RESOLUTION_FRAME_COUNT",
    "RESOLUTION_LEVELS",
    "RESOLUTION_QUERIES",
    "SCALING_FRAME_COUNTS",
    "SCALING_N_SAMPLES",
    "TIMING_REPEATS",
    "TRANSITION_LEVEL",
    "BenchError",
    "Crossover",
    "GroundTruth",
    "LevelCheck",
    "ResolutionCurve",
    "ResolutionPoint",
    "ResolutionQuery",
    "ScalingPoint",
    "ScenarioResult",
    "SeparationCheck",
    "Sizes",
    "Timing",
    "agreement",
    "answers_at_level",
    "check_level",
    "claim_verdict",
    "compression_ratio",
    "crossover",
    "ground_truth_from_csv",
    "gzip_bytes",
    "main",
    "materialize_level",
    "min_separation_from_csv",
    "min_separation_from_graph",
    "render",
    "run_resolution_curve",
    "run_scaling_point",
    "run_scenario",
    "sensor_projection_bytes",
    "table_bytes",
]

EXIT_OK = 0

#: The report was written and a cross-check in it did not say `AGREE`. Distinct
#: from a usage error because it is a different thing to fix, and distinct from
#: `EXIT_OK` because a benchmark whose answers stopped surviving compression has
#: failed at the only thing that makes the ratio worth quoting.
EXIT_CHECK_FAILED = 1
EXIT_USAGE = 2

#: Maximum gzip level, which is the level most favourable to the *baseline* —
#: the thing this benchmark is trying to beat. Fixed rather than exposed as a
#: flag: a compression claim whose baseline strength is a caller's choice is not
#: a claim. It is printed in the report header so nobody has to read this file
#: to know which level produced a number.
GZIP_COMPRESSLEVEL = 9

#: gzip writes a modification time into its header. Left to itself that makes the
#: compressed *bytes* differ between two runs of the same command while their
#: length stays the same — a difference that means nothing and would break a
#: byte-comparison of two runs. Pinned to 0, the same reason `reg.stream` pins
#: the line terminator.
GZIP_MTIME = 0

#: Timed runs per query path; the reported figure is their median. Three, and
#: stated in the report rather than left implicit: one sample of a wall-clock
#: measurement on a shared machine is a number nobody can interpret, and a large
#: number would make the benchmark's own runtime the story. The median rather
#: than the mean because a scheduler hiccup in one repeat should not move the
#: figure. This is a measurement protocol, not a physical parameter — it changes
#: the precision of the timing columns and nothing else in the report.
TIMING_REPEATS = 3

#: The fixed audit question both paths answer. Query 1 of docs/lossiness.md's
#: supported question set (`separation_timeline`), reduced to the scalar an
#: incident review actually asks for. Chosen because it is answerable from
#: *both* sides: the graph holds it as `min_distance` on `SEPARATION` edges, and
#: the CSV can be replayed into it frame by frame. A question the CSV could only
#: answer by rebuilding the whole graph would make the timing comparison a
#: statement about the build, not about the query.
QUESTION = "minimum robot-to-human separation over the run"

#: Verdict vocabulary. Fixed and small, and the third never resolves to the
#: first: a graph with no separation rows for the human answers
#: `COULD-NOT-EVALUATE`, never `AGREE` on the strength of an empty result set.
#:
#: `COULD_NOT_EVALUATE` is **imported** from `reg.query` rather than assigned
#: here (issue #37). It is one verdict with one meaning, and the query layer is
#: where it is produced; two modules each defining the string would be two
#: definitions of the same word, which is the trap this repo keeps naming.
AGREE = "AGREE"
DISAGREE = "DISAGREE"

Verdict = Literal["AGREE", "DISAGREE", "COULD-NOT-EVALUATE"]

#: Claim 1's success criterion, imported from docs/plan.md rather than chosen
#: here: "**Success:** 2–4 orders of magnitude, one number, one chart." Two
#: orders of magnitude is 100x, so that is the bar the headline is measured
#: against and the report prints `MET` or `NOT MET` beside it. A benchmark whose
#: headline cannot come out negative is an advertisement; this is the number the
#: whole commercial argument rests on, so it gets a verdict like everything else
#: in this project that gates something.
CLAIM_1_SUCCESS_RATIO = 100.0

MET = "MET"
NOT_MET = "NOT MET"

#: The ladder of run lengths the scaling study measures, in frames. Stated by
#: issue #30 ("300, 1k, 3k, 10k, 30k frames"), not chosen here, and printed in
#: the report so a table cut short is visibly cut short rather than quietly
#: shorter than the study it claims to be. At 50 Hz the last one is ten minutes
#: of robot time — still nothing like a shift, and the report says so.
SCALING_FRAME_COUNTS: tuple[int, ...] = (300, 1_000, 3_000, 10_000, 30_000)

#: `n_samples` for the ladder, and the one parameter in this file chosen for
#: cost rather than fidelity. It is a real choice with a real consequence, so
#: both are here and both are in the report:
#:
#: * **Why it is legitimate at all.** Since issue #28 the envelope polygon is not
#:   stored, so `n_samples` moves *no byte count* in the table. It moves compute
#:   time, and it moves which frames count as overlapping.
#: * **What it costs.** The envelope is an under-approximation that grows
#:   monotonically with `n_samples` (`reg.envelope`), so a reduced value can only
#:   *remove* overlaps — fewer INTERSECTS rows, fewer retained envelope rows, a
#:   smaller artifact. The bias is in the flattering direction, which is why the
#:   report carries a control row: the shortest ladder length re-measured at the
#:   `--n-samples` the per-scenario table uses, so the size of the bias is a
#:   measurement rather than an assurance.
#: * **Why 16.** Measured on the machine that wrote the first version of this
#:   file: ~35 ms per frame at 16 samples against ~1.18 s at 512. The full ladder
#:   is 44,300 frames — half an hour at 16, fourteen and a half hours at 512.
#:   A 30k row nobody can afford to reproduce is worth less than one they can.
SCALING_N_SAMPLES = 16

# --------------------------------------------------------------------------
# The resolution curve (issue #35). What replaced Claim 1 after issue #30
# refuted it: not "is the graph smaller than the stream" — measured, no — but
# "what does evidence cost per unit of resolution, and how coarse can it get
# before it stops answering the question?" (docs/plan.md Claim 1, "What replaces
# it".)
#
# Three levels, and they are three **views of one build**. Not three builds: a
# curve whose points differ in the simulator run, the envelope parameters or the
# builder would be measuring those, and the whole claim is about resolution.
# --------------------------------------------------------------------------

#: DSSAD-aligned: the occurrence layer alone, timestamps at the artifact's stated
#: occurrence resolution (`reg.graph.OCCURRENCE_TIME_RESOLUTION_S`, ±1.0 s from
#: UN R157). Entities and provenance stay — an occurrence naming an entity the
#: file does not contain is not a record of anything.
OCCURRENCE_LEVEL = "occurrence"

#: The current edge emission: one row per relationship transition, endpoints at
#: `TIME_TOL_S`. This is what `reg.graph` has produced since issue #14.
TRANSITION_LEVEL = "transition"

#: One row per frame per relationship — the density the incremental rule exists
#: to avoid, materialized from the transition view so that the cost of *not*
#: having the rule is a measurement in the same table rather than an argument.
PER_FRAME_LEVEL = "per-frame"

#: Coarsest first, so the table reads as a curve.
RESOLUTION_LEVELS: tuple[str, ...] = (
    OCCURRENCE_LEVEL,
    TRANSITION_LEVEL,
    PER_FRAME_LEVEL,
)

#: The run length the resolution curve is measured at, in frames. **Not chosen
#: here**: it is the middle rung of issue #30's ladder, which issue #35 says to
#: use sparingly — "one moderate length is enough to establish the curve". At
#: 50 Hz it is 60 s of robot time, long enough that the fixed schema-and-index
#: cost is not the whole artifact and short enough to reproduce.
RESOLUTION_FRAME_COUNT = 3_000

#: Seconds in an hour. Named because `bytes/hour` is the figure docs/plan.md
#: quotes for retention and a literal 3600 in the middle of an arithmetic
#: expression is the kind of number nobody checks.
SECONDS_PER_HOUR = 3_600.0

#: The agreement predicate for query 1, quoted from docs/lossiness.md's table:
#: "per sampled frame, |d_graph - d_csv| <= DISTANCE_TOL_M". It is imported, not
#: restated as a literal — `reg.tolerances` is the only place a tolerance is
#: assigned, and a `0.01` here would be a defect even though it is the right
#: number.
SEPARATION_TOLERANCE_M = DISTANCE_TOL_M


class BenchError(Exception):
    """The benchmark could not produce a number it was asked for.

    Never a substituted value. A ratio computed against a zero-byte artifact, a
    projection with no multiplier, or a timing whose repeats disagreed are all
    could-not-evaluate, and every one of them would otherwise land in a table as
    a figure indistinguishable from a measured one.
    """


# --------------------------------------------------------------------------
# The measured quantities. Each is a pure function of its inputs, so
# tests/test_bench.py can assert the arithmetic on a hand-worked example rather
# than on live numbers that will move with every change to the graph.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Sizes:
    """The four byte counts every ratio in the report is built from."""

    raw_csv: int
    gzip_csv: int
    sqlite: int
    gzip_sqlite: int

    @property
    def ratio_vs_raw(self) -> float:
        """Raw CSV bytes per byte of graph. The number a reader arrives with."""
        return compression_ratio(self.raw_csv, self.sqlite)

    @property
    def ratio_vs_gzip_csv(self) -> float:
        """**The headline.** Best-case baseline over the artifact on disk.

        The most conservative of the three: the baseline gets the benefit of
        maximum gzip and the graph gets none. Reported first everywhere.
        """
        return compression_ratio(self.gzip_csv, self.sqlite)

    @property
    def ratio_like_for_like(self) -> float:
        """Both sides gzipped. Larger than the headline, and secondary to it."""
        return compression_ratio(self.gzip_csv, self.gzip_sqlite)


@dataclass(frozen=True)
class Timing:
    """Wall-clock for one query path. **Not deterministic** — see the module
    docstring; the report labels the table that carries these."""

    seconds: float
    repeats: int


@dataclass(frozen=True)
class SeparationCheck:
    """The fixed question, answered twice, with a verdict that can say no.

    `graph_answer` and `csv_answer` are metres, or `None` where that path could
    not answer at all. `None` is a refusal and never a zero: a zero separation
    reads as contact.
    """

    verdict: Verdict
    graph_answer: float | None
    csv_answer: float | None
    tolerance: float
    graph_timing: Timing
    csv_timing: Timing

    @property
    def difference(self) -> float | None:
        if self.graph_answer is None or self.csv_answer is None:
            return None
        return abs(self.graph_answer - self.csv_answer)

    @property
    def speedup(self) -> float | None:
        """How many times faster the graph path was. `None` if either path was
        not timed to a positive duration — a division there would print an
        infinity that reads as a result."""
        if self.graph_timing.seconds <= 0.0 or self.csv_timing.seconds <= 0.0:
            return None
        return self.csv_timing.seconds / self.graph_timing.seconds


@dataclass(frozen=True)
class ScenarioResult:
    """Everything the report says about one scenario."""

    scenario: str
    frames: int
    nodes: dict[str, int]
    edges: dict[str, int]
    sizes: Sizes
    check: SeparationCheck
    #: Bytes per table, from `table_bytes`, or `None` where this SQLite build
    #: could not attribute them. Reported because a ratio nobody can attribute
    #: is a ratio nobody can act on: if the artifact is large, this says which
    #: table made it large.
    tables: dict[str, int] | None

    @property
    def total_nodes(self) -> int:
        return sum(self.nodes.values())

    @property
    def total_edges(self) -> int:
        return sum(self.edges.values())


@dataclass(frozen=True)
class ScalingPoint:
    """One run length, measured. The unit of the scaling table (issue #30).

    A `ScenarioResult` and the `n_samples` it was measured at, because the
    ladder and the control row differ in exactly that one parameter and a table
    that carried the numbers without it would put two different measurements in
    one column.
    """

    result: ScenarioResult
    n_samples: int
    #: The fixture's frame period, so the report can say how much *robot time* a
    #: row is. Ten minutes of it is still not a shift, and a table that only
    #: counted frames would let that go unsaid.
    frame_period_s: float

    @property
    def frames(self) -> int:
        return self.result.frames

    @property
    def seconds(self) -> float:
        """Robot time in this run: frames are a sampling rate, not a duration."""
        return (self.result.frames - 1) * float(self.frame_period_s)

    @property
    def sizes(self) -> Sizes:
        return self.result.sizes

    @property
    def ratio(self) -> float:
        """The headline ratio at this length: gzipped CSV over SQLite on disk."""
        return self.result.sizes.ratio_vs_gzip_csv


@dataclass(frozen=True)
class Crossover:
    """Where the ratio passes 1.0 — **among the lengths actually measured**.

    `crossed_at` is `None` when no measured length reached 1.0. That is a
    finding, not a gap to fill: the alternative is fitting a curve to five
    points and quoting the root, which would put a length nobody ran into the
    same table as five they did.

    `fell_back_below` names any measured length *above* `crossed_at` whose ratio
    is below 1.0 again. It is normally empty; when it is not, the ratio is not
    monotone in run length and "the crossover" is the wrong shape of answer, so
    the report says so instead of quoting the first crossing alone.
    """

    crossed_at: int | None
    largest_measured: int
    smallest_measured: int
    fell_back_below: tuple[int, ...]


def crossover(points: Sequence[ScalingPoint]) -> Crossover:
    """The crossover among `points`. Measured lengths only; nothing is fitted."""
    if not points:
        raise BenchError(
            "no scaling points, so there is nothing to look for a crossover in. "
            "An empty ladder would report 'no crossover' — which is a finding "
            "about the ratio, and this is the absence of a measurement."
        )
    ordered = sorted(points, key=lambda p: p.frames)
    crossed = next((p.frames for p in ordered if p.ratio >= 1.0), None)
    fell_back = (
        tuple(p.frames for p in ordered if p.frames > crossed and p.ratio < 1.0)
        if crossed is not None
        else ()
    )
    return Crossover(
        crossed_at=crossed,
        largest_measured=ordered[-1].frames,
        smallest_measured=ordered[0].frames,
        fell_back_below=fell_back,
    )


def claim_verdict(ratio: float) -> str:
    """`MET` or `NOT MET` against Claim 1's stated success criterion.

    Not a formatting nicety. docs/plan.md fixes the bar at 2-4 orders of
    magnitude and this benchmark exists to test it, so the headline gets a
    verdict that can come out negative — including the case that matters most,
    a ratio below 1, where the "compressed" artifact is larger than the stream
    it replaced.
    """
    return MET if float(ratio) >= CLAIM_1_SUCCESS_RATIO else NOT_MET


#: The tables the breakdown names one by one. Everything else SQLite keeps in
#: the file — the automatic and declared indexes, the schema — is summed into
#: `INDEX_LABEL`, because "which table" is the actionable question and "which
#: index" is not.
#:
#: `node` is named rather than swept into `INDEX_LABEL` (issue #55). It is where
#: every readable identifier in the artifact now lives, and identifier text is
#: exactly what that issue's measurement was about — attributing it to "indexes
#: + schema" would hide the cost of the thing being traded against.
_TABLE_LABELS: tuple[str, ...] = (
    "node",
    *[t for t, _ in store.NODE_TABLES.values()],
    "edge",
    "meta",
)
INDEX_LABEL = "indexes + schema"


def table_bytes(sqlite_path: str | Path) -> dict[str, int] | None:
    """Bytes per table in the artifact, from SQLite's own `dbstat`. Or `None`.

    `None` means this SQLite build has no `dbstat` virtual table, which is a
    could-not-evaluate: the report then says the bytes could not be attributed
    rather than printing an estimate. An estimate of where the bytes went is
    exactly as convincing as an estimate of how many there are, and `length()`
    over the columns misses precisely the parts — page overhead and indexes —
    that turn out to matter.

    The values sum to the file size (less any free pages), so the breakdown is
    an attribution rather than a sample of one.
    """
    conn = store.connect(sqlite_path)
    try:
        try:
            rows = conn.execute(
                "SELECT name, sum(pgsize) AS bytes FROM dbstat GROUP BY name"
            ).fetchall()
        except sqlite3.OperationalError:
            return None
        out: dict[str, int] = {label: 0 for label in (*_TABLE_LABELS, INDEX_LABEL)}
        for row in rows:
            name = str(row["name"])
            label = name if name in out else INDEX_LABEL
            out[label] += int(row["bytes"] or 0)
    finally:
        conn.close()
    return out


def compression_ratio(baseline_bytes: int, artifact_bytes: int) -> float:
    """`baseline_bytes / artifact_bytes`, refusing the degenerate cases.

    A zero-byte artifact would divide to infinity and print as the best
    compression ratio ever recorded; a zero-byte baseline would print as none at
    all. Both mean a file was not written, which is a could-not-evaluate.
    """
    baseline_bytes = int(baseline_bytes)
    artifact_bytes = int(artifact_bytes)
    if artifact_bytes <= 0:
        raise BenchError(
            f"artifact is {artifact_bytes} bytes, so a compression ratio against "
            "it is a division by zero. An empty artifact is a build that did not "
            "happen, not infinite compression."
        )
    if baseline_bytes <= 0:
        raise BenchError(
            f"baseline is {baseline_bytes} bytes. A ratio against an empty "
            "baseline is zero, which would read as 'the graph is larger' rather "
            "than as 'the baseline was never written'."
        )
    return baseline_bytes / artifact_bytes


def sensor_projection_bytes(raw_csv_bytes: int, multiplier: float) -> int:
    """Projected bytes for a "realistic sensor" stream. **Not a measurement.**

    docs/plan.md Phase 8: "Be honest about the projection. The claim you can
    actually measure is graph-vs-logged-state. The terabytes/day figure is
    imported context, not a result from this sim." So there is no default
    multiplier here and none in the CLI — the caller states one or the report
    carries no projected column at all.

    `multiplier < 1` is refused: a projection of a *richer* stream than this
    simulator's state stream cannot be smaller than it, and a multiplier below 1
    would be a projection that flatters the baseline into looking cheap while
    still being labelled conservative.
    """
    raw_csv_bytes = int(raw_csv_bytes)
    multiplier = float(multiplier)
    if raw_csv_bytes <= 0:
        raise BenchError(
            f"raw stream is {raw_csv_bytes} bytes; there is nothing to project "
            "from."
        )
    if not multiplier >= 1.0:
        raise BenchError(
            f"sensor multiplier is {multiplier}. A realistic sensor stream is "
            "richer than this simulator's state stream, so the multiplier is at "
            "least 1; below that the 'projection' shrinks the baseline while "
            "still being labelled conservative."
        )
    return int(round(raw_csv_bytes * multiplier))


def agreement(
    graph_answer: float | None, csv_answer: float | None, tolerance: float
) -> Verdict:
    """The verdict for one cross-check. Three outcomes, and the third stays third.

    Either answer missing is `COULD-NOT-EVALUATE`: an absent separation row and a
    separation of zero are entirely different facts, and the first must never be
    read as agreement with the second.
    """
    tolerance = float(tolerance)
    if tolerance < 0.0:
        raise BenchError(
            f"tolerance is {tolerance}; a negative tolerance makes every "
            "comparison fail for a reason that has nothing to do with the graph."
        )
    if graph_answer is None or csv_answer is None:
        return COULD_NOT_EVALUATE
    return AGREE if abs(graph_answer - csv_answer) <= tolerance else DISAGREE


def gzip_bytes(path: str | Path) -> int:
    """Size of `path` gzipped at `GZIP_COMPRESSLEVEL`, in bytes.

    Compressed in memory and thrown away — the compressed file is not an artifact
    of this project, only its length is a measurement.
    """
    path = Path(path)
    data = path.read_bytes()
    if not data:
        raise BenchError(
            f"{path} is empty. A zero-byte file is a step of the pipeline that "
            "did not run, and gzipping it would put a 20-byte header into the "
            "table as though it were a compressed stream."
        )
    return len(
        gzip.compress(data, compresslevel=GZIP_COMPRESSLEVEL, mtime=GZIP_MTIME)
    )


# --------------------------------------------------------------------------
# The fixed question, answered from each side.
# --------------------------------------------------------------------------


def min_separation_from_graph(
    sqlite_path: str | Path, entity_id: str = graph.HUMAN_ENTITY_ID
) -> float | None:
    """`QUESTION`, from the artifact alone. `None` if it cannot be answered.

    This is one aggregate over the `SEPARATION` edges — the graph stores the
    metric per interval, so the whole run is a single scan of a few dozen rows
    rather than a replay of a few hundred frames. That is the query claim, and
    the timing beside it in the report is the evidence for it.

    `None` (rather than `float('inf')`, or 0.0) when the artifact holds no
    separation row for the entity: the artifact is silent, and silence about a
    separation is not a large separation. An entity the artifact never declared
    is `None` for the same reason — `reg.query` refuses it by name, and the
    refusal is narrowed to `None` here because this function's whole contract is
    "the answer, or nothing".

    **This is now `reg.query.min_separation` with the timing wrapper around it**
    (issue #37). It was a second implementation of the same question until the
    query layer landed; the ground-truth-from-CSV path below is the *other*
    implementation and stays, because the comparison between them is the check.
    """
    conn = store.connect(sqlite_path)
    try:
        answer = min_separation(conn, str(entity_id))
    except QueryError:
        return None
    finally:
        conn.close()
    return float(answer.value) if answer.answered else None  # type: ignore[arg-type]


def min_separation_from_csv(csv_path: str | Path, world: World) -> float | None:
    """`QUESTION`, recomputed from the raw stream. The ground truth to compare to.

    docs/lossiness.md's agreement table specifies exactly this construction for
    query 1: "FK per frame -> min distance to entity". The body comes from
    `frame.proprio()` and `world.limits` — Layer A inputs, even here — and the
    human from `World.human_polygon`, whose radius is a property of the world and
    is *not* a column of the CSV. That the raw path needs a parameter the raw
    file does not carry is worth noticing: the graph records it in `meta`.

    One `World` rather than a world and a separate `Limits`: two arguments that
    can disagree about which robot this is would answer the question for a robot
    that produced neither file.

    Geometry is deliberately *not* simplified here. The graph simplifies the
    entity boundary and quantizes the distance; this path does neither, so the
    two differ by exactly the error budget docs/lossiness.md allocates
    (`GEOM_SIMPLIFY_TOL_M + DISTANCE_TOL_M / 2 <= DISTANCE_TOL_M`), and the
    comparison is a real check of that budget rather than of one code path
    against itself.
    """
    best: float | None = None
    for frame in read_frames(csv_path):
        body = unary_union(link_polygons(frame.proprio(), world.limits))
        distance = float(body.distance(world.human_polygon(frame.human_pos)))
        best = distance if best is None else min(best, distance)
    return best


def _timed(
    answer: Callable[[], float | None], repeats: int, label: str
) -> tuple[float | None, Timing]:
    """Run `answer` `repeats` times; return its answer and the median duration.

    The answers are compared across repeats and a disagreement is a refusal. Both
    paths here are pure functions of a file on disk, so a repeat that answers
    differently means one of them is reading something that is not in the file —
    and averaging two different answers into one table cell would hide it.
    """
    repeats = int(repeats)
    if repeats < 1:
        raise BenchError(f"{label}: repeats={repeats}; nothing would be measured.")

    durations: list[float] = []
    answers: list[float | None] = []
    for _ in range(repeats):
        start = time.perf_counter()
        answers.append(answer())
        durations.append(time.perf_counter() - start)

    if any(a != answers[0] for a in answers[1:]):
        raise BenchError(
            f"{label}: the same query answered {answers!r} across {repeats} "
            "repeats of the same input. One of these is wrong and there is no "
            "way to tell which; refusing to report a median of them."
        )
    return answers[0], Timing(seconds=statistics.median(durations), repeats=repeats)


# --------------------------------------------------------------------------
# Running one scenario end to end
# --------------------------------------------------------------------------


def run_scenario(
    name: str,
    work_dir: str | Path,
    *,
    seed: int,
    horizon: float,
    n_samples: int,
    envelope_seed: int,
    substep_dt: float,
    occurrence_resolution_s: float,
    timing_repeats: int = TIMING_REPEATS,
) -> ScenarioResult:
    """Simulate, build, measure. Every parameter is required and none is guessed.

    `seed`, `horizon`, `n_samples`, `envelope_seed`, `substep_dt` and
    `occurrence_resolution_s` all move the numbers this function returns, so none
    of them has a default here — the CLI supplies them and the report prints
    them. `run_scenario(name, dir)` alone would produce a table of numbers nobody
    could reproduce, which is the failure the whole determinism rule exists to
    prevent.

    Args:
        name: a scenario in `reg.scenarios.SCENARIOS`.
        work_dir: where the intermediate CSV and SQLite go. Its location does not
            enter any measurement; only the sizes of the files do.
        timing_repeats: timed runs per query path, median reported.

    Returns:
        A `ScenarioResult`. Its byte counts, ratios and row counts are a
        deterministic function of the arguments; its timings are not.
    """
    return _measure(
        scenario(name),
        work_dir,
        seed=seed,
        horizon=horizon,
        n_samples=n_samples,
        envelope_seed=envelope_seed,
        substep_dt=substep_dt,
        occurrence_resolution_s=occurrence_resolution_s,
        timing_repeats=timing_repeats,
    )


def run_scaling_point(
    frames: int,
    work_dir: str | Path,
    *,
    seed: int,
    horizon: float,
    n_samples: int,
    envelope_seed: int,
    substep_dt: float,
    occurrence_resolution_s: float,
    timing_repeats: int = TIMING_REPEATS,
) -> ScalingPoint:
    """One rung of the scaling ladder: the long-run fixture at `frames` frames.

    Same measurement as `run_scenario` — same stream format, same builder, same
    cross-check — on `reg.scenarios.long_run(frames)`. The only thing that
    varies down the ladder is the length, which is the point: a ratio measured
    at one length and a ratio measured at another have to differ in nothing else
    or the comparison between them is not about scaling.
    """
    scn = long_run(frames)
    return ScalingPoint(
        result=_measure(
            scn,
            work_dir,
            seed=seed,
            horizon=horizon,
            n_samples=n_samples,
            envelope_seed=envelope_seed,
            substep_dt=substep_dt,
            occurrence_resolution_s=occurrence_resolution_s,
            timing_repeats=timing_repeats,
        ),
        n_samples=int(n_samples),
        frame_period_s=scn.dt,
    )


@dataclass(frozen=True)
class ResolutionQuery:
    """One question the curve asks at every level, and how agreement is judged.

    `tolerance` is `None` for a question whose answer is not a number — those get
    exact equality, the same way docs/lossiness.md gives queries 4-8 no numeric
    tolerance. It is never a knob: every value here is imported from
    `reg.tolerances`, and issue #35 forbids widening any of them, because
    loosening a tolerance changes what the artifact *claims* rather than what it
    *costs*, and cost is the variable under study.
    """

    name: str
    #: What the question is, in one line, for a reader of the report.
    question: str
    #: The agreement predicate, quoted from docs/lossiness.md where it has one.
    predicate: str
    tolerance: float | None
    #: Units for the report's delta column. Prose, not arithmetic.
    unit: str


#: The questions the curve asks. Every one is answerable from the **raw CSV by
#: forward kinematics alone**, and that is the selection rule rather than an
#: accident of what was easy:
#:
#: * docs/lossiness.md's queries 2 and 4 (`first_envelope_intersection`,
#:   `reachable_entities`) are about the *envelope*, and the only ground truth
#:   available for them here would be recomputing an envelope per frame with
#:   `reg.envelope` — the builder's own computation. A check whose ground truth
#:   reruns the code under test cannot fail, and shipping one would be exactly
#:   the "harness that has only ever been run against a healthy graph" that
#:   docs/lossiness.md rules out.
#: * queries 5-8 are declarations, verdicts and the chain. They are Milestone 3
#:   and no fixture produces them; asking them here would report
#:   `COULD-NOT-EVALUATE` for every level and say nothing about resolution.
#:
#: So four questions, each answerable independently, spanning the two things
#: resolution can cost: a *value* and a *time*.
RESOLUTION_QUERIES: tuple[ResolutionQuery, ...] = (
    ResolutionQuery(
        name="min_separation",
        question="the minimum robot-to-human separation over the run",
        predicate="|d_level - d_csv| <= DISTANCE_TOL_M",
        tolerance=DISTANCE_TOL_M,
        unit="m",
    ),
    ResolutionQuery(
        name="time_of_closest_approach",
        question="when the closest approach to the human happened",
        predicate=(
            "|t_level - t| <= TIME_TOL_S for some frame t whose separation is "
            "within DISTANCE_TOL_M of the run's minimum"
        ),
        tolerance=TIME_TOL_S,
        unit="s",
    ),
    ResolutionQuery(
        name="separation_timeline",
        question=(
            "the robot-to-human separation at every frame (query 1 of "
            "docs/lossiness.md's supported set, in full)"
        ),
        predicate="per sampled frame, |d_level - d_csv| <= DISTANCE_TOL_M",
        tolerance=DISTANCE_TOL_M,
        unit="m",
    ),
    ResolutionQuery(
        name="did_contact_occur",
        question="whether the robot body and the human ever intersected",
        predicate="exact equality — a missed or invented contact is a failure",
        tolerance=None,
        unit="",
    ),
)


@dataclass(frozen=True)
class GroundTruth:
    """The four answers recomputed from the raw stream. Computed **once**.

    Once, and shared by every level, for the same reason the curve is three views
    of one build: a ground truth recomputed per level would differ between levels
    by whatever the recomputation is not deterministic in, and the comparison
    would be measuring that.

    `min_separation` is the *unquantized* minimum, so the comparison against the
    artifact's quantized value spends the error budget docs/lossiness.md
    allocates — exactly what `SeparationCheck` already does.

    **`closest_approach_candidates` is a set, and that is the honest shape of
    the answer.** "When was the closest approach?" is the argmin of a quantity
    the artifact retains only to `DISTANCE_TOL_M`, and docs/lossiness.md
    *Unanswerable* #4 says a metric difference finer than the tolerance is
    unanswerable rather than false. So every frame whose separation is within one
    quantum of the run's minimum is a frame the artifact cannot distinguish from
    the minimum, and any of them is a correct answer. Comparing against a single
    argmin frame instead would fail every level by one frame period as soon as
    the graph's simplified entity boundary and this path's unsimplified one
    disagreed by a millimetre near a bucket edge — a failure about the geometry
    budget, reported in a table about resolution.

    This is not a widened tolerance. `TIME_TOL_S` still governs the comparison;
    what the candidate set fixes is *which instants the question has as correct
    answers*, which the lossiness contract already decided.
    """

    min_separation: float | None
    #: The earliest candidate — what the report prints as "the" answer.
    t_closest_approach: float | None
    #: Every frame within `DISTANCE_TOL_M` of the minimum, in frame order.
    closest_approach_candidates: tuple[float, ...]
    #: `(t, unquantized distance)` per frame, in frame order.
    timeline: tuple[tuple[float, float], ...]
    contact_occurred: bool

    @property
    def frames(self) -> int:
        return len(self.timeline)


@dataclass(frozen=True)
class LevelAnswers:
    """What one resolution level can say, with `None` for "it cannot say".

    `None` is a refusal and never a zero or a `False`: a level that holds no
    per-frame separation has not observed a separation of zero at every frame,
    and the difference is the whole reason this dataclass exists rather than a
    dict of numbers.
    """

    min_separation: float | None
    t_closest_approach: float | None
    timeline: tuple[tuple[float, float], ...] | None
    contact_occurred: bool | None


@dataclass(frozen=True)
class LevelCheck:
    """One query, at one level, with a verdict that can say no."""

    query: str
    verdict: Verdict
    #: The two answers and their difference, as the report prints them. Prose,
    #: because the answers are of three different types and a float column would
    #: have to invent a number for the boolean one.
    detail: str


@dataclass(frozen=True)
class ResolutionPoint:
    """One level, measured: what it costs and what it can still answer."""

    level: str
    #: The resolution this level's timestamps are recorded at, in seconds.
    timestamp_resolution_s: float
    size_bytes: int
    nodes: int
    edges: int
    occurrences: int
    #: Robot time in the run, so `bytes_per_hour` is a rate this point can state
    #: on its own rather than one only the curve can assemble.
    run_seconds: float
    checks: tuple[LevelCheck, ...]

    @property
    def bytes_per_hour(self) -> float:
        """The retention rate — **the headline for this table**.

        docs/plan.md Claim 1 forbids quoting a ratio against the CSV while the
        measured one is below 1, and this is what it says to quote instead: an
        absolute number, in the units a retention policy is written in.

        It is `bytes / run_seconds * 3600` and therefore scales the artifact's
        *fixed* schema-and-index cost by the same factor as its per-frame cost.
        Over a run much shorter than an hour that overstates the hourly rate, and
        the report says so on the table rather than here alone.
        """
        if self.run_seconds <= 0.0:
            raise BenchError(
                f"{self.level}: the run is {self.run_seconds} s of robot time, so "
                "a per-hour rate over it is a division by zero. A run of no "
                "duration is a measurement that did not happen."
            )
        return self.size_bytes * SECONDS_PER_HOUR / self.run_seconds

    @property
    def verdict(self) -> Verdict:
        """The level's overall verdict. **The third never resolves to the first.**

        A level that cannot answer a question does not thereby agree with it, so
        one `COULD-NOT-EVALUATE` makes the level's summary `COULD-NOT-EVALUATE`,
        and one `DISAGREE` makes it `DISAGREE` — a wrong answer outranks a
        missing one, because a level that answers wrongly is not a smaller
        artifact, it is a broken one.
        """
        verdicts = {c.verdict for c in self.checks}
        if not verdicts:
            return COULD_NOT_EVALUATE
        if DISAGREE in verdicts:
            return DISAGREE
        if COULD_NOT_EVALUATE in verdicts:
            return COULD_NOT_EVALUATE
        return AGREE


@dataclass(frozen=True)
class ResolutionCurve:
    """The whole curve: one build, three views, one ground truth."""

    scenario: str
    frames: int
    frame_period_s: float
    n_samples: int
    occurrence_resolution_s: float
    #: The build every point is a view of. Its own cross-check is a normal
    #: `SeparationCheck` and gates the exit code; the per-level checks below are
    #: the measurement and do not.
    source: ScenarioResult
    truth: GroundTruth
    points: tuple[ResolutionPoint, ...]

    @property
    def run_seconds(self) -> float:
        return (self.frames - 1) * float(self.frame_period_s)


def _work_paths(scn: Scenario, work_dir: str | Path) -> tuple[Path, Path]:
    """Where one scenario's stream and artifact live under `work_dir`.

    One function so that a caller wanting the artifact `_measure` just wrote —
    the resolution curve does, because it must not rebuild it — names it the same
    way `_measure` did rather than reconstructing the convention.
    """
    work_dir = Path(work_dir)
    return work_dir / f"{scn.name}.csv", work_dir / f"{scn.name}.sqlite"


def _write_stream(scn: Scenario, seed: int, path: Path) -> Path:
    """The raw stream for a `Scenario` object, byte-identical to `reg.sim`.

    `reg.sim.simulate` takes a *registered* name, and the long-run fixture is
    not registered — there is no single frame count that would be the right one
    to put in `SCENARIOS`. This is that function's body with the lookup removed,
    reusing `reg.sim.provenance` rather than restating the fields: a stream
    whose provenance block was written by a second implementation would drift
    from the one the CLI writes, and the drift would show up as a size
    difference in a table about sizes.
    """
    return write_frames(tuple(scn.states(seed)), path, comments=provenance(scn, seed))


def _measure(
    scn: Scenario,
    work_dir: str | Path,
    *,
    seed: int,
    horizon: float,
    n_samples: int,
    envelope_seed: int,
    substep_dt: float,
    occurrence_resolution_s: float,
    timing_repeats: int,
) -> ScenarioResult:
    """Simulate one scenario, build its graph, and measure both. No defaults."""
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    csv_path, sqlite_path = _work_paths(scn, work_dir)

    _write_stream(scn, seed, csv_path)
    result = graph.build(
        csv_path,
        sqlite_path,
        scn.world.limits,
        human_radius=scn.world.human_radius,
        horizon=horizon,
        n_samples=n_samples,
        seed=envelope_seed,
        substep_dt=substep_dt,
        occurrence_resolution_s=occurrence_resolution_s,
    )

    sizes = Sizes(
        raw_csv=csv_path.stat().st_size,
        gzip_csv=gzip_bytes(csv_path),
        sqlite=result.size_bytes,
        gzip_sqlite=gzip_bytes(sqlite_path),
    )

    graph_answer, graph_timing = _timed(
        lambda: min_separation_from_graph(sqlite_path),
        timing_repeats,
        f"{scn.name}: graph query",
    )
    csv_answer, csv_timing = _timed(
        lambda: min_separation_from_csv(csv_path, scn.world),
        timing_repeats,
        f"{scn.name}: raw CSV query",
    )

    return ScenarioResult(
        scenario=scn.name,
        frames=result.frames,
        nodes=dict(result.nodes),
        edges=dict(result.edges),
        sizes=sizes,
        tables=table_bytes(sqlite_path),
        check=SeparationCheck(
            verdict=agreement(graph_answer, csv_answer, SEPARATION_TOLERANCE_M),
            graph_answer=graph_answer,
            csv_answer=csv_answer,
            tolerance=SEPARATION_TOLERANCE_M,
            graph_timing=graph_timing,
            csv_timing=csv_timing,
        ),
    )


# --------------------------------------------------------------------------
# The three views. Each one is the built artifact with everything the level does
# not retain removed, then `VACUUM`ed so the bytes are the bytes that level
# would actually cost rather than the bytes plus the free pages its deletions
# left behind.
#
# Views, not builds. The simulator runs once, the graph is built once, and these
# three files are projections of it — which is what makes the table a curve over
# *resolution* rather than three measurements that differ in everything.
# --------------------------------------------------------------------------


def _asking(conn: sqlite3.Connection, what: str, ask):
    """Call a `reg.query` reader, restating its refusal as a `BenchError`.

    The benchmark's failures are `BenchError` and a `QueryError` escaping into
    `main` would be an uncaught traceback where every other could-not-evaluate
    here is a message. Nothing is swallowed — the query layer's sentence is the
    message.
    """
    try:
        return ask(conn)
    except QueryError as exc:
        raise BenchError(f"{what}: {exc}") from exc


def materialize_level(
    source: str | Path, level: str, out_path: str | Path
) -> Path:
    """Write the `level` view of an already-built artifact. Never rebuilds.

    Args:
        source: an artifact from `reg.graph.build`, left alone.
        level: one of `RESOLUTION_LEVELS`.
        out_path: where the view goes. Replaced if it exists.

    Returns:
        `out_path`, as a `Path`.

    Raises:
        BenchError: an unknown level, or a source artifact that does not carry
            the provenance the per-frame expansion needs. Both are
            could-not-evaluate; neither writes a partial view.
    """
    if level not in RESOLUTION_LEVELS:
        raise BenchError(
            f"{level!r} is not a resolution level. Known levels: "
            f"{list(RESOLUTION_LEVELS)}. The curve is a comparison between named "
            "views of one build, so a level nobody defined has no retention rule "
            "and its byte count would mean nothing."
        )

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.unlink(missing_ok=True)
    shutil.copyfile(Path(source), out_path)

    conn = store.connect(out_path)
    try:
        if level == OCCURRENCE_LEVEL:
            # Everything the edge layer holds goes. What stays is the occurrence
            # rows, the entity set they name, and the provenance — including the
            # retention rule itself, so the view still says what its own silences
            # mean.
            conn.execute("DELETE FROM edge")
            # `drop_nodes` and not `DELETE FROM envelope` (issue #55): the
            # readable identifier lives in `node` now, and a view that kept
            # identity rows for envelopes it no longer holds would measure as
            # larger than the view is. Each point on the curve has to cost what
            # that level costs.
            store.drop_nodes(conn, "Envelope")
            store.drop_nodes(conn, "RobotConfig")
        else:
            # The other two levels are the edge layer, so the occurrence rows go:
            # each point must cost what *that* level costs and not what it costs
            # plus a layer it does not use.
            store.drop_nodes(conn, "Occurrence")
        if level == PER_FRAME_LEVEL:
            _expand_to_frames(conn)
        conn.commit()
        # Outside a transaction, and the reason it is here rather than left to
        # the caller: without it the file keeps the pages the DELETEs freed and
        # the occurrence view measures as large as the artifact it came from.
        conn.execute("VACUUM")
        conn.commit()
    finally:
        conn.close()
    return out_path


def _expand_to_frames(conn: sqlite3.Connection) -> None:
    """Replace every interval with one row per frame it covers.

    The incremental rule run backwards. An edge spanning `[t_start, t_end]`
    asserts the relationship held at every frame in it, so expanding it invents
    nothing — it writes down what the interval already says, once per frame,
    which is what the artifact would have cost without the rule.

    **What this view is not.** It does not restore the per-frame `robot_config`
    and `envelope` rows that issue #29 removed: those were discarded at build
    time and there is nothing here to recover them from. So the per-frame point
    is a **lower bound** on what a per-frame artifact costs, and the report says
    so — an understatement in the direction that makes the coarser levels look
    *less* good, which is the direction to be wrong in.
    """
    # The frame grid comes from `reg.query`, which reconstructs it from
    # `t_first`, `frame_period_s` and `frame_count` in the artifact's own meta —
    # the same grid the timeline query answers on. Two reconstructions of one
    # sampling would let the view and the query disagree about which frames the
    # run had, which is the disagreement no table would show.
    times = _asking(conn, "the per-frame view", frame_times)
    rows = store.read_edges(conn)
    period = _asking(conn, "the per-frame view", frame_period)
    conn.execute("DELETE FROM edge")
    for row in rows:
        t_start = float(row["t_start"])
        t_end = float(row["t_end"])
        # Bisected rather than scanned: this runs once per edge over every frame
        # of the run, and the whole point of the view is to be measurable at a
        # length where that product is large.
        lo = bisect.bisect_left(times, t_start)
        hi = bisect.bisect_right(times, t_end)
        covered = list(times[lo:hi])
        if not covered:
            # An interval covering no sampled frame cannot be expanded into
            # per-frame rows without inventing a frame. It is kept as itself
            # rather than dropped: dropping it would make the per-frame view
            # answer "the relationship never held", which is a different run.
            covered = [t_start] if t_start == t_end else []
            if not covered:  # pragma: no cover - endpoints are frame times
                raise BenchError(
                    f"edge {row['edge_id']} spans [{t_start}, {t_end}], which "
                    f"contains no frame at period {period}. The per-frame view "
                    "would have to invent one."
                )
        for t in covered:
            conn.execute(
                """
                INSERT INTO edge (type, layer, src_kind, src_key, dst_kind,
                                  dst_key, t_start, t_end, overlap_area,
                                  min_distance)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["type"],
                    row["layer"],
                    row["src_kind"],
                    # The surrogates the source rows already carry (issue #55).
                    # The endpoints are the same nodes, so re-resolving their
                    # identifiers per frame would be the same answer at the cost
                    # of a lookup per row of a view built to be measured at
                    # length.
                    row["src_key"],
                    row["dst_kind"],
                    row["dst_key"],
                    t,
                    t,
                    row["overlap_area"],
                    row["min_distance"],
                ),
            )


# --------------------------------------------------------------------------
# The four questions, from each side.
# --------------------------------------------------------------------------


def ground_truth_from_csv(csv_path: str | Path, world: World) -> GroundTruth:
    """The four answers recomputed from the raw stream, in one pass.

    Forward kinematics from `frame.proprio()` and `world.limits` — Layer A inputs
    even here — against the human disc, exactly as `min_separation_from_csv`
    does. Geometry is deliberately not simplified, so the comparison against the
    artifact spends the error budget docs/lossiness.md allocates rather than
    checking one code path against itself.

    It takes no entity argument, unlike `answers_at_level`: the human is the only
    entity whose position the raw stream carries per frame, so it is the only one
    this path can recompute anything about at all.
    """
    timeline: list[tuple[float, float]] = []
    contact = False
    best_raw: float | None = None

    for frame in read_frames(csv_path):
        t = quantize_time(frame.t)
        body = unary_union(link_polygons(frame.proprio(), world.limits))
        human = world.human_polygon(frame.human_pos)
        distance = float(body.distance(human))
        timeline.append((t, distance))
        if body.intersects(human):
            contact = True
        if best_raw is None or distance < best_raw:
            best_raw = distance

    if not timeline:
        raise BenchError(
            f"{csv_path} yielded no frames, so there is no ground truth to check "
            "any resolution level against. An empty stream is a step of the "
            "pipeline that did not run, not a run in which nothing happened."
        )
    # Every frame the artifact could not tell apart from the minimum. One quantum
    # wide because that is the resolution distances are retained at; making it
    # narrower would ask the artifact a question docs/lossiness.md says it cannot
    # answer, and making it wider would stop the check being able to fail.
    candidates = tuple(
        t for t, distance in timeline if distance - best_raw <= DISTANCE_TOL_M
    )
    if not candidates:  # pragma: no cover - the minimum is within zero of itself
        raise BenchError(
            "no frame is within DISTANCE_TOL_M of the run's own minimum "
            "separation, which is arithmetically impossible."
        )
    return GroundTruth(
        min_separation=best_raw,
        t_closest_approach=candidates[0],
        closest_approach_candidates=candidates,
        timeline=tuple(timeline),
        contact_occurred=contact,
    )


#: Which layer each resolution level is a view *of*. `transition` and
#: `per-frame` are two densities of the edge layer and answer identically; the
#: occurrence level is the other layer. Used to check a view is what it claims
#: to be, below.
_LEVEL_LAYER: dict[str, str] = {
    OCCURRENCE_LEVEL: OCCURRENCE_LAYER,
    TRANSITION_LEVEL: EDGE_LAYER,
    PER_FRAME_LEVEL: EDGE_LAYER,
}


def _answer_value(answer) -> object | None:
    """An `Answer`'s value, or `None` where it refused.

    `None` is the refusal travelling into `LevelAnswers`, which reads it the
    same way: not a zero, not a `False`, not an empty timeline.
    """
    return answer.value if answer.answered else None


def answers_at_level(
    view_path: str | Path, level: str, entity_id: str = graph.HUMAN_ENTITY_ID
) -> LevelAnswers:
    """What one level's view can answer — asked through `reg.query`.

    **This function no longer knows how to answer anything** (issue #37). It
    opens the view, checks the view really is the level it claims to be, and
    puts the four questions to `reg.query`, which is the module that cannot read
    the raw stream. The benchmark used to hold its own copies of these queries,
    and two implementations of one question is two answers to it — with the
    graph-versus-CSV comparison in this file silently checking one of them.

    The layer separation that makes the measurement honest is now *structural*
    rather than a branch here: `materialize_level` empties the table the level
    does not retain, `reg.query.available_layers` reads what is actually in the
    file, and each query refuses when its layer is absent. A level allowed to
    fall back on the finer layer would report the finer layer's answers at the
    coarser layer's byte count — so the fallback is checked for, and a view
    still holding a foreign layer is a `BenchError` rather than a good number.
    """
    if level not in RESOLUTION_LEVELS:
        raise BenchError(
            f"{level!r} is not a resolution level. Known levels: "
            f"{list(RESOLUTION_LEVELS)}."
        )
    entity_id = str(entity_id)
    conn = store.connect(view_path)
    try:
        foreign = available_layers(conn) - {_LEVEL_LAYER[level]}
        if foreign:
            raise BenchError(
                f"the {level} view still holds rows in the "
                f"{', '.join(sorted(foreign))} layer, which that level does not "
                "retain. Its answers would come from a layer its byte count "
                "does not pay for, and the curve would be flat for a reason "
                "that has nothing to do with resolution."
            )
        return _asking(
            conn,
            f"the {level} level",
            lambda c: LevelAnswers(
                min_separation=_answer_value(min_separation(c, entity_id)),
                t_closest_approach=_answer_value(
                    time_of_closest_approach(c, entity_id)
                ),
                timeline=_timeline_of(separation_timeline(c, entity_id)),
                contact_occurred=_answer_value(did_contact_occur(c, entity_id)),
            ),
        )
    finally:
        conn.close()


def _timeline_of(answer) -> tuple[tuple[float, float], ...] | None:
    """The `(t, distance)` samples out of a `separation_timeline` answer.

    `None` where the query refused — which at the occurrence level it always
    does, because that layer holds events and not states, and the intervals
    between them are exactly what it discarded. That refusal is now the query
    layer's and every caller gets it, which is what issue #37 moved.
    """
    value = _answer_value(answer)
    return None if value is None else value.samples  # type: ignore[union-attr]


def check_level(
    query: ResolutionQuery, answers: LevelAnswers, truth: GroundTruth
) -> LevelCheck:
    """One query, at one level, against ground truth. Three outcomes.

    Every path through here can return `DISAGREE`, and the one that cannot
    answer returns `COULD-NOT-EVALUATE` — never `AGREE` on the strength of an
    absent answer. `tests/test_bench.py` feeds each of them the condition it
    guards against.
    """
    if query.name == "min_separation":
        return _scalar_check(
            query, answers.min_separation, truth.min_separation, "m"
        )
    if query.name == "time_of_closest_approach":
        return _closest_approach_time_check(query, answers.t_closest_approach, truth)
    if query.name == "separation_timeline":
        return _timeline_check(query, answers.timeline, truth)
    if query.name == "did_contact_occur":
        return _boolean_check(query, answers.contact_occurred, truth)
    raise BenchError(  # pragma: no cover - RESOLUTION_QUERIES is the only source
        f"{query.name!r} has no implementation. A query in the table with no way "
        "to answer it would print as could-not-evaluate at every level, which "
        "reads as a finding about resolution and is a missing function."
    )


def _scalar_check(
    query: ResolutionQuery,
    level_answer: float | None,
    truth_answer: float | None,
    unit: str,
) -> LevelCheck:
    tolerance = query.tolerance
    if tolerance is None:  # pragma: no cover - both scalar queries have one
        raise BenchError(f"{query.name} is compared numerically and states no tolerance.")
    verdict = agreement(level_answer, truth_answer, tolerance)
    if verdict == COULD_NOT_EVALUATE:
        which = "the level" if level_answer is None else "ground truth"
        return LevelCheck(
            query=query.name,
            verdict=verdict,
            detail=f"{which} returned no answer",
        )
    difference = abs(float(level_answer) - float(truth_answer))  # type: ignore[arg-type]
    return LevelCheck(
        query=query.name,
        verdict=verdict,
        detail=(
            f"{float(level_answer):.4f} {unit} vs {float(truth_answer):.4f} "
            f"{unit}, Δ {difference:.4f} {unit} (tol {tolerance} {unit})"
        ),
    )


def _closest_approach_time_check(
    query: ResolutionQuery, level_answer: float | None, truth: GroundTruth
) -> LevelCheck:
    """"When was the closest approach" against the set of frames that qualify.

    Agreement is `|t_level - t| <= TIME_TOL_S` for **some** candidate frame, and
    the reported delta is the distance to the nearest one. See `GroundTruth`:
    the set, not a single argmin, is what the lossiness contract leaves as the
    answer, and the tolerance in force is still `TIME_TOL_S`.
    """
    if level_answer is None:
        return LevelCheck(
            query=query.name,
            verdict=COULD_NOT_EVALUATE,
            detail="this level records no closest approach",
        )
    tolerance = float(query.tolerance)  # type: ignore[arg-type]
    nearest = min(
        truth.closest_approach_candidates, key=lambda t: abs(level_answer - t)
    )
    difference = abs(float(level_answer) - nearest)
    return LevelCheck(
        query=query.name,
        verdict=AGREE if difference <= tolerance else DISAGREE,
        detail=(
            f"{float(level_answer):.4f} s against "
            f"{len(truth.closest_approach_candidates):,} frame(s) within "
            f"{DISTANCE_TOL_M} m of the minimum, nearest at {nearest:.4f} s, "
            f"Δ {difference:.4f} s (tol {tolerance} s)"
        ),
    )


def _timeline_check(
    query: ResolutionQuery,
    timeline: tuple[tuple[float, float], ...] | None,
    truth: GroundTruth,
) -> LevelCheck:
    if timeline is None:
        return LevelCheck(
            query=query.name,
            verdict=COULD_NOT_EVALUATE,
            detail="this level holds no per-frame separation",
        )
    if len(timeline) != truth.frames:
        return LevelCheck(
            query=query.name,
            verdict=COULD_NOT_EVALUATE,
            detail=(
                f"{len(timeline)} frames answered against {truth.frames} in the "
                "stream; a partial timeline is not a timeline"
            ),
        )
    tolerance = float(query.tolerance)  # type: ignore[arg-type]
    worst = 0.0
    worst_t = None
    for (t_level, d_level), (t_truth, d_truth) in zip(timeline, truth.timeline):
        if abs(t_level - t_truth) > TIME_TOL_S:
            return LevelCheck(
                query=query.name,
                verdict=DISAGREE,
                detail=(
                    f"the level answers for t={t_level} where the stream has "
                    f"t={t_truth}"
                ),
            )
        difference = abs(d_level - d_truth)
        if difference > worst:
            worst, worst_t = difference, t_truth
    verdict = AGREE if worst <= tolerance else DISAGREE
    where = "" if worst_t is None else f" at t={worst_t}"
    return LevelCheck(
        query=query.name,
        verdict=verdict,
        detail=(
            f"worst frame Δ {worst:.4f} m{where} over {truth.frames:,} frames "
            f"(tol {tolerance} m)"
        ),
    )


def _boolean_check(
    query: ResolutionQuery, level_answer: bool | None, truth: GroundTruth
) -> LevelCheck:
    if level_answer is None:
        return LevelCheck(
            query=query.name,
            verdict=COULD_NOT_EVALUATE,
            detail="this level does not state whether it would have recorded one",
        )
    verdict = AGREE if bool(level_answer) == truth.contact_occurred else DISAGREE
    vacuous = (
        " — and neither did the run, so this is agreement on a negative"
        if not truth.contact_occurred
        else ""
    )
    return LevelCheck(
        query=query.name,
        verdict=verdict,
        detail=(
            f"level says {bool(level_answer)}, stream says "
            f"{truth.contact_occurred}{vacuous}"
        ),
    )


def _level_counts(view_path: Path) -> tuple[int, int, int]:
    """`(nodes, edges, occurrences)` in one view. Occurrences counted twice on
    purpose — once inside the node total, once on their own — because the whole
    table exists to compare a layer of occurrences against a layer of edges."""
    conn = store.connect(view_path)
    try:
        # `store.node_counts` and not a `SELECT count(*)` per table: a view of a
        # build handed no record stream has no `declaration` or `verdict` table
        # to count (issue #54). The numbers are the same ones.
        counts = store.node_counts(conn)
        nodes = sum(counts.values())
        occurrences = counts["Occurrence"]
        edges = int(
            conn.execute("SELECT count(*) AS n FROM edge").fetchone()["n"]
        )
    finally:
        conn.close()
    return nodes, edges, occurrences


def run_resolution_curve(
    frames: int,
    work_dir: str | Path,
    *,
    seed: int,
    horizon: float,
    n_samples: int,
    envelope_seed: int,
    substep_dt: float,
    occurrence_resolution_s: float,
    timing_repeats: int = TIMING_REPEATS,
) -> ResolutionCurve:
    """Build the long-run fixture once and measure all three views of it.

    **One build.** The simulator runs once, `reg.graph.build` runs once, and the
    three points are projections of that one artifact — issue #35's runtime note
    is a correctness requirement as much as a cost one: three builds would differ
    in more than resolution, and the curve would not be about resolution.

    Args:
        frames: the run length. `RESOLUTION_FRAME_COUNT` is what the CLI passes.
        work_dir: where the stream, the artifact and the three views go.
        occurrence_resolution_s: what the occurrence timestamps are rounded to.
            This is the variable the curve exists to price.

    Returns:
        A `ResolutionCurve`, coarsest point first.
    """
    scn = long_run(frames)
    result = _measure(
        scn,
        work_dir,
        seed=seed,
        horizon=horizon,
        n_samples=n_samples,
        envelope_seed=envelope_seed,
        substep_dt=substep_dt,
        occurrence_resolution_s=occurrence_resolution_s,
        timing_repeats=timing_repeats,
    )
    csv_path, sqlite_path = _work_paths(scn, work_dir)
    truth = ground_truth_from_csv(csv_path, scn.world)

    points: list[ResolutionPoint] = []
    for level in RESOLUTION_LEVELS:
        view = materialize_level(
            sqlite_path, level, Path(work_dir) / "views" / f"{level}.sqlite"
        )
        nodes, edges, occurrences = _level_counts(view)
        answers = answers_at_level(view, level)
        points.append(
            ResolutionPoint(
                level=level,
                timestamp_resolution_s=(
                    float(occurrence_resolution_s)
                    if level == OCCURRENCE_LEVEL
                    else TIME_TOL_S
                ),
                size_bytes=view.stat().st_size,
                nodes=nodes,
                edges=edges,
                occurrences=occurrences,
                run_seconds=(result.frames - 1) * float(scn.dt),
                checks=tuple(
                    check_level(query, answers, truth)
                    for query in RESOLUTION_QUERIES
                ),
            )
        )

    return ResolutionCurve(
        scenario=scn.name,
        frames=result.frames,
        frame_period_s=scn.dt,
        n_samples=int(n_samples),
        occurrence_resolution_s=float(occurrence_resolution_s),
        source=result,
        truth=truth,
        points=tuple(points),
    )


# --------------------------------------------------------------------------
# The report. `render` is pure: results in, markdown out. Nothing that varies
# between two runs of the same command may be added to it -- no path, no clock,
# no hostname (`reg.sim`, rule 2). The wall-clock table is the one exception and
# it is labelled as such where it appears, not only here.
# --------------------------------------------------------------------------


def _int_text(value: int) -> str:
    return f"{int(value):,}"


def _ratio_text(value: float) -> str:
    """A ratio at three significant figures, so two scenarios read comparably."""
    if value >= 100.0:
        return f"{value:,.0f}x"
    if value >= 10.0:
        return f"{value:.1f}x"
    return f"{value:.2f}x"


def _seconds_text(value: float) -> str:
    if value >= 1.0:
        return f"{value:.3f} s"
    if value >= 1e-3:
        return f"{value * 1e3:.3f} ms"
    return f"{value * 1e6:.1f} us"


def _metres_text(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.4f} m"


def _repeats_text(results: Sequence[ScenarioResult]) -> str:
    """How many timed repeats produced these figures — read off the results.

    Off the results rather than off `TIMING_REPEATS`, because `run_scenario`
    takes the count as an argument: printing the module constant would state a
    protocol the numbers in the table were not measured under, which is the
    same failure as printing an invented parameter.
    """
    counts = {r.check.graph_timing.repeats for r in results} | {
        r.check.csv_timing.repeats for r in results
    }
    if not counts:
        return "n/a — nothing in this report was timed"
    return str(sorted(counts)[0]) if len(counts) == 1 else "varies per row"


def _table(header: Sequence[str], rows: Sequence[Sequence[str]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |"]
    lines.append("|" + "|".join("---" for _ in header) + "|")
    for row in rows:
        if len(row) != len(header):
            raise BenchError(
                f"table row has {len(row)} cells for {len(header)} columns: "
                f"{row!r}. A short row shifts every value into the wrong column."
            )
        lines.append("| " + " | ".join(row) + " |")
    return lines


def _bytes_per_frame_text(total: int, frames: int) -> str:
    return f"{int(total) / int(frames):,.1f}"


def _marginal_ratio_text(baseline_delta: int, artifact_delta: int) -> str:
    """`Δ baseline / Δ artifact` between two measured lengths, or `n/a`.

    Arithmetic on two measured points, and *not* an extrapolation: it says what
    each additional frame cost over an interval that was actually run. A
    non-positive artifact delta is reported as `n/a` rather than as an enormous
    ratio — an artifact that did not grow over an interval is a fact about that
    interval, and dividing by it would manufacture a headline.
    """
    try:
        return _ratio_text(compression_ratio(baseline_delta, artifact_delta))
    except BenchError:
        return "n/a"


def _scaling_section(
    scaling: Sequence[ScalingPoint],
    control: ScalingPoint | None,
    *,
    n_samples: int,
) -> list[str]:
    """The ratio-versus-run-length half of Claim 1 (issue #30).

    Measured points only. Every derived column here is arithmetic between two
    lengths that were actually executed; no curve is fitted, and the crossover
    is quoted only if a measured length reached it.
    """
    ladder = sorted(scaling, key=lambda p: p.frames)
    ladder_samples = {p.n_samples for p in ladder}
    crossing = crossover(ladder)

    lines = [
        "",
        "## Ratio versus run length",
        "",
        "Claim 1 is a claim about **scaling**, and the six hand-authored",
        "scenarios are five or six seconds each — the one length at which it",
        "cannot be tested, because a near-constant schema-and-index cost",
        "dominates the artifact there. This",
        "table is the same measurement at a ladder of run lengths, on one",
        "generated fixture (`reg.scenarios.long_run`): an arm working a repeating",
        "cycle while a person patrols in and out, with every cycle drifting",
        "slightly so that no two frames of the run are identical. A fixture that",
        "repeated a short loop exactly would compress on both sides in a way no",
        "real run does.",
        "",
        "**Measured points only.** Nothing below is extrapolated: the marginal",
        "columns are differences between two lengths that were both executed, and",
        "if the ratio does not reach 1.0 in the range run, this section says so",
        "rather than projecting where it would.",
        "",
    ]

    lines += _table(
        ("parameter", "value", "why"),
        [
            (
                "fixture",
                "`reg.scenarios.long_run(frames)`",
                "one scenario at every length, so only the length varies",
            ),
            (
                "lengths",
                ", ".join(_int_text(p.frames) for p in ladder),
                "the ladder actually executed",
            ),
            (
                "envelope samples",
                (
                    _int_text(sorted(ladder_samples)[0])
                    if len(ladder_samples) == 1
                    else "varies per row — see the column"
                ),
                (
                    "compute cost, and which frames count as overlapping. Since "
                    "issue #28 the polygon is not stored, so it moves no byte "
                    "count here — but a tighter envelope removes overlaps, which "
                    "*flatters* the ratio. The control row below measures that."
                ),
            ),
        ],
    )

    lines += ["", "### Sizes and ratios by run length", ""]
    lines += _table(
        (
            "frames",
            "robot time",
            "raw CSV B",
            "gz CSV B",
            "SQLite B",
            "gz SQLite B",
            "nodes",
            "edges",
            "edges/frame",
            "x raw",
            "x gz CSV",
            "verdict",
        ),
        [
            (
                _int_text(p.frames),
                f"{p.seconds:,.1f} s",
                _int_text(p.sizes.raw_csv),
                _int_text(p.sizes.gzip_csv),
                _int_text(p.sizes.sqlite),
                _int_text(p.sizes.gzip_sqlite),
                _int_text(p.result.total_nodes),
                _int_text(p.result.total_edges),
                f"{p.result.total_edges / p.frames:.3f}",
                _ratio_text(p.sizes.ratio_vs_raw),
                f"**{_ratio_text(p.ratio)}**",
                p.result.check.verdict,
            )
            for p in ladder
        ],
    )

    lines += [
        "",
        "### What each additional frame cost",
        "",
        "The per-frame columns are the totals above divided by the frame count.",
        "The `Δ` columns are the difference between one measured length and the",
        "one before it, divided by the difference in frames: what the frames in",
        "*that interval* cost, with the fixed schema-and-index cost differenced",
        "away. `Δ x` is the marginal ratio — above 1.0 means the artifact grew",
        "more slowly than the gzipped baseline over that interval, so the overall",
        "ratio was still climbing there. **It is a rate between two measured",
        "points, not a projection of where the ratio crosses 1.0.**",
        "",
    ]
    marginal_rows = []
    previous: ScalingPoint | None = None
    for point in ladder:
        if previous is None:
            deltas = ("n/a", "n/a", "n/a")
        else:
            d_frames = point.frames - previous.frames
            d_gz = point.sizes.gzip_csv - previous.sizes.gzip_csv
            d_sqlite = point.sizes.sqlite - previous.sizes.sqlite
            deltas = (
                _bytes_per_frame_text(d_gz, d_frames),
                _bytes_per_frame_text(d_sqlite, d_frames),
                _marginal_ratio_text(d_gz, d_sqlite),
            )
        marginal_rows.append(
            (
                _int_text(point.frames),
                _bytes_per_frame_text(point.sizes.gzip_csv, point.frames),
                _bytes_per_frame_text(point.sizes.sqlite, point.frames),
                *deltas,
            )
        )
        previous = point
    lines += _table(
        (
            "frames",
            "gz CSV B/frame",
            "SQLite B/frame",
            "Δ gz CSV B/frame",
            "Δ SQLite B/frame",
            "Δ x",
        ),
        marginal_rows,
    )

    largest = ladder[-1]
    lines += [
        "",
        "### Where the bytes went at the longest measured run",
        "",
        f"Bytes per table at {_int_text(largest.frames)} frames, from SQLite's own",
        "`dbstat`. The same attribution the per-scenario table gets, at the length",
        "where it decides the answer: if one table grows with the frame count, the",
        "ratio cannot climb past what that table costs per frame, whatever happens",
        "to the fixed cost.",
        "",
    ]
    if largest.result.tables is None:
        lines += [
            "**Could not be attributed.** This SQLite build has no `dbstat` "
            "virtual table. That is a could-not-evaluate; no estimate is "
            "substituted for it.",
        ]
    else:
        labels = (*_TABLE_LABELS, INDEX_LABEL)
        lines += _table(
            ("frames", *labels, "file"),
            [
                (
                    _int_text(largest.frames),
                    *[_int_text(largest.result.tables.get(label, 0)) for label in labels],
                    _int_text(largest.sizes.sqlite),
                )
            ],
        )

    lines += ["", "### Crossover", ""]
    if crossing.crossed_at is None:
        lines += [
            "**The ratio does not reach 1.0 at any measured length.** The largest",
            f"run executed is {_int_text(crossing.largest_measured)} frames "
            f"({largest.seconds:,.1f} s of robot time), and the headline ratio",
            f"there is {_ratio_text(largest.ratio)} — the evidence graph still",
            "costs more bytes to retain than a gzipped copy of the stream it",
            "replaced.",
            "",
            "No crossover is projected, and none should be read into the table.",
            "The measured points end where they end; a length fitted from them is",
            "a number nobody ran.",
            "",
            "**This is a finding about the thesis, not a gap in the measurement.**",
            "`docs/plan.md` states Claim 1's success criterion as 2–4 orders of",
            f"magnitude, i.e. at least {_ratio_text(CLAIM_1_SUCCESS_RATIO)}; the",
            "best ratio at any length measured here is "
            f"{_ratio_text(max(p.ratio for p in ladder))}, and it does not reach",
            "1.0. If that holds, the retainable-artifact argument rests on Claims 2–4 — query,",
            "sufficiency boundary, attestation — which do not depend on the",
            "artifact being smaller than the stream. It rests on compression only",
            "at a run length nothing in this repository has measured.",
        ]
    elif crossing.crossed_at == crossing.smallest_measured:
        lines += [
            f"**The ratio passes 1.0 at {_int_text(crossing.crossed_at)} frames**,",
            "which is the *shortest* length measured. Nothing here bounds the",
            "crossing from below: this ladder does not contain a length at which",
            "the artifact was larger than the stream, so where the ratio crosses",
            "is outside the range run, and no value for it is quoted.",
        ]
    else:
        lines += [
            f"**The ratio passes 1.0 at {_int_text(crossing.crossed_at)} frames**,",
            "the smallest measured length at which it does. At every shorter",
            "measured length it is below 1.0 — the artifact is larger than the",
            "gzipped stream it replaced. Where between",
            f"{_int_text(crossing.smallest_measured)} and "
            f"{_int_text(crossing.crossed_at)} frames the crossing actually",
            "happens is not measured, and is not interpolated here.",
        ]

    if crossing.fell_back_below:
        lines += [
            "",
            "**The ratio is not monotone in run length.** It falls back below",
            "1.0 at "
            + ", ".join(f"{_int_text(f)} frames" for f in crossing.fell_back_below)
            + ". A single crossover is the wrong shape of answer for this "
            "table; read the column.",
        ]

    if control is not None:
        lines += [
            "",
            "### Control: what the reduced sample count cost",
            "",
            f"The shortest ladder length re-measured at **{_int_text(control.n_samples)}**",
            "envelope samples — the value the per-scenario table above uses — against",
            "the ladder's own value. The envelope is an under-approximation that grows",
            "monotonically with `n_samples` (`reg.envelope`), so the cheaper setting can",
            "only *remove* overlaps: fewer INTERSECTS rows, fewer retained envelope rows,",
            "a smaller artifact and a **larger** ratio. This row is how much larger, at",
            "one length, measured rather than argued.",
            "",
        ]
        matching = [p for p in ladder if p.frames == control.frames]
        rows = [
            (
                _int_text(p.frames),
                _int_text(p.n_samples),
                _int_text(p.sizes.sqlite),
                _int_text(p.result.total_nodes),
                _int_text(p.result.total_edges),
                f"**{_ratio_text(p.ratio)}**",
            )
            for p in (*matching, control)
        ]
        lines += _table(
            ("frames", "envelope samples", "SQLite B", "nodes", "edges", "x gz CSV"),
            rows,
        )
        if matching:
            base = matching[0]
            delta_bytes = control.sizes.sqlite - base.sizes.sqlite
            delta_edges = control.result.total_edges - base.result.total_edges
            delta_nodes = control.result.total_nodes - base.result.total_nodes
            lines += [
                "",
                f"**Measured difference at {_int_text(base.frames)} frames:** "
                f"{delta_bytes:+,} bytes "
                f"({100.0 * delta_bytes / base.sizes.sqlite:+.1f}%), "
                f"{delta_edges:+,} edges, {delta_nodes:+,} nodes at the higher "
                "sample count. Zero is a measurement like any other: at this "
                "length the tighter envelope removed no overlap the artifact "
                "would otherwise have recorded. It says nothing about the longer "
                "rungs, which were not measured twice — that is what it would "
                "have cost to measure them.",
            ]
    else:
        lines += [
            "",
            "### Control: what the reduced sample count cost",
            "",
            "**Not measured in this run.** The ladder ran at the same `n_samples`",
            f"as the per-scenario table ({_int_text(n_samples)}), so there is no",
            "reduction to control for. When the two differ, this section carries",
            "the shortest ladder length measured at both.",
        ]

    lines += [
        "",
        "### What this table is not",
        "",
        f"* **Not a shift.** The largest run here is {largest.seconds:,.1f} s of",
        "  robot time at 50 Hz. docs/plan.md's terabytes/day is four orders of",
        "  magnitude further out and no row here reaches toward it.",
        "* **Not six scenarios.** One fixture, chosen so that only the length",
        "  varies. A different fixture — a robot that holds still, or one that",
        "  never comes near a person — would produce a different curve, and the",
        "  incremental rule's whole behaviour is a function of how often",
        "  relationships change.",
        "* **Not a claim that the curve continues.** Every row was executed.",
    ]
    return lines


def _bytes_per_hour_text(value: float) -> str:
    """Bytes/hour at the magnitude a retention policy is written in."""
    if value >= 1e9:
        return f"{value / 1e9:,.2f} GB/h"
    if value >= 1e6:
        return f"{value / 1e6:,.2f} MB/h"
    if value >= 1e3:
        return f"{value / 1e3:,.1f} kB/h"
    return f"{value:,.0f} B/h"


def _resolution_section(curve: ResolutionCurve) -> list[str]:
    """What evidence costs per unit of resolution (issue #35).

    **No ratio against the CSV appears in this section.** docs/plan.md Claim 1
    forbids quoting one while the measured ratio is below 1, and the figure that
    replaced it is absolute: bytes/hour, beside the column that decides whether
    the bytes bought anything — whether the questions still get the right answer.
    """
    points = list(curve.points)
    if not points:
        raise BenchError(
            "the resolution curve has no points. An empty curve would read as "
            "'no resolution level answered anything', which is a finding, and "
            "this is the absence of a measurement."
        )

    lines = [
        "",
        "## What resolution costs",
        "",
        "**This is Claim 1 as it stands after issue #30.** The original question —",
        "is the graph smaller than the stream — was measured and answered, no. The",
        "question here is the one worth asking instead: *what does evidence cost",
        "per unit of resolution, and how coarse can it get before it stops",
        "answering the question?*",
        "",
        "The coarsest level is not invented. UN R157's **DSSAD** is the only",
        "mandated evidence recorder for autonomy that exists, and it stores",
        "**occurrences**: a flag, a reason, a date, a timestamp accurate to",
        "**±1.0 s**, and the software version present at the event",
        "(`docs/prior-art.md` §9). `reg` stores relationships at cm / 10 ms, every",
        "frame — two orders of magnitude finer than the only comparable thing",
        "actually required by law.",
        "",
        "**Three views of one build.** The simulator ran once and the graph was",
        "built once; each row below is that artifact with everything the level",
        "does not retain removed, then vacuumed. Nothing here is a second build,",
        "because a curve whose points differed in the run or the parameters would",
        "be measuring those instead of resolution.",
        "",
    ]

    lines += _table(
        ("parameter", "value", "why"),
        [
            (
                "fixture",
                f"`reg.scenarios.{curve.scenario}`",
                "one run, three views of it",
            ),
            (
                "length",
                f"{_int_text(curve.frames)} frames, {curve.run_seconds:,.1f} s of "
                "robot time",
                "one moderate length. `--scaling` is where length is the "
                "variable; here it is held still so resolution can be",
            ),
            (
                "envelope samples",
                _int_text(curve.n_samples),
                "compute cost and which frames count as overlapping; since issue "
                "#28 it moves no byte count",
            ),
            (
                "occurrence resolution",
                f"{curve.occurrence_resolution_s} s",
                "the variable this table prices. DSSAD's stated accuracy is "
                "±1.0 s; `--occurrence-resolution` moves it",
            ),
            (
                "edge-layer resolution",
                f"{TIME_TOL_S} s",
                "`TIME_TOL_S`, and **not** a parameter. Widening it would change "
                "what the artifact claims rather than what it costs",
            ),
        ],
    )

    lines += ["", "### The curve", ""]
    query_names = [q.name for q in RESOLUTION_QUERIES]
    lines += _table(
        (
            "level",
            "timestamp resolution",
            "SQLite B",
            "bytes/hour",
            "nodes",
            "edges",
            "occurrences",
            *query_names,
            "all queries",
        ),
        [
            (
                f"`{p.level}`",
                f"{p.timestamp_resolution_s} s",
                _int_text(p.size_bytes),
                f"**{_bytes_per_hour_text(p.bytes_per_hour)}**",
                _int_text(p.nodes),
                _int_text(p.edges),
                _int_text(p.occurrences),
                *[
                    next(
                        (c.verdict for c in p.checks if c.query == name),
                        COULD_NOT_EVALUATE,
                    )
                    for name in query_names
                ],
                p.verdict,
            )
            for p in points
        ],
    )

    lines += [
        "",
        "`bytes/hour` is the retention figure, and it is what this table quotes",
        "instead of a compression ratio: `docs/plan.md` Claim 1 forbids a ratio",
        "against the stream while the measured one is below 1. It is the file",
        f"size over {curve.run_seconds:,.1f} s of robot time, scaled to an hour,",
        "which scales the artifact's *fixed* schema-and-index cost by the same",
        "factor as its per-frame cost — so at this run length it **overstates**",
        "the hourly rate, and by more for the smaller levels, where the fixed",
        "cost is most of the file.",
        "",
        "`COULD-NOT-EVALUATE` never resolves to `AGREE`: a level that cannot",
        "answer a question has not agreed with it. A level that is small and",
        "answers correctly is the result; a level that is small and answers",
        "wrongly is not a smaller artifact, it is a broken one.",
        "",
        "### What each level answered, and by how much it missed",
        "",
    ]

    detail_rows = []
    for query in RESOLUTION_QUERIES:
        for point in points:
            check = next(
                (c for c in point.checks if c.query == query.name), None
            )
            if check is None:  # pragma: no cover - every point checks every query
                continue
            detail_rows.append(
                (
                    f"`{query.name}`",
                    f"`{point.level}`",
                    check.verdict,
                    check.detail,
                )
            )
    lines += _table(("query", "level", "verdict", "answers"), detail_rows)

    lines += ["", "The questions, and the predicate each is judged under:", ""]
    lines += _table(
        ("query", "question", "agreement predicate"),
        [
            (f"`{q.name}`", q.question, f"`{q.predicate}`")
            for q in RESOLUTION_QUERIES
        ],
    )

    lines += [
        "",
        "Ground truth for all four is recomputed from the raw CSV by forward",
        "kinematics, exactly as the cross-check in *Query wall-clock* is. The",
        "envelope queries of `docs/lossiness.md`'s set (2 and 4) are **not** here:",
        "their only available ground truth would be recomputing an envelope per",
        "frame with `reg.envelope`, which is the builder's own computation, and a",
        "check whose ground truth reruns the code under test cannot fail.",
        "Queries 5–8 are declarations, verdicts and the chain — Milestone 3, no",
        "fixture, and asking them here would print `COULD-NOT-EVALUATE` at every",
        "level for a reason that has nothing to do with resolution.",
        "",
        "### What this table is not",
        "",
        "* **Not a claim that the per-frame row is what per-frame costs.** That",
        "  view expands the retained intervals to one row per frame; it does not",
        "  restore the per-frame `robot_config` and `envelope` rows issue #29",
        "  removed, because they were discarded at build time and nothing here can",
        "  recover them. It is a **lower bound**, and the direction matters: it",
        "  understates what the fine layer costs, which makes the coarse levels",
        "  look *less* good rather than more.",
        "* **Not a licence to delete the fine layer.** The occurrence layer is",
        "  additive. All three points are needed for there to be a curve at all,",
        "  and a single coarse artifact is not a measurement.",
        "* **Not an hour.** See the note under the table.",
    ]
    if not curve.truth.contact_occurred:
        lines += [
            "* **Not a strong check of `did_contact_occur`.** This run contains no",
            "  contact, so every level agreeing means every level agreed on a",
            "  negative. `tests/test_bench.py` is where that check is shown able to",
            "  fail, on a fixture that does contact and on a perturbed artifact.",
        ]
    return lines


def render(
    results: Sequence[ScenarioResult],
    *,
    seed: int,
    horizon: float,
    n_samples: int,
    envelope_seed: int,
    substep_dt: float,
    occurrence_resolution_s: float,
    sensor_multiplier: float | None,
    scaling: Sequence[ScalingPoint] = (),
    scaling_control: ScalingPoint | None = None,
    resolution: ResolutionCurve | None = None,
) -> str:
    """The whole report as markdown. Pure — same results in, same string out.

    `scaling` is the ladder of run lengths (issue #30) and may be empty, in
    which case the report carries no scaling section at all rather than an empty
    one. `scaling_control` is the shortest ladder length re-measured at a
    different `n_samples`; it is reported beside the ladder and never mixed into
    it. `resolution` is the curve over resolution levels (issue #35) and is
    likewise absent rather than empty when it was not run.
    """
    if not results and not scaling and resolution is None:
        raise BenchError(
            "no scenarios were benchmarked, so there is no table to write. An "
            "empty report reads as 'the graph compresses nothing measured', "
            "which is not what happened."
        )

    timed = [*results, *[p.result for p in scaling]]
    if scaling_control is not None:
        timed.append(scaling_control.result)
    if resolution is not None:
        timed.append(resolution.source)

    lines: list[str] = [
        "# Compression benchmark — Claim 1",
        "",
        "Generated by `python -m reg.bench`. `bench/results.md` is gitignored: it",
        "is regenerated from the seeds below, and a committed copy would make the",
        "numbers look like fixtures.",
        "",
        "**What is measured:** the size of the SQLite evidence graph against the",
        "size of the raw simulator state stream it was built from, per scenario",
        "and — since issue #30 — as a function of run length.",
        "**What is not measured: anything about a real robot.** The terabytes/day",
        "figure in `docs/plan.md` is imported context about production humanoid",
        "sensor logs; nothing in this simulator produces or measures it, and no",
        "row below is evidence for it.",
        "",
        "## Run parameters",
        "",
    ]
    # The per-scenario table's `n_samples` is stated only if something in this
    # report was measured at it. A report with only a scaling ladder in it is
    # measured at the ladder's own value, and printing the other one in the
    # header would state a parameter no number here was produced under.
    samples_text = (
        _int_text(n_samples)
        if results or scaling_control is not None
        else "n/a — no table in this report was measured at it"
    )
    occurrence_text = (
        f"{float(occurrence_resolution_s)} s"
        if resolution is None
        else f"{float(resolution.occurrence_resolution_s)} s"
    )
    lines += _table(
        ("parameter", "value", "what it changes"),
        [
            ("`reg` version", __version__, "everything"),
            ("simulator seed", str(int(seed)), "waypoint perturbation, all sizes"),
            ("envelope seed", str(int(envelope_seed)), "interior control samples"),
            ("envelope horizon", f"{float(horizon)} s", "envelope size, overlap rows"),
            ("envelope samples", samples_text, "envelope tightness"),
            ("envelope substep", f"{float(substep_dt)} s", "envelope tightness"),
            (
                "occurrence resolution",
                occurrence_text,
                "occurrence timestamps only — the edge layer is at TIME_TOL_S",
            ),
            (
                "raw float precision",
                str(FLOAT_PRECISION),
                "raw CSV bytes — the denominator",
            ),
            (
                "graph schema version",
                str(store.SCHEMA_VERSION),
                "SQLite bytes — the numerator",
            ),
            ("gzip level", str(GZIP_COMPRESSLEVEL), "the gzipped baseline"),
            (
                "timing repeats",
                _repeats_text(timed),
                "precision of the wall-clock table only",
            ),
        ],
    )

    if resolution is not None:
        lines += _resolution_section(resolution)

    if scaling:
        lines += _scaling_section(scaling, scaling_control, n_samples=n_samples)

    if not results:
        return "\n".join(lines + _caveats()) + "\n"

    lines += [
        "",
        "## Sizes and ratios",
        "",
        "`x gz CSV` is **the headline**: the gzipped CSV baseline divided by the",
        f"SQLite artifact as it sits on disk. gzip runs at level"
        f" {GZIP_COMPRESSLEVEL} — the",
        "strongest setting, i.e. the one most favourable to the baseline — and the",
        "artifact gets no such benefit, so this is the smallest of the three",
        "ratios and the one to quote. `x gz/gz` compresses both sides and is",
        "reported only so the like-for-like comparison is visible too.",
        "",
    ]

    rows = []
    for r in results:
        rows.append(
            (
                f"`{r.scenario}`",
                _int_text(r.frames),
                _int_text(r.total_nodes),
                _int_text(r.total_edges),
                _int_text(r.sizes.raw_csv),
                _int_text(r.sizes.gzip_csv),
                _int_text(r.sizes.sqlite),
                _int_text(r.sizes.gzip_sqlite),
                _ratio_text(r.sizes.ratio_vs_raw),
                f"**{_ratio_text(r.sizes.ratio_vs_gzip_csv)}**",
                _ratio_text(r.sizes.ratio_like_for_like),
            )
        )

    totals = Sizes(
        raw_csv=sum(r.sizes.raw_csv for r in results),
        gzip_csv=sum(r.sizes.gzip_csv for r in results),
        sqlite=sum(r.sizes.sqlite for r in results),
        gzip_sqlite=sum(r.sizes.gzip_sqlite for r in results),
    )
    rows.append(
        (
            "**all scenarios**",
            _int_text(sum(r.frames for r in results)),
            _int_text(sum(r.total_nodes for r in results)),
            _int_text(sum(r.total_edges for r in results)),
            _int_text(totals.raw_csv),
            _int_text(totals.gzip_csv),
            _int_text(totals.sqlite),
            _int_text(totals.gzip_sqlite),
            _ratio_text(totals.ratio_vs_raw),
            f"**{_ratio_text(totals.ratio_vs_gzip_csv)}**",
            _ratio_text(totals.ratio_like_for_like),
        )
    )
    lines += _table(
        (
            "scenario",
            "frames",
            "nodes",
            "edges",
            "raw CSV B",
            "gz CSV B",
            "SQLite B",
            "gz SQLite B",
            "x raw",
            "x gz CSV",
            "x gz/gz",
        ),
        rows,
    )

    headline = totals.ratio_vs_gzip_csv
    verdict = claim_verdict(headline)
    worst = min(results, key=lambda r: r.sizes.ratio_vs_gzip_csv)
    best = max(results, key=lambda r: r.sizes.ratio_vs_gzip_csv)
    lines += [
        "",
        f"**Headline: {_ratio_text(headline)} against gzipped CSV**, over all "
        "scenarios by total bytes. Worst single scenario "
        f"`{worst.scenario}` at {_ratio_text(worst.sizes.ratio_vs_gzip_csv)}; "
        f"best `{best.scenario}` at "
        f"{_ratio_text(best.sizes.ratio_vs_gzip_csv)}. The worst one is the "
        "number to argue with.",
        "",
        f"**Claim 1: {verdict}.** `docs/plan.md` states the success criterion as "
        f"2–4 orders of magnitude, i.e. at least "
        f"{_ratio_text(CLAIM_1_SUCCESS_RATIO)}; the headline above is "
        f"{_ratio_text(headline)}.",
    ]
    if headline < 1.0:
        lines += [
            "",
            "> **The artifact is larger than the stream it replaces.** A ratio "
            "below 1 is not a weak result, it is the opposite result: at these "
            "parameters the evidence graph costs more bytes to retain than the "
            "raw CSV would. See *Where the bytes are* below before quoting "
            "anything from this file.",
        ]
    lines += [
        "",
        "## Where the rows are",
        "",
        "The compression mechanism is the incremental rule (`reg.graph`): a "
        "relationship unchanged within tolerance extends an edge instead of "
        "emitting a row. `edges/frame` is that rule's report card — well below 1 "
        "means relationships are being held as intervals, and a value that "
        "tracks the frame count means an edge type is emitting per frame.",
        "",
    ]

    edge_types = list(store.EDGE_SPECS)
    node_kinds = list(store.NODE_TABLES)
    lines += _table(
        ("scenario", "frames", *edge_types, *node_kinds, "edges/frame"),
        [
            (
                f"`{r.scenario}`",
                _int_text(r.frames),
                *[_int_text(r.edges.get(t, 0)) for t in edge_types],
                *[_int_text(r.nodes.get(k, 0)) for k in node_kinds],
                f"{r.total_edges / r.frames:.3f}",
            )
            for r in results
        ],
    )

    labels = (*_TABLE_LABELS, INDEX_LABEL)
    attributed = [r for r in results if r.tables is not None]
    lines += [
        "",
        "## Where the bytes are",
        "",
        "Bytes per table, from SQLite's own `dbstat` — an attribution, not an",
        "estimate: the columns sum to the file size less any free pages. It is",
        "here so that a ratio can be acted on rather than just quoted. If one",
        "table dominates, that table is the thing to change.",
        "",
    ]
    if not attributed:
        lines += [
            "**Could not be attributed.** This SQLite build has no `dbstat` "
            "virtual table. That is a could-not-evaluate; no estimate is "
            "substituted for it.",
        ]
    else:
        if len(attributed) != len(results):
            missing = ", ".join(
                f"`{r.scenario}`" for r in results if r.tables is None
            )
            lines += [f"Not attributed (no `dbstat`): {missing}.", ""]
        lines += _table(
            ("scenario", *labels, "file"),
            [
                (
                    f"`{r.scenario}`",
                    *[_int_text((r.tables or {}).get(label, 0)) for label in labels],
                    _int_text(r.sizes.sqlite),
                )
                for r in attributed
            ],
        )

    lines += [
        "",
        "## Query wall-clock",
        "",
        f"One fixed question — **{QUESTION}** (query 1 of `docs/lossiness.md`'s",
        "supported set, reduced to a scalar) — answered from the graph alone and",
        "recomputed from the raw CSV as ground truth. Median of",
        f"{_repeats_text(results)} runs each.",
        "",
        "**The two timing columns are wall-clock and are not reproducible bit for "
        "bit.** Everything else in this report is a deterministic function of the "
        "seeds and parameters above; these two are measurements of a machine.",
        "",
        "The verdict is the check that this compression kept the answer:",
        f"`AGREE` means the two paths differ by no more than "
        f"{SEPARATION_TOLERANCE_M} m,",
        "the budget `docs/lossiness.md` allocates for query 1. `DISAGREE` is a bug",
        "in the graph, not a tolerance to widen. `COULD-NOT-EVALUATE` means a path",
        "returned no answer at all, and it never resolves to `AGREE`.",
        "",
    ]
    lines += _table(
        (
            "scenario",
            "graph",
            "raw CSV",
            "speedup",
            "graph answer",
            "CSV answer",
            "difference",
            "verdict",
        ),
        [
            (
                f"`{r.scenario}`",
                _seconds_text(r.check.graph_timing.seconds),
                _seconds_text(r.check.csv_timing.seconds),
                "n/a"
                if r.check.speedup is None
                else _ratio_text(r.check.speedup),
                _metres_text(r.check.graph_answer),
                _metres_text(r.check.csv_answer),
                _metres_text(r.check.difference),
                r.check.verdict,
            )
            for r in results
        ],
    )

    lines += ["", "## Realistic-sensor projection", ""]
    if sensor_multiplier is None:
        lines += [
            "**Not computed. No multiplier was supplied** (`--sensor-multiplier`).",
            "",
            "There is no default for it and there should not be. docs/plan.md",
            "Phase 8: \"the claim you can actually measure is",
            "graph-vs-logged-state. The terabytes/day figure is imported context,",
            "not a result from this sim.\" A plausible multiplier invented here",
            "would be indistinguishable from a measured one by the time anyone",
            "quoted the number.",
        ]
    else:
        lines += [
            f"**PROJECTION, not a measurement.** Multiplier **{sensor_multiplier}x**,",
            "supplied on the command line and applied to the raw CSV size. Nothing",
            "in this simulator produces sensor data; this row scales the state",
            "stream by a number a reader must judge for themselves, and every",
            "figure in it inherits that judgement.",
            "",
        ]
        lines += _table(
            ("scenario", "projected stream B (PROJECTION)", "SQLite B", "x projected"),
            [
                (
                    f"`{r.scenario}`",
                    _int_text(sensor_projection_bytes(r.sizes.raw_csv, sensor_multiplier)),
                    _int_text(r.sizes.sqlite),
                    _ratio_text(
                        compression_ratio(
                            sensor_projection_bytes(r.sizes.raw_csv, sensor_multiplier),
                            r.sizes.sqlite,
                        )
                    ),
                )
                for r in results
            ],
        )

    lines += _caveats()
    return "\n".join(lines) + "\n"


def _caveats() -> list[str]:
    """The four things no number in this report is evidence for."""
    return [
        "",
        "## What these numbers are not",
        "",
        "1. **Not a sensor-log compression ratio.** The baseline is a simulator",
        "   state stream in CSV. Obstacles are re-logged every frame on purpose",
        "   (`reg.stream`) so the baseline is not quietly pre-compressed, but it",
        "   is still not a camera.",
        "2. **Not evidence for the terabytes/day figure** in `docs/plan.md`. That",
        "   is imported context about production humanoids.",
        "3. **Not a safety claim.** The envelope is a sampling-based",
        "   under-approximation (`reg.envelope`); \"the robot could not have",
        "   reached (x, y)\" is not a claim this artifact supports.",
        "4. **Not a claim about other formats.** Change",
        "   `reg.stream.FLOAT_PRECISION` or the graph schema and both sides of",
        "   every ratio move; both versions are in the header for that reason.",
        "",
    ]


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def _positive_float(raw: str) -> float:
    try:
        value = float(raw)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{raw!r} is not a number") from None
    if not math.isfinite(value) or value <= 0.0:
        raise argparse.ArgumentTypeError(f"{value}: must be finite and positive")
    return value


def _non_negative_int(raw: str) -> int:
    try:
        value = int(raw)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{raw!r} is not an integer") from None
    if value < 0:
        raise argparse.ArgumentTypeError(f"{value}: must be >= 0")
    return value


def _frame_counts(raw: str) -> tuple[int, ...]:
    """A comma-separated ladder of run lengths, checked for being a ladder.

    Strictly increasing and at least two frames each. Out of order, the
    crossover text ("it is below 1.0 at every shorter measured length") would be
    a statement about the order they were typed in; duplicated, one length would
    be measured twice and reported as two rungs.
    """
    counts: list[int] = []
    for part in str(raw).split(","):
        text = part.strip()
        if not text:
            raise argparse.ArgumentTypeError(
                f"{raw!r} has an empty entry; the ladder is a comma-separated "
                "list of frame counts, e.g. 300,1000,3000"
            )
        try:
            value = int(text)
        except ValueError:
            raise argparse.ArgumentTypeError(f"{text!r} is not an integer") from None
        if value < 2:
            raise argparse.ArgumentTypeError(
                f"{value}: a run needs at least two frames for a frame period to "
                "exist, and `reg.graph` refuses a stream without one"
            )
        if counts and value <= counts[-1]:
            raise argparse.ArgumentTypeError(
                f"{value} does not come after {counts[-1]}: the lengths must be "
                "strictly increasing, or 'the ratio is below 1.0 at every "
                "shorter measured length' becomes a claim about typing order"
            )
        counts.append(value)
    if not counts:
        raise argparse.ArgumentTypeError("no frame counts given")
    return tuple(counts)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m reg.bench",
        description=(
            "Measure the evidence graph against the raw state stream it was "
            "built from, per scenario and as a function of run length, and write "
            "a markdown report. The headline ratio is against a gzipped "
            "baseline. Same seeds, same numbers (timings excepted, and labelled)."
        ),
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help=f"benchmark every scenario: {', '.join(SCENARIOS)}",
    )
    parser.add_argument(
        "--scaling",
        action="store_true",
        help=(
            "also measure the compression ratio as a function of run length, on "
            f"`reg.scenarios.long_run` at {', '.join(str(n) for n in SCALING_FRAME_COUNTS)} "
            "frames. Can be given on its own or alongside --all/--scenario. "
            "Expect tens of minutes: it is tens of thousands of envelopes."
        ),
    )
    parser.add_argument(
        "--resolution",
        action="store_true",
        help=(
            "also measure what evidence costs per unit of resolution: the "
            "occurrence layer (DSSAD-aligned, ±1 s), the transition layer (the "
            "current edge emission) and a per-frame expansion of it, as three "
            "views of one build, with bytes/hour and whether every supported "
            "query still AGREEs. Can be given on its own. This is Claim 1 as it "
            "stands after issue #30."
        ),
    )
    parser.add_argument(
        "--scenario",
        action="append",
        metavar="NAME",
        help="benchmark one scenario; repeatable. Mutually exclusive with --all.",
    )
    parser.add_argument(
        "--out",
        metavar="PATH",
        help="markdown report to write; parent directories are created. No default.",
    )
    parser.add_argument(
        "--seed",
        type=_non_negative_int,
        default=DEFAULT_SEED,
        metavar="N",
        help=(
            f"simulator seed (default: {DEFAULT_SEED}, same as `reg.sim`). "
            "Printed in the report either way."
        ),
    )
    parser.add_argument(
        "--horizon",
        type=_positive_float,
        default=graph.ENVELOPE_HORIZON,
        metavar="SECONDS",
        help=f"envelope horizon (default: {graph.ENVELOPE_HORIZON}, docs/plan.md Phase 2)",
    )
    parser.add_argument(
        "--n-samples",
        type=_non_negative_int,
        default=graph.ENVELOPE_N_SAMPLES,
        metavar="N",
        help=(
            f"control sequences per envelope (default: {graph.ENVELOPE_N_SAMPLES}). "
            "This dominates the runtime: an envelope per frame over every "
            "scenario is tens of minutes at the default."
        ),
    )
    parser.add_argument(
        "--envelope-seed",
        type=_non_negative_int,
        default=graph.ENVELOPE_SEED,
        metavar="N",
        help=f"seed for the interior control samples (default: {graph.ENVELOPE_SEED})",
    )
    parser.add_argument(
        "--substep-dt",
        type=_positive_float,
        default=SUBSTEP_DT,
        metavar="SECONDS",
        help=f"envelope integration resolution (default: {SUBSTEP_DT})",
    )
    parser.add_argument(
        "--sensor-multiplier",
        type=_positive_float,
        default=None,
        metavar="X",
        help=(
            "if given, the report carries a projected 'realistic sensor' column "
            "equal to the raw stream times X, labelled PROJECTION. **No default**: "
            "an invented multiplier is indistinguishable from a measured one "
            "downstream, so without this flag the column does not exist."
        ),
    )
    parser.add_argument(
        "--scaling-frames",
        type=_frame_counts,
        default=SCALING_FRAME_COUNTS,
        metavar="N,N,...",
        help=(
            "the ladder of run lengths --scaling measures, strictly increasing "
            f"(default: {','.join(str(n) for n in SCALING_FRAME_COUNTS)}, from "
            "issue #30). A shorter ladder is a smaller study, and the report "
            "prints the lengths it actually ran."
        ),
    )
    parser.add_argument(
        "--scaling-n-samples",
        type=_non_negative_int,
        default=SCALING_N_SAMPLES,
        metavar="N",
        help=(
            f"control sequences per envelope for the ladder (default: "
            f"{SCALING_N_SAMPLES}). Lower than --n-samples because the ladder is "
            "tens of thousands of envelopes; since issue #28 it moves no byte "
            "count, and the report carries a control row measuring what the "
            "reduction did to the ratio."
        ),
    )
    parser.add_argument(
        "--resolution-frames",
        type=_non_negative_int,
        default=RESOLUTION_FRAME_COUNT,
        metavar="N",
        help=(
            f"run length for --resolution (default: {RESOLUTION_FRAME_COUNT}, "
            "the middle rung of issue #30's ladder — one moderate length is "
            "enough to establish a curve whose variable is resolution, not "
            "length)."
        ),
    )
    parser.add_argument(
        "--resolution-n-samples",
        type=_non_negative_int,
        default=SCALING_N_SAMPLES,
        metavar="N",
        help=(
            f"control sequences per envelope for --resolution (default: "
            f"{SCALING_N_SAMPLES}, the value issue #30 established as legitimate "
            "for size-comparison work; since issue #28 it moves no byte count)."
        ),
    )
    parser.add_argument(
        "--occurrence-resolution",
        type=_positive_float,
        default=graph.OCCURRENCE_TIME_RESOLUTION_S,
        metavar="SECONDS",
        help=(
            "the resolution occurrence timestamps are rounded to (default: "
            f"{graph.OCCURRENCE_TIME_RESOLUTION_S}, UN R157 DSSAD's stated "
            "accuracy). This is the variable the resolution curve prices; it "
            "does not touch the edge layer, whose endpoints are at TIME_TOL_S."
        ),
    )
    parser.add_argument(
        "--work-dir",
        metavar="PATH",
        help=(
            "keep the intermediate CSV and SQLite here instead of in a temporary "
            "directory that is deleted afterwards. The location does not enter "
            "any measurement."
        ),
    )
    return parser


def _selected(args: argparse.Namespace, parser: argparse.ArgumentParser) -> list[str]:
    if args.all and args.scenario:
        parser.error(
            "--all and --scenario are mutually exclusive. Asking for both leaves "
            "it ambiguous which set the table describes."
        )
    if args.all:
        return list(SCENARIOS)
    if not args.scenario:
        if args.scaling or args.resolution:
            return []
        parser.error(
            "nothing to benchmark: pass --all, --scenario NAME (repeatable), "
            f"--scaling or --resolution. Known scenarios: {', '.join(SCENARIOS)}."
        )
    unknown = [name for name in args.scenario if name not in SCENARIOS]
    if unknown:
        parser.error(
            f"unknown scenario(s): {', '.join(unknown)}. Known scenarios: "
            f"{', '.join(SCENARIOS)}."
        )
    return list(args.scenario)


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)

    names = _selected(args, parser)
    if args.out is None:
        parser.error(
            "--out is required and has no default: a benchmark whose report went "
            "somewhere nobody named is a benchmark nobody can check."
        )

    work_dir = Path(args.work_dir) if args.work_dir else Path(tempfile.mkdtemp(prefix="reg-bench-"))
    results: list[ScenarioResult] = []
    scaling: list[ScalingPoint] = []
    control: ScalingPoint | None = None
    resolution: ResolutionCurve | None = None
    try:
        for name in names:
            print(f"benchmarking {name}...", file=sys.stderr, flush=True)
            results.append(
                run_scenario(
                    name,
                    work_dir,
                    seed=args.seed,
                    horizon=args.horizon,
                    n_samples=args.n_samples,
                    envelope_seed=args.envelope_seed,
                    substep_dt=args.substep_dt,
                    occurrence_resolution_s=args.occurrence_resolution,
                )
            )
        if args.resolution:
            print(
                f"measuring the resolution curve on long_run at "
                f"{args.resolution_frames} frames "
                f"(n_samples={args.resolution_n_samples}, occurrence "
                f"resolution={args.occurrence_resolution} s)...",
                file=sys.stderr,
                flush=True,
            )
            resolution = run_resolution_curve(
                args.resolution_frames,
                work_dir / "resolution",
                seed=args.seed,
                horizon=args.horizon,
                n_samples=args.resolution_n_samples,
                envelope_seed=args.envelope_seed,
                substep_dt=args.substep_dt,
                occurrence_resolution_s=args.occurrence_resolution,
            )
        if args.scaling:
            for frames in args.scaling_frames:
                print(
                    f"benchmarking long_run at {frames} frames "
                    f"(n_samples={args.scaling_n_samples})...",
                    file=sys.stderr,
                    flush=True,
                )
                scaling.append(
                    run_scaling_point(
                        frames,
                        work_dir,
                        seed=args.seed,
                        horizon=args.horizon,
                        n_samples=args.scaling_n_samples,
                        envelope_seed=args.envelope_seed,
                        substep_dt=args.substep_dt,
                        occurrence_resolution_s=args.occurrence_resolution,
                    )
                )
            # The control: the shortest rung again at the per-scenario table's
            # sample count, so the cost of the reduction is measured rather than
            # asserted. Skipped when there is no reduction to measure — a row
            # comparing a parameter with itself would read as a check that
            # passed.
            if args.scaling_n_samples != args.n_samples:
                shortest = min(args.scaling_frames)
                print(
                    f"benchmarking long_run at {shortest} frames "
                    f"(control, n_samples={args.n_samples})...",
                    file=sys.stderr,
                    flush=True,
                )
                control = run_scaling_point(
                    shortest,
                    work_dir / "control",
                    seed=args.seed,
                    horizon=args.horizon,
                    n_samples=args.n_samples,
                    envelope_seed=args.envelope_seed,
                    substep_dt=args.substep_dt,
                    occurrence_resolution_s=args.occurrence_resolution,
                )
        report = render(
            results,
            seed=args.seed,
            horizon=args.horizon,
            n_samples=args.n_samples,
            envelope_seed=args.envelope_seed,
            substep_dt=args.substep_dt,
            occurrence_resolution_s=args.occurrence_resolution,
            sensor_multiplier=args.sensor_multiplier,
            scaling=scaling,
            scaling_control=control,
            resolution=resolution,
        )
    except (BenchError, graph.GraphBuildError, store.StoreError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    finally:
        if not args.work_dir:
            shutil.rmtree(work_dir, ignore_errors=True)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")

    # WHAT GATES THE EXIT CODE, AND WHAT DELIBERATELY DOES NOT. Every build's own
    # cross-check does: a graph that stopped answering query 1 correctly is a bug.
    # The per-level verdicts in the resolution curve do **not**, and that is the
    # point of the curve rather than a leniency — "the occurrence layer cannot
    # answer the separation timeline" is the measurement issue #35 exists to
    # produce, and a command that exited non-zero on its own finding would push
    # the next person to tune the finding away.
    measured = [*results, *[p.result for p in scaling]]
    if control is not None:
        measured.append(control.result)
    if resolution is not None:
        measured.append(resolution.source)
    failed = [r for r in measured if r.check.verdict != AGREE]
    for r in failed:
        print(
            f"warning: {r.scenario}: the graph and the raw CSV answered "
            f"{QUESTION!r} as {r.check.graph_answer!r} and {r.check.csv_answer!r} "
            f"-> {r.check.verdict}",
            file=sys.stderr,
        )
    if resolution is not None:
        for point in resolution.points:
            print(
                f"resolution: {point.level}: {point.size_bytes} B "
                f"({_bytes_per_hour_text(point.bytes_per_hour)}) -> "
                f"{point.verdict}",
                file=sys.stderr,
            )
    print(
        f"wrote {out}: scenarios={len(results)} scaling_points={len(scaling)} "
        f"resolution_levels={0 if resolution is None else len(resolution.points)} "
        f"seed={args.seed}"
    )
    return EXIT_CHECK_FAILED if failed else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
