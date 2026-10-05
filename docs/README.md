# The `reg` documents — what each one is for

**Status:** an index, and nothing else · written 2026-08-31 · keep current

Twelve documents besides this index, five of them normative over something. For
a reader arriving at the folder rather than the front page: which one answers
your question, and — more importantly — which one wins when two of them
disagree.

## Precedence

There is one rule: **where [`plan.md`](plan.md) and
[`prior-art.md`](prior-art.md) disagree, prior art wins and `plan.md` gets
edited.**

## The documents

| Document | What it answers | Standing |
|---|---|---|
| [`plan.md`](plan.md) | What is being built and why: the four claims, the ten phases, the non-goals table. The source document. | Binding for scope. Subordinate to `prior-art.md`. |
| [`prior-art.md`](prior-art.md) | What already exists, what this borrows, and what it must not claim is novel. Six dated passes. | **Normative** over `plan.md`. **Exempt from the word budget**. |
| [`retention.md`](retention.md) | Claim 1's figures: what the artifact costs to keep, measured, and how the numbers moved. | Normative for every retention figure published anywhere. |
| [`sufficiency.md`](sufficiency.md) | Which audit questions the artifact answers on its own authority, and which are only as strong as whatever supplied them — with the basis each tag was computed from recorded beside it, per edge. | **Normative for what this project may claim.** |
| [`limitations.md`](limitations.md) | Each thing the artifact cannot do, what it costs, and what a claim would need in order not to inherit it. | **Normative for what this project may claim.** |
| [`lossiness.md`](lossiness.md) | What the graph keeps, what it discards, what becomes unanswerable, and the three resolution levels. | **Normative** — a design constraint on the graph, not a description of it. |
| [`self-describing.md`](self-describing.md) | What the artifact must carry so a reader need not trust the prose — the three gaps, now normative in `limitations.md` §12. | A design document; §8's tiers have landed. Normative over nothing; defers to `sufficiency.md` and `limitations.md`. |
| [`sensor-baseline.md`](sensor-baseline.md) | Where the sensor-log figure every ratio is computed against comes from. | An **assumption with a sourced range**, never a measurement. |
| [`mobile-base.md`](mobile-base.md) | What allowing the robot to drive does to the bound, the layer boundary and the geometry. | Its status line is the authority for the mobile track; defers to `sufficiency.md` and `limitations.md`. |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | How work gets in and out: grooming an issue, the unattended writer, the draft PR. | Process. See also [`AGENTS.md`](../AGENTS.md). |
| [`adopting.md`](adopting.md) | The reusable pattern without the worked domain, the module-level reuse boundary, and a worked example on a different domain. | For the engineer asking "should we use this?". |
| [`tamper-evidence-design.md`](tamper-evidence-design.md) | The as-built record of the tamper-evidence hardening epic: the threat model, what landed, and what remains. | A design document, not an argument. |

## Reading order

- **To evaluate the argument:** [`plan.md`](plan.md), then
  [`prior-art.md`](prior-art.md) before believing anything in it is new, then
  [`sufficiency.md`](sufficiency.md) and [`limitations.md`](limitations.md) for
  what it may not claim.
- **To check a number:** [`retention.md`](retention.md) for what it is,
  [`sensor-baseline.md`](sensor-baseline.md) for what it is measured against.
  The `bytes/hour` tables are re-derived from code on each CI run; the six-month
  totals computed from them — `267 GB` among them — are **not**. Read
  `test_published_figures.py`'s *What this does not cover* before treating any
  figure here as machine-checked.
- **To write code here:** [`AGENTS.md`](../AGENTS.md), then
  [`CONTRIBUTING.md`](CONTRIBUTING.md), then [`lossiness.md`](lossiness.md) if
  the change touches what the graph keeps.

## A convention worth knowing before editing any of these

Some of these documents are held to their contents by tests, not review —
status headers, landed citations, the `bytes/hour` tables, the conditions
figures must be quoted with. **A list, not a guarantee**: most prose is checked
by nobody. If an edit turns a test red, read the failure before changing the
test — it usually means the edit moved a claim, not a sentence.
