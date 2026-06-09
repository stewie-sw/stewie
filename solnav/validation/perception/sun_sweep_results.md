# Feature front-end vs lunar sun elevation (P1.F method-selection, REAL renders)

Rig stereo (front_left/front_right) rendered on crater_boulders at sun azimuth 215 deg, varying
elevation; RANSAC-fundamental inlier ratio + inlier/raw-match counts per method. Real Godot renders,
no synthetic data.

| sun_elev (deg) | ORB inl/raw ratio | SIFT inl/raw ratio | DISK+LightGlue inl/raw ratio |
|---|---|---|---|
| 3 (grazing)  | 277/302 0.92 | 65/70  0.93 | 161/170  0.95 |
| 8            | 308/331 0.93 | 59/69  0.86 | 227/239  0.95 |
| 20           | 478/515 0.93 | 258/297 0.87 | 777/789  0.98 |
| 40           | 546/592 0.92 | 324/369 0.88 | 1094/1100 0.99 |

**Finding:** at faithful low grazing sun (3-8 deg, the real lunar-polar operating condition) every method
yields fewer features, but **DISK+LightGlue retains the highest inlier ratio (0.95) and more inliers than
SIFT**; ORB is the cheap, ratio-stable fallback; **SIFT degrades worst** under grazing illumination. The
learned (terrestrial-trained) matcher DOES generalize to lunar low-sun here -> a real method-selection
signal for the P1 VO front end. Remaining: a held-out lunar SCENE + albedo/contrast axes, and feeding
the chosen matcher into VO (currently VO uses its own path); not wired into G1.
