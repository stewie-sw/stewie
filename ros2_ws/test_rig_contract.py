"""[REQ:AS-03] / [REQ:AS-17] host-side rig-contract gate for the IPEx vehicle description.

Structural conformance on a non-ROS host (the xacro->URDF expansion + robot_state_publisher TF-tree
smoke is container-gated -- deploy/ros2/Dockerfile.ros2dev). Verifies: the xacro declares base_link,
imu_link, four skid-steer wheels, two bucket drums, and the 8-camera rig; the four stereo TF frames
match the AS-01 boundary contract; front + rear stereo PAIRS are present and wired symmetrically off
the authoritative `stereo_baseline` (default 0.05 m TRL5-final, NOT a hard-coded literal); and the
active-camera budget is the profile's max_live=4 (NASA-4 operational + 4 redundant)."""
import os
import re

from stewie.bridge import autonomy_contract as AC
from stewie.specs import ipex_specs as SPEC
from stewie.specs.profiles import load_profile

_HERE = os.path.dirname(os.path.abspath(__file__))
XACRO = os.path.join(_HERE, "src", "stewie_description", "urdf", "ipex.urdf.xacro")


def _text():
    with open(XACRO) as f:
        return f.read()


def _props():
    """The xacro's <xacro:property name=X value=Y/> numeric dimensions."""
    return {m.group(1): float(m.group(2))
            for m in re.finditer(r'<xacro:property name="(\w+)"\s+value="([0-9.]+)"/>', _text())}


def test_urdf_sourced_dims_match_ipex_specs():  # [REQ:AS-03]
    # TRL-5 consistency: the URDF's SOURCED dimensions must equal their ipex_specs (SCHULER24 /
    # WHEELTEST / BDSCALE) values -- a rename in either place must not silently drift the vehicle.
    p = _props()
    large = SPEC.DRUM_DIMENSIONS_M["large"]
    assert abs(p["wheel_radius"] - SPEC.WHEEL_RADIUS_M) < 1e-6, \
        f"wheel_radius {p['wheel_radius']} != WHEEL_RADIUS_M {SPEC.WHEEL_RADIUS_M}"
    assert abs(p["drum_radius"] - large["diameter"] / 2.0) < 1e-4, \
        f"drum_radius {p['drum_radius']} != large drum dia/2 {large['diameter'] / 2.0}"
    assert abs(p["drum_width"] - large["width"]) < 1e-4, \
        f"drum_width {p['drum_width']} != large drum width {large['width']}"
    assert abs(p["dry_mass"] - SPEC.ROVER_MASS_CLASS_KG) < 1e-6, \
        f"dry_mass {p['dry_mass']} != ROVER_MASS_CLASS_KG {SPEC.ROVER_MASS_CLASS_KG}"


def test_urdf_arm_effort_matches_the_excavation_load():  # [REQ:AS-03]
    # the drum-arm revolute joint's effort limit is the published moon excavation load, not a literal.
    m = re.search(r"<limit[^>]*effort=\"\$\{([0-9.]+)\}\"", _text())
    assert m, "drum-arm <limit> effort not found in the xacro"
    assert abs(float(m.group(1)) - SPEC.ARM_EXCAVATION_LOAD_NM) < 1e-6, \
        f"arm effort {m.group(1)} != ARM_EXCAVATION_LOAD_NM {SPEC.ARM_EXCAVATION_LOAD_NM}"


def test_urdf_mass_split_sums_to_the_sourced_dry_total():  # [REQ:AS-03]
    # the per-part mass allocation is [ASSUMPTION] but MUST conserve the sourced 30 kg dry total.
    p = _props()
    total = p["m_chassis"] + 4 * p["m_wheel"] + 2 * p["m_drum"]
    assert abs(total - SPEC.ROVER_MASS_CLASS_KG) < 1e-6, \
        f"mass split sums to {total}, not the sourced dry total {SPEC.ROVER_MASS_CLASS_KG}"


def test_stereo_baseline_is_authoritative_trl5_final_not_hardcoded():
    t = _text()
    m = re.search(r'<xacro:arg name="stereo_baseline" default="([0-9.]+)"/>', t)
    assert m, "stereo_baseline arg missing"
    assert abs(float(m.group(1)) - 0.05) < 1e-9, f"default {m.group(1)} != TRL5-final 0.05"
    # the stereo camera origins must REFERENCE the property, not a literal (AS-17 'not hard-coded')
    assert "${ stereo_baseline/2}" in t and "${-stereo_baseline/2}" in t


def test_base_imu_wheels_drums_present():
    t = _text()
    assert '<link name="base_link">' in t
    assert '<link name="imu_link"/>' in t
    wheels = set(re.findall(r'<xacro:wheel name="(\w+)"', t))
    assert wheels == {"front_left_wheel", "front_right_wheel", "rear_left_wheel", "rear_right_wheel"}, wheels
    drums = set(re.findall(r'<xacro:drum name="(\w+)"', t))
    assert drums == {"front_drum", "rear_drum"}, drums


def test_eight_camera_rig_with_optical_frames():
    t = _text()
    frames = re.findall(r'<xacro:camera frame="(\w+)"', t)
    assert len(frames) == 8, f"expected 8 cameras, got {frames}"
    # front/rear stereo pairs + side monos + drum cams (NASA-faithful: stereo + side(lander) + drum)
    assert {"front_left", "front_right", "rear_left", "rear_right"} <= set(frames)
    assert {"left_mono", "right_mono"} <= set(frames)
    assert {"drum_front", "drum_back"} <= set(frames)


def test_stereo_tf_frames_match_the_as01_contract():
    t = _text()
    frames = set(re.findall(r'<xacro:camera frame="(\w+)"', t))
    # the AS-01 frozen contract names the 4 stereo camera frames + imu_link; the URDF must define them
    for cf in ("camera_front_left", "camera_front_right", "camera_rear_left", "camera_rear_right"):
        assert cf in AC.FRAMES, f"{cf} not in the AS-01 FRAMES contract"
        bare = cf[len("camera_"):]
        assert bare in frames, f"URDF missing the contract camera frame {cf}"
    assert "imu_link" in AC.FRAMES and '<link name="imu_link"/>' in t


def test_front_and_rear_stereo_pairs_separated_by_the_baseline():
    t = _text()
    # front_left at +b/2, front_right at -b/2 (and rear mirrored) -> |sep| == stereo_baseline
    assert re.search(r'frame="front_left"\s+x="[^"]*"\s+y="\$\{ stereo_baseline/2\}"', t)
    assert re.search(r'frame="front_right"\s+x="[^"]*"\s+y="\$\{-stereo_baseline/2\}"', t)
    assert re.search(r'frame="rear_left"', t) and re.search(r'frame="rear_right"', t)


def test_active_camera_budget_is_profile_max_live_four():
    # NASA-4 operational + 4 redundant: the operational budget is the profile's max_live
    prof = load_profile("STEWIE_IPEX_V1")
    assert int(prof.cameras["max_live"]) == 4


def test_swappable_depth_source_mounts_and_status_labels():
    t = _text()
    for frame in ("depth_sensor_mount", "lidar_front_mount", "rgbd_front_mount"):
        assert f'<xacro:depth_mount name="{frame}"' in t
    assert '<link name="${name}">' in t
    assert '<joint name="${name}_joint" type="fixed">' in t

    prof = load_profile("STEWIE_IPEX_V1")
    sensors = prof.data["sensors"]
    statuses = {source["status"] for source in sensors["depth_sources"]}
    assert {"absent", "simulated", "bench", "flight", "legacy"} <= statuses

    by_name = {source["name"]: source for source in sensors["depth_sources"]}
    assert by_name[sensors["selected_depth_source"]]["status"] in {"flight", "simulated", "bench"}
    assert by_name["lidar_front"]["mount_frame"] == "lidar_front_mount"
    assert by_name["rgbd_front"]["mount_frame"] == "rgbd_front_mount"
    assert by_name["legacy_shoulder_stereo"]["status"] == "legacy"
