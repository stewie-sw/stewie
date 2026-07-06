#!/usr/bin/env python3
"""P1.7 persisted-3D-scene validation (pure python -- no QGIS, no Docker, always runs).

Validates that ``stewie_south_pole.qgz`` carries the DEM-based 3D **local scenes**
as the exact XML QGIS Desktop 3.22+ reads (schema verified against the QGIS
``release-3_22`` source), and that every layer the scenes reference actually exists
in the project. This is the fast CI guard on the 3D config; the visual render proof
is ``render_3d_proof.py`` -> ``proof/site01_3d.png`` (a real oblique DEM render).

Runs under any python (stdlib only). It is a pytest module AND a standalone runner.
"""
from __future__ import annotations

import os
import re
import sys
import xml.etree.ElementTree as ET
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import scene3d  # noqa: E402

QGZ = os.path.join(HERE, "stewie_south_pole.qgz")


def _project_xml() -> str:
    with zipfile.ZipFile(QGZ) as z:
        qgs = [n for n in z.namelist() if n.endswith(".qgs")][0]
        return z.read(qgs).decode("utf-8")


def _project_layer_ids(xml: str) -> set[str]:
    """The canonical layer-definition ids (<id>..</id> inside <maplayer>)."""
    return set(re.findall(r"<id>([^<]+)</id>", xml))


def test_mapviewdocks3d_present_and_wellformed():
    xml = _project_xml()
    m = re.search(r"<mapViewDocks3D>.*?</mapViewDocks3D>", xml, re.S)
    assert m, "no <mapViewDocks3D> element persisted in the .qgz"
    # The block must parse as XML on its own (well-formed).
    root = ET.fromstring(m.group(0))
    assert root.tag == "mapViewDocks3D"
    views = root.findall("view")
    assert len(views) == len(scene3d.SITES_3D), \
        f"expected {len(scene3d.SITES_3D)} 3D views, got {len(views)}"
    names = [v.get("name") for v in views]
    for site in scene3d.SITES_3D:
        assert any(n and n.startswith(site) for n in names), f"no 3D view for {site}: {names}"
    print(f"[3d] {len(views)} <view> present + well-formed: {names}")


def test_each_scene_is_dem_local_scene_with_resolving_layers():
    xml = _project_xml()
    layer_ids = _project_layer_ids(xml)
    block = re.search(r"<mapViewDocks3D>.*?</mapViewDocks3D>", xml, re.S).group(0)
    root = ET.fromstring(block)
    checked = 0
    for view in root.findall("view"):
        name = view.get("name")
        q = view.find("qgis3d")
        assert q is not None, f"{name}: no <qgis3d>"
        # CRS is the lunar polar-stereo frame (local scene on a projected CRS).
        srs = q.find("crs/spatialrefsys")
        assert srs is not None, f"{name}: no <crs><spatialrefsys>"
        authid = srs.findtext("authid")
        assert authid == "IAU_2015:30135", f"{name}: 3D scene CRS {authid} != IAU_2015:30135"
        terrain = q.find("terrain")
        assert terrain is not None and terrain.get("terrain-rendering-enabled") == "1", \
            f"{name}: terrain rendering not enabled"
        # DEM terrain generator referencing a REAL project layer.
        gen = terrain.find("generator")
        assert gen is not None and gen.get("type") == "dem", \
            f"{name}: terrain generator is not a DEM generator"
        dem_id = gen.get("layer")
        assert dem_id in layer_ids, f"{name}: DEM generator layer {dem_id} not in project"
        # Drape layers all resolve to real project layers.
        drape = [el.get("id") for el in terrain.findall("layers/layer")]
        assert len(drape) == 3, f"{name}: expected 3 drape layers, got {len(drape)}"
        for lid in drape:
            assert lid in layer_ids, f"{name}: drape layer {lid} not in project"
        # A camera pose (direct child of <view>, distinct from <qgis3d>/<camera>).
        cams = [c for c in view.findall("camera")]
        pose = [c for c in cams if c.get("dist") is not None]
        assert pose, f"{name}: no camera pose (<camera dist=..>) on the view"
        assert float(pose[0].get("dist")) > 0, f"{name}: camera distance non-positive"
        checked += 1
    assert checked == len(scene3d.SITES_3D)
    print(f"[3d] {checked} scenes: DEM generator + 3-layer drape all resolve to real "
          f"project layers; CRS IAU_2015:30135; camera pose present")


def test_scene3d_builder_unit():
    """scene3d.build_view_xml emits parseable, DEM-generator XML from ids."""
    crs_inner = '<spatialrefsys><authid>IAU_2015:30135</authid></spatialrefsys>'
    v = scene3d.build_view_xml("Site01 3D (local scene)", "DEMID",
                               ["SLOPEID", "DEMID", "HSID"],
                               -11000.0, -12000.0, 700.0, 16000.0, 16000.0, crs_inner)
    root = ET.fromstring(v)
    assert root.tag == "view"
    gen = root.find("qgis3d/terrain/generator")
    assert gen.get("type") == "dem" and gen.get("layer") == "DEMID"
    assert [el.get("id") for el in root.findall("qgis3d/terrain/layers/layer")] == \
        ["SLOPEID", "DEMID", "HSID"]
    assert root.find("camera").get("dist") is not None
    print("[3d] scene3d.build_view_xml -> well-formed DEM local-scene <view>")


def test_render_proof_png_exists():
    """The headless 3D render proof exists (produced by render_3d_proof.py)."""
    png = os.path.join(HERE, "proof", "site01_3d.png")
    assert os.path.exists(png), f"missing {png}; run render_3d_proof.sh"
    assert os.path.getsize(png) > 100_000, "site01_3d.png suspiciously small"
    print(f"[3d] render proof present: {png} ({os.path.getsize(png)//1024} KB)")


_TESTS = [test_mapviewdocks3d_present_and_wellformed,
          test_each_scene_is_dem_local_scene_with_resolving_layers,
          test_scene3d_builder_unit, test_render_proof_png_exists]


def _standalone():
    failures = 0
    for t in _TESTS:
        try:
            t()
            print(f"PASS: {t.__name__}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"FAIL: {t.__name__}: {exc}")
    print(f"\n=== {len(_TESTS) - failures}/{len(_TESTS)} passed, {failures} failed ===")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    try:
        import pytest  # noqa: F401
        _has = hasattr(pytest, "main")
    except Exception:  # noqa: BLE001
        _has = False
    if _has:
        raise SystemExit(pytest.main([os.path.abspath(__file__), "-v", "-s"]))
    _standalone()
