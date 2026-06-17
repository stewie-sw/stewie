"""CT-06 [REQ:CT-06]: production contract checks use explicit exceptions, never a removable `assert`.

A bare `assert` is stripped by `python -O`, silently disabling the check -- so a contract or precondition
guard written as `assert` is a reliability hazard (it evaporates in an optimized run). The runtime packages
(stewie / dart / lode / forge / leap) must therefore `raise` instead. Test files and the eval / demo /
scripts diagnostics may assert freely. This guard scans the real checked-in runtime modules and fails if a
bare `assert` statement reappears, so the conversion cannot silently regress. No fabricated input -- it reads
the actual source tree.
"""
from __future__ import annotations

import os
import re

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PKGS = ("stewie", "dart", "lode", "forge", "leap")
_SKIP_DIR = {"__pycache__", "tests", "eval", "demo", "scripts", ".tools"}
_ASSERT = re.compile(r"^\s*assert\b")


def _runtime_modules():
    for pkg in _PKGS:
        for dirpath, _dirs, files in os.walk(os.path.join(_ROOT, pkg)):
            if any(p.startswith(".") or p in _SKIP_DIR for p in dirpath.split(os.sep)):
                continue
            for fn in files:
                if fn.endswith(".py") and not fn.startswith("test_"):
                    yield os.path.join(dirpath, fn)


def test_ct06_no_bare_assert_in_runtime_modules():
    offenders = []
    for p in _runtime_modules():
        for i, ln in enumerate(open(p, encoding="utf-8", errors="replace"), 1):
            if _ASSERT.match(ln):
                offenders.append(f"{os.path.relpath(p, _ROOT)}:{i}")
    assert not offenders, (
        "CT-06: bare `assert` (stripped by `python -O`) in runtime modules -- use an explicit raise:\n  "
        + "\n  ".join(offenders))


def test_guard_actually_scans_something():
    """Sanity: the walk must find real runtime modules (else the guard would pass vacuously)."""
    assert sum(1 for _ in _runtime_modules()) > 50
