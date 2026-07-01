"""compute_envelope.py — ML-09 edge deployment envelope (typed compute budget + gate).

Any SIMULTANEOUS model set intended for IPEx-class hardware must fit the selected compute
profile under RAM, power, thermal, latency, and sensor-I/O budgets, with degraded-mode
scheduling. This module is the closeable slice: a typed `ComputeProfile` per Jetson Orin
class carrying the PUBLISHED module figures, an `EdgeEnvelope` that names every budget leg
the requirement lists (compute class, active depth source, image/cloud rate, CPU/GPU split,
RAM ceiling, thermal/power ceiling, telemetry bandwidth, offload boundary to a base
station), validators that REJECT an envelope inconsistent with the selected system profile
or a model set exceeding the budget, and a priority-ordered degraded-mode scheduler.

GATED LEG (honest): measured-on-hardware draw (real RAM residency, wall power, junction
temperature, per-model latency under contention) needs live Jetson hardware and is NOT
modeled here — this gate checks DECLARED budgets against PUBLISHED ceilings, the same
declared-budget discipline `ModelArtifact.deployment_ready` (ML-01) established.

Module figures — all NVIDIA-published, no fabricated values:
  [ORINPAGE]  nvidia.com/en-us/autonomous-machines/embedded-systems/jetson-orin/ (fetched
              2026-07-01; Nano/NX columns reflect the JetPack 6 "Super" power modes).
              Orin Nano 8GB: 67 TOPS, 1024-core Ampere/32 TC, 6x A78AE @1.7 GHz, 8 GB
              128-bit LPDDR5 @102 GB/s, 7-25 W, 8x MIPI CSI-2 lanes, up to 4 cameras
              (8 via virtual channels), 1x GbE.
              Orin NX 16GB: 157 TOPS, 1792-core Ampere/56 TC, 8x A78AE @2.0 GHz, 16 GB
              128-bit LPDDR5 @102.4 GB/s, 10-40 W, 8x CSI lanes, up to 4 cameras (8 via
              virtual channels), 1x GbE + 1x 10GbE.
  [DS10662]   NVIDIA Jetson AGX Orin Series Data Sheet, DS-10662-001. AGX Orin 64GB:
              275 TOPS, 2048-core Ampere/64 TC, 12x A78AE @2.2 GHz, 64 GB 256-bit LPDDR5
              @204.8 GB/s, 15-60 W, 16x CSI lanes, up to 6 cameras (16 via virtual
              channels), up to 10 GbE.
  [ORINTDG]   Jetson Orin thermal design guides (TDG-10943-001 AGX / TDG-11127-001
              NX+Nano): the Orin SoC junction temperature must not exceed 105 C (hardware
              shutdown); envelopes must therefore declare a ceiling strictly below it.
"""
# PROVENANCE: STEWIE DART subsystem (A. Storey)
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from stewie.contracts import ModelArtifact

from .profiles import SystemProfile

_DEVICES = ("cpu", "gpu")
ORIN_JUNCTION_MAX_C = 105.0     # [ORINTDG] shared hard limit across the Orin series


class EnvelopeError(ValueError):
    """An envelope is inconsistent with its module/system profile, or a model set exceeds it."""


@dataclass(frozen=True)
class ComputeProfile:
    """One Jetson Orin compute class with its NVIDIA-published module budgets."""

    profile_id: str
    compute_class: str            # human name, e.g. "Jetson Orin NX 16GB"
    cpu_cores: int
    cpu_clock_ghz: float
    gpu_cuda_cores: int
    gpu_tensor_cores: int
    ai_tops_int8_sparse: float    # published headline; per-model TOPS demand is the measured gated leg
    ram_total_mb: int
    ram_bandwidth_gbs: float
    power_min_w: float            # published configurable power-mode range
    power_max_w: float
    thermal_junction_max_c: float
    csi_lanes: int
    max_cameras_native: int
    max_cameras_virtual: int      # via CSI virtual channels
    telemetry_ceiling_mbps: float  # fastest published Ethernet interface
    source: str


JETSON_ORIN_NANO_8GB = ComputeProfile(
    profile_id="jetson_orin_nano_8gb", compute_class="Jetson Orin Nano 8GB",
    cpu_cores=6, cpu_clock_ghz=1.7, gpu_cuda_cores=1024, gpu_tensor_cores=32,
    ai_tops_int8_sparse=67.0, ram_total_mb=8 * 1024, ram_bandwidth_gbs=102.0,
    power_min_w=7.0, power_max_w=25.0, thermal_junction_max_c=ORIN_JUNCTION_MAX_C,
    csi_lanes=8, max_cameras_native=4, max_cameras_virtual=8,
    telemetry_ceiling_mbps=1000.0, source="NVIDIA [ORINPAGE] + [ORINTDG]")

JETSON_ORIN_NX_16GB = ComputeProfile(
    profile_id="jetson_orin_nx_16gb", compute_class="Jetson Orin NX 16GB",
    cpu_cores=8, cpu_clock_ghz=2.0, gpu_cuda_cores=1792, gpu_tensor_cores=56,
    ai_tops_int8_sparse=157.0, ram_total_mb=16 * 1024, ram_bandwidth_gbs=102.4,
    power_min_w=10.0, power_max_w=40.0, thermal_junction_max_c=ORIN_JUNCTION_MAX_C,
    csi_lanes=8, max_cameras_native=4, max_cameras_virtual=8,
    telemetry_ceiling_mbps=10000.0, source="NVIDIA [ORINPAGE] + [ORINTDG]")

JETSON_AGX_ORIN_64GB = ComputeProfile(
    profile_id="jetson_agx_orin_64gb", compute_class="Jetson AGX Orin 64GB",
    cpu_cores=12, cpu_clock_ghz=2.2, gpu_cuda_cores=2048, gpu_tensor_cores=64,
    ai_tops_int8_sparse=275.0, ram_total_mb=64 * 1024, ram_bandwidth_gbs=204.8,
    power_min_w=15.0, power_max_w=60.0, thermal_junction_max_c=ORIN_JUNCTION_MAX_C,
    csi_lanes=16, max_cameras_native=6, max_cameras_virtual=16,
    telemetry_ceiling_mbps=10000.0, source="NVIDIA [DS10662] + [ORINTDG]")

COMPUTE_PROFILES: dict[str, ComputeProfile] = {
    p.profile_id: p for p in (JETSON_ORIN_NANO_8GB, JETSON_ORIN_NX_16GB, JETSON_AGX_ORIN_64GB)}


@dataclass(frozen=True)
class EdgeEnvelope:
    """The named deployment budget every simultaneous model set is gated against (ML-09)."""

    envelope_id: str
    compute: ComputeProfile
    active_depth_source: str      # must be the system profile's SELECTED depth source
    camera_count: int             # must match the rig and fit the module's CSI capability
    image_rate_hz: float          # <= the system profile's camera_hz
    cloud_rate_hz: float          # point clouds derive from frames: <= image_rate_hz
    cpu_fraction: float           # declared CPU share of the inference workload (rest = GPU)
    ram_ceiling_mb: float         # model-set ceiling; ram_ceiling + os_reserve <= module RAM
    os_reserve_mb: float          # OS/runtime/driver reserve outside the model budget
    power_ceiling_w: float        # <= the module's published max power mode
    thermal_ceiling_c: float      # < the 105 C junction hard limit [ORINTDG]
    telemetry_bandwidth_mbps: float  # rover->base-station budget, <= fastest published NIC
    offload_boundary: str         # names what runs at the base station instead of onboard


@dataclass(frozen=True)
class PlacedModel:
    """One model of a simultaneous set: the registered artifact plus its placement budgets.

    Power lives on the PLACEMENT (draw depends on device + invocation rate), so the shared
    ML-01 `ModelArtifact` contract stays untouched. `priority` orders degraded-mode shedding:
    0 = safety-critical (never shed), larger = shed earlier.
    """

    artifact: ModelArtifact
    device: str
    power_budget_w: float
    rate_hz: float
    priority: int


def validate_envelope(envelope: EdgeEnvelope, profile: SystemProfile) -> None:
    """Reject an envelope inconsistent with the module's published limits or the system profile."""
    compute = envelope.compute
    sensors = profile.sensors
    selected = str(sensors.get("selected_depth_source"))
    if envelope.active_depth_source != selected:
        raise EnvelopeError(
            f"active depth source {envelope.active_depth_source!r} is not the system profile's "
            f"selected source {selected!r}")
    rig_cameras = len(profile.cameras["entries"])
    if envelope.camera_count != rig_cameras:
        raise EnvelopeError(
            f"camera count {envelope.camera_count} does not match the {rig_cameras}-camera rig")
    if envelope.camera_count > compute.max_cameras_virtual:
        raise EnvelopeError(
            f"camera count {envelope.camera_count} exceeds {compute.compute_class} CSI capability "
            f"({compute.max_cameras_virtual} via virtual channels)")
    camera_hz = float(profile.data["timing"]["camera_hz"])
    if not 0.0 < envelope.image_rate_hz <= camera_hz:
        raise EnvelopeError(
            f"image rate {envelope.image_rate_hz} Hz outside (0, {camera_hz}] (profile camera_hz)")
    if not 0.0 < envelope.cloud_rate_hz <= envelope.image_rate_hz:
        raise EnvelopeError(
            f"cloud rate {envelope.cloud_rate_hz} Hz must be in (0, image rate "
            f"{envelope.image_rate_hz}] (clouds derive from frames)")
    if not 0.0 <= envelope.cpu_fraction <= 1.0:
        raise EnvelopeError(f"cpu_fraction {envelope.cpu_fraction} must be within [0, 1]")
    if envelope.os_reserve_mb <= 0.0 or envelope.ram_ceiling_mb <= 0.0:
        raise EnvelopeError("RAM ceiling and OS reserve must both be positive")
    if envelope.ram_ceiling_mb + envelope.os_reserve_mb > compute.ram_total_mb:
        raise EnvelopeError(
            f"RAM ceiling {envelope.ram_ceiling_mb} + reserve {envelope.os_reserve_mb} MB exceeds "
            f"the {compute.compute_class} module's {compute.ram_total_mb} MB")
    if not 0.0 < envelope.power_ceiling_w <= compute.power_max_w:
        raise EnvelopeError(
            f"power ceiling {envelope.power_ceiling_w} W outside (0, {compute.power_max_w}] "
            f"(the {compute.compute_class} published max mode)")
    if not 0.0 < envelope.thermal_ceiling_c < compute.thermal_junction_max_c:
        raise EnvelopeError(
            f"thermal ceiling {envelope.thermal_ceiling_c} C must be strictly below the "
            f"{compute.thermal_junction_max_c} C junction hard limit [ORINTDG]")
    if not 0.0 < envelope.telemetry_bandwidth_mbps <= compute.telemetry_ceiling_mbps:
        raise EnvelopeError(
            f"telemetry budget {envelope.telemetry_bandwidth_mbps} Mbps exceeds the module's "
            f"fastest published interface ({compute.telemetry_ceiling_mbps} Mbps)")
    if not envelope.offload_boundary.strip():
        raise EnvelopeError("offload boundary must be named (what runs at the base station)")


def _fit_violations(envelope: EdgeEnvelope, placed: Sequence[PlacedModel]) -> list[str]:
    """Every budget leg a simultaneous model set can exceed, as one message per violation."""
    violations: list[str] = []
    for p in placed:
        if p.device not in _DEVICES:
            violations.append(f"{p.artifact.model_id}: unknown device {p.device!r}")
        if p.artifact.memory_budget_mb <= 0.0 or p.artifact.latency_budget_ms <= 0.0 \
                or p.power_budget_w <= 0.0 or p.rate_hz <= 0.0:
            violations.append(
                f"{p.artifact.model_id}: undeclared budget (memory/latency/power/rate must be "
                "positive to be gated — ML-01)")
    if violations:
        return violations
    ram_mb = sum(p.artifact.memory_budget_mb for p in placed)
    if ram_mb > envelope.ram_ceiling_mb:
        violations.append(
            f"RAM {ram_mb:.0f} MB exceeds the {envelope.ram_ceiling_mb:.0f} MB ceiling")
    power_w = sum(p.power_budget_w for p in placed)
    if power_w > envelope.power_ceiling_w:
        violations.append(
            f"power {power_w:.1f} W exceeds the {envelope.power_ceiling_w:.1f} W ceiling")
    for device in _DEVICES:
        # serial-execution utilization: the conservative feasibility bound for one device
        duty = sum(p.artifact.latency_budget_ms * p.rate_hz / 1000.0
                   for p in placed if p.device == device)
        if duty > 1.0:
            violations.append(f"{device} duty {duty:.2f} exceeds 1.0 (latency x rate infeasible)")
    return violations


def validate_model_set(envelope: EdgeEnvelope, placed: Sequence[PlacedModel]) -> None:
    """ML-09 gate: reject a simultaneous model set whose declared budgets exceed the envelope."""
    violations = _fit_violations(envelope, placed)
    if violations:
        raise EnvelopeError(
            f"model set exceeds envelope {envelope.envelope_id}: " + "; ".join(violations))


def degraded_schedule(envelope: EdgeEnvelope,
                      placed: Sequence[PlacedModel]) -> tuple[PlacedModel, ...]:
    """Degraded-mode scheduling: keep models in priority order (0 first), shedding any model
    the remaining budget cannot hold. Safety-critical (priority 0) models are never shed —
    a priority-0 set that does not fit is REFUSED so the caller cannot deploy blind."""
    critical = tuple(p for p in placed if p.priority == 0)
    if _fit_violations(envelope, critical):
        raise EnvelopeError(
            f"safety-critical models alone exceed envelope {envelope.envelope_id}: "
            + "; ".join(_fit_violations(envelope, critical)))
    retained = list(critical)
    for p in sorted((p for p in placed if p.priority > 0), key=lambda p: p.priority):
        if not _fit_violations(envelope, (*retained, p)):
            retained.append(p)
    # report in the caller's original order for stable downstream display
    order = {id(p): i for i, p in enumerate(placed)}
    return tuple(sorted(retained, key=lambda p: order[id(p)]))
