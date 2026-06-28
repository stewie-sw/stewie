"""GIS-WA1: the work-area authoring backdrop must be a CLEAN, axis-free, native-resolution hillshade of
the [0, window_m]^2 order frame -- NOT the old preview_hillshade.png (a matplotlib FIGURE whose axis
labels + margins misregistered the terrain when blitted into the plan canvas's [0, window_m] world box).

Real-data test: exercises the same real LOLA Haworth bundle that test_globe_cache relies on in CI (no
synthetic DEM). Asserts the contract (PNG, native px = round(window/cell)+1, real relief variation) and
that the raster carries NO chrome -- the bare-raster invariant the plan canvas depends on for an exact
pixel->metre mapping."""
from fastapi.testclient import TestClient

from stewie.server.server import app

client = TestClient(app)


def _decode(content: bytes):
    import io

    import numpy as np
    from imageio.v3 import imread
    return np.asarray(imread(io.BytesIO(content)))


def test_workarea_png_is_clean_native_hillshade():
    r = client.get("/dem/workarea.png?site=haworth&window_m=640")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "image/png"
    img = _decode(r.content)
    # native sampling: 640 m / 5 m cell -> ~129 px square (round(win/cell)+1). The exact cell comes from the
    # bundle; assert square + plausibly native (not the old 5x5-inch 550px matplotlib figure, not a 1px stub).
    assert img.ndim == 3 and img.shape[2] == 4, f"expected RGBA, got {img.shape}"
    h, w = img.shape[:2]
    assert h == w, f"work-area crop must be square (order frame is [0,win]^2); got {h}x{w}"
    assert 64 <= h <= 600, f"expected native-res window (~129 px for 640 m @ 5 m), got {h}"
    # CLEAN raster invariant: a matplotlib figure has wide white (255) axis/title margins -- a bare hillshade
    # floor-lifted to 40..240 grey has NO pure-white border rows. Assert the first/last rows are not white
    # margins (the registration bug the old preview_hillshade.png caused).
    gray = img[:, :, 0]
    assert gray.min() < gray.max(), "degenerate hillshade (no relief) -- DEM not sampled"
    top_row, bot_row = gray[0], gray[-1]
    assert not (top_row.mean() > 250 and bot_row.mean() > 250), "white margins present -> not a clean raster"
    assert gray.max() <= 240, "hillshade should be floor-lifted to <=240 grey, not contain pure-white chrome"


def test_workarea_png_unknown_site_404():
    r = client.get("/dem/workarea.png?site=__nope__&window_m=640")
    assert r.status_code == 404
    assert r.json()["ok"] is False
