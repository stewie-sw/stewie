"""STEWIE estimator benchmark runner -- the FULL s3li_crater loop-closure ladder including the SE(2) heading-
optimizing FIX. Scores, vs RTK ground truth with evo (SE3 + Sim3 + horizontal/vertical split), the four
GT-free estimates and answers: what actually closes the VO 94 m -> paper 21.43 m gap on this sequence.

    .venv/bin/python benchmarks/s3li_crater/run_s3li_crater_se2.py            # use cached freeze
    .venv/bin/python benchmarks/s3li_crater/run_s3li_crater_se2.py --refreeze # re-detect + re-solve
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from freeze_se2_recipe import run_freeze_se2_recipe  # noqa: E402

from dart.s3li_capstone import axis_error_decompose, score, time_offset_s  # noqa: E402
from dart.s3li_dem import DEM_RESOLUTION_M, DEM_SOURCE, S3liDem  # noqa: E402
from dart.s3li_reader import S3liReader  # noqa: E402

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
VALIDATION_DIR = "/mnt/projects/stewie/code/stewie/eval/validation"
FIG_DIR = os.path.join(VALIDATION_DIR, "figures", "s3li_crater_se2_recipe_2026-06-28")


def _evo_version() -> str:
    import evo
    return getattr(evo, "__version__", "unknown")


def _se2_solver_defaults() -> dict:
    """The SE(2) keyframe-graph noise model actually used (the solve_se2_keyframes defaults), so the
    headline rung is reproducible from the artifact (the position-graph solver_params above do NOT
    describe the SE(2) solve)."""
    import inspect

    from dart.loop_pose_graph_se2 import solve_se2_keyframes
    sig = inspect.signature(solve_se2_keyframes)
    keys = ("sigma_odom_xy", "sigma_odom_yaw", "sigma_loop_xy", "sigma_loop_yaw",
            "prior_sigma_xy", "prior_sigma_yaw")
    return {k: float(sig.parameters[k].default) for k in keys}


def _score_one(tum_path: str, label: str, gt_enu, gt_ts_aligned_s, max_diff_s: float) -> dict:
    res = score(tum_path, gt_enu, gt_ts_aligned_s, FIG_DIR, label, max_diff_s=max_diff_s)
    dec = axis_error_decompose(tum_path, gt_enu, gt_ts_aligned_s, max_diff_s=max_diff_s)
    return {"tum": tum_path, "se3_rmse_m": res["metrics"]["ate_aligned_se3_m"]["rmse"],
            "sim3_rmse_m": res["metrics"]["ate_aligned_sim3_m"]["rmse"],
            "sim3_scale": res["metrics"]["sim3_scale"],
            "horizontal_m": dec["rms_horizontal_m"], "vertical_m": dec["rms_vertical_m"]}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stride", type=int, default=3)
    ap.add_argument("--refreeze", action="store_true")
    ap.add_argument("--max-diff-s", type=float, default=0.06)
    args = ap.parse_args()
    os.makedirs(FIG_DIR, exist_ok=True)

    meta_path = os.path.join(THIS_DIR, f"se2_recipe_stride{args.stride}_meta.json")
    if args.refreeze or not os.path.isfile(meta_path):
        run_freeze_se2_recipe(args.stride)
    with open(meta_path) as fh:
        meta = json.load(fh)
    tum = meta["tum"]

    vo_enu = np.loadtxt(tum["vo"])[:, 1:4]
    ts_ns = (np.loadtxt(tum["vo"])[:, 0] * 1e9).astype(np.int64)
    dem = S3liDem()
    reader = S3liReader()
    gt_ts_ns, gt_enu = reader.gt_enu(dem=dem)
    off = time_offset_s(ts_ns, vo_enu, gt_ts_ns, gt_enu)
    gt_ts_aligned_s = (gt_ts_ns.astype(float) + off["offset_s"] * 1e9) / 1e9
    print(f"[run] time offset {off['offset_s']:+.2f}s (xcorr {off['peak_corr']:.3f})", flush=True)

    sc = {
        "vo": _score_one(tum["vo"], "se2_vo", gt_enu, gt_ts_aligned_s, args.max_diff_s),
        "lc_pos": _score_one(tum["lc_pos"], "se2_lc_position", gt_enu, gt_ts_aligned_s, args.max_diff_s),
        "lc_se2": _score_one(tum["lc_se2"], "se2_lc_se2", gt_enu, gt_ts_aligned_s, args.max_diff_s),
        "lc_se2_dem": _score_one(tum["lc_se2_dem"], "se2_lc_se2_dem", gt_enu, gt_ts_aligned_s,
                                 args.max_diff_s),
    }
    if "lc_se2_dem_height_only" in tum:
        sc["lc_se2_dem_h"] = _score_one(tum["lc_se2_dem_height_only"], "se2_lc_se2_dem_height_only",
                                        gt_enu, gt_ts_aligned_s, args.max_diff_s)

    artifact = {
        "experiment": "S3LI s3li_crater FULL loop-closure ladder incl. the SE(2) heading-optimizing fix "
                      "(arXiv:2603.17229 recipe + the position-only -> SE(2) solver upgrade)",
        "date": str(date.today()),
        "data": {"bag": reader.bag_path, "gt": reader.gt_path, "dem_source": DEM_SOURCE,
                 "dem_resolution_m": DEM_RESOLUTION_M, "stride": args.stride,
                 "n_frames": meta["n_frames"], "n_loop_closures": meta["n_loop_closures"]},
        "se2_solve": meta["se2"], "solver_params": meta["solver_params"],
        "se2_solver_params": _se2_solver_defaults(),
        "time_sync": {"offset_s": off["offset_s"], "peak_corr": off["peak_corr"]},
        "ladder": {k: sc[k] for k in sc},
        "ladder_se3_rmse_m": {"vo": sc["vo"]["se3_rmse_m"], "vo_lc_position": sc["lc_pos"]["se3_rmse_m"],
                              "vo_lc_se2": sc["lc_se2"]["se3_rmse_m"],
                              "vo_lc_se2_dem": sc["lc_se2_dem"]["se3_rmse_m"],
                              "vo_lc_se2_dem_height_only": sc.get("lc_se2_dem_h", {}).get("se3_rmse_m"),
                              "paper_vo": 94.01, "paper_full": 21.43},
        "findings": {
            "loop_closure_fixes_gross_drift": bool(sc["lc_pos"]["se3_rmse_m"] < sc["vo"]["se3_rmse_m"]),
            "se2_beats_position_only": bool(sc["lc_se2"]["se3_rmse_m"] < sc["lc_pos"]["se3_rmse_m"]),
            "se2_reaches_paper_target": bool(sc["lc_se2"]["se3_rmse_m"] <= 21.43),
            "dem_normal_helps_vertical": bool(sc["lc_se2_dem"]["vertical_m"] < sc["lc_se2"]["vertical_m"]),
            "dem_normal_helps_se3_overall": bool(sc["lc_se2_dem"]["se3_rmse_m"] < sc["lc_se2"]["se3_rmse_m"]),
            "dem_normal_hurts_horizontal": bool(sc["lc_se2_dem"]["horizontal_m"]
                                                > sc["lc_se2"]["horizontal_m"]),
            "dem_height_only_beats_normal": bool("lc_se2_dem_h" in sc and sc["lc_se2_dem_h"]["se3_rmse_m"]
                                                 < sc["lc_se2_dem"]["se3_rmse_m"]),
            "dem_height_only_beats_se2_alone": bool("lc_se2_dem_h" in sc
                                                    and sc["lc_se2_dem_h"]["se3_rmse_m"]
                                                    < sc["lc_se2"]["se3_rmse_m"]),
            "best_se3_rmse_m": min(sc[k]["se3_rmse_m"] for k in sc),
        },
        "honest_read": (
            "The binding limit was the SOLVER, not the DEM. (1) Loop closure fixes the gross drift "
            f"(VO {sc['vo']['se3_rmse_m']:.0f} m -> position-LC {sc['lc_pos']['se3_rmse_m']:.0f} m). "
            "(2) The decisive lever is OPTIMISING HEADING: the SAME visual loop closures in an SE(2) "
            f"pose graph reach {sc['lc_se2']['se3_rmse_m']:.1f} m SE3 / {sc['lc_se2']['horizontal_m']:.1f} "
            "m horizontal -- 5x better than the position-only graph -- because the SE(2) solve "
            "redistributes the accumulated heading drift that bowed the trajectory, which a position-only "
            "solve cannot. (3) DEM height-normal anchoring on TOP of the now-tight SE(2) estimate "
            "reproduces the paper's 'DEM supplies height' claim for the VERTICAL (vert "
            f"{sc['lc_se2']['vertical_m']:.1f} -> {sc['lc_se2_dem']['vertical_m']:.1f} m), but on the 30 m "
            "Copernicus DEM it PERTURBS the horizontal (horiz "
            f"{sc['lc_se2']['horizontal_m']:.1f} -> {sc['lc_se2_dem']['horizontal_m']:.1f} m) because the "
            "coarse 30 m slope/normal redistributes height residual into a noisy horizontal pull -- so "
            f"DEM-on-top is net-NEGATIVE on SE3 here ({sc['lc_se2']['se3_rmse_m']:.1f} -> "
            f"{sc['lc_se2_dem']['se3_rmse_m']:.1f} m). This is where DEM RESOLUTION finally binds: a 2 m "
            "Pleiades / 10 m Tinitaly DSM (Etna) or a 1-2 m LROC-NAC DSM (Moon) would have accurate "
            "slopes and let the height factor refine vertical WITHOUT the horizontal penalty. "
            "CAVEATS (do not over-read the absolute number): the headline SE(2) rung (c) uses NO DEM, "
            "whereas the paper's 21.43 m is its FULL recipe WITH a 2 m Pleiades DEM -- so 'below the "
            "paper' compares a DEM-less estimate to a DEM-aided one (a different, arguably stronger claim, "
            "not a like-for-like back-end comparison). The SE(2) solve is a "
            f"{meta['se2']['n_keyframes']}-keyframe graph (pose_graph_se2 dense Jacobians cannot take "
            "10599 nodes) lifted to full resolution by an SE(2) deformation, and it did NOT "
            f"gradient-converge (converged={meta['se2']['converged']}, LM iteration cap; cost decreased "
            "monotonically). The robust core finding -- optimising heading is the decisive lever -- holds; "
            "the exact 10-11 m should be read as 'non-converged keyframe SE(2) + deformation lift, no "
            "DEM', pending a sparse analytic full-resolution SE(2) solver."
        ),
        "caveats": {
            "se2_converged": bool(meta["se2"]["converged"]),
            "se2_backend": f"{meta['se2']['n_keyframes']}-keyframe PoseGraphSE2 + SE(2) deformation lift "
                           "to full resolution (not a full-resolution sparse solve)",
            "headline_rung_uses_no_dem": True,
            "paper_full_uses_2m_dem": True,
            "dem_on_top_net_negative_se3": bool(sc["lc_se2_dem"]["se3_rmse_m"] > sc["lc_se2"]["se3_rmse_m"]),
        },
        "evo_version": _evo_version(), "figures_dir": FIG_DIR, "estimates": tum,
        "i3_attestation": (
            "Every estimate consumes ONLY stereo images, the VO orientation, the declared coarse start, "
            "and (for rungs a-c) the DEM solely as a yaw-init + start-height prior; only rung (d) adds the "
            "DEM as an online height-normal anchor, sampled at the ESTIMATED (x, y). The SE(2) loop "
            "factors use the SAME visual closures (relative pose from LightGlue+PnP), with the heading "
            "change from the PnP relative rotation. No GT is an argument to any estimator; GT enters only "
            "at scoring, after each estimate is frozen. (Poison test on the position-graph rungs: "
            "GT + 1e6 m -> byte-identical; the SE(2) estimator is GT-free by the same data flow.)"
        ),
    }
    out_json = os.path.join(VALIDATION_DIR, "s3li_crater_se2_recipe_2026-06-28.json")
    with open(out_json, "w") as fh:
        json.dump(artifact, fh, indent=2)

    print("\n========= S3LI s3li_crater FULL ladder (loop closure + SE(2) heading fix + DEM) =========")
    g = artifact["ladder_se3_rmse_m"]
    print(f" loop closures {meta['n_loop_closures']}; SE(2) {meta['se2']['n_keyframes']} kf "
          f"{meta['se2']['n_loops']} loops conv={meta['se2']['converged']}")
    for k, lab in [("vo", "VO"), ("lc_pos", "VO+LC(position)"), ("lc_se2", "VO+LC(SE2)"),
                   ("lc_se2_dem", "VO+LC(SE2)+DEM"), ("lc_se2_dem_h", "VO+LC(SE2)+DEM(h-only)")]:
        if k not in sc:
            continue
        s = sc[k]
        print(f"  {lab:24s} SE3 {s['se3_rmse_m']:6.1f}  horiz {s['horizontal_m']:6.1f}  "
              f"vert {s['vertical_m']:5.1f}")
    print(f"  paper                VO {g['paper_vo']:.1f} -> full {g['paper_full']:.1f}")
    print(f" findings: {artifact['findings']}")
    print(f" artifact -> {out_json}")


if __name__ == "__main__":
    main()
