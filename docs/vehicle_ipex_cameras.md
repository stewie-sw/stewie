# IPEx Camera & Dust Mitigation Subsystem — extracted spec (SCHULER24)

Source: Schuler et al., *ISRU Pilot Excavator (IPEx) Technology Readiness Level 5 Design Overview*,
ASCEND 2024 (NTRS 20240008162), Section V "Camera and Dust Mitigation Subsystem", pp. 24-31, Figs
27-38. Extracted 2026-06-17 from the full PDF including the figures (the geometry lives in the images,
not the body text). This is the authoritative camera/light/dust spec for STEWIE's sensor model; it
supersedes the assumed values where they differ. Nothing here is fabricated; values without a figure
number are read off the labelled CAD callouts.

## 1. Camera complement (Fig. 27, Fig. 28)

- **8 cameras total**; **minimum 4 to operate**. The 8-set is FULLY REDUNDANT against dust occlusion /
  camera failure (§V.C). The minimum operating set is: **one stereo pair + one side-facing mono + one
  between-the-bucket-drums mono**.
- **Functional roles** (§V intro):
  - **Stereo pair** -> visual odometry + near-field hazard identification (depth via disparity).
  - **Side-facing mono** -> primarily **tracks the lander** (the bearing beacon for relocalization).
  - **Between-drum mono** -> views the terrain AND the excavator itself (self-inspection / drum view).
  - Optional **"Selfie Cam"** config facing the IPEx radiator (Fig. 27 margin note; for regolith-loading
    monitoring of the radiator cover, §VI.B).
- IPEx is a bidirectional skid-steer (bucket drums at both ends), so the redundant 8-set is consistent
  with front + rear stereo pairs plus side + drum monos (STEWIE's current layout; see §5).

## 2. Sensor & lens (§V.A.1-3)

| Parameter | Value | Note |
|---|---|---|
| Sensor (flight) | **Sony IMX547**, **5 MP**, **2.74 µm** pixel, ~**2472 x 2064** | S-mount; switched FROM IMX264 (3.45 µm, C-mount) |
| Lens mount | **S-mount**, fixed aperture (no moving parts; vents in vacuum) | C-mount rejected (outgassing, venting, complexity) |
| Aperture | **f/4** | chosen for high dynamic range in harsh low-sun contrast |
| Focal length | **6 mm AND 4.4 mm** both under evaluation | 6 mm -> HFOV 58.9°; 4.4 mm -> HFOV ~75.3° (IMX547) |
| Colour | monochromatic (perception path) | |

Derived FOV (pure unit conversion, fx = f / pixel_pitch, HFOV = 2·atan(W/2/fx)):
- **6 mm**: fx = 6e-3 / 2.74e-6 = 2189.8 px -> HFOV = 2·atan(2472/2/2189.8) = **58.9°**.
- **4.4 mm**: fx = 1605.8 px -> HFOV = 2·atan(2472/2/1605.8) = **75.3°**.

## 3. Stereo baseline (Fig. 28, Fig. 30, Fig. 32) — THE number we have wrong

- **Initial design: 0.165 m** (16.5 cm), the two cameras split across opposite "shoulders" with the
  excavation arm structure in between (Fig. 28 left).
- **Final design: 0.05 m** (5 cm), the stereo pair **combined into a single housed unit** (Fig. 28 right,
  Fig. 32). The split design lost calibration under structural load/thermal expansion (Fig. 29 shows the
  blown-out disparity), so it was collapsed to one rigid module.
- Trade (Fig. 30 depth-error curves): the **0.05 m** baseline has **higher depth error at distance** but
  a **closer minimum-depth capability** and far better calibration stability; the 0.165 m baseline
  reaches further. IPEx chose near-field accuracy (navigate the immediate environment) over reach.

## 4. Lighting (§V.A.4) — modelled in STEWIE (was rendered OFF by default; now ON, 6 units)

The lunar pole is high-contrast, low-sun, no-atmosphere; the cameras must image SHADOWED regions, so
IPEx carries its own LED illumination. STEWIE DOES model this (`camera_rig.LIGHT_UNITS` +
`build_work_lights()` + the `--work-lights` flag + the sensors.json `lights` block); the prior
committed egress was simply rendered with the lights OFF, which is why its shadows read as black. As of
2026-06-17 the rig models the FULL six units and the crater_boulders egress is rendered with lights ON
(verified: forward camera mean brightness 12.3 -> 45.0, deep-shadow fraction 85% -> 74%).

- **6 LED units total** on IPEx.
- **Per light: 3,000 lumens max**, focused by a **total-internal-reflection (TIR) optic**.
- **Beam angle: ~42° FWHM** (full width at half maximum).
- **Each LED unit = 3 LEDs** on a circuit board.
- **Mono cameras**: **1 LED unit co-located** with the camera (so 4 mono cams -> 4 LED units).
- **Stereo pair**: **NO LEDs on the stereo module**; a **separate stereo LED unit on the OPPOSITE
  shoulder of the chassis**, consisting of **2 LED units**. Reason (real finding): lights co-located with
  the EDS glass back-reflected through the same glass and washed the image, so the stereo lights were
  moved to the far shoulder; the monos got an internal separator between light path and camera. Glare is
  a real, modellable artifact.
- Count check: 4 (mono, 1 each) + 2 (stereo LED unit) = **6 LED units**.

## 5. Dust mitigation (§V.B), calibration & thermal (§V.C)

- **EDS (electrodynamic dust shield) lens covers** on each camera: transparent AC shields that clear dust.
- **EDS cover on an HDRM** (Frangibolt): jettisoned if the EDS can no longer clear the glass (lens ejects
  ~15.2 cm in 1 g, Fig. 38). Last-resort to recover visibility.
- **Fully redundant camera set** for unknown dust loading.
- Calibration params affected by thermal gradients: **distortion coefficients + camera matrix** (focal
  lengths, optical centre, skew). Op temp 0-50 °C (tested in 5° steps + ambient vac, Table 10). Above
  75 °C: grey hot-spot + edge blurring; under vacuum: an image "bulging" distortion shift (Fig. 35).
  Calibration target at 22.9 cm.

## 6. Mount geometry (Fig. 28)

- Stereo module on the **central mast/arm above the chassis**, looking along the drive axis.
- Side monos at the **lateral shoulders**.
- Stereo LED unit on the **opposite shoulder** from the stereo module.
- The PDF gives baselines (0.165 / 0.05 m) as the only explicit on-figure distances; camera mount HEIGHT
  above ground is not a labelled number (read qualitatively: top of chassis, above the wheel/drum
  centreline). STEWIE's mast height stays an [ASSUMPTION] until a dimensioned drawing is sourced.

## 7. STEWIE current vs IPEx real (grounded in `stewie/godot/camera_rig.gd` + `sidecar.gd`)

| Parameter | STEWIE active render | IPEx (SCHULER24) | Verdict |
|---|---|---|---|
| Sensor profile | CALIB: 1024x768, FOV_X 73.99° (EZ-RASSOR URDF) is the DEFAULT/committed egress; FLIGHT profile (IMX547 2472x2064, 58.88°) exists but only behind the `--flight-cam` path (`sidecar.gd:521`) | IMX547, 5 MP, 2.74 µm, 6 mm OR 4.4 mm @ f/4 | flight const captured but NOT the default render |
| HFOV | 73.99° active (≈ the 4.4 mm config); 58.88° flight const (6 mm) | 58.9° (6 mm) or 75.3° (4.4 mm) | active ≈ 4.4 mm; pick the real candidate per profile |
| **Stereo baseline** | **0.070 m** modelled (the frozen-G2-fixture value; `INITIAL_BASELINE_M=0.165` ref) | **0.05 m final** (0.165 m initial) | real is 0.05; 0.05 reverted (broke the frozen byte-identity fixture) — re-freeze pending |
| Camera LED lights | `LIGHT_UNITS` + `build_work_lights()` + `--work-lights`; now **6 units** (4 mono + 2 stereo bank), 3000 lm, 42° FWHM; rendered ON | 6 LED units, 3000 lm, 42° FWHM TIR, mono-colocated, stereo-on-opposite-shoulder | MODELLED; energy lumens->Godot mapping is [CALIB] |
| EDS / dust occlusion | not modelled | EDS shields + HDRM jettison + redundant set | MISSING (relevant to dust-degradation perception) |
| Aperture / exposure | not modelled | f/4, HDR for low-sun | MISSING (no exposure/HDR model) |
| Camera roles/count | 8: front/rear stereo + L/R side mono + front/back drum mono | 8 total / 4 min: stereo + side(lander) + drum; redundant | layout MATCHES; side mono = lander tracker is already the intended role |

## 8. Recommended changes (by value / effort)

1. **Baseline: real final is 0.05 m; the twin still MODELS 0.07 m — REVERTED 2026-06-17.** I first
   propagated 0.05 through the rig + spec layer, but the G2 `runtime_sensors.json` fixture is a FROZEN
   byte-identity reference (the `/admin/gates/validate` `byte_identical_to_frozen` invariant +
   `eval/test_bridge`), so editing it to 0.05 broke CI and the frozen-artifact invariant. Reverted the
   modeled baseline to 0.07 everywhere (`camera_rig.gd`, the `stewie_ipex_v1` profile, `system_profile`,
   the fixture, `ipex_specs` G2 band). `INITIAL_BASELINE_M=0.165` is kept as a reference const. Cleanly
   adopting the real 0.05 m requires RE-FREEZING the G2 fixture + re-validating the gates — a coordinated
   gate-affecting decision, pending Aaron's go. (The served `pointcloud.json` demo asset still
   reads 0.05 from the lit re-render; regenerate when the baseline is settled.)
2. **DONE 2026-06-17 — LED model rendered ON, full 6 units**: added the 2 drum-cam LEDs so the rig models
   4 mono (1 each) + 2 stereo bank = 6, all at 3000 lm / 42° FWHM; crater_boulders egress now rendered
   with `--work-lights` (forward camera mean 12.3 -> 45.0). Remaining: the lumens->Godot energy mapping is
   still [CALIB] `light_energy=8.0` (a physical-light-units upgrade would also re-scale the sun; deferred).
3. **DONE 2026-06-17 — FOV profiles**: `FLIGHT_FOV_X_DEG=58.88` (6 mm) + `LENS_4_4MM_FOV_X_DEG=75.31`
   (4.4 mm) are both defined; the EZ-RASSOR CALIB 73.99° remains the default render profile (the flight
   profile fires behind `--flight-cam`).
4. **EDS dust-occlusion model** (progressive lens dusting + EDS clear cycles + HDRM jettison) for
   dust-degraded perception — the path-dependent-failure story. IN PROGRESS (Python perception model).
5. **f/4 exposure / HDR** sensor model for the low-sun high-contrast response. HIGHER effort; optional.

Items 1-3 are applied (the rendered sensor is now faithful on baseline + lights + FOV); 4 is in progress;
5 is a fidelity extension.
