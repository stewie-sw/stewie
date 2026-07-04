"""AM-08: a VALIDATED braked posture hold with a MODELED holding torque and ZERO holding power.

VT-03 (`arm_joint.ArmJointState.engage_brake`) already gives the zero-VELOCITY hold: a braked joint
carries no velocity and ignores the drive command, so the posture is mechanically held. AM-08 EXTENDS
that with the two things its acceptance names beyond "the joint stops moving":

  * the MODELED holding TORQUE the passive brake must react -- the GRAVITY MOMENT of the arm about its
    pivot at the held angle, ``m * g * L * |cos(theta)|`` (NONZERO when the arm is extended/horizontal,
    ZERO when it is vertical), composed from the real arm geometry (`arm_state.ARM_LENGTH_M`,
    `arm_state.ARM_MASS_FRAC`, the `ipex_specs` 30 kg mass class) and the body's sourced surface gravity
    (`stewie_bodies`) -- no fabricated torque; and
  * a VALIDATED hold -- the held posture is a valid static-stability hold (`physics.stability`): the
    tip-over margin is non-negative at the rover's terrain attitude, accounting for the fore/aft CG
    shift the arm posture itself induces (`arm_state.ArmState.cg_offset_m`).

The brake is a PASSIVE mechanical hold, so its holding POWER is ZERO (it reacts a static torque; it
does not draw power to stand still) -- the "zero ... holding power" branch of the PRD row. The energy to
LEAVE the hold (release + slew the arm back up) is the ICE-RASSOR raise energy (`arm_state.raise_energy_j`),
a SEPARATE budget that is not spent by standing still: transition energy remains charged.

Where `arm_joint` models ONE joint's brake state and `arm_state` the arm-swing kinematics/CG, this module
composes those with the body gravity and the tip-over model into the AM-08 posture-hold assessment. Pure +
on-host; the exact flight-qualified brake torque rating stays the gated Q tier (as with the [ASSUMPTION]
arm geometry it is built on).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from stewie.physics import stability as _stab
from stewie.physics.rover import WHEEL_BASE_M, WHEEL_GAUGE_M
from stewie.specs import constants as _K
from stewie.specs.arm_joint import JOINT_FRONT, JOINT_REAR, ArmJointState
from stewie.specs.arm_state import ARM_LENGTH_M, ARM_MASS_FRAC, ArmState
from stewie.specs.ipex_specs import ROVER_MASS_CLASS_KG
from stewie_bodies import DEFAULT_BODY, get_body

#: The body's sourced surface gravity default (Moon, 1.62 m/s^2) from the body registry -- the one place
#: g lives; override per body via the `g=` argument (the whole drive chain is body-parameterized).
MOON_G_MS2: float = get_body(DEFAULT_BODY).g

#: A passive mechanical arm brake reacts a STATIC torque; it draws no power to hold a posture.
HOLDING_POWER_W: float = 0.0


def gravity_hold_torque_nm(angle_deg: float, *,
                           dry_mass_kg: float = ROVER_MASS_CLASS_KG,
                           drum_load_kg: float = 0.0,
                           g: float = MOON_G_MS2,
                           arm_mass_frac: float = ARM_MASS_FRAC,
                           arm_length_m: float = ARM_LENGTH_M) -> float:
    """The MODELED holding torque the brake must react at ``angle_deg`` -- the GRAVITY MOMENT of the arm
    about its pivot: ``m * g * L * |cos(theta)|``.

    ``m`` is the arm's own share of the dry mass (``arm_mass_frac * dry_mass_kg``) plus any regolith
    ``drum_load_kg`` riding at the drum, matching how `arm_state.cg_offset_m` lumps the link + drum load
    at the drum position ``L`` from the pivot. The lever is the drum's HORIZONTAL offset from the pivot
    (``arm_state`` places the drum at ``L*cos(theta)`` horizontally, ``L*sin(theta)`` vertically), so the
    gravity moment is MAXIMAL when the arm is extended/horizontal (``theta = 0``) and ZERO when it is
    vertical (``theta = +/-90``); ``|cos|`` makes it the torque MAGNITUDE, symmetric in the sign of the
    angle. Composed from the real arm geometry and body g -- no fabricated torque."""
    lumped_kg = arm_mass_frac * dry_mass_kg + drum_load_kg
    lever_m = arm_length_m * abs(math.cos(math.radians(angle_deg)))
    return lumped_kg * g * lever_m


def hold_energy_j(duration_s: float, *, holding_power_w: float = HOLDING_POWER_W) -> float:
    """Energy the brake draws to HOLD a posture for ``duration_s``: ``holding_power_w * duration``. For a
    passive mechanical brake (``HOLDING_POWER_W == 0``) this is 0 J for any duration -- the hold is free."""
    return holding_power_w * max(0.0, duration_s)


def transition_energy_remains_charged(budget_j: float, hold_duration_s: float, *,
                                      holding_power_w: float = HOLDING_POWER_W) -> float:
    """The transition-energy budget left after holding for ``hold_duration_s``: ``budget_j`` minus what the
    hold drew (`hold_energy_j`). With a passive brake (``holding_power_w == 0``) it equals ``budget_j``
    exactly -- the charge reserved to LEAVE the hold (the `arm_state.raise_energy_j` to swing the arm back
    up) is untouched by standing still. This is the PRD AM-08 "transition energy remains charged" clause."""
    return budget_j - hold_energy_j(hold_duration_s, holding_power_w=holding_power_w)


@dataclass(frozen=True)
class BrakedHold:
    """A VALIDATED braked posture hold (AM-08). Both arm joints are braked (VT-03 zero-velocity hold);
    each carries a MODELED gravity holding torque the passive brake reacts; the hold is VALIDATED against
    the static tip-over margin at the rover's terrain attitude (accounting for the CG shift the arm posture
    induces). ``holding_power_w`` is 0 (passive brake). ``valid`` is True only when both joints hold AND
    the stability margin is non-negative (``risk != 'tip'``)."""
    front: ArmJointState
    rear: ArmJointState
    holding_torque_front_nm: float
    holding_torque_rear_nm: float
    holding_power_w: float
    margin_deg: float
    risk: str
    valid: bool

    def held(self) -> bool:
        """Both joints are braked and carry zero velocity -- the posture is mechanically held (VT-03)."""
        return (self.front.brake_engaged and self.rear.brake_engaged
                and self.front.velocity_deg_s == 0.0 and self.rear.velocity_deg_s == 0.0)


def braked_hold(front_deg: float, rear_deg: float, *,
                pitch_deg: float = 0.0, roll_deg: float = 0.0,
                dry_mass_kg: float = ROVER_MASS_CLASS_KG,
                front_drum_kg: float = 0.0, rear_drum_kg: float = 0.0,
                g: float = MOON_G_MS2,
                gauge_m: float = WHEEL_GAUGE_M, wheelbase_m: float = WHEEL_BASE_M,
                cg_height_m: float = _K.CG_HEIGHT_M) -> BrakedHold:
    """Engage both arm brakes at (``front_deg``, ``rear_deg``) and VALIDATE the resulting posture hold.

    The hold is:
      * MECHANICALLY held -- each joint is `engage_brake`d (VT-03): zero velocity, ignores drive commands;
      * MODELED -- each joint carries its gravity holding torque (`gravity_hold_torque_nm`: nonzero when
        extended, zero when vertical), which the passive brake reacts at ``HOLDING_POWER_W == 0``; and
      * VALIDATED -- the arm posture's fore/aft CG shift (`arm_state.ArmState.cg_offset_m`) is fed to the
        static tip-over model (`physics.stability`) at the rover's terrain attitude; ``valid`` requires a
        non-negative margin (``risk != 'tip'``).
    """
    front = ArmJointState(joint=JOINT_FRONT, angle_deg=front_deg).engage_brake()
    rear = ArmJointState(joint=JOINT_REAR, angle_deg=rear_deg).engage_brake()
    tau_f = gravity_hold_torque_nm(front_deg, dry_mass_kg=dry_mass_kg, drum_load_kg=front_drum_kg, g=g)
    tau_r = gravity_hold_torque_nm(rear_deg, dry_mass_kg=dry_mass_kg, drum_load_kg=rear_drum_kg, g=g)
    cg_dx, _cg_dz = ArmState(front_deg=front_deg, back_deg=rear_deg).cg_offset_m(
        front_drum_kg=front_drum_kg, back_drum_kg=rear_drum_kg, dry_mass_kg=dry_mass_kg)
    stab = _stab.stability(pitch_deg, roll_deg, gauge_m=gauge_m, wheelbase_m=wheelbase_m,
                           cg_height_m=cg_height_m, cg_dx_m=cg_dx)
    held = (front.brake_engaged and rear.brake_engaged
            and front.velocity_deg_s == 0.0 and rear.velocity_deg_s == 0.0)
    valid = held and stab["risk"] != "tip"
    return BrakedHold(front=front, rear=rear, holding_torque_front_nm=tau_f,
                      holding_torque_rear_nm=tau_r, holding_power_w=HOLDING_POWER_W,
                      margin_deg=float(stab["margin_deg"]), risk=str(stab["risk"]), valid=valid)