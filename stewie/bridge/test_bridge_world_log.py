"""Step 4 (gap W2): the bridge's command/odom/watchdog path feeds the SAME world-state log as the SIM
run -- so live telemetry, once on a ROS2 host, records canonical DT-01 transactions like every other
world transition.

The rclpy TRANSPORT is host-gated (no ROS2 Jazzy on this host -- the live node test elsewhere asserts
the gate). What IS testable without rclpy is the recording SEAM: drive the rclpy-free RcBridge through a
cmd_vel command, let the SF-01 watchdog trip on a stalled stream, convert the backend's command log to
ExecutionEvents, and commit them through the WorldStateService. The host-gated
``scripts/ros2_bridge/verify_live_bridge.py`` does the identical thing over the real ROS2 transport.
"""
from __future__ import annotations

import numpy as np

from stewie.bridge import rc_contract as RC
from stewie.bridge import ros2_bridge as B
from stewie.server.world_state import WorldStateService
from stewie.twin import versioned as vt


def _twin() -> vt.TwinStore:
    # plumbing fixture: never patched/read (only its identity is linked) -> zero base, no fabrication.
    return vt.TwinStore(np.zeros((32, 32), dtype=float), cell_m=0.5)


def test_session_events_one_event_per_command_safe_carries_cause():
    cmds = [RC.GoTo(leg_id=0, goal_row=0.0, goal_col=1.0, v_max_mps=0.3),
            RC.GoTo(leg_id=0, goal_row=0.0, goal_col=2.0, v_max_mps=0.3),
            RC.Safe(reason=RC.SAFE_REASON_WATCHDOG)]
    evs = B.bridge_session_events(cmds)
    assert [e.kind for e in evs] == ["command", "command", "safe"]
    assert evs[-1].outcome == "safed" and "watchdog" in evs[-1].detail.lower()


def test_operator_and_watchdog_safes_are_both_recorded_with_true_cause():
    """Regression (review B1): a near-zero twist yields Safe(OPERATOR), which the watchdog forwards to
    the backend. Every safe-stop must be recorded with its REAL reason -- an operator stop must not be
    dropped, and a watchdog trip must not be relabeled onto it. The audit log must be faithful."""
    cmds = [RC.GoTo(leg_id=0, goal_row=0.0, goal_col=1.0, v_max_mps=0.3),
            RC.Safe(reason=RC.SAFE_REASON_OPERATOR),                 # operator released the stick
            RC.GoTo(leg_id=0, goal_row=0.0, goal_col=2.0, v_max_mps=0.3),
            RC.Safe(reason=RC.SAFE_REASON_WATCHDOG)]                 # then the stream stalled
    evs = B.bridge_session_events(cmds)
    assert [e.kind for e in evs] == ["command", "safe", "command", "safe"]   # nothing dropped
    assert "operator" in evs[1].detail.lower()                      # operator stop recorded with true cause
    assert "watchdog" in evs[3].detail.lower()                      # watchdog trip NOT relabeled onto it
    assert evs[1].t_s == 1.0 and evs[3].t_s == 3.0                  # ordinals preserved


def test_watchdog_trip_records_a_safe_world_transaction():
    """The SF-01 safety boundary over the bridge: a stalled cmd_vel stream trips the dead-man, and the
    trip is committed as a `safe` world transaction -- the same record_execution_event seam the SIM run
    uses, so live and sim feed one log."""
    be = RC.RecordingBackend()
    wd = RC.SafingWatchdog(be, deadline_s=5.0)
    bridge = B.RcBridge(wd)
    bridge.on_cmd_vel(0.3, 0.0, now=0.0)                    # one drive command through the watchdog
    assert bridge.tick(now=2.0) is False                   # within deadline -> still driving
    assert bridge.tick(now=10.0) is True                   # stalled past 5 s -> tripped + auto-safed

    wss = WorldStateService(twin=_twin())
    evs = B.bridge_session_events(be.commands)
    for ev in evs:
        wss.record_execution_event(provenance=f"bridge {ev.kind}: {ev.detail} [{ev.outcome}]",
                                   mission="teleop", site="haworth", body="moon", mission_t_s=ev.t_s)
    assert wss.transaction_count() == len(evs) and len(evs) >= 2   # >=1 command + the safe terminal
    last = wss.latest()
    assert "safe" in last.provenance.lower() and last.mission == "teleop"
    assert wss.verify_chain()
