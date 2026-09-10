# Limitations

**Status:** normative for what this project may claim · started 2026-08-18 · keep
current

Each entry says what the limitation *is*, what it costs, and what a claim would
need in order not to inherit it. None of them is an error against an intent:
every one is an intent stated out loud.

**How to read this file.** §§1–12 are the normative core and are readable
without anything below them. Under [`## Why`](#why) is rationale — how an entry
came to be stated in the shape it is — and nothing there is normative.
[`docs/plan.md`](plan.md) Phase 10 lists this file as a deliverable and names
what it must eventually cover: inner-approximation sampling, 2D only,
ground-truth perception, no dynamics, a scripted policy, and both chain keys in
one process. Those land with the phases that create them; adding one here is
part of finishing that phase, not a separate decision.

---

## 1. Recomputed envelope geometry assumes the same code, shapely and platform

**What.** Most `envelope` rows in an artifact carry `geometry_wkb = NULL`. The
polygon is a deterministic function of things the artifact does store — the
`robot_config` the row names, plus `horizon`, `n_samples`, `envelope_seed` and
`substep_dt` in `meta` — and `reg.graph.envelope_at(conn, t)` recomputes it on
demand. Which frames keep their geometry is
[`docs/lossiness.md`](lossiness.md) *Discarded* #9, recorded in each artifact
under `meta['envelope_geometry_retention']`.

**The cost, on two axes.** "Deterministic" is deterministic *for the same code
and the same shapely*: `reg.envelope.compute_envelope` unions sampled link
polygons and `reg.tolerances.simplify_geometry` runs Douglas–Peucker over the
result, both GEOS operations, and GEOS is entitled to change its output in a
release. It is also deterministic *on one architecture*: `sin` and `cos` come
from whatever libm the interpreter was linked against, and IEEE-754 pins neither.

**The second axis is measured rather than supposed, and the measurement is kept
in the suite.** The repository's bit-identity tables —
`tests/test_kinematics.py::test_the_demo_arm_at_the_origin_is_bit_identical_to_before_the_base_moved`
and
`tests/test_envelope.py::test_the_outer_set_at_the_origin_is_bit_identical_to_before_the_base_moved`
— pin hex float literals captured on x86_64 Linux, four of those
parametrizations differ in their last bits on arm64 Darwin, and each table
therefore records the platform it was captured on and reports an explicit
could-not-evaluate — the repository's third state, warned so it is audible and
skipped so it never reads as a pass — anywhere else. The moved-base negatives
stay ungated, so a real divergence is still red on every platform. `CLAUDE.md`
rule 2 carries the same qualifier, because *same seed, same bytes* is checked by
two CI runs on one platform.

**What the artifact records.** `meta` carries a buildinfo read off the running
interpreter at build time — `reg.store.ENVIRONMENT_KEYS`, which names the six
keys and why each is one. Putting it inside `meta` rather than beside the
artifact is a stated deviation from the Reproducible Builds practice
([`prior-art.md`](prior-art.md) §27) with Claim 2 as its reason.

**What the code does with it.** `reg.graph.envelope_at` refuses to recompute a
discarded polygon off the recording environment. It compares five of the six
keys — `reg.graph.RECOMPUTE_ENVIRONMENT_KEYS`: the platform's system and
machine, shapely, GEOS and numpy — and where any differs it raises, naming the
key and both values. **It refuses rather than warning**, because a recomputed
polygon that reaches a caller under a warning is a polygon that reaches a query
result, and nothing downstream carries the qualifier.

**Compared and recorded-only are two stated lists, not a list and a remainder.**
The second, `reg.graph.RECORDED_ONLY_ENVIRONMENT_KEYS`, holds the interpreter
alone: a Python patch release arrives from a distribution, on machines nobody
chose to upgrade, so triggering on it would make every artifact unrecomputable
there and teach whoever met the refusal to switch the check off. numpy is
compared, at its full version: it places every link endpoint, a reader installs
it deliberately, and a coarser comparison would assert a bit-identity across
patch releases that numpy does not promise.

**What the refusal does not buy, and the wording is held to it.** It says the
environments differ and names the key. It does not say which difference moved
the geometry — nothing in that path has compared any geometry, and attribution
needs a differ, which `diffoscope` is and this project has no analogue of
([`prior-art.md`](prior-art.md) §27). So this is the **weaker half of
attribution**: an unresolvable disagreement becomes a stated could-not-evaluate,
and not an answer about which library is responsible. Agreement on the
*compared* keys is **necessary and not sufficient**, on two counts. The C
library is recorded nowhere, because `platform.libc_ver()` reports nothing on
macOS and under musl and a key empty on some platforms would mean both *could
not tell* and *nothing to tell*, so two artifacts can agree on all six and have
been linked against different libms. The interpreter is the other: recorded, not
compared, and the price of not crying wolf.

**What remains on a stored frame.** Only recomputation is conditional. A
retained polygon was computed at build time, is evidence in its own right, and
is handed over on any machine — so an artifact stays readable everywhere, and
what stops at the machine boundary is the part that was always conditional.
There a disagreement is visible — `shapely.equals_exact(..., tolerance=0.0)` is
what
`tests/test_graph.py::test_envelope_at_recomputes_the_stored_polygon_exactly`
compares with, deliberately at zero tolerance — and it is visible as a *bare*
disagreement: nothing distinguishes *the geometry moved* from *this is a
different machine*, and those call for opposite responses. `envelope_hash` does
not rescue it: the hash is taken over coordinates quantized to
`reg.envelope.HASH_COORD_PRECISION`, nine decimal places, chosen so that
last-bit noise cannot change the digest. It therefore detects the drift it was
built to detect — a recomputation that moved by more than a nanometre — and an
ulp-scale platform difference passes it silently. **On this axis a matching
`envelope_hash` is not evidence that two polygons are the same bytes.**

Two consequences worth being precise about, because they are not the same:

- **`envelope_hash` still detects geometry drift, on every frame.** The hash was
  computed at build time over the polygon as it then was, so a recomputation
  that disagrees can be caught by rehashing it, on a stored frame or a discarded
  one. What the artifact cannot do is *repair* the disagreement on a discarded
  frame — it can only report it.
- **It does not touch the attestation layer.** Declarations, verdicts and the
  hash chain (Layer A) are stored in full and hash nothing that a geometry
  library computes. `verify_chain()` is unaffected by this limitation.

**What a claim would need instead.** Retaining every polygon — which is what
this project did until the artifact was measured at 20–30x *larger* than a
gzipped CSV of the stream it replaced (24 columns for the priced fixture, 19 of
them Layer B, and not proprioception) — or an exact, versioned geometry kernel
whose output is specified rather than implementation-defined, plus correctly
rounded transcendentals: a claim of bit-identity across architectures needs the
whole stack to be specified, not merely deterministic. Neither is in scope for a
prototype. The mitigation actually taken is to name the dependency, and this
section is the statement that `reg_version` alone is not sufficient.

**What this limitation is not.** It is not a reason to distrust the *retained*
answers. Every `INTERSECTS`, `SEPARATION` and `CONTACT` interval, every
`overlap_area` and `min_distance`, and every envelope `area` and `envelope_hash`
was computed at build time and is stored. Nothing in the supported question set
([`docs/lossiness.md`](lossiness.md)) is answered by recomputing a polygon; the
polygon is what a reader draws, inspects, or re-intersects when going beyond
that set.

---

## 2. The envelope the graph records is an under-approximation

Stated here because [`docs/prior-art.md` §4](prior-art.md) requires it to be, in
the right vocabulary, and because a reader who meets the word "envelope" will
assume the safety-relevant direction.

**What.** `reg.envelope.compute_envelope` samples a finite set of
constant-acceleration control sequences, forward-integrates each, and unions the
bodies they pass through. A finite sample can only **under-cover** the true
forward reachable set. That is the polygon `HAS_ENVELOPE` points at, the one
`envelope_hash` covers, and the one every `INTERSECTS` interval was measured
against: the evidence graph records the region the robot *demonstrably swept*.

**The second region, and what the artifact keeps of it.**
`reg.envelope.outer_envelope(state, limits, horizon)` over-covers — the
horizon-limited joint box pushed through the forward kinematics as an interval,
so every configuration the arm can reach in the window has its body inside it.
It replaces nothing. What every computed envelope retains is the two scalars
`outer_area` and `outer_radius`, which bracket the sampled area from the other
side; the **boundary** is retained on the rows that keep the sampled polygon and
on no others (`reg.graph.GEOMETRY_RETENTION`).
`tests/test_envelope.py::test_no_bang_bang_trajectory_escapes_the_outer_envelope`
is what makes it a bound rather than an estimate, and it ships with the negative
that proves the test can fail.

So the statement about *this* project's answers, in the two directions:

- "the robot **could have** reached (x, y)" — supported, from the sampled
  envelope: every point in it is reachable.
- "the robot **could not have** reached (x, y)" — supported **for a point
  outside the outer set**, and what a stored row gives depends on the row. Where
  the boundary is retained the answer is the region's; elsewhere it is *at a
  radius greater than `outer_radius`* from the base, a disc, and the region is
  recomputable from the `robot_config` and `horizon` the row already names —
  which inherits §1's dependence on the geometry library as the inner one does.
- Between them lies the gap the bracket makes visible rather than closes: a
  point inside the outer set and outside the sampled one is one the artifact
  says nothing about.

**What a tighter version would need.** The interval push-forward here is looser
than the zonotope and polynomial-zonotope machinery of **ARMTD** and **ARMOUR**
([`docs/prior-art.md` §4](prior-art.md)), which [`docs/plan.md`](plan.md) still
de-scopes, and it is kinematic: `qdd_max` stands in for a torque limit and there
is no dynamics model behind it. `reg.envelope`'s module docstring lists the
three further sources of under-coverage in the *inner* set (substep sampling,
flat link caps, constant-accelerations only) and the four steps of the outer
construction, and is the authority on both.

---

## 3. The overclaim check is radial: it bounds how far, not which way

Stated here because a reader meets the phrase "the independently computed
physical bound" in [`docs/plan.md`](plan.md) Phase 4 and in `reg.enforce`'s
fault taxonomy, and will reasonably read it as *what this robot could reach from
here* — a reachable set. It is a disc around one.

**What.** `reg.enforce.horizon_bound(state, limits, window, substep_dt)` is the
radius the check uses. It is always
`outer_radius(outer_envelope(state, limits, window))`, the radial projection of
the horizon-limited outer reachable set of §2, which reads the state, the window
and the base's own actuation bounds. Whether there is a **second** term to take
a minimum with is a property of the robot:

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
is the load-bearing test rather than merely a good one.
[`prior-art.md`](prior-art.md) §23 records both halves of what that costs: the
literature's answer to an unbounded workspace is a **verified fail-safe
manoeuvre** rather than a refusal, which `reg` cannot adopt — that guarantee
lives inside the planner, the common-cause structure
[`../CLAUDE.md`](../CLAUDE.md) rule 3 refuses, and this project can represent no
stop to rest a bound on — and, in consolation, that RTD's own reachable set is
horizon-limited and per-step, so resting on the outer envelope alone is the
position that literature works from.

The containment test against the bound is exact: a disc is convex, so a polygon
lies inside it iff every vertex does, and no polygonal rendering of a circle
enters the comparison.

**What the check detects.** A **radial** overclaim, whenever the declared region
reaches past the horizon-limited projection: an arm folded at the elbow, or one
whose velocity bound will not carry it to full extension within the window, is
bounded well inside the workspace disc, and a declaration reaching between the
two is vetoed. That is the fault a Simplex / ASTM F3269 runtime monitor exists
to catch, and
`tests/test_enforce.py::test_envelope_overclaim_fires_on_a_region_inside_the_workspace_disc`
is that case, with the positive control beside it: the same declaration offered
from a pose that *can* honour it is accepted.

**The cost, which is what remains.** The bound is a radius, so an overclaim that
is **angular** rather than radial is undetected — a region of a reachable radius
in a direction the robot cannot turn to inside the window. `outer_envelope` is
the polygon that would catch those and it is computed; using it for
*containment* rather than for its radius is an open decision, not an oversight,
and the reason is measurable: against the eleven fixtures, the polygon test
re-labels three of the five fault runs as overclaims. `declared_violation`'s
declared joint box spans an elbow range the arm cannot sweep in half a second,
and `stale_declaration` and `escalation_failure` declare regions covering the
frames their silent windows stretch past their stated horizon. Each of those is
arguably a real overclaim; the point is that adopting the polygon test changes
what a fault in the nine-fault taxonomy *means*, and
[`docs/prior-art.md` §5](prior-art.md) cites that taxonomy as a contribution.
Changing a fault's meaning is not a refactor.

Three things this limitation is **not**:

- **It is not a weakness in the independence.** Enforcement computes this bound
  itself from `Limits` and the origin, imports from `reg.declare` no further than
  `Declaration` and `ACTION_CLASSES`, and imports nothing from Layer B at all;
  both restrictions are asserted against the module's own AST in
  `tests/test_enforce.py`. It is the *capability* that is limited, not the
  separation. Softening the import rule to buy a tighter bound would trade the
  mechanism for the measurement.
- **It is not unsound.** Both terms over-cover the true reachable set and the
  minimum of two sound bounds is sound, so no truthful declaration is ever
  vetoed — the error is entirely in the permissive direction, which is the
  correct direction for something whose response is VETO. Comparing against
  `reg.envelope.compute_envelope` instead would be the wrong move: that is the
  *under*-approximation of §2, and a declaration larger than a sampled envelope
  is the expected result for an honest policy, so vetoing on it would cry wolf.
  The other eight faults in the taxonomy — staleness, replay, MAC, vocabulary,
  watchdog, no-declaration, escalation failure and the declaration/action
  mismatch — are decided against the record, not against a reachability bound,
  and none of them inherits this.
- **It is not a bound the enforcer can skip.** `Enforcer.offer` takes the
  proprioceptive state as a required second argument, with no default: the
  tighter bound is a function of where the arm is and how fast it is moving, and
  an enforcer that invented a state would compute a plausible bound for a robot
  that was somewhere else.

**What the supportable claim is, exactly.** *An overclaim is detected iff the
declared region reaches further from the base than the robot can, within the
window the declaration itself states.* The angular half is what a tighter
version would add, and the tighter version is already computed — see the
paragraph above for why adopting it is a decision rather than a step.
`reg/enforce.py`'s module header is the authority on why a loose sound bound is
preferred to a tight unsound one.

---

## 4. A Layer A envelope is Layer A only if its `Limits` are

Stated here because §3 above calls `Limits` "a property of the robot rather than
of its state", and that is true of its *shape* and not guaranteed of its
numbers.

**What.** `compute_envelope` has two inputs. The first, `ProprioState`, is kept
out of Layer B by structure: it has no field naming an entity and
`tests/test_layer_boundary.py` fails if one appears. The second is `Limits`, and
that enforcement does not reach it — not because `Limits` is trusted, but
because the mechanism inspects **field names** and the problem arrives in a
**value**. `qd_max` is an innocent name whatever produced the number in it.
Under **ISO/TS 15066 / ISO 10218-2:2025 speed-and-separation monitoring** — the
practice [`docs/plan.md`](plan.md) cites approvingly, and how collaborative
robots actually run — the commanded speed bound *is* a function of a measured
separation distance. Feed one in and the envelope integrated under it depends on
a perceiver.

**The cost, and what carries it.** The dependence is real either way; what
matters is that it is recorded, so that an SSM-derived envelope cannot be
mistaken for a datasheet one by a query, a `CHECK` constraint or a field-name
test. `Limits` carries `source: LimitSource`, required and with no default,
`reg.envelope.envelope_layer` maps it to a layer, and the `HAS_ENVELOPE` edge is
tagged from that rather than from its type — `PROPRIOCEPTIVE` gives `A`,
`DERIVED` gives `B`. The provenance is persisted in `meta['limits_source']` so a
recomputed envelope (§1) inherits it too, and an artifact that does not carry
the key is a **could-not-evaluate**: nothing reads its absence as the clean
case, and `reg.graph._limits_from_meta` refuses rather than reconstructing a
`Limits` nobody vouched for.

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
deferred — it rewrites what the project may claim, which is a decision and not
an implementation.

---

## 5. Above 100 Hz the artifact cannot address every frame of the run

Stated here because [`docs/lossiness.md`](lossiness.md) advertises per-frame
agreement predicates and a reader will assume they hold at whatever rate their
robot runs at. `reg` runs at 50 Hz, so nothing this project has published is
wrong; **a real manipulator runs at 1 kHz, and there the sentence below is what
applies.**

**What.** Every interval endpoint in an artifact is rounded to
`TIME_TOL_S` = 10 ms, so the artifact's time base has `1 / TIME_TOL_S` = 100
addressable instants per second — **however fast the control loop ran**. At or
below 100 Hz each frame quantizes to its own instant and each retained value is
a value about one frame. Above it several frames share an instant, and a
per-frame value read back out of an interval is the value of whichever of those
frames opened it. At 1 kHz eleven frames share each instant.

**The cost, measured.** On `reg.scenarios.near_miss` at seed 0, resampled at
each rate: `separation_timeline` — query 1 of the supported set — misses its own
`DISTANCE_TOL_M` = 0.01 m predicate at rates above 100 Hz, by up to **0.0140 m**
at 1 kHz. Which rate it *first* misses at is a property of how fast the fixture
moves, not of the artifact, and is the reason the bound above is the structural
100 Hz rather than a measured number. The full ladder, its parameters, and the
four things it shows are in [`docs/lossiness.md`](lossiness.md),
[The rate range these hold in](lossiness.md#the-rate-range-these-hold-in); this
section is what a *claim* inherits, not a second copy of the measurement.

**It is a quantization limit, not a sampling one**, and the distinction decides
what a fix would be. Two measurements separate them. The artifact stores **269
`SEPARATION` intervals at 1 kHz and 269 at 100 Hz** — it is not retaining less
at the higher rate, because there is nothing more it *could* retain; the time
base has no more addresses. And every value it reports is within
`DISTANCE_TOL_M` of a true separation of the run at some frame within
`TIME_TOL_S` of the instant it is reported at. Nothing was sampled away and no
value is wrong. What is missing is the ability to say which frame inside a 10 ms
window a value belongs to.
`tests/test_graph.py::test_the_time_base_miss_is_quantization_and_not_sampling`
is that second measurement as an assertion, and it is what holds the diagnosis
rather than this paragraph.

**The honest sentence.** *At 1 kHz this edge layer cannot place a per-frame
value at a frame within its published tolerances.* It can still place it within
10 ms of one, which is what the artifact says about itself and what a reader is
entitled to rely on. Everything else in the supported question set is
unaffected: they are interval and record queries, and an interval whose
endpoints are good to 10 ms is exactly what this contract always promised.

**What this limitation is not.**

- **It is not a reason to widen `TIME_TOL_S`.** That moves the line rather than
  the behaviour — the failure mode this project exists to warn about — and it
  would make the rate *lower*, since the rate is the quantum's reciprocal.
  [`docs/plan.md`](plan.md) already calls the `DISAGREE` that surfaced this "a
  measurement, not a tolerance to widen".
- **It is not a refusal to build.** A stream above 100 Hz is built normally and
  holds everything it otherwise would; refusing would delete evidence in order
  to avoid stating a limit, and would tell a 1 kHz robot it may not have an
  artifact at all. What the build does instead is record the fact:
  `meta[time_base_domain]` states the rule,
  `meta[time_base_addressable_instants]` counts this run's instants,
  `meta[time_base_resolves_frames]` is `yes` exactly when that equals
  `frame_count`, and `python -m reg.graph build` prints a note on stderr for the
  `no` case.
- **It does not touch Layer A.** Declaration and verdict timestamps are stored
  as the record carries them and are *not* quantized to `TIME_TOL_S` — the MAC
  covers them ([`docs/lossiness.md`](lossiness.md) *Retained* #5).
  `verify_chain`, `declared_bound`, `violations` and `verdicts` answer
  identically at 1 kHz.

**What a claim would need instead.** A time base whose resolution is at least
the control period — either `TIME_TOL_S` reduced to match the fastest rate the
artifact is meant to serve (which costs edge rows, since more values become
distinguishable and the incremental rule collapses fewer of them, and would have
to be measured rather than assumed), or endpoints stored as an integer frame
index against the `frame_period_s` already in `meta`, which addresses every
frame exactly and makes the quantum a display concern rather than a storage one.
The second is the smaller change and neither was taken here: both alter what the
artifact claims.

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

**What.** `reg/chain.py` is Schneier and Kelsey's 1998 construction for secure
logs on untrusted machines — per-record MAC, per-record hash link to the
predecessor, one canonical preimage, a walk that checks both — **minus the
property that scheme was written for.** In the original, the secret is evolved
through a one-way function after every entry and the old value is deleted, so an
attacker who takes the machine at time *b* can write whatever they like from *b*
onward and can neither forge nor undetectably alter anything written before it.
`reg`'s keys are static for the life of a run: `generate_keyring` draws from OS
entropy once and nothing evolves.

Beside it, a second asymmetry with the same root. In Schneier–Kelsey the verifier
`V` walks the chain and asks a trusted server `T` about the final MAC; `V` never
learns a key and therefore cannot forge. `reg` hands the auditor the keyring, so
**anyone who can verify a `reg` artifact can also forge one.**

Both are **named, deliberate absences, recorded here rather than discovered**
([`prior-art.md` §14](prior-art.md)). Neither is an error against an intent: the
second is the price of offline verification with no trusted server, and the
first is a design question this project has not taken.

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
re-issued chain needs **no key at all** — `verify_commitment` recomputes both
heads from the records the file holds and compares them against the recorded ones
(§6). So the verifier-holds-the-key asymmetry does not extend to that check, and
an assessor who is given the artifact and *not* the keyring can still detect that
the history no longer matches what was committed to.

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

---

## 8. The artifact contains personal data and this project has not addressed that

Every other section of this file limits what the artifact can *answer*. This one
limits whether it may be **kept**, which is a different kind of limit.

**Nothing here is legal advice and nothing here is a claim of compliance.** The
obligations below are named because they exist and because this project does not
discharge any of them.

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
person. Retained for six months and **handed to an assessor or an insurer** — the
use this project was built for — that is processing of personal data in an
employment context, and in Germany it is also a technical device objectively
suitable for monitoring workers' behaviour or performance under **§87(1)(6)
BetrVG**, subject to works-council co-determination *before the robot runs*.

**The retention window is bounded from both sides and this project has only ever
cited one of them.** AI Act **Art. 19** (providers) and **Art. 26(6)** (deployers)
set the six-month period *"unless provided otherwise in applicable Union or
national law, **in particular Union law on the protection of personal data**"*.
The floor is expressly subordinate on its face. So for the Layer B half of an
artifact six months may be a **ceiling** rather than a floor, and
[`docs/plan.md`](plan.md)'s Claim 1 is citation-correct and
**argument-incomplete**: it prices retaining an artifact for a window that
data-protection law may forbid it from filling.

**Two further obligations, recorded and still undischarged.**

- **Art. 26(7).** A deployer who is an employer must inform workers'
  representatives and the affected workers *before* putting a high-risk AI system
  into service at the workplace. Nothing here gives that notice; what the
  artifact carries is the deployer's statement of which case it was built in, in
  `meta[worker_notice]`.
- **A DPIA.** GDPR **Art. 35(1)** requires one where processing is likely to
  result in a high risk to data subjects; systematic monitoring of employees is on
  the Art. 35(4) lists national supervisory authorities publish, which is why one
  is near-certain here. Whether this processing also lands inside Art. 35(3)'s
  three enumerated cases is not a question this project can answer.
  That there is no DPIA is not in doubt, and `meta[dpia_reference]` states it in
  words rather than by omission.

**Three keys, so that silence stops reading as a stated negative.** An assessor
holding a file that says nothing cannot separate *a notice given and no key
recording it* from *none given* — the inversion `commitment: none` and a required
`Limits.source` already refuse. So the deployer states three facts at build time,
each required with no default (`reg.identity.Disclosures`):

- `meta[worker_notice]` — `given <yyyy/mm/dd>`, `not-given`, or
  `not-applicable <reason>`;
- `meta[dpia_reference]` — where an assessment lives, or `none`;
- `meta[operator_id_kind]` — whether `operator_id` is a `pseudonym`, whose roster
  is held outside the artifact, or a `direct-identifier` such as a payroll
  number. Both are opaque strings, and neither is inferable from the value.

**Recording is not discharging.** Nothing here adjudicates whether a notice was
adequate, an assessment owed or a pseudonym enough, and an artifact carrying the
three keys is not thereby lawful to retain. The vocabulary states no legal
conclusion, and `tests/test_personal_data.py` holds it to that.

**The fourth fact stays a gap: which basis the file is kept under.** Naming the
instrument a six-month retention is claimed under is a legal determination this
project has no standing to make, so there is no key for it and the absence is
stated rather than dropped — an artifact that cannot say what basis it was
retained under cannot be assessed against either bound. The retention rules
already in `meta` state what a *build* keeps, not how long the *file* may be,
and there is no deadline field or expiry path here.

**The minimisation is real, and it is in the schema rather than in a policy.**
`entity` holds four columns — `entity_key`, `kind`, `is_static`, `geometry_wkb` —
and not one of them names a person: the human's `node_id` is `human`, a role, and
the kind vocabulary is `human`, `crate`, `pillar`, `pallet`. There is no
biometric, no image and no raw frame; [`docs/lossiness.md`](lossiness.md)
*Discarded* #5 excludes raw sensor data "by construction". And the Layer A
boundary keeps the certifiable half clear of the person: `ProprioState` has no
field naming an entity. **The artifact is data-minimising almost by accident** —
a consequence of a 2D simulator and a boundary drawn for another reason.
`tests/test_personal_data.py` turns the accident into a contract: it fails if the
`entity` table grows a column this section leaves undisclosed, if `RunIdentity`
grows a field it does not name, or if a key above goes unnamed here.

**What this limitation is not.**

- **It is not an argument for dropping `operator_id`.** *Which robot, which
  shift* is what makes the file handable to an assessor at all, and Art. 73's
  15-day serious-incident clock cannot start against a record that will not place
  itself in time. Two obligations pull in opposite directions here; that is a
  conflict to resolve in a deployment.
- **It is not confined to Layer B.** The identity block is **Layer A**, so
  discarding every entity-naming edge would still leave an artifact stating which
  operator ran which unit from which instant. The Layer A / Layer B boundary is
  not a personal-data boundary.
- **It is not inherited from DSSAD.** DSSAD is privacy-light: it records
  authority transitions and system events, and says nothing about third parties.
  `reg` borrows that schema shape and **inverts its privacy profile** —
  [`docs/prior-art.md` §9](prior-art.md) states that beside the mapping.

**What a claim would need instead.** A DPIA on record; where §87(1)(6) BetrVG
applies, a works agreement in place before the robot runs; the Art. 26(7) notice
actually given rather than only stated; and a retention rule that is the
**minimum** of the AI Act floor and the data-protection ceiling, written into
`meta` with the same discipline as the four retention rules already there, so that
a reader holding only the file learns when it should have been destroyed.

---

## 9. Every result here is a fixed-base result, and two claims rest on that

The eight entries above limit what the artifact can *answer* or whether it may be
*kept*. Not one of them says that the robot cannot move. That is the largest
scoping assumption in the repository.
[`docs/mobile-base.md`](mobile-base.md) is where the consequences are worked out
in full. This entry states the two that are load-bearing *now*, because until
they are stated, two things this project says read as properties of the method
when they are properties of the mounting.

**What.** `reg.kinematics` fixes the base at the origin — the explicit leading
`0.0` in its cumulative sums *is* the base — and nothing in `reg/` or `tests/`
models a robot pose at all: no transform, no pose field, no frame to carry one.
[`docs/mobile-base.md`](mobile-base.md) discusses a pose at length and models
none, being a design document for work that is not built. Every envelope, every
published figure and the bound `reg/enforce.py` VETOes on is computed for a
planar arm bolted down at the origin.

**The cost, first half: `computed_bound` is finite only because the base is
bolted down, and it says so.** `reg.enforce.computed_bound(limits)` is
`sum(link_lengths) + link_radius`, the radius of a workspace disc, and §3's "the
same scalar at every frame of every scenario" is a fixed-base property: a driven
base has an unbounded workspace, so no horizon-free radius exists for it to
compute. Remove the mounting and the first term is not a looser bound, it is not
a bound — so `computed_bound` refuses a `Limits` with any nonzero base bound,
naming the field, and `CLAUDE.md` rule 3 and §3 both say which case each term
applies to rather than describing the bound as the smaller of two
unconditionally. [`docs/mobile-base.md`](mobile-base.md) §1 works that through,
including the origin-centred disc intersected *inside* `outer_envelope` — the
place where a moved base would produce an unsound bound that looks exactly like
a sound one, which is why the base's translation is added to that disc's radius.

**Nothing in this repository behaves differently for it.** `reg.world.LIMITS`
states four zeros, every fixture and every published figure is a fixed-base run,
and a fixed-base `Limits` gets exactly the disc it always got. What the entry
constrains is what the project may *claim* about a robot it does not ship.

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
ahead-left of its own base at t?* [`docs/mobile-base.md`](mobile-base.md) §2 and
§2.1 carry it.

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

**What a claim would need in order not to inherit this.** Three things. The
first exists; the other two do not.

1. **A bound that refuses.** An unbounded workspace is a could-not-evaluate
   under `CLAUDE.md`'s *a check must be able to fail*, and `computed_bound` must
   say so for a mobile model rather than return a large plausible number that
   VETOes while looking principled. That is built, and `horizon_bound` rests on
   the outer envelope alone for a driven base as a consequence; what it buys is
   a bound that is *honest* about a mobile robot, not a mobile robot this
   repository can run.
2. **A base pose carried as an explicit Layer B input**, with its provenance
   declared and no default, on the precedent `Limits.source` set (§4), so that a
   room-frame envelope is visibly a perception-dependent object and a body-frame
   one is visibly not.
3. **The fixtures and figures to go with it.** Claim 1 stays a fixed-arm claim,
   [`docs/retention.md`](retention.md) says in its own header that the artifact
   side of every figure in it is measured on the fixed-base arm — and that the
   control rate is *not* a blanket condition in the same way, since its ladder
   measures four of them.

Until all three exist, the supportable claim is exactly: **every reachability
answer in this artifact is an answer about an arm whose base is a mounting fact,
and the certifiability of the world-frame ones is inherited from that fact
rather than from the method.**

---

## 10. The base's contribution to the outer set is a disc, and a real base is not

§9 states that every result here is a fixed-base result and that a driven base
would leave every VETO resting on `reg.envelope.outer_envelope`. The outer set
reads the base's four actuation bounds and composes them into the geometry as a
**disc**, which is a much weaker description of a vehicle than it looks.

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
follows (§4): a property of the answer that is decided by the `Limits` it was
computed from travels *with* the answer.

**What a claim would need in order not to inherit this.** A reachable set for the
vehicle rather than a bound on its displacement — RTD and REFINE compute exactly
that for ground robots, with the tracking error inside it, and CORA's conservative
linearization plus polynomial zonotopes is what makes the non-convexity
representable ([`prior-art.md`](prior-art.md) §23, §24). `reg` may not build it:
*no new dependencies* is a standing rule and *an HJ reachability solver* is a
stated non-goal in [`plan.md`](plan.md). A `shapely` polygon has no zonotope
arithmetic behind it, so every step of such a construction would be a buffer whose
error compounds. Until then the supportable claim is exactly: **the outer set
contains everything a base within these actuation bounds could do, and it
contains a great deal that a differential-drive base could not.**

---

## 11. `qd` carries no provenance at all, and the tag now follows the base velocity's

> **Amended 2026-09-08 (issue #252). Half of this entry closed.**
> `reg.envelope.envelope_layer` is now the **weakest of its inputs** —
> `Limits.source`, the provenance of the base velocity the outer set was
> integrated from, and whether the configuration states a room-frame pose — so an
> outer set whose base term came out of visual odometry is tagged `B` however its
> bounds were sourced. Every tagged edge also records what its tag was computed
> from, one row per input, in `edge_layer_basis`. That is the first of the three
> things this entry's last paragraph asked for, taken together with the
> posed-configuration case [`sufficiency.md`](sufficiency.md) §5.8 held open,
> because the two had to be answered in one place or answer differently. **Every
> published retention figure moved** — [`retention.md`](retention.md) is the
> re-measurement.

[`sufficiency.md`](sufficiency.md) §5.9 is the decision the closed half rested
on: a `BaseVelocity` filled from a perceiver is **not** Layer A, so
`reg.types.VelocitySource` is required on the type with no default and no
inference.

**What.** Two gaps remain, and they are different in kind.

*`qd` carries no provenance at all.* `ProprioState.q` and `ProprioState.qd` are
Layer A by their kind, and nothing records where a particular run's numbers came
from. The argument that this is safe is a **deployment** one — joint state comes
off the actuator's own encoders on every arm this project would run on — and by
[`sufficiency.md`](sufficiency.md) §5.6's own standard that is the weaker kind of
argument, the kind somebody can answer by building a thing. A visual joint-state
estimator is that thing. The asymmetry that made the base velocity worth tagging
first is one of *likelihood*, not of structure: visual odometry is ordinary and
visual joint-state estimation is not.

*The stream's column rule still does not follow the value.* One level down from
the edge, `reg.bench.COLUMN_RULES` classifies `base_vel_source` as Layer A beside
the three rates it describes, because that classifier is **per column and
static** while the thing that decides the question is the *value in the cell*.
The edge tag stopped being wrong about this; the column rule has not.

**The cost.** An artifact can be internally honest and still read stronger than
it is. A `WHERE layer = 'B'` query, which is what Claim 3 *is*, returns the
envelope over a perceived base velocity now and will never return the one over a
perceived joint rate. For `qd` there is not even a column to read: an arm whose
joint state came from somewhere unusual produces an artifact indistinguishable
from one whose did not, and no query can be written that would find it.

**What it does not cost, today.** For `qd`, nothing this repository can show you,
and that is the entry rather than a mitigation: every fixture's joint state comes
from the simulator, so an artifact built from a visual estimator would look
identical to one built from encoders. The column rule's cost is bounded —
`expected_header(2, 3)` is the 24 columns Claim 1 is priced on, and
`base_vel_source` appears in a header only a mobile fixture writes.

**What a claim would need in order not to inherit this.** Two things, the first
of the original three having landed. (1) A provenance on `qd` on the pattern
`BaseVelocity` set, or a written argument that a joint rate is structurally
proprioceptive in a way a base rate is not; this entry asserts only that the
argument currently offered is the weaker kind, not that no stronger one exists.
(2) The graded integrity attribute [`sufficiency.md`](sufficiency.md) §7 rejects
for scope, if the claim needs to distinguish a PLd-rated perceiver from an
unrated one — which is what a real assurance case does, and which the binary
cannot express in either direction. Until then the supportable claim is exactly:
**this artifact's layer tags follow the provenance of a base velocity, and there
is no provenance on a joint rate for them to follow.**

---

## 12. The artifact is not self-describing: one question still needs this document

Added 2026-09-05 (issue #198). [`self-describing.md`](self-describing.md) §1 is
the design document; this entry is its tier 0. The three gaps it named were each
already priced somewhere in this file — §1 for the platform, §2 and §3 for the
radius, §11 for the tag — and **that was the finding**: a reader who wants to know
what an auditor can do with the file alone had to assemble it from three entries
written about other things. Two are closed. They are struck rather than deleted,
because how a gap closed is worth as much here as that it did.

**What.** Questions an auditor holding only an artifact and the code that reads
artifacts cannot answer, and must come here for.

| # | the question the file cannot answer | where the mechanism is priced |
|---|---|---|
| ~~1~~ | *What was this `layer` tag computed from?* — **closed** | §11 |
| ~~2~~ | *Whose recomputation is wrong, mine or the file's?* — **closed, weaker form** | §1 |
| 3 | *Could the robot have reached (x, y)?* — **narrowed to the rows that keep no polygon** | §2, §3 |

*1 — closed 2026-09-08; 2 — closed in the weaker form, 2026-09-05 (issues #200
and #201).* Each is priced where the table points. §11: the tag is now the
weakest of its own recorded inputs, `edge_layer_basis` carries them, and
`reg.query.cold_read` reports `layer-tag-basis` as CHECKABLE, so a reader
recomputes it with no document open. §1: the environment is in the file
(`reg.store.ENVIRONMENT_KEYS`) and `envelope_at` **acts on it**, refusing to
recompute off the recording environment and naming the key that differs. What
remains of 2 is that a refusal is a could-not-evaluate rather than an
attribution, and that matching environments are necessary and not sufficient —
the C library is not among the keys.

*3 — narrowed 2026-09-09 (issue #257), and the remainder still routes back
through 2.* The rows that keep the sampled polygon now keep the outer
**boundary** too — 12 of `long_run`'s 3,000 frames, the ones an edge anchors,
which is where an incident report cites. There a question about a *point* is
answered by the region. Elsewhere it stays radial in whichever direction it is
asked (§2's bullets; §3 is what that costs the overclaim check) and the region is
recomputable, which is gap 2. **The ceiling on the rest is `ENVELOPE_RETENTION`,
not this gap**: a boundary on every retained row would answer 84 of those frames
for 7.3x the bytes.

**The cost.** What is left is a fact a reader must take from a markdown file that
no test holds against the artifact. That is the cost this project has already
refused to accept one level down — `reg.enforce` recomputes its own bound rather
than reading the declared one, precisely because a value supplied by the party
being checked is not evidence.

**What closing two and narrowing one cost.** Gap 2 cost a schema bump and a
refusal; gap 1 and gap 3 each cost a schema bump and **every published retention
figure** — [`retention.md`](retention.md) is the re-measurement, +0.20% to
+0.55% for gap 3. None resolved polygon containment for the overclaim check
(issue #82, §3): the recomputation blocker is gone where a boundary is kept, but
containment re-labels three of five fault fixtures.

**What a claim would need in order not to inherit this.** That the file carry
what the prose carries, which is [`self-describing.md`](self-describing.md) §3 and
its build order in §8. Tiers 2 to 5 have landed. What is left is tier 1's
[`prior-art.md`](prior-art.md) pass on build provenance, in-toto and SLSA,
because recording the toolchain that produced an artifact is ordinary practice
this project does not get to discover. Until then the supportable claim is
exactly: **this artifact lets a reader check a layer tag and an environment from
the graph alone; the reachable region behind an edge is a region where an edge
anchors one and a radius everywhere else.**

---

## Why

Nothing below is normative. It is the rationale for the entries above — how each
came to be stated in the shape it is, and which of them arrived as a choice
rather than as a finding. **This file exists early because a limitation is worth
least once nobody remembers it was a choice.**

### When each entry was added

| entry | added | issue |
|---|---|---|
| §1–§4 | with the phases that created them, from 2026-08-18 | — |
| §5 | 2026-08-21 | #77 |
| §6, §7 | with Phase 6; §7's two absences ordered by `prior-art.md` §14 | #104 |
| §8 | 2026-08-26 | #101 |
| §9 | 2026-09-01 | #136 |
| §10 | 2026-09-02 | #163 |
| §11 | 2026-09-03 | #156 |
| §12 | 2026-09-05 | #198 |

### §1 — the environment record, and what it replaced

Before issues #200 and #201 an artifact recorded `reg_version` and the envelope
parameters and nothing about the machine, so an assessor recomputing on another
architecture got a polygon that differed for a reason the artifact could not
state. #200 put the buildinfo in `meta` and #201 made `envelope_at` act on it.
What used to be a number is now a refusal: a worse answer and a true one, and
per *a check must be able to fail* the third state never resolves to the first.

The trigger set was #201's, and the keys it left out were a remainder rather
than a list until issue #241: `env_numpy_version` was recorded by #200, absent
from #201's named triggers, and compared by nothing for two milestones — in the
library that places every link endpoint. The cold read (#231) found it on its
first run against a real artifact — what that report is for. #241 made numpy a
trigger and made the rest a written-down tuple a test holds to a partition of
`reg.store.ENVIRONMENT_KEYS`, so the next key added cannot land in neither list
unnoticed.

### §3 — what the horizon-limited bound closed

Until issue #82 only `computed_bound` existed, so `envelope_overclaim` fired only
on a declaration exceeding the **entire workspace** — and the fault a Simplex /
ASTM F3269 runtime monitor exists to catch was undetectable. Issue #164 is where
the number of terms in the bound stopped being a constant and became a property
of the robot.

### §4 — why a value needed a tag

The dependence on a perceiver was always real; what was absent was any record of
it, so an SSM-derived envelope carried a Layer A tag and no query, no `CHECK`
constraint and no field-name test could tell it from a datasheet one. Issue #84
added `Limits.source` rather than widening the field-name check, because a taint
arriving in a *value* cannot be caught by inspecting *names*.

### §5 — a limit that arrived as a bug report

The 100 Hz ceiling was always implied by a 10 ms quantum and is a choice; nobody
had noticed it was one. The defect issue #77 reported was the silence — a
contract advertising a per-frame budget and never saying what range it held in —
and stating the range is what closed it. The constant was held deliberately
rather than tuned until the finding went away, which is the move
[`docs/plan.md`](plan.md) already refuses by calling the `DISAGREE` that surfaced
this "a measurement, not a tolerance to widen".

### §8 — the hole with no entry

Before issue #101,
`grep -riE "gdpr|personal data|data protection|works council"` over `docs/` and
`reg/` returned nothing substantive, and the only matches for "worker" were
"worker host", the CI machine. In a repository whose credibility rests on stating
its own holes first, that was the largest one, and it went unwritten because it
limits whether the artifact may be *kept* rather than what it can answer.

### §9 — an assumption nobody had to mention

A fixed base was never chosen frame by frame. It is the frame everything else was
written in, so no line of code ever had to name it, which is how the largest
scoping assumption in the repository went unstated for nine phases. Issue #136
wrote it down; issues #163 and #164 then rewrote §3's description of the bound
rather than amending it, because the soundness of the workspace-disc term is a
trivial argument only while the disc is centred on something that stays put.

### §11 — why the mapping is left open, and a belt that was removed

The `VelocitySource`-to-`Layer` mapping is three lines and the test for it is
not: a `velocity_layer` written now would be exercised against no mobile
fixture, and the decision it forces — whether an envelope's layer is the
*minimum* over its inputs, and what that does to the four attestation edges §2's
asymmetry rests on — is the same decision [`sufficiency.md`](sufficiency.md) §5.8
holds open for a posed configuration, on purpose, until there is something in
hand the answer would be about. Writing it twice, separately, in advance of that
fixture is how the two answers end up disagreeing.

The entry used to give a second reason why nothing here carries a mistagged base
velocity: that `reg.enforce.Enforcer` refused to construct for a driven base at
all (issue #164). Issue #189 made that false — an enforcer now constructs for one
and adjudicates it. The entry is unaffected, because the reason was always the
fixtures; what changed is that the first mobile fixture will now produce
artifacts this entry is about rather than failing to build.

### §12 — why it restates three entries rather than adding one

§12 names three questions an auditor holding only the artifact cannot answer, and
each is already priced in §1, §2/§3 and §11. That the three had to be assembled
from entries written about other things *is* the finding, so the restatement is
the point of it rather than a duplication to remove.
