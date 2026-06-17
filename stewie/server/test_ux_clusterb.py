"""Batch-6 cluster B UX/mobile regressions: static gate guards.

  * UX-01/OPT-02 -- the 401 observer must NOT auto-open the auth modal during boot; a casual visitor
    sees a calm signed-out state, the modal opens only on an explicit action.
  * UX-05 -- the planning sidebar (#panel) auto-collapses off the Plan view and restores on return; a
    manual toggle PINS the user's choice in localStorage and overrides the auto behaviour (desktop).
  * MOBILE-03 -- at <=860px the sticky panel header (#phead) reserves left padding so the absolute
    drawer button (#drawerbtn) does not cover the STEWIE wordmark when the drawer is open.
  * MOBILE-05/OPT-03 -- landing.html compresses the hero on a phone so the primary CTA sits above the
    390x844 fold.

The DYNAMIC behaviour (unauthenticated boot keeps the modal hidden; the sidebar collapses off-Plan and
restores; the landing CTA's measured rect sits within the fold) is verified in a REAL browser by
scripts/ux_a11y_smoke.py. This is the fast guard.
"""
from __future__ import annotations

import os
import re

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_INDEX = os.path.join(_ROOT, "stewie", "server", "index.html")
_COCKPIT = os.path.join(_ROOT, "stewie", "server", "web", "assets", "cockpit.js")
_LANDING = os.path.join(_ROOT, "stewie", "server", "web", "landing.html")


def _read(p: str) -> str:
    with open(p) as f:
        return f.read()


def test_ux01_flash_signin_gated_at_boot():
    js = _read(_COCKPIT)
    assert "let _bootComplete = false" in js, "no _bootComplete boot guard declared (UX-01)"
    assert "if (!_bootComplete) return" in js, "flashSignInNeeded is not gated on boot completion (UX-01)"
    assert "_bootComplete = true" in js, "_bootComplete is never set true after boot (UX-01)"


def test_ux05_sidebar_autocollapse_and_pin():
    js = _read(_COCKPIT)
    html = _read(_INDEX)
    assert "function applySidebar" in js, "no applySidebar() (UX-05)"
    assert "stewie_sidebar_pin" in js, "the manual sidebar toggle is not persisted to localStorage (UX-05)"
    assert 'classList.toggle("collapsed"' in js, "the sidebar collapse class is never toggled (UX-05)"
    assert "applySidebar(" in js.split("function setView")[1].split("\n}")[0], \
        "setView does not re-apply the sidebar state on a view change (UX-05)"
    assert "#panel.collapsed" in html, "no collapsed-sidebar CSS rule (UX-05)"


def test_mobile03_phead_reserves_drawer_space():
    html = _read(_INDEX)
    # there may be MORE THAN ONE <=860px block (the stepper co-locates its responsive rules with the
    # stepper CSS, MOBILE-05); the #phead drawer-padding rule need only live in SOME mobile block.
    blocks = re.findall(r"@media \(max-width: 860px\) \{(.*?)\n  \}", html, re.S)
    assert blocks, "could not find a <=860px media query"
    assert any(re.search(r"#phead\s*\{[^}]*padding-left", b) for b in blocks), \
        "#phead does not reserve left padding for the #drawerbtn at <=860px (MOBILE-03)"


def test_mobile05_landing_hero_compressed_for_fold():
    html = _read(_LANDING)
    assert "@media(max-width:560px){" in html, "no <=560px media query in landing.html"
    tail = html.split("@media(max-width:560px){", 1)[1].split("</style>")[0]
    assert ".hero{" in tail, "the phone media query does not compress the hero (MOBILE-05/OPT-03)"
    hero_rule = tail.split(".hero{", 1)[1].split("}")[0]
    assert "padding" in hero_rule, "the hero padding is not reduced for the phone fold (MOBILE-05/OPT-03)"
