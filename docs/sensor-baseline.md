# The sensor-log baseline

**Status: an assumption with a sourced range, not a measurement.** Written
2026-08-19, before the re-measurement run, because it is the one input the
benchmark cannot produce and the first thing a robotics safety reader will check.

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
| **Retention window** | 182.5 days (EU AI Act Art. 12 six-month floor) |
| **Implied continuous rate** | 11.6 MB/s over 24 h, or 34.7 MB/s over an 8-hour shift |

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
the rate and every ratio halves. Against the pre-#54/#55 artifact sizes, over the
182.5-day retention floor:

| sensor rate | log at 6 months | vs occurrence (18.9 GB) | vs transition (229.7 GB) | vs per-frame (589.3 GB) |
|---|---|---|---|---|
| 0.1 TB/day | 18.2 TB | 966x | 79x | 31x |
| 0.5 TB/day | 91.2 TB | 4,828x | 397x | 155x |
| **1 TB/day (published)** | **182.5 TB** | **9,656x** | **795x** | **310x** |
| 5 TB/day | 912.5 TB | 48,280x | 3,973x | 1,548x |
| 21.3 TB/day (cited max) | 3,887 TB | 205,675x | 16,923x | 6,596x |

**What survives the whole range and what does not.** The exact crossovers, in
assumed sensor rate:

| level | clears 2 orders above | clears 3 orders above |
|---|---|---|
| occurrence | 0.010 TB/day | 0.104 TB/day |
| transition | 0.126 TB/day | 1.259 TB/day |
| per-frame | 0.323 TB/day | 3.229 TB/day |

At occurrence resolution the claim clears **two** orders of magnitude at any
sensor rate above 10 GB/day — a hundred times lower than the published
assumption and far below every cited configuration. That conclusion is robust
and does not depend on the assumption being right. Three orders needs
0.104 TB/day, which the published assumption clears tenfold but a very light
sensor suite would not.

At the finer levels it is not robust. **Per-frame retention clears the plan's
two-order criterion only above ~0.32 TB/day, and transition only above
~0.13 TB/day.** Below that the artifact is still smaller than the log, but not
by the margin Claim 1 asserts. And the plan's *upper* bound — four orders — is
reached at occurrence resolution only above ~1.04 TB/day, so it holds at the
published assumption with almost no margin and should not be quoted as though
it had any.

So **the claim should be stated at occurrence resolution and at two-to-three
orders**, not four. That is also the level the only mandated evidence recorder
in existence (UN R157 DSSAD, ±1.0 s) actually operates at — the robust claim and
the regulated one are the same claim, which is convenient rather than
coincidental.

## What would retire this document

A measured figure from a fielded humanoid — sensor manifest, sample rates, codec,
duty cycle, and a logged byte count over a known interval. Until then the honest
form is the one used throughout: an explicit multiplier, a linear sensitivity, and
the word *projection* on every number derived from it.

## See also

- [`plan.md`](plan.md) Claim 1 — where the projection is quoted
- [`lossiness.md`](lossiness.md) — the three resolution levels being priced
- [`prior-art.md`](prior-art.md) §8 — why the artifact loses to a float codec, and
  why that is not this comparison
