"""[REQ:FR-17] More/account menus render as viewport-clamped mobile sheets. On desktop #moremenu/#profmenu
are position:absolute; right:0 inside far-right #viewtabs children, so on phones they opened OFFSCREEN (right
edges ~624/~881px in the review). At phone widths a mobile @media rule overrides them to position:fixed
(needs !important -- the base styles are inline) and clamps them to the viewport (left+right insets), so an
open menu can never produce an offscreen rect. Static guard, backed by scripts/fr17_menu_probe.py."""
import os
import re

_INDEX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")


def _fixed_rules() -> list[str]:
    html = open(_INDEX, encoding="utf-8").read()
    # selector text of every rule that sets position:fixed (the mobile menu-sheet override lives here).
    return re.findall(r"([^{}]+)\{[^{}]*position:\s*fixed\s*!important[^{}]*\}", html)


def test_mobile_menus_render_as_viewport_fixed_sheets():  # [REQ:FR-17]
    sel_text = " ".join(_fixed_rules())
    for sel in ("#moremenu", "#profmenu"):
        assert sel in sel_text, f"{sel} is not overridden to a fixed mobile sheet (position:fixed !important)"


def test_mobile_menu_sheet_is_viewport_clamped():  # [REQ:FR-17]
    html = open(_INDEX, encoding="utf-8").read()
    # the fixed menu rule clamps to the viewport with left + right insets so it cannot cross a screen edge.
    m = re.search(r"#moremenu[^{}]*#profmenu[^{}]*\{([^{}]*)\}|#profmenu[^{}]*#moremenu[^{}]*\{([^{}]*)\}", html)
    rule = (m.group(1) or m.group(2)) if m else ""
    assert re.search(r"left:\s*\d", rule) and re.search(r"right:\s*\d", rule), \
        "the mobile menu sheet is not clamped with left + right viewport insets"
