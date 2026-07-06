# §7.B Reconciliation Proposal — GeoLibre as the mission workbench (2026-07-05)

Proposal to reconcile PRD.md §7.B (GIS Mission Workbench, written 2026-07-04) against what the GeoLibre/Artemis
build proved and against Aaron's decisions this session. **Not yet applied to PRD.md** — review gate first,
because PRD.md drives the autonomous loop + the machine-count artifacts (`gen_program_snapshot.py` etc.).

## Locked decisions (2 question rounds, 2026-07-05)

1. **Integration:** GeoLibre becomes THE §7.B workbench front end, wired to the STEWIE back-end (`/layers`,
   `/dem/*`, `/executive/*`, `/physics/*`, `/profiles`, `/evidence`, the SSE/WS stream). The separate cockpit
   is superseded over time.
2. **Map substrate:** GW-05's "MapLibre local polar-stereographic frame + draped LOLA terrain-RGB" is
   **infeasible** (proven: MapLibre is mercator/globe only, clamps centre to ~85°, can't drape raster at the
   pole; deck overlay mercator-locked; `_GlobeView` black at 88-90°S). Replace with: mercator/globe regional
   overview + per-site deck.gl **OrbitView** on the native polar-stereo DEM. **Mission-accurate throughout.**
3. **Layout:** IDE-style **dockable** workspace (map + inspector + engine panes rearrangeable); **end goal a
   full Tauri v2 desktop app** with multi-window / multi-monitor (D1: keep Tauri, no Electron migration).
4. **Engine panes:** real-time Godot/Gazebo/RViz/ROS2 views are a hard requirement for live mission use;
   greenfield (no rosbridge/Foxglove/gzweb/Godot-web today).
5. **Mission accuracy = correct coordinates + distance/measurement FIRST, then the correct physics layer.**
6. **Build order:** GIS core → runs/evidence → engine panes.
7. **Mechanics:** rewrite affected §7.B rows in place + re-glyph.

## Row-by-row reconciliation

### Rewrite (assumption disproven or target changed)

- **GW-05 (map substrate)** — REWRITE. New acceptance: *"GeoLibre renders a mercator/globe regional overview
  (WAC basemap to ~82°S) PLUS a per-site deck.gl OrbitView of the native polar-stereographic 5 m LOLA DEM
  (85-90°S) as mission-accurate 3D terrain; site coordinates round-trip `/dem/site_xy` ↔ `/dem/site_lonlat`
  within tolerance; selenographic frame, explicit no-WGS84/Earth claim; vector layers place at any latitude; an
  honest imagery-gap banner appears below ~82°S. (extends GL-01; needs GW-00 + BW-02)"*. Glyph **N|N|N**
  (OrbitView renders today only from *static local* data, not `/dem`; the wiring + overview + round-trip are
  unbuilt). Drop the polar-stereo-frame claim; it moves to Open Decision D2 as a spike.
- **GW-06 (layer tree)** — keep, bind to BW-01. Add the *drapeable-vs-inspector split*: site/PSR polygons are
  real MapLibre vector layers; 5 m DEM / illumination / slope carry `renderTarget: "site-inspector"`. **N**.
- **GW-07 (selection + inspector)** — keep; realized by the docked **Site Inspector** panel (Fable plan Ph2),
  store-driven via `ui.siteInspectorSiteId`. **N**.
- **GW-08 / ED-01 (edit session)** — keep; GeoLibre-native, writes only through backend routes. **N**.
- **RT-03 / RT-04 / RT-05 (Gazebo / RViz-Foxglove / Godot)** — REWRITE as **dockable real-time panes** inside
  the GeoLibre workspace (not standalone surfaces), bound to the selected run/profile, evidence-only. Transport
  per Open Decision D3. **N**.

### Re-glyph (done-in-cockpit ≠ done-in-GeoLibre)

- **GW-02 (workspace context)** D→**N**: the routeable context must be rebuilt in GeoLibre's store (one URL
  restores site/body/frame/layers/selection/mode/profile/run/role).
- **AU-01 (command-authority card)** D→**N**: re-implement in GeoLibre chrome.
- **LY-02 (layer-consumption inspector)** D→**N** for the GeoLibre surface (back-end data may exist).

### Stay green (pure back-end, front-end-agnostic — verified endpoints exist)

- **LY-01** (`/layers` catalog), **PH-01/PH-02** (`/physics/*`), **TM-02/TM-03** (terramechanics spine +
  layers), **RT-01** (`/profiles`), **GW-00** (CSP/deploy). Keep **D** — but LY-01 gains a *consumption*
  sub-clause: the catalog must expose `renderTarget` + drape-eligibility so GeoLibre can honour the pole split.

## New rows

- **WS-01 (P0)** — IDE-style dockable workspace shell: a dock/pane manager over GeoLibre's panel system hosting
  map, Site Inspector, and (later) engine panes; layout persists in the workspace context. *Keystone for the
  multi-pane goal.*
- **WS-02 (P1)** — Desktop app target: package the workspace as a **Tauri v2** desktop app with multi-window /
  multi-monitor (D1); engine panes detachable to a second monitor.
- **MA-01 (P0)** — Coordinate + measurement accuracy: every GIS/terrain surface shows selenographic lon/lat +
  local `site_xy` (no Earth claim) + scale; measurement (distance / slope / volume) computes in the local
  metric frame within stated tolerance. *(Aaron: "correct coordinates, distance calculations… first.")*
- **MA-02 (P1)** — Physics-layer accuracy: every route/volume/risk value surfaced in the UI carries its physics
  backend + calibration + source-class + uncertainty (front-end of PH-02/TM); unqualified values are visibly
  not release-eligible. *(Aaron: "then incorporating correct physics layer.")*
- **BW-01 (P0)** — GeoLibre consumes `/layers` + `/layers/legend` → the store layer tree (feeds GW-06).
- **BW-02 (P0)** — GeoLibre consumes `/dem/*` (heightfield / site_xy / site_lonlat / terrain_grid / georef) for
  the OrbitView + coordinate round-trip (feeds GW-05, MA-01).
- **BW-03 (P1)** — GeoLibre consumes `/executive/run` + `/executive/run/{id}/stream` (live) + `/evidence` for
  runs/evidence (feeds RT-02, EV-01).
- **RT-06 (P1)** — Real-time engine transport (D3 resolved: **web-native data + sidecar render**): rosbridge +
  Foxglove (WebSocket) for ROS2/RViz data-truth; Godot + Gazebo rendered by a sidecar and embedded; a
  real-time-latency SLA for mission use. Blocks RT-03/04/05.

## Re-optimized loop pick order (GIS core → runs/evidence → engine panes)

**Phase 1 — GIS core:** GW-00 · RT-00 → WS-01 → BW-01 · BW-02 → GW-05 → GW-06 · GW-03 → GW-07 → MA-01 →
GW-02 → GW-08/ED-01 → GW-04.
**Phase 2 — runs / evidence / accuracy:** AU-01 → BW-03 → RT-02 → EV-01 → MA-02 → PH-02 · TM-03 → TM-04 →
SD-01 → LY-02.
**Phase 3 — real-time engine panes:** RT-06 → RT-04 (RViz/Foxglove) → RT-03 (Gazebo on real DEM) → RT-05
(Godot) → WS-02 (desktop/Electron multi-window).

## Machine-count / artifact implications

- Net rows: +8 new (WS-01/02, MA-01/02, BW-01/02/03, RT-06); ~5 rewrites; 3 re-glyphs (GW-02, AU-01, LY-02
  D→N). `grep -cE "^\| (GW|LY|PH|TM|RT|AU|EV|SD|ED|WS|MA|BW)-"` rises by 8.
- `scripts/req_trace.py` must still reconcile (new rows N|N|N, no `[REQ:]`); regen `gen_program_snapshot.py` /
  `gen_status.py` / `gen_release_manifest.py`; the §0 snapshot total shifts (~339 → ~347, minus any board-count
  effect of the 3 D→N re-glyphs). Commit code+PRD first, then artifacts (FS-01 gate); each new row needs its
  FANOUT_SPECS brief in the same commit.

## Resolved decisions (2026-07-05, round 3)

- **D1 — Desktop shell: keep Tauri v2** (no Electron migration). WS-02 targets Tauri multi-window/monitor.
- **D2 — Polar-stereo map mode: defer as a tracked spike.** Near term = OrbitView + vector layers + honest
  imagery-gap banner; add a scoped `SP-01` polar-stereo-mode spike row with a go/no-go (does not block GIS
  core). GW-05 keeps only the OrbitView + overview claim.
- **D3 — Engine transport: web-native data + sidecar render.** rosbridge + Foxglove for ROS2/RViz (the ROS
  real-time standard, data-truthful, lowest latency); Godot + Gazebo via a render sidecar embedded in the pane.
  Encoded in RT-06.

**Status:** analyze → compare → decisions all complete. Remaining to APPLY to `PRD.md`: edit the §7.B rows in
place, write a FANOUT_SPECS brief per new row (FS-01 gate), regen the 3 count artifacts, `req_trace` + row-count
reconcile, gate-green the full suite, commit code+PRD then artifacts on a branch → main ff. That is the
mechanical execution pass, held for the go.
