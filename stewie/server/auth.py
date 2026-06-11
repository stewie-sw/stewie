"""#52: operator identity -- whitelist + HMAC session tokens + the Tailscale path.

Two ways in, both ending at a WHITELISTED identity:
  1. email + the API key -> POST /auth/login -> an HMAC-SHA256 token (signed with the API key,
     12 h expiry) sent as `Authorization: Bearer <token>`; carries the operator email -- the
     actor for the event history (#39).
  2. Tailscale: when STEWIE_TRUST_TAILSCALE=1 (a deployment served behind `tailscale serve`,
     which injects Tailscale-User-Login), that identity is honored IF whitelisted.
The raw X-API-Key continues to work for automation (CI, scripts) -- identity "api-key".
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time

DEFAULT_ALLOWLIST = (
    "mccardle.john@gmail.com",
    "aaron.w.storey80@gmail.com",
    "storeyaw@clarkson.edu",
)
TOKEN_TTL_S = 12 * 3600


def allowlist() -> tuple:
    env = os.environ.get("STEWIE_ALLOWED_OPERATORS", "")
    if env.strip():
        return tuple(e.strip().lower() for e in env.split(",") if e.strip())
    return DEFAULT_ALLOWLIST


def is_allowed(email: str) -> bool:
    return email.strip().lower() in allowlist()


def _key() -> bytes:
    k = os.environ.get("STEWIE_API_KEY", "") or os.environ.get("DUSTGYM_API_KEY", "")
    return k.encode()


def issue_token(email: str, *, now: float | None = None) -> str:
    payload = json.dumps({"op": email.strip().lower(),
                          "exp": (now if now is not None else time.time()) + TOKEN_TTL_S},
                         separators=(",", ":")).encode()
    sig = hmac.new(_key(), payload, hashlib.sha256).digest()
    return (base64.urlsafe_b64encode(payload).decode().rstrip("=") + "." +
            base64.urlsafe_b64encode(sig).decode().rstrip("="))


def verify_token(token: str, *, now: float | None = None) -> str | None:
    """The operator email if valid + unexpired + whitelisted, else None."""
    try:
        p64, s64 = token.split(".", 1)
        pad = lambda s: s + "=" * (-len(s) % 4)
        payload = base64.urlsafe_b64decode(pad(p64))
        sig = base64.urlsafe_b64decode(pad(s64))
        if not hmac.compare_digest(sig, hmac.new(_key(), payload, hashlib.sha256).digest()):
            return None
        d = json.loads(payload)
        if (now if now is not None else time.time()) > float(d["exp"]):
            return None
        return d["op"] if is_allowed(d["op"]) else None
    except (ValueError, KeyError, TypeError):
        return None


def role_of(identity: str) -> str:
    """#68: 'director' (full state: truth views, training toggles, admin) or 'operator' (shaped
    telemetry only). Directors default to the WHOLE whitelist (today's three are all staff);
    STEWIE_DIRECTORS narrows it when trainees join the whitelist. 'api-key' = automation =
    director-equivalent. 'dev-open' (no key configured) = director."""
    if identity in ("api-key", "dev-open"):
        return "director"
    env = os.environ.get("STEWIE_DIRECTORS", "")
    directors = (tuple(e.strip().lower() for e in env.split(",") if e.strip())
                 if env.strip() else allowlist())
    return "director" if identity.strip().lower() in directors else "operator"


def tailscale_identity(headers) -> str | None:
    """The whitelisted Tailscale identity, ONLY when the deployment opts in."""
    if os.environ.get("STEWIE_TRUST_TAILSCALE", "") != "1":
        return None
    login = headers.get("tailscale-user-login", "") or headers.get("Tailscale-User-Login", "")
    return login.strip().lower() if login and is_allowed(login) else None
