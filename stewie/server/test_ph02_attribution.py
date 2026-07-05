"""[REQ:PH-02] every route/volume/risk value the executive run produces is attributed to the physics backend
that produced it (the conserved tier2_numpy authority) + its calibration model + release-eligibility -- nothing
load-bearing is left unattributed. Real end-to-end SIM run (no mocks) + a unit check that the attribution
defers to the real PH-01 physics_authority + PMC model registries (no divergent hard-coded copy)."""
from fastapi.testclient import TestClient

_ORDERS = [{"kind": "cut", "x": 10.0, "y": 10.0, "action": "dig pad", "footprint_m2": 4.0, "depth_m": 0.3}]


def _client(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("STEWIE_API_KEY", raising=False)
    monkeypatch.setenv("STEWIE_DEV_OPEN", "1")
    import stewie.server.server as SRV
    return TestClient(SRV.app)


def test_ph02_run_attributes_values_to_the_physics_backend(monkeypatch, tmp_path):  # [REQ:PH-02]
    c = _client(monkeypatch, tmp_path)
    r = c.post("/executive/run", json={"orders": _ORDERS, "site": "haworth"})
    assert r.status_code == 200, r.text
    pa = r.json()["physics_attribution"]
    assert pa["backend"] == "tier2_numpy"                       # the conserved authority produced the numbers
    assert pa["conserves_mass"] is True and pa["release_eligible"] is True
    assert "energy_J" in pa["attributed_quantities"]            # the reconciled energy is attributed
    # the calibration names the real validated + frozen model of record, not an unversioned flag
    cal = pa["calibration"]
    assert cal and cal["model_id"] == "tier2_numpy@1.0" and cal["validated"] and cal["frozen"]


def test_ph02_attribution_defers_to_the_real_registries():  # [REQ:PH-02]
    from stewie.contracts.physics_model_control import physics_attribution
    from stewie.specs.physics_authority import BACKENDS
    pa = physics_attribution("tier2_numpy", quantities=("energy_J",))
    # authority mirrors the PH-01 registry exactly (no divergent copy that could drift)
    assert pa["conserves_mass"] == BACKENDS["tier2_numpy"]["conserves_mass"]
    assert pa["release_eligible"] == BACKENDS["tier2_numpy"]["valid_for_release"]
    assert pa["authority_scope"] == list(BACKENDS["tier2_numpy"]["authority_scope"])
    # a rendering-only backend (godot) is attributed as non-conserving + not release-eligible
    gd = physics_attribution("godot")
    assert gd["conserves_mass"] is False and gd["release_eligible"] is False and gd["calibration"] is None
