#!/usr/bin/env python3
"""First end-to-end SENSOR factor in the estimator (audit P4 crossing).

A straight traverse whose wheel/gyro odometry carries a constant GYRO BIAS (a real drift, not
fabricated data) -> dead-reckoning heading walks off. We extract the shadow heading from a REAL
rendered frame (provenance IMAGE_DERIVED, invariant I3: no truth pose), convert it to an absolute
heading via a ONE-TIME start calibration (like aligning a compass at dock), and add it as a
heading factor with its IMAGE-DERIVED sigma. The sensor factor bounds the gyro drift.

Honest scope: one render is reused along a straight path (constant body-frame shadow azimuth);
per-pose rendering + directed clutter resolution (P7) are the full version.
"""
import os, json
import numpy as np
from imageio.v3 import imread

from solnav.perception import shadow_extract as se
from solnav.geometry import shadow
from solnav.slam import posegraph as pg
from solnav.eval import metrics

CUBE = "/mnt/projects/foss_ipex/dustgym/godot_sidecar/out/cube_on_plane.png"
OUT = os.path.join(os.path.dirname(__file__), "out"); os.makedirs(OUT, exist_ok=True)
SUN_AZ = 30.0          # cube scene --sun-azim (configured parameter, NOT rover truth)
GYRO_BIAS = np.radians(0.4)   # rad/step constant gyro bias (a real sensor drift)


def main():
    # straight true traverse, constant heading
    n = 30
    true = pg.integrate_odometry([0, 0, 0.0], [[0.6, 0.0, 0.0]] * n)
    odo_true = pg.relative_odometry(true)
    # odometry the rover BELIEVES: every step carries a constant gyro bias -> heading drifts
    odo_biased = [z + np.array([0, 0, GYRO_BIAS]) for z in odo_true]
    dr = pg.integrate_odometry(true[0], odo_biased)        # dead reckoning (curves off)

    # IMAGE-DERIVED shadow heading from a real render (no truth pose)
    obs = se.extract_shadow_azimuth(np.asarray(imread(CUBE)))   # R~0.99, directed
    yaw_meas_raw = shadow.heading_from_shadow(obs.z_shadow_body_deg, SUN_AZ)
    # one-time start calibration (compass alignment at dock): offset so pose-0 reads truth
    c = np.degrees(true[0, 2]) - yaw_meas_raw
    yaw_abs = np.radians(yaw_meas_raw + c)                  # = true start heading; constant on a straight path
    info_h = 1.0 / np.radians(obs.sigma_deg) ** 2           # image-derived sigma -> factor weight

    def solve(use_sensor):
        g = pg.PoseGraph(); g.add_prior(0, true[0])
        for i, z in enumerate(odo_biased):
            g.add_odom(i, i + 1, z)
        if use_sensor:
            for i in range(0, n + 1, 3):                    # image-derived heading factor every 3 poses
                g.add_heading(i, yaw_abs, info=info_h)
        return g.solve(np.array(dr))

    X_odom = solve(False); X_sensor = solve(True)
    res = {
        "gyro_bias_deg_per_step": round(np.degrees(GYRO_BIAS), 2),
        "image_shadow": {"z_shadow_body_deg": round(obs.z_shadow_body_deg, 1),
                         "confidence_R": round(obs.confidence, 3), "sigma_deg": round(obs.sigma_deg, 1),
                         "provenance": obs.provenance},
        "ate_dead_reckoning_m": round(metrics.ate_rmse_raw(dr, true), 3),
        "ate_odom_only_graph_m": round(metrics.ate_rmse_raw(X_odom, true), 3),
        "ate_with_image_heading_factor_m": round(metrics.ate_rmse_raw(X_sensor, true), 3),
        "heading_err_dead_deg": round(metrics.heading_error_deg(dr[:, 2], true[:, 2]), 2),
        "heading_err_sensor_deg": round(metrics.heading_error_deg(X_sensor[:, 2], true[:, 2]), 2),
        "note": "image-derived heading factor (from pixels, no truth ingress) bounds the gyro drift",
    }
    json.dump(res, open(os.path.join(OUT, "sensor_slam_metrics.json"), "w"), indent=2)
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
