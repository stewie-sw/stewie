#!/usr/bin/env python3
"""PO-04 — the gated-tier report: make CI's un-runnable tiers VISIBLE instead of silent.

The CPU runner cannot execute the Chrono / ROS / Godot-render / GPU tiers (no pychrono, no rclpy,
no render egress, no torch), so those tests skip. A silent skip is indistinguishable from a deleted
tier; this report is the honest artifact in between — it never fakes execution, it only shows the
gates:

  * REAL collection pass: ``pytest --collect-only`` over the given paths (default: the configured
    suite). Module-level gates (``importorskip`` / ``allow_module_level`` skips) and already-True
    ``skipif`` markers are captured with their reasons and bucketed into tiers.
  * DECLARED-GATE census (environment-independent): the test sources are scanned for the gate
    declarations themselves (``pytest.importorskip``, call-time ``pytest.skip("...")``, ``skipif``
    reasons). The Godot render-egress gates fire mid-test, so a collect pass alone under-reports
    them; the source declarations are the stable census.

``--require <tier>`` (repeatable) fails the run when that tier has no visible gate left: CI pins
that the chrono / godot / ros tiers stay visible in the tree rather than silently disappearing.

Usage:
    python scripts/ci_tier_report.py --require chrono --require godot --require ros
"""
from __future__ import annotations

import argparse
import glob
import os
import re
import sys
import tomllib

__all__ = ["classify", "scan_declared_gates", "collect_env_skips", "main"]

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Ordered: first tier whose keyword appears in the (lowercased) reason wins. Keywords are the real
# gate vocabulary of this tree (pychrono importorskip, rclpy container note, render-egress skips,
# torch-gated VO, Haworth-sample skipifs, UDP guards, the opt-in wheel/lock smokes).
_TIER_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("chrono", ("pychrono", "chrono")),
    ("ros", ("rclpy", "rosbags", "ros 2", "ros2", "gazebo")),
    ("godot", ("godot", "render", "egress", "sidecar")),
    ("gpu", ("torch", "cuda", "gpu", "colmap")),
    ("opt-in", ("opt-in",)),
    ("network", ("udp", "network", "socket")),
    ("data", ("haworth", "sample not present", "dem", "scene", "dataset")),
]
_FALLBACK = "other"  # optional-dep import gates (cv2/PIL/scipy/...) and uncategorised reasons

_RE_IMPORTORSKIP = re.compile(r"pytest\.importorskip\(\s*[\'\"]([^\'\"]+)")
_RE_SKIP_CALL = re.compile(r"pytest\.skip\(\s*f?[\'\"]([^\'\"]+)")
_RE_REASON_KWARG = re.compile(r"reason\s*=\s*f?[\'\"]([^\'\"]+)")


def classify(reason: str) -> str:
    """Bucket a gate reason string into its tier (first keyword match wins)."""
    low = reason.lower()
    for tier, keywords in _TIER_KEYWORDS:
        if any(k in low for k in keywords):
            return tier
    return _FALLBACK


def _testpaths() -> list[str]:
    with open(os.path.join(_ROOT, "pyproject.toml"), "rb") as fh:
        cfg = tomllib.load(fh)
    return list(cfg["tool"]["pytest"]["ini_options"]["testpaths"])


def scan_declared_gates() -> list[tuple[str, str]]:
    """(relpath, reason) for every gate DECLARED in the configured suite's test sources."""
    gates: set[tuple[str, str]] = set()
    for tp in _testpaths():
        for path in glob.glob(os.path.join(_ROOT, tp, "**", "test_*.py"), recursive=True):
            with open(path, encoding="utf-8") as fh:
                src = fh.read()
            rel = os.path.relpath(path, _ROOT)
            for mod in _RE_IMPORTORSKIP.findall(src):
                gates.add((rel, f"importorskip: {mod}"))
            for reason in _RE_SKIP_CALL.findall(src):
                gates.add((rel, reason))
            for reason in _RE_REASON_KWARG.findall(src):
                gates.add((rel, reason))
    return sorted(gates)


def collect_env_skips(paths: list[str]) -> tuple[int, list[tuple[str, str]]]:
    """Run the REAL ``pytest --collect-only`` pass; return (exit code, [(nodeid, reason)]).

    Captures collection-level skips (module ``importorskip`` / ``allow_module_level``) and
    ``skipif`` markers whose condition already evaluated True in THIS environment. Call-time
    ``pytest.skip(...)`` inside test bodies is invisible here by design (it would need execution);
    the declared-gate census covers those.
    """
    import pytest

    gates: list[tuple[str, str]] = []

    class _Plugin:
        def pytest_collectreport(self, report):  # noqa: ANN001 - pytest hook
            if report.skipped:
                lr = report.longrepr
                reason = lr[2] if isinstance(lr, tuple) else str(lr)
                gates.append((report.nodeid, reason.removeprefix("Skipped: ")))

        def pytest_collection_finish(self, session):  # noqa: ANN001 - pytest hook
            for item in session.items:
                for m in item.iter_markers("skipif"):
                    cond = m.args[0] if m.args else None
                    # string conditions are pytest-eval'd at run time; only already-True booleans
                    # are known to skip from here (this tree's skipifs are all evaluated booleans)
                    if not isinstance(cond, str) and cond:
                        gates.append((item.nodeid, str(m.kwargs.get("reason", "skipif"))))
                        break

    rc = int(pytest.main(["--collect-only", "-q", "-p", "no:cacheprovider", *paths],
                         plugins=[_Plugin()]))
    return rc, gates


def _by_tier(gates: list[tuple[str, str]]) -> dict[str, list[tuple[str, str]]]:
    out: dict[str, list[tuple[str, str]]] = {}
    for where, reason in gates:
        out.setdefault(classify(reason), []).append((where, reason))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="honest gated-tier report (PO-04)")
    ap.add_argument("paths", nargs="*", help="paths for the collect pass (default: configured suite)")
    ap.add_argument("--require", action="append", default=[], metavar="TIER",
                    help="fail unless this tier has at least one visible gate (repeatable)")
    args = ap.parse_args(argv)

    os.chdir(_ROOT)
    declared = scan_declared_gates()
    rc, env_skips = collect_env_skips(args.paths)
    # 5 == NO_TESTS_COLLECTED: legitimate when the given paths are entirely module-gated (every
    # test skipped AT collection) -- the skips themselves are the report. Anything else is real.
    if rc not in (0, 5):
        print(f"FAIL: collect-only pass exited {rc}", file=sys.stderr)
        return rc

    dec_tiers = _by_tier(declared)
    env_tiers = _by_tier(env_skips)
    print("\n=== gated-tier report (PO-04: skips visible, execution NOT faked) ===")
    print(f"{'tier':<10} {'declared':>8} {'env-skipped':>12}")
    for tier in sorted(set(dec_tiers) | set(env_tiers)):
        print(f"{tier:<10} {len(dec_tiers.get(tier, [])):>8} {len(env_tiers.get(tier, [])):>12}")
    for tier in sorted(env_tiers):
        for nodeid, reason in env_tiers[tier]:
            print(f"  [env-skip:{tier}] {nodeid}: {reason}")

    missing = [t for t in args.require
               if not dec_tiers.get(t) and not env_tiers.get(t)]
    if missing:
        print(f"FAIL: required gated tier(s) with NO visible gate: {', '.join(missing)}",
              file=sys.stderr)
        return 1
    if args.require:
        print(f"OK: required tiers visible: {', '.join(args.require)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
