"""Operational rock taxonomy: simultaneous nav/loc/excav classes + shadow-height physics. No synthetic."""
import math

from dart import rock_taxonomy as RT


def test_70cm_boulder_is_hazard_landmark_and_avoid():
    r = RT.classify(0.70)                    # the user's example: one rock, three meanings
    assert r.nav_class == "E" and r.loc_class == "L2" and r.excav_class == "E3"
    m = r.meanings()
    assert "no-go" in m["navigation"] and "persistent" in m["localization"] and "avoid" in m["excavation"]


def test_small_rock_all_ignore():
    r = RT.classify(0.06)
    assert (r.nav_class, r.loc_class, r.excav_class) == ("A", "L0", "E0")


def test_midsize_40cm():
    r = RT.classify(0.40)
    assert (r.nav_class, r.loc_class, r.excav_class) == ("D", "L1", "E2")


def test_nav_boundary_is_7cm_avoid_threshold():
    # anything ABOVE 7 cm is avoided (0.5 cm margin under the 7.5 cm clearance); <= 7 cm is traversable
    assert RT.classify(0.069).nav_class == "A" and not RT.classify(0.069).is_obstacle
    assert RT.classify(0.072).nav_class == "B" and RT.classify(0.072).is_obstacle
    assert RT.classify(0.072).excav_class == "E1"            # E0 regolith boundary also at 7 cm
    assert RT.AVOID_THRESHOLD_M == 0.07 and RT.IPEX_STEP_OVER_M == 0.075


def test_shadow_height_grazing_sun():
    assert abs(RT.shadow_height_m(2.0, 5.0) - 2.0 * math.tan(math.radians(5))) < 1e-12
    assert RT.shadow_height_m(2.0, 5.0) > 0.17          # long shadow -> resolvable height at the pole


def test_from_detection_with_shadow():
    # rover-cam GSD ~0.5 cm/px: a 30 px box -> 0.15 m (fine bins are ROVER-scale; orbital NAC only
    # resolves >1-2 m boulders, all E/L2/E3). 40 px shadow @ 5 deg sun -> a real height.
    r = RT.from_detection_px((10, 10, 40, 40), 0.9, 0.005, shadow_length_px=40, sun_elevation_deg=5)
    assert abs(r.diameter_m - 0.15) < 1e-6 and r.height_source == "shadow" and r.height_m > 0
    assert r.nav_class == "C" and r.volume_m3 > 0 and r.confidence == 0.9   # 0.15 m -> C (B/C edge excl.)


def test_tall_narrow_rock_is_an_obstacle():
    # audit 2026-06-09: nav class was diameter-only -- a known-tall narrow rock binned drive-over
    from dart import rock_taxonomy as RT
    r = RT.classify(0.05, height_m=0.10, height_source="stereo")   # d=5cm but h=10cm > 7.5cm clearance
    assert r.nav_class != "A" and r.is_obstacle
    r2 = RT.classify(0.05, height_m=0.03, height_source="stereo")  # genuinely small in BOTH dims
    assert r2.nav_class == "A" and not r2.is_obstacle
