# reg — conventions

Read this before writing code here. The unattended writer tells every agent it
launches to follow this file, so it is the contract for work that lands while
nobody is watching.

> **Stack section pending.** The language, layout, build and test commands land
> here once the project is defined, together with the matching CI workflow in
> `.github/workflows/`. Everything below is independent of that choice.

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
