"""splits: leakage-safe spatial-block train/test/val assignment.

The load-bearing generalization gate is NO LEAKAGE: no training chip may share a pixel with any
val or test tile, and val/test tiles are mutually non-overlapping. Training uses an OVERLAPPING
sliding window (stride = tile_m - overlap_m); val/test are NON-overlapping (stride = tile_m); the
blocks are contiguous with a >= 1-tile buffer/gutter (dropped) between them.
"""
from __future__ import annotations

import itertools

from stewie.dataset.dem_source import read_geotiff_geometry
from stewie.dataset.splits import spatial_block_split
from stewie.dataset.tile_grid import TileGrid


def _win(t):
    return (t.px_row0, t.px_col0, t.px_row0 + t.px_h, t.px_col0 + t.px_w)


def _overlap(a, b) -> bool:
    ar0, ac0, ar1, ac1 = _win(a)
    br0, bc0, br1, bc1 = _win(b)
    return not (ar1 <= br0 or br1 <= ar0 or ac1 <= bc0 or bc1 <= ac0)


def _fixture_split(fixture_geometry):
    # tile_m=25 gives an 11x11 grid -> room for 3 contiguous bands + gutters; overlap<tile_m.
    grid = TileGrid(fixture_geometry, tile_m=25.0, sub_m=25.0)
    sp = spatial_block_split(grid, fracs=(0.70, 0.15, 0.15), overlap_m=5.0)
    return grid, sp


def test_partition_covers_all_valid_tiles(fixture_geometry):
    grid, sp = _fixture_split(fixture_geometry)
    valid = {t.index for t in grid.tiles if t.valid_frac >= 1.0}
    train = {t.index for t in sp.train_tiles}
    val = {t.index for t in sp.val_tiles}
    test = {t.index for t in sp.test_tiles}
    dropped = {t.index for t in sp.dropped}
    assert train | val | test | dropped == valid           # partition of the valid tiles
    assert train and val and test                          # all three bands non-empty


def test_splits_are_disjoint(fixture_geometry):
    _grid, sp = _fixture_split(fixture_geometry)
    train = {t.index for t in sp.train_tiles}
    val = {t.index for t in sp.val_tiles}
    test = {t.index for t in sp.test_tiles}
    assert train.isdisjoint(val)
    assert train.isdisjoint(test)
    assert val.isdisjoint(test)


def test_no_leakage_train_chips_vs_val_test(fixture_geometry):
    """THE gate: no training chip shares any pixel with any val or test tile."""
    _grid, sp = _fixture_split(fixture_geometry)
    assert sp.train_chips                                   # chips were produced
    evals = list(sp.val_tiles) + list(sp.test_tiles)
    assert evals
    for chip in sp.train_chips:
        for tile in evals:
            assert not _overlap(chip, tile), (chip.tile_id, tile.tile_id)


def test_val_test_tiles_mutually_nonoverlapping(fixture_geometry):
    _grid, sp = _fixture_split(fixture_geometry)
    evals = list(sp.val_tiles) + list(sp.test_tiles)
    for a, b in itertools.combinations(evals, 2):
        assert not _overlap(a, b)


def test_training_overlaps_but_eval_does_not(fixture_geometry):
    """Overlap is applied to TRAINING only: chip stride < tile_m so adjacent chips overlap; the
    val/test base tiles are stride == tile_m and never overlap each other."""
    _grid, sp = _fixture_split(fixture_geometry)
    assert sp.scheme["stride_m"] == 25.0 - 5.0             # tile_m - overlap_m
    assert sp.scheme["overlap_m"] == 5.0
    # at least one pair of training chips overlaps (proof the sliding window is applied)
    assert any(_overlap(a, b) for a, b in itertools.combinations(sp.train_chips, 2))


def test_buffer_between_blocks_dropped(fixture_geometry):
    _grid, sp = _fixture_split(fixture_geometry)
    assert sp.dropped                                       # gutter tiles exist and are dropped
    assert sp.scheme["buffer_tiles"] >= 1
    # every dropped tile is labeled None (no split)
    for t in sp.dropped:
        assert sp.tile_labels.get(t.index) is None


def test_determinism(fixture_geometry):
    grid = TileGrid(fixture_geometry, tile_m=25.0, sub_m=25.0)
    a = spatial_block_split(grid, fracs=(0.70, 0.15, 0.15), overlap_m=5.0)
    b = spatial_block_split(grid, fracs=(0.70, 0.15, 0.15), overlap_m=5.0)
    assert a.tile_labels == b.tile_labels
    assert [c.tile_id for c in a.train_chips] == [c.tile_id for c in b.train_chips]


def test_overlap_must_be_less_than_tile(fixture_geometry):
    import pytest
    grid = TileGrid(fixture_geometry, tile_m=25.0, sub_m=25.0)
    with pytest.raises(ValueError):
        spatial_block_split(grid, overlap_m=25.0)          # stride would be 0


def test_real_full_dem_no_leakage(real_dem_path):
    """The actual dataset at defaults (tile_m=100, overlap_m=25 -> stride 75): the no-leakage gate."""
    g = read_geotiff_geometry(real_dem_path)
    grid = TileGrid(g, tile_m=100.0, sub_m=25.0)
    sp = spatial_block_split(grid)                          # 70/15/15 defaults
    assert sp.scheme["stride_m"] == 75.0
    valid = {t.index for t in grid.tiles if t.valid_frac >= 1.0}
    train = {t.index for t in sp.train_tiles}
    val = {t.index for t in sp.val_tiles}
    test = {t.index for t in sp.test_tiles}
    dropped = {t.index for t in sp.dropped}
    assert train | val | test | dropped == valid
    assert train.isdisjoint(val) and train.isdisjoint(test) and val.isdisjoint(test)
    evals = list(sp.val_tiles) + list(sp.test_tiles)
    # column-band separation guarantees no chip column-range reaches the eval bands; verify directly
    for chip in sp.train_chips:
        cc0, cc1 = chip.px_col0, chip.px_col0 + chip.px_w
        for tile in evals:
            tc0, tc1 = tile.px_col0, tile.px_col0 + tile.px_w
            assert cc1 <= tc0 or tc1 <= cc0                 # disjoint column ranges -> no shared pixel
