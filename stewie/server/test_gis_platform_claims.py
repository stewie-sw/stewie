"""[REQ:FR-12] Precise GIS/ArcGIS product language + a NAMED ArcGIS adapter boundary + SEPARATE per-layer
display-eligibility vs planning-eligibility. STEWIE does GIS-oriented lunar planning; it does NOT claim to be
a complete ArcGIS platform (the live Feature Service is a gated adapter boundary), and a displayable-but-not-
planning-valid layer is never treated as planning-valid."""
import os
import re

import pytest

from stewie.contracts import LayerManifest, WorldState
from stewie.server.arcgis_adapter import (
    ARCGIS_ADAPTER_BOUNDARY,
    GIS_PRODUCT_LANGUAGE,
    arcgis_to_feature,
    assert_planning_eligible,
    feature_to_arcgis,
    layer_planning_eligible,
)

_SRV = os.path.dirname(os.path.abspath(__file__))


def test_language_is_precise_not_arcgis_platform_complete():  # [REQ:FR-12]
    # the served UI must not claim STEWIE is a complete/full ArcGIS PLATFORM.
    html = open(os.path.join(_SRV, "index.html"), encoding="utf-8").read()
    js = open(os.path.join(_SRV, "web", "assets", "cockpit.js"), encoding="utf-8").read()
    bad = re.compile(r"(complete|full|fully functional|ready)\s+arcgis\s+platform"
                     r"|arcgis\s+platform\s+(complete|ready)"
                     r"|arcgis\s+fully\s+functional", re.I)
    assert not bad.search(html), "index.html over-claims an ArcGIS platform"
    assert not bad.search(js), "cockpit.js over-claims an ArcGIS platform"
    # and the precise positioning names what STEWIE actually is.
    assert "GIS-oriented lunar planning" in GIS_PRODUCT_LANGUAGE
    assert "NOT a complete ArcGIS platform" in GIS_PRODUCT_LANGUAGE


def test_arcgis_boundary_declares_the_gated_feature_service():  # [REQ:FR-12]
    fs = ARCGIS_ADAPTER_BOUNDARY["feature_service"]
    assert fs["read"] == "gated" and fs["query"] == "gated" and fs["edit"] == "gated"
    assert "gated" in ARCGIS_ADAPTER_BOUNDARY["auth"]                  # the live service is honestly gated
    assert "supported" in ARCGIS_ADAPTER_BOUNDARY["round_trip"]        # the round-trip IS real here


@pytest.mark.parametrize("geom", [
    {"type": "Point", "coordinates": [1.0, 2.0]},
    {"type": "LineString", "coordinates": [[0.0, 0.0], [1.0, 1.0]]},
    {"type": "Polygon", "coordinates": [[[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 0.0]]]},
])
def test_geojson_arcgis_round_trips_per_shape(geom):  # [REQ:FR-12]
    f = {"type": "Feature", "geometry": geom, "properties": {"kind": "keepout", "r": 5}}
    af = feature_to_arcgis(f, schema_map={"kind": "TYPE"}, oid=7)
    assert af["attributes"]["OBJECTID"] == 7 and af["attributes"]["TYPE"] == "keepout"
    back = arcgis_to_feature(af, schema_map={"kind": "TYPE"})
    assert back["geometry"] == geom                                   # geometry survives per shape
    assert back["properties"] == {"kind": "keepout", "r": 5}          # attributes de-mapped, OBJECTID dropped


def test_display_only_layer_is_not_planning_valid():  # [REQ:FR-12]
    m = LayerManifest.for_world(WorldState(body="moon", frame="MOON_ME", rows=10, cols=10, cell_m=5.0),
                                transaction_id="t")
    imagery = next(lyr for lyr in m.layers if lyr.layer_id == "imagery")   # display-only (planning=False)
    dem = next(lyr for lyr in m.layers if lyr.layer_id == "dem")           # planning-eligible
    assert layer_planning_eligible(imagery) is False
    assert layer_planning_eligible(dem) is True
    # display eligibility and planning eligibility are SEPARATE -- a displayable layer is refused for planning.
    assert imagery.display is True
    with pytest.raises(ValueError):
        assert_planning_eligible(imagery)
    assert_planning_eligible(dem)                                          # planning-eligible passes
