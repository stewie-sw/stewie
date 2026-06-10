# STEWIE — Surface Terrain Engineering & World-model Integration Environment

**IPEx builds the Moon. STEWIE plans the build.** *(in silico → in situ)*

One stack: conserved-physics lunar terrain authority, mission planner + mission-control reports,
Gymnasium environments, Godot render/sensor sidecar, and the evaluation gates — organized by
responsibility: `stewie/` (platform: physics, terrain, twin, specs, envs, server, bridge, sensors,
godot, eval) · `dart/` (perception) · `lode/` (operations) · `leap/` (earthmoving) · `forge/`
(infrastructure).

- Canonical design source: **`PRD.md`** (STEWIE PRD; §16 = subsystem map + phase gates)
- Install: `pip install -e .[dev]` · serve: `stewie-serve` · deploy: `docker compose -f deploy/compose.yml up -d`
- Gym envs: `import stewie` → `gym.make("Stewie/RoverDrive-v0")` (legacy `Dust/*` IDs + `import
  dustgym` + `DUSTGYM_*` env vars remain as deprecated aliases for one transition cycle)
- History: this monorepo carries the full histories of the `dustgym` simulator (McCardle + Storey)
  and the navigation research formerly named solnav (Storey); both names are retired (2026-06-10).

## M0 state (2026-06-09)
- Committed: both subtree imports (180 commits total; dustgym HEAD `5c986fb`, solnav HEAD `305a632`).
- UNCOMMITTED BY DESIGN: the working-tree overlay deltas — the source repos carried uncommitted
  state (incl. the REAL gate JSON + G1 capture data, untracked in solnav; John's doc edits in
  dustgym). The monorepo working tree is byte-identical to the source trees (diff -r verified);
  those deltas stay uncommitted here exactly as they are uncommitted there. They are not ours to
  commit silently; M1 will commit them only where the restructure must touch them (flagged then).
- Verified in-monorepo: solnav 348 passed + gate JSON byte-identical (md5 bd8bdada…) + ruff/mypy
  clean; dustgym suite result appended below on completion.
- Working-location rule: M1+ restructuring happens HERE. The old trees (`../dustgym`,
  `../research/projects/solnav/solnav`) are FROZEN as fallback sources until M4 passes, then retire
  per M5 (John's + Aaron's sign-offs).
