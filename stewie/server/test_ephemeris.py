"""FS-06 / §25 Phase 1: the ephemeris authority route returns the typed EphemerisObservation contract
with the azimuth convention EXPLICIT (§25.3 -- shared + tested). This is the first Phase-1 route whose
payload is validated to MATCH the contract spine. Real solar authority (stewie.specs.solar); TestClient.

Run: <venv>/bin/python -m pytest stewie/server/test_ephemeris.py -q
"""
import importlib

import pytest
from fastapi.testclient import TestClient

from stewie.contracts import SPINE_VERSION, EphemerisObservation


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_API_KEY", "test-key")
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    import stewie.server.server as srv
    importlib.reload(srv)
    yield TestClient(srv.app)
    monkeypatch.undo()
    importlib.reload(srv)


def test_ephemeris_payload_matches_the_contract(client):
    r = client.get("/ephemeris?mission_t_s=0&lat_deg=-87.45&lon_deg=0")    # public read, no key
    assert r.status_code == 200, r.text
    obs = EphemerisObservation.model_validate(r.json()["ephemeris"])       # payload matches the spine
    assert 0.0 <= obs.sun_az_deg < 360.0 and -90.0 <= obs.sun_el_deg <= 90.0
    assert obs.schema_version == SPINE_VERSION


def test_azimuth_convention_is_explicit_and_shared(client):
    obs = EphemerisObservation.model_validate(client.get("/ephemeris").json()["ephemeris"])
    assert obs.azimuth_convention == "from_north_eastward"     # §25.3: explicit, shared convention
    assert obs.frame == "MOON_ME" and obs.source == "analytic"


def test_site_param_resolves_the_chosen_sites_lat_lon(client):  # #301 (REG-01)
    """A 'site' param resolves the sun geometry to THAT site's lat/lon (sites.site_latlon, the source #274
    wired into the layer/plan sun routes), not the hardcoded Haworth lat the cockpit's 3D-view sun used to
    send for every site. shackleton_rim (~-89.8) genuinely differs from Haworth (-87.45)."""
    from stewie.specs.sites import site_latlon
    slat, slon = site_latlon("shackleton_rim")
    assert abs(slat - (-87.45)) > 0.1                          # the test site genuinely differs from Haworth
    obs = EphemerisObservation.model_validate(
        client.get("/ephemeris?mission_t_s=0&site=shackleton_rim").json()["ephemeris"])
    assert obs.site_lat_deg == pytest.approx(slat) and obs.site_lon_deg == pytest.approx(slon)
    d = EphemerisObservation.model_validate(client.get("/ephemeris").json()["ephemeris"])
    assert d.site_lat_deg == pytest.approx(-87.45)             # no site -> the default Haworth lat (back-compat)


def test_out_of_domain_latitude_is_rejected_at_the_boundary(client):
    r = client.get("/ephemeris?lat_deg=120")                   # |lat| > 90 -> rejected at the route boundary
    assert r.status_code == 400 and r.json()["ok"] is False    # app maps validation errors to 400 {ok,error}
    assert "lat_deg" in r.json()["error"]
