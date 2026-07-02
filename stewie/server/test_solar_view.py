"""PO-12 — the integrated Solar work area, driven by ONE solar authority.

The Solar view composes five previously-scattered elements into a single payload: the sun vector
(ephemeris), the illumination/shadow layers, the active cameras + LEDs, the arm posture, and the
shadow evidence localization ACCEPTED vs REJECTED. `stewie.specs.solar_view.solar_view` is that one
authority; `GET /solar` serves it. Every element traces to a REAL source (solar ephemeris authority,
the gis "sun" raster group, the Godot camera rig + FK, the posture authority, and the SN-02 shadow
accept/reject gate) -- nothing here is fabricated.

These tests assert each element is present AND labeled, and that the accept/reject gate is real: a
crisp solar shadow is accepted, and turning the LEDs on flips the SAME shadow to rejected (illuminator-
cast), which is the "evidence accepted/rejected by localization" element the row requires.

[REQ:PO-12]
"""
from __future__ import annotations

import importlib

import numpy as np
import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.delenv("STEWIE_API_KEY", raising=False)
    monkeypatch.setenv("STEWIE_DEV_OPEN", "1")            # loopback in-process -> operator routes open
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    import stewie.server.server as srv
    importlib.reload(srv)
    yield TestClient(srv.app)
    monkeypatch.undo()
    importlib.reload(srv)


# ---- the authority (the single source the pane reads) ------------------------------------------

def test_authority_carries_all_five_labeled_solar_elements():
    from stewie.specs.solar_view import solar_view
    v = solar_view(mission_t_s=100000.0, posture_name="TRANSIT")
    # (1) sun vector -- az/el + the anti-solar azimuth the shadow loop keys on, with the convention named
    sv = v["sun_vector"]
    assert 0.0 <= sv["sun_az_deg"] < 360.0 and -90.0 <= sv["sun_el_deg"] <= 90.0
    assert abs(((sv["sun_az_deg"] + 180.0) % 360.0) - sv["anti_solar_az_deg"]) < 1e-6
    assert sv["azimuth_convention"] == "from_north_eastward"
    # (2) illumination / shadow layers -- the real gis "sun" group (illumination / incidence / psr)
    keys = {l["key"] for l in v["illumination_layers"]}
    assert {"illumination", "incidence", "psr"} <= keys
    for l in v["illumination_layers"]:
        assert l["name"] and l["raster_route"].startswith("/layers/raster/")
    # (3) active cameras -- the 8 LAC cameras, each labeled with an FK-computed world height
    cams = v["cameras"]
    assert len(cams) == 8
    assert {"front_left", "rear_right", "drum_front_cam"} <= {c["name"] for c in cams}
    for c in cams:
        assert "world_height_m" in c and "active" in c
    # (3b) LEDs -- the illuminator state (decides whether a shadow is solar)
    assert "on" in v["leds"] and v["leds"]["note"]
    # (4) arm posture -- the reconfigurable-morphology authority, labeled + provenanced
    ap = v["arm_posture"]
    assert ap["name"] == "TRANSIT" and ap["stability"] and ap["provenance"]
    assert "chassis_lift_m" in ap
    # (5) shadow evidence -- present as an element even when idle (no mask), with a reason
    assert "shadow_evidence" in v and v["shadow_evidence"]["reason"]
    assert v["authority"].startswith("stewie.specs.solar_view")


def test_sn02_gate_accepts_a_solar_shadow_and_rejects_it_when_leds_are_on():
    # the "accepted vs rejected by localization" element is the REAL SN-02 gate, not a label: a crisp
    # cast shadow is accepted as yaw evidence; turning the LEDs on makes the SAME shadow illuminator-
    # cast, so localization REJECTS it. This is a real behaviour, computed, not asserted-by-fiat.
    from stewie.specs.solar_view import solar_view
    mask = np.zeros((20, 20), dtype=bool)
    mask[5:15, 8] = True
    mask[5:15, 9] = True                                   # a crisp two-cell-wide cast shadow
    accepted = solar_view(cast_shadow_mask=mask, leds_on=False)["shadow_evidence"]
    rejected = solar_view(cast_shadow_mask=mask, leds_on=True)["shadow_evidence"]
    assert accepted["has_evidence"] is True and accepted["accepted"] is True
    assert rejected["has_evidence"] is True and rejected["accepted"] is False
    assert "illuminator" in rejected["reason"].lower()    # the real SN-02 rejection reason


def test_leds_state_drives_both_the_led_element_and_the_gate():
    from stewie.specs.solar_view import solar_view
    v_on = solar_view(leds_on=True)
    assert v_on["leds"]["on"] is True
    assert "illuminator" in v_on["leds"]["note"].lower()


# ---- the served route (the pane's single fetch) ------------------------------------------------

def test_solar_route_serves_the_authority_payload(client):
    r = client.get("/solar?mission_t_s=100000&posture=TRANSIT")
    assert r.status_code == 200, r.text
    j = r.json()
    assert j.get("ok") is True
    sol = j["solar"]
    # every labeled element the pane renders is present on the served payload
    for key in ("sun_vector", "illumination_layers", "cameras", "leds", "arm_posture",
                "shadow_evidence"):
        assert key in sol, f"served /solar payload missing the {key} element"
    assert len(sol["cameras"]) == 8
    assert {l["key"] for l in sol["illumination_layers"]} >= {"illumination", "incidence", "psr"}


def test_solar_route_follows_the_chosen_site(client):
    # #301-style: a 'site' param resolves the sun geometry to THAT site's lat/lon (not hardcoded Haworth)
    from stewie.specs.sites import site_latlon
    slat, _ = site_latlon("shackleton_rim")
    r = client.get("/solar?site=shackleton_rim")
    assert r.status_code == 200, r.text
    assert abs(r.json()["solar"]["sun_vector"]["site_lat_deg"] - slat) < 1e-6


def test_solar_route_rejects_an_unknown_posture_cleanly(client):
    r = client.get("/solar?posture=NOT_A_POSTURE")
    assert r.status_code == 400
    assert "posture" in r.json()["error"].lower()
