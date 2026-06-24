"""G1 blocker #1 slice 1: the PERSISTENT SHARED runtime (STEWIE P20's process core).

The criterion: world state outlives any single client. One long-lived RuntimeProcess owns the
conserved ColumnState (+ the versioned twin); clients attach over a Unix socket (JSON lines),
declare a ROLE, and operate through the seam -- drive mutates the world, produce emits the strict
canonical packet, estimate/evaluate stay file-role-isolated (stewie.eval.roles). Two clients see
ONE world; disconnecting changes nothing; checkpoint/restore round-trips bit-exact.

The ROS bridge (B1) attaches later through this same seam -- one build, two tracks.
"""
import hashlib
import json
import os
import socket
import threading

import numpy as np
import pytest

from stewie.runtime import process as rp


@pytest.fixture()
def runtime(tmp_path):
    sock = str(tmp_path / "rt.sock")
    srv = rp.RuntimeProcess(grid=64, cell_m=0.02, body="moon", socket_path=sock, seed=3,
                            checkpoint_dir=str(tmp_path / "ckpt"))
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    # S-09: wait on the explicit readiness handshake -- the socket is bound, LISTENING, and chmod'd
    # 0600 before _ready fires, so no client below races the bound-but-not-yet-listening ECONNREFUSED
    # window (the prior os.path.exists(sock) poll could see the bind()-created node before listen()).
    assert srv.wait_ready(10.0), "runtime socket never became ready"
    yield sock, srv
    srv.shutdown()


def _rpc(sock_path, req):
    c = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    c.connect(sock_path)
    c.sendall((json.dumps(req) + "\n").encode())
    buf = b""
    while not buf.endswith(b"\n"):
        chunk = c.recv(65536)
        if not chunk:
            break
        buf += chunk
    c.close()
    return json.loads(buf.decode())


def test_world_is_shared_and_outlives_clients(runtime):
    sock, _ = runtime
    p0 = _rpc(sock, {"role": "drive", "cmd": "pose"})
    assert p0["ok"]
    for _ in range(5):
        r = _rpc(sock, {"role": "drive", "cmd": "twist", "v": 0.2, "omega": 0.0, "steps": 4})
        assert r["ok"]
    p1 = _rpc(sock, {"role": "produce", "cmd": "pose"})        # a DIFFERENT client connection
    assert (p1["rc"] != p0["rc"]), "client B must see the world client A changed"


def test_produce_emits_the_strict_canonical_packet(runtime):
    sock, _ = runtime
    _rpc(sock, {"role": "drive", "cmd": "twist", "v": 0.2, "omega": 0.1, "steps": 10})
    r = _rpc(sock, {"role": "produce", "cmd": "packet"})
    assert r["ok"]
    from stewie.bridge.runtime_io import parse_canonical
    parsed = parse_canonical(r["packet"])                      # the strict parser ACCEPTS it
    assert parsed["sequence_id"] == r["packet"]["sequence_id"]
    r2 = _rpc(sock, {"role": "produce", "cmd": "packet"})
    assert r2["packet"]["sequence_id"] > r["packet"]["sequence_id"]   # monotone across calls


def test_mutation_requires_the_drive_role(runtime):
    sock, _ = runtime
    r = _rpc(sock, {"role": "estimate", "cmd": "twist", "v": 0.2, "omega": 0.0, "steps": 1})
    assert not r["ok"] and "role" in r["error"].lower()


def test_world_conserves_mass_across_the_seam(runtime):
    sock, srv = runtime
    m0 = float(np.sum(srv.cs.mass_areal))
    _rpc(sock, {"role": "drive", "cmd": "twist", "v": 0.25, "omega": 0.2, "steps": 30})
    assert float(np.sum(srv.cs.mass_areal)) == pytest.approx(m0, rel=1e-12)


def test_checkpoint_restore_roundtrips(runtime, tmp_path):
    sock, srv = runtime
    _rpc(sock, {"role": "drive", "cmd": "twist", "v": 0.2, "omega": 0.3, "steps": 12})
    r = _rpc(sock, {"role": "drive", "cmd": "checkpoint", "path": "ck.npz"})   # #120: bare name only
    assert r["ok"] and os.path.exists(r["path"])
    pose_before = _rpc(sock, {"role": "drive", "cmd": "pose"})
    _rpc(sock, {"role": "drive", "cmd": "twist", "v": 0.3, "omega": 0.0, "steps": 8})
    r2 = _rpc(sock, {"role": "drive", "cmd": "restore", "path": "ck.npz"})
    assert r2["ok"]
    pose_after = _rpc(sock, {"role": "drive", "cmd": "pose"})
    assert pose_after["rc"] == pose_before["rc"]
    assert pose_after["mass_sha"] == pose_before["mass_sha"]   # bit-exact world restore


def test_packet_carries_real_imu_wheel_channels_after_motion(runtime):
    """Slice 2: motion feeds the REAL producer models; the packet's imu/wheel are OK and parse."""
    sock, _ = runtime
    _rpc(sock, {"role": "drive", "cmd": "twist", "v": 0.2, "omega": 0.1, "steps": 12})
    r = _rpc(sock, {"role": "produce", "cmd": "packet"})
    assert r["ok"]
    pkt = r["packet"]
    assert pkt["channels"]["imu"]["status"] == "OK"
    assert pkt["channels"]["wheel"]["status"] == "OK"
    from stewie.bridge.runtime_io import parse_canonical
    parsed = parse_canonical(pkt)                          # strict parse, truth-scan included
    assert len(parsed["imu"]) >= 12 and len(parsed["wheel"]) >= 12
    # encoder deltas reflect REAL motion (nonzero counts) and slip stays hidden
    assert any(any(c != 0 for c in s_["encoder_count_delta"])
               for s_ in pkt["channels"]["wheel"]["samples"])
    # a second packet drains the buffer: no double-reporting of the same samples
    r2 = _rpc(sock, {"role": "produce", "cmd": "packet"})
    assert r2["packet"]["channels"]["imu"]["status"] == "UNAVAILABLE"


def test_packet_power_channel_is_real_accounting(runtime):
    """Slice 3 / G1 #3: the power channel reports the twin's REAL energy accounting -- SoC falls
    monotonically with commanded work, draw equals the twin's drive power, nothing fabricated."""
    sock, srv = runtime
    r0 = _rpc(sock, {"role": "produce", "cmd": "packet"})
    _rpc(sock, {"role": "drive", "cmd": "twist", "v": 0.25, "omega": 0.0, "steps": 50})
    r1 = _rpc(sock, {"role": "produce", "cmd": "packet"})
    p1 = r1["packet"]["channels"]["power"]
    assert p1["status"] == "OK"
    s1 = p1["samples"][-1]
    assert 0.0 < s1["soc_frac"] < 1.0
    assert s1["power_w"] == pytest.approx(srv.twin.energy["drive_power_w"], rel=0.01)
    _rpc(sock, {"role": "drive", "cmd": "twist", "v": 0.25, "omega": 0.0, "steps": 50})
    r2 = _rpc(sock, {"role": "produce", "cmd": "packet"})
    s2 = r2["packet"]["channels"]["power"]["samples"][-1]
    assert s2["soc_frac"] < s1["soc_frac"]               # work drains the pack
    # the strict parser accepts the full packet with the power channel OK
    from stewie.bridge.runtime_io import parse_canonical
    parse_canonical(r2["packet"])
    # idle packet: power still reports (the BMS always answers), draw 0
    r3 = _rpc(sock, {"role": "produce", "cmd": "packet"})
    s3 = r3["packet"]["channels"]["power"]["samples"][-1]
    assert s3["power_w"] == 0.0 and s3["soc_frac"] == pytest.approx(s2["soc_frac"])
    assert r0["ok"]


def test_camera_channel_attaches_real_frames(tmp_path):
    """Final G1 slice: with a frame store, the packet's camera channel references REAL rendered
    frames (the g2cal pose artifacts) and the whole packet passes the strict parser."""
    import os
    store = os.path.join(os.path.dirname(rp.__file__), "..", "eval", "validation",
                         "g2cal", "pose_0")
    if not os.path.isdir(store):
        pytest.skip("g2cal evidence not present")
    srv = rp.RuntimeProcess(grid=48, cell_m=0.02, body="moon",
                            socket_path=str(tmp_path / "s.sock"), seed=5,
                            frame_store=os.path.abspath(store))
    srv.handle({"role": "drive", "cmd": "twist", "v": 0.2, "omega": 0.0, "steps": 5})
    pkt = srv.handle({"role": "produce", "cmd": "packet"})["packet"]
    cam = pkt["channels"]["camera"]
    assert cam["status"] == "OK" and cam["reference_camera"] == "front_left"
    assert cam["baseline_m"] > 0
    names = {f["name"] for f in cam["frames"]}
    assert {"front_left", "front_right"} <= names
    for f in cam["frames"]:
        assert os.path.exists(f["path"]), f["path"]        # the frames are REAL files
    from stewie.bridge.runtime_io import parse_canonical
    parsed = parse_canonical(pkt)
    assert parsed["camera_frames"]


def test_all_eight_cameras_in_the_packet(tmp_path):
    """T3.1 (Navigation): the full documented rig flows -- all 8 cameras with per-camera intrinsics
    from the frame store's own producer file; the packet still passes the strict parser."""
    import os
    store = os.path.join(os.path.dirname(rp.__file__), "..", "eval", "validation",
                         "g2cal", "pose_0")
    if not os.path.isdir(store):
        pytest.skip("g2cal evidence not present")
    srv = rp.RuntimeProcess(grid=48, cell_m=0.02, body="moon",
                            socket_path=str(tmp_path / "s.sock"), seed=5,
                            frame_store=os.path.abspath(store))
    srv.handle({"role": "drive", "cmd": "twist", "v": 0.2, "omega": 0.0, "steps": 3})
    pkt = srv.handle({"role": "produce", "cmd": "packet"})["packet"]
    cam = pkt["channels"]["camera"]
    names = {f["name"] for f in cam["frames"]}
    assert names == {"front_left", "front_right", "rear_left", "rear_right",
                     "left_mono", "right_mono", "drum_front_cam", "drum_back_cam"}
    for f in cam["frames"]:
        assert os.path.exists(f["path"])                  # every frame is a REAL file
    intr = cam["intrinsics_by_camera"]
    assert set(intr) == names and all(intr[n]["fx"] > 0 for n in names)
    from stewie.bridge.runtime_io import parse_canonical
    assert parse_canonical(pkt)["camera_frames"]


def test_t34_camera_thermal_gating(tmp_path):
    """Navigation T3.4: below the DOCUMENTED camera floor (0 C TVAC, SCHULER24 pp.28-29) the camera
    channel reports UNAVAILABLE reason=thermal -- polar-night perception planning becomes honest.
    The avionics keep running (imu/wheel/power unaffected)."""
    import os
    store = os.path.join(os.path.dirname(rp.__file__), "..", "eval", "validation",
                         "g2cal", "pose_0")
    if not os.path.isdir(store):
        pytest.skip("g2cal evidence not present")
    srv = rp.RuntimeProcess(grid=48, cell_m=0.02, body="moon",
                            socket_path=str(tmp_path / "s.sock"), seed=5,
                            frame_store=os.path.abspath(store))
    srv.handle({"role": "drive", "cmd": "twist", "v": 0.2, "omega": 0.0, "steps": 3})
    warm = srv.handle({"role": "produce", "cmd": "packet"})["packet"]
    assert warm["channels"]["camera"]["status"] == "OK"   # default temp: operational
    r = srv.handle({"role": "drive", "cmd": "set_thermal", "camera_temp_c": -15.0})
    assert r["ok"]
    srv.handle({"role": "drive", "cmd": "twist", "v": 0.2, "omega": 0.0, "steps": 3})
    cold = srv.handle({"role": "produce", "cmd": "packet"})["packet"]
    cam = cold["channels"]["camera"]
    assert cam["status"] == "UNAVAILABLE" and "thermal" in cam.get("reason", "")
    assert cold["channels"]["imu"]["status"] == "OK"      # avionics unaffected (wider qual)
    from stewie.bridge.runtime_io import parse_canonical
    parse_canonical(cold)                                 # still a strictly valid packet


def test_t51_heaters_own_the_camera_window(tmp_path):
    """Navigation T5.1 (corrected en route): the naive sun-equilibrium model PROVED that grazing polar
    sun (max el ~1.6 deg at Haworth) can never passively hold the 0..50 C window -- so, per the
    TRL5 TVAC/heater design, the HEATERS own it while the pack can power them. Powered: camera OK
    at any sun. Pack below the shed reserve: housing falls cold, the TVAC gate fires. Manual
    set_thermal still overrides."""
    import os
    store = os.path.join(os.path.dirname(rp.__file__), "..", "eval", "validation",
                         "g2cal", "pose_0")
    if not os.path.isdir(store):
        pytest.skip("g2cal evidence not present")
    srv = rp.RuntimeProcess(grid=48, cell_m=0.02, body="moon",
                            socket_path=str(tmp_path / "s.sock"), seed=5,
                            frame_store=os.path.abspath(store), sun_thermal=True)
    assert srv.camera_temp_c == srv.THERMAL_T_HEATED_C    # powered: in the window, any sun
    srv.handle({"role": "drive", "cmd": "twist", "v": 0.2, "omega": 0.0, "steps": 3})
    assert srv.handle({"role": "produce", "cmd": "packet"})["packet"]["channels"]["camera"][
        "status"] == "OK"
    srv.energy_used_j = srv.battery_capacity_j * 0.95     # drain past the heater-shed reserve
    srv.handle({"role": "drive", "cmd": "twist", "v": 0.2, "omega": 0.0, "steps": 1})
    cam = srv.handle({"role": "produce", "cmd": "packet"})["packet"]["channels"]["camera"]
    assert cam["status"] == "UNAVAILABLE" and "thermal" in cam["reason"]
    srv.handle({"role": "drive", "cmd": "set_thermal", "camera_temp_c": 15.0})
    srv.handle({"role": "drive", "cmd": "twist", "v": 0.2, "omega": 0.0, "steps": 1})
    assert srv.handle({"role": "produce", "cmd": "packet"})["packet"]["channels"]["camera"][
        "status"] == "OK"


def _raw_rpc(sock_path, raw_bytes):
    """Send raw (possibly malformed/over-cap) bytes that _rpc's json.dumps could never produce, and
    read whatever response comes back. Tolerant of the server rejecting + closing mid-send."""
    c = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    c.settimeout(5.0)                                  # an UNBOUNDED server readline must fail, not hang
    c.connect(sock_path)
    try:
        c.sendall(raw_bytes)
    except (BrokenPipeError, ConnectionResetError, OSError):
        pass                                          # server may reject + close before the send finishes
    buf = b""
    try:
        while not buf.endswith(b"\n"):
            chunk = c.recv(65536)
            if not chunk:
                break
            buf += chunk
    except (ConnectionResetError, OSError):
        pass
    c.close()
    return buf


def test_m03_overlong_line_is_rejected_not_oomed(runtime):
    """M-03: a multi-hundred-KB unterminated line is rejected with a clean error, not buffered to OOM."""
    sock, _ = runtime
    over = b"{" + b"a" * (256 * 1024)                 # 256 KiB, no newline -> over the 64 KiB cap
    resp = _raw_rpc(sock, over)
    assert resp.endswith(b"\n")
    parsed = json.loads(resp.decode())
    assert parsed["ok"] is False and "line" in parsed["error"].lower()


def test_m04_nonfinite_twist_is_rejected_and_world_untouched(runtime):
    """M-04: NaN/inf v must be refused and must NOT corrupt the shared persistent pose."""
    sock, srv = runtime
    p0 = _rpc(sock, {"role": "drive", "cmd": "pose"})
    for bad in (float("nan"), float("inf"), float("-inf")):
        r = _rpc(sock, {"role": "drive", "cmd": "twist", "v": bad, "omega": 0.0, "steps": 1})
        assert r["ok"] is False and "finite" in r["error"].lower()
    p1 = _rpc(sock, {"role": "drive", "cmd": "pose"})
    assert p1["rc"] == p0["rc"]                                   # world pose unchanged
    assert all(np.isfinite(x) for x in srv.rc) and np.isfinite(srv.yaw)


def test_m04_oversized_or_nonfinite_steps_is_rejected(runtime):
    """M-04: steps above the cap (and non-finite steps) are refused before the drive loop spins."""
    sock, _ = runtime
    r = _rpc(sock, {"role": "drive", "cmd": "twist", "v": 0.2, "omega": 0.0, "steps": 10**12})
    assert r["ok"] is False and "steps" in r["error"].lower()
    r2 = _rpc(sock, {"role": "drive", "cmd": "twist", "v": 0.2, "omega": 0.0, "steps": float("inf")})
    assert r2["ok"] is False and "steps" in r2["error"].lower()


def test_m05_socket_is_owner_only(runtime):
    """M-05: the world-mutating socket is created 0o600 (no group/other access)."""
    import stat
    sock, _ = runtime
    mode = stat.S_IMODE(os.stat(sock).st_mode)
    assert mode == 0o600, oct(mode)
    r = _rpc(sock, {"role": "drive", "cmd": "twist", "v": 0.2, "omega": 0.0, "steps": 1})
    assert r["ok"]                                                # same-user client still works


def test_checkpoint_rejects_path_traversal(runtime, tmp_path):
    """#120: checkpoint/restore are confined to the runtime checkpoint dir; an absolute path, a parent
    escape, or a subdir is rejected -- a socket client cannot write/read an arbitrary file. (Pre-fix the
    runtime did np.savez/np.load on the raw client path = arbitrary file write/read.)"""
    sock, _ = runtime
    probe = str(tmp_path / "escape_probe.npz")
    for bad in (probe, "../escape.npz", "/tmp/escape.npz", "sub/dir.npz"):
        r = _rpc(sock, {"role": "drive", "cmd": "checkpoint", "path": bad})
        assert r["ok"] is False, bad
        r2 = _rpc(sock, {"role": "drive", "cmd": "restore", "path": bad})
        assert r2["ok"] is False, bad
    assert not os.path.exists(probe)                 # nothing written outside the checkpoint dir


def test_s09_first_observable_socket_mode_is_0600(tmp_path, monkeypatch):
    """S-09: the FIRST observable mode of the socket is 0600 -- the node is BORN owner-only (bound
    under a restrictive umask), not created world/group-accessible and tightened afterward. We
    capture the mode at the very first os.chmod call (i.e. the bind-created mode, before any
    tightening). Pre-fix, bind ran under the process umask (0o022 here -> 0o755 node), so this mode
    is 0o755 = RED. Also: the FIRST accepted connection (gated on the ready handshake) succeeds."""
    import stat
    sock = str(tmp_path / "first.sock")
    os.umask(0o022)                                  # a permissive process umask, the realistic case
    observed = {}
    real_chmod = os.chmod

    def _spy_chmod(path, mode, *a, **k):
        # the mode of the node AS BORN BY bind(), recorded before the runtime tightens it
        if str(path) == sock and "born" not in observed:
            observed["born"] = stat.S_IMODE(os.stat(path).st_mode)
        return real_chmod(path, mode, *a, **k)

    monkeypatch.setattr(os, "chmod", _spy_chmod)
    srv = rp.RuntimeProcess(grid=32, cell_m=0.02, body="moon", socket_path=sock, seed=1,
                            checkpoint_dir=str(tmp_path / "ckpt"))
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        assert srv.wait_ready(10.0), "socket never became ready"
        assert observed.get("born") == 0o600, oct(observed.get("born", -1))  # born 0600, not tightened
        assert stat.S_IMODE(os.stat(sock).st_mode) == 0o600                  # and stays 0600
        # the FIRST accepted connection succeeds (no bound-but-not-listening race once ready)
        r = _rpc(sock, {"role": "drive", "cmd": "pose"})
        assert r["ok"]
    finally:
        srv.shutdown()


def test_a01_checkpoint_restore_is_bit_exact_and_complete(runtime):
    """A-01: a COMPLETE checkpoint. Advance EVERY subsystem (pose, clock, energy, thermal flag, the
    buffered proprioception samples, the IMU/wheel RNG+biases), checkpoint, then mutate every one of
    those, then restore -- and require the runtime is bit-identical: not just rc/mass but t_sim and
    energy_used_j AND the NEXT command output AND the NEXT packet output (which drains the buffered
    samples through the restored RNG state). Pre-fix the checkpoint stored only mass/pose/yaw/seq, so
    t_sim/energy/buffers/RNG diverged and the next packet differed."""
    sock, srv = runtime
    # advance: drive (pose+clock+energy+slip), buffer samples, set a manual thermal override
    _rpc(sock, {"role": "drive", "cmd": "twist", "v": 0.25, "omega": 0.2, "steps": 17})
    _rpc(sock, {"role": "drive", "cmd": "set_thermal", "camera_temp_c": 12.5})
    _rpc(sock, {"role": "drive", "cmd": "twist", "v": 0.1, "omega": -0.05, "steps": 6})

    # snapshot the full live state for a field-by-field comparison after restore
    def snap():
        return dict(
            rc=tuple(srv.rc), yaw=float(srv.yaw), t_sim=float(srv.t_sim),
            sequence=int(srv.sequence), energy_used_j=float(srv.energy_used_j),
            draw_w=float(srv._draw_w), camera_temp_c=float(srv.camera_temp_c),
            manual_thermal=bool(srv._manual_thermal),
            drum_inventory=float(srv.cs.drum_inventory),
            mass_sum=float(np.sum(srv.cs.mass_areal)),
            mass_sha=hashlib.sha256(srv.cs.mass_areal.tobytes()).hexdigest(),
            n_imu_buf=len(srv._imu_buf), n_wheel_buf=len(srv._wheel_buf),
            gyro_bias=float(srv._imu_model._gyro_bias),
            wheel_seq=int(srv._imu_model._wheel_seq),
            rng=srv._imu_model.rng.bit_generator.state["state"]["state"],
        )

    before = snap()
    # extensionless name must round-trip (save/restore agree on one on-disk path)
    r = _rpc(sock, {"role": "drive", "cmd": "checkpoint", "path": "snapshot"})
    assert r["ok"] and r["path"].endswith("snapshot.npz") and os.path.exists(r["path"])

    # mutate EVERY advanced subsystem so a partial restore would be caught
    _rpc(sock, {"role": "drive", "cmd": "twist", "v": 0.3, "omega": 0.4, "steps": 9})
    _rpc(sock, {"role": "drive", "cmd": "set_thermal", "camera_temp_c": -40.0})
    _rpc(sock, {"role": "produce", "cmd": "packet"})   # drains buffers, bumps sequence, advances draw
    after_mut = snap()
    assert after_mut != before                          # the mutation really moved the state

    # restore by the SAME extensionless name -- must report a checkpoint (not "no checkpoint")
    r2 = _rpc(sock, {"role": "drive", "cmd": "restore", "path": "snapshot"})
    assert r2["ok"], r2

    restored = snap()
    assert restored == before, (
        "restore is not bit-exact/complete; diff: "
        + str({k: (before[k], restored[k]) for k in before if before[k] != restored[k]}))

    # the NEXT packet must be byte-identical to what it would have been from `before` -- this exercises
    # the restored buffered samples drained through the restored RNG/bias state.
    pkt_restored = _rpc(sock, {"role": "produce", "cmd": "packet"})["packet"]
    # independently reproduce: a SECOND runtime restored from the same file emits the same next packet
    twin_srv = rp.RuntimeProcess(grid=64, cell_m=0.02, body="moon",
                                 socket_path=str(srv.socket_path) + ".twin", seed=99,
                                 checkpoint_dir=srv.checkpoint_dir)
    assert twin_srv.handle({"role": "drive", "cmd": "restore", "path": "snapshot"})["ok"]
    pkt_twin = twin_srv.handle({"role": "produce", "cmd": "packet"})["packet"]
    assert json.dumps(pkt_restored, sort_keys=True) == json.dumps(pkt_twin, sort_keys=True)


def test_a01_restore_is_transactional_on_corruption(runtime):
    """A-01: a corrupt snapshot is rejected by the checksum and the LIVE world is left untouched
    (transactional restore -- no half-mutated state)."""
    sock, srv = runtime
    _rpc(sock, {"role": "drive", "cmd": "twist", "v": 0.2, "omega": 0.1, "steps": 8})
    r = _rpc(sock, {"role": "drive", "cmd": "checkpoint", "path": "ck.npz"})
    assert r["ok"]
    # advance the live world AFTER the checkpoint, snapshot it
    _rpc(sock, {"role": "drive", "cmd": "twist", "v": 0.3, "omega": 0.0, "steps": 5})
    live_rc = tuple(srv.rc); live_t = float(srv.t_sim); live_e = float(srv.energy_used_j)
    # corrupt the checkpoint file's bytes (flip the tail) -> checksum must fail
    with open(r["path"], "r+b") as fh:
        fh.seek(-16, os.SEEK_END)
        tail = fh.read(16)
        fh.seek(-16, os.SEEK_END)
        fh.write(bytes((b ^ 0xFF) for b in tail))
    r2 = _rpc(sock, {"role": "drive", "cmd": "restore", "path": "ck.npz"})
    assert r2["ok"] is False and ("checksum" in r2["error"] or "failed" in r2["error"])
    # the live world is UNCHANGED (no partial restore)
    assert tuple(srv.rc) == live_rc and float(srv.t_sim) == live_t
    assert float(srv.energy_used_j) == live_e
