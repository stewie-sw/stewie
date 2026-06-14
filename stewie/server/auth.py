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
import uuid

DEFAULT_ALLOWLIST = (
    "mccardle.john@gmail.com",
    "aaron.w.storey80@gmail.com",
    "storeyaw@clarkson.edu",
)
TOKEN_TTL_S = 12 * 3600
_TOKEN_ISS = "stewie-auth"                     # S-12: issuer claim
_DEFAULT_AUD = "stewie-cockpit"                 # S-12: default audience claim


def allowlist() -> tuple:
    env = os.environ.get("STEWIE_ALLOWED_OPERATORS", "")
    if env.strip():
        return tuple(e.strip().lower() for e in env.split(",") if e.strip())
    return DEFAULT_ALLOWLIST


def is_allowed(email: str) -> bool:
    """Whitelisted? (#117) The operator store is authoritative for emails it holds -- active is
    allowed, pending/revoked are denied. An email with no store record falls back to the
    env/default allowlist, so an empty store behaves exactly as the pre-#117 deployment."""
    from stewie.server import operators as OPS
    e = email.strip().lower()
    if OPS.exists(e):
        return OPS.is_active(e)
    return e in allowlist()


def automation_key() -> bytes:
    """The raw automation credential (STEWIE_API_KEY): the shared key CI/scripts present, and the
    constant the require_auth 'api-key' identity is compared against. NOT the token signing key."""
    return os.environ.get("STEWIE_API_KEY", "").encode()


def _signing_secret() -> bytes:
    """S-12: the SESSION-signing secret, separated from the automation key. Prefer
    STEWIE_SESSION_SECRET so rotating the automation API key does not invalidate live sessions (and
    a leaked automation key cannot mint session tokens). If unset, fall back to a key DERIVED from the
    automation key (kept distinct by a domain-separation tag) so an existing single-secret deployment
    still boots -- but a real deployment SHOULD set STEWIE_SESSION_SECRET."""
    s = os.environ.get("STEWIE_SESSION_SECRET", "")
    if s:
        return s.encode()
    # domain-separated derivation: distinct from the raw automation key, so the key bytes that sign
    # tokens are never the same bytes a client sends as X-API-Key.
    return hashlib.sha256(b"stewie.session.v1\x00" + automation_key()).digest()


def _token_aud() -> str:
    return os.environ.get("STEWIE_TOKEN_AUD", "") or _DEFAULT_AUD


def _revoked_path() -> str:
    from stewie.specs import config as CFG
    return os.path.join(CFG.data_dir(), "revoked_jti.json")


def revoke_jti(jti: str) -> None:
    """S-12: revoke a single session by its token id. Durable (data_dir) so a restart keeps the
    revocation; other live sessions are unaffected."""
    import os as _os
    p = _revoked_path()
    cur = _revoked_set()
    cur.add(jti)
    _os.makedirs(_os.path.dirname(p), exist_ok=True)
    from stewie.twin.io_fields import atomic_write_bytes
    atomic_write_bytes(p, json.dumps(sorted(cur)).encode())


def _revoked_set() -> set:
    p = _revoked_path()
    if not os.path.exists(p):
        return set()
    try:
        with open(p) as fh:
            return set(json.load(fh))
    except (json.JSONDecodeError, OSError, TypeError):
        return set()


def issue_token(email: str, *, now: float | None = None, ttl_s: float | None = None) -> str:
    """Mint a signed session token carrying op/exp/iss/aud/jti (S-12). Signed with the session secret,
    NOT the automation key."""
    t = now if now is not None else time.time()
    payload = json.dumps({"op": email.strip().lower(),
                          "exp": t + (ttl_s if ttl_s is not None else TOKEN_TTL_S),
                          "iat": t, "iss": _TOKEN_ISS, "aud": _token_aud(),
                          "jti": uuid.uuid4().hex},
                         separators=(",", ":")).encode()
    sig = hmac.new(_signing_secret(), payload, hashlib.sha256).digest()
    return (base64.urlsafe_b64encode(payload).decode().rstrip("=") + "." +
            base64.urlsafe_b64encode(sig).decode().rstrip("="))


def decode_claims(token: str) -> dict | None:
    """The token's claims dict IFF the signature verifies (S-12 introspection: jti for revocation,
    iss/aud for context). Does NOT check expiry/allowlist/revocation -- that is verify_token's job."""
    try:
        p64, s64 = token.split(".", 1)
        pad = lambda s: s + "=" * (-len(s) % 4)
        payload = base64.urlsafe_b64decode(pad(p64))
        sig = base64.urlsafe_b64decode(pad(s64))
        if not hmac.compare_digest(sig, hmac.new(_signing_secret(), payload, hashlib.sha256).digest()):
            return None
        return json.loads(payload)
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None


def verify_token(token: str, *, now: float | None = None) -> str | None:
    """The operator email if the token is signed, unexpired, ISSUER+AUDIENCE-matched, not revoked, and
    whitelisted; else None (S-12)."""
    d = decode_claims(token)
    if d is None:
        return None
    try:
        if (now if now is not None else time.time()) > float(d["exp"]):
            return None
        if d.get("iss") != _TOKEN_ISS or d.get("aud") != _token_aud():
            return None
        if d.get("jti") and d["jti"] in _revoked_set():
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
    from stewie.server import operators as OPS
    sr = OPS.store_role(identity)        # #117: a registered active account governs its own role
    if sr is not None:
        return sr
    env = os.environ.get("STEWIE_DIRECTORS", "")
    directors = (tuple(e.strip().lower() for e in env.split(",") if e.strip())
                 if env.strip() else allowlist())
    return "director" if identity.strip().lower() in directors else "operator"


def trusted_proxies() -> tuple:
    """S-03: the IP allowlist of proxies whose Tailscale identity assertion is trusted. Empty (unset)
    keeps the legacy `tailscale serve` topology working (the proxy IS the loopback/tailnet origin)."""
    env = os.environ.get("STEWIE_TRUSTED_PROXIES", "")
    return tuple(p.strip() for p in env.split(",") if p.strip())


def tailscale_identity(headers, *, peer_ip: str | None = None) -> str | None:
    """The whitelisted Tailscale identity, ONLY when the deployment opts in AND the assertion comes
    from a trusted proxy (S-03).

    The header is trusted only when STEWIE_TRUST_TAILSCALE=1. When STEWIE_TRUSTED_PROXIES is set, the
    request's immediate peer must be one of those addresses -- so a direct client cannot spoof the
    header even if it reaches the backend. (The shipped nginx ALSO clears the inbound client header at
    the edge, so the only Tailscale-User-Login the backend ever sees is the proxy's own.) When no
    proxy allowlist is declared, the legacy single-origin behavior is preserved (peer check is a
    no-op), so existing deployments keep working."""
    if os.environ.get("STEWIE_TRUST_TAILSCALE", "") != "1":
        return None
    proxies = trusted_proxies()
    if proxies and (peer_ip is None or peer_ip not in proxies):
        return None
    login = headers.get("tailscale-user-login", "") or headers.get("Tailscale-User-Login", "")
    return login.strip().lower() if login and is_allowed(login) else None
