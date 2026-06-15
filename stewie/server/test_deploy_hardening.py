"""Deploy-file regressions: O-04 (duplicate COPY) and S-13 (supply-chain pinning).

O-04: deploy/Dockerfile.backend copied `stewie` twice (a wasted layer). The COPY must appear once.

S-13: the docs build installed mkdocs-material UNPINNED, and the Docker base used a mutable tag with
no digest. Pin them: the mkdocs install carries a version (==), and the Dockerfile bases are pinned by
digest (@sha256:).

Run: PYTHONPATH=. <venv>/bin/python -m pytest stewie/server/test_deploy_hardening.py -q
"""
from __future__ import annotations

import os
import re

import yaml

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_IPV4 = re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b")


def _read(rel: str) -> str:
    with open(os.path.join(_ROOT, rel)) as f:
        return f.read()


def _compose() -> dict:
    return yaml.safe_load(_read("deploy/compose.yml"))


def test_dockerfile_backend_copies_stewie_once():
    """O-04: the `COPY stewie ./stewie` line must appear exactly once (the duplicate is removed)."""
    text = _read("deploy/Dockerfile.backend")
    copies = [ln for ln in text.splitlines()
              if re.match(r"\s*COPY\s+stewie\s+\./stewie\s*$", ln)]
    assert len(copies) == 1, f"expected exactly one `COPY stewie ./stewie`, found {len(copies)} (O-04)"


def test_mkdocs_material_install_is_pinned():
    """S-13: the docs workflow must pin mkdocs-material to a version (no bare `pip install`)."""
    text = _read(".github/workflows/pages.yml")
    install_lines = [ln for ln in text.splitlines() if "mkdocs-material" in ln and "pip install" in ln]
    assert install_lines, "no mkdocs-material install line found"
    for ln in install_lines:
        assert "==" in ln, f"mkdocs-material is installed UNPINNED (S-13): {ln.strip()!r}"


def test_dockerfiles_pin_base_image_by_digest():
    """S-13: production images must pin the base by digest (@sha256:), not a mutable tag, so a rebuild
    from the same revision uses the same bytes."""
    for df in ("deploy/Dockerfile.backend", "deploy/Dockerfile.frontend"):
        text = _read(df)
        from_lines = [ln for ln in text.splitlines() if ln.strip().upper().startswith("FROM ")]
        assert from_lines, f"{df} has no FROM line"
        for ln in from_lines:
            # a multi-stage `FROM base AS x` that references a prior local stage is fine; only external
            # image references (with a registry tag) must be digest-pinned.
            ref = ln.split()[1]
            if ":" in ref and "/" not in ref.split(":")[0] and "@sha256:" not in ref:
                # e.g. python:3.12-slim -> external image with a mutable tag, no digest
                assert "@sha256:" in ln, f"{df} base is not digest-pinned (S-13): {ln.strip()!r}"


def test_arch05_frontend_bind_has_no_hardcoded_host_ip():
    """ARCH-05: the base compose must not bake a host-specific IP into the frontend publish list (the
    old `100.75.128.41` only worked on one machine). Every published host_ip must be either loopback
    or an env-var reference; loopback must still be published (the cloudflared tunnel origin)."""
    fe = _compose()["services"]["frontend"]
    ports = fe["ports"]
    assert ports, "frontend publishes no ports"
    host_ips = [str(p).split(":")[0] for p in ports]      # short syntax "HOST_IP:HOST_PORT:CTR_PORT"
    assert "127.0.0.1" in host_ips, "loopback bind dropped -- the tunnel origin must stay published"
    for hip in host_ips:
        if hip.startswith("${"):
            continue                                       # env-driven override is allowed
        assert hip == "127.0.0.1", f"hardcoded non-loopback host IP in frontend ports (ARCH-05): {hip!r}"
    # and no stray hardcoded IPv4 literal anywhere in the (short-form) port strings
    for p in ports:
        for lit in _IPV4.findall(str(p)):
            assert lit == "127.0.0.1", f"hardcoded IPv4 {lit!r} in frontend ports (ARCH-05)"


def test_arch05_lan_override_is_env_driven():
    """ARCH-05: the optional LAN/tailnet override publishes the extra interface from an env var
    (STEWIE_FRONTEND_BIND), not a literal IP, so the repo stays host-portable."""
    override = _read("deploy/compose.lan.yml")
    doc = yaml.safe_load(override)
    ports = doc["services"]["frontend"]["ports"]
    joined = " ".join(str(p) for p in ports)
    assert "STEWIE_FRONTEND_BIND" in joined, "LAN override must bind from $STEWIE_FRONTEND_BIND"
    assert not [lit for lit in _IPV4.findall(joined) if lit != "127.0.0.1"], \
        "LAN override hardcodes a host IP -- it must be env-driven (ARCH-05)"


def test_sec07_frontend_is_read_only_with_tmpfs():
    """SEC-07: the frontend nginx container runs on an immutable rootfs (read_only) like the backend,
    with tmpfs backing exactly the paths stock nginx must write (pid /var/run, temp /var/cache/nginx,
    /tmp). Everything else -- config + static html -- stays read-only."""
    fe = _compose()["services"]["frontend"]
    assert fe.get("read_only") is True, "frontend rootfs is not read-only (SEC-07)"
    tmpfs = fe.get("tmpfs") or []
    for needed in ("/var/cache/nginx", "/var/run", "/tmp"):
        assert needed in tmpfs, f"SEC-07: nginx writable path {needed!r} not backed by tmpfs (would EROFS)"
