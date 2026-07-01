# §25 Container-Execution Evidence (AS-02 / AS-03 / AS-04 / AS-05 / AS-06)

Recorded container runs for the ROS2 deployment tiers, rebuilt from current source on 2026-07-01.
These are the execution records behind the PRD AS scorecard updates.

Host: local workspace · Docker 29.6.1 linux/amd64 · all builds `--network=host`.

## Image Digests

| tier | image | digest |
|---|---|---|
| base ROS2 Jazzy dev | `stewie-ros2dev:jazzy` | `sha256:21d3d6224a3bbd0f6ff5b661fcdd15ce8746af96fcb46408c9cc4582cb14a3f7` |
| RViz diagnostics | `stewie-rviz:jazzy` | `sha256:fbe0045424edcc9e080c25bd691d497150a830cfe7dfe3162e1adf5ca9db5b83` |
| Gazebo simulation | `stewie-gazebo:jazzy` | `sha256:74b302596039f2d53a30cd26e4c0427a35f505ffde7efce289a442b0d648ad8f` |

## What Ran

| Row | Smoke | Result | Proves |
|---|---|---|---|
| AS-02 | `docker run --rm stewie-ros2dev:jazzy` with `ros2 pkg list`, `colcon test`, and `colcon test-result --all` | rc=0; 10/10 `stewie_*` packages discoverable; seven ament_python package smoke tests pass | the ROS2 workspace skeleton builds, installs, discovers, and has a non-zero test gate in-container |
| AS-03 | `check_urdf` during base image build after `xacro ipex.urdf.xacro` | rc=0; `Successfully Parsed XML`; root `base_link` has 18 expected children including camera rig, drum, wheels, IMU, `depth_sensor_mount`, `lidar_front_mount`, and `rgbd_front_mount` | the current IPEx URDF/Xacro/SDF rig expands and parses as a valid TF tree with collision/inertial/joint-limit artifacts and swappable depth-source mounts present in source; profile tests prove absent/simulated/bench/flight/legacy sensor labels |
| AS-04 | base, RViz, and Gazebo images build and smoke | 3/3 built tiers pass; 3/6 accepted tiers exist | the tier model works for base ROS2 dev, RViz diagnostics, and Gazebo simulation; perception/SLAM, bridge runtime, and Space ROS remain deferred |
| AS-05 | `docker run --rm stewie-rviz:jazzy` loading `mission.rviz` under Xvfb | rc=0; `SMOKE OK: mission.rviz loaded, no plugin-load failures` | the RViz mission dashboard loads in real rviz2; host tests verify the display/topic contract |
| AS-06 | `docker run --rm stewie-gazebo:jazzy` with gz sim + ros_gz bridge | rc=0; `SMOKE OK: physics/proprioception/contact/depth contract topics publish` | Gazebo launches and publishes `/clock`, `/stewie/wheel_odom`, `/joint_states`, `/stewie/imu`, `/stewie/contact`, `/stewie/perception/points`, `/stewie/camera/front_left/image`, and `/stewie/truth/pose`; `/cmd_vel` is present |

Captured smoke transcripts: `_smoke_ros2dev_pkglist.txt`, `_smoke_rviz.txt`, `_smoke_gazebo.txt`.
Verbose `_build_*.log` files are regenerable from the commands below.

## Reproduce

```bash
cd /mnt/projects/stewie/code
docker build --network=host -f deploy/ros2/Dockerfile.ros2dev -t stewie-ros2dev:jazzy .
docker build --network=host -f deploy/ros2/Dockerfile.rviz -t stewie-rviz:jazzy .
docker build --network=host -f deploy/ros2/Dockerfile.gazebo -t stewie-gazebo:jazzy .
docker run --rm stewie-ros2dev:jazzy bash -lc 'source /opt/ros/jazzy/setup.bash && source install/setup.bash && ros2 pkg list | grep -E "^stewie_" | sort && cd /ws && colcon test --event-handlers console_direct+ && colcon test-result --all'
docker run --rm stewie-rviz:jazzy
docker run --rm stewie-gazebo:jazzy
```

## PRD Marking Applied

| Row | Marked | Basis |
|---|---|---|
| AS-02 | `I=D X=D V=D Q=NA` | all named packages build, discover, and pass the container smoke |
| AS-03 | `I=D X=D V=D Q=G` | URDF parses; SDF/Gazebo artifacts exist; swappable LiDAR/RGB-D mounts and explicit absent/simulated/bench/flight/legacy sensor-profile labels are covered by host and container evidence |
| AS-04 | `I=P X=P V=P Q=NA` | 3 of 6 named tiers build and smoke |
| AS-05 | `I=D X=D V=D Q=NA` | deterministic host display/topic tests plus real rviz2 load smoke |
| AS-06 | `I=D X=D V=D Q=N` | Gazebo robot/sensor seam publishes proprioception, contact/collision, camera, selected depth-cloud, command, clock, TF, and truth-denied bridge topics in-container |

## Still Not Proven

- AS-04 perception/SLAM, bridge runtime, and Space ROS migration container tiers.
- Deferred non-container capabilities named by `scripts/release_gate.py`: live Chrono producer, AprilTag 12.7 mm ROS pose confirmation, dense MVS/COLMAP RMSE, and Space ROS migration.
