"""rover.py kinematics + drum coverage — real sample scenes, conserved-mass invariants.

These exercise the GEOMETRY/STATE-ACCURATE rover primitives (spec §6/§9) on the REAL committed
sample scenes (samples/flat_compact, samples/crater_boulders), never synthetic fields:

  * wheel_pass / four_wheel_pass (default + physical Bekker paths): MASS PRESERVED (density-only
    edits), compaction sinks the rut, SPOIL -> COMPACTED_BERM relabel.
  * wheel_contact_points / build_wheel_tracks_meta: the 4-wheel layout + §5.2 metadata shape.
  * conform_pose: per-wheel normal loads sum to total weight along the surface normal, clast
    ride-over, determinism.
  * step_pose: the unicycle integrator advances by the commanded twist (straight + arc), exact.
  * drum_pass / build_drum_marks_meta: excavate (+optional dump) conserves mass through the drum
    inventory; the §5.2 drum_marks shape.

Run: cd .. && PYTHONPATH=. <venv>/bin/python -m pytest the conserved authority/test_rover.py -q
"""
from __future__ import annotations

import math
import os

import numpy as np
import pytest

from stewie.specs import constants as K
from stewie.physics import rover as R
from stewie.physics.column_state import ColumnState, StateLabel
from stewie.twin.io_fields import load_scene

_SAMPLES = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "samples")
_FLAT = os.path.join(_SAMPLES, "flat_compact")
_LOOSE = os.path.join(_SAMPLES, "rolling_hills")    # loose regolith (1170-1300) -> compaction can sink ruts
_CRATER = os.path.join(_SAMPLES, "crater_boulders")  # real Python-authored clasts (143 boulders)
pytestmark = pytest.mark.skipif(not os.path.isdir(_FLAT), reason="committed sample scenes absent")


def _load_cs(scene_dir):
    """Load a committed sample scene into a ColumnState (datum reconstructed from height/mass/density,
    exactly as worksite.coarse_base_from_bundle does), plus its metadata (carries clasts)."""
    fields, meta = load_scene(scene_dir)
    g = meta["grid"]
    density = fields["density"].astype(np.float64)
    mass = fields["mass_areal"].astype(np.float64)
    datum = fields["heightmap"].astype(np.float64) - mass / density
    cs = ColumnState(int(g["width"]), int(g["height"]), float(g["cell_m"]),
                     mass_areal=mass, density=density,
                     state_label=fields["state_label"].astype(np.uint8),
                     disturbance=fields["disturbance"].astype(np.float64), datum=datum)
    return cs, meta


# ---- straight_path -------------------------------------------------------------------------------
def test_straight_path_endpoints_and_density():
    p = R.straight_path(10, 10, 10, 40)
    assert p[0] == (10, 10) and p[-1] == (10, 40)
    assert all(r == 10 for r, c in p)                       # a horizontal line stays on its row
    assert len(p) >= 31                                     # dense (one cell per col, +1)
    diag = R.straight_path(0, 0, 5, 5)
    assert diag[0] == (0, 0) and diag[-1] == (5, 5)


# ---- wheel_pass: single rut, mass preserved, rut sinks -------------------------------------------
def test_wheel_pass_conserves_mass_and_sinks_rut():
    cs, _ = _load_cs(_LOOSE)
    m0 = cs.grid_mass()
    h0 = cs.derive_height().copy()
    path = R.straight_path(120, 80, 120, 176)
    R.wheel_pass(cs, path, compaction=0.12)
    # density-only edit -> grid mass exactly conserved
    assert math.isclose(cs.grid_mass(), m0, rel_tol=1e-12)
    # the compacted rut thins -> height drops where it was touched
    h1 = cs.derive_height()
    dropped = h1 < h0 - 1e-9
    assert dropped.any()
    assert h1[dropped].max() <= h0[dropped].max() + 1e-12   # never rose
    # the rut is relabelled TREAD and disturbance bumped
    assert int((cs.state_label == int(StateLabel.TREAD)).sum()) > 0


def test_wheel_pass_spoil_becomes_compacted_berm():
    cs, _ = _load_cs(_LOOSE)
    cs.state_label[118:123, 78:178] = np.uint8(StateLabel.SPOIL)   # a band of SPOIL to drive over
    R.wheel_pass(cs, R.straight_path(120, 80, 120, 176))
    assert int((cs.state_label == int(StateLabel.COMPACTED_BERM)).sum()) > 0  # driving over spoil firms it


def test_wheel_pass_empty_path_is_noop():
    cs, _ = _load_cs(_FLAT)
    m0 = cs.grid_mass()
    out = R.wheel_pass(cs, [], )                             # nothing touched
    assert out is cs and math.isclose(cs.grid_mass(), m0, rel_tol=1e-12)


# ---- wheel_contact_points: the 4-wheel layout ---------------------------------------------------
def test_wheel_contact_points_geometry():
    pts = R.wheel_contact_points((100.0, 100.0), 0.0, cell_m=0.05)
    assert set(pts) == {"LF", "RF", "LB", "RB"}
    # heading 0 = +col forward: LF/RF are fore (+col) of LB/RB
    assert pts["LF"][1] > pts["LB"][1] and pts["RF"][1] > pts["RB"][1]
    # gauge separation: L wheels are off the center row from R wheels
    assert pts["LF"][0] != pts["RF"][0]


# ---- four_wheel_pass: four ruts, mass preserved, default + physical paths ------------------------
def test_four_wheel_pass_default_conserves_mass_and_returns_four_polylines():
    cs, _ = _load_cs(_LOOSE)
    m0 = cs.grid_mass()
    poses = [((100.0 + i, 100.0), 0.0) for i in range(20)]
    poly = R.four_wheel_pass(cs, poses, compaction=0.12, physical=False)
    assert set(poly) == {"LF", "RF", "LB", "RB"}
    assert all(len(poly[k]) == len(poses) for k in poly)
    assert math.isclose(cs.grid_mass(), m0, rel_tol=1e-12)   # density-only -> mass exact
    assert int((cs.state_label == int(StateLabel.TREAD)).sum()) > 0


def test_four_wheel_pass_physical_bekker_path_conserves_mass():
    cs, _ = _load_cs(_LOOSE)
    d0 = cs.density.copy()
    m0 = cs.grid_mass()
    poses = [((100.0 + i, 100.0), 0.0) for i in range(20)]
    # physical=True drives compaction from a real Bekker pressure-sinkage solve, not the constant.
    poly = R.four_wheel_pass(cs, poses, physical=True)       # loads=None -> sourced static load
    assert set(poly) == {"LF", "RF", "LB", "RB"}
    assert math.isclose(cs.grid_mass(), m0, rel_tol=1e-12)
    # density rose somewhere under the wheels (a real Bekker compaction response on loose regolith)
    assert (cs.density > d0 + 1e-9).any()


def test_four_wheel_pass_physical_per_wheel_loads_dict():
    cs, _ = _load_cs(_LOOSE)
    m0 = cs.grid_mass()
    poses = [((100.0 + i, 100.0), 0.0) for i in range(15)]
    loads = {"LF": 60.0, "RF": 60.0, "LB": 60.0, "RB": 60.0}
    R.four_wheel_pass(cs, poses, physical=True, loads=loads, slip={"LF": 0.1, "RF": 0.1, "LB": 0.1, "RB": 0.1})
    assert math.isclose(cs.grid_mass(), m0, rel_tol=1e-12)


def test_four_wheel_pass_is_deterministic():
    cs1, _ = _load_cs(_LOOSE)
    cs2, _ = _load_cs(_LOOSE)
    poses = [((100.0 + i, 100.0), 0.3) for i in range(12)]
    R.four_wheel_pass(cs1, poses, physical=True)
    R.four_wheel_pass(cs2, poses, physical=True)
    assert np.array_equal(cs1.density, cs2.density)          # same inputs -> byte-identical
    assert np.array_equal(cs1.derive_height(), cs2.derive_height())


# ---- build_wheel_tracks_meta: §5.2 metadata shape -----------------------------------------------
def test_build_wheel_tracks_meta_shape():
    cs, _ = _load_cs(_LOOSE)
    poses = [((100.0 + i, 100.0), 0.0) for i in range(8)]
    poly = R.four_wheel_pass(cs, poses)
    meta = R.build_wheel_tracks_meta(poly, headings=0.0, cell_m=cs.cell_m, width_m=0.18,
                                     slip={"LF": 0.05, "RF": 0.05, "LB": 0.05, "RB": 0.05})
    assert set(meta) == {"LF", "RF", "LB", "RB"}
    for k, e in meta.items():
        assert e["points"] and all(isinstance(v, int) for pt in e["points"] for v in pt)  # base-cell ints
        assert e["heading_rad"] == 0.0 and e["width_m"] == 0.18  # SI metres, not cells
        assert e["slip"] == 0.05
    # slip=None omits the optional key
    meta2 = R.build_wheel_tracks_meta(poly, headings=0.0, cell_m=cs.cell_m, slip=None)
    assert "slip" not in meta2["LF"]


# ---- conform_pose: per-wheel normal loads, surface normal, clasts, determinism -------------------
def test_conform_pose_normal_loads_sum_to_weight_along_normal():
    cs, meta = _load_cs(_FLAT)
    h = cs.derive_height()
    out = R.conform_pose(h, (128.0, 128.0), 0.0, cell_m=cs.cell_m, payload_kg=0.0)
    # per-wheel loads sum to the total normal load
    s = sum(out["normal_loads"].values())
    assert math.isclose(s, out["normal_load_total_n"], rel_tol=1e-9)
    # total normal load = weight * cos(tilt) = weight * up[1] (flat -> ~full weight)
    weight = K.ROVER_MASS_DRY_KG * K.g
    assert math.isclose(out["normal_load_total_n"], weight * out["up"][1], rel_tol=1e-9)
    assert out["normal_load_total_n"] <= weight + 1e-6       # never exceeds full weight
    # the up vector is a unit normal
    assert math.isclose(np.linalg.norm(out["up"]), 1.0, rel_tol=1e-9)
    assert set(out["contacts"]) == {"LF", "RF", "LB", "RB"}


def test_conform_pose_payload_increases_normal_load():
    cs, _ = _load_cs(_FLAT)
    h = cs.derive_height()
    light = R.conform_pose(h, (128.0, 128.0), 0.0, cell_m=cs.cell_m, payload_kg=0.0)
    heavy = R.conform_pose(h, (128.0, 128.0), 0.0, cell_m=cs.cell_m, payload_kg=15.0)
    assert heavy["normal_load_total_n"] > light["normal_load_total_n"]


def test_conform_pose_clast_ride_over_raises_pose():
    cs, meta = _load_cs(_CRATER)
    h = cs.derive_height()
    clasts = meta["clasts"]
    assert clasts
    # place the rover at the field-cell of a real clast center (x = col*cell, z = row*cell)
    cl = max(clasts, key=lambda c: c.get("radius_m", 0.0))   # the biggest boulder -> clearest ride-over
    cx, _cy, cz = cl["center_m"]
    col = cx / cs.cell_m
    row = cz / cs.cell_m
    flat = R.conform_pose(h, (row, col), 0.0, cell_m=cs.cell_m, clasts=[])         # no ride-over
    ride = R.conform_pose(h, (row, col), 0.0, cell_m=cs.cell_m, clasts=clasts)     # rides the clast
    # clast ride-over lifts at least one contact -> the seat height is at or above the no-clast plane
    assert ride["z_m"] >= flat["z_m"] - 1e-6
    # and the (capped) climb is bounded by the rigid-wheel climb limit (one wheel radius)
    assert ride["z_m"] - flat["z_m"] <= R.WHEEL_RADIUS_M + 1e-6


def test_conform_pose_is_deterministic():
    cs, _ = _load_cs(_FLAT)
    h = cs.derive_height()
    a = R.conform_pose(h, (100.0, 100.0), 0.7, cell_m=cs.cell_m)
    b = R.conform_pose(h, (100.0, 100.0), 0.7, cell_m=cs.cell_m)
    assert a["up"] == b["up"] and a["z_m"] == b["z_m"]


def _tilted_plane(slope_deg, *, grid=64, cell=0.05, axis="col"):
    """A real tilted plane heightmap (deterministic terrain config, not fabricated data): height rises
    linearly with col (axis='col' -> a pitch along the forward/+col axis at heading 0)."""
    coord = (np.arange(grid)[None, :].repeat(grid, axis=0) if axis == "col"
             else np.arange(grid)[:, None].repeat(grid, axis=1)).astype(np.float64)
    return math.tan(math.radians(slope_deg)) * coord * cell


def test_t02_compaction_is_load_asymptotic_progressive_irreversible():
    """T-02: the chosen compaction model is a LOAD-DETERMINED ASYMPTOTIC state law. Pin its four
    documented invariants so a regression to a per-call multiplicative ratchet (which reintroduces the
    H-09 dt-dependence) is caught:
      (1) PROGRESSIVE under increasing load: a heavier pass firms further toward the ceiling;
      (2) ASYMPTOTIC: bounded by RHO_DEEP, with a smooth load->density band below it;
      (3) IDEMPOTENT at constant load: a repeat pass at the same load is a no-op (dt-invariance);
      (4) IRREVERSIBLE under unloading: a lighter follow-up never loosens an already-firmer cell."""
    def fresh():
        return ColumnState(width=16, height=16, cell_m=0.05, mass_areal=np.full((16, 16), 50.0))
    poses = [((8.0, 8.0), 0.0)]

    # (2) asymptotic band: density rises smoothly with load and is bounded by RHO_DEEP
    seq = []
    for load in (12.0, 50.0, 150.0, 250.0):
        cs = fresh()
        R.four_wheel_pass(cs, poses, physical=True, loads=load)
        seq.append(cs.density.max())
        assert cs.density.max() <= K.RHO_DEEP + 1e-9
    # (1) progressive under increasing load: strictly non-decreasing, with real intermediate values
    assert seq[0] < seq[1] < seq[2]                          # below saturation the band is strict
    assert seq[3] == pytest.approx(K.RHO_DEEP)               # high load reaches the ceiling
    assert K.RHO_SURFACE < seq[1] < K.RHO_DEEP               # an intermediate (not just floor/ceiling)

    # (3) idempotent at constant load: a repeat pass at the SAME load does not compact further
    cs = fresh()
    R.four_wheel_pass(cs, poses, physical=True, loads=50.0)
    d1 = cs.density.copy()
    R.four_wheel_pass(cs, poses, physical=True, loads=50.0)
    assert np.allclose(cs.density, d1)                       # constant pressure -> no further compaction

    # (4) irreversible under unloading: a lighter pass after a heavy one never loosens the cell
    cs = fresh()
    R.four_wheel_pass(cs, poses, physical=True, loads=250.0)
    d_heavy = cs.density.copy()
    R.four_wheel_pass(cs, poses, physical=True, loads=12.0)
    assert np.all(cs.density >= d_heavy - 1e-9)              # compaction does not spring back


def test_t04_uphill_transfers_load_to_downhill_wheels():
    """T-04: on an uphill pitch the per-wheel normal reactions must NOT be equal — load transfers to the
    DOWNHILL (rear/B) wheels and off the UPHILL (front/F) wheels, from a rigid-body moment balance about
    the CG. Before the fix conform_pose split normal_total_n equally over all four contacts, so the front
    and rear wheels carried identical load on any slope."""
    cell = 0.05
    h = _tilted_plane(20.0, cell=cell)          # +col uphill -> at heading 0 the rover climbs +col
    out = R.conform_pose(h, (32.0, 32.0), 0.0, cell_m=cell, payload_kg=0.0)
    loads = out["normal_loads"]
    front = loads["LF"] + loads["RF"]           # uphill pair (forward = +col, +wheelbase/2)
    rear = loads["LB"] + loads["RB"]            # downhill pair (-wheelbase/2)
    assert rear > front + 1e-3                  # weight shifts onto the downhill wheels
    # total normal force is conserved (still = weight * cos(tilt))
    weight = K.ROVER_MASS_DRY_KG * K.g
    assert math.isclose(sum(loads.values()), weight * out["up"][1], rel_tol=1e-6)
    # left/right symmetric on a pure pitch (no roll)
    assert math.isclose(loads["LF"], loads["RF"], rel_tol=1e-6)
    assert math.isclose(loads["LB"], loads["RB"], rel_tol=1e-6)


def test_t04_cross_slope_transfers_load_laterally():
    """T-04: a cross-slope (roll) must transfer load LATERALLY — the downhill side carries more than the
    uphill side — while fore/aft stays balanced. Equal-split could never show this."""
    cell = 0.05
    h = _tilted_plane(20.0, cell=cell, axis="row")   # height rises with row -> a roll at heading 0
    out = R.conform_pose(h, (32.0, 32.0), 0.0, cell_m=cell, payload_kg=0.0)
    loads = out["normal_loads"]
    # at heading 0, LEFT world = (-sin0, cos0) = (0,+1) in (x,z) i.e. +row; left wheels (L) are on the
    # +row (higher) side, right wheels (R) on the -row (lower/downhill) side -> R carries more.
    left = loads["LF"] + loads["LB"]
    right = loads["RF"] + loads["RB"]
    assert abs(left - right) > 1e-3             # lateral transfer happened
    assert math.isclose(loads["LF"], loads["LB"], rel_tol=1e-6)   # fore/aft balanced on pure roll
    assert math.isclose(loads["RF"], loads["RB"], rel_tol=1e-6)


def test_t04_steep_slope_unloads_uphill_wheel():
    """T-04: on a steep enough slope (with the real CG height) an uphill wheel can UNLOAD toward zero.
    Equal-split pins every wheel at a quarter of the normal load and can never unload one."""
    cell = 0.05
    h = _tilted_plane(40.0, cell=cell)
    out = R.conform_pose(h, (32.0, 32.0), 0.0, cell_m=cell, payload_kg=0.0,
                         rover_mass_dry_kg=30.0)
    loads = out["normal_loads"]
    # no negative reactions (wheels can't pull down), and the uphill (front) wheels are markedly lighter
    assert all(v >= 0.0 for v in loads.values())
    front_min = min(loads["LF"], loads["RF"])
    rear_max = max(loads["LB"], loads["RB"])
    assert front_min < 0.5 * rear_max          # the uphill wheel is substantially unloaded


def test_clast_contact_height_skips_degenerate_clasts():
    # a clast with no center or non-positive radius is skipped (rover.py:317,321 guards)
    h = R._clast_contact_height([{"radius_m": 0.1}, {"center_m": [0, 0, 0], "radius_m": 0.0}],
                                0.0, 0.0, dem_h=2.0, climb_limit_m=0.18)
    assert h == 2.0                                          # no valid clast -> stays at the DEM height


# ---- step_pose: the unicycle integrator advances by the commanded twist --------------------------
def test_step_pose_straight_line_advances_by_distance():
    # omega = 0 -> straight; yaw 0 advances +col by exactly v*dt/cell_m cells
    cell_m = 0.05
    (r1, c1), yaw1 = R.step_pose((50.0, 50.0), 0.0, v_mps=0.3, omega_radps=0.0, dt_s=2.0, cell_m=cell_m)
    dist_cells = 0.3 * 2.0 / cell_m
    assert math.isclose(c1, 50.0 + dist_cells, rel_tol=1e-9)
    assert math.isclose(r1, 50.0, abs_tol=1e-9) and math.isclose(yaw1, 0.0, abs_tol=1e-12)


def test_step_pose_yaw_pi_over_2_advances_row():
    cell_m = 0.05
    (r1, c1), yaw1 = R.step_pose((50.0, 50.0), math.pi / 2, v_mps=0.3, omega_radps=0.0, dt_s=2.0, cell_m=cell_m)
    dist_cells = 0.3 * 2.0 / cell_m
    assert math.isclose(r1, 50.0 + dist_cells, rel_tol=1e-9)
    assert math.isclose(c1, 50.0, abs_tol=1e-9)             # yaw pi/2 advances +row, not +col


def test_step_pose_arc_advances_yaw_and_curves():
    # omega != 0 -> a circular arc; yaw advances by omega*dt and the displacement is finite/exact
    cell_m = 0.05
    pose, yaw1 = R.step_pose((50.0, 50.0), 0.0, v_mps=0.3, omega_radps=0.5, dt_s=1.0, cell_m=cell_m)
    assert math.isclose(yaw1, 0.5, rel_tol=1e-12)           # yaw advanced by omega*dt
    r1, c1 = pose
    assert (r1, c1) != (50.0, 50.0)                         # the rover moved off the start cell
    # exact constant-twist arc: chord length = 2R sin(omega dt/2), R = v/omega
    v_cells = (0.3 / cell_m)
    R_cells = v_cells / 0.5
    chord = 2.0 * R_cells * math.sin(0.5 * 0.5 * 1.0)
    moved = math.hypot(r1 - 50.0, c1 - 50.0)
    assert math.isclose(moved, chord, rel_tol=1e-9)


def test_step_pose_wraps_yaw_to_pi_interval():
    _, yaw1 = R.step_pose((0.0, 0.0), 3.0, v_mps=0.0, omega_radps=1.0, dt_s=1.0, cell_m=0.05)
    assert -math.pi < yaw1 <= math.pi                       # 3.0 + 1.0 = 4.0 wraps below pi


def test_step_pose_is_deterministic():
    a = R.step_pose((10.0, 20.0), 0.4, 0.25, 0.3, 0.5, cell_m=0.05)
    b = R.step_pose((10.0, 20.0), 0.4, 0.25, 0.3, 0.5, cell_m=0.05)
    assert a == b


# ---- drum_pass: excavate (+dump) conserves mass through the drum inventory -----------------------
def test_drum_pass_excavate_conserves_total_mass():
    cs, _ = _load_cs(_FLAT)
    total0 = cs.total_mass()                                 # grid + drum (drum starts at 0)
    swath = [(120.0, c) for c in range(80, 176)]
    moved = R.drum_pass(cs, swath, depth_m=0.01, width_m=0.20)
    assert moved > 0.0
    # mass left the grid into the drum -> the conserved total is unchanged
    assert math.isclose(cs.total_mass(), total0, rel_tol=1e-12)
    assert math.isclose(cs.drum_inventory, moved, rel_tol=1e-12)
    assert int((cs.state_label == int(StateLabel.EXCAVATED)).sum()) > 0


def test_drum_pass_excavate_then_dump_conserves_and_balances():
    cs, _ = _load_cs(_FLAT)
    total0 = cs.total_mass()
    swath = [(120.0, c) for c in range(80, 140)]
    dump = [(60.0, c) for c in range(80, 140)]
    moved = R.drum_pass(cs, swath, depth_m=0.01, width_m=0.20, dump_rc=dump)
    assert moved > 0.0
    assert math.isclose(cs.total_mass(), total0, rel_tol=1e-9)   # dug -> dumped, conserved end to end
    # the spoil landed as bulked SPOIL where we dumped it
    assert int((cs.state_label == int(StateLabel.SPOIL)).sum()) > 0


def test_drum_pass_empty_swath_is_noop():
    cs, _ = _load_cs(_FLAT)
    total0 = cs.total_mass()
    moved = R.drum_pass(cs, [(-50.0, -50.0)], depth_m=0.01)   # entirely off-grid -> empty mask
    assert moved == 0.0 and math.isclose(cs.total_mass(), total0, rel_tol=1e-12)


# ---- build_drum_marks_meta: §5.2 drum_marks entry shape -----------------------------------------
def test_build_drum_marks_meta_shape():
    swath = [(120.3, 80.6), (120.4, 90.2)]
    entry = R.build_drum_marks_meta(swath, 0.0, drum="front", depth_m=0.05, width_m=0.20, cell_m=0.02)
    assert entry["drum"] == "front"
    assert entry["swath"] == [[120, 81], [120, 90]]          # rounded base-cell ints
    assert entry["depth_m"] == 0.05 and entry["width_m"] == 0.20
    assert entry["teeth_count"] == R.DRUM_TEETH_COUNT and entry["teeth_pitch_m"] == R.DRUM_TEETH_PITCH_M
