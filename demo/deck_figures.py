#!/usr/bin/env python3
"""Static figures for the slide decks (GIFs can't embed in PDF):
  postures_montage.png : the 8 named positions as wireframes, annotated lift/pitch.
  sinkage_fault.png    : Bekker sinkage vs load (wheel vs drum) + camera-fault degradation.
All driven by the real solnav models.
"""
import os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from solnav.posture import wireframe, kinematics as kin
from solnav.terramechanics import sinkage as sk
from solnav.geometry import fov

OUT = os.path.join(os.path.dirname(__file__), "out")
os.makedirs(OUT, exist_ok=True)


def postures_montage(path):
    names = list(kin.POSTURES.keys())          # all 8
    fig = plt.figure(figsize=(15, 7))
    for i, nm in enumerate(names):
        ax = fig.add_subplot(2, 4, i + 1, projection="3d")
        polys, meta = wireframe.rover_skeleton(*kin.POSTURES[nm])
        for p in polys:
            ax.plot(p[:, 0], p[:, 1], p[:, 2], color="#004e42", lw=1.1)
        ax.set_xlim(-0.8, 0.8); ax.set_ylim(-0.8, 0.8); ax.set_zlim(0, 1.0)
        ax.set_box_aspect((1, 1, 0.7)); ax.view_init(elev=16, azim=-62)
        ax.set_title(f"{nm}\nlift {meta['lift_m']:.2f} m, pitch {meta['pitch_deg']:.0f}°", fontsize=9)
        ax.set_xticks([]); ax.set_yticks([]); ax.set_zticks([])
    fig.suptitle("Eight-position posture library (kinematic wireframe; dims [CONFIRM] from RASSOR GLB envelope)", fontsize=12)
    fig.tight_layout(rect=[0, 0, 1, 0.94]); fig.savefig(path, dpi=140); plt.close(fig)


def sinkage_fault(path):
    fig, ax = plt.subplots(1, 2, figsize=(13, 4.5))
    loads = np.linspace(5, 40, 40)
    ax[0].plot(loads, [sk.wheel_sinkage(L) * 1000 for L in loads], label="wheel (b=0.18 m)", color="#4878a8")
    ax[0].plot(loads, [sk.drum_sinkage(L) * 1000 for L in loads], label="on drum (narrow contact)", color="#c0762f")
    ax[0].set_xlabel("normal load per contact (N)"); ax[0].set_ylabel("Bekker sinkage (mm)")
    ax[0].set_title("Load-bearing sinkage, measured lunar moduli\n(NTRS 20220010732); slip-sinkage out of scope")
    ax[0].legend(fontsize=9); ax[0].grid(alpha=0.3)
    hfov = fov.hfov_deg_from_intrinsics(1024, 679.57)
    full = {"front": (0.0, hfov), "left": (90.0, hfov), "right": (-90.0, hfov), "rear": (180.0, hfov)}
    configs = [("4 cams", full), ("3 (no rear)", {k: v for k, v in full.items() if k != "rear"}),
               ("2 (front+left)", {"front": (0.0, hfov), "left": (90.0, hfov)}),
               ("1 (front)", {"front": (0.0, hfov)})]
    yaws = list(range(0, 360, 10))
    cov = [100 * sum(1 for y in yaws if fov.yaw_sweep(5.0, 2.5, c, 0.15, 679.57, yaws)[y]["usable"]) / len(yaws)
           for _, c in configs]
    ax[1].bar([c[0] for c in configs], cov, color="#5aa469")
    ax[1].set_ylabel("lander-framing coverage (%)"); ax[1].set_ylim(0, 100)
    ax[1].set_title("Fault degradation: camera dropout\n(lander visibility across rover yaw)")
    for i, v in enumerate(cov):
        ax[1].text(i, v + 2, f"{v:.0f}%", ha="center", fontsize=9)
    fig.tight_layout(); fig.savefig(path, dpi=140); plt.close(fig)


if __name__ == "__main__":
    postures_montage(os.path.join(OUT, "postures_montage.png"))
    sinkage_fault(os.path.join(OUT, "sinkage_fault.png"))
    print("wrote postures_montage.png (8 postures) + sinkage_fault.png")
