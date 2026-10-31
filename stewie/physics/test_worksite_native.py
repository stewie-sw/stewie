"""Native Haworth behavioral checks, using measured SfS heights and the bundle's [CALIB] mantle.

No generated terrain, procedural features, or replacement implementations are used.
"""
from pathlib import Path
import sys

import numpy as np
import pytest

from stewie.physics.worksite import WorkSite
from stewie.terrain.dem_io import BASE_FIELD_NAMES
from stewie.terrain.tiles_mosaic import TileMosaic


BUNDLE = Path(__file__).resolve().parents[2] / "samples/lunar_dem/haworth_sfs_2km_1m"


@pytest.fixture(autouse=True)
def no_procedural_calls():
    """Observe real calls without replacing any terrain implementation."""
    forbidden = []
    previous = sys.getprofile()

    def observe(frame, event, arg):
        if event == "call":
            module = frame.f_globals.get("__name__", "")
            if module in {"stewie.terrain.dem_overlay", "stewie.terrain.procgen_seed"}:
                forbidden.append((module, frame.f_code.co_name))
            if frame.f_code is WorkSite._bilinear_datum_block.__code__:
                forbidden.append((module, frame.f_code.co_name))

    sys.setprofile(observe)
    try:
        yield
    finally:
        sys.setprofile(previous)
    assert not forbidden, f"native terrain called procedural or smoothing code: {forbidden}"


@pytest.fixture(scope="module")
def loaded():
    # Missing measured input is a failed prerequisite, not a passing or skipped acceptance check.
    assert BUNDLE.is_dir(), f"required measured bundle absent: {BUNDLE}"
    return WorkSite.from_haworth_bundle(str(BUNDLE), fine_cell_m=None, tile_base_cells=7)


def site_from(loaded, **kwargs):
    return WorkSite(
        loaded.base, world_x0=loaded.world_x0, world_y0=loaded.world_y0,
        fine_cell_m=loaded.base.cell_m, tile_base_cells=7,
        datum_verified=loaded.datum_verified, **kwargs,
    )


def assert_native_window(site):
    r0, c0, r1, c1 = site.window_region_rc
    expected = site.reader.window((r0, c0, r1, c1))
    for name in BASE_FIELD_NAMES:
        actual = getattr(site.fine, name)
        assert np.array_equal(actual, expected[name]), name
        assert not np.shares_memory(actual, getattr(site.base, name)), name
    saved = np.memmap(
        BUNDLE / "heightmap.rf32", mode="r", dtype="<f4",
        shape=(site.base.height, site.base.width),
    )
    assert np.array_equal(site.fine.derive_height(), saved[r0:r1, c0:c1])


def test_factory_selects_native_and_preserves_single_window(loaded):
    assert loaded.k == 1
    assert loaded.fine_cell_m == loaded.base.cell_m == 1.0
    assert loaded.datum_verified
    assert loaded.smooth_datum is False
    site = site_from(loaded, smooth_datum=True)
    site.open_window((1001, 1001), radius_m=1.0)
    assert_native_window(site)
    assert site.conservation_residual() < 1e-8


def test_native_streaming_keeps_measured_edges_and_virgin_heights(loaded):
    site = site_from(loaded)
    for rc in ((1001, 1001), (0, 0), (1999, 1999), (1001, 1001)):
        assert site.recenter(site.base_rc_to_xy(rc))
        assert_native_window(site)
        assert np.array_equal(site.window_virgin_height(), site.fine.derive_height())
        assert not np.any(site.diff_field())
        assert site.conservation_residual() < 1e-8


def test_native_cut_dump_survive_recenter_with_conservation(loaded):
    site = site_from(loaded)
    home = site.base_rc_to_xy((1001, 1001))
    away = site.base_rc_to_xy((1050, 1050))
    site.recenter(home)
    virgin = site.window_virgin_height().copy()
    cut = np.zeros_like(virgin, dtype=bool)
    cut[10, 10] = True
    moved = site.flatten(cut, float(virgin[10, 10] - 0.01))
    assert moved > 0.0
    assert site.diff_field()[10, 10] < 0.0
    worked = {name: getattr(site.fine, name).copy() for name in BASE_FIELD_NAMES}
    assert site.conservation_residual() < 1e-8
    site.recenter(away)
    dump = np.zeros((site.fine.height, site.fine.width), dtype=bool)
    dump[10, 10] = True
    placed = site.dump(dump)
    assert placed == moved
    assert site.inventory_kg == 0.0
    assert site.diff_field()[10, 10] > 0.0
    dumped = {name: getattr(site.fine, name).copy() for name in BASE_FIELD_NAMES}
    assert site.conservation_residual() < 1e-8
    site.recenter(home)
    for name in BASE_FIELD_NAMES:
        assert np.array_equal(getattr(site.fine, name), worked[name]), name
    assert np.array_equal(site.window_virgin_height(), virgin)
    assert site.conservation_residual() < 1e-8
    site.recenter(away)
    for name in BASE_FIELD_NAMES:
        assert np.array_equal(getattr(site.fine, name), dumped[name]), name
    assert site.conservation_residual() < 1e-8
    base_fields = site.reader.window((994, 994, 1015, 1015))
    base_height = base_fields["datum"] + base_fields["mass_areal"] / base_fields["density"]
    assert np.array_equal(base_height, virgin)


def test_native_pages_are_lossless_and_separate_from_refined_pages(loaded, tmp_path):
    site = site_from(loaded, page_dir=str(tmp_path))
    mosaic = site.mosaic
    xy = site.base_rc_to_xy((1001, 1001))
    first = mosaic.ensure_fine(xy, radius_m=0.0)[0]
    expected = {name: getattr(first.cs, name).copy() for name in BASE_FIELD_NAMES}
    key = mosaic.resident_keys[0]
    generation_count = mosaic.generation_count
    mosaic.evict((0, 0, 1, 1))
    assert mosaic.resident_count == 0
    page = Path(mosaic._page_path(*key))
    assert (page / "fields.npz").is_file()
    # Old overlay pages used this name even when their requested cell size equaled the base.
    legacy = tmp_path / f"tile_s0_c1_t7_{key[0]}_{key[1]}"
    assert page != legacy
    refined = TileMosaic(site.reader, 1.0, 0.5, tile_base_cells=7, page_dir=str(tmp_path))
    assert refined._page_path(*key) != str(page)
    assert refined._load_paged(*key) is None
    # Constructing the refined namespace does not generate or execute finer terrain.
    reopened = TileMosaic(site.reader, 1.0, 1.0, tile_base_cells=7, page_dir=str(tmp_path))
    restored = reopened.ensure_fine(xy, radius_m=0.0)[0]
    assert reopened.generation_count == 0
    assert mosaic.generation_count == generation_count
    for name in BASE_FIELD_NAMES:
        actual = getattr(restored.cs, name)
        assert np.array_equal(actual, expected[name]), name
        assert actual.dtype == expected[name].dtype, name
    assert np.array_equal(restored.cs.derive_height(), first.cs.derive_height())
