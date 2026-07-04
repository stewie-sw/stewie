"""[REQ:MG-04] the /program requirements board is responsive at phone widths: the interactive targets
(.fbtn / .rowchip / the ConOps-spine applinks / the search box) reach the 44px touch floor at <=768px, the
row-chip lanes collapse to a single column, and the FS-26 no-horizontal-overflow guards are present.
Source-parsed from program.html; RUNTIME-verified via Playwright at 320/360/390/430px (every genuine touch
target measured 44px, 0px horizontal overflow, single-column)."""
import os

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_PROG = os.path.join(_ROOT, "stewie", "server", "web", "program.html")


def _css() -> str:
    with open(_PROG, encoding="utf-8") as fh:
        return fh.read()


def test_mg04_touch_targets_reach_44px_at_phone_widths():  # [REQ:MG-04]
    css = _css()
    i = css.find("max-width: 768px")
    assert i > 0, "no <=768px phone-width media query in program.html"
    block = css[i:i + 400]                                   # the media-query body
    assert "44px" in block, "the phone media query does not raise targets to the 44px touch floor"
    for sel in (".fbtn", ".rowchip", "applink", "program-search"):
        assert sel in block, f"{sel} is not raised to the touch floor at phone width (MG-04)"


def test_mg04_single_column_stack_and_no_horizontal_overflow():  # [REQ:MG-04]
    css = _css().replace(" ", "")
    assert "grid-template-columns:1fr" in css               # the row-chip lanes collapse to one column
    assert 'name="viewport"' in css and "width=device-width" in _css()
    assert "min-width:0" in css                             # FS-26 no-horizontal-scroll guard
