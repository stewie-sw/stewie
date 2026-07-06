"""[REQ:TW-11] the traversal-hardening (traffic.compaction) exposure: the derived spine layer, the
/world/traffic-layer readout, the /layers/raster/traffic.png raster, and the REAL end-to-end fold of a SIM
run's driven path into the persistent per-site TrafficMemory.

No synthetic data: the end-to-end test drives the REAL conserved closed-loop sim (lode.autonomy.
run_closed_loop) over the REAL Haworth DEM and folds its true executed path; the per-wheel load is the real
sourced IPEx static load. If the Haworth DEM bundle is absent the end-to-end test skips loudly.

Run: <venv>/bin/python -m pytest stewie/server/test_traffic_layer_tw11.py -q
"""
import numpy as np
import pytest
from fastapi.testclient import TestClient

from stewie.server.server import app


def _client():
    return TestClient(app, base_url="http://127.0.0.1")


def _png_nontransparent_pixels(png_bytes: bytes) -> int:
    from io import BytesIO

    from PIL import Image
    im = Image.open(BytesIO(png_bytes)).convert("RGBA")
    a = np.asarray(im)[..., 3]
    return int(np.count_nonzero(a > 0))


def test_traffic_compaction_is_a_derived_spine_layer(monkeypatch):
    monkeypatch.setenv("STEWIE_DEV_OPEN", "1")
    j = _client().get("/world/terramechanics-layers").json()
    by = {r["layer"]: r for r in j["derived_layers"]}
    assert "traffic.compaction" in by, "traffic.compaction not served as a derived terramechanics layer"
    row = by["traffic.compaction"]
    assert row["backend"] == "tier2_numpy"
    assert set(row["from_terms"]) == {"contact_pressure", "sinkage"}
    assert row["computed_terms"], "traffic.compaction must carry a real computed solver term"


def test_traffic_compaction_is_in_the_layer_catalog(monkeypatch):
    monkeypatch.setenv("STEWIE_DEV_OPEN", "1")
    j = _client().get("/world/layer-catalog").json()
    ids = {ly["id"] for ly in j["layers"]}
    assert "traffic.compaction" in ids


def test_traffic_layer_readout_empty_then_committed(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_DEV_OPEN", "1")
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    c = _client()
    # nothing folded yet -> committed False
    j = c.get("/world/traffic-layer?site=haworth").json()
    assert j["ok"] and j["committed"] is False
    # fold a REAL driven corridor into the site's TrafficMemory (real sourced wheel load), then re-read
    from stewie.physics import terramechanics as tm
    from stewie.twin import traffic_memory as TW
    from stewie.twin.traffic_memory import TrafficMemory
    mem = TrafficMemory(site="haworth", rows=8, cols=16, cell_m=5.0)
    load = tm.static_wheel_load_n(payload_kg=0.0)
    for k in range(6):                                    # drive the same haul road repeatedly -> it hardens
        mem.apply_path([(3, c_) for c_ in range(16)], load, mission="haul", event_id=f"haul:{k}")
    TW.save_site(str(tmp_path), mem)
    j = c.get("/world/traffic-layer?site=haworth").json()
    assert j["committed"] is True
    s = j["summary"]
    assert s["cells_trafficked"] == 16 and s["max_passes"] == 6
    assert s["peak_relative_density"] > 0.0               # the road hardened
    assert s["peak_bearing_uplift_pa"] > 0.0              # ... into a firmer future pad
    assert j["provenance"]["verified"] is True and j["provenance"]["version"] == 6
    assert j["provenance"]["calibration"]["sigma_c_n"] == "[CALIB]"


def test_traffic_raster_is_transparent_when_empty_then_shows_the_corridor(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_DEV_OPEN", "1")
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    c = _client()
    r0 = c.get("/layers/raster/traffic.png?site=haworth")
    assert r0.status_code == 200 and r0.headers["content-type"] == "image/png"
    assert _png_nontransparent_pixels(r0.content) == 0    # nothing driven yet -> fully transparent (not a 404)
    # fold a real corridor onto the site work-area grid, then the raster must show a NON-blank driven corridor
    from stewie.server.traffic_fold import work_grid_frame
    from stewie.physics import terramechanics as tm
    from stewie.server import state
    from stewie.twin import traffic_memory as TW
    from stewie.twin.traffic_memory import TrafficMemory
    dem, _origin = state.moon_dem("haworth")
    if (dem[0] if isinstance(dem, tuple) else dem) is None:
        pytest.skip("Haworth DEM bundle absent")
    r0f, c0f, rows, cols, cell_m = work_grid_frame(dem)
    mem = TrafficMemory(site="haworth", rows=rows, cols=cols, cell_m=cell_m,
                        origin=(c0f * cell_m, r0f * cell_m))
    load = tm.static_wheel_load_n(payload_kg=0.0)
    for k in range(5):
        mem.apply_path([(rows // 2, cc) for cc in range(10, 40)], load, mission="haul", event_id=f"h:{k}")
    TW.save_site(str(tmp_path), mem)
    r1 = c.get("/layers/raster/traffic.png?site=haworth")
    assert r1.status_code == 200
    assert _png_nontransparent_pixels(r1.content) > 0     # the driven corridor is visibly rendered


def test_end_to_end_real_sim_run_folds_a_driven_corridor(monkeypatch, tmp_path):
    """The REAL wiring: drive the conserved closed-loop sim on the real Haworth DEM, fold its executed path via
    the same traffic_fold bridge the executive uses, and confirm a real per-cell hardened corridor + readout."""
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    from stewie.server import state
    from lode import autonomy as AUT
    from lode import mission_planner as MP
    from stewie.server import traffic_fold as TF
    from stewie.twin import traffic_memory as TW

    dem, origin = state.moon_dem("haworth")
    base = dem[0] if isinstance(dem, tuple) else dem
    if base is None:
        pytest.skip("Haworth DEM bundle absent")
    cell_m = float(dem[1]) if isinstance(dem, tuple) else 5.0
    ax, ay = MP.flattest_anchor((np.asarray(base), cell_m))
    mission = MP.mission_from_dict({"name": "tw11-e2e", "body": "moon",
        "orders": [{"action": "Level A", "kind": "cut", "x": ax + 50, "y": ay + 40,
                    "footprint_m2": 16.0, "depth_m": 0.2},
                   {"action": "Level B", "kind": "cut", "x": ax + 120, "y": ay + 90,
                    "footprint_m2": 16.0, "depth_m": 0.2}],
        "charger": [ax, ay]})
    out = AUT.run_closed_loop(mission, dem=dem, dem_origin=origin)
    mem = TF.traffic_from_run(out, charger=tuple(mission.charger), dem=dem, site="haworth",
                              data_dir=str(tmp_path), mission_id="tw11-e2e")
    assert mem is not None, "the real driven path folded no traffic"
    s = mem.summary()
    assert s["cells_trafficked"] > 0 and s["peak_relative_density"] > 0.0
    # H-09: re-folding the SAME run is idempotent (no new hardening)
    TW.save_site(str(tmp_path), mem)
    mem2 = TF.traffic_from_run(out, charger=tuple(mission.charger), dem=dem, site="haworth",
                               data_dir=str(tmp_path), mission_id="tw11-e2e")
    assert mem2 is None, "re-committing the same SIM run must be idempotent (H-09)"
