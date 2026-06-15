"""#117: the persistent operator-account store -- per-user salted-PBKDF2 credentials.

The store that turns the cockpit's whitelist into real accounts. One JSON document at
``data_dir/operators.json`` (few accounts -> a single file under a process lock, atomically
written via the W-1..W-3 io_fields helper). Each record carries a salted PBKDF2-HMAC-SHA256
password hash (NEVER the plaintext), a role (director|operator), a status
(active|pending|revoked), a failed-login counter + lockout window, and the audit fields
(created/approved/by).

Authority model (back-compat preserving): the store is authoritative ONLY for emails it holds.
An email with no record falls back to the env/default allowlist in stewie.server.auth -- so an
existing deployment with an empty store behaves exactly as before, and self-registration / the
"set password" bootstrap ADD records that then govern. No auto-seeding (which would override an
operator-restricting STEWIE_ALLOWED_OPERATORS).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import threading
import time

log = logging.getLogger("stewie.server")


class AccountStoreError(RuntimeError):
    """S-05 / A-05: the account store is corrupt, unreadable, or schema-invalid. Raised so the caller
    FAILS CLOSED (no silent collapse to an empty store, which would re-enable fallback directors)."""


_PBKDF2_ITERS = 200_000
_SALT_BYTES = 16
_MIN_PASSWORD_LEN = 10
_MAX_FAILED = 5            # consecutive failed logins before lockout
_LOCKOUT_S = 15 * 60      # lockout window after _MAX_FAILED failures
# AG-01 (PRD §7.12): the role ladder in ASCENDING capability order. The tuple index IS the rank,
# so guest < trainee < operator < director. The legacy two roles (director/operator) are preserved,
# so existing stores migrate forward without data loss; `guest` (read-only) and `trainee`
# (own-sandbox write) are the new lower tiers for the invitation-only / training product.
_ROLES = ("guest", "trainee", "operator", "director")
_STATUSES = ("active", "pending", "revoked")


def role_rank(role: str | None) -> int:
    """Capability rank of a role for `require_role`-style gating. Higher = more capable.
    An unknown / None / empty role ranks -1 (BELOW guest) so it can never satisfy a
    `rank(user) >= rank(min)` gate -- the comparison fails closed."""
    return _ROLES.index(role) if role in _ROLES else -1
# S-02: a standards-ish but DELIBERATELY CONSERVATIVE address. The local part is a dot-atom over a
# safe subset (alnum + the common interchange specials . _ % + -), no leading/trailing/double dot;
# the domain is letter/digit/hyphen labels separated by dots with a >=2-char alpha TLD. This admits
# NONE of the HTML/control/shell metacharacters (< > " ' & ; / \ space NUL tab ...) the old
# `[^@\s]+` pattern let through (it accepted "<img/src=x/onerror=alert(1)>@x.co"). RFC 5321 permits a
# wider local set, but a planner whitelist has no need of "/&'!#" addresses and rejecting them shrinks
# the XSS/injection surface; ordinary addresses (user.name+tag@host.tld) still validate.
_EMAIL_LOCAL = r"[A-Za-z0-9_%+-]+(?:\.[A-Za-z0-9_%+-]+)*"
_EMAIL_DOMAIN = r"(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}"
_EMAIL_RE = re.compile(rf"^{_EMAIL_LOCAL}@{_EMAIL_DOMAIN}$")
_MAX_EMAIL_LEN = 254        # RFC 5321 4.5.3.1.3: the full address path cannot exceed 254 octets
_MAX_LOCAL_LEN = 64         # RFC 5321 4.5.3.1.1: the local part cannot exceed 64 octets
# Defense in depth: even if a future regex edit slips, refuse these outright (XSS/HTML/control).
_EMAIL_FORBIDDEN = set('<>"\'&;/\\ `') | {chr(c) for c in range(0x00, 0x20)}

_LOCK = threading.RLock()


def _clock() -> float:
    """Monkeypatchable wall clock (lockout-window tests inject a fixed time)."""
    return time.time()


def _path() -> str:
    from stewie.specs import config as CFG
    return os.path.join(CFG.data_dir(), "operators.json")


def _marker_path() -> str:
    """S-05: the bootstrap-completed marker. Its existence means the store HAS held accounts, so a
    later-missing store is a fault (deletion/partial restore), NOT a clean first run -> fail closed."""
    return _path() + ".bootstrapped"


def _bootstrap_done() -> bool:
    return os.path.exists(_marker_path())


def _mark_bootstrap_done() -> None:
    try:
        with open(_marker_path(), "w") as f:
            f.write(json.dumps({"bootstrapped_at": round(time.time(), 3)}))
    except OSError as e:
        log.error("S-05: could not write the bootstrap-completed marker %r: %r", _marker_path(), e)


def _quarantine(p: str, reason: str) -> None:
    """Move a corrupt store aside (operators.json.corrupt.<ts>) so a later _save cannot overwrite an
    incomplete account set, and the bad bytes are preserved for recovery. High-priority alert."""
    dst = f"{p}.corrupt.{int(time.time())}"
    try:
        os.replace(p, dst)
        log.critical("S-05 ALERT: account store %r is corrupt (%s); quarantined to %r. Authentication "
                     "is FAILING CLOSED until an operator restores a valid store.", p, reason, dst)
    except OSError as e:
        log.critical("S-05 ALERT: account store %r is corrupt (%s) and could NOT be quarantined (%r); "
                     "authentication is FAILING CLOSED.", p, reason, e)


def _load() -> dict:
    """Read the account store, FAILING CLOSED on corruption (S-05 / A-05).

    - No file AND no bootstrap marker -> a clean first run: the empty store (back-compat).
    - No file BUT a bootstrap marker exists -> the store was deleted/partly restored after enrollment:
      AccountStoreError (so fallback directors cannot silently reappear).
    - File present but unreadable / not JSON / wrong schema -> quarantine + AccountStoreError.
    """
    p = _path()
    if not os.path.exists(p):
        if _bootstrap_done():
            raise AccountStoreError(
                f"account store {p!r} is missing but enrollment was completed (marker present); "
                "refusing to fall back to the env/default allowlist -- restore the store")
        return {"version": 1, "operators": {}}
    try:
        with open(p) as fh:
            raw = fh.read()
    except OSError as e:
        # unreadable (permission/IO) -> we cannot prove the account set; fail closed (do NOT quarantine
        # a file we couldn't even read -- a transient permission fault should not destroy the store)
        raise AccountStoreError(f"account store {p!r} is unreadable: {e!r}") from e
    try:
        d = json.loads(raw)
    except json.JSONDecodeError as e:
        _quarantine(p, f"invalid JSON: {e}")
        raise AccountStoreError(f"account store {p!r} is corrupt (invalid JSON)") from e
    if not isinstance(d, dict) or not isinstance(d.get("operators"), dict):
        _quarantine(p, "schema mismatch (no 'operators' mapping)")
        raise AccountStoreError(f"account store {p!r} has an invalid schema")
    return d


def _save(data: dict) -> None:
    from stewie.twin.io_fields import atomic_write_bytes
    os.makedirs(os.path.dirname(_path()), exist_ok=True)
    atomic_write_bytes(_path(), json.dumps(data, indent=1, sort_keys=True).encode())
    _mark_bootstrap_done()      # S-05: enrollment happened -> a later-missing store is now a fault


def _norm(email: str) -> str:
    return email.strip().lower()


def _hash(password: str, salt_hex: str) -> str:
    salt = bytes.fromhex(salt_hex)
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ITERS).hex()


# ---- queries -------------------------------------------------------------------------------
def get(email: str) -> dict | None:
    """The PUBLIC record (no hash/salt) for an account, or None if unknown."""
    with _LOCK:
        rec = _load()["operators"].get(_norm(email))
    if rec is None:
        return None
    return {k: v for k, v in rec.items() if k not in ("pw_hash", "pw_salt")}


def exists(email: str) -> bool:
    with _LOCK:
        return _norm(email) in _load()["operators"]


def has_password(email: str) -> bool:
    with _LOCK:
        rec = _load()["operators"].get(_norm(email))
    return bool(rec and rec.get("pw_hash"))


def is_active(email: str) -> bool:
    """True if a store record exists AND is active. None (no record) -> caller falls back to the
    env/default allowlist; this function only reports what the STORE knows."""
    with _LOCK:
        rec = _load()["operators"].get(_norm(email))
    return bool(rec and rec.get("status") == "active")


def store_role(email: str) -> str | None:
    """The store's role for an ACTIVE account, else None (caller falls back to auth.role_of)."""
    with _LOCK:
        rec = _load()["operators"].get(_norm(email))
    if rec and rec.get("status") == "active":
        return rec.get("role", "operator")
    return None


def list_all() -> list:
    """All accounts as public records, sorted by email -- for the admin panel."""
    with _LOCK:
        ops = _load()["operators"]
    out = [{k: v for k, v in r.items() if k not in ("pw_hash", "pw_salt")} for r in ops.values()]
    return sorted(out, key=lambda r: r["email"])


# ---- mutations -----------------------------------------------------------------------------
def _validate_email(email: str) -> str:
    """S-02: normalize + strictly validate an operator email. Rejects over-long input, control/HTML
    metacharacters, and anything outside a conservative dot-atom@domain grammar (so a value reaching
    the UI or a log can never carry an `<img onerror>`-style payload). Raises ValueError on a bad
    address; returns the normalized (lower-cased, stripped) form."""
    e = _norm(email)
    if not e or len(e) > _MAX_EMAIL_LEN:
        raise ValueError(f"{email!r} is not a valid email address (length)")
    if _EMAIL_FORBIDDEN & set(e):
        raise ValueError(f"{email!r} is not a valid email address (forbidden character)")
    if len(e.split("@", 1)[0]) > _MAX_LOCAL_LEN:
        raise ValueError(f"{email!r} is not a valid email address (local part too long)")
    if not _EMAIL_RE.match(e):
        raise ValueError(f"{email!r} is not a valid email address")
    return e


def _validate_new(email: str, password: str) -> str:
    e = _validate_email(email)
    if len(password) < _MIN_PASSWORD_LEN:
        raise ValueError(f"password must be at least {_MIN_PASSWORD_LEN} characters")
    return e


def register(email: str, password: str, *, role: str = "operator",
             status: str = "pending", by: str | None = None) -> dict:
    """Self-service registration: create a PENDING operator account (default). Raises ValueError
    on a bad email, a weak password, an existing account, or a bad role/status."""
    e = _validate_new(email, password)
    if role not in _ROLES:
        raise ValueError(f"role must be one of {_ROLES}")
    if status not in _STATUSES:
        raise ValueError(f"status must be one of {_STATUSES}")
    salt_hex = os.urandom(_SALT_BYTES).hex()
    now = _clock()
    with _LOCK:
        data = _load()
        if e in data["operators"]:
            raise ValueError(f"an account for {e!r} already exists")
        data["operators"][e] = {
            "email": e, "role": role, "status": status,
            "pw_salt": salt_hex, "pw_hash": _hash(password, salt_hex),
            "created_at": now, "approved_at": (now if status == "active" else None),
            "approved_by": (by if status == "active" else None),
            "failed": 0, "locked_until": 0.0, "last_login": None,
        }
        _save(data)
    return get(e)  # type: ignore[return-value]


def create_active(email: str, password: str, *, role: str = "operator",
                  by: str | None = None) -> dict:
    """Director-creates OR bootstrap self-promotion: an immediately-ACTIVE account."""
    return register(email, password, role=role, status="active", by=by)


def bootstrap_director_from_env() -> str | None:
    """First-director provisioning from the DEPLOY ENV, so the shared deploy key never has to be
    pasted into a browser (the old 'Settings -> Advanced -> automation API key' onboarding is removed).
    If STEWIE_BOOTSTRAP_DIRECTOR (an email) + STEWIE_BOOTSTRAP_PASSWORD are set, the account does NOT
    already exist, AND no active director exists yet, seed it as an active director. Idempotent + safe
    to call on every boot; returns the seeded email or None. The founding director then signs in with
    that password and the shared key stays server-side (X-API-Key remains for CI automation only)."""
    email = (os.environ.get("STEWIE_BOOTSTRAP_DIRECTOR", "") or "").strip().lower()
    password = os.environ.get("STEWIE_BOOTSTRAP_PASSWORD", "")
    if not email or not password:
        return None
    if exists(email):
        return None                                        # already provisioned -> no-op
    if any(r["status"] == "active" and r["role"] == "director" for r in list_all()):
        return None                                        # a fleet is already configured -> don't seed
    try:
        create_active(email, password, role="director", by="bootstrap-env")
    except ValueError:
        return None                                        # bad email / weak password -> skip (logged by caller)
    return email


def verify_credentials(email: str, password: str) -> str | None:
    """The normalized email iff the account is active, unlocked, and the password matches; else
    None (caller returns a GENERIC error -- no existence/lock leak). Failed attempts increment the
    lockout counter; a success resets it and stamps last_login."""
    e = _norm(email)
    now = _clock()
    with _LOCK:
        data = _load()
        rec = data["operators"].get(e)
        if rec is None or rec.get("status") != "active" or not rec.get("pw_hash"):
            return None
        if rec.get("locked_until", 0.0) > now:
            return None
        ok = hmac.compare_digest(_hash(password, rec["pw_salt"]), rec["pw_hash"])
        if ok:
            rec["failed"] = 0
            rec["locked_until"] = 0.0
            rec["last_login"] = now
            _save(data)
            return e
        rec["failed"] = int(rec.get("failed", 0)) + 1
        if rec["failed"] >= _MAX_FAILED:
            rec["locked_until"] = now + _LOCKOUT_S
            rec["failed"] = 0
        _save(data)
        return None


def is_locked(email: str) -> bool:
    with _LOCK:
        rec = _load()["operators"].get(_norm(email))
    return bool(rec and rec.get("locked_until", 0.0) > _clock())


def _mutate(email: str, fn) -> dict:
    e = _norm(email)
    with _LOCK:
        data = _load()
        rec = data["operators"].get(e)
        if rec is None:
            raise ValueError(f"no account for {e!r}")
        fn(rec)
        _save(data)
    return get(e)  # type: ignore[return-value]


def approve(email: str, by: str, *, role: str = "operator") -> dict:
    if role not in _ROLES:
        raise ValueError(f"role must be one of {_ROLES}")

    def _f(rec):
        rec["status"] = "active"
        rec["role"] = role
        rec["approved_at"] = _clock()
        rec["approved_by"] = by
        rec["failed"] = 0
        rec["locked_until"] = 0.0
    return _mutate(email, _f)


def revoke(email: str, by: str) -> dict:
    def _f(rec):
        rec["status"] = "revoked"
        rec["approved_by"] = by
    return _mutate(email, _f)


def set_role(email: str, role: str, by: str) -> dict:
    if role not in _ROLES:
        raise ValueError(f"role must be one of {_ROLES}")

    def _f(rec):
        rec["role"] = role
        rec["approved_by"] = by
    return _mutate(email, _f)


def set_password(email: str, password: str) -> dict:
    """Admin reset OR self-change (the caller enforces old-password / authorization)."""
    if len(password) < _MIN_PASSWORD_LEN:
        raise ValueError(f"password must be at least {_MIN_PASSWORD_LEN} characters")
    salt_hex = os.urandom(_SALT_BYTES).hex()

    def _f(rec):
        rec["pw_salt"] = salt_hex
        rec["pw_hash"] = _hash(password, salt_hex)
        rec["failed"] = 0
        rec["locked_until"] = 0.0
    return _mutate(email, _f)


def verify_old_password(email: str, password: str) -> bool:
    """For self-change: does the supplied password match the stored hash? (No lockout side effect.)"""
    with _LOCK:
        rec = _load()["operators"].get(_norm(email))
    if not rec or not rec.get("pw_hash"):
        return False
    return hmac.compare_digest(_hash(password, rec["pw_salt"]), rec["pw_hash"])


def delete(email: str) -> bool:
    e = _norm(email)
    with _LOCK:
        data = _load()
        if e not in data["operators"]:
            return False
        del data["operators"][e]
        _save(data)
    return True
