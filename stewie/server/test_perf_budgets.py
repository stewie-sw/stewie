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


# --- FS-10: budget classes BEYOND latency -------------------------------------------------------
_EXPECTED_CLASSES = {"memory", "cpu", "gpu", "bandwidth", "tile_cache", "model_inference"}
_EXPECTED_SUBSYSTEMS = {"map_render", "plan", "fleet_solve", "navigation_estimation", "cockpit_mobile"}


def test_every_resource_class_declares_a_budget_subsystem_and_unit(svc):  # [REQ:FS-10]
    classes = svc.resource_budget_classes()
    assert _EXPECTED_CLASSES <= set(classes), \
        f"FS-10 named classes missing: {_EXPECTED_CLASSES - set(classes)}"
    for cls, b in classes.items():
        assert b["budget"] > 0, f"{cls}: budget not declared (>0)"
        assert b["unit"], f"{cls}: no unit declared"
        assert b["subsystem"], f"{cls}: not mapped to a subsystem"
        assert b["live_source"], f"{cls}: live measurement source not named"
    # the declared classes span the FS-10 subsystems (map render / planning / fleet / nav / mobile)
    subs = {b["subsystem"] for b in classes.values()}
    assert _EXPECTED_SUBSYSTEMS <= subs, f"unmapped FS-10 subsystems: {_EXPECTED_SUBSYSTEMS - subs}"


def test_memory_and_cpu_classes_carry_REAL_process_measurements(svc):  # [REQ:FS-10]
    # no synthetic value: the memory/cpu samples come straight from the OS via resource.getrusage.
    svc.sample_process_resources()
    snap = svc.resource_budget_snapshot()
    mem = snap["memory"]
    assert mem["count"] >= 1 and mem["max"] is not None and mem["max"] > 0, \
        "memory budget did not record a real process RSS sample"
    assert mem["unit"] == "MB" and mem["subsystem"] == "navigation_estimation"
    cpu = snap["cpu"]
    assert cpu["count"] >= 1 and cpu["max"] is not None and cpu["max"] >= 0, \
        "cpu budget did not record a real process CPU-time sample"


def test_over_budget_flag_per_class_from_recorded_samples(svc):  # [REQ:FS-10]
    # feed a recorded measurement above/below each class's declared budget -> the accounting flags it,
    # exactly like the latency aggregator (the aggregation logic is what's under test, per class).
    for cls, b in svc.resource_budget_classes().items():
        svc.record_resource(cls, b["budget"] + 10.0)       # one clear over-budget measurement
        row = svc.resource_budget_snapshot()[cls]
        assert row["over_budget"] is True and row["budget"] == b["budget"], (cls, row)
    # a fresh reload -> an under-budget bandwidth sample is NOT flagged
    importlib.reload(svc)
    svc.record_resource("bandwidth", 1.0)                   # 1 KB, well under the 512 KB budget
    assert svc.resource_budget_snapshot()["bandwidth"]["over_budget"] is False


def test_gated_classes_are_declared_but_name_their_missing_live_source(svc):  # [REQ:FS-10]
    # GPU frame-time + model-inference have no live producer on this host: the budget is DECLARED and the
    # gap is NAMED honestly (no fabricated GPU/model traffic), and the class reports count=0 until fed.
    classes = svc.resource_budget_classes()
    assert "gated" in classes["gpu"]["live_source"].lower()
    assert "gated" in classes["model_inference"]["live_source"].lower()
    snap = svc.resource_budget_snapshot()
    assert snap["gpu"]["count"] == 0 and snap["gpu"]["over_budget"] is False


def test_metrics_route_surfaces_the_budgets_block(monkeypatch, tmp_path):  # [REQ:FS-10]
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("STEWIE_DEV_OPEN", "1")
    from fastapi.testclient import TestClient
    import stewie.server.server as SRV
    importlib.reload(SRV)
    c = TestClient(SRV.app)
    m = c.get("/metrics").json()
    assert "budgets" in m, "/metrics does not surface the FS-10 resource budgets"
    assert _EXPECTED_CLASSES <= set(m["budgets"]), "budgets block missing FS-10 classes"
    # the /metrics read triggered a real process-resource sample -> memory is populated from live RSS
    assert m["budgets"]["memory"]["count"] >= 1 and m["budgets"]["memory"]["max"] > 0


def test_tile_cache_class_has_a_real_live_producer_not_a_declared_but_unfed_source(monkeypatch, tmp_path):  # [REQ:FS-10]
    # tile_cache is the map_render budget class, and its live_source names map_layers -- so, unlike the
    # honestly-GATED gpu/model_inference classes, that claim must be BACKED by a real producer. The
    # /dem/workarea.png tile route renders a REAL PNG of the bundled Haworth LOLA DEM at native resolution;
    # serving it records the tile's byte size (KB) into the tile_cache budget. Read back through /metrics so
    # this exercises the same services singleton the router feeds (no module-identity split, no injection).
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("STEWIE_DEV_OPEN", "1")
    from fastapi.testclient import TestClient
    import stewie.server.server as SRV
    importlib.reload(SRV)
    c = TestClient(SRV.app)
    # the class must NOT masquerade as gated -- it claims a live source, so it must have one
    assert "gated" not in c.get("/metrics").json()["budgets"]["tile_cache"]["live_source"].lower()
    r = c.get("/dem/workarea.png?site=haworth&window_m=320&kind=dem")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png", r.status_code
    tc = c.get("/metrics").json()["budgets"]["tile_cache"]
    assert tc["count"] >= 1 and tc["max"] is not None and tc["max"] > 0, \
        "tile_cache budget did not record a real rendered-tile byte sample from /dem/workarea.png"
    assert tc["subsystem"] == "map_render" and tc["unit"] == "KB_per_tile"
