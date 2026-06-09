"""Designated zones: HARD, non-overridable no-go / no-excavation constraints + planner enforcement."""
import os
import sys

import numpy as np
import pytest

from solnav.world import zones as Z

sys.path.insert(0, os.environ.get("DUSTGYM_ROOT", "/mnt/projects/foss_ipex/dustgym"))
_HAVE = os.path.exists("/mnt/projects/foss_ipex/dustgym/samples/lunar_dem/haworth_10km_5m/heightmap.rf32")


def test_no_excavation_zone_blocks_digging_not_traverse():
    reg = Z.ZoneRegistry()
    reg.designate(50, 50, 10, "no_excavation", "borrow-protect")
    assert reg.forbids_excavation(52, 50, 1.0) and not reg.forbids_traverse(52, 50)
    with pytest.raises(Z.ZoneViolation):
        reg.check_excavation(52, 50, 1.0)
    reg.check_traverse(52, 50)                       # traverse is allowed -> no raise


def test_no_go_zone_blocks_both_and_is_not_overridable():
    reg = Z.ZoneRegistry()
    reg.designate(0, 0, 5, "no_go", "crevasse")
    with pytest.raises(Z.ZoneViolation):
        reg.check_traverse(2, 0)
    with pytest.raises(Z.ZoneViolation):
        reg.check_excavation(2, 0)
    # non-overridable: no remove/disable API, zones are frozen immutable
    assert not hasattr(reg, "remove") and not hasattr(reg, "clear") and not hasattr(reg, "override")
    with pytest.raises(Exception):
        reg.zones[0].radius_m = 0.0                  # frozen dataclass -> cannot be relaxed


def test_keepouts_feed_planner():
    reg = Z.ZoneRegistry()
    reg.designate(30, 0, 8, "hazard", "boulder-field")
    reg.designate(60, 0, 5, "no_excavation", "pad")  # NOT a traverse keep-out
    ko = reg.keepouts_for_planner()
    assert len(ko) == 1 and ko[0]["r"] == 8           # only the traverse-forbidding (hazard) zone


def test_zones_force_nogo_in_hazard_map():
    if not _HAVE:
        return
    from planet_browser import mission_planner as MP

    from solnav.perception import hazard_map as HM
    Z2, cell = MP.load_haworth_dem()
    ox, oy = MP.flattest_anchor((Z2, cell))
    sub = (Z2[int(oy / cell):int(oy / cell) + 200, int(ox / cell):int(ox / cell) + 200].copy(), cell)
    reg = Z.ZoneRegistry()
    reg.designate(450, 250, 60, "no_go", "ops-hazard")
    hm = HM.build_hazard_map(sub, (0.0, 0.0), zones=reg)
    assert hm.meta["n_nogo_zones"] == 1
    assert not np.isfinite(hm.cost[hm.world_to_rc(450, 250)])   # the zone is a hard no-go in the map
