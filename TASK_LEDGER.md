# Task ledger

**Artifact ID:** `ART-TASK-LEDGER`
**Producer node:** `ORCH-001`
**Consumers:** all nodes and reviewers
**Status:** active append-only narrative ledger; lifecycle authority remains `GRAPH_MANIFEST.yaml`.

| Entry | Date | Node | Decision/action | Evidence/result | Next edge |
|---|---|---|---|---|---|
| TL-001 | 2026-07-28 | `ORCH-001` | Finished governance durability repair and merged it into Gate 3. | Repair `dab8a5ce`; merge `d1056d9d`; focused/lint/type/full suite passed before restart. | Freeze merged commit as baseline. |
| TL-002 | 2026-07-28 | `ORCH-001` | Preserved the user’s dirty `code/` checkout and removed obsolete temporary worktrees/branches only after ancestry checks. | Active branch and clean restart both point at `d1056d9d`; dirty paths did not overlap merge changes. | Work only in clean restart. |
| TL-003 | 2026-07-28 | `ORCH-001` | Created clean worktree `/mnt/projects/stewie/ultrabuild` on `ultrabuild/graph-orchestration-2026-07-28`. | Clean status at creation. | Begin prompt execution. |
| TL-004 | 2026-07-28 | `INV-001` | Rejected the 522-byte GDrive placeholder and older Claude paste as canonical prompt sources. | User-provided task-thread prompt selected as authority; normalized self-contained contract created. | Review execution contract. |
| TL-005 | 2026-07-28 | `ORCH-001` | Started independent read-only research, world-state, and platform inventories. | Three specialist review nodes dispatched against exact baseline. | Fan in to Barriers 1/2. |
| TL-006 | 2026-07-28 | `RES-010` | Selected state acceptance under agent-induced change as the candidate dissertation center. | Research review found two competing centers (hybrid learned perception and articulated navigation) and an offline but credible state-acceptance mechanism. | Novelty review and explicit claim boundary. |
| TL-007 | 2026-07-28 | `RES-010` | Recorded that existing research evidence is component-level. | Independent twin suite: 314 tests passed; integrated two-domain benchmark, frozen trials/statistics, and claim matrix absent. | Build Barrier-3 slice before broad claims. |
| TL-008 | 2026-07-28 | `ORCH-001` | Created all initial research/architecture artifact drafts and explicit risk/assumption/limitation registers. | Files named in the execution contract exist; schema/graph validation pending. | Independent review, manifest validation, targeted revisions. |
| TL-009 | 2026-07-28 | `INV-001` | Completed three independent tracked-baseline inventories and consolidated them. | Research: 314 twin tests passed; world-state: 185 focused tests plus 19 physics checks; platform: architecture/runtime/host inspection. Counts overlap and are not summed. | Review new artifacts against findings. |
| TL-010 | 2026-07-28 | `INV-001` | Added two critical implementation risks found by adversarial probes. | Cross-site world transaction linked the wrong twin; terrain summary chain did not commit spatial sparse payload. | Add Barrier-3 isolation/tamper acceptance tests. |
| TL-011 | 2026-07-28 | `ORCH-001` | Closed the initial artifact registry and machine-readable schema syntax checks. | 22/22 required files registered; graph/performance documents validate against JSON Schema; two artifact regression tests, Ruff, and focused mypy pass. | Independent Barrier-1/2 artifact review. |
| TL-012 | 2026-07-28 | `REV-010` | Completed independent research, world-state/database, and platform reviews; rejected Barrier 1 and Barrier 2 acceptance. | `FOUNDATION_REVIEW.md` records owned defects and explicit acceptance criteria; `RES-010` moved to `REWORK`. | Close defects without advancing barriers. |
| TL-013 | 2026-07-28 | `ARCH-020` | Reworked the Barrier-2 subset into typed branch, evidence, action, provenance, dependency, candidate, decision, conflict, hypothesis, revision, supersession, query, autonomy-decision, scenario, and barrier contracts. | Draft-2020-12 meta-validation plus positive/adversarial semantic fixtures now fail closed for the reviewed bypasses. | Implement record store/resolver only after Barrier-2 review. |
| TL-014 | 2026-07-28 | `ORCH-001` | Made graph, requirement, risk, and barrier controls executable. | All dependency arcs have typed producer-matching edges; runtime loops are explicit; requirements have owners/citations; open Critical risks block associated barriers; ACCEPT decisions bind reviewed commit, roles, nodes, findings, and evidence hashes. | Re-run independent control-surface review. |
| TL-015 | 2026-07-28 | `ARCH-030` | Added a distinct runtime operational graph. | `RUNTIME_GRAPH.yaml` declares input/output contracts, pre/postconditions, timeouts, retries, isolation, evidence, mutations, fan-in, and bounded loop policy; validator checks endpoint/contract/DAG closure. | Implement only the accepted minimal vertical slice. |
| TL-016 | 2026-07-28 | `RES-020` | Materialized the first adversarial nearest-work matrix. | `NOVELTY_REVIEW.md` classifies established overlap, unsupported candidate contributions, and strong baseline obligations from primary sources. | Complete the named search gaps and obtain independent novelty review. |
| TL-017 | 2026-07-28 | `REV-010` | Ran a final platform/database contract review and retained the Barrier-2 block. | `FND-025`–`FND-032` record transaction-time, write-boundary, promotion-binding, provenance-closure, and golden-graph gaps; validator crash and oracle-visibility seam were corrected. | Freeze only as an explicitly blocked foundation draft. |
| TL-018 | 2026-07-28 | `ORCH-001` | Reconstructed the foundation environment from the universal hash lock. | A new ignored `.venv` installed all 61 locked packages plus the root and two workspace packages without dependency resolution. | Run the declared foundation and focused regression gates. |
| TL-019 | 2026-07-28 | `ORCH-001` | Added and hash-locked minimal JSON Schema validation tooling. | `pyproject.toml` and `requirements-dev.lock` include `jsonschema` plus RFC-3339 support; strict smoke reports 61 fully hash-pinned packages and zero drift across 60 applicable pins. | Preserve the universal lock and repeat on CI-supported Python versions. |
| TL-020 | 2026-07-28 | `ORCH-001` | Ran the clean foundation verification packet. | UltraBuild validator, five artifact tests, Ruff, focused mypy, dependency-lock audit, strict install smoke, and 314 twin regressions passed; requirement trace remains honest at 413 total/320 cited with 20 V!=D audit rows. | Commit the blocked foundation draft without accepting a barrier. |
| TL-021 | 2026-07-29 | `VERT-010` | Implemented the first UltraBuild authority-boundary prototype without advancing a barrier. | `stewie/ultrabuild/` now contains a SQLite WAL/FULL append gateway, store-owned sequence/time/hash completion, exact idempotency, atomic promotion CAS, rebuildable branch heads, payload CAS, integrity verification, cold snapshot, and golden query/plan/action graph. | Independent database, functional, and provenance review. |
| TL-022 | 2026-07-29 | `ARCH-020` | Separated untrusted submissions from completed stored records and typed every authority receipt. | Registered `record_submission`, `append_receipt`, `cas_receipt`, `projection_receipt`, and `payload_receipt` schemas; ordinary append rejects promotion bypasses. This supplies implementation evidence for resolving `FND-025` and `FND-026`, subject to independent finding closure. | Re-run Barrier-2 review against the implementation commit. |
| TL-023 | 2026-07-29 | `WS-020`, `WS-030`, `VERT-010` | Built and self-tested the smallest valid closed world-state and autonomy graph. | The golden fixture has 18 immutable records; 11 focused pytest cases cover cold restore, payload corruption, store ownership, reopen ordering, concurrent promotion, failed-promotion atomicity, historical invalidation, head rebuild, and candidate contract mutation. This supplies prototype evidence for `FND-028` and `FND-030` but is not experimental validation. | Freeze test evidence and obtain independent Barrier-2/3 decisions. |
| TL-024 | 2026-07-29 | `ARCH-030` | Reconciled the operational graph and architecture records with the implemented authority boundary. | `.venv/bin/python scripts/validate_ultrabuild.py`, `.venv/bin/python scripts/validate_ultrabuild_contracts.py`, and `.venv/bin/python -m pytest -q stewie/ultrabuild/test_store.py` exited successfully; barrier states remain unchanged. | Commit-pin the evidence and assign independent review. |

## Open orchestration decisions

- `OD-001`: exact minimum operational effect sizes and perturbation levels must be frozen after pilots.
- `OD-002`: select the terrestrial domain and verify redistribution rights.
- `OD-004`: remove or restore existing claims whose formal/result artifacts are absent.
- `OD-006`: choose the post-prototype migration, retention, spatial-projection, and distributed-store
  strategy only after the SQLite semantic oracle is independently accepted and benchmarked.

## Resolved orchestration decisions

- `OD-003` (2026-07-29): selected `stewie.ultrabuild.store.AuthoritativeStore` as the Barrier-3
  prototype authority. This does not select a deployment-scale backend.
- `OD-005` (2026-07-29): transaction ordering starts with a deterministic SQLite sequence and
  valid-at/known-at revision reference query; Postgres/PostGIS remains a later projection or backend
  candidate.

Defects and revision outcomes will append to this table; prior entries are not rewritten to make the
project appear more linear than it was.
