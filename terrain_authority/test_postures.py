"""IPEx posture definitions load + validate (data-driven morphology for posture-conditioned views)."""
import pytest

from terrain_authority import postures as P

_EXPECTED = {"TRANSIT", "DIG", "DUMP_Z", "MEERKAT", "DRUM_WALK", "IRON_CROSS",
             "SELF_RIGHT", "BRAKED_HOLD", "COBRA"}


def test_all_postures_load_with_required_fields():
    ps = P.load_postures()
    assert _EXPECTED <= set(ps)
    for name, p in ps.items():
        assert isinstance(p.arm_front_pitch_rad, float) and isinstance(p.arm_back_pitch_rad, float)
        assert p.provenance and ("ASSUMPTION" in p.provenance or "SOURCED" in p.provenance)


def test_meerkat_raises_camera_vantage():
    # the AM-03 property: MEERKAT lifts the chassis -> higher camera vantage than TRANSIT
    ps = P.load_postures()
    assert ps["MEERKAT"].camera_vantage_m > ps["TRANSIT"].camera_vantage_m
    assert ps["MEERKAT"].chassis_lift_m > 0.0


def test_postures_have_distinct_arm_geometry():
    ps = P.load_postures()
    geoms = {(p.arm_front_pitch_rad, p.arm_back_pitch_rad) for p in ps.values()}
    assert len(geoms) >= 6                       # postures are genuinely different morphologies


def test_unknown_posture_raises():
    with pytest.raises(KeyError, match="unknown posture"):
        P.get_posture("BANANA")
