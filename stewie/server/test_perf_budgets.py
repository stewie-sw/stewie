"""FS-10: latency budgets. The HTTP middleware records each request's REAL latency per route; the
tracker keeps a bounded recent-sample window, reports p50/p95/max, and flags routes over their declared
budget. /metrics surfaces it and the middleware warns on a real breach.

Percentiles are computed from real recorded latencies -- the unit test feeds known values to the
aggregator (no wall-clock flakiness, no synthetic traffic; the aggregation logic itself is what's under
test). Run: PYTHONPATH=. <venv>/bin/python -m pytest stewie/server/test_perf_budgets.py -q
"""
from __future__ import annotations

import importlib

import pytest


@pytest.fixture()
def svc(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    from stewie.server import services as SVC
    importlib.reload(SVC)
    return SVC


def test_budget_for_returns_route_budget_then_default(svc):
    # a PDF-render route gets a far larger budget than an interactive contract route
    assert svc.budget_for("/plan") > svc.budget_for("/ephemeris")
    assert svc.budget_for("/totally/unknown/route") == svc._DEFAULT_BUDGET_MS


def test_percentiles_from_recorded_latencies(svc):
    for ms in [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]:
        svc.record_latency("/ephemeris", float(ms))
    snap = svc.latency_snapshot()["/ephemeris"]
    assert snap["count"] == 10
    assert 40 <= snap["p50"] <= 60, snap          # median of 10..100
    assert snap["p95"] >= 90, snap
    assert snap["max"] == 100


def test_over_budget_flag_set_only_when_breached(svc):  # [REQ:FS-10]
    b = svc.budget_for("/ephemeris")
    svc.record_latency("/ephemeris", b + 500)     # one clear breach
    snap = svc.latency_snapshot()["/ephemeris"]
    assert snap["over_budget"] is True and snap["budget_ms"] == b

    svc.record_latency("/world", 1.0)             # well under budget
    assert svc.latency_snapshot()["/world"]["over_budget"] is False


def test_sample_window_is_bounded(svc):
    for i in range(svc._LAT_WINDOW * 4):
        svc.record_latency("/world", float(i))
    snap = svc.latency_snapshot()["/world"]
    assert snap["count"] <= svc._LAT_WINDOW, "the latency sample buffer grew unbounded"


def test_metrics_route_returns_a_latency_block(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("STEWIE_DEV_OPEN", "1")
    from fastapi.testclient import TestClient
    import stewie.server.server as SRV
    importlib.reload(SRV)
    c = TestClient(SRV.app)
    c.get("/healthz")                              # generate at least one real request
    m = c.get("/metrics").json()
    assert "latency" in m, "/metrics does not surface the FS-10 latency budgets"
    # the real /healthz request we just made must be tracked with a budget
    assert any("budget_ms" in v for v in m["latency"].values())
