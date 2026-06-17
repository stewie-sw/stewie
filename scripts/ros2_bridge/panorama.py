#!/usr/bin/env python3
"""8-camera rig -> panoramic scene (Convergence #183, shadow-nav lane).

Reads a Godot `--cameras` egress (`out/cam/<scene>/<NNN>/`: the 8 LAC rig PNGs + sensors.json) and
composites the views into a single horizontal PANORAMA, ordered by each camera's world-frame heading
(derived from `pose_in_world.quaternion_xyzw`). The panorama is the surround a ShadowNav landmark
finder works on: the grazing-sun shadow OUTLINES of boulders/craters are the features, and they read
across the full 360 deg of the rig.

Pure numpy + PIL (no cv2/rclpy) so it host-tests against a REAL render egress; SKIPs when none is
present (the egress is render output, not committed -- the same no-fabrication convention as
obs_map_producer). It never invents pixels: a missing camera image is omitted, not synthesized.

Heading from the quaternion: Godot is y-up with -Z forward, +X right. forward = R(q) @ (0,0,-1);
the ground-plane heading az = atan2(forward.x, -forward.z) in [0,360). Cameras are laid left->right
by increasing az, so the strip sweeps the rover's surround.
"""
from __future__ import annotations

import json
import math
import os

import numpy as np
from PIL import Image

CAM_W, CAM_H = 1024, 768


def _quat_forward(q) -> np.ndarray:
    """Rotate Godot's forward vector (0,0,-1) by quaternion q=[x,y,z,w] (the standard v' = v + 2w(qv×v)
    + 2 qv×(qv×v))."""
    x, y, z, w = (float(v) for v in q)
    qv = np.array([x, y, z]); v = np.array([0.0, 0.0, -1.0])
    t = 2.0 * np.cross(qv, v)
    return v + w * t + np.cross(qv, t)


def camera_heading_deg(cam: dict) -> float:
    """A camera's ground-plane heading [0,360) from its world pose (for ordering the panorama)."""
    f = _quat_forward(cam["pose_in_world"]["quaternion_xyzw"])
    return (math.degrees(math.atan2(float(f[0]), -float(f[2]))) + 360.0) % 360.0


def panorama_order(egress_dir: str):
    """The camera entries that HAVE an on-disk image, ordered by heading. Returns [(name, heading_deg,
    image_path)] -- the panorama layout, no pixels read yet."""
    s = json.load(open(os.path.join(egress_dir, "sensors.json")))
    out = []
    for cam in s.get("cameras", []):
        img = os.path.join(egress_dir, cam.get("image", ""))
        if cam.get("image") and os.path.exists(img):
            out.append((cam["name"], camera_heading_deg(cam), img))
    out.sort(key=lambda t: t[1])
    return out


def build_panorama(egress_dir: str) -> np.ndarray:
    """Composite the rig's views into a horizontal panorama (grayscale, uint8), ordered by heading.
    Each tile is the REAL rendered view; tiles are placed left->right by increasing world heading."""
    order = panorama_order(egress_dir)
    if not order:
        raise FileNotFoundError(f"no camera images in {egress_dir} (render with sidecar --cameras first)")
    tiles = []
    for _name, _az, path in order:
        im = np.asarray(Image.open(path).convert("L"))
        if im.shape != (CAM_H, CAM_W):
            im = np.asarray(Image.fromarray(im).resize((CAM_W, CAM_H)))
        tiles.append(im)
    return np.hstack(tiles)


def save_panorama(egress_dir: str, out_path: str) -> dict:
    """Write the panorama PNG; return a manifest (the camera order + headings + dimensions)."""
    pano = build_panorama(egress_dir)
    Image.fromarray(pano).save(out_path)
    order = panorama_order(egress_dir)
    return {"out": out_path, "width": int(pano.shape[1]), "height": int(pano.shape[0]),
            "cameras": [{"name": n, "heading_deg": round(a, 1)} for n, a, _ in order]}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--in", dest="egress", required=True, help="out/cam/<scene>/<NNN>/ dir")
    ap.add_argument("--out", dest="out", required=True, help="output panorama PNG")
    a = ap.parse_args()
    print(json.dumps(save_panorama(a.egress, a.out), indent=1))
