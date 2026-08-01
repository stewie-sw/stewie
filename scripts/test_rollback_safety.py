"""SR-12: the rollback guard must refuse the rollback that was actually sitting there.

Measured on the live host 2026-07-28:

    stewie-backend:latest              created 2026-07-26 12:57
    stewie-backend:rollback            created 2026-07-10 07:51   <-- 7 days BEFORE AR-005
    stewie-backend:rollback-2026-07-26 created 2026-07-11 14:13   <-- the NAME lies by 15 days
    commit 0946e1e8 (AR-005)           landed  2026-07-17 22:58

AR-005 is "anonymous /ide users are no longer director". Executing the documented recovery would
have restored a public backend where every anonymous browser resolves to role director -- and the
misleadingly-named `rollback-2026-07-26` tag is exactly what an operator grabs under pressure.

The real epochs are replayed here so the guard is pinned against the incident it exists for, not
against a hypothetical.

Run: <venv>/bin/python -m pytest scripts/test_rollback_safety.py -q
"""
from __future__ import annotations

import datetime as _dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_rollback_safety as R  # noqa: E402


def _e(iso: str) -> float:
    return _dt.datetime.fromisoformat(iso).timestamp()


_ROLLBACK = _e("2026-07-10T07:51:23-05:00")       # stewie-backend:rollback
_ROLLBACK_MISNAMED = _e("2026-07-11T14:13:38-05:00")   # tagged rollback-2026-07-26
_LATEST = _e("2026-07-26T12:57:21-05:00")
_AR005 = {"sha": "0946e1e8", "id": "AR-005", "date": "2026-07-17T22:58:42-05:00",
          "reason": "anonymous /ide users are no longer director", "epoch": _e("2026-07-17T22:58:42-05:00")}


def test_the_real_rollback_tag_is_refused():
    """The core: the tag the runbook points at would have re-opened AR-005."""
    v = R.evaluate(_ROLLBACK, _AR005, "stewie-backend:rollback")
    assert v["ok"] is False
    assert v["floor_id"] == "AR-005"
    assert 7.0 < v["gap_days"] < 8.5, v
    assert "director" in v["reason"]


def test_the_current_image_is_allowed():
    """latest postdates the floor -- the guard must not block ordinary operation."""
    assert R.evaluate(_LATEST, _AR005, "stewie-backend:latest")["ok"] is True


def test_an_image_exactly_at_the_floor_is_allowed():
    assert R.evaluate(_AR005["epoch"], _AR005, "x")["ok"] is True


def test_a_missing_image_is_refused_not_assumed_safe():
    v = R.evaluate(None, _AR005, "stewie-backend:nope")
    assert v["ok"] is False and "not found" in v["reason"]


def test_no_recorded_floor_is_not_a_refusal():
    assert R.evaluate(_ROLLBACK, None, "x")["ok"] is True


def test_the_misleading_tag_name_is_caught():
    """rollback-2026-07-26 pointing at a 2026-07-11 image is the label an operator trusts."""
    v = R.evaluate_tag_name_truth("stewie-backend:rollback-2026-07-26", _ROLLBACK_MISNAMED)
    assert v["ok"] is False
    assert 14.0 < v["off_days"] < 16.0, v


def test_a_truthful_dated_tag_passes():
    same_day = _e("2026-07-26T09:00:00-05:00")
    assert R.evaluate_tag_name_truth("stewie-backend:rollback-2026-07-26", same_day)["ok"] is True


def test_an_undated_tag_name_is_not_second_guessed():
    assert R.evaluate_tag_name_truth("stewie-backend:rollback", _ROLLBACK)["ok"] is True


def test_the_shipped_floor_file_parses_and_names_ar005():
    """The floor is a real reviewable record, not an empty file that makes the guard vacuous."""
    floor = R.load_floor()
    assert floor is not None, "governance floor missing -- the guard would pass everything"
    assert floor["id"] == "AR-005", f"newest floor entry is {floor}"
    assert floor["epoch"] > _e("2026-07-17T00:00:00-05:00")


def test_the_shipped_floor_refuses_the_real_rollback_image():
    """End to end over the committed floor file: the recorded rollback image is refused."""
    v = R.evaluate(_ROLLBACK, R.load_floor(), "stewie-backend:rollback")
    assert v["ok"] is False and v["floor_id"] == "AR-005"
