# Prior art — what exists, what this borrows, what it must not claim

**Status:** first pass, 2026-08-18 · run before Phase 1, as `plan.md` requires

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

> Automated driving has a mandated evidence recorder. Robotics has none — and the
> DSSAD event vocabulary does not transfer, because it records *transitions of
> authority between human and system*, which is not the failure mode of an
> autonomous manipulator working near a person.

**Action:** add DSSAD to the standards table in `plan.md`; rewrite "the gap this
addresses" around it. Also check before writing the site piece whether the
mid-2026 target slipped, since the plan quotes several dates.

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
  right framing for Claim 3's sufficiency boundary; not yet read.
- **Control barrier functions** as an alternative envelope representation. Noted in
  the plan as a tradeoff to consider; not investigated, and not needed unless the
  sampling envelope proves inadequate.
- **Whether DSSAD's mid-2026 completion target held.** Affects a date in the site
  piece, nothing in the code.

---

# Second pass — 2026-08-19, after Claim 1 was measured and failed

The first pass ran before any code existed. This one ran after the benchmark
refuted the compression claim, and it was aimed at one question: **was the claim
wrong, or was the measurement testing the wrong thing?** Both, in different
proportions.

## 8. Time-series compression is the baseline `reg` was actually competing with

`reg.bench` compares the SQLite artifact against a **gzipped nine-float CSV**.
That is not a naive baseline — it is close to the state of the art for this data
shape. Facebook's **Gorilla** (VLDB 2015) compresses a 16-byte `(timestamp,
value)` pair to **1.37 bytes per point** in production, via delta-of-delta
timestamps and XOR'd values; 96% of timestamps compress to a single bit.
VictoriaMetrics and RedisTimeSeries report the same order.

Gzip on columnar floats gets within reach of that (~21 B/frame for nine values,
so ~2.3 B/value). So the measured comparison was **a relational store with
B-tree indexes and 64-character content hashes against a purpose-built float
codec, at storing floats.** `reg` does not store floats; it stores relationships,
verdicts and provenance. Losing that comparison is not evidence about the thesis.

**Action taken:** Claim 1 in `plan.md` is restated around an absolute retention
rate (51.5 MB/hour, measured) plus a resolution curve, rather than a ratio
against a stream this project was never proposing to replace byte-for-byte.

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
