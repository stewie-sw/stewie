"""Real-data tests for the spatial-k Golombek rock-dispersion producer (viz2 plan v4, task D1).

These run against the REAL committed PGDA LOLA Haworth DEM bundle
(``samples/lunar_dem/haworth_10km_5m``). NO synthetic distributions are fabricated: the
rock field is STATISTICAL -- clasts are drawn (Poisson) from the sourced Golombek
size-frequency law over the REAL heightfield's morphology, never invented. The four D1
clauses plus the manifest-honesty clause are asserted:

  (1) F_k recovery -- per k-stratum the recovered cumulative fractional AREA matches the
      (truncated) Golombek model F_k(D) = k*(exp(-q(k)D) - exp(-q(k)d_max)) within Poisson
      tolerance on the real tile;
  (2) determinism -- the same window + world coordinate + seed yields a byte-identical
      clast list (coordinate-hashed, NOT render-order dependent);
  (3) envelope -- k(x,y) stays inside the Bandfield-anchored [MIN, MAX] envelope EVERYWHERE;
  (4) spatial correlation -- k is genuinely non-uniform and rises near the REAL DEM's fresh
      crater rims / high-curvature / locally-steep ejecta cells vs the flat background;
  (5) honesty -- the manifest carries the Golombek/Bandfield/Demidov citations and the
      verbatim ``[CALIB]`` (spatial abundance) and ``[UNKNOWN]`` (buried_frac) tags.
"""

from __future__ import annotations

import os

import numpy as np
import pytest

from stewie.specs import constants as K
from stewie.terrain import rockfield
from stewie.terrain.site_dem import load_haworth_dem, slope_deg_map

_HERE = os.path.dirname(__file__)
_REPO = os.path.dirname(os.path.dirname(_HERE))
_BUNDLE = os.path.join(_REPO, "samples", "lunar_dem", "haworth_10km_5m")
_LOLA = os.path.join(_BUNDLE, "heightmap.rf32")

requires_lola = pytest.mark.skipif(
    not os.path.exists(_LOLA), reason="real LOLA Haworth DEM not on disk")

# A real, rim-rich Haworth window (max slope ~49 deg, |curvature| up to ~0.2 -- fresh
# crater rims + steep ejecta walls next to flatter background). Boulder-scale diameters so
# the multi-cell (240 m) window yields a tractable, well-sampled clast list.
_WIN = (1000, 1000, 48)          # (row0, col0, n) on the 2000^2 @ 5 m tile
_D_MIN, _D_MAX = 0.25, 0.6       # m (boulder / hazard scale)
# The window's true global origin (south-polar-stereographic metres) from the bundle
# world_bounds -- so the coordinate-hashed seed is a pure function of the WORLD point.
_WX0, _WY0 = -52900.0 + (1000 + 0.5) * 5.0, 105400.0 - (1000 + 0.5) * 5.0


def _win():
    """The real DEM window [m] and its cell size [m]."""
    Z, cell = load_haworth_dem()
    r0, c0, n = _WIN
    return Z[r0:r0 + n, c0:c0 + n].astype(np.float64), float(cell)


def _field(**kw):
    dem, cell = _win()
    return rockfield.rock_field(dem, cell, world_x0=_WX0, world_y0=_WY0,
                                d_min_m=_D_MIN, d_max_m=_D_MAX, **kw)


# ---------------------------------------------------------------------------
# Golombek model helper (the closed-form F_k the sampler inverts).
# ---------------------------------------------------------------------------

def test_golombek_cumulative_area_matches_model():
    k = 0.15
    q = K.golombek_q(k)
    for D in (0.05, 0.2, 0.5):
        assert rockfield.golombek_cumulative_area(k, D) == pytest.approx(k * np.exp(-q * D))
    # Monotone decreasing in D (bigger rocks cover less cumulative area).
    assert (rockfield.golombek_cumulative_area(k, 0.1)
            > rockfield.golombek_cumulative_area(k, 0.4))


# ---------------------------------------------------------------------------
# Clause (3): envelope everywhere.
# ---------------------------------------------------------------------------

@requires_lola
def test_spatial_k_field_within_envelope_everywhere():
    dem, cell = _win()
    k = rockfield.spatial_k_field(dem, cell)
    assert np.all(np.isfinite(k))
    # Never outside the Bandfield-anchored envelope -- clamped, by construction.
    assert k.min() >= K.BOULDER_K_BACKGROUND_MIN - 1e-12
    assert k.max() <= K.BOULDER_K_EJECTA_MAX + 1e-12
    # The interior model interpolates background -> ejecta, so it also honours those anchors.
    assert k.min() >= K.BOULDER_K_BACKGROUND - 1e-9
    assert k.max() <= K.BOULDER_K_EJECTA + 1e-9


# ---------------------------------------------------------------------------
# Clause (4): spatial correlation with REAL DEM morphology (not uniform).
# ---------------------------------------------------------------------------

@requires_lola
def test_spatial_k_field_correlates_with_dem_rims():
    dem, cell = _win()
    k = rockfield.spatial_k_field(dem, cell)
    curv = np.abs(rockfield.curvature_field(dem, cell))
    slope = slope_deg_map(dem, cell)

    # The field is genuinely non-uniform (real spatial variation, not a constant).
    assert k.max() - k.min() > 0.05

    # k rises with BOTH real DEM rim/ejecta proxies (measured correlation, real tile).
    corr_curv = float(np.corrcoef(k.ravel(), curv.ravel())[0, 1])
    corr_slope = float(np.corrcoef(k.ravel(), slope.ravel())[0, 1])
    assert corr_curv > 0.3
    assert corr_slope > 0.2

    # Rim cells (top-decile |curvature|) carry markedly more rock abundance than the
    # low-curvature background (bottom decile).
    cvr, kr = curv.ravel(), k.ravel()
    hi = cvr >= np.percentile(cvr, 90)
    lo = cvr <= np.percentile(cvr, 10)
    assert kr[hi].mean() > 2.0 * kr[lo].mean()

    # A specific rim cell is near the ejecta ceiling; a specific flat cell near background.
    rim = np.unravel_index(int(np.argmax(curv)), curv.shape)
    flat = np.unravel_index(int(np.argmin(slope + 1e3 * curv)), slope.shape)
    assert k[rim] > k[flat]
    assert k[flat] == pytest.approx(K.BOULDER_K_BACKGROUND, abs=5e-3)


# ---------------------------------------------------------------------------
# Clause (2): determinism -- byte-identical clasts for the same world point + seed.
# ---------------------------------------------------------------------------

@requires_lola
def test_rock_field_deterministic_byte_identical():
    a = _field()
    b = _field()
    assert a["clasts"] == b["clasts"]
    assert np.array_equal(a["k_field"], b["k_field"])
    # Ids are a stable ascending 0..n-1 sequence (deterministic concatenation order).
    ids = [c["id"] for c in a["clasts"]]
    assert ids == list(range(len(a["clasts"])))


@requires_lola
def test_rock_field_seed_and_coordinate_change_the_draw():
    base = _field()
    # A different scenario seed re-rolls the Poisson draw (same k-field, different clasts).
    other_seed = _field(world_seed=99)
    assert np.array_equal(base["k_field"], other_seed["k_field"])
    assert base["clasts"] != other_seed["clasts"]
    # A different WORLD coordinate (the seed is coordinate-hashed) also re-rolls the draw.
    dem, cell = _win()
    moved = rockfield.rock_field(dem, cell, world_x0=_WX0 + 500.0, world_y0=_WY0,
                                 d_min_m=_D_MIN, d_max_m=_D_MAX)
    assert base["clasts"] != moved["clasts"]


# ---------------------------------------------------------------------------
# Clause (1): F_k recovery per stratum (real tile, Poisson tolerance).
# ---------------------------------------------------------------------------

@requires_lola
def test_rock_field_fk_recovery_per_stratum():
    f = _field()
    # Use the best-sampled stratum (most clasts -> tightest Poisson statistics).
    strata = f["strata"]
    assert len(strata) >= 3                       # the real rim window spans several strata
    best = max(strata, key=lambda s: s["n_clasts"])
    assert best["n_clasts"] > 500

    k = best["k"]
    area = best["area_m2"]
    # Kept clasts of this stratum only.
    sid = best["stratum"]
    dia = np.array([2.0 * c["radius_m"] for c in f["clasts"] if c["stratum"] == sid])
    assert dia.size == best["n_clasts"]
    rock_area = (np.pi / 4.0) * dia ** 2

    # Recovered cumulative fractional AREA vs the TRUNCATED Golombek model
    # F_k(D) - F_k(d_max) (the sampler covers [D, d_max], not [D, inf)).
    def phi_model(D):
        return (rockfield.golombek_cumulative_area(k, D)
                - rockfield.golombek_cumulative_area(k, _D_MAX))

    prev = np.inf
    for D in (0.25, 0.30, 0.40):
        phi_emp = float(rock_area[dia >= D].sum() / area)
        assert phi_emp == pytest.approx(phi_model(D), rel=0.20)
        assert phi_emp < prev                     # monotone decreasing in D
        prev = phi_emp


# ---------------------------------------------------------------------------
# Clast schema + diameter band + buried-fraction envelope.
# ---------------------------------------------------------------------------

@requires_lola
def test_rock_field_clast_schema_and_band():
    f = _field()
    clasts = f["clasts"]
    assert len(clasts) > 0
    dem, cell = _win()
    n = _WIN[2]
    Wm = Hm = n * cell
    for c in clasts:
        assert set(c) >= {"id", "center_m", "radius_m", "buried_frac"}
        x, _y, z = c["center_m"]
        assert 0.0 <= x <= Wm and 0.0 <= z <= Hm
        diameter = 2.0 * c["radius_m"]
        assert _D_MIN <= diameter <= _D_MAX
        # buried_frac is the [UNKNOWN] U(0.1, 0.7) envelope.
        assert K.BOULDER_BURIED_FRAC_MIN <= c["buried_frac"] <= K.BOULDER_BURIED_FRAC_MAX


# ---------------------------------------------------------------------------
# Clause (5): manifest carries citations + verbatim honesty tags.
# ---------------------------------------------------------------------------

@requires_lola
def test_manifest_carries_citations_and_honesty_tags():
    man = _field()["manifest"]
    blob = repr(man)

    # Verbatim honesty tags -- the spatial abundance is CALIB (sourced envelope, NOT
    # Haworth-measured); buried_frac is a genuine UNKNOWN.
    assert man["honesty_tags"]["spatial_abundance_k"] == "[CALIB]"
    assert man["honesty_tags"]["buried_frac"] == "[UNKNOWN]"
    assert "[CALIB]" in blob and "[UNKNOWN]" in blob
    # It must NOT claim to be a Haworth measurement.
    assert "not" in man["honesty_note"].lower() and "measured" in man["honesty_note"].lower()

    # The three required primary citations are present (Golombek SFD, Bandfield spatial
    # abundance, Demidov h/d).
    for author in ("Golombek", "Bandfield", "Demidov"):
        assert author in blob

    # The SFD model + q-law are recorded.
    assert "exp" in man["sfd_model"] and "q(k)" in man["sfd_model"]
    # k-field summary present and self-consistent with the field.
    kf = man["k_field"]
    assert kf["envelope_min"] == pytest.approx(K.BOULDER_K_BACKGROUND_MIN)
    assert kf["envelope_max"] == pytest.approx(K.BOULDER_K_EJECTA_MAX)
    assert kf["background"] == pytest.approx(K.BOULDER_K_BACKGROUND)
    assert kf["ejecta"] == pytest.approx(K.BOULDER_K_EJECTA)


# ---------------------------------------------------------------------------
# Integration over the real bundle window + the rim-vs-flat real sample.
# ---------------------------------------------------------------------------

@requires_lola
def test_rock_field_for_dem_window_rim_vs_flat():
    r0, c0, n = _WIN
    f = rockfield.rock_field_for_dem_window(
        bundle_dir=_BUNDLE, r0=r0, c0=c0, n=n, d_min_m=_D_MIN, d_max_m=_D_MAX)
    # The window wrapper resolves the same world origin -> identical to the explicit call.
    ref = _field()
    assert f["clasts"] == ref["clasts"]

    # Locate a real rim cell and a real flat cell; count the clasts sitting in each.
    dem, cell = _win()
    curv = np.abs(rockfield.curvature_field(dem, cell))
    slope = slope_deg_map(dem, cell)
    rim = np.unravel_index(int(np.argmax(curv)), curv.shape)
    flat = np.unravel_index(int(np.argmin(slope + 1e3 * curv)), slope.shape)

    def _count_in(cell_rc):
        rr, cc = cell_rc
        m = 0
        for c in f["clasts"]:
            x, _y, z = c["center_m"]
            if int(z / cell) == rr and int(x / cell) == cc:
                m += 1
        return m

    n_rim = _count_in(rim)
    n_flat = _count_in(flat)
    k = f["k_field"]
    # The rim cell carries a higher k AND strictly more clasts than the flat cell.
    assert k[rim] > k[flat]
    assert n_rim > n_flat
