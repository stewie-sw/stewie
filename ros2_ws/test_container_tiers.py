"""[REQ:AS-04] host-side container-tier gate for the ROS2 deployment images.

The AS-04 acceptance names six container tiers; this gate verifies the reproducible-tier CONTRACT
of all six now that every Dockerfile exists: base ROS2 Jazzy dev, RViz diagnostics, Gazebo
simulation, perception/SLAM, bridge runtime, and the Space ROS migration profile. Each layers on
the single base image (never a second base), installs an explicit pinned `ros-jazzy-*` apt manifest
(no floating `apt-get upgrade`), and carries a smoke CMD that exercises the tier's reason to exist.
The docker BUILD + smoke RUN themselves are container-gated (they need a ROS2 Jazzy daemon +
`--network=host`); here we assert the host-side contract every image encodes: a single base,
FROM-base inheritance, a pinned apt manifest, the check_urdf build gate, and a smoke CMD.
"""
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
DEPLOY = os.path.join(_ROOT, "deploy", "ros2")

# the six tiers AS-04 enumerates -> every one now has a Dockerfile (three shipped, three added here).
ACCEPTANCE_TIERS = ("base_ros2dev", "perception_slam", "gazebo", "rviz", "bridge", "space_ros")
BUILT_TIERS = {"base_ros2dev": "Dockerfile.ros2dev",
               "rviz": "Dockerfile.rviz",
               "gazebo": "Dockerfile.gazebo",
               "perception_slam": "Dockerfile.perception_slam",
               "bridge": "Dockerfile.bridge",
               "space_ros": "Dockerfile.space_ros"}
# tiers that layer on the base (everything except the base itself)
DERIVED_TIERS = ("rviz", "gazebo", "perception_slam", "bridge", "space_ros")


def _text(fname):
    with open(os.path.join(DEPLOY, fname)) as f:
        return f.read()


def test_every_acceptance_tier_has_a_built_dockerfile():
    # AS-04 names six tiers; every one now has a Dockerfile (the three deferred tiers are now built).
    assert set(BUILT_TIERS) == set(ACCEPTANCE_TIERS)
    for name, fname in BUILT_TIERS.items():
        assert os.path.exists(os.path.join(DEPLOY, fname)), f"{name} -> {fname}"


def test_base_tier_is_pinned_jazzy_with_the_colcon_and_urdf_gate():
    t = _text("Dockerfile.ros2dev")
    assert "FROM ros:jazzy-ros-base" in t                      # one pinned base image
    assert "python3-colcon-common-extensions" in t             # the workspace builder (AS-02 colcon)
    assert "ros-jazzy-xacro" in t                              # xacro -> URDF expansion (AS-03)
    assert "check_urdf" in t                                   # the URDF build gate runs at image build
    assert "colcon build" in t                                 # the workspace actually builds in-image


def test_every_derived_tier_inherits_from_the_single_base():
    # every non-base tier layers ON stewie-ros2dev:jazzy -- never a second base image (one root)
    for name in DERIVED_TIERS:
        t = _text(BUILT_TIERS[name])
        assert "FROM stewie-ros2dev:jazzy" in t, name
        # exactly one FROM line -> no multi-stage second base sneaking in
        assert sum(1 for ln in t.splitlines() if ln.strip().startswith("FROM ")) == 1, name


def test_diagnostic_and_sim_tiers_add_their_own_packages():
    # RViz + Gazebo each add the packages that define the tier
    rviz, gz = _text("Dockerfile.rviz"), _text("Dockerfile.gazebo")
    assert "ros-jazzy-rviz2" in rviz                           # RViz tier adds rviz2 + grid_map plugin
    assert "grid-map-rviz-plugin" in rviz
    assert "ros-jazzy-ros-gz" in gz                            # Gazebo tier adds ros_gz (Harmonic bridge)


def test_perception_slam_tier_adds_the_slam_packages():
    # perception/SLAM tier: the stereo->points + odom/imu-fusion + observed-DEM stack (AS-07/08/10)
    t = _text("Dockerfile.perception_slam")
    assert "ros-jazzy-cv-bridge" in t                          # image<->cv seam for stereo perception
    assert "ros-jazzy-tf2-ros" in t                            # TF for the localization/mapping frames
    # its smoke discovers the three SLAM-stack packages that layer here
    for exe in ("perception", "localization", "mapping"):
        assert exe in t, f"perception_slam smoke omits {exe}"


def test_bridge_tier_adds_the_boundary_contract_runtime():
    # bridge runtime tier: the AS-01 boundary-contract egress (control -> cmd_vel, vehicle_interface)
    t = _text("Dockerfile.bridge")
    assert "ros-jazzy-ros-gz-bridge" in t                      # the gz<->ROS2 bridge runtime (AS-06 seam)
    # its smoke discovers the two boundary-contract packages that run here
    for exe in ("control", "vehicle_interface"):
        assert exe in t, f"bridge smoke omits {exe}"


def test_space_ros_tier_encodes_the_migration_profile():
    # Space ROS migration profile: swap the RMW to the flight-DDS CycloneDDS and assert it is active
    t = _text("Dockerfile.space_ros")
    assert "ros-jazzy-rmw-cyclonedds-cpp" in t                 # the Space-ROS-mandated DDS vendor
    assert "RMW_IMPLEMENTATION=rmw_cyclonedds_cpp" in t        # profile pins the RMW at image scope
    assert "rmw_cyclonedds_cpp" in t                           # smoke asserts the active middleware


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
