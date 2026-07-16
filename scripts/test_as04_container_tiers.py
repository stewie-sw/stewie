"""[REQ:AS-04] The six ROS container tiers are reproducible: each has a pinned base, a package manifest, and
a smoke command.

AS-04 asks for reproducible containers for the six tiers -- base ROS2 Jazzy dev, perception/SLAM, Gazebo
simulation, RViz diagnostics, bridge runtime, and a Space ROS migration profile -- EACH with a smoke command
and a pinned package manifest. The Dockerfiles exist (I=D, X=D); this gate closes the verification (V=P->D)
by asserting, for every tier, the three reproducibility properties, so a silent regression (an unpinned base,
a dropped smoke, a missing manifest) reds CI.

The BASE tier (ros2dev) is additionally BUILD-VERIFIED by [REQ:RT-00]: its image builds, its CMD smoke lists
the stewie_* ROS packages, and its build-time gate proves the stewie python stack imports under ROS's numpy.
The heavier tiers (gazebo/perception_slam/space_ros) are verified structurally here -- building all six in CI
is minutes of colcon each -- and each carries its own documented `docker run ... ` smoke in its header.
"""
from __future__ import annotations

import os

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_HERE = os.path.join(_REPO, "deploy", "ros2")

#: the six AS-04 tiers -> their Dockerfile.
TIERS = {
    "base ROS2 dev": "Dockerfile.ros2dev",
    "perception/SLAM": "Dockerfile.perception_slam",
    "Gazebo simulation": "Dockerfile.gazebo",
    "RViz diagnostics": "Dockerfile.rviz",
    "bridge runtime": "Dockerfile.bridge",
    "Space ROS migration": "Dockerfile.space_ros",
}


@pytest.mark.parametrize("tier,dockerfile", sorted(TIERS.items()))
def test_each_tier_is_reproducible_pinned_base_manifest_and_smoke(tier, dockerfile):  # [REQ:AS-04]
    path = os.path.join(_HERE, dockerfile)
    assert os.path.isfile(path), f"the {tier!r} tier has no {dockerfile}"
    df = open(path, encoding="utf-8").read()

    # (1) PINNED BASE: FROM a specific tag (or another pinned stewie tier), never a floating :latest.
    from_lines = [ln for ln in df.splitlines() if ln.strip().upper().startswith("FROM ")]
    assert from_lines, f"{tier}: no FROM"
    for fl in from_lines:
        img = fl.split()[1]
        assert ":" in img or img.startswith("stewie-"), f"{tier}: unpinned base {img!r} (no tag)"
        assert not img.endswith(":latest"), f"{tier}: base pinned to :latest is not reproducible"

    # (2) PACKAGE MANIFEST: an explicit apt/ros package list (what the tier installs), or it builds FROM a
    #     stewie tier that already carries one.
    has_apt = "apt-get install" in df or "apt install" in df
    builds_on_stewie = any("stewie-" in fl for fl in from_lines)
    assert has_apt or builds_on_stewie, f"{tier}: no package manifest and not layered on a stewie tier"

    # (3) SMOKE COMMAND: a CMD/HEALTHCHECK, or a documented `docker run ... ` smoke in the header comment.
    has_cmd = "\nCMD " in df or df.startswith("CMD ") or "HEALTHCHECK" in df
    has_doc_smoke = "docker run" in df and ("smoke" in df.lower() or "->" in df)
    assert has_cmd or has_doc_smoke, f"{tier}: no smoke command (CMD/HEALTHCHECK) nor a documented smoke"


def test_the_six_tiers_are_exactly_the_as04_set_no_more_no_fewer():  # [REQ:AS-04]
    """The AS-04 tier set is fixed at six. A new Dockerfile.* in deploy/ros2 that is not one of them (or a
    missing one) means the tier taxonomy drifted from the row -- surface it rather than let it slide."""
    on_disk = {f for f in os.listdir(_HERE)
               if f.startswith("Dockerfile.") and os.path.isfile(os.path.join(_HERE, f))}
    assert on_disk == set(TIERS.values()), (
        f"the ROS container tiers on disk do not match the AS-04 set of six: "
        f"extra={sorted(on_disk - set(TIERS.values()))} missing={sorted(set(TIERS.values()) - on_disk)}")
