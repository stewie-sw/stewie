"""P6 LIVE-LOOP dense perception (CP-09 'I': observability CONSUMED in the live closed loop).

The producer (dart.observed_map / dart.map_channel) renders + scores an observed map as a TESTED tier.
These tests prove the CLOSED LOOP (lode.autonomy.run_closed_loop) now CONSUMES it at the dig decision
point: a rover whose PRIOR dig built a self-made hazard (a berm the stale belief does not carry) OBSERVES
that as-built through a REAL nadir depth render and REACTS -- the in-loop decision changes (it defers +
re-surveys before the irreversible next dig) versus the same loop with no dense perception.

The observed map is a REAL Godot render: the CI-safe test decodes the COMMITTED real-render fixture
(predig/postdig crater_boulders depth PNGs; matplotlib decode, no GPU/cv2), and a separate live test
re-runs the on-host render inside the loop and skips on a bare runner. No synthetic terrain, no fabricated
depth -- the divergence that flips the decision is a real observation of the rover's own conserved as-built.

CC0-1.0 (see ../LICENSE).
"""
from __future__ import annotations

import json
import os

import numpy as np
import pytest

pytest.importorskip("matplotlib")   # the fixture decode uses matplotlib.image (the planning/dev dep, cv2-free)

from dart import map_channel as MC     # noqa: E402
from dart import observed_map as OM     # noqa: E402
from lode import autonomy as A          # noqa: E402
from lode import mission_planner as MP  # noqa: E402

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.normpath(os.path.join(_HERE, ".."))
_FIX = os.path.join(_REPO, "dart", "fixtures", "observed_map")
_SCENE = os.path.join(_REPO, "samples", "crater_boulders")
_BORDER = 3   # trim the partial-observation edge ring (mesh stops at cell centres), as the producer test does


def _have_fixture() -> bool:
    return (os.path.isfile(os.path.join(_FIX, "fixture_meta.json"))
            and os.path.isfile(os.path.join(_FIX, "postdig_depth.png")))


def _two_dig_mission():
    """Two cuts -> two dig legs; the SECOND dig's gate sees the terrain the FIRST dig reshaped."""
    return MP.mission_from_dict({"name": "hz", "body": "moon", "charger": [0, 0], "orders": [
        {"action": "cut near", "kind": "cut", "x": 1.2, "y": 1.2, "footprint_m2": 1.0, "depth_m": 0.05},
        {"action": "cut berm", "kind": "cut", "x": 3.2, "y": 3.2, "footprint_m2": 1.0, "depth_m": 0.05}]})


class _FixtureDensePerception:
    """Injects the COMMITTED real-render fixture (post-dig crater_boulders nadir depth) as the loop's
    dense observation, so CI exercises the in-loop DECISION without a live Godot render. The observed map
    is a REAL render (decoded from the committed PNG); the belief is the real pre-dig heightmap; the site
    region is the fixture's berm footprint. Returns None until a prior dig has reshaped the terrain
    (``built`` non-empty), mirroring the live provider's guard -- so the first dig is never deferred."""

    def __init__(self):
        self._cache = None

    def _load(self):
        if self._cache is None:
            obs, mask = OM.decode_nadir_depth(os.path.join(_FIX, "postdig_depth.png"),
                                              os.path.join(_FIX, "postdig_depth.json"))
            belief = np.fromfile(os.path.join(_SCENE, "heightmap.rf32"),
                                 dtype="<f4").reshape(obs.shape).astype(float)
            with open(os.path.join(_FIX, "fixture_meta.json")) as f:
                br0, bc0, br1, bc1 = json.load(f)["berm_rc"]
            berm = np.zeros(obs.shape, dtype=bool)
            berm[br0:br1, bc0:bc1] = True
            inner = np.zeros(obs.shape, dtype=bool)
            inner[_BORDER:-_BORDER, _BORDER:-_BORDER] = True
            self._cache = (obs, belief, mask, berm & inner & mask)
        return self._cache

    def observe(self, *, site, built, leg=None):
        if not built:                         # no prior self-made change yet -> nothing dense to observe
            return None
        obs, belief, valid, site_mask = self._load()
        return OM.DenseObservation(observed=obs, belief=belief, valid_mask=valid, site_mask=site_mask,
                                   manifest=os.path.join(_FIX, "postdig_depth.json"))


def test_self_made_hazard_changes_the_in_loop_decision():  # [REQ:CP-09]
    """The whole point: WITHOUT dense perception the rover digs blind; WITH the real observed map in the
    loop, a PERCEIVED self-made hazard (the berm the belief does not carry) DEFERS the dig -- the decision
    genuinely changes. The observed map is the committed real Godot render (decoded here), not synthetic."""
    if not _have_fixture():
        pytest.skip("no committed P6 render fixture (run: .venv/bin/python -m dart.gen_observed_map_fixture)")
    m = _two_dig_mission()
    off = A.run_closed_loop(m, dem=None, dem_origin=(0.0, 0.0), algorithm="nearest", objective="time")
    on = A.run_closed_loop(m, dem=None, dem_origin=(0.0, 0.0), algorithm="nearest", objective="time",
                           dense_perception=_FixtureDensePerception())

    # the dense gate DEFERS / re-surveys; it does not drop or reorder work -- both runs complete the SAME
    # canonical plan, so the ONLY difference is the reactive defer the perception drove.
    assert off["completed"] is True and on["completed"] is True
    assert [L["leg"] for L in on["legs"]] == [L["leg"] for L in off["legs"]]

    # WITHOUT dense perception: the rover digs blind -- no self-made-hazard defer anywhere.
    assert off["dense_hazard_defers"] == 0
    assert not any(L["dense_deferred"] for L in off["legs"])
    assert off["dense_obs"] == []

    # WITH the real observed map in the loop: a perceived self-made hazard CHANGES the decision.
    assert on["dense_hazard_defers"] >= 1
    assert on["legs"][0]["dense_deferred"] is False          # first dig: nothing built yet -> not deferred
    assert any(L["dense_deferred"] for L in on["legs"])      # a later dig: the berm is perceived -> deferred

    # the defer is a real ACTION with a measurable cost, not just a counter: it spends survey dwell the
    # coverage-only run did not, and the delta is exactly the dense defers x the survey dwell.
    assert on["survey_time_s"] > off["survey_time_s"]
    assert on["survey_time_s"] - off["survey_time_s"] == pytest.approx(
        on["dense_hazard_defers"] * MC.OBSERVE_DWELL_S)

    # and the record that drove the decision carries the REAL observed-vs-belief divergence at the site
    # (a high dense-tier RMSE + the dense reconstruction tier), not a fabricated flag.
    hazard = [r for r in on["dense_obs"] if r["deferred"]]
    assert hazard and hazard[0]["map_rmse_m"] > 0.15         # perceived self-made change >> the hazard gate


def test_default_fast_path_renders_nothing():  # [REQ:CP-09]
    """Guard: with no dense_perception provider (the default), the loop reports zero dense activity -- the
    expensive render is never on the fast path."""
    m = _two_dig_mission()
    r = A.run_closed_loop(m, dem=None, dem_origin=(0.0, 0.0), algorithm="nearest", objective="time")
    assert r["dense_hazard_defers"] == 0 and r["dense_obs"] == []
    assert all(L["dense_deferred"] is False for L in r["legs"])


def test_live_on_host_render_defers_in_loop():  # [REQ:CP-09]
    """When Godot is present on-host, the loop drives a REAL nadir render of the mutated as-built INSIDE
    the loop (RenderedDensePerception) and the perceived self-made berm defers the second dig from a fresh
    render -- not a stale committed PNG. Skips on a bare CI runner (the fixture test covers the decision)."""
    if not OM.godot_available():
        pytest.skip("on-host Godot render unavailable (bare runner); the fixture test covers the decision")
    m = _two_dig_mission()
    on = A.run_closed_loop(m, dem=None, dem_origin=(0.0, 0.0), algorithm="nearest", objective="time",
                           dense_perception=OM.RenderedDensePerception(_SCENE))
    assert on["completed"] is True
    assert on["dense_hazard_defers"] >= 1                    # the in-loop render perceived the self-made berm
    assert any(L["dense_deferred"] for L in on["legs"])
    hazard = [r for r in on["dense_obs"] if r["deferred"]]
    assert hazard and hazard[0]["map_rmse_m"] > 0.15         # a REAL render divergence drove the defer
