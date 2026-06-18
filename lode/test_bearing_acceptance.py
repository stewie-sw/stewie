"""CP-06 bearing-capacity acceptance (the berm-firming P2 closure): validate_plan reports, per built
pad/berm (fill order), the allowable static bearing capacity of the as-built surface (loose) and of a
firmed (compacted-to-bank-density) surface, and -- when a design structural load is supplied -- whether
the pad holds it and whether firming would make it hold. Additive + REPORTED, NEVER folded into
`feasible` (mirrors berm_profile / repose). Real sourced soil (Moon c=170 Pa, phi=35 deg)."""
from lode import mission_planner as MP


def _balanced(footprint=4.0):
    # a cut that supplies the fill (so the mission is materially feasible) + the pad we bearing-check
    return MP.mission_from_dict({"name": "t", "body": "moon", "orders": [
        {"action": "src", "kind": "cut", "x": 2.0, "y": 2.0, "footprint_m2": 4.0, "depth_m": 0.5},
        {"action": "pad", "kind": "fill", "x": 8.0, "y": 8.0, "footprint_m2": footprint, "depth_m": 0.3},
    ]})


def test_bearing_reports_capacity_when_no_load_given():
    r = MP.validate_plan(_balanced())
    assert "bearing" in r and "bearing_capacity" in r["acceptance_scope"]["covers"]
    pads = [b for b in r["bearing"] if b["action"] == "pad"]
    assert len(pads) == 1 and {b["action"] for b in r["bearing"]} == {"pad"}   # fills only, not the cut
    b = pads[0]
    assert b["allowable_pa"] > 0.0
    assert b["allowable_firmed_pa"] > b["allowable_pa"]          # firming (denser) raises capacity
    assert "design_load_pa" not in b and "holds" not in b        # no load -> capacity-only, no gate
    assert r["bearing_pass"] is True


def test_bearing_is_additive_never_changes_feasible():
    # the SAME mission validated with and without a crushing load must report identical feasibility
    no_load = MP.validate_plan(_balanced())
    crush = MP.validate_plan(_balanced(), bearing_load_pa=1e9)
    assert no_load["feasible"] == crush["feasible"]              # bearing is reported, not gated
    assert crush["bearing"][0]["holds"] is False                 # but the bearing report does fail


def test_bearing_holds_a_light_load():
    r = MP.validate_plan(_balanced(), bearing_load_pa=3000.0)     # ~ a light rover; a lunar pad bears it
    b = [x for x in r["bearing"] if x["action"] == "pad"][0]
    assert b["holds"] is True and r["bearing_pass"] is True


def test_bearing_firming_recommended_between_loose_and_firmed():
    base = MP.validate_plan(_balanced())["bearing"][0]
    load = 0.5 * (base["allowable_pa"] + base["allowable_firmed_pa"])   # loose can't, firmed can
    b = MP.validate_plan(_balanced(), bearing_load_pa=load)["bearing"][0]
    assert b["holds"] is False
    assert b["firming_recommended"] is True


def test_bearing_overload_not_fixable_by_firming():
    firmed = MP.validate_plan(_balanced())["bearing"][0]["allowable_firmed_pa"]
    b = MP.validate_plan(_balanced(), bearing_load_pa=5.0 * firmed)["bearing"][0]   # too heavy even firmed
    assert b["holds"] is False and b["firming_recommended"] is False
