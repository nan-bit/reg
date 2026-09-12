"""A citation from code into `docs/` names a place that is still there.

Issue #274, and the reason it exists as a test rather than as a grep in a PR
body. `reg/` and `tests/` point into the documents about 290 times. The docs cut
(#270) deletes prose, and every deletion is an opportunity to leave a pointer
aimed at nothing — a comment that reads like evidence and resolves to a section
that was cut two PRs ago. Nothing failed when that happened, because a stale
cross-reference is invisible from inside the file holding it.

Two checks, and they catch different failures.

**Sections that exist.** `docs/limitations.md §12` is checked against the
headings `docs/limitations.md` actually has. The match is deliberately narrow:
the `§N` has to sit immediately after the document name. Attributing a loose
`§N` to the nearest document named earlier on the line was tried and produced
three false accusations in this repository — `§14's own words` next to a mention
of `limitations.md` means `prior-art.md` §14 to every human reader. A check that
cries wolf gets switched off within a week, so the narrow form is the one worth
having, and what it costs is stated: a `§N` written apart from its document is
not attributed to any document and is not checked.

**Places that were retired.** A section can survive while the thing cited inside
it does not. `RETIRED_PLACES` is that list: for each, what was cited, the shape
that cites it, and where a citation should point instead. Both entries are from
the cut's first pointer pass — `self-describing.md` §1's gap narrative, which
becomes a pointer to [`docs/limitations.md`](../docs/limitations.md) §12 and its
identically numbered table rows, and §7's two answered questions, which the cut
deletes and §11's amendment records the answer to. A retired place is not
detectable by section number, which is why it needs its own table.

Three-valued per `CLAUDE.md`'s *a check must be able to fail*, and the third
state never resolves to the first: no source files, no documents, no citations
found at all, and a cited document that numbers no sections are each
COULD-NOT-EVALUATE. Only AGREE passes. Emptying `reg/` is not how this check
gets satisfied, and neither is a document renumbering its headings out of a
shape this file can read.

The negatives are the deliverable. Every predicate is fed the condition it
guards against — a citation into a section that does not exist, into a document
that does not exist, into a document with no numbered sections, a retired gap
citation, a retired question citation — and required to say DISAGREE or
COULD-NOT-EVALUATE. `§7`'s question 3, which survives the cut with its number,
is fed in too and required *not* to be flagged.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
DOCS = REPO / "docs"
SOURCE_ROOTS = ("reg", "tests")

AGREE = "AGREE"
DISAGREE = "DISAGREE"
COULD_NOT_EVALUATE = "COULD-NOT-EVALUATE"

#: `docs/<name>.md §<n>`, optionally backticked, with the section immediately
#: after the document. See the module docstring for why nothing looser.
SECTION_CITATION = re.compile(r"`?docs/([a-zA-Z0-9_-]+\.md)`?\s+§\s*(\d+)")

#: A numbered top-level section, as every document in `docs/` writes them:
#: `## 12. The artifact is not self-describing`.
NUMBERED_SECTION = re.compile(r"(?m)^#+\s+(\d+)\.")


@dataclass(frozen=True)
class Citation:
    """One pointer from a source file into a document's numbered section."""

    path: str
    line: int
    document: str
    section: str
    text: str

    def where(self) -> str:
        return f"{self.path}:{self.line}"


@dataclass(frozen=True)
class Retired:
    """A place inside a surviving section that citations must stop naming.

    `what` says what was cited, `pattern` is the shape a citation to it takes,
    and `instead` names where the answer lives now. A `Retired` entry is a claim
    that the destination no longer holds what the citation promised — not that
    the section number changed, which the other check covers.
    """

    what: str
    pattern: re.Pattern[str]
    instead: str


RETIRED_PLACES: tuple[Retired, ...] = (
    Retired(
        what="`docs/self-describing.md` §1's gap narrative",
        # The escaped dot is load-bearing: it keeps this file's own source out
        # of the acceptance grep in issue #274.
        pattern=re.compile(r"self-describing\.md`?\s+gap\s+[0-9]"),
        instead=(
            "`docs/limitations.md` §12, whose table rows 1-3 are the same three "
            "gaps under the same numbering"
        ),
    ),
    Retired(
        what="`docs/self-describing.md` §7's questions 1 and 2",
        # Unanchored to the document on purpose: the two citations this retired
        # wrapped the document name onto the line above. No other document in
        # this repository numbers questions under a section.
        pattern=re.compile(r"§\s*7\s+question\s+[12]\b"),
        instead=(
            "`docs/limitations.md` §11's amendment, which records the answers "
            "(issue #252 for the granularity, issue #229 for the fixture)"
        ),
    ),
)


@dataclass(frozen=True)
class Result:
    """A verdict and what it was reached from."""

    verdict: str
    detail: str


def source_files(
    roots: Path, names: tuple[str, ...] = SOURCE_ROOTS
) -> tuple[Path, ...]:
    """Every Python file under `names`, relative to `roots`."""
    found: list[Path] = []
    for name in names:
        found.extend(sorted((roots / name).rglob("*.py")))
    return tuple(found)


def numbered_sections(document: Path) -> frozenset[str]:
    """The section numbers a document states as headings."""
    return frozenset(NUMBERED_SECTION.findall(document.read_text(encoding="utf-8")))


def citations(sources: tuple[Path, ...], relative_to: Path) -> tuple[Citation, ...]:
    """Every `docs/<name>.md §<n>` pointer in `sources`."""
    found: list[Citation] = []
    for path in sources:
        rel = str(path.relative_to(relative_to))
        for number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            for match in SECTION_CITATION.finditer(line):
                found.append(
                    Citation(
                        path=rel,
                        line=number,
                        document=match.group(1),
                        section=match.group(2),
                        text=match.group(0),
                    )
                )
    return tuple(found)


def check_section_citations_resolve(repo: Path, docs: Path) -> Result:
    """Does every cited section exist in the document it is cited from?"""
    sources = source_files(repo)
    if not sources:
        return Result(COULD_NOT_EVALUATE, f"no Python sources under {repo}.")
    if not docs.is_dir() or not any(docs.glob("*.md")):
        return Result(COULD_NOT_EVALUATE, f"no documents under {docs}.")
    found = citations(sources, repo)
    if not found:
        return Result(
            COULD_NOT_EVALUATE,
            "no section citations found at all. Either the code stopped citing "
            "the documents or SECTION_CITATION stopped matching the shape it "
            "does; neither is this check passing.",
        )

    unreadable: list[str] = []
    broken: list[str] = []
    for citation in found:
        document = docs / citation.document
        if not document.is_file():
            broken.append(f"{citation.where()} cites {citation.text}, which is no file")
            continue
        sections = numbered_sections(document)
        if not sections:
            unreadable.append(
                f"{citation.where()} cites {citation.text}, but "
                f"{citation.document} states no numbered sections"
            )
            continue
        if citation.section not in sections:
            broken.append(
                f"{citation.where()} cites {citation.text}, and "
                f"{citation.document} has sections "
                f"{', '.join(sorted(sections, key=int))}"
            )
    if unreadable:
        return Result(COULD_NOT_EVALUATE, "; ".join(unreadable))
    if broken:
        return Result(DISAGREE, "; ".join(broken))
    return Result(AGREE, f"{len(found)} section citations, all resolved.")


def check_no_citation_into_a_retired_place(repo: Path) -> Result:
    """Does anything still point at a place the docs cut takes away?"""
    sources = source_files(repo)
    if not sources:
        return Result(COULD_NOT_EVALUATE, f"no Python sources under {repo}.")
    if not RETIRED_PLACES:
        return Result(
            COULD_NOT_EVALUATE,
            "RETIRED_PLACES is empty, so this check reads every file and asks "
            "nothing of any of them.",
        )

    aimed: list[str] = []
    for path in sources:
        rel = str(path.relative_to(repo))
        for number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            for retired in RETIRED_PLACES:
                if retired.pattern.search(line):
                    aimed.append(
                        f"{rel}:{number} still cites {retired.what}; "
                        f"point it at {retired.instead}"
                    )
    if aimed:
        return Result(DISAGREE, "; ".join(aimed))
    return Result(
        AGREE, f"{len(sources)} sources, none citing a retired place."
    )


# --------------------------------------------------------------------------
# The repository as it stands.
# --------------------------------------------------------------------------


def test_every_cited_section_exists_in_the_document_cited() -> None:
    result = check_section_citations_resolve(REPO, DOCS)
    assert result.verdict == AGREE, result.detail


def test_nothing_points_at_a_place_the_docs_cut_takes_away() -> None:
    result = check_no_citation_into_a_retired_place(REPO)
    assert result.verdict == AGREE, result.detail


def test_the_runtime_store_error_names_a_section_that_exists() -> None:
    """The one re-aimed citation a user can read without opening the source.

    `reg.store.layer_from_basis` refuses an empty basis and names, in the
    message, the gap the refusal exists for. Issue #274's last acceptance
    criterion is about this string specifically, so it is asserted against the
    document rather than against itself.
    """
    from reg import store

    with pytest.raises(store.StoreError) as raised:
        store.layer_from_basis(())
    message = str(raised.value)

    cited = SECTION_CITATION.findall(message)
    assert cited, f"the refusal cites no document section at all: {message}"
    for document, section in cited:
        assert section in numbered_sections(DOCS / document), (
            f"the refusal cites {document} §{section}, which that file does "
            f"not have."
        )
    for retired in RETIRED_PLACES:
        assert not retired.pattern.search(message), (
            f"the refusal still cites {retired.what}; point it at "
            f"{retired.instead}."
        )


# --------------------------------------------------------------------------
# The negatives. Each predicate is fed the condition it guards against.
# --------------------------------------------------------------------------


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """A miniature repository: one document with sections, one source root."""
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "limitations.md").write_text(
        "# Limitations\n\n## 11. One\n\nprose\n\n## 12. Two\n\nprose\n",
        encoding="utf-8",
    )
    for name in SOURCE_ROOTS:
        (tmp_path / name).mkdir()
    return tmp_path


def _write(tree: Path, body: str, name: str = "mod.py") -> None:
    (tree / SOURCE_ROOTS[0] / name).write_text(body, encoding="utf-8")


#: Like `_CUT_DOC` below: the broken citations the negatives feed in are
#: assembled rather than written out, so that this file — which the checks read
#: like any other — does not accuse itself of the faults it is proving it
#: catches.
_ABSENT_DOC = "gone" + ".md"
_UNNUMBERED_DOC = "flat" + ".md"
_ABSENT_SECTION = 99


def test_a_healthy_tree_agrees(tree: Path) -> None:
    _write(tree, "# see docs/limitations.md §12\n")
    assert check_section_citations_resolve(tree, tree / "docs").verdict == AGREE


def test_a_citation_into_a_section_that_does_not_exist_fails(tree: Path) -> None:
    _write(tree, f"# see docs/limitations.md §{_ABSENT_SECTION}\n")
    result = check_section_citations_resolve(tree, tree / "docs")
    assert result.verdict == DISAGREE
    assert f"§{_ABSENT_SECTION}" in result.detail


def test_a_citation_into_a_document_that_does_not_exist_fails(tree: Path) -> None:
    _write(tree, f"# see docs/{_ABSENT_DOC} §1\n")
    result = check_section_citations_resolve(tree, tree / "docs")
    assert result.verdict == DISAGREE
    assert _ABSENT_DOC in result.detail


def test_a_citation_into_a_document_that_numbers_nothing_cannot_be_evaluated(
    tree: Path,
) -> None:
    (tree / "docs" / _UNNUMBERED_DOC).write_text(
        "# Flat\n\n## Why\n\nprose\n", encoding="utf-8"
    )
    _write(tree, f"# see docs/{_UNNUMBERED_DOC} §2\n")
    result = check_section_citations_resolve(tree, tree / "docs")
    assert result.verdict == COULD_NOT_EVALUATE
    assert "no numbered sections" in result.detail


def test_no_sources_cannot_be_evaluated(tree: Path) -> None:
    """The source roots exist and hold nothing. Nothing is not agreement."""
    assert (
        check_section_citations_resolve(tree, tree / "docs").verdict
        == COULD_NOT_EVALUATE
    )
    assert check_no_citation_into_a_retired_place(tree).verdict == COULD_NOT_EVALUATE


def test_no_documents_cannot_be_evaluated(tree: Path) -> None:
    _write(tree, "# see docs/limitations.md §12\n")
    (tree / "docs" / "limitations.md").unlink()
    assert (
        check_section_citations_resolve(tree, tree / "docs").verdict
        == COULD_NOT_EVALUATE
    )


def test_sources_that_cite_nothing_cannot_be_evaluated(tree: Path) -> None:
    _write(tree, "# a module that points at no document\n")
    result = check_section_citations_resolve(tree, tree / "docs")
    assert result.verdict == COULD_NOT_EVALUATE
    assert "no section citations" in result.detail


def test_an_empty_retired_list_cannot_be_evaluated(
    tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(tree, "# a module\n")
    monkeypatch.setattr(sys.modules[__name__], "RETIRED_PLACES", ())
    result = check_no_citation_into_a_retired_place(tree)
    assert result.verdict == COULD_NOT_EVALUATE


#: The retired shapes and the surviving ones are assembled from these rather
#: than written out, because the checks above read this file like any other and
#: a literal example here would make the guard its own first violation.
_CUT_DOC = "self-" + "describing.md"
_QUESTION = "question"

#: Real citations, as they stood at `1e662d6`, before issue #274 re-aimed them.
RETIRED_EXAMPLES = (
    f"# input under it is the assertion docs/{_CUT_DOC} gap 1 is\n",
    f"# GEOS and the platform (issue #200, docs/{_CUT_DOC} gap 2).\n",
    f'    "(`docs/{_CUT_DOC}` gap 1). The two options below are the two",\n',
    f"# and §7 {_QUESTION} 1 asks at what granularity: **per edge**\n",
    f"# docs/{_CUT_DOC} §7 {_QUESTION} 2).\n",
)

#: Citations the cut keeps, which the same scan has to leave alone. A check
#: that flagged these would push the next agent into re-aiming a live pointer.
SURVIVING_EXAMPLES = (
    f"# environment too (docs/{_CUT_DOC} §7 {_QUESTION} 3 holds that).\n",
    f"# THE LAYER BASIS (issue #252, tier 4 of docs/{_CUT_DOC} §8).\n",
    f"# THE COLD READ (issue #231, docs/{_CUT_DOC} §2 and §8 tier 3).\n",
    "# THE LAYER BASIS (issue #252, docs/limitations.md §12 gap 1).\n",
)


@pytest.mark.parametrize("body", RETIRED_EXAMPLES)
def test_a_citation_into_a_retired_place_fails(tree: Path, body: str) -> None:
    _write(tree, body)
    result = check_no_citation_into_a_retired_place(tree)
    assert result.verdict == DISAGREE
    assert "point it at" in result.detail


@pytest.mark.parametrize("body", SURVIVING_EXAMPLES)
def test_a_citation_that_survives_the_cut_is_not_flagged(tree: Path, body: str) -> None:
    _write(tree, body)
    assert check_no_citation_into_a_retired_place(tree).verdict == AGREE
