# The self-describing artifact — what the file must carry so the prose does not

**Status:** a design document; tiers 0 and 1 of §8 have landed and no code here is
built · written 2026-09-05, tier 1's findings folded in 2026-09-05 · normative over nothing yet; where it touches what
the project may claim it defers to [`sufficiency.md`](sufficiency.md) and
[`limitations.md`](limitations.md) until those files carry the change · the build
order in §8 is the authority on what is proposed versus decided

**§1 is now carried by [`limitations.md`](limitations.md) §12** (issue #198), which
is where the three gaps are normative. The table below is the same finding stated
for this document's own argument; where the two differ, `limitations.md` wins,
because that is the file that says what this project may claim.

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

*Normative in [`limitations.md`](limitations.md) §12; what follows is this
document's statement of the same three, for the argument it goes on to make.*

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

*That sentence declares a reader, and after the sixth prior-art pass it says so.*
"The code that reads artifacts and no document" is a statement about what the
reader already knows — in OAIS's vocabulary a **Designated Community's Knowledge
Base**, which is the only thing that terminates the recursion of what an artifact
must carry ([`prior-art.md`](prior-art.md) §29). The declaration is not new; it was
being made in passing. The reader it names is §4's, and the test is relative to
that reader and to no other.

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

**What the sixth prior-art pass changed about the first row** ([`prior-art.md`](prior-art.md)
§27, §28):

- **The content is adopted, not derived.** An environment record is a
  **buildinfo** — the Reproducible Builds project's name for it — and that project
  is the precedent, not SLSA. The list to carry is *the dependencies and their
  versions, the configuration and the environment variables the computation
  actually uses*, minimised rather than enumerated. C2PA carries the same idea one
  layer up in `claim_generator_info`, which records a claim generator's name,
  version and operating system.
- **Putting it in `meta` is a deviation from that practice, and is stated as
  one.** A buildinfo is deliberately *a separate product beside the artifact*,
  because an archive can distribute it to whoever wants to rebuild. Claim 2 says
  this file answers with no access to anything else, which is a stronger
  requirement than the practice has, so the record goes inside. That reason is the
  deviation's whole justification and it belongs wherever the schema is specified
  — the pattern is [`prior-art.md`](prior-art.md) §5's PROFIsafe deviation.
- **"Attributable" is the weaker half and must not stand unqualified.** Recording
  the environment turns *an unresolvable disagreement* into *a could-not-evaluate*.
  It does not say which library moved the geometry; `diffoscope` exists because a
  version list does not give that, and nothing here proposes building one.
- **The third row has an alternative it did not consider.** C2PA **redacts** —
  removes an assertion, records that it was removed, and the signature still
  validates. Retaining the boundary and discarding it as recomputable are not the
  only two options, and redaction is the one that does not route back through
  gap 2. Choosing is §7's kind of question, not this table's.

## 4. Where the line falls

**Restated after the sixth prior-art pass ([`prior-art.md`](prior-art.md) §29),
which superseded the first version of this section.** The line does not fall
between *in the file* and *in prose*, because that boundary cannot be drawn on its
own terms: there is no quantity of material that makes an artifact
self-interpreting to a reader nobody has named, and a small quantity suffices for
a reader who has been. OAIS calls the material **Representation Information**,
observes that it recurses — a schema needs its schema language, which needs its
own specification — and terminates the recursion in exactly one place: a
**declared Designated Community** and what it already knows.

**So the line is drawn by naming the reader, and this project's reader is
already named.** [`prior-art.md`](prior-art.md) §12 identifies it as IEEE
7001-2021's **incident and accident investigator** — one of that standard's five
stakeholder groups, and the one every claim here addresses.

**In the file:** what a claim depends on, and what would reproduce it, *for an
investigator holding the file* — anything that reader must have in order to
*check* an answer, and does not already have.

**Identified, retained and referenced from the file — which may be prose:** why
the Layer A / Layer B cut is the right one, what the prior art took and what it
left, what this project may claim and may not. Anything a reader must have in
order to *agree*. OAIS does not require Representation Information to live inside
the package; it requires it to be identified, retained and itself preserved, and
the working pattern is a registry the object points at. `docs/` is not
disqualified by being prose. It is disqualified by being unversioned, unhashed and
unreferenced from any artifact — which is a smaller and more fixable defect than
the one the first version of this section diagnosed.

A document that defines is load-bearing and drifts silently. A document that
argues can be wrong in public and gets corrected. The three gaps above are all
cases of the first kind wearing the second kind's clothes.

*The other name, and it disagrees.* In the law of evidence the term of art is
**self-authenticating**, and FRE 902(13)–(14) admit a hash-identified electronic
record only on the certification of a **qualified person**. The hash is necessary
and explicitly not sufficient. Nothing in this document proposes a certifier
field; [`prior-art.md`](prior-art.md) §29 records that whether there should be one
is a person's decision.

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

**What the sixth prior-art pass changed** (issue #199;
[`prior-art.md`](prior-art.md) §26–§29, 2026-09-05 — tier 1 of §8, and the pass
this document ordered before anything here is built). It did not end the track and
it changed four things:

1. **§26 corrected this document.** *"SLSA and in-toto attestations do exactly
   this"* was wrong and is edited below. That literature gives the **statement
   shape** — a signed predicate about a subject digest, which this repository's
   `.wake` records already use — and *not* an environment record: SLSA identifies
   the build platform and requires the verifier to trust it, its
   environment-adjacent fields are optional and best-effort, and it declines to
   require reproducible builds at any level.
2. **§27 found gap 2 solved, with a standard shape, and this document should
   adopt rather than invent.** The shape is the Reproducible Builds project's
   **buildinfo**, and reproducibility there is defined *relative to a stated
   environment* — which is what makes issue #175 an ordinary finding rather than a
   peculiar one. §3 above carries what that changes: adopt the content list, state
   the in-`meta` placement as a deviation with Claim 2 as its reason, and stop
   using *attributable* unqualified.
3. **§28 supplied the shipped precedent and one alternative.** C2PA's
   `claim_generator_info` already records software, version and OS inside a
   hash-bound manifest, so nothing about §3's first row is novel; and **redaction**
   is a standardised alternative to discard-because-recomputable that does not
   route back through gap 2.
4. **§29 superseded §4 and reframed §2.** *Self-describing* has an older name —
   OAIS **Representation Information** — which recurses and terminates only at a
   **declared Designated Community**, so the line is drawn by naming the reader
   rather than by choosing file-versus-prose. The audit and legal literature's
   other name, **self-authenticating**, requires a qualified person's certification
   in addition to the hash, which this artifact has no field for.

**The three gaps and the build order stand.** Nothing in the pass weakens the case
for tier 2; §29 strengthens it, because an environment record is Representation
Information on any reading.

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
Recording the toolchain that produced an artifact is ordinary build provenance,
and the precedent is the **Reproducible Builds** project's buildinfo — an
environment record produced beside the artifact, without which a rebuild that
disagrees is unattributable ([`prior-art.md`](prior-art.md) §27). C2PA carries the
same idea inside a hash-bound manifest, in `claim_generator_info` (§28). What
**SLSA and in-toto** supply is the *statement shape* — a signed predicate about a
subject digest, which this repository's `.wake` records already use — and not the
environment: SLSA identifies the build platform and requires the verifier to trust
it (§26). The contribution, if any, stays where Claim 3 puts it.

*This paragraph is the correction, dated 2026-09-05.* Before the edit it said
that SLSA and in-toto attestations "do exactly this", and it ordered the pass that
found otherwise. The pass ran as tier 1 (issue #199), the survey's entries are
§26–§29, and §6 above records what it changed. **The assumption that
self-describing evidence already has a name was correct**: it has two — OAIS
*Representation Information* and, in the law of evidence, *self-authenticating*
— and they do not agree about what an artifact can carry on its own.

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
   which is stronger and larger. *The supply-chain literature takes the second
   option* — in-toto and SLSA put provenance inside a **signed** predicate bound to
   a subject digest ([`prior-art.md`](prior-art.md) §26). That is a precedent and
   not an answer: their reason is a builder a verifier must trust, and this
   artifact's reason would be Claim 3. Still a person's decision.

## 8. Build order

Sized so a bad attempt is cheap, and split on the seam between kinds of work.

**Tier 0 — say what is true. Landed** (issue #198): [`limitations.md`](limitations.md)
§12 states the three gaps in the vocabulary above, cross-referencing §1, §2, §3
and §11 rather than restating them. No behaviour change. It was independent of
everything below and remains so — nothing here is unblocked by it.

**Tier 1 — the argument. Landed** (issue #199): the
[`prior-art.md`](prior-art.md) sixth pass, §26–§29, on build provenance, in-toto
and SLSA, Reproducible Builds, C2PA, and on whether self-describing evidence is
named in the audit literature. It is. The pass did not end the track; §6 records
what it changed, and the changes are to this document's §2, §3, §4 and §7, not to
the tiers below. Everything downstream depended on it, per the rule that prior art
wins.

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

- [`prior-art.md`](prior-art.md) — §26–§29, the sixth pass this document ordered
  and which corrected it; §12 for the reader §4's line is drawn around; §5 for the
  pattern a stated deviation from a practice takes.
- [`plan.md`](plan.md) — Claims 2 and 3, which this serves, and the non-goals table.
- [`limitations.md`](limitations.md) — §12 (the three gaps as one finding, which
  is where they are normative), and the entries it cross-references: §1 (the
  platform), §2 and §3 (the radius), §11 (the tag that does not follow its value).
- [`lossiness.md`](lossiness.md) — the retention rules this would qualify.
- [`mobile-base.md`](mobile-base.md) — where the fixed-base assumption stopped
  hiding the distinction, and why the gaps became visible now.
