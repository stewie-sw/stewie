"""Katwijk ingest adapter: header-driven CSV parsing (parser unit tests on in-memory CSV in the
documented format) + a real-data-gated integration check (skips without the downloaded dataset)."""
import os

import numpy as np
import pytest

from solnav.bridge import katwijk_io as kw


def _write(p, text):
    p.write_text(text); return str(p)


def test_imu_parser_header_driven(tmp_path):
    # documented-format columns; the parser maps by NAME, so column order is irrelevant
    p = _write(tmp_path / "imu.csv", "timestamp,acc_x,acc_y,acc_z,gyro_x,gyro_y,gyro_z\n"
                                     "0.00,0.1,0.2,9.8,0.0,0.0,0.05\n"
                                     "0.01,0.1,0.2,9.8,0.0,0.0,0.06\n")
    s = kw.load_katwijk_imu(p)
    assert len(s) == 2 and abs(s[0].gyro_z_rps - 0.05) < 1e-9
    assert np.allclose(s[1].accel_xy_mps2, [0.1, 0.2]) and s[0].provenance == "KATWIJK_REAL"


def test_wheel_parser_and_colmap_override(tmp_path):
    p = _write(tmp_path / "odom.csv", "t,fwd_speed,turn_rate\n0.0,0.30,0.01\n0.1,0.28,0.0\n")
    s = kw.load_katwijk_wheel(p, colmap={"v": ["fwd_speed"], "omega": ["turn_rate"]})
    assert len(s) == 2 and abs(s[0].v_mps - 0.30) < 1e-9 and abs(s[1].v_mps - 0.28) < 1e-9


def test_missing_column_raises(tmp_path):
    p = _write(tmp_path / "bad.csv", "time,foo,bar\n0.0,1,2\n")
    with pytest.raises(ValueError, match="not found"):
        kw.load_katwijk_imu(p)


def test_gps_latlon_to_local_xy_origin():
    xy = kw.gps_latlon_to_local_xy([52.20, 52.20], [4.40, 4.40])
    assert np.allclose(xy, 0.0, atol=1e-6)          # constant fix -> origin


def test_truth_latlon_projects(tmp_path):
    p = _write(tmp_path / "gps.csv", "time,latitude,longitude\n0,52.2000,4.4000\n1,52.2001,4.4000\n")
    xy = kw.load_katwijk_truth_xy(p)
    assert xy.shape == (2, 2) and xy[1, 1] > xy[0, 1]   # +latitude -> +north


# Real-data-gated integration: set KATWIJK_DIR to the downloaded dataset to actually run it.
_KW = os.environ.get("KATWIJK_DIR", "")


@pytest.mark.skipif(not (_KW and os.path.isdir(_KW)), reason="Katwijk dataset not downloaded")
def test_real_katwijk_traverse_loads():
    imu = kw.load_katwijk_imu(os.path.join(_KW, "imu.csv"))
    wheel = kw.load_katwijk_wheel(os.path.join(_KW, "wheel_odom.csv"))
    truth = kw.load_katwijk_truth_xy(os.path.join(_KW, "gps.csv"))
    assert len(imu) > 0 and len(wheel) > 0 and truth.shape[1] == 2
