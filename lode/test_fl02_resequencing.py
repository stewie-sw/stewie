"""FL-02 re-sequencing: RESOLVE space-time crowding, not just detect it. `_resolve_spacetime_crowding`
deconflicts the two crowding classes the detectors surface -- stationary work-crowding (`_temporal_conflicts`)
and moving haul-path crossings (`_haul_path_conflicts`) -- by the same FCFS wait the shared charger uses:
the lower vehicle index wins, the higher index (the loser) waits until the winner's span clears. The spans
it acts on are selected to MATCH the detectors, so applying the returned delays drives both detector counts
to 0. No crowding -> all-zero delays (byte-identical fleet). Hand-built timelines exercise the real resolver
+ real detectors; the integration test drives a real mission through plan_multi (no fabricated metrics)."""
import copy

import pytest

import lode.mission_planner as MP


def _work(v_segs):
    """A vehicle whose stationary WORK spans (the _temporal_conflicts class) are (x, y, t0, t1)."""
    return {"tl": [{"kind": "cut", "x0": s[0], "y0": s[1], "x1": s[0], "y1": s[1],
                    "t0": s[2], "t1": s[3]} for s in v_segs]}


def _drive(v_segs):
    """A vehicle whose moving DRIVE legs (the _haul_path_conflicts class) are (x0, y0, x1, y1, t0, t1)."""
    return {"tl": [{"kind": "drive", "x0": s[0], "y0": s[1], "x1": s[2], "y1": s[3],
                    "t0": s[4], "t1": s[5]} for s in v_segs]}


def _shift(per_vehicle, delay):
    """Apply the resolver's per-vehicle wait to the timelines: a vehicle's whole later schedule slides by
    delay[v]. Returns a new per_vehicle so the detectors can be re-run on the RE-SEQUENCED schedule."""
    out = []
    for v, pv in enumerate(per_vehicle):
        d = float(delay[v])
        out.append({"tl": [{**s, "t0": s["t0"] + d, "t1": s["t1"] + d} for s in pv["tl"]]})
    return out


def test_no_crowding_zero_delay():
    # far apart in space (500 m), same time -> nothing to resolve
    pv = [_work([(0, 0, 0.0, 100.0)]), _work([(500, 0, 0.0, 100.0)])]
    assert MP._resolve_spacetime_crowding(pv) == [0.0, 0.0]
    # close in space but DISJOINT in time -> nothing to resolve
    pv2 = [_work([(0, 0, 0.0, 100.0)]), _work([(2, 0, 200.0, 300.0)])]
    assert MP._resolve_spacetime_crowding(pv2) == [0.0, 0.0]


def test_work_crowding_resequences_the_loser():
    # two rovers working 3 m apart at overlapping times -> a real _temporal_conflicts crowding
    pv = [_work([(0, 0, 0.0, 100.0)]), _work([(3, 0, 50.0, 150.0)])]
    assert MP._temporal_conflicts(pv) == 1
    delay = MP._resolve_spacetime_crowding(pv)
    assert delay[0] == 0.0 and delay[1] > 0.0            # lower index wins; the loser (v1) waits
    assert delay[1] >= 100.0 - 50.0                      # at least enough to start after v0's window ends
    assert MP._temporal_conflicts(_shift(pv, delay)) == 0  # applying the wait clears the detected crowding


def test_haul_path_crossing_resequences_the_loser():
    # W->E through origin (t 0..100) vs S->N through origin (t 50..150): a real _haul_path_conflicts crossing
    pv = [_drive([(-10, 0, 10, 0, 0.0, 100.0)]), _drive([(0, -10, 0, 10, 50.0, 150.0)])]
    assert MP._haul_path_conflicts(pv) == 1
    delay = MP._resolve_spacetime_crowding(pv)
    assert delay[0] == 0.0 and delay[1] > 0.0
    assert MP._haul_path_conflicts(_shift(pv, delay)) == 0


def test_three_vehicle_convergence_clears_all_crowding():
    # three rovers crowding the same patch at overlapping times -> every higher index yields, iterated
    pv = [_work([(0, 0, 0.0, 100.0)]), _work([(2, 0, 40.0, 140.0)]), _work([(4, 0, 80.0, 180.0)])]
    assert MP._temporal_conflicts(pv) >= 2
    delay = MP._resolve_spacetime_crowding(pv)
    assert delay[0] == 0.0 and delay[1] > 0.0 and delay[2] > 0.0
    assert MP._temporal_conflicts(_shift(pv, delay)) == 0  # converges to a fully deconflicted schedule


def test_same_vehicle_never_self_crowds():
    # one vehicle's two close-in-space, overlapping-time work spans must NOT produce a self-wait
    pv = [_work([(0, 0, 0.0, 100.0), (1, 0, 50.0, 150.0)])]
    assert MP._resolve_spacetime_crowding(pv) == [0.0]


_ORDERS = [
    {"action": "cutA", "kind": "cut", "x": 20.0, "y": 0.0, "footprint_m2": 9.0, "depth_m": 0.2},
    {"action": "cutB", "kind": "cut", "x": -20.0, "y": 0.0, "footprint_m2": 9.0, "depth_m": 0.2},
    {"action": "fillA", "kind": "fill", "x": 40.0, "y": 0.0, "footprint_m2": 9.0, "depth_m": 0.2},
    {"action": "fillB", "kind": "fill", "x": -40.0, "y": 0.0, "footprint_m2": 9.0, "depth_m": 0.2},
]


def _mk():
    return MP.mission_from_dict({"name": "S", "body": "moon", "charger": [0, 0], "orders": copy.deepcopy(_ORDERS)})


def test_plan_multi_exposes_crowd_wait_and_resequences():  # [REQ:FL-02]
    tot = MP.plan_and_simulate(_mk(), vehicles=2)[4]
    assert "crowd_wait_s" in tot and isinstance(tot["crowd_wait_s"], float) and tot["crowd_wait_s"] >= 0.0
    assert isinstance(tot["crowd_resequenced"], bool)
    # the re-sequencing wait can only DELAY a vehicle, so the resolved makespan never beats the optimistic
    # parallel makespan (which ignores the shared charger AND crowding)
    assert tot["makespan_s"] >= tot["makespan_parallel_s"] - 1e-6


def test_single_vehicle_has_no_crowd_wait_key():
    tot = MP.plan_and_simulate(_mk())[4]
    assert "crowd_wait_s" not in tot               # single-vehicle never enters plan_multi -> byte-identical


# ---- council F26: crowd_wait folds into the idle/survival energy (it extends makespan) ----------
_CROWD_ORDERS = [
    {"action": "cA", "kind": "cut", "x": 10.0, "y": 0.0, "footprint_m2": 16.0, "depth_m": 0.3},
    {"action": "cB", "kind": "cut", "x": 10.0, "y": 2.0, "footprint_m2": 16.0, "depth_m": 0.3},   # 2 m apart
    {"action": "fA", "kind": "fill", "x": 10.0, "y": 1.0, "footprint_m2": 16.0, "depth_m": 0.3},
]


def test_crowd_wait_folds_into_survival_energy(monkeypatch):  # [REQ:FL-02]
    """Council F26: FL-02 space-time crowding waits EXTEND the fleet makespan (they are added into it), so
    the idle-draw survival energy must cover them too. The prior sum omitted crowd_wait_s, undercounting
    idle energy for crowded fleets. With IDLE_POWER_W > 0 and a real crowd wait, survival_energy_J must
    equal idle power times (active per-vehicle time + every queue/crowd/precedence wait)."""
    monkeypatch.setattr(MP, "IDLE_POWER_W", 50.0)                # [ASSUMPTION] 50 W survival load
    m = MP.mission_from_dict({"name": "S", "body": "moon", "charger": [0, 0],
                              "orders": copy.deepcopy(_CROWD_ORDERS)})
    tot = MP.plan_and_simulate(m, vehicles=2)[4]
    assert tot["crowd_wait_s"] > 0.0                             # premise: crowding actually occurred
    active_time = sum(d["time_s"] for d in tot["vehicles_detail"])
    idle_time = (active_time + tot["charger_wait_s"] + tot["crowd_wait_s"] + tot["precedence_wait_s"])
    assert tot["survival_energy_J"] == pytest.approx(50.0 * idle_time)   # crowd_wait_s included
