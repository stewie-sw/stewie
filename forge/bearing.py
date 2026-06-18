"""FORGE — static bearing-capacity model (Terzaghi/Vesic shallow foundation).

The CP-06 berm/pad acceptance (the "berm-firming" P2 closure) needs to answer: can a built pad or berm
carry a STRUCTURAL load -- a lander leg, a stacked habitat element, a parked heavy asset? For the light
~30 kg IPEx rover, slip-sinkage (not static bearing) is the dominant failure mode (see constants.py), so
this model is deliberately for structural loads on a built surface, not for rover trafficability.

Terzaghi's general shallow-foundation equation for the ultimate bearing capacity of a strip/square footing
of width ``B`` at embedment depth ``D`` on a soil of cohesion ``c``, friction angle ``phi`` and unit
weight ``gamma``:

    q_ult = c * Nc  +  (gamma * D) * Nq  +  0.5 * gamma * B * Ngamma

with the Prandtl-Reissner bearing-capacity factors (exact, closed form) and the Vesic (1973) Ngamma --
the standard textbook convention (Das, *Principles of Foundation Engineering*; Bowles, *Foundation
Analysis and Design*):

    Nq      = exp(pi * tan(phi)) * tan(45deg + phi/2)^2
    Nc      = (Nq - 1) / tan(phi)          -> 5.14 (Prandtl) as phi -> 0
    Ngamma  = 2 * (Nq + 1) * tan(phi)      (Vesic 1973)

All inputs SI: cohesion + unit weight in Pa and N/m^3, phi in radians, lengths in m. Outputs in Pa.

Sources: Terzaghi (1943) *Theoretical Soil Mechanics*; Vesic (1973) "Analysis of Ultimate Loads of
Shallow Foundations", JSMFD 99(SM1). Lunar regolith inputs (c, phi, density) are the body-sourced values
in stewie/specs (Apollo + ChaSTE MEASURED).
"""
from __future__ import annotations

import math

#: Prandtl's bearing-capacity factor Nc for a purely cohesive (phi = 0) soil.
NC_PHI0 = 5.14


def bearing_capacity_factors(phi_rad: float) -> tuple[float, float, float]:
    """Return ``(Nc, Nq, Ngamma)`` for friction angle ``phi_rad`` (Prandtl-Reissner + Vesic Ngamma).

    At phi -> 0 the cohesive limit applies exactly: Nc = 5.14, Nq = 1, Ngamma = 0 (no friction/self-weight
    contribution), which is why a frictionless soil's capacity is carried entirely by the cohesion term."""
    if phi_rad <= 1e-9:
        return NC_PHI0, 1.0, 0.0
    t = math.tan(phi_rad)
    nq = math.exp(math.pi * t) * math.tan(math.pi / 4.0 + phi_rad / 2.0) ** 2
    nc = (nq - 1.0) / t
    ng = 2.0 * (nq + 1.0) * t
    return nc, nq, ng


def ultimate_bearing_capacity_pa(cohesion_pa: float, phi_rad: float, unit_weight_n_m3: float,
                                 width_m: float, *, surcharge_depth_m: float = 0.0) -> float:
    """Terzaghi ultimate bearing capacity ``q_ult`` [Pa]; see module docstring for the equation."""
    nc, nq, ng = bearing_capacity_factors(phi_rad)
    q_surcharge = unit_weight_n_m3 * max(0.0, surcharge_depth_m)
    return cohesion_pa * nc + q_surcharge * nq + 0.5 * unit_weight_n_m3 * max(0.0, width_m) * ng


def allowable_bearing_pa(cohesion_pa: float, phi_rad: float, unit_weight_n_m3: float, width_m: float,
                         *, factor_of_safety: float = 3.0, surcharge_depth_m: float = 0.0) -> float:
    """Allowable bearing pressure = ``q_ult / factor_of_safety`` [Pa].

    FS = 3.0 is the standard geotechnical factor of safety for shallow-foundation bearing (Das/Bowles);
    pass a different value for a more/less conservative gate."""
    q_ult = ultimate_bearing_capacity_pa(cohesion_pa, phi_rad, unit_weight_n_m3, width_m,
                                         surcharge_depth_m=surcharge_depth_m)
    return q_ult / max(1e-9, factor_of_safety)
