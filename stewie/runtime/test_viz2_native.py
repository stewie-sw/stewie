"""Real Haworth runtime checks over authenticated localhost sockets.

Native SfS heights are measured inputs. Soil and drivetrain responses remain model assumptions.
The existing real-socket Client is reused without replacing runtime implementations.
"""
from pathlib import Path
import inspect
import json
import math
import time

import pytest

from stewie.runtime.test_viz2_runtime import Client
from stewie.runtime.viz2_runtime import Viz2Runtime
from stewie.specs.ipex_specs import DRIVE_SPEED_MS

BUNDLE = Path(__file__).resolve().parents[2] / "samples/lunar_dem/haworth_sfs_2km_1m"


def exercise_native_feedback(session_dir):
    metadata = json.loads((BUNDLE / "metadata.json").read_text())
    bounds = metadata["world_bounds_m"]
    start = ((bounds["x0"] + bounds["x1"]) / 2, (bounds["y0"] + bounds["y1"]) / 2)
    assert Path(inspect.getfile(Viz2Runtime)).resolve().parent == Path(__file__).resolve().parent
    frames = []
    with Viz2Runtime(str(BUNDLE), session_dir=str(session_dir), start_xy=start) as rt:
        assert rt.wait_ready(10)
        client = Client(rt.port)
        try:
            assert client.handshake(rt.token)["ok"]
            first_pose = rt.ws.pose_xy
            refresh_until = time.monotonic() + 1.0
            last_command = None
            while time.monotonic() < refresh_until:
                client.twist(DRIVE_SPEED_MS / 2, 0.0)
                last_command = time.monotonic()
                frame = client._recv_one()
                assert "seq" in frame, frame
                frames.append(frame)
                client.ack(frame["seq"])
            assert math.dist(first_pose, rt.ws.pose_xy) > 0
            deadline = time.monotonic() + rt.ack_deadline_s + 2
            reason = None
            while time.monotonic() < deadline:
                frame = client._recv_one()
                if frame.get("type") == "safe_stop":
                    reason = frame["reason"]
                    break
                frames.append(frame)
                client.ack(frame["seq"])
            expired_after = time.monotonic() - last_command
            assert reason == "command_expired", reason
            stopped_pose = rt.ws.pose_xy
            client.twist(DRIVE_SPEED_MS / 2, 0.0)
            time.sleep(3 * rt.dt)
            assert rt.ws.pose_xy == stopped_pose
            assert rt._safe_stopped
        finally:
            client.close()

        refused, reason = _exercise_reconnection(rt, metadata)
    first, last = frames[0], frames[-1]
    sim_elapsed = last["payload"]["telem"]["simulation_t_s"] - first["payload"]["telem"]["simulation_t_s"]
    wall_elapsed = last["t"] - first["t"]
    return {"runtime_source": inspect.getfile(Viz2Runtime), "native_cell_m": rt.ws.fine_cell_m,
            "acknowledged_frames": len(frames), "simulation_elapsed_s": sim_elapsed,
            "wall_elapsed_s": wall_elapsed, "simulation_wall_ratio": sim_elapsed / wall_elapsed,
            "command_expiry_observed_s": expired_after, "command_expiry_reason": "command_expired",
            "feedback_loss_reason": reason, "coarse_excavation": refused,
            "distance_before_command_expiry_m": math.dist(first_pose, stopped_pose),
            "mass_residual_kg": rt.ws.conservation_residual(),
            "scope": "Actual CPU actor and authenticated transport; no renderer, learned policy, or hardware qualification."}


def _exercise_reconnection(rt, metadata):
    # Recovery requires a new authenticated session, not a late command on the old epoch.
    client = Client(rt.port)
    try:
        assert client.handshake(rt.token)["ok"]
        client._send({"cmd": "dig"})
        refused = None
        for _ in range(10):
            frame = client._recv_one()
            if frame.get("type") == "command_refused":
                refused = frame
                break
            client.ack(frame["seq"])
        assert refused is not None and refused["cmd"] == "dig"
        assert rt.ws.cut_total_kg == 0
        # Keep commands fresh while withholding acknowledgments: telemetry liveness is separate.
        reason = None
        deadline = time.monotonic() + rt.ack_deadline_s + 2
        while time.monotonic() < deadline:
            client.twist(DRIVE_SPEED_MS / 2, 0.0)
            frame = client._recv_one()
            if frame.get("type") == "safe_stop":
                reason = frame["reason"]
                break
        assert reason == "deadman_link_stall", reason
        disconnected_pose = rt.ws.pose_xy
        time.sleep(3 * rt.dt)
        assert rt.ws.pose_xy == disconnected_pose
        assert rt.ws.clasts == metadata["clasts"]
        rt.ws._require_fine().check_invariants()
        assert abs(rt.ws.conservation_residual()) < 1e-8
    finally:
        client.close()
    return refused, reason


def test_native_feedback_liveness_and_recovery(tmp_path):
    exercise_native_feedback(tmp_path)


def test_runtime_refuses_generated_refinement(tmp_path):
    with pytest.raises(ValueError, match="native DEM resolution"):
        Viz2Runtime(str(BUNDLE), session_dir=str(tmp_path), fine_cell_m=0.05)


def test_runtime_refuses_mismatched_clock(tmp_path):
    with pytest.raises(ValueError, match="dt =="):
        Viz2Runtime(str(BUNDLE), session_dir=str(tmp_path), rate_hz=15, dt=0.1)


if __name__ == "__main__":
    import sys
    print(json.dumps(exercise_native_feedback(Path(sys.argv[1])), indent=2))
