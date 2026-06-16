"""NV-08: the explicit fault taxonomy. Six fault classes the autonomy executive (NV-09) and the operator
must reason about as first-class states, not ad-hoc checks: TIP (static stability margin exhausted),
ENTRAPMENT (wheel slip in slip-sinkage runaway), LOCALIZATION_DIVERGENCE (pose uncertainty grown past
trust), LOW_ENERGY (battery below operational reserve), THERMAL (temperature outside the actuator qual
range), ACTUATOR (a reported drive/drum/arm fault). `classify_faults` takes the telemetry signals the
existing models already compute (stability.ssa margin, slip ladder, pose-graph sigma, battery fraction,
temperature, actuator status) and returns the active faults with severity (warn/critical); thresholds are
sourced where the codebase has a number and tagged [ASSUMPTION] otherwise.
"""
from __future__ import annotations

from stewie.specs import ipex_specs as S

# --- the six fault classes (NV-08) ---------------------------------------------------------------
TIP = "tip"
ENTRAPMENT = "entrapment"
LOCALIZATION_DIVERGENCE = "localization_divergence"
LOW_ENERGY = "low_energy"
THERMAL = "thermal"
ACTUATOR = "actuator"
FAULT_CLASSES = (TIP, ENTRAPMENT, LOCALIZATION_DIVERGENCE, LOW_ENERGY, THERMAL, ACTUATOR)

# --- thresholds (sourced where the codebase has a number; [ASSUMPTION] otherwise) ----------------
TIP_WARN_DEG = 5.0                          # [ASSUMPTION] SSA margin below this = warn; <= 0 = tipping (stability.py)
SLIP_ENTRAP = 0.95                          # slip ladder: s -> s_max is entrapment/runaway (slip.py)
SLIP_WARN = 0.80                            # [ASSUMPTION] approaching entrapment
LOC_DIVERGED_M = 5.0                        # [ASSUMPTION] 1-sigma pose uncertainty = diverged (cf. Katwijk ATE 3.35 m)
LOC_WARN_M = 2.0                            # [ASSUMPTION] growing pose uncertainty
LOW_ENERGY_RESERVE = S.BATTERY_RESERVE_FRAC  # 0.10 -> below the operational reserve is critical (ipex_specs)
LOW_ENERGY_WARN = 0.20                      # [ASSUMPTION] approaching reserve
ACTUATOR_TMIN_C = -35.0                     # IPEx actuator thermal qual TC2 (ipex_specs.py note, SCHULER24)
ACTUATOR_TMAX_C = 40.0                      # IPEx actuator thermal qual TC2 (ipex_specs.py note, SCHULER24)
THERMAL_WARN_MARGIN_C = 5.0                 # [ASSUMPTION] within this of a qual edge = warn


def classify_faults(*, tip_margin_deg: float | None = None, slip: float | None = None,
                    loc_sigma_m: float | None = None, battery_frac: float | None = None,
                    temp_c: float | None = None, actuator_ok: bool | None = None) -> list:
    """Classify the active faults from the provided telemetry. Each signal is optional -- only what is
    supplied is checked (a None signal is simply not classified). Returns a list of fault records
    {fault, severity ('warn'|'critical'), value, limit, message}, in fault-class order."""
    faults: list = []

    def add(cls, sev, value, limit, msg):
        faults.append({"fault": cls, "severity": sev, "value": value, "limit": limit, "message": msg})

    if tip_margin_deg is not None:
        if tip_margin_deg <= 0.0:
            add(TIP, "critical", tip_margin_deg, 0.0, "static stability margin exhausted -> tipping")
        elif tip_margin_deg < TIP_WARN_DEG:
            add(TIP, "warn", tip_margin_deg, TIP_WARN_DEG, "low tip-over margin")
    if slip is not None:
        if slip >= SLIP_ENTRAP:
            add(ENTRAPMENT, "critical", slip, SLIP_ENTRAP, "wheel slip at entrapment (slip-sinkage runaway)")
        elif slip >= SLIP_WARN:
            add(ENTRAPMENT, "warn", slip, SLIP_WARN, "high slip approaching entrapment")
    if loc_sigma_m is not None:
        if loc_sigma_m >= LOC_DIVERGED_M:
            add(LOCALIZATION_DIVERGENCE, "critical", loc_sigma_m, LOC_DIVERGED_M, "pose uncertainty diverged")
        elif loc_sigma_m >= LOC_WARN_M:
            add(LOCALIZATION_DIVERGENCE, "warn", loc_sigma_m, LOC_WARN_M, "growing pose uncertainty")
    if battery_frac is not None:
        if battery_frac < LOW_ENERGY_RESERVE:
            add(LOW_ENERGY, "critical", battery_frac, LOW_ENERGY_RESERVE, "battery below operational reserve")
        elif battery_frac < LOW_ENERGY_WARN:
            add(LOW_ENERGY, "warn", battery_frac, LOW_ENERGY_WARN, "battery approaching reserve")
    if temp_c is not None:
        if temp_c < ACTUATOR_TMIN_C or temp_c > ACTUATOR_TMAX_C:
            add(THERMAL, "critical", temp_c, (ACTUATOR_TMIN_C, ACTUATOR_TMAX_C),
                "temperature outside the actuator qual range")
        elif temp_c < ACTUATOR_TMIN_C + THERMAL_WARN_MARGIN_C or temp_c > ACTUATOR_TMAX_C - THERMAL_WARN_MARGIN_C:
            add(THERMAL, "warn", temp_c, (ACTUATOR_TMIN_C, ACTUATOR_TMAX_C), "temperature near the qual edge")
    if actuator_ok is not None and not actuator_ok:
        add(ACTUATOR, "critical", False, True, "actuator fault reported")
    return faults


def is_safety_critical(faults) -> bool:
    """True if any active fault is critical -> the executive (NV-09) must pause/fail-safe, not just warn."""
    return any(f["severity"] == "critical" for f in faults)


def fault_summary(faults) -> dict:
    """A compact rollup for the executive / operator: count, the distinct classes, the critical ones, and
    whether a safety-critical fault is present."""
    return {"n": len(faults), "classes": sorted({f["fault"] for f in faults}),
            "critical": sorted(f["fault"] for f in faults if f["severity"] == "critical"),
            "safety_critical": is_safety_critical(faults)}
