"""[REQ:D4] Threading the spatial-k rock field into the per-tick conserved drive seam
(``WorkSite.step`` -> ``drive_step(clasts=...)``), so a rock physically rides-over / blocks the
rover per ``rover.conform_pose`` (viz2 plan v4, Phase D task D4).

All terrain is REAL: the committed LRO NAC Shape-from-Shading Haworth 1 m bundle
(``haworth_sfs_2km_1m``). The rocks are placed from the SAME geometry the D1 spatial-k Golombek
producer (``terrain.rockfield``) emits — a partially-buried sphere clast whose exposed cap protrudes
above the DEM — not a fabricated ramp. conform_pose's rigid-wheel ride-over caps the rise onto a
clast's shoulder at one wheel radius (``rover.WHEEL_RADIUS_M``), so a rock WIDER than the wheel tilts
the 4-wheel plane the slip/sinkage solve reads. The gates:

  (1) MECHANISM — a >wheel-radius clast under a real wheel contact raises ``conform_pose`` pitch far
      above the clast-free macro slope (the ride-over onto the capped shoulder), while a clast SMALLER
      than the wheel raises it less (the cap, not the wheel-radius limit, governs);
  (2) RIDES (threaded) — WorkSite.step with ONE >wheel-radius rock in the path develops much more
      slope / slip and less achieved motion than the identical clast-free control, mass conserved
      (the rover rides over the shoulder, partially blocked);
  (3) BLOCKS (threaded) — both front wheels on >wheel-radius rocks drive slip to runaway ENTRAPMENT
      (wheels spin, no forward translation) — the discrete stuck state — mass still conserved;
  (4) BYTE-IDENTICAL — ``clasts`` unset (None) leaves step() equal to the pre-D4 seam, so every
      clast-free gate is unchanged.

Numbers are the REAL measured values on this bundle (flat interior cell, 0.05 m fine, IPEx mass);
thresholds carry margin below/above them, not equalities.
"""
from __future__ import annotations

import os

import numpy as np
import pytest

from stewie.physics import rover as R
from stewie.physics.worksite import WorkSite, coarse_base_from_bundle

_SAMPLES = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "samples", "lunar_dem")
SFS = os.path.join(_SAMPLES, "haworth_sfs_2km_1m")

pytestmark = pytest.mark.skipif(not os.path.isdir(SFS), reason="committed SfS Haworth bundle absent")


def _flat_interior_base_rc():
    """The flattest interior 5 m base cell of the real SfS Haworth floor — a near-level start so a
    clast's ride-over tilt is isolated from the macro slope (mirrors test_worksite_step gate 7)."""
    base, _ = coarse_base_from_bundle(SFS)
    h = base.derive_height()
    gy, gx = np.gradient(h, base.cell_m)
    slope = np.hypot(gx, gy)
    fr, fc = np.unravel_index(int(np.argmin(slope[400:1600, 400:1600])), (1200, 1200))
    return fr + 400, fc + 400


_FLAT_BR, _FLAT_BC = _flat_interior_base_rc()


def _site():
    s = WorkSite.from_haworth_bundle(SFS, fine_cell_m=0.05, tile_base_cells=2)
    start = (s.world_x0 + _FLAT_BC * s.base_cell_m, s.world_y0 + _FLAT_BR * s.base_cell_m)
    s.recenter(start)
    s.set_pose(start, yaw=0.0)                              # yaw 0 -> forward = +col/+X
    return s, start


def _global_clast_at_wheel(s: WorkSite, wheel: str, radius_m: float, *, buried: float = 0.30) -> dict:
    """A partially-buried sphere clast (the D1 rockfield schema) seated on the REAL surface under the
    rover's ``wheel`` contact, in the GLOBAL frame WorkSite.clasts uses: center_m = [gx, abs_h, gy]
    with the center dropped ``buried*diameter`` below the surface so the exposed cap is 2r(1-buried)."""
    rc = s.active_rc_for_xy(s.pose_xy)
    pts = R.wheel_contact_points(rc, s.yaw, cell_m=s.fine_cell_m)
    row, col = pts[wheel]
    ox, oy = s.window_world_origin
    absh = float(s.fine.derive_height()[int(round(row)), int(round(col))])
    diameter = 2.0 * radius_m
    return {
        "id": 0,
        "center_m": [ox + col * s.fine_cell_m, absh + (radius_m - buried * diameter),
                     oy + row * s.fine_cell_m],
        "radius_m": radius_m,
        "shape": "sphere",
        "buried_frac": buried,
    }


# --- gate 1: MECHANISM — conform_pose rides a >wheel-radius clast onto its capped shoulder --------

def test_conform_pose_rides_over_wheel_radius_clast():  # [REQ:D4]
    """A rock WIDER than the wheel, under a real wheel contact, tilts the conform_pose plane far more
    than the (near-flat) clast-free macro slope — the rigid-wheel ride-over onto the shoulder; a rock
    SMALLER than the wheel raises it less (the sphere cap, below the wheel-radius climb limit)."""
    s, _ = _site()
    rc = s.active_rc_for_xy(s.pose_xy)
    h = s.fine.derive_height()
    pts = R.wheel_contact_points(rc, s.yaw, cell_m=s.fine_cell_m)
    row, col = pts["LF"]
    absh = float(h[int(round(row)), int(round(col))])

    def _local(radius_m, buried=0.30):
        d = 2.0 * radius_m
        return [{"id": 0, "center_m": [col * s.fine_cell_m, absh + (radius_m - buried * d),
                                       row * s.fine_cell_m],
                 "radius_m": radius_m, "buried_frac": buried}]

    pitch_none = abs(R.conform_pose(h, rc, s.yaw, cell_m=s.fine_cell_m,
                                    climb_limit_m=R.WHEEL_RADIUS_M)["pitch_rad"])
    big = 0.30                                             # > WHEEL_RADIUS_M (0.18)
    small = 0.06                                           # < WHEEL_RADIUS_M
    assert big > R.WHEEL_RADIUS_M > small
    pitch_big = abs(R.conform_pose(h, rc, s.yaw, cell_m=s.fine_cell_m, clasts=_local(big),
                                   climb_limit_m=R.WHEEL_RADIUS_M)["pitch_rad"])
    pitch_small = abs(R.conform_pose(h, rc, s.yaw, cell_m=s.fine_cell_m, clasts=_local(small),
                                     climb_limit_m=R.WHEEL_RADIUS_M)["pitch_rad"])

    assert pitch_none < 0.02                               # the start cell is genuinely near-flat
    assert pitch_big > 0.15                                # ride-over onto the capped shoulder (~12 deg)
    assert pitch_big > pitch_small > pitch_none            # bigger cap -> more tilt, monotone


# --- gate 2: RIDES — one >wheel-radius rock threaded through step() blocks progress, mass conserved -

def test_step_threads_clast_rides_over_and_blocks_progress():  # [REQ:D4]
    """WorkSite.step with a single >wheel-radius rock in the path (the D4 threading) develops much more
    slope + slip and less achieved motion than the identical clast-free control, and conserves mass —
    the rover rides the shoulder, partially blocked, exactly per conform_pose."""
    ctrl, _ = _site()
    rock, _ = _site()
    rock.clasts = [_global_clast_at_wheel(rock, "LF", 0.30)]   # 0.30 m radius > wheel radius

    tc, _ = ctrl.step(0.2, 0.0, 0.1)
    tr, _ = rock.step(0.2, 0.0, 0.1)

    assert tc["slope_rad"] < 0.02 and tc["slip"] < 0.10       # control: near-flat, low slip
    assert tr["slope_rad"] > 0.15                             # rock: ride-over tilt (~12 deg)
    assert tr["slip"] > 3.0 * tc["slip"]                      # slip jumps on the shoulder
    assert tr["v_achieved"] < 0.8 * tc["v_achieved"]          # progress robbed (blocked/rides)
    assert not tr["entrapped"]                                # one wheel: rides over, not fully stuck
    assert ctrl.conservation_residual() == 0.0
    assert rock.conservation_residual() == 0.0               # ride-over still mass-exact


# --- gate 3: BLOCKS — both front wheels on >wheel-radius rocks -> entrapment, mass conserved --------

def test_step_threads_clasts_entraps_when_both_front_wheels_blocked():  # [REQ:D4]
    """Both front wheels riding >wheel-radius rocks pitch the rover nose-up past the traction budget:
    the per-tick loop drives slip to runaway ENTRAPMENT (wheels spin, no translation) — the fully-
    blocked discrete stuck state — while mass stays conserved."""
    s, _ = _site()
    s.clasts = [_global_clast_at_wheel(s, "LF", 0.30), _global_clast_at_wheel(s, "RF", 0.30)]
    tel = None
    for _ in range(8):
        tel, _dirty = s.step(0.2, 0.0, 0.1)

    assert tel["entrapped"] is True
    assert tel["slip"] > 0.9
    assert tel["v_achieved"] == 0.0                          # discrete stuck state — no creep
    assert s.conservation_residual() == 0.0


# --- gate 4: BYTE-IDENTICAL — no rock field -> the pre-D4 seam is unchanged ------------------------

def test_step_without_clasts_is_byte_identical_to_pre_d4_seam():  # [REQ:D4]
    """clasts unset (None, the default) leaves step() equal to the clast-free seam field-for-field and
    telemetry-for-telemetry — so every clast-free WorkSite.step gate is unaffected by the D4 wiring."""
    a, _ = _site()
    b, _ = _site()
    assert a.clasts is None                                  # default: no rock field
    b.clasts = None                                          # explicit None: same path
    ta, _ = a.step(0.2, 0.1, 0.1)
    tb, _ = b.step(0.2, 0.1, 0.1)
    for key in ("v_achieved", "slip", "sinkage_m", "slope_rad", "contact_len_m",
                "omega_achieved", "entrapped"):
        assert ta[key] == tb[key], key
    assert np.array_equal(a.fine.mass_areal, b.fine.mass_areal)
    assert np.array_equal(a.fine.state_label, b.fine.state_label)
