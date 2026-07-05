"""[REQ:RT-01] the runtime profile registry (/runtime/profiles): the 7 PRD2 execution environments + each one's
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
    assert set(by) == {"desktop_sil", "digital_twin", "ros2_replay", "gazebo_sim",
                       "hil", "field_test", "live_rover"}

    # a SIL / twin / replay / sim profile can NEVER command the real rover (fail-closed authority)
    for sim in ("desktop_sil", "digital_twin", "ros2_replay", "gazebo_sim"):
        assert by[sim]["can_release"] is False and by[sim]["can_execute"] is False, sim

    # gazebo_sim drives a SIM rover (bounded command) under truth-isolated sim_truth, not live
    assert by["gazebo_sim"]["command_capability"] == "bounded"
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
