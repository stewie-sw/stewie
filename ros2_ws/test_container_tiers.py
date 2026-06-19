"""[REQ:AS-04] host-side container-tier gate for the ROS2 deployment images.

The AS-04 acceptance names six container tiers; this gate verifies the model of the ones that are
ACTUALLY built (base ROS2 Jazzy dev, RViz diagnostics, Gazebo simulation) and documents the three
that are deferred (perception/SLAM, bridge runtime, Space ROS migration) so AS-04 stays honest at
I=P, not over-claimed. The docker BUILD + smoke RUN themselves are container-gated (they need a
ROS2 Jazzy daemon + `--network=host`); here we assert the Dockerfiles encode the reproducible-tier
contract: a single base, FROM-base inheritance, a pinned apt manifest, the check_urdf build gate,
and a smoke CMD on every tier.
"""
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
DEPLOY = os.path.join(_ROOT, "deploy", "ros2")

# the tiers AS-04 enumerates; only the first three are built (the rest are deferred -> I=P)
ACCEPTANCE_TIERS = ("base_ros2dev", "perception_slam", "gazebo", "rviz", "bridge", "space_ros")
BUILT_TIERS = {"base_ros2dev": "Dockerfile.ros2dev",
               "rviz": "Dockerfile.rviz",
               "gazebo": "Dockerfile.gazebo"}
DEFERRED_TIERS = ("perception_slam", "bridge", "space_ros")


def _text(fname):
    with open(os.path.join(DEPLOY, fname)) as f:
        return f.read()


def test_built_tiers_are_a_subset_of_the_acceptance_set():
    # honesty: every tier we ship is one AS-04 named, and the three deferred ones are not yet built
    assert set(BUILT_TIERS) <= set(ACCEPTANCE_TIERS)
    assert set(DEFERRED_TIERS) <= set(ACCEPTANCE_TIERS)
    assert set(BUILT_TIERS).isdisjoint(DEFERRED_TIERS)
    for fname in BUILT_TIERS.values():
        assert os.path.exists(os.path.join(DEPLOY, fname)), fname
    # the deferred tiers must NOT have silently appeared as a built Dockerfile claiming completeness
    for name in DEFERRED_TIERS:
        assert name not in BUILT_TIERS


def test_base_tier_is_pinned_jazzy_with_the_colcon_and_urdf_gate():
    t = _text("Dockerfile.ros2dev")
    assert "FROM ros:jazzy-ros-base" in t                      # one pinned base image
    assert "python3-colcon-common-extensions" in t             # the workspace builder (AS-02 colcon)
    assert "ros-jazzy-xacro" in t                              # xacro -> URDF expansion (AS-03)
    assert "check_urdf" in t                                   # the URDF build gate runs at image build
    assert "colcon build" in t                                 # the workspace actually builds in-image


def test_diagnostic_and_sim_tiers_inherit_from_the_single_base():
    # RViz + Gazebo layer ON the base -- never a second base image (one reproducible root)
    rviz, gz = _text("Dockerfile.rviz"), _text("Dockerfile.gazebo")
    assert "FROM stewie-ros2dev:jazzy" in rviz
    assert "FROM stewie-ros2dev:jazzy" in gz
    assert "ros-jazzy-rviz2" in rviz                           # RViz tier adds rviz2 + grid_map plugin
    assert "grid-map-rviz-plugin" in rviz
    assert "ros-jazzy-ros-gz" in gz                            # Gazebo tier adds ros_gz (Harmonic bridge)


def test_every_built_tier_has_a_smoke_command():
    # AS-04: "each container has a smoke command" -- a CMD that exercises the tier's reason to exist
    for fname in BUILT_TIERS.values():
        t = _text(fname)
        assert "CMD [" in t, f"{fname} has no smoke CMD"
        assert "source /opt/ros/jazzy/setup.bash" in t, fname


def test_pinned_apt_manifest_uses_no_floating_upgrade():
    # reproducibility: tiers install explicit ros-jazzy-* packages, not `apt-get upgrade` floats
    for fname in BUILT_TIERS.values():
        t = _text(fname)
        assert "apt-get install" in t
        assert "apt-get upgrade" not in t, f"{fname} floats its package set"
