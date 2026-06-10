"""ARGUS T2.1/T2.2: arm-swing kinematics as ONE articulated state (ode-to-Schuler subsystem).

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
ARM_LIFT_EFFICIENCY = 0.60         # [CALIB] (rassor_mass_model.ARM_LIFT_EFFICIENCY)


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
    def cg_offset_m(self) -> tuple:
        """(dx, dz) CG shift from stowed, from the two arm-mass links (T2.1b -> stability)."""
        dx = dz = 0.0
        for (ox, _oz), deg in ((ARM_ORIGIN_FRONT, self.front_deg),
                               (ARM_ORIGIN_BACK, self.back_deg)):
            a = math.radians(deg)
            sgn = 1.0 if ox > 0 else -1.0
            dx += ARM_MASS_FRAC * (ox + sgn * ARM_LENGTH_M * math.cos(a) - ox)
            dz += ARM_MASS_FRAC * (ARM_LENGTH_M * math.sin(a))
        return dx, dz

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
