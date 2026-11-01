"""Regenerated fixtures reproduce the committed ones (the CI reproducibility gate).

A byte-identical regeneration holds only on one machine: the hosted runner's libm and SIMD paths move
floating-point results by an ULP or so (measured on the CI runner, 2026-11-01: payload values within 7.6e-11
relative and 8.4e-10 absolute, an error metric near 1e-10 within 3.8e-17). So this compares the working tree
against HEAD for the given directories exactly in structure, strings, integers and booleans, and within
``rtol``/``atol`` for floats (JSON numbers, ``.npz`` float arrays; the ephemeris coefficients against 1e-13 of their array's largest
magnitude, since a least-squares fit spreads input noise unevenly across them, measured 9e-9 relative on one
coefficient of an ~3e8-scale series). A digest is allowed
to differ only where it hashes a file this gate compares numerically itself (a fixture's ``payload_sha256`` and
its ``sources`` entries under ``crates/``, the ephemeris ``bin_sha256``, and a package's ephemeris hashes and
header size). Source-code hashes stay exact, so a source edited without regenerating its fixture still fails.
A new untracked file in a gated directory fails too.

    python scripts/check_fixtures_reproduce.py crates/stewie-oracle/fixtures pipeline/packages ...
"""
from __future__ import annotations

import argparse
import io
import json
import math
import subprocess
import sys

RTOL = 1e-9
ATOL = 1e-12
SCALE_RTOL = 1e-13   # the ephemeris coefficients (.bin): of the array's largest magnitude (1.5e11 m -> 0.015 m, under the
# fit's own 1e-10 rad on the Moon series, ~0.04 m)


def _git(*args: str) -> bytes:
    return subprocess.run(["git", *args], check=True, capture_output=True).stdout


def _digest_may_drift(path: str, ptr: str) -> bool:
    """True where a digest or size hashes a file that is itself compared numerically."""
    key = ptr.rsplit("/", 1)[-1]
    if key in ("payload_sha256", "bin_sha256"):
        return True
    if path.endswith(".meta.json") and ptr.startswith("/sources/crates/"):
        return True
    return path.startswith("pipeline/packages/") and ptr.startswith("/ephemeris/") and key in ("sha256", "bytes")


class Drift:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.max_rel = 0.0
        self.drifted: set[str] = set()

    def floats(self, path: str, ptr: str, a: float, b: float) -> None:
        if a == b or (math.isnan(a) and math.isnan(b)):
            return
        d = abs(a - b)
        if not d <= ATOL + RTOL * max(abs(a), abs(b)):
            self.errors.append(f"{path}{ptr}: {a!r} != {b!r} (|d| {d:.3g})")
            return
        self.drifted.add(path)
        self.max_rel = max(self.max_rel, d / max(abs(a), abs(b)))

    def json(self, path: str, ptr: str, a, b) -> None:
        if isinstance(a, bool) or isinstance(b, bool) or a is None or b is None:
            if a is not b and a != b:
                self.errors.append(f"{path}{ptr}: {a!r} != {b!r}")
        elif isinstance(a, float) and isinstance(b, float):
            self.floats(path, ptr, a, b)
        elif type(a) is not type(b):
            self.errors.append(f"{path}{ptr}: {type(a).__name__} != {type(b).__name__}")
        elif isinstance(a, dict):
            if a.keys() != b.keys():
                self.errors.append(f"{path}{ptr}: keys differ {sorted(a.keys() ^ b.keys())[:5]}")
                return
            for k in a:
                self.json(path, f"{ptr}/{k}", a[k], b[k])
        elif isinstance(a, list):
            if len(a) != len(b):
                self.errors.append(f"{path}{ptr}: length {len(a)} != {len(b)}")
                return
            for i, (x, y) in enumerate(zip(a, b)):
                self.json(path, f"{ptr}/{i}", x, y)
        elif a != b:
            if _digest_may_drift(path, ptr):
                self.drifted.add(path)
            else:
                self.errors.append(f"{path}{ptr}: {a!r} != {b!r}")

    def arrays(self, path: str, name: str, a, b, *, scale_relative: bool = False) -> None:
        import numpy as np
        if a.shape != b.shape or a.dtype != b.dtype:
            self.errors.append(f"{path}:{name}: {a.dtype}{a.shape} != {b.dtype}{b.shape}")
        elif np.issubdtype(a.dtype, np.floating):
            # a least-squares fit's coefficients spread an ULP of input noise unevenly: judge each against the
            # array's scale (SCALE_RTOL of its largest magnitude), not against itself
            atol = ATOL
            if scale_relative and a.size:
                atol = max(ATOL, SCALE_RTOL * float(np.nanmax(np.abs(a))))
            ok = np.isclose(a, b, rtol=RTOL, atol=atol, equal_nan=True)
            if not ok.all():
                i = int(np.flatnonzero(~ok.ravel())[0])
                self.errors.append(f"{path}:{name}[{i}]: {a.ravel()[i]!r} != {b.ravel()[i]!r}")
            elif not np.array_equal(a, b, equal_nan=True):
                self.drifted.add(path)
        elif not np.array_equal(a, b):
            self.errors.append(f"{path}:{name}: values differ")

    def file(self, path: str, old: bytes, new: bytes) -> None:
        if old == new:
            return
        if path.endswith(".json"):
            self.json(path, "", json.loads(old), json.loads(new))
        elif path.endswith((".bin", ".npz")):
            self.binary(path, old, new)
        else:
            self.errors.append(f"{path}: bytes differ (no numeric rule for this file type)")

    def binary(self, path: str, old: bytes, new: bytes) -> None:
        import numpy as np                       # only the binary rules need it (the Rust job's python is stdlib-only)
        if path.endswith(".bin"):
            if len(old) != len(new) or len(old) % 8:
                self.errors.append(f"{path}: {len(old)} bytes != {len(new)}")
            else:
                self.arrays(path, "f8", np.frombuffer(old, "<f8"), np.frombuffer(new, "<f8"), scale_relative=True)
        elif path.endswith(".npz"):
            a, b = np.load(io.BytesIO(old)), np.load(io.BytesIO(new))
            if sorted(a.files) != sorted(b.files):
                self.errors.append(f"{path}: arrays {sorted(a.files)} != {sorted(b.files)}")
            else:
                for k in a.files:
                    self.arrays(path, k, a[k], b[k])


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("dirs", nargs="+")
    args = ap.parse_args(argv)
    d = Drift()
    for root in args.dirs:
        for p in _git("ls-files", "--others", "--exclude-standard", "--", root).decode().split():
            d.errors.append(f"{p}: new untracked file (commit it or stop generating it)")
        for p in _git("ls-files", "--", root).decode().split():
            try:
                new = open(p, "rb").read()
            except FileNotFoundError:
                d.errors.append(f"{p}: deleted by the regeneration")
                continue
            d.file(p, _git("show", f"HEAD:{p}"), new)
    for e in d.errors[:40]:
        print(f"NOT REPRODUCED: {e}")
    print(f"{len(d.drifted)} file(s) drifted within rtol={RTOL:g}, atol={ATOL:g} (max relative {d.max_rel:.2e}); "
          f"{len(d.errors)} violation(s)")
    return 1 if d.errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
