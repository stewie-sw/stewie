# STEWIE Deck (14-layer walkthrough) vs Current Code — Diff (2026-07-07)

> **Historical point-in-time diff.** Its “no DB / Phase 0 in progress” language is
> superseded: durable edit sessions and a relational world-transaction projection
> now exist. The missing accepted-world path is DA-07--DA-10—construction events,
> bound evidence, live promotion/atomic publication, and replayable GIS
> projections. Use `../PRD.md`, `../STATUS.md`, and
> `../docs/construction_event_ledger_contract.md` for current status.

> Source deck: `Claude/ToClaude/stewie-walkthrough.pdf` — "STEWIE Open-Source Stack, a layer-by-layer
> walkthrough of the revised, verified architecture" (14 layers + 2 appendices). Current state read from the
> `stewie/code` monorepo this session. Confirmed = read in code; inferred = grep-based, flagged.
>
> **Governing principle (Aaron's framing, and the deck's):** *ML proposes · Physics constrains · STEWIE
> reconciles · ROS executes.* The learned models belong at bounded service points (perception, traversability
> surrogate, cost-fusion, task-policy, failure-prediction); coordinate transforms, world-state, audit, safety,
> and final command authority stay deterministic. The diff below is read through that lens.

## Headline

STEWIE has built the **deterministic, auditable core the philosophy says to build first** — world-state,
conserved terramechanics, mission planning, sim/twin, data sources — **plus** the learned **localization**
stack (SLAM/VO + depth) and the **RL construction envs**. The gaps are almost entirely the deck's **amber
learned-ML insertion points** (which the philosophy explicitly sequences *after* the deterministic core), plus
the **storage DB** (Phase 0, in progress right now) and one **serving-architecture divergence** (WMS vs
TiTiler/OGC-API-Features). Nothing structural is upside-down; the build order matches the boundary doctrine.

## Layer-by-layer diff

| # | Deck layer | Deck target | Current state | Verdict |
|---|---|---|---|---|
| 1 | Open Lunar Data Sources | LRO/LOLA/NAC/WAC, DEM/DTM, illumination/shadow, sensor, ROS bags | Real LOLA DEMs (8× 5 m sites + Haworth 1 m SfS), WAC, global LDEM; ROS2 telemetry; physics shadow (TW-08) | ✅ **built** |
| 2 | Data Ingestion | GDAL/Rasterio, PDAL, GeoPandas, PyProj, STAC index | GDAL/rasterio (`build_project.py`), PyProj (CRS), GeoPandas (geojson). **No STAC catalog, no PDAL** | 🟡 partial |
| 3 | **Spatial Storage** | PostgreSQL+PostGIS, TimescaleDB, STAC object store | **No DB today** (files + hash-chained journals + in-memory). **PostGIS being added now (Phase 0).** No TimescaleDB, no STAC object store | 🔴 **gap → in progress** |
| 4 | QGIS Geospatial Kernel | PyQGIS, QGIS Processing, TiTiler (raster), OGC API Features (vector) | PyQGIS + QGIS Server **WMS**; request-time DEM crop. **No TiTiler, no OGC API Features** (serves via WMS + custom keyless `/world` routes) | 🟡 **different serving** |
| 5 | GeoAI Intelligence | vision backbone → rock/crater/change detection; Bayesian hazard fusion; shadow physics | Learned **VO + mono-depth + loop-closure** (`dart/`, localization) ✅; **no semantic terrain detectors**; hazard = physics/map-channel (not Bayesian fusion); shadow physics ✅ | 🟡 partial (localization yes; semantic GeoAI + Bayesian hazard **no**) |
| 6 | STEWIE World-State Backend | mission state, layer registry, versioned terrain snapshots | DT-01 world-transaction chain, DT-04 observed twin, Terrain Memory (versioned as-built), 66-layer registry, mission state | ✅ **built (STEWIE's strength)** |
| 7 | Terramechanics + Traversability | analytical Bekker-Wong + **learned surrogate** → prediction | Analytical Bekker-Wong + slip ladder + energy (conserved) ✅. **No learned surrogate** | 🟡 partial (analytical yes; surrogate **no**) |
| 8 | Costmap Generation | **learned cost-fusion** on operator paths + attribution | Costmap layers (cost/hazard/traffic) + ROS costmap egress ✅. **Rule/physics-weighted, not learned** | 🟡 partial (costmap yes; learned fusion **no**) |
| 9 | Mission Planning API | 8 primitives: survey, path, reorient, flatten, dig, dump, berm, avoid | `cut/fill/sinter/goto` orders + structures + keep-outs + **traverse + return-to-lander + place-objects** (tool palette). Maps: dig=cut, dump=fill, path/traverse=goto, flatten/berm=structure, avoid=keep-out | ✅ **mostly** (survey/reorient are the thin spots) |
| 10 | Autonomy + ROS 2 | quantized shared backbone onboard perception | ROS2 bridge + `run_closed_loop` + RS-04 replay loop ✅; onboard VO/depth ✅. **No quantized shared backbone** (perception is render/VO, not one shared net) | 🟡 partial |
| 11 | Simulation + Digital Twin | Gazebo, RViz, Godot twin, planned-vs-executed log | gz sim ✅, Godot render ✅, Foxglove-style eng panel ✅, DT-04 twin ✅, SIM execute→remember divergence ✅ | ✅ **built** |
| 12 | Frontend Mission Planner | OGC API Features (vector) + TiTiler (raster) | QWC2 lunar IDE ✅ (front door). Serves via **WMS + custom `/world` routes**, not OGC-API/TiTiler | 🟡 **built, different serving** |
| 13 | Execution Feedback + Retraining | planned-vs-executed → **scheduled retraining** of fine-tuned nodes | Divergence logging (DT-01, SIM loop) ✅; RL gym envs (`stewie/envs/`) ✅. **No scheduled auto-retraining trigger** wired | 🟡 partial (feedback + envs yes; auto-retrain loop **no**) |
| 14 | Export Packages | the complete stack | `build_public_cut.py` release snapshot exists | ✅ mechanism exists |
| App | World-State Hybrid | Global height map (PostGIS+STAC) + onboard TSDF (nvblox/Jetson/D435i) + Nav2 costmap + semantic tags + Godot twin mesh | Global height map (files → Phase 0 PostGIS); **onboard TSDF/nvblox/Jetson = hardware, gated**; Nav2 costmap 🟡 (ROS egress, not full Nav2); semantic tags ✅ (keep-outs/markers); Godot twin mesh 🟡 (render, not event-mesh) | 🟡 partial |

## The gaps, grouped

**A. The bounded learned-ML insertion points (deck amber) — not yet built, and correctly *after* the core:**
L5 semantic GeoAI (rock/crater/change detection + Bayesian hazard), L7 traversability surrogate, L8 learned
cost-fusion, L13 scheduled retraining trigger. STEWIE already has the *infrastructure* they plug into (the RL
envs, the divergence log, the physics they'd surrogate/fuse) — they're insertion points, not rewrites. This is
exactly the "deterministic core first, bounded ML second" order the boundary doctrine prescribes.

**B. Storage (L3) — the one real structural gap, and it's being closed now.** No DB today; Phase 0 is adding
PostGIS + a `stewie` schema + a durable edit-session as I write this. The deck also wants **TimescaleDB** for
telemetry and a **STAC-indexed object store** — neither exists yet; both are natural Phase 1/2 additions on the
same Postgres and align with the persistence design (`design/STEWIE_persistence_db_design_2026-07-07.md`).

**C. Serving architecture (L4/L12) — a divergence to reconcile.** The deck specifies **TiTiler** (raster) +
**OGC API Features** (vector); STEWIE serves via **QGIS Server WMS + custom keyless `/world` routes**. Both
work; the deck's choice is the more standards-forward one and pairs with the STAC object store. Worth a
deliberate decision: adopt TiTiler/OGC-API to match the deck, or keep WMS + custom routes and update the deck.

## Where the current build is *ahead of / different from* the deck

- **Localization ML is real** (`dart/` SuperPoint VO, mono-depth, loop-closure) — the deck's L5/L10 onboard
  perception is partly already here for the *navigation* problem, just not for *terrain-semantic* detection.
- **The mission planning is richer** than the deck's 8 primitives on the authoring side (a full tool palette +
  plan-anywhere + the audited edit-session), though missing explicit `survey`/`reorient` primitives.
- **The conserved world-state + provenance chain (DT-01) is more rigorous** than "versioned terrain snapshots"
  implies — it's the auditable source-of-truth the deck's framing wants STEWIE to be.

## Bottom line

The deck is a sound target and the current build is **on it, in the right order**: the deterministic auditable
spine (L1/L6/L7-analytical/L9/L11) is built, localization ML and RL envs are built, and the remaining work is
the **bounded ML insertion points** (L5/L7-surrogate/L8/L13), the **DB** (L3, in progress), and a **serving
decision** (L4/L12 WMS-vs-TiTiler/OGC-API). No layer is structurally wrong; nothing violates "ML proposes,
STEWIE reconciles." The honest one-liner: *the skeleton and the physics are done; the learned muscle and the
database are the next two builds — in that order.*

---
*Not committed pending review. Companion to STEWIE_persistence_db_design_2026-07-07.md and STEWIE_workflow_design_2026-07-07.md.*
