# Limitations

**Status:** normative for what this project may claim · started 2026-08-18 · keep
current

[`docs/plan.md`](plan.md) Phase 10 lists this file as a deliverable and names what
it must eventually cover: inner-approximation sampling, 2D only, ground-truth
perception, no dynamics, a scripted policy, and both chain keys in one process.
Those land with the phases that create them; adding one here is part of finishing
that phase, not a separate decision. **This file exists early because a limitation
is worth least once nobody remembers it was a choice.**

Each entry says what the limitation *is*, what it costs, and what a claim would
need in order not to inherit it. None of them is a bug: a bug is a defect against
an intent, and every one of these is an intent stated out loud.

---

## 1. Recomputed envelope geometry assumes the same code, shapely and platform

**What.** Most `envelope` rows in an artifact carry `geometry_wkb = NULL`. The
polygon was discarded because it is a deterministic function of things the artifact
does store — the `robot_config` the row names, plus `horizon`, `n_samples`,
`envelope_seed` and `substep_dt` in `meta` — and
`reg.graph.envelope_at(conn, t)` recomputes it on demand. The rule for which frames
keep their geometry is [`docs/lossiness.md`](lossiness.md) *Discarded* #9, and it is
recorded in each artifact under `meta['envelope_geometry_retention']`.

**The cost.** "Deterministic" is deterministic *for the same code and the same
shapely version*. `reg.envelope.compute_envelope` unions sampled link polygons and
`reg.tolerances.simplify_geometry` runs Douglas–Peucker over the result; both are
GEOS operations, and GEOS is entitled to change its output in a release. So an
assessor opening a five-year-old artifact against a newer shapely may get a polygon
that differs from the one that was computed at build time — and on a discarded frame
there is nothing in the file to notice the difference against. The frames that
*kept* their geometry are the exception: there the stored polygon is authoritative
and a recomputation that disagrees with it is detectable, which is exactly what
`tests/test_graph.py::test_envelope_at_recomputes_the_stored_polygon_exactly`
checks. Those frames are the ends of the run and the transitions an incident report
cites, so the geometry a report quotes is stored rather than recomputed — but the
frames *between* them are recomputed, and their fidelity is conditional.

Two consequences worth being precise about, because they are not the same:

- **`envelope_hash` still detects the drift, on every frame.** The hash was computed
  at build time over the polygon as it then was. A recomputation that disagrees can
  be caught by rehashing it, on a stored frame or a discarded one. What the artifact
  cannot do is *repair* the disagreement on a discarded frame — it can only report
  it.
- **It does not touch the attestation layer.** Declarations, verdicts and the hash
  chain (Layer A) are stored in full and hash nothing that a geometry library
  computes. `verify_chain()` is unaffected by this limitation.

**The platform is a second axis, and it is recorded even less than the first.**
"Deterministic" is also deterministic *on one architecture*. `sin` and `cos` come
from whatever libm the interpreter was linked against, and IEEE-754 does not pin
either of them; a GEOS build is entitled to the same freedom. This is measured
rather than supposed: the repository's own bit-identity tables —
`tests/test_kinematics.py::test_the_demo_arm_at_the_origin_is_bit_identical_to_before_the_base_moved`
and
`tests/test_envelope.py::test_the_outer_set_at_the_origin_is_bit_identical_to_before_the_base_moved`
— pin hex float literals captured on x86_64 Linux, and four of those
parametrizations differed in their last bits on arm64 Darwin (issue #175).

**The cost of that axis, in the same two directions.** An assessor recomputing a
discarded envelope from a five-year-old artifact on a different architecture can
get a polygon that differs from the one built at the time, for a reason the
artifact does not record and cannot state. On a *stored* frame the disagreement
is visible — `shapely.equals_exact(..., tolerance=0.0)` is what
`tests/test_graph.py::test_envelope_at_recomputes_the_stored_polygon_exactly`
compares with, deliberately at zero tolerance — and it is visible as a bare
disagreement: nothing distinguishes *the geometry moved* from *this is a
different machine*, and those call for opposite responses. And the first bullet
above does not rescue it: `envelope_hash` is taken over coordinates quantized to
`reg.envelope.HASH_COORD_PRECISION`, nine decimal places, chosen so that
last-bit noise cannot change the digest. So the hash detects the drift it was
built to detect — a recomputation that moved by more than a nanometre — and an
ulp-scale platform difference passes it silently. That is the right trade and it
is worth stating in this direction: on this axis a matching `envelope_hash` is
not evidence that the two polygons are the same bytes.

**What a claim would need instead.** Retaining every polygon — which is what this
project did until issue #28 measured the artifact at 20–30x *larger* than a gzipped
CSV of the stream it replaced (24 columns for the priced fixture, 19 of them
Layer B — not proprioception, whatever this comparison was called before issue
#123) — or an exact, versioned geometry kernel whose output is specified rather
than implementation-defined. Neither is in scope for a prototype. The mitigation
actually taken is to name the dependency: every artifact records `reg_version`
and the retention rule, and this section is the statement that `reg_version`
alone is not sufficient — **the shapely and GEOS versions that built
an artifact are not currently recorded in it, and recording them would let a future
reader know whether to trust a recomputation rather than having to assume.** That is
a small, obvious follow-up and it is deliberately not smuggled in here.

**What a claim would need instead, for this axis.** The same versioned,
specified-output geometry kernel the paragraph above asks for, plus correctly
rounded transcendentals — a claim of bit-identity across architectures needs the
whole stack to be specified, not merely deterministic. Short of that, an artifact
would have to record the platform it was built on (`platform.machine()` and
`platform.system()`, beside the shapely and GEOS versions named above) so a
recomputation that disagrees can be read as *wrong machine* rather than as *the
geometry moved*. **It records none of them today.** What has been done is
the smaller, in-repository half: each bit-identity table now records the platform
it was captured on and reports an explicit could-not-evaluate — the repository's
third state, warned so it is audible and skipped so it never reads as a pass —
when the suite runs anywhere else, while the moved-base negatives stay ungated so
a real divergence is still red on every platform. `CLAUDE.md` rule 2 carries the
same qualifier, because *same seed, same bytes* is checked by two CI runs on one
platform.

**What this limitation is not.** It is not a reason to distrust the *retained*
answers. Every `INTERSECTS`, `SEPARATION` and `CONTACT` interval, every
`overlap_area` and `min_distance`, and every envelope `area` and `envelope_hash` was
computed at build time and is stored. Nothing in the supported question set
([`docs/lossiness.md`](lossiness.md)) is answered by recomputing a polygon; the
polygon is what a reader draws, inspects, or re-intersects when going beyond that
set.

---

## 2. The envelope the graph records is an under-approximation

Stated here because [`docs/prior-art.md` §4](prior-art.md) requires it to be, in the
right vocabulary, and because a reader who meets the word "envelope" will assume the
safety-relevant direction.

`reg.envelope.compute_envelope` samples a finite set of constant-acceleration
control sequences, forward-integrates each, and unions the bodies they pass through.
A finite sample can only **under-cover** the true forward reachable set. That is the
polygon `HAS_ENVELOPE` points at, the one `envelope_hash` covers, and the one every
`INTERSECTS` interval was measured against, and it is unchanged by anything below:
the evidence graph records the region the robot *demonstrably swept*.

**What issue #82 changed, precisely.** There is now a second region —
`reg.envelope.outer_envelope(state, limits, horizon)` — which over-covers: the
horizon-limited joint box pushed through the forward kinematics as an interval, so
every configuration the arm can reach in the window has its body inside it. It is
**not** stored as geometry and does not replace anything. What the artifact retains
of it is two scalars per computed envelope, `outer_area` and `outer_radius`, which
bracket the sampled area from the other side.
`tests/test_envelope.py::test_no_bang_bang_trajectory_escapes_the_outer_envelope`
is what makes it a bound rather than an estimate, and it ships with the negative
that proves the test can fail.

So the statement about *this* project's answers, in the two directions:

- "the robot **could have** reached (x, y)" — supported, as before, from the
  sampled envelope: every point in it is reachable.
- "the robot **could not have** reached (x, y)" — now supported **for a point
  outside the outer set**, which for a retained frame means *at a radius greater
  than `outer_radius`* from the base. The artifact stores the outer set's radius
  and area, not its boundary, so the answer a *stored* row alone gives is radial.
  The full region is recomputable from the `robot_config` and `horizon` the row
  already names, at which point the answer is the region's, not the disc's; that
  recomputation inherits §1's dependence on the geometry library exactly as the
  inner one does.
- Between them lies the gap the bracket makes visible rather than closes: a point
  inside the outer set and outside the sampled one is one the artifact says
  nothing about.

**What a tighter version would need.** The interval push-forward here is looser
than the zonotope and polynomial-zonotope machinery of **ARMTD** and **ARMOUR**
([`docs/prior-art.md` §4](prior-art.md)), which [`docs/plan.md`](plan.md) still
de-scopes, and it is kinematic: `qdd_max` stands in for a torque limit and there is
no dynamics model behind it. `reg.envelope`'s module docstring lists the three
further sources of under-coverage in the *inner* set (substep sampling, flat link
caps, constant-accelerations only) and the four steps of the outer construction,
and is the authority on both.

---

## 3. The overclaim check is radial: it bounds how far, not which way

Stated here because a reader meets the phrase "the independently computed physical
bound" in [`docs/plan.md`](plan.md) Phase 4 and in `reg.enforce`'s fault taxonomy,
and will reasonably read it as *what this robot could reach from here* — a
reachable set. It is a disc around one.

**What.** `reg.enforce.horizon_bound(state, limits, window, substep_dt)` is the
radius the check uses. It is always
`outer_radius(outer_envelope(state, limits, window))`, the radial projection of
the horizon-limited outer reachable set of §2 — which reads the state, the window
and, since issue #163, the base's own actuation bounds. Whether there is a
**second** term to take a minimum with is a property of the robot, and issue #164
is where that stopped being a constant:

- **A base that cannot move** — every `Limits` in this repository, and every
  fixture and figure in it. The bound is the smaller of the projection and
  `computed_bound(limits)`, the radius of the **workspace disc**,
  `sum(link_lengths) + link_radius`, centred on the base that `reg.kinematics`
  fixes at the origin. Its argument is `Limits` alone, so it reads no `q`, no
  `qd` and no horizon and is the same scalar at every frame of every scenario.
  Both terms over-cover, and the minimum of two sound bounds is sound.
- **A base that can drive** — any nonzero base bound. The projection alone,
  because `computed_bound` **refuses**, naming the field. The disc is finite only
  while the base is bolted down (§9): a driven base reaches everywhere given
  enough time, so there is no horizon-free radius to compute, and an unbounded
  workspace is a could-not-evaluate rather than a gap to fill with a large
  plausible number that would VETO while looking principled. Taking a minimum
  with the arm-only disc would have been worse than either — the minimum of a
  sound bound and an unsound one is not a sound bound.

**So for a mobile robot every VETO rests on `outer_envelope`'s soundness
argument alone**, and
`tests/test_envelope.py::test_no_bang_bang_trajectory_escapes_the_outer_envelope`
becomes the load-bearing test rather than merely a good one.
[`prior-art.md`](prior-art.md) §23 records both halves of what that costs: the
literature's answer to an unbounded workspace is not refusal but a **verified
fail-safe manoeuvre** re-verified each planning step — which `reg` cannot adopt,
because that guarantee lives inside the planner (the common-cause structure
[`../CLAUDE.md`](../CLAUDE.md) rule 3 refuses) and because passivation reaches no
table, edge type or query, so this project cannot represent a stop to rest a
bound on. And the consolation: RTD's own reachable set is horizon-limited and
per-step, so resting on the outer envelope alone is the position that literature
works from, not a degraded one.

The containment test against the bound is exact: a disc is convex, so a polygon
lies inside it iff every vertex does, and no polygonal rendering of a circle
enters the comparison.

**What issue #82 closed.** Before it, only the first bound existed, and
`envelope_overclaim` therefore fired only on a declaration exceeding the **entire
workspace**. The fault a Simplex / ASTM F3269 runtime monitor exists to catch — the
policy declared more than it could occupy within the horizon — was undetectable.
It is now detected whenever the overclaim is *radial*: an arm folded at the elbow,
or one whose velocity bound will not carry it to full extension within the window,
is bounded well inside the disc, and a declaration reaching between the two is
vetoed.
`tests/test_enforce.py::test_envelope_overclaim_fires_on_a_region_inside_the_workspace_disc`
is that case, with the positive control beside it: the same declaration offered
from a pose that *can* honour it is accepted.

**The cost, which is what remains.** The bound is a radius, so an overclaim that is
**angular** rather than radial is still undetected — a region of a reachable radius
in a direction the robot cannot turn to inside the window. `outer_envelope` is the
polygon that would catch those and it is computed; using it for *containment*
rather than for its radius is a decision issue #82 leaves open, not an oversight,
and the reason is measurable: against the eleven fixtures, the polygon test
re-labels three of the five fault runs as overclaims. `declared_violation`'s
declared joint box spans an elbow range the arm cannot sweep in half a second, and
`stale_declaration` and `escalation_failure` declare regions covering the frames
their silent windows stretch past their stated horizon. Each of those is arguably a
real overclaim; the point is that adopting the polygon test changes what a fault in
the nine-fault taxonomy *means*, and [`docs/prior-art.md` §5](prior-art.md) cites
that taxonomy as a contribution. Changing a fault's meaning is not a refactor.

Two things this limitation is **not**:

- **It is not a weakness in the independence.** Enforcement computes this bound
  itself from `Limits` and the origin, imports from `reg.declare` no further than
  `Declaration` and `ACTION_CLASSES`, and imports nothing from Layer B at all;
  both restrictions are asserted against the module's own AST in
  `tests/test_enforce.py`. It is the *capability* that is limited, not the
  separation. Softening the import rule to buy a tighter bound would trade the
  mechanism for the measurement.
- **It is not unsound.** Both terms over-cover the true reachable set and the
  minimum of two sound bounds is sound, so no truthful declaration is ever vetoed
  by this check — the error is entirely in the permissive direction, which is the
  correct direction for something whose response is VETO. Comparing against
  `reg.envelope.compute_envelope` instead would be the tempting move and the wrong
  one: that is the *under*-approximation of §2, and a declaration larger than a
  sampled envelope is the expected result for an honest policy, so vetoing on it
  would cry wolf. The other eight faults in the taxonomy — staleness, replay, MAC,
  vocabulary, watchdog, no-declaration, escalation failure and the
  declaration/action mismatch — are decided against the record, not against a
  reachability bound, and none of them inherits this.
- **It is not a bound the enforcer can skip.** `Enforcer.offer` takes the
  proprioceptive state as a required second argument, with no default: the tighter
  bound is a function of where the arm is and how fast it is moving, and an
  enforcer that invented a state would compute a plausible bound for a robot that
  was somewhere else.

**What the supportable claim now is, exactly.** *An overclaim is detected iff the
declared region reaches further from the base than the robot can, within the window
the declaration itself states.* The angular half is what a tighter version would
add, and the tighter version is already computed — see the paragraph above for why
adopting it is a decision rather than a step. `reg/enforce.py`'s module header is
the authority on why a loose sound bound is preferred to a tight unsound one.

---

## 4. A Layer A envelope is Layer A only if its `Limits` are

Stated here because §3 above calls `Limits` "a property of the robot rather than
of its state", and that is true of its *shape* and not guaranteed of its numbers.

**What.** `compute_envelope` has two inputs. The first, `ProprioState`, is kept
out of Layer B by structure: it has no field naming an entity and
`tests/test_layer_boundary.py` fails if one appears. The second is `Limits`, and
that enforcement does not reach it — not because `Limits` is trusted, but because
the mechanism inspects **field names** and the problem arrives in a **value**.
`qd_max` is an innocent name whatever produced the number in it. Under **ISO/TS
15066 / ISO 10218-2:2025 speed-and-separation monitoring** — the practice
[`docs/plan.md`](plan.md) cites approvingly, and how collaborative robots actually
run — the commanded speed bound *is* a function of a measured separation
distance. Feed one in and the envelope integrated under it depends on a perceiver.

**The cost, and what issue #84 changed about it.** The dependence is real either
way; what was wrong was that nothing recorded it, so an SSM-derived envelope
carried a Layer A tag and no query, no `CHECK` constraint and no field-name test
could tell it from a datasheet one. `Limits` now carries `source: LimitSource`,
required and with no default, `reg.envelope.envelope_layer` maps it to a layer,
and the `HAS_ENVELOPE` edge is tagged from that rather than from its type —
`PROPRIOCEPTIVE` gives `A`, `DERIVED` gives `B`. The provenance is persisted in
`meta['limits_source']` so a recomputed envelope (§1) inherits it too, and an
artifact that does not carry the key is a **could-not-evaluate**: nothing reads
its absence as the clean case, and `reg.graph._limits_from_meta` refuses rather
than reconstructing a `Limits` nobody vouched for.

Two things this **is not**:

- **It is not a claim that a Layer B envelope is worth less.** The geometry is
  identical under either provenance — the same polygon, the same hash — and
  `tests/test_layer_boundary.py::test_the_layer_moved_and_the_geometry_did_not`
  is the gate on that. What differs is whose failure modes the answer inherits,
  which is the only thing the layer tag ever meant.
- **It is not inherited by §3's enforcement bound.** `computed_bound` reads
  `link_lengths` and `link_radius` and nothing else: link geometry is
  proprioceptive under SSM as much as anywhere, because the arm does not get
  shorter when a human walks in. So the independence argument in §3 stands
  unchanged for a derived-limits run, and the veto is as strong — or as loose —
  as it is for any other.

**What a claim would need instead.** Nothing further for the *labelling*; that
part is closed. What remains open is the taxonomy itself: two values is a
simplification, an IEC 61496 PLd safety scanner is perception with characterized
failure modes and still lands in `DERIVED`, and modelling that honestly needs a
tag **plus an integrity attribute** rather than a binary.
[`docs/sufficiency.md`](sufficiency.md) §7 records why that was considered and
deferred — it rewrites what the project may claim, which is a decision and not an
implementation.

---

## 5. Above 100 Hz the artifact cannot address every frame of the run

Added 2026-08-21 (issue #77). Stated here because
[`docs/lossiness.md`](lossiness.md) advertises per-frame agreement predicates and
a reader will assume they hold at whatever rate their robot runs at. `reg` runs at
50 Hz, so nothing this project has published is wrong; **a real manipulator runs
at 1 kHz, and there the sentence below is what applies.**

This one arrived as a bug report rather than as a choice, which the preamble above
does not quite cover. The *defect* was the silence — a contract that advertised a
per-frame budget and never said what range it held in — and stating the range is
what closed it. The limit itself was always implied by a 10 ms quantum and is a
choice; nobody had noticed it was one.

**What.** Every interval endpoint in an artifact is rounded to
`TIME_TOL_S` = 10 ms, so the artifact's time base has `1 / TIME_TOL_S` = 100
addressable instants per second — **however fast the control loop ran**. At or
below 100 Hz each frame quantizes to its own instant and each retained value is a
value about one frame. Above it several frames share an instant, and a per-frame
value read back out of an interval is the value of whichever of those frames
opened it. At 1 kHz eleven frames share each instant.

**The cost, measured.** On `reg.scenarios.near_miss` at seed 0, resampled at each
rate: `separation_timeline` — query 1 of the supported set — misses its own
`DISTANCE_TOL_M` = 0.01 m predicate at rates above 100 Hz, by up to **0.0140 m**
at 1 kHz. Which rate it *first* misses at is a property of how fast the fixture
moves, not of the artifact, and is the reason the bound above is the structural
100 Hz rather than a measured number. The full ladder, its parameters, and the
four things it shows are in
[`docs/lossiness.md`](lossiness.md),
[The rate range these hold in](lossiness.md#the-rate-range-these-hold-in); this
section is what a *claim* inherits, not a second copy of the measurement.

**It is a quantization limit, not a sampling one**, and the distinction decides
what a fix would be. Two measurements separate them. The artifact stores **269
`SEPARATION` intervals at 1 kHz and 269 at 100 Hz** — it is not retaining less at
the higher rate, because there is nothing more it *could* retain; the time base has
no more addresses. And every value it reports is within `DISTANCE_TOL_M` of a true
separation of the run at some frame within `TIME_TOL_S` of the instant it is
reported at. Nothing was sampled away and no value is wrong. What is missing is
the ability to say which frame inside a 10 ms window a value belongs to.
`tests/test_graph.py::test_the_time_base_miss_is_quantization_and_not_sampling`
is that second measurement as an assertion.

**The honest sentence, since issue #77 asked for it if it was true.** *At 1 kHz
this edge layer cannot place a per-frame value at a frame within its published
tolerances.* It can still place it within 10 ms of one, which is what the artifact
now says about itself and what a reader is entitled to rely on. Everything else in
the supported question set is unaffected: they are interval and record queries, and
an interval whose endpoints are good to 10 ms is exactly what this contract always
promised.

**What this limitation is not.**

- **It is not a reason to widen `TIME_TOL_S`.** That moves the line rather than
  the behaviour — the failure mode this project exists to warn about — and it
  would make the rate *lower*, since the rate is the quantum's reciprocal.
  [`docs/plan.md`](plan.md) already calls the `DISAGREE` that surfaced this "a
  measurement, not a tolerance to widen", and issue #77 held the constant
  deliberately rather than tuning the finding away.
- **It is not a refusal to build.** A stream above 100 Hz is built normally and
  holds everything it otherwise would; refusing would delete evidence in order to
  avoid stating a limit, and would tell a 1 kHz robot it may not have an artifact
  at all. What the build does instead is record the fact: `meta[time_base_domain]`
  states the rule, `meta[time_base_addressable_instants]` counts this run's
  instants, `meta[time_base_resolves_frames]` is `yes` exactly when that equals
  `frame_count`, and `python -m reg.graph build` prints a note on stderr for the
  `no` case.
- **It does not touch Layer A.** Declaration and verdict timestamps are stored as
  the record carries them and are *not* quantized to `TIME_TOL_S` — the MAC covers
  them ([`docs/lossiness.md`](lossiness.md) *Retained* #5). `verify_chain`,
  `declared_bound`, `violations` and `verdicts` answer identically at 1 kHz.

**What a claim would need instead.** A time base whose resolution is at least the
control period — either `TIME_TOL_S` reduced to match the fastest rate the artifact
is meant to serve (which costs edge rows, since more values become distinguishable
and the incremental rule collapses fewer of them, and would have to be measured
rather than assumed), or endpoints stored as an integer frame index against the
`frame_period_s` already in `meta`, which addresses every frame exactly and makes
the quantum a display concern rather than a storage one. The second is the smaller
change and neither was taken here: both alter what the artifact claims, and issue
#77's scope was to characterise the limit and state it, not to move the line while
nobody was looking.

---

## 6. The commitment is an on-site witness, not a third-party timestamp

**What.** An artifact's two chain heads are committed at close by
`reg/commit.py`'s one shipped scheme, `witness-hmac-sha256-v1`: an HMAC over both
heads under the key of a **second on-site keyholder**, whose key is refused if it
is either of the two that signed the records. What that proves is exactly *a
second party at the same site saw these heads*. It is not timestamping, this
project will not describe it as timestamping, and the artifact itself carries the
sentence saying so (`meta[commitment_statement]`) so that a reader who has only
the file is not misled by the scheme name.

Beside it, `meta[run_start_utc]` is a **declared** instant, required with no
default. It places the run on a wall clock and it is a claim by the same party
that signed the records.

**What it costs.**

- **The instant is not attested.** A colluding operator and witness can date a
  re-issued history to whatever afternoon suits them, sign the heads over it, and
  produce a file in which every check passes. Nothing inside the artifact bears
  on that, and nothing inside an artifact can.
- **The independence is only as good as the site.** Two keyholders at one
  employer share a common cause the way `reg/enforce.py` and `declare/` would if
  one imported the other. The refusal in `check_witness_is_independent` catches
  the *mechanical* version of this — a witness holding a record-signing key — and
  not the organisational one.
- **Verification is three-valued, and the third value is common.** An artifact
  closed with no supplier reports COULD-NOT-EVALUATE and says `commitment: none`;
  so does one whose witness key the verifier does not hold. Neither ever resolves
  to VALID, which is correct and does mean an assessor frequently learns nothing
  from this check alone.

**What is *not* limited.** The half that catches a re-issued chain needs **no key
at all**: `verify_commitment` recomputes both heads from the records the artifact
actually holds and compares them against the recorded ones, so any holder of the
file can detect that the history no longer matches what was committed to. The
witness signature is what stops the recorded heads being rewritten to match. That
asymmetry is why the heads are stored beside the signature rather than only
inside it.

**What a claim would need instead.** A commitment to a party with no relationship
to the operator: an **RFC 3161** timestamp token, or inclusion in an append-only
**transparency log** (which would additionally make a *withheld* artifact
detectable — §8 and §9 of [`lossiness.md`](lossiness.md) Cannot answer). Both are
documented and deliberately unimplemented for one reason: each needs a network
call at artifact close, and this artifact is required to be checkable years later
with no service still running and no call to anyone. That requirement is not a
constraint the design works around — it is the reason the design exists. An
assessor certifying what happened needs a record whose integrity does not rest on
infrastructure belonging to the party being assessed, and the telemetry these
sites already emit runs on exactly that infrastructure. `reg/commit.py` is built
as an interface — `(ChainHeads) -> Commitment` — precisely so that a deployment
prepared to take the dependency gets an adapter rather than a rewrite.
Until then the supportable claim is exactly: **the records were not edited, and a
second party at the same site saw the heads.**

---

## 7. The chain has no forward security, and the verifier holds the keys

**What.** `reg/chain.py` is Schneier and Kelsey's 1998 construction for secure logs
on untrusted machines — per-record MAC, per-record hash link to the predecessor,
one canonical preimage, a walk that checks both — **minus the property that scheme
was written for.** In the original, the secret is evolved through a one-way
function after every entry and the old value is deleted, so an attacker who takes
the machine at time *b* can write whatever they like from *b* onward and can
neither forge nor undetectably alter anything written before it. `reg`'s keys are
static for the life of a run: `generate_keyring` draws from OS entropy once and
nothing evolves.

Beside it, a second asymmetry with the same root. In Schneier–Kelsey the verifier
`V` walks the chain and asks a trusted server `T` about the final MAC; `V` never
learns a key and therefore cannot forge. `reg` hands the auditor the keyring, so
**anyone who can verify a `reg` artifact can also forge one.**

Both are **named, deliberate absences, recorded here rather than discovered**
([`prior-art.md` §14](prior-art.md), issue #104). Neither is a defect against an
intent: the second is the price of offline verification with no trusted server, and
the first is a design question this project has not taken.

**What it costs.**

- **A stolen key is retroactive.** An attacker who obtains the enforcement key can
  rewrite and re-sign the *entire* verdict chain back to genesis, and the result
  verifies. Under forward security the same attacker gets everything after the
  compromise and nothing before it — which is the difference between "this
  artifact is worthless" and "this artifact is trustworthy up to a knowable
  instant".
- **It compounds the re-issuance limit the README already states.** That note says
  a chain under keys held by the record's own author cannot notice the whole
  history being re-run offline. Static keys are why: there is no point in the
  history at which the key that signed it no longer exists.
- **The auditor is not a safe place to put the keyring.** The honesty note says
  both keys in one process demonstrates the *structure* of non-repudiation rather
  than non-repudiation. This is the sharper version of the same sentence and it
  survives even after the enforcement key moves into hardware: whoever is given
  the keys to check the artifact is given the ability to produce a different one.

**What is *not* limited.** The half of the commitment check that catches a
re-issued chain needs **no key at all** — `verify_commitment` recomputes both heads
from the records the file holds and compares them against the recorded ones (§6).
So the verifier-holds-the-key asymmetry does not extend to that check, and an
assessor who is given the artifact and *not* the keyring can still detect that the
history no longer matches what was committed to.

**What a claim would need instead.** Key evolution — the 1998 scheme's `Aᵢ₊₁ =
H(Aᵢ)` with the old value erased, or a forward-secure aggregate MAC (Ma & Tsudik
2008), which additionally resists the truncation attack `chain.py`'s header
describes. Either changes **what an auditor must be given and when**: a verifier
that holds an evolved key cannot check records written before it, so verification
starts needing either the epoch boundaries or a party that kept `A₀`. That is a
Phase 6 design decision about key custody, not an encoding change, and it is open
([`prior-art.md`](prior-art.md), *Still open after this pass*). Until it is taken,
the supportable claim is exactly: **the records were not edited by anyone who did
not hold the keys, and the keys have been valid since the run began.**

## 8. The artifact contains personal data and this project has not addressed that

Added 2026-08-26 (issue #101). Every other section of this file limits what the
artifact can *answer*. This one limits whether it may be **kept**, which is a
different kind of limit and is why it went unwritten: before this section,
`grep -riE "gdpr|personal data|data protection|works council"` over `docs/` and
`reg/` returned nothing substantive, and the only matches for "worker" were
"worker host", the CI machine. It was the one large hole in this file with no
entry, in a repository whose credibility rests on stating its own holes first.

**Nothing here is legal advice and nothing here is a claim of compliance.** The
obligations below are named because they exist and because this project does not
discharge any of them. That is the same register as the six sections above it.

**What the artifact records about a person.** Per shift:

- the position-derived relationship between the robot and an entity whose `kind`
  is `human` — `INTERSECTS` and `SEPARATION` edges carrying `overlap_area` and
  `min_distance` to `DISTANCE_TOL_M` = 0.01 m, over intervals whose endpoints are
  good to `TIME_TOL_S` = 10 ms (`reg/store.py`, the `edge` table);
- `envelope_entered`, `envelope_left`, `contact_began`, `contact_ended` and
  `closest_approach` occurrences naming that entity, each with a DSSAD `date` and
  a wall-clock `t_utc` (`reg.store.OCCURRENCE_SPECS`);
- `meta[unit_id]`, `meta[operator_id]` and `meta[run_start_utc]` — three declared
  strings, all required, none with a default (`reg/identity.py`).

`operator_id` with `run_start_utc` is what turns the rest from telemetry into
personal data: together they select a shift, and a shift resolves against any
roster to a person. The proximity and contact record then attaches to that
person. Retained for six months and **handed to an assessor or an insurer** —
which is the use this project was built for — that is processing of personal data
in an employment context, and in Germany it is also a technical device objectively
suitable for monitoring workers' behaviour or performance under **§87(1)(6)
BetrVG**, which is subject to works-council co-determination *before the robot
runs*, not before the artifact is exported.

**The retention window is bounded from both sides and this project has only ever
cited one of them.** AI Act **Art. 19** (providers) and **Art. 26(6)** (deployers)
set the six-month period *"unless provided otherwise in applicable Union or
national law, **in particular Union law on the protection of personal data**"*.
The floor is expressly subordinate on its own face. So for the Layer B half of an
artifact six months may be a **ceiling** rather than a floor, and
[`docs/plan.md`](plan.md)'s Claim 1 is citation-correct and
**argument-incomplete**: it prices retaining an artifact for a window that
data-protection law may forbid it from filling. The two bounds come from different
instruments and this project has measured against one of them.

**Two further obligations, named and not discharged.**

- **Art. 26(7).** A deployer who is an employer must inform workers'
  representatives and the affected workers *before* putting a high-risk AI system
  into service at the workplace. Nothing in this repository produces that notice
  or records that it was given, and `meta` has no key that would say so.
- **A DPIA.** GDPR **Art. 35(1)** requires one where processing is likely to
  result in a high risk to data subjects; systematic monitoring of employees is on
  the Art. 35(4) lists national supervisory authorities publish, which is why one
  is near-certain here. Whether this processing also lands inside Art. 35(3)'s
  three enumerated cases is not a question this project is competent to answer.
  That there is no DPIA is not in doubt, and that is the part stated here.

**The minimisation is real, and it is in the schema rather than in a policy.**
`entity` holds four columns — `entity_key`, `kind`, `is_static`, `geometry_wkb` —
and not one of them names a person: the human's `node_id` is `human`, a role, and
the kind vocabulary is `human`, `crate`, `pillar`, `pallet`. There is no
biometric, no image and no raw frame; [`docs/lossiness.md`](lossiness.md)
*Discarded* #5 excludes raw sensor data "by construction", for a retention
reason, and the effect of that is a data-protection one. And the Layer A boundary
keeps the certifiable half clear of the person entirely: `ProprioState` has no
field naming an entity and `tests/test_layer_boundary.py` fails if one appears
(CLAUDE.md rule 1). **The artifact is data-minimising almost by accident** — a
consequence of a 2D simulator and a structural boundary drawn for a different
reason, not of a data-protection decision anyone took. Which is exactly why the
honest statement is *"this contains personal data and here is the minimisation
contract"* rather than silence. `tests/test_personal_data.py` is what turns the
accident into a contract: it fails if the `entity` table grows a column this
section does not disclose, or if `RunIdentity` grows a field it does not name.

**What this limitation is not.**

- **It is not an argument for dropping `operator_id`.** *Which robot, which
  shift* is what makes the file handable to an assessor at all, and Art. 73's
  15-day serious-incident clock cannot start against a record that will not place
  itself in time (`reg/identity.py`). The identifier is load-bearing for the
  purpose the artifact exists to serve. Two obligations pull in opposite
  directions here; that is a conflict to resolve in a deployment, not a defect to
  patch out of a prototype.
- **It is not confined to Layer B.** The identity block is **Layer A** —
  `reg/identity.py` says so in its first line — so discarding every entity-naming
  edge in the file would still leave an artifact stating which operator ran which
  unit from which instant. Minimisation cannot be reached by dropping Layer B, and
  the Layer A / Layer B boundary is not a personal-data boundary. It was never
  drawn to be one.
- **It is not something the retention rules already in `meta` address.**
  `GEOMETRY_RETENTION`, `ENVELOPE_RETENTION`, `OCCURRENCE_RETENTION` and
  `ATTESTATION_RETENTION` each state what a *build* keeps. None of them states how
  long the *file* may be kept, there is no deadline field and there is no erasure
  or expiry path anywhere in this codebase. An artifact carries no date after
  which it should not exist.
- **It is not inherited from DSSAD.** DSSAD is privacy-light precisely because it
  records authority transitions and system events and says nothing about third
  parties. `reg` borrows that schema shape and **inverts its privacy profile** —
  [`docs/prior-art.md` §9](prior-art.md) is where that is stated, beside the
  element-by-element mapping that borrows it.

**What a claim would need instead.** A DPIA on record; where §87(1)(6) BetrVG
applies, a works agreement in place before the robot runs; the Art. 26(7) notice
given and recorded; and a retention rule that is the **minimum** of the AI Act
floor and the data-protection ceiling, written into `meta` with the same
discipline as the four retention rules already there, so that a reader holding
only the file learns when it should have been destroyed. None of that is code this
prototype should invent: like `--run-start` and the keyring, each is a
caller-supplied input from a deployment that does not exist here, and a plausible
invented retention deadline would be indistinguishable downstream from a lawful
one. What this section does is stop the artifact reading as though the question
had been asked and answered.

---

## 9. Every result here is a fixed-base result, and two claims rest on that

Added 2026-09-01 (issue #136). The eight entries above limit what the artifact
can *answer* or whether it may be *kept*. Not one of them says that the robot
cannot move. That is the largest scoping assumption in the repository, and it
went unwritten for the reason such assumptions usually do: a fixed base was never
chosen frame by frame, it is the frame everything else was written in, so no line
of code ever had to mention it. [`docs/mobile-base.md`](mobile-base.md) is where
the consequences are worked out in full. This entry states the two that are
load-bearing *now*, because until they are stated, two things this project says
read as properties of the method when they are properties of the mounting.

**What.** `reg.kinematics` fixes the base at the origin — the explicit leading
`0.0` in its cumulative sums *is* the base — and nothing in `reg/` or `tests/`
models a robot pose at all: no transform, no pose field, no frame to carry one.
[`docs/mobile-base.md`](mobile-base.md) discusses a pose at length and models
none, being a design document for work that is not built. Every envelope, every
published figure and the bound `reg/enforce.py` VETOes on is computed for a
planar arm bolted down at the origin.

**The cost, first half: `computed_bound` is finite only because the base is
bolted down — and since issue #164 it says so.** `reg.enforce.computed_bound(limits)`
is `sum(link_lengths) + link_radius`, the radius of a workspace disc. §3 above
calls it "the same scalar at every frame of every scenario", which is exactly
right and is a fixed-base property: a driven base has an unbounded workspace —
given enough time it reaches everywhere — so no horizon-free radius exists for it
to compute. What inherited that was the description of the bound itself, and
that description has now been rewritten rather than amended. `CLAUDE.md` rule 3
and §3 both described `horizon_bound` as the **smaller of two sound bounds**
unconditionally; both now say which case each term applies to, because the
soundness of the first one is a trivial argument only while the disc is centred
on something that stays put. Remove the mounting and the first term is not a
looser bound, it is not a bound — so `computed_bound` refuses a `Limits` with any
nonzero base bound, naming the field, and `horizon_bound` rests on
`outer_envelope` alone for that robot.
`tests/test_envelope.py::test_no_bang_bang_trajectory_escapes_the_outer_envelope`
is therefore the load-bearing test for every mobile VETO rather than merely a
good one. [`docs/mobile-base.md`](mobile-base.md) §1 works that through,
including the origin-centred disc intersected *inside* `outer_envelope` — the
place where a moved base would produce an unsound bound that looks exactly like a
sound one, which is why issue #163 added the base's translation to that disc's
radius before this entry's refusal landed.

**Nothing in this repository changed behaviour when it landed.**
`reg.world.LIMITS` states four zeros, every fixture and every published figure is
a fixed-base run, and a fixed-base `Limits` gets exactly the disc it always got.
What changed is what the project may *claim* about a robot it does not ship.

**The cost, second half: world-frame reachability is Layer A only for a fixed
base.** [`docs/sufficiency.md`](sufficiency.md) §5.1 rests the certifiability of
*could the robot have reached (x, y) at t?* on "the answer inherits nothing from
perception". That holds here, and it holds because *the base is at the origin* is
a **mounting fact** rather than a measurement — free, and true without anybody
sensing anything. For a mobile robot the same sentence is a **localization**
output: map-based pose estimation runs on non-safety-rated sensing, and wheel
odometry drifts without bound under slip its encoders cannot observe. So the
identical question becomes Layer B, and what survives in Layer A is the
body-frame version of it — *could the robot have reached a point 1.2 m
ahead-left of its own base at t?* The fixed base hid the distinction by making
the two frames the same frame, which is why a project whose whole thesis is
tagging evidence with the layer it depends on did not already have this written
down. [`docs/mobile-base.md`](mobile-base.md) §2 and §2.1 carry it.

**What this half is, and is not.** It is a statement about the **present
artifact**: the question is Layer A for the robot this repository models, and
`sufficiency.md` §5.1 is correct as written. This entry does not reclassify it,
does not move a layer tag, and changes no behaviour, no figure and no line of
`docs/sufficiency.md`. Carrying §2.1's shrink of the certifiable question set
into `sufficiency.md` is a separate decision, tracked separately — see
[`docs/mobile-base.md`](mobile-base.md) §7, where it is Tier 1 and where
everything downstream of it waits. What is recorded here is the narrower and
immediately checkable thing: the Layer A status of world-frame reachability is
**conditional on the base being fixed**, and nothing in the code says so, because
there is no base-pose field for a condition to attach to.

**What a claim would need in order not to inherit this.** A claim that is not
about a bolted-down arm needs three things. The first now exists; the other two
do not. First, a bound that **refuses**: an unbounded workspace is a
could-not-evaluate under `CLAUDE.md`'s *a check must be able to fail*, and
`computed_bound` must say so for a mobile model rather than return a large
plausible number — a bound nobody can justify is worse than no bound, because
it VETOes while looking principled. **Issue #164 built it**, and
`horizon_bound` rests on the outer envelope alone for a driven base as a
consequence; what that buys is a bound that is *honest* about a mobile robot,
not a mobile robot this repository can run. Second, a base pose carried as an
explicit **Layer B** input with its provenance declared and no default, on the
precedent `Limits.source` set (§4, issue #84), so that a room-frame envelope is
visibly a perception-dependent object and a body-frame one is visibly not.
Third, the fixtures and figures to go with it: Claim 1 stays a fixed-arm claim,
[`docs/retention.md`](retention.md) says in its own header that the artifact
side of every figure in it is measured on the fixed-base arm — and that the
control rate is *not* a blanket condition in the same way, since its ladder
measures four of them — and nothing in this entry re-measures, retires or moves
any of them. Until all three exist, the supportable claim is exactly: **every
reachability answer in this artifact is an answer about an arm whose base is a
mounting fact, and the certifiability of the world-frame ones is inherited from
that fact rather than from the method.**

---

## 10. The base's contribution to the outer set is a disc, and a real base is not

Added 2026-09-02 (issue #163). §9 states that every result here is a fixed-base
result and that a driven base would leave every VETO resting on
`reg.envelope.outer_envelope`. This entry is what the first half of that work
actually bought and what it did not: the outer set now reads the base's four
actuation bounds, and it composes them into the geometry as a **disc**, which is
a much weaker description of a vehicle than it looks.

**What.** `reg.envelope.outer_envelope` bounds the base's own motion over the
horizon with two scalars — `base_motion_bounds(state, limits, horizon)` returns a
translation bound in metres and a yaw bound in radians, each the integral
`∫ min(|rate₀| + a·s, rate_max) ds` that the joint box is built from. The yaw
folds into the first joint's angular interval, which is exact. The translation is
**Minkowski-summed** with the arm's body-frame set — on a `shapely` polygon, one
`buffer` — so the vehicle is modelled as *able to be anywhere within `d_trans`
metres of where it started, in any direction*.

That last clause is the limitation. A differential-drive base is **nonholonomic**:
it cannot move sideways at all, so its true horizon-limited reachable set is a
curved, non-convex, Dubins-shaped region, and the disc over-covers it by a wide
margin. `docs/mobile-base.md` §3 works the geometry through and
[`prior-art.md`](prior-art.md) §24 has the literature: a zonotope
over-approximation of a Dubins car is already described as *large*, and it takes
**polynomial** zonotopes to capture the curvature at all. So the disc is not
merely loose — it is looser than the loosest thing that literature would publish.

**The cost.** Sound, and useless in proportion to how fast the base can drive.
Every VETO built on this bound errs in the permissive direction, so no truthful
declaration is refused; what is lost is detection. At a 0.2 s horizon and 0.8 m/s
the disc adds ~0.16 m of radius in every direction, and a declaration exceeding
the arm's reach by less than that is no longer caught. The looseness compounds
with §3's: that check is **radial**, and a radial bound is at its weakest exactly
where a nonholonomic base is — a vehicle that cannot turn is nowhere near the rim
of its own disc, so radial-plus-disc is close to no constraint on a base's
heading at all. **How much this costs has not been computed for this construction
by anyone**, here or elsewhere; it is a representation cost with no published
figure attached, and this file does not invent one.

**What it does not cost.** Nothing in this repository, today. `reg.world.LIMITS`
states `base_v_max = base_a_max = base_omega_max = base_alpha_max = 0.0`, both
terms are then exactly zero, and the outer set is bit-identical to the arm-only
one — `tests/test_envelope.py::test_the_outer_set_at_the_origin_is_bit_identical_to_before_the_base_moved`
compares the hex digits of the two retained scalars against the values computed
before any of this existed. No published figure moves, and §9's statement that
every result here is a fixed-base result is unchanged.

**It must be published as loose, and it is.** `reg.envelope.outer_envelope_looseness(limits)`
returns the sentence a caller reporting `outer_area_m2` or `outer_radius_m` has to
carry with it, and it returns a *different* sentence when the base can drive —
naming the disc and the nonholonomic gap. That is deliberately a value rather than
a docstring: the reader who would take an outer area for an estimate of where the
robot can get is reading an artifact, not this module. The same rule the layer tag
follows (§4, issue #84): a property of the answer that is decided by the `Limits`
it was computed from travels *with* the answer.

**What a claim would need in order not to inherit this.** A reachable set for the
vehicle rather than a bound on its displacement — RTD and REFINE compute exactly
that for ground robots, with the tracking error inside it, and CORA's conservative
linearization plus polynomial zonotopes is what makes the non-convexity
representable ([`prior-art.md`](prior-art.md) §23, §24). `reg` may not build it:
*no new dependencies* is a standing rule and *an HJ reachability solver* is a
stated non-goal in [`plan.md`](plan.md). A `shapely` polygon has no zonotope
arithmetic behind it, so every step of such a construction would be a buffer whose
error compounds — which is how the disc got here in the first place. Until then
the supportable claim is exactly: **the outer set contains everything a base
within these actuation bounds could do, and it contains a great deal that a
differential-drive base could not.**

---

## 11. A base velocity's provenance is recorded, and nothing reads it — and `qd` has none at all

Added 2026-09-03 (issue #156). [`sufficiency.md`](sufficiency.md) §5.9 is the
decision: a `BaseVelocity` filled from a perceiver is **not** Layer A, so
`reg.types.VelocitySource` is required on the type with no default and no
inference. This entry is the half of that decision which is not yet enforcement,
and the older hole it leaves standing next to it.

**What.** Two gaps, and they are different in kind.

*The tag does not follow the value.* `reg.envelope.envelope_layer` decides the
`HAS_ENVELOPE` edge's layer from `Limits.source` alone, and nothing anywhere maps
a `VelocitySource` member to a `Layer`. Meanwhile
`reg.envelope.base_motion_bounds` reads `state.base_vel` and integrates it into
the displacement term of `outer_envelope` (§10, issue #163) — which for a mobile
robot is the *only* bound a VETO rests on, since `reg.enforce.computed_bound`
refuses to produce a workspace disc for a base that can drive. So an outer set
whose base term came out of visual odometry is, today, tagged `A` on the strength
of its bounds having come off a datasheet. The same holds one level down in the
raw stream: `reg.bench.COLUMN_RULES` classifies `base_vel_source` as Layer A
beside the three rates it describes, because that classifier is **per column and
static** and the thing that decides the question is the *value in the cell*.

*`qd` carries no provenance at all.* `ProprioState.q` and `ProprioState.qd` are
Layer A by their kind, and nothing records where a particular run's numbers came
from. The argument that this is safe is a **deployment** one — joint state comes
off the actuator's own encoders on every arm this project would run on — and by
[`sufficiency.md`](sufficiency.md) §5.6's own standard that is the weaker kind of
argument, the kind somebody can answer by building a thing. A visual joint-state
estimator is that thing. The asymmetry that made the base velocity worth tagging
first is one of *likelihood*, not of structure: visual odometry is ordinary and
visual joint-state estimation is not.

**The cost.** An artifact can be internally honest and still read stronger than
it is. Everything issue #156 built is real — a `DERIVED` base velocity is
recorded as derived, survives the stream round trip, and cannot be confused with
an encoder-measured one — but a `WHERE layer = 'B'` query, which is what Claim 3
*is*, will not return the envelope over it. A reader who trusts the tag rather
than reading the `base_vel_source` column beside the rates gets the pre-#156
answer. For `qd` there is not even a column to read: an arm whose joint state
came from somewhere unusual produces an artifact indistinguishable from one whose
did not, and no query can be written that would find it.

**What it does not cost, today.** Nothing in this repository. No fixture is
mobile — `reg.world.LIMITS` states four base bounds of zero and every fixture
frame records `base_vel=None` — so no artifact this repository builds carries a
base velocity of either provenance, and every layer tag on every edge in every
fixture is the tag it was. *This paragraph used to add a third reason, that
`reg.enforce.Enforcer` refuses to construct for a driven base at all (issue
#164), and since issue #189 that is false: an enforcer constructs for one and
adjudicates it, resting on `horizon_bound` alone, and `Enforcer.bound` is `None`
for it because there is no workspace disc to report.* The entry is unaffected —
the reason nothing here carries a mistagged base velocity was always the
fixtures, and the enforcer's refusal was a belt beside that brace. What #189
changes is that the belt is gone: the first mobile fixture (mobile-base.md §7
Tier 4) will produce artifacts this entry is about, rather than failing to build
at all, so the gap below stops being hypothetical the moment one lands. No published figure moves: the stream's velocity block
is optional, `expected_header(2, 3)` is the 24 columns Claim 1 is priced on, and
`base_vel_source` appears only in a header no fixture writes.

**Why it was left here rather than closed.** The mapping is three lines and the
test for it is not: a `velocity_layer` written now would be exercised against no
mobile fixture, and the decision it forces — whether an envelope's layer is the
*minimum* over its inputs, and what that does to the four attestation edges §2's
asymmetry rests on — is the same decision [`sufficiency.md`](sufficiency.md) §5.8
holds open for a posed configuration, on purpose, until there is something in
hand the answer would be about. Writing it twice, separately, in advance of that
fixture is how the two answers end up disagreeing.

**What a claim would need in order not to inherit this.** Three things, in
order. (1) An envelope layer that is the weakest of its inputs rather than of one
of them — `Limits.source` **and** the provenance of every state value the bound
was computed from — decided once for the posed-configuration case and this one
together. (2) A provenance on `qd` on the same pattern, or a written argument
that a joint rate is structurally proprioceptive in a way a base rate is not;
this entry asserts only that the argument currently offered is the weaker kind,
not that no stronger one exists. (3) The graded integrity attribute
[`sufficiency.md`](sufficiency.md) §7 rejects for scope, if the claim needs to
distinguish a PLd-rated perceiver from an unrated one — which is what a real
assurance case does, and which the binary cannot express in either direction.
Until then the supportable claim is exactly: **this artifact records whether a
base velocity came from a perceiver, and its layer tags do not yet depend on the
answer.**
