# STEWIE QGIS/QWC2 Current-State Review

**Date:** 2026-07-09  
**Scope:** public QWC2 `/ide/`, QGIS Server/QGIS project boundary, PRD alignment, mission-panel HCI, and Graphify.  
**Method:** source/configuration review; local and public Playwright browser checks; QGIS/QWC2 test execution; three independent LLM-council passes (mission/GIS, frontend/HCI, platform/reliability). Council statements are corroborated below by cited code/configuration and clearly separated from declared roadmap gaps.

## Decision Summary

Do **not** treat `/ide/` as an operable public mission workbench today. Two production findings must be resolved before any workflow or UX completion work:

1. **P0 public GIS outage:** generated QWC2 theme URLs direct a public browser to `http://localhost:8082/ows`, rather than the deployed same-origin `/ows/` proxy. The public browser consequently blocks/does not render the lunar map, even though the QGIS proxy itself is healthy.
2. **P0 public privilege escalation:** public nginx injects a director-equivalent key into the browser-facing execution route without enforcing the documented interim access gate. A successful request can mutate shared simulated world state.

The underlying GIS foundation is real: QGIS has lunar CRS/data fidelity, and the QWC2 mission modules have substantial test coverage. The failure is the deployed edge/configuration and the mismatch between the PRD's unified lifecycle context and the current collection of panels.

## Confirmed Production Findings

### P0 - public QWC2 bypasses the working QGIS proxy

- The public `themes.json` and `themesConfig.json` advertise `http://localhost:8082/ows/...`, while nginx exposes QGIS Server to the browser at same-origin `/ows/`. See [themes.json](../gis/qwc2/static/themes.json), [themesConfig.json](../gis/qwc2/static/themesConfig.json), and [artemis-nginx.conf](../deploy/artemis-nginx.conf).
- Independent public Playwright checks on desktop and 390px mobile found a blank map, no usable lunar tile/canvas, and mixed-content/private-network/CORS failures after selecting the lunar theme. The public `/ows/?...GetCapabilities` endpoint itself returned valid IAU_2015:30135 capabilities.
- This fails QW-01's deployed browser criterion and prevents GL-01/GW-05 from being credibly claimed in the product. See [PRD.md](../PRD.md).

**Required recovery:** restore relative `/ows/?MAP=...` URLs in both theme sources/generated artifacts; rebuild `gis/qwc2/prod`; deploy an immutable build; then require a public Playwright smoke that asserts no `localhost` requests, a nonblank IAU_2015:30135 map, `GetMap` and `GetFeatureInfo` success, and zero blocking console errors at desktop and 390px.

### P0 - unauthenticated public execution is proxy-authorized as director

- The compose stack mounts an htpasswd file, but the active nginx configuration has no `auth_basic` enforcement. See [compose.yml](../deploy/compose.yml) and [artemis-nginx.conf](../deploy/artemis-nginx.conf).
- The `/api/executive/run` proxy injects the shared server API key. The backend resolves that key to director authority, and the route persists run records plus world, terrain, traffic, and belief-state transactions. See [artemis-nginx.conf](../deploy/artemis-nginx.conf), [auth.py](../stewie/server/auth.py), and [executive.py](../stewie/server/routers/executive.py).
- Council verification reached application validation with an unauthenticated public POST instead of receiving 401/403. This remains SIM-only; it does **not** open the real-vehicle gate. It does, however, violate role separation, attribution, and the UI's non-destructive implication.

**Required recovery:** remove the injected credential from every browser-facing mutation route immediately, or make the entire IDE access-controlled at the edge. Use authenticated sessions plus server-side role checks and CSRF protection. If a public demonstration is required, point it to an isolated disposable world namespace rather than shared simulation state.

## QGIS/QWC2 Current State

### What is working

- The QGIS project is lunar-native: IAU_2015:30135, lunar sphere, source COGs, site vectors, and QGIS Server WMS are present. The public same-origin WMS proxy responds; this is not a QGIS Server availability outage.
- `QT_QPA_PLATFORM=offscreen /usr/bin/python3 gis/test_project.py` completed **8/9** gates. All CRS, COG sampling, pole rendering, WMS connection, and site-vector checks passed. The sole failure is a stale group-order assertion: the test demands that South Polar Basemap be bottom-most even though the builder intentionally appends Global South Basemap below it. See [test_project.py](../gis/test_project.py) and [build_project.py](../gis/build_project.py).
- `node --test gis/qwc2/js/**/*.test.js` passed **203/203** pure mission-module tests. This is valuable unit coverage, but it does not exercise a browser through nginx into QGIS.

### What is incomplete by design, not a newly discovered defect

- GW-05 remains open: the primary 2D theme has no Trek background; Trek is used only by Whole Moon. See [PRD.md](../PRD.md), [themesConfig.json](../gis/qwc2/static/themesConfig.json), and [wholeMoonGlobe.js](../gis/qwc2/js/mission/wholeMoonGlobe.js).
- QG-01/QG-03 are still limited to terramechanics and sample-point processing; the PRD does not claim full processing integration.
- ROS/physical dispatch remains gated and SIM-backed. The above execution finding is a shared-SIM authorization defect, not evidence of an open hardware control path.

## PRD Trace

| Requirement | Observed status | Evidence / consequence |
|---|---|---|
| QW-01 deployed QWC2 workbench | **Failed in public browser** | Theme selection cannot consume its WMS due to `localhost` URLs. |
| GW-02 unified workspace | **Partial / materially insufficient** | Current workspace holds `site`, `body`, `mission`, `profile`, `source`; plans/runs still hard-code Moon. It lacks CRS, fleet, selection, layers, authority, revision, run, release, and branch binding. See [workspace.js](../gis/qwc2/js/mission/workspace.js) and [planAuthor.js](../gis/qwc2/js/mission/planAuthor.js). |
| GW-05 imagery + local DEM | **Open as stated** | No Trek 2D background, and public QWC2 cannot currently reach the intended WMS. |
| GW-07 selection inspector | **Partial** | Readout/provenance behavior exists, but action-looking controls are nonsemantic/no-op. See [SelectionInspector.jsx](../gis/qwc2/js/plugins/SelectionInspector.jsx). |
| LY-03 lunar CRS enforcement | **Failed / bypassable** | WGS84 options remain visible; CRS-less GeoJSON is accepted as lunar; stock LayerTree import bypasses MissionUserLayer validation. See [config.json](../gis/qwc2/static/config.json) and [userLayers.js](../gis/qwc2/js/mission/userLayers.js). |
| LY-07 / world terrain truth | **Partial** | Planning composes `CurrentTerrainView`, but the primary QGIS map serves raw COG DEMs rather than the evolving as-built/current terrain view. See [state.py](../stewie/server/state.py), [executive.py](../stewie/server/routers/executive.py), and [gis_layers.py](../stewie/server/gis_layers.py). |
| RT-04 runtime diagnostics | **Partial** | HUD/engineering panels are appropriately evidence-only, but do not supply the PRD's full diagnostic/costmap/robot-model surface. |
| Lifecycle topology | **Partial** | Menu is Plan, Validate, Release, Execute, Report, Settings. The PRD's Rehearse stage is absent, and Release is a read-only runtime catalog rather than a decision/refusal gate. |
| 2D-only architecture pivot | **Contradicted** | Whole Moon loads full-screen Cesium, despite the PRD pivot stating that the product does not use a Cesium globe. Resolve this through an ADR or remove it. See [WholeMoon.jsx](../gis/qwc2/js/plugins/WholeMoon.jsx) and [PRD.md](../PRD.md). |

## Visual Tool And Layout Review

The local IDE renders a map-first surface with restrained dark chrome, a right-side lifecycle menu, and a consistent sidebar frame. This is a workable operator-shell pattern. It cannot compensate for the public map outage. Screens inspected locally included the lifecycle menu, Mission Layers, Mission Plan, Inspector, and Cross-section; public desktop/mobile checks supplied the deployment verdict.

| Menu | Tool | Current visual/interaction assessment | Recommendation |
|---|---|---|---|
| Plan | Whole Moon | Polished globe/dive interaction, but Cesium conflicts with the 2D pivot. | Record and approve an architecture exception, or remove from the core workflow. |
| Plan | Mission Layers | Strong provenance/eligibility vocabulary; 65-layer tree is extremely dense with 8-11px metadata and chips. | Add layer search, saved filters, semantic group toggles, and progressive disclosure. |
| Plan | User Layer | Separate input affordance is good; its CRS policy can be bypassed. | Disable stock import and require explicit lunar CRS for CRS-less data. |
| Plan | Mission Plan | Substantive constructability/fleet/compare/SIM evidence. The pane is a long scroll mixing authoring, safety, scheduling, and execution. | Split into Author, Safety, Optimize, Rehearse stages; place evidence beside the selected template. |
| Validate | Inspector | Clear empty state and provenance intent, but action-looking controls do not execute. | Use real buttons that route through the shared workspace, or disabled buttons with refusal reasons. |
| Validate | Cross-section | Honest point-pair empty state and compact result surface. | Keep; make the start/end selection state unmistakable and keyboard-accessible. |
| Validate | Terrain 3D | Useful analytical intent, but the public base map blocks it and 3D posture needs reconciliation with the 2D decision. | Keep only as a bounded analytic view with a documented data/authority contract. |
| Validate | Terramechanics | Correct analytical placement; visible outcome depends on selected terrain/site state. | Bind every result to selected DEM revision, profile, and freshness. |
| Release | Runtime Context | Read-only profile display, not a release control or eligibility decision. | Replace with revision-bound readiness summary, authority, blockers, and a release/refusal transition. |
| Execute | Rover HUD | Honest evidence-only status; not represented as live autonomy. | Preserve that honesty; show source time/freshness and an explicit SIM-only banner. |
| Execute | Eng Panel | Similar evidence-only posture; current diagnostics remain partial. | Keep out of the critical path until RT-04 data surfaces exist. |
| Report | Evidence / Report | Useful provenance/report frame but dense at narrow widths. | Use collapsible sections and evidence filters; expose export only for actual persisted evidence. |
| Report | Program | Appropriate program-level view. | Bind to selected mission/revision instead of global/default state. |
| Report | Asset Library | Good catalog/provenance start; recovery appears as status, not an action. | Add real recovery workflow, error state, and authority checks. |

Stock QWC2 Editing, FeatureForm, AttributeTable, Redlining, search/bookmark services, and Earth Valhalla routing should be removed or disabled until each has a live lunar-specific contract. They currently expose dead `localhost:8088` services and inappropriate Earth workflow affordances. The current page also disables user zoom and uses click-only `div`/`span` controls in several panels. Add semantic buttons, focus states, Escape/focus management, 44px mobile targets, and user zoom before treating the interface as field-operable.

## Delivery And Verification Gaps

1. `gis/qwc2/prod` is ignored and bind-mounted by nginx; compose does not build or validate it. Current browser bytes can therefore differ from `HEAD`, as this incident demonstrates. Build QWC2 in CI into a commit/hash-stamped immutable artifact or image.
2. CI runs QWC2 pure Node tests, while browser smoke covers the separate cockpit. Add QWC2 public-edge tests for map pixels, WMS CRS/tile/feature-info, console errors, mobile, and exact proxy/auth behavior. See [ci.yml](../.github/workflows/ci.yml).
3. Add an unauthenticated mutation-rejection test for every nginx-exposed API route, especially `/api/executive/run` and edit-session endpoints.
4. Fix the stale QGIS group-order assertion and update the README count from its obsolete 8/8 claim.

## Graphify Update And Recommendations

Completed during this review:

- Rebuilt the deterministic AST graph from 1,546 extracted files: **23,860 nodes**, **48,466 edges**, and **920 communities** after re-clustering.
- Regenerated `graphify-out/GRAPH_REPORT.md` and the published [knowledge-graph.html](../docs/knowledge-graph.html). The report no longer contains the July 4 topology counts.
- The published graph remains an aggregated 920-community view because the full graph exceeds the browser visualization threshold.

Known Graphify hygiene issues:

- `manifest.json` remains from July 4 because the repository's AST rebuild script does not regenerate the CLI manifest. Consolidate around one supported rebuild entry point so graph/report/manifest share a commit and timestamp.
- The code graph is vendor-heavy: Swagger UI, OpenLayers, and Three bundles dominate hubs. Add a project `.graphifyignore` for vendored/generated artifacts and retain a separate full graph only when needed for supply-chain analysis.
- `scripts/export_stewie_interaction_graph.py` also writes `graphify-out/graph.json`, colliding with the canonical AST graph. Give the interaction graph its own stable output name and explicitly link it from the code graph rather than overwriting it.
- Add operational boundary nodes/edges that source-only extraction cannot infer: `QGISProject -> QgisServerWMS -> QWC2Map` (**broken publicly**), `CurrentTerrainView -> QWC2Map` (**partial**), `WorkspaceContext -> mission panels` (**partial**), `BrowserIdentity -> nginx -> ExecutiveRun` (**unsafe**), and `EditSession -> PlanRequest -> PlanResult`.

## Recommended Order Of Work

1. Contain the public execution route and require real edge/browser identity before any more deployment.
2. Restore same-origin WMS URLs, rebuild/deploy QWC2, and prove desktop/mobile browser render through nginx.
3. Make the QWC2 artifact reproducible and make public browser smoke a release gate.
4. Establish one persisted, revision-bound workspace context; make Release a real decision gate; add the missing Rehearse stage.
5. Close lunar CRS import bypasses and make `CurrentTerrainView` the primary operator map layer.
6. Restructure dense panels, eliminate false action affordances, and complete keyboard/mobile operation.
7. Separate and formalize code versus interaction Graphify outputs, then add the deployment/authority edges above.

## Council Record

- **Mission/GIS:** validated the QGIS/QWC2 WMS boundary, lunar CRS/data status, PRD gaps, and QGIS tests.
- **Frontend/HCI:** performed public desktop/mobile visual checks plus panel/layout analysis.
- **Platform/reliability:** validated deployment reproducibility, proxy identity, state mutation, and test coverage.

All three independently converged on the public WMS misrouting and the execution-route authorization defect.
