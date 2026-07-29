# System requirements

**Artifact ID:** `ART-REQUIREMENTS`
**Producer node:** `ARCH-010`
**Consumers:** every implementation, integration, review, and experiment node
**Status:** specified; current-state labels are inventory findings, not acceptance decisions.

`MUST` requirements are Barrier 3 or dissertation-core requirements. `SHOULD` requirements are
required before the broader systems claim. `MAY` requirements are extensions. “Existing” means a
component exists in the merged baseline; it does not mean the integrated requirement is satisfied.

| ID | Requirement | Level | Current baseline | Verification |
|---|---|---:|---|---|
| SEM-01 | Every material state claim identifies one state kind from the ontology. | MUST | Partial | Schema rejection of missing/invalid kind |
| SEM-02 | Planned, predicted, simulated, observed, proposed, reconciled, verified, authoritative, superseded, and archived states remain distinguishable. | MUST | Partial | Cross-interface state-kind tests |
| SEM-03 | Every accepted mutation creates an immutable version or an explicit supersession event. | MUST | Existing components | Replay and mutation tests |
| SEM-04 | A decision records the exact world/map version and query lens it consumed. | MUST | Missing | End-to-end plan/run provenance test |
| SEM-05 | Unresolved competing claims can coexist over the same region and valid time. | MUST | Missing | Conflict-retention scenario |
| SEM-06 | The evaluation reference is structurally inaccessible to the system under test. | MUST | Existing harness component | Poison/displacement attestation |
| SEM-07 | Simulated, observed-candidate, accepted, and archived state use branch-isolated revision heads. | MUST | Missing | SIM/observation cannot change accepted planner surface before promotion |
| TMP-01 | Claims carry explicit valid-time and transaction-time intervals. | MUST | Valid time partial; transaction time missing | Bitemporal schema and query tests |
| TMP-02 | An old observation cannot silently overwrite a state valid after the observation. | MUST | Component gate exists | Out-of-order integration test |
| TMP-03 | The system answers “as known at K, believed valid at T” deterministically. | MUST | Missing | Bitemporal reconstruction oracle |
| TMP-04 | Corrections retain the prior transaction-time record and link supersession cause. | MUST | Partial journals | Correction/replay test |
| PRV-01 | Every claim links source sensor, robot, pipeline, algorithm, calibration, frame, and transformation history. | MUST | Partial | Provenance-completeness metric |
| PRV-02 | Provenance is queryable as structured data, not recoverable only from text logs. | MUST | Partial | Lineage query/replay test |
| PRV-03 | Every derived artifact is content-addressed and records code, config, seed, and input hashes. | MUST | Partial | Reproducibility validator |
| PRV-04 | State mutation and its audit/provenance intent are ordered fail-closed. | MUST | Existing route components | Injected audit-write failure |
| UNC-01 | Sensor, localization, geometry, time, material, model, and dependency uncertainty remain distinct. | MUST | Mostly missing | Schema and propagation tests |
| UNC-02 | Missing coverage is represented by an explicit mask, never silently filled. | MUST | Existing promotion component | R1 mutation test |
| UNC-03 | Reported uncertainty is calibrated or labelled assumption/unknown. | MUST | Partial | Reliability/calibration curves |
| REC-01 | A promoted value is constructed only from admissible observations. | MUST | Existing component | Noninterference mutation tests |
| REC-02 | Physics may veto or trigger abstention but cannot choose values, weights, source subsets, or fills. | MUST | Existing component | Physics-value noninterference tests |
| REC-03 | Reconciliation returns PROMOTE, REJECT, ABSTAIN, or explicit competing hypotheses. | MUST | First three exist | Decision-contract tests |
| REC-04 | Partial overlap is evaluated only where the compared sources both have coverage. | MUST | Existing component | Pair-overlap tests |
| REC-05 | Duplicate source identities are rejected; relabelled duplicates are a declared source-integrity risk. | MUST | Existing component | Duplicate/relabelled fault tests |
| REC-06 | Action-derived pairwise dependency edges are applied after stale-source removal. | MUST | Existing component | Ordering/permutation tests |
| REC-07 | Unknown dependency for multiple sources cannot be treated as independence. | MUST | Existing component | Fail-closed test |
| REC-08 | Planned-versus-observed and simulated-versus-observed divergence remains visible. | SHOULD | Partial UI/design | Divergence API/UI contract test |
| PHY-01 | Physics is labelled by model/version/calibration and uncertainty; it is never physical truth. | MUST | Partial | Evidence schema tests |
| PHY-02 | Material/volume conservation, reachability, and temporal ordering can contribute independent evidence. | SHOULD | Conservation exists | Physics-gating ablation |
| PHY-03 | The no-physics regime is explicit and cannot inherit a physics-backed safety claim. | MUST | Existing component | No-physics fault probe |
| SPA-01 | Coordinate reference system, local frame, axis convention, resolution, extent, and units are explicit. | MUST | Strong existing contracts | Schema/frame tests |
| SPA-02 | 2.5-D, mesh, voxel, raster, and object representations declare supported operations and loss on conversion. | SHOULD | Partial | Round-trip/error contracts |
| SPA-03 | Region and multi-resolution queries preserve state kind, time, provenance, and uncertainty. | SHOULD | Missing | Query integration tests |
| EVT-01 | Events identify actor, source, spatial extent, valid/transaction time, predecessor, uncertainty, verification, and downstream invalidation. | MUST | Partial | Event-schema validation |
| EVT-02 | Journals are append-only, durable, tamper-evident, and fail closed on interior corruption. | MUST | Existing components | Crash/corruption/restart tests |
| EVT-03 | Terrain changes invalidate affected derived layers and dependent plans. | MUST | Missing | Dependency invalidation test |
| EVT-04 | Integrity hashes commit the complete spatial payload or its immutable content hash, not summary metadata alone. | MUST | Partial | Sparse-payload tamper test |
| EVT-05 | Site/world identity is part of every authority lookup; one site cannot link another site’s twin/version. | MUST | Defect observed | Cross-site transaction isolation test |
| SYN-01 | Robot-local claims retain local identity through deferred synchronization. | SHOULD | Missing | Partition/rejoin scenario |
| SYN-02 | Synchronization is metadata-first and content-addressed under bandwidth limits. | SHOULD | Design only | Bandwidth benchmark |
| SYN-03 | Replica convergence never erases scientifically meaningful unresolved conflict. | SHOULD | Missing | Multi-value convergence test |
| AUT-01 | Planning names its state version and rejects stale/unknown state according to policy. | MUST | Missing | Planner integration test |
| AUT-02 | Value-of-information can select act, rescan, request, defer, dispatch, or human review. | SHOULD | Missing | VOI decision experiment |
| SAF-01 | Live command paths are isolated from simulation and require explicit authority. | MUST | Existing governance components | Negative egress and role tests |
| SAF-02 | Stale state, unresolved high-risk conflict, or excessive uncertainty can inhibit action. | MUST | Partial | Failure-containment scenario |
| OBS-01 | Runs carry structured logs, trace IDs, graph-node ID, experiment ID, seed, and mutation records. | MUST | Partial | Observability completeness test |
| OBS-02 | A frozen run can be deterministically replayed or differences are quantified. | MUST | Partial | Replay hash comparison |
| EXP-01 | Baselines receive normalized inputs, terrain, evidence sequences, and seeds. | MUST | Component harness | Harness equivalence test |
| EXP-02 | Harmful acceptance is always reported with abstention and accepted-state error. | MUST | Existing spec | Report-schema validator |
| EXP-03 | Baselines, ablations, perturbations, negative results, uncertainty, and compute cost are retained. | MUST | Partial | Evidence-package validator |
| PER-01 | Mandatory operations satisfy `PERFORMANCE_BUDGET.json` or fail the associated barrier. | MUST | Unmeasured | Repeated benchmark |
| GEN-01 | Generality claims require at least lunar and terrestrial evaluation domains. | MUST for generality | Missing integrated run | Frozen two-domain experiment |

No implementation node may silently downgrade a MUST. A change requires an assumption/risk update,
independent review, and a graph-manifest revision.

## Ownership and evidence policy

Requirement prefixes have one owning graph node: `SEM`/`SPA` → `WS-010`, `TMP` → `WS-020`, `PRV`/
`EVT` → `WS-030`, `UNC` → `WS-050`, `REC` → `WS-040`, `PHY` → `PHY-010`, `SYN` → `VERT-030`,
`AUT` → `VERT-020`, `SAF`/`OBS` → `INT-010`, `EXP` → `EXP-010`, `PER` → `PERF-010`, and `GEN` →
`EXP-020`. The owner produces evidence; it cannot independently accept its requirement.

`scripts/validate_ultrabuild_requirements.py` parses every row, verifies the owner exists, and
reconciles exact `[REQ:XXX-00]` test citations. An uncited row remains planned and is reported without
being represented as verified. A future requirement-evidence record must bind the requirement ID,
test/result artifact, code/control commit, reviewer, and support level before any status advances.
