"""EP-02: dig energy depends on material (an operator difficulty factor) AND the constant baseline model
carries an explicit uncertainty band. The baseline dig_energy_per_kg is a CONSTANT (BP-1-calibrated,
material/density/ice-independent) with the drum-rate (0.72-1.0)x band reported as dig_energy_bounds_MJ;
Mission.dig_energy_factor scales it for a known harder/icier site. None -> 1.0 -> byte-identical."""
import math

import pytest

import lode.mission_planner as MP


def _mk(extra=None):
    p = {"name": "S", "body": "moon", "charger": [0, 0],
         "orders": [{"action": "cut", "kind": "cut", "x": 5.0, "y": 5.0, "footprint_m2": 16.0, "depth_m": 0.3}]}
    if extra:
        p.update(extra)
    return MP.mission_from_dict(p)


def test_default_factor_none_and_explicit_one_is_byte_identical():
    m = _mk()
    assert m.dig_energy_factor is None
    base = MP.plan_context(m).dig_j_per_kg
    assert base > 0
    assert MP.plan_context(_mk({"dig_energy_factor": 1.0})).dig_j_per_kg == base   # 1.0 == None == baseline


def test_factor_scales_dig_energy_everywhere():  # [REQ:EP-02]
    base = MP.plan_context(_mk()).dig_j_per_kg
    assert math.isclose(MP.plan_context(_mk({"dig_energy_factor": 2.0})).dig_j_per_kg, 2.0 * base)
    # the factor flows through to the executed dig energy of the acceptance check (one fold point in plan_context)
    e1 = MP.validate_plan(_mk())["executed_dig_J"]
    e2 = MP.validate_plan(_mk({"dig_energy_factor": 2.0}))["executed_dig_J"]
    assert e1 > 0 and math.isclose(e2, 2.0 * e1, rel_tol=1e-9)


def test_constant_model_uncertainty_band_is_marked():
    # the OR-branch: the baseline constant model carries an explicit (rated, max) band, not false precision
    from stewie.specs.ipex_specs import dig_energy_bounds_j_per_kg, dig_energy_per_kg
    lo, hi = dig_energy_bounds_j_per_kg()
    assert 0 < lo < hi and math.isclose(hi, dig_energy_per_kg())   # band brackets the headline constant


def test_validation():
    with pytest.raises(ValueError):
        _mk({"dig_energy_factor": 0})
    with pytest.raises(ValueError):
        _mk({"dig_energy_factor": -1.0})
    with pytest.raises(ValueError):
        _mk({"dig_energy_factor": float("inf")})
    assert _mk({"dig_energy_factor": 1.5}).dig_energy_factor == 1.5
