"""Classify rocks across a SIMULATION PLAYTHROUGH.

As the rover drives, every stereo frame is run through detect -> stereo-size (obstacle_map) -> operational
classes (rock_taxonomy), giving the semantic Rock world model the navigation/excavation autonomy reasons
over. Height is fused from the best available source: stereo for the rover's oblique view, the cast shadow
(H = L*tan(e)) when the sun is grazing and the GSD is known (nadir/descent). Real renders only.
"""
from __future__ import annotations

import os

import cv2

from . import obstacle_map, rock_taxonomy, shadow_height


def estimate_rock(diameter_m: float, score: float, *, height_m: float | None = None, gray=None,
                  u: float | None = None, v: float | None = None, m_per_px: float | None = None,
                  sun_azimuth_deg: float | None = None, sun_elevation_deg: float | None = None,
                  grazing_max_deg: float = 15.0) -> rock_taxonomy.Rock:
    """Per-rock size fusion -> one operational Rock. Diameter is given (stereo/pixel). Height comes from
    the cast shadow when the sun is grazing and a GSD is supplied (H = L*tan(e)); else the caller's
    stereo/DEM height; else an aspect default. Classes (nav/loc/excav) key on diameter."""
    src = "aspect_default"
    if height_m is not None:
        src = "stereo_or_dem"
    # shadow sizing only FILLS A GAP: it is the documented honest-negative channel on renders, so it
    # must never overwrite a VALIDATED stereo/DEM height (audit M33). Explicit None tests so 0.0
    # values are not silently treated as missing (audit L37).
    if (height_m is None and gray is not None and m_per_px is not None and m_per_px > 0
            and sun_elevation_deg is not None and 0 < sun_elevation_deg <= grazing_max_deg
            and sun_azimuth_deg is not None and u is not None and v is not None):
        h, _ = shadow_height.estimate_height_m(gray, u, v, sun_azimuth_deg=sun_azimuth_deg,
                                               sun_elevation_deg=sun_elevation_deg, m_per_px=m_per_px)
        if h:
            height_m, src = h, "shadow"
    return rock_taxonomy.classify(diameter_m, height_m=height_m, confidence=score, height_source=src)


def classify_stereo_frame(left, right, *, hfov_deg: float = 73.99, baseline_m: float = 0.07,
                          sun_azimuth_deg=None, sun_elevation_deg=None, m_per_px=None) -> list:
    """One playthrough stereo frame -> [(SizedObstacle, Rock)]. Diameter from stereo (correct for the
    rover's oblique view); operational nav/loc/excav classes attached."""
    sized = obstacle_map.classify(left, right, hfov_deg=hfov_deg, baseline_m=baseline_m)
    gray = cv2.cvtColor(left, cv2.COLOR_BGR2GRAY) if left.ndim == 3 else left
    out = []
    for s in sized:
        rock = estimate_rock(s.diameter_m, 1.0, gray=gray, u=s.u, v=s.v, m_per_px=m_per_px,
                             sun_azimuth_deg=sun_azimuth_deg, sun_elevation_deg=sun_elevation_deg)
        out.append((s, rock))
    return out


def classify_traverse(traverse_dir: str, *, hfov_deg: float = 73.99, baseline_m: float = 0.07,
                      sun_azimuth_deg=None, sun_elevation_deg=None, cameras=("front_left", "front_right")):
    """Run the classifier over every frame of a rendered traverse playthrough. Returns
    (per_frame: list[list[(SizedObstacle, Rock)]], world_summary: dict counting nav classes seen)."""
    import glob
    frames = sorted(glob.glob(os.path.join(traverse_dir, "cam", "frame_*")))
    per_frame, summary = [], {c: 0 for c in "ABCDE"}
    for fdir in frames:
        lp = os.path.join(fdir, cameras[0] + ".png")
        rp = os.path.join(fdir, cameras[1] + ".png")
        left, right = cv2.imread(lp), cv2.imread(rp)
        if left is None or right is None:
            continue
        rocks = classify_stereo_frame(left, right, hfov_deg=hfov_deg, baseline_m=baseline_m,
                                      sun_azimuth_deg=sun_azimuth_deg, sun_elevation_deg=sun_elevation_deg)
        for _s, rk in rocks:
            summary[rk.nav_class] = summary.get(rk.nav_class, 0) + 1
        per_frame.append(rocks)
    return per_frame, summary


_NAV_BGR = {"A": (0, 220, 0), "B": (0, 235, 235), "C": (0, 165, 255), "D": (0, 100, 255), "E": (0, 0, 255)}


def draw_classified(left, rocks):
    """Overlay a frame's classified rocks: box colored by nav class + diameter label (cm)."""
    vis = left.copy() if left.ndim == 3 else cv2.cvtColor(left, cv2.COLOR_GRAY2BGR)
    for s, rk in rocks:
        col = _NAV_BGR.get(rk.nav_class, (255, 255, 255))
        x0, y0 = int(s.u - s.radius_px), int(s.v - s.radius_px)
        x1, y1 = int(s.u + s.radius_px), int(s.v + s.radius_px)
        cv2.rectangle(vis, (x0, y0), (x1, y1), col, 1)
        cv2.putText(vis, f"{rk.nav_class}{rk.diameter_m * 100:.0f}", (x0, y0 - 2),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.3, col, 1)
    return vis
