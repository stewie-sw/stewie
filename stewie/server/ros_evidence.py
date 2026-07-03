"""[REQ:FS-27] ROS/Gazebo/RViz evidence surface: aggregate the evidence that a runnable-profile run
matches its profile -- the lifecycle nodes, the bridge/clock topics (/clock, /tf, /joint_states + the
gz-bridged sensor topics), the RViz displays, and the Gazebo worlds. Reads the REAL committed sources (the
AS-01 autonomy contract, the ros_gz_bridge config, mission.rviz, the world SDFs) -- no fabricated evidence.
The cockpit's Validate/System/Report panes fetch this via GET /ros/evidence."""
from __future__ import annotations

import os

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_RVIZ = os.path.join(_ROOT, "ros2_ws", "src", "stewie_rviz", "rviz", "mission.rviz")
_WORLDS = os.path.join(_ROOT, "ros2_ws", "src", "stewie_description", "worlds")
_GZBRIDGE = os.path.join(_ROOT, "ros2_ws", "src", "stewie_bringup", "config", "gz_bridge.yaml")
_ROS2_DEPLOY = os.path.join(_ROOT, "deploy", "ros2")

#: the clock/frame topics a running sim/bridge MUST carry for the run to be trustworthy.
_REQUIRED_CLOCK_TF = ("/clock", "/tf", "/tf_static", "/joint_states")


def _safe_yaml():
    """PyYAML if importable, else None -- the deployed backend may not carry it; the evidence surface
    degrades gracefully (the .rviz/gz configs go empty) rather than 500ing the whole endpoint."""
    try:
        import yaml
        return yaml
    except ImportError:
        return None


def _rviz_displays() -> list[dict]:
    yaml = _safe_yaml()
    if yaml is None or not os.path.exists(_RVIZ):
        return []
    cfg = yaml.safe_load(open(_RVIZ, encoding="utf-8")) or {}
    disps = cfg.get("Visualization Manager", {}).get("Displays", []) or []
    out = []
    for d in disps:
        topic = d.get("Topic")
        out.append({"name": d.get("Name"), "class": d.get("Class"),
                    "topic": topic.get("Value") if isinstance(topic, dict) else None})
    return out


def _gz_bridged_topics() -> list[str]:
    yaml = _safe_yaml()
    if yaml is None or not os.path.exists(_GZBRIDGE):
        return []
    data = yaml.safe_load(open(_GZBRIDGE, encoding="utf-8"))
    if not isinstance(data, list):
        return []
    names = {str(e["ros_topic_name"]) for e in data if isinstance(e, dict) and e.get("ros_topic_name")}
    return sorted(names)


def collect_ros_evidence() -> dict:
    """Real ROS/Gazebo/RViz evidence for the runnable profile -- from the committed contract + configs."""
    from stewie.bridge import autonomy_contract as AC
    nodes = [{"name": n.name, "role": n.role, "lifecycle": bool(n.lifecycle)} for n in AC.NODES.values()]
    bridge = [{"name": t.name, "type": t.msg, "qos": t.qos} for t in AC.TOPICS.values()
              if t.name in _REQUIRED_CLOCK_TF or t.name.startswith("/stewie/")]
    names = {t["name"] for t in bridge}
    rviz = _rviz_displays()
    worlds = sorted(f for f in os.listdir(_WORLDS) if f.endswith(".sdf")) if os.path.isdir(_WORLDS) else []
    tiers = sorted(f[len("Dockerfile."):] for f in os.listdir(_ROS2_DEPLOY)
                   if f.startswith("Dockerfile.")) if os.path.isdir(_ROS2_DEPLOY) else []
    return {
        "lifecycle_nodes": nodes,
        "n_nodes": len(nodes),
        "bridge_topics": bridge,
        "clock_present": "/clock" in names,
        "tf_present": "/tf" in names,
        "joint_states_present": "/joint_states" in names,
        "gz_bridged_topics": _gz_bridged_topics(),
        "rviz_displays": rviz,
        "n_rviz_displays": len(rviz),
        "gazebo_worlds": worlds,
        "container_tiers": tiers,
    }
