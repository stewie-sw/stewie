# GW-11 viz3d.js wiring — execution notes (run-verified prerequisites, 2026-07-09)

Backend redeploy DONE + verified (this session): FEE draft_n(large)=16.7205, healthz 200,
`/world/layer-catalog` has `missing_layer_kinds` (LY-04 live), `/layers/globe/changed_terrain.png`
200/6316 B (LY-07 live). Rollback tag `stewie-backend:rollback` -> dec2d274. CI green @ c9143333.

Wave-1 modules node-tested GREEN: frame 13/13, scalebar 21/21, layers 24/24.

## Two corrections to the frame.js integration note (run-verified, must apply)

1. **DROP `/dem/site_meta`.** It returns **401** on the live backend AND is NOT in the artemis nginx
   key-injection allowlist (only `/dem/site_lonlat`, `/dem/sources`, `/api/plan|structure|construction|
   resync/compare` are). So the client can't reach it. Instead build the coarse K×K lon/lat grid over the
   **rendered window** `[x0, x0+window_m] × [y0, y0+window_m]` using `/dem/site_lonlat` (key-injected,
   already used by `_hoverPick`). All inputs come from the heightfield_full headers I already have:
   `meta.x0, meta.y0, meta.window_m, meta.z_min, meta.z_max`.
   ```
   const K = 9; const lon = new Array(K*K), lat = new Array(K*K);
   await Promise.all(... /dem/site_lonlat?x=(x0 + i/(K-1)*window_m)&y=(y0 + j/(K-1)*window_m) ...);
   FRAME.setLonLatGrid({ x0: meta.x0, y0: meta.y0, dE: window_m/(K-1), dN: window_m/(K-1), cols:K, rows:K, lon, lat });
   FRAME.setOrigin(meta.x0, meta.y0); FRAME.setMeanElev((z_min+z_max)/2); FRAME.setVex(S.vex);
   ```
   Cache per site (S._frameGridCache[site]); guard globe on grid success (`S._frameReady`). Flat mode
   never touches the grid, so it renders even if the grid fetch fails.

2. **UV-based hover/plot/measure recovery (solves the globe-mode inverse gap).** frame.js exposes no
   `place()` inverse, and recovering elev from a raycast hit on the globe cap is hard. But the mesh has a
   uv attribute (`uv.x=i/(n-1), uv.y=j/(n-1)`), and `Raycaster.intersectObject` returns interpolated
   `hit.uv` — invariant to flat/globe placement. So `_raycastSurface` returns the hit; consumers derive
   `e_m = uv.x*(n-1)*step`, `n_m = uv.y*(n-1)*step`, `elev = heightAt(e_m,n_m)+z_min`. Replaces the
   flat-only `p.y/vex + z_min`. Works identically in both modes; no frame.js inverse needed.

## Placement routing (frame.js note b), datum + framing + vex

- Route mesh (`_buildMesh`), km grid + graticule (`_lineOnSurface`), graticule labels, plot/measure
  markers through `FRAME.place(e_m, n_m, heightAt+z_min)` with ABSOLUTE elevation. Mask nodata (skip NaN z).
- Datum shift: place() ENU y = `exaggerate(elev) = meanElev + vex*(elev-meanElev)` (absolute-about-mean),
  NOT the current zmin-relative `hh*vex`. So camera framing must target the tile center in whatever mode:
  `const c = FRAME.place(window_m/2, window_m/2, (z_min+z_max)/2); S.target.set(c.x,c.y,c.z);`
- `setVertExag(k)`: `FRAME.setVex(k)` then — FLAT: cheap y-only update `pos.y[i]=FRAME.exaggerate(baseH[i]+z_min)`;
  GLOBE: full `_buildMesh()` (radial displacement scales x,y,z). Re-drape grid/graticule/markers as today.
- `setGlobe(on)`: `FRAME.setMode(on?'globe':'enu'); _buildMesh(); re-drape grid/graticule/plots/measure;
  reframe target`. Guard on `S._frameReady` (globe needs the grid). Expose `STEWIE_VIZ.setGlobe` + `get globe`.

## Host-page work (both viz hosts) — modules are NOT yet loaded anywhere

- Standalone `/viz` page (routers/pages.py HTML + viz_haworth_page.js): add `<script src="/assets/viz3d/
  frame.js"></script>` (+ scalebar.js, layers.js) BEFORE the `viz3d.js` module tag; add a Globe toggle +
  HUD container divs (scale bar / north / sun / readout) + a layer-stack panel.
- `/ide` MissionTerrain3D plugin (gis/qwc2/js/mission/terrain3d.js): same script tags into the qwc2 build +
  the plugin's mounted DOM; then rebuild qwc2 CLEAN (rm node_modules/.cache), re-stamp, deploy artemis-web.

## Verify order (incremental, per craft discipline — one axis, deploy, Playwright, repeat)

1. frame wiring -> backend rebuild -> Playwright `/viz`: terrain still renders; hover elev correct (flat);
   Globe toggle -> curved cap, overlays stay registered; vex slider still lifts relief.
2. scalebar HUD -> Playwright: scale bar reads a plausible km, north-arrow SIGN (the one claim to verify
   live per scalebar.js header), sun arrow, readout.
3. layer stack -> Playwright: composite drape + legend/opacity/visibility panel.
4. wire into /ide MissionTerrain3D -> qwc2 clean rebuild + artemis deploy -> Playwright /ide 3D +
   changed_terrain drape. Flip §7.B GW-11 glyph N|N|N->D|D|D + [REQ:GW-11] + req_trace/continuity/artifacts.
