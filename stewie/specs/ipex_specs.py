"""ipex_specs.py — IPEx flight-system parameters, real-data-sourced (no fabricated values).

Grounds the M3 energy/battery model (K2) in published IPEx numbers instead of arbitrary
coefficients. Every constant carries its provenance. Primary source:

  [SCHULER24] J.M. Schuler et al., "ISRU Pilot Excavator (IPEx) Technology Readiness Level 5
              Design Overview", AIAA AVIATION FORUM AND ASCEND 2024, 2024.
              NTRS 20240008162.  IPEx mass/speed/size/power were estimated by recreating the
              ConOps with the RASSOR 2 proof-of-concept, recording battery + actuator current
              draw, and applying a ~0.7 one-dimensional scaling factor (RASSOR 2 -> IPEx).
              IPEx IS the modelled vehicle; RASSOR (Mueller 2013, the TRL-4 counter-rotating
              bucket-drum proof of concept) is its PRECURSOR/pilot, not the flight system.
  [WHEELTEST] L. Zhang, J. Schuler, et al., "ISRU Pilot Excavator Wheel Testing in Lunar
              Regolith Simulant", ASCE Earth & Space 2024.  IPEx flight wheel = 30.5 cm dia
              (r = 0.1524 m); skid-steer kinematic track z = 0.5207 m (Eq.1); ConOps 70 km @
              <=30 cm/s; 20 deg slope test; BP-1 simulant @ ~1.75 g/cm^3; "full slip = wheels
              dig themselves deeper" (the slip-entrapment failure mode).
  [BDSCALE]   J. Schuler, A. Nick, et al., "ISRU Pilot Excavator: Bucket Drum Scaling
              Experimental Results", ASCE Earth & Space 2022.  Avg regolith collected per drum
              (small 3.80 / medium 7.30 / large 24.98 kg); drum tangential velocity 8.5x linear
              cut speed; cut depth <=50% of scoop opening; BP-1 shear-vane 27-32 kPa,
              penetrometer 206-226 kPa.
  [BATTERY]   Current flight build: 12S Li-ion pack, ~30 Ah (per project lead, 2026-06-02).
              Test-rig bus was swept at 47.6 / 53.2 / 58.8 V (a 14S range, 58.8 = 14*4.2);
              the 12S/30Ah figure here is the current pack, not the dynamometer rig.

[CALIB] tags mark values derived under a stated assumption (e.g. an operational speed the
paper reports only for an accelerated test). They are honest estimates from real inputs, not
fabricated; refine when the per-actuator current->torque equations (Figs 6, 20) are available.
"""
from __future__ import annotations

import math

TWO_PI = 2.0 * math.pi


# Camera operational floor: TRL5 TVAC qualification runs the cameras 0..50 C (p.28-29) -- the
# binding LOW limit for perception availability planning (the avionics qual is wider, -35/+40).
CAMERA_MIN_OPERATIONAL_C = 0.0    # [SCHULER24 p.28-29 TVAC]

# ---- Published IPEx ConOps / sizing numbers [SCHULER24] -----------------------------------
ROVER_MASS_CLASS_KG = 30.0        # "30 kg-class excavator"
DRIVE_SPEED_MS = 0.30             # nominal driving speed 30 cm/s
DRUM_SPEED_RPM = 25.0             # bucket-drum rotation rate [R2D: RASSOR-2.0 drum-actuator MAX
                                  # ~25 RPM (rated ~18); TRL5 conformance review 2026-06-10 --
                                  # SCHULER24's only "25" is a wheel-actuator docking speed, NOT
                                  # this. Feeds dig_power_w -> 4151 J/kg; rated-18 would scale it
                                  # 0.72x. [ASSUMPTION] until an IPEx-specific drum rate publishes.
REGOLITH_PER_CYCLE_KG = 30.0      # collect/store/deposit up to 30 kg/cycle (15 kg min threshold)
DIG_RATE_KG_PER_HR = 42.0         # demonstration excavation rate
TOTAL_REGOLITH_KG = (5000.0, 10000.0)   # moved over the mission
TRAVERSE_KM = 70.0                # total driving distance
MISSION_DAYS = 11.0
SCALE_FACTOR = 0.7                # 1-D RASSOR 2 -> IPEx scaling factor
BUS_VOLTAGE_TESTED_V = (47.6, 53.2, 58.8)

# Table 3 (Loads experienced during ConOps), wheel actuator, 80:1 gearbox.
WHEEL_GEAR_RATIO = 80.0
DRIVE_MOTOR_TORQUE_NM = 0.063     # Table 3 case 3b motor-side load (the 4-case mean is 0.0635;
                                  # review 2026-06-10 corrected the derivation note)
DRIVE_MOTOR_SPEED_RPM = 1530.0    # motor speed for those driving cases
N_WHEELS = 4

# Table 7 note: "18.5 Nm is predicted excavation load on the moon" (arm actuator).
ARM_EXCAVATION_LOAD_NM = 18.5

# ---- Flight-IPEx geometry [WHEELTEST][SCHULER24] ------------------------------------------
# These are the FLIGHT-IPEx published dimensions. The sim rover's render geometry (rover.py
# WHEEL_GAUGE_M/WHEEL_BASE_M/WHEEL_RADIUS_M, from John's Godot sidecar) is an IPEx-CLASS rover
# of the same 30 kg class; it is NOT overwritten here -- see docs/vehicle_ipex.md for the
# sim-geometry-vs-flight-IPEx reconciliation.
WHEEL_DIAMETER_M = 0.305           # "IPEx-sized wheels, which were 30.5 cm in diameter" [WHEELTEST]
WHEEL_RADIUS_M = WHEEL_DIAMETER_M / 2.0   # r = 0.1524 m, the value used in the skid-steer Eq.1
SKID_STEER_TRACK_M = 0.5207        # Eq.1 kinematic track z on the RASSOR 2 test platform [WHEELTEST]
SKID_STEER = True                  # 4-wheel skid-steer, no steering actuators, no suspension [SCHULER24]

# ---- Mobility envelope (ConOps) [SCHULER24][WHEELTEST] ------------------------------------
OBSTACLE_HEIGHT_M = 0.075          # "traversing rock obstacles up to 7.5 cm in height" [SCHULER24]
NOMINAL_SLOPE_DEG = 15.0           # "inclinations up to 15 deg" (mobility ConOps) [SCHULER24]
SLOPE_TEST_DEG = 20.0             # wheel slope-driving test ran a 20 deg incline [WHEELTEST]
# (RASSOR Gen-1 climbed a 20 deg slope and FAILED a 30 deg loose mound -> slip avalanche; the
# planner's max_traverse_slope_deg default sits between NOMINAL_SLOPE_DEG and that ~30 deg limit.)

# ---- Bucket-drum capacity [BDSCALE] -------------------------------------------------------
# Avg total regolith collected per drum, by drum scale (Schuler 2022 Table 3). IPEx uses the
# small..medium range; the large drum is the RASSOR 2.0 drum. Headline REGOLITH_PER_CYCLE_KG
# (30 kg/cycle) and REGOLITH_MIN_THRESHOLD_KG (15 kg) are the RDS spec [SCHULER24].
DRUM_CAPACITY_KG = {"small": 3.80, "medium": 7.30, "large": 24.98}
REGOLITH_MIN_THRESHOLD_KG = 15.0   # RDS minimum success threshold per cycle [SCHULER24]
TANGENTIAL_TO_CUT_RATIO = 8.5      # drum tangential velocity / linear cut speed [BDSCALE]
MAX_CUT_DEPTH_FRAC = 0.50          # cut depth limited to <=50% of scoop opening (anti-bridging) [BDSCALE]

# ---- BP-1 terrestrial test simulant [BDSCALE][WHEELTEST] ----------------------------------
# REFERENCE values for the GMRO Regolith Test Bed (Earth-g, compacted BP-1), the bin IPEx/RASSOR 2
# are tested in. NOT the lunar surface the terramechanics core models (that is the Lunar Sourcebook
# RHO_SURFACE..RHO_DEEP profile in constants.py). Kept here as sourced provenance; not wired into the
# lunar physics, and a BP-1 Bekker k_c/k_phi profile is deliberately NOT fabricated.
BP1_BULK_DENSITY_KG_M3 = 1750.0    # "~1.75 g/cm^3 after compaction" [WHEELTEST]
BP1_SHEAR_STRENGTH_KPA = (27.0, 32.0)   # Humboldt pocket shear-vane range [BDSCALE]
BP1_PENETRATION_KPA = (206.0, 226.0)    # Humboldt soil penetrometer range [BDSCALE]

# ---- Stereo working envelope [DERIVED] -------------------------------------------------------
# The TRL5 docs publish NO camera ranges; the rig is the LAC-twin 8-camera set. The OBJECTIVE band
# derives from sourced requirements + rig parameters (b = 0.07 m, fx = 679.57 @ 1024 px):
#   near: the SGBM search range, z_min = fx*b/numDisparities  (0.372 m at the default N=128)
#   far : obstacle resolvability, sigma_z = z^2*sigma_d/(fx*b) <= OBSTACLE_HEIGHT_M
#         -> z_max = sqrt(OBSTACLE_HEIGHT_M * fx*b / sigma_d) ~ 1.9 m at sigma_d = 1 px
# Measurements outside the band are not evidence (G2 calibration, 2026-06-10: sub-0.25 m grazing
# views carry a systematic matcher bias from anisotropic texture smear).
STEREO_FX_PX = 679.570327764933       # rig intrinsic at 1024x768 (Godot camera_rig)
STEREO_BASELINE_M = 0.07
def stereo_range_m(num_disparities: int = 128, sigma_d_px: float = 1.0,
                   obstacle_m: float = OBSTACLE_HEIGHT_M) -> tuple:
    """(z_min, z_max) of the objective stereo working band for the IPEx-class rig."""
    fxb = STEREO_FX_PX * STEREO_BASELINE_M
    import math as _m
    return (fxb / float(num_disparities), _m.sqrt(obstacle_m * fxb / sigma_d_px))


# ---- Battery [BATTERY] --------------------------------------------------------------------
BATTERY_SERIES_CELLS = 12         # 12S -> ~44 V pack
BATTERY_CAPACITY_AH = 30.0        # ~30 Ah
LIION_NOMINAL_V_PER_CELL = 3.7    # standard Li-ion nominal: 12 * 3.7 = 44.4 V ~= 44 V
# NOTE: IPEx actuators were qualified at -35 C / +40 C (TC2). That lunar-grade thermal range is
# NOT met by off-the-shelf cells; pack energy/usable capacity degrades sharply at those extremes.
# This model uses nominal-temperature capacity; a thermal-derating factor is [CALIB] future work.


def battery_energy_j() -> float:
    """Usable pack energy at nominal voltage: 12S * 3.7 V * 30 Ah -> J (~4.79 MJ / 1332 Wh)."""
    v_nom = BATTERY_SERIES_CELLS * LIION_NOMINAL_V_PER_CELL
    return v_nom * BATTERY_CAPACITY_AH * 3600.0


def battery_energy_wh() -> float:
    return battery_energy_j() / 3600.0


def drive_power_w() -> float:
    """Whole-rover drive mechanical power from Table 3 driving cases: P = N * tau_motor * omega.

    Motor-side mechanical power (electrical draw is higher by 1/efficiency; the drivetrain
    efficiency is not given in [SCHULER24], so this is a lower bound on battery drain). [CALIB]
    """
    omega = DRIVE_MOTOR_SPEED_RPM * TWO_PI / 60.0
    return N_WHEELS * DRIVE_MOTOR_TORQUE_NM * omega


def drive_energy_per_m() -> float:
    """Joules per metre driven at the nominal 0.30 m/s: P_drive / v."""
    return drive_power_w() / DRIVE_SPEED_MS


def dig_power_w() -> float:
    """Excavation mechanical power: predicted arm load (18.5 N*m) at the drum's operational
    25 RPM. [CALIB] the paper reports 18.5 N*m at a 500 RPM accelerated-life speed; pairing it
    with the 25 RPM operational drum rate is the honest operational estimate."""
    omega = DRUM_SPEED_RPM * TWO_PI / 60.0
    return ARM_EXCAVATION_LOAD_NM * omega


def dig_energy_per_kg() -> float:
    """Joules per kg excavated: P_dig / (dig rate in kg/s)."""
    rate_kg_s = DIG_RATE_KG_PER_HR / 3600.0
    return dig_power_w() / rate_kg_s


# ---- LUNAR-GRAVITY drive power [PHYSICS] ---------------------------------------------------
# drive_power_w() above is the Table-3 ConOps motor load (4 * 0.063 Nm * omega@1530rpm = ~40 W) -- the
# DESIGN / worst-case actuator draw, on the GMRO/BP-1 Earth-g testbed. It is NOT the lunar STEADY-drive
# power: steady-drive resistance (rolling + grade) is gravity-dependent (~ m*g), so on the Moon (1/6 g)
# the flat-drive draw is ~6x lower. Using the 40 W figure as the operational lunar draw SEVERELY
# OVERESTIMATES drive energy. lunar_drive_power_w computes the physical tractive-force draw instead.
# (Table 7's 18.5 Nm dig load IS published as "predicted on the moon", so dig_power_w is already lunar.)
LUNAR_G_MS2 = 1.62                 # Moon surface gravity (parameterizable; bodies.py is the body registry)
DRIVETRAIN_EFFICIENCY = 0.5        # [CALIB] electrical->tractive (motor+gearbox+slip); not in [SCHULER24]
ROLLING_RESISTANCE_COEFF = 0.15    # [ASSUMPTION] rigid wheel on loose regolith (~0.1-0.4); the rigorous
                                   # value is the terramechanics Bekker motion resistance, not a constant


def lunar_drive_power_w(*, slope_deg: float = 0.0, crr: float = ROLLING_RESISTANCE_COEFF,
                        mass_kg: float = ROVER_MASS_CLASS_KG, g_ms2: float = LUNAR_G_MS2,
                        v_ms: float = DRIVE_SPEED_MS, efficiency: float = DRIVETRAIN_EFFICIENCY) -> float:
    """Physical steady-drive electrical power at a given gravity/slope: tractive force
    F = m*g*(crr*cos th + sin th); P_elec = F*v / efficiency. At lunar g + flat this is ~6x below the
    Earth-test Table-3 drive_power_w(). [PHYSICS] for the force; crr + efficiency are tagged estimates.
    This is the LIGHTWEIGHT estimate (constant crr); slip.bekker_drive_power_w is the rigorous version
    that replaces crr with the Bekker compaction resistance + slip-sinkage equilibrium (soil-aware)."""
    th = math.radians(slope_deg)
    f_tractive_n = mass_kg * g_ms2 * (crr * math.cos(th) + math.sin(th))
    return f_tractive_n * v_ms / efficiency


# ---- Housekeeping / parasitic loads [ASSUMPTION] -------------------------------------------
# Continuous loads ABSENT from the published mobility/excavation tables but which DOMINATE a real lunar
# energy budget over an 11-day mission (housekeeping integrated over days >> intermittent drive/dig). The
# per-subsystem watts are NOT public for IPEx, so these are engineering estimates -- DO NOT treat as
# sourced. Rationale: VIPER runs solar-only heaters to survive shadow; CADRE's autonomy COMPUTE produces
# enough heat to force 30-min cooldown shutdowns; X-band DTE comms draw transmit power.
AVIONICS_POWER_W = 15.0            # [ASSUMPTION] flight computer + autonomy compute (SLAM/perception)
COMMS_TX_POWER_W = 15.0            # [ASSUMPTION] X-band direct-to-Earth transmit (duty-cycled)
THERMAL_SURVIVAL_POWER_W = 30.0    # [ASSUMPTION] flat fallback heater load; superseded by the model below


# ---- Environment-aware thermal heater model [PHYSICS + ASSUMPTION] -------------------------
# THERMAL_SURVIVAL_POWER_W is a flat body-blind placeholder. The real heater load is a HEAT BALANCE: the
# rover holds its electronics at a setpoint against the environment's cold sink, losing heat by radiation
# (Stefan-Boltzmann ~T^4) + conduction. It is environment-dependent (lunar day vs night vs PSR differ ~10x)
# and swaps by body. Real environment sink temperatures; the IPEx box geometry/insulation are [ASSUMPTION]
# (MLI emissivity + area dominate the magnitude -> treat the figure as order-of-magnitude, not sourced).
STEFAN_BOLTZMANN = 5.670374e-8     # W/m^2/K^4
ELECTRONICS_SETPOINT_C = -20.0     # [ASSUMPTION] minimum electronics survival temperature
RADIATOR_EMISSIVITY = 0.10         # [ASSUMPTION] MLI-wrapped low-emissivity enclosure
RADIATOR_AREA_M2 = 0.30            # [ASSUMPTION] effective radiating area for a ~30 kg rover box
THERMAL_CONDUCTANCE_W_PER_K = 0.05  # [ASSUMPTION] lumped conductive loss (structure/wheels to surface)

# Representative environment SINK temperatures (deg C): lunar surface day ~+110, night ~-180 (~90 K),
# PSR ~-233 (~40 K); Mars day ~-20, night ~-90; Earth lab +15. [SOURCED-ENV]
ENV_SINK_TEMP_C = {
    "lunar_day": 110.0, "lunar_night": -180.0, "lunar_psr": -233.0,
    "mars_day": -20.0, "mars_night": -90.0, "earth": 15.0,
}
BODY_COLD_ENV = {"moon": "lunar_psr", "mars": "mars_night", "earth": "earth"}   # coldest survival case/body


def thermal_heater_power_w(sink_temp_c: float, *, setpoint_c: float = ELECTRONICS_SETPOINT_C,
                           emissivity: float = RADIATOR_EMISSIVITY, area_m2: float = RADIATOR_AREA_M2,
                           conductance_w_per_k: float = THERMAL_CONDUCTANCE_W_PER_K) -> float:
    """Heater power to hold the electronics at ``setpoint_c`` against an environment sink, by radiative
    (Stefan-Boltzmann ~T^4) + conductive heat balance. Returns 0 when the sink is warmer than the setpoint
    (cooling, not heating, is then needed -- a separate radiator problem). [PHYSICS] balance + real sink
    temps; emissivity/area/conductance are [ASSUMPTION] (insulation dominates the magnitude)."""
    t_set, t_sink = setpoint_c + 273.15, sink_temp_c + 273.15
    if t_sink >= t_set:
        return 0.0
    radiative = emissivity * STEFAN_BOLTZMANN * area_m2 * (t_set ** 4 - t_sink ** 4)
    conductive = conductance_w_per_k * (t_set - t_sink)
    return radiative + conductive


def survival_heater_power_w(body: str = "moon") -> float:
    """Worst-case (coldest environment) survival-heater power for a body, from ENV_SINK_TEMP_C."""
    return thermal_heater_power_w(ENV_SINK_TEMP_C[BODY_COLD_ENV.get(body, "lunar_night")])


def system_power_w(*, driving: bool = True, digging: bool = False, transmitting: bool = False,
                   thermal_w: float | None = None, sink_temp_c: float | None = None,
                   slope_deg: float = 0.0, g_ms2: float = LUNAR_G_MS2) -> float:
    """Total instantaneous electrical draw = surface drive (if driving) + dig (if digging) + avionics +
    comms (if transmitting) + thermal. Sums the gravity-correct [PHYSICS] mobility (swappable by g_ms2 ->
    Earth/Moon/Mars) with the [ASSUMPTION] housekeeping loads the published tables omit. Thermal is the
    environment heat-balance heater (``sink_temp_c``) if given, else an explicit ``thermal_w``, else the
    flat fallback. The housekeeping terms (thermal especially) typically dominate the mission energy; treat
    the total as an order-of-magnitude budget, not a sourced figure."""
    p = AVIONICS_POWER_W
    if thermal_w is not None:
        p += thermal_w
    elif sink_temp_c is not None:
        p += thermal_heater_power_w(sink_temp_c)
    else:
        p += THERMAL_SURVIVAL_POWER_W
    if driving:
        p += lunar_drive_power_w(slope_deg=slope_deg, g_ms2=g_ms2)
    if digging:
        p += dig_power_w()
    if transmitting:
        p += COMMS_TX_POWER_W
    return p


# ---- Planner operational parameters (mission_planner build-sequencer) ----------------------
# NOT in [SCHULER24]: planner-level assumptions for the energy/battery build sequencer. The single
# source of truth for these knobs (mission_planner imports them; nothing is duplicated downstream).
SINTER_HEAD_POWER_W = 1000.0      # [SOURCED] domestic-microwave-class head ~0.8-1.0 kW (Lin et al. 2024);
#                                   NOT on the IPEx baseline (drum excavator, no sinter tool) -- sinter-EQUIPPED
#                                   variant only. constants.SINTER_ENABLED gates it (sourced-physics rationale).
RECHARGE_POWER_W = 700.0          # [CALIB] surface recharge power (no IPEx solar/charge spec)
BATTERY_RESERVE_FRAC = 0.10       # operational: hold >=10% pack reserve before forcing a recharge
# [ASSUMPTION] continuous idle / heater / avionics survival draw, NOT in [SCHULER24] and genuinely
# data-gated. Over a multi-day sortie this term is plausibly the DOMINANT energy cost, so the planner
# surfaces it as its OWN line, tagged [ASSUMPTION]. Default 0 W = "not modelled" (no silent inflation of
# the headline figures); set DUSTGYM_IDLE_POWER_W (or the constant) to fold in a survival load you can
# defend. Lunar-night heater loads for a small rover are tens-to-hundreds of W -- do NOT treat any value
# here as sourced. (mission_planner: survival_energy_J = IDLE_POWER_W * mission duration.)
IDLE_POWER_W = 0.0


def energy_model(cell_m: float, *, allowance_j: float | None = None,
                 allowance_factor: float | None = None,
                 planner_cost_j: float | None = None) -> dict:
    """Grounded coefficients for SkillMacroEnv's resource layer, in SI joules.

    travel_cost_per_cell = drive_energy_per_m * cell_m   (env distance is in cell units)
    dig_cost_per_kg      = dig_energy_per_kg()
    energy_budget        = allowance_j, or allowance_factor * planner_cost_j (a task slice),
                           else the full pack (battery_energy_j()).

    The per-unit costs are real-data-grounded for ANY map scale. The full pack only *binds*
    at mission scale (5 m LOLA cells, 70 km, 1e4 kg); at the 2 cm sandbox scale a single
    construction episode draws ~kJ of a ~4.7 MJ pack, so pass an allowance to make routing
    efficiency matter (allowance_factor ~1.3 of the grounded optimal-plan cost is a tight,
    binding budget).
    """
    if allowance_j is not None:
        budget = float(allowance_j)
    elif allowance_factor is not None and planner_cost_j is not None:
        budget = float(allowance_factor) * float(planner_cost_j)
    else:
        budget = battery_energy_j()
    return {
        "travel_cost_per_cell": drive_energy_per_m() * float(cell_m),
        "dig_cost_per_kg": dig_energy_per_kg(),
        "energy_budget": budget,
    }


def spec_record() -> dict:
    """JSON-dumpable provenance record of every real input + derived quantity."""
    return {
        "source": "Schuler et al., IPEx TRL-5 Design Overview, ASCEND 2024 (NTRS 20240008162)",
        "sources": [
            "Schuler et al., IPEx TRL-5 Design Overview, ASCEND 2024 (NTRS 20240008162)",
            "Zhang, Schuler et al., IPEx Wheel Testing in Lunar Regolith Simulant, ASCE E&S 2024",
            "Schuler, Nick et al., IPEx Bucket Drum Scaling Experimental Results, ASCE E&S 2022",
            "Mueller et al., RASSOR (precursor), IEEE Aerospace 2013",
        ],
        "vehicle": "IPEx (ISRU Pilot Excavator); RASSOR is the TRL-4 precursor/pilot",
        "battery_source": "project lead 2026-06-02: 12S Li-ion, ~30 Ah",
        "geometry": {
            "wheel_diameter_m": WHEEL_DIAMETER_M, "wheel_radius_m": WHEEL_RADIUS_M,
            "skid_steer_track_m": SKID_STEER_TRACK_M, "skid_steer": SKID_STEER,
        },
        "mobility": {
            "obstacle_height_m": OBSTACLE_HEIGHT_M, "nominal_slope_deg": NOMINAL_SLOPE_DEG,
            "slope_test_deg": SLOPE_TEST_DEG,
        },
        "drum_capacity_kg": dict(DRUM_CAPACITY_KG),
        "drum_ops": {
            "regolith_min_threshold_kg": REGOLITH_MIN_THRESHOLD_KG,
            "tangential_to_cut_ratio": TANGENTIAL_TO_CUT_RATIO, "max_cut_depth_frac": MAX_CUT_DEPTH_FRAC,
        },
        "bp1_test_simulant": {
            "bulk_density_kg_m3": BP1_BULK_DENSITY_KG_M3,
            "shear_strength_kpa": list(BP1_SHEAR_STRENGTH_KPA),
            "penetration_kpa": list(BP1_PENETRATION_KPA),
            "note": "terrestrial GMRO test bed (Earth-g); NOT the lunar terramechanics core",
        },
        "published": {
            "mass_class_kg": ROVER_MASS_CLASS_KG, "drive_speed_ms": DRIVE_SPEED_MS,
            "drum_speed_rpm": DRUM_SPEED_RPM, "regolith_per_cycle_kg": REGOLITH_PER_CYCLE_KG,
            "dig_rate_kg_per_hr": DIG_RATE_KG_PER_HR, "total_regolith_kg": list(TOTAL_REGOLITH_KG),
            "traverse_km": TRAVERSE_KM, "mission_days": MISSION_DAYS,
            "scale_factor_rassor2_to_ipex": SCALE_FACTOR,
            "drive_motor_torque_nm": DRIVE_MOTOR_TORQUE_NM,
            "drive_motor_speed_rpm": DRIVE_MOTOR_SPEED_RPM, "n_wheels": N_WHEELS,
            "wheel_gear_ratio": WHEEL_GEAR_RATIO, "arm_excavation_load_nm": ARM_EXCAVATION_LOAD_NM,
            "bus_voltage_tested_v": list(BUS_VOLTAGE_TESTED_V),
            "battery_series_cells": BATTERY_SERIES_CELLS, "battery_capacity_ah": BATTERY_CAPACITY_AH,
        },
        "derived": {
            "battery_energy_wh": round(battery_energy_wh(), 1),
            "battery_energy_mj": round(battery_energy_j() / 1e6, 3),
            "drive_power_w": round(drive_power_w(), 2),
            "drive_energy_per_m_j": round(drive_energy_per_m(), 2),
            "dig_power_w": round(dig_power_w(), 2),
            "dig_energy_per_kg_j": round(dig_energy_per_kg(), 1),
        },
        "planner": {                                  # [CALIB]/operational, not [SCHULER24]
            "sinter_head_power_w": SINTER_HEAD_POWER_W,
            "recharge_power_w": RECHARGE_POWER_W,
            "battery_reserve_frac": BATTERY_RESERVE_FRAC,
        },
    }


# Externalized config overlay (PRD N15 / area O): apply DUSTGYM_<NAME> env vars + the
# DUSTGYM_CONFIG TOML to these published/planner constants. The energy/battery quantities are
# functions that read the constants live, so a 14S override (etc.) recomputes automatically.
from stewie.specs import config as _config  # noqa: E402

_applied_overlay = _config.apply(globals())
if "WHEEL_RADIUS_M" not in _applied_overlay:
    WHEEL_RADIUS_M = WHEEL_DIAMETER_M / 2.0   # derived: recompute from a possibly-overridden diameter
    # (audit M49: an overridden WHEEL_DIAMETER_M left the radius at the old value -> inconsistent
    # wheel geometry between the skid-steer kinematics and the drive chain)


if __name__ == "__main__":
    import json
    print(json.dumps(spec_record(), indent=2))
