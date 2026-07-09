"""[REQ:SD-01] Surface-Design per-structure CONSTRUCTABILITY EVIDENCE is REAL, not fabricated.

The `/structure` decompose already issues mass-balanced cut/fill orders; SD-01's gap was the EVIDENCE an
operator needs before staging a structure. This test proves every evidence number is a real derivation:

  * volume/mass are recomputed independently from the decompose orders (footprint × depth × the conserved
    bank/loose density) and must match the evidence exactly;
  * the local terramechanics (contact pressure, sinkage, slip, entrapment, allowable bearing capacity) must
    equal an INDEPENDENT call to the SAME terramechanics spine (stewie.physics.sinkage / slip) + FORGE the
    physics globe drape uses -- so the panel cannot show a hand-picked number;
  * the constructability verdict is DERIVED (it flips with the spine's own entrapment / sinkage-limit /
    bearing checks), never a fixed string;
  * the `/structure` endpoint returns the evidence, and the DEM-slope path samples the REAL site DEM.

Run: PYTHONPATH=. .venv/bin/python -m pytest stewie/server/test_sd01_constructability.py -q
"""
from __future__ import annotations

import math
import os

import pytest

from leap import structures as ST
from stewie.server import constructability as CB

_HAWORTH = os.path.join(os.path.dirname(__file__), "..", "..", "samples", "lunar_dem",
                        "haworth_10km_5m", "heightmap.rf32")
_HAS_DEM = os.path.exists(_HAWORTH)
# a selenographic point INSIDE the committed Haworth tile (its centre) -- used for the "placement" slope path.
_HAWORTH_LAT, _HAWORTH_LON = -86.333, -25.505


def test_earthwork_volume_mass_match_the_decompose():
    """[REQ:SD-01] Per-order volume = footprint × depth and mass = volume × the conserved bank(cut)/loose(fill)
    density -- recomputed independently from the SAME decompose the queue adopts."""
    orders = ST.decompose("landing_pad", 0.0, 0.0)
    ew = CB.order_earthwork(orders)
    # independent recomputation straight off the order dicts
    exp_cut_vol = sum(o["footprint_m2"] * o["depth_m"] for o in orders if o["kind"] == "cut")
    exp_fill_vol = sum(o["footprint_m2"] * o["depth_m"] for o in orders if o["kind"] == "fill")
    exp_cut_mass = exp_cut_vol * CB.RHO_BANK
    exp_fill_mass = exp_fill_vol * CB.RHO_LOOSE
    # the evidence rounds volume to 4 dp / mass to 1 dp for display; assert to that precision
    assert ew["cut_volume_m3"] == pytest.approx(exp_cut_vol, abs=1e-4)
    assert ew["fill_volume_m3"] == pytest.approx(exp_fill_vol, abs=1e-4)
    assert ew["cut_mass_kg"] == pytest.approx(exp_cut_mass, abs=0.1)
    assert ew["fill_mass_kg"] == pytest.approx(exp_fill_mass, abs=0.1)
    # a landing pad is a balanced structure: the fill consumes exactly the paired cut's bank mass
    assert ew["mass_balanced"] is True
    assert ew["cut_mass_kg"] == pytest.approx(ew["fill_mass_kg"], abs=0.1)
    # per-order breakdown is present and consistent
    assert len(ew["orders"]) == len(orders)
    for oe, o in zip(ew["orders"], orders):
        assert oe["volume_m3"] == pytest.approx(o["footprint_m2"] * o["depth_m"], abs=1e-4)


def test_source_grade_structure_is_not_mass_balanced():
    """[REQ:SD-01] A cut-only source/grade structure (borrow pit) has no fill -> honestly reported as NOT
    mass-balanced (the planner routes the surplus), not silently forced to balance."""
    ew = CB.order_earthwork(ST.decompose("borrow_pit", 0.0, 0.0))
    assert ew["fill_mass_kg"] == 0.0
    assert ew["mass_balanced"] is False


def test_terramechanics_equals_an_independent_spine_call():
    """[REQ:SD-01] The bearing/sinkage/slip come from the REAL terramechanics spine -- assert they equal a
    direct, independent spine + FORGE evaluation at the same slope (no fabricated field)."""
    from forge.bearing import allowable_bearing_pa
    from stewie.physics import sinkage as SK
    from stewie.physics import slip as SL
    from stewie.specs import constants as K
    from stewie.specs import ipex_specs as IPX

    slope = 12.0
    terra = CB.site_terramechanics(slope)
    # independent spine recomputation with the SAME geometry gis_layers._terra_fields uses
    mass, g, n = float(IPX.ROVER_MASS_CLASS_KG), float(IPX.LUNAR_G_MS2), int(K.N_WHEELS)
    weight = mass * g
    th = math.radians(slope)
    n_cell = weight * math.cos(th) / n
    exp_pressure = SK.contact_pressure(n_cell, 0.18, 0.10)
    eq = SL.slip_sinkage_equilibrium(weight, th)
    exp_allow = allowable_bearing_pa(float(K.COHESION), float(K.PHI), CB.RHO_LOOSE * g, 0.18, factor_of_safety=3.0)
    assert terra["contact_pressure_pa"] == pytest.approx(exp_pressure, abs=0.05)
    assert terra["sinkage_m"] == pytest.approx(eq["sinkage_m"], abs=1e-4)
    assert terra["slip"] == pytest.approx(eq["slip"], abs=1e-4)
    assert terra["entrapped"] == bool(eq["entrapped"])
    assert terra["bearing_capacity_pa"] == pytest.approx(exp_allow, abs=0.1)


def test_verdict_is_derived_not_fabricated():
    """[REQ:SD-01] The verdict flips with the spine's OWN physics: flat ground is constructable (bearing OK,
    sinkage within limit); a steep slope that entraps the rover is NOT constructable, and the status names the
    driving check. Nothing here is a fixed constant -- entrapment is the spine's own output."""
    flat = CB.site_terramechanics(0.0)
    v_flat = CB.constructability_verdict(flat)
    assert v_flat["constructable"] is True
    assert v_flat["bearing_ok"] is True
    assert v_flat["sinkage_within_limit"] is True
    assert "bearing OK" in v_flat["status"]

    steep = CB.site_terramechanics(55.0)
    v_steep = CB.constructability_verdict(steep)
    assert steep["entrapped"] is True                    # the spine's own runaway flag drives the verdict
    assert v_steep["constructable"] is False
    assert "NOT constructable" in v_steep["status"]

    # the sinkage limit is the sourced wheel radius, not a hand-picked threshold
    assert v_flat["sinkage_limit_m"] == pytest.approx(float(CB.IPX.WHEEL_RADIUS_M), rel=1e-9)


def test_evidence_carries_material_and_uncertainty_from_the_spine():
    """[REQ:SD-01] The assembled evidence surfaces the material (density) assumption, the DEM resolution, and
    the spine terms' calibration status -- the honest uncertainty, read from the terramechanics spine itself."""
    from stewie.specs.terramechanics_spine import list_terra_spine

    orders = ST.decompose("landing_pad", 0.0, 0.0)
    ev = CB.structure_evidence("landing_pad", orders, site="haworth", site_slope_deg=8.0,
                               dem_resolution_m=5.0, slope_source="placement")
    assert ev["material"]["cut_density_kg_m3"] == CB.RHO_BANK
    assert ev["material"]["fill_density_kg_m3"] == CB.RHO_LOOSE
    assert ev["uncertainty"]["dem_resolution_m"] == 5.0
    # the calibration tags are the REAL spine tags (not invented), so they cannot drift from the spine
    cal = {t["id"]: t["calibration"] for t in list_terra_spine()}
    assert ev["uncertainty"]["sinkage_calibration"] == cal["sinkage"]
    assert ev["uncertainty"]["density_calibration"] == cal["regolith_density"]
    assert ev["uncertainty"]["slope_calibration"] == cal["slope"]
    # terramechanics + verdict are present when a slope is supplied
    assert ev["terramechanics"] is not None
    assert ev["verdict"] is not None


def test_evidence_defers_terramechanics_when_no_slope():
    """[REQ:SD-01] With no site slope (no DEM), the evidence returns earthwork ONLY and leaves terramechanics /
    verdict None -- it does NOT fabricate a slope."""
    orders = ST.decompose("landing_pad", 0.0, 0.0)
    ev = CB.structure_evidence("landing_pad", orders, site=None, site_slope_deg=None)
    assert ev["earthwork"]["cut_mass_kg"] > 0.0
    assert ev["terramechanics"] is None
    assert ev["verdict"] is None
    assert ev["site_slope_deg"] is None


@pytest.mark.skipif(not _HAS_DEM, reason="haworth DEM not present")
def test_site_slope_is_sampled_from_the_real_dem():
    """[REQ:SD-01] The site slope is measured on the REAL committed Haworth DEM -- a positive, finite slope,
    and an in-tile placement resolves the 'placement' source (location-specific, not just the site centre)."""
    slope, cell, src = CB.site_slope_deg("haworth", _HAWORTH_LAT, _HAWORTH_LON)
    assert slope is not None and math.isfinite(slope) and slope > 0.0
    assert cell == pytest.approx(5.0)
    assert src == "placement"


def test_structure_endpoint_returns_evidence():
    """[REQ:SD-01] The /structure endpoint returns the evidence block alongside the orders, and its earthwork
    matches an independent decompose+earthwork. The DEM-slope verdict is asserted only when the DEM is present."""
    from fastapi.testclient import TestClient

    import stewie.server.server as SRV

    prev = os.environ.get("STEWIE_DEV_OPEN")
    os.environ["STEWIE_DEV_OPEN"] = "1"                   # loopback in-process -> require_auth dev-open
    try:
        c = TestClient(SRV.app)
        r = c.post("/structure", json={"name": "landing_pad", "x": 0, "y": 0,
                                       "site": "haworth", "lat": _HAWORTH_LAT, "lon": _HAWORTH_LON})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        ev = body["evidence"]
        # earthwork on the endpoint matches an independent decompose+earthwork
        exp = CB.order_earthwork(ST.decompose("landing_pad", 0.0, 0.0))
        assert ev["earthwork"]["cut_mass_kg"] == pytest.approx(exp["cut_mass_kg"], rel=1e-9)
        assert ev["earthwork"]["mass_balanced"] is True
        if _HAS_DEM:
            assert ev["site_slope_deg"] is not None and ev["site_slope_deg"] > 0.0
            assert ev["terramechanics"] is not None
            assert ev["verdict"] is not None
            # the verdict string is one of the DERIVED forms, not empty
            assert ev["verdict"]["status"]
    finally:
        if prev is None:
            os.environ.pop("STEWIE_DEV_OPEN", None)
        else:
            os.environ["STEWIE_DEV_OPEN"] = prev
