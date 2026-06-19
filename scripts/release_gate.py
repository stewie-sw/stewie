#!/usr/bin/env python3
"""The §25 autonomy-track release gate (AS-01..17).

This is the capstone trace for the full-stack onboard-autonomy execution plan. It maps every AS row
to (a) its live PRD I/X/V/Q status, (b) the tests that cite it with a `[REQ:AS-NN]` marker, and
(c) the tier where its execution + verification evidence actually lives -- so a reader can tell a
host-verified slice from a container-gated one from a still-deferred capability WITHOUT trusting a
narrative.

Two hard rules it encodes (NASA-style: "no capability claim until evidence exists"):
  * a row may only be eligible for V=D if a test cites it AND its verification runs on the host;
  * the genuinely-deferred capabilities are named here, so the gate can never silently "complete" them.

REPORT-ONLY. It reads the PRD; it does NOT promote any V column. Advancing a row to V=D edits the
committee scorecard and stays a human decision. Run: `python3 scripts/release_gate.py`.
"""
from __future__ import annotations

from scripts.req_trace import parse_requirements, scan_markers

AS_ROWS = [f"AS-{n:02d}" for n in range(1, 18)]
_PATHS = ["stewie", "dart", "lode", "scripts", "ros2_ws"]

# WHERE each row's execution + verification evidence lives:
#   host      -- pure-Python autonomy logic; host `pytest` IS the execution + verification.
#   container -- the host test is a static-artifact / contract gate; the live execution (colcon build,
#                check_urdf, rviz2 / gz-sim launch) is container-gated under deploy/ros2/Dockerfile.*
#                and needs a ROS2 Jazzy daemon. The host gate is necessary, not sufficient, for X.
TIER = {
    "AS-01": "host", "AS-07": "host", "AS-08": "host", "AS-09": "host", "AS-10": "host",
    "AS-11": "host", "AS-12": "host", "AS-13": "host", "AS-14": "host", "AS-15": "host",
    "AS-16": "host", "AS-17": "host",
    "AS-02": "container", "AS-03": "container", "AS-04": "container",
    "AS-05": "container", "AS-06": "container",
}

# Capabilities the PRD HONESTLY defers. Named so the release gate cannot mark the track "done" while
# any of these remain stubs / gated. Each maps to the PRD row that tracks it.
DEFERRED = {
    "live_chrono_producer":
        "PRD P7: the live PyChrono force producer is a stub (single rigid cylinder); needs a PyChrono host.",
    "apriltag_12p7mm":
        "AprilTag 12.7 mm pose re-confirm is container-gated (apriltag_ros runs in the ROS2 image).",
    "dense_mvs_rmse":
        "dense MVS / COLMAP observed-map RMSE is CUDA-gated; conserved-truth map coverage is the shipped tier.",
    "space_ros_profile":
        "AS-04 Space ROS migration container tier not built (3 of the 6 named tiers ship: base/rviz/gazebo).",
    "perception_bridge_tiers":
        "AS-04 perception/SLAM + bridge-runtime container tiers not built.",
}


def _recommend(tier: str, i: str, v: str, cited: bool) -> str:
    if not cited:
        return "BLOCKED: no citing test -- cannot claim V=D under the traceability rule."
    if tier == "host":
        if v == "D":
            return "V=D held: host verification present and cited."
        if i == "D":
            return f"eligible for V={v}->D: implementation done, host pytest is the verification, cited."
        return (f"V tracks the partial slice (I={i}); V=D waits on I=D -- verification cannot lead "
                "implementation. Host tests cover what is built.")
    # container tier
    return (f"V stays {v} (host static/contract gate passes); X is gated on the docker build + smoke "
            "(deploy/ros2/Dockerfile.*), so V=D waits on a recorded container run.")


def release_report() -> dict:
    """Build the AS-01..17 release-gate report from the live PRD + the test-marker scan. Read-only."""
    reqs = parse_requirements("PRD.md")
    marks = scan_markers(_PATHS)

    rows: dict = {}
    for r in AS_ROWS:
        d = reqs.get(r, {})
        cites = sorted(marks.get(r, []))
        tier = TIER[r]
        v, i = d.get("V", "?"), d.get("I", "?")
        # V=D eligibility: host-tier, cited, AND implementation done -- verification never leads I.
        eligible = bool(cites) and tier == "host" and i == "D"
        rows[r] = {
            "pri": d.get("pri"), "I": i, "X": d.get("X"), "V": v, "Q": d.get("Q"),
            "tier": tier,
            "citing_tests": cites,
            "cited": bool(cites),
            "eligible_for_v_done": eligible,
            "recommendation": _recommend(tier, i, v, bool(cites)),
        }

    in_matrix = [r for r in AS_ROWS if r in reqs]
    summary = {
        "total": len(AS_ROWS),
        "in_matrix": len(in_matrix),
        "cited": sum(1 for r in rows.values() if r["cited"]),
        "uncited": sorted(r for r, x in rows.items() if not x["cited"]),
        "host_verified": sorted(r for r, x in rows.items() if x["tier"] == "host"),
        "container_gated": sorted(r for r, x in rows.items() if x["tier"] == "container"),
        "eligible_for_v_done": sorted(r for r, x in rows.items() if x["eligible_for_v_done"]),
        "currently_v_done": sorted(r for r, x in rows.items() if x["V"] == "D"),
    }
    return {
        "rows": rows,
        "summary": summary,
        "deferred": dict(DEFERRED),
        "note": ("report-only; the V column is NOT promoted here. Advancing a row to V=D edits the "
                 "committee scorecard and is a human decision. The deferred set must stay non-empty "
                 "until each named capability is implemented + executed + verified."),
    }


def _fmt(rep: dict) -> str:
    s = rep["summary"]
    out = ["STEWIE §25 autonomy-track release gate (AS-01..17)", ""]
    out.append(f"  in matrix:        {s['in_matrix']}/{s['total']}")
    out.append(f"  cited by a test:  {s['cited']}/{s['total']}"
               + (f"   UNCITED: {s['uncited']}" if s["uncited"] else "   (all cited)"))
    out.append(f"  host-verified:    {len(s['host_verified'])}  {s['host_verified']}")
    out.append(f"  container-gated:  {len(s['container_gated'])}  {s['container_gated']}")
    out.append(f"  eligible V=D:     {s['eligible_for_v_done']}")
    out.append(f"  currently V=D:    {s['currently_v_done'] or '[] (none promoted yet)'}")
    out.append("")
    out.append("  per-row:")
    for r in AS_ROWS:
        x = rep["rows"][r]
        out.append(f"    {r} [{x['pri']}] I={x['I']} X={x['X']} V={x['V']} Q={x['Q']}  "
                   f"({x['tier']}, {len(x['citing_tests'])} test refs)")
        out.append(f"        -> {x['recommendation']}")
    out.append("")
    out.append("  STILL DEFERRED (named so the gate cannot silently complete them):")
    for k, why in rep["deferred"].items():
        out.append(f"    - {k}: {why}")
    out.append("")
    out.append(f"  {rep['note']}")
    return "\n".join(out)


def main(argv=None) -> int:
    rep = release_report()
    print(_fmt(rep))
    # the gate FAILS only on a real violation: an AS row with no citing test, or a V=D row uncited.
    s = rep["summary"]
    bad_v_done = [r for r in s["currently_v_done"] if not rep["rows"][r]["cited"]]
    if s["uncited"]:
        print(f"\nVIOLATION -- AS rows with no citing test: {s['uncited']}")
        return 1
    if bad_v_done:
        print(f"\nVIOLATION -- V=D without a citing test: {bad_v_done}")
        return 1
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
