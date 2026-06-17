#!/usr/bin/env python3
"""Shadow-nav landmarks on the 8-cam panorama (Convergence #183 / #79 shadow-outline landmarks).

Under the grazing lunar sun, boulders and crater rims cast long, high-contrast shadows; those cast
shadows are the trackable visual landmarks ShadowNav keys on (deterministic given the sun geometry,
which STEWIE's ephemeris already provides). This detects them on the heading-ordered panorama from
``panorama.py`` and maps each landmark's panorama column to an AZIMUTH bearing -- the bearing
measurement an ARGUS pose-graph factor consumes.

The detector finds dark blobs that are darker than their LOCAL lit neighborhood (so the uniform-black
sky and the rover-occluded void are excluded -- a cast shadow is dark RELATIVE to the lit regolith
around it, not dark in absolute terms). Pure numpy + scipy (no cv2/rclpy); host-testable on a real
render-derived panorama, SKIPs when none is present. No fabricated landmarks -- every keypoint is a
real connected dark-contrast region in the rendered image.
"""
from __future__ import annotations

import numpy as np
from scipy.ndimage import label, uniform_filter

CAM_W = 1024
FOV_X_DEG = 73.99   # camera_rig.gd FOV_X_DEG (the per-tile horizontal field of view)


def detect_shadow_landmarks(gray, *, box: int = 31, delta: float = 16.0, lit_floor: float = 18.0,
                            min_area: int = 50, max_area: int = 40000):
    """Cast-shadow landmarks: connected dark-contrast blobs sitting in a LIT local neighborhood.
    Returns [{x, y, area, contrast}] sorted by area desc (x,y = blob centroid in image pixels)."""
    g = np.asarray(gray, dtype=np.float32)
    local = uniform_filter(g, size=box, mode="nearest")
    shadow = (g < local - delta) & (local > lit_floor)        # darker than the local lit mean, in a lit area
    lab, n = label(shadow)
    out = []
    for i in range(1, n + 1):
        ys, xs = np.where(lab == i)
        a = int(xs.size)
        if a < min_area or a > max_area:
            continue
        out.append({"x": float(xs.mean()), "y": float(ys.mean()), "area": a,
                    "contrast": float((local[ys, xs] - g[ys, xs]).mean())})
    out.sort(key=lambda d: -d["area"])
    return out


def column_to_bearing_deg(col: float, cam_order, *, cam_w: int = CAM_W, fov_x_deg: float = FOV_X_DEG):
    """Map a panorama column to an azimuth bearing [0,360): which tile the column lands in (its camera's
    heading) plus the within-tile offset across the camera FOV. ``cam_order`` is panorama_order()'s
    [(name, heading_deg, path)] -- the same left->right heading layout the panorama was built with."""
    if not cam_order:
        return None
    tile = min(int(col // cam_w), len(cam_order) - 1)
    frac = (col - tile * cam_w) / cam_w - 0.5                  # -0.5..+0.5 across the tile
    return (float(cam_order[tile][1]) + frac * fov_x_deg + 360.0) % 360.0


def landmark_bearings(landmarks, cam_order, **kw):
    """Attach an azimuth bearing to each shadow landmark -> the ARGUS-facing measurement list."""
    out = []
    for lm in landmarks:
        b = column_to_bearing_deg(lm["x"], cam_order, **kw)
        out.append({**lm, "bearing_deg": (round(b, 2) if b is not None else None)})
    return out


if __name__ == "__main__":
    import argparse
    import json
    import os

    from PIL import Image
    import panorama as P
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--in", dest="egress", required=True, help="out/cam/<scene>/<NNN>/ dir")
    ap.add_argument("--top", type=int, default=12, help="report the N largest shadow landmarks")
    a = ap.parse_args()
    pano = P.build_panorama(a.egress)
    order = P.panorama_order(a.egress)
    lms = landmark_bearings(detect_shadow_landmarks(pano), order)[:a.top]
    Image.fromarray(pano).save(os.path.join(a.egress, "panorama.png"))
    print(json.dumps({"n_landmarks": len(lms), "panorama": list(pano.shape),
                      "landmarks": lms}, indent=1))
