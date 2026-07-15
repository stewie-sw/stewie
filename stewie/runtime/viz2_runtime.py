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
from stewie.specs import constants as K
from stewie.specs.ipex_specs import (
    DRUM_CAPACITY_KG, DRUM_DIMENSIONS_M, LUNAR_G_MS2, dig_energy_per_kg, max_cut_per_pass_m)
from stewie.physics.excavation import earthmoving_report, representative_dig
from stewie.physics.material import cell_strength
from stewie.specs.arm_state import (
    ARM_OFFSET_MAX_RAD, ARM_OFFSET_MIN_RAD, dig_engagement, net_dig_reaction_n)
from stewie.physics.rassor_mass_model import DrumSensor
from stewie.twin.io_fields import atomic_write_bytes

#: [REQ:PX-13] Along-heading offset of each bucket drum's contact patch from the pose: the FRONT drum sits
#: +DRUM_OFFSET_M ahead, the BACK drum -DRUM_OFFSET_M behind. Two patches straddling the chassis is what the
#: real RASSOR/IPEx has, and it is WHY the counter-rotating drums' horizontal reactions can cancel
#: (KSC-TOPS-7). [ASSUMPTION]: 0.40 m is the value the single-drum model already used; no sourced drum-pivot
#: standoff is published, so the magnitude is inherited rather than invented, and the SYMMETRY (front and
#: back equidistant) is the part the physics actually leans on.
DRUM_OFFSET_M = 0.40

# Reused DISCIPLINE (not the class): the RuntimeProcess bounded request-line ceiling (M-03). A real
# viz2 command line is < 64 bytes; this cap is ~1000x real traffic, fatal to the unbounded-readline OOM.
MAX_LINE_BYTES = 65536

_RF32 = "<f4"
_R8 = "u1"

# The render/patch field set (plan §2b.4): height, density, state_label, disturbance every drive step;
# mass_areal rides keyframes (the full-resync set) and dig deltas (E1, not exercised in B2).
_DRIVE_FIELDS = ("height", "density", "state_label", "disturbance")


_ROCKFIELD_MOD = None


def _rockfield_module():
    """The Golombek rock-field generator, loaded ONCE per process.

    This used to be re-executed on EVERY Viz2Runtime construction: `spec_from_file_location` +
    `module_from_spec` + `exec_module`, producing a brand-new module object each time and never caching it
    in sys.modules. A process that builds many runtimes (a scenario fingerprint loop, a dataset build, the
    test suite) therefore re-imported and re-initialised it -- and its numeric dependencies -- once per
    world. That is pure waste, and repeated re-execution of modules that pull in native extensions is a
    known source of native instability, which matters here: a full-suite run took a SIGSEGV inside an
    unrelated native reader (see the flaky-crash task). Caching it is correct regardless of whether it was
    the cause; it makes construction cheaper and the process quieter.
    """
    global _ROCKFIELD_MOD
    if _ROCKFIELD_MOD is None:
        import importlib.util
        repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        spec = importlib.util.spec_from_file_location(
            "viz2_rockfield_clasts", os.path.join(repo, "scripts", "viz2_rockfield_clasts.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _ROCKFIELD_MOD = mod
    return _ROCKFIELD_MOD


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
                 dig_depth_m: float = 0.02, dig_half_cells: int | None = None,
                 drum: str = "large", rock_seed: int = 0,
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
        # Selected bucket drum (flight-representative "large" by default): its REAL width feeds the FEE
        # excavation-force model (tool width w) and its scoop height sets the <=50% anti-bridging cut cap.
        # Resolved BEFORE the dig footprint, which is now derived from it.
        self.drum = str(drum) if str(drum) in DRUM_DIMENSIONS_M else "large"
        self._drum_width_m = float(DRUM_DIMENSIONS_M[self.drum]["width"])
        self._drum_radius_m = 0.5 * float(DRUM_DIMENSIONS_M[self.drum]["diameter"])
        self._max_cut_per_pass_m = float(max_cut_per_pass_m(self.drum))
        # [REQ:PX-09] the drum's sourced hold [BDSCALE] (small 3.80 / medium 7.30 / large 24.98 kg). The
        # live dig is BOUNDED by it: a bite that would overfill is trimmed to the room left, and a full
        # drum refuses the bite outright -- that refusal IS the fill -> stop -> haul quantum. (Every hold
        # is <= the 30 kg/cycle RDS envelope, so the envelope now holds by construction, not after the fact.)
        self._drum_capacity_kg = float(DRUM_CAPACITY_KG[self.drum])
        # [REQ:PX-13] The vehicle carries TWO bucket drums, and [BDSCALE] DRUM_CAPACITY_KG is the hold of ONE
        # ("Avg total regolith collected PER DRUM", Schuler 2022 Table 3). So the VEHICLE hold is 2x. Note
        # what does and does not follow: two drums cut two footprints, so mass-in doubles -- but the tank
        # doubles too, so PASSES-TO-FULL IS UNCHANGED. What actually doubles is THROUGHPUT: every haul
        # carries twice the regolith. That is the real reason the machine has two drums.
        #
        # A SOURCED TENSION, SURFACED RATHER THAN CLAMPED: at two drums the vehicle hold is
        #   small 7.60 / medium 14.60 / large 49.96 kg
        # and PX-09 asserted every hold sits inside the 30 kg/cycle RDS envelope "by construction" -- which
        # is now FALSE for the large drum. It is also a category error that predates this row: ipex_specs
        # says plainly "IPEx uses the small..medium range; the large drum is the RASSOR 2.0 drum", so the
        # IPEx RDS envelope never applied to it. test_viz2_dig_reaction.py ASSERTS the breach so it stays
        # visible; a spec mismatch you can see is worth more than one you cannot.
        self._vehicle_capacity_kg = 2.0 * self._drum_capacity_kg
        # [REQ:PX-11] The excavation FOOTPRINT is a PHYSICAL dimension -- the drum's width -- not a cell
        # count. It used to be a fixed `dig_half_cells=6`, so the operator's "cell size" toggle (a RENDER
        # resolution choice on the setup page) silently resized the excavator: a 13x13 box is 0.650 m at
        # 5 cm but 0.260 m at 2 cm, so the SAME dig command on the SAME terrain moved 7.1x more mass at the
        # coarser setting, and neither box was the drum's real width -- while `_dig_fee` billed the pass
        # with width_m = the REAL drum width. Cut geometry and energy model described different tools (the
        # PX-09 class of contradiction, one level out). Derive the closest odd cell box to the drum width
        # so the machine is the same machine at every resolution. An explicit dig_half_cells still wins.
        if dig_half_cells is None:
            cell = float(self.ws.fine_cell_m)
            self.dig_half_cells = max(1, int(round((self._drum_width_m / cell - 1.0) / 2.0)))
        else:
            self.dig_half_cells = int(dig_half_cells)
        # [REQ:PX-12] The DUMP is metered by the drum's own scoops -- the mirror of the bounded dig. It used
        # to call `ws.dump(mask)` with NO kg, which discharges the ENTIRE ledger in a single frame: up to
        # 24.98 kg teleporting onto a 0.35 m box in one tick, after which the sandpile relax spread the
        # resulting mound. A bucket drum cannot do that; it EMPTIES the way it FILLS -- through its scoops,
        # a bite at a time. One pass of scoops carries what one dig pass cuts: the drum-width footprint
        # (PX-11) x the <=50% anti-bridging bite (PX-09, [BDSCALE]) x the in-situ density. The scoops carry
        # what they CUT, so RHO_SURFACE is the right density (RHO_SPOIL equals it here anyway -- bulking
        # arises from the RHO_DEEP->spoil gap, not from a lighter spoil). ASSUMPTION, stated: a discharge
        # pass carries what a dig pass carries, because it is the same scoops turning the other way; the
        # GEOMETRY it rests on is sourced. Measured (5 cm cell): small 0.39 / medium 1.40 / large 3.81 kg
        # -> 9.8 / 5.2 / 6.6 metered passes to empty. (Passes-to-empty is not monotonic in drum size: the
        # footprint quantises to whole cells (PX-11), so the small drum's box is proportionally smaller
        # relative to its hold. The quantum FALLS OUT of the geometry; it is not tuned.) So a berm is now
        # built by passes you can PLAN, COST and LEARN from, not by one instantaneous mound.
        _side_m = (2 * self.dig_half_cells + 1) * float(self.ws.fine_cell_m)
        self._max_discharge_per_pass_kg = (
            _side_m * _side_m * self._max_cut_per_pass_m * float(K.RHO_SURFACE))
        self._drum_full = False                  # telemetry: the operator must dump/haul before digging on
        # [REQ:PX-10] the front arm is a PHYSICAL DOF, not a render pose: this is the operator's manual
        # offset on the dig posture (0 == ARM_DIG_DOWN == drum in the ground), and it GATES the cut, so a
        # rover with its drum raised for transport carves nothing. Clamped to the render rig's travel.
        self._arm_front_offset_rad = 0.0
        self._arm_back_offset_rad = 0.0
        # [REQ:TR-01] the Golombek rock draw. This used to be HARDCODED to 0 in _seed_rockfield while
        # the stream's `world_seed` config only reached the PROCEDURAL bundle path -- so on a real
        # site the seed was a dead knob. A frozen scenario must DECLARE its rock field (and be able to
        # vary it for domain randomisation), so the seed is now live. Default 0 => byte-identical to
        # every world produced before this change.
        self.rock_seed = int(rock_seed)
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
        # [REQ:PX-09] the drum's sourced hold + how full it is. Without this the operator has no way to know
        # WHY digging stopped -- the dig simply refuses once the drum is full (fill -> stop -> haul).
        telem["drum_capacity_kg"] = float(self._drum_capacity_kg)
        telem["drum_fill_frac"] = float(min(1.0, self.ws.inventory_kg / self._drum_capacity_kg)) \
            if self._drum_capacity_kg > 0.0 else 0.0
        telem["drum_full"] = bool(self._drum_full)                      # -> dump/haul before digging on
        telem["max_cut_per_pass_m"] = float(self._max_cut_per_pass_m)   # the <=50%-scoop anti-bridging bite cap
        telem.update(self._sensor_telem())                             # [REQ:PX-14] drum current + inferred + offload
        # [REQ:PX-10] the arm is authoritative state now, so publish it: the operator must be able to see
        # that the drum is raised (engagement 0) and that is WHY a dig command carved nothing.
        telem["arm_front_offset_rad"] = float(self._arm_front_offset_rad)
        telem["arm_back_offset_rad"] = float(self._arm_back_offset_rad)
        telem["dig_engagement"] = float(self._arm_engagement())         # 0 = drum up (no cut) .. 1 = dig posture
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
            elif cmd == "arm":
                # [REQ:PX-10] the render rig's arm pose is now AUTHORITATIVE state: it gates the dig.
                self._ingest_arm(msg)
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

    def _ingest_arm(self, msg: dict) -> None:
        """[REQ:PX-10] Adopt the operator's arm pose (rad offsets on the dig posture). Bounds-checked at
        ingest like the twist (M-04): the arm command arrives from a PUBLIC console, so a non-finite angle
        is REFUSED outright (never applied) and a wild one clamps to the render rig's travel -- neither may
        license a deeper cut than the rig can physically reach."""
        for key, attr in (("front", "_arm_front_offset_rad"), ("back", "_arm_back_offset_rad")):
            if key not in msg:
                continue
            raw = msg.get(key)
            if not (isinstance(raw, (int, float)) and math.isfinite(raw)):
                self._rejected_bounds += 1
                continue                                   # poisoned angle: keep the last good pose
            setattr(self, attr, max(ARM_OFFSET_MIN_RAD, min(ARM_OFFSET_MAX_RAD, float(raw))))

    def _arm_engagement(self, which: str = "front") -> float:
        """[REQ:PX-10/PX-13] 0.0 (drum out of the ground -> no cut) .. 1.0 (dig posture -> the full bite).

        PX-10 made the FRONT arm authoritative; the BACK arm stayed a DEAD DOF -- set, ingested from the
        operator, published as telemetry, and never read by physics. Each arm now gates ITS OWN drum, so
        stowing one removes that drum's mass AND breaks the counter-rotating cancellation (the reaction must
        go to ~0 for the RIGHT reason -- two drums actually cutting -- never because a term was zeroed)."""
        return dig_engagement(self._arm_front_offset_rad if which == "front" else self._arm_back_offset_rad)

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
            mod = _rockfield_module()
            cell = self.ws.base_cell_m
            bw, bh = self.ws.base.width, self.ws.base.height
            n = max(8, min(int(round(140.0 / cell)), bw, bh))
            c0 = int(min(max(0, round((self.start_xy[0] - self.ws.world_x0) / cell - n / 2)), bw - n))
            r0 = int(min(max(0, round((self.start_xy[1] - self.ws.world_y0) / cell - n / 2)), bh - n))
            result = mod.build_clasts(bundle_dir, r0, c0, n, d_min_m=0.15, d_max_m=0.8,
                                      world_seed=self.rock_seed)   # [REQ:TR-01] was hardcoded 0
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

    def _drum_rc(self, which: str = "front") -> tuple[int, int] | None:
        """[REQ:PX-13] Fine-window (row,col) of a bucket drum's contact patch. The FRONT drum sits ~0.4 m
        AHEAD of the pose along the travel heading and the BACK drum ~0.4 m BEHIND it -- two separate patches
        straddling the chassis, which is what the real vehicle has and why its reactions can cancel. Either
        way the worked patch stays out from under the rover body, so the trench/berm reads.
        yaw: 0=+x, +pi/2=+y (worksite convention)."""
        if self.ws.pose_xy is None:
            return None
        ahead = DRUM_OFFSET_M if which == "front" else -DRUM_OFFSET_M
        dx = ahead * math.cos(self.ws.yaw)
        dy = ahead * math.sin(self.ws.yaw)
        rc = self.ws.active_rc_for_xy((self.ws.pose_xy[0] + dx, self.ws.pose_xy[1] + dy))
        return int(round(rc[0])), int(round(rc[1]))

    @property
    def _drum_sensor(self) -> DrumSensor:
        """[REQ:PX-14] The drum-current SENSOR, wired into the runtime at last -- it lived in
        `rassor_mass_model` (the sourced FDC model, NTRS 20210022781) and the runtime never exposed it. It
        turns the conserved true drum mass into the motor-current reading a real rover would draw (no load
        cell), and infers the mass back with the published band. Lazily built (once) and cached; the inverse
        is calibrated across the vehicle's own hold, noise OFF (deterministic)."""
        s = getattr(self, "_drum_sensor_cache", None)
        if s is None:
            s = DrumSensor.calibrated(
                [f * self._vehicle_capacity_kg for f in (0.0, 0.25, 0.5, 0.75, 1.0)],
                capacity_kg=self._vehicle_capacity_kg)
            self._drum_sensor_cache = s
        return s

    def _sensor_telem(self) -> dict:
        """[REQ:PX-14] The drum-current OBSERVABLE, as the runtime now exposes it: the current a real rover
        would read (no load cell) from the conserved true drum mass, the mass inferred back from it, and the
        offload decision on the UPPER confidence bound. These are the closed loop's inputs -- and were
        missing entirely; the sourced FDC model sat in `rassor_mass_model` with nothing wired to it."""
        true_kg = float(self.ws.inventory_kg)
        current_a = float(self._drum_sensor.current(true_kg))
        inferred_kg = float(self._drum_sensor.infer(current_a))
        offload = bool(self._drum_sensor.offload(inferred_kg).offload)
        return {"drum_current_a": current_a, "drum_mass_inferred_kg": inferred_kg,
                "should_offload": offload}

    def autodig_trench(self, target_kg_per_pass: float, *, max_passes: int = 200,
                       noise_frac: float = 0.0, seed: int = 0) -> dict:
        """[REQ:PX-14] AutoDig-equivalent CLOSED-LOOP trench: regulate the per-pass bite to a target
        ingestion, read through the drum-current OBSERVABLE, and stop on drum-full via the sourced offload
        trigger. Actor-thread only (it mutates the conserved world).

        THE LOOP. The open-loop dig cuts the maximum allowed bite every pass. AutoDig instead holds a target
        ingestion: each pass it reads the drum current (with the FDC noise band, if enabled), infers the
        mass, and -- BEFORE biting -- asks `should_offload`; if the UPPER confidence bound has reached
        capacity it stops, so it never overfills even when the sensor is uncertain. Otherwise it takes a
        regulated bite, measures what it actually ingested THROUGH THE SENSOR (not the conserved truth, which
        a real rover cannot see), and corrects the next depth.

        THE CONTROL LAW, and its honest [CALIB]. `k = ingested / d_eff` is the terrain response learned each
        pass (kg per metre of bite); the next depth moves toward the target by `damping * error / k`. The
        DAMPING is the [CALIB] gain -- AutoDig's PID gains are not published, so the number is ours and the
        acceptance is on the BEHAVIOUR (the ingestion tracks the setpoint, a different setpoint gives a
        different bite, it stops on full), never on reproducing NASA's gains. The bite stays inside every
        sourced bound: `_apply_dig` still enforces PX-09 (the <=50% anti-bridging cap + capacity), PX-10 (the
        arm gate), PX-13 (the two-drum reaction). NOTE the sim's density is UNIFORM, so this does NOT model
        `denser -> shallower`; the regulation is against the target and the drum's fill, which are real.
        """
        _DAMPING = 0.7                                     # [CALIB] proportional gain (see the docstring)
        sensor = self._drum_sensor if noise_frac <= 0.0 else DrumSensor.calibrated(
            [f * self._vehicle_capacity_kg for f in (0.0, 0.25, 0.5, 0.75, 1.0)],
            capacity_kg=self._vehicle_capacity_kg, noise_frac=noise_frac, seed=seed)

        ingested: list[float] = []
        max_bite_kg = 0.0
        depth = self._max_cut_per_pass_m                   # start at the anti-bridging max, regulate DOWN
        terminated = False
        for _ in range(int(max_passes)):
            true_before = float(self.ws.inventory_kg)
            inferred_before = float(sensor.infer(sensor.current(true_before)))
            if sensor.offload(inferred_before).offload:    # UPPER-bound full -> stop before overfilling
                terminated = True
                break
            measured, depth, moved = self._autodig_pass(sensor, depth, target_kg_per_pass,
                                                        inferred_before, _DAMPING)
            if moved <= 1e-9:
                break                                      # nothing moved (arm stowed / no room): done
            ingested.append(measured)
            max_bite_kg = max(max_bite_kg, moved)

        return {"ingested_per_pass_kg": ingested, "n_passes": len(ingested),
                "terminated_on_offload": terminated,
                "max_pass_kg": max(ingested) if ingested else 0.0, "max_bite_kg": max_bite_kg}

    def _autodig_pass(self, sensor, depth: float, target: float, inferred_before: float,
                      damping: float) -> tuple[float, float, float]:
        """[REQ:PX-14] ONE regulated AutoDig pass: bite at ``depth`` (bounded per drum by PX-09/10/13),
        measure the ingestion THROUGH THE SENSOR (not the conserved truth), and return
        ``(measured_kg, next_depth_m, true_moved_kg)``. The next depth is a deadbeat-damped proportional
        step on the terrain response ``k = ingested / d_eff`` learned this pass (kg per metre of bite)."""
        true_before = float(self.ws.inventory_kg)
        self._apply_dig(depth_m=depth)
        true_after = float(self.ws.inventory_kg)
        moved = true_after - true_before
        measured = float(sensor.infer(sensor.current(true_after))) - inferred_before
        d_eff = min(depth, self._max_cut_per_pass_m)
        k = max(measured, 1e-6) / max(d_eff, 1e-6)
        next_depth = min(self._max_cut_per_pass_m,
                         max(0.0, depth + damping * (target - measured) / max(k, 1e-6)))
        return measured, next_depth, moved

    def _apply_dig(self, depth_m: float | None = None) -> list[list[int]]:
        """[REQ:PX-13] Conserved excavation with BOTH counter-rotating bucket drums (actor thread only).

        [REQ:PX-14] ``depth_m`` overrides the operator's commanded ``dig_depth_m`` for ONE pass, so the
        AutoDig controller can regulate the bite from feedback. ``None`` = the operator's depth (unchanged).

        The sim used to model HALF THE MACHINE: it cut with the FRONT drum alone and billed the chassis the
        full draft `F = tau/r`. That is the CORRECT answer for a single-drum dig -- and the WRONG VEHICLE.
        The real RASSOR/IPEx digs with both drums counter-rotating; per KSC-TOPS-7 their horizontal reactions
        are equal and OPPOSITE, so the pair nets ~0. In 1/6 g that cancellation is not an optimisation, it is
        the only way a 30 kg-class rover can react the digging force at all -- it simply lacks the weight to
        shove back. So the old model pushed the rover backward with a force the real machine is BUILT to
        cancel, and that false force flowed into traction, slip and energy on EVERY dig tick. It is a
        prerequisite for the training rows (PX-14, TR-02), not a polish item: a policy trained against it
        learns to compensate for a reaction that does not exist on the real vehicle.

        Each arm gates ITS OWN drum (PX-10 generalised: the back arm was a DEAD DOF -- set, ingested,
        telemetered, never read by physics). So the cancellation happens for the RIGHT REASON -- two drums
        actually cutting -- and stowing one restores the full draft rather than a zeroed term. The per-drum
        bounds (PX-09 anti-bridging + capacity, PX-11 footprint) are untouched; they now apply to each drum.

        Returns the dirty bboxes (one per engaged drum) or ``[]`` when nothing cut.
        """
        if self.ws.pose_xy is None:
            return []
        # Which drums are actually in the ground? Each arm gates its own.
        engaged: list[tuple[str, float, tuple[int, int]]] = []
        for which in ("front", "back"):
            e = self._arm_engagement(which)
            if e <= 0.0:
                continue                                     # drum out of the ground: nothing to cut
            drc = self._drum_rc(which)
            if drc is not None:
                engaged.append((which, e, drc))
        if not engaged:
            return []

        # [REQ:PX-09/PX-13] DRUM HOLD -- now the VEHICLE hold (two drums, [BDSCALE] capacity is PER DRUM).
        # A full vehicle refuses the bite (-> dump/haul); the room left is SHARED, and each drum's bite is
        # trimmed against what remains, so the ledger can never exceed capacity no matter how many drums cut.
        room_kg = self._vehicle_capacity_kg - float(self.ws.inventory_kg)
        self._drum_full = room_kg <= 0.0
        if self._drum_full:
            return []                                        # fill -> STOP -> haul: no mass leaves the grid

        dirty: list[list[int]] = []
        total_moved = 0.0
        total_energy_j = 0.0
        net_reaction_n = 0.0
        for which, engagement, (r, c) in engaged:
            cut = self._cut_one_drum(which, engagement, r, c, room_kg, depth_m=depth_m)
            if cut is None:
                continue
            dirty.append(cut["bbox"])
            total_moved += cut["moved_kg"]
            total_energy_j += cut["moved_kg"] * cut["j_per_kg"]
            # KSC-TOPS-7: the drums counter-rotate, so their horizontal reactions carry OPPOSITE signs and
            # the pair nets ~0. Summing the SIGNED per-drum drafts (rather than assuming they are equal) also
            # models PARTIAL cancellation honestly -- two drums cutting into different material do not cancel
            # exactly, and that residual is a real force the chassis feels.
            net_reaction_n += net_dig_reaction_n(
                cut["draft_n"] * self._drum_radius_m, self._drum_radius_m, drums=(which,))
            room_kg = self._vehicle_capacity_kg - float(self.ws.inventory_kg)   # the next drum sees the rest
            if room_kg <= 0.0:
                break

        if not dirty:
            return []
        self._drum_full = float(self.ws.inventory_kg) >= self._vehicle_capacity_kg - 1e-9
        self._last_dig_moved_kg = float(total_moved)
        self._last_dig_j_per_kg = float(total_energy_j / total_moved) if total_moved > 0.0 else 0.0
        self._dig_energy_j += float(total_energy_j)                    # E1: FEE-modulated dig energy debit
        reaction = abs(float(net_reaction_n))                          # magnitude the chassis must react
        self._last_dig_reaction_n = reaction
        self._active_dig_reaction_n = reaction                         # #2: the NEXT drive tick resists it
        self._dig_count += 1
        return dirty

    def _cut_one_drum(self, which: str, engagement: float, r: int, c: int,
                      room_kg: float, depth_m: float | None = None) -> dict | None:
        """[REQ:PX-13] ONE bucket drum's conserved pass: flatten its footprint-sized box, bounded by the
        SAME sourced limits as before (PX-09 anti-bridging + the shared hold, PX-10 the arm gate, PX-11 the
        drum-width footprint). Returns ``{bbox, moved_kg, j_per_kg, draft_n}`` or ``None`` if it cut nothing.

        This is the old single-drum `_apply_dig` body, extracted verbatim so the two drums cannot drift apart
        -- one implementation, driven twice."""
        H, W = self._window_shape
        hc = self.dig_half_cells
        r0, r1 = max(0, r - hc), min(H, r + hc + 1)
        c0, c1 = max(0, c - hc), min(W, c + hc + 1)
        if r1 <= r0 or c1 <= c0:
            return None
        f = self.ws._require_fine()
        # [REQ:PX-09] BOUND THE BITE by the drum's own sourced limits [BDSCALE] before touching the terrain.
        # (1) ANTI-BRIDGING: one pass may not cut deeper than 50% of the scoop opening. `_dig_fee` already
        #     clamped ITS characteristic depth to this, so leaving the CUT uncapped meant the terrain gave up
        #     a deeper bite than the one being billed -- and the McKyes/Reece FEE rises with depth^2, so dig
        #     energy was UNDERSTATED exactly when the cut was worst. Cap the cut, and the two agree.
        # (2) DRUM HOLD: the vehicle carries a finite mass. A bite that would overfill is trimmed to the room
        #     left, so the ledger can never exceed capacity.
        # [REQ:PX-10] ARM GATE: this drum can only cut what ITS arm's posture lets it reach (`engagement`).
        d_cmd = float(self.dig_depth_m if depth_m is None else depth_m)   # [REQ:PX-14] AutoDig may override
        d_eff = min(d_cmd, self._max_cut_per_pass_m) * engagement

        mask = np.zeros((H, W), dtype=bool)
        mask[r0:r1, c0:c1] = True
        height = f.derive_height()
        sub_h = height[r0:r1, c0:c1]
        sub_rho = f.density[r0:r1, c0:c1]
        cell_m = float(self.ws.fine_cell_m)
        cell_area = cell_m * cell_m
        # [REQ:PX-09] ONE {dig} is ONE PASS, and the anti-bridging rule bounds the DEEPEST bite entering the
        # scoop. `flatten` cuts every masked cell down to `target`, so a cell standing PROUD of the box drops
        # by (its relief above the cut level) -- which means anchoring the level to the box MINIMUM lets a
        # proud cell give up (relief + d_eff), silently exceeding the cap on any uneven ground. Anchor to the
        # box MAXIMUM instead: the deepest per-cell bite is then exactly d_eff, the cap actually binds
        # per-cell, and a pass SHAVES the high spots (repeat passes progressively deepen the rut) -- which is
        # what a bucket drum at a fixed cutting level physically does. (This flaw hid behind the drum-capacity
        # trim while the footprint was an oversized cell-count box; PX-11 shrank it to the real drum and
        # exposed it.)
        target = float(sub_h.max()) - d_eff

        def _mass_above(t: float) -> float:
            """kg the cut WOULD remove at level ``t`` (height identity: dz * density * area). An UPPER bound
            on what actually moves -- `cut_to_inventory` additionally clamps each cell at its firm DEM datum
            -- so trimming against this can never overfill the drum, only under-fill it."""
            return float(np.sum(np.clip(sub_h - t, 0.0, None) * sub_rho) * cell_area)

        if _mass_above(target) > room_kg:
            # Raise the cut level until the bite fits the room left (mass is monotone-decreasing in t).
            lo, hi = target, float(sub_h.max())
            for _ in range(48):
                mid = 0.5 * (lo + hi)
                if _mass_above(mid) > room_kg:
                    lo = mid
                else:
                    hi = mid
            target = hi
        moved = float(self.ws.flatten(mask, target))         # cells above target -> cut (conserved)
        if moved <= 0.0:
            return None
        # ONE FEE solve per drum -> the depth^2/density-dependent per-kg energy (council #1) AND this drum's
        # RAW horizontal draft (council #2). The SIGN is applied by the caller via `net_dig_reaction_n`, so a
        # counter-rotating pair cancels and a lone drum does not.
        fee = self._dig_fee(r0, r1, c0, c1, moved, f)
        return {"bbox": [r0, c0, r1, c1], "moved_kg": moved,
                "j_per_kg": float(fee["j_per_kg"]), "draft_n": float(fee["draft_n"])}

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
        # [REQ:PX-13] Return the RAW draft. The SIGN belongs to the caller: `_apply_dig` sums
        # `net_dig_reaction_n(draft*r, r, drums=(which,))` over the ENGAGED drums, so a counter-rotating pair
        # cancels to ~0 (KSC-TOPS-7) while a lone drum still nets the full F = tau/r. Baking `abs(...front)`
        # in here was what made the sim model half the machine.
        draft_n = float(rep["draft_n"])
        reaction_n = abs(net_dig_reaction_n(draft_n * self._drum_radius_m, self._drum_radius_m,
                                            drums=("front",)))     # single-drum magnitude (legacy callers)
        return {"j_per_kg": j_per_kg, "reaction_n": reaction_n, "draft_n": draft_n}

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
        # [REQ:PX-12] METERED: one dump command is ONE PASS OF SCOOPS, not the whole ledger. The conserved
        # authority already took a `kg` -- the runtime simply never passed one, so the drum teleported its
        # entire load in a single frame. `WorkSite.dump` clamps to what the ledger actually holds, so the
        # last pass discharges the remainder and the drum drains monotonically to empty.
        placed = self.ws.dump(mask, kg=self._max_discharge_per_pass_kg)
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
