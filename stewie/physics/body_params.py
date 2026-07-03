"""[REQ:BD-04] The body→terramechanics CONVERSION, on the physics side (physics/forge → bodies, the correct
dependency direction). Moved out of `stewie.specs.bodies` so that the body registry carries only raw
body/regolith data and imports no `stewie.physics` — the prerequisite for publishing `stewie-bodies` as a
zero-STEWIE-dependency package. `stewie.specs.bodies.params_for_body` remains as a lazy compatibility wrapper
that delegates here.
"""
from __future__ import annotations

import dataclasses
import math

from stewie.physics.terramechanics import TerramechanicsParams
from stewie.specs.bodies import get_body


def params_for_body(name, *, allow_analog: bool = False) -> TerramechanicsParams:
    """TerramechanicsParams for a body from its SOURCED constants (bodies_sysrev.md).

    Overrides the repo baseline with the body's sourced cohesion / friction / density / Bekker moduli where
    the literature provides them. For bodies whose Bekker moduli are UNKNOWN (Ceres) the lunar moduli stand in
    as a flagged analog; the body-sourced cohesion/friction/density are still applied. Gravity itself is
    carried separately into the load.

    H-12: for a MICROGRAVITY body (Bennu/Phobos) the gravity-loaded Bekker model is OUT OF REGIME, so this
    REFUSES to return quantitative traction/sinkage params unless allow_analog=True is passed explicitly -- in
    which case the lunar Bekker numbers stand in as a flagged analog and any output MUST be labelled analog,
    NOT predictive. The default fails closed so the planner cannot silently present microgravity results as
    predictions."""
    b = get_body(name)
    if b.bekker_regime == "microgravity" and not allow_analog:
        raise ValueError(
            f"{b.name}: the gravity-loaded Bekker pressure-sinkage model is OUT OF REGIME for this "
            f"microgravity body (g={b.g:.1e} m/s^2); quantitative traction/sinkage planning is refused. "
            f"Pass allow_analog=True to use the flagged lunar analog (label outputs analog, NOT predictive).")
    base = TerramechanicsParams.from_constants()
    kw: dict = {}
    if b.bekker is not None:
        kc, kphi, n = b.bekker
        kw.update(k_c=float(kc), k_phi=float(kphi), n_sinkage=float(n))
    if b.cohesion_pa is not None:
        kw["cohesion"] = float(b.cohesion_pa)
    if b.friction_deg is not None:
        kw["phi_rad"] = math.radians(float(b.friction_deg))
    if b.bulk_density is not None:
        kw["rho_surface"] = float(b.bulk_density)
    # PHYS-01 RESOLVED (audit 2026-06-11): do NOT lyasko-reduce here -- each body's Bekker is ALREADY the
    # body-appropriate SOURCED value (the Moon's k_phi 820000 is the NASA LTV lunar measurement, which encodes
    # the 1/6-g condition). Applying lyasko_reduce on top would DOUBLE-reduce.
    return dataclasses.replace(base, **kw)
