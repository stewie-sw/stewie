"""The persistent shared runtime (STEWIE P20 core / G1 blocker #1, slice 1).

One long-lived process owns the conserved world -- a ColumnState built the same way the envs build
theirs -- and serves a Unix-socket JSON-lines seam. Clients attach, declare a ROLE, and operate:

  drive     twist (mutates via the slip-aware drive loop), pose, checkpoint, restore
  produce   pose, packet (the STRICT canonical runtime packet -- accepted by parse_canonical)
  estimate / evaluate   pose only here; their file work stays in stewie.eval.roles

The world OUTLIVES clients (the G1 persistent-runtime criterion): each request is a fresh
connection against the same state. Checkpoint/restore is bit-exact (npz of the conserved fields +
pose + sequence counter). The ROS bridge attaches through this same seam later -- one build, two
tracks. Single-threaded request handling by design: the authority is the serialization point.
"""
from __future__ import annotations

import hashlib
import json
import os
import socketserver

import numpy as np

from stewie.physics import drive
from stewie.physics.column_state import ColumnState
from stewie.specs import vehicle_twin as vtw
from stewie.twin import proprioception as pp

_MUTATING = {"twist", "checkpoint", "restore"}


class RuntimeProcess:
    def __init__(self, *, grid: int = 64, cell_m: float = 0.02, body: str = "moon",
                 vehicle: str = "ipex", socket_path: str, seed: int = 0):
        rng = np.random.default_rng(seed)
        base = 50.0 + rng.normal(0.0, 0.5, (grid, grid))
        self.cs = ColumnState(width=grid, height=grid, cell_m=cell_m,
                              mass_areal=base.astype(np.float64))
        self.twin = vtw.VehicleTwin.assemble("rt_rover", vehicle=vehicle, body=body)
        self.rc: tuple = (grid / 2.0, grid / 2.0)
        self.yaw: float = 0.0
        self.dt: float = 0.1
        self.sequence: int = 0
        self.socket_path = socket_path
        self._server: socketserver.UnixStreamServer | None = None
        # slice 2: the REAL proprioception producer models, driven by the runtime's actual motion;
        # samples buffer between packets and DRAIN on emit (no double-reporting).
        self.t_sim: float = 0.0
        self._imu_model = pp.ImuWheelModel(seed=seed + 1)
        self._imu_buf: list = []
        self._wheel_buf: list = []
        # slice 3 (G1 #3): REAL pack accounting -- drive power from the twin's grounded energy
        # model integrates over commanded motion; the BMS channel reports SoC + instantaneous draw.
        from stewie.specs import ipex_specs as _S
        self.battery_capacity_j: float = float(_S.battery_energy_j())
        self.energy_used_j: float = 0.0
        self._draw_w: float = 0.0

    # ---- world operations (the seam's verbs) ---------------------------------------------
    def _pose(self) -> dict:
        sha = hashlib.sha256(self.cs.mass_areal.tobytes()).hexdigest()[:16]
        return {"ok": True, "rc": [float(self.rc[0]), float(self.rc[1])],
                "yaw": float(self.yaw), "mass_sha": sha}

    def _twist(self, v: float, omega: float, steps: int) -> dict:
        ctx = self.twin.drive_context()
        telem: dict = {}
        for _ in range(max(1, int(steps))):
            yaw0 = self.yaw
            self.rc, self.yaw, telem = drive.drive_step(
                self.cs, self.rc, self.yaw, float(v), float(omega), dt=self.dt, **ctx)
            self.t_sim += self.dt
            # feed the REAL producer models from the achieved motion (slip stays hidden by the
            # encoder model itself; the IMU sees the true yaw rate, not the commanded one)
            true_yaw_rate = (self.yaw - yaw0) / self.dt
            slip = float(telem.get("slip", 0.0))
            self._imu_buf.append(self._imu_model.step_imu(self.t_sim, true_yaw_rate))
            self._wheel_buf.append(self._imu_model.step_wheel_encoders(
                self.t_sim, float(telem.get("v_achieved", v)), float(omega),
                slip4=(slip, slip, slip, slip), dt=self.dt))
            # pack accounting: the twin's grounded drive power while commanding motion
            self._draw_w = float(self.twin.energy["drive_power_w"]) if (v or omega) else 0.0
            self.energy_used_j += self._draw_w * self.dt
        out = self._pose()
        out["slip"] = float(telem.get("slip", 0.0))
        return out

    def _packet(self) -> dict:
        self.sequence += 1
        if self._imu_buf or self._wheel_buf:
            rate = 1.0 / self.dt
            proprio = pp.runtime_proprioception_packet(
                self._imu_buf, self._wheel_buf, sequence_id=self.sequence,
                imu_rate_hz=rate, wheel_rate_hz=rate)
            channels = dict(proprio["channels"])
            self._imu_buf, self._wheel_buf = [], []          # drain on emit
        else:
            channels = {"imu": {"status": "UNAVAILABLE"}, "wheel": {"status": "UNAVAILABLE"},
                        "joints": {"status": "UNAVAILABLE"}, "power": {"status": "UNAVAILABLE"}}
        channels.setdefault("joints", {"status": "UNAVAILABLE"})
        # the BMS always answers (real pack model; ipex 12S/30Ah): SoC from integrated draw,
        # instantaneous power_w = the current draw (0 when idle). Nothing fabricated -- both
        # values come from the twin's grounded energy model and the runtime's own accounting.
        from stewie.twin.runtime_packet import power_channel
        soc = max(0.0, 1.0 - self.energy_used_j / self.battery_capacity_j)
        idle_draw = 0.0 if not (self._imu_buf or self._wheel_buf) and self._draw_w == 0.0 \
            else self._draw_w
        channels["power"] = power_channel(idle_draw, soc, t=self.t_sim)
        self._draw_w = 0.0                                   # draw is per-emission instantaneous
        channels["camera"] = {"status": "UNAVAILABLE"}       # render attach is a later slice
        pkt = {"schema_version": "dustgym_runtime/1.0",
               "clock": "sim_monotonic",
               "sequence_id": self.sequence,
               "channels": channels}
        return {"ok": True, "packet": pkt}

    def _checkpoint(self, path: str) -> dict:
        np.savez(path, mass_areal=self.cs.mass_areal, rc=np.array(self.rc),
                 yaw=np.array([self.yaw]), sequence=np.array([self.sequence]))
        return {"ok": True, "path": path}

    def _restore(self, path: str) -> dict:
        z = np.load(path)
        self.cs.mass_areal[:, :] = z["mass_areal"]
        self.rc = (float(z["rc"][0]), float(z["rc"][1]))
        self.yaw = float(z["yaw"][0])
        self.sequence = int(z["sequence"][0])
        return {"ok": True}

    # ---- request handling -----------------------------------------------------------------
    def handle(self, req: dict) -> dict:
        role, cmd = str(req.get("role", "")), str(req.get("cmd", ""))
        if role not in ("drive", "produce", "estimate", "evaluate"):
            return {"ok": False, "error": f"unknown role {role!r}"}
        if cmd in _MUTATING and role != "drive":
            return {"ok": False, "error": f"role {role!r} may not mutate the world (drive only)"}
        if cmd == "pose":
            return self._pose()
        if cmd == "twist":
            return self._twist(req.get("v", 0.0), req.get("omega", 0.0), req.get("steps", 1))
        if cmd == "packet":
            if role != "produce":
                return {"ok": False, "error": "packets are the producer role's verb"}
            return self._packet()
        if cmd == "checkpoint":
            return self._checkpoint(req["path"])
        if cmd == "restore":
            return self._restore(req["path"])
        return {"ok": False, "error": f"unknown cmd {cmd!r}"}

    # ---- socket plumbing -------------------------------------------------------------------
    def serve_forever(self) -> None:
        outer = self

        class Handler(socketserver.StreamRequestHandler):
            def handle(self) -> None:
                line = self.rfile.readline()
                if not line:
                    return
                try:
                    resp = outer.handle(json.loads(line.decode()))
                except (ValueError, KeyError, OSError) as e:
                    resp = {"ok": False, "error": str(e)}
                self.wfile.write((json.dumps(resp) + "\n").encode())

        if os.path.exists(self.socket_path):
            os.unlink(self.socket_path)
        self._server = socketserver.UnixStreamServer(self.socket_path, Handler)
        self._server.serve_forever(poll_interval=0.05)

    def shutdown(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
