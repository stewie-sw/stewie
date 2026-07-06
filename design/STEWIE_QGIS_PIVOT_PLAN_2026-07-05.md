# STEWIE QGIS Pivot Plan — remove GeoLibre, dual-client QGIS workbench (2026-07-05)

**Directive (Aaron, verbatim):** "remove geolibre and use qgis, same needs, qgis first with lunar, then
design mission planning on top with all application integrations, then we will add private gates admin
settings etc"

**Decision update (Aaron, same day):** BOTH web AND desktop — a **dual-client** architecture, not an
either/or. Shared core = one lunar `.qgz` project + the STEWIE FastAPI backend as the single mission
brain. Desktop = QGIS Desktop + a PyQGIS mission plugin (power-analyst / mission-designer surface).
Web = QGIS Server publishing the SAME `.qgz` as OGC services to a browser client at app.stewie.space
(QWC2 or a custom viewer; salvage the existing cockpit), rosbridge/Foxglove for ROS. **Web-first** for
the hosted, gated deployment; desktop as the power companion.

**Status:** plan of record for the pivot. Supersedes the GeoLibre execution track of
`design/STEWIE_PRD_reconciliation_2026-07-05.md` (its backend rows and its mission-accuracy /
build-order / engine-transport decisions carry over; its GeoLibre-front-end realization does not).
PRD.md §7.B is NOT edited by this plan — §8 below records exactly which rows change and how, held for
the mechanical PRD pass.

---

## 0. Executive summary

We replace the GeoLibre/Artemis web-GIS front end (React + MapLibre + deck.gl, mercator-locked, broken
at the pole) with a **dual-client QGIS architecture**:

```
                    SHARED CORE (single source of truth)
       ┌──────────────────────────────────────────────────────────┐
       │  stewie_south_pole.qgz  (IAU_2015:30135 polar-stereo     │
       │  project: COG DEMs/slope, imagery, vectors, styling,     │
       │  provenance)            +                                │
       │  STEWIE FastAPI backend (the ONE mission brain:          │
       │  /layers /dem /plan /executive /evidence /physics        │
       │  /profiles /auth — all lifecycle + authority decisions)  │
       └───────────────┬──────────────────────┬───────────────────┘
                       │ opens directly       │ published by QGIS Server
                       ▼                      ▼  (WMS/WMTS/OGC API, Docker)
        DESKTOP CLIENT                   WEB CLIENT (app.stewie.space)
        QGIS Desktop + STEWIE            pole-truthful map viewport
        Workbench PyQGIS plugin          (OpenLayers-based; QWC2 spiked)
        (Qt-docked mission panes         + web mission UI salvaged from
        + engine panes)                  the existing cockpit
                                         + Foxglove/rosbridge panes
```

The pole problem dissolves in both clients: the lunar south-polar CRS is **already in the PROJ
registry on this host as `IAU_2015:30135`**, byte-identical to the CRS our on-disk COGs carry
(verified, §1); QGIS Desktop renders it natively, and QGIS Server renders it server-side so even the
browser — via OpenLayers or QWC2, both of which handle arbitrary projections, unlike MapLibre — gets
pole-truthful map images. The existing STEWIE backend needs almost nothing new to join this
architecture: it **already ships a WMS 1.3.0 endpoint written explicitly "so any QGIS/ArcGIS client
can consume them"** (`stewie/server/routers/ogc.py`) and a GeoJSON/COG GIS-export router
(`gis_export.py`), plus operator auth (PBKDF2 accounts, HMAC tokens, roles, invites) for Phase 3.

**The economics of dual-client (why this is cheap where it matters):** Phase 1 delivers BOTH surfaces
nearly for free, because Desktop and Server read the same `.qgz` — one project file is the entire GIS
substrate for both clients. The only genuine "build twice" cost is the Phase-2 **mission-planning UI +
engine panes** (Qt docks vs web components), and that cost is bounded by two rules: (1) the FastAPI
backend is the single brain — every lifecycle transition, eligibility check, authority decision, and
world-write happens server-side, so both UIs are thin renderers of the same API; (2) the web mission
UI is salvaged from the deployed cockpit (its lifecycle spine, run stream, evidence panes already
exist and are tested), not built from scratch.

Phases: **P1** shared core — QGIS + lunar, pole-truthful, both delivery paths stood up. **P2** mission
planning on top — web-first (cockpit + QGIS-Server map viewport), desktop plugin as the power
companion, all application integrations (runs, evidence, Godot/Gazebo/RViz/ROS2 panes). **P3** private
gates — Cloudflare Access + backend auth in front of the web client and QGIS Server, role-gated UIs,
admin/settings, operator distribution.

---

## 1. Ground truth (verified on this host, 2026-07-05)

Everything in this section is **confirmed**, with the evidence named. Inferred claims elsewhere are
marked.

| Fact | Evidence |
|---|---|
| The lunar south-polar CRS is first-class in PROJ here: `IAU_2015:30135` = "Moon (2015) - Sphere / Ocentric / South Polar", proj4 `+proj=stere +lat_0=-90 +lon_0=0 +k=1 +x_0=0 +y_0=0 +R=1737400 +units=m` | `projinfo IAU_2015:30135` run on this host |
| The geographic lunar CRS is `IAU_2015:30100` (lonlat, R=1737400) | `projinfo IAU_2015:30100` |
| The on-disk COGs carry **exactly that projection**: Polar Stereographic (variant A), lat_0=−90, sphere R=1737400 (WKT names it "unnamed" but the parameters are identical to 30135) | `gdalinfo .../cog/Site01/dem.tif` |
| COGs are real mission data: Float32, DEFLATE+PREDICTOR=3, LAYOUT=COG, internal overviews, NaN nodata, real stats (Site01 dem: 3200², min −523.2 m, max +1959.5 m, center 89°27′S); Haworth 1 m: 11660×12060, 5 overview levels, center 86°50′S | `gdalinfo` on Site01/dem.tif + Haworth_1m_dem.tif |
| Data on disk: `geolibre/apps/geolibre-desktop/public/data/cog/` = 946 MB (Site01/04/06/07/11/20/23/42 × {dem,slope} + Haworth_1m_dem 259 MB); raw polar-stereo GeoTIFFs + slope + Haworth 1 m SfS (537 MB) at `geolibre/data/lunar/` | `ls`/`du` both dirs |
| STEWIE backend already speaks OGC: `routers/ogc.py` is a WMS 1.3.0 GetCapabilities/GetMap over the globe layers, declaring `IAU_2015:30100` + CRS84, public + rate-limited, built for QGIS/ArcGIS clients | read `ogc.py` docstring + code |
| STEWIE backend already exports GIS interchange: `routers/gis_export.py` → RFC-7946 GeoJSON of a plan (orders, keep-outs, traverse, footprints) in selenographic lon/lat + a COG terrain export when rasterio is present | read `gis_export.py` |
| Backend mission surface exists: routers `layers` (`/layers/legend`, `/layers/globe/{kind}.png`, `/layers/globe/{kind}/bbox`), `dem` (`/dem/georef`, `/dem/site_xy`, `/dem/site_lonlat`, `/dem/heightfield`, `/dem/terrain_grid`, `/dem/{name}` …), `executive`, `evidence`, `plan`, `profiles`, `missions`, `fleet`, `rc`, `twin`, `world` | `ls stewie/server/routers/` + grep of layers.py/dem.py |
| Backend auth substrate exists for P3: `auth.py` (email+PBKDF2 password login → 12 h HMAC token, legacy shared-key bootstrap, must_set_password), `invites.py`, `operators_admin.py`, role machinery in `server.auth`/`server.deps` | read `auth.py` |
| GDAL 3.6.2 on host; Docker 29.6.1 **active**; QGIS **not installed** (`qgis`/`qgis_process` not found, no python `qgis` module) | `gdalinfo --version`, `docker --version`, `systemctl is-active docker`, `which` |
| GeoLibre fork state: branch `artemis-lunar-terrain`, 2 Artemis commits on upstream (`6cb4346`, `419a81d`), dirty tree (ARTEMIS_LAYERS.md, SiteLayers2D.tsx, ArtemisTerrainOverlay.tsx, PolarTerrain.tsx untracked/modified), encode scripts `cogify.sh`, `encode_terrain_points.py`, `encode_terrarium.py`, `encode_site_layers.sh` | `git log`/`git status` in /mnt/projects/geolibre |
| The layer catalog to honor: `ARTEMIS_LAYERS.md` (3 rendering paths, Trek/LROC/QuickMap endpoints, PGDA Product 78, PSR/illumination/site vectors) + the PRD2 ~65-layer catalog (`design/STEWIE_PRD2_gis_mission_workbench_2026-07-04.md` L204-278) | read both |

**Inferred (named check):** QGIS ≥3.34 resolves `IAU_2015:*` codes from its bundled PROJ db (PROJ has
shipped the IAU_2015 registry since 8.x; the host PROJ resolves it — confirm inside the installed QGIS
build at P1.0). QGIS packages for Debian 12 come from the qgis.org apt repo; QGIS Server ships as an
official Docker image (confirm at install). OpenLayers renders arbitrary projections via proj4js;
QWC2's client is OpenLayers-based (both from documented capability, verified at the P2.A spike).

---

## 2. Why QGIS wins here (the thesis, sharpened)

The Artemis session proved the negative: MapLibre cannot center past ~85°, cannot drape raster at the
pole, deck.gl's overlay is mercator-locked, `_GlobeView` goes black at 88–90°S. Every workaround
(per-site OrbitView point clouds, a 2D OrthographicView, hand-rolled proj4 readouts) re-implemented,
poorly, what a projection-native GIS does by default. QGIS:

- **Arbitrary project CRS.** Set the canvas (or the QGIS Server render) to `IAU_2015:30135` and the
  pole is the middle of the screen. Vector and raster layers in other CRSs (Trek's equirectangular,
  backend lonlat GeoJSON) reproject on the fly through PROJ — the exact capability MapLibre lacks by
  design. And because QGIS **Server** does the rendering for the web client, the browser inherits
  pole-truthfulness without a client-side projection engine: the web map consumes already-projected
  tiles/images, which is what breaks the mercator dependency that killed GeoLibre.
- **COG-native, float-native, queryable.** Our 946 MB of Float32 COGs load directly as raster layers;
  the Identify tool (desktop) and WMS GetFeatureInfo (web) return the real float32 elevation/slope; no
  `geotiff.js` range-read machinery, no 8-bit PNG previews, no `.bin` point-cloud encoding step. The
  entire "mission-accurate value readout" build queued in ARTEMIS_LAYERS.md §"COG-backed" collapses to
  built-in mechanisms on both clients.
- **Metric measurement at the pole.** In 30135 the frame is Cartesian meters with k=1 at the pole;
  polar-stereo scale error at 85°S is ≤0.2% (k = 2/(1+sin|φ|)), quantifiable and stated — MA-01's
  tolerance clause is satisfiable with arithmetic, not engineering.
- **Processing + PyQGIS.** Hillshade, slope, contours, viewshed, cost surfaces — the derived-layer
  factory the PRD2 catalog wants (`terrain.*`, `hazard.slope_nogo`) is `qgis_process` one-liners over
  the real DEMs, headless-scriptable and CI-testable.
- **One project, two clients.** The `.qgz` is simultaneously the desktop workspace and the QGIS Server
  publication — layer set, styling, and provenance are authored once and stay in sync by construction.
- **Qt docking (desktop) is WS-01.** The "IDE-style dockable workspace" row is a native QGIS
  capability (QDockWidget panels, floatable to other monitors).

What QGIS does **not** give us for free (honest): the web mission UI (rebuilt on the cockpit, §5.A),
interactive web editing (the browser draws features and POSTs them to the backend — OL/QWC2 drawing
tools exist, but the wiring is ours), and web GetFeatureInfo readouts styled to mission standards.
These are exactly the "build twice" costs §0 bounds, and they are priced into Phase 2.

---

## 3. Key architectural decisions

### 3.1 Delivery architecture — **SETTLED (Aaron 2026-07-05): dual-client, shared core, web-first hosting**

Not a fork anymore; recorded as the decision of record, with the shared/per-client split made
explicit (this table governs every phase):

| Tier | Contents | Built once? |
|---|---|---|
| **Shared core — GIS** | `stewie_south_pole.qgz`: CRS (IAU_2015:30135), all raster/vector layers, styling, layer-tree structure, provenance metadata, print layouts | YES — one file, consumed by Desktop (opens directly) and Server (publishes it) |
| **Shared core — brain** | STEWIE FastAPI backend: layer manifest + eligibility, DEM/georef, plan/lifecycle (`/executive`), physics attribution, evidence, auth/roles, audit. ALL authority decisions | YES — both clients are thin over the same API |
| **Per-client — map surface** | Desktop: QGIS canvas (free). Web: OL/QWC2 viewport consuming QGIS Server WMS/WMTS (thin) | Mostly free / thin |
| **Per-client — mission UI** | Desktop: PyQGIS plugin docks. Web: cockpit-salvaged panels + map-bound editing | **The real dual cost** — bounded by thin-UI rule |
| **Per-client — engine panes** | Desktop: Qt docks (QWebEngineView Foxglove, sidecar stream). Web: cockpit panes (Foxglove web, sidecar stream) — same D3 transport both sides | Dual, but transport + evidence semantics shared |

**Build order within the decision (my recommendation):** shared core first (P1 — it IS both clients'
substrate), then **web mission UI first** (P2.A — it inherits the deployed, tested cockpit and serves
the hosted/gated goal Aaron prioritized), desktop plugin in parallel or immediately after (P2.B — the
power-analyst surface; also the surface where plan *authoring* is strongest). Phase 3 gates the web
deployment (Cloudflare Access + backend auth) and distributes the desktop client.

**Guardrails that keep dual-client honest (bind all P2 work):**
1. The backend is the only brain: no lifecycle/eligibility/authority logic in either client; a UI
   that can't render a state renders the backend's refusal reason (AU-01 pattern).
2. One `.qgz`: no client-specific layer forks. A layer that exists only in one client is a bug.
3. Feature parity is NOT a goal: desktop = authoring/analysis-strong; web = monitoring/review/
   lifecycle-strong. The parity target is the *data shown*, not the tools.
4. The execution service remains the sole command egress (EG-06) from both clients.

### 3.2 Web map client: QWC2 vs custom OpenLayers viewer — **RECOMMEND: OpenLayers viewport inside the existing cockpit; QWC2 as a scoped spike for the analyst web surface**

**Recommendation.** Build the web map surface as an **OpenLayers viewport embedded in the existing
vanilla-JS cockpit**, consuming QGIS Server WMS/WMTS in `IAU_2015:30135` (OL takes arbitrary
projections via proj4js — register the 30135/30100 defs and the polar extent). Salvage everything
around it: the cockpit's ConOps lifecycle spine, run stream, evidence panes, auth, deploy pipeline.
Run a **time-boxed QWC2 spike** (≤3 days) in parallel-or-later for the *full-GIS analyst* web surface
(QWC2 reads the same `.qgz` theme and gives layer tree / identify / measure / print for free), with a
go/no-go on: lunar-CRS handling end-to-end, auth integration with our operator tokens, and how much
of the mission UI could live in QWC2 plugin slots.

**Why OL-in-cockpit first:**
- The cockpit is **vanilla JS by a standing decision of record** (the React rewrite black-screened
  and was reverted `55c44c6`; strangler-fig chosen 2026-06-20 and re-affirmed 2026-07-01). OpenLayers
  is framework-free and embeds in vanilla JS cleanly; QWC2 is a React/Redux application — adopting it
  as the shell re-litigates the settled decision, embedding it piecemeal fights its architecture.
- The mission UI already exists in the cockpit (Plan/Rehearse/Validate/Release/Execute/Report,
  role-gated cluster, run stream, evidence). The missing piece is precisely and only the
  pole-truthful map viewport — the minimal change is to add one, not to move the mission UI into a
  new framework.
- Smallest new-dependency surface: OL + proj4js vs a full QWC2 stack (build chain, theming, config
  generator, its own auth expectations).

**Alternatives weighed:**
- *QWC2 as the web client shell:* strongest free GIS functionality (it is literally the QGIS web
  client — theme from the same project, identify/legend/measure/print out of the box) and the most
  "same-.qgz" purity. Costs: React shell vs our vanilla-JS cockpit, bespoke work to host mission
  panels + engine panes inside it, its own auth layer to reconcile. Not rejected — **deferred to the
  spike**, and if the spike goes well QWC2 can become the *analyst* surface at `/gis` while the
  cockpit stays the *operator* surface (two web surfaces, one Server, acceptable under guardrail 3).
- *Custom React viewer:* re-opens the reverted-rewrite path for no capability OL doesn't give. Rejected.
- *MapLibre/deck.gl retained for the web map:* the disproven substrate. Rejected (that's the pivot).

### 3.3 Backend ↔ QGIS integration — **RECOMMEND: HTTP lanes, no custom QgsDataProvider; QGIS Server co-deployed as a compose service**

Consumption lanes, shared-core first:

1. **OGC lane (zero client code):** QGIS Server publishes the `.qgz` (WMS/WMTS/GetFeatureInfo/OGC
   API) → the web viewport consumes it; Desktop reads the same layers from disk directly (and can
   also consume the Server when remote). The backend's existing `/ogc` WMS additionally feeds live
   computed layers (illumination/incidence/psr) to BOTH clients today, before any new code. Extend
   `ogc.py` to advertise `IAU_2015:30135` as an offered CRS (small change) so its GetMap can return
   pole-projected renders too.
2. **JSON/typed lane (mission UIs):** both clients call the FastAPI JSON API with the operator
   token — `/layers` manifest + eligibility; `/dem/georef|site_xy|site_lonlat` round-trip; `/plan`,
   `/executive/*`, `/evidence`, `/profiles`, `/rc/eligibility` for mission panels. Desktop via
   `QgsNetworkAccessManager`; web via the cockpit's existing fetch layer.
3. **File/COG lane:** big rasters stay files. Desktop loads COGs from local disk or `/vsicurl/`
   range-reads against the nginx-served COG volume; QGIS Server reads them from its mounted volume.
   No re-encoding, ever.
4. **Live lane:** `/executive/run/{id}/stream` (SSE) → web: existing cockpit stream handling +
   an OL vector layer updated in place; desktop: QgsTask/thread → memory-layer updates.

**Alternatives weighed:** custom Python `QgsDataProvider` (first-class refresh semantics; heavy
machinery for a small manifest — revisit only if live layers outgrow memory-layer updates); embedding
PyQGIS in the FastAPI process (useful later for server-side layout/report rendering; not the spine —
keeps the backend importable without QGIS). Both deferred, not chosen.

**Deployment shape (web-first):** `qgis-server` official Docker image as a new service in
`code/deploy/compose.yml`, `.qgz` + data volumes mounted read-only, routed at
`app.stewie.space/gis/` through the existing cloudflared → nginx path. Cache rules mirror the
`/assets` lesson (memory `infra_stewie_deploy_cloudflare`): edge-cache public basemap tiles only,
never authenticated operational renders.

### 3.4 Fate of the vanilla-JS cockpit + the GeoLibre/Artemis work — **RECOMMEND: cockpit is PROMOTED (web mission client); GeoLibre fork retired-frozen with a concrete salvage list**

**Cockpit (app.stewie.space):** under the dual-client decision the cockpit is no longer "narrowed" —
it is **promoted to the web mission client**: it keeps the lifecycle spine, run stream, evidence,
auth, program board, admin, and GAINS the OL/QGIS-Server map viewport (§3.2), replacing its
Cesium-globe-era GIS ambitions with a pole-truthful one. This preserves the strangler-fig decision
of record and every `[REQ:]`-tested cockpit row.

**GeoLibre/Artemis fork:** retire as a product; freeze the branch (commit the dirty tree first —
ARTEMIS_LAYERS.md and two of the three .tsx files are currently uncommitted). Do NOT delete. Salvage:

| Artifact | Verdict | Where it goes |
|---|---|---|
| `public/data/cog/` (946 MB: 8 site dem+slope COGs, Haworth 1 m) | **SALVAGE — the crown jewels.** Renderer-agnostic, native to both QGIS clients as-is | Move to `/mnt/projects/stewie/data/gis/cog/` (stewie-owned; geolibre must not remain the host of mission data). Gitignored/volume per MT-01 large-file discipline |
| `data/lunar/` raw polar-stereo GeoTIFFs + Haworth 1 m SfS (1.3 GB) | **SALVAGE** (source-of-truth rasters, re-derivation inputs) | `/mnt/projects/stewie/data/gis/raw/` |
| `scripts/cogify.sh` (GeoTIFF → COG + overviews) | **SALVAGE** | `code/scripts/gis/cogify.sh` |
| `ARTEMIS_LAYERS.md` (catalog research: Trek/LROC/QuickMap/PGDA/PSR endpoints) | **SALVAGE** (input to the P1 catalog; endpoints become QGIS connections / Server layers) | copy into `code/docs/`; mark original superseded |
| Site pins GeoJSON / DEM-center derivation (gdalinfo) | **SALVAGE** (regenerate as proper GeoJSON in 30100) | `data/gis/vectors/artemis_sites.geojson` |
| Cockpit lifecycle/run/evidence/auth panes | **SALVAGE (in place)** — they ARE the web mission UI (§3.2) | stay in `code/` |
| `encode_terrain_points.py` `.bin` point clouds; terrarium encodings; `encode_site_layers.sh` PNG previews | **DROP.** Pure workarounds for the mercator wall | — |
| deck.gl OrbitView / OrthographicView components (PolarTerrain.tsx, SiteLayers2D.tsx, ArtemisTerrainOverlay.tsx) | **DROP from the line; keep frozen on the branch.** 3D inspection → QGIS 3D local scene (P1.7) + the Godot pane | frozen on `artemis-lunar-terrain` |
| GeoLibre fork itself | **FREEZE** (commit dirty work, tag `artemis-final-2026-07-05`, redirect note in its CLAUDE.md) | `/mnt/projects/geolibre` stays, read-only posture |

**Rollback:** all moves are copies + a tag; nothing destroyed. The ~2.3 GB data move: `rsync` +
verify + then delete source; update the nginx COG volume mount if anything still references it.

### 3.5 PRD §7.B implication — noted, NOT applied (do not edit PRD.md in this pass)

§7.B's 2026-07-05 header block says "GeoLibre IS this front end" and encodes the MapLibre-era
compromises. When the mechanical PRD pass runs:

| Row | Today | Under the pivot |
|---|---|---|
| §7.B header + loop order | GeoLibre is the workbench; OrbitView substrate | Dual-client QGIS: one `.qgz` + FastAPI brain; Desktop plugin + QGIS-Server-fed web cockpit |
| GW-05 (map substrate) | mercator/globe overview + per-site OrbitView; "MapLibre cannot render a polar-stereo frame" | REWRITE: canvas/Server render in `IAU_2015:30135`, LOLA COGs + imagery native at 85–90°S in BOTH clients; the OrbitView clause and the imagery-gap banner (mercator sense) dissolve. Round-trip + no-Earth-claim clauses keep |
| SP-01 (polar-stereo map-mode spike, P2) | deferred go/no-go | **CLOSED BY ARCHITECTURE** — the spike's goal is the platform default in both clients |
| WS-01 (dockable workspace) | build a dock manager over GeoLibre panels | RE-SCOPE: desktop = Qt/QGIS docks native; web = the cockpit's existing pane layout (already shipped) |
| WS-02 (Tauri v2 desktop) | Tauri multi-window | **SUPERSEDED — reverses D1 on evidence:** QGIS *is* the desktop app; multi-monitor = floating docks. (D1 chose Tauri when the front end was one web app; the premise changed.) Tauri work stops |
| BW-01/02/03 ("GeoLibre consumes /layers, /dem, /executive+/evidence") | GeoLibre store wiring | REWORD + SPLIT per client: "the web map client / the QGIS plugin consumes …" — semantics identical, feeds unchanged |
| GW-02 (workspace context) | one routeable URL restores all (D, cockpit) | KEEPS its D — the cockpit remains the web client; add the desktop analog (project + plugin-persisted context) as a sub-clause |
| GW-06/03 (layer tree + eligibility) | GeoLibre layer tree | Desktop: QGIS layer tree + Eligibility panel. Web: OL layer control bound to `/layers` manifest. Provenance in QgsLayerMetadata / manifest |
| GW-07 (inspector), GW-08/ED-01 (edit session) | GeoLibre panels | Desktop: plugin dock + QGIS edit session. Web: OL draw/modify tools. BOTH commit ONLY through backend routes (rule unchanged) |
| MA-01 | build coordinate/measure surfaces | Desktop largely native; web = GetFeatureInfo readout + OL measure in 30135; residual = round-trip test vs `/dem/site_xy`↔`site_lonlat` + stated scale tolerance |
| RT-03/04/05/06 (engine panes + transport) | dockable panes in GeoLibre; D3 web-native data + sidecar render | KEEP D3 verbatim; panes exist per client (Qt docks / cockpit panes), same transports, same evidence-only rule |
| GW-00 (Trek CSP) | CSP allowlist for the web panel | KEEPS relevance for the web client (Trek/QGIS-Server/rosbridge origins in CSP); desktop needs none |
| LY-01/02, PH-01/02, TM-02/03/04, RT-01/02, AU-01, EV-01, SD-01, GW-04 | backend / front-end-agnostic | UNCHANGED (these rows are why the pivot is cheap); realizations land per client |
| NEW rows for the pass | — | QS-01 QGIS Server service + `.qgz` publication; QS-02 web map viewport (OL, 30135) in the cockpit; QS-03 QWC2 spike go/no-go; QP-01 desktop plugin skeleton + auth; QP-02 plugin mission panels; AD-01 plugin settings; AU-02 plugin auth integration |

Also: `STEWIE_PRD_reconciliation_2026-07-05.md` gets a superseded-by banner pointing here (its
Locked Decision 1 "GeoLibre becomes THE workbench" is reversed by Aaron's directive; its decision 2's
*evidence* — the mercator-wall proof — plus decisions 4/5/6 and D3 carry over; D1/D2 superseded as
tabled above).

---

## 4. Phase 1 — shared core: QGIS + lunar GIS, both delivery paths (pole-truthful foundation)

Goal: ONE QGIS project where the Artemis III sites at 85–90°S are ordinary, fully-functional GIS —
every ARTEMIS_LAYERS row loadable, float-queryable, measurable, styled, provenance-tagged — opened
directly by Desktop AND published by QGIS Server. Per the dual-client economics, this phase IS both
clients' GIS substrate; the web/desktop split costs nothing here beyond standing the Server up.

**Shared-core vs per-client in P1:** everything in P1.1–P1.6 is shared core. P1.7 (Desktop 3D) and
P1.8 (Server bring-up + first web render) are the two thin per-client tails.

### P1.0 Install + environment (step 0; sudo — flag before running)
- Desktop: QGIS LTR (≥3.40) from the qgis.org apt repo on archimedes (Debian 12) + `python3-qgis`.
  Server: the official `qgis/qgis-server` Docker image (no host install needed; Docker verified
  active). *Rollback: apt remove / remove the compose service.*
- Verify inside BOTH QGIS builds: `IAU_2015:30135` resolves (host PROJ has it; QGIS bundles its own
  PROJ — confirm; fallback = a saved custom CRS from the identical proj4 string; the COGs' embedded
  WKT loads regardless).
- Headless lane for tests/CI: `qgis_process` + PyQGIS in the `qgis/qgis` container so P1 acceptance
  gates run in CI — consistent with the standing rule that nothing here is "container-gated": I
  verify in containers myself.

### P1.1 CRS + project skeleton
- Canonical project `code/gis/stewie_south_pole.qgz` (small; belongs in git). Project CRS
  `IAU_2015:30135`; measurement ellipsoid = the Moon sphere (R=1737400) so measure tools never
  assume WGS84; coordinate display = 30135 meters primary, 30100 lon/lat secondary.
- Data paths project-relative to `/mnt/projects/stewie/data/gis/` (post-salvage move, §3.4). A
  `code/gis/README.md` documents data-fetch (files, sources, checksums) since the 946 MB + 1.3 GB
  stores stay out of git.
- No-Earth-claim discipline (MA-01): project metadata states the selenographic frame; no layer is
  tagged EPSG:4326/WGS84.

### P1.2 Load the real terrain (the on-disk salvage)
- 8 × site `dem.tif` + `slope.tif` COGs + `Haworth_1m_dem.tif` as raster layers, grouped per site.
  Zero conversion — verified COG/Float32/overviews (§1).
- Styling: DEM hypsometric ramp from real per-site stats; slope classed at mobility-relevant breaks
  (5/10/15/20°, per the IPEx envelope — 15° nominal / 20° slope-test from `ipex_specs`); per-site
  hillshade via `gdal:hillshade` in polar stereo (correct at the pole, unlike any mercator hillshade).
- Derived layers via Processing where the PRD2 catalog wants them (contours; `hazard.slope_nogo`
  mask). Provenance (source file, command, date) in QgsLayerMetadata.

### P1.3 Imagery + external services (Path A of ARTEMIS_LAYERS, unified)
The Artemis three-renderer split (Path A/B/C) collapses: every source below is just a layer in the
30135 project, reprojected on the fly, in both clients.
- **LROC NAC South Pole mosaic** (native polar stereo, −90..−85.5°) — priority imagery drape; needs
  no warp at all.
- **Moon Trek WMTS + LROC Lunaserv WMS + QuickMap WMTS** as QGIS connections (endpoints already
  researched in ARTEMIS_LAYERS.md). They serve equirectangular; QGIS warps. *Honest expectation to
  verify:* at 89°S an equirectangular tile is extremely anisotropic — assess per layer; the NAC
  mosaic + our COGs carry the mission zone, global services fill 80–85°S context. This replaces the
  old "imagery-gap banner" with actual imagery where it exists.
- **STEWIE `/ogc` WMS** as a connection — live backend layers (illumination/incidence/psr) in QGIS
  on day 1, zero new code.

### P1.4 Vector layers (Path C)
- `artemis_sites.geojson` — the 8 LOLA-5m site pins + footprint polygons from DEM extents, in 30100,
  site ids matching the backend's naming (so the P2 site switcher round-trips).
- Artemis III 13 candidate regions (USGS ScienceBase 671a6fa8), PSR outlines (LROC PSR Atlas
  ≥10 km²), illumination-percent products (PDS r32) → one `lunar_south_pole.gpkg`, styled,
  provenance in metadata. These were CAT (catalogued, unwired) in Artemis; P1 wires them for real.

### P1.5 The layer catalog as a shared artifact
- Mirror ARTEMIS_LAYERS + the PRD2 `base.*`/`terrain.*`/`hazard.*` naming into layer-tree groups so
  BOTH the P2 plugin and the web manifest bind `/layers` entries to the same ids.
- Toggle/opacity/legend/provenance: desktop native; web = whatever the Server publishes (legend via
  GetLegendGraphic) + the OL layer control in P2.A. Nothing bespoke in P1.

### P1.6 Mission-accuracy readouts (MA-01, the payoff)
- **Value readout:** Identify (desktop) and WMS GetFeatureInfo (server — verify float precision
  passes through) on the COGs = real Float32 elevation/slope. Acceptance: values match
  `gdallocationinfo` on the same pixel, 3 spot checks per site, BOTH paths.
- **Coordinates:** 30135 x/y meters + 30100 lon/lat simultaneously. The per-site *local* `site_xy`
  frame (what `/dem/site_xy` speaks) is an affine from 30135 (subtract the site origin, from
  `gdalinfo`/`/dem/georef`); document per-site offsets in P1, ship in the P2 readouts.
- **Measurement:** distance/area in the metric polar frame; stated tolerance: polar-stereo scale
  k = 2/(1+sin|φ|) ⇒ ≤0.20% at 85°S, ≤0.05% at 87.5°S, →0 at the pole.
- **Round-trip:** a PyQGIS test transforms each site's pin 30100↔30135 vs `gdaltransform` (P1) and
  vs `/dem/site_xy`↔`/dem/site_lonlat` (P2), within tolerance.

### P1.7 Desktop 3D (replaces OrbitView) — per-client tail
- QGIS 3D **local scene** per site: DEM elevation + imagery/slope drape in the projected CRS (local
  scenes on a projected CRS are the supported non-Earth path). Verify on the 3200² sites and
  (windowed) Haworth 1 m. The *mission* 3D view remains Godot's job (RT-05).

### P1.8 QGIS Server bring-up + first pole-truthful web render — per-client tail
- `qgis-server` compose service, `.qgz` + `/mnt/projects/stewie/data/gis` mounted read-only;
  GetCapabilities lists the catalog; GetMap in `IAU_2015:30135` returns Site01 at full styling.
  Local-only in P1 (no public route yet — gating is P3; a temporary Tailscale-gated check is fine).
- This is deliberately in P1, not P3: it proves the shared-core promise (same `.qgz`, two clients)
  before any mission UI is built on it.

### P1 acceptance gate
1. Desktop canvas centered on Site01 (89°27′S) renders DEM+hillshade+slope+NAC imagery — no wall.
2. QGIS Server GetMap of the same view (30135) matches the desktop render.
3. Identify + GetFeatureInfo return Float32 values matching gdallocationinfo (3 checks/site).
4. Measure across a known site extent matches the gdal-computed extent within stated tolerance.
5. All ARTEMIS_LAYERS rows represented: loaded, or explicitly deferred with reason.
6. Trek/LROC/QuickMap + STEWIE `/ogc` WMS connections render in the polar canvas.
7. Headless PyQGIS script (container) reproduces 1–4 → the CI test seed.
8. The `.qgz` + data-fetch README round-trip on a clean machine (John can open it).

---

## 5. Phase 2 — mission planning on top + all application integrations (dual-client, web-first)

Goal: the mission workbench over the shared core. Build order preserved from the reconciliation
(GIS core → runs/evidence → engine panes), applied web-first (P2.A) with the desktop plugin (P2.B)
in parallel where staffing allows. **Shared-core work is listed once (P2.0) and consumed by both.**

### P2.0 Shared-core work (backend; serves both clients, built once)
- **`/layers` manifest hardening (BW-01 feed):** the manifest carries layer id (matching the
  `.qgz`/catalog ids), eligibility (display/planning/release/execute), freshness, uncertainty,
  provenance, and the serving hint (qgis-server WMS/WMTS | backend `/ogc` | COG path | GeoJSON URL).
  One manifest drives the desktop layer panel AND the web layer control.
- **`ogc.py` extension:** advertise `IAU_2015:30135` so backend-computed layers GetMap in the polar
  frame for both clients.
- **Mission-feature routes:** confirm/complete the plan-authoring routes (waypoints/keep-outs/work
  zones/orders with `order_kind`) so both clients' editors write through them (GW-08 rule: the map
  layer is never authority; the backend's accepted state is re-fetched after commit).
- **`/dem/georef` cross-validation** of each site COG against the sim authority (catches GIS-store
  vs authority drift — a check neither side had).
- **SSE/stream shape** for live runs consumed identically by both clients.
- **Physics attribution passthrough (MA-02/PH-02):** every route/volume/risk value in API responses
  carries backend + calibration + source-class + uncertainty; both UIs render unqualified values as
  visibly non-release-eligible.

### P2.A Web client (first): cockpit + pole-truthful viewport
- **A1 — OL viewport (QS-02):** OpenLayers + proj4js (30135/30100 registered) in a cockpit pane,
  consuming QGIS Server WMTS/WMS; layer control bound to `/layers`; site switcher pans the viewport;
  GetFeatureInfo readout (elevation/slope + dual coords + local `site_xy`). CSP additions per GW-00.
  Stamp discipline: run `stamp_cockpit_version.py` after every cockpit asset change (standing rule).
- **A2 — QWC2 spike (QS-03, time-boxed ≤3 days):** stand QWC2 up against the same Server; go/no-go
  on lunar CRS end-to-end, operator-token auth, and mission-panel hosting. Outcome recorded here; a
  "go" adds an analyst `/gis` surface, it does NOT replace A1.
- **A3 — Mission lifecycle on the map:** the existing ConOps spine (already shipped + tested) binds
  to the viewport — plan features render from backend GeoJSON (`/export/geojson` + mission routes);
  OL draw/modify tools author waypoints/keep-outs/orders → POST through the mission routes → re-fetch
  accepted state. MP-07 executability card + AU-01 authority card stay as-is (already built), now
  spatially adjacent to the map.
- **A4 — Runs/evidence on the map:** the cockpit's existing `/executive/run/{id}/stream` handling
  feeds an OL vector layer (live pose + trail); the evidence pane gains map-linked artifacts.
  Latency measured and stated (RT-06 SLA).
- **A5 — Engine panes (web):** Foxglove/rosbridge pane (RT-04) and Gazebo/Godot sidecar-stream panes
  (RT-03/05) in cockpit panes — D3 transport verbatim; evidence-only, no command authority.

### P2.B Desktop client: STEWIE Workbench PyQGIS plugin
- **B1 — Plugin skeleton (QP-01):** `code/apps/qgis_workbench/` (monorepo apps layer; the plugin may
  import client helpers but NEVER `stewie.physics`/authority code — API client only). Standard
  layout (`metadata.txt`, dock widgets), `make plugin-zip`, settings dialog (backend URL, login,
  data dir), token in QgsAuthManager (encrypted), pytest+pytest-qgis in the container CI lane, gated
  on pytest exit code (standing STEWIE rule).
- **B2 — Layer Catalog + Eligibility docks (BW-01/GW-03/GW-06):** `/layers` → layer-tree groups +
  eligibility badges + provenance into QgsLayerMetadata; a display-only layer visibly cannot be
  planning-valid (backend-enforced, plugin-displayed).
- **B3 — Mission Context dock (GW-02 desktop analog):** mission/site/profile/run/role selector
  persisted in project custom properties; a copyable context token the web cockpit can also parse
  (bridges to the cockpit's URL context, which keeps its D).
- **B4 — Lifecycle + authoring docks (GW-08/ED-01 strong form):** the 6-slot lifecycle driving the
  same endpoints as the web; plan authoring as QGIS edit sessions on scratch GPKG layers with
  snapping/measure/undo, commit = POST through backend routes only. This is where dual-client pays:
  the desktop editor is the *strong* authoring surface; the web editor (A3) is the light one.
- **B5 — Runs/evidence docks (BW-03/RT-02/EV-01):** SSE on a background thread → memory-layer live
  pose; Evidence dock browsing bundles per run/profile; **reports via QgsLayout** — mission map
  atlases rendered headless (`qgis_process`) and attached into the backend evidence bundle (upgrades
  the PDF report with real cartography; also serves the web client's report links — shared output
  from a desktop-lane tool).
- **B6 — Engine panes (Qt):** Foxglove in QWebEngineView; Gazebo/Godot sidecar streams in dock
  widgets; float to a second monitor (the old WS-02 need, now free).

### P2 acceptance gate
1. **Web:** at app.stewie.space (staging), an operator sees Site01 pole-truthful imagery+DEM, toggles
   catalog layers, reads a real Float32 elevation at a click, authors a keep-out, runs a desktop_sil
   mission, watches the live pose move, opens the evidence bundle.
2. **Desktop:** fresh QGIS + plugin zip + token → catalog assembles from `/layers`; author a full
   plan (waypoints + keep-out + cut order) → commit → backend accepts → plan renders back
   byte-equivalent within tolerance; run + live pose + evidence + a rendered report layout.
3. **Cross-client:** a plan authored on desktop is visible/actionable in the web lifecycle (and vice
   versa) with zero client-to-client communication — backend-arbitrated only.
4. **Engine panes:** Foxglove pane live on both clients for the same run; adversarial check proves
   no pane can issue a command (sole-egress preserved).
5. Coordinate round-trip vs `/dem/*` green in CI (both clients' readout code paths).

---

## 6. Phase 3 — private gates, admin, settings (web-first gating)

Goal: the hosted web workbench is private/gated; the desktop client authenticates against the same
identity; admin/config coherent. The backend substrate exists (§1: PBKDF2 operators, 12 h HMAC
tokens, roles, invites, operators_admin) — P3 is wiring, not invention.

### P3.1 Gate the hosted deployment (web)
- **Cloudflare Access** in front of the gated routes (`/gis/` QGIS Server, the operational cockpit
  surfaces) — identity-aware gating at the edge, before a byte reaches origin; the public landing +
  demo layers stay open. *Defense in depth:* backend token auth remains mandatory behind Access
  (Access is a moat, not the authority; EG-02 enforcement stays server-side).
- **QGIS Server auth:** nginx/backend token check in front of the Server FCGI for the operational
  project; a public read-only **demo project** variant (basemap + sites only, QS-02 posture mirrors
  the existing GIS-03 public-basemap stance) for the outreach story.
- **Layer-tier gating:** public tier = NASA-derived basemap/sites; authenticated tier = mission/
  design/runtime/evidence classes and any mission-derived rasters (as-built, terrain-memory
  snapshots). The `/layers` manifest carries the tier so both clients degrade honestly when
  unauthenticated.
- Cloudflare cache: basemap tiles cacheable; operational/authenticated renders `no-store` (mirror
  the `?v=` cache lesson).

### P3.2 Desktop auth + role gating
- Plugin login: email+password → `/auth` token (same operator accounts as the web; ONE identity
  system); QgsAuthManager storage; refresh before the 12 h expiry; explicit logout.
- Role-gated UI both clients (director/operator/guest ↔ EG-04 roles): guest read-only, operator
  plan/rehearse/validate, director release-adjacent. Enforcement ALWAYS backend-side; an adversarial
  test proves a guest token cannot release via raw API either.
- Mode/authority: EG-01/02 matrix stays backend-enforced; both clients display the active mode +
  authority card and can never bypass it.

### P3.3 Admin + settings
- Admin surfaces (operators, invites, mode control, audit) STAY in the web cockpit (built, tested;
  EG-10 taxonomy continues there). The desktop plugin links out.
- Plugin settings page: backend URL, login, data dir, cache size, latency display, layer-tier
  visibility. Web settings stay in the cockpit's existing settings surface.
- **Distribution:** versioned plugin zip on repo releases; pinned QGIS LTR documented;
  `scripts/gis/bootstrap_operator.sh` (install QGIS, fetch data per README, install plugin) — a new
  operator (John, an intern) runs in <30 min. The web client needs zero install (the point of
  web-first hosting).

### P3 acceptance gate
1. Unauthenticated: public landing + demo map only; every operational route 401/403s at BOTH layers
   (Access + backend), proven at the API not just the UI.
2. Guest/operator/director tokens exercise their exact floors from both clients; audit records carry
   the EG-07 fields for a release.
3. `app.stewie.space/gis/` serves a pole-truthful GetMap of Site01 through Cloudflare (cache status
   verified), operational project gated.
4. Clean-machine desktop bootstrap succeeds from the script alone.

---

## 7. What still speaks the old contract (pre-flight checklist for execution)

- **PRD.md §7.B** says GeoLibre is the workbench — stale on adoption; §3.5 is the pending edit set
  (NOT edited in this pass; the PRD pass must re-run req_trace / snapshot regen per FS-01).
- **`STEWIE_PRD_reconciliation_2026-07-05.md`** — needs the superseded banner (§3.5).
- **ARTEMIS_LAYERS.md** references BW rows + the OrbitView build queue — salvage-copy, mark original
  superseded.
- **The nginx/deploy COG volume plan** (mount geolibre's `public/data/cog`) — retarget to
  `/mnt/projects/stewie/data/gis/cog/` when the data moves; QGIS Server mounts the same volume.
- **The geolibre fork's dirty tree** — commit + tag BEFORE any data move (ARTEMIS_LAYERS.md and two
  .tsx files are currently uncommitted).
- **Cockpit CSP + asset stamping** — the OL viewport adds origins (QGIS Server path, Trek if
  client-fetched) to CSP per GW-00, and every cockpit.js-adjacent change re-runs
  `stamp_cockpit_version.py` (standing deploy rule).
- **Memory `project_stewie_prd2_gis_fold`** (GIS-first loop pick order) — true in spirit; the
  front-end substrate named in it changes.

## 8. Risks + open spikes (ranked)

1. **QWC2 fit** (medium, time-boxed): React shell vs vanilla-JS cockpit, auth reconciliation, lunar
   CRS end-to-end. Bounded by the A2 spike — OL-in-cockpit is the primary path either way.
2. **WMS GetFeatureInfo float fidelity + web readout quality** (medium): the web value readout must
   return real Float32, not a rendered-pixel approximation — verify at P1.6; fallback = a tiny
   backend readout endpoint over the COGs (rasterio), still shared-core.
3. **Equirectangular service imagery at 89°S** (medium): Trek/LROC global services may warp poorly at
   extreme latitude; NAC polar mosaic + local COGs carry the mission zone. Assessed per-layer P1.3.
4. **SSE/live-layer performance** (medium, both clients): OL vector refresh + QGIS memory-layer
   repaint at run cadence need real latency numbers (RT-06 SLA); fallback = decimated updates. P2.
5. **QGIS-build IAU registry** (low): a build might bundle a PROJ db lacking IAU_2015 → fallback is a
   saved custom CRS from the identical proj4 string; the COGs' embedded WKT loads regardless. P1.0.
6. **QGIS Server behind Cloudflare** (low-medium): GetMap in IAU codes is standard; the Access +
   cache rules are the real work. Spiked early in P3.1 (can pull into P2 staging).
7. **QGIS 3D local scene on the 1 m Haworth (259 MB)** (low): may need windowing; site COGs (29 MB)
   comfortable. P1.7.
8. **Operator install friction (desktop)** (low): bootstrap script + pinned LTR; web client is the
   zero-install path by design.

## 9. Sequencing summary

```
P1 SHARED CORE
  P1.0 install/verify → P1.1 CRS+project → P1.2 COGs (salvage move first, §3.4)
    → P1.3 imagery/WMS → P1.4 vectors → P1.5 catalog → P1.6 accuracy
    → P1.7 desktop 3D ∥ P1.8 QGIS Server bring-up → GATE (both render paths proven)
P2 MISSION LAYER (web-first; A ∥ B where staffed)
  P2.0 backend shared work →
  P2.A web: A1 OL viewport → A2 QWC2 spike → A3 lifecycle-on-map → A4 runs/evidence → A5 engine panes
  P2.B desktop: B1 plugin skeleton → B2 catalog docks → B3 context → B4 authoring → B5 runs/reports → B6 panes
  → GATE (cross-client plan round-trip)
P3 GATES
  P3.1 Cloudflare Access + Server/tier gating → P3.2 desktop auth/roles → P3.3 admin/settings/distribution
  → GATE
```

Parallelizable: P1.3/P1.4 after P1.2; P1.8 any time after P1.2; the PRD mechanical pass (§3.5) any
time after adoption; P3.1's Server-behind-Cloudflare spike can start during P2 staging.

**First three concrete actions on "go":**
1. Commit + tag the geolibre dirty tree (`artemis-final-2026-07-05`).
2. Install QGIS LTR on archimedes (sudo; rollback = apt remove) + pull `qgis/qgis-server` image +
   run the P1.0 verifications.
3. `rsync` the COG + raw stores to `/mnt/projects/stewie/data/gis/` (verify, then retire source).
