"""[REQ:TR-03] The OPERATOR selects the worksite section. The rover spawns where you point, not where the
terrain is flattest.

WHY THIS FILE EXISTS. viz2 always spawned on the FLATTEST INTERIOR SPOT of the tile
(`_flattest_interior_spawn`, [REQ:AS-15]). That was a real fix for a real failure -- it used to spawn at the
tile's blind geometric centre, which can land on a crater wall, so the rover would entrap or tip on arrival
before the operator touched anything. But a SAFETY FALLBACK got hardcoded as THE ONLY BEHAVIOUR, and the
consequence is perverse: it does not merely find flat ground, it finds the FLATTEST GROUND IN THE ENTIRE
TILE. So every session opens on the single most boring 12 m in Haworth -- measured, `haworth_pad_a` has
**0.06 m of relief and a 0.28 deg mean slope** across the whole render window. The terrain looks flat because
IT IS flat. The DEM loads correctly; the float32 height texture is real; the vertex shader displaces. The
picture was honest and the spawn was the bug.

AND THE CAPABILITY WAS ALREADY THERE. `Viz2Runtime(start_xy=...)` is a real constructor parameter and only
falls back to the flattest search when it is None; `viz2_serve.py` already exposes `--start-xy`. The chain
broke in exactly two places -- `protocol.parse_config` had no `start_xy` field, and `app.py` never passed
`--start-xy` when spawning the runtime -- so the browser could not ASK. Same defect shape as the cosmetic arm
(PX-10) and the dead rock seed (TR-01): a real knob with nothing connected to it.

THE PUBLIC-SURFACE RULE. viz2 is reachable by an anonymous browser (RT-06/RT-07). A spawn coordinate is
therefore UNTRUSTED INPUT and is bounds-checked at ingest exactly like the twist (M-04) and the arm angle
(PX-10): non-finite is REFUSED outright, and a coordinate outside the DEM's own world bounds is REFUSED --
never silently clamped into a world that does not exist.

Measured proof this is not cosmetic (same tile, same DEM, no code change):
    haworth_pad_a  (the flattest-search default) : relief 0.06 m, mean slope  0.28 deg
    (-33450.0, 88788.0)                          : relief 3.99 m, mean slope 13.87 deg   -- 66x the relief
There are 544,377 such windows in the tile. The operator was being shown the one flat spot on purpose.
"""
from __future__ import annotations

import json
import os
import tempfile

import numpy as np
import pytest

from stewie.stream import protocol

_SAMPLES = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "samples", "lunar_dem")
SITE = "haworth_sfs_2km_1m"
SFS = os.path.join(_SAMPLES, SITE)
pytestmark = pytest.mark.skipif(not os.path.isdir(SFS), reason="real Haworth SfS bundle not on disk")

#: a REAL sloped, driveable window in the same tile (6-14 deg, inside IPEx's 15 deg nominal envelope).
SLOPED_XY = (-33450.0, 88788.0)


def _bounds() -> dict:
    with open(os.path.join(SFS, "metadata.json"), encoding="utf-8") as fh:
        return json.load(fh)["world_bounds_m"]


def test_the_wire_protocol_carries_an_operator_chosen_spawn() -> None:
    """[REQ:TR-03] THE REQUIREMENT. The browser must be able to ASK for a section. Before this, the config
    had no field for it at all, so the selection could not even be expressed."""
    cfg = protocol.parse_config({"mode": "real", "site": SITE, "start_xy": list(SLOPED_XY)})
    assert cfg.get("start_xy") == pytest.approx(SLOPED_XY), \
        "the operator's chosen section did not survive the wire protocol"


def test_an_unspecified_spawn_still_falls_back_to_the_safe_flattest_search() -> None:
    """[REQ:TR-03] NO REGRESSION. The flattest-interior search exists because the blind geometric centre can
    land on a crater wall and entrap the rover on arrival ([REQ:AS-15]). Selecting a section must make that
    fallback OVERRIDABLE, never absent."""
    cfg = protocol.parse_config({"mode": "real", "site": SITE})
    assert cfg.get("start_xy") is None, "an unchosen spawn must stay None so the safe fallback still runs"


@pytest.mark.parametrize("bad", [
    ["nan", 0.0], [float("nan"), 1.0], [float("inf"), 1.0], [1.0, float("-inf")],
    ["not-a-number", 0.0], [1.0], [1.0, 2.0, 3.0], "34,89", {},
])
def test_a_malformed_spawn_is_refused_outright(bad) -> None:
    """[REQ:TR-03] PUBLIC SURFACE. An anonymous browser can send this. Garbage and non-finite coordinates are
    REFUSED at ingest -- the same discipline as the twist (M-04) and the arm angle (PX-10)."""
    with pytest.raises(protocol.ConfigError):
        protocol.parse_config({"mode": "real", "site": SITE, "start_xy": bad})


def test_a_spawn_outside_the_dem_is_refused_not_clamped() -> None:
    """[REQ:TR-03] You cannot select a section of a world that does not exist. Out-of-bounds is REFUSED, not
    silently clamped to an edge -- a clamp would put the rover somewhere the operator never chose while
    LOOKING like it worked, which is the worse failure.

    NOTE ON WHERE THIS LIVES. The bounds check is NOT in `parse_config`: that module is validation-only and
    does NO I/O by contract (see its docstring), and the tile's extent lives in the bundle metadata. So
    `protocol` owns shape + finiteness (pure), and `app.py` -- which already resolves the bundle -- owns
    bounds. Asserting the pure predicate here keeps the split honest."""
    wb = _bounds()
    inside = ((wb["x0"] + wb["x1"]) / 2.0, (wb["y0"] + wb["y1"]) / 2.0)
    assert protocol.start_xy_in_bounds(inside, wb), "a mid-tile coordinate must be accepted"
    assert protocol.start_xy_in_bounds(None, wb), "an unchosen spawn is always fine (fallback runs)"
    for xy in ((wb["x0"] - 5000.0, wb["y0"] + 10.0),      # west of the tile
               (wb["x1"] + 5000.0, wb["y1"] - 10.0),      # east of the tile
               (wb["x0"] + 10.0, wb["y1"] + 5000.0)):     # north of the tile
        assert not protocol.start_xy_in_bounds(xy, wb), f"{xy} is outside the DEM and must be refused"


def test_the_argv_the_server_builds_is_ACTUALLY_PARSEABLE_by_the_runtime_it_spawns() -> None:
    """[REQ:TR-03] THE GATE THAT SHOULD HAVE EXISTED FIRST -- it did not, and the bug reached production.

    The original version of this test asserted the argv LIST (`"--start-xy" in argv` and the value at the
    next index) and PASSED. But a list of strings is not proof that a program can read them. The server was
    emitting the SEPARATED pair `["--start-xy", "-33450.0,88788.0"]`, and Haworth's x is NEGATIVE in
    IAU_2015:30135 -- so argparse saw a value beginning with '-' and lexed it as an OPTION (its
    negative-number matcher accepts only a BARE number; that string has a comma). Every session over a
    chosen section died at startup with `error: argument --start-xy: expected one argument`, the WS closed,
    and the browser fell into a reconnect storm. The green unit test never noticed.

    So this drives viz2_serve's REAL argparse over the REAL argv the server builds. The `=` form is not a
    style preference -- it is the fix, and this is what proves it."""
    from stewie.runtime.viz2_serve import build_parser
    from stewie.stream import app as app_mod

    argv = app_mod.build_runtime_argv(
        bundle=SFS, session_dir="/tmp/x", fine_cell_m=0.05, start_xy=SLOPED_XY)
    args = build_parser().parse_args(argv[2:])          # argv[0]=python, argv[1]=viz2_serve.py
    assert args.start_xy, "the stream server drops the operator's chosen section on the floor"

    # and the runtime must recover the EXACT coordinate the operator picked (viz2_serve splits on ",")
    xs = args.start_xy.split(",")
    assert (float(xs[0]), float(xs[1])) == pytest.approx(SLOPED_XY), \
        f"the section round-tripped wrong through argv: {args.start_xy!r}"

    # NON-VACUITY: the separated form -- the one that shipped and broke -- must genuinely FAIL to parse.
    broken = [*argv[2:argv.index(f"--start-xy={SLOPED_XY[0]},{SLOPED_XY[1]}")],
              "--start-xy", f"{SLOPED_XY[0]},{SLOPED_XY[1]}"]
    with pytest.raises(SystemExit):                     # argparse exits 2 on "expected one argument"
        build_parser().parse_args(broken)

    # and no chosen section -> NO flag at all, so the runtime's safe flattest fallback still runs
    argv_none = app_mod.build_runtime_argv(
        bundle=SFS, session_dir="/tmp/x", fine_cell_m=0.05, start_xy=None)
    assert not any(a.startswith("--start-xy") for a in argv_none), \
        "an unchosen spawn must leave the safe fallback to the runtime"
    assert build_parser().parse_args(argv_none[2:]).start_xy == ""


def test_the_chosen_section_is_the_section_you_actually_drive() -> None:
    """[REQ:TR-03] End-to-end on the REAL bundle: the runtime honours the choice instead of silently
    re-running the flattest search."""
    from stewie.runtime.viz2_runtime import Viz2Runtime
    with tempfile.TemporaryDirectory() as d:
        rt = Viz2Runtime(SFS, session_dir=d, fine_cell_m=0.05, start_xy=SLOPED_XY)
        try:
            assert rt.start_xy == pytest.approx(SLOPED_XY), "the runtime ignored the operator's section"
        finally:
            rt.stop()


def test_the_selection_is_NOT_cosmetic_it_delivers_real_terrain() -> None:
    """[REQ:TR-03] THE ANTI-DECORATION GATE, and the whole point of the row. A `start_xy` that plumbs
    correctly but lands you on the same flat pad would be worthless. Prove the chosen section carries
    MATERIALLY more relief than the flattest-search default -- i.e. that the operator can actually reach the
    terrain the DEM contains.

    (This is the lesson of the cosmetic arm and the dead seed, applied pre-emptively: wire a knob, then prove
    turning it changes the world.)"""
    from stewie.runtime.viz2_runtime import Viz2Runtime
    reliefs = {}
    for name, xy in (("flattest_default", None), ("operator_chosen", SLOPED_XY)):
        with tempfile.TemporaryDirectory() as d:
            rt = Viz2Runtime(SFS, session_dir=d, fine_cell_m=0.05, start_xy=xy)
            try:
                H = rt.ws._require_fine().derive_height()
                reliefs[name] = float(np.max(H) - np.min(H))
            finally:
                rt.stop()

    flat, chosen = reliefs["flattest_default"], reliefs["operator_chosen"]
    assert flat < 0.30, (
        f"premise moved: the flattest-search default now has {flat:.3f} m of relief; it measured 0.06 m")
    assert chosen > 1.0, (
        f"the operator-chosen section has only {chosen:.3f} m of relief -- it is not real terrain")
    assert chosen > 10.0 * flat, (
        f"choosing a section barely changed the world (flat {flat:.3f} m vs chosen {chosen:.3f} m); the knob "
        "is plumbed but cosmetic")
