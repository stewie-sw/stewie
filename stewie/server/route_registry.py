"""[REQ:AC-01] route coverage registry.

Every FastAPI route is either GENERATED into the typed TS API client (router-owned) or an explicit
static/internal EXEMPTION. So a new backend route cannot silently escape the typed client surface: it is
either covered by the generated client or consciously exempted here, and CI reds otherwise. The richer
per-route metadata the row also calls for -- pane ownership, auth/role, response kind, provenance
requirement, fixtures, authority-mutation flag (AC-02) -- layers onto the router-owned entries and is
deferred with the frontend-shell decision (pane ownership presupposes the pane taxonomy, ADR-0007).
"""
from __future__ import annotations

#: static file / doc / infra routes that are NOT part of the typed application API surface.
EXEMPT_EXACT = frozenset({"/", "/app", "/healthz", "/metrics", "/docs", "/openapi.json", "/redoc",
                          "/favicon.ico"})
#: served static/report/figure trees + the React SPA fallback (file/HTML responses), exempt by prefix.
EXEMPT_PREFIX = ("/assets", "/reports", "/figures", "/figure", "/app/")


def is_exempt(path: str) -> bool:
    """True for a static/infra route that is not part of the typed application API surface."""
    return path in EXEMPT_EXACT or any(path.startswith(p) for p in EXEMPT_PREFIX)


def router_owned_paths(spec: dict) -> list[str]:
    """The application API paths that MUST appear in the generated client (everything not exempt)."""
    return sorted(p for p in spec.get("paths", {}) if not is_exempt(p))


def coverage_gap(spec: dict, client_paths: set[str]) -> list[str]:
    """Router-owned routes absent from the generated client -> AC-01 coverage failure (should be empty)."""
    return sorted(p for p in router_owned_paths(spec) if p not in client_paths)
