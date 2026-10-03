# Tamper-evidence hardening — threat model and schema design

**Status:** design for epic #313 · written 2026-10-03 · normative for #315–#318

Two documented gaps, one epic: the artifact has no external witness (a whole
history can be re-run and re-signed offline, undetectably), and its MAC keys are
static (the one deliberate deviation from Schneier–Kelsey '98). This doc decides
what each fix defeats, how epochs and anchors are shaped, and where the new
records live — and wins where #315–#318 disagree.

## 1. Threat model — three attackers, three answers

| Attacker | What they do | What defeats it |
|---|---|---|
| Key compromise | steals the enforcement MAC key at time *b*, rewrites verdicts from before *b* | the forward-secure ratchet (#315): keys evolve per epoch and predecessors are erased |
| Re-issuer | re-runs the whole history offline under fresh keys, backdates it | external anchoring (#316, #317): a third party witnessed the epoch head at a real instant |
| Tail trimmer | deletes the newest records — no link breaks | anchoring: the anchored head commits to history the trimmer cannot reproduce. The ratchet alone does **not** defeat this. |

The verifier-holds-the-keys asymmetry (`limitations.md` §7) survives this epic by
design: offline verification still needs the keyring. What changes is what a
stolen key buys — with the ratchet, nothing before the compromise; with
anchoring, nothing that predates the last anchor.

## 2. Epochs

- An epoch is a run of records, not a wall-clock window: it closes every **1,024
  records** and at artifact close. Deterministic and replayable.
- Key evolution is per-epoch: `k_{i+1} = SHA-256(k_i)`, the predecessor erased
  immediately — the half of Schneier–Kelsey '98 that `reg/chain.py` omitted.
- Each epoch closes with a Merkle root over its records' canonical hashes. The
  **epoch head** is `SHA-256(prev_epoch_head || merkle_root || checkpoint_sig)`,
  where `checkpoint_sig` is an Ed25519 signature over the epoch's key-commitment,
  made with a long-lived checkpoint key that never signs records.
- The genesis epoch's `prev_epoch_head` is 32 zero bytes, stated in the artifact.

## 3. Anchor adapters

One seam, three classes, all `(ChainHeads) -> Commitment` — the interface
`reg/commit.py` already ships, whose docstring names exactly this extension
point:

- `WitnessCommitter` (existing): the on-site witness, unchanged.
- `Rfc3161Committer` (#316): requests a timestamp token over the epoch head;
  scheme `rfc3161-sha256-v1`.
- `RekorV2Committer` (#317): submits the epoch head as an in-toto v1 statement
  in a DSSE envelope; scheme `rekor-v2-inclusion-v1`.

Anchoring happens **at artifact close**, once per epoch head, and adapters
compose: an artifact may carry witness + TSA + Rekor commitments, each
independently verifiable. `verify_commitment` gains no new outcomes — the three
states already cover an unknown scheme as COULD-NOT-EVALUATE.

## 4. Schema deltas

- `meta['chain_format']`: `chain-sha256-v1` → `chain-sha256-v2`. v1 artifacts
  verify unchanged under the old walk.
- `meta['epoch_records']`: records per epoch (1,024); the walk reads epoch
  boundaries here, not from a constant.
- `epoch_heads(chain TEXT, epoch INTEGER, head BLOB, merkle_root BLOB,
  checkpoint_sig BLOB, key_id TEXT, PRIMARY KEY (chain, epoch))` — per chain,
  one key schedule each.
- New table `anchor_receipts(epoch INTEGER, scheme TEXT, receipt BLOB,
  PRIMARY KEY (epoch, scheme))`: TSA tokens as DER bytes, Rekor inclusion proofs
  as canonical JSON.
- Only 32-byte heads leave the operator boundary — no payload, no personal
  data.

## 5. Offline verifiability

Everything a verifier needs years later is in the artifact: the TSA token with
its full certificate chain, the Rekor inclusion proof with the checkpoint key id.
No network call, no live service, ever — the artifact must verify years later
with no service still running, so anchoring is a close-time operation and
verification is file I/O plus crypto. An artifact closed with no anchor records
`commitment: none`, as today.

## 6. Dependency picks (osv-checked 2026-10-03)

| Package | Version | For | OSV result |
|---|---|---|---|
| `rfc3161-client` | 1.0.9 | TSA requests (#316) | no known vulnerabilities |
| `sigstore` | 4.5.0 | Rekor v2 submission (#317) | no known vulnerabilities |
| `cryptography` | 50.0.2 | transitive (both) | no known vulnerabilities |

Re-check at pin time in #316/#317; a version with known vulnerabilities is not
pinned.

## 7. Long-term verification

- **TSA certificates expire.** Store the full chain with each token; verify
  against the chain as of the token's instant. If the chain is gone the token
  degrades to COULD-NOT-EVALUATE, never to VALID-by-assertion.
- **Rekor shards rotate** (~6 months). Pin the inactive shard's keys from the
  TUF TrustedRoot at anchor time and store the key ids with the proof; a verifier
  that cannot resolve a shard key reports COULD-NOT-EVALUATE.

## 8. Docs-affected checklist (for the #315–#318 consistency sweeps)

- `docs/prior-art.md` §14 (Schneier–Kelsey: the omitted half is now
  implemented), §18 (transparency logs: an adapter, no longer a pointer)
- `docs/limitations.md` §6 (witness vs third-party timestamp), §7 (no forward
  security)
- `README.md` honesty note and the four-claims table (Claim 4)
- `docs/plan.md` wherever it touches the chain or the commitment interface
- `docs/lossiness.md` *Unanswerable* (a Rekor-anchored artifact makes a withheld
  artifact detectable — that entry moves)

## 9. Length accounting for this epic

Pre-epic CODE_COUPLED baseline: **13,961 words** (RATE 42.4, measured
2026-10-02). This doc and its index row add words now; #318's net-zero rule
requires the epic to land back at or under 13,961 — #315–#317 pay for their
prose with cuts.
