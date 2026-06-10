"""#57: perception-gated actions -- DockWithLander validated against the SHADOW TRUTH.

The design (PLANNING_REVISION 2026-06-10 §2): an action type declares its perception
preconditions; the planner consults the illumination authority AT THE ACTION'S TIME AND PLACE.
A dock needs the AprilTag VISIBLE: tag-lock requires light. Docking in shadow fails validation
-- the truth cells come from the horizon-clip mask itself (truth-derived, never guessed).
"""
import numpy as np
import pytest

from lode import actions as ACT
from lode import mission_planner as MP


@pytest.fixture(scope="module")
def lit_and_shadowed():
    dem, cell = MP.load_haworth_dem()
    from dart.illumination import horizon_clip
    sub = np.asarray(dem, dtype=float)[::4, ::4]           # working grid (the full clip is slow)
    lit = horizon_clip(sub, cell * 4, 90.0, 6.0)
    ys, xs = np.where(lit); ds, dxs = np.where(~lit)
    assert len(ys) and len(ds)                             # both states exist at this sun
    i = len(ys) // 2; j = len(ds) // 2
    to_m = lambda r, c: (float(c) * cell * 4, float(r) * cell * 4)
    return {"dem": (sub, cell * 4), "lit_xy": to_m(ys[i], xs[i]), "dark_xy": to_m(ds[j], dxs[j]),
            "sun": (90.0, 6.0)}


def test_dock_in_the_light_passes(lit_and_shadowed):
    s = lit_and_shadowed
    out = ACT.validate_dock(s["lit_xy"], dem_pair=s["dem"], sun_az=s["sun"][0], sun_el=s["sun"][1])
    assert out["ok"] and out["illuminated"] is True
    assert out["phases"] == ["goto_coarse", "acquire_tag", "visual_servo", "dock"]


def test_dock_in_shadow_fails_validation(lit_and_shadowed):
    s = lit_and_shadowed
    out = ACT.validate_dock(s["dark_xy"], dem_pair=s["dem"], sun_az=s["sun"][0], sun_el=s["sun"][1])
    assert out["ok"] is False and out["illuminated"] is False
    assert "shadow" in out["reason"].lower()               # the precondition speaks plainly


def test_dock_beyond_tag_resolvability_fails(lit_and_shadowed):
    s = lit_and_shadowed
    out = ACT.validate_dock(s["lit_xy"], dem_pair=s["dem"], sun_az=s["sun"][0], sun_el=s["sun"][1],
                            approach_from_xy=(s["lit_xy"][0] + 5000.0, s["lit_xy"][1]))
    assert out["ok"] and any("beyond tag acquisition" in w for w in out["warnings"])
