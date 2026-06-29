# Loop-closing visual SLAM with DEM anchoring on real lunar-analogue terrain: a results write-up

**Result in one line.** On the real DLR S3LI `s3li_crater` Mt Etna traverse, a vision-only stereo SLAM
pipeline (SuperPoint+LightGlue VO, visual loop closure, full SE(3) pose graph, online DEM height-normal
anchoring) drives the absolute trajectory error from **93.3 m (VO) to 7.99 m (SE3 ATE)**, below the
21.43 m the reference paper arXiv:2603.17229 reports on the same sequence. Every estimate is computed
without ground truth (truth firewall I3); ground truth enters only at scoring.

---

## 1. Problem and dataset

The reference paper (SuperPoint+LightGlue stereo VO, then loop closure and DEM anchoring) reports
94.01 m to 21.43 m on `s3li_crater`. The goal here is twofold: reproduce that result on the real bag with
a fully de-oracled estimator, and isolate which mechanism actually closes the gap.

`s3li_crater` is a single 25.94 GB ROS1 bag: a 1.3 km rover loop around the Cisternazza crater on Mt
Etna (DLR planetary-analogue stereo + IMU + LiDAR, Giubilato et al.). At stride 3 the run is 10599 stereo
keyframes over 1136 s. Calibration is the Cfgs pinhole intrinsics (fx = fy = 579.49 px, baseline
0.2003 m). Ground truth is the RTKLIB `global_lle.pos` track, converted to the same local ENU frame as
the independent DEM prior. The DEM is the free Copernicus GLO-30 (about 30 m posting, EGM2008 heights);
the paper used a roughly 2 m Pleiades DSM.

---

## 2. Method: the estimator ladder

The estimator is a factor graph over per-keyframe poses, solved by sparse Gauss-Newton with a Huber
robust kernel. The experiment builds it up one capability at a time so each lever is attributable:

1. **VO front end.** SuperPoint detector and descriptor, LightGlue matcher, calibrated stereo
   triangulation for a metric per-frame cloud, temporal 3D-to-2D PnP-RANSAC for inter-frame motion.
   Registered into the DEM ENU frame by a firewall-clean VO-vertical-vs-DEM-height yaw search (no GT).

2. **Visual loop closure.** Each keyframe carries a global appearance descriptor (the L2 mean of its
   SuperPoint descriptors). Revisit candidates are the appearance-nearest temporally-distant keyframes
   (node-index gap gate, never ground-truth proximity). Each candidate is verified by a LightGlue match
   plus PnP-RANSAC; an accepted closure contributes the relative camera pose (translation and rotation)
   between the two keyframes.

3. **Pose-graph solver.** Three variants were built and compared:
   * position-only 3D graph (orientations held at the VO front-end values),
   * keyframe SE(2) graph plus a deformation lift to full resolution (heading freed, exploration),
   * full SE(3) graph (every keyframe a free 6-DOF pose, on-manifold retraction, vectorized SO(3)
     Exp/Log). This is the load-bearing estimator.

4. **DEM anchoring.** Online DEM height-normal factors (residual z minus H(x,y), Jacobian uses the DEM
   surface normal), re-sampled at the estimated (x,y) every iteration, inserted every 20 poses. A
   declared coarse start pose is the gauge prior.

---

## 3. Results

Absolute trajectory error vs RTK ground truth (evo, Umeyama alignment, bag-vs-GT time offset 16.6 s
recovered by speed cross-correlation, peak 0.916). SE3 is rigid alignment; Sim3 also corrects global
scale.

| Stage | SE3 (m) | Sim3 (m) | horizontal (m) | vertical (m) |
|---|---|---|---|---|
| VO (SuperPoint+LightGlue stereo) | 93.33 | 93.21 | 92.51 | 12.34 |
| VIO (gyro-fused heading) | 79.52 | | | |
| Loop closure, position-only graph | 51.05 | 50.82 | 50.46 | 7.76 |
| **SE(3) + loop closure** | **9.96** | 8.38 | 8.18 | 5.68 |
| **SE(3) + loop closure + DEM** | **7.99** | 5.57 | 6.69 | 4.37 |
| Reference paper (2 m Pleiades DEM) | 94.01 -> 21.43 | | | |

Loop closure: 5 closures accepted from 4000 appearance candidates (3995 rejected by the geometric gate),
all tying the end arc (nodes 10548 to 10596) back to the start arc (nodes 18 to 258), the single genuine
revisit of this one-loop traverse (the rover returns within 1.4 m of its start). PnP inliers 16 to 18.

**The mechanism is the heading redistribution.** Holding orientations at the VO values caps loop closure
at the 51.05 m position-only floor. Freeing orientation (the SE(3) graph applies a mean absolute
per-keyframe heading correction of 36.3 degrees) un-bows the loop and drops SE3 to 9.96 m, a 41 m
improvement on the same 5 closures. The loop closures carry a relative rotation that the position-only
graph discards; using it is the lever.

**DEM anchoring then helps once horizontal is tight.** Adding the online DEM factor on top of the SE(3)
estimate lowers SE3 from 9.96 m to 7.99 m and vertical from 5.68 m to 4.37 m. This is the reference
paper's structure ("loop closure supplies horizontal, the DEM supplies height") finally testable: at the
position-only graph's 50 m horizontal residual the same DEM factor did nothing, because it sampled the
wrong terrain.

The SE(3) + LC + DEM solve converged (27 iterations, gradient at a robust-kernel minimum). The truth
firewall poison test passes (corrupting GT by +1e6 m leaves the estimate byte-identical).

---

## 4. What works

- **Loop closure fires and is real**, proposed by appearance and node index only, verified by geometry;
  the measured loop displacement (about 1.3 m) matches the GT revisit distance.
- **Optimising orientation is the decisive lever** (the 41 m drop from the position-only floor).
- **Online DEM height-normal anchoring helps the vertical** once the horizontal is within range.
- The full ladder is below the paper's 21.43 m, with the honest caveat in Section 5.

## 5. What does not work (honest negatives)

- **The horizontal terrain-correlation anchor (DEM_XY) finds 0 of 36 confident windows** on the 30 m
  DEM. The S3LI stereo sees a thin 0.5 to 8 m elevation ribbon, not a 2D terrain tile, so per-window
  terrain registration is unobservable. Loop closure, not DEM_XY, is the horizontal source.
- **DEM normal coupling can hurt at the SE(2) exploration's looser horizontal.** In the keyframe-SE(2)
  variant (7.5 m horizontal) the coarse 30 m normal redistributed height residual into a wrong
  horizontal pull (SE3 10.7 to 14.0 m); a height-only factor recovered the vertical without the penalty
  (8.4 m). In the full SE(3) (6.69 m horizontal) the normal factor helps, so this is a tight-enough
  -horizontal phenomenon, not a DEM defect.
- **Only one revisit region exists.** This is a single-loop traverse; interior drift is corrected only
  through the chain. More loop closures at a lower inlier gate (27 vs 5) made the result worse, not
  better (noisier closures).
- **The "below 21.4 m" comparison is not like-for-like.** The estimator is a batch smoother over all
  10599 poses with 5 tight start-to-end closures on a clean single loop, which can outperform an
  online or filtering setup. The result is a strong feasibility number, not a claim that this method
  beats the paper's system in deployment.

## 6. The performance floor

The SE3 ATE is 7.99 m but the Sim3 ATE is 5.57 m. That 2.4 m gap is a roughly 4 percent VO forward-scale
bias the rigid SE3 alignment cannot absorb. An autoresearch sweep tested every firewall-clean way to
recover that scale and apply it to the trajectory:

| scale source | recovered scale | resulting SE3 (m) | verdict |
|---|---|---|---|
| GT-optimal (ceiling, not reachable) | 1.045 | 5.50 | what a perfect scale would buy |
| loop-closure `vo_scale` state | 0.370 | 85.96 | degenerate: a single revisit shrinks the loop to force closure |
| IMU acceleration regression | 3.065 | 260.07 | too noisy: the slow rover's 0.14 m/s2 horizontal motion accel is 40x below the 5.6 m/s2 gravity-removal residual (corr 0.10) |

No firewall-clean estimator recovers the 4 percent scale on this data; both real methods recover wildly
wrong scales that make the error far worse. A DEM scale search is circular (the SE(3) z is already
DEM-anchored at the current scale). **So 7.99 m SE3 is the genuine floor for vision-only plus a 30 m DEM
plus a single-loop traverse, and 5.57 m (Sim3) is an unreachable ceiling absent a clean metric scale
reference.** The residual is single-revisit geometry plus the 4 percent scale, not the 30 m DEM (the DEM
barely moves the ATE once horizontal is tight).

## 7. Truth firewall and validity

Every estimation function consumes only stereo images, the VO-derived orientation, the independent DEM
prior (sampled at the estimated x,y), and a single declared coarse start. Loop-closure candidates come
from appearance and node index, never GT proximity. The independent Copernicus DEM was surveyed years
before the 2021 rover run and is not built from the rover trajectory, so consuming it as a map prior is
legitimate. Ground truth is loaded only at time sync and scoring, after each estimate is frozen to disk.
The poison test (GT + 1e6 m yields a byte-identical estimate) and structural signature checks confirm no
GT argument reaches any estimator.

## 8. Transfer to the lunar target

Two channels that could push below the floor are not exercisable on this dataset but are real levers on
the lunar South Pole target:

- **Shadow navigation and shadow parallax.** The bag was recorded at sun elevation 71.3 degrees, so a
  1 m rock casts a 0.34 m shadow. Shadow heading and shadow-tip parallax need grazing-sun shadows
  (lunar pole sun 1 to 3 degrees, shadows 20 to 50 times object height). The fusion paths are wired and
  tested: an anti-solar absolute-heading factor (`solve_se2_keyframes(shadow_yaw=...)`) and a
  two-viewpoint lateral-baseline shadow-tip parallax core (`dart/shadow_parallax_nav.py`, reusing the
  trilateration and GDOP machinery from the vertical-articulation parallax module). They add nothing at
  71 degrees but are ready for the render track.
- **Metric scale (IMU, multi-camera).** S3LI is stereo-only and the IMU is gravity-dominated at this
  motion level, so the 4 percent scale is unrecoverable here. The lunar IPEx rig has 8 cameras (wide
  baselines, more closures, wider parallax) and the rover drives with accelerations that make IMU
  pre-integration informative. The IMU being unusable here is the slow-rover analog of the shadow
  channels being unusable here: both are real lunar levers that this Etna daytime dataset does not
  exercise.

---

## 9. What else we can do

Ranked by value to the dissertation and feasibility.

1. **Validate on the lunar render track (the real ARGUS target).** Run the SE(3) estimator plus the
   shadow-yaw and shadow-parallax channels on the Godot/Chrono lunar render over the LOLA Haworth DEM
   with a grazing sun and the 8-camera rig. This is where the shadow and multi-camera levers actually
   work and where the dissertation's contribution lands. The estimator, the shadow factors, and the
   parallax core are already built; this is an integration and a render-fixture task.
2. **Tight visual-inertial pre-integration with online bias and cam-IMU extrinsic.** The honest path to
   sub-6 m on real data and a requirement for deployment. This is the principled fix for the 4 percent
   scale (Section 6) and for VO robustness through feature-poor stretches. The IMU loader and the gyro
   leveling already exist (`dart/s3li_vio.py`); the missing piece is preintegrated IMU factors with
   accel-bias states in the SE(3) graph.
3. **Incremental / online SLAM (iSAM2-style) for a like-for-like comparison.** The current estimator is
   a batch smoother (Section 5). An incremental backend removes the "batch can beat online" caveat and
   is the realistic on-rover form. It also enables the active-sensing triggers (relocalize when the
   covariance grows) the parallax module already exposes.
4. **Multi-loop and additional S3LI sequences.** A traverse with more than one revisit region breaks the
   single-revisit floor (Section 5). Running the other S3LI sequences tests generalization and gives the
   loop-closure detector more than one closure cluster to work with.
5. **Higher-resolution DEM where one binds.** A 2 m Pleiades or 10 m Tinitaly DSM on Etna (registration-
   gated), or the 1 to 2 m LROC-NAC / shape-from-shading DSMs already downloaded for the lunar sites,
   would let the DEM height factor refine the vertical without horizontal penalty and could expose a
   weak terrain-relative horizontal fix the 30 m DEM cannot.
6. **Complete the shadow-parallax perception.** The geometric core is done and tested; the remaining
   work is shadow-tip detection and cross-frame tracking (reusing `dart/shadow_extract.py`) to feed real
   disparities into the parallax factor on the lunar track.
7. **Benchmark against a known lunar-navigation baseline** (the Stanford NAV Lab comparison the
   integration plan calls for), to position the result against published lunar SLAM rather than only the
   one reference paper.

### Loop readiness (data-availability check, 2026-06-28)

Each forward direction was checked against the data actually on disk, so the loops are specified with
their real blocker rather than assumed runnable:

| Loop | Data on disk | Status |
|---|---|---|
| More S3LI sequences (multi-loop generalization) | only `s3li_crater.bag` present | BLOCKED: no second S3LI sequence |
| Katwijk visual SLAM (second real rover) | `katwijk/PartN/LocCam` has 0 image files (only IMU/GPS/odometry text + calibration); existing Katwijk code is wheel+IMU dead-reckoning | BLOCKED: LocCam stereo not downloaded |
| LuSNAR rendered-lunar loop closure | `lusnar/extracted/Moon_1` present (stereo+gt+imu), but the traverse is OPEN (span 256 x 19 m, no revisit) and the DEM is GT-derived | BLOCKED: no revisit (loop closure cannot fire); DEM not firewall-clean |
| Lunar Godot render (the real target) | `stewie/godot/out/plan_render` holds PNGs only, not a consumable stereo+DEM sequence | NEEDS BUILD: the Godot/Chrono producer + sensor-bridge fixtures (FORGE track) |
| VIO into the SE(3) graph | S3LI IMU present; tested-negative for scale (gravity-dominated, corr 0.10) | NEEDS BUILD + COORDINATION: IMU preintegration factors in the concurrent SE(3) estimator; marginal at this motion level |
| Higher-res Etna DEM | only the 30 m Copernicus tile; Tinitaly/Pleiades are registration-gated | BLOCKED: gated download |

**Honest conclusion.** The S3LI loop has converged to its floor (7.99 m, exhaustively documented), and
every forward loop is currently blocked on missing data or is a real build that overlaps the concurrent
SE(3)/integration work. There is no quick autoresearch loop left to run on the present data. The single
highest-value unblocked next step is the **lunar render track** (Section 9 item 1): standing up the
Godot/Chrono producer so the estimator and the already-built shadow and multi-camera channels run on
grazing-sun lunar terrain, which is where those levers actually move the number.

---

## 10. Artifacts and reproducibility

| Artifact (under `stewie/eval/validation/`) | Content |
|---|---|
| `s3li_crater_se3_2026-06-28.json` | the load-bearing SE(3) ladder (93.3 -> 7.99 m), poison test, convergence |
| `s3li_crater_se2_recipe_2026-06-28.json` | the SE(2) exploration ladder incl. height-only DEM (8.4 m) |
| `s3li_crater_paper_recipe_2026-06-28.json` | the position-only loop-closure rung (51.1 m) and DEM-on-50m-horizontal null |
| `s3li_crater_demxy_2026-06-28.json` | the 0/36 terrain-correlation null on the 30 m DEM |
| `s3li_crater_autoresearch_se2_2026-06-28.json` | the SE(2) solver-lever sweep (horizontal floor ~7.5 m) |
| `s3li_crater_autoresearch_scale_2026-06-28.json` | the scale-recovery sweep (floor 7.99 m, ceiling 5.50 m) |
| `s3li_crater_vio_2026-06-28.json` | the gyro-fused VIO rung (79.5 m) |
| `s3li_crater_EXPERIMENT_LOG.md` | the full lab-notebook with the per-experiment tables |

Code: `dart/se3_pose_graph.py` (SE(3) estimator), `dart/loop_closure_visual.py` (loop detection),
`dart/loop_pose_graph_se2.py` (SE(2) variant), `dart/dem_height_graph.py` (DEM factors),
`dart/shadow_parallax_nav.py` (lunar shadow-parallax core), with runners and firewall tests under
`benchmarks/s3li_crater/`.
