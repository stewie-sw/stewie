"""[AR-016] Minimal, secret-free child environment for test subprocesses.

A subprocess launched with ``env={**os.environ, ...}`` carries every ambient secret (API keys, tokens)
into the ``subprocess.run(...)`` keyword object. When the child fails, pytest renders those keyword
arguments verbatim -- turning any developer terminal, CI log, or review transcript into a
credential-exfiltration channel. (This is exactly how a 2026-07-16 review subprocess disclosed unrelated
trading and deployment credentials.)

This wrapper builds the child environment from a SMALL allowlist of non-secret runtime knobs; callers add
only test-safe values via ``extra``. No ambient credential ever enters the child, so a failing child's
rendered arguments are clean. Because the venv's site-packages resolve the editable workspace installs for
the venv interpreter (``sys.executable``), NO ``PYTHONPATH`` manipulation is needed to import
stewie/dart/lode/... in the child -- which also removes the fragile "PYTHONPATH replaces the workspace
packages" failure mode of the previous per-test constructions.
"""
from __future__ import annotations

import os

# The ONLY ambient keys copied into a child: non-secret runtime knobs a subprocess legitimately needs.
# Everything else -- API keys, tokens, and any ambient credential -- is deliberately excluded.
_ALLOW: tuple[str, ...] = (
    "PATH", "HOME", "USER", "LOGNAME", "SHELL", "TERM", "TZ",
    "LANG", "LANGUAGE", "LC_ALL", "LC_CTYPE", "LC_NUMERIC", "LC_TIME", "LC_MESSAGES",
    "TMPDIR", "TEMP", "TMP",                       # temp paths
    "SYSTEMROOT", "WINDIR",                        # windows runtime
)


def child_env(extra: dict[str, str] | None = None, *, allow: tuple[str, ...] = _ALLOW) -> dict[str, str]:
    """A minimal, secret-free environment for a test subprocess.

    Copies only the allowlisted keys from the ambient environment, forces ``PYTHONNOUSERSITE=1`` (clean
    imports: venv site-packages only, no user-site), and overlays ``extra`` (test-safe values ONLY -- never
    a secret). Safe to place in ``subprocess.run(env=...)`` even when the child fails and pytest renders the
    call arguments: no ambient credential is present to leak.
    """
    env = {k: os.environ[k] for k in allow if k in os.environ}
    env.setdefault("PYTHONNOUSERSITE", "1")
    if extra:
        env.update({str(k): str(v) for k, v in extra.items()})
    return env
