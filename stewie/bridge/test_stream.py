"""NV-12: the versioned streaming command/telemetry session -- version + monotonic seq + timestamp per
frame, bounded-window backpressure, and an SF-01-tied safe-stop on link stall. Pure (caller supplies
`now`, the watchdog pattern), tested without ROS2."""
import pytest

from stewie.bridge import rc_contract as RC
from stewie.bridge.stream import PROTOCOL_VERSION, StreamSession


def test_frames_carry_version_seq_timestamp():  # [REQ:NV-12]
    s = StreamSession()
    f0 = s.send({"cmd": "GoTo"}, now=0.0)
    f1 = s.send({"cmd": "Excavate"}, now=0.1)
    assert f0["v"] == PROTOCOL_VERSION and f1["v"] == PROTOCOL_VERSION
    assert f0["seq"] == 0 and f1["seq"] == 1                 # monotonic sequence numbers
    assert f0["t"] == 0.0 and f1["t"] == 0.1                 # timestamps (caller-supplied)
    assert s.outstanding == 2


def test_backpressure_refuses_past_the_window_then_recovers_on_ack():
    s = StreamSession(window=2)
    assert s.send("a", now=0.0) and s.send("b", now=0.0)     # window full
    assert s.send("c", now=0.0) is None and s.refused == 1   # backpressure: refused, not dropped
    s.ack(0)                                                 # consumer acks frame 0 -> window frees
    assert s.send("c", now=0.1) is not None and s.outstanding == 2


def test_cumulative_ack_clears_the_window():
    s = StreamSession(window=8)
    for i in range(5):
        s.send(i, now=0.0)
    s.ack(3)                                                 # cumulative through seq 3
    assert s.last_ack == 3 and s.outstanding == 1            # only seq 4 remains un-acked


def test_safe_stop_trips_on_link_stall_and_fires_once():
    fired = []
    s = StreamSession(ack_deadline_s=2.0, on_safe_stop=lambda: fired.append(1))
    s.send("cmd", now=0.0)
    assert s.tick(now=1.0) is False and not fired            # within deadline -> no trip
    assert s.tick(now=2.5) is True and fired == [1]          # past deadline -> safe-stop, once
    s.tick(now=3.0)
    assert fired == [1]                                      # idempotent; no second fire
    assert s.send("more", now=3.0) is None                   # tripped session refuses further sends


def test_ack_before_deadline_prevents_stall():
    s = StreamSession(ack_deadline_s=2.0)
    s.send("cmd", now=0.0)
    s.ack(0)
    assert s.tick(now=10.0) is False                         # acked -> nothing outstanding -> no stall


def test_safe_stop_submits_link_stall_safe_through_the_rc_backend():
    # NV-12 wires into the SAME RC.Safe contract SF-01 uses -- a stalled link safes the rover
    be = RC.RecordingBackend()
    s = StreamSession(ack_deadline_s=1.0,
                      on_safe_stop=lambda: be.submit(RC.Safe(reason=RC.SAFE_REASON_LINK_STALL)))
    s.send("cmd", now=0.0)
    s.tick(now=2.0)
    assert be.commands and be.commands[-1].kind == "safe"
    assert be.commands[-1].reason == RC.SAFE_REASON_LINK_STALL


def test_construction_validates():
    with pytest.raises(ValueError):
        StreamSession(window=0)
    with pytest.raises(ValueError):
        StreamSession(ack_deadline_s=0)
