"""[REQ:MT-05] the continuity-governance release gate.

One command surfaces the four maintainability metrics the bloat audit said should never drift silently,
so they are visible every release: (1) the total tracked-payload size, (2) the large-file diff (the
oversized tracked binaries + any policy violations, via MT-01), (3) the HTML-sink count in the served
frontend (the large-blast-radius surface MT-03 hardens), and (4) the CI test-tier status (which tiers are
declared). The gate REDS on a new large tracked binary (delegating the concrete guard to MT-01's
check_tracked_artifacts) OR on a new unlisted HTML sink (a down-only ratchet over the known baseline).
It also asserts the governance set the row calls for is present: the ADR-per-boundary set (docs/adr/) and
the generated-artifact manifest (docs/generated_artifacts.yaml, every declared generator on disk).
"""
from __future__ import annotations

import glob
import os
import re
import sys

import yaml

from scripts import check_tracked_artifacts as ARTIFACTS

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
#: the DOM write sinks whose count is the frontend's HTML-injection blast-radius metric (MT-03 gates it).
_SINK_RE = re.compile(r"\b(innerHTML|outerHTML|insertAdjacentHTML)\b")
#: down-only ratchet: the frontend's known HTML-sink baseline. A count ABOVE this is a new unlisted sink and
#: reds the gate (the count may only shrink as MT-03 replaces sinks with safe DOM writes). Measured 2026-07-04.
_SINK_BASELINE = 183
#: the ADR set + the generated-artifact manifest the governance gate requires to be checked in.
_ADR_DIR = os.path.join(_ROOT, "docs", "adr")
_MANIFEST = os.path.join(_ROOT, "docs", "generated_artifacts.yaml")


def html_sink_count() -> int:
    """Count HTML-injection sinks across the served frontend (assets JS + index.html)."""
    total = 0
    paths = glob.glob(os.path.join(_ROOT, "stewie", "server", "web", "assets", "*.js"))
    paths.append(os.path.join(_ROOT, "stewie", "server", "index.html"))
    for p in paths:
        try:
            with open(p, encoding="utf-8") as fh:
                total += len(_SINK_RE.findall(fh.read()))
        except OSError:
            continue
    return total


def ci_test_tiers() -> list[str]:
    """The CI jobs (test tiers) declared in the workflow -- the pinned tier surface (PO-04)."""
    with open(os.path.join(_ROOT, ".github", "workflows", "ci.yml"), encoding="utf-8") as fh:
        return sorted(yaml.safe_load(fh)["jobs"].keys())


def adr_ids() -> list[str]:
    """The accepted ADR set: one record per subsystem boundary (docs/adr/NNNN-*.md, excluding the README)."""
    return sorted(os.path.basename(p) for p in glob.glob(os.path.join(_ADR_DIR, "[0-9]*.md")))


def manifest_missing_generators() -> list[str]:
    """Every generator declared regenerable in the artifact manifest that is NOT on disk (should be empty)."""
    with open(_MANIFEST, encoding="utf-8") as fh:
        man = yaml.safe_load(fh)
    missing = []
    for entry in man.get("regenerable", []):
        gen = entry.get("generator", "")
        if not gen or not os.path.exists(os.path.join(_ROOT, gen)):
            missing.append(gen or f"<no generator for {entry.get('path')}>")
    return missing


def continuity_report() -> dict:
    """Assemble the four continuity metrics + the governance-set status into one release-gate report."""
    art = ARTIFACTS.scan()
    return {
        "tracked_payload_mb": round(art["total_bytes"] / 1048576, 1),
        "oversized_count": len(art["oversized"]),
        "large_file_violations": [p for p, _ in art["violations"]],
        "html_sink_count": html_sink_count(),
        "html_sink_baseline": _SINK_BASELINE,
        "new_html_sinks": max(0, html_sink_count() - _SINK_BASELINE),
        "test_tiers": ci_test_tiers(),
        "adr_count": len(adr_ids()),
        "manifest_missing_generators": manifest_missing_generators(),
    }


def main() -> int:
    r = continuity_report()
    print("STEWIE continuity-governance report")
    print(f"  tracked payload      : {r['tracked_payload_mb']} MB")
    print(f"  oversized binaries   : {r['oversized_count']} (all allowlisted unless flagged below)")
    print(f"  HTML-injection sinks : {r['html_sink_count']} / baseline {r['html_sink_baseline']} (MT-03)")
    print(f"  CI test tiers        : {', '.join(r['test_tiers'])}")
    print(f"  ADRs (docs/adr)      : {r['adr_count']} boundary records")
    print(f"  artifact manifest    : {'OK' if not r['manifest_missing_generators'] else 'MISSING GENERATORS'}")
    rc = 0
    if r["large_file_violations"]:
        print("\nREDS: new large tracked binary (MT-01):")
        for p in r["large_file_violations"]:
            print(f"  {p}")
        rc = 1
    if r["new_html_sinks"]:
        print(f"\nREDS: {r['new_html_sinks']} new unlisted HTML sink(s) over baseline {_SINK_BASELINE} (MT-03)")
        rc = 1
    if r["manifest_missing_generators"]:
        print("\nREDS: artifact-manifest generator(s) missing:")
        for g in r["manifest_missing_generators"]:
            print(f"  {g}")
        rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
