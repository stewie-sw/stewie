"""[REQ:RT-01] the runtime profile registry — the execution environments a mission can run in (software-in-loop
through live rover) and each one's command + evidence capabilities. The cockpit binds this to gate what a
profile may do: a SIL / twin / replay / sim profile can rehearse and produce evidence but NEVER command the
real rover (no release/execute), while only hil / field / live profiles carry live command authority. Sourced
from the PRD2 runnable_profile taxonomy (design doc, Unified Workspace Context). Config, not synthetic data."""
from __future__ import annotations

from typing import TypedDict


class RuntimeProfile(TypedDict):
    id: str
    kind: str
    command_capability: str   # none | bounded | full
    evidence_class: str       # forecast | replay | sim_truth | hil | live
    can_release: bool
    can_execute: bool
    description: str


_PROFILES: tuple[RuntimeProfile, ...] = (
    {"id": "desktop_sil", "kind": "software_in_loop", "command_capability": "none",
     "evidence_class": "forecast", "can_release": False, "can_execute": False,
     "description": "Software-in-the-loop planning/analysis on the conserved numpy authority; no rover, no live command."},
    {"id": "digital_twin", "kind": "digital_twin", "command_capability": "none",
     "evidence_class": "forecast", "can_release": False, "can_execute": False,
     "description": "The observed digital twin: forecasts + belief, read-only, no command egress."},
    {"id": "ros2_replay", "kind": "replay", "command_capability": "none",
     "evidence_class": "replay", "can_release": False, "can_execute": False,
     "description": "Deterministic bag/MCAP replay through the ROS2 spine; evidence only, no live command."},
    # [REQ:RT-07] TWO simulators, SAME authority, DIFFERENT jobs -- and the split is deliberate, not drift.
    # gazebo_sim is the ROS2-NATIVE robot sim: URDF->SDF (stewie.interop.xacro_to_sdf), ros2_control, sensor
    # plugins on real ROS topics -- the integration surface for Nav2/SLAM/Autoware perception.
    # godot_sim is the TERRAIN/EXCAVATION sim: it owns the conserved authority (mass-exact cut/fill; Gazebo
    # has NO mass-conserving deformable terrain, which is precisely why the numpy authority exists) plus the
    # lunar photometry. viz2 speaks a private loopback-TCP JSON protocol, NOT ROS topics.
    # Neither is redundant: delete either and a capability the other does not have goes with it.
    {"id": "gazebo_sim", "kind": "simulation", "command_capability": "bounded",
     "evidence_class": "sim_truth", "can_release": False, "can_execute": False,
     "description": "Gazebo robot/sensor simulation (ROS2-native: URDF/SDF, ros2_control, sensor plugins on real ROS topics); drives the SIM rover under truth-isolated sim_truth, never the real rover."},
    {"id": "godot_sim", "kind": "simulation", "command_capability": "bounded",
     "evidence_class": "sim_truth", "can_release": False, "can_execute": False,
     "description": "Godot/viz2 terrain + excavation simulation on the conserved mass-exact authority (real DEM, lunar photometry, driveable over a private loopback seam); drives the SIM rover under truth-isolated sim_truth, never the real rover."},
    {"id": "hil", "kind": "hardware_in_loop", "command_capability": "bounded",
     "evidence_class": "hil", "can_release": True, "can_execute": True,
     "description": "Hardware-in-the-loop on a bench rover; bounded live actuation under the SF-01 safing watchdog."},
    {"id": "field_test", "kind": "field", "command_capability": "bounded",
     "evidence_class": "live", "can_release": True, "can_execute": True,
     "description": "Bounded field traverse on real hardware; live telemetry + bounded command under release authority."},
    {"id": "live_rover", "kind": "live", "command_capability": "full",
     "evidence_class": "live", "can_release": True, "can_execute": True,
     "description": "Full live rover command in the live namespace; release + execute under the complete authority chain."},
)

PROFILES: dict[str, RuntimeProfile] = {p["id"]: p for p in _PROFILES}


def list_runtime_profiles() -> list[RuntimeProfile]:
    """The 8 runtime profiles in escalation order (SIL → live)."""
    return list(_PROFILES)
