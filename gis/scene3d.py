#!/usr/bin/env python3
"""Shared authoring of the STEWIE QGIS **3D local scene** views (P1.7).

ONE source of truth for the DEM-based 3D local scenes that ``build_project.py``
persists into ``stewie_south_pole.qgz`` and that ``render_3d_proof.py`` renders
headlessly. Both import :func:`build_view_xml` so the persisted config and the
render proof describe the *identical* scene (no drift).

Why hand-authored XML instead of the PyQGIS 3D API
--------------------------------------------------
This host's QGIS is **3.22.16**, whose Python ``qgis._3d`` bindings do NOT expose
the terrain-generator classes (``QgsDemTerrainGenerator`` etc.), the offscreen 3D
engine (``QgsOffscreen3DEngine``), ``Qgs3DMapScene`` or ``Qgs3DUtils``; and
``Qgs3DMapSettings.writeXml`` **segfaults** under the headless interpreter here
(verified: exit 139 at ``writeXml``; ``readXml`` is fine). QGIS 3.22 also predates
``QgsProject.viewsManager()`` (added 3.24), so there is no clean project-level API
to persist a named 3D view headlessly.

The 3D views are therefore authored as the exact XML that QGIS Desktop 3.22 writes
and reads for a 3D map dock -- verified against the QGIS ``release-3_22`` source:

  * project element ``<mapViewDocks3D>`` -> ``<view name=...>`` children, each with
    a ``<qgis3d>`` (``Qgs3DMapSettings::writeXml``) + a direct-child ``<camera>``
    (``QgsCameraController::writeXml`` pose) + dock-geometry attributes
    (``QgisApp::writeDockWidgetSettings``);  read back by ``QgisApp`` readProject.
  * ``<qgis3d>`` -> ``<origin>``, ``<camera>``, ``<color>``, ``<crs>``,
    ``<terrain exaggeration=... elevation-offset=...>`` containing
    ``<layers><layer id=.../></layers>`` (the draped 2D layers) and
    ``<generator type="dem" layer=<demId> resolution=.. skirt-height=..>``
    (``QgsDemTerrainGenerator::writeXml``), plus ``<directional-lights>``.

``Qgs3DMapSettings::readXml`` (the code QGIS Desktop runs on open) is fully
defaulted/guarded, so the omitted optional blocks (skybox, shadows, renderers,
materials) fall back to defaults -- the scene opens cleanly.
"""
from __future__ import annotations

from xml.sax.saxutils import quoteattr

# The five 3200x3200 (5 m/px, 16 km) Artemis candidate sites get a per-site 3D
# local scene. The larger sites (Site06 4000, Site23 4200, Site42 4000) and the
# 1 m Haworth (11660x12060) are deferred from the persisted 3D config to keep
# project-open light -- QGIS opens every <view> as a live GL dock and there is no
# per-view "closed on load" flag in the 3.22 schema. See SCENE3D_DEFERRED.
SITES_3D = ["Site01", "Site04", "Site07", "Site11", "Site20"]

SCENE3D_DEFERRED = {
    "Site06": "4000x4000 (larger tile); loadable in Desktop by cloning a 3200 view",
    "Site23": "4200x4200 (largest tile)",
    "Site42": "4000x4000 (larger tile)",
    "Haworth": "1 m 11660x12060 (259 MB); needs windowing per plan risk #7 -- deferred",
}

# Vertical exaggeration for the persisted scenes. Lunar polar relief is subtle at
# a 16 km footprint; 2x is a labeled display choice (not a data claim) so the
# terrain reads in 3D. Editable per view in Desktop (Scene > Configure).
DEFAULT_EXAGGERATION = 2.0

# DEM terrain generator sampling (QGIS defaults): tile DEM resolution + skirt.
DEM_RESOLUTION = 16
DEM_SKIRT_HEIGHT = 10.0

# Terrain tile map-texture size (px) -- the drape render resolution per tile.
TEXTURE_SIZE = 512


def crs_inner_xml(crs, doc_factory) -> str:
    """Return the ``<spatialrefsys>...</spatialrefsys>`` inner XML for ``crs``.

    Uses ``QgsCoordinateReferenceSystem.writeXml`` (does NOT segfault, unlike the
    3D settings writeXml) so the 3D scene's ``<crs>`` is byte-consistent with how
    QGIS serializes this exact lunar CRS elsewhere in the project.

    ``doc_factory`` is a zero-arg callable returning a fresh ``QDomDocument`` (kept
    injectable so this module imports without PyQt).
    """
    from qgis.PyQt.QtCore import QByteArray, QTextStream
    doc = doc_factory()
    node = doc.createElement("crs")
    crs.writeXml(node, doc)
    # node now holds a <spatialrefsys> child; serialize its children (QDomNode has
    # no toString(); use QDomNode.save into a QTextStream).
    ba = QByteArray()
    stream = QTextStream(ba)
    child = node.firstChild()
    while not child.isNull():
        child.save(stream, 0)  # 0 = no extra indentation whitespace
        child = child.nextSibling()
    stream.flush()
    return bytes(ba).decode("utf-8")


def build_qgis3d_xml(dem_id: str, drape_ids: list[str], cx: float, cy: float,
                     mid_elev: float, crs_inner: str,
                     exaggeration: float = DEFAULT_EXAGGERATION) -> str:
    """The ``<qgis3d>`` Qgs3DMapSettings element for one site's DEM local scene.

    ``dem_id``    layer id whose raster drives terrain elevation (DEM generator).
    ``drape_ids`` layer ids draped as the terrain texture (top-first, matching the
                  2D stack: slope, DEM, hillshade).
    ``cx, cy``    the 3D world **origin** in IAU_2015:30135 metres (the DEM centre)
                  so terrain sits near world 0 for float precision (QGIS pattern).
    ``mid_elev``  mid elevation (m) -- only used by the camera in build_view_xml.
    """
    layers_xml = "".join(f'<layer id={quoteattr(i)}/>' for i in drape_ids)
    # <point-lights> is intentionally omitted: Qgs3DMapSettings::readXml inserts a
    # default overhead point light when the element is absent, which lights the
    # terrain (the drape already carries baked hillshade relief). A directional
    # light is added for oblique shading.
    return (
        '<qgis3d>'
        f'<origin x="{cx:.6f}" y="{cy:.6f}" z="0"/>'
        '<camera field-of-view="45" projection-type="1" '
        'camera-navigation-mode="terrain-based-navigation" camera-movement-speed="5"/>'
        '<color background="0,0,0,255" selection="255,255,0,255"/>'
        f'<crs>{crs_inner}</crs>'
        f'<terrain terrain-rendering-enabled="1" exaggeration="{exaggeration:g}" '
        f'texture-size="{TEXTURE_SIZE}" max-terrain-error="3" max-ground-error="1" '
        'shading-enabled="0" elevation-offset="0" map-theme="" show-labels="0">'
        f'<layers>{layers_xml}</layers>'
        f'<generator type="dem" layer={quoteattr(dem_id)} '
        f'resolution="{DEM_RESOLUTION}" skirt-height="{DEM_SKIRT_HEIGHT:g}"/>'
        '</terrain>'
        '<directional-lights>'
        '<directional-light x="0.5" y="-1" z="-0.3" '
        'color="255,255,255,255" intensity="0.9"/>'
        '</directional-lights>'
        '</qgis3d>'
    )


def camera_pose(cx: float, cy: float, mid_elev: float, width: float, height: float):
    """(centre_world, distance, pitch_deg, yaw_deg) framing the whole site obliquely.

    Terrain world origin is the DEM centre (cx,cy), so the site centre is world
    (0, mid_elev, 0). Distance frames the full footprint at a 45 deg oblique tilt.
    """
    dist = 1.6 * max(width, height)
    return (0.0, mid_elev, 0.0), dist, 45.0, 0.0


def build_view_xml(name: str, dem_id: str, drape_ids: list[str],
                   cx: float, cy: float, mid_elev: float,
                   width: float, height: float, crs_inner: str,
                   exaggeration: float = DEFAULT_EXAGGERATION) -> str:
    """One ``<view>`` (a 3D map dock) for the ``<mapViewDocks3D>`` project element."""
    qgis3d = build_qgis3d_xml(dem_id, drape_ids, cx, cy, mid_elev, crs_inner,
                              exaggeration)
    (_wx, _wy, _wz), dist, pitch, yaw = camera_pose(cx, cy, mid_elev, width, height)
    # <camera> as a DIRECT child of <view> is the QgsCameraController pose:
    #   x=centre.x  y=centre.z  elev=centre.y  (see QgsCameraController::writeXml)
    camera = (f'<camera x="{_wx:g}" y="{_wz:g}" elev="{_wy:g}" '
              f'dist="{dist:.3f}" pitch="{pitch:g}" yaw="{yaw:g}"/>')
    return (
        f'<view name={quoteattr(name)} x="80" y="80" width="1000" height="780" '
        'floating="1" area="1">'
        f'{qgis3d}{camera}'
        '</view>'
    )


def build_mapviewdocks3d_xml(views_xml: list[str]) -> str:
    """Wrap the per-site ``<view>`` blocks in the project ``<mapViewDocks3D>`` element."""
    return "<mapViewDocks3D>" + "".join(views_xml) + "</mapViewDocks3D>"
