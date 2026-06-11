# STEWIE Data Book — vehicles, bodies, datasets, formulas

Reference sheet, tables-first. Every value below is read from the code/data at
`/mnt/projects/stewie/code` (repo-relative paths hereafter) or the named design doc — nothing
restated from memory. Provenance tags are preserved verbatim from their source files:
**[SCHULER24]** IPEx TRL-5 Design Overview (NTRS 20240008162) · **[WHEELTEST]** Zhang/Schuler,
IPEx Wheel Testing, ASCE E&S 2024 · **[BDS]/[BDSCALE]** Schuler/Nick, Bucket Drum Scaling, ASCE
E&S 2022 · **[R2D]** RASSOR 2.0 design paper · **[BATTERY]** project lead 2026-06-02 ·
**[CALIB]** honest estimate from real inputs under a stated assumption · **[ASSUMPTION]**
engineering bound stated for audit · **[UNKNOWN]** genuine wide-envelope unknown ·
MEASURED/ESTIMATED/UNKNOWN per `docs/bodies_sysrev.md`.

Section 5 lists every place the code and the existing docs disagree (flagged, not resolved).

---

## 1. Vehicles

Registry: `stewie/specs/vehicles.py` (`VEHICLES`, `POWER_SOURCES`, `TOOLS`; `DEFAULT_VEHICLE =
"ipex"`). Flight constants: `stewie/specs/ipex_specs.py`. Full harvest:
`/mnt/projects/stewie/design/TWO_VEHICLE_COMPLETE_SPEC_2026-06-10.md`. Only IPEx is
`ui_visible=True`; `rassor2` and `ez_rassor` are data-provenance entries.

### 1.1 IPEx — ISRU Pilot Excavator (the flight vehicle)

#### Mass & mobility

| Item | Value | Source |
|---|---|---|
| Dry mass | 30 kg class (`ROVER_MASS_CLASS_KG = 30.0`) | [SCHULER24] |
| Wheels | 4 × ⌀0.305 m (r = 0.1524 m), skid-steer, no suspension | [WHEELTEST]/[SCHULER24] |
| Skid-steer kinematic track | 0.5207 m (`SKID_STEER_TRACK_M`, Eq. 1, RASSOR-2 test platform) | [WHEELTEST] |
| Registry gauge | 0.3645 m = round(0.7 × 0.5207) — see flag F2 | vehicles.py [CALIB] |
| Registry wheelbase / CG height | 0.30 m / 0.21 m | vehicles.py [CALIB] (no published IPEx number) |
| Nominal drive speed | 0.30 m/s | [SCHULER24] |
| Drive motor (per wheel) | 0.063 N·m motor-side @ 1530 RPM, 80:1 gearbox (Table 3 case 3b; 4-case mean 0.0635) | [SCHULER24] |
| Drive power (Table-3 design case) | 40.38 W = 4 × 0.063 × ω(1530 RPM); motor-side, Earth-g testbed — NOT lunar steady drive | derived [CALIB] |
| Drive energy | 134.6 J/m = drive_power_w / 0.30 m/s | derived |
| Obstacle | 0.075 m rock height | [SCHULER24] |
| Slope | 15° nominal ConOps / 20° tested incline / ~30° RASSOR Gen-1 loose-mound failure / 25° closed-loop routing default | [SCHULER24]/[WHEELTEST]/`docs/map_reference.md` |
| ConOps | 70 km traverse · 11 days · 42 kg/hr dig rate · 5,000–10,000 kg total regolith | [SCHULER24] |
| RASSOR-2 → IPEx scaling | 0.7 (one-dimensional) | [SCHULER24] |

#### Battery & power

| Item | Value | Source |
|---|---|---|
| Pack | 12S Li-ion, ~30 Ah, 3.7 V/cell nominal → 44.4 V | [BATTERY] (project lead 2026-06-02; design doc flags UNVERIFIABLE) |
| Energy | 4.795 MJ = 1332 Wh (`battery_energy_j()`) | derived |
| Bus voltages tested | 47.6 / 53.2 / 58.8 V (14S dynamometer rig, not the flight pack) | [SCHULER24] |
| Thermal qual | actuators −35/+40 °C (TC2); off-the-shelf cells do not meet it — derating is [CALIB] future work | [SCHULER24] |
| Camera operational floor | 0–50 °C TVAC (`CAMERA_MIN_OPERATIONAL_C = 0.0`) | [SCHULER24 p.28-29] |
| Recharge power | 700 W (`RECHARGE_POWER_W`) | [CALIB] (no IPEx solar/charge spec) |
| Battery reserve | ≥10 % before forced recharge (`BATTERY_RESERVE_FRAC = 0.10`) | operational |
| Idle/survival draw | `IDLE_POWER_W = 0.0` default = "not modelled" | [ASSUMPTION], data-gated |
| Housekeeping | avionics 15 W · comms TX 15 W · flat thermal fallback 30 W | [ASSUMPTION] (not in published tables) |
| Drivetrain efficiency | 0.5 (`DRIVETRAIN_EFFICIENCY`) | [CALIB] (not in [SCHULER24]) |
| Rolling-resistance coeff | 0.15 (`ROLLING_RESISTANCE_COEFF`) | [ASSUMPTION] (rigid wheel on loose regolith ~0.1–0.4) |

#### Excavation chain

| Item | Value | Source |
|---|---|---|
| Drums | 2 × counter-rotating (horizontal dig reaction cancels; `arm_state.net_dig_reaction_n`) | KSC-TOPS-7 / US 9,027,265 |
| Drum speed | 25 RPM (`DRUM_SPEED_RPM`) — **[ASSUMPTION]**: 25 is the RASSOR-2.0 drum-actuator MAX [R2D]; rated is 18 (`DRUM_SPEED_RATED_RPM`); SCHULER24's only "25" is a wheel-actuator docking speed | [R2D]/[ASSUMPTION] |
| Capacity per CYCLE | **30 kg/cycle** (`REGOLITH_PER_CYCLE_KG`), 15 kg minimum success threshold — the collect→haul→deposit delivery quantum, NOT a per-drum hold | [SCHULER24] RDS spec |
| Per-drum INSTANTANEOUS holds | small 3.80 / medium 7.30 / large 24.98 kg (`DRUM_CAPACITY_KG`; IPEx uses the small–medium scale, "large" is RASSOR 2.0's drum). A 30 kg cycle spans multiple drum fills; `drum_capacity_kg=30` in the registry is the per-cycle delivery spec, the BDS values bound what is on the arms at any instant (the CG/stability widget's per-drum inputs) | [BDS Table 3]; distinction documented in `docs/map_reference.md` §"The 30 kg question" |
| Drum dims (W × ⌀, scoop W × H) [m] | small 0.1989 × 0.2375, 0.0516 × 0.0264 · medium 0.2461 × 0.2951, 0.0635 × 0.0345 · large 0.3526 × 0.4371, 0.0904 × 0.0478 (`DRUM_DIMENSIONS_M`) | [BDS Table 1] |
| Cut rule | ≤50 % of scoop opening (`MAX_CUT_DEPTH_FRAC`); `max_cut_per_pass_m("large")` = 0.0239 m/pass | [BDS p.7] |
| Tangential/cut ratio | 8.5× drum tangential velocity over linear cut speed | [BDS] |
| Arm excavation load | 18.5 N·m "predicted excavation load on the moon" (arm actuator) | [SCHULER24 Table 7] |
| Dig power | 48.43 W = 18.5 N·m × ω(25 RPM) | derived [CALIB] (18.5 published at 500 RPM accelerated-life; paired with 25 RPM operational) |
| Dig energy | 4151 J/kg = dig_power / (42 kg/hr); honest band (rated 18 RPM, 1.0×@25) = (2989, 4151) J/kg (`dig_energy_bounds_j_per_kg`) | derived |
| Arm pivots | base_link x = ±0.20 m (`ARM_ORIGIN_FRONT/BACK`, sidecar) · link 0.28 m [ASSUMPTION] · travel ±110° [ASSUMPTION] · 20°/s slew [ASSUMPTION] · arm+drum mass share 0.15/arm [ASSUMPTION] | `stewie/specs/arm_state.py` |
| Arm lift efficiency | 0.60 in arm_state.py vs 0.5 in rassor_mass_model.py — see flag F3 | [CALIB] |

#### Cameras (LAC-twin 8-camera rig today; flight = stereo unit + sides + between-drums ×2 redundancy)

Offsets in base_link (x fwd, y up, z left) [m], from the two-vehicle spec harvest of
`camera_rig.gd`/`sidecar.gd`:

| Camera | Offset | Look |
|---|---|---|
| front_left / front_right | (0.30, −0.10, ±0.035) — baseline 0.070 m (`STEREO_BASELINE_M`; John's estimate: the flown reduced baseline is figure-only; the published 16.5 cm split design (`STEREO_BASELINE_REJECTED_M`) was REJECTED for calibration loss under load) | +X, pitchable |
| rear_left / rear_right | (−0.30, −0.10, ±0.035) — baseline 0.070 | −X |
| left/right_mono | (0.0, −0.05, ±0.285) | ±Z |
| drum_front_cam | (0.10, 0.18, 0) | at the live front drum joint |
| drum_back_cam | (−0.10, 0.18, 0) | at the live back drum joint |

| Optics | Value | Source |
|---|---|---|
| Sensor (flight) | Sony IMX547, 5 MP, 2.74 µm pitch; IMX264/C-mount rejected (vacuum/grease) | [SCHULER24 pp.24-28] |
| Aperture / focal | f/4; 6 mm and 4.4 mm candidates (`CAMERA_FOCAL_MM_CANDIDATES`) | [SCHULER24] |
| CALIB profile | 1024×768, FOV_X 73.99°, fx = 679.570 px (`STEREO_FX_PX`) — the EZ-RASSOR URDF value | URDF |
| FLIGHT profile | 2472×2064, 6 mm/2.74 µm → fx = 2189.8 px (`flight_fx_px(6.0)`) | [SCHULER24] doc-true |
| Clip | near 0.02 / far 100 m | sidecar scale |
| Stereo working band | z_min = fx·b/N_disp = 0.372 m (N=128); z_max = √(0.075·fx·b/σ_d) ≈ 1.89 m (σ_d = 1 px) (`stereo_range_m`) | [DERIVED]; sub-0.25 m grazing views carry a systematic matcher bias (G2 calibration 2026-06-10) |

#### Lighting (flight: six LED units; the single-cam-set twin carries four)

| Item | Value | Source |
|---|---|---|
| LED unit | 3000 lm max, 42° FWHM TIR optic, 3 LEDs/unit (`LED_MAX_LUMENS`, `LED_BEAM_FWHM_DEG`, `LED_PER_UNIT`) | [SCHULER24 "Lighting Design"] |
| Count | 6 units total flight; 1 per mono camera; stereo bank = 2 units on the chassis side OPPOSITE the stereo module (a known light-camera baseline: active shadow-ranging geometry) | [SCHULER24] |
| Twin placement | mono LEDs at the mono camera mounts; stereo_bank_a/b at (0.30, 0.0, ±0.12) [ASSUMPTION standoff] | two-vehicle spec |

#### Render & stance

| Item | Value |
|---|---|
| Mesh set | `assets/ipex/` — rover_body, wheel, drum, drum_arm (4 glb, CC0 self-authored, `scripts/gen_ipex_mesh.py`); registry `render_assets="ipex"` |
| AprilTag | 0.1524 m test-site tag (per-scene truth) |
| Known stance gap | the articulated build still places wheels/arms by the EZ-RASSOR URDF stance (gauge 0.57 / wheelbase 0.40 / r 0.18 / CG 0.30 in rover.py + constants); the IPEx-true placement table (track 0.5207, r 0.1524) is the flagged blocking item (two-vehicle spec §"What complete per-vehicle still requires") |

### 1.2 RASSOR 2.0 (TRL-4 breadboard precursor; the platform the test data comes from)

| Item | Value | Source |
|---|---|---|
| Dry mass | 65 kg | [SCHULER22 BD-scaling] / [R2D] |
| Wheels | 4 × ⌀0.43 m (r = 0.215); track 0.5207 m (the test config carried IPEx wheels for [WHEELTEST]) | [WHEELTEST] (Zhang wheel testing) |
| Drums | 4 × large drum halves; **80 kg documented DESIGN HOLD** (`drum_capacity_kg=80.0`) — TRL5 conformance review 2026-06-10 corrected the earlier 2×24.98 two-drum assumption; BDS Table 3's own 4-drum measured figure is 99.94 kg, the design hold is the binding number | [R2D p.7] / [BDS Table 3] |
| Drum actuator | ~25 RPM max / ~18 rated | [R2D] |
| Registry geometry | gauge 0.5207 · wheelbase 0.45 [CALIB] · wheel r 0.215 · CG 0.34 [CALIB] | vehicles.py |
| Energy model | REUSES the IPEx-grounded model (RASSOR-2's own power unpublished — disclosed, not fabricated) | registry provenance |
| Arm-raise observable | drum mass ∝ ∫arm power, R² = 0.996 (ICE-RASSOR line; §4.8) | NTRS 20210022781 |
| Render | `assets/rassor_nasa/` mesh set on disk — not yet bound to the registry entry (`render_assets=""`) | asset tree / two-vehicle spec |
| Role | Earth-validation vehicle on the GMRO BP-1 bed (`bp1_testbed` soil) | T7.1 |

### 1.3 EZ-RASSOR (render-body / stance provenance entry, `ui_visible=False`)

Geometry = the MIT EZ-RASSOR URDF (FlaSpaceInst/UCF; `docs/ezrassor_assets.md`): gauge 0.57,
wheelbase 0.40, wheel r 0.18, CG = `constants.CG_HEIGHT_M` (0.30) — mirrors the rover.py globals
and the default rendered mesh. Energy/drum reuse the IPEx-grounded model (EZ-RASSOR's own
mass/power are not separately sourced and NOT fabricated). The two-vehicle spec dissolves this
entry into "the URDF/stance SOURCE several defaults still carry."

### 1.4 Power sources & tools (registries in vehicles.py)

| Entry | Values | Provenance |
|---|---|---|
| `ipex_battery` (PowerSource) | 12S/30Ah Li-ion, capacity = `battery_energy_j()` = 4.795 MJ, recharge 700 W | ipex_specs (NTRS 20240008162) + 12S/30Ah pack; recharge_w [CALIB] |
| `lander_tower` (PowerSource) | continuous-only, 700 W | [ASSUMPTION] shared surface power station (K8 PSR tower); continuous_w reuses the [CALIB] recharge power, not a new fabricated value |
| `sinter` (Tool) | grants the `sinter` capability; energy 0.92 MJ/kg = `constants.SINTER_ENERGY_J_PER_KG` (thermodynamic floor; measured microwave PROCESS energy is 69 MJ/kg, `SINTER_PROCESS_ENERGY_J_PER_KG_MEASURED`); product density 2300 kg/m³ = `RHO_SINTERED` (microwave-sinter measured) | [CALIB]/[SOURCED] (Lin 2024, Zhang 2020); host platform mass/power unsourced → kept a tool, not a fabricated vehicle. `constants.SINTER_ENABLED = False` gates it off for the IPEx baseline (no sinter head; energetically incompatible with the pack) |

Action vocabulary (`ACTIONS`): drive, excavate, haul, dump, compact, grade, fill, sinter,
process. IPEx/RASSOR-2/EZ-RASSOR base capabilities: {drive, excavate, haul, dump, compact} — NO
sinter without the tool.

---

## 2. Bodies

Registry: `stewie/specs/bodies.py` (`BODIES`, `DEFAULT_BODY = "moon"`); systematic review
`docs/bodies_sysrev.md`. `bekker_regime` = "gravity-loaded" (model valid) or "microgravity"
(Bekker OUT OF REGIME — drive env runs with a warning; treat as placeholder). Where Bekker is
None, the lunar moduli stand in as an explicit flagged analog via `params_for_body()`.

| Body | g [m/s²] | ρ_bulk [kg/m³] | Cohesion [Pa] | φ [°] | Repose [°] | Bekker (k_c [N/m²], k_phi [N/m³], n) | Regime | Confidence (verbatim tags) |
|---|---|---|---|---|---|---|---|---|
| moon | 1.62 | 1300 | 170 | 35 | 35 | (1400, 820000, 1.0) | gravity-loaded | g/density/cohesion/friction MEASURED (Apollo + ChaSTE); Bekker MEASURED (NASA LTV, NTRS 20220010732) |
| mars | 3.71 | 1500 | 1000 | 35 | 33 | (23200, 606700, 1.0) | gravity-loaded | g MEASURED; density/cohesion/friction MEASURED in-situ (MER/InSight); Bekker ESTIMATED (GRC-3 simulant — no native-Mars bevameter) |
| ceres | 0.284 | 1300 | None (UNKNOWN) | 34.5 | 34.5 | None → lunar analog (flagged) | gravity-loaded | g MEASURED (Dawn); repose 34.5 MEASURED; density ESTIMATED; cohesion + Bekker UNKNOWN; friction = repose proxy |
| bennu | 4.0e-5 | 1190 | 2 | 33 | 33 | None — Bekker INVALID (microgravity rubble pile) | microgravity | g/density/cohesion MEASURED (OSIRIS-REx); friction ESTIMATED (boulder morphology). g varies ~3e-5–8.5e-5 across the body |
| phobos | 0.0057 | 1850 | 500 | 38 | 38 | None → lunar analog (flagged) | microgravity | g/density MEASURED; cohesion/friction ESTIMATED (tidal-fracture models); Bekker UNKNOWN (milli-g; MMX/IDEFIX ~2027). g varies ~210 %/~450 % (shape/tides) |
| earth | 9.81 | 1600 | 1040 | 28 | 34 | (990, 1528430, 1.1) | gravity-loaded | reference/validation: Wong dry-sand Bekker table |
| bp1_testbed | 9.81 | 1750 | 1040 | 28 | 34 | (990, 1528430, 1.1) [ANALOG: Wong dry sand] | gravity-loaded | density MEASURED (BP-1 compacted [WHEELTEST]); shear 27–32 kPa + penetration 206–226 kPa MEASURED [BDSCALE] as provenance; Bekker [ANALOG] — a BP-1 fit is unpublished and deliberately NOT fabricated |

Repo lunar baseline (constants.py, distinct from the bodies table): RHO_SURFACE 1300 / RHO_DEEP
1920 kg/m³, Z_T 0.12 m, COHESION 170 Pa, PHI 37°, K_C 1400, K_PHI 820000, N_SINKAGE 1.0, K_SHEAR
0.018 m, SLIP_C1 0.4 / SLIP_C2 0.3 [UNKNOWN], THETA_R 35° (30–47 envelope), SWELL_FACTOR 1.2.
Polar siblings (ChaSTE, Chandrayaan-3, 69.4° S): 750 / 1300 / 1940 kg/m³ over 0–3 / 3–6.5 /
0–10 cm [CALIB] — do not conflate with RHO_DEEP @ ~1 m.

---

## 3. Datasets

### 3.1 In-repo DEM bundles (`samples/lunar_dem/`)

All three: 2000×2000 @ 5.0 m cell (10×10 km), gravity 1.62, fine_cell 0.02 m; fields
heightmap/mass_areal/density (.rf32 `<f4`), disturbance (normalized), state_label (.r8 u1,
VIRGIN/TREAD/EXCAVATED/SPOIL/COMPACTED_BERM/SINTERED); regolith model = uniform 0.12 m loose
mantle @ 1455.83 kg/m³ (ChaSTE depth-integrated mean [CALIB]), 174.7 kg/m² areal; frame =
south polar stereographic, R = 1737400 m sphere (IAU_2015:30135); z = height above sphere;
producer `scripts/build_from_dem.py` (real LOLA ingest, Lane A); citation Barker et al. 2021
(PSS 203:105119) + Mazarico et al. 2011; license basis US-Gov work → CC0-compatible.

| Bundle | world_bounds_m (x0,y0)–(x1,y1) | Height range [m] | relief p98–p2 [m] | datum offset [m] | crop window (row0,col0) |
|---|---|---|---|---|---|
| `haworth_10km_5m` | (−52900, 95400)–(−42900, 105400) | −96.6 … 2842.2 | 2702.3 | 1381.01 | (0, 0) |
| `nobile_rim1_10km_5m` | (83000, 100000)–(93000, 110000) | 877.8 … 6102.5 | 4809.1 | 3689.22 | (2000, 1800) |
| `shackleton_rim_10km_5m` | (−3000, −10000)–(7000, 0) | −2847.9 … 1739.1 | 4405.0 | −534.27 | (200, 1200) |

⚠ The nobile_rim1 and shackleton_rim `metadata.json` files carry stale Haworth descriptive
strings (scene_name, region, dem_provenance.source) — see flag F1. The numeric georeferencing
(world_bounds, height ranges, crop windows) is per-bundle. `haworth_10km_5m` additionally
carries `slope_anchor.json`.

### 3.2 Source DEMs (`/mnt/projects/datasets/lola_5mpp/` — PGDA Product 78, Barker 2021)

Fetched by `scripts/fetch_dem_data.py` from
`https://pgda.gsfc.nasa.gov/data/LOLA_5mpp/<Dir>/<Dir>_final_adj_5mpp_surf.tif` (URL probed live
2026-06-10; <1 MB downloads refused as error pages — "the 206-lies lesson"). 5 m/pix,
south polar stereographic, MOON_ME/DE421, pixel-registered.

| File | Size [bytes] | PGDA site → region |
|---|---|---|
| `Haworth_final_adj_5mpp_surf.tif` | 142,123,767 | Haworth |
| `Site04_final_adj_5mpp_surf.tif` | 40,980,806 | Site04 = Shackleton rim |
| `Site06_final_adj_5mpp_surf.tif` | 64,025,603 | Site06 = Nobile rim 1 |

Known site directory map (fetch script `SITE_DIRS`): Haworth, Shoemaker, Site01 = Connecting
ridge, Site04 = Shackleton rim, Site06 = Nobile rim 1, Site07 = Peak near Shackleton, Site11 =
de Gerlache rim, Site20 = Leibnitz beta plateau, Site23 = Malapert massif, DM2 = Nobile rim 2.

### 3.3 LuNaMaps SfS approach-corridor mosaic (`/mnt/projects/datasets/lunamap_sfs/`)

Bertone/Barker/Mazarico 2023, doi:10.5281/zenodo.10258683. 30 m/pix, 60–80° S strip
(~18,000 km²); for optical-navigation / approach-phase evaluation (not site-scale). Held as
`share_hls_v2_mar.tar` (1,092,108,288 bytes, size recorded in `fetch_dem_data.py` for install
verification; the TAR is only served from the PGDA product page — no stable data-tree URL) +
extracted `share_hls_v2/`. Contents per its `guide.txt` (verbatim mapping):

| File | What it is (guide.txt) |
|---|---|
| `mosaic-sfs_v2.tif` | "our new terrain model @30m/pix" |
| `mosaic-sfs_hs.tif` | hillshade (azi 300°, elev 20°) of the SfS DEM |
| `mosaic-ldem.tif` / `mosaic-ldem_hs.tif` | LDEM over the region of interest / its hillshade |
| `hls_track.shp` | polygon covering the region of interest |
| `diff_ldem_30.png` / `mosaic_vs_ldem.tif` | vertical-difference statistics vs LDEM / georaster |
| `diff_overlaps_30.png` / `mosaic_overlaps.tif` | tile-overlap vertical differences / georaster |
| `disp_maps_plots/`, `dispmap_30.png`, `dmaps_x_mosaic.tif`, `dmaps_y_mosaic.tif` | per-tile x/y disparity maps, RMS, georasters |

### 3.4 SPICE kernels (`$STEWIE_SPICE_KERNELS`, default `/mnt/projects/datasets/spice_kernels/`)

NAIF generic kernels (https://naif.jpl.nasa.gov/pub/naif/generic_kernels/), loaded by
`stewie/specs/solar.py` (`_KERNELS`): `de440s.bsp` (planetary ephemeris, 32,726,016 B) ·
`moon_pa_de440_200625.bpc` (lunar PA orientation, 12,863,488 B) · `moon_de440_250416.tf`
(MOON_ME frames kernel) · `naif0012.tls` (leapseconds) · `pck00011.tpc`. Manual cross-check
oracle: WebGeocalc (https://wgc.jpl.nasa.gov:8443/webgeocalc/). Mission epoch anchor:
`MISSION_EPOCH_UTC = "2026-11-15T00:00:00"` [ASSUMPTION], settable.

### 3.5 Live tile services (`docs/map_reference.md`, each tile-verified before listing)

NASA Trek (the globe basemaps, fetched live, no download):
`https://trek.nasa.gov/tiles/Moon/EQ/{product}/1.0.0/default/default028mm/{z}/{y}/{x}.png`

| Trek product |
|---|
| `LRO_WAC_Mosaic_Global_303ppd_v02` |
| `Kaguya_TCortho_Mosaic_Global_4096ppd` |
| `LRO_LOLA_ClrShade_Global_256ppd_v06` |
| `LRO_LOLA_DEM_Global_128ppd_v04` |
| `LRO_LOLA_ClrSlope_Global_16ppd` |
| `LRO_LOLA_ClrRoughness_Global_16ppd` |
| `LRO_Diviner_ST_Avg_Clr_Global_32ppd` |
| `LRO_LOLA_Shade_Global_128ppd_v04` |

Earth polar-capable layer: NASA GIBS Blue Marble (https://gibs.earthdata.nasa.gov/, EPSG:4326
WMTS). Globe: Cesium 1.119 (pinned via unpkg). Lunar CRS: IAU_2015:30135 (south polar
stereographic, R = 1737400 m sphere) via pyproj's IAU registry. LOLA lineage:
https://ode.rsl.wustl.edu/moon/ · https://pds-geosciences.wustl.edu/missions/lro/lola.htm ·
https://pgda.gsfc.nasa.gov/.

### 3.6 DEM product map (which file for which job — map_reference.md)

| Product | Resolution / coverage | Use |
|---|---|---|
| PGDA Product 78 (Barker 2021) | 5 m/pix, per-site | site-scale planning/excavation (the in-repo bundles' lineage) |
| PGDA Products 81/90 (Barker 2023) | 5–30 m/pix, polewards of 80° S | regional context between sites |
| LuNaMaps SfS strip (Bertone 2023) | 30 m/pix, 60–80° S corridor | optical-navigation / approach-phase evaluation |
| SLDEM2015 | 60 m/pix global | basemap-scale only |

---

## 4. Formulas (equation · variables · code home · provenance)

### 4.1 Bekker pressure-sinkage (`stewie/physics/terramechanics.py`)

| Equation | Variables | Home | Provenance |
|---|---|---|---|
| p = (k_c/b + k_phi·s(ρ)) · z^n, inverted z = (p / (k_c/b + k_phi·s))^(1/n) | p contact pressure [Pa] = N/(L·W); b = min(L, W) Bekker plate width [m]; k_c 1400 Pa/m^(n−1), k_phi 820000 Pa/m^n, n 1.0 (defaults from constants.py, [CALIB] Apollo-era) | `bekker_pressure_sinkage`, `wheel_static_sinkage` | spec §5.2; LOAD-BEARING since Phase 1 (`physical=True` drive-path default) |
| s(ρ) = max(1, ρ/ρ_surface) | density-stiffening (paving emergent, denser soil bears better) | `density_stiffening` | [CALIB] linear law |
| N_wheel = (m_dry + m_payload)·g / n_wheels | ~12.15 N/wheel dry at lunar g; ~24.3 N at full 30 kg payload | `static_wheel_load_n` | IPEx 30 kg-class [SCHULER24] |
| f = z/(t − z), apply ρ *= (1+f), cap at RHO_DEEP | mass-conserving sinkage→density map (height = mass/ρ re-derives); t column thickness | `sinkage_to_density_factor`, vectorized `physical_compaction_field` | spec §10 invariant 1 |
| Lyasko reduce: each of {k_phi, c} ×= 1 − frac·clip(1 − g/g_E, 0, 1), frac = 0.30; n unchanged (n_frac = 0) | 1g → 1/6g: k_phi↓, c↓ → net sinkage↑; k_c, φ little change | `lyasko_reduce`, `TerramechanicsParams.lunar()` | DIRECTION sourced (Lyasko 2010); MAGNITUDE [CALIB], oracle-deferred (FIX-1/FIX-2) |
| DR envelopes: n ~ U(0.8, 1.0); k_phi ~ U(0.2e6, 0.82e6); c ~ U(100, 1000) Pa; c1 ~ U(0.3, 0.5); c2 ~ U(0.2, 0.4) | the honesty tags ARE the randomization spec | `domain_randomize` | spec §5.2 / §7.5 envelopes, not invented spreads |

### 4.2 Slip ladder (`stewie/physics/slip.py`)

| Equation | Variables | Home | Provenance |
|---|---|---|---|
| H_max = c·A + N·tan φ | Coulomb-Mohr traction ceiling; A = contact area | `traction_budget` | spec §6 |
| H(s) = H_max·(1 − (1 − e^(−x))/x), x = s·L/K | Janosi-Hanamoto developed thrust; L contact length, K = K_SHEAR 0.018 m [CALIB] | `developed_thrust` (expm1-stable) | spec §5.2 |
| invert H(s) = demand; demand ≥ H_max (or above H(s_max)) → (s_max, ENTRAPPED) | bisection on the monotone curve; s_max 0.99 | `slip_for_demand` | Spirit-mode runaway |
| m_slip(s) = 1 + (c1 + c2·s)·s/(1 − s), s capped 0.95 | slip-sinkage multiplier (θ_m = (c1 + c2·s)·θ_f rearward stress migration); c1 0.4 / c2 0.3 [UNKNOWN] | `terramechanics.slip_sinkage_multiplier` | spec §6, magnitudes [UNKNOWN] |
| R_c = (b/(n+1))·(k_c/b + k_phi)·z^(n+1) | Bekker compaction (motion) resistance — feeds the runaway | `compaction_resistance` | Bekker |
| fixed point: demand = f·W_along + R_c(z) → s = slip_for_demand → z = z_static·m_slip(s) → … converge or diverge (entrapment: s ≥ 0.95, z ≥ z_entrap ≈ 0.36 m [PROXY], or demand ≥ budget) | f = demand_frac (operator back-off = the recovery lever) | `slip_sinkage_equilibrium` | qualitative validation (monotone, runaway, recovery); quantitative fit oracle-deferred |
| P_elec = n_wheels·demand·v / ((1 − s)·η) | rigorous soil/g/slope-aware drive power; LOWER bound (compaction + grade only — no bulldozing/hysteresis) | `bekker_drive_power_w` | bracket with the constant-Crr estimate below |

### 4.3 Energy (`stewie/specs/ipex_specs.py`)

| Equation | Numbers | Home | Provenance |
|---|---|---|---|
| P_drive = N_wheels · τ_motor · ω | 4 × 0.063 N·m × ω(1530 RPM) = 40.38 W (motor-side, Earth-g design case; lower bound on electrical) | `drive_power_w` | [SCHULER24 Table 3] + [CALIB] |
| E_drive/m = P_drive / v | 40.38 / 0.30 = 134.6 J/m | `drive_energy_per_m` | derived |
| P_dig = τ_arm · ω_drum | 18.5 N·m × ω(25 RPM) = 48.43 W | `dig_power_w` | [SCHULER24 Table 7] + [CALIB] pairing |
| E_dig/kg = P_dig / ṁ | 48.43 / (42/3600) = 4151 J/kg; band (2989, 4151) at rated-18 RPM | `dig_energy_per_kg`, `dig_energy_bounds_j_per_kg` | derived; drum rate is the chain's one [ASSUMPTION] |
| E_pack = 12 × 3.7 V × 30 Ah × 3600 | 4.795 MJ = 1332 Wh | `battery_energy_j` | [BATTERY] |
| P_lunar = m·g·(crr·cos θ + sin θ)·v / η | physical steady-drive draw; ~6× below the Table-3 figure at lunar g flat | `lunar_drive_power_w` | [PHYSICS] force; crr 0.15 [ASSUMPTION], η 0.5 [CALIB] |
| P_heater = ε·σ·A·(T_set⁴ − T_sink⁴) + G·(T_set − T_sink) | T_set −20 °C [ASSUMPTION], ε 0.10, A 0.30 m², G 0.05 W/K all [ASSUMPTION]; sinks [SOURCED-ENV]: lunar day +110 / night −180 / PSR −233 °C | `thermal_heater_power_w`, `survival_heater_power_w` | heat balance [PHYSICS]; magnitude order-of-magnitude |
| P_total = drive + dig + avionics(15) + comms(15) + thermal | order-of-magnitude budget | `system_power_w` | [ASSUMPTION] housekeeping |
| Lift: W = m·g·Δh/η | ICE-RASSOR arm-raise observable; h 0.5 m, η 0.5 [CALIB] | `rassor_mass_model.arm_raise_lift_energy_j`; arm geometry form `arm_state.raise_energy_j` (Δh = L·Δsin, η 0.60 — flag F3) | gravity work; AR R² 0.996 is physically this term |

### 4.4 CG with drum loads (`stewie/specs/arm_state.py`)

cg_offset = (Σ_arms [m_link·(p − p_stow) + m_load·p]) / (m_dry + m_load_f + m_load_b), per arm:
p = (o_x + sgn·L·cos a, L·sin a), stow = (o_x + sgn·L, 0); m_link = 0.15·m_dry [ASSUMPTION],
L = 0.28 m [ASSUMPTION], pivots o_x = ±0.20 m (sidecar). The load enters at the DRUM position,
not at stow — the weighted drums are the balance ballast posture maneuvers with (RASSOR's
signature capability). Home: `ArmState.cg_offset_m` (test-pinned). Companion:
`net_dig_reaction_n(τ, r) = Σ ±τ/r` — counter-rotating drums net ~0 horizontal dig reaction
(KSC-TOPS-7).

### 4.5 SSA tip margins (`stewie/physics/stability.py`)

| Equation | Variables | Home |
|---|---|---|
| SSA = atan(half_support / h_cg); roll half = gauge/2, pitch half = wheelbase/2 | exact componentwise for the rectangular wheel-support polygon (audit M19 refuted a cross-term) | `ssa_deg`, `tip_tilt_limit_deg` |
| margin = min(SSA_pitch − |pitch|, SSA_roll − |roll|); risk ok/warn(0.7·SSA)/tip; NaN attitude fails CLOSED | gauge/wheelbase/cg per consumer — server `/stability` uses gauge 0.5207 (`SKID_STEER_TRACK_M`), wheelbase 0.40 (`rover.WHEEL_BASE_M`), cg 0.30 + drum dz (`constants.CG_HEIGHT_M`); rover_env uses `vehicles.geometry_of` (IPEx: 0.3645/0.30/0.21) — flag F2 | `stability` |

Tipping is TERRAIN-driven, not dig-driven (counter-rotation cancels the dig moment); RASSOR is
symmetric and recovers from overturning — a tip is recoverable, still avoided (time + risk).

### 4.6 Solar azimuth/elevation (`stewie/specs/solar.py`, two backends, SPICE-preferring dispatch)

Mean-motion fallback (kernel-free, disclosed approximation — mean motions only, no
perturbations/eccentricity/parallax/refraction):
sin el = sin φ·sin δ + cos φ·cos δ·cos H; az = atan2(−cos δ·sin H, cos φ·sin δ − sin φ·cos δ·cos H),
az from local north eastward. δ = 1.54°·sin(2π·t/T_sid + phase) (LUNAR_OBLIQUITY_DEG, Cassini
state), sub-solar lon = 360°·t/T_syn; T_syn = 29.530589 d, T_sid = 27.321661 d. Homes:
`sub_solar_point`, mean-motion `sun_az_el`.

SPICE backend (`sun_az_el_spice`): Sun state via `spkpos("SUN", et, "MOON_ME", "LT+S", "MOON")`,
site = `latrec(1737.4 km, lon, lat)`, ENU basis on the IAU sphere → el = asin(u), az =
atan2(e, n). Kernels per §3.4. `sun_az_el_dispatch` picks SPICE when available;
`crosscheck_meanmotion` emits the honest fallback-accuracy artifact (max |Δaz|, |Δel| over a
synodic month).

### 4.7 Hillshade + reprojection (`stewie/server/gis_layers.py`)

| Equation | Variables | Home |
|---|---|---|
| shade = clip(n̂·l̂, 0, 1), n = (−∂z/∂x, −∂z/∂y, 1), l = (cos el·sin az, cos el·cos az, sin el); az 315°, el 45°; gray = 40 + 200·shade | clean cartographic (lambertian) hillshade from the RAW heightmap (the matplotlib preview figure was being draped onto the Moon); the real-sun SHADOW layer is separate (`dart.illumination.horizon_clip`) | `render_globe(kind="dem")` |
| reprojection: build the output lat/lon grid → forward-project every output pixel into the polar-stereo frame (pyproj, IAU_2015:30135 — the SAME CRS as the tile bounds) → nearest-neighbor sample of the source raster; bbox from a 256-point boundary ring inverse-projected; outside-footprint pixels transparent | fixes the rotated/misaligned naive stereo-into-latlon drape; every layer carries ITS OWN bbox | `_reproject`, `_tile_geo` |
| slope layer: slope = atan(hypot(∂z/∂x, ∂z/∂y)) [deg]; hazard: no-go > 20° [WHEELTEST tested], graded band 15–20° (nominal→tested); PSR: never lit across a 12-azimuth horizon sweep at el 3° | thresholds from the slope hierarchy (§1.1) | `render`, `render_globe` |

### 4.8 Drum-mass inference (`stewie/physics/rassor_mass_model.py`, NTRS 20210022781 — ICE-RASSOR)

Linear structure shared by all three models: mass = slope·feature + intercept
(`LinearMassModel`; coefficients NOT published — figure-only, RASSOR/1-g-specific — so `.fit`
calibrates from data, never fabricated).

| Model | Feature | Published quality (verbatim) |
|---|---|---|
| Arm-Raise (AR) | integrated arm-motor power during raise/lower (gravity work) | R² = 0.996 front / 0.974 rear (Fig 6) |
| Free-spinning Drum Current (FDC) | steady average drum current at constant speed | R² = 0.989 / 0.985 (Fig 8); MPE 7.40 % over range (11.84 % with 2 outlier cycles), **2.56 % when > half full (> 20 kg)**; best accuracy, NN-augmented + flight-integrated |
| Excavation Drum Current (EDC) | aggregated dig-cycle current | R² = 0.7601 (Fig 12) |

Forward observable: I = baseline + slope·m, baseline 1.70 A / slope 0.032 A/kg @ 1 g — [CALIB],
read off Fig 7/8, NOT published coefficients; optional g-rescale slope·g/g_ref is a FLAGGED
assumption (paper is 1-g only). Uncertainty: `drum_mass_uncertainty_frac` = 2.56 % above 20 kg,
linear blend up from 7.40 % (or 11.84 % with outliers) below (continuous, monotone upper bound —
audit 2026-06-09 fixed the hard step). Offload autonomy: `should_offload` fires when the UPPER
confidence bound m·(1+unc) reaches capacity (default 30 kg/cycle) — stops before overflow, and
knowledge is tightest (2.56 %) exactly where the decision is made. `DrumSensor` packages
observable + calibrated inverse + decision with optional seeded noise (std =
noise_frac·slope·capacity; noise_frac 0 = deterministic).

---

## 5. Code-vs-docs disagreements (flagged, NOT resolved)

| # | What | The two sides |
|---|---|---|
| F1 | **Stale Haworth strings in the nobile/shackleton DEM bundle metadata.** | `samples/lunar_dem/nobile_rim1_10km_5m/metadata.json` and `shackleton_rim_10km_5m/metadata.json` both say `scene_name: "lunar_dem/haworth_10km_5m"`, `region: "Haworth"`, `dem_provenance.source: "PGDA LOLA_5mpp Haworth_final_adj_5mpp_surf.tif"` — but the directory names, `docs/map_reference.md` (Site04 = Shackleton rim, Site06 = Nobile rim 1, both downloaded to `datasets/lola_5mpp/`), and the per-bundle numeric georeferencing (disjoint world_bounds, height ranges) say otherwise. Root cause visible in `scripts/build_from_dem.py`: `scene_name`, `REGION = "Haworth"` and the provenance `source` string are HARDCODED regardless of `--src`. |
| F2 | **IPEx stability geometry: three different gauge/wheelbase/CG triplets.** | (a) `vehicles.py` registry ipex: gauge 0.3645 (= 0.7 × 0.5207), wheelbase 0.30, CG 0.21 — consumed by `envs/rover_env.py` via `geometry_of`; the design doc agrees ("gauge 0.3645 derived"). (b) `server.py` `/stability`: gauge 0.5207 (`SKID_STEER_TRACK_M`), wheelbase 0.40 (`rover.WHEEL_BASE_M`), CG 0.30 (`constants.CG_HEIGHT_M`) — and `docs/map_reference.md` §"Stability-model fidelity" records "SSA gauge **0.5207** (was 0.57) FIXED". (c) `rover.py`/`constants.py` EZ-RASSOR render stance: 0.57 / 0.40 / 0.30 (the two-vehicle spec's flagged STANCE GAP). Note [WHEELTEST]'s 0.5207 is described in ipex_specs.py as the kinematic track measured ON the RASSOR-2 test platform, while vehicles.py treats it as the RASSOR-2 track and derives IPEx at 0.7× — the same source number is read two ways. |
| F3 | **Arm lift efficiency 0.60 vs 0.5.** | `arm_state.py` `ARM_LIFT_EFFICIENCY = 0.60` with the comment "[CALIB] (rassor_mass_model.ARM_LIFT_EFFICIENCY)", but `rassor_mass_model.py` `ARM_LIFT_EFFICIENCY = 0.5`. The cross-reference and the value disagree. |
| F4 | **K_PHI 820000 vs 200000 (known, self-documented).** | `constants.py` K_PHI = 820000 (spec §5.2 Apollo-era) vs the committed Chrono SCM oracle's JSC-1A analogue k_phi = 0.2e6 (`TerramechanicsParams.scm_oracle`, chrono_scm_rover.py:112) — ~4× apart; SCM predicts MORE sinkage. Tracked as FIX-1, deferred to the PyChrono load-sweep oracle; the DR envelope spans exactly this range. Left open by design. |
| F5 | **RASSOR 2.0 drum capacity 80 vs 99.94 kg (documented in-code).** | Registry holds the R2D p.7 **80 kg design hold** (binding); [BDS Table 3]'s own 4-drum measured figure is 99.94 kg. The TRL5 conformance review 2026-06-10 already corrected an earlier 2×24.98 assumption; both numbers are real, the design hold was chosen. Recorded so future readers don't "fix" it back. |
| F6 | **IPEx 30 kg: per-cycle vs per-drum (resolved semantics, easy to misread).** | `vehicles.py` `drum_capacity_kg = 30` is the per-CYCLE delivery spec [SCHULER24 RDS]; the per-drum instantaneous holds are [BDS Table 3] small 3.80 / medium 7.30 kg. Consistent, not contradictory — documented in `docs/map_reference.md` §"The 30 kg question"; preserved here verbatim so the registry number is not mistaken for a per-drum hold. |
