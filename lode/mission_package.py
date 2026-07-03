"""[REQ:BA-11] Mission-package import/export in open-geospatial formats.

An ArcGIS-COMPATIBLE OPEN package (a directory, no proprietary format): the FR-10 typed layer manifest
(per-layer bounds/resolution/CRS + consumer eligibility), the AUTHORITY TUPLE
(body+site+mission+runtime_mode+runnable_profile+source_class+vehicle+role+command_namespace), GeoJSON
vectors (keepouts/routes/zones/targets), and STAC-style collection metadata. It ROUND-TRIPS (export->import)
with identical layer bounds/resolution/CRS and the authority tuple preserved. The DEM raster is carried as a
GeoTIFF/COG when a real raster backend (rasterio) + a DEM bundle are present, else the manifest references
it by source (honest -- never a fabricated raster). ArcGIS Feature Service is a LATER adapter (FR-12), NOT
claimed here.
"""
from __future__ import annotations

import json
import os

from stewie.contracts import LayerManifest

#: the mission authority tuple every package must carry (who/what/where the plan commands).
AUTHORITY_KEYS = ("body", "site", "mission", "runtime_mode", "runnable_profile",
                  "source_class", "vehicle", "role", "command_namespace")
PACKAGE_VERSION = "1.0"
_EMPTY_FC = {"type": "FeatureCollection", "features": []}


def export_mission_package(out_dir: str, *, world, authority: dict, transaction_id: str,
                           vectors: dict | None = None, dem_path: str | None = None) -> dict:
    """Write an open mission package to ``out_dir``: manifest.json (layer manifest + authority tuple + STAC)
    and vectors.geojson. If ``dem_path`` is a real GeoTIFF/COG it is copied in as dem.tif (the raster
    payload); otherwise the DEM is referenced by source in the manifest (never fabricated). Returns the
    manifest doc. Raises ValueError on an incomplete authority tuple."""
    import shutil

    missing = [k for k in AUTHORITY_KEYS if k not in authority]
    if missing:
        raise ValueError(f"authority tuple missing keys: {missing}")
    os.makedirs(out_dir, exist_ok=True)
    dem_raster = None
    if dem_path and os.path.isfile(dem_path):
        dem_raster = "dem.tif"
        shutil.copyfile(dem_path, os.path.join(out_dir, dem_raster))
    manifest = LayerManifest.for_world(world, transaction_id=transaction_id)
    extent_x, extent_y = world.cols * world.cell_m, world.rows * world.cell_m
    stac = {"type": "Collection", "stac_version": "1.0.0",
            "id": f"{authority['site']}:{authority['mission']}",
            "extent": {"spatial": {"bbox": [[0.0, 0.0, extent_x, extent_y]]}},
            "crs": world.frame}
    doc = {"format": "stewie-mission-package", "version": PACKAGE_VERSION,
           "authority": {k: authority[k] for k in AUTHORITY_KEYS},
           "layer_manifest": manifest.model_dump(), "stac": stac,
           "dem_raster": dem_raster, "dem_source": world.dem_source}
    with open(os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2, sort_keys=True)
    with open(os.path.join(out_dir, "vectors.geojson"), "w", encoding="utf-8") as fh:
        json.dump(vectors if vectors is not None else _EMPTY_FC, fh)
    return doc


def import_mission_package(pkg_dir: str) -> dict:
    """Read an open mission package back: the typed layer manifest, the authority tuple, STAC, and vectors."""
    with open(os.path.join(pkg_dir, "manifest.json"), encoding="utf-8") as fh:
        doc = json.load(fh)
    lm = LayerManifest.model_validate(doc["layer_manifest"])   # typed round-trip (validates the schema)
    vectors = None
    vp = os.path.join(pkg_dir, "vectors.geojson")
    if os.path.isfile(vp):
        with open(vp, encoding="utf-8") as fh:
            vectors = json.load(fh)
    dem_raster_path = None
    if doc.get("dem_raster"):
        cand = os.path.join(pkg_dir, doc["dem_raster"])
        dem_raster_path = cand if os.path.isfile(cand) else None
    return {"authority": doc["authority"], "layer_manifest": lm, "stac": doc.get("stac"),
            "vectors": vectors, "version": doc.get("version"),
            "dem_source": doc.get("dem_source"), "dem_raster_path": dem_raster_path}
