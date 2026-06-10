"""G1 blocker #2 closing pass: TOP-LEVEL strict acceptance on the canonical runtime packet.

The channel/frame allow-lists exist (A5); these close the remaining holes: a novel TOP-LEVEL key or
a novel CHANNEL cannot ride in, the clock block must be well-formed, and sequence_id must be a
non-negative integer. Strict = reject, never coerce.
"""
import pytest

from stewie.bridge import runtime_io as rio


def _minimal():
    return {"schema_version": "dustgym_runtime/1.0",
            "clock": "sim_monotonic",
            "sequence_id": 7,
            "channels": {"camera": {"status": "UNAVAILABLE"},
                         "imu": {"status": "UNAVAILABLE"},
                         "wheel": {"status": "UNAVAILABLE"},
                         "joints": {"status": "UNAVAILABLE"},
                         "power": {"status": "UNAVAILABLE"}}}


def test_minimal_packet_accepted():
    out = rio.parse_canonical(_minimal())
    assert set(out["unavailable"]) >= {"camera", "joints", "power"}


def test_novel_top_level_key_rejected():
    p = _minimal(); p["debug_dump"] = {"anything": 1}
    with pytest.raises(ValueError, match="top-level"):
        rio.parse_canonical(p)


def test_novel_channel_rejected():
    p = _minimal(); p["channels"]["lidar_beta"] = {"status": "OK"}
    with pytest.raises(ValueError, match="channel"):
        rio.parse_canonical(p)


def test_bad_clock_rejected():
    p = _minimal(); p["clock"] = {"t0": 0.0}              # a dict is NOT the contract (name string)
    with pytest.raises(ValueError, match="clock"):
        rio.parse_canonical(p)
    p2 = _minimal(); p2["clock"] = "  "
    with pytest.raises(ValueError, match="clock"):
        rio.parse_canonical(p2)


def test_bad_sequence_rejected():
    p = _minimal(); p["sequence_id"] = -3
    with pytest.raises(ValueError, match="sequence"):
        rio.parse_canonical(p)
    p2 = _minimal(); p2["sequence_id"] = "seven"
    with pytest.raises(ValueError, match="sequence"):
        rio.parse_canonical(p2)
