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

from reg import bench, store
from reg.bench import (
    AGREE,
    COULD_NOT_EVALUATE,
    DISAGREE,
    MET,
    NOT_MET,
    BenchError,
    ScenarioResult,
    SeparationCheck,
    Sizes,
    Timing,
    agreement,
    claim_verdict,
    compression_ratio,
    gzip_bytes,
    min_separation_from_graph,
    render,
    run_scenario,
    sensor_projection_bytes,
)
from reg.scenarios import SCENARIOS
from reg.tolerances import DISTANCE_TOL_M

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
