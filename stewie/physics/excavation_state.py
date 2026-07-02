"""excavation_state.py -- ML-05: the unified ExcavationState estimator.

ONE fusion point for the excavation-sensing pieces that already exist separately: the FDC
drum-current observable + fill-knowledge uncertainty band (rassor_mass_model, ICE-RASSOR
NTRS 20210022781), the load-bearing slip-sinkage equilibrium (slip.py), and the articulated
arm/drum posture (specs.arm_state). Inputs are the row's real telemetry channels --

  drum current      the free-spinning FDC read -> inferred drum mass -> fill_fraction
  drum torque       active excavation load on the drums (dig discriminator; TRL5 Table 7
                    grounds the lunar excavation magnitude at 18.5 N*m)
  IMU pitch         the along-track slope the wheels fight -> slip_sinkage_equilibrium input
  arm state         posture (dig vs stowed) via ArmState kinematics
  drive current     locomotion draw (>0 = driving/hauling)

and the output is the typed contracts.ExcavationState {digging_state, fill_fraction, slip,
stall_risk, confidence}. HONESTY: the fusion is validated on conserved-sim signals only; real
IPEx/AutoDig telemetry is an EXTERNAL, GATED calibration leg, so every estimate this module
emits is advisory=True / calibration="uncalibrated" (the contract's validator enforces the
pairing). Confidence carries the published FDC uncertainty band, widened by the sensor's own
noise fraction -- the autonomy layer plans against imperfect knowledge, never exact state.
"""
from __future__ import annotations

from stewie.contracts import ExcavationState
from stewie.physics import rassor_mass_model as RM
from stewie.physics import slip as SL
from stewie.physics import terramechanics as tm
from stewie.specs.arm_state import ArmState

# [ASSUMPTION] dig-posture threshold: an arm pitched below horizontal by more than this puts the
# drum into the cut (0 deg = stowed horizontal, negative = down; arm_state.ARM_TRAVEL_DEG sweep).
DIG_ARM_DEG = -15.0

UNCALIBRATED_SOURCE = ("conserved-sim fusion: FDC drum current + slip-sinkage equilibrium + "
                       "ArmState posture; UNCALIBRATED (no real IPEx/AutoDig telemetry -- advisory)")


def estimate_excavation_state(*, sensor: RM.DrumSensor, drum_current_a: float, arm: ArmState,
                              imu_pitch_rad: float, total_weight_n: float,
                              drive_current_a: float = 0.0, drum_dig_torque_nm: float = 0.0,
                              params: tm.TerramechanicsParams | None = None,
                              demand_frac: float = 1.0,
                              dig_arm_deg: float = DIG_ARM_DEG) -> ExcavationState:
    """Fuse the telemetry channels into one typed, advisory ExcavationState.

    fill_fraction: the calibrated FDC inverse infers drum mass from ``drum_current_a`` (a
    free-spinning read, the flight-integrated observable), clamped to [0, capacity].
    slip / stall_risk: the per-wheel slip-sinkage equilibrium on ``|imu_pitch_rad|`` -- risk is
    the fraction of the traction budget the demand consumes, saturating at 1.0 on entrapment.
    digging_state: offload trigger (priority: stop digging, go process) > dig posture + drum
    torque > locomotion (loaded = hauling, empty = driving) > idle.
    confidence: 1 - (published FDC band at the inferred fill + the sensor's noise fraction) --
    degrades exactly as the drum-fill knowledge does.
    """
    inferred_kg = max(0.0, sensor.infer(drum_current_a))
    fill_fraction = min(1.0, inferred_kg / sensor.capacity_kg)

    eq = SL.slip_sinkage_equilibrium(total_weight_n, abs(imu_pitch_rad),
                                     params=params, demand_frac=demand_frac)
    slip_ratio = min(1.0, max(0.0, eq["slip"]))
    stall_risk = 1.0 if eq["entrapped"] else min(1.0, max(0.0, eq["demand_n"] / eq["budget_n"]))

    dig_posture = min(arm.front_deg, arm.back_deg) <= dig_arm_deg
    if sensor.offload(inferred_kg).offload:
        digging_state = "offload_due"
    elif dig_posture and drum_dig_torque_nm > 0.0:
        digging_state = "digging"
    elif drive_current_a > 0.0:
        # loaded iff the raw observable reads above the EMPTY free-spin baseline (comparing currents,
        # not inferred masses, avoids calling the drum loaded on the inversion's float dust at 0 kg)
        digging_state = "hauling" if drum_current_a > sensor.baseline_a else "driving"
    else:
        digging_state = "idle"

    band = RM.drum_mass_uncertainty_frac(inferred_kg) + max(0.0, sensor.noise_frac)
    confidence = max(0.0, 1.0 - band)

    return ExcavationState(digging_state=digging_state, fill_fraction=fill_fraction,
                           slip=slip_ratio, stall_risk=stall_risk, confidence=confidence,
                           advisory=True, calibration="uncalibrated", source=UNCALIBRATED_SOURCE)
