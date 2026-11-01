"""Native Haworth route regression checks and repeatable CPU timing.

Run this file directly for timings, or select it explicitly with pytest.
Heights remain unchanged. No generated terrain or cost layers are used.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import time

import numpy as np
import pytest

from lode.planner_routing import MAX_DROP_M, route_least_cost, route_leg, route_leg_inflated, slope_costmap


_SITE = Path(__file__).resolve().parents[1] / "samples/lunar_dem/haworth_sfs_2km_1m"
_HEIGHT_SHA256 = "686dc62484c1d69edf041219a03306946c9742287049f28beed74830659f750c"
_METADATA_SHA256 = "f0c6ef1492212be12639e910f8ce2fe44e618a6a4230632235efe1083edf6b5f"
# Each case: the crop (row, col, size), the slope cap, the endpoints, the crop's sha256, and the expected
# (reached, optimal route cost). The cost is the Dijkstra objective along the returned path, which is unique even
# where tied paths are not; it replaced a sha256 of the whole result (2026-11-01, D-R124), which pinned the last
# bit of numpy's tan/arctan -- and those come from AVX-512 SVML kernels on some CI runners, libm on others.
# Centered crops use safe cells nearest quarter-grid targets, with row-major ties.
# The rugged tile has the most cells above a conservative 10-degree operating cap.
# Tile selection scans complete 256-cell tiles, with row-major ties. This cap is not vehicle qualification.
_CASES = (
    (968, 968, 64, 25.0, (16., 16.), (48., 48.),
     "08e97f2c49088477c3dc07be4bf801e92bcc135c4f9e5b8e0a26c3f1619edd68",
     (True, 47.85428757655659)),
    (936, 936, 128, 25.0, (32., 32.), (96., 96.),
     "6f6bf2615d62d6e94a799cd8a9ae6b40477d2e5edd458514a4d7b097a619e454",
     (True, 96.35390240940285)),
    (872, 872, 256, 25.0, (64., 64.), (192., 192.),
     "102dae06097b91e60da733ac5df6b2d619ef8caba1c7c7d28d2b193047f7eb8f",
     (True, 192.94922306289428)),
    (1024, 1280, 256, 10.0, (64., 64.), (192., 192.),
     "10e5633e2601773df342b8567de0d755a0d0fb11a729fefa3275a2e84f38b330",
     (True, 219.22520379812616)),
    # The first blocked cell in the rugged tile provides a measured unreachable endpoint.
    (1024, 1280, 256, 10.0, (103., 0.), (192., 192.),
     "10e5633e2601773df342b8567de0d755a0d0fb11a729fefa3275a2e84f38b330",
     (False, 0.0)),
    (1024, 1280, 256, 10.0, (64., 64.), (64., 64.),
     "10e5633e2601773df342b8567de0d755a0d0fb11a729fefa3275a2e84f38b330",
     (True, 0.0)),
)


def _native_heights():
    raw = (_SITE / "heightmap.rf32").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == _HEIGHT_SHA256
    assert hashlib.sha256((_SITE / "metadata.json").read_bytes()).hexdigest() == _METADATA_SHA256
    return np.frombuffer(raw, dtype="<f4").reshape(2000, 2000)


def _request(case, heights):
    r0, c0, n, cap, a, b, crop_hash, _ = case
    crop = heights[r0:r0 + n, c0:c0 + n]
    assert hashlib.sha256(crop.tobytes()).hexdigest() == crop_hash
    return crop, cap, a, b


@pytest.mark.parametrize("case", _CASES)
def test_native_route_equivalence_and_safety(case):
    crop, cap, a, b = _request(case, _native_heights())
    result = route_leg((crop, 1.), (0., 0.), a, b, max_slope_deg=cap, return_terms=True)
    assert route_leg((crop, 1.), (0., 0.), a, b, max_slope_deg=cap, return_terms=True) == result
    cost, passable = slope_costmap(crop, 1., max_slope_deg=cap, max_drop_m=MAX_DROP_M)
    length, _, reached, waypoints, terms = result
    want_reached, want_cost = case[-1]
    assert reached is want_reached
    cells = [(int(y), int(x)) for x, y in waypoints]
    path_cost = 0.0                  # the router's edge cost, accumulated as it does
    for (r, c), (nr, nc) in zip(cells, cells[1:]):
        path_cost += math.hypot(nr - r, nc - c) * 0.5 * (float(cost[r, c]) + float(cost[nr, nc]))
    assert path_cost == pytest.approx(want_cost, rel=1e-9, abs=1e-12)
    if not reached:
        assert waypoints == [] and terms == {}
        return
    assert waypoints[0] == a and waypoints[-1] == b
    cells = [(int(y), int(x)) for x, y in waypoints]
    assert all(passable[r, c] for r, c in cells)
    for (r, c), (nr, nc) in zip(cells, cells[1:]):
        assert max(abs(nr - r), abs(nc - c)) == 1
        if r != nr and c != nc:
            assert passable[nr, c] and passable[r, nc]
    # left to right, as the router accumulates: builtin sum() of floats is compensated from Python 3.12
    total = 0.0
    for (r, c), (nr, nc) in zip(cells, cells[1:]):
        total += math.hypot(nr - r, nc - c)
    assert length == total
    assert terms["slope"] == [float(cost[r, c]) for r, c in cells]


def test_native_costmap_rejects_outside_endpoints():
    crop, cap, a, b = _request(_CASES[3], _native_heights())
    cost, passable = slope_costmap(crop, 1., max_slope_deg=cap, max_drop_m=MAX_DROP_M)
    path, length, reached = route_least_cost(cost, passable, 1., (-1, 0), (int(b[1]), int(b[0])))
    assert path == [] and math.isinf(length) and not reached


@pytest.mark.parametrize("footprint_radius_m", (0.0, 1.0))
@pytest.mark.parametrize("return_terms", (False, True))
@pytest.mark.parametrize("origin", ((0.0, 0.0), (100.0, 200.0)))
def test_native_route_endpoint_bounds(footprint_radius_m, return_terms, origin):
    crop, _, _, inside = _request(_CASES[3], _native_heights())
    h, w = crop.shape
    ox, oy = origin
    inside_local = (inside[0] - ox, inside[1] - oy)
    outside = ((-500., -500.), (-0.25, 64.), (64., -0.25),
               (float(w), 64.), (64., float(h)), (float(w) + 0.25, 64.))
    for x, y in outside:
        endpoint = (x - ox, y - oy)
        straight = math.hypot(x - inside[0], y - inside[1])
        expected = (straight, straight, False, [], {}) if return_terms else (straight, straight, False, [])
        for a, b in ((endpoint, inside_local), (inside_local, endpoint)):
            result = route_leg_inflated(
                (crop, 1.), origin, a, b, footprint_radius_m=footprint_radius_m,
                max_slope_deg=10., return_terms=return_terms)
            assert result == expected
    # Boundary-cell interiors remain valid, including fractional positions in the last cell.
    for x, y in ((0., 64.), (64., 0.), (w - 0.25, 64.), (64., h - 0.25)):
        endpoint = (x - ox, y - oy)
        result = route_leg_inflated(
            (crop, 1.), origin, endpoint, endpoint, footprint_radius_m=footprint_radius_m,
            return_terms=return_terms)
        assert len(result) == (5 if return_terms else 4)
        assert result[:3] == (0., 0., True)
        assert result[3] == [(float(int(x)) - ox, float(int(y)) - oy)]


if __name__ == "__main__":
    heights = _native_heights()
    for case in _CASES:
        crop, cap, a, b = _request(case, heights)
        route_leg((crop, 1.), (0., 0.), a, b, max_slope_deg=cap, return_terms=True)
        elapsed = []
        for _ in range(5):
            start = time.perf_counter()
            result = route_leg((crop, 1.), (0., 0.), a, b, max_slope_deg=cap, return_terms=True)
            elapsed.append(time.perf_counter() - start)
        print(json.dumps({"crop_rcn": case[:3], "slope_cap_deg": cap, "a_xy": a, "b_xy": b,
                          "crop_sha256": case[-2], "times_s": elapsed,
                          "result_sha256": hashlib.sha256(json.dumps(result, separators=(",", ":")).encode()).hexdigest()}))
