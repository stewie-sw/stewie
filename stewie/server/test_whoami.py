"""A signed-in identity indicator (the 'who's logged in' corner chip) + sign-out in the cockpit.

Before this, the only signed-in signals were buried text in Settings -> Account + the Admin tab
appearing. This adds a header chip (avatar initial + identity + role badge + sign-out), updated by
refreshAuthState, so a signed-in operator can see WHO they are from anywhere and sign out.

The DYNAMIC behaviour (chip hidden when signed out, populated by renderWhoami, sign-out clears it) is
verified in a real browser by scripts/ux_a11y_smoke.py. This is the fast static guard.
"""
from __future__ import annotations

import os

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_INDEX = os.path.join(_ROOT, "stewie", "server", "index.html")
_COCKPIT = os.path.join(_ROOT, "stewie", "server", "web", "assets", "cockpit.js")


def _read(p: str) -> str:
    with open(p) as f:
        return f.read()


def test_whoami_chip_markup_present():
    html = _read(_INDEX)
    assert 'id="whoami"' in html, "no #whoami identity chip in the header"
    assert 'id="whoami-av"' in html, "no #whoami-av avatar element"
    assert 'id="whoami-signout"' in html, "no #whoami-signout button"


def test_cockpit_renders_and_clears_the_chip():
    js = _read(_COCKPIT)
    assert "function renderWhoami" in js, "no renderWhoami() to populate/hide the chip"
    # refreshAuthState must drive it in BOTH the signed-in and signed-out branches
    body = js.split("function refreshAuthState")[1].split("\nasync function")[0]
    assert body.count("renderWhoami(") >= 2, "refreshAuthState does not update the chip in both branches"
    # a real sign-out path (route + wiring)
    assert "function doLogout" in js and "/auth/logout" in js, "no sign-out path wired"
    assert "whoami-signout" in js, "the sign-out button is not wired to doLogout"
