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
    rng = np.random.default_rng(11)
    return vt.TwinStore(rng.normal(0.0, 0.05, (32, 32)), cell_m=0.5)


def test_session_events_one_command_each_plus_safe_on_trip():
    cmds = [RC.GoTo(leg_id=0, goal_row=0.0, goal_col=1.0, v_max_mps=0.3),
            RC.GoTo(leg_id=0, goal_row=0.0, goal_col=2.0, v_max_mps=0.3),
            RC.Safe(reason=RC.SAFE_REASON_WATCHDOG)]
    evs = B.bridge_session_events(cmds, tripped=True)
    assert [e.kind for e in evs] == ["command", "command", "safe"]   # Safe cmd folded into the terminal
    assert evs[-1].outcome == "safed"


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
    evs = B.bridge_session_events(be.commands, tripped=True)
    for ev in evs:
        wss.record_execution_event(provenance=f"bridge {ev.kind}: {ev.detail} [{ev.outcome}]",
                                   mission="teleop", site="haworth", body="moon", mission_t_s=ev.t_s)
    assert wss.transaction_count() == len(evs) and len(evs) >= 2   # >=1 command + the safe terminal
    last = wss.latest()
    assert "safe" in last.provenance.lower() and last.mission == "teleop"
    assert wss.verify_chain()
