"""P1.8 headless QGIS Server acceptance tests (gate 2, server side).

Proves the SAME ``stewie_south_pole.qgz`` that QGIS Desktop renders also renders
server-side, pole-truthfully, in ``IAU_2015:30135`` -- the "one project, two clients"
promise. These are *live-server* tests: they SKIP cleanly (never fail) when no QGIS
Server is reachable, and they subsample the REAL on-disk lunar project (no synthetic
data, no fixtures).

Run against either published endpoint stood up in ``SERVER.md``:
  * host ``qgis_mapserver`` (project pinned, no MAP arg)   -> http://127.0.0.1:8081/
  * Docker ``qgis/qgis-server`` (MAP arg required)         -> http://127.0.0.1:8082/ows/

Discovery order: ``$STEWIE_QGIS_SERVER`` (an explicit base URL, MAP appended if the
path contains ``/ows``), then the two defaults above. The first endpoint that answers
a GetCapabilities listing the project's Site01 layer is used; otherwise every test
skips.

Gate references: STEWIE_QGIS_PIVOT_PLAN_2026-07-05.md P1.8 / "P1 acceptance gate" item 2.
"""
from __future__ import annotations

import io
import os
import urllib.parse
import urllib.request

import pytest

# Pillow is the only hard test dependency (decode the returned PNG). Skip the whole
# module -- rather than error -- where it is absent, per the STEWIE test-guard rule.
Image = pytest.importorskip("PIL.Image", reason="Pillow required to decode GetMap PNGs")

# Site01 DEM footprint in IAU_2015:30135 metres (gdalinfo cog/Site01/dem.tif): a 16 km
# square centred at 89 deg 27' S. This is the exact extent QGIS Desktop's
# proof/site01_render.png used (build_project.py render_site -> dem.extent()).
SITE01_BBOX_30135 = (-19000.0, -20000.0, -3000.0, -4000.0)  # minx, miny, maxx, maxy
PROJECT_MAP_PATH = "/io/data/code/gis/stewie_south_pole.qgz"  # in-container path (Docker lane)

_CANDIDATES = [
    # (base_url, needs_map): host qgis_mapserver pins the project via -p, so no MAP arg.
    ("http://127.0.0.1:8081/", False),
    # Docker qgis-server routes via nginx /ows/ and needs an explicit MAP arg.
    ("http://127.0.0.1:8082/ows/", True),
]


def _wms_url(base: str, needs_map: bool, params: dict) -> str:
    q = {"SERVICE": "WMS", "VERSION": "1.3.0", **params}
    if needs_map:
        q = {"MAP": PROJECT_MAP_PATH, **q}
    return base + "?" + urllib.parse.urlencode(q)


def _get(url: str, timeout: float = 60.0) -> tuple[int, bytes, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.getcode(), r.read(), r.headers.get_content_type()
    except Exception:  # noqa: BLE001 -- any transport error means "no server", -> skip
        return 0, b"", ""


def _discover() -> tuple[str, bool] | None:
    """Return (base_url, needs_map) for the first endpoint whose GetCapabilities lists
    Site01, or None if none is reachable."""
    override = os.environ.get("STEWIE_QGIS_SERVER")
    candidates = list(_CANDIDATES)
    if override:
        candidates.insert(0, (override, "/ows" in override))
    for base, needs_map in candidates:
        url = _wms_url(base, needs_map, {"REQUEST": "GetCapabilities"})
        code, body, _ = _get(url, timeout=90.0)
        if code == 200 and b"Site01 DEM" in body:
            return base, needs_map
    return None


@pytest.fixture(scope="module")
def endpoint():
    ep = _discover()
    if ep is None:
        pytest.skip(
            "no QGIS Server reachable (start one per gis/SERVER.md, or set "
            "$STEWIE_QGIS_SERVER); server tests are live-only by design"
        )
    return ep


def test_getcapabilities_lists_project_layers(endpoint):
    """Gate 2: GetCapabilities advertises the project's real layers in IAU_2015:30135."""
    base, needs_map = endpoint
    url = _wms_url(base, needs_map, {"REQUEST": "GetCapabilities"})
    code, body, _ = _get(url)
    assert code == 200
    text = body.decode("utf-8", "replace")
    # The authoritative on-disk terrain layers must be published...
    for name in ("Site01 DEM", "Site01 Hillshade", "Site01 Slope"):
        assert f"<Name>{name}</Name>" in text, f"layer {name!r} not in GetCapabilities"
    # ...and the lunar south-polar CRS must be an offered CRS (pole-truthful server render).
    assert "IAU_2015:30135" in text, "project CRS IAU_2015:30135 not advertised"


def test_getmap_site01_nonblank_correct_size(endpoint):
    """Gate 2: a GetMap of Site01 in IAU_2015:30135 returns a non-blank PNG of the
    requested size (real pole-truthful terrain, not an empty frame)."""
    base, needs_map = endpoint
    w = h = 512
    minx, miny, maxx, maxy = SITE01_BBOX_30135
    url = _wms_url(
        base,
        needs_map,
        {
            "REQUEST": "GetMap",
            # WMS draws first-listed at the bottom: Hillshade -> DEM -> Slope on top,
            # matching QGIS Desktop's setLayers([Slope, DEM, Hillshade]) stack.
            "LAYERS": "Site01 Hillshade,Site01 DEM,Site01 Slope",
            "STYLES": "",
            "CRS": "IAU_2015:30135",
            "BBOX": f"{minx},{miny},{maxx},{maxy}",
            "WIDTH": str(w),
            "HEIGHT": str(h),
            "FORMAT": "image/png",
            "BGCOLOR": "0x000000",
            "TRANSPARENT": "FALSE",
        },
    )
    code, body, ctype = _get(url)
    assert code == 200, f"GetMap HTTP {code}"
    assert ctype == "image/png", f"GetMap returned {ctype!r}, not a PNG (likely a ServiceException)"

    im = Image.open(io.BytesIO(body)).convert("RGB")
    assert im.size == (w, h), f"GetMap size {im.size} != requested {(w, h)}"

    # Non-blank: Site01 fills the frame, so almost every pixel is lit. Count pixels whose
    # summed RGB clears a small black threshold (matches build_project._nonblank_frac).
    px = im.load()
    lit = sum(
        1
        for y in range(0, h, 4)
        for x in range(0, w, 4)
        if (lambda r, g, b: r + g + b > 12)(*px[x, y])
    )
    total = len(range(0, h, 4)) * len(range(0, w, 4))
    frac = lit / total
    assert frac > 0.9, f"GetMap is mostly blank (non-black frac {frac:.3f}); Site01 should fill the frame"
