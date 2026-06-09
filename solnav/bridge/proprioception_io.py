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
                         now_s: float | None = None, max_age_s: float = 1.0) -> dict:
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
           "imu": [], "wheel": [], "unavailable": []}

    ci = chans.get("imu", {})
    _allowed(ci, _CHAN_KEYS, "imu channel")
    if ci.get("status") == "OK":
        s = ci.get("samples") or []
        if not s:
            raise ValueError("imu status OK but no payload")
        for x in s:
            _allowed(x, _IMU_SAMPLE_KEYS, "imu sample")
        _monotonic([x["t"] for x in s], "imu")
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
    else:
        if cw.get("samples"):
            raise ValueError("wheel UNAVAILABLE but carries samples")
        out["unavailable"].append("wheel")

    for name in ("joints", "power"):
        c = chans.get(name, {})
        _allowed(c, _CHAN_KEYS, f"{name} channel")
        if c.get("status") == "OK" and not c.get("samples"):
            raise ValueError(f"{name} status OK without payload")
        if c.get("status") != "OK":
            out["unavailable"].append(name)

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
