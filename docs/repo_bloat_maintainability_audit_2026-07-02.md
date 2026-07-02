---
title: Repository Bloat, Maintainability, Security, and Streamlining Audit
nav_order: 58
---

# STEWIE repository bloat and maintainability audit - 2026-07-02

This audit measures current repository/working-tree bloat and identifies what should be deleted,
externalized, refactored, or rewritten for efficiency, security, extensibility, maintainability, and
continuity with the updated PRD.

## Executive summary

The working tree is large: **5.3 GB**. The tracked repository payload is much smaller:
**1,897 tracked files, about 349 MB tracked on disk**. Most disk bloat is local/generated/vendor
state. Most maintainability bloat is not file size; it is boundary drift, generated artifacts in git,
the large browser cockpit shell, ROS skeleton packages, and research/prototype modules that are not
yet wired into one runtime spine.

The right strategy is not a full rewrite. Keep the tested math/perception/planning core and wrap it
behind stricter contracts. Rewrite/streamline the app shell, runtime wiring, data/artifact policy,
and ROS autonomy nodes incrementally.

## Quantitative inventory

Working tree size:

| Area | Size | Notes |
|---|---:|---|
| Whole working tree | 5.3 GB | includes ignored/generated/vendor files |
| Tracked files | ~349 MB | `git ls-files` payload |
| `.git` | 309 MB | history/index/object store |
| `desktop/` | 981 MB | Electron `node_modules` + build output |
| `.venv/` | 905 MB | local Python environment |
| `.claude/` | 611 MB | local workflow worktrees/scratch |
| `datasets/` | 537 MB | local DEM/imagery data; ignored |
| `.mypy_cache/` | 494 MB | local type-check cache |
| root `out/` | 467 MB | generated COLMAP/render scratch |
| `stewie/godot/out/` | 451 MB | generated render outputs |
| `samples/` | 225 MB | mostly tracked sample rasters |
| `validation/` | 53 MB | screenshots/figures |
| `stewie/eval/validation/` | 32 MB | validation fixtures/artifacts |

Tracked payload by top-level directory:

| Area | Tracked size | Tracked files |
|---|---:|---:|
| `samples/` | 234.8 MB | 192 |
| `stewie/` | 77.7 MB | 846 |
| `benchmarks/` | 18.6 MB | 75 |
| `viz/` | 10.3 MB | 16 |
| `validation/` | 8.8 MB | 78 |
| `docs/` | 6.9 MB | 86 |
| `scripts/` | 1.2 MB | 180 |
| `dart/` | 1.2 MB | 160 |
| `lode/` | 1.0 MB | 98 |

Tracked text/code:

| Metric | Value |
|---|---:|
| Total counted text/code lines | ~219k |
| Python files | 909 |
| JS files | 77 |
| Test files matched by filename | 481 |
| Largest JS shell | `stewie/server/web/assets/cockpit.js`, 6,201 lines |
| Cockpit HTML shell | `stewie/server/index.html`, 1,547 lines |
| Largest Python test | `lode/test_mission_planner.py`, 2,323 lines |
| Largest Python module | `stewie/terrain/scenes.py`, 1,255 lines |

## Findings

### P0 - The repository carries large tracked data fixtures that should become external artifacts

`samples/` is the largest tracked payload: about **235 MB**. The biggest tracked files are lunar DEM
sample rasters: multiple `*.rf32` files at 16 MB each plus `state_label.r8` files at 4 MB each.
Together the three lunar DEM bundles alone account for about **204 MB** of tracked payload.

Examples:

- `samples/lunar_dem/haworth_10km_5m/*.rf32`
- `samples/lunar_dem/nobile_rim1_10km_5m/*.rf32`
- `samples/lunar_dem/shackleton_rim_10km_5m/*.rf32`

These are valuable fixtures, but they should not all live as normal tracked source files. Move the
large bundles to an artifact store, DVC/LFS, or fetch-on-demand cache with checksums. Keep only tiny
smoke fixtures and metadata manifests in git.

Recommended target:

- Source checkout: less than 150 MB tracked.
- Default test fixture set: less than 25 MB.
- Full validation datasets: fetched by `stewie-fetch-dem`/artifact script, checksum-pinned.

### P0 - The working copy is polluted by generated/vendor/runtime artifacts

The working tree is 5.3 GB while tracked payload is only 349 MB. The largest local-only directories are
`desktop/`, `.venv/`, `.claude/`, `datasets/`, `.mypy_cache/`, root `out/`, and `stewie/godot/out/`.
The `.gitignore` already covers most of this, but the local tree still has all of it present.

Cleanup policy:

- Keep `.venv/`, `node_modules/`, `desktop/dist/`, `.mypy_cache/`, `.pytest_cache/`, `.ruff_cache/`,
  `.claude/`, `datasets/`, and `out/` out of source operations.
- Add a `scripts/clean_workspace.py` or shell script with dry-run/default-safe removal for ignored
  generated artifacts.
- Move large generated outputs under one ignored `artifacts/` or `.stewie_artifacts/` root instead of
  scattering them across `out/`, `validation/`, `stewie/godot/out/`, `desktop/dist/`, and package dirs.

### P0 - The cockpit shell is the highest-maintenance frontend bloat

`cockpit.js` is 6,201 lines, while `index.html` is 1,547 lines. The file has started a modular split,
but it still owns too much: auth glue, command authority, settings persistence, map/globe layers,
perception rendering, release/execution, report/world-state, trainer/admin/settings, and many direct
`innerHTML`/fetch/localStorage paths.

There is security hardening: an escape helper and DOM builder exist at
`stewie/server/web/assets/cockpit.js:770-791`, credentials are kept out of localStorage at
`cockpit.js:1480-1487`, and command-authority election is explicit at `cockpit.js:1489-1537`.
But this is still a broad blast radius: one file touches nearly every operator workflow.

Rewrite target:

- Do not rewrite the whole frontend at once.
- Extract one route/pane at a time behind typed adapters.
- Move all API calls to one `api_client` layer with view-state results.
- Replace ad-hoc `innerHTML` sites with pure renderers or DOM builders.
- Make the route state model explicit for PRD mode/profile/sensor/authority/truth state.
- Add Playwright smoke for deployed-like desktop/mobile navigation and console errors.

### P0 - ROS autonomy packages are scaffolds, not runtime implementations

The ROS2 workspace is small and good as a skeleton, but not yet a working autonomy runtime. For example,
`stewie_perception` and `stewie_mapping` explicitly say full domain logic lands later and only spin a
node (`ros2_ws/src/stewie_perception/stewie_perception/node.py:1-19`,
`ros2_ws/src/stewie_mapping/stewie_mapping/node.py:1-19`).

This is not bloat in size; it is continuity bloat. The repository contains many tested perception,
mapping, planning, and hazard modules, but the ROS packages do not yet use them. That creates two
mental systems: “algorithm modules that work” and “runtime nodes that exist.”

Rewrite target:

- Replace skeleton ROS nodes with thin adapters over existing tested modules.
- Do not port all logic into ROS packages. Keep domain logic in `dart`/`lode`/`stewie`, and make ROS
  nodes transport adapters with typed message conversion, lifecycle, diagnostics, and topic freshness.

### P1 - Data, generated evidence, and source code are interleaved too freely

There are 617 tracked files under samples/benchmarks/validation/godot-output/eval-validation categories.
Some are necessary acceptance artifacts; many are generated visual evidence or frozen benchmark outputs.
This blurs source, fixture, benchmark, report, and generated-output boundaries.

Recommended structure:

```text
src packages        stewie/, dart/, lode/, leap/, forge/
runtime adapters    ros2_ws/, desktop/, deploy/
tiny fixtures       tests/fixtures/ or stewie/eval/fixtures/
large datasets      external artifact cache
evidence bundles    artifacts/evidence/<run_id>/, ignored by default
golden artifacts    validation/golden/, minimal and curated
docs                docs/
```

### P1 - Python package boundaries are broad and historically grown

The package list in `pyproject.toml:60-64` ships many packages together:
`stewie`, `stewie.physics`, `stewie.terrain`, `stewie.twin`, `stewie.specs`, `stewie.envs`,
`stewie.server`, `stewie.eval`, `stewie.bridge`, `dart`, `lode`, `leap`, and `forge`.

That is convenient, but it makes dependency separation weak. `server` extras include heavy optional
packages such as OpenCV, SciPy, rasterio, matplotlib, and pyproj (`pyproject.toml:30-40`). This is
reasonable for a mission-planner product install, but too broad for lightweight runtime profiles.

Recommended split:

- `stewie-core`: contracts, specs, physics primitives, world/twin state.
- `stewie-perception`: DART image/depth/mapping modules and OpenCV dependencies.
- `stewie-planning`: LODE planner/executive/costmaps.
- `stewie-server`: FastAPI cockpit/API.
- `stewie-ros`: ROS2 adapters.
- `stewie-dev`: benchmarks, validation, artifact tools.

This can be done as optional extras first, not separate repos immediately.

### P1 - Security posture is meaningfully hardened, but review burden remains high

Good:

- Same-origin CORS default in `server.py:105-115`.
- Security headers in `server.py:118-127`.
- Self-hosted Swagger to avoid CDN/CSP breakage in `server.py:93-102`.
- Edge CSP and header policy in `deploy/nginx.conf:28-51`.
- No inline script by policy; `unsafe-inline` remains only for style.
- Session cookies are HttpOnly/SameSite with readable CSRF double-submit design in auth tests/routes.

Risk/review burden:

- CSP still needs `unsafe-eval` for Cesium (`deploy/nginx.conf:32-46`).
- Cockpit still has many `innerHTML` insertion sites, even with escaping and tests.
- Broad use of localStorage for workspace/layout/command-authority state is intentional, but makes
  authority-state review more complex.
- Many scripts use subprocess for render/benchmark/deploy tooling. Most use argument lists rather than
  shell strings, but they increase supply-chain and path-assumption surface.
- Large generated artifacts and local worktrees near source increase accidental disclosure risk.

Recommended security streamlining:

- Centralize all HTML rendering through reviewed helpers.
- Add a static gate that counts and allowlists `innerHTML`/`insertAdjacentHTML`.
- Keep credentials and command authority out of persisted browser storage; current code does this for
  credentials, but command authority should eventually move to server/session state for live operation.
- Move runtime evidence and local datasets out of source paths.

### P1 - Tests are numerous, but the suite is harder to operate than it should be

There are 481 test files by filename match, which is strong. The downside is operational friction:
test paths span `stewie`, `dart`, `lode`, `leap`, `forge`, `scripts`, and `ros2_ws`
(`pyproject.toml:81-96`). Default pytest requires `pytest-timeout`; without the dev extra, test
collection fails on this host.

Recommendations:

- Define test tiers explicitly:
  - `unit-core`
  - `server-ui`
  - `perception`
  - `ros2-container`
  - `artifact/benchmark`
  - `full-release`
- Keep default `pytest` runnable in a fresh dev venv.
- Move slow/data-heavy tests behind markers that fetch fixtures explicitly.
- Track coverage by package boundary, not one monolithic number.

### P2 - Large modules should be split, but only after contracts are pinned

Largest source/test hotspots include:

- `stewie/server/web/assets/cockpit.js` - 6,201 lines.
- `stewie/server/index.html` - 1,547 lines.
- `lode/test_mission_planner.py` - 2,323 lines.
- `stewie/terrain/scenes.py` - 1,255 lines.
- `stewie/physics/tests.py` - 720 lines.
- `dart/dem_import.py` - 677 lines.
- `lode/planner_multivehicle.py` - 676 lines.
- `lode/planner_routing.py` - 626 lines.
- `scripts/colmap/colmap_recon.py` - 612 lines.

These are not all bad. Some are cohesive enough. The rewrite priority should follow blast radius:

1. Cockpit shell.
2. Mission planner test file.
3. Generated scene/data builders.
4. Multi-vehicle planner and route/costmap interfaces.
5. COLMAP/render scripts.

## What should not be rewritten

Do not rewrite these wholesale:

- DART perception/math modules that are already small, tested, and domain-specific.
- LODE planner primitives that have focused tests and clear behavior.
- World/twin state modules that are already append-only/provenance-aware.
- Existing security/auth tests and cookie/CSRF model.
- Existing sample-data readers and validators, unless their artifact location changes.

These should be wrapped behind explicit contracts and moved into cleaner packages, not replaced.

## Rewrite/streamline estimate

Approximate current bloat categories:

| Category | Size/scope | Action |
|---|---:|---|
| Local generated/vendor/cache bloat | ~4.9 GB working-tree overhead | delete locally / keep ignored / clean script |
| Tracked large fixtures/artifacts | ~250-280 MB | externalize most; keep tiny smoke fixtures |
| Frontend shell bloat | ~7.7k lines across cockpit JS+HTML | incremental rewrite/extraction |
| Runtime continuity gap | ROS skeletons + unconnected autonomy loop | implement thin adapters over tested modules |
| Package/dependency breadth | all extras under one project | split optional profiles/extras |
| Test-suite friction | 481 tests, broad paths | tier and mark tests |

Realistic amount that needs rewrite:

- **Full rewrite:** none of the core should be rewritten wholesale.
- **Major extraction/refactor:** about 15-25% of the active codebase, concentrated in the cockpit shell,
  runtime adapters, test organization, and artifact/data policy.
- **Data/artifact restructuring:** most of the tracked payload size, but not much code.
- **Runtime continuity work:** significant new wiring, not a rewrite of algorithms.

## Recommended execution plan

### Phase 0 - Clean local working tree policy

- Add a safe cleaner for ignored generated artifacts.
- Move generated outputs toward one ignored artifact root.
- Keep `.venv`, `.mypy_cache`, `.claude`, `desktop/dist`, `desktop/node_modules`, `datasets`, and
  root `out` out of audits/builds by default.

### Phase 1 - Externalize heavy fixtures

- Replace large tracked `samples/lunar_dem/*/*.rf32` bundles with checksum manifests and fetch scripts.
- Keep one tiny synthetic/real smoke fixture in git.
- Add CI check that rejects new large tracked binary artifacts unless allowlisted.

### Phase 2 - Frontend strangler split

- Extract `api_client`, route state, mode/profile/sensor rail, command rail, diagnostics rail, and one pane
  at a time.
- Add an allowlist gate for HTML sinks.
- Add Playwright deployed-style smoke.

### Phase 3 - Runtime contracts and ROS adapters

- Define runtime contract dataclasses/messages for `DepthObservation`, `VisualHazardObservation`,
  `ObservedMapUpdate`, `CostmapSnapshot`, `LocalizationState`, `TrajectoryCommand`,
  `CommandEligibility`, and `WorldTransaction`.
- Replace ROS skeleton nodes with thin adapters over existing DART/LODE/STEWIE modules.
- Make `desktop_sil` or `ros2_replay` the first connected profile.

### Phase 4 - Package/profile split

- Split optional extras into core/perception/planning/server/ros/dev profiles.
- Make default install lean.
- Keep heavy CV/GIS/benchmark deps out of minimal runtime.

### Phase 5 - Continuity governance

- Add architecture decision records for each boundary.
- Add generated-artifact manifest.
- Add release gate that reports tracked payload size, large-file diff, HTML sink count, and test tier status.

## Bottom line

The repository is not hopelessly bloated in tracked source code. The real issue is mixed concerns:
large fixtures in git, generated artifacts near source, a huge cockpit shell, broad package/dependency
boundaries, and runtime skeletons that lag the tested algorithms. Clean the artifact policy first,
then extract the cockpit and wire ROS/runtime contracts. That will deliver more value than a broad
rewrite.
