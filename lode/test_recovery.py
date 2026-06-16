"""NV-06/07: recovery triggers + the blockage-vs-slope/slip discriminator. Pure decision logic over
the progress ratio, stall duration, and the injected slip-predicted progress -- the NAVLAB26 reference
rule (<25% for ~2 s) and the false-reverse guard."""
import pytest

from lode import recovery as R


# --- NV-06: recovery trigger ---------------------------------------------------------------------
def test_nv06_sustained_low_progress_triggers_recovery():
    """[REQ:NV-06] progress below 25% sustained past the stall window triggers backup recovery."""
    assert R.recovery_needed(0.1, 3.0)["recover"] is True               # 10% for 3 s -> recover
    assert R.recovery_needed(0.1, 3.0)["reason"] == "low_progress"


def test_nv06_brief_dip_does_not_trigger():
    assert R.recovery_needed(0.1, 0.5)["recover"] is False              # only 0.5 s -> below the 2 s window
    assert R.recovery_needed(0.9, 5.0)["recover"] is False              # good progress -> nominal


def test_nv06_planner_failure_always_triggers():
    out = R.recovery_needed(0.9, 0.0, planner_failed=True)
    assert out["recover"] is True and out["reason"] == "planner_failure"


def test_nv06_thresholds_are_configurable():
    assert R.recovery_needed(0.4, 3.0, progress_thresh=0.5)["recover"] is True   # stricter threshold
    assert R.recovery_needed(0.1, 3.0, min_stall_s=5.0)["recover"] is False      # longer window required


# --- NV-07: blockage vs expected slope/slip slowdown ---------------------------------------------
def test_nv07_slowdown_matching_slip_is_not_a_blockage():
    """[REQ:NV-07] low progress that matches the slip-predicted ground speed is an EXPECTED slowdown,
    not a blockage -- so recovery must not reverse."""
    # on a slope slip predicts 80% loss -> expected ratio 0.20; achieving 0.18 is expected, not blocked
    assert R.classify_stall(0.18, 0.20) == "slope_slip"


def test_nv07_progress_far_below_slip_prediction_is_a_blockage():
    # slip predicts 0.90 progress (near-flat) but achieving 0.05 -> blocked despite available traction
    assert R.classify_stall(0.05, 0.90) == "blockage"


def test_nv07_good_progress_is_nominal():
    assert R.classify_stall(0.85, 0.90) == "nominal"


# --- NV-06+07 combined recommendation ------------------------------------------------------------
def test_recommend_reverses_on_a_real_blockage():
    out = R.recommend(0.05, 3.0, 0.90)                                  # stalled, far below slip prediction
    assert out["action"] == "reverse" and out["recover"] is True and out["stall_class"] == "blockage"


def test_recommend_persists_through_an_expected_slope_slowdown():
    """The false-reverse guard: a slow climb that matches slip must NOT reverse."""
    out = R.recommend(0.18, 3.0, 0.20)                                  # low progress, but slip explains it
    assert out["action"] == "persist" and out["stall_class"] == "slope_slip"


def test_recommend_replans_globally_on_planner_failure():
    out = R.recommend(0.9, 0.0, 0.9, planner_failed=True)
    assert out["action"] == "replan_global" and out["recover"] is True


def test_recommend_continues_when_nominal():
    out = R.recommend(0.85, 1.0, 0.90)
    assert out["action"] == "continue" and out["recover"] is False


def test_rejects_nonphysical_inputs():
    with pytest.raises(ValueError):
        R.recovery_needed(-0.1, 1.0)
    with pytest.raises(ValueError):
        R.classify_stall(0.5, 1.5)                                      # expected ratio out of [0,1]
