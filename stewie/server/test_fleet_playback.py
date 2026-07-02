"""PO-11: fleet playback renders EVERY rover and its INDEPENDENT telemetry.

The single-rover execDraw animates one timeline with one marker. PO-11 requires: given a multi-vehicle
PlanResult, one animated marker per rover on its OWN route + per-rover telemetry (N rovers -> N tracks +
N telemetry streams). This test locks the two real halves:

  1. the REAL multi-vehicle plan produces the per-rover data the renderer consumes -- a 2-vehicle plan on a
     real multi-pit mission yields vehicles_detail with one entry per rover, EACH carrying its own `track`
     (charger start + its sequenced site visits) and its own telemetry aggregates. No fabricated data --
     lode.plan_and_simulate is the real planner.
  2. the renderer wiring: fleet_playback.js (the pure N-tracks/N-streams model + per-rover track/telemetry
     builder) is served, loaded before cockpit.js, and cockpit.js renders it into the Fleet pane's
     #fleetplayback container from the last plan's vehicles_detail.

The pure N-rovers -> N-tracks/N-streams renderer LOGIC is unit-tested in fleet_playback.test.js (node);
here we prove the data feeding it is real and the frontend is wired. The live ANIMATED canvas playback +
its Playwright visual check are the browser-render tier (not exercised in this python gate).
"""
from __future__ import annotations

import os

from lode import mission_planner as MP

_HERE = os.path.dirname(os.path.abspath(__file__))
_INDEX = os.path.join(_HERE, "index.html")
_COCKPIT = os.path.join(_HERE, "web", "assets", "cockpit.js")
_MODULE = os.path.join(_HERE, "web", "assets", "fleet_playback.js")


def _read(p: str) -> str:
    with open(p, encoding="utf-8") as f:
        return f.read()


def _pairs_mission(sites):
    orders = []
    for i, (x, y) in enumerate(sites):
        orders += [{"action": f"cut{i}", "kind": "cut", "x": x, "y": y, "footprint_m2": 40, "depth_m": 0.05},
                   {"action": f"fill{i}", "kind": "fill", "x": x + 1, "y": y + 1, "footprint_m2": 40,
                    "depth_m": 0.05 * MP.SWELL}]
    return MP.mission_from_dict({"name": "p", "body": "moon", "charger": [0, 0], "orders": orders})


def test_multi_vehicle_plan_gives_per_rover_track_and_telemetry():  # [REQ:PO-11]
    sites = [(40, 0), (-40, 5), (80, 0), (-80, 5), (0, 90), (0, -90)]      # 6 distinct pits
    m = _pairs_mission(sites)
    _, _, pt2, _, T2 = MP.plan_and_simulate(m, vehicles=2)
    detail = T2["vehicles_detail"]
    assert T2["vehicles"] == 2 and len(detail) == 2, "not one detail entry per rover"
    # N tracks: every rover carries its OWN route (charger start + its sequenced sites), real geometry.
    for d in detail:
        assert isinstance(d.get("track"), list) and len(d["track"]) >= 2, \
            f"rover {d['vehicle']} has no per-rover track (route geometry) for playback"
        assert d["track"][0] == [0.0, 0.0], "each rover's track starts at the shared charger"
        assert all(len(p) == 2 for p in d["track"]), "track waypoints are not [x,y]"
    # the tracks are DISTINCT routes (rovers do not share one timeline)
    assert detail[0]["track"] != detail[1]["track"], "the two rovers have identical tracks (not independent)"
    # N telemetry streams: each rover's own aggregates, and they sum to the real total work.
    for d in detail:
        for k in ("time_s", "energy_J", "distance_m", "n_trips"):
            assert k in d, f"rover {d['vehicle']} telemetry missing {k}"
    assert sum(d["n_trips"] for d in detail) == len(pt2), "per-rover trip counts do not cover the plan"


def test_fleet_playback_module_is_served_and_wired():  # [REQ:PO-11]
    html = _read(_INDEX)
    i_mod = html.find("/assets/fleet_playback.js")
    i_cockpit = html.find("/assets/cockpit.js")
    assert i_mod != -1, "fleet_playback.js is not loaded by index.html"
    assert i_mod < i_cockpit, "fleet_playback.js must load before cockpit.js"
    assert 'id="fleetplayback"' in html, "the Fleet pane has no #fleetplayback playback container"
    mod = _read(_MODULE)
    for fn in ("fleetPlaybackModel", "playbackFrame", "fleetPlaybackHTML"):
        assert f"function {fn}" in mod, f"fleet_playback.js is missing {fn}"
    assert "STEWIE_FLEET_PLAYBACK" in mod, "the module does not export its window namespace"
    js = _read(_COCKPIT)
    assert "STEWIE_FLEET_PLAYBACK" in js and "fleetPlaybackHTML" in js, \
        "cockpit.js does not render the fleet playback into the Fleet pane"
    assert '"fleetplayback"' in js or "'fleetplayback'" in js, \
        "cockpit.js never targets the #fleetplayback container"
