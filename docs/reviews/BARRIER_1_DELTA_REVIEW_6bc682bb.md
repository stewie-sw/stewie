# Barrier 1 scientific delta review — `6bc682bb`

- **Reviewed commit:** `6bc682bb7759490c8c47d7834159833df40a068f`
- **Parent:** `cb9532b21e989c8b7380a030f1a8854721da309e`
- **Archive SHA-256:** `9c12e28c144a4c538e2fe35f4ed131871cddeb9b249b4a154c44f7ef23fd01ec`
- **Review role:** independent scientific and experimental-method reviewer
- **Verdict:** **BLOCK**

The delta closes all three minor findings from the preceding scientific review:

- independent unit-seed pairs are `64`, not 192 action-row/seed combinations;
- documentation and test naming distinguish identifier/seed disjointness from unproved geometric
  disjointness; and
- perturbation CLI help calls the grid an exposed exploratory diagnostic.

`KNOWN_LIMITATIONS.md` also makes the generated 12×12 array boundary explicit.

Verification:

```text
Barrier-1 validator
  PASS structurally — valid=true, acceptance_ready=false

Barrier-1 validator --require-acceptance-ready
  EXPECTED BLOCK — exit 2

Barrier-1 contract plus experiment/perturbation tests
  PASS — 15 passed
```

The snapshot, lineage, provenance, and identity rework does not alter the evaluator, baseline
registry, hypotheses, pilot, firewall, dependency-oracle, or metric-execution path. The critical
blockers remain:

- no evaluator-controlled replacement for the retired allocation;
- no pilot calibration, power justification, frozen MDEs/bounds, materialized/hashes terrain and
  action assets, or spatial proof;
- no confirmatory-ready baseline/ablation implementation, configuration identity, external
  selection, or same-input attestation;
- no executable candidate/evaluator firewall, dependency oracle, permission/output-freeze/poison
  attestation, manifest-driven executor, or contract-bound scorer; and
- no H1–H7 confirmatory evidence or accepted novelty conclusion.

Barrier 1 remains blocked. Evaluation and perturbation remain exploratory diagnostics only.
