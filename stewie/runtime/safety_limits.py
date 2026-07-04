"""[REQ:EG-11] The safety-control layer (PRD §29.8 Safety Control).

Gathers the named safety limits into ONE typed envelope + a fail-closed check, an e-stop primitive, and the
comms-loss behavior. Every limit VALUE is pulled from its SOURCED home -- none is fabricated here:
  * max_speed_mps  = nav_loop.V_CAP_MPS (the IPEx-class hard velocity cap, 0.5 m/s)
  * max_slope_deg  = ipex_specs.SLOPE_TEST_DEG (the 20 deg wheel slope-driving test limit) [WHEELTEST]
  * max_obstacle_m = ipex_specs.OBSTACLE_HEIGHT_M (7.5 cm rock-traverse) [SCHULER24]
  * max_dig_depth_frac = ipex_specs.MAX_CUT_DEPTH_FRAC (<=50% scoop opening, anti-bridging) [BDSCALE]
  * min_battery_frac = ipex_specs.BATTERY_RESERVE_FRAC (>=10% pack reserve)
  * comms_loss_deadline_s = the NV-12 link-stall / SF-01 dead-man deadline (2.0 s)
  * the e-stop / comms-loss safe stance = posture_machine.BRAKED_HOLD (zero motion)

INVARIANT (§29.8): no live execution bypasses this layer -- the command pipeline (EG-06 lower_command) calls
check_within_limits before any emission. Wiring check_within_limits into that pipeline is the noted [REQ:EG-11]
integration follow-up; the layer + checks are delivered here.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from stewie.runtime.nav_loop import V_CAP_MPS
from stewie.specs import ipex_specs as IX
from stewie.specs.posture_machine import BRAKED_HOLD

_COMMS_LOSS_DEADLINE_S = 2.0    # NV-12 command/telemetry link-stall + SF-01 dead-man default [s]


@dataclass(frozen=True)
class SafetyLimits:
    """The §29.8 safety envelope; every default is a real sourced value (see module docstring)."""
    max_speed_mps: float = V_CAP_MPS
    max_slope_deg: float = IX.SLOPE_TEST_DEG
    max_obstacle_m: float = IX.OBSTACLE_HEIGHT_M
    max_dig_depth_frac: float = IX.MAX_CUT_DEPTH_FRAC
    min_battery_frac: float = IX.BATTERY_RESERVE_FRAC
    comms_loss_deadline_s: float = _COMMS_LOSS_DEADLINE_S
    #: optional keep-out predicate: geofence(x_m, y_m) -> True if the position is inside a NO-GO region.
    geofence: Callable[[float, float], bool] | None = None


DEFAULT_LIMITS = SafetyLimits()

#: the e-stop / comms-loss SAFE command: the universal BRAKED_HOLD safe stance, zero motion.
SAFE_COMMAND: dict = {"posture": BRAKED_HOLD, "linear_mps": 0.0, "angular_rps": 0.0, "estop": True}


def estop() -> dict:
    """The e-stop primitive: HALT -- return the SAFE command (BRAKED_HOLD, zero motion). No live command
    proceeds past an e-stop."""
    return dict(SAFE_COMMAND)


def check_within_limits(command: dict, limits: SafetyLimits = DEFAULT_LIMITS) -> tuple[bool, str]:
    """Fail-closed: return (ok, violated_limit). Rejects a command that exceeds ANY named limit
    (speed/slope/obstacle/dig_depth/battery/geofence). An explicit e-stop always passes (it IS the safe
    command). A field absent from the command is not exercised (in-bounds for that field)."""
    if command.get("estop"):
        return True, "estop"
    if abs(float(command.get("linear_mps", 0.0))) > limits.max_speed_mps:
        return False, "speed"
    if float(command.get("slope_deg", 0.0)) > limits.max_slope_deg:
        return False, "slope"
    if float(command.get("obstacle_m", 0.0)) > limits.max_obstacle_m:
        return False, "obstacle"
    if float(command.get("dig_depth_frac", 0.0)) > limits.max_dig_depth_frac:
        return False, "dig_depth"
    if "battery_frac" in command and float(command["battery_frac"]) < limits.min_battery_frac:
        return False, "battery"
    if limits.geofence is not None and "x_m" in command and "y_m" in command \
            and limits.geofence(float(command["x_m"]), float(command["y_m"])):
        return False, "geofence"
    return True, "within_limits"


def comms_loss_behavior(elapsed_s: float, limits: SafetyLimits = DEFAULT_LIMITS) -> dict | None:
    """§29.8 comms-loss behavior: once the command/telemetry link has been silent PAST the deadline, halt to
    the SAFE command (the dead-man switch). Returns the SAFE command when tripped, else None (link alive)."""
    return estop() if elapsed_s > limits.comms_loss_deadline_s else None
