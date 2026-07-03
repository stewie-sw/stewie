"""[REQ:BA-11] the open mission package round-trips (export -> import) with identical layer
bounds/resolution/CRS and the authority tuple preserved -- the ArcGIS-COMPATIBLE open interop the PRD asks
for, without claiming an ArcGIS Feature Service (that is FR-12's later adapter)."""
import pytest

from lode.mission_package import (
    AUTHORITY_KEYS,
    export_mission_package,
    import_mission_package,
)
from stewie.contracts import LayerManifest, WorldState

_AUTHORITY = {"body": "moon", "site": "haworth", "mission": "m1", "runtime_mode": "sim",
              "runnable_profile": "live", "source_class": "stereo_sgbm", "vehicle": "ipex",
              "role": "operator", "command_namespace": "ns-haworth"}


def _haworth_world():
    return WorldState(body="moon", frame="MOON_ME", rows=100, cols=120, cell_m=5.0,
                      dem_source="haworth_10km_5m", observed_fraction=0.2)


def test_haworth_package_round_trips_with_identical_geo_and_authority(tmp_path):  # [REQ:BA-11]
    world = _haworth_world()
    vectors = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [0.0, 0.0]},
         "properties": {"kind": "keepout"}}]}
    pkg = str(tmp_path / "pkg")
    export_mission_package(pkg, world=world, authority=_AUTHORITY, transaction_id="txn-1", vectors=vectors)
    got = import_mission_package(pkg)

    # the authority tuple is preserved verbatim.
    assert got["authority"] == {k: _AUTHORITY[k] for k in AUTHORITY_KEYS}
    # identical layer bounds / resolution / CRS across the round-trip (the core BA-11 guarantee).
    orig = LayerManifest.for_world(world, transaction_id="txn-1")

    def _geo(m):
        return {lyr.layer_id: (lyr.bounds_rows, lyr.bounds_cols, lyr.resolution_m, lyr.crs) for lyr in m.layers}
    assert _geo(orig) == _geo(got["layer_manifest"]), "layer bounds/resolution/CRS drifted on round-trip"
    # the manifest is typed on import (validated), and vectors survive.
    assert isinstance(got["layer_manifest"], LayerManifest)
    assert got["vectors"]["features"][0]["properties"]["kind"] == "keepout"
    # STAC-style metadata carries the site:mission id + the CRS.
    assert got["stac"]["id"] == "haworth:m1" and got["stac"]["crs"] == "MOON_ME"
    # no dem_path given -> the DEM is referenced by source (honest), not a fabricated raster.
    assert got["dem_source"] == "haworth_10km_5m" and got["dem_raster_path"] is None


def test_export_rejects_an_incomplete_authority_tuple(tmp_path):  # [REQ:BA-11]
    with pytest.raises(ValueError):
        export_mission_package(str(tmp_path / "p"), world=_haworth_world(),
                               authority={"body": "moon", "site": "haworth"}, transaction_id="t")
