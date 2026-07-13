"""Real-data gate for scripts/tile_bundle.py — tile a committed LOLA bundle like Haworth and assert
the invariants the widen task requires: tile count == ceil(extent/tile_m); every tile center lat/lon
is finite + south-polar; the no-leakage split holds (train chips share zero pixels with val/test);
splits are disjoint and cover; the emitted GeoJSON carries the bundle's VERBATIM LOLA provenance.

Runs over the real ``samples/lunar_dem/haworth_10km_5m`` bundle (committed, always on disk). Output is
written to a tmp dir, so the test never touches the committed ``tiling/`` artifacts. No synthetic data.
"""
from __future__ import annotations

import json
import math
import os

import pytest

from scripts import tile_bundle as TB

_BUNDLE = os.path.join(TB.DEFAULT_SITE_ROOT, "haworth_10km_5m")


@pytest.fixture(scope="module")
def tiled(tmp_path_factory):
    if not os.path.exists(os.path.join(_BUNDLE, "heightmap.rf32")):
        pytest.skip(f"real bundle missing: {_BUNDLE}")
    out = tmp_path_factory.mktemp("tiling")
    man = TB.tile_bundle(_BUNDLE, out_dir=str(out))
    return man, str(out)


def _read(out: str, name: str) -> dict:
    with open(os.path.join(out, name), encoding="utf-8") as fh:
        return json.load(fh)


def test_tile_count_is_ceil_extent_over_tile_m(tiled):
    man, out = tiled
    idx = _read(out, "tile_index.json")
    # 10 km extent / 100 m tiles -> 100 x 100 = 10000 tiles
    assert idx["n_cols"] == 100 and idx["n_rows"] == 100
    assert idx["n_tiles"] == 100 * 100 == len(idx["tiles"])
    assert man["tiling_spec"]["n_tiles"] == 10000


def test_pixel_size_note_records_the_20px_vs_100px_difference(tiled):
    man, _out = tiled
    spec = man["tiling_spec"]
    # at the 5 m native LOLA cell a 100 m tile is 20 px (Haworth 1 m: 100 px) -- the task's note
    assert spec["tile_px"] == 20 and spec["sub_px"] == 5
    assert "20 px" in spec["pixel_size_note"] and "100 px" in spec["pixel_size_note"]


def test_every_tile_center_is_finite_and_south_polar(tiled):
    _man, out = tiled
    idx = _read(out, "tile_index.json")
    for t in idx["tiles"]:
        lat, lon = t["center_latlon"]
        assert math.isfinite(lat) and math.isfinite(lon)
        assert lat < -80.0, t["tile_id"]           # a real south-polar site, never 0/NaN


def test_splits_disjoint_cover_and_no_leakage(tiled):
    _man, out = tiled
    sp = _read(out, "splits.json")
    train = set(sp["train_tiles"]); val = set(sp["val_tiles"])
    test = set(sp["test_tiles"]); dropped = set(sp["dropped_tiles"])
    assert train and val and test
    assert train.isdisjoint(val) and train.isdisjoint(test) and val.isdisjoint(test)
    idx = _read(out, "tile_index.json")
    valid = {t["index"] for t in idx["tiles"] if t["valid_frac"] >= 1.0}
    assert train | val | test | dropped == valid            # partition of the valid tiles
    # no-leakage: no training chip shares a pixel with any val/test tile (checked on pixel windows)
    tiles_by_index = {t["index"]: t for t in idx["tiles"]}
    eval_wins = [tiles_by_index[i]["px_window"] for i in (val | test)]

    def overlap(a, b) -> bool:
        ar0, ac0, ah, aw = a; br0, bc0, bh, bw = b
        return not (ar0 + ah <= br0 or br0 + bh <= ar0 or ac0 + aw <= bc0 or bc0 + bw <= ac0)

    assert sp["train_chips"]
    for chip in sp["train_chips"]:
        cw = chip["px_window"]
        for ew in eval_wins:
            assert not overlap(cw, ew), chip["tile_id"]


def test_annotations_geojson_is_valid_with_verbatim_lola_provenance(tiled):
    _man, out = tiled
    fc = _read(out, "annotations.geojson")
    assert fc["type"] == "FeatureCollection"
    assert len(fc["features"]) == 10000
    # provenance echoed verbatim from the bundle metadata -> LOLA Barker/Mazarico, NOT SfS
    prov = fc["provenance"]
    meta = json.load(open(os.path.join(_BUNDLE, "metadata.json"), encoding="utf-8"))
    want = (meta.get("dem_provenance", {}) or {}).get("citation", "")
    assert prov["citation"] == want
    assert "Barker" in prov["citation"] and "Mazarico" in prov["citation"]
    assert "Alexandrov" not in prov["citation"] and "Shape-from-Shading" not in prov["citation"]
    # a feature carries real per-layer stats + a split label + a closed 5-point polygon
    f0 = fc["features"][0]
    assert f0["geometry"]["type"] == "Polygon"
    assert len(f0["geometry"]["coordinates"][0]) == 5
    p = f0["properties"]
    assert p["split"] in ("train", "val", "test", None)
    for layer in ("dem", "slope", "aspect"):
        assert f"{layer}_mean" in p and f"{layer}_std" in p


def test_metadata_only_bundle_refuses(tmp_path):
    # a bundle without heightmap.rf32 cannot be tiled -- explicit refusal, never a fabricated tiling
    d = tmp_path / "meta_only_10km_5m"
    d.mkdir()
    (d / "metadata.json").write_text(json.dumps(
        {"grid": {"width": 2000, "height": 2000, "cell_m": 5.0},
         "world_bounds_m": {"x0": 0.0, "y0": 0.0, "x1": 10000.0, "y1": 10000.0}}))
    with pytest.raises(FileNotFoundError):
        TB.tile_bundle(str(d))
