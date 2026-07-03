"""[REQ:FR-18] /program mobile touch ergonomics: at phone widths the filter buttons (.fbtn), the search
box (#program-search), and the row chips (.rowchip) meet the 44px touch floor (they measured ~24/26/22px
in the mobile review, 263 controls under floor). Static guard over program.html's mobile @media block,
backed by a live Playwright measurement in scripts/fr18_program_touch_probe.py."""
import os
import re

_PROG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web", "program.html")


def _html() -> str:
    return open(_PROG, encoding="utf-8").read()


def test_program_has_a_mobile_media_block():  # [REQ:FR-18]
    assert re.search(r"@media \([^)]*max-width", _html()), "/program has no max-width mobile @media block"


def test_program_controls_meet_the_44px_touch_floor_on_mobile():  # [REQ:FR-18]
    html = _html()
    # collect the selector text of every rule that sets min-height:44px; each control must be raised.
    sel_text = " ".join(re.findall(r"([^{};]+)\{[^{}]*min-height:\s*44px[^{}]*\}", html))
    for sel in (".fbtn", ".rowchip", "#program-search"):
        assert sel in sel_text, f"{sel} is not raised to the 44px mobile touch floor"


def test_mobile_search_goes_full_width():  # [REQ:FR-18]
    html = _html()
    # the search box becomes full-width under phone widths (recommendation: flex-basis/width 100%).
    assert re.search(r"#program-search[^{}]*\{[^}]*width:\s*100%", html), \
        "#program-search does not go full-width on mobile"
