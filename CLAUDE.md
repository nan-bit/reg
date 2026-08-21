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

Layout: `reg/` is the package, `tests/` mirrors it, `docs/` holds the argument,
`runs/` and `bench/` hold generated output and are not committed.

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
`computed_bound(limits)` is the radius of the **workspace disc** —
`sum(link_lengths) + link_radius`, base at the origin. It takes `Limits`, not a
`ProprioState`: no `q`, no `qd`, no horizon, the same scalar at every frame of
every run. It is sound in the conservative direction — it over-covers, so nothing
inside it is ever falsely accused — and it is **incomplete**: a declaration that
overclaims what the robot could reach within the horizon, but still fits inside
the workspace disc, is not detected. `envelope_overclaim` therefore fires only on
a declaration exceeding the entire workspace. Tightening it soundly needs an
outer-approximative reachable set (ARMTD / ARMOUR, `docs/prior-art.md` §4), which
`docs/plan.md` de-scopes; see `docs/limitations.md` §3. The independence is real
and full-strength; the *capability* is the part that is limited.

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

See [`nan-bit/issue-runner`](https://github.com/nan-bit/issue-runner) — the harness
lives in its own repo and is installed on the worker host, not vendored here. This
repo's only harness-facing files are `.runner.conf` and
`.github/workflows/epic-advance.yml`.
