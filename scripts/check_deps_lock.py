#!/usr/bin/env python3
"""OPS-03 (PRD §27.2.A / PO-05) — dependency-lock consistency check.

Asserts that every dependency declared in `pyproject.toml` (base + the requested extras) is actually
pinned in the corresponding `requirements-*.lock`. Fails (exit 1) on drift — a declared dependency
missing from the lock — which is the CI signal that a lock is stale after a pyproject edit. Pure text
over the real checked-in artifacts; no network, no install.

Usage:
    python3 scripts/check_deps_lock.py --pyproject pyproject.toml --lock requirements-dev.lock --extras dev
"""
from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _deps_lock import marker_applies, normalize, parse_lock, parse_pyproject  # noqa: E402

__all__ = ["parse_pyproject_deps", "check_lock", "LockCheck", "DEFAULT_IGNORE", "main"]

# Documented intentional lock exclusions (kept out of the lock on purpose, not drift):
#   pytest-xdist — pyproject [tool.pytest.ini_options] explains it is deliberately excluded from the
#   hash-pinned CI lock (a default `-n auto` would error in CI installed from the lock). It is in the
#   `dev` extra for the LOCAL parallel-run speedup only.
DEFAULT_IGNORE = frozenset({"pytest-xdist"})


def parse_pyproject_deps(path: str) -> dict:
    """Declared deps as {'base': set[str], 'extras': {extra: set[str]}} (normalized names)."""
    d = parse_pyproject(path)
    return {"base": d.base, "extras": d.extras}


@dataclass
class LockCheck:
    declared: list[str]
    locked: list[str]
    missing: list[str]    # declared (marker applies, not ignored) but absent from the lock = drift
    ignored: list[str]    # declared but intentionally excluded / marker-excluded (not a failure)

    @property
    def ok(self) -> bool:
        return not self.missing


def check_lock(pyproject: str, lock: str, *, extras: list[str],
               ignore: frozenset[str] = DEFAULT_IGNORE) -> LockCheck:
    deps = parse_pyproject(pyproject)
    declared: set[str] = set(deps.base)
    for ex in extras:
        if ex not in deps.extras:
            raise KeyError(f"extra {ex!r} not declared in {pyproject}")
        declared |= deps.extras[ex]

    ignore = frozenset(normalize(n) for n in ignore)
    locked = {p.name for p in parse_lock(lock)}
    missing: list[str] = []
    ignored: list[str] = []
    for name in sorted(declared):
        if name in locked:
            continue
        # a dep whose env marker excludes the lock's target platform is legitimately absent
        if not marker_applies(deps.markers.get(name)):
            ignored.append(name)
        elif name in ignore:
            ignored.append(name)
        else:
            missing.append(name)
    return LockCheck(declared=sorted(declared), locked=sorted(locked),
                     missing=missing, ignored=ignored)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="verify pyproject deps are covered by a requirements lock")
    ap.add_argument("--pyproject", default="pyproject.toml")
    ap.add_argument("--lock", required=True)
    ap.add_argument("--extras", nargs="*", default=[],
                    help="optional-dependency groups the lock should also cover (e.g. dev / server)")
    ap.add_argument("--ignore", nargs="*", default=None,
                    help="deps intentionally excluded from the lock (default: documented set)")
    args = ap.parse_args(argv)

    ignore = DEFAULT_IGNORE if args.ignore is None else frozenset(args.ignore)
    result = check_lock(args.pyproject, args.lock, extras=args.extras, ignore=ignore)
    label = "+".join(["base", *args.extras]) if args.extras else "base"
    if result.ok:
        extra = f" ({len(result.ignored)} intentionally excluded)" if result.ignored else ""
        print(f"OK: all {len(result.declared)} declared deps ({label}) are pinned in "
              f"{os.path.basename(args.lock)}{extra}")
        return 0
    print(f"DRIFT: {len(result.missing)} declared dep(s) ({label}) missing from "
          f"{os.path.basename(args.lock)}: {', '.join(result.missing)}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
