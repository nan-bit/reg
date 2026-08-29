"""`tests/` mirrors `reg/` — and where it does not, the exception is named.

Issue #129. `CLAUDE.md` stated the layout as *`tests/` mirrors it*, and four
modules had no mirrored file: `reg/sim.py`, `reg/store.py`, `reg/types.py`,
`reg/world.py`. The coverage was never the problem — each of those is imported
by seven to eleven test files and is exercised hard. The problem was that the
file which tells an unattended agent what the rules are stated a rule the
repository did not follow, and nothing failed. An agent reading that sentence
literally would have created four stub test files, which would have *reduced*
clarity about where those modules are actually verified.

So this is not a coverage check and it must not be mistaken for one. It checks
one thing: **every module under `reg/` either has a mirrored `tests/test_*.py`
or a `VERIFIED_ELSEWHERE` entry that names the tests standing in for it.** The
sentence in `CLAUDE.md` now describes that arrangement, and `test_claude_md_*`
below holds it to it.

It fails in both directions, which is the only shape worth having:

* a new module with neither a mirrored test nor an allowlist entry — fail;
* an allowlist entry removed while the mirrored file is still absent — fail;
* an allowlist entry kept after the mirrored file arrived — fail, because a
  stale exemption is how the allowlist stops describing anything;
* an allowlist entry for a module that no longer exists — fail;
* a witness that does not exist, or that does not import the module it is
  claimed to verify — fail. The entry has to be true, not just present.

Three-valued per `CLAUDE.md`'s *a check must be able to fail*: an empty `reg/`,
an empty `tests/`, an allowlist entry naming no witness, and an allowlist entry
giving no reason are all COULD-NOT-EVALUATE, and none of them resolves to a
pass. Emptying something is not how this check gets satisfied.

The negatives are the deliverable here. Every predicate is fed a tree it must
reject — a module with neither condition, an emptied allowlist against the real
absent mirrors, a lying witness, and the pre-#129 wording of the `CLAUDE.md`
sentence — and required to say DISAGREE.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
PACKAGE = REPO / "reg"
TESTS = REPO / "tests"
CLAUDE_MD = REPO / "CLAUDE.md"

AGREE = "AGREE"
DISAGREE = "DISAGREE"
COULD_NOT_EVALUATE = "COULD-NOT-EVALUATE"

# This file is what the `CLAUDE.md` layout sentence points at. If it is renamed,
# rename it there too — `test_claude_md_points_at_this_allowlist` will say so.
SELF = Path(__file__).name


@dataclass(frozen=True)
class Elsewhere:
    """A module verified through its consumers' tests rather than a mirror.

    `witnesses` are the `tests/` files that stand in for the missing mirrored
    file; each must exist and must actually import the module. `why` says what
    about the module makes a mirrored file the wrong shape — a reason, not a
    restatement of the fact that one is missing.
    """

    witnesses: tuple[str, ...]
    why: str


# THIS IS NOT A PLACE TO PARK A NEW MODULE.
#
# An entry here is a claim that a mirrored test file would make the repository
# *harder* to read, and it has to survive being read as one. Every entry below
# is for a module that predates issue #129 and is already imported by seven or
# more test files; "I have not written the test yet" is not one of the reasons
# listed, and it is not an admissible one. If you are adding a module, write
# `tests/test_<module>.py`. If you genuinely believe the exception applies,
# argue it in the PR — adding a line here is not the argument, it is the
# conclusion, and a reviewer who sees this list grow will read it that way.
VERIFIED_ELSEWHERE: dict[str, Elsewhere] = {
    "sim.py": Elsewhere(
        witnesses=("test_sim_cli.py", "test_stream.py", "test_bench_determinism.py"),
        why=(
            "A CLI that composes reg.scenarios and reg.stream and deliberately "
            "holds no simulation logic of its own. What is worth testing about "
            "it is its command-line surface and the determinism of the stream it "
            "produces, and those live with the CLI and the format they belong to."
        ),
    ),
    "store.py": Elsewhere(
        witnesses=("test_graph.py", "test_query.py", "test_chain.py"),
        why=(
            "The SQLite schema and write primitives. A row inserted is only "
            "meaningful once it is read back or hashed, so the primitives are "
            "exercised through the builder, the query layer and the chain rather "
            "than against the schema in isolation."
        ),
    ),
    "types.py": Elsewhere(
        witnesses=("test_layer_boundary.py", "test_envelope.py", "test_kinematics.py"),
        why=(
            "Shared dataclasses carrying the Layer A / Layer B boundary. The "
            "property that matters is structural — what ProprioState may not "
            "name — and it is asserted against the source in "
            "test_layer_boundary.py, which is where a reader looking for the "
            "boundary rule will go."
        ),
    ),
    "world.py": Elsewhere(
        witnesses=("test_scenarios.py", "test_declare.py", "test_viz.py"),
        why=(
            "Layer B ground-truth geometry in its entirety. It holds no logic "
            "Layer A may read; it is fixture data, and it is verified where the "
            "scenarios, declarations and figures built from it are."
        ),
    ),
}


def modules_of(package: Path) -> set[str]:
    """Every module under `package` that a mirrored test could exist for.

    Dunder files are excluded: `__init__.py` is the package marker, and
    `tests/test___init__.py` is not a file anyone should be asked to write.
    """
    return {
        path.name
        for path in sorted(package.glob("*.py"))
        if not path.name.startswith("__")
    }


def mirror_of(module: str) -> str:
    """`sim.py` -> `test_sim.py`. Strict: `test_sim_cli.py` is not a mirror."""
    return f"test_{module}"


def importers(module: str, sources: dict[str, str]) -> set[str]:
    """The `sources` whose text imports `reg.<module>`, by either spelling."""
    stem = module.removesuffix(".py")
    pattern = re.compile(
        rf"\breg\.{re.escape(stem)}\b"
        rf"|\bfrom\s+reg\s+import\s+[^\n]*\b{re.escape(stem)}\b"
    )
    return {name for name, text in sources.items() if pattern.search(text)}


def mirror_verdict(
    modules: set[str],
    tests: set[str],
    allowlist: dict[str, Elsewhere],
) -> tuple[str, list[str]]:
    """Does every module have a mirrored test or a live allowlist entry?

    DISAGREE names each module that has neither, each allowlist entry whose
    mirrored file has since arrived, and each entry naming a module that is
    gone. An empty `reg/` or an empty `tests/` is COULD-NOT-EVALUATE.
    """
    if not modules:
        return COULD_NOT_EVALUATE, ["no modules found under reg/"]
    if not tests:
        return COULD_NOT_EVALUATE, ["no test files found under tests/"]

    problems: list[str] = []
    for module in sorted(modules):
        mirrored = mirror_of(module) in tests
        exempt = module in allowlist
        if not mirrored and not exempt:
            problems.append(
                f"reg/{module}: no tests/{mirror_of(module)} and no "
                f"VERIFIED_ELSEWHERE entry — write the mirrored test"
            )
        elif mirrored and exempt:
            problems.append(
                f"reg/{module}: tests/{mirror_of(module)} exists, so its "
                f"VERIFIED_ELSEWHERE entry is stale — delete it"
            )
    for module in sorted(allowlist):
        if module not in modules:
            problems.append(
                f"VERIFIED_ELSEWHERE names {module}, which is not a module "
                f"under reg/ — delete the entry"
            )

    return (DISAGREE, problems) if problems else (AGREE, [])


def witness_verdict(
    allowlist: dict[str, Elsewhere],
    sources: dict[str, str],
) -> tuple[str, list[str]]:
    """Does every allowlist entry name real tests that really import it?

    An entry naming no witness, or giving no reason, is COULD-NOT-EVALUATE: it
    is the same silence as having no entry at all, dressed as an answer.
    """
    if not sources:
        return COULD_NOT_EVALUATE, ["no test sources to read"]

    unevaluable: list[str] = []
    problems: list[str] = []
    for module, entry in sorted(allowlist.items()):
        if not entry.witnesses:
            unevaluable.append(f"{module}: entry names no witness test file")
        if not entry.why.strip():
            unevaluable.append(f"{module}: entry gives no reason")
        for witness in entry.witnesses:
            if witness not in sources:
                problems.append(f"{module}: witness tests/{witness} does not exist")
            elif witness not in importers(module, sources):
                problems.append(
                    f"{module}: witness tests/{witness} does not import "
                    f"reg.{module.removesuffix('.py')}"
                )

    if unevaluable:
        return COULD_NOT_EVALUATE, unevaluable + problems
    return (DISAGREE, problems) if problems else (AGREE, [])


def present_test_files() -> set[str]:
    return {path.name for path in sorted(TESTS.glob("test_*.py"))}


def present_test_sources() -> dict[str, str]:
    return {
        path.name: path.read_text(encoding="utf-8")
        for path in sorted(TESTS.glob("test_*.py"))
    }


# --------------------------------------------------------------------------
# The tree as it stands
# --------------------------------------------------------------------------


def test_every_module_is_mirrored_or_named_as_an_exception() -> None:
    verdict, problems = mirror_verdict(
        modules_of(PACKAGE), present_test_files(), VERIFIED_ELSEWHERE
    )
    assert verdict == AGREE, "\n".join(problems)


def test_every_exception_names_tests_that_exist_and_import_the_module() -> None:
    verdict, problems = witness_verdict(VERIFIED_ELSEWHERE, present_test_sources())
    assert verdict == AGREE, "\n".join(problems)


def test_the_allowlist_is_exactly_the_unmirrored_modules() -> None:
    """The list describes the tree; it does not exempt anything preemptively."""
    tests = present_test_files()
    unmirrored = {m for m in modules_of(PACKAGE) if mirror_of(m) not in tests}
    assert set(VERIFIED_ELSEWHERE) == unmirrored


# --------------------------------------------------------------------------
# The negatives — each predicate fed the condition it guards against
# --------------------------------------------------------------------------


def test_a_new_module_with_neither_a_mirror_nor_an_entry_fails() -> None:
    modules = modules_of(PACKAGE) | {"planner.py"}
    verdict, problems = mirror_verdict(modules, present_test_files(), VERIFIED_ELSEWHERE)
    assert verdict == DISAGREE
    assert any("reg/planner.py" in p for p in problems)


def test_emptying_the_allowlist_while_the_mirrors_are_absent_fails() -> None:
    """The check the issue names: `pytest` must go red if this list is cleared."""
    verdict, problems = mirror_verdict(modules_of(PACKAGE), present_test_files(), {})
    assert verdict == DISAGREE
    assert len(problems) == len(VERIFIED_ELSEWHERE)
    for module in VERIFIED_ELSEWHERE:
        assert any(f"reg/{module}" in p for p in problems)


def test_an_entry_kept_after_its_mirror_arrived_fails() -> None:
    tests = present_test_files() | {mirror_of("sim.py")}
    verdict, problems = mirror_verdict(modules_of(PACKAGE), tests, VERIFIED_ELSEWHERE)
    assert verdict == DISAGREE
    assert any("stale" in p for p in problems)


def test_an_entry_for_a_module_that_is_gone_fails() -> None:
    allowlist = dict(VERIFIED_ELSEWHERE)
    allowlist["deleted.py"] = Elsewhere(witnesses=("test_graph.py",), why="gone")
    verdict, problems = mirror_verdict(modules_of(PACKAGE), present_test_files(), allowlist)
    assert verdict == DISAGREE
    assert any("deleted.py" in p and "not a module" in p for p in problems)


def test_a_witness_that_does_not_exist_fails() -> None:
    allowlist = {
        "world.py": Elsewhere(witnesses=("test_nowhere.py",), why="claimed"),
    }
    verdict, problems = witness_verdict(allowlist, present_test_sources())
    assert verdict == DISAGREE
    assert any("does not exist" in p for p in problems)


def test_a_witness_that_does_not_import_the_module_fails() -> None:
    """A real test file named as a witness for a module it never touches."""
    sources = present_test_sources()
    assert "test_readme.py" not in importers("world.py", sources)
    allowlist = {
        "world.py": Elsewhere(witnesses=("test_readme.py",), why="claimed"),
    }
    verdict, problems = witness_verdict(allowlist, sources)
    assert verdict == DISAGREE
    assert any("does not import reg.world" in p for p in problems)


@pytest.mark.parametrize(
    "entry",
    [
        Elsewhere(witnesses=(), why="verified elsewhere"),
        Elsewhere(witnesses=("test_graph.py",), why="   "),
    ],
    ids=["names-no-witness", "gives-no-reason"],
)
def test_an_entry_that_says_nothing_is_could_not_evaluate(entry: Elsewhere) -> None:
    verdict, problems = witness_verdict({"store.py": entry}, present_test_sources())
    assert verdict == COULD_NOT_EVALUATE
    assert problems


@pytest.mark.parametrize(
    "modules,tests",
    [(set(), {"test_graph.py"}), ({"graph.py"}, set())],
    ids=["no-modules", "no-tests"],
)
def test_an_empty_tree_is_could_not_evaluate(
    modules: set[str], tests: set[str]
) -> None:
    verdict, problems = mirror_verdict(modules, tests, VERIFIED_ELSEWHERE)
    assert verdict == COULD_NOT_EVALUATE
    assert problems


def test_unreadable_test_sources_are_could_not_evaluate() -> None:
    verdict, problems = witness_verdict(VERIFIED_ELSEWHERE, {})
    assert verdict == COULD_NOT_EVALUATE
    assert problems


# --------------------------------------------------------------------------
# The sentence this exists to make true
# --------------------------------------------------------------------------

LAYOUT = re.compile(r"^Layout:.*?(?=\n\n)", re.MULTILINE | re.DOTALL)


def layout_paragraph(text: str) -> str | None:
    match = LAYOUT.search(text)
    return match.group(0) if match else None


def claude_md_verdict(text: str) -> tuple[str, list[str]]:
    """Does the layout paragraph point at the allowlist that qualifies it?

    A paragraph claiming `tests/` mirrors `reg/` full stop is DISAGREE: that is
    the pre-#129 wording, and it is false. A `CLAUDE.md` with no layout
    paragraph at all is COULD-NOT-EVALUATE — deleting the sentence is not how
    the sentence gets to be true.
    """
    paragraph = layout_paragraph(text)
    if paragraph is None:
        return COULD_NOT_EVALUATE, ["CLAUDE.md has no `Layout:` paragraph"]
    if SELF not in paragraph:
        return DISAGREE, [
            f"the layout paragraph does not name tests/{SELF}, which is where "
            f"the exceptions to `tests/ mirrors reg/` are listed"
        ]
    return AGREE, []


def test_claude_md_points_at_this_allowlist() -> None:
    verdict, problems = claude_md_verdict(CLAUDE_MD.read_text(encoding="utf-8"))
    assert verdict == AGREE, "\n".join(problems)


def test_the_pre_129_layout_sentence_fails() -> None:
    """The exact wording that was there on 2026-08-29, required to say no."""
    before = (
        "Layout: `reg/` is the package, `tests/` mirrors it, `docs/` holds the "
        "argument,\n`runs/` and `bench/` hold generated output and are not "
        "committed.\n\n"
    )
    verdict, problems = claude_md_verdict(before)
    assert verdict == DISAGREE
    assert problems


def test_deleting_the_layout_sentence_is_could_not_evaluate() -> None:
    verdict, problems = claude_md_verdict("# reg — conventions\n\nnothing here.\n")
    assert verdict == COULD_NOT_EVALUATE
    assert problems
