"""Build every golden fixture from the existing Python implementation over REAL inputs.

    python oracle/build_fixtures.py          # rewrite all fixtures (CI then runs git diff --exit-code)

Fixtures:
  dem_samples  per bundled real DEM: heights at interior cells (read_dem_window), slope from the 3x3
               neighbourhood (slope_deg_map), and the selenographic lat/lon of each cell centre
               (dem_origin_to_latlon, pyproj in the bundle's own polar-stereographic CRS).
"""
from __future__ import annotations

import json
import os

import numpy as np

import export_registries
from fixture_io import REPO, write_fixture
from stewie.terrain import site_dem

ORACLE_FIXTURES = os.path.join(REPO, "crates", "stewie-oracle", "fixtures")
SAMPLES_PER_AXIS = 4


def _bundled_dems() -> list[str]:
    root = os.path.join(REPO, "samples", "lunar_dem")
    return sorted(d for d in os.listdir(root) if os.path.isfile(os.path.join(root, d, "heightmap.rf32")))


def _interior_cells(width: int, height: int) -> list[tuple[int, int]]:
    """Evenly spaced interior cells (never on the border, so the 3x3 slope window is complete)."""
    rows = np.linspace(1, height - 2, SAMPLES_PER_AXIS).round().astype(int)
    cols = np.linspace(1, width - 2, SAMPLES_PER_AXIS).round().astype(int)
    return [(int(r), int(c)) for r in rows for c in cols]


def dem_samples() -> None:
    bundles, sources = [], []
    for name in _bundled_dems():
        bundle_dir = os.path.join(REPO, "samples", "lunar_dem", name)
        meta = json.load(open(os.path.join(bundle_dir, "metadata.json"), encoding="utf-8"))
        g = meta["grid"]
        cells = []
        for r, c in _interior_cells(int(g["width"]), int(g["height"])):
            win, cell_m = site_dem.read_dem_window(r - 1, c - 1, 3, 3, bundle_dir=bundle_dir)
            slope = site_dem.slope_deg_map(win, cell_m)[1, 1]
            lat, lon = site_dem.dem_origin_to_latlon(c * cell_m, r * cell_m, bundle_dir=bundle_dir)
            cells.append({"row": r, "col": c, "height_m": float(win[1, 1]), "slope_deg": float(slope),
                          "lat_deg": lat, "lon_deg": lon})
        bundles.append({"bundle": name, "cell_m": float(g["cell_m"]), "width": int(g["width"]),
                        "height": int(g["height"]), "crs": str(site_dem.bundle_crs(bundle_dir).to_wkt()),
                        "cells": cells})
        sources += [f"samples/lunar_dem/{name}/metadata.json", f"samples/lunar_dem/{name}/heightmap.rf32"]
    write_fixture(ORACLE_FIXTURES, "dem_samples", "oracle/build_fixtures.py::dem_samples "
                  "(stewie.terrain.site_dem read_dem_window, slope_deg_map, dem_origin_to_latlon)",
                  sources, {"samples_per_axis": SAMPLES_PER_AXIS, "bundles": bundles})


def main() -> None:
    export_registries.main()
    dem_samples()


if __name__ == "__main__":
    main()
