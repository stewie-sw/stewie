"""[REQ:FR-14] Navigation is labeled preview/rehearsal unless a live+authorized autonomy binary is attested.
The nav surface carries a #navmode badge that reads PREVIEW by default (the live autonomy binary is the
gated leg, so it never attests here) and flips to LIVE only when setNavMode() sees a live-autonomy
attestation. Static guard; runtime proof = scripts/fr14_nav_preview_probe.py."""
import os
import re

_HERE = os.path.dirname(os.path.abspath(__file__))
_INDEX = os.path.join(_HERE, "index.html")
_COCKPIT = os.path.join(_HERE, "web", "assets", "cockpit.js")


def test_nav_surface_carries_a_preview_mode_badge():  # [REQ:FR-14]
    html = open(_INDEX, encoding="utf-8").read()
    m = re.search(r'id="navmode"[^>]*>\s*([A-Z/]+)', html)
    assert m, "the nav surface has no #navmode label"
    assert "PREVIEW" in m.group(1), f"#navmode does not default to PREVIEW (got {m.group(1)!r})"


def test_nav_mode_flips_to_live_only_on_a_live_autonomy_attestation():  # [REQ:FR-14]
    js = open(_COCKPIT, encoding="utf-8").read()
    assert "setNavMode" in js, "no setNavMode() gate in cockpit.js"
    block = js[js.index("setNavMode"):js.index("setNavMode") + 900]
    # the gate keys on a live-autonomy attestation and produces both LIVE and PREVIEW labels.
    assert re.search(r"STEWIE_LIVE_AUTONOMY|live_autonomy|liveAutonomy", block), \
        "setNavMode does not gate on a live-autonomy attestation"
    assert "LIVE" in block and "PREVIEW" in block, "setNavMode does not label both LIVE and PREVIEW"
