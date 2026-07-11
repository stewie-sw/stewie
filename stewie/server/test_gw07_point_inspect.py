"""[REQ:GW-07] the GIS workbench SELECTION INSPECTOR binds a REAL per-cell point query, not just static
catalog metadata. The public GET /world/point resolves a clicked map location (order-frame metres OR
selenographic lat/lon) to the site DEM cell and returns the servable layers' ACTUAL per-cell values --
elevation, slope, the six terramechanics-spine fields (bearing/sinkage/slip_risk/traction_margin/
excavation_resistance/energy_cost), the plan-independent traversal cost + blocking reason -- each computed
from the SAME functions the map drapes render (stewie.server.gis_layers), plus the cell's runtime evidence
(as-built / observed provenance from the composed terrain view). Honest 'no data' is returned where a layer
has no per-cell scalar (the sun-parameterized illumination/incidence/psr, the reference grid, the observed-
only compaction), never a fabricated value; an out-of-tile click returns in_bounds=false with no values.

Backend contract for GW-07. The panel binding is verified LIVE via gis/qwc2/proof/drive_gw07_inspector.cjs.
"""
import importlib
import math

import pytest
from fastapi.testclient import TestClient

H = {"X-API-Key": "test-key"}


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_API_KEY", "test-key")
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("STEWIE_DEV_OPEN", "1")
    from stewie.server import objects as OBJ
    importlib.reload(OBJ)
    from stewie.server import state as S
    importlib.reload(S)
    monkeypatch.setattr(S, "_TWIN", None)
    monkeypatch.setattr(S, "_TWINS", {})
    import stewie.server.server as srv
    importlib.reload(srv)
    yield TestClient(srv.app)
    monkeypatch.undo()
    importlib.reload(srv)


def _attrs(payload):
    return {a["id"]: a for a in payload["attributes"]}


def test_point_is_public_no_key(client):  # [REQ:GW-07]
    # the public /ide/ Selection Inspector has no API key (nginx blanks the identity), so the per-cell
    # attribute source MUST be reachable WITHOUT auth -- unlike the auth-gated /world (which 401s).
    assert client.get("/world?site=haworth").status_code == 401
    r = client.get("/world/point?site=haworth&x=60&y=60")            # a cell inside the Haworth work area
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["ok"] is True and d["cell"]["in_bounds"] is True


def test_point_returns_real_layer_values_at_the_cell(client):  # [REQ:GW-07]
    d = client.get("/world/point?site=haworth&x=60&y=60").json()
    by = _attrs(d)
    # ATTRIBUTES: elevation is a real finite metre reading off the LOLA DEM.
    dem = by["base.dem"]
    assert dem["available"] is True and dem["unit"] == "m"
    assert isinstance(dem["value"], float) and math.isfinite(dem["value"])
    # slope in the physical domain [0, 90] deg.
    slope = by["terrain.slope"]
    assert slope["available"] is True and slope["unit"] == "deg"
    assert 0.0 <= slope["value"] <= 90.0
    # the SIX terramechanics-spine fields, each a finite value carrying its real unit (parity with
    # gis_layers.PHYSICS_LAYERS -- the same solver outputs the drape colours).
    units = {"physics.bearing": "Pa", "physics.sinkage": "m", "physics.slip_risk": "slip ratio",
             "physics.traction_margin": "fraction", "physics.energy_cost": "W",
             "physics.excavation_resistance": "N"}
    for lid, unit in units.items():
        a = by[lid]
        assert a["available"] is True, lid
        assert a["unit"] == unit, (lid, a["unit"])
        assert isinstance(a["value"], float) and math.isfinite(a["value"]), lid
    # the plan-independent traversal COST + the categorical passability/blocking reason.
    cost = by["traffic.cost_global"]
    assert cost["available"] is True and isinstance(cost["value"], float) and math.isfinite(cost["value"])
    blk = by["traffic.traversability"]
    assert blk["available"] is True and isinstance(blk["value"], bool)   # value = passable
    assert blk["reason"] is None or isinstance(blk["reason"], str)


def test_point_reports_honest_no_data_where_no_cell_scalar(client):  # [REQ:GW-07]
    # the sun-parameterized layers, the reference grid, and the observed-only compaction have NO plan-
    # independent per-cell scalar here -- the inspector says so (available=false + a reason) rather than
    # fabricating a number. Never a value where there is none.
    by = _attrs(client.get("/world/point?site=haworth&x=60&y=60").json())
    for lid in ("terrain.illumination", "terrain.incidence", "terrain.psr", "base.grid",
                "traffic.compaction"):
        a = by[lid]
        assert a["available"] is False, lid
        assert a.get("value") is None, lid
        assert a.get("note"), lid                                        # an honest reason, not empty


def test_point_carries_runtime_evidence_at_the_cell(client):  # [REQ:GW-07]
    d = client.get("/world/point?site=haworth&x=60&y=60").json()
    ev = d["runtime_evidence"]
    # a pristine (never-built, never-observed) Haworth cell reads its real provenance: pristine, zero
    # as-built delta, and the site-level observed-twin counters (a real measured 0, not a fabricated age).
    assert ev["cell_source"] in ("pristine", "as_built", "observed")
    assert isinstance(ev["as_built_delta_m"], float) and math.isfinite(ev["as_built_delta_m"])
    for k in ("as_built_version", "twin_version"):
        assert isinstance(ev[k], int)
    assert isinstance(ev["observed_fraction"], float) and 0.0 <= ev["observed_fraction"] <= 1.0
    assert isinstance(ev["observed_at_cell"], bool)


def test_point_available_actions_from_eligibility(client):  # [REQ:GW-07]
    # AVAILABLE ACTIONS: the inspector exposes the mission actions a cell affords -- plan-here (always, on
    # in-bounds ground), place-structure + add-keepout -- gated on real state (a blocked/impassable cell
    # cannot host a structure). These are enumerated, each with an enabled flag + a reason, never faked.
    d = client.get("/world/point?site=haworth&x=60&y=60").json()
    acts = {a["id"]: a for a in d["actions"]}
    assert set(acts) >= {"plan_here", "place_structure", "add_keepout"}
    for a in acts.values():
        assert isinstance(a["enabled"], bool) and a["label"]


def test_point_latlon_input_resolves_the_same_cell_as_xy(client):  # [REQ:GW-07]
    # a map click can arrive as selenographic lat/lon (the OpenLayers view CRS reprojected); it must resolve to
    # the SAME DEM cell as the ORDER-frame metres that GEOGRAPHICALLY correspond to it, and to its true pixel.
    # council #55 (HIGH): lat/lon is ABSOLUTE pixel-metres while the order frame is anchor-relative, so the
    # equivalent order coords subtract the flattest anchor -- the resolver must not double-count it (which sent
    # interior clicks out of bounds). Independent ground truth: pixel (200,200)'s centre lat/lon.
    from stewie.server import state
    from stewie.terrain.site_dem import dem_origin_to_latlon
    _, origin = state.moon_dem("haworth")
    ox, oy = float(origin[0]), float(origin[1])
    ax, ay = 200 * 5.0, 200 * 5.0                          # absolute pixel-metres of pixel (200,200)
    lat, lon = dem_origin_to_latlon(ax, ay)
    by_xy = client.get(f"/world/point?site=haworth&x={ax - ox}&y={ay - oy}").json()   # equivalent order coords
    by_ll = client.get(f"/world/point?site=haworth&lat={lat}&lon={lon}").json()
    assert by_ll["ok"] is True and by_ll["cell"]["in_bounds"] is True
    assert (by_ll["cell"]["row"], by_ll["cell"]["col"]) == (by_xy["cell"]["row"], by_xy["cell"]["col"]) == (200, 200)


def test_point_out_of_tile_is_honest_no_data_not_fabricated(client):  # [REQ:GW-07]
    # a click far outside the tile returns in_bounds=false and NO fabricated layer values -- every attribute
    # is available=false. The inspector never invents a reading off the map.
    d = client.get("/world/point?site=haworth&x=9000000&y=9000000").json()
    assert d["ok"] is True and d["cell"]["in_bounds"] is False
    for a in d["attributes"]:
        assert a["available"] is False and a.get("value") is None


def test_point_unknown_site_404(client):  # [REQ:GW-07]
    r = client.get("/world/point?site=amundsen_rim&x=60&y=60")       # real site id, no bundle on disk
    assert r.status_code == 404
