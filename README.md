# reg — a reachability evidence graph

A retainable, queryable, tamper-evident audit artifact for robot autonomy.

Safety work tells you a robot probably won't hurt anyone. Evidence tells you what
happened when it did. Almost all robot safety research is runtime — keep the
machine inside a bound while it is moving. Very little of it addresses
reconstruction: someone asking, months later and with the robot long since
stopped, what the system knew, what it intended, and what constrained it.

That question has a retention problem attached. Full sensor logs from a humanoid
run to terabytes per day, and on an air-gapped site they cannot leave the
building at all. A scene graph is orders of magnitude smaller. For a regulated
buyer it may be the only representation of an incident you can actually retain,
export, and hand to an assessor or an insurer — which makes the interesting
question not how to record everything, but what the smallest record is that still
answers the questions an assessor will ask.

`reg` is a prototype of that record, in two halves: a temporal scene graph that
answers post-hoc audit questions without replaying raw sensor logs, and a
declaration-and-attestation protocol between an unbounded policy and a bounded
enforcement layer, with a tamper-evident record of every exchange between them.
Everything in the project serves one sentence:

> The model declared it would stay inside this bound. Here is where it tried to
> exceed it. Here is what the enforcement layer did. Here is the signature chain
> proving neither side rewrote the record.

## What this is not

| Not this | Why |
|---|---|
| A perception system — no vision, no SLAM | The thesis is evidence, not perception. Entity positions are ground truth from the simulator. |
| A 3D or realistic robot model | 2D planar demonstrates every claim. |
| An HJ reachability solver | Sampling-based forward reachability on 4–6D state is enough. The result is an **inner** approximation and is labelled as one. |
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
| **1** | **Compression** — evidence graph vs. raw logged state, one size ratio per scenario | `not started` — the headline figure is **not yet measured** |
| **2** | **Query** — audit questions answered from the graph alone, no access to the original stream | `not started` |
| **3** | **Sufficiency boundary** — which claims proprioception-only evidence supports, and which depend on an uncertifiable perceiver | `in progress` — the Layer A/B type boundary and the test that fails when it erodes have landed (`reg/types.py`, `tests/test_layer_boundary.py`); the taxonomy has not |
| **4** | **Attestation** — declaration, independent verification, verdict, tamper-evident chain | `not started` |

## Standards baseline

Four of the load-bearing precedents. [`docs/prior-art.md`](docs/prior-art.md) has
the full treatment, including what this project must *not* claim as novel.

| Precedent | What it establishes | Status |
|---|---|---|
| **UNECE DSSAD** (Data Storage System for Automated Driving, mandated by UN R157) | A regulator already requires a retained evidence recorder for autonomy — and it stores *discrete events*, not continuous state, which is the same retention granularity this project argues for. Its event vocabulary does not transfer: it records transitions of authority between human and system, not the failure modes of a manipulator working near a person. | Regulation completion targeted mid-2026 |
| **EU AI Act Article 12** (with the retention period in Article 19) | High-risk AI systems must technically allow automatic recording of events over their lifetime, retained at least six months. Commentary reads this as requiring decision-level traceability — reconstructing individual decisions, not an activity log. The regulation mandates the capability and says nothing about the artifact. | In force |
| **IEC 61784-3 black channel** / PROFIsafe | Assurance lives in the endpoints; the uncertifiable middle is declared out of scope. `reg` applies this to a learned policy — and deviates deliberately by using HMAC rather than PROFIsafe's CRC, because its threat model includes an adversary who has read the spec. | Published |
| **UL 4600** | Autonomous systems are certified through a structured claim → argument → evidence safety case rather than a test result. | Published (ANSI/UL 4600) |

The gap: ISO 25785-1 will specify what the *robot* must do and UL 4600 specifies
how to structure the *evidence*. Nothing specifies what the model must **emit** so
an OEM can build its safety case. Automated driving has a mandated evidence
recorder; robotics has none.

## How to run

Python 3.11+. Only `shapely` is load-bearing — polygon union and intersection is
the actual math. `sqlite3`, `hmac` and `hashlib` are stdlib on purpose: the
artifact has to open without a runtime.

```bash
pip install -e ".[dev]"
pytest                      # the whole suite; CI runs exactly this
```

As of this commit that is `5 passed` — the layer boundary tests, which are the
only behaviour there is to test so far.

**There are no CLI entry points yet.** The package currently contains the shared
types and the layer boundary they enforce, and nothing that can be invoked from a
shell. The first executable deliverable is the simulator; the build order for it
and everything after is in [`docs/plan.md`](docs/plan.md). This section will list
commands when they exist and not before.

## Status

Built: the package skeleton, the CI test workflow, and `reg/types.py` — the
shared record types and the Layer A / Layer B split, which is the single most
important structural property in the codebase. Layer A (certifiable) is
proprioception, actuation limits, declarations, verdicts and the chain; Layer B
(uncertifiable) is where anything else in the world is. The envelope computation
takes a `ProprioState`, which has no field naming any entity — that absence *is*
the enforcement, and [`tests/test_layer_boundary.py`](tests/test_layer_boundary.py)
fails if it erodes.

Not built: the simulator, the envelope, declarations, enforcement and the fault
taxonomy, the evidence graph and its SQLite store, the chain, the query API, the
benchmarks, the sufficiency taxonomy. That is nine of the ten phases.

No compression number, no incident report output and no GIF appear on this page
because none of them have been produced yet. A plausible placeholder would be
indistinguishable from a measured result to every later reader, and this project's
whole argument is about the difference.

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
