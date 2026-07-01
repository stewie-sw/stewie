"""[REQ:ML-09] Edge deployment envelope — typed Jetson Orin compute profiles carrying
published NVIDIA figures, an EdgeEnvelope that names every budget leg the requirement lists
(compute class, active depth source, image/cloud rate, CPU/GPU split, RAM ceiling,
thermal/power ceiling, telemetry bandwidth, offload boundary), a validator that REJECTS a
declared model set exceeding the budget, and degraded-mode scheduling that sheds by priority.

Real numbers only: the module budgets are NVIDIA-published Jetson Orin specs (sources cited
in compute_envelope.py) and the sensor side is the repo's real STEWIE_IPEX_V1 system profile
(8 cameras @ 10 Hz, selected depth source stereo_front). Measured-on-hardware draw is the
gated leg and is deliberately NOT asserted here — declared budgets are what this gate checks.
"""
from __future__ import annotations

import pytest

from stewie.contracts import ModelArtifact
from stewie.specs import compute_envelope as ce
from stewie.specs.profiles import load_profile


def _artifact(model_id: str, task: str, mem_mb: float, lat_ms: float) -> ModelArtifact:
    return ModelArtifact(model_id=model_id, name=model_id, version="1", task=task,
                         dataset_lineage="lac", eval_split="val",
                         input_schema="SensorFrame", output_schema="TerrainBeliefUpdate",
                         latency_budget_ms=lat_ms, memory_budget_mb=mem_mb,
                         calibrated=True, ood_detector=True, fallback="deterministic")


def _envelope(compute: ce.ComputeProfile = ce.JETSON_ORIN_NX_16GB, **overrides) -> ce.EdgeEnvelope:
    """A budget consistent with STEWIE_IPEX_V1 (stereo_front @ 10 Hz, 8 cameras) on Orin NX 16GB."""
    kwargs = dict(envelope_id="test_edge", compute=compute,
                  active_depth_source="stereo_front", camera_count=8,
                  image_rate_hz=10.0, cloud_rate_hz=5.0, cpu_fraction=0.25,
                  ram_ceiling_mb=12288.0, os_reserve_mb=4096.0,
                  power_ceiling_w=25.0, thermal_ceiling_c=90.0,
                  telemetry_bandwidth_mbps=100.0,
                  offload_boundary="dense multi-view reconstruction + model retraining at the "
                                   "base station; onboard emits typed estimates only")
    kwargs.update(overrides)
    return ce.EdgeEnvelope(**kwargs)


def test_jetson_profiles_carry_published_specs():  # [REQ:ML-09]
    """The three compute-class profiles hold the NVIDIA-published module figures verbatim."""
    agx = ce.JETSON_AGX_ORIN_64GB
    assert agx.ram_total_mb == 64 * 1024 and agx.ram_bandwidth_gbs == 204.8
    assert (agx.power_min_w, agx.power_max_w) == (15.0, 60.0)
    assert agx.cpu_cores == 12 and agx.gpu_cuda_cores == 2048
    nx = ce.JETSON_ORIN_NX_16GB
    assert nx.ram_total_mb == 16 * 1024 and nx.ram_bandwidth_gbs == 102.4
    assert (nx.power_min_w, nx.power_max_w) == (10.0, 40.0)
    assert nx.max_cameras_virtual == 8 and nx.csi_lanes == 8
    nano = ce.JETSON_ORIN_NANO_8GB
    assert nano.ram_total_mb == 8 * 1024 and nano.power_min_w == 7.0
    # every Orin-class SoC shares the published 105 C junction hard limit; each profile cites NVIDIA
    for prof in ce.COMPUTE_PROFILES.values():
        assert prof.thermal_junction_max_c == 105.0
        assert "NVIDIA" in prof.source


def test_envelope_validates_against_real_system_profile():  # [REQ:ML-09]
    """The envelope's sensor legs must be consistent with the REAL selected system profile."""
    profile = load_profile("STEWIE_IPEX_V1")
    env = _envelope()
    ce.validate_envelope(env, profile)                       # accept: consistent with the rig
    # the named depth source must be the profile's SELECTED source (stereo_front), not another
    with pytest.raises(ce.EnvelopeError, match="depth source"):
        ce.validate_envelope(_envelope(active_depth_source="stereo_rear"), profile)
    # the camera count must match the rig (8) and fit the module's published CSI capability
    with pytest.raises(ce.EnvelopeError, match="camera"):
        ce.validate_envelope(_envelope(camera_count=4), profile)
    with pytest.raises(ce.EnvelopeError, match="camera"):    # 8-camera rig > Nano/NX native 4: needs
        ce.validate_envelope(                                 # virtual channels; 16 would exceed even that
            _envelope(camera_count=16), profile)
    # the image rate cannot exceed the profile's real camera_hz (10.0)
    with pytest.raises(ce.EnvelopeError, match="image rate"):
        ce.validate_envelope(_envelope(image_rate_hz=30.0), profile)
    # cloud rate derives from frames: it cannot exceed the image rate
    with pytest.raises(ce.EnvelopeError, match="cloud rate"):
        ce.validate_envelope(_envelope(cloud_rate_hz=20.0), profile)


def test_envelope_ceilings_bounded_by_published_module_limits():  # [REQ:ML-09]
    """Declared ceilings may never exceed what NVIDIA publishes for the module."""
    profile = load_profile("STEWIE_IPEX_V1")
    # power ceiling above the NX 16GB published 40 W max
    with pytest.raises(ce.EnvelopeError, match="power"):
        ce.validate_envelope(_envelope(power_ceiling_w=50.0), profile)
    # thermal ceiling at/above the 105 C junction hard limit
    with pytest.raises(ce.EnvelopeError, match="thermal"):
        ce.validate_envelope(_envelope(thermal_ceiling_c=105.0), profile)
    # RAM ceiling + OS reserve above the module's 16384 MB
    with pytest.raises(ce.EnvelopeError, match="RAM"):
        ce.validate_envelope(_envelope(ram_ceiling_mb=15000.0), profile)
    # telemetry above the module's fastest published interface (10 GbE)
    with pytest.raises(ce.EnvelopeError, match="telemetry"):
        ce.validate_envelope(_envelope(telemetry_bandwidth_mbps=20000.0), profile)
    # the offload boundary must be NAMED (the row's explicit leg)
    with pytest.raises(ce.EnvelopeError, match="offload"):
        ce.validate_envelope(_envelope(offload_boundary=""), profile)


def test_model_set_within_budget_accepted():  # [REQ:ML-09]
    """Accept path: a simultaneous model set whose declared budgets fit the envelope."""
    env = _envelope()
    placed = (
        ce.PlacedModel(_artifact("m_terrain", "terrain_assess", 900.0, 45.0),
                       device="gpu", power_budget_w=8.0, rate_hz=5.0, priority=0),
        ce.PlacedModel(_artifact("m_rock", "rock_classify", 350.0, 20.0),
                       device="gpu", power_budget_w=3.0, rate_hz=2.0, priority=1),
        ce.PlacedModel(_artifact("m_exc", "excavation_state", 128.0, 5.0),
                       device="cpu", power_budget_w=1.5, rate_hz=10.0, priority=0),
    )
    ce.validate_model_set(env, placed)                       # must not raise
    # RAM 1378 <= 12288, power 12.5 <= 25, gpu duty 0.265 + cpu duty 0.05 both <= 1
    assert sum(p.artifact.memory_budget_mb for p in placed) <= env.ram_ceiling_mb


def test_model_set_exceeding_budget_rejected():  # [REQ:ML-09]
    """Reject path: each budget leg individually fails a set that exceeds it."""
    env = _envelope()
    ok = ce.PlacedModel(_artifact("m_terrain", "terrain_assess", 900.0, 45.0),
                        device="gpu", power_budget_w=8.0, rate_hz=5.0, priority=0)
    # RAM: a 12 GB model alongside the 900 MB one blows the 12288 MB ceiling
    hog = ce.PlacedModel(_artifact("m_big", "llm_planner", 12000.0, 80.0),
                         device="gpu", power_budget_w=5.0, rate_hz=1.0, priority=2)
    with pytest.raises(ce.EnvelopeError, match="RAM"):
        ce.validate_model_set(env, (ok, hog))
    # power: 30 W of declared draw over a 25 W ceiling
    hot = ce.PlacedModel(_artifact("m_hot", "shadow_slam", 500.0, 30.0),
                         device="gpu", power_budget_w=30.0, rate_hz=5.0, priority=1)
    with pytest.raises(ce.EnvelopeError, match="power"):
        ce.validate_model_set(env, (ok, hot))
    # latency: 300 ms at 5 Hz is 1.5x serial utilization of the GPU — infeasible
    slow = ce.PlacedModel(_artifact("m_slow", "volume", 200.0, 300.0),
                          device="gpu", power_budget_w=2.0, rate_hz=5.0, priority=1)
    with pytest.raises(ce.EnvelopeError, match="duty"):
        ce.validate_model_set(env, (ok, slow))
    # ML-01 tie-in: an UNDECLARED budget (0 memory) cannot be gated, so it is rejected
    bare = ce.PlacedModel(_artifact("m_bare", "rock_classify", 0.0, 10.0),
                          device="gpu", power_budget_w=1.0, rate_hz=1.0, priority=1)
    with pytest.raises(ce.EnvelopeError, match="undeclared"):
        ce.validate_model_set(env, (bare,))


def test_degraded_mode_scheduler_sheds_by_priority():  # [REQ:ML-09]
    """Over budget -> shed the most sheddable (highest priority number) models until fit."""
    env = _envelope()
    critical = ce.PlacedModel(_artifact("m_terrain", "terrain_assess", 900.0, 45.0),
                              device="gpu", power_budget_w=8.0, rate_hz=5.0, priority=0)
    useful = ce.PlacedModel(_artifact("m_rock", "rock_classify", 350.0, 20.0),
                            device="gpu", power_budget_w=3.0, rate_hz=2.0, priority=1)
    luxury = ce.PlacedModel(_artifact("m_llm", "llm_planner", 11800.0, 200.0),
                            device="gpu", power_budget_w=12.0, rate_hz=0.5, priority=3)
    retained = ce.degraded_schedule(env, (luxury, critical, useful))
    assert critical in retained and useful in retained       # criticals + fitting mid-priority kept
    assert luxury not in retained                            # the RAM/power hog is shed first
    ce.validate_model_set(env, retained)                     # the degraded set genuinely fits
    # a priority-0 set that cannot fit even alone must REFUSE, not silently shed safety models
    impossible = ce.PlacedModel(_artifact("m_imp", "terrain_assess", 20000.0, 45.0),
                                device="gpu", power_budget_w=8.0, rate_hz=5.0, priority=0)
    with pytest.raises(ce.EnvelopeError, match="safety-critical"):
        ce.degraded_schedule(env, (impossible,))
