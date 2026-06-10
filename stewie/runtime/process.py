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

    # ---- world operations (the seam's verbs) ---------------------------------------------
    def _pose(self) -> dict:
        sha = hashlib.sha256(self.cs.mass_areal.tobytes()).hexdigest()[:16]
        return {"ok": True, "rc": [float(self.rc[0]), float(self.rc[1])],
                "yaw": float(self.yaw), "mass_sha": sha}

    def _twist(self, v: float, omega: float, steps: int) -> dict:
        ctx = self.twin.drive_context()
        telem: dict = {}
        for _ in range(max(1, int(steps))):
            self.rc, self.yaw, telem = drive.drive_step(
                self.cs, self.rc, self.yaw, float(v), float(omega), dt=self.dt, **ctx)
        out = self._pose()
        out["slip"] = float(telem.get("slip", 0.0))
        return out

    def _packet(self) -> dict:
        self.sequence += 1
        pkt = {"schema_version": "dustgym_runtime/1.0",
               "clock": "sim_monotonic",
               "sequence_id": self.sequence,
               "channels": {"camera": {"status": "UNAVAILABLE"},
                            "imu": {"status": "UNAVAILABLE"},
                            "wheel": {"status": "UNAVAILABLE"},
                            "joints": {"status": "UNAVAILABLE"},
                            "power": {"status": "UNAVAILABLE"}}}
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
