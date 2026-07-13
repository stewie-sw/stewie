"""[REQ:GW-12] Float32 render-precision canary for the viz2 site catalogue.

GW-12 requires that "every render surface declares a local origin near the work area and renders float32-
relative to it", and its acceptance pins the largest coordinate handed to a float32 render path under a
documented budget: **ULP < 1 cm**. The /ide and cockpit surfaces honour that (0.98 mm, an 8.69x margin).

**viz2's Godot surface does NOT.** It places nodes at ABSOLUTE lunar coordinates (`state_fields.world_min`
is the bundle's real IAU_2015:30135 corner, and `_pose_x = world_min.x + col*cell_m` flows straight into
float32 Node3D transforms). The south-polar stereographic frame puts these sites 10-164 km from the
projection origin, so the float32 step is SITE-DEPENDENT -- and two bundles viz2 actually SERVES from
`/bundles` breach the 1 cm bound:

    malapert_massif_10km_5m   |coord| 132,000 m -> ULP 15.62 mm   (0.64x margin)  BREACH
    nobile_rim2_10km_5m       |coord| 164,000 m -> ULP 15.62 mm   (0.64x margin)  BREACH

15.6 mm is coarser than the sim's own 13.2 mm anti-bridging bite. The PRACTICAL impact today is small --
both are 5 m-cell DEMs, the authoritative pose is float64 in the python runtime (which is what the HUD
reports), and Godot never sends a world coordinate back -- so this is a render-precision defect, not a
physics one. But it is a real breach of a documented contract, and it is UNGUARDED: nothing in GW-12's own
test covers viz2's Godot path.

THIS TEST IS A CANARY, NOT AN ENDORSEMENT. It pins the exact breaching set so that:

  1. adding a NEW site further from the projection origin trips it immediately, instead of silently
     shipping an even coarser render; and
  2. when the render-origin fix lands (rebase the Godot scene to a local origin -- see the PRD row), the
     breach set becomes EMPTY, this test FAILS, and whoever lands the fix MUST come here and assert the
     empty set. The fix cannot land silently either.

THE FIX (attempted, reverted, diagnosis below). Rebase the Godot scene: keep the true corner as a
`render_origin_m` and make `world_min` the origin, so scene coords span only the SITE extent (<= ~20 km ->
ULP <= 1.2 mm; 0.12 mm over a 2 km window: an 8x+ margin for every site). Safe in principle because the
Godot frame is render-only. A first attempt rendered the terrain and rover correctly but made the ENTIRE
ROCK FIELD vanish: the clasts arrive from the runtime's `clasts.json` in absolute world metres, and after
the rebase they were still landing outside the local frame. The frame-ownership of every world-coordinate
ingest (clasts.json, the `{plan:{route}}` push, the lander) must be established BEFORE retrying, and the
retry must be gated on a before/after render capture -- the regression was invisible to the parse gate and
to the HUD, and only the screenshot caught it.
"""
from __future__ import annotations

import glob
import json
import os

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SITES = os.path.join(REPO, "samples", "lunar_dem")

#: GW-12's documented float32 render budget.
BOUND_M = 0.01

#: The sites that BREACH it today, because viz2 renders at absolute lunar coordinates. Shrinking this set
#: is the goal; growing it is a regression. See the module docstring.
KNOWN_BREACHING = {"malapert_massif_10km_5m", "nobile_rim2_10km_5m"}


def _float32_ulp(magnitude_m: float) -> float:
    f = np.float32(magnitude_m)
    return float(np.nextafter(f, np.float32(np.inf)) - f)


def _max_abs_world_coord(bundle_dir: str) -> float | None:
    try:
        wb = json.load(open(os.path.join(bundle_dir, "metadata.json")))["world_bounds_m"]
    except (OSError, KeyError, ValueError):
        return None
    return max(abs(wb["x0"]), abs(wb["x1"]), abs(wb["y0"]), abs(wb["y1"]))


def _breaching_sites() -> set[str]:
    out: set[str] = set()
    for md in glob.glob(os.path.join(SITES, "*", "metadata.json")):
        d = os.path.dirname(md)
        mx = _max_abs_world_coord(d)
        if mx is not None and _float32_ulp(mx) >= BOUND_M:
            out.add(os.path.basename(d))
    return out


def test_the_float32_render_breach_set_is_exactly_the_known_two() -> None:
    """[REQ:GW-12] Pin the breach. FAILS if a new far-flung site is added (a worse render ships), and FAILS
    once the render-origin fix lands (the set empties) -- so neither can happen silently."""
    breaching = _breaching_sites()
    assert breaching == KNOWN_BREACHING, (
        "the float32 render-bound breach set CHANGED.\n"
        f"  now:      {sorted(breaching)}\n"
        f"  expected: {sorted(KNOWN_BREACHING)}\n"
        "If it GREW: a new site sits further from the projection origin and renders even coarser than the "
        "documented 1 cm bound -- rebase the Godot scene to a local render origin (GW-12) rather than "
        "widening this set.\n"
        "If it SHRANK to empty: the render-origin fix has landed -- assert `set()` here and delete the "
        "KNOWN_BREACHING allowance.")


def test_a_local_render_origin_would_clear_every_site() -> None:
    """[REQ:GW-12] The fix is sound: rendering RELATIVE to a local origin bounds the coordinate by the SITE
    EXTENT, not by its distance from the projection origin. Every site then clears the budget with margin.
    This is what makes the breach worth fixing rather than tolerating."""
    for md in glob.glob(os.path.join(SITES, "*", "metadata.json")):
        wb = json.load(open(md)).get("world_bounds_m")
        if not wb:
            continue
        extent = max(abs(wb["x1"] - wb["x0"]), abs(wb["y1"] - wb["y0"]))     # render-origin-relative span
        ulp = _float32_ulp(extent)
        assert ulp < BOUND_M, (
            f"{os.path.basename(os.path.dirname(md))}: even render-origin-relative, a {extent:.0f} m extent "
            f"has a {ulp*1000:.2f} mm float32 ULP -- the local-origin fix would NOT be sufficient here")
