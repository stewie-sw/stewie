"""B2 telemetry injection: the mission-link constraint layer (STEWIE P21).

Pure-python and deterministic under seed: profile schema, token-bucket bandwidth, uplink latency,
seeded packet drop with COUNTED stats, and the camera byte budget. The operator-trainee path runs
through this layer; the director path never does.
"""
import json
import os

import numpy as np
import pytest

from stewie.bridge import telemetry as tl

PROFILES = os.path.join(os.path.dirname(tl.__file__), "profiles")


def test_profiles_load_and_validate():
    ideal = tl.load_profile(os.path.join(PROFILES, "ideal.json"))
    assert ideal.downlink_kbps is None and ideal.drop_prob == 0.0   # no constraints
    dflt = tl.load_profile(os.path.join(PROFILES, "mission_default.json"))
    assert dflt.downlink_kbps > 0 and dflt.uplink_latency_ms > 0
    assert "[ASSUMPTION]" in dflt.provenance                        # honest until the real link budget lands


def test_unknown_profile_keys_rejected(tmp_path):
    p = tmp_path / "bad.json"
    json.dump({"downlink_kbps": 100, "warp_drive": 9}, open(p, "w"))
    with pytest.raises(ValueError):
        tl.load_profile(str(p))


def test_token_bucket_enforces_bandwidth():
    prof = tl.LinkProfile(downlink_kbps=8.0)            # 1000 bytes/s
    link = tl.TelemetryLink(prof, seed=0)
    sent = sum(1 for _ in range(100) if link.try_send(payload_bytes=500, t_s=0.0))
    assert sent == 2                                     # burst capacity = 1 s of budget
    assert link.try_send(payload_bytes=500, t_s=0.4) is False      # only ~400 B refilled
    assert link.try_send(payload_bytes=500, t_s=0.51) is True      # ~510 B refilled


def test_drop_is_seeded_and_counted():
    prof = tl.LinkProfile(drop_prob=0.3)
    a = tl.TelemetryLink(prof, seed=42)
    b = tl.TelemetryLink(prof, seed=42)
    pat_a = [a.try_send(10, t_s=i * 0.1) for i in range(200)]
    pat_b = [b.try_send(10, t_s=i * 0.1) for i in range(200)]
    assert pat_a == pat_b                                # deterministic under seed
    assert a.stats["dropped"] == pat_a.count(False)      # every drop counted
    assert 30 <= a.stats["dropped"] <= 90                # ~0.3 of 200


def test_uplink_latency_delays_commands():
    prof = tl.LinkProfile(uplink_latency_ms=500.0)
    link = tl.TelemetryLink(prof, seed=0)
    link.send_command({"v": 0.2}, t_s=10.0)
    assert link.poll_commands(t_s=10.4) == []            # still in flight
    out = link.poll_commands(t_s=10.5)
    assert out == [{"v": 0.2}]
    assert link.poll_commands(t_s=10.6) == []            # delivered once


def test_camera_budget_downscales_until_fit():
    prof = tl.LinkProfile(downlink_kbps=64.0, camera_max_bytes=4000)
    link = tl.TelemetryLink(prof, seed=0)
    img = (np.random.default_rng(0).integers(0, 255, (240, 320), dtype=np.uint8))
    blob, meta = link.fit_camera_frame(img)
    assert len(blob) <= 4000 and meta["scale"] < 1.0     # had to downscale
    assert meta["format"] == "png"


def test_ideal_profile_is_transparent():
    link = tl.TelemetryLink(tl.LinkProfile(), seed=0)
    assert all(link.try_send(10**6, t_s=0.0) for _ in range(5))
    link.send_command({"x": 1}, t_s=0.0)
    assert link.poll_commands(t_s=0.0) == [{"x": 1}]     # zero latency


def test_downlink_latency_shapes_operator_visibility():
    """#67 [REQ:PO-03]: telemetry the rover SENDS at t becomes operator-VISIBLE at t + downlink
    latency -- light + relay + ground processing; the operator never sees the present."""
    from stewie.bridge.telemetry import LinkProfile, TelemetryLink
    p = LinkProfile(downlink_kbps=100.0, downlink_latency_ms=2600.0, provenance="test")
    ln = TelemetryLink(p, seed=1)
    vis = ln.deliver_at(payload_bytes=500, t_s=10.0)
    assert vis == pytest.approx(12.6)                       # 10 s + 2.6 s
    # ideal: zero latency, unconstrained
    ideal = TelemetryLink(LinkProfile(), seed=1)
    assert ideal.deliver_at(payload_bytes=10**9, t_s=5.0) == pytest.approx(5.0)


def test_deliver_at_respects_the_byte_budget():
    from stewie.bridge.telemetry import LinkProfile, TelemetryLink
    p = LinkProfile(downlink_kbps=1.0, downlink_latency_ms=0.0, provenance="test")  # 125 B/s
    ln = TelemetryLink(p, seed=1)
    assert ln.deliver_at(payload_bytes=100, t_s=0.0) is not None
    assert ln.deliver_at(payload_bytes=10000, t_s=0.0) is None      # over budget -> not delivered
    assert ln.stats["rate_limited"] >= 1


def test_per_sol_budget_ledger_and_stranded_accounting():
    """#69-B [REQ:PO-03]: bytes are the scarcest consumable -- a per-sol ledger draws down on
    every delivery, and what does not fit is STRANDED (counted + named, never silently lost)."""
    from stewie.bridge.telemetry import LinkProfile, TelemetryLink
    p = LinkProfile(downlink_kbps=1000.0, budget_bytes_per_sol=1000, provenance="test")
    ln = TelemetryLink(p, seed=1)
    assert ln.deliver_at(payload_bytes=600, t_s=0.0, name="legA") is not None
    assert ln.budget_remaining() == 400
    assert ln.deliver_at(payload_bytes=600, t_s=1.0, name="camB") is None      # over the sol budget
    assert ln.stats["stranded"] == 1 and ln.stranded[0]["name"] == "camB"
    ln.reset_sol()                                          # the new sol resets the ledger
    assert ln.budget_remaining() == 1000 and ln.deliver_at(payload_bytes=600, t_s=2.0) is not None
