"""[REQ:FR-02] the perception depth-source selector + health/freshness. /perception/depth-sources exposes the
REAL profile registry (each source's health status) + the selected source; the shared usability rule degrades
Release/Execute on a stale / simulated-when-live / absent source. Real endpoint + committed frontend; no
synthetic data (the health status is exactly what the active profile declares)."""
import os

from fastapi.testclient import TestClient

from stewie.server.server import app

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _f(*p: str) -> str:
    with open(os.path.join(_ROOT, "frontend", "src", *p), encoding="utf-8") as fh:
        return fh.read()


def test_fr02_depth_sources_registry_reports_real_health(monkeypatch):  # [REQ:FR-02]
    monkeypatch.setenv("STEWIE_DEV_OPEN", "1")
    c = TestClient(app, base_url="http://127.0.0.1")
    j = c.get("/perception/depth-sources").json()
    assert j["selected"] == "stereo_front"
    by = {s["name"]: s for s in j["sources"]}
    assert by["stereo_front"]["status"] == "flight"        # the healthy live-capable source
    assert by["stereo_rear"]["status"] == "simulated"      # simulated -> degraded when live is required
    assert by["lidar_front"]["status"] == "absent"         # absent -> unusable


def test_fr02_selector_and_degrade_wired_into_release_execute():  # [REQ:FR-02]
    ds = _f("panes", "DepthSource.tsx")
    assert "/perception/depth-sources" in ds and "ws-depthSource" in ds
    for case in ('"absent"', '"legacy"', '"simulated"', "!fresh", '"live"'):
        assert case in ds, f"the usability rule is missing the {case} case"
    auth = _f("panes", "Authority.tsx")
    assert "depthSourceUsable" in auth and "depth-degraded" in auth   # Release/Execute degrade on a bad source
    ws = _f("workspace.ts")
    assert "depthSource" in ws and '"depthSource"' in ws              # state contract + routeable
