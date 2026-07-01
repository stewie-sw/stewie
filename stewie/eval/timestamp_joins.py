"""Timestamp-verified evaluation joins over explicit clock domains (PM-01).

Every join here compares DECLARED clock domains and asserts alignment within a
tolerance, failing loud on skew -- never an implicit exact-equality assumption.
Covered on this leg: the runtime-frame <-> evaluation-truth join (camera stamps
included) and cross-domain stream pairing with a constant-offset estimate. The
live ROS command/arm stream synchronization is the AS lane, not claimed here.
"""
# PROVENANCE: STEWIE eval subsystem (A. Storey)
from __future__ import annotations

import math
from typing import Sequence

import numpy as np

from stewie.bridge.sensor_io import EvaluationTruthPacket, SensorFrame

DEFAULT_JOIN_TOLERANCE_S = 0.01


class TimestampJoinError(ValueError):
    """An evaluation join failed its clock-domain or timestamp-alignment verification."""


def _times(values: Sequence[float], label: str) -> np.ndarray:
    stamps = np.asarray(values, dtype=float)
    if stamps.ndim != 1 or stamps.size == 0:
        raise TimestampJoinError(f"{label} must be a non-empty 1-D timestamp sequence")
    if not np.all(np.isfinite(stamps)):
        raise TimestampJoinError(f"{label} carries a non-finite timestamp")
    if np.any(np.diff(stamps) < 0.0):
        raise TimestampJoinError(f"{label} timestamps must be monotonically non-decreasing")
    return stamps


def estimate_clock_offset(times_a: Sequence[float], times_b: Sequence[float]) -> float:
    """Constant clock offset (b - a) from MATCHED sample pairs of the same events.

    The median is robust to a few jittered pairs; the join itself still verifies every
    residual against tolerance, so a bad estimate fails loud downstream rather than
    silently mis-pairing.
    """
    stamps_a = _times(times_a, "stream A")
    stamps_b = _times(times_b, "stream B")
    if stamps_a.size != stamps_b.size:
        raise TimestampJoinError(
            f"offset estimation needs matched pairs: {stamps_a.size} vs {stamps_b.size} samples"
        )
    return float(np.median(stamps_b - stamps_a))


def join_streams(
    times_a: Sequence[float],
    times_b: Sequence[float],
    *,
    clock_domain_a: str,
    clock_domain_b: str,
    tolerance_s: float = DEFAULT_JOIN_TOLERANCE_S,
    offset_s: float | None = None,
) -> list[tuple[int, int]]:
    """Pair every A sample with its nearest B sample, timestamp-verified within tolerance.

    Cross-domain joins REQUIRE an explicit ``offset_s`` (b - a, e.g. from
    ``estimate_clock_offset``); same-domain joins take offset 0. Any A sample whose
    nearest offset-corrected B sample is farther than ``tolerance_s`` raises.
    """
    if tolerance_s <= 0.0 or not math.isfinite(tolerance_s):
        raise TimestampJoinError("tolerance_s must be positive and finite")
    if clock_domain_a != clock_domain_b and offset_s is None:
        raise TimestampJoinError(
            f"clock domain mismatch: {clock_domain_a!r} vs {clock_domain_b!r} -- a cross-domain "
            "join requires an explicit estimated offset_s"
        )
    if offset_s is not None and not math.isfinite(offset_s):
        raise TimestampJoinError("offset_s must be finite")
    stamps_a = _times(times_a, "stream A")
    stamps_b = _times(times_b, "stream B") - (offset_s or 0.0)
    pairs: list[tuple[int, int]] = []
    for index_a, stamp in enumerate(stamps_a):
        index_b = int(np.argmin(np.abs(stamps_b - stamp)))
        skew = abs(float(stamps_b[index_b]) - float(stamp))
        if skew > tolerance_s:
            raise TimestampJoinError(
                f"stream A sample {index_a} (t={stamp:.6f}) has no stream B sample within "
                f"tolerance {tolerance_s:.6f} s (nearest skew {skew:.6f} s)"
            )
        pairs.append((index_a, index_b))
    return pairs


def assert_frame_truth_aligned(
    frame: SensorFrame,
    truth: EvaluationTruthPacket,
    tolerance_s: float = DEFAULT_JOIN_TOLERANCE_S,
) -> None:
    """Verify the runtime-frame <-> evaluation-truth join: same clock domain, same frame
    identity, packet AND per-camera timestamps aligned within tolerance."""
    if frame.clock_domain != truth.clock_domain:
        raise TimestampJoinError(
            f"clock domain mismatch: runtime {frame.clock_domain!r} vs truth "
            f"{truth.clock_domain!r} -- the evaluation join is same-timebase by contract"
        )
    if frame.frame_index != truth.frame_index:
        raise TimestampJoinError(
            f"frame_index mismatch: runtime {frame.frame_index} vs truth {truth.frame_index}"
        )
    skew = abs(frame.timestamp_s - truth.timestamp_s)
    if skew > tolerance_s:
        raise TimestampJoinError(
            f"runtime/truth timestamp skew {skew:.6f} s exceeds tolerance {tolerance_s:.6f} s"
        )
    for camera in frame.cameras:
        camera_skew = abs(camera.timestamp_s - truth.timestamp_s)
        if camera_skew > tolerance_s:
            raise TimestampJoinError(
                f"camera {camera.name!r} timestamp skew {camera_skew:.6f} s exceeds "
                f"tolerance {tolerance_s:.6f} s"
            )
