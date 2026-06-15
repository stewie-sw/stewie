"""SLAM-04: URDF/forward-kinematics is the SOLE authority for posture geometry.

Audit SLAM-04: the authored per-posture chassis_lift_m / camera_vantage_m constants disagreed with the
forward-kinematics (arm pitch -> chassis lift) by >2 cm for 6 of 9 postures (MEERKAT 7.6 cm, SELF_RIGHT
11.5 cm, COBRA 10.5 cm, IRON_CROSS 5 cm, DRUM_WALK 3.7 cm, BRAKED_HOLD 3 cm). The geometry was already
COMPUTED from FK (and the authored constant ignored), but the stale second source remained in the data
and only triggered a soft warning. Fix: remove the dead authored constants (FK is the single source)
and PROMOTE the contradiction check to a hard load-time gate, so no posture can carry a geometry that
silently diverges from its kinematics. Plus a reprojection/range round-trip that locks the FK lift as
the geometry the parallax instrument actually depends on.
"""
from __future__ import annotations

import json
import warnings

import pytest

from dart.articulated_parallax import range_from_pixel_parallax
from dart.articulated_shadow import dh_from_posture
from stewie.physics import posture_kinematics as pk
from stewie.physics import postures as P


def test_json_carries_no_authored_lift_constants():
    # FK is the sole authority -> the data must not carry a second (divergeable) source
    doc = json.load(open(P._PATH))
    for name, p in doc["postures"].items():
        assert "chassis_lift_m" not in p, f"{name} still carries an authored chassis_lift_m (SLAM-04)"
        assert "camera_vantage_m" not in p, f"{name} still carries an authored camera_vantage_m (SLAM-04)"


def test_real_postures_load_clean_and_lift_equals_fk():
    # the real data loads with NO contradiction warning, and every lift is the FK value
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        ps = P.load_postures()
    for name, post in ps.items():
        fk = pk.chassis_lift_m(post.arm_front_pitch_rad, post.arm_back_pitch_rad)
        assert abs(post.chassis_lift_m - fk) < 1e-9, f"{name}: lift {post.chassis_lift_m} != FK {fk}"
        assert abs(post.camera_vantage_m - fk) < 1e-9, f"{name}: vantage != FK"


def test_load_rejects_authored_lift_that_contradicts_fk(tmp_path):
    # a JSON that reintroduces a contradicting authored constant must FAIL the load (hard gate),
    # not silently use the FK value behind a warning.
    bad = {
        "schema_version": "ipex_postures/1.0",
        "postures": {
            "BOGUS": {
                "arm_front_pitch_rad": -1.0, "arm_back_pitch_rad": -1.0,
                "chassis_lift_m": 0.25,        # FK for (-1,-1) ~ 0.174 m -> 7.6 cm contradiction
                "stability": "nominal", "provenance": "[TEST] deliberate contradiction",
            },
        },
    }
    p = tmp_path / "bad_postures.json"
    p.write_text(json.dumps(bad))
    with pytest.raises(ValueError, match="contradict"):
        P.load_postures(str(p))


def test_load_accepts_authored_lift_that_matches_fk(tmp_path):
    # a faithful authored constant (within tolerance of FK) still loads -- the gate only rejects divergence
    fk = pk.chassis_lift_m(-1.0, -1.0)
    ok = {
        "schema_version": "ipex_postures/1.0",
        "postures": {
            "FAITHFUL": {
                "arm_front_pitch_rad": -1.0, "arm_back_pitch_rad": -1.0,
                "chassis_lift_m": round(fk, 3),
                "stability": "nominal", "provenance": "[TEST] matches FK",
            },
        },
    }
    p = tmp_path / "ok_postures.json"
    p.write_text(json.dumps(ok))
    ps = P.load_postures(str(p))
    assert abs(ps["FAITHFUL"].chassis_lift_m - fk) < 1e-9


def test_dh_from_posture_is_the_fk_lift_difference():
    dh = dh_from_posture("TRANSIT", "MEERKAT")
    expect = (pk.chassis_lift_m(*_angles("MEERKAT")) - pk.chassis_lift_m(*_angles("TRANSIT")))
    assert abs(dh - expect) < 1e-9
    assert dh > 0.0, "MEERKAT must raise the camera above TRANSIT"


@pytest.mark.parametrize("range_m", [2.0, 5.0, 12.0, 30.0])
def test_parallax_range_roundtrips_through_the_fk_lift(range_m):
    # reprojection/range residual gate: the FK lift IS the baseline the parallax instrument uses, so a
    # landmark at range R projecting a pixel shift fx*dh/R must invert back to R with ~zero residual.
    dh = dh_from_posture("TRANSIT", "MEERKAT")
    fx = 800.0
    pixel_shift = fx * dh / range_m                          # pinhole forward projection
    recovered = range_from_pixel_parallax(dh, pixel_shift, fx)
    assert abs(recovered - range_m) < 1e-6, f"range residual {abs(recovered - range_m)} m"


def _angles(name: str):
    post = P.get_posture(name)
    return post.arm_front_pitch_rad, post.arm_back_pitch_rad
