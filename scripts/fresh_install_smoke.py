#!/usr/bin/env python3
"""OPS-03 (PRD §27.2.A / PO-05) — fresh-install smoke for the dependency LOCK.

Two modes:
  * FAST (default, always-on in CI): audit the lock is fully hash-pinned, and verify the resolved
    environment this runs in matches the lock pins (no drift between what CI installed and the lock).
  * REAL (opt-in, --clean-install / STEWIE_LOCK_SMOKE=1): create a clean venv and `pip install` the
    pinned, hash-checked lock into it, proving the lock is installable end-to-end (network + slow).

Complements stewie/server/test_fresh_wheel.py (which installs the built wheel's [server] extra); this
targets the lock artifact itself. Pure stdlib in fast mode.

Usage:
    python3 scripts/fresh_install_smoke.py --lock requirements-dev.lock
    python3 scripts/fresh_install_smoke.py --lock requirements-dev.lock --clean-install
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import venv
from dataclasses import dataclass, field
from importlib import metadata

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _deps_lock import marker_applies, normalize, parse_lock  # noqa: E402

__all__ = ["audit_lock", "verify_installed", "clean_install", "LockAudit", "InstallCheck", "main"]


@dataclass
class LockAudit:
    total: int
    unhashed: list[str] = field(default_factory=list)   # pinned but no sha256 (--generate-hashes gap)


def audit_lock(lock: str) -> LockAudit:
    """Confirm every pinned package in the lock carries at least one sha256 hash."""
    pkgs = parse_lock(lock)
    # `colorama` etc. carry env markers; they are still hashed. A package with NO hashes is the gap.
    unhashed = sorted(p.name for p in pkgs if not p.hashes)
    return LockAudit(total=len(pkgs), unhashed=unhashed)


@dataclass
class InstallCheck:
    checked: int
    missing: list[str] = field(default_factory=list)      # in lock, not importable in this env
    mismatched: list[str] = field(default_factory=list)   # installed version != lock pin

    @property
    def ok(self) -> bool:
        return not self.missing and not self.mismatched


def _installed_versions() -> dict[str, str]:
    return {normalize(d.metadata["Name"]): d.version
            for d in metadata.distributions() if d.metadata["Name"]}


def verify_installed(lock: str) -> InstallCheck:
    """Offline check: the env this runs in matches the lock pins (skipping marker-excluded pkgs).

    Holds with zero drift only in an environment that was actually installed FROM this lock (CI from
    requirements-dev.lock). In a freshly-resolved dev env (e.g. `uv pip install -e .[dev]`) newer
    point releases may be installed; the function reports those as `mismatched` rather than failing,
    so a caller can decide whether to treat drift as fatal (CI) or informational (local).
    """
    installed = _installed_versions()
    missing: list[str] = []
    mismatched: list[str] = []
    checked = 0
    for p in parse_lock(lock):
        # Skip packages excluded by their environment marker on THIS platform (e.g. win32-only).
        if p.marker and not marker_applies(p.marker):
            continue
        checked += 1
        have = installed.get(p.name)
        if have is None:
            missing.append(p.name)
        elif have != p.version:
            mismatched.append(f"{p.name}: env {have} != lock {p.version}")
    return InstallCheck(checked=checked, missing=sorted(missing), mismatched=sorted(mismatched))


def clean_install(lock: str, venv_dir: str) -> int:  # pragma: no cover - opt-in, network + slow
    """Create a clean venv and install the hash-pinned lock into it (real fresh-install proof)."""
    venv.create(venv_dir, with_pip=True)
    py = os.path.join(venv_dir, "Scripts" if os.name == "nt" else "bin", "python")
    clean = {k: v for k, v in os.environ.items()
             if k not in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "PYTHONNOUSERSITE")}
    r = subprocess.run([py, "-m", "pip", "install", "--require-hashes", "-r", lock],
                       env=clean, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout)
        print(r.stderr, file=sys.stderr)
    return r.returncode


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="fresh-install smoke for a pinned requirements lock")
    ap.add_argument("--lock", required=True)
    ap.add_argument("--clean-install", action="store_true",
                    help="actually install the lock into a fresh venv (network + slow)")
    ap.add_argument("--venv", default=None, help="venv dir for --clean-install")
    ap.add_argument("--strict", action="store_true",
                    help="fail on any version drift between the env and the lock (CI / lock-installed env)")
    args = ap.parse_args(argv)

    audit = audit_lock(args.lock)
    if audit.total == 0:
        print(f"ERROR: empty lock {args.lock}", file=sys.stderr)
        return 1
    if audit.unhashed:
        print(f"FAIL: {len(audit.unhashed)} package(s) not hash-pinned: "
              f"{', '.join(audit.unhashed)}", file=sys.stderr)
        return 1
    print(f"OK: lock {os.path.basename(args.lock)} fully hash-pinned ({audit.total} packages)")

    if args.clean_install or os.environ.get("STEWIE_LOCK_SMOKE") == "1":
        venv_dir = args.venv or os.path.join(os.path.dirname(os.path.abspath(args.lock)),
                                             ".lock_smoke_venv")
        rc = clean_install(args.lock, venv_dir)
        print("OK: clean-venv install from lock succeeded" if rc == 0
              else "FAIL: clean-venv install from lock failed", file=sys.stderr)
        return rc

    chk = verify_installed(args.lock)
    # A package in the lock but NOT installed at all is always a broken install -> fail.
    if chk.missing:
        print(f"FAIL: in lock but not installed: {', '.join(chk.missing)}", file=sys.stderr)
        return 1
    # Version drift fails only under --strict (CI installs from the lock, so it has none); in a
    # freshly-resolved dev env newer point releases are informational, not a smoke failure.
    if chk.mismatched:
        sev = "FAIL" if args.strict else "WARN"
        print(f"{sev}: version drift vs lock: {'; '.join(chk.mismatched)}", file=sys.stderr)
        if args.strict:
            return 1
    print(f"OK: resolved env covers all lock pins ({chk.checked} checked, "
          f"{len(chk.mismatched)} version drift)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
