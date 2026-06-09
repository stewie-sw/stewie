"""Canonical single-clock Dustgym runtime packet (P0-3 / G1.A6).

Unifies the REAL sub-producers onto ONE monotonic clock + sequence id:
  - camera     : the Godot camera egress (frames + poses/intrinsics) -- passed in as a channel dict
  - imu, wheel : the Python proprioception producer (proprioception.runtime_proprioception_packet)
  - joints     : the MEASURED drum-arm angles -> posture-conditioned per-camera extrinsics
                 (posture_kinematics) -- AVAILABLE because the posture system models the joints
  - power      : measured BMS telemetry (pack voltage/current/draw/SoC) from the ipex_specs battery
                 model + a supplied instantaneous draw and SoC -- AVAILABLE via power_channel

This is an honest MERGER: it invents no data, and it REJECTS sub-packets whose clock or sequence id
disagree (the P0-3 guarantee that camera + IMU + wheel + joints are truly on one clock). Truth stays on
the separate eval channel (I3); this packet carries no pose/slip/terrain truth.
"""
from __future__ import annotations

from terrain_authority import ipex_specs as specs
from terrain_authority import posture_kinematics as pk


def joint_channel(arm_front_pitch_rad: float, arm_back_pitch_rad: float, *, t: float,
                  slope_along_rad: float = 0.0, slope_cross_rad: float = 0.0) -> dict:
    """Measured arm-joint channel: the two drum-arm pitches + the posture-conditioned per-camera heights
    (forward kinematics). Real -- the rover commands/measures these joints; no truth pose."""
    return {
        "status": "OK",
        "units": {"arm_pitch": "rad", "chassis_lift": "m", "camera_height": "m"},
        "samples": [{
            "t": float(t),
            "arm_front_pitch_rad": float(arm_front_pitch_rad),
            "arm_back_pitch_rad": float(arm_back_pitch_rad),
            "chassis_lift_m": pk.chassis_lift_m(arm_front_pitch_rad, arm_back_pitch_rad),
            "camera_heights_m": pk.camera_heights_m(arm_front_pitch_rad, arm_back_pitch_rad,
                                                    slope_along_rad, slope_cross_rad),
        }],
        "provenance": "SIMULATED_MEASURED_JOINT",
    }


def power_channel(power_w: float, soc_frac: float, *, t: float, voltage_v: float | None = None) -> dict:
    """Measured battery/BMS telemetry: pack voltage + current + instantaneous draw + state of charge.
    Voltage defaults to the 12S Li-ion nominal (ipex_specs); current = power / voltage. Real BMS sensing
    (the rover measures its own pack) -- no pose/terrain truth. The caller supplies the instantaneous draw
    (from drive/dig activity, e.g. ipex_specs.drive_power_w/dig_power_w) and the SoC (from the autonomy
    battery belief); this emitter does not fabricate them."""
    v = float(voltage_v) if voltage_v is not None else specs.BATTERY_SERIES_CELLS * specs.LIION_NOMINAL_V_PER_CELL
    return {
        "status": "OK",
        "units": {"voltage": "V", "current": "A", "power": "W", "soc": "frac"},
        "samples": [{
            "t": float(t),
            "voltage_v": v,
            "current_a": float(power_w) / v if v else 0.0,
            "power_w": float(power_w),
            "soc_frac": float(soc_frac),
        }],
        "provenance": "SIMULATED_BMS",
    }


def canonical_runtime_packet(proprio_packet: dict, camera_channel: dict, *,
                             joints: dict | None = None, sequence_id: int | None = None) -> dict:
    """Unify the proprioception packet + the camera channel (+ optional measured joints) onto one clock
    and sequence id. Rejects if the camera and proprioception clocks or sequence ids disagree."""
    clock = proprio_packet["clock"]
    cam_clock = camera_channel.get("clock", clock)
    if cam_clock != clock:
        raise ValueError(f"camera clock {cam_clock!r} != proprioception clock {clock!r} -- not one canonical clock")
    seq = int(sequence_id if sequence_id is not None else proprio_packet["sequence_id"])
    if int(proprio_packet["sequence_id"]) != seq:
        raise ValueError(f"proprioception sequence_id {proprio_packet['sequence_id']} != {seq} -- "
                         "sequences disagree (audit 2026-06-09: the override skipped this check)")
    cam_seq = camera_channel.get("sequence_id", seq)
    if int(cam_seq) != seq:
        raise ValueError(f"camera sequence_id {cam_seq} != proprioception {seq} -- sequences disagree")
    channels = dict(proprio_packet["channels"])                  # imu, wheel, joints(unavail), power(unavail)
    channels["camera"] = {"status": "OK",
                          **{k: v for k, v in camera_channel.items() if k not in ("clock", "sequence_id")}}
    if joints is not None:
        jt = [smp.get("t") for smp in joints.get("samples", [])]
        if jt and (min(jt) < 0.0):
            raise ValueError("joints sample timestamps must be on the canonical non-negative clock")
        j_clock = joints.get("clock", clock)
        if j_clock != clock:
            # audit M04: joints merged with ZERO clock validation, contradicting the one-clock contract
            raise ValueError(f"joints clock {j_clock!r} != canonical clock {clock!r}")
        channels["joints"] = joints                              # measured joints now AVAILABLE
    return {"schema_version": "dustgym_runtime/1.0", "clock": clock, "sequence_id": seq, "channels": channels}
