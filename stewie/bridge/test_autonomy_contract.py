"""[REQ:AS-01] / [REQ:AS-15] Phase-0 gate test for the frozen STEWIE autonomy boundary contract.

Asserts the boundary is Autoware-shaped with no road/lanelet behavior, that estimator nodes are
truth-denied, and -- the real gate -- that validate_contract() REJECTS a tampered contract: a missing
required node, a road/lanelet dependency, and a truth-topic input to an estimator node."""
import dataclasses

from stewie.bridge import autonomy_contract as AC


def test_real_contract_validates_clean():
    assert AC.validate_contract() == []


def test_all_autoware_shaped_roles_present_and_no_road_behavior():
    roles = {n.role for n in AC.NODES.values()}
    for r in AC.REQUIRED_ROLES:
        assert r in roles, f"missing role {r}"
    assert not (roles & {"behavior_planning", "route_planning", "lanelet", "traffic"})


def test_truth_denial_no_estimator_subscribes_a_truth_topic():
    for n in AC.NODES.values():
        if n.role in AC.ESTIMATOR_ROLES:
            assert not (set(n.subscribes) & set(AC.TRUTH_TOPICS)), f"{n.name} subscribes truth"


def test_gate_rejects_truth_input_to_an_estimator():
    loc = AC.NODES["localization"]
    bad = {**AC.NODES, "localization": dataclasses.replace(
        loc, subscribes=loc.subscribes + ("/stewie/truth/pose",))}
    assert any("truth-denial" in e for e in AC.validate_contract(nodes=bad))


def test_gate_rejects_a_road_lanelet_dependency():
    pl = AC.NODES["planning"]
    bad = {**AC.NODES, "planning": dataclasses.replace(pl, dependencies=("lanelet2",))}
    assert any("forbidden road/lanelet" in e for e in AC.validate_contract(nodes=bad))


def test_gate_rejects_a_missing_required_role():
    bad = {k: v for k, v in AC.NODES.items() if v.role != "mission_executive"}
    assert any("mission_executive" in e for e in AC.validate_contract(nodes=bad))


def test_command_topics_are_command_qos_and_safe_path_present():
    for ct in AC.COMMAND_TOPICS:
        assert AC.TOPICS[ct].qos == AC.QOS_COMMAND
    assert AC.SAFE_STATE_TOPIC in AC.TOPICS
    assert any(AC.SAFE_STATE_TOPIC in n.publishes for n in AC.NODES.values())


def test_topic_graph_is_closed_no_dangling():
    assert not [e for e in AC.validate_contract() if "undefined topic" in e]


def test_as07_navigation_spine_is_source_neutral_and_truth_denied():  # [REQ:AS-07]
    assert AC.validate_navigation_spine() == []
    stages = {stage.name: stage for stage in AC.NAVIGATION_SPINE}
    assert set(stages) == {
        "stereo_feature_tracking",
        "source_neutral_depth_odometry",
        "visual_inertial_fusion",
        "pose_graph_loop_closure",
    }
    depth = stages["source_neutral_depth_odometry"]
    assert "/stewie/perception/points" in depth.inputs
    assert set(depth.optional_depth_sources) == {"stereo_sgbm", "stereo_neural", "lidar", "rgbd", "replay"}
    assert "/stewie/localization/loop_closures" in stages["pose_graph_loop_closure"].outputs
    assert all(stage.truth_denied for stage in AC.NAVIGATION_SPINE)


def test_as07_navigation_spine_rejects_truth_or_lidar_only_shortcut():  # [REQ:AS-07]
    depth = next(stage for stage in AC.NAVIGATION_SPINE if stage.name == "source_neutral_depth_odometry")
    bad_truth = tuple(
        dataclasses.replace(stage, inputs=stage.inputs + ("/stewie/truth/pose",))
        if stage.name == "visual_inertial_fusion" else stage
        for stage in AC.NAVIGATION_SPINE
    )
    assert any("truth-denial" in e for e in AC.validate_navigation_spine(stages=bad_truth))

    lidar_only = tuple(
        dataclasses.replace(depth, optional_depth_sources=("lidar",))
        if stage.name == depth.name else stage
        for stage in AC.NAVIGATION_SPINE
    )
    assert any("source_neutral_depth_odometry" in e for e in AC.validate_navigation_spine(stages=lidar_only))


def test_depth_sources_feed_one_shared_mapping_localization_contract():
    """[REQ:AS-01] The row's depth-source-neutrality clause: stereo, LiDAR, RGB-D, and replayed point
    clouds must feed the SAME mapping/localization contract, not per-source forks.

    Non-vacuous: the source-neutral depth stage carries all four swappable depth families yet emits a
    SINGLE depth-odometry topic, and mapping + localization both consume the ONE shared point-cloud
    contract rather than any source-specific topic -- and a per-source fork (a lidar_points topic the
    mapping node must switch to) is proved to break the contract's closed topic graph."""
    depth = next(s for s in AC.NAVIGATION_SPINE if s.name == "source_neutral_depth_odometry")
    # every intended depth family (stereo passive/neural, LiDAR, RGB-D, replay) is a selectable source ...
    assert set(depth.optional_depth_sources) >= {"stereo_sgbm", "stereo_neural", "lidar", "rgbd", "replay"}
    # ... but they converge on ONE depth-odometry output and ONE shared point-cloud input, not a fork.
    assert depth.outputs == ("/stewie/localization/depth_odom",)
    assert "/stewie/perception/points" in depth.inputs

    shared_cloud = "/stewie/perception/points"
    assert shared_cloud in AC.NODES["mapping"].subscribes
    assert shared_cloud in AC.NODES["localization"].subscribes
    # neither estimator wires a source-specific cloud topic (a lidar/rgbd/replay fork breaks neutrality)
    forked = {"/stewie/perception/lidar_points", "/stewie/perception/rgbd_points",
              "/stewie/perception/replay_points"}
    assert not (set(AC.NODES["mapping"].subscribes) & forked)
    assert not (set(AC.NODES["localization"].subscribes) & forked)

    # mutation: a mapping node that forks onto a source-specific cloud (not in the shared contract) must
    # be REJECTED by the gate -- proves the shared-contract assertion above is not vacuous.
    mp = AC.NODES["mapping"]
    forked_map = {**AC.NODES, "mapping": dataclasses.replace(
        mp, subscribes=("/stewie/perception/lidar_points",) + mp.subscribes[1:])}
    assert any("undefined topic" in e and "lidar_points" in e
               for e in AC.validate_contract(nodes=forked_map))
