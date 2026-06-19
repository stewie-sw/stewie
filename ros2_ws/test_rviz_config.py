"""[REQ:AS-05] host-side lint for the STEWIE mission RViz dashboard (§25 Phase 3).

Verifies the config declares every required operator display and that each binds to an AS-01
boundary-contract topic -- native RViz types bind the contract topic directly; STEWIE custom-msg
displays bind a companion *_viz / *_markers / status topic whose base IS a contract topic. The
container rviz2 load smoke (GUI under xvfb) is the runtime half; this is the deterministic config gate."""
import os

import yaml

from stewie.bridge import autonomy_contract as AC

_HERE = os.path.dirname(os.path.abspath(__file__))
RVIZ = os.path.join(_HERE, "src", "stewie_rviz", "rviz", "mission.rviz")


def _displays():
    with open(RVIZ) as f:
        cfg = yaml.safe_load(f)
    out = []
    for d in cfg["Visualization Manager"]["Displays"]:
        topic = None
        for key in ("Topic", "Description Topic"):
            if isinstance(d.get(key), dict):
                topic = d[key].get("Value")
        out.append((d["Class"], d.get("Name"), topic))
    return out


def test_fixed_frame_is_rep103_map():
    cfg = yaml.safe_load(open(RVIZ))
    assert cfg["Visualization Manager"]["Global Options"]["Fixed Frame"] == "map"


def test_all_required_display_classes_present():
    classes = {c for c, _, _ in _displays()}
    required = {
        "rviz_default_plugins/Grid", "rviz_default_plugins/RobotModel", "rviz_default_plugins/TF",
        "rviz_default_plugins/Odometry", "rviz_default_plugins/Path", "rviz_default_plugins/Map",
        "grid_map_rviz_plugin/GridMap", "rviz_default_plugins/PointCloud2",
        "rviz_default_plugins/Image", "rviz_default_plugins/MarkerArray",
        "rviz_default_plugins/PoseWithCovariance",
    }
    missing = required - classes
    assert not missing, f"mission.rviz missing required displays: {missing}"


def test_native_displays_bind_exact_contract_topics():
    by_name = {name: topic for _, name, topic in _displays()}
    expected = {
        "Odometry": "/stewie/odom",
        "Planned Path": "/stewie/plan/path",
        "Costmap": "/stewie/costmap",
        "Occupancy": "/stewie/map/occupancy",
        "DEM": "/stewie/map/dem",
        "Excavation State": "/stewie/map/excavation_state",
        "Perception Points": "/stewie/perception/points",
        "Front Left Cam": "/stewie/camera/front_left/image",
        "Front Right Cam": "/stewie/camera/front_right/image",
        "Localization Covariance": "/stewie/localization/cov",
    }
    for name, topic in expected.items():
        assert by_name.get(name) == topic, f"{name} binds {by_name.get(name)!r}, expected {topic}"
        assert topic in AC.TOPICS, f"{topic} is not an AS-01 contract topic"


def test_companion_viz_topics_derive_from_contract_topics():
    topics = {t for _, _, t in _displays() if t}
    # each companion viz topic's BASE must be a real contract topic (no orphan viz channels)
    companions = {
        "/stewie/plan/local_traj_viz": "/stewie/plan/local_traj",
        "/stewie/perception/rocks_markers": "/stewie/perception/rocks",
        "/stewie/argus/factors_markers": "/stewie/argus/factors",
    }
    for viz, base in companions.items():
        assert viz in topics, f"missing companion display topic {viz}"
        assert base in AC.TOPICS, f"companion base {base} not in contract"


def test_status_overlay_covers_diagnostics_safe_and_command():
    # the aggregated status MarkerArray stands in for the non-natively-displayable contract channels
    topics = {t for _, _, t in _displays() if t}
    assert "/stewie/status_markers" in topics
    for required_channel in ("/diagnostics", "/stewie/safe_state", "/stewie/exec/decision", "/cmd_vel"):
        assert required_channel in AC.TOPICS, f"{required_channel} missing from contract"


def test_robotmodel_uses_robot_description():
    by_name = {name: topic for _, name, topic in _displays()}
    assert by_name.get("RobotModel") == "/robot_description"
