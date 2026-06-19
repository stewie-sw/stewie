"""[REQ:AS-02] host-side conformance gate for the ROS2 workspace skeleton (§25 Phase 1).

Verifies STRUCTURE + contract-conformance on a non-ROS host (the colcon build/test acceptance is
container-gated -- deploy/ros2/Dockerfile.ros2dev). Checks: the 10 AS-02 packages exist with well-formed
manifests; stewie_msgs carries every interface the AS-01 boundary contract references; the node packages
map to AS-01 roles and import safely without rclpy."""
import importlib.util
import os
import xml.etree.ElementTree as ET

import pytest

from stewie.bridge import autonomy_contract as AC

_HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(_HERE, "src")

AS02_PACKAGES = ("stewie_msgs", "stewie_description", "stewie_bringup", "stewie_vehicle_interface",
                 "stewie_perception", "stewie_localization", "stewie_mapping", "stewie_planning",
                 "stewie_control", "stewie_rviz")

NODE_PACKAGES = {  # package -> AS-01 contract role
    "stewie_perception": "perception", "stewie_localization": "localization",
    "stewie_mapping": "mapping", "stewie_planning": "planning",
    "stewie_control": "control", "stewie_vehicle_interface": "vehicle_interface",
}


def test_all_ten_packages_exist_with_wellformed_manifest():
    for pkg in AS02_PACKAGES:
        pxml = os.path.join(SRC, pkg, "package.xml")
        assert os.path.isfile(pxml), f"missing {pkg}/package.xml"
        name = ET.parse(pxml).getroot().findtext("name")
        assert name == pkg, f"{pkg}/package.xml declares name {name!r}"


def test_stewie_msgs_covers_every_contract_interface():
    msg_dir = os.path.join(SRC, "stewie_msgs", "msg")
    have = {f[:-4] for f in os.listdir(msg_dir) if f.endswith(".msg")}
    # every stewie_msgs/<T> referenced by the frozen AS-01 topic contract must have a .msg
    referenced = {t.msg.split("/", 1)[1] for t in AC.TOPICS.values() if t.msg.startswith("stewie_msgs/")}
    missing = referenced - have
    assert not missing, f"stewie_msgs missing contract interfaces: {missing}"
    assert referenced, "no stewie_msgs interfaces referenced by the contract?"


def test_node_packages_map_to_contract_roles_and_import_without_rclpy():
    roles = {n.role for n in AC.NODES.values()}
    for pkg, role in NODE_PACKAGES.items():
        assert role in roles, f"{pkg} role {role!r} not in the AS-01 contract"
        node_py = os.path.join(SRC, pkg, pkg, "node.py")
        assert os.path.isfile(node_py), f"missing {pkg}/{pkg}/node.py"
        spec = importlib.util.spec_from_file_location(f"_skel_{pkg}", node_py)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)          # must import on a non-ROS host (rclpy-optional)
        assert hasattr(mod, "main") and mod.ROLE == role


def test_node_main_is_run_gated_without_rclpy():
    # a skeleton node must FAIL CLOSED (SystemExit) when run on a host with no rclpy -- not silently no-op
    node_py = os.path.join(SRC, "stewie_control", "stewie_control", "node.py")
    spec = importlib.util.spec_from_file_location("_skel_ctl", node_py)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if not mod._HAVE_RCLPY:
        with pytest.raises(SystemExit):
            mod.main()
