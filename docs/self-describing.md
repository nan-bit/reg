# The self-describing artifact — what the file must carry so the prose does not

**Status:** a design document, nothing here is built · written 2026-09-05 ·
normative over nothing yet; where it touches what the project may claim it
defers to [`sufficiency.md`](sufficiency.md) and [`limitations.md`](limitations.md)
until those files carry the change · the build order in §8 is the authority on
what is proposed versus decided

---

## The claim this is about

> **Claim 2.** Audit questions answered from the graph alone, no access to the
> original stream.

> **Claim 3.** …the conditionality of each answer is retained **with the answer**,
> in the artifact, and can be asked about months later.

Both are already written in [`plan.md`](plan.md). Nothing below proposes a new
claim. It proposes that the artifact meet the two it already makes, because in
three respects it does not: an auditor holding the file needs a markdown document
to interpret it, needs the original machine to recompute it, and cannot ask it
one of the two questions §2 of [`limitations.md`](limitations.md) says it answers.

## 1. The three gaps, as they stand today

| # | what an auditor cannot do with the file alone | why | where it is recorded now |
|---|---|---|---|
| 1 | Check a `layer` tag | The tag is written; what it was computed **from** is not | `sufficiency.md` §5.6, §5.9 |
| 2 | Recompute a discarded polygon and trust the result | The artifact records `reg_version` and an envelope-parameter digest, and **not** the shapely/GEOS version or the platform | `limitations.md` §1 |
| 3 | Ask *could the robot have reached (x, y)?* | Only `outer_radius_m` and `outer_area_m2` are retained, not the boundary | `limitations.md` §2, §3 |

**Gap 1 — a tag that is asserted rather than checkable.** `envelope_layer` takes
`Limits` and nothing else. That was sound while the only taint could arrive
through the bounds; since issue #163 the outer set reads `state.base_vel`, and
since issue #156 a `BaseVelocity` may be `DERIVED`. The stream records
`base_vel_source`, so the dependency is *in the file* — but the `HAS_ENVELOPE`
edge is still tagged from `Limits.source` alone, and the two can disagree with
nothing to say so. A reader who trusts the tag gets the pre-#156 answer.

**Gap 2 — recomputation with no stated environment.** The retention argument is
that a polygon may be discarded because it is a deterministic function of the row
and four numbers in `meta`. Issue #175 measured that the function is the
platform's: tables captured on one architecture differ in their last bits on
another. So an auditor who recomputes and disagrees cannot distinguish *wrong
machine* from *the geometry moved* — and those are opposite findings.

**Gap 3 — a radius where the question wants a region.** A stored envelope row
answers *not at that distance*. It cannot answer *not at that point*, because the
boundary is not there to test against. The region is recomputable, which routes
the question straight back through gap 2.

## 2. The test that decides all three

**The cold read.** Open an artifact with the code that reads artifacts and **no
document**. For every claim the file makes, either it can be checked from the file
or it cannot.

This is the acceptance criterion and it must be a test, not a principle. Its shape,
per *a check must be able to fail*:

| state | meaning |
|---|---|
| **pass** | every layer tag re-derives from a basis in the file; every discarded geometry names the environment that would reproduce it |
| **fail** | a tag disagrees with its basis, or a basis is absent where the tag exists |
| **could-not-evaluate** | the artifact predates the schema that carries a basis — reported as such, never as a pass |

The negative ships with it: an artifact whose tag has been edited to disagree with
its own basis must be refused, and one whose basis is intact must not be.

## 3. What moves into the file

| addition | what it buys | cost |
|---|---|---|
| **Environment** in `meta`: shapely and GEOS versions, platform, Python | Gap 2. A recomputation that disagrees becomes attributable | a few rows; schema bump |
| **Layer basis** per tagged edge: the inputs the tag was computed from, each with its provenance | Gap 1, and the tag becomes checkable rather than trusted | a row per input per tagged edge |
| **The outer boundary**, retained rather than projected | Gap 3 | bytes, and the published figures move |

The first is small and unblocks the honesty of the other two. The third is the
expensive one and is a decision, not a task — see §8.

## 4. Where the line falls

**In the file:** what a claim depends on, and what would reproduce it. Anything a
reader must have in order to *check* an answer.

**In prose:** why the Layer A / Layer B cut is the right one, what the prior art
took and what it left, what this project may claim and may not. Anything a reader
must have in order to *agree*.

A document that defines is load-bearing and drifts silently. A document that
argues can be wrong in public and gets corrected. The three gaps above are all
cases of the first kind wearing the second kind's clothes.

## 5. Relation to the documents epic

Issue #170 measured the corpus and diagnosed it correctly: specification and
rationale are interleaved at the paragraph level, and 23% of prose narrates a
past defect. Its method — a normative core, rationale below a line — is right and
this document is written in that shape.

**This is a different cut, one step earlier.** #170 separates specification from
rationale inside the prose. This asks how much of that specification should be
prose at all. The answer changes #170's job: every normative fact the artifact
carries itself is a fact the documents no longer have to state, restate in a
second file, and keep in step.

They are independent and can be done in either order. Doing this one first makes
#170's tiers 2 and 3 smaller.

## 6. What this does not propose

- **No new claim.** §0 quotes the two this serves.
- **No change to the Layer A / Layer B boundary.** A basis records what a tag was
  computed from; it does not move what counts as Layer A. `CLAUDE.md` rule 1 is
  untouched.
- **No dependency.** A version string is `importlib.metadata`; a basis is rows.
- **Not a resolution of the two open decisions.** The envelope-layer minimum
  (`limitations.md` §11) and polygon containment (issue #82) both become
  *answerable* once a basis and a boundary are in the file. Answering them is
  separate, and each still changes what a published claim means.

---

## Why

*Rationale below the line, per #170's method. Nothing above depends on reading it.*

**Why "self-describing" and not "documented".** An assurance case is read by
someone who does not trust the author. Every fact that lives only in the author's
prose is a fact that reader has to take on trust — which is the thing an evidence
artifact exists to avoid. The project already applies this reasoning one level
down: enforcement recomputes its own bound rather than reading the declared one,
and `tests/test_enforce.py` asserts the independence against the source. The same
argument applied to the artifact says the file should carry its own basis.

**Why the drift is not hypothetical.** On 2026-09-05, `sufficiency.md` §5.8 said
*"Nothing in `reg/` writes a posed configuration."* Issue #191 had just made that
false. It was caught because an agent read the paragraph while changing the code,
and it was corrected in the same PR — a good outcome that depended on someone
happening to look. A published figure that drifts from what the code measures
fails the build. Nothing catches a normative sentence that drifts, and there are
hundreds of them.

**Why gap 2 is the one to do first even though it is the smallest.** Gaps 1 and 3
both end in *recompute it and see*. If recomputation cannot be attributed, closing
them buys less than it appears to: an auditor still ends at a disagreement they
cannot resolve. Recording the environment is a few rows and it is what makes the
other two worth doing.

**Why the boundary is a decision and not a task.** Retaining it costs bytes on
every retained envelope, which moves the published figures — the same class of
cost issue #166 paid and #191 avoided only by page alignment. It also interacts
with issue #82: once the boundary is in the file, using it for containment stops
being blocked on recomputation and becomes purely a question about what a fault in
the nine-fault taxonomy means. That question needs a person.

**What this borrows.** Nothing here is novel and the doc should not imply it is.
Recording the toolchain that produced an artifact is ordinary build provenance —
SLSA and in-toto attestations do exactly this, and the artifact already borrows
in-toto's statement shape for `.wake` records. The contribution, if any, stays
where Claim 3 puts it. Before this is built, [`prior-art.md`](prior-art.md) needs
a pass on provenance and reproducible-build practice, and on whether "self-
describing evidence" has a name in the audit literature already. **Assume it does.**

---

## 7. Open questions a person should answer

1. **Basis granularity.** Per edge, or per computed envelope? Per edge is precise
   and multiplies rows; per envelope is cheaper and coarser.
2. **Does the basis change what a `WHERE layer = 'B'` query returns today?** If a
   tag is currently wrong for a `DERIVED` velocity, adding the basis makes it
   visible — and no fixture in this repository states one, so nothing here moves.
   A fixture that does is one line and would settle it.
3. **Does the environment belong in `meta` or in the chain?** In `meta` it is
   descriptive. Signed into the attestation chain it becomes a claim someone made,
   which is stronger and larger.

## 8. Build order

Sized so a bad attempt is cheap, and split on the seam between kinds of work.

**Tier 0 — say what is true.** A `limitations.md` entry stating the three gaps in
the vocabulary above. No behaviour change. Independent of everything below.

**Tier 1 — the argument.** A `prior-art.md` pass on build provenance, in-toto and
SLSA, and on whether self-describing evidence is named in the audit literature.
Everything downstream depends on it, per the rule that prior art wins.

**Tier 2 — the environment in `meta`.** Shapely and GEOS versions, platform,
Python. Schema bump. A recomputation guard that reports could-not-evaluate off the
recording environment rather than a pass or a failure, on the pattern issue #175
established for the bit-identity tables.

**Tier 3 — the cold-read test.** §2, against the fixtures, with its negative. It
can be written the moment tier 2 lands and it is what makes the rest checkable.

**Tier 4 — the layer basis.** Depends on §7 question 1 being answered. Ships with
the `DERIVED` fixture from question 2, because a basis nothing exercises is a
basis nobody knows the shape of.

**Tier 5 — the boundary.** A decision first, then bytes, then a re-measurement and
republish of every figure that moves. Not to be started until tiers 2 and 3 make
the argument for it concrete.

## See also

- [`plan.md`](plan.md) — Claims 2 and 3, which this serves, and the non-goals table.
- [`limitations.md`](limitations.md) — §1 (the platform), §2 and §3 (the radius),
  §11 (the tag that does not follow its value).
- [`lossiness.md`](lossiness.md) — the retention rules this would qualify.
- [`mobile-base.md`](mobile-base.md) — where the fixed-base assumption stopped
  hiding the distinction, and why the gaps became visible now.
