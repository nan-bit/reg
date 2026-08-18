# reg

> **Scaffold.** The unattended writer is wired up and idle; the project itself is
> not yet defined. See [`CLAUDE.md`](CLAUDE.md) for the conventions that govern
> work here.

## Status

| | |
|---|---|
| Writer (`reg-runner.service`) | installed, supervised, polling |
| Control plane (`agent-ready` label + `epic-advance.yml`) | live |
| Merging | manual — every PR is a draft a human marks ready |
| Stack + CI test workflow | pending |

## How work happens

Groom an issue, label it `agent-ready`, and the writer picks it up within ~2
minutes, cuts a worktree, implements it, and opens a **draft PR**. Dependencies are
`Depends-on: #N` trailers in the issue body; `epic-advance.yml` flips the next tier
when they close.

An issue is ready when it names its **acceptance criteria**, its **affected
areas**, and the **command that verifies it**.

The harness is [`nan-bit/issue-runner`](https://github.com/nan-bit/issue-runner),
installed on the worker host. This repo configures it through `.runner.conf`.

```bash
gh issue edit N --add-label agent-ready
journalctl --user -u reg-runner -f
```
