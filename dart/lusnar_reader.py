"""Reader for the REAL LuSNAR lunar dataset (arXiv:2407.06512, zqyu9/ JeremyLuo/LuSNAR).

LuSNAR is a synthetic (Unreal Engine) multi-sensor lunar benchmark: per-scene STEREO cameras + dense
depth + semantic labels + a spinning LiDAR + IMU + a ground-truth trajectory. This module reads ONE
scene directory (e.g. ``Moon_1``) into the same calibration/iteration idiom the rest of DART uses
(cf. :class:`dart.stereo_vo.Intrinsics`), so the existing stereo/VO/mapping front ends consume it
unchanged.

DISCOVERED on-disk layout of an extracted scene (verified by inspecting the real Moon_1 bytes -- the
dataset README's idealised ``image1/image2`` + PNG-depth layout does NOT match what ships):

    Moon_1/
    |- image0/                 LEFT camera (the reference camera)
    |  |- color/  <stem>.png   1024x1024 RGBA uint8
    |  |- depth/  <stem>.pfm   1024x1024 float32, metres (sky = 65504.0 sentinel)
    |  '- label/  <stem>.png   1024x1024 RGB uint8, colour-coded semantic mask
    |- image1/                 RIGHT camera
    |  '- color/  <stem>.png   1024x1024 RGBA uint8  (no depth/label on the right)
    |- LiDAR/     <stem>.txt    per-frame point cloud "x,y,z,category"
    |             timestamp.txt per-frame LiDAR sensor world pose "ts,px,py,pz,qw,qx,qy,qz"
    |- gt.txt                  ground-truth trajectory, EuRoC RS_R CSV (see GtPose)
    '- imu.txt                 100 Hz IMU "ts,wx,wy,wz,ax,ay,az"

``<stem>`` is the nanosecond-epoch timestamp; the SAME stem indexes every modality. There is NO
per-scene calibration file: intrinsics + baseline come from the published sensor spec and are exposed
as module constants below (a CAMERA PROPERTY, not a ground-truth pose).

Truth firewall (invariant I3): this reader DOES load ground-truth poses (gt.txt) and ground-truth
geometry (depth, LiDAR). That is allowed here because the READER IS NOT THE ESTIMATOR -- it is the
data/scoring layer. ``LusnarFrame.pose`` and ``scene_dem`` are for SCORING / map-prior use only; the
firewall is enforced DOWNSTREAM where a frame is fed to a perception/SLAM front end, which must take
images (+ camera calibration) only and never a GT pose. Do not route ``frame.pose`` into an estimator.
"""
# PROVENANCE: STEWIE DART subsystem (A. Storey)
from __future__ import annotations

import glob
import math
import os
from dataclasses import dataclass

import numpy as np

# --- published LuSNAR sensor spec (README / arXiv:2407.06512); no per-scene calib file on disk ------
LUSNAR_IMAGE_SIZE = 1024
LUSNAR_FOV_DEG = 80.0
# Focal length the dataset reports (610.17784 px); it is exactly the pinhole focal of the 80 deg FOV
# at 1024 px: (1024/2)/tan(40 deg) = 610.18. Square pixels, principal point at the image centre.
LUSNAR_FOCAL_PX = 610.17784
LUSNAR_BASELINE_M = 0.310          # stereo baseline, README "Baseline 310 mm"
# Sky / no-surface pixels in the .pfm depth carry the FP16-max value, not a real range.
LUSNAR_SKY_DEPTH_SENTINEL = 65504.0
# documented 3D point-cloud label ids: -1 regolith, 0 crater, 174 rock
LUSNAR_LIDAR_LABELS = (-1, 0, 174)

_LEFT_DIR = "image0"
_RIGHT_DIR = "image1"


@dataclass(frozen=True)
class LusnarIntrinsics:
    """Pinhole intrinsics for a LuSNAR camera (square pixels, principal point at the image centre)."""

    fx: float
    fy: float
    cx: float
    cy: float
    width: int
    height: int

    def matrix(self) -> np.ndarray:
        """The 3x3 camera intrinsic matrix K."""
        return np.array(
            [[self.fx, 0.0, self.cx], [0.0, self.fy, self.cy], [0.0, 0.0, 1.0]], dtype=float
        )


LUSNAR_INTRINSICS = LusnarIntrinsics(
    fx=LUSNAR_FOCAL_PX, fy=LUSNAR_FOCAL_PX,
    cx=LUSNAR_IMAGE_SIZE * 0.5, cy=LUSNAR_IMAGE_SIZE * 0.5,
    width=LUSNAR_IMAGE_SIZE, height=LUSNAR_IMAGE_SIZE,
)


@dataclass(frozen=True)
class GtPose:
    """One ground-truth pose (EVAL/SCORING ONLY -- invariant I3).

    From gt.txt, EuRoC RS_R format: ``position_m`` (3,) metres and ``quaternion_wxyz`` (4,) the
    Hamilton quaternion (q_w, q_x, q_y, q_z) of the body (R) frame in the world (sensor/reference S)
    frame. gt.txt also carries velocity + gyro/accel biases, kept on the row but not needed for pose.
    """

    timestamp_ns: int
    position_m: np.ndarray
    quaternion_wxyz: np.ndarray

    def rotation_matrix(self) -> np.ndarray:
        """3x3 rotation from the unit quaternion (q_w, q_x, q_y, q_z)."""
        q = np.asarray(self.quaternion_wxyz, dtype=float)
        n = np.linalg.norm(q)
        if n == 0.0:
            raise ValueError("zero-norm quaternion has no rotation")
        w, x, y, z = q / n
        return np.array([
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ], dtype=float)

    def matrix(self) -> np.ndarray:
        """4x4 homogeneous SE(3) transform (rotation + translation)."""
        T = np.eye(4)
        T[:3, :3] = self.rotation_matrix()
        T[:3, 3] = np.asarray(self.position_m, dtype=float)
        return T


@dataclass(frozen=True)
class LusnarFrame:
    """One synchronized LuSNAR frame. ``left`` is the reference (image0) camera; ``right`` (image1) is
    the stereo partner. ``depth_m`` is the left-camera metric depth (sky = ``LUSNAR_SKY_DEPTH_SENTINEL``).
    ``pose`` is the ground-truth pose nearest this frame's timestamp (EVAL ONLY -- invariant I3)."""

    timestamp_ns: int
    left: np.ndarray
    right: np.ndarray | None
    depth_m: np.ndarray
    label_rgb: np.ndarray
    intrinsics: LusnarIntrinsics
    baseline_m: float
    pose: GtPose | None


def read_pfm(path: str) -> np.ndarray:
    """Read a (grayscale or colour) PFM file into a float32 array.

    LuSNAR depth is grayscale ``Pf`` with scale ``-1`` (little-endian). PFM stores rows bottom-to-top,
    so the raster is flipped vertically to row-major (top-to-bottom) to match the colour image."""
    with open(path, "rb") as f:
        header = f.readline().decode("ascii").rstrip()
        if header not in ("PF", "Pf"):
            raise ValueError(f"{path!r} is not a PFM file (header {header!r})")
        color = header == "PF"
        dims = f.readline().decode("ascii").split()
        width, height = int(dims[0]), int(dims[1])
        scale = float(f.readline().decode("ascii").rstrip())
        endian = "<" if scale < 0 else ">"
        channels = 3 if color else 1
        count = width * height * channels
        data = np.frombuffer(f.read(count * 4), dtype=endian + "f4").astype(np.float32)
    data = data.reshape((height, width, channels)) if color else data.reshape((height, width))
    return np.flipud(data).copy()


def _read_image(path: str) -> np.ndarray:
    from imageio.v3 import imread
    return np.asarray(imread(path))


class LusnarReader:
    """Frame-iterable reader over one extracted LuSNAR scene directory.

    Discovers frames from ``image0/color/*.png`` (the reference camera) and matches each frame's
    ground-truth pose by nearest gt.txt timestamp. Iterating yields :class:`LusnarFrame`.
    """

    def __init__(
        self,
        scene_dir: str,
        *,
        require_right: bool = True,
        require_depth: bool = True,
        require_pose: bool = True,
        pose_match_tol_ns: int = 5_000_000,
    ) -> None:
        if not os.path.isdir(scene_dir):
            raise FileNotFoundError(f"LuSNAR scene dir not found: {scene_dir}")
        self.scene_dir = scene_dir
        self.require_right = require_right
        self.require_depth = require_depth
        self.require_pose = require_pose
        self.pose_match_tol_ns = int(pose_match_tol_ns)
        self.intrinsics = LUSNAR_INTRINSICS
        self.baseline_m = LUSNAR_BASELINE_M

        color_glob = os.path.join(scene_dir, _LEFT_DIR, "color", "*.png")
        stems = sorted(
            (os.path.splitext(os.path.basename(p))[0] for p in glob.glob(color_glob)),
            key=int,
        )
        if not stems:
            raise FileNotFoundError(f"no left-camera frames under {color_glob}")
        self._stems = stems
        self._ts = np.array([int(s) for s in stems], dtype=np.int64)

        gt_path = os.path.join(scene_dir, "gt.txt")
        if os.path.isfile(gt_path):
            self._gt_ts, self._gt_pos, self._gt_quat = _load_gt(gt_path)
        else:
            if require_pose:
                raise FileNotFoundError(f"ground-truth gt.txt not found in {scene_dir}")
            self._gt_ts = np.empty(0, dtype=np.int64)
            self._gt_pos = np.empty((0, 3))
            self._gt_quat = np.empty((0, 4))

    def __len__(self) -> int:
        return len(self._stems)

    @property
    def stems(self) -> list[str]:
        """The ns-epoch filename stems, one per frame, in time order."""
        return list(self._stems)

    @property
    def timestamps(self) -> list[int]:
        """The ns-epoch timestamps, one per frame, strictly increasing."""
        return [int(t) for t in self._ts]

    def _path(self, sub: tuple[str, ...], stem: str, ext: str) -> str:
        return os.path.join(self.scene_dir, *sub, stem + ext)

    def pose(self, index: int) -> GtPose | None:
        """Ground-truth pose nearest this frame's timestamp (EVAL ONLY -- invariant I3).

        Raises if the nearest gt.txt timestamp is farther than ``pose_match_tol_ns`` (an honest
        failure rather than a silently mismatched pose). Returns None only when poses were not required
        and gt.txt is absent."""
        if self._gt_ts.size == 0:
            if self.require_pose:
                raise FileNotFoundError("no ground-truth poses loaded")
            return None
        ts = int(self._ts[index])
        j = int(np.searchsorted(self._gt_ts, ts))
        cand = [k for k in (j - 1, j) if 0 <= k < self._gt_ts.size]
        k = min(cand, key=lambda c: abs(int(self._gt_ts[c]) - ts))
        delta = abs(int(self._gt_ts[k]) - ts)
        if delta > self.pose_match_tol_ns:
            raise ValueError(
                f"no GT pose within {self.pose_match_tol_ns} ns of frame {ts} (nearest off by {delta} ns)"
            )
        return GtPose(timestamp_ns=int(self._gt_ts[k]),
                      position_m=self._gt_pos[k].copy(),
                      quaternion_wxyz=self._gt_quat[k].copy())

    def frame(self, index: int) -> LusnarFrame:
        """Load the synchronized :class:`LusnarFrame` at ``index``."""
        stem = self._stems[index]
        left = _read_image(self._path((_LEFT_DIR, "color"), stem, ".png"))

        right: np.ndarray | None = None
        right_path = self._path((_RIGHT_DIR, "color"), stem, ".png")
        if os.path.isfile(right_path):
            right = _read_image(right_path)
        elif self.require_right:
            raise FileNotFoundError(f"right-camera frame missing: {right_path}")

        depth_path = self._path((_LEFT_DIR, "depth"), stem, ".pfm")
        if os.path.isfile(depth_path):
            depth = read_pfm(depth_path)
        elif self.require_depth:
            raise FileNotFoundError(f"depth frame missing: {depth_path}")
        else:
            depth = np.empty((0, 0), dtype=np.float32)

        label_path = self._path((_LEFT_DIR, "label"), stem, ".png")
        label = _read_image(label_path) if os.path.isfile(label_path) else np.empty((0, 0, 3), np.uint8)

        return LusnarFrame(
            timestamp_ns=int(self._ts[index]),
            left=left,
            right=right,
            depth_m=depth,
            label_rgb=label,
            intrinsics=self.intrinsics,
            baseline_m=self.baseline_m,
            pose=self.pose(index) if self._gt_ts.size else None,
        )

    def __iter__(self):
        for i in range(len(self)):
            yield self.frame(i)

    # ---- ground-truth geometry (SCORING / map-prior; invariant I3 -- not an estimator input) --------
    def lidar_points(self, index: int) -> np.ndarray:
        """The GT LiDAR cloud for this frame as (N, 4) ``[x, y, z, category]`` in the LiDAR frame."""
        stem = self._stems[index]
        path = self._path(("LiDAR",), stem, ".txt")
        return np.loadtxt(path, delimiter=",", dtype=np.float64).reshape(-1, 4)

    def lidar_sensor_pose(self, index: int) -> GtPose | None:
        """Per-frame LiDAR sensor WORLD pose from ``LiDAR/timestamp.txt`` (keyed exactly to the frame
        stem). Used to place per-frame clouds into a common world frame for :meth:`scene_dem`. Returns
        None if the index file is absent."""
        idx_path = self._path(("LiDAR",), "timestamp", ".txt")
        if not os.path.isfile(idx_path):
            return None
        if not hasattr(self, "_lidar_pose"):
            self._lidar_pose = _load_lidar_pose_index(idx_path)
        stem = self._stems[index]
        rec = self._lidar_pose.get(stem)
        if rec is None:
            return None
        return GtPose(timestamp_ns=int(stem), position_m=rec[0:3].copy(), quaternion_wxyz=rec[3:7].copy())

    def depth_to_points(self, depth_m: np.ndarray) -> np.ndarray:
        """Back-project a left-camera depth map to an (M, 3) camera-frame point cloud (x right, y down,
        z forward), dropping sky / sentinel pixels. A depth-derived surface sampling."""
        d = np.asarray(depth_m, dtype=np.float64)
        h, w = d.shape
        fx, fy = self.intrinsics.fx, self.intrinsics.fy
        cx, cy = self.intrinsics.cx, self.intrinsics.cy
        vv, uu = np.mgrid[0:h, 0:w]
        valid = (d > 0.0) & (d < LUSNAR_SKY_DEPTH_SENTINEL) & np.isfinite(d)
        z = d[valid]
        x = (uu[valid] - cx) * z / fx
        y = (vv[valid] - cy) * z / fy
        return np.stack([x, y, z], axis=1)

    def scene_dem(
        self,
        indices=None,
        *,
        cell_m: float = 0.5,
        source: str = "lidar",
        world: bool = True,
    ):
        """Build a 2.5-D ground-truth elevation grid (DEM map prior) by binning GT points by max height.

        ``source="lidar"`` accumulates the per-frame LiDAR clouds; when ``world=True`` each cloud is
        transformed into the common world frame by its :meth:`lidar_sensor_pose` so multiple frames
        overlay consistently (verified: consecutive clouds register to ~1 mm). Returns
        ``(Z, cell_m, x0, y0)`` where ``Z[r, c]`` is the max elevation (NaN where unobserved) of the
        cell whose corner is ``(x0 + c*cell_m, y0 + r*cell_m)``. SCORING / map-prior use only
        (invariant I3) -- never an estimator input."""
        if indices is None:
            indices = range(len(self))
        if source != "lidar":
            raise ValueError(f"unsupported DEM source {source!r} (only 'lidar')")
        clouds = []
        for i in indices:
            pc = self.lidar_points(i)[:, :3]
            if world:
                sp = self.lidar_sensor_pose(i)
                if sp is None:
                    raise FileNotFoundError("world=True needs LiDAR/timestamp.txt sensor poses")
                pc = (sp.rotation_matrix() @ pc.T).T + sp.position_m
            clouds.append(pc)
        pts = np.concatenate(clouds, axis=0)
        x0, y0 = float(pts[:, 0].min()), float(pts[:, 1].min())
        cols = np.floor((pts[:, 0] - x0) / cell_m).astype(int)
        rows = np.floor((pts[:, 1] - y0) / cell_m).astype(int)
        nrows, ncols = int(rows.max()) + 1, int(cols.max()) + 1
        Z = np.full((nrows, ncols), np.nan, dtype=float)
        # max elevation per cell (np.maximum.at accumulates a per-cell reduction)
        flat = rows * ncols + cols
        order = np.argsort(flat)
        flat_s, z_s = flat[order], pts[order, 2]
        uniq, start = np.unique(flat_s, return_index=True)
        seg_max = np.maximum.reduceat(z_s, start)
        Z.flat[uniq] = seg_max
        return Z, cell_m, x0, y0


def _load_gt(path: str):
    """Parse gt.txt (EuRoC RS_R CSV) -> (ts int64[N], pos float[N,3], quat_wxyz float[N,4]).

    Timestamps are read as integers from the raw text (np.loadtxt's float64 would lose ns precision)."""
    ts: list[int] = []
    pos: list[list[float]] = []
    quat: list[list[float]] = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(",")
            ts.append(int(parts[0]))
            pos.append([float(parts[1]), float(parts[2]), float(parts[3])])
            quat.append([float(parts[4]), float(parts[5]), float(parts[6]), float(parts[7])])
    return np.array(ts, dtype=np.int64), np.array(pos, dtype=float), np.array(quat, dtype=float)


def _load_lidar_pose_index(path: str) -> dict[str, np.ndarray]:
    """Parse LiDAR/timestamp.txt -> {stem: [px,py,pz,qw,qx,qy,qz]} keyed by the exact frame stem."""
    out: dict[str, np.ndarray] = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(",")
            out[parts[0]] = np.array([float(v) for v in parts[1:8]], dtype=float)
    return out


def intrinsics_consistency_check() -> bool:
    """True iff the published focal equals the pinhole focal of the FOV (a calibration self-check)."""
    expected = (LUSNAR_IMAGE_SIZE * 0.5) / math.tan(math.radians(LUSNAR_FOV_DEG) * 0.5)
    return abs(LUSNAR_FOCAL_PX - expected) < 0.01
