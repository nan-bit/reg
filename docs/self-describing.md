# The self-describing artifact — what the file must carry so the prose does not

**Status:** a design document; **every tier of §8 has landed** · written
2026-09-05, tiers 0 to 2 2026-09-05, tier 3 2026-09-07 to 2026-09-11, tier 4
2026-09-08, tier 5 2026-09-10 to 2026-09-11 · normative over nothing yet; where it touches what the project may
claim it defers to [`sufficiency.md`](sufficiency.md) and
[`limitations.md`](limitations.md) until those files carry the change · §8 is
the authority on what landed and carries the issue numbers per tier

This file says what the artifact must carry so that a reader need not trust the
prose. The three gaps that motivated it are normative in
[`limitations.md`](limitations.md) §12 and their state is what `--cold-read`
prints; what stays here is the rule that draws the line, the deviation the
environment record makes, and the build order.

---

## The claim this is about

> **Claim 2.** Audit questions answered from the graph alone, no access to the
> original stream.

> **Claim 3.** …the conditionality of each answer is retained **with the answer**,
> in the artifact, and can be asked about months later.

Both are already written in [`plan.md`](plan.md). Nothing below proposes a new
claim. It proposes that the artifact meet the two it already makes.

## 1. The three gaps

**Normative in [`limitations.md`](limitations.md) §12**, whose table rows 1 to 3
are these same three gaps under the same numbering, each with how it closed and
what is left of it. What the *artifact* says about them is not prose at all:
`python -m reg.query FILE --cold-read` prints one row per claim the file makes
about itself, and §2 is what that report is.

## 2. The test that decides all three

**The cold read.** Open an artifact with the code that reads artifacts and **no
document**. For every claim the file makes, either it can be checked from the file
or it cannot.

*That sentence declares a reader.* "The code that reads artifacts and no
document" names what the reader already knows, which is the only thing that
terminates the recursion of what an artifact must carry
([`prior-art.md`](prior-art.md) §29). The reader it names is §4's, and the test is
relative to that reader and to no other.

**Landed as `reg.query.cold_read`, and it is not a test.** It ships in the
package because the audience is an assessor holding a file, and a check they
cannot run tells them nothing. `python -m reg.query FILE --cold-read` prints the
rows, their five states and what each rests on — read off the file rather than
restated here.

**What that report does not carry is which claim each row serves.**
`ColdReadClaim` holds a claim, a question, a state and a detail, and no claim
number, so the mapping onto [`plan.md`](plan.md)'s four is here:

| claim | the rows that serve it |
|---|---|
| 1 | `recompute-discarded-polygon` |
| 2 | `reached-point` |
| 3 | `layer-tag-basis` |
| 4 | `chain-intact`, `passivation-acknowledged` |
| under none | `recording-environment`, which Claim 1's row rests on, and `disclosures-stated`, which reads back what the deployer states about [`limitations.md`](limitations.md) §8's obligations |

*Checkable with a key the file does not contain* is not a weaker form of
*checkable*: a MAC verifiable with nothing but the file it sits in attests to
nobody, so the gate **is** the design, and a report flattening that row into
either neighbour would call a deliberate gate a shortcoming.

**The negatives ship with it.** `tests/test_query.py` pins every row per shipped
fixture and feeds the report each condition a state guards against, including
the states no healthy artifact produces.

**It closes no gap.** It makes them legible from the file, which is what let
#228 be judged by more than a PR body.

## 3. What moves into the file

**The environment record is adopted rather than derived, and its placement is a
deviation from the practice it is adopted from.** A **buildinfo** is deliberately
*a separate product beside the artifact*, because an archive can distribute it to
whoever wants to rebuild ([`prior-art.md`](prior-art.md) §27). Claim 2 says this
file answers with no access to anything else, which is a stronger requirement
than the practice has, so the record goes inside: `reg.store.ENVIRONMENT_KEYS`,
six keys, the five of them in `reg.graph.RECOMPUTE_ENVIRONMENT_KEYS` compared
before `envelope_at` will recompute a discarded polygon. A deviation's reason
belongs wherever the schema is specified — the pattern is
[`prior-art.md`](prior-art.md) §5's PROFIsafe deviation — and it is stated at
`reg.store.ENVIRONMENT_KEYS` and at [`lossiness.md`](lossiness.md) *Discarded* #9.

**What the departure costs**, said in the same breath as its reason: the
environment cannot be handed to a rebuilder without handing over the artifact,
and it is descriptive `meta` — nothing in the chain signs it, so a party who can
rewrite the file can rewrite its environment too. §7 question 3 is where that
second half is still a person's decision.

**"Attributable" is the weaker half and must not stand unqualified.** Recording
the environment turns *an unresolvable disagreement* into *a could-not-evaluate*.
It does not say which library moved the geometry; `diffoscope` exists because a
version list does not give that ([`prior-art.md`](prior-art.md) §27), and nothing
here proposes building one.

**Retaining the boundary had an alternative this document did not consider.**
C2PA **redacts** — removes an assertion, records that it was removed, and the
signature still validates ([`prior-art.md`](prior-art.md) §28). Retaining a
polygon and discarding it as recomputable are not the only two options, and
redaction is the one that does not route back through the recomputation gap
([`limitations.md`](limitations.md) §12, row 2). Choosing is §7's kind of
question.

## 4. Where the line falls

**Restated after the sixth prior-art pass ([`prior-art.md`](prior-art.md) §29),
which superseded the first version of this section.** The line does not fall
between *in the file* and *in prose*, because that boundary cannot be drawn on its
own terms: there is no quantity of material that makes an artifact
self-interpreting to a reader nobody has named, and a small quantity suffices for
a reader who has been. OAIS calls the material **Representation Information**, and
terminates its recursion in exactly one place: a **declared Designated Community**
and what it already knows.

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
argues can be wrong in public and gets corrected. The three gaps
[`limitations.md`](limitations.md) §12 states are all cases of the first kind
wearing the second kind's clothes.

*The other name, and it disagrees.* In the law of evidence the term of art is
**self-authenticating**, and FRE 902(13)–(14) admit a hash-identified electronic
record only on the certification of a **qualified person**. The hash is necessary
and explicitly not sufficient. Nothing in this document proposes a certifier
field; [`prior-art.md`](prior-art.md) §29 records that whether there should be one
is a person's decision.

## 5. Relation to the documents epic

**Cut.** #170 is closed, and its method — a normative core with rationale below a
line — is the shape this document is written in.

## 6. What this does not propose

- **No new claim.** *The claim this is about* quotes the two this serves.
- **No change to the Layer A / Layer B boundary.** A basis records what a tag was
  computed from; it does not move what counts as Layer A. `CLAUDE.md` rule 1 is
  untouched.
- **No dependency.** A version string is `importlib.metadata`; a basis is rows.
- **Not a resolution of polygon containment** (issue #82), which became
  *answerable* once a boundary was in the file. Answering it is separate and
  still changes what a published claim means. The envelope-layer minimum was the
  other open decision here and is one no longer: issue #252 adopted it, and
  [`limitations.md`](limitations.md) §11's amendment is where that is recorded.

**What the sixth prior-art pass changed** ([`prior-art.md`](prior-art.md)
§26–§29) now lives in §3, the buildinfo deviation and *attributable* qualified;
§4, the reader; §7 question 3; and *What this borrows*, the SLSA correction. That
file's table names the sections each change first landed in, which this one no
longer carries. It did not end the track: §29 strengthens the case for tier 2,
because an environment record is Representation Information on any reading.

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

---

## 7. Open questions a person should answer

3. **Does the environment belong in `meta` or in the chain?** In `meta` it is
   descriptive. Signed into the attestation chain it becomes a claim someone made,
   which is stronger and larger. *The supply-chain literature takes the second
   option* — in-toto and SLSA put provenance inside a **signed** predicate bound to
   a subject digest ([`prior-art.md`](prior-art.md) §26). That is a precedent and
   not an answer: their reason is a builder a verifier must trust, and this
   artifact's reason would be Claim 3. Still a person's decision.

## 8. Build order

Sized so a bad attempt is cheap, and split on the seam between writing the data
and using it: only the second changes what a query answers. Every tier has
landed.

- **Tier 0 — say what is true.** #198, 2026-09-05:
  [`limitations.md`](limitations.md) §12 states the three gaps.
- **Tier 1 — the argument.** #199, 2026-09-05: the
  [`prior-art.md`](prior-art.md) sixth pass, §26–§29, which everything below
  depended on, per the rule that prior art wins.
- **Tier 2 — the environment in `meta`.** #200 and #201, 2026-09-05: six keys
  from `reg.store.build_environment` at `SCHEMA_VERSION` 11, and
  `reg.graph.envelope_at` refusing to recompute off the recording environment.
  No published figure moved.
- **Tier 3 — the cold read.** #231, #242 and #262, 2026-09-07 to 2026-09-11:
  `reg.query.cold_read` and `--cold-read`, seven claims in five states.
- **Tier 4 — the layer basis.** #252, 2026-09-08: option A, per edge, as
  `reg.store.EDGE_BASIS_TABLE` at `SCHEMA_VERSION` 13, with `envelope_layer` the
  weakest of its inputs and `open_edge` refusing an edge whose tag disagrees
  with it. Every published retention figure moved.
- **Tier 5 — the boundary.** #257, #258 and #265, 2026-09-10 to 2026-09-11:
  `envelope.outer_wkb` at `SCHEMA_VERSION` 14 under option C, plus
  `reg.query.reached_point`, `pointwise_coverage` and `--reached-point`. Every
  published retention figure moved again.

**Where the costings are.** Both tiers priced their options before adopting
one, on `long_run` at 3,000 frames with `--seed 0`. The dated tables are **PR
#251**'s (tier 4, `reg.bench --layer-basis`) and **PR #250**'s (tier 5,
`reg.bench --outer-boundary`), the second restated in issue #228's first
comment, 2026-09-07. Both are against the figures published then; the artifact
has since grown, so re-running either describes neither run.

**What tier 4's costing found, and per edge was adopted on.** Per envelope is
cheaper by covering less rather than by sharing, and it cannot express the case
it is priced against: two `HAS_ENVELOPE` edges over one deduplicated envelope
row whose bases differ get one basis between them.

**What tier 5's costing found, and option C was adopted on. The headline figures
do not move at all** — the occurrence level retains no envelope row, so
no boundary reaches the figure Claim 1 is quoted on. C writes 12 boundaries
where B writes 84, and `ENVELOPE_RETENTION` has already capped the pointwise
question at 2.8% of frames, so B buys 84 answerable frames rather than 12. Which
coverage is right is a question about what an incident report cites, and the
ceiling is a separate decision.

## See also

- [`limitations.md`](limitations.md) — §12, where the three gaps are normative,
  and §11's amendment for the tag that did not follow its value.
- [`prior-art.md`](prior-art.md) — §26–§29, the sixth pass this document
  ordered; §12 for the reader §4's line is drawn around; §5 for the pattern a
  stated deviation takes.
- [`plan.md`](plan.md) — Claims 2 and 3, which this serves.
- [`lossiness.md`](lossiness.md) — the retention rules this qualifies.
- [`retention.md`](retention.md) — what tiers 4 and 5 cost, re-measured.
