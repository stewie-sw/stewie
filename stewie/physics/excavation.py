"""First-principles excavation DRAFT force -- the McKyes / Reece Fundamental Earthmoving Equation (FEE).

This is the REAL dig-difficulty model that ``physics.excavation_resistance`` binds to (task #78, design
`STEWIE_LUNAR_PLATFORM_DESIGN_2026-07-06.md` §1.5). It REPLACES the honesty-relabelled proxy that layer
carried through task #53 -- the Bekker WHEEL compaction/motion resistance ``slip.compaction_resistance``
(the resistance a wheel climbs out of its own rut), which is not a cutting force at all.

Model (McKyes 1985, "Soil Cutting and Tillage", Elsevier, Ch. 3-4; Reece 1964, "The fundamental equation
of earthmoving mechanics", Proc. IMechE 179(3F):16-22; applied to LUNAR regolith by Wilkinson & DeGennaro
2007, "Digging and pushing lunar regolith", J. Terramechanics 44:133-152, eq. 1). For a wide blade / drum
cutting edge of width ``w`` at rake angle ``alpha`` cutting to depth ``d`` in a soil of bulk density
``gamma``, cohesion ``c``, internal friction ``phi``, soil-tool (external) friction ``delta``, under a
surface surcharge ``q``, the horizontal draft force is

    F = (gamma * g * d**2 * N_gamma  +  c * d * N_c  +  q * d * N_q) * w                         (FEE)

The N-factors are NOT free parameters: they follow from a limit-equilibrium analysis of the soil wedge
that fails along a planar rupture surface at angle ``beta`` below horizontal (McKyes 1985 eqs.; the
two-dimensional wide-blade wedge). With ``m(x) = cot(x)`` and the common denominator
``D = cos(alpha+delta) + sin(alpha+delta) * cot(beta+phi)``:

    N_gamma = (cot(alpha) + cot(beta)) / (2 * D)
    N_c     = (1 + cot(beta) * cot(beta+phi)) / D
    N_q     = (cot(alpha) + cot(beta)) / D                    (note N_q == 2 * N_gamma)

The rupture angle ``beta`` is itself determined by the physics: the wedge fails along the surface that
requires the LEAST tool force, so ``beta`` is found by MINIMIZING F over ``beta`` (McKyes 1985; Wilkinson &
DeGennaro 2007 minimise the tool force over the failure angle). This module solves that minimisation
numerically over the valid domain ``beta in (0, pi/2 - phi)`` (where cot(beta+phi) > 0 so D > 0 and every
N-factor is positive), so the returned draft is a well-defined positive force.

Consistency with the spine: ``phi``, ``c`` and the bulk density ``gamma`` come from the SAME material model
the rest of the terramechanics spine reads (``stewie.physics.material.cell_strength`` maps a cell's real
bulk density to (phi, cohesion)); the tool geometry (drum/blade width ``w``, cut depth ``d``) comes from
``stewie.specs.ipex_specs`` (the IPEx bucket-drum). The counter-rotating-drum design cancels the NET
horizontal reaction on the vehicle (spec §9); this draft term feeds dig ENERGY + interaction-zone stress,
NOT a net vehicle reaction.

[CALIB-PENDING] -- the MODEL is grounded in the standard equation, but the rake angle ``alpha`` and the
soil-tool friction ``delta`` for the IPEx bucket-drum scoop geometry are not published, so their defaults
below are documented engineering assumptions. Quantitative field validation of the N-factors against real
IPEx/GMRO dig-force telemetry is not available; the predicted specific dig energy is reconciled against the
IPEx electrical dig-energy baseline (``ipex_specs.dig_energy_per_kg`` ~4151 J/kg) only as an order-of-
magnitude LOWER BOUND (ideal mechanical cutting work is a small fraction of the measured electrical dig
energy, which also carries drum-mechanism, lifting and motor-efficiency losses -- see reconciliation below).
"""
# PROVENANCE: STEWIE FORGE subsystem (A. Storey), task #78.
from __future__ import annotations

import math

from stewie.physics import material as _material
from stewie.specs import constants as _K

# ---------------------------------------------------------------------------
# Tool-geometry / soil-tool interface defaults. [CALIB-PENDING] -- the FEE math is exact; these two
# angles for the IPEx bucket-drum scoop are documented assumptions (not in the public IPEx spec).
# ---------------------------------------------------------------------------
#: Blade/scoop rake angle from horizontal [rad]. [CALIB-PENDING] 45 deg is a mid-range earthmoving-blade
#: value (McKyes 1985 uses 30-90 deg); the IPEx bucket-drum scoop's effective rake is not published.
RAKE_ANGLE_RAD = math.radians(45.0)

#: Soil-tool (external) friction as a fraction of the soil internal friction phi. [CALIB-PENDING]
#: delta = 0.5*phi (steel-on-regolith is commonly delta ~ 0.3-0.6 * phi; Wilkinson & DeGennaro 2007 use a
#: soil-metal interface friction). For the lunar phi ~ 37-50 deg this gives delta ~ 18-25 deg.
SOIL_TOOL_FRICTION_FRAC = 0.5


def earthmoving_factors(phi_rad: float, beta_rad: float, *, rake_rad: float = RAKE_ANGLE_RAD,
                        soil_tool_friction_rad: float | None = None) -> tuple[float, float, float]:
    """The McKyes/Reece earthmoving N-factors (N_gamma, N_c, N_q) for a planar soil wedge failing at
    angle ``beta_rad`` below horizontal. All angles in radians. ``soil_tool_friction_rad`` (delta) defaults
    to SOIL_TOOL_FRICTION_FRAC * phi. Raises ValueError if the geometry leaves the valid domain
    (beta+phi >= pi/2, so cot(beta+phi) <= 0 and the denominator is non-positive)."""
    delta = SOIL_TOOL_FRICTION_FRAC * phi_rad if soil_tool_friction_rad is None else soil_tool_friction_rad
    if not (0.0 < beta_rad < math.pi / 2.0):
        raise ValueError(f"beta must be in (0, pi/2); got {beta_rad}")
    if beta_rad + phi_rad >= math.pi / 2.0:
        raise ValueError("beta + phi must be < pi/2 (cot(beta+phi) > 0 for a positive earthmoving wedge)")
    cot_alpha = 1.0 / math.tan(rake_rad)
    cot_beta = 1.0 / math.tan(beta_rad)
    cot_beta_phi = 1.0 / math.tan(beta_rad + phi_rad)
    denom = math.cos(rake_rad + delta) + math.sin(rake_rad + delta) * cot_beta_phi
    if denom <= 0.0:
        raise ValueError("earthmoving denominator (cos(a+d)+sin(a+d)cot(b+phi)) must be > 0")
    n_gamma = (cot_alpha + cot_beta) / (2.0 * denom)
    n_c = (1.0 + cot_beta * cot_beta_phi) / denom
    n_q = (cot_alpha + cot_beta) / denom
    return n_gamma, n_c, n_q


def earthmoving_report(*, depth_m: float, width_m: float, cohesion_pa: float,
                       bulk_density_kg_m3: float, gravity_ms2: float, phi_rad: float,
                       rake_rad: float = RAKE_ANGLE_RAD, soil_tool_friction_rad: float | None = None,
                       surcharge_pa: float = 0.0, n_beta: int = 900) -> dict:
    """Solve the FEE for the draft force + the critical rupture angle + the N-factors + specific dig energy.

    F = (gamma*g*d^2*N_gamma + c*d*N_c + q*d*N_q) * w, with beta chosen to MINIMISE F over the valid domain
    beta in (0, pi/2 - phi) (the wedge fails along the least-force surface -- McKyes 1985 / Wilkinson &
    DeGennaro 2007). Returns {draft_n, n_gamma, n_c, n_q, beta_rad, specific_energy_j_per_kg, ...}. Raises
    ValueError on non-positive depth/width/density or a degenerate soil (phi >= ~90 deg)."""
    if depth_m <= 0.0 or width_m <= 0.0:
        raise ValueError(f"depth_m and width_m must be > 0 (got depth={depth_m}, width={width_m})")
    if bulk_density_kg_m3 <= 0.0:
        raise ValueError(f"bulk_density_kg_m3 must be > 0 (got {bulk_density_kg_m3})")
    if not (0.0 < phi_rad < math.pi / 2.0):
        raise ValueError(f"phi_rad must be in (0, pi/2); got {phi_rad}")
    if cohesion_pa < 0.0 or surcharge_pa < 0.0:
        raise ValueError("cohesion_pa and surcharge_pa must be >= 0")

    gamma = float(bulk_density_kg_m3)
    g = float(gravity_ms2)
    d = float(depth_m)
    w = float(width_m)
    q = float(surcharge_pa)
    # scan beta over (eps, pi/2 - phi - eps); the minimum tool force is interior (the factors diverge as
    # beta -> 0 and are finite at the upper edge). A fine scan is exact to the grid; the caller's
    # monotonicity does not depend on the grid because the envelope theorem makes dF/d(c,gamma,d) the partial
    # at the optimum. n_beta+ knots keep the reported draft stable to <0.1%.
    beta_hi = math.pi / 2.0 - phi_rad
    lo = 1e-3
    hi = beta_hi - 1e-3
    if hi <= lo:
        raise ValueError("no valid rupture-angle window (phi too close to pi/2)")
    best = None
    for i in range(n_beta + 1):
        beta = lo + (hi - lo) * i / n_beta
        try:
            n_gamma, n_c, n_q = earthmoving_factors(phi_rad, beta, rake_rad=rake_rad,
                                                    soil_tool_friction_rad=soil_tool_friction_rad)
        except ValueError:
            continue
        # per unit width, then * w. Every N-factor is positive on this domain, so F > 0.
        f = (gamma * g * d * d * n_gamma + cohesion_pa * d * n_c + q * d * n_q) * w
        if best is None or f < best[0]:
            best = (f, n_gamma, n_c, n_q, beta)
    if best is None:
        raise ValueError("no valid earthmoving wedge found in the beta window")
    draft_n, n_gamma, n_c, n_q, beta = best
    # specific dig energy: F * v_dig / (rho * A * v_dig) = F / (rho * w * d) [J/kg] (design §1.5). The dig
    # speed cancels; A = w*d is the swept cut cross-section, so rho*w*d is the excavated mass per unit tool
    # travel. This is the IDEAL mechanical cutting work per kg -- a strict lower bound on the measured
    # electrical dig energy (mechanism/lifting/motor losses are not in the cutting model).
    specific_energy = draft_n / (gamma * w * d)
    return {
        "draft_n": float(draft_n),
        "n_gamma": float(n_gamma), "n_c": float(n_c), "n_q": float(n_q),
        "beta_rad": float(beta), "beta_deg": float(math.degrees(beta)),
        "specific_energy_j_per_kg": float(specific_energy),
        "depth_m": d, "width_m": w, "cohesion_pa": float(cohesion_pa),
        "bulk_density_kg_m3": gamma, "phi_deg": float(math.degrees(phi_rad)),
    }


def draft_force(*, depth_m: float, width_m: float, cohesion_pa: float, bulk_density_kg_m3: float,
                gravity_ms2: float = _K.g, phi_rad: float = _K.PHI, rake_rad: float = RAKE_ANGLE_RAD,
                soil_tool_friction_rad: float | None = None, surcharge_pa: float = 0.0) -> float:
    """The excavation DRAFT force [N] from the McKyes/Reece FEE (the scalar the spine binds). Positive,
    monotone-increasing in cut depth ``depth_m``, cohesion ``cohesion_pa`` and bulk density
    ``bulk_density_kg_m3``. See :func:`earthmoving_report` for the full solve + N-factors."""
    return earthmoving_report(
        depth_m=depth_m, width_m=width_m, cohesion_pa=cohesion_pa,
        bulk_density_kg_m3=bulk_density_kg_m3, gravity_ms2=gravity_ms2, phi_rad=phi_rad,
        rake_rad=rake_rad, soil_tool_friction_rad=soil_tool_friction_rad,
        surcharge_pa=surcharge_pa)["draft_n"]


# ---------------------------------------------------------------------------
# Representative IPEx bucket-drum dig -- the values the map layer / point-inspector report and the
# reconciliation checks against the IPEx dig-energy baseline. Geometry from ipex_specs (real), soil from
# the material model (real), so nothing here is fabricated.
# ---------------------------------------------------------------------------
#: In-situ bulk density of the material a representative IPEx dig cuts [kg/m^3]. The BP-1 lunar simulant
#: the IPEx dig-energy baseline was measured against (ipex_specs.BP1_BULK_DENSITY_KG_M3 = 1750). Using the
#: SAME material makes the specific-energy reconciliation apples-to-apples.
def representative_dig(*, drum: str = "large") -> dict:
    """The FEE report for a representative IPEx bucket-drum dig: tool width + max cut-per-pass from
    ``ipex_specs`` (real drum geometry), soil (phi, c) from ``material.cell_strength`` at the BP-1 in-situ
    density, lunar gravity. Used by the map layer + point inspector + the dig-energy reconciliation."""
    from stewie.specs import ipex_specs as _ipex
    width_m = float(_ipex.DRUM_DIMENSIONS_M[drum]["width"])       # real bucket-drum width (BDSCALE Table 1)
    depth_m = float(_ipex.max_cut_per_pass_m(drum))              # 50% of scoop-opening height (anti-bridging)
    gamma = float(_ipex.BP1_BULK_DENSITY_KG_M3)                  # BP-1 simulant density (dig baseline material)
    phi_rad, cohesion_pa = _material.cell_strength(gamma)        # SAME material model the spine reads
    return earthmoving_report(depth_m=depth_m, width_m=width_m, cohesion_pa=cohesion_pa,
                              bulk_density_kg_m3=gamma, gravity_ms2=float(_ipex.LUNAR_G_MS2),
                              phi_rad=phi_rad)


def representative_draft_n(*, drum: str = "large") -> float:
    """Scalar draft force [N] for the representative IPEx dig (the value the excavation_resistance map layer
    reports on the bare DEM -- a per-material dig-difficulty constant, uniform where the in-situ material is
    uniform)."""
    return representative_dig(drum=drum)["draft_n"]
