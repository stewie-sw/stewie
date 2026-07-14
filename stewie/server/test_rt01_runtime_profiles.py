"""[REQ:RT-01] the runtime profile registry (/runtime/profiles): the 8 PRD2 execution environments + each one's
command/evidence capabilities. The core safety invariant: a SIL / twin / replay / sim profile can rehearse and
produce evidence but NEVER command the real rover (can_release/can_execute False); only hil / field / live carry
live command authority, escalating command_capability none->bounded->full. Real endpoint + config registry."""
from fastapi.testclient import TestClient

from stewie.server.server import app


def test_rt01_runtime_profile_registry(monkeypatch):  # [REQ:RT-01]
    monkeypatch.setenv("STEWIE_DEV_OPEN", "1")
    c = TestClient(app, base_url="http://127.0.0.1")
    j = c.get("/runtime/profiles").json()
    by = {p["id"]: p for p in j["profiles"]}
    # [REQ:RT-07] godot_sim joined the registry: viz2 -- the sim that is actually built, driveable and
    # PUBLICLY reachable -- previously declared no profile, so it sat outside this authority model entirely.
    assert set(by) == {"desktop_sil", "digital_twin", "ros2_replay", "gazebo_sim", "godot_sim",
                       "hil", "field_test", "live_rover"}

    # a SIL / twin / replay / sim profile can NEVER command the real rover (fail-closed authority)
    for sim in ("desktop_sil", "digital_twin", "ros2_replay", "gazebo_sim", "godot_sim"):
        assert by[sim]["can_release"] is False and by[sim]["can_execute"] is False, sim

    # BOTH sims drive a SIM rover (bounded command) under truth-isolated sim_truth, not live. Same
    # authority, different jobs: gazebo_sim is the ROS2-native robot/sensor surface (Nav2/SLAM/Autoware);
    # godot_sim owns the conserved terrain + excavation authority, which Gazebo has no equivalent for.
    for sim in ("gazebo_sim", "godot_sim"):
        assert by[sim]["command_capability"] == "bounded"
        assert by[sim]["evidence_class"] == "sim_truth"
    assert by["gazebo_sim"]["evidence_class"] == "sim_truth"

    # only hil / field / live carry live command authority; only live_rover is full
    for live in ("hil", "field_test", "live_rover"):
        assert by[live]["can_release"] is True and by[live]["can_execute"] is True, live
    assert by["live_rover"]["command_capability"] == "full"
    assert by["field_test"]["evidence_class"] == "live"


def test_rt01_command_capability_escalates():  # [REQ:RT-01]
    from stewie.specs.runtime_profiles import PROFILES
    rank = {"none": 0, "bounded": 1, "full": 2}
    assert rank[PROFILES["desktop_sil"]["command_capability"]] == 0
    assert rank[PROFILES["gazebo_sim"]["command_capability"]] == 1
    assert rank[PROFILES["live_rover"]["command_capability"]] == 2
