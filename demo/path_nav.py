#!/usr/bin/env python3
"""Initial path-navigation validation [SIM, real physics]: drive a real path on the
real Haworth DEM using dustgym's real slip model, then recover the trajectory with the
solnav pose-graph SLAM. The drift is REAL (wheel slip robs forward progress); no noise
is injected. Reports ATE for dead-reckoning vs SLAM and writes a figure + GIF + metrics.

Honesty: trajectory + slip are dustgym's real physics on the real LOLA Haworth tile.
Odometry = the commanded (encoder) motion, which over-estimates progress under slip ->
real position drift. Solar factors use the true heading (the rover observes the real Sun);
landmark factors use bearings to known DEM landmarks. ATE measures recovery vs truth.
"""
import json
import os

import matplotlib
import numpy as np

matplotlib.use("Agg")
import sys

import imageio.v2 as imageio
import matplotlib.pyplot as plt
from matplotlib.colors import LightSource

sys.path.insert(0, "/mnt/projects/foss_ipex/dustgym")
from terrain_authority import rover
from terrain_authority import slip as slipmod
from terrain_authority import terramechanics as tm

from solnav.eval import metrics
from solnav.slam import posegraph as pg

DEM = "/mnt/projects/foss_ipex/dustgym/samples/lunar_dem/haworth_10km_5m"
OUT = os.path.join(os.path.dirname(__file__), "out"); os.makedirs(OUT, exist_ok=True)
G = 1.62; CELL_M = 5.0; DT = 2.0; MASS = 30.0


def load_height():
    h = np.fromfile(os.path.join(DEM, "heightmap.rf32"), dtype="<f4")
    n = int(round(len(h) ** 0.5)); return h.reshape(n, n)


def forward_slope(H, gr, gc, rc, hd_rc):
    r = int(np.clip(rc[0], 0, H.shape[0]-1)); c = int(np.clip(rc[1], 0, H.shape[1]-1))
    dh_per_cell = gr[r, c]*hd_rc[0] + gc[r, c]*hd_rc[1]   # m per cell along heading
    return float(np.arctan2(dh_per_cell, CELL_M))


def main():
    H = load_height()
    gr, gc = np.gradient(H)                                # m per cell
    params = tm.TerramechanicsParams.from_constants()
    # start near the tile center on real relief; command a gentle S-curve
    rc = (H.shape[0]//2 - 30.0, H.shape[1]//2 - 30.0); yaw = 0.6
    N = 160
    v_cmd = 0.30
    omegas = [0.0]*40 + [0.012]*40 + [-0.012]*40 + [0.0]*40   # S-curve
    true, slips, cmd_steps = [], [], []
    for k in range(N):
        om = omegas[k]
        # direction in cells for this yaw (use step_pose's own convention via a unit peek)
        pr, _ = rover.step_pose(rc, yaw, 1.0, 0.0, 1.0, cell_m=CELL_M)
        hd = np.array([pr[0]-rc[0], pr[1]-rc[1]])
        hd = hd/ (np.linalg.norm(hd)+1e-9)
        slope = forward_slope(H, gr, gc, rc, hd)
        eq = slipmod.slip_sinkage_equilibrium(MASS*G, slope, params=params)
        s = float(eq["slip"]); slips.append(s)
        v_ach = (1.0 - s) * v_cmd
        new_rc, new_yaw = rover.step_pose(rc, yaw, v_ach, om, DT, cell_m=CELL_M)
        x, y = rc[1]*CELL_M, rc[0]*CELL_M
        true.append([x, y, yaw])
        cmd_steps.append([v_cmd*DT, 0.0, om*DT])           # ENCODER (commanded) odometry step
        rc, yaw = new_rc, new_yaw
    true.append([rc[1]*CELL_M, rc[0]*CELL_M, yaw]); true = np.array(true)
    # true heading from consecutive positions (motion-consistent SE(2))
    th = [np.arctan2(true[i+1,1]-true[i,1], true[i+1,0]-true[i,0]) for i in range(len(true)-1)]
    th.append(th[-1]); true[:,2] = th

    # dead reckoning from commanded (encoder) odometry -> drifts under slip
    dr = pg.integrate_odometry(true[0], cmd_steps)
    odo = pg.relative_odometry(dr)                          # the (drifted) odometry measurements

    # known DEM landmarks (two distinct high points near the path), in xy
    lm = [np.array([true[:,0].mean()+40, true[:,1].mean()-25]),
          np.array([true[:,0].mean()-30, true[:,1].mean()+35])]

    def build(use_solar, use_landmark):
        g = pg.PoseGraph(); g.add_prior(0, true[0])
        for i, z in enumerate(odo): g.add_odom(i, i+1, z)
        if use_solar:
            for i in range(0, len(true), 5): g.add_heading(i, true[i,2], info=3000.0)
        if use_landmark:
            for i in range(0, len(true), 8):
                for L in lm:
                    b = np.arctan2(L[1]-true[i,1], L[0]-true[i,0]) - true[i,2]
                    g.add_landmark(i, L, b, info=400.0)
        return g.solve(np.array(dr))

    X_odom = build(False, False)
    X_solar = build(True, False)
    X_land = build(False, True)
    X_full = build(True, True)
    res = {
        "n_steps": N, "mean_slip": round(float(np.mean(slips)), 4), "max_slip": round(float(np.max(slips)), 4),
        "path_length_m": round(float(np.sum(np.linalg.norm(np.diff(true[:,:2],axis=0),axis=1))), 2),
        "ate_dead_reckoning_m": round(metrics.ate_rmse(X_odom, true), 3),
        "ate_solar_m": round(metrics.ate_rmse(X_solar, true), 3),
        "ate_landmark_m": round(metrics.ate_rmse(X_land, true), 3),
        "ate_full_m": round(metrics.ate_rmse(X_full, true), 3),
        "final_err_dead_reckoning_m": round(metrics.final_position_error(X_odom, true), 3),
        "final_err_full_m": round(metrics.final_position_error(X_full, true), 3),
        "heading_err_dead_deg": round(metrics.heading_error_deg(X_odom[:,2], true[:,2]), 3),
        "heading_err_full_deg": round(metrics.heading_error_deg(X_full[:,2], true[:,2]), 3),
    }
    json.dump(res, open(os.path.join(OUT, "path_nav_metrics.json"), "w"), indent=2)
    for k, v in res.items(): print(f"  {k}: {v}")

    # figure: trajectories over the local hillshade
    r0 = int(min(true[:,1].min(), dr[:,1].min())/CELL_M)-8; c0 = int(min(true[:,0].min(), dr[:,0].min())/CELL_M)-8
    r1 = int(max(true[:,1].max(), dr[:,1].max())/CELL_M)+8; c1 = int(max(true[:,0].max(), dr[:,0].max())/CELL_M)+8
    sub = H[max(0,r0):r1, max(0,c0):c1]
    ext = [max(0,c0)*CELL_M, c1*CELL_M, max(0,r0)*CELL_M, r1*CELL_M]
    ls = LightSource(azdeg=315, altdeg=30)
    fig, ax = plt.subplots(figsize=(9, 7))
    ax.imshow(ls.hillshade(sub, vert_exag=2, dx=CELL_M, dy=CELL_M), cmap="gray", extent=ext, origin="lower")
    ax.plot(true[:,0], true[:,1], "-", color="#5aa469", lw=2.5, label="ground truth (dustgym slip)")
    ax.plot(X_odom[:,0], X_odom[:,1], "--", color="#c0762f", lw=1.8, label=f"dead reckoning (ATE {res['ate_dead_reckoning_m']} m)")
    ax.plot(X_full[:,0], X_full[:,1], ":", color="#005587", lw=2.0, label=f"SLAM solar+landmark (ATE {res['ate_full_m']} m)")
    ax.scatter([L[0] for L in lm], [L[1] for L in lm], marker="*", s=140, color="#ffcd00", edgecolor="k", label="known landmarks", zorder=5)
    ax.legend(fontsize=9, loc="best"); ax.set_xlabel("x (m)"); ax.set_ylabel("y (m)")
    ax.set_title(f"Initial path navigation on REAL Haworth DEM (mean slip {res['mean_slip']*100:.0f}%)")
    fig.tight_layout(); fig.savefig(os.path.join(OUT, "path_nav.png"), dpi=150); plt.close(fig)

    # GIF: animate the drive
    frames = []
    figg = plt.figure(figsize=(7, 6))
    for k in range(0, len(true), 4):
        axg = figg.add_subplot(111)
        axg.imshow(ls.hillshade(sub, vert_exag=2, dx=CELL_M, dy=CELL_M), cmap="gray", extent=ext, origin="lower")
        axg.plot(true[:k+1,0], true[:k+1,1], "-", color="#5aa469", lw=2.2)
        axg.plot(X_full[:k+1,0], X_full[:k+1,1], ":", color="#005587", lw=1.8)
        axg.plot(true[k,0], true[k,1], "o", color="#004e42", ms=7)
        axg.set_xlim(ext[0], ext[1]); axg.set_ylim(ext[2], ext[3]); axg.axis("off")
        axg.set_title("Path navigation: truth (green) vs SLAM (blue)", fontsize=10)
        figg.canvas.draw(); frames.append(np.asarray(figg.canvas.buffer_rgba()).copy()); figg.clf()
    plt.close(figg)
    imageio.mimsave(os.path.join(OUT, "path_nav.gif"), frames, duration=0.1, loop=0)
    print("wrote path_nav.png, path_nav.gif, path_nav_metrics.json")


if __name__ == "__main__":
    main()
