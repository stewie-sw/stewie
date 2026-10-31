"""Build every golden fixture from the existing Python implementation over REAL inputs.

    python oracle/build_fixtures.py          # rewrite all fixtures (CI then runs git diff --exit-code)

Fixtures:
  dem_samples        per bundled real DEM: heights at interior cells (read_dem_window), slope from the
                     3x3 neighbourhood (slope_deg_map), and the selenographic lat/lon of each cell centre
                     (dem_origin_to_latlon, pyproj in the bundle's own polar-stereographic CRS).
  ephem_topocentric  10,000 epochs over 2026-2035 at three catalog sites: SPICE str2et (UTC -> TDB) and
                     the apparent (LT+S) Sun and Earth vectors seen from the site (spkcpo, MOON_ME_DE440_ME421).
                     Needs the NAIF kernels (pipeline/fetch_spice.py).
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "pipeline"))  # fetch_spice

import export_registries  # noqa: E402
import fetch_spice  # noqa: E402
from fixture_io import REPO, write_fixture  # noqa: E402
from stewie.specs.sites import SITES  # noqa: E402
from stewie.terrain import site_dem  # noqa: E402

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


EPHEM_SITES = ("haworth", "shackleton_rim", "malapert_massif")
EPHEM_EPOCHS = 10_000


def ephem_topocentric() -> None:
    import spiceypy as sp                              # oracle-only dependency (dev lock)

    kernels = fetch_spice.fetch()
    sp.kclear()
    for path in kernels.values():
        sp.furnsh(path)
    radius_km = sp.bodvrd("MOON", "RADII", 3)[1][0]
    t0, t1 = sp.str2et("2026-01-01T00:00:00"), sp.str2et("2036-01-01T00:00:00")
    rng = np.random.default_rng(20261031)              # epoch sampling only; every value comes from SPICE
    samples = []
    for i, et_guess in enumerate(rng.uniform(t0, t1 - 60.0, EPHEM_EPOCHS)):
        utc = sp.et2utc(float(et_guess), "ISOC", 3) + "Z"
        et = sp.str2et(utc[:-1])
        site = SITES[EPHEM_SITES[i % len(EPHEM_SITES)]]
        lat, lon = np.radians(site.lat_deg), np.radians(site.lon_deg)
        obs = radius_km * np.array([np.cos(lat) * np.cos(lon), np.cos(lat) * np.sin(lon), np.sin(lat)])
        row = {"utc": utc, "tdb": et, "site": site.name}
        for tgt in ("SUN", "EARTH"):
            pos, _lt = sp.spkcpo(tgt, et, "MOON_ME_DE440_ME421", "OBSERVER", "LT+S", obs, "MOON",
                                 "MOON_ME_DE440_ME421")
            row[tgt.lower() + "_m"] = [float(v) * 1000.0 for v in pos[:3]]
        samples.append(row)
    sites = {n: {"lat_deg": SITES[n].lat_deg, "lon_deg": SITES[n].lon_deg} for n in EPHEM_SITES}
    write_fixture(ORACLE_FIXTURES, "ephem_topocentric", "oracle/build_fixtures.py::ephem_topocentric "
                  "(spiceypy str2et, spkcpo LT+S, MOON_ME_DE440_ME421, observer on the sphere h=0)",
                  [f".cache/spice/{n}" for n in sorted(kernels)] + ["crates/stewie-contracts/fixtures/sites.json"],
                  {"moon_radius_km": radius_km, "sites": sites, "samples": samples})


def main() -> None:
    export_registries.main()
    dem_samples()
    ephem_topocentric()


if __name__ == "__main__":
    main()
