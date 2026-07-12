"""[REQ:] viz2 stream protocol — session-config + per-frame input parse (the browser<->server contract).

Gate on exit code: pytest stewie/stream/test_protocol.py

The SAME contract the future three.js setup screen must send. Config resolves mode/site/fine/sun;
input clamps normalized twist intent to [-1,1], drops non-finite values, and only emits keys that are
actually present (so a lone dig frame never zeroes a held twist). No I/O.
"""
from __future__ import annotations

import math

import pytest

from stewie.stream import protocol


# ── parse_config ──────────────────────────────────────────────────────────────────────────
def test_config_defaults_to_real_haworth():
    cfg = protocol.parse_config("{}")
    assert cfg["mode"] == "real"
    assert cfg["site"] == protocol.DEFAULT_SITE
    assert cfg["fine_cell_m"] in (0.05, 0.02)
    assert cfg["sun_az"] == protocol.DEFAULT_SUN_AZ
    assert cfg["sun_el"] == protocol.DEFAULT_SUN_EL


def test_config_real_site_and_sun_override():
    cfg = protocol.parse_config(
        {"mode": "real", "site": "shackleton_rim_10km_5m", "sun": {"az": 300, "el": 5}})
    assert cfg["site"] == "shackleton_rim_10km_5m"
    assert cfg["sun_az"] == 300.0 and cfg["sun_el"] == 5.0


def test_config_rejects_site_path_escape():
    for bad in ("../etc", "a/b", "..", ".hidden"):
        with pytest.raises(protocol.ConfigError):
            protocol.parse_config({"mode": "real", "site": bad})


def test_config_procedural_carries_seed_and_params():
    cfg = protocol.parse_config(
        {"mode": "procedural", "world_seed": 7, "params": {"amplitude_m": 3.0}, "fine": 0.02})
    assert cfg["mode"] == "procedural"
    assert cfg["world_seed"] == 7
    assert cfg["params"] == {"amplitude_m": 3.0}
    assert cfg["fine_cell_m"] == 0.02


def test_config_bad_mode_and_bad_json_raise():
    with pytest.raises(protocol.ConfigError):
        protocol.parse_config({"mode": "wobble"})
    with pytest.raises(protocol.ConfigError):
        protocol.parse_config("{not json")


def test_config_fine_snaps_to_allowed():
    # a stray fine value snaps to the nearest allowed runtime cell size
    assert protocol.parse_config({"fine": 0.049})["fine_cell_m"] == 0.05
    assert protocol.parse_config({"fine": 0.021})["fine_cell_m"] == 0.02


# ── normalize_input ───────────────────────────────────────────────────────────────────────
def test_input_twist_clamped_to_unit_interval():
    cmd = protocol.normalize_input({"v": 5.0, "omega": -9.0})
    assert cmd["v"] == 1.0 and cmd["omega"] == -1.0


def test_input_non_finite_twist_dropped_to_zero():
    cmd = protocol.normalize_input({"v": float("nan"), "omega": float("inf")})
    assert cmd["v"] == 0.0 and cmd["omega"] == 0.0
    assert math.isfinite(cmd["v"]) and math.isfinite(cmd["omega"])


def test_input_lone_dig_does_not_inject_a_twist():
    cmd = protocol.normalize_input({"dig": True})
    assert cmd == {"dig": True}          # no v/omega keys -> Godot keeps its held twist


def test_input_dump_and_sun():
    cmd = protocol.normalize_input({"dump": True, "sun_az": 725.0, "sun_el": 200.0})
    assert cmd["dump"] is True
    assert cmd["sun_az"] == 725.0 % 360.0     # wrapped
    assert cmd["sun_el"] == 90.0              # clamped to the elevation ceiling


def test_input_plan_true_routes_the_waypoints():
    """council #14 planning->render: plan=True is the verb to draw a route through the plotted waypoints."""
    assert protocol.normalize_input({"plan": True}) == {"plan": True}


def test_input_plan_route_dict_passes_valid_world_points():
    """A {route:[[x,z],...]} plan (the mission_planner push) passes with finite world points only."""
    cmd = protocol.normalize_input({"plan": {"route": [[1.5, 2.5], [3.0, 4.0], [5.0, 6.0]]}})
    assert cmd == {"plan": {"route": [[1.5, 2.5], [3.0, 4.0], [5.0, 6.0]]}}
    # a malformed route (non-list, or points < 2 coords) yields no plan key (never crashes Godot)
    assert protocol.normalize_input({"plan": {"route": "nope"}}) == {}
    assert protocol.normalize_input({"plan": {"route": [[1.0]]}}) == {}


def test_input_garbage_returns_empty():
    assert protocol.normalize_input("not json") == {}
    assert protocol.normalize_input(42) == {}
    assert protocol.normalize_input({"nothing": "useful"}) == {}
