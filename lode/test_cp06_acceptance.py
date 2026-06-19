"""CP-06: validate_plan acceptance reports berm crest-profile + repose-angle stability, additively.

Today's acceptance covered flatness + mass + datum-floor + siting only. CP-06 adds two REPORTED checks
(not folded into `feasible`, mirroring as-built flatness): (1) berm_profile -- did each fill order's
executed crest rise reach the ordered depth_m (as-built mean rise above the pre-build datum) within tol;
(2) repose -- the as-built flank slope of each worked footprint vs the soil's angle of repose (phi), so an
over-steep pile/wall that would slump is flagged. Lunar phi = 35 deg (mission_soil_params)."""
import math

import lode.mission_planner as MP


def _mission(orders):
    return MP.mission_from_dict({"name": "S", "body": "moon", "charger": [0, 0], "orders": orders})


def test_cp06_fields_present_and_shaped():
    m = _mission([
        {"action": "src", "kind": "cut", "x": 5.0, "y": 5.0, "footprint_m2": 36.0, "depth_m": 0.2},
        {"action": "berm", "kind": "fill", "x": 20.0, "y": 20.0, "footprint_m2": 16.0, "depth_m": 0.1},
    ])
    r = MP.validate_plan(m)
    # repose limit is the soil angle of repose (phi), exactly
    assert abs(r["repose_limit_deg"] - math.degrees(MP.mission_soil_params(m).phi_rad)) < 1e-6
    # berm_profile reports FILL orders only; repose reports every worked footprint
    assert {b["action"] for b in r["berm_profile"]} == {"berm"}
    assert {o["action"] for o in r["repose"]} == {"src", "berm"}
    b = r["berm_profile"][0]
    assert set(b) == {"action", "target_rise_m", "as_built_rise_m", "within_tol"}
    assert b["target_rise_m"] == 0.1
    assert abs(b["as_built_rise_m"] - 0.1) <= 0.02 and b["within_tol"] is True   # fill reached its crest
    # shallow worked surfaces (0.2 cut / 0.1 fill flanks < 35 deg) are repose-stable
    assert r["repose_pass"] is True and r["berm_profile_pass"] is True
    assert "berm_profile" in r["acceptance_scope"]["covers"]
    assert "repose_stability" in r["acceptance_scope"]["covers"]


def test_cp06_repose_flags_oversteep_pile():
    # a deep narrow fill (1 m rise over a 0.5 m cell -> ~55 deg flank) exceeds the 35 deg repose limit
    r = MP.validate_plan(_mission([
        {"action": "src", "kind": "cut", "x": 5.0, "y": 5.0, "footprint_m2": 36.0, "depth_m": 1.0},
        {"action": "pad", "kind": "fill", "x": 20.0, "y": 20.0, "footprint_m2": 4.0, "depth_m": 1.0},
    ]))
    pad = [o for o in r["repose"] if o["action"] == "pad"][0]
    assert pad["max_slope_deg"] > r["repose_limit_deg"]
    assert pad["stable"] is False
    assert r["repose_pass"] is False
    # the pile DID reach its commanded crest, even though it is over-steep -> profile pass, repose fail
    assert r["berm_profile"][0]["within_tol"] is True


def test_cp06_underbuilt_berm_flagged():
    # a fill with no supplying cut draws from an empty drum -> places ~nothing -> crest far below target
    r = MP.validate_plan(_mission([
        {"action": "berm", "kind": "fill", "x": 10.0, "y": 10.0, "footprint_m2": 16.0, "depth_m": 0.3},
    ]))
    b = r["berm_profile"][0]
    assert b["target_rise_m"] == 0.3
    assert b["as_built_rise_m"] < 0.3 - 0.02            # under-built
    assert b["within_tol"] is False and r["berm_profile_pass"] is False


def test_cp06_does_not_gate_feasible():
    # repose/berm are REPORTED, not gating: an over-steep but materially-realizable plan stays feasible
    r = MP.validate_plan(_mission([
        {"action": "src", "kind": "cut", "x": 5.0, "y": 5.0, "footprint_m2": 36.0, "depth_m": 1.0},
        {"action": "pad", "kind": "fill", "x": 20.0, "y": 20.0, "footprint_m2": 4.0, "depth_m": 1.0},
    ]))
    assert r["repose_pass"] is False                   # over-steep flanks
    assert r["feasible"] is True                       # but mass-conserved + sited -> still feasible


def test_cp06_acceptance_scope_accounts_for_all_seven_terms():  # [REQ:CP-06]
    # every CP-06 acceptance term is accounted for in the scope: the geometry/mass/bearing terms are
    # CHECKED here; time + energy are explicitly DEFERRED to the plan totals (makespan_s / energy_J +
    # the EP-* ledger + battery reserve). No CP-06 term is silently missing.
    r = MP.validate_plan(_mission([
        {"action": "src", "kind": "cut", "x": 5.0, "y": 5.0, "footprint_m2": 36.0, "depth_m": 0.2},
        {"action": "berm", "kind": "fill", "x": 20.0, "y": 20.0, "footprint_m2": 16.0, "depth_m": 0.1},
    ]))
    scope = r["acceptance_scope"]
    accounted = set(scope["covers"]) | set(scope["defers_to_totals"])
    cp06_terms = {"pad flatness": "as_built_flatness", "berm profile": "berm_profile",
                  "bearing/compaction": "bearing_capacity", "repose stability": "repose_stability",
                  "mass": "mass_conservation", "time": "time_budget", "energy": "energy_budget"}
    missing = {term for term, key in cp06_terms.items() if key not in accounted}
    assert not missing, f"CP-06 acceptance terms not accounted for in the scope: {missing}"
    # time/energy are DEFERRED (carried by the totals), not re-checked in validate_plan
    assert {"time_budget", "energy_budget"} <= set(scope["defers_to_totals"])
