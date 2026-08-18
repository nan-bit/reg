# Reachability Evidence Graph — prototype plan

**Status:** brainstorm, v2 · captured 2026-08-18 · not yet reconciled against `prior-art.md`

This is the source document for `reg`. It is a brainstorm, not a specification:
where it and `docs/prior-art.md` disagree, prior art wins and this file gets
edited. Phases are cut when research shows they reinvent something with a name.

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
a humanoid are terabytes/day and cannot leave an air-gapped site. A scene graph is
orders of magnitude smaller and may be the only representation you can retain,
export, and hand to an assessor or insurer.

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

Build in order. Each is independently shippable.

### Claim 1 — Compression (the commercial argument)
Graph vs. raw logged state, size ratio, per scenario.
**Success:** 2–4 orders of magnitude, one number, one chart.

### Claim 2 — Query (what makes it evidence, not a log)
Audit questions answered from the graph alone, no access to the original stream.
**Success:** 4 queries returning answers verifiable against held-out ground truth.

### Claim 3 — Sufficiency boundary (the honest one)
Which claims the proprioception-only layer can support, and which depend on an
uncertifiable perceiver.
**Success:** a taxonomy with worked examples of each.

### Claim 4 — Attestation (the differentiating one)
Declaration, independent verification, verdict, tamper-evident chain.
**Success:** the demo sentence answered end to end, as one query.

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

**Independence is the mechanism.** The enforcement layer computes its own envelope
from proprioception and never trusts the declared one. In the code, enforcement
must not import from `declare/` beyond the dataclass. This mirrors the argument
that a constraint layer supplied by the same party as the policy has common-cause
failure with it.

### The fault taxonomy — the core contribution

The 61784-3 pattern applied to semantics rather than transport.

| Fault | Detection | Response |
|---|---|---|
| **No declaration** | Actuation with no open valid declaration | VETO |
| **Stale declaration** | `t_now > t_issued + horizon` | VETO, require re-declaration |
| **Declaration/action mismatch** | Commanded action outside the declared envelope | CLAMP to declared bound |
| **Envelope overclaim** | Declared envelope exceeds the independently computed physical bound | VETO the declaration itself |
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
| `Envelope` | `envelope_id`, `area`, `geometry_wkb`, `horizon`, `source` (`computed` / `declared` / `clamped`) |
| `Entity` | `entity_id`, `kind`, `geometry_wkb` |
| `RobotConfig` | `config_id`, `q`, `qd` (quantized) |
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

**Deliverable:** `python -m reg.graph build runs/contact.csv --out runs/contact.sqlite`

---

## Phase 6 — Chain integrity

**Goal:** tamper-evidence over the record.

Each `Declaration` and `Verdict` carries `prev_hash` (SHA-256 over the canonical
serialization of the previous record) and a `mac` under its own key. Two keys:
policy and enforcement. Verification walks the chain and checks every link and
every MAC.

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

**Deliverable:** `python -m reg.bench --all --out bench/results.md`

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
> a queryable, tamper-evident record small enough to leave an air-gapped site.

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
