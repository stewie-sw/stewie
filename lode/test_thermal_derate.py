"""EP-05: thermal derating must BITE the battery-aware sim, not merely be reported. A cold mission
shrinks the usable pack (thermal_derate), so the rover recharges more often for the same workload;
a warm/None mission is byte-identical to an un-temperatured plan."""
import lode.mission_planner as MP


def _mission(temp_c=None):
    # one large cut far from the charger -> the dig energy needs several recharge cycles
    order = [MP.BuildOrder("big cut", "cut", 100.0, 100.0, 50.0, 0.05)]
    return MP.Mission("derate-test", "moon", order, charger=(0.0, 0.0), temp_c=temp_c)


def test_cold_mission_recharges_more_than_warm():
    warm = MP.plan_and_simulate(_mission(temp_c=None))[4]
    cold = MP.plan_and_simulate(_mission(temp_c=-60.0))[4]    # thermal_derate(-60) hits the 0.5 floor
    assert cold["charges"] > warm["charges"]                  # half the usable pack -> ~2x the recharges
    assert cold["energy_J"] >= warm["energy_J"]               # extra charge-return drive costs more energy


def test_warm_and_none_are_identical_no_derate_above_zero():
    base = MP.plan_and_simulate(_mission(temp_c=None))[4]
    warm = MP.plan_and_simulate(_mission(temp_c=10.0))[4]     # >= 0 C -> derate 1.0
    assert warm["charges"] == base["charges"]
    assert abs(warm["energy_J"] - base["energy_J"]) < 1e-6    # no derate when warm -> identical plan
