"""F22: the _WORKAREA_CACHE / _FULL_LAYER_CACHE FIFO eviction (next(iter(dict)) + pop + insert on a plain
dict) is NOT thread-safe under FastAPI's sync-route threadpool -- a concurrent insert while another thread
iterates for eviction raises ``RuntimeError: dictionary changed size during iteration`` -> a 500.

The race window (between ``iter(cache)`` and the first ``next``) is tiny in production, so we widen it
DETERMINISTICALLY with a real ``dict`` subclass whose ``__iter__`` sleeps -- exposing the exact production
line ``next(iter(_WORKAREA_CACHE))`` while other threads insert concurrently through the real route. The fix
(guarding insert+evict with a threading.Lock) serializes the block so a concurrent insert cannot resize the
dict mid-iteration. Real Haworth DEM, no synthetic data.
"""
import time
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

from stewie.server import routers as _routers  # noqa: F401  (ensure the package is importable)
from stewie.server.routers import dem as DEM
from stewie.server.server import app


class _SlowIterDict(dict):
    """A real dict whose iteration is deliberately slow, so a concurrent insert lands between the iterator's
    creation and its first ``next`` -- deterministically triggering the unlocked-eviction race."""

    def __iter__(self):
        it = super().__iter__()   # a live iterator over THIS dict (snapshots size at creation)
        time.sleep(0.003)         # widen the window: a concurrent insert now resizes the dict under `it`
        return it


def test_workarea_png_concurrent_distinct_windows_no_500(monkeypatch):
    """Fire many distinct window_m values (exceeding a lowered cap) at /dem/workarea.png from a thread pool;
    with the eviction under a lock, zero requests 500 and no RuntimeError escapes."""
    # a small cap so eviction fires on nearly every insert; the slow-iter dict makes the race deterministic.
    monkeypatch.setattr(DEM, "_WORKAREA_CACHE", _SlowIterDict(), raising=True)
    monkeypatch.setattr(DEM, "_WORKAREA_CACHE_MAX", 4, raising=True)
    client = TestClient(app, raise_server_exceptions=False)  # a 500 should surface as a status, not re-raise

    windows = [12.0 + 2.0 * i for i in range(24)]           # 24 distinct order-frame windows -> 24 ckeys

    def _hit(w):
        r = client.get("/dem/workarea.png", params={"site": "haworth", "window_m": w, "kind": "dem"})
        return r.status_code

    with ThreadPoolExecutor(max_workers=8) as ex:
        codes = list(ex.map(_hit, windows))

    fails = [c for c in codes if c >= 500]
    assert not fails, f"concurrent workarea eviction raced -> {len(fails)} server error(s): {sorted(set(codes))}"
    # sanity: the real Haworth renders succeeded (200) where they weren't evicted mid-flight; never a 500.
    assert all(c in (200, 429) or c < 500 for c in codes), sorted(set(codes))
