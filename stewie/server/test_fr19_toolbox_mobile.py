"""[REQ:FR-19] The Plan ToolBox is a viewport-contained mobile sheet with a 44px keep-out radius control.

Static guard over index.html's mobile @media block (backed by a Playwright runtime measurement at
320/390/430/768 px in scripts/fr19_toolbox_probe.py): the expanded #edittoolbar must be contained within the
viewport -- it no longer anchors at right:50px + max-width:66vw, which clipped the #edittools tray ~2px past
the 320px viewport -- and #koradius (the keep-out radius number input, excluded from the MOBILE-01 touch
rule that only names checkbox/range) must reach the 44px touch floor.
"""
import os
import re

_INDEX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")


def _html() -> str:
    return open(_INDEX, encoding="utf-8").read()


def test_toolbox_is_viewport_contained_on_mobile():  # [REQ:FR-19]
    rules = re.findall(r"#edittoolbar\s*\{([^}]*)\}", _html())
    assert rules, "no #edittoolbar rule"
    # at least one #edittoolbar rule (the mobile one) caps the tray to the viewport (calc(...100vw...)),
    # so the expanded #edittools left edge can no longer cross 0.
    assert any("100vw" in r for r in rules), "no viewport-contained (100vw) #edittoolbar rule"
    # the old clipping anchor (max-width:66vw at right:50px) is gone from every rule.
    assert not any("66vw" in r for r in rules), "the old max-width:66vw that clipped the tray past 320px remains"


def test_keep_out_radius_meets_the_44px_touch_floor_on_mobile():  # [REQ:FR-19]
    html = _html()
    assert (re.search(r"#koradius[^{]*\{[^}]*min-height:\s*44px", html)
            or re.search(r'input\[type="number"\][^{]*\{[^}]*min-height:\s*44px', html)), \
        "keep-out radius (#koradius / number input) has no 44px mobile touch floor"
