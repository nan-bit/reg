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

## 1. Recomputed envelope geometry assumes the same code and the same shapely

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

**What a claim would need instead.** Retaining every polygon — which is what this
project did until issue #28 measured the artifact at 20–30x *larger* than a gzipped
CSV of the stream it replaced — or an exact, versioned geometry kernel whose output
is specified rather than implementation-defined. Neither is in scope for a
prototype. The mitigation actually taken is to name the dependency: every artifact
records `reg_version` and the retention rule, and this section is the statement that
`reg_version` alone is not sufficient — **the shapely and GEOS versions that built
an artifact are not currently recorded in it, and recording them would let a future
reader know whether to trust a recomputation rather than having to assume.** That is
a small, obvious follow-up and it is deliberately not smuggled in here.

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

**What.** `reg.enforce.horizon_bound(state, limits, window)` is the radius the
check uses, and it is the smaller of two things:

- `computed_bound(limits)`, the radius of the **workspace disc** —
  `sum(link_lengths) + link_radius`, centred on the base that `reg.kinematics`
  fixes at the origin. Its argument is `Limits` alone, so it reads no `q`, no `qd`
  and no horizon and is the same scalar at every frame of every scenario.
- `outer_radius(outer_envelope(state, limits, window))`, the radial projection of
  the horizon-limited outer reachable set of §2 — which does read the state and the
  window.

The containment test against it is exact: a disc is convex, so a polygon lies
inside it iff every vertex does, and no polygonal rendering of a circle enters the
comparison.

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
call at artifact close, and the README claims air-gapped operation. `reg/commit.py`
is built as an interface — `(ChainHeads) -> Commitment` — precisely so that
dropping the air-gap claim makes either one an adapter rather than a rewrite.
Until then the supportable claim is exactly: **the records were not edited, and a
second party at the same site saw the heads.**
