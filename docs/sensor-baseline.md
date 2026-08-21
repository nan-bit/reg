# The sensor-log baseline

**Status: an assumption with a sourced range, not a measurement.** Written
2026-08-19, because the sensor rate is the one input the benchmark cannot produce
and the first thing a robotics safety reader will check. **The artifact sizes it
is applied to were re-measured 2026-08-20 (issue #60) and every figure below is
from that run; the sensor assumption itself is unchanged and was not permitted to
move.** It is an input with a sourced range, and choosing the value that makes
the conclusion come out is the failure this document exists to prevent — so the
multiplier stayed at 1 TB/day and the *conclusion* moved instead. See
[Sensitivity](#sensitivity).

**The artifact side gained a second variable on 2026-08-21 (issue #68): the
robot's own control rate.** Every artifact size in this document was measured at
50 Hz and every one of them is linear in that rate, because enforcement emits a
verdict and a chain record per commanded action. A real manipulator loop runs at
1 kHz. That is measured now too, in [The control rate](#the-control-rate), and
it moved the conclusion a second time — the multiplier, a second time, did not.

`docs/plan.md` Claim 1 compares the artifact against a raw sensor log at
**1 TB/day**. `reg` has no sensors. Nothing in this repository measures, or can
measure, that figure — the simulator emits a nine-float proprioception stream and
that is the whole of its input. Every comparison against a sensor log is therefore
a **projection**, and this document is what it is projected from.

The benchmark enforces the distinction in code rather than in prose:
`--sensor-multiplier` has **no default**. Omit it and the report prints the
measured columns and says the sensor comparison was not computed. There is no
value of the flag that makes the output claim to have measured a robot.

## What is actually published

| | |
|---|---|
| **Assumed** | 1 TB/day of raw sensor log, continuous |
| **Sourced range** | ~0.02 – 21 TB/day depending on sensor suite and duty cycle |
| **Where 1 TB/day sits in it** | low end — below every cited continuous-logging configuration |
| **Retention window** | 182.5 days (EU AI Act six-month floor: Art. 19 providers, Art. 26(6) deployers — *not* Art. 12, which sets no period) |
| **Implied continuous rate** | 11.6 MB/s over 24 h, or 34.7 MB/s over an 8-hour shift |
| **Robot control rate the artifact sizes assume** | 50 Hz (`reg.scenarios.DEFAULT_DT`). **Measured**, not assumed, at 100/250/1000 Hz too — [The control rate](#the-control-rate) |

## Sources

The most precise published figure found is a range, not a point:

> "Embodied AI data traffic can range from about **800 B/s** for motion-only data
> to **246 MB/s** depending on sensor configuration; one RGB-D teleoperation setup
> reports about **185 MB/s** throughput."
>
> — *Data Standards for Humanoid Robotics: The Missing Infrastructure for Physical
> AI*, arXiv:2606.19769

Converted to daily volumes:

| rate | 24 h | 8-hour shift |
|---|---|---|
| 800 B/s (motion only — roughly what `reg` logs) | 0.07 GB | 0.02 GB |
| 185 MB/s (RGB-D teleoperation) | 16.0 TB | 5.3 TB |
| 246 MB/s (upper configuration) | 21.3 TB | 7.1 TB |

A second anchor, from the other direction — a real collected dataset:
**HIW-500** is 10 TB over 500 hours across 12 homes, which is ~20 GB/hour, or
~0.5 TB over a 24-hour day. That is far below the teleoperation figure because it
is **compressed, curated episode data rather than a continuous raw log** — the
distinction that matters most here, and the reason the range spans three orders
of magnitude.

For scale from the adjacent regulated industry, automotive: a production
autonomous vehicle is widely quoted at 1.4–19 TB/hour, and development vehicles
higher still. Those figures are an order of magnitude above the humanoid ones and
are **not** used in any `reg` projection; they are recorded here only so nobody
reads 1 TB/day as aggressive.

Sources:
- [Data Standards for Humanoid Robotics (arXiv:2606.19769)](https://arxiv.org/html/2606.19769)
- [Humanoid Everyday (arXiv:2510.08807)](https://arxiv.org/html/2510.08807v1)
- [BitRobot / Hugging Face HIW-500 dataset](https://www.humanoidsdaily.com/news/bitrobot-and-hugging-face-drop-hiw-500-a-massive-10tb-real-home-humanoid-dataset)
- [The Robotic Data Pipeline: Sensors to Training Datasets](https://www.trossenrobotics.com/post/robotic-data-pipeline-sensor-streams-to-training-datasets)
- [The Data Deluge: AV data volumes (Siemens Polarion)](https://blogs.sw.siemens.com/polarion/the-data-deluge-what-do-we-do-with-the-data-generated-by-avs/)

**Honest characterisation of these sources.** One arXiv preprint with a range and
no sensor configuration attached to its endpoints; one dataset size that has to be
divided by hours to become a rate; two industry blog posts. None is a measurement
of a fielded humanoid logging continuously for six months, because that robot is
not deployed and that log does not exist yet. This is the state of the evidence,
and the argument is built to survive it — see the sensitivity below.

## Sensitivity

The ratio is **linear in the assumed rate**, so the assumption never hides: halve
the rate and every ratio halves.

The artifact sizes below are **measured**, from one execution of
`python -m reg.bench --resolution --seed 0` on 2026-08-20 (issue #60):
`long_run` at 3,000 frames **at a 50 Hz control rate**, 16 envelope samples,
200 ms horizon, 1.0 s occurrence
resolution, 0.5 s replan interval and declaration horizon, 1.0 s watchdog. Each
size is that level's measured `bytes/hour` — 60.05, 149.47 and 217.32 MB/h —
times the 4,380 hours in the retention floor. The control rate is not a detail
of the fixture: every one of those three figures is **linear in it**, and
[The control rate](#the-control-rate) below is the measurement of that. They are **much larger than the
provisional figures they replace**, because those measured an artifact holding no
Layer A record at all (issue #59): occurrence went 18.9 GB → 263 GB, transition
229.7 → 655 GB, per-frame 589.3 → 952 GB. What the sensitivity establishes is
*the shape of the dependence*, which did not change when the sizes did — but the
conclusion drawn from it did, and the two paragraphs after the crossover table
are where.

| sensor rate | log at 6 months | vs occurrence (263 GB) | vs transition (655 GB) | vs per-frame (952 GB) |
|---|---|---|---|---|
| 0.1 TB/day | 18.2 TB | 69x | 28x | 19x |
| 0.5 TB/day | 91.2 TB | 347x | 139x | 96x |
| **1 TB/day (published)** | **182.5 TB** | **694x** | **279x** | **192x** |
| 5 TB/day | 912.5 TB | 3,470x | 1,394x | 959x |
| 21.3 TB/day (cited max) | 3,887 TB | 14,780x | 5,938x | 4,084x |

**What survives the whole range and what does not.** The crossovers are
**derived, not measured** — `threshold_TB_per_day = size_GB * 10^orders / 1000 /
182.5`, so occurrence at two orders is `263 * 100 / 1000 / 182.5 = 0.144` — and
they are recomputed from the sizes above rather than carried over:

| level | clears 2 orders above | clears 3 orders above |
|---|---|---|
| occurrence | 0.144 TB/day | 1.441 TB/day |
| transition | 0.359 TB/day | 3.587 TB/day |
| per-frame | 0.522 TB/day | 5.216 TB/day |

At occurrence resolution the claim clears **two** orders of magnitude at any
sensor rate above 0.144 TB/day — seven times lower than the published
assumption, and below every cited configuration that carries a camera, including
HIW-500's compressed ~0.5 TB/day. A motion-only stream at 800 B/s is 0.07 GB/day
and clears nothing, which was equally true of the provisional figures. So the
two-order conclusion still does not depend on the assumption being right to
within a factor of a few.

**Three orders now needs 1.44 TB/day, which the published assumption does not
reach.** Before Layer A was measured this threshold sat at 0.104 TB/day and the
assumption cleared it tenfold. That is the single largest change this
re-measurement made to the argument, and it is a change in the conclusion, not
in the input: the multiplier is the same 1 TB/day it was, for the same sourced
reasons.

At the finer levels it is weaker still. **Per-frame retention clears the plan's
two-order criterion only above ~0.52 TB/day, and transition only above
~0.36 TB/day** — both within a factor of three of the published assumption, so
neither has the margin to survive the assumption being wrong by an order of
magnitude. Below those rates the artifact is still smaller than the log, but not
by the margin Claim 1 asserts. And the plan's *upper* bound — four orders — is
reached at occurrence resolution only above 14.4 TB/day, which is inside the
cited range but far above the published assumption, so it is not available at
all and must not be quoted.

So **the claim should be stated at occurrence resolution and at two orders** —
not two-to-three, and never four. That is also the level the only mandated
evidence recorder in existence (UN R157 DSSAD, ±1.0 s) actually operates at — the
robust claim and the regulated one are the same claim, which is convenient rather
than coincidental.

**Why coarsening buys so much less than it did.** The occurrence level is no
longer mostly geometry. The declaration, verdict and chain records are emitted
per action and no resolution level coarsens them, so at ±1 s they are 3,120 of
the artifact's 3,166 node rows — the level is now dominated by a Layer A cost that
resolution does not touch. Coarsening the *scene* still works; it just has less
left to work on.

## The control rate

**Status: measured, on the artifact side, 2026-08-21 (issue #68).** Everything
above this heading holds the *sensor* rate as the variable and the artifact
sizes as fixed. They are not fixed. They are **linear in the robot's control
rate**, which no document in this repository named until this section, and the
rate this simulator runs at is not the rate a manipulator runs at.

**Why the artifact scales with it at all.** Enforcement adjudicates every
commanded action, so it emits one verdict and one chain record **per control
step**, and no resolution level coarsens a record (that is what issue #59
established, and it is why the occurrence level is 3,120 of 3,166 node rows at
50 Hz). The policy's declarations do *not* scale — it replans on a wall-clock
interval — so the verdict layer is the whole of the growth.

**Measured**, from one execution of
`python -m reg.bench --control-rate-hz 50,100,250,1000 --seed 0`: the resolution
curve at four control rates over **one fixed run duration**, 59.98 s of robot
time, at one seed, 16 envelope samples, 200 ms horizon, 1.0 s occurrence
resolution, 0.5 s replan interval and declaration horizon, 1.0 s watchdog. The
frame count moves with the rate because it must — 3,000 frames at 50 Hz, 59,981
at 1 kHz — and everything else is held still, so the only thing that differs
between two rows is how often the robot acted. The 50 Hz row reproduces the
published curve exactly, which is what makes the other three comparable to it.

| control rate | frames | records retained | occurrence | transition | per-frame |
|---|---|---|---|---|---|
| **50 Hz (published above)** | 3,000 | 3,120 | **60.05 MB/h** | 149.47 MB/h | 217.32 MB/h |
| 100 Hz | 5,999 | 6,119 | 106.14 MB/h | 245.96 MB/h | 409.33 MB/h |
| 250 Hz | 14,996 | 15,116 | 246.70 MB/h | 527.82 MB/h | 1.04 GB/h |
| **1 kHz (a real manipulator)** | 59,981 | 60,101 | **950.55 MB/h** | 1.94 GB/h | 4.26 GB/h |
| *x, 50 Hz → 1 kHz* | *20.0x* | *19.3x* | *15.8x* | *13.0x* | *19.6x* |

Those are measured points. **Nothing between them is interpolated and nothing
beyond them is extrapolated** — a rate nobody ran is not in the table, however
obvious it would look on a line through the ones that are.

The growth is **sublinear**: 15.8x at the occurrence level for a 20x rate
increase, because the scene rows and the fixed schema-and-index cost do not
scale with the rate. Only the record layer does, and by 1 kHz it is 60,101 of
that level's 60,572 node rows — 99.2%, against 98.5% at 50 Hz. The level is
almost entirely a per-action attestation stream, and that is what the rate buys
and what a cadence change would cut.

### What it does to the claim

The same arithmetic as the sensitivity above — that figure times the 4,380 hours
in the retention floor, against the **unchanged** 182.5 TB assumption:

| control rate | occurrence, 6 months | vs 182.5 TB | transition | vs | per-frame | vs |
|---|---|---|---|---|---|---|
| **50 Hz** | **263 GB** | **~694x** | 655 GB | ~279x | 952 GB | ~192x |
| 100 Hz | 465 GB | ~393x | 1.08 TB | ~169x | 1.79 TB | ~102x |
| 250 Hz | 1.08 TB | ~169x | 2.31 TB | ~79x | 4.56 TB | ~40x |
| **1 kHz** | **4.16 TB** | **~44x** | 8.49 TB | ~22x | 18.65 TB | ~10x |

**At 1 kHz the claim is below two orders of magnitude, and this document says so
rather than repairing it.** ~44x at occurrence resolution is **one** order, not
two. The two-order band is still occupied at 250 Hz (~169x) and is gone by
1 kHz; where between those two it goes was not measured and is therefore not
quoted. Every finer level is worse: transition is ~22x and per-frame ~10x at
1 kHz.

**The sensor assumption was not adjusted to compensate.** It is the same
1 TB/day it has been since this document was written, for the same sourced
reasons. This is the second time the measurement has moved and the assumption
has not — the first was issue #60, when Layer A entered the artifact and three
orders stopped being available — and it is the discipline the document exists
for: the input has a range and the conclusion is what moves.

**An outside estimate, checked.** Issue #68 arrived with a reviewer's estimate of
~5.1 TB per robot per six months at 1 kHz, i.e. ~36x, flagged explicitly as
unverified. The measured figures are 4.16 TB and ~44x. The estimate was
directionally right and slightly pessimistic, for the reason above: it assumed
the whole level scales, and 1.5% of it does not.

**What is out of scope here.** Declaring per behaviour segment rather than per
control step would cut the term that scales, and this measurement shows it is
the dominant lever — the verdict layer is essentially all of the growth. It is a
change to the attestation cadence and is held pending its own decision.

**One caveat that is not about cost.** At 250 Hz and 1 kHz the transition and
per-frame levels return `DISAGREE` on `separation_timeline`. The edge layer's
endpoints are quantized to `TIME_TOL_S` = 0.01 s, which is coarser than the
control period above 100 Hz, so a per-frame separation read back out of an
interval can miss by more than `DISTANCE_TOL_M`. That is a property of the graph
builder rather than of retention, it is reported rather than tuned away, and it
means a 1 kHz robot does not get the finer levels' full answer even after paying
for them.

## What would retire this document

A measured figure from a fielded humanoid — sensor manifest, sample rates, codec,
duty cycle, and a logged byte count over a known interval. Until then the honest
form is the one used throughout: an explicit multiplier, a linear sensitivity, and
the word *projection* on every number derived from it.

That would retire the *sensor* side. The control rate is the other half and is
already retired as an assumption: it is measured, and the figure a reader needs
is the rate their robot's constraint layer actually adjudicates at.

## See also

- [`plan.md`](plan.md) Claim 1 — where the projection is quoted
- [`lossiness.md`](lossiness.md) — the three resolution levels being priced
- [`prior-art.md`](prior-art.md) §8 — why the artifact loses to a float codec, and
  why that is not this comparison
- `python -m reg.bench --control-rate-hz 50,100,250,1000 --seed 0` — the command
  that produces the control-rate table, and `--resolution` for the curve at one
  rate. Neither flag has a default rate to fall back on
