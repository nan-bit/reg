"""The audit queries, and the boundary that makes Claim 2 mean anything.

THE TESTS THIS FILE EXISTS FOR
------------------------------
Three, and everything else is support.

**1. `test_importing_reg_query_does_not_import_the_stream`.** Claim 2 is "audit
questions answered from the graph alone, no access to the original stream", and
the word doing the work is *alone*. Nothing enforced it before issue #37: the
queries lived inside `reg.bench`, which legitimately reads both sides, so the
claim rested on a module's good manners. This test imports `reg.query` in a
fresh interpreter and fails if `reg.stream`, `reg.scenarios`, `reg.sim`,
`reg.world` — or `reg.graph` or `reg.bench`, which import them — reached
`sys.modules`. It is the same shape of enforcement as
`tests/test_layer_boundary.py`, for the same reason: a structural property that
nothing can fail is a comment.

**2. `test_the_occurrence_level_cannot_answer_the_separation_timeline`.** An
empty result and an unanswerable question are different facts, and conflating
them is the defect this repo exists to refuse. Asked for a per-frame timeline,
an occurrence-level artifact must return `COULD-NOT-EVALUATE` **with a reason**
— not `()`, which reads as "the robot was never near anything".

**3. `test_the_timeline_check_says_no_when_the_graph_is_perturbed`.** The
agreement tests below all pass on a healthy artifact, which proves nothing about
whether they can fail. One distance shifted past `DISTANCE_TOL_M` has to come
back `DISAGREE`.

WHAT IS CHECKED AGAINST THE RAW STREAM, AND WHAT IS NOT
-------------------------------------------------------
`separation_timeline`, `min_separation`, `time_of_closest_approach`,
`did_contact_occur` and `frames_at_risk` are all answerable from the CSV by
forward kinematics alone, so each is checked against it — through
`reg.bench.check_level` and `reg.bench.ground_truth_from_csv` where those
already exist, rather than through a second checker written here.

`first_envelope_intersection` and `reachable_entities` are **not**, and the
reason is `reg.bench.RESOLUTION_QUERIES`': the only ground truth available for
them would be recomputing an envelope per frame with `reg.envelope`, which is
the builder's own computation. A check whose ground truth reruns the code under
test cannot fail. They are checked instead against invariants that *can* fail —
that a visit is not invented, that two separate visits are not merged into one,
and that a window before the entry does not contain the entity.

Envelope parameters are coarse throughout (`_FAST`), copied from
`tests/test_bench.py` for the reason it gives: cost is linear in
`n_samples * horizon / substep_dt` and nothing here is about envelope fidelity.
"""

from __future__ import annotations

import ast
import math
import subprocess
import sys
from pathlib import Path

import pytest

from reg import bench, chain, graph, query, store
from reg.bench import AGREE, COULD_NOT_EVALUATE, DISAGREE, run_scenario
from reg.envelope import outer_radius
from reg.identity import DPIA_NONE, Disclosures, RunIdentity
from reg.query import ANSWERED, QueryError
from reg.scenarios import scenario
from reg.tolerances import DISTANCE_TOL_M, TIME_TOL_S

#: Copied from `tests/test_bench.py`: 4 samples is exactly the corner count for
#: the two-link demo arm, so `compute_envelope` accepts it.
_FAST = {
    "horizon": 0.05,
    "n_samples": 4,
    "envelope_seed": 0,
    "substep_dt": 0.05,
    "occurrence_resolution_s": graph.OCCURRENCE_TIME_RESOLUTION_S,
}

#: The one fixture that contacts. `did_contact_occur` agreeing on a run with no
#: contact is agreement on a negative and proves nothing about whether it can
#: fail, and `frames_at_risk` needs a run that actually gets close.
SCENARIO = "contact"

#: The declared run identity every artifact in this file is built with. Stated
#: once: `graph.build` records it, and a value that varied per call would make
#: two fixtures here two different runs.
TEST_IDENTITY = RunIdentity.declare(
    run_start="2026-08-21T09:00:00Z",
    unit_id="unit-test-arm-1",
    operator_id="op-test",
)

#: What every build in this file states about the obligations
#: `docs/limitations.md` §8 names (issue #125). Required at build with no
#: default, and declared once here for `TEST_IDENTITY`'s reason: a value that varied
#: per call would make two artifacts in this file two different runs. These
#: tests are not about the disclosure keys — `tests/test_personal_data.py` and
#: `tests/test_graph.py` are — so they state one and move on.
TEST_DISCLOSURES = Disclosures.declare(
    worker_notice="not-given",
    dpia_reference=DPIA_NONE,
    operator_id_kind="pseudonym",
)

#: A separation the `contact` fixture crosses in both directions, so the at-risk
#: interval set is neither empty nor the whole run. Stated here rather than
#: taken from anywhere: what counts as risk is a property of a deployment, and
#: `frames_at_risk` refuses to invent one.
THRESHOLD_M = 0.5

#: Modules `reg.query` must not be able to reach. The first four are named by
#: issue #37; `reg.graph` and `reg.bench` are here because both import the first
#: four, and an import is one attribute lookup away from a call.
FORBIDDEN_MODULES = (
    "reg.stream",
    "reg.scenarios",
    "reg.sim",
    "reg.world",
    "reg.graph",
    "reg.bench",
)

#: Names that would mean the scene leaked into the query layer's namespace.
FORBIDDEN_NAMES = ("World", "StateFrame", "Obstacle", "Scenario", "read_frames")


# --------------------------------------------------------------------------
# Fixtures. One build, module-scoped, shared by everything below.
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def built(tmp_path_factory) -> tuple[Path, Path]:
    """One real build: `(csv, sqlite)`.

    `bench._work_paths` is the one definition of where `run_scenario` puts its
    files; restating the convention here would be a second definition of it.
    """
    work = tmp_path_factory.mktemp("query")
    run_scenario(SCENARIO, work, seed=0, **_FAST)
    return bench._work_paths(scenario(SCENARIO), work)


@pytest.fixture(scope="module")
def artifact(built) -> Path:
    return built[1]


@pytest.fixture(scope="module")
def truth(built) -> bench.GroundTruth:
    csv_path, _ = built
    # `records=None`: this fixture's build is handed no record stream, so the
    # Layer A questions in `RESOLUTION_QUERIES` are could-not-evaluate here.
    # Stated rather than defaulted (issue #59) — a default would let a caller
    # reach that state without saying so.
    return bench.ground_truth_from_csv(
        csv_path, scenario(SCENARIO).world, records=None
    )


@pytest.fixture(scope="module")
def occurrence_view(artifact: Path, tmp_path_factory) -> Path:
    """The DSSAD-aligned view of that build: occurrences, no edge layer."""
    out = tmp_path_factory.mktemp("views") / "occurrence.sqlite"
    return bench.materialize_level(artifact, bench.OCCURRENCE_LEVEL, out)


def _ask(path: Path, fn, *args):
    """Open `path`, put one question to it, close. Answers are values, not rows."""
    conn = store.connect(path)
    try:
        return fn(conn, *args)
    finally:
        conn.close()


def _copy(source: Path, target: Path, *statements: str) -> Path:
    """A copy of an artifact with SQL applied. How every negative test is built."""
    import shutil

    shutil.copyfile(source, target)
    conn = store.connect(target)
    try:
        for statement in statements:
            conn.execute(statement)
        conn.commit()
    finally:
        conn.close()
    return target


# --------------------------------------------------------------------------
# THE BOUNDARY. Claim 2's "alone", enforced rather than asserted in prose.
# --------------------------------------------------------------------------


def _reg_imports(source: str) -> set[str]:
    """Every `reg.*` module an import statement in `source` names.

    Factored out so the test below can be fed the condition it guards against —
    a checker only ever run against a clean file has not been shown able to say
    no at all.
    """
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
            for alias in node.names:
                found.add(f"{node.module}.{alias.name}")
    return {name for name in found if name.startswith("reg")}


def test_reg_query_imports_no_stream_or_layer_b_module() -> None:
    """The source-level half: no import statement names a forbidden module."""
    imported = _reg_imports(Path(query.__file__).read_text())
    offenders = sorted(
        name
        for name in imported
        if any(name == m or name.startswith(m + ".") for m in FORBIDDEN_MODULES)
    )
    assert not offenders, (
        f"reg/query.py imports {offenders}. Claim 2 is that audit questions are "
        "answered from the graph alone; a query module that can reach the stream "
        "reader, or reach a module that can, makes 'alone' a promise rather than "
        "a property. If a query needs something the artifact does not hold, that "
        "is a could-not-evaluate."
    )


def test_the_import_checker_can_say_no() -> None:
    """THE NEGATIVE TEST for the check above. Feed it the convenience import."""
    offending = "from __future__ import annotations\nimport reg.stream\n"
    assert "reg.stream" in _reg_imports(offending)
    clean = "from reg import store\nfrom reg.tolerances import TIME_TOL_S\n"
    assert not _reg_imports(clean) & set(FORBIDDEN_MODULES)


def test_importing_reg_query_does_not_import_the_stream() -> None:
    """The runtime half, and the stronger one: a fresh interpreter, and nothing
    forbidden in `sys.modules` afterwards.

    Stronger because it catches the *transitive* reach the source check cannot:
    `import reg.graph` would put `reg.stream` one attribute away without ever
    naming it here.
    """
    code = (
        "import sys, reg.query; "
        "print(' '.join(sorted(m for m in sys.modules if m.startswith('reg'))))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=True,
    )
    loaded = set(result.stdout.split())
    assert loaded, "the subprocess reported no reg modules at all; it did not run"
    offenders = sorted(loaded & set(FORBIDDEN_MODULES))
    assert not offenders, (
        f"importing reg.query pulled in {offenders}. The raw stream must be "
        "structurally out of reach, not merely unused."
    )


def test_the_query_namespace_binds_nothing_from_the_scene() -> None:
    """No `World`, `StateFrame` or `Obstacle` bound in `reg.query`."""
    for name in FORBIDDEN_NAMES:
        assert not hasattr(query, name), (
            f"reg.query binds {name!r}. Layer B's types have no business in a "
            "module whose only input is a SQLite file."
        )


def test_the_meta_keys_this_module_reads_are_the_ones_the_builder_writes(
    artifact: Path,
) -> None:
    """The cost of that isolation, paid for with a test rather than tolerated.

    `reg.query` names the `meta` keys it reads instead of importing them from
    `reg.graph`, because importing the writer would defeat the point. A rename on
    either side would otherwise turn every query into a could-not-evaluate months
    later, so it fails here instead — the discipline `tests/test_tolerances.py`
    uses on docs/lossiness.md.
    """
    conn = store.connect(artifact)
    try:
        meta = store.all_meta(conn)
    finally:
        conn.close()
    for key in (
        query.META_T_FIRST,
        query.META_T_LAST,
        query.META_FRAME_COUNT,
        query.META_OCCURRENCE_RETENTION,
        query.META_OCCURRENCE_RESOLUTION,
        query.META_ATTESTATION_RECORDS,
        query.META_ATTESTATION_RETENTION,
        store.META_FRAME_PERIOD,
    ):
        assert key in meta, (
            f"reg.query reads meta[{key!r}] and reg.graph does not write it."
        )
    assert query.META_OCCURRENCE_RETENTION == graph.META_OCCURRENCE_RETENTION
    assert query.META_OCCURRENCE_RESOLUTION == graph.META_OCCURRENCE_RESOLUTION
    assert query.META_ATTESTATION_RECORDS == graph.META_ATTESTATION_RECORDS
    assert query.META_ATTESTATION_RETENTION == graph.META_ATTESTATION_RETENTION
    # The two counts are written only where a record stream was supplied, so
    # they are not asserted present in this artifact — which was built without
    # one. Their *spelling* is still one contract with the builder, and with
    # `reg.chain`, which names its own copies for the same reason.
    assert query.META_DECLARATION_COUNT == graph.META_DECLARATION_COUNT
    assert query.META_VERDICT_COUNT == graph.META_VERDICT_COUNT
    assert query.ATTESTATION_PRESENT == chain.ATTESTATION_PRESENT


# --------------------------------------------------------------------------
# Agreement with the raw stream, through the benchmark's own checker.
# --------------------------------------------------------------------------


def _check(
    name: str,
    answers: bench.LevelAnswers,
    truth: bench.GroundTruth,
    *,
    timestamp_resolution_s: float,
) -> str:
    """One query's verdict, from `reg.bench.check_level`. Not a second checker.

    docs/lossiness.md's agreement predicates are already implemented once, in the
    benchmark, and issue #37 says to reuse them. Writing a comparison here would
    be the same trap the whole issue is about, one level down.

    `timestamp_resolution_s` is passed through without a default for the reason
    `check_level` requires one: an artifact asked a timing question has to say
    how precisely it records time, or it gets graded against a precision it
    never claimed.
    """
    spec = next(q for q in bench.RESOLUTION_QUERIES if q.name == name)
    return bench.check_level(
        spec, answers, truth, timestamp_resolution_s=timestamp_resolution_s
    ).verdict


def test_the_separation_timeline_agrees_with_the_raw_stream(
    artifact: Path, truth: bench.GroundTruth
) -> None:
    """Query 1, at every frame, against forward kinematics from the CSV."""
    answer = _ask(artifact, query.separation_timeline, graph.HUMAN_ENTITY_ID)
    assert answer.verdict == ANSWERED
    assert answer.layer == query.EDGE_LAYER
    assert answer.value.frames == truth.frames
    assert answer.tolerances["distance_m"] == DISTANCE_TOL_M
    assert (
        _check(
            "separation_timeline",
            bench.LevelAnswers(None, None, answer.value.samples, None, None),
            truth,
            timestamp_resolution_s=bench.TIME_TOL_S,
        )
        == AGREE
    )


def test_the_timeline_check_says_no_when_the_graph_is_perturbed(
    artifact: Path, truth: bench.GroundTruth, tmp_path: Path
) -> None:
    """THE NEGATIVE TEST for every agreement assertion above it.

    One distance shifted past `DISTANCE_TOL_M`. If this comes back `AGREE` the
    checks in this file are decorative — they would pass for a query layer that
    returned the wrong numbers as readily as for one that returned the right
    ones.
    """
    tampered = _copy(
        artifact,
        tmp_path / "tampered.sqlite",
        "UPDATE edge SET min_distance = min_distance + "
        f"{10 * DISTANCE_TOL_M} WHERE type = 'SEPARATION'",
    )
    answer = _ask(tampered, query.separation_timeline, graph.HUMAN_ENTITY_ID)
    assert answer.verdict == ANSWERED, "the perturbed artifact still answers"
    assert (
        _check(
            "separation_timeline",
            bench.LevelAnswers(None, None, answer.value.samples, None, None),
            truth,
            timestamp_resolution_s=bench.TIME_TOL_S,
        )
        == DISAGREE
    )


def test_min_separation_and_the_contact_flag_agree_with_the_raw_stream(
    artifact: Path, truth: bench.GroundTruth
) -> None:
    assert truth.contact_occurred, (
        "precondition failed: this fixture does not contact, so agreement on "
        "did_contact_occur would be agreement on a negative."
    )
    smallest = _ask(artifact, query.min_separation, graph.HUMAN_ENTITY_ID)
    contact = _ask(artifact, query.did_contact_occur, graph.HUMAN_ENTITY_ID)
    when = _ask(artifact, query.time_of_closest_approach, graph.HUMAN_ENTITY_ID)
    assert {smallest.verdict, contact.verdict, when.verdict} == {ANSWERED}

    answers = bench.LevelAnswers(
        min_separation=smallest.value,
        t_closest_approach=when.value,
        timeline=None,
        contact_occurred=contact.value,
        attestation=None,
    )
    assert _check(
        "min_separation", answers, truth, timestamp_resolution_s=bench.TIME_TOL_S
    ) == AGREE
    assert _check(
        "did_contact_occur", answers, truth, timestamp_resolution_s=bench.TIME_TOL_S
    ) == AGREE
    assert (
        _check(
            "time_of_closest_approach",
            answers,
            truth,
            timestamp_resolution_s=bench.TIME_TOL_S,
        )
        == AGREE
    )


def test_frames_at_risk_covers_every_frame_the_stream_says_is_at_risk(
    artifact: Path, truth: bench.GroundTruth
) -> None:
    """Query 3, against the per-frame threshold test docs/lossiness.md specifies.

    The predicate spends the quantum the artifact advertises rather than
    pretending it is not there: a frame whose *true* separation is within one
    `DISTANCE_TOL_M` of the threshold may legitimately fall either side, because
    the stored distance it was tested against is rounded to that. So the two
    halves asserted are the two that carry no ambiguity — clearly-below frames
    must be covered, clearly-above frames must not be — and a query off by more
    than a quantum fails both.
    """
    answer = _ask(
        artifact, query.frames_at_risk, graph.HUMAN_ENTITY_ID, THRESHOLD_M
    )
    assert answer.verdict == ANSWERED
    intervals = answer.value.intervals
    assert intervals, (
        f"precondition failed: nothing in this fixture comes within "
        f"{THRESHOLD_M} m, so the query has nothing to be right or wrong about."
    )

    def covered(t: float) -> bool:
        return any(
            i.t_start - TIME_TOL_S <= t <= i.t_end + TIME_TOL_S for i in intervals
        )

    below = [t for t, d in truth.timeline if d <= THRESHOLD_M - DISTANCE_TOL_M]
    above = [t for t, d in truth.timeline if d >= THRESHOLD_M + DISTANCE_TOL_M]
    assert below and above, (
        "precondition failed: this threshold does not split the run, so the "
        "check could not come out wrong in either direction."
    )
    assert all(covered(t) for t in below), (
        "a frame the raw stream puts clearly below the threshold is not in any "
        "at-risk interval"
    )
    assert not any(covered(t) for t in above), (
        "a frame the raw stream puts clearly above the threshold is inside an "
        "at-risk interval"
    )
    assert answer.value.frames == sum(i.frames for i in intervals)


def test_frames_at_risk_counts_frames_by_the_period_not_by_the_rows(
    artifact: Path,
) -> None:
    """docs/lossiness.md *Discarded* #10: the two questions that name frames
    divide an interval by `frame_period_s`, because a row count would depend on
    which frames happened to anchor an edge."""
    answer = _ask(
        artifact, query.frames_at_risk, graph.HUMAN_ENTITY_ID, THRESHOLD_M
    )
    period = answer.value.frame_period_s
    for interval in answer.value.intervals:
        assert interval.frames == round((interval.t_end - interval.t_start) / period) + 1


# --------------------------------------------------------------------------
# The two envelope queries. No CSV ground truth exists for them that would not
# rerun the builder's own computation, so these are invariants that can fail.
# --------------------------------------------------------------------------


def test_the_first_intersection_is_the_first_intersects_row(artifact: Path) -> None:
    answer = _ask(
        artifact, query.first_envelope_intersection, graph.HUMAN_ENTITY_ID
    )
    assert answer.verdict == ANSWERED
    conn = store.connect(artifact)
    try:
        rows = store.read_edges(
            conn, edge_type="INTERSECTS", dst_id=graph.HUMAN_ENTITY_ID
        )
    finally:
        conn.close()
    assert rows, "precondition failed: the human never enters the envelope here"
    assert answer.value.t_first == min(float(r["t_start"]) for r in rows)
    assert answer.value.intervals[-1].t_end == max(float(r["t_end"]) for r in rows)
    # The metric steps of one visit are one visit, not 59 of them.
    assert len(answer.value.intervals) < len(rows)
    assert all(i.max_overlap_area > 0.0 for i in answer.value.intervals)


def test_two_separate_visits_are_not_merged_into_one(
    artifact: Path, tmp_path: Path
) -> None:
    """THE NEGATIVE TEST for the interval merging.

    Merging exists because an `INTERSECTS` edge closes and reopens on every
    `AREA_QUANT_SIGFIGS` step of the overlap, and reporting 59 visits where the
    human made one would be a wrong answer. A merge rule that swallowed a real
    gap would be the opposite wrong answer and much worse — it would report the
    entity inside the reachable set during seconds it had left. So: punch a hole
    in the middle of the visit and the query must report two.
    """
    answer = _ask(
        artifact, query.first_envelope_intersection, graph.HUMAN_ENTITY_ID
    )
    visit = answer.value.intervals[0]
    assert len(answer.value.intervals) == 1, "this test assumes one visit"
    middle = (visit.t_start + visit.t_end) / 2.0
    span = (visit.t_end - visit.t_start) / 10.0
    holed = _copy(
        artifact,
        tmp_path / "holed.sqlite",
        "DELETE FROM edge WHERE type = 'INTERSECTS' "
        f"AND t_start >= {middle - span} AND t_end <= {middle + span}",
    )
    after = _ask(holed, query.first_envelope_intersection, graph.HUMAN_ENTITY_ID)
    assert len(after.value.intervals) == 2, (
        "a gap of many frames was merged away; the query would report the "
        "entity inside the reachable set during time the artifact says it was "
        "not."
    )


def test_reachable_entities_is_a_set_over_the_window(artifact: Path) -> None:
    """Query 4. Exact set equality, and the window really is a window."""
    conn = store.connect(artifact)
    try:
        first, last = query.run_interval(conn)
        whole = query.reachable_entities(conn, first, last)
        entry = query.first_envelope_intersection(conn, graph.HUMAN_ENTITY_ID)
        t_first = entry.value.t_first
        assert t_first is not None, "precondition failed: nothing ever enters"
        before = query.reachable_entities(conn, first, t_first - TIME_TOL_S * 2)
        inside = query.reachable_entities(conn, t_first, t_first + TIME_TOL_S)
    finally:
        conn.close()

    assert graph.HUMAN_ENTITY_ID in whole.value.entity_ids
    assert graph.HUMAN_ENTITY_ID in inside.value.entity_ids
    assert graph.HUMAN_ENTITY_ID not in before.value.entity_ids, (
        "the entity is reported inside the envelope before it first entered it"
    )
    # An empty answer is still an answer, and it names what it ruled out.
    assert before.verdict == ANSWERED
    assert set(before.value.declared) == set(whole.value.declared)
    assert set(whole.value.entity_ids) <= set(whole.value.declared)


# --------------------------------------------------------------------------
# NEGATIVE: an artifact that cannot answer says so, with a reason.
# --------------------------------------------------------------------------


def test_the_occurrence_level_cannot_answer_the_separation_timeline(
    occurrence_view: Path,
) -> None:
    """**The test this file exists for.** An empty result and an unanswerable
    question are different facts.

    Issue #36 measured exactly this at the benchmark. It moves here so that any
    caller gets it: the occurrence layer holds events, not states, and the
    intervals between them are precisely what it discarded.
    """
    answer = _ask(
        occurrence_view, query.separation_timeline, graph.HUMAN_ENTITY_ID
    )
    assert answer.verdict == COULD_NOT_EVALUATE
    assert answer.value is None, (
        "an empty timeline would read as 'the robot was never near anything'"
    )
    assert answer.layer is None
    assert answer.reason.strip(), "a refusal with no reason is silence"
    assert "occurrence" in answer.reason


@pytest.mark.parametrize(
    "name", ["first_envelope_intersection", "reachable_entities"]
)
def test_the_other_edge_only_queries_refuse_at_occurrence_level(
    occurrence_view: Path, name: str
) -> None:
    """Every query that declares the edge layer refuses without it — not just
    the one the benchmark happened to measure."""
    conn = store.connect(occurrence_view)
    try:
        if name == "reachable_entities":
            first, last = query.run_interval(conn)
            answer = query.reachable_entities(conn, first, last)
        else:
            answer = query.first_envelope_intersection(
                conn, graph.HUMAN_ENTITY_ID
            )
    finally:
        conn.close()
    assert answer.verdict == COULD_NOT_EVALUATE
    assert answer.value is None
    assert answer.reason.strip()


def test_the_occurrence_level_still_answers_what_it_can(
    occurrence_view: Path, truth: bench.GroundTruth
) -> None:
    """The control. Without it, "the coarse level refuses" would be
    indistinguishable from "the coarse level refuses everything", and the
    resolution finding would say nothing."""
    smallest = _ask(occurrence_view, query.min_separation, graph.HUMAN_ENTITY_ID)
    contact = _ask(occurrence_view, query.did_contact_occur, graph.HUMAN_ENTITY_ID)
    assert smallest.verdict == ANSWERED
    assert smallest.layer == query.OCCURRENCE_LAYER
    assert contact.verdict == ANSWERED and contact.value is True
    answers = bench.LevelAnswers(smallest.value, None, None, contact.value, None)
    # This view records occurrences to 1.0 s, so that is the precision its
    # answers are graded at. Neither question below is a timing question, but
    # stating it is what keeps the coarse level from being asked a fine one.
    coarse = graph.OCCURRENCE_TIME_RESOLUTION_S
    assert (
        _check("min_separation", answers, truth, timestamp_resolution_s=coarse)
        == AGREE
    )
    assert (
        _check("did_contact_occur", answers, truth, timestamp_resolution_s=coarse)
        == AGREE
    )


def test_the_occurrence_answer_reports_the_coarse_tolerance(
    occurrence_view: Path,
) -> None:
    """The ±1 s, carried on the answer rather than lost in the formatting.

    The same question answers from either layer and the two are two orders of
    magnitude apart. A caller given `2.0` with no tolerance would read it as
    `TIME_TOL_S`-accurate, which is the fabricated digit docs/lossiness.md
    forbids.
    """
    edge_answer_tolerance = TIME_TOL_S
    coarse = _ask(
        occurrence_view, query.time_of_closest_approach, graph.HUMAN_ENTITY_ID
    )
    assert coarse.verdict == ANSWERED
    assert coarse.layer == query.OCCURRENCE_LAYER
    assert coarse.tolerances["time_s"] == graph.OCCURRENCE_TIME_RESOLUTION_S
    assert coarse.tolerances["time_s"] > edge_answer_tolerance


def test_the_closed_world_contact_answer_needs_the_rule_in_the_file(
    occurrence_view: Path, tmp_path: Path
) -> None:
    """THE NEGATIVE TEST for the occurrence layer's one closed-world reading.

    "No `contact_began` row" means no contact **only** because the artifact
    carries `occurrence_retention` saying one would have been written — the same
    reason DSSAD's absent occurrence flag is readable. Strip the rule and the
    answer must become a refusal, not `False`.
    """
    stripped = _copy(
        occurrence_view,
        tmp_path / "no_rule.sqlite",
        f"DELETE FROM meta WHERE key = '{query.META_OCCURRENCE_RETENTION}'",
    )
    answer = _ask(stripped, query.did_contact_occur, graph.HUMAN_ENTITY_ID)
    assert answer.verdict == COULD_NOT_EVALUATE
    assert answer.value is None, "silence read as a negative"
    assert query.META_OCCURRENCE_RETENTION in answer.reason


def test_a_query_does_not_fall_back_from_a_damaged_edge_layer(
    artifact: Path, tmp_path: Path
) -> None:
    """No cross-layer fallback inside one file, and this is where it would show.

    The artifact holds both layers. Delete the edge layer's `SEPARATION` rows
    and the occurrence layer's `closest_approach` is still sitting there with an
    answer — a *correct* one, even. Taking it would mean the resolution of an
    answer, and the tolerance reported beside it, are decided by which rows
    happened to survive rather than by what the artifact is. Refusing is the
    only thing that keeps `Answer.layer` an attribution.
    """
    damaged = _copy(
        artifact,
        tmp_path / "damaged.sqlite",
        "DELETE FROM edge WHERE type = 'SEPARATION'",
    )
    conn = store.connect(damaged)
    try:
        assert query.OCCURRENCE_LAYER in query.available_layers(conn), (
            "precondition failed: the coarse answer is not present, so there "
            "was nothing to fall back to"
        )
        assert store.read_occurrences(
            conn, occurrence_type="closest_approach", entity_id=graph.HUMAN_ENTITY_ID
        ), "precondition failed: no closest_approach row to be tempted by"
        answer = query.min_separation(conn, graph.HUMAN_ENTITY_ID)
    finally:
        conn.close()
    assert answer.verdict == COULD_NOT_EVALUATE
    assert answer.value is None


def test_an_artifact_with_no_rows_at_all_refuses_every_query(
    artifact: Path, tmp_path: Path
) -> None:
    """Silence is not agreement. An artifact stripped of both layers answers
    nothing, and it must not answer *emptily*."""
    empty = _copy(
        artifact,
        tmp_path / "empty.sqlite",
        "DELETE FROM edge",
        "DELETE FROM occurrence",
    )
    conn = store.connect(empty)
    try:
        answers = [
            query.separation_timeline(conn, graph.HUMAN_ENTITY_ID),
            query.first_envelope_intersection(conn, graph.HUMAN_ENTITY_ID),
            query.frames_at_risk(conn, graph.HUMAN_ENTITY_ID, THRESHOLD_M),
            query.min_separation(conn, graph.HUMAN_ENTITY_ID),
            query.time_of_closest_approach(conn, graph.HUMAN_ENTITY_ID),
            query.did_contact_occur(conn, graph.HUMAN_ENTITY_ID),
            query.reachable_entities(conn, *query.run_interval(conn)),
        ]
    finally:
        conn.close()
    for answer in answers:
        assert answer.verdict == COULD_NOT_EVALUATE, answer.query
        assert answer.value is None, answer.query
        assert answer.reason.strip(), answer.query


# --------------------------------------------------------------------------
# THE POINTWISE REACHABILITY QUESTION (issue #258).
#
# #257 retained the outer boundary where `GEOMETRY_RETENTION` already keeps the
# inner polygon; this is the query that tests a point against it. The property
# every test below is arranged around is the one the issue names:
#
#   **A RADIAL ANSWER MUST NEVER BE RETURNED WEARING A POINTWISE ONE'S CLOTHES.**
#
# `outer_radius` is on every retained row, so at a frame with no boundary a
# plausible True/False is one column away. `test_a_frame_with_no_boundary_is_a_
# could_not_evaluate` is the test that would catch it being reached for, and
# `test_the_radius_still_answers_where_the_region_would_not` is what shows the
# two answers genuinely differ — a point inside the radius and outside the
# region, on the shipped fixture, which is the substitution made visible.
# --------------------------------------------------------------------------


def _first_retained_boundary(conn) -> tuple[float, str, object]:
    """`(t, envelope_id, region)` for the first frame that keeps an outer one.

    Read off the artifact rather than listed, because which frames
    `GEOMETRY_RETENTION` covers is a property of the run and a hard-coded `t`
    would pin this file to one scenario's transitions.
    """
    row = conn.execute(
        "SELECT e.t_start AS t, n.node_id AS id, v.outer_wkb AS wkb FROM edge e "
        "JOIN node n ON n.node_key = e.dst_key "
        "JOIN envelope v ON v.envelope_key = e.dst_key "
        "WHERE e.type = 'HAS_ENVELOPE' AND v.outer_wkb IS NOT NULL "
        "ORDER BY e.t_start, e.edge_id LIMIT 1"
    ).fetchone()
    assert row is not None, (
        "precondition failed: this artifact retains no outer boundary at any "
        "frame, so nothing below is exercised"
    )
    return float(row["t"]), str(row["id"]), store.from_wkb(row["wkb"])


def _uncovered_frame(conn) -> float:
    """A frame time this artifact retains no outer boundary at. There are many."""
    covered = {
        float(row["t_start"])
        for row in conn.execute(
            "SELECT e.t_start FROM edge e "
            "JOIN envelope v ON v.envelope_key = e.dst_key "
            "WHERE e.type = 'HAS_ENVELOPE' AND v.outer_wkb IS NOT NULL"
        ).fetchall()
    }
    for row in conn.execute(
        "SELECT e.t_start AS t FROM edge e "
        "JOIN envelope v ON v.envelope_key = e.dst_key "
        "WHERE e.type = 'HAS_ENVELOPE' AND v.outer_wkb IS NULL "
        "ORDER BY e.t_start"
    ).fetchall():
        if float(row["t"]) not in covered:
            return float(row["t"])
    raise AssertionError(
        "precondition failed: every frame with an envelope keeps a boundary, "
        "so the could-not-evaluate arm cannot be reached on this fixture"
    )


def test_a_point_inside_the_retained_boundary_answers_reachable(
    artifact: Path,
) -> None:
    """The positive half. A point the region contains comes back *not excluded*.

    The point is the region's own `representative_point()`, which shapely
    guarantees lies inside it, so this asserts the query reads the retained
    polygon rather than that a particular coordinate happens to be covered.
    """
    conn = store.connect(artifact)
    try:
        t, envelope_id, region = _first_retained_boundary(conn)
        inside = region.representative_point()
        answer = query.reached_point(conn, inside.x, inside.y, t)
    finally:
        conn.close()

    assert answer.verdict == ANSWERED
    assert answer.layer == query.EDGE_LAYER
    assert answer.value.could_have_reached is True
    assert answer.value.envelope_id == envelope_id
    assert answer.value.t == t
    assert answer.tolerances == {"time_s": TIME_TOL_S}


def test_a_point_outside_the_retained_boundary_answers_not_reachable(
    artifact: Path,
) -> None:
    """The negative half, and the direction that carries the safety claim.

    The outer set over-covers, so *outside* is a sound exclusion — the robot
    could not have been there. The point is the region's bounding box translated
    by its own width and height, which is outside it by construction and is
    derived from the file rather than invented.
    """
    conn = store.connect(artifact)
    try:
        t, _, region = _first_retained_boundary(conn)
        minx, miny, maxx, maxy = region.bounds
        answer = query.reached_point(
            conn, maxx + (maxx - minx), maxy + (maxy - miny), t
        )
    finally:
        conn.close()

    assert answer.verdict == ANSWERED
    assert answer.value.could_have_reached is False
    assert "outside" in answer.reason


def test_a_frame_with_no_boundary_is_a_could_not_evaluate(artifact: Path) -> None:
    """**THE TEST THIS ISSUE EXISTS FOR.** No boundary, no pointwise answer.

    The row at such a frame still carries `outer_radius`, and a radial verdict
    computed from it would be a plausible True/False in this answer's shape that
    nothing downstream could tell from a real one. So the verdict is
    COULD-NOT-EVALUATE, the value is `None` — not `False`, which reads as *the
    robot could not have reached it* — and the reason names the retention rule
    that decided it.
    """
    conn = store.connect(artifact)
    try:
        t = _uncovered_frame(conn)
        answer = query.reached_point(conn, 0.0, 0.0, t)
        radial = conn.execute(
            "SELECT count(outer_radius) AS n FROM envelope"
        ).fetchone()["n"]
    finally:
        conn.close()

    assert answer.verdict == COULD_NOT_EVALUATE
    assert answer.value is None
    assert query.OUTER_BOUNDARY_COLUMN in answer.reason
    assert query.META_GEOMETRY_RETENTION in answer.reason
    assert int(radial) > 0, (
        "precondition: the radius has to be present at that frame, or this test "
        "is not about a substitution that was available"
    )


def test_the_radius_still_answers_where_the_region_would_not(
    artifact: Path,
) -> None:
    """The substitution, made visible — and the reason the two are not one query.

    There are points inside `outer_radius` of the base and outside the retained
    region: the outer set is a union of sectors, not a disc. At such a point the
    exact answer is *excluded* and a radial one would have been *not excluded*,
    which is the whole distinction between *not at that distance* and *not at
    that point*. Issue #258 added a question and removed none, so the radius is
    still on the row and still travels on the answer.
    """
    import math

    import shapely

    conn = store.connect(artifact)
    try:
        t, envelope_id, region = _first_retained_boundary(conn)
        centre = graph.envelope_frame(conn, envelope_id)
        radius = float(
            store.envelope_row(conn, envelope_id)["outer_radius"]
        )
        witness = None
        for i in range(360):
            angle = math.radians(i)
            x = centre.x + 0.99 * radius * math.cos(angle)
            y = centre.y + 0.99 * radius * math.sin(angle)
            if not region.covers(shapely.Point(x, y)):
                witness = (x, y)
                break
        assert witness is not None, (
            "precondition failed: every point inside outer_radius is inside the "
            "retained region on this fixture, so the two answers cannot differ "
            "and this test is measuring nothing"
        )
        answer = query.reached_point(conn, witness[0], witness[1], t)
    finally:
        conn.close()

    assert answer.verdict == ANSWERED
    assert answer.value.could_have_reached is False, (
        "the region excludes this point; a radial answer would not"
    )
    assert answer.value.outer_radius_m == radius
    assert math.hypot(witness[0] - centre.x, witness[1] - centre.y) < radius


def test_the_answer_states_how_much_of_the_run_it_covers(artifact: Path) -> None:
    """Coverage on the answer **and** on the refusal, so a *no* cannot be misread.

    A caller has to be able to learn that a handful of the run's frames are
    pointwise-answerable, or *this artifact cannot answer at t* reads as *the
    robot could not have been there*. `pointwise_coverage` is public for the
    same reason: the number that makes a refusal readable must be reachable
    without an answer to hang it on.
    """
    conn = store.connect(artifact)
    try:
        coverage = query.pointwise_coverage(conn)
        t, _, region = _first_retained_boundary(conn)
        inside = region.representative_point()
        answered = query.reached_point(conn, inside.x, inside.y, t)
        refused = query.reached_point(conn, inside.x, inside.y, _uncovered_frame(conn))
        rows = conn.execute(
            "SELECT count(*) AS total, count(outer_wkb) AS stored, "
            "count(outer_radius) AS radial FROM envelope"
        ).fetchone()
        frames = int(float(store.get_meta(conn, query.META_FRAME_COUNT)))
    finally:
        conn.close()

    assert coverage == query.PointwiseCoverage(
        frames=frames,
        envelope_rows=int(rows["total"]),
        pointwise_rows=int(rows["stored"]),
        radial_rows=int(rows["radial"]),
    )
    assert 0 < coverage.pointwise_rows < coverage.frames
    assert answered.value.coverage == coverage
    for text in (answered.reason, refused.reason):
        assert f"{coverage.pointwise_rows} of this run's {frames} frame(s)" in text


def test_the_answer_carries_the_layer_tag_the_file_holds(
    artifact: Path, mobile_built: tuple[Path, Path]
) -> None:
    """The letter comes off the `HAS_ENVELOPE` edge, and is never inferred.

    The spec's own `layer_tag` is the **weaker** of the two the question can
    have, because a static letter cannot carry docs/sufficiency.md §5.1's
    condition — the `(x, y)` is a room coordinate, so the answer is only as
    strong as whatever put the robot in the room. The per-answer tag is the
    file's, and the two fixtures here are the two cases: a bolted arm whose
    bound came off its own limits, and a run whose base velocity came out of a
    perceiver.
    """
    assert query.QUERIES["reached_point"].layer_tag == query.LAYER_B

    seen = {}
    for path in (artifact, mobile_built[1]):
        conn = store.connect(path)
        try:
            t, envelope_id, region = _first_retained_boundary(conn)
            inside = region.representative_point()
            answer = query.reached_point(conn, inside.x, inside.y, t)
            edge = conn.execute(
                "SELECT e.layer AS layer FROM edge e "
                "JOIN node n ON n.node_key = e.dst_key "
                f"WHERE e.type = 'HAS_ENVELOPE' AND n.node_id = '{envelope_id}' "
                "ORDER BY e.edge_id LIMIT 1"
            ).fetchone()
        finally:
            conn.close()
        assert answer.verdict == ANSWERED, answer.reason
        assert answer.value.envelope_layer == str(edge["layer"])
        seen[path] = answer.value.envelope_layer

    assert set(seen.values()) == {query.LAYER_A, query.LAYER_B}, (
        "one fixture must tag its HAS_ENVELOPE edge A and the other B, or this "
        "test cannot tell a tag that is read from one that is assumed: "
        f"{seen}"
    )


def test_a_boundary_its_own_row_contradicts_is_a_could_not_evaluate(
    artifact: Path, tmp_path: Path
) -> None:
    """**THE TAMPER NEGATIVE.** An exclusion must not rest on bytes the row denies.

    No digest covers `outer_wkb` — `envelope_hash` is over the inner geometry
    and the chain commits to records — so a boundary replaced by a smaller one
    leaves `verify-chain` VERIFIED, and before this check the query then
    answered *excluded* for a point the robot could have reached: a confident
    false accusation, the one direction this query must never get wrong. The
    file still contradicts itself, because `outer_area` beside the blob is the
    original region's, and that disagreement is the only thing the reader can
    check with nothing but the file.

    The replacement is a 2 cm square about the region's own inside point, and
    the queried point is inside the original region and outside the square, so
    the preconditions below show the false accusation was genuinely available.
    """
    import shapely

    conn = store.connect(artifact)
    try:
        t, envelope_id, region = _first_retained_boundary(conn)
        inside = region.representative_point()
        minx, miny, maxx, maxy = region.bounds
        witness = None
        for i in range(1, 100):
            candidate = shapely.Point(
                minx + (maxx - minx) * i / 100.0, inside.y
            )
            if region.covers(candidate) and candidate.distance(inside) > 0.05:
                witness = candidate
                break
        assert witness is not None, (
            "precondition failed: no point of the retained region lies 5 cm "
            "from its inside point along that line, so nothing below is a "
            "point the replacement excludes and the original does not"
        )
        honest = query.reached_point(conn, witness.x, witness.y, t)
    finally:
        conn.close()
    assert honest.verdict == ANSWERED and honest.value.could_have_reached

    shrunk = shapely.box(inside.x - 0.01, inside.y - 0.01, inside.x + 0.01, inside.y + 0.01)
    assert not shrunk.covers(witness)
    tampered = _copy(
        artifact,
        tmp_path / "shrunk.sqlite",
        "UPDATE envelope SET outer_wkb = x'" + store.to_wkb(shrunk).hex() + "' "
        "WHERE envelope_key = (SELECT node_key FROM node WHERE node_id = "
        f"'{envelope_id}')",
    )
    conn = store.connect(tampered)
    try:
        answer = query.reached_point(conn, witness.x, witness.y, t)
    finally:
        conn.close()

    assert answer.verdict == COULD_NOT_EVALUATE
    assert answer.value is None, (
        "a refused answer must carry no verdict: False here is the accusation "
        "the tampered bytes would have produced"
    )
    assert "outer_area" in answer.reason
    assert envelope_id in answer.reason


def test_the_agreement_check_passes_every_boundary_the_builder_wrote(
    artifact: Path, mobile_built: tuple[Path, Path]
) -> None:
    """The positive half of the tamper check: it does not cry wolf.

    The row's `outer_area` and `outer_radius` are both measured before the
    region is placed, so on a posed frame the blob disagrees with each of them
    by a rigid transform's float noise as well as by the rounding. Both
    fixtures, every retained boundary, **both halves of the check** — the mobile
    one is the run whose frames are posed — and each must answer, or the check
    would refuse clean files and be switched off within a week.
    """
    for path in (artifact, mobile_built[1]):
        conn = store.connect(path)
        try:
            rows = conn.execute(
                "SELECT e.t_start AS t, v.outer_wkb AS wkb FROM edge e "
                "JOIN envelope v ON v.envelope_key = e.dst_key "
                "WHERE e.type = 'HAS_ENVELOPE' AND v.outer_wkb IS NOT NULL "
                "ORDER BY e.t_start, e.edge_id"
            ).fetchall()
            assert rows, f"precondition failed: {path} retains no boundary"
            for row in rows:
                inside = store.from_wkb(row["wkb"]).representative_point()
                answer = query.reached_point(
                    conn, inside.x, inside.y, float(row["t"])
                )
                if answer.verdict != ANSWERED:
                    # Two transitions inside one quantum is a separate refusal
                    # with its own test; it is not this check speaking.
                    assert "outer_area" not in answer.reason, answer.reason
                    # Nor the radius half of it (issue #265). The mobile run's
                    # frames are posed, so the stored radius is measured about
                    # the origin before `_place` and compared here about the
                    # centre the row states — which is where the float noise is,
                    # and the reason this loop covers both fixtures.
                    assert "outer_radius" not in answer.reason, answer.reason
        finally:
            conn.close()


def _moved_boundary(
    source: Path, target: Path, *, repair_radius: bool
) -> tuple[Path, float, str, object, object]:
    """A copy whose first retained boundary is the same region, somewhere else.

    `(path, t, envelope_id, original, moved)`. The translation is the region's
    own bounding-box width plus half a metre, so the two are disjoint and every
    point of the original is a point the replacement excludes — a false
    accusation available at each one, and far past `DISTANCE_TOL_M`.

    `repair_radius=True` also writes the moved region's radius into the row, and
    that copy is not a tamper test: it is what the file would have said with no
    radius check at all, which is the only way to show the accusation was
    genuinely on offer.
    """
    from shapely.affinity import translate

    conn = store.connect(source)
    try:
        t, envelope_id, original = _first_retained_boundary(conn)
    finally:
        conn.close()

    minx, _, maxx, _ = original.bounds
    moved = translate(original, xoff=(maxx - minx) + 0.5)
    statements = [
        "UPDATE envelope SET outer_wkb = x'" + store.to_wkb(moved).hex() + "' "
        "WHERE envelope_key = (SELECT node_key FROM node WHERE node_id = "
        f"'{envelope_id}')"
    ]
    if repair_radius:
        conn = store.connect(source)
        try:
            centre = store.envelope_base_frame(conn, envelope_id)
        finally:
            conn.close()
        statements.append(
            f"UPDATE envelope SET outer_radius = {outer_radius(moved, centre)!r} "
            "WHERE envelope_key = (SELECT node_key FROM node WHERE node_id = "
            f"'{envelope_id}')"
        )
    return _copy(source, target, *statements), t, envelope_id, original, moved


def test_a_boundary_moved_from_where_its_row_says_is_a_could_not_evaluate(
    artifact: Path, tmp_path: Path
) -> None:
    """**THE MOVED-REGION NEGATIVE.** The area check alone lets this through.

    A translation keeps the area exactly, so the comparison issue #258 shipped
    passes the region without a word — and every point of it has shifted, so
    points the robot could reach come back *excluded*. That is the one direction
    this answer must not get wrong, and it is why the row's `outer_radius`, a
    distance from the envelope's own centre, is the second half of the check.

    The preconditions are the test. Without them this is a refusal with no
    demonstration that anything was being refused: the first shows the area
    comparison still passes the moved region, and the second shows what the file
    says when only the radius check is missing — *excluded*, confidently, at a
    point the original covers.
    """
    honest_path, t, envelope_id, original, moved = _moved_boundary(
        artifact, tmp_path / "moved-consistent.sqlite", repair_radius=True
    )
    witness = original.representative_point()
    assert not moved.covers(witness), (
        "precondition failed: the translated region still covers the point, so "
        "nothing below is an exclusion the move invented"
    )

    conn = store.connect(artifact)
    try:
        truthful = query.reached_point(conn, witness.x, witness.y, t)
        stored_area = float(
            conn.execute(
                "SELECT outer_area AS a FROM envelope WHERE envelope_key = "
                "(SELECT node_key FROM node WHERE node_id = ?)",
                (envelope_id,),
            ).fetchone()["a"]
        )
    finally:
        conn.close()
    assert truthful.verdict == ANSWERED and truthful.value.could_have_reached

    # PRECONDITION 1: the area comparison, on its own, passes the moved region.
    quantum = 10.0 ** (
        math.floor(math.log10(stored_area)) - (query.AREA_QUANT_SIGFIGS - 1)
    )
    assert abs(moved.area - stored_area) <= quantum, (
        "precondition failed: the translation changed the area past its "
        "quantum, so issue #258's check would have caught this and the gap "
        "this test is about is not the one being exercised"
    )

    # PRECONDITION 2: with the radius agreeing too, the file accuses.
    conn = store.connect(honest_path)
    try:
        accusing = query.reached_point(conn, witness.x, witness.y, t)
    finally:
        conn.close()
    assert accusing.verdict == ANSWERED, accusing.reason
    assert not accusing.value.could_have_reached, (
        "precondition failed: a copy whose row agrees with the moved region in "
        "both figures must answer *excluded* here, or there is no false "
        "accusation for the radius check to stop"
    )

    # AND THE CHECK: the row still states the original radius, and it refuses.
    moved_path, *_ = _moved_boundary(
        artifact, tmp_path / "moved.sqlite", repair_radius=False
    )
    conn = store.connect(moved_path)
    try:
        answer = query.reached_point(conn, witness.x, witness.y, t)
    finally:
        conn.close()

    assert answer.verdict == COULD_NOT_EVALUATE
    assert answer.value is None, (
        "a refused answer must carry no verdict: False here is the accusation "
        "the moved region would have produced"
    )
    assert "outer_radius" in answer.reason
    assert envelope_id in answer.reason


def test_the_moved_region_reaches_the_cold_read_as_a_could_not_evaluate(
    artifact: Path, tmp_path: Path
) -> None:
    """And the row an assessor reads carries the refusal, not a state around it.

    `_reached_point_claim` probes the *first* retained boundary, which is the one
    `_moved_boundary` moves, so the check the cold read runs is the check that
    refuses — and the row reports what the query said rather than asserting a
    state about a check nobody watched fail.
    """
    moved_path, _, envelope_id, _, _ = _moved_boundary(
        artifact, tmp_path / "moved-cold.sqlite", repair_radius=False
    )
    assert _cold_read(artifact)[query.CLAIM_REACHED_POINT].state == query.CHECKABLE, (
        "precondition failed: the untampered fixture must be CHECKABLE here, or "
        "the state below says nothing about the move"
    )
    row = _cold_read(moved_path)[query.CLAIM_REACHED_POINT]
    assert row.state == COULD_NOT_EVALUATE
    assert not row.checkable
    assert "refuses" in row.detail and "outer_radius" in row.detail
    assert envelope_id in row.detail


def test_a_boundary_no_radius_can_be_measured_from_refuses(
    artifact: Path, tmp_path: Path
) -> None:
    """A blob whose *row agrees with it* and whose extent is still not defined.

    `reg.store.to_wkb` refuses an invalid geometry, so nothing this package
    writes lands here — but the blob is uncovered by any digest, so a file
    something else wrote can carry one, and with `outer_area` set to match it
    the comparison above waves it through. `reg.envelope.outer_radius` then
    raises rather than returning, and a caller asking about a point is owed an
    answer or a reason: a traceback is neither.
    """
    import shapely

    conn = store.connect(artifact)
    try:
        t, envelope_id, _ = _first_retained_boundary(conn)
    finally:
        conn.close()

    # Self-intersecting and of positive area, so it survives the area check
    # once the row is made to agree with it.
    ill_formed = shapely.Polygon(
        [(0, 0), (2, 0), (2, 2), (1, 2), (1, 1), (3, 1), (3, 3), (0, 3)]
    )
    assert not ill_formed.is_valid and ill_formed.area > 0, (
        "precondition failed: this fixture geometry must be invalid and have "
        "extent, or it is caught by a different arm than the one under test"
    )
    with pytest.raises(store.StoreError, match="invalid geometry"):
        store.to_wkb(ill_formed)

    broken = _copy(
        artifact,
        tmp_path / "ill-formed.sqlite",
        "UPDATE envelope SET outer_wkb = x'"
        + shapely.to_wkb(ill_formed).hex()
        + f"', outer_area = {ill_formed.area!r} "
        "WHERE envelope_key = (SELECT node_key FROM node WHERE node_id = "
        f"'{envelope_id}')",
    )
    conn = store.connect(broken)
    try:
        answer = query.reached_point(conn, 0.5, 0.5, t)
    finally:
        conn.close()

    assert answer.verdict == COULD_NOT_EVALUATE
    assert answer.value is None
    assert envelope_id in answer.reason
    assert "outer_radius" in answer.reason


def test_a_boundary_whose_centre_the_file_states_nowhere_refuses(
    artifact: Path, tmp_path: Path
) -> None:
    """**THE NO-CENTRE NEGATIVE.** A check that could not run is not one that passed.

    The containment test needs no centre — the retained region is already in the
    room frame — but the agreement check does, and `outer_radius` is a length
    about a point the artifact has to name. This fixture names the origin, so a
    reader that resolved the absence to `(0, 0)` would answer *exactly* what the
    honest file answers and nothing downstream could tell the two apart. That is
    the reason the absence refuses instead, and it is the same rule
    `reg.store.envelope_base_frame` states.
    """
    conn = store.connect(artifact)
    try:
        t, envelope_id, region = _first_retained_boundary(conn)
        witness = region.representative_point()
        honest = query.reached_point(conn, witness.x, witness.y, t)
        stated = store.get_meta(conn, store.META_BASE_FRAME)
    finally:
        conn.close()
    assert honest.verdict == ANSWERED and honest.value.could_have_reached
    assert stated is not None, (
        "precondition failed: this fixture must state a base frame, or "
        "deleting it below changes nothing"
    )

    stripped = _copy(
        artifact,
        tmp_path / "no-centre.sqlite",
        f"DELETE FROM meta WHERE key = '{store.META_BASE_FRAME}'",
    )
    conn = store.connect(stripped)
    try:
        answer = query.reached_point(conn, witness.x, witness.y, t)
        posed = conn.execute(
            "SELECT count(base_pose) AS posed FROM robot_config"
        ).fetchone()["posed"]
    finally:
        conn.close()
    assert int(posed) == 0, (
        "precondition failed: a configuration in this copy still states a "
        "pose, so the centre is readable and the deletion removed nothing"
    )
    assert answer.verdict == COULD_NOT_EVALUATE
    assert answer.value is None
    assert store.META_BASE_FRAME in answer.reason
    assert envelope_id in answer.reason


def test_an_artifact_written_before_the_boundary_column_refuses(
    artifact: Path, tmp_path: Path
) -> None:
    """**THE PRE-SCHEMA NEGATIVE.** No column is not *no region was retained*.

    A file written against schema 13 had nowhere to put a boundary. Reporting
    zero covered frames would say this build chose to retain none, which is a
    decision somebody would have had to take. `pointwise_coverage` refuses and
    the query reports a could-not-evaluate naming the schema; the arm is reached
    through raw `sqlite3` because `store.connect` refuses such a file, which is
    exactly how an assessor with an archive meets it.
    """
    import sqlite3 as _sqlite3

    older = _copy(artifact, tmp_path / "no-column.sqlite")
    conn = _sqlite3.connect(older)
    conn.row_factory = _sqlite3.Row
    try:
        # The column is named in a CHECK, so `ALTER TABLE ... DROP COLUMN`
        # refuses it. The table is rebuilt without it instead, which is the
        # shape a schema-13 file actually has.
        conn.execute(
            "CREATE TABLE envelope_13 AS SELECT envelope_key, envelope_hash, "
            "area, geometry_wkb, config_key, horizon, source, outer_area, "
            "outer_radius FROM envelope"
        )
        conn.execute("DROP TABLE envelope")
        conn.execute("ALTER TABLE envelope_13 RENAME TO envelope")
        conn.commit()
        answer = query.reached_point(conn, 0.0, 0.0, 0.0)
        with pytest.raises(QueryError) as caught:
            query.pointwise_coverage(conn)
    finally:
        conn.close()

    assert answer.verdict == COULD_NOT_EVALUATE
    assert answer.value is None
    assert query.OUTER_BOUNDARY_COLUMN in answer.reason
    assert str(store.SCHEMA_VERSION) in answer.reason
    assert query.OUTER_BOUNDARY_COLUMN in str(caught.value)


@pytest.mark.parametrize(
    "args",
    [
        (float("nan"), 0.0, 0.0),
        (0.0, float("inf"), 0.0),
        (0.0, 0.0, float("nan")),
        ("0.0", 0.0, 0.0),
    ],
)
def test_a_point_that_is_not_a_point_is_a_caller_error(artifact: Path, args) -> None:
    """A `QueryError` and not a refusal: the artifact would answer some other
    point, so this is the asker's mistake and not the file's silence."""
    conn = store.connect(artifact)
    try:
        with pytest.raises(QueryError):
            query.reached_point(conn, *args)
    finally:
        conn.close()


def test_the_cli_answers_the_point_question(artifact: Path, capsys) -> None:
    """`--reached-point X Y T`, and the three arguments are required together."""
    conn = store.connect(artifact)
    try:
        t, _, region = _first_retained_boundary(conn)
        inside = region.representative_point()
    finally:
        conn.close()

    code = query.main(
        [str(artifact), "--reached-point", str(inside.x), str(inside.y), str(t)]
    )
    out = capsys.readouterr().out
    assert code == query.EXIT_OK
    assert "verdict:    ANSWERED" in out
    assert "NOT EXCLUDED" in out
    assert "pointwise coverage:" in out


# --------------------------------------------------------------------------
# NEGATIVE: arguments the queries refuse, each naming what is available.
# --------------------------------------------------------------------------


def test_an_unknown_entity_is_refused_and_names_the_ones_present(
    artifact: Path,
) -> None:
    """Not an empty answer: "absence of an entity from the graph is not evidence
    of its absence from the room" (docs/lossiness.md *Unanswerable* #2)."""
    with pytest.raises(QueryError) as exc:
        _ask(artifact, query.separation_timeline, "human_0")
    message = str(exc.value)
    assert "human_0" in message
    assert graph.HUMAN_ENTITY_ID in message
    assert "obs_crate" in message


@pytest.mark.parametrize(
    "fn",
    [
        query.separation_timeline,
        query.first_envelope_intersection,
        query.min_separation,
        query.time_of_closest_approach,
        query.did_contact_occur,
    ],
)
def test_every_entity_query_refuses_an_unknown_entity(artifact: Path, fn) -> None:
    """One query refusing is not a boundary; all of them refusing is."""
    with pytest.raises(QueryError, match="not an entity"):
        _ask(artifact, fn, "nobody_by_that_name")


@pytest.mark.parametrize("threshold", [0.0, -0.5, float("nan"), float("inf")])
def test_a_threshold_that_is_not_a_positive_distance_is_refused(
    artifact: Path, threshold: float
) -> None:
    """No default and no clamp. A threshold of zero is the contact question and
    a non-finite one compares true against every interval in the file."""
    with pytest.raises(QueryError):
        _ask(artifact, query.frames_at_risk, graph.HUMAN_ENTITY_ID, threshold)


def test_a_window_outside_the_run_is_refused(artifact: Path) -> None:
    """Refused rather than clamped: a clamped window answers about a different
    time and says nothing about having done so."""
    conn = store.connect(artifact)
    try:
        first, last = query.run_interval(conn)
        with pytest.raises(QueryError, match="not inside this run"):
            query.reachable_entities(conn, first, last + 10.0)
        with pytest.raises(QueryError, match="not inside this run"):
            query.reachable_entities(conn, first - 10.0, last)
        with pytest.raises(QueryError, match="backwards"):
            query.reachable_entities(conn, last, first)
        with pytest.raises(QueryError):
            query.reachable_entities(conn, first, float("nan"))
    finally:
        conn.close()


def test_a_partial_timeline_is_not_a_timeline(artifact: Path, tmp_path: Path) -> None:
    """A separation layer with a hole in it is a could-not-evaluate.

    A short list compared elementwise against anything else lines frame 40 up
    against frame 41 and reports agreement or disagreement about neither.
    """
    conn = store.connect(artifact)
    try:
        times = query.frame_times(conn)
    finally:
        conn.close()
    middle = times[len(times) // 2]
    holed = _copy(
        artifact,
        tmp_path / "holed_timeline.sqlite",
        "DELETE FROM edge WHERE type = 'SEPARATION' "
        f"AND t_start <= {middle} AND t_end >= {middle}",
    )
    answer = _ask(holed, query.separation_timeline, graph.HUMAN_ENTITY_ID)
    assert answer.verdict == COULD_NOT_EVALUATE
    assert answer.value is None
    assert "frames" in answer.reason


# --------------------------------------------------------------------------
# The CLI. It formats; it does not answer.
# --------------------------------------------------------------------------


def test_list_names_every_supported_query(capsys) -> None:
    assert query.main(["--list"]) == query.EXIT_OK
    out = capsys.readouterr().out
    for name in query.QUERIES:
        assert "--" + name.replace("_", "-") in out
    # And the ones that do not exist yet are named as absent rather than left
    # to look like queries that returned nothing. `verify_chain` was on this
    # list until issue #49; it is now a flag, and
    # `test_the_query_list_names_verify_chain_and_what_is_still_absent` is what
    # checks the list moved it rather than dropped it.
    assert "incident_report" in out


def test_the_cli_answers_a_scene_query(artifact: Path, capsys) -> None:
    code = query.main(
        [str(artifact), "--separation-timeline", graph.HUMAN_ENTITY_ID]
    )
    out = capsys.readouterr().out
    assert code == query.EXIT_OK
    assert "verdict:    ANSWERED" in out
    assert "tolerances:" in out
    assert out.count("\n") > 10


@pytest.mark.parametrize(
    "argv_tail",
    [
        ["--separation-timeline", "human_0"],
        ["--frames-at-risk", graph.HUMAN_ENTITY_ID, "0"],
        ["--frames-at-risk", graph.HUMAN_ENTITY_ID, "not-a-number"],
        ["--reachable-entities", "0", "9999"],
    ],
)
def test_the_cli_exits_non_zero_and_says_why(
    artifact: Path, capsys, argv_tail: list[str]
) -> None:
    """"Unknown query or entity exits non-zero naming what is available, never
    empty output.\""""
    code = query.main([str(artifact), *argv_tail])
    captured = capsys.readouterr()
    assert code == query.EXIT_USAGE
    assert captured.err.strip(), "a refusal with no message is worse than a crash"


def test_naming_no_query_lists_the_ones_that_exist(artifact: Path, capsys) -> None:
    """Nothing is answered by default: a query layer that picked one would
    answer a question nobody asked."""
    code = query.main([str(artifact)])
    err = capsys.readouterr().err
    assert code == query.EXIT_USAGE
    assert "--separation-timeline" in err


def test_a_could_not_evaluate_has_its_own_exit_code(
    occurrence_view: Path, capsys
) -> None:
    """Answered, could-not-evaluate and refused are three outcomes, so they are
    three exit codes. Collapsing the middle one into either end is exactly the
    conflation this module refuses one level up."""
    code = query.main(
        [str(occurrence_view), "--separation-timeline", graph.HUMAN_ENTITY_ID]
    )
    out = capsys.readouterr().out
    assert code == query.EXIT_COULD_NOT_EVALUATE
    assert COULD_NOT_EVALUATE in out
    assert out.strip(), "never empty output"


def test_a_file_that_is_not_an_artifact_is_refused(tmp_path: Path, capsys) -> None:
    missing = tmp_path / "nothing.sqlite"
    assert query.main([str(missing), "--min-separation", "human"]) == query.EXIT_USAGE
    assert capsys.readouterr().err.strip()

    not_a_graph = tmp_path / "junk.sqlite"
    not_a_graph.write_bytes(b"not a database")
    assert (
        query.main([str(not_a_graph), "--min-separation", "human"])
        == query.EXIT_USAGE
    )
    assert capsys.readouterr().err.strip()


def test_render_is_pure_and_never_empty(artifact: Path) -> None:
    """The CLI formats and the functions return. `render` reads no file, so an
    answer can be formatted by a caller that did not fetch it."""
    answer = _ask(artifact, query.min_separation, graph.HUMAN_ENTITY_ID)
    text = query.render(answer)
    assert text.strip()
    assert query.render(answer) == text


# --------------------------------------------------------------------------
# --verify-chain and --tamper (issue #49).
#
# The walk itself is `tests/test_chain.py`'s. What is tested here is the CLI:
# four exit codes for four different facts, the flags that are refused rather
# than ignored, and the one import in `reg/query.py` that has to stay inside a
# function or Claim 2's "alone" stops being a property of the import graph.
# --------------------------------------------------------------------------

#: The chain fixture's parameters. Stated here for the reason
#: `tests/test_chain.py` states them: `emit_declarations` and `Enforcer` refuse
#: to invent any of the three, and a coarser frame period is the same run looked
#: at less often.
CHAIN_DT = 0.1
CHAIN_REPLAN_S = 0.5
CHAIN_HORIZON_S = 0.5
CHAIN_WATCHDOG_S = 1.0

#: Fixed material, not a secret and not pretending to be one — the same
#: discipline `tests/test_graph.py` uses, because `generate_keyring` is
#: deliberately unseeded.
CHAIN_KEYRING = chain.Keyring.from_material(
    policy=bytes(range(32)), enforcement=bytes(range(32, 64))
)


def _attested_build(tmp: Path, name: str) -> tuple[Path, Path]:
    """Build `name` with its own record stream. `(artifact, keyring)`.

    One definition, used by both attested fixtures below. Through
    `graph.attestation_from_stream` rather than a second copy of the
    policy/enforcer wiring, for the reason `tests/test_graph.py` gives: a
    fixture that assembled the records differently from the way the CLI does
    would be testing a run nobody can produce.
    """
    from dataclasses import replace as _replace

    from reg.sim import provenance
    from reg.stream import write_frames

    scn = _replace(scenario(name), dt=CHAIN_DT)
    csv = write_frames(scn.states(0), tmp / f"{name}.csv", comments=provenance(scn, 0))
    keyring_path = chain.write_keyring(CHAIN_KEYRING, tmp / "keyring.json")
    records = graph.attestation_from_stream(
        csv,
        scn,
        keyring_path=keyring_path,
        replan_interval_s=CHAIN_REPLAN_S,
        declaration_horizon_s=CHAIN_HORIZON_S,
        watchdog_period_s=CHAIN_WATCHDOG_S,
        # The same 0.05 the `graph.build` below is given. Spelled out for the
        # reason that build spells its parameters out, and it must match it:
        # one run, one discretisation (issue #106).
        substep_dt=0.05,
    )
    out = tmp / f"{name}.sqlite"
    # The envelope parameters are spelled out rather than taken from `_FAST`,
    # which names them the way `run_scenario` does; every call in this repo
    # passes them explicitly so no test depends on a default staying put.
    graph.build(
        csv,
        out,
        scn.world.limits,
        identity=TEST_IDENTITY,
        disclosures=TEST_DISCLOSURES,
        human_radius=scn.world.human_radius,
        records=records,
        horizon=0.1,
        n_samples=4,
        seed=0,
        substep_dt=0.05,
    )
    return out, keyring_path


@pytest.fixture(scope="module")
def attested(tmp_path_factory) -> tuple[Path, Path]:
    """`(artifact, keyring)` — one build with both record chains in it.

    `declared_violation`: the policy declares it will stay inside q0 <= 0.8 and
    then commands q0 out to 1.5, so the run holds a real
    `declaration_action_mismatch` and a real CLAMP. The human is parked far away,
    which is what makes this fixture the **negative** for the assumption check —
    the report cites no Layer B fact and must therefore carry no assumption.
    """
    return _attested_build(tmp_path_factory.mktemp("verify-chain"), "declared_violation")


@pytest.fixture(scope="module")
def clean_attested(tmp_path_factory) -> tuple[Path, Path]:
    """`(artifact, keyring)` for a run in which the policy kept its word.

    `contact` states no fixed `declared_q_bounds`, so its policy declares exactly
    the region its own upcoming configurations sweep — a true statement about
    itself, and every action is PERMITted. It is the fixture two negatives need:
    an incident report over a run with no incident must not raise, and the human
    *does* enter the envelope here, so the report cites a Layer B fact and has to
    populate `assumption` for it.
    """
    return _attested_build(tmp_path_factory.mktemp("clean-attested"), "contact")


def test_the_chain_import_is_deferred() -> None:
    """`reg.chain` reaches `reg.stream`, so `reg.query` may only import it
    inside the function that needs it.

    The runtime gate above already fails if this regresses — but it fails with
    "importing reg.query pulled in reg.stream", which does not say what to do
    about it. This one names the rule: the import stays in a function body.
    """
    tree = ast.parse(Path(query.__file__).read_text())
    module_level = set()
    for node in tree.body:  # only the top level, not ast.walk
        if isinstance(node, ast.Import):
            module_level.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            module_level.update(
                {node.module, *(f"{node.module}.{a.name}" for a in node.names)}
            )
    offenders = sorted(n for n in module_level if n.startswith("reg.chain"))
    assert not offenders, (
        f"reg/query.py imports {offenders} at module level. reg.chain imports "
        "reg.stream for the precision its canonical serialization commits to, "
        "so hoisting this import puts the raw stream one attribute away from "
        "every scene query. It belongs inside _verify_chain_cli."
    )
    assert "from reg import chain" in Path(query.__file__).read_text(), (
        "and it does have to be imported somewhere: --verify-chain must not "
        "grow a second copy of the canonicalization the MACs are taken over"
    )


def test_the_could_not_evaluate_spelling_is_one_string() -> None:
    """`reg.chain` and `reg.query` reach the same third verdict, and a
    vocabulary with two definitions is one that can drift."""
    assert chain.ChainState.COULD_NOT_EVALUATE.value == COULD_NOT_EVALUATE


def test_the_cli_verifies_an_intact_chain(attested, capsys) -> None:
    artifact, keyring = attested
    code = query.main([str(artifact), "--verify-chain", "--keyring", str(keyring)])
    out = capsys.readouterr().out
    assert code == query.EXIT_OK
    assert "VERIFIED" in out
    # Both chains, and what was actually checked in each — a verdict with no
    # counts beside it does not distinguish a walk over 250 records from a walk
    # over none.
    assert "policy (Declaration)" in out
    assert "enforcement (Verdict)" in out
    assert "links checked" in out and "MACs checked" in out


@pytest.mark.parametrize(
    "spec, expected_in_output",
    [
        ("declaration:first:horizon=9.5", "mac"),
        ("verdict:#3:t=99.5", "mac"),
        ("declaration:last:mac=" + "a" * 64, "mac"),
        ("verdict:#5:prev_hash=" + "b" * 64, "link"),
        ("verdict:last:delete", "count"),
    ],
)
def test_the_cli_exits_broken_on_a_tampered_copy(
    attested, tmp_path: Path, capsys, spec: str, expected_in_output: str
) -> None:
    """NEGATIVE, one per tamper mode, through the CLI a person actually runs.

    Exit 3 and not 1: a chain that broke and a chain that could not be checked
    are different facts, and a CI job that collapsed them would read a missing
    keyring as a tampered artifact.
    """
    artifact, keyring = attested
    code = query.main(
        [
            str(artifact),
            "--verify-chain",
            "--keyring",
            str(keyring),
            "--tamper",
            spec,
            "--tamper-out",
            str(tmp_path / "tampered.sqlite"),
        ]
    )
    out = capsys.readouterr().out
    assert code == query.EXIT_BROKEN
    assert "BROKEN" in out
    assert expected_in_output in out
    # What was changed, printed beside the verdict: "BROKEN" on its own is not
    # usable evidence.
    assert "tampered" in out


def test_the_cli_leaves_the_artifact_it_was_pointed_at_alone(
    attested, tmp_path: Path, capsys
) -> None:
    artifact, keyring = attested
    before = artifact.read_bytes()
    query.main(
        [
            str(artifact),
            "--verify-chain",
            "--keyring",
            str(keyring),
            "--tamper",
            "declaration:first:horizon=9.5",
            "--tamper-out",
            str(tmp_path / "copy.sqlite"),
        ]
    )
    capsys.readouterr()
    assert artifact.read_bytes() == before
    assert (
        query.main([str(artifact), "--verify-chain", "--keyring", str(keyring)])
        == query.EXIT_OK
    )


def test_the_cli_could_not_evaluate_without_a_key(attested, capsys) -> None:
    """NEGATIVE. No keyring, no MAC checked — exit 1, and never exit 0."""
    artifact, _ = attested
    code = query.main([str(artifact), "--verify-chain"])
    out = capsys.readouterr().out
    assert code == query.EXIT_COULD_NOT_EVALUATE
    assert COULD_NOT_EVALUATE in out
    assert "no key" in out


def test_the_cli_could_not_evaluate_on_an_artifact_with_no_records(
    artifact: Path, capsys
) -> None:
    """NEGATIVE. The build in this file was handed no record stream, and an
    artifact with nothing in it is not a verified artifact."""
    code = query.main([str(artifact), "--verify-chain"])
    out = capsys.readouterr().out
    assert code == query.EXIT_COULD_NOT_EVALUATE
    assert COULD_NOT_EVALUATE in out
    assert "no record stream" in out


@pytest.mark.parametrize(
    "argv_tail, match",
    [
        (["--verify-chain", "--tamper", "verdict:last:delete"], "--tamper-out"),
        (["--verify-chain", "--tamper-out", "x.sqlite"], "no --tamper was given"),
        (
            ["--verify-chain", "--tamper", "nonsense", "--tamper-out", "x.sqlite"],
            "CHAIN:SELECTOR:OP",
        ),
        (["--verify-chain", "--keyring", "no-such-keyring.json"], "keyring"),
        (["--min-separation", "human", "--tamper", "verdict:last:delete"], "--tamper"),
        (["--min-separation", "human", "--keyring", "k.json"], "--keyring"),
    ],
)
def test_the_cli_refuses_a_flag_it_would_otherwise_drop(
    artifact: Path, capsys, argv_tail: list[str], match: str
) -> None:
    """NEGATIVE. A flag silently ignored reads as one that was applied — and a
    tamper spec nobody can parse must never come back as a clean verdict."""
    code = query.main([str(artifact), *argv_tail])
    err = capsys.readouterr().err
    assert code == query.EXIT_USAGE
    assert match in err


def test_render_chain_report_is_pure_and_names_every_chain(attested) -> None:
    """The CLI formats; the walk returns. `render_chain_report` reads no file."""
    artifact, _ = attested
    conn = store.connect(artifact)
    try:
        report = chain.verify_chain(conn, CHAIN_KEYRING)
    finally:
        conn.close()
    text = query.render_chain_report(report)
    assert text.strip()
    assert query.render_chain_report(report) == text
    for result in report.chains:
        assert result.chain in text
        assert result.kind in text


def test_the_query_list_names_every_query_and_the_two_that_are_not_queries() -> None:
    """`--list` is the vocabulary, and since issue #50 nothing on it is absent.

    The three attestation queries print with the rest because they are
    `Answer`-returning queries now; `--verify-chain` and `--incident` are named
    below the table because neither returns an `Answer`. A name missing from this
    list reads as a milestone that has not landed, which is how "no violations"
    and "this build does not record violations" come to look the same.
    """
    text = query._list_text()
    assert "--verify-chain" in text
    assert "--tamper" in text
    assert "--incident" in text
    assert "incident_report" in text
    for name in ("declared_bound", "violations", "verdicts"):
        assert "--" + name.replace("_", "-") in text
        assert name in query.QUERIES
    assert "not implemented" not in text


# --------------------------------------------------------------------------
# THE ATTESTATION QUERIES AND THE INCIDENT REPORT (issue #50).
#
# The tests this section exists for, in order of how much they carry:
#
# **1. `test_no_attestation_query_touches_an_entity_bearing_edge`.** Every
# attestation query is Layer A, and docs/sufficiency.md §2 makes that the
# strongest claim the project makes: whether the policy honoured its own
# declaration is answerable from certifiable evidence, independently of whether
# perception was right. The test traces the SQL each query actually issues, so it
# is a property of what runs rather than of what a docstring says — and it ships
# with its negative, a scene query on the same artifact that the same trace
# catches touching Layer B.
#
# **2. `test_the_incident_report_names_the_declaration_the_fault_the_clamp_and_a_
# verified_chain`.** The money query, against the `declared_violation` fixture
# and cross-checked against the records that fixture actually produced — not
# against a synthetic pair, because the property being tested is a fact about
# that run.
#
# **3. The three negatives the issue names.** A clean fixture reports no incident
# and does not raise; a tampered artifact reports the broken chain *first*; and a
# report citing a Layer B fact carries its assumption while one citing none
# carries no assumption, which is what makes the assumption check able to fail at
# all.
# --------------------------------------------------------------------------

#: An instant `declared_violation` is violating at and two declarations cover.
INCIDENT_T = 3.5

#: An instant `contact`'s human is inside the computed envelope at, and a
#: declaration is in force at. The overlap runs t=2.0-3.4 in that fixture at
#: these envelope parameters; the midpoint is inside it with room either side.
CLEAN_T = 2.5


def _records_of(path: Path):
    """`(declarations, verdicts)` as the artifact holds them.

    The tests below assert against the fixture rather than against a rebuilt
    expectation, and these are the readers the rest of the repo uses. They are
    deliberately **not** what `reg.query` reads with — see
    `test_no_attestation_query_touches_an_entity_bearing_edge` and the module
    header of `reg/query.py`.
    """
    conn = store.connect(path)
    try:
        return store.read_declarations(conn), store.read_verdicts(conn)
    finally:
        conn.close()


def _report(path: Path, t: float, keyring) -> query.IncidentReport:
    conn = store.connect(path)
    try:
        return query.incident_report(conn, t, keyring)
    finally:
        conn.close()


# --- the property this issue exists for -----------------------------------


def _traced(path: Path, fn, *args) -> list[str]:
    """Every SQL statement one query issues, captured off the connection.

    Traced rather than read off the source, because what matters is which tables
    a query *touches at run time*. A helper that grew an entity join would pass
    any check made against this file's imports and fail here.
    """
    conn = store.connect(path)
    statements: list[str] = []
    conn.set_trace_callback(statements.append)
    try:
        fn(conn, *args)
    finally:
        conn.set_trace_callback(None)
        conn.close()
    return statements


#: Edge types that name an `Entity`, derived from the schema rather than listed
#: here: `reg.store.EDGE_SPECS` is the vocabulary's single definition and an
#: edge type added without a layer decision has to fail this test, not slip
#: through a hand-written tuple.
LAYER_B_EDGE_TYPES = tuple(
    name for name, spec in store.EDGE_SPECS.items() if spec.layer == "B"
)


def test_no_attestation_query_touches_an_entity_bearing_edge(attested) -> None:
    """**THE TEST OF THIS ISSUE.** docs/sufficiency.md §2, held at run time.

    Every attestation query is Layer A, and that is worth more than a comment:
    it means no perceptual error can make a policy that exceeded its declared
    bound look like one that did not. So the SQL each one issues is captured and
    checked — no `entity` table, no `occurrence` join, and no edge type
    `reg.store.EDGE_SPECS` marks Layer B.
    """
    artifact, _ = attested
    declarations, _ = _records_of(artifact)
    assert declarations, "precondition failed: this fixture holds no declarations"

    for fn, args in (
        (query.declared_bound, (INCIDENT_T,)),
        (query.violations, ((0.0, 5.0),)),
        (query.verdicts, (declarations[0].declaration_id,)),
        (query.acknowledgments, ()),
    ):
        statements = _traced(artifact, fn, *args)
        assert statements, f"{fn.__name__} issued no SQL at all"
        blob = " ".join(statements).upper()
        assert " ENTITY" not in blob and "ENTITY_ID" not in blob, (
            f"{fn.__name__} reads the entity table. Every attestation answer "
            "would then be only as strong as whatever supplied that entity's "
            "position, which is the whole asymmetry docs/sufficiency.md §2 "
            f"claims: {statements}"
        )
        for edge_type in LAYER_B_EDGE_TYPES:
            assert edge_type not in blob, (
                f"{fn.__name__} reads {edge_type} edges, which are Layer B "
                f"(reg.store.EDGE_SPECS): {statements}"
            )


def test_the_layer_check_says_no_when_it_is_pointed_at_a_scene_query(
    attested,
) -> None:
    """NEGATIVE for the test above. A check that only ever passes proves nothing.

    `separation_timeline` is Layer B by construction, so the same trace has to
    catch it — otherwise the assertion above is passing because it cannot fail.
    """
    artifact, _ = attested
    blob = " ".join(
        _traced(artifact, query.separation_timeline, graph.HUMAN_ENTITY_ID)
    ).upper()
    assert "ENTITY" in blob
    assert any(edge_type in blob for edge_type in LAYER_B_EDGE_TYPES)


def test_every_attestation_query_declares_layer_a(attested) -> None:
    """And says so in the answer, not only in the SQL it did not issue."""
    artifact, _ = attested
    declarations, _ = _records_of(artifact)
    for name in ("declared_bound", "violations", "verdicts", "acknowledgments"):
        spec = query.QUERIES[name]
        assert spec.layer_tag == query.LAYER_A
        assert spec.answerable_from == frozenset({query.ATTESTATION_LAYER})
        assert not spec.tolerance.startswith("|"), (
            "docs/lossiness.md gives the attestation queries no numeric "
            "tolerance: they are exact by construction"
        )
    for answer in (
        _ask(artifact, query.declared_bound, INCIDENT_T),
        _ask(artifact, query.violations, (0.0, 5.0)),
        _ask(artifact, query.verdicts, declarations[0].declaration_id),
        # `declared_violation` is 122 PERMITs and 129 CLAMPs and stops the robot
        # at no point, so this one is ANSWERED with an empty list — which is the
        # case the layer tag has to hold for too.
        _ask(artifact, query.acknowledgments),
    ):
        assert answer.verdict == ANSWERED, answer.reason
        assert answer.layer == query.ATTESTATION_LAYER
        assert answer.tolerances == {}


# --- query 5: declared_bound ----------------------------------------------


def test_declared_bound_reads_the_claim_the_policy_signed(attested) -> None:
    """Against the fixture's own records, field for field.

    `declared_violation` replans every 0.5 s with a 0.5 s horizon, so two claims
    are in force at an instant that lands on a replan boundary — and both come
    back. Picking one would be this module inventing a precedence rule nobody
    signed.
    """
    artifact, _ = attested
    declarations, _ = _records_of(artifact)
    answer = _ask(artifact, query.declared_bound, INCIDENT_T)
    assert answer.verdict == ANSWERED

    value = answer.value
    assert value.t == INCIDENT_T
    expected = [
        d
        for d in declarations
        if d.t_issued <= INCIDENT_T <= d.t_issued + d.horizon
    ]
    assert expected, "precondition failed: no declaration covers the incident"
    assert [b.declaration_id for b in value.bounds] == [
        d.declaration_id for d in expected
    ]
    for bound, record in zip(value.bounds, expected, strict=True):
        assert bound.seq == record.seq
        assert bound.t_issued == record.t_issued
        assert bound.horizon == record.horizon
        assert bound.action_class == record.action_class
        assert bound.area > 0.0
        assert bound.t_expires == record.t_issued + record.horizon
    assert value.window == (
        min(d.t_issued for d in expected),
        max(d.t_issued + d.horizon for d in expected),
    )


def test_declared_bound_refuses_an_instant_no_declaration_covers(attested) -> None:
    """NEGATIVE. A lapsed claim is not a claim, and the nearest one is a
    statement the policy had stopped standing behind."""
    artifact, _ = attested
    answer = _ask(artifact, query.declared_bound, 500.0)
    assert answer.verdict == COULD_NOT_EVALUATE
    assert answer.value is None
    assert "in force" in answer.reason


@pytest.mark.parametrize(
    "fn, args",
    [
        (query.declared_bound, (1.0,)),
        (query.violations, ((0.0, 1.0),)),
        (query.verdicts, ("anything",)),
        (query.acknowledgments, ()),
    ],
)
def test_an_artifact_with_no_record_layer_refuses_every_attestation_query(
    artifact: Path, fn, args
) -> None:
    """NEGATIVE, and the distinction the whole project is about.

    The `artifact` fixture was built with no record stream. "This build stores
    no verdicts" and "this run produced none" are the same empty table and
    different facts, so the refusal names `meta[attestation_records]` rather
    than coming back as an empty list.
    """
    answer = _ask(artifact, fn, *args)
    assert answer.verdict == COULD_NOT_EVALUATE
    assert answer.value is None
    assert query.META_ATTESTATION_RECORDS in answer.reason


def test_an_attestation_query_refuses_an_artifact_missing_the_retention_rule(
    attested, tmp_path: Path
) -> None:
    """NEGATIVE. Without the rule in the file, an empty result is silence.

    The closed-world reading — "no commanded action here was refused" — is
    licensed by `meta[attestation_retention]` saying every record the run
    produced was stored. Strip it and the answer has to become a refusal, not
    an empty tuple. Exactly the discipline `did_contact_occur` follows for
    `occurrence_retention` one layer over.
    """
    artifact, _ = attested
    stripped = _copy(
        artifact,
        tmp_path / "no_rule.sqlite",
        f"DELETE FROM meta WHERE key = '{query.META_ATTESTATION_RETENTION}'",
    )
    answer = _ask(stripped, query.violations, (0.0, 5.0))
    assert answer.verdict == COULD_NOT_EVALUATE
    assert answer.value is None, "silence read as 'nothing was refused'"
    assert query.META_ATTESTATION_RETENTION in answer.reason


# --- query 6: violations ---------------------------------------------------


def test_violations_names_every_refused_action_with_its_fault(attested) -> None:
    """Against the fixture: the exact set of `(t, fault_code)` the record holds.

    docs/lossiness.md's agreement table gives this query no tolerance — a missed
    or invented fault is a failure, not a near miss — so the comparison is set
    equality against the verdicts the fixture actually signed.
    """
    artifact, _ = attested
    _, records = _records_of(artifact)
    answer = _ask(artifact, query.violations, (0.0, 5.0))
    assert answer.verdict == ANSWERED

    value = answer.value
    expected = [v for v in records if v.outcome != "PERMIT" and 0.0 <= v.t <= 5.0]
    assert expected, "precondition failed: this fixture refused nothing"
    assert {(a.t, a.fault) for a in value.actions} == {
        (v.t, v.fault) for v in expected
    }
    assert value.faults == ("declaration_action_mismatch",)
    assert value.adjudications == len([v for v in records if 0.0 <= v.t <= 5.0])
    assert value.began == min(v.t for v in expected)
    assert all(a.outcome == "CLAMP" for a in value.actions)
    assert all(a.applied_envelope_id is not None for a in value.actions), (
        "a CLAMP applied a bound and the ENFORCED edge is where it is recorded"
    )


def test_violations_on_a_clean_run_is_an_answer_and_not_a_refusal(
    clean_attested,
) -> None:
    """The other half of the three-state discipline. `contact`'s policy declares
    exactly what it goes on to do, so the honest answer is an empty set —
    ANSWERED with no actions, never a could-not-evaluate and never a raise."""
    artifact, _ = clean_attested
    answer = _ask(artifact, query.violations, (0.0, 5.0))
    assert answer.verdict == ANSWERED
    assert answer.value.actions == ()
    assert answer.value.faults == ()
    assert answer.value.adjudications > 0, (
        "an empty window would make this vacuous: the run has to have been "
        "adjudicated for 'nothing was refused' to mean anything"
    )
    assert answer.value.began is None


def test_violations_refuses_a_backwards_window(attested) -> None:
    """NEGATIVE. A backwards window matches no verdict, so it would come back as
    'no action was refused' rather than as the mistake it is."""
    artifact, _ = attested
    with pytest.raises(QueryError, match="backwards"):
        _ask(artifact, query.violations, (4.0, 1.0))


# --- query 7: verdicts -----------------------------------------------------


def test_verdicts_does_not_flatten_one_declaration_into_one_verdict(
    attested,
) -> None:
    """Issue #43's property, read back out through the query API.

    A verdict is per commanded action, so one declaration of this fixture is
    adjudicated PERMIT and later CLAMP. A query that returned one verdict per
    declaration would pass every other test here and would have lost *when* the
    violation began — the demo sentence's second clause.
    """
    artifact, _ = attested
    declarations, records = _records_of(artifact)
    by_declaration: dict[str, set[str]] = {}
    for verdict in records:
        if verdict.declaration_id is not None:
            by_declaration.setdefault(verdict.declaration_id, set()).add(
                verdict.outcome
            )
    both = sorted(k for k, o in by_declaration.items() if len(o) > 1)
    assert both, (
        "precondition failed: no declaration in this fixture is adjudicated "
        "more than one way, so the property below is not being tested"
    )

    answer = _ask(artifact, query.verdicts, both[0])
    assert answer.verdict == ANSWERED
    value = answer.value
    assert value.declaration_id == both[0]
    assert len(value.adjudications) == len(
        [v for v in records if v.declaration_id == both[0]]
    )
    assert set(value.outcomes) == by_declaration[both[0]]
    assert {"PERMIT", "CLAMP"} <= set(value.outcomes)
    assert [a.seq for a in value.adjudications] == sorted(
        a.seq for a in value.adjudications
    )


def test_verdicts_refuses_an_unknown_declaration_and_names_what_is_present(
    attested,
) -> None:
    """NEGATIVE. Not an empty list: an empty adjudication list for a record
    nobody signed reads as a claim enforcement never checked, which is a finding
    and not an absence."""
    artifact, _ = attested
    declarations, _ = _records_of(artifact)
    with pytest.raises(QueryError) as exc:
        _ask(artifact, query.verdicts, "no-such-declaration")
    message = str(exc.value)
    assert "no-such-declaration" in message
    assert declarations[0].declaration_id in message


# --- the acknowledgment query: was the passivation cleared, and by whom -----
#
# Issue #247. The three-valued part is what these are about: an ANSWERED with
# an empty list, an ANSWERED with every passivation carrying its record, and a
# COULD-NOT-EVALUATE that must never read as "nobody acknowledged it".


@pytest.fixture(scope="module")
def acknowledged(tmp_path_factory) -> tuple[Path, Path]:
    """`(artifact, keyring)` for the one shipped fixture whose operator clears.

    `stale_declaration` goes silent from t=2.0, its last declaration expires,
    enforcement passivates, and `AckPoint(2.5, ...)` is the operator saying why
    it is safe to resume. The policy never speaks again, so the run holds a
    passivation that was **acknowledged and never lifted** — which is the shape
    the query has to answer about, not a tidier one.
    """
    return _attested_build(
        tmp_path_factory.mktemp("acknowledged"), "stale_declaration"
    )


def test_the_acknowledgment_query_names_the_passivation_and_who_cleared_it(
    acknowledged,
) -> None:
    """**THE QUESTION ISSUE #247 EXISTS TO MAKE ASKABLE**, from the file alone.

    Field for field against the records the fixture's own enforcer signed, not
    against constants written here: the reason is the operator's sentence, the
    instant is the one the acknowledgment was signed at, and the verdict named
    is the one that actually passivated.

    **`party` and `operator_id` are two fields on purpose.** The record is
    signed under the enforcement key and carries no human field, so what the
    artifact can attribute is the key-holding role; `operator_id` is separately
    what the *build* was told (issue #83). Blending them would answer *by whom*
    with a name nobody signed for.
    """
    artifact, _ = acknowledged
    _, verdicts = _records_of(artifact)
    conn = store.connect(artifact)
    try:
        stored = store.read_acknowledgments(conn)
    finally:
        conn.close()
    assert len(stored) == 1, (
        "the fixture stopped producing an acknowledgment, so this test is no "
        "longer about the query"
    )
    record = stored[0]

    answer = _ask(artifact, query.acknowledgments)
    assert answer.verdict == ANSWERED, answer.reason
    assert answer.layer == query.ATTESTATION_LAYER
    assert answer.tolerances == {}

    value = answer.value
    assert value.answered
    assert value.unmatched == ()
    assert len(value.passivations) == 1, (
        "this fixture stops once and does not resume; more than one passivation "
        "means the derivation below is not walking the run this test describes"
    )
    passivation = value.passivations[0]

    passivating = {v.verdict_id: v for v in verdicts if v.outcome in ("VETO", "SAFE_STATE")}
    assert passivation.verdict_id in passivating, (
        "the query opened a passivation on a verdict enforcement did not "
        "passivate on"
    )
    opener = passivating[passivation.verdict_id]
    assert passivation.fault == opener.fault
    assert passivation.t_start == opener.t
    assert passivation.t_end is None, (
        "the policy never speaks again in this fixture, so the passivation has "
        "no end — and None is that fact rather than a missing value"
    )
    assert passivation.verdicts > 1, (
        "every frame after the expiry re-reports the stop, so the passivation "
        "covers more verdicts than the one that opened it"
    )

    assert passivation.acknowledged
    ack = passivation.acknowledgment
    assert (ack.ack_id, ack.seq, ack.t, ack.fault, ack.reason) == (
        record.ack_id,
        record.seq,
        record.t,
        record.fault,
        record.reason,
    )
    assert ack.party == query.ACKNOWLEDGING_PARTY
    assert ack.operator_id == TEST_IDENTITY.operator_id
    assert ack.reason.strip(), "a rubber stamp reached the artifact"
    assert record.verdict_id == passivation.verdict_id


#: The two occurrence types `reg.graph._OccurrenceLog` writes when enforcement
#: stops the robot: a refused declaration and a passivation entered on some
#: other fault. Both are written once at the transition and not per frame, which
#: is what makes their count comparable with a count of passivations.
PASSIVATION_OCCURRENCES = ("declaration_vetoed", "safe_state_entered")


def test_the_passivation_the_query_derives_is_the_one_the_occurrence_log_recorded(
    acknowledged,
) -> None:
    """TWO DERIVATIONS OF ONE FACT, HELD AGAINST EACH OTHER.

    `reg.query.acknowledgments` walks the verdict stream and decides where a
    passivation opened and where it closed; `reg.graph`'s occurrence log decided
    the same thing at build time, from the fault taxonomy rather than from the
    outcome, and wrote it into the occurrence layer. Neither reads the other. If
    they disagree, one of them is wrong about when the robot was stopped and a
    reader has no way to tell which, so they are compared here rather than
    trusted apart.

    **The two rules are not the same rule.** The log passivates on
    `fault in reg.enforce.PASSIVATING_FAULTS`; the query passivates on
    `outcome in PASSIVATING_OUTCOMES`. They pick out the same verdicts only
    because the one non-passivating fault is the one whose response is the
    CLAMP — which is exactly the coincidence
    `test_the_passivating_outcomes_are_the_enforcers` pins, and this is that
    coincidence checked against a real run.
    """
    artifact, _ = acknowledged
    conn = store.connect(artifact)
    try:
        opened = [
            row
            for kind in PASSIVATION_OCCURRENCES
            for row in store.read_occurrences(conn, occurrence_type=kind)
        ]
        resumed = store.read_occurrences(conn, occurrence_type="reintegrated")
    finally:
        conn.close()
    assert opened, (
        "the fixture recorded no passivation occurrence, so this comparison has "
        "only one side and checks nothing"
    )

    value = _ask(artifact, query.acknowledgments).value
    assert len(value.passivations) == len(opened)
    # The occurrence instant is quantized to `OCCURRENCE_TIME_RESOLUTION_S` and
    # the record's is not — docs/lossiness.md Retained #5 stores a record's own
    # `t` unquantized on purpose — so the comparison is at the coarser of the
    # two. Comparing at TIME_TOL_S would be asserting that this level carries a
    # precision it says it does not.
    for passivation, row in zip(value.passivations, sorted(opened, key=lambda r: r["t"])):
        assert passivation.t_start == pytest.approx(
            float(row["t"]), abs=graph.OCCURRENCE_TIME_RESOLUTION_S
        )
    assert len(resumed) == sum(1 for p in value.passivations if p.t_end is not None), (
        "the two sides disagree about whether the run came back out of its "
        "passivation, which is the second half of the same derivation"
    )


def test_a_run_that_stopped_for_nothing_is_answered_and_not_a_refusal(
    clean_attested,
) -> None:
    """AN EMPTY LIST THAT IS AN ANSWER, and the only one in this query.

    `contact` declares exactly what it then does, so every action is PERMITted
    and enforcement never stops the robot. Nothing needed acknowledging, so the
    question is **closed** — reporting a could-not-evaluate here would make the
    query unable to say that a run was clean, which is a finding it has to be
    able to make.
    """
    artifact, _ = clean_attested
    answer = _ask(artifact, query.acknowledgments)
    assert answer.verdict == ANSWERED, answer.reason
    assert answer.value.passivations == ()
    assert answer.value.unmatched == ()
    assert answer.value.answered


def test_a_passivation_nobody_acknowledged_is_a_could_not_evaluate_never_a_no(
    acknowledged, tmp_path: Path
) -> None:
    """**THE NEGATIVE THIS QUERY EXISTS FOR.** Silence is not an acquittal.

    Drop the acknowledgment row from a copy — the shape of an artifact built
    from a run in which nobody told the enforcer anything — and the passivation
    is still there and still unexplained. The answer must be a refusal that
    names the verdict, not an `acknowledged=False` a reader would quote as *the
    passivation was never acknowledged*. What the artifact records is what
    enforcement was **told**: an operator who inspected the cell and never said
    so leaves exactly this absence, and so does one who did nothing.
    """
    artifact, _ = acknowledged
    control = _ask(artifact, query.acknowledgments)
    assert control.verdict == ANSWERED, (
        "the control build already refuses, so the refusal below says nothing "
        "about the dropped record"
    )
    verdict_id = control.value.passivations[0].verdict_id

    stripped = _copy(
        artifact, tmp_path / "unacknowledged.sqlite", "DELETE FROM acknowledgment"
    )
    answer = _ask(stripped, query.acknowledgments)
    assert answer.verdict == COULD_NOT_EVALUATE
    assert answer.value is None, (
        "a value here would let a reader quote the passivation as unacknowledged"
    )
    assert verdict_id in answer.reason
    assert "by whom" in answer.reason


def test_an_acknowledgment_of_a_verdict_that_stopped_nothing_is_refused(
    acknowledged, tmp_path: Path
) -> None:
    """THE OTHER NEGATIVE: a record the walk cannot place is not dropped.

    Turn the passivating verdict into a PERMIT on a copy and the acknowledgment
    names a verdict that opened no passivation. Placing it anyway would report a
    passivation nobody made; dropping it would hide a signed record. So the
    answer is a refusal naming the acknowledgment, and `Passivations.unmatched`
    is where it stays visible.
    """
    artifact, _ = acknowledged
    control = _ask(artifact, query.acknowledgments)
    ack_id = control.value.passivations[0].acknowledgment.ack_id
    verdict_id = control.value.passivations[0].verdict_id

    rewritten = _copy(
        artifact,
        tmp_path / "unmatched.sqlite",
        "UPDATE verdict SET outcome = 'PERMIT', fault = NULL "
        "WHERE verdict_key = (SELECT node_key FROM node "
        f"WHERE node_id = '{verdict_id}')",
    )
    answer = _ask(rewritten, query.acknowledgments)
    assert answer.verdict == COULD_NOT_EVALUATE
    assert answer.value is None
    assert ack_id in answer.reason


def test_the_acknowledging_party_is_the_signing_role() -> None:
    """`reg.query` may not import `reg.enforce`, so it spells the role itself.

    The cost of that is paid here, exactly as it is for `PERMIT` and `VERIFIED`
    above: a rename on the enforcement side would otherwise make every answer
    attribute an acknowledgment to a party that no longer signs one.
    """
    from reg import enforce

    assert query.ACKNOWLEDGING_PARTY == enforce.Acknowledgment.SIGNING_ROLE


def test_the_passivating_outcomes_are_the_enforcers() -> None:
    """The same discipline, one vocabulary over — and it is the derivation, not
    a copy of the tuple.

    `reg.enforce` passivates on every fault except `declaration_action_mismatch`,
    whose response is the CLAMP. So *the outcomes that are neither PERMIT nor
    CLAMP* and *the outcomes that passivate* are the same two strings, and this
    fails if either side moves.
    """
    from reg import enforce

    assert set(query.PASSIVATING_OUTCOMES) == set(enforce.OUTCOMES) - {
        query.PERMITTED_OUTCOME,
        "CLAMP",
    }
    assert enforce.PASSIVATING_FAULTS == frozenset(enforce.FAULTS) - {
        "declaration_action_mismatch"
    }


# --- query 8: verify_chain, reachable from the query API -------------------


def test_verify_chain_is_reachable_from_the_query_api(attested) -> None:
    """docs/plan.md Phase 7 lists it beside the other three, so it is beside
    them — and it is the same walk, not a second one."""
    artifact, _ = attested
    conn = store.connect(artifact)
    try:
        report = query.verify_chain(conn, CHAIN_KEYRING)
        assert report.state is chain.ChainState.VERIFIED
        assert report == chain.verify_chain(conn, CHAIN_KEYRING)
    finally:
        conn.close()


def test_the_vocabularies_this_module_names_are_the_ones_that_define_them() -> None:
    """`reg.query` cannot import `reg.enforce` or `reg.chain` at module level, so
    it spells `PERMIT` and `VERIFIED` itself. The cost of that is paid here: a
    rename on either side fails now rather than turning every incident report
    into a false pass months later."""
    from reg import enforce

    assert query.PERMITTED_OUTCOME in enforce.OUTCOMES
    assert query.CHAIN_VERIFIED == chain.ChainState.VERIFIED.value
    assert query.LAYER_A == "A" and query.LAYER_B == "B"
    # Union over `possible_layers`, not over `spec.layer`: `HAS_ENVELOPE`'s layer
    # is a set rather than one value, because it follows `Limits.source` and not
    # the edge type (issue #84). The property being pinned is unchanged — the two
    # strings `reg.query` spells out are exactly the ones `reg.store` writes.
    written = set().union(
        *(store.possible_layers(edge_type) for edge_type in store.EDGE_SPECS)
    )
    assert written == {query.LAYER_A, query.LAYER_B}


# --- the money query -------------------------------------------------------


def test_the_incident_report_names_the_declaration_the_fault_the_clamp_and_a_verified_chain(
    attested,
) -> None:
    """**THE MONEY TEST**, against the fixture and not a synthetic record.

    docs/plan.md Phase 7's demo sentence, in four clauses and in order: what the
    policy declared, where the commanded action left it, what enforcement did
    about it, and that neither side rewrote the record.
    """
    artifact, _ = attested
    declarations, records = _records_of(artifact)
    report = _report(artifact, INCIDENT_T, CHAIN_KEYRING)

    assert report.answered
    assert report.incident
    assert report.integrity == chain.ChainState.VERIFIED.value
    assert report.integrity_verified

    # ...the declaration.
    covered = [
        d
        for d in declarations
        if d.t_issued <= INCIDENT_T <= d.t_issued + d.horizon
    ]
    assert [b.declaration_id for b in report.bounds] == [
        d.declaration_id for d in covered
    ]

    # ...the fault, and the CLAMP.
    assert report.violation is not None
    assert report.violation.fault == "declaration_action_mismatch"
    assert report.violation.outcome == "CLAMP"
    assert report.violation.applied_envelope_id is not None
    signed = {v.verdict_id: v for v in records}[report.violation.verdict_id]
    assert (signed.outcome, signed.fault, signed.t) == (
        report.violation.outcome,
        report.violation.fault,
        report.violation.t,
    )

    # ...the time the violation began, over the whole record and not over a
    # window this report chose for itself.
    refused = [v for v in records if v.outcome != "PERMIT"]
    assert report.first_refusal is not None
    assert report.first_refusal.t == min(v.t for v in refused)

    # ...and all of it in the prose, in docs/plan.md Phase 7's shape.
    text = query.render_incident(report)
    assert covered[0].declaration_id in text
    assert "DECLARATION_ACTION_MISMATCH" in text
    assert "CLAMP" in text
    assert "Chain verified" in text
    assert f"{report.violation.t:.4f}" in text

    # ...under GSN field names, which is what makes it liftable into a safety
    # case rather than transcribable into one (docs/prior-art.md §7).
    for field in query.GSN_FIELDS:
        assert hasattr(report, field)
        assert f"{field}:" in text
    assert report.goal and report.strategy and report.justification
    assert any(item.kind == "declaration" for item in report.solution)
    assert any(item.kind == "verdict" for item in report.solution)
    assert any(item.kind == "chain" for item in report.solution)


def test_a_clean_fixture_reports_no_incident_and_does_not_raise(
    clean_attested,
) -> None:
    """NEGATIVE. "There was no incident" is an answer, and a query that raised on
    a clean run could not be used to check whether a run was clean."""
    artifact, _ = clean_attested
    report = _report(artifact, CLEAN_T, CHAIN_KEYRING)

    assert report.answered
    assert not report.incident
    assert report.violation is None
    assert report.first_refusal is None
    assert report.integrity_verified
    assert report.bounds, "a clean report still says what was declared"
    text = query.render_incident(report)
    assert "No incident" in text
    assert "incident:   no" in text


def test_a_t_incident_no_declaration_covers_is_a_could_not_evaluate_report(
    attested,
) -> None:
    """NEGATIVE, and the distinction issue #41 already enforces for the scene
    queries: an empty report and a refusal are different facts."""
    artifact, _ = attested
    report = _report(artifact, 500.0, CHAIN_KEYRING)
    assert report.verdict == COULD_NOT_EVALUATE
    assert not report.answered
    assert not report.incident
    assert report.bounds == ()
    assert report.reason.strip()
    text = query.render_incident(report)
    assert COULD_NOT_EVALUATE in text
    assert "cannot say what the policy declared" in text


def test_a_tampered_artifact_reports_the_broken_chain_first(
    attested, tmp_path: Path
) -> None:
    """NEGATIVE, and the ordering rule the issue makes explicit.

    Produced with issue #49's `--tamper` rather than by editing a row here, so
    the artifact under test is one the shipped tool makes. Every other line of
    the report is a claim about a record whose integrity is now in question, and
    a report that buried that at the bottom would be misleading in exactly the
    way this project exists to prevent.
    """
    artifact, _ = attested
    tampered = chain.tamper(
        artifact,
        tmp_path / "tampered.sqlite",
        "declaration:first:horizon=9.5",
    )
    assert tampered.field == "horizon", "precondition: one field, one record"

    report = _report(tampered.copy, INCIDENT_T, CHAIN_KEYRING)
    assert report.integrity == chain.ChainState.BROKEN.value
    assert not report.integrity_verified
    assert report.clauses[0].name == query.CLAUSE_INTEGRITY, (
        f"the integrity clause is at index "
        f"{[c.name for c in report.clauses].index(query.CLAUSE_INTEGRITY)}, not "
        "first. Every clause after it is a claim about this record."
    )
    # The integrity clause carries the chain's own state. BROKEN is a finding
    # rather than a failure to look — what it must never be is a pass.
    assert report.clauses[0].verdict == chain.ChainState.BROKEN.value
    assert report.clauses[0].answered

    text = query.render_incident(report)
    assert "INTEGRITY BROKEN" in text
    assert text.index("INTEGRITY BROKEN") < text.index("the policy declared"), (
        "the integrity failure has to precede every claim that depends on it"
    )
    assert tampered.record_id in text


def test_a_report_over_a_verified_chain_puts_the_integrity_clause_last(
    attested,
) -> None:
    """The positive half of the ordering rule, so "first" is a decision the
    report makes rather than a constant it always emits."""
    artifact, _ = attested
    report = _report(artifact, INCIDENT_T, CHAIN_KEYRING)
    assert report.clauses[-1].name == query.CLAUSE_INTEGRITY
    assert report.clauses[-1].verdict == chain.ChainState.VERIFIED.value
    assert report.clauses[0].name == query.CLAUSE_DECLARED


def test_a_report_with_no_keyring_is_not_a_pass(attested) -> None:
    """NEGATIVE. Not having checked a MAC is not the same as having checked it.

    The links are still walked, no MAC is checked, and the chain comes back
    COULD-NOT-EVALUATE — which moves the integrity clause to the front, because
    a report over a record nobody authenticated is exactly a report whose
    integrity is in question.
    """
    artifact, _ = attested
    report = _report(artifact, INCIDENT_T, None)
    assert report.integrity == chain.ChainState.COULD_NOT_EVALUATE.value
    assert not report.integrity_verified
    assert report.clauses[0].name == query.CLAUSE_INTEGRITY
    assert not report.clauses[0].answered, (
        "an unchecked chain learned nothing, which is the one verdict that is "
        "neither a pass nor a finding"
    )
    assert "no key" in query.render_incident(report).lower()


# --- Claim 3: the assumption slot, and the negative that makes it real -----


def test_a_layer_b_fact_in_the_report_carries_its_assumption(
    clean_attested,
) -> None:
    """`contact` puts the human inside the computed envelope during the window,
    so the report cites a Layer B fact — and an incident report that quoted a
    conditional claim as certifiable is the one thing Claim 3 exists to stop."""
    artifact, _ = clean_attested
    report = _report(artifact, CLEAN_T, CHAIN_KEYRING)

    assert report.scene, (
        "precondition failed: no entity is inside the envelope in this window, "
        "so there is no Layer B fact for the report to be honest about"
    )
    assert any(item.layer == query.LAYER_B for item in report.solution)
    assert report.assumption, (
        "the report cites a Layer B evidence item and carries no assumption, "
        "which quotes a conditional claim as certifiable"
    )
    assert any(graph.HUMAN_ENTITY_ID in text for text in report.assumption)

    text = query.render_incident(report)
    assert "[B]" in text
    assert "Layer B" in text
    # And the attestation half is unaffected by it — docs/sufficiency.md §2,
    # visible in the output rather than asserted in a paragraph.
    assert report.clause(query.CLAUSE_DECLARED).layer == query.LAYER_A
    assert report.clause(query.CLAUSE_DECLARED).answered


def test_a_report_citing_no_layer_b_fact_carries_no_assumption(attested) -> None:
    """NEGATIVE for the test above, and the reason the check can fail at all.

    `declared_violation` parks the human far away, so nothing intersects the
    envelope and the report cites no Layer B evidence. An `assumption` that were
    always populated would make the positive test vacuous — and would attach a
    perception caveat to a finding that does not rest on perception, which is
    the same error in the other direction.
    """
    artifact, _ = attested
    report = _report(artifact, INCIDENT_T, CHAIN_KEYRING)
    assert report.scene == ()
    assert all(item.layer == query.LAYER_A for item in report.solution)
    assert report.assumption == ()
    assert report.incident, (
        "and the finding is still made: an all-Layer-A report is the strong "
        "case, not a degraded one"
    )
    assert "carries no assumption" in query.render_incident(report)


def test_the_assumption_slot_is_populated_exactly_by_the_layer_b_evidence(
    attested, clean_attested
) -> None:
    """The invariant both tests above are instances of, stated once."""
    for fixture, t in ((attested, INCIDENT_T), (clean_attested, CLEAN_T)):
        artifact, _ = fixture
        report = _report(artifact, t, CHAIN_KEYRING)
        layer_b = [item for item in report.solution if item.layer == query.LAYER_B]
        assert bool(report.assumption) == bool(layer_b)
        assert len(report.assumption) == len(layer_b)


def test_a_report_over_an_artifact_with_no_layer_b_edge_refuses_the_scene_clause(
    attested, tmp_path: Path
) -> None:
    """NEGATIVE, and the third state for the Layer B clause specifically.

    Strip the Layer B edges — leaving the record and its four Layer A edges
    intact — and the scene clause must say it cannot tell, not that nobody was
    there, while every attestation clause beside it still answers. That
    asymmetry is the claim; here it is as two verdicts in one report.

    Deleting the whole edge table would not test this: it would take the
    `DECLARED` edges with it and the report would refuse for a different reason.
    """
    artifact, _ = attested
    stripped = _copy(
        artifact, tmp_path / "no_edges.sqlite", "DELETE FROM edge WHERE layer = 'B'"
    )
    report = _report(stripped, INCIDENT_T, CHAIN_KEYRING)
    scene = report.clause(query.CLAUSE_SCENE)
    assert scene.verdict == COULD_NOT_EVALUATE
    assert report.scene == ()
    assert report.assumption == ()
    assert report.clause(query.CLAUSE_DECLARED).answered, (
        "the attestation clause is unaffected by the missing scene layer"
    )


# --- determinism and purity ------------------------------------------------


def test_the_incident_report_is_deterministic(attested) -> None:
    """Same artifact, same report. An audit artifact that answers differently on
    two reads is not an audit artifact."""
    artifact, _ = attested
    first = _report(artifact, INCIDENT_T, CHAIN_KEYRING)
    second = _report(artifact, INCIDENT_T, CHAIN_KEYRING)
    assert first == second
    assert query.render_incident(first) == query.render_incident(second)


def test_render_incident_is_pure_and_never_empty(attested) -> None:
    """The CLI formats and the query returns. `render_incident` reads no file, so
    a caller can format a report it did not fetch."""
    artifact, _ = attested
    report = _report(artifact, INCIDENT_T, CHAIN_KEYRING)
    text = query.render_incident(report)
    assert text.strip()
    assert query.render_incident(report) == text


def test_an_incident_report_refuses_a_non_finite_t(attested) -> None:
    """NEGATIVE. The only thing this query raises for is a caller error."""
    artifact, _ = attested
    with pytest.raises(QueryError, match="t_incident"):
        _report(artifact, float("nan"), CHAIN_KEYRING)


# --- the CLI ---------------------------------------------------------------


def test_the_cli_prints_the_incident_report(attested, capsys) -> None:
    artifact, keyring = attested
    code = query.main(
        [str(artifact), "--incident", str(INCIDENT_T), "--keyring", str(keyring)]
    )
    out = capsys.readouterr().out
    assert code == query.EXIT_OK
    assert "incident report:" in out
    assert "DECLARATION_ACTION_MISMATCH" in out
    assert "Chain verified" in out
    for field in query.GSN_FIELDS:
        assert f"{field}:" in out


def test_the_cli_exits_could_not_evaluate_without_a_keyring(attested, capsys) -> None:
    """Exit `1`, not `0`. A script that treated "could not check" as "checked and
    fine" is the failure mode the three-state discipline exists to prevent."""
    artifact, _ = attested
    code = query.main([str(artifact), "--incident", str(INCIDENT_T)])
    out = capsys.readouterr().out
    assert code == query.EXIT_COULD_NOT_EVALUATE
    assert COULD_NOT_EVALUATE in out


def test_the_cli_exits_broken_for_a_report_over_a_tampered_artifact(
    attested, tmp_path: Path, capsys
) -> None:
    """Exit `3`. A broken chain outranks everything else the report managed to
    say: the one thing a caller must not be able to do is read a report over an
    altered record as a clean pass."""
    artifact, keyring = attested
    tampered = chain.tamper(
        artifact, tmp_path / "cli_tampered.sqlite", "verdict:first:t=99.0"
    )
    code = query.main(
        [
            str(tampered.copy),
            "--incident",
            str(INCIDENT_T),
            "--keyring",
            str(keyring),
        ]
    )
    out = capsys.readouterr().out
    assert code == query.EXIT_BROKEN
    assert "INTEGRITY BROKEN" in out


def test_the_cli_reports_an_artifact_with_no_record_layer_rather_than_failing(
    artifact: Path, capsys
) -> None:
    """The verification command of issue #50 runs `--incident` against an
    artifact built without `--keyring`, which holds no attestation layer at all.
    That is a could-not-evaluate with a stated reason and exit `1` — not a
    crash, and emphatically not an empty report."""
    code = query.main([str(artifact), "--incident", "3.5"])
    out = capsys.readouterr().out
    assert code == query.EXIT_COULD_NOT_EVALUATE
    assert query.META_ATTESTATION_RECORDS in out
    assert out.strip()


@pytest.mark.parametrize(
    "argv_tail, match",
    [
        (["--incident", "not-a-number"], "not a number"),
        (["--incident", "3.5", "--tamper", "verdict:last:delete"], "--tamper"),
        (["--incident", "3.5", "--keyring", "no-such-keyring.json"], "keyring"),
    ],
)
def test_the_incident_cli_refuses_rather_than_ignores(
    attested, capsys, argv_tail: list[str], match: str
) -> None:
    """NEGATIVE. A flag silently dropped reads as one that was applied."""
    artifact, _ = attested
    code = query.main([str(artifact), *argv_tail])
    err = capsys.readouterr().err
    assert code == query.EXIT_USAGE
    assert match in err


@pytest.mark.parametrize(
    "argv_tail",
    [
        ["--declared-bound", str(INCIDENT_T)],
        ["--violations", "0", "5"],
    ],
)
def test_the_cli_answers_an_attestation_query(
    attested, capsys, argv_tail: list[str]
) -> None:
    artifact, _ = attested
    code = query.main([str(artifact), *argv_tail])
    out = capsys.readouterr().out
    assert code == query.EXIT_OK
    assert "verdict:    ANSWERED" in out
    assert f"layer:      {query.ATTESTATION_LAYER}" in out
    assert "evidence layer A" in out


def test_the_cli_answers_the_verdicts_query(attested, capsys) -> None:
    artifact, _ = attested
    declarations, _ = _records_of(artifact)
    code = query.main(
        [str(artifact), "--verdicts", declarations[0].declaration_id]
    )
    out = capsys.readouterr().out
    assert code == query.EXIT_OK
    assert declarations[0].declaration_id in out
    assert "adjudication(s)" in out


# --------------------------------------------------------------------------
# ENCODING IS NOT RETENTION (issue #54).
#
# Two changes in `reg.store` — a 1 KiB page size, and not creating the record
# tables for a build that was handed no record stream — that are supposed to
# alter how the artifact is written and nothing else. "Nothing else" is not a
# property of a diff; it is a property that has to be checked, and the check is
# equality: the same stream built under either encoding answers every supported
# question with the *same* `Answer`, not with one that agrees within tolerance.
#
# The capability the second change could plausibly have cost is the #48
# distinction, which #52's incident report depends on: "this build was given no
# record stream" and "a run that produced none" are different facts, and the
# tables are now absent in the first case. `meta[attestation_records]` still
# carries it, and the two tests at the end of this section are what say so.
# --------------------------------------------------------------------------


def _every_query(conn, *, declaration_id: str = "any-declaration-id") -> tuple:
    """Every supported question, asked with fixed arguments. One tuple.

    `query.QUERIES` is iterated rather than listed so a query added later is
    covered here without anybody remembering to add it — the arguments are
    keyed by name and a missing key is a `KeyError`, not a silently skipped
    query.

    `declaration_id` defaults to one no build produces, because the artifacts
    this is asked of hold no record layer and the refusal *is* the answer. An
    attested artifact refuses that id as a caller error before any query runs,
    so a caller with one passes a declaration the file actually holds.
    """
    arguments = {
        "separation_timeline": (graph.HUMAN_ENTITY_ID,),
        "first_envelope_intersection": (graph.HUMAN_ENTITY_ID,),
        "frames_at_risk": (graph.HUMAN_ENTITY_ID, THRESHOLD_M),
        "reachable_entities": (0.0, 5.0),
        "min_separation": (graph.HUMAN_ENTITY_ID,),
        "time_of_closest_approach": (graph.HUMAN_ENTITY_ID,),
        "did_contact_occur": (graph.HUMAN_ENTITY_ID,),
        # The base's own origin at the run's first instant, which every build
        # here retains a boundary for (`GEOMETRY_RETENTION` keeps both ends of
        # the run). Two coordinates and a time, so the answer is the same one
        # under either encoding or neither is.
        "reached_point": (0.0, 0.0, 0.0),
        "declared_bound": (1.0,),
        "violations": ((0.0, 5.0),),
        "verdicts": (declaration_id,),
        "acknowledgments": (),
    }
    return tuple(
        getattr(query, name)(conn, *arguments[name]) for name in query.QUERIES
    )


def _build_at(csv_path: Path, out: Path, *, page_size: int, always_create: bool):
    """Build `csv_path` under a named encoding. Returns the artifact path.

    `always_create=True` is the pre-#54 behaviour — the record tables created
    whether or not there is anything to put in them — reproduced by wrapping
    `store.create` rather than by keeping a second schema around, so what is
    compared is this build with one boolean flipped.
    """
    real_create = store.create
    real_page_size = store.PAGE_SIZE

    def create(path, *, record_tables):
        return real_create(path, record_tables=record_tables or always_create)

    store.PAGE_SIZE = page_size
    store.create = create
    try:
        graph.build(
            csv_path,
            out,
            scenario(SCENARIO).world.limits,
            # `bench.BENCH_IDENTITY`, not this file's, because the artifact this
            # one is compared against row-for-row is a `run_scenario` build.
            # The declared identity lands in `meta` and on every occurrence row
            # (issue #83), so two different ones would make these two artifacts
            # two different runs and the comparison would be about that rather
            # than about the encoding.
            identity=bench.BENCH_IDENTITY,
            # And `bench.BENCH_DISCLOSURES` beside it, for the same reason:
            # the three keys issue #125 added land in `meta`, so a different
            # set here would show up as a `meta` difference the encoding did
            # not cause.
            disclosures=bench.BENCH_DISCLOSURES,
            human_radius=scenario(SCENARIO).world.human_radius,
            horizon=_FAST["horizon"],
            n_samples=_FAST["n_samples"],
            seed=_FAST["envelope_seed"],
            substep_dt=_FAST["substep_dt"],
            occurrence_resolution_s=_FAST["occurrence_resolution_s"],
        )
    finally:
        store.create = real_create
        store.PAGE_SIZE = real_page_size
    return out


@pytest.fixture(scope="module")
def old_encoding(built, tmp_path_factory) -> Path:
    """The `artifact` fixture's stream, built the way it was built before #54."""
    csv_path, _ = built
    work = tmp_path_factory.mktemp("old-encoding")
    return _build_at(csv_path, work / "old.sqlite", page_size=4096, always_create=True)


def test_the_two_encodings_hold_the_same_rows(artifact: Path, old_encoding: Path) -> None:
    """Row for row, table for table — except the two the new one does not create.

    The strongest form of "no behavioural change" available without a second
    checkout: the same stream, the same seed, one boolean and one page size
    apart, and every row of every table identical.
    """
    new_conn = store.connect(artifact)
    old_conn = store.connect(old_encoding)
    try:
        assert store.has_record_tables(old_conn) is True
        assert store.has_record_tables(new_conn) is False

        tables = [
            table
            for table, _ in store.NODE_TABLES.values()
            if table not in store.RECORD_TABLE_NAMES
        ] + ["edge", "meta"]
        for table in tables:
            new_rows = [
                tuple(row) for row in new_conn.execute(f"SELECT * FROM {table}")
            ]
            old_rows = [
                tuple(row) for row in old_conn.execute(f"SELECT * FROM {table}")
            ]
            assert new_rows == old_rows, f"{table} differs between the encodings"

        # And the two tables the new encoding leaves out held nothing anyway,
        # which is the entire justification for leaving them out.
        for table in sorted(store.RECORD_TABLE_NAMES):
            assert (
                old_conn.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"]
                == 0
            )
    finally:
        new_conn.close()
        old_conn.close()


def test_every_query_answers_identically_under_either_encoding(
    artifact: Path, old_encoding: Path
) -> None:
    """Equality, not agreement within tolerance. All ten, refusals included.

    The three attestation queries refuse on both, and the refusals have to be
    the *same* refusal: a build with no record stream and no record tables must
    not start saying something new about why it cannot answer.
    """
    new_conn = store.connect(artifact)
    old_conn = store.connect(old_encoding)
    try:
        new_answers = _every_query(new_conn)
        old_answers = _every_query(old_conn)
    finally:
        new_conn.close()
        old_conn.close()

    assert len(new_answers) == len(query.QUERIES)
    for new, old in zip(new_answers, old_answers, strict=True):
        assert new == old, f"{new.query} changed with the encoding"
    assert any(answer.verdict == ANSWERED for answer in new_answers), (
        "every query refused, so this test compared ten refusals and nothing else"
    )
    assert any(answer.verdict == COULD_NOT_EVALUATE for answer in new_answers)


@pytest.fixture(scope="module")
def empty_record_stream(built, tmp_path_factory) -> Path:
    """A build handed a record stream that holds nothing.

    The other side of the distinction: `meta[attestation_records]` is `present`,
    the record tables exist, and they are empty because the run produced
    nothing — not because nobody was asked.
    """
    csv_path, _ = built
    out = tmp_path_factory.mktemp("empty-records") / "empty.sqlite"
    graph.build(
        csv_path,
        out,
        scenario(SCENARIO).world.limits,
        identity=TEST_IDENTITY,
        disclosures=TEST_DISCLOSURES,
        human_radius=scenario(SCENARIO).world.human_radius,
        records=graph.AttestationRecords(
            declarations=(), verdicts=(), acknowledgments=()
        ),
        horizon=_FAST["horizon"],
        n_samples=_FAST["n_samples"],
        seed=_FAST["envelope_seed"],
        substep_dt=_FAST["substep_dt"],
        occurrence_resolution_s=_FAST["occurrence_resolution_s"],
    )
    return out


def test_a_build_with_no_record_stream_creates_no_record_tables(
    artifact: Path, empty_record_stream: Path
) -> None:
    """The saving, asserted beside the fact it must not have cost.

    Two artifacts, both holding zero declarations and zero verdicts. One was
    offered a record stream and one was not, and that — not the presence of the
    tables — is what `meta[attestation_records]` says.
    """
    absent = store.connect(artifact)
    empty = store.connect(empty_record_stream)
    try:
        assert store.has_record_tables(absent) is False
        assert query.attestation_state(absent) != query.ATTESTATION_PRESENT

        assert store.has_record_tables(empty) is True
        assert query.attestation_state(empty) == query.ATTESTATION_PRESENT
        assert query.declaration_ids(empty) == ()
    finally:
        absent.close()
        empty.close()


def test_the_incident_report_still_tells_the_two_empty_runs_apart(
    artifact: Path, empty_record_stream: Path
) -> None:
    """NEGATIVE, and the one the saving had to survive (issues #48, #52, #54).

    Neither artifact can produce an incident report, and they must not fail to
    for the same reason. The build that was handed no record stream is refused
    on `meta[attestation_records]` and says so in as many words; the build that
    was handed an empty one holds a record layer and refuses because that layer
    states nothing in force at the instant asked about. If the second sentence
    ever becomes the first, the artifact has lost the ability to say which of
    the two happened, and no number of saved bytes is worth that.
    """
    no_stream = _ask(artifact, query.incident_report, 3.5, None)
    produced_none = _ask(empty_record_stream, query.incident_report, 3.5, None)

    assert no_stream.verdict == COULD_NOT_EVALUATE
    assert produced_none.verdict == COULD_NOT_EVALUATE

    assert query.META_ATTESTATION_RECORDS in no_stream.reason
    assert "no record stream" in no_stream.reason
    assert query.META_ATTESTATION_RECORDS not in produced_none.reason
    assert no_stream.reason != produced_none.reason

    # The chain clause tells them apart too, and it is the clause an assessor
    # reads first when it did not verify.
    could_not = chain.ChainState.COULD_NOT_EVALUATE.value
    assert no_stream.integrity == produced_none.integrity == could_not
    absent_text = "\n".join(c.text for c in no_stream.clauses)
    empty_text = "\n".join(c.text for c in produced_none.clauses)
    assert "no record stream" in absent_text
    assert "no record stream" not in empty_text


# --------------------------------------------------------------------------
# THE SURROGATE KEYS (issue #55), from the query side.
#
# `node_key` is storage. Two properties have to hold for that sentence to be
# true, and neither is provable by the answers alone: the numbering must not
# reach any answer, and no answer may cite a surrogate where it used to cite an
# identifier.
# --------------------------------------------------------------------------

#: Every column in the schema that holds a `node.node_key`. Listed rather than
#: derived, because the point of the test below is to renumber **all** of them:
#: a derivation that missed one would renumber a consistent artifact into a
#: consistent artifact and prove nothing.
_KEY_COLUMNS: dict[str, tuple[str, ...]] = {
    "node": ("node_key",),
    "robot_config": ("config_key",),
    "envelope": ("envelope_key", "config_key"),
    "entity": ("entity_key",),
    "occurrence": ("occurrence_key", "entity_key"),
    "edge": ("src_key", "dst_key"),
    "declaration": ("declaration_key",),
    "verdict": ("verdict_key", "declaration_key"),
}

#: Far above any key a build allocates, so the shift collides with nothing.
_RENUMBER_BY = 1_000_000


def _renumber(source: Path, target: Path, *tables: str) -> Path:
    """A copy of `source` with the surrogate keys of `tables` shifted.

    Given every table, the artifact is renumbered and stays consistent — the
    same nodes with different integers on them. Given a subset, it is
    *inconsistent*, which is how the negative below feeds this check the
    condition it guards against.
    """
    import shutil

    shutil.copyfile(source, target)
    conn = store.connect(target)
    try:
        for table in tables:
            for column in _KEY_COLUMNS[table]:
                conn.execute(
                    f"UPDATE {table} SET {column} = {column} + ?"  # noqa: S608
                    f" WHERE {column} IS NOT NULL",
                    (_RENUMBER_BY,),
                )
        conn.commit()
    finally:
        conn.close()
    return target


def test_renumbering_the_surrogate_keys_changes_no_answer(
    attested, tmp_path: Path
) -> None:
    """**Equality, not agreement within tolerance.** Every query, both layers.

    The strongest available statement that `node_key` is an encoding detail: the
    same artifact with every surrogate shifted by a million answers every
    supported question with the identical value, refusals and reasons included,
    and produces the identical incident report. If any join, index or answer had
    come to depend on the numbering — or if a `node_key` had leaked into a field
    that used to carry an identifier — the two would differ.

    It compares the artifact against itself rather than against a recorded
    answer set, which is what keeps it a statement about the *encoding*: a
    golden would also fail on a shapely upgrade that moved a polygon by a
    nanometre, and would then report that as an encoding regression.
    """
    artifact, _ = attested
    renumbered = _renumber(
        artifact, tmp_path / "renumbered.sqlite", *_KEY_COLUMNS
    )

    conn = store.connect(renumbered)
    try:
        moved = conn.execute(
            "SELECT min(node_key) AS lo FROM node"
        ).fetchone()["lo"]
    finally:
        conn.close()
    assert moved >= _RENUMBER_BY, "precondition failed: nothing was renumbered"

    before = _every_query_on(artifact)
    after = _every_query_on(renumbered)
    assert len(before) == len(query.QUERIES)
    for old, new in zip(before, after, strict=True):
        assert old == new, f"{old.query} changed when the surrogates were renumbered"
    assert any(a.verdict == ANSWERED for a in before), (
        "every query refused, so this compared refusals and nothing else"
    )

    assert _report(artifact, INCIDENT_T, CHAIN_KEYRING) == _report(
        renumbered, INCIDENT_T, CHAIN_KEYRING
    )


def test_a_half_renumbered_artifact_is_refused_rather_than_answered(
    attested, tmp_path: Path
) -> None:
    """THE NEGATIVE for the test above. It has to be able to fail.

    Shifting the `edge` endpoints and nothing else leaves every edge pointing at
    a node that is not there. The scene queries must **refuse** — the artifact
    holds rows it cannot resolve, which is a could-not-evaluate — and must not
    quietly answer from an edge layer whose endpoints resolve to nothing.
    """
    artifact, _ = attested
    broken = _renumber(artifact, tmp_path / "half.sqlite", "edge")

    answer = _ask(broken, query.separation_timeline, graph.HUMAN_ENTITY_ID)
    assert answer.verdict == COULD_NOT_EVALUATE
    assert answer.value is None

    intact = _ask(artifact, query.separation_timeline, graph.HUMAN_ENTITY_ID)
    assert intact.verdict == ANSWERED, (
        "precondition failed: the intact artifact does not answer either, so "
        "the refusal above is not evidence of anything"
    )


def _every_attested_query(conn) -> tuple:
    """`_every_query`, with a `declaration_id` this artifact actually holds.

    `_every_query`'s fixed id is deliberately one no build produces — it is
    asked of an artifact with no record layer, where the refusal is the answer.
    On an attested artifact that same id is a `QueryError` before any query
    runs, so query 7 is asked about a real declaration here and the attestation
    half of the comparison is a comparison of answers rather than of raisers.
    """
    return _every_query(conn, declaration_id=query.declaration_ids(conn)[0])


def _every_query_on(path: Path) -> tuple:
    conn = store.connect(path)
    try:
        return _every_attested_query(conn)
    finally:
        conn.close()


def test_no_answer_cites_a_surrogate_key(attested) -> None:
    """Issue #52's output, after issue #55: readable identifiers, never integers.

    `declared_violation-verdict-00150` is what an assessor reads and what
    `docs/` quotes. Every id-shaped field of every answer and of the incident
    report is checked against the artifact's own `node` table, so a field that
    started returning `147` fails here rather than in somebody's PDF — and a
    field returning an id the artifact does not hold fails too, which is the
    other way a resolved join can go wrong.
    """
    import dataclasses

    artifact, _ = attested
    conn = store.connect(artifact)
    try:
        known = {
            str(row["node_id"])
            for row in conn.execute("SELECT node_id FROM node")
        }
        answers = _every_attested_query(conn)
        report = query.incident_report(conn, INCIDENT_T, CHAIN_KEYRING)
    finally:
        conn.close()
    assert known, "precondition failed: the artifact declares no nodes"

    def id_fields(value, seen: list[tuple[str, object]]) -> None:
        if dataclasses.is_dataclass(value) and not isinstance(value, type):
            for f in dataclasses.fields(value):
                item = getattr(value, f.name)
                if f.name.endswith("_id") or f.name.endswith("_ids"):
                    seen.append((f.name, item))
                else:
                    id_fields(item, seen)
        elif isinstance(value, (list, tuple)):
            for item in value:
                id_fields(item, seen)

    found: list[tuple[str, object]] = []
    for answer in answers:
        id_fields(answer.value, found)
    id_fields(report, found)
    for item in report.solution:
        found.append(("ref", item.ref))

    assert found, "precondition failed: no answer carried an identifier at all"
    cited = 0
    for name, value in found:
        for one in value if isinstance(value, (list, tuple)) else (value,):
            if one is None:
                continue
            assert isinstance(one, str), f"{name} came back as {one!r}, not an id"
            assert not one.isdigit(), f"{name} is {one!r}, which is a surrogate"
            # `ref` carries prose alongside ids in some clauses, so it is only
            # required to *contain* one the artifact holds; the `*_id` fields
            # must be one exactly.
            if name == "ref":
                continue
            assert one in known, (
                f"{name} is {one!r}, which is not a node this artifact holds"
            )
            cited += 1
    assert cited, "no answer cited an identifier, so nothing above was checked"


# ==========================================================================
# THE STANDARD QUESTIONS, PUT TO A MOBILE ARTIFACT (issue #178, §7 Tier 4)
#
# Everything above asks a bolted arm. `mobile_transit` is the first fixture in
# this repository whose base drives, and the acceptance criterion of that tier
# is that an artifact built from one can be *read back and queried* — which is
# a claim about this module, not about the builder.
#
# The claim the fixture itself exists for is the one docs/sufficiency.md §5.6
# makes: *can the robot reach this configuration* is Layer A and unchanged by a
# drive, and *can the robot reach this room coordinate* is Layer B and has two
# different answers in one run. `reachable_entities` is exactly that question,
# and asked over the first second and over the last it must give exactly those
# two answers.
#
# The second test here is the one that could rot quietly. Every distance in a
# mobile artifact is measured from where the base was, and a builder that
# placed the envelope but left the *body* at the origin would produce a file
# that parses, answers every question, and is wrong about all of them. So the
# separation answers are checked against a recomputation from the raw stream
# that places the body at each frame's pose — and against one that does not,
# which must disagree.
# ==========================================================================

#: `mobile_transit` at the builder's own horizon rather than `_FAST`'s 0.05.
#: The room-frame claim is about the arm's *forward reachable set*, and at a
#: 50 ms horizon that set is barely larger than the arm — the human is never in
#: it, and `reachable_entities` would answer the empty set at both ends of the
#: run for a reason that is about the parameter and not about the drive.
_MOBILE_FAST = {
    "horizon": 0.2,
    "n_samples": 4,
    "envelope_seed": 0,
    "substep_dt": 0.05,
    "occurrence_resolution_s": graph.OCCURRENCE_TIME_RESOLUTION_S,
}

#: The scene questions every artifact must be able to answer. The record-layer
#: queries (`declared_bound`, `violations`, `verdicts`) are deliberately not
#: here: this build is handed no record stream, so their could-not-evaluate is
#: the honest answer and asserting `ANSWERED` for them would be asserting a bug.
MOBILE_SCENE_QUERIES = (
    "separation_timeline",
    "min_separation",
    "time_of_closest_approach",
    "did_contact_occur",
    "frames_at_risk",
    "first_envelope_intersection",
    "reachable_entities",
)


@pytest.fixture(scope="module")
def mobile_built(tmp_path_factory) -> tuple[Path, Path]:
    """One real build of `mobile_transit`: `(csv, sqlite)`.

    Not through `bench.run_scenario`, which is the benchmark harness and would
    price a run this repository does not price (docs/mobile-base.md §7:
    **Claim 1 stays a fixed-arm claim**). The producer and the builder are the
    same two calls that harness makes; what is skipped is the measurement.
    """
    from reg.sim import simulate

    work = tmp_path_factory.mktemp("mobile-query")
    scn = scenario("mobile_transit")
    csv, out = work / "mobile.csv", work / "mobile.sqlite"
    simulate(scn.name, 0, csv)
    graph.build(
        csv,
        out,
        scn.world.limits,
        identity=TEST_IDENTITY,
        disclosures=TEST_DISCLOSURES,
        human_radius=scn.world.human_radius,
        horizon=_MOBILE_FAST["horizon"],
        n_samples=_MOBILE_FAST["n_samples"],
        seed=_MOBILE_FAST["envelope_seed"],
        substep_dt=_MOBILE_FAST["substep_dt"],
        occurrence_resolution_s=_MOBILE_FAST["occurrence_resolution_s"],
    )
    return csv, out


@pytest.mark.parametrize("name", MOBILE_SCENE_QUERIES)
def test_every_scene_question_is_answered_by_a_mobile_artifact(
    mobile_built, name: str
) -> None:
    """The acceptance criterion: the standard questions, against a run that drove.

    `ANSWERED` and not merely "did not raise". A could-not-evaluate here would
    be the honest report of a file that cannot answer, and that is exactly the
    outcome this tier has to rule out — an artifact of a mobile run that parses
    and answers nothing is the failure docs/mobile-base.md §7 says
    `GEOMETRY_RETENTION`'s posed clause exists to prevent.
    """
    arguments = {
        "separation_timeline": (graph.HUMAN_ENTITY_ID,),
        "min_separation": (graph.HUMAN_ENTITY_ID,),
        "time_of_closest_approach": (graph.HUMAN_ENTITY_ID,),
        "did_contact_occur": (graph.HUMAN_ENTITY_ID,),
        "frames_at_risk": (graph.HUMAN_ENTITY_ID, THRESHOLD_M),
        "first_envelope_intersection": (graph.HUMAN_ENTITY_ID,),
        "reachable_entities": (0.0, 5.0),
    }
    answer = _ask(mobile_built[1], getattr(query, name), *arguments[name])
    assert answer.verdict == ANSWERED, f"{name}: {answer.reason}"
    assert answer.value is not None


def test_the_room_frame_answer_changes_because_the_base_drove(mobile_built) -> None:
    """**The claim `mobile_transit` exists for, asked of the artifact**
    (docs/sufficiency.md §5.6).

    One person, standing still for the whole run. Over the first second the
    reachable set names nobody; over the last it names them. The arm is not the
    difference — it is folded for the transit and presented on arrival, and both
    configurations are ones the robot could adopt anywhere — the difference is a
    room-frame pose the robot did not measure.

    Both halves are asserted, and the first is the one that makes the second
    mean anything: a query that named the human over every window would satisfy
    the second on its own.
    """
    artifact = mobile_built[1]
    early = _ask(artifact, query.reachable_entities, 0.0, 1.0)
    late = _ask(artifact, query.reachable_entities, 4.0, 5.0)

    assert early.verdict == ANSWERED and late.verdict == ANSWERED
    assert graph.HUMAN_ENTITY_ID in early.value.declared, (
        "the human is not even declared in this artifact, so an empty early "
        "answer would mean the entity is missing rather than out of reach"
    )
    assert early.value.entity_ids == (), (
        f"the human is reachable over the first second ({early.value.entity_ids}); "
        "this run is supposed to start from a pose that could not reach them"
    )
    assert graph.HUMAN_ENTITY_ID in late.value.entity_ids, (
        f"the human is not reachable over the last second ({late.value.entity_ids}); "
        "the drive did not change the answer and the fixture claims nothing"
    )

    first = _ask(artifact, query.first_envelope_intersection, graph.HUMAN_ENTITY_ID)
    assert first.verdict == ANSWERED
    assert first.value.t_first is not None and first.value.t_first > 1.0, (
        "the envelope meets the human before the transit is under way"
    )


def _separation_from_csv(
    csv_path: Path, limits, human_radius: float, *, posed: bool
) -> list[tuple[float, float]]:
    """The body-to-human distance per frame, recomputed from the raw stream.

    `posed=True` places the body at each frame's own base pose, which is what a
    room-frame separation *is* for a robot that drove; `posed=False` leaves it
    at the origin, which is what the same code says for a bolted arm. The second
    is here to be the negative: it is the timeline a builder that forgot the
    pose would produce, and the check below is only a check if it can tell the
    two apart.

    Deliberately not `bench.ground_truth_from_csv` — that function places every
    body at `ORIGIN_FRAME`, which is correct for the eleven and is the *wrong*
    of these two answers here.

    **The whole timeline rather than its minimum**, and that is not a
    generalization for its own sake: over this fixture the two minima happen to
    fall within a centimetre of each other — the arm at full stretch from the
    origin very nearly reaches a person the driven robot reaches comfortably —
    so a check on the minimum alone would be one coincidence away from passing
    for a builder that had dropped the pose entirely.
    """
    import numpy as np
    from shapely.geometry import Point
    from shapely.ops import unary_union

    from reg.kinematics import ORIGIN_FRAME, BaseFrame, link_polygons
    from reg.stream import read_frames

    out: list[tuple[float, float]] = []
    for frame in read_frames(csv_path):
        base = ORIGIN_FRAME
        if posed:
            pose = frame.base_pose
            base = BaseFrame(x=pose.x, y=pose.y, theta=pose.theta)
        body = unary_union(link_polygons(np.asarray(frame.q, dtype=float), limits, base))
        human = Point(*(float(v) for v in frame.human_pos)).buffer(human_radius)
        out.append((float(frame.t), float(body.distance(human))))
    assert out, f"{csv_path} yielded no frames"
    return out


def test_the_separation_a_mobile_artifact_reports_is_measured_from_where_it_drove(
    mobile_built,
) -> None:
    """**The half that would rot quietly**, and its negative in one test.

    The separation timeline in a mobile artifact must agree, frame for frame,
    with a recomputation that places the robot's body at the pose each frame
    recorded — and must *disagree* with the same recomputation at the origin.
    Without the second half this is a check that cannot fail in the direction
    that matters: an artifact whose separations were all measured for a robot at
    (0, 0) would still answer every question in this module, and every answer
    would be about a robot that was somewhere else.
    """
    csv, artifact = mobile_built
    scn = scenario("mobile_transit")
    answer = _ask(artifact, query.separation_timeline, graph.HUMAN_ENTITY_ID)
    assert answer.verdict == ANSWERED, answer.reason

    reported = {round(t, 6): d for t, d in answer.value.samples}
    at_the_pose = _separation_from_csv(
        csv, scn.world.limits, scn.world.human_radius, posed=True
    )
    at_the_origin = _separation_from_csv(
        csv, scn.world.limits, scn.world.human_radius, posed=False
    )
    assert len(reported) == len(at_the_pose), (
        f"the artifact answers {len(reported)} frames and the stream has "
        f"{len(at_the_pose)}"
    )

    for t, truth in at_the_pose:
        got = reported[round(t, 6)]
        assert abs(got - truth) <= DISTANCE_TOL_M, (
            f"t={t}: the artifact reports {got} m and the stream says "
            f"{truth:.4f} m from where the base actually was"
        )

    disagreements = [
        t
        for t, wrong in at_the_origin
        if abs(reported[round(t, 6)] - wrong) > DISTANCE_TOL_M
    ]
    assert len(disagreements) > len(at_the_origin) // 2, (
        f"the artifact agrees with a body left at the origin on all but "
        f"{len(disagreements)} of {len(at_the_origin)} frames, which is what a "
        "builder that dropped the base pose would produce"
    )


# --------------------------------------------------------------------------
# THE COLD READ (issue #231, docs/self-describing.md §2 and §8 tier 3).
#
# `cold_read` reports what an artifact says about itself with no document open.
# The tests below do three things and nothing else is support:
#
# 1. **They pin what it must say today**, per claim and per shipped fixture. A
#    gap closing elsewhere makes one of these expectations wrong, and it has to
#    be changed on purpose rather than drift.
# 2. **They feed it the conditions it reports on.** An environment stripped out,
#    an environment blanked, a schema older than the states were derived
#    against, a `layer` column left intact, an artifact with no chain in it at
#    all, and a record whose MAC has been blanked. Most of those must come back
#    something other than CHECKABLE, and the intact ones must come back in the
#    state their evidence actually supports rather than CHECKABLE — a report
#    whose only exercised path is the healthy one has not been shown able to
#    say no.
# 3. **They hold it to `reg.graph` and to `reg.chain`.** `reg.query` cannot
#    import either, so the recompute keys and the record chains are copies, and
#    a copy that nothing compares is a second definition waiting to drift.
#    Three tests compare them: one on the key list, one on the behaviour in both
#    directions, and one on the chains `reg.chain` walks.
#
# THE FIFTH STATE (issue #242). `chain-intact` arrived with a state of its own,
# and the test that used to refuse a fifth now refuses a **sixth**. That was the
# deliberate act the refusal exists to force: none of the four fitted a claim
# that is checkable by a key-holder and by nobody else, and flattening it into a
# neighbour would have reported the design as a defect or the defect as a
# design.
# --------------------------------------------------------------------------

#: What the cold read must say today, per claim, on an artifact built from
#: `main` — the table in issue #231. Pinned here so that closing a gap **fails
#: this file** and has to be updated deliberately.
#:
#: **`layer-tag-basis` moved to CHECKABLE at schema 13** (issue #252), and it is
#: the first of the four rows to move since the report shipped. It moved because
#: `edge_layer_basis` puts the basis in the file and `reg.store.open_edge`
#: refuses a tag that disagrees with it, so a reader recomputes the tag from the
#: rows rather than trusting it. Editing this line was the deliberate act the
#: pin exists to force.
#:
#: **`reached-point` moved to CHECKABLE with issue #258**, and it is the second
#: — the last of the four to leave READABLE-NOT-CHECKABLE, so no row in this
#: table is in that state any more. #257 put the outer boundary in the file and
#: made the region readable; #258 added `reg.query.reached_point`, which tests a
#: point against it, and the cold read now runs that query in both directions
#: rather than reporting a state about a check nobody invoked. The gap that
#: remains is **coverage** and not checkability: 12 frames of 3,000 on the
#: published run, capped by `ENVELOPE_RETENTION` rather than by this row, and
#: the answer states its own coverage so that a refusal elsewhere cannot be read
#: as a *no*. This line was edited by the change that closed it, which is the
#: sequence the pin exists to force.
COLD_READ_TODAY = {
    query.CLAIM_ENVIRONMENT: query.CHECKABLE,
    query.CLAIM_RECOMPUTE: query.CHECKABLE,
    query.CLAIM_LAYER_BASIS: query.CHECKABLE,
    query.CLAIM_REACHED_POINT: query.CHECKABLE,
    query.CLAIM_CHAIN_INTACT: query.ABSENT,
    query.CLAIM_ACKNOWLEDGMENT: query.ABSENT,
}

#: The same four rows, on a build that **was** handed a record stream — plus
#: Claim 4's two, which are the whole point of issue #242. `chain-intact` is the
#: fifth state: the records are there, every one of them carries its link and
#: its MAC, and what a reader needs beyond the file is a key. `passivation-
#: acknowledged` is CHECKABLE from the file alone, and it is the first row in
#: this report to become checkable by *evidence being added* (issue #247) rather
#: than by provenance being recorded.
#:
#: Two tables and not one, because the first four states are a property of the
#: schema and these two are a property of **what this build was handed**. A
#: single table would have had to pick one, and the pick would have hidden the
#: other fixture's row.
COLD_READ_ATTESTED = {
    **COLD_READ_TODAY,
    query.CLAIM_CHAIN_INTACT: query.CHECKABLE_WITH_A_KEY,
    query.CLAIM_ACKNOWLEDGMENT: query.CHECKABLE,
}

#: The same, for a view with no edge layer and no envelopes. `materialize_level`
#: at the occurrence resolution keeps the environment and drops the rows the
#: other two claims are about, so those two are **ABSENT** — the file makes no
#: claim rather than making one it cannot support. Listed because a report that
#: could only produce one shape of answer would not be reporting anything.
COLD_READ_OCCURRENCE_VIEW = {
    query.CLAIM_ENVIRONMENT: query.CHECKABLE,
    query.CLAIM_RECOMPUTE: query.CHECKABLE,
    query.CLAIM_LAYER_BASIS: query.ABSENT,
    query.CLAIM_REACHED_POINT: query.ABSENT,
    query.CLAIM_CHAIN_INTACT: query.ABSENT,
    query.CLAIM_ACKNOWLEDGMENT: query.ABSENT,
}

#: Names of the cold read's implementation, for the structural check that it
#: opens nothing. `cold_read`'s promise is *no document*, and the cheapest thing
#: that can fail is the source: a function that never names a filesystem call
#: cannot make one.
COLD_READ_FUNCTIONS = (
    "cold_read",
    "render_cold_read",
    "_schema_version_text",
    "_unpinned_claims",
    "_environment_claim",
    "_running_environment",
    "_recompute_claim",
    "_layer_basis_claim",
    "_reached_point_claim",
    "_chain_intact_claim",
    "_acknowledgment_claim",
    # Reached by `_reached_point_claim`, which answers by *running* the query in
    # both directions (issue #258) rather than asserting a state about a check
    # nobody invoked — the same rule `_acknowledgment_claim` follows, and here
    # too the promise is about what the cold read reaches rather than which
    # functions it is spelled in.
    "reached_point",
    "pointwise_coverage",
    "_has_outer_boundary_column",
    "_coverage_text",
    "available_layers",
    "_layer_for",
    "_no_layer",
    "_refuse",
    "_finite",
    # Reached by `_acknowledgment_claim`, which answers by running the query
    # rather than re-deriving the passivation walk (issue #242). Listed because
    # the promise is about what the cold read *reaches*, not about which
    # functions it is spelled in — a callee that opened a second file would
    # break the promise just as thoroughly.
    "acknowledgments",
    "attestation_state",
    "_no_record_layer",
    "_refuse_record",
    "_acknowledgment_rows",
    "_verdict_rows",
    "_passivation",
    "_acknowledged",
)

#: Names that would mean the cold read read something other than the artifact it
#: was handed. `Path` is here with the others: the artifact arrives as an open
#: connection, so a path constructed inside these functions is a second file.
FILESYSTEM_NAMES = ("open", "read_text", "read_bytes", "Path", "glob", "listdir")


def _cold_read(path: Path) -> query.ColdRead:
    """Open `path`, cold-read it, close. The same shape as `_ask`."""
    conn = store.connect(path)
    try:
        return query.cold_read(conn)
    finally:
        conn.close()


def _raw_cold_read(path: Path) -> query.ColdRead:
    """Cold-read a file `store.connect` would refuse.

    `store.connect` rejects any `schema_version` this build does not understand,
    so the older-schema arm is unreachable through it. An assessor holding an
    archived artifact meets that arm through whatever sqlite3 they have, which
    is what this is.
    """
    import sqlite3 as _sqlite3

    conn = _sqlite3.connect(path)
    conn.row_factory = _sqlite3.Row
    try:
        return query.cold_read(conn)
    finally:
        conn.close()


def _named_calls(source: str, function_names: tuple[str, ...]) -> set[str]:
    """Every name called or attribute reached inside the named functions.

    Factored out so the check below can be fed the condition it guards against.
    A checker only ever run against a clean file has not been shown able to say
    no at all.
    """
    tree = ast.parse(source)
    wanted = {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name in function_names
    }
    found: set[str] = set()
    for node in wanted.values():
        for inner in ast.walk(node):
            if isinstance(inner, ast.Name):
                found.add(inner.id)
            elif isinstance(inner, ast.Attribute):
                found.add(inner.attr)
    return found


# --------------------------------------------------------------------------
# What it must say today. One row per claim, per shipped fixture.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fixture, index, expected",
    [
        ("built", 1, COLD_READ_TODAY),
        ("attested", 0, COLD_READ_ATTESTED),
        ("clean_attested", 0, COLD_READ_ATTESTED),
        ("mobile_built", 1, COLD_READ_TODAY),
        ("occurrence_view", None, COLD_READ_OCCURRENCE_VIEW),
    ],
)
def test_the_cold_read_says_the_same_things_about_every_shipped_fixture(
    request, fixture: str, index: int | None, expected: dict[str, str]
) -> None:
    """THE PINNED TABLE. Every row, per artifact this file builds.

    Every fixture here is a different run — one fixed-arm scenario with no
    records, two with both record chains, one whose base drives, and one view at
    the occurrence resolution. **The first four states do not depend on the
    run**, and that is the finding: what a file supports there is a property of
    the schema, so an assessor meets the same rows whatever they were handed —
    including on the run whose base drove and whose every base rate came out of
    a perceiver.

    Claim 4's two rows are the exception and it is not a weakening (issue #242):
    whether a file holds a signed record is a property of *the build*, not of
    the schema, so `built` reports ABSENT and `attested` reports the fifth
    state. A single expectation covering both would have had to call one of them
    wrong.

    **Closing a gap breaks this test**, which is the point of pinning it. Issue
    #252 put the basis in the file and `layer-tag-basis` moved to CHECKABLE;
    this expectation was edited by the change that closed it, which is the
    sequence the pin exists to force. `reached-point` is #228's and is still
    READABLE-NOT-CHECKABLE.
    """
    value = request.getfixturevalue(fixture)
    artifact = value if index is None else value[index]
    report = _cold_read(artifact)

    assert report.schema_version == str(store.SCHEMA_VERSION)
    got = {row.claim: row.state for row in report.claims}
    assert got == expected, (
        f"{fixture} cold-reads as {got} and the pinned table says {expected}. "
        "If a gap closed, edit the table; if it did not, this is a regression "
        "in what the file supports."
    )
    for row in report.claims:
        assert row.claim in row.message and row.state in row.message, (
            f"{row.claim}'s message does not name both the claim and the state: "
            f"{row.message!r}"
        )
        assert row.detail.strip(), f"{row.claim} carries no detail"


def test_the_last_four_states_are_not_a_pass(attested: tuple[Path, Path]) -> None:
    """Only `CHECKABLE` is a pass, and the other four are not degrees of it.

    The states are strings and `checkable` is the only predicate over them, so
    this is the test that keeps the vocabulary from collapsing into a boolean
    somewhere downstream. Run on `attested` since issue #242, because that is
    the fixture whose report carries the fifth state — the one a reader is most
    likely to mistake for a pass, being the one that says *checkable* in its own
    name.
    """
    report = _cold_read(attested[0])
    assert set(query.COLD_READ_STATES) == {
        query.CHECKABLE,
        query.CHECKABLE_WITH_A_KEY,
        query.READABLE_NOT_CHECKABLE,
        query.ABSENT,
        COULD_NOT_EVALUATE,
    }
    for row in report.claims:
        assert row.checkable == (row.state == query.CHECKABLE), (
            f"{row.claim} is {row.state} and reports checkable={row.checkable}"
        )
    assert set(report.checkable) | set(report.not_checkable) == set(
        query.COLD_READ_CLAIMS
    )
    assert not set(report.checkable) & set(report.not_checkable)
    assert query.CLAIM_LAYER_BASIS in report.checkable
    assert query.CLAIM_ACKNOWLEDGMENT in report.checkable
    assert query.CLAIM_REACHED_POINT in report.checkable, (
        "issue #258 moved this row: the boundary was already readable and the "
        "query that tests a point against it now exists, so the report runs it"
    )
    assert query.CLAIM_CHAIN_INTACT in report.not_checkable, (
        "the chain row is checkable with a key and not from the file, so it "
        "belongs in `not_checkable` — a report that promoted it would tell an "
        "assessor the file settles tamper-evidence on its own"
    )


def test_the_cold_read_is_pinned_to_this_build_s_schema() -> None:
    """The deliberate-update gate, and the whole reason the pin is a constant.

    Every state above is a property of a particular set of columns and `meta`
    keys. #227 put a basis table in the file and #228 will put a boundary in it;
    either one bumps `store.SCHEMA_VERSION`, and this fails the moment it moves
    — before an assessor is handed a report still calling a closed gap
    *readable, not checkable*. It is what made issue #252 re-derive all four
    states against schema 13 rather than only the one it was about.
    """
    assert query.COLD_READ_SCHEMA_VERSION == store.SCHEMA_VERSION, (
        f"reg.query.COLD_READ_SCHEMA_VERSION is "
        f"{query.COLD_READ_SCHEMA_VERSION} and the schema is now "
        f"{store.SCHEMA_VERSION}. Re-derive every state in COLD_READ_TODAY "
        "against the new columns, update the table and then move the constant. "
        "Moving the constant alone is how a closed gap goes on being reported "
        "as an open one."
    )


def test_the_cold_read_opens_nothing() -> None:
    """*No document*, enforced against the source rather than promised.

    `cold_read`'s claim is that it reads the artifact it was handed and nothing
    else. Its argument is an open connection, so anything that opened a second
    file would have to name one of `FILESYSTEM_NAMES` to do it.
    """
    reached = _named_calls(Path(query.__file__).read_text(), COLD_READ_FUNCTIONS)
    offenders = sorted(reached & set(FILESYSTEM_NAMES))
    assert not offenders, (
        f"the cold read's implementation names {offenders}. It answers from the "
        "artifact it was handed; a second file is a document, and 'no document' "
        "is the acceptance criterion it exists to meet."
    )


def test_the_no_document_check_can_say_no() -> None:
    """THE NEGATIVE for the check above. Feed it a function that opens a file."""
    offending = "def cold_read(conn):\n    return open('docs/plan.md').read()\n"
    assert "open" in _named_calls(offending, ("cold_read",))
    clean = "def cold_read(conn):\n    return conn.execute('SELECT 1')\n"
    assert not _named_calls(clean, ("cold_read",)) & set(FILESYSTEM_NAMES)


# --------------------------------------------------------------------------
# The negatives. Each feeds the report the condition it reports on.
# --------------------------------------------------------------------------


def test_a_stripped_environment_is_absent_and_not_checkable(
    artifact: Path, tmp_path: Path
) -> None:
    """THE FIRST NEGATIVE (issue #231). No `env_*` keys — **ABSENT**.

    Not CHECKABLE, obviously; and not COULD-NOT-EVALUATE either, which is the
    part worth a test. The file states the schema those keys arrived in, so it
    had somewhere to put them and did not — an absence somebody's build chose,
    which is a different fact from an archive written before the keys existed.
    """
    stripped = _copy(
        artifact,
        tmp_path / "no-environment.sqlite",
        "DELETE FROM meta WHERE key LIKE 'env\\_%' ESCAPE '\\'",
    )
    report = _cold_read(stripped)
    assert report.state(query.CLAIM_ENVIRONMENT) == query.ABSENT
    assert report.state(query.CLAIM_RECOMPUTE) == query.READABLE_NOT_CHECKABLE
    assert report.recompute_permitted is None, (
        "nothing was compared, so 'permitted' is neither True nor False — a "
        "False here would report a machine mismatch for a file that never said "
        "which machine it was built on"
    )
    detail = report[query.CLAIM_ENVIRONMENT].detail
    for key in store.ENVIRONMENT_KEYS:
        assert key in detail, f"the refusal does not name {key}"


def test_a_blank_environment_key_is_absent_and_not_a_mismatch(
    artifact: Path, tmp_path: Path
) -> None:
    """An environment is six keys or it is none.

    A file carrying `env_platform_machine=''` compares unequal to every
    recomputing interpreter, so a report that took the block at face value would
    say *built on another machine* about a file that said nothing. It is ABSENT,
    the same as no block at all, and the detail names the key.
    """
    blanked = _copy(
        artifact,
        tmp_path / "blank-machine.sqlite",
        f"UPDATE meta SET value = '' WHERE key = '{store.META_ENV_PLATFORM_MACHINE}'",
    )
    report = _cold_read(blanked)
    assert report.state(query.CLAIM_ENVIRONMENT) == query.ABSENT
    assert store.META_ENV_PLATFORM_MACHINE in report[query.CLAIM_ENVIRONMENT].detail
    assert report.recompute_permitted is None


def test_a_schema_older_than_the_states_is_could_not_evaluate_and_not_absent(
    artifact: Path, tmp_path: Path
) -> None:
    """THE SECOND NEGATIVE (issue #231). `schema_version` 10 — **all four
    COULD-NOT-EVALUATE**, and not one of them ABSENT.

    An artifact written before issue #200 has no environment, and reporting that
    as an absence would be a finding about a file that was written against a
    schema with nowhere to put one. The other three rows go the same way for the
    same reason and it is stated rather than assumed: every state this report
    gives is about a particular set of columns, and against another set they are
    states about columns this reader cannot place.
    """
    older = _copy(
        artifact,
        tmp_path / "schema-10.sqlite",
        "DELETE FROM meta WHERE key LIKE 'env\\_%' ESCAPE '\\'",
        f"UPDATE meta SET value = '10' WHERE key = '{store.META_SCHEMA_VERSION}'",
    )
    with pytest.raises(store.StoreError):
        store.connect(older)  # the reason `_raw_cold_read` exists

    report = _raw_cold_read(older)
    assert report.schema_version == "10"
    assert report.recompute_permitted is None
    for row in report.claims:
        assert row.state == COULD_NOT_EVALUATE, (
            f"{row.claim} is {row.state} on a schema-10 file. An artifact that "
            "predates the schema carrying a claim has not left the claim out."
        )
        assert query.ABSENT not in row.state
        assert "11" in row.detail and "10" in row.detail


def test_a_file_that_states_no_schema_at_all_is_could_not_evaluate(
    artifact: Path, tmp_path: Path
) -> None:
    """And it says so — a version nobody stated is not version 11."""
    unversioned = _copy(
        artifact,
        tmp_path / "no-schema.sqlite",
        f"DELETE FROM meta WHERE key = '{store.META_SCHEMA_VERSION}'",
    )
    report = _raw_cold_read(unversioned)
    assert report.schema_version is None
    assert {row.state for row in report.claims} == {COULD_NOT_EVALUATE}
    assert store.META_SCHEMA_VERSION in report[query.CLAIM_ENVIRONMENT].detail


def test_a_newer_schema_is_could_not_evaluate_rather_than_a_stale_pass(
    artifact: Path, tmp_path: Path
) -> None:
    """The other direction, and the one that protects an assessor.

    A newer schema is where a gap gets closed. A report that went on calling a
    closed gap *readable, not checkable* would be the trusted-because-nobody-
    rechecked sentence this whole track exists to remove, so a version this
    reader was not derived against is a could-not-evaluate whichever side of 11
    it falls on.
    """
    newer = _copy(
        artifact,
        tmp_path / "schema-99.sqlite",
        f"UPDATE meta SET value = '99' WHERE key = '{store.META_SCHEMA_VERSION}'",
    )
    report = _raw_cold_read(newer)
    assert {row.state for row in report.claims} == {COULD_NOT_EVALUATE}
    assert "COLD_READ_SCHEMA_VERSION" in report[query.CLAIM_LAYER_BASIS].detail


def test_an_intact_layer_column_is_checkable_against_its_basis(
    artifact: Path,
) -> None:
    """THE THIRD ROW, after issue #252 closed the gap it used to report.

    Nothing is broken in this file: every edge carries a well-formed `layer` tag
    and every one of them carries the basis it was computed from. So the check
    runs — the report recomputes each tag as the weakest of its own inputs and
    compares — and the healthy case comes back CHECKABLE with the count it
    checked and the inputs it checked over, which is what separates a pass from
    an assertion (docs/self-describing.md gap 1).

    The two negatives are next door: a basis removed from the file, and a tag
    edited to disagree with the basis under it.
    """
    conn = store.connect(artifact)
    try:
        tags = {
            str(row["layer"])
            for row in conn.execute("SELECT DISTINCT layer FROM edge").fetchall()
        }
        tagged = int(
            conn.execute("SELECT count(*) AS n FROM edge").fetchone()["n"]
        )
        inputs = {
            str(row["input"])
            for row in conn.execute(
                f"SELECT DISTINCT input FROM {store.EDGE_BASIS_TABLE}"
            ).fetchall()
        }
    finally:
        conn.close()
    assert tags == {query.LAYER_A, query.LAYER_B}, (
        f"this fixture carries {tags}; the point of the test is that the column "
        "is intact"
    )

    row = _cold_read(artifact)[query.CLAIM_LAYER_BASIS]
    assert row.state == query.CHECKABLE
    assert row.checkable
    assert str(tagged) in row.detail, (
        "the report does not say how many tags it checked, so a reader cannot "
        "tell the check ran over the whole file"
    )
    assert all(name in row.detail for name in inputs), (
        "the report does not name the inputs it checked over, so a reader "
        "cannot tell what the tag was said to follow"
    )


def test_a_tag_with_no_basis_under_it_is_readable_not_checkable(
    artifact: Path, tmp_path: Path
) -> None:
    """**THE NEGATIVE.** Delete the basis and the row must stop being a pass.

    Without this, CHECKABLE above asserts a state the report has never been
    shown able to leave — a `_layer_basis_claim` that returned CHECKABLE
    unconditionally would pass every assertion in the test above. This feeds it
    exactly the file the claim is about: tags intact, basis gone, which is what
    every artifact this project built before schema 13 looks like.
    """
    stripped = _copy(
        artifact,
        tmp_path / "no-basis.sqlite",
        f"DELETE FROM {store.EDGE_BASIS_TABLE}",
    )
    row = _cold_read(stripped)[query.CLAIM_LAYER_BASIS]
    assert row.state == query.READABLE_NOT_CHECKABLE
    assert not row.checkable
    assert store.EDGE_BASIS_TABLE in row.detail


def test_a_tag_that_disagrees_with_its_basis_is_could_not_evaluate(
    artifact: Path, tmp_path: Path
) -> None:
    """**THE SECOND NEGATIVE**, and the state is deliberately the third one.

    A tag whose basis admits the other layer is not a missing basis and it is not
    a pass: the file states two answers to *what was this tag computed from* and
    settles neither. Reporting it as READABLE-NOT-CHECKABLE would say the file
    carries nothing when it carries a contradiction, and reporting it as
    CHECKABLE would hand an assessor a verified-looking row over a tag the file
    itself disputes.

    `reg.store.open_edge` cannot produce this file, which is why the fixture is
    made with `UPDATE`: the writer refuses such an edge. What is being tested is
    that the *reader* says no when handed one anyway.
    """
    broken = _copy(
        artifact,
        tmp_path / "disagreeing.sqlite",
        "UPDATE edge SET layer = 'A' WHERE layer = 'B'",
    )
    row = _cold_read(broken)[query.CLAIM_LAYER_BASIS]
    assert row.state == COULD_NOT_EVALUATE
    assert not row.checkable
    assert "admits" in row.detail


def test_the_retained_boundary_makes_the_point_question_checkable(
    artifact: Path,
) -> None:
    """THE FOURTH ROW, and it moved with issue #258.

    The boundary arrived at schema 14 (#257) and made the region *readable*;
    this row is CHECKABLE because `reg.query.reached_point` tests a point
    against it and the report **runs** that query rather than asserting a state
    about it. Held to the file and to the query rather than to the prose: the
    counts come out of the envelope table, and the detail has to quote both the
    radial count and the smaller pointwise one — a row that reported the two as
    one number would have hidden the coverage the answer exists to state.
    """
    conn = store.connect(artifact)
    try:
        columns = {
            str(r["name"])
            for r in conn.execute("PRAGMA table_info(envelope)").fetchall()
        }
        radial, stored = conn.execute(
            "SELECT count(outer_radius) AS radial, count(outer_wkb) AS stored "
            "FROM envelope"
        ).fetchone()
    finally:
        conn.close()
    assert query.OUTER_BOUNDARY_COLUMN in columns
    assert 0 < stored < radial, (
        "precondition: this fixture must retain a boundary at some frames and "
        "not at others, or neither half of the row below is exercised"
    )

    row = _cold_read(artifact)[query.CLAIM_REACHED_POINT]
    assert row.state == query.CHECKABLE
    assert row.checkable
    assert "radially" in row.detail
    assert str(radial) in row.detail and str(stored) in row.detail


def test_a_file_that_kept_no_boundary_is_readable_and_not_checkable(
    artifact: Path, tmp_path: Path
) -> None:
    """**THE NEGATIVE.** Take the boundaries out and the row must stop passing.

    Without this, CHECKABLE above asserts a state the report has never been
    shown able to leave, and a `_reached_point_claim` that returned CHECKABLE on
    sight of an `outer_wkb` column would pass it. This feeds it the file the
    claim is about: the radii intact, every region gone, which is what every
    artifact this project built before schema 14 looks like.

    The inner polygon goes with the outer one, and not to be tidy — the schema's
    own CHECK ties them together (issue #257), so a copy that dropped only the
    boundary is a file `store.connect` would refuse to write and no assessor
    would ever meet.
    """
    stripped = _copy(
        artifact,
        tmp_path / "no-boundary.sqlite",
        "UPDATE envelope SET outer_wkb = NULL, geometry_wkb = NULL",
    )
    row = _cold_read(stripped)[query.CLAIM_REACHED_POINT]
    assert row.state == query.READABLE_NOT_CHECKABLE
    assert not row.checkable
    assert "radially only" in row.detail


def test_a_boundary_whose_containment_cannot_fail_is_could_not_evaluate(
    artifact: Path, tmp_path: Path
) -> None:
    """**THE SECOND NEGATIVE**, and the state is deliberately the fourth one.

    A row that answers *not excluded* to a point inside the region **and** to
    one outside its bounding box has a containment test that has not been seen
    to say both things. That is not a missing boundary and it is not a pass:
    reporting it READABLE-NOT-CHECKABLE would say the file carries no region
    when it carries one, and reporting it CHECKABLE would credit the file with a
    check nothing has shown can fail.

    The condition is fed in by replacing one retained boundary with a region of
    **no extent** — the two probe points are derived from the region's own
    bounds, so a degenerate one collapses them onto each other and the check
    stops being able to disagree with itself. `reg.graph` cannot produce this
    file and the schema's `outer_area > 0` says why an outer bound of no extent
    is always a failed computation; what is being tested is that the *reader*
    says no when handed one anyway.

    It says no one step earlier than that argument: a region of no extent
    contradicts its row's `outer_area`, so `reached_point` refuses before any
    containment runs, and the row carries that refusal. The same-verdict arm
    is reached by the test after this one.
    """
    import shapely

    conn = store.connect(artifact)
    try:
        envelope_id = str(
            conn.execute(
                "SELECT n.node_id AS id FROM edge e "
                "JOIN node n ON n.node_key = e.dst_key "
                "JOIN envelope v ON v.envelope_key = e.dst_key "
                "WHERE e.type = 'HAS_ENVELOPE' AND v.outer_wkb IS NOT NULL "
                "ORDER BY e.t_start, e.edge_id LIMIT 1"
            ).fetchone()["id"]
        )
    finally:
        conn.close()

    degenerate = store.to_wkb(shapely.Point(0.0, 0.0)).hex()
    flattened = _copy(
        artifact,
        tmp_path / "no-extent.sqlite",
        "UPDATE envelope SET outer_wkb = x'" + degenerate + "' "
        "WHERE envelope_key = (SELECT node_key FROM node WHERE node_id = "
        f"'{envelope_id}')",
    )
    row = _cold_read(flattened)[query.CLAIM_REACHED_POINT]
    assert row.state == COULD_NOT_EVALUATE
    assert not row.checkable
    assert "refuses" in row.detail and "outer_area" in row.detail


def test_a_containment_that_says_one_thing_twice_is_could_not_evaluate(
    artifact: Path, monkeypatch
) -> None:
    """The same-verdict arm, which no schema-valid file can now reach.

    The agreement check refuses a region of no extent before containment runs,
    so the only way left to feed this arm its condition is a `reached_point`
    that answers *not excluded* to everything. The arm stays because the
    cold read must not credit a check it has not seen fail, whatever made it
    unable to.
    """
    import dataclasses

    real = query.reached_point

    def agrees_with_everything(conn, x, y, t):
        answer = real(conn, x, y, t)
        return dataclasses.replace(
            answer,
            value=dataclasses.replace(answer.value, could_have_reached=True),
        )

    monkeypatch.setattr(query, "reached_point", agrees_with_everything)
    row = _cold_read(artifact)[query.CLAIM_REACHED_POINT]
    assert row.state == COULD_NOT_EVALUATE
    assert not row.checkable
    assert "same verdict" in row.detail


def test_a_schema_before_the_boundary_is_could_not_evaluate_not_absent(
    artifact: Path, tmp_path: Path
) -> None:
    """THE THIRD NEGATIVE, and it is issue #257's own distinction one level up.

    An artifact written against schema 13 retained no boundary because there was
    nowhere to put one. Reporting that as ABSENT would be a finding about a
    build that chose to retain nothing, which nobody chose here — so it goes the
    way every pre-schema file goes in this report, and the arm is reached
    through raw `sqlite3` because `store.connect` refuses the file.
    """
    older = _copy(
        artifact,
        tmp_path / "schema-13.sqlite",
        f"UPDATE meta SET value = '13' WHERE key = '{store.META_SCHEMA_VERSION}'",
    )
    with pytest.raises(store.StoreError):
        store.connect(older)

    row = _raw_cold_read(older)[query.CLAIM_REACHED_POINT]
    assert row.state == COULD_NOT_EVALUATE
    assert row.state != query.ABSENT
    assert "13" in row.detail and str(query.COLD_READ_SCHEMA_VERSION) in row.detail


def test_a_chain_in_the_file_is_checkable_with_a_key_the_file_does_not_contain(
    attested: tuple[Path, Path],
) -> None:
    """THE FIFTH ROW, and the fifth state (issue #242).

    Nothing is wrong with this file: both record chains are in it and every
    record carries the `prev_hash` that links it to its predecessor and the
    `mac` its party signed it with. So the claim is checkable — by whoever holds
    the key — and the report has to say both halves of that: what a reader would
    need, and what `verify_chain` would then tell them.

    Asserted against the file rather than against the prose: the record counts
    come out of the tables, and the detail has to quote them.
    """
    artifact, _ = attested
    conn = store.connect(artifact)
    try:
        counts = {
            table: int(
                conn.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"]
            )
            for _, table, _ in query.COLD_READ_RECORD_CHAINS
        }
    finally:
        conn.close()
    assert counts["declaration"] > 0 and counts["verdict"] > 0, (
        f"this fixture holds {counts}; the point of the test is that a chain is "
        "in the file"
    )

    row = _cold_read(artifact)[query.CLAIM_CHAIN_INTACT]
    assert row.state == query.CHECKABLE_WITH_A_KEY
    assert not row.checkable, (
        "the file alone does not settle it, so `checkable` is False — the state "
        "string is where the distinction from READABLE-NOT-CHECKABLE is read"
    )
    for table, held in counts.items():
        if held:
            assert f"{table}" in row.detail and str(held) in row.detail
    assert "keyring" in row.detail, "the detail does not name what a reader needs"
    assert "verify_chain" in row.detail, (
        "the detail does not name what the reader would then run, so it states "
        "a gate without stating what is behind it"
    )
    for verdict in ("VERIFIED", "BROKEN", COULD_NOT_EVALUATE):
        assert verdict in row.detail


def test_the_cold_read_does_not_verify_the_chain(
    attested: tuple[Path, Path], tmp_path: Path
) -> None:
    """THE NEGATIVE that keeps the row a *report* rather than a second walk.

    A file whose MACs have been rewritten to a value no key produces is one
    `verify_chain` says BROKEN of. The cold read must report the **same state**
    it reports on the intact file, because it is not checking: it says the
    record is there and the check is gated on a key, and running the check is
    `verify_chain`'s job. A report that changed its answer here would be a
    second implementation of that walk, free to disagree with the one under
    test — and it would be doing it without a key, which is the part that could
    not be right.
    """
    artifact, keyring_path = attested
    tampered = _copy(
        artifact,
        tmp_path / "rewritten-macs.sqlite",
        # One hex digit of every verdict MAC, flipped. The *shape* has to
        # survive: a MAC of the wrong length is a could-not-evaluate for every
        # reader, and this test needs the walk to say BROKEN.
        "UPDATE verdict SET mac = substr(mac, 1, length(mac) - 1) || "
        "CASE WHEN substr(mac, length(mac), 1) = 'a' THEN 'b' ELSE 'a' END",
    )
    assert (
        _cold_read(tampered).state(query.CLAIM_CHAIN_INTACT)
        == query.CHECKABLE_WITH_A_KEY
    )

    conn = store.connect(tampered)
    try:
        report = chain.verify_chain(conn, chain.load_keyring(keyring_path))
    finally:
        conn.close()
    assert report.state is chain.ChainState.BROKEN, (
        "the tamper this test makes must be one the real walk rejects, or it "
        "shows nothing about the cold read declining to run that walk"
    )


def test_an_artifact_with_no_chain_is_absent_and_not_the_fifth_state(
    artifact: Path,
) -> None:
    """THE FIRST NEGATIVE for the row above (issue #242). No records — ABSENT.

    Not the fifth state, which is the whole point of the test: a file with
    nothing signed in it has not failed to support a check, and reporting
    *checkable with a key* over an empty chain would tell an assessor to go and
    find a keyring for a record that is not there.
    """
    conn = store.connect(artifact)
    try:
        tables = {
            str(row["name"])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        held = sum(
            int(conn.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"])
            for _, table, _ in query.COLD_READ_RECORD_CHAINS
            if table in tables
        )
    finally:
        conn.close()
    assert held == 0, "this fixture was built with no record stream"
    assert not tables & {t for _, t, _ in query.COLD_READ_RECORD_CHAINS}, (
        "a build handed no record stream does not create the record tables, so "
        "this is the arm where a missing table has to read as no records"
    )

    row = _cold_read(artifact)[query.CLAIM_CHAIN_INTACT]
    assert row.state == query.ABSENT
    assert row.state != query.CHECKABLE_WITH_A_KEY
    for _, table, _ in query.COLD_READ_RECORD_CHAINS:
        assert table in row.detail


def test_the_fifth_state_does_not_depend_on_the_reader_holding_a_key(
    attested: tuple[Path, Path], tmp_path: Path, monkeypatch
) -> None:
    """THE SECOND NEGATIVE. The state is about the file, not about the caller.

    `cold_read` takes a connection and nothing else, so there is no keyring to
    hand it — and that is the property being asserted. A state that moved when a
    keyring happened to be lying next to the artifact would be reporting the
    reader's desk rather than the file, and two assessors would get two answers
    about one artifact.
    """
    artifact, keyring_path = attested
    with_key = _cold_read(artifact).state(query.CLAIM_CHAIN_INTACT)

    away = tmp_path / "no-keys-here"
    away.mkdir()
    monkeypatch.chdir(away)
    assert not list(away.iterdir()), "the working directory holds no keyring"
    without_key = _cold_read(artifact).state(query.CLAIM_CHAIN_INTACT)

    assert with_key == without_key == query.CHECKABLE_WITH_A_KEY
    assert not keyring_path.is_relative_to(away)


def test_a_record_with_a_blank_mac_is_readable_and_not_checkable_at_all(
    attested: tuple[Path, Path], tmp_path: Path
) -> None:
    """THE THIRD NEGATIVE, and the one that separates the two middle states.

    A record whose `mac` is blank is unverifiable by *anyone* — the key-holder
    included — so it is not the fifth state with a key missing. It is the file
    holding a record and not the signature the record would be checked against,
    which is exactly READABLE-NOT-CHECKABLE. Without this, the fifth state would
    be a state the report has never been shown able to leave for the right
    reason.
    """
    artifact, _ = attested
    blanked = _copy(
        artifact,
        tmp_path / "blank-mac.sqlite",
        "UPDATE verdict SET mac = '' WHERE seq = (SELECT min(seq) FROM verdict)",
    )
    row = _cold_read(blanked)[query.CLAIM_CHAIN_INTACT]
    assert row.state == query.READABLE_NOT_CHECKABLE
    assert row.state != query.CHECKABLE_WITH_A_KEY
    assert "mac" in row.detail and "verdict" in row.detail


def test_the_acknowledgment_row_is_checkable_from_the_file_alone(
    attested: tuple[Path, Path],
) -> None:
    """THE SIXTH ROW. Claim 4's other question, and it needs no key (issue #247).

    `reg.query.acknowledgments(conn)` takes only a connection, so this half of
    Claim 4 really is answerable from the file — the first row in this report to
    become CHECKABLE because *evidence was added* rather than because provenance
    was recorded.

    Held to the query rather than re-derived: the row's state is whatever
    `acknowledgments` answers, so the two cannot disagree about one file.
    """
    artifact, _ = attested
    answer = _ask(artifact, query.acknowledgments)
    assert answer.verdict == ANSWERED, (
        "this fixture must answer the question, or the row below is pinned to a "
        "refusal"
    )
    row = _cold_read(artifact)[query.CLAIM_ACKNOWLEDGMENT]
    assert row.state == query.CHECKABLE
    assert answer.reason in row.detail
    assert query.ACKNOWLEDGING_PARTY in row.detail


def test_an_unacknowledged_passivation_is_could_not_evaluate_and_never_absent(
    attested: tuple[Path, Path], tmp_path: Path
) -> None:
    """THE NEGATIVE for the row above, and it is issue #247's whole distinction.

    Delete the acknowledgment and leave the passivation: the artifact then holds
    a stop nobody in it cleared. That is **not** "nobody acknowledged it" — the
    record holds what enforcement was told — so it is a could-not-evaluate, and
    a report that said ABSENT would have flattened the distinction the
    acknowledgment exists to draw.
    """
    artifact, _ = attested
    passivated = _copy(
        artifact,
        tmp_path / "unacknowledged.sqlite",
        # A passivating verdict with no acknowledgment of it: rewrite one
        # PERMIT to a VETO, which the walk reads as a stop that never ended.
        "UPDATE verdict SET outcome = 'VETO', fault = 'stale_declaration' "
        "WHERE seq = (SELECT max(seq) FROM verdict)",
    )
    assert _ask(passivated, query.acknowledgments).verdict == COULD_NOT_EVALUATE

    row = _cold_read(passivated)[query.CLAIM_ACKNOWLEDGMENT]
    assert row.state == COULD_NOT_EVALUATE
    assert row.state != query.ABSENT
    assert "never a" in row.detail


def test_the_acknowledgment_row_is_absent_where_no_record_stream_was_given(
    artifact: Path,
) -> None:
    """And ABSENT here is right, unlike above: this build was handed no record
    stream at all, so it holds no verdict that could have stopped the robot. The
    file makes no claim rather than making one it cannot support."""
    row = _cold_read(artifact)[query.CLAIM_ACKNOWLEDGMENT]
    assert row.state == query.ABSENT
    assert query.META_ATTESTATION_RECORDS in row.detail


# --------------------------------------------------------------------------
# Held to `reg.graph` and to `reg.chain`. The copies, and the behaviour behind
# them.
# --------------------------------------------------------------------------


def test_the_cold_read_names_the_record_chains_reg_chain_walks() -> None:
    """The second copy, checked (issue #242). `reg.query` cannot import
    `reg.chain` at module level — it reaches `reg.stream` — so the party, table
    and count key of every record chain are spelled a second time in
    `reg.query`. This is what pays for that.

    The same discipline as the recompute keys next door, and the failure it
    prevents is sharper: a table this copy did not name is a chain the cold read
    counts zero records in, and zero records is how it reports **ABSENT**. So a
    record kind added to `reg.chain` and not here would make an artifact holding
    a signed chain report that it holds none — the one direction of error a
    tamper-evidence row must not have.
    """
    walked = tuple(
        (str(spec.role), record.table, record.count_key)
        for spec in chain.CHAINS
        for record in spec.records
    )
    assert query.COLD_READ_RECORD_CHAINS == walked, (
        "reg.query's copy of the record chains has drifted from "
        "reg.chain.CHAINS. The cold read would then report a chain as absent "
        "that verify_chain walks, or count a table nothing signs."
    )
    assert query.META_DECLARATION_COUNT == chain.META_DECLARATION_COUNT
    assert query.META_VERDICT_COUNT == chain.META_VERDICT_COUNT
    assert query.META_ACKNOWLEDGMENT_COUNT == chain.META_ACKNOWLEDGMENT_COUNT


def test_the_cold_read_names_the_recompute_keys_the_builder_refuses_on() -> None:
    """The copy, checked. `reg.query` cannot import `reg.graph` — the boundary
    test at the top of this file walks the whole AST, so a deferred import would
    not get past it either — so the keys `envelope_at` refuses on are spelled a
    second time in `reg.query`. This is what pays for that.

    The same discipline as
    `test_the_meta_keys_this_module_reads_are_the_ones_the_builder_writes`: a
    rename on either side would otherwise turn the report into a quiet
    disagreement with the reader it is describing.

    **Both halves of the split, since issue #241.** The report names the keys it
    compared *and* the recorded ones it did not, so an assessor is not left to
    subtract one list from another; a copy of only the first would let the
    second go stale silently, which is the shape of the defect #241 fixed.
    """
    assert query.COLD_READ_RECOMPUTE_KEYS == graph.RECOMPUTE_ENVIRONMENT_KEYS, (
        "reg.query's copy of the recompute keys has drifted from "
        "reg.graph.RECOMPUTE_ENVIRONMENT_KEYS. The cold read would then report "
        "a recomputation as permitted that envelope_at refuses, or the reverse."
    )
    assert (
        query.COLD_READ_RECORDED_ONLY_KEYS == graph.RECORDED_ONLY_ENVIRONMENT_KEYS
    ), (
        "reg.query's copy of the recorded-but-not-compared keys has drifted "
        "from reg.graph.RECORDED_ONLY_ENVIRONMENT_KEYS. The cold read would "
        "then name the wrong keys as the reach of its own pass."
    )
    assert set(query.COLD_READ_RECOMPUTE_KEYS) <= set(store.ENVIRONMENT_KEYS)
    assert set(query.COLD_READ_RECORDED_ONLY_KEYS) <= set(store.ENVIRONMENT_KEYS)


def test_the_cold_read_reports_the_environment_the_builder_reads_back(
    artifact: Path,
) -> None:
    """One environment, two readers, and they must agree on every key.

    `reg.graph.recorded_environment` is the builder-side reader. The cold read
    does not call it and must still quote the same six values, or the report
    describes a file nobody else sees.
    """
    conn = store.connect(artifact)
    try:
        recorded = graph.recorded_environment(conn)
    finally:
        conn.close()
    detail = _cold_read(artifact)[query.CLAIM_ENVIRONMENT].detail
    for key, value in recorded.items():
        assert f"{key}={value}" in detail, (
            f"the cold read does not report {key}={value}, which "
            "reg.graph.recorded_environment reads out of the same file"
        )


@pytest.mark.parametrize("matching", [True, False])
def test_the_cold_read_agrees_with_envelope_at_about_a_recompute(
    artifact: Path, tmp_path: Path, matching: bool
) -> None:
    """**BOTH SIDES.** `recompute_permitted` is `True` exactly when
    `reg.graph.envelope_at` will recompute a discarded polygon.

    The matching case is this machine, which wrote the file. The mismatched case
    edits one recorded key to a machine this is not — the same edit issue #201's
    own tests make — and both readers have to change their answer together. A
    report that said *permitted* where `envelope_at` refuses would be worse than
    no report: an assessor would go looking for a geometry disagreement that the
    reader was never going to let them see.
    """
    target = artifact
    if not matching:
        target = _copy(
            artifact,
            tmp_path / "elsewhere.sqlite",
            f"UPDATE meta SET value = 'not-{store.build_environment()[store.META_ENV_PLATFORM_MACHINE]}' "
            f"WHERE key = '{store.META_ENV_PLATFORM_MACHINE}'",
        )

    report = _cold_read(target)
    assert report.state(query.CLAIM_RECOMPUTE) == query.CHECKABLE, (
        "the state is about the file, which carries the environment either way; "
        "only 'permitted' is about the machine reading it"
    )
    assert report.recompute_permitted is matching

    conn = store.connect(target)
    try:
        discarded = conn.execute(
            "SELECT e.t_start AS t FROM edge e "
            "JOIN envelope v ON v.envelope_key = e.dst_key "
            "WHERE e.type = 'HAS_ENVELOPE' AND v.geometry_wkb IS NULL "
            "ORDER BY e.t_start LIMIT 1"
        ).fetchone()
        assert discarded is not None, (
            "this fixture retains every polygon, so it cannot exercise the "
            "recompute path at all"
        )
        t = float(discarded["t"])
        if matching:
            assert graph.envelope_at(conn, t) is not None
        else:
            with pytest.raises(graph.GraphQueryError) as caught:
                graph.envelope_at(conn, t)
            assert store.META_ENV_PLATFORM_MACHINE in str(caught.value)
    finally:
        conn.close()


def test_a_file_with_no_environment_refuses_a_recompute_on_both_readers(
    artifact: Path, tmp_path: Path
) -> None:
    """The third arm, where `permitted` is `None` and `envelope_at` still says
    no — and says no *differently*, because nothing was compared.

    Without this, `None` and `False` could be collapsed into one falsey value
    and every test above would still pass.
    """
    stripped = _copy(
        artifact,
        tmp_path / "unattributable.sqlite",
        "DELETE FROM meta WHERE key LIKE 'env\\_%' ESCAPE '\\'",
    )
    report = _cold_read(stripped)
    assert report.recompute_permitted is None
    assert report.recompute_permitted is not False

    conn = store.connect(stripped)
    try:
        row = conn.execute(
            "SELECT e.t_start AS t FROM edge e "
            "JOIN envelope v ON v.envelope_key = e.dst_key "
            "WHERE e.type = 'HAS_ENVELOPE' AND v.geometry_wkb IS NULL "
            "ORDER BY e.t_start LIMIT 1"
        ).fetchone()
        with pytest.raises(graph.GraphQueryError) as caught:
            graph.envelope_at(conn, float(row["t"]))
    finally:
        conn.close()
    assert "states no" in str(caught.value)


# --------------------------------------------------------------------------
# The report's own refusals, and the CLI.
# --------------------------------------------------------------------------


def test_a_sixth_state_is_refused(artifact: Path) -> None:
    """A row may only carry one of the five. A sixth is a state nobody defined
    the relationship of to a pass, and a caller reading it would have to guess.

    **This test used to refuse a fifth, and issue #242 was the deliberate act it
    existed to force.** It is not an obstacle that was routed around: the fifth
    state was added because `chain-intact` fits none of the four — the file
    alone cannot check it, it is not unverifiable, the chain is not absent, and
    nothing failed to be established — and because flattening it into a
    neighbour would report a deliberate gate as a defect. Editing this line is
    the cost of that, and the cost is paid once per state rather than never.
    """
    with pytest.raises(QueryError) as caught:
        query.ColdReadClaim(
            claim=query.CLAIM_ENVIRONMENT,
            question="?",
            state="MOSTLY-FINE",
            detail="d",
        )
    assert "MOSTLY-FINE" in str(caught.value)
    assert query.CHECKABLE_WITH_A_KEY in str(caught.value), (
        "the refusal lists the states it accepts, and the fifth is one of them"
    )

    with pytest.raises(QueryError):
        query.ColdReadClaim(
            claim="something-else", question="?", state=query.ABSENT, detail="d"
        )
    with pytest.raises(QueryError):
        query.ColdReadClaim(
            claim=query.CLAIM_ENVIRONMENT,
            question="?",
            state=query.ABSENT,
            detail="   ",
        )


def test_a_partial_report_is_refused(artifact: Path) -> None:
    """Every claim gets a row. A row omitted and a row reporting ABSENT are
    different facts, and a report that could omit one would make them look the
    same to a reader counting rows."""
    full = _cold_read(artifact)
    with pytest.raises(QueryError) as caught:
        query.ColdRead(
            schema_version=full.schema_version,
            claims=full.claims[:-1],
            recompute_permitted=full.recompute_permitted,
        )
    assert query.CLAIM_ACKNOWLEDGMENT in str(caught.value)
    assert query.CLAIM_CHAIN_INTACT in str(caught.value)
    with pytest.raises(QueryError):
        full[query.CLAIM_ENVIRONMENT + "-nope"]


def test_the_cli_prints_the_cold_read(artifact: Path, capsys) -> None:
    """`--cold-read` on an artifact from `main`: exit 0 and one row per claim,
    each with its state and its detail. Exit 0 is not a claim that every row
    passed — four of the six are CHECKABLE here and two are ABSENT, and a state
    short of CHECKABLE is the report working rather than the run failing; only a
    row that could not be *evaluated* is exit 1."""
    code = query.main([str(artifact), "--cold-read"])
    out = capsys.readouterr().out
    assert code == query.EXIT_OK
    for claim, state in COLD_READ_TODAY.items():
        assert f"{claim}: {state}" in out
    # `READABLE-NOT-CHECKABLE` was asserted present here until issue #258 moved
    # the last row out of it. It is not gone from the vocabulary — the negatives
    # above reach it — but no shipped fixture reports it any more, and an
    # assertion that a state appears on a *healthy* artifact could only be kept
    # true by leaving a gap open.
    assert f"{query.CLAIM_REACHED_POINT}: {query.CHECKABLE}" in out
    assert "recompute permitted: yes" in out


def test_the_cli_prints_the_fifth_state_on_an_attested_artifact(
    attested: tuple[Path, Path], capsys
) -> None:
    """And exit 0 with it. `CHECKABLE-WITH-A-KEY-THE-FILE-DOES-NOT-CONTAIN` is
    not a could-not-evaluate: nothing failed to be established, so a `1` here
    would be red on every artifact this project builds with a record stream.

    The printed row must carry the whole state string, because that string *is*
    the finding — an assessor who saw only "CHECKABLE" would take the file to
    settle tamper-evidence on its own.
    """
    code = query.main([str(attested[0]), "--cold-read"])
    out = capsys.readouterr().out
    assert code == query.EXIT_OK
    for claim, state in COLD_READ_ATTESTED.items():
        assert f"{claim}: {state}" in out
    assert f"{query.CLAIM_CHAIN_INTACT}: {query.CHECKABLE_WITH_A_KEY}" in out
    assert "keyring" in out


def test_the_cli_refuses_a_key_it_would_otherwise_drop_on_a_cold_read(
    artifact: Path, tmp_path: Path, capsys
) -> None:
    """`--cold-read --keyring K` reads no key, so it is refused rather than
    ignored. Same rule as every other flag pairing here: a flag that is silently
    dropped reads as one that was applied."""
    code = query.main(
        [str(artifact), "--cold-read", "--keyring", str(tmp_path / "absent.json")]
    )
    assert code == query.EXIT_USAGE
    assert "--keyring" in capsys.readouterr().err


def test_the_cold_read_is_in_the_list_output(capsys) -> None:
    """`--list` names it. A reader who does not know the flag exists cannot run
    the one check this track ships, and a name missing from the list reads as a
    milestone that has not landed."""
    query.main(["--list"])
    out = capsys.readouterr().out
    assert "--cold-read" in out
    for state in query.COLD_READ_STATES:
        assert state in out, (
            f"--list does not name the {state} state, so a reader meeting it in "
            "a report has nowhere to look it up"
        )
