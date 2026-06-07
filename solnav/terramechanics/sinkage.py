"""Load-bearing Bekker pressure-sinkage for wheels and drums, and the chassis-height
and dig-depth corrections it implies.

Bekker:        p = (k_c / b + k_phi * s) * z^n
  p   contact pressure [Pa] = normal load / contact area
  b   smaller contact-patch dimension [m] (Bekker plate width)
  s   density-stiffening factor (>=1; firmer soil -> less sinkage)
  n   sinkage exponent
inverted:      z = ( p / (k_c/b + k_phi*s) )^(1/n)

This matches the dustgym terramechanics formulation (terrain_authority/terramechanics.py).
Moon moduli are the MEASURED values from the NASA LTV terramechanics white paper
(NTRS 20220010732): k_c=1400 N/m^2, k_phi=820000 N/m^3, n=1.0. Lunar gravity 1.62 m/s^2.

SCOPE (honest, matches dustgym): this is the LOAD-BEARING static sinkage only. The
path-dependent SLIP-SINKAGE / runaway-entrapment mode (a much larger, dynamic sink
under spinning wheels) is NOT modeled here; it needs a slip-coupled solver
(PyChrono host). It is the dominant risk on steep/loose slopes and is listed as a
required future model, deliberately not stubbed.

Why navigation cares: even mm-scale sinkage shifts the chassis (and therefore the
camera extrinsics the SLAM graph depends on), and the drums settle BELOW their
commanded cut depth under load, which the dig-depth control must compensate.
"""
from __future__ import annotations

from dataclasses import dataclass

LUNAR_G = 1.62  # m/s^2


@dataclass(frozen=True)
class BekkerParams:
    k_c: float       # cohesive modulus [N/m^2]
    k_phi: float     # frictional modulus [N/m^3]
    n: float         # sinkage exponent
    provenance: str = ""


# Measured lunar moduli (NASA LTV white paper, NTRS 20220010732); same as dustgym BODIES["moon"].
MOON = BekkerParams(1400.0, 820000.0, 1.0,
                    "NASA LTV terramechanics white paper NTRS 20220010732 (measured)")
# Mars GRC-3 simulant (Oravec et al. 2020 NASA GRC), for cross-body checks.
MARS_GRC3 = BekkerParams(23200.0, 606700.0, 1.0, "Oravec et al. 2020 NASA GRC GRC-3")


def static_load_per_contact(total_mass_kg: float, n_contacts: int = 4, g: float = LUNAR_G) -> float:
    """Equal-split static normal load per contact [N] = m*g/n. (Fore/aft CG transfer
    is a refinement.)"""
    return total_mass_kg * g / n_contacts


def contact_pressure(load_n: float, b_m: float, contact_len_m: float) -> float:
    """p = load / (b * l) [Pa]."""
    return load_n / (b_m * contact_len_m)


def bekker_sinkage(pressure_pa: float, *, b_m: float, params: BekkerParams = MOON,
                   density_factor: float = 1.0) -> float:
    """z = (p / (k_c/b + k_phi*s))^(1/n) [m]."""
    denom = params.k_c / b_m + params.k_phi * density_factor
    return (pressure_pa / denom) ** (1.0 / params.n)


def wheel_sinkage(load_n: float, wheel_width_m: float = 0.18, contact_len_m: float = 0.10,
                  params: BekkerParams = MOON, density_factor: float = 1.0) -> float:
    """Static sinkage of a wheel (Bekker width b = wheel width)."""
    p = contact_pressure(load_n, wheel_width_m, contact_len_m)
    return bekker_sinkage(p, b_m=wheel_width_m, params=params, density_factor=density_factor)


def drum_sinkage(load_n: float, drum_len_m: float = 0.20, contact_len_m: float = 0.04,
                 params: BekkerParams = MOON, density_factor: float = 1.0) -> float:
    """Static sinkage when bearing on a bucket drum. The drum's narrow contact chord
    (contact_len) gives higher pressure than a wheel at equal load -> more sinkage,
    which is why a raised (meerkat/iron-cross) stance settles more."""
    p = contact_pressure(load_n, drum_len_m, contact_len_m)
    return bekker_sinkage(p, b_m=min(drum_len_m, contact_len_m), params=params,
                          density_factor=density_factor)


def effective_height_drop(nominal_height_m: float, sinkage_m: float) -> float:
    """Chassis/camera height after the contacts sink: nominal - sinkage [m]."""
    return nominal_height_m - sinkage_m


def effective_dig_depth(commanded_cut_m: float, sinkage_m: float) -> float:
    """Drums settle below the commanded cut under load: effective depth = cut + sinkage."""
    return commanded_cut_m + sinkage_m
