"""The personal-data disclosure, pinned to the schema it describes (issue #101).

WHAT THIS GUARDS
----------------
`docs/limitations.md` §8 states that the artifact contains personal data, names
the obligations that creates, and offers a **minimisation contract**: the entity
side of the schema carries no identifier, and the identifying fields are three
declared strings in `meta`. Prose does not fail, and a minimisation contract
written in prose is exactly the kind of claim that goes quietly stale — the day
somebody adds `entity.worker_name` or a fourth field to `RunIdentity`, the
disclosure is wrong and nothing says so.

So the checks here run in two directions:

* **Schema -> document.** Every column of the real `entity` table and every
  field of the real `RunIdentity` must be named in the disclosure. A new
  identifying column fails this test, and the way to green it is to disclose the
  column or not to add it. This is the half that makes "data-minimising almost
  by accident" into something with a tripwire under it.
* **Document -> obligations.** The disclosure must still name the things issue
  #101 required it to name: the Art. 19 / Art. 26(6) subordination proviso, Art.
  26(7), the DPIA, §87(1)(6) BetrVG, and the fact that retention is therefore
  bounded from both sides. `docs/plan.md` must carry the proviso where it frames
  the six-month floor, and `docs/prior-art.md` §9 must state the DSSAD
  privacy-profile inversion where it claims the DSSAD alignment.

And one check runs the other way round: **no claim of compliance and no legal
advice.** That was an explicit acceptance criterion, and it is the failure mode
a document of this kind actually has — a sentence that reads as reassurance is
worse than the silence it replaced.

WHAT THE ARTIFACT ITSELF NOW SAYS, AND WHAT IT STILL CANNOT
-----------------------------------------------------------
The disclosure named those obligations in prose while the file was silent, so an
assessor holding one could not separate *a notice given and no key recording it*
from *none given*. Three `meta` keys close that (issue #125), and three more
checks here hold the pair together:

* **The section names the keys.** They join the meta identifiers in the
  schema -> document direction, so renaming one without disclosing the new name
  fails exactly as adding an `entity` column would.
* **The section says recording is not discharging, and keeps the retention basis
  stated as a gap.** Both are acceptance criteria of #125 and both are the kind
  of sentence that quietly goes missing in an edit; a §8 that reads as though
  the obligations had been met is the failure this whole module exists against.
* **The vocabulary claims nothing.** The key names and every value they may take
  are scanned for a term that reads as a legal conclusion — the same direction
  as `test_a_compliance_claim_is_caught`, applied to the schema rather than to
  the prose, because `meta[worker_notice] = lawful-basis-established` would be a
  compliance claim in a place no document check would ever look.

THREE-VALUED, LIKE EVERY OTHER CHECK HERE
-----------------------------------------
A missing section, an empty document and a schema that could not be read are
**COULD-NOT-EVALUATE**, never AGREE (CLAUDE.md, `docs/CONTRIBUTING.md`). Deleting
§7 must not be a way to pass the test that §7 exists, which is precisely how a
grep-shaped check gets defeated.
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Sequence
from pathlib import Path

import pytest

from reg import graph, store
from reg.identity import (
    DPIA_NONE,
    OperatorIdKind,
    RunIdentity,
    WorkerNoticeStatus,
)

REPO = Path(__file__).resolve().parent.parent
LIMITATIONS = REPO / "docs" / "limitations.md"
PLAN = REPO / "docs" / "plan.md"
PRIOR_ART = REPO / "docs" / "prior-art.md"

AGREE = "AGREE"
DISAGREE = "DISAGREE"
COULD_NOT_EVALUATE = "COULD-NOT-EVALUATE"

#: The disclosure is found by what it says, not by its number. Sections get
#: renumbered; a check keyed on "§7" would go quietly green on a file where §7
#: had become something else entirely.
DISCLOSURE_HEADING = re.compile(
    r"^##\s+\d+\.\s+.*personal data.*$", re.IGNORECASE | re.MULTILINE
)

#: The DSSAD alignment lives in `prior-art.md` §9, and the inversion has to be
#: stated there rather than only in `limitations.md` — a reader who takes the
#: element-by-element mapping at face value never reaches the other file.
PRIOR_ART_SECTION_9 = re.compile(r"^##\s+9\.\s", re.MULTILINE)
NEXT_H2 = re.compile(r"^##\s", re.MULTILINE)

#: What issue #101 required the disclosure to name. The label is what a failure
#: message says is missing; nobody should have to read the regex to find out.
OBLIGATIONS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("the artifact contains personal data", re.compile(r"contains personal data", re.I)),
    ("GDPR, by name", re.compile(r"\bGDPR\b")),
    ("AI Act Art. 19", re.compile(r"\bArt(?:icle)?\.\s*19\b")),
    ("AI Act Art. 26(6)", re.compile(r"\b26\(6\)")),
    (
        "the Art. 19 / 26(6) subordination proviso, quoted",
        re.compile(
            r"in particular Union law on the protection of personal data", re.I
        ),
    ),
    ("retention bounded from both sides, not only a floor", re.compile(r"\bceiling\b", re.I)),
    ("AI Act Art. 26(7)", re.compile(r"\b26\(7\)")),
    ("the DPIA obligation", re.compile(r"\bDPIA\b")),
    ("GDPR Art. 35", re.compile(r"\bArt(?:icle)?\.\s*35\b")),
    ("§87(1)(6) BetrVG", re.compile(r"87\(1\)\(6\).{0,20}BetrVG", re.S)),
    ("that the obligations are unaddressed here", re.compile(r"not (?:discharge|addressed)", re.I)),
)

#: A sentence that reads as reassurance. `complies with` and `compliant` are the
#: two ways this document could stop being a statement of a gap; "is legal
#: advice" is the third, and all three are negatable, which is why the negation
#: scan below exists rather than a bare substring test.
CLAIM_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("a compliance claim", re.compile(r"\bcompl(?:ies|y|ying)\s+with\b", re.I)),
    ("a compliance claim", re.compile(r"\b(?:is|are|becomes?|remains?)\s+(?:fully\s+|GDPR[-\s])?compliant\b", re.I)),
    ("a claim to give legal advice", re.compile(r"\b(?:is|are|constitutes?)\s+legal advice\b", re.I)),
)

#: The words that turn one of the above into a disclaimer. Scanned backwards to
#: the start of the sentence, because "nothing here is legal advice" and "this
#: is legal advice" differ by exactly one of them.
NEGATIONS = re.compile(r"\b(?:no|not|nothing|never|neither|nor|without)\b", re.I)


# --------------------------------------------------------------------------
# Reading the documents and the schema
# --------------------------------------------------------------------------


def normalise(text: str) -> str:
    """Strip markdown emphasis and collapse whitespace, nothing else.

    Close to the treatment `tests/test_readme.py` gives a figure, and for the
    same reason: a quoted proviso that wraps across two lines, or that carries a
    `**bold**` inside it, is the same sentence, and a check that disagreed would
    be a check on the line wrapping. The underscore is **not** stripped here,
    unlike there — half of what this file looks for is `operator_id`.
    """
    return re.sub(r"\s+", " ", re.sub(r"[*`~]", "", text))


def read(path: Path) -> str:
    """The document, or `""` if it cannot be read — which is a refusal, not a pass."""
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def disclosure(text: str) -> str:
    """The personal-data section of `limitations.md`, heading to next heading."""
    match = DISCLOSURE_HEADING.search(text)
    if match is None:
        return ""
    rest = text[match.end() :]
    following = NEXT_H2.search(rest)
    return text[match.start() :] if following is None else text[match.start() : match.end() + following.start()]


def prior_art_section_9(text: str) -> str:
    """`prior-art.md` §9 — the DSSAD data model — heading to next `##`."""
    match = PRIOR_ART_SECTION_9.search(text)
    if match is None:
        return ""
    rest = text[match.end() :]
    following = NEXT_H2.search(rest)
    return text[match.start() :] if following is None else text[match.start() : match.end() + following.start()]


def entity_columns(tmp_path: Path) -> tuple[str, ...]:
    """The `entity` table's columns, from a real artifact rather than from a list.

    Through `store.create` on purpose: a hand-written expectation here would be
    a second copy of the schema, and the whole point is to notice when the
    schema moves out from under the document.
    """
    conn = store.create(tmp_path / "schema.sqlite", record_tables=False)
    try:
        return tuple(row[1] for row in conn.execute("PRAGMA table_info(entity)"))
    finally:
        conn.close()


def identity_fields() -> tuple[str, ...]:
    """Every field of `RunIdentity` — the identifiers a run is required to declare."""
    return tuple(field.name for field in dataclasses.fields(RunIdentity))


#: The `meta` keys the identifiers land under, taken from `reg.graph` rather
#: than spelled here: renaming a key without disclosing the new name is the
#: same defect as adding one.
META_IDENTIFIERS = (graph.META_UNIT_ID, graph.META_OPERATOR_ID, graph.META_RUN_START)

#: The three keys the deployer states about the obligations §8 names (issue
#: #125), taken from `reg.graph` for the same reason: a key the artifact writes
#: and the disclosure does not name is a fact in the file that nothing tells a
#: reader how to read.
META_DISCLOSURES = (
    graph.META_WORKER_NOTICE,
    graph.META_DPIA_REFERENCE,
    graph.META_OPERATOR_ID_KIND,
)

#: What §8 has to keep saying now that the artifact carries those three keys.
#: Both halves are acceptance criteria of issue #125: a section that recorded
#: the keys and stopped saying the obligations are undischarged would read as
#: though the gap had closed, and the retention basis is the one fact of the
#: four that stays unbuilt — stated as a gap rather than silently dropped.
RECORDS_AND_STILL_OWES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("that recording is not discharging", re.compile(r"recording is not discharging", re.I)),
    (
        "that the retention basis is still a gap",
        re.compile(r"(gap|cannot say what basis|no key for it)", re.I),
    ),
    (
        "why the basis is not built — a legal determination this project cannot make",
        re.compile(r"legal determination", re.I),
    ),
    (
        "that an artifact with no basis cannot be assessed against either bound",
        re.compile(r"against either bound", re.I),
    ),
)

#: A term that reads as a legal conclusion. Scanned over the **vocabulary** —
#: the key names and every value they may take — rather than over prose, so it
#: is a word list and not the sentence patterns above: a value has no sentence
#: around it to negate a claim, and `dpia_reference = compliant` would be a
#: claim of compliance sitting in `meta` where no document check would find it.
#: `pseudonym` is deliberately absent from this list and `pseudonymised` is
#: deliberately in it: the first describes an identifier, the second names a
#: GDPR Art. 4(5) measure and reads as a claim to have taken one.
CLAIM_TERMS = re.compile(
    r"(compliant|compliance|complies|lawful|legal|permitted|authoris|authoriz|"
    r"approved|certified|exempt|waived|discharged|satisfied|anonymous|anonymis|"
    r"anonymiz|pseudonymis|pseudonymiz|consent)",
    re.IGNORECASE,
)


def disclosure_vocabulary() -> tuple[str, ...]:
    """Every token the three disclosure keys can put in an artifact.

    Derived from the enums rather than listed here, so a member added later is
    scanned without anyone remembering to add it — which is the only version of
    this check that stays true.
    """
    return (
        *META_DISCLOSURES,
        *(member.value for member in WorkerNoticeStatus),
        *(member.value for member in OperatorIdKind),
        DPIA_NONE,
    )


def check_vocabulary_claims_nothing(terms: Sequence[str]) -> tuple[str, list[str]]:
    """Verdict on whether any key or value reads as a legal conclusion.

    An empty vocabulary is COULD-NOT-EVALUATE: a scan over nothing finds
    nothing, and reporting that as a pass is how this check would die the day
    the enums moved.
    """
    if not terms:
        return COULD_NOT_EVALUATE, ["no vocabulary to scan"]
    found = [term for term in terms if CLAIM_TERMS.search(term)]
    return (DISAGREE, [f"{term!r} reads as a legal conclusion" for term in found]) if found else (AGREE, [])


def check_records_and_still_owes(section: str) -> tuple[str, list[str]]:
    """Verdict on whether §8 states what the keys do and do not settle."""
    if not section.strip():
        return COULD_NOT_EVALUATE, ["no personal-data section in docs/limitations.md"]
    flat = normalise(section)
    missing = [label for label, pattern in RECORDS_AND_STILL_OWES if not pattern.search(flat)]
    return (DISAGREE, missing) if missing else (AGREE, [])


# --------------------------------------------------------------------------
# The checks
# --------------------------------------------------------------------------


def check_disclosure(
    section: str,
    *,
    columns: tuple[str, ...],
    fields: tuple[str, ...],
    meta_keys: tuple[str, ...],
) -> tuple[str, list[str]]:
    """Verdict on whether the disclosure still describes the schema it claims to.

    Returns the verdict and everything missing. No section, or nothing to
    compare it against, is COULD-NOT-EVALUATE: a check that reports *pass* on an
    absent document is not a check.
    """
    if not section.strip():
        return COULD_NOT_EVALUATE, ["no personal-data section in docs/limitations.md"]
    if not columns or not fields or not meta_keys:
        return COULD_NOT_EVALUATE, ["the schema could not be read, so nothing was compared"]

    section = normalise(section)
    missing = [label for label, pattern in OBLIGATIONS if not pattern.search(section)]
    missing += [
        f"`entity` column {column!r} is not disclosed" for column in columns if column not in section
    ]
    missing += [
        f"`RunIdentity` field {field!r} is not disclosed" for field in fields if field not in section
    ]
    # Whole-token, unlike the two loops above: `operator_id_kind` contains
    # `operator_id`, so a plain substring test would let a section that named
    # only the longer key pass for the shorter one — a disclosure gap that
    # arrived *because* a key was added, which is the failure this loop guards.
    missing += [
        f"meta key {key!r} is not disclosed"
        for key in meta_keys
        if re.search(rf"(?<!\w){re.escape(key)}(?!\w)", section) is None
    ]
    return (DISAGREE if missing else AGREE), missing


def sentence_start(text: str, index: int) -> int:
    """Where the sentence containing `index` begins. Paragraph breaks count."""
    boundary = max(text.rfind(mark, 0, index) for mark in (". ", ".\n", "\n\n", "! ", "? "))
    return 0 if boundary < 0 else boundary


def check_no_compliance_claim(section: str) -> tuple[str, list[str]]:
    """Verdict on whether the disclosure keeps out of the reassurance business.

    Every hit is read in its sentence: this file has to be able to say *"nothing
    here is legal advice"* without that sentence being the violation.
    """
    if not section.strip():
        return COULD_NOT_EVALUATE, ["no section to read"]
    found = []
    for label, pattern in CLAIM_PATTERNS:
        for match in pattern.finditer(section):
            lead = section[sentence_start(section, match.start()) : match.start()]
            if NEGATIONS.search(lead) is None:
                found.append(f"{label}: {section[match.start() : match.end() + 20]!r}")
    return (DISAGREE if found else AGREE), found


def check_proviso(text: str, *, where: str) -> tuple[str, list[str]]:
    """Verdict on whether a document carries the subordination proviso at all."""
    if not text.strip():
        return COULD_NOT_EVALUATE, [f"{where} could not be read"]
    flat = normalise(text)
    proviso = re.search(r"in particular Union law on the protection of personal data", flat, re.I)
    pointer = re.search(r"limitations\.md", flat)
    missing = []
    if proviso is None:
        missing.append(f"{where} does not quote the Art. 19 / 26(6) data-protection proviso")
    if pointer is None:
        missing.append(f"{where} does not point at the disclosure")
    return (DISAGREE if missing else AGREE), missing


def check_inversion(section: str) -> tuple[str, list[str]]:
    """Verdict on whether §9 states the privacy-profile inversion beside the mapping."""
    if not section.strip():
        return COULD_NOT_EVALUATE, ["prior-art.md §9 not found"]
    required = (
        ("the word privacy", re.compile(r"\bprivacy\b", re.I)),
        ("that the profile inverts", re.compile(r"\binvert", re.I)),
        ("what DSSAD records instead", re.compile(r"\bDSSAD\b")),
        ("the entry into the disclosure", re.compile(r"limitations\.md")),
    )
    flat = normalise(section)
    missing = [label for label, pattern in required if not pattern.search(flat)]
    return (DISAGREE if missing else AGREE), missing


# --------------------------------------------------------------------------
# The documents as they stand
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def limitations() -> str:
    return read(LIMITATIONS)


def test_the_disclosure_describes_the_schema_that_exists(
    limitations: str, tmp_path: Path
) -> None:
    verdict, missing = check_disclosure(
        disclosure(limitations),
        columns=entity_columns(tmp_path),
        fields=identity_fields(),
        meta_keys=META_IDENTIFIERS + META_DISCLOSURES,
    )
    assert verdict == AGREE, (
        "docs/limitations.md's personal-data section no longer matches what the "
        "artifact records, or no longer names an obligation issue #101 required: "
        + "; ".join(missing)
    )


def test_the_disclosure_claims_no_compliance_and_gives_no_advice(limitations: str) -> None:
    verdict, found = check_no_compliance_claim(disclosure(limitations))
    assert verdict == AGREE, (
        "the personal-data section reads as reassurance rather than as a "
        "statement of a gap, which issue #101 excluded explicitly: " + "; ".join(found)
    )


def test_the_plan_frames_the_retention_floor_as_subordinate() -> None:
    verdict, missing = check_proviso(read(PLAN), where="docs/plan.md")
    assert verdict == AGREE, "; ".join(missing)


def test_the_dssad_alignment_states_the_privacy_inversion() -> None:
    verdict, missing = check_inversion(prior_art_section_9(read(PRIOR_ART)))
    assert verdict == AGREE, (
        "docs/prior-art.md §9 claims the DSSAD alignment without stating that "
        "`reg` inverts its privacy profile: " + "; ".join(missing)
    )


def test_the_disclosure_says_what_the_artifact_records_and_still_owes(
    limitations: str,
) -> None:
    """Both halves of issue #125's acceptance criteria, in one verdict.

    The section has to say that the three keys record rather than discharge, and
    it has to keep the retention basis stated as a gap with the reason it is one.
    A §8 that carried the keys and dropped either sentence would read as though
    the obligations had been met, which is the exact inversion this file exists
    against — and it is a plausible edit, because the keys look like progress.
    """
    verdict, missing = check_records_and_still_owes(disclosure(limitations))
    assert verdict == AGREE, (
        "docs/limitations.md's personal-data section carries the three keys but "
        "no longer states what they settle and what they do not: "
        + "; ".join(missing)
    )


def test_no_disclosure_key_or_value_reads_as_a_legal_conclusion() -> None:
    """The vocabulary an artifact can contain, scanned for a compliance claim.

    Issue #125 required that no key imply a legal conclusion. The keys and their
    values are where that would land without any document check noticing: a
    `meta` value is read by whoever opens the file, and there is no sentence
    around it to carry a disclaimer. Derived from the enums, so a fourth
    `WorkerNoticeStatus` is scanned the day it is added.
    """
    verdict, found = check_vocabulary_claims_nothing(disclosure_vocabulary())
    assert verdict == AGREE, (
        "a disclosure key or value reads as a claim about the law rather than "
        "as a statement of fact: " + "; ".join(found)
    )


def test_the_disclosure_names_the_minimisation_it_relies_on(limitations: str) -> None:
    """The contract is only worth pinning if it says what it is."""
    section = disclosure(limitations)
    assert "minimis" in section.lower(), (
        "the section states the obligation but not the minimisation already "
        "implicit in the schema, which is half of what issue #101 asked for"
    )


# --------------------------------------------------------------------------
# The negatives: every check above, fed the condition it guards against
# --------------------------------------------------------------------------


#: A disclosure that would pass, used as the base for the mutations below. Kept
#: minimal on purpose — it is not a copy of the real section, it is the least
#: text that satisfies every requirement, so a mutation removes exactly one
#: thing.
GOOD = """## 7. The artifact contains personal data and this project has not addressed that

Nothing here is legal advice. The artifact contains personal data: meta[unit_id],
meta[operator_id] and meta[run_start_utc], the run_start it parses, and the
entity table's entity_key, kind, is_static and geometry_wkb columns, none of
which names a person. That minimisation is in the schema.

GDPR applies. Art. 19 and Art. 26(6) set six months "unless provided otherwise
in applicable Union or national law, in particular Union law on the protection
of personal data", so the window may be a ceiling as well as a floor. Art. 26(7)
and a DPIA under GDPR Art. 35 are named here and this project does not discharge
them, nor does §87(1)(6) BetrVG go addressed.

What the deployer states, each required with no default: meta[worker_notice],
meta[dpia_reference] and meta[operator_id_kind]. Recording is not discharging.
The basis the file is kept under has no key, because naming it is a legal
determination this project has no standing to make, and an artifact that cannot
say what basis it was retained under cannot be assessed against either bound;
that gap stays open.
"""


def mutate(removed: str, replacement: str = "") -> str:
    flat = normalise(GOOD)
    assert removed in flat, f"{removed!r} is not in the fixture, so removing it proves nothing"
    return flat.replace(removed, replacement)


@pytest.fixture(scope="module")
def schema(tmp_path_factory: pytest.TempPathFactory) -> tuple[str, ...]:
    return entity_columns(tmp_path_factory.mktemp("schema"))


def check_good(section: str, schema: tuple[str, ...]) -> tuple[str, list[str]]:
    return check_disclosure(
        section,
        columns=schema,
        fields=identity_fields(),
        meta_keys=META_IDENTIFIERS + META_DISCLOSURES,
    )


def test_the_fixture_disclosure_passes(schema: tuple[str, ...]) -> None:
    """Otherwise every negative below passes for the wrong reason."""
    verdict, missing = check_good(GOOD, schema)
    assert verdict == AGREE, "; ".join(missing)


@pytest.mark.parametrize(
    "removed",
    [
        "Art. 26(7)",
        "DPIA",
        "§87(1)(6) BetrVG",
        "in particular Union law on the protection of personal data",
        "ceiling",
        "meta[operator_id]",
        "meta[worker_notice]",
        "meta[dpia_reference]",
        "meta[operator_id_kind]",
    ],
)
def test_a_disclosure_missing_a_required_statement_is_caught(
    removed: str, schema: tuple[str, ...]
) -> None:
    verdict, missing = check_good(mutate(removed), schema)
    assert verdict == DISAGREE
    assert missing


def test_an_undisclosed_entity_column_is_caught(schema: tuple[str, ...]) -> None:
    """The tripwire under the minimisation contract, exercised directly.

    A column named for a person is the case that matters, and the check does not
    need to recognise the name: anything the section does not disclose fails,
    which is the only rule that cannot be defeated by a column called something
    innocuous.
    """
    verdict, missing = check_good(GOOD, (*schema, "worker_name"))
    assert verdict == DISAGREE
    assert any("worker_name" in item for item in missing)


def test_an_undisclosed_identity_field_is_caught(schema: tuple[str, ...]) -> None:
    @dataclasses.dataclass(frozen=True)
    class WithBadge:
        run_start: str
        unit_id: str
        operator_id: str
        badge_number: str

    verdict, missing = check_disclosure(
        GOOD,
        columns=schema,
        fields=tuple(field.name for field in dataclasses.fields(WithBadge)),
        meta_keys=META_IDENTIFIERS + META_DISCLOSURES,
    )
    assert verdict == DISAGREE
    assert any("badge_number" in item for item in missing)


@pytest.mark.parametrize(
    "section",
    ["", "   \n\n  ", "## 7. Something else entirely\n\nNo section here.\n"],
)
def test_a_missing_section_is_not_a_pass(section: str, schema: tuple[str, ...]) -> None:
    verdict, _ = check_good(disclosure(section), schema)
    assert verdict == COULD_NOT_EVALUATE


def test_an_unreadable_schema_is_not_a_pass() -> None:
    verdict, missing = check_disclosure(
        GOOD,
        columns=(),
        fields=identity_fields(),
        meta_keys=META_IDENTIFIERS + META_DISCLOSURES,
    )
    assert verdict == COULD_NOT_EVALUATE
    assert missing


@pytest.mark.parametrize(
    "sentence",
    [
        "This artifact complies with the GDPR.",
        "An artifact built this way is GDPR-compliant.",
        "Held for six months, the file is compliant.",
        "This section is legal advice.",
    ],
)
def test_a_compliance_claim_is_caught(sentence: str) -> None:
    verdict, found = check_no_compliance_claim(GOOD + "\n" + sentence + "\n")
    assert verdict == DISAGREE, f"{sentence!r} was not caught"
    assert found


@pytest.mark.parametrize(
    "sentence",
    [
        "Nothing here is legal advice and nothing here is a claim of compliance.",
        "This section does not comply with anything and says so.",
        "No artifact built here is compliant, and none is claimed to be.",
    ],
)
def test_a_disclaimer_is_not_a_claim(sentence: str) -> None:
    verdict, found = check_no_compliance_claim(GOOD + "\n" + sentence + "\n")
    assert verdict == AGREE, f"the disclaimer {sentence!r} was read as a claim: {found}"


def test_an_empty_section_cannot_pass_the_compliance_check() -> None:
    verdict, _ = check_no_compliance_claim("")
    assert verdict == COULD_NOT_EVALUATE


@pytest.mark.parametrize(
    "text",
    ["", "The EU AI Act sets that floor at six months.\n"],
)
def test_a_plan_without_the_proviso_is_caught(text: str) -> None:
    verdict, missing = check_proviso(text, where="a stand-in")
    assert verdict in (DISAGREE, COULD_NOT_EVALUATE)
    assert verdict != AGREE
    assert missing


def test_a_section_9_without_the_inversion_is_caught() -> None:
    verdict, missing = check_inversion(
        "## 9. DSSAD's actual data model\n\nThe elements map one for one.\n"
    )
    assert verdict == DISAGREE
    assert missing


def test_a_missing_section_9_is_not_a_pass() -> None:
    verdict, _ = check_inversion(prior_art_section_9("# no sections here\n"))
    assert verdict == COULD_NOT_EVALUATE


@pytest.mark.parametrize(
    "removed",
    [
        "Recording is not discharging.",
        "legal determination",
        "against either bound",
    ],
)
def test_a_section_that_drops_what_it_still_owes_is_caught(removed: str) -> None:
    """THE NEGATIVE for the pair above, one sentence at a time.

    Each removal is the edit that would make §8 read as though the three keys
    closed the obligations they record. The check has to say no to every one of
    them, or it is asserting nothing about a document that will be edited.
    """
    verdict, missing = check_records_and_still_owes(mutate(removed))
    assert verdict == DISAGREE
    assert missing


def test_a_missing_section_cannot_pass_the_records_and_owes_check() -> None:
    verdict, missing = check_records_and_still_owes("")
    assert verdict == COULD_NOT_EVALUATE
    assert missing


@pytest.mark.parametrize(
    "term",
    [
        "gdpr-compliant",
        "lawful-basis-established",
        "dpia_approved",
        "worker_notice_legal",
        "pseudonymised",
        "anonymised",
        "consent-given",
    ],
)
def test_a_vocabulary_term_that_claims_compliance_is_caught(term: str) -> None:
    """THE NEGATIVE, in the shape `test_a_compliance_claim_is_caught` uses.

    Every one of these is a value somebody could plausibly want: they read as
    progress, and each of them would put a legal conclusion in `meta` under this
    project's name. `pseudonymised` is the subtle one — `pseudonym` describes an
    identifier and passes, while the participle names a GDPR Art. 4(5) measure
    and claims one was taken.
    """
    verdict, found = check_vocabulary_claims_nothing((*disclosure_vocabulary(), term))
    assert verdict == DISAGREE, f"{term!r} was not caught"
    assert any(term in item for item in found)


def test_an_empty_vocabulary_is_not_a_pass() -> None:
    """A scan over nothing finds nothing, and that is not agreement."""
    verdict, missing = check_vocabulary_claims_nothing(())
    assert verdict == COULD_NOT_EVALUATE
    assert missing


def test_the_vocabulary_is_derived_rather_than_listed() -> None:
    """The scan has to cover what an artifact can actually hold.

    A hand-written list here would go stale the first time a member was added,
    and it would go stale silently — the check would still pass, over the words
    somebody remembered. So this asserts the derivation: every enum member's
    value, and every key `reg.graph` writes, is in what gets scanned.
    """
    vocabulary = set(disclosure_vocabulary())
    for member in (*WorkerNoticeStatus, *OperatorIdKind):
        assert member.value in vocabulary, f"{member} is not scanned"
    for key in META_DISCLOSURES:
        assert key in vocabulary, f"{key} is not scanned"
    assert DPIA_NONE in vocabulary
