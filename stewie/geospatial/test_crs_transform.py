"""[REQ:BA-05] frame-transform chain: Godot<->REP-103 round-trips + body<->site_enu georef round-trip."""
import pytest

from stewie.geospatial import crs_transform as X


def test_godot_rep103_round_trips_a_control_point():  # [REQ:BA-05]
    for p in [(1.0, 2.0, 3.0), (-0.5, 0.0, 4.2), (0.0, 0.0, 0.0), (7.0, -3.0, 0.25)]:
        back = X.godot_to_rep103(*X.rep103_to_godot(*p))
        assert all(abs(a - b) < 1e-12 for a, b in zip(p, back)), f"{p} -> {back} not identity"


def test_rep103_axes_map_to_godot_per_the_sidecar_convention():  # [REQ:BA-05]
    # sidecar.gd: the Z-up spin axis (0,1,0) maps to Godot (0,0,-1); the Z-up (up) unit maps to Godot +Y.
    assert X.rep103_to_godot(0.0, 1.0, 0.0) == (0.0, 0.0, -1.0)
    assert X.rep103_to_godot(0.0, 0.0, 1.0) == (0.0, 1.0, 0.0)
    assert X.rep103_to_godot(1.0, 0.0, 0.0) == (1.0, 0.0, 0.0)  # x-forward is shared


def test_frame_chain_covers_the_six_seams_in_order():  # [REQ:BA-05]
    frames = ["body_crs", "site_enu", "map", "odom", "base_link", "sensors"]
    seams = [(a, b) for a, b, _ in X.FRAME_CHAIN]
    for a, b in zip(frames, frames[1:]):
        assert (a, b) in seams, f"the transform chain is missing the {a}->{b} seam"


def test_body_site_enu_round_trips_a_control_point():  # [REQ:BA-05]
    # reuse the REAL Haworth georef (site_dem): an INTERIOR local ENU point (the DEM origin frame is +x,+y
    # into the north-up tile) -> lat/lon -> back. The round-trip snaps to the DEM pixel grid, so the error
    # is bounded by one cell.
    try:
        from stewie.terrain.site_dem import dem_grid_info
        cell = float(dem_grid_info()["cell_m"])
        x, y = 100.0, 150.0
        lat, lon = X.site_enu_to_body(x, y)
        bx, by = X.body_to_site_enu(lat, lon)
    except ImportError:
        pytest.skip("pyproj (the [planner] extra) not installed")
    except FileNotFoundError:
        pytest.skip("Haworth DEM bundle not present")
    assert abs(bx - x) <= cell and abs(by - y) <= cell, \
        f"({x},{y}) -> ({lat:.6f},{lon:.6f}) -> ({bx:.2f},{by:.2f}); cell={cell}"
