# Adopting the pattern — what this gives another domain

**Status:** new in #302 · the reusable pattern, stated abstractly · the worked example runs as `tests/test_adopting_example.py` · keep current

The repository argues one domain end to end. For the engineer asking "should we use this?": the pattern abstractly, what the adopter writes versus what the framework provides, and a worked example on a different domain.

## The pattern

1. **Declaration.** The acting side states a bound on what it is about to do — before doing it — and signs the statement. The bound is whatever 2D region the domain's invariant can be expressed as.
2. **Verdict.** An independent side recomputes what actually happened from its own observations — it never reads the declaration — and records whether the bound held.
3. **Commit.** Every record is hash-chained to its predecessor and signed under a separate key per side, so neither side can fabricate the other's records.
4. **Query.** The chained records land in a store that answers questions with the originating service long gone: a cold read.

The "independent recomputation" is whatever observation the adopter trusts; the framework supplies the records, the chain, and the store.

## The reuse boundary

You reuse `reg.declare`, `reg.enforce`, `reg.chain` and `reg.query`: the records, the signing, the chaining, and the cold read over the record tables. You write the domain's observation step — the `Enforcer` class belongs to the repository's worked domain, as do `reg.envelope`, `reg.scenarios` and `reg.sim`. Those stay behind; everything else is the framework.

## Worked example: an agent's tool budget

`tests/test_adopting_example.py` runs the pattern on an agent that must stay within a tool-call and token budget: the policy declares the budget as a rectangle in (calls, kilotokens) space, a small check tests each action's cumulative usage with the real `reg.enforce.escape_region`, and verdicts are real `reg.enforce.Verdict` records chained into a real store — a cold read names the action that exceeded the budget. The record vocabularies (action classes, the nine faults) come from the repository's worked domain; the toy reuses them as labels, and a real adoption defines its own.

## What this doesn't give you

The pattern tells you whether the acting side honored the bound it stated — not whether the bound was the right bound. A budget no agent can meet produces a perfect record of inevitable violations. The bound is engineering judgment; the evidence is what the framework supplies. The excitement lives on ernan.dev, not here.

Conventions for working in this repository: [AGENTS.md](../AGENTS.md).
