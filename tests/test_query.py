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
import subprocess
import sys
from pathlib import Path

import pytest

from reg import bench, chain, graph, query, store
from reg.bench import AGREE, COULD_NOT_EVALUATE, DISAGREE, run_scenario
from reg.identity import RunIdentity
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
    for name in ("declared_bound", "violations", "verdicts"):
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
        "declared_bound": (1.0,),
        "violations": ((0.0, 5.0),),
        "verdicts": (declaration_id,),
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
        human_radius=scenario(SCENARIO).world.human_radius,
        records=graph.AttestationRecords(declarations=(), verdicts=()),
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
