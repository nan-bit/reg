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
# documents left behind no room. See ARGUMENT_MAX below. #244 is this
# mechanism's second use: `CLAUDE.md` leaves the code-coupled group and the
# ceiling is re-measured over the six documents that remain (see the RATE log
# row), which is the origin #170 tier 6 one click away.
EXEMPT: dict[str, str] = {
    "CLAUDE.md": (
        "The conventions the code must follow, and the only file the "
        "unattended writer reads by default — its three rules are the ones "
        "this repository calls structural. The budget's premise is that a "
        "document should shrink when the thing it describes simplifies, and "
        "the ceiling rewards doing exactly that; a document that must not "
        "shrink into pointers cannot sit under it, because a rule turned into "
        "a pointer may be a rule the next agent never reads — whether links "
        "inside `CLAUDE.md` are followed was investigated on 2026-09-11 (#244) "
        "and could not be settled from retained evidence. Decision D5 (#270) "
        "leaves the file whole, so the file leaves the budget. It is exempt "
        "from the *budget* only: the paragraph and narration ceilings still "
        "count its paragraphs, as `docs/prior-art.md`'s entry records."
    ),
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
#   85.6  today, 2026-09-07, after #230 priced the three outer-boundary
#         retention options. `reg.bench` gained seven public symbols — the
#         study, the per-level costing, the boundary recomputation, the
#         movement arithmetic and their three result types — against 443 words
#         in `docs/self-describing.md` §8, which is where the measurement is
#         published and where the decision will be taken. 26,532 / 310 = 85.59,
#         rounded up to the next tenth. The prose is a table and three
#         paragraphs about it, and it sits below that file's rationale line
#         where §8 already lives
#   85.5  today, 2026-09-07, after #249 priced the two layer-basis
#         granularities. `reg.bench` gained seven public symbols again — the
#         study, the per-level costing, the two basis derivations, and their
#         three result types — against 551 words in `docs/self-describing.md`
#         §8, which is where the measurement is published and where the
#         decision will be taken. 27,083 / 317 = 85.44, rounded up to the next
#         tenth. It is the same shape as #230 one tier up and it is paid for
#         the same way, in the same file, below the same rationale line; what
#         it did *not* need is a second statement of the finding, because the
#         report `reg.bench` writes carries the argument and §8 carries the
#         numbers a decision is taken from
#   84.2  today, 2026-09-09, after #125 gave the artifact the three keys
#         `docs/limitations.md` §8's obligations were disclosed in prose only.
#         `reg.identity` gained four public symbols — the two enums, the notice
#         and `Disclosures` — against no new code-coupled prose at all, so the
#         denominator moved and the numerator did not. 27,349 / 325 = 84.15,
#         rounded up to the next tenth. Lowered rather than left: a rate that
#         falls because the surface grew under fixed prose is a rate that has
#         fallen, and holding it would bank room no diff would show
#   85.2  2026-09-08, after #252 adopted the layer basis per edge.
#         `reg.store` gained thirteen public symbols and `reg.envelope` one,
#         against the prose that closes `self-describing.md` §1 gap 1 and its
#         §8 tier 4, `sensor-baseline.md`'s republished ladder and `README.md`'s
#         republished headline. 27,329 / 321 = 85.14, rounded up to the next
#         tenth. The symbols are what the file now carries — a table, a row
#         type, the arithmetic over it and the four input names — so the
#         denominator moved for the same reason the prose did
#   84.1  today, 2026-09-10, after #258 answered the pointwise reachability
#         question from the boundary #257 retained. `reg.query` gained four
#         public symbols — `reached_point`, `pointwise_coverage` and the two
#         answer shapes `ReachedPoint` and `PointwiseCoverage` — against 281
#         words in `docs/self-describing.md`, split between §1's gap 3, §2's
#         table and negatives, and §8's tier 5. 27,646 / 329 = 84.02, rounded
#         up to the next tenth. This is the #220 case a third time: the prose
#         describes the symbols, so the denominator moved with it. Most of the
#         new words sit below that file's rationale line, in §8, which is why
#         the narration ceiling did not move
#   84.1  today, 2026-09-11, after #262 gave the cold read its seventh row.
#         Unchanged and re-measured: `reg/query.py` gained no top-level
#         definition — the row is a claim id, three `meta` keys and a private
#         builder — so the denominator held at 329 while
#         `docs/self-describing.md` went 6,066 -> 6,053. §2's table row, its
#         sentence on why this is a claim and not a state, and §8 tier 3's
#         provenance were paid for inside the same file and thirteen words
#         over: §1 gap 2 stopped restating `limitations.md` §1's three states
#         and §3's own numpy bullet, and its restatement of §8 tier 2's split
#         went with them. 27,655 / 329 = 84.05, and 84.0 is not available — it
#         would put the ceiling at 27,636, under the corpus — so 84.1 is the
#         tightest tenth and the thirteen words are not banked headroom
#   84.1  today, 2026-09-11, after #271 made the front page's demo run. Unchanged
#         and re-measured: `README.md` went 3,577 -> 3,556 while the denominator
#         held at 330. The three disclosure flags `reg.graph build` has required
#         since #125 were added to both of its builds, and paid for inside the
#         same file by the Status section's *Built.* paragraph, which listed
#         what the four claims above it already name. 27,725 / 330 = 84.02, and
#         84.0 is not available — it would put the ceiling at 27,720, under the
#         corpus — so 84.1 is the tightest tenth and the twenty-seven words are
#         not banked headroom
#   83.9  today, 2026-09-12, after #273 retired the no-Layer-A ratio and
#         re-measured the scaling ladder. `README.md` went 3,556 -> 3,524, the
#         Claim 1 row losing the sentence that carried the retired figure and
#         its condition, and `docs/sensor-baseline.md` went 6,163 -> 6,140: the
#         corrected cause of the sublinear growth and the corrected pointer at
#         `lossiness.md` cost 32 words and were paid for and twenty-three over, by
#         three restatements — *What is actually published* restating the table
#         row directly above it, *Sensitivity* restating the linearity that
#         paragraph states, and a third telling of `limitations.md` §5 inside
#         one section. 27,670 / 330 = 83.85, rounded up to the next tenth. The
#         denominator did not move: this change is documents and tests only
#   72.6  today, 2026-09-14, after #275 cut `docs/self-describing.md` to what
#         the file still needs a document for: 6,144 -> 2,430, every tier of its
#         §8 having landed. §1's gap table and narrative, §2's two restated
#         tables and its list of the negatives, §3's cost table, §5, the
#         sixth-pass summary and §7's two answered questions are pointers or
#         gone, and §8's two costing tables are their findings beside a pointer
#         at the PRs that carry them dated. 23,956 / 330 = 72.59, rounded up to
#         the next tenth. This is the largest step this ratchet has taken and it
#         is the cheapest kind: the prose describes a build that finished, so
#         the denominator did not move and nothing it described was removed
#   61.1  today, 2026-09-16, after #276 cut `docs/mobile-base.md` to what the
#         file still needs a document for: 8,171 -> 4,382, every tier of its §7
#         having landed. §7's *State* column and its narration, §7.1's account of
#         what Tier 4 ships, §7.2's fixture descriptions (`python -m reg.sim
#         --list` prints them), §6's table, §3's construction and literature
#         paragraphs, §2's restatement of `sufficiency.md` §5.6 and §4's ten
#         prose items are pointers, one line each, or gone. `docs/README.md`'s
#         row for the file went -4 with them, because it described the same track
#         as half-built. 20,163 / 330 = 61.10 exactly — measured, no headroom,
#         and the tenth below would put the ceiling at 20,130, under the corpus.
#         Second-largest step this ratchet has taken and the same cheap
#         kind as #275's: the denominator did not move, because a design
#         document's tiers landing removes no symbol
#   55.3  today, 2026-09-27, after #279: `docs/sensor-baseline.md` 6,066 ->
#         4,162. The cut is the duplicated tables and the Why history — the
#         linearity note, the six-month table (now a pointer at `retention.md`
#         and `limitations.md` §5), the sublinear-growth paragraph #273 had
#         corrected, the air-gap history, and the whole ## Why — with every
#         guarded table kept. 18,242 / 330 = 55.28, rounded up to the next
#         tenth. Measured, no headroom.
#   46.2  today, 2026-09-27, after #244 exempted `CLAUDE.md` from the word
#         budget (decision D5, #270 — the file stays whole, so it leaves the
#         group). This is the trap #237's row documents for the argument group
#         (#170 tier 6), applied to the code-coupled group: a document leaving
#         takes its words out of the ceiling with it. `CLAUDE.md`'s 2,321 words
#         are gone from the numerator and nothing else moved; the six documents
#         that remain are 15,227 / 330 = 46.14, rounded up to the next tenth.
#         Measured, no headroom.
#
#   53.2  today, 2026-09-27, after #280: the entry points — `README.md`
#         3,467 -> 3,093 (claims rows 3-4 condensed, the honesty note, the
#         Status section and *How work happens* now pointers), plus
#         `docs/CONTRIBUTING.md` 704 -> 366 (the CLAUDE.md copy becomes
#         pointers). 17,545 / 330 = 53.17, rounded up to the next tenth.
#         Measured, no headroom.
#
# The step to 78.2 is the finding #171 was regroomed to state: code-coupled
# prose grew 29% while the surface it describes grew 3%, which is the exact
# thing this budget exists to catch. The step from there to 94.5 is not a
# second raise in density — it is the same corpus counted with
# `docs/self-describing.md` in the group the regroom put it in.
#
# **62.7 was the number to get back under, and 61.1 is under it** — reached by
# the two design documents whose build orders finished, #275 and #276, not by a
# cut to the prose that describes the package. It is separate from ARGUMENT_MAX
# because these words track the package and those words track how much there is
# to argue; see the module docstring.
#   44.3  today, 2026-09-27, after #295: `docs/sensor-baseline.md` 4,162 ->
#         3,584 (the incumbent-encoding methodology condensed to its tables:
#         the validation procedure to a reproduction pointer, the retire-this-
#         section to one sentence, the air-gap premise to its retirement
#         record, the Assumptions list roughly halved). Code-coupled words
#         15,227 -> 14,592; 14,592 / 330 = 44.22, rounded up to the next
#         tenth. Measured, no headroom.
#   44.2  today, 2026-09-28, after #304: the baseline composition became
#         single-source-of-truth — `README.md`'s restatement replaced by a
#         link to `docs/sensor-baseline.md`. Code-coupled words
#         14,592 -> 14,568; 14,568 / 330 = 44.15, rounded up to the next
#         tenth. Measured, no headroom.
#   43.3  today, 2026-09-28, after #296: `docs/self-describing.md` §8
#         396 -> 94 words (the build order to its landed statement: the
#         dated tier table, "Where the costings are", and the two tier-4/5
#         costing paragraphs cut; the dated tables live on in PRs #250/#251).
#         Code-coupled words 14,568 -> 14,266; 14,266 / 330 = 43.23,
#         rounded up to the next tenth. Measured, no headroom.
#   41.5  today, 2026-09-28, after #297: `docs/mobile-base.md`'s `## Why`
#         539 -> 22 words (the 24-row landing table and the precedent-setting
#         paragraph cut to a one-line retirement stub) and §6 107 -> 22 words
#         (a pointer at `prior-art.md` §21–§25). Code-coupled words
#         14,266 -> 13,672; 13,672 / 330 = 41.44, rounded up to the next
#         tenth. Measured, no headroom.
RATE = 41.5

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
#   47,132  today, 2026-09-08, after #252 made the layer tag the weakest of its
#           inputs. `limitations.md` §11's first gap closed and §12's first two
#           rows with it, `sufficiency.md` §5.8 and §5.9 record where the two
#           cases were settled together, `lossiness.md` *Retained* #9 gained the
#           basis, and `retention.md` is republished throughout. Paid for
#           entirely out of what closing a gap made redundant: §11's account of
#           a tag that does not follow its value, and §12's restatement of §1's
#           environment argument, are both gone. Thirty-two words lower than the
#           last ceiling rather than level with it, for the reason the #233 row
#           gives — measured, no headroom
#   47,131  today, 2026-09-08, after #253 retired Claim 3's condition. The basis
#           had landed, so `plan.md`'s claim and `sufficiency.md`'s normative
#           restatement of it say what the file now carries — the basis beside
#           the tag, per edge — instead of naming an absence and the issue that
#           would end it. It costs one word less than the condition did:
#           `plan.md` -1, and `sufficiency.md` level, its clause going -2 and
#           its `## Why` provenance row +2 to record the retirement beside the
#           condition. One word lower than the last ceiling rather than level
#           with it, for the reason the #233 row gives — measured, no headroom
#   47,129  today, 2026-09-09, after #125. `docs/limitations.md` §8 gained the
#           three `meta` keys the deployer now states, the vocabulary each takes
#           and the sentence that recording is not discharging, and it gained
#           the retention basis as a gap that stays open. Paid for inside the
#           same section: the minimisation paragraph and *What a claim would
#           need instead* stopped restating themselves, the bullet on the four
#           retention rules folded into the paragraph about the basis it was
#           half of, and three bullets lost a clause each. Two words below the
#           last ceiling rather than level with it — measured, no headroom
#   47,127  today, 2026-09-09, after #257 retained the outer boundary and
#           republished every figure that moved. The four documents this group
#           holds that state the retention rule gained a clause each; it was
#           paid for by the restatement those clauses made redundant —
#           `limitations.md` §12's per-gap narratives of the two closed gaps
#           folded into one paragraph pointing at §1 and §11, `lossiness.md`
#           *Discarded* #9's outer-scalar clause became the rule it now shares
#           with the inner polygon, and §2's two-directions bullet stopped
#           saying the recomputation twice. Two words below the last ceiling
#           rather than level with it — measured, no headroom
#   47,125  today, 2026-09-11, after #271 replaced `plan.md` Phase 5's copy of
#           the build command with a pointer at the README's *Reading an
#           incident*, which is now run by `tests/test_readme.py`. A copy is how
#           that command went stale — it had been missing the three flags #125
#           made required. The pointer is three words shorter than the command
#           it replaces and the sentence under it gained one naming the
#           disclosure flags beside the identity ones, so the section went -2.
#           Two words below the last ceiling — measured, no headroom
#   47,035  today, 2026-09-12, after #273 retired the no-Layer-A ratio and
#           re-measured the scaling ladder. `docs/retention.md` went 6,070 ->
#           5,973 and `docs/plan.md` 8,484 -> 8,491. The ladder lost a rung and
#           the figures derived from it, and the retired figure's condition —
#           stated at both ends of one subsection, which is the restatement the
#           #233 row named and did not finish — became one sentence saying no
#           ratio is published from the ladder. The dated account of the
#           retirement was cut rather than kept: issue #273 carries it. `plan.md`
#           pays seven for stating the Layer-A condition where the retired
#           figure stood. Ninety words below the last ceiling rather than level
#           with it, for the reason the #233 row gives — measured, no headroom
#   47,027  today, 2026-09-16, after #286 retired the boundary-coverage ratio.
#           `docs/limitations.md` went 10,224 -> 10,216, and it is the only
#           file in this group the change touches. §12's last paragraph stopped
#           naming a tier that had landed and stopped restating
#           `self-describing.md`'s build order; both are one pointer now, at §8's
#           tier lines and at §3. The gap-3 sentence pays for its pointer at PR
#           #250 out of the retired ratio's own words. Eight words lower than
#           the last ceiling rather than level with it, for the reason the #233
#           row gives — measured, no headroom
#   46,936  today, 2026-09-16, after #276 corrected the stale mobile-base status
#           in the two normative documents. `docs/limitations.md` went 10,216 ->
#           10,150 and `docs/sufficiency.md` 11,532 -> 11,507. This group has no
#           headroom, so each correction states the current fact in fewer words
#           than the stale one: §9's *What* stopped saying the tree models no
#           pose and stopped calling the design document unbuilt, §9's *What this
#           half is* stopped holding Tier 1 pending, §11's `## Why` stopped
#           holding open a decision #252 took, and `sufficiency.md` §5.8 stopped
#           resting on *no fixture is mobile* and on an `Enforcer` that refuses a
#           driven base. Ninety-one words lower than the last ceiling rather than
#           level with it, for the reason the #233 row gives — measured, no
#           headroom
#   46,866  today, 2026-09-26, finishing #276's correction pass: the Sep 16
#           commit missed two stale sentences in `docs/sufficiency.md`, and both
#           said the same false thing the pass had already corrected elsewhere.
#           §5.9's *What remains unbuilt* still claimed nothing maps a
#           `VelocitySource` to a `Layer` and rested on *no fixture is mobile* —
#           #252 took the mapping and the four fixtures build — and the *See
#           also* entry still called `docs/mobile-base.md` a design document
#           with nothing built behind it. `docs/sufficiency.md` went 11,507 ->
#           11,437. Seventy words lower than the last ceiling rather than level
#           with it, for the reason the #233 row gives — measured, no headroom
#   44,640  today, 2026-09-26, after #277 corrected what the code contradicts
#           and cut what the file carries in `docs/plan.md`. `docs/plan.md`
#           went 8,491 -> 6,265: the amendments, the Claim 1 composition and
#           derived-arithmetic narration, the mandated-window paragraph, Claim
#           3's *Why*, Claim 4's re-issuance section, the stale architecture
#           tree, the Declaration and Verdict dataclasses, the Phase 5 schema
#           tables and lossiness blockquote, Phase 6's honesty note, Phase 7's
#           fake output, Phase 9's table, the build-order table and the
#           implementing-agent notes. Two thousand two hundred twenty-six words
#           lower than the last ceiling rather than level with it, for the
#           reason the #233 row gives — measured, no headroom
#   44,688  today, 2026-09-26, after restoring the one paragraph the issue
#           keeps: `60.85 MB/h` with 50 Hz, which `tests/test_bench.py`
#           requires in `docs/plan.md`. The "derived, not measured" paragraph
#           stays cut; the figure now lives in a 48-word paragraph stating the
#           measured rate, its control rate and the pointer at `retention.md`.
#           Forty-eight words above the last ceiling rather than level with
#           it, for the reason the #233 row gives — measured, no headroom
#   41,892  today, 2026-09-27, after #278: `docs/retention.md` lost ~2,700
#           words of figure-move and history narration — the status line, the
#           reframing archaeology, the parameter history, the sensitivity
#           numbers, the marginal-cost account, the superseded 2.51x, the
#           kept-for-the-record criterion — and the surviving rationale moved
#           under a plain `## Why`. Measured, no headroom, for the reason the
#           #233 row gives
#   41,891  2026-09-27, #278 follow-up: restoring the "24 columns, 19 of them
#           Layer B" composition `test_baseline_stream_description.py` requires
#           cost a net 1 word after tightening the `## Why` prose to stay under
#           the ceiling. Measured, no headroom.
#   41,211  today, 2026-09-27, after #294: `docs/retention.md` lost the Why
#           history paragraphs, the sublinear-growth analysis (the numbered
#           items, the 5.0x paragraph, the "no longer a document's job"
#           paragraph — `reg.bench` prints the attribution at every rung now),
#           and the candidate-label deliberation table. Measured, no headroom.
#   41,222  2026-09-27, #294 follow-up: the Why stub keeps one pointer sentence
#           at prior-art.md §8 and lossiness.md — `test_retention_why_is_a_section`
#           requires the section to point at both, and the pointers are live
#           cross-references, not history. Measured, no headroom.
#   41,233  2026-09-27, #294 follow-up 2: the "24 columns / 19 Layer B"
#           composition `test_baseline_stream_description.py` requires moved
#           from the cut "Claim 1 lost" paragraph to the Layer-A comparison
#           prose — a document naming the baseline must say what it holds.
#           Measured, no headroom.
#   41,205  today, 2026-09-28, after #304: the composition is stated once, in
#           `docs/sensor-baseline.md` — `docs/plan.md`, `docs/limitations.md`,
#           `docs/lossiness.md` and `docs/retention.md` link it instead of
#           restating it (`docs/prior-art.md`'s three restatements leave with
#           it; that file is exempt from this budget). Measured, no headroom.
#   41,205  today, 2026-09-28, after #297: re-measured at 41,205 —
#           `docs/mobile-base.md` is code-coupled, not in this group, so the
#           Why/§6 cuts moved nothing here. Confirmed, not lowered.
ARGUMENT_MAX = 41205

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
#    89  today, 2026-09-08, after #252: `docs/limitations.md` went 17 -> 15 and
#        three files went up by one each. The two that fell are §11's account of
#        the gap that closed and §12's restatement of §1; the three that rose
#        were then cut back under the threshold rather than banked, so the net
#        is one paragraph and it is lowered rather than held
#    88  today, 2026-09-08, after #242: `docs/self-describing.md` went 4 -> 3.
#        The paragraph that fell below the threshold is §8 tier 2's account of
#        which environment keys the recompute path compares, which is now a
#        pointer at §1's gap 2 — cut to pay for §2's fifth state and Claim 4's
#        two rows, not for this ceiling, and lowered here for the reason the
#        #241 row gives
#    87  today, 2026-09-09, after #125: `docs/limitations.md` went 2 -> 1. The
#        paragraph that fell below the threshold is §8's *What a claim would
#        need instead*, which stopped restating the caller-supplied-input
#        argument `reg/identity.py` makes — cut for the word budget rather than
#        for this ceiling, and lowered here for the reason the #241 row gives
#    85  today, 2026-09-09, after #257: `docs/limitations.md` went 15 -> 13 and
#        `docs/lossiness.md` 18 -> 17. Two of the three are §12's two closed-gap
#        narratives, merged into one paragraph under the threshold, and the
#        third is *Retained* #8's outer-scalar clause, which stopped restating
#        *Discarded* #9's recomputation argument. All three were cut to pay for
#        the boundary's own clauses, not for this ceiling, and are lowered here
#        for the reason the #241 row gives
#    83  today, 2026-09-11, after #262: `docs/self-describing.md` went 5 -> 3.
#        Both are §1 gap 2's — the three states `limitations.md` §1 is normative
#        on, and the numpy sentence §3's minimise-rule bullet states in full one
#        screen below. Both were cut to pay for §2's seventh row, not for this
#        ceiling, and are lowered here for the reason the #241 row gives
#    80  today, 2026-09-12, after #273: `docs/retention.md` went 8 -> 5. All
#        three fell out of retiring a figure and re-measuring a ladder — the
#        ratio paragraph, the *Why it lost* item that priced a 30,000-frame rung
#        and the subsection opener that stated the retired figure's condition
#        were each rewritten around what is measured now, and each came out
#        under the threshold. Cut for the word budget rather than for this
#        ceiling, and lowered here for the reason the #241 row gives
#    79  today, 2026-09-14, after #275: `docs/self-describing.md` went 1 -> 0.
#        The paragraph that fell is §3's account of what the minimise rule
#        settled when it was applied — the corpus's one over-long paragraph from
#        this document, and it went with the table it qualified rather than
#        being split. Cut for the word budget rather than for this ceiling, and
#        lowered here for the reason the #241 row gives
#    78  today, 2026-09-16, after #276: `docs/limitations.md` went 13 -> 12 and
#        `docs/mobile-base.md` held at 0. The paragraph that fell is §9's *What*,
#        which stopped saying that nothing in the tree models a robot pose — cut
#        because it was false, not for this ceiling, and lowered here for the
#        reason the #241 row gives. The cut file contributed nothing to this
#        count before or after: #214 took it to zero and the prose that replaced
#        §2's opening was split rather than left at 121 words
#    75  today, 2026-09-26, after #277: `docs/plan.md` went 6 -> 3. The three
#        that fell are the mandated-window paragraph, Claim 3's *Why it is
#        Layer A that makes this work*, and Claim 4's re-issuance closer — all
#        cut with the sections that carried them, not for this ceiling. The
#        rewritten network-call paragraph was split in two rather than left at
#        130 words, because two claims were sharing it, which is the #217
#        reason for splitting. Lowered for the reason the #241 row gives
#    71  today, 2026-09-27, after #278: `docs/retention.md` went 5 -> 1. The
#        four that fell are the reframing blockquote, the parameter history,
#        the marginal-cost paragraph and the kept-for-the-record criterion —
#        all cut with the narration that carried them, not for this ceiling.
#        Lowered for the reason the #241 row gives
#    71  today, 2026-09-27, after #279: `docs/sensor-baseline.md` re-measured
#        at 71 — the cut took tables and short paragraphs, no long one.
#        Confirmed, not lowered.
#    71  today, 2026-09-27, after #280: re-measured at 71 — the entry-point
#        cuts took prose paragraphs, none of them over the 120-word line.
#        Confirmed, not lowered.
#    71  today, 2026-09-27, after #294: re-measured at 71 — the cut took the
#        Why history paragraphs, the sublinear analysis items and the
#        candidate-label deliberation table, none of them over the 120-word
#        line. Confirmed, not lowered.
#    71  today, 2026-09-27, after #295: `docs/sensor-baseline.md` re-measured
#        at 71 — the methodology cuts took procedural narration and list
#        items, none of them over the 120-word line. Confirmed, not lowered.
#    71  today, 2026-09-28, after #304: re-measured at 71 — the composition
#        cuts took clauses inside paragraphs, no paragraph over the line.
#        Confirmed, not lowered.
#    71  today, 2026-09-28, after #296: re-measured at 71 — the §8 cuts took
#        a table and list items, no paragraph over the line. Confirmed, not
#        lowered.
#    71  today, 2026-09-28, after #297: re-measured at 71 — the Why cut took
#        a table and the §6 cut took one paragraph, neither over the line.
#        Confirmed, not lowered.
LONG_PARAGRAPHS_MAX = 71

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
#    136  today, 2026-09-08, after #253: `docs/plan.md` went 6 -> 5. Claim 3's
#        paragraph stopped matching because the marker in it was `until issue
#        #227` — the condition itself, and the whole of what that paragraph
#        narrated. A claim that states what the artifact does needs no issue
#        number to say when it will, so nothing was reworded for this ceiling;
#        it is lowered for the reason the #241 row gives
#    135  today, 2026-09-12, after #273: `docs/retention.md` went 21 -> 20.
#        *Why it lost* item 2 had gained a sentence dating when its point was
#        retired, and it was cut rather than reworded — the issue carries that
#        history. Lowered for the reason the #241 row gives
#   128  today, 2026-09-14, after #275: `docs/self-describing.md` went 11 -> 4.
#        Six went with the prose that carried them — the three gap narratives,
#        §2's account of the negatives, §5's relation to #170 and the sixth-pass
#        summary — and the seventh is the status header, which stopped
#        enumerating what landed tier by tier once §8 carried one line each.
#        None was reworded for this ceiling and none moved below the line: a
#        document whose tiers have all landed narrates less by carrying less.
#        Lowered for the reason the #241 row gives
#   128  today, 2026-09-16, after #276. Unchanged and re-measured, which is the
#        point: `docs/mobile-base.md` was already at 0 above its rationale line,
#        #214 having put its archaeology below one, so cutting 3,789 words of it
#        moved nothing here — the ~1,450 words of narration that went were below
#        the line to begin with. `docs/limitations.md` held at 13, its two
#        corrected §9 paragraphs and its rewritten §11 `## Why` sitting where
#        they sat. What this row records is that the replacement prose narrates
#        nothing new: §3's construction paragraph was reworded off `was not
#        raised` rather than rewrapped around it, which is the #217 caveat
#   126  today, 2026-09-26, after #277. Five narrations went with the cut
#        prose — the header's *what has changed*, the Claim 1 composition
#        paragraph, the mandated-window paragraph, Claim 3's *Why it is Layer
#        A that makes this work*, and the passivation paragraph that reached
#        the artifact — and three markers newly fire on the replacement prose:
#        Phase 4's bound paragraph on its live `(issue #164)` cross-reference,
#        the merged passivation paragraph on a carried-over *before it*, and
#        Phase 2 on the *no longer outstanding* the issue ordered stated. The
#        first two are the shape #213 found, references plan.md keeps inline
#        by its status header; the third narrates by instruction. Net two, and
#        lowered for the reason the #241 row gives
#   110  today, 2026-09-27, after #278: `docs/retention.md` went 20 -> 4. The
#        sixteen that fell are the status line, the wrong-twice paragraph, the
#        reframing blockquote, the parameter history, the sensitivity numbers,
#        the marginal-cost account, the superseded 2.51x and the
#        kept-for-the-record criterion — all cut with the narration that
#        carried them, and the surviving rationale moved under `## Why`,
#        below the rationale line. The four that remain are issue-cited
#        measurement records the document keeps inline. Lowered for the
#        reason the #241 row gives
#   110  today, 2026-09-27, after #279: `docs/sensor-baseline.md` re-measured
#        at 110 — the Why history it cut sat below the rationale line.
#        Confirmed, not lowered.
#   110  today, 2026-09-27, after #280: re-measured at 110 — the entry-point
#        cuts took restated process prose, none of it a past-defect narration.
#        Confirmed, not lowered.
#   109  today, 2026-09-27, after #294: `docs/retention.md` re-measured at 109 —
#        one narration fell with the cut prose (the sublinear analysis item
#        citing issue #116); the Why history it cut sat below the rationale
#        line. Lowered.
#   109  today, 2026-09-27, after #295: `docs/sensor-baseline.md` re-measured
#        at 109 — the methodology cuts took procedure and rationale prose,
#        none of it a past-defect narration. Confirmed, not lowered.
#   109  today, 2026-09-28, after #304: re-measured at 109 — the composition
#        cuts took restated counts, none of it a past-defect narration.
#        Confirmed, not lowered.
#   109  today, 2026-09-28, after #296: re-measured at 109 — the §8 cuts took
#        dated decision archaeology, none of it a past-defect narration.
#        Confirmed, not lowered.
#   109  today, 2026-09-28, after #297: re-measured at 109 — the Why and §6
#        cuts took a dated table and present-tense prior-art prose, none of it
#        a past-defect narration. Confirmed, not lowered.
NARRATION_MAX = 109

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
    docs["README.md"] = docs["README.md"] + "\n\n" + ("filler " * 2000)
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


# --------------------------------------------------------------------------
# The #277 corrections are pinned (issue #277, decision D6 of #270).
#
# `docs/plan.md` is binding for scope but carried implementation descriptions
# the code contradicts and prose other files already carry. Each predicate
# below reads `docs/plan.md` and says whether the corrected statement is in
# it and the stale one is not. Every predicate is fed the stale wording it
# guards against and required to say DISAGREE, and an empty document is
# COULD-NOT-EVALUATE — deleting the section is not how a correction is kept.
# --------------------------------------------------------------------------


def _plan_text() -> str:
    return (REPO / "docs" / "plan.md").read_text(encoding="utf-8")


def _empty_is_no_verdict(
    text: str,
) -> tuple[str, list[str]] | None:
    if not text.strip():
        return COULD_NOT_EVALUATE, ["docs/plan.md could not be read"]
    return None


def horizon_bound_states_the_driven_base_case(
    text: str,
) -> tuple[str, list[str]]:
    """Claim 4 and Phase 4: two terms for a fixed base, one for a driven one.

    Issue #164. `computed_bound` refuses a nonzero base bound, so a driven
    base gets the outer-set projection alone — the old unconditional "smaller
    of two sound bounds" described a robot that cannot drive.
    """
    empty = _empty_is_no_verdict(text)
    if empty is not None:
        return empty
    problems = []
    if not re.search(r"fixed base.{0,200}smaller of two", text, re.I | re.S):
        problems.append("no fixed-base two-term bound stated")
    if not re.search(r"driven base.{0,300}alone", text, re.I | re.S):
        problems.append("no driven-base outer-projection-alone stated")
    if not re.search(r"computed_bound.{0,200}refus", text, re.I | re.S):
        problems.append("no computed_bound refusal stated")
    return (DISAGREE if problems else AGREE), problems


def phase_5_schema_is_a_pointer(text: str) -> tuple[str, list[str]]:
    """Phase 5 carries no schema tables; the code does.

    The Nodes/Edges tables named `CONTAINS`, which `reg.store.EDGE_SPECS`
    does not define. The section now points at `reg/store.py` and
    `reg.store.EDGE_SPECS` instead of carrying a second copy.
    """
    empty = _empty_is_no_verdict(text)
    if empty is not None:
        return empty
    problems = []
    if "reg/store.py" not in text:
        problems.append("no pointer at reg/store.py")
    if "EDGE_SPECS" not in text:
        problems.append("no pointer at reg.store.EDGE_SPECS")
    if "CONTAINS" in text:
        problems.append("stale CONTAINS edge still named")
    if "envelope_id" in text:
        problems.append("stale Nodes table fields still present")
    return (DISAGREE if problems else AGREE), problems


def phase_7_money_query_points_at_readme(text: str) -> tuple[str, list[str]]:
    """Phase 7's money query points at README's real output, not a fenced fake.

    `tests/test_readme.py` proves the *Reading an incident* block runs; the
    D-0891 / 4,218-records block was invented and is gone.
    """
    empty = _empty_is_no_verdict(text)
    if empty is not None:
        return empty
    problems = []
    if "Reading an incident" not in text:
        problems.append("no pointer at README's Reading an incident")
    if "D-0891" in text:
        problems.append("fake incident output still present")
    if "4,218 records" in text:
        problems.append("fake chain-verified line still present")
    return (DISAGREE if problems else AGREE), problems


def phase_8_agrees_with_the_ratio_ban(text: str) -> tuple[str, list[str]]:
    """Phase 8 measures bytes/hour, not a ratio — Claim 1's ban, stated there.

    *Nothing in this repository may quote a compression ratio as the
    commercial argument while the measured one is below 1.* Phase 8's tables
    asked for one anyway.
    """
    empty = _empty_is_no_verdict(text)
    if empty is not None:
        return empty
    problems = []
    if re.search(r"^\| Ratio", text, re.M):
        problems.append("a Ratio metric row is still in Phase 8's tables")
    if not re.search(r"not a ratio", text, re.I):
        problems.append("Phase 8 does not say why there is no ratio column")
    return (DISAGREE if problems else AGREE), problems


def no_stale_architecture_tree(text: str) -> tuple[str, list[str]]:
    """The layout lives in CLAUDE.md and tests/test_layout.py, not here.

    The tree named `sim/`, `envelope/` and the other pre-`reg/` directory
    names; it disagreed with the repository it described.
    """
    empty = _empty_is_no_verdict(text)
    if empty is not None:
        return empty
    problems = []
    if re.search(r"^sim/ +2D world", text, re.M):
        problems.append("the stale architecture tree is back")
    if "test_layout.py" not in text:
        problems.append("no pointer at the file that enforces the layout")
    return (DISAGREE if problems else AGREE), problems


def phase_2_outer_approximation_is_landed(text: str) -> tuple[str, list[str]]:
    """Phase 2 no longer asks for an outer approximation — #82 built it.

    `reg.envelope.outer_envelope` is what Phase 4's bound rests on; the old
    "a real safety claim needs an outer approximation" is false.
    """
    empty = _empty_is_no_verdict(text)
    if empty is not None:
        return empty
    problems = []
    if not re.search(r"outer_envelope.{0,40}landed", text, re.I):
        problems.append("no statement that outer_envelope landed")
    if re.search(r"needs an outer approximation", text, re.I):
        problems.append("the outstanding-outer-approximation sentence is back")
    return (DISAGREE if problems else AGREE), problems


def claim_2_quotes_no_benchmark_figures(text: str) -> tuple[str, list[str]]:
    """Claim 2 quotes no benchmark figures; tests/test_bench.py holds them.

    The 264–380x, 70 ms, 0.0–8.2 mm and 10 mm figures were measured nowhere
    this repository checks. The section points at the benchmark instead of
    quoting it, because a figure quoted here and measured there drifts.
    """
    empty = _empty_is_no_verdict(text)
    if empty is not None:
        return empty
    problems = []
    for figure in ("264–380x", "70 ms", "0.0–8.2", "10 mm"):
        if figure in text:
            problems.append(f"unguarded benchmark figure still quoted: {figure}")
    if "test_bench.py" not in text:
        problems.append("no pointer at tests/test_bench.py")
    return (DISAGREE if problems else AGREE), problems


def build_order_states_what_shipped(text: str) -> tuple[str, list[str]]:
    """Build order is one status line: milestones 1–3 shipped, 4/Phase 10 left.

    The milestone table described a project that had not started; the table
    is gone and the line says what is true.
    """
    empty = _empty_is_no_verdict(text)
    if empty is not None:
        return empty
    problems = []
    if not re.search(r"Milestones 1–3 shipped", text):
        problems.append("no statement that milestones 1–3 shipped")
    if not re.search(r"[Mm]ilestone 4.*Phase 10 remains", text, re.S):
        problems.append("no statement that milestone 4 / Phase 10 remains")
    return (DISAGREE if problems else AGREE), problems


def phase_10_has_no_headline_number(text: str) -> tuple[str, list[str]]:
    """Phase 10 promises no headline compression number; standards.md died.

    `docs/standards.md` was never created — the baseline table lives in
    plan.md's own Standards baseline section — and Claim 1 bans the ratio
    the headline number would have quoted.
    """
    empty = _empty_is_no_verdict(text)
    if empty is not None:
        return empty
    problems = []
    if re.search(r"headline compression number", text, re.I):
        problems.append("the headline compression number is back")
    if not re.search(r"standards\.md.{0,60}never created", text, re.I | re.S):
        problems.append("no statement that docs/standards.md was never created")
    return (DISAGREE if problems else AGREE), problems


def claim_1_keeps_the_measured_rate(text: str) -> tuple[str, list[str]]:
    """Claim 1 keeps `60.85 MB/h` with 50 Hz — `tests/test_bench.py` needs it.

    The composition paragraph and the "derived, not measured" paragraph are
    cut, but the measured rate they carried stays: a document that quotes the
    six-month total publishes the `bytes/hour` it is built from, and a figure
    linear in an unstated rate is not a measured figure.
    """
    empty = _empty_is_no_verdict(text)
    if empty is not None:
        return empty
    problems = []
    if "60.85 MB/h" not in text:
        problems.append("the measured 60.85 MB/h rate is gone")
    if not re.search(r"60\.85 MB/h.{0,200}50 Hz", text, re.S):
        problems.append("the rate is not stated with its 50 Hz control rate")
    return (DISAGREE if problems else AGREE), problems


def claim_numbers_carry_no_stale_count(text: str) -> tuple[str, list[str]]:
    """The claim identifiers' reference count is not quoted.

    "Referenced from 125 places" was unmeasured and unmaintained; the
    sentence that the numbers do not move stands without it.
    """
    empty = _empty_is_no_verdict(text)
    if empty is not None:
        return empty
    if re.search(r"125\s+places", text):
        return DISAGREE, ["the stale 125-places count is back"]
    return AGREE, []


# The stale wordings each predicate guards against, verbatim from plan.md
# before #277. Every one must fail its predicate.
STALE_HORIZON_BOUND = """`horizon_bound(state, limits, window, substep_dt)` is the radius a declared
region is tested against, and it is the smaller of two sound bounds: the
workspace disc `sum(link_lengths) + link_radius`, which reads no `q`, no `q̇`
and no horizon; and the radial projection of `reg.envelope.outer_envelope`, a
horizon-limited **outer** reachable set — the joint box pushed through the
forward kinematics as an interval — which reads all three. Both over-cover, so
nothing inside is ever falsely accused."""

STALE_SCHEMA = """| `Envelope` | `envelope_id`, `area`, `geometry_wkb`, `horizon`, `source` |
| `CONTAINS` / `INTERSECTS` | Envelope → Entity (with `overlap_area`) |"""

STALE_MONEY_QUERY = """```
At t=12.34s the policy declared envelope D-0891 (area 0.42 m²)
Chain verified: 4,218 records, 0 breaks
```"""

STALE_RATIO_ROW = """| Ratio | vs. raw and vs. projection |"""

STALE_TREE = """```
sim/          2D world, robot kinematics, scripted human motion
envelope/     proprioception-only forward reachable set  [LAYER A]
```"""

STALE_OUTER_APPROXIMATION = """A real safety claim needs an outer approximation. Naming
this is a point in your favor."""

STALE_REFRAMED = """**Reframed 2026-08-19.** The benchmark reports a 264–380x speedup against
recomputing from the raw CSV, and **that is not the claim worth making** — 70 ms
is not slow, and nobody retains an evidence artifact to save 70 ms. The claim is
the `AGREE` column beside it: at every measured length up to 30,000 frames, the
graph's answer matches ground truth recomputed from the raw stream to within
0.0–8.2 mm against a 10 mm advertised tolerance."""

STALE_BUILD_ORDER = """| **1** | 1, 2, 5 (basic), 8 (compression only) | Yes — "here's a compression number and a picture" |"""

STALE_PHASE_10 = """- `README.md` — thesis in 3 paragraphs, four claims, headline compression number,
  the incident report output, how to run
- `docs/standards.md` — the baseline table above, with the two deliberate deviations"""

STALE_MEASURED_RATE = """**The artifact's measured rate is 60.85 MB/h** at an unstated control rate;
the six-month total is that rate times the window."""

STALE_COUNT = """**The numbers are identifiers, not a ranking.** They are referenced from 125
places across this repository, including `reg/` and `tests/`, so they do not
move."""


def test_horizon_bound_states_the_driven_base_case() -> None:
    verdict, problems = horizon_bound_states_the_driven_base_case(_plan_text())
    assert verdict == AGREE, "\n".join(problems)
    verdict, problems = horizon_bound_states_the_driven_base_case(
        STALE_HORIZON_BOUND
    )
    assert verdict == DISAGREE, "the unconditional two-term bound passes"
    assert problems
    verdict, problems = horizon_bound_states_the_driven_base_case("")
    assert verdict == COULD_NOT_EVALUATE
    assert problems


def test_phase_5_schema_is_a_pointer() -> None:
    verdict, problems = phase_5_schema_is_a_pointer(_plan_text())
    assert verdict == AGREE, "\n".join(problems)
    verdict, problems = phase_5_schema_is_a_pointer(STALE_SCHEMA)
    assert verdict == DISAGREE, "the stale schema tables pass"
    assert problems
    verdict, problems = phase_5_schema_is_a_pointer("")
    assert verdict == COULD_NOT_EVALUATE
    assert problems


def test_phase_7_money_query_points_at_readme() -> None:
    verdict, problems = phase_7_money_query_points_at_readme(_plan_text())
    assert verdict == AGREE, "\n".join(problems)
    verdict, problems = phase_7_money_query_points_at_readme(STALE_MONEY_QUERY)
    assert verdict == DISAGREE, "the fake output block passes"
    assert problems
    verdict, problems = phase_7_money_query_points_at_readme("")
    assert verdict == COULD_NOT_EVALUATE
    assert problems


def test_phase_8_agrees_with_the_ratio_ban() -> None:
    verdict, problems = phase_8_agrees_with_the_ratio_ban(_plan_text())
    assert verdict == AGREE, "\n".join(problems)
    verdict, problems = phase_8_agrees_with_the_ratio_ban(STALE_RATIO_ROW)
    assert verdict == DISAGREE, "the Ratio metric row passes"
    assert problems
    verdict, problems = phase_8_agrees_with_the_ratio_ban("")
    assert verdict == COULD_NOT_EVALUATE
    assert problems


def test_no_stale_architecture_tree() -> None:
    verdict, problems = no_stale_architecture_tree(_plan_text())
    assert verdict == AGREE, "\n".join(problems)
    verdict, problems = no_stale_architecture_tree(STALE_TREE)
    assert verdict == DISAGREE, "the stale tree passes"
    assert problems
    verdict, problems = no_stale_architecture_tree("")
    assert verdict == COULD_NOT_EVALUATE
    assert problems


def test_phase_2_outer_approximation_is_landed() -> None:
    verdict, problems = phase_2_outer_approximation_is_landed(_plan_text())
    assert verdict == AGREE, "\n".join(problems)
    verdict, problems = phase_2_outer_approximation_is_landed(
        STALE_OUTER_APPROXIMATION
    )
    assert verdict == DISAGREE, "the outstanding-outer-approximation passes"
    assert problems
    verdict, problems = phase_2_outer_approximation_is_landed("")
    assert verdict == COULD_NOT_EVALUATE
    assert problems


def test_claim_2_quotes_no_benchmark_figures() -> None:
    verdict, problems = claim_2_quotes_no_benchmark_figures(_plan_text())
    assert verdict == AGREE, "\n".join(problems)
    verdict, problems = claim_2_quotes_no_benchmark_figures(STALE_REFRAMED)
    assert verdict == DISAGREE, "the unguarded benchmark figures pass"
    assert problems
    verdict, problems = claim_2_quotes_no_benchmark_figures("")
    assert verdict == COULD_NOT_EVALUATE
    assert problems


def test_build_order_states_what_shipped() -> None:
    verdict, problems = build_order_states_what_shipped(_plan_text())
    assert verdict == AGREE, "\n".join(problems)
    verdict, problems = build_order_states_what_shipped(STALE_BUILD_ORDER)
    assert verdict == DISAGREE, "the milestone table passes"
    assert problems
    verdict, problems = build_order_states_what_shipped("")
    assert verdict == COULD_NOT_EVALUATE
    assert problems


def test_phase_10_has_no_headline_number() -> None:
    verdict, problems = phase_10_has_no_headline_number(_plan_text())
    assert verdict == AGREE, "\n".join(problems)
    verdict, problems = phase_10_has_no_headline_number(STALE_PHASE_10)
    assert verdict == DISAGREE, "the headline number passes"
    assert problems
    verdict, problems = phase_10_has_no_headline_number("")
    assert verdict == COULD_NOT_EVALUATE
    assert problems


def test_claim_1_keeps_the_measured_rate() -> None:
    verdict, problems = claim_1_keeps_the_measured_rate(_plan_text())
    assert verdict == AGREE, "\n".join(problems)
    verdict, problems = claim_1_keeps_the_measured_rate(STALE_MEASURED_RATE)
    assert verdict == DISAGREE, "the rate without its control rate passes"
    assert problems
    verdict, problems = claim_1_keeps_the_measured_rate("")
    assert verdict == COULD_NOT_EVALUATE
    assert problems


def test_claim_numbers_carry_no_stale_count() -> None:
    verdict, problems = claim_numbers_carry_no_stale_count(_plan_text())
    assert verdict == AGREE, "\n".join(problems)
    verdict, problems = claim_numbers_carry_no_stale_count(STALE_COUNT)
    assert verdict == DISAGREE, "the 125-places count passes"
    assert problems
    verdict, problems = claim_numbers_carry_no_stale_count("")
    assert verdict == COULD_NOT_EVALUATE
    assert problems


# --------------------------------------------------------------------------
# Issue #278: `docs/retention.md` loses ~2,400 words of figure-move and
# history narration. The tables and the live argument stay; the archaeology
# goes, and what rationale survives moves under a plain `## Why`, the split
# issue #170 gave the other documents. Each predicate below reads
# `docs/retention.md` (the plan one reads `docs/plan.md`) and says whether the
# corrected statement is in it and the stale one is not. Every predicate is
# fed the stale wording it guards against and required to say DISAGREE, and
# an empty document is COULD-NOT-EVALUATE — deleting the section is not how a
# correction is kept.
# --------------------------------------------------------------------------


def _retention_text() -> str:
    return (REPO / "docs" / "retention.md").read_text(encoding="utf-8")


def _retention_empty_is_no_verdict(
    text: str,
) -> tuple[str, list[str]] | None:
    if not text.strip():
        return COULD_NOT_EVALUATE, ["docs/retention.md could not be read"]
    return None


def retention_header_keeps_machine_checked_drops_history(
    text: str,
) -> tuple[str, list[str]]:
    """The header keeps the scope line and the fixed-base condition.

    The status line ("keep current", the re-measurement roll) and the "wrong
    twice" paragraph were history about the document rather than conditions on
    the figures; the rationale they carried moved under `## Why`.
    """
    empty = _retention_empty_is_no_verdict(text)
    if empty is not None:
        return empty
    problems = []
    if "What is machine-checked here is less than the whole file" not in text:
        problems.append("the machine-checked scope line is gone")
    if "fixed-base planar" not in text:
        problems.append("the fixed-base condition is gone")
    if "keep current" in text:
        problems.append("the stale status line is back")
    if "wrong twice" in text:
        problems.append("the wrong-twice archaeology is back")
    return (DISAGREE if problems else AGREE), problems


def retention_parameter_block_is_command_and_rate(
    text: str,
) -> tuple[str, list[str]]:
    """The parameter block is the dated command at 50 Hz, not the history.

    The blockquote named what it replaced (provisional figures, a no-Layer-A
    artifact) instead of what it is: one dated command at the 50 Hz fixture
    rate.
    """
    empty = _retention_empty_is_no_verdict(text)
    if empty is not None:
        return empty
    problems = []
    if "Measured 2026-08-20 (issue #60)" not in text:
        problems.append("the dated measurement command is gone")
    if "**50 Hz**" not in text:
        problems.append("the parameter block no longer names 50 Hz")
    if "These replace the provisional figures" in text:
        problems.append("the provisional-figures history is back")
    if "no Layer A at all" in text:
        problems.append("the no-Layer-A history is back")
    return (DISAGREE if problems else AGREE), problems


def retention_two_orders_points_at_sensor_baseline(
    text: str,
) -> tuple[str, list[str]]:
    """Two orders, not three, never four — the sensitivity lives in sensor-baseline.md.

    The paragraph carried the sensitivity numbers (0.146/1.46/14.6 TB/day)
    inline; they are sensor-baseline.md's to keep current, so this is a
    pointer now, keeping the "two, not three, never four" and the DSSAD clause.
    """
    empty = _retention_empty_is_no_verdict(text)
    if empty is not None:
        return empty
    problems = []
    if "two orders, not three, and never four" not in text:
        problems.append("the two-not-three-never-four statement is gone")
    if "DSSAD" not in text:
        problems.append("the DSSAD clause is gone")
    if "sensor-baseline.md" not in text:
        problems.append("no pointer at sensor-baseline.md")
    for stale in ("0.146 TB/day", "1.46 TB/day", "14.6 TB/day"):
        if stale in text:
            problems.append(f"stale inline sensitivity figure is back: {stale}")
    return (DISAGREE if problems else AGREE), problems


def retention_scaling_says_encoding_does_not_move_it(
    text: str,
) -> tuple[str, list[str]]:
    """The scaling narrative is one line: encoding doesn't move it, resolution does.

    The marginal-cost arithmetic (21.5 B vs 354.6 B) and the structural account
    were history around the re-measured #273 rungs, which stay.
    """
    empty = _retention_empty_is_no_verdict(text)
    if empty is not None:
        return empty
    problems = []
    if "Encoding does not move it; resolution does" not in text:
        problems.append("the encoding-does-not-move-it conclusion is gone")
    if "21.5 B of gzipped CSV" in text:
        problems.append("the stale marginal-cost arithmetic is back")
    if "354.6 B of SQLite" in text:
        problems.append("the stale marginal-cost arithmetic is back")
    return (DISAGREE if problems else AGREE), problems


def retention_no_superseded_251x(text: str) -> tuple[str, list[str]]:
    """The superseded 2.51x is gone.

    It priced compression as a default rosbag2 does not apply and left the
    message index out; the incumbent table beside it carries the comparison
    now.
    """
    empty = _retention_empty_is_no_verdict(text)
    if empty is not None:
        return empty
    if "2.51x" in text:
        return DISAGREE, ["the superseded 2.51x is back"]
    return AGREE, []


def retention_criterion_4_is_one_line(text: str) -> tuple[str, list[str]]:
    """Criterion 4 is a single superseded line, not a kept record.

    The paragraph headed "Superseded, and kept for the record" carried the
    live prohibition inside a superseded bullet; the prohibition is plan.md
    Claim 1's.
    """
    empty = _retention_empty_is_no_verdict(text)
    if empty is not None:
        return empty
    problems = []
    match = re.search(r"^4\. (.+)$", text, re.M)
    if not match:
        problems.append("criterion 4 not found")
    else:
        line = match.group(1)
        if "Superseded" not in line:
            problems.append("criterion 4 does not say superseded")
        if "does not rest on compression" not in line:
            problems.append("criterion 4 lost its one-line content")
    if "kept for the record" in text:
        problems.append("the stale kept-for-the-record wording is back")
    return (DISAGREE if problems else AGREE), problems


def plan_no_fourth_kept_for_record(text: str) -> tuple[str, list[str]]:
    """plan.md no longer keeps a fourth criterion for the record.

    Criterion 4 is superseded to a single line in retention.md; the plan's
    pointer says so.
    """
    empty = _empty_is_no_verdict(text)
    if empty is not None:
        return empty
    problems = []
    if "a fourth kept for the record" in text:
        problems.append("the stale fourth-kept-for-the-record wording is back")
    if "fourth superseded" not in text:
        problems.append("the plan does not say the fourth is superseded")
    return (DISAGREE if problems else AGREE), problems


def retention_why_is_a_section(text: str) -> tuple[str, list[str]]:
    """The rationale lives under a plain `## Why`, per the #170 split.

    "Why it lost" was a dated section of three numbered findings; it is two
    sentences now, pointing at prior-art.md §8 and lossiness.md, and the label
    and reframing rationale sit beside it under the same heading.
    """
    empty = _retention_empty_is_no_verdict(text)
    if empty is not None:
        return empty
    problems = []
    if not re.search(r"^## Why$", text, re.M):
        problems.append("no plain ## Why section")
    if "## Why it lost" in text:
        problems.append("the old Why-it-lost heading is back")
    why = re.search(r"^## Why$(.*?)(?=^## |\Z)", text, re.M | re.S)
    body = why.group(1) if why else ""
    if "prior-art.md" not in body or "§8" not in body:
        problems.append("## Why does not point at prior-art.md §8")
    if "lossiness.md" not in body:
        problems.append("## Why does not point at lossiness.md")
    if "The baseline was never the thesis" in text:
        problems.append("the old numbered why-it-lost findings are back")
    return (DISAGREE if problems else AGREE), problems


# The stale wordings each predicate guards against, verbatim from
# docs/retention.md (and docs/plan.md) before #278. Every one must fail its
# predicate.
STALE_RETENTION_STATUS = """**Status:** normative for every retention figure this project publishes ·
re-measured 2026-08-20 (issue #60), with later work carrying its own issue
number where it sits — #98's Layer-A comparison, #116's label and byte
attribution, #257's outer boundary, #273's re-measured ladder · extracted from [`plan.md`](plan.md) Claim 1 on 2026-08-31, **with
no figure changed** · keep current

**What is machine-checked here is less than the whole file.**
`tests/test_published_figures.py` re-derives four things from the code on every
CI run: the control-rate ladder's **50 Hz row**, the coarsest level's **label**
and the record and node counts behind it, the **byte attribution**, and the
**Layer-A comparison** table.

Everything else is prose or arithmetic over those, `267 GB` among them; that
module's own *What this does not cover* is the authority on the boundary, and
this line exists so that nothing here reads as guaranteed when it is not.

This is [`plan.md`](plan.md) Claim 1's measurement record: a set of measured
figures, the arithmetic behind them, and the record of how they moved. `plan.md`
states the claim and the conditions that travel with it; the derivations, the
ladder and the corrections are here.

**The artifact side of every figure here is measured on the fixed-base planar
arm** — 2–3 revolute links, base at the origin. That is a condition on all of
them, and moving the robot would move all of them. The **control rate** is not a
single condition in the same way: the resolution table below is at the 50 Hz
`reg.scenarios.DEFAULT_DT` runs at, and *The control rate* measures the same
curve at 100 Hz, 250 Hz and 1 kHz. Every table says which rate it is at.

**This document has been wrong twice and the corrections are kept in place
rather than tidied away** — refuted against a baseline that was never the claim,
then republished against an artifact that turned out to hold no Layer A at all.
The record of how a number moved is worth more here than a clean statement of
where it landed, in a project whose argument is that evidence should survive its
own revision."""

STALE_PARAMETER_BLOCK = """> **Measured 2026-08-20 (issue #60). These replace the provisional figures.**
> One execution of `python -m reg.bench --resolution --seed 0` — `long_run` at
> 3,000 frames (60.0 s of robot time), 16 envelope samples, 200 ms horizon,
> 1.0 s occurrence resolution, 0.5 s replan interval and declaration horizon,
> 1.0 s watchdog. The figures it replaces predated the #54/#55 encoding work
> and, far more importantly, measured an artifact holding **no Layer A at all**
> (issue #59). Every level got **larger**, and the coarsest got larger by 13.9x:
> the declaration, verdict and chain records are emitted per action and **no
> resolution level coarsens them**, so at ±1 s they are 3,120 of the artifact's
> 3,166 node rows. Coarsening now buys much less than the provisional table implied,
> and that is the finding, not a defect in it."""

STALE_TWO_ORDERS = """**State it at two orders, not three, and never four.** The ratio is linear in
the assumed sensor rate, and the sensitivity analysis is blunt about what that
buys: the 2-order band is occupied down to 0.146 TB/day — a sevenfold margin
below the assumption, where before Layer A was measured it looked like a
hundredfold — while three orders needs 1.46 TB/day, which the published
assumption does **not** reach, and four needs 14.6 TB/day. The robust claim is
the one to make, and it is now a narrower one. It is also, conveniently, the
resolution the only mandated evidence recorder in existence operates at (UN R157
DSSAD, ±1.0 s). The finer levels are weaker again: transition clears two orders
only above ~0.46 TB/day and per-frame only above ~0.71 TB/day."""

STALE_SCALING = """The ratio *does* improve with run length — the fixed schema cost amortises.
**It does not reach 1.0 anywhere in the measured range.** The marginal cost of
one more frame over the interval between the two rungs is 21.5 B of gzipped CSV
against 354.6 B of SQLite. Measured points only: the ladder holds what was run."""

STALE_251X = """The **2.51x** published here from 2026-08-26 is superseded: it priced
compression as a default rosbag2 does not apply and left the message index out,
and both made the incumbent look cheap."""

STALE_CRITERION_4 = """4. Superseded, and kept for the record: *until a measured length clears 1.0, the
   retainable-artifact argument does not rest on compression.* It was written
   when the wrong baseline was believed to be the right one."""

STALE_PLAN_FOURTH = """published under it — three live, and a fourth kept for the record — are
[`retention.md`](retention.md), *Success, restated*."""

STALE_WHY_IT_LOST = """## Why it lost — three things the measurement exposed (2026-08-19)

**1. The baseline was never the thesis.**"""


def test_retention_header_keeps_machine_checked_drops_history() -> None:
    verdict, problems = retention_header_keeps_machine_checked_drops_history(
        _retention_text()
    )
    assert verdict == AGREE, "\n".join(problems)
    verdict, problems = retention_header_keeps_machine_checked_drops_history(
        STALE_RETENTION_STATUS
    )
    assert verdict == DISAGREE, "the stale status line passes"
    assert problems
    verdict, problems = retention_header_keeps_machine_checked_drops_history("")
    assert verdict == COULD_NOT_EVALUATE
    assert problems


def test_retention_parameter_block_is_command_and_rate() -> None:
    verdict, problems = retention_parameter_block_is_command_and_rate(
        _retention_text()
    )
    assert verdict == AGREE, "\n".join(problems)
    verdict, problems = retention_parameter_block_is_command_and_rate(
        STALE_PARAMETER_BLOCK
    )
    assert verdict == DISAGREE, "the stale parameter block passes"
    assert problems
    verdict, problems = retention_parameter_block_is_command_and_rate("")
    assert verdict == COULD_NOT_EVALUATE
    assert problems


def test_retention_two_orders_points_at_sensor_baseline() -> None:
    verdict, problems = retention_two_orders_points_at_sensor_baseline(
        _retention_text()
    )
    assert verdict == AGREE, "\n".join(problems)
    verdict, problems = retention_two_orders_points_at_sensor_baseline(
        STALE_TWO_ORDERS
    )
    assert verdict == DISAGREE, "the stale inline sensitivity passes"
    assert problems
    verdict, problems = retention_two_orders_points_at_sensor_baseline("")
    assert verdict == COULD_NOT_EVALUATE
    assert problems


def test_retention_scaling_says_encoding_does_not_move_it() -> None:
    verdict, problems = retention_scaling_says_encoding_does_not_move_it(
        _retention_text()
    )
    assert verdict == AGREE, "\n".join(problems)
    verdict, problems = retention_scaling_says_encoding_does_not_move_it(
        STALE_SCALING
    )
    assert verdict == DISAGREE, "the stale marginal-cost arithmetic passes"
    assert problems
    verdict, problems = retention_scaling_says_encoding_does_not_move_it("")
    assert verdict == COULD_NOT_EVALUATE
    assert problems


def test_retention_no_superseded_251x() -> None:
    verdict, problems = retention_no_superseded_251x(_retention_text())
    assert verdict == AGREE, "\n".join(problems)
    verdict, problems = retention_no_superseded_251x(STALE_251X)
    assert verdict == DISAGREE, "the superseded 2.51x passes"
    assert problems
    verdict, problems = retention_no_superseded_251x("")
    assert verdict == COULD_NOT_EVALUATE
    assert problems


def test_retention_criterion_4_is_one_line() -> None:
    verdict, problems = retention_criterion_4_is_one_line(_retention_text())
    assert verdict == AGREE, "\n".join(problems)
    verdict, problems = retention_criterion_4_is_one_line(STALE_CRITERION_4)
    assert verdict == DISAGREE, "the stale kept-for-the-record criterion passes"
    assert problems
    verdict, problems = retention_criterion_4_is_one_line("")
    assert verdict == COULD_NOT_EVALUATE
    assert problems


def test_plan_no_fourth_kept_for_record() -> None:
    verdict, problems = plan_no_fourth_kept_for_record(_plan_text())
    assert verdict == AGREE, "\n".join(problems)
    verdict, problems = plan_no_fourth_kept_for_record(STALE_PLAN_FOURTH)
    assert verdict == DISAGREE, "the stale fourth-kept-for-the-record passes"
    assert problems
    verdict, problems = plan_no_fourth_kept_for_record("")
    assert verdict == COULD_NOT_EVALUATE
    assert problems


def test_retention_why_is_a_section() -> None:
    verdict, problems = retention_why_is_a_section(_retention_text())
    assert verdict == AGREE, "\n".join(problems)
    verdict, problems = retention_why_is_a_section(STALE_WHY_IT_LOST)
    assert verdict == DISAGREE, "the old Why-it-lost heading passes"
    assert problems
    verdict, problems = retention_why_is_a_section("")
    assert verdict == COULD_NOT_EVALUATE
    assert problems


def _baseline_text() -> str:
    return (REPO / "docs" / "sensor-baseline.md").read_text(encoding="utf-8")


def _baseline_empty_is_no_verdict(
    text: str,
) -> tuple[str, list[str]] | None:
    if not text.strip():
        return COULD_NOT_EVALUATE, ["docs/sensor-baseline.md could not be read"]
    return None


def baseline_why_is_one_sentence(
    text: str,
) -> tuple[str, list[str]]:
    """## Why is one sentence: the multiplier stayed 1 TB/day.

    D3 reverses #213, which had moved the section history under ## Why as
    worth keeping. The provenance table and the re-measurement narratives
    are gone.
    """
    empty = _baseline_empty_is_no_verdict(text)
    if empty is not None:
        return empty
    problems = []
    if "The multiplier stayed 1 TB/day through every re-measurement." not in text:
        problems.append("the one-sentence ## Why is gone")
    for stale in (
        "Nothing below is normative. It is the provenance",
        "### When each section was added",
        "### The sizes the Layer A re-measurement replaced",
        "### What the two re-measurements did to the conclusion",
    ):
        if stale in text:
            problems.append(f"the stale Why history is back: {stale[:40]}")
    return (DISAGREE if problems else AGREE), problems


def baseline_no_six_month_table(
    text: str,
) -> tuple[str, list[str]]:
    """*What it does to the claim* is a pointer, not a table.

    retention.md and limitations.md §5 duplicate the six-month table exactly
    and with no guard on the copy; this document keeps only the sensor side,
    which does not move.
    """
    empty = _baseline_empty_is_no_verdict(text)
    if empty is not None:
        return empty
    problems = []
    if "| **1 kHz** | **4.72 TB**" in text:
        problems.append("the stale six-month table is back")
    if "What the claim becomes at each rung" not in text:
        problems.append("the pointer at retention.md's six-month table is gone")
    if "limitations.md" not in text or "§5" not in text:
        problems.append("the pointer at limitations.md §5 is gone")
    if "The sensor assumption is not adjusted to compensate" not in text:
        problems.append("the sensor-side-not-adjusted paragraph is gone")
    return (DISAGREE if problems else AGREE), problems


def baseline_no_sublinear_growth_paragraph(
    text: str,
) -> tuple[str, list[str]]:
    """The sublinear-growth paragraph is gone.

    #273 corrected its attribution; what remains is history around the
    re-measured ladder, which stays.
    """
    empty = _baseline_empty_is_no_verdict(text)
    if empty is not None:
        return empty
    if "The growth is **sublinear**" in text:
        return DISAGREE, ["the stale sublinear-growth paragraph is back"]
    return AGREE, []


def baseline_air_gap_is_a_retired_pointer(
    text: str,
) -> tuple[str, list[str]]:
    """The air-gap section names the premise, says retired, and points.

    The history of where the premise was stated and what would bring it back
    is gone; the heading, the retirement, and the requirement half stay.
    """
    empty = _baseline_empty_is_no_verdict(text)
    if empty is not None:
        return empty
    problems = []
    if "## A premise this document does not carry: air-gapped sites" not in text:
        problems.append("the air-gap heading is gone")
    if "retired, not repaired" not in text:
        problems.append("the retirement is gone")
    for stale in (
        "It was stated as fact in `README.md`",
        "**What would bring the premise back.**",
        "stood in for the requirement below in three more places",
    ):
        if stale in text:
            problems.append(f"the stale air-gap history is back: {stale[:40]}")
    return (DISAGREE if problems else AGREE), problems


def baseline_sensitivity_parameter_block_condensed(
    text: str,
) -> tuple[str, list[str]]:
    """The Sensitivity parameter block is one line, not a duplicated block.

    The full run parameters live in retention.md; here only the command and
    the rate travel with the table.
    """
    empty = _baseline_empty_is_no_verdict(text)
    if empty is not None:
        return empty
    problems = []
    if "at a 50 Hz control rate. Each" not in text:
        problems.append("the condensed parameter line is gone")
    for stale in (
        "16 envelope samples, 200 ms horizon",
        "1.0 s occurrence resolution, 0.5 s replan interval",
    ):
        if stale in text:
            problems.append(f"the stale parameter block is back: {stale[:40]}")
    return (DISAGREE if problems else AGREE), problems


def baseline_sensor_multiplier_has_no_default(
    text: str,
) -> tuple[str, list[str]]:
    """--sensor-multiplier has no default.

    The benchmark enforces the baseline in code rather than prose; the
    paragraph stating that stays.
    """
    empty = _baseline_empty_is_no_verdict(text)
    if empty is not None:
        return empty
    if "--sensor-multiplier` has\n**no default**" not in text:
        return DISAGREE, ["the --sensor-multiplier no-default paragraph is gone"]
    return AGREE, []


# The stale wordings each predicate guards against, verbatim from
# docs/sensor-baseline.md before #279. Every one must fail its predicate.
STALE_BASELINE_WHY = """## Why

Nothing below is normative. It is the provenance of the sections above: which
issue each arrived with, and what each re-measurement moved. An assumption is
worth least once nobody remembers what it was weighed against.

### When each section was added"""

STALE_SIX_MONTH_TABLE = """| control rate | occurrence, 6 months | vs 182.5 TB | transition | vs | per-frame | vs |
|---|---|---|---|---|---|---|
| **50 Hz** | **267 GB** | **~684x** | 838 GB | ~218x | 1,293 GB | ~141x |
| 100 Hz | 469 GB | ~389x | 1.38 TB | ~132x | 2.47 TB | ~74x |
| 250 Hz | 1.09 TB | ~167x | 2.96 TB | ~62x | 6.42 TB | ~28x |
| **1 kHz** | **4.72 TB** | **~39x** | 11.57 TB | ~16x | 28.53 TB | ~6x |"""

STALE_SUBLINEAR = """The growth is **sublinear**: 17.7x at the occurrence level for a 20x rate
increase, and the term that does not scale is the **`declaration` table**, 18.3%
of the coarsest level at 50 Hz: the policy replans on a wall-clock interval, so
it emits the same declarations at every rung.
[`retention.md`](retention.md), *Why the growth is sublinear*, measures that
level per table and is where the attribution is established. Only the record
layer scales, and by 1 kHz it is 60,101 of that level's 61,826 node rows —
97.2%, against 98.5% at 50 Hz. That level is almost
entirely a per-action attestation stream at either rate, which is what the rate
buys and what a cadence change would cut."""

STALE_AIR_GAP = """**The retention argument rests on the sensor rate alone.** A second empirical
claim once stood beside it: that full sensor logs cannot leave an air-gapped
site. It was stated as fact in `README.md` and three times in
[`plan.md`](plan.md), stood in for the requirement below in three more places,
and appeared **zero times here** — no source, no range, no sensitivity, in the
document where every other input gets all three.

**It is retired rather than sourced, because the argument does not need it.**
What the retention argument needs is that keeping the raw log for the mandated
window is expensive per robot and keeping the artifact is not. Both halves are
above and neither mentions a network: 182.5 TB per robot per window at the
published multiplier, against 267 GB of artifact at occurrence resolution and a
50 Hz control rate, sensitivity in [Sensitivity](#sensitivity). None of that
arithmetic moves on a site with a fibre uplink, and sourcing the premise would
have added a second empirical input carrying no weight.

**The requirement half stands, because it is a different kind of claim.**
*Off-network verifiability* — one self-contained file an assessor can check years
later with no service still running and no call to anyone — is a **requirement of
the design**, not an observation about how sites are run. These sites are heavily
instrumented and their telemetry already flows to a cloud the operator runs,
which is the reason for it: an assessor certifying what happened needs a record
whose integrity does not rest on the assessed party's infrastructure.

Requirements are stated, not sourced, so that half needs nothing from this
document. It is stated in [`limitations.md`](limitations.md) §6, in
[`plan.md`](plan.md) under Claim 4, and in `reg/commit.py`, where RFC 3161 and
transparency-log commitment are documented and deliberately unimplemented under
it.

**What would bring the premise back.** A measurement rather than an assertion:
how many deployments in the target class run isolated, over what range, with the
retention argument's sensitivity to it — the three things every other input here
carries. Absent that, no document states site isolation as fact, and
`tests/test_air_gap_framing.py` fails if one starts to."""

STALE_SENSITIVITY_PARAMS = """The artifact sizes below are **measured**, from one execution of
`python -m reg.bench --resolution --seed 0`: `long_run` at 3,000 frames **at a
50 Hz control rate**, 16 envelope samples, 200 ms horizon, 1.0 s occurrence
resolution, 0.5 s replan interval and declaration horizon, 1.0 s watchdog. Each
size is that level's measured `bytes/hour` — 60.85, 191.39 and 295.13 MB/h —
times the 4,380 hours in the retention floor."""


def test_baseline_why_is_one_sentence() -> None:
    verdict, problems = baseline_why_is_one_sentence(_baseline_text())
    assert verdict == AGREE, "\n".join(problems)
    verdict, problems = baseline_why_is_one_sentence(STALE_BASELINE_WHY)
    assert verdict == DISAGREE, "the stale Why history passes"
    assert problems
    verdict, problems = baseline_why_is_one_sentence("")
    assert verdict == COULD_NOT_EVALUATE
    assert problems


def test_baseline_no_six_month_table() -> None:
    verdict, problems = baseline_no_six_month_table(_baseline_text())
    assert verdict == AGREE, "\n".join(problems)
    verdict, problems = baseline_no_six_month_table(STALE_SIX_MONTH_TABLE)
    assert verdict == DISAGREE, "the stale six-month table passes"
    assert problems
    verdict, problems = baseline_no_six_month_table("")
    assert verdict == COULD_NOT_EVALUATE
    assert problems


def test_baseline_no_sublinear_growth_paragraph() -> None:
    verdict, problems = baseline_no_sublinear_growth_paragraph(_baseline_text())
    assert verdict == AGREE, "\n".join(problems)
    verdict, problems = baseline_no_sublinear_growth_paragraph(STALE_SUBLINEAR)
    assert verdict == DISAGREE, "the stale sublinear paragraph passes"
    assert problems
    verdict, problems = baseline_no_sublinear_growth_paragraph("")
    assert verdict == COULD_NOT_EVALUATE
    assert problems


def test_baseline_air_gap_is_a_retired_pointer() -> None:
    verdict, problems = baseline_air_gap_is_a_retired_pointer(_baseline_text())
    assert verdict == AGREE, "\n".join(problems)
    verdict, problems = baseline_air_gap_is_a_retired_pointer(STALE_AIR_GAP)
    assert verdict == DISAGREE, "the stale air-gap history passes"
    assert problems
    verdict, problems = baseline_air_gap_is_a_retired_pointer("")
    assert verdict == COULD_NOT_EVALUATE
    assert problems


def test_baseline_sensitivity_parameter_block_condensed() -> None:
    verdict, problems = baseline_sensitivity_parameter_block_condensed(
        _baseline_text()
    )
    assert verdict == AGREE, "\n".join(problems)
    verdict, problems = baseline_sensitivity_parameter_block_condensed(
        STALE_SENSITIVITY_PARAMS
    )
    assert verdict == DISAGREE, "the stale parameter block passes"
    assert problems
    verdict, problems = baseline_sensitivity_parameter_block_condensed("")
    assert verdict == COULD_NOT_EVALUATE
    assert problems


def test_baseline_sensor_multiplier_has_no_default() -> None:
    verdict, problems = baseline_sensor_multiplier_has_no_default(_baseline_text())
    assert verdict == AGREE, "\n".join(problems)
    verdict, problems = baseline_sensor_multiplier_has_no_default(
        "The benchmark enforces this in code rather than prose."
    )
    assert verdict == DISAGREE, "a text without the no-default paragraph passes"
    assert problems
    verdict, problems = baseline_sensor_multiplier_has_no_default("")
    assert verdict == COULD_NOT_EVALUATE
    assert problems


# ==========================================================================
# THE ENTRY POINTS AS POINTERS (issue #280; decisions D4 and D5).
#
# The last cut of #270 covers the entry points: the docs index, which is now
# wrong about its own contents; the front page's status restatement; and
# `docs/CONTRIBUTING.md`'s copy of `CLAUDE.md`. Under D5 `CLAUDE.md` stays
# whole, so `CONTRIBUTING.md` points at it instead of restating it.
# ==========================================================================


def _index_text() -> str:
    return (REPO / "docs" / "README.md").read_text(encoding="utf-8")


def _front_page_text() -> str:
    return (REPO / "README.md").read_text(encoding="utf-8")


def _contributing_text() -> str:
    return (REPO / "docs" / "CONTRIBUTING.md").read_text(encoding="utf-8")


def _entry_point_empty_is_no_verdict(
    text: str, name: str
) -> tuple[str, list[str]] | None:
    if not text.strip():
        return COULD_NOT_EVALUATE, [f"{name} could not be read"]
    return None


def index_states_ten_documents(
    text: str,
) -> tuple[str, list[str]]:
    """The index counts the documents it actually holds.

    Eleven `.md` files live under `docs/`, one of them this index — and there
    was no row for `self-describing.md`. The count said nine.
    """
    empty = _entry_point_empty_is_no_verdict(text, "docs/README.md")
    if empty is not None:
        return empty
    problems = []
    if "Nine documents besides this index" in text:
        problems.append("the stale nine-document count is back")
    if "Ten documents besides this index" not in text:
        problems.append("the corrected ten-document count is gone")
    return (DISAGREE if problems else AGREE), problems


def index_lists_self_describing(
    text: str,
) -> tuple[str, list[str]]:
    """`self-describing.md` gets the row the index owed it.

    The document existed before the index named it; a reader arriving at the
    folder rather than the front page had no way to learn what it answers.
    """
    empty = _entry_point_empty_is_no_verdict(text, "docs/README.md")
    if empty is not None:
        return empty
    problems = []
    if "self-describing.md`](self-describing.md)" not in text:
        problems.append("the self-describing.md row is gone")
    return (DISAGREE if problems else AGREE), problems


def index_mobile_base_row_is_a_pointer(
    text: str,
) -> tuple[str, list[str]]:
    """The mobile-base row points at that document's status line.

    The row restated what the track had built; the document's own status line
    is the authority, and a copy is how the two drift apart.
    """
    empty = _entry_point_empty_is_no_verdict(text, "docs/README.md")
    if empty is not None:
        return empty
    problems = []
    if "every tier of its §7 has landed" in text:
        problems.append("the stale mobile-base build-order restatement is back")
    if "Its status line is the authority" not in text:
        problems.append("the pointer at mobile-base.md's status line is gone")
    return (DISAGREE if problems else AGREE), problems


def index_prior_art_budget_condensed(
    text: str,
) -> tuple[str, list[str]]:
    """The prior-art row's budget sentence is a clause, not a paragraph.

    The exemption is what the reader needs; the test module that enforces it
    is named in the test module, not the index.
    """
    empty = _entry_point_empty_is_no_verdict(text, "docs/README.md")
    if empty is not None:
        return empty
    problems = []
    if "The one document **exempt from the word budget**" in text:
        problems.append("the stale prior-art budget sentence is back")
    if "**Exempt from the word budget**" not in text:
        problems.append("the condensed budget clause is gone")
    return (DISAGREE if problems else AGREE), problems


def readme_claim_rows_condensed(
    text: str,
) -> tuple[str, list[str]]:
    """Claims rows 3 and 4 are condensed, with their pinned clauses kept.

    D4 keeps the Claim 1 row; rows 3 and 4 carried narration that belongs in
    the documents they point at. What must not go with it: row 3's
    `edge_layer_basis` clause, which `test_published_figures` pins, and row
    4's status word in backticks with no gap phrases, which `test_readme`
    pins.
    """
    empty = _entry_point_empty_is_no_verdict(text, "README.md")
    if empty is not None:
        return empty
    problems = []
    for stale in (
        "The tag is checkable and not merely readable",
        "DSSAD's `R157SWIN` element is **not implemented**",
        "the `stale_declaration` fixture produces one",
        "the layer argument is [`docs/sufficiency.md`](docs/sufficiency.md) §5.10",
    ):
        if stale in text:
            problems.append(f"the stale claims-row narration is back: {stale[:40]}")
    if "edge_layer_basis" not in text:
        problems.append("row 3 lost the basis clause test_published_figures pins")
    if "`landed` — the `Declaration` record" not in text:
        problems.append("row 4 lost its backticked status word")
    return (DISAGREE if problems else AGREE), problems


def readme_personal_data_note_condensed(
    text: str,
) -> tuple[str, list[str]]:
    """The honesty note states the disclosure instead of understating it.

    The artifact states its disclosures in `docs/limitations.md` §8 and the
    cold read reports `disclosures-stated`; the note said the project had not
    addressed it.
    """
    empty = _entry_point_empty_is_no_verdict(text, "README.md")
    if empty is not None:
        return empty
    problems = []
    if "this project has not addressed that" in text:
        problems.append("the understated honesty note is back")
    if "disclosures-stated" not in text:
        problems.append("the note no longer names what the cold read reports")
    if "docs/limitations.md" not in text or "§8" not in text:
        problems.append("the note no longer points at limitations.md §8")
    return (DISAGREE if problems else AGREE), problems


def readme_status_is_a_link(
    text: str,
) -> tuple[str, list[str]]:
    """The Status section is the write-up link and nothing else.

    The descoped-GIF accounting, the placeholder paragraph and the
    read-plan.md pointer are restatements of the argument the section exists
    to send the reader to.
    """
    empty = _entry_point_empty_is_no_verdict(text, "README.md")
    if empty is not None:
        return empty
    problems = []
    for stale in (
        "is **descoped** rather than pending",
        "Nothing on this page is illustrated by a placeholder",
        "Read [`docs/plan.md`](docs/plan.md) for the argument",
    ):
        if stale in text:
            problems.append(f"the stale Status section is back: {stale[:40]}")
    if "https://ernan.dev/projects/reg" not in text:
        problems.append("the write-up link is gone")
    return (DISAGREE if problems else AGREE), problems


def readme_how_work_happens_is_a_pointer(
    text: str,
) -> tuple[str, list[str]]:
    """*How work happens* points at CONTRIBUTING.md instead of restating it.

    The impact report and the pointer at the running harness stay — the latter
    is pinned by `test_harness_pointer` — and the grooming steps live in
    `docs/CONTRIBUTING.md`.
    """
    empty = _entry_point_empty_is_no_verdict(text, "README.md")
    if empty is not None:
        return empty
    problems = []
    for stale in (
        "journalctl --user -u reg-runner -f",
        "The conventions code here must follow are in [`CLAUDE.md`](CLAUDE.md)",
    ):
        if stale in text:
            problems.append(f"the stale How-work-happens prose is back: {stale[:40]}")
    if "docs/CONTRIBUTING.md" not in text:
        problems.append("the pointer at CONTRIBUTING.md is gone")
    if "impact report" not in text:
        problems.append("the impact report is gone")
    if "nan-bit/wake-runner" not in text:
        problems.append("the harness pointer test_harness_pointer pins is gone")
    return (DISAGREE if problems else AGREE), problems


def contributing_path_is_a_pointer(
    text: str,
) -> tuple[str, list[str]]:
    """*The path a change takes* points at CLAUDE.md's *Working unattended*.

    The numbered steps restated the run's rules; the queue-and-watch commands
    are this file's own and stay.
    """
    empty = _entry_point_empty_is_no_verdict(text, "docs/CONTRIBUTING.md")
    if empty is not None:
        return empty
    problems = []
    for stale in (
        "**Someone grooms an issue.**",
        "within ~2 minutes of polling",
        "Those are different claims and the machine only makes the first one",
    ):
        if stale in text:
            problems.append(f"the restated path steps are back: {stale[:40]}")
    if "*Working unattended*" not in text:
        problems.append("the pointer at CLAUDE.md's Working unattended is gone")
    if "gh issue edit N --add-label agent-ready" not in text:
        problems.append("the queue command is gone")
    return (DISAGREE if problems else AGREE), problems


def contributing_ready_is_a_pointer(
    text: str,
) -> tuple[str, list[str]]:
    """*What makes an issue ready* names the rules instead of restating them.

    D5: the section restated `CLAUDE.md`'s *Queueing work*. No rule is lost —
    the pointer names the literal `## Affected areas` heading rule and
    "declare `tests/`", which live in `CLAUDE.md`.
    """
    empty = _entry_point_empty_is_no_verdict(text, "docs/CONTRIBUTING.md")
    if empty is not None:
        return empty
    problems = []
    for stale in (
        "Anything the writer would otherwise have to invent",
        "`epic-advance.yml` workflow flips the next tier",
        "the PR body says exactly what remains",
    ):
        if stale in text:
            problems.append(f"the restated readiness rules are back: {stale[:40]}")
    for kept in ("*Queueing work*", "## Affected areas", "declare `tests/`"):
        if kept not in text:
            problems.append(f"the pointer lost a rule it must name: {kept}")
    return (DISAGREE if problems else AGREE), problems


def contributing_pr_is_a_pointer(
    text: str,
) -> tuple[str, list[str]]:
    """*What lands in a pull request* points at CLAUDE.md's *Commits*.

    The bullets restated the repo's rules for the change itself; the draft /
    verification / `Closes #N` shape is the section's own and stays.
    """
    empty = _entry_point_empty_is_no_verdict(text, "docs/CONTRIBUTING.md")
    if empty is not None:
        return empty
    problems = []
    for stale in (
        "a smaller correct change in\n  preference to a larger speculative one",
        "no \"Generated with Claude Code\" trailer",
    ):
        if stale in text:
            problems.append(f"the restated PR rules are back: {stale[:40]}")
    if "*Commits*" not in text:
        problems.append("the pointer at CLAUDE.md's Commits is gone")
    if "`Closes #N`" not in text:
        problems.append("the Closes trailer is gone")
    return (DISAGREE if problems else AGREE), problems


#: Contiguous-verbatim text from the pre-#280 documents, each the thing its
#: predicate must refuse.
STALE_INDEX_COUNT = """Nine documents besides this index, five of them normative over something. This
page exists so that a reader arriving at the folder rather than at the front page
can tell which one answers their question, and — more importantly — which one
wins when two of them disagree."""

STALE_INDEX_TABLE = """| [`plan.md`](plan.md) | What is being built and why: the four claims, the ten phases, the non-goals table. The source document. | Binding for scope. Subordinate to `prior-art.md`. |
| [`prior-art.md`](prior-art.md) | What already exists, what this borrows, and what it must not claim is novel. Six dated passes. | **Normative** where it disagrees with `plan.md`. The one document **exempt from the word budget** in `tests/test_doc_shape.py`: a log of outside work does not get shorter when this package does. |
| [`retention.md`](retention.md) | What the artifact costs to keep, measured — Claim 1's figures, the arithmetic, and how the numbers moved. | Normative for every retention figure published anywhere. |
| [`sufficiency.md`](sufficiency.md) | Which audit questions the artifact answers on its own authority, and which are only as strong as whatever supplied the entity positions — with the basis each tag was computed from recorded beside it, per edge. Claim 3. | **Normative for what this project may claim.** |
| [`limitations.md`](limitations.md) | Each thing the artifact cannot do, what it costs, and what a claim would need in order not to inherit it. | **Normative for what this project may claim.** |
| [`lossiness.md`](lossiness.md) | What the graph keeps, what it discards, what becomes unanswerable, and the three resolution levels. | **Normative.** A design constraint on the graph, not a description of it. |
| [`sensor-baseline.md`](sensor-baseline.md) | Where the sensor-log figure every ratio is computed against comes from. | An **assumption with a sourced range**, never a measurement. |
| [`mobile-base.md`](mobile-base.md) | What allowing the robot to drive does to the bound, the layer boundary and the geometry. | **A design document whose track is built** — every tier of its §7 has landed, and its §7.3 is the authority on what the track supports. Normative for the mobile track only; defers to `sufficiency.md` and `limitations.md` on what may be claimed. |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | How work gets in and out: grooming an issue, the unattended writer, the draft PR. | Process. See also [`CLAUDE.md`](../CLAUDE.md) for the conventions code must follow. |"""

STALE_MOBILE_BASE_ROW = """| [`mobile-base.md`](mobile-base.md) | What allowing the robot to drive does to the bound, the layer boundary and the geometry. | **A design document whose track is built** — every tier of its §7 has landed, and its §7.3 is the authority on what the track supports. Normative for the mobile track only; defers to `sufficiency.md` and `limitations.md` on what may be claimed. |"""

STALE_PRIOR_ART_ROW = """| [`prior-art.md`](prior-art.md) | What already exists, what this borrows, and what it must not claim is novel. Six dated passes. | **Normative** where it disagrees with `plan.md`. The one document **exempt from the word budget** in `tests/test_doc_shape.py`: a log of outside work does not get shorter when this package does. |"""

STALE_CLAIM_ROWS = """| **4** | **Attestation** — declaration, independent verification, verdict, tamper-evident chain | `landed` — the `Declaration` record and the hash chain (`reg/chain.py`, `reg/declare.py`), independent adjudication and the nine-fault taxonomy (`reg/enforce.py`), both record chains persisted in the artifact (`reg/graph.py`), and `verify_chain` with the `--tamper` demonstration that it can say no, all exercisable end to end from a shipped fixture to a query. What the chain binds is the *party that made each record*, not the build of the policy under investigation — DSSAD's `R157SWIN` element is **not implemented**, because nothing here has a policy version to bind ([`docs/prior-art.md` §9](docs/prior-art.md)). **Passivation and reintegration are exercisable since issue #247.** The `Acknowledgment` reaches the artifact — a table, an `ACKNOWLEDGED` edge, the enforcement chain over both record kinds, and `reg.query.acknowledgments` — and the `stale_declaration` fixture produces one, so **"was the passivation acknowledged, and by whom" is a question this artifact answers**. It answers *by whom* with the signing **party** and not a person, no field of the record holding one, and a passivation the file holds no acknowledgment of is a **could-not-evaluate** rather than a *no* ([`docs/lossiness.md`](docs/lossiness.md) *Retained* #7; the layer argument is [`docs/sufficiency.md`](docs/sufficiency.md) §5.10) |
| **3** | **Sufficiency boundary** — which claims proprioception-only evidence supports, and which depend on an uncertifiable perceiver | `landed` — the Layer A/B type boundary and the test that fails when it erodes (`reg/types.py`, `tests/test_layer_boundary.py`), and the taxonomy itself in [`docs/sufficiency.md`](docs/sufficiency.md), which is normative for what this project may claim. The rule is not name-based alone, because a taint can arrive in a *value*: `Limits.source` is required with no default, and an artifact carrying none is a **could-not-evaluate** rather than a clean Layer A one ([`docs/limitations.md` §4](docs/limitations.md)). **The tag is checkable and not merely readable**: each tagged edge records what its tag was computed from in `edge_layer_basis`, and `reg.query.cold_read` reports `layer-tag-basis` as `CHECKABLE` |"""

STALE_HONESTY_NOTE = """**The artifact contains personal data, and this project has not addressed that.**
Every other limitation on this page bounds what the artifact can *answer*. This
one bounds whether it may be *kept*: per shift it records the robot's proximity
to an entity whose `kind` is `human`, contact and closest-approach occurrences
naming that entity with a wall-clock datum, and `meta[operator_id]` beside
`meta[run_start_utc]` — which together select a shift, and a shift resolves
against any roster to a person.

The minimisation is real and in the schema, not in a policy: no column here names
anybody. The obligations that remain are named and not discharged, and the AI
Act's six-month period is expressly subordinate to data-protection law — so for
that half of the artifact it may be a ceiling rather than the floor Claim 1
prices against ([`docs/limitations.md` §8](docs/limitations.md))."""

STALE_STATUS = """## Status

**Published.** The write-up — [`docs/plan.md`](docs/plan.md) Phase 10 — is at
[ernan.dev/projects/reg](https://ernan.dev/projects/reg). The GIF that phase also
listed is **descoped** rather than pending; `reg/viz.py` renders the still frame and
that is where the visual argument stops, so nothing in Phase 10 is outstanding.

Nothing on this page is illustrated by a placeholder. A plausible one would be
indistinguishable from a measured result to every later reader, and that
difference is the project's whole argument — which is also why the sensor-log
comparison is labelled a projection, and why `reg.bench --sensor-multiplier` has
no default: there is no value of that flag that makes the output claim to have
measured a robot. The incident report above **is** real output, reproduced by the
four commands beside it.

Read [`docs/plan.md`](docs/plan.md) for the argument and the full build order, and
[`docs/prior-art.md`](docs/prior-art.md) before claiming anything here is novel.
The two disagree in places; prior art wins."""

STALE_HOW_WORK_HAPPENS = """## How work happens

Groom an issue, label it `agent-ready`, and an unattended writer picks it up,
cuts a worktree, implements it, and opens a **draft PR**. A human marks it ready;
nothing on the worker host merges. What makes an issue ready, how issues declare
their order, and what has to be in the PR are in
[`docs/CONTRIBUTING.md`](docs/CONTRIBUTING.md).

Every PR the writer opens carries an **impact report** — what the change touches
and what that reaches. It is advisory: it informs the human review, it does not
gate the merge.

```bash
gh issue edit N --add-label agent-ready
journalctl --user -u reg-runner -f
```

The conventions code here must follow are in [`CLAUDE.md`](CLAUDE.md). The
harness itself is [`nan-bit/wake-runner`](https://github.com/nan-bit/wake-runner),
installed on the worker host — this repo configures it through `.runner.conf`.
[`nan-bit/issue-runner`](https://github.com/nan-bit/issue-runner) is its archived
predecessor; older commits and issues here name it and none of them mean the
harness running now."""

STALE_CONTRIBUTING_PATH = """## The path a change takes

1. **Someone grooms an issue.** Not a wish — a specification (see below).
2. **Someone labels it `agent-ready`.** That label is the queue. Applying it is the
   decision to spend a writer pass on the issue; it is a human action, deliberately.
3. **The writer picks it up** within ~2 minutes of polling, cuts a fresh worktree
   and branch (`auto/issue-N`) off `origin/main`, and implements the issue there.
   One issue → one worktree → one branch → one PR.
4. **The writer runs the issue's stated verification** and opens a **draft PR** with
   that output pasted into the body.
5. **A human reviews and marks it ready.** Merging is manual. A draft PR is the
   writer saying "here is my work"; marking it ready is a person saying "I have read
   it". Those are different claims and the machine only makes the first one."""

STALE_CONTRIBUTING_READY = """## What makes an issue ready

An issue is ready when a writer that cannot ask a follow-up question could still
finish it. Concretely, it names three things:

- **Acceptance criteria** — what must be true when the work is done, stated so that
  a reader can check each one rather than judge them.
- **Affected areas** — the paths the change is allowed to touch. Concurrent agents
  share this repo, and an unexplained edit outside the stated areas becomes someone
  else's merge conflict.
- **Verification** — the command that decides done. If the issue names a command,
  that command *is* the definition of done, and its output belongs in the PR body.

Anything the writer would otherwise have to invent — a threshold, a limit, a
filename, a default — belongs in the issue, for the reason [`CLAUDE.md`](../CLAUDE.md)
gives under *Never invent a default*. If it is missing, the writer is expected to
say so loudly rather than fill the gap.

### Dependencies between issues

Issues declare order with a `Depends-on: #N` trailer in the body. The
`epic-advance.yml` workflow flips the next tier to `agent-ready` when the issues it
depends on **close** — so a PR that says `Refs #N` instead of `Closes #N` leaves
`#N` open and stalls every task waiting on it. `Refs` is the right choice only when
scope was knowingly left unfinished, and then the PR body says exactly what remains."""

STALE_CONTRIBUTING_PR = """## What lands in a pull request

- **Always a draft.** A human marks it ready.
- **The verification output**, pasted into the body.
- **`Closes #N`** when the acceptance criteria are met.
- **The repo's rules for the change itself** — tests as the deliverable, the
  negative test beside anything that acts as a check, a smaller correct change in
  preference to a larger speculative one, and conventional-commit subjects with no
  `Co-Authored-By` and no "Generated with Claude Code" trailer. Each is stated in
  full in [`CLAUDE.md`](../CLAUDE.md), and they apply to the writer because they are
  the repo's, not the other way round."""


def test_index_states_ten_documents() -> None:
    verdict, problems = index_states_ten_documents(_index_text())
    assert verdict == AGREE, "\n".join(problems)
    verdict, problems = index_states_ten_documents(STALE_INDEX_COUNT)
    assert verdict == DISAGREE, "the stale nine-document count passes"
    assert problems
    verdict, problems = index_states_ten_documents("")
    assert verdict == COULD_NOT_EVALUATE
    assert problems


def test_index_lists_self_describing() -> None:
    verdict, problems = index_lists_self_describing(_index_text())
    assert verdict == AGREE, "\n".join(problems)
    verdict, problems = index_lists_self_describing(STALE_INDEX_TABLE)
    assert verdict == DISAGREE, "the stale table without the row passes"
    assert problems
    verdict, problems = index_lists_self_describing("")
    assert verdict == COULD_NOT_EVALUATE
    assert problems


def test_index_mobile_base_row_is_a_pointer() -> None:
    verdict, problems = index_mobile_base_row_is_a_pointer(_index_text())
    assert verdict == AGREE, "\n".join(problems)
    verdict, problems = index_mobile_base_row_is_a_pointer(STALE_MOBILE_BASE_ROW)
    assert verdict == DISAGREE, "the stale mobile-base row passes"
    assert problems
    verdict, problems = index_mobile_base_row_is_a_pointer("")
    assert verdict == COULD_NOT_EVALUATE
    assert problems


def test_index_prior_art_budget_condensed() -> None:
    verdict, problems = index_prior_art_budget_condensed(_index_text())
    assert verdict == AGREE, "\n".join(problems)
    verdict, problems = index_prior_art_budget_condensed(STALE_PRIOR_ART_ROW)
    assert verdict == DISAGREE, "the stale budget sentence passes"
    assert problems
    verdict, problems = index_prior_art_budget_condensed("")
    assert verdict == COULD_NOT_EVALUATE
    assert problems


def test_readme_claim_rows_condensed() -> None:
    verdict, problems = readme_claim_rows_condensed(_front_page_text())
    assert verdict == AGREE, "\n".join(problems)
    verdict, problems = readme_claim_rows_condensed(STALE_CLAIM_ROWS)
    assert verdict == DISAGREE, "the stale claims rows pass"
    assert problems
    verdict, problems = readme_claim_rows_condensed("")
    assert verdict == COULD_NOT_EVALUATE
    assert problems


def test_readme_personal_data_note_condensed() -> None:
    verdict, problems = readme_personal_data_note_condensed(_front_page_text())
    assert verdict == AGREE, "\n".join(problems)
    verdict, problems = readme_personal_data_note_condensed(STALE_HONESTY_NOTE)
    assert verdict == DISAGREE, "the stale honesty note passes"
    assert problems
    verdict, problems = readme_personal_data_note_condensed("")
    assert verdict == COULD_NOT_EVALUATE
    assert problems


def test_readme_status_is_a_link() -> None:
    verdict, problems = readme_status_is_a_link(_front_page_text())
    assert verdict == AGREE, "\n".join(problems)
    verdict, problems = readme_status_is_a_link(STALE_STATUS)
    assert verdict == DISAGREE, "the stale Status section passes"
    assert problems
    verdict, problems = readme_status_is_a_link("")
    assert verdict == COULD_NOT_EVALUATE
    assert problems


def test_readme_how_work_happens_is_a_pointer() -> None:
    verdict, problems = readme_how_work_happens_is_a_pointer(_front_page_text())
    assert verdict == AGREE, "\n".join(problems)
    verdict, problems = readme_how_work_happens_is_a_pointer(STALE_HOW_WORK_HAPPENS)
    assert verdict == DISAGREE, "the stale How-work-happens section passes"
    assert problems
    verdict, problems = readme_how_work_happens_is_a_pointer("")
    assert verdict == COULD_NOT_EVALUATE
    assert problems


def test_contributing_path_is_a_pointer() -> None:
    verdict, problems = contributing_path_is_a_pointer(_contributing_text())
    assert verdict == AGREE, "\n".join(problems)
    verdict, problems = contributing_path_is_a_pointer(STALE_CONTRIBUTING_PATH)
    assert verdict == DISAGREE, "the stale path steps pass"
    assert problems
    verdict, problems = contributing_path_is_a_pointer("")
    assert verdict == COULD_NOT_EVALUATE
    assert problems


def test_contributing_ready_is_a_pointer() -> None:
    verdict, problems = contributing_ready_is_a_pointer(_contributing_text())
    assert verdict == AGREE, "\n".join(problems)
    verdict, problems = contributing_ready_is_a_pointer(STALE_CONTRIBUTING_READY)
    assert verdict == DISAGREE, "the stale readiness rules pass"
    assert problems
    verdict, problems = contributing_ready_is_a_pointer("")
    assert verdict == COULD_NOT_EVALUATE
    assert problems


def test_contributing_pr_is_a_pointer() -> None:
    verdict, problems = contributing_pr_is_a_pointer(_contributing_text())
    assert verdict == AGREE, "\n".join(problems)
    verdict, problems = contributing_pr_is_a_pointer(STALE_CONTRIBUTING_PR)
    assert verdict == DISAGREE, "the stale PR rules pass"
    assert problems
    verdict, problems = contributing_pr_is_a_pointer("")
    assert verdict == COULD_NOT_EVALUATE
    assert problems
