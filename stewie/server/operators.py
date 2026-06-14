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
import os
import re
import threading
import time

_PBKDF2_ITERS = 200_000
_SALT_BYTES = 16
_MIN_PASSWORD_LEN = 10
_MAX_FAILED = 5            # consecutive failed logins before lockout
_LOCKOUT_S = 15 * 60      # lockout window after _MAX_FAILED failures
_ROLES = ("director", "operator")
_STATUSES = ("active", "pending", "revoked")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

_LOCK = threading.RLock()


def _clock() -> float:
    """Monkeypatchable wall clock (lockout-window tests inject a fixed time)."""
    return time.time()


def _path() -> str:
    from stewie.specs import config as CFG
    return os.path.join(CFG.data_dir(), "operators.json")


def _load() -> dict:
    p = _path()
    if not os.path.exists(p):
        return {"version": 1, "operators": {}}
    try:
        d = json.load(open(p))
        if not isinstance(d, dict) or "operators" not in d:
            return {"version": 1, "operators": {}}
        return d
    except (json.JSONDecodeError, OSError):
        return {"version": 1, "operators": {}}


def _save(data: dict) -> None:
    from stewie.twin.io_fields import atomic_write_bytes
    os.makedirs(os.path.dirname(_path()), exist_ok=True)
    atomic_write_bytes(_path(), json.dumps(data, indent=1, sort_keys=True).encode())


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
def _validate_new(email: str, password: str) -> str:
    e = _norm(email)
    if not _EMAIL_RE.match(e):
        raise ValueError(f"{email!r} is not a valid email address")
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
