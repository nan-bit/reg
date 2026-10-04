# Retention — what it costs to keep the artifact

**What is machine-checked here is less than the whole file.**
`tests/test_published_figures.py` re-derives four things from the code on every
CI run: the control-rate ladder's **50 Hz row**, the coarsest level's **label**
and the record and node counts behind it, the **byte attribution**, and the
**Layer-A comparison** table.

Everything else is prose or arithmetic over those, `267 GB` among them; that
module's own *What this does not cover* is the authority on the boundary, and
this line exists so that nothing here reads as guaranteed when it is not.

**The artifact side of every figure here is measured on the fixed-base planar
arm** — 2–3 revolute links, base at the origin. That is a condition on all of
them, and moving the robot would move all of them. The **control rate** is not a
single condition in the same way: the resolution table below is at the 50 Hz
`reg.scenarios.DEFAULT_DT` runs at, and *The control rate* measures the same
curve at 100 Hz, 250 Hz and 1 kHz. Every table says which rate it is at.

---

Per robot, from the measured resolution curve:

> **Measured 2026-08-20 (issue #60).** `python -m reg.bench --resolution
> --seed 0` — `long_run` at 3,000 frames (60.0 s of robot time) at a **50 Hz**
> control rate, 16 envelope samples, 200 ms horizon, 1.0 s occurrence
> resolution, 0.5 s replan interval and declaration horizon, 1.0 s watchdog.

| retained at | per robot, 6 months | fleet of 100 |
|---|---|---|
| **occurrence (±1 s) — 98.5% attestation records** | **267 GB** | 26.7 TB |
| transition (10 ms) | 838 GB | 83.8 TB |
| per-frame (10 ms) | 1,293 GB | 129.3 TB |
| *raw sensor log @ 1 TB/day (assumed, **not measured here**)* | *182.5 TB* | *18.2 PB* |

Each is the measured `bytes/hour` for that level — 61.15, 191.70 and
295.44 MB/h at **50 Hz** — times the 4,380 hours in the 182.5-day retention
floor. Every one of those three figures **moves with that rate**: enforcement
emits one verdict and one chain record per commanded action and no resolution
level coarsens them.

At occurrence resolution the artifact is **~684x smaller** than the sensor
stream over the mandated retention period — two orders of magnitude, and
**short of three**. The artifact side of that comparison is
measured. The sensor side is an **assumption with a sourced range**, set out in
[`sensor-baseline.md`](sensor-baseline.md) with its citations and a sensitivity
table; `reg.bench --sensor-multiplier` has no default, so the multiplier is
always stated rather than assumed.

**State it at two orders, not three, and never four.** The ratio is linear in
the assumed sensor rate; [`sensor-baseline.md`](sensor-baseline.md) carries the
sensitivity analysis. It is also the resolution the only mandated evidence
recorder in existence operates at (UN R157 DSSAD, ±1.0 s).

## What the coarsest level actually holds, and what it is therefore called

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

The level is therefore called **occurrence (±1 s) — 98.5% attestation records**:
a per-action attestation record whose coarsest view keeps a DSSAD-**aligned**
occurrence layer.

## The control rate — and it is not two orders at 1 kHz

> **Measured 2026-08-21 (issue #68), re-measured 2026-09-08 (issue #252).**
> `python -m reg.bench --control-rate-hz
> 50,100,250,1000 --seed 0`: the resolution curve at four control rates over one
> fixed run duration (59.98 s of robot time), same seed, same envelope
> parameters, same record parameterization. The 50 Hz row is the published curve
> above, reproduced byte for byte, which is what makes the other three
> comparable to it. Measured points only — nothing here is fitted or
> extrapolated.

Every figure in the resolution table above is a figure **at 50 Hz** and every one
of them **moves with that rate**, because enforcement emits one verdict and one
chain record per commanded action and no resolution level coarsens them. A real
manipulator control loop runs at 1 kHz, twenty times this simulator's rate:

| control rate | occurrence | transition | per-frame |
|---|---|---|---|
| **50 Hz (this simulator, published above)** | **61.15 MB/h → 267 GB → ~684x** | 191.70 MB/h → 838 GB → ~218x | 295.44 MB/h → 1,293 GB → ~141x |
| 100 Hz | 107.00 MB/h → 469 GB → ~389x | 314.74 MB/h → 1.38 TB → ~132x | 563.22 MB/h → 2.47 TB → ~74x |
| 250 Hz | 247.75 MB/h → 1.09 TB → ~167x | 676.31 MB/h → 2.96 TB → ~62x | 1.47 GB/h → 6.42 TB → ~28x |
| **1 kHz (a real manipulator)** | **1.08 GB/h → 4.72 TB → ~39x** | 2.64 GB/h → 11.57 TB → ~16x | 6.51 GB/h → 28.53 TB → ~6x |

The `MB/h` column is measured. The six-month size is that figure times the 4,380
hours in the retention floor, and the ratio is against the **assumed** 182.5 TB
sensor log — an assumption, unchanged, at 1 TB/day
([`sensor-baseline.md`](sensor-baseline.md)).

**Two rungs sit above the artifact's declared domain of validity.**
`reg.tolerances.TIME_BASE_MAX_RATE_HZ` is 100 Hz ([`limitations.md`](limitations.md) §5);
the 250 Hz and 1 kHz rows are real retention costs a real manipulator pays, but
not rates at which every per-frame query answers inside its published tolerance.
Only the 50 Hz row is pinned — re-measured from the code on every CI run
(`tests/test_published_figures.py`); the rest are manual measurements, dated and
commanded in the blockquote above.

**So the two-order claim is a claim about the control rate as well as about the
sensor rate, and at 1 kHz it does not hold**: at occurrence resolution a 1 kHz
robot retains **4.72 TB** for the mandated six months — **~39x** below the
assumed sensor log, one order of magnitude, not two.

**How to state Claim 1 now.** *At occurrence resolution, two orders of magnitude
at a 50 Hz control rate and one at 1 kHz — the first pinned, the second a manual
measurement at a rate above the artifact's time base
([`limitations.md`](limitations.md) §5).*
Encoding does not move it; resolution does.

## Why the growth is sublinear

The growth is **sublinear** — 17.7x for a 20x rate increase — because the term
that carries it is the `declaration` table, which the record's earlier account
did not name (issue #116).

Bytes per table, from SQLite's own `dbstat`, on the **50 Hz** rung of the ladder
above — which is the published curve, so this attributes the very artifact
Claim 1 prices:

| table, coarsest level at 50 Hz | bytes | share of the level |
|---|---|---|
| `verdict` | 551,936 | 54.2% |
| `declaration` | 185,344 | 18.2% |
| `indexes + schema` | 139,264 | 13.7% |
| `node` | 112,640 | 11.1% |
| `meta` | 12,288 | 1.2% |
| `occurrence` | 9,216 | 0.9% |
| `entity` | 3,072 | 0.3% |
| `envelope`, `robot_config`, `acknowledgment`, `edge`, `edge_layer_basis` — one empty page each | 5,120 | 0.5% |
| **file** | **1,018,880** | |

*`acknowledgment` arrives with schema 12 and `edge_layer_basis` with schema 13;
`long_run` passivates never and this level holds no edge, so each is one empty
page.*

**This is a purchasing decision, not a slogan.** 267 GB buys *did contact
occur*, *how close did it come*, every refused action with its fault code and
the declaration it was raised against, and both hash chains walked end to end.
It also buys *when* — **for events sustained longer than its one-second
quantum**; a brief minimum it refuses rather than misplaces, and whether a
coarse timestamp is enough is a property of the event, not of the recorder. 838
GB buys *when exactly* for an event of any length, the full separation timeline,
and the region each declaration claimed and each clamp actually applied — which
±1 s does not hold, so `declared_bound` and `verdicts` come back
`COULD-NOT-EVALUATE` there. The resolution curve prices evidence per audit
question, and that is the commercial argument in its useful form.

## The scaling bound

**What was measured** (`python -m reg.bench --scaling --scaling-frames
300,3000 --seed 0 --out <path>`, re-measured 2026-09-12 for issue #273;
long-run fixture, 16 envelope samples, 200 ms horizon, no record stream at
either rung — a size comparison against the raw stream, holding no Layer A).
No ratio is published from it: the Layer-A **~51x** below carries the claim,
being the harsher comparison and the one `tests/test_published_figures.py`
re-measures every run.

| frames | robot time | x gz CSV |
|---|---|---|
| 300 | 6.0 s | 0.05x |
| 3,000 | 60.0 s | 0.06x |

The ratio *does* improve with run length — the fixed schema cost amortises.
**It does not reach 1.0 anywhere in the measured range.** Measured points only:
the ladder holds what was run. **Encoding does not move this number** — two
encoding passes took ~13% off on disk and ~3% compressed — **and the variable
that moves it is resolution.**

### The same comparison, measured on the artifact that carries Layer A

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
| artifact on disk | 3,291,136 B |
| gzipped CSV baseline | 64,652 B |
| x gz CSV | 0.02x |
| how much larger | ~51x |

**That baseline is not the incumbent.** Nobody retains a gzipped CSV;
practitioners retain rosbag2, in MCAP. The five-column rows below are
projections from the MCAP specification ([`sensor-baseline.md`](sensor-baseline.md)),
held to the byte by `tests/test_incumbent_encoding.py`; the 24-column rows are
bags `ros2 bag record` wrote on 2026-09-06, whole files, against the 3,291,136 B
artifact above — both with the Layer B half on `/tf`, the arrangement most
favourable to the incumbent.

| MCAP against a gzipped CSV of the same content | bag | bag / gz CSV | artifact / bag |
|---|---|---|---|
| 5 columns / 251 frames, **projected**, vs 3,053 B — `none` | 35,893 B | **11.76x** | |
| the same, one compressed projection for both zstd profiles | 11,685 B | **3.83x** | |
| 24 columns / 3,000 frames, **measured**, vs 64,652 B — no profile passed | 1,637,963 B | **25.34x** | **2.01x** |
| the same, `zstd_fast` | 360,798 B | **5.58x** | **9.12x** |
| the same, `zstd_small` | 252,034 B | **3.90x** | **13.06x** |

**Beside `~51x` the figure is a pair, and the pair is a range with its ends
named**: the artifact is **9.12x** a `zstd_fast` bag and **13.06x** a
`zstd_small` one, of the same 24 columns of the same run, where `~51x` is against
a gzipped CSV of those same columns ([the sensor baseline](sensor-baseline.md#what-the-projection-is-measured-against)). Each end composes — `50.91x / 5.58x` and
`50.91x / 3.90x` — which a five-column ratio against a 24-column headline could
never do. **If one number is wanted it is 9.12x**, because `zstd_fast` is the
larger bag and so the smaller ratio: the end least flattering to this project.
Quoting either alone is preset-shopping. 2.01x is the same comparison at the
uncompressed default, beside them and not instead of them.

### Success, restated to something a measurement can meet or miss

These are the criteria the *record* is held to — three live — naming what has
to be measured, labelled and reported before a figure
here counts. They are not a second statement of the
claim: how Claim 1 is to be stated in a sentence is
[`plan.md`](plan.md) Claim 1's, and where the two are about the same thing that
one governs.


1. The **absolute retention cost** is measured at each resolution level and
   reported per robot per six months, beside what each level can answer.
2. Any comparison against a sensor log is **labelled a projection**, computed
   from a stated multiplier, and never quoted as a measured ratio.
3. The ratio against the raw stream is reported **across run lengths** as a
   design bound, with the crossover at 1.0 stated or its absence stated. Measured
   points only.
4. *Superseded: until a measured length clears 1.0, the retainable-artifact argument does not rest on compression.*

---

## Why

Nothing below is normative — the rationale for the record above: how the
figures moved, and which shapings arrived as choices rather than findings.
The like-for-like comparison is [`prior-art.md`](prior-art.md) §8; the
resolution argument is [`lossiness.md`](lossiness.md).

### What replaces it

Claim 1 stops being "is the graph smaller than the stream" and becomes "what
does evidence cost per unit of resolution, and how coarse can it get before it
stops answering the question?" The deliverable is one curve with at least three
points — occurrence-level (DSSAD-aligned), transition-level, and the current
per-frame level — reporting for each: bytes/hour, and whether the supported
queries still `AGREE` within their stated tolerance.

## See also

- [`plan.md`](plan.md) Claim 1 — the claim these figures serve, and the
  conditions that travel with each figure wherever it is quoted.
- [`sensor-baseline.md`](sensor-baseline.md) — where the sensor side comes from:
  an assumption with a sourced range, never a measurement, and the sensitivity
  table the ratio's robustness rests on.
- [`lossiness.md`](lossiness.md) — the three resolution levels priced above, and
  what each can still be asked.
- [`limitations.md`](limitations.md) §5 — the rate ceiling above which an
  artifact cannot address every frame of the run it prices. Two rungs above are
  beyond it.
- [`prior-art.md`](prior-art.md) §8 and §16 — the float codec the artifact loses
  to, and the incumbent a bag-shaped baseline would be.
- `python -m reg.bench --resolution --seed 0 --out runs/resolution.md` — the
  command that produces the resolution table; swap `--resolution` for
  `--control-rate-hz 50,100,250,1000` for the ladder. **`--out` is required and
  has no default**, so neither command runs without it — a report that went
  somewhere nobody named is one nobody can check. `--control-rate-hz` has no
  default either; `--seed` does, and is passed explicitly above so the run is
  reproducible from the line as written.
