# Retention — what it costs to keep the artifact

**Status:** normative for every retention figure this project publishes ·
re-measured 2026-08-20 (issue #60), with later work carrying its own issue
number where it sits — #98's Layer-A comparison, #116's label and byte
attribution · extracted from [`plan.md`](plan.md) Claim 1 on 2026-08-31, **with
no figure changed** · keep current

**What is machine-checked here, and it is less than the whole file.**
`tests/test_published_figures.py` re-derives four things from the code on every
CI run: the control-rate ladder's **50 Hz row**, the coarsest level's **label**
and the record and node counts behind it, the **byte attribution**, and the
**Layer-A comparison** table. Everything else is prose or arithmetic over those —
including the six-month totals in the resolution table below, `265 GB` among
them, and every ratio against the sensor assumption. That module's own *What this
does not cover* is the authority on the boundary; this line exists so that
nothing here reads as guaranteed when it is not.

This is [`plan.md`](plan.md) Claim 1's measurement record. It lives in its own
file because it is not a plan: it is a set of measured figures, the arithmetic
behind them, and the record of how they moved. `plan.md` states the claim and
the conditions that travel with it, and republishes the headline figures; the
derivations, the ladder and the record of the corrections are here.

**The artifact side of every figure here is measured on the fixed-base planar
arm** — 2–3 revolute links, base at the origin. That is a condition on all of
them, and moving the robot would move all of them. The **control rate** is not a
single condition in the same way: the resolution table below is at the 50 Hz
`reg.scenarios.DEFAULT_DT` runs at, and *The control rate* then measures the
same curve at 100 Hz, 250 Hz and 1 kHz. Every table says which rate it is at,
because every figure in them is linear in it.

**This document has been wrong twice and the corrections are kept in place
rather than tidied away** — refuted against a baseline that was never the claim,
then republished against an artifact that turned out to hold no Layer A at all.
The record of how a number moved is worth more here than a clean statement of
where it landed, in a project whose argument is that evidence should survive its
own revision.

---

**What the claim is, and where it is stated.** Retention is the enabling
condition for Claim 4 rather than a rival to it: an attestation you cannot afford
to keep until the claim is filed is worthless. The property the rest of the
argument needs is *cheap enough to keep for the mandated window*, not *smaller
than the alternative by the largest available factor* — which is why this is
named Retention and no longer Compression. The claim itself, with the conditions
that travel with every figure below, is [`plan.md`](plan.md) Claim 1.

**Success, as originally stated:** 2–4 orders of magnitude, one number, one chart.

> **Reframed 2026-08-19, and this reframing is a correction to a correction.**
> This record first had Claim 1 as *refuted*, on a benchmark that
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
until 2026-08-21. `README.md` and [`plan.md`](plan.md)'s regulatory table always
cited it correctly; the slip was under the headline number, which is where it
would have been read.)

**And that floor is subordinate to data-protection law, which nothing here
prices** (issue #101). Both Articles set the six-month period *"unless provided
otherwise in applicable Union or national law, in particular Union law on the
protection of personal data"*, and the artifact contains personal data. Every
figure below is what it costs to keep the artifact for the mandated window; none
of them is a claim that keeping it for that window is permitted. Stated in full,
once, where the claim is: [`plan.md`](plan.md) Claim 1. The entry it rests on —
with Art. 26(7) and the DPIA obligation named, and no claim of compliance — is
[`limitations.md` §8](limitations.md).

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
| **occurrence (±1 s) — 98.5% attestation records** | **265 GB** | 26.5 TB |
| transition (10 ms) | 658 GB | 65.8 TB |
| per-frame (10 ms) | 955 GB | 95.5 TB |
| *raw sensor log @ 1 TB/day (assumed, **not measured here**)* | *182.5 TB* | *18.2 PB* |

Each is the measured `bytes/hour` for that level — 60.42, 150.15 and
218.00 MB/h — times the 4,380 hours in the 182.5-day retention floor. **Every
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

At occurrence resolution the artifact is **~689x smaller** than the sensor
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
hundredfold — while three orders needs 1.45 TB/day, which the published
assumption does **not** reach, and four needs 14.5 TB/day. The robust claim is
the one to make, and it is now a narrower one. It is also, conveniently, the
resolution the only mandated evidence recorder in existence operates at (UN R157
DSSAD, ±1.0 s). The finer levels are weaker again: transition clears two orders
only above ~0.36 TB/day and per-frame only above ~0.52 TB/day.

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

A reader who took *DSSAD-shaped* at face value concluded that this is a
DSSAD-equivalent event recorder priced at 265 GB. It is not. It is a **per-action
attestation record** with an occurrence layer attached, and 265 GB is
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
   cost 265 GB. A recorder holding this level's 42 occurrence rows and none of
   its 3,120 records would be a far smaller file, and this project has not
   measured one.
2. **The lever on the 265 GB is the attestation cadence**, not the occurrence
   vocabulary. Declaring per behaviour segment rather than per control step
   would cut the term that dominates; it is a design change to what the artifact
   attests, it is held open, and *The control rate* below says so again where it
   bites hardest.

## The control rate — and it is not two orders at 1 kHz

> **Measured 2026-08-21 (issue #68).** `python -m reg.bench --control-rate-hz
> 50,100,250,1000 --seed 0`: the resolution curve at four control rates over one
> fixed run duration (59.98 s of robot time), same seed, same envelope
> parameters, same record parameterization. The 50 Hz row is the published curve
> above, reproduced byte for byte, which is what makes the other three
> comparable to it. Measured points only — nothing here is fitted or
> extrapolated.

Every figure in the resolution table above is a figure **at 50 Hz** and every one
of them **moves with that rate**, because enforcement emits one verdict and one
chain record per commanded action and no resolution level coarsens them. The
declaration count does not move with the rate at all — the policy replans on a
wall-clock interval — so the verdicts are the whole of the growth **in rows**.
The growth in *bytes* is slower than that, and *Why the growth is sublinear*
below is where the difference is attributed rather than asserted. A real
manipulator control loop runs at 1 kHz, twenty times this simulator's rate:

| control rate | occurrence | transition | per-frame |
|---|---|---|---|
| **50 Hz (this simulator, published above)** | **60.42 MB/h → 265 GB → ~689x** | 150.15 MB/h → 658 GB → ~277x | 218.00 MB/h → 955 GB → ~191x |
| 100 Hz | 106.57 MB/h → 467 GB → ~391x | 247.19 MB/h → 1.08 TB → ~169x | 410.37 MB/h → 1.80 TB → ~101x |
| 250 Hz | 247.32 MB/h → 1.08 TB → ~169x | 529.79 MB/h → 2.32 TB → ~79x | 1.04 GB/h → 4.56 TB → ~40x |
| **1 kHz (a real manipulator)** | **1.08 GB/h → 4.73 TB → ~39x** | 2.08 GB/h → 9.11 TB → ~20x | 4.52 GB/h → 19.80 TB → ~9x |

The `MB/h` column is measured. The six-month size is that figure times the 4,380
hours in the retention floor, and the ratio is against the **assumed** 182.5 TB
sensor log — an assumption, unchanged, at 1 TB/day
([`sensor-baseline.md`](sensor-baseline.md)).

**The ratio is computed from the six-month size *as published here*, not from the
unrounded product.** At 50 Hz that is `182.5 TB / 265 GB = ~689x`, where the
unrounded 264.64 GB would give ~690x. Both are defensible and the difference is
inside the `~`; what is not defensible is leaving the choice unstated, because
the two conventions disagree on two of the four rungs and nothing in the
repository derives these ratios to check them. Stated here so a reader who
recomputes and gets the other answer knows which step they took differently.

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
robot retains **4.73 TB** for the mandated six months and the artifact is
**~39x** below the assumed sensor log — **one order of magnitude, not two**, and
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
*Why the growth is sublinear* below, and was stated wrongly here until
issue #116.

**What is not done here.** Declaring per behaviour segment rather than per
control step would cut the term that scales, and it is the dominant lever: the
verdict layer is essentially all of the growth. It is a design change to the
attestation cadence, held pending its own decision, and issue #68 explicitly
does not take it.

## Why the growth is sublinear, and why the cause given here was wrong

**What this record said for three milestones:** *the scene rows and the fixed
schema-and-index cost do not scale with the rate.* Both clauses are true. Neither
term is anywhere near large enough to turn a 20x rate increase into 15.8x, and
the term that is large enough was not named at all (issue #116). The 15.8x is a
measurement and it has not moved; what follows replaces the account of it.

Bytes per table, from SQLite's own `dbstat`, on the **50 Hz** rung of the ladder
above — which is the published curve, so this attributes the very artifact
Claim 1 prices:

| table, coarsest level at 50 Hz | bytes | share of the level |
|---|---|---|
| `verdict` | 551,936 | 54.8% |
| `declaration` | 185,344 | 18.4% |
| `indexes + schema` | 131,072 | 13.0% |
| `node` | 112,640 | 11.2% |
| `meta` | 10,240 | 1.0% |
| `occurrence` | 9,216 | 0.9% |
| `entity` | 3,072 | 0.3% |
| `envelope`, `robot_config`, `edge` — one empty page each | 3,072 | 0.3% |
| **file** | **1,006,592** | |

1. **The scene rows are 5,120 B**, 0.5% of the level: `entity`, `envelope` and
   `robot_config` together, two of the three being a single empty page at this
   level. Half a percent of a file cannot account for a fifth of its growth.
2. **`indexes + schema` is not the artifact's fixed cost.** It is 131,072 B
   here and most of it is indexes *over rows*, which arrive with the rows and
   leave with them. The genuinely fixed part is the schema: an artifact created
   and never written to is **26,624 B** — `reg.store.create(path,
   record_tables=True)`, ten tables and their indexes at `reg.store.PAGE_SIZE` —
   which is 2.6% of this level.
3. **The mass the control rate does not move is the `declaration` table**, at
   185,344 B and 18.4% of the level. The fixture's policy replans on a
   **wall-clock** interval, so it emits the same 120 declarations at every rung
   of the ladder — `tests/test_bench.py` asserts exactly that, because a
   declaration count that started tracking the frame clock would invalidate the
   study — and a declaration row is fat: ~1,545 B against a verdict row's
   ~184 B, because it carries the declared region as a polygon. Twenty times the
   control rate buys twenty times the verdicts and **no** further declarations.
   An 18.4% share at 50 Hz is a share of about 1% at 1 kHz, and that dilution is
   where the difference between 20x and 15.8x goes.

**The two terms it named come to 31,744 B, 3.2% of the level; the
term it did not name is 185,344 B, 18.4%.** The stated cause is smaller than the
one that carries the effect by a factor of **5.8**. Issue #116 estimated the miss
at ~15x, reading it off *row* counts; measured in bytes it is 5.8x against the
term that actually carries it. Same direction, same conclusion, and now an
arithmetic anybody can re-run.

**And it is no longer a document's job to be right about it.** `reg.bench`
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

**This is a purchasing decision, not a slogan.** 265 GB buys *did contact
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

## The measured result against the wrong baseline, kept because it bounds the design


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

### The same comparison, measured on the artifact that carries Layer A

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
| artifact on disk | 2,584,576 B |
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

Nothing here changes the conclusion this comparison exists for. The answer to
*is the graph smaller than the stream it replaces* is still **no**, by rather
more than it looked, and for the same structural reason.

### Success, restated to something a measurement can meet or miss

These are the criteria the *record* is held to — three live and one kept for the
record — naming what has to be measured, labelled and reported before a figure
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
4. Superseded, and kept for the record: *until a measured length clears 1.0, the
   retainable-artifact argument does not rest on compression.* It was written
   when the wrong baseline was believed to be the right one. It rests on
   compression again, correctly stated — and on Claims 2–4 — query, sufficiency
   boundary, attestation — none of which needs the artifact to be smaller than
   the stream. The prohibition this criterion carried — no compression ratio as
   the commercial argument while the measured one is below 1 — is **not**
   superseded and is not stated here, because a binding rule inside a bullet
   headed *superseded* is a rule nobody can safely cite. It is
   [`plan.md`](plan.md) Claim 1's, where the code that obeys it already points.

The original criterion is kept above rather than deleted: it is what the project
set out to show, and the gap between it and the table is the finding.

## Why it lost — three things the measurement exposed (2026-08-19)

**1. The baseline was never the thesis.** The claim argues from
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

## What replaces it: resolution as the measured variable

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


## See also

- [`plan.md`](plan.md) Claim 1 — the claim these figures serve, and the
  conditions that travel with each of them wherever it is quoted.
- [`sensor-baseline.md`](sensor-baseline.md) — where the sensor side comes from.
  It is an assumption with a sourced range, never a measurement, and the
  sensitivity table there is what the ratio's robustness rests on.
- [`lossiness.md`](lossiness.md) — the three resolution levels being priced, and
  what each of them can still be asked.
- [`limitations.md`](limitations.md) §5 — the rate ceiling above which an
  artifact cannot address every frame of the run it prices. Two rungs of the
  ladder above are beyond it.
- [`prior-art.md`](prior-art.md) §8 and §16 — why the artifact loses to a float
  codec, and the incumbent (rosbag2/MCAP) that a bag-shaped baseline would be.
- `python -m reg.bench --resolution --seed 0 --out runs/resolution.md` — the
  command that produces the resolution table; swap `--resolution` for
  `--control-rate-hz 50,100,250,1000` for the ladder. **`--out` is required and
  has no default**, so neither command runs without it — a report that went
  somewhere nobody named is one nobody can check. `--control-rate-hz` has no
  default either; `--seed` does, and is passed explicitly above so the run is
  reproducible from the line as written.
