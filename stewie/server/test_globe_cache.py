"""GIS-04 (audit 2026-06-15): the globe disk cache must actually COMMIT, not orphan .part files."""
from stewie.server import gis_layers as GL


def test_globe_disk_cache_commits_not_orphan_part_files(monkeypatch, tmp_path):
    """np.save(stem+'.npy.part', ...) APPENDED '.npy' -> wrote '<stem>.npy.part.npy', so the os.replace of
    the (nonexistent) '<stem>.npy.part' threw and the bare `except OSError` swallowed it -> the disk cache
    NEVER persisted (orphan .npy.part.npy + .json.part left, every globe request recomputed). The cache must
    commit <stem>.npy + <stem>.json, leave no .part orphans, and be re-readable from disk."""
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    GL._GLOBE_CACHE.clear()
    out = GL.render_globe("dem", sun_el=6.0, sun_az=90.0)          # real Haworth hillshade (no synthetic data)
    assert out is not None
    cdir = tmp_path / "globe_cache"
    # REG-01 made the stem site-aware (dem_<site>_<el>_<az>); assert the cache COMMITTED a .npy + matching
    # .json sidecar (stem-agnostic) and left no .part orphans -- the GIS-04 invariant, robust to the stem.
    # stem-agnostic glob: tolerant of the site token AND the render cache-version suffix (..._r2) so a
    # version bump (R-1: native-res drape) doesn't false-fail this GIS-04 commit invariant.
    # F7: the dem drape is SUN-INDEPENDENT (fixed 315/45 hillshade), so its cache stem no longer carries the
    # sun_el/sun_az tokens (`dem_<site>_r2`); glob stem-agnostically on the site token.
    npys = list(cdir.glob("dem_haworth*.npy"))
    assert npys, f"globe cache .npy never committed (GIS-04); dir={list(cdir.iterdir()) if cdir.exists() else 'MISSING'}"
    assert list(cdir.glob("dem_haworth*.json")), "globe cache .json sidecar (commit marker) never committed (GIS-04)"
    assert not list(cdir.glob("*.part*")), f"orphan .part files left behind: {list(cdir.glob('*.part*'))}"
    # with the in-memory cache cleared, a second call must read the committed bytes from DISK
    GL._GLOBE_CACHE.clear()
    out2 = GL.render_globe("dem", sun_el=6.0, sun_az=90.0)
    assert out2[0].shape == out[0].shape


def test_dem_globe_cache_is_sun_independent_single_entry(monkeypatch, tmp_path):
    """F7: a SUN-INDEPENDENT kind (dem hillshade is a fixed 315/45 lambertian, not the real-sun layer) must
    NOT re-render or re-cache per sun angle. Two different (sun_el, sun_az) return the SAME cached object and
    leave exactly ONE _GLOBE_CACHE entry + ONE globe_cache disk file for kind=dem -- so dragging the sun/time
    slider cannot grow memory/disk without bound."""
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    GL._GLOBE_CACHE.clear()
    a = GL.render_globe("dem", sun_el=5.0, sun_az=10.0)     # real Haworth hillshade (no synthetic data)
    b = GL.render_globe("dem", sun_el=40.0, sun_az=200.0)
    assert a is b, "the dem drape must be cached sun-independently (same object for different sun angles)"
    dem_keys = [k for k in GL._GLOBE_CACHE if k[1] == "dem"]
    assert len(dem_keys) == 1, f"expected exactly one dem cache entry, got {dem_keys}"
    cdir = tmp_path / "globe_cache"
    dem_npys = list(cdir.glob("dem_*.npy"))
    assert len(dem_npys) == 1, f"expected exactly one dem globe_cache disk file, got {dem_npys}"


def test_globe_cache_is_bounded_by_a_fifo_cap(monkeypatch, tmp_path):
    """F7: _GLOBE_CACHE must have a FIFO/LRU size cap (like _WORKAREA_CACHE), so a churn of distinct keys
    cannot grow it without bound. Drive many distinct real slope renders (each slope_vmax is its OWN cache
    key via the G5 symbology tuple) past a lowered cap and assert the in-memory cache never exceeds it."""
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    GL._GLOBE_CACHE.clear()
    old = GL._GLOBE_CACHE_MAX
    GL._GLOBE_CACHE_MAX = 4
    try:
        for vmax in range(10, 46, 5):                      # 8 distinct slope_vmax -> 8 distinct real cache keys
            GL.render_globe("slope", site="haworth", slope_vmax=float(vmax), slope_classes=5)
        assert len(GL._GLOBE_CACHE) <= GL._GLOBE_CACHE_MAX, (
            f"_GLOBE_CACHE grew past its cap: {len(GL._GLOBE_CACHE)} > {GL._GLOBE_CACHE_MAX}")
        assert len(GL._GLOBE_CACHE) >= 1, "the cache should retain the most recent entries under the cap"
    finally:
        GL._GLOBE_CACHE_MAX = old
        GL._GLOBE_CACHE.clear()
