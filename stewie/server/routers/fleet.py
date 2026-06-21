"""Fleet router (FS-03 work area): the read surface for the cockpit Fleet pane. Returns the REAL
vehicle registry (stewie.specs.vehicles.VEHICLES -- the .py source of truth) as the fleet roster the
operator can field: per-vehicle mass, drum capacity, drive power, dig energy, capabilities, onboard
power, and provenance. The PER-PLAN fleet allocation (per-vehicle trips/energy/makespan + the
space-time conflict counts) is NOT persisted server-side -- it lives in the /plan response's
`totals.vehicles_detail` + the fleet-level conflict fields, which the cockpit already holds from the
last plan; the Fleet pane merges THIS static roster with that live plan detail. So /fleet is the
roster authority; the makespan/allocation/conflicts come from /plan. Operator+ (it is a fleet-command
work area; AG-01 / adapters.WORK_AREA_MIN_ROLE.fleet = 'operator'). No fabricated data -- every field
is read straight off the registry, and the response flags that the live allocation comes from /plan."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from stewie.server.deps import require_role

router = APIRouter()


def _vehicle_row(v) -> dict:
    """One registry Vehicle -> a JSON-safe roster row. Every value is read off the real spec; the power
    source labels are resolved through the POWER_SOURCES registry (same source of truth)."""
    from stewie.specs import vehicles as VH
    powers = []
    for pid in v.onboard_power:
        try:
            ps = VH.get_power(pid)
            powers.append({"id": ps.name, "label": ps.label, "kind": ps.kind,
                           "capacity_j": float(ps.capacity_j)})
        except KeyError:
            powers.append({"id": pid, "label": pid, "kind": "unknown", "capacity_j": 0.0})
    return {
        "id": v.name,
        "label": v.label,
        "dry_mass_kg": float(v.dry_mass_kg),
        "n_wheels": int(v.n_wheels),
        "drum_capacity_kg": float(v.drum_capacity_kg),
        "drive_power_w": float(v.drive_power_w),
        "dig_energy_j_per_kg": float(v.dig_energy_j_per_kg),
        "can_dig": v.dig_energy_j_per_kg > 0.0,
        "capabilities": sorted(v.capabilities),
        "onboard_power": powers,
        "ui_visible": bool(v.ui_visible),
        "provenance": v.provenance,
    }


@router.get("/fleet")
def get_fleet(_auth: str = Depends(require_role("operator"))):
    """FS-03: the fleet roster (the real vehicle registry) + the default fleet specs. The live
    per-vehicle ALLOCATION (trips/energy/makespan) and the space-time CONFLICT counts are a property of
    a specific plan, so they are served by /plan (totals.vehicles_detail + makespan_s + *_conflicts),
    which the cockpit holds from the last plan -- `live_allocation_source` names where the pane reads
    them, so the contract is explicit and nothing is fabricated here."""
    from stewie.specs import vehicles as VH
    rows = [_vehicle_row(v) for v in VH.VEHICLES.values()]
    return {
        "ok": True,
        "vehicles": rows,
        "count": len(rows),
        "ui_visible_count": sum(1 for r in rows if r["ui_visible"]),
        "default_vehicle": VH.DEFAULT_VEHICLE,
        # the per-plan fleet allocation/makespan/conflicts are not persisted; they come from /plan.
        "live_allocation_source": "plan.totals.vehicles_detail + makespan_s + vehicle_conflicts",
        "note": ("Roster is the real vehicle registry (specs/vehicles.py). Per-vehicle allocation, "
                 "makespan, and space-time conflicts are a property of a planned mission and are read "
                 "from the last /plan result, not stored server-side."),
    }
