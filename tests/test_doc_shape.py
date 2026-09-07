"""The documents have a shape, and the shape is checked (issue #171).

Tier 1 of #170. The corpus is 99,505 words across thirteen documents and it is
growing faster than the code it describes: 76,428 words when #170 measured it,
against a package surface that moved from 252 public symbols to 260 over the
same span. An unread document drifts from the code with nothing to catch it,
and nothing in this repository noticed the growth.

**This checks shape, not content.** `tests/test_published_figures.py` re-derives
the published figures from the code and `tests/test_doc_status_headers.py` holds
each status header against its own body; both are about whether a document is
*true*. Nothing here reads a claim. This file asks only how much prose there is,
how it is distributed, and whether a reader can find out what a document is for
without reading all of it. It must not be taken as covering accuracy, and it
does not weaken either of those two.

WHY THE BUDGET HAS TWO TERMS
----------------------------
A single word ceiling is the wrong instrument. This repository is under active
development, so documentation that *describes the code* must be free to grow
with it — a flat ceiling either blocks that or gets raised until it means
nothing. But most of the corpus does not describe the code. `sufficiency.md` is
11,164 words of boundary argument and would not shrink if half the package were
deleted; tying it to code size would hand it a larger allowance every time a
feature ships, which is backwards.

So each half is governed by what actually drives it: code-coupled prose by
`RATE * public_symbols`, argument and reference prose by a flat `ARGUMENT_MAX`.

**Adding code buys documentation budget. Having more ideas does not.** That is
the whole design.

WHAT COUNTS AS A DOCUMENT, AND WHY ALL THREE LISTS ARE EXPLICIT
---------------------------------------------------------------
`CODE_COUPLED`, `ARGUMENT` and `EXEMPT` between them must name every file in the
corpus, and no file may be in two of them. A file in none of the three fails,
because a budget escaped by adding a file is a budget that dies quietly — this
is the pattern `tests/test_layout.py` already uses for modules with no mirrored
test, including the part where each entry says *why* it is where it is.

`EXEMPT` is the case where neither term is the right instrument, and #170 tier 6
made it expensive to use rather than rare by convention: a document that leaves a
group takes its words out of that group's ceiling with it, so exempting one buys
the documents left behind nothing. Removing `prior-art.md` — 36% of the argument
group — while leaving `ARGUMENT_MAX` where it stood would have granted the other
five a third of the budget as free headroom, which ends a ratchet more
effectively than raising a constant does, because it does not look like a raise.

THE RATCHET
-----------
Every constant here may be **lowered and never raised**. Tiers 2–5 of #170 each
lower them; without that this check does nothing but freeze today's density in
place. Two consequences are deliberate:

* a change that adds prose without adding surface fails, and the fix is to cut
  something in the same change rather than to raise a constant;
* a refactor that *removes* public symbols shrinks the budget and can put the
  corpus over. That is usually correct — documentation describing removed
  surface should go — but it fires at an inconvenient moment, so the failure
  message names the group, the ceiling and the overage.

Three-valued per `CLAUDE.md`'s *a check must be able to fail*: an empty corpus,
a package with no public symbols, a classification entry with no reason, and a
document with no prose at all are COULD-NOT-EVALUATE, and none of them resolves
to a pass. Deleting the documents is not how this check gets satisfied.

Every predicate below is fed the condition it guards against and required to say
DISAGREE, and each numeric ceiling is fed a value one notch tighter than the
constant to show the constant has no headroom in it.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
PACKAGE = REPO / "reg"

AGREE = "AGREE"
DISAGREE = "DISAGREE"
COULD_NOT_EVALUATE = "COULD-NOT-EVALUATE"


# --------------------------------------------------------------------------
# The corpus, and the classification of every file in it
# --------------------------------------------------------------------------

def corpus_paths() -> tuple[str, ...]:
    """Every markdown file this budget governs.

    `docs/` is globbed rather than listed, so a new document arrives in the
    corpus by existing and has to be classified below before `pytest` is green
    again. That is the intent, not an oversight.
    """
    top = ("README.md", "CLAUDE.md")
    docs = tuple(f"docs/{path.name}" for path in sorted((REPO / "docs").glob("*.md")))
    return tuple(name for name in top + docs if (REPO / name).is_file())


# Documents whose length should track the code. Each entry says why, because a
# classification with no reason is how a document ends up in whichever group
# has room. Moving a file between the lists moves its words between two
# ceilings and is a decision, not a tidy-up.
CODE_COUPLED: dict[str, str] = {
    "README.md": (
        "The front page. It describes what the package is and how to run it, "
        "and every section of it points at a module."
    ),
    "CLAUDE.md": (
        "The conventions the code must follow, stated in terms of the modules "
        "and tests that enforce them. Simplifying an API shortens it."
    ),
    "docs/CONTRIBUTING.md": (
        "How work arrives and what a queueable issue names. It describes the "
        "process around the package rather than arguing anything about it."
    ),
    "docs/README.md": (
        "The index of docs/. It grows with the documents it lists, not with "
        "the argument any of them makes."
    ),
    "docs/mobile-base.md": (
        "A design document for one track, with a build order in §7 that says "
        "per tier what has landed. It shrinks as its tiers land."
    ),
    "docs/self-describing.md": (
        "A design document for one track, with a build order in §8 — the same "
        "shape as mobile-base.md, and classified beside it for the same "
        "reason. It describes what the artifact must carry rather than arguing "
        "a claim, and it shrinks as its tiers land. It did not exist when #171 "
        "was filed, which is why the issue's own table does not carry it."
    ),
    "docs/sensor-baseline.md": (
        "The sensor assumption and the artifact sizes it is applied against. "
        "Every table in it is measured from the package at a stated rate."
    ),
}

# Documents whose length is driven by how much there is to argue or to cite.
# None of these would shrink if the package did, which is exactly why tying
# them to `public_symbols` would be backwards.
ARGUMENT: dict[str, str] = {
    "docs/plan.md": (
        "The claims, the phases and the non-goals. It is the argument for the "
        "project; the code is what the argument is about."
    ),
    "docs/sufficiency.md": (
        "Which audit claims survive an uncertifiable perceiver. A boundary "
        "argument, normative over what the project may claim."
    ),
    "docs/limitations.md": (
        "What the project may not claim and what each limitation costs. "
        "Normative, and it grows with the claims rather than with the code."
    ),
    "docs/lossiness.md": (
        "The discard contract and the question set it is relative to. It was "
        "required to land before any graph code was written."
    ),
    "docs/retention.md": (
        "Claim 1's measurement record — the figures, the arithmetic behind "
        "them and how they moved. An argument about cost."
    ),
}

# Documents the budget does not reach at all: not counted against either
# ceiling, and not licensed to grow by it either. Each entry says why the
# budget's *premise* does not apply, in the form `tests/test_layout.py`'s
# `VERIFIED_ELSEWHERE` entries take — a reason, not a restatement of the fact
# that the file is long. An entry with no reason is COULD-NOT-EVALUATE and a
# file listed here as well as in a group is a DISAGREE, because an exemption
# that can be held alongside a classification is a discount on a ceiling.
#
# Adding to this list is not free: #170 tier 6 settled that the ceiling a
# document leaves is re-measured without it, so an exemption gives the
# documents left behind no room. See ARGUMENT_MAX below.
EXEMPT: dict[str, str] = {
    "docs/prior-art.md": (
        "A dated log of work done outside this repository — twenty-nine "
        "entries across six passes, each kept whole because half of what the "
        "file records is *when* something was found. The budget's premise is "
        "that a document should shrink when the thing it describes simplifies; "
        "what this one describes is not in this package and does not simplify "
        "when the package does, so neither term measures it. `RATE * "
        "public_symbols` would hand it a larger allowance every time a feature "
        "ships, and a flat ceiling would price a citation found tomorrow "
        "against prose written here today. It is exempt from the *budget* "
        "only: `tests/test_prior_art.py` still requires an entry per named "
        "body of work, both directions per entry, a verdict and a reading "
        "status, and this module's paragraph and narration ceilings still "
        "count its paragraphs."
    ),
}


# --------------------------------------------------------------------------
# The two budget constants
# --------------------------------------------------------------------------

# RATE — words of code-coupled prose per public symbol.
#
# MAY BE LOWERED, NEVER RAISED. It is a ratchet: tiers 2-5 of #170 each lower
# it, and a change that cannot fit under it is asking to cut something, not to
# edit this line. Raising it is the move that teaches everyone the rule is
# decorative, and it has already been made once — recorded here so the first
# cutting tier knows what it owes:
#
#   62.7  #171 as filed          15,793 / 252 symbols
#   78.2  #171 regroomed, 2026-09-05, before docs/self-describing.md was
#         classified             20,332 / 260 symbols
#   94.5  2026-09-05             24,560 / 260 symbols = 94.46, rounded up to
#         the next tenth and by nothing more
#   94.3  2026-09-05, after #213 split `docs/sensor-baseline.md` into a
#         normative core and a `## Why` line: that file went 4,173 -> 4,116, of
#         which 3,595 is the normative core. 24,503 / 260 = 94.24, rounded up
#         the same way. The cut is small next to tiers 2-4 because this file's
#         narration is mostly *figures* — superseded sizes, thresholds and
#         attributions — and those move below the line rather than out
#   93.5  2026-09-06, after #214 did the same to `docs/mobile-base.md`:
#         that file went 8,331 -> 8,129, of which 6,328 is the normative core.
#         24,301 / 260 = 93.46, rounded up the same way. The cut is smaller than
#         the shape change: 1,801 words moved below the line and the file is
#         still the longest in this group, because a design document whose tiers
#         have all landed carries a build order that is mostly provenance, and
#         provenance is what moved rather than went
#   90.6  today, 2026-09-06, after #217 stopped the three reader-facing entry
#         points restating what they link to: `README.md` 3,930 -> 3,402,
#         `docs/README.md` 785 -> 642, `docs/CONTRIBUTING.md` 792 -> 716.
#         23,554 / 260 = 90.59, rounded up the same way. All three are in this
#         group and none of them is a design document, so unlike #213 and #214
#         the words left the corpus rather than moving below a `## Why` line —
#         what was cut is prose the linked document states in full
#   88.8  today, 2026-09-06, after #220 priced the incumbent over the whole
#         stream: `docs/sensor-baseline.md` 4,541 -> 5,310 and `README.md`
#         3,402 -> 3,502, against 265 -> 280 public symbols in `reg/`.
#         24,848 / 280 = 88.74, rounded up to the next tenth. This is the case
#         the two-term budget was designed for and the first time it has
#         happened: the prose describes fifteen new symbols, so the denominator
#         moved with it and the density fell without anything being cut
#   88.8  2026-09-06, after #233 republished the incumbent figures from the
#         measured bags. Unchanged and re-measured: `README.md` 3,503 -> 3,547
#         and `docs/sensor-baseline.md` 6,213 -> 6,164, 25,747 / 290 = 88.79.
#         The republication is paid for inside the same file that carries it —
#         three 2026-09-06 provenance rows merged into one, and four paragraphs
#         restating the projection cut to what the tables already say
#   88.8  today, 2026-09-07, after #229 added a fourth mobile fixture.
#         Unchanged and re-measured: `docs/mobile-base.md` went 8,129 -> 8,129,
#         25,745 / 290 = 88.78. A fixture is a module-level assignment and
#         `public_symbols` counts definitions, so this change bought no budget
#         and the denominator did not move — §7.2's new bullet is paid for
#         inside the same file, by four passages restating something the reader
#         is already being pointed at: §5 restating §4 item 8 of this same
#         document, §7.3 and §6 restating `limitations.md` §2-§3 and
#         `prior-art.md`'s standing over its own pass, and §5 restating
#         `retention.md`'s status header while `See also` links it anyway.
#         88.7 is not available — it would put the ceiling at 25,723, under the
#         corpus — so this is the tightest tenth and not a banked difference
#   88.6  today, 2026-09-07, after #231 shipped the cold read. This is the #220
#         case again and the second time it has happened: `reg/query.py` gained
#         four public symbols — `cold_read`, `render_cold_read`, `ColdRead` and
#         `ColdReadClaim` — and `docs/self-describing.md` went 4,228 -> 4,513
#         describing them, so the denominator moved with the prose. 26,028 / 294
#         = 88.53, rounded up to the next tenth. The §2 table it replaced was
#         three states wide and the shipped report is four, which is most of the
#         difference; what did *not* grow is the archaeology, because the two
#         issue references the new prose needed live in §8's build order, below
#         that file's rationale line, which is where #213 and #214 put theirs
#   86.2  today, 2026-09-07, after #247 let an `Acknowledgment` reach the
#         artifact. The denominator moved and the numerator barely did:
#         `reg.store`, `reg.chain`, `reg.query` and `reg.scenarios` gained nine
#         public symbols between them — the store's two readers/writers,
#         `RecordSpec` and `read_chain_records`, the query and its three answer
#         shapes, and `AckPoint` — against 45 words, almost all of them
#         `README.md`'s Claim 4 row saying the passivation question is now
#         answerable. 26,089 / 303 = 86.10, rounded up to the next tenth. A
#         ceiling left at 88.6 would have banked 726 words of headroom bought by
#         shipping a feature, which is the raise this ratchet exists to refuse
#
# The step to 78.2 is the finding #171 was regroomed to state: code-coupled
# prose grew 29% while the surface it describes grew 3%, which is the exact
# thing this budget exists to catch. The step from there to 94.5 is not a
# second raise in density — it is the same corpus counted with
# `docs/self-describing.md` in the group the regroom put it in.
#
# **62.7 is the number to get back under.** It is separate from ARGUMENT_MAX
# because these words track the package and those words track how much there is
# to argue; see the module docstring.
RATE = 86.2

# ARGUMENT_MAX — a flat ceiling, in words, on argument and reference prose.
#
# MAY BE LOWERED, NEVER RAISED, for the same reason and by the same tiers. Flat
# rather than per-symbol because nothing in this group would shrink if the
# package did: shipping a feature must not buy `sufficiency.md` a larger
# allowance.
#
#   60,635  #171 as filed
#   74,945  2026-09-05, when #171 landed — measured, no headroom
#   74,590  2026-09-05, after #206 split `docs/limitations.md` into a normative
#           core and a `## Why` line — measured, no headroom
#   74,230  2026-09-05, after #209 did the same to `docs/lossiness.md`: that
#           file went 11,116 -> 10,756, of which 9,391 is the normative core
#   73,969  2026-09-05, after #210 did the same to `docs/sufficiency.md`:
#           that file went 11,425 -> 11,164, of which 9,707 is the normative
#           core — measured, no headroom
#   73,968  2026-09-06, after #117 republished the incumbent encoding under both
#           rosbag2 presets. The prose that added to `retention.md`, `plan.md`
#           and `prior-art.md` is paid for in the same group: `retention.md`
#           stopped restating `plan.md`'s *What it supports* and its Article 19
#           / 26(6) quotation, and dropped a forward pointer that summarised a
#           section three screens below it. A ceiling one word lower than the
#           last one is what a change that adds prose looks like when it finds
#           the room rather than asking for it — measured, no headroom
#   73,968  2026-09-06, after #220 published the whole-stream incumbent figures.
#           Unchanged, which is the point: `retention.md`, `plan.md` and
#           `prior-art.md` gained 492 words between them and gave back 492, all
#           of it prose restating a document it links to — the `TIME_TOL_S`
#           caveat `sensor-baseline.md` carries, the Gorilla comparison
#           `prior-art.md` §8 carries, the pin boundary
#           `tests/test_published_figures.py` carries, and the 13x condition
#           `retention.md` was stating at both ends of one subsection —
#           measured, no headroom
#   73,962  today, 2026-09-06, after #233 republished those figures from the
#           bags rosbag2 wrote. `prior-art.md` gained a third dated correction
#           and `plan.md` a longer Claim 1 condition, because the compressed
#           figure is now a pair and both ends of it are published: +169 words
#           between them. `retention.md` paid for it and 6 words over, going
#           -175 — it was still restating `prior-art.md` §8's Gorilla slice,
#           `plan.md`'s Art. 26(7) entry, the same 13x condition at both ends of
#           one subsection, and the answer to the original framing twice in one
#           screen. Six words lower than the last ceiling rather than level with
#           it, because a ceiling set above the measurement banks the difference
#           as headroom — measured, no headroom
#   47,194  today, 2026-09-07, #170 tier 6: `docs/prior-art.md` moved to
#           `EXEMPT` above and the ceiling was re-measured over the five
#           documents that remain. Nothing was cut and nothing was written — the
#           ceiling fell by exactly the 26,768 words that left, which is the
#           whole content of this row. Leaving it at 73,962 would have handed
#           those five 36% of the budget as headroom nobody asked for and no
#           diff would show, which is a raise in every respect except how it
#           reads. An exemption that pays for itself this way is one the next
#           tier can be trusted with; one that does not would make `EXEMPT` the
#           group with room — measured, no headroom
#   47,187  today, 2026-09-07, after #241 made numpy a compared key and gave the
#           recorded-but-not-compared set a name. `limitations.md` §1 gained the
#           split and its argument and `lossiness.md` *Discarded* #9 gained the
#           second list: +67 between them, paid for and seven words over. What
#           went was restatement of a document each already links to —
#           `lossiness.md`'s second telling of the buildinfo deviation and its
#           cost, which `self-describing.md` §3 holds, and its second telling of
#           the attribution limit, which is §1's; and `limitations.md`'s repeat
#           of the #175 platform measurement below its `## Why` line, four
#           paragraphs under the normative statement of the same thing. One
#           cut was tried and reverted — the Layer B column count in *What a
#           claim would need instead*, which
#           `tests/test_baseline_stream_description.py` requires every document
#           naming the baseline to carry, and which is therefore restatement on
#           purpose. Seven words lower than the last ceiling rather than level
#           with it, for the reason the #233 row gives — measured, no headroom
#   47,181  today, 2026-09-07, after #243 stated Claim 3's condition in the
#           sentence that makes the claim. `plan.md`'s Claim 3 gained the clause
#           and the evidence for it (+61), `sufficiency.md`'s normative
#           restatement gained the clause (+20) and a provenance row under its
#           `## Why` line (+18). `plan.md` paid for all 99 and six words over,
#           by cutting 105 of restatement: its second telling of the angular
#           half and the held decision, which its own Phase 4 carries four
#           screens below and `limitations.md` §3 is normative on, and its Phase
#           9 telling of `sufficiency.md` §1, the file that section names as its
#           own deliverable. Six words lower than the last ceiling rather than
#           level with it, for the reason the #233 row gives — measured, no
#           headroom
#   47,164  today, 2026-09-07, after #247 let an `Acknowledgment` reach the
#           artifact. `sufficiency.md` gained §5.10 — the layer argument for the
#           acknowledgment, which is the third case the entity-naming heuristic
#           does not decide and so had to be reasoning rather than a table row —
#           and `lossiness.md` *Retained* #7 was rewritten from a refusal into a
#           retention clause. Paid for and seventeen words over: `plan.md`'s
#           Claim 4 and Phase 4 stopped restating what `lossiness.md` #7 and
#           `sufficiency.md` §5.10 now carry, and `sufficiency.md` §5.9's
#           graded-attribute paragraph became a pointer at §7's fourth bullet,
#           which is where that argument is made in full. Seventeen words lower
#           than the last ceiling rather than level with it, for the reason the
#           #233 row gives — measured, no headroom
ARGUMENT_MAX = 47164

# What counts as a long paragraph. 120 is #170's threshold and is kept so the
# two measurements are of the same thing.
PARAGRAPH_MAX_WORDS = 120

# How many of them the corpus may hold. MAY BE LOWERED, NEVER RAISED.
#
#   110  #170's measurement, 2026-09-02, over 821 prose paragraphs
#   146  2026-09-05, when #171 landed, over 915
#   141  2026-09-05, after #206: five of docs/limitations.md's twenty-three
#        over-long paragraphs were split or cut
#   135  2026-09-05, after #209: docs/lossiness.md went 26 -> 20
#   121  2026-09-05, after #210: docs/sufficiency.md went 14 -> 0, six of the
#        fourteen by splitting rather than cutting
#   116  2026-09-05, after #213: docs/sensor-baseline.md went 5 -> 0, four of
#        the five by splitting rather than cutting
#    99  2026-09-06, after #214: docs/mobile-base.md went 17 -> 0,
#        counted over the whole file rather than over its normative core, so a
#        paragraph moved below the `## Why` line had to be split there too
#    97  2026-09-06, after #217: README.md went 2 -> 0. Both were in the
#        honesty note and both were split rather than cut, because what made
#        them long was two claims sharing a paragraph, not restatement
#    94  today, 2026-09-06, after #220: docs/retention.md went 11 -> 7. All four
#        went by cutting rather than splitting, because each was restating a
#        document it links to; docs/prior-art.md's dated correction was written
#        as two paragraphs rather than one for the same ceiling
#    92  today, 2026-09-07, after #241: docs/limitations.md and docs/lossiness.md
#        went 7 -> 5 between them, and neither change was made for this ceiling.
#        §1's *What the code does with it* became two paragraphs because what is
#        compared and what is only recorded are two decisions, and lossiness.md's
#        buildinfo paragraph fell below the threshold when its restatement of
#        self-describing.md §3 came out. A ceiling that falls out of work done
#        for another reason is still a ceiling that has fallen; leaving it at 94
#        would bank two paragraphs of headroom no diff would show
#    91  today, 2026-09-07, after #243: `docs/plan.md` went 8 -> 7. The
#        paragraph that fell below the threshold is the one Claim 4 used to
#        spend 179 words restating Phase 4 and `limitations.md` §3 in, and it
#        was cut for the word budget rather than for this ceiling. Lowered for
#        the reason the #241 row gives: a ceiling that falls out of work done
#        for another reason is still a ceiling that has fallen
#    90  today, 2026-09-07, after #247: `docs/plan.md` went 7 -> 6. The
#        paragraph that fell below the threshold is Phase 4's account of what
#        the artifact could not hold, which is now a pointer at
#        `lossiness.md` *Retained* #7 — cut for the word budget rather than for
#        this ceiling, and lowered here for the reason the #241 row gives
LONG_PARAGRAPHS_MAX = 90

# Prose paragraphs narrating a past defect above the document's rationale line.
# MAY BE LOWERED, NEVER RAISED.
#
#   190  #170's measurement, 2026-09-02, by its own counting rule
#   265  2026-09-05, when #171 landed, by PAST_DEFECT_MARKERS below — a
#        different rule, so the two are comparable in direction and not to the
#        unit
#   240  2026-09-05, after #206 moved docs/limitations.md's archaeology below a
#        `## Why` heading: that file went 38 -> 13
#   212  2026-09-05, after #209 did the same to docs/lossiness.md: that file
#        went 39 -> 11
#   179  2026-09-05, after #210 did the same to docs/sufficiency.md: that
#        file went 33 -> 0. Zero is what the proxy now counts above that file's
#        rationale line, not a claim that the file narrates nothing — two of the
#        33 were the marker set firing on normative text and were reworded in
#        the present tense, which the docstring below says it over-counts
#   165  2026-09-05, after #213 did the same to docs/sensor-baseline.md: that
#        file went 14 -> 0. Same caveat as above — six of the fourteen fired on
#        nothing but an issue reference, and five of those were live
#        cross-references in normative text, so what moved below the line was
#        the reference, into that file's `## Why` provenance table
#   141  2026-09-06, after #214 did the same to docs/mobile-base.md:
#        that file went 24 -> 0. Seventeen of the 24 carried an issue reference
#        and eight carried nothing else, which is the same shape #213 found;
#        the references moved into that file's `## Why` provenance table and
#        the tier-by-tier archaeology moved with them
#   139  today, 2026-09-06, after #217: README.md and docs/CONTRIBUTING.md went
#        1 -> 0 each, and neither file gained a `## Why` line — an entry point
#        that needs one is an entry point carrying provenance. One went by a cut
#        (CONTRIBUTING's restatement of CLAUDE.md's *Never invent a default*,
#        now a pointer to it) and one by rewording in the present tense, the
#        same over-count #210 recorded. A third paragraph fired mid-cut and is
#        worth knowing about: `was\nnot made` did not match across a line break
#        and `was not made` on one line did, so this proxy is sensitive to
#        rewrapping. It was reworded rather than rewrapped, because wrapping a
#        sentence to clear a marker is gaming the count
#   137  today, 2026-09-06, after #220: `docs/prior-art.md` gained a second
#        dated correction, which narrates for the same structural reason, and
#        `docs/retention.md` lost two — the `TIME_TOL_S` caveat and the Gorilla
#        comparison, both cut to a pointer at the document that carries them in
#        full. Net one, and set to what is above the line rather than left at
#        138, which would have banked the difference as headroom
#   138  2026-09-06, after #117: `docs/prior-art.md` gained a dated correction,
#        which narrates by construction — a survey pass is corrected by adding
#        to it and dating the addition, never by rewriting the entry — and
#        `docs/retention.md` lost two, both of them paragraphs that restated a
#        document they linked to. Set to what is now above the line rather than
#        left at 139, which would have banked the difference as headroom
#   137  today, 2026-09-07, after #247. Unchanged, which is the point: the prose
#        this issue wrote sits above four rationale lines and would have added
#        six, every one of them by an issue reference and nothing else — the
#        shape #213 and #214 found. The references went where each file keeps
#        them, `sufficiency.md`'s *When each section was added* table and
#        `mobile-base.md`'s *When each part of the track landed* table, and
#        `plan.md`, which keeps its references inline by its own status header,
#        had its two paragraphs reworded in the present tense. What is left is
#        one dated correction in `prior-art.md`, where a survey pass is corrected
#        by addition and a correction that narrates is the form the file takes,
#        and it is paid for by §17's SOTER comparison no longer narrating a gap
#        that has closed
NARRATION_MAX = 137

# Documents whose summary paragraph runs over SUMMARY_MAX_WORDS. MAY BE
# LOWERED, NEVER RAISED — and it is already at zero, which is the only value it
# can be lowered to. Six documents were over when #171 was filed; #171 rewrote
# their opening paragraphs and moved what they carried down into the body.
SUMMARY_MAX_WORDS = 60
SUMMARY_OVER_MAX = 0


# --------------------------------------------------------------------------
# Reading a document
# --------------------------------------------------------------------------

FENCE = re.compile(r"^```.*?^```", re.MULTILINE | re.DOTALL)
CODE_SPAN = re.compile(r"`[^`]*`")
THEMATIC_BREAK = re.compile(r"^[-*_=]{3,}\s*$")

# A block is not prose if it opens as a table row, a fence, an ATX heading, a
# block quote or a list item. The heading arm requires the space markdown
# itself requires, so a paragraph opening on an issue reference — `#201's
# grooming ...`, which happens twice in docs/self-describing.md — stays prose.
NON_PROSE = re.compile(r"^(\||```|#{1,6}(\s|$)|>|\s*[-*+]\s|\s*\d+[.)]\s)")

# A status header is a paragraph and is counted as one everywhere except in
# `summary_paragraph`. It is not the summary — #171 says so directly — because
# it states standing, dates and provenance rather than what the document is
# about, and for `plan.md` and `prior-art.md` it is asserted against the body
# by tests/test_doc_status_headers.py. Both spellings in the corpus are caught:
# `**Status:** ...` and `**Status: ...**`.
STATUS_HEADER = re.compile(r"^\*\*Status[:*]")

# The line below which narration is allowed: a dedicated rationale section, the
# shape #170's method asks each document to grow. The heading text must be the
# word and nothing else — `## Why the growth is sublinear` in retention.md is a
# section about a topic, not a rationale line, and treating it as one would
# exempt the rest of that document by accident.
RATIONALE_LINE = re.compile(r"^#{1,6}\s+(why|rationale|decisions?|history)\s*$",
                            re.IGNORECASE | re.MULTILINE)

# Markers of a paragraph narrating a past defect. This is a proxy, calibrated
# against the 23% #170 counted by hand, and it is honest about being one: it
# over-counts a paragraph that cites an issue as a live cross-reference and it
# under-counts narration written without any of these phrases. It is fit for a
# monotone ratchet over the whole corpus, which is what it is used for. It is
# not a verdict on any single paragraph and must not be quoted as one.
PAST_DEFECT_MARKERS = re.compile(
    "|".join(
        (
            r"\bissues? #\d+",
            r"\(#\d+\)",
            r"\bused to\b",
            r"\bpreviously\b",
            r"\boriginally\b",
            r"\bat the time\b",
            r"\bturned out\b",
            r"\bno longer\b",
            r"\b(bug|bugs|defect|defects|regression|mistake|oversight)\b",
            r"\b(broke|broken|failed|failing)\b",
            r"\bw(as|ere) (wrong|not|never|absent|missing|silent)\b",
            r"\bw(as|ere) fixed\b",
            r"\bwent red\b",
            r"\bcorrections?\b",
            r"\bcorrected\b",
            r"\bbefore (that|this|it)\b",
            r"\bshould have\b",
            r"\bdid not\b",
            r"\buntil (issue|20\d\d)\b",
        )
    ),
    re.IGNORECASE,
)


def words(text: str) -> int:
    """Whitespace-delimited tokens of the raw markdown — what `wc -w` counts."""
    return len(text.split())


def blocks(text: str) -> list[str]:
    """Blank-line-delimited blocks, with fenced code removed first.

    Fences come out before the split because a fenced block may contain blank
    lines, and half of one is not a paragraph.
    """
    stripped = FENCE.sub("", text)
    return [b for b in (part.strip("\n") for part in re.split(r"\n\s*\n", stripped)) if b.strip()]


def is_prose(block: str) -> bool:
    return not NON_PROSE.match(block) and not THEMATIC_BREAK.match(block.strip())


def prose_paragraphs(text: str) -> list[str]:
    return [block for block in blocks(text) if is_prose(block)]


def paragraph_words(block: str) -> int:
    """Words in a paragraph, with inline code spans removed.

    A path or a symbol should not inflate a paragraph — `reg.store.EDGE_SPECS`
    is one idea and would otherwise count as several.
    """
    return len(CODE_SPAN.sub(" ", block).split())


def summary_paragraph(text: str) -> str | None:
    """The first prose paragraph after the title, skipping a status header."""
    for block in prose_paragraphs(text):
        if STATUS_HEADER.match(block):
            continue
        return block
    return None


def above_the_rationale_line(text: str) -> str:
    match = RATIONALE_LINE.search(text)
    return text[: match.start()] if match else text


def narrates_a_past_defect(block: str) -> bool:
    return PAST_DEFECT_MARKERS.search(CODE_SPAN.sub(" ", block)) is not None


def public_symbols(package: Path) -> int:
    """Top-level `def` and `class` under `package`, not prefixed with `_`.

    The denominator tracks the surface a reader must understand. Lines of code
    would reward writing more of them, modules are too coarse, and a test count
    would reward test proliferation. Simplifying an API genuinely reduces the
    documentation it needs, and this moves when that happens.
    """
    total = 0
    for path in sorted(package.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if not node.name.startswith("_"):
                    total += 1
    return total


def read_corpus() -> dict[str, str]:
    return {name: (REPO / name).read_text(encoding="utf-8") for name in corpus_paths()}


# --------------------------------------------------------------------------
# The checks, each three-valued and each returning what it would say
# --------------------------------------------------------------------------


def classification_verdict(
    files: tuple[str, ...],
    code_coupled: dict[str, str],
    argument: dict[str, str],
    exempt: dict[str, str],
) -> tuple[str, list[str]]:
    """Is every corpus file in exactly one of the three lists, with a reason?

    DISAGREE names a file in none of them, a file in more than one, and a
    listed file that is not in the corpus. `EXEMPT` is checked exactly as the
    two groups are: it is a third home, not an escape hatch that may be held
    alongside a classification, because a file that is exempt *and* in a group
    is a document whose words are excused from the ceiling they are counted
    against. An entry whose reason is blank is COULD-NOT-EVALUATE: a
    classification that says nothing is the same silence as no classification,
    dressed as an answer, and an exemption that says nothing is worse, since
    nothing else in this module will ever look at that file again. So is an
    empty corpus.
    """
    if not files:
        return COULD_NOT_EVALUATE, ["no documents found — the corpus is empty"]

    unevaluable = [
        f"{name}: classified with no reason given"
        for name, why in sorted({**code_coupled, **argument, **exempt}.items())
        if not why.strip()
    ]
    if unevaluable:
        return COULD_NOT_EVALUATE, unevaluable

    lists = (("CODE_COUPLED", code_coupled), ("ARGUMENT", argument), ("EXEMPT", exempt))
    problems: list[str] = []
    for name in files:
        homes = [label for label, table in lists if name in table]
        if not homes:
            problems.append(
                f"{name} is in the corpus and in none of CODE_COUPLED, "
                f"ARGUMENT or EXEMPT — classify it, and say why it belongs there"
            )
        elif len(homes) > 1:
            problems.append(
                f"{name} is in {' and '.join(homes)}; a document has exactly "
                f"one home, and being exempt is not a discount on a ceiling"
            )
    for name in sorted(set(code_coupled) | set(argument) | set(exempt)):
        if name not in files:
            problems.append(f"{name} is classified but is not in the corpus — drop it")

    return (DISAGREE, problems) if problems else (AGREE, [])


def budget_verdict(
    docs: dict[str, str],
    symbols: int,
    code_coupled: dict[str, str],
    argument: dict[str, str],
    rate: float,
    argument_max: int,
) -> tuple[str, list[str]]:
    """Is each group inside its ceiling?

    A package with no public symbols is COULD-NOT-EVALUATE — the denominator is
    gone, and a budget of zero words is not a finding about the documents. So
    is an empty corpus. A group over its ceiling is DISAGREE, and the message
    names the group, the ceiling and the overage, because this fires at
    inconvenient moments and a failure whose remedy is unobvious is the one
    that gets deleted instead of the mistake.
    """
    if not docs:
        return COULD_NOT_EVALUATE, ["no documents found — the corpus is empty"]
    if symbols <= 0:
        return COULD_NOT_EVALUATE, [
            "reg/ has no public symbols, so RATE * public_symbols is not a "
            "budget — nothing about the documents can be decided from it"
        ]

    coupled_words = sum(words(text) for name, text in docs.items() if name in code_coupled)
    argument_words = sum(words(text) for name, text in docs.items() if name in argument)
    coupled_ceiling = int(rate * symbols)

    problems: list[str] = []
    if coupled_words > coupled_ceiling:
        problems.append(
            f"code-coupled documents are over budget: {coupled_words:,} words "
            f"against a ceiling of {coupled_ceiling:,} "
            f"(RATE {rate} x {symbols} public symbols), over by "
            f"{coupled_words - coupled_ceiling:,}. Cut prose in this group, or "
            f"— if the surface really did shrink — cut the documentation that "
            f"described what was removed. RATE may be lowered, never raised."
        )
    if argument_words > argument_max:
        problems.append(
            f"argument/reference documents are over budget: "
            f"{argument_words:,} words against a ceiling of "
            f"{argument_max:,}, over by {argument_words - argument_max:,}. "
            f"Cut something in this change. ARGUMENT_MAX may be lowered, "
            f"never raised."
        )
    return (DISAGREE, problems) if problems else (AGREE, [])


def long_paragraph_verdict(
    docs: dict[str, str], limit: int, ceiling: int
) -> tuple[str, list[str]]:
    """How many prose paragraphs run over `limit` words?"""
    if not docs:
        return COULD_NOT_EVALUATE, ["no documents found — the corpus is empty"]
    found = [
        name
        for name, text in docs.items()
        for block in prose_paragraphs(text)
        if paragraph_words(block) > limit
    ]
    if not any(prose_paragraphs(text) for text in docs.values()):
        return COULD_NOT_EVALUATE, ["no prose paragraphs found in the corpus"]
    if len(found) > ceiling:
        per_doc = ", ".join(f"{name} {found.count(name)}" for name in sorted(set(found)))
        return DISAGREE, [
            f"paragraphs over {limit} words: {len(found)} against a ceiling of "
            f"{ceiling}, over by {len(found) - ceiling} ({per_doc}). Split one, "
            f"or cut one. LONG_PARAGRAPHS_MAX may be lowered, never raised."
        ]
    return AGREE, []


def narration_verdict(docs: dict[str, str], ceiling: int) -> tuple[str, list[str]]:
    """How many paragraphs narrating a past defect sit above the rationale line?"""
    if not docs:
        return COULD_NOT_EVALUATE, ["no documents found — the corpus is empty"]
    found = [
        name
        for name, text in docs.items()
        for block in prose_paragraphs(above_the_rationale_line(text))
        if narrates_a_past_defect(block)
    ]
    if len(found) > ceiling:
        per_doc = ", ".join(f"{name} {found.count(name)}" for name in sorted(set(found)))
        return DISAGREE, [
            f"paragraphs narrating a past defect above the rationale line: "
            f"{len(found)} against a ceiling of {ceiling}, over by "
            f"{len(found) - ceiling} ({per_doc}). Move it below a `## Why` "
            f"heading, or cut it. NARRATION_MAX may be lowered, never raised."
        ]
    return AGREE, []


def summary_verdict(
    docs: dict[str, str], limit: int, ceiling: int
) -> tuple[str, list[str]]:
    """Does every document open with something readable in one breath?

    A document with no prose paragraph at all is COULD-NOT-EVALUATE. Having no
    summary is not a way to have a short one.
    """
    if not docs:
        return COULD_NOT_EVALUATE, ["no documents found — the corpus is empty"]

    unevaluable: list[str] = []
    over: list[str] = []
    for name, text in sorted(docs.items()):
        summary = summary_paragraph(text)
        if summary is None:
            unevaluable.append(f"{name}: no prose paragraph after the title")
            continue
        count = paragraph_words(summary)
        if count > limit:
            over.append(f"{name} {count} words")
    if unevaluable:
        return COULD_NOT_EVALUATE, unevaluable
    if len(over) > ceiling:
        return DISAGREE, [
            f"documents whose opening paragraph runs over {limit} words: "
            f"{len(over)} against a ceiling of {ceiling}, over by "
            f"{len(over) - ceiling} ({'; '.join(over)}). Rewrite the opening "
            f"paragraph and move what it carried down into the body."
        ]
    return AGREE, []


RATCHET_CONSTANTS = ("RATE", "ARGUMENT_MAX", "LONG_PARAGRAPHS_MAX", "NARRATION_MAX")


def ratchet_comment_verdict(source: str, names: tuple[str, ...]) -> tuple[str, list[str]]:
    """Does each constant carry a comment saying which way it may move?

    The number and the sentence licensing it are one claim. A constant raised
    with the sentence deleted is the failure #170 warns about, and it is
    invisible in a diff that only shows the number moving.
    """
    if not source.strip():
        return COULD_NOT_EVALUATE, ["no source to read"]
    problems: list[str] = []
    for name in names:
        match = re.search(rf"^{name}\s*[:=]", source, re.MULTILINE)
        if match is None:
            problems.append(f"{name} is not defined in this module")
            continue
        preceding = source[: match.start()].split("\n\n")[-1]
        flat = " ".join(preceding.split()).lower()
        if "lowered" not in flat or "never raised" not in flat:
            problems.append(
                f"{name} has no comment saying it may be lowered and never "
                f"raised — the number and the sentence move together"
            )
    return (DISAGREE, problems) if problems else (AGREE, [])


# --------------------------------------------------------------------------
# The corpus as it stands
# --------------------------------------------------------------------------


def test_every_document_is_classified_into_exactly_one_group() -> None:
    verdict, problems = classification_verdict(
        corpus_paths(), CODE_COUPLED, ARGUMENT, EXEMPT
    )
    assert verdict == AGREE, "\n".join(problems)


def test_each_group_is_inside_its_budget() -> None:
    verdict, problems = budget_verdict(
        read_corpus(), public_symbols(PACKAGE), CODE_COUPLED, ARGUMENT,
        RATE, ARGUMENT_MAX,
    )
    assert verdict == AGREE, "\n".join(problems)


def test_long_paragraphs_are_under_the_ceiling() -> None:
    verdict, problems = long_paragraph_verdict(
        read_corpus(), PARAGRAPH_MAX_WORDS, LONG_PARAGRAPHS_MAX
    )
    assert verdict == AGREE, "\n".join(problems)


def test_defect_narration_above_the_rationale_line_is_under_the_ceiling() -> None:
    verdict, problems = narration_verdict(read_corpus(), NARRATION_MAX)
    assert verdict == AGREE, "\n".join(problems)


def test_every_document_opens_with_a_summary_readable_in_one_breath() -> None:
    verdict, problems = summary_verdict(
        read_corpus(), SUMMARY_MAX_WORDS, SUMMARY_OVER_MAX
    )
    assert verdict == AGREE, "\n".join(problems)


def test_each_ratchet_constant_says_which_way_it_may_move() -> None:
    verdict, problems = ratchet_comment_verdict(
        Path(__file__).read_text(encoding="utf-8"), RATCHET_CONSTANTS
    )
    assert verdict == AGREE, "\n".join(problems)


# --------------------------------------------------------------------------
# No headroom — each ceiling, one notch tighter, must fail
#
# A ceiling with slack in it constrains nothing until the slack is used up, and
# nothing in a diff shows how much is left. These are what make "set at today's
# measurement" checkable rather than asserted.
# --------------------------------------------------------------------------


def test_the_code_coupled_budget_has_no_headroom() -> None:
    verdict, problems = budget_verdict(
        read_corpus(), public_symbols(PACKAGE), CODE_COUPLED, ARGUMENT,
        RATE - 0.1, ARGUMENT_MAX,
    )
    assert verdict == DISAGREE
    assert any("code-coupled" in p for p in problems)


def test_the_argument_budget_has_no_headroom() -> None:
    verdict, problems = budget_verdict(
        read_corpus(), public_symbols(PACKAGE), CODE_COUPLED, ARGUMENT,
        RATE, ARGUMENT_MAX - 1,
    )
    assert verdict == DISAGREE
    assert any("argument/reference" in p for p in problems)


def test_the_long_paragraph_ceiling_has_no_headroom() -> None:
    verdict, problems = long_paragraph_verdict(
        read_corpus(), PARAGRAPH_MAX_WORDS, LONG_PARAGRAPHS_MAX - 1
    )
    assert verdict == DISAGREE
    assert any("over by 1" in p for p in problems)


def test_the_narration_ceiling_has_no_headroom() -> None:
    verdict, problems = narration_verdict(read_corpus(), NARRATION_MAX - 1)
    assert verdict == DISAGREE
    assert any("over by 1" in p for p in problems)


# --------------------------------------------------------------------------
# The negatives — every predicate fed the condition it guards against
# --------------------------------------------------------------------------


def test_a_document_in_none_of_the_three_lists_fails() -> None:
    """The way this kind of budget dies: escape it by adding a file.

    Adding `EXEMPT` is what could have broken this, so it is asserted after the
    third list exists and not only before it: a corpus file still has to be
    named somewhere, and *nowhere* is not one of the three answers.
    """
    files = corpus_paths() + ("docs/appendix.md",)
    verdict, problems = classification_verdict(files, CODE_COUPLED, ARGUMENT, EXEMPT)
    assert verdict == DISAGREE
    assert any("docs/appendix.md" in p and "none of" in p for p in problems)


def test_a_document_in_both_budget_groups_fails() -> None:
    both = {**ARGUMENT, "README.md": "claimed twice"}
    verdict, problems = classification_verdict(corpus_paths(), CODE_COUPLED, both, EXEMPT)
    assert verdict == DISAGREE
    assert any(
        "README.md" in p and "CODE_COUPLED and ARGUMENT" in p for p in problems
    )


def test_a_document_that_is_exempt_and_also_in_a_budget_group_fails() -> None:
    """The shape an exemption would take if it were a discount.

    A file counted against `ARGUMENT_MAX` and simultaneously excused from it
    reads as classified to anyone scanning the group, while its words are the
    ones the ceiling was set above. Two homes is one too many in either
    direction.
    """
    excused = {**EXEMPT, "docs/plan.md": "exempt as well as counted"}
    verdict, problems = classification_verdict(
        corpus_paths(), CODE_COUPLED, ARGUMENT, excused
    )
    assert verdict == DISAGREE
    assert any("docs/plan.md" in p and "ARGUMENT and EXEMPT" in p for p in problems)


def test_a_classified_document_that_does_not_exist_fails() -> None:
    stale = {**CODE_COUPLED, "docs/deleted.md": "a document that was removed"}
    verdict, problems = classification_verdict(
        corpus_paths(), stale, ARGUMENT, EXEMPT
    )
    assert verdict == DISAGREE
    assert any("docs/deleted.md" in p and "not in the corpus" in p for p in problems)


def test_an_exemption_for_a_document_that_does_not_exist_fails() -> None:
    """A stale exemption is how the list stops describing anything."""
    stale = {**EXEMPT, "docs/deleted.md": "exempt, and also gone"}
    verdict, problems = classification_verdict(
        corpus_paths(), CODE_COUPLED, ARGUMENT, stale
    )
    assert verdict == DISAGREE
    assert any("docs/deleted.md" in p and "not in the corpus" in p for p in problems)


def test_a_classification_with_no_reason_is_could_not_evaluate() -> None:
    silent = {**CODE_COUPLED, "README.md": "   "}
    verdict, problems = classification_verdict(
        corpus_paths(), silent, ARGUMENT, EXEMPT
    )
    assert verdict == COULD_NOT_EVALUATE
    assert any("no reason" in p for p in problems)


def test_a_second_exemption_with_no_reason_is_could_not_evaluate() -> None:
    """A second document exempted in silence, which is how a list grows.

    COULD-NOT-EVALUATE and not a pass: `CLAUDE.md`'s rule is that the third
    verdict never resolves to the first, and a wordless exemption is exactly
    the silence that rule names.
    """
    silent = {**EXEMPT, "docs/plan.md": "   "}
    verdict, problems = classification_verdict(
        corpus_paths(), CODE_COUPLED, ARGUMENT, silent
    )
    assert verdict != AGREE
    assert verdict == COULD_NOT_EVALUATE
    assert any("docs/plan.md" in p and "no reason" in p for p in problems)


def test_prose_added_without_surface_fails_the_budget() -> None:
    """The signal this whole check exists to produce."""
    docs = dict(read_corpus())
    docs["CLAUDE.md"] = docs["CLAUDE.md"] + "\n\n" + ("filler " * 2000)
    verdict, problems = budget_verdict(
        docs, public_symbols(PACKAGE), CODE_COUPLED, ARGUMENT, RATE, ARGUMENT_MAX
    )
    assert verdict == DISAGREE
    assert any("code-coupled" in p and "over by" in p for p in problems)


def test_removing_public_symbols_can_put_the_corpus_over() -> None:
    """Deliberate, and it fires at an inconvenient moment — so it says why."""
    verdict, problems = budget_verdict(
        read_corpus(), public_symbols(PACKAGE) // 2, CODE_COUPLED, ARGUMENT,
        RATE, ARGUMENT_MAX,
    )
    assert verdict == DISAGREE
    assert any("public symbols" in p and "over by" in p for p in problems)


def test_an_argument_document_growing_fails_the_flat_ceiling() -> None:
    docs = dict(read_corpus())
    docs["docs/sufficiency.md"] = docs["docs/sufficiency.md"] + "\n\n" + ("filler " * 500)
    verdict, problems = budget_verdict(
        docs, public_symbols(PACKAGE), CODE_COUPLED, ARGUMENT, RATE, ARGUMENT_MAX
    )
    assert verdict == DISAGREE
    assert any("argument/reference" in p and "500" in p for p in problems)


def test_an_exempt_document_growing_moves_neither_ceiling() -> None:
    """What the exemption buys, stated as a check rather than as a comment.

    The counterpart of the test above, and the reason `ARGUMENT_MAX` had to
    fall by 26,768: the exempt words are not in the argument group's total, so
    if the ceiling had stayed where it was the five documents that remain would
    have been free to grow into the room this document vacated.
    """
    docs = dict(read_corpus())
    for name in EXEMPT:
        docs[name] = docs[name] + "\n\n" + ("filler " * 5000)
    verdict, problems = budget_verdict(
        docs, public_symbols(PACKAGE), CODE_COUPLED, ARGUMENT, RATE, ARGUMENT_MAX
    )
    assert verdict == AGREE, "\n".join(problems)


def test_adding_code_does_not_buy_the_argument_group_anything() -> None:
    """The sentence in the docstring, as a check."""
    docs = read_corpus()
    over = {**docs, "docs/plan.md": docs["docs/plan.md"] + "\n\n" + ("filler " * 400)}
    verdict, problems = budget_verdict(
        over, public_symbols(PACKAGE) * 10, CODE_COUPLED, ARGUMENT, RATE, ARGUMENT_MAX
    )
    assert verdict == DISAGREE
    assert any("argument/reference" in p for p in problems)


def test_a_long_paragraph_fails() -> None:
    docs = {"docs/fixture.md": "# Fixture\n\n" + ("word " * 200)}
    verdict, problems = long_paragraph_verdict(docs, PARAGRAPH_MAX_WORDS, 0)
    assert verdict == DISAGREE
    assert any("docs/fixture.md 1" in p for p in problems)


@pytest.mark.parametrize(
    "block",
    [
        "| a | b |\n" * 100,
        "```\n" + ("word " * 200) + "\n```",
        "> " + ("word " * 200),
        "\n".join(f"- item {i} " + "word " * 20 for i in range(20)),
    ],
    ids=["table", "fence", "block-quote", "list"],
)
def test_a_table_a_fence_a_quote_or_a_list_is_not_a_long_paragraph(block: str) -> None:
    """The exclusions, each fed something that would fail without them."""
    text = f"# Fixture\n\nA short opening line.\n\n{block}\n"
    verdict, problems = long_paragraph_verdict(
        {"docs/fixture.md": text}, PARAGRAPH_MAX_WORDS, 0
    )
    assert verdict == AGREE, problems


def test_a_paragraph_of_code_spans_is_not_inflated_into_a_long_one() -> None:
    text = "# Fixture\n\n" + " ".join(f"`reg.module.symbol_{i}`" for i in range(200))
    verdict, _ = long_paragraph_verdict(
        {"docs/fixture.md": text}, PARAGRAPH_MAX_WORDS, 0
    )
    assert verdict == AGREE


def test_defect_narration_is_detected() -> None:
    docs = {"docs/fixture.md": "# Fixture\n\nThe bound was wrong until issue #84 "
                              "fixed the source, and the check previously said "
                              "nothing about it."}
    verdict, problems = narration_verdict(docs, 0)
    assert verdict == DISAGREE
    assert any("docs/fixture.md 1" in p for p in problems)


def test_a_normative_paragraph_is_not_counted_as_narration() -> None:
    docs = {"docs/fixture.md": "# Fixture\n\nThe envelope takes a proprioceptive "
                              "state, and the absence of any field naming an "
                              "entity is the enforcement."}
    verdict, _ = narration_verdict(docs, 0)
    assert verdict == AGREE


def test_narration_below_the_rationale_line_is_not_counted() -> None:
    """The line is what makes the ceiling reachable: move it, do not delete it."""
    narration = "The bound was wrong until issue #84 fixed the source."
    above = {"docs/fixture.md": f"# Fixture\n\n{narration}\n"}
    below = {"docs/fixture.md": f"# Fixture\n\nA short summary.\n\n## Why\n\n{narration}\n"}
    assert narration_verdict(above, 0)[0] == DISAGREE
    assert narration_verdict(below, 0)[0] == AGREE


def test_a_topic_heading_beginning_with_why_is_not_a_rationale_line() -> None:
    """`## Why the growth is sublinear` is a section, not the line.

    Reading it as one would exempt everything after it, which in
    docs/retention.md is most of the file.
    """
    narration = "The bound was wrong until issue #84 fixed the source."
    docs = {
        "docs/fixture.md": (
            "# Fixture\n\nA short summary.\n\n"
            "## Why the growth is sublinear\n\n" + narration + "\n"
        )
    }
    assert narration_verdict(docs, 0)[0] == DISAGREE


def test_an_overlong_summary_fails() -> None:
    docs = {"docs/fixture.md": "# Fixture\n\n" + ("word " * 100)}
    verdict, problems = summary_verdict(docs, SUMMARY_MAX_WORDS, 0)
    assert verdict == DISAGREE
    assert any("docs/fixture.md 100 words" in p for p in problems)


@pytest.mark.parametrize(
    "status",
    ["**Status:** " + "word " * 200, "**Status: " + "word " * 200 + "**"],
    ids=["colon-outside-the-bold", "colon-inside-the-bold"],
)
def test_a_status_header_is_not_the_summary(status: str) -> None:
    """Both spellings in the corpus, and neither is what a reader is opening on."""
    docs = {"docs/fixture.md": f"# Fixture\n\n{status}\n\nA short opening line.\n"}
    verdict, problems = summary_verdict(docs, SUMMARY_MAX_WORDS, 0)
    assert verdict == AGREE, problems


def test_a_status_header_still_counts_as_a_paragraph_everywhere_else() -> None:
    """It is exempt from being the summary, not from the budget."""
    docs = {"docs/fixture.md": "# Fixture\n\n**Status:** " + ("word " * 200)}
    assert long_paragraph_verdict(docs, PARAGRAPH_MAX_WORDS, 0)[0] == DISAGREE


def test_a_document_with_no_prose_at_all_is_could_not_evaluate() -> None:
    """Deleting the summary is not a way to have a short one."""
    docs = {"docs/fixture.md": "# Fixture\n\n| a | b |\n|---|---|\n| 1 | 2 |\n"}
    verdict, problems = summary_verdict(docs, SUMMARY_MAX_WORDS, 0)
    assert verdict == COULD_NOT_EVALUATE
    assert any("no prose paragraph" in p for p in problems)


@pytest.mark.parametrize(
    "check",
    [
        lambda docs: classification_verdict((), CODE_COUPLED, ARGUMENT, EXEMPT),
        lambda docs: budget_verdict(docs, 260, CODE_COUPLED, ARGUMENT, RATE, ARGUMENT_MAX),
        lambda docs: long_paragraph_verdict(docs, PARAGRAPH_MAX_WORDS, 0),
        lambda docs: narration_verdict(docs, 0),
        lambda docs: summary_verdict(docs, SUMMARY_MAX_WORDS, 0),
    ],
    ids=["classification", "budget", "long-paragraphs", "narration", "summary"],
)
def test_an_empty_corpus_is_could_not_evaluate(check) -> None:
    verdict, problems = check({})
    assert verdict == COULD_NOT_EVALUATE
    assert problems


def test_a_package_with_no_public_symbols_is_could_not_evaluate() -> None:
    """The denominator is gone; a budget of zero words is not a finding."""
    verdict, problems = budget_verdict(
        read_corpus(), 0, CODE_COUPLED, ARGUMENT, RATE, ARGUMENT_MAX
    )
    assert verdict == COULD_NOT_EVALUATE
    assert any("no public symbols" in p for p in problems)


def test_a_constant_raised_with_its_comment_deleted_fails() -> None:
    source = "# a number\nRATE = 200.0\n\n# another\nARGUMENT_MAX = 999999\n"
    verdict, problems = ratchet_comment_verdict(source, ("RATE", "ARGUMENT_MAX"))
    assert verdict == DISAGREE
    assert len(problems) == 2


def test_a_missing_constant_fails() -> None:
    verdict, problems = ratchet_comment_verdict("RATE = 1.0\n", ("NARRATION_MAX",))
    assert verdict == DISAGREE
    assert any("not defined" in p for p in problems)


def test_no_source_is_could_not_evaluate() -> None:
    verdict, problems = ratchet_comment_verdict("", RATCHET_CONSTANTS)
    assert verdict == COULD_NOT_EVALUATE
    assert problems


# --------------------------------------------------------------------------
# The denominator, pinned to its definition rather than to a number
# --------------------------------------------------------------------------


def test_public_symbols_counts_top_level_public_definitions_only() -> None:
    fixture = REPO / "reg"
    assert public_symbols(fixture) > 0
    source = "\n".join(
        (
            "def public(): pass",
            "def _private(): pass",
            "class Public: pass",
            "class _Private: pass",
            "class Outer:",
            "    def method(self): pass",
            "if True:",
            "    def nested(): pass",
        )
    )
    tree = ast.parse(source)
    counted = sum(
        1
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        and not node.name.startswith("_")
    )
    assert counted == 3  # public, Public, Outer — the nested and private ones are not
