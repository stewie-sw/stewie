"""Desktop local-trust auth (STEWIE_DESKTOP): the bundled single-user desktop app opens straight to
the cockpit, WITHOUT weakening the public/docker deploy. The bypass is gated on the explicit
STEWIE_DESKTOP flag AND a loopback client; the public deploy never sets the flag, so it cannot
activate there. These tests pin that contract: granted only with flag+loopback, fail-closed otherwise.
"""
import pytest
from fastapi import HTTPException

from stewie.server import auth as AUTH
from stewie.server.deps import require_auth


def _req(host="127.0.0.1"):
    # minimal stand-in for a Starlette Request: require_auth only reads request.client.host on the
    # desktop/dev branches (it raises before touching cookies when no key + no bypass applies).
    return type("R", (), {"client": type("C", (), {"host": host})(),
                          "cookies": {}, "headers": {}, "method": "GET"})()


def test_desktop_flag_on_loopback_grants_local_director(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("STEWIE_DESKTOP", "1")
    monkeypatch.delenv("STEWIE_API_KEY", raising=False)
    ident = require_auth(_req(), x_api_key=None, authorization=None, tailscale_user_login=None)
    assert ident == "desktop-local"
    assert AUTH.role_of("desktop-local") == "director"      # full cockpit access for the single user


def test_no_desktop_flag_is_fail_closed(monkeypatch, tmp_path):
    # without the flag, a keyless server stays LOCKED (the pre-existing fail-closed default) -- the
    # desktop branch must NOT have opened a hole for the public deploy.
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("STEWIE_DESKTOP", raising=False)
    monkeypatch.delenv("STEWIE_API_KEY", raising=False)
    monkeypatch.delenv("STEWIE_DEV_OPEN", raising=False)
    with pytest.raises(HTTPException) as e:
        require_auth(_req(), x_api_key=None, authorization=None, tailscale_user_login=None)
    assert e.value.status_code == 503


def test_desktop_flag_requires_loopback(monkeypatch, tmp_path):
    # defense in depth: the flag alone is not enough -- a non-loopback client gets no bypass.
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("STEWIE_DESKTOP", "1")
    monkeypatch.delenv("STEWIE_API_KEY", raising=False)
    monkeypatch.delenv("STEWIE_DEV_OPEN", raising=False)
    with pytest.raises(HTTPException) as e:
        require_auth(_req(host="10.0.0.5"), x_api_key=None, authorization=None, tailscale_user_login=None)
    assert e.value.status_code == 503


def test_desktop_flag_does_not_override_a_configured_api_key_for_remote(monkeypatch, tmp_path):
    # if a key IS configured (a server deploy) AND somehow STEWIE_DESKTOP leaked, a NON-loopback
    # client still cannot use the bypass and must present a real credential.
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("STEWIE_DESKTOP", "1")
    monkeypatch.setenv("STEWIE_API_KEY", "real-key")
    with pytest.raises(HTTPException) as e:
        require_auth(_req(host="10.0.0.5"), x_api_key=None, authorization=None, tailscale_user_login=None)
    assert e.value.status_code == 401
