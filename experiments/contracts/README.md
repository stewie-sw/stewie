# Barrier-1 closure packet

This directory contains additive, machine-checkable research-design contracts. It contains no
comparative result and does not advance a graph lifecycle state by itself.

## Evidence labels

- `specified`: a contract, formula, or decision rule is exact enough for validation.
- `provisional`: an exact design value is reserved but has not been calibrated or independently
  accepted.
- `pending`: an implementation, payload, content hash, runtime attestation, or review does not yet
  exist.
- `synthetic_oracle_fixture_not_empirical_result`: hand-constructed input with a known answer used only
  to test metric code.

No artifact in this packet is labelled experimentally validated.

## Contents

- `../../BASELINE_REGISTRY.yaml`: normalized systems, owners, versions, configurations, licenses,
  adapters, input-equivalence rules, and compute caps.
- `../../research/hypothesis_contracts.yaml`: exact H1-H7 domains, comparisons, endpoints, estimands,
  provisional MDEs/bounds, availability guards, and falsification rules.
- `pilot_allocation.yaml`: a provisional reserved unit/window/seed assignment. Geometry and source
  hashes remain pending.
- `evaluation_allocation.yaml`: the original disjoint evaluation assignment, now irreversibly
  retired because its seeds and synthetic window design were exposed to the development harness. It
  is retained as an audit artifact and must never be used as confirmatory evidence.
- `metric_oracles/*.json`: synthetic golden fixtures for temporal, reconciliation, provenance,
  decision, and interaction formulas.
- `dependency_oracle_negative_controls.yaml`: independent 2x2 overlap/correlation identification
  design.
- `reference_firewall.yaml`: candidate/evaluator projection, identity, mount, freeze, permission, and
  poison-test contract.
- `validate_barrier1_contracts.py`: packet and cross-artifact validator.
- `test_barrier1_contracts.py`: focused positive and mutation tests.

## Commands

```bash
.venv/bin/python experiments/contracts/validate_barrier1_contracts.py
.venv/bin/pytest -q -p no:cacheprovider experiments/contracts/test_barrier1_contracts.py
```

The first command exits zero when the *design packet* is internally coherent and prints
`"acceptance_ready": false` while calibration and evidence are pending. To use it as a future barrier
gate:

```bash
.venv/bin/python experiments/contracts/validate_barrier1_contracts.py \
  --require-acceptance-ready
```

That command intentionally exits nonzero in the current packet.

## Required evidence before acceptance

1. Materialize and hash terrain windows, action geometries, system implementations, and configurations.
2. Replace the retired evaluation allocation under evaluator control, prove pilot/evaluation spatial
   disjointness, and run only the pilot allocation before that replacement is frozen.
3. Replace provisional MDEs, bounds, margins, and sample size with the independently reviewed pilot
   decision; retain the earlier values in history.
4. Execute baseline same-input attestations, dependency-oracle poison tests, and reference-firewall
   permission/poison tests.
5. Freeze the evaluation packet at a commit and obtain an independent typed Barrier-1 decision that
   targets that commit.
