"""Ingest the Katwijk Beach Planetary Rover Dataset (ESA, Hewitt et al. 2018) -> dart structures.

This provides the LOCKED VALIDATION CAPTURE that Gate G1 requires: a REAL run with timestamped wheel
odometry + IMU + DGPS ground truth on natural, GNSS-denied terrain (the closest public analog to an
IPEx surface traverse; no public IPEx flight telemetry exists). Run dart's SE(2) pose graph on the
wheel/IMU stream and score ATE/RPE vs the DGPS track.

Parsing is HEADER-DRIVEN: columns are matched by NAME, never by guessed position, so the exact column
order in the dataset's Table 5 cannot silently break it; pass `colmap` to override the aliases. The
loaders are REAL-DATA-GATED -- each takes a path into the downloaded dataset; NO Katwijk bytes are
bundled (ESA license + size). Download: https://robotics.estec.esa.int/datasets/katwijk-beach-11-2015/
"""
# PROVENANCE: STEWIE DART subsystem (A. Storey)
from __future__ import annotations

import csv
import os

import numpy as np

from stewie.sensors.imu_wheel import ImuSample, WheelOdomSample

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
                if h == a:        # EXACT match only: substring + single-letter aliases ('n' in "snr")
                    found = j; break   # silently bound WRONG columns (audit 2026-06-09)
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
    # exact-match alias sets, SAME as _resolve (audit M13): the old substring predicate missed a
    # valid 'east'/'north' header, mis-routing the file to the lat/lon branch -> spurious failure
    has_en = any(h in ("easting", "east", "x", "e") for h in low) and \
        any(h in ("northing", "north", "y", "n") for h in low)
    if has_en:
        idx = _resolve(header, ["easting", "northing"], colmap)
        return np.array([[float(r[idx["easting"]]), float(r[idx["northing"]])] for _, r in rows])
    idx = _resolve(header, ["lat", "lon"], colmap)
    latlon = np.array([[float(r[idx["lat"]]), float(r[idx["lon"]])] for _, r in rows])
    return gps_latlon_to_local_xy(latlon[:, 0], latlon[:, 1])


# ---- REAL-file parsers (2026-06-10): the roboshare files are HEADERLESS ------------------------
# Format authority: Hewitt et al. IJRR 2018 + de Jong (UvA, 2019) which documents the extra
# per-joint columns: imu.txt = ts + acc[xyz] + gyro[xyz] + inclinometer-acc[xyz] (Stim300, no
# magnetometer); odometry.txt = ts + 6 drive joints x (angular displacement, angular velocity,
# analogue encoder) + 4 steering joints x (same triple) + rocker + bogie_left + bogie_right [rad];
# gps-latlong.txt = ts + RTK status + lat + lon + alt + sd_north + sd_east + sd_up [m].
# Linear wheel conversion needs the HDPR wheel radius (wheelTransformation.m) -- NOT guessed here.

def parse_ts(s: str) -> float:
    """'YYYY_MM_DD_HH_MM_SS_mmm' -> POSIX seconds (UTC assumed per the dataset docs)."""
    import datetime as _dt
    p = s.split("_")
    if len(p) != 7:
        raise ValueError(f"bad Katwijk timestamp {s!r}")
    base = _dt.datetime(int(p[0]), int(p[1]), int(p[2]), int(p[3]), int(p[4]), int(p[5]),
                        tzinfo=_dt.timezone.utc).timestamp()
    # the real files carry ms values of 1000 on some rows (logger rollover quirk, e.g.
    # 2015_11_26_12_54_30_1000 in Part1/imu.txt) -- add as seconds-fraction rather than reject
    return base + int(p[6]) / 1000.0


def load_imu_real(path: str) -> list:
    """[{t, acc[3], gyro[3], incl_acc[3]}] from the headerless roboshare imu.txt."""
    out = []
    for ln in open(path):
        f = ln.split()
        if len(f) != 10:
            raise ValueError(f"imu.txt row has {len(f)} fields (want 10): {ln[:60]!r}")
        v = [float(x) for x in f[1:]]
        out.append({"t": parse_ts(f[0]), "acc": v[0:3], "gyro": v[3:6], "incl_acc": v[6:9]})
    if not out:
        raise ValueError("empty imu.txt")
    return out


def load_gps_real(path: str) -> list:
    """[{t, status, lat, lon, alt, sd_n, sd_e, sd_u}] from gps-latlong.txt (RTK ground truth)."""
    out = []
    for ln in open(path):
        f = ln.split()
        if len(f) != 8:
            raise ValueError(f"gps row has {len(f)} fields (want 8): {ln[:60]!r}")
        out.append({"t": parse_ts(f[0]), "status": f[1], "lat": float(f[2]), "lon": float(f[3]),
                    "alt": float(f[4]), "sd_n": float(f[5]), "sd_e": float(f[6]),
                    "sd_u": float(f[7])})
    if not out:
        raise ValueError("empty gps file")
    return out


def load_odometry_real(path: str) -> list:
    """[{t, drive_disp[6], drive_vel[6], steer_disp[4], rocker, bogie_l, bogie_r}] (angles, rad).

    Column binding per de Jong 2019: each of the 6 drive + 4 steering joints carries the triple
    (angular displacement, angular velocity, analogue encoder value); the analogue values are
    documented as accidental and are DISCARDED. Linear conversion awaits the HDPR wheel radius."""
    out = []
    for ln in open(path):
        f = ln.split()
        if len(f) != 34:
            raise ValueError(f"odometry row has {len(f)} fields (want 34): {ln[:60]!r}")
        v = [float(x) for x in f[1:]]
        triples = [v[i:i + 3] for i in range(0, 30, 3)]
        out.append({"t": parse_ts(f[0]),
                    "drive_disp": [tr[0] for tr in triples[:6]],
                    "drive_vel": [tr[1] for tr in triples[:6]],
                    "steer_disp": [tr[0] for tr in triples[6:10]],
                    "rocker": v[30], "bogie_l": v[31], "bogie_r": v[32]})
    if not out:
        raise ValueError("empty odometry file")
    return out
