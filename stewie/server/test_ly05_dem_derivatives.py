"""[REQ:LY-05] DEM-derivative analysis rasters: aspect, curvature, roughness + contours.

Asserts the aspect + curvature VALUES against a REAL LOLA Haworth DEM crop (no synthetic data): the
gradient-azimuth field points downhill on the real terrain, and the Laplacian-curvature field carries the
right concave/convex sign on the real terrain. Then asserts each new globe kind renders a non-degenerate
PNG via the public render path (/layers/globe/{kind}.png + /bbox), that roughness reuses the ONE lode
source of truth, that the legend carries the three entries, and that the contours endpoint is a real
GeoJSON vector product whose vertices land in the site footprint.
"""
import io

import numpy as np
import pytest
from fastapi.testclient import TestClient

from lode import mission_planner as mp
from stewie.server.gis_layers import (
    _roughness_rgba, aspect_deg, contour_geojson, curvature_laplacian,
)
from stewie.server.server import app


@pytest.fixture(scope="module")
def real_crop():
    """A REAL 200x200 crop of the LOLA Haworth 5 m DEM with genuine relief (subsampled real bundle,
    samples/lunar_dem/haworth_10km_5m) -- never synthetic."""
    dem, cell = mp.load_haworth_dem()
    crop = np.asarray(dem[850:1050, 850:1050], dtype=float)
    assert crop.shape == (200, 200) and float(crop.std()) > 1.0   # real relief present
    return crop, float(cell)


def test_aspect_values_point_downhill_on_real_dem(real_crop):  # [REQ:LY-05]
    crop, cell = real_crop
    asp = aspect_deg(crop, cell)
    # in range, cyclic azimuth, and non-degenerate (a real crop faces many directions)
    assert asp.shape == crop.shape
    assert float(asp.min()) >= 0.0 and float(asp.max()) < 360.0
    assert float(asp.max()) - float(asp.min()) > 45.0
    # reference-equivalence: the aspect field IS atan2(-dz/dcol, dz/drow) of the SAME gradient (no sign flip)
    gy, gx = np.gradient(crop, cell)
    ref = np.degrees(np.arctan2(-gx, gy)) % 360.0
    assert np.allclose(asp, ref)
    # PHYSICAL check on real terrain: stepping ~1.5 cells along the aspect (downhill) azimuth lands on
    # LOWER ground for essentially every interior cell with real slope. grid-north = -row, east = +col.
    slope = np.degrees(np.arctan(np.hypot(gx, gy)))
    H, W = crop.shape
    rr, cc = np.mgrid[0:H, 0:W]
    a = np.radians(asp)
    r2 = np.clip(np.round(rr - 1.5 * np.cos(a)).astype(int), 0, H - 1)
    c2 = np.clip(np.round(cc + 1.5 * np.sin(a)).astype(int), 0, W - 1)
    interior = (rr >= 3) & (rr < H - 3) & (cc >= 3) & (cc < W - 3) & (slope > 2.0)
    frac_downhill = float(np.mean(crop[r2, c2][interior] < crop[interior]))
    assert frac_downhill > 0.9, f"aspect should point downhill on the real DEM (got {frac_downhill:.3f})"


def test_curvature_values_have_correct_sign_on_real_dem(real_crop):  # [REQ:LY-05]
    crop, cell = real_crop
    lap = curvature_laplacian(crop, cell)
    assert lap.shape == crop.shape
    # reference-equivalence: Laplacian = d2z/dx2 + d2z/dy2 of the SAME gradient
    gy, gx = np.gradient(crop, cell)
    gyy, _ = np.gradient(gy, cell)
    _, gxx = np.gradient(gx, cell)
    assert np.allclose(lap, gxx + gyy)
    assert float(np.nanstd(lap)) > 0.0   # non-degenerate on real terrain
    # PHYSICAL sign convention on real terrain: concave-up hollows (cell BELOW its neighbours) are POSITIVE,
    # convex-up mounds (cell ABOVE its neighbours) are NEGATIVE. rel = center - neighbour-mean is >0 at
    # mounds, <0 at hollows, so it must correlate STRONGLY NEGATIVELY with the Laplacian.
    from scipy.ndimage import uniform_filter
    nbr_mean = (uniform_filter(crop, size=3, mode="nearest") * 9.0 - crop) / 8.0
    rel = crop - nbr_mean
    H, W = crop.shape
    rr, cc = np.mgrid[0:H, 0:W]
    ii = (rr >= 2) & (rr < H - 2) & (cc >= 2) & (cc < W - 2)
    corr = float(np.corrcoef(lap[ii].ravel(), rel[ii].ravel())[0, 1])
    assert corr < -0.5, f"curvature sign must match concave(+)/convex(-) on the real DEM (corr {corr:.3f})"
    # the crop's global-interior low point is concave-up (+), its high point convex-up (-)
    z_i = np.where(ii, crop, np.nan)
    imin = np.unravel_index(np.nanargmin(z_i), z_i.shape)
    imax = np.unravel_index(np.nanargmax(z_i), z_i.shape)
    assert float(lap[imin]) > 0.0 and float(lap[imax]) < 0.0


def test_roughness_reuses_the_lode_source_of_truth(real_crop):  # [REQ:LY-05]
    """The roughness drape must colour the SAME window-RMS-slope field lode.costmap_layers._roughness
    computes (one source of truth) -- not a private reimplementation."""
    crop, cell = real_crop
    from lode.costmap_layers import CostmapContext
    from lode.costmap_layers import _roughness as lode_roughness
    rough, _mask, name = lode_roughness(CostmapContext(Z=crop, cell_m=cell))
    assert name == "roughness" and float(np.asarray(rough).std()) > 0.0
    # the drape renders a non-degenerate RGBA from exactly that field
    rgba = _roughness_rgba(crop, cell)
    assert rgba.shape == (200, 200, 4) and rgba.dtype == np.uint8
    assert int(rgba[..., :3].std()) > 0
    # higher roughness -> higher opacity (the ramp is monotone in the lode field): the roughest cell is
    # at least as opaque as the smoothest.
    r = np.asarray(rough)
    lo = np.unravel_index(int(np.argmin(r)), r.shape)
    hi = np.unravel_index(int(np.argmax(r)), r.shape)
    assert rgba[hi][3] >= rgba[lo][3]


@pytest.mark.parametrize("kind", ["aspect", "curvature", "roughness"])
def test_new_globe_kinds_render_nondegenerate_png_and_bbox(kind):  # [REQ:LY-05]
    """Each new kind renders a real, non-degenerate PNG via /layers/globe/{kind}.png and carries a bbox
    on a real site (haworth)."""
    c = TestClient(app, base_url="http://127.0.0.1")
    r = c.get(f"/layers/globe/{kind}.png", params={"site": "haworth"})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "image/png"
    from PIL import Image
    im = Image.open(io.BytesIO(r.content)).convert("RGBA")
    assert im.size[0] > 8 and im.size[1] > 8
    arr = np.asarray(im)
    visible = arr[arr[..., 3] > 0]
    assert visible.shape[0] > 0, "drape rendered fully transparent"
    assert len(np.unique(visible[:, :3].reshape(-1, 3), axis=0)) > 1, "drape is a single flat colour"
    b = c.get(f"/layers/globe/{kind}/bbox", params={"site": "haworth"})
    assert b.status_code == 200, b.text
    bj = b.json()
    assert bj["ok"] and bj["south"] < bj["north"] and bj["west"] < bj["east"]
    assert bj["north"] <= -85.0     # a real south-polar Haworth tile


def test_legend_carries_the_ly05_entries():  # [REQ:LY-05]
    c = TestClient(app, base_url="http://127.0.0.1")
    j = c.get("/layers/legend").json()
    for kind in ("aspect", "curvature", "roughness"):
        assert kind in j, f"legend missing {kind}"
        assert j[kind]["ramp"] and j[kind]["text"]
    # the curvature legend states its definition + sign convention; roughness names the one source of truth
    assert "∇²z" in j["curvature"]["ramp"] or "Laplacian" in j["curvature"]["text"]
    assert "_roughness" in j["roughness"]["text"]


def test_unknown_kind_still_404s():  # [REQ:LY-05] the allow-list stays closed
    c = TestClient(app, base_url="http://127.0.0.1")
    assert c.get("/layers/globe/not_a_kind.png", params={"site": "haworth"}).status_code == 404


def test_contours_geojson_is_a_real_vector_product():  # [REQ:LY-05]
    """Contours are a REAL vector product: contourpy isolines of the real DEM at a stated interval,
    reprojected to selenographic lon/lat, in the Haworth footprint. Display-only in the LY-01 catalog."""
    fc = contour_geojson("haworth", 100.0)
    assert fc["type"] == "FeatureCollection"
    p = fc["properties"]
    assert p["interval_m"] == 100.0 and p["crs"] == "OGC:CRS84"
    assert p["levels"] >= 5 and p["vertices"] > 100 and not p["truncated"]
    assert "display-only" in p["eligibility"]
    # every feature is a MultiLineString whose vertices land in the real Haworth lon/lat footprint
    lons, lats = [], []
    for f in fc["features"]:
        assert f["geometry"]["type"] == "MultiLineString"
        assert isinstance(f["properties"]["elevation_m"], float)
        for line in f["geometry"]["coordinates"]:
            assert len(line) >= 2
            for lon, lat in line:
                lons.append(lon); lats.append(lat)
    assert min(lats) > -87.0 and max(lats) < -85.5      # Haworth ~ -86.5..-86.1
    assert -31.0 < min(lons) and max(lons) < -20.0      # Haworth ~ -29..-22
    # elevation levels are stepped by the stated interval
    elevs = sorted({f["properties"]["elevation_m"] for f in fc["features"]})
    assert all(abs((elevs[i + 1] - elevs[i]) - 100.0) < 1e-6 for i in range(len(elevs) - 1))


def test_contours_endpoint_serves_geojson():  # [REQ:LY-05]
    c = TestClient(app, base_url="http://127.0.0.1")
    r = c.get("/layers/contours.geojson", params={"site": "haworth", "interval": 200.0})
    assert r.status_code == 200, r.text
    assert "geo+json" in r.headers["content-type"]
    fc = r.json()
    assert fc["type"] == "FeatureCollection" and fc["properties"]["interval_m"] == 200.0
    assert len(fc["features"]) >= 3
    # an unknown site 404s (the DEM bundle resolve raises)
    assert c.get("/layers/contours.geojson", params={"site": "nope_not_a_site"}).status_code == 404
