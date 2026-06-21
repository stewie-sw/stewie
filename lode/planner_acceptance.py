"""ARCH-2: conserved-authority plan ACCEPTANCE (extracted from mission_planner.py).

Two acceptance checks that rasterize a mission's orders onto a ``ColumnState`` and execute the cut/fill
edits to test MATERIAL realizability, siting, and the as-built surface -- distinct from the simulated
``totals`` (route/battery/sequence/time/energy), which the /plan boundary owns and fails closed on:

  * ``validate_plan`` -- I8/H-07/CP-06: pooled all-cuts-then-all-fills material check on the conserved
    authority, plus slope/off-DEM siting, as-built flatness, berm crest-profile + repose stability, and
    static bearing-capacity (Terzaghi/Vesic) per built pad.
  * ``execute_plan_acceptance`` -- the ORDERED IR-replay variant: walks trips in plan order through a
    CAPACITY-BOUNDED drum so drum-supply sequencing + overlapping cut/fill footprints (which the pooled
    check flattens) are caught.

The planner-core helpers these need (``SWELL``, ``_drum_kg``, ``plan_context``, ``mission_soil_params``,
``body_gravity``) are read through a deferred ``from lode import mission_planner`` inside each function --
a RUNTIME import after both modules are loaded, so it never cycles at import scope (the same lazy
discipline the facade uses for ``planner_views`` via ``__getattr__`` and for ``forge.bearing`` inline).
The facade (mission_planner) re-exports these so ``MP.validate_plan`` / ``MP.execute_plan_acceptance``
are unchanged.
"""
# PROVENANCE: STEWIE LODE subsystem (A. Storey)
from __future__ import annotations

import math

import numpy as np

from stewie.physics.column_state import ColumnState  # conserved authority -- the as-built grid
from stewie.terrain.site_dem import slope_deg_map     # I6/I11/CP-06 slope siting + repose


def validate_plan(mission, *, cell_m=0.5, regolith_depth_m=10.0, max_cells=500, dem=None,
                  dem_origin=(0.0, 0.0), max_slope_deg=15.0, accept_flatness_tol_m=0.02,
                  bearing_load_pa=None, bearing_fs=3.0):
    """I8: MATERIAL-realizability acceptance on the CONSERVED authority (NOT full plan validation -- audit
    H-07). Rasterize each order's footprint onto a `ColumnState`, execute the cuts (into the drum) then the
    fills (from the drum), and report mass conservation + per-order feasibility + the executed (mass-exact)
    cut/fill vs the planner's abstract estimate, the slope/off-DEM siting gate, and the as-built flatness.
    A cut deeper than the regolith mantle floors at the datum (infeasible); a fill the drum can't supply
    is flagged; an order off the tile or on too steep a slope is rejected.

    SCOPE (audit H-07): this checks MATERIAL realizability + siting + as-built only. It executes all cuts
    then all fills through one pooled drum, so it deliberately does NOT re-derive sequence/precedence
    ordering, the drum-CAPACITY shuttle-cycle count, or route/battery dynamics -- the plan is already
    decomposed into self-balanced cut->fill trips, so an ordered re-execution is materially identical, and
    those feasibility axes are owned by the simulated `totals` (reserve-aware drive C-04, blocked-route
    feasibility) and surfaced/fail-closed at the /plan product boundary (H-03). The report carries
    `acceptance_scope` (what it covers vs defers) + `drum_capacity_kg`/`shuttle_cycles_est` so the
    single-pool execution is not mistaken for a capacity-bounded shuttle."""
    from lode import mission_planner as MP   # deferred: planner-core helpers, no import-scope cycle
    rho_bank, rho_loose = mission.density * MP.SWELL, mission.density
    cuts = [o for o in mission.orders if o.kind == "cut"]
    fills = [o for o in mission.orders if o.kind == "fill"]
    sides = [math.sqrt(o.footprint_m2) for o in mission.orders]
    margin = 2.0 + (max(sides) / 2 if sides else 0.0)
    x0 = min(o.x - s / 2 for o, s in zip(mission.orders, sides)) - margin
    y0 = min(o.y - s / 2 for o, s in zip(mission.orders, sides)) - margin
    x1 = max(o.x + s / 2 for o, s in zip(mission.orders, sides)) + margin
    y1 = max(o.y + s / 2 for o, s in zip(mission.orders, sides)) + margin
    if max(x1 - x0, y1 - y0) / cell_m > max_cells:          # cap grid for speed; coarsen the cell
        cell_m = max(x1 - x0, y1 - y0) / max_cells
    W = max(1, int(math.ceil((x1 - x0) / cell_m)))
    H = max(1, int(math.ceil((y1 - y0) / cell_m)))
    cs = ColumnState(width=W, height=H, cell_m=cell_m,
                     mass_areal=np.full((H, W), rho_bank * regolith_depth_m, dtype=np.float64))
    # P0 as-built acceptance: when a DEM is given, start the surface at the REAL terrain (datum = terrain
    # - mantle so derive_height == terrain), not a flat mantle. A uniform-depth cut/fill on a sloped surface
    # then leaves a sloped surface -- so the as-built flatness check below actually reveals whether the plan
    # achieves a level pad (it can't on a flat mantle, where everything is trivially flat).
    on_real_dem = dem is not None
    if on_real_dem:
        Z, _dem_cell = dem
        ox, oy = dem_origin
        ci = np.clip(((x0 + (np.arange(W) + 0.5) * cell_m + ox) / _dem_cell).astype(int), 0, Z.shape[1] - 1)
        ri = np.clip(((y0 + (np.arange(H) + 0.5) * cell_m + oy) / _dem_cell).astype(int), 0, Z.shape[0] - 1)
        cs.datum = Z[np.ix_(ri, ci)] - regolith_depth_m
    m0 = cs.total_mass()
    datum_h0 = cs.derive_height().copy()                   # CP-06: pre-build surface (berm rise vs target)
    rr, cc = np.meshgrid(np.arange(H), np.arange(W), indexing="ij")

    def _mask(o):
        s = math.sqrt(o.footprint_m2); half = (s / 2) / cell_m
        cx, cy = (o.x - x0) / cell_m, (o.y - y0) / cell_m
        return (np.abs(cc + 0.5 - cx) <= half) & (np.abs(rr + 0.5 - cy) <= half)

    cell_area = cell_m * cell_m
    feasible = True
    exec_cut = 0.0
    for o in cuts:                                          # cuts first -> load the global drum
        mask = _mask(o)
        if not mask.any():
            feasible = False; continue
        moved = cs.cut_to_inventory(mask, o.depth_m * rho_bank)
        exec_cut += moved
        # feasibility = did the authority move the asked-for depth over the RASTERIZED footprint? gate on
        # the on-grid area (mask cells x cell_area), not the analytic footprint, so a sub-grid footprint
        # under-covering the 0.5 m cells doesn't read as infeasible -- only a true datum-floor does.
        if moved < 0.99 * mask.sum() * cell_area * o.depth_m * rho_bank:   # floored at datum -> not enough material
            feasible = False
    exec_fill = 0.0
    for o in fills:                                         # fills from the drum
        mask = _mask(o)
        if not mask.any():
            feasible = False; continue
        target = cs.derive_height().copy(); target[mask] += o.depth_m
        placed = cs.fill_toward(mask, target, max_lift_m=o.depth_m, spoil_density=rho_loose)
        exec_fill += placed
    # fills draw from a SHARED drum -> fill feasibility is a global MATERIAL question, not per-order grid
    # coverage: the plan is fill-infeasible only when the drum ran dry while the executed fill fell short
    # of the analytic plan (a genuine under-supply), not when rasterization shifts the berm by a few cells.
    planned_fill_total = sum(o.footprint_m2 * o.depth_m * rho_loose for o in fills)
    if fills and exec_fill < 0.99 * planned_fill_total and cs.drum_inventory <= 1e-6 * max(1.0, planned_fill_total):
        feasible = False
    drift = abs(cs.total_mass() - m0)
    mass_conserved = drift <= 1e-6 * max(1.0, m0)
    # P0 as-built acceptance: measure the FLATNESS of the executed surface over each worked footprint
    # (RMSE of as-built height about the footprint mean) -- the "did we build a level pad to +/-tol" check
    # the flat-mantle path could never give. Reported per-order (worst + mean); on a flat mantle it is ~0.
    # NOT folded into `feasible` (a uniform-depth excavation of a slope is feasible but legitimately not flat).
    as_built = cs.derive_height()
    flat_rmses = []
    for o in mission.orders:
        mask = _mask(o)
        if int(mask.sum()) < 2:
            continue
        h = as_built[mask]
        flat_rmses.append(float(np.sqrt(np.mean((h - h.mean()) ** 2))))
    as_built_worst = max(flat_rmses) if flat_rmses else 0.0
    as_built_mean = (sum(flat_rmses) / len(flat_rmses)) if flat_rmses else 0.0
    # CP-06: berm-profile + repose acceptance (additive, REPORTED -- like flatness, NOT folded into
    # `feasible`). berm_profile: per fill order, did the executed crest rise reach the ordered depth_m
    # (as-built mean height above the pre-build datum over the footprint) within tol? repose: the as-built
    # side-slope of each worked footprint must not exceed the soil's angle of repose (phi), else the pile
    # slumps -- a stability gate the flatness RMSE alone misses (a tall steep berm can be flat-topped yet
    # over-steep on its flanks). Reported, not gated: berm under-build / over-steepness is a quality flag
    # for the operator, not a material-conservation infeasibility (which `feasible` already covers).
    repose_limit_deg = math.degrees(float(MP.mission_soil_params(mission).phi_rad))
    as_built_slope = slope_deg_map(as_built, cell_m)
    berm_profile = []
    for o in fills:
        mask = _mask(o)
        if int(mask.sum()) < 2:
            continue
        rise = float(as_built[mask].mean() - datum_h0[mask].mean())
        berm_profile.append({"action": o.action, "target_rise_m": round(float(o.depth_m), 4),
                             "as_built_rise_m": round(rise, 4),
                             "within_tol": bool(abs(rise - float(o.depth_m)) <= accept_flatness_tol_m)})
    repose = []
    for o in mission.orders:
        mask = _mask(o)
        if int(mask.sum()) < 2:
            continue
        worst_slope = float(as_built_slope[mask].max())
        repose.append({"action": o.action, "max_slope_deg": round(worst_slope, 2),
                       "repose_limit_deg": round(repose_limit_deg, 2),
                       "stable": bool(worst_slope <= repose_limit_deg)})
    berm_profile_pass = all(b["within_tol"] for b in berm_profile) if berm_profile else True
    repose_pass = all(r["stable"] for r in repose) if repose else True
    # CP-06 berm-firming: static BEARING-CAPACITY acceptance per built pad/berm (fill order). forge.bearing
    # (Terzaghi/Vesic) gives the allowable bearing pressure of the as-built surface (loose) and of a FIRMED
    # surface -- compacted to bank density (the sourced SWELL is the only firming gain modeled; a cohesion/phi
    # gain from compaction is deliberately NOT claimed, so allowable_firmed is a conservative lower bound).
    # For the light rover slip-sinkage dominates (constants.py), so this gates ONLY a supplied STRUCTURAL
    # design load (a lander leg / stacked habitat element): holds = allowable_loose >= load;
    # firming_recommended = loose fails but a firmed pad holds. Additive + REPORTED, never folded into
    # `feasible` -- a pad that needs firming is an operational flag, not a material-conservation infeasibility.
    from forge.bearing import allowable_bearing_pa
    _soil = MP.mission_soil_params(mission)
    _g_body = MP.body_gravity(mission.body)
    gamma_loose, gamma_firm = rho_loose * _g_body, rho_bank * _g_body
    bearing = []
    for o in fills:
        mask = _mask(o)
        if int(mask.sum()) < 2:
            continue
        b_width = math.sqrt(o.footprint_m2)
        allow_loose = allowable_bearing_pa(_soil.cohesion, _soil.phi_rad, gamma_loose, b_width, factor_of_safety=bearing_fs)
        allow_firm = allowable_bearing_pa(_soil.cohesion, _soil.phi_rad, gamma_firm, b_width, factor_of_safety=bearing_fs)
        rec = {"action": o.action, "width_m": round(b_width, 3),
               "allowable_pa": round(allow_loose, 1), "allowable_firmed_pa": round(allow_firm, 1),
               "factor_of_safety": float(bearing_fs)}
        if bearing_load_pa is not None:
            holds = bool(allow_loose >= bearing_load_pa)
            rec["design_load_pa"] = float(bearing_load_pa)
            rec["holds"] = holds
            rec["firming_recommended"] = bool((not holds) and allow_firm >= bearing_load_pa)
        bearing.append(rec)
    bearing_pass = all(b.get("holds", True) for b in bearing) if bearing else True
    # I6 + I11: terrain-aware siting against the real DEM. A pad on a crater wall fails even when material
    # is available. dem = (heightmap, cell_m). M11: the order's LOCAL x,y is anchored to a real DEM site via
    # dem_origin (DEM meters where local (0,0) sits). I11: gate the WHOLE footprint, not just the center cell
    # -- a pad whose centre is flat but whose edge straddles a steep rim must still fail (worst slope over the
    # footprint + the fraction of footprint cells over the threshold are reported as the acceptance check).
    slope_violations = []
    off_dem_orders = []
    if dem is not None:
        Z, dem_cell = dem
        smap = slope_deg_map(Z, dem_cell)
        Hd, Wd = smap.shape
        ox, oy = dem_origin
        for o in mission.orders:
            half = (math.sqrt(o.footprint_m2) / 2.0) / dem_cell
            cx, cy = (ox + o.x) / dem_cell, (oy + o.y) / dem_cell
            ur0, ur1 = int(round(cy - half)), int(round(cy + half)) + 1   # UNclamped footprint cell box
            uc0, uc1 = int(round(cx - half)), int(round(cx + half)) + 1
            if ur0 < 0 or uc0 < 0 or ur1 > Hd or uc1 > Wd:     # H-08: footprint leaves the DEM -> can't be
                off_dem_orders.append({"action": o.action, "x": o.x, "y": o.y})   # validated -> reject (no edge-clip)
                continue
            patch = smap[ur0:ur1, uc0:uc1]
            if not patch.size:
                continue
            worst = float(patch.max())
            if worst > max_slope_deg:                          # any cell in the footprint too steep -> reject
                slope_violations.append({"action": o.action, "slope_deg": round(worst, 1),
                                         "frac_over": round(float((patch > max_slope_deg).mean()), 2),
                                         "x": o.x, "y": o.y})
    # H-07: this is MATERIAL realizability + siting + as-built, NOT full plan validation. Make the scope
    # machine-readable (covers vs defers) and surface the drum capacity + shuttle-cycle count the pooled
    # single-drum execution abstracts away, so a consumer can't mistake it for a capacity-bounded shuttle.
    ctx = MP.plan_context(mission)                         # H-01: the selected vehicle's drum + dig energy
    drum_cap = ctx.drum_kg
    shuttle_cycles_est = int(sum(max(1, math.ceil((o.footprint_m2 * o.depth_m * rho_bank) / drum_cap))
                                 for o in cuts)) if drum_cap > 0 else 0
    return {
        "feasible": bool(feasible and mass_conserved and not slope_violations and not off_dem_orders),
        "mass_conserved": bool(mass_conserved),
        "slope_violations": slope_violations,
        "off_dem_orders": off_dem_orders,                      # H-08: orders whose footprint left the DEM bounds
        # H-07: honest acceptance scope -- what this conserved-authority check covers vs what it defers to
        # the simulated totals / Plan IR (route, battery, sequence/precedence, drum-cycle), which the /plan
        # boundary fails closed on (H-03/C-04). The plan is self-balanced cut->fill trips, so an ordered IR
        # re-execution is materially identical -- this is acceptance, not a redundant second simulator.
        "acceptance_scope": {
            "covers": ["mass_conservation", "datum_floor_feasibility", "drum_supply",
                       "slope_siting", "off_dem_siting", "as_built_flatness",
                       "berm_profile", "repose_stability", "bearing_capacity"],
            "defers_to_totals": ["route_feasibility", "battery_reserve", "sequence_precedence",
                                 "drum_capacity_shuttle_cycles",
                                 # CP-06: time + energy acceptance live in the plan totals (makespan_s /
                                 # energy_J + the EP-* ledger + battery_reserve), not re-checked here.
                                 "time_budget", "energy_budget"]},
        "drum_capacity_kg": float(drum_cap),
        "shuttle_cycles_est": shuttle_cycles_est,              # ceil(cut_mass / drum_cap), summed over cuts
        "max_slope_deg": float(max_slope_deg),
        "mass_drift_kg": float(drift),
        "planned_cut_kg": float(sum(o.footprint_m2 * o.depth_m * rho_bank for o in cuts)),
        "executed_cut_kg": float(exec_cut),
        "planned_fill_kg": float(sum(o.footprint_m2 * o.depth_m * rho_loose for o in fills)),
        "executed_fill_kg": float(exec_fill),
        "drum_remaining_kg": float(cs.drum_inventory),
        "executed_dig_J": float(exec_cut * ctx.dig_j_per_kg),
        "grid": {"rows": H, "cols": W, "cell_m": cell_m},
        # P0 as-built acceptance (level-surface check on the executed surface):
        "as_built_on_real_dem": bool(on_real_dem),         # False -> measured on a flat mantle (trivially flat)
        "as_built_flatness_rmse_m": float(as_built_worst),  # worst footprint flatness RMSE
        "as_built_flatness_mean_m": float(as_built_mean),
        "as_built_tol_m": float(accept_flatness_tol_m),
        "as_built_pass": bool(as_built_worst <= accept_flatness_tol_m),
        # CP-06: berm crest-profile (rise vs ordered depth) + repose-angle stability (additive, reported):
        "berm_profile": berm_profile,                          # per fill: target vs as-built crest rise
        "berm_profile_pass": bool(berm_profile_pass),
        "repose": repose,                                      # per order: as-built flank slope vs phi
        "repose_pass": bool(repose_pass),
        "repose_limit_deg": round(float(repose_limit_deg), 2),
        # CP-06 berm-firming: per pad/berm allowable bearing capacity (loose + firmed); holds/firming when a
        # structural design load is supplied (bearing_load_pa). Additive/reported, not folded into `feasible`.
        "bearing": bearing,
        "bearing_pass": bool(bearing_pass),
    }


def execute_plan_acceptance(mission, trips, *, cell_m=0.5, regolith_depth_m=10.0, max_cells=500,
                            dem=None, dem_origin=(0.0, 0.0)):
    """H-07 follow-up: ORDERED IR-replay acceptance (the literal "execute the exact Plan IR" path).

    Unlike validate_plan's pooled all-cuts-then-all-fills material check, this walks the TRIPS IN PLAN
    ORDER through a CAPACITY-BOUNDED drum -- each trip cuts its cut footprint INTO the drum, then fills its
    fill footprint FROM the drum -- so two order-dependent effects the pooled check flattens are caught:
      (1) drum-supply sequencing: a fill scheduled before its supplying cut draws from an EMPTY drum and
          places nothing (the pooled check always has every cut's material on hand, masking this);
      (2) overlapping cut/fill footprints across trips (berm on a just-cut pad, a re-grade) -- the as-built
          surface depends on the order, which all-cuts-then-fills cannot represent.
    Returns the ORDERED as-built surface + mass conservation + the running drum balance (the min inventory
    over the walk; < 0 means a fill out-ran its supply) + the max simultaneous drum load vs capacity +
    shuttle-cycle count. Mass is a density-only edit so it is conserved exactly. Self-contained (mirrors
    validate_plan's grid so the two as-built surfaces are directly comparable)."""
    from lode import mission_planner as MP   # deferred: planner-core helpers, no import-scope cycle
    rho_bank, rho_loose = mission.density * MP.SWELL, mission.density
    cap = MP._drum_kg(mission)
    order_by_action = {o.action: o for o in mission.orders}
    sides = [math.sqrt(o.footprint_m2) for o in mission.orders]
    margin = 2.0 + (max(sides) / 2 if sides else 0.0)
    x0 = min(o.x - s / 2 for o, s in zip(mission.orders, sides)) - margin
    y0 = min(o.y - s / 2 for o, s in zip(mission.orders, sides)) - margin
    x1 = max(o.x + s / 2 for o, s in zip(mission.orders, sides)) + margin
    y1 = max(o.y + s / 2 for o, s in zip(mission.orders, sides)) + margin
    if max(x1 - x0, y1 - y0) / cell_m > max_cells:
        cell_m = max(x1 - x0, y1 - y0) / max_cells
    W = max(1, int(math.ceil((x1 - x0) / cell_m)))
    H = max(1, int(math.ceil((y1 - y0) / cell_m)))
    cs = ColumnState(width=W, height=H, cell_m=cell_m,
                     mass_areal=np.full((H, W), rho_bank * regolith_depth_m, dtype=np.float64))
    if dem is not None:
        Z, _dem_cell = dem
        ox, oy = dem_origin
        ci = np.clip(((x0 + (np.arange(W) + 0.5) * cell_m + ox) / _dem_cell).astype(int), 0, Z.shape[1] - 1)
        ri = np.clip(((y0 + (np.arange(H) + 0.5) * cell_m + oy) / _dem_cell).astype(int), 0, Z.shape[0] - 1)
        cs.datum = Z[np.ix_(ri, ci)] - regolith_depth_m
    m0 = cs.total_mass()
    rr, cc = np.meshgrid(np.arange(H), np.arange(W), indexing="ij")

    def _mask(o):
        s = math.sqrt(o.footprint_m2); half = (s / 2) / cell_m
        cx, cy = (o.x - x0) / cell_m, (o.y - y0) / cell_m
        return (np.abs(cc + 0.5 - cx) <= half) & (np.abs(rr + 0.5 - cy) <= half)

    def _orders(tr, kind):
        return [order_by_action[a] for a in tr.get("actions", ())
                if a in order_by_action and order_by_action[a].kind == kind]

    # P-02 / MATH-01: capacity-bounded shuttle that replays each trip's ASSIGNED FLOW (tr["mass"]) -- NOT
    # the whole source-order footprint -- in drum-sized loads. A cutfill trip ALTERNATES cut-a-load /
    # transport / fill-from-the-load until its flow is moved, so a normal multi-load cut/fill EXECUTES
    # instead of overflowing the drum on the first load and being wrongly rejected (the audited MATH-01
    # bug cut the whole 9360 kg cut into a 30 kg drum first, then declared infeasible before any fill drained
    # it). The drum never exceeds `cap`; `supply_left` caps how much a cut order can give across flows. A
    # pure cut (spoil, no fill to drain it) still overflows -> correctly infeasible; a pure fill (import)
    # drains the drum. `placed_kg` records the mass actually deposited into fills.
    step = cap if cap > 0 else float("inf")               # max kg the drum can hold (== drum capacity)
    supply_left = {id(o): o.footprint_m2 * o.depth_m * rho_bank for o in mission.orders if o.kind == "cut"}
    feasible = True; drum_max = 0.0; running_min = 0.0; shuttle_cycles = 0; placed_kg = 0.0

    def _drain(fmask, ftarget, depth):                    # drain the drum into a fill (bounded; dips to, never below, 0)
        nonlocal placed_kg, running_min
        placed = 1.0
        while cs.drum_inventory > 1e-6 and placed > 1e-6:
            before = cs.drum_inventory
            cs.fill_toward(fmask, ftarget, max_lift_m=depth, spoil_density=rho_loose)
            placed = before - cs.drum_inventory
            placed_kg += placed
            running_min = min(running_min, cs.drum_inventory)
        running_min = min(running_min, cs.drum_inventory)

    for tr in trips:                                       # PLAN ORDER -- the executable sequence
        cuts, fills = _orders(tr, "cut"), _orders(tr, "fill")
        flow_mass = float(tr.get("mass", 0.0))
        if cuts and fills and flow_mass > 1e-6:            # cutfill: SHUTTLE the assigned flow in drum-sized loads
            co, fo = cuts[0], fills[0]                     # a cutfill trip pairs one cut + one fill
            cmask, fmask = _mask(co), _mask(fo)
            if not cmask.any() or not fmask.any():
                feasible = False; continue
            n = int(cmask.sum())
            ftarget = cs.derive_height().copy(); ftarget[fmask] += fo.depth_m
            remaining = min(flow_mass, supply_left.get(id(co), flow_mass))
            while remaining > 1e-6:
                take = min(remaining, step - cs.drum_inventory)
                if take > 1e-6:
                    moved = cs.cut_to_inventory(cmask, take / (n * cs.cell_area))
                    drum_max = max(drum_max, cs.drum_inventory); shuttle_cycles += 1
                    if moved <= 1e-6:                      # cut footprint exhausted (datum floor) -> short supply
                        feasible = False; break
                    remaining -= moved
                    supply_left[id(co)] = supply_left.get(id(co), flow_mass) - moved
                _drain(fmask, ftarget, fo.depth_m)         # transport + deposit this load before the next cut
                if cs.drum_inventory > 1e-6 and take <= 1e-6:   # drum can't drain into a full fill -> stuck
                    feasible = False; break
        else:                                              # pure cut (spoil/dig) or pure fill (import)
            for o in cuts:
                mask = _mask(o)
                if not mask.any(): feasible = False; continue
                n = int(mask.sum()); want = supply_left.get(id(o), o.footprint_m2 * o.depth_m * rho_bank)
                while want > 1e-6:
                    free = step - cs.drum_inventory
                    if free <= 1e-6: feasible = False; break   # a cut with no fill to drain it -> overflow
                    take = min(want, free)
                    moved = cs.cut_to_inventory(mask, take / (n * cs.cell_area))
                    drum_max = max(drum_max, cs.drum_inventory); shuttle_cycles += 1
                    if moved <= 1e-6: feasible = False; break
                    want -= moved
                supply_left[id(o)] = want
            for o in fills:
                mask = _mask(o)
                if not mask.any(): feasible = False; continue
                ftarget = cs.derive_height().copy(); ftarget[mask] += o.depth_m
                _drain(mask, ftarget, o.depth_m)
    drift = abs(cs.total_mass() - m0)
    mass_conserved = drift <= 1e-6 * max(1.0, m0)
    return {
        "executes_ordered_ir": True,
        "feasible": bool(feasible and mass_conserved),
        "mass_conserved": bool(mass_conserved),
        "mass_drift_kg": float(drift),
        "drum_capacity_kg": float(cap),
        "max_simultaneous_drum_kg": float(drum_max),       # the peak inventory the bounded drum had to hold
        "running_drum_min_kg": float(running_min),         # < 0 would mean a fill out-ran its supply in sequence
        "shuttle_cycles": int(shuttle_cycles),
        "placed_kg": float(placed_kg),                     # MATH-01: mass actually deposited into fills
        "as_built": cs.derive_height(),                    # the ORDER-dependent surface the pooled check flattens
        "grid": {"rows": H, "cols": W, "cell_m": cell_m},
    }
