# STEWIE Astrophysics & Planetary-Science Primer

**Audience:** a new intern or operator joining the project. You do not need an astronomy
background to read this. You DO need to trust the numbers — so every number in this primer
was read out of the codebase, and each section ends with pointers to the exact files that
carry it. Nothing here is invented; where the code tags a value `[CALIB]`, `[ASSUMPTION]`,
or `[UNKNOWN]`, this primer says so too.

Provenance shorthand used below (these are the repo's own citation tags, defined in
`stewie/specs/ipex_specs.py` and `docs/map_reference.md`):

- **[SCHULER24]** — IPEx TRL-5 Design Overview, NTRS 20240008162
- **[WHEELTEST]** — IPEx wheel testing in lunar regolith simulant, ASCE Earth & Space 2024
- **[BDSCALE]** — IPEx bucket-drum scaling experiments, ASCE Earth & Space 2022
- **[R2D]** — RASSOR 2.0 design paper (drum actuator rates)
- **NASA LTV** — LTV terramechanics white paper, NTRS 20220010732 (lunar Bekker moduli)
- **ChaSTE** — Chandrayaan-3 in-situ polar density profile (as carried in `constants.py`)
- Live data services (NASA Trek tiles, NAIF/SPICE kernels, LOLA PDS, PGDA) are indexed in
  `docs/map_reference.md` — that file is the source list for everything map-shaped.

---

## 1. The Moon's sky — day, night, and the polar spiral

### A day on the Moon is a month long

The Moon rotates once per orbit (it is tidally locked), so the Sun takes one **synodic
month** — **29.530589 days** (`SYNODIC_MONTH_S` in `stewie/specs/solar.py`) — to go from
local noon to local noon. The mission planner carries this as the operating timescale:
a lunar day is **708.7 hours**, daylight is roughly half of that (**354.4 h**), and the
usable high-sun work window the planner budgets against is **216–264 hours**
(`BODY_TIMESCALE["moon"]` in `lode/mission_planner.py`).

That two-week day / two-week night cycle is brutal thermally. The representative sink
temperatures the power model uses (`ENV_SINK_TEMP_C` in `stewie/specs/ipex_specs.py`,
tagged `[SOURCED-ENV]`): lunar **day ~ +110 °C**, lunar **night ~ −180 °C (~90 K)**, and a
permanently shadowed crater floor ~ **−233 °C (~40 K)**. Surviving the night is a heater
problem (Section 4 of `ipex_specs.py` models it as a Stefan-Boltzmann + conduction heat
balance); the box geometry inputs there are tagged `[ASSUMPTION]`, the sink temperatures
are not.

### Almost no seasons: the 1.54° tilt

Earth's axis is tilted 23.4°, which gives us strong seasons. The Moon's spin axis is
inclined only **1.54°** to the ecliptic normal (`LUNAR_OBLIQUITY_DEG = 1.54` in
`solar.py`, the IAU/Cassini state). Consequence: the **sub-solar latitude** — the latitude
where the Sun is directly overhead — never strays more than ±1.54° from the equator. It
oscillates sinusoidally with the **sidereal month** period, **27.321661 days**
(`SIDEREAL_MONTH_S`), while the sub-solar **longitude** sweeps a full 360° once per
synodic month. (Why two different periods? See Section 6.)

### What this means at the poles

Stand at a polar site like Haworth (the project's canonical site latitude is **−87.45°**,
hard-coded as the solar authority's site in `stewie/server/session.py`). Geometry from
`solar.py`'s docstring, exact in structure:

- The Sun's **azimuth circles the entire horizon once per lunar day** — it does not rise
  in the east and set in the west; it slowly corkscrews around you.
- Its **elevation breathes inside ±(colatitude + 1.54°)**. At −87.45° the colatitude is
  2.55°, so the Sun never gets more than about 4° above (or below) the horizon — a
  months-long grazing spiral, alternating polar "summer" (sun skims above the horizon)
  and polar "winter" (it skims below).

The spec's polar sun-elevation band is **0–7°** (`SUN_ELEVATION_DEG_POLAR = 7.0` in
`stewie/specs/constants.py`, tagged `[FIXED]`). Grazing light is the defining perception
condition of the whole project: shadows are enormous, terrain relief dominates whether
anything is lit at all (Section 5), and solar power is available only in elevated,
well-exposed spots.

### Why Haworth matters

Haworth is a south-polar crater whose floor is permanently shadowed (a PSR — Section 5)
while parts of its rim see long illumination. That combination — power and cold-trapped
volatiles within driving distance of each other — is why it is an ISRU target, and why
the repo's primary terrain is the real LOLA-derived Haworth tile (PGDA Product 78; see
Section 2). It is genuinely dramatic terrain: the 10 km working crop has **2702 m of
rim-to-floor relief** (`docs/lunar_dem_10km_eval.md`, validation addendum).

One more constant for the sky: solar irradiance at the Moon is **1361 W/m²**
(`S_solar` in `constants.py`, `[FIXED]`) — no atmosphere, so that full value arrives at
the surface whenever the Sun is geometrically visible. No twilight, no haze, no
scattering: lit is lit and dark is black.

**Where this lives in the code**
- `stewie/specs/solar.py` — obliquity (1.54°), synodic/sidereal month lengths, sub-solar
  point, site azimuth/elevation, the polar-elevation-envelope statement (docstring).
- `stewie/specs/constants.py` — `SUN_ELEVATION_DEG_POLAR = 7.0`, `S_solar = 1361.0`.
- `lode/mission_planner.py` — `BODY_TIMESCALE` (708.7 h lunar day, 216–264 h op window).
- `stewie/specs/ipex_specs.py` — `ENV_SINK_TEMP_C` day/night/PSR sink temperatures and
  the heater heat-balance model.
- `stewie/server/session.py` — the Haworth site latitude (−87.45°) the solar authority uses.

---

## 2. Coordinate systems for lunar work

You will touch four coordinate layers. Keeping them straight is most of the battle.

### Selenographic latitude/longitude

"Selenographic" = lat/lon on the Moon, exactly like geographic lat/lon on Earth, defined
in a **body-fixed** frame (one that rotates with the Moon). The frame the code uses is
**MOON_ME** (Mean-Earth/polar-axis), realized through the SPICE kernels
`moon_pa_de440_200625.bpc` + `moon_de440_250416.tf` (`_KERNELS` in `solar.py`). When
`sun_az_el_spice()` asks "where is the Sun from this site," it requests the Sun's position
**in MOON_ME** and converts the site lat/lon to a 3-D point on a sphere of radius
**1737.4 km** (`r_moon = 1737.4` in `solar.py`).

### South polar stereographic projection (the working map plane)

Lat/lon is terrible for doing geometry near a pole (longitude lines converge). So all the
polar DEM products — and the project's terrain math — live in a flat projected plane:
**IAU_2015:30135**, a south polar stereographic projection on a **1737.4 km sphere**.
The PROJ definition (from `docs/lunar_dem_10km_eval.md` §"Horizontal"):

```
+proj=stere +lat_0=-90 +lon_0=0 +k=1 +x_0=0 +y_0=0 +R=1737400 +units=m +no_defs
```

X/Y are real metres; the south pole is the origin. The Haworth Product-78 tile sits at
tiepoint **X0 = −52900, Y0 = 105400** in this plane, is **5960×5960 pixels at 5 m/pixel
(29.8 km square)**, and its Z values are **height above the 1737.4 km sphere in metres,
NOT an absolute radius** — the tile's range is −1643 to +2842 m and you must NOT subtract
1737400 (this exact mistake is called out and corrected in `lunar_dem_10km_eval.md`'s
validation addendum; `dem_import.py` documents the contract as `z_semantics`).

### Pixel registration — the half-pixel lesson

A GeoTIFF tiepoint can mean two different things, and getting it wrong silently shifts
your whole world. GeoTIFF `GTRasterType=1` (**PixelIsArea**) says the tiepoint is the
**northwest CORNER of the first pixel**; `GTRasterType=2` (**PixelIsPoint**) says it is
the first pixel's **center**. The repo's affine contract is first-pixel-CENTER, and the
PGDA products declare PixelIsArea — so the ingest must shift the origin **half a pixel
inward** (`x0 += px/2; y0 -= px/2`, `dart/dem_import.py` around line 233). Before this
fix, *every bundle sat 2.5 m west and 2.5 m north of truth* (half of a 5 m pixel, in each
axis). The code's comment keeps the moral: *"positioning is the hard truth."* When you
ingest any new raster, check its raster type before you trust a single coordinate.

### The globe you see in the browser

The Cesium cockpit globe is **deliberately WGS84-shaped** (an Earth ellipsoid — Cesium
1.119's custom-globe path errors out). This is fine *because the documented invariants
hold*: imagery drapes and cursor picks share the same surface, drape bounding boxes carry
true selenographic values from the IAU CRS inverse projection, and the scale bar
multiplies the WGS84 distance by **R_body / R_earth** so it reads true body metres (it was
**3.67× off** on the Moon before that fix). All verified and recorded in
`docs/map_reference.md` §"Coordinate truth."

**Where this lives in the code**
- `dart/dem_import.py` — GeoTIFF ingest: tiepoint/scale tags, the PixelIsArea half-pixel
  fix, `z_semantics`, the IAU_2015:30135 frame string.
- `docs/map_reference.md` — the rendering pipeline table, coordinate-truth notes, and the
  full live source list (NASA Trek tiles, NAIF kernels, LOLA PDS, PGDA, pyproj/IAU).
- `docs/lunar_dem_10km_eval.md` — the Product-78 Haworth tile facts (5960², 5 m/pix,
  tiepoint, Z semantics, 2702 m relief).
- `stewie/specs/solar.py` — MOON_ME frame usage and the 1737.4 km sphere.

---

## 3. Regolith — the stuff the rover lives on

### What it is

The Moon has no soil in the Earth sense (no water, no organics, no weathering). Its
surface is **regolith**: rock smashed by billions of years of impacts into a layer of
angular fragments, from boulders down to abrasive dust. The grains themselves are
anorthositic rock and impact-glass agglutinates with a **solid grain density of
~3100 kg/m³** (`RHO_GRAIN = G_s × RHO_WATER`, with specific gravity `G_s = 3.1`, in
`constants.py`). The median grain size the repo carries is **D50 = 70 µm**
(`[CALIB]`, spec band 40–130 µm) — a fine, poorly sorted, angular silty sand.

### Density: loose over dense

Bulk density (grains + void space) is far below grain density, and it increases sharply
with depth as voids close. The repo's equatorial/Apollo-era profile (`constants.py`,
`[CALIB]`):

| Quantity | Value | Meaning |
|---|---|---|
| `RHO_SURFACE` | **1300 kg/m³** | loose fluffy fines, immediate surface |
| `RHO_DEEP` | **1920 kg/m³** | compacted material below ~1 m |
| `Z_T` | **0.12 m** | the loose-over-dense transition depth |

There is also a **polar** in-situ profile from ChaSTE (Chandrayaan-3, measured at
69.4° S): **~750 kg/m³ over 0–3 cm**, **~1300 over 3–6.5 cm**, **~1940 bulk average over
0–10 cm** (`RHO_SURFACE_POLAR` / `RHO_MID_POLAR` / `RHO_BULK_POLAR_10CM`). The constants
file carries an explicit warning: ChaSTE's 1940 at 10 cm does **not** "confirm"
`RHO_DEEP`=1920 at ~1 m — different depths, different measurements, do not conflate.

### Strength: cohesion, friction, repose

Dry granular materials get their strength from two things: **cohesion** (grains sticking
to each other — for lunar regolith it is mechanical interlocking of jagged grains, the
spec calls it "like Velcro") and **internal friction** (resistance to grains sliding past
each other, expressed as an angle). Repo values (`constants.py`, `[CALIB]`):
cohesion **170 Pa**, friction angle **37°**. The bodies registry (`bodies.py`) carries the
sourced per-body set: Moon cohesion 170 Pa / friction 35° (Apollo + NASA LTV provenance).

The **angle of repose** — the steepest slope a loose pile can hold — is nominally **35°**
with a wide envelope of **30–47°** (`THETA_R`, `THETA_R_MIN/MAX`, tagged `[UNKNOWN]`:
finer is steeper, highland steeper than mare, and the low-gravity effect is "genuinely
unsettled"). This single angle drives pile shapes, berm stability, and the planner's
berm re-hazard rule.

### Swell (bulking)

Dig up dense in-situ material and it comes out fluffed: same mass, more volume. The
spec's swell factor is **1.2** (`SWELL_FACTOR`, band 1.1–1.3, `[CALIB]`), but note the
honest detail in `constants.py`: in the conserved authority, bulking actually *emerges*
from the density gap — deep material at `RHO_DEEP` (1920) is redeposited as loose spoil
at `RHO_SPOIL` (= `RHO_SURFACE` = 1300). A bucket deposits more volume than the hole it
left. This is why cut-and-fill plans never balance by volume; the planner balances by
**mass** (Section 4).

### Volatiles

In permanently shadowed cold traps, water ice can be mixed into the regolith at up to
**5.6 ± 2.9 % by mass** (`W_ICE_MAX = 0.056`, `[UNKNOWN]`, LCROSS-derived, per the
constants file). Ice content gates a regime change (granular → cemented) and is the
economic point of the whole south-polar program. Why the ice survives there: Section 5.

### Simulants: BP-1 and the GMRO test bed

You cannot buy lunar regolith, so hardware is tested in **simulants**. The bin IPEx and
RASSOR actually drive in is the GMRO Regolith Test Bed filled with compacted **BP-1**:
bulk density **~1750 kg/m³** after compaction [WHEELTEST], shear strength **27–32 kPa**
(shear vane) and penetration resistance **206–226 kPa** (penetrometer) [BDSCALE] — all
carried in `ipex_specs.py` as reference provenance, deliberately NOT wired into the lunar
physics core. There is also a `bp1_testbed` soil entry in `bodies.py` (Earth gravity,
those measured values) so Earth-validation missions can plan against the bed the real
hardware drives in. Its Bekker moduli are an honest **[ANALOG]** (Wong dry sand stands
in) because a BP-1 Bekker fit is unpublished — the repo refuses to fabricate one.

**Where this lives in the code**
- `stewie/specs/constants.py` — densities (1300/1920/3100), Z_T, cohesion 170 Pa,
  friction 37°, repose 35° (30–47°), swell 1.2, D50 70 µm, W_ICE_MAX 5.6%, the ChaSTE
  polar profile + `polar_density_profile()`.
- `stewie/specs/bodies.py` — sourced per-body regolith constants with
  MEASURED/ESTIMATED/UNKNOWN confidence strings; the `bp1_testbed` soil.
- `stewie/specs/ipex_specs.py` — BP-1 measured properties (`BP1_*`).
- `lode/mission_planner.py` — bank-vs-loose density in cut→fill balancing (the
  bulking consequence, around the "Bulking/swell (I7)" comment).

---

## 4. Gravity and mechanics — why 1/6 g changes everything (and what it doesn't change)

### Mass is invariant; weight is not

A kilogram of regolith is a kilogram everywhere. What changes between bodies is
**weight** — the force gravity exerts on it, `W = m·g`. The bodies registry
(`stewie/specs/bodies.py`) carries the measured surface gravities:

| Body | g [m/s²] | Bekker regime |
|---|---|---|
| Earth | 9.81 | gravity-loaded |
| Mars | 3.71 | gravity-loaded |
| Moon | **1.62** | gravity-loaded |
| Ceres | 0.284 | gravity-loaded |
| Phobos | 0.0057 (varies ~210% across the body, ~450% with Mars tides) | **microgravity — Bekker invalid** |
| Bennu | 4.0×10⁻⁵ (3×10⁻⁵ equator to 8.5×10⁻⁵ poles) | **microgravity — Bekker invalid** |

Because the terrain authority conserves **mass**, the cut/fill bookkeeping is gravity-
invariant: moving 1000 kg of regolith is the same 1000 kg on any body. What gravity
scales is every **force-derived** quantity: weight on wheels, bearing pressure, sinkage,
traction, lift energy.

### Terramechanics: the Bekker model and where it breaks

Wheel-on-soil mechanics in this codebase is the classical **Bekker pressure–sinkage**
model: `p = (k_c/b + k_phi) · z^n` — pressure grows with sinkage z, with a cohesive
modulus k_c, a frictional modulus k_phi, and exponent n. The Moon's sourced values
(NASA LTV white paper, NTRS 20220010732, carried in `bodies.py`): **k_c = 1400 N/m²,
k_phi = 820000 N/m³, n = 1.0**, cohesion 170 Pa. (`constants.py` holds the same values
as the repo baseline, with an honest "PAPERED OVER" note: these are Earth-fit
calibration starting points; the Lyasko low-gravity correction says k_phi and cohesion
drop in low g while sinkage *increases* under the same load — so uncorrected moduli
UNDER-predict lunar sinkage.)

The model has a validity regime, flagged per body as `bekker_regime`. Bekker assumes the
soil is **loaded by gravity** — pressure from overburden makes the pressure–sinkage curve
meaningful. On Bennu (g ≈ 4×10⁻⁵ m/s², measured cohesion ≤ 2 Pa, a near-fluidized rubble
pile) and Phobos (milli-g), there is essentially **no overburden**: grain-to-grain
cohesion and granular dynamics dominate, the right tools are granular Bond numbers and
DEM simulation, and the Bekker math is **out of regime**. The drive environment still
runs for those bodies but emits a warning — treat the output as placeholder, not physics
(`bodies.py` module docstring).

### Why RASSOR/IPEx has counter-rotating drums

On Earth, an excavator digs by being heavy: its weight anchors it against the horizontal
reaction force of the cutting blade. In 1/6 g a 30 kg-class rover (`ROVER_MASS_CLASS_KG
= 30.0` [SCHULER24]) weighs ~49 N — about as much as a 5 kg bag of flour on Earth. It
cannot push a blade into the ground without shoving itself backwards.

RASSOR's answer (inherited by IPEx, its flight-class successor): **two bucket drums
spinning in opposite directions**, so the horizontal dig reactions **cancel each other**.
The dig force loop closes through the rover's own structure instead of through traction.
This is stated as the design thesis in `constants.py` (the rover-mass block): low mass is
deliberate, the drums cancel the dig reaction, and the consequence is *very low weight on
wheels* — which is exactly why **slip-sinkage**, not static bearing failure, is the
dominant mobility failure mode the slip ladder models (`SLIP_C1 = 0.4`, `SLIP_C2 = 0.3`,
both honestly `[UNKNOWN]` — the Spirit-rover entrapment regime).

The mobility envelope, from the sourced record (`ipex_specs.py` + the slope hierarchy
table in `docs/map_reference.md`): nominal ConOps slope **15°** [SCHULER24], demonstrated
wheel test at **20°** [WHEELTEST], RASSOR Gen-1 **failed a 30°** loose mound (slip
avalanche), planner routing default **25°** (documented as between tested and failure).
Tip-over is a separate, terrain-driven check: with the modeled geometry the static
stability angle is **~33.7° in pitch** (CG height 0.30 m is a tagged `[ASSUMPTION]`,
`CG_HEIGHT_M` in `constants.py`).

### Excavation energy: cutting mechanics, not lifting

Here is the number that surprises everyone. The grounded IPEx dig cost is
**~4151 J per kg** of regolith excavated (`dig_energy_per_kg()` in `ipex_specs.py`:
the published 18.5 N·m arm excavation load [SCHULER24 Table 7] at the 25 RPM drum rate
gives ~48.4 W of dig power; divided by the 42 kg/hr demonstrated dig rate
[SCHULER24] that is 4151 J/kg. The drum rate is the chain's one `[ASSUMPTION]`; the
honest band is 0.72–1.0× of that figure, `dig_energy_bounds_j_per_kg()`).

Now compare that to gravity. Lifting one kilogram 0.30 m into the drum against lunar
gravity costs `m·g·h` = 1 × 1.62 × 0.30 ≈ **0.49 J**. The dig cost is **~8,600 times
larger** (4151 / 0.486 ≈ 8.5×10³; the exact ratio depends on the lift height you assume,
but the order does not move). Equivalently: 4151 J/kg is the energy to hoist that
kilogram **~2.5 km** straight up at lunar g (4151 / 1.62 ≈ 2562 m).

The lesson: **excavation energy is dominated by cutting mechanics — shearing cohesive,
interlocked, abrasive soil — not by raising material against gravity.** This is why the
mission planner treats dig energy (mass × 4151 J/kg) as the dominant, order-independent
cost of any plan, and adds gravity lift as a separate exact term (`lift_e = mass · g ·
Δh` in `lode/mission_planner.py`, `plan_trips`) that only matters over real elevation
changes. It is also why low gravity does NOT make digging ~6× cheaper — gravity barely
shows up in the dig term at all.

Driving, by contrast, IS gravity-dominated: steady rolling resistance scales with weight
(~`m·g`), so the Earth-testbed Table-3 drive figure (**~40 W**, → **~135 J/m** at
0.30 m/s) badly overestimates lunar flat driving; the physical lunar estimate is
**~4.4 W** flat (`lunar_drive_power_w()` in `ipex_specs.py`, with `[CALIB]`/
`[ASSUMPTION]`-tagged efficiency and rolling-resistance inputs).

For scale, the whole battery is **4.79 MJ (1332 Wh**; 12S × 3.7 V × 30 Ah,
`battery_energy_j()`), and sintering — fusing regolith into a hard surface — has a
thermodynamic **floor** of 0.92 MJ/kg, ~**220× the dig cost** per kg, which is the
sourced physical reason `SINTER_ENABLED = False` for the IPEx baseline (`constants.py`).

**Where this lives in the code**
- `stewie/specs/bodies.py` — per-body g, density, cohesion, friction, repose, Bekker
  moduli, `bekker_regime` (the microgravity invalidity flag), `params_for_body()`.
- `stewie/specs/constants.py` — the lunar Bekker baseline (k_c 1400 / k_phi 820000 /
  n 1.0), cohesion/friction, slip coefficients `[UNKNOWN]`, the counter-rotating-drum
  design-thesis note, `CG_HEIGHT_M`, sinter constants + gate.
- `stewie/specs/ipex_specs.py` — dig 4151 J/kg (and its honest 0.72–1.0× band), drive
  135 J/m, battery 4.79 MJ, `lunar_drive_power_w()`, slope envelope, drum capacities.
- `lode/mission_planner.py` — dig-dominated planning, exact `m·g·Δh` lift term,
  mass-based cut/fill balance, per-body gravity via `body_gravity()`.
- `stewie/physics/terramechanics.py` and `stewie/physics/slip.py` — the load-bearing
  Bekker solve and the slip-sinkage ladder (referenced from the constants).

---

## 5. Light and shadow — the polar sun as sensor, hazard, and resource map

### Regolith is not a matte screen (BRDF basics)

A BRDF (bidirectional reflectance distribution function) describes how a surface
redistributes incoming light as a function of incidence and viewing angles. The simplest
model, Lambert, scatters equally in all directions — and lunar regolith is decidedly
non-Lambertian. The render track therefore ships a sourced **Hapke IMSA /
Lommel–Seeliger** photometric model instead of Lambert (see `docs/spec_coverage.md` §8
and `docs/render_fidelity_spec.md` §9): single scattering weighted by μ₀/(μ₀+μ), a
two-term phase function, and the **opposition effect** (the surge in brightness when the
Sun is directly behind the camera). Practical consequences for perception: lunar scenes
have hard shadow edges, strong brightness variation with viewing geometry, and washed-out
contrast when looking down-sun — none of which a Lambert renderer would show you.

### Horizon clipping: "lit" is a property of the terrain, not the sky

A naive illumination test says: sun elevation > 0 → everything is lit. At a polar site
that is badly wrong — a crater floor can sit in shadow for years while the Sun is
technically "up." The real test, implemented in `dart/illumination.py
horizon_clip()`: a pixel is illuminated **iff nothing along the up-sun ray rises above
its line of sight at the Sun's elevation**. Concretely, a sun-ward cell of height
`h_s` at horizontal distance `d` blocks a pixel of height `h_p` when
`h_s − h_p > d · tan(el)`.

At the polar grazing elevation of **7°**, `tan(7°) ≈ 0.123`, so **one metre of relief
throws an ~8 m shadow** (the module docstring's headline). This is why polar shadows are
long and **information-rich**: every rock, rut, and berm writes its height into the
image as a measurable shadow, and a shadow's edge moves as the Sun spirals — the demo's
per-face shadow attribution and lit/unlit failure A/B exploit exactly this. Grazing light
turns shadow into a navigation signal (relief pops at high contrast) and into a hazard
(whole work areas go dark for weeks).

Two honesty notes carried by the module itself: (1) it computes a **single-tile,
single-epoch geometric horizon** — a true PSR/illumination product (PGDA Product 69)
bakes in multi-year ephemerides, libration, and far horizons tens of km away that one
tile cannot see; treat this as a geometry-accurate shadow stand-in, not a validated
illumination product. (2) Cells with no data are conservatively NOT claimed illuminated.

### Permanently shadowed regions and the ice

Near the poles, with the Sun never more than a few degrees up and the spin axis tilted
only 1.54°, the floors of deep craters like Haworth have local horizons higher than the
Sun ever reaches — they are **permanently shadowed regions (PSRs)**. No direct sunlight,
ever, for ~billions of years. With no atmosphere to carry heat, their floors stabilize
around **~40 K** (the `lunar_psr` sink temperature, −233 °C, in `ipex_specs.py`).

That makes them **cold traps**: any water molecule that wanders in (delivered by comets,
solar-wind chemistry, impacts) sticks and essentially never leaves, because below
**110 K** the sublimation rate of water ice is negligible on geologic timescales.
`T_PSR_K = 110.0` in `constants.py` is exactly this threshold — the H₂O-ice stability
line — and `psr_gate()` in `illumination.py` consumes it as the documented screening
threshold. The gate itself is honest about what it is: a **geometric necessary
condition** (shadowed at this sun epoch), not a thermal model; it even refuses
non-cryogenic thresholds with a `ValueError`. The expected prize, from `constants.py`:
up to **5.6 ± 2.9 %** water ice by mass (LCROSS-derived, `[UNKNOWN]` envelope).

So the same geometry that starves a PSR of light and power preserves the very resource
(water → drinking water, oxygen, propellant) that IPEx-class excavators exist to mine.
Power on the rim, ice on the floor, and a slope/shadow gauntlet between them — that is
the south-polar mission in one sentence.

**Where this lives in the code**
- `dart/illumination.py` — `horizon_clip()` (the ray-march, the `h_s − h_p > d·tan(el)`
  blocking criterion, the 7°→~8 m shadow statement, the Product-69 honesty caveat,
  nodata conservatism) and `psr_gate()` (T_PSR_K = 110 K consumption, necessary-condition
  honesty, cryogenic-threshold validation).
- `stewie/specs/constants.py` — `SUN_ELEVATION_DEG_POLAR = 7.0`, `T_PSR_K = 110.0`,
  `W_ICE_MAX = 0.056`.
- `stewie/specs/ipex_specs.py` — `ENV_SINK_TEMP_C["lunar_psr"] = −233 °C` (~40 K).
- `docs/spec_coverage.md` §8 and `docs/render_fidelity_spec.md` §9 — the
  Hapke/Lommel–Seeliger BRDF in the render track.
- `docs/map_reference.md` — the work-area shadow/PSR rasters in the cockpit (computed
  server-side from the heightmap at the SPICE sun).

---

## 6. Time — two months, real ephemerides, and why approximations fail at the pole

### Synodic vs sidereal

The Moon has two month lengths, and the code uses both (`solar.py`):

- **Sidereal month — 27.321661 days**: one revolution of the Moon relative to the fixed
  stars. The Moon's orientation in inertial space repeats with this period, so the
  **sub-solar latitude** (the ±1.54° seasonal nod) oscillates at the sidereal period.
- **Synodic month — 29.530589 days**: one revolution relative to the **Sun**. While the
  Moon completes a sidereal orbit, the Earth–Moon system has moved ~1/13 of the way
  around the Sun, so the Moon needs ~2.2 extra days to face the Sun the same way again.
  This is the **lunar day** — the period of the sub-solar **longitude** sweep, and the
  708.7 h the planner budgets.

### The real wheel: SPICE

The accurate way to know where the Sun is from a lunar site at a given UTC time is NASA's
**SPICE** system (NAIF): planetary ephemerides plus body orientation models, queried
through SpiceyPy. The repo's solar authority (`sun_az_el_spice()` in `solar.py`) loads
five generic kernels — `de440s.bsp` (planetary ephemeris), `moon_pa_de440_200625.bpc` +
`moon_de440_250416.tf` (the MOON_ME body-fixed frame), `naif0012.tls` (leap seconds),
`pck00011.tpc` (planetary constants) — from `$STEWIE_SPICE_KERNELS` (default
`/mnt/projects/datasets/spice_kernels`; kernels live outside the repo). It asks for the
Sun's position from the Moon center in MOON_ME with light-time + stellar aberration
(`"LT+S"`), then converts to the site's local east-north-up frame on the 1737.4 km
sphere. Mission time 0 anchors to `MISSION_EPOCH_UTC = "2026-11-15T00:00:00"` (tagged
`[ASSUMPTION]` — a notional demo epoch, settable). The kernel sources and the WebGeocalc
manual cross-check oracle are indexed in `docs/map_reference.md`.

### The fallback, and its measured price

When SPICE or its kernels are unavailable, `solar.py` falls back to a **mean-motion**
model: sub-solar longitude advances uniformly (360° per synodic month), sub-solar
latitude is a pure 1.54° sinusoid, no orbital eccentricity, no equation of time, no
perturbations, arbitrary phase at mission start. The module docstring discloses all of
this up front, and `sun_az_el_dispatch()` prefers SPICE whenever `spice_available()` is
true.

Crucially, the repo does not just *assert* the fallback is worse — it **measures** the
gap. `crosscheck_meanmotion()` sweeps a synodic month comparing both backends, and the
dated artifact `stewie/eval/validation/solar_crosscheck_2026-06-10.json` records the
result at the Haworth site (−87.45°, 24 epochs, epoch 2026-11-15):

- **max |Δ elevation| = 5.605°**
- **max |Δ azimuth| = 175.216°**

Why that is fatal at a pole, specifically: the entire polar solar game is played inside
an elevation band of **0–7°** (Section 1). A **5.6° elevation error** is most of the
band — the fallback can put the Sun above the horizon when it is really below it, i.e.
**mis-state polar day vs night outright**, flipping every shadow mask, PSR screen, solar
power window, and thermal case downstream. (The huge azimuth delta is the same phase
error seen through polar geometry, where azimuth swings fast at near-zero elevation.) At
mid-latitudes the identical model error would be a mild pointing inaccuracy; at −87.45°
it changes whether the world is lit. That asymmetry — small ephemeris errors becoming
qualitative day/night errors near the poles — is why the SPICE backend is the default
("the correct wheel; NASA has already built it") and the mean-motion model survives only
as a disclosed, accuracy-reported fallback.

**Where this lives in the code**
- `stewie/specs/solar.py` — both month constants, the mean-motion model + its disclosed
  approximations, the SPICE backend (`_KERNELS`, `$STEWIE_SPICE_KERNELS`,
  `MISSION_EPOCH_UTC`, LT+S, MOON_ME), `sun_az_el_dispatch()`, `crosscheck_meanmotion()`.
- `stewie/eval/validation/solar_crosscheck_2026-06-10.json` — the dated artifact with the
  measured 5.605° / 175.216° fallback deltas at −87.45°.
- `lode/mission_planner.py` — `BODY_TIMESCALE` (the synodic day as operating timescale).
- `docs/map_reference.md` — NAIF kernel sources and the WebGeocalc cross-check oracle.

---

*Primer written 2026-06-10. Every number above was verified against the files cited in
its section; honesty tags (`[FIXED]`/`[CALIB]`/`[ASSUMPTION]`/`[UNKNOWN]`/`[ANALOG]`)
are reproduced from the source files, not assigned here. If you change a constant, this
primer is downstream of you — update the section that cites it.*
