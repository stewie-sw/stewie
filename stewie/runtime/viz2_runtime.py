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
from stewie.contracts.physics_model_control import LIVE_DEFAULT_MODEL_ID, resolve_live_backend
from stewie.physics.worksite import WorkSite
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
                 dig_depth_m: float = 0.12, dig_half_cells: int = 8,
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
            # deep-interior default: the base grid centre
            start_xy = (self.ws.world_x0 + 0.5 * self.ws.base.width * self.ws.base_cell_m,
                        self.ws.world_y0 + 0.5 * self.ws.base.height * self.ws.base_cell_m)
        self.ws.recenter((float(start_xy[0]), float(start_xy[1])))
        self.ws.set_pose((float(start_xy[0]), float(start_xy[1])), yaw=float(start_yaw))

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
        self.host = str(host)

        # --- session directory + generation store ---
        self.session_dir = os.path.abspath(session_dir)
        os.makedirs(self.session_dir, exist_ok=True)
        self.generations_dir = os.path.join(self.session_dir, "generations")
        os.makedirs(self.generations_dir, exist_ok=True)
        self.token_path = os.path.join(self.session_dir, "viz2_session.json")

        # --- authenticated loopback-TCP seam (bound now; token minted; 0600 file) ---
        self.token = secrets.token_hex(32)
        self._listen = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listen.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listen.bind((self.host, 0))
        self._listen.listen(8)
        self._listen.settimeout(0.2)
        self.port = int(self._listen.getsockname()[1])
        self._write_token_file()

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
        self._rejected_stale = 0
        self._rejected_bounds = 0
        self._dig_count = 0
        self._last_applied_twist: tuple[float, float] = (0.0, 0.0)

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

    # -- token file (S-09 discipline applied to a FILE) ----------------------------------------

    def _write_token_file(self) -> None:
        """Write ``{port, token}`` to a 0600 file. Born 0600 under a restrictive umask (the
        process.py S-09 idiom applied to a file), plus a belt-and-suspenders chmod — so only the same
        OS user can read the token that authorizes the drive session."""
        data = (json.dumps({"port": self.port, "token": self.token}) + "\n").encode()
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
                v, omega = (0.0, 0.0) if self._safe_stopped else self._latest_twist
            if sess is not None:
                self._step_and_publish(sess, outbound, epoch, v, omega, force_kf, do_dig)
            # maintain the fixed rate (real timing, no faking)
            rest = self._period - (time.monotonic() - t0)
            if rest > 0:
                time.sleep(rest)

    def _step_and_publish(self, sess: StreamSession, outbound: queue.Queue | None,
                          epoch: int, v: float, omega: float, force_kf: bool,
                          do_dig: bool = False) -> None:
        telem, dirty = self.ws.step(v, omega, self.dt)       # the conserved single-mutator drive
        self._last_applied_twist = (v, omega)
        if do_dig:
            # a conserved dig at the current pose (WorkSite.flatten -> the drum ledger); its dirty
            # region rides THIS generation, so height/state/disturbance carry the trench downstream.
            dig_dirty = self._apply_dig()
            dirty = dirty + dig_dirty
            telem["dug"] = bool(dig_dirty)
        keyframe = (force_kf or bool(telem.get("recentered"))
                    or (self._generation + 1 - self._last_keyframe_gen) >= self.keyframe_interval)
        gen = self._advance_generation(dirty, keyframe)
        residual_frac = self._residual_frac()
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

    def _apply_dig(self) -> list[list[int]]:
        """Conserved excavation at the current pose (actor thread only): flatten a footprint-sized
        box down to ``dig_depth_m`` below its lowest cell, so every masked cell is a pure CUT into the
        drum ledger (mass exact). Returns the dig's dirty bbox (fine-cell ``[r0,c0,r1,c1]``) or ``[]``
        when the pose is unseated. The height drop is what the window mesh's vertex shader displaces —
        the visibly carved rut."""
        if self.ws.pose_xy is None:
            return []
        H, W = self._window_shape
        rc = self.ws.active_rc_for_xy(self.ws.pose_xy)
        r = int(round(rc[0]))
        c = int(round(rc[1]))
        hc = self.dig_half_cells
        r0, r1 = max(0, r - hc), min(H, r + hc + 1)
        c0, c1 = max(0, c - hc), min(W, c + hc + 1)
        if r1 <= r0 or c1 <= c0:
            return []
        f = self.ws._require_fine()
        mask = np.zeros((H, W), dtype=bool)
        mask[r0:r1, c0:c1] = True
        target = float(f.derive_height()[r0:r1, c0:c1].min()) - self.dig_depth_m
        self.ws.flatten(mask, target)                        # cells above target -> cut (conserved)
        self._dig_count += 1
        return [[r0, c0, r1, c1]]

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
            atomic_write_bytes(os.path.join(gdir, fname), data)
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
                           json.dumps(manifest, sort_keys=True).encode())
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

    def latest_manifest_path(self) -> str:
        if self._latest_manifest is None:
            raise RuntimeError("no generation manifest written yet")
        return self._latest_manifest

    def latest_keyframe_manifest_path(self) -> str:
        if self._latest_keyframe_manifest is None:
            raise RuntimeError("no keyframe manifest written yet")
        return self._latest_keyframe_manifest
