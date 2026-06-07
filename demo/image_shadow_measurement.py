#!/usr/bin/env python3
"""First genuine sensor->factor: image-derived shadow heading (Algorithm P4 sec 15.2).

NOTHING here reads the rover's truth pose (invariant I3). The shadow azimuth is extracted from
rendered PIXELS; the Sun azimuth is a CONFIGURED scene parameter (--sun-azim), not rover truth.
Two checks: (1) a clean single cast shadow -> high-confidence extraction; (2) sun-response --
rendering the same scene at two known Sun azimuths, the extracted direction must rotate with the
Sun. Then the extracted z_shadow_body feeds shadow.heading_from_shadow -> a sensor-derived yaw.
"""
import os, json
import numpy as np
from imageio.v3 import imread

from solnav.perception import shadow_extract as se
from solnav.geometry import shadow

OUTd = "/mnt/projects/foss_ipex/dustgym/godot_sidecar/out"
OUT = os.path.join(os.path.dirname(__file__), "out"); os.makedirs(OUT, exist_ok=True)


def main():
    res = {}
    # (1) clean single cast shadow (cube on plane, 5 deg sun) -> high confidence
    clean = se.extract_shadow_azimuth(np.asarray(imread(OUTd + "/cube_on_plane.png")))
    res["clean"] = {"az_deg": round(clean.z_shadow_body_deg, 1), "confidence": round(clean.confidence, 3),
                    "sigma_deg": round(clean.sigma_deg, 1), "n_edge_px": clean.n_edge_px,
                    "provenance": clean.provenance}

    # (2) sun-response: same boulder scene at two KNOWN sun azimuths (gate off to show tracking)
    pair = {}
    for az in (180, 260):
        p = OUTd + f"/td_sun_{az}.png"
        if not os.path.exists(p):
            continue
        o = se.extract_shadow_azimuth(np.asarray(imread(p)), gate=False)
        pair[az] = o
    if len(pair) == 2:
        d_ext = ((pair[260].z_shadow_body_deg - pair[180].z_shadow_body_deg + 180) % 360) - 180
        res["sun_response"] = {
            "az180_extracted": round(pair[180].z_shadow_body_deg, 1), "R180": round(pair[180].confidence, 3),
            "az260_extracted": round(pair[260].z_shadow_body_deg, 1), "R260": round(pair[260].confidence, 3),
            "delta_extracted_deg": round(float(d_ext), 1), "delta_sun_deg": 80.0,
            "tracks_sun": bool(abs(abs(d_ext) - 80.0) < 30.0),
            "note": "low R in dense clutter -> the gate rejects it; needs a segmentation front-end (P7)"}

    # (3) wire the clean image-derived measurement into a heading factor (vs the oracle)
    known_sun_az = 30.0   # the cube scene's --sun-azim (a configured parameter, NOT rover truth)
    yaw_from_image = shadow.heading_from_shadow(clean.z_shadow_body_deg, known_sun_az)
    res["sensor_derived_heading_factor"] = {
        "z_shadow_body_deg": round(clean.z_shadow_body_deg, 1),
        "yaw_from_image_deg": round(yaw_from_image, 1),
        "factor_info": round(1.0 / np.radians(clean.sigma_deg) ** 2, 1),
        "note": "yaw + image-derived sigma -> a real solar/shadow heading factor (no truth ingress)"}

    json.dump(res, open(os.path.join(OUT, "image_shadow_metrics.json"), "w"), indent=2)
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
