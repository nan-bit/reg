# The sensor-log baseline

**Status: an assumption with a sourced range, not a measurement.** The sensor
rate is the one input the benchmark cannot produce, so it is stated here with a
source, a range and a sensitivity. The artifact side is measured, at a stated
control rate. Provenance is under [Why](#why).

`docs/plan.md` Claim 1 compares the artifact against a raw sensor log at
**1 TB/day**. `reg` has no sensors, and nothing in this repository measures or
can measure that figure. Every comparison against a sensor log is therefore a
**projection**, and this document is what it is projected from.

## What is actually published

| | |
|---|---|
| **Assumed** | 1 TB/day of raw sensor log, continuous |
| **Sourced range** | ~0.02 – 21 TB/day depending on sensor suite and duty cycle |
| **Where 1 TB/day sits in it** | low end — below every cited continuous-logging configuration |
| **Retention window** | 182.5 days (EU AI Act six-month floor: Art. 19 providers, Art. 26(6) deployers — *not* Art. 12, which sets no period) |
| **Implied continuous rate** | 11.6 MB/s over 24 h, or 34.7 MB/s over an 8-hour shift |
| **Robot control rate the artifact sizes assume** | 50 Hz (`reg.scenarios.DEFAULT_DT`). **Measured**, not assumed, at 100/250/1000 Hz too — [The control rate](#the-control-rate) |

**The multiplier is the input and the conclusion is what moves.** Choosing the
value that makes the conclusion come out is the failure this document exists to
prevent, so the multiplier stays at 1 TB/day and the claim drawn from it is
restated whenever the artifact side is re-measured ([Sensitivity](#sensitivity)).

**Every artifact size here is linear in that control rate**, because enforcement
emits a verdict and a chain record per commanded action. Every size published
above [The control rate](#the-control-rate) is at 50 Hz; that section measures the
rest of the ladder, and states beside each table what the rungs above 100 Hz can
and cannot be asked.

## What the projection is measured against

The simulator emits its own state stream and that is the whole of its input. That
stream is **not** proprioception: for the fixture the benchmark prices it is
**24 columns and 19 of them are Layer B**
(`reg.stream.expected_header(2, 3)`) — `human_x`, `human_y`, `human_vx`,
`human_vy` and each obstacle's `id`, `kind`, `x`, `y`, `r`, beside the five
proprioceptive columns `reg.bench.proprioceptive_columns` returns. Simulator
ground truth for a person is exactly the Layer B content this document projects
rather than measures, so the baseline is small *and* carries the entity state a
real system would have to perceive; see
[The Layer B asymmetry](#the-layer-b-asymmetry).

The benchmark enforces the distinction in code rather than in prose:
`--sensor-multiplier` has **no default**. Omit it and the report prints the
measured columns and says no projection was computed
(`tests/test_bench.py::test_without_a_multiplier_there_is_no_projection_at_all`).
No value of the flag makes the output claim to have measured a robot.

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
~0.5 TB over a 24-hour day. It sits far below the teleoperation figure because it
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
not deployed and that log does not exist yet. The argument is built to survive
that — see the sensitivity below.

## Sensitivity

The ratio is **linear in the assumed rate**, so the assumption never hides: halve
the rate and every ratio halves.

The artifact sizes below are **measured**, from one execution of
`python -m reg.bench --resolution --seed 0`: `long_run` at 3,000 frames **at a
50 Hz control rate**, 16 envelope samples, 200 ms horizon, 1.0 s occurrence
resolution, 0.5 s replan interval and declaration horizon, 1.0 s watchdog. Each
size is that level's measured `bytes/hour` — 60.42, 150.15 and 218.00 MB/h —
times the 4,380 hours in the retention floor. Every one of those three figures is
**linear in the control rate**, which [The control rate](#the-control-rate) below
measures. What the sensitivity establishes is *the shape of the dependence*; the
conclusion drawn from it is the two paragraphs after the crossover table.

| sensor rate | log at 6 months | vs occurrence (265 GB) | vs transition (658 GB) | vs per-frame (955 GB) |
|---|---|---|---|---|
| 0.1 TB/day | 18.2 TB | 69x | 28x | 19x |
| 0.5 TB/day | 91.2 TB | 344x | 139x | 96x |
| **1 TB/day (published)** | **182.5 TB** | **689x** | **277x** | **191x** |
| 5 TB/day | 912.5 TB | 3,443x | 1,387x | 955x |
| 21.3 TB/day (cited max) | 3,887 TB | 14,669x | 5,908x | 4,070x |

**What survives the whole range and what does not.** The crossovers are
**derived, not measured** — `threshold_TB_per_day = size_GB * 10^orders / 1000 /
182.5`, so occurrence at two orders is `265 * 100 / 1000 / 182.5 = 0.145` — and
they are recomputed from the sizes above rather than carried over:

| level | clears 2 orders above | clears 3 orders above |
|---|---|---|
| occurrence | 0.145 TB/day | 1.450 TB/day |
| transition | 0.360 TB/day | 3.604 TB/day |
| per-frame | 0.523 TB/day | 5.232 TB/day |

At occurrence resolution the claim clears **two** orders of magnitude at any
sensor rate above 0.145 TB/day — seven times lower than the published
assumption, and below every cited configuration that carries a camera, including
HIW-500's compressed ~0.5 TB/day. A motion-only stream at 800 B/s is 0.07 GB/day
and clears nothing. So the two-order conclusion does not depend on the assumption
being right to within a factor of a few. **Three orders needs 1.45 TB/day, which
the published assumption does not reach.**

At the finer levels it is weaker still. **Per-frame retention clears the plan's
two-order criterion only above ~0.52 TB/day, and transition only above
~0.36 TB/day** — both within a factor of three of the published assumption, so
neither survives the assumption being wrong by an order of magnitude. Below those
rates the artifact is still smaller than the log, but not by the margin Claim 1
asserts. The plan's *upper* bound of four orders is reached at occurrence
resolution only above 14.4 TB/day: inside the cited range, far above the
assumption, so it is not available and must not be quoted.

So **the claim should be stated at occurrence resolution and at two orders** —
not two-to-three, and never four. That is also the level the only mandated
evidence recorder in existence (UN R157 DSSAD, ±1.0 s) operates at: the robust
claim and the regulated one are the same claim.

**Why coarsening buys so little at the coarsest level.** That level is not mostly
geometry. It is dominated by the declaration, verdict and chain records, which no
resolution level coarsens — 3,120 of its 3,166 node rows, counted in the next
section. Coarsening the *scene* still works; it just has less left to work on.

## The control rate

**Status: measured, on the artifact side.** Everything above this heading holds
the *sensor* rate as the variable and the artifact sizes as fixed. They are not
fixed: they are **linear in the robot's control rate**, and this simulator's rate
is not a manipulator's.

**Why the artifact scales with it at all.** Enforcement adjudicates every
commanded action, so it emits one verdict and one chain record **per control
step**, and no resolution level coarsens a record — which is why the occurrence
level is 3,120 of 3,166 node rows at 50 Hz. The policy's declarations do *not*
scale, because it replans on a wall-clock interval, so the verdict layer is the
growth.

**Measured**, from one execution of
`python -m reg.bench --control-rate-hz 50,100,250,1000 --seed 0`: the resolution
curve at four control rates over **one fixed run duration**, 59.98 s of robot
time, at one seed and the parameter block [Sensitivity](#sensitivity) states. The
frame count moves with the rate because it must — 3,000 frames at 50 Hz, 59,981
at 1 kHz — and everything else is held still, so the only thing differing between
two rows is how often the robot acted. The 50 Hz row reproduces the published
curve exactly, which is what makes the other three comparable to it.

| control rate | frames | records retained | occurrence | transition | per-frame |
|---|---|---|---|---|---|
| **50 Hz (published above)** | 3,000 | 3,120 | **60.42 MB/h** | 150.15 MB/h | 218.00 MB/h |
| 100 Hz | 5,999 | 6,119 | 106.57 MB/h | 247.19 MB/h | 410.37 MB/h |
| 250 Hz | 14,996 | 15,116 | 247.32 MB/h | 529.79 MB/h | 1.04 GB/h |
| **1 kHz (a real manipulator)** | 59,981 | 60,101 | **1.08 GB/h** | 2.08 GB/h | 4.52 GB/h |
| *x, 50 Hz → 1 kHz* | *20.0x* | *19.3x* | *17.8x* | *13.9x* | *20.7x* |

Those are measured points. **Nothing between them is interpolated and nothing
beyond them is extrapolated** — a rate nobody ran is not in the table, however
obvious it would look on a line through the ones that are. They are also a
**manual measurement**: only the 50 Hz row is re-measured by
`tests/test_published_figures.py` on every CI run, and the decision to leave the
pin there rather than extend it to the ladder is recorded in
[`retention.md`](retention.md), *The control rate*. The 250 Hz and 1 kHz rows are
above `reg.tolerances.TIME_BASE_MAX_RATE_HZ` = 100 Hz, so their artifacts cannot
address every frame of the run they price
([`limitations.md`](limitations.md) §5).

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
| **50 Hz** | **265 GB** | **~689x** | 658 GB | ~277x | 955 GB | ~191x |
| 100 Hz | 467 GB | ~391x | 1.08 TB | ~169x | 1.80 TB | ~101x |
| 250 Hz | 1.08 TB | ~169x | 2.32 TB | ~79x | 4.56 TB | ~40x |
| **1 kHz** | **4.73 TB** | **~39x** | 9.11 TB | ~20x | 19.80 TB | ~9x |

**At 1 kHz the claim is below two orders of magnitude, and this document says so
rather than repairing it.** ~39x at occurrence resolution is **one** order, not
two. The two-order band is still occupied at 250 Hz (~169x) and is gone by
1 kHz; where between those two it goes is unmeasured and is therefore not quoted.
Every finer level is worse: transition is ~21x and per-frame ~10x at 1 kHz. Both
of those rows are also above the 100 Hz the artifact's time base is declared
valid at, so what they buy is bounded by [`limitations.md`](limitations.md) §5 as
well as by the price.

**The sensor assumption is not adjusted to compensate.** It is the same
1 TB/day it has been since this document was written, for the same sourced
reasons, and it has stood through both re-measurements that moved the artifact
side (both are in the [Why](#why) table). The input has a range and the
conclusion is what moves.

**What is out of scope here.** Declaring per behaviour segment rather than per
control step would cut the term that scales, and this measurement shows it is the
dominant lever. It is a change to the attestation cadence and is held pending its
own decision.

**One caveat that is not about cost.** At 250 Hz and 1 kHz the transition and
per-frame levels return `DISAGREE` on `separation_timeline`. The edge layer's
endpoints are quantized to `TIME_TOL_S` = 0.01 s, which is coarser than the
control period above 100 Hz, so a per-frame separation read back out of an
interval can miss by more than `DISTANCE_TOL_M`.

That is a property of the graph builder rather than of retention, it is reported
rather than tuned away, and it means a 1 kHz robot does not get the finer levels'
full answer even after paying for them — the cost side of the limit
[`limitations.md`](limitations.md) §5 states.

## The incumbent encoding: rosbag2 / MCAP

**Status: a projection, computed from published specification.** No `mcap`
library was used and no `zstd` was run — this repository adds no dependency for a
baseline. What is *measured* is the byte stream produced by an encoder written
here from the spec, applied to real fixture data. What is *projected* is that a
rosbag2 writer would produce the same layout.

### Why this baseline exists

Claim 1's negative result is measured against a **gzipped CSV**. Nobody retains a
gzipped CSV. What practitioners retain is rosbag2, increasingly in MCAP, and two
independent external reviews named it as the unnamed incumbent. A comparison
against a format nobody runs prices a counterfactual.

### The comparison

Same information on both sides — `t`, `q`, `qd` for a two-joint arm, 251 frames
of the `declared_violation` fixture at 50 Hz. **Both rosbag2 presets are
priced**, because the configuration a practitioner gets and the configuration
that matches a gzipped baseline are not the same one:

| Encoding | Size | x gz CSV |
|---|---|---|
| CSV, gzip -9 | **3,053 B** | 1.00x |
| MCAP, `mcap_default` — uncompressed, chunked, indexed | **35,893 B** | **11.76x** |
| MCAP, `mcap_compressed_nocrc` — zstd chunks, indexed | **11,685 B** | **3.83x** |

`mcap_default` is rosbag2's default preset: **uncompressed**, chunked at 768 KiB,
with a message index; compression is the opt-in `mcap_compressed_nocrc`
([rosbag2 storage plugin benchmarks](https://mcap.dev/guides/benchmarks/rosbag2-storage-plugins)).
So **what a practitioner retains without choosing anything costs 11.76x the
gzipped CSV**, and the compressed preset — the like-for-like against a gzipped
baseline — costs 3.83x. Both are published rather than one: quoting whichever
preset suits the argument is the same move as measuring against a baseline
nobody runs, one layer down.

The cost is per-message self-description plus a per-message index, which is what
a bag format is for and is expensive at 50 Hz:

```
143 B  per message, before compression
   1   opcode
   8   record length
  22   channel_id, sequence, log_time, publish_time   (mcap.dev/spec)
  96   CDR payload
        of which 32 B is the four float64s that carry the data;
        the rest is the encapsulation header, the Time struct, the
        joint-name strings repeated on every message, and alignment padding
  16   MessageIndex entry: log_time 8 + offset 8, one per message
        and outside the chunk, so uncompressed under either preset
```

So the baseline Claim 1 currently uses is not merely unrepresentative — it is
**about 12x more efficient than what a practitioner actually retains**, and
about 4x more efficient than the same bag with compression turned on. The
artifact's disadvantage against what practitioners keep is correspondingly
smaller than the published figure against gzipped CSV.

**This document does not restate the headline.** The ratio above is an encoding
ratio, free of fixed cost on both sides. Translating it into Claim 1 needs
`reg.bench` measuring its own fixtures, which is open work ([Why](#why) says
whose). A short-run artifact measurement will not do it: over a five-second
fixture the artifact's fixed schema and index cost dominates, and any ratio taken
there says more about the schema than the encoding.

### Assumptions, each of which can move the number

- **`mcap_default` is a floor and the compressed figure is not.** Every
  assumption below makes the default preset look cheaper than a real bag, so
  11.76x understates the incumbent. The compressed figure carries one
  assumption whose direction nobody here can state, which is the next line, so
  *floor* is claimed for the first number and withdrawn for the second.
- **gzip -9 stands in for zstd** in `mcap_compressed_nocrc`. Comparable in
  class, not identical, and which is smaller on this data is unmeasured. The
  default preset compresses nothing and carries no compressor assumption at all.
- **File-level records excluded** — header, schema, channel, chunk headers,
  chunk index, statistics, summary, footer, and the 15 B fixed part of each
  MessageIndex record. Adds roughly 1-2 kB fixed: negligible at scale, material
  at 251 messages, and it makes MCAP look *better* here than it is.
- **The per-message index is included**, at 16 B per message under both presets.
  It is what makes a bag seekable, rosbag2 writes it by default, and it scales
  with the run rather than sitting in the fixed cost above.
- **Joint names `joint_0` / `joint_1`, empty `frame_id`, empty `effort`.** Real
  robots use longer joint names, which makes MCAP look worse.
- **`sensor_msgs/msg/JointState` with position and velocity only.** A system
  publishing effort, or publishing at a higher rate than it commands, differs.
- **XCDR1 little-endian**, the ROS 2 default via Fast-CDR.

### The Layer B asymmetry

The two sides do not carry the same information about the world, and the
comparison is only honest with that stated rather than footnoted. The fixture
stream carries `human_x`, `human_y`, `human_vx`, `human_vy` — **simulator ground
truth for the person**. No robot's `/joint_states` contains that and no bag does
either; a real system carries perception output, and the sensing that produced
it. Neither is priced here.

This comparison therefore prices **proprioception only, on both sides**. It says
nothing about what it costs to know where the human was. That is Layer B, the
expensive half, and the half this document projects rather than measures
everywhere else.

### What would retire this section

A rosbag2 writer with the real `mcap` library and real `zstd`, run once outside
this repository against the same fixture, recorded here with its version and
command line, and priced under both presets. That replaces a projection with a
measurement and should be done before any outside-facing document leans on the
11.76x.

## A premise this document does not carry: air-gapped sites

**The retention argument rests on the sensor rate alone.** A second empirical
claim once stood beside it: that full sensor logs cannot leave an air-gapped
site. It was stated as a fact in `README.md` and three times in
[`plan.md`](plan.md), it stood in for the requirement below in three more places,
and it appeared **zero times here**: no source, no range, no sensitivity, in the
document where every other input gets all three.

**It is retired rather than sourced, because the argument does not need it.**
What the retention argument needs is that keeping the raw log for the mandated
window is expensive per robot and keeping the artifact is not. Both halves are
above and neither mentions a network: 182.5 TB per robot per retention window at
the published multiplier, against 265 GB of artifact at occurrence resolution and
a 50 Hz control rate, with the sensitivity to the multiplier in
[Sensitivity](#sensitivity). None of that arithmetic moves on a site with a fibre
uplink, and sourcing the premise would have added a second empirical input
carrying no weight.

**The requirement half stands, because it is a different kind of claim.**
*Off-network verifiability* — one self-contained file an assessor can check years
later with no service still running and no call to anyone — is a **requirement of
the design**, not an observation about how sites are run. These sites are heavily
instrumented and their telemetry already flows to a cloud the operator runs,
which is the reason for the requirement: an assessor certifying what happened
needs a record whose integrity does not rest on infrastructure belonging to the
party assessed.

Requirements are stated, not sourced, so that half needs nothing from this
document. It is stated in [`limitations.md`](limitations.md) §6, in
[`plan.md`](plan.md) under Claim 4, and in `reg/commit.py`, where RFC 3161 and
transparency-log commitment are documented and deliberately unimplemented under
it.

**What would bring the premise back.** A measurement rather than an assertion: how
many deployments in the target class run isolated, over what range, with the
sensitivity of the retention argument to it — the same three things every other
input on this page carries. Absent that, no document in this repository states
site isolation as a fact, and `tests/test_air_gap_framing.py` fails if one starts
to.

## What would retire this document

A measured figure from a fielded humanoid — sensor manifest, sample rates, codec,
duty cycle, and a logged byte count over a known interval. Until then the honest
form is the one used throughout: an explicit multiplier, a linear sensitivity, and
the word *projection* on every number derived from it.

That retires the *sensor* side only. The control rate is the other half, and it
is already measured rather than assumed: the figure a reader needs is the rate
their own robot's constraint layer adjudicates at. The rosbag2/MCAP
projection retires separately and on its own terms — see
[What would retire this section](#what-would-retire-this-section).

## See also

- [`retention.md`](retention.md) — where the projection is quoted, and every
  artifact-side figure it is quoted against
- [`plan.md`](plan.md) Claim 1 — the claim the projection serves
- [`lossiness.md`](lossiness.md) — the three resolution levels being priced
- [`prior-art.md`](prior-art.md) §8 — why the artifact loses to a float codec, and
  why that is not this comparison
- `python -m reg.bench --control-rate-hz 50,100,250,1000 --seed 0` — the command
  that produces the control-rate table, and `--resolution` for the curve at one
  rate. Neither flag has a default rate to fall back on

## Why

Nothing below is normative. It is the provenance of the sections above: which
issue each arrived with, and what each re-measurement moved. An assumption is
worth least once nobody remembers what it was weighed against.

### When each section was added

| section | issue | dated in this file as |
|---|---|---|
| The document, the multiplier, its sourced range | #58 | 2026-08-19 |
| Every size re-measured with Layer A in the artifact; the window as Art. 19 and Art. 26(6) | #59, #60, #64 | 2026-08-20 |
| *The control rate* and its ladder; run identity and the outer-envelope scalars in the sizes; the ladder republished | #68, #82, #83, #94 | 2026-08-21 |
| *The incumbent encoding*; the premise this document does not carry | #117, #102 | 2026-08-26 |
| *The incumbent encoding* republished under both rosbag2 presets, with the message index priced | #117 | 2026-09-06 |
| The priced stream, as 24 columns and 19 Layer B | #123 | 2026-08-27 |
| Three sensitivity rows recomputed from the sizes | — | 2026-08-28 |
| The base pose on `robot_config`; the ladder re-measured, three rungs of it stale | #166 | 2026-09-02 |

### The sizes the Layer A re-measurement replaced

The provisional figures measured an artifact holding no Layer A record at all
(issue #59): occurrence went 18.9 GB → 263 GB, transition 229.7 → 655 GB,
per-frame 589.3 → 952 GB. Those are the figures #59 produced; today they are 265,
658 and 955 GB. Issues #83, #82 and #166 account for the 0.8% between — run
identity, the outer-envelope scalars and the base pose on the `robot_config`
row, whose byte cost is itemised in [`lossiness.md`](lossiness.md), *Retained*
#8.

The attribution is to #59 because that is the change that moved the figures by an
order of magnitude, and because it established that no resolution level coarsens
a record — which is what put the coarsest level at 3,120 of 3,166 node rows and
made the control rate the artifact's second variable. Before it, coarsening the
scene bought proportionally more.

### What the two re-measurements did to the conclusion

Before Layer A entered the artifact the three-order threshold sat at
0.104 TB/day and the published assumption cleared it tenfold; issue #60 is where
three orders stopped being available, and issue #68 is where the two-order band
went at 1 kHz. Both times the multiplier stayed at 1 TB/day, and the two-order
conclusion at 50 Hz did not move at all.

### An outside estimate, checked

Issue #68 arrived with a reviewer's estimate of ~5.1 TB per robot per six months
at 1 kHz, i.e. ~36x, flagged explicitly as unverified. The measured figures are
4.73 TB and ~39x. The estimate was directionally right and slightly pessimistic,
for the reason *The control rate* gives: it assumed the whole level scales, and
1.5% of it does not.

### Whose work the incumbent ratio is waiting on

Translating the 11.76x into Claim 1 is not #117's work but its successor's: the
two comparisons are not composable. Until that lands the ratio travels with the
condition that it is a hand-built encoding comparison and not a real bag, which
is what `README.md` and [`plan.md`](plan.md) state wherever they quote it.

### What the 2026-09-06 re-measurement moved, and why

This section published **2.51x** and **7,669 B** from 2026-08-26. That figure is
superseded: it priced chunk compression as though rosbag2 applied it by default
and left the message index out, so it modelled a configuration a practitioner has
to select and undercharged even that one. Both errors ran the same way — they
made the incumbent look cheap, which made this project's disadvantage look worse
than it is, the same direction of error the gzipped-CSV baseline itself has.
Correcting them gives 35,893 B at the default preset and 11,685 B at the
compressed one, against the same 3,053 B of gzipped CSV.
