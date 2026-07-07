"""[REQ:TM-03] The PHYSICS (TM) analysis drape: the terramechanics-spine per-cell fields draped on the
map as new globe kinds, so the "Physics (TM)" catalog group renders instead of being catalog-only.

Each servable physics kind is the REAL terramechanics-spine solver output (stewie.specs.terramechanics_spine
binds each catalog row to a live callable in stewie.physics.sinkage / slip), evaluated per-cell on the site's
REAL DEM slope -- the same values the drive-loop terramechanics solver produces, just draped. Grounded on the
committed LOLA Haworth tile (a native-resolution subsample of samples/lunar_dem/haworth_10km_5m -- real data,
not synthetic).

Asserts: the render helpers emit valid RGBA PNGs; each field is physically sensible on real terrain (slip /
sinkage / drive-energy / excavation-resistance RISE on steeper ground, traction margin and contact pressure
FALL); the kinds are globe kinds with legends whose colour ramp is the SAME single source the renderer uses;
and physics.compaction -- an OBSERVED (traffic/support) state, not a plan-independent per-cell DEM field -- is
NOT fabricated (the honest 6/7).
"""
import os

import numpy as np
import pytest

from stewie.server import gis_layers as G

_HAWORTH = os.path.join(os.path.dirname(__file__), "..", "..", "samples", "lunar_dem",
                        "haworth_10km_5m", "heightmap.rf32")
pytestmark = pytest.mark.skipif(not os.path.exists(_HAWORTH), reason="haworth DEM not present")

_CELL = 5.0            # native tile resolution (m/px)

# the six terramechanics-spine fields that ARE a plan-independent per-cell function of the DEM slope
_SERVABLE = ("bearing", "sinkage", "slip_risk", "traction_margin", "energy_cost", "excavation_resistance")
# fields that RISE on steeper ground vs those that FALL (physical sanity, robust to the entrapment tail)
_RISING = {"sinkage", "slip_risk", "energy_cost", "excavation_resistance"}
_FALLING = {"bearing", "traction_margin"}


def _haworth_window():
    """A real 96x96 crop of the committed LOLA Haworth tile (native 5 m cells) with genuine crater relief
    -- gentle and steep slope both present (min ~3.6 deg, max ~48.8 deg), real slope variation."""
    full = np.fromfile(_HAWORTH, dtype="<f4").reshape(2000, 2000).astype(float)
    return full[1000:1096, 1000:1096].copy(), _CELL


def _decode_png(png: bytes):
    from imageio.v3 import imread
    return imread(png)


def test_physics_helpers_emit_valid_rgba_png():
    dem, cell = _haworth_window()
    for kind in _SERVABLE:
        rgba = G._physics_rgba(dem, cell, kind)
        assert rgba is not None, kind
        assert rgba.shape == (dem.shape[0], dem.shape[1], 4)
        assert rgba.dtype == np.uint8
        dec = _decode_png(G._to_png(rgba))            # round-trips through a real PNG encoder/decoder
        assert dec.shape == rgba.shape
        assert np.array_equal(dec, rgba)


def test_terra_fields_are_real_and_slope_sensible():
    from lode.planner_routing import slope_deg_map
    dem, cell = _haworth_window()
    fields = G._terra_fields(dem, cell)
    slope = np.asarray(slope_deg_map(dem, cell), float)
    steep = slope > np.percentile(slope, 75)
    gentle = slope < np.percentile(slope, 25)
    for kind in _SERVABLE:
        f = np.asarray(fields[kind], float)
        assert f.shape == dem.shape and np.all(np.isfinite(f)), kind
        sm, gm = f[steep].mean(), f[gentle].mean()
        if kind in _RISING:
            assert sm > gm, f"{kind}: expected steeper ground to raise the field ({sm} !> {gm})"
        else:
            assert sm < gm, f"{kind}: expected steeper ground to lower the field ({sm} !< {gm})"


def test_physics_fields_come_from_the_real_terramechanics_spine():
    # the fields are the SAME real solver callables the terramechanics spine binds (no re-implementation):
    # a known slope must reproduce the spine solvers' output exactly.
    import math

    from stewie.physics import sinkage as SK
    from stewie.physics import slip as SL
    from stewie.specs import constants as K
    from stewie.specs import ipex_specs

    # a uniform-slope patch so the LUT-interpolated field equals the direct scalar solve at that slope
    deg = 12.0
    dem = np.tan(np.radians(deg)) * (_CELL * np.arange(16))[None, :] * np.ones((16, 1))
    from lode.planner_routing import slope_deg_map
    assert abs(float(np.median(slope_deg_map(dem, _CELL))) - deg) < 0.5   # patch really is ~deg slope
    fields = G._terra_fields(dem, _CELL)
    mass, g, n = float(ipex_specs.ROVER_MASS_CLASS_KG), float(ipex_specs.LUNAR_G_MS2), int(K.N_WHEELS)
    th = math.radians(deg)
    eq = SL.slip_sinkage_equilibrium(mass * g, th)
    # slip_risk == the spine slip_for_demand output at this slope (via the equilibrium solve)
    assert abs(float(np.median(fields["slip_risk"])) - eq["slip"]) < 5e-3
    # bearing == the spine contact_pressure at this slope's normal load
    p = SK.contact_pressure(mass * g * math.cos(th) / n, 0.18, 0.10)
    assert abs(float(np.median(fields["bearing"])) - p) < 1.0


def test_physics_kinds_are_globe_kinds_with_legends():
    from stewie.server.routers.layers import _GLOBE_KINDS, layers_legend
    legend = layers_legend()
    for kind in _SERVABLE:
        assert kind in _GLOBE_KINDS, kind
        assert kind in legend, kind
        entry = legend[kind]
        assert entry.get("text"), kind                 # a human-readable legend for the panel


def test_physics_legend_ramp_is_the_single_colour_source():
    # the /layers/legend physics entries are BUILT FROM the same PHYSICS_LAYERS spec the renderer colours
    # with -- one source of truth for the ramp (mirrors blocking_legend() <-> BLOCKING_COLORS).
    from stewie.server.routers.layers import layers_legend
    legend = layers_legend()
    for kind in _SERVABLE:
        spec = G.PHYSICS_LAYERS[kind]
        assert legend[kind]["ramp"] == spec["ramp"]
        assert legend[kind]["unit"] == spec["unit"]


def test_render_globe_wires_physics_end_to_end():
    # the full drape pipeline (slope -> spine solve -> colourise -> reproject to geographic) for each kind
    for kind in _SERVABLE:
        out = G.render_globe(kind, sun_el=15.0, sun_az=90.0, site="haworth")
        assert out is not None, kind
        rgba, bbox = out
        assert rgba.ndim == 3 and rgba.shape[2] == 4 and rgba.dtype == np.uint8
        assert {"south", "north", "west", "east"} <= set(bbox)
        assert bbox["north"] <= -85.0                  # a south-polar selenographic tile


def test_physics_compaction_is_not_fabricated():
    # physics.compaction is an OBSERVED compaction/sinter/support STATE (source_class observed/derived, the
    # TrafficMemory Dr family) -- it has no plan-independent per-cell value on the bare DEM, so it is NOT a
    # servable globe kind and the renderer returns None rather than inventing a field (honest 6/7).
    from stewie.server.routers.layers import _GLOBE_KINDS
    dem, cell = _haworth_window()
    assert "compaction" not in _GLOBE_KINDS
    assert G._physics_rgba(dem, cell, "compaction") is None
