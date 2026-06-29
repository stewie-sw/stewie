"""Reader for the REAL DLR S3LI ``s3li_crater`` ROS1 bag (Mt Etna / Cisternazza, 2021-07-07).

S3LI (Stereo, Sensor-fused, Semantic Lunar-analogue Indexing -- the DLR planetary-analogue stereo +
IMU + LiDAR dataset, Giubilato et al.) ``s3li_crater`` is a ~1.3 km rover loop around the Cisternazza
crater on Mt Etna, recorded as a single 25.94 GB ROS1 bag (1136 s, 2.07 M messages). This module reads
that bag into the same calibration / streaming idiom the rest of DART uses (cf.
:class:`dart.lusnar_reader.LusnarReader` and :class:`dart.stereo_vo.Intrinsics`), so the existing
stereo / VO / mapping front ends consume it unchanged. It is the real-rover companion to the synthetic
:mod:`dart.lusnar_reader`, and it shares the local ENU frame of :mod:`dart.s3li_dem` (the independent
Copernicus Etna DEM prior for the same traverse).

VERIFIED on-disk facts (measured 2026-06-28; nothing here is synthetic):

  * Topics (``rosbags.rosbag1.Reader``): ``/stereo/left/image_rect`` (33593) + ``/stereo/right/
    image_rect`` (31796) are ``sensor_msgs/Image``, **mono8, 512x688, step 688** -> decode
    ``np.frombuffer(m.data, np.uint8).reshape(m.height, m.width)``. ``/imu/data`` (454373) is
    ``sensor_msgs/Imu``. ``/stereo/{left,right}/camera_info`` is ``sensor_msgs/CameraInfo`` (uppercase
    ``K``/``P``/``D``/``R`` attrs). ``/bf_lidar/points_raw`` is a PointCloud2, ignored here.
  * The left and right image COUNTS DIFFER (33593 vs 31796), so left<->right is associated by NEAREST
    header timestamp within a ~half-frame tolerance (frame rate ~30 Hz -> ~17 ms). Matched pairs share
    an IDENTICAL header stamp (assoc dt = 0); a dropped right frame leaves its left with the nearest
    right ~33 ms away, which the tolerance rejects. Stream once, buffer to pair -- never random-index
    the 26 GB bag.
  * Timestamps: ``m.header.stamp.sec * 1e9 + m.header.stamp.nanosec`` -> Unix-epoch ns (first left
    image 1625658929426191123 = 2021-07-07 11:55:29 UTC). Strictly increasing per stream.
  * Intrinsics (Cfgs/cam0_pinhole.yaml, PINHOLE, zero distortion): fx=fy=579.4882694716105,
    cx=342.1329879760742, cy=255.80628776550293, 688x512. baseline = Camera.bf/fx (orbslam_config) =
    116.08582250779968 / 579.4882694716105 = 0.2003247 m. The in-bag ``camera_info`` carries the SAME
    calibration (K rounded to ~6 dp; right ``P[3] = -116.085823 = -fx*baseline``), so Cfgs and bag
    AGREE to ~5e-7 -- see :meth:`S3liReader.bag_intrinsics`.
  * Ground truth (GT/s3li_crater/global_lle.pos, RTKLIB): 7582 rows, ~5 Hz, ``YYYY/MM/DD HH:MM:SS.sss
    lat lon height Q ns ...``, WGS84-ELLIPSOIDAL. Converted into the SAME local ENU frame as
    :class:`dart.s3li_dem.S3liDem` (whose declared origin IS the GT first row), the crater loop spans
    E ~309 m x N ~245 m. The GT calendar column is labelled GPST; by direct UTC conversion the bag
    record window (1136 s) is fully NESTED inside the GT window (GT starts 458 s before, ends 25 s
    after), so the spans OVERLAP and no constant leap offset is applied -- :meth:`time_alignment`
    reports the spans and the (zero) offset so any residual GPS-vs-UTC ~18 s subtlety stays visible
    rather than being silently absorbed.

TRUTH FIREWALL (invariant I3). The GT loaders (:meth:`gt_lle`, :meth:`gt_enu`, :meth:`time_alignment`)
are SCORING-ONLY. The stereo / IMU stream (:meth:`stereo_pairs`, :meth:`imu`) carries NO pose; a
downstream visual-odometry / SLAM front end must take images + K + baseline only and never a GT pose.
The READER is the data / scoring layer, not the estimator -- as in :mod:`dart.lusnar_reader`, the
firewall is enforced DOWNSTREAM at the estimator input, never by routing a GT pose into a perception
API. Do not feed :meth:`gt_enu` into an estimator.
"""
# PROVENANCE: STEWIE DART subsystem (A. Storey). Data: DLR S3LI s3li_crater (Mt Etna analogue, public).
from __future__ import annotations

import datetime as _dt
import os
from collections import deque
from dataclasses import dataclass
from typing import Any, Iterator

import numpy as np

# rosbags is a heavy OPTIONAL dependency: it is only needed to read the REAL DLR S3LI ROS1 bag, which is
# data-gated (absent in CI and most checkouts). Import it lazily-at-module-load via try/except so merely
# IMPORTING this module (S3liReader, Intrinsics, the dataclasses) never requires rosbags -- that lets the
# many tests that import S3liReader collect cleanly without it. Any method that actually opens a bag uses
# these symbols and will fail clearly only when invoked, by which point the gated bag must also be present.
try:
    from rosbags.rosbag1 import Reader
    from rosbags.typesys import Stores, get_typestore
except ModuleNotFoundError:                      # pragma: no cover - exercised only where rosbags is absent
    Reader = None                                # type: ignore[assignment,misc]
    Stores = None                                # type: ignore[assignment]
    get_typestore = None                         # type: ignore[assignment]

from dart.stereo_vo import Intrinsics

# --- real-data paths (absolute; mirror the _KATWIJK / _LUSNAR constants in the sibling readers) ----
_DATA_ROOT = "/mnt/projects/datasets/argus_dem_nav/s3li/data"
DEFAULT_BAG_PATH = os.path.join(_DATA_ROOT, "Bagfiles", "s3li_crater.bag")
DEFAULT_GT_PATH = os.path.join(_DATA_ROOT, "GT", "s3li_crater", "global_lle.pos")

# --- ROS topics on the bag -------------------------------------------------------------------------
LEFT_IMAGE_TOPIC = "/stereo/left/image_rect"
RIGHT_IMAGE_TOPIC = "/stereo/right/image_rect"
LEFT_INFO_TOPIC = "/stereo/left/camera_info"
RIGHT_INFO_TOPIC = "/stereo/right/camera_info"
IMU_TOPIC = "/imu/data"
_IMAGE_TOPIC = {"left": LEFT_IMAGE_TOPIC, "right": RIGHT_IMAGE_TOPIC}

# --- calibration (Cfgs/cam0_pinhole.yaml, PINHOLE + zero distortion; bf from orbslam_config.yaml) ---
S3LI_FX = 579.4882694716105
S3LI_FY = 579.4882694716105
S3LI_CX = 342.1329879760742
S3LI_CY = 255.80628776550293
S3LI_WIDTH = 688
S3LI_HEIGHT = 512
# orbslam_config.yaml Camera.bf (= fx * stereo baseline). The in-bag right camera_info P[3] == -bf.
S3LI_CAMERA_BF = 116.08582250779968
S3LI_BASELINE_M = S3LI_CAMERA_BF / S3LI_FX  # 0.2003247 m

# Frame rate ~30 Hz (median interval ~33.3 ms) -> a half-frame association window of ~17 ms cleanly
# separates true matches (shared stamp, dt~0) from dropped-frame neighbours (~33 ms away).
DEFAULT_ASSOC_TOL_NS = 17_000_000


@dataclass(frozen=True)
class TimeAlignment:
    """Bag-vs-GT clock report (SCORING context; invariant I3). All fields are Unix-epoch nanoseconds.
    ``overlaps`` is True iff the GT window covers the bag window by direct UTC conversion; ``offset_ns``
    is the constant offset to ADD to GT so its window covers the bag -- 0 when they already overlap
    (the measured case). It is REPORTED, never silently applied, so a residual GPS-vs-UTC leap offset
    stays visible."""

    bag_start_ns: int
    bag_end_ns: int
    gt_start_ns: int
    gt_end_ns: int
    overlaps: bool
    offset_ns: int

    @property
    def bag_duration_s(self) -> float:
        return (self.bag_end_ns - self.bag_start_ns) / 1e9

    @property
    def gt_duration_s(self) -> float:
        return (self.gt_end_ns - self.gt_start_ns) / 1e9


def _header_ns(msg: Any) -> int:
    """Unix-epoch ns from a message's ``std_msgs/Header`` stamp (sec + nanosec)."""
    stamp = msg.header.stamp
    return int(stamp.sec) * 1_000_000_000 + int(stamp.nanosec)


class S3liReader:
    """Streaming reader over the real DLR S3LI ``s3li_crater`` ROS1 bag.

    Construction is cheap -- it stores paths + builds the Cfgs intrinsics and opens NOTHING. Each
    accessor opens the bag once via a context-managed :class:`rosbags.rosbag1.Reader`, filters to the
    connections it needs, and streams in record order (which equals per-stream header order on this
    bag). Stereo pairs are built by nearest-timestamp association during a single pass; the bag is
    never random-indexed.
    """

    def __init__(
        self,
        bag_path: str = DEFAULT_BAG_PATH,
        gt_path: str = DEFAULT_GT_PATH,
        *,
        assoc_tol_ns: int = DEFAULT_ASSOC_TOL_NS,
    ) -> None:
        self.bag_path = bag_path
        self.gt_path = gt_path
        self.assoc_tol_ns = int(assoc_tol_ns)
        self.intrinsics = Intrinsics(fx=S3LI_FX, fy=S3LI_FY, cx=S3LI_CX, cy=S3LI_CY)
        self.baseline_m = S3LI_BASELINE_M
        self.image_size = (S3LI_HEIGHT, S3LI_WIDTH)
        self._typestore = get_typestore(Stores.ROS1_NOETIC)

    # ---- bag plumbing -----------------------------------------------------------------------------
    def _require_bag(self) -> None:
        if not os.path.isfile(self.bag_path):
            raise FileNotFoundError(f"S3LI bag not found: {self.bag_path}")

    def _connections(self, reader: Reader, topics: tuple[str, ...]) -> list:
        """The bag connections whose topic is in ``topics`` (raises if any topic is absent)."""
        conns = [c for c in reader.connections if c.topic in topics]
        present = {c.topic for c in conns}
        missing = set(topics) - present
        if missing:
            raise KeyError(f"topics {sorted(missing)} not in bag {self.bag_path}")
        return conns

    # ---- stereo (streamed, nearest-timestamp paired) ----------------------------------------------
    def stereo_pairs(self, *, stride: int = 1) -> Iterator[tuple[int, np.ndarray, np.ndarray]]:
        """Stream stereo pairs in time order, yielding ``(timestamp_ns, left_u8, right_u8)``.

        Left and right are decoded mono8 ``uint8`` arrays of shape (512, 688). A single pass over the
        bag buffers the two image streams and emits a pair whenever the oldest unmatched left and right
        fall within ``assoc_tol_ns`` (matched pairs share a header stamp); an unmatched frame -- the
        side whose count is smaller is missing some frames -- is dropped. ``stride`` yields every
        ``stride``-th matched pair (still one streaming pass, never a random index). The yielded
        ``timestamp_ns`` is the left image's header stamp.
        """
        if stride < 1:
            raise ValueError("stride must be >= 1")
        self._require_bag()
        ts = self._typestore
        tol = self.assoc_tol_ns
        lq: deque[tuple[int, np.ndarray]] = deque()
        rq: deque[tuple[int, np.ndarray]] = deque()
        pair_idx = 0
        with Reader(self.bag_path) as reader:
            conns = self._connections(reader, (LEFT_IMAGE_TOPIC, RIGHT_IMAGE_TOPIC))
            for conn, _t, raw in reader.messages(connections=conns):
                msg: Any = ts.deserialize_ros1(raw, conn.msgtype)
                stamp = _header_ns(msg)
                img = np.frombuffer(msg.data, np.uint8).reshape(msg.height, msg.width)
                (lq if conn.topic == LEFT_IMAGE_TOPIC else rq).append((stamp, img))
                # Two-pointer merge: each stream is monotonic, so the queue fronts are the global
                # minima of the remaining stamps -> the nearest match for a front is the other front.
                while lq and rq:
                    lt, limg = lq[0]
                    rt, rimg = rq[0]
                    if abs(lt - rt) <= tol:
                        lq.popleft()
                        rq.popleft()
                        if pair_idx % stride == 0:
                            yield lt, limg, rimg
                        pair_idx += 1
                    elif lt < rt:
                        lq.popleft()        # this left has no right within tol -> drop it
                    else:
                        rq.popleft()        # this right has no left within tol -> drop it

    def image_timestamps(self, side: str, *, limit: int | None = None) -> Iterator[int]:
        """Stream the header-stamp ns of one camera (``side`` in {'left','right'}), in time order.

        A lightweight accessor (no image decode buffering) for diagnostics / association analysis;
        ``limit`` caps how many are read so a test can early-break instead of scanning all ~33k."""
        if side not in _IMAGE_TOPIC:
            raise ValueError(f"side must be 'left' or 'right', got {side!r}")
        self._require_bag()
        ts = self._typestore
        topic = _IMAGE_TOPIC[side]
        n = 0
        with Reader(self.bag_path) as reader:
            conns = self._connections(reader, (topic,))
            for conn, _t, raw in reader.messages(connections=conns):
                msg: Any = ts.deserialize_ros1(raw, conn.msgtype)
                yield _header_ns(msg)
                n += 1
                if limit is not None and n >= limit:
                    return

    # ---- IMU (streamed) ---------------------------------------------------------------------------
    def imu(self) -> Iterator[tuple[int, np.ndarray, np.ndarray]]:
        """Stream ``/imu/data`` as ``(timestamp_ns, gyro_xyz, accel_xyz)``: angular velocity (rad/s)
        and linear acceleration (m/s^2), each a (3,) float array, in time order."""
        self._require_bag()
        ts = self._typestore
        with Reader(self.bag_path) as reader:
            conns = self._connections(reader, (IMU_TOPIC,))
            for conn, _t, raw in reader.messages(connections=conns):
                msg: Any = ts.deserialize_ros1(raw, conn.msgtype)
                w = msg.angular_velocity
                a = msg.linear_acceleration
                gyro = np.array([w.x, w.y, w.z], dtype=float)
                accel = np.array([a.x, a.y, a.z], dtype=float)
                yield _header_ns(msg), gyro, accel

    # ---- in-bag camera_info cross-check -----------------------------------------------------------
    def bag_intrinsics(self) -> tuple[Intrinsics, float]:
        """Read the FIRST in-bag ``camera_info`` of each side -> (left K as :class:`Intrinsics`,
        baseline from the right ``P[3] = -fx*baseline``). For cross-checking the Cfgs calibration
        against what the bag itself carries (they agree to the bag's ~6-dp rounding)."""
        self._require_bag()
        ts = self._typestore
        with Reader(self.bag_path) as reader:
            lconn = self._connections(reader, (LEFT_INFO_TOPIC,))
            left_K = None
            for conn, _t, raw in reader.messages(connections=lconn):
                m: Any = ts.deserialize_ros1(raw, conn.msgtype)
                left_K = np.asarray(m.K, dtype=float).reshape(3, 3)
                break
            rconn = self._connections(reader, (RIGHT_INFO_TOPIC,))
            right_P3 = None
            for conn, _t, raw in reader.messages(connections=rconn):
                m = ts.deserialize_ros1(raw, conn.msgtype)
                right_P3 = float(np.asarray(m.P, dtype=float)[3])
                break
        if left_K is None or right_P3 is None:
            raise KeyError("camera_info messages not found in bag")
        fx = float(left_K[0, 0])
        intr = Intrinsics(fx=fx, fy=float(left_K[1, 1]), cx=float(left_K[0, 2]), cy=float(left_K[1, 2]))
        baseline = -right_P3 / fx
        return intr, baseline

    def bag_time_span_ns(self) -> tuple[int, int]:
        """The bag's record-time span ``(start_ns, end_ns)`` (Unix-epoch ns; first/last message
        record time, which on this bag equals the first/last image header stamp)."""
        self._require_bag()
        with Reader(self.bag_path) as reader:
            return int(reader.start_time), int(reader.end_time)

    # ---- ground truth (SCORING ONLY -- invariant I3) ----------------------------------------------
    def gt_lle(self) -> tuple[np.ndarray, np.ndarray]:
        """Load global_lle.pos -> ``(timestamps_ns int64[N], lle float[N,3])`` where ``lle`` is
        ``[lat_deg, lon_deg, height_m]`` (WGS84-ELLIPSOIDAL). The calendar column (labelled GPST) is
        parsed as UTC -> Unix-epoch ns. SCORING ONLY (invariant I3)."""
        if not os.path.isfile(self.gt_path):
            raise FileNotFoundError(f"S3LI GT track not found: {self.gt_path}")
        ts_list: list[int] = []
        lle_list: list[list[float]] = []
        with open(self.gt_path) as f:
            for line in f:
                if line.startswith("%") or not line.strip():
                    continue
                p = line.split()
                t = _dt.datetime.strptime(p[0] + " " + p[1], "%Y/%m/%d %H:%M:%S.%f").replace(
                    tzinfo=_dt.timezone.utc
                )
                ts_list.append(int(round(t.timestamp() * 1e9)))
                lle_list.append([float(p[2]), float(p[3]), float(p[4])])
        return np.array(ts_list, dtype=np.int64), np.array(lle_list, dtype=float)

    def gt_enu(self, dem: "object | None" = None) -> tuple[np.ndarray, np.ndarray]:
        """GT positions in the local ENU frame of :class:`dart.s3li_dem.S3liDem` (so GT and the DEM
        prior share one frame) -> ``(timestamps_ns int64[N], enu float[N,3])`` (East, North, Up in
        metres). Pass a constructed ``S3liDem`` to reuse it; otherwise one is built on the default
        DEM tile (raises if the tile is absent). SCORING ONLY (invariant I3)."""
        if dem is None:
            from dart.s3li_dem import S3liDem

            dem = S3liDem()
        ts, lle = self.gt_lle()
        enu = dem.lle_to_enu(lle[:, 0], lle[:, 1], lle[:, 2]).T  # type: ignore[attr-defined]
        return ts, np.ascontiguousarray(enu, dtype=float)

    def time_alignment(self) -> TimeAlignment:
        """Report the bag record span vs the GT span and the constant offset between them (SCORING
        context; invariant I3). The offset is REPORTED, never silently applied: it is 0 when the GT
        window already covers the bag window by direct UTC conversion (the measured case -- the bag is
        nested inside the GT window), otherwise the midpoint shift that would align them."""
        bag_start, bag_end = self.bag_time_span_ns()
        gt_ts, _ = self.gt_lle()
        gt_start, gt_end = int(gt_ts[0]), int(gt_ts[-1])
        overlaps = gt_start <= bag_end and bag_start <= gt_end
        offset = 0 if overlaps else int((bag_start + bag_end) // 2 - (gt_start + gt_end) // 2)
        return TimeAlignment(
            bag_start_ns=bag_start,
            bag_end_ns=bag_end,
            gt_start_ns=gt_start,
            gt_end_ns=gt_end,
            overlaps=overlaps,
            offset_ns=offset,
        )
