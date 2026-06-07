#!/usr/bin/env python3
"""Split the dense end-to-end demo into two larger slide figures (real pipeline):
  end_to_end_perception.png : real frame | stereo disparity (7% valid) | shadow mask (90%)
  end_to_end_map.png        : Haworth DEM crop | posture lift+stability | lander framing vs yaw
"""
import os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from solnav.bridge import dustgym_io
from solnav.perception import stereo_depth, masking
from solnav.geometry import dem, fov
from solnav.posture import kinematics as kin
from solnav.ipex.specs import IPEX

FOSS = "/mnt/projects/foss_ipex"
SENSORS = FOSS + "/roversim/godot_sidecar/out/cam/crater_boulders/000/sensors.json"
DEM_DIR = FOSS + "/dustgym/samples/lunar_dem/haworth_10km_5m"
OUT = os.path.join(os.path.dirname(__file__), "out")


def main():
    frame = dustgym_io.read_sensors(SENSORS)
    L = dustgym_io.load_camera_image(SENSORS, "front_left")
    R = dustgym_io.load_camera_image(SENSORS, "front_right")
    fx = frame.camera("front_left").fx
    disp = stereo_depth.compute_disparity(L, R)
    vf = stereo_depth.valid_fraction(disp)
    sh = masking.detect_shadow_mask(L)

    # --- A: perception trio ---
    figA, ax = plt.subplots(1, 3, figsize=(15, 5))
    ax[0].imshow(stereo_depth.to_gray(L), cmap="gray"); ax[0].set_title("Real front-left (low-Sun lunar)"); ax[0].axis("off")
    im = ax[1].imshow(np.where(disp > 0, disp, np.nan), cmap="magma")
    ax[1].set_title(f"Stereo disparity: {vf*100:.0f}% valid"); ax[1].axis("off"); figA.colorbar(im, ax=ax[1], fraction=0.046)
    ax[2].imshow(masking.overlay(stereo_depth.to_gray(L), sh)); ax[2].set_title(f"Shadow mask: {sh.mean()*100:.0f}%"); ax[2].axis("off")
    figA.suptitle("Perception on a REAL frame: naive stereo starves on low-Sun, low-texture lunar imagery", fontsize=13)
    figA.tight_layout(rect=[0, 0, 1, 0.95]); figA.savefig(os.path.join(OUT, "end_to_end_perception.png"), dpi=140); plt.close(figA)

    # --- B: map / posture / visibility trio ---
    H, posting, _ = dem.load_dem(DEM_DIR)
    patch, _, n = dem.crop_meters(H, posting, 100.0)
    names = ["TRANSIT", "COBRA", "MEERKAT", "IRON_CROSS"]
    lifts = [kin.posture(nm).chassis_lift_m for nm in names]
    margins = [kin.stability_margin_m(kin.posture(nm), 15, 15) for nm in names]
    hfov = fov.hfov_deg_from_intrinsics(frame.camera("front_left").width, fx)
    cams = {"front": (0., hfov), "left": (90., hfov), "right": (-90., hfov), "rear": (180., hfov)}
    yaws = list(range(0, 360, 15))
    sweep = fov.yaw_sweep(5.0, 2.5, cams, IPEX.apriltag_size_m, fx, yaws)
    framed = [len(sweep[y]["cameras_framing"]) for y in yaws]

    figB, ax = plt.subplots(1, 3, figsize=(15, 5))
    ax[0].imshow(patch, cmap="gist_earth"); ax[0].set_title(f"Real Haworth DEM, 100x100 m ({n}x{n})"); ax[0].axis("off")
    x = np.arange(len(names))
    ax[1].bar(x - 0.2, lifts, 0.4, label="chassis lift (m)", color="#4878a8")
    ax[1].bar(x + 0.2, margins, 0.4, label="stability margin (m)", color="#c0762f")
    ax[1].set_xticks(x); ax[1].set_xticklabels(names, rotation=20, fontsize=9); ax[1].legend(fontsize=8)
    ax[1].set_title("Posture: lift + stability")
    ax[2].bar([str(y) for y in yaws], framed, color="#5aa469")
    ax[2].set_title(f"Cameras framing lander vs yaw (HFOV {hfov:.0f} deg)"); ax[2].tick_params(axis="x", labelsize=6, rotation=90)
    figB.suptitle("Map tier + active geometry: real Haworth DEM, posture lift/stability, lander visibility", fontsize=13)
    figB.tight_layout(rect=[0, 0, 1, 0.95]); figB.savefig(os.path.join(OUT, "end_to_end_map.png"), dpi=140); plt.close(figB)
    print("wrote end_to_end_perception.png + end_to_end_map.png")


if __name__ == "__main__":
    main()
