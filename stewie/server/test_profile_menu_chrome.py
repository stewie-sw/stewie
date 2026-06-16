"""FS-20: the cockpit chrome IA. System / Settings / Admin no longer sit on the work-area tab bar
alongside the five mission views -- they live in a role-gated profile menu anchored to the signed-in
identity chip (Settings everyone, System operator+, Admin director). The director-only Admin pane is
where the audit ledger (/events) is surfaced -- "log files visible for admins".

The DYNAMIC behaviour (menu opens on click, items switch panes, role-gated visibility) is verified in
a real browser by scripts/cockpit_render.py. This is the fast static guard that keeps the IA from
silently regressing in CI.
"""
from __future__ import annotations

import os
import re

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_INDEX = os.path.join(_ROOT, "stewie", "server", "index.html")
_COCKPIT = os.path.join(_ROOT, "stewie", "server", "web", "assets", "cockpit.js")


def _read(p: str) -> str:
    with open(p) as f:
        return f.read()


def test_moved_views_are_off_the_work_area_tab_bar():
    html = _read(_INDEX)
    vtab_views = re.findall(r'class="vtab[^"]*"[^>]*data-view="([a-z]+)"', html)
    assert vtab_views == ["plan", "nav", "perception", "metrics", "report"], \
        f"the work-area tab bar is {vtab_views}; System/Settings/Admin must not be vtabs"


def test_moved_views_live_in_the_profile_menu():
    html = _read(_INDEX)
    assert 'id="profbtn"' in html, "no #profbtn account button to anchor the menu"
    assert 'id="profmenu"' in html, "no #profmenu dropdown"
    menu_views = set(re.findall(r'class="profitem"[^>]*data-view="([a-z]+)"', html))
    assert {"settings", "system", "admin"} <= menu_views, \
        f"profile menu carries {menu_views}; expected settings/system/admin"
    # the role-gated items must be addressable by gateChrome
    assert 'id="prof-system"' in html and 'id="prof-admin"' in html
    # sign-out stays reachable from the menu
    assert 'id="whoami-signout"' in html, "sign-out dropped from the profile menu"


def test_role_gating_wired_in_cockpit_js():
    js = _read(_COCKPIT)
    assert "function gateChrome" in js, "no gateChrome() to role-gate the menu items"
    body = js.split("function gateChrome")[1].split("\n}")[0]
    assert '_rrank("operator")' in body, "System is not gated to operator+"
    assert 'role === "director"' in body, "Admin is not gated to director"
    # gateChrome must fire in BOTH auth branches (signed-in + signed-out), replacing the old vtab gate
    auth = js.split("async function refreshAuthState")[1].split("\nasync function")[0]
    assert auth.count("gateChrome(") >= 2, "refreshAuthState does not gate the menu in both branches"
    assert 'vtab-admin' not in js, "stale vtab-admin gating left behind after the IA move"
    # the menu is actually wired (toggle + item routing through setView)
    assert "wireProfile" in js and 'querySelectorAll(".profitem[data-view]")' in js, \
        "profile menu items are not wired to setView"


def test_admin_pane_surfaces_the_audit_log_for_admins():
    html, js = _read(_INDEX), _read(_COCKPIT)
    assert 'id="adminaudit"' in html, "no #adminaudit block in the Admin pane"
    assert "/events" in html, "the Admin audit caption does not name its source (/events)"
    # renderAdmin must actually fetch the ledger into that block (not leave a dangling placeholder)
    ra = js.split("async function renderAdmin")[1].split("\nasync function")[0]
    assert "/events" in ra and "adminaudit" in ra, \
        "renderAdmin does not populate #adminaudit from /events"
