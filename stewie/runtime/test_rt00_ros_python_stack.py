"""[REQ:RT-00] The ROS image carries the STEWIE python stack, so a live-spine rclpy node can import + run
the replay loop -- and that loop runs headless on a real DEM slice.

WHY THIS FILE EXISTS. RT-00 is the prerequisite that unblocks RS-05 and RT-03 (the ROS perception/mapping
rows). `Dockerfile.ros2dev` colcon-builds the ROS workspace, but a live rclpy node's real job is to import
the conserved python runtime (`stewie.runtime.replay_loop.run_replay` et al) and drive it -- and the ROS
image did NOT carry that python stack (its CMD only checked `ros2 pkg list`). So an rclpy node inside the
container would `ModuleNotFoundError: No module named 'stewie'`. This row installs the numpy/scipy/pydantic/
gymnasium the runtime needs (PINNED) + the monorepo into the container's SYSTEM python -- the same
interpreter rclpy uses.

TWO HALVES, verified two ways:
  * the DOCKERFILE carries the pinned install + a BUILD-TIME import gate (asserted statically here, so CI
    stays cheap -- building the full ROS image in CI is minutes of colcon), AND
  * `run_replay` actually RUNS HEADLESS ON A REAL DEM SLICE -- the exact operation the container performs --
    asserted here on the host against the real Haworth DEM (the same code, same call, that a live node runs).
The build-time gate (`python3 -c "from stewie.runtime.replay_loop import run_replay"` in the image RUN) means
a broken import FAILS THE IMAGE; the in-container run was verified by `docker run` at build time.
"""
from __future__ import annotations

import os

import numpy as np
import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_DOCKERFILE = os.path.join(_REPO, "deploy", "ros2", "Dockerfile.ros2dev")


def test_the_ros_dockerfile_installs_the_pinned_python_stack_with_an_import_gate():  # [REQ:RT-00]
    """The ROS image must carry the python stack a live rclpy node imports -- pinned, monorepo, gated."""
    df = open(_DOCKERFILE, encoding="utf-8").read()
    # the pinned stewie-added deps (the reproducible manifest). numpy is DELIBERATELY not pinned by us --
    # it comes from ROS (debian numpy 1.26.4, which rclpy is built against); forcing the host's 2.4.6 both
    # fails (cannot uninstall a debian-managed numpy) and would risk breaking rclpy under a major bump.
    for pin in ("scipy==", "pydantic==", "gymnasium=="):
        assert pin in df, f"the ROS image does not pin {pin!r} -- the python manifest is not reproducible"
    assert "numpy==" not in df, "the ROS image pins numpy -- it must inherit ROS's (rclpy is built on it)"
    assert "--ignore-installed" in df, "pip will try to remove the debian numpy and fail (RECORD not found)"
    # the monorepo packages a live node imports -- incl. the separate `packages/` (stewie_bodies/forge),
    # which run_replay pulls transitively (stewie.specs.bodies -> stewie_bodies).
    for pkg in ("COPY stewie", "COPY dart", "COPY lode", "COPY packages"):
        assert pkg in df, f"the ROS image does not carry the {pkg!r} package -- rclpy nodes cannot import it"
    assert "packages/stewie-bodies" in df, "the ROS image omits stewie_bodies -- run_replay's import fails"
    # the BUILD-TIME import gate: a broken run_replay import (incl. numpy-1.26 incompat) fails the image
    assert "from stewie.runtime.replay_loop import run_replay" in df, \
        "the Dockerfile has no build-time import gate -- a broken stack would ship silently"
    # pip must be available (ros:jazzy-ros-base ships no bare `pip`; the build failed 127 until fixed)
    assert "python3-pip" in df and "python3 -m pip install" in df, \
        "the image installs via bare `pip` -- ros:jazzy-ros-base has no pip on PATH (exit 127)"


def test_run_replay_runs_headless_on_a_real_dem_slice():  # [REQ:RT-00]
    """The operation the container performs: import run_replay and drive it over a REAL DEM slice, headless,
    producing a typed EvidenceBundle. This is the exact call a live rclpy node makes -- verified on the host
    against the real Haworth DEM (the container runs the identical code)."""
    from stewie.runtime.replay_loop import EvidenceBundle, run_replay
    from stewie.server import state as S

    dem, _ = S.moon_dem("haworth")
    z = np.asarray(dem[0], dtype=float)[500:560, 1700:1760]      # the real, traversable replay frame
    cell = float(dem[1])
    assert np.isfinite(z).all() and float(z.max() - z.min()) > 0.0, "the DEM slice is not real terrain"

    S._WSS = None                                                # a fresh world-state service
    wss = S.world_state_service()
    bundle = run_replay(z, cell, (5 * cell, 5 * cell), (50 * cell, 50 * cell), wss=wss)
    assert isinstance(bundle, EvidenceBundle), "run_replay did not produce a typed EvidenceBundle"
    assert wss.verify_chain(), "the headless replay's world-transaction chain did not verify"


@pytest.mark.skipif(os.environ.get("STEWIE_RUN_DOCKER_TESTS") != "1",
                    reason="in-container run is a build-time/opt-in check (heavy image build); "
                           "the Dockerfile import gate + the host run above cover the acceptance in CI")
def test_run_replay_imports_inside_the_built_ros_image():  # [REQ:RT-00]
    """OPT-IN heavy check: if the stewie-ros2dev:jazzy image is built, prove `import run_replay` resolves
    INSIDE it (the actual rclpy interpreter). Skipped in CI (multi-minute colcon build); run with
    STEWIE_RUN_DOCKER_TESTS=1 after `docker build -f deploy/ros2/Dockerfile.ros2dev`."""
    import subprocess
    r = subprocess.run(
        ["docker", "run", "--rm", "stewie-ros2dev:jazzy", "bash", "-lc",
         "source /opt/ros/jazzy/setup.bash && python3 -c "
         "'from stewie.runtime.replay_loop import run_replay; print(\"OK\")'"],
        capture_output=True, text=True, timeout=120)
    assert r.returncode == 0 and "OK" in r.stdout, f"in-container import failed: {r.stderr[-400:]}"
