# EZ-RASSOR on real Katwijk -- FULL-TRAVERSE articulation-parallax absolute-fix (2026-07-02)

**RENDERED-SENSOR SIMULATION, ARGUS G2 tier. Real AHN 0.5 m terrain macro-shape + real Katwijk Part4 RTK trajectory + real 8-cam EZ-RASSOR/IPEx rig geometry; ALL sub-0.5 m camera texture is PROCEDURAL Godot infill, NOT real imagery. Geometric-cue result on real Katwijk geometry; NOT a real-image match; does NOT close the real-LocCam VO gap.**

The EZ-RASSOR/IPEx 8-camera rig was rendered at the 56 REAL Part4 RTK poses (of 58 moving stations
selected) spanning the WHOLE ~76 m Part4 traverse. Because the traverse (ENU bbox ~40 x 63 m,
diagonal ~74 m) is longer than one 40 m scene and the sidecar far-plane is hardcoded 100 m, the trajectory
was TILED into **2 overlapping 50 m local scenes** (bbox-segmented, midpoint-centred so
every assigned station clears the rover-patch margin by >= 2 m; each rover-to-farthest-terrain
distance <= ~52 m, safely inside the far-plane). Each tile is a real AHN 0.5 m DTM crop, ENU-pinned at the
first RTK fix, built by the milestone-1 ingest (`KatwijkAhnDem` -> `dem_to_base` -> `save_scene`).

At each pose the rig rendered a two-posture chassis-lift A/B pair (TRANSIT lift 0.0 -> MEERKAT lift 0.1743 m),
and `articulation_bridge.localize_on_render_pair` recovered an ABSOLUTE ground-position fix truth-free
(block-match vertical parallax -> range = fx*dh/dv -> DEM-raycast landmark -> RANSAC trilateration). Each
tile's scene-local fix was translated back to the single first-fix ENU frame (add the tile's `world_min`),
so all 56 fixes and the RTK truth live in ONE consistent frame before scoring.

- **Per-station absolute fix error (vs rendered/snapped RTK):** 0.359-17.715 m (median 4.103 m, p90 8.832 m).
- **Full-traverse absolute-fix ATE (RMS, no alignment):** 5.785 m -- absolute-position accuracy of the parallax cue over the whole traverse.
- **Full-traverse aligned ATE (Umeyama):** 5.646 m -- trajectory-shape consistency after a best rigid alignment.
- **RTK->grid snap:** median 0.201 m, max 0.329 m (truth discretization from the sidecar's integer rover-rc, <= half a cell diagonal ~0.354 m).
- **Tiling:** 2 tiles; resolved 56/58 (0 render-fail, 2 unsolvable-skipped, not fabricated).

**vs the single 40 m scene** (`ezrassor_katwijk_articulation_parallax_2026-07-02.json`, 26 stations idx 35..61):
absolute-fix ATE 4.778 m / aligned 4.631 m. The full traverse extends coverage to idx 0..61 (the earlier
~half of the path the single scene never saw) and scores the reassembled multi-tile trajectory end to end.

**What the number means:** how accurately the standstill articulation-parallax GEOMETRIC cue localizes the
rover's absolute position over the FULL Katwijk traverse, from the real rig, rendered-sim. It is NOT a
real-image match and does NOT close the real-LocCam VO gap (all sub-0.5 m texture is procedural infill).

Artifact: `ezrassor_katwijk_fulltraverse_articulation_parallax_2026-07-02.json` (tiling plan, per-station
errors, commands, reused-vs-written). Estimator + ingest reused verbatim; only the full-track selection, the
tiling plan, the per-tile scene parametrization, and the ONE-frame assembly + scoring were written here.
