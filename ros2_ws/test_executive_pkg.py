"""[REQ:AS-13] host-side conformance gate for the ROS2 mission-executive node package (§25 Phase 11).

The AS-13 executive is the ROS2-side node that monitors preconditions, acknowledgements, covariance,
resource reservations, faults, acceptance state, and safing, then emits continue / pause / replan /
relocalize / reverse / SAFE. lode/test_executive_decision.py already gates the PURE decision logic
(lode.executive.executive_step / to_executive_decision). This gate closes the ROS2 seam: the
stewie_executive package must EXIST, map to the AS-01 `mission_executive` role, subscribe/publish
exactly the contract topics for that role, import on a non-ROS host (rclpy-optional), fail closed when
run without rclpy, and route its decision through the shared lode.executive verb set. The live node
spin + real topic subscriptions are container-gated (needs a ROS2 Jazzy rclpy runtime)."""
import importlib.util
import os
import xml.etree.ElementTree as ET

import pytest

from stewie.bridge import autonomy_contract as AC

_HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(_HERE, "src")
PKG = "stewie_executive"
ROLE = "mission_executive"


def _load_node():
    node_py = os.path.join(SRC, PKG, PKG, "node.py")
    assert os.path.isfile(node_py), f"missing {PKG}/{PKG}/node.py"
    spec = importlib.util.spec_from_file_location("_skel_exec", node_py)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)            # must import on a non-ROS host (rclpy-optional)
    return mod


def test_package_exists_with_wellformed_manifest():
    pxml = os.path.join(SRC, PKG, "package.xml")
    assert os.path.isfile(pxml), f"missing {PKG}/package.xml"
    name = ET.parse(pxml).getroot().findtext("name")
    assert name == PKG, f"{PKG}/package.xml declares name {name!r}"


def test_mission_executive_role_is_in_the_contract():
    roles = {n.role for n in AC.NODES.values()}
    assert ROLE in roles, f"{ROLE!r} not defined in the AS-01 boundary contract"


def test_node_imports_without_rclpy_and_declares_the_role():
    mod = _load_node()
    assert hasattr(mod, "main"), f"{PKG} node.py exports no main()"
    assert mod.ROLE == ROLE, f"{PKG} declares ROLE {mod.ROLE!r}, expected {ROLE!r}"


def test_node_pub_sub_match_the_contract_exactly():
    # the node advertises the same subscribe/publish sets the frozen contract assigns mission_executive
    mod = _load_node()
    node = AC.NODES[ROLE]
    assert set(mod.SUBSCRIBES) == set(node.subscribes), (
        f"{PKG} SUBSCRIBES {mod.SUBSCRIBES} != contract {node.subscribes}")
    assert set(mod.PUBLISHES) == set(node.publishes), (
        f"{PKG} PUBLISHES {mod.PUBLISHES} != contract {node.publishes}")
    # every one of those topics is a defined topic in the contract graph (closed graph)
    for t in (*mod.SUBSCRIBES, *mod.PUBLISHES):
        assert t in AC.TOPICS, f"{PKG} references undefined topic {t!r}"


def test_node_emits_the_executive_decision_topic_and_msg_type():
    # AS-13 output seam: publishes /stewie/exec/decision typed as stewie_msgs/ExecutiveDecision
    mod = _load_node()
    dec_topic = "/stewie/exec/decision"
    assert dec_topic in mod.PUBLISHES, f"{PKG} does not publish {dec_topic}"
    assert AC.TOPICS[dec_topic].msg == "stewie_msgs/ExecutiveDecision"


def test_node_routes_decisions_through_the_shared_verb_set():
    # the node's decide() delegates to lode.executive so the whole precedence ladder + verb set is one
    # source of truth (no re-derived logic). A safety-critical fault must surface as the SAFE verb.
    mod = _load_node()
    out = mod.decide(faults=[{"fault": "imu_dropout", "severity": "critical"}])
    assert out["decision"] == "safe", f"critical fault did not yield SAFE: {out}"
    assert mod.decide()["decision"] == "continue", "nominal signals did not yield continue"
    verbs = {"continue", "pause", "replan", "relocalize", "reverse", "safe"}
    assert out["decision"] in verbs


def test_node_main_is_run_gated_without_rclpy():
    # a skeleton node must FAIL CLOSED (SystemExit) when run on a host with no rclpy -- not silently no-op
    mod = _load_node()
    if not mod._HAVE_RCLPY:
        with pytest.raises(SystemExit):
            mod.main()
