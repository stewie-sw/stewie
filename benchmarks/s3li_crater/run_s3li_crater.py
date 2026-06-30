"""STEWIE estimator benchmark runner: SuperPoint+LightGlue stereo VO -> DEM-anchoring on the REAL DLR S3LI
``s3li_crater`` Mt-Etna traverse, scored vs RTK ground truth with evo (reproduces arXiv:2603.17229's
VO -> VO+DEM-anchoring result on real data).

Estimation (VO + DEM anchoring) NEVER reads GT; GT is loaded only for time-sync + scoring, after each
estimate is frozen to disk. The reusable core is :mod:`dart.s3li_capstone`; this is the CLI wrapper.

Run from the repo root::

    .venv/bin/python benchmarks/s3li_crater/run_s3li_crater.py            # use cached VO npz
    .venv/bin/python benchmarks/s3li_crater/run_s3li_crater.py --rerun-vo # re-run + re-freeze VO
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from freeze_vo import run_freeze  # noqa: E402  (sibling module under benchmarks/s3li_crater/)

from dart.s3li_capstone import (  # noqa: E402
    axis_error_decompose,
    estimate_and_freeze,
    score,
    time_offset_s,
)
from dart.s3li_dem import DEM_SOURCE, S3liDem  # noqa: E402
from dart.s3li_reader import S3liReader  # noqa: E402

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
VALIDATION_DIR = "/mnt/projects/stewie/code/stewie/eval/validation"
FIG_DIR = os.path.join(VALIDATION_DIR, "figures", "s3li_crater_2026-06-28")


def _evo_version() -> str:
    import evo
    return getattr(evo, "__version__", "unknown")


def _read_poison_attestation() -> dict:
    p = os.path.join(THIS_DIR, "poison_attestation.json")
    if os.path.isfile(p):
        with open(p) as fh:
            return json.load(fh)
    return {"status": "run benchmarks/s3li_crater/test_s3li_firewall.py to write poison_attestation.json"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stride", type=int, default=3)
    ap.add_argument("--rerun-vo", action="store_true")
    ap.add_argument("--sigma-vo-m", type=float, default=0.05)
    ap.add_argument("--sigma-dem-m", type=float, default=2.0)
    ap.add_argument("--sigma-prior-m", type=float, default=0.5)
    ap.add_argument("--anchor-every", type=int, default=10)
    ap.add_argument("--max-diff-s", type=float, default=0.06)
    args = ap.parse_args()
    os.makedirs(FIG_DIR, exist_ok=True)

    npz_path = os.path.join(THIS_DIR, f"vo_cam_stride{args.stride}.npz")
    if args.rerun_vo or not os.path.isfile(npz_path):
        run_freeze(args.stride)
    with open(os.path.join(THIS_DIR, f"vo_cam_stride{args.stride}_meta.json")) as fh:
        vo_meta = json.load(fh)

    dem = S3liDem()
    d = np.load(npz_path)
    ts_ns = d["ts_ns"].astype(np.int64)
    xyz_cam = d["xyz_cam"].astype(float)

    # ---- estimation (NO GT) -> freeze ----
    est = estimate_and_freeze(xyz_cam, ts_ns, dem, THIS_DIR, sigma_vo_m=args.sigma_vo_m,
                              sigma_dem_m=args.sigma_dem_m, sigma_prior_m=args.sigma_prior_m,
                              anchor_every=args.anchor_every)
    print(f"[run] yaw {est['yaw']['yaw_deg']:.1f} deg (VO-vs-DEM corr {est['yaw']['peak_corr']:.3f}); "
          f"DEM correction mean |dz| {est['anchor_diag']['mean_abs_height_correction_m']:.2f} m, "
          f"mean |dxy| {est['anchor_diag']['mean_abs_horizontal_correction_m']:.2f} m", flush=True)

    # ---- GT (scoring only, after the estimates are frozen) ----
    reader = S3liReader()
    gt_ts_ns, gt_enu = reader.gt_enu(dem=dem)
    align = reader.time_alignment()
    off = time_offset_s(ts_ns, est["enu_vo"], gt_ts_ns, gt_enu)
    gt_ts_aligned_s = (gt_ts_ns.astype(float) + off["offset_s"] * 1e9) / 1e9
    print(f"[run] time offset {off['offset_s']:+.2f}s (speed xcorr peak {off['peak_corr']:.3f})", flush=True)

    vo_cam_tum = os.path.join(THIS_DIR, f"vo_cam_stride{args.stride}.tum")
    res_vo = score(vo_cam_tum, gt_enu, gt_ts_aligned_s, FIG_DIR, "s3li_crater_vo", max_diff_s=args.max_diff_s)
    res_vo_enu = score(est["vo_enu_tum"], gt_enu, gt_ts_aligned_s, FIG_DIR, "s3li_crater_vo_enu",
                       max_diff_s=args.max_diff_s)
    res_anc = score(est["anchored_tum"], gt_enu, gt_ts_aligned_s, FIG_DIR, "s3li_crater_dem_anchored",
                    max_diff_s=args.max_diff_s)

    ate_vo_se3 = res_vo["metrics"]["ate_aligned_se3_m"]["rmse"]
    ate_vo_enu_se3 = res_vo_enu["metrics"]["ate_aligned_se3_m"]["rmse"]
    ate_anc_se3 = res_anc["metrics"]["ate_aligned_se3_m"]["rmse"]
    drift_reduction_pct = 100.0 * (ate_vo_enu_se3 - ate_anc_se3) / ate_vo_enu_se3
    dec_vo = axis_error_decompose(est["vo_enu_tum"], gt_enu, gt_ts_aligned_s, max_diff_s=args.max_diff_s)
    dec_anc = axis_error_decompose(est["anchored_tum"], gt_enu, gt_ts_aligned_s, max_diff_s=args.max_diff_s)

    artifact = {
        "experiment": "S3LI s3li_crater SuperPoint+LightGlue stereo VO -> DEM-anchoring (arXiv:2603.17229)",
        "date": str(date.today()),
        "data": {"bag": reader.bag_path, "gt": reader.gt_path, "dem_source": DEM_SOURCE,
                 "stride": args.stride, "n_frames": vo_meta["n_frames"],
                 "duration_s": vo_meta["duration_s"], "n_valid_vo_steps": vo_meta["n_valid"],
                 "vo_runtime_s": vo_meta["vo_runtime_s"], "median_pnp_inliers": vo_meta["median_pnp_inliers"],
                 "median_stereo_points": vo_meta["median_stereo_points"]},
        "time_sync": {"method": "VO-vs-GT translation-speed cross-correlation (constant offset, 0.2 s grid, +/-30 s)",
                      "offset_s": off["offset_s"], "peak_corr": off["peak_corr"],
                      "reader_utc_overlap_offset_s": align.offset_ns / 1e9,
                      "reader_windows_overlap": align.overlaps},
        "registration": {"frame": "DEM local ENU (S3liDem declared origin)",
                         "declared_attitude": "level camera (roll=pitch=0)",
                         "heading_source": "firewall-clean VO-vertical-vs-DEM-height yaw search (NOT GT)",
                         "yaw_deg": est["yaw"]["yaw_deg"], "yaw_vo_dem_corr": est["yaw"]["peak_corr"],
                         "z0_m": est["z0_m"]},
        "ate_vo": {"frame": "camera (full resolution)", "se3": res_vo["metrics"]["ate_aligned_se3_m"],
                   "sim3": res_vo["metrics"]["ate_aligned_sim3_m"], "sim3_scale": res_vo["metrics"]["sim3_scale"],
                   "rpe_trans_m": res_vo["metrics"]["rpe_trans_m"], "rpe_kind": res_vo["metrics"]["rpe_kind"],
                   "n_pose_pairs": res_vo["metrics"]["n_pose_pairs"]},
        "ate_vo_enu": {"frame": "DEM ENU (registered VO, same nodes as anchored)",
                       "se3": res_vo_enu["metrics"]["ate_aligned_se3_m"],
                       "sim3": res_vo_enu["metrics"]["ate_aligned_sim3_m"],
                       "sim3_scale": res_vo_enu["metrics"]["sim3_scale"],
                       "se3_axis_decompose_m": dec_vo},
        "ate_anchored": {"frame": "DEM ENU (DEM height-normal anchored)",
                         "se3": res_anc["metrics"]["ate_aligned_se3_m"],
                         "sim3": res_anc["metrics"]["ate_aligned_sim3_m"],
                         "sim3_scale": res_anc["metrics"]["sim3_scale"],
                         "se3_axis_decompose_m": dec_anc, "anchor_diag": est["anchor_diag"],
                         "anchor_count": len(est["anchor_indices"]),
                         "solver": {"sigma_vo_m": args.sigma_vo_m, "sigma_dem_m": args.sigma_dem_m,
                                    "sigma_prior_m": args.sigma_prior_m, "anchor_every": args.anchor_every}},
        "drift_reduction_pct_se3_vs_vo_enu": drift_reduction_pct,
        "poison_test": _read_poison_attestation(),
        "evo_version": _evo_version(),
        "figures_dir": FIG_DIR,
        "estimates": {"vo_cam_tum": vo_cam_tum, "vo_enu_tum": est["vo_enu_tum"],
                      "anchored_tum": est["anchored_tum"]},
    }
    out_json = os.path.join(VALIDATION_DIR, "s3li_crater_vo_dem_anchor_2026-06-28.json")
    with open(out_json, "w") as fh:
        json.dump(artifact, fh, indent=2)

    print("\n================ S3LI s3li_crater VO -> DEM-anchoring ================")
    print(f" stride {args.stride}  frames {vo_meta['n_frames']}  duration {vo_meta['duration_s']:.0f}s  "
          f"VO runtime {vo_meta['vo_runtime_s']:.0f}s")
    print(f" time offset {off['offset_s']:+.2f}s (xcorr {off['peak_corr']:.3f})")
    print(f" ATE_vo (cam)      SE3 {ate_vo_se3:8.3f} m | Sim3 {res_vo['metrics']['ate_aligned_sim3_m']['rmse']:8.3f} m "
          f"(scale {res_vo['metrics']['sim3_scale']:.4f})")
    print(f" ATE_vo (ENU)      SE3 {ate_vo_enu_se3:8.3f} m | Sim3 {res_vo_enu['metrics']['ate_aligned_sim3_m']['rmse']:8.3f} m")
    print(f" ATE_anchored(ENU) SE3 {ate_anc_se3:8.3f} m | Sim3 {res_anc['metrics']['ate_aligned_sim3_m']['rmse']:8.3f} m")
    print(f" drift reduction (SE3, vs VO-ENU): {drift_reduction_pct:+.1f}%")
    print(f" VO-ENU  aligned err: horiz {dec_vo['rms_horizontal_m']:.2f} m | vert {dec_vo['rms_vertical_m']:.2f} m")
    print(f" anchored aligned err: horiz {dec_anc['rms_horizontal_m']:.2f} m | vert {dec_anc['rms_vertical_m']:.2f} m")
    print(f" artifact -> {out_json}")


if __name__ == "__main__":
    main()
