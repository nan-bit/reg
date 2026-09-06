# The sensor-log baseline

**Status: an assumption with a sourced range, not a measurement.** The sensor
rate is the one input the benchmark cannot produce, so it is stated with a
source, a range and a sensitivity. The artifact side is measured, at a stated
control rate. Provenance is under [Why](#why).

`docs/plan.md` Claim 1 compares the artifact against a raw sensor log at
**1 TB/day**. `reg` has no sensors and nothing here can measure that figure, so
every comparison against a sensor log is a **projection** — and this document is
what it is projected from.

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
value that makes the conclusion come out is the failure this document prevents,
so the multiplier stays at 1 TB/day and the claim drawn from it is restated
whenever the artifact side is re-measured ([Sensitivity](#sensitivity)).

**Every artifact size here is linear in that control rate**, because enforcement
emits a verdict and a chain record per commanded action. Every size above
[The control rate](#the-control-rate) is at 50 Hz; that section measures the rest
of the ladder and states what the rungs above 100 Hz can and cannot be asked.

## What the projection is measured against

The simulator's own state stream is the whole of the benchmark's input, and it is
**not** proprioception: for the fixture priced it is **24 columns and 19 of them
are Layer B** (`reg.stream.expected_header(2, 3)`) — `human_x`, `human_y`,
`human_vx`, `human_vy` and each obstacle's `id`, `kind`, `x`, `y`, `r`, beside
the five proprioceptive columns `reg.bench.proprioceptive_columns` returns.
Simulator ground truth for a person is the Layer B content this document projects
rather than measures, so the baseline is small *and* carries entity state a real
system would have to perceive; see
[The Layer B asymmetry](#the-layer-b-asymmetry).

The benchmark enforces this in code rather than prose: `--sensor-multiplier` has
**no default**. Omit it and the report prints the measured columns and says no
projection was computed
(`tests/test_bench.py::test_without_a_multiplier_there_is_no_projection_at_all`).
No value of it makes the output claim to have measured a robot.

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

A second anchor from the other direction, a real collected dataset: **HIW-500**
is 10 TB over 500 hours across 12 homes — ~20 GB/hour, or ~0.5 TB a day. It sits
far below the teleoperation figure because it is **compressed, curated episode
data rather than a continuous raw log** — the distinction that matters most here,
and why the range spans three orders of magnitude.

For scale from the adjacent regulated industry: a production autonomous vehicle
is widely quoted at 1.4–19 TB/hour, development vehicles higher. An order of
magnitude above the humanoid figures, **not** used in any `reg` projection, and
recorded only so nobody reads 1 TB/day as aggressive.

Sources:
- [Data Standards for Humanoid Robotics (arXiv:2606.19769)](https://arxiv.org/html/2606.19769)
- [Humanoid Everyday (arXiv:2510.08807)](https://arxiv.org/html/2510.08807v1)
- [HIW-500](https://www.humanoidsdaily.com/news/bitrobot-and-hugging-face-drop-hiw-500-a-massive-10tb-real-home-humanoid-dataset)
- [The Robotic Data Pipeline](https://www.trossenrobotics.com/post/robotic-data-pipeline-sensor-streams-to-training-datasets)
- [The Data Deluge (Siemens Polarion)](https://blogs.sw.siemens.com/polarion/the-data-deluge-what-do-we-do-with-the-data-generated-by-avs/)

**Honest characterisation of these sources.** One arXiv preprint with a range and
no sensor configuration on its endpoints; one dataset size that has to be divided
by hours to become a rate; two industry blog posts. None measures a fielded
humanoid logging continuously for six months, because that robot is not deployed
and that log does not exist yet. The argument is built to survive that — see the
sensitivity below.

## Sensitivity

The ratio is **linear in the assumed rate**, so the assumption never hides: halve
the rate and every ratio halves.

The artifact sizes below are **measured**, from one execution of
`python -m reg.bench --resolution --seed 0`: `long_run` at 3,000 frames **at a
50 Hz control rate**, 16 envelope samples, 200 ms horizon, 1.0 s occurrence
resolution, 0.5 s replan interval and declaration horizon, 1.0 s watchdog. Each
size is that level's measured `bytes/hour` — 60.42, 150.15 and 218.00 MB/h —
times the 4,380 hours in the retention floor, and all three are **linear in the
control rate**, which [The control rate](#the-control-rate) measures. The
sensitivity establishes *the shape of the dependence*; the conclusion drawn from
it is the two paragraphs after the crossover table.

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
sensor rate above 0.145 TB/day — seven times below the published assumption, and
below every cited configuration carrying a camera, including HIW-500's compressed
~0.5 TB/day. A motion-only stream at 800 B/s is 0.07 GB/day and clears nothing.
The two-order conclusion therefore does not need the assumption right to within a
factor of a few. **Three orders needs 1.45 TB/day, which it does not reach.**

At the finer levels it is weaker still. **Per-frame retention clears the plan's
two-order criterion only above ~0.52 TB/day, and transition only above
~0.36 TB/day** — both within a factor of three of the published assumption, so
neither survives it being wrong by an order of magnitude. Below those rates the
artifact is still smaller than the log, but not by the margin Claim 1 asserts.
The plan's *upper* bound of four orders is reached at occurrence resolution only
above 14.4 TB/day: inside the cited range, far above the assumption, so it is not
available and must not be quoted.

So **the claim should be stated at occurrence resolution and at two orders** —
not two-to-three, never four. That is also the level the only mandated evidence
recorder in existence (UN R157 DSSAD, ±1.0 s) operates at: the robust claim and
the regulated one are the same.

**Why coarsening buys so little at the coarsest level.** That level is not mostly
geometry: it is dominated by the declaration, verdict and chain records, which no
resolution level coarsens — 3,120 of its 3,166 node rows, counted in the next
section. Coarsening the *scene* still works, with less left to work on.

## The control rate

**Status: measured, on the artifact side.** Everything above holds the *sensor*
rate as the variable and the artifact sizes as fixed. They are not: they are
**linear in the robot's control rate**, and this simulator's rate is not a
manipulator's.

**Why the artifact scales with it at all.** Enforcement emits one verdict and one
chain record **per control step**, and no resolution level coarsens a record —
which is why the occurrence level is 3,120 of 3,166 node rows at 50 Hz. The
policy's declarations do *not* scale, since it replans on a wall-clock interval,
so the verdict layer is the growth.

**Measured**, from one execution of
`python -m reg.bench --control-rate-hz 50,100,250,1000 --seed 0`: the resolution
curve at four control rates over **one fixed run duration**, 59.98 s of robot
time, at one seed and the parameter block [Sensitivity](#sensitivity) states. The
frame count moves with the rate because it must — 3,000 frames at 50 Hz, 59,981
at 1 kHz — and everything else is held still, so two rows differ only in how
often the robot acted. The 50 Hz row reproduces the published curve exactly,
which is what makes the other three comparable to it.

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
`tests/test_published_figures.py` on every CI run, and leaving the pin there
rather than extending it to the ladder is recorded in
[`retention.md`](retention.md), *The control rate*. The 250 Hz and 1 kHz rows sit
above `reg.tolerances.TIME_BASE_MAX_RATE_HZ` = 100 Hz, so their artifacts cannot
address every frame they price ([`limitations.md`](limitations.md) §5).

The growth is **sublinear**: 15.8x at the occurrence level for a 20x rate
increase, because the scene rows and the fixed schema-and-index cost do not scale
with the rate. Only the record layer does, and by 1 kHz it is 60,101 of that
level's 60,572 node rows — 99.2%, against 98.5% at 50 Hz. That level is almost
entirely a per-action attestation stream, which is what the rate buys and what a
cadence change would cut.

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
two. The two-order band is still occupied at 250 Hz (~169x) and is gone by 1 kHz;
where between those two it goes is unmeasured and is not quoted. Every finer
level is worse: transition ~21x and per-frame ~10x at 1 kHz. Both rows also sit
above the 100 Hz the artifact's time base is declared valid at, so what they buy
is bounded by [`limitations.md`](limitations.md) §5 as well as by the price.

**The sensor assumption is not adjusted to compensate.** It is the same
1 TB/day it has been since this document was written, for the same sourced
reasons, and it has stood through both re-measurements that moved the artifact
side (both are in the [Why](#why) table). The input has a range and the
conclusion is what moves.

**What is out of scope here.** Declaring per behaviour segment rather than per
control step would cut the term that scales, and this measurement shows it is the
dominant lever. It changes the attestation cadence and is held pending its own
decision.

**One caveat that is not about cost.** At 250 Hz and 1 kHz the transition and
per-frame levels return `DISAGREE` on `separation_timeline`: the edge layer's
endpoints are quantized to `TIME_TOL_S` = 0.01 s, coarser than the control period
above 100 Hz, so a per-frame separation read back out of an interval can miss by
more than `DISTANCE_TOL_M`.

That is a property of the graph builder rather than of retention, reported rather
than tuned away, and it means a 1 kHz robot does not get the finer levels' full
answer even after paying for them — the cost side of
[`limitations.md`](limitations.md) §5.

## The incumbent encoding: rosbag2 / MCAP

**Status: a projection computed from published specification, checked against a
real encoder and against rosbag2.** No `mcap` library is used here and no
`zstd` is run —
this repository adds no dependency for a baseline. What is *measured* is the byte
stream an encoder written here from the spec produces on real fixture data; what
is *projected* is that a rosbag2 writer lays out the same bytes.

**That projection is now tested rather than asserted.** Every uncompressed
figure came back exact against a reference writer
([Validating the projection](#validating-the-projection-against-a-real-bag)) and
within 1% of a bag `ros2 bag record` wrote ([the rosbag2 run](#the-rosbag2-run));
two compressed figures sit outside the registered band and are marked where
this document publishes them.

### Why this baseline exists

Claim 1's negative result is measured against a **gzipped CSV**, which nobody
retains. Practitioners retain rosbag2, increasingly in MCAP, and two independent
external reviews named it as the unnamed incumbent. A comparison against a format
nobody runs prices a counterfactual.

### The comparison

Same information on both sides — `t`, `q`, `qd` for a two-joint arm, 251 frames
of the `declared_violation` fixture at 50 Hz. **Uncompressed and compressed are
both priced**: what a practitioner gets and what matches a gzipped baseline are
not the same configuration:

| Encoding | Size | x gz CSV |
|---|---|---|
| CSV, gzip -9 | **3,053 B** | 1.00x |
| MCAP, `none` — uncompressed, chunked, indexed | **35,893 B** | **11.76x** |
| MCAP, `zstd_fast` / `zstd_small` — zstd chunks, indexed | **11,685 B** | **3.83x** |

The names are `--storage-preset-profile` values
(`reg.bench.ROSBAG2_STORAGE_PRESET_PROFILES`). `none` is what a bag costs when
nobody chooses, **uncompressed** and message-indexed, so **what a practitioner
retains without choosing anything costs 11.76x the gzipped CSV**. The compressed
row is one projection standing for both zstd profiles, at 3.83x;
[the rosbag2 run](#the-rosbag2-run) measures it against each and it matches
neither. Both are published anyway: quoting whichever suits the argument is the
error the gzipped baseline already makes, one layer down.

The cost is per-message self-description plus a per-message index, which is what
a bag format is for and is expensive at 50 Hz:

```
143 B  per message, before compression
   1   opcode
   8   record length
  22   channel_id, sequence, log_time, publish_time   (mcap.dev/spec)
  96   CDR payload
        of which 32 B is the four float64s that carry the data; the rest
        is the encapsulation header, the Time struct, the joint names
        repeated on every message, and alignment padding
  16   MessageIndex entry: log_time 8 + offset 8, one per message
        and outside the chunk, so uncompressed under either preset
```

So the gzipped-CSV baseline is **about 12x more efficient than what a
practitioner retains**, and about 4x more efficient than the same bag
compressed. The artifact's disadvantage against what practitioners keep is
correspondingly smaller.

**This document does not restate the headline.** The ratio above is an encoding
ratio, free of fixed cost on both sides and over 5 columns of 24.
[`retention.md`](retention.md) is where Claim 1's headline meets it, on the
whole-stream figures below — measured on the 3,000-frame fixture, because over a
five-second one the artifact's fixed cost dominates.

### Assumptions, each of which can move the number

These govern both tables in this section — the same encoder over different
columns of the same fixture.

- **`none` is a floor; the compressed figure is not.** Every assumption below
  makes the uncompressed profile look cheaper than a real bag, so 11.76x
  understates the incumbent. The compressed figure instead rests on **gzip -9
  standing in for zstd** — comparable in class, not identical — and that
  direction is now measured rather than open: it costs both compressed
  whole-stream figures their standing
  ([Validating the projection](#validating-the-projection-against-a-real-bag)).
- **File-level records excluded** — header, schema, channel, chunk headers,
  chunk index, statistics, summary, footer, and the 15 B fixed part of each
  MessageIndex record. Roughly 1-2 kB fixed: negligible at scale, material at
  251 messages, and it makes MCAP look *better* here than it is.
- **The per-message index is included**, at 16 B per message under every profile
  priced, and measured at 16.06 B against the `fastwrite` bag that writes none.
  It makes a bag seekable, rosbag2 writes it by default, and it scales with the
  run. `fastwrite` is not priced here for the same reason: the cost that defines
  it is one this encoder always charges.
- **Joint names `joint_0` / `joint_1`, empty `frame_id`, empty `effort`.** Real
  robots use longer joint names, which makes MCAP look worse.
- **`sensor_msgs/msg/JointState` with position and velocity only.** A system
  publishing effort, or publishing at a higher rate than it commands, differs.
- **XCDR1 little-endian**, the ROS 2 default via Fast-CDR.

### The Layer B asymmetry, and what closing it costs

The two sides of the table above do not carry the same information about the
world, and the comparison is only honest with that stated. The fixture stream
carries `human_x`, `human_y`, `human_vx`, `human_vy` — **simulator ground truth
for the person**. No robot's `/joint_states` holds that and no bag does; a real
system carries perception output and the sensing behind it, neither priced
here.

That table therefore prices **proprioception only, on both sides**: five of the
fixture's 24 columns. The section below prices the other nineteen, so this ratio
and [`retention.md`](retention.md)'s headline cover the same content and divide
into one another. Neither prices the *sensing* behind a real system's version of
those nineteen — the expensive half, and the half this document projects rather
than measures.

### The same encoding, over the whole stream

**What a real system publishes for the world half is a decision, and the decision
is the deliverable.** The human and the obstacles are entities with poses, and a
ROS 2 system puts them on topics of its own choosing. Every choice moves the
number, so `reg.bench.LAYER_B_OPTIONS` prices the candidates and
`cheapest_layer_b_option` takes the **smallest** — the arrangement most
favourable to the incumbent:

| arrangement for the 19 Layer B columns, 3,000 frames | `none` | `zstd_fast` / `zstd_small` |
|---|---|---|
| **`/tf`** — one `tf2_msgs/TFMessage` per control period, one `TransformStamped` per entity | **1,209,000 B** | **170,628 B** [^v] |
| `geometry_msgs/PoseStamped` per entity per control period, each on its own topic | 1,476,000 B | 315,225 B |

`/tf` is smaller either way and is chosen either way: it carries the
per-message MCAP framing and the 16 B message index once per control period
instead of once per entity, each entity's identity rides in its child frame
name, and a tf tree is what many ROS 2 systems publish entity poses on anyway.

**`visualization_msgs/MarkerArray` is the third candidate and it is not priced.**
A Marker states an extent in `scale`; the stream carries one for each obstacle
and none for the human, and nothing here may choose one. A plausible metre would
sit inside a published byte count looking exactly like a measured one, so
`reg.bench.marker_cdr` refuses that entity by name.

**Refusing it costs the comparison nothing**: a Marker cannot be the most
favourable arrangement anyway. It carries the same Header and Pose as a
`TransformStamped` and adds a namespace, an id, a type, an action, a scale, a
colour, a lifetime, a frame-locked flag, two empty arrays and two empty strings
on top — dearer per entity term by term, at one message per control period
either way. `tests/test_incumbent_encoding.py` measures that on an obstacle.

**The bag, both halves, over the same 3,000-frame fixture the retention figures
are measured on:**

| Encoding, all 24 columns | `none` | `zstd_fast` / `zstd_small` |
|---|---|---|
| `/joint_states` — the 5 proprioceptive columns | 429,000 B | 136,500 B |
| `/tf` — the 19 Layer B columns | 1,209,000 B | 170,628 B [^v] |
| **the bag** | **1,638,000 B** | **307,128 B** [^v] |
| the same 24 columns as CSV, gzip -9 | 64,652 B | 64,652 B |
| x gz CSV | **25.34x** | **4.75x** [^v] |

[^v]: **Outside the validation band; this figure does not stand.** A real MCAP
    encoder produced 154,040 B for `/tf`, 284,259 B for the bag and **4.40x** —
    out by -9.72% and -7.45% against a +/-5% band registered ahead of it. It
    overstates the incumbent, which flatters this project; the uncompressed
    column beside it is exact.
    [Validating the projection](#validating-the-projection-against-a-real-bag).

[`retention.md`](retention.md), *The same comparison, measured on the artifact
that carries Layer A*, is where those become a ratio against the artifact.

#### Three discounts this hands the incumbent, each one deliberate

- **Eight of the nineteen columns are charged nothing per frame** — `human_vx`,
  `human_vy`, and each obstacle's `kind` and `r`, itemised by
  `reg.bench.uncharged_layer_b_columns`. An obstacle's extent and kind hold
  still and a real system latches them once; the human's velocity is a finite
  difference of the two pose columns the bag already carries. The gzipped CSV
  pays for all eight on every one of 3,000 rows.
- **The parent frame is `map`**, three characters, on the wire in every
  transform of every message. A deployment on `odom_combined` pays more.
- **Every file-level record is excluded**, as in the table above. The per-entity
  alternative gains most from that, being the arrangement whose entity names
  live in topic strings rather than in the payload.

Each of the three runs the same way: it makes the bag cheaper, which makes the
artifact's ratio against the bag larger, which is the direction that goes
against this project.

### Validating the projection against a real bag

A specification can be read correctly and applied to the wrong configuration, so
a projection nobody outside this repository can regenerate is an assertion
([`prior-art.md`](prior-art.md) §27). Both fixtures, at the seed every figure
here is measured at:

```bash
python -m reg.sim --scenario declared_violation --seed 0 --out dv.csv        #   251 frames
python -m reg.sim --scenario long_run_3000      --seed 0 --out long_run.csv  # 3,000 frames
```

Republish each row as ROS 2 messages and record with rosbag2's MCAP plugin.
`/joint_states` is `sensor_msgs/msg/JointState`: `header.stamp` from `t`, empty
`frame_id`, `name` `joint_0`/`joint_1`, `position` from `q_*`, `velocity` from
`qd_*`, empty `effort`. `/tf` is `tf2_msgs/msg/TFMessage`, one per control period,
one `TransformStamped` per entity in header order, `frame_id` `map`
(`reg.bench.LAYER_B_PARENT_FRAME`), `child_frame_id` the entity name, translation
(`x`, `y`, 0), identity rotation. Both carry `log_time` = `publish_time` =
`round(t x 1e9)` and `sequence` = the row index, XCDR1 little-endian. Six bags —
`/joint_states` over 251 frames, then `/joint_states`, `/tf` and both over 3,000
— uncompressed, chunked at 768 KiB, indexed, and again with zstd chunks.

**Compare the per-message scaling total, not file sizes**, since the projection
excludes every file-level record. Walk the bag by opcode; per chunk sum the
Message records with their framing, re-compressing those records alone at the
writer's own chunk boundaries; add 16 B per MessageIndex entry, read out of the
index records. Set that beside `reg.bench.mcap_joint_states_bytes`,
`layer_b_mcap_bytes(option="tf_tree")` and `full_content_mcap_bytes`.

**The tolerance, fixed in commit e8f1534 ahead of the bags.** Payload length,
per-message framing, MessageIndex entry width and the whole uncompressed total
are compared **exactly**: byte counts off the spec and the IDL over a known
message count, with no estimate in them. The compressed total gets **+/-5%**,
for the one substitution — gzip -9 for zstd, which *Assumptions* above declines a
direction for.

Within the band the projection stands, delta beside it. Outside it, the figure
is marked as not standing wherever this document quotes it. A tolerance chosen
after seeing the number is not one, and either outcome is a result.

**The measurement: 2026-09-06, x86_64 Linux**, by the reference Python MCAP
writer — `mcap` 1.4.0, `mcap-ros2-support` 0.5.7, `zstandard` 0.25.0 (libzstd
1.5.7), CPython 3.12.3. **Not exercised: rosbag2's own C++ writer**, so a second
implementation of the same spec stands in. All five per-message terms are exact,
and the 96 B and 356 B payloads came back **byte-identical** to
`reg.bench.joint_state_cdr` and `tf_message_cdr`, padding included.

```
fixture             frames  topics             preset                  projected    measured    delta  verdict
declared_violation     251  /joint_states      none                       35,893      35,893   +0.00%  stands
declared_violation     251  /joint_states      reference_zstd_l3          11,685      11,358   -2.80%  stands
long_run_3000        3,000  /joint_states      none                      429,000     429,000   +0.00%  stands
long_run_3000        3,000  /joint_states      reference_zstd_l3         136,500     133,134   -2.47%  stands
long_run_3000        3,000  /tf                none                    1,209,000   1,209,000   +0.00%  stands
long_run_3000        3,000  /tf                reference_zstd_l3         170,628     154,040   -9.72%  DOES-NOT-STAND
long_run_3000        3,000  /joint_states+/tf  none                    1,638,000   1,638,000   +0.00%  stands
long_run_3000        3,000  /joint_states+/tf  reference_zstd_l3         307,128     284,259   -7.45%  DOES-NOT-STAND
```

`reg.bench.MCAP_SIZE_MEASUREMENTS` holds those rows and derives each verdict from
its own two byte counts; `tests/test_incumbent_encoding.py` fails if table and
record disagree, or if the projection drifts.

**Every uncompressed figure is the same integer**, on both fixtures and both
column sets, so **11.76x and 25.34x stand as measurements**. **The compressed
figures split**, structurally: gzip's window is 32 KiB and zstd's is not, while a
`/tf` message repeats the parent frame, four entity names, three static poses and
four identity quaternions every 387 B.

A negative delta means the projection published a bag dearer than the real one.
Across zstd levels 1 to 19 `/tf` stays outside the band, so the verdict is not an
artefact of the level.

**The two are marked, not replaced.** `reg.bench` computes them live for any
stream, and a constant substituted here would make a general function return a
number it never computed.

### The rosbag2 run

`ros2 bag record` itself, on both fixtures, by the procedure above.
**2026-09-06, `ros:jazzy` under Docker 29.4.0 on an arm64 Darwin host, via
`rosbag2_py`**, `/joint_states` + `/tf`, whole files as the filesystem reports
them (`reg.bench.ROSBAG2_PROVENANCE`). No ROS 2 is installed on the host that
writes this repository's unattended changes, so to it these bytes are given
data.

**Two preset names this document published are names rosbag2 rejects**, each
answered with `unknown MCAP storage preset profile (valid options are 'none',
'fastwrite', 'zstd_fast', 'zstd_small')`. They are mcap.dev's benchmark
vocabulary, not `--storage-preset-profile` values. **And rosbag2 ships two
compressed profiles**, so one projection cannot be right about "the compressed
preset":

```
fixture             frames  profile     measured   projected     delta  verdict
declared_violation     251  unset        147,827           -        -  not-projected
declared_violation     251  none         147,831     137,046  +7.870%  no-band
declared_violation     251  fastwrite    139,621           -        -  not-projected
declared_violation     251  zstd_fast     39,227      25,225 +55.508%  no-band
declared_violation     251  zstd_small    28,295      25,225 +12.170%  no-band
long_run_3000        3,000  unset      1,637,963           -        -  not-projected
long_run_3000        3,000  none       1,637,967   1,638,000  -0.002%  stands
long_run_3000        3,000  fastwrite  1,541,617           -        -  not-projected
long_run_3000        3,000  zstd_fast    360,798     307,128 +17.475%  no-band
long_run_3000        3,000  zstd_small   252,034     307,128 -17.938%  no-band
```

**One row carries a band: the uncompressed 3,000-frame bag, at 1%**, fixed ahead
of the run (`reg.bench.ROSBAG2_UNCOMPRESSED_TOLERANCE`). No other row gets one
and none reads as a pass: the `fastwrite` and unset bags have no projection to
judge, and one compressed projection covers two profiles 43% apart. What the run
settles:

- **The uncompressed projection is the bag**: 1,638,000 B against 1,637,967 B,
  -0.002%, inside the band, and closer than its parts: ~11.8 kB of excluded
  file-level records against ~4 B per frame-pair of over-charge, cancelling at
  3,000 frames and showing as +7.87% at 251.
- **The default is uncompressed, measured.** No profile and `none` differ by 4 B
  on 147,827, under one message of framing.
- **The 16 B index is confirmed from a second direction**: `none` − `fastwrite`
  over 6,000 messages is 16.06 B per message
  (`reg.bench.rosbag2_index_bytes_per_message`), the 0.06 being the per-chunk
  fixed part this projection excludes.
- **Neither compressed figure projects a profile**: 307,128 B sits 14.9% under
  `zstd_fast` and 21.9% over `zstd_small`, so the marked figures stay marked,
  and marked about a model now rather than about a missing measurement.

`reg.bench.ROSBAG2_SIZE_MEASUREMENTS` holds the ten rows and derives each verdict
from its own byte counts; `tests/test_incumbent_encoding.py` fails if page and
record disagree.

### What would retire this section

A compressed projection that models one of the two zstd profiles. Everything a
bag can settle is settled above — record layout, payloads, framing, index and the
whole uncompressed total. What is left is gzip -9 standing in for zstd, and no
further `ros2 bag record` closes it: the two profiles bracket the projection, so
a compressed figure that stands has to name which one it models. That is a
modelling question ([`plan.md`](plan.md) forbids the dependency that would
answer it directly).

## A premise this document does not carry: air-gapped sites

**The retention argument rests on the sensor rate alone.** A second empirical
claim once stood beside it: that full sensor logs cannot leave an air-gapped
site. It was stated as fact in `README.md` and three times in
[`plan.md`](plan.md), stood in for the requirement below in three more places,
and appeared **zero times here** — no source, no range, no sensitivity, in the
document where every other input gets all three.

**It is retired rather than sourced, because the argument does not need it.**
What the retention argument needs is that keeping the raw log for the mandated
window is expensive per robot and keeping the artifact is not. Both halves are
above and neither mentions a network: 182.5 TB per robot per window at the
published multiplier, against 265 GB of artifact at occurrence resolution and a
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
`tests/test_air_gap_framing.py` fails if one starts to.

## What would retire this document

A measured figure from a fielded humanoid — sensor manifest, sample rates, codec,
duty cycle, and a logged byte count over a known interval. Until then the honest
form is the one used throughout: an explicit multiplier, a linear sensitivity, and
the word *projection* on every number derived from it.

That retires the *sensor* side only. The control rate is the other half and is
already measured rather than assumed: the figure a reader needs is the rate their
own robot's constraint layer adjudicates at. The rosbag2/MCAP projection retires
separately — [What would retire this section](#what-would-retire-this-section).

## See also

- [`retention.md`](retention.md) — where the projection is quoted, and every
  artifact-side figure it is quoted against
- [`plan.md`](plan.md) Claim 1 — the claim the projection serves
- [`lossiness.md`](lossiness.md) — the three resolution levels being priced
- [`prior-art.md`](prior-art.md) §8 — why the artifact loses to a float codec, and
  why that is not this comparison
- `--control-rate-hz` and `--resolution` on `python -m reg.bench` — the commands
  above, neither with a default rate to fall back on

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
| *The same encoding, over the whole stream* — the `/tf` decision, its alternatives and the whole-stream figures | #220 | 2026-09-06 |
| *Validating the projection against a real bag* — the procedure, the tolerance registered ahead of it, and the measurement | #221 | 2026-09-06 |
| *The rosbag2 run* — the real profile names, the measured bags and the 1% band on the uncompressed projection | #232 | 2026-09-06 |
| The priced stream, as 24 columns and 19 Layer B | #123 | 2026-08-27 |
| Three sensitivity rows recomputed from the sizes | — | 2026-08-28 |
| The base pose on `robot_config`; the ladder re-measured, three rungs of it stale | #166 | 2026-09-02 |

### The sizes the Layer A re-measurement replaced

The provisional figures measured an artifact holding no Layer A record at all
(issue #59): occurrence went 18.9 GB → 263 GB, transition 229.7 → 655 GB,
per-frame 589.3 → 952 GB. Today they are 265, 658 and 955 GB; #83, #82 and #166
account for the 0.8% between — run identity, the outer-envelope scalars and the
base pose on `robot_config`, itemised in [`lossiness.md`](lossiness.md),
*Retained* #8.

The attribution is to #59 because it moved the figures by an order of magnitude
and established that no resolution level coarsens a record — which put the
coarsest level at 3,120 of 3,166 node rows and made the control rate the
artifact's second variable. Before it, coarsening the scene bought more.

### What the two re-measurements did to the conclusion

Before Layer A entered the artifact the three-order threshold sat at
0.104 TB/day and the published assumption cleared it tenfold; issue #60 is where
three orders stopped being available and #68 is where the two-order band went at
1 kHz. Both times the multiplier stayed at 1 TB/day and the two-order conclusion
at 50 Hz did not move.

### An outside estimate, checked

Issue #68 arrived with a reviewer's estimate of ~5.1 TB per robot per six months
at 1 kHz, ~36x, flagged as unverified. The measured figures are 4.73 TB and ~39x:
directionally right and slightly pessimistic, for the reason *The control rate*
gives — it assumed the whole level scales, and 1.5% of it does not.

### Whose work the incumbent ratio was waiting on

Translating the 11.76x into Claim 1 was not #117's work but its successor's: the
two comparisons were not composable, five columns on one side and 24 on the
other. Issue #220 closed that, and [`retention.md`](retention.md) now publishes
one ratio of the artifact against the bag. `README.md`, [`plan.md`](plan.md),
[`retention.md`](retention.md) and [`prior-art.md`](prior-art.md) still carry the
condition that no rosbag2 run stands behind the figures, and still carry the two
retired preset names; #232 measured the bags and left that republication to the
issue that depends on it.

### What the 2026-09-06 re-measurement moved, and why

This section published **2.51x** and **7,669 B** from 2026-08-26. That figure is
superseded: it priced chunk compression as though rosbag2 applied it by default
and left the message index out, so it modelled a configuration a practitioner has
to select and undercharged even that one. Both errors made the incumbent look
cheap, which made this project's disadvantage look worse than it is — the same
direction of error the gzipped-CSV baseline has. Correcting them gives 35,893 B
at the default preset and 11,685 B at the compressed one, against the same
3,053 B of gzipped CSV.
