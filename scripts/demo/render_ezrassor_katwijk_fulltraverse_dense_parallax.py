"""FULL-TRAVERSE payoff: EZ-RASSOR rig at the REAL Part4 RTK poses across the WHOLE Katwijk Part4
trajectory (not one 40 m scene), scored with the ARTICULATION-PARALLAX absolute-fix path vs RTK truth.

HONESTY LABEL: RENDERED-SENSOR SIMULATION, ARGUS G2 tier. Real AHN 0.5 m terrain macro-shape + real
Part4 RTK trajectory + real 8-cam EZ-RASSOR/IPEx rig geometry; ALL sub-0.5 m camera texture is
PROCEDURAL Godot infill, NOT real imagery. Geometric-cue result on real Katwijk geometry; NOT a
real-image match; does NOT close the real-LocCam VO gap.

WHY TILING: Part4's whole traverse (~76 m path, ENU bbox ~40 x 63 m) is longer than one 40 m scene,
and the sidecar camera far-plane is hardcoded 100 m, so the whole traverse cannot live in one scene.
We TILE it: cover the trajectory with a sequence of overlapping local scenes (each 50 m, safely inside
the far-plane; each rover-to-farthest-terrain distance <= ~52 m), assign each RTK station to the tile
that contains it (bbox-segmented, midpoint-centred, so every member is >= MARGIN_M + BUF_M inside its
tile), render+localize every station across all tiles, then assemble ALL absolute parallax fixes into
ONE full-traverse trajectory in the single first-fix ENU frame and score its ATE vs the full Part4 RTK.

REUSED verbatim (no logic change):
  - benchmarks/katwijk/build_katwijk_scene.py::KatwijkAhnDem  -> the milestone-1 AHN 0.5 m DTM ingest
    sampler (ENU first-fix anchor, pyproj EPSG:4326->28992); the per-tile crop+inject mirrors
    build_katwijk_scene.main() (dem_to_base -> save_scene, world_bounds ENU-pinned) parametrized only
    by (tile centre, extent).
  - stewie/godot/render.sh + sidecar.tscn  -> the 8-cam EZ-RASSOR/IPEx render (--rover-rc/--rover-yaw/
    --chassis-lift), NEVER --headless.
  - stewie/godot/articulation_bridge.localize_on_render_pair  -> the estimator (block-match parallax ->
    range = fx*dh/dv -> DEM raycast landmark -> RANSAC trilateration).
  - dart.ablation._align_ate  -> Umeyama aligned-ATE primitive (same one the template's
    fused_render_traverse uses).
  - stewie.bridge.katwijk_io.load_gps_real + the pyproj ENU transform.
  - render()/to_local()/per-station block  -> the two hard-won fixes from render_ezrassor_katwijk_parallax.py:
    (1) snapshot sensors.json per posture (A then B share the render egress dir, so B would overwrite A
        -> dh<=0 fail); (2) translate emitted sensor positions into the scene-local zero-origin frame
        (subtract world_min) because depth_truth._height_at indexes the heightfield from zero while the
        scene pins world_bounds to the ENU frame. These are copied verbatim; only the frame constants
        (X0,Y0,CELL,SCENE) become PER-TILE (which is exactly how the per-tile frame offsets are handled).

WRITTEN here: the full-track moving-station selection; the bbox-segmented midpoint-centred tiling plan;
per-tile scene build (parametrized centre+extent); per-tile station->fix assembly into ONE ENU frame;
full-traverse scoring (absolute-fix RMS + Umeyama aligned ATE + per-station distribution).

Run:  /mnt/projects/stewie/code/.venv/bin/python scripts/demo/render_ezrassor_katwijk_fulltraverse_parallax.py
      (append  --plan-only  to build tiles + verify the assignment/margins WITHOUT rendering)
"""
import json, os, shutil, subprocess, sys, time
import numpy as np

ROOT = "/mnt/projects/stewie/code"; os.chdir(ROOT)
sys.path.insert(0, ROOT); sys.path.insert(0, f"{ROOT}/stewie/godot"); sys.path.insert(0, f"{ROOT}/benchmarks/katwijk")

import articulation_bridge as AB
from dart.ablation import _align_ate
from dart.dem_import import Affine, dem_to_base
from pyproj import Transformer
from stewie.bridge.katwijk_io import load_gps_real
from stewie.twin.io_fields import save_scene
from build_katwijk_scene import AHN, KatwijkAhnDem  # the milestone-1 ingest sampler, verbatim

GPS = "/mnt/projects/datasets/katwijk/Part4/gps-latlong.txt"
LAT0, LON0 = 52.217259107, 4.4034692045
GODOT = f"{ROOT}/stewie/godot/.tools/godot/Godot_v4.6.3-stable_linux.x86_64"; PROJ = f"{ROOT}/stewie/godot"
STAGE = "/tmp/claude-1000/-mnt-projects/56ff42d5-5b12-4ac9-b424-8c422e825760/scratchpad/ezrassor_ftdense_stage"
SCENES_ROOT = f"{ROOT}/out/scenes"
ARTIFACT_DIR = f"{ROOT}/stewie/eval/validation"
ARTIFACT = f"{ARTIFACT_DIR}/ezrassor_katwijk_fulltraverse_dense_articulation_parallax_2026-07-02.json"
README = f"{ARTIFACT_DIR}/ezrassor_katwijk_fulltraverse_dense_articulation_parallax_2026-07-02.README.md"

SUN_ELEV, SUN_AZIM, SIZE = "5", "215", "1024x768"
EXTENT_M = 30.0          # DENSE tile side (robustness stress test; << 100 m far-plane; each station more centred)
CELL = 0.5               # base grid = native AHN resolution
MARGIN_M = 3.0           # keep the rover patch inside each tile (== single-scene driver)
BUF_M = 2.0              # extra slack beyond MARGIN so every assigned station clears the margin check
THIN_M = 0.30            # drop the parked-tail near-duplicate fixes (== single-scene driver)
GRAVITY_M_S2 = 9.80665
DH = AB.chassis_lift_for("MEERKAT")
PLAN_ONLY = "--plan-only" in sys.argv

HONESTY = ("RENDERED-SENSOR SIMULATION, ARGUS G2 tier. Real AHN 0.5 m terrain macro-shape + real "
           "Katwijk Part4 RTK trajectory + real 8-cam EZ-RASSOR/IPEx rig geometry; ALL sub-0.5 m "
           "camera texture is PROCEDURAL Godot infill, NOT real imagery. Geometric-cue result on real "
           "Katwijk geometry; NOT a real-image match; does NOT close the real-LocCam VO gap.")

# --- REAL Part4 RTK in the first-fix ENU frame (== build_katwijk_scene.py's frame) ----------------
gps = load_gps_real(GPS)
assert abs(gps[0]["lat"] - LAT0) < 1e-6 and abs(gps[0]["lon"] - LON0) < 1e-6, "anchor mismatch"
to_rd = Transformer.from_crs("EPSG:4326", "EPSG:28992", always_xy=True)
rd0 = to_rd.transform(LON0, LAT0)
EN = np.array([[to_rd.transform(g["lon"], g["lat"])[0] - rd0[0],
                to_rd.transform(g["lon"], g["lat"])[1] - rd0[1]] for g in gps])
N_FIX = len(EN)
seg = np.hypot(np.diff(EN[:, 0]), np.diff(EN[:, 1]))
PATH_LEN = float(seg.sum())


def heading_deg(i):
    """Travel heading in ENU from consecutive RTK points (GLOBAL indices; == build_katwijk_scene)."""
    j = min(i + 1, N_FIX - 1)
    d = EN[j] - EN[i]
    if np.hypot(*d) < 1e-6:
        d = EN[i] - EN[max(i - 1, 0)]
    return float(np.degrees(np.arctan2(d[1], d[0])))


# --- global moving-station selection (thin the parked tail), then bbox-segmented midpoint tiling -----
selected, last = [], None
for i in range(N_FIX - 1):                          # need a next fix for heading
    e, n = EN[i]
    if last is not None and np.hypot(e - EN[last][0], n - EN[last][1]) < THIN_M:
        continue
    selected.append(i); last = i

MAXSPAN = EXTENT_M - 2 * MARGIN_M - 2 * BUF_M       # bbox side a tile's members may occupy
segments, cur, bb = [], [], None
for i in selected:
    e, n = EN[i]
    if not cur:
        cur = [i]; bb = [e, e, n, n]; continue
    ne0, ne1, nn0, nn1 = min(bb[0], e), max(bb[1], e), min(bb[2], n), max(bb[3], n)
    if (ne1 - ne0) <= MAXSPAN and (nn1 - nn0) <= MAXSPAN:
        cur.append(i); bb = [ne0, ne1, nn0, nn1]
    else:
        segments.append((cur, bb)); cur = [i]; bb = [e, e, n, n]
if cur:
    segments.append((cur, bb))

tiles = []
for k, (members, (e0, e1, n0, n1)) in enumerate(segments):
    ce, cn = (e0 + e1) / 2.0, (n0 + n1) / 2.0
    reach = max(abs(e0 - ce), abs(e1 - ce), abs(n0 - cn), abs(n1 - cn))
    tiles.append({"k": k, "center_enu": [float(ce), float(cn)], "members": members,
                  "member_maxreach_m": float(reach)})

print(f"[track] {N_FIX} RTK fixes, path length {PATH_LEN:.1f} m; ENU bbox "
      f"E[{EN[:,0].min():.1f},{EN[:,0].max():.1f}] N[{EN[:,1].min():.1f},{EN[:,1].max():.1f}]")
print(f"[select] {len(selected)} moving stations (thin {THIN_M} m): idx {selected[0]}..{selected[-1]}")
print(f"[tiling] {len(tiles)} tiles, {EXTENT_M:.0f} m each (maxspan {MAXSPAN:.0f} m, margin {MARGIN_M} m + buf {BUF_M} m):")
half_reach = EXTENT_M / 2.0 - MARGIN_M              # driver margin check: |station-center| <= this
for t in tiles:
    slack = half_reach - t["member_maxreach_m"]
    print(f"  tile {t['k']}: center=({t['center_enu'][0]:.2f},{t['center_enu'][1]:.2f})  "
          f"{len(t['members'])} stations idx[{t['members'][0]}..{t['members'][-1]}]  "
          f"maxreach={t['member_maxreach_m']:.1f} m  margin-slack={slack:.1f} m")
    assert slack > 0, f"tile {t['k']} has a station outside the margin check (slack {slack:.2f} m)"


# --- per-tile scene build: mirrors build_katwijk_scene.main() crop+inject, parametrized centre+extent -
def build_tile_scene(dem, center_e, center_n, scene_dir, scene_name):
    n = int(round(EXTENT_M / CELL)); half = n // 2
    x0 = center_e - half * CELL; y0 = center_n - half * CELL
    Z = np.empty((n, n), dtype=np.float32)
    for row in range(n):
        nn = y0 + row * CELL
        for col in range(n):
            Z[row, col] = dem.height_enu(x0 + col * CELL, nn)
    cs = dem_to_base(Z, Affine(x0=float(x0), y0=float(y0), px=CELL), CELL)
    rt_err = float(np.max(np.abs(cs.derive_height() - Z.astype(np.float64))))
    x1, y1 = x0 + n * CELL, y0 + n * CELL
    hmin, hmax = float(Z.min()), float(Z.max())
    meta = {
        "schema_version": "1.0", "scene_name": scene_name,
        "producer": "scripts/demo/render_ezrassor_katwijk_fulltraverse_parallax.py "
                    "(build_katwijk_scene ingest, per-tile parametrized centre+extent)",
        "grid": {"width": n, "height": n, "cell_m": CELL, "order": "row-major-C"},
        "world_bounds_m": {"x0": round(x0, 6), "y0": round(y0, 6), "x1": round(x1, 6), "y1": round(y1, 6)},
        "gravity_m_s2": GRAVITY_M_S2,
        "fields": {
            "heightmap": {"file": "heightmap.rf32", "dtype": "<f4", "units": "m"},
            "mass_areal": {"file": "mass_areal.rf32", "dtype": "<f4", "units": "kg/m^2"},
            "density": {"file": "density.rf32", "dtype": "<f4", "units": "kg/m^3"},
            "disturbance": {"file": "disturbance.rf32", "dtype": "<f4", "units": "1 (normalized)"},
            "state_label": {"file": "state_label.r8", "dtype": "u1",
                            "enum": ["VIRGIN", "TREAD", "EXCAVATED", "SPOIL", "COMPACTED_BERM", "SINTERED"]},
        },
        "ice_present": False, "height_range_m": [round(hmin, 5), round(hmax, 5)], "clasts": [],
        "active_zone": {"min_rc": [0, 0], "max_rc": [n, n]},
        "quadtree": [{"level": 0, "row0": 0, "col0": 0, "size": n, "label": "ROOT"}],
        "rover_rc": [half, half],
        "dem_provenance": {
            "source": "AHN 0.5 m national LiDAR DTM (Katwijk), " + AHN, "crs": "EPSG:28992 (RD New)",
            "native_cell_m": 0.5,
            "enu_anchor": {"lat": LAT0, "lon": LON0, "note": "first Part4 RTK fix = declared start datum"},
            "rtk_source": GPS, "tile_center_enu_m": {"east": round(center_e, 6), "north": round(center_n, 6)},
        },
        "honesty": HONESTY,
        "notes": (f"Full-traverse tile: real AHN DTM crop ({EXTENT_M:.0f} m @ {CELL} m) centred on ENU "
                  f"({center_e:.3f},{center_n:.3f}); world_bounds pinned to the first-fix ENU frame so "
                  "rover-rc and RTK share ONE frame. " + HONESTY),
    }
    save_scene(scene_dir, cs.fields_dict(), meta)
    return meta, rt_err, [x0, y0, x1, y1]


# --- render()/to_local(): VERBATIM from render_ezrassor_katwijk_parallax.py (scene/frame per tile) ----
env = dict(os.environ, GODOT=GODOT)


def render(scene, scene_name, lift, row, col, yaw_deg, dest):
    shutil.rmtree(f"{PROJ}/out/cam/{scene_name}", ignore_errors=True)
    os.makedirs(dest, exist_ok=True)
    cmd = ["bash", f"{PROJ}/render.sh", "res://sidecar.tscn", "--", "--scene", scene, "--cameras",
           "--layers", "terrain,clasts,rover", "--rover-rc", f"{row},{col}", "--rover-yaw", f"{yaw_deg}",
           "--chassis-lift", f"{lift:.4f}", "--sun-elev", SUN_ELEV, "--sun-azim", SUN_AZIM, "--size", SIZE]
    subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=180)
    eg = f"{PROJ}/out/cam/{scene_name}/000"
    if not os.path.exists(f"{eg}/front_left.png"):
        return None
    for fn in os.listdir(eg):
        if fn.endswith(".png"):
            shutil.copy(f"{eg}/{fn}", f"{dest}/{fn}")
    # snapshot sensors.json IMMEDIATELY: eg/ is rmtree'd by the next render() (A then B share eg)
    sens = f"{dest}/sensors.json"
    shutil.copy(f"{eg}/sensors.json", sens)
    return sens


def to_local(src_sensors, dst_sensors, x0, y0):
    """Frame bookkeeping: express positions in the scene-local zero-origin frame (subtract this tile's
    world_min); orientation untouched. Matches depth_truth's zero-origin heightfield indexing."""
    s = json.load(open(src_sensors))
    rp = s["rover"]["position_m"]; s["rover"]["position_m"] = [rp[0] - x0, rp[1], rp[2] - y0]
    for cam in s["cameras"]:
        p = cam["pose_in_world"]["position_m"]
        cam["pose_in_world"]["position_m"] = [p[0] - x0, p[1], p[2] - y0]
    json.dump(s, open(dst_sensors, "w"))


CMD_TEMPLATE = ("bash stewie/godot/render.sh res://sidecar.tscn -- --scene <TILE_SCENE> --cameras "
                "--layers terrain,clasts,rover --rover-rc <row,col> --rover-yaw <deg> "
                f"--chassis-lift <0.0|{DH:.4f}> --sun-elev {SUN_ELEV} --sun-azim {SUN_AZIM} --size {SIZE}")

# --- build every tile scene (cheap; also the plan-only artifact) ------------------------------------
shutil.rmtree(STAGE, ignore_errors=True)
for t in tiles:
    t["scene_name"] = f"katwijk_part4_ftdense_tile{t['k']}"
    t["scene_dir"] = f"{SCENES_ROOT}/{t['scene_name']}"
    meta, rt_err, wb = build_tile_scene(KatwijkAhnDem(AHN, LAT0, LON0),
                                        t["center_enu"][0], t["center_enu"][1], t["scene_dir"], t["scene_name"])
    t["world_bounds_m"] = wb; t["rt_err_m"] = rt_err
    t["height_range_m"] = meta["height_range_m"]
    print(f"[build] tile {t['k']} -> {t['scene_dir']}  world_bounds={[round(v,2) for v in wb]}  "
          f"height {meta['height_range_m']}  round-trip max|err|={rt_err:.1e} m")

if PLAN_ONLY:
    print("\n[plan-only] tiles built, assignment + margins verified; no rendering. Exiting.")
    sys.exit(0)

# --- render + localize every station across all tiles, assemble into ONE ENU frame ------------------
records, errors_abs, fix_traj, true_traj = [], [], [], []
t0 = time.time()
for t in tiles:
    X0, Y0, X1, Y1 = t["world_bounds_m"]; SCENE = t["scene_dir"]; SNAME = t["scene_name"]
    for i in t["members"]:
        e, n = float(EN[i][0]), float(EN[i][1])
        col = int(round((e - X0) / CELL)); row = int(round((n - Y0) / CELL))  # nearest grid node
        yaw = heading_deg(i)
        sd = f"{STAGE}/tile{t['k']}_idx{i:03d}"
        sa = render(SCENE, SNAME, 0.0, row, col, yaw, f"{sd}/A")
        sb = render(SCENE, SNAME, DH, row, col, yaw, f"{sd}/B")
        if sa is None or sb is None:
            print(f"  [t{t['k']} idx{i:3d}] rc=({row},{col}) RENDER FAILED -> skipped")
            records.append({"tile": t["k"], "rtk_idx": i, "rover_rc": [row, col], "status": "render_failed"})
            continue
        to_local(sa, f"{sd}/A_sensors.json", X0, Y0); to_local(sb, f"{sd}/B_sensors.json", X0, Y0)
        rendered_true_enu = [X0 + col * CELL, Y0 + row * CELL]     # snapped RTK pose in GLOBAL ENU
        snap = float(np.hypot(rendered_true_enu[0] - e, rendered_true_enu[1] - n))
        try:
            res = AB.localize_on_render_pair(sd, SCENE)
        except (ValueError, FileNotFoundError) as ex:
            print(f"  [t{t['k']} idx{i:3d}] rc=({row},{col}) UNSOLVABLE ({ex}) -> skipped (not fabricated)")
            records.append({"tile": t["k"], "rtk_idx": i, "rover_rc": [row, col], "rtk_enu": [e, n],
                            "rendered_true_enu": rendered_true_enu, "snap_offset_m": round(snap, 3),
                            "status": "unsolvable", "reason": str(ex)})
            continue
        fx, fz = res["fix_xy"]                                     # scene-local (zero-origin)
        fix_enu = [fx + X0, fz + Y0]                              # GLOBAL ENU (per-tile offset handled)
        err_vs_rendered = float(res["error_m"])                  # fix vs rendered (snapped RTK) truth
        err_vs_raw_rtk = float(np.hypot(fix_enu[0] - e, fix_enu[1] - n))
        errors_abs.append(err_vs_rendered)
        fix_traj.append(fix_enu); true_traj.append(rendered_true_enu)
        print(f"  [t{t['k']} idx{i:3d}] rc=({row},{col}) yaw={yaw:6.1f}  fix_err={err_vs_rendered:.3f} m  "
              f"(vs raw RTK {err_vs_raw_rtk:.3f})  {res['n_inliers']}/{res['n_features']} inl  "
              f"sig={res['fix_sigma_m']:.3f}  R={res['range_span_m']}")
        records.append({
            "tile": t["k"], "rtk_idx": i, "rover_rc": [row, col], "rover_yaw_deg": round(yaw, 2),
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
      f"({n_render_fail} render-fail, {n_unsolvable} unsolvable-skipped) across {len(tiles)} tiles")

if n_res < 3:
    print("BLOCKED: fewer than 3 stations resolved -> refusing to fabricate an ATE.")
    sys.exit(2)

errors_abs = np.array(errors_abs)
FIX = np.array(fix_traj); TRU = np.array(true_traj)
abs_rms = float(np.sqrt(np.mean(errors_abs ** 2)))            # absolute-fix accuracy (no alignment)
aligned_ate = float(_align_ate(FIX, TRU))                     # Umeyama aligned ATE over the FULL traverse

snaps = [r["snap_offset_m"] for r in records if "snap_offset_m" in r]
per_tile = []
for t in tiles:
    tk = [r for r in records if r["tile"] == t["k"]]
    tr = [r["fix_error_vs_rendered_m"] for r in tk if r["status"] == "resolved"]
    per_tile.append({"tile": t["k"], "center_enu": t["center_enu"], "n_members": len(t["members"]),
                     "n_resolved": len(tr), "world_bounds_m": [round(v, 3) for v in t["world_bounds_m"]],
                     "height_range_m": t["height_range_m"], "rt_err_m": t["rt_err_m"],
                     "fix_error_min_max_mean_m": [round(min(tr), 3), round(max(tr), 3), round(float(np.mean(tr)), 3)] if tr else None})

agg = {
    "n_selected": n_sel, "n_resolved": n_res, "n_render_failed": n_render_fail, "n_unsolvable_skipped": n_unsolvable,
    "per_station_fix_error_vs_rendered_m": {
        "min": round(float(errors_abs.min()), 3), "max": round(float(errors_abs.max()), 3),
        "mean": round(float(errors_abs.mean()), 3), "median": round(float(np.median(errors_abs)), 3),
        "p90": round(float(np.percentile(errors_abs, 90)), 3)},
    "absolute_fix_ate_rms_m": round(abs_rms, 3),
    "aligned_ate_m": round(aligned_ate, 3),
    "rtk_snap_offset_m": {
        "median": round(float(np.median(snaps)), 3), "max": round(float(np.max(snaps)), 3),
        "note": "rendered rover pose = RTK snapped to the 0.5 m DEM grid (sidecar takes integer "
                "rover-rc); bounded by half a cell diagonal (~0.354 m). Estimator target = rendered pose."},
    "elapsed_s": round(elapsed, 1),
}
print("\n=== FULL-TRAVERSE SCORE ===")
print(f"tiles: {len(tiles)}  stations: {n_res}/{n_sel} resolved ({n_render_fail} render-fail, {n_unsolvable} unsolvable)")
print(f"per-station fix error (vs rendered/snapped RTK): {agg['per_station_fix_error_vs_rendered_m']}")
print(f"absolute-fix ATE (RMS, no alignment): {abs_rms:.3f} m")
print(f"aligned ATE (Umeyama, full traverse): {aligned_ate:.3f} m")

out = {
    "experiment": "EZ-RASSOR rig at real Part4 RTK poses across the FULL Katwijk trajectory (tiled "
                  "AHN scenes), articulation-parallax absolute-fix path, scored vs full-traverse RTK truth",
    "date": "2026-07-02", "honesty_label": HONESTY,
    "rtk_source": GPS, "n_rtk_fixes": N_FIX, "path_length_m": round(PATH_LEN, 2),
    "enu_bbox_m": {"e": [round(float(EN[:, 0].min()), 3), round(float(EN[:, 0].max()), 3)],
                   "n": [round(float(EN[:, 1].min()), 3), round(float(EN[:, 1].max()), 3)]},
    "enu_anchor": {"lat": LAT0, "lon": LON0, "note": "first Part4 fix = start datum"},
    "enu_transform": "pyproj EPSG:4326 -> EPSG:28992 (RD New), first-fix anchored (== build_katwijk_scene.py)",
    "dem_source": AHN, "chassis_lift_dh_m": round(DH, 4),
    "posture_pair": ["TRANSIT (lift 0.0)", "MEERKAT (lift %.4f)" % DH],
    "sun_elev_deg": float(SUN_ELEV), "sun_azim_deg": float(SUN_AZIM), "render_size": SIZE,
    "tiling": {"extent_m": EXTENT_M, "cell_m": CELL, "margin_m": MARGIN_M, "buf_m": BUF_M, "thin_m": THIN_M,
               "n_tiles": len(tiles), "far_plane_m": 100.0,
               "rule": "global moving-station selection (thin) -> bbox-segmented (span <= extent-2*margin-2*buf) "
                       "-> tile centred on each segment's bbox midpoint (symmetric margins); every member "
                       "clears the driver's |station-center| <= extent/2 - margin check by >= buf.",
               "rtk_idx_selected": selected, "tiles": per_tile},
    "aggregate": agg, "stations": records,
    "exact_commands": {
        "build_tile_scene (per tile, build_katwijk_scene ingest parametrized)":
            "KatwijkAhnDem(AHN,LAT0,LON0) -> per-cell height_enu crop -> dem_to_base -> save_scene "
            "(world_bounds ENU-pinned at tile centre +- extent/2)",
        "per_station_render_A_and_B (row,col from (E-x0)/cell,(N-y0)/cell; lift 0.0 then %.4f)" % DH: CMD_TEMPLATE,
        "localize": "stewie/godot/articulation_bridge.localize_on_render_pair(<station_dir>, <tile_scene_dir>)",
        "run": ".venv/bin/python scripts/demo/render_ezrassor_katwijk_fulltraverse_parallax.py",
    },
    "reused_vs_written": {
        "reused_verbatim": [
            "benchmarks/katwijk/build_katwijk_scene.py::KatwijkAhnDem -> the AHN 0.5 m DTM ingest sampler "
            "(ENU first-fix anchor, pyproj EPSG:4326->28992); per-tile crop+inject mirrors "
            "build_katwijk_scene.main() (dem_to_base -> save_scene, world_bounds ENU-pinned)",
            "stewie/godot/render.sh + sidecar.tscn -> 8-cam EZ-RASSOR/IPEx render",
            "stewie/godot/articulation_bridge.localize_on_render_pair -> the articulation-parallax "
            "absolute-fix estimator (block-match parallax -> range -> DEM raycast -> RANSAC trilateration)",
            "dart.depth_truth -> DEM raycast landmark association (via the estimator)",
            "dart.ablation._align_ate -> Umeyama aligned-ATE primitive",
            "stewie.bridge.katwijk_io.load_gps_real + pyproj ENU transform",
            "render()/to_local()/per-station block from render_ezrassor_katwijk_parallax.py, incl. its two "
            "fixes (per-posture sensors.json snapshot; world_min frame translation) -- copied verbatim, "
            "with the frame constants (X0,Y0,CELL,SCENE) made PER-TILE (how the per-tile offsets are handled)",
        ],
        "written_this_experiment": [
            "full-track moving-station selection over the real RTK ENU poses (thin the parked tail)",
            "bbox-segmented, midpoint-centred tiling plan covering the whole traverse inside the 100 m far-plane",
            "per-tile scene build parametrized by (centre, extent) (same ingest, different crop)",
            "per-tile station->fix assembly into ONE first-fix ENU frame (add each tile's world_min to the "
            "scene-local fix), and full-traverse scoring (absolute-fix RMS + Umeyama aligned ATE + distribution)",
        ],
    },
    "comparison_2tile_baseline": {
        "baseline_artifact": "ezrassor_katwijk_fulltraverse_articulation_parallax_2026-07-02.json",
        "baseline_commit": "9913eb5",
        "purpose": "ROBUSTNESS STRESS TEST: identical estimator/render/station-selection/thinning; ONLY the "
                   "tile extent changes (50 m 2-tile baseline -> 30 m dense). Tests whether the ATE is robust "
                   "to tiling granularity (each station sits more centred in a tighter scene).",
        "baseline_2tile": {"extent_m": 50.0, "n_tiles": 2, "n_selected": 58, "n_resolved": 56,
                           "n_unsolvable_skipped": 2, "n_render_failed": 0,
                           "absolute_fix_ate_rms_m": 5.785, "aligned_ate_m": 5.646,
                           "per_station_fix_error_min_max_mean_median_p90_m": [0.359, 17.715, 4.815, 4.103, 8.832]},
        "dense_this_run": {"extent_m": EXTENT_M, "n_tiles": len(tiles), "n_selected": n_sel, "n_resolved": n_res,
                           "n_unsolvable_skipped": n_unsolvable, "n_render_failed": n_render_fail,
                           "absolute_fix_ate_rms_m": round(abs_rms, 3), "aligned_ate_m": round(aligned_ate, 3),
                           "per_station_fix_error_min_max_mean_median_p90_m": [
                               round(float(errors_abs.min()), 3), round(float(errors_abs.max()), 3),
                               round(float(errors_abs.mean()), 3), round(float(np.median(errors_abs)), 3),
                               round(float(np.percentile(errors_abs, 90)), 3)]},
        "delta_absolute_fix_ate_m": round(abs_rms - 5.785, 3),
        "delta_aligned_ate_m": round(aligned_ate - 5.646, 3),
        "verdict_rule": "ROBUST if |delta absolute-fix ATE| <= ~0.5 m; IMPROVES if the dense ATE is materially "
                        "tighter; DEGRADES if materially larger. Verdict is computed post-hoc from the deltas above.",
    },
    "comparison_single_scene": {
        "single_scene_artifact": "ezrassor_katwijk_articulation_parallax_2026-07-02.json",
        "single_scene": {"scene": "katwijk_part4_station50 (one 40 m scene)", "n_stations": 26,
                         "rtk_idx": "35..61", "absolute_fix_ate_rms_m": 4.778, "aligned_ate_m": 4.631,
                         "per_station_fix_error_min_max_mean_median_m": [0.596, 13.541, 3.631, 2.524]},
        "note": "the full traverse adds the earlier ~half of the path (idx 0..34) the single 40 m scene "
                "never covered; the single scene only saw idx 35..61.",
    },
    "interpretation": (
        "Absolute-fix ATE (%.3f m RMS) is the accuracy with which the standstill articulation-parallax cue "
        "recovers the rover's ABSOLUTE ground position, truth-free, across the WHOLE %.0f m Part4 traverse on "
        "REAL Katwijk AHN 0.5 m terrain geometry from the real 8-cam rig, tiled into %d local scenes and "
        "reassembled into one ENU frame. Per-station errors span %.3f-%.3f m. GEOMETRIC-cue result on real "
        "terrain shape, NOT a real-image VO result: sub-0.5 m camera texture is procedural Godot infill, so "
        "this does not close the real-LocCam gap."
        % (abs_rms, PATH_LEN, len(tiles), float(errors_abs.min()), float(errors_abs.max()))),
}
os.makedirs(ARTIFACT_DIR, exist_ok=True)
json.dump(out, open(ARTIFACT, "w"), indent=2)
print(f"\nwrote artifact: {ARTIFACT}")

# --- robustness verdict vs the committed 2-tile baseline (5.785 abs / 5.646 aligned) ----------------
BASE_ABS, BASE_ALN = 5.785, 5.646
d_abs = abs_rms - BASE_ABS
if abs(d_abs) <= 0.5:
    VERDICT = f"ROBUST (dense absolute-fix ATE {abs_rms:.3f} m vs baseline {BASE_ABS} m; delta {d_abs:+.3f} m, within +-0.5 m)"
elif d_abs < 0:
    VERDICT = f"IMPROVES (dense absolute-fix ATE {abs_rms:.3f} m vs baseline {BASE_ABS} m; delta {d_abs:+.3f} m, tighter)"
else:
    VERDICT = f"DEGRADES (dense absolute-fix ATE {abs_rms:.3f} m vs baseline {BASE_ABS} m; delta {d_abs:+.3f} m, larger)"
print(f"\n=== ROBUSTNESS VERDICT vs 2-tile baseline ===\n{VERDICT}")
print(f"aligned: dense {aligned_ate:.3f} m vs baseline {BASE_ALN} m (delta {aligned_ate-BASE_ALN:+.3f} m)")

readme = f"""# EZ-RASSOR on real Katwijk -- FULL-TRAVERSE DENSE-TILING articulation-parallax absolute-fix (2026-07-02)

**{HONESTY}**

The EZ-RASSOR/IPEx 8-camera rig was rendered at the {n_res} REAL Part4 RTK poses (of {n_sel} moving stations
selected) spanning the WHOLE ~{PATH_LEN:.0f} m Part4 traverse. Because the traverse (ENU bbox ~40 x 63 m,
diagonal ~74 m) is longer than one 40 m scene and the sidecar far-plane is hardcoded 100 m, the trajectory
was TILED into **{len(tiles)} overlapping {EXTENT_M:.0f} m local scenes** (bbox-segmented, midpoint-centred so
every assigned station clears the rover-patch margin by >= {BUF_M:.0f} m; each rover-to-farthest-terrain
distance <= ~52 m, safely inside the far-plane). Each tile is a real AHN 0.5 m DTM crop, ENU-pinned at the
first RTK fix, built by the milestone-1 ingest (`KatwijkAhnDem` -> `dem_to_base` -> `save_scene`).

At each pose the rig rendered a two-posture chassis-lift A/B pair (TRANSIT lift 0.0 -> MEERKAT lift {DH:.4f} m),
and `articulation_bridge.localize_on_render_pair` recovered an ABSOLUTE ground-position fix truth-free
(block-match vertical parallax -> range = fx*dh/dv -> DEM-raycast landmark -> RANSAC trilateration). Each
tile's scene-local fix was translated back to the single first-fix ENU frame (add the tile's `world_min`),
so all {n_res} fixes and the RTK truth live in ONE consistent frame before scoring.

- **Per-station absolute fix error (vs rendered/snapped RTK):** {agg['per_station_fix_error_vs_rendered_m']['min']}-{agg['per_station_fix_error_vs_rendered_m']['max']} m (median {agg['per_station_fix_error_vs_rendered_m']['median']} m, p90 {agg['per_station_fix_error_vs_rendered_m']['p90']} m).
- **Full-traverse absolute-fix ATE (RMS, no alignment):** {abs_rms:.3f} m -- absolute-position accuracy of the parallax cue over the whole traverse.
- **Full-traverse aligned ATE (Umeyama):** {aligned_ate:.3f} m -- trajectory-shape consistency after a best rigid alignment.
- **RTK->grid snap:** median {agg['rtk_snap_offset_m']['median']} m, max {agg['rtk_snap_offset_m']['max']} m (truth discretization from the sidecar's integer rover-rc, <= half a cell diagonal ~0.354 m).
- **Tiling:** {len(tiles)} tiles; resolved {n_res}/{n_sel} ({n_render_fail} render-fail, {n_unsolvable} unsolvable-skipped, not fabricated).

## Robustness stress test: dense ({EXTENT_M:.0f} m, {len(tiles)} tiles) vs the 2-tile 50 m baseline

This run is a like-for-like **robustness stress test** of the committed 2-tile full-traverse result
(`ezrassor_katwijk_fulltraverse_articulation_parallax_2026-07-02.json`, commit 9913eb5, absolute-fix ATE
**5.785 m** / aligned **5.646 m**, 56/58 resolved, 2 tiles @ 50 m). The estimator, render pipeline, station
selection, and {THIN_M} m thinning are **identical**; ONLY the tile extent changed (50 m -> {EXTENT_M:.0f} m,
{len(tiles)} tiles), so each station sits more centred inside a tighter scene.

| | baseline (2 tiles, 50 m) | dense ({len(tiles)} tiles, {EXTENT_M:.0f} m) | delta |
|---|---|---|---|
| absolute-fix ATE (RMS) | 5.785 m | {abs_rms:.3f} m | {abs_rms-5.785:+.3f} m |
| aligned ATE (Umeyama) | 5.646 m | {aligned_ate:.3f} m | {aligned_ate-5.646:+.3f} m |
| resolved / selected | 56 / 58 | {n_res} / {n_sel} | |
| unsolvable-skipped | 2 | {n_unsolvable} | |
| per-station mean / median / p90 | 4.815 / 4.103 / 8.832 m | {agg['per_station_fix_error_vs_rendered_m']['mean']} / {agg['per_station_fix_error_vs_rendered_m']['median']} / {agg['per_station_fix_error_vs_rendered_m']['p90']} m | |

**VERDICT: {VERDICT}**

The absolute-fix ATE is the truth-free absolute-position accuracy of the standstill articulation-parallax
GEOMETRIC cue. The parallax range solve (`range = fx*dh/dv` -> DEM-raycast landmark -> RANSAC trilateration)
depends on the rig geometry and the local DEM shape around each station, NOT on where the tile's edges fall,
so the ATE should be largely invariant to tiling granularity if the pipeline is sound.

**vs the single 40 m scene** (`ezrassor_katwijk_articulation_parallax_2026-07-02.json`, 26 stations idx 35..61):
absolute-fix ATE 4.778 m / aligned 4.631 m -- covered only the later ~half; both full-traverse runs extend
coverage to idx 0..61 and score the reassembled multi-tile trajectory end to end.

**What the number means:** how accurately the standstill articulation-parallax GEOMETRIC cue localizes the
rover's absolute position over the FULL Katwijk traverse, from the real rig, rendered-sim. It is NOT a
real-image match and does NOT close the real-LocCam VO gap (all sub-0.5 m texture is procedural infill).

Artifact: `ezrassor_katwijk_fulltraverse_articulation_parallax_2026-07-02.json` (tiling plan, per-station
errors, commands, reused-vs-written). Estimator + ingest reused verbatim; only the full-track selection, the
tiling plan, the per-tile scene parametrization, and the ONE-frame assembly + scoring were written here.
"""
open(README, "w").write(readme)
print(f"wrote README: {README}")
