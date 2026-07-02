"""[REQ:ML-05] Excavation State Model — the unified estimator fusing drum current + wheel slip +
IMU pitch + arm/drum posture + drive current into ONE typed ExcavationState {digging_state,
fill_fraction, slip, stall_risk, confidence}, ADVISORY until calibrated against real IPEx/AutoDig
telemetry (external, gated — never faked here).

Every signal is REAL conserved-sim: the drum mass is cut from a ColumnState (mass-conserving
authority), the drum current is the FDC observable synthesized from that true mass
(rassor_mass_model, NTRS 20210022781), slip/stall come from the load-bearing slip-sinkage
equilibrium (slip.py) driven by the IPEx weight at lunar g, and arm posture is a stepped ArmState.
No fabricated telemetry.
"""
from __future__ import annotations

import numpy as np
import pytest

from stewie.contracts import ExcavationState
from stewie.physics import rassor_mass_model as RM
from stewie.physics.column_state import ColumnState
from stewie.physics.excavation_state import estimate_excavation_state
from stewie.specs import constants as K
from stewie.specs.arm_state import ArmState

WEIGHT_N = K.ROVER_MASS_DRY_KG * K.g          # IPEx-class 30 kg at lunar g — the real drive load


def _drum_with_mass(target_kg):
    """Cut ~target_kg of REAL conserved regolith into a drum; return the true drum kg."""
    cs = ColumnState(width=20, height=20, cell_m=0.05,
                     mass_areal=np.full((20, 20), 400.0))                  # deep mantle -> removable
    mask = np.zeros((cs.height, cs.width), bool)
    mask[5:15, 5:15] = True
    area = float(mask.sum()) * cs.cell_area
    cs.cut_to_inventory(mask, target_kg / area)                            # areal kg/m^2 so total ~ target
    return cs.drum_inventory


def _sensor(noise_frac=0.0, seed=0):
    return RM.DrumSensor.calibrated([5, 10, 15, 20, 25, 30], noise_frac=noise_frac, seed=seed)


def _dig_arm():
    """ArmState driven INTO dig posture through its own rate-limited kinematics (not teleported)."""
    arm = ArmState()
    arm.command(front_deg=-40.0)
    for _ in range(30):
        arm.step(0.1)                                                      # 3 s at 20 deg/s -> -40 deg
    return arm


def test_typed_excavation_state_from_real_conserved_signals():  # [REQ:ML-05]
    """Drive the estimator end-to-end from conserved-sim signals -> a typed, in-domain,
    advisory/uncalibrated ExcavationState that says DIGGING at a mid fill."""
    true_kg = _drum_with_mass(24.0)
    sensor = _sensor()
    state = estimate_excavation_state(
        sensor=sensor,
        drum_current_a=sensor.current(true_kg),                            # the FDC observable
        arm=_dig_arm(),
        drum_dig_torque_nm=18.5,                                           # TRL5 Table 7 excavation load
        imu_pitch_rad=np.radians(5.0),
        total_weight_n=WEIGHT_N,
    )
    assert isinstance(state, ExcavationState)
    assert state.digging_state == "digging"
    assert 0.0 <= state.fill_fraction <= 1.0
    assert abs(state.fill_fraction - true_kg / sensor.capacity_kg) < 0.05  # tracks the true fill
    assert 0.0 <= state.slip <= 1.0
    assert 0.0 <= state.stall_risk <= 1.0
    assert 0.0 < state.confidence <= 1.0
    assert state.advisory is True                                          # gated leg not faked
    assert state.calibration == "uncalibrated"
    assert "uncalibrated" in state.source.lower()


def test_confidence_degrades_with_drum_sensor_uncertainty_band():  # [REQ:ML-05]
    """Confidence must fall as the DrumSensor uncertainty band widens: (a) sensor noise ON vs OFF,
    (b) below-half-full FDC regime (7.40% MPE) vs above-half-full (2.56%)."""
    true_kg = _drum_with_mass(24.0)
    kw = dict(arm=ArmState(), imu_pitch_rad=0.0, total_weight_n=WEIGHT_N)
    clean = _sensor(noise_frac=0.0)
    noisy = _sensor(noise_frac=0.10, seed=3)
    c_clean = estimate_excavation_state(sensor=clean, drum_current_a=clean.current(true_kg), **kw)
    c_noisy = estimate_excavation_state(sensor=noisy, drum_current_a=noisy.current(true_kg), **kw)
    assert c_noisy.confidence < c_clean.confidence                         # (a) noise widens the band

    low_kg = _drum_with_mass(6.0)                                          # < HALF_FULL_KG -> 7.40% regime
    c_low = estimate_excavation_state(sensor=clean, drum_current_a=clean.current(low_kg), **kw)
    assert c_low.confidence < c_clean.confidence                           # (b) paper band widens below half full


def test_stall_risk_rises_with_imu_pitch_and_saturates_on_entrapment():  # [REQ:ML-05]
    """The IMU pitch is the slope the wheels fight (slip-sinkage equilibrium input): stall_risk
    must rise monotonically with pitch and hit 1.0 with slip pinned high when the equilibrium
    diverges (Spirit-mode entrapment past ~45 deg)."""
    sensor = _sensor()
    cur = sensor.current(_drum_with_mass(10.0))
    kw = dict(sensor=sensor, drum_current_a=cur, arm=ArmState(), total_weight_n=WEIGHT_N)
    gentle = estimate_excavation_state(imu_pitch_rad=np.radians(5.0), **kw)
    steep = estimate_excavation_state(imu_pitch_rad=np.radians(25.0), **kw)
    trapped = estimate_excavation_state(imu_pitch_rad=np.radians(55.0), **kw)
    assert gentle.stall_risk < steep.stall_risk < trapped.stall_risk
    assert trapped.stall_risk == 1.0                                       # entrapment saturates the risk
    assert trapped.slip > 0.9                                              # runaway slip is reported


def test_digging_state_classification():  # [REQ:ML-05]
    """digging_state fuses arm posture + drum torque + drive current + the offload trigger:
    idle / driving (empty) / hauling (loaded) / digging / offload_due (priority near capacity)."""
    sensor = _sensor()
    kw = dict(sensor=sensor, imu_pitch_rad=0.0, total_weight_n=WEIGHT_N)
    empty_cur = sensor.current(0.0)
    assert estimate_excavation_state(drum_current_a=empty_cur, arm=ArmState(),
                                     **kw).digging_state == "idle"
    assert estimate_excavation_state(drum_current_a=empty_cur, arm=ArmState(),
                                     drive_current_a=2.0, **kw).digging_state == "driving"
    mid_cur = sensor.current(_drum_with_mass(18.0))
    assert estimate_excavation_state(drum_current_a=mid_cur, arm=ArmState(),
                                     drive_current_a=2.0, **kw).digging_state == "hauling"
    # near capacity the offload trigger outranks the dig posture (stop digging, go process)
    full_cur = sensor.current(_drum_with_mass(30.0))
    state = estimate_excavation_state(drum_current_a=full_cur, arm=_dig_arm(),
                                      drum_dig_torque_nm=18.5, **kw)
    assert state.digging_state == "offload_due"


def test_contract_rejects_uncalibrated_nonadvisory_and_bad_domains():  # [REQ:ML-05]
    """The typed contract enforces the honesty gate: an uncalibrated estimate may NOT drop the
    advisory flag, unknown digging_state values are rejected, and [0,1] domains are enforced."""
    ok = dict(digging_state="idle", fill_fraction=0.5, slip=0.1, stall_risk=0.2, confidence=0.9)
    with pytest.raises(ValueError):
        ExcavationState(**ok, advisory=False, calibration="uncalibrated")
    with pytest.raises(ValueError):
        ExcavationState(**{**ok, "digging_state": "warp_drive"})
    with pytest.raises(ValueError):
        ExcavationState(**{**ok, "fill_fraction": 1.5})
    with pytest.raises(ValueError):
        ExcavationState(**{**ok, "confidence": -0.1})
