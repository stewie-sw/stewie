"""[REQ:FS-27] the ROS/Gazebo/RViz evidence surface: the aggregator + route return the REAL evidence a
run's profile-match rests on -- lifecycle nodes, the clock/tf/joint + gz-bridged topics, the RViz displays,
and the Gazebo worlds -- read from the committed AS-01 contract + configs (no fabricated evidence)."""
import importlib

from fastapi.testclient import TestClient


def test_ros_evidence_aggregates_the_real_ros_gazebo_rviz_evidence():  # [REQ:FS-27]
    from stewie.server.ros_evidence import collect_ros_evidence
    e = collect_ros_evidence()
    # the AS-01 lifecycle node graph is surfaced (not empty), each carrying its role.
    assert e["n_nodes"] >= 9 and all(n.get("role") for n in e["lifecycle_nodes"])
    # the clock/frame topics a trustworthy sim/bridge run must carry.
    assert e["clock_present"] and e["tf_present"] and e["joint_states_present"]
    # the gz-bridged sensor topics, the RViz displays (incl. a MarkerArray), and the Gazebo worlds.
    assert len(e["gz_bridged_topics"]) >= 10
    assert e["n_rviz_displays"] >= 10
    assert any(d["class"] and "MarkerArray" in d["class"] for d in e["rviz_displays"])
    assert any(w.endswith(".sdf") for w in e["gazebo_worlds"])
    # the process/container profile: the AS-04 ROS container tiers (gazebo/rviz/bridge/...).
    assert e["container_tiers"] and {"gazebo", "rviz", "bridge"} <= set(e["container_tiers"])


def test_ros_evidence_route_serves_the_surface(monkeypatch):  # [REQ:FS-27]
    monkeypatch.setenv("STEWIE_API_KEY", "devkey")
    import stewie.server.server as srv
    importlib.reload(srv)
    c = TestClient(srv.app)
    r = c.get("/ros/evidence", headers={"X-API-Key": "devkey"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["ok"] and d["clock_present"] and d["n_nodes"] >= 9
    assert d["gazebo_worlds"] and d["rviz_displays"]
