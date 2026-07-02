#!/usr/bin/env python3
"""OPS-03 (PRD §27.2.A / PO-05) — scan the RESOLVED dependency artifacts for known vulnerabilities.

The dependency-hardening chain already commits a hash-pinned lock (`requirements-*.lock`), builds a
CycloneDX SBOM (`gen_sbom.py`), checks lock/pyproject drift (`check_deps_lock.py`), and smoke-tests a
fresh install (`fresh_install_smoke.py`). This is the missing "scan resolved artifacts" step: it runs a
REAL vulnerability scan over the resolved lock and FAILS on a finding at/above the severity threshold,
so a shipped release cannot silently carry a CVE-bearing pin.

The scanner is `pip-audit` (queries the OSV / PyPI advisory DBs). Because that needs a network vuln DB,
the LIVE scan is a soft-gated leg — where the scanner or network is absent this exits SKIPPED, never
fabricating a clean result. The parse + gate logic is fully tested offline against REAL captured
pip-audit output (`scripts/fixtures/pip_audit/`).

Usage:
    python3 scripts/scan_artifacts.py --lock requirements-dev.lock          # live scan, gate the result
    python3 scripts/scan_artifacts.py --report captured.json                # gate a pre-captured report
    python3 scripts/scan_artifacts.py --lock requirements-dev.lock --ignore-vuln PYSEC-2021-66

Exit codes: 0 = clean (or all findings waived), 2 = findings at/above threshold (release refused),
3 = the scanner is unavailable / could not run (SKIPPED, not a pass — CI decides whether to hard-fail).
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass, field

# --- typed report shapes ------------------------------------------------------------------------

_ADVISORY_PREFIXES = ("PYSEC-", "CVE-", "GHSA-", "OSV-")


@dataclass(frozen=True)
class Component:
    name: str
    version: str


@dataclass(frozen=True)
class Finding:
    package: str
    version: str
    id: str                                  # the advisory ID (PYSEC-/CVE-/GHSA-/OSV-...)
    fix_versions: list[str] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)

    def all_ids(self) -> set[str]:
        """The advisory ID plus every alias -- so a waiver keyed on any of them matches."""
        return {self.id, *self.aliases}


@dataclass(frozen=True)
class ScanReport:
    components: list[Component]
    findings: list[Finding]
    source: str = ""
    ran: bool = False                        # True only after a live scanner invocation

    @property
    def n_packages(self) -> int:
        return len(self.components)

    @property
    def n_findings(self) -> int:
        return len(self.findings)


# --- parsing REAL pip-audit --format json output ------------------------------------------------

def parse_pip_audit(doc: dict, *, source: str = "", ran: bool = False) -> ScanReport:
    """Parse a `pip-audit --format json` document into a typed ScanReport.

    pip-audit emits `{"dependencies": [{"name","version","vulns": [{"id","fix_versions","aliases",
    ...}]}], "fixes": [...]}`. Every component + finding here comes verbatim from that real output --
    nothing is invented; a dependency with an empty `vulns` list yields no findings.
    """
    components: list[Component] = []
    findings: list[Finding] = []
    for dep in doc.get("dependencies", []) or []:
        name = str(dep.get("name", "")).strip()
        version = str(dep.get("version", "")).strip()
        if not name:
            continue
        components.append(Component(name=name, version=version))
        for v in dep.get("vulns", []) or []:
            vid = str(v.get("id", "")).strip()
            if not vid:
                continue
            findings.append(Finding(
                package=name, version=version, id=vid,
                fix_versions=[str(f) for f in (v.get("fix_versions") or [])],
                aliases=[str(a) for a in (v.get("aliases") or [])],
            ))
    return ScanReport(components=components, findings=findings, source=source, ran=ran)


# --- the gate -----------------------------------------------------------------------------------

def gate(report: ScanReport, *, ignore_ids: set[str] | None = None) -> int:
    """Return the CI exit code for a scan report.

    A finding blocks release unless every one of its IDs/aliases is in ``ignore_ids`` (a documented,
    tracked waiver of an accepted-risk advisory). Any remaining finding refuses (exit 2); a clean or
    fully-waived report passes (exit 0). pip-audit does not rank severity in its default JSON, so the
    threshold here is presence-of-advisory: any un-waived known vulnerability blocks.
    """
    ignore = set(ignore_ids or ())
    live = [f for f in report.findings if not (f.all_ids() & ignore)]
    return 2 if live else 0


# --- the live scan (soft-gated) -----------------------------------------------------------------

def scanner_available() -> bool:
    """True only if pip-audit is on PATH AND can actually execute here.

    `shutil.which` finding the console script is NOT enough: its shebang may point at an interpreter
    that cannot import `pip_audit` (e.g. under PYTHONNOUSERSITE the user-site install is hidden). The
    soft gate must reflect whether the scanner can really RUN, so we invoke `pip-audit --version`.
    """
    exe = shutil.which("pip-audit")
    if exe is None:
        return False
    try:
        proc = subprocess.run([exe, "--version"], capture_output=True, text=True,
                              timeout=30.0, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def run_scan(lock_path: str, *, require_hashes: bool = True,
             timeout_s: float = 300.0) -> ScanReport | None:
    """Invoke pip-audit over the resolved lock and parse its REAL JSON output.

    Returns a ScanReport with ``ran=True`` on a successful invocation (whether or not findings exist),
    or ``None`` when the scanner is unavailable / cannot reach a vuln DB (a soft-gated SKIP -- never a
    fabricated clean result). A non-zero pip-audit exit is EXPECTED when vulns are found (exit 1); that
    is a real result, not an error, so it is parsed rather than treated as a failure.
    """
    exe = shutil.which("pip-audit")
    if exe is None:
        return None
    cmd = [exe, "-r", lock_path, "--format", "json", "--progress-spinner", "off"]
    if require_hashes:
        cmd.append("--require-hashes")
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    out = proc.stdout.strip()
    if not out:
        # no JSON on stdout -> the scan could not run (e.g. no network to the OSV/PyPI DB); SKIP, do
        # not claim clean. pip-audit's diagnostic is on stderr.
        return None
    try:
        doc = json.loads(out)
    except json.JSONDecodeError:
        return None
    return parse_pip_audit(doc, source=lock_path, ran=True)


# --- CLI ----------------------------------------------------------------------------------------

def _report_from_args(args) -> tuple[ScanReport | None, bool]:
    """Resolve the report to gate: a pre-captured --report file, or a live --lock scan.
    Returns (report, skipped)."""
    if args.report:
        with open(args.report, encoding="utf-8") as fh:
            return parse_pip_audit(json.load(fh), source=args.report), False
    report = run_scan(args.lock, require_hashes=not args.no_require_hashes)
    return report, report is None


def _fmt(report: ScanReport, ignore_ids: set[str]) -> str:
    live = [f for f in report.findings if not (f.all_ids() & ignore_ids)]
    waived = [f for f in report.findings if f.all_ids() & ignore_ids]
    out = ["STEWIE PO-05 resolved-artifact CVE scan", ""]
    out.append(f"  source:     {report.source or '<captured report>'}")
    out.append(f"  scanned:    {report.n_packages} resolved packages")
    out.append(f"  findings:   {report.n_findings} ({len(live)} blocking, {len(waived)} waived)")
    for f in live:
        fix = f", fix -> {', '.join(f.fix_versions)}" if f.fix_versions else " (no fix available)"
        out.append(f"    BLOCK  {f.package}=={f.version}  {f.id}{fix}")
    for f in waived:
        out.append(f"    waived {f.package}=={f.version}  {f.id}")
    out.append("")
    out.append("  result:     " + ("REFUSED (findings at/above threshold)" if live else "clean"))
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="scan resolved dependency artifacts for known CVEs (PO-05)")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--lock", help="path to a requirements-*.lock to scan live with pip-audit")
    src.add_argument("--report", help="path to a pre-captured pip-audit --format json report to gate")
    ap.add_argument("--ignore-vuln", action="append", default=[], dest="ignore",
                    help="a tracked, accepted-risk advisory ID to waive (repeatable)")
    ap.add_argument("--no-require-hashes", action="store_true",
                    help="do not pass --require-hashes to pip-audit (for a non-hashed lock)")
    args = ap.parse_args(argv)

    report, skipped = _report_from_args(args)
    if skipped or report is None:
        print("PO-05 scan SKIPPED: pip-audit unavailable or could not reach a vulnerability DB "
              "(soft-gated: needs the scanner + network). NOT reported as clean.", file=sys.stderr)
        return 3
    ignore_ids = set(args.ignore)
    print(_fmt(report, ignore_ids))
    return gate(report, ignore_ids=ignore_ids)


if __name__ == "__main__":
    sys.exit(main())
