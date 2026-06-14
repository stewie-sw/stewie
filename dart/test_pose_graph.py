"""#78 (ARGUS subsystem): the windowed pose-graph estimator.

The thesis claim is a UNIFIED articulated state every estimator reads. This is the spine: a
windowed 2-D pose graph that fuses odometry priors (the drift model) with absolute factors
(DEM scan-registration + a SHADOW-outline residual) into a joint least-squares estimate with
covariance -- the structure ARGUS needs and that resync.py's 1-D fuse was the placeholder for.
Real factor primitives (dart/localization, dart/shadow_predict) feed it; no fabricated data.
"""
import numpy as np
import pytest

from dart import pose_graph as PG


def test_odometry_only_chain_reproduces_dead_reckoning():
    """[REQ:CP-06] with ONLY odometry factors, the optimum is the integrated path (the baseline)."""
    g = PG.PoseGraph()
    g.add_prior(0, (0.0, 0.0), sigma=0.01)
    g.add_odometry(0, 1, (1.0, 0.0), sigma=0.05)
    g.add_odometry(1, 2, (1.0, 0.0), sigma=0.05)
    est = g.optimize()
    assert est[2] == pytest.approx((2.0, 0.0), abs=1e-3)    # 0 -> 1 -> 2 m, no correction


def test_an_absolute_factor_pulls_the_drifted_chain_back():
    """[REQ:CP-06] a DEM/shadow absolute fix at the last node corrects accumulated odometry drift,
    and the fused covariance at that node SHRINKS below the odometry-only growth."""
    g = PG.PoseGraph()
    g.add_prior(0, (0.0, 0.0), sigma=0.01)
    g.add_odometry(0, 1, (1.0, 0.0), sigma=0.20)            # drifty odometry
    g.add_odometry(1, 2, (1.0, 0.0), sigma=0.20)
    odo_only = g.optimize_with_cov()
    g.add_absolute(2, (1.85, 0.10), sigma=0.05)            # a sharp absolute fix near truth
    fused = g.optimize_with_cov()
    assert abs(fused["pose"][2][0] - 1.85) < abs(odo_only["pose"][2][0] - 1.85)  # pulled toward the fix
    assert fused["sigma"][2] < odo_only["sigma"][2]        # the fix shrinks the node's uncertainty


def test_shadow_outline_descriptor_seeds_an_absolute_factor_structurally():
    """[REQ:SN] H-16: shadow_outline_descriptor is a FEATURE DESCRIPTOR (the observed shadow-edge centroid
    in the local frame), NOT a registered observed-vs-predicted map match. Its centroid can SEED an
    absolute factor as the structural form of the ARGUS shadow-as-instrument claim -- the graph fuses it
    like any absolute term -- but the real map registration + rover-camera transform is the #79 slice."""
    from dart.shadow_predict import cast_shadow_mask
    # a small real-terrain patch with a ridge -> a cast shadow whose edge is the descriptor source
    z = np.zeros((24, 24))
    z[10:14, :] = 3.0                                       # an E-W ridge casts a shadow across the row axis
    mask = cast_shadow_mask((z, 5.0), sun_az_deg=0.0, sun_el_deg=10.0)   # N-S sun, perpendicular to the E-W ridge (C-03)
    assert mask.any() and not mask.all()                   # a real partial shadow exists
    obs_xy, sigma = PG.shadow_outline_descriptor(mask, cell_m=5.0, prior_xy=(60.0, 55.0))
    g = PG.PoseGraph()
    g.add_prior(0, (62.0, 58.0), sigma=8.0)                # a DRIFTED dead-reckoning guess (uncertain)
    g.add_absolute(0, obs_xy, sigma=sigma)
    est = g.optimize()
    # the honest claim: the sharper shadow fix pulls the drifted estimate toward itself -- the
    # estimate ends up nearer the shadow observation than the drifted prior (information-weighted)
    d_obs = np.hypot(est[0][0] - obs_xy[0], est[0][1] - obs_xy[1])
    d_prior = np.hypot(est[0][0] - 62.0, est[0][1] - 58.0)
    assert d_obs < d_prior                                  # the shadow factor wins over the drift


def test_h15_gauge_free_pose_graph_reports_unobservable_not_finite_sigma():
    """Audit H-15 (2026-06-13): a 2-D position graph with only relative (odometry) factors is GAUGE-FREE --
    the global translation is unobservable. The solver's tiny ridge keeps it solvable but its covariance is
    ridge-induced, NOT physical. optimize_with_cov must report observable=False and an INFINITE sigma; an
    anchored graph is observable with finite sigma."""
    import math
    g = PG.PoseGraph()
    g.add_odometry(0, 1, (1.0, 0.0), sigma=0.1)              # only a relative factor -> gauge-free
    out = g.optimize_with_cov()
    assert out["observable"] is False and math.isinf(out["sigma"][0]) and math.isinf(out["sigma"][1])
    g.add_prior(0, (0.0, 0.0), sigma=0.1)                    # anchor the gauge -> observable, finite
    out2 = g.optimize_with_cov()
    assert out2["observable"] is True and math.isfinite(out2["sigma"][1])
