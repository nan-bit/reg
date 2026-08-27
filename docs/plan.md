# Reachability Evidence Graph — prototype plan

**Status:** the source document for `reg`, and the source of every figure the
README publishes · captured 2026-08-18 and amended in place since, each
substantive change carrying its own date and issue number where it sits ·
reconciled against [`prior-art.md`](prior-art.md) through its four passes, except
for the **seven** items named below · keep current

Where this file and [`docs/prior-art.md`](prior-art.md) disagree, **prior art
wins and this file gets edited**, and phases are cut when research shows they
reinvent something with a name. That rule has not changed; what has changed is
that it has been exercised four times, and most of what those passes ordered into
this file is now in it — DSSAD and EU AI Act Art. 12 in the standards baseline;
Simplex / ASTM F3269 named for what Phase 4 already was, and ARMTD / ARMOUR for
the envelope machinery, with the novelty claim they take dropped; Claim 1
restated as a retention rate and Claim 2 as answer-agreement; Schneier–Kelsey
cited where Phase 6 introduces the chain (issue #104); ConSerts where Claim 3
states its contribution; rosbag2/MCAP priced against Claim 1's baseline (issue
#117). So this is not a brainstorm and has not been one since the first pass ran.
It is still not a *specification*: nothing here is normative over `prior-art.md`,
and a phase that has not been built says so in its own section.

**What is unreconciled is these seven, and nothing else is meant by the word.**
Each is a change a pass ordered into *this* file, and this file has not made:

| From | Ordered here | Not done |
|---|---|---|
| §1 | Rewrite *The gap this addresses* around DSSAD, in the mandate-versus-proposal form | The section still ends on "the unoccupied space"; the distinction reached the standards table and not the argument |
| §5 | Deviation 1: PROFIsafe's CRC seed is the **Codename**, a configured per-device value | It still reads "a known value", which is the looser claim §5 corrected |
| §6 | Align Phase 5's naming with Hydra / Kimera | Phase 5 names neither |
| §11 | Cite the ethical black box in Phase 10 as the proposal this project is an instance of | Cited in `README.md`, not here |
| §12 | Add IEEE 7001-2021 to the standards baseline, claiming no investigator level | Absent here, and everywhere else in the repository |
| §17 | Cite SOTER beside Phase 4's Simplex / F3269 citation | Absent |
| §19 | Adopt ISO 21448 (SOTIF)'s vocabulary where Claim 3 is written in longhand | Absent |

That table is a check, not a note: `tests/test_doc_status_headers.py` fails if an
item listed here has since landed in the body, and fails if one is dropped from
the list while still missing from it.

---

## What this is

A prototype demonstrating a **retainable evidence artifact** for robot autonomy.
Two halves:

1. A temporal scene graph that answers post-hoc audit questions without replaying
   raw sensor logs
2. A declaration-and-attestation protocol between an unbounded policy and a
   bounded enforcement layer, with a tamper-evident record of every exchange

**The demo sentence — everything serves this:**

> The model declared it would stay inside this bound. Here is where it tried to
> exceed it. Here is what the enforcement layer did. Here is the signature chain
> proving neither side rewrote the record.

**The thesis:** safety work tells you a robot probably won't hurt anyone.
Evidence tells you what happened when it did. Almost all robot safety research is
runtime; very little addresses reconstruction months later. Full sensor logs from
a humanoid are terabytes/day, against a retention floor of six months — 182.5 TB
per robot at the rate Claim 1 assumes, and that arithmetic is the same on a site
with a fibre uplink as on one without ([`sensor-baseline.md`](sensor-baseline.md)
sources the rate and gives the sensitivity). A scene graph may be the only
representation you can retain, export, and hand to an assessor or insurer.

> **Amended twice on 2026-08-19; read the second amendment. Re-measured
> 2026-08-20.** The clause "orders of magnitude smaller" was struck that morning,
> because the benchmark showed the graph is ~13x *larger* per frame than a
> gzipped copy of the simulator's raw state stream, 24 columns and 19 of them
> Layer B — **measured on an artifact holding no Layer A**;
> the artifact this project ships carries the record stream and is ~40x larger,
> which is the figure Claim 1 publishes. It was restored the same day, because that
> stream was never what the claim was about — it is ~90 MB/day gzipped and
> answers no audit question. Against a *sensor* log the artifact is **~691x**
> smaller over a six-month retention period at occurrence resolution (264 GB vs
> 182.5 TB per robot). That is two orders of magnitude and not three: the
> earlier ~9,900x was measured before the artifact carried any Layer A record
> (issue #59). The artifact side is measured; the sensor side is sourced and must
> always be labelled a projection. See Claim 1 for both numbers and why the first
> amendment was wrong.

> **Amended 2026-08-26 (issue #102).** The thesis paragraph rested on a second
> empirical premise beside the sensor rate — an unsourced claim about the
> connectivity of the sites this targets — which appeared nowhere in
> [`sensor-baseline.md`](sensor-baseline.md), the document where every other
> assumption of this argument carries a source, a range and a sensitivity. It is
> **retired rather than sourced**: the volume and the retention floor carry the
> retention argument on their own. The retirement, and what evidence would bring
> the premise back, is recorded in `sensor-baseline.md`. *Off-network
> verifiability* is a different thing and is not retired — it is a **requirement**
> of this design rather than an observation about sites, and it is stated as one
> under Claim 4 and in [`limitations.md`](limitations.md) §6.

**This is not:** a perception system, a safety controller, a physics engine, a
research contribution to reachability analysis, or a proposed standard. It is an
argument about evidence, made concrete.

---

## Standards baseline

Every design decision traces to an existing precedent. This is what separates the
project from a toy, and it is the section that belongs on the personal site.

| Design element | Precedent | Status |
|---|---|---|
| Assurance lives in the endpoints; the uncertifiable middle is declared out of scope | IEC 61784-3 **black channel** | Published, universally deployed |
| Container with sequence number, watchdog, integrity check bound to endpoint identity | **PROFIsafe** (IEC 61784-3 profile) | Published |
| Passivation to safe state on any detected fault; reintegration gated, never automatic | PROFIsafe F-Device | Published |
| Enumerated fault taxonomy with a defined detection mechanism and response per fault | IEC 61784-3 clause structure | Published |
| Claim → argument → evidence, traced into a safety case; non-prescriptive, technology-agnostic, explicitly covers ML validation | **UL 4600** | Published (ANSI/UL 4600) |
| Actively controlled stability — de-energize is *not* a safe state; fall-zone and balance hazards | **ISO/CD 25785-1** | Committee Draft, no publication date |
| Cybersecurity requirements as they pertain to robot safety | **ISO 10218:2025** (Parts 1 & 2) | Published Feb 2025 |
| Speed and separation monitoring; time-varying protective volume from speed, stopping distance, sensor latency | ISO/TS 15066, now absorbed into **ISO 10218-2:2025** | Published |
| A mandated, retained evidence recorder for autonomy: **occurrences** with flag, reason, date, timestamp (±1.0 s) and the software version present at the event (`R157SWIN`) | **UNECE DSSAD**, UN R157 (ALKS) | Published; the closest existing thing to this project. `reg` implements the first four elements and **not** `R157SWIN` — see [`prior-art.md` §9](prior-art.md) |
| Automatic event logging over the system lifetime, retained ≥6 months, sufficient for post-hoc reconstruction of individual decisions | **EU AI Act Art. 12** (record-keeping), Art. 19 | In force. The ≥6 months is a floor *"unless provided otherwise… in particular Union law on the protection of personal data"* — an artifact holding personal data is bounded from both sides, and the obligations that creates are unaddressed here: [`limitations.md` §8](limitations.md) |

### Two deviations from precedent, both deliberate — state them prominently

**1. Keyed MAC, not CRC.** PROFIsafe's CRC is seeded with a known value. It is a
*safety* mechanism and is forgeable by anyone with the protocol spec; this has
been publicly demonstrated. This prototype uses HMAC because the threat model
includes an adversary, not just noise.

**2. Semantic faults, not transport faults.** PROFIsafe validates that a message
arrived intact, in order, from the right sender. It says nothing about whether the
message was a *good idea*. For a learned policy that is the entire problem. The
fault taxonomy in Phase 6 is the black-channel pattern applied to semantics — the
actual contribution here.

### The gap this addresses

ISO 25785-1 will specify what the *robot* must do. UL 4600 specifies how to
structure the *evidence*. Nothing specifies **what the model must emit** so an OEM
can build its safety case. That interface is the unoccupied space.

### The regulatory clock (context for the writeup)

EU AI Act fully in force August 2026. Revised Product Liability Directive applies
December 2026. Machinery Regulation January 2027. ISO 25785-1 still unpublished.
The evidence demand arrives before the standard does.

---

## Non-goals — enforce these, scope creep kills this project

| Do NOT build | Why |
|---|---|
| Perception / vision / SLAM | Thesis is evidence, not perception. Use ground-truth positions from the sim. |
| 3D or realistic robot models | 2D planar demonstrates every claim. |
| An HJ reachability solver | Sampling-based forward reachability on 4–6D state is enough. |
| Accurate physics | Nobody evaluating this cares about the dynamics. |
| A real-time system | Offline batch is fine. |
| A learned policy | Scripted trajectories. The policy being a black box is the *premise*, not something to implement. |
| A real PKI | Two keys in a keyring file. See the honesty note in Phase 6. |
| A UI beyond matplotlib | Static plots and a CLI. |

If a task doesn't serve one of the four claims, cut it.

---

## The four claims

**The numbers are identifiers, not a ranking.** They are referenced from 125
places across this repository, including `reg/` and `tests/`, so they do not
move. They were assigned in build order, and build order is not argument order —
reading the numbering as a priority is what let the differentiating claim sit at
six lines while the supporting one ran to 264.

Argument order is **4, 3, 2, 1**: what the artifact proves, what that proof is
worth, how you ask it, and what it costs to keep. The sections below stay in
numeric order so a reference to "Claim 1" still lands where a reader expects; the
summary in [`README.md`](../README.md) presents them in argument order.

Each is independently shippable.

### Claim 1 — Retention (what it costs to keep, and why that is a supporting claim)

**This section is the longest in the document and that is not a statement of its
importance.** It is long because it has been wrong twice and the corrections are
kept in place rather than tidied away — refuted against a baseline that was never
the claim, then republished against an artifact that turned out to hold no Layer A
at all. The record of how a number moved is worth more here than a clean
statement of where it landed, in a project whose argument is that evidence should
survive its own revision.

**What it now supports.** An attestation you cannot afford to keep until the
claim is filed is worthless, so retention is the enabling condition for Claim 4
rather than a rival to it. The property the rest of the argument needs is *cheap
enough to keep for the mandated window* — not *smaller than the alternative by
the largest available factor*. That distinction is why the section is named
Retention and no longer Compression: a ratio is a comparison against a
counterfactual, and an absolute cost against a legal retention floor is a fact
about a budget.

**Success, as originally stated:** 2–4 orders of magnitude, one number, one chart.

> **Reframed 2026-08-19, and this reframing is a correction to a correction.**
> The section below first recorded Claim 1 as *refuted*, on a benchmark that
> compared the artifact against a gzipped copy of the simulator's own raw state
> CSV — 24 columns for the priced fixture, 19 of them Layer B. That
> comparison was never the claim. It was the only baseline this simulator can
> produce, and treating "the only thing measurable" as "the thing being claimed"
> is the error — the same error the project exists to warn about, committed in its
> own success criterion.
>
> **Nobody has ever chosen between retaining this simulator's state stream and
> retaining a scene graph.** That stream is ~21 B/frame gzipped — 3.8 MB/hour,
> ~90 MB/day at 50 Hz — and it answers no audit question. (This line read "about 3.8 MB/day"
> until 2026-08-20; that was the hourly figure with the wrong unit on it, caught
> when every retention number here was re-measured. The argument is unaffected:
> 90 MB/day is still four orders below the sensor assumption.) The economic
> argument was always the artifact against *sensor* logs, which this simulator
> has none of.

**The commercial argument, stated as it should have been.** What matters to a
buyer is not a ratio, it is the absolute cost of retaining evidence for as long
as the law requires it. The EU AI Act sets that floor at six months — in
**Article 19** for providers and **Article 26(6)** for deployers; Article 12 is
record-keeping and sets no period. (This read "Article 12 sets that floor"
until 2026-08-21. `README.md` and this document's own regulatory table always
cited it correctly; the slip was under the headline number, which is where it
would have been read.)

**And that floor is subordinate to data-protection law, which this section does
not price** (issue #101). Both Articles set the six-month period *"unless
provided otherwise in applicable Union or national law, **in particular Union law
on the protection of personal data**"*. The artifact contains personal data:
`meta[operator_id]` with `meta[run_start_utc]` selects a shift, and the Layer B
edges record how close a human came to a machine, to the centimetre, all shift.
So for that half of the file six months may be a **ceiling** rather than a floor.
Every figure below is what it costs to keep the artifact for the mandated window;
none of them is a claim that keeping it for that window is permitted. The
entry — with Art. 26(7) and the DPIA obligation named, and no claim of
compliance — is [`docs/limitations.md` §8](limitations.md).

Per robot, from the measured resolution curve:

> **Measured 2026-08-20 (issue #60). These replace the provisional figures.**
> One execution of `python -m reg.bench --resolution --seed 0` — `long_run` at
> 3,000 frames (60.0 s of robot time), 16 envelope samples, 200 ms horizon,
> 1.0 s occurrence resolution, 0.5 s replan interval and declaration horizon,
> 1.0 s watchdog. The figures it replaces predated the #54/#55 encoding work
> and, far more importantly, measured an artifact holding **no Layer A at all**
> (issue #59). Every level got **larger**, and the coarsest got larger by 13.9x:
> the declaration, verdict and chain records are emitted per action and **no
> resolution level coarsens them**, so at ±1 s they are 3,120 of the artifact's
> 3,166 node rows. Coarsening now buys much less than the provisional table implied,
> and that is the finding, not a defect in it.

| retained at | per robot, 6 months | fleet of 100 |
|---|---|---|
| **occurrence (±1 s) — 98.5% attestation records** | **264 GB** | 26.4 TB |
| transition (10 ms) | 656 GB | 65.6 TB |
| per-frame (10 ms) | 953 GB | 95.3 TB |
| *raw sensor log @ 1 TB/day (assumed, **not measured here**)* | *182.5 TB* | *18.2 PB* |

Each is the measured `bytes/hour` for that level — 60.29, 149.72 and
217.57 MB/h — times the 4,380 hours in the 182.5-day retention floor. **Every
one of those three figures is a figure at 50 Hz**, which is what
`reg.scenarios.DEFAULT_DT` runs at, and every one of them **moves with that
rate**: enforcement emits one verdict and one chain record per commanded action
and no resolution level coarsens them. The *record layer* is linear in the rate;
the *file* is not, and by how much is measured below rather than assumed. A real
manipulator control loop runs at 1 kHz. That is measured, not asserted — see
*The control rate* below and [`sensor-baseline.md`](sensor-baseline.md).

And each is an **extrapolation from a 59.98-second run** in one respect that is
worth stating where the figure is: `bytes/hour` is `size x 3600 / run seconds`,
so the artifact's fixed schema-and-index cost is scaled to an hour alongside its
per-frame cost, and the hourly rate is therefore an **over**statement — by most
at the coarsest level, where that fixed cost is the largest share of the file.
The figures are published as measured rather than with the fixed term netted
out, because separating the two terms means fitting `size = fixed + per-frame x
frames` across run lengths and evaluating the fit, which is the extrapolation
`reg.bench` refuses everywhere else. `reg.bench` now carries this sentence in
**every** report shape that prints a `bytes/hour` figure — the resolution table,
the control-rate ladder and the console summary — rather than in one of the
three (issue #116).

**The first row's label changed in issue #116 and its figures did not.** What
the coarsest level actually holds, why it is no longer called *DSSAD-shaped*,
and the two labels that were rejected instead are below, under *What the
coarsest level actually holds*.

At occurrence resolution the artifact is **~691x smaller** than the sensor
stream over the mandated retention period: inside the original criterion's
two-order band, and **short of three**. The artifact side of that comparison is
measured. The sensor side is an **assumption with a sourced range**, set out in
[`sensor-baseline.md`](sensor-baseline.md) with its citations and a sensitivity
table; `reg.bench --sensor-multiplier` has no default, so the multiplier is
always stated rather than assumed.

**State it at two orders, not three, and never four.** The ratio is linear in
the assumed sensor rate, and the sensitivity analysis is blunt about what that
buys: the 2-order band is occupied down to 0.145 TB/day — a sevenfold margin
below the assumption, where before Layer A was measured it looked like a
hundredfold — while three orders needs 1.44 TB/day, which the published
assumption does **not** reach, and four needs 14.4 TB/day. The robust claim is
the one to make, and it is now a narrower one. It is also, conveniently, the
resolution the only mandated evidence recorder in existence operates at (UN R157
DSSAD, ±1.0 s). The finer levels are weaker again: transition clears two orders
only above ~0.36 TB/day and per-frame only above ~0.52 TB/day.

#### What the coarsest level actually holds, and what it is therefore called

**The first row's label was `occurrence (±1 s, DSSAD-shaped)` and it described
1.3% of the level** (issue #116). Measured on the artifact it prices — one
execution of the command in the blockquote above:

| the coarsest level, by node row | rows | share |
|---|---|---|
| verdicts — one per commanded action | 3,000 | 94.8% |
| declarations — one per replan interval | 120 | 3.8% |
| **attestation records together**, each carrying its chain record | **3,120** | **98.5%** |
| occurrences — the DSSAD-shaped part | 42 | 1.3% |
| entities — an occurrence naming an entity the file does not hold is not a record of anything | 4 | 0.1% |
| **total** | **3,166** | |

A reader who took *DSSAD-shaped* at face value concluded that this is a
DSSAD-equivalent event recorder priced at 264 GB. It is not. It is a **per-action
attestation record** with an occurrence layer attached, and 264 GB is
overwhelmingly the price of the attestation. Nothing in the *measurement* was
wrong — the figure reproduces to the byte — and nothing about it moved when the
label did.

**Replacing that label is a positioning decision, not a wording fix**, so the
alternatives and the choice are recorded here rather than settled by whichever
phrase read best:

| candidate label | what it claims this artifact is | verdict |
|---|---|---|
| *occurrence (±1 s, DSSAD-shaped)* | a mandated-style event recorder operating at DSSAD's quantum | **rejected.** True of 1.3% of the rows and of 100% of the reader's impression. It also claims a lineage the artifact does not have: `R157SWIN` is not implemented ([`prior-art.md` §9](prior-art.md)), so this is not a DSSAD even at the level it borrows a quantum from |
| *occurrence (±1 s)* | a timestamp resolution, and nothing about contents | **rejected.** Accurate and empty. Silence about what the level holds is what let the first label stand for three milestones |
| **occurrence (±1 s) — 98.5% attestation records** | a per-action attestation record whose coarsest view keeps a DSSAD-**aligned** occurrence layer | **chosen.** It states the composition, which is the thing a reader gets wrong, and it keeps the quantum's provenance where it belongs — on the quantum |

**What the choice commits this project to.** That Claim 1 is a claim about
retaining **attestation**, not about retaining events cheaply. Two consequences,
both stated rather than left to be discovered:

1. **The comparison against DSSAD is a comparison of resolution, not of
   contents.** UN R157's DSSAD is why ±1 s is the coarsest quantum this project
   prices (*The control rate* below, [`lossiness.md`](lossiness.md) *Level 1*);
   it is not a claim that `reg` at this level is a DSSAD, or that a DSSAD would
   cost 264 GB. A recorder holding this level's 42 occurrence rows and none of
   its 3,120 records would be a far smaller file, and this project has not
   measured one.
2. **The lever on the 264 GB is the attestation cadence**, not the occurrence
   vocabulary. Declaring per behaviour segment rather than per control step
   would cut the term that dominates; it is a design change to what the artifact
   attests, it is held open, and *The control rate* below says so again where it
   bites hardest.

#### The control rate — and it is not two orders at 1 kHz

> **Measured 2026-08-21 (issue #68).** `python -m reg.bench --control-rate-hz
> 50,100,250,1000 --seed 0`: the resolution curve at four control rates over one
> fixed run duration (59.98 s of robot time), same seed, same envelope
> parameters, same record parameterization. The 50 Hz row is the published curve
> above, reproduced byte for byte, which is what makes the other three
> comparable to it. Measured points only — nothing here is fitted or
> extrapolated.

Every retention figure in this section is a figure **at 50 Hz** and every one of
them **moves with that rate**, because enforcement emits one verdict and one
chain record per commanded action and no resolution level coarsens them. The
declaration count does not move with the rate at all — the policy replans on a
wall-clock interval — so the verdicts are the whole of the growth **in rows**.
The growth in *bytes* is slower than that, and *Why the growth is sublinear*
below is where the difference is attributed rather than asserted. A real
manipulator control loop runs at 1 kHz, twenty times this simulator's rate:

| control rate | occurrence | transition | per-frame |
|---|---|---|---|
| **50 Hz (this simulator, published above)** | **60.29 MB/h → 264 GB → ~691x** | 149.72 MB/h → 656 GB → ~278x | 217.57 MB/h → 953 GB → ~192x |
| 100 Hz | 106.45 MB/h → 466 GB → ~391x | 246.33 MB/h → 1.08 TB → ~169x | 409.70 MB/h → 1.79 TB → ~102x |
| 250 Hz | 247.13 MB/h → 1.08 TB → ~169x | 528.44 MB/h → 2.31 TB → ~79x | 1.04 GB/h → 4.56 TB → ~40x |
| **1 kHz (a real manipulator)** | **951.65 MB/h → 4.17 TB → ~44x** | 1.94 GB/h → 8.50 TB → ~21x | 4.26 GB/h → 18.66 TB → ~10x |

The `MB/h` column is measured. The six-month size is that figure times the 4,380
hours in the retention floor, and the ratio is against the **assumed** 182.5 TB
sensor log — an assumption, unchanged, at 1 TB/day
([`sensor-baseline.md`](sensor-baseline.md)).

**Two of those rungs are above the artifact's own declared domain of validity, and
that is stated here rather than two documents away.**
`reg.tolerances.TIME_BASE_MAX_RATE_HZ` is 100 Hz — the reciprocal of `TIME_TOL_S`
— and above it several control frames share one addressable instant, so a
per-frame value read back out of an interval is the value of whichever frame
opened it ([`limitations.md`](limitations.md) §5). The 250 Hz and 1 kHz rows are
real retention costs a real manipulator really pays, and they are what a reader
should budget from; what they are not is rates at which every per-frame query
answers inside its published tolerance. The `DISAGREE` below is the same fact
arriving from the other side. Wherever these two rungs are quoted, §5 is quoted
with them.

**They are also not pinned, and this is the record of that decision (issue #98).**
`tests/test_published_figures.py` re-measures the published curve on every CI run
and compares it against the tables in this repository — but only the **50 Hz**
row, which is the curve it builds. Extending it to the ladder means running
`--control-rate-hz 50,100,250,1000` in the test session, and the 1 kHz point alone
is twenty times the frames of the pinned build, for rows that can only move when
the 50 Hz row moves: every one of them is the same curve at a different `dt`.
**The decision is to leave the pin where it is and to stop the unpinned rungs
being quoted as though they were pinned** — the ladder is a manual measurement,
dated and commanded in the blockquote above, and `README.md` now says so in the
same breath as it quotes the 1 kHz figure rather than leading with it. Silence was
the third option and it is the one this project keeps having to correct.

**So the two-order claim is a claim about the control rate as well as about the
sensor rate, and at 1 kHz it does not hold.** At occurrence resolution a 1 kHz
robot retains **4.17 TB** for the mandated six months and the artifact is
**~44x** below the assumed sensor log — **one order of magnitude, not two**, and
at a rate whose per-frame queries are outside the artifact's stated time base
([`limitations.md`](limitations.md) §5). The
band survives at 250 Hz (~169x) and is gone by 1 kHz; where between those two it
goes is not measured and is therefore not quoted. **The assumption was not
touched to fix this** — the sensor multiplier is the same 1 TB/day it was, for
the same sourced reasons, and moving it to keep a conclusion is the exact
failure `sensor-baseline.md` exists to prevent.

**How to state Claim 1 now.** *At occurrence resolution, two orders of magnitude
at a 50 Hz control rate and one at 1 kHz — the first pinned, the second a manual
measurement at a rate above the artifact's time base
([`limitations.md`](limitations.md) §5).* Both are measured; which one applies
is a property of the robot, not of this argument. The growth is **sublinear** —
15.8x for a 20x rate increase — and the record layer is what does scale: at
1 kHz it is 60,101 of the occurrence level's 60,572 node rows, against 3,120 of
3,166 at 50 Hz. *Why* the bytes grow more slowly than the rows is measured in
*Why the growth is sublinear* below, and was stated wrongly here until issue
#116.

**What is not done here.** Declaring per behaviour segment rather than per
control step would cut the term that scales, and it is the dominant lever: the
verdict layer is essentially all of the growth. It is a design change to the
attestation cadence, held pending its own decision, and issue #68 explicitly
does not take it.

#### Why the growth is sublinear, and why the cause given here was wrong

**What this document said for three milestones:** *the scene rows and the fixed
schema-and-index cost do not scale with the rate.* Both clauses are true. Neither
term is anywhere near large enough to turn a 20x rate increase into 15.8x, and
the term that is large enough was not named at all (issue #116). The 15.8x is a
measurement and it has not moved; what follows replaces the account of it.

Bytes per table, from SQLite's own `dbstat`, on the **50 Hz** rung of the ladder
above — which is the published curve, so this attributes the very artifact
Claim 1 prices:

| table, coarsest level at 50 Hz | bytes | share of the level |
|---|---|---|
| `verdict` | 551,936 | 54.9% |
| `declaration` | 185,344 | 18.5% |
| `indexes + schema` | 129,024 | 12.8% |
| `node` | 112,640 | 11.2% |
| `meta` | 10,240 | 1.0% |
| `occurrence` | 9,216 | 0.9% |
| `entity` | 3,072 | 0.3% |
| `envelope`, `robot_config`, `edge` — one empty page each | 3,072 | 0.3% |
| **file** | **1,004,544** | |

1. **The scene rows are 5,120 B**, 0.5% of the level: `entity`, `envelope` and
   `robot_config` together, two of the three being a single empty page at this
   level. Half a percent of a file cannot account for a fifth of its growth.
2. **`indexes + schema` is not the artifact's fixed cost.** It is 129,024 B
   here and most of it is indexes *over rows*, which arrive with the rows and
   leave with them. The genuinely fixed part is the schema: an artifact created
   and never written to is **26,624 B** — `reg.store.create(path,
   record_tables=True)`, ten tables and their indexes at `reg.store.PAGE_SIZE` —
   which is 2.6% of this level.
3. **The mass the control rate does not move is the `declaration` table**, at
   185,344 B and 18.5% of the level. The fixture's policy replans on a
   **wall-clock** interval, so it emits the same 120 declarations at every rung
   of the ladder — `tests/test_bench.py` asserts exactly that, because a
   declaration count that started tracking the frame clock would invalidate the
   study — and a declaration row is fat: ~1,545 B against a verdict row's
   ~184 B, because it carries the declared region as a polygon. Twenty times the
   control rate buys twenty times the verdicts and **no** further declarations.
   An 18.5% share at 50 Hz is a share of about 1% at 1 kHz, and that dilution is
   where the difference between 20x and 15.8x goes.

**The two terms this document named come to 31,744 B, 3.2% of the level; the
term it did not name is 185,344 B, 18.5%.** The stated cause is smaller than the
one that carries the effect by a factor of **5.8**. Issue #116 estimated the miss
at ~15x, reading it off *row* counts; measured in bytes it is 5.8x against the
term that actually carries it. Same direction, same conclusion, and now an
arithmetic anybody can re-run.

**And it is no longer this document's job to be right about it.** `reg.bench`
prints the whole attribution at **every** rung of any ladder it is asked for,
and an exact identity over it — what each table would hold had it grown with the
rate, minus what it holds, summing to the difference with no remainder — under
*Where the `occurrence` bytes are, and which of them the rate moves*. The cause
is read off a column instead of being asserted in prose. On a SQLite build
without `dbstat` the report states that the cause **could not be established**
and substitutes nothing for it, which is the failure mode this subsection is
repairing, made unavailable.

**And the finer levels stop answering before they stop being affordable.** At
250 Hz and 1 kHz the transition and per-frame levels return `DISAGREE` on
`separation_timeline`: the edge layer's endpoints are quantized to `TIME_TOL_S`
= 0.01 s, which is coarser than the control period above 100 Hz, so a per-frame
separation read back out of an interval can miss by more than `DISTANCE_TOL_M`.
That is a measurement, not a tolerance to widen (`docs/lossiness.md`), and it is
a finding about the **graph builder** rather than about retention cost — so it
is reported here and in the benchmark's own table, and repairing it is a
separate piece of work in `reg.graph`, not something this measurement is
permitted to tune away.

**This is a purchasing decision, not a slogan.** 264 GB buys *did contact
occur*, *how close did it come*, every refused action with its fault code and
the declaration it was raised against, and both hash chains walked end to end.
It also buys *when* — **for events sustained longer than its one-second
quantum**; a brief minimum it refuses rather than misplaces, and whether a
coarse timestamp is enough is a property of the event, not of the recorder. 655
GB buys *when exactly* for an event of any length, the full separation timeline,
and the region each declaration claimed and each clamp actually applied — which
±1 s does not hold, so `declared_bound` and `verdicts` come back
`COULD-NOT-EVALUATE` there. The resolution curve prices evidence per audit
question, and that is the commercial argument in its useful form.

#### The measured result against the wrong baseline, kept because it bounds the design


**What was measured** (`python -m reg.bench --scaling --seed 0`, re-run
2026-08-20 for issue #60; long-run fixture, 16 envelope samples, 200 ms
horizon, no record stream at any rung — this ladder is a size comparison
against the raw stream and holds no Layer A):

| frames | robot time | x gz CSV |
|---|---|---|
| 300 | 6 s | 0.06x |
| 3,000 | 60 s | 0.08x |
| 30,000 | 600 s | 0.08x |

The ratio *does* improve with run length — the fixed schema cost amortises — and
then flattens. **It does not reach 1.0 anywhere in the measured range.** The
marginal cost of one more frame is constant across every measured interval:
~21 B of gzipped CSV against ~263 B of SQLite. **With no record stream in it —
which is what every rung above holds** — the artifact is roughly 13x *larger*
than a gzipped copy of the stream it replaces, and no amount of run length
changes that, because it is the per-frame cost that dominates, not the fixed one.
That condition travels with the number: the artifact Claim 1 actually prices
carries Layer A and is **~40x** larger, measured immediately below.

**Why, and it is structural rather than an encoding detail:** the incremental
rule compresses relationships that hold still. An arm in motion changes its
distance to every entity continuously, so `SEPARATION` edges are emitted at a
rate set by how fast the arm moves, and a row in SQLite with its indexes costs
an order of magnitude more than a line of gzipped CSV.

That result stands and is worth publishing, as a bounded engineering finding
rather than a verdict: **the graph costs ~263 B/frame, which is expensive next to
a float codec and negligible next to anything with a camera in it.** Reporting it
openly is what makes the sensor-log projection credible rather than promotional —
a paper that only reports the flattering comparison has told you which
comparisons it ran.

Two encoding passes (#54 page size and unused tables, #55 integer surrogate keys
and a binary hash) took ~13% off on disk and ~3% compressed. That bounds the
lever: **encoding does not move this number, and no further encoding work should
be undertaken expecting it to.** The variable that moves it is resolution.

##### The same comparison, measured on the artifact that carries Layer A

**13x is the figure for an artifact holding no declaration, no verdict, no fault
and no chain record.** The ladder above sets `records=None` at every rung, for the
reason the blockquote gives: a record stream adds a term that scales with the
replan interval rather than with the run, and the study's variable is the run.
That is the right parameterization for a study about *length* and the wrong number
to quote as the cost of the artifact this project ships — which is issue #59's
error, found in the resolution curve, surviving in the front page until issue #98.

**What was measured** on the build the retention figures above come from
(`python -m reg.bench --resolution --seed 0`; `long_run` at 3,000 frames **at a
50 Hz control rate**, 16 envelope samples, 200 ms horizon, 1.0 s occurrence
resolution, 0.5 s replan interval and declaration horizon, 1.0 s watchdog), taking
the artifact `reg.graph build` produced before any resolution view is materialized
from it:

| the build Claim 1 prices, at 3,000 frames | measured |
|---|---|
| declarations | 120 |
| verdicts | 3,000 |
| faults | 24 |
| chain records | 3,120 |
| artifact on disk | 2,577,408 B |
| gzipped CSV baseline | 64,651 B |
| x gz CSV | 0.03x |
| how much larger | ~40x |

**That baseline is not the incumbent, and the gap is now measured.** Nobody
retains a gzipped CSV; practitioners retain rosbag2, in MCAP. For the same
proprioceptive content — `t`, `q`, `qd` over the same fixture — MCAP
`/joint_states` costs **2.51x** what the gzipped CSV costs: 7,669 B against
3,053 B, computed from the MCAP specification and chunk-compressed, recorded as a
projection in [`sensor-baseline.md`](sensor-baseline.md) *The incumbent encoding*
and held to the byte by `tests/test_incumbent_encoding.py`.

So **~40x overstates the artifact's disadvantage against what a buyer actually
keeps**, and by an amount this project has not measured: the 2.51x is
proprioception on both sides, while the ~40x baseline carries the human's state
and three obstacles as well. The two comparisons do not cover the same content
and are not composable into a single corrected ratio. **~40x remains the number
to quote**, now with the incumbent named beside it rather than left unstated.


The baseline is the same 64,651 B on both sides of the comparison — same fixture,
same seed, same stream — so the whole of the distance between 13x and **~40x** is
the Layer A the build carries: the ladder above has **no record stream** in it and
this build has 3,120 chain records in it. **~40x is the number to quote**, and 13x
may be quoted only with that condition attached in the same sentence, which
`tests/test_published_figures.py` now checks in every document that quotes it.

The table itself is pinned rather than asserted: the same module re-measures this
build on every CI run and compares it against the table above, and it fails in both
directions — a code change that moves the measurement fails it, and a table edited
to match a regression fails it too.

Nothing here changes the conclusion the section exists for. The answer to *is the
graph smaller than the stream it replaces* is still **no**, by rather more than it
looked, and for the same structural reason.

**Success, restated to something a measurement can meet or miss:**

1. The **absolute retention cost** is measured at each resolution level and
   reported per robot per six months, beside what each level can answer.
2. Any comparison against a sensor log is **labelled a projection**, computed
   from a stated multiplier, and never quoted as a measured ratio.
3. The ratio against the raw stream is reported **across run lengths** as a
   design bound, with the crossover at 1.0 stated or its absence stated. Measured
   points only.
4. Superseded, and kept for the record: *until a measured length clears 1.0, the
   retainable-artifact argument does not rest on compression.* It was written
   when the wrong baseline was believed to be the right one. It rests on
   compression again, correctly stated — and on Claims 2–4 — query, sufficiency
   boundary, attestation — none of which needs the artifact to be smaller than
   the stream. Nothing in this repository may quote a compression ratio as the
   commercial argument while the measured one is below 1.

The original criterion is kept above rather than deleted: it is what the project
set out to show, and the gap between it and the table is the finding.

#### Why it lost — three things the measurement exposed (2026-08-19)

**1. The baseline was never the thesis.** This document argues from
*terabytes/day of raw sensor logs* — cameras, LiDAR, tactile, IMU. What
`reg.bench` measures against is the simulator's own raw state CSV, which for the
priced `declared_violation` fixture is **24 columns, 19 of them Layer B** — the
human's pose and velocity and each obstacle's id, kind and pose, beside the five
proprioceptive columns `t`, `q_0`, `q_1`, `qd_0`, `qd_1`
(`reg.stream.expected_header(2, 3)`, `reg.bench.proprioceptive_columns`).
Gzipped, that whole stream lands at ~21 B/frame. The comparison was a relational
artifact with indexes and content hashes against a float compressor doing what
float compressors are for. It was unwinnable, and losing it says nothing about
the thesis.

*What ~21 B/frame may and may not be compared against.* It is the full
24-column stream, so it is not a per-point figure and does not sit beside one.
Until 2026-08-27 this paragraph placed it next to Gorilla's **1.37 bytes per
point** (`docs/prior-art.md` §8) as though the two were the same measurement;
they are not, because most of those 24 columns are entity state no time-series
compressor is benchmarked on. The like-for-like slice, measured on the same
fixture and the same seed, is the five proprioceptive columns alone: **3,053 B
gzipped over 251 frames = 12.2 B/frame**, ~2.4 B per recorded value. That is the
number to put beside Gorilla — and even it is not a clean comparison, since a
Gorilla *point* is a (timestamp, value) pair while `t` here is shared across the
four joint values in a frame. Both figures come from
`python -m reg.sim --scenario declared_violation --seed 0`, the second through
`reg.bench.gzip_bytes_of_columns` over `reg.bench.proprioceptive_columns`;
~21 B/frame is unchanged and is what the retention arithmetic above uses.

**2. The number that is actually about retention is absolute, and we have it.**
At 30,000 frames / 600 s **at 50 Hz** the artifact is 7.89 MB, i.e. **47.3
MB/hour, 1.14
GB/day** (355 MB/day gzipped) — re-measured 2026-08-20, and still an artifact
at transition resolution with no Layer A in it, which is what makes it
comparable to the 8.59 MB this line used to quote. That is a measured property
of this simulator's output, quotable without a ratio, and it is comfortably
retainable and exportable.
Whether it is three orders of magnitude below a real sensor log is
**imported context, not a result** — this simulator has no sensors and cannot
measure it. Say so wherever the figure appears.

**3. `reg` chose a resolution no standard asks for.** UN R157's DSSAD — the
mandated evidence recorder for automated driving, and the closest precedent this
project has — stores **occurrences**: an occurrence flag, a reason, a date, a
timestamp at **±1.0 second**, and the software version identifier present at the
event. `reg` stores relationships at **cm / 10 ms, every frame**. Two orders of
magnitude finer than the only comparable thing that is actually required by law.
The per-frame cost that sank Claim 1 is the price of a resolution nobody
specified.

#### What replaces it: resolution as the measured variable

Claim 1 stops being "is the graph smaller than the stream" — that is answered, no
— and becomes **"what does evidence cost per unit of resolution, and how coarse
can it get before it stops answering the question?"**

That is a better claim in three ways: it is measurable here, it maps onto a
mandated schema instead of an invented one, and its answer is useful whichever
way it comes out. Concretely, the deliverable is one curve with at least three
points — occurrence-level (DSSAD-aligned), transition-level, and the current
per-frame level — reporting for each: bytes/hour, and whether the supported
queries still `AGREE` within their stated tolerance.

If the occurrence level answers the audit questions at a fraction of the bytes,
that is the commercial argument, properly grounded. If it does not, the finding
is that the questions this project cares about need finer evidence than the
regulation currently mandates — which is a more interesting thing to say than a
compression ratio.

### Claim 2 — Query (what makes it evidence, not a log)
Audit questions answered from the graph alone, no access to the original stream.
**Success:** 4 queries returning answers verifiable against held-out ground truth.

**Reframed 2026-08-19.** The benchmark reports a 264–380x speedup against
recomputing from the raw CSV, and **that is not the claim worth making** — 70 ms
is not slow, and nobody retains an evidence artifact to save 70 ms. The claim is
the `AGREE` column beside it: at every measured length up to 30,000 frames, the
graph's answer matches ground truth recomputed from the raw stream to within
0.0–8.2 mm against a 10 mm advertised tolerance.

That is the retention argument, not a performance one: **the answers survive the
discard.** A smaller artifact that answered differently would be worthless; this
one answers the same and is the thing you can still hold when the stream is gone.
Quote the agreement, mention the speed once, and never lead with it.

### Claim 3 — Sufficiency boundary (the strongest surviving novelty)

**The claim.** Which answers the proprioception-only layer supports on its own
authority, and which are a conjunction with *the entity was where the artifact
says it was* — recorded per answer, in the artifact, and queryable afterwards.

**Stated narrowly, because the broad version is taken.** ConSerts (Schneider &
Trapp) formalised guarantees that hold conditional on runtime evidence supplied
by components carrying their own assurance, and dynamic safety cases (Denney &
Pai) update the argument as that evidence arrives —
[`docs/prior-art.md`](prior-art.md) §13. So the novelty is **not** that a claim
can be conditional on runtime evidence. It is that **the conditionality of each
answer is retained with the answer and can be asked about months later**, and
that the case it handles is the one where no assured component exists or ever
will. A ConSert discharges a demand against a component's guarantee and withdraws
the guarantee when it cannot; `reg` answers anyway and marks what the answer
depends on. *May I act* versus *what may be concluded afterwards*.

**Why it is Layer A that makes this work.** The boundary is enforced by types
rather than by reviewer discipline — `ProprioState` names no entity, and
`tests/test_layer_boundary.py` fails if that erodes — and by the schema, where
`layer` is a column on every edge and every occurrence rather than a caveat in a
README. `Limits` was the known gap — it was declared Layer A as a property of the
robot, and under ISO/TS 15066 speed-and-separation monitoring a commanded speed
bound is a function of measured separation, which makes it perception-derived
while nothing caught it. **Closed by issue #84**: `Limits.source` is required with
no default, and the `HAS_ENVELOPE` edge is tagged from it rather than from its
type, so an SSM-derived envelope is a Layer B edge. The dependence is unchanged;
what changed is that the artifact records it. See
[`docs/sufficiency.md`](sufficiency.md) §7 for what that still does not claim —
starting with the fact that a two-value provenance is a simplification.

**Success:** a taxonomy with worked examples of each, normative for what this
project may claim.

### Claim 4 — Attestation (the one the others exist to support)

**The claim.** After the fact, the artifact can say what the policy committed to,
what an independent check concluded about it, and whether the record has been
altered since — and the first two do not come from the same party.

**The mechanism.** A `Declaration` is emitted by the policy side and states a
bound it intends to stay within. A `Verdict` is emitted by enforcement, which
recomputes its own bound from the robot's own limits and never reads the declared
one. Both are chained: every record carries a hash link to its predecessor and a
keyed MAC, so a deletion or an edit breaks verification at that point and at
every point after it.

**Why the independence is structural rather than promised.** `reg/enforce.py`
imports from `declare/` no further than the `Declaration` dataclass, and
`tests/test_enforce.py` asserts that against the source at the AST level. A
constraint layer supplied by the same party as the policy has common-cause
failure with it; widening that import is never a refactor.

**What the independent check actually checks, stated plainly.**
`horizon_bound(state, limits, window)` is the radius a declared region is tested
against, and it is the smaller of two sound bounds: the workspace disc
`sum(link_lengths) + link_radius`, which reads no `q`, no `q̇` and no horizon; and
the radial projection of `reg.envelope.outer_envelope`, a horizon-limited **outer**
reachable set — the joint box pushed through the forward kinematics as an interval
— which reads all three. Both over-cover, so nothing inside is ever falsely
accused.

It is **still incomplete, and in a way that is now sayable in one line**: the bound
is a radius, so it detects an overclaim that reaches *further than the robot can*
and not one that points *where the robot cannot turn in time*. Until issue #82 the
first was undetected too, and the fault a Simplex / ASTM F3269 runtime monitor
exists to catch — the policy declared more than it could occupy within the horizon
— could not fire at all unless the declaration left the entire workspace. The
polygon that would close the angular half is computed and its area and radius are
retained beside every envelope in the artifact; wiring it to the *containment* test
re-labels three of the five fault fixtures as overclaims, which changes what a
fault in the §5 taxonomy means, so it is left as a decision rather than taken as a
step ([`docs/limitations.md`](limitations.md) §3). The independence is real; the
capability is bounded and the bound is stated. Those are different sentences and
this document has previously run them together.

**What the chain proves, and what it does not.** It proves the records are
internally consistent under the keys that signed them. It does not prove no
record was withheld. On re-issuance — the whole history re-run and re-signed
offline by its own author, which is the party a regulator distrusts most — issue
#83 closed the two gaps that made the question unaskable, and it is worth being
exact about how far that goes.

The artifact now carries **absolute time**: `--run-start` is a required
caller-supplied input with no default, `meta` names the unit and the operator,
and every occurrence carries DSSAD's `date` derived from that start. Determinism
is untouched, because the instant is declared rather than read from a clock —
same seed *and* same declared start, same bytes. That makes the run locatable and
correlatable with the other logs in the cell. It does not by itself make the date
*true*: it is a claim by the same author as the records.

What bears on the claim is the **commitment** (`reg/commit.py`): the two chain
heads signed at artifact close by a second on-site keyholder whose key signed no
record in the file, refused outright if it is one of the record-signing keys.
Half of it needs no key at all — the recorded heads are recomputed from the
records the artifact actually holds, so *anyone* holding the file can see a
re-issued chain — and the witness signature is what stops the recorded heads
being rewritten to match. An artifact closed with no supplier records
`commitment: none` explicitly; silence never reads as commitment.

So this is now the structure of non-repudiation **plus a second party at the same
site**, and that is the honest ceiling of it. An on-site witness is not a
third-party timestamp: it does not prove the heads existed by any given instant
to someone with no relationship to the operator. RFC 3161 and transparency-log
adapters would, and both are documented and deliberately unimplemented — each
needs a network call at artifact close, and this artifact is required to be
checkable years later with no service still running and no call to anyone. That
requirement is not a site constraint worked around; it is the point. An assessor
certifying what happened needs a record whose integrity does not rest on
infrastructure belonging to the party being assessed, and the telemetry pipeline
these sites already run is that party's. The `Committer` interface exists so that
a deployment prepared to take the dependency gets an adapter rather than a
rewrite.

**What this claim does not cover, stated here rather than left to be inferred.**
Passivation and reintegration — Phase 4's asymmetry, the part the plan says people
omit — is implemented in `reg/enforce.py` and reaches no artifact, so *was the
passivation acknowledged, and by whom* is not among the questions this claim's
evidence answers. The refusal that keeps the `Acknowledgment` out is deliberate
and documented (Phase 4 below, [`docs/lossiness.md`](lossiness.md) *Retained* #7);
what it means for the claim is that the attestation an artifact carries is
declaration, verdict and chain, and not the record that cleared a fault. Issue
#112.

**Success:** the demo sentence answered end to end, as one query, with
`verify_chain` able to say no — demonstrated by `--tamper`, not asserted.

---

## Architecture

```
sim/          2D world, robot kinematics, scripted human motion
envelope/     proprioception-only forward reachable set  [LAYER A]
declare/      policy-side declaration emission            [BLACK CHANNEL]
enforce/      independent verification, verdicts, faults  [LAYER A]
chain/        hash chain + HMAC over the record
graph/        temporal evidence graph, incremental diff
store/        persistence (SQLite)
query/        audit query API
viz/          matplotlib rendering
bench/        compression + query benchmarks
```

### Stack

Python 3.11+ · `numpy` · `shapely` · `sqlite3` (stdlib) · `matplotlib` ·
`hmac`/`hashlib` (stdlib) · `pytest`

**Only `shapely` is load-bearing.** Polygon union and intersection is the actual
math; reimplementing it is a waste. Everything else is substitutable — if you swap
something, note it in the README, because reproducibility is part of the claim
this project makes.

**SQLite, not DuckDB.** The tables are small, the queries are interval joins and
chain walks, and SQLite is stdlib. It also strengthens the artifact story: a
single portable file with no external runtime is more credible as something handed
to an assessor than a format requiring a specific engine. Geometry is stored as
WKB blobs; all geometric work happens in Python via shapely.

**No `networkx`.** Graph construction writes straight to SQL. If in-memory
manipulation turns out to be genuinely needed during Phase 5, add it then — not
preemptively.

**No PyBullet.** Write the 2D kinematics directly — ~100 lines, and it removes a
dependency that invites scope creep.

**Raw stream format: CSV.** Not parquet. It's a more legible compression baseline
and drops `pyarrow`. Report both the raw CSV size and a gzipped CSV size, since a
skeptic will rightly ask whether the graph is just beating an uncompressed format.

---

## Phase 1 — Simulator

**Goal:** a deterministic 2D world producing a ground-truth state stream.

**Robot:** planar arm, 2–3 revolute links, fixed base. State `q`, `q̇`. Known
limits `q_min`, `q_max`, `q̇_max`, and an acceleration bound `q̈_max` (treat the
torque limit as an acceleration bound — do not build a dynamics model). FK → link
segment endpoints.

**World:** rectangular room, 3–5 static obstacles, one moving human (circle with
position and velocity).

**Human motion:** scripted, named scenarios. Author these first — they're the
fixtures for everything downstream.

- `approach_and_retreat` — enters reachable set, leaves, no contact
- `near_miss` — envelope intersects, no contact
- `contact` — body intersection (the incident case)
- `static_bystander` — present, never in envelope
- `sustained_overlap` — inside envelope across many frames
- `declared_violation` — policy declares one bound, then commands outside it

**Robot motion:** scripted joint waypoints with interpolation. No planner, no
controller.

```python
@dataclass
class StateFrame:
    t: float
    q: np.ndarray
    qd: np.ndarray
    human_pos: np.ndarray     # ground truth — Layer B only
    human_vel: np.ndarray
    objects: list[Obstacle]   # static, but log per-frame to inflate the raw stream honestly
```

**Deliverable:** `python -m reg.sim --scenario contact --out runs/contact.csv`

---

## Phase 2 — Proprioception-only envelope [Layer A]

**Goal:** from `q`, `q̇`, and kinematic/actuation limits *alone*, compute the
region the body can occupy within horizon `H` (default 200ms).

**Critical constraint:** this must not touch `human_pos` or `objects`. **Enforce
with a type boundary** — pass only a `ProprioState` struct in. This is the single
most important structural property in the codebase. If the envelope can see the
world, the sufficiency argument evaporates and you've built a visualization.

**Method (sampling, not HJ):**

1. Sample N control sequences within `q̈_max` over `H` (N ≈ 500–2000; corner
   controls plus random interior)
2. Forward-integrate each
3. Swept link polygons via FK at substeps
4. Union → reachable region
5. Return `shapely` polygon

This is an **inner approximation** — sampling can only under-cover. Say so in the
code and the writeup. A real safety claim needs an outer approximation. Naming
this is a point in your favor.

Also compute `envelope_area` and `envelope_hash` (for Phase 5 diffing).

**Deliverable:** `compute_envelope(proprio_state, limits, horizon=0.2) -> Polygon`,
plus a single-frame visualization.

---

## Phase 3 — Declaration [black channel side]

**Goal:** the policy emits a machine-readable statement of intent before actuating.

The policy here is scripted and deliberately imperfect — in `declared_violation`
it declares one bound and then commands outside it. **The policy is the black
channel: arbitrarily capable, uncertified, out of scope.** Do not make it smart.

```python
@dataclass
class Declaration:
    declaration_id: str
    seq: int                    # monotonic — replay/reorder detection
    t_issued: float
    horizon: float              # validity window
    action_class: str           # from a fixed vocabulary
    declared_envelope: bytes    # WKB polygon the policy claims it will stay within
    prev_hash: str              # hash chain link
    mac: str                    # HMAC over all of the above, policy key
```

Vocabulary for `action_class`: `reach`, `hold`, `retract`, `traverse`, `escalate`.
Fixed and small — an out-of-vocabulary declaration is a detectable fault.

**Deliverable:** declaration stream alongside the state stream, one per replan
interval (not per frame — declarations are cheap because they're coarse, which is
part of the compression story).

---

## Phase 4 — Enforcement and fault detection [Layer A]

**Goal:** independently verify each declaration and each commanded action, emit a
signed verdict.

**Independence is the mechanism.** The enforcement layer computes its own bound
and never trusts the declared one. In the code, enforcement must not import from
`declare/` beyond the dataclass, and it may not see Layer B at all — both are
asserted against the source in `tests/test_enforce.py`. This mirrors the argument
that a constraint layer supplied by the same party as the policy has common-cause
failure with it.

**What that bound actually is, and what Phase 4 therefore delivers.** The bound
is *not* `compute_envelope` from Phase 2 — that is an under-approximation, and
vetoing against something that under-covers the reachable set would produce false
VETOs on truthful policies. It is `reg.enforce.horizon_bound(state, limits,
window)`, the smaller of two bounds that each over-cover:

- `computed_bound(limits)`, the radius of the **workspace disc**,
  `sum(link_lengths) + link_radius`, base at the origin. It takes `Limits`, a
  property of the robot rather than of its state, so it reads no `q`, no `qd` and
  no horizon and is the same scalar at every frame of every scenario.
- the radial projection of `reg.envelope.outer_envelope(state, limits, window)` —
  a horizon-limited **outer** reachable set, the joint box pushed through the
  forward kinematics as an interval (issue #82). This one reads all three.

That makes Phase 4 an independent monitor whose bound is **sound in the
conservative direction and radial.** It over-covers, so nothing inside it is ever
falsely accused, and every VETO it does emit is real. Until issue #82 the second
term did not exist and the check was weak enough that the `envelope_overclaim`
fixture had to declare past the *entire workspace* to trip it; it now fires on a
declaration reaching further than the robot can get in the window it declared,
which is the fault a Simplex / ASTM F3269 runtime monitor exists to catch. What
remains uncaught is the **angular** half — a region of a reachable radius in a
direction the robot cannot turn to in time. The polygon that would catch those is
computed, and its area and radius are retained beside every envelope in the
artifact as the other side of the bracket; using it for containment rather than
for its radius re-labels three of the five fault fixtures as overclaims, so it is
a decision about the taxonomy rather than a tightening. A tighter *construction*
again is the zonotope machinery of ARMTD and ARMOUR ([`docs/prior-art.md`
§4](prior-art.md)), which this plan still de-scopes. Recorded as
[`docs/limitations.md`](limitations.md) §3; `reg/enforce.py`'s module header is
the authority on the reasoning.

The other eight faults in the taxonomy below are unaffected by this: staleness,
replay, MAC, vocabulary, watchdog and the declaration/action mismatch are each
decided exactly, against the record rather than against a reachability bound.

### The fault taxonomy — the core contribution

The 61784-3 pattern applied to semantics rather than transport.

| Fault | Detection | Response |
|---|---|---|
| **No declaration** | Actuation with no open valid declaration | VETO |
| **Stale declaration** | `t_now > t_issued + horizon` | VETO, require re-declaration |
| **Declaration/action mismatch** | Commanded action outside the declared envelope | CLAMP to declared bound |
| **Envelope overclaim** | Declared envelope exceeds `horizon_bound` — the smaller of the static workspace disc and the radial projection of the horizon-limited outer reachable set (#82). Catches the **radial** half: a folded arm, or one whose velocity bound will not carry it to full extension in the window, has a bound well inside the disc. The **angular** half is still undetected — a region of reachable radius in a direction the robot cannot turn to in time. The polygon that would catch it is computed and retained; using it for containment is a held decision | VETO the declaration itself |
| **Out-of-vocabulary action** | `action_class` not in schema | VETO |
| **Unattributed** | MAC verification fails | VETO |
| **Replay / reorder** | `seq` reuse or regression | VETO |
| **Watchdog expiry** | No declaration within `W` ms | Drive to safe state |
| **Escalation failure** | Escalation conditions met, no `escalate` declaration emitted | Flag + safe state |

Note the last one has no PROFIsafe analog. It exists because a learned policy can
fail by *not acting*, which a transport protocol never has to consider. Worth
calling out in the writeup.

### Verdict

```python
@dataclass
class Verdict:
    verdict_id: str
    declaration_id: str | None
    seq: int
    t: float
    outcome: Literal["PERMIT", "CLAMP", "VETO", "SAFE_STATE"]
    fault: str | None           # from the taxonomy
    clamped_envelope: bytes | None
    prev_hash: str
    mac: str                    # enforcement key — different from policy key
```

### Passivation and reintegration

After VETO or SAFE_STATE, recovery is **not** automatic. Requires a fresh
declaration plus an explicit acknowledgment record. That asymmetry is deliberate
and it's the part people omit when they copy the pattern — implement it.

**It is implemented, and it is implemented here and nowhere else.**
`reg.enforce.Acknowledgment` is signed with the enforcement key, names the
`verdict_id` that passivated rather than just the fault, refuses a second
acknowledgment of the same passivation, and refuses a pre-emptive one outright;
`Enforcer.acknowledge` and a fresh accepted declaration are both required, and
either alone resumes nothing. That is the mechanism, and it is Phase 4's
deliverable.

**What it does not do is reach an artifact, and Phase 5 onwards does not carry
it.** There is no acknowledgment table, no edge type and no query for one, and
`graph.build` *refuses* a record stream containing one — twice, deliberately, and
pinned by `tests/test_graph.py`. So a passivation is auditable after the fact and
its *clearing* is not: the run's own enforcer knew who acknowledged it and why,
and the file that outlives the run does not. Issue #112 is where that changes, and
it changes what Claim 4 claims — a schema change, a new edge type, a query, a
fixture and a re-measurement. See [`docs/lossiness.md`](lossiness.md) *Retained*
#7, which states the same gap, and `README.md`'s Claim 4 row, which is worded to
agree with both.

**Deliverable:** verdict stream, and a scenario where the `declared_violation` run
produces a clean CLAMP with a named fault.

---

## Phase 5 — Evidence graph

**Goal:** a temporal graph capturing relationships, declarations, and verdicts —
not raw state.

### Schema

**Nodes**

| Type | Fields |
|---|---|
| ~~`Timestep`~~ | ~~`t`, `frame_id`~~ — **dropped, issue #29.** Every edge already carries `t_start`/`t_end`; a node per instant was a second and denser representation of time, one row per frame, and nothing in Phase 7's query set reads it. See [`docs/lossiness.md`](lossiness.md) *Discarded* #10 |
| `node` | `node_key`, `node_id` — **added, issue #55.** Not a node kind: the identity table. The readable identifier of every node of every kind is stored here once, and the INTEGER `node_key` is what each payload row is keyed on and what every join and index below carries. The `*_id` columns in the rows that follow name the identifier a reader still gets from `reg.store`; the *column* is `node.node_id`. A storage decision — the identifiers, the reports that cite them and the answers are unchanged |
| `Envelope` | `envelope_id`, `area`, `geometry_wkb`, `horizon`, `source` (`computed` / `declared` / `clamped`), `envelope_hash` (stored as 32 raw bytes since issue #55; hex on the wire) |
| `Entity` | `entity_id`, `kind`, `geometry_wkb` |
| `RobotConfig` | `config_id`, `q`, `qd` (quantized) |
| `Occurrence` | `occurrence_id`, `seq`, `type` (the DSSAD occurrence flag), `layer`, `reason`, `t` (at `occurrence_time_resolution_s`), `date`, `t_utc`, `entity_id`, `value`, `recorder_version` — **added, issue #35.** The event-level layer, additive beside the edges; see [`docs/lossiness.md`](lossiness.md) *The three resolution levels* and [`docs/prior-art.md` §9](prior-art.md). `recorder_version` is the **recorder's** build and envelope digest and was called `sw_version` until issue #109; it is **not** DSSAD's `R157SWIN`, which names the system under investigation and which this project does **not implement** — nothing here has a policy version to bind ([`docs/prior-art.md` §9](prior-art.md)) |
| `Declaration` | as Phase 3 |
| `Verdict` | as Phase 4 |

**Edges** — all carry `t_start`, `t_end`, which is what makes this temporal and
compressible

| Type | Semantics |
|---|---|
| `HAS_ENVELOPE` | RobotConfig → Envelope (was Timestep → Envelope; issue #29) |
| `CONTAINS` / `INTERSECTS` | Envelope → Entity (with `overlap_area`) |
| `SEPARATION` | RobotConfig → Entity (`min_distance`) |
| `CONTACT` | RobotConfig → Entity |
| `DECLARED` | Declaration → Envelope |
| `ADJUDICATED` | Verdict → Declaration |
| `ENFORCED` | Verdict → Envelope (the bound actually applied) |
| `FOLLOWS` | hash chain link between consecutive records |

### The incremental principle — the AIC transfer

Do **not** emit a node per frame. Emit on change; extend `t_end` otherwise.

- Relationship unchanged within tolerance → extend the existing edge
- Quantize hard: distances to cm, areas to 2 sig figs, `shapely.simplify(tolerance)`
- Store envelope geometry only on material change (hash + tolerance)

A robot holding still for 3 seconds at 50Hz should produce ~1 node, not 150. The
compression ratio comes almost entirely from this.

### Lossiness contract — write this BEFORE implementing the graph

`docs/lossiness.md`, kept current:

> **Retained:** topological and metric relationships between the reachable set and
> every entity at cm/10ms resolution; exact timing of relationship transitions;
> every declaration, verdict, and fault with full attribution.
>
> **Discarded:** exact joint trajectories between transitions, sub-cm geometry, raw
> sensor data, anything not affecting a supported query.
>
> **Unanswerable:** exact pose at an arbitrary unsampled instant; anything about
> entities outside the entity set.

Same discipline as reachability pruning in AIC — not compressing, discarding what's
provably irrelevant to the supported question set.

**Deliverable:** `python -m reg.graph build runs/contact.csv --out runs/contact.sqlite
--run-start 2026-08-21T09:00:00Z --unit-id arm-07 --operator-id op-day-shift`

The three identity flags are required and have no default (issue #83); the start
is declared rather than read from a clock, so the deliverable stays
byte-reproducible.

---

## Phase 6 — Chain integrity

**Goal:** tamper-evidence over the record.

Each `Declaration` and `Verdict` carries `prev_hash` (SHA-256 over the canonical
serialization of the previous record) and a `mac` under its own key. Two keys:
policy and enforcement. Verification walks the chain and checks every link and
every MAC.

**This construction has a name and a 1998 paper, and neither is this project's.**
Per-record MAC plus per-record hash link over one canonical preimage is
**Schneier & Kelsey, "Cryptographic Support for Secure Logs on Untrusted
Machines"** (USENIX Security 1998; ACM TISSEC 2(2), 1999) — implemented here
**minus its forward security**, which is a named, deliberate absence
([`docs/limitations.md`](limitations.md) §7) and not an oversight. What this phase
adds to the ancestor is two chains under role-typed keys and a verifier with three
outcomes; nothing cryptographic. The truncation limit is the **truncation attack**
of Ma & Tsudik (2008), and the structural answer — a Merkle history tree, as
deployed in Certificate Transparency — is a Phase 6 design question this plan does
not take. [`docs/prior-art.md`](prior-art.md) §14 and §18 hold the full comparison;
`reg/chain.py`'s header is the authority on what this module does and does not
inherit.

Include a `--tamper` flag that mutates one record in the persisted graph, so
`verify_chain()` visibly fails. That's the demo.

### Honesty note — put this in the README, not a footnote

In this prototype both keys live in the same process. **That demonstrates the
structure of non-repudiation, not non-repudiation.** A real deployment requires the
enforcement key in hardware the policy vendor cannot reach — which is the same
independence argument as the layer separation, one level down. Say this plainly;
the project is more credible for it.

**Deliverable:** `python -m reg.query runs/contact.sqlite --verify-chain`

---

## Phase 7 — Query API (Claims 2 and 4)

Answer from `contact.sqlite` alone. This module must not be able to read the CSV —
enforce it, the same way Layer A is enforced.

### Query set

**Scene queries**

1. `separation_timeline(entity_id)` — min distance over time
2. `first_envelope_intersection(entity_id)` — when the entity first entered the
   reachable set, plus overlap intervals
3. `frames_at_risk(entity_id, threshold)` — intervals exceeding threshold before a
   contact event
4. `reachable_entities(t_start, t_end)` — which entities were ever inside the
   envelope

**Attestation queries**

5. `declared_bound(t)` — what the policy claimed at time t
6. `violations(window)` — every commanded action outside its declared bound, with
   fault code
7. `verdicts(declaration_id)` — what enforcement did and why
8. `verify_chain()` — integrity over the full record

### The money query

`incident_report(t_incident)` — one call, returning the demo sentence as structured
output:

```
At t=12.34s the policy declared envelope D-0891 (area 0.42 m²)
  action_class: reach, horizon 200ms, seq 891
At t=12.41s the commanded action exceeded that envelope by 0.09 m²
  fault: DECLARATION_ACTION_MISMATCH
Enforcement adjudicated V-0891 at t=12.41s
  outcome: CLAMP to declared bound
Human entity human_0 was inside the computed physical envelope
  from t=12.28s to t=12.55s (27 frames)
Chain verified: 4,218 records, 0 breaks
```

**Verification:** for each scenario compute ground truth from the CSV, compare
against graph-derived answers, report agreement within stated quantization
tolerance. Disagreement outside tolerance is a bug.

**Deliverable:** `python -m reg.query runs/contact.sqlite --incident 12.34`

---

## Phase 8 — Benchmarks (Claim 1)

Per scenario:

| Metric | |
|---|---|
| Raw state stream | CSV bytes, and gzipped CSV bytes |
| "Realistic sensor" projection | raw × a stated, conservative multiplier — **label as projection, not measurement** |
| Graph size | sqlite bytes, and gzipped sqlite bytes |
| Ratio | vs. raw and vs. projection |
| Node/edge counts | vs. frame count |
| Declaration/verdict overhead | bytes added by Phases 3–6 |

**Be honest about the projection.** The claim you can actually measure is
graph-vs-logged-state. The terabytes/day figure is imported context, not a result
from this sim.

Also report query wall-clock: graph vs. computing from raw. Secondary argument, but
real.

And across run lengths (issue #30), because Claim 1 is a claim about *scaling*
and six seconds is the one length at which it cannot be tested — a near-constant
schema-and-index cost dominates the artifact there:

| Metric | |
|---|---|
| Ratio vs. run length | one fixture (`reg.scenarios.long_run`) at 300, 1k, 3k, 10k, 30k frames |
| Crossover | the measured length at which the ratio passes 1.0 — or, plainly, that it does not |
| Marginal cost | Δ bytes per frame between two measured lengths, both sides |

**Measured points only.** No fitted curve, and no projected crossover quoted as
if it were measured — the same rule the sensor projection follows.

**Deliverable:** `python -m reg.bench --all --scaling --out bench/results.md`

---

## Phase 9 — Sufficiency boundary (Claim 3)

Tag every edge with the layer(s) it depends on:

- **Layer A (certifiable):** proprioception-derived envelope, declarations,
  verdicts, chain. Sensors with characterizable failure modes.
- **Layer B (uncertifiable):** entity positions — ground truth here, perception in
  a real system.

Then the taxonomy:

| Query | Layer A alone | Needs Layer B | Claim strength |
|---|---|---|---|
| Could the robot have reached (x,y) at time t? | ✅ | | Certifiable |
| Did the policy exceed its declared bound? | ✅ | | Certifiable |
| Was the record tampered with? | ✅ | | Certifiable |
| Was the human inside the reachable set? | | ✅ | Only as strong as perception |
| Did the robot contact the human? | | ✅ | Only as strong as perception |

**The finding:** a volume derived from perception inherits perception's failure
modes. You cannot ground a certifiable envelope in an uncertifiable perceiver. The
layered structure makes explicit which audit claims survive and which are
conditional on the perception stack's own assurance case.

**Note the asymmetry, because it's the interesting result:** every *attestation*
query is Layer A. Whether the policy honored its own declaration is answerable with
certifiable evidence, independent of whether perception was right. That is a
materially stronger claim than anything about the world, and it is exactly what the
black-channel pattern buys.

**Deliverable:** `docs/sufficiency.md`

---

## Phase 10 — Writeup and site piece

### Repo

- `README.md` — thesis in 3 paragraphs, four claims, headline compression number,
  the incident report output, one GIF, how to run
- `docs/standards.md` — the baseline table above, with the two deliberate deviations
- `docs/lossiness.md`
- `docs/sufficiency.md`
- `docs/limitations.md` — inner-approximation sampling, 2D only, ground-truth
  perception, no dynamics, scripted policy, both keys in one process

### GIF

Robot moving, computed envelope overlaid, declared envelope in a second color,
human entering and leaving, and a visible CLAMP event where the two envelopes
diverge. That single image is the whole argument.

### For ernan.dev

**Frame:** *An evidence layer for physical AI.*

Lead paragraph, roughly:

> Robot safety research asks whether a machine will cause harm. Regulated buyers
> ask a different question: when something happens, can you prove what happened?
> ISO 25785-1, the first safety standard for dynamically stable robots, is still a
> committee draft. UL 4600 already established that autonomous systems are
> certified through a structured safety case rather than a test result. Meanwhile
> the EU AI Act is in force, the Product Liability Directive lands in December
> 2026, and the Machinery Regulation in January 2027. The evidence requirement is
> arriving before the standard does.
>
> This prototype takes a pattern from industrial functional safety — IEC 61784-3's
> black channel, where an uncertifiable transport is declared out of scope and all
> assurance moves to the endpoints — and applies it to a learned control policy.
> The policy stays arbitrarily capable and uncertified. A bounded enforcement layer
> independently verifies what it declared it would do, and every exchange lands in
> a queryable, tamper-evident record cheap enough to keep for the mandated
> retention window and self-contained enough to check with no service still
> running.

Then: the headline compression number. The incident report block. The GIF. Link to
repo. A short "what this doesn't do" section — that one earns more credibility than
anything else on the page.

**Tone:** a position paper with a working implementation attached, not a product.

---

## Build order

| Milestone | Phases | Ship-worthy? |
|---|---|---|
| **1** | 1, 2, 5 (basic), 8 (compression only) | Yes — "here's a compression number and a picture" |
| **2** | 7 (scene queries), 8 (full), 9 | Yes — "and here are the audit queries, and here's what they can't tell you" |
| **3** | 3, 4, 6, 7 (attestation queries) | Yes — the demo sentence, end to end |
| **4** | 10 | The site piece |

**Milestone 3 roughly doubles the project.** Milestones 1–2 stand alone as a
complete argument about evidence. Do not start Phase 3 until Milestone 2 ships. If
time runs out, a finished Milestone 2 beats a half-built Milestone 3.

---

## Notes for the implementing agent

- Clarity over performance everywhere. This is a demonstration, not a system.
- **Determinism is non-negotiable.** Seed everything. An audit artifact that isn't
  reproducible isn't an audit artifact.
- **Enforce Layer A / Layer B with types, not convention.** Most important
  structural property in the codebase.
- **Enforce enforcement/policy independence the same way.** `enforce/` must not
  import from `declare/` beyond the dataclass.
- Write the lossiness contract before implementing the graph. It's a design
  constraint, not documentation.
- Scenario fixtures stay small and hand-authored. Randomized scenarios make the
  compression numbers unfalsifiable.
- The scripted policy should be *imperfect on purpose*. A policy that never
  violates its declaration makes Phase 4 undemonstrable.
- When a phase's success criterion is met, commit and stop. Do not gold-plate.
