"""TDD gates for ``Viz2Runtime`` — the serialized viz2 session actor (viz2 PRD Phase B2, plan v4
§2b.3 transport+liveness, §2b.4 patch manifests, §2b.2 backend gate).

Every gate runs over the REAL committed LRO NAC Shape-from-Shading Haworth 1 m bundle
(``haworth_sfs_2km_1m``) and a REAL localhost TCP socket — no synthetic terrain, no fake sockets,
no faked timing (the deadman is proven by real wall-clock silence). The runtime is the sole mutator;
the socket client only enqueues twists and reads telemetry.

Gates:
  1. connect with token -> drive a twist -> telemetry shows slip>0 on a slope, mass conserved;
  2. deadman without traffic: connect, one twist, then SILENCE -> within ack_deadline_s the runtime
     zeroes the twist (proves the tick driver runs independent of inbound reads);
  3. auth: a tokenless connect is refused before any command; a role:"drive" frame WITHOUT the token
     is refused; the token file is mode 0600 (stat asserted); a stale-epoch frame is dropped after a
     reconnect;
  4. patch manifest: a step writes a generation manifest carrying ALL changed fields + a digest; two
     DISJOINT steps with the intermediate manifest skipped -> applying only the newest covers BOTH
     regions (union coverage); a keyframe is emitted on recenter/connect;
  5. backend: requesting ``tier3_chrono@0.0`` for mutation raises ``PhysicsModelRefused``; a static
     assert the module never calls ``select_backend``.
"""
from __future__ import annotations

import json
import os
import socket
import stat
import time

import numpy as np
import pytest

from stewie.contracts.physics_model_control import PhysicsModelRefused
from stewie.runtime import viz2_runtime as V2
from stewie.runtime.viz2_runtime import Viz2Runtime, apply_manifest

_SAMPLES = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "samples", "lunar_dem")
SFS = os.path.join(_SAMPLES, "haworth_sfs_2km_1m")

pytestmark = pytest.mark.skipif(not os.path.isdir(SFS), reason="committed SfS Haworth bundle absent")


# --------------------------------------------------------------------------------------------
# a real loopback-TCP client: token handshake, JSON-line frames, cumulative acks
# --------------------------------------------------------------------------------------------

class Client:
    """A minimal real-socket client — connects to 127.0.0.1:port, presents the token, then sends
    twist/ack frames and reads newline-delimited JSON telemetry. No mocking: real bytes on a real
    localhost socket."""

    def __init__(self, port: int):
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=5.0)
        self.sock.settimeout(2.0)
        self._buf = b""
        self.reply: dict | None = None

    def handshake(self, token: str | None, *, role: str | None = "drive") -> dict:
        frame: dict = {}
        if token is not None:
            frame["token"] = token
        if role is not None:
            frame["role"] = role                 # server MUST ignore this
        self._send(frame)
        self.reply = self._recv_one()
        return self.reply

    def twist(self, v: float, omega: float) -> None:
        self._send({"cmd": "twist", "v": v, "omega": omega})

    def ack(self, seq: int) -> None:
        self._send({"cmd": "ack", "seq": seq})

    def _send(self, obj: dict) -> None:
        self.sock.sendall((json.dumps(obj) + "\n").encode())

    def _recv_one(self, timeout: float = 2.0):
        self.sock.settimeout(timeout)
        while b"\n" not in self._buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                return None
            self._buf += chunk
        line, self._buf = self._buf.split(b"\n", 1)
        return json.loads(line.decode())

    def drain(self, *, seconds: float, ack: bool = True) -> list[dict]:
        """Read every frame available over ``seconds`` (acking cumulatively when asked)."""
        frames: list[dict] = []
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            try:
                self.sock.settimeout(0.1)
                chunk = self.sock.recv(4096)
                if not chunk:
                    break
                self._buf += chunk
            except socket.timeout:
                continue
            while b"\n" in self._buf:
                line, self._buf = self._buf.split(b"\n", 1)
                if not line.strip():
                    continue
                f = json.loads(line.decode())
                frames.append(f)
                if ack and "seq" in f:
                    self.ack(int(f["seq"]))
        return frames

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


# --------------------------------------------------------------------------------------------
# helpers over the real DEM
# --------------------------------------------------------------------------------------------

def _tile_center_xy(rt: Viz2Runtime, base_r: int, base_c: int) -> tuple[float, float]:
    ws = rt.ws
    tbc = ws.tile_base_cells
    br = (base_r // tbc) * tbc + tbc // 2
    bc = (base_c // tbc) * tbc + tbc // 2
    return (ws.world_x0 + bc * ws.base_cell_m, ws.world_y0 + br * ws.base_cell_m)


def _sloped_start_xy() -> tuple[float, float]:
    """A genuinely sloped interior cell on the real SfS Haworth DEM (argmax interior slope) — where a
    driven wheel develops real slip. Global metres, from the bundle's own world_bounds."""
    from stewie.physics.worksite import coarse_base_from_bundle
    base, meta = coarse_base_from_bundle(SFS)
    h = base.derive_height()
    gy, gx = np.gradient(h, base.cell_m)
    slope = np.hypot(gx, gy)
    slope[:400, :] = 0.0; slope[-400:, :] = 0.0
    slope[:, :400] = 0.0; slope[:, -400:] = 0.0
    br, bc = (int(v) for v in np.unravel_index(int(np.argmax(slope)), slope.shape))
    wb = meta["world_bounds_m"]
    return (float(wb["x0"]) + bc * base.cell_m, float(wb["y0"]) + br * base.cell_m)


def _runtime(session_dir, **kw) -> Viz2Runtime:
    kw.setdefault("fine_cell_m", 0.05)
    kw.setdefault("tile_base_cells", 4)
    return Viz2Runtime(SFS, session_dir=str(session_dir), **kw)


# --------------------------------------------------------------------------------------------
# gate 1: connect with token -> drive a twist -> slip>0 on a slope, mass conserved
# --------------------------------------------------------------------------------------------

def test_connect_drive_twist_shows_slip_on_slope_mass_conserved(tmp_path):
    rt = _runtime(tmp_path, start_xy=_sloped_start_xy(), start_yaw=np.pi / 4.0)
    with rt:
        assert rt.wait_ready(10.0)
        c = Client(rt.port)
        reply = c.handshake(rt.token)
        assert reply["ok"] is True and reply["role"] == "drive"
        c.twist(0.3, 0.0)                              # drive uphill on the sloped cell
        frames = c.drain(seconds=1.5)
        c.close()
    # a telemetry frame reported real slip on the slope
    slips = [f["payload"]["telem"]["slip"] for f in frames
             if f.get("payload", {}).get("type") == "telemetry"]
    assert slips, "no telemetry frames received"
    assert max(slips) > 0.0, f"expected slip>0 on the slope, got max {max(slips) if slips else None}"
    # mass conserved across the whole driven run (residual reported by the actor and read after stop)
    assert rt.conservation_residual_frac() < 1e-6


# --------------------------------------------------------------------------------------------
# gate 2: deadman without traffic -> the runtime zeroes the twist within ack_deadline_s
# --------------------------------------------------------------------------------------------

def test_deadman_trips_on_silence_and_zeroes_twist(tmp_path):
    rt = _runtime(tmp_path, start_xy=_tile_center_xy_from_bundle(),
                  start_yaw=0.0, ack_deadline_s=0.4)
    with rt:
        assert rt.wait_ready(10.0)
        c = Client(rt.port)
        c.handshake(rt.token)
        c.twist(0.25, 0.0)                            # one command, then go silent (never ack)
        time.sleep(0.15)
        assert rt._latest_twist != (0.0, 0.0)         # the twist is live before the deadman
        # SILENCE: read nothing, ack nothing. The tick driver must still trip the deadman.
        deadline = time.monotonic() + 2.0
        while not rt._safe_stopped and time.monotonic() < deadline:
            time.sleep(0.02)
        assert rt._safe_stopped, "deadman did not trip on silence"
        assert rt._latest_twist == (0.0, 0.0)         # safe-stop zeroed the held twist
        assert rt._current_session is None            # tripped session was closed (terminal)
        c.close()


def test_deadman_rearm_via_fresh_session(tmp_path):
    """Round-3 rearm contract: the tripped StreamSession is terminal; recovery is a NEW authenticated
    session (fresh keyframe), not a reset. After rearm the rover drives again."""
    rt = _runtime(tmp_path, start_xy=_tile_center_xy_from_bundle(),
                  start_yaw=0.0, ack_deadline_s=0.4)
    with rt:
        assert rt.wait_ready(10.0)
        c1 = Client(rt.port)
        c1.handshake(rt.token)
        c1.twist(0.25, 0.0)
        deadline = time.monotonic() + 2.0
        while not rt._safe_stopped and time.monotonic() < deadline:
            time.sleep(0.02)
        assert rt._safe_stopped and rt._current_session is None
        c1.close()
        # rearm: a fresh authenticated session clears the safe-stop and re-arms with a keyframe
        c2 = Client(rt.port)
        reply = c2.handshake(rt.token)
        assert reply["ok"] is True
        assert rt._safe_stopped is False              # fresh session re-armed
        c2.twist(0.2, 0.0)
        frames = c2.drain(seconds=0.8)
        kinds = [f.get("payload", {}).get("type") for f in frames]
        assert "telemetry" in kinds                   # drive resumed after rearm
        c2.close()


# --------------------------------------------------------------------------------------------
# gate 3: auth — tokenless refused, role-without-token refused, 0600 file, stale-epoch dropped
# --------------------------------------------------------------------------------------------

def test_tokenless_connect_is_refused_before_any_command(tmp_path):
    rt = _runtime(tmp_path, start_xy=_tile_center_xy_from_bundle())
    with rt:
        assert rt.wait_ready(10.0)
        c = Client(rt.port)
        reply = c.handshake(None)                     # no token at all
        assert reply is None or reply.get("ok") is False
        assert rt._current_session is None            # nothing was authorized
        c.close()


def test_role_frame_without_token_is_refused(tmp_path):
    rt = _runtime(tmp_path, start_xy=_tile_center_xy_from_bundle())
    with rt:
        assert rt.wait_ready(10.0)
        c = Client(rt.port)
        reply = c.handshake(None, role="drive")       # role but NO token
        assert reply is None or reply.get("ok") is False
        assert rt._current_session is None
        c.close()


def test_wrong_token_is_refused(tmp_path):
    rt = _runtime(tmp_path, start_xy=_tile_center_xy_from_bundle())
    with rt:
        assert rt.wait_ready(10.0)
        c = Client(rt.port)
        reply = c.handshake("not-the-real-token", role="drive")
        assert reply is None or reply.get("ok") is False
        assert rt._current_session is None
        c.close()


def test_token_file_is_mode_0600(tmp_path):
    rt = _runtime(tmp_path, start_xy=_tile_center_xy_from_bundle())
    with rt:
        assert rt.wait_ready(10.0)
        st = os.stat(rt.token_path)
        assert stat.S_IMODE(st.st_mode) == 0o600, oct(stat.S_IMODE(st.st_mode))
        payload = json.loads(open(rt.token_path).read())
        assert payload["port"] == rt.port and payload["token"] == rt.token


def test_server_assigns_role_ignoring_client_supplied_role(tmp_path):
    rt = _runtime(tmp_path, start_xy=_tile_center_xy_from_bundle())
    with rt:
        assert rt.wait_ready(10.0)
        c = Client(rt.port)
        reply = c.handshake(rt.token, role="director")   # client asks for a bogus elevated role
        assert reply["ok"] is True and reply["role"] == "drive"  # server assigns drive regardless
        c.close()


def test_stale_epoch_frame_is_dropped_after_reconnect(tmp_path):
    rt = _runtime(tmp_path, start_xy=_tile_center_xy_from_bundle(), start_yaw=0.0)
    with rt:
        assert rt.wait_ready(10.0)
        c1 = Client(rt.port)
        r1 = c1.handshake(rt.token)
        epoch1 = r1["epoch"]
        c2 = Client(rt.port)                          # a newer session supersedes epoch1
        r2 = c2.handshake(rt.token)
        epoch2 = r2["epoch"]
        assert epoch2 > epoch1
        assert rt._current_epoch == epoch2
        # a twist on the SUPERSEDED connection must be fenced (dropped), never applied
        c1.twist(0.3, 0.0)
        time.sleep(0.4)
        assert rt._latest_twist == (0.0, 0.0)         # the stale-epoch command changed nothing
        assert rt._rejected_stale > 0                 # and it was really seen-and-dropped
        c1.close()
        c2.close()


# --------------------------------------------------------------------------------------------
# gate 4: patch manifest — all changed fields + digest; union coverage; keyframe on connect/recenter
# --------------------------------------------------------------------------------------------

def _read_manifest(path):
    return json.loads(open(path).read())


def test_generation_manifest_has_all_changed_fields_and_digests(tmp_path):
    rt = _runtime(tmp_path, start_xy=_tile_center_xy_from_bundle(), start_yaw=0.0,
                  keyframe_interval=10_000)
    with rt:
        assert rt.wait_ready(10.0)
        c = Client(rt.port)
        c.handshake(rt.token)
        c.twist(0.3, 0.0)
        c.drain(seconds=0.8)
        c.close()
    m = _read_manifest(rt.latest_manifest_path())
    for field in ("height", "density", "state_label", "disturbance"):
        assert field in m["fields"], field
        fm = m["fields"][field]
        assert "file" in fm and "shape" in fm and "digest" in fm
        # the digest is real: it verifies against the crop bytes on disk
        raw = open(os.path.join(os.path.dirname(rt.latest_manifest_path()), fm["file"]), "rb").read()
        import hashlib
        assert hashlib.sha256(raw).hexdigest() == fm["digest"]
    assert m["bbox_rc"] and len(m["bbox_rc"]) == 4


def test_keyframe_emitted_on_connect(tmp_path):
    rt = _runtime(tmp_path, start_xy=_tile_center_xy_from_bundle(), start_yaw=0.0,
                  keyframe_interval=10_000)
    with rt:
        assert rt.wait_ready(10.0)
        c = Client(rt.port)
        c.handshake(rt.token)
        c.drain(seconds=0.4)
        c.close()
    kf = _read_manifest(rt.latest_keyframe_manifest_path())
    assert kf["keyframe"] is True
    H, W = rt.window_shape()
    assert kf["bbox_rc"] == [0, 0, H, W]               # a keyframe covers the whole window
    assert "mass_areal" in kf["fields"]                # full resync set


def test_union_coverage_skipping_intermediate_manifest(tmp_path):
    """NB-1 union coverage: drive two DISJOINT footprints; a client that applies ONLY the newest
    manifest (skipping every intermediate) still reproduces the authority at BOTH regions, because
    each manifest covers the dirty UNION since the consumer's last ACK."""
    rt = _runtime(tmp_path, start_xy=_tile_center_xy_from_bundle(), start_yaw=0.0,
                  keyframe_interval=10_000)          # only the connect keyframe exists
    with rt:
        assert rt.wait_ready(10.0)
        c = Client(rt.port)
        c.handshake(rt.token)
        c.twist(0.3, 0.0)
        frames = c.drain(seconds=2.0, ack=False)      # deliberately NEVER ack -> union keeps growing
        c.close()
    tele = [f["payload"] for f in frames if f.get("payload", {}).get("type") == "telemetry"]
    assert len(tele) >= 5
    # the drive produced two DISJOINT step footprints (early vs late) — the NB-1 premise
    first_bb = tele[1]["dirty"][0]
    last_bb = tele[-1]["dirty"][0]
    r0, c0, r1, c1 = first_bb
    R0, C0, R1, C1 = last_bb
    disjoint = (r1 <= R0 or R1 <= r0 or c1 <= C0 or C1 <= c0)
    assert disjoint, f"footprints not disjoint: {first_bb} vs {last_bb}"
    assert not any(t["telem"]["recentered"] for t in tele)   # single window (no keyframe reset)

    # a client that applies ONLY keyframe + the newest delta (skipping all intermediates)
    H, W = rt.window_shape()
    dst = {"height": np.zeros((H, W), "<f4"), "density": np.zeros((H, W), "<f4"),
           "state_label": np.zeros((H, W), "u1"), "disturbance": np.zeros((H, W), "<f4"),
           "mass_areal": np.zeros((H, W), "<f4")}
    apply_manifest(dst, rt.latest_keyframe_manifest_path())
    newest = _read_manifest(rt.latest_manifest_path())
    assert newest["keyframe"] is False
    apply_manifest(dst, rt.latest_manifest_path())

    auth = rt.window_fields()
    # the newest delta's union covered everything changed since the keyframe -> full-window equality
    assert np.array_equal(dst["state_label"], auth["state_label"])
    assert np.allclose(dst["height"], auth["height"], atol=1e-4)
    assert np.allclose(dst["density"], auth["density"], atol=1e-3)
    assert np.allclose(dst["disturbance"], auth["disturbance"], atol=1e-6)


def test_keyframe_emitted_on_recenter(tmp_path):
    """Driving far enough to slide the streaming window forces a full-window keyframe (window origin
    moved) — carried from v2, the union-reset the client resyncs from."""
    rt = _runtime(tmp_path, start_xy=_tile_center_xy_from_bundle(), start_yaw=0.0,
                  keyframe_interval=10_000)
    with rt:
        assert rt.wait_ready(10.0)
        c = Client(rt.port)
        c.handshake(rt.token)
        c.twist(0.3, 0.0)
        frames = c.drain(seconds=6.0)                 # >4 m -> crosses a base tile -> recenter
        c.close()
    tele = [f["payload"] for f in frames if f.get("payload", {}).get("type") == "telemetry"]
    recentered = [t for t in tele if t["telem"]["recentered"]]
    assert recentered, "the drive never recentered"
    # the recenter generation was emitted as a keyframe
    assert any(t["keyframe"] for t in recentered), "recenter did not force a keyframe"


# --------------------------------------------------------------------------------------------
# gate 5: backend governance (R-M3) — chrono refused; the module never calls select_backend
# --------------------------------------------------------------------------------------------

def test_requesting_chrono_backend_for_mutation_is_refused(tmp_path):
    with pytest.raises(PhysicsModelRefused):
        Viz2Runtime(SFS, session_dir=str(tmp_path), model_id="tier3_chrono@0.0",
                    start_xy=_tile_center_xy_from_bundle())


def test_default_backend_resolves_conserved(tmp_path):
    rt = _runtime(tmp_path, start_xy=_tile_center_xy_from_bundle())
    with rt:
        assert rt.backend.info().authority_class == "conserved"
        assert rt.backend.conserves_mass() is True


def test_module_never_calls_select_backend():
    """Static assert (R-M3): the mutation-authority path resolves ONLY through resolve_live_backend;
    select_backend (strict only in LIVE) must never appear in the module source."""
    src = open(V2.__file__).read()
    assert "select_backend" not in src, "viz2_runtime must never reference select_backend (R-M3)"


# --------------------------------------------------------------------------------------------
# module-scope helper: a tile-center start on the real bundle (used by many gates)
# --------------------------------------------------------------------------------------------

_CENTER_XY: tuple[float, float] | None = None


def _tile_center_xy_from_bundle() -> tuple[float, float]:
    """A deep-interior base-tile-center start on the real SfS bundle (no boundary clamp, room to
    drive before a recenter)."""
    global _CENTER_XY
    if _CENTER_XY is None:
        from stewie.physics.worksite import coarse_base_from_bundle
        _base, meta = coarse_base_from_bundle(SFS)
        wb = meta["world_bounds_m"]
        cell = meta["grid"]["cell_m"]
        # base cell (1002,1002) is the centre of tile (250,250) at tile_base_cells=4
        _CENTER_XY = (float(wb["x0"]) + 1002 * cell, float(wb["y0"]) + 1002 * cell)
    return _CENTER_XY
