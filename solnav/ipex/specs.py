"""IPEx platform constants used by solnav, with provenance tags.

[SPEC]    = stated in the public record (NASA/KSC papers, LAC docs/API, the
            architecture reference, or read from a real LAC/dustgym sensors.json).
[CONFIRM] = read the exact value from the LAC geometry page / runtime API before
            locking (see ALGORITHMS.md "parameters to confirm"). Nothing here is
            fabricated; [CONFIRM] values are sourced estimates pending the
            authoritative geometry page.

Sources: ~/Downloads/IPEx_Rover_Architecture_DigitalTwin_Reference.md;
NTRS 20240008162 (TRL-5), 20210025846 (bucket-drum scaling); dustgym ipex_specs.py
(energy); and a real LAC-twin sensors.json (intrinsics, stereo baseline, sun).
At integration, reconcile with dustgym.ipex_specs rather than duplicating.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..config import SystemProfile, load_profile


@dataclass(frozen=True)
class IPExSpecs:
    profile_id: str = "DUSTGYM_IPEX_V1"
    profile_sha256: str = ""

    # Mass / mobility  [SPEC]
    mass_class_kg: float = 30.0
    drive_speed_ms: float = 0.30
    slope_max_deg: float = 15.0
    obstacle_max_m: float = 0.075
    traverse_max_km: float = 70.0

    # Arms / drums  [SPEC: Schuler et al. 2024, IPEx TRL-5 Design Overview]
    n_arms: int = 2
    n_drums: int = 4
    regolith_per_cycle_kg: float = 30.0   # collect/store/deposit per cycle [SPEC]; min 15 kg
    regolith_per_cycle_min_kg: float = 15.0
    excavation_rate_kg_hr: float = 42.0   # [SPEC]
    arm_nominal_max_deg: float = 55.0     # RDS arms stay <=55 deg in nominal ops [SPEC]
    arm_iron_cross_deg: float = 90.0      # "iron cross": arms parallel to ground [SPEC]
    chassis_raise_tilt_deg: float = 45.0  # one arm under body raises chassis ~45 deg [SPEC]
    arm_angle_max_rad: float = 2.36       # absolute mechanical max ~135 deg [SPEC]; [CONFIRM] exact
    drum_cut_depth_frac_max: float = 0.50  # <=50% scoop opening for best fill [SPEC]
    # Lineage scaling  [SPEC]
    rassor2_dry_mass_kg: float = 65.0
    scale_factor_vs_rassor2: float = 0.7  # 1-D linear scale RASSOR 2 -> IPEx [SPEC]

    # Camera optics  [SPEC: Schuler 2024 CDMS]
    sensor_mp: float = 5.0                # Sony IMX547, 5 MP
    pixel_um: float = 2.74
    lens_focal_mm: tuple = (6.0, 4.4)     # candidate S-mount focal lengths [SPEC]
    aperture_fnum: float = 4.0            # f/4 [SPEC]
    led_lumens_max: float = 3000.0        # per light [SPEC]
    led_beam_fwhm_deg: float = 42.0       # [SPEC]
    baseline_original_m: float = 0.165    # split-shoulder design before combining [SPEC]

    # Cameras / IMU  [SPEC]
    n_cameras: int = 8
    max_live_cameras: int = 4
    cam_max_res_wh: tuple = (2448, 2048)
    render_hz: float = 10.0
    sim_hz: float = 20.0
    imu_hz: float = 20.0

    # Stereo / intrinsics  [SPEC: from a real LAC-twin sensors.json render]
    stereo_baseline_m: float = 0.07       # front stereo, measured 0.0700 m
    fx_px: float = 679.57                 # twin render; [CONFIRM] flight intrinsics

    # Fiducials  [SPEC]
    apriltag_family: str = "tag36h11"
    apriltag_size_m: float = 0.15
    fiducial_free_bonus_pts: int = 150

    # Energy  [SPEC: dustgym ipex_specs from SCHULER24 + 12S/44V/30Ah pack]
    drive_j_per_m: float = 135.0
    dig_j_per_kg: float = 4151.0
    pack_wh: float = 1332.0

    # Mapping / scoring envelope  [SPEC: LAC]
    map_area_m: float = 27.0
    map_grid_cells: int = 180
    map_cell_m: float = 0.15
    height_tolerance_m: float = 0.05

    def pack_joules(self) -> float:
        """Battery capacity in joules (Wh * 3600)."""
        return self.pack_wh * 3600.0

    def regolith_capacity_kg(self) -> float:
        """Max regolith per excavation cycle [SPEC: Schuler 2024]."""
        return self.regolith_per_cycle_kg

    @classmethod
    def from_profile(cls, profile: str | SystemProfile | None = None) -> "IPExSpecs":
        selected = profile if isinstance(profile, SystemProfile) else load_profile(profile)
        vehicle = selected.vehicle
        cameras = selected.cameras
        optics = cameras["optics"]
        energy = selected.energy
        mapping = selected.mapping
        posture = selected.data["posture"]
        return cls(
            profile_id=selected.profile_id,
            profile_sha256=selected.sha256,
            mass_class_kg=float(vehicle["dry_mass_kg"]),
            drive_speed_ms=float(vehicle["nominal_speed_mps"]),
            slope_max_deg=float(vehicle["nominal_slope_deg"]),
            obstacle_max_m=float(vehicle["obstacle_height_m"]),
            arm_nominal_max_deg=float(posture["nominal_limit_deg"]),
            arm_angle_max_rad=float(posture["mechanical_limit_rad"]),
            n_cameras=len(cameras["entries"]),
            max_live_cameras=int(cameras["max_live"]),
            cam_max_res_wh=tuple(optics["maximum_resolution_px"]),
            render_hz=float(selected.data["timing"]["camera_hz"]),
            sim_hz=1.0 / float(selected.data["timing"]["drive_dt_s"]),
            imu_hz=float(selected.data["timing"]["imu_hz"] or 0.0),
            stereo_baseline_m=float(selected.data["stereo"]["front"]["baseline_m"]),
            fx_px=float(optics["fx_px"]),
            drive_j_per_m=float(energy.get("drive_j_per_m", 0.0)),
            dig_j_per_kg=float(energy.get("dig_j_per_kg", 0.0)),
            pack_wh=float(energy["capacity_wh"]),
            map_area_m=float(mapping["area_m"]),
            map_grid_cells=int(mapping["grid_cells"]),
            map_cell_m=float(mapping["cell_m"]),
            height_tolerance_m=float(mapping["height_tolerance_m"]),
        )


IPEX = IPExSpecs.from_profile()
