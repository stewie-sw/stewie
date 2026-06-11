"""SN-08b: full posture x load feasibility coverage."""
from dart import posture_coverage as PC
from stewie.physics import posture_a3 as P


def test_every_posture_evaluated_under_every_load():
    m = PC.posture_load_matrix()
    assert set(m) == set(P.POSTURES)                       # ALL named postures
    for row in m.values():
        assert set(row) == set(PC.LOAD_CONDITIONS)         # ALL load conditions (loaded AND unloaded)
        for cell in row.values():
            assert "margin_m" in cell and "feasible" in cell


def test_one_sided_posture_tips_under_opposing_load():
    """SN-08b [REQ:SN-08]: the coverage finding -- COBRA (front raised) is feasible UNLOADED but
    INFEASIBLE with the REAR drum loaded (cross-load tip). This is why all positions must be tried
    loaded AND unloaded, not just unloaded."""
    m = PC.posture_load_matrix()
    assert m["COBRA"]["unloaded"]["feasible"] is True
    assert m["COBRA"]["rear_loaded"]["feasible"] is False  # opposing-drum load tips it
    assert m["REVERSE_COBRA"]["front_loaded"]["feasible"] is False
    assert m["MEERKAT_1S"]["rear_loaded"]["feasible"] is False


def test_only_symmetric_raises_are_load_robust():
    """The coverage finding: only the SYMMETRIC raised postures (DRUM_WALK, IRON_CROSS) stay feasible
    under EVERY load condition; IRON_CROSS has an identical margin front- vs rear-loaded (balanced)."""
    m = PC.posture_load_matrix()
    for name in ("DRUM_WALK", "IRON_CROSS"):
        assert all(m[name][c]["feasible"] for c in PC.LOAD_CONDITIONS), f"{name} should be load-robust"
    ic = m["IRON_CROSS"]
    assert abs(ic["front_loaded"]["margin_m"] - ic["rear_loaded"]["margin_m"]) < 1e-6


def test_transit_tips_under_a_single_end_load():
    """Honest finding (why all postures must be tried LOADED): TRANSIT is feasible unloaded and with
    BOTH ends loaded (the loads cancel fore/aft), but a SINGLE-end 20 kg drum at full-reach arms drops
    it below the safety margin -- a static low posture is not automatically load-safe."""
    m = PC.posture_load_matrix(load_kg=20.0, min_margin_m=0.05)
    assert m["TRANSIT"]["unloaded"]["feasible"] and m["TRANSIT"]["both_loaded"]["feasible"]
    assert not m["TRANSIT"]["front_loaded"]["feasible"]
    assert not m["TRANSIT"]["rear_loaded"]["feasible"]


def test_feasible_set_shrinks_under_load():
    """The usable viewpoint set is smaller loaded than unloaded -- the honest operational cost."""
    unl = set(PC.feasible_postures("unloaded"))
    rear = set(PC.feasible_postures("rear_loaded"))
    assert rear < unl or len(rear) < len(unl)              # rear load removes the front-raised postures
