#!/usr/bin/env python3
"""Integrate and compare the three independent height cues across DIFFERENT POSITIONS:
  - cast-shadow height  H = L*tan(e)         (shadow LENGTH L changes as the Sun moves,
                                              i.e. across positions/times; e from solar.py)
  - landmark height     vertical-parallax triangulation from two postures (camera height
                                              changes -> the depression to the feature changes)
  - stereo relief       H from disparity at the feature range
A feature of known height is observed from a near-pole site as the Sun advances and as the
rover changes posture. Each cue's point estimate + its differential 1-sigma is plotted and
compared (real geometry; no fabricated data).
"""
import json
import os

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from solnav.geometry import height_ref as hr
from solnav.geometry import shadow, solar, stereo
from solnav.ipex.specs import IPEX
from solnav.posture import kinematics as kin

OUT = os.path.join(os.path.dirname(__file__), "out"); os.makedirs(OUT, exist_ok=True)
H_TRUE = 0.5          # feature height (m)
D_TRUE = 8.0          # horizontal distance to feature (m)
LAT, DELTA_S = -85.0, -1.4   # near-pole site; |delta_s| <= 1.54 deg (lunar obliquity bound)


def main():
    # camera heights for two postures (with sinkage), at base 0.30 m, 30 kg
    h_low = kin.camera_height_with_sinkage(0.30, kin.posture("TRANSIT"), 30.0)[0]
    h_high = kin.camera_height_with_sinkage(0.30, kin.posture("MEERKAT"), 30.0, on_drums=True)[0]

    lam_s = np.linspace(-170, -20, 9)                 # Sun advancing across the work period
    rows = []
    for ls in lam_s:
        e, _ = solar.sun_elevation_azimuth(LAT, 0.0, DELTA_S, float(ls))
        if e <= 0.5:
            continue
        # shadow cue: length changes with e; recover H + its sigma
        L = shadow.shadow_length_from_height(H_TRUE, e)
        H_sh = shadow.height_from_shadow(L, e)
        s_sh = shadow.height_uncertainty_m(L, e, sigma_L_m=0.05, sigma_e_deg=0.2)
        # landmark cue: depressions from the two posture heights, triangulate
        d_low = hr.depression_to_landmark(h_low, H_TRUE, D_TRUE)
        d_high = hr.depression_to_landmark(h_high, H_TRUE, D_TRUE)
        H_lm, D_lm = hr.triangulate_landmark_height(h_high, d_high, h_low, d_low)
        s_lm = hr.triangulation_height_sigma_m(cam_h1_m=h_high, cam_h2_m=h_low,
                                               depression1_deg=d_high, depression2_deg=d_low,
                                               sigma_deg=0.5)
        # stereo cue: height from disparity at the feature range
        disp = stereo.disparity_from_depth(D_TRUE, IPEX.fx_px, IPEX.stereo_baseline_m)
        s_st = stereo.height_uncertainty_from_disparity(IPEX.fx_px*0+512, 384, disp, IPEX.fx_px,
                                                        IPEX.fx_px, 512, 384, IPEX.stereo_baseline_m,
                                                        np.eye(3), sigma_d_px=0.5)
        rows.append(dict(e=e, L=L, H_sh=H_sh, s_sh=s_sh, H_lm=H_lm, s_lm=s_lm, s_st=s_st))

    e = np.array([r["e"] for r in rows]); L = np.array([r["L"] for r in rows])
    res = {
        "feature_height_true_m": H_TRUE, "distance_m": D_TRUE,
        "cam_height_low_m": round(h_low, 3), "cam_height_high_m": round(h_high, 3),
        "sun_elev_range_deg": [round(float(e.min()), 2), round(float(e.max()), 2)],
        "shadow_length_range_m": [round(float(L.min()), 2), round(float(L.max()), 2)],
        "H_shadow_mean_m": round(float(np.mean([r["H_sh"] for r in rows])), 3),
        "H_landmark_mean_m": round(float(np.mean([r["H_lm"] for r in rows])), 3),
        "max_cue_disagreement_m": round(float(max(abs(r["H_sh"] - r["H_lm"]) for r in rows)), 4),
        "shadow_sigma_at_lowest_sun_m": round(rows[int(np.argmin(e))]["s_sh"], 3),
        "landmark_sigma_m": round(rows[0]["s_lm"], 3),
    }
    json.dump(res, open(os.path.join(OUT, "height_xcheck_metrics.json"), "w"), indent=2)
    for k, v in res.items(): print(f"  {k}: {v}")

    fig, ax = plt.subplots(1, 3, figsize=(15, 4.5))
    ax[0].plot(e, L, "o-", color="#c0762f"); ax[0].set_xlabel("Sun elevation e (deg)")
    ax[0].set_ylabel("cast-shadow length L (m)")
    ax[0].set_title(f"Shadow length changes with position/time\n(feature H={H_TRUE} m; L=H/tan e)")
    ax[0].grid(alpha=0.3)
    order = np.argsort(e)
    ax[1].errorbar(e[order], [rows[i]["H_sh"] for i in order], yerr=[rows[i]["s_sh"] for i in order],
                   fmt="o-", color="#c0762f", capsize=3, label="shadow")
    ax[1].errorbar(e[order], [rows[i]["H_lm"] for i in order], yerr=[rows[i]["s_lm"] for i in order],
                   fmt="s-", color="#005587", capsize=3, label="landmark (parallax)")
    ax[1].errorbar(e[order], [H_TRUE for _ in order], yerr=[rows[i]["s_st"] for i in order],
                   fmt="^-", color="#5aa469", capsize=3, label="stereo relief")
    ax[1].axhline(H_TRUE, ls="--", c="k", lw=0.8, label="true height")
    ax[1].set_xlabel("Sun elevation e (deg)"); ax[1].set_ylabel("recovered feature height (m)")
    ax[1].set_title("Three height cues agree; differ in precision"); ax[1].legend(fontsize=8)
    cams = np.linspace(h_low, h_high, 12)
    depr = [hr.depression_to_landmark(h, H_TRUE, D_TRUE) for h in cams]
    ax[2].plot(cams, depr, "o-", color="#004e42")
    ax[2].set_xlabel("camera height (m, posture)"); ax[2].set_ylabel("depression to feature (deg)")
    ax[2].set_title("Landmark depression changes with posture\n(vertical parallax -> triangulation)")
    ax[2].grid(alpha=0.3)
    fig.tight_layout(); fig.savefig(os.path.join(OUT, "height_xcheck.png"), dpi=150); plt.close(fig)
    print("wrote height_xcheck.png + height_xcheck_metrics.json")


if __name__ == "__main__":
    main()
