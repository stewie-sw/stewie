"""NV-08: the explicit fault taxonomy. Each of the six fault classes triggers at its grounded threshold
(battery reserve 0.10 from ipex_specs; actuator thermal qual -35/+40 C; slip-ladder entrapment; SSA tip
margin), warn vs critical is distinguished, and the safety-critical rollup gates the executive."""
from lode import faults as F
from stewie.specs import ipex_specs as S


def _classes(faults):
    return {f["fault"]: f["severity"] for f in faults}


def test_nv08_six_named_fault_classes_exist():
    """[REQ:NV-08] tip, entrapment, localization divergence, low energy, thermal, actuator are explicit."""
    assert set(F.FAULT_CLASSES) == {F.TIP, F.ENTRAPMENT, F.LOCALIZATION_DIVERGENCE,
                                    F.LOW_ENERGY, F.THERMAL, F.ACTUATOR}


def test_nv08_nominal_telemetry_has_no_faults():
    out = F.classify_faults(tip_margin_deg=20.0, slip=0.1, loc_sigma_m=0.5, battery_frac=0.8,
                            temp_c=10.0, actuator_ok=True)
    assert out == [] and F.is_safety_critical(out) is False


def test_nv08_tip_margin_exhausted_is_critical():
    assert _classes(F.classify_faults(tip_margin_deg=0.0))[F.TIP] == "critical"
    assert _classes(F.classify_faults(tip_margin_deg=3.0))[F.TIP] == "warn"      # low but positive margin


def test_nv08_slip_entrapment_is_critical():
    assert _classes(F.classify_faults(slip=0.97))[F.ENTRAPMENT] == "critical"
    assert _classes(F.classify_faults(slip=0.85))[F.ENTRAPMENT] == "warn"


def test_nv08_low_energy_keys_on_the_real_reserve_fraction():
    # below the sourced 10% operational reserve -> critical; just above -> warn
    assert _classes(F.classify_faults(battery_frac=S.BATTERY_RESERVE_FRAC - 0.01))[F.LOW_ENERGY] == "critical"
    assert _classes(F.classify_faults(battery_frac=0.15))[F.LOW_ENERGY] == "warn"
    assert F.classify_faults(battery_frac=0.50) == []                            # healthy pack -> nothing


def test_nv08_thermal_keys_on_the_actuator_qual_range():
    assert _classes(F.classify_faults(temp_c=-40.0))[F.THERMAL] == "critical"     # below -35 C qual
    assert _classes(F.classify_faults(temp_c=45.0))[F.THERMAL] == "critical"      # above +40 C qual
    assert _classes(F.classify_faults(temp_c=-32.0))[F.THERMAL] == "warn"         # within 5 C of the edge


def test_nv08_localization_divergence_and_actuator():
    assert _classes(F.classify_faults(loc_sigma_m=6.0))[F.LOCALIZATION_DIVERGENCE] == "critical"
    assert _classes(F.classify_faults(loc_sigma_m=3.0))[F.LOCALIZATION_DIVERGENCE] == "warn"
    assert _classes(F.classify_faults(actuator_ok=False))[F.ACTUATOR] == "critical"


def test_nv08_summary_and_safety_critical_rollup():
    faults = F.classify_faults(tip_margin_deg=-1.0, slip=0.85, battery_frac=0.5)   # 1 critical + 1 warn
    summ = F.fault_summary(faults)
    assert summ["n"] == 2 and summ["safety_critical"] is True
    assert F.TIP in summ["critical"] and F.ENTRAPMENT not in summ["critical"]      # warn not in critical list
    assert set(summ["classes"]) == {F.TIP, F.ENTRAPMENT}
