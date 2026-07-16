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


def test_evidence_surface_holds_no_command_authority_executive_is_sole_egress():  # [REQ:RT-02]
    """[REQ:RT-02] The ROS/Gazebo/RViz/Godot evidence surface attaches to the selected run/profile and holds
    NO independent command authority -- the execution service is the SOLE command egress (extends BA-08).

    Verified structurally, not by comment. (1) `ros_evidence` is READ-ONLY: it exposes an aggregator + the
    GET route only, and its AST contains no command verb (release/execute/advance/cmd_vel) and no POST. (2)
    the evidence is BOUND TO THE PROFILE: it is read from the committed AS-01 autonomy contract
    (`autonomy_contract.NODES/TOPICS`), not invented. (3) the command verbs live ONLY on the executive
    router, gated behind director auth -- a different module -- so an evidence pane cannot command the rover.
    """
    import ast
    import inspect

    import stewie.server.ros_evidence as EV
    from stewie.bridge import autonomy_contract as AC

    # (1) READ-ONLY: no command egress anywhere in the evidence module's source.
    tree = ast.parse(inspect.getsource(EV))
    banned = {"release_plan", "advance", "run", "cmd_vel", "make_live_node", "rclpy"}
    hits = [n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and n.id in banned]
    hits += [n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute) and n.attr in banned]
    assert hits == [], f"the evidence surface names a command path -- it must be read-only: {hits}"

    # (2) BOUND TO THE PROFILE: the evidence is the committed contract's node/topic graph, not fabricated.
    e = EV.collect_ros_evidence()
    assert {n["name"] for n in e["lifecycle_nodes"]} == set(AC.NODES), \
        "the evidence node set is not the committed autonomy-contract profile"

    # (3) SOLE EGRESS: the command verbs live only on the executive, behind director auth -- a different
    # module the evidence surface does not import.
    import stewie.server.routers.executive as EXE
    exe_src = inspect.getsource(EXE)
    assert '@router.post("/executive/release-plan")' in exe_src and "require_director" in exe_src, \
        "the executive is not the director-gated command egress it must be"
    assert "executive" not in inspect.getsource(EV), \
        "the evidence surface reaches the executive -- it must not hold or route command authority"


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
