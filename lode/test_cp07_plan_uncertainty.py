"""CP-07: plan uncertainty is aggregated into ONE block carrying the named sources into the
feasibility/time/energy picture. Honest: a source gets a numeric figure only where grounded in-repo
(dig-rate energy band, localization corridor margin, DEM cell sigma, operator material factor); drum-fill,
slip, and power-window are named but flagged unquantified (modeled elsewhere, not yet a plan band)."""
import lode.mission_planner as MP

_SOURCES = {"dig_rate", "material", "localization", "dem", "drum_fill", "slip", "power_window"}


def _mk(extra=None):
    p = {"name": "S", "body": "moon", "charger": [0, 0],
         "orders": [{"action": "cut", "kind": "cut", "x": 5.0, "y": 5.0, "footprint_m2": 16.0, "depth_m": 0.3},
                    {"action": "fill", "kind": "fill", "x": 15.0, "y": 15.0, "footprint_m2": 16.0, "depth_m": 0.3}]}
    if extra:
        p.update(extra)
    return MP.mission_from_dict(p)


def test_plan_uncertainty_block_present_and_carries_dig_band():  # [REQ:CP-07]
    tot = MP.plan_and_simulate(_mk())[4]
    pu = tot["plan_uncertainty"]
    assert pu["energy_MJ_band"] == list(tot["dig_energy_bounds_MJ"])   # dig-rate band carried into the block
    assert set(pu["sources"]) == _SOURCES                             # all seven named sources enumerated


def test_honest_quantified_flags():
    pu = MP.plan_and_simulate(_mk())[4]["plan_uncertainty"]["sources"]
    assert pu["dig_rate"]["quantified"] and pu["localization"]["quantified"] and pu["dem"]["quantified"]
    # slip's plan band is the [CALIB] moduli (oracle-gated FIX-1/2) -> honestly flagged unquantified
    assert pu["slip"]["quantified"] is False
    assert pu["material"]["quantified"] is False                      # no operator factor -> baseline
    pu2 = MP.plan_and_simulate(_mk({"dig_energy_factor": 1.5}))[4]["plan_uncertainty"]["sources"]
    assert pu2["material"]["quantified"] is True and pu2["material"]["dig_energy_factor"] == 1.5


def test_drum_fill_carries_a_grounded_cycle_band():  # [REQ:CP-07]
    # CP-07: drum-fill sensing error (DrumSensor FDC MPE, ICE-RASSOR) does NOT change the dig energy --
    # the same total mass must be dug -- but it perturbs the OFFLOAD cycle count, so it carries a +/-MPE
    # band on drum_cycles (the time-relevant quantity), NOT a fabricated energy band.
    tot = MP.plan_and_simulate(_mk())[4]
    df = tot["plan_uncertainty"]["sources"]["drum_fill"]
    assert df["quantified"] is True and df["into"] == "time"
    assert df["mpe_frac"] == MP.RM.FDC_MPE_HALF_FULL and df["cycles"] == float(tot["drum_cycles"])
    lo, hi = df["cycles_band"]
    assert lo < df["cycles"] < hi                                     # a real +/-MPE band straddling the nominal
    assert abs((hi - lo) - 2 * df["mpe_frac"] * df["cycles"]) < 0.05  # band width == 2*MPE*cycles (grounded)


def test_power_window_quantified_only_when_set():
    base = MP.plan_and_simulate(_mk())[4]["plan_uncertainty"]["sources"]
    assert base["power_window"]["quantified"] is False
    w = MP.plan_and_simulate(_mk({"mission_windows": {"work": [[0, 1e12]]}}))[4]["plan_uncertainty"]["sources"]
    assert w["power_window"]["quantified"] is True
