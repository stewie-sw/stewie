#!/usr/bin/env python3
"""[REQ:AS-17] #194 — re-freeze the G2 stereo corpus 0.070 m -> 0.05 m (TRL5-final).

Per fixture dir: re-render the 8-camera rig at the NEW 0.05 m baseline (camera_rig.gd is already
0.05), reconstructing the render config (rover-rc, sun) from the fixture's OWN frozen sensors.json,
then SURGICALLY update only the geometry-dependent fields:
  * swap the 4 stereo PNGs (front_left/front_right/rear_left/rear_right) with the new renders;
  * sensors.json   : the 4 stereo cams' extrinsic_in_base_link + pose_in_world; stereo/stereo_rear baseline_m;
  * runtime_sensors: the 4 stereo cams' extrinsic_in_base_link; stereo/stereo_rear baseline_m; profile_sha256;
  * evaluation_truth: the 4 stereo cams' pose_in_world (camera_poses_in_world); profile_sha256.
Monos + drum cams are proven bit-identical at 0.05 (positions unchanged) -> left untouched. All
non-geometric bookkeeping (calibration_id, timestamps, health, lander, rover, sun) is preserved
byte-for-byte: the diff is exactly what the baseline change causes. depth-truth is recomputed at test
time by ray_cast_depth, so nothing precomputed is stored.

NOT a stub/synthetic: every value comes from the real 0.05 Godot render. The render is deterministic
for geometry (validated Δ=0 vs frozen at 0.070).

Usage:  refreeze_stereo_05.py <pose_dir> [pose_dir ...]    # writes the dirs in place (git-tracked, revertible)
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

import numpy as np

from stewie.specs.profiles import load_profile

ROOT = "/mnt/projects/stewie/code"
SCENE = f"{ROOT}/samples/crater_boulders"
GODOT_CAM = f"{ROOT}/stewie/godot/out/cam/crater_boulders"
GODOT_OUT = f"{GODOT_CAM}/000"
CELL = 0.02
STEREO = ("front_left", "front_right", "rear_left", "rear_right")
NEW_SHA = load_profile("STEWIE_IPEX_V1").sha256   # the edited 0.05 profile's sha


def reconstruct_rc(rover_pos):
    """world (x=col, z=row) -> integer grid cell (r, c). g2cal poses sit on integer cells."""
    x, _y, z = rover_pos
    return int(round(z / CELL)), int(round(x / CELL))


def render_05(rc, sun, with_clasts: bool):
    shutil.rmtree(GODOT_CAM, ignore_errors=True)
    layers = "terrain,clasts,rover" if with_clasts else "terrain,rover"
    cmd = ["bash", f"{ROOT}/stewie/godot/render.sh", "res://sidecar.tscn", "--",
           "--scene", SCENE, "--cameras", "--layers", layers,
           "--rover-rc", f"{rc[0]},{rc[1]}", "--rover-yaw", "0",
           "--sun-elev", str(sun["elevation_deg"]), "--sun-azim", str(sun["azimuth_deg"]),
           "--size", "1024x768"]
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=240)
    if not os.path.exists(f"{GODOT_OUT}/front_left.png"):
        raise RuntimeError(f"render failed for rc={rc}: {r.stderr[-400:]}")
    return json.load(open(f"{GODOT_OUT}/sensors.json"))


def _set_cam_field(cam_list, name, key, value):
    for c in cam_list:
        if c["name"] == name:
            c[key] = value
            return
    raise KeyError(f"camera {name} not in list")


def refreeze_pose(pose_dir: str):
    froz = json.load(open(f"{pose_dir}/sensors.json"))
    rover = froz["rover"]["position_m"]
    sun = froz["sun"]
    rc = reconstruct_rc(rover)
    with_clasts = "noclasts" not in os.path.basename(pose_dir)
    new = render_05(rc, sun, with_clasts)
    new_cams = {c["name"]: c for c in new["cameras"]}
    new_base = new["stereo"]["baseline_m"]
    new_base_rear = new.get("stereo_rear", {}).get("baseline_m", new_base)

    # 1) swap the 4 stereo PNGs
    for cam in STEREO:
        shutil.copy(f"{GODOT_OUT}/{cam}.png", f"{pose_dir}/{cam}.png")

    # 2) sensors.json: stereo cams' extrinsic + pose_in_world, baselines
    sj = json.load(open(f"{pose_dir}/sensors.json"))
    for cam in STEREO:
        _set_cam_field(sj["cameras"], cam, "extrinsic_in_base_link", new_cams[cam]["extrinsic_in_base_link"])
        _set_cam_field(sj["cameras"], cam, "pose_in_world", new_cams[cam]["pose_in_world"])
    sj["stereo"]["baseline_m"] = new_base
    if "stereo_rear" in sj:
        sj["stereo_rear"]["baseline_m"] = new_base_rear
    json.dump(sj, open(f"{pose_dir}/sensors.json", "w"), indent=2)

    # 3) runtime_sensors.json: stereo extrinsics, baselines, profile sha
    rt = json.load(open(f"{pose_dir}/runtime_sensors.json"))
    for cam in STEREO:
        _set_cam_field(rt["cameras"], cam, "extrinsic_in_base_link", new_cams[cam]["extrinsic_in_base_link"])
    rt["stereo"]["baseline_m"] = new_base
    if "stereo_rear" in rt:
        rt["stereo_rear"]["baseline_m"] = new_base_rear
    rt["profile_sha256"] = NEW_SHA
    json.dump(rt, open(f"{pose_dir}/runtime_sensors.json", "w"), indent=2)

    # 4) evaluation_truth.json: stereo cams' pose_in_world, profile sha
    et = json.load(open(f"{pose_dir}/evaluation_truth.json"))
    for cam in STEREO:
        _set_cam_field(et["camera_poses_in_world"], cam, "pose_in_world", new_cams[cam]["pose_in_world"])
    et["profile_sha256"] = NEW_SHA
    json.dump(et, open(f"{pose_dir}/evaluation_truth.json", "w"), indent=2)

    # verify the written separation == new baseline
    fl = np.array([c for c in sj["cameras"] if c["name"] == "front_left"][0]["extrinsic_in_base_link"]["position_m"])
    fr = np.array([c for c in sj["cameras"] if c["name"] == "front_right"][0]["extrinsic_in_base_link"]["position_m"])
    sep = float(np.linalg.norm(fl - fr))
    return {"pose": os.path.basename(pose_dir), "rc": rc, "baseline_m": round(new_base, 6),
            "front_sep_m": round(sep, 6)}


if __name__ == "__main__":
    for pd in sys.argv[1:]:
        print(json.dumps(refreeze_pose(pd)))
