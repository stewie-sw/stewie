"""Leakage-safe spatial-block train/test/val split.

A random tile split leaks through spatial autocorrelation (neighbouring tiles are near-duplicates), so
the assignment is SPATIAL BLOCKS: contiguous bands along one axis, with a buffer/gutter of dropped
tiles between them so no split is spatially adjacent to another. On top of that:

  * TRAINING uses an OVERLAPPING sliding window -- chips of side ``tile_m`` at stride
    ``tile_m - overlap_m`` (more, overlapping samples). Overlap is applied to TRAINING ONLY.
  * VAL and TEST are the NON-overlapping base tiles (stride ``tile_m``), so each evaluation location
    is counted exactly once.
  * The buffer between blocks is ``>= max(overlap_m, tile_m)`` (default one full tile), and, because
    training chips are constrained to lie fully inside the train band, NO training chip can share a
    pixel with -- or sit within the buffer of -- any val/test tile. That no-leakage property is the
    load-bearing generalization gate (see ``tests/test_splits.py``).

Deterministic: the banding is a pure function of the grid dimensions + fractions (no randomness).
Default 70/15/15. ``min_valid_frac`` (default 1.0) keeps partial edge tiles out of every split.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from stewie.dataset.tile_grid import Tile, TileGrid, TileSpec, build_tiles


@dataclass(frozen=True)
class SplitResult:
    tile_labels: dict[int, str | None]     # valid-tile index -> 'train' | 'val' | 'test' | None (buffer)
    train_tiles: list[Tile]                # base grid tiles in the train band
    val_tiles: list[Tile]                  # NON-overlapping eval tiles
    test_tiles: list[Tile]
    dropped: list[Tile]                    # buffer/gutter valid tiles (label None)
    train_chips: list[Tile]                # OVERLAPPING sliding-window training chips
    scheme: dict = field(default_factory=dict)

    def split_of(self, index: int) -> str | None:
        return self.tile_labels.get(index)


def spatial_block_split(grid: TileGrid, *, fracs: tuple[float, float, float] = (0.70, 0.15, 0.15),
                        axis: str = "col", buffer_tiles: int | None = None,
                        overlap_m: float = 25.0, min_valid_frac: float = 1.0) -> SplitResult:
    """Assign ``grid``'s valid tiles to contiguous, buffered train/val/test bands + build train chips.

    ``axis``: band along ``"col"`` (default) or ``"row"``. ``overlap_m`` must be ``< tile_m``
    (else the training stride is <= 0). ``buffer_tiles`` defaults to ``ceil(max(overlap_m, tile_m) /
    tile_m)`` == 1 -- one full-tile gutter, which satisfies the ``>= max(overlap_m, tile_m)`` buffer.
    """
    if axis not in ("col", "row"):
        raise ValueError(f"axis must be 'col' or 'row', got {axis!r}")
    if abs(sum(fracs) - 1.0) > 1e-6:
        raise ValueError(f"fracs must sum to 1.0, got {fracs} (sum {sum(fracs)})")
    tile_m = grid.tile_m
    if not (0.0 <= overlap_m < tile_m):
        raise ValueError(f"overlap_m ({overlap_m}) must be in [0, tile_m={tile_m}) -- stride must be > 0")
    stride_m = tile_m - overlap_m
    buffer_m = max(overlap_m, tile_m)
    if buffer_tiles is None:
        buffer_tiles = max(1, int(math.ceil(buffer_m / tile_m)))
    if buffer_tiles < 1:
        raise ValueError(f"buffer_tiles ({buffer_tiles}) must be >= 1")

    n = grid.n_cols if axis == "col" else grid.n_rows
    usable = n - 2 * buffer_tiles
    if usable < 3:
        raise ValueError(
            f"too few {axis} bands: n={n}, buffer_tiles={buffer_tiles} -> usable={usable} < 3; "
            "use a smaller tile_m, a bigger DEM, or fewer buffer tiles")
    train_n = int(round(fracs[0] * usable))
    val_n = int(round(fracs[1] * usable))
    train_n = max(1, min(train_n, usable - 2))          # keep val + test >= 1 each
    val_n = max(1, min(val_n, usable - train_n - 1))

    tr_end = train_n
    val_start = tr_end + buffer_tiles
    val_end = val_start + val_n
    test_start = val_end + buffer_tiles

    def _label(k: int) -> str | None:
        if k < tr_end:
            return "train"
        if k < val_start:
            return None                                 # gutter 1
        if k < val_end:
            return "val"
        if k < test_start:
            return None                                 # gutter 2
        return "test"                                   # test absorbs the remainder

    def _key(t: Tile) -> int:
        return t.col if axis == "col" else t.row

    valid = [t for t in grid.tiles if t.valid_frac >= min_valid_frac]
    tile_labels: dict[int, str | None] = {}
    train_tiles: list[Tile] = []
    val_tiles: list[Tile] = []
    test_tiles: list[Tile] = []
    dropped: list[Tile] = []
    for t in valid:
        lab = _label(_key(t))
        tile_labels[t.index] = lab
        if lab == "train":
            train_tiles.append(t)
        elif lab == "val":
            val_tiles.append(t)
        elif lab == "test":
            test_tiles.append(t)
        else:
            dropped.append(t)

    train_chips = _build_train_chips(grid, train_tiles, tile_m=tile_m, stride_m=stride_m)

    scheme = {
        "axis": axis, "fracs": list(fracs), "buffer_tiles": buffer_tiles, "buffer_m": buffer_m,
        "overlap_m": overlap_m, "tile_m": tile_m, "stride_m": stride_m, "min_valid_frac": min_valid_frac,
        "bands": {"train": [0, tr_end], "val": [val_start, val_end], "test": [test_start, n]},
        "gutters": [[tr_end, val_start], [val_end, test_start]],
        "n_train_tiles": len(train_tiles), "n_val_tiles": len(val_tiles),
        "n_test_tiles": len(test_tiles), "n_dropped": len(dropped), "n_train_chips": len(train_chips),
    }
    return SplitResult(tile_labels=tile_labels, train_tiles=train_tiles, val_tiles=val_tiles,
                       test_tiles=test_tiles, dropped=dropped, train_chips=train_chips, scheme=scheme)


def _build_train_chips(grid: TileGrid, train_tiles: list[Tile], *, tile_m: float,
                       stride_m: float) -> list[Tile]:
    """Overlapping ``tile_m`` chips at ``stride_m`` over the train band, each fully inside the band.

    Constraining every chip to lie inside the bounding box of the (full) train tiles is what makes
    the no-leakage guarantee hold: the band stops one buffer-tile short of the val band, so a chip
    (side ``tile_m``) can never reach a val/test tile."""
    if not train_tiles:
        return []
    g = grid.geometry
    x_lo = min(t.x0 for t in train_tiles)
    x_hi = max(t.x1 for t in train_tiles)
    y_lo = min(t.y0 for t in train_tiles)
    y_hi = max(t.y1 for t in train_tiles)
    eps = 1e-6

    x_starts: list[float] = []
    x = x_lo
    while x + tile_m <= x_hi + eps:
        x_starts.append(x)
        x += stride_m
    y_tops: list[float] = []
    yt = y_hi
    while yt - tile_m >= y_lo - eps:
        y_tops.append(yt)
        yt -= stride_m

    specs: list[TileSpec] = []
    idx = 0
    for yt in y_tops:
        y0, y1 = yt - tile_m, yt
        prow = int(round((g.y_max - y1) / g.cell_m))
        for xs in x_starts:
            x0, x1 = xs, xs + tile_m
            pcol = int(round((x0 - g.x_min) / g.cell_m))
            specs.append(TileSpec(index=idx, row=prow, col=pcol,
                                  tile_id=f"chip_r{prow:05d}c{pcol:05d}", x0=x0, y0=y0, x1=x1, y1=y1))
            idx += 1
    return build_tiles(g, specs, tile_m=tile_m, sub_m=grid.sub_m, kind="chip", split="train")
