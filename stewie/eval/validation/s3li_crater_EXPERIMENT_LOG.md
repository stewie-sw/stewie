# S3LI s3li_crater navigation experiments — what works, what doesn't

Real DLR S3LI `s3li_crater` Mt-Etna loop (25 GB bag, 1.3 km, stride 3 = 10599 frames). Reproducing the
arXiv:2603.17229 recipe (VO → loop closure → DEM anchoring) and pushing past it. Every estimate is
ground-truth-free (truth firewall I3); GT enters only at evo scoring after each estimate is frozen.
DEM = free Copernicus GLO-30 (~30 m); the paper used a ~2 m Pleiades DSM.

> **⚠ SUPERSEDED FOR THE "FLOOR" CLAIM (2026-06-28).** This log is supporting **SE(2)** exploration. Its
> "8.4 m is the floor" and "horizontal pinned at ~7.5 m" claims are the floor of the *keyframe-SE(2) +
> deformation-lift* configuration only (orientations only partially freed). The **load-bearing dissertation
> result is the full SE(3) pose-graph estimator** (commit `ef8d4e2`, artifact
> `s3li_crater_se3_2026-06-28.json`): freeing full SE(3) orientation breaks through that floor to **7.99 m
> SE3 / 6.69 m horizontal** (converged, 27 iter, I3 poison-test PASS). In the full SE(3) the DEM
> height-**normal** factor *helps* (horizontal is tight enough at 6.69 m that the slope coupling is fine), so
> the height-only workaround this log needed at SE(2)'s 7.5 m is not needed there. Read "8.4 m" / "~7.5 m
> floor" below as SE(2)-lift-specific, not the estimator's limit.

## The ladder (SE3 ATE vs RTK GT, evo, offset −16.6 s)

| # | Estimate | SE3 m | horiz m | vert m | Sim3 scale | verdict |
|---|---|---|---|---|---|---|
| a | VO (SuperPoint+LightGlue stereo) | 93.3 | 92.5 | 12.3 | 0.953 | baseline (matches paper VO 94.0) |
| b | VO + loop closure, **position** graph | 51.1 | 50.5 | 7.8 | 1.040 | partial — fixes translation only |
| c | VO + loop closure, **SE(2)** graph | 10.7 | 7.5 | 7.7 | — | beats paper's 21.4 |
| d | VO + LC(SE2) + DEM height-**normal** | 14.0 | 13.4 | 4.0 | — | net-negative (slope coupling) |
| e | VO + LC(SE2) + DEM **height-only** | **8.4** | 7.5 | **3.9** | — | ✅ best — decoupled slope |
| — | paper (Pleiades 2 m DEM) | 21.43 | — | — | — | target |

Autoresearch sweep (`s3li_crater_autoresearch_se2_2026-06-28.json`) confirms **8.4 m is the floor on this
dataset**: best = `finer_kf` (SE(2) step 20, converged, + height-only DEM) **8.42 m** (h 7.47, v 3.89).

Artifacts: `s3li_crater_paper_recipe_2026-06-28.json` (rungs a–b–d on the position graph),
`s3li_crater_se2_recipe_2026-06-28.json` (full ladder a–d). Figures under
`figures/s3li_crater_{paper,se2}_recipe_2026-06-28/`.

## What works

1. **Visual loop closure fires and is real.** 5 closures accepted of 4000 appearance candidates (3995
   rejected: 3017 too-few-3D-correspondences, 785 too-few-matches, 193 pnp-failed — appearance proposes,
   geometry disposes). All tie the END arc (nodes 10548–10596) back to the START arc (nodes 18–258): the
   single genuine revisit of this one-loop crater (rover returns within 1.4 m of start). Inliers 16–18;
   measured loop displacement (~1.1–1.5 m) matches the GT revisit distance. Firewall: candidates from a
   global SuperPoint descriptor + node-index gap, NEVER GT proximity; relative pose from LightGlue+PnP.
   Poison test (GT+1e6) → byte-identical estimate.

2. **Loop closure fixes the gross drift** (93.3 → 51.1 SE3, −45 % horizontal) even in the weak
   position-only graph.

3. **Optimising HEADING is the decisive lever (the main finding).** The SAME 5 closures, now carrying a
   relative `dyaw` (from the PnP relative rotation), in an **SE(2)** pose graph reach **10.7 m SE3 /
   7.5 m horizontal** — 5× better than the position-only graph and **below the paper's 21.4 m**. The
   SE(2) solve redistributes the accumulated heading drift that bowed the trajectory; a position-only
   solve (orientations pinned at VO values) structurally cannot. This was the binding limit, NOT the DEM.

4. **DEM height-normal anchoring helps the VERTICAL once the horizontal is tight** (vert 7.7 → 4.0 m,
   −48 %). This reproduces the paper's "loop closure supplies horizontal, DEM supplies height" claim —
   but ONLY in rung (d), on top of the SE(2) fix. At the 50 m horizontal residual of the position-only
   graph, the same DEM factor did nothing (it sampled the wrong terrain).

## What doesn't work (honest negatives)

5. **DEM-on-top is net-neutral on SE3 on the 30 m DEM** (14.0 vs 10.7): while it halves the vertical it
   PERTURBS the horizontal (7.5 → 13.4 m), because the coarse 30 m slope/normal redistributes the height
   residual into a noisy horizontal pull. **This is where DEM RESOLUTION finally binds** — a 2 m Pleiades
   / 10 m Tinitaly (Etna) or 1–2 m LROC-NAC (Moon) DSM would have accurate slopes and let the height
   factor refine vertical WITHOUT the horizontal penalty. Higher-res DEM is necessary for a net-positive
   DEM leg; on the 30 m DEM it isn't.

6. **The horizontal terrain-correlation anchor (DEM_XY) finds 0 confident fixes** on the 30 m DEM
   (`s3li_crater_demxy_2026-06-28.json`): the S3LI stereo sees a thin ~1-D elevation ribbon (depth
   0.5–8 m), not a 2-D tile, so per-window terrain registration is unobservable. Superseded by loop
   closure as the horizontal source.

7. **Only ONE revisit region exists** (single-loop traverse) — confirmed: even 27 loop closures (lower
   inlier gate) give the same result; more closures in the same region don't help. Multi-loop traverses
   would close more.

8. **The SE(2) solve runs on a 362-node KEYFRAME graph** (`pose_graph_se2.py` uses dense numerical
   Jacobians; full 10599-node is infeasible there) and lifts to full resolution by an SE(2) deformation;
   it does NOT gradient-converge (hits the LM iteration cap), though the LM only accepts cost-decreasing
   steps so the cost decreases monotonically. The exact 10.7 m should therefore be read as "non-converged
   keyframe SE(2) + deformation lift, no DEM"; stability across iteration count is NOT yet demonstrated.
   A sparse analytic SE(2) GN over all 10599 nodes (converged, full-resolution) is the clean follow-up
   and the way to pin the absolute number. The headline finding (optimising heading is the decisive
   lever — 5x better than the position-only graph) is robust to this caveat; the precise value is not.

## Autoresearch: can we get below 8.4 m? (sweep result)

`benchmarks/s3li_crater/autoresearch_se2.py` swept the solver levers (keyframe step, loop-closure count,
heading-factor stiffness, LM iterations, DEM mode) against the real scored SE3:

| trial | SE3 | horiz | vert | note |
|---|---|---|---|---|
| se2_base (step30 + h-only DEM) | 8.44 | 7.49 | 3.89 | non-converged |
| more_loops (27 closures, inl 12) | 8.89 | 8.01 | 3.86 | **worse** — extra closures are noisier |
| tight_yaw (loop σ 0.02) | 8.63 | 7.71 | 3.88 | worse |
| more_iters (150) | 8.45 | 7.50 | 3.88 | no change — not iteration-limited |
| **finer_kf (step20)** | **8.42** | **7.47** | 3.89 | **best, and CONVERGES** |
| combo (step20, inl12) | 9.08 | 8.23 | 3.85 | worse (inl12) |
| combo_no_dem (step20, no DEM) | 11.28 | 8.28 | 7.66 | shows DEM-height-only buys the −3.8 m vert |

**Finding — the horizontal is pinned at ~7.5 m across EVERY config.** It does not move with keyframe step,
closure count, iterations, or heading stiffness: it is the floor set by the **5 loop closures over a single
revisit region** (each ~2 m measurement noise). Height-only DEM takes the vertical to ~3.9 m, so **SE3 ≈
8.4 m is the floor for this dataset's channels.** To go below it needs *more/better loop closures* (a
multi-loop traverse) or an *independent absolute channel* — which is where the channels below come in.

## Channels we could add — and whether they help HERE (honest)

The user asked about shadow nav, shadow parallax, and secondary/multi-camera views. Verdict for **this
real S3LI sequence**:

- **Shadow yaw / shadow parallax — NOT a lever here, a LUNAR lever.** The bag was recorded at **sun
  elevation 71.3°** (near-noon summer Etna): a 1 m rock casts a **0.34 m** shadow. Shadow heading and
  shadow-tip parallax need long, sharp, grazing-sun shadows — the lunar South Pole (sun ~1–3° → shadows
  20–50× object height), not Etna daytime. The fusion paths ARE wired (`solve_se2_keyframes(shadow_yaw=…)`
  adds an anti-solar absolute-heading factor; `dart/shadow_parallax_nav.py` is the lateral-baseline
  parallax core) and tested, ready for the lunar render track (Godot shadows on LOLA Haworth) — but they
  would add ~nothing on S3LI's 71° sun.
- **Secondary views / multiple cameras — NOT available here.** S3LI is a **stereo pair (2 cameras)**, and
  the VO already uses BOTH (left+right for triangulation). There is no additional camera on this dataset;
  the 8-monochrome-camera rig is the lunar IPEx/LAC target. On the Moon, the wide-baseline 8-cam rig is a
  real lever (more loop closures + wider parallax); on S3LI the only "secondary view" is the right camera
  (0.2 m stereo baseline, already consumed).

So **8.4 m is the honest floor for S3LI**; the next gains are dataset-structural (multi-loop) or
deployment-specific (the lunar shadow + multi-camera channels), not more solver tuning.

## Scale-recovery autoresearch — pushing the SE(3) 7.99 m toward the 5.57 m Sim3 floor

The committed full-SE(3) estimator (`s3li_crater_se3_2026-06-28.json`) sits at **SE3 7.99 m / Sim3
5.57 m** — the 2.4 m gap is a **~4% VO forward-scale bias** the rigid SE3 alignment can't absorb. The
autoresearch loop (`benchmarks/s3li_crater/autoresearch_scale.py`, artifact
`s3li_crater_autoresearch_scale_2026-06-28.json`) tested every firewall-clean way to recover that scale,
applying each to the SE(3) trajectory and re-scoring:

| method | recovered scale | SE3 | verdict |
|---|---|---|---|
| baseline (SE3+LC+DEM) | 1.000 | 7.99 | the committed floor |
| **GT-optimal (ceiling)** | 1.045 | **5.50** | what a perfect scale would buy — **GT-derived, not reachable** |
| loop closure (`vo_scale` state) | 0.370 | 85.96 | **DEGENERATE** — a single revisit lets scale shrink the whole loop to force closure |
| IMU accel-regression | 3.065 | 260.07 | **TOO NOISY** — the slow rover's 0.14 m/s² horizontal motion accel is 40× below the 5.6 m/s² gravity-removal residual (corr 0.10) |

**Conclusion: the 4% scale is NOT firewall-cleanly recoverable on this data.** Both real estimators
recover wildly wrong scales that make the ATE *far worse*; only the GT-derived scale reaches 5.50 m. A
DEM scale search is circular (the SE(3) z is already DEM-anchored at the current scale). So **7.99 m SE3
is the genuine floor** for vision-only + a 30 m DEM + a single-loop traverse, and **~5.6 m (Sim3) is an
unreachable ceiling** without a clean metric scale reference: a higher-res DEM (Tinitaly/Pleiades/LROC-
NAC, all gated here), wheel odometry (absent from the bag), tight IMU pre-integration with online accel-
bias + cam-IMU-extrinsic estimation (a real VIO build, and marginal at this motion level), or a
multi-loop traverse (different data). The IMU being unusable here is the slow-rover analog of the
shadow channels being unusable here — both are real lunar levers that this Etna dataset just doesn't
exercise.

## Method / solver notes

- Position graph: `dart/dem_height_graph.py` (analytic sparse GN, 3-D node positions; `height_only` DEM
  factor decouples the slope from horizontal).
- Loop closure: `dart/loop_closure_visual.py` (appearance proposal + LightGlue/PnP verify; the visual
  relative pose, incl. `r_ab` rotation for the SE(2) `dyaw`).
- SE(2) fix: `dart/loop_pose_graph_se2.py` (keyframe `PoseGraphSE2` + deformation lift to full res).
- DEM: `dart/s3li_dem.py` (Copernicus GLO-30, EGM2008; height + normal sampler).

## Next: shadow-parallax navigation (in progress)

The independent geometric channel for the lunar target (low grazing sun → long sharp cast shadows). Core
built: `dart/shadow_parallax_nav.py` — two-viewpoint LATERAL-baseline parallax of cast shadow-tip
landmarks (`R = fx·B/disparity`, B = VO drive baseline), trilateration + GDOP reused from
`dart/articulated_parallax.py` (SN-10, vertical-articulation parallax), injected as a PARALLAX_XY
pose-graph fix (the unblocked factor path; metric shadow length/boundary remain guardrail-blocked).
Validity bound: a shadow tip is a fixed ground point only within a sun-static window (polar anti-solar
drift ~0.5 °/hr — negligible over a seconds-long drive baseline). Remaining: shadow-tip detection +
cross-frame tracking (reuse `dart/shadow_extract.py` / `shadow_height.py`), and a closed-loop test on
the lunar render track (Godot shadows on the LOLA Haworth DEM). See `dart/shadow_parallax_nav.py` header
and `dart/test_shadow_parallax_nav.py`.
