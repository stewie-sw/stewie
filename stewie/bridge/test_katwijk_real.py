"""A8: the REAL roboshare Katwijk files parse with documented column bindings (no guessing).

Fixtures are the first 120 lines of the actual Traverse-1 Part1 files (real data, subsampled).
Format authority: Hewitt IJRR 2018 + de Jong (UvA 2019) for the undocumented extra columns.
"""
import os

from stewie.bridge import katwijk_io as kio

FIX = os.path.join(os.path.dirname(__file__), "tests", "fixtures", "katwijk")


def test_timestamps_parse_and_are_monotone():
    rows = kio.load_imu_real(os.path.join(FIX, "imu.txt"))
    ts = [r["t"] for r in rows]
    assert len(ts) == 120 and all(b > a for a, b in zip(ts, ts[1:]))
    assert abs((ts[1] - ts[0]) - 0.01) < 0.01            # ~100 Hz


def test_imu_physics_sanity_on_real_rows():
    rows = kio.load_imu_real(os.path.join(FIX, "imu.txt"))
    import math
    g = [math.sqrt(sum(a * a for a in r["acc"])) for r in rows]
    assert all(9.0 < x < 10.5 for x in g)                # static-ish: |acc| ~ 9.81
    assert all(abs(w) < 0.5 for r in rows for w in r["gyro"])


def test_gps_rtk_fixed_and_millimetre_sigmas():
    rows = kio.load_gps_real(os.path.join(FIX, "gps-latlong.txt"))
    assert all(r["status"] == "RTK_FIXED" for r in rows)
    assert all(52.0 < r["lat"] < 52.5 and 4.0 < r["lon"] < 4.8 for r in rows)   # Katwijk
    assert all(r["sd_n"] < 0.05 and r["sd_e"] < 0.05 for r in rows)             # cm-class truth


def test_odometry_structure_binds():
    rows = kio.load_odometry_real(os.path.join(FIX, "odometry.txt"))
    r0 = rows[0]
    assert len(r0["drive_disp"]) == 6 and len(r0["steer_disp"]) == 4
    assert all(abs(x) < 3.2 for x in (r0["rocker"], r0["bogie_l"], r0["bogie_r"]))
    ts = [r["t"] for r in rows]
    assert abs((ts[1] - ts[0]) - 0.08) < 0.08            # ~10-12 Hz
