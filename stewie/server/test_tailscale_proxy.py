"""S-03 regression: the trusted Tailscale identity header must not be spoofable at the shipped edge.

The audit found the backend trusts `Tailscale-User-Login` when STEWIE_TRUST_TAILSCALE=1, but the
shipped nginx forwarded the client's own copy of that header unchanged -- so a direct client behind
that nginx could assert any allowlisted (even director) identity.

This pins two halves:
 - the shipped nginx config CLEARS the inbound Tailscale-User-Login on the proxied path (so a client
   header never reaches the backend through nginx), and
 - the backend only honors the header from a VERIFIED proxy peer: with STEWIE_TRUST_TAILSCALE=1 but a
   non-trusted peer, the header is ignored; from the configured trusted proxy address it is honored.

Run: PYTHONPATH=. <venv>/bin/python -m pytest stewie/server/test_tailscale_proxy.py -q
"""
from __future__ import annotations

import importlib
import os

import pytest


def test_nginx_clears_the_inbound_tailscale_header():
    """The shipped nginx must clear (reset) Tailscale-User-Login on the API proxy location so a
    client-supplied value cannot reach the backend through the edge."""
    here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    conf = os.path.join(here, "deploy", "nginx.conf")
    text = open(conf).read().lower()
    # the directive must appear and reset the header to empty (proxy_set_header Tailscale-User-Login "")
    assert "proxy_set_header tailscale-user-login" in text, (
        "nginx does not clear/override the Tailscale-User-Login header (S-03)")
    # and it must set it to empty, not forward a client value
    import re
    m = re.search(r'proxy_set_header\s+tailscale-user-login\s+(.+?);', text)
    assert m, "could not parse the Tailscale-User-Login proxy_set_header directive"
    val = m.group(1).strip().strip('"').strip("'")
    assert val == "", f"nginx forwards a non-empty Tailscale-User-Login ({val!r}); it must reset to empty (S-03)"


@pytest.fixture()
def auth(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("STEWIE_TRUST_TAILSCALE", "1")
    from stewie.server import auth as AUTH
    importlib.reload(AUTH)
    return AUTH


def test_tailscale_header_ignored_from_untrusted_peer(auth, monkeypatch):
    """With trust enabled but a TRUSTED-PROXY address configured, a header arriving from a different
    (untrusted) peer must be ignored -- the backend cannot accept a spoofed identity from a direct
    client."""
    monkeypatch.setenv("STEWIE_TRUSTED_PROXIES", "10.9.0.1")
    headers = {"tailscale-user-login": "mccardle.john@gmail.com"}
    assert auth.tailscale_identity(headers, peer_ip="203.0.113.7") is None, (
        "the Tailscale header was honored from an untrusted peer (S-03)")


def test_tailscale_header_honored_only_from_trusted_proxy(auth, monkeypatch):
    monkeypatch.setenv("STEWIE_TRUSTED_PROXIES", "10.9.0.1")
    headers = {"tailscale-user-login": "mccardle.john@gmail.com"}
    assert auth.tailscale_identity(headers, peer_ip="10.9.0.1") == "mccardle.john@gmail.com", (
        "the trusted proxy could not inject the backend-visible identity (S-03)")


def test_no_trusted_proxy_configured_fails_closed(auth, monkeypatch):
    """SEC-03: with trust enabled but NO proxy allowlist declared, the header must be IGNORED (fail
    closed). The previous behavior honored it from any peer -- a direct client could then spoof an
    allowlisted identity. An operator must now name the trusted proxy peers explicitly."""
    monkeypatch.delenv("STEWIE_TRUSTED_PROXIES", raising=False)
    headers = {"tailscale-user-login": "mccardle.john@gmail.com"}
    assert auth.tailscale_identity(headers, peer_ip="127.0.0.1") is None
    assert auth.tailscale_identity(headers) is None


def test_cidr_proxy_allowlist_is_honored(auth, monkeypatch):
    """SEC-03: a STEWIE_TRUSTED_PROXIES entry may be a CIDR; a peer inside the network is trusted, one
    outside it is not."""
    monkeypatch.setenv("STEWIE_TRUSTED_PROXIES", "10.9.0.0/24")
    headers = {"tailscale-user-login": "mccardle.john@gmail.com"}
    assert auth.tailscale_identity(headers, peer_ip="10.9.0.42") == "mccardle.john@gmail.com"
    assert auth.tailscale_identity(headers, peer_ip="10.9.1.42") is None


def test_startup_rejects_trust_without_a_proxy_allowlist(auth, monkeypatch):
    """SEC-03: the deployment must REFUSE to boot if it trusts the Tailscale header without naming the
    proxy peers (an unbounded trust set is fail-open). With an allowlist (or with trust off), boot is OK."""
    monkeypatch.delenv("STEWIE_TRUSTED_PROXIES", raising=False)
    with pytest.raises(RuntimeError):
        auth.validate_proxy_trust_config()
    monkeypatch.setenv("STEWIE_TRUSTED_PROXIES", "10.9.0.1")
    auth.validate_proxy_trust_config()                    # allowlist present -> OK
    monkeypatch.setenv("STEWIE_TRUST_TAILSCALE", "0")
    monkeypatch.delenv("STEWIE_TRUSTED_PROXIES", raising=False)
    auth.validate_proxy_trust_config()                    # trust off -> OK
