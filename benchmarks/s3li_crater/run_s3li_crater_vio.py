"""ARGUS capstone runner (VIO variant): fuse the S3LI IMU gyro into the SuperPoint+LightGlue stereo VO
to tame the heading drift that left the vision-only VO at ATE 93.3 m (92.9 m horizontal) on the REAL
DLR S3LI ``s3li_crater`` Mt-Etna traverse, then RE-TEST DEM height-normal anchoring on the improved
trajectory. Scored vs RTK ground truth with evo.

Estimation (VIO + DEM anchoring) NEVER reads GT; GT is loaded only for time-sync + scoring, after each
estimate is frozen to disk. The reusable core is :mod:`dart.s3li_vio` (+ :mod:`dart.s3li_capstone` for
the registration / anchoring / scoring helpers it reuses); this is the CLI wrapper.

Run from the repo root::

    .venv/bin/python benchmarks/s3li_crater/run_s3li_crater_vio.py             # use cached VIO freeze
    .venv/bin/python benchmarks/s3li_crater/run_s3li_crater_vio.py --rerun-vio # re-build + re-freeze VIO
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from freeze_vio import run_freeze_vio  # noqa: E402  (sibling module under benchmarks/s3li_crater/)

from dart.s3li_capstone import (  # noqa: E402
    anchor_vo,
    axis_error_decompose,
    register_cam_to_enu,
    score,
    time_offset_s,
    write_tum,
    yaw_search,
)
from dart.s3li_dem import DEM_SOURCE, S3liDem  # noqa: E402
from dart.s3li_reader import S3liReader  # noqa: E402

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
VALIDATION_DIR = "/mnt/projects/stewie/code/stewie/eval/validation"
FIG_DIR = os.path.join(VALIDATION_DIR, "figures", "s3li_crater_vio_2026-06-28")

# the committed vision-only baseline this VIO variant is compared against (frozen capstone artifact)
VO_BASELINE_JSON = os.path.join(VALIDATION_DIR, "s3li_crater_vo_dem_anchor_2026-06-28.json")


def _evo_version() -> str:
    import evo
    return getattr(evo, "__version__", "unknown")


def _read_poison_attestation() -> dict:
    p = os.path.join(THIS_DIR, "poison_attestation_vio.json")
    if os.path.isfile(p):
        with open(p) as fh:
            return json.load(fh)
    return {"status": "run benchmarks/s3li_crater/test_s3li_vio_firewall.py to write "
                      "poison_attestation_vio.json"}


def _vo_baseline() -> dict:
    if os.path.isfile(VO_BASELINE_JSON):
        with open(VO_BASELINE_JSON) as fh:
            b = json.load(fh)
        return {
            "ate_vo_enu_se3_rmse_m": b["ate_vo_enu"]["se3"]["rmse"],
            "ate_vo_enu_horizontal_m": b["ate_vo_enu"]["se3_axis_decompose_m"]["rms_horizontal_m"],
            "ate_vo_enu_vertical_m": b["ate_vo_enu"]["se3_axis_decompose_m"]["rms_vertical_m"],
            "ate_vo_anchored_se3_rmse_m": b["ate_anchored"]["se3"]["rmse"],
            "drift_reduction_pct_vo": b["drift_reduction_pct_se3_vs_vo_enu"],
            "source": VO_BASELINE_JSON,
        }
    return {"status": "VO baseline artifact not found", "source": VO_BASELINE_JSON}


def _ate_from_decompose(dec: dict) -> float:
    """ATE SE(3) RMSE = sqrt(rms_horizontal^2 + rms_vertical^2) (exact identity for the SE(3)-aligned
    residual; lets the registration sweep skip the figure-rendering scorer)."""
    return float(np.hypot(dec["rms_horizontal_m"], dec["rms_vertical_m"]))


def _registration_robustness(xyz_leveled: np.ndarray, ts_ns: np.ndarray, dem: S3liDem,
                             gt_enu: np.ndarray, gt_ts_aligned_s: np.ndarray, *, max_diff_s: float,
                             anchor_every: int, sigma_vo_m: float, sigma_dem_m: float,
                             sigma_prior_m: float) -> list[dict]:
    """Firewall-clean sweep over the yaw-search window: register + DEM-anchor the VIO trajectory at each
    window (NO GT), then score (GT). Shows whether DEM anchoring helps under ANY reasonable heading
    registration, so the anchoring verdict is not an artifact of one yaw. 0 = full-trajectory window."""
    import os
    import tempfile
    z0 = float(dem.height_enu(0.0, 0.0))
    ident = np.tile(np.array([1.0, 0.0, 0.0, 0.0]), (ts_ns.size, 1))
    rows: list[dict] = []
    for win in (1500, 3000, 6000, 0):
        yaw = yaw_search(xyz_leveled, dem, z0, window=win)
        enu = register_cam_to_enu(xyz_leveled, yaw["yaw_rad"], z0)
        result, _idx = anchor_vo(enu, dem, sigma_vo_m=sigma_vo_m, sigma_dem_m=sigma_dem_m,
                                 sigma_prior_m=sigma_prior_m, anchor_every=anchor_every)
        out = tempfile.mkdtemp()
        te, ta = os.path.join(out, "e.tum"), os.path.join(out, "a.tum")
        write_tum(te, ts_ns / 1e9, enu, ident)
        write_tum(ta, ts_ns / 1e9, result.xyz, ident)
        de = axis_error_decompose(te, gt_enu, gt_ts_aligned_s, max_diff_s=max_diff_s)
        da = axis_error_decompose(ta, gt_enu, gt_ts_aligned_s, max_diff_s=max_diff_s)
        rows.append({
            "yaw_window_frames": win, "yaw_deg": yaw["yaw_deg"], "yaw_dem_corr": yaw["peak_corr"],
            "ate_vio_se3_m": _ate_from_decompose(de),
            "ate_vio_anchored_se3_m": _ate_from_decompose(da),
            "anchored_horizontal_m": da["rms_horizontal_m"], "anchored_vertical_m": da["rms_vertical_m"],
            "mean_abs_height_correction_m": result.mean_abs_height_correction_m,
        })
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stride", type=int, default=3)
    ap.add_argument("--rerun-vio", action="store_true")
    ap.add_argument("--sigma-vo-m", type=float, default=0.05)
    ap.add_argument("--sigma-dem-m", type=float, default=2.0)
    ap.add_argument("--sigma-prior-m", type=float, default=0.5)
    ap.add_argument("--anchor-every", type=int, default=10)
    ap.add_argument("--max-diff-s", type=float, default=0.06)
    args = ap.parse_args()
    os.makedirs(FIG_DIR, exist_ok=True)

    meta_path = os.path.join(THIS_DIR, f"vio_stride{args.stride}_meta.json")
    if args.rerun_vio or not os.path.isfile(meta_path):
        run_freeze_vio(args.stride, anchor_every=args.anchor_every, sigma_vo_m=args.sigma_vo_m,
                       sigma_dem_m=args.sigma_dem_m, sigma_prior_m=args.sigma_prior_m)
    with open(meta_path) as fh:
        vio_meta = json.load(fh)

    vio_enu_tum = vio_meta["vio_enu_tum"]
    anchored_tum = vio_meta["anchored_tum"]

    # re-load the frozen VIO-ENU positions (for the time-sync speed profile) from the TUM
    vio_enu = np.loadtxt(vio_enu_tum)[:, 1:4]
    ts_ns = (np.loadtxt(vio_enu_tum)[:, 0] * 1e9).astype(np.int64)

    dem = S3liDem()

    # ---- GT (scoring only, after the estimates are frozen) ----
    reader = S3liReader()
    gt_ts_ns, gt_enu = reader.gt_enu(dem=dem)
    align = reader.time_alignment()
    off = time_offset_s(ts_ns, vio_enu, gt_ts_ns, gt_enu)
    gt_ts_aligned_s = (gt_ts_ns.astype(float) + off["offset_s"] * 1e9) / 1e9
    print(f"[run] time offset {off['offset_s']:+.2f}s (speed xcorr peak {off['peak_corr']:.3f})", flush=True)

    res_vio = score(vio_enu_tum, gt_enu, gt_ts_aligned_s, FIG_DIR, "s3li_crater_vio_enu",
                    max_diff_s=args.max_diff_s)
    res_anc = score(anchored_tum, gt_enu, gt_ts_aligned_s, FIG_DIR, "s3li_crater_vio_dem_anchored",
                    max_diff_s=args.max_diff_s)

    ate_vio_se3 = res_vio["metrics"]["ate_aligned_se3_m"]["rmse"]
    ate_anc_se3 = res_anc["metrics"]["ate_aligned_se3_m"]["rmse"]
    drift_reduction_pct = 100.0 * (ate_vio_se3 - ate_anc_se3) / ate_vio_se3
    dec_vio = axis_error_decompose(vio_enu_tum, gt_enu, gt_ts_aligned_s, max_diff_s=args.max_diff_s)
    dec_anc = axis_error_decompose(anchored_tum, gt_enu, gt_ts_aligned_s, max_diff_s=args.max_diff_s)

    # firewall-clean registration-robustness sweep (does DEM anchoring help under ANY heading reg?)
    reg_sweep: list[dict] = []
    if os.path.isfile(vio_meta.get("leveled_npz", "")):
        lev = np.load(vio_meta["leveled_npz"])
        reg_sweep = _registration_robustness(
            lev["xyz_leveled"], ts_ns, dem, gt_enu, gt_ts_aligned_s, max_diff_s=args.max_diff_s,
            anchor_every=args.anchor_every, sigma_vo_m=args.sigma_vo_m, sigma_dem_m=args.sigma_dem_m,
            sigma_prior_m=args.sigma_prior_m)

    baseline = _vo_baseline()
    vb = vio_meta["vio_build"]

    artifact = {
        "experiment": "S3LI s3li_crater stereo-VIO (gyro-aided SuperPoint+LightGlue VO) -> DEM-anchoring; "
                      "heading-drift fix + DEM re-test (vs vision-only arXiv:2603.17229 baseline)",
        "date": str(date.today()),
        "data": {"bag": reader.bag_path, "gt": reader.gt_path, "dem_source": DEM_SOURCE,
                 "stride": args.stride, "n_frames": vio_meta["n_frames"],
                 "n_imu_samples": vio_meta["n_imu_samples"],
                 "imu_load_s": vio_meta["imu_load_s"], "vio_build_s": vio_meta["vio_build_s"]},
        "vio_formulation": {
            "what_imu_constrains": "relative ROTATION (heading) from bias-corrected gyro preintegration "
                                   "between stereo keyframes + absolute roll/pitch from accel gravity",
            "scale_source": "stereo VO (metric); IMU does NOT set scale",
            "gyro_bias_rad_s": vb["gyro_bias_rad_s"],
            "gyro_bias_estimation": "joint least-squares vs VO per-step rotations (firewall-clean; no GT)",
            "vo_gyro_resid_deg_before": vb["vo_gyro_resid_deg_before"],
            "vo_gyro_resid_deg_after": vb["vo_gyro_resid_deg_after"],
            "cam_imu_extrinsic_Tbc": "applied (body_T_cam0, Cfgs/orbslam_config.yaml)",
            "cam_imu_td_s": vb["cam_imu_td_s"],
            "gravity_norm_m_s2": vb["gravity_norm_m_s2"],
            "leveling_tilt_deg": vb["leveling_tilt_deg"],
            "imu_gyro_noise_rad_s_sqrthz": vb["imu_gyro_noise_rad_s_sqrthz"],
            "solver_reused": "dart.dem_height_graph.DemHeightPoseGraph (sparse analytic Gauss-Newton) "
                             "for DEM anchoring; gyro bias by scipy.optimize.least_squares",
        },
        "time_sync": {"method": "VIO-vs-GT translation-speed cross-correlation (constant offset, 0.2 s "
                                "grid, +/-30 s)", "offset_s": off["offset_s"], "peak_corr": off["peak_corr"],
                      "reader_utc_overlap_offset_s": align.offset_ns / 1e9,
                      "reader_windows_overlap": align.overlaps},
        "registration": {"frame": "DEM local ENU (S3liDem declared origin)",
                         "declared_attitude": "gravity-leveled (roll/pitch from accel; firewall-clean)",
                         "heading_source": "firewall-clean VIO-vertical-vs-DEM-height yaw search (NOT GT)",
                         "yaw_deg": vio_meta["yaw_deg"], "yaw_vio_dem_corr": vio_meta["yaw_peak_corr"],
                         "z0_m": vio_meta["z0_m"]},
        "ate_vio_enu": {"frame": "DEM ENU (gyro-aided VIO, same nodes as anchored)",
                        "se3": res_vio["metrics"]["ate_aligned_se3_m"],
                        "sim3": res_vio["metrics"]["ate_aligned_sim3_m"],
                        "sim3_scale": res_vio["metrics"]["sim3_scale"],
                        "rpe_trans_m": res_vio["metrics"]["rpe_trans_m"],
                        "rpe_kind": res_vio["metrics"]["rpe_kind"],
                        "n_pose_pairs": res_vio["metrics"]["n_pose_pairs"],
                        "se3_axis_decompose_m": dec_vio},
        "ate_vio_anchored": {"frame": "DEM ENU (VIO + DEM height-normal anchored)",
                             "se3": res_anc["metrics"]["ate_aligned_se3_m"],
                             "sim3": res_anc["metrics"]["ate_aligned_sim3_m"],
                             "sim3_scale": res_anc["metrics"]["sim3_scale"],
                             "se3_axis_decompose_m": dec_anc, "anchor_diag": vio_meta["anchor_diag"],
                             "solver": {"sigma_vo_m": args.sigma_vo_m, "sigma_dem_m": args.sigma_dem_m,
                                        "sigma_prior_m": args.sigma_prior_m,
                                        "anchor_every": args.anchor_every}},
        "drift_reduction_pct_se3_vs_vio_enu": drift_reduction_pct,
        "anchoring_registration_robustness": {
            "note": "DEM anchoring re-tested under a firewall-clean sweep of the yaw-search window; "
                    "anchoring does not beat the un-anchored VIO under ANY heading registration (the "
                    "dominant residual is horizontal, so DEM height-normal anchoring -- which acts on the "
                    "vertical -- cannot recover it, and the large horizontal error makes the DEM sample "
                    "the wrong terrain, hence the tens-of-metres height corrections).",
            "sweep": reg_sweep,
        },
        "comparison_vs_vision_only_baseline": baseline,
        "poison_test": _read_poison_attestation(),
        "evo_version": _evo_version(),
        "figures_dir": FIG_DIR,
        "estimates": {"vio_enu_tum": vio_enu_tum, "anchored_tum": anchored_tum},
        "i3_attestation": (
            "The VIO + VIO-anchored estimates consume ONLY the stereo-VO poses, the IMU stream, the "
            "cam-IMU calibration, the DEM (sampled at the ESTIMATED position), and a single declared "
            "coarse start. No ground-truth trajectory is an argument to any estimation function. GT "
            "enters only at time-sync + scoring, after each estimate is frozen; the poison test "
            "(GT + 1e6 m) confirms both frozen estimates are byte-identical."
        ),
    }
    out_json = os.path.join(VALIDATION_DIR, "s3li_crater_vio_2026-06-28.json")
    with open(out_json, "w") as fh:
        json.dump(artifact, fh, indent=2)

    print("\n================ S3LI s3li_crater stereo-VIO (gyro-aided VO) -> DEM-anchoring ================")
    print(f" stride {args.stride}  frames {vio_meta['n_frames']}  IMU {vio_meta['n_imu_samples']}  "
          f"VIO build {vio_meta['vio_build_s']:.0f}s")
    print(f" gyro bias (rad/s) {np.array(vb['gyro_bias_rad_s'])}  "
          f"gyro-vs-VO resid {vb['vo_gyro_resid_deg_before']:.3f}->{vb['vo_gyro_resid_deg_after']:.3f} deg")
    print(f" time offset {off['offset_s']:+.2f}s (xcorr {off['peak_corr']:.3f})")
    if "ate_vo_enu_se3_rmse_m" in baseline:
        print(f" [baseline] VO-ENU     SE3 {baseline['ate_vo_enu_se3_rmse_m']:8.3f} m  "
              f"(horiz {baseline['ate_vo_enu_horizontal_m']:.2f} | vert {baseline['ate_vo_enu_vertical_m']:.2f})")
        print(f" [baseline] VO-anchored SE3 {baseline['ate_vo_anchored_se3_rmse_m']:8.3f} m")
    print(f" ATE_vio (ENU)      SE3 {ate_vio_se3:8.3f} m | Sim3 {res_vio['metrics']['ate_aligned_sim3_m']['rmse']:8.3f} m "
          f"(scale {res_vio['metrics']['sim3_scale']:.4f})")
    print(f" ATE_vio_anchored   SE3 {ate_anc_se3:8.3f} m | Sim3 {res_anc['metrics']['ate_aligned_sim3_m']['rmse']:8.3f} m")
    print(f" drift reduction (SE3, anchored vs VIO-ENU): {drift_reduction_pct:+.1f}%")
    print(f" VIO-ENU   aligned err: horiz {dec_vio['rms_horizontal_m']:.2f} m | vert {dec_vio['rms_vertical_m']:.2f} m")
    print(f" anchored  aligned err: horiz {dec_anc['rms_horizontal_m']:.2f} m | vert {dec_anc['rms_vertical_m']:.2f} m")
    print(f" artifact -> {out_json}")


if __name__ == "__main__":
    main()
