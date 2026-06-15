"""Batch-6 accessibility regressions (UX-03 contrast, UX-04 ARIA): static guards on the cockpit markup.

UX-03: the --dim palette text must reach WCAG AA (>=4.5:1) on its theme background, in BOTH themes
(the --dim text was 3.08:1 dark / 3.58:1 light before). UX-04: the view switcher is a WAI-ARIA tablist,
the auth modal is a role=dialog aria-modal, and the Cesium canvas carries an aria-label.

The DYNAMIC behaviour (aria-selected toggles, arrow-key nav, focus, computed touch-target px, 0 CSP
violations) is verified by the real-browser scripts/ux_a11y_smoke.py. This is the fast gate guard.
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


def _relative_luminance(hexs: str) -> float:
    h = hexs.lstrip("#")
    rgb = [int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]
    lin = [(c / 12.92) if c <= 0.03928 else (((c + 0.055) / 1.055) ** 2.4) for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def _contrast(fg: str, bg: str) -> float:
    a, b = _relative_luminance(fg) + 0.05, _relative_luminance(bg) + 0.05
    return max(a, b) / min(a, b)


def _var(block: str, name: str) -> str:
    m = re.search(rf"{re.escape(name)}\s*:\s*(#[0-9a-fA-F]{{6}})", block)
    assert m, f"{name} not found in the palette block"
    return m.group(1)


def test_ux03_dim_text_contrast_meets_wcag_aa_both_themes():
    html = _read(_INDEX)
    # dark theme = the :root block; light theme = the body.light block
    root = html.split(":root")[1].split("}")[0]
    light = html.split("body.light")[1].split("}")[0]
    dark_ratio = _contrast(_var(root, "--dim"), _var(root, "--bg"))
    light_ratio = _contrast(_var(light, "--dim"), _var(light, "--bg"))
    assert dark_ratio >= 4.5, f"--dim (dark) contrast {dark_ratio:.2f} < 4.5 (WCAG AA, UX-03)"
    assert light_ratio >= 4.5, f"--dim (light) contrast {light_ratio:.2f} < 4.5 (WCAG AA, UX-03)"


def test_ux04_static_aria_roles_present():
    html = _read(_INDEX)
    assert 'id="cesium"' in html and 'role="application"' in html and "aria-label=" in html, \
        "the Cesium canvas needs role=application + an aria-label (UX-04)"
    assert 'id="authmodal"' in html and 'role="dialog"' in html and 'aria-modal="true"' in html, \
        "the auth modal needs role=dialog aria-modal (UX-04)"


def test_ux04_cockpit_wires_tab_semantics_and_dialog_keys():
    js = _read(_COCKPIT)
    assert 'setAttribute("role", "tablist")' in js, "viewtabs not given role=tablist (UX-04)"
    assert 'setAttribute("role", "tab")' in js and 'aria-selected' in js, "vtabs not given tab semantics"
    assert 'setAttribute("role", "tabpanel")' in js, "panes not given role=tabpanel (UX-04)"
    assert 'e.key === "Escape"' in js and "closeAuth()" in js, "Escape does not close the auth dialog (UX-04)"
    assert 'ArrowRight' in js and 'ArrowLeft' in js, "no arrow-key tab navigation (UX-04)"
