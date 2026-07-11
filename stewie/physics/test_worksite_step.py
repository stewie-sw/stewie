"""TDD gates for the per-tick conserved drive seam ``WorkSite.step`` (viz2 PRD Phase B1) and its
NM-7 boundary/displacement safety.

All terrain is REAL: the committed LRO NAC Shape-from-Shading Haworth 1 m bundle
(``haworth_sfs_2km_1m``) for the streaming/boundary/command gates, and a real steep crater-rim
bundle (``shackleton_rim_10km_5m``) for the entrapment gate — the Haworth floor tops out near 23°,
too gentle to entrap, so the slip-runaway is exercised on genuinely steep DEM data rather than a
fabricated ramp. No synthetic terrain, no stubs.

step() must equal a direct drive_step on the same window (byte-identical, gate 1), refuse to mutate
un-verified terrain (gate 2), conserve mass across a step-driven recenter (gate 3), clamp at the site
boundary while still carving (gate 4), turn a fully-out-of-site recenter into a typed refusal that
leaves the session untouched (gate 5), refuse teleport/non-finite commands without moving (gate 6),
and run the real slip/sinkage/entrapment physics per tick (gate 7).
"""
from __future__ import annotations

import os

import numpy as np
import pytest

from stewie.specs import constants as K
from stewie.physics.column_state import ColumnState, StateLabel
from stewie.physics.drive import drive_step
from stewie.physics.worksite import (
    WorkSite,
    WorkSiteBoundsError,
    WorkSiteCommandError,
    WorkSiteDatumError,
    coarse_base_from_bundle,
)

_SAMPLES = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "samples", "lunar_dem")
SFS = os.path.join(_SAMPLES, "haworth_sfs_2km_1m")     # real 1 m SfS Haworth, gentle floor
RIM = os.path.join(_SAMPLES, "shackleton_rim_10km_5m")  # real crater rim, genuine >45° slopes

pytestmark = pytest.mark.skipif(not os.path.isdir(SFS), reason="committed SfS Haworth bundle absent")


def _site(bundle=SFS, **kw):
    kw.setdefault("fine_cell_m", 0.05)
    kw.setdefault("tile_base_cells", 2)
    return WorkSite.from_haworth_bundle(bundle, **kw)


def _xy(site, br, bc):
    return (site.world_x0 + bc * site.base_cell_m, site.world_y0 + br * site.base_cell_m)


def _copy_fine(cs: ColumnState) -> ColumnState:
    """An independent byte-copy of a fine ColumnState (drive_step mutates in place)."""
    return ColumnState(
        int(cs.width), int(cs.height), float(cs.cell_m),
        mass_areal=np.array(cs.mass_areal), density=np.array(cs.density),
        state_label=np.array(cs.state_label), disturbance=np.array(cs.disturbance),
        datum=np.array(cs.datum))


def _fine_digest(cs: ColumnState):
    return (cs.mass_areal.copy(), cs.density.copy(),
            cs.state_label.copy(), cs.disturbance.copy(), cs.datum.copy())


def _assert_fine_unchanged(cs: ColumnState, digest) -> None:
    ma, de, sl, di, da = digest
    assert np.array_equal(cs.mass_areal, ma)
    assert np.array_equal(cs.density, de)
    assert np.array_equal(cs.state_label, sl)
    assert np.array_equal(cs.disturbance, di)
    assert np.array_equal(cs.datum, da)


# --- gate 1: step == a direct drive_step on the same window (byte-identical) -----------------

def test_step_matches_direct_drive_step_byte_identical():
    """One step() over the interior must be BYTE-IDENTICAL to calling drive_step directly on a copy of
    the same window at the same pose/twist — step adds only safety, it never perturbs the physics."""
    s = _site()
    start = _xy(s, 1000, 1000)                              # deep interior -> no clamp, no recenter
    s.recenter(start)
    s.set_pose(start, yaw=0.3)

    ref = _copy_fine(s.fine)
    rc = s.active_rc_for_xy(s.pose_xy)
    exp_rc, exp_yaw, exp_tel = drive_step(
        ref, rc, s.yaw, 0.2, 0.1, dt=0.1, params=None,
        payload_kg=s.inventory_kg, wheel_width_m=0.18, g=K.g)

    tel, dirty = s.step(0.2, 0.1, 0.1)

    # terrain edits identical, field-for-field
    assert np.array_equal(s.fine.mass_areal, ref.mass_areal)
    assert np.array_equal(s.fine.density, ref.density)
    assert np.array_equal(s.fine.state_label, ref.state_label)
    assert np.array_equal(s.fine.disturbance, ref.disturbance)
    assert np.array_equal(s.fine.datum, ref.datum)
    # telemetry identical on every drive_step field
    for key in ("v_achieved", "slip", "sinkage_m", "slope_rad", "contact_len_m",
                "omega_achieved", "entrapped", "rc", "yaw"):
        assert tel[key] == exp_tel[key], key
    assert tel["bounds_clamped"] is False and tel["recentered"] is False


# --- gate 2: datum verified before the first step -------------------------------------------

def test_step_refuses_terrain_that_was_not_datum_verified():
    """The bundle-loaded site is datum-verified (coarse_base_from_bundle asserts the DEM round-trip) and
    step() runs; a WorkSite built from a raw ColumnState is NOT verified and step() refuses to mutate."""
    s = _site()
    assert s.datum_verified is True
    s.recenter(_xy(s, 1000, 1000))
    s.step(0.1, 0.0, 0.1)                                   # verified -> proceeds

    base, meta = coarse_base_from_bundle(SFS)
    wb = meta["world_bounds_m"]
    raw = WorkSite(base, world_x0=float(wb["x0"]), world_y0=float(wb["y0"]),
                   fine_cell_m=0.05, tile_base_cells=2)
    assert raw.datum_verified is False
    raw.recenter(_xy(raw, 1000, 1000))
    with pytest.raises(WorkSiteDatumError):
        raw.step(0.1, 0.0, 0.1)


# --- gate 3: conservation_residual() < 1e-6*baseline across a step-driven recenter -----------

def test_step_conserves_mass_across_a_recenter():
    """Driving straight far enough to slide the streaming window (a step-driven recenter) must keep the
    conserved invariant tiny the whole way — the paged worked state is lossless."""
    s = _site()
    start = _xy(s, 1000, 1000)
    s.recenter(start)
    s.set_pose(start, yaw=0.0)                              # yaw 0 -> advances +col, deep interior
    base = s._baseline_virgin_kg
    recentered_any = False
    for _ in range(150):                                   # ~4.5 m at 0.3 m/s -> crosses tile seams
        tel, _dirty = s.step(0.3, 0.0, 0.1)
        recentered_any = recentered_any or tel["recentered"]
        assert s.conservation_residual() / base < 1e-6
    assert recentered_any                                  # the drive actually forced a window slide
    assert not tel["bounds_clamped"]                       # interior drive never hit the site edge


# --- gate 4: drive INTO the boundary -> pose clamps + flag set + no crash + wheels still carve ---

def test_step_clamps_at_site_boundary_and_still_carves():
    """Driving at v_max toward the site's max corner clamps the pose to world_bounds minus the footprint
    margin (bounds_clamped set), never crashes, and the wheels keep carving a non-empty footprint."""
    s = _site()
    start = (s.world_x1 - 0.1, s.world_y1 - 0.1)            # 10 cm shy of the +x/+y corner
    s.recenter(start)
    s.set_pose(start, yaw=np.pi / 4.0)                      # forward = +row/+col = toward the corner
    before = s.fine.state_label.copy()

    clamped_any = False
    carved_any = False
    for _ in range(20):
        tel, dirty = s.step(s.v_max, 0.0, 0.1)             # full-speed straight at the edge
        clamped_any = clamped_any or tel["bounds_clamped"]
        (r0, c0, r1, c1), = dirty
        assert r1 > r0 and c1 > c0                          # the carved footprint bbox is non-empty
        carved_any = carved_any or bool((s.fine.state_label != before).any())
        # the pose never leaves the interior box (clause 1)
        margin = s._bounds_margin_m(0.1, s.v_max, 0.18)
        px, py = s.pose_xy
        assert s.world_x0 + margin - 1e-9 <= px <= s.world_x1 - margin + 1e-9
        assert s.world_y0 + margin - 1e-9 <= py <= s.world_y1 - margin + 1e-9

    assert clamped_any                                     # it really pressed against the boundary
    assert carved_any                                      # and kept carving there (mask never empty)
    # every wheel mask stayed non-empty: TREAD was actually stamped this run
    assert int((s.fine.state_label == int(StateLabel.TREAD)).sum()) > 0


# --- gate 5: recenter fully outside the site -> typed refusal, session state unchanged --------

def test_recenter_fully_outside_is_typed_refusal_state_unchanged():
    """A recenter target with no covering base tile raises the TYPED WorkSiteBoundsError (not the old
    bare ValueError crash from min() over an empty set) and leaves the session byte-for-byte unchanged."""
    s = _site()
    s.recenter(_xy(s, 1000, 1000))
    digest = _fine_digest(s.fine)
    baseline = s._baseline_virgin_kg
    blocks = set(s.active_blocks)
    store_keys = set(s.worked_store)
    recenters = s.recenters
    last_xy = s._last_rover_xy

    far = (s.world_x1 + 500.0, s.world_y1 + 500.0)          # entirely off the +x/+y corner
    with pytest.raises(WorkSiteBoundsError):
        s.recenter(far)

    _assert_fine_unchanged(s.fine, digest)
    assert s._baseline_virgin_kg == baseline
    assert s.active_blocks == blocks
    assert set(s.worked_store) == store_keys
    assert s.recenters == recenters
    assert s._last_rover_xy == last_xy                     # the OOB target was NOT recorded


# --- gate 6: a command exceeding the bound (or non-finite) -> refused, pose unmoved ----------

@pytest.mark.parametrize("v,omega", [
    (float("nan"), 0.0),      # non-finite
    (0.0, float("inf")),      # non-finite omega
    (10.0, 0.0),              # |v| >> v_max
    (0.1, 100.0),             # |omega| >> omega_max
])
def test_step_refuses_out_of_bound_commands_pose_unmoved(v, omega):
    """M-04: a non-finite or over-bound twist is refused BEFORE any mutation — pose and terrain unmoved."""
    s = _site()
    s.recenter(_xy(s, 1000, 1000))
    s.step(0.1, 0.0, 0.1)                                   # a valid tick to seat the pose
    pose = s.pose_xy
    yaw = s.yaw
    digest = _fine_digest(s.fine)

    with pytest.raises(WorkSiteCommandError):
        s.step(v, omega, 0.1)

    assert s.pose_xy == pose and s.yaw == yaw
    _assert_fine_unchanged(s.fine, digest)


# --- gate 7: real physics per tick — slip rises with slope; entrapment past the steep threshold ---

def test_step_slip_rises_with_real_slope():
    """On the real SfS Haworth DEM, a step on a measurably sloped cell develops more slip than a step on
    a near-flat cell — the conserved slip/sinkage loop runs live per tick (real data, no ramp)."""
    base, _ = coarse_base_from_bundle(SFS)
    h = base.derive_height()
    gy, gx = np.gradient(h, base.cell_m)
    slope = np.hypot(gx, gy)
    interior = slope[400:1600, 400:1600]
    fr, fc = np.unravel_index(int(np.argmin(interior)), interior.shape)   # flattest interior cell
    flat_rc = (fr + 400, fc + 400)
    steep_rc = tuple(int(v) for v in np.unravel_index(int(np.argmax(slope)), slope.shape))

    def _one(brc):
        s = _site()
        xy = _xy(s, *brc)
        s.recenter(xy)
        s.set_pose(xy, yaw=np.pi / 4.0)
        tel, _ = s.step(0.3, 0.0, 0.1)
        return tel

    flat = _one(flat_rc)
    steep = _one(steep_rc)
    assert steep["slope_rad"] > flat["slope_rad"]
    assert steep["slip"] > flat["slip"]
    assert not flat["entrapped"]


@pytest.mark.skipif(not os.path.isdir(RIM), reason="committed steep crater-rim bundle absent")
def test_step_entraps_on_real_steep_rim_conserving():
    """On a real >45° crater-rim cell the per-tick loop drives slip to runaway ENTRAPMENT (wheels spin,
    no forward translation) — the path-dependent failure — while mass stays conserved. Real DEM."""
    base, _ = coarse_base_from_bundle(RIM)
    h = base.derive_height()
    gy, gx = np.gradient(h, base.cell_m)
    slope = np.hypot(gx, gy)
    slope[:40, :] = 0.0; slope[-40:, :] = 0.0             # keep the target off the DEM edge
    slope[:, :40] = 0.0; slope[:, -40:] = 0.0
    steep = tuple(int(v) for v in np.unravel_index(int(np.argmax(slope)), slope.shape))
    grow, gcol = float(gy[steep]), float(gx[steep])
    n = float(np.hypot(grow, gcol))
    yaw = float(np.arctan2(grow / n, gcol / n))            # heading straight up the fall line

    s = _site(bundle=RIM)
    xy = _xy(s, *steep)
    s.recenter(xy)
    s.set_pose(xy, yaw=yaw)
    base_kg = s._baseline_virgin_kg
    tel = None
    for _ in range(6):
        tel, _dirty = s.step(0.3, 0.0, 0.1)

    assert tel["entrapped"] is True
    assert tel["slip"] > 0.9
    assert tel["v_achieved"] == 0.0                        # discrete stuck state — no creep
    assert s.conservation_residual() / base_kg < 1e-6      # entrapment still conserves mass
