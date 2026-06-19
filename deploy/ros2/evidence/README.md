# §25 container-execution evidence (AS-02 / AS-03 / AS-04 / AS-05 / AS-06)

Recorded container runs for the ROS2 deployment tiers, rebuilt **from current source** (after the
2026-06-18 0.05 m stereo re-freeze) so the smokes reflect the live workspace, not a stale image.
This is the `X` (execution) evidence the §25 release gate (`scripts/release_gate.py`) names as the
gate for the five container-tier rows.

Host: archimedes · Docker 29.5.3 (overlay2, rootless-capable) · all builds `--network=host`.

## Image digests (reproducibility anchor)

| tier | image | digest |
|---|---|---|
| base (ROS2 Jazzy dev) | `stewie-ros2dev:jazzy` | `sha256:6d4dc8c8417d1b239d4a8bf64e76fe086e19927063fb2c24ef62eada80bedb51` |
| RViz diagnostics | `stewie-rviz:jazzy` | `sha256:dac247c2554cae387ce43ae0e816d472c23b13ead3c0321008661300e50475cf` |
| Gazebo simulation | `stewie-gazebo:jazzy` | `sha256:6c3d87159309a1aa5ba3ba1886220354b8c53f4c58c5a32226a86406b507badd` |

## What ran, and what it proves

| Row | Smoke | Result | Proves |
|---|---|---|---|
| **AS-02** | `docker run --rm stewie-ros2dev:jazzy` (`ros2 pkg list \| grep ^stewie_`) | rc=0, **10/10 packages** | the workspace colcon-builds and all 10 `stewie_*` packages are discoverable in-container |
| **AS-03** | `check_urdf` at image build (`xacro ipex.urdf.xacro \| check_urdf`) | rc=0, **"Successfully Parsed XML"** | the IPEx URDF parses to a valid TF tree: `base_link` → 8 cameras (+optical), both bucket drums (`front_drum_arm`→`front_drum`), 4 skid-steer wheels, `imu_link` |
| **AS-04** | all three tiers build + smoke (base / FROM-base rviz / FROM-base gazebo) | 3/3 build rc=0, 3/3 smoke rc=0 | the reproducible **tier model** works: one pinned base, two tiers inherit it, each smokes. (3 of 6 named tiers; perception/SLAM, bridge, Space ROS still deferred.) |
| **AS-05** | `docker run --rm stewie-rviz:jazzy` (rviz2 headless on `mission.rviz` under xvfb) | rc=0, **"SMOKE OK: mission.rviz loaded, no plugin-load failures"** | the mission RViz config loads in a real rviz2 with the grid_map plugin; no missing-plugin failures |
| **AS-06** | `docker run --rm stewie-gazebo:jazzy` (gz Harmonic sim + ros_gz bridge) | rc=0, **"SMOKE OK: physics/proprioception contract topics publish"** | gz sim launches and publishes the contract topics: `/clock /cmd_vel /joint_states /robot_description /tf /tf_static /stewie/imu /stewie/wheel_odom /stewie/truth/pose /stewie/camera/front_{left,right}/image` (PUB OK confirmed on clock, wheel_odom, joint_states, imu, front_left image, truth/pose) |

Captured smoke transcripts: `_smoke_ros2dev_pkglist.txt`, `_smoke_rviz.txt`, `_smoke_gazebo.txt`
(the verbose `_build_*.log` apt/colcon transcripts are git-ignored — regenerable from the commands below).

## Reproduce

```bash
cd /mnt/projects/stewie/code
docker build --network=host -f deploy/ros2/Dockerfile.ros2dev -t stewie-ros2dev:jazzy .   # base; runs check_urdf
docker build --network=host -f deploy/ros2/Dockerfile.rviz    -t stewie-rviz:jazzy    .   # FROM base
docker build --network=host -f deploy/ros2/Dockerfile.gazebo  -t stewie-gazebo:jazzy  .   # FROM base
docker run --rm stewie-ros2dev:jazzy        # AS-02 package discovery
docker run --rm stewie-rviz:jazzy           # AS-05 rviz config load
docker run --rm stewie-gazebo:jazzy         # AS-06 gz topic publish
```

## What this does NOT prove (still gated/deferred — release-gate `deferred` set)

- **AS-06 contact/collision** is named in the acceptance but the smoke verifies topic *publishing*
  only — contact/collision physics is not demonstrated here (its gz tests assert 0 contacts).
- **AS-03 collision geometry / inertials** are not separately asserted by `check_urdf` (a clean parse
  needs only the kinematic tree); the host `test_rig_contract` covers structure, not mass properties.
- **AS-05** the host test confirms RobotModel + config structure, not every one of the ~13 named displays.
- **AprilTag 12.7 mm** pose re-confirm (needs `apriltag_ros` wired into the image), **live Chrono
  producer** (P7), **dense MVS / COLMAP RMSE** (CUDA), and the **Space ROS / perception / bridge**
  container tiers remain deferred.

## Scorecard recommendation (NOT applied — committee-scorecard call, like the V column)

Backed by the recorded runs above, the honest per-row promotion is:

| Row | now (I/X) | recommended | basis |
|---|---|---|---|
| AS-02 | N/N | **I=D, X=D** | 10/10 packages build + discoverable — acceptance fully met |
| AS-03 | N/N | **X=D**; I=D only after collision/inertial confirmation | URDF parses to full TF tree; mass props unverified |
| AS-04 | P/N | **X=P** | 3 of 6 tiers build + smoke; 3 deferred |
| AS-05 | N/N | **X=D**; I=D after full display-set confirmation | mission.rviz loads; not every display asserted |
| AS-06 | N/N | **X=D**; I stays **P** | topics publish; contact/collision not demonstrated |

The `X` column is a factual "did it execute" claim and is now recorded + reproducible; `I=D` and the
`V` column carry acceptance-completeness judgment and stay the human's call.
