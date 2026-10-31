"""Fixed LAC-style benchmark suite (PM-10) -- REPORT-ONLY (no CI gate, no pass/fail bar).

ONE fixed suite that assembles the LAC-style metrics this host can measure -- the 5 cm
height-cell pass fraction, runtime, and failure count -- into per-condition rows swept over the
FIXED condition matrix seeds x light x rocks, plus an integer failure count aggregated across the
sweep.  It ASSEMBLES the repo's existing scorers; it invents no metric and no data.  Localization
RMSE, coverage and rock F1 are not measured here: the real-rover localization data was removed
(2026-10-31) and no rock detector runs on rendered frames on this host.

  height_cell_pass_frac -- score_map.map_height_metrics at tol_m = 0.05 (the LAC 5 cm height-cell
                           metric) on a REAL committed scene heightmap (2 cm posting) vs a REAL
                           block-mean lower-resolution reconstruction of it (subsampled real data,
                           the test_score_map convention -- like a thumbnail, never fabricated).
  runtime_s             -- measured wall time of the condition's executed legs (perf_counter).
  failure_count         -- legs that RAISED during the condition, counted per row (status 'failed',
                           value None) and summed across the sweep.  Failures surface, never hide.

HONESTY -- which axes bind what (the sweep is not oversold):
  * seed  binds the height leg (a seeded crop of the real heightmap -- the CPU stand-in for
    per-seed scenario generation).
  * rocks binds the scene selection (crater_boulders, 143 committed clasts, vs crater, 0) and the
    truth rock count carried on each row.  NOTE: clasts are separate rigid objects, NOT baked into the committed
    heightmaps, so on this CPU tier the height leg barely distinguishes the two scenes; a
    render-tier observed map WOULD see the boulders.  That render sweep is GATED.
  * light binds NOTHING executable here: lit-vs-shadow only enters through the Godot render /
    sensor model (GPU-gated), so both light rows carry the same CPU numbers and the report says so
    (`gated` block).  Reporting the axis with an explicit non-binding note beats faking variation.

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

SUITE_NAME = "lac_style_fixed_v1"

# The per-condition metric slots this suite measures: exactly these keys on every row.
METRIC_KEYS = (
    "height_cell_pass_frac",
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


def run_condition(
    condition: Mapping[str, Any],
    *,
    scene_by_rocks: Mapping[bool, str] = DEFAULT_SCENE_BY_ROCKS,
    repo_root: str = _REPO,
) -> dict:
    """One per-condition row: the metric slots + per-leg status + honesty context.

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

    # 5 cm height-cell pass fraction -- seeded crop of the real scene heightmap.
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

    # runtime + failure count -- real measurements of THIS condition's execution.
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
) -> dict:
    """Run the fixed suite over the condition matrix -> the PM-10 report.

    Per-condition rows carry every metric slot (see METRIC_KEYS); `failure_count` at the top
    level is the integer aggregate across the sweep.  Report-only: no pass/fail, no threshold.
    """
    rows = [
        run_condition(c, scene_by_rocks=scene_by_rocks, repo_root=repo_root)
        for c in conditions
    ]
    return {
        "suite": SUITE_NAME,
        "report_only": True,
        "height_tol_m": HEIGHT_TOL_M,
        "n_conditions": len(rows),
        "conditions": rows,
        "failure_count": int(sum(r["metrics"]["failure_count"] for r in rows)),
        "not_measured": {
            "light_axis": "lit-vs-shadow binds only the render/sensor tier; both light rows carry the "
                          "same CPU numbers by construction",
        },
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI: print the suite report JSON to stdout (report-only, like eval_harness)."""
    print(json.dumps(run_lac_suite(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
