#!/usr/bin/env python3
"""End-to-end solnav pipeline demo on a REAL frame + the REAL Haworth south-pole DEM.

Honest demonstration (every output labeled REAL / [SPEC] / [CONFIRM] / DIFFERENT-SOURCE):
  1. Read a real LAC-twin/dustgym frame (front stereo + sensors.json).
  2. Real stereo depth (cv2 SGBM) -> the honestly-sparse valid fraction on low-sun lunar imagery.
  3. Masking: self-supervised shadow mask; feature filtering keeps textured surface.
  4. Cast-shadow height H = L*tan(e) using the frame's real Sun elevation.
  5. Real Haworth DEM (south pole) 100x100 m crop as the global map; scan-to-DEM registration
     mechanism demonstrated by recovering a known shift on the real DEM.
  6. Posture kinematics: camera height/pitch/parallax + stability across TRANSIT/COBRA/MEERKAT/IRON_CROSS.
  7. Spin relative to the lander: which cameras frame + can detect the lander AprilTag vs rover yaw.
Produces demo/out/end_to_end.png and a printed honesty ledger.
"""
import os

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from solnav.bridge import dustgym_io
from solnav.geometry import dem, fov, shadow
from solnav.ipex.specs import IPEX
from solnav.perception import masking, stereo_depth
from solnav.posture import kinematics as kin

FOSS = "/mnt/projects/foss_ipex"
SENSORS = FOSS + "/roversim/godot_sidecar/out/cam/crater_boulders/000/sensors.json"
DEM_DIR = FOSS + "/dustgym/samples/lunar_dem/haworth_10km_5m"
OUT = os.path.join(os.path.dirname(__file__), "out", "end_to_end.png")
ledger = []


def log(tag, msg):
    ledger.append((tag, msg))
    print(f"[{tag:14s}] {msg}")


def main():
    fig, ax = plt.subplots(2, 3, figsize=(15, 9))

    # --- 1. real frame ---
    frame = dustgym_io.read_sensors(SENSORS)
    L = dustgym_io.load_camera_image(SENSORS, "front_left")
    R = dustgym_io.load_camera_image(SENSORS, "front_right")
    fxL = frame.camera("front_left").fx
    log("REAL", f"frame: {len(frame.cameras)} cameras, front_left {L.shape}, fx={fxL:.1f}, "
                 f"baseline={frame.stereo_baseline_m:.3f} m, sun elev={frame.sun_elevation_deg} az={frame.sun_azimuth_deg}")
    ax[0, 0].imshow(stereo_depth.to_gray(L), cmap="gray"); ax[0, 0].set_title("1. Real front-left (low-sun lunar)"); ax[0, 0].axis("off")

    # --- 2. stereo depth (REAL) ---
    disp = stereo_depth.compute_disparity(L, R)
    vf = stereo_depth.valid_fraction(disp)
    depth = stereo_depth.disparity_to_depth(disp, fxL, frame.stereo_baseline_m)
    log("REAL", f"stereo SGBM: valid disparity {vf*100:.1f}% (low-texture/low-sun starves naive stereo -> motivates the cues), "
                 f"depth median {np.nanmedian(depth):.2f} m")
    im = ax[0, 1].imshow(np.where(disp > 0, disp, np.nan), cmap="magma")
    ax[0, 1].set_title(f"2. Real stereo disparity ({vf*100:.0f}% valid)"); ax[0, 1].axis("off"); fig.colorbar(im, ax=ax[0, 1], fraction=0.04)

    # --- 3. masking (REAL) ---
    sh = masking.detect_shadow_mask(L)
    log("REAL", f"shadow mask: {sh.mean()*100:.1f}% of pixels in shadow (the regions where stereo also fails)")
    ax[0, 2].imshow(masking.overlay(stereo_depth.to_gray(L), sh)); ax[0, 2].set_title(f"3. Shadow mask ({sh.mean()*100:.0f}%)"); ax[0, 2].axis("off")

    # --- 4. cast-shadow height (REAL geometry, real sun elevation) ---
    e = frame.sun_elevation_deg or 5.0
    for H in (0.2, 0.5, 1.0):
        log("REAL", f"shadow geometry: a {H:.1f} m rock at sun elev {e:.0f} deg casts a {shadow.shadow_length_from_height(H, e):.2f} m shadow (H=L*tan e)")

    # --- 5. DEM (REAL Haworth south pole), 100x100 m crop + registration mechanism ---
    H, posting, meta = dem.load_dem(DEM_DIR)
    patch, (r0, c0), n = dem.crop_meters(H, posting, 100.0)
    log("REAL", f"Haworth DEM {H.shape} @ {posting:.1f} m posting; 100 m crop = {n}x{n} cells, relief {patch.max()-patch.min():.1f} m")
    # registration mechanism: shift a sub-patch by a known offset on the REAL DEM, recover it
    sub = patch[3:-3, 3:-3]
    true_dr, true_dc = 2, -1
    shifted_dem = np.roll(np.roll(patch, true_dr, 0), true_dc, 1)
    dr, dc, rmse = dem.register_to_dem(sub, shifted_dem, search_radius_cells=5)
    log("REAL", f"scan-to-DEM registration recovered shift ({dr},{dc}) vs truth ({true_dr},{true_dc}), RMSE {rmse:.3f} m")
    log("DIFF-SOURCE", "the render scene is a 5 m procedural patch, NOT georeferenced to Haworth; full "
                       "render-to-DEM registration needs a Godot run on the Haworth tile (not done here)")
    hs = np.gradient(patch.astype(float))[0]
    ax[1, 0].imshow(patch, cmap="gist_earth"); ax[1, 0].set_title(f"5. Real Haworth DEM, 100x100 m ({n}x{n})"); ax[1, 0].axis("off")

    # --- 6. posture kinematics (angles [SPEC], dims [CONFIRM]) ---
    names = ["TRANSIT", "COBRA", "MEERKAT", "IRON_CROSS"]
    lifts, margins = [], []
    for nm in names:
        ps = kin.posture(nm)
        h, p = kin.camera_height_pitch(0.30, 0.0, ps)   # base cam ~0.30 m [CONFIRM]
        mg = kin.stability_margin_m(ps, fill_front_kg=15.0, fill_rear_kg=15.0)
        feas = kin.is_feasible(ps, 15.0, 15.0)
        lifts.append(ps.chassis_lift_m); margins.append(mg)
        log("SPEC+CONFIRM", f"{nm:10s} arms=({ps.arm_front_deg:.0f},{ps.arm_rear_deg:.0f}) "
                            f"lift={ps.chassis_lift_m:.2f} m pitch={ps.pitch_deg:.1f} deg "
                            f"stab_margin={mg:.2f} m feasible={feas} nominal={ps.within_nominal}")
    pg = kin.parallax_baseline_m(kin.posture("TRANSIT"), kin.posture("MEERKAT"))
    log("SPEC+CONFIRM", f"MEERKAT vs TRANSIT vertical parallax gain = {pg:.2f} m (widens landmark triangulation baseline)")
    x = np.arange(len(names))
    ax[1, 1].bar(x - 0.2, lifts, 0.4, label="chassis lift (m)", color="#4878a8")
    ax[1, 1].bar(x + 0.2, margins, 0.4, label="stability margin (m)", color="#c0762f")
    ax[1, 1].set_xticks(x); ax[1, 1].set_xticklabels(names, rotation=20, fontsize=8)
    ax[1, 1].axhline(0.05, ls="--", c="r", lw=0.8); ax[1, 1].legend(fontsize=7)
    ax[1, 1].set_title("6. Posture: lift + stability ([CONFIRM] dims)")

    # --- 7. spin relative to lander: AprilTag visibility vs yaw (REAL geometry) ---
    rel = frame.lander_pos_m - frame.rover_pos_m
    lander_bearing = (np.degrees(np.arctan2(rel[1], rel[0]))) % 360.0
    lander_dist = float(np.linalg.norm(rel[:2])) or 5.0
    hfov = fov.hfov_deg_from_intrinsics(frame.camera("front_left").width, fxL)
    cams = {"front": (0.0, hfov), "left": (90.0, hfov), "right": (-90.0, hfov), "rear": (180.0, hfov)}
    yaws = list(range(0, 360, 15))
    sweep = fov.yaw_sweep(lander_bearing, lander_dist, cams, IPEX.apriltag_size_m, fxL, yaws)
    det = fov.tag_detectable(IPEX.apriltag_size_m, lander_dist, fxL)
    n_usable = sum(1 for y in yaws if sweep[y]["usable"])
    log("REAL", f"lander bearing {lander_bearing:.0f} deg, dist {lander_dist:.1f} m, cam HFOV {hfov:.0f} deg, "
                 f"tag detectable={det}; lander framed by >=1 cam at {n_usable}/{len(yaws)} headings")
    framed = [len(sweep[y]["cameras_framing"]) for y in yaws]
    ax[1, 2].bar([str(y) for y in yaws], framed, color="#5aa469")
    ax[1, 2].set_title(f"7. Cameras framing lander vs rover yaw (HFOV {hfov:.0f} deg)")
    ax[1, 2].set_xlabel("rover yaw (deg)"); ax[1, 2].set_ylabel("# cameras"); ax[1, 2].tick_params(axis='x', labelsize=6, rotation=90)

    fig.suptitle("solnav end-to-end on a REAL frame + REAL Haworth DEM (see honesty ledger)", fontsize=13)
    fig.tight_layout(rect=[0, 0, 1, 0.97])
    fig.savefig(OUT, dpi=150)
    print(f"\nfigure -> {OUT}")
    print("\n=== HONESTY LEDGER ===")
    from collections import Counter
    c = Counter(t for t, _ in ledger)
    print("tag counts:", dict(c))


if __name__ == "__main__":
    main()
