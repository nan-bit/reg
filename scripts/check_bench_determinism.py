#!/usr/bin/env python3
"""Run `reg.bench` twice at one seed and fail if the reports differ (issue #75).

WHY THIS EXISTS
---------------
CI has checked `reg.sim` for determinism since the workflow was written. It has
never checked `reg.bench` — and `reg.bench` is what produces every published
figure in `docs/plan.md`, `docs/sensor-baseline.md`, `docs/sufficiency.md` and
`README.md`. "Same seed, same bytes" (docs/plan.md rule 2) was verified by hand
on the one command it matters most for. Verified by hand is not verified.

WHAT IT COMPARES, AND WHAT IT DOES NOT
--------------------------------------
Both runs are made with `--no-timings`, so the reports carry no wall-clock
figures at all and the comparison is an exact byte comparison of whole files.
The exclusion is therefore **structural**: it is the three columns
`reg.bench.WALL_CLOCK_COLUMNS` names, removed at render time, and nothing else.
No text filter runs here, which is deliberate — a filter dropping lines matching
`ms` would also drop the word "samples", and the scaling section quotes robot
time in seconds, so a filter on "s" or "seconds" would swallow real figures. The
measurement is unchanged by the flag: the query is still timed, the repeats still
run, the answers and verdicts in the compared report still come out of them.

WHAT IT DOES WHEN IT CANNOT TELL
--------------------------------
It says so, and that never resolves to a pass in the way that matters. A missing
`reg.bench`, or one too old to have `--no-timings`, is reported as SKIPPED and
exits 0 — the model is the `reg.sim` step's comment, "a check that cannot fail
yet must at least say so". Everything else — a run that exited non-zero, a report
that was not written, reports that differ — exits 1. An unreadable or absent
report is a could-not-evaluate and is treated as a failure, not as agreement.

USAGE
-----
    python scripts/check_bench_determinism.py --seed 0 -- <bench arguments>

The bench arguments are required and are not defaulted here: which run CI makes
is a choice a reader of the workflow should be able to see in the workflow, not
one buried in this file. `--second-seed` runs the second pass at a different seed
and is how the check is shown able to fail; see
`tests/test_bench_determinism.py`.

THE WORKFLOW STEP THIS IS WAITING FOR
-------------------------------------
`.github/workflows/**` is the machinery that runs the unattended writer and the
writer does not edit it (CLAUDE.md, docs/CONTRIBUTING.md "What is off limits"),
so the CI wiring is a human's to paste in. Until it is, this check runs only when
someone runs it. The step, to go after the existing `reg.sim` one, which stays
exactly as it is:

    - name: Determinism — reg.bench, which produces every published figure
      # ~20 s: one scenario, one ladder rung and the resolution curve, all at
      # 300 frames and 4 envelope samples. Not `--all`, which would add minutes
      # and cover no additional code path — every section of the report is
      # rendered by this run. Both passes use --no-timings, so the comparison is
      # an exact `cmp` and the exclusion is three named columns rather than a
      # text filter.
      run: >-
        python scripts/check_bench_determinism.py --seed 0 --
        --scenario contact --n-samples 4
        --scaling --scaling-frames 300 --scaling-n-samples 4
        --resolution --resolution-frames 300 --resolution-n-samples 4
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Sequence

#: Exit codes. 2 is argparse's own usage exit and is not raised here.
EXIT_OK = 0
EXIT_FAIL = 1

#: How many lines of the difference to print. Enough to identify which table
#: moved; not so many that a whole report scrolls past in a CI log.
DIFF_LINES = 40


def _bench_help() -> str | None:
    """`reg.bench --help`, or None if the module is not there to ask.

    Asking the installed module rather than importing a constant from it: this
    script's job is to check the command CI runs, so what matters is what that
    command supports.
    """
    try:
        import reg.bench  # noqa: F401
    except Exception:
        return None
    proc = subprocess.run(
        [sys.executable, "-m", "reg.bench", "--help"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout


def _run(bench_args: Sequence[str], *, seed: int, out: Path) -> int:
    argv = [
        sys.executable,
        "-m",
        "reg.bench",
        *bench_args,
        "--no-timings",
        "--seed",
        str(seed),
        "--out",
        str(out),
    ]
    print(f"$ {Path(sys.executable).name} {' '.join(argv[1:])}", flush=True)
    proc = subprocess.run(argv, stdout=subprocess.PIPE, text=True)
    if proc.stdout:
        print(proc.stdout.rstrip(), flush=True)
    return proc.returncode


def _read(path: Path) -> bytes | None:
    try:
        data = path.read_bytes()
    except OSError:
        return None
    return data or None


def _diff(a: str, b: str, name_a: str, name_b: str) -> list[str]:
    import difflib

    lines = list(
        difflib.unified_diff(
            a.splitlines(), b.splitlines(), fromfile=name_a, tofile=name_b, lineterm=""
        )
    )
    if len(lines) > DIFF_LINES:
        return [*lines[:DIFF_LINES], f"... {len(lines) - DIFF_LINES} more diff lines"]
    return lines


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python scripts/check_bench_determinism.py",
        description=(
            "Run `python -m reg.bench` twice with --no-timings and compare the "
            "two reports byte for byte."
        ),
    )
    parser.add_argument(
        "--seed",
        type=int,
        required=True,
        metavar="N",
        help=(
            "simulator seed for both runs. Required and not defaulted: a "
            "determinism check whose seed nobody stated is a check nobody can "
            "reproduce."
        ),
    )
    parser.add_argument(
        "--second-seed",
        type=int,
        default=None,
        metavar="N",
        help=(
            "seed for the second run (default: --seed, which is the check). Give "
            "a different value to perturb the second run on purpose and confirm "
            "the comparison reports a difference — that is the negative test, not "
            "a mode CI runs."
        ),
    )
    parser.add_argument(
        "--keep-dir",
        metavar="PATH",
        help=(
            "write the two reports here and leave them behind, instead of in a "
            "temporary directory that is deleted afterwards."
        ),
    )
    parser.add_argument(
        "bench_args",
        nargs="+",
        metavar="BENCH_ARG",
        help=(
            "the `reg.bench` arguments naming the run to make, after a literal "
            "`--`. Required: this script does not choose the benchmark. --seed, "
            "--out and --no-timings are supplied by this script and must not "
            "appear here."
        ),
    )
    args = parser.parse_args(argv)

    supplied_here = {"--seed", "--out", "--no-timings"}
    # `--seed=0` as well as `--seed 0`: the same clash written the other way,
    # and one that argparse in the child would resolve silently in favour of
    # whichever came last.
    clash = sorted(
        supplied_here.intersection(arg.split("=", 1)[0] for arg in args.bench_args)
    )
    if clash:
        parser.error(
            f"{', '.join(clash)} is supplied by this script; passing it in the "
            "bench arguments would make it ambiguous which run was compared"
        )

    help_text = _bench_help()
    if help_text is None:
        print(
            "reg.bench could not be run — determinism check SKIPPED, not passed.",
            flush=True,
        )
        return EXIT_OK
    if "--no-timings" not in help_text:
        print(
            "this reg.bench has no --no-timings, so the wall-clock columns cannot "
            "be excluded structurally — determinism check SKIPPED, not passed.",
            flush=True,
        )
        return EXIT_OK

    second_seed = args.seed if args.second_seed is None else args.second_seed
    if second_seed != args.seed:
        print(
            f"NOTE: the second run uses seed {second_seed}, not {args.seed}. This "
            "is the deliberately perturbed mode: a difference below is the "
            "expected result, not a determinism failure.",
            flush=True,
        )

    work = Path(args.keep_dir) if args.keep_dir else Path(tempfile.mkdtemp(prefix="reg-det-"))
    work.mkdir(parents=True, exist_ok=True)
    path_a, path_b = work / "a.md", work / "b.md"
    try:
        for path, seed in ((path_a, args.seed), (path_b, second_seed)):
            code = _run(args.bench_args, seed=seed, out=path)
            if code != 0:
                print(
                    f"reg.bench exited {code} writing {path.name}, so the two runs "
                    "were never compared. COULD NOT EVALUATE — treated as a "
                    "failure, because it is not agreement.",
                    flush=True,
                )
                return EXIT_FAIL

        data_a, data_b = _read(path_a), _read(path_b)
        if data_a is None or data_b is None:
            missing = ", ".join(
                p.name for p, d in ((path_a, data_a), (path_b, data_b)) if d is None
            )
            print(
                f"no report to compare ({missing} absent or empty). COULD NOT "
                "EVALUATE — treated as a failure, because it is not agreement.",
                flush=True,
            )
            return EXIT_FAIL

        if data_a == data_b:
            if second_seed != args.seed:
                print(
                    f"IDENTICAL ACROSS SEEDS {args.seed} and {second_seed}. This "
                    "was the perturbed mode, where a difference was expected: "
                    "either the seed moves no figure in this run, or the "
                    "comparison is not looking at what it claims to.",
                    flush=True,
                )
                return EXIT_FAIL
            print(
                f"deterministic: {len(data_a)} identical bytes across two runs at "
                f"seed {args.seed}, wall-clock columns excluded by --no-timings "
                "and nothing else excluded.",
                flush=True,
            )
            return EXIT_OK

        if second_seed != args.seed:
            print(
                f"DIFFERENT, as expected: seed {args.seed} and seed {second_seed} "
                "produced different reports. The comparison can fail.",
                flush=True,
            )
        else:
            print(
                f"NOT DETERMINISTIC — the same command at seed {args.seed} "
                "produced different reports, and no wall-clock figure is in "
                "either of them.",
                flush=True,
            )
        for line in _diff(
            data_a.decode("utf-8", "replace"),
            data_b.decode("utf-8", "replace"),
            path_a.name,
            path_b.name,
        ):
            print(line, flush=True)
        return EXIT_FAIL
    finally:
        if not args.keep_dir:
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
