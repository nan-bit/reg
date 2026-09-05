# Prior art — what exists, what this borrows, what it must not claim

**Status:** **normative** where it disagrees with [`plan.md`](plan.md) — prior art
wins and `plan.md` gets edited, which is the README's stated rule and this file's
whole purpose · **six passes**: 2026-08-18 before Phase 1, 2026-08-19 after the
benchmark appeared to refute Claim 1, 2026-08-21 and 2026-08-26 each prompted
by an outside reader, 2026-09-01 before the mobile track's design is built on, and
2026-09-05 before the self-describing artifact is · keep current

Each pass is kept whole and dated rather than folded into the one after it,
because half of what this file records is *when* something was found: a citation
that was there before the claim was written reads differently from one added
after the claim was published. Later passes correct earlier entries in place,
marked and dated — §1's mandate-versus-proposal amendment is the pattern, and the
correction runs in that direction only, because an entry that is quietly rewritten
stops being evidence of what was known when.

Every pass ends on a table of changes it orders into other files. §20 is what
happened when one of those tables went undischarged for five days while nothing
went red; `tests/test_prior_art.py` is why that cannot now happen quietly, and
[`plan.md`](plan.md)'s own header carries the seven ordered changes that have not
been made there yet.

---

# The entries at a glance

Twenty-nine entries across six passes. **This is an index, not a summary**: it gives
each entry a name and a place and says nothing about what it concluded. The first
cut of this table carried a fourth column of one-line verdicts, and four of the
twenty were wrong — §1's collapsed the mandate/proposal distinction that §1 was
amended on 2026-08-21 to draw, and §2's contradicted its own section outright.
That is the hazard a summary of this file carries and a list of names does not:
the distinctions here are load-bearing, several were arrived at by amendment, and
nothing mechanical can check a paraphrase of one. Read the section.

| § | Body of work | Pass |
|---|---|---|
| 1 | UNECE **DSSAD** under UN R157 | 1 · 2026-08-18 |
| 2 | **EU AI Act Article 12** | 1 · 2026-08-18 |
| 3 | **ASTM F3269** / Simplex | 1 · 2026-08-18 |
| 4 | **ARMTD / ARMOUR** | 1 · 2026-08-18 |
| 5 | **PROFIsafe** | 1 · 2026-08-18 |
| 6 | **Scene graphs** (Hydra, Kimera) | 1 · 2026-08-18 |
| 7 | **GSN** | 1 · 2026-08-18 |
| 8 | **Time-series compression** | 2 · 2026-08-19 |
| 9 | **DSSAD's data model** | 2 · 2026-08-19 |
| 10 | **Intent attestation** | 2 · 2026-08-19 |
| 11 | **The Ethical Black Box** (Winfield & Jirotka 2017) | 3 · 2026-08-21 |
| 12 | **IEEE Std 7001-2021** | 3 · 2026-08-21 |
| 13 | **ConSerts** and dynamic safety cases | 3 · 2026-08-21 |
| 14 | **Schneier & Kelsey 1998** | 3 · 2026-08-21 |
| 15 | *What the third pass did not disturb* | 3 · 2026-08-21 |
| 16 | **rosbag2 / MCAP** | 4 · 2026-08-26 |
| 17 | **SOTER** (2019) | 4 · 2026-08-26 |
| 18 | **Transparency logs** (Crosby & Wallach; RFC 6962/9162) | 4 · 2026-08-26 |
| 19 | **ISO 21448 (SOTIF)** | 4 · 2026-08-26 |
| 20 | *§14's action list, discharged* | 4 · 2026-08-26 |
| 21 | **Marvel & Bostelman** (NIST, IEEE ROSE 2013) | 5 · 2026-09-01 |
| 22 | **ISO 3691-4** and **ANSI/A3 R15.08** | 5 · 2026-09-01 |
| 23 | **RTD / REFINE** | 5 · 2026-09-01 |
| 24 | **CORA** and zonotope reachability | 5 · 2026-09-01 |
| 25 | **Set-theoretic localization** | 5 · 2026-09-01 |
| 26 | **in-toto attestations** and **SLSA** provenance | 6 · 2026-09-05 |
| 27 | **Reproducible Builds** | 6 · 2026-09-05 |
| 28 | **C2PA** content provenance | 6 · 2026-09-05 |
| 29 | **OAIS Representation Information**; **FRE 902(13)–(14)** | 6 · 2026-09-05 |

---

# First pass — 2026-08-18, before any code existed

The purpose of this pass was to find where the plan reinvents something with a
name. It found four things that change the plan and one that sharpens the
positioning considerably. Nothing found makes a phase redundant, but **Phase 2
loses a novelty claim** and the writeup gains two much better citations.

---

## 1. The finding that changes the positioning: DSSAD already exists

**UNECE DSSAD** — Data Storage System for Automated Driving, mandated by **UN R157**
for automated lane-keeping systems. It records *discrete events* during autonomous
operation: system activation, deactivation, partial failure, transition demands,
minimal-risk manoeuvres. It exists so that months later someone can determine
whether the system or the human was driving. Regulation completion targeted mid-2026.

This matters three ways:

**It validates the core design choice.** DSSAD stores events, not continuous
state — the same "emit on change, not per frame" principle as Phase 5. A mandated
standard already concluded that an event-level record is the right retention
granularity for autonomy. That is much stronger support for the compression
argument than anything the benchmark alone can produce.

**It gives the thesis a precedent instead of a hunch.** The plan currently argues
from first principles that a retained evidence artifact is needed. It does not need
to: a regulator already mandated one for cars.

**It sharpens the gap.** The current framing ("nothing specifies what the model
must emit") is true but abstract. The concrete version is stronger:

> Automated driving has a **mandated** evidence recorder. Robotics has no mandate.
> What it has is a **proposal** — Winfield and Jirotka's ethical black box, made by
> name in 2017 and given a draft data specification in 2022 (§11). And the DSSAD
> event vocabulary does not transfer either way, because it records *transitions of
> authority between human and system*, which is not the failure mode of an
> autonomous manipulator working near a person.

**Amended 2026-08-21 (issue #69).** That paragraph read "Robotics has none" until
the third pass. It was true of mandates and false of proposals, and the sentence
did not draw the line — which reads as a claim that nobody has thought of this,
nine years after somebody did. The distinction is load-bearing in both directions.
The missing *mandate* is what leaves the gap open and is the argument for doing
the work. The existing *proposal* is prior art this project has to distinguish
itself from rather than re-announce, and §11 is where that is done.

**Action:** add DSSAD to the standards table in `plan.md`; rewrite "the gap this
addresses" around it, in the mandate/proposal form above rather than the original.
Also check before writing the site piece whether the mid-2026 target slipped, since
the plan quotes several dates. `README.md`'s standards table ends on the
unqualified version of the same sentence ("Automated driving has a mandated
evidence recorder; robotics has none") and needs the same amendment — it was left
alone under issue #69, which scoped itself to this file.

---

## 2. EU AI Act Article 12 is a much better citation than "the AI Act"

Article 12 requires high-risk AI systems to **technically allow automatic
recording of events over the system's lifetime**, with logs retained for a period
appropriate to the intended purpose and **at least six months** (Article 19). The
stated purposes include identifying situations where the system presents a risk,
post-market monitoring, and monitoring operation.

The commentary consensus is that this requires **decision-level traceability** —
enough to reconstruct individual decisions after the fact, not merely an activity
log.

That is the project's thesis restated as a legal obligation. The regulation
mandates the *capability* and says nothing about the *artifact*, which is exactly
the space `reg` occupies.

**Action:** cite Article 12 specifically in the writeup, replacing the vaguer "EU
AI Act fully in force August 2026". Keep the date; add the article.

---

## 3. Phase 4 should adopt ASTM F3269's vocabulary

**ASTM F3269-21** — *Standard practice for methods to safely bound behavior of
aircraft systems containing complex functions using run-time assurance.* It
defines exactly the architecture Phase 4 describes, and it names the parts:

| F3269 term | `reg` equivalent |
|---|---|
| **Complex Function** | the policy — capable, insufficiently verifiable, out of scope |
| **Recovery Function** | the enforcement layer — bounded, verifiable, has authority |
| **Run-time monitor** | the fault detection in Phase 4 |

Using an existing standard's nouns for an existing standard's structure is free
credibility, and it also pre-empts the obvious objection that this is the Simplex
architecture with new words. It *is* the Simplex architecture; say so.

**Canonical Simplex citation:** Seto, Krogh, Sha, Chutinan, *"The Simplex
Architecture for Safe Online Control System Upgrades,"* Proc. American Control
Conference, Philadelphia, 1998, pp. 3504–3508.

**Action:** in Phase 4, state that the structure is Simplex / F3269 run-time
assurance, and that the contribution is not the architecture but the **fault
taxonomy applied to semantics**. That claim survives; the architectural one never
existed.

---

## 4. Phase 2 loses its novelty claim — and that is fine

The plan asks whether anyone computes reachable sets from proprioception only,
deliberately excluding exogenous state, and suspects it "may already have a name."
It does, and it is standard practice.

**ARMTD** (*Reachable Sets for Safe, Real-Time Manipulator Trajectory Design*,
Holmes, Kousik et al., RSS 2020) computes a parameterized reachable set for each
joint **offline and independent of any obstacle**, assembles the full-arm reachable
set in workspace, and only then **intersects it with obstacles** to generate
collision-avoidance constraints. Its successor **ARMOUR** extends this with
polynomial zonotopes.

So the Layer A / Layer B split in Phase 2 is not an insight — it is how
reachability-based trajectory design has worked for years, for the same reason
(the reachable set is a property of the robot, not the scene).

Two consequences, both improvements:

**Stop claiming it.** The novel part of `reg` is not that the envelope is
obstacle-independent. It is that the *evidence graph tags every edge with which
layer it depends on*, and therefore states which audit claims survive an
uncertifiable perceiver. That is Claim 3, and it stands.

**Fix the approximation vocabulary.** This literature computes **over-approximations**
(outer approximations) via zonotopes, because a safety guarantee requires
conservatism: the true reachable set must be contained in the computed one. The
plan's sampling method produces an **under-approximation** (inner approximation) —
the correct terms are "over-/outer-approximative" and "under-approximation", and
the plan already uses them correctly. Keep the sampling method (it is a demo, and
`plan.md` explicitly de-scopes an HJ solver), but the limitation must be stated in
the ARMTD/zonotope vocabulary and cite the alternative, or a reviewer who knows
this field will assume ignorance rather than a deliberate trade.

**Action:** Phase 2 keeps its method. `docs/limitations.md` states the under- vs
over-approximation issue in standard terms and cites ARMTD/ARMOUR as what a real
claim would require.

---

## 5. The PROFIsafe deviation is real, but state it precisely

Confirmed: published work (*Exploring Network Security in PROFIsafe*, Springer,
2009) demonstrates altering safety-related process data without any of the
protocol's safety measures detecting it. PROFIsafe assures against random
malfunction, not against an intelligent adversary; the standard's own scope says
intentional attack is out of scope. The recommended countermeasure in the
literature is defence-in-depth with separate security modules, not a stronger CRC.

One correction to the plan's wording. The CRC seed is the **Codename**, a
configured per-device value used for addressing and masquerade protection between
F-Devices — not simply "a known value". The accurate claim is narrower and
stronger:

> PROFIsafe's CRC is a *safety* mechanism. Its seed is a configuration value, not a
> secret, and the protocol is explicitly out of scope for intentional attack. `reg`
> uses HMAC because its threat model includes an adversary who has read the spec.

**Action:** correct the wording in `plan.md`'s deviation 1. The deviation itself is
sound and worth keeping prominent.

---

## 6. Scene graphs: the gap looks real, stated carefully

**Hydra** and **Kimera** (MIT SPARK) build hierarchical 3D scene graphs
incrementally from sensor streams in real time — nodes as spatial concepts at
several abstraction levels, edges as spatiotemporal relations. That is the closest
existing thing to Phase 5's schema, and the terminology should align where it is
free to do so.

Searching for treatment of the scene graph as a **retained artifact for post-hoc
audit** turned up nothing. The framing throughout that line of work is a runtime
representation supporting perception, planning and loop closure — built to be used
now, not read months later by an assessor.

**State this carefully.** Absence from a search is not proof of absence. The
honest form for the writeup is *"this line of work treats the scene graph as a
runtime representation; I found no work treating it as a retained evidence
artifact"* — a claim about what was found, which is defensible, rather than a
claim about what exists, which is not.

**Action:** align Phase 5 node/edge naming with Hydra/Kimera where it costs
nothing. Cite them as the schema ancestor.

**Re-examined 2026-08-21 (issue #69) and left exactly as it stands.** The third
pass read four further bodies of work, two of them recorders built for accident
investigators. None of them treats a scene graph as a retained artifact either,
and none of them is a counterexample to the sentence above — see §15, which says
what each of the four did and did not disturb. The hedge is better informed than
it was; it is not retracted, and it should not be strengthened into a claim about
the world.

---

## 7. GSN gives Phase 7 a better output format than prose

**Goal Structuring Notation** is the standard notation for assurance-case
arguments, and UL 4600 prescribes safety-case content for autonomous products. GSN's
elements map onto the incident report directly:

| GSN element | `incident_report()` |
|---|---|
| **Goal** | the claim being audited ("the policy stayed within its declared bound") |
| **Strategy** | the argument ("by independent verification of every declaration") |
| **Solution** | the evidence item — a specific verdict, envelope, or chain segment |
| **Assumption** | Layer B dependence, where the answer rests on perception |
| **Justification** | why proprioception-only evidence suffices for this claim |

This costs almost nothing: emit the structured output with GSN-compatible field
names alongside the human-readable prose. The payoff is that the query output
drops into an assurance case rather than needing to be transcribed into one, and
the `Assumption` slot is a natural home for the Claim 3 layer tagging.

**Action:** Phase 7 emits both prose and a GSN-shaped structure. Do **not** build a
GSN diagram renderer — that is scope creep; field names only.

---

## Summary of changes to `plan.md`

| # | Change | Phase |
|---|---|---|
| 1 | Add DSSAD to standards table; rewrite "the gap" around it | Standards, Phase 10 |
| 2 | Cite EU AI Act Article 12 specifically | Standards, Phase 10 |
| 3 | Name the Phase 4 structure as Simplex / ASTM F3269; adopt Complex/Recovery Function | Phase 4 |
| 4 | Drop the novelty claim for obstacle-independent envelopes; cite ARMTD/ARMOUR; state under- vs over-approximation in standard terms | Phase 2, limitations |
| 5 | Correct the PROFIsafe CRC wording (Codename, not "known value") | Standards |
| 6 | Align Phase 5 naming with Hydra/Kimera; hedge the retained-artifact gap claim | Phase 5, Phase 10 |
| 7 | Emit GSN-compatible field names from `incident_report()` | Phase 7 |

**Nothing here cuts a phase.** The plan survives the pass with its four claims
intact. What it loses is one novelty claim it did not need, and what it gains is a
mandated precedent (DSSAD), a legal hook (Article 12), and a standard's vocabulary
for the architecture it had already designed correctly.

---

## Still open

Not resolved in this pass; none block Phase 1.

- **IEC 61784-3 clause-level fault enumeration.** The plan wants the fault list
  verbatim to parallel it. Secondary summaries are everywhere; the actual clause
  text is paywalled. Either buy the standard or cite the PROFIsafe profile's
  published fault table and say which it is.
- **ISO 21448 (SOTIF)** — hazards from correct-but-inadequate function. Likely the
  right framing for Claim 3's sufficiency boundary. **Closed by §19** (fourth
  pass): read from secondary sources and entered, with the paywalled clause text
  recorded as the part that is still outstanding.
- **Control barrier functions** as an alternative envelope representation. Noted in
  the plan as a tradeoff to consider; not investigated, and not needed unless the
  sampling envelope proves inadequate.
- **Whether DSSAD's mid-2026 completion target held.** Affects a date in the site
  piece, nothing in the code.

---

# Second pass — 2026-08-19, after Claim 1 appeared to fail

The first pass ran before any code existed. This one ran after the benchmark
appeared to refute the compression claim, and it was aimed at one question: **was
the claim wrong, or was the measurement testing the wrong thing?** Both, in
different proportions.

**Postscript, later the same day.** The proportions turned out to be lopsided.
§8 below is right that a float codec beats this artifact on floats and always
will — but that contest was never the claim. The measurement was testing the
wrong thing, and Claim 1 has been restored on the baseline it was always about —
the sensor log named in the plan and the README hours before any benchmark ran,
not a baseline selected after a bad result. Its rate is an assumption, not a
measurement, and is documented as one in [`sensor-baseline.md`](sensor-baseline.md). §8 stands as
written: it is the reason no further encoding work is worth doing.

## 8. Time-series compression is the baseline `reg` was actually competing with

`reg.bench` compares the SQLite artifact against a **gzipped copy of the
simulator's raw state CSV** — for the priced `declared_violation` fixture, **24
columns, 19 of them Layer B** (`reg.stream.expected_header(2, 3)`: the human's
pose and velocity and each obstacle's id, kind and pose, beside the five
proprioceptive columns `reg.bench.proprioceptive_columns` returns).
That is not a naive baseline — it is close to the state of the art for this data
shape. Facebook's **Gorilla** (VLDB 2015) compresses a 16-byte `(timestamp,
value)` pair to **1.37 bytes per point** in production, via delta-of-delta
timestamps and XOR'd values; 96% of timestamps compress to a single bit.
VictoriaMetrics and RedisTimeSeries report the same order.

**What that 1.37 is and is not being compared against.** Until 2026-08-27 this
section put it beside the published **~21 B/frame** and divided that by a column
count of 9 the stream never had, to get ~2.3 B/value. Both halves were wrong:
the priced fixture's stream is 24 columns, and most of the ones the old count
left out are entity state no time-series compressor is benchmarked on, so a
per-point ratio taken over the whole stream compares two different things. The
slice a float codec is actually the incumbent for is the proprioceptive one, and
on the same fixture and seed it comes to **3,053 B gzipped over 251 frames =
12.2 B/frame**, ~2.4 B per recorded value — against Gorilla's 1.37, and still
not a clean like-for-like, because a Gorilla point carries its own timestamp
while `t` here is shared across a frame's four joint values. The published ~21
B/frame does not move; it is the full 24-column stream and is quoted as that.

So the measured comparison was **a relational store with
B-tree indexes and 64-character content hashes against a purpose-built float
codec, at storing floats.** `reg` does not store floats; it stores relationships,
verdicts and provenance. Losing that comparison is not evidence about the thesis.

**Action taken:** Claim 1 in `plan.md` is restated around an absolute retention
rate (47.3 MB/hour at transition resolution **at a 50 Hz control rate**, and
linear in that rate, re-measured 2026-08-20) plus a resolution curve, rather than
a ratio against a stream this project was never proposing to replace
byte-for-byte.

**What this does not excuse:** the per-frame cost is real and would be real
against any baseline. §10 is the response to that.

## 9. DSSAD's actual data model — and how far `reg` overshot it

§1 established that DSSAD exists and records events rather than continuous state.
This pass got the data elements. Per UN R157, for each listed event the recorder
stores at minimum:

- the **occurrence flag**
- the **reason** for the occurrence, where applicable
- the **date**, `yyyy/mm/dd`
- the **timestamp**, `hh:mm:ss` with timezone, accuracy **±1.0 second**
- the **R157SWIN** — the software version identifier present when the event
  occurred

Two consequences.

**`reg` is roughly two orders of magnitude finer than the mandate.** DSSAD:
occurrences at ±1 s. `reg`: relationships at cm / 10 ms, every frame. The
per-frame cost that sank Claim 1 is the price of a resolution **no standard
asks for**, chosen by this project without noticing it was choosing.

**The software-version element is a free gift to Claim 4.** DSSAD already
requires that a recorded event be bound to the software that produced it. That is
the same argument as `reg`'s signing keys, one level less cryptographic, and it
means "bind the record to the thing that made it" is a *requirement in force*
rather than a nice idea. `reg`'s `meta` should carry the equivalent — code
version and envelope parameters — which it partly does already.

### The element-by-element mapping, and the one that is not implemented

| DSSAD element | `reg` | Where |
|---|---|---|
| occurrence flag | implemented | `occurrence.type`, vocabulary fixed in `reg.store.OCCURRENCE_SPECS` |
| reason, where applicable | implemented | `occurrence.reason`, non-empty or refused |
| date, `yyyy/mm/dd` | implemented (issue #83) | `occurrence.date`, derived from the declared `--run-start` |
| timestamp, ±1.0 s | implemented | `occurrence.t` and `occurrence.t_utc`, at `meta[occurrence_time_resolution_s]` |
| **R157SWIN** — the software version identifier present when the event occurred | **not implemented** | see below |

**R157SWIN is not implemented, and until issue #109 this project's mapping said
otherwise.** The regulation's subject is *the automated driving system whose
behaviour is under investigation*: the element exists so an occurrence can be
attributed to the build that produced the behaviour. What `reg` had was a column
named `sw_version` carrying `reg`'s own version plus a digest of the envelope
parameters — the version of the tool that was **watching**, not of the thing
being watched — and `reg/store.py`'s schema comment presented that as the
element. Those are two different pieces of software. The mapping did not
simplify the element; it identified the wrong one, which is worse than a gap,
because a column that reads as satisfied is not looked at twice.

The gap is left open rather than filled. Nothing in this prototype has a policy
version to bind: the simulator has no policy vendor, `reg.declare.Declaration`
carries no version field, and no `META_*` key names a policy, model or vendor.
Manufacturing an identifier to fill the column would be the invented default
`CLAUDE.md` forbids, one layer up from a parameter — indistinguishable
downstream from a real one. A deployment with a real policy build is where the
element becomes bindable, and there it would be a **required, caller-supplied
input** with no default, the shape `--run-start` and the keyring already have;
it is not derivable from anything inside this process.

What survives is the recorder stamp, under a name that says what it is:
`occurrence.recorder_version` and `meta[occurrence_recorder_version]`
(`reg.graph.recorder_version`). It is not offered as R157SWIN anywhere. It earns
its place on a different argument — the same code at a different horizon
computes a different envelope and therefore a different set of
`envelope_entered` occurrences, so an occurrence is interpretable only beside
the parameters that produced it, and the digest on every row is checkable
against the parameters `meta` carries in full. `reg.graph.OCCURRENCE_RETENTION`
states the absence inside the artifact, so a reader holding only the file learns
the element is unimplemented rather than inferring it from a column that is not
there — the discipline `meta[attestation_records]` already applies to the record
tables.

This costs Claim 4 nothing it had. The "free gift" above was that *binding a
record to the software that produced it is a requirement in force*, and that
argument is about the signing keys, which do bind the party that made each
record. It was never that `reg` had already satisfied the element.

### The shape transfers and the privacy profile inverts

Added 2026-08-26 (issue #101), because the mapping table above is where this
project claims the DSSAD alignment and it is where the cost of the alignment
belongs too.

**DSSAD is privacy-light by construction.** Every element it mandates —
occurrence flag, reason, date, timestamp, `R157SWIN` — is about the *system*: a
transition of driving authority, and the build that was running when it happened.
None of them is about a person outside the vehicle, so a DSSAD record can be
retained, exported and audited without personal data being the subject of it.

**`reg` imports that shape and points it the other way.** Five of the twelve
occurrence types in `reg.store.OCCURRENCE_SPECS` — `envelope_entered`,
`envelope_left`, `contact_began`, `contact_ended`, `closest_approach` — take an
`entity_key`, and in the fixtures this project ships that entity is a human. The
edge layer beneath them records that human's separation from the machine to the
centimetre for the length of the shift, and `meta[operator_id]` names who was
running it. Same elements, opposite privacy profile: DSSAD records what the
system did, `reg` records what the system did *near someone*.

The inversion is invisible in the element-by-element table above, because it is
not a property of *which* elements exist — `reg` implements four of the five —
but of what they are filled with. That is exactly why it is written down here
rather than assumed to travel with the citation.
[`docs/limitations.md` §8](limitations.md) is the entry for what the inversion
obliges and what this project has not done about it; nothing here is a claim of
compliance.

## 10. Intent attestation now has an active adjacent field — in software, not robots

The first pass found nothing occupying Claim 4. That is no longer true, and the
writeup must not claim an empty field.

There is a 2026 line of work on **cryptographic runtime governance for AI
agents**: architectures that bind an agent to an immutable policy layer, require
it to **declare intent before acting**, evaluate that declaration against runtime
context, issue a signed authority token when it passes, block execution when it
does not, and keep a tamper-evident log of the whole exchange. Signed "intent
attestations" describing an agent's current purpose are a named primitive there.

That is recognisably the same shape as Phases 3–4 of this project.

**What is still distinct, stated carefully:**

- That work governs **software agents** — tool calls, data access, API actions.
  `reg` governs a **physical control policy**, where the bound is a region of
  space the body may occupy and the failure is contact with a person.
- Its lineage is zero-trust and supply-chain security. `reg`'s is **industrial
  functional safety** — IEC 61784-3's black channel, PROFIsafe's fault taxonomy
  and passivation, ASTM F3269's Complex/Recovery Function split.
- It is not answerable to ISO 10218, ISO 25785-1 or DSSAD, and does not have to
  produce evidence an assessor will accept under a machinery regulation.

**Action for Phase 10:** say "this pattern is emerging for software agents; this
applies it to a physical policy under machinery-safety precedent" rather than
"nothing occupies this space". Cite the field. Being second in a field and first
in a domain is a defensible claim; being wrong about the field is not.

## Changes this pass makes to the plan

| # | Change | Where |
|---|---|---|
| 8 | Claim 1 restated as retention rate + resolution curve, not a ratio | `plan.md` Claim 1 |
| 9 | DSSAD data elements added to the standards table; occurrence layer proposed | `plan.md` standards, Claim 1 |
| 10 | Claim 4's novelty narrowed from "unoccupied" to "new domain for an emerging pattern" | `plan.md` Phase 10 |
| — | Claim 2 reframed from speedup to answer-agreement | `plan.md` Claim 2 |

---

# Third pass — 2026-08-21, four bodies of work named by an outside reader

The first two passes were run by the author, which is the weakness they share: a
search only finds what its author knows to look for. This one was prompted from
outside — an external technical review with no context on the project named four
things absent from this file, two of them close enough that their absence read as
unfamiliarity rather than as a hedge. All four were read before the entries below
were written, and all four turned out to be on point; none is left out for lack of
relevance, and where one is a looser match than the reviewer implied (§13.2) that
is said in the entry rather than fixed by dropping it.

What the pass costs, stated up front so it is not buried in four long sections:

- **§11 takes the thesis.** A robot carrying a flight-data-recorder equivalent so
  that an accident can be reconstructed is Winfield and Jirotka's proposal from
  2017, not this project's idea. Two of `reg`'s four claims are refinements *of*
  that proposal.
- **§14 takes the chain.** `reg/chain.py` is Schneier and Kelsey's 1998
  construction minus its forward security. §5 cited PROFIsafe for the deviation
  and never cited the thing being deviated from.
- **§13 takes the structure of Claim 3.** Guarantees that hold conditional on
  evidence supplied at runtime were formalised as ConSerts in 2013.
- **§12 is the one that costs nothing and was simply missing.** IEEE 7001-2021
  grades transparency to accident investigators on an ordinal scale, and a
  ten-row standards baseline that omits it looks like it was assembled from
  memory.

What survives each is stated in each entry. It is smaller every time and it is
still there — and in two of the four cases what survives is *retention*, which is
the one axis none of this work is on.

---

## 11. The ethical black box — this project's thesis, proposed by name in 2017

**Winfield, A.F.T. and Jirotka, M., "The Case for an Ethical Black Box",** in
*Towards Autonomous Robotic Systems* (TAROS 2017), LNCS 10454, Springer,
pp. 262–273. Followed by **Winfield, van Maris, Salvini and Jirotka, "An Ethical
Black Box for Social Robots: a draft Open Standard"** (2022, arXiv:2205.06564),
which is an RFC-style draft 0.1 with a full record specification, and by
**Winfield, Winkle, Webb, Lyngs, Jirotka and Macrae, "Robot Accident
Investigation: a case study in responsible robotics"** (in *Software Engineering
for Robotics*, Springer, 2021).

The 2017 paper proposes that robots and autonomous systems be fitted as standard
with the equivalent of an aircraft Flight Data Recorder, continuously recording
sensor and relevant internal status data, so that an investigator can afterwards
establish why the robot did what it did. Its outline specification collects from
three subsystems: from the sensors, sampled or compressed raw data or extracted
features; from the actuators, the **demands** ("steer left 10 degrees"); and from
the AI, as a minimum a high-level state ("braking", "steering left") and ideally
the goals and the alerts that drove those demands. Everything date- and
time-stamped. The stated key principle is that the recorded data must be enough to
**reconstruct the timeline leading up to and during an accident**, annotated with
the sensory inputs, the actuator demands and the high-level decisions.

That is this project's thesis, published nine years before this project, in
robotics, under a name. It has to be cited as the ancestor and not restated as a
finding.

The 2022 draft standard is the more useful document to compare an artifact
against, because it is concrete. It defines three ASCII record types — one
MetaData record (robot name, manufacturer, operator, responsible person, EBB
version), one DataData record (how many robot-data records are held, and the date
and time of the oldest and the newest), and *n* RobotData records holding actuator
demands and actual values, touch/IR/line sensors, gyro, accelerometer,
temperature, WiFi status, a microphone WAV clip, a camera JPEG frame grab, text
commands and replies, and a four-character decision code with an optional reason
string. Each record ends in a `chkS` checksum specified as **a 64-bit
non-cryptographic hash function, to be determined.** The RD records are written in
a ring: after record *n*, the writer returns to record 1 and overwrites.

### What `reg` does that the EBB does not

**1. The record is not the policy's self-report.** The EBB's defining structural
property is that data flows are strictly one-way and the EBB is *passive* — it
accepts data from the robot controller and must not affect the robot's operation.
The 2022 draft repeats this and notes, in a footnote, that letting the robot read
its own EBB to answer "why did you do that?" would violate the passivity
principle. The consequence is not stated in either paper and it is the whole of
`reg`'s Claim 4: **everything in an EBB is on the authority of the thing under
investigation.** A controller that logs `decC = 0042: "obstacle detected, braking"`
is the same controller whose behaviour is in question, and the record inherits
whatever was wrong with it. `reg` splits the record in two — a `Declaration` the
policy signs and a `Verdict` an enforcement layer signs after recomputing the
envelope from proprioception and the actuation limits, importing from `declare/`
no further than the dataclass. The verdict is not a log of what the policy said; it
is a second party's finding about it, and the two are separable in the artifact
because they are signed under different keys by different roles.

**2. The integrity mechanism is a checksum, and the records are not linked.**
`chkS` is unkeyed and 64-bit, covers one record, and is explicitly undetermined
as to algorithm. Nothing binds record *i* to record *i−1*. An RD record can be
edited and its checksum recomputed by anyone who has read the draft; a contiguous
run of records can be deleted and every remaining checksum still verifies; the
ring's wrap means position carries no order either. The 2017 paper's entire
treatment of this is one sentence — "the EBB will of course also need to be secure
and tamper-proof" — which is a requirement, not a mechanism. `reg` supplies the
mechanism: HMAC-SHA256 per record under a role-typed key, a `prev_hash` link
whose break is reported with both ends, and a verifier with three outcomes that
refuses to call an empty artifact verified. That mechanism is not `reg`'s
invention either — see §14 — but the gap between "must be tamper-proof" and a
construction that has been analysed in the literature since 1998 is a real gap,
and it is the one place where this project is straightforwardly ahead of the draft
standard.

**3. Retention. This is the difference to lead with.** The EBB is a ring buffer.
The 2017 paper does the arithmetic itself: sample or compress a driverless car's
output to ~100 MB/s, fit a 1 TB solid-state drive, and you hold **about three
hours**, continuously overwriting the oldest data, exactly as an FDR does. The
2022 draft makes the ring normative. That is a device for the hours *before* an
accident, and it is the right design for reconstructing a crash. It is not a
design for the question EU AI Act Article 12 and Article 19 actually ask, which is
what an operator can still produce **six months later**, and it is not a design for
answering anything without re-reading the raw record. `reg`'s Claim 1 — retention
rate per unit of resolution, and which queries still `AGREE` after the discard — is
a question about the far side of the ring buffer's horizon. Nothing in the EBB
line addresses it, and nothing in it contradicts the answer.

**4. The artifact is expected to answer, not to be interpreted.** The 2017 paper
is explicit that transparency "is not achieved by the EBB alone but through the
processes of accident investigation", and §5 of that paper — the best part of it —
is about those processes: multiple witnesses, police forensics, the manufacturer
called to explain, and the epistemological status of different kinds of witnessing.
The EBB supplies the timeline that other accounts are superposed on. `reg`'s
Claim 2 is narrower and stronger in one respect: the audit question is answered
**from the graph alone**, with the raw stream gone, and the answer carries the
layer it depends on. Claim 3's layer tag is what an investigator would otherwise
have to reconstruct by knowing which fields of the log came from a perceiver.

### What the EBB does that `reg` does not

Almost everything physical and almost everything social. It is a hardware
proposal as much as a data one — rugged enough to survive a serious accident,
with a specified connector, signalling and protocol, and a defined physical
interface by which an investigator gets the data out. It covers a whole robot,
including the sensor stream: an RD record can carry a JPEG frame grab and a WAV
clip, which is Layer B raw data that `reg` deliberately holds none of. It has a
draft open standard, a stated intent to ship model implementations, and an
accident-investigation methodology behind it with a published case study. `reg`
has a simulated planar arm, no hardware story at all, and no account of the human
process an artifact is handed into.

### Contribution, or different setting?

**Both, and the split is clean.** The thesis is the EBB's. Two of `reg`'s
differences are contributions to it rather than a different setting: independent
computation of what gets recorded (§11.1) and retention past the ring buffer
(§11.3). One is a straightforward improvement the draft standard should take
(§11.2, and it should take it from §14, not from here). The rest of what `reg`
does is a narrower instance of Winfield and Jirotka's proposal, and the README
should say so in those words.

**Action for Phase 10 and the README:** cite the 2017 paper as the proposal this
project is an instance of, and the 2022 draft as the closest existing data
specification. State `reg` as *an ethical black box whose contents are
independently computed and whose retention horizon is the regulator's, not the
ring buffer's* — which is a claim about two properties, not about the idea.
Do **not** claim the idea.

---

## 12. IEEE Std 7001-2021 — the scale this project should have been graded on

**IEEE Std 7001-2021, *IEEE Standard for Transparency of Autonomous Systems*.**
Companion paper: Winfield et al., "IEEE P7001: A Proposed Standard on
Transparency", *Frontiers in Robotics and AI* 8:665729 (2021).

7001 defines measurable levels of transparency, 0 (none) to 5 (the maximum
achievable), separately for five stakeholder groups: users; the general public and
bystanders; safety certification agencies; **incident and accident investigators**;
and lawyers and expert witnesses. A System Transparency Specification states the
level targeted for each group and a System Transparency Assessment grades the
system against it. Compliance is voluntary.

The investigator ladder is the one that matters here. As the P7001 paper describes
it: **level 1** is a recording device allowing capture and playback of the
situation around the robot leading up to and during an accident; **level 2** adds a
data logging system holding a date- and time-stamped record of sensor inputs, user
commands and actuator outputs; **level 3** requires that logger to conform to an
existing open or industry standard and to additionally log high-level decisions;
**level 4** adds the **reasons** for those decisions; **level 5** requires the
designers to give investigators tools for visualising the log.

Its absence from a ten-row standards baseline was conspicuous for a specific
reason, not a general one: **this is the only published standard that grades an
evidence recorder instead of requiring one**, and Claim 1's restatement after the
second pass was precisely "resolution as the measured variable" (§8, and
`plan.md`). The project built an ordinal scale of its own — occurrence, transition,
per-frame — while an ordinal scale addressed to the same reader already existed.

### What `reg` does that 7001 does not

7001 says a log must exist and, at level 3, that it must conform to **"an existing
open or industry standard"** — naming none, because for robotics there is none.
That is the same gap §1 describes from the mandate side, restated from the
standards side by a published standard: the transparency requirement is specified,
the artifact that satisfies it is delegated to a document nobody has written. `reg`
is a candidate for exactly that delegation, and the 2022 EBB draft (§11) is the
other one. This is the strongest external support the project has for the claim
that the gap is real, because it is a gap a standards working group wrote down.

### What 7001 does that `reg` does not

It grades four other stakeholder groups, and it defines an assessment procedure
that `reg` has never been run through. **No compliance claim may be made.** Saying
"`reg` reaches level 4" would be an unassessed self-grade against a standard with
a defined assessment, which is worse than saying nothing.

And there is a more interesting reason the self-grade cannot be made even
informally, which is a genuine finding of this pass:

> **`reg` cannot be placed on 7001's investigator ladder at all, and the reason it
> cannot is Claim 3.** The ladder is content-cumulative and its base is level 2 —
> sensor inputs, user commands, actuator outputs. `reg` holds **no sensor inputs
> and no user commands**; the envelope takes a `ProprioState`, which has no field
> naming any entity, and that absence is enforced by
> `tests/test_layer_boundary.py`. What it does hold is level-4-shaped: a `Verdict`
> carries an `outcome` and a `fault` from a fixed taxonomy, which is the reason for
> a decision, bound cryptographically to the declaration it adjudicated. So the
> artifact sits above the ladder's top on one axis and below its second rung on
> another, because the ladder assumes the entity-facing record is the *base* of the
> evidence and this project's entire argument is that the entity-facing record is
> the part that cannot be certified.

That is worth stating publicly rather than resolving. It is a concrete instance of
the sufficiency boundary showing up in someone else's normative document.

**Action:** add IEEE 7001-2021 to the standards baseline in `plan.md` and the
README, with the investigator levels quoted and the observation above stated as an
observation. Do not claim a level. If a level is ever claimed, it is after an STA,
and `docs/sufficiency.md` is where the "cannot be placed on the ladder" argument
belongs in full.

---

## 13. ConSerts and dynamic safety cases — Claim 3's structure, formalised in 2013

### 13.1 ConSerts — the close one

**Schneider, D. and Trapp, M., "Conditional Safety Certification of Open Adaptive
Systems"**, ACM Transactions on Autonomous and Adaptive Systems, 2013, and
"Engineering Conditional Safety Certificates for Open Adaptive Systems" (2013);
later positioned as the first implementation of a Digital Dependability Identity
in **Schneider, Trapp, Papadopoulos, Armengaud, Zeller and Höfig, "WAP: Digital
Dependability Identities"** (arXiv:2105.14984).

A ConSert is a safety certificate issued at development time — by safety experts
or an authorised body, after a manual check of the argument, like any other
certificate — which certifies **guarantees that hold conditional on demands**. Two
kinds of operand discharge a condition: *demands* on services provided by other
components, satisfied at runtime by those components' own guarantees; and
**runtime evidences (RtE)**, where "in principle, any runtime analysis providing a
Boolean result can be used", split into intra-device evidence (self-contained) and
inter-device evidence (requiring standardised information from others). The
relation between demands and a guarantee is a Boolean function over a directed
acyclic graph — a tuple of Boolean inputs, gates, edges and one Boolean output —
and a ConSert is one such function per guarantee level per offered service, with
levels typed by a domain integrity scale (AgPL under ISO 25119, SIL elsewhere). At
runtime the systems match guarantees against demands and establish which guarantee
level currently holds; the example in the DDI paper has three, from full
automation down to a default that can always be granted.

**This is Claim 3's structure, and it is thirteen years old.** "Which claims
survive an input whose assurance you do not have" is guarantee–demand matching. The
warning §4 issued about ARMTD applies again in the same words: a reviewer who knows
this field will read an unqualified Claim 3 as ignorance rather than as a
deliberate narrowing.

**What ConSerts does that `reg` does not.** It grades. A ConSert has multiple
guarantee levels per service, each typed by an integrity level from a domain
standard, and losing a demand moves the system down the ladder rather than off it.
`reg` has one bound and a verdict per commanded action; it has no notion of "this
claim holds at integrity level d, and at level b if perception is unavailable", and
it could not currently express one. ConSerts is also **prospective and it gates
behaviour**: the evaluation decides whether the systems may cooperate at all, right
now. And it has an engineering method, tool support and a certification story.
`reg`'s layer tag is a column derived from a type table in one module.

**What `reg` does that ConSerts does not — and it is one thing.** ConSerts
evaluates its condition and acts on the result; **the evaluation is not retained.**
Nothing in the approach produces an artifact from which a third party can
establish, months later, that a particular claim was conditional and on what. `reg`
carries the tag as a column in every edge and every occurrence of a stored
artifact, so the conditionality of an answer survives into the audit, which is the
question ConSerts was not built for. State the surviving novelty exactly that
narrowly: **not that claims can be conditional on runtime evidence, which is
ConSerts, but that the conditionality of each answer is retained and queryable
after the fact.**

There is also a difference in the case being handled, and it cuts the other way
from how it first looks. A ConSert demand is discharged by a component that
**carries its own assurance**; the whole mechanism assumes the supplier can offer a
typed guarantee. `reg`'s Claim 3 is about the case where it cannot and never will —
an uncertifiable perceiver has no guarantee to give. In ConSerts' vocabulary Layer
B is a permanently undischargeable demand, and ConSerts' answer to that is correct
and well-defined: withdraw the guarantee, degrade to the default. `reg` does not
withdraw anything; it answers the question and marks the answer. Those are answers
to two different questions — *may I act* versus *what may be concluded afterwards* —
and the second is not a weaker version of the first.

**Free vocabulary, on the same terms as §3's.** A `reg` `Verdict` is an
intra-device runtime evidence in ConSerts' sense: a runtime analysis returning a
Boolean-typed result about the current configuration. Using an existing formalism's
nouns for a structure that formalism already covers is the same trade that adopting
F3269's Complex/Recovery Function was.

### 13.2 Dynamic safety cases — the looser one, kept in for what it consumes

**Denney, E., Pai, G. and Habli, I., "Dynamic Safety Cases for Through-Life Safety
Assurance"**, Proc. 37th ICSE (2015), vol. 2, pp. 587–590; building on **Denney,
Naylor and Pai, "Querying Safety Cases"** (SAFECOMP 2014, LNCS 8666, pp. 294–309).

A DSC is a safety argument that keeps evolving after deployment. It comprises
assurance variables (system, environment, artifacts, events); an argument structure
whose nodes carry metadata linking them to those variables; a confidence structure,
e.g. a Bayesian network; a collection of monitors returning discrete or continuous
values with a period; and update rules of the form *condition → action*, where the
condition is a formula over the confidence structure and the action is selected by
a query over the argument. The worked rules are the point: an observation that
invalidates an assumption removes the branch of the argument that depended on it,
and a confidence drop below a threshold creates a task for an engineer to inspect
the evidence beneath a named node.

This is a **looser match to `reg` than the reviewer implied**, and it is kept in
for a reason rather than for symmetry. What a DSC updates is the *argument*. Its
monitored data is an input to a confidence computation, not the retained thing;
the artifact it maintains is the safety case. `reg` produces the other half — the
evidence item a monitor would read and an argument node would point at. They
compose rather than compete, and §7 already identified the seam without knowing
this work existed: an `incident_report()` that emits GSN-shaped field names is
emitting exactly what a DSC's argument metadata links to. The honest one-line
version is that **the dynamic safety case is the consumer this project's output was
designed for, named.**

What it does that `reg` does not: a query language over an argument, a confidence
model, and a lifecycle for revising claims when assumptions are violated. `reg` has
no argument structure and updates nothing. What `reg` does that it does not: it is
the evidence, tamper-evident and layer-tagged, which DSCs assume exists and say
nothing about producing.

**Action for Phase 9:** cite ConSerts in `docs/sufficiency.md` as the formalism
that already covers conditional guarantees, and narrow the sentence about what the
layer tag contributes to *retention of the conditionality*, which is what survives
the reading. Adopt "runtime evidence" for what a `Verdict` is. Cite Denney & Pai in
Phase 7 beside GSN, as the consumer of the structured output — not as a competitor.
**No claim in `plan.md` is edited by this pass**; see the note below.

---

## 14. Schneier & Kelsey 1998 — where `reg.chain` actually comes from

**Schneier, B. and Kelsey, J., "Cryptographic Support for Secure Logs on Untrusted
Machines"**, 7th USENIX Security Symposium, 1998; journal version, "Secure Audit
Logs to Support Computer Forensics", ACM Transactions on Information and System
Security 2(2), 1999. Forward integrity for logs is due to **Bellare and Yee**; the
analysis quoted below is from **Ma, D. and Tsudik, G., "A New Approach to Secure
Logging"** (IACR ePrint 2008/185).

The construction. A logging machine `U` opening a log establishes a secret `A₀`
with a trusted remote server `T`. Each entry `Lᵢ` holds the entry type `Wᵢ`, the
data encrypted under a key derived from the type and the current secret, a hash
chain element `Yᵢ = H(Wᵢ ‖ Cᵢ ‖ Yᵢ₋₁)`, and a MAC `Zᵢ = MAC_{Aᵢ}(Yᵢ)`. After each
entry the secret is evolved through a one-way function, `Aᵢ₊₁ = H(Aᵢ)`, and the old
value **deleted** — which is the property the scheme exists for: an attacker who
takes the machine at time *b* obtains `A_b` and can write whatever they like from
then on, but cannot forge or undetectably alter anything written before *b*. `U`
closes the log with a final record and erases the remaining secrets. A verifier `V`
walks the hash chain itself and sends only `Yf` and `Zf` to `T`, which knows `A₀`
and can therefore recompute `Af`.

**`reg/chain.py` is that, minus the forward security.** Per-record MAC, per-record
link to the predecessor's hash, one canonical preimage, a walk that checks both.
The module header cites the black channel and §5 cites PROFIsafe for the deviation
to HMAC; nothing cited the construction, which has a name, a 1998 paper and thirty
years of analysis behind it.

Two consequences, and only one of them is comfortable.

**The truncation limit the module header documents is a named attack, and the
answer it proposes is the known one.** `chain.py`'s header states that deleting the
last record of a chain breaks no link, that the two witnesses which catch it — the
`meta` counts and the `FOLLOWS` edges — carry no MAC, and that what defeats it is
an external commitment to the final chain hash. That is the **truncation attack**,
named against exactly this construction by Ma and Tsudik in 2008: the attacker
erases a contiguous run of tail-end entries, and no `Yᵢ` protects anything written
after *i*, so nothing detects it unless a trusted party knows the current record
count. The literature's fix is the one the header reaches for (synchronisation with
`T`, or an external commitment) plus later schemes — forward-secure *aggregate*
MACs — which resist it without a trusted party by making verification
all-or-nothing. Arriving at a correct statement of a known limitation
independently is fine. Publishing it as though the limitation were peculiar to this
artifact is not, and the header should cite.

**Two things `reg` does that the 1998 scheme does not**, neither of them
cryptographic:

- **Two chains, two parties, role-typed keys.** Schneier–Kelsey has one logger.
  Its per-entry type `Wᵢ` governs who may *read* an entry, not who *wrote* it —
  attribution is not a question the scheme asks, because there is only one writer.
  `reg` splits the record by issuer: declarations under the policy key, verdicts
  under the enforcement key, a `Key` that carries its own role, and a `sign` that
  raises rather than producing a MAC that would verify under the wrong party. That
  is the mechanism Claim 4 rests on and it is absent from the ancestor because the
  ancestor had no use for it.
- **A verifier with three outcomes.** `ChainState` is VERIFIED, BROKEN or
  COULD-NOT-EVALUATE, `ChainReport.__bool__` raises, and an artifact with no
  records, no stated count or no key comes back could-not-evaluate rather than
  verified. The 1998 paper's verification is pass/fail, as almost all of them are.
  This is software-engineering discipline — the house rule that a check must be
  able to fail — not a contribution to secure logging.

**Three things the 1998 scheme does that `reg` does not**, and the third is the
one that is not currently written down anywhere in the repository:

- **Forward security.** `reg`'s keys are static for the life of a run;
  `generate_keyring` draws from OS entropy once and nothing evolves. An attacker
  who obtains the enforcement key can rewrite and re-sign the entire verdict chain
  back to genesis. Under Schneier–Kelsey they could not touch anything written
  before the compromise.
- **Entry confidentiality and access control.** `reg` stores records in the clear
  in SQLite. Deliberate — the artifact is meant to open without a runtime — but it
  is a difference from the scheme, not an absence in it.
- **A verifier that never holds the key.** In Schneier–Kelsey, `V` verifies the
  chain and asks `T` about the MAC; `V` never learns `Aᵢ` and therefore cannot
  forge. `reg` hands the auditor the keyring, so **anyone who can verify a `reg`
  artifact can also forge one.** The honesty note in `chain.py` and the README says
  both keys living in one process demonstrates the structure of non-repudiation
  rather than non-repudiation; it does not say this, and this is a separate and
  sharper statement of the same weakness. It is the price of offline verification
  with no trusted server — which also buys something real, since it is why `reg`
  has no *delayed detection* problem, the second drawback Ma and Tsudik identify in
  Schneier–Kelsey.

### Contribution, or different setting?

**Neither: a reimplementation, in a new setting, weaker than the original on the
axis the original was written for.** That is not a criticism of the code — the
setting genuinely differs, and the two additions above are the right ones for it —
but it settles what may be claimed. Nothing about `reg`'s chain is novel, and the
one paragraph in the README that reads as though the construction were designed
here should read as an application of a known one.

**Action:** cite Schneier–Kelsey 1998/1999 wherever the chain is introduced
(README, `plan.md` Phase 6, `chain.py`'s module header) and cite Ma & Tsudik 2008
beside the truncation paragraph. Record the missing forward security in
`docs/limitations.md` as a **named, deliberate absence** rather than an oversight,
together with the verifier-holds-the-key asymmetry. Whether to add key evolution is
a Phase 6 design question and not a small one — it changes what an auditor must be
given and when — and this file's job is to record that the gap is a deviation from
a known scheme, not to decide it.

**Status: discharged by issue #104** (fourth pass, §20), which also added the
history tree and Certificate Transparency beside the truncation paragraph (§18) —
citing a named attack without its published fix reproduces this section's own
complaint one level down.

---

## 15. What this pass did not disturb

**§6's hedge stands, in the form it was written in.** It says this line of work
treats the scene graph as a runtime representation, and that *I found no work
treating it as a retained evidence artifact* — a claim about the search, not about
the world. Each of the four readings was checked against it and none is a
counterexample:

| Read | Does it retain a graph for post-hoc audit? |
|---|---|
| Ethical black box (§11) | No. A ring buffer of flat, time-stamped records — no relationships, and the horizon is hours. |
| IEEE 7001 (§12) | No. It requires a log *conforming to an existing open standard* and names none; the artifact is delegated, not specified. |
| ConSerts (§13.1) | No. Guarantee–demand matching is evaluated at runtime and the evaluation is discarded. |
| Schneier–Kelsey (§14) | No. A secure log format, indifferent to what an entry means. |

The hedge is now better informed by four bodies of work, which is why it should
keep exactly the form it has: four searches that did not find a thing are still
four searches.

**No claim in `plan.md` is edited by this pass, and none needed to be.** Claim 3 as
`plan.md` states it — *which claims the proprioception-only layer can support, and
which depend on an uncertifiable perceiver* — is a statement of a deliverable and
asserts no novelty, so ConSerts does not contradict it; what ConSerts constrains is
the *positioning* around it, which is §13's action and belongs in
`docs/sufficiency.md` and the writeup. Claim 4's novelty was already narrowed in
§10 from "unoccupied" to "new domain for an emerging pattern"; §11 narrows the
domain claim further — the *pattern* of a robot evidence recorder is Winfield and
Jirotka's — and what remains is independent computation and retention horizon,
which is a smaller and still defensible statement. Claim 1 and Claim 2 are
untouched by all four.

## Changes this pass makes to the plan

| # | Change | Where |
|---|---|---|
| 11 | Cite the ethical black box as the proposal this project is an instance of; state `reg` as an EBB with independently computed contents and a regulator's retention horizon | README, `plan.md` Phase 10 |
| 11a | Amend the "robotics has none" sentence to distinguish mandate from proposal | §1 above (**done**), `README.md` standards table (**not done** — outside issue #69's scope) |
| 12 | Add IEEE 7001-2021 to the standards baseline with the investigator levels; state that `reg` cannot be placed on that ladder and that Claim 3 is why; claim no level | `plan.md` standards, README, `docs/sufficiency.md` |
| 13 | Cite ConSerts as the formalism covering conditional guarantees; narrow the layer-tag contribution to *retained* conditionality; adopt "runtime evidence" for a `Verdict`; cite Denney & Pai beside GSN as the consumer | `docs/sufficiency.md`, `plan.md` Phases 7 and 9 |
| 14 | Cite Schneier–Kelsey as the chain's construction and Ma & Tsudik for the truncation attack; record the missing forward security and the verifier-holds-the-key asymmetry | README, `plan.md` Phase 6, `chain.py` header, `docs/limitations.md` (**done** — issue #104, §20) |

## Still open after this pass

- **The full text of IEEE 7001-2021.** The investigator levels above are as the
  P7001 paper describes them, not as the published standard words them. Anything
  quoted in the writeup must come from the standard itself, which is paywalled —
  the same problem §"Still open" records for IEC 61784-3.
- **Whether the EBB draft standard advanced past draft 0.1.** It was an RFC in
  2022 inviting comment. If a later draft specified the checksum, §11.2 needs
  re-reading before it is repeated anywhere public.
- **Forward security for `reg.chain`.** Named as a gap in §14, not designed, and
  now **recorded** as a named absence in [`limitations.md`](limitations.md) §7
  (issue #104) — which is not the same as closed. It is a Phase 6 question about
  key custody, not an encoding change.
- **ConSerts' guarantee levels as a model for graded claims.** `reg` has one bound
  and a binary verdict. Whether the sufficiency boundary should be graded rather
  than binary is a real design question this pass opened and did not answer.

---

# Fourth pass — 2026-08-26, three named by a second external review, one this file kept calling unread

The third pass was prompted from outside and found four bodies of work. A second
external review, reading the file the third pass produced, named three more — and
then pointed at this file's own action lists, which is the sharper of its two
observations. §14 ordered four citations on 2026-08-21 and none of them was in the
repository on 2026-08-26; the file that says *publishing a known limitation as
though it were peculiar to this artifact is not fine* had published exactly that
for five days, because a survey's action list is prose and prose does not fail.
Issue #104 is where that was discharged (§20), and
`tests/test_prior_art.py` is what keeps it discharged.

What the pass costs, up front:

- **§16 names the incumbent.** Every retention comparison this project publishes
  was against a gzipped copy of the simulator's own raw state CSV — 24 columns
  for the priced fixture, 19 of them Layer B. What practitioners actually retain
  is a **rosbag2/MCAP** bag, and a reader who runs one was never told this file
  knew the name. The arithmetic does not move; the honesty of the framing does.
- **§17 takes "Simplex, applied to a learned policy, in robotics".** SOTER did
  that in 2019, with a switching rule derived from a reachability check, a
  composition proof and a flying drone. §3 said "it *is* the Simplex
  architecture; say so" and then cited a 2001 paper and a 2021 standard with the
  2019 robotics implementation between them missing.
- **§18 takes the append-only log, again and further.** §14 gave the chain back to
  Schneier and Kelsey. §18 observes that the problem has moved on twice since —
  history trees in 2009, Certificate Transparency in 2013 — and that the
  truncation limit `chain.py`'s header documents has a **published structural
  fix** this project does not use.
- **§19 costs nothing and was overdue.** ISO 21448 is the standard's own name for
  what `docs/sufficiency.md` describes in longhand. It has been listed as *not yet
  read* since the first pass.

What survives, as in the third pass, is **retention** and **attribution**. It is a
smaller pair every time and it is still there.

---

## 16. rosbag2 and MCAP — the incumbent every retention figure was quietly compared against

**rosbag2**, the recording subsystem of ROS 2, and **MCAP** — the container format
(Foxglove, Apache-2.0, spec at `mcap.dev`) that has been rosbag2's default storage
plugin since ROS 2 Iron (2023), superseding its SQLite plugin and ROS 1's `.bag`.
Read alongside the `mcap` CLI and Foxglove, which are what an engineer opens a bag
with.

**What it is.** A container of length-prefixed, opcode-tagged records — Header,
Schema, Channel, Message, Chunk, MessageIndex, ChunkIndex, Attachment, Metadata,
DataEnd, Footer — holding serialised messages, each tagged with its channel and
carrying both a log time and a publish time. Messages are grouped into chunks,
chunks are compressed (zstd or lz4) and indexed, so a reader seeks to a time range
without decoding the file. **Schemas are embedded**, so a bag is self-describing: it
opens years later without the ROS installation that wrote it, which is why the
format has users outside ROS. Integrity is a **CRC32** over each chunk and over the
data section.

**Why its absence from this file mattered.** Not because a bag is a competitor —
it is not, and the section below says why — but because it is the thing a buyer
already has. A retention argument addressed to someone who runs rosbag2 and is told
about a gzipped CSV is an argument that has not met its reader. Two independent
reviews named it, in two rounds, before it was written down.

### What `reg` does that a bag does not

- **It is not the robot's self-report.** Every record in a bag arrives on the
  authority of the system under investigation — the same property §11 identifies
  in the ethical black box, and for the same reason: a recorder writes what it is
  handed. `reg`'s two chains hold what the policy *declared* and what an
  independent check *concluded*, under different keys, and the artifact says which
  one was wrong when they disagree.
- **CRC32 is error detection, not tamper evidence.** It catches a flipped bit on
  disk. An attacker who edits a message recomputes it in a line of code. There is
  no key, so there is nothing to forge and nothing to attribute.
- **A bag is *designed* to survive truncation, which is the same thing as being
  unable to detect it.** MCAP's summary section and index sit at the end and are
  optional precisely so that a recorder killed mid-write leaves a readable file.
  That is the right engineering call for a recorder, and it means the attack
  `chain.py`'s header documents and Ma & Tsudik name (§14) is not an anomaly in a
  bag — it is a supported state. `reg` cannot detect the same attack either,
  without an external commitment; the difference is that `reg` treats it as a
  limit to be written down and a bag treats it as a feature.
- **Content, not carriage.** A bag is indifferent to what a message means, in
  exactly the way §14 says Schneier–Kelsey is indifferent to what an entry means.
  There is no verdict, no fault taxonomy, no layer tag, and therefore no
  representation for *which of this answer's conjuncts came from the perceiver* —
  the question Claim 3 exists to make askable.
- **A retention horizon.** This is the one that matters and it is not a
  cleverness: bags hold every message on the recorded topics at full rate, so the
  practice is hours to days on the robot with selective upload, and the six-month
  question is answered by **deleting**. `reg`'s comparison is therefore not "a
  smaller file with the same contents". It is a different and much smaller thing,
  kept for a period nobody keeps a bag for.

### What a bag does that `reg` does not

- **Replay.** `ros2 bag play` reconstitutes the messages and a stack can be re-run
  against them. `reg` retains no inputs and can replay nothing, by construction —
  the envelope takes a `ProprioState` and the artifact holds no sensor data at all.
- **Self-description of its semantics.** MCAP embeds a machine-readable schema for
  every message it holds. A `reg` artifact carries its SQLite schema and a `meta`
  table of stated rules, which is the same instinct — but the meaning of a `fault`
  value or a `layer` tag still lives in this repository, not in the file.
- **Indexed random access, an install base and tooling.** Foxglove renders a bag;
  nothing renders a `reg` artifact except `reg.query` and `reg.viz`.

### What this does *not* change, and one thing it does

**The benchmark is not re-run against a bag, and §8 is why.** That section already
settled that a purpose-built float codec beats a relational store at storing
floats and that the contest was never the claim. Adding a third float container to
that comparison buys nothing.

It does, however, sharpen one figure's direction. The `~40x larger` comparison
is against a **gzipped copy of this project's own raw state stream at
`reg.stream.FLOAT_PRECISION`** — text, quantised to the artifact's stated
resolution before it is compressed, and **24 columns wide for the priced
fixture, 19 of them Layer B**. A bag carries the joint states out of it as CDR
doubles with all 52 mantissa bits, a per-message record header and two
timestamps, under a general-purpose compressor that does no better on float
noise than gzip does (§8's Gorilla citation is the same observation from the
other side). So the incumbent is very probably **larger** than the baseline this
project chose to lose against, and the `~40x` is against the most favourable
possible comparator rather than the real one. **That is argued, not measured** —
it is in "Still open" below, and no published figure is edited on the strength
of an argument.

**And the two sides do not carry the same content, which is the part to keep
hold of.** A `/joint_states` bag holds the five proprioceptive columns; the
gzipped CSV in the `~40x` holds all 24, the human's ground-truth pose and
velocity included. `docs/sensor-baseline.md`'s incumbent section (issue #117)
prices the encoding like-for-like on the proprioceptive slice alone and gets
**2.51x**, so the bag is dearer per unit of the *same* content — but a bag
priced against the full stream would also be carrying less of the world. Neither
number is a licence to say the incumbent is 2.51x the `~40x` baseline.

**Action:** name rosbag2/MCAP as the incumbent wherever the retention comparison
is introduced. **Partly done, and not by this pass.** `docs/sensor-baseline.md`
gained an *incumbent encoding* section in 54175ee (issue #117) that names the
format and prices it: MCAP `/joint_states` is **2.51x** a gzipped CSV carrying the
same content, computed from the MCAP specification and recorded as a projection
rather than a measurement. **README and `plan.md` Claim 1 still describe the
baseline without naming what it stands in for** — outside issue #104's affected
areas, the same way §11a records the README standards table.

---

## 17. SOTER — Simplex with an implementation, in robotics, in 2019

**Desai, A., Ghosh, S., Seshia, S.A., Shankar, N. and Tiwari, A., "SOTER: A
Runtime Assurance Framework for Programming Safe Robotics Systems"**, DSN 2019
(arXiv:1808.07921); and **"SOTER on ROS: A Run-Time Assurance Framework on the
Robot Operating System"**, RV 2020. Beside it, the runtime-verification-for-robotics
line: **Huang, Erdogan, Zhang, Moore, Luo, Sundaresan and Roşu, "ROSRV: Runtime
Verification for Robots"**, RV 2014; **Ferrando, Cardoso, Fisher, Ancona,
Franceschini and Mascardi, "ROSMonitoring: A Runtime Verification Framework for
ROS"**, TAROS 2020.

**SOTER.** A runtime-assurance *module* as a language construct. Each module wraps
an unverified **advanced controller** — explicitly allowed to be a learned or
otherwise unverifiable component — with a verified **safe controller** and a
switching rule, and the framework derives the switching rule from a time-bounded
reachability check on a plant model: if the advanced controller's proposed action
cannot be shown to keep the system inside the safe set for the response window,
control transfers to the safe controller and returns after a settling period.
Composition of modules is proved to preserve the safety invariant, and the whole
is demonstrated on a drone surveillance mission in simulation and on hardware.

That is the architecture §3 already names — Simplex, in ASTM F3269's vocabulary —
with the two things §3's citations did not have: an implementation in robotics, and
a switching condition *computed* rather than hand-written. `reg/enforce.py`'s
`horizon_bound` is the same decision procedure one dimension poorer (a radius, not
a region — [`docs/limitations.md`](limitations.md) §3), and `reg` stops where SOTER
continues, at the refusal.

**ROSRV** interposes on the ROS master, checks messages against monitors generated
from formal specifications, and can **block** a command that violates one — and it
carries an access-control layer saying which nodes may publish what, which is the
nearest thing in this line to `reg`'s role-typed keys. **ROSMonitoring** generates
monitor nodes from an RML specification and runs them online or **offline against a
recorded log** — the closest anything here gets to retention, and it is worth being
precise about how close: the log is the monitor's *input*, the verdicts are the
monitor's output, and nothing writes the verdicts back into the log as records that
a later reader could check. The artifact stays a bag (§16).

### What `reg` does that SOTER does not

- **It retains.** A SOTER switch is a control decision; neither paper produces an
  evidence artifact, and what a SOTER deployment has afterwards is §16's bag. The
  reason the switch fired — the containment check that failed — is not in it.
- **It attributes.** SOTER's advanced and safe controllers are two modules of one
  program, written, compiled and deployed by one team. The independence is
  architectural. `reg`'s is between **parties**: the import rule asserted against
  the source at the AST level, plus two keys carrying their roles, and a `sign`
  that raises rather than producing a MAC that would verify under the wrong one.
  Nothing in SOTER asks who wrote a verdict, because there is only one author —
  structurally the same absence §14 finds in Schneier–Kelsey's single logger.
- **Three outcomes.** A switching condition is binary because it has to be; it is
  in the loop. An adjudicator that runs after the robot has stopped can afford
  COULD-NOT-EVALUATE, and this project requires it.

### What SOTER does that `reg` does not

- **The recovery half, working, on a real vehicle.** `reg`'s passivation and
  reintegration reach no table, no edge type and no query, and `graph.build`
  refuses a run containing one (README; issue #112). ASTM F3269's
  Complex/Recovery split is cited in §3 and only half of it is exercisable here.
- **A derived switching condition and a composition proof.** SOTER computes the
  safe set from a model; `reg`'s bound is hand-derived, radial, and incomplete in
  a documented direction.
- **Guarantees at the language level.** SOTER's argument is a proof over the P
  program. `reg`'s is a unit test over a hand-written bound.

### Contribution, or different setting?

**Different setting — and the setting is downstream of SOTER's, not beside it.**
SOTER decides; `reg` records what was decided so that someone who was not there can
check it. Nothing here is a better runtime monitor and this file should not be read
as claiming one. What it does cost is a sentence nobody has written but a reader
might infer: **"runtime assurance applied to a learned policy" is not this
project's move, it is SOTER's from 2019**, and any positioning that leans on the
novelty of bounding an unverifiable controller in robotics is leaning on something
already occupied. What is not occupied is the record.

**Action:** cite SOTER and SOTER-on-ROS in `reg/enforce.py`'s module header beside
the Simplex and F3269 citations already there, and in `plan.md` Phase 4, as the
robotics implementation of the architecture rather than as a competitor. **Not done
in this pass** — `reg/enforce.py` and Phase 4 are outside issue #104's affected
areas.

---

## 18. Transparency logs — the append-only-log problem, with proofs instead of a walk

**Laurie, B., Langley, A. and Kasper, E., "Certificate Transparency", RFC 6962
(2013)**; **Laurie, Messeri and Stradling, "Certificate Transparency Version 2.0",
RFC 9162 (2021)**. Underneath them: **Merkle, R., "Protocols for Public Key
Cryptosystems"** (IEEE S&P 1980) for the hash tree, and **Crosby, S. and Wallach,
D., "Efficient Data Structures for Tamper-Evident Logging"** (USENIX Security
2009) for the **history tree**, which is written directly against the
Schneier–Kelsey line §14 places `reg` in. Deployed descendants worth knowing exist:
**CONIKS** (Melara et al., 2015), Google's **Trillian**, the **Go checksum
database** (Cox, "Transparent Logs for Skeptical Clients", 2019) and
**Sigstore/Rekor** (2021).

**The construction.** Entries are leaves of a Merkle tree and the log periodically
signs a tree head. Two proofs, each O(log n) hashes: **inclusion** — this entry is
under this head — and **consistency** — the tree under this head is a prefix
extension of the tree under that earlier head, so nothing committed before it was
altered or removed. A client that has ever seen one head can check that the log is
append-only without holding the log. Because an operator can still show different
heads to different clients, deployments add **gossip** and **witness cosigning**: a
set of witnesses countersign the heads they have seen, and a head without enough
cosignatures is not accepted.

Three things this settles about `reg/chain.py` and `reg/commit.py`. Only the first
is comfortable.

**1. `reg` solves a solved problem with the 1998 structure rather than the 2009
one.** A hash chain is verified by walking every record; a tree is verified by
exhibiting a logarithmic number of hashes. For an artifact opened whole by one
auditor, the walk is fine and the tree buys nothing. It stops being fine the moment
an auditor is handed *part* of an artifact — a chain cannot prove a record's
membership without the records around it, and a tree can. Whether this project is
ever asked for a partial disclosure is a question nobody has put to it; if it is,
the answer in the literature is a tree.

**2. The truncation attack has a structural fix that needs no trusted server at
write time.** `chain.py`'s header says what defeats truncation is "an external
commitment to the final chain hash", and §14 repeats it. That is correct and it is
narrower than what is known: a consistency proof against **any** previously
published head detects the removal of anything committed before it, and the
append-only property is *proved* to the verifier rather than assumed from a count
that carries no MAC. The gap between `reg` and the state of the art here is not the
commitment — `reg/commit.py` commits both heads at close — it is that the
commitment supports no inclusion proof and is held by a party the operator chose.

**3. `--witness` is witness cosigning with one witness, inside the operator.**
[`docs/limitations.md`](limitations.md) §6 already says the independence is only as
good as the site. This line of work supplies the name for what is missing: a split
view is detected by parties who **compare** heads with each other, and a single
witness on the operator's payroll compares nothing. Stated this way the gap is
located rather than merely admitted — `reg` is not missing a timestamp, it is
missing a gossip set, and RFC 3161 (which `commit.py` and the README already name)
is the weaker of the two things it could adopt.

### What `reg` does that a transparency log does not

- **Content.** CT logs opaque certificates and asserts nothing about what they
  mean; it is content-indifferent in exactly the way §14 finds Schneier–Kelsey to
  be, and the way §16 finds a bag to be. Every question Claim 2 answers is a
  question about what a record *says*.
- **Two writers with typed roles.** A CT log has one appender. The policy /
  enforcement split has no analogue in it.
- **Offline verification.** Every property CT offers costs a network call: the
  SCT, the monitors, the gossip. `reg`'s claim is a file that verifies years later
  with no service still running and no call to anyone. That is not a better
  design — it is the other end of a trade, and CT is what the other end looks
  like.
- **Three-valued verification**, again, and again as software-engineering
  discipline rather than as a contribution.

### What a transparency log does that `reg` does not

Everything in the construction above — proofs rather than a walk, a log operated by
someone with no relationship to the party writing entries, split-view detection,
and a signed statement about *when*. And the sociological half, which is the part
worth stating carefully because this repository has a sentence that skips it:

> `docs/limitations.md` §6 says a transparency log "would additionally make a
> *withheld* artifact detectable". **It would, conditionally.** A log makes a
> withheld entry detectable to a party who independently knows the entry should
> exist — in CT, the domain owner who knows which certificates they asked for.
> Nothing in the log supplies that expectation. For `reg` the equivalent is
> somebody who knows a shift ran and can therefore notice that no artifact was
> committed for it, which is an operational arrangement and not a property of the
> data structure.

That sentence is **not edited here**; issue #104 records the finding and leaves the
claim to whoever owns §6.

### Contribution, or different setting?

**Neither, and this one has no consolation.** §14 established that `reg`'s chain is
a reimplementation of a 1998 construction; §18 establishes that the 1998
construction was itself superseded for this problem, twice, in ways that address
the exact limitation `chain.py` documents. What `reg` has is a *reason* — offline,
one auditor, no service still running — and that reason is a requirement this
project set for itself, not a gap in the literature. Nothing about the chain is
novel and nothing about it should be described as solving the append-only-log
problem.

**Action:** cite Crosby & Wallach and RFC 6962/9162 in `chain.py`'s header beside
the truncation paragraph, as the structural answer this artifact does not use.
Whether to adopt a tree is a Phase 6 design question and interacts with the forward
security §14 opened — both are about what an auditor is given and when, and neither
is decided here.

---

## 19. ISO 21448 (SOTIF) — the vocabulary Claim 3 has been paraphrasing since the first pass

**ISO 21448:2022, *Road vehicles — Safety of the intended functionality*,**
published 2022 after ISO/PAS 21448:2019.

**Read from secondary sources, not from the clause text.** The standard is
paywalled, the same status this file records for IEC 61784-3 and IEEE 7001. What
follows is its scope and its vocabulary as the published literature and ISO's own
scope statement describe them; **nothing below is a quotation**, and anything
quoted in the writeup has to come from the standard itself. That is a different
status from *not yet read*, which is what this file said for three passes and
cannot say again: the shape of the standard, what it is for and what it asks are
not behind the paywall, and an assessor reads "unread" as unfamiliarity with the
one document that names this project's central problem.

**What it is.** ISO 26262 covers hazards caused by **malfunctions** — a component
fails and the system does something it was not built to do. 21448 covers the
complementary case: hazards that arise with **no fault at all**, from functional
insufficiencies of the intended function or from reasonably foreseeable misuse. A
perception stack working exactly as built that does not see a person in low sun has
not malfunctioned; it has met a **triggering condition** for a **performance
limitation**. Its organising device is a partition of scenarios into four areas —
known and not hazardous, known and hazardous, **unknown and hazardous**, unknown
and not hazardous — and the work of the standard is to shrink the second and third
until a stated **acceptance criterion** for residual risk is met.

**The third area is [`docs/sufficiency.md`](sufficiency.md) §6 in longhand, without
the name.** That document already writes:

> A person nobody detected leaves an artifact that answers *no contact* with total
> confidence.

That is an unknown hazardous scenario produced by a performance limitation,
described from the evidence side rather than the validation side.
[`docs/lossiness.md`](lossiness.md) *Unanswerable* #2 states the same thing about
the artifact. The vocabulary — functional insufficiency, performance limitation,
triggering condition, acceptance criterion — is the language an automotive assessor
would read Claim 3 in, and it costs this project nothing to use it.

### What `reg` does that 21448 does not

**21448 is a development-time argument.** It says what must be analysed, validated
and argued before release, and nothing about what a system must **record while
running** so that the argument can be checked afterwards. That is the same gap §1
records from the mandate side and §12 from the transparency-standard side, arriving
now from a third direction: the analysis is specified, the evidence that it held in
the field is not.

What `reg` retains against that gap is narrower than it is tempting to say, so it
is worth saying exactly. **`reg` cannot evidence a triggering condition.** It holds
no perceptual input and by construction never will — the envelope takes a
`ProprioState`, and `tests/test_layer_boundary.py` fails if that erodes. What it
retains is the **dependence**: per edge and therefore per answer, whether the
answer rested on the uncertifiable perceiver. That tells an investigator which
sentences of a report would have to be re-examined if a triggering condition were
later established from some other source. It does not tell them a triggering
condition occurred.

### What 21448 does that `reg` does not

- **An acceptance criterion.** 21448 asks for a quantified residual-risk target and
  an argument that meets it. `reg` has no notion of *enough*;
  [`docs/sufficiency.md`](sufficiency.md) §7 already says the project attempts no
  perception assurance case.
- **Reasonably foreseeable misuse**, for which this artifact has no
  representation at all.
- **A domain that matches.** 21448 is road vehicles. The manipulator standards
  (ISO 10218, ISO/TS 15066) have no SOTIF analogue, so borrowing the vocabulary is
  borrowing across domains and should be labelled as such wherever it is used.

### The mapping that must not be drawn

**Layer A / Layer B is not SOTIF's four areas, and the resemblance is a trap.**
SOTIF partitions **scenarios**, by whether they are known and whether they are
hazardous. `reg` partitions **claims**, by which evidence they rest on. A Layer A
verdict is not "Area 1", and the tempting correspondence — Layer B ≈ areas 3 and
4 — is wrong in a way that would mislead an assessor: the layer tag is about the
*provenance* of an answer and says nothing whatever about whether the scenario that
produced it was anticipated. A Layer B answer in a thoroughly known scenario is
still Layer B. Adopting the vocabulary means adopting the words for the perception
problem, not the taxonomy.

### Contribution, or different setting?

**Neither: a lens.** 21448 is not prior art for anything `reg` built; it is the
name for the problem Claim 3 is about, and the reason to enter it is that an
assessor who knows the name will notice its absence.

**Action:** adopt SOTIF's vocabulary in `docs/sufficiency.md` where Area 3 is
currently in longhand, and add ISO 21448 to the standards baseline in `plan.md` and
the README. **Not done in this pass** — outside issue #104's affected areas.

---

## 20. §14's action list, discharged

The second observation of the review that prompted this pass was not about a body
of work. It was that §14 ends in an instruction and the instruction had not been
carried out — so the module whose header describes a known attack as though this
project had found it kept describing it that way for five days after the file
saying that is not acceptable was committed.

| §14 ordered | Where | Status |
|---|---|---|
| Cite Schneier–Kelsey 1998/1999 wherever the chain is introduced | `README.md`, honesty note | **done** (#104) |
| " | `docs/plan.md` Phase 6 | **done** (#104) |
| " | `reg/chain.py` module header | **done** (#104) |
| Cite Ma & Tsudik 2008 beside the truncation paragraph | `reg/chain.py` module header | **done** (#104) |
| Record the missing forward security as a named, deliberate absence, with the verifier-holds-the-key asymmetry | `docs/limitations.md` | **done** (#104), §7 |

Two things were added that §14 did not order and §18 did: the truncation paragraph
also names the history tree and Certificate Transparency as the structural answer,
because citing the attack and not its published fix reproduces the same defect one
level down.

**And the mechanism, which is the part that matters.** An action list in a survey
file is prose, and this repository's rule is that a check must be able to fail.
`tests/test_prior_art.py` now asserts each of the citations above against the
source of the file it was ordered into, asserts that SOTIF is not described as
unread, and — the half that makes it a check rather than a decoration — is fed the
pre-#104 text of each file and required to say **no**.

---

## What this pass did not disturb

**§6's hedge stands, for the fifth and sixth searches.** None of the four retains a
graph for post-hoc audit:

| Read | Does it retain a graph for post-hoc audit? |
|---|---|
| rosbag2 / MCAP (§16) | No. A time-ordered message stream with embedded schemas; no relationships, and the horizon is hours to days. |
| SOTER (§17) | No. It retains nothing at all; the switch is a control decision. |
| Transparency logs (§18) | No. An append-only log of opaque entries, indifferent to what an entry means. |
| ISO 21448 (§19) | No. Not an artifact — a development-time argument. |

**No claim in `plan.md` is edited by this pass.** Claim 1's arithmetic is untouched;
§16 changes the *name of the incumbent* in the prose around it and argues one
figure's direction without measuring it. Claim 2 is untouched. Claim 3 gains a
vocabulary and no competitor — 21448 asks a different question about a different
partition (§19). Claim 4 is untouched by §17, which occupies the runtime half and
not the record, and by §18, which strengthens §14's existing conclusion that
nothing about the chain is novel rather than adding a new one.

**Two positioning risks are recorded rather than fixed**, both per the rule that a
survey does not edit the claims it bears on:

- Any sentence implying that bounding a learned policy at runtime in robotics is
  this project's move is leaning on ground SOTER occupied in 2019 (§17).
- `docs/limitations.md` §6's "would additionally make a *withheld* artifact
  detectable" is conditional on an independent expectation the data structure does
  not supply (§18).

## Changes this pass makes to the plan

| # | Change | Where |
|---|---|---|
| 16 | Name rosbag2/MCAP as the incumbent wherever the retention comparison is introduced; state that the horizon, not the size, is the difference | `sensor-baseline.md`, README, `plan.md` Claim 1 (**not done** — outside #104) |
| 17 | Cite SOTER and SOTER-on-ROS as the robotics implementation of Simplex/F3269, beside the citations already in the header | `reg/enforce.py`, `plan.md` Phase 4 (**not done** — outside #104) |
| 18 | Cite the history tree and CT beside the truncation paragraph as the structural answer this artifact does not use | `reg/chain.py` header (**done**) |
| 19 | Adopt SOTIF's vocabulary where Area 3 is written in longhand; add ISO 21448 to the standards baseline | `docs/sufficiency.md`, `plan.md`, README (**not done** — outside #104) |
| 14 | The third pass's four citations and the forward-security entry | README, `plan.md` Phase 6, `chain.py`, `limitations.md` (**done** — §20) |

## Still open after this pass

- **A measured MCAP bag of the proprioceptive slice of the same stream** — a real
  `mcap` writer with real `zstd`, against the projection issue #117 computed from
  the specification. §16 argues the incumbent
  is larger than the gzipped CSV and does not measure it. Until it is measured the
  argument stays in this file and out of every document that publishes a figure.
- **The clause text of ISO 21448.** Paywalled, like IEC 61784-3 and IEEE
  7001-2021. §19 is entered from secondary sources and says so.
- **Whether the chain becomes a tree.** §18 names the structure that fixes the
  truncation limit and the partial-disclosure limit at once. It is a Phase 6
  design question, it interacts with the forward-security question §14 opened, and
  neither is decided in a survey.
- **Whether a witness set replaces a witness.** `--witness` is cosigning with
  N = 1 inside the operator (§18). Raising N is an operational change, not an
  encoding one, and off-network verifiability survives it.
- **Whether SOTIF's areas belong in `docs/sufficiency.md` at all**, given §19's
  warning that the two partitions are on different axes. Adopting the vocabulary
  is safe; adopting the taxonomy is not, and the document has to say which it did.

---

# Fifth pass — 2026-09-01, before the mobile track's design is built on

The first four passes were prompted by a phase boundary, a benchmark, and two
outside readers. This one is prompted by this repository's own rule:
[`docs/mobile-base.md`](mobile-base.md) was written on 2026-08-31, it makes
claims about mobile-robot safety practice and about reachable-set construction
for nonholonomic vehicles, and this file — normative over `plan.md` — had an
entry for none of it. The survey goes in **before** the design is built on, which
is what the first pass's own header says it is for. Nothing in the mobile track
is code yet, so this is the cheapest moment this pass will ever be available at.

What the pass costs, up front:

- **§21 dates a citation the design leans on.** Marvel & Bostelman's finding that
  neither parent standard covers a mobile manipulator was true in 2013 and is not
  now — ANSI/A3 R15.08 defines the category. The *unbounded work volume* half of
  the citation survives untouched, because that is a property of the machine; the
  *no standard covers this* half must not be repeated in 2026.
- **§22 finds that the standards' answer to an unbounded work volume is the same
  shape as this project's.** A speed-dependent **protective field in the vehicle
  frame**, plus a guaranteed stop. `docs/mobile-base.md` §2 arrived at that split
  independently and can stop presenting it as an analogy — and must simultaneously
  stop short of the word, because *protective field* carries a conformance rating
  nothing here has.
- **§23 takes "refusal is what you do when the workspace is unbounded".** RTD's
  answer is a **fail-safe manoeuvre** verified in advance and appended to every
  plan. Refusal is still right *here*, for a reason `reg`'s architecture supplies;
  §1 of the design document concluded it without recording that an alternative
  exists.
- **§24 costs nothing and corrects one sentence.** Conservative linearization is
  what makes a nonlinear model analysable at all; the convexity §3 complains
  about is the *zonotope representation*, and polynomial zonotopes are the same
  tool's other one. The Minkowski sum §3 proposes is this literature's primitive.
- **§25 is the one that changes what the project may say.** Set-theoretic
  localization is the only candidate in this survey for making a room-frame pose
  certifiable. It does not — and the reason generalises: **no localizer of any
  kind can**, because the room frame is defined by things outside the robot. The
  base pose is Layer B *structurally*, not for want of a better estimator.

What survives, as in the third and fourth passes, is **retention** and
**attribution**. It is the same pair each time, and none of the five retains
anything.

**A note on sources before the entries, because four of the five have a
boundary.** The NIST paper's PDF did not extract and §21 is written from its
abstract and from secondary sources. Both standards in §22 are paywalled and it
is entered from secondary sources and vendor summaries, with **no clause number
cited anywhere in it** — a clause number is exactly the thing that cannot be
checked from a summary, and quoting one would be the defect §19 names rather than
the one it avoids. §23 and §24 are from published preprints and tool
documentation; no code was run. Each entry says this in its own first lines,
because a reader who reaches one entry does not necessarily read this paragraph.

---

## 21. Marvel & Bostelman 2013 — the gap that was named, and has since been partly filled

**Marvel, J.A. and Bostelman, R., *"Towards Mobile Manipulator Safety
Standards,"* Proc. IEEE International Symposium on Robotic and Sensors
Environments (ROSE), Washington DC, 2013.** NIST. Beside it, the same group's
measurement line — Bostelman, Hong and Marvel, *"Survey of Research for
Performance Measurement of Mobile Manipulators,"* J. Research of NIST, 2016.

**Read from its abstract and from secondary sources; the paper PDF did not
extract.** Nothing below is a quotation, and
[`docs/mobile-base.md`](mobile-base.md) §1 already labels its use of the paper a
paraphrase. That is the same status this file records for IEC 61784-3, IEEE 7001
and ISO 21448, arrived at for a different reason — not a paywall, a file.

**What it is.** A standards-gap analysis. A mobile manipulator is a manipulator
on a driven base, and in 2013 it fell between two families that each assume away
the other's problem: the industrial-robot standards (ANSI/RIA R15.06, ISO 10218)
assume a **fixed, surveyable work volume** that a risk assessment can be written
against, and the driverless-truck standards (ANSI/ITSDF B56.5, and the ISO 3691
line) assume the vehicle's payload does not **reach**. Composed, the machine has
a work volume that is effectively unbounded and not predictable in advance, and
neither parent standard's safeguarding argument survives the composition. The
paper argues for the category, for test methods, and for measurement.

**What has changed since, and it is why this entry is dated rather than cited
flat.** The gap is, in part, closed. **ANSI/A3 R15.08-1** (2020, requirements on
the manufacturer) and **R15.08-2** (2023, on the integrator) define the
*industrial mobile robot* as a category and distinguish types by whether a
manipulator is fitted and whether it may operate while the platform is in motion
(§22). So a 2013 citation for *no standard covers this* is a citation to a state
of the world that has moved, and using it that way in 2026 is the same species of
error as §1's "robotics has none" — a true sentence about a mandate, published as
a sentence about the field. The citation for *the work volume is effectively
unbounded* is unaffected, because that is a statement about the machine and not
about who has written a document.

### What `reg` does that the NIST paper does not

- **It retains something.** The paper specifies no artifact, no record and no
  format; it is an argument about which committee owns a machine and what would
  have to be measured. Nothing in it survives the run it describes.
- **It attributes.** No keys, no two parties, nothing to forge — the paper is not
  in that business at all.
- **It tags the dependence.** The whole of Claim 3 has no counterpart here.

### What the NIST paper does that `reg` does not

- **It treats the composed machine as the unit of analysis**, which is precisely
  what this repository does not do: there is no base anywhere in the tree
  ([`docs/mobile-base.md`](mobile-base.md) §4 checked, and found none).
- **It is grounded in measurement.** NIST's mobile-manipulator work is artifacts,
  ground truth and repeatability figures for real machines. `reg` has no notion of
  a *measured* positioning performance at all; `Limits` are **declared**, and
  `Limits.source` exists (issue #84) precisely because this project cannot
  measure them and must record whose number it was given.
- **It addresses a standards committee.** This project addresses an investigator
  reading an artifact months later, which is a different reader with a different
  question.

**Action:** `docs/mobile-base.md` §1 keeps the paraphrase and gains the
date-limit: the paper for the unbounded work volume, R15.08 for the composition.
**Done in this pass**, and §6's summary row moves with it.

---

## 22. ISO 3691-4 and ANSI/A3 R15.08 — the standards that own the mobile case

**ISO 3691-4, *Industrial trucks — Safety requirements and verification — Part 4:
Driverless industrial trucks and their systems*** (first edition 2020, revised
2023); **ANSI/A3 R15.08-1-2020** and **ANSI/A3 R15.08-2-2023, *Industrial Mobile
Robots — Safety Requirements*** (A3, the Association for Advancing Automation,
formerly RIA).

**Both are paywalled. Entered from secondary sources and vendor summaries — the
same status this file records for IEC 61784-3, IEEE 7001-2021 and ISO 21448.**
Nothing below is a quotation and **no clause number appears anywhere in this
entry**, deliberately: a clause number is the one thing a summary cannot support,
and citing one would read as a full read of a document nobody here has opened.
What is not behind the paywall is the shape of the safeguarding argument, which
is what this entry is for.

**What they are.** The safety case for a driverless vehicle is not built on
knowing where the vehicle is. It is built on a **protective field**: a region,
monitored by a safety-rated device — in practice a safety laser scanner — defined
**in the vehicle's own frame**, sized so that the vehicle can come to a stop
before anything detected in the field is reached. The field is **switched with
speed and steering**, because the stopping distance is; the guaranteed action on a
detection is a stop. R15.08 carries the same structure to a machine with a
manipulator on it and takes on what the arm adds. Map-based pose estimation is a
**navigation** function in this architecture, not a safety one: it runs on
sensing that is not safety-rated, and nothing about the safeguarding argument
depends on it being right.

**The finding: this is the same object as the body-frame envelope, and
`docs/mobile-base.md` §2 arrived at it independently.** A protective field is a
**horizon-limited region in the vehicle frame, sized by what the vehicle can do
before it stops**. That is `reg.envelope.outer_envelope(state, limits, window)`
with the window set by the stopping time, and the split that document draws — a
Layer A body-frame set and a Layer B pose — is not an analogy to safety practice.
It is the partition safety practice already draws, for the same reason: the
body-frame quantity is the one that can be argued about without trusting a
perceiver. Two independent derivations agreeing is worth more to that document
than the derivation was.

**And the warning that arrives with it, which is the half a hurried reading would
drop.** *Protective field* is a term of art with a **conformance meaning**: a
field is the output of a rated device, at a stated performance level, validated
by a stated procedure, in a system somebody assessed. `reg`'s envelope is a
`shapely` polygon computed by unrated Python from a simulator, and calling it a
protective field would claim the rating along with the noun. This is exactly the
trap §12 records for IEEE 7001's investigator levels — *state that the project
cannot be placed on that ladder, and claim no level* — arriving a second time
from a second standard. The design document may say the body-frame set **is what
a protective field is**; it may not say it is one.

### What `reg` does that a protective field does not

- **It is retained.** A field is evaluated continuously and **discarded
  continuously**. A stop leaves a stop; nothing months later says what region was
  being monitored at *t*, what was in it, or what the machine concluded. That is
  §13.1's ConSerts finding — runtime evaluation, thrown away — reappearing in the
  one place a regulator has actually mandated the evaluation.
- **It attributes.** Two parties, two keys, a record neither can rewrite without
  it showing. A scanner's output arrives on the authority of the machine that
  holds it, which is §11's and §16's observation again.
- **It says which claims rest on the perceiver.** In a compliant vehicle every
  safety claim rests on the scanner, and the standards' answer is to **rate the
  scanner** rather than to tag the claim. `reg` can rate nothing, and tags
  instead. That is the whole trade Claim 3 makes, stated by a standard that made
  the other choice.

### What ISO 3691-4 does that `reg` does not

- **Rating, validation and conformance.** Performance levels, verification
  procedures, an assessment somebody signs. This project has none of that and
  [`docs/sufficiency.md`](sufficiency.md) §7 already says it attempts no
  assurance case.
- **It covers the composition.** R15.08 has a category for a machine that
  manipulates while it drives. `reg` has no base at all, and the design document's
  build order (§7 there) puts one four tiers out.
- **Stopping performance as a measured quantity.** The field is sized from a
  measured stopping distance under stated conditions. `reg`'s `Limits` are
  declared with a required `source` and never measured.
- **It governs a real machine on a real floor.** Everything here is a simulator.

**Action:** `docs/mobile-base.md` §2 names the body-frame set as *what a
protective field is*, and carries the rating caveat in the same breath. **Done in
this pass.** The same caveat belongs wherever this project states what it may
claim — [`docs/sufficiency.md`](sufficiency.md) — and that is **not done**,
outside issue #138's affected areas, the same way §11a records the README
standards table.

---

## 23. RTD and REFINE — the answer to an unbounded workspace is a fail-safe manoeuvre, not a refusal

**Kousik, S., Vaskov, S., Bu, F., Johnson-Roberson, M. and Vasudevan, R.,
*"Bridging the Gap Between Safety and Real-Time Performance in Receding-Horizon
Trajectory Design for Mobile Robots,"* International Journal of Robotics Research,
2020 (arXiv:1809.06746)** — **RTD**. And **Liu, Shao, Lymburner, Qin, Kaushik,
Trang, Wang, Ivanović, Tseng and Vasudevan, *"REFINE: Reachability-based
Trajectory Design using Robust Feedback Linearization and Zonotopes"*** — the
full-size-vehicle successor, read from its preprint.

**Read from published preprints. No implementation was run**, and the venue and
year of REFINE are not asserted here because the preprint is what was read.

**This file already has the arm half of this line and not the ground-vehicle
half.** §4 is ARMTD and ARMOUR, from the same group, and it is where Phase 2's
novelty claim was given up. RTD is the sibling that does it for a **nonholonomic
ground robot**, which is the case [`docs/mobile-base.md`](mobile-base.md) §3 is
about. Missing it while citing ARMTD is the shape of omission a reviewer reads as
having found one paper rather than a literature.

**What it is.** Offline, RTD computes a forward reachable set of a
**parameterized family of trajectories** — including the tracking error of the
real system against the model, so the set covers what the machine does and not
what the model does — and represents it as a polynomial level set. Online, it
intersects that set with sensed obstacles to carve away the trajectory parameters
that could collide, and optimizes over what remains. Every plan ends in a
**fail-safe manoeuvre**, verified in the same offline set, so that if no parameter
is safe at the next planning step the previously-verified stop executes. That
construction is what buys the *not-at-fault* guarantee: the robot is never in a
state from which it has no verified action. REFINE replaces the level sets with
zonotope reachability under robust partial feedback linearization and runs it on a
full-size vehicle.

**What it says to `docs/mobile-base.md` §1, which is why this entry is not just
another citation.** That section concludes that `computed_bound` must **refuse**
for a mobile model, because an unbounded workspace is a could-not-evaluate and a
plausible large number is worse than none. That conclusion stands. What the
section does not record is that **the literature has a different answer to the
same fact**, and it is not refusal: it is to stop needing a horizon-free bound at
all, by carrying a verified stopping manoeuvre and re-verifying every step.

`reg` cannot take that answer, and the reason is architectural rather than a
preference. RTD's guarantee lives in a **planner** — the same party that chooses
the trajectory proves the trajectory safe, which is the common-cause structure
[`CLAUDE.md`](../CLAUDE.md) rule 3 exists to refuse. And `reg`'s enforcement layer
VETOes a *declaration*; it commands nothing, and the one thing in the tree that
resembles a fail-safe — passivation — is documented in the README as **not
exercisable**, reaching no table, no edge type and no query. A project that cannot
represent a stop cannot rest a bound on having one. Refusal is right here for
`reg`'s reasons, and saying so is stronger than concluding it as though nothing
else had been tried.

**One thing it confirms.** RTD's set is horizon-limited and computed per planning
step, which is exactly the status `horizon_bound`'s second term has. So §1's
"every VETO rests on the outer envelope's soundness argument" is not a degraded
position — it is the position this literature works from, and the pressure it puts
on `tests/test_envelope.py::test_no_bang_bang_trajectory_escapes_the_outer_envelope`
is real rather than a symptom of having lost something.

### What `reg` does that RTD does not

- **It retains.** The forward reachable set and the safe parameter subset are
  computed each step and discarded. Nothing afterwards says which family was
  verified at *t*, against what, or what was left.
- **It separates the two parties.** RTD's check is inside the planner. `reg`'s
  bound is computed by `reg/enforce.py` from `Limits` and a `ProprioState`, and
  the import boundary that keeps it from reading the policy's own reasoning is
  asserted against the source.
- **It tags the dependence.** RTD's offline set is obstacle-independent — that is
  §4's finding, and it is why the split is not novel — but nothing in what RTD
  leaves behind says which of its conclusions rested on the sensed obstacle set,
  because it leaves nothing behind.

### What RTD does that `reg` does not

- **A sound over-approximation for a nonholonomic system, with tracking error
  inside it.** `reg`'s outer envelope covers a fixed-base arm and models **no**
  tracking error: the controller is assumed to follow the commanded trajectory.
  For a driven base that assumption is the load-bearing one, and this is where the
  literature says so.
- **A fail-safe manoeuvre and a not-at-fault guarantee.** `reg` has no authority
  to stop anything.
- **Real time, online, on hardware.**
- **The machinery.** Polynomial level sets and zonotope arithmetic. `reg` must not
  build it — *no new dependencies* is a standing rule and an HJ solver is a stated
  non-goal in [`plan.md`](plan.md) — so the cost is that the composed bound §3
  proposes is loose, and it must be **published as loose**.

**Action:** `docs/mobile-base.md` §1 records the fail-safe alternative beside its
refusal, and why this project declines it. **Done in this pass.**

---

## 24. CORA and zonotope reachability for nonholonomic vehicles

**Althoff, M., *CORA — COntinuous Reachability Analyzer*** (Technische Universität
München; MATLAB), introduced in the ARCH workshop series (*"An Introduction to
CORA 2015"*). The two techniques the design document leans on: **Althoff,
Stursberg and Buss, *"Reachability Analysis of Nonlinear Systems with Uncertain
Parameters using Conservative Linearization,"* CDC 2008**, and **Kochdumper and
Althoff, *"Sparse Polynomial Zonotopes: A Novel Set Representation for
Reachability Analysis,"* IEEE Transactions on Automatic Control, 2021.** The
closest application to the mobile case is **Althoff and Dolan, *"Online
Verification of Automated Road Vehicles Using Reachability Analysis,"* IEEE
Transactions on Robotics, 2014.**

**Read from published preprints and the tool's documentation. CORA was not run**,
and no figure here is measured.

**What it is.** Set-propagation reachability. A **zonotope** — a centre plus
generator vectors — is closed under Minkowski sum and linear maps at low cost,
which is what makes propagating one through a linear system cheap. Nonlinear
dynamics are handled by linearizing about the current set and adding a
**set-valued abstraction-error term** that over-approximates everything the
linearization dropped; that is what *conservative linearization* names, and it is
what makes a nonlinear model analysable at all. For a unicycle or Dubins model,
uncertainty in heading **curves** the reachable set, and a zonotope — convex, and
centrally symmetric — over-approximates a curved set loosely. **Polynomial**
zonotopes represent the curvature directly and are much tighter. Online
verification (Althoff & Dolan) is the same machinery used as a runtime checker
rather than an offline proof, which is the use closest to this project's.

**What this corrects in [`docs/mobile-base.md`](mobile-base.md) §3.** That
section reads *"CORA's conservative linearization gives a large convex
over-approximation of a Dubins car where polynomial zonotopes capture the
non-convexity"*, which credits the looseness to the wrong mechanism and reads as
though two tools were being named. Conservative linearization is not what makes
the answer convex; the **representation** is, and polynomial zonotopes are the
same tool's other representation. Small, and precisely the class of error this
file exists to catch before it is quoted onward.

**And one thing it adds, which is not a correction.** The construction §3
proposes — a body-frame translation bound over the horizon, **Minkowski-summed**
with the arm's own body-frame outer set — is this literature's primitive. Zonotopes
exist in large part *because* Minkowski sum is exact and cheap on them; on a
`shapely` polygon the same operation is a buffer, and the over-approximation error
it introduces compounds with every step it is applied. So §3's "deliberately
loose" is loose in a way this literature has a name and a cost model for, and the
honest form of publishing it as loose is to say **what** the looseness is: a
representation cost this project pays for not taking a dependency it has already
refused.

### What `reg` does that CORA does not

- **It retains an artifact.** CORA is a library: it computes a set and returns it.
  There is no record, no chain, no query, and nothing months later.
- **It attributes and it tags.** Neither has a counterpart in a reachability
  library, and neither should.
- **It answers a question about a run that happened.** CORA answers a question
  about a model.

### What CORA does that `reg` does not

- **Sound reachability for nonlinear and hybrid systems with uncertain parameters
  and uncertain inputs, in continuous time, with a stated over-approximation
  argument and a decade of benchmarks behind it.** `reg`'s `outer_envelope` is a
  grid over the joint box plus a swept sector per link, with a hand-written
  soundness argument for one class of trajectories and a `MAX_OUTER_GRID_CONFIGS`
  guard that raises a could-not-evaluate when the enumeration gets too big. The
  guard is honest; it is also the price of not having a set representation.
- **Tightness.** Everything above is why the composed base-plus-arm bound will be
  loose, and why *how* loose is not something this project can currently state.
- **A representation that composes.** Minkowski sum, linear maps and intersection,
  in one object, in any dimension.

**Action:** `docs/mobile-base.md` §3's CORA sentence is corrected and the
Minkowski-sum looseness is stated in this literature's terms. **Done in this
pass.** What a tighter construction would buy still belongs in
[`docs/limitations.md`](limitations.md) when the mobile track has code — **not
done**, and outside issue #138's affected areas.

---

## 25. Set-theoretic localization — the one route that could have made the base pose certifiable, and does not

**Jaulin, L., Kieffer, M., Didrit, O. and Walter, É., *Applied Interval
Analysis*, Springer, 2001**; **Kieffer, Jaulin and Walter, *"Guaranteed recursive
nonlinear state bounding using interval analysis,"* International Journal of
Adaptive Control and Signal Processing, 2002**; **Jaulin, *"Robust set-membership
state estimation; application to underwater robotics,"* Automatica, 2009.** The
older set-membership line behind them: **Schweppe (1968)**, and **Milanese and
Vicino** on bounded-error parameter estimation.

**Read from published preprints and textbook summaries.**

**What it is.** Estimation without probability. Given errors that are **bounded**
rather than distributed — this sensor is wrong by at most ±e — the estimator
returns a **set** guaranteed to contain the true state, computed by interval
analysis and constraint propagation (SIVIA, and the contractor line that followed
it). The output is a union of boxes rather than a mean and a covariance, and the
guarantee has a specific form: *the true pose is in this set, or one of the stated
hypotheses is false.* For robot localization the hypotheses are the sensor error
bounds and a map of landmarks. It is robust to outliers in a way a Gaussian filter
is not, because a measurement can be permitted to be wrong q times out of m
without the guarantee collapsing.

**Why it is in this pass at all.** [`docs/mobile-base.md`](mobile-base.md) §2
puts the base pose in Layer B and §2.2 records the dead-reckoning nuance — a
dead-reckoned pose is Layer A *relative to the last known pose*, with an error
that grows without bound under slip, which is "Layer A with a validity horizon"
and not a value this project's binary has. If any estimator could hand back a
room-frame pose with a **characterized** failure mode, that nuance would become a
decision rather than a note. This is the candidate. The pass has to say plainly
whether it works.

**It does not, and the reason generalises past this method.** The guarantee is
conditional on two things: bounded-error hypotheses on the sensors, and a **map**.
Both are exogenous — a model of the world, supplied by somebody, about things that
are not the robot — so both are Layer B under this project's own definition, and a
guarantee conditioned on a Layer B input is a Layer B guarantee. It is stronger
and better-behaved than a probabilistic one, and it is still on the far side of
the boundary.

Which means the conclusion is not *this method is not good enough*. It is that
**no localizer can be**, because a room-frame pose is a statement about the
robot's relationship to things outside it, and the layer boundary is drawn at
exactly that line. The base pose is Layer B **structurally**. `docs/mobile-base.md`
§2 argues it from the safety-rating status of localization sensing — true, and a
weaker argument, because it would be answered by someone building a safety-rated
localizer. The structural argument would not be.

**What it does change, and this is worth recording before Tier 3.** A set-valued
pose composes with §3's construction directly: the room-frame envelope becomes the
body-frame set **Minkowski-summed with the pose set**, rather than rigidly
transformed by a point. That preserves the over-approximation across the frame
change, which a point pose does not — and it is the same primitive §24 says this
whole literature is built on. Today's Layer B tag is binary: it says the answer
inherited the perceiver and says nothing about how wrong the answer can be. A
set-valued pose is the shape in which that magnitude could be carried. Whether the
tag should ever carry one is a types decision (Tier 2), it interacts with issue
#84's deliberate refusal of a graded integrity attribute, and a survey does not
take it.

### What `reg` does that a bounded-error localizer does not

- **It retains, attributes and tags.** An estimator returns a set and moves on;
  nothing afterwards says what set it returned at *t* or under which hypotheses.
- **It records the hypotheses as hypotheses.** The one thing this project is
  actually built to do with a conditional guarantee is keep the condition attached
  to the answer — which is §13.1's *retained conditionality*, the narrowed form of
  the layer-tag contribution.

### What a bounded-error localizer does that `reg` does not

- **It bounds its own error.** Under stated hypotheses it returns a set that
  provably contains the truth. `reg`'s Layer B tag carries no magnitude at all and
  [`docs/limitations.md`](limitations.md) is where that is recorded.
- **It works on exteroceptive data**, which `reg` by construction never holds —
  the envelope takes a `ProprioState` and `tests/test_layer_boundary.py` fails if
  that erodes.
- **It localizes.** *Perception / vision / SLAM* is a binding non-goal in
  [`plan.md`](plan.md), and nothing about this entry proposes changing that.

**Action:** `docs/mobile-base.md` §2 states the pose's Layer B status as
structural rather than estimator-limited, and §2.2 records the set-valued pose as
what this literature would change. **Done in this pass.** The same restatement
belongs in [`docs/sufficiency.md`](sufficiency.md) §5.1 when that document carries
§2.1's shrink of the certifiable question set — **not done**, outside issue #138's
affected areas, and it is Tier 1 of the design document's build order rather than
this issue.

---

## What this pass did not disturb

**§6's hedge stands, and this is the seventh search.** None of the five
retains a graph for post-hoc audit:

| Read | Does it retain a graph for post-hoc audit? |
|---|---|
| Marvel & Bostelman (§21) | No. A standards-gap analysis and a call for test methods; it specifies no artifact. |
| ISO 3691-4 / R15.08 (§22) | No. A protective field is evaluated and discarded continuously; the standards specify performance and rating, not a record. |
| RTD / REFINE (§23) | No. The reachable set and the safe parameter subset are recomputed every planning step and thrown away. |
| CORA (§24) | No. A library that returns sets. |
| Set-theoretic localization (§25) | No. An estimator. |

**No claim in `plan.md` is edited by this pass, and no published figure moves.**
All four claims are fixed-arm claims and the mobile track is exploratory and
unbenchmarked, which [`docs/mobile-base.md`](mobile-base.md) §5 already says of
itself. Claim 3 gains a second standard that made the opposite trade (§22) and no
competitor.

**Two positioning risks are recorded rather than fixed**, per the rule that a
survey does not edit the claims it bears on:

- Any sentence implying that a **horizon-limited region in the vehicle's own
  frame** is this project's construction is leaning on ground ISO 3691-4 and
  R15.08 have occupied since 2020 (§22) — and the word for it carries a rating
  this project cannot claim.
- Any sentence implying that refusal is the *only* principled response to an
  unbounded workspace is leaning on RTD not existing (§23).

## Changes this pass makes to the plan

| # | Change | Where |
|---|---|---|
| 21 | Date-limit the Marvel & Bostelman citation — the unbounded work volume, not "neither standard covers it" — and name R15.08 as where the composition went | `docs/mobile-base.md` §1, §6 (**done**) |
| 22 | Name the body-frame set as *what a protective field is*, with the conformance-rating caveat in the same breath | `docs/mobile-base.md` §2, §6 (**done**) |
| 22a | The same caveat where the project states what it may claim | `docs/sufficiency.md` (**not done** — outside #138) |
| 23 | Record the fail-safe manoeuvre as the literature's alternative to refusal, and why `reg` declines it | `docs/mobile-base.md` §1, §6 (**done**) |
| 24 | Correct what conservative linearization names; state the Minkowski-sum looseness as the representation cost it is | `docs/mobile-base.md` §3, §6 (**done**) |
| 25 | State the base pose's Layer B status as structural rather than estimator-limited; record the set-valued pose | `docs/mobile-base.md` §2, §2.2, §6 (**done**) |
| 25a | The same restatement where the certifiable question set is defined | `docs/sufficiency.md` §5.1 (**not done** — outside #138, and Tier 1 of the design document's build order) |

## Still open after this pass

- **The clause text of ISO 3691-4 and of ANSI/A3 R15.08.** Paywalled, like IEC
  61784-3, IEEE 7001-2021 and ISO 21448. §22 is entered from secondary sources and
  vendor summaries, says so, and cites no clause number for that reason. What a
  full read would most likely change is the type distinctions in R15.08, which the
  next bullet depends on.
- **The full text of Marvel & Bostelman 2013.** The abstract and secondary
  sources are what §21 is written from; the PDF did not extract and obtaining it
  remains outstanding. The date-limit finding is the part a full read would
  sharpen.
- **Whether R15.08's distinction between a platform that may manipulate while
  moving and one that may not changes the composition in
  [`docs/mobile-base.md`](mobile-base.md) §3.** If the two motions never overlap,
  the base bound and the arm bound compose sequentially and the Minkowski sum is
  unnecessarily loose. That is a design decision with a standards precedent behind
  it and it is not taken here.
- **How loose the composed bound actually is.** §24 says the looseness is a
  representation cost with a cost model in the literature; nobody has computed it
  for this construction, and until somebody does, "deliberately loose" is a
  statement of intent rather than a number.
- **Whether the Layer B tag ever carries a magnitude.** §25 says a set-valued pose
  is the shape one would take. It collides with issue #84's deliberate refusal of a
  graded scheme, it is a types decision rather than a survey one, and it should be
  decided in the same change as the pose provenance enum or not at all.

---

# Sixth pass — 2026-09-05, before the self-describing artifact is built

[`docs/self-describing.md`](self-describing.md) was written on 2026-09-05. It
proposes recording the toolchain that produced an artifact and putting a tag's
basis in the file beside the tag, and it ends its own rationale with an
instruction: *"Before this is built, `prior-art.md` needs a pass on provenance and
reproducible-build practice, and on whether 'self-describing evidence' has a name
in the audit literature already. **Assume it does.**"* The assumption was right on
all four counts, and one of the four names a defect in the sentence that ordered
the pass.

Tier 1 of that document's build order **is** this pass, and everything below it in
the order depends on the outcome, per the rule at the head of this file: prior art
wins and the plan gets edited.

What the pass costs, up front:

- **§26 corrects the sentence in `self-describing.md` that cites it.** The
  document says SLSA and in-toto attestations *"do exactly this"* — record the
  toolchain that produced an artifact. They do not. SLSA's provenance identifies
  the **build platform** and requires the verifier to *trust* it; the fields that
  could carry an environment are optional, best-effort and offered for debugging.
  The statement shape is worth borrowing and this repository already borrows it.
  The environment record is somebody else's contribution, and §27 is whose.
- **§27 is the entry the issue predicted: gap 2 is solved practice, and it has a
  file format.** Reproducible Builds defines reproducibility *relative to a stated
  build environment* and records that environment in a **buildinfo** —
  deliberately as a separate product **beside** the artifact rather than inside
  it. So the content of `self-describing.md` §3's first row is settled by prior art
  and should be adopted rather than derived; its placement inside `meta` is a
  deviation made for a reason the practice does not have, and must be stated as
  one on §5's pattern. Two things arrive free: `diffoscope`, which is what makes a
  mismatch *attributable* rather than merely visible, and `reprotest`, which says
  that CI comparing two runs on one machine is the weakest test in the family.
- **§28 supplies the shipped precedent for the environment field, one layer up.**
  C2PA's `claim_generator_info` records the name, version **and operating system**
  of the software that produced a claim, inside a manifest bound to the asset's
  bytes by hash. It also has a defined way to remove part of a record without
  breaking the signature — redaction — which is a different answer from this
  project's to the same question, and the one that does not route back through
  gap 2.
- **§29 is the one that changes what the design document may say.** The idea of an
  artifact carrying what it needs in order to be interpreted has a name — OAIS
  **Representation Information** — and the model that names it also shows the goal
  is unreachable as stated: Representation Information is recursive, and the
  recursion terminates only at a **declared Designated Community**. So §4's line
  cannot be drawn as *in the file* versus *in prose*; it is drawn by naming the
  reader, which this survey already did in §12. The audit and legal literature's
  other name is **self-authenticating**, and its answer is the opposite of
  self-describing: FRE 902(14) accepts a hash-identified copy only when a
  **qualified person certifies** it.

What survives, as in every pass since the third, is **retention** and
**attribution** — and this is the first pass in which the second is contested.
in-toto, C2PA and FRE 902 are all attribution mechanisms, and two of the three
have a signing story stronger than this project's. All four bodies of work are
about evidence rather than about robots, and none of them is a competitor to
Claim 1 or Claim 4.

**A note on sources before the entries, because all four have a boundary.** §26,
§27 and §28 are read from the specifications' own published text on 2026-09-05 —
the in-toto Statement v1 spec, the SLSA v1.0 provenance, levels and FAQ pages, the
Reproducible Builds documentation, and the C2PA 2.1 specification — and **no
implementation was run**: no attestation was generated or verified, no build was
rebuilt, no manifest was validated. §29 carries the real boundary: **ISO 14721 is
paywalled**, the free CCSDS Magenta Book was fetched and its PDF is encrypted
against text extraction and **did not extract** here, so its half of that entry is
entered from secondary sources with **no clause number cited anywhere in it**.
Each entry repeats this in its own first lines, because a reader who reaches one
entry does not necessarily read this paragraph.

---

## 26. in-toto and SLSA — the attestation shape this repository already uses, and the environment it does not carry

**The in-toto Attestation Framework, *Statement* v1**, over the framework
introduced in Torres-Arias, S., Awwad, H., Moore, R., Cappos, J. and Curtmola, R.,
*"in-toto: Providing farm-to-table guarantees for bits and bytes,"* USENIX
Security 2019. Beside it **SLSA** (Supply-chain Levels for Software Artifacts)
**v1.0**, its Provenance predicate and its build track.

**Read from the published specification text on 2026-09-05** — the in-toto
Statement v1 spec and the SLSA v1.0 provenance, levels and FAQ pages. **No
implementation was run**; nothing here generated or verified an attestation, and
nothing below is a quotation from the USENIX paper, which was not opened.

**What it is.** An in-toto Statement is four fields: `_type`, pinned to
`https://in-toto.io/Statement/v1`; `subject`, a set of artifacts of which each
*"MUST have `digest` set"* and which are *"matched purely by digest, regardless of
content type"*; `predicateType`, a URI naming what kind of claim this is; and
`predicate`, the claim itself. The Statement is signed in an envelope, and the
predicate is where an ecosystem of claim types lives. SLSA's Provenance is one of
them: a `buildDefinition` (`buildType`, `externalParameters`, optional
`internalParameters`, optional `resolvedDependencies`) and `runDetails` (`builder`,
optional `metadata`, optional `byproducts`).

**This repository is already inside that shape and had not surveyed it.** The
`.wake` records the harness writes onto each branch are in-toto Statements with a
harness-defined `predicateType` — a subject with a digest, a predicate with the
attempt. What those records hold is
[`wake-runner`](https://github.com/nan-bit/wake-runner)'s to document and this
file will not restate it. What matters here is the order: the borrowing happened
before the survey, which is the thing this file exists to prevent.

**The finding, and it corrects the document that ordered this pass.**
[`docs/self-describing.md`](self-describing.md) says *"Recording the toolchain that
produced an artifact is ordinary build provenance — SLSA and in-toto attestations
do exactly this."* The first half is right. The second is not. SLSA Build L1
requires *"Provenance exists describing how the artifact was built, including the
build platform, build process, and top-level inputs"* — the build platform
**identified**, not described. The fields that could carry an environment are all
optional and all hedged: `internalParameters` are *"set internally by the
platform"*, *"there is no need to verify these parameters because the build
platform is already trusted"*, they are offered *"for debugging, incident
response, and vulnerability management"*, and they merely *"MAY be necessary for
reproducing the build"*; `resolvedDependencies` is an *"unordered collection of
artifacts needed at build time"* whose *"completeness is best effort, at least
through SLSA Build L3"*. No build level requires a hermetic or a reproducible
build, and the FAQ is explicit that *"SLSA does not require verified reproducible
builds directly"* — they are *"one option for implementing the requirements"*,
declined as a requirement partly because rebuilders sharing a pipeline share a
common cause, which is `CLAUDE.md`'s third rule arriving from the other direction.

So this literature's answer to *whom do I believe about this artifact* is a signed
identity, and its answer to *what would reproduce it* is: ask the builder. That is
a different question from gap 2's, and an artifact that recorded `builder.id` and
nothing else would leave an auditor exactly where [`limitations.md`](limitations.md)
§1 leaves them.

### What `reg` does that in-toto does not

- **It is about a run, not a build.** Every predicate in this ecosystem describes
  how bytes were produced from other bytes by a build system. `reg`'s subject is a
  robot's own state and what was declared against it, and every question Claim 2
  answers is a question about what a record *says*.
- **It recomputes rather than attests.** `reg/enforce.py` computes its own bound
  and refuses to import the policy's; an attestation verifier checks a signature
  and a digest and takes the predicate's word for its contents. Nothing in the
  shape can disagree with the claim it carries.
- **It tags dependence.** Layer A / Layer B has no counterpart. A predicate field
  is trusted or absent; it is never marked *this one came from outside the robot*.

### What in-toto does that `reg` does not

- **It separates the claim from the artifact and matches by digest.** A `reg`
  artifact carries its chain inside the file the chain protects. An attestation is
  a detached, independently distributable statement about a digest, which is what
  lets a third party hold and serve it — the property §18 found in transparency
  logs, here without the log.
- **It has a policy language and a threshold of signers.** in-toto's layout names
  the steps of a supply chain, who may perform each and how many must agree, and
  verification is against that layout. `reg` has two keys in one process (§14,
  [`limitations.md`](limitations.md) §6) and no notion of a party who was
  *supposed* to sign.
- **It versions its own schema in the file.** `_type` and `predicateType` are URIs
  a reader resolves. `reg`'s `meta` carries `reg_version`, and a reader who does
  not already know the project cannot resolve it to anything.

**Verdict — it corrects [`self-describing.md`](self-describing.md) and supersedes
none of it.** The sentence attributing the environment record to SLSA and in-toto
is wrong and is edited in this pass: what this literature gives is the *statement
shape*, which the repository already uses. §3's first row stands unchanged as a
design; its precedent moves to §27. §7's third question — `meta` or the chain? —
gains a precedent rather than an answer: here the environment-adjacent fields live
inside a **signed** predicate bound to a subject digest, which is the "stronger and
larger" option that question names, and choosing it is still a person's decision.

**Action:** [`docs/self-describing.md`](self-describing.md)'s *What this borrows*
paragraph is corrected and §7's third question gains the precedent — **done in
this pass**. Nothing in `plan.md` moves.

---

## 27. Reproducible Builds — gap 2, solved by someone else, with a name and a file format

**The Reproducible Builds project** — its definition, its documentation on
recording and on defining a build environment, the `SOURCE_DATE_EPOCH`
specification, `reprotest` and `diffoscope`.

**Read from the project's own documentation on 2026-09-05**
(`reproducible-builds.org/docs/`: *Definitions*, *Recording the build
environment*, *Definition strategies*, and the documentation index). **No build
was rebuilt and neither tool was run here**; nothing below is a quotation from a
Debian `.buildinfo`.

**The definition, and it is the whole finding.** *"A build is reproducible if
given the same source code, build environment and build instructions, any party
can recreate bit-by-bit identical copies of all specified artifacts."*
Reproducibility is defined **relative to a stated environment** — not as a property
an artifact has by itself. Which means [`limitations.md`](limitations.md) §1 and
issue #175 are not a discovery about this project; they are the first thing this
field says. *"Relevant attributes of the build environment would usually include
dependencies and their versions, build configuration flags and environment
variables as far as they are used by the build system (eg. the locale)"* — and the
advice is to **minimise** that set rather than to enumerate the world.

**The mechanism has a name and a shape.** *"All relevant information about the
build environment should either be defined as part of the development process or
recorded during the build process."* Recorded, it *"is stored best as a separate
build product that can be easily ignored or distributed separately"* — the
**buildinfo**: plain text in Debian, key–value pairs in Arch, one form per
ecosystem. Two tools sit either side of it. `reprotest` builds twice while
**deliberately varying** the environment — the project's own list of variations
runs to build path, hostname, timezone, locale, umask, input and output ordering,
randomness and system image. `diffoscope` recursively diffs two artifacts and says
**where** they differ.

**Three things this settles for `self-describing.md`, and one is a correction to
the placement rather than to the content.**

**1. Gap 2 is solved practice, and the content should be adopted rather than
derived.** §3's first row — shapely and GEOS versions, platform, Python — is a
buildinfo for a geometry computation. Adopt the list, name the practice, and cite
it; a list arrived at from first principles here would be the same list with no
provenance and no community maintaining it.

**2. The practice puts it beside the artifact and `reg` will not — a deviation to
state, not an oversight to fix.** A buildinfo is *a separate build product*,
because an archive can distribute it separately to whoever wants to rebuild. Claim
2 says the file answers with no access to anything else, so this project has a
reason to put the environment **inside** `meta` that the practice does not have.
That is the shape of §5's PROFIsafe deviation — a deliberate departure, stated
precisely, with its reason — and left unstated it reads as unfamiliarity.

**3. Attribution needs a differ, and a version list does not give one.**
`diffoscope` exists because knowing that two environments differ does not say
*which* difference moved the bytes. The tier-2 guard `self-describing.md` proposes
— report could-not-evaluate when the recording environment does not match the
recomputing one — is the right first move and it is the weaker half: it converts an
unattributable disagreement into a refusal to evaluate, which is what this
repository's *a check must be able to fail* demands, and it still does not tell an
auditor which library moved. Say that, rather than letting *attributable* stand
unqualified.

### What `reg` does that the Reproducible Builds project does not

- **It carries an adversary.** Reproducibility defends against a compromised
  builder and is checked by independent rebuilders comparing bytes; the artifact
  itself is not signed by two parties with different roles, and nothing in it is
  designed to survive its author. `reg`'s chain is (§14, §18).
- **Its subject is a run, and its "source" is a row.** A rebuild starts from a
  source tree. A `reg` recomputation starts from one retained row of
  proprioceptive state and four numbers in `meta` — a far smaller input, and a
  correspondingly stronger claim about what was retained.
- **It tags the dependence of what it recomputes.** Layer A / Layer B again; a
  buildinfo has no notion of a value that came from outside the machine.

### What the Reproducible Builds project does that `reg` does not

- **It states the environment.** This is gap 2, and it is why the entry exists. An
  artifact this repository writes today records `reg_version` and an
  envelope-parameter digest, and neither the shapely/GEOS build nor the platform.
- **It varies the environment on purpose.** `reprotest` is an entire tool for
  *discovering* unreproducibility rather than assuming it away. CI here compares
  two runs on **one machine**, which in that vocabulary is a reproduction with **no
  variations applied** — the weakest member of the family — and issue #175 found
  the architecture variation by hand rather than by running one.
- **It explains a mismatch.** `diffoscope` has no analogue here, and building one
  is not proposed.
- **It has independent rebuilders.** The property is checked by parties who are not
  the builder. Every recomputation of a `reg` artifact contemplated so far is by
  one auditor, holding the file, alone.

**Verdict — it supersedes the *derive it* half of
[`self-describing.md`](self-describing.md) §3's first row and corrects §6's
attribution; the three gaps stand as stated.** Gap 2 is correct, and it is a known
problem with a known answer. The document should adopt the buildinfo content list,
name the practice, state the in-`meta` placement as a deviation with its reason,
and qualify *attributable*.

**Action:** [`docs/self-describing.md`](self-describing.md) §3 gains the deviation
and the qualification, and §6 records the outcome — **done in this pass**. Adopting
the field list is tier 2, which is code and a schema bump and **not done** here.
The CI-variation finding belongs in [`limitations.md`](limitations.md) §1 and is
**not done** — outside issue #199's affected areas.

---

## 28. C2PA — a claim bound to the bytes it describes, and the software version already inside it

**The Coalition for Content Provenance and Authenticity, *C2PA Specification*,
version 2.1**, and the manifest model underneath it.

**Read from the published 2.1 specification text on 2026-09-05.** **No manifest
was generated or validated here** and no implementation was run; nothing below is
a quotation from a conformance-program document, which was not opened.

**What it is.** A **manifest** is *"the set of information about the provenance of
an asset based on the combination of one or more assertions (including content
bindings), a single claim, and a claim signature."* Assertions are individual
statements — what was captured, what was edited, what the ingredients were. The
claim references them and is signed. Manifests travel **embedded in the asset**, in
a JUMBF box, and may also be external and referenced. Ingredients make the manifest
store a chain: an asset built from other assets carries theirs.

**Two bindings, and the distinction is the useful one.** A **hard binding** is a
cryptographic hash over the asset's bytes, which lets a validator *"ensure that (a)
this manifest belongs with this asset and (b) that the asset has not been
modified."* A **soft binding** — a fingerprint or a watermark — matches *"derived
assets and asset renditions"* whose bits differ, which is what is left when the
manifest has been stripped.

**The field `self-describing.md` §3 proposes already exists in a shipped
standard.** `claim_generator_info` records *"the non-human (hardware or software)
actor that actually generated the claim"* — name, version, **operating system**. A
content-provenance standard concluded that the software and the OS which produced
a claim belong inside the claim. That is §3's first row one layer up, and it is
the strongest available answer to *is putting the environment in the file
unusual?* It is not.

**Redaction, which is a different answer to this project's hardest retention
question.** C2PA permits an assertion to be removed when an asset becomes an
ingredient — *"removing the entire assertion from the manifest's assertion store or
retaining the labelled assertion container but replacing its data with zeros"* —
with the claim still validating. [`lossiness.md`](lossiness.md)'s argument for
discarding a polygon is that it is recomputable, and gap 2 is the price of that
argument. Redaction pays a different price: the removed thing is **gone**, the
record says so, and nothing about the reader's environment is involved. Which of
the two this project wants is not settled by this entry. That the alternative
exists, is standardised, and does not route back through gap 2 is what §3's third
row does not currently know.

**The disclaimer to copy.** The specification says of its own conformance that it
*"SHOULD NOT provide value judgments about whether a given set of provenance data
is 'good' or 'bad,' merely whether the assertions included within can be validated
as associated with the underlying asset, correctly formed, and free from
tampering."* That is §12's *no compliance claim may be made*, written by a
standards body about itself, and it is the sentence a `reg` artifact's reader
documentation should be modelled on.

### What `reg` does that C2PA does not

- **It disagrees with a claim.** Validation there is about binding, form and
  tampering, and explicitly not about whether an assertion is true. `reg/enforce.py`
  recomputes the bound and can VETO the declaration — a check on the substance,
  which this standard deliberately declines to make.
- **It answers questions the record was not written to answer.** A manifest is read
  as a manifest; Claim 2's queries run over a graph of runs, and the artifact is a
  database.
- **It tags dependence.** Layer A / Layer B. An assertion is signed or absent;
  there is no third state saying *this came from outside*.

### What C2PA does that `reg` does not

- **It binds the record to the bytes it describes.** The hard binding is over the
  asset. A `reg` artifact's chain is over its own records, inside the file, and
  nothing in it says *these are the observations this evidence is about* in a form
  that would survive the two being separated.
- **It plans for separation.** Soft bindings exist because metadata gets stripped
  in the world. Nothing in this project has considered what an artifact means when
  it arrives without its `meta`.
- **It has a trust model with a list.** A validator decides *which signer to
  accept* against a published trust list. `reg` hands the auditor the keyring, and
  §14's asymmetry is the whole story.
- **It removes without breaking.** Redaction, above.

**Verdict — it corrects [`self-describing.md`](self-describing.md) §4's statement
of the line and leaves the rest standing.** §4 draws the line between *in the file*
and *in prose*. C2PA's line is between what is **bound to the artifact** and what
is ambient: a manifest that is external and referenced is self-describing in every
sense §4 wants, provided the binding holds. The three gaps stand; §3's first row
gains a precedent; §3's third row gains an alternative it did not consider.

**Action:** [`docs/self-describing.md`](self-describing.md) §3 records the
alternative — **done in this pass**. The restatement of §4's line is folded into
§29's, which is the sharper version of the same correction.

---

## 29. OAIS Representation Information, and "self-authenticating" — the idea has two names and they disagree

**OAIS — the *Reference Model for an Open Archival Information System*, CCSDS
650.0-M-2 / ISO 14721:2012, third edition CCSDS 650.0-M-3 / ISO 14721:2025.**
Beside it, from an entirely different literature, **Federal Rules of Evidence
902(13) and 902(14)**, the 2017 amendments on **self-authenticating** electronic
records. And, as the working instances of the idea, the packaging conventions that
call themselves self-describing: **BagIt** (RFC 8493) and **RO-Crate**.

**Boundary, and it is the largest in this pass. ISO 14721 is paywalled**, and the
free CCSDS Magenta Book was fetched on 2026-09-05 and is an encrypted PDF that
**did not extract** in this environment. The OAIS half of this entry is therefore
**entered from secondary sources** — the DPC and OCLC literature and the model's
published summaries — and **cites no clause number anywhere**, for the reason §22
gives: a clause number is exactly what a summary cannot support. The FRE half is
read from the rule text and its Committee Notes. Nothing below is a quotation from
the Magenta Book.

**The question this entry was asked.** [`docs/self-describing.md`](self-describing.md)
§4 draws a line between what an artifact must carry and what may stay in prose,
and the issue that ordered this pass asked whether *an artifact that carries what
it needs in order to be interpreted* has a name. It does — and the name arrives
with a demonstration that the goal is unreachable as §4 states it.

**Representation Information.** In OAIS an archived object is a Data Object plus
the **Representation Information** needed to render and understand its bits, split
into **Structure Information** — the format: how bits become characters, numbers,
arrays, tables — and **Semantic Information** — what those values mean: a data
dictionary, a glossary, the documentation. Structure is aimed at machines and
semantics at people. Around it sits **Preservation Description Information** in
five parts: Reference, Provenance, Context, Fixity and Access Rights.

**The recursion, which is the finding.** Representation Information is itself
information, so it needs Representation Information: a schema needs its schema
language, which needs its own specification, and the regress can continue for an
arbitrary number of steps. It terminates in exactly one place — the **Designated
Community's Knowledge Base**. The archive *declares* who its consumers are and
stops adding where their assumed knowledge takes over. The broader the designated
community, the less may be assumed and the more must be carried.

**Which means §4's line is not the line.** *In the file* versus *in prose* is not a
boundary that can be drawn on its own terms: there is no quantity of material that
makes an artifact self-interpreting to a reader nobody has named, and there is a
small quantity that suffices for a reader who has been. This survey already named
that reader — §12, IEEE 7001's **incident and accident investigator**, one of the
five stakeholder groups, and the one this project addresses. So the defensible
statement of §4 is *what a claim depends on, and what would reproduce it, for an
investigator holding the file*, and the stopping point is a declaration that can be
argued with. §2's cold read already contains that declaration and hides it: *"the
code that reads artifacts and no document"* **is** a knowledge base, asserted in
passing. Stating it as one is the change.

**And the practice does not put it all in the package.** Representation
Information may be held in a **Representation Information Registry** — PRONOM is
the working example, a registry of formats and of the software and hardware
environments needed to support them — and referenced from the object. What the
model requires is that the Representation Information be identified, retained and
itself preserved, not that it live inside the bag; BagIt and RO-Crate are the two
packaging conventions built on that reading, and RO-Crate delegates checksums to
BagIt precisely so that the metadata and the fixity live in different files. Which
is §28's binding distinction reached from the archival side: `docs/` is not
disqualified by being prose. It is disqualified by being **unversioned, unhashed
and unreferenced from the artifact** — a smaller and more fixable defect than
"move it into the file".

**The other name, and it says the opposite.** In the law of evidence the term of
art is **self-authenticating**. FRE 902(13) admits *"a record generated by an
electronic process or system that produces an accurate result, as shown by a
certification of a qualified person"*; 902(14) admits *"data copied from an
electronic device, storage medium, or file, if authenticated by a process of
digital identification, as shown by a certification of a qualified person"* — and
the Committee Notes make that process of digital identification a **hash
comparison**. So the closest thing this literature has to an artifact that
authenticates itself is a hash **plus a human certification**: the hash is
necessary and explicitly not sufficient. A `reg` artifact supplies the digital
identification and has no field for a certifier — and §14's asymmetry means the
certifier would be the operator, which is exactly what a 902 certification is, and
why the rule attaches a person's name to a penalty rather than a signature to a
key.

### What `reg` does that OAIS does not

- **It is executable and it can fail.** OAIS is a reference model: functional
  entities and information objects, no format, no bytes, no test. `reg` is a
  schema, a reader and a suite that goes red.
- **It has an adversary.** Fixity there is against corruption and error, and the
  archive is trusted and audited separately (ISO 16363). `reg`'s chain is against
  an author who would prefer the record said something else, and the two-key split
  exists for that.
- **It generates its evidence from the system under scrutiny, at run time.** An
  archive receives finished objects from a producer. This pipeline has no
  producer/archive boundary at all, which is why Provenance in the PDI sense is
  thin here and why Layer A / Layer B is doing a job OAIS has no name for.

### What OAIS does that `reg` does not

- **It requires the reader to be declared.** Designated Community is a first-class,
  mandatory concept, and every judgement about sufficiency is relative to it. `reg`
  has an implied reader in four documents and names it nowhere the artifact can
  see.
- **It has a place to put the interpretation.** Representation Information,
  structure and semantics, with a registry pattern for sharing it. The equivalent
  here is a `docs/` tree that no artifact references and no version pins.
- **It carries Context and Access Rights.** Two of the five PDI components have no
  counterpart: nothing in an artifact says what wider programme a run belongs to,
  and nothing says who may see it — [`retention.md`](retention.md) discusses
  disclosure as prose.
- **It certifies the custodian.** ISO 16363 audits the repository, not the object.
  `reg` has no custodian model, which is the same hole FRE 902 fills with a
  qualified person.

**Verdict — it supersedes [`self-describing.md`](self-describing.md) §4's statement
of the line, corrects §2's framing, and leaves the three gaps and the build order
standing.** *Self-describing* is a real idea with an older name, and the name comes
with two conditions the design document does not state: the reader must be
declared, and the interpretation must be identified and retained rather than
necessarily inlined. Neither weakens the case for tier 2 — an environment record is
Representation Information on any reading, and gap 2 is precisely the case where
the investigator's knowledge base cannot cover the difference.

**Action:** [`docs/self-describing.md`](self-describing.md) §4 gains the Designated
Community statement and §2's cold read is marked as the stopping-point declaration
it is — **done in this pass**. Naming that reader where the project says what it
may claim belongs in [`docs/sufficiency.md`](sufficiency.md) and is **not done** —
outside issue #199's affected areas.

---

## What this pass did not disturb

**§6's hedge stands, and this is the eighth search — but this is the first pass
that found something retaining a provenance graph, and the table says so rather
than eliding it:**

| Read | Does it retain a graph for post-hoc audit? |
|---|---|
| in-toto / SLSA (§26) | No. A signed statement about one subject digest. Attestations accumulate along a supply chain, and nothing in the framework walks them as a graph afterwards. |
| Reproducible Builds (§27) | No. A buildinfo is a flat record of one build, distributed beside the artifact. |
| C2PA (§28) | **Partly, and it is the closest thing eight searches have turned up.** A manifest store chains ingredient manifests, travels with the asset, is hash-bound, and is meant to be read later by someone deciding whether to believe the asset. It is a graph of *asset derivation*, not of a system's evaluations of its own state; nothing in it is recomputable and nothing in it is tagged for dependence. §6's sentence is about **scene graphs** and survives unedited — but the broader claim *nobody retains a provenance graph* was never this file's, and this entry is why it must not become one. |
| OAIS (§29) | Not in this sense. A reference model, whose Information Packages are archived objects rather than a queryable record of runs. |

**No claim in `plan.md` is edited by this pass, and no published figure moves.**
All four bodies of work are about evidence rather than about robots. Claims 2 and 3
gain a vocabulary — Representation Information, Designated Community, buildinfo,
hard binding, self-authenticating — and no competitor.

**Three positioning risks are recorded rather than fixed**, per the rule that a
survey does not edit the claims it bears on:

- Any sentence implying that recording the environment **inside** the artifact is
  this project's idea is leaning on C2PA's `claim_generator_info` not existing
  (§28) and on the buildinfo not existing (§27).
- Any sentence calling a `reg` artifact **self-describing** without naming its
  reader is using a term whose own literature makes it relative to a declared
  community (§29).
- Any sentence calling a recomputation **attributable** once the environment is
  recorded is claiming what `diffoscope` exists because a version list does not
  give (§27).

## Changes this pass makes to the plan

| # | Change | Where |
|---|---|---|
| 26 | Correct *"SLSA and in-toto attestations do exactly this"* — that literature gives the statement shape, not the environment | `docs/self-describing.md` §6 (**done**) |
| 26a | Record that the signed-predicate placement is this literature's, where the open question is asked | `docs/self-describing.md` §7 (**done**) |
| 27 | Name Reproducible Builds as the precedent for gap 2 and adopt the buildinfo content list rather than deriving one | `docs/self-describing.md` §6 (**done**); the field list is tier 2 (**not done** — code and schema, outside #199) |
| 27a | State the in-`meta` placement as a deviation from the buildinfo practice, with Claim 2 as its reason, on §5's pattern; qualify *attributable* | `docs/self-describing.md` §3 (**done**) |
| 27b | Record that CI's two runs are a reproduction with no variations applied, and that #175's variation was found by hand | `docs/limitations.md` §1 (**not done** — outside #199) |
| 28 | Record redaction as the standardised alternative to recompute-and-see, which does not route through gap 2 | `docs/self-describing.md` §3 (**done**) |
| 29 | Restate §4's line as a function of a declared Designated Community, and mark §2's cold read as the declaration it already is | `docs/self-describing.md` §2, §4 (**done**) |
| 29a | The same restatement where the project says what it may claim and for whom | `docs/sufficiency.md` (**not done** — outside #199) |

## Still open after this pass

- **The clause text of ISO 14721.** Paywalled in its ISO edition, like IEC 61784-3,
  IEEE 7001-2021, ISO 21448 and both standards in §22; the free CCSDS Magenta Book
  is an encrypted PDF that did not extract here. §29 is entered from secondary
  sources, says so, and cites no clause number for that reason. Obtaining a copy
  that extracts is outstanding, and what a full read would most likely sharpen is
  the exact wording on where Representation Information may be held — which §29's
  correction to §4 leans on.
- **The in-toto USENIX Security 2019 paper.** §26 is written from the
  specification, which is the part the design depends on; the paper was not opened
  and obtaining it is outstanding. The layout-and-threshold comparison is what it
  would sharpen.
- **Whether a `reg` artifact should carry a certifier at all.** FRE 902(13)–(14)
  admit a hash-identified record on a **qualified person's certification**, and
  this project has been designing as though the file could stand without one. It
  collides with §14's asymmetry and with [`limitations.md`](limitations.md) §6, it
  is a claim about who is accountable rather than about bytes, and it is a person's
  decision.
- **Whether redaction or recomputation is the right answer for a discarded
  polygon.** §28 supplies the alternative; choosing costs bytes either way and
  moves the published retention figures, which is the class of decision tier 5 of
  the design document's build order already reserves for a person.
- **Whether the environment record is descriptive in `meta` or signed into the
  chain.** §26 supplies the precedent — this literature signs it —
  and [`self-describing.md`](self-describing.md) §7's third question is still where
  it gets decided.
