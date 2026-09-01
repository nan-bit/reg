# reg — conventions

Read this before writing code here. The unattended writer tells every agent it
launches to follow this file, so it is the contract for work that lands while
nobody is watching.

`reg` is a **reachability evidence graph** — a retainable evidence artifact for
robot autonomy. Read [`docs/plan.md`](docs/plan.md) before writing code, and
[`docs/prior-art.md`](docs/prior-art.md) before claiming anything is novel.

## Stack

Python 3.11+ · `numpy` · `shapely` · `sqlite3` (stdlib) · `matplotlib` ·
`hmac`/`hashlib` (stdlib) · `pytest`

```bash
pip install -e ".[dev]"
pytest                      # the whole suite; CI runs exactly this
```

Layout: `reg/` is the package, `docs/` holds the argument, `runs/` and `bench/`
hold generated output and are not committed. `tests/` mirrors `reg/` — a new
module gets `tests/test_<module>.py` — with four named exceptions: `sim.py`,
`store.py`, `types.py` and `world.py` are verified through the tests of their
consumers rather than through a mirrored file, because for those a mirrored file
would say less about where they are actually checked, not more.
`tests/test_layout.py` holds that list, says where each one is verified, and
fails if a module appears with neither a mirrored test nor an entry. It is not a
place to park a new module.

**Do not add dependencies.** Only `shapely` is load-bearing — polygon union and
intersection is the actual math. No `networkx`, no `pyarrow`, no PyBullet, no
DuckDB; each was considered and rejected in `docs/plan.md`. If you believe one is
needed, say so in the PR and do not add it.

## The three rules specific to this project

**1. The Layer A / Layer B boundary is structural, not conventional.** Layer A
(certifiable) is proprioception, actuation limits, declarations, verdicts, the
chain. Layer B (uncertifiable) is where anything else in the world is. The
envelope takes a `ProprioState`, which has no field naming any entity — that
absence *is* the enforcement, and `tests/test_layer_boundary.py` fails if it
erodes. Widening Layer A changes what this project can claim; it is never a
refactor.

*Actuation limits are on that list conditionally, and the condition is recorded.*
Name-based enforcement covers the envelope's state argument, not its bounds:
`Limits` names nothing outside the robot either, and under ISO/TS 15066
speed-and-separation monitoring `qd_max` is a function of a *measured* separation
distance. A taint arriving in a value cannot be caught by inspecting names, so
`Limits.source` is required with no default, `reg.envelope.envelope_layer` maps
it to a layer, and the `HAS_ENVELOPE` edge is tagged from that — `PROPRIOCEPTIVE`
gives `A`, `DERIVED` gives `B`. Do not give `source` a default and do not infer
it; an artifact with no `meta['limits_source']` is a could-not-evaluate and must
not read as a clean Layer A one. Issue #84, `docs/sufficiency.md` §7,
`docs/limitations.md` §4.

**2. Determinism is non-negotiable.** Seed everything; take the seed as an
argument and record it. Same seed, same bytes. An audit artifact that is not
reproducible is not an audit artifact, and CI compares two runs.

**3. Enforcement must not trust the policy.** `reg/enforce.py` computes its own
bound and imports from `declare/` no further than the dataclass. A constraint
layer supplied by the same party as the policy has common-cause failure with it —
that independence is the mechanism, not a style preference, and
`tests/test_enforce.py::test_enforce_imports_from_declare_no_further_than_the_dataclass`
asserts it against the source. Widening that import is never a refactor.

*What the bound is, so nobody reads more into "its own" than is there.*
`horizon_bound(state, limits, window, substep_dt)` is the radius a declared
region is tested against: the **smaller** of `computed_bound(limits)` — the
workspace disc, `sum(link_lengths) + link_radius`, base at the origin, no `q`,
no `qd`, no horizon — and the radial projection of `reg.envelope.outer_envelope`,
a horizon-limited **outer** reachable set (issue #82). Both over-cover, and the
minimum of two sound bounds is sound, so nothing inside is ever falsely accused.
It is still **incomplete, radially now rather than entirely**: it detects a
declaration reaching further than the robot can get in the window, and not one
pointing where the robot cannot turn in time. The polygon that would catch the
second is computed and retained as `outer_area_m2` / `outer_radius_m` per
envelope; using it for containment re-labels three of the five fault fixtures,
which changes what a fault in the taxonomy means, so it is an open decision and
not a tightening anyone should take unilaterally. See `docs/limitations.md` §2
and §3. The independence is real and full-strength; the *capability* is the part
that is limited.

*`Enforcer.offer` takes the state, and it is required.* The tighter bound is a
function of where the arm is and how fast it is moving, so `offer(declaration,
state)` has no default for its second argument. An invented state would produce a
plausible bound for a robot that was somewhere else — the one failure mode a bound
that VETOes must not have. `reg.envelope.outer_envelope` is where the soundness
argument lives, in four steps, and
`tests/test_envelope.py::test_no_bang_bang_trajectory_escapes_the_outer_envelope`
is what keeps it true. Weakening either is never a refactor.

## Scope

`docs/plan.md` has a non-goals table. It is binding. If a task does not serve one
of the four claims, it is out of scope — say so in the PR rather than building it.
When a phase's success criterion is met, stop; do not gold-plate.

## Writing code

- **Never invent a default.** If a parameter, threshold or limit is not supplied,
  fail loudly and name what is missing. A plausible invented number is
  indistinguishable from a supplied one everywhere downstream, so it does not
  surface as a bug — it surfaces as behaviour nobody can explain, months later.
- **Tests are the deliverable**, not a courtesy. New behaviour without a test that
  would fail if the behaviour regressed is incomplete work. Prefer invariants to
  golden values.
- **A check must be able to fail.** Anything that gates something reports *pass*,
  *fail*, or *could-not-evaluate* — and the third never resolves to the first.
  Silence, an empty list and an unparsed payload are all could-not-evaluate. Ship
  the negative test with it: feed it the condition it guards against and assert it
  says no.
- **Prefer a smaller correct change** to a larger speculative one.

## Queueing work for the writer

Grooming is the whole job. The writer is good at doing a well-specified thing and
has no way to ask what you meant, so an issue is the entire specification and the
only one it gets.

**An issue is queueable when it names three things.**

1. **Acceptance criteria** — what must be true when it is done, in terms someone
   other than the author can check.
2. **`## Affected areas`** — the paths the change should touch, under that
   heading.
3. **The command that verifies it** — usually `pytest`. If the issue names a
   command, that command is the definition of done.

Then `gh issue edit N --add-label agent-ready`. The label *is* the queue; the
writer polls every two minutes and claims one issue at a time.

**The heading is parsed literally, and this is the part that fails quietly.** The
writer looks for a markdown heading matching `affected areas`, case-insensitive,
at any level — `## Affected areas` is the conventional form. It reads until the
next heading. Write "Affected files:", or put the paths in a bullet with no
heading above them, and the parse returns nothing: the verdict becomes
`undeclared`, the scope check stops being a check, and nothing says so at the
time. An issue that looks well-written and is not queueable is the failure mode
this paragraph exists to prevent.

Inside the section the parser is deliberately forgiving — backticks, stray
punctuation and a bare filename all work — because a declaration that fails to
match produces a false "this went out of scope", and a check that cries wolf gets
switched off within a week. The generosity is about the *declaration*, never
about the reach.

**What the declaration is for.** After each attempt the writer computes what the
change reached and compares it against these paths, then writes the result to
`.wake/` on the branch. A reach outside the declaration is reported on the PR. So
the section is not paperwork: it is the only thing that makes an out-of-scope edit
visible, and an issue without one buys a record that can say nothing about scope.
Declare where you expect the work to land — not the whole repository, and not one
file when you know a test will follow.

**Declare `tests/` whenever the work will need a test, which here is nearly
always.** *Tests are the deliverable* is a rule of this repository, so an agent
that adds one is following the repo; if the declaration named only the file being
changed, the record then reports the test as out of scope. That has happened on
three consecutive attempts, and every time the finding was correct and useless —
it flagged the agent for obeying `CLAUDE.md`.

A scope check that fires on the expected shape of the work teaches you to ignore
it, which costs the findings you would have wanted. Declaring the test path is
cheaper than learning to skim past the report.

**Dependencies** go in the body as a `Depends-on: #12, #14` trailer, so a human
reading the issue sees them. A tier does not flip to `agent-ready` until
everything it depends on is closed.

**Labels that mean a person decides:** `needs-human`, `blocked`, `epic`. The
advance workflow never flips an issue carrying one.

**Size it so a bad attempt is cheap.** The writer opens draft PRs and merges
nothing, so the cost of a wrong attempt is a closed PR. Issues that are small,
verifiable and independent are worth more than issues that are ambitious.

## Working unattended

- One issue → one worktree → one branch → one **draft** PR. A human marks it
  ready; nothing on the host merges.
- Stay inside the issue's "Affected areas". An unexplained edit outside scope
  becomes someone else's merge conflict — concurrent agents share this repo.
- Run the issue's stated verification before opening the PR and paste the output
  into the PR body. If the issue names a command, that command is the definition
  of done.
- `Closes #N` when the acceptance criteria are met. `Refs #N` leaves the issue
  open, which blocks every task declaring `Depends-on: #N` and stalls the tier —
  it is not the cautious choice.
- Do not modify `.github/workflows/**` or `.runner.conf`. That is the machinery
  running you.

## Commits and PRs

- No `Co-Authored-By` trailer, no "Generated with Claude Code" trailer.
- Conventional-commit subjects (`feat:`, `fix:`, `docs:`, `chore:`), referencing
  the issue number.

## How the runner works

See [`nan-bit/wake-runner`](https://github.com/nan-bit/wake-runner) — the harness
lives in its own repo and is installed on the worker host, not vendored here. It
is what writes unattended changes in this repository, and `.runner.conf` pins the
version of it that does.
[`nan-bit/issue-runner`](https://github.com/nan-bit/issue-runner) is the archived
predecessor: older commit messages and issues here name it, and none of them mean
the harness running now.

This repo's only harness-facing files are `.runner.conf` and
`.github/workflows/epic-advance.yml`. `.wake/` is not a third one — it is not
configuration at all, but output: the harness writes a record of each attempt
there, on the branch that attempt is working on. Do not hand-edit those records
and do not delete them, including the ones left by an earlier attempt at the
issue you are on. What a record holds is wake-runner's to document; this file
saying it too is how the two drift apart.
