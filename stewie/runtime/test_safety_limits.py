"""[REQ:EG-11] The safety-control layer: each sourced limit rejects an out-of-bound command; e-stop halts;
comms-loss past the deadline triggers the safe stance; the limit values stay sourced (not fabricated)."""
from stewie.runtime.safety_limits import (
    DEFAULT_LIMITS,
    SAFE_COMMAND,
    SafetyLimits,
    check_within_limits,
    comms_loss_behavior,
    estop,
)
from stewie.specs.posture_machine import BRAKED_HOLD


def test_eg11_each_limit_rejects_out_of_bound():  # [REQ:EG-11]
    L = DEFAULT_LIMITS
    assert check_within_limits({"linear_mps": L.max_speed_mps + 0.1})[1] == "speed"
    assert check_within_limits({"slope_deg": L.max_slope_deg + 1})[1] == "slope"
    assert check_within_limits({"obstacle_m": L.max_obstacle_m + 0.01})[1] == "obstacle"
    assert check_within_limits({"dig_depth_frac": L.max_dig_depth_frac + 0.1})[1] == "dig_depth"
    assert check_within_limits({"battery_frac": L.min_battery_frac - 0.01})[1] == "battery"


def test_eg11_within_limits_command_passes():  # [REQ:EG-11]
    ok, why = check_within_limits({"linear_mps": 0.2, "slope_deg": 10.0, "obstacle_m": 0.03,
                                   "dig_depth_frac": 0.4, "battery_frac": 0.5})
    assert ok is True and why == "within_limits"


def test_eg11_geofence_rejects_a_keepout_position():  # [REQ:EG-11]
    limits = SafetyLimits(geofence=lambda x, y: (x - 5.0) ** 2 + (y - 5.0) ** 2 < 4.0)   # keep-out r=2 @ (5,5)
    assert check_within_limits({"x_m": 5.0, "y_m": 5.0}, limits)[1] == "geofence"        # inside -> rejected
    assert check_within_limits({"x_m": 20.0, "y_m": 20.0}, limits)[0] is True            # outside -> ok


def test_eg11_estop_halts_and_always_passes():  # [REQ:EG-11]
    s = estop()
    assert s["estop"] is True and s["linear_mps"] == 0.0 and s["angular_rps"] == 0.0
    assert s["posture"] == BRAKED_HOLD
    assert check_within_limits({"estop": True, "linear_mps": 99.0}) == (True, "estop")


def test_eg11_comms_loss_past_deadline_triggers_safe():  # [REQ:EG-11]
    L = DEFAULT_LIMITS
    assert comms_loss_behavior(L.comms_loss_deadline_s + 0.1) == SAFE_COMMAND    # tripped -> SAFE
    assert comms_loss_behavior(L.comms_loss_deadline_s - 0.1) is None            # link alive -> no action


def test_eg11_limits_are_sourced_not_fabricated():  # [REQ:EG-11]
    from stewie.runtime.nav_loop import V_CAP_MPS
    from stewie.specs import ipex_specs as IX
    L = DEFAULT_LIMITS
    assert L.max_speed_mps == V_CAP_MPS
    assert (L.max_slope_deg, L.max_obstacle_m) == (IX.SLOPE_TEST_DEG, IX.OBSTACLE_HEIGHT_M)
    assert (L.max_dig_depth_frac, L.min_battery_frac) == (IX.MAX_CUT_DEPTH_FRAC, IX.BATTERY_RESERVE_FRAC)
