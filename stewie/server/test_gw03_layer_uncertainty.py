"""[REQ:GW-03] the GIS workbench layer manifest UI must differentiate display / planning / release-execute
eligibility AND expose per-layer FRESHNESS + PROVENANCE + UNCERTAINTY. Freshness/provenance land via GW-06
(the public /world/layer-manifest); this file is the UNCERTAINTY + eligibility-differentiation contract the
panel binds. The per-layer uncertainty is a source_class-IMPLIED confidence (class + tier), derived at serve
time from the REAL declared source_class of each catalog layer — never a fabricated numeric uncertainty. The
/world/layer-catalog endpoint (the SUPERSET the panel groups) carries it on every row, and the eligibility
fields (planning vs release-execute, display implicit) make a display-only layer distinct from a planning one.

The panel rendering of this is verified LIVE via gis/qwc2/proof/drive_gw03_uncertainty.cjs.
"""
from fastapi.testclient import TestClient

from stewie.server.routers.world import layer_confidence


def _catalog(monkeypatch):
    monkeypatch.setenv("STEWIE_DEV_OPEN", "1")
    from stewie.server.server import app
    c = TestClient(app, base_url="http://127.0.0.1")
    return c.get("/world/layer-catalog").json()


def test_layer_confidence_is_faithful_to_the_declared_source_class():  # [REQ:GW-03]
    # UNCERTAINTY = a source_class-implied CONFIDENCE class+tier, classified from the REAL provenance tokens.
    # A directly-observed layer is measured/high; a static prior is reference; a forecast/belief layer is
    # predicted/low; a derived layer is derived/medium; a user design is authored. No fabricated number.
    assert layer_confidence("observed")["cls"] == "measured" and layer_confidence("observed")["tier"] == "high"
    assert layer_confidence("prior")["cls"] == "reference"
    assert layer_confidence("forecast")["tier"] == "low" and layer_confidence("forecast")["cls"] == "predicted"
    # strongest grounding token wins (matches the provClass badge): a derived score that folds in a belief
    # input is classified by its strongest term (derived/medium), with the full basis kept for transparency.
    assert layer_confidence("derived/belief")["cls"] == "derived" and layer_confidence("derived/belief")["tier"] == "medium"
    assert layer_confidence("derived")["cls"] == "derived" and layer_confidence("derived")["tier"] == "medium"
    assert layer_confidence("user/forecast")["cls"] == "predicted"  # forecast outranks user authoring
    # the strongest grounding token sets the class (mirrors the provClass badge): prior/observed -> measured.
    assert layer_confidence("prior/observed")["cls"] == "measured"
    # ...but that high tier is CONDITIONAL on fresh observation (a prior DEM is only measured once observed).
    assert layer_confidence("prior/observed")["conditional"] is True
    assert layer_confidence("observed")["conditional"] is False     # a pure observation is not conditional
    assert layer_confidence("derived")["conditional"] is False      # a computed layer is not a live measurement
    # an unrecognized/empty provenance reads honestly as unknown, never a guessed value.
    assert layer_confidence("")["cls"] == "unknown" and layer_confidence("")["tier"] == "n/a"


def test_catalog_endpoint_carries_per_layer_uncertainty(monkeypatch):  # [REQ:GW-03]
    cat = _catalog(monkeypatch)
    assert cat["count"] == 66 and len(cat["layers"]) == 66
    tiers = {"high", "medium", "low", "n/a"}
    for ly in cat["layers"]:
        c = ly.get("confidence")
        assert c is not None, f"{ly['id']} carries no confidence (per-layer uncertainty missing)"
        assert c["tier"] in tiers and isinstance(c["cls"], str) and c["cls"]
        assert c["basis"] == ly["source_class"]                     # transparent: the raw provenance it derives from
        assert isinstance(c["conditional"], bool)
    # spot-check real rows differentiate: an observed hazard vs a static prior vs a forecast route.
    by = {ly["id"]: ly for ly in cat["layers"]}
    assert by["base.dem"]["confidence"]["cls"] == "measured" and by["base.dem"]["confidence"]["conditional"] is True
    assert by["base.imagery"]["confidence"]["cls"] == "reference"   # prior-only basemap
    assert by["mission.route_candidates"]["confidence"]["tier"] == "low"   # forecast -> predicted/low
    assert by["design.cut"]["confidence"]["cls"] == "predicted"     # user/forecast design intent


def test_catalog_endpoint_differentiates_eligibility(monkeypatch):  # [REQ:GW-03]
    # The acceptance requires the UI differentiate display / planning / release-execute eligibility. The
    # catalog carries the machine-readable basis for that: a DISPLAY-ONLY layer (not planning-eligible) is
    # distinct from a PLANNING-eligible one, and a RELEASE-execute-eligible layer is distinct again.
    cat = _catalog(monkeypatch)
    by = {ly["id"]: ly for ly in cat["layers"]}
    for lid in ("planning_eligible", "release_execute_eligible"):   # every row carries both eligibility gates
        assert all(lid in ly for ly in cat["layers"])
    # display-only: shown on the map but NOT a planning/autonomy input (truth/basemap can't drive planning).
    for did in ("base.imagery", "base.hillshade", "runtime.gazebo_truth"):
        assert by[did]["planning_eligible"] is False and by[did]["release_execute_eligible"] is False
    # planning-eligible-but-not-releasable: reads into the planner, but not a release/execute authority.
    assert by["terrain.los"]["planning_eligible"] is True and by["terrain.los"]["release_execute_eligible"] is False
    # release-execute-eligible authority: the DEM feeds planning AND is releasable if fresh/provenanced.
    assert by["base.dem"]["planning_eligible"] is True and by["base.dem"]["release_execute_eligible"] is True
    # the three tiers are genuinely distinct populations (not all-equal), so the UI has something to differentiate.
    disp_only = [ly["id"] for ly in cat["layers"] if not ly["planning_eligible"]]
    planning = [ly["id"] for ly in cat["layers"] if ly["planning_eligible"] and not ly["release_execute_eligible"]]
    releasable = [ly["id"] for ly in cat["layers"] if ly["release_execute_eligible"]]
    assert disp_only and planning and releasable
