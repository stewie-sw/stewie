"""Ingest the Katwijk Beach Planetary Rover Dataset (ESA, Hewitt et al. 2018) -> solnav structures.

This provides the LOCKED VALIDATION CAPTURE that Gate G1 requires: a REAL run with timestamped wheel
odometry + IMU + DGPS ground truth on natural, GNSS-denied terrain (the closest public analog to an
IPEx surface traverse; no public IPEx flight telemetry exists). Run solnav's SE(2) pose graph on the
wheel/IMU stream and score ATE/RPE vs the DGPS track.

Parsing is HEADER-DRIVEN: columns are matched by NAME, never by guessed position, so the exact column
order in the dataset's Table 5 cannot silently break it; pass `colmap` to override the aliases. The
loaders are REAL-DATA-GATED -- each takes a path into the downloaded dataset; NO Katwijk bytes are
bundled (ESA license + size). Download: https://robotics.estec.esa.int/datasets/katwijk-beach-11-2015/
"""
from __future__ import annotations

import csv
import os

import numpy as np

from ..sensors.imu_wheel import ImuSample, WheelOdomSample

# Header ALIASES (lowercased substring match). Confirm/extend against the dataset README at download.
_ALIASES = {
    "time": ["timestamp", "time", "sec", "t"],
    "gyro_z": ["gyro_z", "gyroz", "gz", "wz", "angular_z", "yaw_rate"],
    "acc_x": ["acc_x", "accel_x", "ax"],
    "acc_y": ["acc_y", "accel_y", "ay"],
    "v": ["wheel_v", "odom_v", "velocity", "speed", "v"],
    "omega": ["omega", "yaw_rate", "angular_z", "w"],
    "lat": ["latitude", "lat"],
    "lon": ["longitude", "lon", "lng"],
    "easting": ["easting", "east", "x", "e"],
    "northing": ["northing", "north", "y", "n"],
}


def _resolve(header: list, fields: list, colmap: dict | None) -> dict:
    cm = dict(_ALIASES); cm.update(colmap or {})
    low = [h.strip().lower() for h in header]
    idx = {}
    for f in fields:
        aliases = cm.get(f, [f]) if isinstance(cm.get(f, [f]), list) else [cm[f]]
        found = None
        for a in aliases:
            for j, h in enumerate(low):
                if h == a or a in h:
                    found = j; break
            if found is not None:
                break
        if found is None:
            raise ValueError(f"Katwijk column for '{f}' not found in header {header}; "
                             "pass colmap={'%s': ['<real name>']}" % f)
        idx[f] = found
    return idx


def _rows(path: str):
    with open(path, newline="") as fh:
        r = csv.reader(fh)
        header = next(r)
        for row in r:
            if row:
                yield header, row


def load_katwijk_imu(path: str, colmap: dict | None = None) -> list:
    """Parse the Katwijk IMU log -> [ImuSample] (yaw-rate gyro + planar accel)."""
    if not os.path.exists(path):
        raise FileNotFoundError(f"Katwijk IMU log not present: {path} (download the dataset)")
    out, idx = [], None
    for header, row in _rows(path):
        if idx is None:
            idx = _resolve(header, ["time", "gyro_z", "acc_x", "acc_y"], colmap)
        out.append(ImuSample(t=float(row[idx["time"]]), gyro_z_rps=float(row[idx["gyro_z"]]),
                             accel_xy_mps2=np.array([float(row[idx["acc_x"]]), float(row[idx["acc_y"]])]),
                             provenance="KATWIJK_REAL"))
    return out


def load_katwijk_wheel(path: str, colmap: dict | None = None) -> list:
    """Parse the Katwijk wheel-odometry log -> [WheelOdomSample] (forward speed + yaw rate)."""
    if not os.path.exists(path):
        raise FileNotFoundError(f"Katwijk wheel-odometry log not present: {path}")
    out, idx = [], None
    for header, row in _rows(path):
        if idx is None:
            idx = _resolve(header, ["time", "v", "omega"], colmap)
        out.append(WheelOdomSample(t=float(row[idx["time"]]), v_mps=float(row[idx["v"]]),
                                   omega_rps=float(row[idx["omega"]]), provenance="KATWIJK_REAL"))
    return out


def gps_latlon_to_local_xy(lat_deg, lon_deg) -> np.ndarray:
    """Equirectangular projection to local ENU metres about the mean fix (adequate over ~1 km)."""
    lat = np.asarray(lat_deg, float); lon = np.asarray(lon_deg, float)
    lat0, lon0 = lat.mean(), lon.mean()
    R = 6378137.0
    east = np.radians(lon - lon0) * R * np.cos(np.radians(lat0))
    north = np.radians(lat - lat0) * R
    return np.column_stack([east, north])


def load_katwijk_truth_xy(path: str, colmap: dict | None = None) -> np.ndarray:
    """Parse the DGPS ground truth -> local ENU xy (metres) for ATE/RPE scoring. Accepts either
    lat/lon or pre-projected easting/northing columns."""
    if not os.path.exists(path):
        raise FileNotFoundError(f"Katwijk DGPS truth not present: {path}")
    rows = list(_rows(path))
    if not rows:
        raise ValueError("empty DGPS file")
    header = rows[0][0]
    low = [h.strip().lower() for h in header]
    has_en = any("easting" in h or h in ("x", "e") for h in low) and \
        any("northing" in h or h in ("y", "n") for h in low)
    if has_en:
        idx = _resolve(header, ["easting", "northing"], colmap)
        return np.array([[float(r[idx["easting"]]), float(r[idx["northing"]])] for _, r in rows])
    idx = _resolve(header, ["lat", "lon"], colmap)
    latlon = np.array([[float(r[idx["lat"]]), float(r[idx["lon"]])] for _, r in rows])
    return gps_latlon_to_local_xy(latlon[:, 0], latlon[:, 1])
