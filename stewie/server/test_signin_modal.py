"""The operator sign-in modal, decluttered.

It carried the founding-director / CI 'automation key' field inline AND a bottom 'continue without
signing in' link, which crowded the everyday sign-in box. The automation key is redundant (Settings ->
'Advanced -- automation API key' has it for the one-time bootstrap), so it is removed from the modal;
dismissal becomes a single header close (X). The everyday box is just: tabs (Sign in / Request access)
+ email + password + Sign in.

The dynamic behaviour (X closes, Esc closes, open focuses the email field, no automation field) is in
scripts/ux_a11y_smoke.py. This is the fast static guard.
"""
from __future__ import annotations

import os

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_INDEX = os.path.join(_ROOT, "stewie", "server", "index.html")
_COCKPIT = os.path.join(_ROOT, "stewie", "server", "web", "assets", "cockpit.js")


def _read(p):
    with open(p) as f:
        return f.read()


def test_signin_modal_keeps_the_core_fields():
    html = _read(_INDEX)
    for el in ('id="auth-email"', 'id="auth-pass"', 'id="auth-do-login"',
               'id="auth-tab-login"', 'id="auth-tab-register"', 'id="auth-dismiss"'):
        assert el in html, f"sign-in modal lost {el}"


def test_automation_key_removed_from_the_modal():
    html = _read(_INDEX)
    # the automation key lives ONLY in Settings now (id=set-apikey), not the sign-in modal
    assert 'id="auth-apikey"' not in html, "automation-key field still clutters the sign-in modal"
    assert 'id="auth-save-key"' not in html, "automation-key 'use key' button still in the modal"
    assert 'id="set-apikey"' in html, "the automation key must still exist in Settings (bootstrap path)"


def test_open_focuses_a_form_field_not_the_close_button():
    js = _read(_COCKPIT)
    body = js.split("function openAuth")[1].split("function closeAuth")[0]
    # focus must target a form INPUT, not the header close button (a bare 'input, button' query would
    # land on the X)
    assert 'querySelector("input")' in body or "auth-email" in body, \
        "openAuth still focuses the first input-or-button (would grab the close X)"
