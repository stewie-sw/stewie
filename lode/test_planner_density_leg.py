"""#242 1b: the PLANNER's per-leg haul energy responds to the REAL per-cell regolith density along the
route. A leg over a compacted wheel trail (density up) stiffens BEARING -> less sinkage -> less slip ->
less drive energy than the same leg over loose ground. Reuses the grounded density_stiffening relation
the simulator drive loop uses (no new law); density_field=None is byte-identical to the prior uniform-soil
planner (back-compat). REAL DATA only: the density + height fields come from committed physics-evolved
scenes -- samples/tread_track_4wheel, a 4-wheel drive pass: t000 = before (loose), t018 = after (the
compacted trail). No synthetic data."""
import json
import os

import numpy as np
import pytest

from lode import planner_endurance as PE
from lode import planner_trips as PT
from stewie.specs import constants as K

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LOOSE = os.path.join(_ROOT, "samples", "tread_track_4wheel", "t000")     # before the drive (loose)
_COMPACT = os.path.join(_ROOT, "samples", "tread_track_4wheel", "t018")   # after the drive (compacted)
_HAVE = pytest.mark.skipif(not os.path.isfile(os.path.join(_COMPACT, "density.rf32")),
                           reason="tread_track_4wheel sample scene absent")
_KW = dict(loads=1, drum_kg=8.0, g=K.g, soil=None, drive_j_per_m=135.0, rover_mass_kg=30.0)


def _load(scene):
    g = json.load(open(os.path.join(scene, "metadata.json")))["grid"]
    H, W, cell = int(g["height"]), int(g["width"]), float(g["cell_m"])
    Z = np.fromfile(os.path.join(scene, "heightmap.rf32"), dtype="<f4").reshape(H, W).astype(float)
    rho = np.fromfile(os.path.join(scene, "density.rf32"), dtype="<f4").reshape(H, W).astype(float)
    return Z, rho, cell


def test_slip_alpha_to_slip_responds_to_density():
    """Unit: denser ground slips less; density=None == loose surface density (back-compat)."""
    loose = PE.slip_alpha_to_slip(12.0, density=K.RHO_SURFACE)
    dense = PE.slip_alpha_to_slip(12.0, density=K.RHO_DEEP)
    none = PE.slip_alpha_to_slip(12.0, density=None)
    assert dense < loose, "compacted ground must slip less than loose surface"
    assert abs(none - loose) < 1e-12, "density=None must equal loose-surface density (back-compat)"


@_HAVE
def test_haul_energy_lower_over_compacted_trail():
    """Integration: the same haul leg costs LESS over the real compacted trail than over uniform-loose."""
    Z, rho_c, cell = _load(_COMPACT)
    H, W = Z.shape
    # route a short leg whose single-segment midpoint lands on the MOST compacted interior cell (the
    # trail), so the per-segment density sample is genuinely high and on-grid (metres = index * cell).
    interior = rho_c[5:H - 5, 5:W - 5]
    rr, cc = np.unravel_index(int(np.argmax(interior)), interior.shape)
    r, c = rr + 5, cc + 5
    xc, yc = c * cell, r * cell
    wp = [(xc - 2 * cell, yc), (xc + 2 * cell, yc)]
    dem, origin = (Z, cell), (0.0, 0.0)
    r_uniform = PT._segmented_haul_energy(dem, origin, wp, density_field=None, **_KW)
    r_compact = PT._segmented_haul_energy(dem, origin, wp, density_field=rho_c, **_KW)
    assert r_uniform is not None and r_compact is not None
    e_uniform, _flat_u = r_uniform   # [REQ:EP-01] (total, flat-drive baseline) -- total is compared here
    e_compact, _flat_c = r_compact
    assert rho_c[r, c] > K.RHO_SURFACE, "sanity: the sampled trail cell is genuinely compacted (real data)"
    assert e_compact < e_uniform, f"compacted trail must cost less drive energy: {e_compact} !< {e_uniform}"


@_HAVE
def test_loose_scene_matches_uniform_surface():
    """A scene whose density is everywhere <= RHO_SURFACE plans identically to None: the grounded
    density_stiffening = max(1, rho/rho_surface) clamps to 1, so loose ground is the back-compat path."""
    Z, rho_l, cell = _load(_LOOSE)
    H, W = Z.shape
    assert rho_l.max() <= K.RHO_SURFACE + 1e-6, "t000 is the pre-drive loose scene (real)"
    wp = [(10 * cell, 10 * cell), ((W // 2) * cell, 10 * cell)]
    dem, origin = (Z, cell), (0.0, 0.0)
    r_none = PT._segmented_haul_energy(dem, origin, wp, density_field=None, **_KW)
    r_loose = PT._segmented_haul_energy(dem, origin, wp, density_field=rho_l, **_KW)
    assert r_none is not None and r_loose is not None
    e_none, _ = r_none               # [REQ:EP-01] (total, flat-drive baseline) -- total is compared here
    e_loose, _ = r_loose
    assert abs(e_loose - e_none) < 1e-9, "loose (<=surface) field must equal the uniform-surface plan"
