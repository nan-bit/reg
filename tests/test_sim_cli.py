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

from reg.scenarios import SCENARIOS, scenario
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
    """A scenario whose base drives. Not a registered one: no fixture in
    `SCENARIOS` drives, because Claim 1 is priced on eleven bolted arms
    (docs/mobile-base.md §7 Tier 4)."""
    from reg.scenarios import Scenario, Waypoint
    from reg.types import LimitSource, Limits, PoseSource, VelocitySource
    from reg.world import DEMO_WORLD, ROOM, World

    limits = Limits(
        q_min=np.array([-np.pi, -2.6]),
        q_max=np.array([np.pi, 2.6]),
        qd_max=np.array([2.0, 2.5]),
        qdd_max=np.array([8.0, 10.0]),
        link_lengths=np.array([0.5, 0.4]),
        source=LimitSource.PROPRIOCEPTIVE,
        link_radius=0.05,
        base_v_max=0.8,
        base_a_max=1.2,
        base_omega_max=1.0,
        base_alpha_max=2.0,
    )
    return Scenario(
        name="probe_drives",
        description="a base that drives, constructed by a test",
        world=World(
            room=ROOM,
            obstacles=DEMO_WORLD.obstacles,
            limits=limits,
            human_radius=DEMO_WORLD.human_radius,
        ),
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
