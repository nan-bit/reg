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

from pathlib import Path

import pytest
from shapely.ops import unary_union

from reg import bench, graph, store
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
_FAST = {"horizon": 0.05, "n_samples": 4, "envelope_seed": 0, "substep_dt": 0.05}

#: One scenario, the shortest that still has a human moving through the scene.
SCENARIO = "near_miss"

_RENDER_ARGS = {
    "seed": 0,
    "horizon": 0.2,
    "n_samples": 512,
    "envelope_seed": 0,
    "substep_dt": 0.02,
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
                    envelope_seed=11, substep_dt=0.02)
    assert "| simulator seed | 3 |" in report
    assert "| envelope seed | 11 |" in report
    assert "| envelope horizon | 0.2 s |" in report
    assert "| envelope samples | 512 |" in report
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
