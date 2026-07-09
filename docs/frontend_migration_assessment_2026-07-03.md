# Rebuilding STEWIE on GeoLibre — honest effort assessment

**Date:** 2026-07-03 · **Author:** review pass (staged for Aaron, not committed) · **Question:** how hard would
it be to rebuild STEWIE on top of [opengeos/GeoLibre](https://github.com/opengeos/GeoLibre)?

## TL;DR

"Rebuild on GeoLibre" is **a frontend migration, not a rebuild** — STEWIE's value (the Python
DART/LODE/LEAP/FORGE core, physics, RL, runtime spine, 140 API routes) is untouched and would sit behind
GeoLibre exactly as GeoLibre's own "optional FastAPI sidecar" pattern intends. The cost is concentrated in
two places, one bounded and one not:

1. **Re-implementing 13 domain ConOps panes** (~8,000 LOC of vanilla-JS cockpit) as React components —
   bounded but large (**~3–5 months** of focused frontend work).
2. **Porting the globe from Cesium to MapLibre/deck.gl on a lunar body** — **unbounded risk**. Cesium
   renders arbitrary ellipsoids (the Moon) natively; MapLibre/deck.gl are Web-Mercator/WGS84 engines built
   for Earth. This is either a downgrade (lose the 3D globe for a 2D polar-stereographic map) or a research
   project.

And it re-runs the one thing this project already tried and reverted: a big-bang React rewrite (`55c44c6`,
black-screened on Cesium init; the standing decision is *strangler-fig the vanilla cockpit, not another React
rewrite*).

**Verdict:** don't rebuild on GeoLibre. The single genuine gain (client-side spatial queries via DuckDB-WASM)
is **additive and borrowable without adopting the platform**. Recommendation and the cheaper path are at the
bottom.

## What GeoLibre is (and isn't, for us)

A modern MIT GIS **data** platform (React + TypeScript + MapLibre GL JS + deck.gl + DuckDB-WASM Spatial +
Tauri v2, optional FastAPI sidecar). It is excellent at import/style/query/edit of Earth geospatial data
(GeoJSON, Shapefile, GeoParquet, COG). It has **no** physics, simulation, RL, robotics, mission-planning, or
non-Earth body support. So it can host STEWIE's *map/GIS surface*, not STEWIE's *engine* — the engine stays
Python and stays exactly where it is.

## Component-by-component effort (grounded in the real tree)

| STEWIE component | Size (measured) | Under GeoLibre | Effort | Risk |
|---|---|---|---|---|
| Python core (DART/LODE/LEAP/FORGE, physics, RL, planner, runtime spine) | — | **unchanged** — becomes GeoLibre's FastAPI sidecar | ~0 | none |
| 140 API routes (36 routers) | 140 endpoints | unchanged; React client calls them | low (client bindings) | low |
| The globe | 142 Cesium refs in `cockpit.js`, 8 in `index.html` | **Cesium → MapLibre + deck.gl** | **very high** | **very high** (lunar CRS) |
| 13 ConOps panes (plan/rehearse/validate/release/execute/report + fleet/construction/models/trainer/admin/settings/system) | `cockpit.js` 6,321 LOC + `index.html` 1,599 LOC | **rewrite as React components** — GeoLibre provides none of these | high (the bulk) | medium |
| 41 pure render modules (38 node tests) | framework-agnostic HTML builders | **partial reuse** (call via JSX/innerHTML) or port; re-target tests | medium | low |
| Client spatial queries | none today | **DuckDB-WASM** over the FR-10 layer manifest | new capability | low |
| Desktop shell | existing Electron app (`desktop/`) | Tauri v2 (lateral swap) | medium | low, marginal gain |

## The three hard problems, honestly

**1. Lunar CRS on an Earth-centric map engine (the real blocker).** STEWIE is body-aware: lunar datum radius
1,737,400 m, polar-stereographic work areas, NASA Trek WMTS on Cesium's Moon ellipsoid. Cesium supports
arbitrary ellipsoids out of the box. MapLibre GL's projection support is Mercator + an Earth-WGS84 globe;
deck.gl assumes Web-Mercator geo. There is no first-class "render body X" knob. Options: (a) accept a flat 2D
polar-stereographic map and lose the 3D globe STEWIE has today; (b) invest heavily in custom projection /
non-Earth handling on MapLibre; (c) keep Cesium *alongside* GeoLibre (then you haven't really rebuilt on
GeoLibre, you've bolted its panels next to your globe). None is cheap, and (a) is a product downgrade.

**2. GeoLibre gives you zero of the 13 panes.** The ConOps spine (Plan · Rehearse · Validate · Release ·
Execute · Report) plus Fleet/Construction/Models/Trainer/admin surfaces are STEWIE-specific mission-ops UI —
build queues, evidence cards, the release sign-off lifecycle, the /program board. All ~8,000 LOC of it gets
re-authored in React. This is the bulk of the calendar time and it is *pure re-implementation* — you are not
buying UI from GeoLibre here, you are paying to move UI you already have into a new framework.

**3. You already ran this experiment.** The React rewrite was attempted and reverted (`55c44c6`, black-screen
on Cesium init). The architectural decision of record is strangler-fig the vanilla cockpit. "Rebuild on
GeoLibre" is that same big-bang rewrite at *larger* scope (a whole app shell, not just React). The failure
mode that killed it last time — the globe init — is exactly the hardest part above.

## The one genuine gain — and the cheaper way to get it

The real thing GeoLibre would give STEWIE is **DuckDB-WASM client-side spatial queries** over the layer
catalog. That is a good idea. But it is **additive**: STEWIE already built the typed layer manifest (FR-10),
the open GeoParquet/COG/GeoJSON mission package (BA-11), and the OGC/WMS + ArcGIS-boundary seam (FR-12) this
same session. You can drop DuckDB-WASM into the *existing* cockpit as one panel over the FR-10 manifest
**without** a framework migration. Same for MapLibre — it can be added as an *alternate 2D layer viewer* beside
the Cesium globe, not as a replacement for it.

That is the actual recommendation from the earlier assessment, now quantified: **borrow the component at the
interop seam you already own; do not adopt the platform.**

## If you nonetheless want to proceed — phased plan with off-ramps

Never big-bang. Each phase ships value and has a kill gate.

- **Phase 0 — spike (1–2 wk).** Stand up GeoLibre locally, point its FastAPI sidecar at STEWIE's backend,
  and try to render the **Haworth DEM (COG) as one MapLibre layer on the lunar body**. *Gate:* if the lunar
  globe/CRS doesn't render faithfully in ≤2 weeks, **stop** — problem #1 is the whole ballgame and it failed.
- **Phase 1 — one pane, side-by-side (3–4 wk).** Re-implement the single simplest read-only pane (Report or
  the /program board) as a React component talking to the live backend, deployed *next to* the current
  cockpit. *Gate:* honest LOC + hours actuals vs the estimate; extrapolate to 13 panes before committing.
- **Phase 2 — DuckDB-WASM over FR-10 (2 wk).** The genuine-gain slice. Worth doing **whether or not** you
  migrate — so do it first as a standalone win in the current cockpit; if the migration dies at Phase 0/1 you
  still keep this.
- **Phase 3+ — pane-by-pane strangler (months).** Only if Phases 0–1 cleared their gates. Migrate panes one
  at a time, keep Cesium until MapLibre-lunar is proven, retire the vanilla cockpit last.

## Recommendation

**Do not rebuild STEWIE on GeoLibre.** The backend is safe either way, so the entire cost is a frontend
rewrite dominated by (a) porting a faithful lunar globe onto an Earth-centric engine and (b) re-authoring
8,000 LOC of domain UI GeoLibre does not provide — while repeating a rewrite that already failed. The only
real prize (DuckDB-WASM client queries) is a two-week additive win on the interop layer STEWIE already built
this session. Take that prize; keep the core and the Cesium globe.

If the motivation is something specific GeoLibre does well (multi-platform packaging, prettier basemaps,
client SQL), name it and we'll borrow that one thing at the seam — that is a bounded, reversible win, which
a platform migration is not.
