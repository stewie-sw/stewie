# Security Policy

STEWIE is a simulation and mission-planning platform. It does not process sensitive data or
credentials. The one network-facing component is the optional mission-planner web UI
(`stewie/server/server.py`), a FastAPI/uvicorn (ASGI) service intended for local or trusted-LAN use.
The repository's license is currently all-rights-reserved (the prior CC0 dedication was withdrawn
2026-06-10; see [`LICENSE`](LICENSE)).

## Supported versions

The `main` branch is the only supported line during pre-1.0 development. Fixes land on `main`; there is
no separate maintenance branch.

| Version | Supported |
|---------|-----------|
| `main` (latest) | yes |
| tagged pre-releases | best-effort |

## Reporting a vulnerability

Please report security issues **privately** rather than in a public issue:

1. Open a private vulnerability report via the repository's
   **Security → Report a vulnerability** tab (GitHub Security Advisories), or
2. Contact a maintainer directly.

Include the affected file/endpoint, a reproduction, and the impact. We aim to acknowledge within a few
days and to discuss a fix and disclosure timeline with you.

## Operational notes (mission-planner web UI)

- The server binds to whatever `--host`/`--port` you pass. `--host 0.0.0.0` exposes it on all
  interfaces — only do this on a trusted network. The default is loopback.
- It serves files from its own package directory and a `reports/` output directory; it does not accept
  arbitrary file paths from clients.
- `POST /plan` and `POST /sense` accept JSON build/sensor parameters and run the deterministic planner;
  they execute no client-supplied code.

Coordinated security review is welcome; redistribution and reuse are governed by [`LICENSE`](LICENSE).
