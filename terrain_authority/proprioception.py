"""Proprioception sensor GENERATION (IMU + four-wheel encoders) for the dustgym physics authority.

Per the solnav/dustgym ownership split (STANFORD_LITERATURE_ARCHITECTURE_DIFF_2026-06-08): DUSTGYM owns
sensor generation and synchronized publication; solnav owns parsing, time-sync, derived odometry, and
estimation. This module is the GENERATION side: given the true body twist + hidden per-wheel slip from
the conserved physics, it emits noisy/quantized sensor samples. Truth (pose/slip/terrain) is NEVER on a
sample (invariant I3); every sample carries covariance (I4).

Parameters are SOURCED, not invented (terrain_authority/data/imu_wheel_params.json): XSENS MTi-10 output
specs for IMU noise; 12-bit encoder counts/rev [ASSUMPTION]; MER design-goal slip band. Moved here from
solnav (the producer owns the sensor model); solnav now consumes the published samples.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

import numpy as np

_G = 9.80665e-6   # micro-g to m/s^2
_PARAMS_PATH = os.path.join(os.path.dirname(__file__), "data", "imu_wheel_params.json")


def load_params(path: str = _PARAMS_PATH) -> dict:
    with open(path) as f:
        return json.load(f)


@dataclass
class ImuSample:
    t: float
    gyro_z_rps: float                 # yaw rate [rad/s]
    accel_xy_mps2: np.ndarray         # planar specific force [m/s^2]
    gyro_var: float = 0.0             # measurement variance [rad/s]^2 (I4)
    accel_var: float = 0.0            # per-axis measurement variance [m/s^2]^2 (I4)
    provenance: str = "SIMULATED_SENSOR"


@dataclass
class WheelSample:
    """Raw four-wheel encoder observation (order LF, RF, LR, RR). The encoder measures WHEEL rotation,
    so under slip it over-reads ground motion; slip is NOT a field (I3)."""
    t: float
    encoder_delta_rad: np.ndarray         # (4,) quantized per-wheel rotation since last sample
    encoder_count_delta: np.ndarray       # (4,) integer count deltas
    covariance: np.ndarray                # (4,4) quantization covariance (I4)
    wheel_radius_m: float
    encoder_counts_per_rev: int
    sample_ids: tuple                     # lineage (I10)
    config_revision: str
    covariance_calibrated: bool = False
    provenance: str = "SIMULATED_SENSOR"


@dataclass
class WheelOdomSample:
    t: float
    v_mps: float                      # encoder-derived body forward speed (over-reads under slip)
    omega_rps: float                  # yaw rate DERIVED from noisy differential wheel encoders
    v_var: float = 0.0
    omega_var: float = 0.0
    provenance: str = "SIMULATED_SENSOR"


@dataclass
class ImuWheelModel:
    """Stateful sensor generator (the Gauss-Markov biases persist across steps)."""
    params: dict = field(default_factory=load_params)
    seed: int = 0

    def __post_init__(self):
        self.rng = np.random.default_rng(self.seed)
        g = self.params["imu"]["gyro"]; a = self.params["imu"]["accel"]; bm = self.params["imu"]["bias_model"]
        rate = float(self.params["imu"]["rate_hz"])
        self.dt = 1.0 / rate
        self.gyro_sigma = np.radians(float(g["noise_density_dps_per_sqrtHz"])) * np.sqrt(rate)
        self.accel_sigma = float(a["noise_density_ug_per_sqrtHz"]) * _G * np.sqrt(rate)
        self.gyro_bias_ss = np.radians(float(g["in_run_bias_stability_dps"]))
        self.accel_bias_ss = float(a["in_run_bias_stability_mps2"])
        tau = float(bm["correlation_time_s"])
        self._a = np.exp(-self.dt / tau); self._q = np.sqrt(1.0 - self._a ** 2)
        self._gyro_bias = 0.0; self._accel_bias = np.zeros(2)
        self.track_m = float(self.params["platform"]["track_m"])
        self.wheel_radius_m = float(self.params["platform"]["wheel_radius_m"])
        self.cpr = int(self.params["wheel_odometry"]["encoder_counts_per_rev"])
        self.config_revision = str(self.params.get("date", "unknown"))
        self._wheel_seq = 0

    def step_imu(self, t: float, true_yaw_rate_rps: float, true_accel_xy=(0.0, 0.0)) -> ImuSample:
        self._gyro_bias = self._a * self._gyro_bias + self._q * self.gyro_bias_ss * self.rng.normal()
        self._accel_bias = self._a * self._accel_bias + self._q * self.accel_bias_ss * self.rng.normal(size=2)
        gyro = true_yaw_rate_rps + self._gyro_bias + self.rng.normal(0.0, self.gyro_sigma)
        accel = np.asarray(true_accel_xy, float) + self._accel_bias + self.rng.normal(0.0, self.accel_sigma, size=2)
        return ImuSample(t=float(t), gyro_z_rps=float(gyro), accel_xy_mps2=accel,
                         gyro_var=float(self.gyro_sigma ** 2), accel_var=float(self.accel_sigma ** 2))

    def step_wheel_encoders(self, t: float, v_body: float, omega_body: float,
                            slip4=(0.0, 0.0, 0.0, 0.0), dt: float = 0.1,
                            sample_id: int | None = None) -> WheelSample:
        """Per-wheel encoder deltas (LF, RF, LR, RR) from the true body twist + hidden per-wheel slip.
        ground = theta*r*(1-slip) -> theta = v_ground*dt/(r*(1-slip)); quantized to counts. slip hidden."""
        half = 0.5 * self.track_m
        vg = np.array([v_body - omega_body * half, v_body + omega_body * half,
                       v_body - omega_body * half, v_body + omega_body * half])
        slip = np.clip(np.asarray(slip4, float), 0.0, 0.99)
        theta = vg * dt / (self.wheel_radius_m * (1.0 - slip))
        counts = np.round(theta * self.cpr / (2.0 * np.pi)).astype(int)
        q = 2.0 * np.pi / self.cpr
        if sample_id is None:
            sample_id = self._wheel_seq; self._wheel_seq += 1
        return WheelSample(t=float(t), encoder_delta_rad=counts * q, encoder_count_delta=counts,
                           covariance=np.eye(4) * (q ** 2 / 12.0), wheel_radius_m=self.wheel_radius_m,
                           encoder_counts_per_rev=self.cpr, sample_ids=(f"wheel:{sample_id}",),
                           config_revision=self.config_revision)

    def step_wheel(self, t: float, true_v_mps: float, slip: float,
                   true_yaw_rate_rps: float = 0.0) -> WheelOdomSample:
        """Aggregate differential-encoder reading: v and omega derived from two noisy wheel encoders;
        true slip used internally only (I3)."""
        slip = float(np.clip(slip, 0.0, 0.99)); half = 0.5 * self.track_m
        wL = (true_v_mps - true_yaw_rate_rps * half) / (1.0 - slip)
        wR = (true_v_mps + true_yaw_rate_rps * half) / (1.0 - slip)
        sL = float(self.params["wheel_odometry"]["encoder_read_noise_frac"]) * max(abs(wL), 1e-3)
        sR = float(self.params["wheel_odometry"]["encoder_read_noise_frac"]) * max(abs(wR), 1e-3)
        wL += self.rng.normal(0.0, sL); wR += self.rng.normal(0.0, sR)
        return WheelOdomSample(t=float(t), v_mps=float(0.5 * (wL + wR)),
                               omega_rps=float((wR - wL) / self.track_m),
                               v_var=float(0.25 * (sL ** 2 + sR ** 2)),
                               omega_var=float((sL ** 2 + sR ** 2) / self.track_m ** 2))


def runtime_proprioception_packet(imu: list, wheel_enc: list, *, sequence_id: int,
                                  imu_rate_hz: float, wheel_rate_hz: float,
                                  clock: str = "sim_monotonic", joints: dict | None = None) -> dict:
    """Build the additive, serializable runtime proprioception packet (schema proprioception/1.1).

    Channels carry samples + covariance + units + provenance on ONE monotonic clock + sequence id.
    The wheel channel publishes the RAW FOUR-WHEEL ENCODER samples (the producer owns the raw sensor;
    solnav derives body odometry). NO pose / slip / terrain / evaluation truth (I3); availability is OK
    only with a payload. ``joints`` (optional) is a measured arm-joint channel from
    ``runtime_packet.joint_channel`` (real FK -- drum-arm pitches + posture-conditioned camera heights);
    when absent the joints channel is honestly UNAVAILABLE. power has no battery-telemetry model -> always
    UNAVAILABLE (not faked).
    """
    def _imu_ch():
        return {
            "status": "OK", "rate_hz": float(imu_rate_hz),
            "units": {"gyro_z": "rad/s", "accel_xy": "m/s^2"},
            "samples": [
                {"t": s.t, "gyro_z": s.gyro_z_rps, "accel_xy": [float(s.accel_xy_mps2[0]), float(s.accel_xy_mps2[1])],
                 "gyro_var": s.gyro_var, "accel_var": s.accel_var} for s in imu],
            "provenance": "SIMULATED_SENSOR",
        }

    def _wheel_ch():
        ch = {"status": "OK", "rate_hz": float(wheel_rate_hz), "order": ["LF", "RF", "LR", "RR"],
              "units": {"encoder_delta": "rad", "encoder_count_delta": "count", "covariance": "rad^2"},
              "samples": [
                  {"t": s.t, "encoder_delta_rad": [float(x) for x in s.encoder_delta_rad],
                   "encoder_count_delta": [int(x) for x in s.encoder_count_delta],
                   "covariance": [[float(c) for c in row] for row in s.covariance],
                   "sample_ids": list(s.sample_ids)} for s in wheel_enc],
              "provenance": "SIMULATED_SENSOR"}
        if wheel_enc:
            ch["wheel_radius_m"] = float(wheel_enc[0].wheel_radius_m)
            ch["encoder_counts_per_rev"] = int(wheel_enc[0].encoder_counts_per_rev)
            ch["config_revision"] = str(wheel_enc[0].config_revision)
        return ch

    return {
        "schema_version": "proprioception/1.1",
        "clock": clock,
        "sequence_id": int(sequence_id),
        "channels": {
            "imu": _imu_ch(),
            "wheel": _wheel_ch(),
            "joints": joints if joints is not None else {
                "status": "UNAVAILABLE", "reason": "no measured joint channel supplied to this packet"},
            "power": {"status": "UNAVAILABLE", "reason": "no battery-telemetry model in this producer yet"},
        },
    }
