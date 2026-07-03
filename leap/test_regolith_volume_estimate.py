"""[REQ:FR-13] the RegolithVolumeEstimate contract: a before/after terrain delta produces a conserved,
uncertainty-carrying volume estimate, cross-checked against the conserved-authority mass and the drum
sensor, linked to a world transaction. Driven from a REAL mission terrain delta (lode.planner_acceptance
mission_terrain_delta over the conserved authority) -- no synthetic data."""
import pytest

import lode.mission_planner as MP
from leap.volume_evidence import siteplan_volume_evidence
from lode.planner_acceptance import mission_terrain_delta
from stewie.contracts import RegolithVolumeEstimate
from stewie.specs import constants as K


def _cut_mission(footprint_m2=1.0, depth_m=0.013):
    # a 1 m^2 x 13 mm cut ~= 25 kg: one drum cycle, in the >half-full FDC regime (the drum cross-check's
    # sweet spot). Same conserved fixture the ML-06 estimator test uses.
    return MP.mission_from_dict({"name": "S", "body": "moon", "charger": [0, 0],
                                 "orders": [{"action": "src", "kind": "cut", "x": 5.0, "y": 5.0,
                                             "footprint_m2": footprint_m2, "depth_m": depth_m}]})


def test_siteplan_emits_a_conserved_uncertainty_carrying_volume_estimate():  # [REQ:FR-13]
    ev = siteplan_volume_evidence(_cut_mission(), work_order_id="wo-1", transaction_id="txn-1",
                                  density_kg_m3=K.RHO_SURFACE, density_frac=0.1)
    assert isinstance(ev, RegolithVolumeEstimate)
    assert ev.observed_mass_kg > 0.0 and ev.change_cells > 0
    # the uncertainty band brackets the estimate.
    assert ev.uncertainty_kg > 0.0
    assert ev.lower_kg <= ev.observed_mass_kg <= ev.upper_kg
    # cross-checked against the conserved-authority mass: agrees, residual ~0 (conservation holds).
    assert ev.agreement_conserved is True
    assert abs(ev.conserved_err_kg) < 1e-6 * max(1.0, ev.observed_mass_kg)
    # typed confidence + acceptance + a linked world transaction.
    assert ev.confidence_class in ("high", "medium", "low")
    assert ev.acceptance in ("accepted", "review")
    assert ev.transaction_id == "txn-1" and ev.work_order_id == "wo-1"
    assert ev.before_source and ev.after_source


def test_drum_cross_check_drives_acceptance():  # [REQ:FR-13]
    m = _cut_mission()
    d = mission_terrain_delta(m)
    # a drum inference that MATCHES the moved mass -> both cross-checks (conservation + drum) agree -> accepted.
    ev = siteplan_volume_evidence(m, work_order_id="wo-2", transaction_id="txn-2",
                                  density_kg_m3=K.RHO_SURFACE, density_frac=0.1, drum_inferred_kg=d["mass_moved_kg"])
    assert ev.agreement_drum is True
    assert ev.acceptance == "accepted"


def test_estimate_is_a_strict_frozen_contract_and_round_trips():  # [REQ:FR-13]
    ev = siteplan_volume_evidence(_cut_mission(), work_order_id="wo-3", transaction_id="txn-3",
                                  density_kg_m3=K.RHO_SURFACE, density_frac=0.1)
    # frozen -> immutable (cannot be edited after emission).
    with pytest.raises(Exception):
        ev.observed_mass_kg = 0.0
    # round-trips through model_dump for the cockpit/report consumer.
    dd = ev.model_dump()
    assert dd["transaction_id"] == "txn-3" and dd["acceptance"] == ev.acceptance
    assert dd["uncertainty_kg"] == ev.uncertainty_kg
