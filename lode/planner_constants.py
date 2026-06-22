"""ARCH-03: the shared, immutable planner constants in a DEPENDENCY-NEUTRAL module.

These energy/rate/reserve constants are needed by BOTH the solver (`lode.mission_planner`) and the
read-only views (`lode.planner_views`). Hosting them here -- importing only the IPEx spec source --
lets `planner_views` get them WITHOUT importing `mission_planner`, which (together with the lazy
view re-export in mission_planner) breaks the former bidirectional import cycle. Values are the exact
IPEx-grounded expressions the solver used before, so the byte-identical G1/G2 eval is unchanged.
"""
# PROVENANCE: STEWIE LODE subsystem (A. Storey)
from __future__ import annotations

from stewie.specs import ipex_specs as S

DRIVE_SPEED_MS = S.DRIVE_SPEED_MS                 # 0.30 m/s
DIG_RATE_KG_S = S.DIG_RATE_KG_PER_HR / 3600.0     # 42 kg/hr
DIG_J_PER_KG = S.dig_energy_per_kg()              # ~4151 J/kg (derived)
DRIVE_J_PER_M = S.drive_energy_per_m()            # ~135 J/m (derived)
BATTERY_J = S.battery_energy_j()                  # ~4.79 MJ (12S/30Ah)
RESERVE_FRAC = S.BATTERY_RESERVE_FRAC             # 0.10
CHARGE_W = S.RECHARGE_POWER_W                     # 700 W [CALIB]

# ARCH-2 (#123): constants the model leaf (lode.planner_model) shares with the energy/scoring clusters
# that stay in mission_planner -- hosted here in the dependency-neutral leaf so BOTH import them with no
# cycle. Values are the exact expressions mission_planner defined before, so the plan is byte-identical.
#: P-06 positional-uncertainty margin [m] added to the vehicle swept radius when inflating routing hazards.
LOCALIZATION_MARGIN_M = 0.15
#: CP-08 objective-constraint key -> the core metric it caps. Used by mission_from_dict (validation, in
#: planner_model) and _constraint_penalty (sequencing, in mission_planner).
_CONSTRAINT_CAPS = {"max_time_s": "time_s", "max_energy_J": "energy_J",
                    "max_charges": "charges", "max_distance_m": "distance_m"}
