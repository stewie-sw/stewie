"""Route handoff checks against the unchanged native Haworth DEM, without a renderer."""
from __future__ import annotations

import asyncio
import json
import math
from pathlib import Path

import numpy as np

from lode.planner_routing import slope_costmap
from stewie.physics.worksite import coarse_base_from_bundle
from stewie.runtime.viz2_runtime import Viz2Runtime
from stewie.specs.ipex_specs import NOMINAL_SLOPE_DEG
from stewie.stream.app import StreamSession
from stewie.stream.protocol import parse_config

BUNDLE = Path(__file__).resolve().parents[2] / "samples/lunar_dem/haworth_sfs_2km_1m"


def exercise_handoff():
    base, metadata = coarse_base_from_bundle(str(BUNDLE))
    height = base.derive_height()
    cell = float(metadata["grid"]["cell_m"])
    bounds = metadata["world_bounds_m"]
    x0, y0 = float(bounds["x0"]), float(bounds["y0"])
    row, col = height.shape[0] // 2, height.shape[1] // 2
    start = (x0 + col * cell, y0 + row * cell)
    goal = (start[0] + 8 * cell, start[1])
    session = StreamSession(parse_config({"start_xy": list(start)}))
    try:
        with Viz2Runtime(str(BUNDLE), session_dir=session.session_dir, start_xy=start) as runtime:
            assert runtime.wait_ready(10)
            route = session._planner_route([goal])
            assert route is not None and route[0] == list(start) and route[-1] == list(goal)
            largest_step = max(math.dist(a, b) for a, b in zip(route, route[1:]))
            assert largest_step <= math.sqrt(2) * cell + 1e-8
            _, passable = slope_costmap(height, cell, max_slope_deg=NOMINAL_SLOPE_DEG)
            for x, y in route:
                assert passable[round((y - y0) / cell), round((x - x0) / cell)]
            blocked = np.argwhere(~passable)
            nearest = blocked[np.argmin(np.sum((blocked - (row, col)) ** 2, axis=1))]
            hazard = (x0 + int(nearest[1]) * cell, y0 + int(nearest[0]) * cell)
            assert session._planner_route([goal, hazard]) is None
            assert session._planner_route([goal, (x0 - cell, y0)]) is None
            assert session._planner_route([]) is None
            assert session._planner_route([goal], max_legs=0) is None
            assert session._plan_goals({"waypoints": [list(goal), list(goal[:1])]}) is None
            assert session._plan_goals({"waypoints": [list(goal)]}) == [goal]
            return {
                "source": str(BUNDLE), "start_xy": start, "goal_xy": goal,
                "native_cell_m": cell, "route_points": len(route),
                "largest_handoff_step_m": largest_step,
                "hazard_cells_at_runtime_threshold": int(np.count_nonzero(~passable)),
                "slope_limit_deg": NOMINAL_SLOPE_DEG, "blocked_goal_xy": hazard,
                "unreachable_leg": "whole mission refused",
                "outside_goal": "whole mission refused",
                "empty_mission": "refused", "excess_legs": "refused",
                "malformed_goal": "refused without dropping the goal",
            }
    finally:
        asyncio.run(session.stop())


def test_native_route_handoff_preserves_corridor_and_complete_intent():
    exercise_handoff()


if __name__ == "__main__":
    print(json.dumps(exercise_handoff(), indent=2))
