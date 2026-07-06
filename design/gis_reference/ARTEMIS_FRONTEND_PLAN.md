# Artemis Front-End Integration Plan (GeoLibre-native)

*Planning deliverable produced by a Fable-5 agent that read the real code on branch `artemis-lunar-terrain`
(store, project schema, shell layout, right-panel registry, plugin API, the mercator-lock comment, and the
four Artemis files). Front end only; design doc, no code. Line references were read this session.*

## Executive summary

The single most important architectural move: promote the per-site OrbitView terrain from a DOM-event modal to
a **store-driven, docked Site Inspector that rides GeoLibre's existing right-panel registry** (the same
`registerRightPanel` / dock system that powers `PluginRightPanel`, with `replace-style` and positional docks
already built). Selection state becomes one nullable field in the `ui` slice of `packages/core/src/store.ts`,
which the pins, the inspector, and the `?terrain=` deep link all read and write; the CustomEvent and the modal
are deleted. Lunar data enters the normal layer tree: vectors (site polygons, PSR outlines) are ordinary
`GeoLibreLayer` records that render fine on the globe at any latitude, while anything raster south of ~82°S is
honestly declared un-drapeable and routed to the inspector's OrbitView, which we keep as the only
pole-truthful renderer (verified: `_GlobeView` goes black at 88-90°S; the MapboxOverlay is mercator-locked per
`packages/plugins/src/plugins/deckgl-viz/overlay.ts:148`). The pole gets an explicit, honest UI treatment
(banner + fly-to-pole affordance + vector overlays) instead of pretending the smeared OPM tiles are imagery.

## Phase 1 — Store-driven site selection; retire the CustomEvent

**Goal:** one source of truth for "which site is open." Smallest possible diff; ships alone.

- `packages/core/src/store.ts`: add `ui.siteInspectorSiteId: string | null` + `setSiteInspectorSite`, following
  the `ui.loadEditorFeaturesLayerId` pattern (ephemeral, auto-excluded from undo `partialize` and the project
  file). Clear it in `newProject`/`loadProject`.
- New `packages/core/src/sites.ts` (exported from core like `GEOLIBRE_BODY`/`PLANET_BASEMAPS`): the 8-site
  catalog now hardcoded in `useArtemisSites.ts:13-22`, plus `body`, DEM asset base path, provenance (PGDA
  Product 78, LOLA 5 m, gdalinfo centres). Pins, inspector, deep link, Phase 3 layers all read this module.
- `useArtemisSites.ts`: pin click calls `setSiteInspectorSite(s.id)` instead of `window.dispatchEvent`.
- `ArtemisTerrainOverlay.tsx`: interim, subscribe to the store field (deleted in Phase 2).
- `main.tsx`: keep `?terrain=<Site>` as the chrome-free standalone mount; add a read-once `useSiteDeepLink()`
  in the full-app path for a new `?site=<Site>` param that hydrates the store. Two params, one meaning each.

**Risk:** low. Only trap: keep the site id out of undo `partialize` and the project schema.

## Phase 2 — Site Inspector as a docked right panel

**Goal:** replace the modal with a first-class panel that coexists with the map.

Options weighed: keep modal (reject — covers the map); second synced map pane (reject — OrbitView is local
Cartesian, "sync" with a lat/lon camera is meaningless); **docked right panel via the existing registry
(recommend)** — matches the Layers/Style model, docking + resize already exist, hosts its own `Deck` instance
independent of the mercator-locked overlay (which is why it renders the pole).

- Refactor `PolarTerrain.tsx` → `components/terrain/TerrainOrbitView.tsx` (presentational, props-driven, no
  `location.search` reads; keeps the Deck lifecycle + `.bin`/`.json` fetch). `PolarTerrain` becomes a thin
  wrapper keeping URL-param camera overrides for the standalone route only.
- New `components/panels/SiteInspectorPanel.tsx` (composed like `StylePanel`): header, `TerrainOrbitView`,
  attributes (from meta JSON, PolarTerrain.tsx:142-147), provenance (Phase 1 catalog), actions — "Fly to site"
  (`setMapView`), "Copy deep link" (`?site=`), "Open standalone" (`?terrain=`), "Maximize" (reuse `Dialog`).
- `DesktopShell.tsx`: render next to `StylePanel`/`PluginRightPanel`, driven by `ui.siteInspectorSiteId`.
  Prefer registering through the right-panel registry (inherits dock stepping + merge/detach) over hardwiring.
- Delete `ArtemisTerrainOverlay.tsx` + its import at parity. Lazy-import `TerrainOrbitView` (keep deck.gl out of
  the boot chunk).

**Risk:** a second live WebGL context; `deck.finalize()` on close (done), cache decoded buffers per site for
instant reopen; wide default panel width (an OrbitView in a 320 px rail is cramped — rely on maximize).

## Phase 3 — Lunar layers into the store layer tree, legend, provenance

**The split (load-bearing):** landing-site polygons + PSR outlines = real MapLibre `geojson` layers (vectors
render on the globe at any latitude); global WAC = basemap; per-site 5 m DEM + illumination + slope/hazard =
**inspector-only** (OrbitView / deck sublayers) because raster can't drape at the pole.

Inspector-only layers still appear in the tree: mirror them as `GeoLibreLayer` records (Components-plugin
precedent) with `metadata.renderTarget: "site-inspector"` + provenance; `MapController.syncLayers` skips them
(one guard, like `externalNativeLayer`); the inspector honors their `visible`/`opacity`. Buys legend +
provenance + toggles with no new panel UI. Don't invent a new `LayerType` yet.

- New `lib/lunar-layers.ts` (or extend `sites.ts`): the catalog, seeded on moon-build `newProject` via existing
  `addGeoJsonLayer`/`addTileLayer`. This is the on-ramp for the PRD §7.B 65-layer catalog / 24 GIS rows.
- `packages/map`: one-line sync skip for `renderTarget === "site-inspector"`.
- `useArtemisSites.ts`: pins read the catalog/layer; clicking a site polygon goes through existing identify +
  also calls `setSiteInspectorSite` (satisfies "click pin OR polygon").

**Risk:** seeded layers enter undo + saved project (correct) — body-gate the seeding; keep `parseProject`
tolerant on Earth builds; ship simplified PSR geometry via `source.url` so `prepareLayerForSave` strips embeds.

## Phase 4 — Honest pole presentation

**Ship now:** keep globe default; add an **imagery-gap banner** (reuse `MapModeBanner`) south of ~80°S — "No
basemap imagery below ~82°S. Site terrain is available at 5 m in the Site Inspector," with a per-site action;
optionally auto-fade `basemapOpacity` below the threshold (only when untouched) + a latitude-ring graticule
(vector) so the frame is never empty. Add a **"South Pole" fly-to** button. The per-site OrbitView stays the
truth path.

**Deferred spike (do NOT build now):** a regional polar-stereographic map mode — MapLibre only does
mercator/globe, so this means pre-projected polar-stereo tiles through a fake-mercator scheme + a proj4
coordinate-readout shim, with identify/measure/geocode either disabled or transformed. It is the only route to
a draped, multi-layer pole map (where the full §7.B polar raster catalog would land) but it is a projection lie
with a long tail. One-week spike with a go/no-go; must not block Phases 1-4.

## Phase 5 — Consolidation

Delete the `artemis:open-terrain` CustomEvent + listeners (grep-gate in review); unit tests (store setter,
catalog integrity, deep-link parse); Playwright e2e (moon boots on polar view, pin → inspector, Esc/close
clears the store field, `?site=` deep link, `?terrain=` still standalone); i18n all new strings via `t()`;
branch + PR, never `main`; new tile hosts need the Tauri CSP allowlist.

## Reuse map

**Reuse:** Zustand `ui` slice + its undo/persistence exclusions · right-panel registry (docks, merge/detach) ·
`Dialog` from `@geolibre/ui` · `addGeoJsonLayer`/`addTileLayer` · `syncLayers` + legend + `layer.metadata`
provenance · `MapModeBanner` · lazy-chunk pattern · the existing `?terrain=` mount.
**Not reused:** the mercator-locked `MapboxOverlay` deck path for anything polar; `MapGrid` panes for terrain.
**Build new:** `TerrainOrbitView`, `SiteInspectorPanel`, `packages/core/src/sites.ts`, the lunar layer manifest,
the pole banner + fly-to, the sync skip.

**Ordering:** Phase 1 is the keystone (everything keys off `ui.siteInspectorSiteId`); Phase 2 is the visible
win; Phase 3 makes data first-class and fully unlocks the click-polygon inspector; Phase 4 is UX honesty on
Phase 3's vectors; Phase 5 locks it in. The polar-stereo mode is the only open architectural fork — isolated as
a spike so it can't stall the rest.
