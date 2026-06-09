"""A5: parse + validate the dustgym runtime proprioception packet (schema proprioception/1.x) into
solnav typed objects.

solnav owns parsing + time-sync + validation (the producer owns generation). Validation enforces:
strictly-monotonic per-channel timestamps; status<->payload consistency (OK requires a payload;
UNAVAILABLE must not carry samples); FINITENESS of every numeric field; covariance 4x4 SYMMETRY (no
silent symmetrization) and PSD; and a TRUTH FIREWALL (invariant I3) by BOTH a forbidden-key denylist and
a strict per-level ALLOW-LIST -- any key outside the declared schema (or any rover/lander/slip/ground-
truth key) is rejected, so a novel truth field cannot ride in. Returns solnav ImuSample/WheelSample lists.
"""
from __future__ import annotations

import json

import numpy as np

from ..sensors.imu_wheel import ImuSample, WheelSample

# I3 denylist (cheap belt-and-suspenders over the whole blob)
_FORBIDDEN = ("rover_pos", "rover_quat", "lander", "true_slip", "ground_truth",
              "pose_in_world", "terrain_truth")

# Strict allow-lists per nesting level (schema proprioception/1.x). Any key outside these is rejected.
_TOP = {"schema_version", "clock", "sequence_id", "channels"}
_CHAN_NAMES = {"imu", "wheel", "joints", "power"}
_CHAN_KEYS = {"status", "reason", "rate_hz", "units", "samples", "order", "provenance",
              "wheel_radius_m", "encoder_counts_per_rev", "config_revision"}
_IMU_SAMPLE_KEYS = {"t", "gyro_z", "accel_xy", "gyro_var", "accel_var"}
_WHEEL_SAMPLE_KEYS = {"t", "encoder_delta_rad", "encoder_count_delta", "covariance", "sample_ids"}

# Required SI unit identities per channel (A5 req 2: validate units; reject unit-mismatched fixtures).
_IMU_UNITS = {"gyro_z": "rad/s", "accel_xy": "m/s^2"}
_WHEEL_UNITS = {"encoder_delta": "rad", "encoder_count_delta": "count", "covariance": "rad^2"}
_JOINT_SAMPLE_KEYS = {"t", "arm_front_pitch_rad", "arm_back_pitch_rad", "chassis_lift_m", "camera_heights_m"}
_JOINT_UNITS = {"arm_pitch": "rad", "chassis_lift": "m", "camera_height": "m"}
_POWER_SAMPLE_KEYS = {"t", "voltage_v", "current_a", "power_w", "soc_frac"}
_POWER_UNITS = {"voltage": "V", "current": "A", "power": "W", "soc": "frac"}


def _monotonic(ts, name):
    a = np.asarray(ts, float)
    if a.size and np.any(np.diff(a) <= 0.0):
        raise ValueError(f"{name} timestamps are not strictly monotonic")


def _finite(value, name):
    a = np.asarray(value, float)
    if not np.all(np.isfinite(a)):
        raise ValueError(f"{name} has non-finite (NaN/Inf) values")
    return a


def _allowed(keys, allow, ctx):
    extra = set(keys) - allow
    if extra:
        raise ValueError(f"unexpected key(s) {sorted(extra)} in {ctx} (allow-list/I3 violation)")


def _check_units(declared, expected, ctx):
    if not declared:
        raise ValueError(f"{ctx} channel (status OK) is missing the required units declaration")
    for k, want in expected.items():
        got = declared.get(k)
        if got != want:
            raise ValueError(f"{ctx} unit mismatch for '{k}': expected '{want}', got {got!r}")


def parse_proprioception(packet: dict, *, sync_tolerance_s: float = 1.0,
                         now_s: float | None = None, max_age_s: float = 1.0,
                         expected_profile: str | None = None) -> dict:
    if not str(packet.get("schema_version", "")).startswith("proprioception/"):
        raise ValueError("not a proprioception packet")
    _allowed(packet, _TOP, "packet")
    blob = json.dumps(packet).lower()
    for k in _FORBIDDEN:
        if k in blob:
            raise ValueError(f"truth key '{k}' present in runtime packet (I3 violation)")
    chans = packet["channels"]
    _allowed(chans, _CHAN_NAMES, "channels")
    out = {"sequence_id": packet["sequence_id"], "clock": packet["clock"],
           "imu": [], "wheel": [], "joints": [], "power": [], "unavailable": []}

    ci = chans.get("imu", {})
    _allowed(ci, _CHAN_KEYS, "imu channel")
    if ci.get("status") == "OK":
        s = ci.get("samples") or []
        if not s:
            raise ValueError("imu status OK but no payload")
        for x in s:
            _allowed(x, _IMU_SAMPLE_KEYS, "imu sample")
        _monotonic([x["t"] for x in s], "imu")
        for x in s:                                   # I4: variances are covariances -> must be >= 0
            if float(x.get("gyro_var", 0.0)) < 0.0 or float(x.get("accel_var", 0.0)) < 0.0:
                raise ValueError("imu variance is negative (not a valid covariance)")
        out["imu"] = [ImuSample(
            t=_finite(x["t"], "imu.t").item(), gyro_z_rps=_finite(x["gyro_z"], "imu.gyro_z").item(),
            accel_xy_mps2=_finite(x["accel_xy"], "imu.accel_xy"),
            gyro_var=_finite(x.get("gyro_var", 0.0), "imu.gyro_var").item(),
            accel_var=_finite(x.get("accel_var", 0.0), "imu.accel_var").item()) for x in s]
        _check_units(ci.get("units"), _IMU_UNITS, "imu")
    else:
        if ci.get("samples"):
            raise ValueError("imu UNAVAILABLE but carries samples")
        out["unavailable"].append("imu")

    cw = chans.get("wheel", {})
    _allowed(cw, _CHAN_KEYS, "wheel channel")
    if cw.get("status") == "OK":
        s = cw.get("samples") or []
        if not s:
            raise ValueError("wheel status OK but no payload")
        for x in s:
            _allowed(x, _WHEEL_SAMPLE_KEYS, "wheel sample")
        _monotonic([x["t"] for x in s], "wheel")
        if cw.get("order") != ["LF", "RF", "LR", "RR"]:
            raise ValueError("wheel channel must declare four-wheel order LF,RF,LR,RR")
        wr, cpr = cw.get("wheel_radius_m"), cw.get("encoder_counts_per_rev")
        if wr is None or cpr is None:
            raise ValueError("wheel channel missing wheel_radius_m / encoder_counts_per_rev")
        for x in s:
            cov = np.asarray(x["covariance"], float)
            if cov.shape != (4, 4):
                raise ValueError("wheel covariance is not 4x4")
            if not np.all(np.isfinite(cov)):
                raise ValueError("wheel covariance has non-finite (NaN/Inf) values")
            if np.max(np.abs(cov - cov.T)) > 1e-9:           # explicit -- do NOT silently symmetrize
                raise ValueError("wheel covariance is not symmetric")
            if np.any(np.linalg.eigvalsh(cov) < -1e-9):
                raise ValueError("wheel covariance is not PSD")
            ed = _finite(x["encoder_delta_rad"], "wheel.encoder_delta_rad")
            if ed.shape != (4,):
                raise ValueError("wheel sample must carry four encoder deltas")
            out["wheel"].append(WheelSample(
                t=_finite(x["t"], "wheel.t").item(), encoder_delta_rad=ed,
                encoder_count_delta=np.asarray(x["encoder_count_delta"], int), covariance=cov,
                wheel_radius_m=float(wr), encoder_counts_per_rev=int(cpr),
                sample_ids=tuple(x.get("sample_ids", ())),
                config_revision=str(cw.get("config_revision", ""))))
        _check_units(cw.get("units"), _WHEEL_UNITS, "wheel")
        rev = str(cw.get("config_revision", ""))                  # profile/calibration identity (A5 req 2)
        if not rev:
            raise ValueError("wheel channel (status OK) missing config_revision (calibration identity)")
        if expected_profile is not None and rev != expected_profile:
            raise ValueError(f"wheel calibration profile mismatch: expected '{expected_profile}', got '{rev}'")
    else:
        if cw.get("samples"):
            raise ValueError("wheel UNAVAILABLE but carries samples")
        out["unavailable"].append("wheel")

    # joints: measured arm-joint channel (drum-arm pitches + posture-conditioned per-camera heights).
    cj = chans.get("joints", {})
    _allowed(cj, _CHAN_KEYS, "joints channel")
    if cj.get("status") == "OK":
        js = cj.get("samples") or []
        if not js:
            raise ValueError("joints status OK without payload")
        for x in js:
            _allowed(x, _JOINT_SAMPLE_KEYS, "joints sample")
        _monotonic([x["t"] for x in js], "joints")
        _check_units(cj.get("units"), _JOINT_UNITS, "joints")
        for x in js:
            _finite(x["t"], "joints.t")
            _finite(x["arm_front_pitch_rad"], "joints.arm_front_pitch_rad")
            _finite(x["arm_back_pitch_rad"], "joints.arm_back_pitch_rad")
            _finite(x.get("chassis_lift_m", 0.0), "joints.chassis_lift_m")
            ch = x.get("camera_heights_m", {})
            if not isinstance(ch, dict):
                raise ValueError("joints camera_heights_m must be a per-camera height map")
            for cam, h in ch.items():
                _finite(h, f"joints.camera_heights_m.{cam}")
            out["joints"].append(x)
    else:
        out["unavailable"].append("joints")

    # power: measured BMS telemetry (pack voltage/current/draw/SoC).
    cp = chans.get("power", {})
    _allowed(cp, _CHAN_KEYS, "power channel")
    if cp.get("status") == "OK":
        ps = cp.get("samples") or []
        if not ps:
            raise ValueError("power status OK without payload")
        for x in ps:
            _allowed(x, _POWER_SAMPLE_KEYS, "power sample")
        _monotonic([x["t"] for x in ps], "power")
        _check_units(cp.get("units"), _POWER_UNITS, "power")
        for x in ps:
            for k in ("t", "voltage_v", "current_a", "power_w", "soc_frac"):
                _finite(x[k], f"power.{k}")
            if not 0.0 <= float(x["soc_frac"]) <= 1.0:
                raise ValueError(f"power soc_frac out of [0,1]: {x['soc_frac']}")
            if float(x["voltage_v"]) < 0.0:
                raise ValueError("power voltage_v must be non-negative")
            out["power"].append(x)
    else:
        out["unavailable"].append("power")

    # cross-channel synchronization tolerance (A5 req 4: enforce, do not silently resample). Samples are
    # monotonic, so first/last are the window bounds; reject if the imu and wheel windows are disjoint
    # beyond tolerance.
    if out["imu"] and out["wheel"]:
        i0, i1 = out["imu"][0].t, out["imu"][-1].t
        w0, w1 = out["wheel"][0].t, out["wheel"][-1].t
        gap = max(0.0, max(i0, w0) - min(i1, w1))
        if gap > sync_tolerance_s:
            raise ValueError(f"imu/wheel windows unsynchronized: {gap:.3f}s gap exceeds "
                             f"{sync_tolerance_s}s tolerance (no silent resampling)")

    # staleness: against the consumer's runtime clock, the freshest sample must be recent enough
    # (reject rather than extrapolate stale data). Only enforced when the caller supplies now_s.
    if now_s is not None:
        for chan in ("imu", "wheel"):
            if out[chan]:
                age = now_s - out[chan][-1].t
                if age > max_age_s:
                    raise ValueError(f"{chan} channel is stale: freshest sample is {age:.3f}s old "
                                     f"(> {max_age_s}s); reject (no extrapolation)")
    return out
