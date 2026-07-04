"""[REQ:BA-06] URDF <-> Godot scene-graph interop (part of the BA-06 converter set).

A URDF robot (link tree wired by joints) converts to a Godot scene graph -- one Node3D per link, parented by
the joint tree, each carrying its joint origin (xyz + rpy) as its local transform. The round-trip preserves
the STRUCTURE: link count, joint count, the parent->child tree, and every joint origin. Pure stdlib
(xml.etree); on-host. The input URDF is plain XML -- a xacro description must be expanded first (see the
container-gated xacro_to_sdf converter, which also produces the expanded URDF fixture)."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass

_Vec3 = tuple[float, float, float]


@dataclass(frozen=True)
class GodotNode:
    """One Godot Node3D == one URDF link. `parent` is the parent link name (None for the scene root); `xyz`
    + `rpy` are the local transform from the joint that attaches this link to its parent."""
    name: str
    parent: str | None
    xyz: _Vec3
    rpy: _Vec3
    joint_name: str | None
    joint_type: str | None


@dataclass
class GodotScene:
    root: str
    nodes: list[GodotNode]

    @property
    def link_count(self) -> int:
        return len(self.nodes)

    @property
    def joint_count(self) -> int:
        return sum(1 for n in self.nodes if n.parent is not None)


def _origin(joint: ET.Element) -> tuple[_Vec3, _Vec3]:
    o = joint.find("origin")
    xyz = tuple(float(v) for v in (o.get("xyz", "0 0 0") if o is not None else "0 0 0").split())
    rpy = tuple(float(v) for v in (o.get("rpy", "0 0 0") if o is not None else "0 0 0").split())
    return xyz, rpy  # type: ignore[return-value]


def _scene_from_root(root: ET.Element) -> GodotScene:
    links = [name for ln in root.findall("link") if (name := ln.get("name"))]
    joints = root.findall("joint")
    # child link -> (parent link, joint name, type, origin)
    by_child: dict[str, tuple[str, str, str, _Vec3, _Vec3]] = {}
    for j in joints:
        p, c = j.find("parent"), j.find("child")
        if p is None or c is None:
            continue
        pl, cl = p.get("link"), c.get("link")
        xyz, rpy = _origin(j)
        if pl and cl:
            by_child[cl] = (pl, j.get("name", ""), j.get("type", "fixed"), xyz, rpy)
    roots = [ln for ln in links if ln not in by_child]
    if len(roots) != 1:
        raise ValueError(f"URDF must have exactly one root link, found {roots}")
    nodes = []
    for ln in links:
        if ln in by_child:
            pl, jn, jt, xyz, rpy = by_child[ln]
            nodes.append(GodotNode(ln, pl, xyz, rpy, jn, jt))
        else:
            nodes.append(GodotNode(ln, None, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0), None, None))
    return GodotScene(root=roots[0], nodes=nodes)


def urdf_to_godot_scene(urdf_path: str) -> GodotScene:
    return _scene_from_root(ET.parse(urdf_path).getroot())


def urdf_string_to_godot_scene(urdf_xml: str) -> GodotScene:
    return _scene_from_root(ET.fromstring(urdf_xml))


def godot_scene_to_urdf(scene: GodotScene, robot_name: str = "robot") -> str:
    """Emit a plain URDF (structure only: links + joints with origins) from the Godot scene graph."""
    robot = ET.Element("robot", {"name": robot_name})
    for n in scene.nodes:
        ET.SubElement(robot, "link", {"name": n.name})
    for n in scene.nodes:
        if n.parent is None:
            continue
        j = ET.SubElement(robot, "joint",
                          {"name": n.joint_name or f"{n.name}_joint", "type": n.joint_type or "fixed"})
        ET.SubElement(j, "parent", {"link": n.parent})
        ET.SubElement(j, "child", {"link": n.name})
        ET.SubElement(j, "origin", {"xyz": " ".join(str(v) for v in n.xyz),
                                    "rpy": " ".join(str(v) for v in n.rpy)})
    return ET.tostring(robot, encoding="unicode")
