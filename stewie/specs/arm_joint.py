"""VT-03: front/rear arm JOINT STATE as ONE typed, validated record (the vehicle-twin arm surface).

Where `arm_state.ArmState` is the arm-swing KINEMATICS stepper (rate-limited pitch, CG, camera pose,
raise energy), `ArmJointState` is the typed per-joint STATE the vehicle twin exposes and every consumer
reasons over: joint id (front/rear), angle, its min/max travel limit, angular velocity, and brake
state, with the two invariants VT-03 asks for enforced at construction --

  * angle is WITHIN its [min_deg, max_deg] limit (an out-of-range pose is rejected, not clamped
    silently), and
  * a BRAKED joint HOLDS: it carries zero velocity and `step` ignores commands (AM-08 -- the brake is
    a passive posture hold; a braked joint does not move).

The travel and slew LIMITS are NOT re-fabricated here: they default from `arm_state.ARM_TRAVEL_DEG`
(the [ASSUMPTION] RASSOR-lineage sweep -- the IPEx figure is figure-only) and `arm_state.ARM_RATE_DEG_S`,
the one place those numbers live, so a single edit re-trues both the kinematics and this record. The
EXACT flight-qualified IPEx/LAC arm pivot geometry, limits, and brake behavior remain the gated Q tier
(PRD VT-03: "Exact geometry must come from authoritative LAC/IPEx data") -- this models the STRUCTURE
(joint id + limits + velocity + brake + validation) on-host, exactly as `arm_state`/`posture_machine`
already do for the assumption-tagged posture numbers.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from stewie.specs.arm_state import ARM_RATE_DEG_S, ARM_TRAVEL_DEG, ArmState

#: the two articulated arms of the counter-rotating-drum excavator. "rear" is `arm_state`'s "back".
JOINT_FRONT = "front"
JOINT_REAR = "rear"
JOINTS = (JOINT_FRONT, JOINT_REAR)

_EPS = 1e-9


@dataclass(frozen=True)
class ArmJointState:
    """One arm joint's typed state. Frozen (a state snapshot is immutable); `step`/`engage_brake`/
    `release_brake` return NEW records. Invariants enforced in `__post_init__`: known joint id, a
    valid limit interval, angle within limits, velocity within the slew capability, and -- the AM-08
    hold -- a braked joint carries zero velocity."""
    joint: str
    angle_deg: float
    min_deg: float = ARM_TRAVEL_DEG[0]
    max_deg: float = ARM_TRAVEL_DEG[1]
    velocity_deg_s: float = 0.0
    max_rate_deg_s: float = ARM_RATE_DEG_S
    brake_engaged: bool = False

    def __post_init__(self) -> None:
        if self.joint not in JOINTS:
            raise ValueError(f"unknown arm joint {self.joint!r}; known: {JOINTS}")
        if not self.min_deg < self.max_deg:
            raise ValueError(f"invalid limit interval for {self.joint}: min_deg {self.min_deg} "
                             f">= max_deg {self.max_deg}")
        if self.max_rate_deg_s <= 0.0:
            raise ValueError(f"max_rate_deg_s must be > 0 (got {self.max_rate_deg_s})")
        if not self.min_deg - _EPS <= self.angle_deg <= self.max_deg + _EPS:
            raise ValueError(f"{self.joint} angle {self.angle_deg} deg outside limits "
                             f"[{self.min_deg}, {self.max_deg}]")
        if abs(self.velocity_deg_s) > self.max_rate_deg_s + _EPS:
            raise ValueError(f"{self.joint} velocity {self.velocity_deg_s} deg/s exceeds slew rate "
                             f"{self.max_rate_deg_s} deg/s")
        if self.brake_engaged and abs(self.velocity_deg_s) > _EPS:
            raise ValueError(f"a braked joint holds: {self.joint} cannot carry velocity "
                             f"{self.velocity_deg_s} deg/s while braked (AM-08)")

    # ---- queries --------------------------------------------------------------------------------
    def within_limits(self, deg: float | None = None) -> bool:
        """True if `deg` (or the current angle) is within [min_deg, max_deg]."""
        v = self.angle_deg if deg is None else deg
        return self.min_deg - _EPS <= v <= self.max_deg + _EPS

    def clamp(self, deg: float) -> float:
        """`deg` clamped into the joint's travel limits."""
        return min(self.max_deg, max(self.min_deg, deg))

    # ---- transitions (return a new immutable record) --------------------------------------------
    def step(self, target_deg: float, dt: float) -> "ArmJointState":
        """Advance one tick toward `target_deg`. A BRAKED joint HOLDS -- the command is ignored and
        the joint does not move (AM-08). Otherwise the joint slews toward the (limit-clamped) target,
        rate-limited by `max_rate_deg_s`, and the achieved rate becomes `velocity_deg_s` (0 at the
        target). Matches `ArmState.step`'s rate-limit math on a single joint."""
        if self.brake_engaged:
            return self                                  # holds; braked => velocity already 0
        if dt <= 0.0:
            return replace(self, velocity_deg_s=0.0)
        tgt = self.clamp(target_deg)
        lim = self.max_rate_deg_s * dt
        move = max(-lim, min(lim, tgt - self.angle_deg))
        return replace(self, angle_deg=self.angle_deg + move, velocity_deg_s=move / dt)

    def engage_brake(self) -> "ArmJointState":
        """Engage the brake: zero the velocity and hold the current angle (AM-08 passive hold)."""
        return replace(self, brake_engaged=True, velocity_deg_s=0.0)

    def release_brake(self) -> "ArmJointState":
        """Release the brake (velocity stays 0 until the next `step`)."""
        return replace(self, brake_engaged=False)


def _rate_limited_velocity(cur: float, tgt: float, dt: float, rate: float) -> float:
    """The per-tick commanded velocity `ArmState.step` would realize: rate-limited (tgt-cur)/dt."""
    if dt <= 0.0:
        return 0.0
    lim = rate * dt
    return max(-lim, min(lim, tgt - cur)) / dt


def pair_from_arm_state(arm: ArmState, *, dt: float = 1.0,
                        min_deg: float = ARM_TRAVEL_DEG[0], max_deg: float = ARM_TRAVEL_DEG[1],
                        max_rate_deg_s: float = ARM_RATE_DEG_S,
                        front_brake: bool = False, rear_brake: bool = False,
                        ) -> "tuple[ArmJointState, ArmJointState]":
    """Project the vehicle twin's arm-swing kinematics (`arm_state.ArmState`, front/back pitch +
    targets) onto the two typed joint records (front, rear). Velocity is the SAME rate-limited
    (target-current)/dt `ArmState.step` realizes; a braked joint reports zero velocity. Reuses the
    module travel/slew limits (arm_state's one source) so nothing is re-fabricated here."""
    vf = 0.0 if front_brake else _rate_limited_velocity(arm.front_deg, arm.front_target_deg, dt, max_rate_deg_s)
    vr = 0.0 if rear_brake else _rate_limited_velocity(arm.back_deg, arm.back_target_deg, dt, max_rate_deg_s)
    front = ArmJointState(joint=JOINT_FRONT, angle_deg=arm.front_deg, min_deg=min_deg, max_deg=max_deg,
                          velocity_deg_s=vf, max_rate_deg_s=max_rate_deg_s, brake_engaged=front_brake)
    rear = ArmJointState(joint=JOINT_REAR, angle_deg=arm.back_deg, min_deg=min_deg, max_deg=max_deg,
                         velocity_deg_s=vr, max_rate_deg_s=max_rate_deg_s, brake_engaged=rear_brake)
    return front, rear
