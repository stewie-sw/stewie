# Reproducibility package

**Artifact ID:** `ART-REPRODUCIBILITY-PACKAGE`
**Producer node:** `EXP-030`
**Consumers:** `REV-010`, `DISS-010`
**Evidence source:** `608c6881e9be5754ac801a7833ee1f8217c238a0`
**Status:** `source_clean_evidence_generated`

Install the locked development environment as described in `REPRODUCIBILITY_PLAN.md`, then run:

```bash
.venv/bin/python scripts/validate_ultrabuild.py
.venv/bin/python scripts/validate_ultrabuild_requirements.py
.venv/bin/python experiments/contracts/validate_barrier1_contracts.py
.venv/bin/pytest -ra -p no:cacheprovider \
  stewie/ultrabuild experiments/contracts scripts/test_ultrabuild_artifacts.py
STEWIE_WHEEL_SMOKE=1 .venv/bin/pytest -q -p no:cacheprovider \
  stewie/ultrabuild/test_package_integration_regressions.py
PYTHONNOUSERSITE=1 .venv/bin/pytest -n auto
.venv/bin/python -m stewie.ultrabuild.cli demo --output /tmp/stewie-demo
.venv/bin/python -m stewie.ultrabuild.cli multi-demo --output /tmp/stewie-multi
.venv/bin/python -m stewie.ultrabuild.cli conflict-demo --output /tmp/stewie-conflict
.venv/bin/python -m stewie.ultrabuild.cli evaluate --output /tmp/stewie-evaluation
.venv/bin/python -m stewie.ultrabuild.cli perturb --output /tmp/stewie-perturbation
.venv/bin/python -m stewie.ultrabuild.cli fault-inject --output /tmp/stewie-faults
.venv/bin/python -m stewie.ultrabuild.cli benchmark \
  --measured-runs 200 --output /tmp/stewie-performance
```

Retained evidence hashes:

| Artifact | SHA-256 |
|---|---|
| `evaluation/trials.jsonl` | `c7d618c7b3cdb220be598e3baa80c1d0a1256ab2a7ae1d5296f9a0db923ede3e` |
| `evaluation/evaluation_report.json` | `33b07b83337a7c4239081d8e85e22d36cce5f14f5ecd7dac9c8e641d4666d75f` |
| `perturbation/perturbation-report.json` | `a44d78651203336f5ca47f74fa7bbb966f3ee7f3268b62c94889147d3b4ce5d7` |
| `fault-injection/fault-injection-report.json` | `51b3b2929e210d7e20e190bab2b0c12d2c8b8d495f3f6a62c6fa5f2336e84d96` |
| `performance/performance-report.json` | `a0e72927357f28c47e645c87b57cc99405151d353e0333b722d5dcdf43a30d4d` |

Each machine report embeds the exact source commit, `code_commit_status: repository_discovered`,
`source_dirty: false`, package version, content hash, claim limit, and unsupported scope. The
synthetic evaluation and perturbation arrays are development-visible and may be reproduced only as
exploratory diagnostics, never as a confirmatory holdout.
