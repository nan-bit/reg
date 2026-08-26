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
from pathlib import Path

import pytest

from reg import graph, store
from reg.identity import RunIdentity

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
    missing += [f"meta key {key!r} is not disclosed" for key in meta_keys if key not in section]
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
        meta_keys=META_IDENTIFIERS,
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
        section, columns=schema, fields=identity_fields(), meta_keys=META_IDENTIFIERS
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
        meta_keys=META_IDENTIFIERS,
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
        GOOD, columns=(), fields=identity_fields(), meta_keys=META_IDENTIFIERS
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
