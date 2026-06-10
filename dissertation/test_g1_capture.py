"""G1 locked-capture integrity: the simulated baseline files match their manifest hashes, and the
recorded wheel+IMU dead-reckoning baseline is in the physically expected band."""
import hashlib
import json
import os

import pytest

ROOT = os.path.dirname(__file__)                                  # dissertation/ (M2)
MANIFEST = os.path.join(ROOT, "validation", "scene_manifest.json")
G1CAP = os.path.join(ROOT, "validation", "g1_capture.py")
_DUST = os.environ.get("DUSTGYM_ROOT", "/mnt/projects/foss_ipex/dustgym")
_DEM = os.path.join(_DUST, "samples", "lunar_dem", "haworth_10km_5m", "heightmap.rf32")


def test_g1a3_capture_has_no_hardcoded_machine_paths():
    src = open(G1CAP).read()
    assert "/mnt/projects" not in src       # portable: dustgym/DEM/output resolved via CLI/env


@pytest.mark.skipif(not os.path.exists(_DEM), reason="dustgym DEM not available")
def test_g1a3_capture_portable_and_reproducible(tmp_path):
    import subprocess
    import sys

    def run(out):
        subprocess.run([sys.executable, G1CAP, "--dustgym-root", _DUST, "--dem", _DEM,
                        "--output", str(out), "--seed", "0"], cwd=ROOT, check=True,
                       env={**os.environ, "PYTHONPATH": os.path.dirname(ROOT)})   # monorepo root (M2)
    a, b = tmp_path / "a", tmp_path / "b"
    run(a); run(b)

    def h(p):
        return hashlib.sha256(open(p, "rb").read()).hexdigest()
    for f in ("imu.csv", "wheel_odom.csv", "truth.csv"):
        assert h(a / f) == h(b / f)          # reproducible across separate output dirs
    prov = json.load(open(a / "g1_capture_result.json"))["reproducibility"]
    for k in ("dustgym_commit", "solnav_commit", "param_sha256", "dem_sha256", "seed", "python", "numpy"):
        assert k in prov


def _entry():
    m = json.load(open(MANIFEST))
    for e in m.get("simulated_locked", []):
        if e["id"] == "g1_imu_wheel_baseline_haworth":
            return e
    return None


def test_manifest_has_g1_simulated_locked_entry():
    e = _entry()
    assert e is not None and "MEASUREMENT_MODEL_SIM" in e["provenance"]
    assert e["files"]                                            # hashes are recorded


@pytest.mark.skipif(_entry() is None or not os.path.exists(os.path.join(ROOT, "validation", "g1_capture", "imu.csv")),
                    reason="G1 capture not generated (run validation/g1_capture.py)")
def test_g1_locked_capture_matches_manifest_hashes():
    e = _entry()
    for rel, expected in e["files"].items():
        path = os.path.join(ROOT, rel)
        got = hashlib.sha256(open(path, "rb").read()).hexdigest()
        assert got == expected, f"{rel} hash drift: locked capture was modified"


@pytest.mark.skipif(not os.path.exists(os.path.join(ROOT, "validation", "g1_capture", "g1_capture_result.json")),
                    reason="G1 capture not generated")
def test_g1_baseline_ate_in_expected_band():
    r = json.load(open(os.path.join(ROOT, "validation", "g1_capture", "g1_capture_result.json")))
    b = r["baseline_wheel_imu_dead_reckoning"]
    assert r["imu_rate_hz"] == 100.0 and r["wheel_rate_hz"] == 10.0
    assert r["n_imu_samples"] == 32000 and r["n_wheel_samples"] == 3200
    # passive dead reckoning on an ~88 m slip path: a few metres of drift, not cm and not hundreds
    assert 1.0 < b["ate_raw_same_frame_m"] < 20.0
    assert 0.0 < r["mean_slip"] < 0.30          # within the Maimone low-slip regime
