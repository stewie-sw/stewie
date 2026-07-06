#!/usr/bin/env python3
"""Gate-8 clean-machine round-trip test: "John can open it".

Opens ``stewie_south_pole.qgz`` in a FRESH QGIS Docker container (default
``qgis/qgis-server:3.34`` -- PyQGIS 3.34 + an IAU-aware PROJ, a *different* build
from the 3.22 the project was authored in, so this doubles as a forward-compat
open) with only ``code/gis`` + ``data/gis`` mounted, and asserts the project is
portable: every file-backed layer loads valid via its project-relative datasource
path, no "unavailable/bad layer" errors, and a headless Site01 render is non-blank.

The container runs with ``--network none`` (a truly clean machine): the on-disk
IAU_2015:30135 COG rasters + site-vector layers MUST load from the mounted disk;
the external WMS drapes are expected-unreachable and are NOT counted as failures.

This test is **live-only**: it SKIPS cleanly (never fails) where Docker is absent
or the QGIS image is not present locally (it does NOT auto-pull a ~2 GB image in
CI). It runs on this host, where the image is present. Set ``$STEWIE_QGIS_IMAGE``
to use a different image (e.g. ``qgis/qgis:3.34``).

Run:
    /mnt/projects/07_runtime_system/venv/bin/python -m pytest gis/test_cleanmachine.py -v
    # or standalone (no pytest needed):
    /usr/bin/python3 gis/test_cleanmachine.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
CODE_GIS = HERE
DATA_GIS = "/mnt/projects/stewie/data/gis"
QGZ = os.path.join(HERE, "stewie_south_pole.qgz")
PROOF = os.path.join(HERE, "proof")
IMAGE = os.environ.get("STEWIE_QGIS_IMAGE", "qgis/qgis-server:3.34")

# Expected on-disk layers: 26 gdal COG rasters + 2 OGR site-vector layers.
EXPECTED_FILE_LAYERS = 28


def _sh(cmd, timeout=90):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except Exception as exc:  # noqa: BLE001
        return 127, "", str(exc)


def _docker_ready() -> tuple[bool, str]:
    if not shutil.which("docker"):
        return False, "docker CLI not found"
    rc, _, err = _sh(["docker", "info", "--format", "{{.ServerVersion}}"], timeout=30)
    if rc != 0:
        return False, f"docker daemon not usable: {err.strip()[:120]}"
    rc, _, _ = _sh(["docker", "image", "inspect", IMAGE], timeout=30)
    if rc != 0:
        return False, f"image {IMAGE!r} not present locally (skip; do not auto-pull)"
    return True, "ready"


def run_cleanmachine() -> dict:
    """Run the in-container probe and return its JSON report (raises on hard error)."""
    assert os.path.exists(QGZ), f"missing {QGZ}; run build_project.py first"
    out = tempfile.mkdtemp(prefix="stewie_gate8_")
    os.chmod(out, 0o777)  # container root writes report.json + the render here
    try:
        cmd = [
            "docker", "run", "--rm", "--name", "stewie-gate8-cleanmachine",
            "--network", "none",
            "-v", f"{CODE_GIS}:/proj/code/gis:ro",
            "-v", f"{DATA_GIS}:/proj/data/gis:ro",
            "-v", f"{out}:/out",
            "--entrypoint", "/bin/bash", IMAGE, "-lc",
            "QT_QPA_PLATFORM=offscreen python3 /proj/code/gis/cleanmachine_probe.py "
            "/proj/code/gis/stewie_south_pole.qgz /out",
        ]
        rc, sout, serr = _sh(cmd, timeout=300)
        report_path = os.path.join(out, "report.json")
        if not os.path.exists(report_path):
            raise RuntimeError(f"probe wrote no report (rc={rc})\nSTDERR:\n{serr[-800:]}")
        with open(report_path) as fh:
            report = json.load(fh)
        report["_container_rc"] = rc
        # Preserve the clean-machine render as committed evidence.
        png = os.path.join(out, "site01_cleanmachine.png")
        if os.path.exists(png):
            os.makedirs(PROOF, exist_ok=True)
            shutil.copyfile(png, os.path.join(PROOF, "site01_cleanmachine.png"))
            report["_proof_png"] = os.path.join(PROOF, "site01_cleanmachine.png")
        return report
    finally:
        shutil.rmtree(out, ignore_errors=True)


def _skip(msg):
    try:
        import pytest
        if hasattr(pytest, "skip"):
            pytest.skip(msg)
    except ImportError:
        pass
    raise _Skipped(msg)


class _Skipped(Exception):
    pass


def test_cleanmachine_roundtrip():
    """Gate 8: the .qgz opens portably in a fresh containerized QGIS."""
    ready, why = _docker_ready()
    if not ready:
        _skip(f"clean-machine gate is live-only: {why}")
    report = run_cleanmachine()

    assert report["project_read_ok"] is True, "QgsProject.read() failed in the fresh container"
    assert report["n_file_layers"] >= EXPECTED_FILE_LAYERS, \
        f"expected >= {EXPECTED_FILE_LAYERS} file layers, got {report['n_file_layers']}"
    assert report["bad_file_layers"] == [], \
        f"bad/unavailable file layers in fresh container: {report['bad_file_layers']}"
    assert report["n_file_layers_valid"] == report["n_file_layers"], \
        "not every file layer resolved its relative datasource path"
    r = report["render_site01"]
    assert r["attempted"] and r["nonblank_frac"] > 0.9, \
        f"Site01 clean-machine render blank/absent: {r}"
    # the portable .qgz still carries the persisted 3D local scenes
    assert report["scenes_3d_in_qgz"] == 5, \
        f"expected 5 persisted 3D scenes in the portable .qgz, got {report['scenes_3d_in_qgz']}"
    print(f"[gate-8] fresh {report['qgis_version']} container: "
          f"{report['n_file_layers_valid']}/{report['n_file_layers']} file layers valid, "
          f"0 bad; Site01 render non-blank={r['nonblank_frac']}; "
          f"3D scenes in .qgz={report['scenes_3d_in_qgz']}; "
          f"WMS (network none) invalid={sum(1 for w in report['wms_layers'] if not w['valid'])}/"
          f"{len(report['wms_layers'])} (expected)")


def _standalone():
    try:
        test_cleanmachine_roundtrip()
        print("PASS: test_cleanmachine_roundtrip")
        code = 0
    except _Skipped as exc:
        print(f"SKIP: test_cleanmachine_roundtrip: {exc}")
        code = 0
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: test_cleanmachine_roundtrip: {exc}")
        code = 1
    sys.stdout.flush()
    sys.exit(code)


if __name__ == "__main__":
    try:
        import pytest  # noqa: F401
        _has_pytest = hasattr(pytest, "main")
    except Exception:  # noqa: BLE001
        _has_pytest = False
    if _has_pytest:
        raise SystemExit(pytest.main([os.path.abspath(__file__), "-v", "-s"]))
    _standalone()
