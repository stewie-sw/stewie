#!/usr/bin/env python3
"""P1.7 headless 3D **render proof** attempt for the STEWIE 3D local scene.

This is the honest "attempt the render" leg of P1.7. QGIS 3.22's PyQGIS bindings
do NOT expose the offscreen 3D engine (``QgsOffscreen3DEngine``), ``Qgs3DMapScene``
or ``Qgs3DUtils``, so the ONLY programmatic 3D render path here is a print layout
carrying a ``QgsLayoutItem3DMap`` (which IS exposed) exported to an image. That
path drives Qt3D under the hood and needs a real OpenGL context, so this script
must run under a GL-capable display (xvfb provides GL 4.5 via llvmpipe on this
host; the NVIDIA GPU is only reachable via Vulkan under a bare Xvfb, not GLX).

Run (the wrapper handles the display + a non-offscreen Qt platform):

    ./render_3d_proof.sh                 # -> proof/site01_3d.png (+ per-site)
    ./render_3d_proof.sh Site04          # a specific site

On success it writes ``proof/<site>_3d.png`` and prints the non-black fraction.
On failure it prints the EXACT failure and exits non-zero -- it never writes a
fake/blank PNG. The persisted 3D scene config in ``stewie_south_pole.qgz`` (built
by ``build_project.py``) is the real deliverable regardless; this only tries to
capture a picture of it headlessly.
"""
from __future__ import annotations

import os
import sys

# Must NOT be offscreen: Qt3D needs a GL context. The wrapper sets DISPLAY (xvfb)
# and clears QT_QPA_PLATFORM; guard here too.
if os.environ.get("QT_QPA_PLATFORM") == "offscreen":
    os.environ.pop("QT_QPA_PLATFORM")

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import scene3d  # noqa: E402
import build_project as B  # constants (SITES, PROJ_CRS)  # noqa: E402

QGZ = os.path.join(HERE, "stewie_south_pole.qgz")


def _img_stats(img, step=6):
    """Return (terrain_frac, lum_std). ``terrain_frac`` is the fraction of pixels
    that are drawn TERRAIN (not near-white layout page, not near-black) -- so a
    blank white page (which a naive non-black check would pass) scores ~0. A real
    draped 3D terrain also has high luminance variance, caught by ``lum_std``."""
    w, h = img.width(), img.height()
    lums, terrain, n = [], 0, 0
    for y in range(0, h, step):
        for x in range(0, w, step):
            c = img.pixelColor(x, y)
            r, g, b, a = c.red(), c.green(), c.blue(), c.alpha()
            lum = 0.299 * r + 0.587 * g + 0.114 * b
            lums.append(lum)
            near_white = (r > 244 and g > 244 and b > 244)
            near_black = (r + g + b) < 24 or a == 0
            terrain += (not near_white and not near_black)
            n += 1
    mean = sum(lums) / n
    std = (sum((v - mean) ** 2 for v in lums) / n) ** 0.5
    return round(terrain / n, 4), round(std, 2)


def render_site(site: str, out_png: str, px: int = 1400, dpi: int = 180) -> tuple[bool, float, str]:
    from qgis.core import (
        QgsProject, QgsCoordinateReferenceSystem, QgsReadWriteContext,
        QgsLayout, QgsLayoutExporter, QgsLayoutPoint,
        QgsLayoutSize, QgsUnitTypes, QgsVector3D,
    )
    from qgis._3d import Qgs3DMapSettings, QgsLayoutItem3DMap, QgsCameraPose
    from qgis.PyQt.QtXml import QDomDocument

    proj = QgsProject()
    if not proj.read(QGZ):
        return False, 0.0, f"could not read project {QGZ}"

    dem = proj.mapLayersByName(f"{site} DEM")
    hs = proj.mapLayersByName(f"{site} Hillshade")
    sl = proj.mapLayersByName(f"{site} Slope")
    if not (dem and hs and sl):
        return False, 0.0, f"{site}: DEM/Hillshade/Slope not all present in project"
    dem, hs, sl = dem[0], hs[0], sl[0]

    ext = dem.dataProvider().extent()
    cx = (ext.xMinimum() + ext.xMaximum()) / 2.0
    cy = (ext.yMinimum() + ext.yMaximum()) / 2.0
    st = dem.dataProvider().bandStatistics(1)
    mid_elev = (st.minimumValue + st.maximumValue) / 2.0
    width, height = ext.width(), ext.height()

    crs = QgsCoordinateReferenceSystem(B.PROJ_CRS)
    crs_inner = scene3d.crs_inner_xml(crs, QDomDocument)
    # drape order top->bottom: slope, DEM, hillshade (matches the 2D proof stack).
    drape_ids = [sl.id(), dem.id(), hs.id()]
    qgis3d_xml = scene3d.build_qgis3d_xml(dem.id(), drape_ids, cx, cy, mid_elev, crs_inner)

    doc = QDomDocument()
    if not doc.setContent(qgis3d_xml):
        return False, 0.0, "hand-authored <qgis3d> XML did not parse"
    settings = Qgs3DMapSettings()
    settings.readXml(doc.documentElement(), QgsReadWriteContext())
    settings.setTransformContext(proj.transformContext())
    settings.setPathResolver(proj.pathResolver())
    settings.setMapThemeCollection(proj.mapThemeCollection())
    settings.resolveReferences(proj)
    if not settings.crs().isValid():
        return False, 0.0, "3D settings CRS did not resolve"
    if len(settings.layers()) != 3:
        return False, 0.0, f"3D drape layers did not resolve ({len(settings.layers())}/3)"

    # print layout carrying the 3D map item
    layout = QgsLayout(proj)
    layout.initializeDefaults()
    page = layout.pageCollection().pages()[0]
    side_mm = px / dpi * 25.4
    page.setPageSize(QgsLayoutSize(side_mm, side_mm, QgsUnitTypes.LayoutMillimeters))

    item = QgsLayoutItem3DMap(layout)
    layout.addLayoutItem(item)
    item.attemptMove(QgsLayoutPoint(0, 0, QgsUnitTypes.LayoutMillimeters))
    item.attemptResize(QgsLayoutSize(side_mm, side_mm, QgsUnitTypes.LayoutMillimeters))
    item.setMapSettings(settings)

    (wx, wy, wz), dist, pitch, yaw = scene3d.camera_pose(cx, cy, mid_elev, width, height)
    pose = QgsCameraPose()
    pose.setCenterPoint(QgsVector3D(wx, wy, wz))
    pose.setDistanceFromCenterPoint(dist)
    pose.setPitchAngle(pitch)
    pose.setHeadingAngle(yaw)
    item.setCameraPose(pose)

    exporter = QgsLayoutExporter(layout)
    img_settings = QgsLayoutExporter.ImageExportSettings()
    img_settings.dpi = dpi
    res = exporter.exportToImage(out_png, img_settings)
    if res != QgsLayoutExporter.Success:
        return False, 0.0, f"QgsLayoutExporter.exportToImage returned {res} (not Success)"
    if not os.path.exists(out_png):
        return False, 0.0, "exporter reported success but no PNG written"

    from qgis.PyQt.QtGui import QImage
    img = QImage(out_png)
    if img.isNull():
        return False, 0.0, "exported PNG failed to load"
    terrain_frac, lum_std = _img_stats(img)
    # A real oblique DEM render fills a large share of the frame with colored
    # terrain AND has high luminance variance; a blank page fails both.
    if terrain_frac < 0.30 or lum_std < 15.0:
        return False, terrain_frac, (f"render is blank/degenerate "
                                     f"(terrain_frac={terrain_frac}, lum_std={lum_std})")
    return True, terrain_frac, f"lum_std={lum_std}"


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    sites = argv or ["Site01"]
    from qgis.core import QgsApplication
    QgsApplication.setPrefixPath("/usr", True)
    app = QgsApplication([], True)  # GUI enabled -> Qt3D
    app.initQgis()

    proof_dir = os.path.join(HERE, "proof")
    os.makedirs(proof_dir, exist_ok=True)
    rc = 0
    for site in sites:
        out = os.path.join(proof_dir, f"{site.lower()}_3d.png")
        try:
            ok, frac, msg = render_site(site, out)
        except Exception as exc:  # noqa: BLE001
            ok, frac, msg = False, 0.0, f"exception: {exc!r}"
        if ok:
            print(f"[3d-proof] {site}: WROTE {out} terrain_frac={frac} {msg}")
        else:
            print(f"[3d-proof] {site}: FAILED -> {msg}")
            rc = 3
    sys.stdout.flush()
    os._exit(rc)


if __name__ == "__main__":
    main()
