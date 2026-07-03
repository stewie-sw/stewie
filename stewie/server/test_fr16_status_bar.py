"""[REQ:FR-16] fixed mobile status/action bar + [REQ:FR-21] mobile IA control-plane split.

On phones placeStatusCluster() (cockpit.js) MOVES the operational status/account chrome
(#healthchip / #alertbtn / #wsslot / #whoami) into a #statuscluster that a mobile @media rule pins
position:fixed at the top -- so the status/action plane stays in the first viewport (it was scrolling
offscreen at the right of #viewtabs), separated from the independently-scrollable #viewtabs work rail
(the FR-21 control-plane split). Static guard; the runtime proof is scripts/fr16_status_probe.py (all four
in the first viewport, no overlap, no body overflow at 320/360/390/430; desktop restores to #viewtabs)."""
import os
import re

_HERE = os.path.dirname(os.path.abspath(__file__))
_INDEX = os.path.join(_HERE, "index.html")
_COCKPIT = os.path.join(_HERE, "web", "assets", "cockpit.js")


def test_cockpit_moves_the_status_chrome_into_a_cluster_on_mobile():  # [REQ:FR-16]
    js = open(_COCKPIT, encoding="utf-8").read()
    assert "placeStatusCluster" in js, "no placeStatusCluster mover in cockpit.js"
    assert '"statuscluster"' in js, "placeStatusCluster does not build a #statuscluster"
    # it gathers the four status controls by id (they keep their ids so the state renderers ride along).
    block = js[js.index("placeStatusCluster"):js.index("placeStatusCluster") + 1200]
    for eid in ("healthchip", "alertbtn", "wsslot", "whoami"):
        assert eid in block, f"placeStatusCluster does not gather {eid}"


def _fixed_selectors(html: str) -> list[str]:
    return re.findall(r"([^{}]+)\{[^{}]*position:\s*fixed[^{}]*\}", html)


def test_status_bar_is_position_fixed_on_mobile():  # [REQ:FR-16]
    html = open(_INDEX, encoding="utf-8").read()
    assert any("#statuscluster" in s for s in _fixed_selectors(html)), \
        "#statuscluster is not pinned position:fixed on mobile"


def test_mobile_ia_splits_the_fixed_status_plane_from_the_scrollable_work_rail():  # [REQ:FR-21]
    html = open(_INDEX, encoding="utf-8").read()
    # the status/action plane (#statuscluster) is FIXED (non-scrolling)...
    assert any("#statuscluster" in s for s in _fixed_selectors(html)), "#statuscluster status plane not fixed"
    # ...while the #viewtabs work rail scrolls independently -> the two planes are separated.
    assert re.search(r"#viewtabs\s*\{[^{}]*overflow-x:\s*auto", html), \
        "#viewtabs work rail is not independently scrollable (no control-plane split)"
