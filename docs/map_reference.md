# The map stack — reference (state as of 2026-06-10)

The operational state captured in live debugging (2026-06-10): the Cesium globe carries the
Haworth work area at its true selenographic footprint — red outline + label, the 5 m DEM drape
blending into the global basemap, and the work-area analysis rasters (slope/hazard/shadow/PSR)
draped over their own 640 m extent. This page is the future-reference record of HOW that works
and WHERE every piece comes from. All sources below are linked services or in-repo artifacts —
nothing needs a separate download to be referenced.

## The rendering pipeline (what draws, from where)

| Layer | Source | Mechanism |
|---|---|---|
| Global basemaps (8) | NASA Trek tile services (live, no download) | `UrlTemplateImageryProvider`, geographic tiling |
| Haworth 5 m DEM drape | in-repo `samples/lunar_dem/haworth_10km_5m/heightmap.rf32` (LOLA-derived) | clean 315°/45° hillshade from the RAW heightmap → server-side reprojection to a geographic grid → `SingleTileImageryProvider.fromUrl` in its own bbox |
| Work-area rasters | computed server-side from the same heightmap (slope, hazard, horizon-clipped shadow at the SPICE sun, PSR sweep) | reprojected over the 640 m work-area bbox; legends served by `/layers/legend` FROM the physics constants |
| Footprint outline + label | `/dem/georef` — `world_bounds_m` inverse-projected via IAU_2015:30135 | Cesium polygon entity (outline-only; clicking it loads the granular set) |

## Coordinate truth (verified 2026-06-10, task #42)

- The globe is **deliberately WGS84-shaped** (Cesium 1.119's custom-globe path errors); imagery,
  lat/lon angles, pan/zoom are correct because drape and picks share the same surface, and the
  drape bboxes carry TRUE selenographic values from the IAU CRS inverse projection.
- The **scale bar** multiplies the WGS84 Cartesian distance by `R_body / R_earth` — it reads true
  body meters (it was 3.67× off on the Moon before the fix).
- `/dem/site_xy` (cursor meters inside the footprint) runs server-side on the true CRS via
  pyproj — independent of the globe's shape.

## The slope hierarchy (verified 2026-06-10, task #43 — "why 20°, not 40°?")

| Threshold | Value | Source |
|---|---|---|
| Penalty | >15° | IPEx mobility ConOps "inclinations up to 15 deg" [SCHULER24] |
| No-go (hard) | >20° | the demonstrated wheel slope-driving test incline [WHEELTEST] |
| Empirical ceiling | ~30° | RASSOR Gen-1 FAILED a 30° loose mound (slip avalanche) |
| Closed-loop routing default | 25° | documented as between tested and the failure point |

40° has no support in the traced record and exceeds the documented failure point. Steeper
operation would be a different MODE (arm-anchored quasi-static locomotion) requiring its own
source and its own perception-gated action type.

## Live-referenceable services and data (in the stack, no separate download)

- **NASA Trek tile services** (the basemaps, fetched live):
  `https://trek.nasa.gov/tiles/Moon/EQ/{product}/1.0.0/default/default028mm/{z}/{y}/{x}.png`
  — products in use (each tile-verified before listing): `LRO_WAC_Mosaic_Global_303ppd_v02`,
  `Kaguya_TCortho_Mosaic_Global_4096ppd`, `LRO_LOLA_ClrShade_Global_256ppd_v06`,
  `LRO_LOLA_DEM_Global_128ppd_v04`, `LRO_LOLA_ClrSlope_Global_16ppd`,
  `LRO_LOLA_ClrRoughness_Global_16ppd`, `LRO_Diviner_ST_Avg_Clr_Global_32ppd`,
  `LRO_LOLA_Shade_Global_128ppd_v04`. Catalog: <https://trek.nasa.gov/moon/>
- **Earth polar-capable layer**: NASA GIBS Blue Marble,
  <https://gibs.earthdata.nasa.gov/> (EPSG:4326 WMTS).
- **SPICE / NAIF** (the solar authority): SpiceyPy + generic kernels from
  <https://naif.jpl.nasa.gov/pub/naif/generic_kernels/> (`de440s.bsp`,
  `moon_pa_de440_200625.bpc`, `moon_de440_250416.tf`, `naif0012.tls`, `pck00011.tpc`; local
  cache at `$STEWIE_SPICE_KERNELS`). WebGeocalc (the manual cross-check oracle):
  <https://wgc.jpl.nasa.gov:8443/webgeocalc/>. Tutorials: <https://naif.jpl.nasa.gov/naif/tutorials.html>
- **LOLA source data** (the Haworth DEM's lineage): LOLA PDS node
  <https://ode.rsl.wustl.edu/moon/> and the LRO LOLA archive at
  <https://pds-geosciences.wustl.edu/missions/lro/lola.htm>; polar products via
  <https://pgda.gsfc.nasa.gov/>.
- **Lunar CRS**: IAU_2015:30135 (south polar stereographic, R=1737400 m sphere) resolved through
  pyproj's IAU registry — <https://proj.org/>.
- **Cesium** (the globe): <https://cesium.com/learn/cesiumjs/ref-doc/> (pinned 1.119 via unpkg).

## Traced platform papers (the constants' provenance tags)

- **[SCHULER24]** Schuler et al., IPEx ConOps / TRL-5 documentation — mobility envelope, RDS
  spec, camera/LED systems (NTRS; title-cited, the in-repo conformance review carries the page
  traces).
- **[WHEELTEST]** the IPEx/RASSOR-2 wheel slope-driving test (Eq. 1 kinematic track 0.5207 m,
  20° incline; NTRS title-cited).
- **[R2D]** RASSOR 2.0 design paper (drum actuator ~25/18 RPM, 80 kg design hold).
- **[BDS]/[BDSCALE]** bucket-drum scaling (Schuler 2022; Table 1 drum dims, Table 3 capacities).
- **ICE-RASSOR drum-mass sensing**: NTRS 20210022781 — arm-power integral mass estimate
  (R² 0.996), the basis of the drum-fill telemetry.
- **Carstens & Schuler, IEMS 2025** — the IPEx control-room operator findings behind PRD §16.5's
  UI requirements.

NTRS search (all NASA papers above are public): <https://ntrs.nasa.gov/>.

## Stability-model fidelity (audited 2026-06-10, Aaron's question — task #59)

| Quantity | Value in the model | Provenance | Verdict |
|---|---|---|---|
| SSA gauge | **0.5207 m** (was 0.57) | skid-steer kinematic track [WHEELTEST Eq.1] | FIXED — the tip margins ran on the EZ-RASSOR render stance |
| SSA wheelbase | 0.40 m | [ASSUMPTION — no documented IPEx wheelbase; render-rig consistent] | tagged honest |
| CG height | 0.30 m | modeled (constants.py; SSA ~33.7° pitch binds) | tagged; no doc value |
| Arm length (pivot→drum axis) | 0.28 m | [ASSUMPTION: render-rig consistent] | tagged honest |
| Arm arc | ±110° | [ASSUMPTION — RASSOR-lineage sweep; the IPEx value is figure-only] | tagged honest |
| Arm+drum mass share | 0.15/arm | [ASSUMPTION] | tagged honest |
| Drum dims | ⌀437.1 mm (large) | [BDS Table 1] | the CG widget now DRAWS the real radius (fill density ∝ load) |
| Drum loads in CG | at the drum position | ArmState.cg_offset_m, test-pinned | correct |

Honest summary: the LOAD physics (masses at drum positions, mass-weighted CG, SSA per-axis exact
for the rectangular support) is sound and test-pinned; the GEOMETRY carries four tagged
assumptions (wheelbase, CG height, arm length, arc) pending IPEx-doc values — the known stance
gap from the two-vehicle spec. The gauge bias is fixed with the documented track.

## DEM product map (which file for which job — Aaron's question, 2026-06-10)

| Product | Resolution / coverage | Use in STEWIE/SolNav |
|---|---|---|
| **PGDA Product 78** (Barker 2021) | **5 m/pix**, per-site (SiteNN dirs: 04=Shackleton rim, 06=Nobile rim 1, 01=Connecting ridge, 07=Peak-near-Shackleton, 11=de Gerlache, 20=Leibnitz β, 23=Malapert, + Haworth, Shoemaker, DM2=Nobile rim 2) | **site-scale planning/excavation** — the Haworth bundle's own lineage; Site04+Site06 downloaded to `datasets/lola_5mpp/` |
| PGDA Products 81/90 (Barker 2023) | 5–30 m/pix, polewards of 80°S | regional context between sites |
| **LuNaMaps SfS strip** (Bertone 2023, doi:10.5281/zenodo.10258683) | 30 m/pix, the 60°–80°S **approach corridor** (18,000 km², 1.1 GB TAR) | **optical-navigation / approach-phase evaluation** (SolNav dissertation) — not site-scale |
| SLDEM2015 | 60 m/pix global | basemap-scale only |

## The 30 kg question (Aaron, 2026-06-10): per drum or total?

**TOTAL per excavation cycle — the vehicle's delivery quantum, not a per-drum hold.** The RDS
spec reads "collect/store/deposit up to 30 kg/cycle (15 kg minimum success threshold)"
[SCHULER24] — the collect→haul→deposit loop. The per-drum INSTANTANEOUS holds are a different,
measured number [BDS Table 3]: small 3.80 kg / medium 7.30 kg per drum (IPEx carries the
small–medium scale; the 24.98 kg "large" is RASSOR 2.0's drum). With two drums at medium scale
(~14.6 kg held at once), a 30 kg cycle therefore spans MULTIPLE drum fills per delivery —
consistent, not contradictory, but worth stating plainly: `drum_capacity_kg=30` in the registry
is the per-CYCLE delivery spec the planner's drum-loads math uses, and the BDS per-drum values
bound what is on the arms at any instant (which is what the CG/stability widget takes as its
per-drum load inputs, max 30 kg slider deliberately above the medium hold for RASSOR-2-class
what-ifs).
