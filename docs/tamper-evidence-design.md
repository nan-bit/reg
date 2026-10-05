# Tamper-evidence hardening — threat model and schema design

**Status:** as-built record for epic #313 · condensed 2026-10-04 after #315–#318
landed · the implementation and [`docs/limitations.md`](limitations.md) §§6–7
are the authority

Two gaps, one epic: no external witness — a history re-run and re-signed
offline — and static MAC keys, the deliberate deviation from Schneier–Kelsey
'98.

| Attacker | What defeats it |
|---|---|
| Key compromise — steals the MAC key, rewrites earlier verdicts | the ratchet (#315): per-epoch keys, predecessors erased |
| Re-issuer — re-runs history offline under fresh keys, backdates it | anchoring (#316, #317): a third party witnessed the epoch head |
| Tail trimmer — deletes the newest records | the anchored head commits to history the trimmer cannot reproduce |

Per epoch (#315–#318): the ratchet (`k_{i+1} = SHA-256(k_i)` every 1,024
records, predecessors erased; Merkle root and Ed25519 checkpoint per head;
format v2, v1 still verifies), RFC 3161 timestamps and Rekor v2 in-toto
statements per head, and a query surface (`reg.query.anchor_status`, the
cold read, `incident_report`) reporting per-epoch findings.

What remains, per [`docs/limitations.md`](limitations.md) §§6–7: anchoring is
opt-in at close, the verifier holds the keys, and trust gaps degrade to
COULD-NOT-EVALUATE, never VALID-by-assertion.
