# EZ-RASSOR on real Katwijk -- articulation-parallax absolute-fix payoff (2026-07-02)

**RENDERED-SENSOR SIMULATION, ARGUS G2 tier. Real terrain macro-shape (AHN 0.5 m DTM) + real Katwijk Part4 RTK trajectory + real 8-cam EZ-RASSOR/IPEx rig geometry; ALL sub-0.5 m camera texture is PROCEDURAL Godot infill, NOT real imagery. This tests the articulation-parallax GEOMETRIC cue on real Katwijk geometry; it is NOT a real-image match and does NOT close the real-LocCam VO gap.**

The EZ-RASSOR/IPEx 8-camera rig was rendered at the 26 REAL Part4 RTK poses (of 26 selected)
that fall inside the `katwijk_part4_station50` scene footprint (real AHN 0.5 m DTM crop, ENU-anchored at
the first RTK fix). At each pose the rig rendered a two-posture chassis-lift A/B pair (TRANSIT lift 0.0
-> MEERKAT lift 0.1743 m), and `articulation_bridge.localize_on_render_pair` recovered an ABSOLUTE
ground-position fix truth-free (block-match vertical parallax -> range = fx*dh/dv -> DEM-raycast landmark
-> RANSAC trilateration). Fixes were scored against the RTK truth (the render places the rover at the RTK
pose snapped to the 0.5 m DEM grid; the estimator's target is that rendered pose).

- **Per-station absolute fix error (vs rendered/snapped RTK):** 0.596-13.541 m (median 2.524 m).
- **Absolute-fix ATE (RMS, no alignment):** 4.778 m -- the headline: absolute-position accuracy of the parallax cue on real Katwijk geometry.
- **Aligned ATE (Umeyama, template's `_align_ate`):** 4.631 m -- trajectory-shape consistency after a best rigid alignment.
- **RTK->grid snap:** median 0.226 m, max 0.313 m (truth discretization from the sidecar's integer rover-rc, <= half a cell diagonal ~0.354 m).

**What the number means:** how accurately the standstill articulation-parallax GEOMETRIC cue localizes
the rover's absolute position on REAL Katwijk terrain shape, from the real rig, rendered-sim. It is NOT a
real-image match and does NOT close the real-LocCam VO gap (all sub-0.5 m texture is procedural infill).

Artifact: `ezrassor_katwijk_articulation_parallax_2026-07-02.json` (per-station errors, commands,
reused-vs-written breakdown). Estimator reused verbatim; only station selection, a world_min
frame-bookkeeping translation, and scoring were written for this run.
