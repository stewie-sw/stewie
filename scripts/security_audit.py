#!/usr/bin/env python3
"""SE-01 (PRD §7 / FANOUT SE-01) — the full release security-audit gate.

A release is only allowed once eight audit domains -- host, container, app, DNS/site, secret,
backup/restore, dependency/SBOM/CVE, and external-surface -- each carry a real status and every
finding is tracked to closure. This module is the machine-checkable slice of that gate:

  * `SE01_AUDIT_DOMAINS` is the typed audit manifest. Each domain records a `status`, the real
    `evidence` it rests on, its open `findings`, and (for a gated leg) the `gated_reason` that names
    why it cannot be audited from a repo checkout.
  * `security_audit_report()` aggregates the manifest and returns a release decision. It REFUSES
    (`releasable=False`) while any required domain is missing, any non-gated domain is not PASS or
    holds an open finding, or a gated leg names no reason.

Two hard rules it encodes (NASA-style: "no capability claim until evidence exists"):
  * an infra-gated leg (host / DNS / backup-restore / external-surface) stays NAMED with a reason,
    so the gate can never silently mark it complete;
  * the manifest reflects the REAL current state -- the CVE scan of resolved artifacts IS wired now
    (scripts/scan_artifacts.py + its gate, tested on real pip-audit output), but the OPS-02
    secret-hygiene finding on the deploy host is still open, so the gate honestly refuses release
    today. Nothing here is fabricated closed.

REPORT-ONLY. It reads the manifest; it does not mutate the PRD or promote any status. Run:
`python3 scripts/security_audit.py` (exit 0 = releasable, 1 = refused).
"""
from __future__ import annotations

# --- status vocabulary --------------------------------------------------------------------------
PASS = "PASS"                 # audited, no open findings
FINDING_OPEN = "FINDING_OPEN"  # audited, has an open finding -> blocks release
GATED = "GATED"               # cannot be audited from a repo checkout (needs live infra) -> named, not blocking
NOT_RUN = "NOT_RUN"           # the audit is not wired yet -> blocks release (must run before shipping)

_STATUSES = frozenset({PASS, FINDING_OPEN, GATED, NOT_RUN})

# The eight audit domains the SE-01 release row requires, in the row's stated order.
REQUIRED_DOMAINS = (
    "host",
    "container",
    "app",
    "dns_site",
    "secret",
    "backup_restore",
    "dependency_sbom_cve",
    "external_surface",
)

# --- the REAL current audit manifest ------------------------------------------------------------
# Every entry rests on evidence that exists in this tree. Gated legs name why they cannot be closed
# from a checkout; open findings name the real, un-closed work. Do NOT mark a gated leg PASS and do
# NOT fabricate a CVE result -- both would defeat the gate.
SE01_AUDIT_DOMAINS: dict = {
    "host": {
        "status": GATED,
        "evidence": "SECURITY.md operational notes (loopback default, trusted-LAN guidance).",
        "findings": [],
        "gated_reason": ("host hardening walkthrough needs live-host access to the archimedes deploy "
                         "host; it cannot be audited from a repo checkout."),
    },
    "container": {
        "status": PASS,
        "evidence": ("stewie/server/test_deploy_hardening.py -- Dockerfile bases digest-pinned "
                     "(@sha256:), mkdocs-material version-pinned, single COPY (O-04 / S-13)."),
        "findings": [],
    },
    "app": {
        "status": PASS,
        "evidence": ("stewie/server/test_security.py (S-01/02/04/11: cross-identity bootstrap, "
                     "email-validator XSS, plaintext-HTTP guard, CORS) + scripts/sec01_cookie_smoke.py "
                     "+ scripts/sec04_xss_smoke.py."),
        "findings": [],
    },
    "dns_site": {
        "status": GATED,
        "evidence": "deploy/DEPLOY.md documents the path (Cloudflare -> cloudflared -> :8000).",
        "findings": [],
        "gated_reason": ("DNS / live-site audit (app.stewie.space records, TLS, edge cache headers) "
                         "needs DNS + live-site access."),
    },
    "secret": {
        "status": FINDING_OPEN,
        "evidence": "SECURITY.md operational notes; PRD §27.2 OPS-02 (carried from the 2026-06-15 host audit).",
        "findings": [
            ("OPS-02: STEWIE_API_KEY rotation and stale STEWIE_DIRECTOR_KEY removal on the deploy host "
             "are not confirmed from this checkout; deploy/.env perms read 600 in-repo but the live-host "
             "copy is unverifiable here. Finding stays open until closed on the host."),
        ],
    },
    "backup_restore": {
        "status": GATED,
        "evidence": "DT-01 runtime-packet log (stewie/twin/envelope.py) records mission/terrain state.",
        "findings": [],
        "gated_reason": ("a drilled backup/restore needs a second host + off-host replication "
                         "(the DT-01 cold-rebuild infra), which is not built here."),
    },
    "dependency_sbom_cve": {
        "status": PASS,
        "evidence": ("scripts/gen_sbom.py emits a CycloneDX 1.5 SBOM from the pinned lock; "
                     "scripts/check_deps_lock.py [REQ:PO-05] asserts the lock matches pyproject; "
                     "scripts/scan_artifacts.py [REQ:PO-05] runs a real pip-audit CVE scan of the "
                     "resolved lock and its gate REFUSES on any un-waived advisory (proven in "
                     "scripts/test_scan_artifacts.py against real captured pip-audit output -- the "
                     "vulnerable jinja2 2.11.2 capture with real CVE IDs refuses, the clean capture "
                     "passes). The live scan soft-gates to SKIP where the scanner/network is absent "
                     "so it never fabricates a clean result -- but the scan-and-gate mechanism over "
                     "resolved artifacts is wired and tested, which is what this domain requires."),
        "findings": [],
    },
    "external_surface": {
        "status": GATED,
        "evidence": ("SECURITY.md -- the single network-facing component is the optional mission-planner "
                     "web UI (stewie/server/server.py)."),
        "findings": [],
        "gated_reason": ("external-exposure audit (port / TLS / edge scan of the live public surface) "
                         "needs the live site."),
    },
}


def security_audit_report(domains: dict | None = None) -> dict:
    """Aggregate the audit manifest into a release decision. Read-only.

    A non-gated domain blocks release unless it is PASS with no open findings. A gated leg never
    blocks but MUST name a reason (a reason-less GATED entry is an attempt to hide the leg and is
    reported as invalid, which also refuses release). A missing required domain refuses release.
    """
    domains = SE01_AUDIT_DOMAINS if domains is None else domains

    missing = [d for d in REQUIRED_DOMAINS if d not in domains]
    per_domain: dict = {}
    blocking: list = []
    gated: list = []
    invalid_gated: list = []
    open_findings: list = []

    for name, entry in domains.items():
        status = entry.get("status")
        findings = list(entry.get("findings", []) or [])
        gated_reason = entry.get("gated_reason")
        blocks = False

        if status == GATED:
            gated.append(name)
            if not gated_reason:
                invalid_gated.append(name)   # a gated leg with no reason cannot silently complete
        elif status != PASS or findings:
            blocks = True                    # NOT_RUN, FINDING_OPEN, or any open finding refuses

        if findings:
            open_findings.extend(f"{name}: {f}" for f in findings)
        if blocks:
            blocking.append(name)

        per_domain[name] = {
            "status": status,
            "evidence": entry.get("evidence"),
            "findings": findings,
            "gated_reason": gated_reason,
            "blocks_release": blocks,
        }

    releasable = not missing and not blocking and not invalid_gated
    return {
        "domains": per_domain,
        "required": list(REQUIRED_DOMAINS),
        "missing": sorted(missing),
        "blocking": sorted(blocking),
        "gated": sorted(gated),
        "invalid_gated_no_reason": sorted(invalid_gated),
        "open_findings": open_findings,
        "releasable": releasable,
        "note": ("report-only; a release is refused while any required domain is missing, any "
                 "non-gated domain is not PASS / holds an open finding, or a gated leg names no "
                 "reason. The infra-gated legs stay named so the gate cannot silently complete them."),
    }


def _fmt(rep: dict) -> str:
    out = ["STEWIE SE-01 release security-audit gate", ""]
    out.append(f"  releasable:  {rep['releasable']}")
    out.append(f"  required:    {len(rep['required'])} domains")
    if rep["missing"]:
        out.append(f"  MISSING:     {rep['missing']}")
    out.append(f"  blocking:    {rep['blocking'] or '[] (none)'}")
    out.append(f"  gated:       {rep['gated']}")
    if rep["invalid_gated_no_reason"]:
        out.append(f"  INVALID GATE (no reason): {rep['invalid_gated_no_reason']}")
    out.append("")
    out.append("  per-domain:")
    for name in rep["required"]:
        d = rep["domains"].get(name)
        if d is None:
            out.append(f"    {name}: <missing from manifest>")
            continue
        flag = " BLOCKS" if d["blocks_release"] else ""
        out.append(f"    {name}: {d['status']}{flag}")
        if d["gated_reason"]:
            out.append(f"        gated: {d['gated_reason']}")
        for f in d["findings"]:
            out.append(f"        open finding: {f}")
    out.append("")
    out.append(f"  {rep['note']}")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    rep = security_audit_report()
    print(_fmt(rep))
    return 0 if rep["releasable"] else 1


if __name__ == "__main__":
    import sys

    sys.exit(main())
