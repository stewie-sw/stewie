"""Shared fixtures for the stewie.dataset tests.

Real data only. The tiny committed GeoTIFF fixture is a REAL subsampled window of the LOLA Haworth
1 m DEM (see ``fixtures/haworth_1m_fixture_256.provenance.json`` + ``_make_fixture.py``); the full
11660x12060 DEM is not bundled, so the ``real_dem_path`` fixture skips when it is absent.
"""
from __future__ import annotations

import os

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE_TIF = os.path.join(_HERE, "fixtures", "haworth_1m_fixture_256.tif")


@pytest.fixture(scope="session")
def fixture_tif() -> str:
    if not os.path.exists(FIXTURE_TIF):
        pytest.skip(f"real-DEM fixture missing: {FIXTURE_TIF} (regen: python -m stewie.dataset.tests._make_fixture)")
    return FIXTURE_TIF


@pytest.fixture()
def fixture_geometry(fixture_tif):
    from stewie.dataset.dem_source import read_geotiff_geometry
    return read_geotiff_geometry(fixture_tif)


@pytest.fixture()
def fixture_reader(fixture_tif):
    from stewie.dataset.dem_source import GeoTiffWindowReader
    return GeoTiffWindowReader(fixture_tif)


@pytest.fixture(scope="session")
def real_dem_path() -> str:
    from stewie.dataset.dem_source import resolve_dem_path
    p = resolve_dem_path()
    if p is None:
        pytest.skip("real Haworth 1 m DEM (Lunar_LROnac_Haworth_sfs-dem_1m_v3.tif) not present on this host")
    return p
