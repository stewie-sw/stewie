# Barrier 1 independent scientific-method re-review — `cb9532b2`

- **Reviewed commit:** `cb9532b21e989c8b7380a030f1a8854721da309e`
- **Review role:** independent scientific and experimental-method reviewer
- **Review mode:** read-only isolated archive
- **Archive SHA-256:** `c6d5a9374d6953f2e32233a35f40bf987c63f38a02d2f8cc02c5ce90836c0196`
- **Verdict:** **BLOCK**

The remediation materially improves scientific honesty but does not make Barrier 1
acceptance-ready. The machine gate agrees: the packet is structurally valid,
`acceptance_ready=false`, and the acceptance-required form exits `2`.

## Resolved or materially improved

- The development-exposed allocation is explicitly retired, execution-disabled, ineligible for
  confirmatory results, and forbidden from confirmatory reuse.
- The independent unit is now the terrain window. Action, seed, system, and perturbation are repeated
  measures. The executable bootstrap reports eight units, not 24 action rows.
- Evaluation and perturbation outputs state that their arrays and seeds are exposed exploratory
  diagnostics.
- `CandidateScenario` and candidate output no longer expose the executed action outcome or reference
  identity. A reference-only poison probe leaves candidate state and summary hashes unchanged.
- Non-finite candidate states are unavailable/invalid, rather than silently available.
- Registry implementation, adapter, hash, same-input, and external-selection gaps are disclosed.

## Open critical defects

1. No replacement evaluator-controlled allocation, materialized/hash-bound terrain/action package,
   spatial proof, disjoint pilot, power analysis, calibrated MDE, or sample-size freeze exists.
2. Reference and dependency firewalls remain specifications. Candidate/evaluator images,
   permissions, canonical output freeze, and non-vacuous poison attestations are absent; execution
   remains in one Python process.
3. The 21 registered systems and four H7 cells are not bound to executable implementations,
   configurations, or same-input attestations. Several internal methods remain duplicate or
   confounded, and no credible external comparator ran.
4. No manifest-driven confirmatory executor or contract-bound metric scorer enforces
   `execution_allowed`, reviewed identity, allocation hashes, multiplicity, availability guards, or
   stopping rules.
5. The conservative novelty boundary still lacks independent acceptance and establishes no novel
   contribution.

## Residual method limitations

- Four pairs among the eight synthetic development envelopes overlap.
- The corrected terrain-window resampling does not turn those fixtures into a research allocation.
- Runtime scoring remains a development proxy rather than the registered planner/query-lens,
  stale-overwrite, multiplicity, and availability decision procedure.
- STEWIE and every named ablation have `0/192` harmful-plan flags. `no_dependency` differs from
  STEWIE only at floating-point roundoff; only intentionally weak overwrite methods show harm.

## H1–H7 disposition

All definitions remain provisionally falsifiable. All effect claims remain blocked:

- H1 lacks registered B-VERSION/B-BITEMP execution and the temporal-oracle experiment.
- H2 lacks an executable independent dependency oracle and a measurable mechanism effect.
- H3 has local structural tests only, without the joint fault/model-bias grid or firewall attestation.
- H4 retains a confounded provenance comparator and lacks explanation/replay endpoints.
- H5 uses a synthetic threshold proxy rather than the registered planner experiment.
- H6 has only partial host-local microbenchmarks.
- H7 has no executable P0D0/P1D0/P0D1/P1D1 factorial.

## Verification

```text
scripts/validate_ultrabuild.py
  PASS

scripts/validate_ultrabuild_contracts.py
  PASS

scripts/validate_ultrabuild_requirements.py
  PASS — 51 requirements, 11 test-cited, 40 pending

experiments/contracts/validate_barrier1_contracts.py
  PASS structurally — acceptance_ready=false

experiments/contracts/validate_barrier1_contracts.py --require-acceptance-ready
  EXPECTED BLOCK — exit 2

focused pytest
  PASS — 36 passed, 1 opt-in wheel test skipped

focused Ruff
  PASS
```

## Claim boundary

Supported: explicit allocation retirement, terrain-window accounting, deterministic exploratory
behavior, candidate API non-exposure, and structural prototype tests.

Unsupported: any H1–H7 effect, baseline superiority, ablation attribution, real Haworth performance,
generality, physical fidelity, operational safety, mission readiness, or executable evaluator
isolation.

The controlled harness is unequivocally exploratory only.
