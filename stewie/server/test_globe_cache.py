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
    npys = list(cdir.glob("dem_*_6.0_90.0.npy"))
    assert npys, f"globe cache .npy never committed (GIS-04); dir={list(cdir.iterdir()) if cdir.exists() else 'MISSING'}"
    assert list(cdir.glob("dem_*_6.0_90.0.json")), "globe cache .json sidecar (commit marker) never committed (GIS-04)"
    assert not list(cdir.glob("*.part*")), f"orphan .part files left behind: {list(cdir.glob('*.part*'))}"
    # with the in-memory cache cleared, a second call must read the committed bytes from DISK
    GL._GLOBE_CACHE.clear()
    out2 = GL.render_globe("dem", sun_el=6.0, sun_az=90.0)
    assert out2[0].shape == out[0].shape
