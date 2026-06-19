"""FS-05: the auditable navigation contract -- one descriptor connecting the navigation stages, each
self-reporting whether its implementing seam is wired on this host. The live Autoware/Nav2 planner binary
is the gated tier. Pure (import-check); the /nav/contract endpoint surfaces it."""
from lode.planner_routing import _NAV_STAGES, navigation_contract


def test_contract_connects_all_on_host_stages():  # [REQ:FS-05]
    c = navigation_contract()
    assert c["version"] == "1.0"
    stages = {s["stage"]: s for s in c["stages"]}
    # every on-host navigation stage is named AND its seam is importable on this host
    for name, _mod, _attr in _NAV_STAGES:
        assert stages[name]["present"] is True, (name, stages[name])
    assert {"global_route", "local_trajectory", "tracker", "recovery", "keepouts",
            "negative_obstacles", "illumination_risk", "slip_energy_budget",
            "ros_action_lowering"} <= set(stages)
    assert c["on_host_complete"] is True                       # all on-host seams wired


def test_contract_requires_callable_seams_not_just_importable():  # [REQ:FS-05]
    # FS-05 hardening: a stage is `present` only if its seam resolves to a real CALLABLE entry point, not
    # merely an importable name -- so a seam renamed to a constant (or a typo'd attr) flips to present=False
    # instead of silently passing. Every on-host seam must in fact be callable.
    import importlib
    for name, mod, attr in _NAV_STAGES:
        fn = getattr(importlib.import_module(mod), attr, None)
        assert callable(fn), f"FS-05 seam {name} ({mod}.{attr}) must be callable, got {type(fn).__name__}"
    # the contract agrees: with every seam callable, the on-host stack is complete
    assert navigation_contract()["on_host_complete"] is True


def test_ros_lowering_stage_points_at_nv11():
    seam = next(s for s in navigation_contract()["stages"] if s["stage"] == "ros_action_lowering")
    assert seam["present"] and "lower_plan_ir" in seam["seam"]   # NV-11 is the nav stack's ROS egress


def test_live_planner_binary_is_the_only_gated_tier():
    c = navigation_contract()
    gated = [s for s in c["stages"] if not s["present"]]
    assert [s["stage"] for s in gated] == ["live_planner_binary"]
    assert "gated" in gated[0]["note"].lower()                # honestly flagged, not stubbed


def test_nav_contract_endpoint_serves_it():
    import importlib

    from fastapi.testclient import TestClient
    import stewie.server.server as srv
    importlib.reload(srv)
    c = TestClient(srv.app)
    r = c.get("/nav/contract")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["ok"] and d["on_host_complete"] is True and len(d["stages"]) == len(_NAV_STAGES) + 1
