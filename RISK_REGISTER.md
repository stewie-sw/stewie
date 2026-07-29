# Risk register

**Artifact ID:** `ART-RISKS`
**Producer node:** `ORCH-001`
**Consumers:** every graph node and barrier
**Status:** active; reviewed at every barrier.

| ID | Risk | Likelihood | Impact | Owner node | Trigger/evidence | Mitigation and contingency |
|---|---|---|---|---|---|---|
| R-01 | The live resync path bypasses the research promotion mechanism. | Certain | Critical | `VERT-010` | `docs/BENCHMARK_SPEC.md` and route inspection | Make one gated write path; add a bypass-negative integration test. Block Barrier 3 until closed. |
| R-02 | Version history is misrepresented as bitemporal state. | Certain | Critical | `WS-020` | No transaction-time interval/query implementation | Use explicit terminology; implement reference queries before claiming bitemporality. |
| R-03 | Action overlap is mistaken for measured error covariance. | High | Critical | `WS-040` | `shared_terrain.py` produces possible-dependency edges only | Preserve “may depend” semantics; evaluate with independent residual data; ablate graph assumptions. |
| R-04 | Relabelled duplicate sources defeat the rule. | High | Critical | `WS-030` | Existing 20/20 harmful controlled result | Bind source credentials; hash/attest payloads; retain as explicit failure boundary if undetectable. |
| R-05 | Model/sensor uncertainty is uncalibrated or scalar-only. | High | High | `WS-050` | One scalar sigma per source; no per-cell covariance | Calibration experiments, typed unknowns, and a per-cell extension; abstain outside support. |
| R-06 | Safety improvement is an abstention artifact. | Medium | Critical | `EXP-010` | Gate can refuse instead of accept | Always pair harm with abstention, accepted error, time to correction, and decision cost. |
| R-07 | Withheld reference leaks into candidate generation. | Low | Critical | `EXP-010` | Shared simulation process/harness | Structural separation plus reference-displacement attestation and independent harness review. |
| R-08 | A controlled simulation result is described as physical validation. | High | Critical | `DISS-010` | Current tests inject faults over simulated changes | Enforce support labels and claim matrix; require physical/independent data for physical claims. |
| R-09 | Existing docs support three incompatible thesis centers. | Certain | High | `RES-010` | State acceptance, hybrid world models, and articulated navigation are each called the dissertation center | Freeze state acceptance as core; treat physics/perception/navigation as apparatus or scoped secondary studies. |
| R-10 | Claimed formal/evaluation artifacts are absent. | Certain | Critical | `RES-020` | `docs/BENCHMARK_SPEC.md` names `dissertation/formal`; cited S3LI JSONs are absent | Remove/downgrade claims or restore verified content-addressed artifacts; never cite missing evidence. |
| R-11 | Novelty overlaps established temporal DB, GIS, SLAM, provenance, CRDT, and scene-graph work. | High | Critical | `RES-020` | Initial primary-source review | Complete adversarial novelty matrix; narrow claim to mechanism interaction; include strong external baselines. |
| R-12 | The harm tolerance or support threshold is author-selected. | High | High | `EXP-010` | Existing amendment history found free parameters | Derive from downstream task where possible; preregister sensitivity curves and minimum effects. |
| R-13 | Live and experimental semantics diverge after integration. | High | Critical | `INT-010` | Existing fixed precedence in production path | One contract and differential tests comparing API and library results. |
| R-14 | Event/audit/provenance durability fails across processes. | Low | Critical | `ARCH-020` | Recently repaired governance races show the class is real | Cross-process locks/transactions, injected write failures, restart/corruption tests. |
| R-15 | Terrain rollback destroys evidence needed for historical reconstruction. | Medium | High | `WS-020` | Current `TerrainMemory.revert_to` truncates later retained history | Replace destructive rollback in research path with new branch/supersession event. |
| R-16 | Partial coverage or frames cause false support/merge. | High | Critical | `WS-040` | Prior benchmark amendment exposed this seam | Explicit masks, pairwise overlap, frame uncertainty, coverage perturbations, mutation tests. |
| R-17 | Licensing prevents an open reproducibility package. | High | High | `ORCH-001` | Repo is all-rights-reserved while benchmark/docs mention open/CC0 | Produce a license matrix, remove contradictory claims, and separate redistributable manifests from restricted assets. |
| R-18 | Missing external data/GPU/ROS/Godot/Chrono makes runs nonportable. | High | Medium | `PERF-010` | Host-gated tiers already exist | CPU Barrier-3 slice, visible skips, fetch/checksum tools, and tiered replication instructions. |
| R-19 | Performance scales poorly with cell/source/version graph size. | Medium | High | `PERF-010` | No integrated scaling report | Predeclare scale grid and budgets; profile before optimizing; snapshot/index only after semantics pass. |
| R-20 | Better map metrics do not improve decisions. | Medium | Critical | `EXP-020` | No current end-to-end decision experiment | Make RQ5 a required systems-claim test; accept a null result and narrow conclusions. |
| R-21 | Requirements/status counts are internally inconsistent. | Certain | Medium | `ORCH-001` | README says 339 while generated status says 413 | Generated manifest wins; repair narrative counts in a separate reviewed node. |
| R-22 | “No synthetic values”/“exact prediction” language overstates the evidence. | Certain | High | `DISS-010` | Real DEM plus synthetic actions/noise/bias and exact-within-model physics | Use precise labels: real base terrain, controlled simulated changes/faults, numerically conserved model. |
| R-23 | A site-labelled transaction links the wrong site’s observed twin. | Demonstrated | Critical | `ARCH-010` | Independent multi-site probe linked Shackleton label to default Haworth twin identity | Make world/site part of authority key and accessor; add cross-site isolation/restart tests. |
| R-24 | Terrain history chain verifies summary metadata while spatial deltas are altered. | Demonstrated | Critical | `WS-020` | Independent probe modified retained indices without breaking `TerrainMemory.verify_chain()` | Hash immutable sparse payload bytes/content ID; reject destructive rollback on research branches. |
| R-25 | Published root wheel can omit required workspace packages installed manually by CI. | Medium | High | `INT-010` | Root metadata versus CI/publish workflow inspection | Add declared dependencies or publish workspace artifacts together; clean wheel import test. |

`RISK_DISPOSITIONS.yaml` binds every row to barriers, status, evidence, residual risk, and acceptance
authority. A Critical risk marked `open` or merely `mitigated` blocks its associated barrier until
independent review either closes it or records `accepted_limitation` with a narrowed claim in that
barrier's typed decision.
