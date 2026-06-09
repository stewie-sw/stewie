"""Event-sourced world model: derive terrain from L0 + L4 events; protected charger zone. Real DEM."""
import os
import sys

from solnav.world import world_model as WM

sys.path.insert(0, os.environ.get("DUSTGYM_ROOT", "/mnt/projects/foss_ipex/dustgym"))
_HAVE = os.path.exists("/mnt/projects/foss_ipex/dustgym/samples/lunar_dem/haworth_10km_5m/heightmap.rf32")


def _crop():
    from planet_browser import mission_planner as MP
    Z, cell = MP.load_haworth_dem()
    return (Z[1000:1100, 1000:1100].copy(), cell)


def test_terrain_is_derived_from_events_not_stored():
    if not _HAVE:
        return
    wm = WM.WorldModel(_crop())
    base, _ = wm.current_terrain()
    e = wm.add_event(150.0, 150.0, 20.0, -0.4, kind="cut")     # excavate 40 cm over a 20 m disc
    cur, _ = wm.current_terrain()
    assert wm.delta_at(150.0, 150.0) == -0.4                   # L3 reflects the event
    assert cur[wm.world_to_rc(150, 150)] < base[wm.world_to_rc(150, 150)]  # terrain DERIVED lower
    assert e.volume_m3 > 0 and wm.excavated_near(150, 150, 5.0)  # the event is queryable


def test_reconcile_observation_infers_events():
    if not _HAVE:
        return
    wm = WM.WorldModel(_crop())
    obs, _ = wm.current_terrain()
    obs = obs.copy(); obs[40:45, 40:45] += 0.3                 # a berm appears in the observation
    new = wm.reconcile_observation(obs, min_dheight_m=0.1)
    assert new and all(ev.kind == "fill" for ev in new)        # inferred as fill events


def test_protected_charger_zone():
    if not _HAVE:
        return
    wm = WM.WorldModel(_crop())
    wm.protect(300.0, 300.0, 10.0, "charger")
    assert wm.is_protected(305.0, 300.0) and not wm.is_protected(350.0, 300.0)
    assert wm.violates_protection(308.0, 300.0, 5.0)           # digging near the charger is flagged
    assert not wm.violates_protection(330.0, 300.0, 5.0)
