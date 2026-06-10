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
