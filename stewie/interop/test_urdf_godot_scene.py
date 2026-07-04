"""[REQ:BA-06] URDF<->Godot scene round-trips the REAL ipex robot description with STRUCTURE preserved: link
count, joint count, the parent->child tree, and every joint origin. Fixture = the real ipex.expanded.urdf
(the ipex.urdf.xacro expanded by the container's xacro -- real robot data, never synthetic)."""
import pytest

from stewie.interop.urdf_godot_scene import (
    godot_scene_to_urdf,
    urdf_string_to_godot_scene,
    urdf_to_godot_scene,
)

_URDF = "ros2_ws/src/stewie_description/urdf/ipex.expanded.urdf"


def _parent_map(scene):
    return {n.name: n.parent for n in scene.nodes}


def _origin_map(scene):
    return {n.name: (n.xyz, n.rpy) for n in scene.nodes}


def test_ba06_urdf_godot_scene_roundtrip_preserves_structure():  # [REQ:BA-06]
    scene = urdf_to_godot_scene(_URDF)
    # the real ipex description: 29 links, 28 joints, a single scene root
    assert scene.link_count == 29 and scene.joint_count == 28
    roots = [n for n in scene.nodes if n.parent is None]
    assert len(roots) == 1 and roots[0].name == scene.root

    # round-trip: scene -> URDF -> scene, structure identical
    scene2 = urdf_string_to_godot_scene(godot_scene_to_urdf(scene, "ipex"))
    assert scene2.link_count == 29 and scene2.joint_count == 28 and scene2.root == scene.root
    assert _parent_map(scene2) == _parent_map(scene)                         # parent->child tree preserved
    o1, o2 = _origin_map(scene), _origin_map(scene2)
    assert set(o1) == set(o2)
    for k in o1:                                                             # every joint origin preserved
        assert o1[k][0] == pytest.approx(o2[k][0]) and o1[k][1] == pytest.approx(o2[k][1])
