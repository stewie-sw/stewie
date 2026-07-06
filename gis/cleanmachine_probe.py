#!/usr/bin/env python3
"""Gate-8 clean-machine probe -- runs INSIDE a fresh QGIS Docker container.

Opens ``stewie_south_pole.qgz`` in a QGIS install that has never seen this project
(e.g. ``qgis/qgis-server:3.34``, PyQGIS 3.34 + an IAU-aware PROJ) with only the
mounted ``code/gis`` + ``data/gis`` volumes, and reports whether it is portable:

  * every FILE-backed layer (the 26 IAU_2015:30135 COG rasters + the 2 site-vector
    OGR layers) loads valid AND its datasource resolves to a real file under the
    mounted data volume -- i.e. the project-relative ``../../data/gis/...`` paths
    resolved on a machine that is not this build host. This is the "John can open
    it" proof.
  * a headless render of Site01 (DEM + hillshade + slope, in IAU_2015:30135) is
    non-blank -- the pole-truthful terrain draws in the fresh environment.

External WMS drapes (LROC Lunaserv, STEWIE ``/ogc``) are NETWORK services; the
container runs with ``--network none``, so they are expected-invalid and reported
informationally -- their unreachability is an environment fact, not a portability
defect of the ``.qgz``.

Usage (in-container):  python3 cleanmachine_probe.py <project.qgz> <out_dir>
Writes ``<out_dir>/report.json`` + ``<out_dir>/site01_cleanmachine.png`` and prints
the JSON report. Exit 0 iff all file layers are valid + Site01 render is non-blank.
"""
from __future__ import annotations

import json
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: cleanmachine_probe.py <project.qgz> <out_dir>", file=sys.stderr)
        return 2
    qgz, out_dir = sys.argv[1], sys.argv[2]
    os.makedirs(out_dir, exist_ok=True)

    from qgis.core import (
        Qgis, QgsApplication, QgsProject, QgsSettings,
        QgsCoordinateReferenceSystem, QgsMapSettings, QgsMapRendererParallelJob,
    )
    from qgis.PyQt.QtCore import QSize
    from qgis.PyQt.QtGui import QColor

    QgsApplication.setPrefixPath("/usr", True)
    app = QgsApplication([], False)
    app.initQgis()

    # Bound any (failed) network wait so a WMS layer cannot stall the open.
    QgsSettings().setValue("qgis/networkAndProxy/networkTimeout", 3000)

    proj = QgsProject()
    read_ok = proj.read(qgz)

    layers = list(proj.mapLayers().values())
    file_layers, wms_layers = [], []
    for lyr in layers:
        prov = lyr.providerType()
        src = lyr.source().split("|")[0]         # strip OGR geometrytype suffix
        # WMS datasources are URI strings, not paths.
        rec = {"name": lyr.name(), "provider": prov, "valid": bool(lyr.isValid()),
               "authid": lyr.crs().authid()}
        if prov in ("gdal", "ogr"):
            rec["source_exists"] = os.path.exists(src)
            rec["source"] = src
            file_layers.append(rec)
        else:
            wms_layers.append(rec)

    bad_file_layers = [r for r in file_layers
                       if not r["valid"] or not r["source_exists"]]

    # ---- headless render of Site01 (fresh-env pole-truthful terrain) ------
    render = {"attempted": False, "nonblank_frac": 0.0, "png": None}
    names = ["Site01 Slope", "Site01 DEM", "Site01 Hillshade"]
    found = [proj.mapLayersByName(n) for n in names]
    if all(found):
        render["attempted"] = True
        stack = [f[0] for f in found]
        dem = proj.mapLayersByName("Site01 DEM")[0]
        ext = dem.dataProvider().extent()
        ms = QgsMapSettings()
        ms.setLayers(stack)
        ms.setDestinationCrs(QgsCoordinateReferenceSystem("IAU_2015:30135"))
        ms.setExtent(ext)
        ms.setOutputSize(QSize(512, 512))
        ms.setBackgroundColor(QColor(0, 0, 0))
        job = QgsMapRendererParallelJob(ms)
        job.start()
        job.waitForFinished()
        img = job.renderedImage()
        png = os.path.join(out_dir, "site01_cleanmachine.png")
        img.save(png)
        render["png"] = png
        nz = n = 0
        for y in range(0, img.height(), 6):
            for x in range(0, img.width(), 6):
                c = img.pixelColor(x, y)
                n += 1
                nz += (c.alpha() > 0 and (c.red() + c.green() + c.blue()) > 20)
        render["nonblank_frac"] = round(nz / n, 4) if n else 0.0

    # Detect the persisted 3D scenes in the project XML (QgsProject core does not
    # instantiate 3D views -- that is QgisApp -- but their presence is portable).
    import zipfile as _zip, re as _re
    scenes3d = 0
    try:
        with _zip.ZipFile(qgz) as z:
            qgs = [m for m in z.namelist() if m.endswith(".qgs")][0]
            xml = z.read(qgs).decode("utf-8", "replace")
        mvd = _re.search(r"<mapViewDocks3D>.*?</mapViewDocks3D>", xml, _re.S)
        scenes3d = len(_re.findall(r"<view ", mvd.group(0))) if mvd else 0
    except Exception:  # noqa: BLE001
        scenes3d = -1

    report = {
        "qgis_version": Qgis.QGIS_VERSION,
        "project_read_ok": bool(read_ok),
        "n_layers": len(layers),
        "n_file_layers": len(file_layers),
        "n_file_layers_valid": sum(1 for r in file_layers if r["valid"] and r["source_exists"]),
        "bad_file_layers": bad_file_layers,
        "wms_layers": wms_layers,
        "file_layers": file_layers,
        "render_site01": render,
        "scenes_3d_in_qgz": scenes3d,
    }
    with open(os.path.join(out_dir, "report.json"), "w") as fh:
        json.dump(report, fh, indent=2)
    print(json.dumps(report, indent=2))

    passed = (read_ok and not bad_file_layers
              and render["attempted"] and render["nonblank_frac"] > 0.9)
    sys.stdout.flush()
    os._exit(0 if passed else 1)


if __name__ == "__main__":
    main()
