# The `reg` documents — what each one is for

**Status:** an index, and nothing else · written 2026-08-31 · keep current

Nine documents besides this index, five of them normative over something. This
page exists so that a reader arriving at the folder rather than at the front page
can tell which one answers their question, and — more importantly — which one
wins when two of them disagree.

## Precedence

There is one rule: **where [`plan.md`](plan.md) and
[`prior-art.md`](prior-art.md) disagree, prior art wins and `plan.md` gets
edited.**

## The documents

| Document | What it answers | Standing |
|---|---|---|
| [`plan.md`](plan.md) | What is being built and why: the four claims, the ten phases, the non-goals table. The source document. | Binding for scope. Subordinate to `prior-art.md`. |
| [`prior-art.md`](prior-art.md) | What already exists, what this borrows, and what it must not claim is novel. Six dated passes. | **Normative** where it disagrees with `plan.md`. The one document **exempt from the word budget** in `tests/test_doc_shape.py`: a log of outside work does not get shorter when this package does. |
| [`retention.md`](retention.md) | What the artifact costs to keep, measured — Claim 1's figures, the arithmetic, and how the numbers moved. | Normative for every retention figure published anywhere. |
| [`sufficiency.md`](sufficiency.md) | Which audit questions the artifact answers on its own authority, and which are only as strong as whatever supplied the entity positions — with the basis each tag was computed from recorded beside it, per edge. Claim 3. | **Normative for what this project may claim.** |
| [`limitations.md`](limitations.md) | Each thing the artifact cannot do, what it costs, and what a claim would need in order not to inherit it. | **Normative for what this project may claim.** |
| [`lossiness.md`](lossiness.md) | What the graph keeps, what it discards, what becomes unanswerable, and the three resolution levels. | **Normative.** A design constraint on the graph, not a description of it. |
| [`sensor-baseline.md`](sensor-baseline.md) | Where the sensor-log figure every ratio is computed against comes from. | An **assumption with a sourced range**, never a measurement. |
| [`mobile-base.md`](mobile-base.md) | What allowing the robot to drive does to the bound, the layer boundary and the geometry. | **A design document, and no longer entirely one** — its Tiers 1-3 are built and Tier 4 has started, and its own status line is the authority on which parts. Normative for the mobile track only; defers to `sufficiency.md` and `limitations.md` on what may be claimed. |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | How work gets in and out: grooming an issue, the unattended writer, the draft PR. | Process. See also [`CLAUDE.md`](../CLAUDE.md) for the conventions code must follow. |

## Reading order

- **To evaluate the argument:** [`plan.md`](plan.md), then
  [`prior-art.md`](prior-art.md) before believing anything in it is new, then
  [`sufficiency.md`](sufficiency.md) and [`limitations.md`](limitations.md) for
  what it may not claim.
- **To check a number:** [`retention.md`](retention.md) for what it is and
  [`sensor-baseline.md`](sensor-baseline.md) for what it is measured against.
  The `bytes/hour` tables are re-derived from the code on each CI run by
  `tests/test_published_figures.py`; the six-month totals computed from them —
  `266 GB` among them — are **not**. That module's own
  *What this does not cover* is the list, and it is worth reading before
  treating any figure here as machine-checked.
- **To write code here:** [`CLAUDE.md`](../CLAUDE.md), then
  [`CONTRIBUTING.md`](CONTRIBUTING.md), then
  [`lossiness.md`](lossiness.md) if the change touches what the graph keeps.

## A convention worth knowing before editing any of these

Parts of some of these documents are held to their contents by tests rather
than by review — status headers, the citations they claim have landed, the
`bytes/hour` tables, and the conditions certain figures must be quoted with.
**That is a list, not a guarantee**: most prose here is checked by nobody. If an
edit turns a test red, read the failure before changing the test — it is usually
telling you the edit moved a claim rather than a sentence.
