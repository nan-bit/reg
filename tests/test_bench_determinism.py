"""`--no-timings` and the CI check built on it (issue #75).

WHAT IS BEING TESTED, AND WHY IT IS ITS OWN FILE
------------------------------------------------
CI has run `reg.sim` twice and compared bytes since the workflow existed. It has
never run `reg.bench` twice — and `reg.bench` is what produces every published
figure. `scripts/check_bench_determinism.py` closes that, and this file is what
shows the check can fail: a determinism check that has only ever been shown
identical inputs has not been shown to work at all.

THE TWO THINGS THAT CAN GO WRONG, AND THE TESTS FOR EACH
--------------------------------------------------------
1. **The exclusion swallows a real difference.** The three wall-clock columns are
   legitimately non-reproducible and must be excluded; anything else excluded
   with them would be a difference the check stops seeing. So the exclusion is
   asserted from both sides: two results differing *only* in their timings render
   identically under `--no-timings`
   (`test_two_results_differing_only_in_the_clock_render_identically`), and the
   figures a textual filter would have swallowed — the robot-time seconds in the
   scaling section, the word "samples" — are asserted still present
   (`test_no_timings_leaves_the_robot_time_seconds_alone`).
2. **The check cannot fail.** `test_the_check_reports_a_difference_when_the_second_run_is_perturbed`
   runs the real script with a perturbed second seed and asserts it says no, and
   every could-not-evaluate path — bench exited non-zero, no report written, a
   `reg.bench` too old to have the flag — is asserted to *not* come out as a
   pass.

The live runs here use the shortest scenario at the coarsest legal envelope
parameters, for the reason `tests/test_bench.py` gives: nothing in this file is
about envelope fidelity, and the property under test is byte equality.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

from reg import bench, graph, store
from reg.bench import (
    AGREE,
    WALL_CLOCK_COLUMNS,
    ScalingPoint,
    ScenarioResult,
    SeparationCheck,
    Sizes,
    Timing,
    render,
)
from reg.tolerances import DISTANCE_TOL_M

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "check_bench_determinism.py"

#: The cheapest live run that still goes through the whole artifact path: the
#: shortest scenario, four envelope samples (the corner count for the demo arm,
#: i.e. the smallest legal value) and one substep of the horizon.
TINY_RUN = [
    "--scenario",
    "no_declaration",
    "--n-samples",
    "4",
    "--horizon",
    "0.05",
    "--substep-dt",
    "0.05",
]

_RENDER_ARGS = {
    "seed": 0,
    "horizon": 0.2,
    "n_samples": 512,
    "envelope_seed": 0,
    "substep_dt": 0.02,
    "occurrence_resolution_s": graph.OCCURRENCE_TIME_RESOLUTION_S,
    "sensor_multiplier": None,
}


def _result(*, graph_seconds: float, csv_seconds: float) -> ScenarioResult:
    """One hand-built result. Only the two wall-clock figures are parameters."""
    return ScenarioResult(
        scenario="fixture",
        frames=100,
        nodes={kind: 1 for kind in store.NODE_TABLES},
        edges={edge_type: 2 for edge_type in store.EDGE_SPECS},
        sizes=Sizes(raw_csv=20_000, gzip_csv=2_000, sqlite=1_000, gzip_sqlite=400),
        check=SeparationCheck(
            verdict=AGREE,
            graph_answer=0.12,
            csv_answer=0.123,
            tolerance=DISTANCE_TOL_M,
            graph_timing=Timing(seconds=graph_seconds, repeats=3),
            csv_timing=Timing(seconds=csv_seconds, repeats=3),
        ),
        tables={"envelope": 500, "edge": 500},
    )


def _query_section(report: str) -> list[str]:
    """The lines of `## Query wall-clock`, up to the next section.

    By section rather than by pattern-matching a header row: `## Where the bytes
    are` also has a `scenario` column and a `verdict` one (the node table), so a
    test that went looking for the first matching row would assert about the
    wrong table and pass for the wrong reason.
    """
    lines = report.splitlines()
    start = lines.index("## Query wall-clock")
    rest = lines[start + 1 :]
    end = next((i for i, line in enumerate(rest) if line.startswith("## ")), len(rest))
    return rest[:end]


def _query_table_header(report: str) -> str:
    return next(line for line in _query_section(report) if line.startswith("| scenario |"))


def _script(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )


@pytest.fixture(scope="module")
def check_module():
    """`scripts/check_bench_determinism.py` imported by path.

    It is a script, not part of the `reg` package — CI machinery is not the
    product (CLAUDE.md) — so the could-not-evaluate paths are reached by
    importing it here rather than by making it importable as `reg.something`.
    """
    spec = importlib.util.spec_from_file_location("check_bench_determinism", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --------------------------------------------------------------------------
# What the flag removes, and what it must leave alone.
# --------------------------------------------------------------------------


def test_the_wall_clock_columns_are_there_unless_the_flag_is_given() -> None:
    """The positive control. Without it, a report that lost its timings for some
    other reason would make every test below pass."""
    header = _query_table_header(
        render([_result(graph_seconds=0.0002, csv_seconds=0.05)], **_RENDER_ARGS)
    )
    for column in WALL_CLOCK_COLUMNS:
        assert f"| {column} |" in header


def test_no_timings_removes_exactly_the_wall_clock_columns() -> None:
    header = _query_table_header(
        render(
            [_result(graph_seconds=0.0002, csv_seconds=0.05)],
            timings=False,
            **_RENDER_ARGS,
        )
    )
    for column in WALL_CLOCK_COLUMNS:
        assert f"| {column} |" not in header
    # And nothing else in that table goes: the verdict *is* the check on Claim 1,
    # and a determinism check comparing a report with no verdict in it would be
    # comparing the header block.
    for column in ("graph answer", "CSV answer", "difference", "verdict"):
        assert f"| {column} |" in header


def test_no_timings_keeps_the_verdict_row_itself() -> None:
    report = render(
        [_result(graph_seconds=0.0002, csv_seconds=0.05)],
        timings=False,
        **_RENDER_ARGS,
    )
    row = next(line for line in _query_section(report) if line.startswith("| `fixture` |"))
    assert row.endswith("| AGREE |")
    assert "0.1200 m" in row and "0.1230 m" in row


def test_two_results_differing_only_in_the_clock_render_identically() -> None:
    """The property the whole check rests on. Two runs at one seed differ in the
    timings and in nothing else, so under `--no-timings` they must be the same
    bytes — and with the timings in, they must not, or the flag is excluding
    something that was never varying."""
    fast = _result(graph_seconds=0.0002, csv_seconds=0.05)
    slow = _result(graph_seconds=0.0009, csv_seconds=0.31)

    assert render([fast], **_RENDER_ARGS) != render([slow], **_RENDER_ARGS)
    assert render([fast], timings=False, **_RENDER_ARGS) == render(
        [slow], timings=False, **_RENDER_ARGS
    )


def test_a_real_difference_still_shows_under_no_timings() -> None:
    """The other half: the flag must not be a way of hiding a moved figure. A
    different byte count is a different report with the timings gone."""
    one = _result(graph_seconds=0.0002, csv_seconds=0.05)
    other = ScenarioResult(
        **{
            **{f.name: getattr(one, f.name) for f in one.__dataclass_fields__.values()},
            "sizes": Sizes(raw_csv=20_001, gzip_csv=2_000, sqlite=1_000, gzip_sqlite=400),
        }
    )
    assert render([one], timings=False, **_RENDER_ARGS) != render(
        [other], timings=False, **_RENDER_ARGS
    )


def test_no_timings_leaves_the_robot_time_seconds_alone() -> None:
    """The failure mode issue #75 names. A filter dropping lines matching `ms`
    would take the word "samples" with it, and one matching seconds would take
    the scaling section's *robot* time — which is `(frames - 1) * dt`, a
    deterministic figure and one of the study's results. The exclusion is
    structural precisely so that neither is possible; this asserts it."""
    point = ScalingPoint(
        result=_result(graph_seconds=0.0002, csv_seconds=0.05),
        n_samples=16,
        frame_period_s=0.02,
    )
    report = render([], scaling=[point], timings=False, **_RENDER_ARGS)
    # (100 - 1) frames * 0.02 s, in the ladder's own row.
    assert any(
        line.startswith("| 100 | 2.0 s |") for line in report.splitlines()
    ), "the ladder's robot-time column went with the wall-clock ones"
    assert "| envelope samples | 16 |" in report


def test_the_timing_repeats_row_does_not_claim_a_table_that_is_not_there() -> None:
    """The repeats still happen — the answers come out of them — so the row stays
    and states the protocol the numbers were measured under. What it must not do
    is describe the precision of a table this report does not contain."""
    with_timings = render([_result(graph_seconds=0.1, csv_seconds=0.2)], **_RENDER_ARGS)
    without = render(
        [_result(graph_seconds=0.1, csv_seconds=0.2)], timings=False, **_RENDER_ARGS
    )
    assert "| timing repeats | 3 | precision of the wall-clock table only |" in with_timings
    assert "| timing repeats | 3 |" in without
    assert "precision of the wall-clock table only" not in without


def test_the_cli_flag_reaches_the_report(tmp_path: Path, monkeypatch) -> None:
    """`--no-timings` on the command line, not just `timings=False` in Python."""
    seen: dict[str, object] = {}
    real_render = bench.render

    def spy(*args, **kwargs):
        seen.update(kwargs)
        return real_render(*args, **kwargs)

    monkeypatch.setattr(bench, "render", spy)
    out = tmp_path / "r.md"
    code = bench.main(
        [*TINY_RUN, "--seed", "0", "--no-timings", "--out", str(out)]
    )
    assert code == 0
    assert seen["timings"] is False
    header = _query_table_header(out.read_text(encoding="utf-8"))
    for column in WALL_CLOCK_COLUMNS:
        assert f"| {column} |" not in header


def test_without_the_flag_the_cli_still_reports_timings(tmp_path: Path) -> None:
    out = tmp_path / "r.md"
    assert bench.main([*TINY_RUN, "--seed", "0", "--out", str(out)]) == 0
    header = _query_table_header(out.read_text(encoding="utf-8"))
    for column in WALL_CLOCK_COLUMNS:
        assert f"| {column} |" in header


# --------------------------------------------------------------------------
# The check itself, end to end. The negative case is the one that matters.
# --------------------------------------------------------------------------


def test_the_check_passes_two_runs_at_one_seed() -> None:
    proc = _script("--seed", "0", "--", *TINY_RUN)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "deterministic:" in proc.stdout
    assert "identical bytes" in proc.stdout


def test_the_check_reports_a_difference_when_the_second_run_is_perturbed() -> None:
    """THE TEST THIS FILE EXISTS FOR. Feed the comparison the condition it
    guards against — a second run that is not the same run — and it must say no.
    The seed is perturbed rather than the file, so what moves is a published
    figure produced the way CI produces it."""
    proc = _script("--seed", "0", "--second-seed", "3", "--", *TINY_RUN)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "DIFFERENT, as expected" in proc.stdout
    # And it must show *which* figures moved, not just that something did: a red
    # CI step nobody can localise gets rerun until it goes green.
    assert any(line.startswith("-| ") for line in proc.stdout.splitlines())
    assert "deterministic:" not in proc.stdout


def test_a_bench_that_exited_non_zero_is_a_failure_not_a_pass() -> None:
    """Could-not-evaluate never resolves to pass (CLAUDE.md). An unknown scenario
    makes `reg.bench` exit before writing anything; two reports that were never
    produced are not two identical reports."""
    proc = _script("--seed", "0", "--", "--scenario", "not_a_scenario")
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "COULD NOT EVALUATE" in proc.stdout
    assert "deterministic:" not in proc.stdout


def test_a_report_that_was_never_written_is_a_failure(check_module, monkeypatch) -> None:
    """The same rule one level down: a run that claims success and leaves no file
    is silence, and silence is not agreement."""
    monkeypatch.setattr(check_module, "_run", lambda *a, **k: 0)
    code = check_module.main(["--seed", "0", "--", *TINY_RUN])
    assert code == check_module.EXIT_FAIL


def test_identical_reports_across_two_different_seeds_is_a_failure(
    check_module, monkeypatch
) -> None:
    """The perturbed mode is a check on the check. If the seeds differ and the
    bytes do not, the comparison is not looking at what it claims to — reporting
    that as a pass would be the exact false green this issue is about."""

    def write(bench_args, *, seed, out):
        out.write_text("same bytes whatever the seed\n", encoding="utf-8")
        return 0

    monkeypatch.setattr(check_module, "_run", write)
    code = check_module.main(["--seed", "0", "--second-seed", "1", "--", *TINY_RUN])
    assert code == check_module.EXIT_FAIL


@pytest.mark.parametrize(
    "help_text",
    [None, "usage: python -m reg.bench [--all] [--scaling]\n"],
    ids=["bench-absent", "bench-without-the-flag"],
)
def test_it_skips_loudly_rather_than_passing_silently(
    check_module, monkeypatch, capsys, help_text
) -> None:
    """The `reg.sim` step's model, and its comment: a check that cannot fail yet
    must at least say so. It exits 0 — a `reg.bench` that predates the flag is
    not a determinism failure — but it must never print anything a reader would
    take for a pass."""
    monkeypatch.setattr(check_module, "_bench_help", lambda: help_text)
    code = check_module.main(["--seed", "0", "--", *TINY_RUN])
    out = capsys.readouterr().out
    assert code == check_module.EXIT_OK
    assert "SKIPPED, not passed" in out
    assert "deterministic:" not in out


@pytest.mark.parametrize("clash", ["--seed", "--out", "--no-timings"])
@pytest.mark.parametrize("form", ["separate", "equals"])
def test_it_refuses_bench_arguments_it_supplies_itself(clash: str, form: str) -> None:
    """Two `--seed`s would leave it ambiguous which run was compared, and a
    `--out` in the passed-through arguments would send a report somewhere the
    comparison never looks. `--seed=0` is the same clash written the other way."""
    extra = [clash, "9"] if form == "separate" else [f"{clash}=9"]
    proc = _script("--seed", "0", "--", *TINY_RUN, *extra)
    assert proc.returncode == 2
    assert clash in proc.stderr


def test_it_will_not_run_without_a_seed_or_without_a_benchmark() -> None:
    """No invented default for either (CLAUDE.md). A seed nobody stated is a
    check nobody can reproduce, and a benchmark this script chose for itself
    would be a run the workflow does not show."""
    assert _script("--", *TINY_RUN).returncode == 2
    assert _script("--seed", "0").returncode == 2
