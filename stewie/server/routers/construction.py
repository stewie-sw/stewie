"""Construction router (FS-03 work area): the read surface for the cockpit Construction pane (badge FORGE,
operator+). It is the BUILD authority -- the two things an operator needs before a build is staged or
accepted, both read straight off the real source of truth (nothing fabricated):

  * the BUILD CATALOG -- the composite structure templates (leap.structures.STRUCTURES: landing pad,
    habitat foundation, blast berm, crater fill, borrow pit, haul road, solar pad, trench). Each template
    decomposes to mass-balanced cut/fill primitive orders; this router expands every template at a fixed
    probe origin with its DEFAULT params so the pane shows the real primitive breakdown (cut/fill kinds,
    footprint, depth) the planner would issue -- the same dicts mission_planner consumes.

  * the ACCEPTANCE CRITERIA -- what lode.planner_acceptance.validate_plan actually measures on the
    conserved authority (flatness RMSE tol, berm crest-profile, repose-angle stability, static
    bearing-capacity, slope/off-DEM siting, mass conservation, drum supply), plus what it DEFERS to the
    plan totals (route/battery/time/energy). This is the criteria DEFINITION (the real default tolerances
    read off the validate_plan signature); the per-plan AS-BUILT acceptance RESULT is a property of a
    specific plan, so it is served by /plan (the `validation` + `ordered_acceptance` blocks), which the
    cockpit holds from the last plan -- `live_acceptance_source` names where the pane reads it. Honest
    empty-state in the pane when no plan has been run.

Operator+ (it is a build-command work area; mirrors the Fleet tab's AG-01 operator gate)."""
from __future__ import annotations

import inspect
from typing import Any, Callable, cast

from fastapi import APIRouter, Depends

from stewie.server.deps import require_role

router = APIRouter()

#: a fixed local-frame probe origin to expand each template's default build at (meters). The catalog is
#: a CATALOG -- it shows the real primitive breakdown of each structure at its default size; the operator
#: re-sites + re-sizes it when staging the actual build.
_PROBE_XY = (0.0, 0.0)


def _template_row(name: str) -> dict:
    """One structure template -> a JSON-safe catalog row: its default-param signature + the real
    decomposed cut/fill primitive orders (leap.structures), so the pane shows what the planner issues."""
    from leap import structures as S
    fn = cast("Callable[..., Any]", S.STRUCTURES[name])
    sig = inspect.signature(fn)
    defaults = {p.name: p.default for p in sig.parameters.values()
                if p.default is not inspect.Parameter.empty}
    orders = S.decompose(name, *_PROBE_XY)
    prim = [{"action": o["action"], "kind": o["kind"],
             "footprint_m2": round(float(o["footprint_m2"]), 3),
             "depth_m": round(float(o["depth_m"]), 4), "note": o.get("note", "")}
            for o in orders]
    n_cut = sum(1 for o in prim if o["kind"] == "cut")
    n_fill = sum(1 for o in prim if o["kind"] == "fill")
    return {
        "id": name,
        "doc": (fn.__doc__ or "").strip().splitlines()[0] if fn.__doc__ else "",
        "defaults": {k: (round(float(v), 4) if isinstance(v, (int, float)) else v)
                     for k, v in defaults.items()},
        "orders": prim,
        "n_orders": len(prim),
        "n_cut": n_cut,
        "n_fill": n_fill,
        "balanced": n_cut > 0 and n_fill > 0,   # a cut<->fill pair = volume-conserved; cut-only = source/grade
    }


@router.get("/construction")
def get_construction(_auth: str = Depends(require_role("operator"))):
    """FS-03: the build catalog (real structure templates, decomposed to cut/fill primitives) + the
    acceptance-criteria DEFINITION (what validate_plan measures + its default tolerances). The per-plan
    AS-BUILT acceptance result (flatness/berm-profile/repose/bearing pass/fail on the real terrain) is a
    property of a planned mission and is served by /plan (`validation` + `ordered_acceptance`), which the
    cockpit holds from the last plan -- `live_acceptance_source` names where the pane reads it, so the
    contract is explicit and nothing is fabricated here."""
    from leap import structures as S
    from lode import planner_acceptance as PA
    rows = [_template_row(n) for n in sorted(S.STRUCTURES)]

    # the real default acceptance tolerances, read off validate_plan's signature (single source of truth).
    sig = inspect.signature(PA.validate_plan)
    def _d(p: str):
        v = sig.parameters[p].default
        return float(v) if isinstance(v, (int, float)) else v
    acceptance = {
        # what validate_plan measures on the conserved authority (the as-built acceptance checks):
        "checks": [
            {"id": "mass_conservation", "what": "all-cuts-then-all-fills balance on the conserved grid"},
            {"id": "datum_floor_feasibility", "what": "a cut deeper than the regolith mantle is infeasible"},
            {"id": "drum_supply", "what": "every fill can be supplied from the drum it was cut into"},
            {"id": "slope_siting", "what": "no order sited on slope above max_slope_deg",
             "max_slope_deg": _d("max_slope_deg")},
            {"id": "off_dem_siting", "what": "no order placed off the loaded DEM tile"},
            {"id": "as_built_flatness", "what": "executed-surface flatness RMSE within tol",
             "tol_m": _d("accept_flatness_tol_m")},
            {"id": "berm_profile", "what": "as-built crest rise reaches the ordered depth within tol",
             "tol_m": _d("accept_flatness_tol_m")},
            {"id": "repose_stability", "what": "as-built flank slope <= the soil angle of repose (phi)"},
            {"id": "bearing_capacity", "what": "Terzaghi/Vesic allowable bearing of each built pad/berm",
             "factor_of_safety": _d("bearing_fs")},
        ],
        # what acceptance DEFERS to the plan totals (route/battery/time/energy live there, not re-checked):
        "defers_to_totals": ["route_feasibility", "battery_reserve", "sequence_precedence",
                             "drum_capacity_shuttle_cycles", "time_budget", "energy_budget"],
    }
    return {
        "ok": True,
        "templates": rows,
        "count": len(rows),
        "balanced_count": sum(1 for r in rows if r["balanced"]),
        "probe_origin_m": list(_PROBE_XY),
        "acceptance": acceptance,
        # the per-plan AS-BUILT acceptance result is not persisted; it comes from /plan.
        "live_acceptance_source": "plan.validation (validate_plan) + plan.ordered_acceptance (IR replay)",
        "note": ("Catalog is the real structure-template library (leap/structures.py), each decomposed to "
                 "mass-balanced cut/fill primitives. Acceptance criteria are the real validate_plan checks "
                 "(lode/planner_acceptance.py) with their default tolerances. The AS-BUILT pass/fail on "
                 "the real terrain is a property of a planned mission and is read from the last /plan "
                 "result (validation + ordered_acceptance), not stored server-side."),
    }
