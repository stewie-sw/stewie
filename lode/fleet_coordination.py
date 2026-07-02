"""FS-04: multi-vehicle coordination umbrella -- the consolidated conflict-explanation surface + the safe
replan/fallback behavior on top of the FL-02/03/04 fleet machinery.

`plan_multi` already produces per-vehicle allocation + health, shared-resource reservations, space-time /
haul-path / charger deconfliction, and cross-vehicle precedence, and it sets `fleet_needs_replan` when a
rover is stranded. This module adds the two pieces FS-04 was missing:

  * `fleet_coordination_explanation` -- one HUMAN-READABLE surface over a plan's real totals (deconfliction
    status, per-rover allocation/health, cross-vehicle precedence, shared-resource reservations, and the
    replan trigger). Every line is derived from the totals; nothing is fabricated.

  * `fleet_replan_fallback` -- the SAFE replan/fallback: plan with the requested fleet; if the plan is
    feasible, return it; if a rover is stranded, RE-PLAN with successively fewer vehicles and return the
    first feasible plan (a safe reallocation to a smaller fleet); if NO vehicle count is feasible (e.g. a
    pit beyond reachable range), REFUSE to dispatch a stranding plan and return an honest infeasible
    verdict. (Full in-place reallocation across a fixed-size fleet is future MV work; shedding vehicles or
    refusing is the conservative safe behavior, and it never dispatches a plan that strands a rover.)
"""
# PROVENANCE: STEWIE LODE subsystem (A. Storey)
from __future__ import annotations

from typing import Any, Mapping


def _fleet_plan_feasible(totals: Mapping[str, Any]) -> bool:
    """A plan is feasible when no rover is stranded. Multi-vehicle: no replan trigger AND every rover's
    health is feasible. Single-vehicle: no infeasible_reasons recorded."""
    detail = totals.get("vehicles_detail") or []
    if detail:
        return (not totals.get("fleet_needs_replan")) and all(d["health"]["feasible"] for d in detail)
    return not totals.get("infeasible_reasons")


def _hours(s: Any) -> str:
    return f"{float(s or 0) / 3600:.2f}h"


def fleet_coordination_explanation(totals: Mapping[str, Any]) -> list[str]:
    """Human-readable coordination explanations derived entirely from a plan's real totals."""
    lines: list[str] = []
    detail = totals.get("vehicles_detail") or []
    n = int(totals.get("vehicles", len(detail)) or len(detail))
    conflicts = {
        "space-time": int(totals.get("vehicle_conflicts", 0) or 0),
        "temporal-crowding": int(totals.get("temporal_conflicts", 0) or 0),
        "haul-path": int(totals.get("haul_path_conflicts", 0) or 0),
        "charger": int(totals.get("charger_conflicts", 0) or 0),
    }
    active = {k: v for k, v in conflicts.items() if v}
    if not active:
        lines.append(f"{n} rovers, fully deconflicted (no space-time, haul-path, charger, or "
                     "temporal-crowding conflicts).")
    else:
        for k, v in active.items():
            lines.append(f"{v} {k} conflict(s) detected across the fleet.")
    for d in detail:
        h = d.get("health", {})
        soc = (f"{h.get('min_batt_frac', 0) * 100:.0f}%"
               if isinstance(h.get("min_batt_frac"), (int, float)) else "n/a")
        waits = []
        for key, label in (("charger_wait_s", "charger"), ("crowd_wait_s", "crowding"),
                           ("precedence_wait_s", "precedence"), ("resource_wait_s", "resource")):
            if d.get(key):
                waits.append(f"{label} {_hours(d[key])}")
        wtxt = (" waits: " + ", ".join(waits)) if waits else ""
        lines.append(f"rover {d['vehicle']}: {d.get('n_trips', 0)} trips, {h.get('health', '?')}, "
                     f"min SoC {soc}.{wtxt}")
    if totals.get("precedence_split"):
        lines.append("cross-vehicle precedence: a dependency chain was split across rovers -- the "
                     "predecessor is sequenced before its cross-rover successor.")
    if totals.get("shared_resources_modeled"):
        lines.append("shared-resource reservations modeled: concurrent admission is capped at capacity "
                     "(no over-subscription).")
    if totals.get("fleet_needs_replan"):
        lines.append("FLEET NEEDS REPLAN: a rover is stranded (infeasible allocation) -- dispatch "
                     "withheld pending a safe fallback.")
    return lines


def fleet_replan_fallback(mission, vehicles: int, **plan_kw) -> dict:
    """Safe replan/fallback on infeasibility. Returns a dict with the resolved plan totals, whether a
    replan happened, the vehicle count used, the fallback chain tried, feasibility, and the
    human-readable explanation."""
    from lode import mission_planner as MP
    tried: list[dict] = []
    first_totals: Mapping[str, Any] | None = None
    requested = int(vehicles)
    for v in range(requested, 0, -1):
        totals = MP.plan_and_simulate(mission, vehicles=v, **plan_kw)[-1]
        if first_totals is None:
            first_totals = totals
        feasible = _fleet_plan_feasible(totals)
        tried.append({"vehicles": v, "feasible": feasible})
        if feasible:
            return {"feasible": True, "vehicles": v, "replanned": v != requested,
                    "from_vehicles": requested, "totals": totals, "tried": tried,
                    "explanation": fleet_coordination_explanation(totals)}
    # nothing feasible at any fleet size -> refuse to dispatch a stranding plan (safe fallback = refuse).
    # The returned totals + explanation are the REQUESTED fleet's stranded plan (it names the stranded
    # rovers + the replan trigger), not the smallest attempt -- that is what the operator must see.
    return {"feasible": False, "vehicles": requested, "replanned": True, "from_vehicles": requested,
            "totals": first_totals, "tried": tried,
            "reason": ("no vehicle count yields a feasible plan (e.g. a pit beyond reachable range); "
                       "dispatch withheld rather than stranding a rover"),
            "explanation": fleet_coordination_explanation(first_totals or {})}
