"""[REQ:GW-00] the QWC2/OpenLayers map + RViz/Godot web-panel CSP contract (deploy/nginx.conf, the sole CSP surface —
the backend sets none). The production CSP allowlists the NASA Trek tile host for BOTH img-src and connect-src
so OpenLayers streams real Trek raster tiles, permits its blob web workers (worker-src blob:),
and allows same-origin WebSocket for a proxied RViz/Godot (Foxglove/rosbridge) web panel (connect-src 'self').
Prerequisite for GW-05 (map substrate) + RT-04 (web panel); pins the allowlist so the imagery + panels can't
silently regress."""
import os
import re

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _csp_directives() -> dict[str, list[str]]:
    with open(os.path.join(_ROOT, "deploy", "nginx.conf"), encoding="utf-8") as fh:
        conf = fh.read()
    m = re.search(r'Content-Security-Policy\s+"([^"]+)"', conf)
    assert m, "deploy/nginx.conf must send a Content-Security-Policy header"
    return {p.split()[0]: p.split()[1:] for p in m.group(1).split(";") if p.strip()}


def test_gw00_csp_allowlists_trek_for_imagery():  # [REQ:GW-00]
    csp = _csp_directives()
    for d in ("img-src", "connect-src"):
        assert "https://trek.nasa.gov" in csp.get(d, []), \
            f"CSP {d} must allowlist https://trek.nasa.gov so the QWC2/OpenLayers basemap streams real Trek tiles"


def test_gw00_csp_supports_blob_workers_and_web_panels():  # [REQ:GW-00]
    csp = _csp_directives()
    assert "blob:" in csp.get("worker-src", []), "OpenLayers/QWC2 needs blob web workers (worker-src blob:)"
    assert "'self'" in csp.get("connect-src", []), \
        "connect-src 'self' is required for a same-origin proxied RViz/Godot (Foxglove/rosbridge) web panel"
    # object/base/frame-ancestors stay locked down even as we open the tile + panel origins
    assert csp.get("object-src") == ["'none'"] and csp.get("frame-ancestors") == ["'none'"]
