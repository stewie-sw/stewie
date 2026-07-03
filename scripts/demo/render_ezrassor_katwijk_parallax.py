"""PAYOFF EXPERIMENT: EZ-RASSOR rig at the REAL Part4 RTK poses inside the katwijk_part4_station50
scene, scored with the ARTICULATION-PARALLAX absolute-fix path against RTK truth.

HONESTY LABEL: RENDERED-SENSOR SIMULATION, ARGUS G2 tier. Real terrain macro-shape (AHN 0.5 m DTM)
+ real Katwijk Part4 RTK trajectory + real 8-cam EZ-RASSOR/IPEx rig geometry; ALL sub-0.5 m camera
texture is PROCEDURAL Godot infill, NOT real imagery. This tests the articulation-parallax GEOMETRIC
cue on real Katwijk geometry; it is NOT a real-image match and does NOT close the real-LocCam VO gap.

REUSED verbatim (no logic change): build_katwijk_scene.py's scene (ENU first-fix anchor, pyproj
EPSG:4326->28992, rover-rc = (E-x0)/cell,(N-y0)/cell); render.sh + sidecar.tscn (8-cam rig,
--rover-rc/--rover-yaw/--chassis-lift); articulation_bridge.localize_on_render_pair (the estimator);
dart.depth_truth (DEM raycast, via the estimator); dart.ablation._align_ate (Umeyama aligned ATE, the
same primitive the template's fused_render_traverse uses); katwijk_io.load_gps_real + the ENU transform.

WRITTEN here: station selection over the real RTK ENU poses inside the footprint; per-station render
at rover-rc + heading yaw; a documented FRAME-BOOKKEEPING translation (express the emitted sensor
camera/rover positions in the scene-local zero-origin frame by subtracting world_min, because
depth_truth._height_at indexes the heightfield from a zero origin and this scene pins world_bounds to
the ENU frame -- crater_boulders happens to have world_min=(0,0) so the template never hit this);
assembly + scoring.
"""
import json, os, shutil, subprocess, sys, time
import numpy as np
ROOT = "/mnt/projects/stewie/code"; os.chdir(ROOT)
sys.path.insert(0, ROOT); sys.path.insert(0, f"{ROOT}/stewie/godot")
import articulation_bridge as AB
from dart.ablation import _align_ate
from pyproj import Transformer
from stewie.bridge.katwijk_io import load_gps_real

SCENE = f"{ROOT}/out/scenes/katwijk_part4_station50"; SCENE_NAME = os.path.basename(SCENE)
GODOT = f"{ROOT}/stewie/godot/.tools/godot/Godot_v4.6.3-stable_linux.x86_64"; PROJ = f"{ROOT}/stewie/godot"
STAGE = "/tmp/claude-1000/-mnt-projects/56ff42d5-5b12-4ac9-b424-8c422e825760/scratchpad/ezrassor_stage"
ARTIFACT_DIR = f"{ROOT}/stewie/eval/validation"
ARTIFACT = f"{ARTIFACT_DIR}/ezrassor_katwijk_articulation_parallax_2026-07-02.json"
README = f"{ARTIFACT_DIR}/ezrassor_katwijk_articulation_parallax_2026-07-02.README.md"

GPS = "/mnt/projects/datasets/katwijk/Part4/gps-latlong.txt"
LAT0, LON0 = 52.217259107, 4.4034692045
SUN_ELEV, SUN_AZIM, SIZE = "5", "215", "1024x768"
MARGIN_M = 3.0          # keep the rover patch inside the footprint
THIN_M = 0.30           # drop the parked-tail near-duplicate fixes
DH = AB.chassis_lift_for("MEERKAT")

HONESTY = ("RENDERED-SENSOR SIMULATION, ARGUS G2 tier. Real terrain macro-shape (AHN 0.5 m DTM) + "
           "real Katwijk Part4 RTK trajectory + real 8-cam EZ-RASSOR/IPEx rig geometry; ALL sub-0.5 m "
           "camera texture is PROCEDURAL Godot infill, NOT real imagery. This tests the "
           "articulation-parallax GEOMETRIC cue on real Katwijk geometry; it is NOT a real-image "
           "match and does NOT close the real-LocCam VO gap.")

meta = json.load(open(f"{SCENE}/metadata.json"))
wb = meta["world_bounds_m"]; X0, Y0 = wb["x0"], wb["y0"]; X1, Y1 = wb["x1"], wb["y1"]
CELL = float(meta["grid"]["cell_m"]); W = int(meta["grid"]["width"]); H = int(meta["grid"]["height"])

# --- REAL Part4 RTK in the SAME first-fix ENU frame build_katwijk_scene.py used ------------------
gps = load_gps_real(GPS)
assert abs(gps[0]["lat"] - LAT0) < 1e-6 and abs(gps[0]["lon"] - LON0) < 1e-6, "anchor mismatch"
to_rd = Transformer.from_crs("EPSG:4326", "EPSG:28992", always_xy=True)
rd0 = to_rd.transform(LON0, LAT0)
EN = np.array([[to_rd.transform(g["lon"], g["lat"])[0] - rd0[0],
                to_rd.transform(g["lon"], g["lat"])[1] - rd0[1]] for g in gps])
N_FIX = len(EN)

# heading per fix from consecutive RTK points (ENU), same convention as build_katwijk_scene
def heading_deg(i):
    j = min(i + 1, N_FIX - 1)
    d = EN[j] - EN[i]
    if np.hypot(*d) < 1e-6:
        d = EN[i] - EN[max(i - 1, 0)]
    return float(np.degrees(np.arctan2(d[1], d[0])))

# select: inside footprint (margin) AND moving (>= THIN_M from last kept)
selected = []
last = None
for i in range(N_FIX - 1):
    e, n = EN[i]
    if not (X0 + MARGIN_M <= e <= X1 - MARGIN_M and Y0 + MARGIN_M <= n <= Y1 - MARGIN_M):
        continue
    if last is not None and np.hypot(e - EN[last][0], n - EN[last][1]) < THIN_M:
        continue
    selected.append(i); last = i
print(f"[select] {len(selected)} in-scene moving poses (margin {MARGIN_M} m, thin {THIN_M} m): "
      f"idx {selected[0]}..{selected[-1]}")

shutil.rmtree(STAGE, ignore_errors=True)
env = dict(os.environ, GODOT=GODOT)

def render(lift, row, col, yaw_deg, dest):
    shutil.rmtree(f"{PROJ}/out/cam/{SCENE_NAME}", ignore_errors=True)
    os.makedirs(dest, exist_ok=True)
    cmd = ["bash", f"{PROJ}/render.sh", "res://sidecar.tscn", "--", "--scene", SCENE, "--cameras",
           "--layers", "terrain,clasts,rover", "--rover-rc", f"{row},{col}", "--rover-yaw", f"{yaw_deg}",
           "--chassis-lift", f"{lift:.4f}", "--sun-elev", SUN_ELEV, "--sun-azim", SUN_AZIM, "--size", SIZE]
    subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=180)
    eg = f"{PROJ}/out/cam/{SCENE_NAME}/000"
    if not os.path.exists(f"{eg}/front_left.png"):
        return None
    for fn in os.listdir(eg):
        if fn.endswith(".png"):
            shutil.copy(f"{eg}/{fn}", f"{dest}/{fn}")
    # snapshot sensors.json IMMEDIATELY: eg/ is rmtree'd by the next render() (A then B share eg)
    sens = f"{dest}/sensors.json"
    shutil.copy(f"{eg}/sensors.json", sens)
    return sens

def to_local(src_sensors, dst_sensors):
    """Frame bookkeeping: express positions in the scene-local zero-origin frame (subtract world_min);
    orientation untouched. Matches depth_truth's zero-origin heightfield indexing."""
    s = json.load(open(src_sensors))
    rp = s["rover"]["position_m"]; s["rover"]["position_m"] = [rp[0] - X0, rp[1], rp[2] - Y0]
    for cam in s["cameras"]:
        p = cam["pose_in_world"]["position_m"]
        cam["pose_in_world"]["position_m"] = [p[0] - X0, p[1], p[2] - Y0]
    json.dump(s, open(dst_sensors, "w"))

CMD_TEMPLATE = ("bash stewie/godot/render.sh res://sidecar.tscn -- --scene <SCENE> --cameras "
                "--layers terrain,clasts,rover --rover-rc <row,col> --rover-yaw <deg> "
                f"--chassis-lift <0.0|{DH:.4f}> --sun-elev {SUN_ELEV} --sun-azim {SUN_AZIM} --size {SIZE}")

records, errors_abs, fix_traj, true_traj = [], [], [], []
t0 = time.time()
for k, i in enumerate(selected):
    e, n = float(EN[i][0]), float(EN[i][1])
    col = int(round((e - X0) / CELL)); row = int(round((n - Y0) / CELL))  # nearest grid node (snap <= half-cell diag)
    yaw = heading_deg(i)
    sd = f"{STAGE}/station_{k:02d}_idx{i:03d}"
    sa = render(0.0, row, col, yaw, f"{sd}/A")
    sb = render(DH, row, col, yaw, f"{sd}/B")
    if sa is None or sb is None:
        print(f"  [{k:2d}] idx{i} rc=({row},{col}) RENDER FAILED -> skipped")
        records.append({"k": k, "rtk_idx": i, "rover_rc": [row, col], "status": "render_failed"})
        continue
    to_local(sa, f"{sd}/A_sensors.json"); to_local(sb, f"{sd}/B_sensors.json")
    rendered_true_enu = [X0 + col * CELL, Y0 + row * CELL]     # snapped RTK pose (integer cell)
    snap = float(np.hypot(rendered_true_enu[0] - e, rendered_true_enu[1] - n))
    try:
        res = AB.localize_on_render_pair(sd, SCENE)
    except (ValueError, FileNotFoundError) as ex:
        print(f"  [{k:2d}] idx{i} rc=({row},{col}) UNSOLVABLE ({ex}) -> skipped (not fabricated)")
        records.append({"k": k, "rtk_idx": i, "rover_rc": [row, col], "rtk_enu": [e, n],
                        "rendered_true_enu": rendered_true_enu, "snap_offset_m": round(snap, 3),
                        "status": "unsolvable", "reason": str(ex)})
        continue
    fx, fz = res["fix_xy"]                                     # scene-local
    fix_enu = [fx + X0, fz + Y0]
    err_vs_rendered = float(res["error_m"])                   # fix vs rendered (snapped RTK) truth
    err_vs_raw_rtk = float(np.hypot(fix_enu[0] - e, fix_enu[1] - n))
    errors_abs.append(err_vs_rendered)
    fix_traj.append(fix_enu); true_traj.append(rendered_true_enu)
    print(f"  [{k:2d}] idx{i} rc=({row},{col}) yaw={yaw:6.1f}  fix_err={err_vs_rendered:.3f} m  "
          f"(vs raw RTK {err_vs_raw_rtk:.3f})  {res['n_inliers']}/{res['n_features']} inl  "
          f"sig={res['fix_sigma_m']:.3f}  R={res['range_span_m']}")
    records.append({
        "k": k, "rtk_idx": i, "rover_rc": [row, col], "rover_yaw_deg": round(yaw, 2),
        "rtk_enu": [round(e, 4), round(n, 4)], "rendered_true_enu": [round(v, 4) for v in rendered_true_enu],
        "snap_offset_m": round(snap, 3), "fix_enu": [round(v, 4) for v in fix_enu],
        "fix_error_vs_rendered_m": round(err_vs_rendered, 3), "fix_error_vs_raw_rtk_m": round(err_vs_raw_rtk, 3),
        "n_features": res["n_features"], "n_inliers": res["n_inliers"],
        "fix_sigma_m": res["fix_sigma_m"], "range_span_m": res["range_span_m"], "status": "resolved"})

elapsed = time.time() - t0
n_sel = len(selected); n_res = len(errors_abs)
n_render_fail = sum(1 for r in records if r.get("status") == "render_failed")
n_unsolvable = sum(1 for r in records if r.get("status") == "unsolvable")
print(f"\n[done] {n_res}/{n_sel} stations resolved a fix in {elapsed:.0f}s "
      f"({n_render_fail} render-fail, {n_unsolvable} unsolvable-skipped)")

if n_res < 3:
    print("BLOCKED: fewer than 3 stations resolved -> refusing to fabricate an ATE.")
    sys.exit(2)

errors_abs = np.array(errors_abs)
FIX = np.array(fix_traj); TRU = np.array(true_traj)
abs_rms = float(np.sqrt(np.mean(errors_abs ** 2)))            # absolute-fix accuracy (no alignment)
aligned_ate = float(_align_ate(FIX, TRU))                     # template's Umeyama aligned ATE primitive
agg = {
    "n_selected": n_sel, "n_resolved": n_res, "n_render_failed": n_render_fail,
    "n_unsolvable_skipped": n_unsolvable,
    "per_station_fix_error_vs_rendered_m": {
        "min": round(float(errors_abs.min()), 3), "max": round(float(errors_abs.max()), 3),
        "mean": round(float(errors_abs.mean()), 3), "median": round(float(np.median(errors_abs)), 3)},
    "absolute_fix_ate_rms_m": round(abs_rms, 3),
    "aligned_ate_m": round(aligned_ate, 3),
    "rtk_snap_offset_m": {
        "median": round(float(np.median([r["snap_offset_m"] for r in records if "snap_offset_m" in r])), 3),
        "max": round(float(np.max([r["snap_offset_m"] for r in records if "snap_offset_m" in r])), 3),
        "note": "rendered rover pose = RTK snapped to the 0.5 m DEM grid (sidecar takes integer rover-rc); "
                "bounded by half a cell diagonal (~0.354 m). Estimator target = rendered pose."},
    "elapsed_s": round(elapsed, 1),
}
print("\n=== SCORE ===")
print(f"per-station fix error (vs rendered/snapped RTK): {agg['per_station_fix_error_vs_rendered_m']}")
print(f"absolute-fix ATE (RMS, no alignment): {abs_rms:.3f} m")
print(f"aligned ATE (Umeyama, template primitive): {aligned_ate:.3f} m")
print(f"RTK->grid snap offset: median {agg['rtk_snap_offset_m']['median']} m, max {agg['rtk_snap_offset_m']['max']} m")

out = {
    "experiment": "EZ-RASSOR rig at real Part4 RTK poses on the real Katwijk AHN scene, "
                  "articulation-parallax absolute-fix path, scored vs RTK truth",
    "date": "2026-07-02", "honesty_label": HONESTY,
    "scene_path": SCENE, "scene_world_bounds_m": wb, "scene_cell_m": CELL, "scene_grid": [W, H],
    "rtk_source": GPS, "enu_anchor": {"lat": LAT0, "lon": LON0, "note": "first Part4 fix = start datum"},
    "enu_transform": "pyproj EPSG:4326 -> EPSG:28992 (RD New), first-fix anchored (== build_katwijk_scene.py)",
    "chassis_lift_dh_m": round(DH, 4), "posture_pair": ["TRANSIT (lift 0.0)", "MEERKAT (lift %.4f)" % DH],
    "sun_elev_deg": float(SUN_ELEV), "sun_azim_deg": float(SUN_AZIM), "render_size": SIZE,
    "selection": {"margin_m": MARGIN_M, "thin_m": THIN_M,
                  "rtk_idx_selected": selected, "rule": "inside footprint (margin) AND >= thin_m from last kept (drops parked tail)"},
    "aggregate": agg, "stations": records,
    "exact_commands": {
        "build_scene (milestone 1, NOT re-run; scene reused as-is)":
            ".venv/bin/python benchmarks/katwijk/build_katwijk_scene.py",
        "per_station_render_A_and_B (row,col from (E-x0)/cell,(N-y0)/cell; lift 0.0 then %.4f)" % DH:
            CMD_TEMPLATE,
        "localize": "stewie/godot/articulation_bridge.localize_on_render_pair(<station_dir>, <scene_dir>)",
        "run": ".venv/bin/python scripts/demo/render_ezrassor_katwijk_parallax.py",
    },
    "reused_vs_written": {
        "reused_verbatim": [
            "benchmarks/katwijk/build_katwijk_scene.py -> the milestone-1 scene (ENU first-fix anchor, "
            "pyproj EPSG:4326->28992, rover-rc mapping); scene NOT rebuilt",
            "stewie/godot/render.sh + sidecar.tscn -> 8-cam EZ-RASSOR/IPEx render",
            "stewie/godot/articulation_bridge.localize_on_render_pair -> the articulation-parallax "
            "absolute-fix estimator (block-match parallax -> range -> DEM raycast -> RANSAC trilateration)",
            "dart.depth_truth -> DEM raycast landmark association (via the estimator)",
            "dart.ablation._align_ate -> Umeyama aligned-ATE primitive (same one the template's "
            "fused_render_traverse uses via run_integrated_slam)",
            "stewie.bridge.katwijk_io.load_gps_real + pyproj ENU transform",
        ],
        "written_this_experiment": [
            "station selection over the real RTK ENU poses inside the footprint (moving-run thinning)",
            "per-station render invocation at rover-rc + heading yaw",
            "a documented frame-bookkeeping translation: express emitted sensor camera/rover positions "
            "in the scene-local zero-origin frame (subtract world_min) so they match depth_truth's "
            "zero-origin heightfield indexing (translation only; orientation unchanged; estimator "
            "logic untouched). Root cause: this scene pins world_bounds to the ENU frame while "
            "depth_truth._height_at indexes from a zero origin; crater_boulders has world_min=(0,0) so "
            "the template never exercised this.",
            "assembly + scoring (absolute-fix RMS + aligned ATE)",
        ],
    },
    "interpretation": (
        "The absolute-fix ATE (%.3f m RMS) is the accuracy with which the standstill "
        "articulation-parallax cue recovers the rover's ABSOLUTE ground position, truth-free, on REAL "
        "Katwijk AHN 0.5 m terrain geometry, from the real 8-cam rig. Per-station errors span %.3f-%.3f m. "
        "It is a GEOMETRIC-cue result on real terrain shape, NOT a real-image VO result: the sub-0.5 m "
        "camera texture is procedural Godot infill, so this does not close the real-LocCam gap."
        % (abs_rms, float(errors_abs.min()), float(errors_abs.max()))),
}
os.makedirs(ARTIFACT_DIR, exist_ok=True)
json.dump(out, open(ARTIFACT, "w"), indent=2)
print(f"\nwrote artifact: {ARTIFACT}")

readme = f"""# EZ-RASSOR on real Katwijk -- articulation-parallax absolute-fix payoff (2026-07-02)

**{HONESTY}**

The EZ-RASSOR/IPEx 8-camera rig was rendered at the {n_res} REAL Part4 RTK poses (of {n_sel} selected)
that fall inside the `katwijk_part4_station50` scene footprint (real AHN 0.5 m DTM crop, ENU-anchored at
the first RTK fix). At each pose the rig rendered a two-posture chassis-lift A/B pair (TRANSIT lift 0.0
-> MEERKAT lift {DH:.4f} m), and `articulation_bridge.localize_on_render_pair` recovered an ABSOLUTE
ground-position fix truth-free (block-match vertical parallax -> range = fx*dh/dv -> DEM-raycast landmark
-> RANSAC trilateration). Fixes were scored against the RTK truth (the render places the rover at the RTK
pose snapped to the 0.5 m DEM grid; the estimator's target is that rendered pose).

- **Per-station absolute fix error (vs rendered/snapped RTK):** {agg['per_station_fix_error_vs_rendered_m']['min']}-{agg['per_station_fix_error_vs_rendered_m']['max']} m (median {agg['per_station_fix_error_vs_rendered_m']['median']} m).
- **Absolute-fix ATE (RMS, no alignment):** {abs_rms:.3f} m -- the headline: absolute-position accuracy of the parallax cue on real Katwijk geometry.
- **Aligned ATE (Umeyama, template's `_align_ate`):** {aligned_ate:.3f} m -- trajectory-shape consistency after a best rigid alignment.
- **RTK->grid snap:** median {agg['rtk_snap_offset_m']['median']} m, max {agg['rtk_snap_offset_m']['max']} m (truth discretization from the sidecar's integer rover-rc, <= half a cell diagonal ~0.354 m).

**What the number means:** how accurately the standstill articulation-parallax GEOMETRIC cue localizes
the rover's absolute position on REAL Katwijk terrain shape, from the real rig, rendered-sim. It is NOT a
real-image match and does NOT close the real-LocCam VO gap (all sub-0.5 m texture is procedural infill).

Artifact: `ezrassor_katwijk_articulation_parallax_2026-07-02.json` (per-station errors, commands,
reused-vs-written breakdown). Estimator reused verbatim; only station selection, a world_min
frame-bookkeeping translation, and scoring were written for this run.
"""
open(README, "w").write(readme)
print(f"wrote README: {README}")
