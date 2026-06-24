"""The persistent shared runtime (STEWIE P20 core / G1 blocker #1, slice 1).

One long-lived process owns the conserved world -- a ColumnState built the same way the envs build
theirs -- and serves a Unix-socket JSON-lines seam. Clients attach, declare a ROLE, and operate:

  drive     twist (mutates via the slip-aware drive loop), pose, checkpoint, restore
  produce   pose, packet (the STRICT canonical runtime packet -- accepted by parse_canonical)
  estimate / evaluate   pose only here; their file work stays in stewie.eval.roles

The world OUTLIVES clients (the G1 persistent-runtime criterion): each request is a fresh
connection against the same state. Checkpoint/restore is a COMPLETE, bit-exact, versioned snapshot
(A-01): every mutable field of the world AND of the stateful sensor/RNG models is serialized -- the
conserved ColumnState rasters, the pose/clock (rc/yaw/dt/t_sim/sequence), the pack accounting
(energy + instantaneous draw), the thermal flags, the buffered-but-unemitted proprioception samples,
and the IMU/wheel model's Gauss-Markov biases + PCG64 generator state -- so a restore reproduces not
only the world but the NEXT command and the NEXT packet bit-for-bit. The snapshot is written to a
dot-prefixed temp, flushed + fsync'd, then atomically os.replace'd into place, and a sha256 content
checksum is verified on restore; the restore is transactional -- it builds a fresh validated runtime
and swaps it in only after the whole snapshot loads, so a corrupt or partial file never half-mutates
the live world. The ROS bridge attaches through this same seam later -- one build, two tracks.
Single-threaded request handling by design: the authority is the serialization point.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import math
import os
import socketserver
import tempfile
import threading

import numpy as np

from stewie.physics import drive
from stewie.physics.column_state import ColumnState
from stewie.specs import vehicle_twin as vtw
from stewie.twin import proprioception as pp

# A-01: the checkpoint schema version. Bumped if the serialized field set changes; a restore refuses
# a snapshot whose major version it does not understand rather than silently dropping new state.
CHECKPOINT_SCHEMA = "stewie_runtime_checkpoint/1.0"

_MUTATING = {"twist", "checkpoint", "restore", "set_thermal"}
# M-03/M-04: input bounds on the world-mutating Unix-socket seam. A real request line is < 30 bytes
# and the largest 'steps' used anywhere in the repo/gate is 50, so these caps are ~2000x and ~20000x
# real traffic -- generous for legitimate clients, fatal to the OOM (unbounded readline) and the
# CPU-spin (steps=10**12) bombs. Non-finite v/omega/steps are rejected outright: a NaN twist would
# silently poison the SHARED persistent world pose for every later client.
MAX_LINE_BYTES = 65536          # 64 KiB request-line ceiling (readline is bounded to this)
MAX_TWIST_STEPS = 1_000_000     # at dt=0.1 s this is 1e5 sim-seconds in one request


class RuntimeProcess:
    def __init__(self, *, grid: int = 64, cell_m: float = 0.02, body: str = "moon",
                 vehicle: str = "ipex", socket_path: str, seed: int = 0,
                 frame_store: str | None = None, checkpoint_dir: str | None = None,
                 mission_t0_s: float = 0.0, sun_thermal: bool = False):
        # M-?? / #120: checkpoint/restore confine to this runtime-OWNED directory; a socket client
        # supplies only a bare filename, never an arbitrary path (no traversal / no arbitrary file IO).
        self.checkpoint_dir = checkpoint_dir or os.path.join(
            os.environ.get("STEWIE_DATA_DIR", tempfile.gettempdir()), "stewie_runtime_checkpoints")
        # A-01: keep the construction args so a transactional restore can rebuild a *fresh, validated*
        # runtime with the SAME shape/vehicle/body/config before overlaying the serialized state.
        self.grid = int(grid)
        self.cell_m = float(cell_m)
        self.body = str(body)
        self.vehicle = str(vehicle)
        self.seed = int(seed)
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
        # S-09: an explicit readiness handshake. serve_forever() sets this only AFTER the socket is
        # bound, listening, AND chmod'd 0600 -- so a client that waits on it never hits the
        # bound-but-not-yet-listening ECONNREFUSED window nor a transient group/other-readable mode.
        self._ready = threading.Event()
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
        # final slice: an attached frame store -- a REAL captured pose directory (producer
        # sensors.json + rendered PNGs). When present, packets carry the camera channel.
        self.frame_store = frame_store
        # T3.4: camera thermal state -- the DOCUMENTED floor is 0 C (TVAC qual, SCHULER24
        # pp.28-29; ipex_specs.CAMERA_MIN_OPERATIONAL_C). Settable via the seam now; the
        # sun-driven thermal model (T5.1) will own it later.
        self.camera_temp_c: float = 20.0
        # T5.1 (first slice): the sun OWNS the camera temperature when sun_thermal is on --
        # instantaneous radiative equilibrium between solar input (~ max(sin el, 0)) and the cold
        # sky: T = T_NIGHT + (T_DAY - T_NIGHT) * sin(el)+ . Both endpoints [ASSUMPTION] (camera-
        # housing equilibria; the documented bound is the 0..50 C operational window the GATE uses);
        # no thermal mass/lag yet -- the upgrade slot is a first-order lag behind the same call.
        self.mission_t0_s = float(mission_t0_s)
        self.sun_thermal = bool(sun_thermal)
        self._manual_thermal = False
        if self.sun_thermal:
            self._update_thermal_from_sun()

    # ---- world operations (the seam's verbs) ---------------------------------------------
    THERMAL_T_COLD_C = -60.0    # [ASSUMPTION] unheated housing equilibrium (grazing polar sun:
                                # max el ~1.6 deg at Haworth -> sin(el) <= 0.03 -- passive solar
                                # CANNOT hold the 0..50 C window; building the naive sun-equilibrium
                                # model PROVED that, so the heaters own the window, per the TRL5
                                # TVAC/heater design)
    THERMAL_T_HEATED_C = 10.0   # [ASSUMPTION] heater setpoint inside the documented window
    HEATER_RESERVE_FRAC = 0.10  # [ASSUMPTION] below this SoC the heaters shed (survival power)

    def _update_thermal_from_sun(self) -> None:
        """T5.1 corrected: camera availability at a polar site is HEATER-driven -- the window
        holds while the pack can power the heaters; pack below the shed reserve -> the housing
        falls to the cold equilibrium and the TVAC gate fires."""
        if not self.sun_thermal or self._manual_thermal:
            return
        soc = max(0.0, 1.0 - self.energy_used_j / self.battery_capacity_j)
        self.camera_temp_c = (self.THERMAL_T_HEATED_C if soc > self.HEATER_RESERVE_FRAC
                              else self.THERMAL_T_COLD_C)

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
        self._update_thermal_from_sun()                  # T5.1: time advanced -> sun -> temperature
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
        channels["camera"] = self._camera_channel()
        pkt = {"schema_version": "stewie_runtime/1.0",
               "clock": "sim_monotonic",
               "sequence_id": self.sequence,
               "channels": channels}
        return {"ok": True, "packet": pkt}

    def _camera_channel(self) -> dict:
        from stewie.specs.ipex_specs import CAMERA_MIN_OPERATIONAL_C
        if self.camera_temp_c < CAMERA_MIN_OPERATIONAL_C:
            return {"status": "UNAVAILABLE",
                    "reason": f"thermal: camera {self.camera_temp_c:.1f} C below the "
                              f"{CAMERA_MIN_OPERATIONAL_C:.0f} C TVAC floor"}
        # The camera channel from the attached frame store: REAL rendered frames, runtime clock.
        # The stereo pair shares one keyframe timestamp (the strict parser's per-camera
        # monotonicity allows that); intrinsics/baseline come from the store's own producer
        # sensors.json -- the runtime never invents calibration. (Was a mid-function no-op
        # string -- the docs agent caught it.)
        if self.frame_store is None:
            return {"status": "UNAVAILABLE"}
        import json as _json
        sens = _json.load(open(os.path.join(self.frame_store, "sensors.json")))
        stereo = sens["stereo"]
        cam0 = next(c for c in sens["cameras"] if c["name"] == stereo["left"])
        # Navigation T3.1: the FULL documented rig -- every camera the store's producer file declares,
        # each with ITS OWN intrinsics (per-camera fx/cx/cy from the producer, never assumed).
        frames, intr = [], {}
        for c in sens["cameras"]:
            png = os.path.join(self.frame_store, f"{c['name']}.png")
            if not os.path.exists(png):
                continue                                  # a missing redundant view degrades, not fails
            frames.append({"name": c["name"], "t": float(self.t_sim), "path": png})
            intr[c["name"]] = c["intrinsics"]
        if not any(f["name"] == stereo["left"] for f in frames):
            return {"status": "UNAVAILABLE", "reason": "reference stereo frame missing"}
        return {"status": "OK", "frames": frames,
                "reference_camera": stereo["left"], "baseline_m": float(stereo["baseline_m"]),
                "intrinsics": cam0["intrinsics"], "intrinsics_by_camera": intr}

    def _resolve_checkpoint(self, name: str) -> str:
        """#120: confine a client-supplied checkpoint NAME to the runtime-owned checkpoint dir. A bare
        filename only -- reject absolute paths, path separators, and .. -- so a socket client cannot
        write or read an arbitrary file via checkpoint/restore (was an arbitrary-path traversal).

        A-01: the resolved path is NORMALIZED to carry a single ``.npz`` extension. np.savez appends
        ``.npz`` when the path lacks it, so an extensionless name (``snapshot``) was written to
        ``snapshot.npz`` while the runtime returned/looked up ``snapshot`` -- a checkpoint that
        existed on disk but reported "no checkpoint" on restore. Normalizing here makes save and
        restore agree on ONE on-disk path for any client name, with or without the extension."""
        name = str(name)
        if not name or os.path.isabs(name) or os.sep in name \
                or (os.altsep and os.altsep in name) or name in (".", ".."):
            raise ValueError(f"checkpoint name must be a bare filename, got {name!r}")
        base = os.path.realpath(self.checkpoint_dir)
        os.makedirs(base, exist_ok=True)
        if not name.endswith(".npz"):                        # one canonical extension; save==restore path
            name = name + ".npz"
        full = os.path.realpath(os.path.join(base, name))
        if os.path.commonpath([base, full]) != base:        # defense-in-depth against escape
            raise ValueError("checkpoint name escapes the checkpoint directory")
        return full

    # ---- A-01: complete versioned checkpoint/restore --------------------------------------
    @staticmethod
    def _sample_to_jsonable(s) -> dict:
        """Turn a proprioception sample dataclass into a JSON-safe dict (numpy arrays -> nested
        lists, tuples preserved as lists). The class name rides along so restore reconstructs the
        right dataclass."""
        out: dict = {"__cls__": type(s).__name__}
        for f in dataclasses.fields(s):
            v = getattr(s, f.name)
            if isinstance(v, np.ndarray):
                out[f.name] = {"__ndarray__": v.tolist(), "dtype": str(v.dtype)}
            elif isinstance(v, tuple):
                out[f.name] = {"__tuple__": list(v)}
            else:
                out[f.name] = v
        return out

    @staticmethod
    def _sample_from_jsonable(d: dict):
        """Inverse of _sample_to_jsonable -- rebuild the exact dataclass, restoring numpy arrays with
        their original dtype so the next packet serializes bit-for-bit."""
        cls = getattr(pp, d["__cls__"])
        kwargs: dict = {}
        for k, v in d.items():
            if k == "__cls__":
                continue
            if isinstance(v, dict) and "__ndarray__" in v:
                kwargs[k] = np.array(v["__ndarray__"], dtype=np.dtype(v["dtype"]))
            elif isinstance(v, dict) and "__tuple__" in v:
                kwargs[k] = tuple(v["__tuple__"])
            else:
                kwargs[k] = v
        return cls(**kwargs)

    def _imu_model_state(self) -> dict:
        """The IMU/wheel model's full MUTABLE state: the Gauss-Markov biases, the wheel sample
        counter, and the PCG64 generator state (large ints survive JSON intact). Reconstructing the
        model from `seed` alone is NOT enough -- the biases and the RNG have advanced with every
        emitted sample, so they must be serialized verbatim for bit-exactness."""
        m = self._imu_model
        return {"seed": int(m.seed),
                "gyro_bias": float(m._gyro_bias),
                "accel_bias": np.asarray(m._accel_bias, dtype=float).tolist(),
                "wheel_seq": int(m._wheel_seq),
                "rng_state": m.rng.bit_generator.state}

    @staticmethod
    def _apply_imu_model_state(model, st: dict) -> None:
        model._gyro_bias = float(st["gyro_bias"])
        model._accel_bias = np.asarray(st["accel_bias"], dtype=float)
        model._wheel_seq = int(st["wheel_seq"])
        model.rng.bit_generator.state = st["rng_state"]

    def _serialize_state(self) -> dict:
        """The COMPLETE mutable runtime state as a JSON-safe metadata dict. Large numpy rasters are
        NOT here -- they ride as their own npz arrays (cheaper, no float->str round-trip); this dict
        carries every scalar/flag/buffer/model-state field. Restoring this dict + the rasters
        reproduces the world AND the next command/packet exactly."""
        return {
            "schema": CHECKPOINT_SCHEMA,
            # construction shape/config (a restore rebuilds a fresh validated runtime with these)
            "grid": self.grid, "cell_m": self.cell_m, "body": self.body,
            "vehicle": self.vehicle, "seed": self.seed,
            # pose + clock
            "rc": [float(self.rc[0]), float(self.rc[1])], "yaw": float(self.yaw),
            "dt": float(self.dt), "sequence": int(self.sequence), "t_sim": float(self.t_sim),
            # column-state scalars (the rasters travel as npz arrays)
            "drum_inventory": float(self.cs.drum_inventory),
            "has_ice": self.cs.ice is not None,
            # pack accounting
            "battery_capacity_j": float(self.battery_capacity_j),
            "energy_used_j": float(self.energy_used_j),
            "draw_w": float(self._draw_w),
            # thermal
            "camera_temp_c": float(self.camera_temp_c),
            "mission_t0_s": float(self.mission_t0_s),
            "sun_thermal": bool(self.sun_thermal),
            "manual_thermal": bool(self._manual_thermal),
            # buffered-but-unemitted proprioception samples (drained on the NEXT packet)
            "imu_buf": [self._sample_to_jsonable(s) for s in self._imu_buf],
            "wheel_buf": [self._sample_to_jsonable(s) for s in self._wheel_buf],
            # the stateful sensor model (biases + RNG)
            "imu_model": self._imu_model_state(),
        }

    def _checkpoint(self, name: str) -> dict:
        """Write a COMPLETE, versioned, atomic, checksummed snapshot. Mirrors twin.backup's M-11
        idiom: dot-prefixed temp -> flush+fsync -> os.replace (atomic) so a crash never leaves a
        truncated file at the canonical name, and a sha256 over the logical content lets restore
        detect silent corruption of the (non-hash-chained) arrays/metadata."""
        full = self._resolve_checkpoint(name)
        meta = self._serialize_state()
        meta_bytes = json.dumps(meta, sort_keys=True).encode()
        cs = self.cs
        arrays: dict[str, np.ndarray] = {
            "mass_areal": np.asarray(cs.mass_areal, dtype=np.float64),
            "density": np.asarray(cs.density, dtype=np.float64),
            "state_label": np.asarray(cs.state_label, dtype=np.uint8),
            "disturbance": np.asarray(cs.disturbance, dtype=np.float64),
            "datum": np.asarray(cs.datum, dtype=np.float64),
        }
        if cs.ice is not None:
            arrays["ice"] = np.asarray(cs.ice, dtype=np.float64)
        # the checksum binds the metadata AND every raster so neither can corrupt unnoticed
        h = hashlib.sha256()
        h.update(meta_bytes)
        for k in sorted(arrays):
            h.update(k.encode())
            h.update(np.ascontiguousarray(arrays[k]).tobytes())
        chk = h.hexdigest()
        meta_arr = np.frombuffer(meta_bytes, dtype=np.uint8)
        chk_arr = np.frombuffer(chk.encode(), dtype=np.uint8)
        # Explicit keyword args (the twin.backup M-11 idiom) -- np.savez's positional slots are
        # (file, *args), so the data rasters MUST ride as named keywords; ice is named only when
        # present so an absent volatile field is not invented on disk.
        tmp = os.path.join(os.path.dirname(full), f".{os.path.basename(full)}.tmp")
        try:
            with open(tmp, "wb") as fh:
                if "ice" in arrays:
                    np.savez(fh, meta=meta_arr, checksum=chk_arr,
                             mass_areal=arrays["mass_areal"], density=arrays["density"],
                             state_label=arrays["state_label"], disturbance=arrays["disturbance"],
                             datum=arrays["datum"], ice=arrays["ice"])
                else:
                    np.savez(fh, meta=meta_arr, checksum=chk_arr,
                             mass_areal=arrays["mass_areal"], density=arrays["density"],
                             state_label=arrays["state_label"], disturbance=arrays["disturbance"],
                             datum=arrays["datum"])
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, full)                              # atomic rename within the filesystem
        except BaseException:
            if os.path.exists(tmp):
                os.remove(tmp)                                # leave no .tmp behind on failure
            raise
        return {"ok": True, "path": full}

    def _restore(self, name: str) -> dict:
        """Transactional restore: load + validate the WHOLE snapshot into a fresh RuntimeProcess
        before swapping any field into the live world. A corrupt/partial/incompatible snapshot leaves
        the running world untouched (no half-mutated state)."""
        full = self._resolve_checkpoint(name)
        if not os.path.exists(full):
            return {"ok": False, "error": f"no checkpoint {name!r}"}
        try:
            with np.load(full) as z:
                meta_bytes = bytes(z["meta"].tobytes())
                meta = json.loads(meta_bytes.decode())
                schema = str(meta.get("schema", ""))
                if schema.split("/")[0] != CHECKPOINT_SCHEMA.split("/")[0]:
                    return {"ok": False, "error": f"unknown checkpoint schema {schema!r}"}
                arrays = {k: np.array(z[k]) for k in z.files
                          if k not in ("meta", "checksum")}
                if "checksum" in z.files:
                    want = bytes(z["checksum"].tobytes()).decode()
                    h = hashlib.sha256()
                    h.update(meta_bytes)
                    for k in sorted(arrays):
                        h.update(k.encode())
                        h.update(np.ascontiguousarray(arrays[k]).tobytes())
                    if h.hexdigest() != want:
                        return {"ok": False,
                                "error": "checkpoint integrity check failed: checksum mismatch"}
            # ---- build a FRESH, validated runtime off the snapshot's construction args ----
            fresh = RuntimeProcess(
                grid=int(meta["grid"]), cell_m=float(meta["cell_m"]), body=str(meta["body"]),
                vehicle=str(meta["vehicle"]), socket_path=self.socket_path, seed=int(meta["seed"]),
                frame_store=self.frame_store, checkpoint_dir=self.checkpoint_dir,
                mission_t0_s=float(meta["mission_t0_s"]), sun_thermal=bool(meta["sun_thermal"]))
            # overlay the conserved rasters (ColumnState validates assignment via construction; here
            # we write into the already-validated arrays in place to keep the same dtypes/shapes)
            fresh.cs.mass_areal[:, :] = arrays["mass_areal"]
            fresh.cs.density[:, :] = arrays["density"]
            fresh.cs.state_label[:, :] = arrays["state_label"]
            fresh.cs.disturbance[:, :] = arrays["disturbance"]
            fresh.cs.datum[:, :] = arrays["datum"]
            # a fresh ColumnState defaults ice to None; only overlay it when the snapshot HAD an ice
            # field (matches the dataclass's runtime "ndarray or None" contract without a None assign)
            if meta["has_ice"]:
                fresh.cs.ice = arrays["ice"]
            fresh.cs.drum_inventory = float(meta["drum_inventory"])
            # pose + clock
            fresh.rc = (float(meta["rc"][0]), float(meta["rc"][1]))
            fresh.yaw = float(meta["yaw"]); fresh.dt = float(meta["dt"])
            fresh.sequence = int(meta["sequence"]); fresh.t_sim = float(meta["t_sim"])
            # pack + thermal
            fresh.battery_capacity_j = float(meta["battery_capacity_j"])
            fresh.energy_used_j = float(meta["energy_used_j"])
            fresh._draw_w = float(meta["draw_w"])
            fresh.camera_temp_c = float(meta["camera_temp_c"])
            fresh._manual_thermal = bool(meta["manual_thermal"])
            # buffered samples + the stateful sensor model
            fresh._imu_buf = [self._sample_from_jsonable(d) for d in meta["imu_buf"]]
            fresh._wheel_buf = [self._sample_from_jsonable(d) for d in meta["wheel_buf"]]
            self._apply_imu_model_state(fresh._imu_model, meta["imu_model"])
        except Exception as e:
            # The whole load+validate+rebuild ran on a SEPARATE fresh object -- nothing has touched
            # the LIVE world yet. So ANY failure (a corrupt zip -> BadZipFile, a bad field -> KeyError,
            # a domain violation -> ValueError) is caught here and reported, leaving the running world
            # exactly as it was. Catching broadly is safe because this block has no live side effects;
            # the commit below (after the except) has no remaining failure point.
            return {"ok": False, "error": f"checkpoint restore failed: {e}"}
        # ---- commit: swap the validated fresh state into the live world (no failure point left) ----
        self.cs = fresh.cs
        self.twin = fresh.twin
        self.grid, self.cell_m, self.body, self.vehicle, self.seed = (
            fresh.grid, fresh.cell_m, fresh.body, fresh.vehicle, fresh.seed)
        self.rc, self.yaw, self.dt = fresh.rc, fresh.yaw, fresh.dt
        self.sequence, self.t_sim = fresh.sequence, fresh.t_sim
        self.battery_capacity_j = fresh.battery_capacity_j
        self.energy_used_j, self._draw_w = fresh.energy_used_j, fresh._draw_w
        self.camera_temp_c, self._manual_thermal = fresh.camera_temp_c, fresh._manual_thermal
        self.mission_t0_s, self.sun_thermal = fresh.mission_t0_s, fresh.sun_thermal
        self._imu_model = fresh._imu_model
        self._imu_buf, self._wheel_buf = fresh._imu_buf, fresh._wheel_buf
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
            v, omega, steps = req.get("v", 0.0), req.get("omega", 0.0), req.get("steps", 1)
            # M-04: a mutating command must be finite + bounded. Non-finite v/omega would corrupt the
            # SHARED persistent pose; steps=10**12 would spin the single-threaded authority. (v=0 or a
            # reverse v<0 stay legal -- only non-finite is rejected.)
            if not (isinstance(v, (int, float)) and math.isfinite(v)
                    and isinstance(omega, (int, float)) and math.isfinite(omega)):
                return {"ok": False, "error": "twist v/omega must be finite"}
            try:
                steps = int(steps)
            except (TypeError, ValueError, OverflowError):
                return {"ok": False, "error": "twist steps must be a positive integer"}
            if steps < 1 or steps > MAX_TWIST_STEPS:
                return {"ok": False, "error": f"twist steps must be in 1..{MAX_TWIST_STEPS}"}
            return self._twist(v, omega, steps)
        if cmd == "packet":
            if role != "produce":
                return {"ok": False, "error": "packets are the producer role's verb"}
            return self._packet()
        if cmd == "set_thermal":
            t = float(req["camera_temp_c"])
            if not math.isfinite(t):                     # M-04: a NaN temp defeats the TVAC gate
                return {"ok": False, "error": "camera_temp_c must be finite"}
            self.camera_temp_c = t
            self._manual_thermal = True                  # the inspection override beats the model
            return {"ok": True, "camera_temp_c": self.camera_temp_c}
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
                # M-03: bound the read. readline(MAX+1) returns at most MAX+1 bytes, so an unterminated
                # multi-GB stream is rejected, never buffered to OOM.
                line = self.rfile.readline(MAX_LINE_BYTES + 1)
                if not line:
                    return
                if len(line) > MAX_LINE_BYTES or not line.endswith(b"\n"):
                    self.wfile.write((json.dumps({"ok": False,
                        "error": f"request line exceeds {MAX_LINE_BYTES} bytes or is unterminated"})
                        + "\n").encode())
                    return
                try:
                    resp = outer.handle(json.loads(line.decode()))
                except (ValueError, KeyError, OSError) as e:
                    resp = {"ok": False, "error": str(e)}
                self.wfile.write((json.dumps(resp) + "\n").encode())

        if os.path.exists(self.socket_path):
            os.unlink(self.socket_path)
        # S-09: the FIRST observable mode of the socket must be 0600. UnixStreamServer's constructor
        # binds (creates the filesystem node) AND listens in one call, and bind() honours the process
        # umask -- so a node created under the default umask is briefly group/other-accessible BEFORE
        # any later chmod. Bind under a restrictive umask (0o177) so the node is born 0600; restore the
        # umask immediately after. The post-bind chmod is belt-and-suspenders (e.g. a 0000 umask).
        prev_umask = os.umask(0o177)
        try:
            self._server = socketserver.UnixStreamServer(self.socket_path, Handler)
        finally:
            os.umask(prev_umask)
        os.chmod(self.socket_path, 0o600)                # M-05/S-09: owner-only, before readiness
        # S-09: signal readiness ONLY now -- bound, listening, AND chmod'd. A client that waits on
        # _ready can never hit the bound-but-not-yet-listening ECONNREFUSED window (the constructor
        # above has already run server_activate/listen) nor observe a transient non-0600 mode.
        self._ready.set()
        self._server.serve_forever(poll_interval=0.05)

    def wait_ready(self, timeout: float = 10.0) -> bool:
        """Block until serve_forever() has bound + listened + chmod'd the socket. Returns True once
        the seam is accepting connections (the explicit S-09 readiness handshake)."""
        return self._ready.wait(timeout)

    def shutdown(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        self._ready.clear()                              # S-09: a re-served instance re-handshakes
