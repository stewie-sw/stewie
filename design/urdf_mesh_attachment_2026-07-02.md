# IPEx URDF mesh attachment — plan + status (2026-07-02)

**Goal (per Aaron):** the ROS/Gazebo rover should *look* like the articulated EZ-RASSOR (as Godot already
renders it) while **keeping IPEx specs** — i.e. attach the EZ-RASSOR meshes to the URDF `<visual>`, keep
the IPEx-spec primitive `<collision>` + inertials + joint limits, and (if ever available) swap in a real
IPEx mesh. Articulation + specs are already done (see `test_rig_contract.py`): 4 continuous wheels, 2
revolute drum arms + drum spin, dims/masses guarded against `ipex_specs`.

## Status: DONE — wired + render-verified

The EZ-RASSOR per-link meshes are converted to STL, baked to IPEx dims, attributed (MIT) under
`ros2_ws/src/stewie_description/meshes/`, and wired into the URDF `<visual>` (chassis/wheel/drum/arm);
the `<collision>` stays primitive (cylinder/box) for fast physics. Verified NOT deferred: the xacro
expands (`xacro` in stewie-ros2dev:jazzy, `check_urdf` parses the 18-child tree), and the assembled
robot was rendered headless (yourdfpy + trimesh under xvfb) to
`2026-07-02_ipex_urdf_ezrassor_render.png` — a recognizable articulated RASSOR/IPEx rover: central
chassis, 4 spoked wheels, 2 full-width bucket drums at the arm ends, 8-camera rig frames. Guarded by
`test_rig_contract.py::test_urdf_visual_uses_the_ezrassor_meshes_collision_stays_primitive` [REQ:AS-03].

Remaining fine-tuning (cosmetic, not blocking): the drum barrel scale reads a touch large in the render;
tune the drum non-uniform scale + re-bake if desired. A real IPEx mesh can swap in per-link if CAD
becomes available (none is public).

## Measured mesh dims vs IPEx targets (the wiring inputs)

From `meshes/MESH_TRANSFORMS.json` (trimesh bounding boxes) — the native meshes do NOT match IPEx dims,
so the wiring must transform each:

| link | native extents (m) | IPEx target | wiring transform |
|---|---|---|---|
| rover_body | 0.628 × 0.226 × 0.341 | chassis ~0.46 long | center; uniform scale ~0.73 (length match) |
| wheel | 0.358 × 0.358 × 0.283 | dia 0.305, width 0.18, axle +Y | rot Z→Y (−90° about X); uniform scale 0.852 |
| drum | 0.371 × 0.371 × **1.005** | dia 0.4371, width 0.3526, axle +Y | rot Z→Y; **non-uniform** (barrel 1.005→0.353) — verify this mesh's barrel axis in RViz first |
| drum_arm | 0.549 × 0.224 × 0.188, center +0.165 X | reach 0.32, pivot at arm root | translate pivot (−X) to origin; scale ~0.58 |

**Open item for RViz:** `sidecar.gd` references a `ROVER_SCALE := 0.35` "URDF mesh scale macro" that does
NOT exist in the current URDF (0 meshes today). That 0.35 does not reconcile with the per-link
bounding-box→IPEx-dim scales above, so the sidecar comment is stale; the wiring scale is per-link
(table), verified visually, not a single 0.35 macro.

## Plan (do at the container-gated step)
1. In the ROS2 dev container, add per-link `<visual><geometry><mesh filename="package://stewie_description/meshes/<part>.stl" scale="…"/></geometry><origin …/></visual>` using the table transforms; keep the primitive `<collision>`.
2. `ros2 launch` robot_state_publisher + RViz2; confirm each part sits at its joint frame and the drum/arm pivots are correct; tune scale/rpy/xyz until the articulated rover matches Godot.
3. Re-export the scaled/oriented meshes (bake the transform) so the URDF references are scale=1, origin=0.
4. Then swap to a real IPEx mesh per-link if a CAD source ever becomes available (none is public today).
