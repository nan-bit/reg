# Contributing to reg

Work here arrives one way: as a **groomed issue labelled `agent-ready`**, picked up
by the unattended writer, landing as a **draft pull request** that a human marks
ready. There is no other path — nothing on the worker host merges, and no agent
marks its own PR ready.

This file describes that path. The conventions the code itself must follow live in
[`CLAUDE.md`](../CLAUDE.md); this is about how work gets in and out.

## The path a change takes

1. **Someone grooms an issue.** Not a wish — a specification (see below).
2. **Someone labels it `agent-ready`.** That label is the queue. Applying it is the
   decision to spend a writer pass on the issue; it is a human action, deliberately.
3. **The writer picks it up** within ~2 minutes of polling, cuts a fresh worktree
   and branch (`auto/issue-N`) off `origin/main`, and implements the issue there.
   One issue → one worktree → one branch → one PR.
4. **The writer runs the issue's stated verification** and opens a **draft PR** with
   that output pasted into the body.
5. **A human reviews and marks it ready.** Merging is manual. A draft PR is the
   writer saying "here is my work"; marking it ready is a person saying "I have read
   it". Those are different claims and the machine only makes the first one.

```bash
gh issue edit N --add-label agent-ready   # queue an issue
journalctl --user -u reg-runner -f        # watch the writer work
```

## What makes an issue ready

An issue is ready when a writer that cannot ask a follow-up question could still
finish it. Concretely, it names three things:

- **Acceptance criteria** — what must be true when the work is done, stated so that
  a reader can check each one rather than judge them.
- **Affected areas** — the paths the change is allowed to touch. Concurrent agents
  share this repo, and an unexplained edit outside the stated areas becomes someone
  else's merge conflict.
- **Verification** — the command that decides done. If the issue names a command,
  that command *is* the definition of done, and its output belongs in the PR body.

Anything the writer would otherwise have to invent — a threshold, a limit, a
filename, a default — belongs in the issue, for the reason [`CLAUDE.md`](../CLAUDE.md)
gives under *Never invent a default*. If it is missing, the writer is expected to
say so loudly rather than fill the gap.

### Dependencies between issues

Issues declare order with a `Depends-on: #N` trailer in the body. The
`epic-advance.yml` workflow flips the next tier to `agent-ready` when the issues it
depends on **close** — so a PR that says `Refs #N` instead of `Closes #N` leaves
`#N` open and stalls every task waiting on it. `Refs` is the right choice only when
scope was knowingly left unfinished, and then the PR body says exactly what remains.

## What lands in a pull request

- **Always a draft.** A human marks it ready.
- **The verification output**, pasted into the body.
- **`Closes #N`** when the acceptance criteria are met.
- **The repo's rules for the change itself** — tests as the deliverable, the
  negative test beside anything that acts as a check, a smaller correct change in
  preference to a larger speculative one, and conventional-commit subjects with no
  `Co-Authored-By` and no "Generated with Claude Code" trailer. Each is stated in
  full in [`CLAUDE.md`](../CLAUDE.md), and they apply to the writer because they are
  the repo's, not the other way round.

## What is off limits

`.github/workflows/**` and `.runner.conf` are the machinery that runs the writer,
not the product, and [`CLAUDE.md`](../CLAUDE.md) puts them off limits to it. Changes
there are made by a human, in a separate PR. An issue that genuinely requires them
gets the rest of its scope done and a note in the PR body naming the change that was
not made.

## For humans working directly

The same conventions apply. Branch, open a draft PR, name what verifies it. If you
are touching something an `agent-ready` issue also names, expect a conflict and say
so in the PR.
