# Lunar Mission Systems Audit

Date: 2026-07-02
Project: STEWIE
Scope: world model, digital twin, mission planner, GIS/ArcGIS platform fit, navigation, perception, mapping, lunar surface design, operator cockpit bridge
Skills applied: `lunar-mission-systems-audit`, bridged with `frontend-review-design`

## Executive Summary

STEWIE has credible mission-system scaffolding for a lunar planning and digital twin platform. The strongest implemented areas are the typed world routes, world transaction ledger, per-site observed twin behavior, terrain view routes, route-backed navigation preview, perception route contracts, GIS body/CRS safeguards, OGC/GIS export tests, and a cockpit organized around the mission flow.

The project is not yet ready to claim an end-to-end operational lunar mission system. The key missing bridge is the live observed-world loop: camera or sensor evidence must become classified hazards, update the world model with uncertainty and provenance, affect planner costmaps/routes, gate command eligibility, and render in the cockpit as operator evidence. Today, the repo contains important algorithmic and route-level pieces, and tests pass for many components, but the live chain is still incomplete.

The second major issue is platform language. The code and UI can support a GIS-oriented planning workflow, and tests cover lunar CRS, terrain-vs-imagery labeling, OGC/WMS, and export paths. That is different from being a full ArcGIS platform unless the system supports concrete ArcGIS service contracts, authentication, editing/versioning semantics, offline packaging, and round-trip validation. The product should use precise claims until those contracts exist.

## Evidence Collected

### Runtime and frontend checks

- Browser opened: `http://127.0.0.1:8771/`
- Console errors: 0
- Mobile cockpit horizontal overflow: false at 390 x 844
- Mobile program board horizontal overflow: false at 390 x 844
- Screenshots captured for cockpit desktop, cockpit mobile, and program board mobile.

### Test runs

Frontend and bridge suite:

```text
129 passed, 2 warnings
```

Domain-heavy lunar systems suite:

```text
.venv/bin/python -m pytest \
  dart/test_hazard_map.py \
  dart/test_rock_detect.py \
  dart/test_obstacle_map.py \
  dart/test_mapping.py \
  dart/test_world_model_layers.py \
  lode/test_nav_pipeline.py \
  lode/test_gis_export.py \
  lode/test_mission_intent_compiler.py \
  lode/test_illumination_route.py \
  lode/test_terrain_delta.py \
  leap/test_siteplan.py \
  leap/test_structures.py

121 passed
```

## System Purpose Assessment

The system should be evaluated as a lunar mission planning and operations preparation platform with a digital twin. Its purpose is to let users plan, rehearse, validate, release, execute, and report lunar-surface activity using terrain, GIS, fleet, structure, perception, navigation, solar, and world-state evidence.

It should not be framed as a generic GIS viewer, a generic dashboard, or a free-form simulation toy. For mission planning, the critical user promise is not "show maps." The promise is "make a bounded, auditable, physically and operationally valid mission plan, then maintain the evidence needed to decide whether that plan can be released or executed."

## Mission-System Asset Model

The system should treat these as first-class governed assets:

- Lunar body and CRS.
- Site and mission area.
- DEM, imagery, slope, roughness, illumination, and communications layers.
- Observed-world masks and uncertainty layers.
- Terrain deltas and world transactions.
- Hazard observations, hazard maps, keep-outs, and classifier evidence.
- Fleet, vehicle capabilities, command namespace, and health.
- Navigation route, local plan, recovery plan, and covariance.
- Surface construction design: pads, berms, roads, zones, staging, materials, volumes.
- Mission intent, constraints, acceptance gates, signoffs, and release packages.
- Runtime profile: replay, simulation, hardware-in-loop, field test, live rover.
- Operator evidence: source freshness, provenance, refusal reasons, and acknowledgements.

## Findings

### P1 - Live hazard perception to world model to planner loop is incomplete

Evidence:

- `PRD.md:834` states that hazard perception algorithms are built and tested, but the live camera-to-classifier-to-map-to-planner-to-eligibility-to-cockpit chain is not connected.
- `FANOUT_SPECS.md:730` tracks FS-29 live hazard classifier UI and route integration.
- `FANOUT_SPECS.md:735` tracks PM-19 camera-to-classifier-to-map-to-planner loop closure.
- `stewie/server/web/assets/cockpit.js:941` initializes the cockpit perception pane with static perception sample assets.
- `stewie/server/web/assets/cockpit.js:958` sets the sample `source_profile` to `stereo_sgbm`.
- `stewie/server/web/assets/cockpit.js:1001` labels the evidence class as simulation.
- `stewie/server/routers/perception.py:145` exposes compare behavior.
- `stewie/server/routers/perception.py:159` exposes localize behavior.
- `stewie/server/routers/nav.py:152` includes a `/nav/react` path that can convert observed rocks to dynamic keep-outs and replanning behavior.
- Domain tests for hazard map, rock detection, obstacle map, mapping, and navigation passed.

Impact:

The project has the building blocks, but it does not yet prove the mission-critical loop: a sensor observation changes the world model, changes the planner, changes command eligibility, and appears to the operator with provenance and refusal/approval evidence. Without that proof, the system should be described as a planning and simulation scaffold, not a validated operational perception-navigation stack.

Recommendation:

Implement a typed observed-hazard pipeline:

1. `VisualHazardObservation`: source profile, image/frame id, timestamp, camera pose, classifier id, confidence, covariance.
2. `HazardMapUpdate`: projected map footprint, hazard class, uncertainty, body CRS, observed mask update.
3. `WorldTransaction`: atomic transaction that records the observation and resulting layer changes.
4. `PlannerImpact`: route/costmap delta, rejected route reason, changed keep-outs, map freshness.
5. `CommandEligibility`: whether Release/Execute is allowed, degraded, or refused.
6. `CockpitEvidence`: visible panel showing source, confidence, uncertainty, map freshness, and planner impact.

File-level work:

- Extend `stewie/server/routers/perception.py` with a hazard observation ingestion and classifier evidence route.
- Connect observed hazard updates to the world transaction path in `stewie/server/routers/world.py`.
- Ensure `stewie/server/routers/nav.py` consumes the updated observed hazard layer through a typed costmap input, not only a UI preview.
- Replace static perception evidence in `stewie/server/web/assets/cockpit.js` with route-backed live/replay/sim evidence.
- Add a cockpit panel for hazard classifier status and route impact.
- Add a test where an injected rock/hazard observation changes the returned route or marks execution ineligible.

### P1 - Product mode and runnable profile are missing from mission authority

Evidence:

- `stewie/server/web/assets/cockpit_state.js:10` only models source as `live`, `sim`, and `eval`.
- `stewie/server/web/assets/cockpit_state.js:11` only models mode as `sandbox` and `live`.
- `stewie/server/web/assets/cockpit_state.js:27` omits product mode and runnable profile from default state.
- `stewie/server/web/assets/cockpit_state.js:43` omits product mode and runnable profile from URL serialization.
- `PRD.md:842` tracks FS-25 as not done.
- `FANOUT_SPECS.md:682` tracks the same gap.

Impact:

Mission planning, GIS planning, training, simulation, hardware-in-loop, evaluation, and live operations have different safety envelopes. If the system cannot carry the selected runtime profile across frontend, backend, release, execute, and reports, it cannot make robust authority claims.

Recommendation:

Define a mission authority tuple:

```text
body + site + mission + productMode + runnableProfile + sourceClass + vehicle + role + commandNamespace
```

Then require that tuple in:

- URL state.
- Release package.
- Execute request.
- World transaction metadata.
- Report output.
- Admin audit log.

This is the bridge between frontend design and lunar mission assurance.

### P1 - World model is improved, but unified layer contracts are still incomplete

Evidence:

- `stewie/server/routers/world.py:30` exposes `/world` as a rich descriptor.
- `stewie/server/routers/world.py:53` calculates observed fraction from the twin observed mask.
- `stewie/server/routers/world.py:80` exposes world transaction routes.
- `stewie/server/routers/world.py:124` exposes current terrain view metadata.
- `stewie/server/routers/world.py:140` exposes current terrain view PNG.
- `PRD.md:838` marks atomic world state transactions as done.
- `PRD.md:839` marks per-site/source observed twin behavior as done.
- `PRD.md:841` marks `/world` rich descriptor as done.
- `FANOUT_SPECS.md:380` tracks TW-05 unified material/traversability/observed/uncertainty layer requirements.
- Tests for world state service, world transaction atomicity, per-site twin, current terrain view, and world model layers passed.

Impact:

The world routes and tests show meaningful progress. The remaining risk is whether the world model contract is rich enough for a mission planner to reason over materials, traversability, observation state, uncertainty, provenance, and freshness at the layer level. A scalar descriptor is useful for UI summaries, but mission planning needs layer manifests that downstream planning and acceptance gates can consume consistently.

Recommendation:

Add a layer manifest contract to the world descriptor.

Minimum fields:

- Layer id.
- Layer type: DEM, imagery, slope, roughness, material, traversability, observed mask, uncertainty, hazard, illumination, communications.
- Body CRS.
- Site bounds.
- Resolution.
- Source.
- Provenance.
- Timestamp and freshness.
- Uncertainty model.
- Validity mask.
- Transaction id.
- Consumer eligibility: display, planning, release, execute.

File-level work:

- Extend the world response model used by `stewie/server/routers/world.py`.
- Add fixtures that prove material/traversability/observed/uncertainty layers are discoverable and typed.
- Make planner costmap construction consume the same layer manifest used by the cockpit.

### P1 - Planner consumption of observed-world deltas needs an end-to-end gate

Evidence:

- `stewie/server/routers/nav.py:49` exposes local planning.
- `stewie/server/routers/nav.py:152` exposes `/nav/react` with dynamic keep-outs and replanning behavior.
- `stewie/server/routers/nav.py:200` exposes `/nav/run` preview behavior over terrain.
- `FANOUT_SPECS.md:745` tracks RS-02: planner consumes observed world.
- Domain navigation and terrain delta tests passed.

Impact:

The planner can preview and react, but the audit needs a stronger invariant: when the observed world changes, the planner's costmap and route decision change in a way that can be proven, displayed, and audited. This is especially important for lunar terrain where updated rocks, slopes, trenches, berms, and regolith disturbances can invalidate a route.

Recommendation:

Create an explicit observed-world-to-planner acceptance test:

- Start with a known DEM and route.
- Inject an observed hazard or terrain delta.
- Commit it through a world transaction.
- Rebuild the costmap from the world layer manifest.
- Prove the route changes, is refused, or records a justified unchanged result.
- Render the planner impact in the cockpit and release evidence.

File-level work:

- Add or extend planner tests under `lode/`.
- Add a server integration test that touches world transaction plus nav route.
- Add a cockpit fixture showing "route changed because observed hazard X entered leg Y."

### P1 - GIS/ArcGIS platform claims need stricter boundaries

Evidence:

- `stewie/server/index.html:87` comments describe GIS/ArcGIS functionality in broad terms.
- `stewie/server/test_gi02_body_crs.py` passed.
- `stewie/server/test_gis03_globe_guard.py` passed.
- `stewie/server/test_gis_export.py` passed.
- `stewie/server/test_ogc_wms.py` passed.
- `lode/test_gis_export.py` passed.
- `FANOUT_SPECS.md:472` tracks GI-02 body-aware CRS behavior.
- `FANOUT_SPECS.md:480` tracks GI-03 globe and CRS guard behavior.

Impact:

The project supports important GIS-oriented behavior: lunar CRS awareness, terrain-vs-imagery labeling, export, WMS/OGC handling, and guardrails against Earth-globe assumptions. That is strong for a lunar planning application. It is not enough evidence to claim full ArcGIS platform support unless the project implements and tests concrete ArcGIS service contracts.

Recommendation:

Use precise language:

- Acceptable now: "GIS-oriented lunar mission planning", "OGC/WMS and export support", "body-aware CRS", "ArcGIS-compatible planning concepts where implemented."
- Avoid for now: "ArcGIS fully functional" or "ArcGIS platform complete."

To support a stronger ArcGIS claim, add contracts and tests for:

- ArcGIS Feature Service read/query.
- ArcGIS Feature Service edit or sync where required.
- ArcGIS authentication/token handling.
- Feature layer schema mapping.
- Attachments or evidence artifacts if used.
- Offline package import/export if required for mission planning.
- CRS and vertical datum handling for lunar bodies.
- Round-trip validation from STEWIE asset to ArcGIS layer and back.

File-level work:

- Replace broad UI comments or labels with narrower language until contracts exist.
- Add an ArcGIS integration adapter boundary instead of mixing ArcGIS assumptions into generic GIS code.
- Add fixtures for each supported ArcGIS service shape.

### P1 - Lunar surface design needs observed before/after volume and uncertainty evidence

Evidence:

- `leap/test_siteplan.py` passed.
- `leap/test_structures.py` passed.
- `FANOUT_SPECS.md:292` tracks ML-06 regolith volume estimation from observed before/after data with uncertainty and drum cross-check.

Impact:

Surface design is not only drawing pads, berms, and roads. For lunar construction, the design must carry material movement, volume estimates, uncertainty, and after-action verification. Without observed before/after volume evidence, the system cannot close the loop between planned surface design and actual terrain changes.

Recommendation:

Add a `RegolithVolumeEstimate` contract:

- Structure or work-order id.
- Before terrain source.
- After terrain source.
- Change mask.
- Estimated cut/fill.
- Uncertainty.
- Drum/load cross-check.
- Conservation residual.
- Confidence class.
- Acceptance status.
- Linked world transaction.

File-level work:

- Extend LEAP structure/siteplan outputs with volume evidence.
- Connect before/after terrain views to world transactions.
- Add cockpit/report rendering for volume acceptance and uncertainty.
- Add tests using synthetic before/after terrain deltas.

### P2 - Navigation preview is strong, but live autonomy binary integration remains gated

Evidence:

- `stewie/server/routers/nav.py:25` exposes a navigation contract.
- `stewie/server/routers/nav.py:49` exposes local planning.
- `stewie/server/routers/nav.py:104` exposes fault and executive safety decision paths.
- `stewie/server/routers/nav.py:200` exposes `/nav/run` route preview behavior.
- `FANOUT_SPECS.md:62` describes the on-host navigation spine as done, with live planner binary execution gated.
- Navigation pipeline tests passed.

Impact:

This is acceptable for a planning/digital-twin system, but product language and UI controls must make clear that this is preview/rehearsal unless the selected runnable profile proves a live autonomy integration is active and authorized.

Recommendation:

Keep the navigation pane explicit about preview vs live execution. For any future live profile, require runtime namespace, watchdog state, command envelope, and acknowledgement evidence before enabling controls.

### P2 - Observability and traceability should become mission evidence, not just ops telemetry

Evidence:

- `FANOUT_SPECS.md:156` tracks FS-19 observability ledger as partial.
- `FANOUT_SPECS.md:172` tracks FS-23 architecture traceability ledger as partial.
- World transactions and report panes exist, but not every mission decision is yet represented as an evidence object.

Impact:

Mission planning auditability depends on explaining why a plan was accepted, changed, rejected, released, or executed. Logs alone are not enough; decisions need typed evidence linked to assets.

Recommendation:

Define mission evidence records for:

- Route accepted/rejected.
- Hazard detected/ignored.
- Surface design accepted/rejected.
- Release gate passed/failed.
- Command authority granted/refused.
- World model transaction committed/rolled back.

Each record should link to source assets, source freshness, provenance, operator, product mode, runnable profile, and transaction id.

## ArcGIS/GIS Platform Design Recommendation

Use a layered architecture:

1. Mission GIS core: body-aware CRS, DEM, imagery, vector features, hazards, routes, structures, observations.
2. OGC adapters: WMS/WMTS/COG/GeoJSON and existing export paths.
3. ArcGIS adapter: explicit Feature Service, Scene/Tile service, authentication, feature schema, edit/sync, and offline package support where needed.
4. Cockpit asset registry: user-facing layer catalog with source, freshness, uncertainty, and planning eligibility.
5. Planner bridge: costmap and constraint generation from the same layer manifests shown in the cockpit.

Do not let the frontend imply that a layer is planning-valid just because it can be displayed. Every layer should have display eligibility and planning eligibility as separate fields.

## Digital Twin Design Recommendation

The digital twin should be organized around immutable transactions and typed layer manifests:

- Immutable world transactions record every committed observation, terrain delta, design edit, and plan-impacting update.
- Mutable views, such as current terrain view, are derived products with source transaction ids.
- Planning consumes derived views only when their freshness, uncertainty, and provenance meet the selected runnable profile policy.
- Cockpit displays the same transaction and layer evidence used by the planner.

## Mission Planner Design Recommendation

The planner should move from "route preview with rich context" toward "evidence-producing mission compiler."

Each planning run should produce:

- Input layer manifest.
- Intent and constraints.
- Solver version.
- Cost model.
- Accepted route.
- Rejected alternatives.
- Hazard and keep-out summary.
- Energy/illumination/communications assumptions.
- Uncertainty summary.
- Release eligibility.
- Explanation suitable for the cockpit and report.

## Concrete Next Changes

1. Implement the observed-hazard pipeline from perception to world transaction to planner impact to cockpit evidence.
2. Add product mode and runnable profile to mission authority, URL state, release, execute, reports, and audit logs.
3. Extend `/world` with typed layer manifests for material, traversability, observed mask, uncertainty, hazards, and freshness.
4. Add an end-to-end test proving observed-world deltas affect planner output or command eligibility.
5. Narrow GIS/ArcGIS UI claims until explicit ArcGIS contracts and tests exist.
6. Add regolith before/after volume estimation with uncertainty and drum/load cross-check.
7. Promote mission evidence records to first-class artifacts in reports and admin audit.

## Verification Notes

The audit used local code inspection, live browser checks, mobile viewport checks, frontend test suites, backend bridge tests, and domain tests across DART, LODE, and LEAP. It did not validate current Esri product behavior or external ArcGIS service compatibility against live Esri documentation or services; the ArcGIS recommendations are therefore architecture recommendations based on the repository evidence, not a certification of current ArcGIS platform support.
