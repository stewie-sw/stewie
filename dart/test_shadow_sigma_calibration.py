"""#81 shadow-channel sigma calibration over the real Haworth DEM."""
import numpy as np

from dart.shadow_sigma_calibration import calibrate_shadow_sigma


def _dem():
    z = np.zeros((60, 60))
    z[25:30, :] = 4.0                      # a ridge -> a real cast shadow (real-shaped, not fabricated values)
    return (z, 5.0)


def test_calibration_produces_a_dated_artifact_shape():
    """#81 [REQ:SN]: the shadow-sigma calibration emits the artifact -- per-elevation sigma_H, a
    dev sigma, held-out coverage, and the operating envelope."""
    art = calibrate_shadow_sigma(_dem(), sun_az_deg=90.0, sigma_edge_px=1.0)
    assert art["schema_version"].startswith("stewie_shadow_sigma_calibration")
    assert art["n"] >= 4 and art["per_elevation"]
    assert 0.0 <= art["holdout_coverage"] <= 1.0
    for r in art["per_elevation"]:
        assert r["sigma_H_m"] > 0 and r["shadow_len_m"] > 0


def test_low_sun_is_the_informative_envelope():
    """[REQ:SN] the shadow channel is most precise at LOW sun (long shadow): sigma_H at 10deg is
    smaller than at 30deg for the same edge noise -- the operating envelope is the low-sun band.
    (High sun casts a sub-cell shadow on a low ridge = unmeasurable, itself the envelope's upper
    edge -- so the comparison uses two elevations that BOTH cast a measurable shadow.)"""
    art = calibrate_shadow_sigma(_dem(), sun_az_deg=90.0, elev_sweep=[10, 30], sigma_edge_px=1.0)
    by = {r["elev_deg"]: r["sigma_H_m"] for r in art["per_elevation"]}
    assert 10.0 in by and 30.0 in by                      # both cast a measurable shadow on the ridge
    assert by[10.0] < by[30.0]                            # low sun -> tighter height fix
