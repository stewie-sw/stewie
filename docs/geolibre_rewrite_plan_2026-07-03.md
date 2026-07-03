# STEWIE GeoLibre-Style Frontend Rebuild Plan

Date: 2026-07-03

Scope: planning only. This document assumes Aaron's locked decisions: React/TypeScript + MapLibre GL JS + deck.gl + DuckDB-WASM Spatial + Tauri v2; Python FastAPI remains the sidecar; the map is 2D only; physics engines and body profiles become first-class extension seams.

## Reconciliation (Claude + Codex, 2026-07-03)

This plan was produced by conferring. Codex ran a max-reasoning, code-grounded pass (the body below, cited at file:line); Claude ran an independent pass in parallel (`scratchpad/claude_geolibre_plan.md`). The two agree on the architecture. Recorded here: the agreements, the reconciled decisions where they differed, and the binding constraints.

**Agreed independently by both:** two-process split (Python backend UNCHANGED as the FastAPI sidecar; React frontend is the only rewrite); 2D map, no globe, local order frame in metres; DuckDB-WASM over the FR-10 manifest as the one real GeoLibre gain; a generated OpenAPI client for the 140 routes; the two extensibility seams (PhysicsBackend + BodyProfile); the FR-10 manifest as the single layer authority; strangler-fig with the vanilla cockpit live until pane-by-pane parity; the physics/body foundation landing before the panes that display backend/body evidence; strict non-fabrication (BodyProfile null+provenance, Chrono as geometry-oracle NOT release-eligible until it conserves mass).

**Reconciled decisions (where the two passes differed):**

1. **Lane codes must be 2-letter + 2-digit.** The matrix parser (`scripts/req_trace.py` `_ROW`, regex `[A-Z]{2}-\d{2}`) and the /program board REJECT 3-letter codes. Codex's `API-`/`BOD-`/`TAU-`/`MIG-` are remapped: **RF** (React frontend shell + panes), **GL** (GeoLibre 2D map workbench), **DW** (DuckDB-WASM), **AC** (API client + route coverage), **PX** (physics-backend extension), **BD** (body-profile registry), **TU** (Tauri desktop + sidecar), **MG** (strangler migration governance). Required, not cosmetic.

2. **Rendering: MapLibre-primary (Codex) vs deck.gl OrthographicView-primary (Claude).** Both make it the Phase-2 spike + kill-gate. DECISION: the spike tries **MapLibre in local-projected mode first** (GeoLibre-faithful, reuses its stack); if MapLibre's Earth/WebMercator orientation fights the local metres frame, fall back to **deck.gl OrthographicView** (non-geo, no projection) with MapLibre only for optional lon/lat basemap. Same kill-gate either way: Haworth DEM renders non-blank + control points round-trip through `/dem/site_xy` / `/dem/site_lonlat` within tolerance, with no WGS84 claim on lunar coordinates.

3. **Physics/body foundation sequencing.** Codex places it at Phase 3 (after the map kill-gate); Claude placed it first (independent, low-risk, delivers the extensibility ask early). RECONCILED: run the **PX + BD backend refactor as an INDEPENDENT PARALLEL BACKEND TRACK**. It is not gated on the UI rewrite and it benefits the CURRENT vanilla cockpit too, so it can start immediately and land regardless of whether the UI rewrite clears its Phase-2 gate. Codex's ordering constraint still holds ("before the panes that display backend/body evidence") but it is not blocked behind the map spike.

4. **Effort: 7-12 months for the full program (Codex), not 3-5 months.** Claude's 3-5 months was the pane rewrite only; the full program (2D map + API client + DuckDB + Tauri + PhysicsBackend + BodyProfile + 13 panes) is the larger figure. Adopted.

**Note on priorities:** the rewrite is a new initiative, so it introduces NEW P0 rows (AC/RF/GL/PX/BD/MG foundations). The current board's "all P0 complete" refers to the pre-pivot backend/cockpit scope; the pivot re-opens P0 with the rebuild foundations. This is honest and expected.

Binding acceptance constraints are in §5 below. The PRD (§6 Target Architecture; §7 lanes RF/GL/DW/AC/PX/BD/TU/MG; roadmap) is rewritten from this plan.

---

## 0. Grounding Snapshot

Confirmed from the tree:

- The earlier assessment frames "GeoLibre" as a frontend migration: the Python DART/LODE/LEAP/FORGE core and FastAPI API stay intact behind a sidecar, while the cost is the cockpit rewrite and map migration (`docs/geolibre_migration_assessment_2026-07-03.md:8-18`, `docs/geolibre_migration_assessment_2026-07-03.md:30-34`).
- That same assessment measured the frontend work: `cockpit.js` is 6,321 LOC, `index.html` is 1,599 LOC, the ConOps pane set is STEWIE-specific, and GeoLibre supplies none of those mission-ops panes (`docs/geolibre_migration_assessment_2026-07-03.md:13-14`, `docs/geolibre_migration_assessment_2026-07-03.md:42-45`, `docs/geolibre_migration_assessment_2026-07-03.md:58-62`).
- The main previous risk was lunar/non-Earth CRS in Cesium -> MapLibre/deck; 2D polar/projected lunar map is now accepted, which removes the hardest 3D-globe requirement but not every CRS/frame risk (`docs/geolibre_migration_assessment_2026-07-03.md:50-56`).
- A React+Vite rewrite was previously reverted at `55c44c6` after a Cesium init black screen; the documented lesson was "strangler-fig the vanilla cockpit" rather than big-bang rewrite (`docs/geolibre_migration_assessment_2026-07-03.md:20-22`, `PRD.md:154-165`, `PRD.md:1677-1681`).
- The backend is already routerized. `stewie/server/server.py` imports and includes 35 router modules plus app-level routes (`stewie/server/server.py:129-200`). `ls stewie/server/routers/` shows 36 files including `__init__.py`. Command inventory found 140 `@router.*` route decorators in `stewie/server/routers/*`, 145 total route decorators when `server.py` app routes are counted, and 146 FastAPI app routes when the generated `/openapi.json` route is included. The assessment's "140 API routes (36 routers)" is therefore correct for router-owned API routes (`docs/geolibre_migration_assessment_2026-07-03.md:40-41`).
- The current frontend loads self-hosted Cesium before the cockpit scripts (`stewie/server/index.html:19-25`) and then loads many extracted pure modules plus `cockpit.js` (`stewie/server/index.html:1560-1597`). The assets directory currently contains 41 non-test JS modules and 38 top-level `*.test.js` files.
- The current ConOps/work-area shell is DOM-first: the top tabs are Plan, Rehearse, Validate, Release, Execute, Report, plus role-gated Fleet, Construction, Models, Trainer and account-menu Settings/System/Admin (`stewie/server/index.html:811-890`). `cockpit.js` maps those names to pane IDs in `VIEW_PANE` (`stewie/server/web/assets/cockpit.js:803-814`) and drives `setView`/pipeline state (`stewie/server/web/assets/cockpit.js:894-972`, `stewie/server/web/assets/cockpit.js:6122-6270`).
- FR-10 already exists: `/world` returns `layer_manifest` from `LayerManifest.for_world(...)` (`stewie/server/routers/world.py:30-81`), and `LayerManifest`/`WorldLayer` already carry layer id/type, CRS/body, bounds, resolution, source/provenance, freshness, uncertainty, validity, transaction id, and display/planning/release/execute eligibility (`stewie/contracts/__init__.py:443-517`).
- Current body support is a constant dictionary plus helpers, not a plugin system. `Body` fields are `name`, `label`, `g`, `bekker_regime`, `bulk_density`, `cohesion_pa`, `friction_deg`, `repose_deg`, `bekker`, `confidence`, `g_note`, `role`, `provenance`, `ellipsoid_radius_m`, and `crs` (`stewie/specs/bodies.py:32-49`). Built-ins include Moon, Mars, Ceres, Bennu, Phobos, Earth, and `bp1_testbed` (`stewie/specs/bodies.py:51-135`). `params_for_body` refuses microgravity Bekker calculations unless `allow_analog=True` (`stewie/specs/bodies.py:157-175`).
- The current Tier-2 terramechanics authority is function/config based: `TerramechanicsParams` is JSON-serializable (`stewie/physics/terramechanics.py:52-113`); `static_wheel_load_n`, `wheel_static_sinkage`, `physical_compaction_field`, `physical_compaction_target_density`, `lyasko_reduce`, and `domain_randomize` are the load/sinkage/compaction/calibration functions (`stewie/physics/terramechanics.py:124-135`, `stewie/physics/terramechanics.py:171-199`, `stewie/physics/terramechanics.py:235-299`, `stewie/physics/terramechanics.py:305-337`, `stewie/physics/terramechanics.py:346-364`).
- Static structural bearing is already separate in FORGE via `ultimate_bearing_capacity_pa` and `allowable_bearing_pa` (`forge/bearing.py:1-27`, `forge/bearing.py:50-66`).
- Chrono SCM is not a complete backend today. `scripts/chrono_scm_export.py` is explicitly a STUB; it can source heightmap/disturbance/state labels from SCM, while mass_areal/density/ice stay surrogate-side placeholders because SCM does not conserve/expose areal mass (`scripts/chrono_scm_export.py:2-33`, `scripts/chrono_scm_export.py:115-147`, `scripts/chrono_scm_export.py:193-216`).
- `PlanRequest` already accepts `body`, `vehicles`, `site`, and slope/charger constraints, but no physics backend id (`stewie/server/routers/plan.py:82-95`). `mission_from_dict` validates `body` and optional `soil` against `bodies.py` (`lode/planner_model.py:284-310`). `plan_context` already makes body gravity affect flat drive energy (`lode/planner_model.py:70-90`), and `mission_soil_params` resolves the soil/body terramechanics params (`lode/planner_model.py:256-260`).

Inferred / needs confirmation:

- The final React app can be served at `/app2` or `/geo` during strangler migration; no such route exists today. Confirm by choosing a deployment path in an ADR before implementation.
- The sidecar in Tauri can launch the existing `stewie-serve`/uvicorn entry point; that is consistent with the current server entry point but requires Tauri process-supervision design.
- DuckDB-WASM can operate over the FR-10 manifest and mission-package files without backend changes for read-only analysis; write-back/edit semantics need a separate contract.

## 1. Target Architecture

### 1.1 High-Level Runtime Shape

Target stack:

```text
Tauri v2 desktop shell
  -> React 18/19 + TypeScript app
     -> MapLibre GL JS 2D projected map (no globe)
     -> deck.gl overlay layers for routes, orders, keep-outs, hazards, fleet tracks, observations
     -> DuckDB-WASM Spatial query engine over FR-10 layer manifest + mission packages
     -> Generated API client over FastAPI /openapi.json + typed route registry
  -> Python FastAPI sidecar (existing stewie.server.server:app)
     -> 140 existing router-owned API routes reused
     -> new small extension endpoints for PhysicsBackend + BodyProfile registries
     -> existing DART/LODE/LEAP/FORGE/physics code unchanged except the extension seams
```

The frontend rewrite is not allowed to rewrite or bypass the backend's authority. The PRD already states reports, Plan IR, playback, validation, and autonomy are views over single-source runtime artifacts (`PRD.md:448-468`), and §6.2 states conserved terrain mutation and observed-twin events are layered rather than overwritten (`PRD.md:470-495`). The React app must preserve that: client state may author intent and view results, but physics mutations still happen only through the backend authority path.

### 1.2 React Frontend Layers

Proposed package layout:

```text
frontend/
  package.json
  tsconfig.json
  vite.config.ts
  src/
    app/
      App.tsx
      routes.tsx
      Shell.tsx
      auth.ts
      queryClient.ts
      state.ts
    api/
      generated/              # generated from /openapi.json
      stewieClient.ts          # fetch wrapper: baseUrl, cookies/CSRF/API key, errors
      routeRegistry.ts         # all route-to-pane/API coverage metadata
      schemas.ts               # generated or zod mirror for route fixtures
    contracts/
      bodyProfile.ts
      physicsBackend.ts
      layerManifest.ts
      mission.ts
      provenance.ts
    map/
      MapWorkbench.tsx
      mapProjection.ts
      mapLayers.ts
      deckLayers.ts
      identify.ts
      measurement.ts
      editSession.ts
    data/
      duckdb/
        engine.ts
        manifestLoader.ts
        spatialQueries.ts
        queryResults.ts
    panes/
      plan/
      rehearse/
      validate/
        navigation/
        perception/
        solar/
      release/
      execute/
      report/
      fleet/
      construction/
      models/
      trainer/
      admin/
      settings/
      system/
    components/
      provenance/
      authority/
      command/
      layout/
      charts/
      forms/
      tables/
    tests/
      fixtures/
```

State management choice:

- Use TanStack Query for server state, route-backed cache invalidation, loading/error/empty states, and optimistic safety around mutation routes. This replaces ad-hoc fetch/read state in `cockpit.js`; current route-backed panes fetch directly in functions such as Fleet/Construction/Models/Trainer loaders (`stewie/server/web/assets/cockpit.js:1164-1328`).
- Use Zustand for local UI/workspace state: active pane, selected body/site/mission, current product mode/runnable profile, selected map layer, edit session, drawer/sheet state, and unsaved authoring draft. This is a good fit because current `cockpit_state.js` is a small global routeable state model loaded before `cockpit.js` (`stewie/server/index.html:1594`) and because PRD FS-16 requires one routeable state model for mission/site/vehicle/body/time/mode/role/work area/source (`PRD.md:783`).
- Do not put backend-derived artifacts such as `PlanResult`, `WorldState`, `LayerManifest`, or `ExecutionEvent` only in Zustand. Those are authoritative server data and should live behind generated API client calls plus TanStack Query keys.

State key sketch:

```ts
type ProductMode = "gis_plan" | "train" | "sim_operate" | "evaluate" | "operate";
type RunnableProfile = "desktop_sil" | "digital_twin" | "ros2_replay" | "hil_jetson" | "live_rover";

interface WorkspaceState {
  pane: ConOpsPaneId;
  validateSubpane: "navigation" | "perception" | "solar";
  missionName?: string;
  site: string;             // e.g. haworth
  bodyId: string;           // BodyProfile.id, default moon
  vehicleId: string;
  physicsBackendId: string; // PhysicsBackend.id, default tier2_numpy
  productMode: ProductMode;
  runnableProfile: RunnableProfile;
  sourceClass: "prior" | "observed" | "forecast" | "sim_truth" | "live";
  selectedLayerIds: string[];
  selectedEntity?: { kind: string; id: string };
  editSession?: EditSessionState;
}
```

### 1.3 2D MapLibre/deck Map Model

Decision: no 3D globe. The map is a flat 2D workbench. It should expose two coordinate views:

- Planetary/site view: body/site CRS metadata, bounding boxes, layer list, and site selection. The body profile provides `crs` and `ellipsoid_radius_m` where known (`stewie/specs/bodies.py:47-49`, Moon/Mars values at `stewie/specs/bodies.py:61-76`).
- Local order-frame view: the planner's metres-East/metres-North frame over the site DEM. Existing `/dem/site_xy` and `/dem/site_lonlat` are used today to transform between selenographic lat/lon and order/site metres in `cockpit.js` (`stewie/server/web/assets/cockpit.js:224-230`, `stewie/server/web/assets/cockpit.js:4597-4674`). The 2D target should promote that transform chain to typed code, not bury it in UI handlers.

Map layers:

- Base raster: `/dem/workarea.png`, `/layers/raster/{kind}.png`, `/world/terrain_view.png`, and export/COG routes where applicable.
- FR-10 manifest: `/world` returns `layer_manifest`; React should treat it as the layer authority and not build a separate client-only catalog (`stewie/server/routers/world.py:72-81`, `stewie/contracts/__init__.py:481-517`).
- deck.gl overlays: build orders, keep-outs, routes, planned/rehearsed/executed tracks, fleet positions, uncertainty cells, observed hazards, volume evidence, and release/execute authority markers.
- No Cesium/Three.js path in the target UI. Existing 3D-only features must either be retired, represented as 2D forecast/heightfield layers, or kept as legacy-only until explicitly rebuilt.

Map projection strategy:

```ts
interface SiteProjection {
  bodyId: string;
  siteId: string;
  crs: string; // body profile CRS or local projected CRS label
  orderFrame: "x_east_y_north_m";
  worldToMapMeters(x: number, y: number): [number, number];
  mapMetersToWorld(mx: number, my: number): [number, number];
  lonLatToSiteXY?(lon: number, lat: number): Promise<[number, number]>;
  siteXYToLonLat?(x: number, y: number): Promise<[number, number]>;
}
```

Because MapLibre/deck are Earth/WebMercator-oriented per the assessment (`docs/geolibre_migration_assessment_2026-07-03.md:50-56`), the target should avoid presenting WGS84-looking coordinates as body-correct unless the transform is explicit. For the first production target, render local projected metres as the operational map and show body CRS metadata in the coordinate readout.

### 1.4 The 13 Pane React Component Set

ConOps panes to rebuild:

1. `PlanPane`: mission/site/body/physics/vehicle selection, layer workbench, orders, keep-outs, authoring, solve, profile save/load, Plan IR export.
2. `RehearsePane`: director-gated forward comparison over `/resync/compare`.
3. `ValidatePane`: parent shell for Navigation, Perception, and Solar subpanes.
4. `ReleasePane`: director sign-off, immutable revision evidence, `/executive/release-plan`.
5. `ExecutePane`: forecast replay plus `/executive/run` sim stream and command-eligibility surfaces; live remains gated.
6. `ReportPane`: PDF/report embed, `PlanResult` dashboard, world transactions, volume evidence.
7. `FleetPane`: `/fleet` registry plus last-plan per-vehicle allocations.
8. `ConstructionPane`: `/construction` catalog plus as-built acceptance and terrain-memory evidence.
9. `ModelsPane`: `/models` system profiles, vehicles, body registry, model governance, and new physics/backend registry surfaces.
10. `TrainerPane`: `/trainer/history`, sessions, scorecards, debrief.
11. `AdminPane`: `/admin/operators/*`, invites, governance operations.
12. `SettingsPane`: user/workspace/API/session settings.
13. `SystemPane`: health, metrics, API docs, evidence, validation/config surfaces.

The existing DOM shell already distinguishes the primary spine and role-gated secondary/admin surfaces (`stewie/server/index.html:811-890`). The React target should keep the product hierarchy but not keep DOM IDs as architecture.

Each pane contract:

```ts
interface PaneModule {
  id: ConOpsPaneId;
  label: string;
  minRole: "guest" | "trainee" | "operator" | "director";
  sourceClass: "prior" | "observed" | "forecast" | "sim_truth" | "live";
  routeBindings: RouteBinding[];
  Component: React.ComponentType;
  emptyFixture: unknown;
  errorFixture: unknown;
  mobileFixture: unknown;
}

interface RouteBinding {
  method: "GET" | "POST" | "PUT" | "DELETE";
  pathTemplate: string;
  generatedOperationId: string;
  schemaName?: string;
  provenanceRequired: boolean;
  mutatesAuthority: boolean;
}
```

This is the React version of PRD FR-06's route-to-pane registry requirement (`PRD.md:954-963`) and FS-18's route contract gate (`PRD.md:785`).

### 1.5 DuckDB-WASM Spatial Over FR-10

Confirmed gain: the prior assessment identifies DuckDB-WASM client-side spatial queries over FR-10 as the genuine GeoLibre benefit (`docs/geolibre_migration_assessment_2026-07-03.md:69-76`).

Target shape:

```ts
interface DuckLayerTable {
  layerId: string;
  layerType: string;
  crs: string;
  body: string;
  source: string;
  provenance: string;
  transactionId: string;
  display: boolean;
  planning: boolean;
  release: boolean;
  execute: boolean;
  geometryColumn?: string;
  rasterRef?: string;
  loadedAt: string;
}

interface SpatialQueryService {
  init(): Promise<void>;
  loadManifest(manifest: LayerManifest): Promise<void>;
  attachGeoJSON(name: string, geojson: object, provenance: Provenance): Promise<void>;
  attachGeoParquet(url: string, tableName: string): Promise<void>;
  query<T = unknown>(sql: string, params?: unknown[]): Promise<T[]>;
  explain(sql: string): Promise<string>;
}
```

Rules:

- DuckDB is a query/analysis layer, not a source of mission authority.
- DuckDB tables must carry FR-10 `display/planning/release/execute` eligibility, and the UI must not let a display-only layer silently become a planning/release input.
- Write-back from DuckDB query results to mission objects must go through existing backend routes such as `/gis/import`, `/missions/{name}`, `/structures/custom/{name}`, or new explicit edit-session routes. The current backend already has GIS import/query/export routes in `gis_export.py` per route inventory, and PRD BA-11 says mission packages preserve authority tuple and CRS/layer metadata (`PRD.md:1001`).

### 1.6 API Client Covering All Routes

Route inventory:

- 140 router-owned routes in `stewie/server/routers/*` confirmed by `@router.*` decorators.
- 5 app-level route decorators in `server.py`: `/docs`, `/`, `/index.html`, and GET/POST fallbacks.
- 146 FastAPI app routes when `/openapi.json` is counted.

Target:

```text
api/generated/
  openapi.json
  client.ts
  types.ts
api/routeRegistry.ts
  one record per router-owned route
  plus app/static routes tagged "static/system"
```

Generation:

- Generate from live `/openapi.json` in CI and fail on uncommitted generated drift.
- Keep a route coverage test that compares generated OpenAPI paths to `routeRegistry`.
- For streaming/download/static routes, use typed hand adapters:
  - SSE: `/executive/run/{run_id}/stream`, `/rc/telemetry/stream`.
  - Binary/image/PDF: `/layers/raster/{kind}.png`, `/layers/globe/{kind}.png`, `/dem/workarea.png`, `/world/terrain_view.png`, `/export/cog/{kind}.tif`, `/reports/{name}`, `/figure/{key:path}`, `/assets/{path:path}`.
  - Static/dev-only routes: `/`, `/index.html`, `/assets/*`, `/cesium/*` during legacy period.

Coverage contract:

```ts
interface ApiRouteRegistryEntry {
  method: string;
  pathTemplate: string;
  ownerRouter: string;
  operationId: string;
  paneIds: ConOpsPaneId[];
  auth: "open" | "auth" | "operator" | "director";
  responseKind: "json" | "binary" | "sse" | "html" | "static";
  provenanceRequired: boolean;
  mutates: boolean;
  fixtures: {
    ok?: string;
    empty?: string;
    error?: string;
    mobile?: string;
  };
}
```

### 1.7 FastAPI Sidecar Attachment

Backend remains `stewie.server.server:app`, preserving the existing sidecar entry point (`stewie/server/server.py:1-14`, `stewie/server/server.py:89-90`).

Web deployment:

- Serve React bundle from existing FastAPI/static or the existing Nginx frontend.
- Keep same-origin API by default, preserving current same-origin/CORS hardening. `server.py` currently defaults CORS to an empty allowlist unless explicitly configured (`stewie/server/server.py:105-115`).

Tauri deployment:

- Tauri launches or connects to the FastAPI sidecar on a loopback port.
- Sidecar readiness flow: wait for `/healthz`, fetch `/auth/config`, fetch `/openapi.json`/version, then mount app.
- Sidecar process logs and crashes surface in `SystemPane`, not hidden in a terminal.
- If sidecar is absent, the React app may render a degraded local-shell state but must not fabricate backend data.

### 1.8 Extensibility Seam A: PhysicsBackend

Purpose: make Tier-2 conserved NumPy, Tier-3 Chrono/hybrid SCM, and future engines selectable per mission/body without letting the UI or learned components mutate terrain directly.

Confirmed source constraints:

- Current Tier-2 functions provide body/soil parameters, wheel load/sinkage, mass-conserving compaction, slip, and domain randomization (`stewie/physics/terramechanics.py:52-364`, `lode/planner_endurance.py:195-213`).
- Structural bearing lives in FORGE (`forge/bearing.py:50-66`).
- Chrono SCM export can source deformed height/disturbance but not mass/density, so a Chrono backend must either be marked `geometry_oracle_only` or be hybridized with Tier-2 mass/density bookkeeping (`scripts/chrono_scm_export.py:15-33`, `scripts/chrono_scm_export.py:214-216`).
- Existing mission planning resolves gravity from `mission.body` and soil via `mission.soil or mission.body` (`lode/planner_model.py:70-90`, `lode/planner_model.py:256-260`).

Proposed Python protocol:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol
import numpy as np

PhysicsMode = Literal["planning", "simulation", "oracle", "hybrid"]
PhysicsAuthorityClass = Literal["conserved", "geometry_oracle", "advisory"]

@dataclass(frozen=True)
class PhysicsBackendInfo:
    id: str                         # "tier2_numpy", "chrono_scm_hybrid"
    label: str
    version: str
    authority_class: PhysicsAuthorityClass
    modes: tuple[PhysicsMode, ...]
    supported_bodies: tuple[str, ...]       # body ids or "*"
    supported_regimes: tuple[str, ...]      # e.g. "gravity-loaded"; microgravity may be refused
    writes_interface_fields: bool
    conserves_mass: bool
    notes: str

@dataclass(frozen=True)
class PhysicsSupportVerdict:
    ok: bool
    reason: str = ""
    degraded: bool = False
    required_labels: tuple[str, ...] = ()    # e.g. ("ANALOG", "OUT_OF_REGIME")

@dataclass(frozen=True)
class SoilParamsDTO:
    k_c: float
    k_phi: float
    n_sinkage: float
    cohesion: float
    phi_rad: float
    k_shear: float
    slip_c1: float
    slip_c2: float
    rho_surface: float
    rho_deep: float
    provenance: str
    confidence: str

@dataclass(frozen=True)
class PlanningPhysicsContextDTO:
    body_id: str
    backend_id: str
    gravity_m_s2: float
    drive_j_per_m: float
    dig_j_per_kg: float
    battery_j: float
    drum_kg: float
    rover_mass_kg: float
    drive_power_w: float
    soil: SoilParamsDTO
    labels: tuple[str, ...] = ()

@dataclass(frozen=True)
class SinkageResult:
    sinkage_m: float
    pressure_pa: float
    stiffening: float
    provenance: str

@dataclass(frozen=True)
class SlipResult:
    slip: float                      # clamped [0, 0.95] like planner_endurance
    sinkage_m: float | None
    traction_ok: bool
    labels: tuple[str, ...]

@dataclass(frozen=True)
class BearingResult:
    ultimate_pa: float
    allowable_pa: float
    factor_of_safety: float
    provenance: str

@dataclass(frozen=True)
class InterfaceFieldExport:
    fields: dict[str, np.ndarray]     # heightmap, mass_areal, density, disturbance, state_label...
    metadata: dict
    authority_class: PhysicsAuthorityClass
    labels: tuple[str, ...]

class PhysicsBackend(Protocol):
    def info(self) -> PhysicsBackendInfo: ...

    def supports(
        self,
        *,
        body: "BodyProfile",
        mode: PhysicsMode,
        allow_analog: bool = False,
    ) -> PhysicsSupportVerdict: ...

    def resolve_soil_params(
        self,
        *,
        body: "BodyProfile",
        soil: "BodyProfile | None" = None,
        allow_analog: bool = False,
    ) -> SoilParamsDTO: ...

    def planning_context(
        self,
        *,
        mission: "Mission",
        vehicle: "VehicleModel",
        body: "BodyProfile",
        soil: "BodyProfile | None" = None,
        allow_analog: bool = False,
    ) -> PlanningPhysicsContextDTO: ...

    def static_wheel_load_n(
        self,
        *,
        payload_kg: float,
        rover_mass_dry_kg: float,
        n_wheels: int,
        g_m_s2: float,
    ) -> float: ...

    def wheel_static_sinkage(
        self,
        *,
        load_n: float,
        density_kg_m3: float | None,
        params: SoilParamsDTO,
        contact_len_m: float,
        contact_width_m: float,
    ) -> SinkageResult: ...

    def physical_compaction_field(
        self,
        *,
        density_kg_m3: np.ndarray,
        mass_areal_kg_m2: np.ndarray,
        load_n: float,
        params: SoilParamsDTO,
        contact_len_m: float,
        contact_width_m: float,
        slip: float = 0.0,
    ) -> np.ndarray: ...

    def physical_compaction_target_density(
        self,
        *,
        mass_areal_kg_m2: np.ndarray,
        load_n: float,
        params: SoilParamsDTO,
        contact_len_m: float,
        contact_width_m: float,
        slip: float = 0.0,
    ) -> np.ndarray: ...

    def slip_equilibrium(
        self,
        *,
        slope_deg: float,
        payload_kg: float,
        density_kg_m3: float | None,
        params: SoilParamsDTO,
        rover_mass_kg: float,
        body: "BodyProfile",
    ) -> SlipResult: ...

    def allowable_bearing(
        self,
        *,
        cohesion_pa: float,
        phi_rad: float,
        unit_weight_n_m3: float,
        width_m: float,
        factor_of_safety: float = 3.0,
        surcharge_depth_m: float = 0.0,
    ) -> BearingResult: ...

    def export_interface_fields(
        self,
        *,
        scene_name: str,
        width: int,
        height: int,
        cell_m: float,
        gravity_m_s2: float,
        terrain_handle: object | None = None,
        surrogate_fields: dict[str, np.ndarray] | None = None,
    ) -> InterfaceFieldExport: ...
```

Implementation mapping:

- `Tier2NumpyBackend` is a thin adapter over `stewie.specs.bodies.params_for_body`, `stewie.physics.terramechanics.*`, `lode.planner_model.plan_context`, `lode.planner_endurance.slip_alpha_to_slip`, and `forge.bearing.*`.
- `ChronoScmHybridBackend` starts as `authority_class="geometry_oracle"` and `conserves_mass=False` until the hybrid path passes a mass-conservation acceptance. It may implement `export_interface_fields` using the shape in `scripts/chrono_scm_export.py`, but must label mass/density placeholders if used (`scripts/chrono_scm_export.py:126-147`).
- Future engines must provide the same return contracts and labels. A backend that cannot conserve mass cannot be selected for release/execute authority.

API surface:

```http
GET  /physics/backends
GET  /physics/backends/{backend_id}
POST /physics/backends/{backend_id}/supports
POST /physics/resolve-context
POST /physics/compare
```

Request/response sketches:

```json
{
  "mission": {"body": "moon", "soil": "bp1_testbed", "vehicle": "ipex"},
  "backend_id": "tier2_numpy",
  "mode": "planning",
  "allow_analog": false
}
```

```json
{
  "ok": true,
  "backend": {"id": "tier2_numpy", "authority_class": "conserved", "conserves_mass": true},
  "support": {"ok": true, "degraded": false, "required_labels": []},
  "context": {
    "body_id": "moon",
    "gravity_m_s2": 1.62,
    "drive_j_per_m": 0.0,
    "soil": {"k_c": 1400.0, "k_phi": 820000.0, "n_sinkage": 1.0}
  }
}
```

Mission selection:

- Extend mission/profile schema with `physics_backend_id`, default `tier2_numpy`.
- Extend `/plan`, `/plan/commands`, `/plan/math`, `/resync/compare`, `/executive/release-plan`, `/executive/run`, and export/report surfaces to carry the selected backend id and support verdict in provenance.
- UI selector lives in `PlanPane` and `ModelsPane`; Release/Execute shows backend support evidence.

### 1.9 Extensibility Seam B: BodyProfile Registry

Purpose: make Moon/Mars/Ceres/Earth/Bennu/Phobos and future bodies clean profiles rather than hard-coded constants, while preserving current no-fabrication provenance discipline.

Confirmed current schema from `Body`:

```python
@dataclasses.dataclass(frozen=True)
class Body:
    name: str
    label: str
    g: float
    bekker_regime: str
    bulk_density: float | None = None
    cohesion_pa: float | None = None
    friction_deg: float | None = None
    repose_deg: float | None = None
    bekker: tuple | None = None
    confidence: str = ""
    g_note: str = ""
    role: str = ""
    provenance: str = ""
    ellipsoid_radius_m: float | None = None
    crs: str | None = None
```

Proposed Pydantic/JSON schema:

```ts
type BekkerRegime = "gravity-loaded" | "microgravity";
type ProvenanceTag = "MEASURED" | "ESTIMATED" | "ANALOG" | "UNKNOWN" | "CALIB";

interface BekkerParams {
  k_c: number;       // N/m^2 in current repo units
  k_phi: number;     // N/m^3 in current repo units
  n: number;
  provenance: string;
  tags: ProvenanceTag[];
}

interface BodyProfile {
  schema_version: "1.0";
  id: string;                         // canonical lowercase key; current Body.name
  label: string;
  gravity_m_s2: number;               // current Body.g
  bekker_regime: BekkerRegime;
  bulk_density_kg_m3: number | null;
  cohesion_pa: number | null;
  friction_deg: number | null;
  repose_deg: number | null;
  bekker: BekkerParams | null;
  confidence: string;
  gravity_note?: string;
  role: string;
  provenance: string;
  ellipsoid_radius_m: number | null;
  crs: string | null;                 // e.g. IAU_2015:30100
  default_site_ids: string[];
  allowed_physics_backend_ids?: string[];
  labels: ProvenanceTag[];
}
```

Python registry sketch:

```python
class BodyProfileRegistry:
    def register(self, profile: BodyProfile, *, source: str, replace: bool = False) -> None: ...
    def get(self, body_id: str) -> BodyProfile: ...
    def list(self) -> list[BodyProfile]: ...
    def params_for_body(self, body_id: str, *, allow_analog: bool = False) -> TerramechanicsParams: ...
    def body_in_regime(self, body_id: str) -> bool: ...
    def validate_mission_body(self, body_id: str, physics_backend_id: str, *, allow_analog: bool = False) -> PhysicsSupportVerdict: ...
```

File layout:

```text
stewie/specs/body_profiles/
  moon.json
  mars.json
  ceres.json
  bennu.json
  phobos.json
  earth.json
  bp1_testbed.json
stewie/specs/body_registry.py
stewie/server/routers/body_profiles.py
```

Registration mechanism:

1. Built-ins are loaded from `stewie/specs/body_profiles/*.json`.
2. Optional local/operator profiles are loaded from `STEWIE_BODY_PROFILE_PATHS`, a path list outside source control.
3. Future Python packages may register entry points under `stewie.body_profiles`; keep this optional until the built-in JSON path is stable.
4. Duplicate ids are rejected unless `replace=True` and the source is explicitly marked as an override. Overrides must carry provenance and labels.

API surface:

```http
GET  /body-profiles
GET  /body-profiles/{body_id}
POST /body-profiles/validate
```

Compatibility:

- Keep `/bodies.json` during migration because the vanilla cockpit populates body/soil dropdowns from it (`stewie/server/routers/assets.py:53-58`, `stewie/server/web/assets/cockpit.js:6012-6024`).
- `/models` should move from reading `B.BODIES` directly to reading `BodyProfileRegistry`, but response keys can remain compatible (`stewie/server/routers/models.py:69-81`, `stewie/server/routers/models.py:84-140`).
- `params_for_body(name)` can remain as a compatibility wrapper over the registry until all call sites move.

UI selection:

- `PlanPane`: Body selector + soil/profile override + physics backend selector + support verdict. Microgravity bodies display an out-of-regime refusal unless the operator explicitly enables analog/advisory mode, preserving current `params_for_body` fail-closed behavior (`stewie/specs/bodies.py:165-175`).
- `ModelsPane`: Body registry table with provenance/confidence/CRS/regime and backend compatibility matrix.
- `MapWorkbench`: body/site profile determines coordinate readout and local projection metadata. A body without map CRS can still run local-order-frame planning if a site DEM exists, but the UI must label planetary coordinate operations unavailable.

## 2. Rewritten PRD Structure

### 2.1 What §6 Target Architecture Should Say

Replace the current L0-L7 target architecture text (`PRD.md:420-446`) with the same domain layers but a new explicit product/frontend/runtime split:

```text
L8  Product shells
    Web deployment + Tauri v2 desktop shell, both using the same React/TypeScript app.

L7  Operator cockpit and GIS workbench
    React ConOps panes, MapLibre/deck 2D projected map, DuckDB-WASM Spatial query workbench,
    generated API client, route-to-pane registry, provenance/mode/authority labels.

L6  Mission and fleet planning
    goals / structures / PlanResult / resources / acceptance / Plan IR / body+physics selection

L5  Navigation and execution
    coverage planner / local planner / tracker / recovery / executive / command eligibility

L4  Perception and localization
    camera policy / segmentation / stereo VO / SLAM / observed layers / solar factors

L3  Vehicle digital twin
    VehicleTwin / ArmState / drums / CG / support polygon / work lights / camera rig

L2  Terrain, illumination, and world state
    FR-10 LayerManifest / conserved terrain / observed twin / rocks / uncertainty / sun/shadow

L1  Pluggable physics authority
    PhysicsBackend interface: Tier-2 NumPy conserved authority, Tier-3 Chrono/hybrid, future engines.

L0  Contracts and profiles
    units / schemas / time / frames / provenance / invariant enforcement /
    BodyProfile registry / PhysicsBackend contracts / authority labels
```

Add authoritative artifacts to §6.1:

- `LayerManifest`: already implemented under FR-10 and returned by `/world` (`stewie/server/routers/world.py:72-81`, `stewie/contracts/__init__.py:481-517`).
- `BodyProfile`: versioned body/regolith/CRS profile replacing direct `BODIES` dictionary coupling.
- `PhysicsBackendInfo` and `PhysicsBackendSelection`: selected per mission/body/profile, recorded in PlanResult/report/release evidence.
- `ApiRouteRegistry`: generated typed client coverage for all 140 router-owned routes.
- `SpatialQueryWorkspace`: DuckDB-WASM loaded catalog/query state, explicitly advisory/display until write-back goes through backend routes.
- `DesktopSidecarSession`: Tauri sidecar process state, base URL, version, health, log path.

Revise §6.2 world-state text:

- Keep the layered conserved/observed split. It is still correct (`PRD.md:470-495`).
- Add that the React map consumes `LayerManifest` as the only layer authority; MapLibre/deck display does not create new planner truth.
- Add that 2D projected map is the accepted UI model; no 3D globe is a requirement for the rebuilt frontend.

### 2.2 §7 Lane Reorganization

Do not mass-edit backend rows simply because the frontend is changing. Backend rows mostly stay because FastAPI/core are reused.

Preserve mostly as-is:

- `CT-*`: contracts/conserved authority.
- `TW-*`, `DT-*`: world/twin layering.
- `VT-*`, `AM-*`: vehicle/arms/drums.
- `PM-*`, `SN-*`, `NV-*`, `AS-*`, `BA-*`: perception/navigation/autonomy.
- `CP-*`, `MO-*`, `EP-*`, `FL-*`: mission planning, executive, energy, fleet.
- `PO-*`, `AG-*`, `BP-*`: packaging, identity, backend hardening.
- `ML-*`, `RL-*`, `SL-*`: model/autonomy governance.

Mark migrated/superseded:

- `FS-03`, `FS-15`, `FS-16`, `FS-18`, `FS-20`, `FS-21`, `FS-24`: preserve the intent but mark "MIGRATED to RF/API/RX lanes" once the React lanes land.
- `FR-01..FR-21`: split. Rows about provenance, authority, mobile, route registry, layer manifest, and ArcGIS boundaries stay conceptually valid, but should be rewritten into the new React/GeoLibre lanes. Rows that are fixes to the vanilla DOM shell should be closed as historical once the vanilla shell retires.
- Cesium/3D-specific GI wording: rewrite into 2D MapLibre/projected-map correctness. `GI-01` becomes a deployment browser smoke for the React/Tauri map app; `GI-02` becomes body/profile CRS correctness with no 3D terrain claim.
- `FS-23`/React episode prose should remain historical, not an active plan.

Proposed new §7 lane codes:

| Code | Lane | Purpose |
|---|---|---|
| `RF-*` | React frontend shell and ConOps panes | React app shell, 13 panes, pane registry, responsive IA, role gates, provenance labels, pane parity. |
| `GL-*` | GeoLibre 2D map workbench | MapLibre/deck 2D map, projected lunar/body map, FR-10 layer display, identify/measure/edit, CRS labels. |
| `DW-*` | DuckDB-WASM Spatial | Client query engine over FR-10/mission packages, query UI, advisory/write-back boundaries, performance/offline limits. |
| `API-*` | TypeScript API client and route coverage | Generated OpenAPI client, registry coverage for all 140 router routes, typed fixtures, SSE/binary adapters. |
| `PX-*` | Physics backend extension | `PhysicsBackend` protocol, Tier-2 adapter, Chrono/hybrid status, mission/backend selection, release eligibility. |
| `BOD-*` | Body profile registry | `BodyProfile` schema, built-in profile files, local/plugin registration, body/profile UI, no-fabrication provenance. |
| `TAU-*` | Tauri desktop shell and sidecar | Tauri v2 packaging, FastAPI sidecar supervision, local data dirs, update/log/error handling, offline/degraded behavior. |
| `MIG-*` | Strangler migration governance | Vanilla/React side-by-side routing, parity gates, rollback, retirement criteria, cache/version stamping. |

Example new rows:

| ID | P | Requirement and acceptance |
|---|---|---|
| `API-01` | P0 | Generate a TypeScript client from live `/openapi.json`; CI fails when generated paths diverge from FastAPI. Acceptance: every one of the 140 router-owned routes has a registry entry or an explicit static/internal exemption. |
| `API-02` | P0 | Route registry records pane ownership, auth/role, response kind, provenance requirement, fixtures, and whether the route mutates authority. Acceptance: missing fixture/role/provenance for a pane-backed route fails. |
| `RF-01` | P0 | React shell implements the same 13 pane identities and role visibility as the vanilla cockpit. Acceptance: signed-in browser tests can open Plan/Rehearse/Validate/Release/Execute/Report/Fleet/Construction/Models/Trainer/Admin/Settings/System at desktop and phone widths. |
| `RF-02` | P0 | React state model carries mission/site/body/vehicle/physics backend/product mode/runnable profile/source class/work area. Acceptance: URL/state round-trips and Release/Execute refuse mismatched profile/backend states. |
| `GL-01` | P0 | 2D MapLibre/deck workbench renders the selected site's DEM/layers from `/world` FR-10 manifest and local order frame. Acceptance: known control points round-trip through `/dem/site_xy` and `/dem/site_lonlat` within tolerance; no Earth/WGS84 claim is shown for lunar map coordinates. |
| `GL-02` | P1 | Map identify/measure/edit sessions operate on deck layers and write mission edits only through backend routes. Acceptance: a keep-out created on the map appears in the mission request and routes around it, matching existing planner behavior. |
| `DW-01` | P1 | DuckDB-WASM loads the FR-10 manifest and vector mission package into queryable tables with layer eligibility fields. Acceptance: a query can select hazards/keep-outs/routes by bbox/provenance and cannot mark display-only layers as planning-valid. |
| `PX-01` | P0 | Define `PhysicsBackend` protocol and implement `tier2_numpy` adapter over existing terramechanics/FORGE/planner context. Acceptance: Moon Tier-2 `/plan` output is byte-compatible or explicitly diff-reviewed, and microgravity refusal behavior remains fail-closed. |
| `PX-02` | P1 | Mission/profile schema carries `physics_backend_id`, and `/physics/backends` exposes backend support/authority/conservation status. Acceptance: React and backend both show the selected backend in plan/report/release evidence. |
| `PX-03` | P2 | Chrono SCM backend is exposed only as `geometry_oracle`/`hybrid` until mass-conservation closure exists. Acceptance: it cannot be selected for release/execute authority while `conserves_mass=false`. |
| `BOD-01` | P0 | Convert current `BODIES` constants into versioned `BodyProfile` records without changing values. Acceptance: Moon/Mars/Ceres/Bennu/Phobos/Earth/BP-1 profiles match current `bodies.py` fields and tests prove `params_for_body` compatibility. |
| `BOD-02` | P1 | Body profile registry supports built-in JSON plus local profile paths with provenance and duplicate-id rules. Acceptance: invalid/missing provenance or fabricated numeric fields are rejected. |
| `TAU-01` | P1 | Tauri app starts/connects to FastAPI sidecar and surfaces health/logs/version. Acceptance: cold start reaches `/healthz` and `/auth/config`, and sidecar failure produces a SystemPane degraded state. |
| `MIG-01` | P0 | Vanilla cockpit remains served and deployable until React parity gates pass. Acceptance: `/app` continues to pass existing smoke tests while `/app2`/React migrates panes. |
| `MIG-02` | P0 | No pane is flipped from vanilla to React without signed-in Playwright parity, fixture tests, mobile fit, route registry coverage, and rollback route. |

## 3. Phased Migration Plan With Kill-Gates

The migration must remain a strangler fig because the earlier React rewrite failed and was reverted (`PRD.md:154-165`, `PRD.md:1677-1681`). The vanilla cockpit stays live until full parity.

### Phase 0: ADR, Inventory, and Route Contract Freeze

Estimate: 1 week.

Work:

- Write ADR: "2D React/GeoLibre-style rewrite, no 3D globe, FastAPI sidecar retained."
- Inventory all 140 router-owned routes into a registry seed.
- Freeze current vanilla cockpit smoke/parity fixtures: key screenshots or DOM snapshots for Plan, Report, Validate, Execute, Fleet, Construction, Models, Trainer, Admin/Settings/System.
- Decide React served path: recommended `/app2` during migration, with `/app` staying vanilla.
- Decide Tauri sidecar runtime strategy but do not block web migration on packaging.

Kill-gate / exit criterion:

- `MIG-01` accepted: vanilla `/app` remains default.
- Route inventory reconciles 140 router-owned API routes plus known static/app routes.
- No source-pane flip is allowed until this inventory exists.
- Stop or re-scope if owner will not accept side-by-side migration and rollback.

### Phase 1: React/Tauri-Web Shell + Generated API Client

Estimate: 2-3 weeks.

Work:

- Scaffold React/TS app and route shell under `/app2` or equivalent.
- Generate API client from `/openapi.json`; add route registry and coverage tests.
- Implement auth/session basics, role visibility, error/loading/empty components.
- Implement Zustand workspace state and TanStack Query.
- Add `SystemPane` minimal health/API version view first because it proves sidecar communication with low mission risk.

Kill-gate:

- API registry covers every router-owned route or has explicit exemption.
- React shell loads signed-in and signed-out against the existing sidecar.
- `/app` vanilla remains unaffected.
- If generated client cannot model enough routes due OpenAPI gaps, fix the route schemas before pane migration.

### Phase 2: 2D MapLibre/deck Map Spike Over Real Site Data

Estimate: 2-4 weeks.

Work:

- Implement `MapWorkbench` with MapLibre in local order-frame mode and deck overlays.
- Consume `/world` and FR-10 `LayerManifest`.
- Render Haworth DEM/workarea/raster layers and basic order/keep-out overlays.
- Implement coordinate readout and round-trip checks using existing DEM transform endpoints.
- No 3D, no Cesium, no globe.

Kill-gate:

- Haworth DEM/layers render nonblank and correctly framed at desktop/mobile.
- Known control points round-trip order-frame <-> lon/lat through backend endpoints within an agreed tolerance.
- UI labels local projected/order-frame coordinates honestly; no WGS84/Earth implication.
- If 2D MapLibre cannot support the local projected map without unacceptable distortion or interaction bugs, stop the platform rewrite and keep DuckDB/API work as additive.

### Phase 3: BodyProfile + PhysicsBackend Foundation

Estimate: 3-5 weeks.

Work:

- Add `BodyProfile` schema and registry while keeping current `bodies.py` helper compatibility.
- Add `PhysicsBackend` protocol and `tier2_numpy` adapter over current functions.
- Add read/validate endpoints: `/body-profiles`, `/physics/backends`, `/physics/resolve-context`.
- Extend mission/profile schema with `physics_backend_id` but default to `tier2_numpy`.
- React `PlanPane` shell shows body + physics selectors and support verdict. Do not yet make Chrono selectable for authority.

Why here:

- This lands before Plan/Fleet/Execute migration because those panes need to display backend/body evidence.
- It does not block the first shell/map work because no pane has been flipped yet.

Kill-gate:

- Moon/Tier-2 planning remains byte-compatible or differences are explained and test-approved.
- Microgravity behavior remains fail-closed unless `allow_analog=True`, preserving `params_for_body` semantics.
- `/models` and new registry endpoints agree on built-in body/profile values.
- Chrono/hybrid appears only with `conserves_mass=false` / not release-eligible until proven otherwise.

### Phase 4: DuckDB-WASM Spatial Layer Workbench

Estimate: 2-3 weeks.

Work:

- Initialize DuckDB-WASM and spatial extension in the React app.
- Load FR-10 `LayerManifest` into layer tables.
- Load mission package/vector exports where available.
- Build query panel for bbox/layer/provenance/eligibility queries.
- Keep query results advisory unless the operator writes them back via existing backend routes.

Kill-gate:

- Query panel can inspect layers from a real `/world` manifest and a real mission package.
- Eligibility fields survive into query results.
- Browser memory/load time remain within a defined budget on Haworth-scale data.
- If WASM performance is poor, keep DuckDB as an optional panel and do not block pane migration.

### Phase 5: First Pane Migration - ReportPane

Estimate: 3-4 weeks.

First pane: `ReportPane`.

Reason:

- It is read-heavy, lower command risk, and already consumes `PlanResult`, report PDF, world transactions, and volume evidence.
- It exercises the typed API, provenance labels, iframe/download/binary handling, and prior-plan state without authoring or command authority.
- This matches the earlier assessment's recommendation to begin with Report or Program board as a side-by-side pane (`docs/geolibre_migration_assessment_2026-07-03.md:88-90`).

Work:

- Implement React `ReportPane` from route fixtures.
- Compare output against vanilla report/dashboard behavior.
- Keep the vanilla pane as default until signed-in tests pass.

Kill-gate:

- Report pane opens for a real planned mission, shows the PDF/report link, PlanResult dashboard, world-state provenance, and empty/error states.
- Desktop/mobile parity with vanilla for critical content.
- Actual LOC/hours are recorded and extrapolated to 13 panes. If Report exceeds estimate by >2x, re-plan before continuing.

### Phase 6: PlanPane Authoring and Solve

Estimate: 5-8 weeks.

Work:

- Rebuild Plan pane: site/body/physics/vehicle, orders, footprints, keep-outs, mission save/load, plan/commands/math/profile/export.
- Use MapWorkbench/deck edit sessions instead of Cesium entity editing.
- Preserve existing backend request shapes for `/plan`, `/plan/commands`, `/plan/math`, `/missions`, `/structures/custom`, `/gis/*`.
- Surface support verdict for selected body/physics before solve.

Kill-gate:

- A real Haworth mission planned in React produces equivalent `/plan` payload/result/report to vanilla.
- Keep-outs/footprints route around hazards and validate as expected.
- No client-side direct terrain mutation; all solve/mutate paths go through backend.
- If order authoring parity cannot be achieved without backend contract changes, pause pane migration and land the backend contract first.

### Phase 7: High-Consequence ConOps Panes

Estimate: 6-10 weeks.

Panes:

- `RehearsePane`
- `ValidatePane` with Navigation/Perception/Solar subpanes
- `ReleasePane`
- `ExecutePane`

Work:

- Rebuild candidate comparison, validation previews, authority evidence, release sign-off, forecast replay, sim execute stream, and command eligibility.
- Keep live/forecast/sim/truth labels machine-readable and visible.
- Ensure Release/Execute use product mode, runnable profile, selected physics backend, body profile, sensor profile, map freshness, and authority verdict.

Kill-gate:

- Release cannot sign a plan without complete evidence fields.
- Execute cannot present simulated forecast as live.
- Director/operator role gates match existing backend behavior.
- SSE streams work reliably.
- If React introduces ambiguity in command authority, do not flip Release/Execute; keep vanilla for those panes.

### Phase 8: Secondary and Control Panes

Estimate: 5-8 weeks.

Panes:

- `FleetPane`
- `ConstructionPane`
- `ModelsPane`
- `TrainerPane`
- `AdminPane`
- `SettingsPane`
- `SystemPane` full version

Work:

- Rebuild registry/governance/trainer/admin surfaces with typed adapters.
- `ModelsPane` becomes the operator-visible home for BodyProfile and PhysicsBackend registries.
- `SystemPane` includes sidecar health, API docs link, metrics, logs/degraded states, and route registry status.

Kill-gate:

- All 13 pane ids are React-backed with fixtures, mobile tests, role tests, and route registry coverage.
- Admin actions show governance policy and audit/degraded state.
- No route-backed pane is missing error/empty/loading states.

### Phase 9: Tauri v2 Packaging and Offline/Sidecar Hardening

Estimate: 3-6 weeks.

Work:

- Package React app in Tauri v2.
- Launch/connect to FastAPI sidecar.
- Define app data dirs, logs, crash handling, sidecar updates, and offline/degraded behavior.
- Confirm public web deployment remains supported.

Kill-gate:

- Tauri cold-start reaches sidecar health and renders the same route-backed panes as web.
- Sidecar crash/restart is visible in SystemPane.
- Desktop packaging does not fork command authority or persistence rules.
- If sidecar supervision is unreliable, ship web React first and keep Tauri beta-gated.

### Phase 10: Vanilla Cockpit Retirement

Estimate: 1-2 weeks after parity is proven.

Work:

- Flip `/app` to React.
- Keep vanilla at `/legacy-app` for one release only, or remove after rollback window.
- Remove Cesium from the active app surface only after no React pane depends on it.
- Update asset cache stamping/deploy docs for React bundle and preserve the existing cache-bust discipline noted in AGENTS.

Kill-gate:

- Full signed-in Playwright suite passes on React across desktop/mobile.
- Existing backend suite remains green.
- Route registry coverage is 100% for pane-backed routes.
- All migrated PRD rows have `[REQ:]` evidence or are marked partial/open honestly.
- Vanilla can be removed only when no production workflow requires it and rollback path is documented.

## 4. Risks, Unknowns, and Effort

### Confirmed Risks

1. Frontend rewrite size is real and large.
   Confirmed by measured `cockpit.js`/`index.html` sizes and 13 domain panes (`docs/geolibre_migration_assessment_2026-07-03.md:13-14`, `docs/geolibre_migration_assessment_2026-07-03.md:42-45`, `stewie/server/web/assets/cockpit.js` 6,321 LOC, `stewie/server/index.html` 1,599 LOC).

2. MapLibre/deck do not remove all CRS/frame risk.
   The 3D lunar-globe risk is defused by the 2D decision, but the assessment still establishes MapLibre/deck as Earth/WebMercator-oriented (`docs/geolibre_migration_assessment_2026-07-03.md:50-56`). STEWIE still must be honest about body CRS, order frame, and transforms.

3. Current body support is not a plugin seam.
   Body values and regime rules are hard-coded in `BODIES` and helper functions (`stewie/specs/bodies.py:51-196`). A registry refactor touches planner validation, `/models`, `/bodies.json`, UI dropdowns, and tests.

4. Current physics support is not one swappable object.
   Tier-2 physics is spread across terramechanics functions, planner context, slip/endurance, column authority, and FORGE bearing (`stewie/physics/terramechanics.py:52-364`, `lode/planner_model.py:70-90`, `lode/planner_endurance.py:195-213`, `forge/bearing.py:50-66`). A `PhysicsBackend` must wrap existing behavior first, not replace it.

5. Chrono is not release-ready as an authority backend.
   The SCM exporter is a stub and explicitly leaves mass/density surrogate-side (`scripts/chrono_scm_export.py:2-33`, `scripts/chrono_scm_export.py:214-216`). Selecting Chrono for release/execute before hybrid mass-conservation closure would violate STEWIE's authority rule.

6. Route/client coverage is broad.
   There are 140 router-owned API routes, with SSE, binary, static, auth-gated, and compute-heavy routes. A generated client alone will not handle every route kind safely.

### Inferred Risks / Spikes Needed

1. Local projected MapLibre mode.
   Need a spike to prove MapLibre can be used comfortably as an engineering-order-frame viewport without misleading geodetic behavior. Confirmation: render Haworth DEM, order-frame axes, and deck overlays; round-trip control points through backend transform endpoints.

2. DuckDB-WASM data volume.
   Need a browser memory/performance spike with real FR-10/Haworth/mission-package payloads. Confirmation: query latency and memory budget on representative mission packages.

3. OpenAPI completeness.
   Need a generation spike. Some routes may use raw dicts or binary responses; generated types may be weak. Confirmation: generated client compiles and route registry has fixtures for all pane-backed routes.

4. Tauri sidecar supervision.
   Need a sidecar process lifecycle spike on target OSes. Confirmation: cold start, shutdown, crash, port conflict, logs, and data-dir behavior.

5. Backend extension blast radius.
   BodyProfile/PX refactors can easily touch planner, reports, UI, model registry, tests. Confirmation: implement Tier-2 adapter with compatibility tests before exposing UI selection.

### Per-Phase Effort Estimate

| Phase | Estimate | Risk |
|---|---:|---|
| 0 ADR/inventory | 1 week | Low |
| 1 React shell/API client | 2-3 weeks | Medium |
| 2 2D map spike | 2-4 weeks | High until proven |
| 3 Body/physics foundation | 3-5 weeks | High backend contract risk |
| 4 DuckDB-WASM | 2-3 weeks | Medium |
| 5 Report pane | 3-4 weeks | Medium; calibrates pane cost |
| 6 Plan pane | 5-8 weeks | High; authoring/workflow parity |
| 7 Rehearse/Validate/Release/Execute | 6-10 weeks | High; authority/evidence risk |
| 8 Secondary/control panes | 5-8 weeks | Medium-high; many surfaces |
| 9 Tauri packaging | 3-6 weeks | Medium |
| 10 Vanilla retirement | 1-2 weeks | Medium; rollback/deploy |

Total rough order: 7-12 months for one focused senior builder, shorter with parallel frontend/API/backend lanes after Phase 2/3 gates. The earlier assessment's 3-5 months covered the pane rewrite only (`docs/geolibre_migration_assessment_2026-07-03.md:13-14`); adding 2D map, API generation, DuckDB, Tauri, BodyProfile, and PhysicsBackend makes the full program larger.

### Top Unknowns That Could Sink the Plan

1. 2D map product adequacy.
   If operators need the removed 3D terrain/globe affordances for trust or planning, 2D may be accepted technically but fail product parity. Confirmation: Phase 2 operator review with real Haworth plan authoring.

2. Plan authoring parity.
   The Plan pane is the densest surface: site/body/fleet/orders/layers/GIS/query/profile/export/solve. If React/deck edit sessions cannot match current authoring speed and correctness, the rewrite stalls at Phase 6.

3. Physics/backend abstraction leakage.
   If physics behavior remains too intertwined with mission planner internals, a clean backend selector may become a label rather than a real seam. Confirmation: `PX-01` Tier-2 adapter passes byte-compatibility and all downstream planner/report/release surfaces read the selected backend id.

4. API/generated-client mismatch.
   Raw dict endpoints and binary/SSE routes can weaken type guarantees. Confirmation: `API-01`/`API-02` coverage gate and fixture tests.

5. Tauri operational complexity.
   Desktop sidecar packaging can create a second operational product with update/log/auth/persistence differences. Confirmation: Phase 9 beta with web parity and visible sidecar state.

## 5. Non-Negotiable Acceptance Rules

- Vanilla cockpit stays live until React pane parity is proven.
- No pane flip without signed-in browser evidence, mobile fit, route registry coverage, fixtures, and rollback.
- No client-side mutation of conserved terrain.
- No display-only/advisory layer may become planning/release/execute input without backend eligibility.
- No Chrono/backend selection may imply mass-conserved authority until the backend reports and proves `conserves_mass=true`.
- No BodyProfile numeric field may be fabricated; missing data is `null` plus provenance/confidence labels, following current `bodies.py` discipline (`stewie/specs/bodies.py:3-7`).
- Release/Execute surfaces must show body profile, physics backend, product mode, runnable profile, sensor/map freshness, and command eligibility before action.

## 6. Packaging structure (2026-07-03, Claude + Aaron)

STEWIE is ALREADY a multi-package monorepo (`stewie` + `dart`/`lode`/`leap`/`forge`, one version,
editable-installed). Question raised: split into INDEPENDENT PyPI packages by domain (mapping / navigation /
perception / planning / geotech / terramechanics / physics)? **DECISION: no independent-repo split; keep the
monorepo; optionally workspace-ify; extract only the two truly-independent + citable pieces.**

Rationale (grounded in the import graph, measured 2026-07-03):

- Cross-subsystem coupling is heavy and LOAD-BEARING: `dart` imported 164x, `lode` 143x, `stewie`-core 95x,
  `leap` 17x, `forge` 3x. dart/lode/core share `stewie.contracts` + the world model by design — their
  "independence" is illusory; untangling it would break the conservation/provenance guarantees or create
  version-pin hell.
- N independently-versioned packages ADD ceremony for a solo builder (release ordering, pins, N CI pipelines)
  — the OPPOSITE of "streamline". The monorepo-with-editable-install already gives clean boundaries + isolated
  test suites (dart 80 / lode 55 / leap 8 / forge 1) at no release cost.
- Packaging is organizational, not a RUNTIME optimization: it buys boundaries + reusability + citability, not
  speed.
- The 7-domain split CUTS ACROSS the existing DART/LODE/LEAP/FORGE boundaries (FORGE = geotech + terramechanics
  + physics; LODE = planning + mapping; DART = nav + perception + autonomy) — a re-decomposition is churn on
  top of the coupling. Keep the grounded subsystem boundaries.

DO:

1. Keep the monorepo. Optionally workspace-ify (uv/hatch workspace: one repo, multiple distributions, ONE
   shared version, atomic cross-package commits) if per-subsystem `pip install` is wanted.
2. Extract + publish the two low-coupling, standalone-valuable, CITABLE pieces:
   - `forge` (terramechanics + geotech/bearing) = the body-aware analytical layer, i.e. the "PlanetGroundhog"
     from the geotech discussion. 2 modules, imported 3x, numpy-only.
   - `bodies` / `BodyProfile` (planetary regolith parameter registry). Low coupling, reusable, citable.
3. This falls OUT of the PX + BD refactor: once `PhysicsBackend` + `BodyProfile` sit behind clean interfaces,
   the interface IS the package boundary, so extracting `stewie-forge` / `stewie-bodies` is nearly free. It is
   NOT a third concurrent structural initiative — it is a by-product of the PX/BD lanes. Sequence: PX/BD ->
   forge/bodies decoupled -> publish.

DON'T: split the coupled core (contracts / twin / runtime / server / dart / lode) into independent repos;
re-decompose by the 7 domains.

See also `docs/traversal_compaction_layer_2026-07-03.md` (a new world-model feature captured this session).
