"""B2.x telemetry injector: the operator-bound message pipe over the link constraint layer (P21/P23).

The injector drives ``TelemetryLink`` for a STREAM of operator-bound telemetry messages: it applies
the token-bucket bytes/s rate limit, the uplink command latency, and the seeded message drop (drops
COUNTED and published on a stats channel), and is deterministic under ``seed``. Two named mission
profiles back it: ``ideal`` (no constraints) and an [ASSUMPTION]-tagged default until the rover team
supplies the real link budget.

Pure-python + numpy, deterministic under seed (the bridge convention). No ROS2 required.
"""
import os

import pytest

from stewie.bridge import injector as inj
from stewie.bridge import telemetry as tl

PROFILES = os.path.join(os.path.dirname(tl.__file__), "profiles")


def _msgs(n, payload_bytes, dt, t0=0.0):
    """A deterministic operator-bound message stream: n messages, fixed size, spaced dt apart."""
    return [inj.OperatorMessage(t_s=t0 + i * dt, payload_bytes=payload_bytes, kind="telem",
                                body={"i": i}) for i in range(n)]


def test_named_profiles_back_the_injector():
    ideal = inj.TelemetryInjector.from_profile_name("ideal", seed=0)
    assert ideal.profile.downlink_kbps is None and ideal.profile.drop_prob == 0.0
    default = inj.TelemetryInjector.from_profile_name("mission_default", seed=0)
    assert default.profile.downlink_kbps > 0 and default.profile.drop_prob > 0
    assert "[ASSUMPTION]" in default.profile.provenance     # honest until the real link budget lands


def test_drop_counts_under_a_fixed_seed_match_injected_exactly():
    """Every message either DELIVERED or DROPPED; drops are counted and the stats channel total
    equals the count of dropped results, exactly, under a fixed seed."""
    prof = tl.LinkProfile(drop_prob=0.3)                    # rate UNconstrained: isolate drop
    a = inj.TelemetryInjector(prof, seed=42)
    b = inj.TelemetryInjector(prof, seed=42)
    msgs = _msgs(200, payload_bytes=10, dt=0.1)
    res_a = a.inject(msgs)
    res_b = b.inject(msgs)
    delivered_a = [r for r in res_a if r.delivered]
    dropped_a = [r for r in res_a if r.reason == "dropped"]
    assert [r.delivered for r in res_a] == [r.delivered for r in res_b]    # deterministic under seed
    assert a.stats_channel.dropped == len(dropped_a)        # stats-channel count == actual drops
    assert a.stats_channel.dropped == 200 - len(delivered_a)
    assert a.stats_channel.injected == 200
    assert 30 <= a.stats_channel.dropped <= 90              # ~0.3 of 200


def test_seeded_drop_pattern_is_reproducible_across_instances():
    prof = tl.LinkProfile(drop_prob=0.4)
    pat = lambda: [r.delivered for r in inj.TelemetryInjector(prof, seed=7).inject(_msgs(150, 10, 0.1))]
    assert pat() == pat()


def test_token_bucket_caps_operator_side_throughput_at_profile_kbps():
    """Measured operator-side throughput over a replayed stream must be <= the profile's kbps.

    A token bucket allows a one-second burst on top of the steady rate, so the cap is
    ``delivered_bytes <= burst + kbps * span``; over a window long enough that the burst amortizes,
    the measured rate converges to (and never exceeds) the profile's kbps."""
    prof = tl.LinkProfile(downlink_kbps=8.0)               # 1000 bytes/s; burst capacity = 1 s = 1000 B
    injr = inj.TelemetryInjector(prof, seed=0)
    bytes_per_s = prof.downlink_kbps * 125.0
    # A long burst (1000 x 500-byte messages stamped 0.02 s apart -> ~20 s window) so the one-second
    # burst allowance amortizes and the measured rate is the steady-state cap.
    msgs = [inj.OperatorMessage(t_s=i * 0.02, payload_bytes=500, kind="telem", body={"i": i})
            for i in range(1000)]
    res = injr.inject(msgs)
    delivered = [r for r in res if r.delivered]
    span = max(m.t_s for m in msgs) - min(m.t_s for m in msgs)
    delivered_bytes = sum(r.message.payload_bytes for r in delivered)
    # the token-bucket guarantee: delivered never exceeds steady budget + the one-second burst
    assert delivered_bytes <= bytes_per_s * span + bytes_per_s + 1e-9
    measured_kbps = (delivered_bytes * 8.0 / 1000.0) / span
    assert measured_kbps <= prof.downlink_kbps * 1.10      # within 10% of the cap once amortized
    assert injr.stats_channel.rate_limited == len(res) - len(delivered) - injr.stats_channel.dropped


def test_uplink_latency_delays_operator_commands():
    prof = tl.LinkProfile(uplink_latency_ms=500.0)
    injr = inj.TelemetryInjector(prof, seed=0)
    injr.send_command({"v": 0.2}, t_s=10.0)
    assert injr.poll_commands(t_s=10.4) == []              # still in flight
    assert injr.poll_commands(t_s=10.5) == [{"v": 0.2}]
    assert injr.poll_commands(t_s=10.6) == []              # delivered once


def test_ideal_profile_delivers_everything_with_zero_latency():
    injr = inj.TelemetryInjector(tl.LinkProfile(), seed=0)
    res = injr.inject(_msgs(20, payload_bytes=10**6, dt=0.0))
    assert all(r.delivered for r in res)                    # unconstrained
    assert injr.stats_channel.dropped == 0 and injr.stats_channel.rate_limited == 0
    injr.send_command({"x": 1}, t_s=0.0)
    assert injr.poll_commands(t_s=0.0) == [{"x": 1}]        # zero uplink latency


def test_delivered_messages_carry_operator_visibility_time():
    """A delivered message exposes the operator-visibility time (t_s + downlink latency); the
    operator never sees the present (the move-and-wait baseline)."""
    prof = tl.LinkProfile(downlink_kbps=100.0, downlink_latency_ms=2600.0, provenance="test")
    injr = inj.TelemetryInjector(prof, seed=1)
    res = injr.inject([inj.OperatorMessage(t_s=10.0, payload_bytes=500, kind="telem", body={})])
    assert res[0].delivered
    assert res[0].visible_at == pytest.approx(12.6)        # 10 s + 2.6 s


def test_stats_channel_publishes_running_totals():
    """The stats channel is a published, snapshot-able record (the operator/director stats topic)."""
    prof = tl.LinkProfile(drop_prob=0.5)
    injr = inj.TelemetryInjector(prof, seed=3)
    injr.inject(_msgs(40, 10, 0.1))
    snap = injr.stats_channel.snapshot()
    assert snap["injected"] == 40
    assert snap["delivered"] + snap["dropped"] + snap["rate_limited"] == 40
    assert snap["bytes_delivered"] == sum(10 for _ in range(snap["delivered"]))


def test_unknown_profile_name_rejected():
    with pytest.raises((FileNotFoundError, ValueError)):
        inj.TelemetryInjector.from_profile_name("warp_drive", seed=0)
