"""#79 slice: the docking-autonomy state machine (perception-gated transitions)."""
from lode.dock_fsm import DockObs, run, step


def _lit(range_m, err):                                    # a good perception tick
    return DockObs(tag_visible=True, range_m=range_m, pose_error_m=err, illuminated=True)


def test_nominal_sequence_reaches_docked():
    """#79: APPROACH -> ALIGN -> DOCK -> DOCKED under good perception."""
    obs = [_lit(40, 5.0),    # too far -> stay APPROACH
           _lit(20, 5.0),    # in range, tag locked -> ALIGN
           _lit(2, 0.20),    # error <= ALIGN_TOL -> DOCK
           _lit(0.5, 0.03)]  # error <= DOCK_TOL -> DOCKED
    out = run(obs)
    assert out["docked"] and out["final"] == "DOCKED"
    assert [t["to"] for t in out["trace"]] == ["ALIGN", "DOCK", "DOCKED"]


def test_shadow_blocks_leaving_approach():
    """[REQ:SN] an unlit dock site cannot acquire the tag -> stays APPROACH (the #57 gate)."""
    out = run([DockObs(tag_visible=False, range_m=10, pose_error_m=9, illuminated=False)] * 3)
    assert out["final"] == "APPROACH" and not out["docked"]


def test_tag_loss_mid_align_aborts():
    # [REQ:NV-09] the executive monitors preconditions (tag-lock) and fails safe (ABORT)
    """tag-lock is the only pose truth; losing it mid-dock backs off (ABORT), never blind-pushes."""
    s1, _ = step("APPROACH", _lit(20, 5.0))
    assert s1 == "ALIGN"
    s2, reason = step("ALIGN", DockObs(tag_visible=False, range_m=2, pose_error_m=0.2, illuminated=True))
    assert s2 == "ABORT" and "tag-lock lost" in reason


def test_out_of_range_holds_in_approach():
    out = run([_lit(50, 5.0), _lit(45, 5.0)])
    assert out["final"] == "APPROACH"


def test_lost_illumination_mid_dock_aborts():
    s, reason = step("DOCK", DockObs(tag_visible=True, range_m=1, pose_error_m=0.1, illuminated=False))
    assert s == "ABORT" and "illumination" in reason
