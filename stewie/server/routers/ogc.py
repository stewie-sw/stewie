"""ArcGIS-G1 (#248): an OGC WMS 1.3.0 service over STEWIE's already-rendered globe layers, so any
QGIS/ArcGIS client can consume them. GetCapabilities advertises the 7 globe layers + their
selenographic extent; GetMap honours an arbitrary BBOX/WIDTH/HEIGHT (real subsetting -- a crop +
resample of the geographic drape, not always-full-extent) in CRS84 or EPSG:4326.

Auth posture: PUBLIC + per-IP rate-limited, SHARING the globe drape's limiter (globe_quota). The WMS
exposes the SAME public base-map data the drape does (GIS-03: a base map you cannot see is worse than
the DoS the rate-limit already covers), so it follows the drape's posture, NOT #246's operational-data
gate. The lunar CRS is declared honestly (IAU_2015:30100, the geodetic CRS of the :30135 drape); CRS84
is also offered so axis order is unambiguous (EPSG:4326 in WMS 1.3.0 is lat,lon)."""
from __future__ import annotations

import html

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from stewie.server.routers.layers import _GLOBE_KINDS, globe_quota

router = APIRouter()

_LUNAR_GEOG = "IAU_2015:30100"          # Moon (2015) ocentric sphere -- the geographic CRS of the drape
_MAX_PX = 4096                          # per-dimension GetMap bound (a multi-GB render is a DoS)
_MAX_TOTAL_PX = 2048 * 2048             # #288: total pixel-AREA budget. The per-dimension cap alone lets
#                                         4096x4096 through (each <=4096) yet that builds ~7 float64 WxH
#                                         meshgrids (~1 GB) on this PUBLIC, only IP-rate-limited route.
_SE_MIME = "application/vnd.ogc.se_xml"  # WMS ServiceExceptionReport media type


def _service_exception(msg: str, code: str = "InvalidParameterValue", status: int = 400) -> Response:
    body = ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<ServiceExceptionReport version="1.3.0" xmlns="http://www.opengis.net/ogc">\n'
            f'  <ServiceException code="{html.escape(code)}">{html.escape(msg)}</ServiceException>\n'
            '</ServiceExceptionReport>\n')
    return Response(content=body, media_type=_SE_MIME, status_code=status)


def _ci(params: dict, key: str, default: str | None = None) -> str | None:
    """Case-insensitive KVP lookup (WMS request keys are case-insensitive)."""
    for k, v in params.items():
        if k.lower() == key.lower():
            return v
    return default


def _self_url(request: Request) -> str:
    """The WMS endpoint URL for OnlineResource hrefs, honouring a reverse proxy's forwarded scheme/host
    (STEWIE serves behind Cloudflare -> cloudflared)."""
    proto = request.headers.get("x-forwarded-proto")
    host = request.headers.get("x-forwarded-host") or request.headers.get("host")
    if proto and host:
        return f"{proto}://{host}/ogc/wms"
    return str(request.url_for("wms"))


@router.get("/ogc/wms", name="wms")
def wms(request: Request, _auth: str = Depends(globe_quota)) -> Response:
    p = dict(request.query_params)
    req = (_ci(p, "REQUEST") or "").lower()
    svc = (_ci(p, "SERVICE") or "WMS").upper()
    if svc != "WMS":
        return _service_exception(f"unsupported SERVICE {svc!r}; this endpoint is WMS",
                                  code="InvalidParameterValue")
    if req == "getcapabilities":
        return _capabilities(request, p)
    if req == "getmap":
        return _getmap(request, p)
    return _service_exception(
        f"unsupported REQUEST {_ci(p, 'REQUEST')!r}; expected GetCapabilities or GetMap",
        code="OperationNotSupported")


def _capabilities(request: Request, p: dict) -> Response:
    import stewie.server.gis_layers as G
    site = _ci(p, "site", "haworth") or "haworth"
    try:
        bb = G.geographic_bbox(site)
    except (KeyError, FileNotFoundError) as e:
        return _service_exception(f"unknown site {site!r}: {e}", code="InvalidParameterValue", status=404)
    href = html.escape(_self_url(request))
    w, e_, s, n = bb["west"], bb["east"], bb["south"], bb["north"]

    def _layer(kind: str) -> str:
        return (
            f'      <Layer queryable="0">\n'
            f'        <Name>{kind}</Name>\n'
            f'        <Title>STEWIE {kind} (globe drape)</Title>\n'
            f'        <CRS>CRS:84</CRS><CRS>EPSG:4326</CRS><CRS>{_LUNAR_GEOG}</CRS>\n'
            f'        <EX_GeographicBoundingBox>\n'
            f'          <westBoundLongitude>{w:.6f}</westBoundLongitude>\n'
            f'          <eastBoundLongitude>{e_:.6f}</eastBoundLongitude>\n'
            f'          <southBoundLatitude>{s:.6f}</southBoundLatitude>\n'
            f'          <northBoundLatitude>{n:.6f}</northBoundLatitude>\n'
            f'        </EX_GeographicBoundingBox>\n'
            f'        <BoundingBox CRS="CRS:84" minx="{w:.6f}" miny="{s:.6f}" maxx="{e_:.6f}" maxy="{n:.6f}"/>\n'
            f'      </Layer>\n')

    layers = "".join(_layer(k) for k in _GLOBE_KINDS)
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<WMS_Capabilities version="1.3.0" xmlns="http://www.opengis.net/wms" '
        'xmlns:xlink="http://www.w3.org/1999/xlink">\n'
        '  <Service>\n'
        '    <Name>WMS</Name>\n'
        '    <Title>STEWIE lunar globe layers</Title>\n'
        '    <Abstract>Selenographic drape of the STEWIE digital-twin globe layers (south-polar Moon, '
        'IAU_2015:30100). Coordinates are SELENOGRAPHIC lat/lon; CRS:84 and the IAU lunar CRS are '
        'authoritative. EPSG:4326 is offered only as a numeric (lat/lon-degree) convenience alias for '
        'clients that require it -- the datum is the Moon, NOT WGS84 Earth. Base-map data; SIM/analysis '
        'products are separate.</Abstract>\n'
        f'    <OnlineResource xlink:type="simple" xlink:href="{href}"/>\n'
        '  </Service>\n'
        '  <Capability>\n'
        '    <Request>\n'
        '      <GetCapabilities><Format>text/xml</Format>\n'
        f'        <DCPType><HTTP><Get><OnlineResource xlink:type="simple" xlink:href="{href}"/></Get></HTTP></DCPType>\n'
        '      </GetCapabilities>\n'
        '      <GetMap><Format>image/png</Format>\n'
        f'        <DCPType><HTTP><Get><OnlineResource xlink:type="simple" xlink:href="{href}"/></Get></HTTP></DCPType>\n'
        '      </GetMap>\n'
        '    </Request>\n'
        '    <Exception><Format>XML</Format></Exception>\n'
        '    <Layer>\n'
        '      <Title>STEWIE globe layers</Title>\n'
        f'      <CRS>CRS:84</CRS><CRS>EPSG:4326</CRS><CRS>{_LUNAR_GEOG}</CRS>\n'
        f'      <EX_GeographicBoundingBox>\n'
        f'        <westBoundLongitude>{w:.6f}</westBoundLongitude>\n'
        f'        <eastBoundLongitude>{e_:.6f}</eastBoundLongitude>\n'
        f'        <southBoundLatitude>{s:.6f}</southBoundLatitude>\n'
        f'        <northBoundLatitude>{n:.6f}</northBoundLatitude>\n'
        f'      </EX_GeographicBoundingBox>\n'
        f'{layers}'
        '    </Layer>\n'
        '  </Capability>\n'
        '</WMS_Capabilities>\n')
    return Response(content=xml, media_type="text/xml")


def _getmap(request: Request, p: dict) -> Response:
    import numpy as np

    import stewie.server.gis_layers as G
    ver = _ci(p, "VERSION")
    if ver and ver != "1.3.0":                               # M1/M2: 1.3.0-only -> no 1.1.x axis-order ambiguity
        return _service_exception(f"version {ver!r} not supported; this service is WMS 1.3.0",
                                  code="InvalidParameterValue")
    layers = [s.strip() for s in (_ci(p, "LAYERS") or "").split(",") if s.strip()]
    if len(layers) > 1:                                      # M3: do not silently drop -- we do not composite
        return _service_exception("multiple LAYERS not supported; request one layer per GetMap",
                                  code="InvalidParameterValue")
    kind = layers[0] if layers else ""
    if kind not in _GLOBE_KINDS:
        return _service_exception(f"layer {kind!r} is not defined", code="LayerNotDefined")
    fmt = (_ci(p, "FORMAT") or "image/png").lower()
    if fmt not in ("image/png", "image/png; mode=8bit"):
        return _service_exception(f"format {fmt!r} not supported; only image/png", code="InvalidFormat")
    # WIDTH/HEIGHT: positive ints, bounded so a giant request cannot force a multi-GB render.
    try:
        width = int(_ci(p, "WIDTH") or "")
        height = int(_ci(p, "HEIGHT") or "")
    except ValueError:
        return _service_exception("WIDTH and HEIGHT must be integers")
    if not (1 <= width <= _MAX_PX and 1 <= height <= _MAX_PX):
        return _service_exception(f"WIDTH/HEIGHT must be in [1,{_MAX_PX}]")
    if width * height > _MAX_TOTAL_PX:   # #288: bound the AREA too (per-dim cap alone allows a ~1 GB 4096x4096)
        return _service_exception(f"WIDTH*HEIGHT must be <= {_MAX_TOTAL_PX} pixels "
                                  f"(got {width}x{height}={width * height})")
    # BBOX axis order: CRS84 is lon,lat; EPSG:4326 / the lunar geographic CRS are lat,lon in WMS 1.3.0.
    crs = (_ci(p, "CRS") or "CRS:84").upper().replace("OGC:", "")   # WMS 1.3.0 uses CRS, not 1.1.x SRS
    try:
        v = [float(x) for x in (_ci(p, "BBOX") or "").split(",")]
        if len(v) != 4:
            raise ValueError
    except ValueError:
        return _service_exception("BBOX must be four comma-separated numbers")
    if "CRS84" in crs.replace(":", ""):
        west, south, east, north = v
    elif "4326" in crs or "30100" in crs:                    # WMS 1.3.0 geographic axis order = lat,lon
        south, west, north, east = v
    else:
        return _service_exception(f"CRS {crs!r} not supported; use CRS:84, EPSG:4326, or {_LUNAR_GEOG}",
                                  code="InvalidCRS")
    if not (east > west and north > south):
        return _service_exception("degenerate BBOX (need west<east and south<north)")

    site = _ci(p, "site", "haworth") or "haworth"
    try:
        src, sb = G.render_globe(kind, site=site)
    except (KeyError, FileNotFoundError) as e:
        return _service_exception(f"layer {kind!r} unavailable for site {site!r}: {e}",
                                  code="LayerNotDefined", status=404)

    # Crop + resample the geographic (lat/lon, north-up) drape onto the requested WIDTH x HEIGHT window.
    lon = np.linspace(west, east, width)
    lat = np.linspace(north, south, height)                  # row 0 = north (top)
    lon_g, lat_g = np.meshgrid(lon, lat)
    sh, sw = src.shape[:2]
    col = (lon_g - sb["west"]) / (sb["east"] - sb["west"]) * (sw - 1)
    row = (sb["north"] - lat_g) / (sb["north"] - sb["south"]) * (sh - 1)
    valid = (col >= 0) & (col <= sw - 1) & (row >= 0) & (row <= sh - 1)
    ci = np.clip(np.round(col).astype(int), 0, sw - 1)
    ri = np.clip(np.round(row).astype(int), 0, sh - 1)
    out = src[ri, ci].astype("uint8")
    out[~valid] = 0                                          # transparent outside the tile footprint
    return Response(content=G._to_png(out), media_type="image/png")
