"""[REQ:RS-02] the planner consumes the OBSERVED world, not just the static DEM. The planning surface
every plan route uses (state.as_built_dem -> current_terrain_view) now composes the site's own observed
twin (DT-04) over the prior DEM, so an observed hazard ABSENT from the static DEM measurably changes the
hazard costmap the route planner keys on: a raised obstacle the twin observed becomes NOGO cells the
static-DEM costmap does not have. (The observed-DEM layer is wired + verified here; the full multi-layer
observed world -- occupancy / rock-object graph / changed-terrain mask / map-uncertainty with per-cell
provenance -- is the remaining partial.)"""
import importlib
import os
import tempfile

import numpy as np

from dart.hazard_map import build_hazard_map

_R0, _C0, _WIN = 500, 500, 120     # a real-DEM window around the injected hazard


def _state_with_clean_twin(monkeypatch):
    monkeypatch.setenv("STEWIE_DATA_DIR", tempfile.mkdtemp())
    from stewie.server import state as S
    importlib.reload(S)
    monkeypatch.setattr(S, "_TWIN", None)
    monkeypatch.setattr(S, "_TWINS", {})
    return S


def _region(surface):
    z = surface[0] if isinstance(surface, tuple) else surface
    return np.asarray(z)[_R0:_R0 + _WIN, _C0:_C0 + _WIN]


def test_an_observed_hazard_changes_the_planning_surface_and_costmap(monkeypatch):
    S = _state_with_clean_twin(monkeypatch)
    dem, _anchor = S.moon_dem("haworth")
    z, cell = dem[0], dem[1]
    origin = (0.0, 0.0)

    # baseline: the composed planning surface + its hazard costmap over the static DEM (no observed patch).
    base = _region(S.as_built_dem("haworth", (z, cell), origin))
    base_hz = build_hazard_map((base, cell), dem_origin=origin, max_slope_deg=20.0)
    base_nogo = int((~base_hz.traversable).sum())

    # inject an OBSERVED hazard absent from the static DEM: a +40 m obstacle the twin measured.
    tw = S.twin("haworth")
    r, c = 40, 40                               # inside the window (window-local 40 -> global _R0+40)
    bump = np.asarray(tw.base[_R0 + r:_R0 + r + 16, _C0 + c:_C0 + c + 16]) + 40.0
    tw.apply_patch(bump.tolist(), origin_rc=(_R0 + r, _C0 + c), provenance="rs02-observed-hazard")

    obs = _region(S.as_built_dem("haworth", (z, cell), origin))
    obs_hz = build_hazard_map((obs, cell), dem_origin=origin, max_slope_deg=20.0)
    obs_nogo = int((~obs_hz.traversable).sum())

    # the planning surface changed by the injected height where the twin observed it.
    assert float(np.abs(obs - base)[r:r + 16, c:c + 16].max()) >= 39.0
    # and the observed hazard MEASURABLY changes the costmap: NOGO cells appear that the static DEM lacked.
    assert obs_nogo > base_nogo, f"observed hazard did not raise no-go cells ({base_nogo} -> {obs_nogo})"
    # the new no-go concentrates at the observed obstacle (its steep rim), not spread across the static map.
    assert not np.isfinite(obs_hz.cost[r:r + 16, c:c + 16]).all()


def test_the_observed_layer_is_the_site_specific_twin_not_a_global_one(monkeypatch):
    # RS-02 reads the OBSERVED world per site (DT-04): a hazard observed on one site does not leak into
    # another site's planning surface.
    S = _state_with_clean_twin(monkeypatch)
    dem, _anchor = S.moon_dem("haworth")
    z, cell = dem[0], dem[1]
    tw = S.twin("shackleton_rim")
    tw.apply_patch((np.asarray(tw.base[_R0:_R0 + 8, _C0:_C0 + 8]) + 40.0).tolist(),
                   origin_rc=(_R0, _C0), provenance="rs02")
    # haworth's planning surface is unaffected by a shackleton observation.
    haw = _region(S.as_built_dem("haworth", (z, cell), (0.0, 0.0)))
    assert np.isfinite(haw).all()
    base = _region((z, cell))
    assert float(np.abs(haw - base).max()) < 1.0   # no shackleton hazard bled into haworth
