"""The compression benchmark: the arithmetic, the verdicts, and the refusals.

WHY ALMOST NOTHING HERE ASSERTS A LIVE NUMBER
---------------------------------------------
Claim 1's headline ratio will move with every change to the graph schema, the
envelope parameters and the raw stream's float precision — that is the point of
having a benchmark. A test pinned to today's ratio would be a golden value that
goes red for improvements and green for a benchmark that quietly stopped
measuring anything.

So the ratios are tested on **hand-worked examples** (issue #15: "ratios are
computed the stated way — assert on a hand-worked example rather than on the
live numbers, which will move"), and the live run is tested for *shape*: every
required column present, every count a count of something, and the same numbers
twice.

THE TESTS THIS FILE EXISTS FOR
------------------------------
`test_the_report_says_so_when_the_artifact_is_larger_than_the_stream` and
`test_the_cross_check_says_no_when_the_graph_is_perturbed`. A benchmark is a
check on Claim 1 and a check must be able to fail, so both of its verdicts are
fed the condition they guard against:

* a result set where the "compressed" artifact is *larger* than the baseline —
  the report must say Claim 1 is `NOT MET` and say the artifact is larger, not
  print a small number and move on;
* an artifact whose separation rows have been perturbed past `DISTANCE_TOL_M` —
  the cross-check must return `DISAGREE`, and an artifact with no separation
  rows at all must return `COULD-NOT-EVALUATE` rather than agreeing with an
  empty result set.

Envelope parameters are deliberately coarse throughout (`_FAST`), for the reason
`tests/test_graph.py` gives: cost is linear in `n_samples * horizon / substep_dt`
and nothing here is about envelope fidelity. They are passed explicitly at every
call so no test depends on a default staying put.
"""

from __future__ import annotations

import dataclasses
import shutil
from pathlib import Path

import pytest
from shapely.ops import unary_union

from reg import bench, graph, query, store
from reg.bench import (
    AGREE,
    COULD_NOT_EVALUATE,
    DISAGREE,
    MET,
    NOT_MET,
    BenchError,
    ScalingPoint,
    ScenarioResult,
    SeparationCheck,
    Sizes,
    Timing,
    agreement,
    claim_verdict,
    compression_ratio,
    crossover,
    gzip_bytes,
    min_separation_from_graph,
    render,
    run_scaling_point,
    run_scenario,
    sensor_projection_bytes,
)
from reg.envelope import compute_envelope
from reg.kinematics import link_polygons
from reg.scenarios import SCENARIOS, long_run, scenario
from reg.tolerances import DISTANCE_TOL_M, simplify_geometry

#: Coarse but legal: 4 samples is exactly the corner count for the two-link demo
#: arm, so `compute_envelope` accepts it.
_FAST = {
    "horizon": 0.05,
    "n_samples": 4,
    "envelope_seed": 0,
    "substep_dt": 0.05,
    # Stated rather than inherited, like the four above: it is a parameter of
    # the artifact these tests measure, and `run_scenario` has no default for it.
    "occurrence_resolution_s": graph.OCCURRENCE_TIME_RESOLUTION_S,
}

#: One scenario, the shortest that still has a human moving through the scene.
SCENARIO = "near_miss"

_RENDER_ARGS = {
    "seed": 0,
    "horizon": 0.2,
    "n_samples": 512,
    "envelope_seed": 0,
    "substep_dt": 0.02,
    "occurrence_resolution_s": graph.OCCURRENCE_TIME_RESOLUTION_S,
}


# --------------------------------------------------------------------------
# Hand-worked arithmetic. Every ratio in the report is one of these three.
# --------------------------------------------------------------------------


def test_compression_ratio_is_baseline_over_artifact() -> None:
    """1 MB of stream into 4 kB of graph is 250x, and nothing else."""
    assert compression_ratio(1_000_000, 4_000) == 250.0
    assert compression_ratio(4_000, 1_000_000) == 0.004


def test_the_three_ratios_are_computed_the_stated_way() -> None:
    """The headline divides the *gzipped* baseline by the artifact **on disk**.

    Hand-worked so the definition is pinned independently of the live numbers:
    a 1000-byte stream that gzips to 100, against a 50-byte artifact that gzips
    to 20.
    """
    sizes = Sizes(raw_csv=1000, gzip_csv=100, sqlite=50, gzip_sqlite=20)
    assert sizes.ratio_vs_raw == 20.0  # 1000 / 50
    assert sizes.ratio_vs_gzip_csv == 2.0  # 100 / 50  <- the headline
    assert sizes.ratio_like_for_like == 5.0  # 100 / 20


def test_the_headline_is_the_most_conservative_of_the_three() -> None:
    """An invariant, not a value: whenever gzip actually compresses both sides,
    the headline is the smallest ratio the report carries. This is what stops a
    later edit from quietly promoting a friendlier number to the headline."""
    sizes = Sizes(raw_csv=999_999, gzip_csv=123_456, sqlite=7_777, gzip_sqlite=2_222)
    assert sizes.ratio_vs_gzip_csv <= sizes.ratio_vs_raw
    assert sizes.ratio_vs_gzip_csv <= sizes.ratio_like_for_like


@pytest.mark.parametrize("artifact", [0, -1])
def test_an_empty_artifact_is_a_refusal_not_infinite_compression(artifact: int) -> None:
    """A division by zero here would print as the best ratio ever recorded."""
    with pytest.raises(BenchError, match="division by zero|bytes"):
        compression_ratio(1000, artifact)


def test_an_empty_baseline_is_a_refusal() -> None:
    """Zero would read as 'the graph is larger', not as 'nothing was written'."""
    with pytest.raises(BenchError, match="baseline"):
        compression_ratio(0, 1000)


# --------------------------------------------------------------------------
# The projection. It is the part of Claim 1 most easily overstated.
# --------------------------------------------------------------------------


def test_the_projection_is_the_raw_stream_times_the_stated_multiplier() -> None:
    assert sensor_projection_bytes(1000, 100.0) == 100_000
    assert sensor_projection_bytes(1000, 1.0) == 1000


def test_a_multiplier_below_one_is_refused() -> None:
    """A "realistic sensor" stream is richer than a state stream. A multiplier
    below 1 would shrink the baseline while still being labelled conservative."""
    with pytest.raises(BenchError, match="multiplier"):
        sensor_projection_bytes(1000, 0.5)


def test_without_a_multiplier_there_is_no_projection_at_all(tmp_path: Path) -> None:
    """No default, and no invented column. The report says why instead."""
    report = render([_result()], sensor_multiplier=None, **_RENDER_ARGS)
    assert "No multiplier was supplied" in report
    assert "PROJECTION" not in report


def test_with_a_multiplier_the_projection_is_labelled_a_projection() -> None:
    report = render([_result()], sensor_multiplier=100.0, **_RENDER_ARGS)
    assert "PROJECTION, not a measurement" in report
    assert "100.0x" in report
    # 20,000 raw bytes x 100 = 2,000,000, formatted with separators.
    assert "2,000,000" in report


@pytest.mark.parametrize("multiplier", [None, 100.0])
def test_the_report_disowns_the_terabytes_figure_either_way(multiplier) -> None:
    """Issue #15: say it "in the output itself, not only in prose"."""
    report = render([_result()], sensor_multiplier=multiplier, **_RENDER_ARGS)
    assert "imported context" in report
    assert "terabytes/day" in report


# --------------------------------------------------------------------------
# The verdicts. Both must be able to say no.
# --------------------------------------------------------------------------


def test_agreement_says_yes_inside_the_tolerance_and_no_outside_it() -> None:
    assert agreement(0.10, 0.105, DISTANCE_TOL_M) == AGREE
    assert agreement(0.10, 0.11, DISTANCE_TOL_M) == AGREE  # exactly at tolerance
    assert agreement(0.10, 0.13, DISTANCE_TOL_M) == DISAGREE


@pytest.mark.parametrize(
    ("graph_answer", "csv_answer"), [(None, 0.5), (0.5, None), (None, None)]
)
def test_a_missing_answer_never_resolves_to_agreement(graph_answer, csv_answer) -> None:
    """THE THIRD OUTCOME. An absent separation row and a separation of zero are
    different facts; the first must never read as agreement with the second."""
    assert agreement(graph_answer, csv_answer, DISTANCE_TOL_M) == COULD_NOT_EVALUATE


def test_claim_1_has_a_bar_and_it_can_be_missed() -> None:
    """docs/plan.md: 2-4 orders of magnitude. Two orders is 100x."""
    assert claim_verdict(100.0) == MET
    assert claim_verdict(1_000.0) == MET
    assert claim_verdict(99.9) == NOT_MET
    assert claim_verdict(0.02) == NOT_MET


def test_the_report_says_so_when_the_artifact_is_larger_than_the_stream() -> None:
    """THE NEGATIVE TEST FOR THE HEADLINE.

    Feed the report the condition it exists to detect — an artifact bigger than
    the baseline it replaced — and assert it says so in words rather than
    printing 0.02x among nine other columns and leaving the reader to notice.
    """
    fat = _result(sizes=Sizes(raw_csv=20_000, gzip_csv=2_000, sqlite=300_000, gzip_sqlite=100_000))
    report = render([fat], sensor_multiplier=None, **_RENDER_ARGS)
    assert f"**Claim 1: {NOT_MET}.**" in report
    assert "larger than the stream it replaces" in report


def test_the_report_says_claim_1_is_met_when_the_ratio_clears_the_bar() -> None:
    """And the positive half, so the test above is not passing on a report that
    says "NOT MET" unconditionally."""
    lean = _result(sizes=Sizes(raw_csv=2_000_000, gzip_csv=200_000, sqlite=1_000, gzip_sqlite=400))
    report = render([lean], sensor_multiplier=None, **_RENDER_ARGS)
    assert f"**Claim 1: {MET}.**" in report
    assert "larger than the stream it replaces" not in report


def test_render_refuses_an_empty_result_set() -> None:
    """An empty report reads as 'the graph compresses nothing measured'."""
    with pytest.raises(BenchError, match="no scenarios"):
        render([], sensor_multiplier=None, **_RENDER_ARGS)


def test_timings_that_disagree_across_repeats_are_refused() -> None:
    """Both query paths are pure functions of a file on disk. A repeat that
    answers differently means one of them is reading something that is not in
    the file, and a median of two different answers would hide it."""
    answers = iter([0.5, 0.5, 0.6])
    with pytest.raises(BenchError, match="repeats"):
        bench._timed(lambda: next(answers), 3, "unit test")


# --------------------------------------------------------------------------
# gzip
# --------------------------------------------------------------------------


def test_gzip_bytes_compresses_and_is_reproducible(tmp_path: Path) -> None:
    """The baseline has to be measurable twice to the same number, or the ratio
    it is the numerator of is not reproducible either."""
    path = tmp_path / "repetitive.csv"
    path.write_text("t,q_0\n" + "0.000000,0.000000\n" * 500, encoding="utf-8")
    first = gzip_bytes(path)
    assert first == gzip_bytes(path)
    assert first < path.stat().st_size


def test_gzipping_an_empty_file_is_refused(tmp_path: Path) -> None:
    """A 20-byte gzip header is not a compressed stream; an empty input file is
    a step of the pipeline that did not run."""
    empty = tmp_path / "empty.csv"
    empty.write_bytes(b"")
    with pytest.raises(BenchError, match="empty"):
        gzip_bytes(empty)


# --------------------------------------------------------------------------
# The live run. Shape, not values.
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def live(tmp_path_factory) -> ScenarioResult:
    """One real scenario, benchmarked end to end. Module-scoped: it simulates,
    builds a graph and answers a query, and three tests want the same one."""
    work = tmp_path_factory.mktemp("bench-live")
    return run_scenario(SCENARIO, work, seed=0, **_FAST)


def test_a_scenario_run_produces_every_required_column(live: ScenarioResult) -> None:
    """Issue #15's required per-scenario columns, each present and each a
    measurement of something rather than a placeholder."""
    assert live.scenario == SCENARIO
    assert live.frames > 1

    assert live.sizes.raw_csv > 0
    assert live.sizes.gzip_csv > 0
    assert live.sizes.gzip_csv < live.sizes.raw_csv
    assert live.sizes.sqlite > 0
    assert live.sizes.gzip_sqlite > 0
    assert live.sizes.gzip_sqlite < live.sizes.sqlite

    assert live.sizes.ratio_vs_raw > 0.0
    assert live.sizes.ratio_vs_gzip_csv > 0.0

    # All four edge types and all four node kinds, present even at zero: a
    # missing key is indistinguishable from "no contact in this run".
    assert set(live.edges) == set(store.EDGE_SPECS)
    assert set(live.nodes) == set(store.NODE_TABLES)
    assert live.total_edges > 0
    assert live.total_nodes > 0


def test_the_fixed_question_is_answered_from_both_sides_and_they_agree(
    live: ScenarioResult,
) -> None:
    """The compression is only a result if the answer survived it.

    docs/lossiness.md's predicate for query 1: |d_graph - d_csv| <=
    DISTANCE_TOL_M. Both answers are asserted present first — two `None`s would
    "agree" in the loosest possible sense and this test would say nothing.
    """
    check = live.check
    assert check.graph_answer is not None
    assert check.csv_answer is not None
    assert check.verdict == AGREE
    assert check.difference <= DISTANCE_TOL_M
    assert check.graph_timing.seconds > 0.0
    assert check.csv_timing.seconds > 0.0


def test_two_runs_agree_on_every_number_except_the_clock(tmp_path: Path) -> None:
    """Determinism (CLAUDE.md rule 2), scoped honestly: the sizes, the row
    counts and the answers are a function of the seeds; the timings are not, and
    the report says which is which rather than claiming both."""
    a = run_scenario(SCENARIO, tmp_path / "a", seed=0, **_FAST)
    b = run_scenario(SCENARIO, tmp_path / "b", seed=0, **_FAST)

    assert a.sizes == b.sizes
    assert a.frames == b.frames
    assert a.edges == b.edges
    assert a.nodes == b.nodes
    assert a.tables == b.tables
    assert a.check.graph_answer == b.check.graph_answer
    assert a.check.csv_answer == b.check.csv_answer


def test_a_different_seed_is_a_different_run(tmp_path: Path) -> None:
    """The seed is reported because it moves the numbers. If it did not,
    reporting it would be decoration and the determinism claim would be empty."""
    a = run_scenario(SCENARIO, tmp_path / "a", seed=0, **_FAST)
    b = run_scenario(SCENARIO, tmp_path / "b", seed=7, **_FAST)
    assert a.check.csv_answer != b.check.csv_answer


def test_the_report_carries_the_seeds_and_the_envelope_parameters(
    live: ScenarioResult,
) -> None:
    """Issue #15: "the table includes the seed used". Both seeds, in fact — the
    simulator's and the envelope's — because a run reproduced with the wrong one
    produces different numbers and no error."""
    report = render([live], sensor_multiplier=None, seed=3, horizon=0.2, n_samples=512,
                    envelope_seed=11, substep_dt=0.02, occurrence_resolution_s=0.25)
    assert "| simulator seed | 3 |" in report
    assert "| envelope seed | 11 |" in report
    assert "| envelope horizon | 0.2 s |" in report
    assert "| envelope samples | 512 |" in report
    # The occurrence resolution moves the occurrence layer's timestamps and
    # nothing else, and it is settable, so the header states which one produced
    # the artifact rather than leaving a reader to assume DSSAD's 1.0 s.
    assert "| occurrence resolution | 0.25 s |" in report
    assert f"| gzip level | {bench.GZIP_COMPRESSLEVEL} |" in report


def test_the_reported_repeat_count_is_the_one_the_numbers_were_measured_under() -> None:
    """`run_scenario` takes the repeat count as an argument, so the header must
    read it off the results rather than print the module constant — otherwise it
    states a protocol the table was not measured under."""
    five = _result(
        check=SeparationCheck(
            verdict=AGREE,
            graph_answer=0.12,
            csv_answer=0.123,
            tolerance=DISTANCE_TOL_M,
            graph_timing=Timing(seconds=0.0002, repeats=5),
            csv_timing=Timing(seconds=0.05, repeats=5),
        )
    )
    report = render([five], sensor_multiplier=None, **_RENDER_ARGS)
    assert "| timing repeats | 5 |" in report


def test_the_report_has_a_row_per_scenario_with_every_required_column(
    live: ScenarioResult,
) -> None:
    report = render([live], sensor_multiplier=None, **_RENDER_ARGS)
    header = next(
        line for line in report.splitlines() if line.startswith("| scenario | frames |")
    )
    for column in ("raw CSV B", "gz CSV B", "SQLite B", "gz SQLite B", "x raw", "x gz CSV"):
        assert column in header
    assert f"| `{SCENARIO}` |" in report
    # And the wall-clock comparison the issue asks for, both sides of it.
    assert bench.QUESTION in report
    assert "speedup" in report


# --------------------------------------------------------------------------
# The cross-check, fed what it guards against.
# --------------------------------------------------------------------------


@pytest.fixture()
def artifact(tmp_path: Path) -> Path:
    """A real evidence graph to perturb."""
    run_scenario(SCENARIO, tmp_path, seed=0, **_FAST)
    return tmp_path / f"{SCENARIO}.sqlite"


def test_the_cross_check_says_no_when_the_graph_is_perturbed(artifact: Path) -> None:
    """THE NEGATIVE TEST. docs/lossiness.md: "feed it a graph with a deliberately
    perturbed edge — one distance shifted by more than DISTANCE_TOL_M — and
    assert it reports fail". A harness only ever run against a healthy graph has
    not been shown able to fail at all."""
    healthy = min_separation_from_graph(artifact)
    assert healthy is not None

    conn = store.connect(artifact)
    try:
        conn.execute(
            "UPDATE edge SET min_distance = min_distance + ? WHERE type = 'SEPARATION'",
            (10 * DISTANCE_TOL_M,),
        )
        conn.commit()
    finally:
        conn.close()

    perturbed = min_separation_from_graph(artifact)
    assert perturbed is not None
    assert agreement(perturbed, healthy, DISTANCE_TOL_M) == DISAGREE


def test_an_artifact_with_no_separation_rows_could_not_evaluate(artifact: Path) -> None:
    """Silence is not agreement. An empty result set must not answer 0.0, which
    reads as contact, nor a large number, which reads as safety."""
    conn = store.connect(artifact)
    try:
        conn.execute("DELETE FROM edge WHERE type = 'SEPARATION'")
        conn.commit()
    finally:
        conn.close()

    assert min_separation_from_graph(artifact) is None
    assert agreement(None, 0.42, DISTANCE_TOL_M) == COULD_NOT_EVALUATE


def test_an_entity_that_is_not_in_the_graph_could_not_evaluate(artifact: Path) -> None:
    """"Absence of an entity from the graph is not evidence of its absence from
    the room" (docs/lossiness.md, Unanswerable #2)."""
    assert min_separation_from_graph(artifact, "nobody_by_that_name") is None


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def test_cli_writes_a_report(tmp_path: Path) -> None:
    out = tmp_path / "results.md"
    code = bench.main(
        [
            "--scenario",
            SCENARIO,
            "--out",
            str(out),
            "--n-samples",
            str(_FAST["n_samples"]),
            "--horizon",
            str(_FAST["horizon"]),
            "--substep-dt",
            str(_FAST["substep_dt"]),
            "--work-dir",
            str(tmp_path / "work"),
        ]
    )
    assert code == bench.EXIT_OK
    report = out.read_text(encoding="utf-8")
    assert f"| `{SCENARIO}` |" in report
    # Nothing that varies between two runs of the same command may be in the
    # report -- the work directory in particular (reg.sim, rule 2).
    assert str(tmp_path) not in report


def test_cli_all_benchmarks_every_scenario(tmp_path: Path, monkeypatch) -> None:
    """`--all` is the deliverable command, and it must mean *all six*.

    The run itself is stubbed: this is a test about the selection and the
    report, and an envelope per frame over six scenarios is tens of minutes —
    the issue's verification command is where the real thing runs.
    """
    seen: list[str] = []

    def fake_run(name, work_dir, **kwargs):
        seen.append(name)
        return _result(scenario=name)

    monkeypatch.setattr(bench, "run_scenario", fake_run)
    out = tmp_path / "results.md"
    assert bench.main(["--all", "--out", str(out)]) == bench.EXIT_OK

    assert seen == list(SCENARIOS)
    report = out.read_text(encoding="utf-8")
    for name in SCENARIOS:
        assert f"| `{name}` |" in report


def test_cli_exits_non_zero_when_a_cross_check_did_not_agree(
    tmp_path: Path, monkeypatch
) -> None:
    """The benchmark is a check, so the shell has to be able to see it fail. A
    report full of ratios whose answers no longer survive compression is worse
    than no report: it is a wrong result that looks like a right one."""
    disagreeing = _result(
        check=SeparationCheck(
            verdict=DISAGREE,
            graph_answer=0.12,
            csv_answer=0.90,
            tolerance=DISTANCE_TOL_M,
            graph_timing=Timing(seconds=0.0002, repeats=3),
            csv_timing=Timing(seconds=0.05, repeats=3),
        )
    )
    monkeypatch.setattr(bench, "run_scenario", lambda name, work_dir, **kw: disagreeing)
    out = tmp_path / "results.md"
    assert bench.main(["--scenario", SCENARIO, "--out", str(out)]) == bench.EXIT_CHECK_FAILED
    # ...and the report was still written, because the numbers in it are what
    # someone diagnosing the disagreement needs.
    assert out.exists()


@pytest.mark.parametrize(
    "argv",
    [
        pytest.param([], id="no selection"),
        pytest.param(["--all", "--scenario", SCENARIO], id="both"),
        pytest.param(["--scenario", "not_a_scenario"], id="unknown scenario"),
    ],
)
def test_cli_refuses_an_ambiguous_or_unknown_selection(
    tmp_path: Path, argv: list[str]
) -> None:
    """Defaulting to a scenario, or to all of them, would write a complete and
    plausible table of a question nobody asked (`reg.sim` makes the same
    refusal)."""
    with pytest.raises(SystemExit) as excinfo:
        bench.main([*argv, "--out", str(tmp_path / "results.md")])
    assert excinfo.value.code == bench.EXIT_USAGE


def test_cli_requires_an_output_path() -> None:
    with pytest.raises(SystemExit) as excinfo:
        bench.main(["--scenario", SCENARIO])
    assert excinfo.value.code == bench.EXIT_USAGE


# --------------------------------------------------------------------------
# The long-run fixture (issue #30). The scaling table is a table about one
# fixture, so what that fixture actually does is the first thing to pin down.
# --------------------------------------------------------------------------


@pytest.mark.parametrize("frames", [2, 37, 300, 3_000])
def test_the_long_run_is_the_length_it_was_asked_for(frames: int) -> None:
    """The frame count is the parameter, so it had better be the frame count."""
    scn = long_run(frames)
    assert scn.n_frames == frames
    assert len(tuple(scn.states(0))) == frames
    assert scn.name == f"long_run_{frames}"


def test_the_long_run_resolves_from_its_own_name() -> None:
    """A stream records its scenario *name*; `reg.graph` recovers the world from
    it. A generated name nothing can resolve would make the long run the one
    stream whose limits and human radius cannot be recovered from the file."""
    assert scenario("long_run_640").joint_waypoints == long_run(640).joint_waypoints
    with pytest.raises(KeyError, match="unknown scenario"):
        scenario("long_run_")
    with pytest.raises(KeyError, match="unknown scenario"):
        scenario("long_run_abc")


def test_a_long_run_stream_can_be_rebuilt_from_its_own_provenance(
    tmp_path: Path,
) -> None:
    """The chain from artifact back to parameters stays closed for a generated
    fixture. `reg.graph` recovers the robot's limits and the human's radius from
    the scenario *named in the stream*, and refuses rather than invent them — so
    a name it could not resolve would make the long run the one stream nobody
    can rebuild. Cheap envelope parameters: this is about the lookup."""
    csv = bench._write_stream(long_run(20), 0, tmp_path / "long.csv")
    code = graph.main(
        [
            "build",
            str(csv),
            "--out",
            str(tmp_path / "long.sqlite"),
            "--n-samples",
            str(_FAST["n_samples"]),
            "--horizon",
            str(_FAST["horizon"]),
            "--substep-dt",
            str(_FAST["substep_dt"]),
        ]
    )
    assert code == graph.EXIT_OK
    assert (tmp_path / "long.sqlite").stat().st_size > 0


@pytest.mark.parametrize("frames", [0, 1, -5])
def test_a_run_shorter_than_two_frames_is_refused(frames: int) -> None:
    """`reg.graph` refuses a stream with no frame period; generating one here
    would just move the failure somewhere it reads as a build error."""
    with pytest.raises(ValueError, match="two frames"):
        long_run(frames)


def test_a_non_integer_length_is_refused() -> None:
    with pytest.raises(TypeError, match="int"):
        long_run(300.0)  # type: ignore[arg-type]


def test_no_two_frames_of_the_long_run_are_identical() -> None:
    """THE PROPERTY THE FIXTURE EXISTS FOR, and the one issue #30 names as
    disqualifying: "a path that produces literally identical frames is not [a
    fixture], because it would compress in a way a real run would not".

    A 3,000-frame run is a minute of robot time, fifteen arm cycles. Without the
    per-cycle drift every fourth second would repeat exactly, gzip would
    collapse the baseline and the incremental rule would see one transition set
    over and over — both sides of the ratio would be measuring the fixture's
    periodicity rather than the graph.
    """
    frames = tuple(long_run(3_000).states(0))
    signatures = {
        (tuple(f.q), tuple(f.qd), tuple(f.human_pos)) for f in frames
    }
    assert len(signatures) == len(frames)


def test_the_long_run_is_deterministic_in_length_and_seed() -> None:
    """Same length and seed, same frames; a different seed, a different run.
    Both halves, because a fixture that ignored the seed would pass the first."""
    a = tuple(long_run(300).states(0))
    b = tuple(long_run(300).states(0))
    assert [f.human_pos.tolist() for f in a] == [f.human_pos.tolist() for f in b]
    assert [f.q.tolist() for f in a] == [f.q.tolist() for f in b]

    other = tuple(long_run(300).states(7))
    assert [f.q.tolist() for f in other] != [f.q.tolist() for f in a]


def test_a_longer_run_extends_the_shorter_one_rather_than_replacing_it() -> None:
    """Two rungs of the ladder are one run measured for longer.

    If they were not — if the fixture rescaled itself to the length asked for —
    the table would compare two different fixtures and call the difference
    scaling. The knots come off an absolute clock, so they line up.

    Up to the last *full* knot only, and the boundary is the honest part: each
    run's final knot lands on its own end, so the last segment of the shorter
    run is that run's own, and the seed's per-knot draws stop lining up there
    too. Nothing before it moves.
    """
    short_scn, long_scn = long_run(300), long_run(3_000)
    shared_until = min(
        short_scn.joint_waypoints[-2].t, short_scn.human_waypoints[-2].t
    )
    short = [f for f in short_scn.states(0) if f.t <= shared_until]
    long = [f for f in long_scn.states(0) if f.t <= shared_until]

    assert len(short) > 1
    assert [f.q.tolist() for f in short] == [f.q.tolist() for f in long]
    assert [f.human_pos.tolist() for f in short] == [f.human_pos.tolist() for f in long]


def test_the_person_enters_the_reachable_set_and_is_not_always_inside_it() -> None:
    """The fixture's own name-claim, checked against the envelope itself.

    `tests/test_scenarios.py` makes the same argument for the six: a fixture
    whose claim is only in its description drifts until it no longer tests what
    it says. Both halves are here because only the pair is a claim — a person
    permanently inside the reachable set and a person never inside it are both
    degenerate, and each would pass one of these on its own.

    Checked at the closest and furthest frames of a 300-frame run, at the
    ladder's own sample count. Two envelopes, not three hundred: the distances
    that pick the frames need no envelope at all.
    """
    scn = long_run(300)
    frames = tuple(scn.states(0))
    distances = [
        unary_union(link_polygons(f.proprio(), scn.world.limits)).distance(
            scn.world.human_polygon(f.human_pos)
        )
        for f in frames
    ]
    closest = frames[min(range(len(frames)), key=distances.__getitem__)]
    furthest = frames[max(range(len(frames)), key=distances.__getitem__)]

    def overlaps(frame) -> bool:
        envelope = simplify_geometry(
            compute_envelope(
                frame.proprio(),
                scn.world.limits,
                horizon=0.2,
                n_samples=bench.SCALING_N_SAMPLES,
                seed=0,
                substep_dt=0.02,
            )
        )
        overlap = envelope.intersection(scn.world.human_polygon(frame.human_pos))
        return not overlap.is_empty and overlap.area > 0.0

    assert overlaps(closest)
    assert not overlaps(furthest)


# --------------------------------------------------------------------------
# The crossover. It is the answer the scaling table exists to give, and the
# answer it must be able to give is "it does not".
# --------------------------------------------------------------------------


def test_the_crossover_is_the_smallest_measured_length_that_reaches_one() -> None:
    found = crossover(
        [_point(300, ratio=0.2), _point(3_000, ratio=0.9), _point(30_000, ratio=1.4)]
    )
    assert found.crossed_at == 30_000
    assert found.largest_measured == 30_000
    assert found.smallest_measured == 300
    assert found.fell_back_below == ()


def test_a_ratio_that_never_reaches_one_reports_no_crossover() -> None:
    """THE NEGATIVE TEST for the crossover, and the outcome issue #30 says must
    not be softened: a plateau below 1.0 answers `None`, not the largest length
    measured and not a fitted one."""
    found = crossover(
        [_point(300, ratio=0.06), _point(3_000, ratio=0.11), _point(30_000, ratio=0.12)]
    )
    assert found.crossed_at is None
    assert found.largest_measured == 30_000


def test_a_ratio_that_falls_back_below_one_is_not_reported_as_a_clean_crossing() -> None:
    found = crossover(
        [_point(300, ratio=0.5), _point(3_000, ratio=1.2), _point(30_000, ratio=0.8)]
    )
    assert found.crossed_at == 3_000
    assert found.fell_back_below == (30_000,)


def test_a_crossover_over_no_measurements_is_refused() -> None:
    """"No crossover" is a finding about the ratio. An empty ladder is the
    absence of a measurement, and the two must not print the same sentence."""
    with pytest.raises(BenchError, match="nothing to look for"):
        crossover([])


def test_the_marginal_ratio_refuses_an_artifact_that_did_not_grow() -> None:
    """Δ SQLite <= 0 over an interval is a fact about that interval. Dividing by
    it would manufacture an enormous marginal ratio and put it in a table beside
    measured ones."""
    assert bench._marginal_ratio_text(1_000, 0) == "n/a"
    assert bench._marginal_ratio_text(1_000, -5) == "n/a"
    assert bench._marginal_ratio_text(1_000, 500) == "2.00x"


# --------------------------------------------------------------------------
# The scaling section of the report.
# --------------------------------------------------------------------------


@pytest.fixture()
def ladder() -> list[ScalingPoint]:
    """Two rungs whose ratio climbs and stays well below 1.0 — the shape issue
    #30 expects if the compression argument does not hold."""
    return [
        _point(
            300,
            sizes=Sizes(raw_csv=60_000, gzip_csv=6_000, sqlite=115_000, gzip_sqlite=20_000),
        ),
        _point(
            3_000,
            sizes=Sizes(raw_csv=600_000, gzip_csv=60_000, sqlite=400_000, gzip_sqlite=90_000),
        ),
    ]


def test_the_scaling_table_carries_every_column_the_issue_asks_for(ladder: list[ScalingPoint]) -> None:
    """Issue #30: "raw CSV bytes, gzipped CSV bytes, SQLite bytes, gzipped
    SQLite bytes, node and edge counts, and the headline ratio", one row per
    measured length."""
    report = render([], sensor_multiplier=None, scaling=ladder, **_RENDER_ARGS)
    header = next(
        line for line in report.splitlines() if line.startswith("| frames | robot time |")
    )
    for column in (
        "raw CSV B",
        "gz CSV B",
        "SQLite B",
        "gz SQLite B",
        "nodes",
        "edges",
        "x gz CSV",
    ):
        assert column in header
    assert "| 300 |" in report
    assert "| 3,000 |" in report


def test_the_scaling_block_states_the_sample_count_the_ladder_ran_at(ladder: list[ScalingPoint]) -> None:
    """Issue #30: "it changes which frames count as overlapping, so the value
    used must appear in the table's parameter block"."""
    report = render([], sensor_multiplier=None, scaling=ladder, **_RENDER_ARGS)
    assert f"| envelope samples | {ladder[0].n_samples} |" in report
    # ...and the per-scenario table's value is *not* stated as though something
    # here had been measured at it, because nothing was.
    assert "| envelope samples | n/a — no table in this report was measured at it |" in report


def test_a_ladder_that_never_reaches_one_says_so_and_projects_nothing(ladder: list[ScalingPoint]) -> None:
    """THE HONEST-OUTCOME CLAUSE, in the output rather than in a commit message.
    Issue #30: "If the ratio plateaus below 1.0, say so in bench/results.md and
    in the PR body, and do not soften it"."""
    report = render([], sensor_multiplier=None, scaling=ladder, **_RENDER_ARGS)
    assert "does not reach 1.0 at any measured length" in report
    assert "No crossover is projected" in report
    assert "finding about the thesis" in report
    assert "passes 1.0 at" not in report


def test_a_ladder_that_crosses_names_the_length_it_crossed_at(ladder: list[ScalingPoint]) -> None:
    """The positive half, so the test above is not passing against a report that
    says "no crossover" whatever it is given."""
    crossing = [
        ladder[0],
        _point(
            3_000,
            ratio=None,
            sizes=Sizes(raw_csv=600_000, gzip_csv=60_000, sqlite=50_000, gzip_sqlite=20_000),
        ),
    ]
    report = render([], sensor_multiplier=None, scaling=crossing, **_RENDER_ARGS)
    assert "**The ratio passes 1.0 at 3,000 frames**" in report
    assert "does not reach 1.0 at any measured length" not in report


def test_a_ladder_that_starts_above_one_does_not_claim_a_bounded_crossing() -> None:
    """If the shortest rung already clears 1.0 there is no measured length below
    it to bound the crossing, and the report must not name a range it did not
    measure the bottom of."""
    report = render(
        [],
        sensor_multiplier=None,
        scaling=[_point(300, ratio=1.4), _point(3_000, ratio=2.0)],
        **_RENDER_ARGS,
    )
    assert "the *shortest* length measured" in report
    assert "no value for it is quoted" in report


def test_a_non_monotone_ladder_says_so_instead_of_quoting_one_crossing() -> None:
    report = render(
        [],
        sensor_multiplier=None,
        scaling=[_point(300, ratio=0.5), _point(3_000, ratio=1.2), _point(30_000, ratio=0.8)],
        **_RENDER_ARGS,
    )
    assert "not monotone in run length" in report
    assert "falls back below" in report


def test_the_control_row_is_absent_rather_than_faked_when_it_was_not_run(ladder: list[ScalingPoint]) -> None:
    report = render([], sensor_multiplier=None, scaling=ladder, **_RENDER_ARGS)
    assert "**Not measured in this run.**" in report

    control = _point(
        300,
        ratio=None,
        n_samples=512,
        sizes=Sizes(raw_csv=60_000, gzip_csv=6_000, sqlite=130_000, gzip_sqlite=22_000),
    )
    with_control = render(
        [], sensor_multiplier=None, scaling=ladder, scaling_control=control, **_RENDER_ARGS
    )
    assert "**Not measured in this run.**" not in with_control
    assert "| 300 | 512 | 130,000 |" in with_control
    # ...and the size of the reduction's effect is stated as a number, since a
    # reader comparing two rows by eye is how a 13% difference gets called
    # "about the same".
    assert "+15,000 bytes (+13.0%), +0 edges, +0 nodes" in with_control


def test_a_control_that_changed_nothing_says_zero_rather_than_going_quiet(
    ladder: list[ScalingPoint],
) -> None:
    """The measured outcome at 300 frames, and the one most easily mistaken for
    a control that never ran: the two sample counts produce the same artifact."""
    report = render(
        [],
        sensor_multiplier=None,
        scaling=ladder,
        scaling_control=_point(300, n_samples=512, sizes=ladder[0].sizes),
        **_RENDER_ARGS,
    )
    assert "+0 bytes (+0.0%), +0 edges, +0 nodes" in report
    assert "Zero is a measurement like any other" in report


def test_a_report_with_no_scaling_carries_no_scaling_section() -> None:
    """An empty section reads as a study that found nothing."""
    report = render([_result()], sensor_multiplier=None, **_RENDER_ARGS)
    assert "Ratio versus run length" not in report


def test_one_report_carries_both_tables(ladder: list[ScalingPoint]) -> None:
    """Issue #30: "`bench/results.md` gains the scaling table **alongside** the
    per-scenario one". Both sections, one file, from `--all --scaling`."""
    report = render([_result()], sensor_multiplier=None, scaling=ladder, **_RENDER_ARGS)
    assert "## Sizes and ratios" in report
    assert "## Ratio versus run length" in report
    assert "| `fixture` |" in report
    assert "| 3,000 |" in report


def test_render_still_refuses_a_report_with_nothing_in_it_at_all() -> None:
    with pytest.raises(BenchError, match="no scenarios"):
        render([], sensor_multiplier=None, scaling=[], **_RENDER_ARGS)


# --------------------------------------------------------------------------
# The scaling CLI, run for real at a length a test can afford.
# --------------------------------------------------------------------------


def test_cli_scaling_measures_the_ladder_it_was_given(tmp_path: Path) -> None:
    """`--scaling` on its own: no scenario selection, and the report is the
    ladder. Two short rungs at coarse envelope parameters — this is a test about
    the ladder being measured and reported, not about envelope fidelity."""
    out = tmp_path / "scaling.md"
    code = bench.main(
        [
            "--scaling",
            "--scaling-frames",
            "20,40",
            "--scaling-n-samples",
            "4",
            "--n-samples",
            "4",
            "--horizon",
            str(_FAST["horizon"]),
            "--substep-dt",
            str(_FAST["substep_dt"]),
            "--out",
            str(out),
            "--work-dir",
            str(tmp_path / "work"),
        ]
    )
    assert code == bench.EXIT_OK
    report = out.read_text(encoding="utf-8")
    assert "| 20 |" in report
    assert "| 40 |" in report
    assert "| lengths | 20, 40 |" in report
    # Same sample count as the per-scenario flag, so there is no reduction to
    # control for and the section says that rather than comparing a parameter
    # with itself.
    assert "**Not measured in this run.**" in report
    assert str(tmp_path) not in report


def test_cli_scaling_measures_a_control_when_the_sample_counts_differ(
    tmp_path: Path,
) -> None:
    """The ladder is cheap because `n_samples` is reduced, and the size of that
    reduction's effect is measured at one length rather than asserted."""
    out = tmp_path / "scaling.md"
    code = bench.main(
        [
            "--scaling",
            "--scaling-frames",
            "20",
            "--scaling-n-samples",
            "4",
            "--n-samples",
            "6",
            "--horizon",
            str(_FAST["horizon"]),
            "--substep-dt",
            str(_FAST["substep_dt"]),
            "--out",
            str(out),
            "--work-dir",
            str(tmp_path / "work"),
        ]
    )
    assert code == bench.EXIT_OK
    report = out.read_text(encoding="utf-8")
    assert "**Not measured in this run.**" not in report
    assert "| 20 | 6 |" in report


def test_two_runs_of_one_scaling_point_agree_on_every_byte_count(tmp_path: Path) -> None:
    """Determinism, on the rungs as much as on the scenarios: a ladder that
    moved between two runs would make the trend down it unreadable."""
    a = run_scaling_point(20, tmp_path / "a", seed=0, **_FAST)
    b = run_scaling_point(20, tmp_path / "b", seed=0, **_FAST)
    assert a.sizes == b.sizes
    assert a.result.edges == b.result.edges
    assert a.result.nodes == b.result.nodes
    assert a.frames == b.frames == 20


@pytest.mark.parametrize(
    "ladder",
    [
        pytest.param("3000,300", id="not increasing"),
        pytest.param("300,300", id="duplicated"),
        pytest.param("1", id="too short to have a frame period"),
        pytest.param("300,", id="empty entry"),
        pytest.param("300,many", id="not a number"),
    ],
)
def test_cli_refuses_a_ladder_that_is_not_one(tmp_path: Path, ladder: str) -> None:
    """A ladder out of order would turn "below 1.0 at every shorter measured
    length" into a claim about the order the lengths were typed in."""
    with pytest.raises(SystemExit) as excinfo:
        bench.main(
            ["--scaling", "--scaling-frames", ladder, "--out", str(tmp_path / "r.md")]
        )
    assert excinfo.value.code == bench.EXIT_USAGE


# --------------------------------------------------------------------------
# Hand-built results, for the report tests above. Deliberately not a live run:
# a test about what the report *says* must not depend on what the graph
# currently *measures*.
# --------------------------------------------------------------------------


def _result(**overrides) -> ScenarioResult:
    fields = {
        "scenario": "fixture",
        "frames": 100,
        "nodes": {kind: 1 for kind in store.NODE_TABLES},
        "edges": {edge_type: 2 for edge_type in store.EDGE_SPECS},
        "sizes": Sizes(raw_csv=20_000, gzip_csv=2_000, sqlite=1_000, gzip_sqlite=400),
        "check": SeparationCheck(
            verdict=AGREE,
            graph_answer=0.12,
            csv_answer=0.123,
            tolerance=DISTANCE_TOL_M,
            graph_timing=Timing(seconds=0.0002, repeats=3),
            csv_timing=Timing(seconds=0.05, repeats=3),
        ),
        "tables": {"envelope": 500, "edge": 500},
    }
    fields.update(overrides)
    return ScenarioResult(**fields)  # type: ignore[arg-type]


def _point(
    frames: int,
    *,
    ratio: float | None = None,
    sizes: Sizes | None = None,
    n_samples: int = bench.SCALING_N_SAMPLES,
) -> ScalingPoint:
    """One hand-built rung. Give it a `ratio` or a `Sizes`, not both.

    `ratio` builds a `Sizes` whose headline is exactly that number, which is
    what the crossover tests are about; `sizes` is for the report tests, where
    the individual byte columns are what is being asserted.
    """
    if (ratio is None) == (sizes is None):
        raise TypeError("_point takes exactly one of ratio= and sizes=")
    if sizes is None:
        sqlite = 100_000
        gzip_csv = int(round(float(ratio) * sqlite))
        sizes = Sizes(
            raw_csv=gzip_csv * 10,
            gzip_csv=gzip_csv,
            sqlite=sqlite,
            gzip_sqlite=sqlite // 4,
        )
    return ScalingPoint(
        result=_result(scenario=f"long_run_{frames}", frames=frames, sizes=sizes),
        n_samples=n_samples,
        frame_period_s=0.02,
    )


# --------------------------------------------------------------------------
# The resolution curve (issue #35). What evidence costs per unit of resolution.
#
# THE TWO TESTS THIS SECTION EXISTS FOR:
# `test_the_occurrence_level_cannot_answer_the_separation_timeline` and
# `test_the_contact_check_says_no_when_the_occurrence_layer_is_wrong`. The curve
# is a check like everything else here, so both halves of it are fed what they
# guard against: a level that cannot answer must say could-not-evaluate rather
# than agree, and a level that answers *wrongly* must say disagree rather than
# report a small artifact.
# --------------------------------------------------------------------------

#: The fixture the level checks run against — the one scenario that contacts,
#: because `did_contact_occur` agreeing on a run with no contact is agreement on
#: a negative and proves nothing about whether it can fail.
RESOLUTION_SCENARIO = "contact"


@pytest.fixture(scope="module")
def built(tmp_path_factory) -> tuple[Path, Path]:
    """One real build: `(csv, sqlite)`. Module-scoped, and built exactly once —
    which is also what the curve itself must do."""
    work = tmp_path_factory.mktemp("resolution")
    run_scenario(RESOLUTION_SCENARIO, work, seed=0, **_FAST)
    # `_measure` names its files after the scenario; `bench._work_paths` is the
    # one definition of that and the tests read it rather than restate it.
    return bench._work_paths(scenario(RESOLUTION_SCENARIO), work)


@pytest.fixture(scope="module")
def views(built, tmp_path_factory) -> dict[str, Path]:
    """The three views of that one build."""
    _, sqlite_path = built
    out = tmp_path_factory.mktemp("views")
    return {
        level: bench.materialize_level(sqlite_path, level, out / f"{level}.sqlite")
        for level in bench.RESOLUTION_LEVELS
    }


@pytest.fixture(scope="module")
def truth(built) -> bench.GroundTruth:
    csv_path, _ = built
    # `records=None`, written down rather than defaulted (issue #59): this
    # fixture is built by `run_scenario`, which hands `graph.build` no record
    # stream, so its Layer A ground truth genuinely does not exist. That is the
    # state the whole curve was silently in before issue #59, and the tests below
    # use it as the negative case rather than pretending it cannot happen.
    return bench.ground_truth_from_csv(
        csv_path, scenario(RESOLUTION_SCENARIO).world, records=None
    )


def _checks(view: Path, level: str, truth: bench.GroundTruth) -> dict[str, str]:
    answers = bench.answers_at_level(
        view, level, attestation=truth.attestation, keyring=None
    )
    return {
        q.name: bench.check_level(q, answers, truth).verdict
        for q in bench.RESOLUTION_QUERIES
    }


#: The Layer B half of the question set, by name. The unattested fixture above
#: can only be asked these, and saying which is which here keeps every test that
#: uses it from restating the split.
_SCENE_QUERIES = tuple(
    q.name for q in bench.RESOLUTION_QUERIES if q.layer == query.LAYER_B
)
_RECORD_QUERIES = tuple(
    q.name for q in bench.RESOLUTION_QUERIES if q.layer == query.LAYER_A
)


def test_each_view_keeps_only_what_its_level_retains(views: dict[str, Path]) -> None:
    """The three views are disjoint layers of one artifact, not three copies.

    If the occurrence view kept the edges it would cost what the edge layer
    costs, and the curve would be flat for a reason that has nothing to do with
    resolution.
    """
    def counts(path: Path) -> tuple[int, int]:
        conn = store.connect(path)
        try:
            edges = conn.execute("SELECT count(*) AS n FROM edge").fetchone()["n"]
            occ = conn.execute("SELECT count(*) AS n FROM occurrence").fetchone()["n"]
        finally:
            conn.close()
        return int(edges), int(occ)

    occurrence_edges, occurrence_rows = counts(views[bench.OCCURRENCE_LEVEL])
    transition_edges, transition_rows = counts(views[bench.TRANSITION_LEVEL])
    per_frame_edges, per_frame_rows = counts(views[bench.PER_FRAME_LEVEL])

    assert occurrence_edges == 0 and occurrence_rows > 0
    assert transition_edges > 0 and transition_rows == 0
    assert per_frame_edges > transition_edges and per_frame_rows == 0


def test_the_per_frame_view_has_a_row_per_frame_per_relationship(
    built, views: dict[str, Path]
) -> None:
    """The incremental rule run backwards: an interval asserts the relationship
    held at every frame under it, and this writes that down once per frame."""
    _, sqlite_path = built
    conn = store.connect(sqlite_path)
    try:
        frames = int(store.get_meta(conn, "frame_count"))
    finally:
        conn.close()

    conn = store.connect(views[bench.PER_FRAME_LEVEL])
    try:
        rows = store.read_edges(
            conn, edge_type="SEPARATION", dst_id=graph.HUMAN_ENTITY_ID
        )
    finally:
        conn.close()
    assert len(rows) == frames
    assert all(row["t_start"] == row["t_end"] for row in rows)


def test_the_coarser_the_level_the_fewer_the_bytes(views: dict[str, Path]) -> None:
    """The curve's shape, on a real build. Not a golden ratio — an ordering.

    A number would move with the schema; the ordering is the claim, and it is
    the one that would break if a view stopped dropping what its level discards.
    """
    sizes = {level: path.stat().st_size for level, path in views.items()}
    assert (
        sizes[bench.OCCURRENCE_LEVEL]
        < sizes[bench.TRANSITION_LEVEL]
        < sizes[bench.PER_FRAME_LEVEL]
    ), sizes


def test_the_occurrence_level_answers_the_questions_it_can(
    views: dict[str, Path], truth: bench.GroundTruth
) -> None:
    """The finding the issue exists to produce, on a fixture that contacts.

    `min_separation` and `did_contact_occur` survive two orders of magnitude of
    coarsening; the per-frame timeline and the timing of the closest approach do
    not. That is "did-contact-occur needs only occurrence resolution, the
    separation timeline needs transition resolution", measured.
    """
    assert truth.contact_occurred, (
        "precondition failed: this fixture does not contact, so agreement on "
        "did_contact_occur would be agreement on a negative."
    )
    verdicts = _checks(views[bench.OCCURRENCE_LEVEL], bench.OCCURRENCE_LEVEL, truth)
    assert verdicts["min_separation"] == AGREE
    assert verdicts["did_contact_occur"] == AGREE
    assert verdicts["separation_timeline"] == COULD_NOT_EVALUATE


@pytest.mark.parametrize(
    "level", [bench.TRANSITION_LEVEL, bench.PER_FRAME_LEVEL]
)
def test_the_edge_levels_answer_every_question(
    views: dict[str, Path], truth: bench.GroundTruth, level: str
) -> None:
    """The other end of the curve: the fine layers still agree on all four.

    This is the control. Without it, "the occurrence layer disagrees" would be
    indistinguishable from "the check disagrees with everything".

    Scene questions only — this fixture holds no record stream, and what the
    Layer A questions do on it is
    `test_a_build_with_no_record_stream_cannot_evaluate_layer_a`.
    """
    verdicts = _checks(views[level], level, truth)
    assert {verdicts[name] for name in _SCENE_QUERIES} == {AGREE}


def test_the_occurrence_level_cannot_answer_the_separation_timeline(
    views: dict[str, Path], truth: bench.GroundTruth
) -> None:
    """**COULD-NOT-EVALUATE never resolves to AGREE**, and this is where it would.

    The occurrence layer holds events, not states. A harness that scored "no
    per-frame separation" as agreement would report the coarsest level answering
    everything at a fraction of the bytes, which is the flattering wrong answer
    this whole file is written against.
    """
    answers = bench.answers_at_level(
        views[bench.OCCURRENCE_LEVEL],
        bench.OCCURRENCE_LEVEL,
        attestation=None,
        keyring=None,
    )
    assert answers.timeline is None
    query = next(
        q for q in bench.RESOLUTION_QUERIES if q.name == "separation_timeline"
    )
    check = bench.check_level(query, answers, truth)
    assert check.verdict == COULD_NOT_EVALUATE
    assert "per-frame" in check.detail


def _timing_truth(candidates: tuple[float, ...]) -> bench.GroundTruth:
    """A ground truth whose only content is when the closest approach was.

    Hand-built rather than measured, because what is under test is the *shape* of
    the comparison — how a coarse timestamp fares against the tolerance the
    artifact advertises — and a fixture would tie it to whether that particular
    run's minimum happened to last longer than a second.
    """
    return bench.GroundTruth(
        min_separation=0.2,
        t_closest_approach=candidates[0],
        closest_approach_candidates=candidates,
        timeline=tuple((t, 0.2) for t in candidates),
        contact_occurred=False,
        attestation=None,
    )


def test_the_coarse_timestamp_is_reported_as_a_disagreement() -> None:
    """**The ±1 s cost, priced.** Reported rather than tuned away.

    `TIME_TOL_S` is what the artifact advertises for interval endpoints, and a
    timestamp rounded to a whole second cannot meet it when the event it names
    did not happen on a second boundary. The issue's instruction is to report the
    divergence, so this must come out `DISAGREE` with the delta in the detail —
    not `AGREE` on the strength of the level's own coarser resolution, which
    would make the check unable to fail by construction.
    """
    query = next(
        q for q in bench.RESOLUTION_QUERIES if q.name == "time_of_closest_approach"
    )
    coarse = bench.LevelAnswers(
        min_separation=0.2,
        t_closest_approach=2.0,  # what a 1 s resolution can say about t = 2.53
        timeline=None,
        contact_occurred=False,
        attestation=None,
    )
    check = bench.check_level(query, coarse, _timing_truth((2.51, 2.53, 2.55)))
    assert check.verdict == DISAGREE
    assert "0.5100" in check.detail
    assert "tol" in check.detail


def test_an_answer_inside_the_candidate_set_agrees() -> None:
    """The other half, or the check above would be unfalsifiable in the other
    direction: an answer naming a frame the artifact cannot tell from the
    minimum is *correct*, and every frame within `DISTANCE_TOL_M` of the minimum
    is such a frame (docs/lossiness.md Unanswerable #4)."""
    query = next(
        q for q in bench.RESOLUTION_QUERIES if q.name == "time_of_closest_approach"
    )
    fine = bench.LevelAnswers(
        min_separation=0.2,
        t_closest_approach=2.55,
        timeline=None,
        contact_occurred=False,
        attestation=None,
    )
    assert (
        bench.check_level(query, fine, _timing_truth((2.51, 2.53, 2.55))).verdict
        == AGREE
    )
    # And a level that records no closest approach at all does not thereby agree.
    silent = bench.LevelAnswers(None, None, None, None, None)
    assert (
        bench.check_level(query, silent, _timing_truth((2.51,))).verdict
        == COULD_NOT_EVALUATE
    )


def test_a_sustained_minimum_is_locatable_even_at_one_second(
    views: dict[str, Path], truth: bench.GroundTruth
) -> None:
    """The measured counterpart, and it is a finding rather than a formality.

    On this fixture the robot is in contact for more than a second, so the set of
    frames the artifact cannot tell from the minimum spans a whole second and the
    ±1 s timestamp lands inside it. *When* a coarse timestamp is good enough is a
    property of the event, not of the recorder — which is exactly what a curve
    over resolution is for.
    """
    query = next(
        q for q in bench.RESOLUTION_QUERIES if q.name == "time_of_closest_approach"
    )
    assert (
        max(truth.closest_approach_candidates)
        - min(truth.closest_approach_candidates)
        > 1.0
    ), "precondition failed: the minimum is not sustained for over a second here"
    answers = bench.answers_at_level(
        views[bench.OCCURRENCE_LEVEL],
        bench.OCCURRENCE_LEVEL,
        attestation=None,
        keyring=None,
    )
    assert bench.check_level(query, answers, truth).verdict == AGREE


def test_the_contact_check_says_no_when_the_occurrence_layer_is_wrong(
    views: dict[str, Path], truth: bench.GroundTruth, tmp_path: Path
) -> None:
    """THE NEGATIVE TEST for the occurrence layer's one closed-world answer.

    "No `contact_began` row" is read as "no contact occurred", which is only
    legitimate because the artifact carries the retention rule saying one would
    have been written. So the check must catch a layer that lost the row: delete
    it and the verdict has to flip, or the coarse level would score `AGREE` for
    saying nothing at all.
    """
    tampered = tmp_path / "tampered.sqlite"
    shutil.copyfile(views[bench.OCCURRENCE_LEVEL], tampered)
    conn = store.connect(tampered)
    try:
        conn.execute("DELETE FROM occurrence WHERE type = 'contact_began'")
        conn.commit()
    finally:
        conn.close()

    query = next(q for q in bench.RESOLUTION_QUERIES if q.name == "did_contact_occur")
    answers = bench.answers_at_level(
        tampered, bench.OCCURRENCE_LEVEL, attestation=None, keyring=None
    )
    assert bench.check_level(query, answers, truth).verdict == DISAGREE


def test_a_perturbed_value_is_caught_at_every_level(
    views: dict[str, Path], truth: bench.GroundTruth, tmp_path: Path
) -> None:
    """docs/lossiness.md's "ship the negative test", applied to each view.

    One distance shifted by more than `DISTANCE_TOL_M`, at each level, in the
    column that level answers from. Every one must report `DISAGREE`.
    """
    for level, path in views.items():
        tampered = tmp_path / f"tampered_{level}.sqlite"
        shutil.copyfile(path, tampered)
        conn = store.connect(tampered)
        try:
            if level == bench.OCCURRENCE_LEVEL:
                conn.execute(
                    "UPDATE occurrence SET value = value + ? "
                    "WHERE type = 'closest_approach'",
                    (10 * DISTANCE_TOL_M,),
                )
            else:
                conn.execute(
                    "UPDATE edge SET min_distance = min_distance + ? "
                    "WHERE type = 'SEPARATION'",
                    (10 * DISTANCE_TOL_M,),
                )
            conn.commit()
        finally:
            conn.close()

        query = next(
            q for q in bench.RESOLUTION_QUERIES if q.name == "min_separation"
        )
        answers = bench.answers_at_level(
            tampered, level, attestation=None, keyring=None
        )
        assert bench.check_level(query, answers, truth).verdict == DISAGREE, level


def test_an_artifact_with_no_rows_at_a_level_could_not_evaluate(
    views: dict[str, Path], truth: bench.GroundTruth, tmp_path: Path
) -> None:
    """Silence is not agreement, one layer down. An empty view answers nothing."""
    empty = tmp_path / "empty.sqlite"
    shutil.copyfile(views[bench.TRANSITION_LEVEL], empty)
    conn = store.connect(empty)
    try:
        conn.execute("DELETE FROM edge")
        conn.commit()
    finally:
        conn.close()

    answers = bench.answers_at_level(
        empty, bench.TRANSITION_LEVEL, attestation=None, keyring=None
    )
    assert answers.min_separation is None
    # And the closed-world reading does not survive the layer it was licensed
    # by: a view with nothing in it does not thereby report "no contact
    # occurred" (issue #37 — before the query layer, this answered `False`).
    assert answers.contact_occurred is None
    verdicts = {
        q.name: bench.check_level(q, answers, truth).verdict
        for q in bench.RESOLUTION_QUERIES
    }
    assert verdicts["min_separation"] == COULD_NOT_EVALUATE
    assert verdicts["separation_timeline"] == COULD_NOT_EVALUATE
    assert verdicts["did_contact_occur"] == COULD_NOT_EVALUATE


def test_a_view_that_still_holds_a_foreign_layer_is_refused(built) -> None:
    """THE NEGATIVE TEST for the level separation, which used to be a branch.

    Since issue #37 `answers_at_level` does not know how to answer anything — it
    puts the questions to `reg.query`, and what keeps the occurrence level from
    reporting the edge layer's answers is that `materialize_level` emptied the
    edge table. So the thing that has to be checked is that the view really is
    the level it claims to be: the *unprojected* build holds both layers, and
    asking it for the occurrence level's answers must be refused rather than
    quietly answered at edge resolution.
    """
    _, sqlite_path = built
    with pytest.raises(BenchError, match="foreign|still holds rows"):
        bench.answers_at_level(
            sqlite_path,
            bench.OCCURRENCE_LEVEL,
            attestation=None,
            keyring=None,
        )


def test_the_benchmark_and_the_query_layer_answer_with_one_implementation(
    built,
) -> None:
    """Issue #37's "extract, do not duplicate", asserted.

    `min_separation_from_graph` is `reg.query.min_separation` with a timing
    wrapper; the ground-truth-from-CSV path is the *other* implementation and
    exists on purpose. If these two ever disagree, one of them has grown a
    second copy of the question.
    """
    _, sqlite_path = built
    conn = store.connect(sqlite_path)
    try:
        direct = query.min_separation(conn, graph.HUMAN_ENTITY_ID)
    finally:
        conn.close()
    assert direct.verdict != COULD_NOT_EVALUATE
    assert min_separation_from_graph(sqlite_path) == direct.value
    # One verdict vocabulary, one definition of it.
    assert COULD_NOT_EVALUATE is query.COULD_NOT_EVALUATE


@pytest.mark.parametrize("level", ["", "occurrences", "frame"])
def test_a_level_nobody_defined_is_refused(
    built, tmp_path: Path, level: str
) -> None:
    """A byte count for a view with no retention rule means nothing."""
    _, sqlite_path = built
    with pytest.raises(BenchError, match="not a resolution level"):
        bench.materialize_level(sqlite_path, level, tmp_path / "x.sqlite")
    with pytest.raises(BenchError, match="not a resolution level"):
        bench.answers_at_level(
            sqlite_path, level, attestation=None, keyring=None
        )


def test_the_curve_builds_the_graph_exactly_once(tmp_path: Path, monkeypatch) -> None:
    """Issue #35's runtime note, as an assertion rather than as a good intention.

    "The resolution curve is three views of the *same* builds, so it must not
    re-run the simulator or rebuild graphs per level." That is a correctness
    requirement as much as a cost one: three builds would differ in more than
    resolution, and the curve would not be a curve over resolution.
    """
    builds: list[object] = []
    real_build = graph.build

    def counting_build(*args, **kwargs):
        builds.append(args[0])
        return real_build(*args, **kwargs)

    monkeypatch.setattr(graph, "build", counting_build)
    curve = bench.run_resolution_curve(
        30,
        tmp_path / "work",
        seed=0,
        timing_repeats=1,
        **_FAST,
    )
    assert len(builds) == 1, builds
    assert [p.level for p in curve.points] == list(bench.RESOLUTION_LEVELS)
    assert curve.frames == 30
    assert curve.occurrence_resolution_s == graph.OCCURRENCE_TIME_RESOLUTION_S


def test_the_curve_is_deterministic(tmp_path: Path) -> None:
    """Same seed and parameters, same bytes at every level (rule 2).

    **Byte-for-byte, not merely the same length** (issue #59). The curve now
    signs a record stream, and the obvious way to do that — `reg.chain.
    generate_keyring`, which draws from OS entropy — would leave every size in
    this table identical while every MAC in the artifact differed between two
    runs of one command. A comparison of byte *counts* cannot see that, so this
    compares the files.
    """
    kwargs = {"seed": 0, "timing_repeats": 1, **_FAST}
    a = bench.run_resolution_curve(30, tmp_path / "a", **kwargs)
    b = bench.run_resolution_curve(30, tmp_path / "b", **kwargs)
    assert [p.size_bytes for p in a.points] == [p.size_bytes for p in b.points]
    assert [p.nodes for p in a.points] == [p.nodes for p in b.points]
    assert [p.records for p in a.points] == [p.records for p in b.points]
    assert a.attestation_counts == b.attestation_counts
    assert [c.verdict for p in a.points for c in p.checks] == [
        c.verdict for p in b.points for c in p.checks
    ]
    for level in bench.RESOLUTION_LEVELS:
        left = (tmp_path / "a" / "views" / f"{level}.sqlite").read_bytes()
        right = (tmp_path / "b" / "views" / f"{level}.sqlite").read_bytes()
        assert left == right, level


# --- the report ------------------------------------------------------------


def _level(level: str, **overrides) -> bench.ResolutionPoint:
    fields = {
        "level": level,
        "timestamp_resolution_s": 1.0,
        "size_bytes": 20_000,
        "nodes": 12,
        "edges": 0,
        "occurrences": 12,
        "records": 4,
        "run_seconds": 60.0,
        "checks": tuple(
            bench.LevelCheck(query=q.name, verdict=AGREE, detail="0.1 vs 0.1")
            for q in bench.RESOLUTION_QUERIES
        ),
    }
    fields.update(overrides)
    return bench.ResolutionPoint(**fields)  # type: ignore[arg-type]


#: A hand-built Layer A ground truth for the render tests. Hand-built for the
#: same reason `_timing_truth` is: what is under test is the *shape* of the
#: report — that the coverage fraction, the price column and the Layer A finding
#: all render — and a measured fixture would tie those assertions to what one
#: run's policy happened to declare.
_ATTESTATION_TRUTH = bench.AttestationTruth(
    declaration_count=12,
    verdict_count=300,
    fault_count=15,
    t_probe=3.0,
    declared_at_probe=(("d-5", 5, 2.5, 0.5, "retract"),),
    violations=(("v-0", 0, 0.0, "CLAMP", "declaration_action_mismatch", "d-0"),),
    probe_declaration_id="d-0",
    adjudications_of_probe=(
        ("v-0", 0, 0.0, "CLAMP", "declaration_action_mismatch", True),
    ),
)


def _curve(points=None, **overrides) -> bench.ResolutionCurve:
    fields = {
        "scenario": "long_run_3000",
        "frames": 3_000,
        "frame_period_s": 0.02,
        "n_samples": 16,
        "occurrence_resolution_s": 1.0,
        "source": _result(scenario="long_run_3000", frames=3_000),
        "truth": bench.GroundTruth(
            min_separation=0.2,
            t_closest_approach=1.0,
            closest_approach_candidates=(1.0,),
            timeline=((0.0, 0.2),),
            contact_occurred=True,
            attestation=_ATTESTATION_TRUTH,
        ),
        "points": tuple(
            points
            if points is not None
            else [_level(name) for name in bench.RESOLUTION_LEVELS]
        ),
        "replan_interval_s": bench.RESOLUTION_REPLAN_INTERVAL_S,
        "declaration_horizon_s": bench.RESOLUTION_DECLARATION_HORIZON_S,
        "watchdog_period_s": bench.RESOLUTION_WATCHDOG_PERIOD_S,
    }
    fields.update(overrides)
    return bench.ResolutionCurve(**fields)  # type: ignore[arg-type]


def test_bytes_per_hour_is_the_headline_and_no_csv_ratio_appears() -> None:
    """Issue #35: "do not report a ratio against the CSV as the headline. Report
    bytes/hour and the agreement column."

    docs/plan.md Claim 1 forbids quoting a ratio against the stream while the
    measured one is below 1, so the table must not carry one at all — a column
    nobody is allowed to quote is a column that gets quoted.
    """
    report = render(
        [], sensor_multiplier=None, resolution=_curve(), **_RENDER_ARGS
    )
    header = next(
        line for line in report.splitlines() if line.startswith("| level |")
    )
    for column in ("bytes/hour", "SQLite B", "nodes", "edges", "occurrences"):
        assert column in header
    for query in bench.RESOLUTION_QUERIES:
        assert query.name in header
    # The ratio columns the rest of the report uses must not be in this one.
    assert "x gz CSV" not in header
    assert "x raw" not in header


def test_the_resolution_table_carries_a_verdict_per_level_and_query() -> None:
    """The column that decides it. A size table with no agreement column would
    report a smaller artifact and say nothing about whether it still works."""
    points = [
        _level(bench.OCCURRENCE_LEVEL, checks=(
            bench.LevelCheck("min_separation", AGREE, "0.1 vs 0.1"),
            bench.LevelCheck("separation_timeline", COULD_NOT_EVALUATE, "no rows"),
        )),
        _level(bench.TRANSITION_LEVEL),
    ]
    report = render(
        [], sensor_multiplier=None, resolution=_curve(points), **_RENDER_ARGS
    )
    assert COULD_NOT_EVALUATE in report
    assert "no rows" in report


def test_a_level_that_could_not_evaluate_does_not_summarise_as_agree() -> None:
    """The third verdict never resolves to the first, and a wrong answer outranks
    a missing one — otherwise a broken level would read as a merely partial one."""
    agreeing = _level("x", checks=(bench.LevelCheck("q", AGREE, ""),))
    silent = _level("x", checks=(
        bench.LevelCheck("q", AGREE, ""),
        bench.LevelCheck("r", COULD_NOT_EVALUATE, ""),
    ))
    wrong = _level("x", checks=(
        bench.LevelCheck("q", DISAGREE, ""),
        bench.LevelCheck("r", COULD_NOT_EVALUATE, ""),
    ))
    assert agreeing.verdict == AGREE
    assert silent.verdict == COULD_NOT_EVALUATE
    assert wrong.verdict == DISAGREE
    assert _level("x", checks=()).verdict == COULD_NOT_EVALUATE


def test_the_report_says_the_per_frame_view_is_a_lower_bound() -> None:
    """It expands the intervals; it cannot restore the nodes issue #29 removed.
    A reader must not read that row as what a per-frame artifact costs."""
    report = render(
        [], sensor_multiplier=None, resolution=_curve(), **_RENDER_ARGS
    )
    assert "lower bound" in report


def test_a_report_with_no_resolution_curve_carries_no_such_section() -> None:
    """Absent rather than empty, like the scaling section and the projection."""
    report = render([_result()], sensor_multiplier=None, **_RENDER_ARGS)
    assert "## What resolution costs" not in report


def test_a_curve_with_no_points_is_refused() -> None:
    """An empty curve would read as "no level answered anything", which is a
    finding. This is the absence of a measurement."""
    with pytest.raises(BenchError, match="no points"):
        render([], sensor_multiplier=None, resolution=_curve([]), **_RENDER_ARGS)


def test_a_run_of_no_duration_has_no_hourly_rate() -> None:
    """A rate over zero seconds is a division by zero, not an infinite rate."""
    with pytest.raises(BenchError, match="division by zero"):
        _level("x", run_seconds=0.0).bytes_per_hour


def test_bytes_per_hour_is_the_size_scaled_by_the_run_length() -> None:
    """Hand-worked: 20 kB over 60 s is 1.2 MB/h, and nothing else."""
    point = _level("x", size_bytes=20_000, run_seconds=60.0)
    assert point.bytes_per_hour == pytest.approx(20_000 * 3600 / 60)


def test_cli_resolution_writes_the_curve(tmp_path: Path) -> None:
    """The issue's verification command, at a length a test can afford."""
    out = tmp_path / "resolution.md"
    code = bench.main(
        [
            "--resolution",
            "--resolution-frames",
            "30",
            "--resolution-n-samples",
            str(_FAST["n_samples"]),
            "--horizon",
            str(_FAST["horizon"]),
            "--substep-dt",
            str(_FAST["substep_dt"]),
            "--out",
            str(out),
            "--work-dir",
            str(tmp_path / "work"),
        ]
    )
    assert code == bench.EXIT_OK
    report = out.read_text(encoding="utf-8")
    assert "## What resolution costs" in report
    for level in bench.RESOLUTION_LEVELS:
        assert f"| `{level}` |" in report
    # Nothing that varies between two runs of the same command may reach it.
    assert str(tmp_path) not in report


def test_cli_resolution_does_not_fail_on_its_own_finding(tmp_path: Path) -> None:
    """The exit code must not gate on the per-level verdicts.

    The occurrence level disagreeing about *when* the closest approach happened
    is the measurement, not a regression. A command that exited non-zero on its
    own finding would push the next person to tune the finding away — which is
    the one thing issue #35 says not to do.
    """
    out = tmp_path / "resolution.md"
    code = bench.main(
        [
            "--resolution",
            "--resolution-frames",
            "30",
            "--resolution-n-samples",
            str(_FAST["n_samples"]),
            "--horizon",
            str(_FAST["horizon"]),
            "--substep-dt",
            str(_FAST["substep_dt"]),
            "--out",
            str(out),
            "--work-dir",
            str(tmp_path / "work"),
        ]
    )
    assert code == bench.EXIT_OK
    assert DISAGREE in out.read_text(encoding="utf-8"), (
        "no level disagreed at this length, so this run does not show that the "
        "exit code is independent of the per-level verdicts. Pick a fixture or a "
        "resolution where they diverge rather than deleting the assertion."
    )


# --------------------------------------------------------------------------
# LAYER A IN THE CURVE (issue #59).
#
# THE TESTS THIS SECTION EXISTS FOR:
# `test_the_measured_build_carries_a_non_zero_layer_a` and the four negative
# tests under it. The bug this section was written against is silently-zero —
# `_measure` never passed `records=`, so the artifact every published number came
# from held no declaration, no verdict, no fault and no chain, and nothing said
# so. A zero is invisible in a byte column, so the counts are asserted directly;
# and a check that has only ever seen a healthy artifact has not been shown able
# to fail, so each of the four record questions is fed the condition it guards
# against.
# --------------------------------------------------------------------------

#: Long enough for the fixture to emit several declarations, several hundred
#: verdicts and a non-zero number of faults, and short enough to build inside a
#: test. Not a golden number: what the assertions below check is that each count
#: is non-zero, never what it is.
ATTESTED_FRAMES = 120


@pytest.fixture(scope="module")
def attested(tmp_path_factory) -> tuple[bench.ResolutionCurve, Path, dict[str, Path]]:
    """One real attested curve: `(curve, artifact, views)`. Built once.

    The curve's own views are on disk where `run_resolution_curve` left them, so
    the tampering tests copy those rather than re-materializing — a second
    projection would be a second artifact and the comparison would be against a
    file the curve never measured.
    """
    work = tmp_path_factory.mktemp("attested")
    curve = bench.run_resolution_curve(
        ATTESTED_FRAMES, work, seed=0, timing_repeats=1, **_FAST
    )
    _, sqlite_path = bench._work_paths(long_run(ATTESTED_FRAMES), work)
    views = {
        level: work / "views" / f"{level}.sqlite"
        for level in bench.RESOLUTION_LEVELS
    }
    return curve, sqlite_path, views


def _record_checks(
    view: Path, level: str, curve: bench.ResolutionCurve
) -> dict[str, bench.LevelCheck]:
    """Every Layer A check at one level, keyed by query name."""
    answers = bench.answers_at_level(
        view,
        level,
        attestation=curve.truth.attestation,
        keyring=bench.measurement_keyring(0),
    )
    return {
        q.name: bench.check_level(q, answers, curve.truth)
        for q in bench.RESOLUTION_QUERIES
        if q.name in _RECORD_QUERIES
    }


def test_the_measured_build_carries_a_non_zero_layer_a(attested) -> None:
    """**THE TEST THIS ISSUE EXISTS FOR.** Every Layer A count must be non-zero.

    Before issue #59 all four were zero and the report said nothing, because
    `_measure` called `graph.build` without `records=` and a build handed no
    record stream is indistinguishable in a byte count from a run that produced
    none. A test that only checked the report renders would have passed
    throughout. This one fails on zero, which is the only thing that stops it
    happening again.
    """
    curve, artifact, _ = attested
    counts = curve.attestation_counts
    for name in ("declarations", "verdicts", "faults", "chain_records"):
        assert counts[name] > 0, (
            f"{name} is zero in the artifact the resolution curve measured. That "
            "is the bug issue #59 exists to fix: Layer A absent from every number "
            "the curve publishes, with nothing saying so."
        )
    # And the rows really are in the file, not only in the ground truth: the
    # counts above come from the emitted stream, and a build that dropped them on
    # the way in would still satisfy them.
    conn = store.connect(artifact)
    try:
        assert query.attestation_state(conn) == "present"
        nodes = store.node_counts(conn)
    finally:
        conn.close()
    assert nodes["Declaration"] == counts["declarations"]
    assert nodes["Verdict"] == counts["verdicts"]


def test_the_fixture_declares_a_box_it_never_leaves_and_is_still_refused(
    attested,
) -> None:
    """The fixture's fault is a real one, and it is the one it claims.

    `reg.scenarios.LONG_RUN_DECLARED_Q_BOUNDS` contains every configuration the
    run commands, so the policy's claim about *where the arm is* is true at every
    frame. The faults come from the reachable set over the declaration's horizon
    leaving that box — which is `declaration_action_mismatch` and nothing else. A
    fixture producing some other fault would be measuring a different run than
    the one its docstring describes.
    """
    curve, _, _ = attested
    faults = {v[4] for v in curve.truth.attestation.violations}
    assert faults == {long_run(ATTESTED_FRAMES).fault} == {
        "declaration_action_mismatch"
    }
    assert all(
        v[3] != "PERMIT" for v in curve.truth.attestation.violations
    ), "a PERMIT is not a violation"


def test_every_layer_a_question_agrees_at_the_edge_levels(attested) -> None:
    """The control for the four negative tests below.

    Without it, "the tampered view disagrees" would be indistinguishable from
    "this check disagrees with everything", which is the failure mode a harness
    that has only ever been run against a broken artifact has.
    """
    curve, _, views = attested
    for level in (bench.TRANSITION_LEVEL, bench.PER_FRAME_LEVEL):
        checks = _record_checks(views[level], level, curve)
        assert {c.verdict for c in checks.values()} == {AGREE}, (level, checks)


def test_a_build_with_no_record_stream_cannot_evaluate_layer_a(
    views: dict[str, Path], truth: bench.GroundTruth
) -> None:
    """**COULD-NOT-EVALUATE never resolves to AGREE**, for the record questions.

    The `contact` fixture is built by `run_scenario`, which passes
    `records=None`. Every Layer A question over it has to come back
    could-not-evaluate at every level — not `AGREE` on the strength of an empty
    record table, which is exactly what a closed-world read of a table nobody
    wrote to would produce.
    """
    for level in bench.RESOLUTION_LEVELS:
        verdicts = _checks(views[level], level, truth)
        for name in _RECORD_QUERIES:
            assert verdicts[name] == COULD_NOT_EVALUATE, (level, name)


def _tamper(view: Path, out: Path, sql: str, params: tuple = ()) -> Path:
    """A copy of one view with one statement run against it."""
    shutil.copyfile(view, out)
    conn = store.connect(out)
    try:
        conn.execute(sql, params)
        conn.commit()
    finally:
        conn.close()
    return out


def test_declared_bound_says_no_when_the_declarations_are_wrong(
    attested, tmp_path: Path
) -> None:
    """THE NEGATIVE TEST for "every Declaration, in full".

    Two ways it must be able to say no, and they are different findings: a
    declaration whose *field* was altered is a level answering wrongly, and a
    declaration whose region the level no longer holds is a level that cannot
    answer. Neither may come back `AGREE`.
    """
    curve, _, views = attested
    level = bench.TRANSITION_LEVEL

    altered = _tamper(
        views[level],
        tmp_path / "altered.sqlite",
        "UPDATE declaration SET horizon = horizon + 10.0",
    )
    assert (
        _record_checks(altered, level, curve)["declared_bound"].verdict == DISAGREE
    )

    # And the same question with the claimed region removed. `reg.query` refuses
    # rather than reporting a declaration with no bound, and the check must carry
    # that refusal through as could-not-evaluate rather than scoring the fields
    # it can still see.
    regionless = _tamper(
        views[level],
        tmp_path / "regionless.sqlite",
        "DELETE FROM edge WHERE type = 'DECLARED'",
    )
    assert _record_checks(regionless, level, curve)["declared_bound"].verdict == (
        COULD_NOT_EVALUATE
    )


def test_violations_says_no_when_a_fault_is_dropped_or_reattributed(
    attested, tmp_path: Path
) -> None:
    """THE NEGATIVE TEST for "every fault, with full attribution".

    docs/lossiness.md gives this question exact set equality — "a missed or
    invented fault is a failure" — so a level that lost one refused action, and a
    level that kept every fault code but forgot which declaration it was raised
    against, both have to say no. The second is the one a check comparing fault
    codes alone would miss.
    """
    curve, _, views = attested
    level = bench.TRANSITION_LEVEL

    dropped = _tamper(
        views[level],
        tmp_path / "dropped.sqlite",
        "DELETE FROM verdict WHERE fault IS NOT NULL AND seq = "
        "(SELECT min(seq) FROM verdict WHERE fault IS NOT NULL)",
    )
    assert _record_checks(dropped, level, curve)["violations"].verdict == DISAGREE

    unattributed = _tamper(
        views[level],
        tmp_path / "unattributed.sqlite",
        "UPDATE verdict SET declaration_key = NULL WHERE fault IS NOT NULL",
    )
    assert (
        _record_checks(unattributed, level, curve)["violations"].verdict == DISAGREE
    )


def test_verdicts_says_no_when_an_adjudication_or_its_bound_is_lost(
    attested, tmp_path: Path
) -> None:
    """THE NEGATIVE TEST for "every Verdict, in full".

    An altered field is a wrong answer; a lost clamped bound is a missing one.
    The two get different verdicts on purpose — collapsing them would let a level
    that quietly dropped the region a clamp applied score `AGREE` on a question
    whose whole predicate is "in full".

    The altered field is `t` and not `outcome` because the schema refuses to hold
    a CLAMP with no clamped envelope — which is the store doing its job, and
    means an outcome cannot be edited in isolation at all.
    """
    curve, _, views = attested
    level = bench.TRANSITION_LEVEL

    altered = _tamper(
        views[level],
        tmp_path / "instant.sqlite",
        "UPDATE verdict SET t = t + 1.0",
    )
    assert _record_checks(altered, level, curve)["verdicts"].verdict == DISAGREE

    boundless = _tamper(
        views[level],
        tmp_path / "boundless.sqlite",
        "DELETE FROM edge WHERE type = 'ENFORCED'",
    )
    check = _record_checks(boundless, level, curve)["verdicts"]
    assert check.verdict == COULD_NOT_EVALUATE
    assert "clamped envelope" in check.detail


def test_the_chain_check_says_no_when_the_record_is_truncated_or_altered(
    attested, tmp_path: Path
) -> None:
    """THE NEGATIVE TEST for "the complete hash chain". Two artifacts, two ways.

    An altered field breaks a MAC and a removed record leaves a dangling
    `FOLLOWS` link; the walk reports both, and this check must carry them through
    as `DISAGREE` rather than reading "a chain came back" as a chain that
    verified.
    """
    curve, _, views = attested
    level = bench.TRANSITION_LEVEL

    forged = _tamper(
        views[level],
        tmp_path / "forged.sqlite",
        "UPDATE declaration SET horizon = horizon + 1.0 WHERE seq = 0",
    )
    assert _record_checks(forged, level, curve)["verify_chain"].verdict == DISAGREE

    truncated = _tamper(
        views[level],
        tmp_path / "truncated.sqlite",
        "DELETE FROM verdict WHERE seq = (SELECT max(seq) FROM verdict)",
    )
    check = _record_checks(truncated, level, curve)["verify_chain"]
    assert check.verdict == DISAGREE
    assert "BROKEN" in check.detail


def test_a_chain_that_verified_over_a_short_record_is_still_a_disagreement(
    attested,
) -> None:
    """Why the emitted lengths are in this predicate and not just `VERIFIED`.

    `reg.chain` walks what the artifact holds and checks it against the
    artifact's own stated count and its own `FOLLOWS` links, so on a real file a
    truncation is caught three times over — which is why the test above cannot
    produce this state without dismantling the artifact. The state is still worth
    guarding: the number of records the *run emitted* is the only one that does
    not come from the file, and a walk that came back verified over fewer than
    that has verified a record with something missing from it. Fed directly,
    because a check is a function and this is the input it must say no to.
    """
    curve, _, _ = attested
    truth = curve.truth
    spec = next(q for q in bench.RESOLUTION_QUERIES if q.name == "verify_chain")
    short = bench.AttestationAnswers(
        declared_at_probe=None,
        declared_regions_present=None,
        violations=None,
        adjudications_of_probe=None,
        chain=(
            "VERIFIED",
            truth.attestation.declaration_count,
            truth.attestation.verdict_count - 1,
        ),
    )
    check = bench.check_level(
        spec,
        bench.LevelAnswers(None, None, None, None, short),
        truth,
    )
    assert check.verdict == DISAGREE
    assert "truncated" in check.detail
    # And the whole record, verified, is the control: without it the assertion
    # above would hold for a check that disagreed with everything.
    whole = dataclasses.replace(
        short,
        chain=(
            "VERIFIED",
            truth.attestation.declaration_count,
            truth.attestation.verdict_count,
        ),
    )
    assert (
        bench.check_level(
            spec, bench.LevelAnswers(None, None, None, None, whole), truth
        ).verdict
        == AGREE
    )


def test_the_chain_walked_without_a_key_is_not_a_chain_that_verified(
    attested,
) -> None:
    """A MAC nobody checked is unchecked, not valid.

    `reg.chain.verify_chain(conn, None)` comes back COULD-NOT-EVALUATE with its
    links walked, and this check must carry that through rather than scoring the
    record counts it can still see. It is the same rule as everywhere else here,
    applied to the one question that takes a key.
    """
    curve, _, views = attested
    answers = bench.answers_at_level(
        views[bench.TRANSITION_LEVEL],
        bench.TRANSITION_LEVEL,
        attestation=curve.truth.attestation,
        keyring=None,
    )
    spec = next(q for q in bench.RESOLUTION_QUERIES if q.name == "verify_chain")
    assert (
        bench.check_level(spec, answers, curve.truth).verdict == COULD_NOT_EVALUATE
    )


def test_the_per_frame_view_does_not_duplicate_the_record_edges(attested) -> None:
    """The per-frame expansion restates relationships, not records.

    A `DECLARED` edge spans a validity window and a `FOLLOWS` edge links two
    records; neither asserts anything "at every frame", so expanding them would
    return one declaration 26 times and make the per-frame level look like it
    answers `declared_bound` wrongly — a finding about this view's construction
    wearing the label of a finding about resolution.
    """
    counts = {}
    for level in (bench.TRANSITION_LEVEL, bench.PER_FRAME_LEVEL):
        conn = store.connect(attested[2][level])
        try:
            counts[level] = {
                str(row["type"]): int(row["n"])
                for row in conn.execute(
                    "SELECT type, count(*) AS n FROM edge GROUP BY type"
                )
            }
        finally:
            conn.close()
    for record_edge in ("DECLARED", "ADJUDICATED", "ENFORCED", "FOLLOWS"):
        assert counts[bench.PER_FRAME_LEVEL].get(record_edge, 0) == counts[
            bench.TRANSITION_LEVEL
        ].get(record_edge, 0), record_edge
    # And the relationship edges *are* expanded, or the assertion above would
    # hold for a view that expanded nothing at all.
    assert (
        counts[bench.PER_FRAME_LEVEL]["SEPARATION"]
        > counts[bench.TRANSITION_LEVEL]["SEPARATION"]
    )


def test_the_measurement_keyring_is_a_function_of_the_seed(tmp_path: Path) -> None:
    """Same seed, same key material; different seed, different (rule 2).

    The curve's artifact has to be byte-reproducible, which a keyring from OS
    entropy would prevent. What this must not become is a keyring shared across
    seeds — key material that does not vary with the run is one step closer to
    looking like a real one.
    """
    a = bench.measurement_keyring(0)
    b = bench.measurement_keyring(0)
    other = bench.measurement_keyring(1)
    material = lambda k: tuple(key.material for key in k.keys)  # noqa: E731
    assert material(a) == material(b)
    assert material(a) != material(other)
    # Both roles, and they are not the same bytes: one key doing both jobs would
    # make the two chains forgeable from each other even in a measurement.
    assert len({key.material for key in a.keys}) == 2
    with pytest.raises(BenchError, match="must be an int"):
        bench.measurement_keyring(0.5)  # type: ignore[arg-type]


# --- coverage --------------------------------------------------------------


def test_every_supported_question_is_in_exactly_one_bucket() -> None:
    """The denominator is the whole supported set, with no question named twice.

    Coverage as a fraction is only meaningful if the denominator is the document
    it claims to be counting. A duplicate row would make the fraction wrong in
    the flattering direction.
    """
    names = [q.name for q in bench.SUPPORTED_QUESTIONS]
    assert len(names) == len(set(names)) == 9
    assert all(
        q.status in (bench.PRICED, bench.EXCLUDED) for q in bench.SUPPORTED_QUESTIONS
    )
    priced, total = bench.coverage()
    assert total == len(names)
    assert 0 < priced < total, (
        "coverage is either total or zero, which means the table below stopped "
        "distinguishing a priced question from an excluded one"
    )


def test_a_priced_question_is_one_the_table_actually_asks() -> None:
    """A `PRICED` row nobody asks is the omission this block exists to prevent,
    wearing the label of its own fix."""
    asked = {q.name for q in bench.RESOLUTION_QUERIES}
    for question in bench.SUPPORTED_QUESTIONS:
        if question.status == bench.PRICED:
            assert question.name in asked, question.name


def test_an_excluded_question_carries_a_reason_and_is_not_a_pass() -> None:
    """`EXCLUDED` is a could-not-evaluate. It must never render as `AGREE`."""
    with pytest.raises(BenchError, match="no reason"):
        bench.SupportedQuestion(
            name="x", layer=query.LAYER_B, status=bench.EXCLUDED, reason=""
        )
    with pytest.raises(BenchError, match="not a coverage status"):
        bench.SupportedQuestion(
            name="x", layer=query.LAYER_B, status=AGREE, reason="because"
        )
    excluded = [q for q in bench.SUPPORTED_QUESTIONS if q.status == bench.EXCLUDED]
    assert excluded, "nothing is excluded, so this assertion checks nothing"
    assert all(q.status != AGREE for q in excluded)


def test_the_report_states_coverage_as_a_fraction_of_the_supported_set() -> None:
    """Five silently-omitted questions under a row reading AGREE reads as full
    coverage, so the fraction and every exclusion are in the report itself."""
    report = render([], sensor_multiplier=None, resolution=_curve(), **_RENDER_ARGS)
    priced, total = bench.coverage()
    assert f"**{priced} of {total}**" in report
    for question in bench.SUPPORTED_QUESTIONS:
        assert f"`{question.name}`" in report
        if question.status == bench.EXCLUDED:
            assert question.reason.split(".")[0][:40] in report, question.name
    assert bench.EXCLUDED in report
    # The two Retained clauses that are not questions are mentioned rather than
    # silently left out of the denominator.
    for clause, _ in bench.RETAINED_CLAUSES_NOT_IN_THE_QUESTION_SET:
        assert clause in report


def test_the_report_says_what_each_level_loses(attested) -> None:
    """The 12x is only a finding with a price attached, so the price is a column.

    Measured rather than hand-built: what has to appear is the name of a question
    a real level really loses, and a fabricated point could carry any name at all.
    """
    curve, _, _ = attested
    report = render([], sensor_multiplier=None, resolution=curve, **_RENDER_ARGS)
    assert "what you lose" in report
    lossy = [p for p in curve.points if p.lost]
    assert lossy, "no level lost anything, so this run prices nothing"
    for name in lossy[0].lost:
        assert f"`{name}`" in report
    assert "x smaller" in report
    # A level that loses nothing says so rather than leaving the cell blank.
    assert any(not p.lost for p in curve.points)
    assert "nothing in this table" in report


def test_the_layer_a_finding_is_stated_rather_than_left_to_be_inferred() -> None:
    """Both branches, because the report has to say something either way.

    "The certifiable layer is retained in full at every level" is a result, and
    so is "it is not, and here is where it is lost". Four identical rows of
    verdicts are neither.
    """
    intact = _curve()
    assert intact.layer_a_is_resolution_independent
    report = render([], sensor_multiplier=None, resolution=intact, **_RENDER_ARGS)
    assert "retained in full at every level" in report

    lossy_point = _level(
        bench.OCCURRENCE_LEVEL,
        checks=tuple(
            bench.LevelCheck(
                query=q.name,
                verdict=COULD_NOT_EVALUATE if q.name == "declared_bound" else AGREE,
                detail="",
            )
            for q in bench.RESOLUTION_QUERIES
        ),
    )
    lossy = _curve([lossy_point, _level(bench.TRANSITION_LEVEL)])
    assert not lossy.layer_a_is_resolution_independent
    report = render([], sensor_multiplier=None, resolution=lossy, **_RENDER_ARGS)
    assert "not* fully resolution-independent" in report
    assert "`declared_bound`" in report


def test_a_curve_with_no_record_stream_claims_nothing_about_layer_a() -> None:
    """Absence is reported as absence. A curve that measured no Layer A has not
    shown that Layer A survives coarsening — it has shown nothing about it."""
    curve = _curve(truth=bench.GroundTruth(0.2, 1.0, (1.0,), ((0.0, 0.2),), True, None))
    assert not curve.layer_a_is_resolution_independent
    assert curve.attestation_counts == {
        "declarations": 0,
        "verdicts": 0,
        "faults": 0,
        "chain_records": 0,
    }
    report = render([], sensor_multiplier=None, resolution=curve, **_RENDER_ARGS)
    assert "Nothing is claimed about Layer A here" in report


def test_the_report_prints_the_record_parameterisation(attested) -> None:
    """Which replan rate, horizon and watchdog produced these record counts.

    Every one of the three decides how much of the fault taxonomy can fire at
    all, so a table of record counts that did not say which values produced them
    would be a measurement nobody could reproduce — and the keyring line is there
    so nobody reads the chain column as a verified provenance.
    """
    curve, _, _ = attested
    report = render([], sensor_multiplier=None, resolution=curve, **_RENDER_ARGS)
    assert f"{curve.replan_interval_s} s" in report
    assert "measurement_keyring" in report
    assert "attest to nothing" in report
    for name, count in curve.attestation_counts.items():
        assert f"{count:,}" in report, name
