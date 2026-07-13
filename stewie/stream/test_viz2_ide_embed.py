"""[REQ:RT-06] The viz2 DRIVE-VALIDATE surface embedded in the QWC2 /ide — SIM-scoped command
authority, the SF-01 all-stop latch, and the /ide embed wiring.

Gate on exit code: pytest stewie/stream/test_viz2_ide_embed.py

WHY THIS FILE EXISTS: the Drive 3D panel now ships on the PUBLIC front door
(artemis.stewie.space/ide/ -> menu -> Validate -> Drive 3D, whose iframe is the public
viz2.stewie.space stream). That makes the console's command verbs ({cmd_vel}/{safe}/{rearm}) and the
excavation actuators reachable by an ANONYMOUS browser. Three properties therefore have to hold as
executable REGRESSION GATES, not as prose in a design doc:

  1. SIM-ONLY EGRESS — the stream server MAY lower a twist through the real contract functions
     (``rc_contract`` / ``ros2_bridge.twist_to_command``) to prove shape conformance, but it must
     NEVER construct or import a real-rover egress (the LIVE rclpy node, the executive/release
     command path). A publicly reachable console that could actuate a real rover would violate the
     AG-08 real-instruction gate and the SF-02 bounded-command-authority rule. The actuation target
     is the in-process conserved sim + Godot, and this test pins that.
  2. SF-01 ALL-STOP — a contract {safe} latches and refuses BOTH motion (v/omega/traverse/plan/
     click_px and {cmd_vel}) AND the excavation actuators (dig/dump/drum/arm_front_d/arm_back_d)
     until {rearm}. A Safe that only stopped the wheels while the drum kept spinning is not a Safe.
  3. /ide EMBED WIRING — MissionDrive3D is registered in BOTH places QWC2 requires (appConfig
     pluginsDef + config.json plugins.common) and exposed as the Validate submenu entry, so the
     panel is actually reachable from the menu by a real user (not only via the test harness).

(1) and (2) run against the REAL ``pump_input`` handler. The GPU is isolated -- no Godot is spawned
and the Godot TCP seam is replaced by a capturing fake writer -- so the latch/gate logic under test
stays REAL while the renderer does not. (The full Godot loop is the opt-in e2e, STEWIE_STREAM_E2E=1.)
"""
from __future__ import annotations

import ast
import asyncio
import json
from pathlib import Path

from fastapi.testclient import TestClient

from stewie.stream import app as app_mod

app = app_mod.app
CFG = {"mode": "real", "site": "haworth_sfs_2km_1m"}

REPO = Path(__file__).resolve().parents[2]
QWC2 = REPO / "gis" / "qwc2"
APP_PY = Path(app_mod.__file__)

#: Symbols that would mean the public stream server can actuate a REAL rover. ``twist_to_command`` and
#: ``rc_contract`` are deliberately NOT here: they are pure shape/lowering functions (twist -> a typed
#: command object), and using them is how the sim proves contract conformance without an egress.
REAL_ROVER_EGRESS = (
    "make_live_node",      # ros2_bridge: constructs the LIVE rclpy Node that publishes to a real rover
    "rclpy",               # a live ROS2 client in the stream server would be a real command path
    "executive",           # the execution service is the SOLE real command egress (RT-02) -- not us
    "release_plan",        # director-gated real-mission release
)


class _FakeSeam:
    """Stands in for the Godot TCP seam: captures the frames the server would push to the renderer."""

    def __init__(self) -> None:
        self.frames: list[bytes] = []

    def write(self, b: bytes) -> None:
        self.frames.append(b)

    async def drain(self) -> None:
        return None


def _patch_real_input_no_gpu(monkeypatch) -> _FakeSeam:
    """Spawn NO Godot, but keep the REAL pump_input so the SF-01 latch + cmd_vel gate actually run.
    (test_security.py stubs pump_input out; here it is precisely what is under test.)"""
    seam = _FakeSeam()

    async def _start(self, *, connect_timeout: float = 90.0) -> None:
        self._writer = seam                       # the renderer seam the handler writes commands to

    async def _park(self, *_a, **_k) -> None:
        await asyncio.Event().wait()              # frame pumps park until teardown cancels them

    monkeypatch.setattr(app_mod.StreamSession, "start", _start)
    monkeypatch.setattr(app_mod.StreamSession, "_read_seam", _park)
    monkeypatch.setattr(app_mod.StreamSession, "_send_ws", _park)
    return seam


def _cmds(seam: _FakeSeam) -> list[dict]:
    """Decode the JSON command payloads the server pushed to the renderer seam."""
    out: list[dict] = []
    for f in seam.frames:
        i = f.find(b"{")
        if i < 0:
            continue
        try:
            out.append(json.loads(f[i:].decode("utf-8")))
        except (ValueError, UnicodeDecodeError):
            continue
    return out


# ── 1. SIM-ONLY EGRESS ────────────────────────────────────────────────────────────────────────────
def test_public_stream_server_has_no_real_rover_egress() -> None:
    """[REQ:RT-06] The publicly reachable stream server must not import/construct a real-rover command
    path. Guard the whole module by AST (imports + attribute/name use), not a comment."""
    tree = ast.parse(APP_PY.read_text(encoding="utf-8"))
    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                hits += [f"import {a.name}:{node.lineno}" for s in REAL_ROVER_EGRESS if s in a.name]
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            for a in node.names:
                hits += [f"from {mod} import {a.name}:{node.lineno}"
                         for s in REAL_ROVER_EGRESS if s in mod or s in a.name]
        elif isinstance(node, ast.Attribute):
            hits += [f"attr .{node.attr}:{node.lineno}" for s in REAL_ROVER_EGRESS if s == node.attr]
        elif isinstance(node, ast.Name):
            hits += [f"name {node.id}:{node.lineno}" for s in REAL_ROVER_EGRESS if s == node.id]
    assert hits == [], (
        "viz2's PUBLIC stream server reaches a real-rover egress -- an anonymous browser could actuate "
        f"real hardware (violates AG-08 / SF-02 / RT-02 sole-egress): {hits}")


def test_cmd_vel_lowers_through_the_real_contract_and_drives_only_the_sim(monkeypatch) -> None:
    """[REQ:RT-06] {cmd_vel} is acknowledged with the REAL lowered contract kind (shape proof) and the
    resulting actuation is a normalized twist to the RENDERER SEAM (the sim) -- not a ROS publish."""
    seam = _patch_real_input_no_gpu(monkeypatch)
    with TestClient(app).websocket_connect("/ws") as ws:
        ws.send_json(CFG)
        assert ws.receive_json()["type"] == "ready"
        ws.send_json({"cmd_vel": {"linear_x": 0.29, "angular_z": 0.0}})   # full-speed forward (LIVE_LIN)
        ack = ws.receive_json()
    assert ack["type"] == "cmd_vel_ack"
    assert ack["rc"] not in ("?", "invalid"), (
        f"cmd_vel did not lower through the real ros2_bridge.twist_to_command contract: rc={ack['rc']}")
    assert ack["v"] == 1.0 and ack["omega"] == 0.0        # SI -> normalized, clamped
    drive = [c for c in _cmds(seam) if "v" in c]
    assert drive and drive[-1]["v"] == 1.0, f"the twist did not reach the sim seam: {_cmds(seam)}"


# ── 2. SF-01 ALL-STOP LATCH ───────────────────────────────────────────────────────────────────────
def test_safe_latches_all_stop_then_refuses_motion_until_rearm(monkeypatch) -> None:
    """[REQ:RT-06] {safe} -> an immediate all-stop frame + a latch that refuses {cmd_vel}; {rearm} restores."""
    seam = _patch_real_input_no_gpu(monkeypatch)
    with TestClient(app).websocket_connect("/ws") as ws:
        ws.send_json(CFG)
        assert ws.receive_json()["type"] == "ready"

        ws.send_json({"safe": {}})
        safe = ws.receive_json()
        assert safe["type"] == "safe" and safe["latched"] is True
        stop = _cmds(seam)[-1]
        assert stop["v"] == 0.0 and stop["omega"] == 0.0 and stop["traverse"] is False, \
            f"a contract Safe must push an immediate all-stop to the sim, got {stop}"

        n_before = len(seam.frames)
        ws.send_json({"cmd_vel": {"linear_x": 0.29, "angular_z": 0.0}})   # must be REFUSED while latched
        err = ws.receive_json()
        assert err["type"] == "error" and "SAFE" in err["error"]
        assert len(seam.frames) == n_before, "a SAFE-latched session still forwarded a twist to the sim"

        ws.send_json({"rearm": True})
        assert ws.receive_json()["type"] == "rearmed"
        ws.send_json({"cmd_vel": {"linear_x": 0.29, "angular_z": 0.0}})   # accepted again after rearm
        assert ws.receive_json()["type"] == "cmd_vel_ack"
        assert len(seam.frames) > n_before, "rearm did not restore motion"


def test_safe_latch_also_refuses_the_excavation_actuators(monkeypatch) -> None:
    """[REQ:RT-06] A Safe that stopped the wheels but let the drum/arms keep actuating is not a Safe.
    Every actuation verb must be refused while latched (the council found dig/dump/drum/arm passing)."""
    seam = _patch_real_input_no_gpu(monkeypatch)
    actuators = [{"dig": True}, {"dump": True}, {"drum": 1.0},
                 {"arm_front_d": 0.2}, {"arm_back_d": -0.2},
                 {"v": 1.0, "omega": 0.0}, {"traverse": True}, {"click_px": [10.0, 10.0]}]
    with TestClient(app).websocket_connect("/ws") as ws:
        ws.send_json(CFG)
        assert ws.receive_json()["type"] == "ready"
        ws.send_json({"safe": {}})
        assert ws.receive_json()["type"] == "safe"

        n_before = len(seam.frames)                       # the all-stop frame is already in
        for cmd in actuators:
            ws.send_json(cmd)
        ws.send_json({"rearm": True})                     # a round-trip: proves the loop drained the above
        assert ws.receive_json()["type"] == "rearmed"

    leaked = _cmds(seam)[n_before:]
    assert leaked == [], f"SAFE-latched session leaked actuation to the sim: {leaked}"


# ── 3. /ide EMBED WIRING ──────────────────────────────────────────────────────────────────────────
def test_missiondrive3d_is_registered_and_reachable_from_the_validate_menu() -> None:
    """[REQ:RT-06] The panel is only reachable by a real user if it is registered in BOTH QWC2 places
    AND exposed as a menu entry. (req_trace scans python only, so this is the gate that keeps the JS
    plugin's delivery honest -- it fails if a rebuild/refactor drops the registration.)"""
    plugin = QWC2 / "js" / "plugins" / "MissionDrive3D.jsx"
    assert plugin.is_file(), "the MissionDrive3D /ide plugin is missing"
    src = plugin.read_text(encoding="utf-8")
    assert "stewie:plan" in src, "the plugin no longer forwards the mission to viz2 via postMessage"
    assert "data-stewie-drive-iframe" in src, "the viz2 stream iframe is gone from the plugin"

    cfg_js = (QWC2 / "js" / "appConfig.js").read_text(encoding="utf-8")
    assert "MissionDrive3DPlugin" in cfg_js, "MissionDrive3D is not in appConfig.js pluginsDef"

    cfg = json.loads((QWC2 / "static" / "config.json").read_text(encoding="utf-8"))
    common = [p.get("name") for p in cfg["plugins"]["common"]]
    assert "MissionDrive3D" in common, "MissionDrive3D is not in config.json plugins.common"

    def _menu_keys(obj) -> list:
        found: list = []
        if isinstance(obj, dict):
            if obj.get("key"):
                found.append(obj["key"])
            for v in obj.values():
                found += _menu_keys(v)
        elif isinstance(obj, list):
            for v in obj:
                found += _menu_keys(v)
        return found

    assert "MissionDrive3D" in _menu_keys(cfg), \
        "MissionDrive3D has no menu entry -- a real user cannot open the Drive 3D panel"
