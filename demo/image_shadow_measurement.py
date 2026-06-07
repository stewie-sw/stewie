#!/usr/bin/env python3
"""Image-derived shadow-axis diagnostic for Algorithm P4 section 15.2.

Nothing here reads rover truth. It demonstrates image-plane extraction and Sun response. It
does not claim a body-frame heading factor: the clean fixture uses an oblique free camera, and
the clutter method returns an axis modulo 180 degrees. Camera-to-body/ground mapping, direction
resolution, and covariance calibration remain required.
"""
import json
import os

import numpy as np
from imageio.v3 import imread

from solnav.perception import shadow_extract as se

OUTd = "/mnt/projects/foss_ipex/dustgym/godot_sidecar/out"
OUT = os.path.join(os.path.dirname(__file__), "out"); os.makedirs(OUT, exist_ok=True)


def main():
    res = {}
    # (1) clean single cast shadow (cube on plane, 5 deg sun) -> high confidence
    clean = se.extract_shadow_azimuth(np.asarray(imread(OUTd + "/cube_on_plane.png")))
    res["clean_image_direction"] = {
        "az_image_deg": round(clean.z_shadow_image_deg, 1),
        "confidence": round(clean.confidence, 3),
        "dispersion_deg_uncalibrated": round(clean.dispersion_deg, 1),
        "n_support": clean.n_support,
        "coordinate_frame": clean.coordinate_frame,
        "periodicity_deg": clean.periodicity_deg,
        "provenance": clean.provenance,
    }

    # (2) sun-response in dense clutter via the P7 blob front-end (same scene, two KNOWN suns).
    # P7 recovers the shadow AXIS (mod 180) at high concentration -> passes the gate where the
    # per-pixel boundary method does not. The 180-deg DIRECTION resolution stays the open sub-problem.
    pair = {}
    for az in (180, 260):
        p = OUTd + f"/td_sun_{az}.png"
        if os.path.exists(p):
            pair[az] = se.extract_shadow_azimuth_p7(np.asarray(imread(p)), gate=False)
    if len(pair) == 2:
        res["sun_response_p7"] = {
            "R_axis_180": round(pair[180].confidence, 3), "n_blobs_180": pair[180].n_support,
            "R_axis_260": round(pair[260].confidence, 3), "n_blobs_260": pair[260].n_support,
            "passes_gate": bool(min(pair[180].confidence, pair[260].confidence) > 0.30),
            "periodicity_deg": 180,
            "direction_resolved": False,
            "note": ("P7 blob axis-concentration ~0.7 (vs ~0.09 per-pixel) passes the gate in dense "
                     "clutter and tracks the Sun on the AXIS (mod 180, ~12 deg); the 180-deg direction "
                     "resolution (caster association) is the remaining open sub-problem.")}

    res["heading_factor_status"] = {
        "status": "BLOCKED",
        "reason": (
            "The extracted angle is in image coordinates. A calibrated image-to-ground/body "
            "mapping, direction resolution, and calibrated angular covariance are required."
        ),
    }

    json.dump(res, open(os.path.join(OUT, "image_shadow_metrics.json"), "w"), indent=2)
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
