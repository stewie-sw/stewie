"""Fixed LAC-style benchmark suite (PM-10) -- REPORT-ONLY (no CI gate, no pass/fail bar).

ONE fixed suite that assembles the six LAC-style metrics -- localization RMSE, the 5 cm
height-cell pass fraction, rock F1, coverage, runtime, and failure count -- into per-condition
rows swept over the FIXED condition matrix seeds x light x rocks, plus an integer failure count
aggregated across the sweep.  It ASSEMBLES the repo's existing scorers; it invents no metric and
no data:

  localization_rmse_m   -- the REAL ESA Katwijk dead-reckoning ATE (stewie.eval.katwijk_baseline
                           .run) on the COMMITTED ~30 s real fixture (gps/odometry/imu verbatim
                           slice; provenance in the fixture dir).  Deterministic, CI-runnable.
  height_cell_pass_frac -- score_map.map_height_metrics at tol_m = 0.05 (the LAC 5 cm height-cell
                           metric) on a REAL committed scene heightmap (2 cm posting) vs a REAL
                           block-mean lower-resolution reconstruction of it (subsampled real data,
                           the test_score_map convention -- like a thumbnail, never fabricated).
  rock_f1               -- GATED.  Scoring needs an OBSERVED rock list from a detector on rendered
                           frames (the Godot/GPU track); none exists on this host, so the leg is
                           reported as status 'gated' with value None -- NEVER a fabricated number.
                           The TRUTH rock list is real (the scene's committed clast metadata) and
                           its count is carried on the row for the day a detector output lands.
  coverage_frac         -- dart.map_channel.coverage_mask (the cheap onboard-observability tier)
                           over the REAL RTK station track of the same committed Katwijk fixture.
  runtime_s             -- measured wall time of the condition's executed legs (perf_counter).
  failure_count         -- legs that RAISED during the condition, counted per row (status 'failed',
                           value None) and summed across the sweep.  Failures surface, never hide.

HONESTY -- which axes bind what (the sweep is not oversold):
  * seed  binds the height leg (a seeded crop of the real heightmap -- the CPU stand-in for
    per-seed scenario generation).
  * rocks binds the scene selection (crater_boulders, 143 committed clasts, vs crater, 0) and the
    truth rock list.  NOTE: clasts are separate rigid objects, NOT baked into the committed
    heightmaps, so on this CPU tier the height leg barely distinguishes the two scenes; a
    render-tier observed map WOULD see the boulders.  That render sweep is GATED.
  * light binds NOTHING executable here: lit-vs-shadow only enters through the Godot render /
    sensor model (GPU-gated), so both light rows carry the same CPU numbers and the report says so
    (`gated` block).  Reporting the axis with an explicit non-binding note beats faking variation.
  * the localization + coverage legs are condition-INSENSITIVE on the CPU path (one real dataset,
    a deterministic pipeline); their per-condition sweep is likewise render/sim-gated.

Pure stdlib + numpy + the repo's own scorers.  No ROS import; runs on the bare host .venv.

CC0-1.0 (see ../../LICENSE).
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Mapping, Optional, Sequence

import numpy as np

import score_map as sm
from dart.map_channel import SENSOR_RADIUS_M, coverage_mask
from stewie.eval import katwijk_baseline as kb

SUITE_NAME = "lac_style_fixed_v1"

# The six per-condition metric slots (the PM-10 row): exactly these keys on every row.
METRIC_KEYS = (
    "localization_rmse_m",
    "height_cell_pass_frac",
    "rock_f1",
    "coverage_frac",
    "runtime_s",
    "failure_count",
)

# FIXED condition matrix: 3 seeds x 2 light x 2 rocks = 12 conditions.  Frozen so every run of the
# suite is the SAME benchmark (fixed-suite semantics), not a drifting parameterization.
LAC_SEEDS = (0, 1, 2)
LAC_LIGHTS = ("lit", "shadow")
LAC_ROCKS = (True, False)
LAC_CONDITIONS = tuple(
    {"seed": s, "light": li, "rocks": ro}
    for s in LAC_SEEDS for li in LAC_LIGHTS for ro in LAC_ROCKS
)

# rocks axis -> REAL committed scene bundle (see module docstring honesty note).
DEFAULT_SCENE_BY_ROCKS = {True: "crater_boulders", False: "crater"}

# LAC 5 cm height-cell tolerance; crop/block sizes for the real reconstruction leg (2 cm posting:
# a 128^2 crop is a 2.56 m patch, block 8 = a 16 cm block-mean reconstruction).
HEIGHT_TOL_M = 0.05
CROP_CELLS = 128
COARSEN_BLOCK = 8

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.normpath(os.path.join(_HERE, "..", ".."))
# the committed ~30 s REAL Katwijk slice test_katwijk_mini guards (CI-present, no skipif)
KATWIJK_MINI = os.path.join(os.path.dirname(os.path.abspath(kb.__file__)),
                            "tests", "fixtures", "katwijk_mini")


def _load_scene(scene: str, repo_root: str = _REPO) -> tuple[np.ndarray, list]:
    """(heightfield [m], clast list) from a REAL committed scene bundle under samples/."""
    bundle = os.path.join(repo_root, "samples", scene)
    with open(os.path.join(bundle, "metadata.json"), "r", encoding="utf-8") as fh:
        meta = json.load(fh)
    g = meta["grid"]
    z = np.fromfile(os.path.join(bundle, "heightmap.rf32"), dtype="<f4")
    return z.reshape(int(g["height"]), int(g["width"])).astype(np.float64), (meta.get("clasts") or [])


def _coarsen(z: np.ndarray, block: int) -> np.ndarray:
    """REAL lower-resolution reconstruction: block-mean downsample then upsample back (the
    test_score_map convention -- a real thumbnail of real data, nothing fabricated)."""
    n0 = z.shape[0] - z.shape[0] % block
    n1 = z.shape[1] - z.shape[1] % block
    zc = z[:n0, :n1]
    small = zc.reshape(n0 // block, block, n1 // block, block).mean(axis=(1, 3))
    return np.kron(small, np.ones((block, block)))


def _seeded_crop(z: np.ndarray, seed: int, n: int = CROP_CELLS) -> np.ndarray:
    """A seed-deterministic n x n crop of the real heightfield -- the CPU stand-in for per-seed
    scenario generation (subsampling real data; the seed picks WHERE, it synthesises nothing)."""
    rng = np.random.default_rng(seed)
    r0 = int(rng.integers(0, z.shape[0] - n))
    c0 = int(rng.integers(0, z.shape[1] - n))
    return z[r0:r0 + n, c0:c0 + n]


def _height_leg(scene: str, seed: int, repo_root: str) -> dict:
    """5 cm height-cell pass fraction on a seeded crop of the real scene heightmap."""
    z, clasts = _load_scene(scene, repo_root)
    crop = _seeded_crop(z, seed)
    observed = _coarsen(crop, COARSEN_BLOCK)[:crop.shape[0], :crop.shape[1]]
    rmse, pass_frac = sm.map_height_metrics(observed, crop, tol_m=HEIGHT_TOL_M)
    return {"pass_frac": pass_frac, "rmse_m": rmse, "n_truth_rocks": len(clasts)}


def _coverage_leg(stations_xy: np.ndarray, *, margin_m: float = 10.0, cell_m: float = 1.0) -> float:
    """Observed fraction of the traverse worksite (station bbox + margin) via the real station track."""
    x, y = stations_xy[:, 0], stations_xy[:, 1]
    bbox = (float(x.min() - margin_m), float(y.min() - margin_m),
            float(x.max() + margin_m), float(y.max() + margin_m))
    obs = coverage_mask(bbox, cell_m, [tuple(p) for p in stations_xy], SENSOR_RADIUS_M)
    return float(obs.mean())


def run_condition(
    condition: Mapping[str, Any],
    *,
    scene_by_rocks: Mapping[bool, str] = DEFAULT_SCENE_BY_ROCKS,
    repo_root: str = _REPO,
    katwijk_dir: str = KATWIJK_MINI,
) -> dict:
    """One per-condition row: the six metric slots + per-leg status + honesty context.

    Every leg runs under its own try/except: a raising leg becomes status 'failed' with value None
    and increments the row's failure_count -- the suite reports the failure, it never hides it and
    never substitutes a number.
    """
    t0 = time.perf_counter()
    scene = scene_by_rocks[bool(condition["rocks"])]
    metrics: dict[str, Optional[float]] = {}
    status: dict[str, str] = {}
    context: dict[str, Any] = {}
    failures = 0
    n_truth_rocks = None

    # (1) localization RMSE -- real Katwijk dead-reckoning on the committed fixture.
    try:
        loc = kb.run(katwijk_dir)
        metrics["localization_rmse_m"] = float(loc["ate_aligned_m"])
        context["localization"] = {
            "source": loc["dataset"] + " (committed ~30 s real slice)",
            "eval_track_length_m": loc["eval_track_length_m"],
            "condition_insensitive": True,   # deterministic real pipeline; sim sweep is gated
        }
        status["localization_rmse_m"] = "ok"
    except Exception as exc:                                       # surfaced, not hidden
        metrics["localization_rmse_m"] = None
        status["localization_rmse_m"] = "failed"
        context["localization_error"] = repr(exc)
        failures += 1

    # (2) 5 cm height-cell pass fraction -- seeded crop of the real scene heightmap.
    try:
        h = _height_leg(scene, int(condition["seed"]), repo_root)
        metrics["height_cell_pass_frac"] = h["pass_frac"]
        context["height_rmse_m"] = h["rmse_m"]
        n_truth_rocks = h["n_truth_rocks"]
        status["height_cell_pass_frac"] = "ok"
    except Exception as exc:
        metrics["height_cell_pass_frac"] = None
        status["height_cell_pass_frac"] = "failed"
        context["height_error"] = repr(exc)
        failures += 1

    # (3) rock F1 -- GATED: no observed rock list without the render+detector track.  The truth
    # list is real (committed clasts) and its count rides on the row; the value stays None.
    metrics["rock_f1"] = None
    status["rock_f1"] = "gated"

    # (4) coverage -- the real RTK station track over its own worksite (observability tier).
    try:
        _, gt_xy = kb.load_rtk_track(katwijk_dir)
        metrics["coverage_frac"] = _coverage_leg(gt_xy)
        context["coverage"] = {"n_stations": int(len(gt_xy)), "condition_insensitive": True}
        status["coverage_frac"] = "ok"
    except Exception as exc:
        metrics["coverage_frac"] = None
        status["coverage_frac"] = "failed"
        context["coverage_error"] = repr(exc)
        failures += 1

    # (5) runtime + (6) failure count -- real measurements of THIS condition's execution.
    metrics["runtime_s"] = float(time.perf_counter() - t0)
    metrics["failure_count"] = failures
    status["runtime_s"] = "ok"
    status["failure_count"] = "ok"

    return {
        "condition": dict(condition),
        "scene": scene,
        "n_truth_rocks": n_truth_rocks,
        "metrics": metrics,
        "status": status,
        "context": context,
    }


def run_lac_suite(
    conditions: Sequence[Mapping[str, Any]] = LAC_CONDITIONS,
    *,
    scene_by_rocks: Mapping[bool, str] = DEFAULT_SCENE_BY_ROCKS,
    repo_root: str = _REPO,
    katwijk_dir: str = KATWIJK_MINI,
) -> dict:
    """Run the fixed suite over the condition matrix -> the PM-10 report.

    Per-condition rows carry all six metric slots (see METRIC_KEYS); `failure_count` at the top
    level is the integer aggregate across the sweep.  Report-only: no pass/fail, no threshold.
    """
    rows = [
        run_condition(c, scene_by_rocks=scene_by_rocks, repo_root=repo_root,
                      katwijk_dir=katwijk_dir)
        for c in conditions
    ]
    return {
        "suite": SUITE_NAME,
        "report_only": True,
        "height_tol_m": HEIGHT_TOL_M,
        "n_conditions": len(rows),
        "conditions": rows,
        "failure_count": int(sum(r["metrics"]["failure_count"] for r in rows)),
        "gated": {
            "rock_f1": "needs an observed rock list from a detector on Godot-rendered frames "
                       "(GPU/render track); reported as status 'gated', value None -- never faked",
            "light_axis": "lit-vs-shadow binds only the render/sensor tier (GPU-gated); both "
                          "light rows carry the same CPU numbers by construction",
            "localization_and_coverage_sweep": "the CPU legs are one real deterministic dataset; "
                                               "their per-seed/light/rocks sweep needs the "
                                               "rendered sim and is gated",
        },
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI: print the suite report JSON to stdout (report-only, like eval_harness)."""
    print(json.dumps(run_lac_suite(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
