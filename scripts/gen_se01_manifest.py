"""[REQ:BP-01] Generate the dated SE-01 release security-audit EVIDENCE manifest: ONE record per required
domain, projected from the live scripts/security_audit.py state. The dated
`docs/security/se-01/<date>/manifest.json` is the release evidence artifact that closes SE-01 -- a durable,
dated snapshot of each domain's status + evidence (a non-gated domain is PASS with no open finding; a gated
leg names why it cannot be audited from a checkout). Regenerate: `python scripts/gen_se01_manifest.py <date>`.
"""
from __future__ import annotations

import json
import os
import sys

from scripts.security_audit import (
    REQUIRED_DOMAINS,
    SE01_AUDIT_DOMAINS,
    security_audit_report,
)

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def build_manifest(date: str) -> dict:
    """The evidence manifest -- one record per required domain + the release verdict, from the live audit."""
    rep = security_audit_report()
    return {
        "audit_date": date,
        "releasable": rep["releasable"],
        "blocking": rep["blocking"],
        "domains": {
            d: {
                "status": SE01_AUDIT_DOMAINS[d]["status"],
                "evidence": SE01_AUDIT_DOMAINS[d].get("evidence", ""),
                "findings": list(SE01_AUDIT_DOMAINS[d].get("findings", [])),
                "gated_reason": SE01_AUDIT_DOMAINS[d].get("gated_reason", ""),
            }
            for d in REQUIRED_DOMAINS
        },
    }


def main(argv=None) -> int:
    a = argv if argv is not None else sys.argv[1:]
    date = a[0] if a else "0000-00-00"
    out_dir = os.path.join(_ROOT, "docs", "security", "se-01", date)
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "manifest.json")
    m = build_manifest(date)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(m, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(f"wrote {path}: {len(m['domains'])} domains, releasable={m['releasable']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
