#!/usr/bin/env python3
"""G1.A6 synchronized stereo traverse: one short CONTINUOUS drive on the crater_boulders scene whose
front_left/front_right camera keyframes share ONE monotonic clock + sequence id with the IMU/wheel
proprioception. Not disconnected-scene stitching: every frame comes from the same physics trajectory.

Truth (poses) is written to a SEPARATE truth/ dir, never into the estimator input (cam/ + proprioception).
Records render latency, drops, and duplicate sequence ids. Portable (CLI/env); no hardcoded paths.

  python3 validation/a6_stereo_traverse.py --dustgym-root <dir> --output <dir> --seed 0 --stations 6
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time

import numpy as np

CELL_M, DT, MASS, G, V_CMD = 0.02, 1.0, 30.0, 1.62, 0.30
IMU_HZ, WHEEL_HZ = 100.0, 10.0
CAM_H, BASELINE, LOOKAHEAD = 0.8, 0.07, 1.0       # camera height, stereo baseline, look-ahead (m)


def _render(sidecar, scene, pose, out_png, size="384x288", elev=8, azim=200):
    """One sidecar render at a Godot --pose; returns wall-clock latency or None on failure."""
    t0 = time.time()
    tmp = "a6_tmp_%d.png" % (int(t0 * 1e6) % 1_000_000)
    r = subprocess.run(["./render_layers.sh", "--", "--scene", scene, "--layers", "terrain,clasts",
                        "--sun-elev", str(elev), "--sun-azim", str(azim),
                        "--pose", ",".join(f"{v:.4f}" for v in pose), "--size", size, "--out", tmp],
                       cwd=sidecar, capture_output=True, text=True, timeout=200)
    src = os.path.join(sidecar, "out", tmp)
    if r.returncode != 0 or not os.path.exists(src):
        return None
    os.makedirs(os.path.dirname(out_png), exist_ok=True)
    shutil.move(src, out_png)
    return time.time() - t0


def run(dustgym_root, out_dir, seed, stations):
    sys.path.insert(0, dustgym_root)
    from terrain_authority import proprioception as pp
    from terrain_authority import rover
    from terrain_authority import runtime_packet as rp
    from terrain_authority import slip as slipmod
    from terrain_authority import terramechanics as tm
    sidecar = os.path.join(dustgym_root, "godot_sidecar")
    scene = "../samples/crater_boulders"
    dem = os.path.join(dustgym_root, "samples", "crater_boulders", "heightmap.rf32")
    h = np.fromfile(dem, dtype="<f4"); n = int(round(len(h) ** 0.5)); H = h.reshape(n, n)
    gr, gc = np.gradient(H)
    params = tm.TerramechanicsParams.from_constants()
    cam_dir = os.path.join(out_dir, "cam"); truth_dir = os.path.join(out_dir, "truth")
    os.makedirs(cam_dir, exist_ok=True); os.makedirs(truth_dir, exist_ok=True)

    # short continuous straight traverse near the scene centre (Godot x grows, z fixed ~2.56)
    rc = (n // 2, 50.0); yaw = 0.0          # row=centre, col=50 (x~1.0 m); heading +x
    model = pp.ImuWheelModel(seed=seed)
    frames, imu, wheel, truth, t, drops, seen = [], [], [], [], 0.0, 0, set()
    for k in range(stations):
        pr, _ = rover.step_pose(rc, yaw, 1.0, 0.0, 1.0, cell_m=CELL_M)
        hd = np.array([pr[0] - rc[0], pr[1] - rc[1]]); hd = hd / (np.linalg.norm(hd) + 1e-9)
        ri, ci = int(np.clip(rc[0], 0, n - 1)), int(np.clip(rc[1], 0, n - 1))
        slope = np.arctan2(gr[ri, ci] * hd[0] + gc[ri, ci] * hd[1], CELL_M)
        s = float(slipmod.slip_sinkage_equilibrium(MASS * G, slope, params=params)["slip"])
        v_true = V_CMD * (1.0 - s)
        gx, gz = rc[1] * CELL_M, rc[0] * CELL_M       # Godot ground (x, z)
        truth.append({"seq": k, "t": t, "x": gx, "z": gz, "yaw": yaw, "slip": s,
                      "provenance": "GROUND_TRUTH_EVAL"})
        cam = {}
        for name, lat in (("front_left", +BASELINE / 2), ("front_right", -BASELINE / 2)):
            pose = (gx, CAM_H, gz + lat, gx + LOOKAHEAD, CAM_H - 0.4, gz + lat)
            png = os.path.join(cam_dir, f"frame_{k:03d}", f"{name}.png")
            dtl = _render(sidecar, scene, pose, png)
            if dtl is None:
                drops += 1; continue
            cam[name] = {"path": os.path.relpath(png, out_dir), "render_latency_s": round(dtl, 3)}
        dup = k in seen; seen.add(k)
        # estimator-input frame: identity + timing + image refs ONLY -- NO true pose (I3)
        frames.append({"seq": k, "t": t, "cameras": cam, "duplicate": dup})
        # proprioception on the SAME clock between this station and the next
        for j in range(int(IMU_HZ * DT)):
            imu.append(model.step_imu(t + j / IMU_HZ, 0.0, (0.0, 0.0)))
        for j in range(int(WHEEL_HZ * DT)):       # RAW four-wheel encoders (P0-2), slip hidden (I3)
            wheel.append(model.step_wheel_encoders(t + j / WHEEL_HZ, v_true, 0.0, (s, s, s, s), dt=1.0 / WHEEL_HZ))
        rc, yaw = rover.step_pose(rc, yaw, v_true, 0.0, DT, cell_m=CELL_M); t += DT

    packet = pp.runtime_proprioception_packet(imu, wheel, sequence_id=0, imu_rate_hz=IMU_HZ, wheel_rate_hz=WHEEL_HZ)
    json.dump(packet, open(os.path.join(out_dir, "proprioception.json"), "w"))   # estimator input
    seq = {
        "schema_version": "stereo_traverse/1.0", "clock": "sim_monotonic", "scene": "crater_boulders",
        "camera_calibration": {"baseline_m": BASELINE, "reference_camera": "front_left", "size": "384x288"},
        "n_frames": len(frames), "drops": drops,
        "duplicate_seq": sum(1 for f in frames if f["duplicate"]),
        "distinct_poses": len({(round(p["x"], 4), round(p["z"], 4), round(p["yaw"], 4)) for p in truth}),
        "render_latency_s": {"mean": round(float(np.mean([c["render_latency_s"]
                             for f in frames for c in f["cameras"].values()] or [0])), 3)},
        "frames": frames,
    }
    json.dump(seq, open(os.path.join(out_dir, "sequence.json"), "w"), indent=2)   # estimator input
    # canonical single-clock packet (P0-3): camera + IMU + four-wheel + measured joints (TRANSIT) on one clock
    cam_channel = {"clock": "sim_monotonic", "sequence_id": 0, "reference_camera": "front_left",
                   "baseline_m": BASELINE,
                   "frames": [{"name": nm, "t": f["t"], "path": c["path"]}
                              for f in frames for nm, c in f["cameras"].items()]}
    canonical = rp.canonical_runtime_packet(packet, cam_channel,
                                            joints=rp.joint_channel(0.65, 0.65, t=0.0), sequence_id=0)
    json.dump(canonical, open(os.path.join(out_dir, "canonical_runtime.json"), "w"), indent=2)  # estimator input
    json.dump({"poses": truth, "provenance": "GROUND_TRUTH_EVAL"},
              open(os.path.join(truth_dir, "truth.json"), "w"), indent=2)          # EVAL ONLY (I3)
    return seq


def main(argv=None):
    ap = argparse.ArgumentParser(description="G1.A6 synchronized stereo traverse (portable).")
    ap.add_argument("--dustgym-root", default=os.environ.get("DUSTGYM_ROOT"))
    ap.add_argument("--output", required=True)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--stations", type=int, default=6)
    a = ap.parse_args(argv)
    if not a.dustgym_root:
        ap.error("--dustgym-root or DUSTGYM_ROOT required")
    seq = run(a.dustgym_root, a.output, a.seed, a.stations)
    print(json.dumps({k: v for k, v in seq.items() if k != "frames"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
