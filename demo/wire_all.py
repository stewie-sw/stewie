#!/usr/bin/env python3
"""Wire everything together and minimize the distance offset (ATE).

Drives a real path on the real Haworth DEM (real dustgym slip), then progressively adds
cues to the unified pose graph -- odometry -> +solar heading -> +1 landmark -> +multi-landmark
(multipoint bearings via the 8-camera rig) -> dense observations -- and reports how far the
distance offset (ATE) can be driven down. The 8-camera rig reports how many cameras frame
each landmark per station. Real geometry + real slip; no fabricated data.
"""
import os, json, sys
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, "/mnt/projects/foss_ipex/dustgym")
from terrain_authority import slip as slipmod, rover
from terrain_authority import terramechanics as tm

from solnav.slam import posegraph as pg
from solnav.eval import metrics
from solnav.perception import camera_rig as cr

DEM = "/mnt/projects/foss_ipex/dustgym/samples/lunar_dem/haworth_10km_5m"
OUT = os.path.join(os.path.dirname(__file__), "out"); os.makedirs(OUT, exist_ok=True)
G, CELL_M, DT, MASS = 1.62, 5.0, 2.0, 30.0


def drive():
    h = np.fromfile(os.path.join(DEM, "heightmap.rf32"), dtype="<f4"); n = int(round(len(h)**0.5))
    H = h.reshape(n, n); gr, gc = np.gradient(H)
    params = tm.TerramechanicsParams.from_constants()
    rc = (n//2 - 30.0, n//2 - 30.0); yaw = 0.6
    omegas = [0.0]*40 + [0.012]*40 + [-0.012]*40 + [0.0]*40
    true, cmd = [], []
    for k in range(160):
        pr, _ = rover.step_pose(rc, yaw, 1.0, 0.0, 1.0, cell_m=CELL_M)
        hd = np.array([pr[0]-rc[0], pr[1]-rc[1]]); hd = hd/(np.linalg.norm(hd)+1e-9)
        r = int(np.clip(rc[0],0,n-1)); c = int(np.clip(rc[1],0,n-1))
        slope = np.arctan2(gr[r,c]*hd[0] + gc[r,c]*hd[1], CELL_M)
        s = float(slipmod.slip_sinkage_equilibrium(MASS*G, slope, params=params)["slip"])
        new_rc, new_yaw = rover.step_pose(rc, yaw, (1-s)*0.30, omegas[k], DT, cell_m=CELL_M)
        true.append([rc[1]*CELL_M, rc[0]*CELL_M, yaw]); cmd.append([0.30*DT, 0.0, omegas[k]*DT])
        rc, yaw = new_rc, new_yaw
    true.append([rc[1]*CELL_M, rc[0]*CELL_M, yaw]); true = np.array(true)
    th = [np.arctan2(true[i+1,1]-true[i,1], true[i+1,0]-true[i,0]) for i in range(len(true)-1)]; th.append(th[-1])
    true[:,2] = th
    return true, cmd


def main():
    true, cmd = drive()
    dr = pg.integrate_odometry(true[0], cmd)
    odo = pg.relative_odometry(dr)
    cx, cy = true[:,0].mean(), true[:,1].mean()
    # six distributed landmarks (good multipoint geometry)
    K = 6
    lm = [np.array([cx + 45*np.cos(t), cy + 45*np.sin(t)]) for t in np.linspace(0, 2*np.pi, K, endpoint=False)]
    rig = cr.CameraRig()

    def build(solar, n_lm, every):
        g = pg.PoseGraph(); g.add_prior(0, true[0])
        for i, z in enumerate(odo): g.add_odom(i, i+1, z)
        if solar:
            for i in range(0, len(true), 5): g.add_heading(i, true[i,2], info=3000.0)
        for i in range(0, len(true), every):
            for L in lm[:n_lm]:
                b = np.arctan2(L[1]-true[i,1], L[0]-true[i,0]) - true[i,2]
                g.add_landmark(i, L, b, info=400.0)
        return g.solve(np.array(dr))

    stages = [
        ("odometry only", build(False, 0, 999)),
        ("+ solar heading", build(True, 0, 999)),
        ("+ 1 landmark", build(True, 1, 8)),
        ("+ 6 landmarks (multipoint)", build(True, 6, 8)),
        ("+ 6 lm, dense (every pose)", build(True, 6, 1)),
    ]
    ates = [(name, round(metrics.ate_rmse(X, true), 3)) for name, X in stages]
    # 8-camera coverage of landmarks per station (rig wired in)
    seen_counts = []
    for i in range(0, len(true), 8):
        for L in lm:
            wb = np.degrees(np.arctan2(L[1]-true[i,1], L[0]-true[i,0]))
            d = np.linalg.norm(L - true[i,:2])
            seen_counts.append(len(rig.cameras_seeing(wb, np.degrees(true[i,2]), d)))
    res = {
        "ate_by_stage_m": dict(ates),
        "min_ate_m": min(a for _, a in ates),
        "reduction_x": round(ates[0][1] / max(ates[-1][1], 1e-6), 1),
        "mean_cameras_seeing_a_landmark": round(float(np.mean(seen_counts)), 2),
    }
    json.dump(res, open(os.path.join(OUT, "wire_all_metrics.json"), "w"), indent=2)
    for k, v in res.items(): print(f"  {k}: {v}")

    fig, ax = plt.subplots(1, 2, figsize=(13, 5))
    names = [n for n, _ in ates]; vals = [a for _, a in ates]
    ax[0].barh(range(len(names)), vals, color="#005587"); ax[0].set_yticks(range(len(names)))
    ax[0].set_yticklabels(names, fontsize=9); ax[0].invert_yaxis()
    ax[0].set_xlabel("ATE distance offset (m)"); ax[0].set_title("Minimizing distance offset by wiring in cues")
    for i, v in enumerate(vals): ax[0].text(v, i, f" {v} m", va="center", fontsize=9)
    best = stages[-1][1]
    ax[1].plot(true[:,0], true[:,1], "-", color="#5aa469", lw=2.5, label="ground truth")
    ax[1].plot(dr[:,0], dr[:,1], "--", color="#c0762f", lw=1.5, label=f"dead reckoning ({ates[0][1]} m)")
    ax[1].plot(best[:,0], best[:,1], ":", color="#005587", lw=2, label=f"full SLAM ({ates[-1][1]} m)")
    ax[1].scatter([L[0] for L in lm], [L[1] for L in lm], marker="*", s=120, color="#ffcd00", edgecolor="k", label="landmarks")
    ax[1].legend(fontsize=8); ax[1].set_aspect("equal"); ax[1].set_title("Best wiring vs truth")
    fig.tight_layout(); fig.savefig(os.path.join(OUT, "wire_all.png"), dpi=150); plt.close(fig)
    print("wrote wire_all.png + wire_all_metrics.json")


if __name__ == "__main__":
    main()
