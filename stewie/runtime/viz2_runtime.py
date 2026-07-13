"""``Viz2Runtime`` — the serialized viz2 session actor (viz2 PRD Phase B2; plan v4 §2b.3 transport +
liveness, §2b.4 patch manifests, §2b.2 backend gate).

ONE core-owned, serialized, windowed conserved-terrain session. A single physics thread — the SOLE
mutator — runs a FIXED-RATE ACTOR LOOP over an adopted streaming ``WorkSite``:

    drain the command mailbox -> apply the latest twist (commands coalesce to the latest) ->
    ``ws.step()`` -> write the patch generation -> drive ``StreamSession.tick(now=monotonic())``
    every iteration -> on a deadman trip, zero the twist (safe-stop).

Socket I/O lives entirely off that thread: the acceptor + per-connection handler threads only
ENQUEUE commands and DRAIN outbound telemetry; they never touch the world. This is the fix for the
``RuntimeProcess`` trap (a blocked ``readline`` starves everything, so the deadman has no driver,
plan §0.2 / NB-3): here the tick is driven by the actor loop, which no stalled client can starve.

This module REUSES ``stewie.runtime.process.RuntimeProcess``'s seam DISCIPLINES as patterns — it does
NOT subclass it (its request-driven mutation model is the trap): bounded request lines
(``MAX_LINE_BYTES``), M-04 input bounds on mutating commands, the S-09 readiness handshake + 0600
umask discipline (applied to a token FILE instead of a socket node), and the atomic-write commit
marker. NET-NEW here: the actor loop + mailbox, the ``StreamSession`` deadman wiring, the
authenticated loopback-TCP transport, and the generation-namespaced patch-manifest writer.

Security (plan §0.4 / NM-6): the transport is loopback TCP on an EPHEMERAL 127.0.0.1 port. A plain
loopback port carries no owner semantics, so the boundary is a per-session random TOKEN written to a
0600 file (only the same OS user can read it); the first client frame must present the token; the
SERVER assigns the session role (a client-supplied ``role`` is ignored); a wrong/missing token closes
the connection. Each accepted connection mints a monotonic session EPOCH; frames on a superseded
epoch are dropped (stale-client fencing), so a delayed client can never resume authority after a
newer session took over — the single-mutator invariant survives reconnects.

Deadman is TERMINAL (plan §2b.3 round-3): ``StreamSession`` has no rearm API — once ``tick()`` trips,
``send()`` refuses permanently. On a trip the runtime HOLDS the safe-stop (twist stays zero) and
CLOSES the session; recovery is a NEW authenticated connection (fresh ``StreamSession`` +
server-assigned role + forced keyframe), never a reset.

Mutation authority (plan §2b.2 / R-M3): resolved ONLY through
``physics_model_control.resolve_live_backend`` (validated AND frozen AND non-deprecated AND conserved
AND per-body). The non-strict, mode-composing resolver (which is strict only in LIVE and would admit
any registered model otherwise) NEVER appears on this path — the numpy ``WorkSite`` IS the resolved
``tier2_numpy`` authority; the gate confirms the runtime is authorized to mutate with a conserved
backend and fails closed otherwise (``tier3_chrono@0.0`` is refused). The R-M3 static gate asserts
this module's source never even names that non-strict resolver.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import queue
import secrets
import socket
import threading
import time

import numpy as np

from stewie.bridge.stream import PROTOCOL_VERSION, StreamSession
from stewie.contracts import RegolithVolumeEstimate
from stewie.contracts.physics_model_control import LIVE_DEFAULT_MODEL_ID, resolve_live_backend
from stewie.physics.worksite import WorkSite
from stewie.specs.ipex_specs import (
    DRUM_DIMENSIONS_M, LUNAR_G_MS2, dig_energy_per_kg, max_cut_per_pass_m)
from stewie.physics.excavation import earthmoving_report, representative_dig
from stewie.physics.material import cell_strength
from stewie.specs.arm_state import net_dig_reaction_n
from stewie.twin.io_fields import atomic_write_bytes

# Reused DISCIPLINE (not the class): the RuntimeProcess bounded request-line ceiling (M-03). A real
# viz2 command line is < 64 bytes; this cap is ~1000x real traffic, fatal to the unbounded-readline OOM.
MAX_LINE_BYTES = 65536

_RF32 = "<f4"
_R8 = "u1"

# The render/patch field set (plan §2b.4): height, density, state_label, disturbance every drive step;
# mass_areal rides keyframes (the full-resync set) and dig deltas (E1, not exercised in B2).
_DRIVE_FIELDS = ("height", "density", "state_label", "disturbance")


def apply_manifest(dst: dict[str, np.ndarray], manifest_path: str) -> dict:
    """Apply one generation manifest's absolute-value crops into ``dst`` (the viz2 client's role, in
    Python). ``dst`` maps field name -> a full-window array; each field's crop is blitted at the
    manifest ``bbox_rc`` after its sha256 digest is verified against the on-disk bytes. Absolute values
    make this IDEMPOTENT and superset-safe (plan §2b.4). Returns the parsed manifest dict."""
    with open(manifest_path) as fh:
        m = json.load(fh)
    r0, c0, r1, c1 = m["bbox_rc"]
    gdir = os.path.dirname(manifest_path)
    for name, fmeta in m["fields"].items():
        with open(os.path.join(gdir, fmeta["file"]), "rb") as fh:
            raw = fh.read()
        if hashlib.sha256(raw).hexdigest() != fmeta["digest"]:
            raise ValueError(f"manifest {manifest_path}: digest mismatch for field {name!r}")
        crop = np.frombuffer(raw, dtype=np.dtype(fmeta["dtype"])).reshape(fmeta["shape"])
        if name in dst:
            dst[name][r0:r1, c0:c1] = crop
    return m


class Viz2Runtime:
    """A serialized, authenticated, windowed conserved-terrain session actor for viz2 (Phase B2)."""

    def __init__(self, bundle_dir: str, *, session_dir: str,
                 model_id: str = LIVE_DEFAULT_MODEL_ID, body: str = "moon",
                 fine_cell_m: float = 0.05, tile_base_cells: int = 4,
                 start_xy: tuple[float, float] | None = None, start_yaw: float = 0.0,
                 rate_hz: float = 15.0, dt: float = 0.1,
                 ack_deadline_s: float = 2.0, window: int = 64,
                 keyframe_interval: int = 90, retain_generations: int = 256,
                 dig_depth_m: float = 0.02, dig_half_cells: int = 6,
                 drum: str = "large",
                 host: str = "127.0.0.1"):
        # --- backend governance FIRST (R-M3): resolve mutation authority ONLY through the strict LIVE
        # resolver; a refused model raises PhysicsModelRefused before any world/socket is built. The
        # numpy WorkSite IS this resolved tier2_numpy authority — the gate proves we are AUTHORIZED to
        # mutate with a conserved backend, fail-closed. The non-strict resolver is never called here.
        self.model_id = str(model_id)
        self.body = str(body)
        self.backend = resolve_live_backend(self.model_id, body=self.body)

        # --- the conserved session world: a datum-verified streaming WorkSite (Phase B1) ---
        self.ws = WorkSite.from_haworth_bundle(
            bundle_dir, fine_cell_m=fine_cell_m, tile_base_cells=tile_base_cells)
        if start_xy is None:
            start_xy = self._flattest_interior_spawn()
        self.ws.recenter((float(start_xy[0]), float(start_xy[1])))
        self.ws.set_pose((float(start_xy[0]), float(start_xy[1])), yaw=float(start_yaw))
        # expose the resolved spawn + base-grid geometry so the stream server can seed the rock field
        # (and any world-frame overlay) around where the rover actually starts.
        self.start_xy = (float(start_xy[0]), float(start_xy[1]))

        self.dt = float(dt)
        self.rate_hz = float(rate_hz)
        self._period = 1.0 / self.rate_hz
        self.ack_deadline_s = float(ack_deadline_s)
        self.window = int(window)
        self.keyframe_interval = int(keyframe_interval)
        self.retain_generations = int(retain_generations)
        # B3 dig: a conserved excavation the driver can trigger to CARVE the terrain (a real height
        # drop). On this real bundle a straight drive only compacts (density-only, TREAD) — the
        # surface density is already ~1456 kg/m^3, above the light IPEx wheel's Bekker firming target,
        # so derive_height() does not move on a drive. The dig removes areal mass (WorkSite.flatten,
        # mass into the drum ledger), so derive_height() drops and the window mesh's VERTEX shader
        # displaces the trench — the visible carved rut the NB-2 render-geometry contract proves.
        self.dig_depth_m = float(dig_depth_m)
        self.dig_half_cells = int(dig_half_cells)
        # Selected bucket drum (flight-representative "large" by default): its REAL width feeds the FEE
        # excavation-force model (tool width w) and its scoop height sets the <=50% anti-bridging cut cap.
        self.drum = str(drum) if str(drum) in DRUM_DIMENSIONS_M else "large"
        self._drum_width_m = float(DRUM_DIMENSIONS_M[self.drum]["width"])
        self._drum_radius_m = 0.5 * float(DRUM_DIMENSIONS_M[self.drum]["diameter"])
        self._max_cut_per_pass_m = float(max_cut_per_pass_m(self.drum))
        self.host = str(host)

        # --- session directory + generation store ---
        self.session_dir = os.path.abspath(session_dir)
        os.makedirs(self.session_dir, exist_ok=True)
        self.generations_dir = os.path.join(self.session_dir, "generations")
        os.makedirs(self.generations_dir, exist_ok=True)
        self.token_path = os.path.join(self.session_dir, "viz2_session.json")

        # --- rock field: seed the spatial-k Golombek boulders around the spawn ONCE, set them on the
        #     WorkSite so the conserved drive PHYSICALLY rides over / is blocked by them (drive_step D4
        #     clasts), and write the SAME list as clasts.json for the Godot display -- one source, so a
        #     rock the rover SEES is the rock it FEELS.
        self._seed_rockfield(str(bundle_dir))

        # --- authenticated loopback-TCP seam (bound now; token minted; 0600 file) ---
        self.token = secrets.token_hex(32)
        self._listen = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listen.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listen.bind((self.host, 0))
        self._listen.listen(8)
        self._listen.settimeout(0.2)
        self.port = int(self._listen.getsockname()[1])
        self._write_token_file()

        self._init_actor_state()

    def _init_actor_state(self) -> None:
        """[REQ:AS-15] actor/socket mutable state + metric accumulators + generation bookkeeping, split
        out of __init__ to keep the constructor under the Power-of-10 statement budget (no behaviour change)."""
        # --- shared actor/socket state (guarded by _lock) ---
        self._lock = threading.RLock()
        self._inbound: queue.Queue[tuple[int, dict]] = queue.Queue()
        self._current_epoch = 0
        self._epoch_counter = 0
        self._current_session: StreamSession | None = None
        self._current_outbound: queue.Queue[dict] | None = None
        self._latest_twist: tuple[float, float] = (0.0, 0.0)
        self._safe_stopped = False
        self._force_keyframe = False
        self._pending_dig = False
        self._pending_dump = False
        self._rejected_stale = 0
        self._rejected_bounds = 0
        self._dig_count = 0
        self._dump_count = 0
        self._last_applied_twist: tuple[float, float] = (0.0, 0.0)
        # E1: excavation energy — every kg cut costs the grounded IPEx dig figure (Schuler et al 2024,
        # 4151 J/kg via ipex_specs.dig_energy_per_kg). Accumulated on the actor thread as the drum cuts;
        # streamed on telemetry so the HUD energy budget decreases by the real J/kg. Dump is passive
        # (spoil is dropped) — no grounded dump-energy constant exists, so it debits nothing (honest).
        self._dig_energy_per_kg = float(dig_energy_per_kg())
        # FEE grounding (council #1): the flat electrical J/kg above is now the ANCHOR for a depth/density-
        # dependent cost. `_fee_ref_j_per_kg` is the McKyes/Reece MECHANICAL specific energy for the
        # representative IPEx dig of THIS drum (real width + <=50%-scoop depth + BP-1 in-situ soil). Per-pass
        # energy = electrical_anchor * FEE(this pass) / FEE(representative) — i.e. the FEE mechanical work
        # scaled by a CONSTANT excavation efficiency (ASSUMPTION) pinned so the representative dig == the
        # grounded ~4151 J/kg, but a deeper/denser cut costs proportionally more (see `_dig_specific_energy`).
        self._fee_ref_j_per_kg = float(representative_dig(drum=self.drum)["specific_energy_j_per_kg"])
        self._dig_energy_j = 0.0
        self._last_dig_moved_kg = 0.0
        self._last_dig_j_per_kg = float(self._dig_energy_per_kg)
        # #2: the unbalanced horizontal draft reaction from a dig, fed to the NEXT drive tick's traction
        # demand (a single-front-drum cut is uncancelled; a counter-rotating pair would net ~0). _active is
        # the pending impulse the drive consumes then clears; _last is the HUD/telemetry value.
        self._active_dig_reaction_n = 0.0
        self._last_dig_reaction_n = 0.0
        # #31 aggregate execution metrics (DETERMINISTIC, from the real per-tick drive telem; no rng):
        # ground-truth path length vs the slip-blind WHEEL ODOMETRY. The encoder reads the commanded wheel
        # speed, so under slip it over-reads the achieved ground distance -> odometry_error is the
        # dead-reckoning drift (the MER ~10%-of-distance envelope; stewie/sensors/imu_wheel provenance).
        self._dist_actual_m = 0.0        # SUM |v_achieved| dt  (ground truth)
        self._dist_wheel_m = 0.0         # SUM |v_cmd| dt        (wheel encoder, slip-blind -> over-reads)
        self._slope_sum_deg = 0.0
        self._slope_n = 0
        # #32 faithful DETERMINISTIC IMU (no rng): gyro = achieved yaw rate; accelerometer = SPECIFIC FORCE
        # = body longitudinal accel d(v_achieved)/dt + gravity projected along the incline (lunar g), + a
        # lateral centripetal term. The grounded MTi-10 noise model (twin.proprioception) stays OPT-IN.
        self._prev_v_achieved = 0.0
        self._imu_gyro_z = 0.0           # yaw rate [rad/s]
        self._imu_accel_long = 0.0       # longitudinal specific force [m/s^2]
        self._imu_accel_lat = 0.0        # lateral (centripetal) specific force [m/s^2]

        # --- generation / union-coverage bookkeeping (actor-thread owned) ---
        self._generation = 0
        self._last_acked_gen = 0
        self._last_keyframe_gen = 0
        self._pending: list[tuple[int, list[int]]] = []     # (generation, bbox) since coverage floor
        self._seq_to_gen: dict[int, int] = {}
        self._latest_manifest: str | None = None
        self._latest_keyframe_manifest: str | None = None
        _fine0 = self.ws._require_fine()
        self._window_shape = (int(_fine0.height), int(_fine0.width))

        # --- threads ---
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._actor_thread: threading.Thread | None = None
        self._accept_thread: threading.Thread | None = None
        self._conn_threads: list[threading.Thread] = []

    def _flattest_interior_spawn(self) -> tuple[float, float]:
        """[REQ:AS-15] Spawn on the FLATTEST interior spot of the REAL DEM -- NOT the blind geometric
        centre, which on a 10 km LOLA crater tile is often a >18 deg wall (median tile slope ~16 deg) so
        the conserved slip model entraps the rover at t=0. Neighborhood-mean slope over the real heightfield
        (no synthetic data); the 1 m SfS tile's centre was already flat so this does not regress it."""
        from scipy.ndimage import uniform_filter
        _h = np.asarray(self.ws.base.derive_height(), dtype=float)
        _gy, _gx = np.gradient(_h, self.ws.base_cell_m)
        _sm = uniform_filter(np.hypot(_gx, _gy), size=9, mode="nearest")   # tan(slope), region-mean
        _m = max(1, int(round(0.06 * min(_h.shape))))                      # keep the fine window interior
        _big = float(_sm.max()) + 1.0
        _sm[:_m, :] = _big; _sm[-_m:, :] = _big; _sm[:, :_m] = _big; _sm[:, -_m:] = _big
        _r, _c = np.unravel_index(int(np.argmin(_sm)), _sm.shape)
        print("viz2_runtime: spawn on flattest interior spot rc=(%d,%d) slope=%.2fdeg (was blind centre)"
              % (_r, _c, np.degrees(np.arctan(float(_sm[_r, _c])))), flush=True)
        return (self.ws.world_x0 + float(_c) * self.ws.base_cell_m,
                self.ws.world_y0 + float(_r) * self.ws.base_cell_m)

    # -- token file (S-09 discipline applied to a FILE) ----------------------------------------

    def _write_token_file(self) -> None:
        """Write ``{port, token}`` to a 0600 file. Born 0600 under a restrictive umask (the
        process.py S-09 idiom applied to a file), plus a belt-and-suspenders chmod — so only the same
        OS user can read the token that authorizes the drive session."""
        data = (json.dumps({
            "port": self.port, "token": self.token,
            "start_xy": list(self.start_xy),
            "world_x0": float(self.ws.world_x0), "world_y0": float(self.ws.world_y0),
            "base_cell_m": float(self.ws.base_cell_m),
            "base_w": int(self.ws.base.width), "base_h": int(self.ws.base.height),
        }) + "\n").encode()
        prev = os.umask(0o177)
        try:
            with open(self.token_path, "wb") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
        finally:
            os.umask(prev)
        os.chmod(self.token_path, 0o600)

    # -- lifecycle -----------------------------------------------------------------------------

    def start(self) -> None:
        self._actor_thread = threading.Thread(target=self._actor_loop, name="viz2-actor", daemon=True)
        self._accept_thread = threading.Thread(target=self._accept_loop, name="viz2-accept", daemon=True)
        self._actor_thread.start()
        self._accept_thread.start()
        # S-09 readiness: bound + listening + token file written + threads live.
        self._ready.set()

    def wait_ready(self, timeout: float = 10.0) -> bool:
        return self._ready.wait(timeout)

    def stop(self) -> None:
        self._stop.set()
        if self._actor_thread is not None:
            self._actor_thread.join(timeout=5.0)
        if self._accept_thread is not None:
            self._accept_thread.join(timeout=5.0)
        for t in list(self._conn_threads):
            t.join(timeout=2.0)
        try:
            self._listen.close()
        except OSError:
            pass
        try:
            if os.path.exists(self.token_path):
                os.remove(self.token_path)
        except OSError:
            pass
        self._ready.clear()

    def __enter__(self) -> "Viz2Runtime":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop()

    # -- socket side (never mutates the world) -------------------------------------------------

    def _accept_loop(self) -> None:
        while not self._stop.is_set():
            try:
                conn, _addr = self._listen.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            t = threading.Thread(target=self._serve_conn, args=(conn,), daemon=True)
            t.start()
            self._conn_threads.append(t)

    def _serve_conn(self, conn: socket.socket) -> None:
        """Per-connection handler: token handshake -> register a fresh session (epoch) -> a poll loop
        that ENQUEUES inbound frames and DRAINS this session's outbound telemetry. It NEVER touches
        the world (that is the actor loop's sole province)."""
        conn.settimeout(2.0)
        try:
            line = self._read_line(conn)
            if line is None:
                self._reply(conn, {"ok": False, "error": "empty handshake"})
                return
            try:
                hello = json.loads(line.decode())
            except (ValueError, UnicodeDecodeError):
                self._reply(conn, {"ok": False, "error": "handshake not JSON"})
                return
            # AUTH: the token must be present AND correct. A constant-time compare (the process.py
            # M-05 discipline) — a missing/wrong token authorizes nothing and closes the connection.
            tok = hello.get("token")
            if not isinstance(tok, str) or not secrets.compare_digest(tok, self.token):
                self._reply(conn, {"ok": False, "error": "bad or missing token"})
                return
            # SERVER assigns the role; a client-supplied `role` is ignored.
            epoch, outbound = self._register_session()
            self._reply(conn, {"ok": True, "role": "drive", "epoch": epoch,
                               "protocol_version": PROTOCOL_VERSION})
            self._conn_poll(conn, epoch, outbound)
        except OSError:
            pass
        finally:
            try:
                conn.close()
            except OSError:
                pass

    def _register_session(self) -> tuple[int, queue.Queue]:
        """Mint a new epoch + a fresh StreamSession (the tripped one is terminal — no reset), clear the
        held safe-stop, reset the coalesced twist, and force a connect keyframe. Supersedes any prior
        session (stale-epoch fencing)."""
        with self._lock:
            self._epoch_counter += 1
            epoch = self._epoch_counter
            outbound: queue.Queue[dict] = queue.Queue()
            sess = StreamSession(window=self.window, ack_deadline_s=self.ack_deadline_s,
                                 on_safe_stop=self._make_safe_stop(epoch))
            self._current_epoch = epoch
            self._current_session = sess
            self._current_outbound = outbound
            self._latest_twist = (0.0, 0.0)
            self._safe_stopped = False
            self._force_keyframe = True                     # keyframe on (re)connect
            return epoch, outbound

    def _make_safe_stop(self, epoch: int):
        def _cb() -> None:
            # fired once inside StreamSession.tick() on the ACTOR thread: hold safe-stop + zero twist.
            with self._lock:
                if epoch == self._current_epoch:
                    self._safe_stopped = True
                    self._latest_twist = (0.0, 0.0)
        return _cb

    def _conn_poll(self, conn: socket.socket, epoch: int, outbound: queue.Queue) -> None:
        conn.settimeout(0.05)
        buf = b""
        while not self._stop.is_set():
            # 1) drain this session's outbound telemetry to the client
            try:
                while True:
                    frame = outbound.get_nowait()
                    conn.sendall((json.dumps(frame) + "\n").encode())
            except queue.Empty:
                pass
            # 2) read inbound frames -> enqueue (epoch-tagged; the actor is the authoritative fence)
            try:
                data = conn.recv(4096)
                if not data:
                    break                                    # client closed
                buf += data
            except socket.timeout:
                buf = self._drain_lines(buf, epoch)
                continue
            except OSError:
                break
            if len(buf) > MAX_LINE_BYTES and b"\n" not in buf:
                break                                        # M-03: unterminated flood
            buf = self._drain_lines(buf, epoch)

    def _drain_lines(self, buf: bytes, epoch: int) -> bytes:
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            if len(line) > MAX_LINE_BYTES or not line.strip():
                continue
            try:
                msg = json.loads(line.decode())
            except (ValueError, UnicodeDecodeError):
                continue
            if isinstance(msg, dict):
                self._inbound.put((epoch, msg))
        return buf

    def _read_line(self, conn: socket.socket) -> bytes | None:
        buf = b""
        while b"\n" not in buf:
            chunk = conn.recv(4096)
            if not chunk:
                return None
            buf += chunk
            if len(buf) > MAX_LINE_BYTES:
                return None                                  # M-03 bound
        return buf.split(b"\n", 1)[0]

    def _reply(self, conn: socket.socket, obj: dict) -> None:
        try:
            conn.sendall((json.dumps(obj) + "\n").encode())
        except OSError:
            pass

    # -- the actor loop (the SOLE mutator) -----------------------------------------------------

    def _actor_loop(self) -> None:
        while not self._stop.is_set():
            t0 = time.monotonic()
            self._drain_inbound()
            with self._lock:
                sess = self._current_session
                outbound = self._current_outbound
                epoch = self._current_epoch
                force_kf = self._force_keyframe
                self._force_keyframe = False
                do_dig = self._pending_dig and not self._safe_stopped
                self._pending_dig = False
                do_dump = self._pending_dump and not self._safe_stopped
                self._pending_dump = False
                v, omega = (0.0, 0.0) if self._safe_stopped else self._latest_twist
            if sess is not None:
                self._step_and_publish(sess, outbound, epoch, v, omega, force_kf, do_dig, do_dump)
            # maintain the fixed rate (real timing, no faking)
            rest = self._period - (time.monotonic() - t0)
            if rest > 0:
                time.sleep(rest)

    def _step_and_publish(self, sess: StreamSession, outbound: queue.Queue | None,
                          epoch: int, v: float, omega: float, force_kf: bool,
                          do_dig: bool = False, do_dump: bool = False) -> None:
        # #2: the drive resists any pending unbalanced dig reaction from the PRIOR tick's dig (raises slip /
        # can entrap), then the single-tick impulse is consumed. A dig LATER in this same tick re-arms it.
        telem, dirty = self.ws.step(v, omega, self.dt, dig_reaction_n=self._active_dig_reaction_n)
        self._active_dig_reaction_n = 0.0
        self._last_applied_twist = (v, omega)
        self._accumulate_metrics(telem, self.dt)          # #31 aggregate exec metrics from the real telem
        if do_dig:
            # a conserved dig at the current pose (WorkSite.flatten -> the drum ledger); its dirty
            # region rides THIS generation, so height/state/disturbance carry the trench downstream.
            dig_dirty = self._apply_dig()
            dirty = dirty + dig_dirty
            telem["dug"] = bool(dig_dirty)
        if do_dump:
            # a conserved dump at the current pose (WorkSite.dump -> spoil onto the footprint); its
            # dirty region rides THIS generation, so the bermed height/state carry downstream.
            dump_dirty = self._apply_dump()
            dirty = dirty + dump_dirty
            telem["dumped"] = bool(dump_dirty)
        keyframe = (force_kf or bool(telem.get("recentered"))
                    or (self._generation + 1 - self._last_keyframe_gen) >= self.keyframe_interval)
        gen = self._advance_generation(dirty, keyframe)
        residual_frac = self._residual_frac()
        # E1: moved-mass ledgers + grounded excavation energy on every telemetry frame (HUD budget).
        telem["cut_total_kg"] = float(self.ws.cut_total_kg)
        telem["placed_total_kg"] = float(self.ws.placed_total_kg)
        telem["inventory_kg"] = float(self.ws.inventory_kg)
        telem["dig_energy_j"] = float(self._dig_energy_j)
        telem["dig_energy_per_kg"] = float(self._dig_energy_per_kg)     # grounded electrical anchor
        telem["dig_j_per_kg"] = float(self._last_dig_j_per_kg)          # FEE-modulated cost of the last pass
        telem["dig_reaction_n"] = float(self._last_dig_reaction_n)      # #2: unbalanced draft reaction (last dig)
        # #31 aggregate execution metrics (deterministic; wheel odometry over-reads the ground truth by slip)
        telem["dist_actual_m"] = float(self._dist_actual_m)
        telem["wheel_odo_m"] = float(self._dist_wheel_m)
        telem["odometry_error_m"] = float(self._dist_wheel_m - self._dist_actual_m)
        telem["avg_slope_deg"] = float(self._slope_sum_deg / max(1, self._slope_n))
        # #32 faithful deterministic IMU (specific force + yaw rate)
        telem["imu_gyro_z"] = float(self._imu_gyro_z)
        telem["imu_accel_long"] = float(self._imu_accel_long)
        telem["imu_accel_lat"] = float(self._imu_accel_lat)
        payload = {
            "type": "telemetry", "generation": gen, "keyframe": keyframe,
            "telem": telem, "dirty": [list(b) for b in dirty],
            "residual_frac": residual_frac, "safe_stop": self._safe_stopped,
        }
        frame = sess.send(payload, now=time.monotonic())
        if frame is not None:
            self._seq_to_gen[int(frame["seq"])] = gen
            if outbound is not None:
                outbound.put(frame)
        # drive the deadman every iteration — independent of any inbound read (the NB-3 fix)
        if sess.tick(now=time.monotonic()):
            self._on_trip(epoch, outbound)

    def _on_trip(self, epoch: int, outbound: queue.Queue | None) -> None:
        """Deadman terminal: the safe-stop is already held (the on_safe_stop callback zeroed the
        twist); emit a raw safe-stop notice (the tripped session's send() refuses, so this rides
        out-of-band) and CLOSE the session. Recovery is a fresh authenticated connection."""
        if outbound is not None:
            outbound.put({"type": "safe_stop", "reason": "deadman_link_stall", "epoch": epoch})
        with self._lock:
            if epoch == self._current_epoch:
                self._current_session = None
                self._current_outbound = None
                # _safe_stopped stays True until a fresh session re-arms (holds the rover stopped)

    def _drain_inbound(self) -> None:
        """Apply queued socket messages of the CURRENT epoch; DROP stale-epoch frames (fencing). Twist
        bounds (M-04) are checked here at ingest so ws.step never sees an out-of-bound command."""
        while True:
            try:
                epoch, msg = self._inbound.get_nowait()
            except queue.Empty:
                return
            with self._lock:
                current = self._current_epoch
                sess = self._current_session
            if epoch != current:
                self._rejected_stale += 1                    # stale-client fencing (plan §2b.3)
                continue
            cmd = str(msg.get("cmd", ""))
            if cmd == "twist":
                self._ingest_twist(msg)
            elif cmd == "dig":
                # arm a conserved dig for the next actor tick (applied on the actor thread only).
                self._pending_dig = True
            elif cmd == "dump":
                # arm a conserved dump for the next actor tick (applied on the actor thread only).
                self._pending_dump = True
            elif cmd == "ack" and sess is not None:
                seq_raw = msg.get("seq")
                if seq_raw is None:
                    continue
                try:
                    seq = int(seq_raw)
                except (TypeError, ValueError):
                    continue
                sess.ack(seq)
                gen = self._seq_to_gen.get(seq)
                if gen is not None and gen > self._last_acked_gen:
                    self._last_acked_gen = gen               # union-coverage floor advances

    def _ingest_twist(self, msg: dict) -> None:
        v, omega = msg.get("v", 0.0), msg.get("omega", 0.0)
        # M-04 (the process.py pattern): a non-finite / over-bound twist is REFUSED at ingest, never
        # applied — so one command can never teleport the footprint or poison the shared pose.
        if not (isinstance(v, (int, float)) and math.isfinite(v)
                and isinstance(omega, (int, float)) and math.isfinite(omega)):
            self._rejected_bounds += 1
            return
        if abs(float(v)) > self.ws.v_max or abs(float(omega)) > self.ws.omega_max:
            self._rejected_bounds += 1
            return
        with self._lock:
            if not self._safe_stopped:
                self._latest_twist = (float(v), float(omega))

    def _seed_rockfield(self, bundle_dir: str) -> None:
        """Generate the spatial-k Golombek rock field around the spawn and SET it on the WorkSite so the
        conserved drive rides over / is blocked by rocks (drive_step clasts D4), plus write the same list
        to clasts.json for the Godot display. Best-effort: any failure -> no rocks (drive still works;
        drive_step(clasts=None) is the byte-identical clast-free seam). To bound the per-tick ride-over
        scan, only the largest boulders are handed to the physics; the display shows the full field."""
        try:
            import importlib.util
            repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            spec = importlib.util.spec_from_file_location(
                "viz2_rockfield_clasts", os.path.join(repo, "scripts", "viz2_rockfield_clasts.py"))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            cell = self.ws.base_cell_m
            bw, bh = self.ws.base.width, self.ws.base.height
            n = max(8, min(int(round(140.0 / cell)), bw, bh))
            c0 = int(min(max(0, round((self.start_xy[0] - self.ws.world_x0) / cell - n / 2)), bw - n))
            r0 = int(min(max(0, round((self.start_xy[1] - self.ws.world_y0) / cell - n / 2)), bh - n))
            result = mod.build_clasts(bundle_dir, r0, c0, n, d_min_m=0.15, d_max_m=0.8, world_seed=0)
            clasts = result.get("clasts") or []
            # ALL boulders go to the physics now (small ride-over with a bump, >wheel-radius block/pitch);
            # the window-local filter is vectorized + O(nearby), so the full field is cheap per tick.
            self.ws.clasts = clasts or None
            with open(os.path.join(self.session_dir, "clasts.json"), "w") as fh:
                json.dump(result, fh)                        # display: the SAME full field
            print("viz2_runtime: rock field %d clasts -> physics(ride-over/block) + display"
                  % len(clasts), flush=True)
        except Exception as exc:
            print("viz2_runtime: rockfield skipped (%s: %s)" % (type(exc).__name__, exc), flush=True)

    def _accumulate_metrics(self, telem: dict, dt: float) -> None:
        """#31: fold ONE tick's real drive telem into the deterministic aggregate metrics. Wheel odometry
        integrates the COMMANDED wheel speed (what a slip-blind encoder reads), ground truth integrates the
        ACHIEVED speed; under slip v_achieved < v_cmd so the wheel odometry over-reads -> the running
        odometry_error is the dead-reckoning drift. avg slope is the mean traversed grade. No rng, no synthetic."""
        va = float(telem.get("v_achieved", 0.0))          # signed ground-truth body speed
        vc = float(telem.get("v_cmd", 0.0))               # commanded (== wheel-surface) speed
        omega = float(telem.get("omega_achieved", 0.0))   # achieved yaw rate
        slope = float(telem.get("slope_rad", 0.0))
        if not (math.isfinite(va) and math.isfinite(vc) and math.isfinite(omega) and math.isfinite(slope)):
            return                                        # never latch a NaN into the faithful cumulative HUD metrics
        # #31 aggregate distances (magnitudes) + mean grade
        self._dist_actual_m += abs(va) * dt
        self._dist_wheel_m += abs(vc) * dt
        self._slope_sum_deg += math.degrees(abs(slope))
        self._slope_n += 1
        # #32 faithful DETERMINISTIC IMU: gyro = achieved yaw rate; accelerometer = SPECIFIC FORCE
        # (body accel d(v)/dt + gravity along the incline, lunar g) + a lateral centripetal term.
        self._imu_gyro_z = omega
        self._imu_accel_long = (va - self._prev_v_achieved) / max(dt, 1e-6) + LUNAR_G_MS2 * math.sin(slope)
        self._imu_accel_lat = omega * va
        self._prev_v_achieved = va

    def _drum_rc(self) -> tuple[int, int] | None:
        """Fine-window (row,col) of the FRONT DRUM (~0.4 m ahead of the pose along the travel heading) --
        the real dig/dump contact point (front-drum-down geometry), which also keeps the worked patch
        out from under the rover body so the trench/berm reads. yaw: 0=+x, +pi/2=+y (worksite convention)."""
        if self.ws.pose_xy is None:
            return None
        ahead = 0.40
        dx = ahead * math.cos(self.ws.yaw)
        dy = ahead * math.sin(self.ws.yaw)
        rc = self.ws.active_rc_for_xy((self.ws.pose_xy[0] + dx, self.ws.pose_xy[1] + dy))
        return int(round(rc[0])), int(round(rc[1]))

    def _apply_dig(self) -> list[list[int]]:
        """Conserved excavation at the current pose (actor thread only): flatten a footprint-sized
        box down to ``dig_depth_m`` below its lowest cell, so every masked cell is a pure CUT into the
        drum ledger (mass exact). Returns the dig's dirty bbox (fine-cell ``[r0,c0,r1,c1]``) or ``[]``
        when the pose is unseated. The height drop is what the window mesh's vertex shader displaces —
        the visibly carved rut."""
        if self.ws.pose_xy is None:
            return []
        H, W = self._window_shape
        drc = self._drum_rc()
        if drc is None:
            return []
        r, c = drc
        hc = self.dig_half_cells
        r0, r1 = max(0, r - hc), min(H, r + hc + 1)
        c0, c1 = max(0, c - hc), min(W, c + hc + 1)
        if r1 <= r0 or c1 <= c0:
            return []
        f = self.ws._require_fine()
        mask = np.zeros((H, W), dtype=bool)
        mask[r0:r1, c0:c1] = True
        target = float(f.derive_height()[r0:r1, c0:c1].min()) - self.dig_depth_m
        moved = self.ws.flatten(mask, target)                # cells above target -> cut (conserved)
        self._last_dig_moved_kg = float(moved)
        # ONE FEE solve -> the depth^2/density-dependent per-kg energy (council #1) AND the unbalanced draft
        # reaction on the chassis (council #2), not the old flat constant / zero reaction.
        fee = self._dig_fee(r0, r1, c0, c1, float(moved), f)
        self._last_dig_j_per_kg = float(fee["j_per_kg"])
        self._dig_energy_j += float(moved) * float(fee["j_per_kg"])    # E1: FEE-modulated dig energy debit
        self._last_dig_reaction_n = float(fee["reaction_n"])
        self._active_dig_reaction_n = float(fee["reaction_n"])         # #2: the NEXT drive tick resists it
        self._dig_count += 1
        return [[r0, c0, r1, c1]]

    def _dig_fee(self, r0: int, r1: int, c0: int, c1: int, moved_kg: float, f) -> dict:
        """ONE McKyes/Reece FEE solve for ONE excavation pass -> ``{j_per_kg, reaction_n}`` (councils #1 + #2).

        ``excavation.earthmoving_report`` over the real per-pass BITE depth, the selected drum's tool width,
        and the LOCAL in-situ regolith density + strength gives the MECHANICAL cutting work per kg (rising
        with cut depth^2 and density) AND the horizontal draft force. Energy: scaled by a constant excavation
        efficiency (ASSUMPTION) pinning the representative IPEx dig to the grounded electrical figure, so
        ``j_per_kg = anchor * FEE(this pass) / FEE(representative)``. Reaction: the live model cuts with a
        SINGLE (front) drum, so ``net_dig_reaction_n`` leaves the FULL draft on the chassis (a future
        counter-rotating both-drum dig would net ~0) -> fed to the next drive tick's traction demand.
        Falls back to ``{flat energy, 0 reaction}`` on no-bite / degenerate footprint / degenerate wedge."""
        flat = {"j_per_kg": float(self._dig_energy_per_kg), "reaction_n": 0.0}
        if moved_kg <= 0.0 or self._fee_ref_j_per_kg <= 0.0:
            return flat
        cell = float(self.ws.fine_cell_m)
        area_m2 = float((r1 - r0) * (c1 - c0)) * cell * cell
        if area_m2 <= 0.0:
            return flat
        # LOCAL in-situ bulk density of the cut cells (real per-cell density field, not a constant).
        rho = float(np.mean(np.asarray(f.density[r0:r1, c0:c1], dtype=float)))
        if rho <= 0.0:
            return flat
        # Characteristic per-pass BITE depth = mean height removed = moved / (rho * area); capped at the
        # <=50%-scoop anti-bridging limit so the FEE depth stays in the physical single-pass regime.
        d_eff = min(moved_kg / (rho * area_m2), self._max_cut_per_pass_m)
        if d_eff <= 0.0:
            return flat
        phi_rad, cohesion_pa = cell_strength(rho)
        try:
            rep = earthmoving_report(
                depth_m=d_eff, width_m=self._drum_width_m, cohesion_pa=cohesion_pa,
                bulk_density_kg_m3=rho, gravity_ms2=LUNAR_G_MS2, phi_rad=phi_rad)
        except ValueError:
            return flat
        j_per_kg = float(self._dig_energy_per_kg) * (float(rep["specific_energy_j_per_kg"]) / self._fee_ref_j_per_kg)
        # single front drum digging => no counter-rotation cancellation => the full FEE draft reacts on the
        # chassis. Route through net_dig_reaction_n (torque=draft*r) so the counter-rotation semantics are
        # explicit + future-proof: switching drums=("front","back") for a balanced both-drum dig nets ~0.
        draft_n = float(rep["draft_n"])
        reaction_n = abs(net_dig_reaction_n(draft_n * self._drum_radius_m, self._drum_radius_m,
                                            drums=("front",)))
        return {"j_per_kg": j_per_kg, "reaction_n": reaction_n}

    def _dig_specific_energy(self, r0: int, r1: int, c0: int, c1: int,
                             moved_kg: float, f) -> float:
        """Thin wrapper -> the FEE-grounded specific dig energy [J/kg] for ONE pass (council #1). See _dig_fee."""
        return float(self._dig_fee(r0, r1, c0, c1, moved_kg, f)["j_per_kg"])

    def _apply_dump(self) -> list[list[int]]:
        """Conserved deposit at the current pose (actor thread only): dump the whole drum ledger as
        bulked SPOIL over a footprint-sized box, so a berm rises (a real height gain the window mesh's
        vertex shader displaces — the positive side of the E2 diff drape). Returns the dump's dirty bbox
        (fine-cell ``[r0,c0,r1,c1]``) or ``[]`` when the pose is unseated / the drum is empty."""
        if self.ws.pose_xy is None or self.ws.inventory_kg <= 0.0:
            return []
        H, W = self._window_shape
        drc = self._drum_rc()
        if drc is None:
            return []
        r, c = drc
        hc = self.dig_half_cells
        r0, r1 = max(0, r - hc), min(H, r + hc + 1)
        c0, c1 = max(0, c - hc), min(W, c + hc + 1)
        if r1 <= r0 or c1 <= c0:
            return []
        mask = np.zeros((H, W), dtype=bool)
        mask[r0:r1, c0:c1] = True
        placed = self.ws.dump(mask)                          # whole ledger -> bulked spoil (conserved)
        if placed <= 0.0:
            return []
        # sandpile-relax the fresh spoil to the ~35 deg lunar angle of repose so a real BERM forms
        # (mass-conserving within the window) instead of a flat-topped box; the repose cone spreads
        # past the dump footprint, so widen the dirty bbox the render re-displaces.
        self.ws.relax()
        self._dump_count += 1
        br = 2 * hc
        return [[max(0, r0 - br), max(0, c0 - br), min(H, r1 + br), min(W, c1 + br)]]

    # -- generation-namespaced patch manifests (plan §2b.4) ------------------------------------

    def _advance_generation(self, dirty: list[list[int]], keyframe: bool) -> int:
        self._generation += 1
        gen = self._generation
        for bb in dirty:
            self._pending.append((gen, list(bb)))
        if keyframe:
            self._last_keyframe_gen = gen
        # coverage floor = the later of the consumer's last ACK and the last keyframe; the union covers
        # every dirty region since that floor (plan §2b.4 union-coverage invariant).
        floor = max(self._last_acked_gen, self._last_keyframe_gen if not keyframe else 0)
        self._pending = [(g, bb) for (g, bb) in self._pending if g > floor]
        H, W = self._window_shape
        if keyframe:
            bbox = [0, 0, H, W]
            self._pending = []                               # a keyframe is the new coverage baseline
        else:
            bbox = self._union_bbox(self._pending, H, W)
        self._write_manifest(gen, bbox, keyframe, dirty)
        self._prune_generations(gen)
        return gen

    @staticmethod
    def _union_bbox(pending: list[tuple[int, list[int]]], H: int, W: int) -> list[int]:
        r0 = min(bb[0] for _, bb in pending)
        c0 = min(bb[1] for _, bb in pending)
        r1 = max(bb[2] for _, bb in pending)
        c1 = max(bb[3] for _, bb in pending)
        return [max(0, r0), max(0, c0), min(H, r1), min(W, c1)]

    def _field_arrays(self, keyframe: bool) -> dict[str, tuple[np.ndarray, str, str]]:
        f = self.ws._require_fine()
        arrs: dict[str, tuple[np.ndarray, str, str]] = {
            "height": (f.derive_height(), _RF32, "height.rf32"),
            "density": (f.density, _RF32, "density.rf32"),
            "state_label": (f.state_label, _R8, "state_label.r8"),
            "disturbance": (f.disturbance, _RF32, "disturbance.rf32"),
            # E2: the signed before/after difference drape field (h_now - h_virgin), streamed every
            # generation so the client's diff shader falsecolors the live cut(-)/berm(+) as it carves.
            "diff": (self.ws.diff_field(), _RF32, "diff.rf32"),
        }
        if keyframe:
            arrs["mass_areal"] = (f.mass_areal, _RF32, "mass_areal.rf32")   # full-resync set
        return arrs

    def _write_manifest(self, gen: int, bbox: list[int], keyframe: bool,
                        dirty: list[list[int]]) -> None:
        r0, c0, r1, c1 = bbox
        gdir = os.path.join(self.generations_dir, f"gen_{gen:08d}")
        os.makedirs(gdir, exist_ok=True)
        fields_meta: dict[str, dict] = {}
        for name, (arr, dtype, fname) in self._field_arrays(keyframe).items():
            crop = np.ascontiguousarray(np.asarray(arr)[r0:r1, c0:c1].astype(dtype))
            data = crop.tobytes()
            atomic_write_bytes(os.path.join(gdir, fname), data, sync=False)   # ephemeral per-tick dir (council: perf)
            fields_meta[name] = {"file": fname, "dtype": dtype,
                                 "shape": [int(r1 - r0), int(c1 - c0)],
                                 "digest": hashlib.sha256(data).hexdigest()}
        wwo = self.ws.window_world_origin
        manifest = {
            "protocol_version": PROTOCOL_VERSION,
            "generation": int(gen), "keyframe": bool(keyframe),
            "window_world_origin": [float(wwo[0]), float(wwo[1])] if wwo is not None else None,
            "fine_cell_m": float(self.ws.fine_cell_m),
            "bbox_rc": [int(r0), int(c0), int(r1), int(c1)],
            "shape": [int(r1 - r0), int(c1 - c0)],
            "fields": fields_meta,
            "dirty": [list(b) for b in dirty],
        }
        # the manifest is written LAST (the commit marker): its presence guarantees every crop beside
        # it is complete (io_fields CT-04 idiom). Atomic tmp+rename.
        atomic_write_bytes(os.path.join(gdir, "manifest.json"),
                           json.dumps(manifest, sort_keys=True).encode(), sync=False)   # ephemeral (council: perf)
        self._latest_manifest = os.path.join(gdir, "manifest.json")
        if keyframe:
            self._latest_keyframe_manifest = self._latest_manifest

    def _prune_generations(self, gen: int) -> None:
        """Bound disk: keep only the most recent ``retain_generations`` generation dirs. Never prunes
        the newest keyframe (a late-joining client resyncs from it)."""
        old = gen - self.retain_generations
        if old < 1:
            return
        keep_kf = self._latest_keyframe_manifest
        gdir = os.path.join(self.generations_dir, f"gen_{old:08d}")
        if keep_kf is not None and os.path.dirname(keep_kf) == gdir:
            return
        if os.path.isdir(gdir):
            for fn in os.listdir(gdir):
                try:
                    os.remove(os.path.join(gdir, fn))
                except OSError:
                    pass
            try:
                os.rmdir(gdir)
            except OSError:
                pass

    # -- introspection (call after stop() for a race-free world read) --------------------------

    def _residual_frac(self) -> float:
        base = self.ws._baseline_virgin_kg
        if not base:
            return 0.0
        return self.ws.conservation_residual() / base

    def conservation_residual_frac(self) -> float:
        return self._residual_frac()

    def window_shape(self) -> tuple[int, int]:
        return self._window_shape

    def window_fields(self) -> dict[str, np.ndarray]:
        """A snapshot of the authority's current active-window render fields (call after stop())."""
        f = self.ws._require_fine()
        return {
            "height": f.derive_height().astype("<f4"),
            "density": np.asarray(f.density, dtype="<f4"),
            "state_label": np.asarray(f.state_label, dtype="u1"),
            "disturbance": np.asarray(f.disturbance, dtype="<f4"),
            "mass_areal": np.asarray(f.mass_areal, dtype="<f4"),
        }

    def emit_volume_evidence(self, *, density_kg_m3: float | None = None,
                             work_order_id: str = "viz2-session",
                             transaction_id: str = "viz2-session",
                             height_rmse_m: float = 0.0, density_frac: float = 0.0) -> dict:
        """E3: on session/dig end, emit the REAL RegolithVolumeEstimate over the worked active window.

        ``before`` = the deterministic VIRGIN surface (E2's ``window_virgin_height``), ``after`` = the
        as-built ``derive_height()``; the conserved cross-check is ``conserved_mass_kg = cut_total_kg``
        — the cumulative CUT mass ONLY. ``from_delta`` compares it against the cut-volume mass
        ``observed = cut_volume_m3 * density``; on the conserved authority these agree exactly (the cut
        releases height ``removed_areal/density``), so ``agreement_conserved`` is True with a
        cut-then-dump-in-place run passing (the round-3 regression the old ``cut+placed`` argument would
        have falsely failed — verified plan §9/E3).

        ``placed_total_kg`` and the drum residual ``inventory_kg`` are returned as SEPARATE quantities,
        NEVER summed into ``conserved_mass_kg``. ``density_kg_m3`` defaults to the in-situ (virgin)
        density of the CUT cells (uniform on the default mantle); pass a sourced value to override."""
        f = self.ws._require_fine()
        before = self.ws.window_virgin_height()
        after = np.asarray(f.derive_height(), dtype=float)
        if density_kg_m3 is None:
            # in-situ density of the CUT material: cut cells (below virgin) keep their original density
            # (flatten reduces mass_areal only; dump — not flatten — is what changes a cell's density),
            # so their density is the honest in-situ figure `observed = cut_volume*density` must use.
            dens = np.asarray(f.density, dtype=float)
            cut_mask = (after - before) < -1e-9
            density_kg_m3 = float(dens[cut_mask].mean()) if cut_mask.any() else float(dens.mean())
        est = RegolithVolumeEstimate.from_delta(
            before, after, float(self.ws.fine_cell_m),
            work_order_id=work_order_id,
            before_source="viz2:window_virgin",
            after_source="viz2:as_built",
            transaction_id=transaction_id,
            density_kg_m3=float(density_kg_m3),
            height_rmse_m=float(height_rmse_m),
            density_frac=float(density_frac),
            conserved_mass_kg=float(self.ws.cut_total_kg),   # CUT mass ONLY (E3 round-3 contract)
        )
        return {
            "estimate": est,
            "cut_total_kg": float(self.ws.cut_total_kg),
            "placed_total_kg": float(self.ws.placed_total_kg),   # SEPARATE, never summed in
            "inventory_kg": float(self.ws.inventory_kg),         # SEPARATE, never summed in
            "density_kg_m3": float(density_kg_m3),
            "dig_energy_j": float(self._dig_energy_j),
        }

    def latest_manifest_path(self) -> str:
        if self._latest_manifest is None:
            raise RuntimeError("no generation manifest written yet")
        return self._latest_manifest

    def latest_keyframe_manifest_path(self) -> str:
        if self._latest_keyframe_manifest is None:
            raise RuntimeError("no keyframe manifest written yet")
        return self._latest_keyframe_manifest
