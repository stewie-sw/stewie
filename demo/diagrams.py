#!/usr/bin/env python3
"""Presentation diagrams:
  variables_diagram.png : the REAL Godot front-left image annotated with the geometry
                          variables -- camera height, Sun elevation, cast-shadow length,
                          and the H = L*tan(e) relation.
  dem_2d_3d.png         : the REAL Haworth south-pole DEM as a 2D hillshade map (left)
                          and a 3D wireframe heightmap (right) -- the 2D->3D map tier.
"""
import os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LightSource

from solnav.bridge import dustgym_io
from solnav.geometry import dem, shadow
from solnav.perception import stereo_depth

FOSS = "/mnt/projects/foss_ipex"
SENSORS = FOSS + "/roversim/godot_sidecar/out/cam/crater_boulders/000/sensors.json"
DEM_DIR = FOSS + "/dustgym/samples/lunar_dem/haworth_10km_5m"
OUT = os.path.join(os.path.dirname(__file__), "out")
os.makedirs(OUT, exist_ok=True)


def variables_diagram(path):
    frame = dustgym_io.read_sensors(SENSORS)
    img = stereo_depth.to_gray(dustgym_io.load_camera_image(SENSORS, "front_left"))
    e = frame.sun_elevation_deg or 5.0
    az = frame.sun_azimuth_deg or 215.0
    H, W = img.shape
    fig, ax = plt.subplots(figsize=(10, 7))
    ax.imshow(img, cmap="gray"); ax.set_xlim(0, W); ax.set_ylim(H, 0)

    # camera height (left vertical arrow)
    ax.annotate("", xy=(40, H * 0.35), xytext=(40, H * 0.92),
                arrowprops=dict(arrowstyle="<->", color="#ffcd00", lw=2))
    ax.text(52, H * 0.63, "camera height $H_{cam}$\n(posture-dependent;\n- Bekker sinkage)",
            color="#ffcd00", fontsize=10, va="center")

    # Sun glyph + elevation angle
    sx, sy = W * 0.86, H * 0.12
    ax.plot(sx, sy, marker="o", ms=22, color="#ffcd00", markeredgecolor="orange")
    ax.annotate("", xy=(sx - 130, sy + 130 * np.tan(np.radians(e))), xytext=(sx, sy),
                arrowprops=dict(arrowstyle="->", color="#ffcd00", lw=2))
    ax.text(sx - 10, sy - 18, f"Sun: elev $e$={e:.0f}°, az={az:.0f}°\n(low-Sun regime)",
            color="#ffcd00", fontsize=10, ha="right")

    # cast-shadow length bracket near the lit structure (schematic location)
    y0 = H * 0.74
    ax.annotate("", xy=(W * 0.40, y0), xytext=(W * 0.62, y0),
                arrowprops=dict(arrowstyle="<->", color="#5aa469", lw=2))
    ax.text(W * 0.51, y0 + 24, "cast-shadow length $L$", color="#5aa469", fontsize=10, ha="center")

    # the relation box
    Lex = shadow.shadow_length_from_height(0.5, e)
    ax.text(W * 0.30, H * 0.06,
            f"$H = L\\,\\tan(e)$   |   shadow azimuth $=$ Sun az $+180\\degree$\n"
            f"at $e$={e:.0f}° a 0.5 m feature casts $L$={Lex:.1f} m of shadow",
            color="white", fontsize=11, bbox=dict(boxstyle="round", fc="#005587", alpha=0.85))
    ax.set_title("Navigation geometry variables on a REAL Godot frame", fontsize=12)
    ax.axis("off")
    fig.tight_layout(); fig.savefig(path, dpi=140); plt.close(fig)


def dem_2d_3d(path, size_m=300.0):
    H, posting, meta = dem.load_dem(DEM_DIR)
    patch, _, n = dem.crop_meters(H, posting, size_m)
    x = np.arange(n) * posting; y = np.arange(n) * posting
    Xg, Yg = np.meshgrid(x, y)
    fig = plt.figure(figsize=(13, 5.5))
    # 2D hillshade map
    ax1 = fig.add_subplot(1, 2, 1)
    ls = LightSource(azdeg=315, altdeg=30)
    ax1.imshow(ls.hillshade(patch, vert_exag=2.0, dx=posting, dy=posting), cmap="gray",
               extent=[0, n * posting, 0, n * posting])
    ax1.set_title(f"2D DEM map (Haworth, {n*posting:.0f}x{n*posting:.0f} m hillshade)")
    ax1.set_xlabel("m"); ax1.set_ylabel("m")
    # 3D wireframe heightmap
    ax2 = fig.add_subplot(1, 2, 2, projection="3d")
    s = max(1, n // 40)
    ax2.plot_wireframe(Xg[::s, ::s], Yg[::s, ::s], patch[::s, ::s], color="#004e42", lw=0.5)
    ax2.set_title("3D wireframe heightmap (same tile)")
    ax2.set_xlabel("m"); ax2.set_ylabel("m"); ax2.set_zlabel("elev (m)")
    ax2.view_init(elev=35, azim=-58)
    fig.suptitle("2D map -> 3D rendering: REAL Haworth south-pole DEM", fontsize=12)
    fig.tight_layout(); fig.savefig(path, dpi=140); plt.close(fig)


if __name__ == "__main__":
    variables_diagram(os.path.join(OUT, "variables_diagram.png"))
    dem_2d_3d(os.path.join(OUT, "dem_2d_3d.png"))
    print("wrote", OUT + "/variables_diagram.png", "and", OUT + "/dem_2d_3d.png")
