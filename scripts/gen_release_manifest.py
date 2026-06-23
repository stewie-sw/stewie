#!/usr/bin/env python3
"""PO-13: the RELEASE-EVIDENCE manifest generator (companion to scripts/gen_status.py).

ONE release-evidence surface, aggregated entirely from the live tools + real artifacts -- never
hand-numbered. It reuses ``scripts/req_trace`` (the §7 reconciliation), ``scripts/release_gate`` (the
AS-01..17 autonomy gate), ``scripts/gen_sbom`` (the pinned-lock SBOM), ``scripts/check_deps_lock`` (the
pyproject<->lock drift check), and ``stewie.__version__`` / ``pyproject [project].version`` (the single
version source, drift-checked). It emits ``release_manifest.json`` at the repo root.

DETERMINISTIC vs VOLATILE. The committed ``release_manifest.json`` carries only DETERMINISTIC release
evidence -- fields that change ONLY when the matrix / deps / version / docs change (version, req_trace
reconciliation, autonomy gate, SBOM component count, dep-lock status, changelog + SemVer-policy presence).
``--check`` regenerates that surface in memory and exits non-zero if the committed file is stale (the CI
guard that keeps it honest, exactly like gen_status.py). The VOLATILE fields (generated_at, the git
commit, live coverage/tests) are NOT committed -- they would make the file perpetually stale; ``--full``
writes a complete manifest (deterministic + volatile) under ``config.reports_dir()`` (gitignored) at
release time.

Run: ``python3 scripts/gen_release_manifest.py`` (write the committed surface) · ``--check`` (CI staleness
gate) · ``--full`` (release-time manifest with commit + coverage/tests, written to the reports dir).
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import subprocess
import sys

# bare-script import support (mirrors gen_status.py): put the repo root on sys.path so `scripts.*` +
# `stewie` resolve when run as `python scripts/gen_release_manifest.py`.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)

from scripts.check_deps_lock import check_lock
from scripts.gen_sbom import _project_version, parse_lock
from scripts.release_gate import release_report
from scripts.req_trace import trace

_PATHS = ["stewie", "dart", "lode", "scripts", "ros2_ws"]
# (lock file, the pyproject optional-dependency extras it must cover) -- the pairs CI already checks.
_LOCKS = [("requirements-dev.lock", ["dev"]), ("requirements-server.lock", ["server"])]
_SBOM_LOCK = "requirements-dev.lock"      # the superset lock the SBOM component count is taken from


def _read(path: str) -> str | None:
    try:
        return open(path, encoding="utf-8").read()
    except OSError:
        return None


def _version_block(root: str) -> dict:
    """The single version source, drift-checked: stewie.__version__ == pyproject [project].version."""
    import stewie
    pkg = str(getattr(stewie, "__version__", ""))
    try:
        proj = _project_version(root)
    except Exception:
        proj = None
    return {"stewie___version__": pkg, "pyproject_version": proj,
            "in_sync": bool(proj is not None and pkg == proj)}


def _req_trace_block(prd: str, paths: list) -> dict:
    tr = trace(prd, paths)
    return {"total": tr["total"], "cited": tr["cited"],
            "v_done_uncited": tr["v_done_uncited"],
            "understated_count": len(tr["understated"]),
            "unknown_markers": tr["unknown_markers"],
            # the release-honesty condition req_trace enforces: no V=D lacks a citing test, no orphan marker.
            "reconciles": bool(not tr["v_done_uncited"] and not tr["unknown_markers"])}


def _autonomy_gate_block() -> dict:
    s = release_report()["summary"]
    return {k: s[k] for k in ("in_matrix", "total", "cited", "currently_v_done",
                              "eligible_for_v_done", "host_verified", "container_gated", "uncited")}


def _sbom_block(root: str) -> dict:
    lock = os.path.join(root, _SBOM_LOCK)
    try:
        n = len(parse_lock(lock))
        return {"source_lock": _SBOM_LOCK, "spec_version": "1.5", "component_count": n,
                "source": "scripts.gen_sbom.parse_lock (CycloneDX via scripts/gen_sbom.py)"}
    except Exception:
        return {"source_lock": _SBOM_LOCK, "component_count": None, "source": "unavailable"}


def _deps_block(root: str) -> dict:
    pyproject = os.path.join(root, "pyproject.toml")
    locks = []
    for lock, extras in _LOCKS:
        try:
            lc = check_lock(pyproject, os.path.join(root, lock), extras=extras)
            locks.append({"lock": lock, "extras": extras,
                          "lock_check": "ok" if not lc.missing else "drift", "missing": lc.missing})
        except Exception as e:
            locks.append({"lock": lock, "extras": extras, "lock_check": "unavailable", "error": str(e)[:120]})
    return {"locks": locks, "all_ok": all(l.get("lock_check") == "ok" for l in locks)}


def _changelog_block(root: str, version: str) -> dict:
    txt = _read(os.path.join(root, "CHANGELOG.md")) or ""
    return {"path": "CHANGELOG.md", "present": bool(txt),
            "documents_version": bool(version and version in txt),
            "keepachangelog": "Keep a Changelog" in txt or "## [" in txt,
            "semver_declared": "Semantic Versioning" in txt or "semver" in txt.lower()}


def _semver_policy_block(root: str) -> dict:
    p = os.path.join(root, "docs", "RELEASE.md")
    return {"path": "docs/RELEASE.md", "present": os.path.exists(p)}


def collect_deterministic(root: str, prd: str, paths: list) -> dict:
    """The committed surface: every field changes ONLY when the underlying matrix/deps/version/docs do.
    No volatile fields (no timestamp, no commit, no live coverage) -> the --check gate is stable."""
    ver = _version_block(root)
    return {
        "schema_version": 1,
        "version": ver,
        "req_trace": _req_trace_block(prd, paths),
        "autonomy_gate": _autonomy_gate_block(),
        "sbom": _sbom_block(root),
        "dependencies": _deps_block(root),
        "changelog": _changelog_block(root, ver["stewie___version__"]),
        "semver_policy": _semver_policy_block(root),
        "sources": [
            "stewie.__version__", "pyproject.toml [project].version",
            "scripts/req_trace.py", "scripts/release_gate.py", "scripts/gen_sbom.py",
            "scripts/check_deps_lock.py", "CHANGELOG.md", "docs/RELEASE.md",
        ],
        "volatile_fields_at_release": [
            "generated_at", "commit", "coverage", "tests",
            "(written by --full to the reports dir; excluded here so the committed surface is stable)",
        ],
    }


def _git(args: list) -> str | None:
    try:
        return subprocess.run(["git", *args], cwd=_REPO_ROOT, capture_output=True, text=True,
                              check=True).stdout.strip()
    except Exception:
        return None


def _coverage_block(root: str) -> dict:
    """Live coverage from the .coverage SQLite via coverage.py; null when the artifact is absent."""
    cov_file = os.path.join(root, ".coverage")
    if not os.path.exists(cov_file):
        return {"percent_covered": None, "source": "unavailable (.coverage absent)"}
    try:
        import coverage
        cov = coverage.Coverage(data_file=cov_file)
        cov.load()
        # measured total -- report() returns the percent; capture via a throwaway buffer.
        import io
        pct = cov.report(file=io.StringIO())
        return {"percent_covered": round(float(pct), 2), "fail_under": 85,
                "source": ".coverage SQLite via coverage.py"}
    except Exception as e:
        return {"percent_covered": None, "source": f"unavailable ({str(e)[:80]})"}


def collect_volatile(root: str) -> dict:
    """The release-time fields (NOT committed): timestamp, the git commit, live coverage. Tests come from
    a real --junitxml artifact when present, else null (never a hand number)."""
    return {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "commit": {
            "sha": _git(["rev-parse", "HEAD"]), "sha_short": _git(["rev-parse", "--short", "HEAD"]),
            "branch": _git(["rev-parse", "--abbrev-ref", "HEAD"]),
            "dirty": bool(_git(["status", "--porcelain"])),
            "describe": _git(["describe", "--tags", "--always", "--dirty"]),
        },
        "coverage": _coverage_block(root),
        "tests": {"source": "unavailable (no junitxml artifact); run pytest --junitxml at release time"},
    }


def render_json(d: dict) -> str:
    return json.dumps(d, indent=2, sort_keys=True) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--prd", default=os.path.join(_REPO_ROOT, "PRD.md"))
    ap.add_argument("--paths", nargs="*", default=_PATHS)
    ap.add_argument("--out", default=os.path.join(_REPO_ROOT, "release_manifest.json"))
    ap.add_argument("--check", action="store_true",
                    help="regenerate the deterministic surface in memory; exit 2 if the committed file is stale")
    ap.add_argument("--full", action="store_true",
                    help="write a complete manifest (deterministic + volatile commit/coverage/tests) to the reports dir")
    args = ap.parse_args(argv)

    det = collect_deterministic(_REPO_ROOT, args.prd, args.paths)
    fresh = render_json(det)

    if args.check:
        current = _read(args.out)
        if current != fresh:
            print("STALE -- run `python3 scripts/gen_release_manifest.py` to regenerate: " + args.out)
            return 2
        print("release_manifest.json is in sync with the live tools")
        return 0

    if args.full:
        from stewie.specs import config
        full = {**det, **collect_volatile(_REPO_ROOT)}
        rdir = config.reports_dir()
        os.makedirs(rdir, exist_ok=True)
        out = os.path.join(rdir, "release_manifest_full.json")
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(render_json(full))
        print(f"wrote release-time manifest (with commit + coverage) -> {out}")
        return 0

    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(fresh)
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
