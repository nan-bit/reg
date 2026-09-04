"""The simulator CLI — `python -m reg.sim`. **Layer B**: this emits ground truth.

    python -m reg.sim --list
    python -m reg.sim --scenario contact --seed 0 --out runs/contact.csv

This is the last piece of Phase 1 (docs/plan.md): a deterministic 2D world
producing a raw state stream. It is a thin composition — `reg.scenarios` owns the
fixtures, `reg.stream` owns the format — and deliberately has no simulation logic
of its own. There is no planner, no controller and no dynamics model here, and
none should arrive: docs/plan.md lists all three under non-goals.

WHAT THIS FILE IS ACTUALLY RESPONSIBLE FOR
------------------------------------------
Three things, and they are all about the run being reproducible afterwards:

**1. Provenance goes in the artifact.** The seed is written into the CSV as a
`#` block above the header (`reg.stream.COMMENT_PREFIX`), not into a sidecar
file, not into a filename. docs/lossiness.md keeps "the run's provenance —
scenario name, seed, tolerance constants in force, and the schema version, once
per artifact. Determinism is only checkable if the artifact says what produced
it." A sidecar is provenance that can be separated from the thing it describes.

**2. Nothing that varies between two runs of the same command may enter the
file.** No wall-clock time, no hostname, no output path — the determinism check
in CI writes `/tmp/a.csv` and `/tmp/b.csv` and compares bytes, so a path in the
banner would turn a check about the simulator into a check about `argv`. That
absence is load-bearing; `tests/test_sim_cli.py` asserts two different output
paths give identical bytes.

**3. An unknown scenario is a refusal, not a fallback.** `--scenario typo` exits
non-zero naming every valid name. Defaulting to one of them would produce a
complete, plausible, byte-identical-on-rerun artifact of the wrong situation.

THE BASE BLOCKS ARE NOT A FLAG HERE (issue #177)
------------------------------------------------
A scenario that drives its base yields frames carrying a `BasePose` and a
`BaseVelocity`, and `reg.stream.write_frames` derives the header from the
frames — so the two optional blocks issue #176 defined appear in the artifact
for a driving scenario and are absent for a fixed-base one, with nothing in this
file deciding it. That is deliberate: a switch here could write a mobile run out
as a fixed-base file, or grow eleven bolted-down fixtures a set of columns they
have nothing to put in, and either would move `expected_header(2, 3)` — the 24
columns Claim 1's published figures are measured on. What this file adds is the
provenance block above them, whose version already records that a header with no
base columns is a statement about the *run* (see `PROVENANCE_VERSION`).

ON `--seed` HAVING A DEFAULT
----------------------------
CLAUDE.md forbids inventing defaults, and the reason it gives is precise: an
invented number is *indistinguishable downstream from a supplied one*. `--seed 0`
is specified by issue #12 rather than invented here, and — the part that matters
— it is recorded in the artifact either way, so nothing downstream has to guess
which seed produced a file. `Scenario.states()` still takes a seed with no
default; the library never chooses one. Everything else the run needs (`--out`,
`--scenario`) has no default at all, because there is no correct guess for them.
"""

from __future__ import annotations

import argparse
import os
import sys
import textwrap
from collections.abc import Sequence
from pathlib import Path

from reg import __version__
from reg.scenarios import SCENARIOS, Scenario, scenario
from reg.stream import FLOAT_PRECISION, read_comments, write_frames

#: Usage errors exit with argparse's own code, so the shell sees one convention.
EXIT_OK = 0
EXIT_USAGE = 2

#: Version of the provenance block's field set, and of the stream schema the
#: block sits above. Bumped when a field is added, removed or renamed, so a
#: reader that meets an unfamiliar block can say it does not understand it rather
#: than silently finding no `seed=` and carrying on.
#:
#: **v2, issue #176.** `reg.stream` gained the two optional base blocks, so a
#: header with no base columns stopped being the only header this producer can
#: write. Under v1 that absence had exactly one meaning — this format has no base
#: columns at all — and a reader was entitled to conclude it from the version
#: alone. Under v2 it means *this run recorded no base*, which is a statement
#: about the run. Those are different facts, and the version is what tells them
#: apart in a file already written.
PROVENANCE_VERSION = 2

#: Written into every artifact; see "ON `--seed` HAVING A DEFAULT" above.
DEFAULT_SEED = 0

#: First line of the block. A file that does not start with this states nothing
#: about what produced it.
PROVENANCE_BANNER = f"reg-sim provenance v{PROVENANCE_VERSION}"


def provenance(scn: Scenario, seed: int) -> list[str]:
    """The `key=value` lines recording what produced a stream.

    Every value here is a property of the *run*, fixed by (scenario, seed). If you
    add a field, add one that two runs of the same command agree on.
    """
    return [
        PROVENANCE_BANNER,
        f"reg_version={__version__}",
        f"scenario={scn.name}",
        f"seed={seed}",
        f"dt={scn.dt}",
        f"duration={scn.duration}",
        f"frames={scn.n_frames}",
        f"float_precision={FLOAT_PRECISION}",
    ]


def parse_provenance(path: str | os.PathLike[str]) -> dict[str, str]:
    """Read a stream's provenance block back as a mapping. `{}` if it has none.

    An empty mapping means the file does not say what produced it — a
    could-not-evaluate, and callers must not read it as "the defaults were used".
    Values stay strings: this returns what the file says, and turning `seed=0`
    into an int is a decision for whoever is comparing it to something.
    """
    fields: dict[str, str] = {}
    for line in read_comments(path):
        key, sep, value = line.partition("=")
        if sep:
            fields[key.strip()] = value.strip()
    return fields


def simulate(name: str, seed: int, out: str | os.PathLike[str]) -> Path:
    """Write the raw stream for one scenario at one seed. Returns the path.

    Raises `KeyError` naming the valid scenarios if `name` is not one of them, and
    `TypeError` if `seed` is not an int (both from the layers below — this
    function adds no leniency of its own).
    """
    scn = scenario(name)
    frames = tuple(scn.states(seed))
    path = Path(out)
    # `runs/` is gitignored and will not exist on a fresh clone. Creating it is
    # not inventing anything: the caller named the path, this only makes it
    # writable. An existing file at that path is overwritten, as `write_frames`
    # has always done.
    path.parent.mkdir(parents=True, exist_ok=True)
    return write_frames(frames, path, comments=provenance(scn, seed))


def _seed(raw: str) -> int:
    try:
        value = int(raw)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{raw!r} is not an integer") from None
    if value < 0:
        raise argparse.ArgumentTypeError(
            f"{value}: seeds must be >= 0 (numpy's SeedSequence rejects negative "
            "entropy). Refusing rather than taking the absolute value, which "
            "would make two runs labelled with different seeds identical."
        )
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m reg.sim",
        description=(
            "Write the deterministic ground-truth state stream for one named "
            "scenario. Same scenario and seed, same bytes."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--scenario",
        metavar="NAME",
        help=f"one of: {', '.join(SCENARIOS)}",
    )
    parser.add_argument(
        "--seed",
        type=_seed,
        default=DEFAULT_SEED,
        metavar="N",
        help=(
            f"perturbs the scenario waypoints (default: {DEFAULT_SEED}). Recorded "
            "in the output either way, so an artifact never leaves it ambiguous."
        ),
    )
    parser.add_argument(
        "--out",
        metavar="PATH",
        help="CSV to write; parent directories are created. No default.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="print the scenario names and what each one is for, then exit",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)

    if args.list:
        for name, scn in SCENARIOS.items():
            print(name)
            print(
                textwrap.fill(
                    scn.description,
                    width=76,
                    initial_indent="    ",
                    subsequent_indent="    ",
                )
            )
        return EXIT_OK

    # Both are required, but not `required=True`: that would make `--list`
    # impossible to run on its own.
    if args.scenario is None:
        parser.error(
            "--scenario is required and has no default. Run --list for the names."
        )
    if args.out is None:
        parser.error(
            "--out is required and has no default: writing an audit artifact to a "
            "path nobody named is how runs get lost."
        )

    try:
        path = simulate(args.scenario, args.seed, args.out)
    except KeyError as exc:
        # `reg.scenarios.scenario` raises with the full list of valid names. The
        # alternative — picking one — writes a perfectly well-formed artifact of
        # a situation nobody asked about.
        print(f"error: {exc.args[0]}", file=sys.stderr)
        return EXIT_USAGE

    print(
        f"wrote {path}: scenario={args.scenario} seed={args.seed} "
        f"frames={SCENARIOS[args.scenario].n_frames} bytes={path.stat().st_size}"
    )
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
