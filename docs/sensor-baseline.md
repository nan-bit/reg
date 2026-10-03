# The sensor-log baseline

**Status: an assumption with a sourced range, not a measurement.** The sensor
rate is the one input the benchmark cannot produce, so it is stated with a
source, a range and a sensitivity. The artifact side is measured, at a stated
control rate.

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

## What the projection is measured against

The simulator's state stream is the whole of the benchmark's input: for the
fixture priced it is **24 columns and 19 of them are Layer B**
(`reg.stream.expected_header(2, 3)`) — the five proprioceptive columns beside
the human and obstacle entity state a real system would have to perceive; see
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
`python -m reg.bench --resolution --seed 0` at a 50 Hz control rate. Each
size is that level's measured `bytes/hour` — 61.03, 191.57 and 295.32 MB/h —
times the 4,380 hours in the retention floor. The
sensitivity establishes *the shape of the dependence*; the conclusion drawn from
it is the two paragraphs after the crossover table.

| sensor rate | log at 6 months | vs occurrence (267 GB) | vs transition (838 GB) | vs per-frame (1,293 GB) |
|---|---|---|---|---|
| 0.1 TB/day | 18.2 TB | 68x | 22x | 14x |
| 0.5 TB/day | 91.2 TB | 342x | 109x | 71x |
| **1 TB/day (published)** | **182.5 TB** | **684x** | **218x** | **141x** |
| 5 TB/day | 912.5 TB | 3,418x | 1,089x | 706x |
| 21.3 TB/day (cited max) | 3,887 TB | 14,559x | 4,639x | 3,006x |

**What survives the whole range and what does not.** The crossovers are
**derived, not measured** — `threshold_TB_per_day = size_GB * 10^orders / 1000 /
182.5`, so occurrence at two orders is `267 * 100 / 1000 / 182.5 = 0.146` — and
they are recomputed from the sizes above rather than carried over:

| level | clears 2 orders above | clears 3 orders above |
|---|---|---|
| occurrence | 0.146 TB/day | 1.463 TB/day |
| transition | 0.459 TB/day | 4.592 TB/day |
| per-frame | 0.708 TB/day | 7.085 TB/day |

At occurrence resolution the claim clears **two** orders of magnitude at any
sensor rate above 0.146 TB/day — seven times below the published assumption, and
below every cited configuration carrying a camera, including HIW-500's compressed
~0.5 TB/day. A motion-only stream at 800 B/s is 0.07 GB/day and clears nothing.
The two-order conclusion therefore does not need the assumption right to within a
factor of a few. **Three orders needs 1.46 TB/day, which it does not reach.**

At the finer levels it is weaker still. **Per-frame retention clears the plan's
two-order criterion only above ~0.71 TB/day, and transition only above
~0.46 TB/day** — both within a factor of three of the published assumption, so
neither survives it being wrong by an order of magnitude. Below those rates the
artifact is still smaller than the log, but not by the margin Claim 1 asserts.
The plan's *upper* bound of four orders is reached at occurrence resolution only
above 14.6 TB/day: inside the cited range, far above the assumption, so it is not
available and must not be quoted.

So **the claim should be stated at occurrence resolution and at two orders** —
not two-to-three, never four. That is also the level the only mandated evidence
recorder in existence (UN R157 DSSAD, ±1.0 s) operates at: the robust claim and
the regulated one are the same.

## The control rate

**Status: measured, on the artifact side.** The artifact sizes are **linear in
the robot's control rate**, and this simulator's rate is not a manipulator's.

**Measured** 2026-08-21, re-measured 2026-09-08 and 2026-09-09, from one run of
`python -m reg.bench --control-rate-hz 50,100,250,1000 --seed 0`: the resolution
curve at four control rates over **one fixed run duration**, 59.98 s of robot
time, at one seed and the parameter block [Sensitivity](#sensitivity) states. The
frame count moves with the rate because it must — 3,000 frames at 50 Hz, 59,981
at 1 kHz — and everything else is held still, so two rows differ only in how
often the robot acted. The 50 Hz row reproduces the published curve exactly,
which is what makes the other three comparable to it.

| control rate | frames | records retained | occurrence | transition | per-frame |
|---|---|---|---|---|---|
| **50 Hz (published above)** | 3,000 | 3,120 | **61.03 MB/h** | 191.57 MB/h | 295.32 MB/h |
| 100 Hz | 5,999 | 6,119 | 107.00 MB/h | 314.74 MB/h | 563.22 MB/h |
| 250 Hz | 14,996 | 15,116 | 247.75 MB/h | 676.31 MB/h | 1.47 GB/h |
| **1 kHz (a real manipulator)** | 59,981 | 60,101 | **1.08 GB/h** | 2.64 GB/h | 6.51 GB/h |
| *x, 50 Hz → 1 kHz* | *20.0x* | *19.3x* | *17.7x* | *13.8x* | *22.1x* |

Those are measured points. **Nothing between them is interpolated and nothing
beyond them is extrapolated** — a rate nobody ran is not in the table, however
obvious it would look on a line through the ones that are. They are also a
**manual measurement**: only the 50 Hz row is re-measured by
`tests/test_published_figures.py` on every CI run, and leaving the pin there
rather than extending it to the ladder is recorded in
[`retention.md`](retention.md), *The control rate*. The 250 Hz and 1 kHz rows sit
above `reg.tolerances.TIME_BASE_MAX_RATE_HZ` = 100 Hz, so their artifacts cannot
address every frame they price ([`limitations.md`](limitations.md) §5).

### What it does to the claim

What the claim becomes at each rung is [`retention.md`](retention.md)'s
six-month table, and what the rungs above 100 Hz can and cannot be asked is
[`limitations.md`](limitations.md) §5. This section keeps only the sensor side,
which does not move.

**The sensor assumption is not adjusted to compensate.** It is the same
1 TB/day it has been since this document was written, for the same sourced
reasons, and it has stood through every re-measurement that moved the artifact
side (see [Why](#why)). The input has a range and the conclusion is what moves.

## The incumbent encoding: rosbag2 / MCAP

**Status: a projection from the published specification, checked against a real
encoder and against rosbag2.** What is *measured* is the byte stream an encoder
written here from the spec produces on real fixture data; what is *projected*
is that a rosbag2 writer lays out the same bytes. The uncompressed figures came
back exact and the compressed ones outside the registered band are marked where
published.

### The comparison

Same information on both sides — `t`, `q`, `qd` for a two-joint arm, 251 frames
of the `declared_violation` fixture at 50 Hz, uncompressed and compressed both
priced:

| Encoding | Size | x gz CSV |
|---|---|---|
| CSV, gzip -9 | **3,053 B** | 1.00x |
| MCAP, `none` — uncompressed, chunked, indexed | **35,893 B** | **11.76x** |
| MCAP, `zstd_fast` / `zstd_small` — zstd chunks, indexed | **11,685 B** | **3.83x** |

The names are `--storage-preset-profile` values
(`reg.bench.ROSBAG2_STORAGE_PRESET_PROFILES`). `none` is what a bag costs when
nobody chooses, so **what a practitioner retains without choosing anything costs
11.76x the gzipped CSV**.

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

**This document does not restate the headline.** The ratio above is an encoding
ratio over 5 columns of 24; [`retention.md`](retention.md) is where Claim 1's
headline meets it, on the whole-stream figures below.

### Assumptions, each of which can move the number

These govern both tables in this section — the same encoder over different
columns of the same fixture.

- **`none` is a floor; the compressed figure is not** — every assumption below cheapens the uncompressed bag, so 11.76x understates the incumbent; the compressed figure rests on gzip -9 for zstd, so neither compressed whole-stream figure stands.
- **File-level records excluded** (~1-2 kB fixed) — negligible at scale, material at 251 messages, favouring MCAP.
- **The per-message index is included** at 16 B per message under every profile priced (measured 16.06 B) — the honest charge, rosbag2's default; `fastwrite` not priced.
- **Joint names `joint_0` / `joint_1`, empty `frame_id`, empty `effort`** — real robots use longer names, making MCAP look worse.
- **`sensor_msgs/msg/JointState` with position and velocity only**; **XCDR1 little-endian**, the ROS 2 default.

### The Layer B asymmetry, and what closing it costs

The two sides of the table above do not carry the same information about the
world, and the comparison is only honest with that stated. The fixture stream
carries `human_x`, `human_y`, `human_vx`, `human_vy` — **simulator ground truth
for the person**. No robot's `/joint_states` holds that and no bag does; a real
system carries perception output and the sensing behind it, neither priced
here.

That table therefore prices **proprioception only, on both sides**: five of the
fixture's 24 columns, and the section below prices the other nineteen. Neither
prices the *sensing* behind a real system's version of those nineteen — the
expensive half, and the half this document projects rather than measures.

### The same encoding, over the whole stream

**What a real system publishes for the world half is a decision, and the decision
is the deliverable.** `reg.bench.LAYER_B_OPTIONS` prices the candidates and
`cheapest_layer_b_option` takes the **smallest** — the arrangement most
favourable to the incumbent:

| arrangement for the 19 Layer B columns, 3,000 frames | `none` | `zstd_fast` / `zstd_small` |
|---|---|---|
| **`/tf`** — one `tf2_msgs/TFMessage` per control period, one `TransformStamped` per entity | **1,209,000 B** | **170,628 B** [^v] |
| `geometry_msgs/PoseStamped` per entity per control period, each on its own topic | 1,476,000 B | 315,225 B |

`/tf` is smaller either way and is chosen either way: it carries the
per-message MCAP framing and the 16 B message index once per control period
instead of once per entity.

**`visualization_msgs/MarkerArray` is the third candidate and it is not priced.**
A Marker states an extent in `scale`; the stream carries one for each obstacle
and none for the human, and nothing here may choose one. A plausible metre would
sit inside a published byte count looking exactly like a measured one, so
`reg.bench.marker_cdr` refuses that entity by name — and refusing it costs the
comparison nothing, since a Marker is dearer per entity term by term.

**The bag, both halves, over the same 3,000-frame fixture the retention figures
are measured on:**

| Encoding, all 24 columns | `none` | `zstd_fast` / `zstd_small` |
|---|---|---|
| `/joint_states` — the 5 proprioceptive columns | 429,000 B | 136,500 B |
| `/tf` — the 19 Layer B columns | 1,209,000 B | 170,628 B [^v] |
| **the bag, projected** | **1,638,000 B** | **307,128 B** [^v] |
| the same 24 columns as CSV, gzip -9 | 64,652 B | 64,652 B |

[^v]: **Outside the validation band; this figure does not stand.** A real MCAP
    encoder produced 154,040 B for `/tf` and 284,259 B for the bag — out by
    -9.72% and -7.45% against a +/-5% band registered ahead of it. It
    overstates the incumbent, which flatters this project; the uncompressed
    column beside it is exact.
    [Validating the projection](#validating-the-projection-against-a-real-bag).

**What is published against that gzipped CSV is the bag rosbag2 wrote**, not the
projection above — [the rosbag2 run](#the-rosbag2-run), whole files, same
columns, same frames: **25.34x** uncompressed with no profile passed
(1,637,963 B), **5.58x** at `zstd_fast` (360,798 B), **3.90x** at `zstd_small`
(252,034 B).

[`retention.md`](retention.md), *The same comparison, measured on the artifact
that carries Layer A*, is where these become a ratio against the artifact.

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

A specification can be read correctly and applied to the wrong configuration, so a projection nobody outside this repository can regenerate is an assertion ([`prior-art.md`](prior-art.md) §27). Reproduce: `python -m reg.sim --scenario declared_violation --seed 0` / `--scenario long_run_3000 --seed 0`; republish each row as ROS 2 messages — `sensor_msgs/msg/JointState` on `/joint_states`, `tf2_msgs/msg/TFMessage` on `/tf` with `frame_id` from `reg.bench.LAYER_B_PARENT_FRAME` — XCDR1, `log_time` and `sequence` per row; record with rosbag2's MCAP plugin, 768 KiB chunks, presets `none` / `zstd_fast`; compare the per-message scaling total against `reg.bench`'s byte functions. The verdict tolerances are constants fixed in `reg.bench` ahead of the measurement (`MCAP_VALIDATION_TOLERANCE`), not chosen after seeing the numbers. Measured 2026-09-06 by the reference Python MCAP writer (`mcap` 1.4.0, `mcap-ros2-support` 0.5.7, `zstandard` 0.25.0); rosbag2's own writer not exercised — full provenance in `reg.bench.MCAP_VALIDATION_PROVENANCE`.

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

### The rosbag2 run

`ros2 bag record` itself, on both fixtures, by
[`scripts/record_rosbag2.py`](../scripts/record_rosbag2.py).
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
  and marked about a model now rather than about a missing measurement. What is
  published is the two bags, as a pair.

`reg.bench.ROSBAG2_SIZE_MEASUREMENTS` holds the ten rows and derives each verdict
from its own byte counts; `tests/test_incumbent_encoding.py` fails if page and
record disagree.

### What would retire this section

A compressed projection that models one of the two zstd profiles — the profiles bracket the projection, so a standing compressed figure has to name which one.

## A premise this document does not carry: air-gapped sites

The air-gap premise — that full sensor logs cannot leave an air-gapped site — is **retired, not repaired**.

## What would retire this document

A measured figure from a fielded humanoid — sensor manifest, sample rates, codec,
duty cycle, and a logged byte count over a known interval. Until then the honest
form is the one used throughout: an explicit multiplier, a linear sensitivity, and
the word *projection* on every number derived from it.

That retires the *sensor* side only; the control rate is the other half and is
already measured rather than assumed. The rosbag2/MCAP projection retires
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

The multiplier stayed 1 TB/day through every re-measurement.
