"""[REQ:ML-06] Regolith Volume Estimator: moved volume/mass WITH an uncertainty band from before/after
heightfields, cross-checked against the conserved-authority mass_moved_kg AND the DrumSensor estimate.

No synthetic data: the before/after surfaces are the conserved authority's own output for a REAL mission
(mission_terrain_delta's base/as_built grids), the per-cell height uncertainty is the REAL dense-stereo
height RMSE measured off the COMMITTED g2cal rendered pose (stewie/eval/validation/g2cal/pose_1 vs
samples/crater_boulders -- CPU SGBM, no GPU), and the drum estimate goes through the real ICE-RASSOR
FDC sensing path (true drum mass -> current -> calibrated inverse), exactly as test_drum_sensing does.

GATED (named, not faked): the DENSE observed-before/after leg -- running this estimator on two stereo
RECONSTRUCTIONS of a worksite (before/after renders -> SGBM heightfields) needs the GPU render pipeline
(P6 map channel); here the estimator consumes conserved surfaces + the measured stereo height RMSE.

Run: <venv>/bin/python -m pytest lode/test_regolith_volume.py -q
"""
import os

import pytest

import lode.mission_planner as MP
from lode.planner_acceptance import mission_terrain_delta, validate_plan
from lode.regolith_volume import estimate_moved_regolith
from stewie.eval.perception_measure import measure_pair
from stewie.physics.rassor_mass_model import (
    FDC_MPE_HALF_FULL, HALF_FULL_KG, REGOLITH_PER_CYCLE_KG, DrumSensor)
from stewie.specs import constants as K

_G2_POSE = os.path.join("stewie", "eval", "validation", "g2cal", "pose_1")
_SCENE = os.path.join("samples", "crater_boulders")


def _mission(orders):
    return MP.mission_from_dict({"name": "S", "body": "moon", "charger": [0, 0], "orders": orders})


def _cut_mission(footprint_m2=1.0, depth_m=0.013):
    # 1 m^2 x 13 mm at rho_bank 1920 -> ~24.96 kg: fits ONE drum cycle (~30 kg) AND is in the >half-full
    # regime (> 20 kg) where the published FDC error is tightest (2.56%) -- the drum cross-check's sweet spot.
    return _mission([{"action": "src", "kind": "cut", "x": 5.0, "y": 5.0,
                      "footprint_m2": footprint_m2, "depth_m": depth_m}])


@pytest.fixture(scope="module")
def height_rmse_m():
    """REAL measured dense-stereo height RMSE off the committed g2cal rendered pose (CPU, ~3 s)."""
    m = measure_pair(_G2_POSE, _SCENE)
    assert m["n_height"] > 0 and m["height_rmse_m"] > 0.0
    return m["height_rmse_m"]


def test_estimate_agrees_with_conserved_authority_mass(height_rmse_m):
    """[REQ:ML-06] the DEM-differencing estimate (cut volume x in-situ density) lands ON the conserved
    mass_moved_kg, and the truth sits inside the REAL-measured-RMSE uncertainty band."""
    d = mission_terrain_delta(_cut_mission())
    est = estimate_moved_regolith(d["base"], d["as_built"], d["cell_m"], density_kg_m3=K.RHO_SURFACE,
                                  height_rmse_m=height_rmse_m, conserved_mass_kg=d["mass_moved_kg"])
    # the observed estimate is the conserved truth (same authority surfaces, exact conversion)
    assert est["observed_mass_kg"] == pytest.approx(d["mass_moved_kg"], rel=1e-6)
    assert est["cut_volume_m3"] > 0.0 and est["fill_volume_m3"] == 0.0
    # a REAL nonzero band (measured stereo height RMSE over the worked cells), and the truth is inside it
    assert est["uncertainty_kg"] > 0.0
    assert est["lower_kg"] < d["mass_moved_kg"] < est["upper_kg"]
    assert est["agreement_conserved"] is True
    assert est["conserved_err_kg"] == pytest.approx(0.0, abs=1e-6 * d["mass_moved_kg"])


def test_cross_check_drum_sensor_estimate(height_rmse_m):
    """[REQ:ML-06] the DEM estimate agrees (within band) with the drum-fill sensing estimate produced by
    the real FDC path: conserved drum mass -> synthesized motor current -> calibrated inverse model."""
    m = _cut_mission()
    d = mission_terrain_delta(m)
    # cut-only mission -> everything excavated is IN the drum: the sensed true mass IS mass_moved_kg
    r = validate_plan(m)
    assert r["drum_remaining_kg"] == pytest.approx(d["mass_moved_kg"], rel=1e-9)
    assert HALF_FULL_KG < d["mass_moved_kg"] < REGOLITH_PER_CYCLE_KG   # one drum, >half full (2.56% regime)
    sensor = DrumSensor.calibrated([0.0, 5.0, 10.0, 15.0, 20.0, 25.0, 30.0], noise_frac=0.0)
    drum_inferred = sensor.observe(r["drum_remaining_kg"])             # deterministic sensing (noise OFF)
    assert drum_inferred == pytest.approx(d["mass_moved_kg"], abs=0.5)  # the FDC inverse recovers the mass
    est = estimate_moved_regolith(d["base"], d["as_built"], d["cell_m"], density_kg_m3=K.RHO_SURFACE,
                                  height_rmse_m=height_rmse_m, conserved_mass_kg=d["mass_moved_kg"],
                                  drum_inferred_kg=drum_inferred)
    assert est["agreement_drum"] is True and est["agreement_conserved"] is True
    # the drum band carries the PUBLISHED >half-full error and covers the DEM estimate
    assert est["drum_uncertainty_frac"] == pytest.approx(FDC_MPE_HALF_FULL)
    assert est["drum_lower_kg"] <= est["observed_mass_kg"] <= est["drum_upper_kg"]


def test_uncertainty_band_structure_and_disagreement_detection(height_rmse_m):
    """[REQ:ML-06] the band always covers the point estimate, widens monotonically with the height RMSE
    and the density envelope, and the agreement checks can actually FAIL (non-vacuous)."""
    d = mission_terrain_delta(_cut_mission())
    kw = dict(density_kg_m3=K.RHO_SURFACE, conserved_mass_kg=d["mass_moved_kg"])
    tight = estimate_moved_regolith(d["base"], d["as_built"], d["cell_m"], height_rmse_m=height_rmse_m, **kw)
    wide = estimate_moved_regolith(d["base"], d["as_built"], d["cell_m"],
                                   height_rmse_m=2 * height_rmse_m, density_frac=0.1, **kw)
    for est in (tight, wide):
        assert est["lower_kg"] <= est["observed_mass_kg"] <= est["upper_kg"]
    assert wide["uncertainty_kg"] > tight["uncertainty_kg"]
    # zero declared uncertainty: the estimate still equals the truth (roundoff-guarded agreement)
    exact = estimate_moved_regolith(d["base"], d["as_built"], d["cell_m"], height_rmse_m=0.0, **kw)
    assert exact["uncertainty_kg"] == 0.0 and exact["agreement_conserved"] is True
    # NON-VACUOUS: a wrong conserved mass / wrong drum estimate is REJECTED by the same checks
    bad = estimate_moved_regolith(d["base"], d["as_built"], d["cell_m"], height_rmse_m=height_rmse_m,
                                  density_kg_m3=K.RHO_SURFACE, conserved_mass_kg=2 * d["mass_moved_kg"],
                                  drum_inferred_kg=3 * d["mass_moved_kg"])
    assert bad["agreement_conserved"] is False and bad["agreement_drum"] is False


def test_cut_and_fill_mission_volumes_and_fill_mass(height_rmse_m):
    """[REQ:ML-06] on a cut+fill mission the estimator reads BOTH sides: cut mass still matches the
    conserved moved mass, and the fill volume x spoil density recovers the executed fill mass."""
    m = _mission([
        {"action": "src", "kind": "cut", "x": 5.0, "y": 5.0, "footprint_m2": 1.0, "depth_m": 0.013},
        {"action": "pad", "kind": "fill", "x": 20.0, "y": 20.0, "footprint_m2": 1.0, "depth_m": 0.005},
    ])
    d = mission_terrain_delta(m)
    r = validate_plan(m)
    est = estimate_moved_regolith(d["base"], d["as_built"], d["cell_m"], density_kg_m3=K.RHO_SURFACE,
                                  spoil_density_kg_m3=K.RHO_SPOIL, height_rmse_m=height_rmse_m,
                                  conserved_mass_kg=d["mass_moved_kg"])
    assert est["cut_volume_m3"] > 0.0 and est["fill_volume_m3"] > 0.0
    assert est["agreement_conserved"] is True
    assert est["fill_mass_kg"] == pytest.approx(r["executed_fill_kg"], rel=1e-6)


def test_rejects_unphysical_inputs():
    """[REQ:ML-06] input validation: a non-positive density / negative uncertainty cannot silently produce
    a mass estimate."""
    d = mission_terrain_delta(_cut_mission())
    with pytest.raises(ValueError):
        estimate_moved_regolith(d["base"], d["as_built"], d["cell_m"], density_kg_m3=0.0)
    with pytest.raises(ValueError):
        estimate_moved_regolith(d["base"], d["as_built"], d["cell_m"], density_kg_m3=K.RHO_SURFACE,
                                height_rmse_m=-0.01)
