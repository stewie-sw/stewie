"""[REQ:RS-03] the receding-horizon nav loop drives toward goal over a REAL lunar DEM window (a
locally-flat, fully-traversable 60x60 slice of the Haworth tile -- no synthetic terrain), emits EXACTLY
one bounded command per driving tick, and recovers from an injected block / uncertainty."""
import numpy as np
import pytest

from dart.hazard_map import build_hazard_map, plan_route
from stewie.contracts.runtime_spine import TrajectoryCommand
from stewie.runtime.nav_loop import V_CAP_MPS, NavState, nav_tick, run_to_goal


@pytest.fixture(scope="module")
def fixture():
    """A real, traversable Haworth window + its hazard map (probed flattest 60x60 @ 5 m/cell)."""
    from stewie.server import state as S
    dem, _ = S.moon_dem("haworth")
    z, cell = np.asarray(dem[0]), float(dem[1])
    w = z[500:560, 1700:1760]
    hz = build_hazard_map((w, cell), max_slope_deg=25.0)
    start = (5 * cell, 5 * cell)
    goal = (50 * cell, 50 * cell)
    return hz, start, goal, cell


def test_loop_drives_to_goal_emitting_one_bounded_command_per_tick(fixture):
    hz, start, goal, _ = fixture
    st = NavState(x=start[0], y=start[1], goal_x=goal[0], goal_y=goal[1])
    final, cmds = run_to_goal(st, hz, v_max=0.3, step_m=2.0)
    assert final.done and final.status == "arrived"
    assert cmds, "the loop must have lowered commands on the way to goal"
    # every lowered command is a bounded TrajectoryCommand (RS-01), speed within the hard cap.
    for cmd in cmds:
        assert isinstance(cmd, TrajectoryCommand) and cmd.bounded and cmd.kind == "goto"
        assert 0.0 < cmd.v_max_mps <= V_CAP_MPS
    # exactly one command per driving tick: leg_ids are the tick indices, strictly increasing (no batch).
    legs = [c.leg_id for c in cmds]
    assert legs == sorted(legs) and len(set(legs)) == len(legs)


def test_a_single_tick_emits_at_most_one_command(fixture):
    hz, start, goal, _ = fixture
    st = NavState(x=start[0], y=start[1], goal_x=goal[0], goal_y=goal[1])
    _new, cmd = nav_tick(st, hz, v_max=0.3, step_m=2.0)
    assert cmd is None or isinstance(cmd, TrajectoryCommand)   # the return is ONE command, never a list


def test_loop_recovers_from_an_injected_block(fixture):
    hz, start, goal, _ = fixture
    # inject a full NOGO wall between start and goal -> no traversable corridor.
    walled = np.array(hz.cost, copy=True)
    walled[25, :] = np.inf                                     # a wall across the whole window
    hz_blocked = type(hz)(cost=walled, slope_deg=hz.slope_deg, roughness_m=hz.roughness_m,
                          rock_cost=hz.rock_cost, hazard_class=hz.hazard_class, confidence=hz.confidence,
                          cell_m=hz.cell_m, origin=hz.origin)
    assert plan_route(hz_blocked, start, goal) == []          # goal genuinely unreachable
    st = NavState(x=start[0], y=start[1], goal_x=goal[0], goal_y=goal[1])
    new, cmd = nav_tick(st, hz_blocked, v_max=0.3, step_m=2.0)
    assert cmd is None                                        # recover: no motion command into a blocked map
    assert new.recovering and new.status == "recovering"
    # unblock: the SAME loop then makes progress (recovers, does not dead-end).
    _final, cmds = run_to_goal(new, hz, v_max=0.3, step_m=2.0)
    assert cmds and _final.done


def test_uncertain_belief_forces_a_replan(fixture):
    hz, start, goal, _ = fixture
    # a stale/wrong route + uncertain=True must trigger a fresh plan_route and still lower a command.
    st = NavState(x=start[0], y=start[1], goal_x=goal[0], goal_y=goal[1],
                  route=((999.0, 999.0), (998.0, 998.0)))     # a bogus route the loop should discard
    new, cmd = nav_tick(st, hz, v_max=0.3, step_m=2.0, uncertain=True)
    assert cmd is not None                                    # replanned to a real corridor and drove
    assert new.route and new.route[0] != (999.0, 999.0)       # the bogus route was replaced


def test_bounded_command_caps_velocity_at_the_hard_limit(fixture):
    hz, start, goal, _ = fixture
    st = NavState(x=start[0], y=start[1], goal_x=goal[0], goal_y=goal[1])
    _new, cmd = nav_tick(st, hz, v_max=5.0, step_m=2.0)       # ask for 5 m/s
    assert cmd is not None and cmd.v_max_mps == V_CAP_MPS      # bounded down to the IPEx-class cap
