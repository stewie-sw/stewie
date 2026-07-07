"""[REQ:TW-11] the TRAFFIC globe drape: the observed traversal-compaction state (TrafficMemory Dr) surfaced
as a PUBLIC map layer (/layers/globe/traffic.png), the same globe-drape pattern the cost/blocking/6-physics
layers ship. The traffic drape reprojects the site's persistent TrafficMemory over the FIXED work-area crop it
lives on (co-registered with the dem/slope/hazard drapes), so where the rover has driven it shows the REAL
per-cell compaction and where it has not it is transparent (honest -- no fabricated compaction).

No synthetic data: the end-to-end test drives the REAL conserved closed-loop sim (lode.autonomy.run_closed_loop)
over the REAL Haworth DEM and folds its true executed path via the same traffic_fold bridge the executive uses;
the compaction the drape colours is TrafficMemory.relative_density() (the conserved Dr). If the Haworth DEM
bundle is absent the DEM-dependent tests skip loudly.

Run: <venv>/bin/python -m pytest stewie/server/test_traffic_globe_tw11.py -q
"""
import os

import numpy as np
import pytest
from fastapi.testclient import TestClient

from stewie.server import gis_layers as G
from stewie.server.server import app

_HAWORTH = os.path.join(os.path.dirname(__file__), "..", "..", "samples", "lunar_dem",
                        "haworth_10km_5m", "heightmap.rf32")
_needs_dem = pytest.mark.skipif(not os.path.exists(_HAWORTH), reason="haworth DEM not present")


def _client():
    return TestClient(app, base_url="http://127.0.0.1")


def _alpha_nonzero(rgba: np.ndarray) -> int:
    return int(np.count_nonzero(np.asarray(rgba)[..., 3] > 0))


def _fold_real_sim_run(tmp_path) -> "object":
    """Drive the REAL conserved closed-loop sim on the real Haworth DEM and fold its true executed path into the
    site's persistent TrafficMemory (the SAME traffic_fold bridge routers/executive uses). Returns the folded
    TrafficMemory (already saved under tmp_path) so the globe drape can read the REAL compaction."""
    from lode import autonomy as AUT
    from lode import mission_planner as MP

    from stewie.server import state, traffic_fold as TF
    from stewie.twin import traffic_memory as TW
    dem, origin = state.moon_dem("haworth")
    base = dem[0] if isinstance(dem, tuple) else dem
    if base is None:
        pytest.skip("Haworth DEM bundle absent")
    cell_m = float(dem[1]) if isinstance(dem, tuple) else 5.0
    ax, ay = MP.flattest_anchor((np.asarray(base), cell_m))
    mission = MP.mission_from_dict({"name": "tw11-globe", "body": "moon",
        "orders": [{"action": "Level A", "kind": "cut", "x": ax + 50, "y": ay + 40,
                    "footprint_m2": 16.0, "depth_m": 0.2},
                   {"action": "Level B", "kind": "cut", "x": ax + 120, "y": ay + 90,
                    "footprint_m2": 16.0, "depth_m": 0.2}],
        "charger": [ax, ay]})
    out = AUT.run_closed_loop(mission, dem=dem, dem_origin=origin)
    mem = TF.traffic_from_run(out, charger=tuple(mission.charger), dem=dem, site="haworth",
                              data_dir=str(tmp_path), mission_id="tw11-globe")
    assert mem is not None, "the real driven path folded no traffic"
    TW.save_site(str(tmp_path), mem)
    return mem


def test_traffic_is_a_public_globe_kind_with_a_legend():
    # servable, like the cost/blocking/physics drapes: an allow-listed globe kind + a legend the panel renders.
    from stewie.server.routers.layers import _GLOBE_KINDS, layers_legend
    assert "traffic" in _GLOBE_KINDS
    legend = layers_legend()
    assert "traffic" in legend
    entry = legend["traffic"]
    assert entry.get("text")                                  # human-readable legend text
    assert entry.get("bands") and len(entry["bands"]) >= 3    # the sequential Dr band ramp (loose -> paved)


@_needs_dem
def test_traffic_globe_is_transparent_when_no_run_has_folded(monkeypatch, tmp_path):
    # an untraveled site -> the drape is a real (south-polar) raster that is FULLY transparent: honest, not a
    # fabricated corridor and not a 404. It carries the work-area sub-window bbox all the same.
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    out = G.render_globe("traffic", site="haworth")
    assert out is not None
    rgba, bbox = out
    assert rgba.ndim == 3 and rgba.shape[2] == 4 and rgba.dtype == np.uint8
    assert {"south", "north", "west", "east"} <= set(bbox)
    assert bbox["north"] <= -85.0                             # a south-polar selenographic tile (co-registered)
    assert _alpha_nonzero(rgba) == 0                          # nothing driven yet -> fully transparent


@_needs_dem
def test_traffic_globe_shows_real_compaction_after_a_real_sim_run(monkeypatch, tmp_path):
    # BEFORE: transparent. AFTER folding a REAL SIM run's driven path: the drape shows the REAL per-cell
    # compaction (non-empty raster), NOT synthetic.
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    empty = G.render_globe("traffic", site="haworth")[0]
    assert _alpha_nonzero(empty) == 0                         # baseline: untraveled -> transparent

    mem = _fold_real_sim_run(tmp_path)
    assert float(mem.summary()["peak_relative_density"]) > 0.0   # the real driven road hardened (conserved Dr)

    rgba, bbox = G.render_globe("traffic", site="haworth")
    assert rgba.dtype == np.uint8 and rgba.shape[2] == 4
    assert bbox["north"] <= -85.0
    assert _alpha_nonzero(rgba) > 0                           # the REAL compacted corridor is visibly draped
    # the drape's colours are the traffic Dr ramp (loose #f7f7f7 -> paved #252525); the visible pixels are
    # greys in that ramp, never an invented hue -- their max channel spread stays small (grey), proving it is
    # the Dr-band colouring, not a fabricated colour map.
    vis = rgba[rgba[..., 3] > 0][:, :3].astype(int)
    assert vis.size > 0
    chan_spread = int(np.abs(vis.max(axis=1) - vis.min(axis=1)).max())
    assert chan_spread <= 4                                   # grey ramp (R==G==B within rounding), not a hue


@_needs_dem
def test_traffic_globe_png_is_public_and_renders_end_to_end(monkeypatch, tmp_path):
    # the ROUTE: /layers/globe/traffic.png is PUBLIC (no auth, like every globe drape) and serves a real PNG.
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    _fold_real_sim_run(tmp_path)
    c = _client()
    r = c.get("/layers/globe/traffic.png?site=haworth")
    assert r.status_code == 200, r.text                       # public: no 401/403
    assert r.headers["content-type"] == "image/png"
    from io import BytesIO

    from PIL import Image
    a = np.asarray(Image.open(BytesIO(r.content)).convert("RGBA"))
    assert int(np.count_nonzero(a[..., 3] > 0)) > 0           # the real compacted corridor renders through the route
    # and the bbox route is public + agrees this is a south-polar tile
    rb = c.get("/layers/globe/traffic/bbox?site=haworth")
    assert rb.status_code == 200 and rb.json()["north"] <= -85.0
