#!/usr/bin/env bash
# [RT-03] Headless Gazebo camera-render + read-only frame relay entrypoint (compose 'gzcam' profile).
#
# Runs the gz-sim IPEx lunar sim headless and pushes ONE rendered camera as base64 JPEG to the RT-04
# collector, so the browser "Gazebo View" pane shows a live, evidence-only render. gz + the camera
# feeder run in the SAME container (shared /dev/shm -> DDS SHM transport, no cross-container UDP
# profile needed), on an ISOLATED ROS_DOMAIN_ID so this never perturbs the live domain-0 rover/nav
# stack behind RT-04.
#
# SOFTWARE RENDER (llvmpipe): the host nvidia-container-runtime injects compute (nvidia-smi) but NOT
# the graphics driver (no libGLX_nvidia / libEGL_nvidia), and a *visible-but-undriveable* GPU makes
# gz-sim's ogre2 pick EGL and segfault. So this service takes NO GPU: with the GPU hidden, Mesa uses
# llvmpipe cleanly under an auth-free Xvfb + GLX. Real render, CPU-only (~4 cores), a few Hz.
#
# READ-ONLY: the feeder holds zero ROS publishers; it only subscribes to the rendered image and relays
# pixels. There is no path from the browser pane to /cmd_vel or any service.
set -o pipefail

export DISPLAY="${DISPLAY:-:99}"
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-7}"
export LIBGL_ALWAYS_SOFTWARE="${LIBGL_ALWAYS_SOFTWARE:-1}"
export GALLIUM_DRIVER="${GALLIUM_DRIVER:-llvmpipe}"
# Resolve the rover STL meshes (model://stewie_description/meshes/...) from the source tree baked into
# the image (colcon does not install them into the share dir), else the rover renders bodiless.
export GZ_SIM_RESOURCE_PATH="${GZ_SIM_RESOURCE_PATH:-/ws/src:/ws/install/stewie_description/share}"
export STEWIE_CAM_TOPIC="${STEWIE_CAM_TOPIC:-/stewie/camera/front_left/image}"
export STEWIE_CAM_OUT_TOPIC="${STEWIE_CAM_OUT_TOPIC:-/stewie/camera/front_left/jpeg}"

# Auth-free virtual X display so gz's ogre2 GLX opens it without an Xauthority cookie.
Xvfb "$DISPLAY" -screen 0 1280x1024x24 -ac >/tmp/xvfb.log 2>&1 &
sleep 3

source /opt/ros/jazzy/setup.bash
source /ws/install/setup.bash

# gz server + world + rover spawn + ros_gz bridge (headless).
ros2 launch stewie_bringup gz_sim.launch.py >/tmp/gzlaunch.log 2>&1 &
GZ_PID=$!

# Give gz + the bridge time to come up (ogre2 camera render init on llvmpipe is slow). The feeder is
# tolerant of "no frames yet" -- it subscribes and pushes only once real frames arrive -- so a fixed
# settle is more robust than a discovery-latency-sensitive `ros2 topic hz` gate. Log the camera rate
# for the record once (best-effort, non-blocking to the feeder).
sleep 25
( timeout 10 ros2 topic hz "$STEWIE_CAM_TOPIC" 2>/dev/null | head -1 \
  | sed "s/^/[gzcam] $STEWIE_CAM_TOPIC /" || true ) &

# Read-only camera feeder -> RT-04 collector ingest (127.0.0.1:9091). host-net -> loopback works.
python3 /camera_feeder.py >/tmp/camfeeder.log 2>&1 &
FEED_PID=$!

# If either half dies, exit so compose 'restart: unless-stopped' brings the pair back cleanly.
wait -n "$GZ_PID" "$FEED_PID"
echo "[gzcam] a child exited; shutting down for restart"
kill "$GZ_PID" "$FEED_PID" 2>/dev/null
exit 1
