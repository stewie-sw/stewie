# Repository and environment inventory

**Artifact ID:** `ART-INVENTORY`
**Producer node:** `INV-001`
**Consumers:** `RES-010`, `ARCH-010`, `WS-010`, `EXP-010`, `ORCH-001`
**Status:** independently inspected baseline; implementation claims remain limited to cited components.

## Identity and scope

- Commit: `d1056d9deff4e540557b13c8cb78fc799330410e`
- Branch: `ultrabuild/graph-orchestration-2026-07-28`
- Clean restart: `/mnt/projects/stewie/ultrabuild`
- The user’s separate dirty checkout at `/mnt/projects/stewie/code` was preserved.
- Inventory agents excluded concurrently authored UltraBuild documents and assessed tracked baseline
  code/documents only.

## Repository shape

The monorepo contains:

- `stewie/`: physics, terrain, twin, contracts, runtime, FastAPI, sensors, geospatial, and evaluation;
- `dart/`: perception, localization, geometry, and evidence;
- `lode/`: planning, execution, fleet, and autonomy;
- `leap/`: earthmoving/construction tasks;
- `forge/`: physics service boundary;
- `gis/`, `stewie_qgis/`: QGIS/QWC2 integration;
- `ros2_ws/`: ROS 2 packages and messages;
- `frontend/` plus legacy server assets: operator surfaces;
- `benchmarks/`, `validation/`, `samples/`: executable probes and artifacts; and
- `docs/`, `design/`, `papers/`: architecture, requirements, reviews, and sources.

There are no tracked top-level `dissertation/`, `experiments/`, `baselines/`, `ablations/`, or
dedicated `stewie/world_state`, `stewie/provenance`, `stewie/temporal`, or
`stewie/reconciliation` packages. Relevant implementation is distributed through
`stewie/twin`, `stewie/contracts`, `stewie/server`, and `stewie/physics`.

## Reusable foundations

| Foundation | Evidence | Reuse boundary |
|---|---|---|
| Conserved terrain mutation | ADRs 0001–0003; `stewie/physics/column_state.py` | Simulation/physics evidence, not physical truth |
| Observed patch journal | `stewie/twin/versioned.py` | Strong byte-hashed append/replay; provenance/time schema incomplete |
| Terrain history | `stewie/twin/terrain_memory.py` | Sparse integer-version reconstruction; destructive rollback and incomplete spatial hash |
| Linked transactions | `stewie/twin/envelope.py`, `stewie/server/world_state.py` | Durable identities; state roles and two-time semantics absent |
| Promotion kernel | `stewie/twin/promotion.py` | Observation-only candidate, physics veto, stale/dependency handling; offline path |
| Comparators/fault probes | `stewie/twin/baselines.py`, `veto_experiment.py`, twin tests | Controlled simulation/component evidence |
| Multi-vehicle overlap | `stewie/twin/shared_terrain.py` | Action-derived possible-dependency edges, not map reconciliation |
| Frames/CRS/units | `INTERFACE.md`, `stewie/bridge/frames.py`, `stewie/geospatial/` | Strong reusable seams; canonical docs have some drift |
| GIS | `gis/README.md`, QGIS project and COG checks | Mature projection/operator surface, not authority |
| Runtime/render | `stewie/runtime/viz2_runtime.py`, `stewie/stream/` | Useful deterministic simulation adapter |
| Governance/audit | `stewie/contracts/audit.py`, server governance | Recently hardened; operational audit is not full scientific lineage |
| CI/package gates | `.github/workflows/ci.yml`, locks, scripts | Broad engineering checks; not scientific validation |

## Barrier-2 and Barrier-3 blockers

1. Simulated, observed-candidate, accepted, and archived terrain are not isolated branches.
2. Live `POST /twin/resync` writes observations directly; planning uses observed-wins precedence.
3. The production reconciliation contract assumes fresh observations; the stronger promotion kernel
   is experimental only.
4. Valid time is partial; transaction-time intervals and bitemporal queries do not exist.
5. Persistent records reduce much lineage to strings and scalar uncertainty.
6. Conflicting hypotheses are not durably stored.
7. Plans/commands do not consistently name the accepted world revision and time lens used.
8. `TerrainMemory` chain metadata does not commit the complete sparse spatial delta; destructive
   `revert_to` removes later history.
9. A multi-site probe showed a transaction labelled for Shackleton could link the default Haworth
   twin identity because `WorldStateService` carries one global set of identities.
10. Projection writes are best effort without a durable outbox/lag-rebuild protocol.
11. Runtime/API/ROS contracts omit decision-critical source, clock, frame, calibration, uncertainty,
    and revision fields.
12. Native ROS nodes are mostly skeletal and do not constitute a closed autonomy loop.
13. Process-local locks and a one-worker modular monolith are not horizontally scalable.
14. Existing performance probes do not measure region/robot/version scaling.
15. Root package publication may omit required workspace packages that CI installs manually.

## Research blockers and contradictions

- Three documents imply three dissertation centers: state acceptance, conserved dynamics plus learned
  perception, and articulated-rover estimation. This restart selects state acceptance; the others are
  supporting apparatus/studies unless separately defended.
- `docs/BENCHMARK_SPEC.md` acknowledges the integrated two-domain benchmark and live gating are
  incomplete.
- The benchmark cites a Lean project under `dissertation/formal`, but no such tracked project exists.
- An S3LI write-up names result JSON artifacts absent from this checkout.
- The root license is all-rights-reserved while some texts promise open/CC0 release.
- README requirement counts disagree with the generated 413-row status/manifest.
- Real base terrain is combined with controlled simulated actions and injected faults; broad “nothing
  synthetic” language is false.
- Numerically exact conservation within a model does not establish exact physical prediction.
- A synthetic second source is called `lidar`, conflicting with the no-LiDAR primary condition.

## Existing executable evidence

Independent inventory runs reported:

- all `stewie/twin/test_*.py`: 314 passed;
- focused storage/transaction/reconciliation/physics suites: 185 passed in overlapping groups;
- `python -m stewie.physics.tests`: 19/19 checks passed;
- a cut/dump/relax probe conserved 761.083052 kg with relative numerical drift `1.49e-16`; and
- the merged commit had already passed the full repository suite, lint, and changed-file type checks
  before the clean restart.

These results are not added together because the suites overlap. No frozen UltraBuild test log or
exact-commit clean-environment attestation exists yet.

## Host capability

| Resource | Available |
|---|---|
| CPU/RAM/disk | Intel i9-14900K class, 32 logical CPUs; 125 GiB RAM; about 454 GiB free |
| GPU | NVIDIA RTX 3090, 24 GiB, driver 535.261.03 |
| Runtime | Python 3.11.2; Node 20.20.2; Docker 29.6.2 |
| GIS | QGIS 3.22.16; GDAL 3.6.2 |
| Formal tooling | Lean launcher present, but requested toolchain attempted a download and was not used as evidence |
| Missing on host PATH | ROS 2, colcon, Gazebo, Godot, COLMAP; a separate Godot binary exists under `/mnt/projects/tools/` |
| Python env | No `.venv` in the clean worktree; adjacent checkout venv is not a clean reproduction environment |
| Assets | Haworth/LOLA, Katwijk, GIS COG, and several validation assets present |

Existing running containers originated from the other checkout and are not evidence for this branch.

## Minimal next build

Use one real Haworth window, one conserved action, one delayed partial observation, and four immutable
records: evidence claim, world event, world revision, and conflict/decision. Append JSONL manifests
and content-addressed NPZ payloads are adequate for Barrier 3. Simulation and observation remain
candidate branches; only a recorded reconciliation decision may advance an accepted branch.
