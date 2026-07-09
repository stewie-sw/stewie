"""[REQ:MP-09] Physics scoring of plan candidates via the conserved PhysicsBackend (PX-04, PRD §30).

Score a candidate's terramechanics with the REAL conserved authority: per-wheel static load -> static
sinkage, and a two-part feasibility check. (1) the wheel contact pressure must not exceed the ground's
allowable STATIC bearing capacity (a static-pad sub-check: a wheel/pad that bears more than the regolith
can carry sinks in). (2) the BINDING rover-trafficability gate is slip-sinkage ENTRAPMENT: for the light
IPEx, slip-sinkage (not static bearing) is the dominant failure mode (forge/bearing.py:4-6), so a candidate
that would slip-entrap on a representative leg slope is infeasible EVEN WHEN its contact pressure is well
below the Terzaghi allowable. feasible = (contact_pressure <= allowable_bearing) AND (not entrapped). An
infeasible candidate is FLAGGED (feasible=False, score<0) so it is never silently ranked. All inputs are real:
the stewie.specs.vehicles geometry, the body's gravity, and the backend's soil params -- no fabricated numbers.
Only a CONSERVED (release-authority) backend may score for planning.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from stewie.physics import slip as SL
from stewie.physics.backend import PhysicsBackend, get_backend
from stewie.specs import bodies as B
from stewie.specs import ipex_specs as S
from stewie.specs import vehicles as V


class PhysicsScoreError(Exception):
    """Raised when planning-scoring is attempted with a non-conserved (non-release-authority) backend."""


@dataclass(frozen=True)
class PhysicsScore:
    """A candidate's physics score from the conserved backend: the real terramechanics quantities + a
    feasibility flag + a scalar score (higher = better; only a feasible candidate gets a positive score).
    ``entrapped`` is the slip-sinkage verdict at the representative leg slope -- the BINDING trafficability
    gate for the light IPEx; ``allowable_bearing_pa`` vs ``contact_pressure_pa`` is the static-pad sub-check."""
    per_wheel_load_n: float
    sinkage_m: float
    contact_pressure_pa: float
    allowable_bearing_pa: float
    entrapped: bool
    feasible: bool
    score: float


def score_candidate(*, body: str, payload_kg: float, vehicle_name: str = "ipex",
                    slope_deg: float = S.NOMINAL_SLOPE_DEG,
                    backend: PhysicsBackend | None = None) -> PhysicsScore:
    """Score a plan candidate's terramechanics via the CONSERVED backend. Feasibility has two parts:
    (1) the wheel contact pressure must not exceed the ground's allowable static bearing capacity, and
    (2) the BINDING rover-trafficability gate -- the rover must not slip-ENTRAP on the representative leg
    slope ``slope_deg`` (slip-sinkage is the dominant failure for the light IPEx, forge/bearing.py). So
    feasible = (contact_pressure <= allowable_bearing) AND (not entrapped). ``slope_deg`` defaults to the
    published IPEx mobility ConOps limit (ipex_specs.NOMINAL_SLOPE_DEG, 15 deg); pass the plan's actual
    worst leg grade for a route-specific gate. Returns a PhysicsScore; an infeasible candidate is flagged
    (feasible=False, score<0). Raises PhysicsScoreError if `backend` is not conserved."""
    be = backend or get_backend("tier2_numpy")
    if not be.conserves_mass():
        raise PhysicsScoreError("planning physics scoring requires a conserved (release-authority) backend")
    veh = V.VEHICLES[vehicle_name]
    g = B.get_body(body).g
    params = be.resolve_soil_params(body, allow_analog=True)
    load_n = be.static_wheel_load_n(payload_kg, rover_mass_dry_kg=veh.dry_mass_kg, n_wheels=veh.n_wheels, g=g)
    sinkage_m = be.wheel_static_sinkage(load_n, params=params, contact_len_m=veh.contact_len_m,
                                        contact_width_m=veh.wheel_width_m)
    contact_area_m2 = max(veh.contact_len_m * veh.wheel_width_m, 1e-9)
    contact_pressure_pa = load_n / contact_area_m2
    allowable_pa = be.allowable_bearing_pa(params.cohesion, params.phi_rad, params.rho_surface * g,
                                           veh.wheel_width_m)
    # BINDING trafficability gate: slip-sinkage entrapment on the representative leg slope. Uses the SAME
    # conserved slip-sinkage equilibrium solver the drive loop / constructability use, at the candidate's
    # TOTAL weight (per-wheel load x n_wheels) and the body-correct soil params. |slope| via abs() (a
    # descent's demand is signed but entrapment is a magnitude question), mirroring bekker_drive_power_w.
    total_weight_n = load_n * veh.n_wheels
    eq = SL.slip_sinkage_equilibrium(total_weight_n, math.radians(abs(slope_deg)), n_wheels=veh.n_wheels,
                                     contact_len_m=veh.contact_len_m, contact_width_m=veh.wheel_width_m,
                                     params=params)
    entrapped = bool(eq["entrapped"])
    feasible = (contact_pressure_pa <= allowable_pa) and (not entrapped)
    score = (1.0 / (1.0 + sinkage_m)) if feasible else -1.0
    return PhysicsScore(per_wheel_load_n=load_n, sinkage_m=sinkage_m,
                        contact_pressure_pa=contact_pressure_pa, allowable_bearing_pa=allowable_pa,
                        entrapped=entrapped, feasible=feasible, score=score)


def rank_feasible(scores: list[PhysicsScore]) -> list[PhysicsScore]:
    """Rank ONLY the feasible candidates, best score first. Infeasible candidates are EXCLUDED (flagged, not
    silently ranked), so an infeasible candidate can never outrank a feasible one."""
    return sorted((s for s in scores if s.feasible), key=lambda s: s.score, reverse=True)
