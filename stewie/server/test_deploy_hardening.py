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


def test_backend_entrypoint_enters_the_tls_guard():
    """[REQ:BP-02] the production backend CMD must enter the GUARDED entrypoint so the public-bind TLS
    guard (server._require_tls_for_public_bind, called only from main()) actually runs -- NOT a raw
    `uvicorn stewie.server.server:app`, which imports the ASGI app directly and bypasses main()."""
    cmd = [ln for ln in _read("deploy/Dockerfile.backend").splitlines()
           if re.match(r"\s*CMD\b", ln)][-1]
    # It must enter main()'s guard via `python -m stewie.server.server` -- NOT a raw `uvicorn ...server:app`
    # (bypasses main()) and NOT the bare `stewie-serve` console script: `python -m` puts WORKDIR /app on
    # sys.path so the app imports from /app (which carries the web/*.html + samples/ DATA FILES), whereas
    # the console script imports the installed site-packages copy that has NO data files -> /program 404s
    # and the Haworth DEM disappears (regressed once; this pins the data-file-safe form).
    assert "-m" in cmd and "stewie.server.server" in cmd and "uvicorn" not in cmd, (
        f"backend CMD must be `python -m stewie.server.server` (guarded + imports /app data files), got: {cmd}")
    assert "server:app" not in cmd and "server.server:app" not in cmd, (
        "a raw `uvicorn ...server:app` bypasses the public-bind TLS guard (BP-02)")
    assert '"stewie-serve"' not in cmd, (
        "the bare stewie-serve console script imports site-packages (no data files) -> /program + DEM 404")


def test_the_tls_guard_fails_closed_on_a_plaintext_public_bind(monkeypatch):
    """[REQ:BP-02] proves the guard main() runs actually refuses a public bind with no TLS declared, so
    entering it (above) is meaningful: 0.0.0.0 without STEWIE_TLS_TERMINATED / DEV_OPEN -> SystemExit."""
    import pytest

    from stewie.server import server as SRV
    monkeypatch.delenv("STEWIE_TLS_TERMINATED", raising=False)
    monkeypatch.delenv("STEWIE_DEV_OPEN", raising=False)
    with pytest.raises(SystemExit):
        SRV._require_tls_for_public_bind("0.0.0.0")
    # declaring the terminator (as compose does) lets the same public bind through.
    monkeypatch.setenv("STEWIE_TLS_TERMINATED", "1")
    SRV._require_tls_for_public_bind("0.0.0.0")     # no raise
    SRV._require_tls_for_public_bind("127.0.0.1")   # loopback always allowed


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


# ---- WEB-01: Cesium self-hosted same-origin (was unpkg.com, blocked by CSP script-src 'self') --------

def test_web01_index_self_hosts_cesium():
    """WEB-01: the cockpit must load Cesium from the same origin (/cesium/...), never a CDN, set
    CESIUM_BASE_URL before the bundle so it finds its Workers/Assets, and guard `window.Cesium` before
    the first Cesium.* reference so a load failure degrades to the 2-D tools instead of throwing."""
    html = _read("stewie/server/index.html")
    assert "unpkg.com" not in html and "cesium.com/downloads" not in html, \
        "index.html still loads Cesium from a CDN (CSP script-src 'self' blocks it -> blank map)"
    assert 'src="/cesium/Cesium.js"' in html, "Cesium.js not loaded same-origin from /cesium/"
    assert "/cesium/Widgets/widgets.css" in html, "Cesium widgets.css not loaded same-origin"
    # CESIUM_BASE_URL is set before Cesium.js (head); after ARCH-02 it is an external same-origin script.
    head = html.split("/cesium/Cesium.js")[0]
    assert ('window.CESIUM_BASE_URL = "/cesium/"' in head) or ("cesium-config.js" in head), \
        "CESIUM_BASE_URL not set (inline or external) before Cesium.js"
    # ARCH-02: the window.Cesium guard now lives in the external cockpit script, not inline in index.html
    cockpit = _read("stewie/server/web/assets/cockpit.js")
    assert 'typeof window.Cesium === "undefined"' in cockpit, \
        "no window.Cesium guard before the Cesium.* calls (cockpit.js)"


def test_web01_nginx_csp_keeps_script_self_and_allowlists_tiles():  # [REQ:FS-11]
    """WEB-01 (revised, live-site fix) + the FS-11 CSP/no-inline-script deployment clause: script-src
    admits the same origin + blob workers + eval (Cesium
    1.119 calls plain runtime eval() -- 'wasm-unsafe-eval' alone is NOT enough and the strict CSP blanked
    the live globe), but never a CDN host and never inline scripts/handlers; worker-src allows Cesium's
    same-origin/blob workers; img-src and connect-src allowlist exactly the read-only NASA/Esri imagery
    tile CDNs (no wildcard). 'unsafe-eval' is the one concession Cesium forces; it is scoped to scripts we
    self-host same-origin (no CDN, no inline), so the XSS surface stays our own bundle."""
    conf = _read("deploy/nginx.conf")
    csp = [ln for ln in conf.splitlines() if "add_header Content-Security-Policy" in ln]
    assert csp, "no CSP header in nginx.conf"
    csp = csp[0]
    script_src = csp.split("script-src", 1)[1].split(";", 1)[0]
    # script-src self-hosts the bundle (no CDN DEP host). The ONE allowed remote host is Cloudflare's own
    # zone-injected Web-Analytics beacon (static.cloudflareinsights.com): the edge already serves the whole
    # site, so its beacon is not a new third-party trust -- and without it the CSP refuses the auto-injected
    # beacon with a loud red console error. Arbitrary CDN hosts (unpkg, etc.) stay forbidden.
    remote = [t for t in script_src.split() if t.startswith("http")]
    assert "'self'" in script_src and "unpkg" not in csp and remote in ([], ["https://static.cloudflareinsights.com"]), \
        "script-src may only name the Cloudflare Insights beacon as a remote host -- self-host every other script"
    assert "'wasm-unsafe-eval'" in script_src, "Cesium WebAssembly needs 'wasm-unsafe-eval' in script-src"
    assert "blob:" in script_src, "Cesium workers importScripts(blob:) -> script-src must allow blob:"
    # ARCH-02/SEC-04: the cockpit JS is external, so script-src must NOT allow inline scripts/handlers.
    assert "'unsafe-inline'" not in script_src.split(), \
        "script-src must NOT allow 'unsafe-inline' after ARCH-02 (the cockpit JS is external)"
    # Live-site fix: Cesium 1.119 does plain runtime eval() (not only WASM), so 'unsafe-eval' is required
    # -- without it the globe rendered blank with a CSP "Missing 'unsafe-eval'" console error.
    assert "'unsafe-eval'" in script_src.split(), \
        "Cesium 1.119 calls runtime eval() -> script-src must include 'unsafe-eval' (else the globe blanks)"
    assert "worker-src 'self' blob:" in csp, "Cesium Web Workers need worker-src 'self' blob:"
    for host in ("https://trek.nasa.gov", "https://server.arcgisonline.com", "https://gibs.earthdata.nasa.gov"):
        assert host in csp, f"imagery tile CDN {host} not allowlisted in the CSP (tiles would be blocked)"
    assert "img-src" in csp and "* " not in csp.split("img-src")[1].split(";")[0], "img-src must not wildcard"


def test_web01_nginx_serves_cesium_statically_before_the_proxy():
    """WEB-01: a `location /cesium/` must serve the bundle statically and PRECEDE the catch-all
    `location /` (which proxies to the backend), or /cesium/* would 404 at the API."""
    conf = _read("deploy/nginx.conf")
    assert "location /cesium/" in conf, "no static location for the self-hosted Cesium bundle"
    assert conf.index("location /cesium/") < conf.index("location / {"), \
        "location /cesium/ must come before the catch-all proxy location /"


def test_web01_frontend_image_vendors_cesium():
    """WEB-01: the frontend image vendors the PINNED Cesium build into the served html dir (it is too
    large to commit and the CSP forbids a CDN), and removes the build tool in the same layer."""
    df = _read("deploy/Dockerfile.frontend")
    assert "cesium-1.119.0.tgz" in df, "Dockerfile.frontend does not vendor the pinned Cesium 1.119 build"
    assert "/usr/share/nginx/html/cesium" in df, "Cesium not copied into the served html dir"
    assert "apk del curl" in df, "the build tool (curl) is not removed from the final image layer"


# ---- SEC-05: third-party deps installed from a HASHED lock (supply-chain integrity) ------------------

def test_sec05_dependency_locks_are_hash_pinned():
    """SEC-05: the server + dev dependency locks pin exact versions AND sha256 hashes, so a rebuild
    from the same revision installs identical bytes and a tampered/yanked release cannot slip in."""
    for lock in ("requirements-server.lock", "requirements-dev.lock"):
        text = _read(lock)
        assert "--hash=sha256:" in text, f"{lock} is not hash-pinned (SEC-05)"
        pins = [ln for ln in text.splitlines() if re.match(r"^[A-Za-z0-9].+==", ln)]
        assert len(pins) >= 5, f"{lock} has too few pinned requirements ({len(pins)})"
        # every pinned requirement line is immediately followed by at least one --hash
        for ln in text.splitlines():
            if re.match(r"^[A-Za-z0-9].+==", ln):
                assert ln.rstrip().endswith("\\"), f"{lock}: a pin without a trailing hash continuation: {ln!r}"


def test_sec05_docker_installs_from_the_lock_with_require_hashes():
    """SEC-05: the backend image installs deps from the hashed server lock (--require-hashes), then the
    stewie package --no-deps -- not an unpinned `pip install .[server]`."""
    df = _read("deploy/Dockerfile.backend")
    assert "--require-hashes -r requirements-server.lock" in df, "Dockerfile does not install from the lock"
    assert "--no-deps ." in df, "Dockerfile does not install the package --no-deps after the lock"
    assert '".[server]"' not in df, "Dockerfile still has the unpinned `.[server]` install (SEC-05)"


def test_sec05_ci_installs_from_the_lock():
    """SEC-05: every CI install installs from the hashed dev lock, not an unpinned editable extra."""
    ci = _read(".github/workflows/ci.yml")
    assert "--require-hashes -r requirements-dev.lock" in ci, "CI does not install from the hashed lock"
    assert "pip install -e .[dev]" not in ci, "CI still has an unpinned `pip install -e .[dev]` (SEC-05)"


def test_frontend_dockerfile_makes_served_assets_world_readable():
    """bodies.json is produced by write_json_atomic (mkstemp -> 0600); a locally-built frontend image can
    COPY in a root/owner-only file the non-root nginx worker cannot read -> 403 on GET /bodies.json ->
    empty fleet/soil dropdowns. The Dockerfile must chmod the served html tree world-readable so a 0600
    source can never strand the cockpit again."""
    df = _read("deploy/Dockerfile.frontend")
    assert re.search(r"chmod\s+-R\s+a\+rX\s+/usr/share/nginx/html", df), \
        "Dockerfile.frontend must `chmod -R a+rX /usr/share/nginx/html` (a 0600 bodies.json -> nginx 403)"


def test_generated_bodies_json_is_world_readable():
    """The bodies.json generator must leave the file group/other-readable (nginx serves it as a non-root
    user). write_json_atomic alone yields 0600; gen_bodies_json must chmod 0644 after the atomic write."""
    import importlib

    import stewie.server.gen_bodies_json as g
    importlib.reload(g)                                  # re-run the generator body -> rewrite + chmod
    path = os.path.join(_ROOT, "stewie/server/bodies.json")
    mode = os.stat(path).st_mode
    assert mode & 0o044 == 0o044, f"bodies.json must be group/other readable for nginx; mode={oct(mode & 0o777)}"


def test_katwijk_mount_is_readonly_and_env_overridable():
    """REG-01 (review gap): the Katwijk dataset wiring (069286f) added STEWIE_KATWIJK_DIR + a read-only host
    mount so /slam returns real ATE on the deployed host, but no deploy-config test pinned it -- the analogous
    frontend bind IS guarded (test_arch05_*). Without this, dropping the mount / baking a machine path / flipping
    :ro to rw would silently re-break /slam with all tests green. (The app-layer 503-when-absent is covered in
    test_server.py.)"""
    be = _compose()["services"]["backend"]
    assert "STEWIE_KATWIJK_DIR" in be.get("environment", {}), \
        "backend must set STEWIE_KATWIJK_DIR (/slam 503s on the deployed host without it)"
    kat = [str(v) for v in be.get("volumes", []) if ":/katwijk:ro" in str(v)]
    assert kat, "the Katwijk dataset must be mounted READ-ONLY at /katwijk"
    host = kat[0].split(":")[0]
    assert host.startswith("${"), f"the katwijk host path must be env-overridable (ARCH-05 no baked path), got {host!r}"
    assert not _IPV4.search(host), f"no hardcoded host IP in the katwijk mount, got {host!r}"
