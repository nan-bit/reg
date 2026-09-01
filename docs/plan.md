# Reachability Evidence Graph — prototype plan

**Status:** the source document for `reg` — the claims, the phases and the
non-goals · **not** the source of the retention figures since 2026-08-31; Claim 1
states them and [`retention.md`](retention.md) measures them · captured
2026-08-18 and amended in place since, each
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
summary in [`README.md`](../README.md) presents them in argument order. Claim 1
is the one that is short here on purpose — it states the claim and the conditions
that travel with its figures, and its measurement record is
[`retention.md`](retention.md).

Each is independently shippable.

### Claim 1 — Retention (what it costs to keep, and why that is a supporting claim)

**The measurements, the arithmetic behind them and the record of how the figures
moved are in [`retention.md`](retention.md).** They were this section until
2026-08-31 and nothing about them changed in the move; what is left here is the
claim itself and the conditions a reader has to carry away with any figure from
it.

**What it supports.** An attestation you cannot afford to keep until the claim is
filed is worthless, so retention is the enabling condition for Claim 4 rather
than a rival to it. The property the rest of the argument needs is *cheap enough
to keep for the mandated window* — not *smaller than the alternative by the
largest available factor*. That distinction is why this is named Retention and no
longer Compression: a ratio is a comparison against a counterfactual, and an
absolute cost against a legal retention floor is a fact about a budget.

**Success, as originally stated:** 2–4 orders of magnitude, one number, one
chart. **As it should be stated now:** at occurrence resolution the artifact
costs **264 GB** per robot for the six-month window, which is **~691x** below an
assumed **182.5 TB** raw sensor log over the same period. Two orders, not three,
and never four — the ratio is linear in the assumed sensor rate, and
[`sensor-baseline.md`](sensor-baseline.md) is blunt about what that buys. That
sentence is the claim; the criteria a *figure* has to meet before it may be
published under it — three live, and a fourth kept for the record — are
[`retention.md`](retention.md), *Success, restated*.

**That coarsest level is 98.5% attestation records, and the figure means nothing
without it** (issue #116). 3,120 of its 3,166 node rows are declarations and
verdicts, against 42 occurrences: no resolution level coarsens a per-action
record, so 264 GB is the price of retaining **attestation**, not the price of a
DSSAD-equivalent event log. The level was labelled *DSSAD-shaped* until #116,
which was true of 1.3% of the rows and of 100% of the reader's impression.
Quoting "at occurrence resolution" without the composition reinstates exactly
that reading. The label, the two rejected alternatives and what the choice
commits this project to are in [`retention.md`](retention.md), *What the coarsest
level actually holds*.

**And 264 GB is derived, not measured.** It is the measured **60.29 MB/h** — at
the **50 Hz** control rate `reg.scenarios.DEFAULT_DT` runs at, and linear in it —
times the 4,380 hours in the 182.5-day retention floor. `bytes/hour` is itself
`size × 3600 / run seconds` over a 59.98-second run, so the artifact's fixed
schema-and-index cost is scaled to an hour alongside its per-frame cost and the
hourly rate is an **over**statement — by most at the coarsest level, where that
fixed term is the largest share of the file. `reg.bench` carries that sentence in
every report shape that prints a `bytes/hour` figure; it is carried here for the
same reason, because this is where the derived total is led with.

**The artifact side is measured; the sensor side is a projection.** The
multiplier is an assumption with a sourced range — **1 TB/day** — and
`reg.bench --sensor-multiplier` has no default, so it is always stated rather
than inherited. `reg` has no sensors and nothing here can measure one.

**The mandated window, and the law that is not this section's to price**
(issue #101). The EU AI Act sets the six-month floor in **Article 19** for
providers and **Article 26(6)** for deployers; Article 12 is record-keeping and
sets no period. Both Articles set that period *"unless provided otherwise in
applicable Union or national law, **in particular Union law on the protection of
personal data**"*. The artifact contains personal data: `meta[operator_id]` with
`meta[run_start_utc]` selects a shift, and the Layer B edges record how close a
human came to a machine, to the centimetre, all shift. So for that half of the
file six months may be a **ceiling** rather than a floor. Every figure published
under this claim is what it costs to keep the artifact for the mandated window;
none of them is a claim that keeping it for that window is permitted. The
entry — with Art. 26(7) and the DPIA obligation named, and no claim of
compliance — is [`docs/limitations.md` §8](limitations.md).

**Two conditions that travel with the comparison figures wherever they are
quoted.** The original framing — is the graph smaller than the stream it
replaces — is answered **no**, and both of the numbers that answer it carry a
condition that is part of the number:

- A **13x** figure appears in that comparison measured on a build holding **no
  declaration, verdict, fault or chain record at all** — no Layer A. The current
  build carries all of it and the figure is **~40x**. Quoting 13x without the
  condition quotes a different artifact.
- The gzipped state CSV is **not what practitioners retain**. Against
  **rosbag2/MCAP**, the incumbent, the same proprioceptive content costs
  **2.51x** what the gzipped CSV does — and that is a **hand-built encoding
  comparison and not a real bag**, which [`sensor-baseline.md`](sensor-baseline.md)
  requires be said wherever the figure is quoted until issue #117 retires it. So
  the artifact's disadvantage against a real bag is smaller than the figure
  suggests; by how much is not measured, because the two comparisons do not carry
  the same content.

**And the prohibition those two conditions imply, stated as a rule here because
code cites it as one.** *Nothing in this repository may quote a compression ratio
as the commercial argument while the measured one is below 1.* `reg.bench` refuses
to carry such a column at all and prints `bytes/hour` instead — a column nobody is
allowed to quote is a column that gets quoted — and it says why wherever it does
so. Five sites name this claim as the authority: four in `reg/bench.py`, one of
which reaches the emitted report, and one in `tests/test_bench.py`. The rule is
stated here so that following any of them lands on it.

*Two wordings, one object.* Those sites say "against the CSV" and "against the
stream" in roughly equal numbers. They mean the same thing — the gzipped copy of
the simulator's own raw state CSV, 24 columns and 19 of them Layer B — and the
rule above is deliberately stated without either name, so that it does not have
to be restated when one of them is settled on. What replaces the ratio —
resolution as the measured variable — is [`retention.md`](retention.md),
*What replaces it*.

**Every figure under this claim is a fixed-base-arm figure at 50 Hz.** Both
halves move it: the control rate because enforcement emits a verdict and a chain
record per commanded action, and the robot model because the artifact's contents
are a function of what it records about the machine. The rate is measured at four
rungs in [`retention.md`](retention.md), *The control rate*; the rate ceiling
above which the time base can no longer place a frame is
[`limitations.md` §5](limitations.md).

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
`horizon_bound(state, limits, window, substep_dt)` is the radius a declared
region is tested against, and it is the smaller of two sound bounds: the
workspace disc `sum(link_lengths) + link_radius`, which reads no `q`, no `q̇`
and no horizon; and the radial projection of `reg.envelope.outer_envelope`, a
horizon-limited **outer** reachable set — the joint box pushed through the
forward kinematics as an interval — which reads all three. Both over-cover, so
nothing inside is ever falsely accused.

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
window, substep_dt)`, the smaller of two bounds that each over-cover:

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
  the incident report output, how to run
- `docs/standards.md` — the baseline table above, with the two deliberate deviations
- `docs/lossiness.md`
- `docs/sufficiency.md`
- `docs/limitations.md` — inner-approximation sampling, 2D only, ground-truth
  perception, no dynamics, scripted policy, both keys in one process

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

Then: the headline compression number. The incident report block. Link to
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
