"""[REQ:RT-07] viz2/Godot DECLARES a runtime profile, and the declaration is PROVEN, not promised.

WHY THIS FILE EXISTS. The RT-01 registry enumerates the execution environments a mission can run in and
each one's command + evidence authority. It named `gazebo_sim` -- "drives the SIM rover under truth-isolated
sim_truth, never the real rover" -- and that sentence describes **viz2 exactly**. But viz2 was not in the
registry at all: `viz2_runtime` and the stream server declared NO profile. So the one simulator that is
actually built, driveable, and REACHABLE FROM THE PUBLIC INTERNET (RT-06) sat entirely outside the authority
model whose whole purpose is to guarantee that a simulation can never command real hardware.

That is the gap this closes. `godot_sim` is the profile viz2 has always BEEN; it simply had no name.

AND THE PART THAT MATTERS: the registry is DECLARATIVE. Nothing reads `can_release` / `can_execute` to
refuse anything -- outside the registry and its own test, every mention of those flags in the codebase is
inside a DOCSTRING. A profile entry, on its own, is a comment with a type annotation. Adding one and calling
it safety would be exactly the class of bug this project keeps finding: the cosmetic arm (PX-10), the dead
rock seed (TR-01), the modelled-but-unused dig reaction (PX-13). A flag nothing reads is not a control.

So the declaration is BOUND to the structural proof that already exists. viz2's real safety is not a boolean;
it is RT-06's AST egress guard, which proves the public stream server cannot even NAME a real-rover command
path. This file ties the two together: the profile viz2 declares must say `can_release=False` /
`can_execute=False`, AND the module must be structurally incapable of the egress that would make those
booleans a lie. Neither half can drift from the other without failing here.

HONEST SCOPE. This does NOT make the registry enforcing in general -- the other six profiles remain
declarative, and real command authority is gated elsewhere (the executive sole-egress RT-02, the director
grant, /rc/eligibility). What it does is ensure that for the ONE profile that is publicly reachable, the
claim and the proof are welded together.
"""
from __future__ import annotations

import ast
from pathlib import Path

from stewie.specs.runtime_profiles import PROFILES, list_runtime_profiles
from stewie.stream import app as app_mod
from stewie.stream.test_viz2_ide_embed import REAL_ROVER_EGRESS

APP_PY = Path(app_mod.__file__)


def test_the_registry_has_a_godot_sim_profile() -> None:
    """[REQ:RT-07] viz2/Godot is a real execution environment and must be nameable as one. Before this,
    the only 'simulation' slot was `gazebo_sim` -- a DIFFERENT engine, for a different job (ROS2-native
    robot/sensor integration; Gazebo has no mass-conserving deformable terrain, which is the entire point
    of the Godot path)."""
    assert "godot_sim" in PROFILES, (
        "viz2/Godot -- the sim that is actually built, driveable and publicly reachable -- has no runtime "
        "profile, so it sits outside the authority model entirely")
    p = PROFILES["godot_sim"]
    assert p["kind"] == "simulation"
    assert p["command_capability"] == "bounded"   # it DOES drive a sim rover (bounded), unlike desktop_sil
    assert p["evidence_class"] == "sim_truth"     # its truth is the conserved authority, not a forecast


def test_a_simulation_profile_can_never_release_or_execute() -> None:
    """[REQ:RT-07] The fail-closed rule the registry exists to express. godot_sim joins the sim family:
    it may rehearse and produce evidence, never command the real rover."""
    for sim in ("desktop_sil", "digital_twin", "ros2_replay", "gazebo_sim", "godot_sim"):
        p = PROFILES[sim]
        assert p["can_release"] is False, f"{sim} must not be able to release a real mission"
        assert p["can_execute"] is False, f"{sim} must not be able to execute on real hardware"


def test_the_stream_server_declares_the_profile_it_actually_runs_under() -> None:
    """[REQ:RT-07] The declaration must live on the runtime, not in a doc. An unclaimed profile is a
    profile nothing is bound by."""
    assert getattr(app_mod, "RUNTIME_PROFILE", None) == "godot_sim", (
        "the public stream server does not declare its runtime profile, so nothing ties viz2 to the "
        "authority model that is supposed to govern it")
    assert app_mod.RUNTIME_PROFILE in PROFILES, "viz2 declares a profile that is not in the registry"


def test_the_declared_profile_is_PROVEN_by_the_egress_guard_not_merely_asserted() -> None:
    """[REQ:RT-07] THE POINT OF THIS FILE. `can_execute=False` is a dict value; nothing in the codebase
    reads it to refuse anything. What actually makes it TRUE is that the public stream server is
    structurally incapable of naming a real-rover command path (RT-06's AST guard). Weld the two: the
    profile viz2 declares claims no command authority, AND the module provably cannot exercise any.

    If someone later adds an egress to the stream server, this fails -- even though the dict still says
    False -- which is the whole difference between a claim and a control."""
    p = PROFILES[app_mod.RUNTIME_PROFILE]
    assert p["can_release"] is False and p["can_execute"] is False

    tree = ast.parse(APP_PY.read_text(encoding="utf-8"))
    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                hits += [f"import {a.name}:{node.lineno}" for s in REAL_ROVER_EGRESS if s in a.name]
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            for a in node.names:
                hits += [f"from {mod} import {a.name}:{node.lineno}"
                         for s in REAL_ROVER_EGRESS if s in mod or s in a.name]
        elif isinstance(node, ast.Attribute):
            hits += [f"attr .{node.attr}:{node.lineno}" for s in REAL_ROVER_EGRESS if s == node.attr]
        elif isinstance(node, ast.Name):
            hits += [f"name {node.id}:{node.lineno}" for s in REAL_ROVER_EGRESS if s == node.id]
    assert hits == [], (
        f"viz2 declares the profile {app_mod.RUNTIME_PROFILE!r} (can_execute=False), but its module can "
        f"reach a real-rover egress -- the declaration is a lie the registry cannot catch: {hits}")


def test_godot_sim_is_distinct_from_gazebo_sim_and_both_survive() -> None:
    """[REQ:RT-07] Record the architectural decision as a test, so nobody collapses one into the other.

    They are NOT redundant. Godot/viz2 owns what Gazebo cannot: the conserved terrain authority
    (mass-exact cut/fill -- Gazebo has no mass-conserving deformable terrain, which is precisely why the
    numpy authority exists) plus lunar photometry. Gazebo owns what Godot cannot: a ROS2-native robot
    (URDF->SDF via stewie.interop.xacro_to_sdf, ros2_control, sensor plugins on real ROS topics) -- the
    integration surface for Nav2/SLAM/Autoware perception. viz2 speaks a private loopback-TCP JSON
    protocol, not ROS topics.

    Both are simulations with identical AUTHORITY (bounded command, sim_truth evidence, no release, no
    execute) and different JOBS. Deleting either loses a capability the other does not have."""
    ids = [p["id"] for p in list_runtime_profiles()]
    assert "godot_sim" in ids and "gazebo_sim" in ids, "both simulators must remain nameable"
    g, z = PROFILES["godot_sim"], PROFILES["gazebo_sim"]
    assert (g["command_capability"], g["evidence_class"]) == (z["command_capability"], z["evidence_class"]), \
        "the two sims must carry the SAME authority -- they differ in job, not in what they are allowed to do"
    assert g["description"] != z["description"], "each sim must say what it is FOR, or the split is lost"


def test_the_profiles_still_escalate_none_to_bounded_to_full() -> None:
    """[REQ:RT-07] Adding a profile must not break the escalation ladder the cockpit gates on."""
    rank = {"none": 0, "bounded": 1, "full": 2}
    assert rank[PROFILES["desktop_sil"]["command_capability"]] == 0
    assert rank[PROFILES["godot_sim"]["command_capability"]] == 1
    assert rank[PROFILES["live_rover"]["command_capability"]] == 2
    for live in ("hil", "field_test", "live_rover"):
        assert PROFILES[live]["can_release"] is True and PROFILES[live]["can_execute"] is True
