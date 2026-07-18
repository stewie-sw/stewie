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
import logging
import os
import threading
import time
import uuid

# #285: serialize the read-modify-write of the durable revocation store. revoke_jti reads the set, adds a
# jti, then atomic_write_bytes; two concurrent logouts (sync handlers -> FastAPI threadpool) would both read
# the OLD set and the second write would drop the first's revocation -- a fail-OPEN lost-update window.
_REVOKE_LOCK = threading.Lock()

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
    # BP-04: production must not silently trust the built-in staff allowlist. In a TLS-terminated
    # (public/prod) posture with no explicit STEWIE_ALLOWED_OPERATORS, fail CLOSED (empty -> nobody is
    # allowlisted) rather than honoring the hardcoded emails. Local/dev/desktop keep the defaults.
    if os.environ.get("STEWIE_TLS_TERMINATED", "") == "1":
        return ()
    return DEFAULT_ALLOWLIST


def identity_on_builtin_defaults() -> bool:
    """[REQ:BP-04] True when operator identity runs on BUILT-IN defaults -- no explicit
    STEWIE_ALLOWED_OPERATORS AND no STEWIE_DIRECTORS. A DEGRADED posture that /healthz + /config surface:
    in production allowlist() already fails closed on it, but the flag makes the misconfiguration visible
    (a real deployment sets both explicitly; dev/desktop may run on defaults)."""
    return (not os.environ.get("STEWIE_ALLOWED_OPERATORS", "").strip()
            and not os.environ.get("STEWIE_DIRECTORS", "").strip())


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


def gis_anon_key() -> bytes:
    """[AR-005] The SCOPED public-GIS anonymous-planner credential (STEWIE_GIS_ANON_KEY). nginx injects it on
    the anonymous read/plan routes via the distinct ``X-Stewie-Anon-Key`` header INSTEAD of the
    director-equivalent ``X-API-Key`` -- so a public /ide user resolves to the GUEST planner principal
    (``role_of('gis-anon') == 'guest'``: plan/read only, its own audit actor + quota), never director. It is
    DISTINCT from ``automation_key()``; empty means no anonymous principal is configured (the public routes
    then require real auth, fail-closed)."""
    return os.environ.get("STEWIE_GIS_ANON_KEY", "").encode()


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


_log = logging.getLogger("stewie.server.auth")


def session_secret_is_derived() -> bool:
    """[REQ:BP-03] True when STEWIE_SESSION_SECRET is unset, so the session-signing key is DERIVED from the
    automation key -- meaning an API-key rotation WOULD invalidate every live session. A real deployment
    must set STEWIE_SESSION_SECRET so the automation key and the session secret rotate independently."""
    return not os.environ.get("STEWIE_SESSION_SECRET", "")


def require_session_secret_for_prod() -> None:
    """[REQ:BP-03] Refuse to boot a PRODUCTION deployment (STEWIE_TLS_TERMINATED=1) whose session-signing
    key is derived from STEWIE_API_KEY. Without a standalone STEWIE_SESSION_SECRET, rotating the automation
    key silently invalidates all live sessions (review P1-2). Fails LOUD at startup, mirroring the API-key
    and proxy-trust guards -- never a silent fail-open. A non-production boot (TLS not terminated) only WARNS
    so a local run still starts."""
    if not session_secret_is_derived():
        return
    if os.environ.get("STEWIE_TLS_TERMINATED", "") == "1":
        raise RuntimeError(
            "production (STEWIE_TLS_TERMINATED=1) requires a standalone STEWIE_SESSION_SECRET: without it the "
            "session-signing key is derived from STEWIE_API_KEY, so rotating the automation key would silently "
            "invalidate all live sessions (BP-03). Set STEWIE_SESSION_SECRET and restart.")
    _log.warning(
        "auth: STEWIE_SESSION_SECRET unset -> session key DERIVED from STEWIE_API_KEY; an API-key rotation "
        "will invalidate live sessions. Set STEWIE_SESSION_SECRET for a real deployment (BP-03).")


def _token_aud() -> str:
    return os.environ.get("STEWIE_TOKEN_AUD", "") or _DEFAULT_AUD


def _revoked_path() -> str:
    from stewie.specs import config as CFG
    return os.path.join(CFG.data_dir(), "revoked_jti.json")


class RevocationStoreError(Exception):
    """SEC-02: the session-revocation store exists but cannot be read/parsed. Callers must FAIL CLOSED
    (deny the token) rather than treat the unreadable store as 'nothing is revoked'."""


def revoke_jti(jti: str) -> None:
    """S-12: revoke a single session by its token id. Durable (data_dir) so a restart keeps the
    revocation; other live sessions are unaffected. SEC-02: if the existing store is unreadable this
    RAISES instead of overwriting it -- silently replacing a corrupt store with a fresh single-entry
    file would drop every prior revocation and re-open the fail-open hole."""
    import os as _os
    p = _revoked_path()
    with _REVOKE_LOCK:                                   # #285: atomic read-modify-write -> no lost revocation
        try:
            cur = _revoked_set()
        except RevocationStoreError:
            from stewie.server import services as SVC
            SVC.record_revocation_failure(RevocationStoreError(f"revoke_jti aborted: {p} unreadable"))
            raise
        cur.add(jti)
        _os.makedirs(_os.path.dirname(p), exist_ok=True)
        from stewie.twin.io_fields import atomic_write_bytes
        atomic_write_bytes(p, json.dumps(sorted(cur)).encode())


def _revoked_set() -> set:
    """The revoked-jti set. An ABSENT file is the normal no-revocations state (empty). A present file
    that cannot be read or is not a JSON list RAISES RevocationStoreError (SEC-02 fail-closed) -- it must
    NOT collapse to an empty set, which would silently make every revoked token valid again."""
    p = _revoked_path()
    if not os.path.exists(p):
        return set()
    try:
        with open(p) as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
        raise RevocationStoreError(repr(e)) from e
    if not isinstance(data, list):
        raise RevocationStoreError(f"revocation store is not a JSON list: {type(data).__name__}")
    return set(data)


def is_revoked(jti: str) -> bool:
    """SEC-02: True iff the session jti is revoked. FAILS CLOSED -- if the store exists but cannot be
    read we cannot prove the token is NOT revoked, so we DENY (return True), flip a visible degraded
    health flag, and write an audit event. A corrupt store thus forces re-auth instead of silently
    honouring revoked tokens."""
    try:
        return jti in _revoked_set()
    except RevocationStoreError as e:
        from stewie.server import services as SVC
        SVC.record_revocation_failure(e)
        return True


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
        if d.get("jti") and is_revoked(d["jti"]):          # SEC-02: fails CLOSED on a corrupt store
            return None
        return d["op"] if is_allowed(d["op"]) else None
    except (ValueError, KeyError, TypeError):
        return None


def role_of(identity: str) -> str:
    """#68: 'director' (full state: truth views, training toggles, admin) or 'operator' (shaped
    telemetry only). Directors default to the WHOLE whitelist (today's three are all staff);
    STEWIE_DIRECTORS narrows it when trainees join the whitelist. 'api-key' = automation =
    director-equivalent. 'dev-open' (no key configured) = director. 'desktop-local' (the bundled
    single-user desktop app, STEWIE_DESKTOP=1 on loopback) = director."""
    if identity in ("api-key", "dev-open", "desktop-local"):
        return "director"
    if identity == "gis-anon":               # [AR-005] the scoped public-GIS planner: guest (plan/read), never director
        return "guest"
    from stewie.server import operators as OPS
    sr = OPS.store_role(identity)        # #117: a registered active account governs its own role
    if sr is not None:
        return sr
    env = os.environ.get("STEWIE_DIRECTORS", "")
    directors = (tuple(e.strip().lower() for e in env.split(",") if e.strip())
                 if env.strip() else allowlist())
    return "director" if identity.strip().lower() in directors else "operator"


def trusted_proxies() -> tuple:
    """S-03 / SEC-03: the allowlist of proxy peers (IP or CIDR) whose Tailscale identity assertion is
    trusted. REQUIRED (non-empty) whenever STEWIE_TRUST_TAILSCALE=1 -- see validate_proxy_trust_config."""
    env = os.environ.get("STEWIE_TRUSTED_PROXIES", "")
    return tuple(p.strip() for p in env.split(",") if p.strip())


def _peer_trusted(peer_ip: str | None, proxies: tuple) -> bool:
    """SEC-03: True iff `peer_ip` is inside the trusted-proxy allowlist. Each entry may be an exact
    token (a literal IP, or a non-IP peer label such as a unix-socket/testclient host), or a CIDR
    network. A None peer, or one matching no entry, is NOT trusted."""
    import ipaddress
    if peer_ip is None:
        return False
    if peer_ip in proxies:                       # exact token match (literal IP or non-IP peer label)
        return True
    try:
        ip = ipaddress.ip_address(peer_ip)
    except ValueError:
        return False                             # a non-IP peer with no exact match is not trusted
    for entry in proxies:
        try:
            if "/" in entry and ip in ipaddress.ip_network(entry, strict=False):
                return True
        except ValueError:
            continue
    return False


def validate_proxy_trust_config() -> None:
    """SEC-03: refuse to boot a deployment that TRUSTS the Tailscale identity header without declaring
    WHICH proxy peers may assert it. STEWIE_TRUST_TAILSCALE=1 with an empty STEWIE_TRUSTED_PROXIES would
    honor `Tailscale-User-Login` from ANY peer, so a direct client could spoof an allowlisted (even
    director) identity. Called at startup so the misconfiguration fails LOUD, not silently fail-open."""
    if os.environ.get("STEWIE_TRUST_TAILSCALE", "") == "1" and not trusted_proxies():
        raise RuntimeError(
            "STEWIE_TRUST_TAILSCALE=1 requires a non-empty STEWIE_TRUSTED_PROXIES allowlist (the proxy "
            "IP/CIDR whose Tailscale-User-Login header is trusted). Refusing to start fail-open (SEC-03).")


def tailscale_identity(headers, *, peer_ip: str | None = None) -> str | None:
    """The whitelisted Tailscale identity, ONLY when the deployment opts in AND the assertion comes from
    a trusted proxy peer (S-03 / SEC-03).

    The header is trusted only when STEWIE_TRUST_TAILSCALE=1 AND the immediate peer is in the
    STEWIE_TRUSTED_PROXIES allowlist (IP or CIDR). SEC-03: an EMPTY proxy allowlist is fail-closed here
    (the header is ignored) and is rejected outright at startup (validate_proxy_trust_config) -- trusting
    the header from an unbounded peer set let a direct client spoof an identity. The shipped nginx also
    clears the inbound client header at the edge, so the only value the backend sees is the proxy's own."""
    if os.environ.get("STEWIE_TRUST_TAILSCALE", "") != "1":
        return None
    proxies = trusted_proxies()
    if not proxies or not _peer_trusted(peer_ip, proxies):
        return None
    login = headers.get("tailscale-user-login", "") or headers.get("Tailscale-User-Login", "")
    return login.strip().lower() if login and is_allowed(login) else None
