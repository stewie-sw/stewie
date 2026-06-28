"""TDD for dart.s3li_reader: a reader for the REAL DLR S3LI ``s3li_crater`` ROS1 bag (Mt Etna /
Cisternazza, 2021-07-07; the same traverse dart.s3li_dem anchors). Runs against the locally staged
25.94 GB bag; STREAMS only the first handful of real stereo / IMU messages (never random-indexes the
26 GB bag, never copies it). Data-gated -> skips cleanly where the bag / GT / DEM are absent, mirroring
the _have_lusnar / _have_katwijk / _have_all pattern in the sibling readers.

Verified-on-disk facts these tests pin (measured on the real bag + Cfgs + GT, 2026-06-28):
  * stereo: /stereo/{left,right}/image_rect are sensor_msgs/Image, mono8, 512x688, step 688 -> decode
    np.frombuffer(data, uint8).reshape(512, 688). Left=33593 msgs, right=31796 -> the counts DIFFER,
    so left<->right is associated by NEAREST header timestamp within a ~half-frame tol (~17 ms; frame
    rate ~30 Hz). Matched pairs share an IDENTICAL header stamp (assoc dt = 0); dropped-right frames
    leave a left with its nearest right ~33 ms away, which the tol correctly rejects.
  * intrinsics (Cfgs/cam0_pinhole.yaml, PINHOLE, zero distortion): fx=fy=579.4882694716105,
    cx=342.1329879760742, cy=255.80628776550293, 688x512. baseline = Camera.bf/fx =
    116.08582250779968/579.4882694716105 = 0.2003247 m. The in-bag camera_info carries the SAME calib
    (K rounded to ~6 dp; right P[3] = -116.085823 = -fx*baseline) -> Cfgs and bag AGREE to ~5e-7.
  * GT (GT/s3li_crater/global_lle.pos, RTKLIB): 7582 rows, ~5 Hz, WGS84-ellipsoidal lat/lon/height.
    Converted to the SAME local ENU frame as dart.s3li_dem (its declared origin == the GT first row),
    the crater loop spans E ~309 m x N ~245 m. The bag window (record span 1136 s, fully nested in the
    GT window by direct UTC conversion: GT starts 458 s before, ends 25 s after) -> direct conversion
    OVERLAPS, no leap offset needed (the GT calendar column is labelled GPST; a finer GPS-vs-UTC ~18 s
    alignment cannot be resolved from span overlap alone and is NOT silently applied).

Truth firewall (invariant I3): the GT loaders here are SCORING-ONLY. The stereo / IMU stream carries
NO pose; a downstream VO consumes images + K + baseline only. These tests read GT to SCORE / validate
(the test is the scoring layer, like dart.lusnar_reader's GT use); the firewall is enforced downstream
at the estimator input, never by feeding a GT pose into a perception API.
"""
import os

import numpy as np
import pytest

from dart import s3li_dem, s3li_reader
from dart.s3li_reader import S3liReader

_have_bag = os.path.isfile(s3li_reader.DEFAULT_BAG_PATH)
_have_gt = os.path.isfile(s3li_reader.DEFAULT_GT_PATH)
_have_dem = os.path.isfile(s3li_dem.DEFAULT_DEM_PATH)


@pytest.fixture(scope="module")
def reader() -> S3liReader:
    # Construction is cheap: it stores paths + builds intrinsics, opens NOTHING.
    return S3liReader()


# ---- pure / numeric (no bag, no GT) --------------------------------------------------------------
def test_intrinsics_match_cfgs(reader: S3liReader) -> None:
    """reader.intrinsics is the Cfgs/cam0_pinhole.yaml pinhole calibration, exposed as the same
    Intrinsics type the VO front ends consume (dart.stereo_vo.Intrinsics)."""
    K = reader.intrinsics.matrix()
    assert K.shape == (3, 3)
    assert K[0, 0] == pytest.approx(579.4882694716105, abs=1e-9)
    assert K[1, 1] == pytest.approx(579.4882694716105, abs=1e-9)
    assert K[0, 2] == pytest.approx(342.1329879760742, abs=1e-9)
    assert K[1, 2] == pytest.approx(255.80628776550293, abs=1e-9)
    assert K[2, 2] == 1.0


def test_baseline_is_bf_over_fx(reader: S3liReader) -> None:
    """The stereo baseline is the orbslam_config Camera.bf divided by fx (bf = fx*baseline)."""
    assert reader.baseline_m == pytest.approx(116.08582250779968 / 579.4882694716105, abs=1e-12)
    assert reader.baseline_m == pytest.approx(0.2003247, abs=1e-6)
    assert reader.baseline_m > 0.0


# ---- GT (needs the GT track; no bag) -------------------------------------------------------------
@pytest.mark.skipif(not _have_gt, reason="S3LI global_lle.pos GT not staged")
def test_gt_lle_loads_real_track(reader: S3liReader) -> None:
    ts, lle = reader.gt_lle()
    assert ts.dtype == np.int64
    assert lle.shape == (ts.shape[0], 3)
    assert ts.shape[0] == 7582                       # the real s3li_crater RTKLIB row count
    assert np.all(np.diff(ts) > 0)                   # strictly increasing epoch-ns timestamps
    # Mt Etna / Cisternazza traverse, and the first GT row IS the s3li_dem declared origin.
    assert lle[0, 0] == pytest.approx(s3li_dem.ORIGIN_LAT_DEG, abs=1e-6)
    assert lle[0, 1] == pytest.approx(s3li_dem.ORIGIN_LON_DEG, abs=1e-6)
    assert np.all((37.0 < lle[:, 0]) & (lle[:, 0] < 38.0))
    assert np.all((14.0 < lle[:, 1]) & (lle[:, 1] < 16.0))


# ---- GT ENU (needs GT + the independent DEM, for the shared frame) -------------------------------
@pytest.mark.skipif(not (_have_gt and _have_dem), reason="S3LI GT or Copernicus DEM tile not staged")
def test_gt_enu_in_s3li_dem_frame(reader: S3liReader) -> None:
    """GT in the SAME local ENU frame as dart.s3li_dem (origin = the declared start fix). The crater
    loop spans E ~309 m x N ~245 m -- the real Cisternazza crater traverse."""
    ts, enu = reader.gt_enu()
    assert ts.dtype == np.int64
    assert enu.shape == (ts.shape[0], 3)
    # the origin equals the GT first row -> the first ENU point is (0, 0, 0)
    assert np.allclose(enu[0], 0.0, atol=1e-6)
    e_ext = float(np.ptp(enu[:, 0]))
    n_ext = float(np.ptp(enu[:, 1]))
    assert 290.0 < e_ext < 330.0                     # measured 309.04 m
    assert 230.0 < n_ext < 260.0                     # measured 244.79 m
    assert np.hypot(e_ext, n_ext) > 200.0            # a real ~300 m crater loop, not a point


# ---- bag stereo (needs the bag); STREAM the first ~60 pairs, early-break -------------------------
@pytest.mark.skipif(not _have_bag, reason="S3LI s3li_crater.bag not staged")
def test_stereo_pairs_shapes_and_monotonic(reader: S3liReader) -> None:
    pairs = []
    for ts_ns, left, right in reader.stereo_pairs():
        pairs.append((ts_ns, left, right))
        if len(pairs) >= 60:
            break
    assert len(pairs) == 60
    ts0, left0, right0 = pairs[0]
    assert left0.shape == (512, 688)                 # mono8 512x688
    assert left0.dtype == np.uint8
    assert right0.shape == (512, 688)
    assert right0.dtype == np.uint8
    # left and right are DISTINCT camera frames, not the same buffer twice
    assert not np.array_equal(left0, right0)
    stamps = [p[0] for p in pairs]
    assert all(b > a for a, b in zip(stamps, stamps[1:]))   # strictly increasing pair stamps


@pytest.mark.skipif(not _have_bag, reason="S3LI s3li_crater.bag not staged")
def test_stereo_association_dt_within_tolerance(reader: S3liReader) -> None:
    """Left/right counts differ (33593 vs 31796) -> nearest-timestamp association. Matched pairs share
    an identical header stamp (dt~0); dropped-right frames sit ~33 ms from their nearest right and are
    correctly rejected by the ~17 ms tol. Measured on the first chunk: median |dt|~0, >0.85 within tol."""
    left_ts = np.array(list(reader.image_timestamps("left", limit=100)), dtype=np.int64)
    right_ts = np.array(list(reader.image_timestamps("right", limit=100)), dtype=np.int64)
    assert np.all(np.diff(left_ts) > 0)              # each stream is strictly increasing
    assert np.all(np.diff(right_ts) > 0)
    # frame rate ~30 Hz
    med_interval_ms = float(np.median(np.diff(left_ts)) / 1e6)
    assert 30.0 < med_interval_ms < 36.0
    # nearest-neighbour left->right association dt
    dts_ms = []
    for lt in left_ts:
        j = int(np.searchsorted(right_ts, lt))
        cand = [k for k in (j - 1, j) if 0 <= k < right_ts.shape[0]]
        k = min(cand, key=lambda c: abs(int(right_ts[c]) - int(lt)))
        dts_ms.append(abs(int(right_ts[k]) - int(lt)) / 1e6)
    dts_ms = np.array(dts_ms)
    assert float(np.median(dts_ms)) < 1.0            # true matches share the stamp
    assert float((dts_ms < s3li_reader.DEFAULT_ASSOC_TOL_NS / 1e6).mean()) > 0.85


@pytest.mark.skipif(not _have_bag, reason="S3LI s3li_crater.bag not staged")
def test_stereo_stride(reader: S3liReader) -> None:
    """stride=k yields every k-th matched pair (still streamed once, never random-indexed)."""
    full = []
    for i, (ts_ns, _l, _r) in enumerate(reader.stereo_pairs()):
        full.append(ts_ns)
        if i >= 9:
            break
    strided = []
    for i, (ts_ns, _l, _r) in enumerate(reader.stereo_pairs(stride=3)):
        strided.append(ts_ns)
        if i >= 3:
            break
    assert strided == full[::3][: len(strided)]      # 0th, 3rd, 6th, 9th matched pair


@pytest.mark.skipif(not _have_bag, reason="S3LI s3li_crater.bag not staged")
def test_imu_stream(reader: S3liReader) -> None:
    samples = []
    for t_ns, gyro, accel in reader.imu():
        samples.append((t_ns, gyro, accel))
        if len(samples) >= 50:
            break
    assert len(samples) == 50
    t0, gyro0, accel0 = samples[0]
    assert isinstance(t0, int)
    assert gyro0.shape == (3,) and accel0.shape == (3,)
    assert np.all(np.isfinite(gyro0)) and np.all(np.isfinite(accel0))
    stamps = [s[0] for s in samples]
    assert all(b > a for a, b in zip(stamps, stamps[1:]))     # strictly increasing
    # gravity dominates the accelerometer at rest/slow drive: |accel| within a few g of 9.8 m/s^2
    accels = np.array([np.linalg.norm(s[2]) for s in samples])
    assert np.all((2.0 < accels) & (accels < 30.0))


# ---- in-bag camera_info cross-check (needs the bag) ----------------------------------------------
@pytest.mark.skipif(not _have_bag, reason="S3LI s3li_crater.bag not staged")
def test_bag_camera_info_agrees_with_cfgs(reader: S3liReader) -> None:
    """The in-bag camera_info (K from left, baseline from right P[3]=-fx*baseline) reproduces the Cfgs
    calibration to within the bag's ~6-dp rounding."""
    bag_intr, bag_baseline = reader.bag_intrinsics()
    Kc = reader.intrinsics.matrix()
    Kb = bag_intr.matrix()
    assert np.max(np.abs(Kb - Kc)) < 1e-3            # in-bag K vs Cfgs K (bag rounded to ~6 dp)
    assert bag_baseline == pytest.approx(reader.baseline_m, abs=1e-4)
    assert bag_baseline > 0.0


# ---- time alignment (needs bag + GT) -------------------------------------------------------------
@pytest.mark.skipif(not (_have_bag and _have_gt), reason="S3LI bag or GT not staged")
def test_bag_gt_time_alignment_overlaps(reader: S3liReader) -> None:
    """Bag record span (~1136 s) is fully nested inside the GT window by direct UTC conversion, so the
    spans OVERLAP and no constant leap offset is needed (offset_ns == 0). Reported so the offset is
    visible (the GT column is labelled GPST)."""
    al = reader.time_alignment()
    assert al.bag_end_ns > al.bag_start_ns
    assert al.gt_end_ns > al.gt_start_ns
    assert 1100.0 < al.bag_duration_s < 1200.0       # measured 1135.98 s
    assert al.overlaps is True
    assert al.offset_ns == 0
    # the bag window sits inside the GT window (GT starts before, ends after)
    assert al.gt_start_ns <= al.bag_start_ns
    assert al.gt_end_ns >= al.bag_end_ns
