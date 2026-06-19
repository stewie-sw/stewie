"""[REQ:AS-11] lunar costmap-layer acceptance (§25 Phase 9): each layer affects path cost OR rejection
and a blocked cell exposes a visible reason. Hazard layers are isolated with controlled-geometry DEM
fixtures (ramp/cliff/plane -- as dem_stats' own tests do); the real crater_boulders DEM exercises the
composite."""
import math
import os

import numpy as np
import pytest

from lode import costmap_layers as cl

_DEM = os.path.join(os.path.dirname(__file__), "..", "samples", "crater_boulders", "heightmap.rf32")


def _ramp(angle_deg, n=24, cell_m=0.1):
    """A planar ramp of a given slope (lit, no drop): slope_deg_map -> angle everywhere."""
    z = (np.arange(n) * cell_m * math.tan(math.radians(angle_deg)))[None, :].repeat(n, 0)
    return z.astype(float), cell_m


def test_layer_names_cover_the_prd_set():
    for name in ("slope", "roughness", "slip", "tip_risk", "negative_obstacle",
                 "illumination", "psr", "energy", "keepout", "reservation"):
        assert name in cl.LAYER_NAMES


def test_slope_layer_rejects_steep_cells_with_reason():
    z, cm = _ramp(35.0)                                  # 35 deg > 25 deg cap
    ctx = cl.CostmapContext(Z=z, cell_m=cm, max_slope_deg=25.0, sun_el_deg=80.0)
    out = cl.compose(ctx)
    assert out.per_layer_block["slope"] > 0
    blocked = np.argwhere(~out.passable)
    assert len(blocked) and all(cl.blocking_reason(out, rc) in ("slope", "tip_risk") for rc in blocked)
    assert "slope" in out.reason[~out.passable].tolist()


def test_tip_risk_isolated_when_below_slope_cap():
    # slope cap raised above the tip limit (~35 deg): a 37 deg ramp passes the slope gate but trips tip
    z, cm = _ramp(37.0)
    ctx = cl.CostmapContext(Z=z, cell_m=cm, max_slope_deg=60.0, sun_el_deg=80.0)
    out = cl.compose(ctx)
    assert out.per_layer_block["slope"] == 0          # not rejected by slope
    assert out.per_layer_block["tip_risk"] > 0        # rejected by tip risk
    assert "tip_risk" in out.reason[~out.passable].tolist()


def test_negative_obstacle_blocks_a_cliff_with_reason():
    z = np.zeros((24, 24))
    z[:, 12:] = -1.0                                  # a 1 m drop-off cliff at column 12
    ctx = cl.CostmapContext(Z=z, cell_m=0.5, max_slope_deg=89.0, max_drop_m=0.15, sun_el_deg=80.0)
    # isolate the layer (compose's layers arg): a drop-off is otherwise also claimed by slope/tip_risk
    out = cl.compose(ctx, layers=[cl._negative_obstacle])
    assert out.per_layer_block["negative_obstacle"] > 0
    assert "negative_obstacle" in out.reason[~out.passable].tolist()


def test_keepout_and_reservation_block_with_reason():
    z = np.zeros((20, 20))
    ko = np.zeros(z.shape, bool); ko[5, 5] = True
    rv = np.zeros(z.shape, bool); rv[8, 8] = True
    ctx = cl.CostmapContext(Z=z, cell_m=0.5, max_slope_deg=89.0, sun_el_deg=80.0,
                            keepout_mask=ko, reserved_mask=rv)
    out = cl.compose(ctx)
    assert cl.blocking_reason(out, (5, 5)) == "keepout"
    assert cl.blocking_reason(out, (8, 8)) == "reservation"


def test_cost_layers_raise_cost_on_rough_sloped_terrain():
    z, cm = _ramp(15.0)                               # below the cap: passable but costed
    ctx = cl.CostmapContext(Z=z, cell_m=cm, max_slope_deg=25.0, sun_el_deg=80.0)
    out = cl.compose(ctx)
    # slope/slip/illumination/energy all add positive cost; the composite is above the 1.0 base
    for layer in ("slope", "slip", "illumination", "energy"):
        assert out.per_layer_cost[layer] > 0.0, layer
    assert float(out.cost.max()) > 1.0


@pytest.mark.skipif(not os.path.exists(_DEM), reason="crater_boulders DEM not present")
def test_real_terrain_composite_blocks_have_reasons():
    dem = np.fromfile(_DEM, dtype="<f4").reshape(256, 256).astype(float)[96:160, 96:160].copy()
    out = cl.compose(cl.CostmapContext(Z=dem, cell_m=0.02, sun_el_deg=12.0, sun_az_deg=200.0))
    blocked = out.reason[~out.passable].tolist()
    assert blocked, "real crater terrain should block some cells"
    assert all(r in cl.LAYER_NAMES for r in blocked)   # every blocked cell names a real layer
