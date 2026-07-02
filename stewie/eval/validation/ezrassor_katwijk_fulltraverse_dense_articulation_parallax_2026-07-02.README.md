# EZ-RASSOR on real Katwijk -- FULL-TRAVERSE DENSE-TILING articulation-parallax absolute-fix (2026-07-02)

**RENDERED-SENSOR SIMULATION, ARGUS G2 tier. Real AHN 0.5 m terrain macro-shape + real Katwijk Part4 RTK trajectory + real 8-cam EZ-RASSOR/IPEx rig geometry; ALL sub-0.5 m camera texture is PROCEDURAL Godot infill, NOT real imagery. Geometric-cue result on real Katwijk geometry; NOT a real-image match; does NOT close the real-LocCam VO gap.**

The EZ-RASSOR/IPEx 8-camera rig was rendered at the 57 REAL Part4 RTK poses (of 58 moving stations
selected) spanning the WHOLE ~76 m Part4 traverse. Because the traverse (ENU bbox ~40 x 63 m,
diagonal ~74 m) is longer than one 40 m scene and the sidecar far-plane is hardcoded 100 m, the trajectory
was TILED into **4 overlapping 30 m local scenes** (bbox-segmented, midpoint-centred so
every assigned station clears the rover-patch margin by >= 2 m; each rover-to-farthest-terrain
distance <= ~52 m, safely inside the far-plane). Each tile is a real AHN 0.5 m DTM crop, ENU-pinned at the
first RTK fix, built by the milestone-1 ingest (`KatwijkAhnDem` -> `dem_to_base` -> `save_scene`).

At each pose the rig rendered a two-posture chassis-lift A/B pair (TRANSIT lift 0.0 -> MEERKAT lift 0.1743 m),
and `articulation_bridge.localize_on_render_pair` recovered an ABSOLUTE ground-position fix truth-free
(block-match vertical parallax -> range = fx*dh/dv -> DEM-raycast landmark -> RANSAC trilateration). Each
tile's scene-local fix was translated back to the single first-fix ENU frame (add the tile's `world_min`),
so all 57 fixes and the RTK truth live in ONE consistent frame before scoring.

- **Per-station absolute fix error (vs rendered/snapped RTK):** 0.377-11.753 m (median 2.964 m, p90 8.021 m).
- **Full-traverse absolute-fix ATE (RMS, no alignment):** 4.724 m -- absolute-position accuracy of the parallax cue over the whole traverse.
- **Full-traverse aligned ATE (Umeyama):** 4.685 m -- trajectory-shape consistency after a best rigid alignment.
- **RTK->grid snap:** median 0.192 m, max 0.349 m (truth discretization from the sidecar's integer rover-rc, <= half a cell diagonal ~0.354 m).
- **Tiling:** 4 tiles; resolved 57/58 (0 render-fail, 1 unsolvable-skipped, not fabricated).

## Robustness stress test: dense (30 m, 4 tiles) vs the 2-tile 50 m baseline

This run is a like-for-like **robustness stress test** of the committed 2-tile full-traverse result
(`ezrassor_katwijk_fulltraverse_articulation_parallax_2026-07-02.json`, commit 9913eb5, absolute-fix ATE
**5.785 m** / aligned **5.646 m**, 56/58 resolved, 2 tiles @ 50 m). The estimator, render pipeline, station
selection, and 0.3 m thinning are **identical**; ONLY the tile extent changed (50 m -> 30 m,
4 tiles), so each station sits more centred inside a tighter scene.

| | baseline (2 tiles, 50 m) | dense (4 tiles, 30 m) | delta |
|---|---|---|---|
| absolute-fix ATE (RMS) | 5.785 m | 4.724 m | -1.061 m |
| aligned ATE (Umeyama) | 5.646 m | 4.685 m | -0.961 m |
| resolved / selected | 56 / 58 | 57 / 58 | |
| unsolvable-skipped | 2 | 1 | |
| per-station mean / median / p90 | 4.815 / 4.103 / 8.832 m | 3.822 / 2.964 / 8.021 m | |

**VERDICT: IMPROVES (dense absolute-fix ATE 4.724 m vs baseline 5.785 m; delta -1.061 m, tighter)**

The absolute-fix ATE is the truth-free absolute-position accuracy of the standstill articulation-parallax
GEOMETRIC cue. The parallax range solve (`range = fx*dh/dv` -> DEM-raycast landmark -> RANSAC trilateration)
depends on the rig geometry and the local DEM shape around each station, NOT on where the tile's edges fall,
so the ATE should be largely invariant to tiling granularity if the pipeline is sound.

**vs the single 40 m scene** (`ezrassor_katwijk_articulation_parallax_2026-07-02.json`, 26 stations idx 35..61):
absolute-fix ATE 4.778 m / aligned 4.631 m -- covered only the later ~half; both full-traverse runs extend
coverage to idx 0..61 and score the reassembled multi-tile trajectory end to end.

**What the number means:** how accurately the standstill articulation-parallax GEOMETRIC cue localizes the
rover's absolute position over the FULL Katwijk traverse, from the real rig, rendered-sim. It is NOT a
real-image match and does NOT close the real-LocCam VO gap (all sub-0.5 m texture is procedural infill).

Artifact: `ezrassor_katwijk_fulltraverse_articulation_parallax_2026-07-02.json` (tiling plan, per-station
errors, commands, reused-vs-written). Estimator + ingest reused verbatim; only the full-track selection, the
tiling plan, the per-tile scene parametrization, and the ONE-frame assembly + scoring were written here.
