"""#91 (SN-07): the LED-budget selection policy. Pure + deterministic over the real 8-cam rig azimuths;
no fabricated photometry -- the alignment is geometric (cos of the camera-vs-shadow azimuth separation)."""
import pytest

from dart import led_budget as LB


def test_dead_ahead_shadow_picks_the_front_camera_and_fully_lights_it():
    s = LB.select_led_budget([(0.0, 1.0)], active_cam_limit=2, power_budget_w=20.0, led_max_w=10.0)
    assert s["n_cameras"] >= 1
    assert s["selected"][0]["camera"].startswith("front") or s["selected"][0]["camera"] == "arm_front"
    assert s["uncovered_need"] == pytest.approx(0.0)       # a front LED at full intensity covers az=0
    assert s["illuminated_need"] == pytest.approx(1.0)


def test_rear_shadow_picks_a_rear_facing_camera():
    s = LB.select_led_budget([(180.0, 1.0)], active_cam_limit=1, power_budget_w=10.0, led_max_w=10.0)
    az = LB.CAMERA_RIG[s["selected"][0]["camera"]][0]
    assert abs((az - 180.0 + 180.0) % 360.0 - 180.0) < 1e-6   # a camera facing ~180 deg


def test_two_opposed_shadows_use_two_cameras_within_the_active_limit():
    s = LB.select_led_budget([(0.0, 1.0), (180.0, 1.0)], active_cam_limit=2, power_budget_w=20.0, led_max_w=10.0)
    assert s["n_cameras"] == 2
    assert s["uncovered_need"] == pytest.approx(0.0, abs=1e-6)


def test_active_camera_limit_caps_coverage():
    one = LB.select_led_budget([(0.0, 1.0), (180.0, 1.0)], active_cam_limit=1, power_budget_w=20.0, led_max_w=10.0)
    two = LB.select_led_budget([(0.0, 1.0), (180.0, 1.0)], active_cam_limit=2, power_budget_w=20.0, led_max_w=10.0)
    assert one["n_cameras"] == 1 and two["n_cameras"] == 2
    assert one["uncovered_need"] > two["uncovered_need"]   # one camera can't light both opposed shadows


def test_power_budget_caps_intensity_and_coverage():
    full = LB.select_led_budget([(0.0, 1.0)], active_cam_limit=1, power_budget_w=10.0, led_max_w=10.0)
    half = LB.select_led_budget([(0.0, 1.0)], active_cam_limit=1, power_budget_w=5.0, led_max_w=10.0)
    assert half["selected"][0]["intensity"] == pytest.approx(0.5)   # only half the watts -> half intensity
    assert half["uncovered_need"] > full["uncovered_need"]          # partial light leaves residual need
    assert half["power_used_w"] == pytest.approx(5.0)


def test_zero_budget_lights_nothing():
    s = LB.select_led_budget([(0.0, 1.0)], active_cam_limit=2, power_budget_w=0.0)
    assert s["n_cameras"] == 0 and s["uncovered_need"] == pytest.approx(1.0)


def test_rejects_nonphysical_inputs():
    with pytest.raises(ValueError):
        LB.select_led_budget([(0.0, 1.0)], led_max_w=0.0)
