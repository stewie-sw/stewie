#!/usr/bin/env python3
"""8-pane faithful posture-transition GIF: animate what the 8 LAC cameras see as the rover transitions
between two postures (e.g. TRANSIT -> MEERKAT). Each pane is one camera, labelled with its name and its
COMPUTED world height (terrain_authority.posture_kinematics: arm angles + slope + posture pitch + mount).
Cameras stay faithfully oriented (the Godot rig applies each extrinsic; drum cams track the live arms).

Reusable sim view:
  python3 posture_camera_gif.py --from TRANSIT --to MEERKAT --steps 10 --output /tmp/posture_cams.gif
"""
import argparse
import math
import os
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))   # dustgym root for terrain_authority
from stewie.physics import posture_kinematics as pk          # noqa: E402
from stewie.physics.postures import get_posture              # noqa: E402

# 4x2 pane layout (front row, rear row)
PANES = ["front_left", "front_right", "left_mono", "drum_front_cam",
         "rear_left", "rear_right", "right_mono", "drum_back_cam"]


def _lerp(a, b, t):
    return a + (b - a) * t


def main(argv=None):
    ap = argparse.ArgumentParser(description="8-pane posture-transition camera GIF (faithful).")
    ap.add_argument("--from", dest="p_from", default="TRANSIT")
    ap.add_argument("--to", dest="p_to", default="MEERKAT")
    ap.add_argument("--steps", type=int, default=10)
    ap.add_argument("--scene", default="../samples/crater_boulders")
    ap.add_argument("--rover-rc", default="110,70")
    ap.add_argument("--sun-elev", type=float, default=5.0)     # faithful lunar polar grazing default
    ap.add_argument("--sun-azim", type=float, default=215.0)
    ap.add_argument("--slope-along-deg", type=float, default=0.0)
    ap.add_argument("--size", default="256x192")
    ap.add_argument("--delay", type=int, default=45)
    ap.add_argument("--output", required=True)
    a = ap.parse_args(argv)

    pa, pb = get_posture(a.p_from), get_posture(a.p_to)
    work = a.output + ".frames"
    os.makedirs(work, exist_ok=True)
    cam_out = os.path.join(_HERE, "out", "cam", os.path.basename(a.scene), "000")
    panels = []
    for i in range(a.steps):
        t = i / max(1, a.steps - 1)
        af = _lerp(pa.arm_front_pitch_rad, pb.arm_front_pitch_rad, t)
        ab = _lerp(pa.arm_back_pitch_rad, pb.arm_back_pitch_rad, t)
        lift = pk.chassis_lift_m(af, ab)
        heights = pk.camera_heights_m(af, ab, slope_along_rad=math.radians(a.slope_along_deg))
        r = subprocess.run([os.path.join(_HERE, "render_layers.sh"), "--", "--scene", a.scene,
                            "--cameras", "--layers", "terrain,clasts,rover", "--rover-rc", a.rover_rc,
                            "--arm-front-pitch", f"{af:.4f}", "--arm-back-pitch", f"{ab:.4f}",
                            "--chassis-lift", f"{lift:.4f}", "--sun-elev", f"{a.sun_elev}",
                            "--sun-azim", f"{a.sun_azim}", "--size", a.size],
                           cwd=_HERE, capture_output=True, text=True, timeout=200)
        if r.returncode != 0:
            print(f"step {i}: render failed\n{r.stderr[-400:]}"); return 1
        # labelled 4x2 montage of the 8 panes (camera name + computed height)
        cmd = ["montage"]
        for name in PANES:
            cmd += ["-label", f"{name}  h={heights[name]:+.2f}m", os.path.join(cam_out, f"{name}.png")]
        panel = os.path.join(work, f"panel_{i:03d}.png")
        cmd += ["-tile", "4x2", "-geometry", "+4+4", "-background", "black", "-fill", "white",
                "-pointsize", "13", "-title",
                f"{a.p_from} -> {a.p_to}  step {i+1}/{a.steps}  arms=({af:+.2f},{ab:+.2f}) rad  "
                f"lift={lift:.3f} m  sun {a.sun_elev:.0f} deg (faithful)", panel]
        subprocess.run(cmd, check=True, timeout=120)
        panels.append(panel)
        print(f"step {i+1}/{a.steps}: arms=({af:+.2f},{ab:+.2f}) lift={lift:.3f}m")

    # ping-pong so the loop shows the transition both ways, then assemble the GIF
    seq = panels + panels[-2:0:-1]
    subprocess.run(["convert", "-delay", str(a.delay), "-loop", "0"] + seq + [a.output], check=True, timeout=180)
    print(f"GIF: {a.output} ({os.path.getsize(a.output)} bytes, {len(seq)} frames)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
