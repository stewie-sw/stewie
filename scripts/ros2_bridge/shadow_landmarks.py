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


def scale_landmarks(landmarks, sx: float, sy: float):
    """Rescale landmark image coords for a downscaled served panorama. x,y move with the resize;
    AREA scales by sx*sy; the AZIMUTH bearing is geometry (computed from the full-res column) and is
    invariant under resize, so it is carried through unchanged. Used to fit the full-res panorama's
    landmarks onto the smaller PNG the cockpit Perception pane serves."""
    out = []
    for lm in landmarks:
        out.append({**lm,
                    "x": round(lm["x"] * sx, 2), "y": round(lm["y"] * sy, 2),
                    "area": int(round(lm.get("area", 0) * sx * sy))})
    return out


def emit_served_artifacts(egress_dir: str, out_dir: str, *, width: int = 2048, top: int = 12,
                          scene: str = ""):
    """Render the cockpit Perception-pane assets from a REAL render egress: a downscaled panorama PNG
    plus a landmarks.json manifest the front-end overlays. Landmarks are detected on the full-res
    panorama (bearings true), then scaled to the served width. Returns the manifest dict."""
    import json
    import os

    from PIL import Image
    import panorama as P

    full = P.build_panorama(egress_dir)
    order = P.panorama_order(egress_dir)
    lms = landmark_bearings(detect_shadow_landmarks(full), order)[:top]
    fh, fw = full.shape
    sx = width / fw
    sh = max(1, int(round(fh * sx)))
    served = np.asarray(Image.fromarray(full).resize((width, sh)))
    scaled = scale_landmarks(lms, sx, sh / fh)
    os.makedirs(out_dir, exist_ok=True)
    Image.fromarray(served).save(os.path.join(out_dir, "panorama.png"))
    manifest = {
        "scene": scene or os.path.basename(os.path.dirname(os.path.normpath(egress_dir))),
        "width": int(width), "height": int(sh),
        "full_width": int(fw), "full_height": int(fh),
        "cameras": [{"name": n, "heading_deg": round(az, 1)} for n, az, _ in order],
        "landmarks": scaled,
        "note": ("Real Godot 8-camera rig render -> heading-ordered panorama; shadow-nav landmarks are "
                 "cast-shadow dark-contrast blobs, each tagged with its azimuth bearing (the ARGUS "
                 "pose-graph measurement). No synthetic pixels."),
    }
    with open(os.path.join(out_dir, "landmarks.json"), "w") as f:
        json.dump(manifest, f, indent=1)
    return manifest


if __name__ == "__main__":
    import argparse
    import json
    import os

    from PIL import Image
    import panorama as P
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--in", dest="egress", required=True, help="out/cam/<scene>/<NNN>/ dir")
    ap.add_argument("--top", type=int, default=12, help="report the N largest shadow landmarks")
    ap.add_argument("--emit-served", dest="served", default="",
                    help="also write a downscaled panorama.png + landmarks.json for the cockpit here")
    ap.add_argument("--served-width", type=int, default=2048, help="served panorama width (px)")
    a = ap.parse_args()
    pano = P.build_panorama(a.egress)
    order = P.panorama_order(a.egress)
    lms = landmark_bearings(detect_shadow_landmarks(pano), order)[:a.top]
    Image.fromarray(pano).save(os.path.join(a.egress, "panorama.png"))
    if a.served:
        m = emit_served_artifacts(a.egress, a.served, width=a.served_width, top=a.top)
        print(json.dumps({"served": a.served, "served_dims": [m["width"], m["height"]],
                          "n_landmarks": len(m["landmarks"])}, indent=1))
    else:
        print(json.dumps({"n_landmarks": len(lms), "panorama": list(pano.shape),
                          "landmarks": lms}, indent=1))
