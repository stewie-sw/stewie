"""[REQ:BA-06] xacro->SDF preserves the ARTICULATED (non-fixed) joint DOF of the REAL ipex description --
fixed joints correctly lump into their parent in SDF, so the invariant is the non-fixed joint count, not the
raw link count. Container-gated (needs the ROS `xacro` + `gz` tools): SKIPS cleanly on the CPU-only host/CI;
verified in the on-host stewie-ros2 / stewie-gazebo container."""
import shutil

import pytest

from stewie.interop.xacro_to_sdf import articulated_joint_count, xacro_to_sdf, xacro_to_urdf

_XACRO = "ros2_ws/src/stewie_description/urdf/ipex.urdf.xacro"
_HAVE_TOOLS = bool(shutil.which("xacro") and shutil.which("gz"))


@pytest.mark.skipif(
    not _HAVE_TOOLS,
    reason="[REQ:BA-06] xacro->SDF needs the ROS xacro+gz tools (container-gated; verified in stewie-ros2/gazebo)",
)
def test_ba06_xacro_to_sdf_preserves_articulated_joints():  # [REQ:BA-06]
    urdf = xacro_to_urdf(_XACRO, {"stereo_baseline": "0.2"})
    sdf = xacro_to_sdf(_XACRO, {"stereo_baseline": "0.2"})
    n = articulated_joint_count(urdf)
    assert n > 0 and articulated_joint_count(sdf) == n     # articulated DOF preserved through fixed-joint lumping
    assert 'name="ipex"' in urdf and "ipex" in sdf         # model name survives


def test_ba06_articulated_joint_count_on_the_real_ipex_urdf():  # [REQ:BA-06] (on-host: counting on real data)
    with open("ros2_ws/src/stewie_description/urdf/ipex.expanded.urdf") as f:
        urdf = f.read()
    # the REAL ipex has 8 articulated (non-fixed) joints of its 28 (20 fixed); container-verified 8==8 to SDF
    assert articulated_joint_count(urdf) == 8
