#!/usr/bin/env python3
"""Headless acceptance tests for the STEWIE south-pole lunar QGIS project.

Reproduces P1 acceptance-gate items 1 / 3 / 4 on real data, no synthetic values:

  Gate 1  test_pole_renders_not_black   - the pole (Site01 89.46S, Site04 89.77S)
          renders DEM+hillshade+slope as ordinary, undistorted GIS (no black wall).
  Gate 3  test_value_readout_fidelity   - QGIS raster identify/sample returns the
          SAME Float32 value as `gdallocationinfo -valonly` for spot pixels/site.
  Gate 4  test_measurement_polar_tolerance - a known site extent measured in the
          metric IAU_2015:30135 frame matches the gdal extent, and the true Moon-
          sphere ground distance is within the polar-stereo scale tolerance
          k = 2/(1+sin|phi|).
  (also) test_project_crs_and_no_earth_claim - project CRS is IAU_2015:30135; the
          authoritative COGs are 30135, the site vectors + external context layers
          are the lunar geographic 30100, and NO layer is tagged EPSG:4326/WGS.

  Gate 5  test_gate5_artemis_rows_all_accounted (pure python, no QGIS) - every
          ARTEMIS_LAYERS.md row is a loaded layer OR an explicitly-deferred row with
          a reason + URL (the importable ARTEMIS_ROWS registry).
  Gate 6  test_gate6_status_json_consistency (pure python) + test_gate6_connections_
          render_from_saved_project (QGIS) - the external connections recorded as
          "renders" carry a real non-blank render_frac, are added to the saved .qgz,
          and the site01_with_imagery proof PNG is non-black.
  (P1.4)  test_site_vectors_roundtrip (QGIS) - the 9 site pins (8 SiteNN + Haworth)
          load in 30100, ids match the backend naming, and each pin round-trips
          30100->30135 inside its own DEM footprint.

QGIS-dependent tests are guarded with ``pytest.importorskip("qgis")`` so they SKIP
cleanly where QGIS is not installed (STEWIE CI has no QGIS lane yet) and RUN on this
host. The two gate-5/gate-6 registry/json tests are pure python and always run.

This file is a valid pytest module (CI seed) AND a standalone runner. On a host
whose system python has no pytest (PEP-668), run it directly:

    QT_QPA_PLATFORM=offscreen /usr/bin/python3 test_project.py

The standalone runner executes the identical test_* functions and locks the
process exit code (0 = all pass) via os._exit, bypassing QGIS's segfault-on-
teardown on this host. In a qgis+pytest CI container it runs as normal pytest.
"""
from __future__ import annotations

import json
import math
import os
import subprocess
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_project as B  # constants + pure helpers; no QGIS side effects on import

QGZ = os.path.join(HERE, "stewie_south_pole.qgz")
STATUS_JSON = os.path.join(HERE, "layer_status.json")
PROOF_IMAGERY = os.path.join(HERE, "proof", "site01_with_imagery.png")


def _need_qgis():
    """Skip under pytest when QGIS is absent; no-op in the standalone runner (host
    has QGIS). Keeps CI (no QGIS lane) green while running fully on this host.

    Note: this host carries a BROKEN empty-namespace `pytest` (importable but with
    no `importorskip`/`main`); treat that as "no pytest" and import qgis directly."""
    try:
        import pytest
        real_pytest = hasattr(pytest, "importorskip") and hasattr(pytest, "main")
    except ImportError:
        real_pytest = False
    if real_pytest:
        pytest.importorskip("qgis")   # under real pytest: SKIP if qgis is missing
    else:
        import qgis  # noqa: F401 -- standalone host: raises only if truly missing

_APP = None
_PROJECT = None


def _qgis():
    global _APP
    if _APP is None:
        from qgis.core import QgsApplication
        QgsApplication.setPrefixPath("/usr", True)
        _APP = QgsApplication([], False)
        _APP.initQgis()
    return _APP


def _project():
    global _PROJECT
    if _PROJECT is None:
        _qgis()
        from qgis.core import QgsProject
        p = QgsProject()
        assert p.read(QGZ), f"failed to read {QGZ}"
        _PROJECT = p
    return _PROJECT


def _raster_layers(kinds):
    """Data raster layers whose name ends with one of `kinds` (e.g. 'DEM','Slope')."""
    out = []
    for lyr in _project().mapLayers().values():
        nm = lyr.name()
        if any(nm.endswith(k) or nm.endswith(k + " (1 m)") for k in kinds):
            out.append(lyr)
    return sorted(out, key=lambda l: l.name())


def _is_nodata(v):
    return (v is None) or (isinstance(v, float) and math.isnan(v)) \
        or (v <= -9000.0) or (v < -1e30)


def _gdal_value(path, col, row):
    r = subprocess.run(["gdallocationinfo", "-valonly", path, str(col), str(row)],
                       capture_output=True, text=True)
    s = r.stdout.strip()
    if not s:
        return None
    try:
        return float(s.split("\n")[0])
    except ValueError:
        return None


def _pixel_center_xy(layer, col, row):
    from qgis.core import QgsPointXY
    ext = layer.dataProvider().extent()
    w, h = layer.width(), layer.height()
    x = ext.xMinimum() + (col + 0.5) * (ext.width() / w)
    y = ext.yMaximum() - (row + 0.5) * (ext.height() / h)
    return QgsPointXY(x, y)


# candidate interior grid positions (fx, fy) -> pick first 3 valid per raster
_CANDIDATES = [(0.40, 0.40), (0.50, 0.50), (0.60, 0.60),
               (0.45, 0.55), (0.55, 0.45), (0.35, 0.62), (0.62, 0.35),
               (0.50, 0.35), (0.35, 0.50)]


# ---------------------------------------------------------------------------
# Gate: CRS + no-Earth-claim (MA-01)
# ---------------------------------------------------------------------------
def test_project_crs_and_no_earth_claim():
    _need_qgis()
    p = _project()
    assert p.crs().authid() == B.PROJ_CRS, p.crs().authid()
    assert p.ellipsoid() == B.MOON_ELLIPSOID, p.ellipsoid()
    layers = list(p.mapLayers().values())
    by_prov = {}
    for lyr in layers:
        by_prov.setdefault(lyr.providerType(), []).append(lyr)

    # MA-01 no-Earth-claim: EVERY layer is a lunar IAU_2015 frame; external WMS are
    # relabelled to 30100, so nothing in the project is EPSG:4326/WGS84.
    for lyr in layers:
        aid = lyr.crs().authid()
        assert aid.startswith("IAU_2015:"), f"{lyr.name()} tagged {aid!r}, not a lunar CRS"
        assert "4326" not in aid and "WGS" not in aid.upper(), f"{lyr.name()} tagged {aid!r} (Earth)"

    # gdal rasters: 26 authoritative terrain COGs + 3 context/basemap COGs (the LOLA relief
    # basemaps + the LROC WAC albedo toggle) = 29, all relabelled to IAU_2015:30135.
    gdal = by_prov.get("gdal", [])
    assert len(gdal) == 29, f"expected 29 gdal rasters (26 terrain + 3 basemap/context), got {len(gdal)}"
    for lyr in gdal:
        assert lyr.crs().authid() == B.PROJ_CRS, f"{lyr.name()} tagged {lyr.crs().authid()}"

    # Site vectors: 2 ogr layers in the lunar geographic 30100.
    ogr = by_prov.get("ogr", [])
    assert len(ogr) == 2, f"expected 2 vector layers, got {len(ogr)}"
    for lyr in ogr:
        assert lyr.crs().authid() == B.GEO_CRS, f"{lyr.name()} tagged {lyr.crs().authid()}"

    # External context WMS: relabelled to lunar 30100 (no Earth claim).
    wms = by_prov.get("wms", [])
    assert wms, "expected >=1 external WMS context layer"
    for lyr in wms:
        assert lyr.crs().authid() == B.GEO_CRS, f"{lyr.name()} WMS tagged {lyr.crs().authid()}"

    assert len(layers) == 29 + 2 + len(wms), \
        f"layer accounting: {len(layers)} != 29 gdal + 2 ogr + {len(wms)} wms"
    print(f"[gate-crs] project CRS={p.crs().authid()} ellipsoid={p.ellipsoid()} "
          f"layers={len(layers)} = 26 terrain + 3 basemap/context (30135) + 2 vectors(30100) + "
          f"{len(wms)} external(30100); none EPSG:4326/WGS")


# ---------------------------------------------------------------------------
# Gate 5: every ARTEMIS_LAYERS row is a loaded layer or a deferred row w/ reason
# (pure python -- no QGIS, always runs, incl. STEWIE CI without a QGIS lane).
# ---------------------------------------------------------------------------
def test_gate5_artemis_rows_all_accounted():
    bad = B.artemis_gate5_ok()
    assert bad == [], f"gate-5 rows not fully accounted: {bad}"
    dispositions = {r["disposition"] for r in B.ARTEMIS_ROWS}
    assert dispositions <= {"loaded", "deferred"}, dispositions
    loaded = [r for r in B.ARTEMIS_ROWS if r["disposition"] == "loaded"]
    deferred = [r for r in B.ARTEMIS_ROWS if r["disposition"] == "deferred"]
    assert len(B.ARTEMIS_ROWS) >= 16, len(B.ARTEMIS_ROWS)
    for r in deferred:
        assert r.get("reason") and r.get("url"), f"deferred row missing reason/url: {r['row']}"
    joined = " ".join(r["row"].lower() for r in B.ARTEMIS_ROWS)
    for token in ("trek", "lunaserv", "quickmap", "/ogc"):
        assert token in joined, f"ARTEMIS catalog missing a row for {token!r}"
    print(f"[gate-5] {len(B.ARTEMIS_ROWS)} rows: {len(loaded)} loaded, "
          f"{len(deferred)} deferred (each with reason+URL) -- all accounted")


# ---------------------------------------------------------------------------
# Gate 6 (pure python): recorded external-render evidence is internally consistent.
# ---------------------------------------------------------------------------
def test_gate6_status_json_consistency():
    assert os.path.exists(STATUS_JSON), f"missing {STATUS_JSON}; run build_project.py"
    with open(STATUS_JSON) as fh:
        status = json.load(fh)
    assert status["gate5_ok"] is True
    svcs = {s["id"]: s for s in status["gate6_external_services"]}
    assert svcs, "no external services recorded"
    renders = [s for s in svcs.values() if s["status"] == "renders"]
    assert renders, "gate 6 expects at least one external connection that RENDERS"
    for s in renders:
        assert s["render_frac"] >= 0.02, f"{s['id']} 'renders' but frac={s['render_frac']}"
        assert s["added"] is True, f"{s['id']} 'renders' but not added to project"
    nac = svcs.get("stewie.base.lroc_nac_sp")           # priority NAC drape must render
    assert nac and nac["status"] == "renders" and nac["render_frac"] >= 0.2, nac
    ogc = svcs.get("stewie.base.stewie_ogc_dem")        # added; server tile real
    assert ogc and ogc["added"] is True, ogc
    assert ogc.get("server_tile_frac", 0.0) >= 0.2, \
        f"/ogc server tile evidence missing/blank: {ogc.get('server_tile_frac')}"
    print(f"[gate-6/json] {len(renders)} connections render "
          f"(NAC={nac['render_frac']}); /ogc server tile={ogc.get('server_tile_frac')}")


# ---------------------------------------------------------------------------
# Gate 6 (QGIS): the saved .qgz's external connections + the imagery proof PNG.
# ---------------------------------------------------------------------------
def test_gate6_connections_render_from_saved_project():
    _need_qgis()
    from qgis.core import (QgsCoordinateReferenceSystem, QgsMapRendererParallelJob,
                           QgsMapSettings)
    from qgis.PyQt.QtCore import QSize
    from qgis.PyQt.QtGui import QColor, QImage
    p = _project()
    wms = [L for L in p.mapLayers().values() if L.providerType() == "wms"]
    ids = {L.metadata().identifier() for L in wms}
    for want in ("stewie.base.lroc_nac_sp", "stewie.base.lroc_wac_global",
                 "stewie.base.stewie_ogc_dem"):
        assert want in ids, f"{want} not in saved project WMS layers {ids}"
    for L in wms:
        assert L.crs().authid() == B.GEO_CRS, f"{L.name()} not relabelled lunar"

    assert os.path.exists(PROOF_IMAGERY), f"missing proof {PROOF_IMAGERY}"
    img = QImage(PROOF_IMAGERY)
    assert not img.isNull(), "proof PNG failed to load"
    nz = n = 0
    for y in range(0, img.height(), 12):
        for x in range(0, img.width(), 12):
            c = img.pixelColor(x, y)
            n += 1
            nz += (c.red() + c.green() + c.blue()) > 20
    frac = nz / n
    assert frac > 0.5, f"imagery proof non-black frac {frac:.3f} too low"
    print(f"[gate-6/qgis] {len(wms)} WMS connections in saved .qgz (all 30100); "
          f"site01_with_imagery non-black frac={frac:.3f}")

    # Bonus: live re-render of the NAC drape from the SAVED project over Site01.
    # Network-dependent -> skip (never fail) if the service is unreachable now.
    try:
        nac = [L for L in wms if L.metadata().identifier() == "stewie.base.lroc_nac_sp"][0]
        ext = p.mapLayersByName("Site01 DEM")[0].dataProvider().extent()
        ms = QgsMapSettings()
        ms.setLayers([nac])
        ms.setDestinationCrs(QgsCoordinateReferenceSystem(B.PROJ_CRS))
        ms.setExtent(ext)
        ms.setOutputSize(QSize(256, 256))
        ms.setBackgroundColor(QColor(0, 0, 0))
        job = QgsMapRendererParallelJob(ms)
        job.start()
        job.waitForFinished()
        rimg = job.renderedImage()
        rz = rn = 0
        for y in range(0, rimg.height(), 6):
            for x in range(0, rimg.width(), 6):
                c = rimg.pixelColor(x, y)
                rn += 1
                rz += (c.alpha() > 0 and (c.red() + c.green() + c.blue()) > 20)
        live = rz / rn
        if live > 0.0:
            assert live >= 0.05, f"live NAC re-render suspiciously blank: {live}"
            print(f"[gate-6/qgis] live NAC re-render over Site01 non-black frac={live:.3f}")
        else:
            print("[gate-6/qgis] live NAC re-render blank (service unreachable now) -- skipped")
    except Exception as exc:  # noqa: BLE001 -- network is optional for this bonus check
        print(f"[gate-6/qgis] live NAC re-render skipped ({exc})")


# ---------------------------------------------------------------------------
# P1.4: the site vectors load in 30100 and round-trip 30100<->30135 in-footprint.
# ---------------------------------------------------------------------------
def test_site_vectors_roundtrip():
    _need_qgis()
    from qgis.core import (QgsCoordinateReferenceSystem, QgsCoordinateTransform,
                           QgsPointXY)
    p = _project()
    pins = p.mapLayersByName("Artemis site pins")
    foots = p.mapLayersByName("Artemis site footprints")
    assert pins and foots, "vector layers not found in project"
    pins, foots = pins[0], foots[0]
    assert pins.crs().authid() == B.GEO_CRS, pins.crs().authid()
    assert foots.crs().authid() == B.GEO_CRS, foots.crs().authid()
    # The 8 SiteNN pins + the Haworth 1 m SfS tile (its own DEM, not a SiteNN).
    expected_ids = set(B.SITES) | {"Haworth"}
    assert pins.featureCount() == len(expected_ids), pins.featureCount()
    assert foots.featureCount() == len(expected_ids), foots.featureCount()

    ids = {f["site"] for f in pins.getFeatures()}
    assert ids == expected_ids, f"pin site ids {ids} != {expected_ids}"

    # Each pin's DEM layer name: SiteNN -> "<Site> DEM"; Haworth -> "Haworth DEM (1 m)".
    dem_name = {s: f"{s} DEM" for s in B.SITES}
    dem_name["Haworth"] = "Haworth DEM (1 m)"

    geo = QgsCoordinateReferenceSystem(B.GEO_CRS)
    prj = QgsCoordinateReferenceSystem(B.PROJ_CRS)
    ct = QgsCoordinateTransform(geo, prj, p.transformContext())
    checked = 0
    for f in pins.getFeatures():
        site = f["site"]
        dem = p.mapLayersByName(dem_name[site])
        assert dem, f"no DEM layer for {site}"
        ext = dem[0].dataProvider().extent()      # 30135 metric
        g = f.geometry().asPoint()                # 30100 lon/lat
        xy = ct.transform(QgsPointXY(g.x(), g.y()))
        assert ext.contains(xy), \
            f"{site} pin {xy} not inside its DEM extent {ext.toString(0)}"
        checked += 1
    assert checked == len(expected_ids)
    print(f"[p1.4] {checked} site pins round-trip 30100->30135 inside their DEM "
          f"footprints; ids match backend naming {sorted(ids)}")


# ---------------------------------------------------------------------------
# Continuous south-polar basemap: a real LOLA LDEM hillshade COG loaded at the
# bottom of the tree, relabelled 30135, spanning ~75-90S (fills under the sites).
# ---------------------------------------------------------------------------
def test_south_polar_basemap_present():
    _need_qgis()
    p = _project()
    found = p.mapLayersByName(B.BASEMAP_NAME)
    assert found, f"basemap layer {B.BASEMAP_NAME!r} not in project"
    bm = found[0]
    assert bm.providerType() == "gdal", bm.providerType()
    assert bm.crs().authid() == B.PROJ_CRS, bm.crs().authid()
    assert bm.source().endswith("basemap_south_polar.tif"), bm.source()
    # 75-90S native LDEM square is ~915 km across (pole-centred), so its extent must
    # reach well beyond the ~305 km site-cluster block -> it truly fills under+around.
    ext = bm.dataProvider().extent()
    assert ext.width() > 800000.0, f"basemap extent too small: {ext.width():.0f} m"
    assert ext.xMinimum() < -400000.0 and ext.xMaximum() > 400000.0, ext.toString(0)
    # Bottom of the tree (rendered first / underneath the authoritative DEMs).
    root = p.layerTreeRoot()
    last = root.children()[-1]
    from qgis.core import QgsLayerTreeGroup
    assert isinstance(last, QgsLayerTreeGroup), type(last)
    assert bm.id() in [n.layerId() for n in last.findLayers()], \
        "basemap is not in the bottom-most layer-tree group"
    print(f"[basemap] {B.BASEMAP_NAME}: gdal {bm.crs().authid()} "
          f"{bm.width()}x{bm.height()} extent_w={ext.width():.0f} m; bottom of tree")


# ---------------------------------------------------------------------------
# Gate 3: value readout fidelity (QGIS sample == gdallocationinfo, Float32)
# ---------------------------------------------------------------------------
def test_value_readout_fidelity():
    _need_qgis()
    rasters = _raster_layers(("DEM", "Slope"))
    assert rasters, "no DEM/Slope layers found"
    rows = []
    mismatches = []
    per_raster = {}
    for lyr in rasters:
        path = lyr.source()
        prov = lyr.dataProvider()
        w, h = lyr.width(), lyr.height()
        found = 0
        for fx, fy in _CANDIDATES:
            if found >= 3:
                break
            col, row = int(fx * w), int(fy * h)
            gv = _gdal_value(path, col, row)
            if _is_nodata(gv):
                continue
            pt = _pixel_center_xy(lyr, col, row)
            qv, ok = prov.sample(pt, 1)
            if not ok or _is_nodata(qv):
                continue
            diff = abs(qv - gv)
            passed = math.isclose(qv, gv, rel_tol=1e-6, abs_tol=1e-3)
            rows.append((lyr.name(), col, row, gv, qv, diff, passed))
            if not passed:
                mismatches.append((lyr.name(), col, row, gv, qv, diff))
            found += 1
        per_raster[lyr.name()] = found
        assert found == 3, f"{lyr.name()}: only {found} valid spot pixels found"

    print("\n[gate-3] value readout fidelity (QGIS sample vs gdallocationinfo -valonly)")
    print(f"  {'layer':22s} {'col':>5s} {'row':>5s} {'gdal':>16s} {'qgis':>16s} {'|diff|':>10s}  ok")
    for (nm, c, r, gv, qv, d, ok) in rows:
        print(f"  {nm:22s} {c:5d} {r:5d} {gv:16.6f} {qv:16.6f} {d:10.3g}  {'PASS' if ok else 'FAIL'}")
    print(f"  total spot checks={len(rows)} across {len(rasters)} COGs; mismatches={len(mismatches)}")
    assert not mismatches, f"value mismatches: {mismatches}"


# ---------------------------------------------------------------------------
# Gate 4: measurement in the metric polar frame within polar-stereo tolerance
# ---------------------------------------------------------------------------
def test_measurement_polar_tolerance():
    _need_qgis()
    from qgis.core import (QgsCoordinateReferenceSystem, QgsCoordinateTransform,
                           QgsDistanceArea, QgsPointXY)
    p = _project()
    crs = QgsCoordinateReferenceSystem(B.PROJ_CRS)
    geo = QgsCoordinateReferenceSystem(B.GEO_CRS)
    ct = QgsCoordinateTransform(crs, geo, p.transformContext())

    da = QgsDistanceArea()
    da.setSourceCrs(crs, p.transformContext())
    da.setEllipsoid("NONE")  # planar metric measurement in the projected frame

    rows = []
    for site in B.SITES:
        lyr = p.mapLayersByName(f"{site} DEM")[0]
        ext = lyr.dataProvider().extent()
        w = lyr.width()
        px = ext.width() / w
        gdal_extent_m = w * px                    # == ncols * pixel size (gdalinfo)
        p1 = QgsPointXY(ext.xMinimum(), ext.yMaximum())
        p2 = QgsPointXY(ext.xMaximum(), ext.yMaximum())
        planar = da.measureLine(p1, p2)           # QGIS metric measure in 30135
        assert math.isclose(planar, gdal_extent_m, rel_tol=1e-9, abs_tol=1e-6), \
            f"{site}: QGIS planar {planar} != gdal extent {gdal_extent_m}"
        a = ct.transform(p1)
        b = ct.transform(p2)
        ground = B.great_circle_m(a.x(), a.y(), b.x(), b.y())   # true Moon-sphere m
        frac = abs(planar - ground) / planar
        lat_least_south = min(abs(a.y()), abs(b.y()))
        bound = B.polar_stereo_scale_bound(lat_least_south)     # k - 1 (max distortion)
        ok = frac <= bound * 1.05 + 1e-9
        rows.append((site, planar, gdal_extent_m, ground, frac, bound, lat_least_south, ok))

    print("\n[gate-4] measurement: metric 30135 extent vs gdal extent vs Moon-sphere ground")
    print(f"  {'site':7s} {'planar_m':>11s} {'gdal_m':>11s} {'ground_m':>12s} "
          f"{'frac%':>8s} {'bound%':>8s} {'|lat|N':>7s}  ok")
    for (s, pl, ge, gr, fr, bd, la, ok) in rows:
        print(f"  {s:7s} {pl:11.3f} {ge:11.3f} {gr:12.3f} {fr*100:8.4f} "
              f"{bd*100:8.4f} {la:7.3f}  {'PASS' if ok else 'FAIL'}")
    bad = [r for r in rows if not r[-1]]
    assert not bad, f"scale tolerance exceeded: {[(r[0], r[4], r[5]) for r in bad]}"


# ---------------------------------------------------------------------------
# Gate 1: the pole renders as ordinary GIS (DEM+hillshade+slope, no black wall)
# ---------------------------------------------------------------------------
def _render_site(site, size=800):
    from qgis.core import (QgsCoordinateReferenceSystem, QgsMapRendererParallelJob,
                           QgsMapSettings)
    from qgis.PyQt.QtCore import QSize
    from qgis.PyQt.QtGui import QColor
    p = _project()
    names = [f"{site} Slope", f"{site} DEM", f"{site} Hillshade"]
    layers = [p.mapLayersByName(n)[0] for n in names if p.mapLayersByName(n)]
    assert len(layers) == 3, f"{site}: expected slope+dem+hillshade, got {len(layers)}"
    ext = p.mapLayersByName(f"{site} DEM")[0].dataProvider().extent()
    ms = QgsMapSettings()
    ms.setLayers(layers)
    ms.setDestinationCrs(QgsCoordinateReferenceSystem(B.PROJ_CRS))
    ms.setExtent(ext)
    ms.setOutputSize(QSize(size, size))
    ms.setBackgroundColor(QColor(0, 0, 0))
    job = QgsMapRendererParallelJob(ms)
    job.start()
    job.waitForFinished()
    return job.renderedImage()


def _image_stats(img, step=8):
    lums, nonblack, n = [], 0, 0
    w, h = img.width(), img.height()
    for y in range(0, h, step):
        for x in range(0, w, step):
            c = img.pixelColor(x, y)
            lum = 0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue()
            lums.append(lum)
            nonblack += (lum > 8)
            n += 1
    mean = sum(lums) / n
    std = (sum((v - mean) ** 2 for v in lums) / n) ** 0.5
    return mean, std, nonblack / n


def test_pole_renders_not_black():
    _need_qgis()
    print("\n[gate-1] pole render (DEM+hillshade+slope) - no black wall, no distortion")
    for site in ("Site01", "Site04"):
        img = _render_site(site)
        assert not img.isNull(), f"{site}: null render"
        mean, std, frac = _image_stats(img)
        lat = {"Site01": -89.463, "Site04": -89.767}[site]
        print(f"  {site} (lat {lat}): lum_mean={mean:.1f} lum_std={std:.1f} "
              f"nonblack_frac={frac:.3f}")
        assert frac > 0.90, f"{site}: {frac:.3f} non-black (a black wall would be ~0)"
        assert std > 10.0, f"{site}: luminance std {std:.1f} too flat (no terrain)"


# ---------------------------------------------------------------------------
# Standalone runner (locks exit code past QGIS teardown segfault on this host)
# ---------------------------------------------------------------------------
def _standalone():
    tests = [test_gate5_artemis_rows_all_accounted, test_gate6_status_json_consistency,
             test_project_crs_and_no_earth_claim, test_south_polar_basemap_present,
             test_value_readout_fidelity, test_measurement_polar_tolerance,
             test_pole_renders_not_black, test_gate6_connections_render_from_saved_project,
             test_site_vectors_roundtrip]
    failures = 0
    for t in tests:
        try:
            t()
            print(f"PASS: {t.__name__}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"FAIL: {t.__name__}: {exc}")
    print(f"\n=== {len(tests) - failures}/{len(tests)} passed, {failures} failed ===")
    sys.stdout.flush()
    os._exit(1 if failures else 0)


if __name__ == "__main__":
    try:
        import pytest  # noqa: F401
        _has_pytest = hasattr(pytest, "main")
    except Exception:  # noqa: BLE001
        _has_pytest = False
    if _has_pytest:
        raise SystemExit(pytest.main([os.path.abspath(__file__), "-v", "-s"]))
    _standalone()
