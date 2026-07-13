"""Navigation T2.1/T2.2: arm-swing kinematics as ONE articulated state (ode-to-Schuler subsystem).

Doc truth folded in: arm pivots at base_link x = +/-0.20 m (the render rig's ARM_*_ORIGIN -- one
geometry for physics AND pixels), arm-actuator excavation load 18.5 N*m on the Moon (TRL5 Table 7),
arm raise as the ICE-RASSOR mass-inference observable (m*g*dh/eta), and the KSC-TOPS-7 design
truth that COUNTER-ROTATING drums cancel the horizontal dig reaction. Travel range and slew rate
are [ASSUMPTION] (RASSOR-lineage arms sweep a wide arc; the IPEx values are figure-only) -- tagged,
rate-limited, and centralized here so one number change re-trues every consumer (render args,
joints channel, CG/stability, energy).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

ARM_TRAVEL_DEG = (-110.0, 110.0)   # [ASSUMPTION] RASSOR-lineage sweep; IPEx value figure-only
ARM_RATE_DEG_S = 20.0              # [ASSUMPTION] slew limit; bounds posture-change cadence
ARM_LENGTH_M = 0.28                # pivot -> drum axis [ASSUMPTION: render-rig consistent]
ARM_ORIGIN_FRONT = (0.20, 0.0)     # base_link x,z [sidecar ARM_FRONT_ORIGIN]
ARM_ORIGIN_BACK = (-0.20, 0.0)     # base_link x,z [sidecar ARM_BACK_ORIGIN]
ARM_MASS_FRAC = 0.15               # arm+drum share of dry mass per arm [ASSUMPTION]
from stewie.physics.rassor_mass_model import ARM_LIFT_EFFICIENCY  # 0.5 [CALIB] -- ONE source
                                                                   # (was a drifted local 0.60; F3)

#: [REQ:PX-10] The front-arm pitch (rad) that puts the drum in the DIG posture -- the "COBRA" stance the
#: sim already commands (front arm DOWN to cut, back arm UP to transport). This is the ONE authority for
#: that number; ``stewie/godot/viz2_root.gd`` mirrors it as ``ARM_DIG_DOWN`` for the render rig. Negative
#: lowers the drum. The operator's manual ``arm_front_d`` deltas are an OFFSET on top of it.
ARM_DIG_DOWN_RAD = -0.55           # [ASSUMPTION: render-rig consistent] drum-down dig posture

#: [REQ:PX-10] Travel limits on the operator's manual arm OFFSET (rad). The render rig clamps the manual
#: arm_front_d/arm_back_d deltas to exactly this band, and the runtime clamps to the same band at ingest --
#: so a command off the public console can never pose the arm somewhere the rig cannot physically go (nor
#: license a deeper cut than the rig can reach). ONE authority; ``viz2_root.gd`` mirrors these numbers.
ARM_OFFSET_MIN_RAD = -0.4          # further DOWN than the dig posture (engagement already saturates at 1)
ARM_OFFSET_MAX_RAD = 1.0           # raised well past stowed-horizontal (transport)


def dig_engagement(arm_front_offset_rad: float) -> float:
    """[REQ:PX-10] How much of the commanded bite the front drum can actually take, given where the
    operator has put the arm. 0.0 = the drum is not in the ground (transport / stowed) -> NO cut;
    1.0 = the drum is at (or below) the dig posture -> the full commanded bite (which the PX-09 caps then
    bound).

    ``arm_front_offset_rad`` is the operator's manual offset, exactly as the render rig applies it:
    effective pitch = ARM_DIG_DOWN_RAD + offset. So offset 0 IS the dig posture (engagement 1.0), which is
    why arming this gate does not change the default dig; raising the arm for transport (positive offset)
    drives engagement to 0 and the dig stops cutting -- which is the whole point.

    HONEST MODELLING NOTE. The physically right function is geometric: the drum's cutting edge penetrates
    the ground by (arm-pivot height) - L*sin(pitch) - drum_radius, and the bite is that penetration. We do
    NOT have a sourced arm-pivot height above ground (assuming the pivot sits at the wheel axle puts the
    large drum's edge BELOW the wheels at stow, which is plainly wrong), so inventing that geometry would
    fabricate every absolute number that fell out of it. Instead the engagement is a LINEAR ramp between
    the two postures the sim itself defines -- stowed (no contact) and ARM_DIG_DOWN (full commanded bite).
    [ASSUMPTION] the ramp SHAPE; the GATE it implements (arm up => no cut) is exact and is the requirement.
    A geometric penetration model is deferred to a sourced pivot height.
    """
    if not math.isfinite(arm_front_offset_rad):
        return 0.0                                  # a non-finite command must never license a cut
    pitch = ARM_DIG_DOWN_RAD + float(arm_front_offset_rad)
    if pitch >= 0.0:                                # at or above stowed-horizontal: the drum is off the ground
        return 0.0
    return max(0.0, min(1.0, pitch / ARM_DIG_DOWN_RAD))


@dataclass
class ArmState:
    """Front/back arm pitch [deg, 0 = stowed horizontal], rate-limited toward commands."""
    front_deg: float = 0.0
    back_deg: float = 0.0
    front_target_deg: float = 0.0
    back_target_deg: float = 0.0

    def command(self, front_deg: float | None = None, back_deg: float | None = None) -> None:
        lo, hi = ARM_TRAVEL_DEG
        if front_deg is not None:
            self.front_target_deg = min(hi, max(lo, float(front_deg)))
        if back_deg is not None:
            self.back_target_deg = min(hi, max(lo, float(back_deg)))

    def step(self, dt: float) -> None:
        lim = ARM_RATE_DEG_S * float(dt)
        for attr, tgt in (("front_deg", self.front_target_deg),
                          ("back_deg", self.back_target_deg)):
            cur = getattr(self, attr)
            d = tgt - cur
            setattr(self, attr, cur + max(-lim, min(lim, d)))

    # ---- consumers ------------------------------------------------------------------------
    def cg_offset_m(self, front_drum_kg: float = 0.0, back_drum_kg: float = 0.0,
                    dry_mass_kg: float = 30.0) -> tuple:
        """(dx, dz) CG shift from stowed. TWO mass terms per arm: the link's own share
        (ARM_MASS_FRAC of dry mass) AND the drum LOAD riding at the drum position -- the weighted
        drums ARE the balance ballast maneuvers posture with (Aaron 2026-06-10; RASSOR's signature
        capability). Mass-weighted about the total (dry + loads)."""
        total = max(1e-9, dry_mass_kg + front_drum_kg + back_drum_kg)
        mx = mz = 0.0
        for (ox, _oz), deg, load in ((ARM_ORIGIN_FRONT, self.front_deg, front_drum_kg),
                                     (ARM_ORIGIN_BACK, self.back_deg, back_drum_kg)):
            a = math.radians(deg)
            sgn = 1.0 if ox > 0 else -1.0
            link_m = ARM_MASS_FRAC * dry_mass_kg
            px = ox + sgn * ARM_LENGTH_M * math.cos(a)
            pz = ARM_LENGTH_M * math.sin(a)
            stow_x, stow_z = ox + sgn * ARM_LENGTH_M, 0.0
            mx += link_m * (px - stow_x) + load * px      # load enters at the drum, not at stow
            mz += link_m * (pz - stow_z) + load * pz
        return mx / total, mz / total

    def drum_cam_offset_m(self, which: str = "front") -> tuple:
        """(x, z) of the drum-arm camera in base_link (rigid link off the pivot) -- the
        navigation-by-posturing observable: command the arm, the camera viewpoint moves."""
        ox, _oz = ARM_ORIGIN_FRONT if which == "front" else ARM_ORIGIN_BACK
        sgn = 1.0 if which == "front" else -1.0
        a = math.radians(self.front_deg if which == "front" else self.back_deg)
        return (ox + sgn * ARM_LENGTH_M * math.cos(a), ARM_LENGTH_M * math.sin(a))

    def raise_energy_j(self, drum_mass_kg: float, g: float, *, from_deg: float,
                       to_deg: float) -> float:
        """The ICE-RASSOR observable: lifting the loaded drum costs m*g*dh/eta; lowering ~0."""
        dh = ARM_LENGTH_M * (math.sin(math.radians(to_deg)) - math.sin(math.radians(from_deg)))
        return max(0.0, drum_mass_kg * float(g) * dh / ARM_LIFT_EFFICIENCY)


def net_dig_reaction_n(torque_nm: float, drum_radius_m: float,
                       drums: tuple = ("front", "back")) -> float:
    """KSC-TOPS-7 (T2.2): counter-rotating drums dig in opposing directions -- the horizontal
    reactions are equal and OPPOSITE, so the pair nets ~0 and a single drum nets F = tau/r."""
    f = float(torque_nm) / float(drum_radius_m)
    sign = {"front": +1.0, "back": -1.0}
    return sum(sign[d] * f for d in drums)
