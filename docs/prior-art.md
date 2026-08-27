# Prior art — what exists, what this borrows, what it must not claim

**Status:** **normative** where it disagrees with [`plan.md`](plan.md) — prior art
wins and `plan.md` gets edited, which is the README's stated rule and this file's
whole purpose · **four passes**: 2026-08-18 before Phase 1, 2026-08-19 after the
benchmark appeared to refute Claim 1, and 2026-08-21 and 2026-08-26 each prompted
by an outside reader · keep current

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
