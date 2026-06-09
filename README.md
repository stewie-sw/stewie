# STEWIE — Surface Terrain Engineering & World-model Integration Environment

Monorepo (M0, 2026-06-09): full histories of `dustgym` (McCardle + Storey) and `solnav` (Storey)
imported via subtree under `dustgym/` and `solnav/`. The DART/LODE/LEAP/FORGE restructure happens in
M1+ (see `../design/SUBSYSTEM_REORG_PLAN_2026-06-09.md`). PRIVATE while PN1/PN2 are unpublished.

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
