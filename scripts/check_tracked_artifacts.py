"""[REQ:MT-01] Large-file / tracked-artifact policy gate.

The 2026-07-02 bloat audit found the maintainability risk is NEW large binaries slipping into git (the
tracked payload is ~345 MB, dominated by the DEM fixtures). This gate makes that impossible to do
quietly: it lists every git-tracked file over ``THRESHOLD_BYTES`` and FAILS if any is not on an explicit
allowlist. Adding a new large binary reds the build until it is either shrunk, externalized, or
deliberately allowlisted with a reason. The gate also reports the total tracked payload so its growth is
visible (MT-05 consumes this number).

The allowlist is the CURRENT known baseline, each entry tagged with its disposition: the DEM bundles are
KEEP-BUT-EXTERNALIZE (the big MT-01 follow-on -- replace with checksum manifests + a fetch script), the
rover meshes + benchmark fixtures are KEEP (real CC0 assets / real test data), the render GIFs are
TRIAGE (generated, candidates for untracking once their doc references are checked).
"""
from __future__ import annotations

import fnmatch
import os
import subprocess
import sys

THRESHOLD_BYTES = 5 * 1024 * 1024        # 5 MB: above this a tracked binary must be allowlisted

#: (glob, disposition) -- every currently-oversized tracked path matches exactly one entry.
ALLOWLIST: tuple[tuple[str, str], ...] = (
    ("samples/lunar_dem/*/*.rf32", "KEEP-EXTERNALIZE: real LOLA DEM bundle (MT-01 follow-on: manifest+fetch)"),
    ("samples/lunar_dem/*/*.r8", "KEEP-EXTERNALIZE: real DEM state-label raster (MT-01 follow-on)"),
    ("samples/lunar_dem/*/tiling/annotations.geojson",
     "KEEP-EXTERNALIZE: derived per-tile GeoJSON annotations (regenerable via scripts/tile_bundle.py; MT-01 follow-on)"),
    ("stewie/godot/assets/*/*.glb", "KEEP: real CC0 rover mesh (EZ-RASSOR / IPEx)"),
    ("benchmarks/*/fixtures/*.tif", "KEEP: real NAC shadow benchmark fixture"),
    ("stewie/godot/out/*.gif", "TRIAGE: generated render GIF (untrack once doc refs checked)"),
    ("viz/out/*.gif", "TRIAGE: generated viz GIF (untrack once doc refs checked)"),
)


def _repo_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def tracked_files() -> list[str]:
    root = _repo_root()
    out = subprocess.run(["git", "ls-files", "-z"], cwd=root, capture_output=True, text=True, check=True)
    return [p for p in out.stdout.split("\0") if p]


def is_allowlisted(path: str) -> bool:
    return any(fnmatch.fnmatch(path, pat) for pat, _ in ALLOWLIST)


def scan(threshold: int = THRESHOLD_BYTES) -> dict:
    """Return {total_bytes, oversized: [(path, bytes)], violations: [(path, bytes)]} over the tracked tree."""
    root = _repo_root()
    total = 0
    oversized: list[tuple[str, int]] = []
    for p in tracked_files():
        fp = os.path.join(root, p)
        try:
            n = os.path.getsize(fp)
        except OSError:
            continue
        total += n
        if n > threshold:
            oversized.append((p, n))
    violations = [(p, n) for p, n in oversized if not is_allowlisted(p)]
    return {"total_bytes": total, "oversized": sorted(oversized), "violations": sorted(violations)}


def main() -> int:
    r = scan()
    print(f"tracked payload: {r['total_bytes'] / 1048576:.1f} MB across {len(tracked_files())} files")
    print(f"oversized (> {THRESHOLD_BYTES // 1048576} MB): {len(r['oversized'])} "
          f"({len(r['oversized']) - len(r['violations'])} allowlisted)")
    if r["violations"]:
        print("\nPOLICY VIOLATION -- new large tracked binaries (not on the allowlist):")
        for p, n in r["violations"]:
            print(f"  {n / 1048576:6.1f} MB  {p}")
        print("\nShrink it, externalize it (manifest+fetch), or add an allowlist entry with a reason.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
