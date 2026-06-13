"""server.py route coverage -- the FastAPI app driven through Starlette's TestClient (real ASGI).

Covers every route + the {ok:false,error} envelope + status codes the browser contract depends on, plus
the production-hardening surface (PRD N7/N8): Pydantic input limits, API-key auth on mutating routes,
CORS, reports TTL, /healthz, /metrics. The app is the REAL one (grounded mission_planner, no synthetic
constants). Run: PYTHONPATH=. <venv>/bin/python -m pytest planet_browser/test_server.py -q
"""
from __future__ import annotations

import os
import time

import pytest
from fastapi.testclient import TestClient

from stewie.server import server as SRV


@pytest.fixture()
def client():
    return TestClient(SRV.app)


# ---- GET static + content types ------------------------------------------------------------------
def test_get_index_root_and_alias(client):
    for route in ("/", "/index.html"):
        r = client.get(route)
        assert r.status_code == 200 and b"<" in r.content[:2048]      # real HTML
        assert "text/html" in r.headers["content-type"]


def test_get_bodies_json_is_real_json(client):
    r = client.get("/bodies.json")
    assert r.status_code == 200 and "application/json" in r.headers["content-type"]
    d = r.json()
    assert "moon" in d and "_ipex" in d                              # the py-generated bodies + ipex mirror


def test_get_unknown_route_404(client):
    r = client.get("/does-not-exist")
    assert r.status_code == 404 and r.json()["ok"] is False and "no route" in r.json()["error"]


def test_get_missing_report_404(client):
    r = client.get("/reports/nonesuch-deadbeef.pdf")
    assert r.status_code == 404 and r.json()["ok"] is False and "not found" in r.json()["error"]


# ---- GET /dem/ : the real committed Haworth preview PNGs -----------------------------------------
def test_get_dem_hillshade_png(client):
    r = client.get("/dem/hillshade.png")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"                     # a real PNG signature


def test_get_dem_height_png(client):
    r = client.get("/dem/height.png")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png" and r.content[:4] == b"\x89PNG"


def test_get_dem_unknown_404(client):
    r = client.get("/dem/bogus.png")
    assert r.status_code == 404 and "no dem" in r.json()["error"]


# ---- a generated report is actually served back from /reports/ ----------------------------------
def test_report_pdf_round_trips_through_reports_route(client):
    payload = {"name": "Served Site", "body": "moon", "charger": [0, 0], "orders": [
        {"action": "cut", "kind": "cut", "x": 40, "y": 30, "footprint_m2": 36, "depth_m": 0.04},
        {"action": "fill", "kind": "fill", "x": 44, "y": 44, "footprint_m2": 14, "depth_m": 0.10}]}
    r = client.post("/plan", json=payload)
    assert r.status_code == 200 and r.json()["pdf"].startswith("/reports/")
    pr = client.get(r.json()["pdf"])
    assert pr.status_code == 200 and pr.content[:5] == b"%PDF-" and pr.headers["content-type"] == "application/pdf"
    mr = client.get(r.json()["md"])
    assert mr.status_code == 200 and "text/markdown" in mr.headers["content-type"] and len(mr.content) > 0


# ---- POST error paths ---------------------------------------------------------------------------
def test_post_unknown_route_404(client):
    r = client.post("/nope", json={})
    assert r.status_code == 404 and r.json()["ok"] is False and "no route" in r.json()["error"]


def test_post_bad_json_400(client):
    r = client.post("/plan", content=b"{not valid json", headers={"content-type": "application/json"})
    assert r.status_code == 400 and r.json()["ok"] is False and "bad JSON" in r.json()["error"]


def test_plan_sinter_order_gated_off_400(client):
    r = client.post("/plan", json={"name": "S", "body": "moon", "charger": [0, 0], "orders": [
        {"action": "Sinter apron", "kind": "sinter", "x": 10, "y": 10, "footprint_m2": 9, "depth_m": 0.01}]})
    assert r.status_code == 400 and r.json()["ok"] is False and "GATED OFF" in r.json()["error"]


def test_plan_unknown_body_400(client):
    r = client.post("/plan", json={"name": "P", "body": "pluto", "charger": [0, 0], "orders": [
        {"action": "cut", "kind": "cut", "x": 1, "y": 1, "footprint_m2": 9, "depth_m": 0.02}]})
    assert r.status_code == 400 and "body" in r.json()["error"]


def test_plan_too_many_orders_rejected(client):
    # N8 input limit: a queue beyond _MAX_ORDERS is refused at the contract, before the planner runs.
    big = [{"action": "cut", "kind": "cut", "x": 0, "y": 0, "footprint_m2": 1, "depth_m": 0.01}] * (SRV._MAX_ORDERS + 1)
    r = client.post("/plan", json={"name": "huge", "body": "moon", "charger": [0, 0], "orders": big})
    assert r.status_code == 400 and r.json()["ok"] is False


# ---- /sense (drum-fill sensing) error + success -------------------------------------------------
def test_sense_missing_true_mass_400(client):
    r = client.post("/sense", json={"capacity_kg": 30.0})
    assert r.status_code == 400 and "true_mass_kg" in r.json()["error"]


def test_sense_success_inferred_and_offload(client):
    r = client.post("/sense", json={"true_mass_kg": 12.0})
    body = r.json()
    assert r.status_code == 200 and body["ok"] is True
    assert abs(body["inferred_kg"] - 12.0) < 1.0                     # faithful inference, noise off
    assert body["offload"] is False and body["current_a"] > 0.0
    assert body["lower_kg"] <= body["inferred_kg"] <= body["upper_kg"]


# ---- /compare + /structure error paths ----------------------------------------------------------
def test_compare_unknown_body_400(client):
    r = client.post("/compare", json={"name": "c", "body": "pluto", "charger": [0, 0], "orders": [
        {"action": "cut", "kind": "cut", "x": 1, "y": 1, "footprint_m2": 9, "depth_m": 0.02}]})
    assert r.status_code == 400 and r.json()["ok"] is False


def test_structure_non_numeric_xy_400(client):
    r = client.post("/structure", json={"name": "landing_pad", "x": "oops", "y": 0})
    assert r.status_code == 400 and r.json()["ok"] is False and "x" in r.json()["error"]


def test_structure_unknown_name_400(client):
    r = client.post("/structure", json={"name": "death_star", "x": 0, "y": 0})
    assert r.status_code == 400 and r.json()["ok"] is False and "death_star" in r.json()["error"]


def test_structure_landing_pad_success(client):
    r = client.post("/structure", json={"name": "landing_pad", "x": 10, "y": 10})
    body = r.json()
    assert r.status_code == 200 and body["ok"] is True and body["name"] == "landing_pad"
    assert isinstance(body["orders"], list) and len(body["orders"]) >= 1


# ---- /render : 503 when the Godot pipeline is absent, 400 on bad params --------------------------
def test_render_503_when_pipeline_absent(client, monkeypatch):
    monkeypatch.setattr(SRV, "PRP", None)                           # real degrade path, not a stub of logic
    r = client.post("/render", json={"u": 0.5, "v": 0.5})
    assert r.status_code == 503 and r.json()["ok"] is False and "render pipeline unavailable" in r.json()["error"]


def test_render_bad_params_400(client):
    # Pydantic rejects a non-numeric / out-of-range param at the contract (400) before any Godot work.
    r = client.post("/render", json={"u": "not-a-float", "v": 0.5})
    assert r.status_code == 400 and r.json()["ok"] is False
    r2 = client.post("/render", json={"u": 5.0, "v": 0.5})          # out of [0,1]
    assert r2.status_code == 400 and r2.json()["ok"] is False


# ---- production-hardening surface (PRD N7/N8) ----------------------------------------------------
def test_healthz(client):
    r = client.get("/healthz")
    body = r.json()
    assert r.status_code == 200 and body["status"] == "ok" and "version" in body and body["uptime_s"] >= 0.0


def test_metrics_counts_requests(client):
    client.get("/healthz")
    r = client.get("/metrics")
    body = r.json()
    assert r.status_code == 200 and body["requests_total"] >= 1 and "by_status" in body and "by_route" in body


def test_cors_header_present(client):
    r = client.get("/healthz", headers={"origin": "http://example.com"})
    assert r.status_code == 200 and "access-control-allow-origin" in {k.lower() for k in r.headers}


def test_auth_enforced_only_when_key_set(client, monkeypatch):
    # open by default
    assert client.post("/sense", json={"true_mass_kg": 5.0}).status_code == 200
    # with a key set, mutating routes require it
    monkeypatch.setenv("DUSTGYM_API_KEY", "s3cret")
    assert client.post("/sense", json={"true_mass_kg": 5.0}).status_code == 401
    ok = client.post("/sense", json={"true_mass_kg": 5.0}, headers={"X-API-Key": "s3cret"})
    assert ok.status_code == 200 and ok.json()["ok"] is True
    bearer = client.post("/sense", json={"true_mass_kg": 5.0}, headers={"Authorization": "Bearer s3cret"})
    assert bearer.status_code == 200


def test_prune_reports_removes_old_files(tmp_path, monkeypatch):
    monkeypatch.setattr(SRV, "REPORTS", str(tmp_path))
    old = tmp_path / "stale-report.pdf"
    old.write_bytes(b"%PDF-old")
    os.utime(old, (time.time() - 7200, time.time() - 7200))         # 2 h old
    fresh = tmp_path / "fresh-report.pdf"
    fresh.write_bytes(b"%PDF-new")
    removed = SRV._prune_reports(ttl_s=3600)                        # 1 h TTL
    assert removed == 1 and not old.exists() and fresh.exists()


# ---- POST /localize : P1.1 -- the ARGUS articulation-parallax fix, wired into the estimator -------
def test_localize_recovers_known_position_with_covariance(client):
    """[REQ:PM-06] /localize ties articulation_localize into a live PoseGraphSE2: from the shadow-tip
    PIXEL shifts under a commanded lift dh it triangulates ranges, fixes (x,y) heading-free, injects an
    ABSOLUTE factor, and returns the re-optimized fix + geometry-derived 1-sigma (the missing endpoint
    that makes the estimator reachable from the live system)."""
    import math

    from dart import articulated_parallax as AP
    landmarks = [(6.0, 0.0), (0.0, 8.0), (-5.0, -5.0)]     # three known shadow-tip landmarks
    dh_m, fx_px = 0.174, 679.57                            # real IPEx lift + IMX547/6 mm focal length
    ranges = [math.hypot(x, y) for x, y in landmarks]      # rover truly at the origin
    shifts = [AP.pixel_shift_for_range(dh_m, r, fx_px) for r in ranges]  # exact parallax pixel shifts
    r = client.post("/localize", json={
        "landmarks_xy": landmarks, "pixel_shifts": shifts, "dh_m": dh_m, "fx_px": fx_px,
        "prior_xy": [1.5, -1.0], "prior_sigma_xy": 50.0,   # a deliberately wrong, WEAK prior
    })
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["ok"] is True
    fix = b["fix_xy"]
    assert math.hypot(fix[0], fix[1]) < 0.05               # recovers the origin to < 5 cm
    assert b["fix_sigma_m"] > 0.0                          # covariance is geometry-derived, not zero
    assert b["xy_sigma"]["0"] < 50.0                       # the absolute fix tightened the weak prior


def test_localize_rejects_too_few_landmarks(client):
    """[REQ:PM-06] a heading-free fix needs >= 2 landmarks; one is a clean 400, not a crash."""
    r = client.post("/localize", json={
        "landmarks_xy": [[6.0, 0.0]], "pixel_shifts": [50.0], "dh_m": 0.174, "fx_px": 679.57})
    assert r.status_code == 400 and r.json()["ok"] is False


def test_localize_forbids_truth_fields(client):
    """[REQ:PM-06] I3: the estimator surface is observation-only -- a truth pose in the body is rejected
    by the typed contract (extra='forbid'), never silently consumed."""
    r = client.post("/localize", json={
        "landmarks_xy": [[6.0, 0.0], [0.0, 8.0]], "pixel_shifts": [20.0, 15.0],
        "dh_m": 0.174, "fx_px": 679.57, "true_pose_xy": [0.0, 0.0]})
    assert r.status_code == 400 and r.json()["ok"] is False    # rejected by the typed contract (app maps 422->400)
    assert "true_pose_xy" in r.json()["error"]                 # the forbidden field is named, never consumed


# ---- POST /slam : P1.2 -- the integrated multi-factor SLAM run, exposed over a real segment --------
_KATWIJK = os.environ.get("STEWIE_KATWIJK_DIR", "/mnt/projects/datasets/katwijk")


@pytest.mark.skipif(not os.path.isdir(os.path.join(_KATWIJK, "Part1")),
                    reason="raw Katwijk dataset not on this host (ESA license + size, not bundled)")
def test_slam_fuses_real_katwijk_and_bounds_drift(client, monkeypatch):
    """[REQ:PM-06] /slam runs the integrated SLAM over a REAL Katwijk segment and returns trajectory +
    ATE + leave-one-out; the fused absolute drift is far below the odometry-only baseline."""
    monkeypatch.setenv("STEWIE_KATWIJK_DIR", _KATWIJK)
    SRV._KATWIJK_CACHE.clear()
    r = client.post("/slam", json={"segment": "Part1", "n_keyframes": 20})
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["ok"] is True
    assert b["abs_max_err_m"] < b["baseline_abs_max_err_m"]     # fusion beats odometry-only drift
    assert len(b["trajectory_xy"]) == 20 and len(b["trajectory_xy"][0]) == 2
    assert set(b["leave_one_out"]) == {"imu", "shadow", "parallax", "dem"}


def test_slam_503_when_dataset_absent(client, monkeypatch):
    """[REQ:PM-06] no machine paths in source -- with no dataset configured, /slam answers a clean 503,
    it never fabricates a trajectory."""
    monkeypatch.delenv("STEWIE_KATWIJK_DIR", raising=False)
    monkeypatch.delenv("DUSTGYM_KATWIJK_DIR", raising=False)
    SRV._KATWIJK_CACHE.clear()
    r = client.post("/slam", json={"segment": "Part1"})
    assert r.status_code == 503 and r.json()["ok"] is False


def test_slam_rejects_bad_segment(client):
    """[REQ:PM-06] the segment is pattern-validated -> no path traversal into the dataset root."""
    r = client.post("/slam", json={"segment": "../../etc"})
    assert r.status_code == 400 and r.json()["ok"] is False
