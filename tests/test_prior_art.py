"""The survey's own action lists are prose, and prose does not fail.

Issue #104. `docs/prior-art.md` §14 ended on 2026-08-21 with an instruction:
cite Schneier–Kelsey wherever the chain is introduced, cite Ma & Tsudik beside
the truncation paragraph, and record the missing forward security in
`docs/limitations.md`. None of it was in the repository five days later, and
nothing went red — so the file whose own sentence is *publishing a known
limitation as though it were peculiar to this artifact is not fine* published
exactly that for five days.

This is the check that would have caught it, and it is the mechanism §20 names.
It asserts each ordered citation against the source of the file it was ordered
into; it asserts that no body of work in the survey is still described as
unread; and it asserts that every entry says both of the things an entry is for
— what the work does that `reg` does not, and what `reg` does that it does not.

Issue #138 extends the roster rather than starting a file: the fifth pass's
five bodies of work are held to the same both-directions standard as the four
above, and — because four of the five have a source boundary — each is also
required to say what it was read *from*.

Issue #199 extends it once more, and adds the one thing a pass ordered *by a
design document* has to carry that the earlier passes did not: a **verdict**.
The sixth pass exists to decide whether `docs/self-describing.md` survives it,
so an entry that surveys a body of work and never says what it does to that
document has done the reading and not the job. All three predicates apply to
all four entries — both directions, a source boundary, and a verdict.

**Every predicate here is fed the pre-#104 text and required to say no.** A
check that only ever sees the corrected wording proves nothing about whether it
can fail, and the defect being guarded is an *absence*, which is the easiest
thing in the world to accidentally assert away with a substring match against a
document that mentions the topic somewhere else.

Three-valued, per `docs/CONTRIBUTING.md` and `CLAUDE.md`: a file that cannot be
read, or a section that cannot be located, is COULD-NOT-EVALUATE and never
resolves to a pass. Deleting a section is not how this check gets satisfied.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

PRIOR_ART = REPO / "docs" / "prior-art.md"
LIMITATIONS = REPO / "docs" / "limitations.md"
PLAN = REPO / "docs" / "plan.md"
README = REPO / "README.md"
CHAIN = REPO / "reg" / "chain.py"

AGREE = "AGREE"
DISAGREE = "DISAGREE"
COULD_NOT_EVALUATE = "COULD-NOT-EVALUATE"


# --------------------------------------------------------------------------
# Predicates. Each takes the text it is pointed at and answers about that text
# alone — never about the file it came from — so that the negative tests below
# can feed them the wording that was actually there before this issue.
# --------------------------------------------------------------------------


def normalise(text: str) -> str:
    """Strip markdown emphasis and collapse whitespace, nothing else.

    So that `**Schneier**` and `Schneier` are the same token, and a citation
    broken across a line wrap is still one citation.
    """
    return re.sub(r"\s+", " ", re.sub(r"[*_`]", "", text))


def cites_the_construction(text: str) -> bool:
    """Does `text` credit the chain to Schneier and Kelsey, with a year?

    Both names and a year. A bare "Schneier" is a mention; the point of the
    citation is that a reader can find the paper.
    """
    flat = normalise(text)
    return (
        re.search(r"Schneier", flat) is not None
        and re.search(r"Kelsey", flat) is not None
        and re.search(r"\b(1998|1999)\b", flat) is not None
    )


def cites_the_truncation_attack(text: str) -> bool:
    """Does `text` name the truncation attack *and* the paper that named it?

    Describing the attack without the citation is the defect §14 objected to,
    so describing it is not enough on its own.
    """
    flat = normalise(text)
    return (
        re.search(r"Ma\b", flat) is not None
        and re.search(r"Tsudik", flat) is not None
        and re.search(r"truncation attack", flat, re.IGNORECASE) is not None
    )


def records_forward_security_as_an_absence(text: str) -> bool:
    """Does `text` say `reg` does *not* have forward security, and own it?

    Three conjuncts, because each alone is satisfiable by text that leaves the
    reader worse off: the property has to be named, the absence has to be
    stated as this artifact's, and the keys have to be described as static —
    which is the mechanism, and the part someone re-deriving the entry would
    have to get right.
    """
    flat = normalise(text)
    return (
        re.search(r"forward secur", flat, re.IGNORECASE) is not None
        and re.search(
            r"(no forward secur|without its forward secur|minus (the|its) forward"
            r" secur|missing forward secur|has no forward secur)",
            flat,
            re.IGNORECASE,
        )
        is not None
        and re.search(r"keys are static|static for the life", flat) is not None
    )


def records_the_verifier_holds_the_key(text: str) -> bool:
    """Does `text` state the asymmetry: verifying and forging need the same key?"""
    flat = normalise(text)
    return (
        re.search(
            r"anyone who can verify [^.]{0,40}can also forge", flat, re.IGNORECASE
        )
        is not None
    )


#: A body of work whose *reading* is outstanding. Narrow on purpose: this file
#: discusses unreadness at length — what a reviewer reads an omission as, what
#: the status used to be — and a predicate that fired on the discussion would
#: be unsatisfiable by any file honest enough to explain itself.
UNREAD = re.compile(r"(not yet read|still unread|remains unread|\bunread\b)", re.I)


def is_described_as_unread(bullet: str) -> bool:
    """Does this status bullet say the reading itself is still outstanding?

    Applied to a bullet from a *Still open* list — the place this file records
    what it has not done — and not to prose. Paywalled, open, outstanding and
    not designed are all permitted statuses; not-yet-read is not.
    """
    return UNREAD.search(normalise(bullet)) is not None


def still_open_bullets(text: str) -> list[str]:
    """Every bullet of every *Still open* list in the file, unwrapped.

    Returns an empty list if the file has no such list, which the caller turns
    into COULD-NOT-EVALUATE: deleting the place where outstanding work is
    recorded is not a way to have none.
    """
    bullets: list[str] = []
    for block in re.split(r"\n(?=#{1,6} )", text):
        first_line = block.split("\n", 1)[0]
        if not re.search(r"still open", first_line, re.IGNORECASE):
            continue
        body = block.split("\n", 1)[1] if "\n" in block else ""
        bullets += [item for item in re.split(r"\n(?=- )", body) if item.startswith("- ")]
    return bullets


#: A statement of what an entry was read *from*, in the forms this file uses.
#: Deliberately a disjunction of phrasings rather than one wording: the check is
#: on the presence of a boundary, never on how it is phrased. What it catches is
#: an entry with **none** — which reads as a full read of whatever it cites, and
#: is the defect `test_sotif_is_entered_with_the_status_of_its_reading_stated`
#: guards for one standard and this guards for a pass with four of them.
SOURCE_BOUNDARY = re.compile(
    r"read from|entered from|paywall|secondary sources|did not extract"
    r"|preprint|was not run|no implementation was run|not a quotation"
    r"|nothing below is a quotation",
    re.IGNORECASE,
)


def states_a_source_boundary(text: str) -> bool:
    """Does this entry say what it was read from?"""
    return SOURCE_BOUNDARY.search(normalise(text)) is not None


#: A verdict's disposition: what the entry does to the document it bears on.
#: Three outcomes, and *leaves it standing* is one of them — an entry that
#: changes nothing is a result, not a missing result, which is why this is a
#: disjunction rather than a requirement that something moved.
VERDICT_DISPOSITION = re.compile(
    r"supersede|correct|leaves .{0,60}standing|stand(s|ing)\b", re.IGNORECASE
)


def states_a_verdict(text: str) -> bool:
    """Does this entry say what it does to the document that ordered the pass?

    Three conjuncts, and each rules out a different way of appearing to have
    one. The word **Verdict** is what makes it findable by a reader who is not
    reading the whole entry. Naming `self-describing.md` is what makes it a
    verdict *on the design* rather than a summary of the reading — issue #199's
    pass was ordered by that document and exists to dispose of it. And a
    disposition — supersedes, corrects, leaves standing — is what keeps
    "Verdict: interesting" from counting.
    """
    flat = normalise(text)
    return (
        re.search(r"\bVerdict\b", flat) is not None
        and re.search(r"self-describing", flat, re.IGNORECASE) is not None
        and VERDICT_DISPOSITION.search(flat) is not None
    )


def says_both_directions(text: str) -> bool:
    """Does an entry say what the work does that `reg` does not, and the reverse?

    The acceptance criterion for issue #104: *"Related work exists" is not an
    entry.* An entry earns its place by being comparative in both directions,
    which in this file's format is two headings or two sentences of the shape
    `What X does that reg does not` / `What reg does that X does not`.
    """
    flat = normalise(text)
    reg_side = re.search(r"[Ww]hat reg does that .{0,60}? does not", flat)
    other_side = re.search(r"[Ww]hat (?!reg does)\S.{0,60}? does that reg does not", flat)
    return reg_side is not None and other_side is not None


# --------------------------------------------------------------------------
# Locating the text each predicate is pointed at. A section that cannot be
# found is COULD-NOT-EVALUATE, not a pass.
# --------------------------------------------------------------------------


def module_docstring(path: Path) -> str:
    """The module header of a Python file, without importing it."""
    source = path.read_text(encoding="utf-8")
    match = re.match(r'\s*"""(.*?)"""', source, re.DOTALL)
    return match.group(1) if match else ""


def section(text: str, heading: re.Pattern[str]) -> str:
    """The markdown section whose heading matches, body included, or ``""``.

    Bounded by the next heading at the **same level or shallower**, so a
    section's subsections come with it and its successors do not. That is not
    a nicety: this file's entries put *what it does that `reg` does not* in a
    `###` subheading, and a splitter that stopped at every heading would cut
    every entry off above the part being checked.
    """
    blocks = re.split(r"\n(?=#{1,6} )", text)
    for index, block in enumerate(blocks):
        first_line = block.split("\n", 1)[0]
        match = re.match(r"(#{1,6}) ", first_line)
        if not match or not heading.search(first_line):
            continue
        level = len(match.group(1))
        out = [block]
        for following in blocks[index + 1 :]:
            deeper = re.match(r"(#{1,6}) ", following)
            if deeper and len(deeper.group(1)) <= level:
                break
            out.append(following)
        return "\n".join(out)
    return ""


def underlined_section(docstring: str, title: str) -> str:
    """A block of `reg/chain.py`'s header, which uses underlined headings."""
    pattern = re.compile(
        rf"^{re.escape(title)}\n^[-=]+\n(.*?)(?=\n^[A-Z][A-Z ,`'\-:0-9()]+\n^[-=]+\n|\Z)",
        re.DOTALL | re.MULTILINE,
    )
    match = pattern.search(docstring)
    return match.group(1) if match else ""


def verdict(located: str, holds: bool) -> str:
    """Three values, and the third never resolves to the first."""
    if not located.strip():
        return COULD_NOT_EVALUATE
    return AGREE if holds else DISAGREE


# --------------------------------------------------------------------------
# §14's action list, asserted against the four files it named.
# --------------------------------------------------------------------------


CHAIN_HEADER = module_docstring(CHAIN)
TRUNCATION = underlined_section(
    CHAIN_HEADER, "WHAT TRUNCATION COSTS, AND THE HONEST LIMIT OF DETECTING IT"
)


def test_the_chain_module_header_cites_the_construction_it_implements() -> None:
    """`docs/prior-art.md` §14, first ordered action, in `reg/chain.py`."""
    assert CHAIN_HEADER.strip(), "reg/chain.py has no module docstring to check"
    assert verdict(CHAIN_HEADER, cites_the_construction(CHAIN_HEADER)) == AGREE, (
        "reg/chain.py's header describes a construction it did not invent. "
        "docs/prior-art.md §14 ordered the Schneier-Kelsey 1998/1999 citation "
        "here; without it the header reads as though the scheme were designed "
        "in this repository."
    )


def test_the_truncation_paragraph_cites_the_attack_by_name() -> None:
    """§14's second ordered action, beside the paragraph it is about.

    The citation has to be *in the truncation section*, not merely in the file:
    a reader who reaches the paragraph documenting the limit is the reader who
    needs to know it is a named attack with a literature.
    """
    assert verdict(TRUNCATION, cites_the_truncation_attack(TRUNCATION)) == AGREE, (
        "reg/chain.py documents the truncation limit without citing Ma & "
        "Tsudik 2008, which named the attack against exactly this "
        "construction. Publishing a known limitation as though it were "
        "peculiar to this artifact is the thing docs/prior-art.md §14 objects "
        "to."
    )


def test_the_front_page_cites_the_construction_where_the_chain_is_introduced() -> None:
    """§14 ordered the citation *wherever the chain is introduced*."""
    honesty = section(
        README.read_text(encoding="utf-8"),
        re.compile(r"honesty note", re.IGNORECASE),
    )
    assert verdict(honesty, cites_the_construction(honesty)) == AGREE, (
        "README.md's honesty note introduces the chain and does not say whose "
        "construction it is. docs/prior-art.md §14: the one paragraph that "
        "reads as though the construction were designed here should read as "
        "an application of a known one."
    )


def test_phase_6_cites_the_construction() -> None:
    """§14's third ordered location: `docs/plan.md` Phase 6."""
    phase_6 = section(
        PLAN.read_text(encoding="utf-8"),
        re.compile(r"Phase 6", re.IGNORECASE),
    )
    assert verdict(phase_6, cites_the_construction(phase_6)) == AGREE, (
        "docs/plan.md Phase 6 specifies the chain and does not cite the paper "
        "it comes from."
    )


def test_the_missing_forward_security_is_recorded_as_a_named_absence() -> None:
    """§14's fourth ordered action, and the one with no other home.

    `docs/limitations.md` is where a deliberate absence goes; §14's own words
    are *a named, deliberate absence rather than an oversight*, together with
    the verifier-holds-the-key asymmetry.
    """
    text = LIMITATIONS.read_text(encoding="utf-8")
    entry = section(text, re.compile(r"forward secur", re.IGNORECASE))
    assert verdict(entry, records_forward_security_as_an_absence(entry)) == AGREE, (
        "docs/limitations.md has no entry recording that reg/chain.py "
        "implements Schneier-Kelsey without its forward security. Until it "
        "does, an assessor reads static keys as an oversight, which is the "
        "reading docs/prior-art.md §14 says is unavailable."
    )
    assert verdict(entry, records_the_verifier_holds_the_key(entry)) == AGREE, (
        "the same entry has to carry the second half §14 ordered: reg hands "
        "the auditor the keyring, so anyone who can verify an artifact can "
        "also forge one."
    )


# --------------------------------------------------------------------------
# The survey's coverage: the four bodies of work issue #104 named.
# --------------------------------------------------------------------------


#: Each item the issue required an entry for, and a pattern locating its
#: heading. Listed rather than globbed on purpose: the point of the check is
#: that these four specifically are present, and a roster derived from the
#: file's own headings would agree with the file no matter what it said.
ENTRIES_ISSUE_104 = {
    "rosbag2 / MCAP": re.compile(r"rosbag2 and MCAP", re.IGNORECASE),
    "SOTER": re.compile(r"\bSOTER\b"),
    "transparency logs": re.compile(r"[Tt]ransparency logs"),
    "ISO 21448 (SOTIF)": re.compile(r"SOTIF"),
}

#: The fifth pass, issue #138 — the five bodies of work `docs/mobile-base.md`
#: §6 names and this survey had no entry for while a design document was being
#: written on top of them. Same standard as the four above, which is what that
#: issue's acceptance criteria say: an entry that is not comparative in both
#: directions is not an entry, at any pass number.
ENTRIES_ISSUE_138 = {
    "Marvel & Bostelman (NIST, ROSE 2013)": re.compile(r"Marvel"),
    "ISO 3691-4 / ANSI/A3 R15.08": re.compile(r"3691-4"),
    "RTD / REFINE": re.compile(r"\bRTD\b"),
    "CORA": re.compile(r"\bCORA\b"),
    "set-theoretic localization": re.compile(r"[Ss]et-theoretic localization"),
}

#: The fifth-pass entries whose source boundary is a **paywall**, which have to
#: say the word rather than any boundary: an entry written from summaries that
#: reads as though the standard had been opened is a different defect from
#: leaving it unread, not a smaller one.
PAYWALLED_IN_THE_FIFTH_PASS = {"ISO 3691-4 / ANSI/A3 R15.08"}

#: The sixth pass, issue #199 — the four bodies of work
#: [`docs/self-describing.md`](../docs/self-describing.md) ordered a pass on
#: before anything it proposes is built. Same standard again, plus the verdict:
#: the pass was commissioned to decide the fate of a design document, and an
#: entry that does not say what it decided is a reading rather than a finding.
ENTRIES_ISSUE_199 = {
    "in-toto / SLSA": re.compile(r"in-toto"),
    "Reproducible Builds": re.compile(r"Reproducible Builds"),
    "C2PA": re.compile(r"\bC2PA\b"),
    "OAIS Representation Information": re.compile(r"Representation Information"),
}

#: The sixth-pass entry whose source boundary is a **paywall**, on the same
#: reasoning as `PAYWALLED_IN_THE_FIFTH_PASS`: ISO 14721 was not opened, and an
#: entry written from the digital-preservation literature that reads as though
#: the standard had been is the defect, not the smaller version of it.
PAYWALLED_IN_THE_SIXTH_PASS = {"OAIS Representation Information"}

REQUIRED_ENTRIES = {**ENTRIES_ISSUE_104, **ENTRIES_ISSUE_138, **ENTRIES_ISSUE_199}


@pytest.mark.parametrize("item", sorted(REQUIRED_ENTRIES))
def test_the_survey_has_an_entry_for_each_named_body_of_work(item: str) -> None:
    """Issue #104's acceptance criterion, and #138's, one item at a time."""
    entry = section(PRIOR_ART.read_text(encoding="utf-8"), REQUIRED_ENTRIES[item])
    assert entry.strip(), (
        f"docs/prior-art.md has no section for {item}. An external review "
        "named it as absent; a survey that does not name what a reviewer "
        "names reads as unfamiliarity."
    )
    assert verdict(entry, says_both_directions(entry)) == AGREE, (
        f"the {item} entry does not say both of the things an entry is for — "
        "what it does that reg does not, and what reg does that it does not. "
        'Issue #104: "Related work exists" is not an entry.'
    )


@pytest.mark.parametrize("item", sorted(ENTRIES_ISSUE_138))
def test_each_fifth_pass_entry_records_what_it_was_read_from(item: str) -> None:
    """Issue #138: reading status is recorded per entry as a source boundary.

    Four of the five have one — a paper whose PDF did not extract, two
    paywalled standards, and two lines read from preprints with nothing run —
    and an entry that carries no boundary reads as a full read of every
    document it cites. That is the failure
    `test_sotif_is_entered_with_the_status_of_its_reading_stated` guards for a
    single standard; this is the same guard over a whole pass.
    """
    entry = section(PRIOR_ART.read_text(encoding="utf-8"), ENTRIES_ISSUE_138[item])
    assert entry.strip(), f"docs/prior-art.md has no section for {item}"
    assert verdict(entry, states_a_source_boundary(entry)) == AGREE, (
        f"the {item} entry does not say what it was read from. An entry that "
        "states no source boundary reads as a full read of everything it "
        "cites, which is the claim docs/prior-art.md exists to prevent."
    )
    if item in PAYWALLED_IN_THE_FIFTH_PASS:
        assert re.search(r"paywall", normalise(entry), re.IGNORECASE), (
            f"the {item} entry does not say the clause text is paywalled. "
            "Some other boundary is not that one: a reader has to know the "
            "standard itself was not opened."
        )


@pytest.mark.parametrize("item", sorted(ENTRIES_ISSUE_199))
def test_each_sixth_pass_entry_records_what_it_was_read_from(item: str) -> None:
    """Issue #199, the same guard as #138's, over the sixth pass.

    Three of the four are read from specification text published on the web
    with no implementation run; the fourth is a paywalled standard whose free
    edition did not extract. An entry carrying none of that reads as a full
    read of every document it cites.
    """
    entry = section(PRIOR_ART.read_text(encoding="utf-8"), ENTRIES_ISSUE_199[item])
    assert entry.strip(), f"docs/prior-art.md has no section for {item}"
    assert verdict(entry, states_a_source_boundary(entry)) == AGREE, (
        f"the {item} entry does not say what it was read from. An entry that "
        "states no source boundary reads as a full read of everything it "
        "cites, which is the claim docs/prior-art.md exists to prevent."
    )
    if item in PAYWALLED_IN_THE_SIXTH_PASS:
        assert re.search(r"paywall", normalise(entry), re.IGNORECASE), (
            f"the {item} entry does not say the standard's text is paywalled. "
            "Some other boundary is not that one: a reader has to know the "
            "standard itself was not opened."
        )


@pytest.mark.parametrize("item", sorted(ENTRIES_ISSUE_199))
def test_each_sixth_pass_entry_carries_a_verdict(item: str) -> None:
    """Issue #199's acceptance criterion, one entry at a time.

    The sixth pass was ordered by `docs/self-describing.md` — *"Before this is
    built, prior-art.md needs a pass ... Assume it does"* — and the rule at the
    head of the survey is that prior art wins and the plan gets edited. So an
    entry that reads the work and stops has not discharged the order: what the
    reading *does* to that document is the deliverable, and *leaves it
    standing* is one of the three answers.
    """
    entry = section(PRIOR_ART.read_text(encoding="utf-8"), ENTRIES_ISSUE_199[item])
    assert entry.strip(), f"docs/prior-art.md has no section for {item}"
    assert verdict(entry, states_a_verdict(entry)) == AGREE, (
        f"the {item} entry carries no verdict on docs/self-describing.md. "
        "That document ordered this pass before anything it proposes is "
        "built; an entry that does not say whether it supersedes, corrects or "
        "leaves the design standing has done the reading and not the job."
    )


def test_no_body_of_work_in_the_survey_is_still_described_as_unread() -> None:
    """SOTIF was listed as *not yet read* for three passes.

    Issue #104: *"unread" after three passes is the one status that cannot
    stand.* This asserts it of the whole file, not of SOTIF alone — the defect
    is the status, and the next thing to acquire it should fail here too.
    """
    bullets = still_open_bullets(PRIOR_ART.read_text(encoding="utf-8"))
    assert bullets, (
        "docs/prior-art.md has no 'Still open' list to check. That is "
        "COULD-NOT-EVALUATE, not a pass — the list is where this file records "
        "what it has not done, and deleting it is not a way to have nothing "
        "outstanding."
    )
    offending = [normalise(bullet) for bullet in bullets if is_described_as_unread(bullet)]
    assert not offending, (
        "docs/prior-art.md still carries an outstanding item whose status is "
        f"that nobody has read it: {offending}. Read it and enter it, or "
        "record it as out of scope with a reason. Neither of those is 'not "
        "yet read'."
    )


def test_sotif_is_entered_with_the_status_of_its_reading_stated() -> None:
    """Entered *and* honest about how: the clause text is paywalled.

    The failure this guards is the opposite of the one above — an entry
    written from secondary sources that reads as though the standard had been
    opened. `docs/prior-art.md` already carries that discipline for IEC
    61784-3 and IEEE 7001; SOTIF gets it too.
    """
    entry = section(PRIOR_ART.read_text(encoding="utf-8"), re.compile(r"SOTIF"))
    flat = normalise(entry)
    assert re.search(r"21448", flat), "the SOTIF entry does not give the number"
    assert re.search(r"paywall", flat, re.IGNORECASE), (
        "the SOTIF entry does not say the clause text is paywalled and that it "
        "was entered from secondary sources. An entry that reads as though the "
        "standard had been opened is a different defect from leaving it unread, "
        "not a smaller one."
    )


# --------------------------------------------------------------------------
# THE NEGATIVES. Every predicate above, fed what was actually there before
# issue #104, and required to say no.
# --------------------------------------------------------------------------


#: `reg/chain.py`'s truncation paragraph as it stood before #104 — a correct
#: statement of the attack, independently derived, with no citation. This is
#: the exact text §14 objected to.
BEFORE_TRUNCATION = """
Deleting the *last* record of a chain breaks no link: every record that remains
still commits to its predecessor. Two witnesses in the artifact catch it anyway —
the record counts `reg.graph` writes into `meta`, and the `FOLLOWS` edges, one of
which is left pointing at a record the file no longer holds. **Neither is covered
by a MAC**, so an attacker who edits the count and drops the edge as well is not
detected by this walk. What defeats it is an external commitment to the final
chain hash, which is a deployment question and not something this file can solve
on its own.
"""

#: The README's honesty note before #104. It is candid about both keys living
#: in one process and says nothing about whose construction the chain is.
BEFORE_README = """
Every `Declaration` is signed with a policy key and linked to its predecessor by
a SHA-256 chain, and every `Verdict` is signed with a separate enforcement key.
**In this prototype both keys live in the same process.** That demonstrates the
*structure* of non-repudiation — two parties, two keys, a record neither can
rewrite without it showing — and not non-repudiation itself.
"""

#: `docs/plan.md` Phase 6 before #104.
BEFORE_PHASE_6 = """
Each `Declaration` and `Verdict` carries `prev_hash` (SHA-256 over the canonical
serialization of the previous record) and a `mac` under its own key. Two keys:
policy and enforcement. Verification walks the chain and checks every link and
every MAC.
"""

#: The first pass's bullet for SOTIF, which stood for three passes.
BEFORE_SOTIF = (
    "- **ISO 21448 (SOTIF)** — hazards from correct-but-inadequate function. "
    "Likely the right framing for Claim 3's sufficiency boundary; not yet read."
)


def test_the_construction_check_rejects_the_text_it_was_written_against() -> None:
    """Fed the pre-#104 README and Phase 6, the predicate must say no."""
    assert not cites_the_construction(BEFORE_README)
    assert not cites_the_construction(BEFORE_PHASE_6)
    # And silence is not a citation either. It is could-not-evaluate, and the
    # verdict function is what keeps that from resolving to a pass.
    assert verdict("", cites_the_construction("")) == COULD_NOT_EVALUATE
    # A mention is not a citation: the year is what makes the paper findable.
    assert not cites_the_construction("the usual Schneier and Kelsey style chain")


def test_the_truncation_check_rejects_an_uncited_correct_description() -> None:
    """The hard negative: the old paragraph is *right*, and still fails.

    What §14 objects to is not an error. It is a correct statement of a known
    limitation published as though the limitation were peculiar to this
    artifact — so a predicate that passes on a well-written uncited paragraph
    is a predicate that would never have caught anything.
    """
    assert not cites_the_truncation_attack(BEFORE_TRUNCATION)
    assert verdict(BEFORE_TRUNCATION, cites_the_truncation_attack(BEFORE_TRUNCATION)) == (
        DISAGREE
    )
    # Naming the attack without the paper is still not the citation.
    assert not cites_the_truncation_attack(
        "an attacker who erases the tail mounts a truncation attack"
    )


def test_the_forward_security_check_rejects_the_adjacent_admissions() -> None:
    """`docs/limitations.md` was already candid — about other things.

    §6 and the README's honesty note discuss key custody at length, so a loose
    predicate would have passed on the file as it stood and reported the
    absence as recorded. Both are fed in here and both must fail.
    """
    before_limitations = (
        "The keyring is a JSON file of two hex keys. There is no PKI, no key "
        "rotation and no revocation, and the file's only protection is its "
        "filesystem mode. Two keyholders at one employer share a common cause."
    )
    assert not records_forward_security_as_an_absence(before_limitations)
    assert not records_the_verifier_holds_the_key(before_limitations)
    assert not records_forward_security_as_an_absence(BEFORE_README)

    # Naming the property while claiming it is the inversion that matters most:
    # this must not pass just because the words appear.
    claims_it = (
        "The chain has forward security: the key is evolved after every record "
        "and the old value erased."
    )
    assert not records_forward_security_as_an_absence(claims_it)


def test_the_unread_check_rejects_the_bullet_that_stood_for_three_passes() -> None:
    """Fed the first pass's SOTIF bullet, the predicate must say it is unread."""
    assert is_described_as_unread(BEFORE_SOTIF)
    # And it must not fire on the ordinary business of a survey: things that
    # are open, outstanding or paywalled are not things that are unread.
    assert not is_described_as_unread(
        "The clause text of ISO 21448. Paywalled, like IEC 61784-3. Entered "
        "from secondary sources and says so."
    )


def test_the_entry_check_rejects_related_work_exists() -> None:
    """Issue #104's own words as the negative fixture.

    A section that names the work, gets the citation right and stops there is
    exactly what the acceptance criterion excludes, and it is what a hurried
    pass produces.
    """
    stub = (
        "## 16. rosbag2 and MCAP\n\n"
        "**rosbag2**, the recording subsystem of ROS 2, and **MCAP**, its "
        "default storage format. Related work exists. It is what practitioners "
        "retain today and it is worth being aware of.\n"
    )
    assert not says_both_directions(stub)
    assert verdict(stub, says_both_directions(stub)) == DISAGREE

    # One direction only is the commoner failure, and it must also fail.
    half = stub + "\n### What a bag does that `reg` does not\n\nReplay.\n"
    assert not says_both_directions(half)


#: An entry written as though the standard had been opened: comparative in both
#: directions, correct in outline, and silent about the fact that nobody here
#: has read a clause of it. It even cites a requirement, which is the thing a
#: summary cannot support.
NO_SOURCE_BOUNDARY = """## 22. ISO 3691-4 and ANSI/A3 R15.08

**ISO 3691-4** requires the protective field to be sized to the stopping
distance of the truck at its current speed, and requires the field to be
switched as that speed changes.

### What `reg` does that a protective field does not

It retains the evaluation.

### What ISO 3691-4 does that `reg` does not

It rates the device that produces the field.
"""


def test_the_source_boundary_check_rejects_an_entry_that_reads_as_a_full_read() -> None:
    """The hard negative: the fixture passes the *other* check and still fails.

    It is comparative in both directions, so the entry check clears it. What
    it does not say is that nobody opened the standard — and it states a
    requirement, which is exactly what a vendor summary cannot support. A
    predicate that passed this would report the boundary as recorded.
    """
    assert says_both_directions(NO_SOURCE_BOUNDARY)
    assert not states_a_source_boundary(NO_SOURCE_BOUNDARY)
    assert verdict(
        NO_SOURCE_BOUNDARY, states_a_source_boundary(NO_SOURCE_BOUNDARY)
    ) == DISAGREE
    # And a deleted entry is could-not-evaluate, not a pass.
    assert verdict("", states_a_source_boundary("")) == COULD_NOT_EVALUATE
    # A boundary is not satisfied by the file merely discussing reading status
    # somewhere else: the predicate only ever sees one entry.
    assert states_a_source_boundary(
        NO_SOURCE_BOUNDARY + "\nBoth standards are paywalled.\n"
    )


#: An entry that passes both of the other checks and carries no verdict: it is
#: comparative in both directions, it says what it was read from, and it never
#: says what any of it does to the document that commissioned the pass. This is
#: what a thorough reading with no decision in it looks like, and it is the
#: failure issue #199's acceptance criteria were written against.
NO_VERDICT = """## 27. Reproducible Builds

**Read from the project's own documentation.** No build was rebuilt.

A build is reproducible given the same source, environment and instructions.
The environment is recorded in a buildinfo.

### What `reg` does that the Reproducible Builds project does not

It carries an adversary.

### What the Reproducible Builds project does that `reg` does not

It states the environment.
"""


def test_the_verdict_check_rejects_a_thorough_entry_that_decides_nothing() -> None:
    """The hard negative: it clears both of the older checks and still fails.

    An entry can be correct, comparative and honest about its sources and
    still leave the design document exactly where it found it — which is the
    one outcome a pass ordered *before this is built* cannot deliver.
    """
    assert says_both_directions(NO_VERDICT)
    assert states_a_source_boundary(NO_VERDICT)
    assert not states_a_verdict(NO_VERDICT)
    assert verdict(NO_VERDICT, states_a_verdict(NO_VERDICT)) == DISAGREE
    # And a deleted entry is could-not-evaluate, not a pass.
    assert verdict("", states_a_verdict("")) == COULD_NOT_EVALUATE

    # The word alone is not a verdict. This one is findable and says nothing.
    labelled = NO_VERDICT + "\n**Verdict.** Interesting and worth knowing.\n"
    assert not states_a_verdict(labelled)

    # Nor is a disposition about some other document: the pass was ordered by
    # self-describing.md and the verdict has to be on that.
    elsewhere = NO_VERDICT + (
        "\n**Verdict.** It supersedes nothing in `docs/lossiness.md`.\n"
    )
    assert not states_a_verdict(elsewhere)

    # And the real thing passes, including the do-nothing outcome — an entry
    # that changes the design is not the only entry that has decided.
    stands = NO_VERDICT + (
        "\n**Verdict — it leaves `docs/self-describing.md` standing.** The three "
        "gaps are unaffected.\n"
    )
    assert states_a_verdict(stands)


def test_a_missing_section_is_could_not_evaluate_and_not_a_pass() -> None:
    """Deleting a section is not how these checks get satisfied."""
    assert section("# A\n\nbody\n", re.compile(r"nothing like this")) == ""
    assert verdict("", True) == COULD_NOT_EVALUATE
    assert underlined_section("no underlined headings here", "MISSING") == ""
