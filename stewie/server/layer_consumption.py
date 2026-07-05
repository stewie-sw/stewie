"""[REQ:LY-02] the layer-consumption inspector — for each LY-01 catalog layer, WHERE it is consumed across the
mission surface (display / planner / costmap / rehearsal / release / execute / report / export). Consumption is
DERIVED from the LY-01 eligibility (planning_eligible / release_execute_eligible / domain / source_class), so it
is a faithful projection of the catalog, never a hand-written map that could drift: a layer feeds the planner
only if it is planning-eligible; it feeds release/execute only if it is release/execute-eligible."""
from __future__ import annotations

CONSUMERS = ["display", "planner", "costmap", "rehearsal", "release", "execute", "report", "export"]
_COSTMAP_DOMAINS = {"base", "terrain", "traffic", "hazard", "physics", "regolith"}
_REHEARSAL_DOMAINS = {"runtime", "physics", "map", "robot", "mission"}


def consumers_for(layer: dict) -> list[str]:
    """The ordered consumers of one catalog layer, derived from its eligibility + domain + source class."""
    dom = layer["domain"]
    src = layer.get("source_class", "")
    out = {"display", "report"}  # every layer is displayable + reportable (it is evidence)
    if layer["planning_eligible"]:
        out.add("planner")
        if dom in _COSTMAP_DOMAINS:
            out.add("costmap")  # the spatial cost inputs the planner rasters
    if layer["release_execute_eligible"]:
        out |= {"release", "execute"}
    if dom in _REHEARSAL_DOMAINS or "sim" in src or "observed" in src:
        out.add("rehearsal")  # runtime/observed layers a rehearsal produces or consumes
    if dom != "runtime":
        out.add("export")  # live runtime/truth layers are not exportable products
    return [c for c in CONSUMERS if c in out]
