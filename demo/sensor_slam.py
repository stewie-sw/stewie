#!/usr/bin/env python3
"""Blocked shadow-heading integration diagnostic.

The rendered image produces an image-plane shadow direction. It cannot become a rover heading
factor until camera-to-body/ground mapping and covariance calibration exist. This demo records
that integration gate instead of using a truth-derived offset to force the image angle into the
body frame.
"""
import json
import os

import numpy as np
from imageio.v3 import imread

from solnav.perception import shadow_extract as se

CUBE = "/mnt/projects/foss_ipex/dustgym/godot_sidecar/out/cube_on_plane.png"
OUT = os.path.join(os.path.dirname(__file__), "out"); os.makedirs(OUT, exist_ok=True)


def main():
    obs = se.extract_shadow_azimuth(np.asarray(imread(CUBE)))
    res = {
        "status": "BLOCKED",
        "image_shadow_candidate": {
            "az_image_deg": round(obs.z_shadow_image_deg, 1),
            "confidence": round(obs.confidence, 3),
            "dispersion_deg_uncalibrated": round(obs.dispersion_deg, 1),
            "coordinate_frame": obs.coordinate_frame,
            "periodicity_deg": obs.periodicity_deg,
            "covariance_calibrated": obs.covariance_calibrated,
            "provenance": obs.provenance,
        },
        "missing_requirements": [
            "calibrated camera-to-body transform",
            "image-axis to local-ground direction mapping",
            "direction ambiguity resolution",
            "validated angular covariance",
            "per-pose image acquisition",
        ],
    }
    json.dump(res, open(os.path.join(OUT, "sensor_slam_metrics.json"), "w"), indent=2)
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
