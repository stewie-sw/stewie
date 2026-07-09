"""[systems-eng] Cache-Control policy for the keyless public /ide GETs.

DYNAMIC world/planner reads must carry ``no-store`` (a stale cache would show wrong world/planner state);
STATIC LOLA-DEM-derived products must carry a short ``public, max-age`` and must NOT be no-store (no-store
would kill the viz -- a ~16 MB heightfield re-fetched every load). The one nuance verified here: the
``traffic`` drape is DYNAMIC (per-site TrafficMemory, mutates as runs fold) while ``cost``/``blocking`` are
DEM+sun-only -> static.

Real data: hits the app's real routes on the ``haworth`` LOLA bundle (no synthetic data); the pure-policy
tests exercise ``cache_control.classify`` directly, which needs no server.
"""
from fastapi.testclient import TestClient

from stewie.server import cache_control as CC
from stewie.server.server import app

client = TestClient(app)

# The two public classes, from the module's own tables (kept in one place so the test can't drift from policy).
DYNAMIC_PATHS = sorted(CC.NO_STORE_PATHS)
STATIC_PATHS = sorted(CC.STATIC_EXACT_PATHS)


# --------------------------------------------------------------------------------------------------------
# Pure policy table (no server): exhaustive, deterministic, DEM-independent.
# --------------------------------------------------------------------------------------------------------
def test_classify_every_dynamic_world_path_is_no_store_overwrite():
    for p in DYNAMIC_PATHS:
        assert CC.classify(p) == ("no-store", True), p


def test_classify_every_static_exact_path_is_public_maxage_setdefault():
    for p in STATIC_PATHS:
        value, overwrite = CC.classify(p)
        assert value == CC.STATIC_MAX_AGE, p
        assert value.startswith("public, max-age="), p
        assert "no-store" not in value, p
        assert overwrite is False, p          # setdefault so a route's own longer max-age survives


def test_classify_globe_png_kind_split_traffic_dynamic_rest_static():
    # cost/blocking are DEM+sun-only (static); traffic reads the mutable TrafficMemory (dynamic).
    for static_kind in ("dem", "slope", "hazard", "cost", "blocking", "psr", "roughness"):
        assert CC.classify(f"/layers/globe/{static_kind}.png") == (CC.STATIC_MAX_AGE, False), static_kind
    assert CC.classify("/layers/globe/traffic.png") == ("no-store", True)


def test_classify_globe_bbox_is_static_footprint_regardless_of_kind():
    for k in ("dem", "cost", "traffic"):
        assert CC.classify(f"/layers/globe/{k}/bbox") == (CC.STATIC_MAX_AGE, False), k


def test_classify_layerpng_and_wms_are_kind_aware():
    class _Q(dict):
        pass
    # /dem/heightfield_full/layer.png -- kind is a query param (route reads lowercase `kind`, default dem).
    assert CC.classify("/dem/heightfield_full/layer.png", _Q(kind="dem")) == (CC.STATIC_MAX_AGE, False)
    assert CC.classify("/dem/heightfield_full/layer.png", _Q(kind="cost")) == (CC.STATIC_MAX_AGE, False)
    assert CC.classify("/dem/heightfield_full/layer.png", _Q(kind="traffic")) == ("no-store", True)
    assert CC.classify("/dem/heightfield_full/layer.png", _Q()) == (CC.STATIC_MAX_AGE, False)  # default dem
    # /ogc/wms -- LAYERS is case-insensitive (mirrors the route's _ci); GetCapabilities (no LAYERS) is static.
    assert CC.classify("/ogc/wms", _Q(LAYERS="dem")) == (CC.STATIC_MAX_AGE, False)
    assert CC.classify("/ogc/wms", _Q(LAYERS="traffic")) == ("no-store", True)
    assert CC.classify("/ogc/wms", _Q(layers="traffic")) == ("no-store", True)   # case-insensitive
    assert CC.classify("/ogc/wms", _Q()) == (CC.STATIC_MAX_AGE, False)            # GetCapabilities


def test_classify_unrelated_path_is_untouched():
    for p in ("/world", "/world/transaction", "/dem/heightfield", "/layers/contours.geojson",
              "/api/plan", "/healthz", "/sites"):
        assert CC.classify(p) is None, p


# --------------------------------------------------------------------------------------------------------
# Wiring (live app): the middleware actually stamps the header end-to-end.
# --------------------------------------------------------------------------------------------------------
def test_dynamic_world_reads_carry_no_store_live():
    # DEM-independent 200s (catalog/consumption/terramechanics registries) -> unambiguous header assertion.
    for p in ("/world/layer-catalog", "/world/layer-consumption", "/world/terramechanics-layers"):
        r = client.get(p)
        assert r.status_code == 200, p
        assert r.headers.get("cache-control") == "no-store", (p, r.headers.get("cache-control"))


def test_static_products_are_cacheable_not_no_store_live():
    # /layers/legend is DEM-independent (physics constants); it must be publicly cacheable, never no-store.
    r = client.get("/layers/legend")
    assert r.status_code == 200
    cc = r.headers.get("cache-control")
    assert cc == "public, max-age=300", cc
    assert "no-store" not in (cc or "")


def test_heightfield_full_keeps_its_own_longer_max_age_live():
    # The route sets public, max-age=3600; the middleware must NOT clobber it down to 300 (setdefault).
    r = client.get("/dem/heightfield_full?site=haworth")
    assert r.status_code == 200
    cc = r.headers.get("cache-control")
    assert cc == "public, max-age=3600", cc
    assert "no-store" not in (cc or "")


def test_traffic_drape_is_dynamic_no_store_live():
    # The one drape KIND that composes mutable world-state (per-site TrafficMemory Dr) must not be cached.
    r = client.get("/layers/globe/traffic.png")
    assert r.status_code == 200
    assert r.headers.get("cache-control") == "no-store", r.headers.get("cache-control")


def test_static_globe_drape_is_cacheable_live():
    # A DEM+sun-only drape (cost) is safe to edge-cache -> public max-age, never no-store.
    r = client.get("/layers/globe/cost.png")
    assert r.status_code == 200
    cc = r.headers.get("cache-control")
    assert cc == "public, max-age=300", cc
    assert "no-store" not in (cc or "")
