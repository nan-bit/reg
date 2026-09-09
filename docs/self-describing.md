# The self-describing artifact — what the file must carry so the prose does not

**Status:** a design document; tiers 0-4 of §8 have landed — tier 2 in two
halves, the environment **recorded** (issue #200) and then **acted on** (issue
#201, the recompute path refuses off the recording environment), tier 3 as
`reg.query.cold_read` (issues #231, #242) and tier 4 as the layer basis per edge
(issue #252); tier 5 has its costing (issue #230) and not its decision · written
2026-09-05, tier 1 2026-09-05, tier 2 2026-09-05, tier 3 2026-09-07, tier 4
2026-09-08 · normative
over nothing yet; where it touches what the project may claim it defers to
[`sufficiency.md`](sufficiency.md) and [`limitations.md`](limitations.md) until
those files carry the change · the build order in §8 is the authority on what is
proposed versus decided

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
| ~~1~~ | Check a `layer` tag | The tag was written and what it was computed **from** was not — **closed by issue #252**: `edge_layer_basis` carries one row per input per tagged edge, and the tag is the weakest of them | `sufficiency.md` §5.6, §5.9 |
| 2 | Recompute a discarded polygon and trust the result | The artifact records `reg_version` and an envelope-parameter digest, and **not** the shapely/GEOS version or the platform — **closed in the weaker form by issues #200 and #201**: it records them, and `envelope_at` refuses to recompute where they differ. What is left is that a refusal is not an attribution | `limitations.md` §1 |
| ~~3~~ | Ask *could the robot have reached (x, y)?* | Only `outer_radius_m` and `outer_area_m2` were retained, not the boundary — **narrowed by issue #257**: the boundary is retained wherever the sampled polygon is, so the question is the region's at every frame an edge anchors and radial at the rest | `limitations.md` §2, §3 |

**Gap 1 — a tag that was asserted rather than checkable. Closed 2026-09-08
(issue #252).** `envelope_layer` took `Limits` and nothing else. That was sound
while the only taint could arrive through the bounds; since issue #163 the outer
set reads `state.base_vel`, and since issue #156 a `BaseVelocity` may be
`DERIVED`. The stream recorded `base_vel_source`, so the dependency was *in the
file* — but the `HAS_ENVELOPE` edge was tagged from `Limits.source` alone, and
the two could disagree with nothing to say so. Now `envelope_layer` takes all
three inputs and returns the weakest, every tagged edge carries what its tag was
computed from, and `open_edge` refuses an edge whose tag and basis disagree. §8
tier 4 is what it cost.

**Gap 2 — recomputation with no stated environment.** The retention argument is
that a polygon may be discarded because it is a deterministic function of the row
and four numbers in `meta`. Issue #175 measured that the function is the
platform's: tables captured on one architecture differ in their last bits on
another. So an auditor who recomputes and disagrees cannot distinguish *wrong
machine* from *the geometry moved* — and those are opposite findings.

*Closed in the weaker form, 2026-09-05 (issues #200 and #201).* `meta` carries
the six keys §3's first row asks for — `reg.store.ENVIRONMENT_KEYS`, read off the
running interpreter and read back by `reg.graph.recorded_environment` — with
`SCHEMA_VERSION` at 11 and its note beside the others. **And the reader now acts
on them.** `reg.graph.envelope_at` refuses to recompute a discarded polygon off
the recording environment, comparing `reg.graph.RECOMPUTE_ENVIRONMENT_KEYS` —
five of the six, the sixth being `reg.graph.RECORDED_ONLY_ENVIRONMENT_KEYS` — and
naming the key that differs and both values. It **refuses
rather than warning**, because a recomputed polygon that reaches a caller under a
warning is a polygon that reaches a query result. Three states and the third
never resolves to the first: the keys agree and the recomputation happens exactly
as before; one differs and it is a could-not-evaluate; the artifact states no
environment — everything built before #200 — and it is a *different*
could-not-evaluate, because nothing was compared.

**What is not closed, and the sentence is load-bearing.** The refusal names the
key and does not say which difference moved the geometry; nothing in that path
compares any geometry. This is the **weaker half of attribution** — an
unresolvable disagreement becomes a stated one — and `diffoscope` is what the
other half looks like ([`prior-art.md`](prior-art.md) §27). The interpreter and
numpy are recorded and are not triggers, which is a decision taken in issue
#201's grooming: a patch release would make every artifact unrecomputable on any
machine that has been updated, and a check that fires on the expected shape of
the world is a check that gets switched off. numpy is the weaker call of the two
and is stated rather than left to be discovered, because `numpy.cos` and
`numpy.sin` place every link endpoint.

The split into two issues was deliberate: writing the data and using it are
different work, and only the second changes what a query answers.

**Gap 3 — a radius where the question wants a region. Narrowed 2026-09-09
(issue #257).** A stored envelope row answered *not at that distance* and could
not answer *not at that point*, because the boundary was not there to test
against. `outer_wkb` is now retained under `GEOMETRY_RETENTION`'s own rule —
option C of §8's tier 5 — so the rows that keep the sampled polygon carry the
outer region too and answer pointwise. On the rest the answer is still radial
and the region is still recomputable, which routes that remainder back through
gap 2; and what caps it is `ENVELOPE_RETENTION` rather than this gap, which is
why retaining a boundary everywhere buys 84 frames of 3,000 rather than 12.

## 2. The test that decides all three

**The cold read.** Open an artifact with the code that reads artifacts and **no
document**. For every claim the file makes, either it can be checked from the file
or it cannot.

*That sentence declares a reader.* "The code that reads artifacts and no
document" names what the reader already knows, which is the only thing that
terminates the recursion of what an artifact must carry — §6 item 4 and
[`prior-art.md`](prior-art.md) §29. The reader it names is §4's, and the test is
relative to that reader and to no other.

**Landed as `reg.query.cold_read`, and it is not a test.** It ships in the
package because the audience is an assessor holding a file, and a check they
cannot run tells them nothing; `python -m reg.query FILE --cold-read` prints it.
One row per claim the file makes about itself, in five states, per *a check must
be able to fail*:

| state | meaning |
|---|---|
| **checkable** | the file carries what is needed to verify the claim |
| **checkable with a key the file does not contain** | the record is there and the check on it is deliberately gated on a key |
| **readable, not checkable** | the claim is present and the file does not support verifying it |
| **absent** | the claim is not in this file |
| **could-not-evaluate** | the file was written against a schema these states were not derived against |

**The last three never resolve to the first.** Nor is the second a weaker form of
the first: a MAC verifiable with nothing but the file it sits in attests to
nobody, so the gate **is** the design, and a report flattening that row into
either neighbour would call a deliberate gate a shortcoming, or a shortcoming a
gate. It is the one claim here whose verification is withheld on purpose.

**It covers all four of [`plan.md`](plan.md)'s claims**, in six rows, on an
artifact built from `main` at `schema_version` 14 with a record stream stored.
Claim 4's two are **absent** on a build handed none — a fact about the build
rather than about the schema:

| claim | row | what the file supports |
|---|---|---|
| 4 | `chain-intact` | **checkable with a key it does not contain** — both chains are in the file, every record carries its link and its MAC, and `verify_chain(conn, keyring)` is what a key-holder runs |
| 4 | `passivation-acknowledged` | **checkable** — `acknowledgments(conn)` needs no key; a passivation nobody cleared is a could-not-evaluate, never a *no* |
| 3 | `layer-tag-basis` | **checkable** — gap 1, closed |
| 2 | `reached-point` | **readable, not checkable** — the boundary is in the file where an edge anchors one (gap 3, narrowed); no query tests a point against it |
| 1 | `recompute-discarded-polygon` | **checkable** — the discard contract retention rests on |
| — | `recording-environment` | **checkable** — what the row above rests on |

Claim 4's two rows are what the other four support. `tests/test_query.py` pins
every row per shipped fixture, so closing a gap fails there and has to be updated
on purpose.

**It reports and it re-verifies nothing.** `recompute_permitted` is held to agree
with `reg.graph.envelope_at` on both sides; the chain row runs *nothing*, having
no keyring, `reg.chain.verify_chain` being the one implementation of that walk.
The negatives ship with each — `env_*` keys stripped is *absent* and not
*checkable*, a file predating schema 11 is *could-not-evaluate* and not *absent*,
a file with no chain in it is *absent* and not the fifth state, and a record whose
MAC has been blanked is *readable, not checkable*, being unverifiable by anybody.

**It closes no gap.** It makes them legible from the file, which is what let
#228 be judged by more than a PR body.

## 3. What moves into the file

| addition | what it buys | cost |
|---|---|---|
| **Environment** in `meta`: shapely and GEOS versions, platform, Python — **landed, issue #200**, as six keys: those four, plus numpy, plus the platform's system and machine separately; **acted on, issue #201**, by `envelope_at` over four of them | Gap 2, in the weaker form below. A recomputation that disagrees becomes a could-not-evaluate rather than an unresolvable one — and off the recording environment it is refused before it can disagree | six rows; schema bump to 11; **no published figure moved**; a recompute off the recording environment stops returning a polygon |
| **Layer basis** per tagged edge: the inputs the tag was computed from, each with its provenance | Gap 1, and the tag becomes checkable rather than trusted | a row per input per tagged edge |
| **The outer boundary**, retained rather than projected — **landed, issue #257**, where the sampled polygon already is | Gap 3, at the frames an edge anchors | +0.61% and +0.42% of the two finer figures; schema bump to 14 |

The first is small and unblocks the honesty of the other two. The third was the
expensive one and was taken as a decision rather than a task — see §8.

**What the sixth prior-art pass changed about the first row** ([`prior-art.md`](prior-art.md)
§27, §28):

- **The content is adopted, not derived.** An environment record is a
  **buildinfo** — the Reproducible Builds project's name for it — and that project
  is the precedent, not SLSA. The list to carry is *the dependencies and their
  versions, the configuration and the environment variables the computation
  actually uses*, minimised rather than enumerated; §6 item 3 is C2PA's
  shipped form of the same idea.

  *What the minimise rule settled when it was applied* (issue #200). Two keys
  arrived that the row above did not name — **numpy**, because `np.cos` and
  `np.sin` place every link endpoint in `reg.kinematics`, and the platform's
  **system** and **machine** as separate keys rather than one platform string,
  because that is the pair issue #175 measured a divergence across. Everything
  that would not change the geometry stayed out: no hostname, no build path, no
  user, no locale, no timezone. **One thing that would change it is out too, and
  it is stated rather than quietly dropped** — the C library, because
  `platform.libc_ver()` reports nothing on macOS and under musl, so a key for it
  would be empty on some platforms and would mean both *could not tell* and *no
  glibc here*. Two artifacts can therefore agree on all six keys and have been
  linked against different libms: matching environments are necessary for a
  bit-identical recomputation and not sufficient.
- **Putting it in `meta` is a deviation from that practice, and is stated as
  one.** A buildinfo is deliberately *a separate product beside the artifact*,
  because an archive can distribute it to whoever wants to rebuild. Claim 2 says
  this file answers with no access to anything else, which is a stronger
  requirement than the practice has, so the record goes inside. That reason is the
  deviation's whole justification and it belongs wherever the schema is specified
  — the pattern is [`prior-art.md`](prior-art.md) §5's PROFIsafe deviation. It is
  now stated there: `reg.store.ENVIRONMENT_KEYS`, where the keys are specified,
  and [`lossiness.md`](lossiness.md) *Discarded* #9, where the retention argument
  the record qualifies lives. **What the departure costs**, said in the same
  breath as its reason: the environment cannot be handed to a rebuilder without
  handing over the artifact, and it is descriptive `meta` — nothing in the chain
  signs it, so a party who can rewrite the file can rewrite its environment too.
  §7 question 3 is where that second half is still a person's decision.
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
a reader who has been. OAIS calls the material **Representation Information**, and
terminates its recursion in exactly one place: a **declared Designated Community**
and what it already knows (§6 item 4).

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

Issue #170 diagnosed the corpus correctly, and its method — a normative core,
rationale below a line — is right; this document is written in that shape.

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

1. **§26 corrected this document.** That literature gives the **statement
   shape** — a signed predicate about a subject digest — and *not* an environment
   record: SLSA identifies the build platform and requires the verifier to trust
   it, and it declines to require reproducible builds at any level.
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

*It was six rows, and the estimate held* (issue #200). The measurement is in the
PR: `python -m reg.bench --resolution --seed 0` and the four-rung control-rate
ladder both produce reports identical in every measured number, before and after,
because six short strings in one `meta` row each land inside pages the file was
already paying for. That is the smallest a change to the artifact has come out
at, and it is the reason this tier went first rather than an argument that it
should have.

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

**Tier 2 — the environment in `meta`. Landed, in two halves.** The recording
(issue #200): six keys written by `reg.store.build_environment` from the running
interpreter, read back by `reg.graph.recorded_environment`, `SCHEMA_VERSION` at 11
with its note, and no published figure moved. The acting (issue #201):
`reg.graph.envelope_at` refuses to recompute a discarded polygon off the recording
environment. §1's gap 2 is which keys that refusal compares and what each half
bought. The split was on the seam this build order is cut along — writing the data
and using it are different work, and only the second changes what a query answers.
Tier 3 was unblocked by the first half; nothing else here was waiting on either.

**Tier 3 — the cold read. Landed** (issue #231) **and extended to Claim 4** (issue
#242): `reg.query.cold_read` and `--cold-read`, six claims in five states, pinned
per shipped fixture in `tests/test_query.py` with its negatives. The fifth state
is `chain-intact`'s, and §2 says why it is a state and not a shade of one of the
four. It ships in the package rather than in `tests/`, and §2 says why.

**Tier 4 — the layer basis. Landed** (issue #252). **Option A, per edge**, is in
the schema as `reg.store.EDGE_BASIS_TABLE` at `SCHEMA_VERSION` 13: one row per
input per tagged edge, each naming the input, the value it had in this build,
where it was read and the layer that input alone admits. `reg.store.open_edge`
writes it and refuses an edge whose tag disagrees with it, `reg.envelope.
envelope_layer` became the **weakest of its inputs** rather than of one of them,
and `reg.query.cold_read` reports `layer-tag-basis` as `CHECKABLE`. §7 question 1
is answered by the measurement below and question 2's `DERIVED` fixture
(`reg.scenarios.mobile_derived_velocity`, issue #229) is what exercises it.
**Every published retention figure moved** — [`retention.md`](retention.md) is
the re-measurement, and it is the price of the tier.

*Its own tier 2, the costing, landed first* (issue #249): `reg.bench
--layer-basis` priced both granularities and adopted neither. Measured with
`python -m reg.bench --layer-basis --seed 0` on the fixture Claim 1 is priced
on, `long_run` at 3,000 frames. **The table below is that measurement as it was
reported, against the figures published then** — the artifact has since grown by
what option A costs, so re-running the study today prices the same question
against a larger baseline, and republishing these cells would describe neither
run.

| level | option | artifact | vs today | basis rows | answers | 6 months | vs sensor |
|---|---|---|---|---|---|---|---|
| `occurrence` | today | 1,008,640 B | — | 0 | 0 of 0 | 265 GB | ~689x |
| `occurrence` | A and B alike | 1,011,712 B | +0.30% | 0 | 0 of 0 | 266 GB | ~687x |
| `transition` | today | 2,503,680 B | — | 0 | 0 of 9,724 | 658 GB | ~277x |
| `transition` | A | 3,158,016 B | +26.13% | 9,892 | 9,724 of 9,724 | 830 GB | ~220x |
| `transition` | B | 2,525,184 B | +0.86% | 252 | 84 of 9,724 | 664 GB | ~275x |
| `per-frame` | today | 3,634,176 B | — | 0 | 0 of 18,428 | 955 GB | ~191x |
| `per-frame` | A | 4,857,856 B | +33.67% | 18,596 | 18,428 of 18,428 | 1,277 GB | ~143x |
| `per-frame` | B | 3,655,680 B | +0.59% | 252 | 84 of 18,428 | 961 GB | ~190x |

**The headline figures move here; under tier 5's options they did not.** A
granularity adds a table rather than a column, and an empty table with its key
costs SQLite pages at every level — so `265 GB` became 266 GB and `~689x`
became ~687x even where no basis row is written. The totals and multiples are
the published figures scaled by the measured ratio; the sensor side of the last
column is a projection wherever it is quoted
([`sensor-baseline.md`](sensor-baseline.md)).

**B is cheaper by covering less, not by sharing.** It answers 84 of the
transition level's 9,724 tagged edges — 0.86% — because the basis hangs on an
envelope and most tagged edges name none: a `SEPARATION`, an `ADJUDICATED` or a
`FOLLOWS` edge has no envelope endpoint, and an `INTERSECTS` or
`DECLARED` edge has one whose basis did not decide its tag. The sharing B is
cheaper *by* measures **1.00**: `ENVELOPE_RETENTION` has already reduced the
envelope rows to the ones an edge anchors, so there is no set of edges to
amortise a reference over. Per edge answered, B costs 256 B against A's 67 —
3.8x, the opposite direction from its byte column.

**Question 1's second half: B cannot express it.** Two `HAS_ENVELOPE` edges
over one envelope row whose bases differ get one
basis between them, because envelope rows are deduplicated on `(envelope_hash,
source, horizon)` while the pose taint is read off the *edge's own endpoint*.
`tests/test_bench.py` feeds the study that case and asserts it reports the
second edge misstated.

**Neither option closed gap 1 on its own, and what took the third decision.**
`base_vel_source` was an input no table retained, so both priced it as *not
retained*: the builder had to record the value too, which is a change to what is
retained rather than to where. Issue #252 took that decision with the
granularity, because a basis whose rows a reader cannot check the tag against is
not a basis. The value is on the basis row itself, so a run whose base rates came
out of a perceiver and one whose came off its wheels produce different bases, and
the tag follows.

**Tier 5 — the boundary** (issue #228). A decision first, then bytes, then a
re-measurement and republish of every figure that moves. Not to be started until
tiers 2 and 3 make the argument for it concrete.

*Its own tier 1, the costing, has landed* (issue #230): `reg.bench
--outer-boundary` prices all three options and adopts none. Measured with
`python -m reg.bench --outer-boundary --seed 0` on the fixture Claim 1 is priced
on, `long_run` at 3,000 frames. Nothing was retained and no figure republished.

| level | option | artifact | vs A | 6 months | vs sensor |
|---|---|---|---|---|---|
| `occurrence` | A, B and C alike | 1,008,640 B | +0.00% | 265 GB | ~689x |
| `transition` | A | 2,503,680 B | — | 658 GB | ~277x |
| `transition` | B | 2,616,320 B | +4.50% | 688 GB | ~265x |
| `transition` | C | 2,519,040 B | +0.61% | 662 GB | ~275x |
| `per-frame` | A | 3,634,176 B | — | 955 GB | ~191x |
| `per-frame` | B | 3,746,816 B | +3.10% | 985 GB | ~185x |
| `per-frame` | C | 3,649,536 B | +0.42% | 959 GB | ~190x |

**The headline figures do not move at all.** `265 GB` and `~689x` were figures at
occurrence resolution, and that level retains no envelope row, so no rule for the
outer boundary reaches it. The totals and multiples above are the published
figures scaled by the measured ratio; the sensor side of the last column is a
projection wherever it is quoted ([`sensor-baseline.md`](sensor-baseline.md)).

The build retains 86 envelope rows and 14 of them keep an inner polygon. Option B
writes 84 boundaries — every `computed` envelope; the other two rows are a
declared and a clamped region, which are not reachable sets and have no outer set
to retain. Option C writes 12. So C is 14% of B's rows for 14% of its bytes:
15,360 B against 112,640 B at the transition level.

**What either option buys is capped by a rule this decision does not touch.**
Under B the pointwise question is answerable at 84 of the run's 3,000 frames,
under C at 12, under A at none. `ENVELOPE_RETENTION` decides which frames get an
envelope row at all, and it has already put that ceiling at 2.8% — so retaining a
boundary *everywhere* does not make the artifact answer *everywhere*. It makes it
answer at 84 frames rather than 12, for 7.3x the bytes. Whether that is worth
4.50% of the transition figure is #228's to decide, and this tier does not.

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
