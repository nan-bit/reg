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

import argparse
import ast
import concurrent.futures
import dataclasses
import functools
import re
import shutil
import threading
from pathlib import Path

import pytest
from shapely.ops import unary_union

from reg import bench, graph, query, scenarios, store
from reg.bench import (
    AGREE,
    COLUMN_RULES,
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
    column_layer,
    compression_ratio,
    crossover,
    gzip_bytes,
    min_separation_from_graph,
    proprioceptive_columns,
    render,
    run_scaling_point,
    run_scenario,
    sensor_projection_bytes,
)
from reg.envelope import compute_envelope
from reg.kinematics import ORIGIN_FRAME, link_polygons
from reg.scenarios import SCENARIOS, long_run, scenario
from reg.stream import expected_header
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
# The Layer A / Layer B column split, and the column it has no rule for.
#
# `proprioceptive_columns` decides which columns of the raw stream the incumbent
# comparison is priced over. Before issue #137 its rule was `c == "t" or
# c.startswith(("q_", "qd_"))` and every other column fell through to Layer B —
# so there was no header it could refuse, because the fall-through *was* a
# classification. These tests are in two halves: the split it computes today
# does not move, and a column it has no rule for is refused by name.
# --------------------------------------------------------------------------

#: The fixture Claim 1's published figures are priced on: two joints, three
#: obstacles, 24 columns, five of them proprioceptive.
PRICED_HEADER = expected_header(2, 3)


def test_every_column_of_the_priced_header_is_classifiable() -> None:
    """The 24 columns of the priced fixture all have a rule, so no published
    figure moves. If this fails the rule set lost a rule, not the schema."""
    assert len(PRICED_HEADER) == 24
    for column in PRICED_HEADER:
        assert column_layer(column) in {query.LAYER_A, query.LAYER_B}


def test_the_split_is_the_one_the_published_figures_were_measured_over() -> None:
    """Five proprioceptive columns, 19 Layer B, in header order — the split
    `docs/sensor-baseline.md` and the README quote. The rule set replaced a
    predicate; it must not have replaced the answer."""
    prop = proprioceptive_columns(PRICED_HEADER)
    assert prop == ["t", "q_0", "q_1", "qd_0", "qd_1"]
    assert len([c for c in PRICED_HEADER if c not in prop]) == 19


@pytest.mark.parametrize(
    ("n_joints", "n_obstacles"), [(0, 0), (1, 0), (2, 3), (6, 1), (7, 12)]
)
def test_the_rule_set_covers_the_schema_at_every_shape(
    n_joints: int, n_obstacles: int
) -> None:
    """The rule set is checked against `reg.stream.expected_header` rather than
    against a copy of it, so a column added to the schema fails here — which is
    the whole point of the refusal being possible at all."""
    header = expected_header(n_joints, n_obstacles)
    prop = proprioceptive_columns(header)
    assert len(prop) == 1 + 2 * n_joints
    assert set(prop) <= set(header)


def test_each_column_is_matched_by_exactly_one_rule() -> None:
    """Two rules matching one column would make the answer depend on their order
    in the tuple, which is not a property anyone editing the data would check."""
    for column in expected_header(3, 2):
        matched = [rule for rule in COLUMN_RULES if rule.matches(column)]
        assert len(matched) == 1, f"{column!r} matched {len(matched)} rules"


def test_every_rule_names_a_layer_and_says_what_the_column_is() -> None:
    """The rule set is data, so the data has to be well-formed: a rule with an
    empty `what` is a rule nobody can review."""
    assert COLUMN_RULES
    for rule in COLUMN_RULES:
        assert rule.layer in {query.LAYER_A, query.LAYER_B}
        assert rule.what.strip()


# --- the negative half: a column with no rule -------------------------------


def test_a_header_with_an_unknown_column_is_refused() -> None:
    """**The negative test.** A mobile base's pose column is neither `q_` nor
    `qd_`; under the old predicate it was counted as Layer B, silently moving
    the split Claim 1's comparison is computed over."""
    header = ["t", "q_0", "qd_0", "base_x", "human_x", "human_y", "human_vx", "human_vy"]
    with pytest.raises(BenchError, match="base_x"):
        proprioceptive_columns(header)


def test_the_refusal_does_not_resolve_to_layer_b() -> None:
    """The old behaviour is the thing being ruled out, so assert it directly:
    the unknown column must not come back as a Layer B answer."""
    with pytest.raises(BenchError):
        proprioceptive_columns(["t", "odom_theta"])
    with pytest.raises(BenchError, match="odom_theta"):
        column_layer("odom_theta")


def test_every_unknown_column_is_named_not_only_the_first() -> None:
    """A schema usually grows by a block. Naming one of five sends whoever is
    adding the rules round the loop five times."""
    with pytest.raises(BenchError) as excinfo:
        proprioceptive_columns(["t", "base_x", "base_y", "base_theta"])
    message = str(excinfo.value)
    for column in ("base_x", "base_y", "base_theta"):
        assert column in message


def test_a_prefix_of_a_known_column_is_not_absorbed_by_it() -> None:
    """`q_base` is not a joint angle. The rules are full matches, because a
    `startswith` rule counts anything beginning `q_` as proprioception — which
    is the shape of the defect being fixed, one rule further in."""
    for column in ("q_base", "qd_base", "q_", "human_z", "obs_0_vx", "tt"):
        with pytest.raises(BenchError, match=re.escape(column)):
            column_layer(column)


def test_the_refusal_is_an_exception_and_not_a_sentinel() -> None:
    """`BenchError` is what the rest of `reg.bench` refuses with. A sentinel
    return value is a refusal a caller can ignore by accident."""
    assert issubclass(BenchError, Exception)
    with pytest.raises(BenchError):
        proprioceptive_columns(["t", "q_0", "unknown_column"])


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
            # Required with no default (issue #83). This test is about the
            # scenario lookup, so it declares the same identity the benchmark's
            # own builds declare rather than inventing a second one.
            "--run-start",
            bench.BENCH_IDENTITY.run_start_text,
            "--unit-id",
            bench.BENCH_IDENTITY.unit_id,
            "--operator-id",
            bench.BENCH_IDENTITY.operator_id,
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
        unary_union(link_polygons(f.proprio(), scn.world.limits, ORIGIN_FRAME)).distance(
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


def _resolution_of(level: str) -> float:
    """The level's own timestamp quantum, the way `run_resolution_curve` sets it.

    A test that passed `TIME_TOL_S` for every level would grade `occurrence`
    against a precision it does not claim — the defect this mirrors exists to
    keep out.
    """
    return (
        graph.OCCURRENCE_TIME_RESOLUTION_S
        if level == bench.OCCURRENCE_LEVEL
        else bench.TIME_TOL_S
    )


def _checks(view: Path, level: str, truth: bench.GroundTruth) -> dict[str, str]:
    answers = bench.answers_at_level(
        view, level, attestation=truth.attestation, keyring=None
    )
    return {
        q.name: bench.check_level(
            q, answers, truth, timestamp_resolution_s=_resolution_of(level)
        ).verdict
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
    check = bench.check_level(
        query,
        answers,
        truth,
        timestamp_resolution_s=_resolution_of(bench.OCCURRENCE_LEVEL),
    )
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
    check = bench.check_level(
        query,
        coarse,
        _timing_truth((2.51, 2.53, 2.55)),
        timestamp_resolution_s=bench.TIME_TOL_S,
    )
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
        bench.check_level(
            query,
            fine,
            _timing_truth((2.51, 2.53, 2.55)),
            timestamp_resolution_s=bench.TIME_TOL_S,
        ).verdict
        == AGREE
    )
    # And a level that records no closest approach at all does not thereby agree.
    silent = bench.LevelAnswers(None, None, None, None, None)
    assert (
        bench.check_level(
            query,
            silent,
            _timing_truth((2.51,)),
            timestamp_resolution_s=bench.TIME_TOL_S,
        ).verdict
        == COULD_NOT_EVALUATE
    )


def test_a_coarse_level_is_imprecise_within_its_quantum_and_wrong_outside_it() -> None:
    """THE NEGATIVE TEST for the quantum-aware comparison.

    The fix that stopped `occurrence` scoring `DISAGREE` for being coarse must
    not have stopped it scoring `DISAGREE` for being *wrong*. A check that
    cannot fail is not a check, and "widen the tolerance until the level
    passes" is the failure mode this guards.

    One quantum (1.0 s), three answers, three verdicts.
    """
    query = next(
        q for q in bench.RESOLUTION_QUERIES if q.name == "time_of_closest_approach"
    )
    truth = _timing_truth((45.98,))
    quantum = 1.0

    def verdict_for(answer: float) -> str:
        return bench.check_level(
            query,
            bench.LevelAnswers(None, answer, None, None, None),
            truth,
            timestamp_resolution_s=quantum,
        ).verdict

    # Inside TIME_TOL_S — the coarse timestamp landed on the answer anyway.
    assert verdict_for(45.98) == AGREE
    # Outside the tolerance, inside the quantum — the real occurrence case,
    # 0.02 s out on a level that promises only 1.0 s. Imprecise, not wrong.
    assert verdict_for(46.00) == COULD_NOT_EVALUATE
    # Outside the quantum too. The level misplaced the event by more than its
    # own resolution, and no widening of the tolerance may excuse that.
    assert verdict_for(48.00) == DISAGREE

    check = bench.check_level(
        query,
        bench.LevelAnswers(None, 46.00, None, None, None),
        truth,
        timestamp_resolution_s=quantum,
    )
    assert "quantum" in check.detail, (
        "a refusal on these grounds has to say so in the detail column, or the "
        "table shows a blank where a level declined to answer"
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
    assert (
        bench.check_level(
            query,
            answers,
            truth,
            timestamp_resolution_s=_resolution_of(bench.OCCURRENCE_LEVEL),
        ).verdict
        == AGREE
    )


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
    assert (
        bench.check_level(
            query,
            answers,
            truth,
            timestamp_resolution_s=_resolution_of(bench.OCCURRENCE_LEVEL),
        ).verdict
        == DISAGREE
    )


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
        assert (
            bench.check_level(
                query, answers, truth, timestamp_resolution_s=_resolution_of(level)
            ).verdict
            == DISAGREE
        ), level


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
        q.name: bench.check_level(
            q, answers, truth, timestamp_resolution_s=bench.TIME_TOL_S
        ).verdict
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
        # `None` unless a test overrides it: the render tests are about the
        # *shape* of the report, and a hand-written byte attribution here would
        # be a made-up measurement in every one of them. The shapes that use it
        # take it explicitly (issue #116).
        "tables": None,
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

    The occurrence level being unable to say *when* the closest approach
    happened is the measurement, not a regression. A command that exited
    non-zero on its own finding would push the next person to tune the finding
    away — which is the one thing issue #35 says not to do.

    **This assertion used to look for `DISAGREE`.** It changed with the
    quantum-aware comparison in `_closest_approach_time_check`: the occurrence
    level records to 1.0 s and was being graded against 0.01 s, so answering
    46.00 s against a true 45.98 s scored `DISAGREE` — a level marked wrong for
    being exactly as coarse as it says it is. The natural finding at this level
    is a refusal, so that is what is asserted, and it is asserted specifically
    rather than as "not AGREE": a run where every level agreed would prove
    nothing about the exit code, and so would one that had quietly started
    disagreeing again.
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
    report = out.read_text(encoding="utf-8")
    assert COULD_NOT_EVALUATE in report, (
        "no level refused at this length, so this run does not show that the "
        "exit code is independent of the per-level verdicts. Pick a fixture or a "
        "resolution where they diverge rather than deleting the assertion."
    )
    assert DISAGREE not in report, (
        "a level disagreed on this fixture, where nothing is tampered with and "
        "every level is as accurate as it claims to be. Before treating this as "
        "the finding, check it is not a check grading a level against a "
        "precision finer than that level's own quantum — which is what this "
        "assertion previously mistook for a measurement."
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
        q.name: bench.check_level(
            q, answers, curve.truth, timestamp_resolution_s=_resolution_of(level)
        )
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
        timestamp_resolution_s=bench.TIME_TOL_S,
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
            spec,
            bench.LevelAnswers(None, None, None, None, whole),
            truth,
            timestamp_resolution_s=bench.TIME_TOL_S,
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
        bench.check_level(
            spec,
            answers,
            curve.truth,
            timestamp_resolution_s=bench.TIME_TOL_S,
        ).verdict
        == COULD_NOT_EVALUATE
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


# --------------------------------------------------------------------------
# THE CONTROL RATE (issue #68).
#
# THE TESTS THIS SECTION EXISTS FOR: `test_the_verdict_count_is_one_per_commanded
# _action_and_the_declarations_are_not` and the two document checks under
# "Drift". The finding this section was written against is a headline retention
# figure that is **linear in a parameter no document named**: enforcement emits
# one verdict and one chain record per commanded action, so the level that
# carries Claim 1 scales with the control rate, and this simulator runs at 50 Hz
# while a real manipulator loop runs at 1 kHz.
#
# So there are three kinds of test here. The arithmetic of a rate ladder, worked
# by hand and refused where it would have to round. The mechanism, asserted as an
# invariant rather than as a byte count — verdicts track the frame count, and the
# declarations, whose interval is wall-clock, do not. And a check that the
# published figures and the rate they were measured at cannot drift apart, fed
# the condition it guards against.
# --------------------------------------------------------------------------


def test_the_base_rate_is_the_fixture_rate_and_is_not_restated() -> None:
    """50 Hz, derived from `reg.scenarios.DEFAULT_DT` rather than typed here.

    A literal `50.0` in `reg.bench` would be a second definition of the frame
    period, and the two would drift the first time either moved — which is the
    shape of the bug this whole section is about.
    """
    assert bench.BASE_CONTROL_RATE_HZ == 1.0 / scenarios.DEFAULT_DT


def test_frames_at_rate_is_the_duration_in_control_steps() -> None:
    """Hand-worked. 59.98 s is 2,999 steps at 50 Hz and 59,980 at 1 kHz, and a
    run is one frame longer than it has steps."""
    assert bench.frames_at_rate(50.0, 59.98) == 3_000
    assert bench.frames_at_rate(1_000.0, 59.98) == 59_981
    assert bench.frames_at_rate(100.0, 1.0) == 101


def test_a_rate_that_does_not_divide_the_run_is_refused() -> None:
    """**The negative test.** Rounding would give one row of the table a
    different run length from the others, and the study holds the run length
    still so that the rate is the only thing that differs."""
    with pytest.raises(BenchError, match="not a whole number"):
        bench.frames_at_rate(3.0, 0.58)


@pytest.mark.parametrize(
    ("rate", "run_seconds"),
    [(0.0, 60.0), (-50.0, 60.0), (50.0, 0.0), (50.0, -1.0), (float("inf"), 60.0)],
)
def test_a_rate_or_duration_that_is_not_a_measurement_is_refused(
    rate: float, run_seconds: float
) -> None:
    with pytest.raises(BenchError, match="finite, positive"):
        bench.frames_at_rate(rate, run_seconds)


def test_the_base_rate_row_is_the_published_curve_and_not_something_near_it() -> None:
    """**The anchoring invariant.** The duration the study holds constant is the
    published curve's own length, so its base-rate row is that curve re-run under
    the same seed and parameters rather than a second measurement of something
    nearby. Without this the ladder would be internally comparable and comparable
    with nothing else — and what the study exists to answer is what the
    *published* figures do at 1 kHz."""
    run_seconds = bench.control_rate_run_seconds(bench.RESOLUTION_FRAME_COUNT)
    assert run_seconds == (bench.RESOLUTION_FRAME_COUNT - 1) * scenarios.DEFAULT_DT
    assert (
        bench.frames_at_rate(bench.BASE_CONTROL_RATE_HZ, run_seconds)
        == bench.RESOLUTION_FRAME_COUNT
    )


def test_a_run_with_no_frame_period_has_no_duration_to_hold_constant() -> None:
    with pytest.raises(BenchError, match="at least two frames"):
        bench.control_rate_run_seconds(1)


@pytest.mark.parametrize("raw", ["50", "1000", ""])
def test_one_rate_is_not_a_ladder_at_the_cli(raw: str) -> None:
    """A single rate is the ordinary resolution curve. A section headed with a
    comparison and holding one row would be read as the comparison."""
    with pytest.raises(argparse.ArgumentTypeError):
        bench._rates(raw)


@pytest.mark.parametrize("raw", ["1000,50", "50,50", "50,abc", "50,-1", "50,0"])
def test_a_ladder_that_is_not_a_ladder_is_refused_at_the_cli(raw: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        bench._rates(raw)


def test_the_cli_has_no_default_control_rate() -> None:
    """**No default, and there must not be one** (CLAUDE.md, and the whole point
    of issue #68). The rate is exactly the parameter that went unstated under
    every published retention figure; a ladder this flag picked for itself would
    restate the problem one level down."""
    assert bench._parser().get_default("control_rate_hz") is None


#: Two rates an order apart, over a run short enough to build twice inside a
#: test. Not golden: every assertion below is about how the two points differ,
#: never about what either one measures.
_LADDER_FRAMES = 30
_LADDER_RATES = (50.0, 250.0)


@pytest.fixture(scope="module")
def rate_ladder(tmp_path_factory) -> tuple[bench.ControlRatePoint, ...]:
    """One real control-rate study at two rates. Built once."""
    work = tmp_path_factory.mktemp("control-rate")
    return bench.run_control_rate_study(
        _LADDER_RATES,
        work,
        run_seconds=bench.control_rate_run_seconds(_LADDER_FRAMES),
        seed=0,
        timing_repeats=1,
        **_FAST,
    )


def test_the_study_holds_the_run_duration_still_and_moves_the_frame_count(
    rate_ladder,
) -> None:
    """The design of the experiment, asserted rather than described.

    Two rates cannot share both a duration and a frame count. It is the frame
    count that moves, because holding *it* still instead would compare a minute
    of robot time against seconds of it — measuring how the fixed schema cost
    amortises, which is what `--scaling` is for, inside a table whose only
    variable is supposed to be the rate.
    """
    durations = {round(p.run_seconds, 9) for p in rate_ladder}
    assert len(durations) == 1, f"the run length moved between rates: {durations}"
    assert [p.rate_hz for p in rate_ladder] == sorted(_LADDER_RATES)
    assert [p.frames for p in rate_ladder] == sorted(p.frames for p in rate_ladder)
    for point in rate_ladder:
        assert point.dt == pytest.approx(1.0 / point.rate_hz)
        assert point.curve.frame_period_s == pytest.approx(1.0 / point.rate_hz)


def test_the_verdict_count_is_one_per_commanded_action_and_the_declarations_are_not(
    rate_ladder,
) -> None:
    """**THE TEST THIS ISSUE EXISTS FOR.** The mechanism, as an invariant.

    Enforcement adjudicates every commanded action, so the verdict count *is* the
    frame count and scales with the rate. The policy replans on a wall-clock
    interval, so its declaration count does not move at all when the rate does.
    That asymmetry is why the retention figure is linear in the control rate, and
    it is asserted here rather than left to be read off a table of byte counts —
    a byte count that stopped scaling would look like an improvement.
    """
    declarations = {p.curve.attestation_counts["declarations"] for p in rate_ladder}
    assert len(declarations) == 1, (
        f"the declaration count moved with the control rate: {declarations}. The "
        "replan interval is a wall-clock period; if this moved, the fixture's "
        "policy is being driven by the frame clock and the study's explanation "
        "of its own finding is wrong."
    )
    for point in rate_ladder:
        counts = point.curve.attestation_counts
        assert counts["verdicts"] == point.frames, (
            f"{point.rate_hz} Hz: {counts['verdicts']} verdicts for "
            f"{point.frames} frames. One verdict per commanded action is the "
            "premise of the whole finding."
        )
        assert counts["chain_records"] == counts["verdicts"] + counts["declarations"]


def test_the_records_retained_grow_with_the_rate_at_every_level(rate_ladder) -> None:
    """The record layer is not coarsened by any resolution level, so the row
    count rises with the rate at all three — including the coarsest, which is the
    one docs/plan.md Claim 1 leads with."""
    low, high = rate_ladder[0], rate_ladder[-1]
    for level in bench.RESOLUTION_LEVELS:
        assert high.level(level).records > low.level(level).records, level


def test_rate_multiple_is_arithmetic_between_two_measured_points(rate_ladder) -> None:
    """Two measured endpoints and the ratio between them — nothing fitted."""
    for level in bench.RESOLUTION_LEVELS:
        low, high, multiple = bench.rate_multiple(rate_ladder, level)
        assert low == rate_ladder[0].level(level).bytes_per_hour
        assert high == rate_ladder[-1].level(level).bytes_per_hour
        assert multiple == high / low


def test_one_point_is_not_a_multiple(rate_ladder) -> None:
    """The negative: a ratio needs two measurements, and one that quietly
    returned 1.0x would read as 'the rate costs nothing'."""
    with pytest.raises(BenchError, match="two measured rates"):
        bench.rate_multiple(rate_ladder[:1], bench.OCCURRENCE_LEVEL)
    with pytest.raises(BenchError, match="measure how the figure"):
        bench.run_control_rate_study(
            [50.0],
            "unused",
            run_seconds=1.0,
            seed=0,
            timing_repeats=1,
            **_FAST,
        )


def test_a_repeated_rate_is_one_row_printed_twice(tmp_path: Path) -> None:
    with pytest.raises(BenchError, match="repeats a rate"):
        bench.run_control_rate_study(
            [50.0, 50.0],
            tmp_path,
            run_seconds=1.0,
            seed=0,
            timing_repeats=1,
            **_FAST,
        )


def test_a_level_that_stopped_answering_at_a_high_rate_is_not_hidden(rate_ladder) -> None:
    """A cheaper artifact that stopped answering is not a cheaper artifact.

    Every level at every rate carries a verdict and the questions it lost, and
    `COULD-NOT-EVALUATE` never resolves to `AGREE`. This asserts the *shape* —
    that the report cannot show a byte count without the verdict beside it —
    rather than which verdict this fixture happens to produce.
    """
    report = render([], sensor_multiplier=None, control_rates=rate_ladder, **_RENDER_ARGS)
    assert "## What the control rate costs" in report
    assert "what you lose" in report
    for point in rate_ladder:
        for level in bench.RESOLUTION_LEVELS:
            assert point.level(level).verdict in (
                AGREE,
                DISAGREE,
                COULD_NOT_EVALUATE,
            )
    assert "Not a fitted curve" in report


def test_the_report_states_the_rate_every_number_in_it_was_measured_at(
    rate_ladder,
) -> None:
    """The fix for the finding, in the report itself: no byte count appears
    without the control rate that produced it stated in the same section."""
    report = render([], sensor_multiplier=None, control_rates=rate_ladder, **_RENDER_ARGS)
    for point in rate_ladder:
        assert bench._rate_text(point.rate_hz) in report
    assert "1 kHz" in report


def test_a_report_with_no_control_rate_ladder_carries_no_such_section(
    attested,
) -> None:
    """Absent, not empty — the same rule the scaling and resolution sections
    follow."""
    curve, _, _ = attested
    report = render([], sensor_multiplier=None, resolution=curve, **_RENDER_ARGS)
    assert "## What the control rate costs" not in report


def test_the_resolution_table_states_the_control_rate_it_was_measured_at(
    attested,
) -> None:
    """**The single-curve half of the fix.** `--resolution` on its own now says
    which rate its figures assume; before issue #68 nothing did, in this report
    or in any document."""
    curve, _, _ = attested
    report = render([], sensor_multiplier=None, resolution=curve, **_RENDER_ARGS)
    assert "control rate" in report
    assert bench._rate_text(1.0 / curve.frame_period_s) in report
    # "moves with this", not "linear in this": the record layer is linear in the
    # rate and the file is not, and the ladder measures the gap (issue #116).
    assert "moves with this" in report
    assert "linear in this" not in report


def test_a_ladder_with_one_point_is_not_a_section(rate_ladder) -> None:
    with pytest.raises(BenchError, match="promising a comparison"):
        render([], sensor_multiplier=None, control_rates=rate_ladder[:1], **_RENDER_ARGS)


def test_cli_control_rate_writes_the_ladder(tmp_path: Path) -> None:
    """The issue's verification command, at a length a test can afford."""
    out = tmp_path / "control-rate.md"
    code = bench.main(
        [
            "--control-rate-hz",
            "50,100",
            "--resolution-frames",
            str(_LADDER_FRAMES),
            "--resolution-n-samples",
            str(_FAST["n_samples"]),
            "--horizon",
            str(_FAST["horizon"]),
            "--substep-dt",
            str(_FAST["substep_dt"]),
            "--seed",
            "0",
            "--out",
            str(out),
            "--work-dir",
            str(tmp_path / "work"),
        ]
    )
    assert code == bench.EXIT_OK
    report = out.read_text(encoding="utf-8")
    assert "## What the control rate costs" in report
    assert "| `occurrence` |" in report
    # Nothing that varies between two runs of the same command may reach it.
    assert str(tmp_path) not in report


# --------------------------------------------------------------------------
# DRIFT: a retention figure and the rate it was measured at (issue #68).
#
# The check is cheap and it is the one that would have caught this issue. Every
# published bytes/hour figure is linear in the control rate, so a document that
# quotes one without naming the rate is quoting a number that cannot be
# reproduced or compared — and both documents did exactly that for three
# milestones while nothing failed, because prose does not fail.
#
# Scope (issue #78): every document under `docs/`, discovered by glob rather
# than listed by hand. #68 scoped this to the two documents it owned and said so;
# `docs/sufficiency.md` and `docs/prior-art.md` then quoted the same figures to
# the weaker standard for three milestones, which is the defect repeating one
# level up — a hand-maintained roster drifts exactly the way the prose did. A
# document that quotes no artifact-side figure comes back COULD-NOT-EVALUATE and
# is not a pass, and `test_the_documents_that_carry_figures_are_the_ones_expected`
# is what stops that third verdict from becoming a place to hide.
# --------------------------------------------------------------------------

REPO = Path(__file__).resolve().parent.parent

#: A retention figure: `60.05 MB/h`, `3.8 MB/hour`, `1.14 GB/h`.
PER_HOUR = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(?:[kMGT]?B)/h(?:our)?\b")

#: A control rate: `50 Hz`, `1 kHz`, `1,000 Hz`.
RATE = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(k?)Hz\b")


def _sections(text: str) -> list[str]:
    """The document split at its markdown headings, heading kept with its body."""
    return [p for p in re.split(r"\n(?=#{1,6} )", text) if p.strip()]


def _paragraphs(section: str) -> list[str]:
    return [p for p in re.split(r"\n\s*\n", section) if p.strip()]


def _rates_hz(text: str) -> set[float]:
    """Every control rate named in `text`, normalised to Hz."""
    return {
        float(number.replace(",", "")) * (1_000.0 if kilo else 1.0)
        for number, kilo in RATE.findall(text)
    }


def rate_is_stated_with_the_figure(text: str) -> tuple[str, list[str]]:
    """Verdict on whether every retention figure names the rate it assumes.

    **What it checks.** A section naming one of `reg.bench.RESOLUTION_LEVELS` is
    a section about this artifact's retention cost. Every paragraph of one that
    quotes a per-hour figure has to name the base control rate *in that
    paragraph* — a rate three paragraphs away is not a rate a reader of the
    figure sees.

    **What it deliberately does not check.** A per-hour figure in a section that
    names no resolution level is a figure about something else — the sensor-log
    rates in `docs/sensor-baseline.md`'s sources are not linear in this
    simulator's control rate, and demanding one there would be noise. And it
    cannot check that the prose around a figure is honest; a reviewer still has
    to do that.

    Three-valued, and the third does not resolve to the first: a document with no
    artifact-side retention figure is `COULD-NOT-EVALUATE`, because deleting the
    figures is how a check of this shape would otherwise be defeated. Returns the
    verdict and the offending figures.
    """
    checked = 0
    missing: list[str] = []
    for section in _sections(text):
        if not any(level in section for level in bench.RESOLUTION_LEVELS):
            continue
        for paragraph in _paragraphs(section):
            figures = PER_HOUR.findall(paragraph)
            if not figures:
                continue
            checked += 1
            if bench.BASE_CONTROL_RATE_HZ not in _rates_hz(paragraph):
                missing += [f"{n} B/h" for n in figures]
    if not checked:
        return COULD_NOT_EVALUATE, []
    return (DISAGREE if missing else AGREE), missing


#: Every document in `docs/`, in a stable order. Globbed, not listed: the
#: document added next milestone is inside this check on the day it is written,
#: which is the property #68's hand-written pair of names did not have.
DOCS = sorted(path.name for path in (REPO / "docs").glob("*.md"))

#: The documents that carry an artifact-side retention figure today. Pinned so
#: that deleting the figures — the one way a check of this shape is defeated
#: without anything going red — moves a document out of this set and fails.
# `retention.md` joined this set on 2026-08-31, when Claim 1's measurement record
# was extracted into it. `plan.md` stayed: it leads with the derived six-month
# total, so it publishes the `bytes/hour` that total is derived from, and a
# document that quotes the figure has to name the rate it is linear in.
DOCS_WITH_RETENTION_FIGURES = frozenset(
    {"plan.md", "retention.md", "prior-art.md", "sensor-baseline.md", "sufficiency.md"}
)


@pytest.mark.parametrize("doc", DOCS)
def test_every_published_retention_figure_names_the_control_rate(doc: str) -> None:
    """**THE DOCUMENT CHECK THIS ISSUE EXISTS FOR.**

    A figure that is linear in an unstated parameter is not a measured figure.
    The rate compared against is `reg.bench.BASE_CONTROL_RATE_HZ`, which is
    derived from `reg.scenarios.DEFAULT_DT` — so re-parameterising the fixture
    and leaving the documents alone fails here rather than in six months.

    Every document in `docs/`, since issue #78. One that quotes no artifact-side
    figure is COULD-NOT-EVALUATE here — permitted, because there is nothing in it
    to be wrong about, and pinned by the roster test below so that "nothing to
    check" cannot become the state of a document that used to have figures.
    """
    verdict, missing = rate_is_stated_with_the_figure(
        (REPO / "docs" / doc).read_text(encoding="utf-8")
    )
    assert verdict != DISAGREE, (
        f"docs/{doc} quotes {missing} in a paragraph that never names the control "
        f"rate. Every one of those figures is linear in it "
        f"({bench.BASE_CONTROL_RATE_HZ:g} Hz here, 1 kHz on a real manipulator), "
        "so a reader cannot reproduce or compare them. Name the rate in the same "
        "paragraph as the figure."
    )


def test_the_documents_that_carry_figures_are_the_ones_expected() -> None:
    """**SILENCE IS NOT A PASS, AT THE CORPUS LEVEL.**

    The test above is satisfied by a document with no figures in it, so on its
    own it would go green if every figure in the repository were deleted — or if
    the glob matched nothing at all and it ran zero cases. This names which
    documents are supposed to have something to check. It fails in both
    directions and both are worth a look: a document that lost its figures, and
    one that gained them (which is a new publication site for a rate-linear
    number, not a problem — add it here once its figures name the rate).
    """
    carrying = {
        doc
        for doc in DOCS
        if rate_is_stated_with_the_figure(
            (REPO / "docs" / doc).read_text(encoding="utf-8")
        )[0]
        != COULD_NOT_EVALUATE
    }
    assert carrying == set(DOCS_WITH_RETENTION_FIGURES), (
        "the set of documents carrying an artifact-side retention figure has "
        f"moved: gained {sorted(carrying - DOCS_WITH_RETENTION_FIGURES)}, lost "
        f"{sorted(DOCS_WITH_RETENTION_FIGURES - carrying)}. A gain needs adding "
        "to DOCS_WITH_RETENTION_FIGURES; a loss means the figures the check "
        "above exists to guard are no longer being published there."
    )


def test_a_retention_figure_with_no_rate_beside_it_is_caught() -> None:
    """**The negative test.** This is the exact shape issue #68 was filed about:
    a measured figure, published, with nothing saying what it is linear in."""
    verdict, missing = rate_is_stated_with_the_figure(
        "## Sensitivity\n\nThe occurrence level costs 60.05 MB/h.\n"
    )
    assert verdict == DISAGREE
    assert missing == ["60.05 B/h"]


def test_a_rate_stated_in_another_paragraph_does_not_cover_this_one() -> None:
    """Proximity is the point. A rate named at the top of a long section is not
    a rate a reader of the figure five paragraphs down ever sees."""
    verdict, _ = rate_is_stated_with_the_figure(
        "## Retention\n\nThe fixture runs at 50 Hz.\n\n"
        "The occurrence level costs 60.05 MB/h.\n"
    )
    assert verdict == DISAGREE


def test_a_rate_stated_in_another_section_does_not_cover_this_one() -> None:
    verdict, _ = rate_is_stated_with_the_figure(
        "## Parameters\n\nThe occurrence level runs at 50 Hz.\n\n"
        "## Retention\n\nThe occurrence level costs 60.05 MB/h.\n"
    )
    assert verdict == DISAGREE


def test_the_wrong_rate_beside_the_figure_is_caught() -> None:
    """A paragraph that names 1 kHz and quotes a figure measured at 50 Hz is
    worse than one that names no rate at all."""
    verdict, missing = rate_is_stated_with_the_figure(
        "## Retention\n\nAt 1 kHz the occurrence level costs 60.05 MB/h.\n"
    )
    assert verdict == DISAGREE
    assert missing == ["60.05 B/h"]


def test_a_rate_beside_the_figure_passes() -> None:
    """The positive control: the check is not one that can only say no."""
    verdict, missing = rate_is_stated_with_the_figure(
        "## Retention\n\nAt 50 Hz the occurrence level costs 60.05 MB/h.\n"
    )
    assert (verdict, missing) == (AGREE, [])


def test_a_rate_in_the_heading_of_the_table_that_carries_the_figures_covers_them() -> None:
    """The form `docs/sufficiency.md`'s curve now uses, so the shape of that fix
    is pinned rather than assumed: a markdown table is one paragraph, and a rate
    in its column heading is a rate a reader of every figure under it sees."""
    verdict, missing = rate_is_stated_with_the_figure(
        "### The measured curve\n\n"
        "| level | bytes/hour @ 50 Hz |\n|---|---|\n"
        "| `occurrence` | **60.05 MB/h** |\n"
    )
    assert (verdict, missing) == (AGREE, [])


def test_a_rate_in_a_neighbouring_table_does_not_cover_the_figures() -> None:
    """And the negative half of the same shape: two tables are two paragraphs,
    so a parameter block above the curve does not qualify the curve."""
    verdict, missing = rate_is_stated_with_the_figure(
        "### The measured curve\n\n"
        "| parameter | value |\n|---|---|\n| control rate | 50 Hz |\n\n"
        "| level | bytes/hour |\n|---|---|\n| `occurrence` | **60.05 MB/h** |\n"
    )
    assert verdict == DISAGREE
    assert missing == ["60.05 B/h"]


@pytest.mark.parametrize(
    "text",
    [
        "## Retention\n\nThe occurrence level was measured at 50 Hz.\n",
        "## Sources\n\nOne teleoperation setup reports about 20 GB/hour.\n",
    ],
)
def test_nothing_to_check_is_not_a_pass(text: str) -> None:
    """Silence is could-not-evaluate, and so is a per-hour figure that is not
    about this artifact at all — a sensor rate is not linear in this
    simulator's control rate, and counting it as a pass would let the artifact
    figures be deleted while the check stayed green."""
    verdict, _ = rate_is_stated_with_the_figure(text)
    assert verdict == COULD_NOT_EVALUATE


def test_the_control_rate_report_is_deterministic(tmp_path: Path) -> None:
    """Same seed, same ladder, same report (rule 2). CI compares two runs.

    The rate is the one thing this study varies, and it varies it by handing
    `reg.scenarios.long_run` a different `dt` — so the two runs below differ in
    nothing at all and the whole report, tables and verdicts, has to come back
    byte for byte. Rendered rather than compared as byte counts, for the reason
    `test_the_curve_is_deterministic` gives: identical sizes are not identical
    artifacts.
    """
    args = [
        "--control-rate-hz",
        "50,100",
        "--resolution-frames",
        str(_LADDER_FRAMES),
        "--resolution-n-samples",
        str(_FAST["n_samples"]),
        "--horizon",
        str(_FAST["horizon"]),
        "--substep-dt",
        str(_FAST["substep_dt"]),
        "--seed",
        "0",
    ]
    reports = []
    for run in ("a", "b"):
        out = tmp_path / f"{run}.md"
        assert (
            bench.main([*args, "--out", str(out), "--work-dir", str(tmp_path / run)])
            == bench.EXIT_OK
        )
        reports.append(out.read_text(encoding="utf-8"))
    assert reports[0] == reports[1]


# --------------------------------------------------------------------------
# RUNNING SCENARIOS CONCURRENTLY (issue #74).
#
# The benchmark used one of six cores and numpy's five OpenBLAS worker threads
# slept through the run; `--jobs N` measures the per-scenario table N processes
# at a time. Everything below exists because the risk in that change is not that
# it is slow — it is that it is quietly non-reproducible, in a project whose
# whole argument is reproducibility.
#
# Three properties, and each is tested against the condition it guards against:
#
# 1. Results are assembled in submission order. The test forces the *opposite*
#    completion order and asserts it made no difference — and asserts the
#    completion order really was reversed, so it cannot pass by the tasks having
#    happened to finish in order.
# 2. A parallel report is byte-identical to the serial one at the same seed, and
#    to a second parallel run. That is the acceptance criterion, and the third
#    comparison is the one that would catch a seed reaching somewhere it should
#    not.
# 3. The flag refuses the two combinations where it would mislead: with the
#    wall-clock columns on (contended timings are not the published serial
#    ones), and with nothing selected for it to apply to.
# --------------------------------------------------------------------------

_PARALLEL_SCENARIOS = ("near_miss", "contact")


def _thread_pool(jobs: int) -> concurrent.futures.Executor:
    """An executor a test can drive. Threads, so the tasks share the closures
    and events the test uses to control what finishes when."""
    return concurrent.futures.ThreadPoolExecutor(max_workers=jobs)


def test_results_come_back_in_submission_order_not_completion_order() -> None:
    """The determinism property of `--jobs`, tested by violating its premise.

    The four tasks are wired to finish in exactly reverse order — task i waits
    on its own event and releases task i-1 — so a `_in_submission_order` that
    had been rewritten around `concurrent.futures.as_completed` would return
    [3, 2, 1, 0] and this test would fail. `completed` is asserted first: if the
    tasks had finished in submission order after all, the second assertion would
    hold for a reason that says nothing.

    No sleeps, so the ordering is forced rather than raced for.
    """
    n = 4
    events = [threading.Event() for _ in range(n)]
    completed: list[int] = []
    lock = threading.Lock()

    def call(i: int) -> int:
        assert events[i].wait(timeout=30), f"task {i} was never released"
        with lock:
            completed.append(i)
        if i > 0:
            events[i - 1].set()
        return i

    events[n - 1].set()
    out = bench._in_submission_order(
        [functools.partial(call, i) for i in range(n)],
        jobs=n,
        executor_factory=_thread_pool,
    )

    assert completed == list(reversed(range(n))), (
        "the tasks did not finish in reverse order, so this run does not "
        "distinguish submission order from completion order at all"
    )
    assert out == list(range(n))


def test_a_worker_that_raised_is_not_a_result() -> None:
    """A scenario that failed is not a scenario that measured something.

    The exception comes back out of the parallel path the way it would out of
    the serial loop, rather than becoming a `None` row that the report would
    render as a measurement.
    """

    def boom() -> int:
        raise BenchError("the third scenario could not be built")

    with pytest.raises(BenchError, match="third scenario"):
        bench._in_submission_order(
            [lambda: 1, lambda: 2, boom],
            jobs=3,
            executor_factory=_thread_pool,
        )


def test_no_worker_is_not_a_pool() -> None:
    """`jobs=0` is not the serial path — omitting the flag is."""
    with pytest.raises(BenchError, match="jobs=0"):
        bench._in_submission_order([lambda: 1], jobs=0, executor_factory=_thread_pool)


def test_the_serial_and_parallel_paths_pass_the_same_arguments(tmp_path: Path) -> None:
    """`run_scenarios` measures the same thing either way, in the same order.

    Compared as `ScenarioResult`s rather than as a rendered report, so a
    difference in any byte count, row count or answer shows up as itself. The
    scenario names are asserted in order too: two results that agree on every
    number but arrived transposed would still be a report with the wrong rows.
    """
    common = dict(
        seed=0,
        horizon=_FAST["horizon"],
        n_samples=_FAST["n_samples"],
        envelope_seed=_FAST["envelope_seed"],
        substep_dt=_FAST["substep_dt"],
        occurrence_resolution_s=_FAST["occurrence_resolution_s"],
    )
    serial = bench.run_scenarios(
        _PARALLEL_SCENARIOS, tmp_path / "serial", jobs=None, **common
    )
    parallel = bench.run_scenarios(
        _PARALLEL_SCENARIOS,
        tmp_path / "parallel",
        jobs=2,
        executor_factory=_thread_pool,
        **common,
    )

    assert [r.scenario for r in serial] == list(_PARALLEL_SCENARIOS)
    assert [r.scenario for r in parallel] == list(_PARALLEL_SCENARIOS)
    for a, b in zip(serial, parallel):
        assert (a.sizes, a.frames, a.nodes, a.edges, a.tables) == (
            b.sizes,
            b.frames,
            b.nodes,
            b.edges,
            b.tables,
        )
        assert a.check.graph_answer == b.check.graph_answer
        assert a.check.csv_answer == b.check.csv_answer
        assert a.check.verdict == b.check.verdict


def test_a_parallel_report_is_byte_identical_to_the_serial_one(tmp_path: Path) -> None:
    """The issue's acceptance criterion, at a size a test can afford.

    Three reports through the real CLI and the real process pool: one serial,
    two parallel. All three must be the same bytes. The third comparison is the
    one the issue says is load-bearing — two parallel runs agreeing with each
    other but not with the serial run would mean concurrency had reached a
    figure, and only this comparison would say so.
    """
    args = [
        *[a for name in _PARALLEL_SCENARIOS for a in ("--scenario", name)],
        "--horizon",
        str(_FAST["horizon"]),
        "--n-samples",
        str(_FAST["n_samples"]),
        "--envelope-seed",
        str(_FAST["envelope_seed"]),
        "--substep-dt",
        str(_FAST["substep_dt"]),
        "--seed",
        "0",
        # Required with --jobs, and the reason the comparison can be exact:
        # the wall-clock columns are the only fields two runs may differ in.
        "--no-timings",
    ]
    reports = []
    passes = (
        ("serial", []),
        ("parallel-a", ["--jobs", "2"]),
        ("parallel-b", ["--jobs", "2"]),
    )
    for run, jobs in passes:
        out = tmp_path / f"{run}.md"
        assert (
            bench.main(
                [*args, *jobs, "--out", str(out), "--work-dir", str(tmp_path / run)]
            )
            == bench.EXIT_OK
        )
        reports.append(out.read_bytes())

    assert reports[0] == reports[1] == reports[2]
    assert reports[0], "an empty report compares equal to another empty one"


def test_the_cli_has_no_default_job_count() -> None:
    """CLAUDE.md: never invent a default. The worker count is a property of the
    machine, so a benchmark that picked one would print a wall-clock figure
    nobody could reproduce elsewhere — and the serial path has to stay reachable
    for the comparison the wall-clock table is made of."""
    args = bench._parser().parse_args(["--all", "--out", "x.md"])
    assert args.jobs is None


@pytest.mark.parametrize("raw", ["0", "-2", "two", "1.5"])
def test_a_job_count_that_is_not_a_worker_count_is_refused(raw: str) -> None:
    with pytest.raises(SystemExit) as exc:
        bench._parser().parse_args(
            ["--all", "--no-timings", "--jobs", raw, "--out", "x.md"]
        )
    assert exc.value.code == 2


def test_parallel_timings_are_refused_rather_than_quietly_contended(
    tmp_path: Path, capsys
) -> None:
    """The negative test for the flag's one real hazard.

    `graph`, `raw CSV` and `speedup` are medians of real elapsed time. Measured
    while N scenarios share the machine they are not comparable with the
    published serial figures, and a speedup whose two halves were measured under
    different contention is not a ratio of anything. The issue's instruction is
    "do not mix" — so the combination is refused, by name, rather than producing
    a table that looks like the published one and is not.
    """
    with pytest.raises(SystemExit) as exc:
        bench.main(
            ["--all", "--jobs", "2", "--out", str(tmp_path / "out.md")]
        )
    assert exc.value.code == 2
    message = capsys.readouterr().err
    assert "--no-timings" in message
    for column in bench.WALL_CLOCK_COLUMNS:
        assert column in message
    assert not (tmp_path / "out.md").exists(), "a refused run wrote a report"


def test_jobs_with_nothing_to_apply_it_to_is_refused(tmp_path: Path) -> None:
    """`--scaling` and `--control-rate-hz` are not parallelised — their longest
    rung is most of their work, so six cores buy ~1.4x and a new determinism
    surface. A `--jobs` on such a run would do nothing at all, and silently
    doing nothing is what the flag must not do."""
    with pytest.raises(SystemExit) as exc:
        bench.main(
            [
                "--scaling",
                "--jobs",
                "2",
                "--no-timings",
                "--out",
                str(tmp_path / "out.md"),
            ]
        )
    assert exc.value.code == 2


def test_nothing_in_the_benchmark_reads_results_in_completion_order() -> None:
    """The claim `_in_submission_order` makes about the rest of the file, checked.

    `concurrent.futures.as_completed` is the one-line way to make this report
    order-dependent, and it is the natural thing to reach for when adding a
    second parallel section later — the ordering test above only covers the
    function that exists today. Read out of the AST rather than grepped, so this
    file's own prose about `as_completed` is not what it finds.

    If a future caller genuinely needs completion order for something that is
    not assembled into the report, this assertion is the place to record why.
    """
    tree = ast.parse(Path(bench.__file__).read_text(encoding="utf-8"))
    used = [
        node
        for node in ast.walk(tree)
        if (isinstance(node, ast.Attribute) and node.attr == "as_completed")
        or (isinstance(node, ast.Name) and node.id == "as_completed")
    ]
    assert not used, (
        "reg.bench uses concurrent.futures.as_completed at line(s) "
        f"{[n.lineno for n in used]}. Completion order is a property of the "
        "machine; a report assembled in it is not reproducible (docs/plan.md "
        "rule 2). Results go back to their submission index before anything "
        "renders them."
    )


# ==========================================================================
# `bytes/hour` EXTRAPOLATES A SHORT RUN, AND EVERY SHAPE THAT PRINTS IT HAS TO
# SAY SO (issue #116).
#
# `bytes_per_hour` is `size * 3600 / run_seconds`, so the artifact's fixed
# schema-and-index cost is scaled to an hour alongside its per-frame cost. The
# resolution table disclosed that; the control-rate ladder — whose most-quoted
# number is a *ratio* between two of these figures, with the fixed term carried
# at both ends and a different share of the file at each — did not, and neither
# did the console summary. One disclosure travelling with one rendering of a
# number is a disclosure a reader can be shown the number without.
#
# The check is over this module's own AST rather than over a rendered report,
# because a rendered report only exercises the shapes a test happened to build.
# The shape added next milestone is inside this check on the day it is written.
# ==========================================================================

#: The one function that turns a figure into text. Everything that prints a
#: `bytes/hour` figure goes through it, which is what makes "every shape" a
#: question the AST can answer.
_FIGURE_RENDERER = "_bytes_per_hour_text"

#: The constant carrying the disclosure. A shape is compliant if it names this,
#: or calls a helper that does.
_DISCLOSURE = "BYTES_PER_HOUR_EXTRAPOLATION"


def _names_used(node: ast.AST) -> set[str]:
    """Every identifier mentioned anywhere inside `node`."""
    return {
        child.id if isinstance(child, ast.Name) else child.attr
        for child in ast.walk(node)
        if isinstance(child, (ast.Name, ast.Attribute))
    }


def bytes_per_hour_disclosure_verdict(source: str) -> tuple[str, list[str]]:
    """Verdict on whether every shape printing `bytes/hour` discloses what it is.

    A **shape** is a top-level function whose body renders a `bytes/hour` figure.
    It is compliant if it names `BYTES_PER_HOUR_EXTRAPOLATION` itself or calls a
    function that does — one level of indirection, which is what lets the two
    disclosure helpers exist without every caller restating the sentence.

    Three-valued, and the third is not a pass: a source with nothing that prints
    the figure comes back `COULD-NOT-EVALUATE`, because renaming the renderer is
    otherwise a way to make this check find nothing and go green.

    Returns the verdict and the names of the offending shapes.
    """
    tree = ast.parse(source)
    functions = {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    disclosing = {
        name
        for name, node in functions.items()
        if _DISCLOSURE in _names_used(node)
    }
    shapes = {
        name: node
        for name, node in functions.items()
        if _FIGURE_RENDERER in _names_used(node) and name != _FIGURE_RENDERER
    }
    if not shapes:
        return COULD_NOT_EVALUATE, []
    missing = sorted(
        name
        for name, node in shapes.items()
        if not (_names_used(node) & (disclosing | {_DISCLOSURE}))
    )
    return (DISAGREE if missing else AGREE), missing


#: The report shapes that print a `bytes/hour` figure today. Pinned for the
#: reason every roster in this repository is pinned: the check above is
#: satisfied by a source with no shapes in it, so on its own it would go green
#: if the figure stopped being published at all. A gain is fine and belongs
#: here once it discloses; a loss means a publication site disappeared.
BYTES_PER_HOUR_SHAPES = frozenset(
    {"_resolution_section", "_control_rate_section", "main"}
)


def test_every_report_shape_that_prints_bytes_per_hour_discloses_the_extrapolation() -> None:
    """**THE TEST THIS HALF OF ISSUE #116 EXISTS FOR.**"""
    source = Path(bench.__file__).read_text(encoding="utf-8")
    verdict, missing = bytes_per_hour_disclosure_verdict(source)
    assert verdict == AGREE, (
        f"reg.bench renders a bytes/hour figure in {missing} without naming "
        f"{_DISCLOSURE}. That figure scales the artifact's fixed "
        "schema-and-index cost to an hour along with its per-frame cost; a "
        "shape that prints it without saying so publishes an extrapolation as "
        "a measurement (issue #116)."
    )


def test_the_shapes_that_print_the_figure_are_the_ones_expected() -> None:
    """Silence is not a pass at the corpus level either."""
    source = Path(bench.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    shapes = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and _FIGURE_RENDERER in _names_used(node)
        and node.name != _FIGURE_RENDERER
    }
    assert shapes == set(BYTES_PER_HOUR_SHAPES), (
        "the set of report shapes printing a bytes/hour figure has moved: "
        f"gained {sorted(shapes - BYTES_PER_HOUR_SHAPES)}, lost "
        f"{sorted(BYTES_PER_HOUR_SHAPES - shapes)}. A gain needs adding here "
        "and needs to carry the disclosure; a loss means the figure is no "
        "longer published where the check above expects it."
    )


def test_a_shape_that_prints_the_figure_with_no_disclosure_is_caught() -> None:
    """**The negative test.** The exact shape issue #116 was filed about: a
    figure printed, correctly, with nothing saying what it extrapolates."""
    verdict, missing = bytes_per_hour_disclosure_verdict(
        "def _some_new_section(point):\n"
        "    return [_bytes_per_hour_text(point.bytes_per_hour)]\n"
    )
    assert verdict == DISAGREE
    assert missing == ["_some_new_section"]


def test_a_source_that_prints_no_figure_is_not_a_pass() -> None:
    """Renaming the renderer must not be a way to go green."""
    verdict, missing = bytes_per_hour_disclosure_verdict(
        "def _some_new_section(point):\n    return [str(point.size_bytes)]\n"
    )
    assert verdict == COULD_NOT_EVALUATE
    assert missing == []


def test_the_disclosure_line_says_the_same_thing_as_the_markdown() -> None:
    """The console shape renders the constant rather than restating it, so the
    two cannot drift into saying different things about one number."""
    line = bench._bytes_per_hour_disclosure_line(59.98)
    assert "extrapolates" in line and "overstates" in line
    assert "59.98 s" in line
    assert "*" not in line and "`" not in line, (
        "the console disclosure carries markdown emphasis; it is printed to a "
        "terminal, not rendered."
    )


def test_the_control_rate_ladder_discloses_the_extrapolation(rate_ladder) -> None:
    """The shape that was missing it, in a rendered report."""
    report = render([], sensor_multiplier=None, control_rates=rate_ladder, **_RENDER_ARGS)
    section = report.split("## What the control rate costs", 1)[1]
    assert "extrapolates a run shorter than an hour" in section
    assert f"{rate_ladder[0].run_seconds:,.2f} s" in section


# ==========================================================================
# WHY THE BYTES GROW MORE SLOWLY THAN THE RATE (issue #116).
#
# The ladder's most-quoted result is that the occurrence level costs ~15.8x as
# much per robot-hour for a 20x rate increase, and the cause published beside it
# was a term far too small to produce it. The repair is not a better sentence:
# it is `dbstat`, per table, at each rung, and the arithmetic that follows.
# ==========================================================================


def _has_dbstat(ladder) -> bool:
    return all(
        point.level(level).tables is not None
        for point in ladder
        for level in bench.RESOLUTION_LEVELS
    )


def test_every_level_carries_its_own_byte_attribution(rate_ladder) -> None:
    """The measurement exists, per level, and sums to the file it describes.

    `dbstat`'s per-table bytes sum to the file size less its free pages, so the
    attribution is an attribution rather than a sample: it may be smaller than
    the file and may never be larger.
    """
    if not _has_dbstat(rate_ladder):
        pytest.skip("this SQLite build has no dbstat virtual table")
    for point in rate_ladder:
        for level in bench.RESOLUTION_LEVELS:
            tables = point.level(level).tables
            assert set(tables) <= {*bench._TABLE_LABELS, bench.INDEX_LABEL}
            attributed = sum(tables.values())
            assert 0 < attributed <= point.level(level).size_bytes


def test_the_report_attributes_the_sublinearity_rather_than_asserting_it(
    rate_ladder,
) -> None:
    """**THE TEST THE OTHER HALF OF ISSUE #116 EXISTS FOR.**

    The section must name the tables the rate does not move, in bytes, and the
    ratio the rest grew by. Asserted as shape and as arithmetic — the fixture's
    two rates are 30 frames apart and which tables happen to freeze there is not
    a property worth pinning.
    """
    if not _has_dbstat(rate_ladder):
        pytest.skip("this SQLite build has no dbstat virtual table")
    report = render([], sensor_multiplier=None, control_rates=rate_ladder, **_RENDER_ARGS)
    section = report.split("#### Where the `occurrence` bytes are", 1)[1]
    assert "Could not be attributed" not in section
    assert "share of the shortfall" in section
    assert "is an identity, not a model" in section
    assert f"`{bench.INDEX_LABEL}`" in section


def test_without_dbstat_the_cause_is_a_could_not_evaluate_and_not_a_story(
    rate_ladder,
) -> None:
    """**The negative test.** Feed it the condition it guards against: an
    artifact whose bytes cannot be attributed. The section must say the cause
    is not established, and must not fall back to the plausible one."""
    blinded = tuple(
        dataclasses.replace(
            point,
            curve=dataclasses.replace(
                point.curve,
                points=tuple(
                    dataclasses.replace(level_point, tables=None)
                    for level_point in point.curve.points
                ),
            ),
        )
        for point in rate_ladder
    )
    report = render([], sensor_multiplier=None, control_rates=blinded, **_RENDER_ARGS)
    section = report.split("#### Where the `occurrence` bytes are", 1)[1]
    assert "Could not be attributed" in section
    assert "the cause of the sublinearity is not stated in this report" in section
    assert "share of the shortfall" not in section


def test_the_shortfall_is_an_identity_on_a_hand_worked_example() -> None:
    """The arithmetic, on numbers a reader can check by eye.

    Two tables, a 10x rate increase, one table that grew with the rate and one
    that did not move at all. The entries sum to the total by construction and
    that is the property: a decomposition with a remainder would let the largest
    contributor be whatever the remainder was hiding.
    """
    per_table, total = bench.sublinearity_shortfall(
        {"scales": 100, "does not": 100}, {"scales": 1_000, "does not": 100}, 10.0
    )
    assert per_table == {"scales": 0.0, "does not": 900.0}
    assert total == pytest.approx(900.0)
    assert sum(per_table.values()) == pytest.approx(total)


def test_a_table_that_grew_faster_than_the_rate_is_a_negative_contribution() -> None:
    """Sublinearity is not assumed. A table that outgrew the rate reduces the
    gap rather than being clipped to zero, and a whole artifact that outgrew it
    comes back with a non-positive total."""
    per_table, total = bench.sublinearity_shortfall(
        {"greedy": 100}, {"greedy": 3_000}, 10.0
    )
    assert per_table["greedy"] == pytest.approx(-2_000.0)
    assert total == pytest.approx(-2_000.0)


def test_the_shortfall_refuses_a_multiple_that_is_not_one() -> None:
    """A ratio against a non-positive multiple is not a quantity."""
    for bad in (0.0, -2.0, float("nan"), float("inf")):
        with pytest.raises(BenchError, match="rate multiple"):
            bench.sublinearity_shortfall({"a": 1}, {"a": 2}, bad)


def test_an_artifact_that_outgrew_the_rate_reports_no_shortfall(rate_ladder) -> None:
    """**The other negative test.** The section must not narrate a sublinearity
    that is not in the numbers: feed it a high-rate artifact that grew faster
    than the rate and it has to say there is nothing to attribute."""
    if not _has_dbstat(rate_ladder):
        pytest.skip("this SQLite build has no dbstat virtual table")
    inflated = list(rate_ladder)
    high = inflated[-1]
    inflated[-1] = dataclasses.replace(
        high,
        curve=dataclasses.replace(
            high.curve,
            points=tuple(
                dataclasses.replace(
                    p, tables={k: v * 10_000 for k, v in p.tables.items()}
                )
                for p in high.curve.points
            ),
        ),
    )
    report = render(
        [], sensor_multiplier=None, control_rates=tuple(inflated), **_RENDER_ARGS
    )
    section = report.split("#### Where the `occurrence` bytes are", 1)[1]
    assert "There is no shortfall to attribute" in section
    assert "share of the shortfall" not in section
