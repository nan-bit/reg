"""The simulator CLI — reproducibility, provenance, and refusal.

The tests that matter most here are not about argparse. They are:

* `test_the_same_command_twice_is_byte_identical` and its sibling for *different*
  output paths — this is the check CI runs, and it is only meaningful if nothing
  varying (a clock, a path, a hostname) can reach the file.
* `test_each_scenario_differs_between_seeds` — all six scenarios carry non-zero
  jitter, so the seed is a real input rather than decoration. If a scenario is
  ever authored with `q_jitter == human_jitter == 0` this fails, which is the
  right outcome: a `--seed` flag that changes nothing is a lie in the artifact.
* the refusal tests — an unknown scenario, a missing `--out`, a negative seed. A
  CLI that quietly defaulted would write a well-formed artifact of the wrong run,
  and nothing downstream could tell.
"""

from __future__ import annotations

import subprocess
import sys

import numpy as np
import pytest

from reg.scenarios import MOBILE_SCENARIOS, MOBILE_WORLD, SCENARIOS, scenario
from reg.sim import (
    DEFAULT_SEED,
    EXIT_OK,
    EXIT_USAGE,
    PROVENANCE_BANNER,
    PROVENANCE_VERSION,
    main,
    parse_provenance,
    simulate,
)
from reg.stream import (
    COMMENT_PREFIX,
    ENCODING,
    expected_header,
    read_comments,
    read_frames,
)


def run(tmp_path, name: str = "contact", seed: int | None = 0, out: str = "out.csv"):
    """Invoke the CLI the way the issue's command does, in-process."""
    path = tmp_path / out
    argv = ["--scenario", name, "--out", str(path)]
    if seed is not None:
        argv += ["--seed", str(seed)]
    assert main(argv) == EXIT_OK
    return path


def header_line(path) -> str:
    """The first line that is not provenance."""
    for line in path.read_text(encoding=ENCODING).splitlines():
        if not line.startswith(COMMENT_PREFIX):
            return line
    raise AssertionError(f"{path} has no header row")


# --- it writes the stream ---------------------------------------------------


def test_writes_a_non_empty_file_with_the_expected_header(tmp_path) -> None:
    path = run(tmp_path)
    assert path.stat().st_size > 0

    scn = SCENARIOS["contact"]
    n_joints = len(scn.world.limits.link_lengths)
    n_obstacles = len(scn.world.obstacles)
    assert header_line(path) == ",".join(expected_header(n_joints, n_obstacles))


def test_writes_one_row_per_frame(tmp_path) -> None:
    path = run(tmp_path)
    rows = [
        line
        for line in path.read_text(encoding=ENCODING).splitlines()
        if not line.startswith(COMMENT_PREFIX)
    ]
    assert len(rows) == SCENARIOS["contact"].n_frames + 1  # + the header


def test_the_written_stream_reads_back_as_the_scenario(tmp_path) -> None:
    """The provenance block must not cost the artifact its own reader.

    A file `reg.stream` cannot parse is not a stream, however well-formed it looks
    — Phase 4 builds the graph by reading exactly this back.
    """
    path = run(tmp_path, name="near_miss", seed=3)
    got = list(read_frames(path))
    want = list(scenario("near_miss").states(3))

    assert len(got) == len(want)
    for a, b in zip(got, want):
        assert a.t == pytest.approx(b.t, abs=1e-6)
        assert np.allclose(a.q, b.q, atol=1e-6, rtol=0)
        assert np.allclose(a.human_pos, b.human_pos, atol=1e-6, rtol=0)
        assert [o.entity_id for o in a.objects] == [o.entity_id for o in b.objects]


@pytest.mark.parametrize("name", list(SCENARIOS))
def test_every_scenario_can_be_written_and_read(tmp_path, name) -> None:
    path = run(tmp_path, name=name, out=f"{name}.csv")
    assert len(list(read_frames(path))) == SCENARIOS[name].n_frames


# --- determinism ------------------------------------------------------------


def test_the_same_command_twice_is_byte_identical(tmp_path) -> None:
    a = run(tmp_path, seed=0, out="a.csv")
    b = run(tmp_path, seed=0, out="b.csv")
    assert a.read_bytes() == b.read_bytes()


def test_the_output_path_does_not_reach_the_bytes(tmp_path) -> None:
    """Two runs differing only in `--out` must agree — CI compares a.csv to b.csv.

    Fails if anything positional or environmental (a path, a timestamp, a
    hostname) is ever added to the provenance block.
    """
    a = run(tmp_path, out="one.csv")
    b = run(tmp_path, out="nested/deeply/two-with-a-longer-name.csv")
    assert a.read_bytes() == b.read_bytes()


@pytest.mark.parametrize("name", list(SCENARIOS))
def test_each_scenario_differs_between_seeds(tmp_path, name) -> None:
    """Not one of the six is seed-independent — every one carries jitter.

    Stated rather than assumed: issue #12 allows "all six are fully deterministic
    regardless of seed" as an outcome, but that is not this repo's, and a silent
    change to it would make `--seed` a no-op flag recorded in every artifact.
    """
    scn = SCENARIOS[name]
    assert scn.q_jitter > 0.0 or scn.human_jitter > 0.0

    a = run(tmp_path, name=name, seed=0, out=f"{name}-0.csv")
    b = run(tmp_path, name=name, seed=1, out=f"{name}-1.csv")
    assert a.read_bytes() != b.read_bytes()


def test_determinism_holds_across_processes(tmp_path) -> None:
    """The in-process test cannot see a hash seed or an import-order effect."""
    paths = []
    for out in ("p.csv", "q.csv"):
        path = tmp_path / out
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "reg.sim",
                "--scenario",
                "contact",
                "--seed",
                "0",
                "--out",
                str(path),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        paths.append(path)
    assert paths[0].read_bytes() == paths[1].read_bytes()


# --- provenance -------------------------------------------------------------


def test_the_seed_is_recorded_in_the_file(tmp_path) -> None:
    path = run(tmp_path, name="contact", seed=7)
    fields = parse_provenance(path)
    assert fields["seed"] == "7"
    assert fields["scenario"] == "contact"
    assert read_comments(path)[0] == PROVENANCE_BANNER


def test_the_default_seed_is_recorded_like_any_other(tmp_path) -> None:
    """The point of a recorded default: downstream never has to guess."""
    path = run(tmp_path, seed=None)
    assert parse_provenance(path)["seed"] == str(DEFAULT_SEED)


def test_provenance_matches_the_run(tmp_path) -> None:
    path = run(tmp_path, name="sustained_overlap", seed=2, out="s.csv")
    scn = SCENARIOS["sustained_overlap"]
    fields = parse_provenance(path)
    assert fields["frames"] == str(scn.n_frames)
    assert fields["dt"] == str(scn.dt)
    assert fields["duration"] == str(scn.duration)


def test_a_file_without_provenance_reports_nothing_rather_than_defaults(
    tmp_path,
) -> None:
    """The negative half of provenance: absence is could-not-evaluate.

    `reg.stream.write_frames` with no comments is a legal stream; asking it what
    produced it must return nothing at all, not `seed=0`.
    """
    from reg.stream import write_frames

    path = tmp_path / "bare.csv"
    write_frames(scenario("contact").states(0), path)
    assert parse_provenance(path) == {}


def test_the_banner_names_the_current_provenance_version(tmp_path) -> None:
    """The version is what tells two blocks apart, so it has to be *in* the file.

    Bumped to 2 by issue #176: `reg.stream` gained the two optional base blocks,
    so a header with no base columns stopped meaning *this format has no base
    columns* and started meaning *this run recorded no base*. Those are different
    facts, and a reader holding a file written before the change can only tell
    which one it is looking at from the version. Read out of the artifact rather
    than compared to the constant twice over, because the property is that the
    number reaches the file.
    """
    path = run(tmp_path)
    assert read_comments(path)[0] == f"reg-sim provenance v{PROVENANCE_VERSION}"
    assert PROVENANCE_VERSION >= 2


def test_a_fixed_arm_scenario_records_no_base_rather_than_a_still_one(
    tmp_path,
) -> None:
    """**The negative beside the version bump.** Every scenario in this
    repository is bolted to the origin, so every stream the CLI writes must come
    back with no base at all.

    The schema can carry one since issue #176, which is exactly what makes this
    worth asserting: a producer that started writing zeros into base columns
    would still round-trip, still validate, and would say the base was measured
    and found still — a claim no fixture here can make. `None` is *not
    recorded*, and it must not resolve into a reading nobody took.
    """
    path = run(tmp_path, name="contact")
    assert "base" not in header_line(path)
    frames = list(read_frames(path))
    assert frames
    assert all(f.base_vel is None and f.base_pose is None for f in frames)


# --- refusal ----------------------------------------------------------------


def test_an_unknown_scenario_exits_non_zero_naming_the_valid_ones(
    tmp_path, capsys
) -> None:
    path = tmp_path / "never.csv"
    code = main(["--scenario", "contct", "--out", str(path), "--seed", "0"])

    assert code != EXIT_OK
    assert code == EXIT_USAGE
    err = capsys.readouterr().err
    for name in SCENARIOS:
        assert name in err
    assert not path.exists(), "a refused run must not leave an artifact behind"


def test_an_unknown_scenario_exits_non_zero_as_a_process(tmp_path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "reg.sim",
            "--scenario",
            "no_such_scenario",
            "--out",
            str(tmp_path / "never.csv"),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "contact" in result.stderr


def test_a_missing_scenario_is_a_usage_error(tmp_path) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--out", str(tmp_path / "never.csv")])
    assert exit_info.value.code == EXIT_USAGE


def test_a_missing_out_is_a_usage_error() -> None:
    """No default path: an artifact written somewhere nobody named is a lost run."""
    with pytest.raises(SystemExit) as exit_info:
        main(["--scenario", "contact"])
    assert exit_info.value.code == EXIT_USAGE


def test_a_negative_seed_is_refused() -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--scenario", "contact", "--seed", "-1", "--out", "never.csv"])
    assert exit_info.value.code == EXIT_USAGE


def test_a_non_integer_seed_is_refused() -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--scenario", "contact", "--seed", "0.5", "--out", "never.csv"])
    assert exit_info.value.code == EXIT_USAGE


def test_simulate_refuses_an_unknown_scenario_by_name(tmp_path) -> None:
    """The library layer refuses too — the CLI is not the only entry point."""
    with pytest.raises(KeyError, match="unknown scenario"):
        simulate("nope", 0, tmp_path / "never.csv")


# --- the output path --------------------------------------------------------


def test_the_output_directory_is_created(tmp_path) -> None:
    path = tmp_path / "runs" / "nested" / "contact.csv"
    assert main(["--scenario", "contact", "--seed", "0", "--out", str(path)]) == EXIT_OK
    assert path.exists()


def test_an_existing_file_is_overwritten_not_appended(tmp_path) -> None:
    path = tmp_path / "out.csv"
    path.write_text("stale content that is not a stream\n", encoding=ENCODING)
    assert main(["--scenario", "contact", "--seed", "0", "--out", str(path)]) == EXIT_OK
    assert "stale" not in path.read_text(encoding=ENCODING)
    assert len(list(read_frames(path))) == SCENARIOS["contact"].n_frames


# --- --list -----------------------------------------------------------------


def test_list_names_every_scenario_and_exits_zero(capsys) -> None:
    assert main(["--list"]) == EXIT_OK
    out = capsys.readouterr().out
    for name in SCENARIOS:
        assert name in out


def test_list_needs_no_other_argument(capsys) -> None:
    """`--list` is how you find out what `--scenario` accepts; requiring
    `--scenario` to run it would be a closed loop."""
    assert main(["--list"]) == EXIT_OK
    assert capsys.readouterr().out.strip()


# --------------------------------------------------------------------------
# THE BASE BLOCKS (issue #177)
#
# This file's subject is the producer, and what issue #177 makes checkable here
# is that the producer decides nothing: `write_frames` derives the header from
# the frames, so the two optional blocks of issue #176 appear for a scenario
# that drives and are absent for one that does not, with no flag in `reg.sim`
# choosing between them. Both halves are asserted — the second is the one every
# published figure depends on.
# --------------------------------------------------------------------------


def driving_scenario():
    """A scenario whose base drives, constructed here rather than shipped.

    Not a registered one, and since issue #178 that is a narrower statement than
    it was: three fixtures in `reg.scenarios.MOBILE_SCENARIOS` drive, and none of
    them is in `SCENARIOS`, because Claim 1 is priced on the eleven bolted arms
    (docs/mobile-base.md §7 Tier 4). This one stays because the tests below are
    about the *producer* deciding nothing — a one-second run with no jitter in
    the arm is the cheapest thing that makes the header question answerable, and
    the shipped fixtures are exercised through the CLI further down.

    Its robot is `MOBILE_WORLD`, imported rather than rebuilt: the four base
    numbers used to be spelled out again here, and a second copy of them would
    let this probe and the shipped fixtures drift into two different vehicles
    without anything going red.
    """
    from reg.scenarios import Scenario, Waypoint
    from reg.types import PoseSource, VelocitySource

    return Scenario(
        name="probe_drives",
        description="a base that drives, constructed by a test",
        world=MOBILE_WORLD,
        duration=1.0,
        joint_waypoints=(Waypoint(0.0, (0.0, 0.0)), Waypoint(1.0, (0.5, 0.5))),
        human_waypoints=(Waypoint(0.0, (2.0, 0.0)), Waypoint(1.0, (2.0, 0.5))),
        q_jitter=0.0,
        human_jitter=0.0,
        base_waypoints=(
            Waypoint(0.0, (0.0, 0.0, 0.0)),
            Waypoint(1.0, (0.4, 0.2, 0.3)),
        ),
        base_pose_source=PoseSource.DEAD_RECKONED,
        base_vel_source=VelocitySource.PROPRIOCEPTIVE,
        base_jitter=(0.01, 0.005),
    )


def test_the_producer_writes_the_base_blocks_for_a_driving_scenario(
    tmp_path, monkeypatch
) -> None:
    """A run whose base drove is written as one, with both provenance columns.

    The scenario is registered for the length of this test because `simulate`
    resolves a *name* — the artifact records the name and nothing else can
    rebuild the world from it (`reg.graph._resolve_world`), so a producer that
    took a `Scenario` object would be a second path into the file that the
    provenance block cannot describe.
    """
    from reg.types import PoseSource, VelocitySource

    scn = driving_scenario()
    monkeypatch.setitem(SCENARIOS, scn.name, scn)

    path = simulate(scn.name, 0, tmp_path / "drives.csv")
    assert header_line(path).split(",") == expected_header(
        2, 3, base_vel=True, base_pose=True
    )

    got = list(read_frames(path))
    want = list(scn.states(0))
    assert len(got) == len(want) == scn.n_frames
    for a, b in zip(got, want):
        assert a.base_pose.x == pytest.approx(b.base_pose.x, abs=1e-6)
        assert a.base_pose.y == pytest.approx(b.base_pose.y, abs=1e-6)
        assert a.base_pose.theta == pytest.approx(b.base_pose.theta, abs=1e-6)
        assert a.base_vel.vx == pytest.approx(b.base_vel.vx, abs=1e-6)
        assert a.base_vel.omega == pytest.approx(b.base_vel.omega, abs=1e-6)
        assert a.base_pose.source is PoseSource.DEAD_RECKONED
        assert a.base_vel.source is VelocitySource.PROPRIOCEPTIVE

    # The provenance block is unchanged in shape: what a driving run adds is
    # columns, not fields above the header (`PROVENANCE_VERSION` already
    # records that a header with no base columns is a statement about the run).
    assert parse_provenance(path)["scenario"] == scn.name


def test_a_driving_run_is_still_byte_identical_on_two_writes(
    tmp_path, monkeypatch
) -> None:
    """Determinism is non-negotiable (CLAUDE.md rule 2), and the base columns
    are new floats on the path CI compares. A run whose seed perturbs a base
    path has to reproduce byte for byte like every other one."""
    scn = driving_scenario()
    monkeypatch.setitem(SCENARIOS, scn.name, scn)
    a = simulate(scn.name, 0, tmp_path / "a.csv")
    b = simulate(scn.name, 0, tmp_path / "b.csv")
    assert a.read_bytes() == b.read_bytes()


@pytest.mark.parametrize("name", list(SCENARIOS))
def test_no_registered_scenario_grows_a_base_column(tmp_path, name: str) -> None:
    """**The half Claim 1 is priced on, asserted rather than assumed.**

    All eleven are bolted to the origin, so each writes the header it has always
    written: `expected_header(2, 3)`, 24 columns, no base block. If a fixture
    ever drives, this fails — which is the right outcome, because the gzipped
    baseline every published figure is divided by would have moved and
    docs/retention.md's figures would need re-measuring with it (issue #181).
    """
    path = run(tmp_path, name=name, out=f"{name}.csv")
    header = header_line(path).split(",")
    assert header == expected_header(2, 3)
    assert len(header) == 24
    assert not any(column.startswith("base_") for column in header)


# --------------------------------------------------------------------------
# THE MOBILE FIXTURES THROUGH THIS CLI (issue #178, docs/mobile-base.md §7)
#
# The probe above is a scenario this file builds; these are the three the
# package ships, and the difference is the whole of Tier 4. The issue's own
# command is `python -m reg.sim --scenario <mobile> --out ...`, so what is
# asserted here is that command: it exits zero, it writes a stream with both
# base blocks, the stream reads back as the run, and it says what it wrote.
#
# The last of those is not a formality. `main` used to print its banner from
# `SCENARIOS[args.scenario]`, which is a registry the mobile fixtures and the
# generated `long_run_<n>` are deliberately not in — so the command wrote the
# file and then raised `KeyError` describing it. Both are pinned below.
# --------------------------------------------------------------------------


@pytest.mark.parametrize("name", list(MOBILE_SCENARIOS))
def test_every_mobile_fixture_can_be_written_and_read(tmp_path, name: str) -> None:
    """The issue's command, end to end, for each of the three.

    The header is `expected_header(2, 3, base_vel=True, base_pose=True)` — the
    two optional blocks of issue #176, which `write_frames` derives from the
    frames rather than from a flag — and every frame comes back stating both.
    """
    path = run(tmp_path, name=name, out=f"{name}.csv")
    scn = MOBILE_SCENARIOS[name]

    assert header_line(path).split(",") == expected_header(
        2, 3, base_vel=True, base_pose=True
    )
    got = list(read_frames(path))
    want = list(scn.states(0))
    assert len(got) == len(want) == scn.n_frames
    for a, b in zip(got, want):
        assert a.base_pose is not None and a.base_vel is not None
        assert a.base_pose.x == pytest.approx(b.base_pose.x, abs=1e-6)
        assert a.base_pose.y == pytest.approx(b.base_pose.y, abs=1e-6)
        assert a.base_pose.theta == pytest.approx(b.base_pose.theta, abs=1e-6)
        assert a.base_vel.vx == pytest.approx(b.base_vel.vx, abs=1e-6)
        assert a.base_vel.vy == pytest.approx(b.base_vel.vy, abs=1e-6)
        assert a.base_vel.omega == pytest.approx(b.base_vel.omega, abs=1e-6)
        assert a.base_pose.source is scn.base_pose_source
        assert a.base_vel.source is scn.base_vel_source

    fields = parse_provenance(path)
    assert fields["scenario"] == name
    assert fields["seed"] == "0"
    assert fields["frames"] == str(scn.n_frames)


@pytest.mark.parametrize("name", list(MOBILE_SCENARIOS))
def test_a_mobile_fixture_is_byte_identical_on_two_writes(tmp_path, name: str) -> None:
    """CLAUDE.md rule 2, over the columns this tier added. Same seed, same bytes."""
    a = run(tmp_path, name=name, seed=0, out=f"{name}-a.csv")
    b = run(tmp_path, name=name, seed=0, out=f"{name}-b.csv")
    assert a.read_bytes() == b.read_bytes()


@pytest.mark.parametrize("name", list(MOBILE_SCENARIOS))
def test_each_mobile_fixture_differs_between_seeds(tmp_path, name: str) -> None:
    """The seed is a real input to a mobile run too, and for `mobile_frozen_arm`
    it is the only place that can be checked: that fixture states `q_jitter=0.0`
    on purpose, so what the seed moves there is the human and the base path. A
    `--seed` flag recorded in a stream it did not change is a lie in the
    artifact.
    """
    scn = MOBILE_SCENARIOS[name]
    assert scn.q_jitter > 0.0 or scn.human_jitter > 0.0 or scn.base_jitter != (0.0, 0.0)

    a = run(tmp_path, name=name, seed=0, out=f"{name}-0.csv")
    b = run(tmp_path, name=name, seed=1, out=f"{name}-1.csv")
    assert a.read_bytes() != b.read_bytes()


def test_the_banner_describes_a_run_that_is_not_in_the_registry(
    tmp_path, capsys
) -> None:
    """**The regression this section exists for.**

    `main` resolves the scenario it just simulated rather than indexing
    `SCENARIOS`, so it can describe a run that registry does not hold. Fed a
    mobile fixture and a generated long run — the two kinds `scenario()`
    resolves and `SCENARIOS` does not — it must report the frame count of each
    instead of raising over a file it has already written.
    """
    for name in ("mobile_transit", "long_run_60"):
        path = tmp_path / f"{name}.csv"
        assert main(["--scenario", name, "--seed", "0", "--out", str(path)]) == EXIT_OK
        line = capsys.readouterr().out.strip()
        assert f"scenario={name}" in line, line
        assert f"frames={scenario(name).n_frames}" in line, line
        assert path.exists()


def test_list_names_the_mobile_fixtures_and_says_they_are_a_second_group(
    capsys,
) -> None:
    """A fixture nothing lists is a fixture nobody can run.

    `--list` is how a reader finds out what `--scenario` accepts, so keeping the
    mobile fixtures out of `SCENARIOS` — which is about what `reg.bench` prices
    — must not also keep them out of this. Both groups appear, and each under a
    heading, because a flat list of fourteen names would say the two sets are
    interchangeable and docs/mobile-base.md §7 is that they are not.
    """
    assert main(["--list"]) == EXIT_OK
    out = capsys.readouterr().out
    for name in list(SCENARIOS) + list(MOBILE_SCENARIOS):
        assert name in out, name
    assert "the fixed-base fixtures" in out
    assert "the mobile fixtures" in out
    for scn in MOBILE_SCENARIOS.values():
        # The description is what says which claim the fixture is for, so the
        # listing has to carry it rather than the name alone.
        assert scn.description.split(".")[0][:40] in " ".join(out.split())


def test_an_unknown_mobile_name_names_the_mobile_fixtures_in_its_refusal(
    tmp_path, capsys
) -> None:
    """NEGATIVE. A typo in a mobile name must not read as 'no such thing'.

    The refusal already listed the eleven; a reader who mistyped `mobile_transit`
    and got back only the fixed-base names would reasonably conclude the fixture
    does not exist.
    """
    path = tmp_path / "never.csv"
    code = main(["--scenario", "mobile_transt", "--out", str(path), "--seed", "0"])

    assert code == EXIT_USAGE
    err = capsys.readouterr().err
    for name in list(SCENARIOS) + list(MOBILE_SCENARIOS):
        assert name in err, name
    assert not path.exists(), "a refused run must not leave an artifact behind"
