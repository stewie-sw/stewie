"""[REQ:GW-06] the GIS workbench layer tree (GW-06) binds REAL per-layer FRESHNESS + PROVENANCE, not just
the static LY-01 catalog. The public GET /world/layer-manifest is the key-free projection of the auth-gated
/world descriptor's DT-05 enrichment: for a site it returns the measured ``observed_fraction`` (freshness),
the ``dem_source`` provenance id, a ``provenance_class``, and the typed per-layer manifest. The public /ide/
Mission Layers panel binds THIS (it cannot reach the auth-gated /world), so the freshness/provenance shown on
the map layer tree is the real observed-twin / as-built enrichment, not a fabricated timestamp.

Backend contract for GW-06. The panel binding is verified LIVE via gis/qwc2/proof/drive_gw06_freshness.cjs.
"""
import importlib

import pytest
from fastapi.testclient import TestClient

H = {"X-API-Key": "test-key"}
_TERRAIN_MISSION = {"name": "pad-A", "body": "moon", "charger": [0, 0],
                    "orders": [{"action": "src", "kind": "cut", "x": 5.0, "y": 5.0,
                                "footprint_m2": 36.0, "depth_m": 0.3}]}


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_API_KEY", "test-key")
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("STEWIE_DEV_OPEN", "1")             # resolves to the operator identity for resync
    from stewie.server import objects as OBJ
    importlib.reload(OBJ)
    from stewie.server import state as S
    importlib.reload(S)
    monkeypatch.setattr(S, "_TWIN", None)
    monkeypatch.setattr(S, "_TWINS", {})
    import stewie.server.server as srv
    importlib.reload(srv)
    yield TestClient(srv.app)
    monkeypatch.undo()
    importlib.reload(srv)


def test_layer_manifest_is_public_no_key(client):  # [REQ:GW-06]
    # the public /ide/ has no API key (nginx blanks the identity), so the panel's freshness source MUST
    # be reachable WITHOUT auth -- unlike the auth-gated /world (which 401s for a keyless caller).
    assert client.get("/world?site=haworth").status_code == 401       # rich descriptor is auth-gated
    r = client.get("/world/layer-manifest?site=haworth")              # freshness projection is public
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True


def test_layer_manifest_carries_real_freshness_and_provenance(client):  # [REQ:GW-06]
    d = client.get("/world/layer-manifest?site=haworth").json()
    fr = d["freshness"]
    # FRESHNESS: observed_fraction is present + a real (not-null) float in [0,1]. A bare site with no
    # fresh observation reads 0.0 (a real measured 0, never a fabricated age/timestamp).
    assert "observed_fraction" in fr and fr["observed_fraction"] is not None
    assert isinstance(fr["observed_fraction"], float) and 0.0 <= fr["observed_fraction"] <= 1.0
    assert fr["observed"] is True                                    # the observed twin exists for haworth
    # PROVENANCE: a real dem_sources id + a provenance class keyed on real coverage.
    assert fr["dem_source"] == "haworth_10km_5m" and fr["dem_source"]
    assert fr["provenance_class"] == "prior"                         # 0.0 coverage -> prior (not yet observed)
    for k in ("twin_version", "as_built_version", "mutated"):        # as-built freshness present, not null
        assert k in fr and fr[k] is not None


def test_layer_manifest_per_layer_provenance_and_source(client):  # [REQ:GW-06]
    lm = client.get("/world/layer-manifest?site=haworth").json()["layer_manifest"]
    by = {lyr["layer_id"]: lyr for lyr in lm["layers"]}
    dem = by["dem"]
    # each layer carries its provenance + a real source id; the DEM layer's source IS the dem_sources id.
    assert dem["source"] == "haworth_10km_5m"
    assert dem["provenance"] in ("prior", "observed") and dem["provenance"] is not None
    assert isinstance(dem["display"], bool) and isinstance(dem["planning"], bool)   # typed eligibility


def test_layer_manifest_freshness_reflects_a_real_observation(client):  # [REQ:GW-06]
    # a resync that patches the observed twin lifts the REAL freshness the panel reads -- observed_fraction
    # rises off 0.0 and the provenance flips prior -> observed. No synthetic value is ever injected.
    before = client.get("/world/layer-manifest?site=haworth").json()["freshness"]
    assert before["observed_fraction"] == 0.0 and before["provenance_class"] == "prior"
    r = client.post("/twin/resync", headers=H, json={
        "heights_m": [[1.0, 1.0], [1.0, 1.0]], "origin_rc": [100, 100], "provenance": "gw06", "site": "haworth"})
    assert r.status_code == 200, r.text
    after = client.get("/world/layer-manifest?site=haworth").json()["freshness"]
    assert after["observed_fraction"] > 0.0                          # real fresh coverage now measured
    assert after["provenance_class"] == "observed" and after["twin_version"] >= 1


def test_layer_manifest_and_world_report_the_same_enrichment(client):  # [REQ:GW-06]
    # the public projection must not drift from the auth-gated descriptor -- both read _site_enrichment.
    pub = client.get("/world/layer-manifest?site=haworth").json()["freshness"]
    rich = client.get("/world?site=haworth", headers=H).json()
    assert pub["observed_fraction"] == rich["world"]["observed_fraction"]
    assert pub["dem_source"] == rich["world"]["dem_source"]
    assert pub["mutated"] == rich["enrichment"]["mutated"]


def test_layer_manifest_404s_a_site_without_a_dem_bundle(client):  # [REQ:GW-06]
    r = client.get("/world/layer-manifest?site=de_gerlache_rim")    # a real site id whose bundle is not on disk
    assert r.status_code == 404
