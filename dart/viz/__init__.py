"""dart.viz -- reusable figure generation for STEWIE estimator runs.

The keystone evaluation of a STEWIE estimator (visual odometry / SLAM) is a frozen estimate
trajectory scored against ground truth with evo. ``run_figures`` turns that scoring into the
paper-style figure set (trajectory overlay, ATE error map, drift-vs-distance, RPE curve) plus a
metrics JSON, and is dataset-agnostic so later runs (S3LI, Katwijk, ...) reuse it unchanged. A thin
LuSNAR adapter (:func:`run_figures.lusnar_gt_trajectory`) builds the ground-truth trajectory from
:class:`dart.lusnar_reader.LusnarReader`.
"""
from dart.viz.run_figures import (
    FigureBundle,
    GtSamples,
    compute_figure_bundle,
    generate_figures,
    load_estimate,
    lusnar_gt_trajectory,
)

__all__ = [
    "FigureBundle",
    "GtSamples",
    "compute_figure_bundle",
    "generate_figures",
    "load_estimate",
    "lusnar_gt_trajectory",
]
