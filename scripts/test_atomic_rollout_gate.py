"""FS-14 [REQ:FS-14]: the atomic rollout rule is machine-checked end-to-end.

The rule -- no row is marked complete (V=D) while any of its gates fail, and partial work stays
explicitly labeled partial in the matrix -- is enforced by three mechanisms that must BIND together:

  1. the citation gate (scripts/req_trace.py): V=D requires a citing [REQ:] test, CI exit 1 otherwise;
  2. the derived status surface (scripts/gen_status.py): STATUS.md/.json come ONLY from the live tools,
     and --check fails (exit 2) when the surface no longer matches the matrix it claims to describe;
  3. the honesty audits (req_trace understated + scripts/release_gate.py): a cited-but-partial row is
     SURFACED as partial (never silently promoted), verification eligibility never leads
     implementation, and the genuinely-gated capabilities stay NAMED in the deferred set.

Each mechanism is proven to bind by tampering a TEMP copy of the real PRD (never the real files) and
watching the gate catch it. Modeled on scripts/test_req_trace.py and scripts/test_gen_status.py.
"""
import os

import pytest

from scripts import gen_status as GS
from scripts.release_gate import release_report
from scripts.req_trace import _ROW, main, parse_requirements, trace

# the same scan roots the CI gates use (the autonomy tests live in ros2_ws too)
PATHS = ["stewie", "dart", "lode", "leap", "forge", "scripts", "ros2_ws", "stewie_qgis"]
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PRD = os.path.join(_REPO_ROOT, "PRD.md")


def _tampered_prd(tmp_path, rid: str, new_v: str) -> str:
    """A temp copy of the real PRD with row `rid`'s V column rewritten to `new_v` (real files untouched)."""
    out, hit = [], False
    for ln in open(_PRD, encoding="utf-8"):
        m = _ROW.match(ln)
        if m and m.group(1) == rid:
            s, e = m.span(6)                       # group 6 is the V column
            ln = ln[:s] + new_v + ln[e:]
            hit = True
        out.append(ln)
    assert hit, f"row {rid} not found in the PRD matrix"
    p = tmp_path / "tampered_prd.md"
    p.write_text("".join(out), encoding="utf-8")
    return str(p)


def _pick_row(cited: bool, v_done: bool) -> str:
    """A real matrix row with the given (cited, V=D) state, computed live so nothing is hardcoded.

    AS rows are excluded: they carry their own §25 release-gate semantics (scripts/release_gate.py),
    and the tamper trials here exercise the general-matrix rule.
    """
    reqs = parse_requirements(_PRD)
    marks = trace(_PRD, PATHS)["markers"]
    for rid in sorted(reqs):
        if rid.startswith("AS-"):
            continue
        if (rid in marks) == cited and (reqs[rid]["V"] == "D") == v_done:
            return rid
    pytest.skip(f"no non-AS row with cited={cited}, V=D={v_done} exists in the live matrix")


def test_rollout_rule_holds_on_the_live_matrix():  # [REQ:FS-14]
    # the live matrix satisfies the atomic rollout rule RIGHT NOW: no row claims V=D without a citing
    # test, no citation is orphaned, and every surfaced partial row genuinely is partial (V != D).
    reqs = parse_requirements(_PRD)
    report = trace(_PRD, PATHS)
    assert report["v_done_uncited"] == []
    assert report["unknown_markers"] == []
    for rid, v in report["understated"]:
        assert rid in report["cited_ids"] and reqs[rid]["V"] == v and v != "D"


def test_completion_gate_refuses_v_done_while_its_gate_fails(tmp_path):  # [REQ:FS-14]
    # tamper trial 1: promote an UNCITED row to V=D in a temp PRD copy -- the citation gate must catch
    # the premature completion claim and fail CI (exit 1). This is the "cannot be marked complete
    # while any of its gates fail" half of the rollout rule, proven to bind rather than asserted.
    rid = _pick_row(cited=False, v_done=False)
    tampered = _tampered_prd(tmp_path, rid, "D")
    assert rid in trace(tampered, PATHS)["v_done_uncited"]
    assert main(["--prd", tampered, "--paths", *PATHS]) == 1


def test_partial_work_stays_labeled_partial(tmp_path):  # [REQ:FS-14]
    # tamper trial 2: demote a cited V=D row to P -- the row must be SURFACED as understated (partial
    # explicitly labeled partial, held for human promotion review), not failed and not silently
    # re-promoted. The status surface derived from the tampered matrix must carry the same label.
    rid = _pick_row(cited=True, v_done=True)
    tampered = _tampered_prd(tmp_path, rid, "P")
    report = trace(tampered, PATHS)
    assert (rid, "P") in report["understated"]
    assert rid not in report["v_done_uncited"]
    assert main(["--prd", tampered, "--paths", *PATHS]) == 0     # surfaced for review, not a violation
    st = GS.collect(tampered, PATHS)
    assert {"id": rid, "v": "P"} in st["v_ne_d_flagged"]         # the derived surface labels it partial


def test_status_surface_derives_from_the_matrix_and_freshness_binds(tmp_path):  # [REQ:FS-14]
    # the generated artifacts are fresh FOR THE PRD THEY CLAIM: a surface written from the real matrix
    # passes --check against it (exit 0), and the SAME surface fails --check (exit 2) against a matrix
    # that has moved -- so a hand edit or a stale regen can never hide a status change.
    md_out, json_out = str(tmp_path / "STATUS.md"), str(tmp_path / "STATUS.json")
    assert GS.main(["--prd", _PRD, "--md-out", md_out, "--json-out", json_out]) == 0
    assert GS.main(["--prd", _PRD, "--md-out", md_out, "--json-out", json_out, "--check"]) == 0
    rid = _pick_row(cited=True, v_done=True)
    tampered = _tampered_prd(tmp_path, rid, "P")
    assert GS.main(["--prd", tampered, "--md-out", md_out, "--json-out", json_out, "--check"]) == 2


def test_verification_never_leads_implementation_and_gated_legs_stay_named():  # [REQ:FS-14]
    # dependency order at the release gate: a row is eligible for V=D only when it is cited AND its
    # implementation is done (verification cannot lead implementation), every currently-V=D row is
    # cited, and the genuinely-gated capabilities stay NAMED so the gate can never silently complete
    # them (live Chrono producer / AprilTag container re-confirm / CUDA dense-MVS).
    rep = release_report()
    for rid, row in rep["rows"].items():
        if row["eligible_for_v_done"]:
            assert row["cited"] and row["I"] == "D", f"{rid}: eligibility must not lead implementation"
    for rid in rep["summary"]["currently_v_done"]:
        assert rep["rows"][rid]["cited"], f"{rid}: V=D held without a citing test"
    for gated in ("live_chrono_producer", "apriltag_12p7mm", "dense_mvs_rmse"):
        assert rep["deferred"].get(gated), f"gated capability {gated} lost its named deferral"
