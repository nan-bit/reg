# reg — a reachability evidence graph

A retainable, queryable, tamper-evident audit artifact for robot autonomy.

Safety work tells you a robot probably won't hurt anyone. Evidence tells you what
happened when it did. Almost all robot safety research is runtime — keep the
machine inside a bound while it is moving. Very little of it addresses
reconstruction: someone asking, months later and with the robot long since
stopped, what the system knew, what it intended, and what constrained it.

**Robotics already has an answer to that.** The Ethical Black Box was proposed in
2017 by Winfield and Jirotka and drafted as an open standard in 2022 — a
flight-data-recorder equivalent carried by the robot so an accident can be
reconstructed ([`docs/prior-art.md`](docs/prior-art.md) §11). `reg` is that idea
with three things changed, and each is checkable against their published draft:

1. **The record is not the robot's self-report.** An EBB is passive: everything in
   it arrives on the authority of the system under investigation. Here, what the
   policy *declared* it would do and what an independent check *concluded* are
   separate records, computed and signed by different parties. When they disagree,
   the artifact says which one was wrong.
2. **Integrity is a keyed hash chain**, not a per-record checksum. The EBB draft's
   `chkS` is an unkeyed 64-bit non-cryptographic value covering a single record,
   with no link between records — delete a run of records and every remaining
   checksum still verifies.
3. **It is built for the six months *after* an incident**, not the hours before
   it. An EBB is a ring buffer; the 2017 paper's own arithmetic is roughly three
   hours on a 1 TB drive. The window that matters for liability is the retention
   period, and that is a different engineering problem.

Keeping the record that long is what makes it practical rather than theoretical,
and it is measured rather than asserted: **264 GB** per robot for six months at
the 50 Hz control loop this simulator runs at, against an assumed 1 TB/day sensor
log — roughly **691x** smaller ([`docs/plan.md`](docs/plan.md) Claim 1). The
artifact side is measured, and re-measured on every CI run against every document
that publishes it (`tests/test_published_figures.py`), so it cannot drift quietly.
The sensor side is a **projection** from a sourced assumption, never measured here
([`docs/sensor-baseline.md`](docs/sensor-baseline.md)).

The figure at a 1 kHz control rate, and the rate ceiling above which the artifact
can no longer address every frame of the run it prices, are in
[`docs/plan.md`](docs/plan.md) Claim 1 and
[`docs/limitations.md` §5](docs/limitations.md). *Cheap enough to keep* is the
only property the rest of the argument needs from this.

`reg` is a prototype of that record, in two halves: a
declaration-and-attestation protocol between an unbounded policy and a bounded
enforcement layer, with a tamper-evident record of every exchange between them —
and a temporal scene graph that answers post-hoc audit questions without
replaying raw sensor logs. The attestation half is what the sentence below turns
on; the scene graph is what makes the answers specific.

Everything in the project serves one sentence:

> The model declared it would stay inside this bound. Here is where it tried to
> exceed it. Here is what the enforcement layer did. Here is the signature chain
> proving neither side rewrote the record.

## What this is not

| Not this | Why |
|---|---|
| A perception system — no vision, no SLAM | The thesis is evidence, not perception. Entity positions are ground truth from the simulator. |
| A 3D or realistic robot model | 2D planar demonstrates every claim. |
| An HJ reachability solver | Sampling on 4–6D state is enough, and both directions ship: `compute_envelope` is an **inner** approximation — the set the robot demonstrably swept, which the graph records — and `reg.envelope.outer_envelope` is an **over**-approximation of the set it cannot leave within the horizon, which is what `enforce.horizon_bound` adjudicates against. Reporting the two together is a bracket, not a solver. |
| A physics engine | Nobody evaluating this cares about the dynamics; the torque limit is treated as an acceleration bound. |
| A real-time system | Offline batch. |
| A learned policy | Scripted trajectories. The policy being a black box is the *premise*, not something to implement. |
| A real PKI | Two keys in a keyring file. |
| A proposed standard, or a research contribution to reachability analysis | Every design element traces to an existing precedent — see below. |

It is an argument about evidence, made concrete.

## The four claims

Each is independently shippable, and they are built in order. Status reflects the
repository as it stands, not the plan.

| | Claim | Status |
|---|---|---|
| **4** | **Attestation** — declaration, independent verification, verdict, tamper-evident chain | `landed, minus the passivation half` — the `Declaration` record and the hash chain (`reg/chain.py`, `reg/declare.py`), independent adjudication and the nine-fault taxonomy (`reg/enforce.py`), both record chains persisted in the artifact (`reg/graph.py`), and `verify_chain` with the `--tamper` demonstration that it can say no. All of that is exercisable end to end, from a shipped fixture to a query. What the chain binds is the *party that made each record*, not the build of the policy under investigation — DSSAD's `R157SWIN` element is **not implemented**, because nothing here has a policy version to bind ([`docs/prior-art.md` §9](docs/prior-art.md)). **Passivation and reintegration are not exercisable.** They exist only in `reg/enforce.py`: the record reaches no table, no edge type and no query, no shipped fixture produces one, and `graph.build` *refuses* a run containing one rather than write a chain link over the gap. The refusal is deliberate and documented where it happens; what it costs is that **"was the passivation acknowledged, and by whom" is a question this artifact cannot be asked**. Issue #112 is where that would change, and it is a claim change, not a refactor. [`docs/lossiness.md`](docs/lossiness.md) *Retained* #7 states the same gap |
| **3** | **Sufficiency boundary** — which claims proprioception-only evidence supports, and which depend on an uncertifiable perceiver | `landed` — the Layer A/B type boundary and the test that fails when it erodes (`reg/types.py`, `tests/test_layer_boundary.py`), and the taxonomy itself in [`docs/sufficiency.md`](docs/sufficiency.md), which is normative for what this project may claim: which audit questions the artifact answers on its own authority and which are only as strong as whatever supplied the entity positions. The rule is not name-based alone, because a taint can arrive in a *value*: `Limits.source` is required with no default, `reg.envelope.envelope_layer` maps it to a layer, and the `HAS_ENVELOPE` edge is tagged from that — proprioceptive bounds give `A`, bounds derived from a measured separation give `B`, which is the ISO/TS 15066 speed-and-separation case. An artifact carrying no `meta['limits_source']` is a **could-not-evaluate** rather than a clean Layer A one, and an unknown provenance string is refused outright (`tests/test_layer_boundary.py`) |
| **2** | **Query** — audit questions answered from the graph alone, no access to the original stream | `landed` — `reg/query.py` answers all nine of [`docs/plan.md`](docs/plan.md) Phase 7's questions, including `incident_report()`. "Alone" is a property of the import graph, not a promise: the module imports neither the stream reader nor anything that does, and `tests/test_query.py` fails if it ever can |
| **1** | **Retention** — what it costs to keep the artifact for the mandated window | `landed, reframed` — measured and published in [`docs/plan.md`](docs/plan.md) Claim 1: **264 GB** per robot for six months at occurrence resolution (±1 s), **~691x** below an assumed 182.5 TB sensor log at a 50 Hz control rate. That coarsest level is **98.5% attestation records** — 3,120 declarations and verdicts against 42 occurrences — so the figure is the price of retaining *attestation*, not of a DSSAD-equivalent event log; the label said the opposite until issue #116, and the positioning decision behind the new one is recorded in [`docs/plan.md`](docs/plan.md), *What the coarsest level actually holds*. Measured on the artifact side, a **projection** on the sensor side ([`docs/sensor-baseline.md`](docs/sensor-baseline.md)). The original framing — is the graph smaller than the stream it replaces — is answered **no**: **~40x** *larger* than a gzipped copy of the raw state stream — which is **24 columns** for the priced fixture, **19 of them Layer B**: the human's pose and velocity and every obstacle's, beside 5 proprioceptive ones (`reg.stream.expected_header`, `reg.bench.proprioceptive_columns`) — measured on the artifact that carries Layer A. That baseline is not what practitioners retain: against rosbag2/MCAP, the incumbent, the same proprioceptive content costs **2.51x** what the gzipped CSV does — on a **hand-built encoding comparison and not a real bag**, which [`docs/sensor-baseline.md`](docs/sensor-baseline.md) requires be said wherever the figure is quoted until issue #117 retires it. So the artifact's disadvantage against a real bag is smaller than this figure — by how much is not measured, because the two comparisons do not carry the same content. A **13x** figure appears in the same comparison measured on a build holding **no declaration, verdict, fault or chain record at all**, and that condition travels with it wherever it is quoted. Published beside the retention figure because it is the comparison a skeptic runs. The 1 kHz rung and the rate ceiling above which the time base cannot place a frame are in [`docs/limitations.md` §5](docs/limitations.md). `python -m reg.bench --all` reports the per-scenario table for all eleven scenarios; `--resolution` produces the curve, and `--control-rate-hz` the curve at a ladder of control rates |

The number is an identifier, not a rank — it is referenced throughout this repository and does not move. The **order** is the argument: what the artifact proves, what that proof is worth, how you ask it, and what it costs to keep.


## The honesty note: this is the structure of non-repudiation, not non-repudiation

Every `Declaration` is signed with a policy key and linked to its predecessor by
a SHA-256 chain, and every `Verdict` is signed with a separate enforcement key. **In this prototype both keys live in the same process.** That demonstrates
the *structure* of non-repudiation — two parties, two keys, a record neither can
rewrite without it showing — and not non-repudiation itself, because a process
holding both keys can forge either side of the exchange.

A real deployment needs the enforcement key in hardware the policy vendor cannot
reach. That is the same independence argument as the Layer A / Layer B
separation, one level down: a signature from a key the signer's counterparty also
holds has common-cause failure with the thing it is supposed to attest, exactly
as a constraint layer supplied by the policy vendor does.

**The chain itself is not this project's invention, and the version here is the
weaker one.** A per-record MAC plus a per-record hash link to the predecessor is
Schneier and Kelsey's 1998 construction for secure logs on untrusted machines
(USENIX Security 1998; ACM TISSEC, 1999), and `reg` implements it **without its
forward security**: their scheme evolves the key after every entry and deletes the
old one, so an attacker who takes the machine cannot forge what was written before
they arrived, and `reg`'s keys are static for the life of a run. Anyone holding the
keyring can also re-sign the whole history. Both are named, deliberate absences
rather than oversights ([`docs/limitations.md` §7](docs/limitations.md)), and what
this project adds to the ancestor — two chains under role-typed keys, and a
verifier with three outcomes — is not cryptographic. Deleting the *last* records of
a chain, which breaks no link, is likewise a named attack against exactly this
construction — Ma and Tsudik's truncation attack — with a published fix in a
different data structure that `reg` does not use
([`docs/prior-art.md` §14 and §18](docs/prior-art.md)).

**The chain alone deters editing, not re-issuance**, and the two are different
faults. A chain under keys held by the record's own author cannot notice the
whole history being re-run and re-signed offline — the resulting artifact
verifies perfectly. Two things bear on that:

- `--run-start` is a **required, no-default** UTC instant, and `meta` names the
  unit and the operator, so the artifact says which robot and which shift.
  Determinism is untouched, because the start is *declared* rather than read
  from a clock: same seed **and** same declared start, same bytes.
- `--witness` commits both chain heads at artifact close, signed by a second
  on-site keyholder whose key signed no record in the file. Half of that check
  needs no key at all, which the demonstration below makes concrete.

**An on-site witness is not a third-party timestamp.** It proves a second party
at the same site saw these heads, not that they existed by any instant to someone
with no relationship to the operator. RFC 3161 and transparency-log adapters
would; both need a network call at the moment the artifact closes, and this
artifact is meant to be verifiable years later with no service still running and
no call to anyone. Both are documented and deliberately unimplemented
([`docs/limitations.md` §6](docs/limitations.md)). An artifact closed without a
witness records `commitment: none` in so many words — silence never reads as
commitment.

**The artifact contains personal data, and this project has not addressed that.**
Every other limitation on this page bounds what the artifact can *answer*. This
one bounds whether it may be *kept*. Per shift it records the robot's proximity
to an entity whose `kind` is `human`, contact and closest-approach occurrences
naming that entity with a wall-clock datum, and `meta[operator_id]` beside
`meta[run_start_utc]` — which together select a shift, and a shift resolves
against any roster to a person. Retained six months and handed to an assessor,
that is processing of personal data in an employment context. The minimisation is
real and in the schema, not in a policy: no column here names anybody. The
obligations that remain are named and not discharged, and the AI Act's six-month
period is expressly subordinate to data-protection law — so for that half of the
artifact it may be a ceiling rather than the floor Claim 1 prices against
([`docs/limitations.md` §8](docs/limitations.md)).

Two smaller admissions in the same spirit:

- The keyring is a JSON file of two hex keys. There is no PKI, no key rotation
  and no revocation, and the file's only protection is its filesystem mode.
- The record commits to floats at the raw stream's fixed precision
  (`reg.stream.FLOAT_PRECISION`), so the chain is tamper-evident at that
  resolution and not below it.

Intent attestation of this shape is **not a new idea and this project does not
claim it as one** — there is a 2026 line of work on cryptographic runtime
governance in which software agents declare intent before acting and receive
signed authority tokens ([`docs/prior-art.md` §10](docs/prior-art.md)). What is
distinct here is the domain (a physical control policy, where the bound is a
region of space and the failure is contact with a person) and the lineage
(IEC 61784-3 and machinery safety, not zero-trust).

## Standards baseline

Four of the load-bearing precedents. [`docs/prior-art.md`](docs/prior-art.md) has
the full treatment, including what this project must *not* claim as novel.

| Precedent | What it establishes | Status |
|---|---|---|
| **UNECE DSSAD** (Data Storage System for Automated Driving, mandated by UN R157) | A regulator already requires a retained evidence recorder for autonomy — and it stores *discrete events*, not continuous state, which is the same retention granularity this project argues for. Its event vocabulary does not transfer: it records transitions of authority between human and system, not the failure modes of a manipulator working near a person. `reg`'s occurrence layer implements four of its five data elements; the fifth, `R157SWIN`, is **not implemented** and is recorded as such ([`docs/prior-art.md` §9](docs/prior-art.md)). | In force. The informal group's work ran past its June 2026 target and a mandate extension is being sought, so the event vocabulary is still moving |
| **EU AI Act Article 12** (with the retention period in Article 19) | High-risk AI systems must technically allow automatic recording of events over their lifetime, retained at least six months. Commentary reads this as requiring decision-level traceability — reconstructing individual decisions, not an activity log. The regulation mandates the capability and says nothing about the artifact. | In force |
| **IEC 61784-3 black channel** / PROFIsafe | Assurance lives in the endpoints; the uncertifiable middle is declared out of scope. `reg` applies this to a learned policy — and deviates deliberately by using HMAC rather than PROFIsafe's CRC, because its threat model includes an adversary who has read the spec. | Published |
| **UL 4600** | Autonomous systems are certified through a structured claim → argument → evidence safety case rather than a test result. | Published (ANSI/UL 4600) |

The gap: ISO 25785-1 will specify what the *robot* must do and UL 4600 specifies
how to structure the *evidence*. Nothing specifies what the model must **emit** so
an OEM can build its safety case. Automated driving has a **mandated** evidence
recorder; robotics has a **proposal** — the Ethical Black Box, above — and no
mandate. The distinction matters: a proposal is something to build on, and a
mandate is what makes someone build.

## How to run

Python 3.11+. Only `shapely` is load-bearing — polygon union and intersection is
the actual math. `sqlite3`, `hmac` and `hashlib` are stdlib on purpose: the
artifact has to open without a runtime.

```bash
pip install -e ".[dev]"
pytest                      # the whole suite; CI runs exactly this
```

The CLI entry points that exist are `python -m reg.sim`, `python -m reg.graph`,
`python -m reg.query` and `python -m reg.bench`; each takes `--help`. The build
order is in [`docs/plan.md`](docs/plan.md).

## Reading an incident

The demo sentence of [`docs/plan.md`](docs/plan.md) Phase 7, answered end to end
as one query. Reproduce it with a keyring of your own — key material is the one
thing in this project that is deliberately **not** derivable from a seed. The run
start is the same kind of input: required, no default, and *declared* rather than
read from your clock, so the build below is still byte-reproducible.

```bash
python -c "from reg.chain import generate_keyring, write_keyring; write_keyring(generate_keyring(), 'keyring.json')"
python -m reg.sim   --scenario declared_violation --seed 0 --out dv.csv
python -m reg.graph build dv.csv --out dv.sqlite --keyring keyring.json \
    --replan-interval 0.5 --declaration-horizon 0.5 --watchdog-period 1.0 \
    --run-start 2026-08-21T09:00:00Z --unit-id arm-07 --operator-id op-day-shift
python -m reg.query dv.sqlite --incident 3.5 --keyring keyring.json
```

which prints, on the run above. **Abridged**: `…` marks an elided line, and the
`[scene]` clause and the whole GSN block follow what is shown.

```
incident report: t=3.5000 s
verdict:    ANSWERED
integrity:  VERIFIED
incident:   yes
note:       2 declaration(s) in force at t=3.5; 51 of 51 adjudication(s) in [3.0, 4.0] were not permitted …

[declared] ANSWERED (evidence layer A)
At t=3.0000s the policy declared envelope env_95506a4e3d27bc96 (area 0.83 m²)
  action_class: reach, horizon 500ms, seq 6, declaration declared_violation-decl-00006
  in force from t=3.0000s to t=3.5000s
…

[violation] ANSWERED (evidence layer A)
At t=3.0000s a commanded action was not permitted as issued
  fault: DECLARATION_ACTION_MISMATCH
  51 of 51 adjudication(s) in [3.0000, 4.0000] s were refused; fault(s) present: …
  how far outside the bound the action lay is not retained: …
  the earliest refused action in the whole record is at t=2.1000s (verdict …

[enforcement] ANSWERED (evidence layer A)
Enforcement adjudicated verdict declared_violation-verdict-00150 at t=3.0000s
  outcome: CLAMP to envelope env_55ad010616fe70b3 (area 0.83 m²)

[integrity] VERIFIED (evidence layer A)
Chain verified: 262 records, 0 breaks
```

Three things about that output are the point rather than decoration. It carries
**GSN-compatible field names** (`goal`, `strategy`, `solution`, `assumption`,
`justification`) beside the prose, per
[`docs/prior-art.md` §7](docs/prior-art.md), so it drops into a UL 4600 safety
case rather than needing transcription — field names only, no diagram. It
**populates `assumption` exactly when it cites a Layer B fact**, so a report that
rests on perception says so and one that does not is not made to look
conditional. And if the chain does not verify it says so **first**: every other
line is a claim about a record whose integrity is then in question. Tamper with a
copy and watch it —

```bash
python -m reg.query dv.sqlite --verify-chain --keyring keyring.json \
    --tamper declaration:first:horizon=9.5 --tamper-out tampered.sqlite
python -m reg.query tampered.sqlite --incident 3.5 --keyring keyring.json  # exit 3
```

### Committing the chain heads

The re-issuance defence argued above, operationally. Commit the two chain heads
at artifact close to a second on-site keyholder — a different key from either of
the two that sign records, and one this project refuses to accept if it is not:

```bash
python -c "from reg.commit import generate_witness, write_witness; write_witness(generate_witness('witness-safety-officer'), 'witness.json')"
python -m reg.graph build dv.csv --out dv.sqlite --keyring keyring.json \
    --witness witness.json \
    --replan-interval 0.5 --declaration-horizon 0.5 --watchdog-period 1.0 \
    --run-start 2026-08-21T09:00:00Z --unit-id arm-07 --operator-id op-day-shift
python -m reg.query dv.sqlite --verify-chain --keyring keyring.json --witness witness.json
```

which reports `commitment: VALID`. The half worth understanding is that a
re-issued chain is caught **with no keys at all** — the heads are recomputed from
the records the file actually holds and compared against the recorded ones, so
the tampered artifact above reports `commitment: INVALID` and names which head
moved even with no `--keyring` and no `--witness` on the command line. The
witness signature is what stops the recorded heads being rewritten to match.

## Status

**Built.** The shared record types and the Layer A/B split (`reg/types.py`, and
Claim 3 above), the simulator and its eleven scenario fixtures, the
proprioception-only envelope, the evidence graph and its SQLite store, the
benchmarks and the viz, the hash chain with its two keyed MACs (`reg/chain.py`),
the `Declaration` record and the scripted policy that emits it
(`reg/declare.py`), independent adjudication and the nine-fault taxonomy
(`reg/enforce.py`), chain verification with the `--tamper` demonstration that it
can fail, and the query API in full (`reg/query.py`): the four scene questions,
the four attestation questions, and `incident_report()` above them.

**Published.** The write-up — [`docs/plan.md`](docs/plan.md) Phase 10 — is at
[ernan.dev/projects/reg](https://ernan.dev/projects/reg). The GIF that phase also
listed is **descoped** rather than pending; `reg/viz.py` renders the still frame and
that is where the visual argument stops, so nothing in Phase 10 is outstanding.

Nothing on this page is illustrated by a placeholder. A plausible one would be
indistinguishable from a measured result to every later reader, and that
difference is the project's whole argument — which is also why the sensor-log
comparison is labelled a projection, and why `reg.bench --sensor-multiplier` has
no default: there is no value of that flag that makes the output claim to have
measured a robot. The incident report above **is** real output, reproduced by the
four commands beside it.

Read [`docs/plan.md`](docs/plan.md) for the argument and the full build order, and
[`docs/prior-art.md`](docs/prior-art.md) before claiming anything here is novel.
The two disagree in places; prior art wins.

## How work happens

Groom an issue, label it `agent-ready`, and an unattended writer picks it up,
cuts a worktree, implements it, and opens a **draft PR**. A human marks it ready;
nothing on the worker host merges. Dependencies are `Depends-on: #N` trailers in
the issue body, and `epic-advance.yml` flips the next tier when they close. An
issue is ready when it names its **acceptance criteria**, its **affected areas**,
and the **command that verifies it**.

Every PR the writer opens carries an **impact report** — what the change touches
and what that reaches. It is advisory: it informs the human review, it does not
gate the merge.

```bash
gh issue edit N --add-label agent-ready
journalctl --user -u reg-runner -f
```

The conventions code here must follow are in [`CLAUDE.md`](CLAUDE.md); the path a
change takes in and out is in [`docs/CONTRIBUTING.md`](docs/CONTRIBUTING.md). The
harness itself is [`nan-bit/issue-runner`](https://github.com/nan-bit/issue-runner),
installed on the worker host — this repo configures it through `.runner.conf`.

## License

MIT — see [`LICENSE`](LICENSE).
