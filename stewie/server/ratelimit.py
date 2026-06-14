"""S-07 / S-08: a small, dependency-free, thread-safe fixed-window rate limiter.

Process-local (the deployment runs ONE uvicorn worker -- PRD/A-05), so a per-key counter in memory is
the correct scope here; a multi-worker deployment would move this to a shared store (A-05 follow-up).
Used to bound auth bursts (per-IP and per-account) and per-identity heavy-route quotas without pulling
in slowapi/redis. Fixed-window is intentional: simple, bounded memory, and adequate for abuse control.
"""
from __future__ import annotations

import threading
import time


class RateLimiter:
    """A fixed-window counter keyed by an arbitrary string (IP, account, identity). `max_hits` calls
    are allowed per `window_s`; the (window+1)th returns False (the caller maps that to HTTP 429)."""

    def __init__(self, max_hits: int, window_s: float) -> None:
        self.max_hits = int(max_hits)
        self.window_s = float(window_s)
        self._lock = threading.Lock()
        self._buckets: dict[str, tuple[float, int]] = {}   # key -> (window_start, count)

    def allow(self, key: str, *, now: float | None = None) -> bool:
        """True if this hit is within the window cap (and records it); False if the cap is exceeded."""
        t = now if now is not None else time.monotonic()
        with self._lock:
            start, count = self._buckets.get(key, (t, 0))
            if t - start >= self.window_s:                 # window elapsed -> reset
                start, count = t, 0
            if count >= self.max_hits:
                self._buckets[key] = (start, count)
                return False
            self._buckets[key] = (start, count + 1)
            # opportunistic GC so the dict cannot grow without bound under churned keys
            if len(self._buckets) > 4096:
                self._gc(t)
            return True

    def reset(self, key: str | None = None) -> None:
        with self._lock:
            if key is None:
                self._buckets.clear()
            else:
                self._buckets.pop(key, None)

    def _gc(self, now: float) -> None:
        stale = [k for k, (start, _c) in self._buckets.items() if now - start >= self.window_s]
        for k in stale:
            del self._buckets[k]


def client_ip(request) -> str:
    """The best client IP for rate-limiting. Trust X-Forwarded-For ONLY when STEWIE_TRUST_PROXY=1 (the
    backend is behind the shipped nginx that sets it); otherwise use the direct peer so a client cannot
    spoof its rate-limit key with a forged header."""
    import os
    if os.environ.get("STEWIE_TRUST_PROXY", "") == "1":
        xff = request.headers.get("x-forwarded-for", "")
        if xff:
            return xff.split(",")[0].strip()
    c = getattr(request, "client", None)
    return c.host if c is not None else "-"
