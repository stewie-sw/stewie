#!/usr/bin/env python3
"""Kinematic wireframe GIFs for presentations (driven by the real FK + FOV models).

  postures.gif : 3D rover wireframe morphing TRANSIT -> COBRA -> MEERKAT -> IRON_CROSS,
                 annotated with chassis lift + pitch from forward_kinematics.
  spin.gif     : top-down rover spinning relative to the lander; front/side camera FOV
                 wedges sweep, the body turns green when a camera frames the lander tag.

Schematic dimensions are the [CONFIRM] GLB-envelope estimates in kinematics.py.
"""
import os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import imageio.v2 as imageio

from solnav.posture import wireframe, kinematics as kin
from solnav.geometry import fov

OUT = os.path.join(os.path.dirname(__file__), "out")
os.makedirs(OUT, exist_ok=True)


def _frame(fig):
    fig.canvas.draw()
    return np.asarray(fig.canvas.buffer_rgba()).copy()


def _interp_keyframes(keys, steps=14):
    seq = []
    for (a0, b0), (a1, b1) in zip(keys[:-1], keys[1:]):
        for t in np.linspace(0, 1, steps, endpoint=False):
            seq.append((a0 + (a1 - a0) * t, b0 + (b1 - b0) * t))
    seq.append(keys[-1])
    return seq


def postures_gif(path):
    keys = [kin.POSTURES[n] for n in ("TRANSIT", "COBRA", "MEERKAT", "IRON_CROSS")]
    seq = _interp_keyframes(keys + keys[::-1], steps=12)
    frames = []
    fig = plt.figure(figsize=(6, 5))
    for af, ar in seq:
        ax = fig.add_subplot(111, projection="3d")
        polys, meta = wireframe.rover_skeleton(af, ar)
        for p in polys:
            ax.plot(p[:, 0], p[:, 1], p[:, 2], color="#004e42", lw=1.3)
        ax.set_xlim(-0.8, 0.8); ax.set_ylim(-0.8, 0.8); ax.set_zlim(0, 1.0)
        ax.set_box_aspect((1, 1, 0.7)); ax.view_init(elev=16, azim=-62)
        ax.set_title(f"{meta['name']}  arms=({af:.0f},{ar:.0f})  "
                     f"lift={meta['lift_m']:.2f} m  pitch={meta['pitch_deg']:.0f} deg",
                     fontsize=10)
        ax.set_xlabel("fore (m)"); ax.set_zlabel("up (m)")
        frames.append(_frame(fig)); fig.clf()
    plt.close(fig)
    imageio.mimsave(path, frames, duration=0.08, loop=0)
    return len(frames)


def spin_gif(path, lander_bearing=40.0, lander_dist=2.5):
    hfov = fov.hfov_deg_from_intrinsics(1024, 679.57)
    cams = {"front": 0.0, "left": 90.0, "right": -90.0, "rear": 180.0}
    detect = fov.tag_detectable(0.15, lander_dist, 679.57)
    frames = []
    fig = plt.figure(figsize=(5, 5))
    for yaw in range(0, 360, 10):
        ax = fig.add_subplot(111)
        usable = any(fov.in_fov(lander_bearing, yaw, off, hfov) for off in cams.values()) and detect
        # rover body (rotated rectangle)
        L, W = kin.WHEELBASE_M, kin.TRACK_M
        c = np.array([[-L/2, -W/2], [L/2, -W/2], [L/2, W/2], [-L/2, W/2], [-L/2, -W/2]])
        th = np.radians(yaw); Rm = np.array([[np.cos(th), -np.sin(th)], [np.sin(th), np.cos(th)]])
        b = c @ Rm.T
        ax.fill(b[:, 0], b[:, 1], color="#5aa469" if usable else "#999999", alpha=0.7)
        # camera FOV wedges
        for name, off in cams.items():
            a0 = np.radians(yaw + off - hfov / 2); a1 = np.radians(yaw + off + hfov / 2)
            aa = np.linspace(a0, a1, 12); r = 1.6
            wedge = np.concatenate([[[0, 0]], np.stack([r*np.cos(aa), r*np.sin(aa)], 1), [[0, 0]]])
            ax.plot(wedge[:, 0], wedge[:, 1], color="#005587", lw=0.6, alpha=0.5)
        # lander marker (fixed world bearing)
        lb = np.radians(lander_bearing)
        ax.plot(lander_dist*np.cos(lb), lander_dist*np.sin(lb), marker="*", ms=16, color="#ffcd00",
                markeredgecolor="k")
        ax.text(lander_dist*np.cos(lb), lander_dist*np.sin(lb)+0.15, "lander", ha="center", fontsize=8)
        ax.set_xlim(-3, 3); ax.set_ylim(-3, 3); ax.set_aspect("equal")
        ax.set_title(f"rover yaw {yaw} deg  -  lander {'FRAMED' if usable else 'not framed'}", fontsize=10)
        frames.append(_frame(fig)); fig.clf()
    plt.close(fig)
    imageio.mimsave(path, frames, duration=0.1, loop=0)
    return len(frames)


if __name__ == "__main__":
    n1 = postures_gif(os.path.join(OUT, "postures.gif"))
    n2 = spin_gif(os.path.join(OUT, "spin.gif"))
    print(f"postures.gif: {n1} frames -> {OUT}/postures.gif")
    print(f"spin.gif: {n2} frames -> {OUT}/spin.gif")
