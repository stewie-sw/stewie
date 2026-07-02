"""[REQ:SE-01] Full release security-audit gate acceptance.

SE-01 requires that a release only ships once eight audit domains -- host, container, app,
DNS/site, secret, backup/restore, dependency/SBOM/CVE, and external-surface -- each carry a real
status, and every finding is tracked to closure. These tests enforce, mechanically, the two rules
the row states in prose:

  * the release gate REFUSES while any required domain is missing, or any non-gated domain holds an
    open finding / is not run (verification never leads a real fix);
  * the genuinely infra-gated legs (host, DNS, backup/restore, external-surface) stay NAMED with a
    reason, so the gate can never silently mark them complete.

The manifest asserted here is the REAL current audit state: the container/app/dependency-SBOM slices
have citing tests + tooling that pass, the CVE scan of resolved artifacts is not wired, and the
OPS-02 secret-hygiene finding on the deploy host is still open. So the gate honestly refuses release
today; the small in-memory manifests only exercise the decision function's pass/refuse branches (the
same fixture pattern scripts/test_check_deps_lock.py uses for its clean/drift branches).
"""
from scripts.security_audit import (
    FINDING_OPEN,
    GATED,
    NOT_RUN,
    PASS,
    REQUIRED_DOMAINS,
    SE01_AUDIT_DOMAINS,
    main,
    security_audit_report,
)

# The four legs that need live-host / DNS / second-host / live-site access and cannot be audited
# from a repo checkout. Named here so a test fails if any is ever silently dropped.
_INFRA_GATED = {"host", "dns_site", "backup_restore", "external_surface"}


def _all_pass_manifest():
    """A hypothetical fully-cleared manifest: the auditable domains PASS, the infra legs GATED with a
    named reason. Used ONLY to exercise the releasable branch -- it is not a claim about today's state.
    """
    m = {}
    for d in REQUIRED_DOMAINS:
        if d in _INFRA_GATED:
            m[d] = {"status": GATED, "evidence": f"{d} audit", "findings": [],
                    "gated_reason": f"{d} needs live infra access"}
        else:
            m[d] = {"status": PASS, "evidence": f"{d} audit passed", "findings": []}
    return m


def test_real_manifest_lists_all_eight_domains_with_typed_entries():
    # the audit manifest (typed) must cover exactly the eight SE-01 domains, each with a status +
    # findings list (the two required fields the gate reasons over).
    assert set(SE01_AUDIT_DOMAINS) == set(REQUIRED_DOMAINS)
    assert len(REQUIRED_DOMAINS) == 8
    for name, entry in SE01_AUDIT_DOMAINS.items():
        assert entry["status"] in {PASS, FINDING_OPEN, GATED, NOT_RUN}, name
        assert isinstance(entry.get("findings", []), list), name
        if entry["status"] == GATED:
            assert entry.get("gated_reason"), f"{name} is GATED but names no reason"


def test_real_gate_refuses_release_today_for_real_open_findings():
    # honest current state: the CVE-scan leg is now wired + tested (scripts/scan_artifacts.py), so the
    # dependency domain no longer blocks -- but the OPS-02 secret finding on the deploy host is still
    # open (live-host-gated, not closeable from a checkout), so the release gate REFUSES. This is the
    # non-vacuous core assertion.
    rep = security_audit_report()
    assert rep["releasable"] is False
    assert "secret" in rep["blocking"]
    # the CVE leg is closed -> it must NOT be among the blockers anymore
    assert "dependency_sbom_cve" not in rep["blocking"]
    # the refusal must surface the actual finding, not an opaque boolean
    joined = " ".join(rep["open_findings"]).lower()
    assert "ops-02" in joined
    assert main() == 1  # the CLI exit code refuses release too


def test_infra_gated_legs_stay_named_and_do_not_block():
    # the four infra legs are GATED with a reason and are excluded from the release-block decision,
    # but can never be silently completed (a reason is mandatory).
    rep = security_audit_report()
    assert set(rep["gated"]) == _INFRA_GATED
    for leg in _INFRA_GATED:
        assert leg not in rep["blocking"], f"{leg} is infra-gated and must not block release"
        assert SE01_AUDIT_DOMAINS[leg]["gated_reason"]


def test_gate_passes_only_when_every_non_gated_domain_is_pass():
    rep = security_audit_report(_all_pass_manifest())
    assert rep["releasable"] is True
    assert rep["blocking"] == []
    assert rep["missing"] == []
    assert set(rep["gated"]) == _INFRA_GATED


def test_open_finding_in_a_non_gated_domain_refuses_release():
    m = _all_pass_manifest()
    m["app"] = {"status": FINDING_OPEN, "evidence": "app audit",
                "findings": ["reflected XSS on /plan echo"]}
    rep = security_audit_report(m)
    assert rep["releasable"] is False
    assert "app" in rep["blocking"]


def test_cve_scan_not_run_refuses_release():
    # a dependency domain whose CVE leg has not run must refuse -- an SBOM alone is not the domain.
    m = _all_pass_manifest()
    m["dependency_sbom_cve"] = {"status": NOT_RUN,
                                "evidence": "SBOM built; CVE scan of resolved artifacts not run",
                                "findings": []}
    rep = security_audit_report(m)
    assert rep["releasable"] is False
    assert "dependency_sbom_cve" in rep["blocking"]


def test_missing_required_domain_refuses_release():
    m = _all_pass_manifest()
    del m["container"]
    rep = security_audit_report(m)
    assert rep["releasable"] is False
    assert "container" in rep["missing"]


def test_a_gated_domain_without_a_reason_cannot_silently_complete():
    # marking a domain GATED with no reason is an attempt to hide it -> the manifest is not releasable.
    m = _all_pass_manifest()
    m["host"] = {"status": GATED, "evidence": "host", "findings": []}  # no gated_reason
    rep = security_audit_report(m)
    assert "host" in rep["invalid_gated_no_reason"]
    assert rep["releasable"] is False


def test_dependency_sbom_cve_domain_is_backed_by_a_real_wired_cve_scan():
    # SE-01's dependency/SBOM/CVE domain is only PASS because the "scan resolved artifacts for known
    # CVEs" step is a REAL, wired, tested mechanism -- not a claim. Prove it non-vacuously against the
    # actual scanner (scripts/scan_artifacts.py) over its REAL captured pip-audit fixtures: the gate
    # REFUSES on the genuinely-vulnerable jinja2 2.11.2 capture (real CVE IDs) and passes on the clean
    # capture. If that gate did not really refuse on real findings, the domain has no business PASSing.
    import json
    import os

    from scripts import scan_artifacts

    fix = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "scripts", "fixtures", "pip_audit")
    with open(os.path.join(fix, "vulnerable_report.json"), encoding="utf-8") as fh:
        vuln = scan_artifacts.parse_pip_audit(json.load(fh))
    with open(os.path.join(fix, "clean_report.json"), encoding="utf-8") as fh:
        clean = scan_artifacts.parse_pip_audit(json.load(fh))
    # the scan of resolved artifacts is real: it finds real advisories and its gate refuses on them
    assert vuln.n_findings >= 1
    assert any(f.id.startswith(("PYSEC-", "CVE-", "GHSA-")) for f in vuln.findings)
    assert scan_artifacts.gate(vuln) != 0, "the wired CVE gate must refuse on real findings"
    assert scan_artifacts.gate(clean) == 0, "the wired CVE gate must pass a clean scan"

    # the SE-01 manifest reflects that this mechanism is wired: the dependency domain PASSes with no
    # open finding, and its evidence cites the real scanner (no stale 'cve_scan_not_run' finding).
    dep = SE01_AUDIT_DOMAINS["dependency_sbom_cve"]
    assert dep["status"] == PASS, dep["status"]
    assert dep["findings"] == []
    assert "scan_artifacts" in dep["evidence"]
    rep = security_audit_report()
    assert "dependency_sbom_cve" not in rep["blocking"]
