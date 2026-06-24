"""Fresh-render ATE-at-scale via the PARALLAX leg (robust, the Navigation articulation cue): render a
per-station two-posture A/B pair along a traverse on crater_boulders, extract REAL absolute parallax
fixes (articulation_bridge.localize_on_render_pair), fuse via run_integrated_slam(measured_fixes), and
score ATE vs the true station cells. Real pixels only; truth = placed cells. Shadow leg NOT used.

This is the fresh-render end-to-end exercise of dart.render_traverse (the SLAM-seam adapter). It is
GPU-GATED: it shells out to Godot via stewie/godot/render.sh (NEVER --headless; runs res://sidecar.tscn
with --layers terrain,clasts,rover), ~1-2 s/station-posture on an RTX 3090.

VERIFIED 2026-06-17 on the L-path (one 90-deg turn, 8 stations, gyro bias 0.03 rad/step): 7/8 stations
resolved a parallax fix (0.30-1.91 m, mean 0.71 m; 1 unsolvable -> skipped, not fabricated); FUSED beats
odometry on aligned-ATE 0.709 vs 0.967 m AND on absolute error abs_max 1.825 vs 2.841 m. HONEST CAVEATS:
fix quality is terrain/range-dependent; aligned-ATE only discriminates on a TURNING path (a straight
traverse's constant-gyro-bias drift is a rigid rotation Umeyama alignment cancels -> the fix's absolute
benefit is invisible to aligned-ATE there, though abs_max still drops ~3.6->0.5 m). The stereo-VO leg
under-recovers on fresh ad-hoc traverses (validated only on the committed a6 traverse). No finished
lunar-shadow SLAM is claimed (slam_seam header).

Run:  .venv/bin/python scripts/demo/render_parallax_ate.py"""
import json, math, os, shutil, subprocess, sys, time
import numpy as np
ROOT = "/mnt/projects/stewie/code"; os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, f"{ROOT}/stewie/godot")
from dart import render_traverse as RT
import articulation_bridge as AB

SCENE = f"{ROOT}/samples/crater_boulders"; SCENE_NAME = "crater_boulders"
GODOT = f"{ROOT}/stewie/godot/.tools/godot/Godot_v4.6.3-stable_linux.x86_64"; PROJ = f"{ROOT}/stewie/godot"
STAGE = "/tmp/par_seq"; CELL = 0.02; DH = AB.chassis_lift_for("MEERKAT")  # 0.1743 m known parallax baseline
# L-PATH: leg 1 travels +row (yaw -90), leg 2 turns to +col (yaw 0). A constant gyro bias then drifts
# the two legs DIFFERENTLY -> non-rigid error that alignment cannot cancel -> aligned-ATE discriminates.
leg1 = [(50 + 25 * k, 100, -90.0) for k in range(4)]        # rows 50..125 at col 100
leg2 = [(125, 125 + 25 * k, 0.0) for k in range(4)]         # row 125, cols 125..200
PATH = leg1 + leg2                                          # 8 stations, 0.50 m steps, one 90-deg turn
N = len(PATH)
stations = [(r, c) for (r, c, _y) in PATH]
yaws_deg = [y for (_r, _c, y) in PATH]
truth_xy = np.array([[c * CELL, r * CELL] for (r, c) in stations], float)
truth_yaw = np.array([math.radians(y) for y in yaws_deg], float)
shutil.rmtree(STAGE, ignore_errors=True)
env = dict(os.environ, GODOT=GODOT)

def render(lift, r, c, yaw, dest):
    shutil.rmtree(f"{PROJ}/out/cam/{SCENE_NAME}", ignore_errors=True)
    os.makedirs(dest, exist_ok=True)
    cmd = ["bash", f"{PROJ}/render.sh", "res://sidecar.tscn", "--", "--scene", SCENE, "--cameras",
           "--layers", "terrain,clasts,rover", "--rover-rc", f"{r},{c}", "--rover-yaw", f"{yaw}",
           "--chassis-lift", f"{lift:.4f}", "--sun-elev", "5", "--sun-azim", "215", "--size", "1024x768"]
    subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=90)
    eg = f"{PROJ}/out/cam/{SCENE_NAME}/000"
    if not os.path.exists(f"{eg}/front_left.png"):
        return False
    for fn in os.listdir(eg):
        if fn.endswith(".png"):
            shutil.copy(f"{eg}/{fn}", f"{dest}/{fn}")
    return True

def station_dir(k):
    return f"{STAGE}/station_{k:02d}"

print("=== gauge station 0 A/B ===")
fixes, truth_seen = {}, {}
t0 = time.time()
for k, (r, c) in enumerate(stations):
    sd = station_dir(k); yaw = yaws_deg[k]
    okA = render(0.0, r, c, yaw, f"{sd}/A"); shutil.copy(f"{PROJ}/out/cam/{SCENE_NAME}/000/sensors.json", f"{sd}/A_sensors.json")
    okB = render(DH, r, c, yaw, f"{sd}/B"); shutil.copy(f"{PROJ}/out/cam/{SCENE_NAME}/000/sensors.json", f"{sd}/B_sensors.json")
    if not (okA and okB):
        print(f"  station {k}: render failed"); sys.exit(1)
    try:
        res = AB.localize_on_render_pair(sd, SCENE)
        fixes[k] = ((res["fix_xy"][0], res["fix_xy"][1]), float(res["fix_sigma_m"]))
        truth_seen[k] = res["true_xy"]
        print(f"  station {k} rc=({r},{c}): fix err {res['error_m']:.3f} m  ({res['n_inliers']} inliers)")
    except ValueError as e:
        print(f"  station {k}: parallax unsolvable ({e}) -> no fix (skipped, not fabricated)")
print(f"rendered+extracted {N} stations in {time.time()-t0:.0f}s")

# fuse: parallax absolute fixes at keyframes 1..N-1 (fix_interval=1) vs gyro-drift odometry
meas = {"parallax": {k: v for k, v in fixes.items() if k >= 1}}
res = RT.fused_render_traverse(truth_xy, truth_yaw, measured_fixes=meas,
                               factors=("odom", "imu", "parallax"), fix_interval=1, gyro_bias_rad=0.03)
print(f"\nfresh PARALLAX fixes: {len(fixes)}/{N} stations resolved (mean err "
      f"{np.mean([math.hypot(fixes[k][0][0]-truth_seen[k][0], fixes[k][0][1]-truth_seen[k][1]) for k in fixes]):.3f} m)")
print(f"ATE fused (parallax) {res['ate_fused_m']:.3f} m  vs odom {res['ate_odom_m']:.3f} m  "
      f"(abs_max fused {res['abs_max_fused_m']:.3f} / odom {res['abs_max_odom_m']:.3f})  over {N} stations")
json.dump({**res, "fixes": {str(k): fixes[k] for k in fixes}, "dh_m": DH},
          open(f"{STAGE}/parallax_ate.json", "w"), indent=2)
print(f"wrote {STAGE}/parallax_ate.json")
print("RESULT: PASS" if res["ate_fused_m"] < res["ate_odom_m"] else "RESULT: fused did NOT beat odom")
