"""[REQ:TM-04] the rehearsal/report compares predicted vs observed terramechanics from the REAL run legs,
honestly: energy has a genuine predicted (nominal model) vs observed (slip-truth) gap with a residual; slip is
reported observed-only (the SIM legs carry no separate nominal-slip prediction); sinkage is marked not-
telemetered rather than fabricated. Real end-to-end SIM run + a unit check of the comparison on real legs."""
from fastapi.testclient import TestClient

_ORDERS = [{"kind": "cut", "x": 10.0, "y": 10.0, "action": "dig pad", "footprint_m2": 4.0, "depth_m": 0.3}]


def _client(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("STEWIE_API_KEY", raising=False)
    monkeypatch.setenv("STEWIE_DEV_OPEN", "1")
    import stewie.server.server as SRV
    return TestClient(SRV.app)


def test_tm04_run_reports_predicted_vs_observed(monkeypatch, tmp_path):  # [REQ:TM-04]
    c = _client(monkeypatch, tmp_path)
    r = c.post("/executive/run", json={"orders": _ORDERS, "site": "haworth"})
    assert r.status_code == 200, r.text
    tc = r.json()["terramechanics_comparison"]
    by = {t["term"]: t for t in tc["terms"]}
    assert tc["backend"] == "tier2_numpy" and tc["n_legs"] >= 1

    # energy is a REAL predicted-vs-observed comparison with a residual
    e = by["energy_J"]
    assert e["available"] is True and e["predicted"] is not None and e["observed"] is not None
    assert e["residual"] == e["observed"] - e["predicted"] and "within_tolerance" in e

    # slip is reported observed-only (honest: no nominal-slip prediction is telemetered)
    s = by["slip"]
    assert s["available"] == "observed_only" and s["predicted"] is None and s["observed"] is not None

    # sinkage is honestly marked not-telemetered, NOT fabricated
    k = by["sinkage"]
    assert k["available"] is False and k["observed"] is None and k["predicted"] is None


def test_tm04_comparison_defers_to_real_legs():  # [REQ:TM-04]
    from stewie.runtime.replay_loop import terramechanics_comparison
    legs = [{"nominal_J": 100.0, "true_J": 130.0, "energy_sigma_J": 10.0, "slip": 0.02},
            {"nominal_J": 200.0, "true_J": 205.0, "energy_sigma_J": 50.0, "slip": 0.04}]
    by = {t["term"]: t for t in terramechanics_comparison(legs)["terms"]}
    # energy sums the real legs; residual = observed - predicted; tolerance = sum of leg sigmas
    assert by["energy_J"]["predicted"] == 300.0 and by["energy_J"]["observed"] == 335.0
    assert by["energy_J"]["residual"] == 35.0 and by["energy_J"]["within_tolerance"] is True  # 35 <= 60
    assert abs(by["slip"]["observed"] - 0.03) < 1e-9   # mean of the real leg slips
    # empty legs -> no fabricated numbers
    empty = {t["term"]: t for t in terramechanics_comparison([])["terms"]}
    assert empty["slip"]["observed"] is None and empty["energy_J"]["predicted"] == 0.0
