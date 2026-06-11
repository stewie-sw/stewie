"""#66 + SF-01: the pluggable RC contract + the safing watchdog.

Deduced from John's frozen CONTRACT.md (scripts/ccsds_ros_nav/CONTRACT.md §2/§3): the dirt-pit
remote-control seam is GoTo/Safe/SetSim commands + Pose/Leg telemetry. STEWIE presents the SAME
contract whether it drives the conserved sim authority OR a real pit robot -- the backend is
pluggable, the contract is the seam. SF-01 (the architecture's flagged-REQUIRED missing node) is
the command-timeout watchdog: a dead-man switch that auto-SAFEs if commands stop arriving.
"""

from stewie.bridge import rc_contract as RC


def test_commands_match_johns_contract_apids():
    """#66: the APID registry is John's CONTRACT.md §2 verbatim (wire-compatible)."""
    assert RC.APID_CMD_GOTO == 0x0C8 and RC.APID_CMD_SAFE == 0x0C9 and RC.APID_CMD_SETSIM == 0x0CA
    assert RC.APID_TLM_POSE == 0x064 and RC.APID_TLM_LEG == 0x065


def test_goto_command_roundtrips():
    """A GoTo carries the §3 fields (leg_id, goal_row, goal_col, v_max, radius)."""
    g = RC.GoTo(leg_id=3, goal_row=10.0, goal_col=20.0, v_max_mps=0.3, goal_radius_cells=1.0)
    assert g.kind == "goto" and g.leg_id == 3 and g.goal_col == 20.0


def test_sim_backend_executes_a_goto_and_emits_pose():
    """#66: the SimBackend drives the conserved authority toward the goal and emits Pose telemetry
    whose position MOVES toward the waypoint (a real backend, not a stub)."""
    be = RC.SimBackend(start_rc=(0.0, 0.0))
    be.submit(RC.GoTo(leg_id=1, goal_row=0.0, goal_col=10.0, v_max_mps=0.3, goal_radius_cells=1.0))
    tlm = []
    for _ in range(40):
        tlm += be.poll()
    poses = [t for t in tlm if t.kind == "pose"]
    assert poses, "the backend must emit Pose telemetry while driving"
    assert poses[-1].col > poses[0].col          # moved toward goal_col=10
    assert poses[-1].col <= 10.0 + 1e-6          # never overshoots the goal


def test_safing_watchdog_trips_on_command_timeout():
    """SF-01 [REQ:SF-01]: if no command arrives within the deadline, the watchdog auto-issues SAFE
    to the backend (the dead-man switch the architecture flags REQUIRED, Phase-0/Week-4)."""
    be = RC.RecordingBackend()
    wd = RC.SafingWatchdog(be, deadline_s=2.0)
    wd.feed(now=0.0)                              # a valid command at t=0
    wd.tick(now=1.0)                              # within deadline -> no safe
    assert not wd.tripped and not any(c.kind == "safe" for c in be.commands)
    wd.tick(now=2.5)                             # past the 2 s deadline -> AUTO-SAFE
    assert wd.tripped and be.commands[-1].kind == "safe"
    assert be.commands[-1].reason == RC.SAFE_REASON_WATCHDOG


def test_watchdog_resets_on_each_valid_command():
    """A heartbeat (feed) before the deadline keeps the link alive."""
    be = RC.RecordingBackend()
    wd = RC.SafingWatchdog(be, deadline_s=2.0)
    for t in (0.0, 1.5, 3.0, 4.5):               # fed every 1.5 s < 2 s deadline
        wd.feed(now=t)
        wd.tick(now=t + 0.1)
    assert not wd.tripped and not any(c.kind == "safe" for c in be.commands)


def test_setsim_is_director_only_capability():
    """#68 tie-in: SetSim (time acceleration) is a TRAINING toggle -- the contract marks it
    director-only so an operator role cannot fast-forward past mission latency."""
    assert RC.SetSim(time_factor=10.0).director_only is True
    assert RC.GoTo(leg_id=0, goal_row=0, goal_col=1, v_max_mps=0.3, goal_radius_cells=1).director_only is False


def test_any_backend_plugs_into_the_same_contract():
    """#66: the pluggable seam -- a custom backend (e.g. the real dirt-pit robot) implementing the
    RCBackend ABC drives through the SAME watchdog + command path as the sim."""
    class PitBackend(RC.RCBackend):
        def __init__(self): self.log = []
        def submit(self, cmd): self.log.append(cmd)
        def poll(self): return []
    pit = PitBackend()
    wd = RC.SafingWatchdog(pit, deadline_s=1.0)
    wd.submit(RC.GoTo(leg_id=0, goal_row=0, goal_col=5, v_max_mps=0.3, goal_radius_cells=1), now=0.0)
    assert pit.log[-1].kind == "goto"            # the command reached the pluggable backend
    wd.tick(now=2.0)
    assert pit.log[-1].kind == "safe"            # the watchdog safes the real backend too


def test_plan_outputs_reusable_rc_commands():
    """#66 (Aaron: "plan should output cmds for reuse"): a plan converts to a GoTo command
    sequence that REPLAYS through the same RC backend -- plan once, command many."""
    from lode import mission_planner as MP
    m = MP.mission_from_dict({"name": "c", "body": "moon", "charger": [0, 0], "orders": [
        {"action": "a", "kind": "cut", "x": 20, "y": 0, "footprint_m2": 16, "depth_m": 0.05},
        {"action": "b", "kind": "fill", "x": 40, "y": 10, "footprint_m2": 16, "depth_m": 0.05}]})
    cmds = RC.commands_from_plan(m, cell_m=5.0)
    assert cmds and all(c.kind == "goto" for c in cmds)
    assert all(isinstance(c.leg_id, int) for c in cmds)
    assert cmds[0].leg_id == 0 and cmds[1].leg_id == 1     # sequenced, reusable
    # the commands REPLAY: feed them to a fresh backend and it drives
    be = RC.SimBackend(start_rc=(0.0, 0.0), cell_m=5.0)
    be.submit(cmds[0])
    moved = any(t.kind == "pose" for _ in range(50) for t in be.poll())
    assert moved                                           # the exported command actually drives
