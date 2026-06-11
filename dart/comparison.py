"""ARGUS vs the LAC state of the art: a grounded comparison framework.

Two reference systems anchor the comparison (compared as APPROACH CLASSES on the shared LAC/IPEx
testbed -- their actual stacks are not run; in-tree representatives of each class are):

  * Stanford NAV Lab (LAC 1st place, Dai et al., arXiv:2603.17232): passive stereo VO + pose-graph
    SLAM + semantic rock mapping. Representative: dart.pose_graph_se2 over odometry/VO (passive,
    relative). Builds the map online; no orbital prior; drives; no shadow geometry; passive.
  * ShadowNav (JPL, Verma/Maimone et al., arXiv:2405.01673; crater work arXiv:2301.04630): GLOBAL
    localization in darkness by matching crater leading edges to an offboard orbital map with a
    particle filter, using the rover's own illumination. Representative: dart.localization.register_to_dem
    (match a local terrain patch to the orbital DEM for a global fix). Needs the orbital prior; drives;
    shadow used as an APPEARANCE feature for matching; passive (own light, not posture).

ARGUS contributes what neither has: the shadow as a GEOMETRIC instrument (azimuth->heading SN-03,
self-shadow length change->sun-el/slope SN-09, articulation parallax->range/standstill fix SN-10) and
ACTIVE MORPHOLOGY (a commanded posture creates the baseline/observation). The three are largely
COMPLEMENTARY -- ShadowNav coarse-global-map-match, Stanford passive-relative-VO, ARGUS active-local-
geometric + direct heading. Real DEM + real geometry; no fabricated comparison.
"""
from __future__ import annotations

import numpy as np

from dart import articulated_parallax as AP
from dart.localization import register_to_dem


def nav_capability_matrix() -> dict:
    """The grounded structural positioning of the three approach classes (attributes from the cited
    papers). Capabilities, not a single score -- the systems target different regimes."""
    return {
        "Stanford NAV Lab (LAC)": {
            "paper": "arXiv:2603.17232", "scope": "local map + relative nav (27x27 m)",
            "needs_orbital_prior": False, "builds_map_online": True, "motion": "driving",
            "heading_source": "stereo VO + pose-graph", "illumination": "passive sunlit",
            "shadow_role": "none (semantic rocks)", "active_reconfiguration": False},
        "ShadowNav (JPL)": {
            "paper": "arXiv:2405.01673", "scope": "global localization in darkness",
            "needs_orbital_prior": True, "builds_map_online": False, "motion": "driving",
            "heading_source": "from global map-match", "illumination": "darkness + own light",
            "shadow_role": "crater-edge appearance feature for matching", "active_reconfiguration": False},
        "ARGUS": {
            "paper": "this work", "scope": "drift-bounded nav + shadow as instrument",
            "needs_orbital_prior": False, "builds_map_online": True, "motion": "standstill maneuver",
            "heading_source": "shadow azimuth (direct, SN-03)", "illumination": "low-sun grazing shadows",
            "shadow_role": "GEOMETRIC measurement (azimuth/length/parallax)", "active_reconfiguration": True},
    }


def compare_position_fix(dem, true_rc, landmarks_xy, *, cell_m, dh_m, fx_px, sigma_px=0.3,
                         guess_offset_cells=3):
    """Head-to-head position-fix error on ONE real scene: the ShadowNav-class map-match
    (register_to_dem) vs the ARGUS articulation parallax. Returns {approach: error_m, ...}. The
    Stanford-class passive baseline has no standalone absolute fix here (it is relative VO), so it is
    reported as map-dependent/relative, not a single number."""
    Z = np.asarray(dem, float)
    tr, tc = int(true_rc[0]), int(true_rc[1])
    # ShadowNav-class: a local terrain patch matched back into the orbital DEM (a global fix)
    half = 12
    observed = Z[tr - half:tr + half + 1, tc - half:tc + half + 1]   # odd square (2*half+1)
    guess = (tr + guess_offset_cells, tc + guess_offset_cells)
    reg = register_to_dem(observed, (Z, cell_m), guess, search_radius_cells=max(5, guess_offset_cells + 2))
    mr, mc = reg["corrected_rc"]
    err_shadownav = float(np.hypot(mr - tr, mc - tc) * cell_m)
    # ARGUS: articulation parallax -> ranges -> trilateration (map-free, heading-free)
    true_xy = np.array([tc * cell_m, tr * cell_m])
    L = np.asarray(landmarks_xy, float)
    shifts = [AP.pixel_shift_for_range(dh_m, float(np.hypot(*(true_xy - Li))), fx_px) for Li in L]
    ranges = [AP.range_from_pixel_parallax(dh_m, s, fx_px) for s in shifts]
    fix = AP.position_fix_from_ranges(L, ranges, guess=(true_xy[0] + 1.0, true_xy[1] + 1.0))
    err_argus = float(np.hypot(fix[0] - true_xy[0], fix[1] - true_xy[1]))
    return {"ShadowNav-class (map-match)": err_shadownav, "ARGUS (articulation parallax)": err_argus,
            "Stanford-class (passive VO)": None}
