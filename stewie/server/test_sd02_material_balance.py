"""[REQ:SD-02] cut/fill material-balance (extends SD-01).

For cut+fill orders, planTools.materialBalance returns bank cut volume, loose spoil (RHO_DEEP->RHO_SPOIL
bulking), compacted fill demand, and the net borrow/spoil in kg with mass conserved (cut-only => net spoil,
fill-only => net borrow). The runtime behavior is proven by the node test
gis/qwc2/js/mission/planTools.test.js ([REQ:SD-02]: the swell factor, the surplus/deficit direction, and
the cut-only/fill-only net cases). req_trace.py counts only Python markers, so this static gate is the python
[REQ:SD-02] citation: it asserts the source computes the conserved-mass balance with the RHO_DEEP/RHO_SPOIL
bulking. HONEST SCOPE: the densities are MOON-hardcoded (constants.py RHO_DEEP=1920 / RHO_SPOIL=1300);
body-aware densities are deferred (task #62), so this row is verified for lunar planning only.
"""
from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).parents[2]
_PLANTOOLS = _ROOT / "gis" / "qwc2" / "js" / "mission" / "planTools.js"


def _read() -> str:
    assert _PLANTOOLS.exists(), f"SD-02 source missing: {_PLANTOOLS}"
    return _PLANTOOLS.read_text(encoding="utf-8")


def test_material_balance_conserves_mass_with_rho_deep_to_rho_spoil_bulking():  # [REQ:SD-02]
    src = _read()
    assert "function materialBalance" in src, "the material-balance function is gone"
    body = src.split("function materialBalance", 1)[1].split("\n    }", 1)[0]
    # bank cut + loose fill densities are the MOON constants (RHO_DEEP bank -> RHO_SPOIL loose).
    assert "rhoBank" in body and "1920" in body, "bank density (RHO_DEEP=1920) missing"
    assert "rhoLoose" in body and "1300" in body, "loose density (RHO_SPOIL=1300) missing"
    # loose spoil = bank cut bulked by rhoBank/rhoLoose (the ~+48% swell) -> drives drum loads + haul cycles.
    assert "cutBank * (rhoBank / rhoLoose)" in body, "loose-spoil bulking is not RHO_DEEP/RHO_SPOIL"
    # the balance is the CONSERVED MASS (cut@bank vs fill@loose), not a naive bank-volume difference.
    assert "cutBank * rhoBank" in body and "fillBank * rhoLoose" in body, "masses not computed at their densities"
    assert "cutMassKg - fillMassKg" in body, "balance is not the conserved mass difference"


def test_material_balance_reports_the_net_direction_and_the_returned_shape():  # [REQ:SD-02]
    src = _read()
    body = src.split("function materialBalance", 1)[1].split("\n    }", 1)[0]
    # net direction: surplus (>=0) = net spoil, deficit (<0) = net borrow -- the cut-only/fill-only cases.
    assert 'balanceKg >= 0 ? "surplus" : "deficit"' in body, "the net spoil/borrow direction is not surfaced"
    # the returned triple the acceptance names + the mass fields, exported for the mission panel.
    for field in ("cut_m3", "fill_m3", "loose_spoil_m3", "cut_mass_kg", "fill_mass_kg", "balance_kg", "status"):
        assert field in body, f"materialBalance does not return {field}"
    assert "materialBalance: materialBalance" in src, "materialBalance is not exported"


def test_densities_are_moon_hardcoded_body_aware_is_deferred():  # [REQ:SD-02]
    """The honest scope: SD-02 is verified for the Moon. The densities default to the lunar constants; a
    non-moon body would need body-aware densities (task #62), which are NOT yet wired -- so this asserts the
    moon defaults exist (not that body-aware exists), keeping the glyph honest about its scope."""
    src = _read()
    body = src.split("function materialBalance", 1)[1].split("\n    }", 1)[0]
    assert "opts.rhoBank || 1920" in body and "opts.rhoLoose || 1300" in body, \
        "the moon-density defaults (RHO_DEEP/RHO_SPOIL) are not the hardcoded fallback"
