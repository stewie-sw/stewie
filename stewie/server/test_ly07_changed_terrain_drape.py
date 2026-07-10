"""[REQ:LY-07] the signed terrain-change / dig-fill-depth drape (before-vs-after DEM difference).

The visual producer for the LY-01 catalog rows ``map.changed_terrain`` + ``evidence.before_after_dem``:
a SIGNED elevation-difference drape of the composed as-built/observed surface
(``stewie.twin.terrain_view.compose_terrain_view``, read via ``state.current_terrain_view``) MINUS the
pristine base DEM. CUT (as-built below base) is negative/red, FILL/berm (above base) positive/blue, on a
diverging ramp about zero; an unworked cell (no change) is fully transparent; the drape carries the
as_built/twin versions it was computed from. Per-cell depth is read back at ``/world/point``
(``runtime_evidence.as_built_delta_m`` -- the SAME ``view.heights - base`` at the clicked cell).

Proven END-TO-END on the REAL Haworth LOLA tile (no synthetic terrain): a conserved cut+fill transaction
(``POST /executive/run`` folds the mass-conserving cut/fill into the site TerrainMemory, exactly the SD-01
path) makes the drape show the cut region NEGATIVE (red) and the berm POSITIVE (blue), with the cut depth
matching the transaction's ``max_cut_m`` and the imprinted net volume matching the conserved authority's
``net_volume_m3``.
"""
from __future__ import annotations

import importlib

import numpy as np
import pytest
from fastapi.testclient import TestClient

H = {"X-API-Key": "test-key"}

# a conserved cut+fill transaction on the site build frame: cut a pad (loads the drum) + build a berm
# elsewhere (fills FROM the drum). A cut LOWERS its footprint (negative), a fill RAISES the berm (positive)
# -- a clean, deterministic two-signed before/after change, mass-conserved by the authority.
_CUT_FILL = [
    {"kind": "cut", "x": 12.0, "y": 12.0, "action": "dig pad", "footprint_m2": 36.0, "depth_m": 0.5},
    {"kind": "fill", "x": 45.0, "y": 45.0, "action": "build berm", "footprint_m2": 25.0, "depth_m": 0.4},
]


@pytest.fixture()
def client(monkeypatch, tmp_path):
    """A fresh app over a fresh per-test data dir (its own empty TerrainMemory) -- the same fixture shape as
    test_sd01_terrain_transaction: DEV_OPEN + an API key, twin/WSS reset so the run starts from genesis."""
    monkeypatch.setenv("STEWIE_API_KEY", "test-key")
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("STEWIE_DEV_OPEN", "1")
    from stewie.server import state as S
    monkeypatch.setattr(S, "_TWIN", None)
    monkeypatch.setattr(S, "_WSS", None)
    import stewie.server.server as srv
    importlib.reload(srv)
    yield TestClient(srv.app)
    monkeypatch.undo()
    importlib.reload(srv)


def test_ly07_changed_drape_shows_cut_negative_berm_positive_on_real_site(client):
    """[REQ:LY-07] After a conserved cut+fill on the REAL Haworth DEM, the signed-difference drape colours the
    cut region NEGATIVE (red) and the berm POSITIVE (blue), unworked ground transparent; the cut depth matches
    ``max_cut_m`` and the imprinted net volume matches the conserved authority's ``net_volume_m3``; the per-cell
    depth is read back at /world/point; and the render carries the as_built/twin versions it was computed from."""
    from stewie.server import gis_layers as GL
    from stewie.server import state as S

    dem, origin = S.moon_dem("haworth")
    z0, cell = dem
    z0 = np.asarray(z0, dtype=float)

    # BEFORE any build: the composed view equals the pristine DEM -> the change field is all zero, and the
    # drape is FULLY TRANSPARENT (honest: an unworked surface shows no change).
    view0 = S.current_terrain_view("haworth", (z0.copy(), cell), origin)
    changed0 = np.asarray(view0.heights, dtype=float) - z0
    assert not (np.abs(changed0) > GL._CHANGED_EPS_M).any(), "no build yet -> no terrain change"
    assert int(GL._changed_terrain_rgba(changed0)[..., 3].max()) == 0, "zero-change drape must be transparent"

    # EXECUTE the cut+fill as a SIM run: the execute->remember loop folds the conserved cut/fill into the
    # site's TerrainMemory (the SD-01 path). Two order kinds -> a genuine two-signed before/after transaction.
    r = client.post("/executive/run", headers=H, json={"orders": _CUT_FILL, "site": "haworth"})
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True and r.json()["safed"] is False

    tm = client.get("/twin/terrain/haworth", headers=H).json()
    assert tm["recorded"] is True and tm["version"] >= 1 and tm["chain_valid"] is True
    assert tm["max_cut_m"] > 0.0, "the cut pad must lower the terrain (max_cut_m > 0)"
    assert tm["max_fill_m"] > 0.0, "the berm fill must raise the terrain (max_fill_m > 0)"

    # the SIGNED change field the drape colours = the composed as-built view (compose_terrain_view) minus the
    # pristine base DEM. It carries the as_built version the fold advanced.
    view = S.current_terrain_view("haworth", (z0.copy(), cell), origin)
    assert view.as_built_version >= 1
    changed = np.asarray(view.heights, dtype=float) - z0
    assert (changed < -1e-6).any(), "a cut must produce cells BELOW base (negative change)"
    assert (changed > 1e-6).any(), "a berm fill must produce cells ABOVE base (positive change)"

    # DEPTHS MATCH THE TRANSACTION: the deepest cut equals the authority's reported max_cut_m, and the
    # imprinted net volume equals the conserved authority's net_volume_m3 (mass-conserved, not a cosmetic edit).
    assert np.isclose(-float(changed.min()), tm["max_cut_m"], rtol=1e-3, atol=1e-3), (
        f"drape deepest cut {-float(changed.min())} != authority max_cut_m {tm['max_cut_m']}")
    imprint_net_m3 = float(changed.sum()) * cell * cell
    assert np.isclose(imprint_net_m3, tm["net_volume_m3"], rtol=1e-3, atol=1e-2), (
        f"imprint net {imprint_net_m3} != conserved authority net {tm['net_volume_m3']}")

    # the DRAPE (the signed-diff producer): cut cell red + opaque, berm cell blue + opaque, unworked transparent.
    rgba = GL._changed_terrain_rgba(changed)
    assert rgba.shape == (*changed.shape, 4) and rgba.dtype == np.uint8
    cr, cc = np.unravel_index(int(np.argmin(changed)), changed.shape)   # the deepest CUT cell (most negative)
    fr, fc = np.unravel_index(int(np.argmax(changed)), changed.shape)   # the highest FILL/berm cell (most positive)
    cut_px, fill_px = rgba[cr, cc], rgba[fr, fc]
    assert cut_px[3] > 0 and int(cut_px[0]) > int(cut_px[2]), "cut cell must be opaque + red (R > B)"
    assert fill_px[3] > 0 and int(fill_px[2]) > int(fill_px[0]), "berm cell must be opaque + blue (B > R)"
    # an exactly-unworked cell (the tile corner, far from the worked region) is fully transparent.
    assert changed[0, 0] == 0.0 and int(rgba[0, 0, 3]) == 0, "unworked ground must be transparent"

    # PER-CELL DEPTH via /world/point (the selection inspector): the clicked cut/berm locations report the
    # SAME signed change (runtime_evidence.as_built_delta_m == view.heights - base at the cell).
    pj_cut = client.get("/world/point?site=haworth&x=12&y=12", headers=H).json()
    pj_fill = client.get("/world/point?site=haworth&x=45&y=45", headers=H).json()
    assert pj_cut["runtime_evidence"]["as_built_delta_m"] < 0.0, "the cut point reads a NEGATIVE depth"
    assert pj_fill["runtime_evidence"]["as_built_delta_m"] > 0.0, "the berm point reads a POSITIVE height"
    assert pj_cut["runtime_evidence"]["cell_source"] == "as_built"

    # the GLOBE producer wires end to end and CARRIES the as_built/twin versions it was computed from.
    out = GL.render_globe("changed_terrain", site="haworth")
    assert out is not None, "the changed_terrain drape must render"
    grgba, bbox = out
    assert grgba.ndim == 3 and grgba.shape[2] == 4 and grgba.dtype == np.uint8
    assert {"south", "north", "west", "east"} <= set(bbox)
    assert bbox["as_built_version"] >= 1 and "twin_version" in bbox, "the drape must carry its versions"
    assert int(grgba[..., 3].max()) > 0, "the geographic drape must show the worked change (non-transparent)"


def test_ly07_globe_kind_registered_with_legend_and_catalog():
    """[REQ:LY-07] changed_terrain is an allow-listed globe kind with a diverging cut<->fill legend, and the
    LY-01 catalog carries the two rows this drape is the producer for (map.changed_terrain +
    evidence.before_after_dem)."""
    import json
    import os

    from stewie.server.routers.layers import _GLOBE_KINDS, layers_legend
    assert "changed_terrain" in _GLOBE_KINDS
    entry = layers_legend()["changed_terrain"]
    assert entry.get("text") and entry.get("ramp"), "a human-readable diverging legend for the panel"

    root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    with open(os.path.join(root, "stewie", "server", "layer_catalog.json"), encoding="utf-8") as fh:
        ids = {row["id"] for row in json.load(fh)["layers"]}
    assert {"map.changed_terrain", "evidence.before_after_dem"} <= ids, (
        "the drape's LY-01 catalog rows must be registered")
