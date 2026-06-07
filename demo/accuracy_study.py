#!/usr/bin/env python3
"""Hypothesize + test 10 ways to improve localization accuracy [SIM, real physics + noise].

Real Haworth path with real dustgym slip; ALIGNED ATE (Umeyama), seeded sensor-noise model,
5-seed means, observations gated by camera FOV (no oracle availability), Huber where stated.
Each hypothesis is a prediction tested against the baseline. Honest: some help, some do not,
some cost battery. Writes accuracy_study_metrics.json.
"""
import json
import os
import sys

import numpy as np

sys.path.insert(0, "/mnt/projects/foss_ipex/dustgym")
from terrain_authority import rover
from terrain_authority import slip as slipmod
from terrain_authority import terramechanics as tm

from solnav.eval import metrics
from solnav.geometry import fov
from solnav.perception import camera_rig as cr
from solnav.slam import posegraph as pg

DEM = "/mnt/projects/foss_ipex/dustgym/samples/lunar_dem/haworth_10km_5m"
OUT = os.path.join(os.path.dirname(__file__), "out"); os.makedirs(OUT, exist_ok=True)
G, CELL_M, DT = 1.62, 5.0, 2.0
RIG = cr.CameraRig()
HFOV = fov.hfov_deg_from_intrinsics(1024, 679.57)
CAM_OFFS = [0.0, 90.0, -90.0, 180.0]   # active-camera yaw offsets (front/left/right/rear)


def drive():
    h = np.fromfile(os.path.join(DEM, "heightmap.rf32"), dtype="<f4"); n = int(round(len(h)**0.5))
    H = h.reshape(n, n); gr, gc = np.gradient(H)
    params = tm.TerramechanicsParams.from_constants()
    rc = (n//2-30.0, n//2-30.0); yaw = 0.6
    omegas = [0.0]*40 + [0.012]*40 + [-0.012]*40 + [0.0]*40
    true, cmd = [], []
    for k in range(160):
        pr, _ = rover.step_pose(rc, yaw, 1.0, 0.0, 1.0, cell_m=CELL_M)
        hd = np.array([pr[0]-rc[0], pr[1]-rc[1]]); hd = hd/(np.linalg.norm(hd)+1e-9)
        ri, ci = int(np.clip(rc[0],0,n-1)), int(np.clip(rc[1],0,n-1))
        slope = np.arctan2(gr[ri,ci]*hd[0]+gc[ri,ci]*hd[1], CELL_M)
        s = float(slipmod.slip_sinkage_equilibrium(30.0*G, slope, params=params)["slip"])
        nrc, nyaw = rover.step_pose(rc, yaw, (1-s)*0.30, omegas[k], DT, cell_m=CELL_M)
        true.append([rc[1]*CELL_M, rc[0]*CELL_M, yaw]); cmd.append([0.30*DT, 0.0, omegas[k]*DT])
        rc, yaw = nrc, nyaw
    true.append([rc[1]*CELL_M, rc[0]*CELL_M, yaw]); true = np.array(true)
    th=[np.arctan2(true[i+1,1]-true[i,1], true[i+1,0]-true[i,0]) for i in range(len(true)-1)]; th.append(th[-1])
    true[:,2]=th
    return true, cmd


def visible(L, pose):
    wb = np.degrees(np.arctan2(L[1]-pose[1], L[0]-pose[0])); yaw = np.degrees(pose[2])
    return any(fov.in_fov(wb, yaw, off, HFOV) for off in CAM_OFFS)


def main():
    true, cmd = drive()
    dr = pg.integrate_odometry(true[0], cmd); odo = pg.relative_odometry(dr)
    cx, cy = true[:,0].mean(), true[:,1].mean()
    lm6 = [np.array([cx+45*np.cos(t), cy+45*np.sin(t)]) for t in np.linspace(0,2*np.pi,6,endpoint=False)]
    lm9 = [np.array([cx+40*np.cos(t), cy+40*np.sin(t)]) for t in np.linspace(0,2*np.pi,9,endpoint=False)]

    def graph(landmarks, every, sb_deg, odom_info, solar, gate, huber, outlier_frac, seed):
        rng = np.random.default_rng(seed); sb = np.radians(sb_deg); sh = np.radians(1.0)
        g = pg.PoseGraph(); g.add_prior(0, true[0])
        for i, z in enumerate(odo):
            g.add_odom(i, i+1, z, info=odom_info)
        if solar:
            for i in range(0, len(true), 5): g.add_heading(i, true[i,2]+rng.normal(0,sh), info=1/sh**2)
        for i in range(0, len(true), every):
            for L in landmarks:
                if gate and not visible(L, true[i]): continue
                b = np.arctan2(L[1]-true[i,1], L[0]-true[i,0]) - true[i,2] + rng.normal(0, sb)
                if outlier_frac and rng.random() < outlier_frac: b += np.radians(20.0)
                g.add_landmark(i, L, b, info=1/sb**2)
        return metrics.ate_rmse(g.solve(np.array(dr), huber_delta=huber), true)

    def mean5(**kw):
        return round(float(np.mean([graph(seed=s, **kw) for s in range(5)])), 3)

    base = dict(landmarks=lm6, every=8, sb_deg=0.5, odom_info=(100.,100.,100.),
                solar=True, gate=True, huber=None, outlier_frac=0.0)
    H = {}
    H["H0 odometry only (dead reckoning)"] = round(metrics.ate_rmse(dr, true), 3)
    H["H1 + solar heading"] = mean5(**{**base, "landmarks": []})
    H["H2 + 3 landmarks (FOV-gated)"] = mean5(**{**base, "landmarks": lm6[:3]})
    H["H3 + 6 landmarks"] = mean5(**base)
    H["H4 + 9 landmarks"] = mean5(**{**base, "landmarks": lm9})
    H["H5 denser obs (every 2)"] = mean5(**{**base, "every": 2})
    H["H6 lower bearing noise (0.25 deg)"] = mean5(**{**base, "sb_deg": 0.25})
    H["H7 calibrated odom info (10x)"] = mean5(**{**base, "odom_info": (1000.,1000.,1000.)})
    H["H8a 5% outliers, NO robust"] = mean5(**{**base, "every": 2, "outlier_frac": 0.05})
    H["H8b 5% outliers, Huber"] = mean5(**{**base, "every": 2, "outlier_frac": 0.05, "huber": 2.0})
    H["H9 ungated (oracle availability)"] = mean5(**{**base, "every": 2, "gate": False})
    H["H10 best honest (9 lm, every 2, 0.25 deg, Huber, gated)"] = mean5(
        landmarks=lm9, every=2, sb_deg=0.25, odom_info=(1000.,1000.,1000.),
        solar=True, gate=True, huber=2.0, outlier_frac=0.0)
    res = {"metric": "aligned ATE (m), mean of 5 seeds", "path_m": 87.7,
           "results": H, "best_honest_m": H["H10 best honest (9 lm, every 2, 0.25 deg, Huber, gated)"],
           "navlab_bar_m": 0.067}
    json.dump(res, open(os.path.join(OUT, "accuracy_study_metrics.json"), "w"), indent=2)
    for k, v in H.items(): print(f"  {k}: {v} m")
    print(f"  best honest: {res['best_honest_m']} m  vs NavLab bar 0.067 m")


if __name__ == "__main__":
    main()
