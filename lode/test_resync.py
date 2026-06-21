"""#70 (rung 2): the RESYNC protocol -- telemetry-corrected forward simulation.

John's framing: "simulate movements at faster than realtime with multiple possible inputs, and
compare outcomes. It should resync often and continue simulating the future." Honest framing:
input iteration over the existing terramechanics; the NEW piece is resync (a real observation
corrects the believed state, and the futures re-simulate from the corrected state).
"""
from lode import mission_planner as MP
from lode import resync as RS


def _mission():
    return MP.mission_from_dict({"name": "rs", "body": "moon", "charger": [0, 0], "orders": [
        {"action": "a", "kind": "cut", "x": 12, "y": 0, "footprint_m2": 16, "depth_m": 0.05},
        {"action": "b", "kind": "fill", "x": 30, "y": 8, "footprint_m2": 16, "depth_m": 0.05},
        {"action": "c", "kind": "cut", "x": 55, "y": 30, "footprint_m2": 16, "depth_m": 0.05},
        {"action": "d", "kind": "fill", "x": 14, "y": 2, "footprint_m2": 16, "depth_m": 0.05},
    ]})


def test_resync_corrects_a_drifted_belief():
    """[REQ:CP-05] a pose observation pulls the believed state toward truth and SHRINKS sigma."""
    from lode.autonomy import initial_belief, predict
    b = initial_belief(_mission(), 4)
    b = predict(b, moved_to=(10.0, 0.0), drive_m=10.0, odom_drift_frac=0.05, energy_spent_J=0.0)
    drifted_err = abs(b.x - 10.4)                          # the drifted belief is off truth
    corrected = RS.resync(b, observation={"x": 10.4, "y": 0.1, "pos_sigma_m": 0.12})
    assert abs(corrected.x - 10.4) < drifted_err + 1e-9    # pulled toward the observation
    assert corrected.pos_sigma_m <= min(b.pos_sigma_m, 0.12) + 1e-9   # fused sigma shrinks


def test_forward_compare_ranks_candidate_futures():
    """Faster-than-realtime futures: candidate solver inputs re-simulated from the CURRENT
    state, ranked by outcome -- the operator sees the comparison, not a single oracle answer."""
    m = _mission()
    out = RS.forward_compare(m, candidates=("nearest", "two_opt"), objective="duration")
    assert len(out["futures"]) == 2
    names = [f["algorithm"] for f in out["futures"]]
    assert "nearest" in names and "two_opt" in names
    for f in out["futures"]:
        assert f["time_s"] > 0 and f["energy_MJ"] > 0 and f["wall_s"] < 30.0
    # ranked best-first on the objective
    assert out["futures"][0]["time_s"] <= out["futures"][-1]["time_s"] + 1e-9
    assert out["recommended"] == out["futures"][0]["algorithm"]


def test_forward_compare_exposes_feasibility_first_fields():
    """REHEARSE (mission-ops screen 2): every candidate future carries the FEASIBILITY-FIRST review
    fields -- feasible + infeasible_reasons, return-to-lander margin, objective completion, charges --
    drawn from the same conserved planner totals (no fabricated numbers)."""
    m = _mission()
    out = RS.forward_compare(m, candidates=("nearest", "two_opt"), objective="duration")
    for f in out["futures"]:
        assert isinstance(f["feasible"], bool)
        assert isinstance(f["infeasible_reasons"], list)
        # return-to-lander block carried straight from totals (#161): feasible + margin
        assert isinstance(f["return_to_lander"]["feasible"], bool)
        assert "margin_J" in f["return_to_lander"]
        # objective completion: how many of the mission's orders the plan resolves into trips
        assert f["objectives_total"] >= 1
        assert f["charges"] >= 0


def test_forward_compare_never_ranks_infeasible_above_feasible():
    """The screen-2 INVARIANT: a feasible candidate is ALWAYS ranked above an infeasible one, even when
    the infeasible candidate would score better on the raw objective. The recommendation is the head of a
    feasible-first ordering, and is None when no candidate is feasible."""
    # two synthetic futures (the ordering rule is pure, so we test it on the public sort directly):
    # an infeasible candidate that is FASTER must still sort BELOW a slower feasible one.
    fast_infeasible = {"algorithm": "x", "time_s": 10.0, "energy_MJ": 1.0, "feasible": False}
    slow_feasible = {"algorithm": "y", "time_s": 99.0, "energy_MJ": 9.0, "feasible": True}
    ranked = RS.rank_feasible_first([fast_infeasible, slow_feasible], objective="duration")
    assert ranked[0]["algorithm"] == "y"          # feasible first, despite being slower
    assert ranked[1]["algorithm"] == "x"
    # all-infeasible -> still ordered by objective, but recommended is None at the route layer
    both_bad = RS.rank_feasible_first(
        [{"algorithm": "a", "time_s": 5.0, "feasible": False},
         {"algorithm": "b", "time_s": 3.0, "feasible": False}], objective="duration")
    assert [f["algorithm"] for f in both_bad] == ["b", "a"]   # objective order within the infeasible group


def test_resync_graph_fuses_multiple_factors():
    """#78 [REQ:CP-06]: the graph resync fuses DEM + shadow fixes jointly; sigma shrinks below
    either single fix and the estimate sits between the factors, prior-weighted."""
    from lode.autonomy import initial_belief, predict
    from lode import resync as RS
    b = initial_belief(_mission(), 4)
    b = predict(b, moved_to=(10.0, 0.0), drive_m=10.0, odom_drift_frac=0.2, energy_spent_J=0.0)
    out = RS.resync_graph(b, [{"x": 10.4, "y": 0.1, "pos_sigma_m": 0.15},
                              {"x": 10.2, "y": -0.1, "pos_sigma_m": 0.20}])
    assert out.pos_sigma_m < 0.15                       # two fixes beat the best single one
    assert 10.0 < out.x < 10.5                          # pulled into the fix cluster


def test_resync_se2_fuses_odometry_imu_and_fix():
    """#78: the SE(2) resync wrapper fuses body-frame odo + a gyro yaw factor + an absolute fix,
    returning a heading-aware corrected pose with shrunk sigma."""
    from lode.autonomy import initial_belief
    from lode import resync as RS
    b = initial_belief(_mission(), 4)
    out = RS.resync_se2(b, between=((1.0, 0.0, 0.2), 0.1, 0.3), imu_yaw=(0.1, 0.02),
                        observations=[{"x": 1.0, "y": 0.05, "pos_sigma_m": 0.05}])
    assert "yaw" in out and abs(out["yaw"] - 0.1) < 0.15      # gyro pulled the heading
    assert out["xy_sigma"] < 0.5                             # the fix tightened position
