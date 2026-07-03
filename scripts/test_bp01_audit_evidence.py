"""[REQ:BP-01] the SE-01 release security-audit EVIDENCE gate: a DATED
`docs/security/se-01/<date>/manifest.json` carries ONE evidence record per required domain, each with a
status + evidence (a non-gated domain is PASS with no open finding; a gated leg names its reason), and the
committed evidence MATCHES the live audit state so it cannot silently drift. This is the artifact that
closes SE-01."""
import glob
import json
import os

from scripts.security_audit import (
    REQUIRED_DOMAINS,
    SE01_AUDIT_DOMAINS,
    security_audit_report,
)

_SEC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "security", "se-01")


def _latest_manifest() -> str | None:
    ms = sorted(glob.glob(os.path.join(_SEC, "*", "manifest.json")))
    return ms[-1] if ms else None


def test_a_dated_evidence_manifest_exists_with_one_typed_record_per_domain():  # [REQ:BP-01]
    p = _latest_manifest()
    assert p, "no dated docs/security/se-01/<date>/manifest.json evidence artifact"
    assert os.path.basename(os.path.dirname(p)).count("-") == 2, "the manifest directory must be dated YYYY-MM-DD"
    m = json.load(open(p, encoding="utf-8"))
    # exactly the eight required SE-01 domains, each a typed record.
    assert set(m["domains"]) == set(REQUIRED_DOMAINS)
    for d, rec in m["domains"].items():
        assert rec.get("status") and "evidence" in rec, f"{d}: record needs a status + evidence"
        if rec["status"] == "GATED":
            assert rec.get("gated_reason"), f"{d}: a gated leg must name its reason"
        else:
            assert rec["status"] == "PASS" and not rec.get("findings"), f"{d}: non-gated must be PASS, no open finding"


def test_evidence_manifest_matches_the_live_audit_state_no_drift():  # [REQ:BP-01]
    p = _latest_manifest()
    m = json.load(open(p, encoding="utf-8"))
    rep = security_audit_report()
    # the evidence cannot claim releasable while the live gate refuses, nor misreport any domain's status.
    assert m["releasable"] == rep["releasable"]
    for d in REQUIRED_DOMAINS:
        assert m["domains"][d]["status"] == SE01_AUDIT_DOMAINS[d]["status"], f"{d}: manifest drifted from the audit"
