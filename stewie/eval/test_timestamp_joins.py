"""[REQ:PM-01] Explicit clock domains + timestamp-verified evaluation joins.

Closeable slice: the runtime-frame <-> evaluation-truth join over the REAL committed
fixture frame plus cross-clock-domain stream alignment with constant-offset estimation
(real ImuWheelModel samples). The live ROS command/arm stream leg is separate (AS lane)
and is deliberately NOT claimed here.
"""
import dataclasses
import os
import sys

import pytest

from stewie.bridge import sensor_io
from stewie.eval import timestamp_joins as tj

_FRAME_DIR = os.path.join(os.path.dirname(__file__), "tests", "fixtures", "frame")
_DUST = os.environ.get("STEWIE_ROOT", "/mnt/projects/stewie/code")


def _frame_and_truth():
    frame = sensor_io.read_sensors(os.path.join(_FRAME_DIR, "runtime_sensors.json"))
    truth = sensor_io.read_evaluation_truth(os.path.join(_FRAME_DIR, "evaluation_truth.json"))
    return frame, truth


def test_fixture_streams_declare_clock_domains_and_aligned_join_passes():
    """[REQ:PM-01] the real committed frame + truth carry an EXPLICIT clock domain and their
    evaluation join is timestamp-verified within tolerance (camera stamps included)."""
    frame, truth = _frame_and_truth()
    assert frame.clock_domain == "sim_monotonic"          # the canonical single sim timebase
    assert truth.clock_domain == "sim_monotonic"
    tj.assert_frame_truth_aligned(frame, truth, tolerance_s=0.01)   # aligned -> no raise


def test_skewed_truth_join_is_rejected():
    """[REQ:PM-01] a 1 s truth-clock skew on the SAME real frame fails the evaluation join
    (tolerance-based, not silently accepted)."""
    frame, truth = _frame_and_truth()
    skewed = dataclasses.replace(truth, timestamp_s=truth.timestamp_s + 1.0)
    with pytest.raises(tj.TimestampJoinError, match="tolerance"):
        tj.assert_frame_truth_aligned(frame, skewed, tolerance_s=0.01)


def test_frame_index_mismatch_is_rejected():
    """[REQ:PM-01] equal timestamps are not enough -- the join also verifies frame identity."""
    frame, truth = _frame_and_truth()
    wrong = dataclasses.replace(truth, frame_index=truth.frame_index + 1)
    with pytest.raises(tj.TimestampJoinError, match="frame_index"):
        tj.assert_frame_truth_aligned(frame, wrong)


def test_cross_clock_domain_frame_truth_join_is_refused():
    """[REQ:PM-01] a truth packet on a FOREIGN clock domain never joins implicitly -- the
    domains are declared and compared, not assumed."""
    frame, truth = _frame_and_truth()
    foreign = dataclasses.replace(truth, clock_domain="ros_wall")
    with pytest.raises(tj.TimestampJoinError, match="clock domain"):
        tj.assert_frame_truth_aligned(frame, foreign)


@pytest.mark.skipif(not os.path.isdir(_DUST), reason="stewie not available")
def test_offset_estimation_aligns_cross_domain_imu_stream():
    """[REQ:PM-01] the same real IMU stream reported on a boot-offset clock joins ONLY after
    the constant offset is estimated from matched samples; the unaligned cross-domain join
    is refused rather than silently paired."""
    sys.path.insert(0, _DUST)
    from stewie.twin import proprioception as pp
    model = pp.ImuWheelModel(seed=0)
    imu_t = [model.step_imu(i * 0.01, 0.0).t for i in range(20)]     # real producer samples
    boot_offset = 3.2                                                # eval clock booted later
    eval_t = [t + boot_offset for t in imu_t]

    with pytest.raises(tj.TimestampJoinError, match="clock domain"):
        tj.join_streams(imu_t, eval_t, clock_domain_a="sim_monotonic", clock_domain_b="eval_wall")

    offset = tj.estimate_clock_offset(imu_t, eval_t)
    assert offset == pytest.approx(boot_offset, abs=1e-12)
    pairs = tj.join_streams(imu_t, eval_t, clock_domain_a="sim_monotonic",
                            clock_domain_b="eval_wall", offset_s=offset)
    assert pairs == [(i, i) for i in range(20)]                      # every sample pairs exactly

    # residual skew beyond tolerance after offset correction still fails loud
    skewed = list(eval_t)
    skewed[-1] += 0.5                                                # keeps the stream monotone
    with pytest.raises(tj.TimestampJoinError, match="tolerance"):
        tj.join_streams(imu_t, skewed, clock_domain_a="sim_monotonic",
                        clock_domain_b="eval_wall", offset_s=offset, tolerance_s=0.001)
