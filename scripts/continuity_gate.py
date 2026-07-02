"""[REQ:MT-05] the continuity-governance release gate REPORT.

One command surfaces the four maintainability metrics the bloat audit said should never drift silently,
so they are visible every release: (1) the total tracked-payload size, (2) the large-file diff (the
oversized tracked binaries + any policy violations, via MT-01), (3) the HTML-sink count in the served
frontend (the large-blast-radius surface MT-03 hardens), and (4) the CI test-tier status (which tiers are
declared). The gate REDS on a new large tracked binary (delegating the concrete guard to MT-01's
check_tracked_artifacts). The ADR-per-boundary set + the generated-artifact manifest the row also calls
for are the remaining governance follow-ons; this is the metric report + the large-file red.
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


def continuity_report() -> dict:
    """Assemble the four continuity metrics into one report (the release-gate artifact)."""
    art = ARTIFACTS.scan()
    return {
        "tracked_payload_mb": round(art["total_bytes"] / 1048576, 1),
        "oversized_count": len(art["oversized"]),
        "large_file_violations": [p for p, _ in art["violations"]],
        "html_sink_count": html_sink_count(),
        "test_tiers": ci_test_tiers(),
    }


def main() -> int:
    r = continuity_report()
    print("STEWIE continuity-governance report")
    print(f"  tracked payload      : {r['tracked_payload_mb']} MB")
    print(f"  oversized binaries   : {r['oversized_count']} (all allowlisted unless flagged below)")
    print(f"  HTML-injection sinks : {r['html_sink_count']} (MT-03 hardens these)")
    print(f"  CI test tiers        : {', '.join(r['test_tiers'])}")
    if r["large_file_violations"]:
        print("\nREDS: new large tracked binary (MT-01):")
        for p in r["large_file_violations"]:
            print(f"  {p}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
