"""The air-gap premise, retired — and pinned so it cannot come back (issue #102).

WHAT THIS GUARDS
----------------
The repository used to carry an unsourced empirical claim about how the target
deployments are run — *full sensor logs cannot leave an air-gapped site* — and it
carried it **backwards**: as a site constraint the design works around, which
"ruled out" a third-party timestamp. These sites are not isolated. They are
heavily instrumented and their telemetry already flows to a cloud the operator
runs, which is the *reason* an assessor needs a record whose integrity does not
rest on that infrastructure, not an obstacle to producing one.

So the claim was split in two and both halves were moved:

* **The empirical half is retired.** The retention argument turns on volume and a
  retention floor, both of which hold on a site with a fibre uplink. The
  retirement — and what evidence would bring the premise back — is recorded in
  `docs/sensor-baseline.md`, the document where every input to that argument
  carries a source, a range and a sensitivity.
* **The requirement half is stated as a requirement.** Off-network verifiability
  — one self-contained file, checkable years later with no service still running
  and no call to anyone — is a property this artifact must have. It is why RFC
  3161 and transparency-log commitment are documented and deliberately
  unimplemented (`docs/limitations.md` §6, `reg/commit.py`).

Prose does not fail, and this is exactly the kind of framing that drifts back one
sentence at a time. Two checks, in the two directions the defect had:

* **Nowhere else says it.** Every mention of air-gapping in the corpus must be
  inside the passage that records the premise as retired. A sentence that
  reintroduces it anywhere — as a fact, as a constraint, as an aside — fails.
* **The refusal names the right reason.** Every paragraph that refuses a network
  call at artifact close must state the requirement in that same paragraph. A
  paragraph three sections away is not a reason a reader of the refusal sees, and
  the original defect was precisely a refusal whose stated reason was the
  inverted premise.

THREE-VALUED, AND THE THIRD NEVER RESOLVES TO THE FIRST
-------------------------------------------------------
Both checks are defeated the same way: delete the thing being checked. A corpus
that mentions air-gapping nowhere *at all* has also lost the record of why, and
comes back COULD-NOT-EVALUATE rather than AGREE; so does a corpus with no
refusal paragraph left to inspect. The two tests against the real repository
assert against both of those verdicts, separately, so a deletion is visible as
itself rather than as a pass.

`tests/` IS NOT IN THE CORPUS
-----------------------------
This file has to contain the sentences it forbids in order to feed them to the
predicates below, and a check that failed on its own negative fixtures would be
deleted rather than fixed. The corpus is the documents and the package: the
places a reader of this project actually reads.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from reg.commit import COMMITMENT_STATEMENT

REPO = Path(__file__).resolve().parent.parent

AGREE = "AGREE"
DISAGREE = "DISAGREE"
COULD_NOT_EVALUATE = "COULD-NOT-EVALUATE"

#: Every spelling of the premise, including the ones a paraphrase would reach
#: for. Matched case-insensitively: `air-gapped`, `air gap`, `airgapping`.
AIR_GAP = re.compile(r"\bair[\s\-_]?gap(?:ped|ping|s)?\b", re.IGNORECASE)

#: Where the retirement is recorded. One document, by design: the issue's
#: complaint was that the premise lived in two registers at once.
RETIREMENT_FILE = "docs/sensor-baseline.md"

#: The word that makes the record a retirement rather than a restatement. A
#: section that names the premise and does not say it is retired is a section
#: that still asserts it.
RETIRED = re.compile(r"\bretired\b", re.IGNORECASE)

#: A refusal to make a network call when the artifact closes. This is the
#: sentence RFC 3161 and transparency-log commitment are rejected in.
NETWORK_CALL = re.compile(r"network call", re.IGNORECASE)

#: The reason that refusal is allowed to give: a property of the artifact, not a
#: property of the site. Phrased as the repository phrases it, and required in
#: the same paragraph as the refusal.
REQUIREMENT = re.compile(r"no service still running", re.IGNORECASE)


def corpus() -> dict[str, str]:
    """Every file a reader of this project reads, keyed by repo-relative path.

    Globbed rather than listed: the document added next milestone is inside this
    check on the day it is written. `tests/` is excluded and the module docstring
    says why.
    """
    paths = [
        *(REPO / "docs").glob("*.md"),
        *(REPO / "reg").glob("*.py"),
        *(REPO / "scripts").glob("*.py"),
        *REPO.glob("*.md"),
    ]
    return {
        path.relative_to(REPO).as_posix(): path.read_text(encoding="utf-8")
        for path in sorted(paths)
    }


def sections(text: str) -> list[str]:
    """The document split at its markdown headings, heading kept with its body."""
    return [part for part in re.split(r"\n(?=#{1,6} )", text) if part.strip()]


def paragraphs(text: str) -> list[str]:
    return [part for part in re.split(r"\n\s*\n", text) if part.strip()]


def retirement_record(text: str) -> str:
    """The section of the retirement document whose *heading* names the premise.

    Found by what its heading says, not by its position: sections get moved and
    renumbered, and a check keyed on an ordinal would go green on a file where
    that ordinal had become something else.
    """
    for section in sections(text):
        heading = section.split("\n", 1)[0]
        if AIR_GAP.search(heading):
            return section
    return ""


def mentions(text: str) -> list[str]:
    """Every line of `text` that names the premise, stripped."""
    return [line.strip() for line in text.splitlines() if AIR_GAP.search(line)]


def air_gap_is_only_named_where_it_is_retired(
    sources: dict[str, str],
) -> tuple[str, list[str]]:
    """Verdict on whether the premise survives anywhere as an assertion.

    AGREE when every mention in the corpus is inside the retirement record.
    DISAGREE names the file and line of each one that is not.
    COULD-NOT-EVALUATE when the retirement record is missing or no longer says
    the premise is retired — because at that point the corpus is silent about a
    claim it used to make, and silence is not the same finding as consistency.
    """
    record = retirement_record(sources.get(RETIREMENT_FILE, ""))
    if not record or not RETIRED.search(record):
        return COULD_NOT_EVALUATE, []
    stray: list[str] = []
    for name, text in sorted(sources.items()):
        body = text.replace(record, "") if name == RETIREMENT_FILE else text
        stray += [f"{name}: {line}" for line in mentions(body)]
    return (DISAGREE if stray else AGREE), stray


def the_refusal_states_the_requirement(
    sources: dict[str, str],
) -> tuple[str, list[str]]:
    """Verdict on the reason given for not calling a network at artifact close.

    Every paragraph that mentions a network call has to name the property that
    refusal protects, *in that paragraph*. COULD-NOT-EVALUATE when no paragraph
    in the corpus refuses one at all: deleting the refusal is the other way a
    check of this shape is defeated.
    """
    checked = 0
    silent: list[str] = []
    for name, text in sorted(sources.items()):
        for paragraph in paragraphs(text):
            if not NETWORK_CALL.search(paragraph):
                continue
            checked += 1
            if not REQUIREMENT.search(paragraph):
                silent.append(f"{name}: {' '.join(paragraph.split())[:120]}")
    if not checked:
        return COULD_NOT_EVALUATE, []
    return (DISAGREE if silent else AGREE), silent


# --------------------------------------------------------------------------
# The repository as it stands.
# --------------------------------------------------------------------------


def test_the_premise_is_named_nowhere_but_in_its_own_retirement() -> None:
    """**THE CHECK THIS ISSUE EXISTS FOR.**

    One mention, in one register: the passage that records the premise as
    retired. Anything else is the claim coming back.
    """
    verdict, stray = air_gap_is_only_named_where_it_is_retired(corpus())
    assert verdict != DISAGREE, (
        "the air-gap premise is asserted outside its retirement record:\n  "
        + "\n  ".join(stray)
        + f"\n\nIt is an unsourced empirical claim about how the target sites are "
        f"run (issue #102). Either retire the sentence, or source it in "
        f"{RETIREMENT_FILE} with a range and a sensitivity the way every other "
        "input to the retention argument is sourced. Off-network verifiability "
        "is a separate claim and is stated as a requirement, not as a site fact."
    )


def test_the_retirement_record_is_still_in_the_document_that_holds_it() -> None:
    """**SILENCE IS NOT A PASS.**

    The test above goes green on a corpus that says nothing about air-gapping at
    all — including one where somebody deleted the passage explaining why. This
    is what stops "nothing to check" from becoming the state of the record.
    """
    verdict, _ = air_gap_is_only_named_where_it_is_retired(corpus())
    assert verdict != COULD_NOT_EVALUATE, (
        f"{RETIREMENT_FILE} no longer has a section whose heading names the "
        "air-gap premise and whose body says it is retired. That record is what "
        "stops the premise being reintroduced by somebody who never knew it had "
        "been examined (issue #102)."
    )


def test_every_refusal_of_a_network_call_names_the_requirement_it_protects() -> None:
    verdict, silent = the_refusal_states_the_requirement(corpus())
    assert verdict != DISAGREE, (
        "a network call at artifact close is refused without naming what that "
        "refusal protects:\n  " + "\n  ".join(silent) + "\n\nThe reason is that "
        "the artifact must be checkable years later with no service still "
        "running and no call to anyone — a property it must have, not a "
        "constraint imposed by an isolated site."
    )


def test_there_is_still_a_refusal_to_check() -> None:
    """The other deletion. RFC 3161 and transparency-log commitment are refused
    somewhere in this corpus; if they stop being, this check has silently become
    vacuous rather than satisfied."""
    verdict, _ = the_refusal_states_the_requirement(corpus())
    assert verdict != COULD_NOT_EVALUATE, (
        "no paragraph in the corpus refuses a network call at artifact close. "
        "Either the refusal moved and this check now inspects nothing, or the "
        "project has taken the dependency and `docs/limitations.md` §6 is stale."
    )


def test_the_artifact_states_the_requirement_and_not_the_site_fact() -> None:
    """The statement the artifact itself carries, in `meta`.

    An assessor reading the file gets `COMMITMENT_STATEMENT` and nothing else.
    It has to give the reason a timestamp is absent, and it must not give the
    reason that was wrong — the one this project shipped until issue #102.
    """
    assert REQUIREMENT.search(COMMITMENT_STATEMENT) is not None
    assert AIR_GAP.search(COMMITMENT_STATEMENT) is None


# --------------------------------------------------------------------------
# THE NEGATIVES. Each is the condition the check exists to catch, fed to it.
# --------------------------------------------------------------------------

#: A retirement document that satisfies the anchor, so the negatives below vary
#: exactly one thing: what the *rest* of the corpus says.
_RECORD = (
    "# The sensor-log baseline\n\n"
    "Body.\n\n"
    "## A premise this document does not carry: air-gapped sites\n\n"
    "It is retired rather than sourced, because the argument does not need it.\n\n"
    "## What would retire this document\n\nBody.\n"
)


def test_the_old_thesis_sentence_is_caught() -> None:
    """The sentence `docs/plan.md` carried until issue #102, verbatim."""
    verdict, stray = air_gap_is_only_named_where_it_is_retired(
        {
            RETIREMENT_FILE: _RECORD,
            "docs/plan.md": (
                "Full sensor logs from a humanoid are terabytes/day and cannot "
                "leave an air-gapped site.\n"
            ),
        }
    )
    assert verdict == DISAGREE
    assert any("docs/plan.md" in item for item in stray)


def test_the_inverted_premise_is_caught() -> None:
    """The other half of the defect: the premise used to *rule something out*."""
    verdict, stray = air_gap_is_only_named_where_it_is_retired(
        {
            RETIREMENT_FILE: _RECORD,
            "reg/commit.py": (
                "# both need a network call at artifact close, which this "
                "project's\n# air-gapped operation rules out.\n"
            ),
        }
    )
    assert verdict == DISAGREE
    assert any("reg/commit.py" in item for item in stray)


def test_a_mention_in_the_retirement_document_but_outside_the_record_is_caught() -> None:
    """The subtle one. The document that retires the premise is still allowed to
    assert it somewhere else on the page unless the check is scoped to the
    section, and a reader who lands on the assertion never sees the retirement."""
    verdict, stray = air_gap_is_only_named_where_it_is_retired(
        {RETIREMENT_FILE: _RECORD + "\n## Sources\n\nThese sites are air-gapped.\n"}
    )
    assert verdict == DISAGREE
    assert stray == [f"{RETIREMENT_FILE}: These sites are air-gapped."]


def test_deleting_the_retirement_record_does_not_pass() -> None:
    """A corpus with no mention anywhere — including no record of why."""
    verdict, stray = air_gap_is_only_named_where_it_is_retired(
        {RETIREMENT_FILE: "# The sensor-log baseline\n\nBody.\n", "docs/plan.md": "Body.\n"}
    )
    assert verdict == COULD_NOT_EVALUATE
    assert stray == []


def test_a_record_that_names_the_premise_without_retiring_it_does_not_pass() -> None:
    """The heading is there, the retirement is not. That is the premise restated
    under a heading, which is the failure mode of a check keyed on a heading."""
    verdict, _ = air_gap_is_only_named_where_it_is_retired(
        {
            RETIREMENT_FILE: (
                "# The sensor-log baseline\n\n"
                "## Air-gapped sites\n\nThese deployments are isolated.\n"
            )
        }
    )
    assert verdict == COULD_NOT_EVALUATE


def test_a_refusal_that_gives_the_old_reason_is_caught() -> None:
    """The paragraph as it read until issue #102."""
    verdict, silent = the_refusal_states_the_requirement(
        {
            "docs/limitations.md": (
                "Both are documented and deliberately unimplemented for one "
                "reason: each needs a network call at artifact close, and the "
                "README claims isolated operation.\n"
            )
        }
    )
    assert verdict == DISAGREE
    assert any("docs/limitations.md" in item for item in silent)


def test_a_requirement_stated_three_paragraphs_away_is_not_stated() -> None:
    """Paragraph-scoped on purpose. A reader of the refusal reads the refusal."""
    verdict, _ = the_refusal_states_the_requirement(
        {
            "docs/plan.md": (
                "Both need a network call at artifact close.\n\n"
                "Some other paragraph.\n\n"
                "The artifact is checkable with no service still running.\n"
            )
        }
    )
    assert verdict == DISAGREE


def test_a_corpus_with_no_refusal_left_does_not_pass() -> None:
    verdict, silent = the_refusal_states_the_requirement({"docs/plan.md": "Body.\n"})
    assert verdict == COULD_NOT_EVALUATE
    assert silent == []


@pytest.mark.parametrize(
    "spelling",
    ["air-gapped", "air gapped", "airgapped", "Air-Gap", "air-gaps", "air_gap"],
)
def test_the_premise_is_caught_however_it_is_spelled(spelling: str) -> None:
    """A paraphrase is the cheapest way past a check of this shape."""
    verdict, _ = air_gap_is_only_named_where_it_is_retired(
        {RETIREMENT_FILE: _RECORD, "README.md": f"The site is {spelling}.\n"}
    )
    assert verdict == DISAGREE
