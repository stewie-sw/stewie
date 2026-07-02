"""FS-11 security-hardening gate: no automation secrets in browser state.

The row's other clauses are pinned where they live (screened before this file was added, so the
gate EXTENDS the [REQ:FS-11] set instead of duplicating it):
 - fail-closed auth ......... test_account_store_failclosed.py (corrupt store denies fallback director)
 - config redaction ......... stewie/specs/test_config.py (describe()/  /config never returns VALUES)
 - CSP / no inline script ... test_deploy_hardening.py::test_web01_nginx_csp_keeps_script_self_and_allowlists_tiles
 - auth-route rate limits ... test_auth_limits.py (login per-IP/per-account 429; register per-IP 429)
 - role gating .............. test_profile_write_role.py, test_capability_gate.py
 - command-path interlocks .. test_command_gate.py (sandbox rejected, watchdog/stale-link 409)
 - SBOM ..................... scripts/test_gen_sbom.py (CycloneDX from the real locks, no fabrication)

This file closes the remaining browser-state clause end-to-end: with real STEWIE_* secret values set
in the server's environment, every HTML surface a browser receives (/ the cockpit shell, /program the
board, /landing the public page) must not contain any secret VALUE. The pages are static today, so
this pins the property against a future template/inline-config change quietly interpolating env.

Run: PYTHONPATH=. <venv>/bin/python -m pytest stewie/server/test_fs11_hardening_gate.py -q
"""
from __future__ import annotations

import os
import re

from fastapi.testclient import TestClient

from stewie.server.server import app

# env names that hold credentials; values shorter than 8 chars are skipped (trivial substrings would
# false-positive against ordinary page text)
_SECRET_ENV = re.compile(r"^STEWIE_.*(KEY|TOKEN|SECRET|PASSWORD)$")

_BROWSER_PAGES = ("/", "/program", "/landing")


def test_served_pages_never_contain_stewie_secret_values(monkeypatch):  # [REQ:FS-11]
    """Set known secret values, GET every HTML surface the browser loads, and prove none of the
    VALUES appear in any response body (the KEYS may -- an operator seeing 'API_KEY is set' is fine;
    the credential itself in browser-visible state is the FS-11 violation)."""
    api_key = "fs11-sentinel-api-key-3f9c1b7e"
    director_key = "fs11-sentinel-director-key-8a2d4c6f"
    monkeypatch.setenv("STEWIE_API_KEY", api_key)
    monkeypatch.setenv("STEWIE_DIRECTOR_KEY", director_key)
    # sweep EVERY secret-shaped STEWIE_* var actually present, not only the two sentinels, so a real
    # deployment credential inherited from the test environment is asserted absent too
    secrets = {name: val for name, val in os.environ.items()
               if _SECRET_ENV.match(name) and len(val) >= 8}
    assert api_key in secrets.values() and director_key in secrets.values(), \
        "sentinel secrets not picked up -- the sweep itself is broken"

    client = TestClient(app)
    for url in _BROWSER_PAGES:
        r = client.get(url)
        # non-vacuous: the page must actually serve as real HTML with a real body, otherwise the
        # absence assertions below would pass against a 404 stub
        assert r.status_code == 200, f"{url} did not serve ({r.status_code})"
        assert r.headers["content-type"].startswith("text/html"), f"{url} is not an HTML surface"
        assert len(r.text) > 500, f"{url} served an implausibly small page ({len(r.text)} bytes)"
        for name, val in secrets.items():
            assert val not in r.text, f"{url} leaked the VALUE of {name} into browser state"
