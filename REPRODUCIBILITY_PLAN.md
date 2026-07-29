# Reproducibility plan

**Artifact ID:** `ART-REPRODUCIBILITY`
**Producer node:** `ORCH-001`
**Consumers:** `VERT-010`, `EXP-020`, `PERF-010`, `INT-010`, `DISS-010`
**Status:** specified; no frozen UltraBuild experiment release exists yet.

## Frozen identity

Every reported result names:

- Git commit and dirty-state status;
- scenario and input content hashes;
- schema/policy/algorithm versions;
- exact environment lock and container image digest where used;
- hardware/OS/runtime manifest;
- configuration digest and deterministic seed;
- graph node and experiment IDs;
- exact command and exit status; and
- hashes of raw per-trial and aggregate outputs.

The clean restart baseline is
`d1056d9deff4e540557b13c8cb78fc799330410e` on
`ultrabuild/graph-orchestration-2026-07-28`.

## Environment construction

CPU reference environment:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/pip install --require-hashes -r requirements-dev.lock
.venv/bin/pip install -e . --no-deps
.venv/bin/pip install -e packages/stewie-bodies --no-deps
.venv/bin/pip install -e packages/stewie-forge --no-deps
```

The published reproduction path will use either the exact lock plus OS manifest or a digest-pinned
container. GPU/Godot/ROS/Chrono tiers are separate profiles with visible skip/failure status.

## Repository gates

```bash
.venv/bin/python scripts/validate_ultrabuild.py
.venv/bin/python scripts/validate_ultrabuild_requirements.py
.venv/bin/python scripts/req_trace.py
.venv/bin/ruff check --select F stewie dart lode leap forge scripts viz
.venv/bin/mypy
.venv/bin/pytest stewie/twin -p no:cacheprovider
.venv/bin/pytest
```

Browser, frontend, package, and gated-tier commands remain those named in `.github/workflows/ci.yml`.
The first UltraBuild evidence release will capture stdout/stderr and a machine-readable result for
each required gate.

`jsonschema` 4.x and the RFC-3339 format checker are development-only validation dependencies. Their
purpose is Draft-2020-12 meta-schema, payload, and timestamp validation; both are MIT-licensed. They
add no mission/runtime import, network call, or payload execution. Versions and hashes are frozen in
`requirements-dev.lock`; schema validation cost is measured only as development/ingest overhead and
must not be omitted to improve reported runtime latency.

## Scenario packaging

Each scenario directory contains:

- `scenario.json` conforming to `schemas/ultrabuild/scenario.schema.json`, including terrain hash/CRS,
  robots, separately mounted candidate-action and withheld-execution manifests, typed evidence
  references/delays, perturbation generators and oracle-independence flags, independent units, seeds,
  endpoints, statistics, harm tolerance, and reference-firewall protocol;
- referenced evidence/action/provenance records carry clocks, coverage-mask hashes, source lineage,
  and payload hashes under their own typed schemas rather than as undeclared scenario fields;
- immutable payloads or fetch manifests with checksums;
- `systems.yaml`, `seeds.txt`, and preregistered comparison/ablation plan;
- per-trial JSONL emitted before aggregation;
- aggregate CSV/Parquet and statistical report;
- reference-leakage attestation;
- command/environment manifest; and
- reviewer decision.

Scenario IDs are hashes of canonical scenario content. Changing a parameter creates a new ID.

## Determinism

- Seed Python/NumPy and every simulator/model source that exposes a seed.
- Pin thread-pool settings and record worker count.
- Sort unordered evidence by stable identity where semantics require order invariance.
- Compare byte hashes where deterministic serialization is promised.
- Otherwise declare numeric tolerances and report observed cross-platform variation.
- Retain failure and negative-result artifacts, not only successful runs.

## Reference firewall

Candidate generation runs and freezes before the evaluator mounts/opens the reference. A poison test
changes only the reference and requires identical candidates/decisions. Any violation invalidates the
run family.

## Independent replication

An independent reviewer receives only the frozen package and commands. Barrier 7 requires successful
reproduction of the headline tables/figures on a clean worktree. Score 5 in the quality rubric
requires external or separately controlled replication.

## Retention

Metadata, manifests, source, small trial records, and statistical outputs are version-controlled when
appropriate. Large payloads are content-addressed with durable locations and checksums. Every report
must remain interpretable if an optional large payload becomes unavailable; missing data is an
explicit reproduction failure, never silently regenerated from different inputs.
