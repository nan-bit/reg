# Contributing to reg

Work here arrives one way: as a **groomed issue labelled `agent-ready`**, picked up
by the unattended writer, landing as a **draft pull request** that a human marks
ready. There is no other path — nothing on the worker host merges, and no agent
marks its own PR ready.

This file describes that path. The conventions the code itself must follow live in
[`AGENTS.md`](../AGENTS.md); this is about how work gets in and out.

## The path a change takes

The run's rules are [`AGENTS.md`](../AGENTS.md)'s *Working unattended*: one
issue → one worktree → one branch → one **draft** PR, and nothing on the worker
host merges. This file does not restate them.

```bash
gh issue edit N --add-label agent-ready   # queue an issue
journalctl --user -u reg-runner -f        # watch the writer work
```

## What makes an issue ready

An issue is ready when a writer that cannot ask a follow-up question could
still finish it. The rules — acceptance criteria, the literal
`## Affected areas` heading, the command that verifies it, the rule to declare `tests/`
whenever the work will need a test, and the `Depends-on: #N` order trailer —
are [`AGENTS.md`](../AGENTS.md)'s *Queueing work*. This file does not restate
them.
## What lands in a pull request

Always a draft; the verification output pasted into the body; `Closes #N`
when the acceptance criteria are met. The repo's rules for the change itself
are [`AGENTS.md`](../AGENTS.md)'s *Commits*. This file does not restate them.

## What is off limits

`.github/workflows/**` and `.runner.conf` are the machinery that runs the writer,
not the product, and [`AGENTS.md`](../AGENTS.md) puts them off limits to it. An agent
editing them mid-flight would be changing the rules of the run it is inside, and a
writer that breaks itself cannot report that it did. Changes there are made by a
human, in a separate PR. An issue that genuinely requires them gets the rest of its
scope done, and a note in the PR body naming the change a human still has to make.

## For humans working directly

The same conventions apply. Branch, open a draft PR, name what verifies it. If you
are touching something an `agent-ready` issue also names, expect a conflict and say
so in the PR.
