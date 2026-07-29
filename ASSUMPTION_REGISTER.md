# Assumption register

**Artifact ID:** `ART-ASSUMPTIONS`
**Producer node:** `ORCH-001`
**Consumers:** every implementation and experiment node
**Status:** active; assumptions are test inputs, not facts.

| ID | Assumption | Basis | Test/sensitivity | Failure response |
|---|---|---|---|---|
| A-01 | A shared action extent identifies a possible dependency between subsequent source errors. | Conservative provenance heuristic | Compare against residual-estimated dependency and no-edge/global-edge ablations | Narrow claim; abstain where dependency is unknown |
| A-02 | Source identity is cryptographically/operationally bound and not freely relabelled. | Required to reject duplicates | Duplicate and relabelled-duplicate fault injection | Add attestation or declare source-integrity boundary |
| A-03 | Cross-component observation errors have zero covariance for the analytic variance bound. | Current theorem condition | Residual association tests and sensitivity to hidden common error | Do not use probability interpretation; widen/abstain |
| A-04 | Declared marginal uncertainty is calibrated. | Required by statistical gate | Miscalibration sweep and reliability curves | Recalibrate or label unknown; reject safety bound |
| A-05 | Physics-model bias may be arbitrary, but physics cannot enter accepted values. | Structural mechanism | Noninterference mutation tests | Block promotion integration |
| A-06 | A task harm tolerance can be declared or physically derived. | Downstream operation requirement | Curves over tolerance and threshold sensitivity | Avoid single-threshold conclusion |
| A-07 | Store transaction order is monotonic and durable. | Event-store contract | Concurrent append, crash, corruption, restart tests | Fail closed and repair store |
| A-08 | Valid time can be mapped from source clocks with bounded uncertainty. | Sensor/robot clock metadata | Clock-offset/drift perturbations | Preserve time uncertainty; abstain if ordering matters |
| A-09 | A 2.5-D elevation patch is adequate for the first grading/excavation slice. | Current code and tasks | Scenarios without overhang/void plus conversion-error report | Move affected cases to voxel/mesh extension |
| A-10 | The Haworth crop is suitable for controlled lunar simulation evaluation. | Real LOLA-derived base terrain | Multiple crop/relief blocks | No generality claim from one crop |
| A-11 | Simulated conserved state is a valid withheld reference for testing software reconciliation behavior. | Controlled systems experiment | Reference firewall and model-mismatch studies | Label as simulated reference only |
| A-12 | Action logs sufficiently describe executed spatial effects. | Needed for dependency/time inference | Recall/precision and partial-execution sweeps | Preserve alternatives or request verification |
| A-13 | Observation-source errors are exchangeable enough for the selected aggregate/statistics. | Current plain-mean mechanism | Heteroscedastic/per-cell uncertainty study | Replace model or narrow scope |
| A-14 | Payload hashes and journal chains are computationally collision-resistant. | SHA-256 standard engineering assumption | Integrity verification; no empirical collision test | Upgrade algorithm if security guidance changes |
| A-15 | CPU-only execution is adequate for Barrier 3. | Mechanism operates on bounded 2.5-D arrays | Performance benchmark | Reduce slice or review architecture |
| A-16 | Camera/IMU/odometry remain the primary sensor condition; LiDAR is not required. | Mission constraint | CI/test configuration without LiDAR | Remove accidental LiDAR-labelled synthetic source |
| A-17 | Terrestrial data can be licensed and normalized without advantaging one method. | Required for generality | Data/license review and same-interface check | Defer generality claim |

An assumption becomes a supported condition only after its named test passes. A failed assumption does
not automatically invalidate all engineering behavior, but it invalidates every theorem or claim that
depends on it.
