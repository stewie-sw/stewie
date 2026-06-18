"""PM-09: per-cell elevation uncertainty uses EFFECTIVE sample support (correlated one-view pixels are
not independent) and an uncertainty floor -- not naive per_sigma/sqrt(N)."""
import numpy as np

from dart.mapping import ElevationMap


def _map(count):
    count = np.asarray(count, float)
    elev = np.where(count > 0, 1500.0, np.nan)
    return ElevationMap(elevation=elev, count=count, cell_m=0.1,
                        n_points=int(count.sum()), n_frames=3)


def test_dense_one_view_pixels_are_capped_not_independent():
    m = _map([[100, 2], [0, 8]])
    sigma, n_eff = m.cell_uncertainty(per_sample_sigma_m=0.05, floor_m=0.0, correlation_cap=8)
    # 100 correlated pixels do NOT beat the cap: n_eff caps at 8, sigma = 0.05/sqrt(8), NOT 0.05/sqrt(100)
    assert n_eff[0, 0] == 8.0
    assert abs(sigma[0, 0] - 0.05 / np.sqrt(8)) < 1e-9
    assert sigma[0, 0] > 0.05 / np.sqrt(100) + 1e-6           # strictly worse than naive independence
    assert n_eff[0, 1] == 2.0 and abs(sigma[0, 1] - 0.05 / np.sqrt(2)) < 1e-9


def test_uncertainty_floor_is_never_undercut():
    m = _map([[10000]])
    sigma, _ = m.cell_uncertainty(per_sample_sigma_m=0.05, floor_m=0.03, correlation_cap=8)
    assert sigma[0, 0] == 0.03                                # floored, no matter how many pixels


def test_unobserved_cells_are_nan():
    m = _map([[0, 5]])
    sigma, n_eff = m.cell_uncertainty()
    assert np.isnan(sigma[0, 0]) and n_eff[0, 0] == 0.0
    assert np.isfinite(sigma[0, 1]) and n_eff[0, 1] == 5.0
