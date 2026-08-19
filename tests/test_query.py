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

from reg import bench, graph, query, store
from reg.bench import AGREE, COULD_NOT_EVALUATE, DISAGREE, run_scenario
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
    return bench.ground_truth_from_csv(csv_path, scenario(SCENARIO).world)


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
        store.META_FRAME_PERIOD,
    ):
        assert key in meta, (
            f"reg.query reads meta[{key!r}] and reg.graph does not write it."
        )
    assert query.META_OCCURRENCE_RETENTION == graph.META_OCCURRENCE_RETENTION
    assert query.META_OCCURRENCE_RESOLUTION == graph.META_OCCURRENCE_RESOLUTION


# --------------------------------------------------------------------------
# Agreement with the raw stream, through the benchmark's own checker.
# --------------------------------------------------------------------------


def _check(name: str, answers: bench.LevelAnswers, truth: bench.GroundTruth) -> str:
    """One query's verdict, from `reg.bench.check_level`. Not a second checker.

    docs/lossiness.md's agreement predicates are already implemented once, in the
    benchmark, and issue #37 says to reuse them. Writing a comparison here would
    be the same trap the whole issue is about, one level down.
    """
    spec = next(q for q in bench.RESOLUTION_QUERIES if q.name == name)
    return bench.check_level(spec, answers, truth).verdict


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
            bench.LevelAnswers(None, None, answer.value.samples, None),
            truth,
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
            bench.LevelAnswers(None, None, answer.value.samples, None),
            truth,
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
    )
    assert _check("min_separation", answers, truth) == AGREE
    assert _check("did_contact_occur", answers, truth) == AGREE
    assert _check("time_of_closest_approach", answers, truth) == AGREE


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
    answers = bench.LevelAnswers(smallest.value, None, None, contact.value)
    assert _check("min_separation", answers, truth) == AGREE
    assert _check("did_contact_occur", answers, truth) == AGREE


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
    # to look like queries that returned nothing.
    assert "verify_chain" in out


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
