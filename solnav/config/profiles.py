"""Load and validate complete Dustgym/official system profiles.

Profiles are the authority for values shared by camera geometry, IPEx specifications,
runtime compatibility checks, and experiment provenance. Runtime sensor metadata remains
the authority for a particular frame, but it must be compatible with the selected profile.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any, Mapping, Optional

import numpy as np

DEFAULT_PROFILE_ID = "DUSTGYM_IPEX_V1"
PROFILE_ENV = "SOLNAV_PROFILE"
_ALIASES = {
    "dustgym": DEFAULT_PROFILE_ID,
    "official": "OFFICIAL_LAC_2025_UNVERIFIED",
}
_FILES = {
    DEFAULT_PROFILE_ID: "dustgym_ipex_v1.json",
    "OFFICIAL_LAC_2025_UNVERIFIED": "official_lac_2025_unverified.json",
}


class ProfileError(ValueError):
    """A profile is incomplete, internally inconsistent, or unsuitable for a requested use."""


class MixedProfileError(ProfileError):
    """Runtime metadata belongs to a different geometry/optics profile."""


@dataclass(frozen=True)
class SystemProfile:
    """Validated profile plus the checksum of the exact source bytes."""

    data: Mapping[str, Any]
    sha256: str
    source: str

    @property
    def profile_id(self) -> str:
        return str(self.data["profile_id"])

    @property
    def status(self) -> str:
        return str(self.data["status"])

    @property
    def substrate(self) -> str:
        return str(self.data["substrate"])

    @property
    def cameras(self) -> Mapping[str, Any]:
        return self.data["cameras"]

    @property
    def vehicle(self) -> Mapping[str, Any]:
        return self.data["vehicle"]

    @property
    def energy(self) -> Mapping[str, Any]:
        return self.data["energy"]

    @property
    def mapping(self) -> Mapping[str, Any]:
        return self.data["mapping"]

    def camera(self, name: str) -> Mapping[str, Any]:
        for camera in self.cameras["entries"]:
            if camera["name"] == name:
                return camera
        raise KeyError(name)

    def record(self) -> dict[str, str]:
        return {
            "profile_id": self.profile_id,
            "profile_sha256": self.sha256,
            "profile_status": self.status,
            "profile_source": self.source,
        }


def available_profiles() -> tuple[str, ...]:
    return tuple(sorted(_FILES))


def _resource_bytes(filename: str) -> bytes:
    return resources.files("solnav.config").joinpath("data").joinpath(filename).read_bytes()


def _resolve(identifier: Optional[str]) -> tuple[bytes, str]:
    requested = identifier or os.environ.get(PROFILE_ENV, DEFAULT_PROFILE_ID)
    key = _ALIASES.get(requested.lower(), requested)
    if key in _FILES:
        return _resource_bytes(_FILES[key]), "package:" + _FILES[key]
    path = Path(requested)
    if path.is_file():
        return path.read_bytes(), str(path.resolve())
    raise ProfileError(
        f"unknown profile {requested!r}; expected one of {available_profiles()} or a JSON path"
    )


def _vec3(value: Any, label: str) -> np.ndarray:
    v = np.asarray(value, dtype=float)
    if v.shape != (3,) or not np.all(np.isfinite(v)):
        raise ProfileError(f"{label} must be a finite 3-vector")
    return v


def _body_position(camera: Mapping[str, Any]) -> np.ndarray:
    p = _vec3(camera["position_m"], f"camera {camera.get('name')} position_m")
    frame = camera.get("position_frame")
    if frame == "body":
        return p
    if frame == "godot":
        return np.array([p[0], -p[2], p[1]])
    raise ProfileError(f"camera {camera.get('name')} has unsupported position_frame {frame!r}")


def _validate(data: Mapping[str, Any], *, require_verified: bool) -> None:
    required = {
        "schema_version", "profile_id", "status", "substrate", "frames", "timing",
        "vehicle", "cameras", "stereo", "posture", "terrain", "energy", "mapping",
    }
    missing = sorted(required - set(data))
    if missing:
        raise ProfileError(f"profile missing top-level fields: {missing}")
    if data["schema_version"] != "solnav_system_profile/1.0":
        raise ProfileError(f"unsupported schema_version {data['schema_version']!r}")
    if require_verified and data["status"] != "VERIFIED":
        raise ProfileError(
            f"profile {data['profile_id']} is {data['status']}, but verified data was required"
        )

    cameras = data["cameras"]
    entries = cameras.get("entries", [])
    names = [camera.get("name") for camera in entries]
    if len(entries) != 8 or len(set(names)) != 8:
        raise ProfileError("profile must define exactly eight uniquely named cameras")
    for camera in entries:
        _body_position(camera)
        _vec3(camera["optical_axis_body"], f"camera {camera.get('name')} optical_axis_body")
        if float(np.linalg.norm(camera["optical_axis_body"])) < 1e-9:
            raise ProfileError(f"camera {camera.get('name')} optical axis is zero")

    optics = cameras["optics"]
    width = int(optics["width_px"])
    height = int(optics["height_px"])
    hfov = float(optics["hfov_deg"])
    fx = float(optics["fx_px"])
    if width <= 0 or height <= 0 or not 0.0 < hfov < 180.0 or fx <= 0.0:
        raise ProfileError("camera dimensions, HFOV, and focal length must be positive")
    fx_derived = (width * 0.5) / math.tan(math.radians(hfov) * 0.5)
    if not math.isclose(fx, fx_derived, rel_tol=2e-4, abs_tol=1e-3):
        raise ProfileError(
            f"camera fx {fx} is inconsistent with width {width} and HFOV {hfov}; "
            f"expected {fx_derived}"
        )

    by_name = {camera["name"]: camera for camera in entries}
    for pair_name, pair in data["stereo"].items():
        try:
            left = _body_position(by_name[pair["left"]])
            right = _body_position(by_name[pair["right"]])
        except KeyError as exc:
            raise ProfileError(f"stereo pair {pair_name} references unknown camera {exc}") from exc
        actual = float(np.linalg.norm(left - right))
        declared = float(pair["baseline_m"])
        if not math.isclose(actual, declared, rel_tol=1e-5, abs_tol=1e-6):
            raise ProfileError(
                f"stereo pair {pair_name} baseline mismatch: geometry {actual}, declared {declared}"
            )

    vehicle = data["vehicle"]
    for key in ("dry_mass_kg", "wheelbase_m", "track_gauge_m", "wheel_radius_m"):
        if float(vehicle[key]) <= 0.0:
            raise ProfileError(f"vehicle.{key} must be positive")


def load_profile(identifier: Optional[str] = None, *, require_verified: bool = False) -> SystemProfile:
    raw, source = _resolve(identifier)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProfileError(f"invalid profile JSON in {source}: {exc}") from exc
    if not isinstance(data, dict):
        raise ProfileError(f"profile in {source} must be a JSON object")
    _validate(data, require_verified=require_verified)
    return SystemProfile(data=data, sha256=hashlib.sha256(raw).hexdigest(), source=source)


def get_profile() -> SystemProfile:
    """Load the profile selected by ``SOLNAV_PROFILE`` (Dustgym by default)."""
    return load_profile()


def validate_sensor_frame(
    profile: SystemProfile,
    frame: Any,
    *,
    baseline_tol_m: float = 1e-3,
    focal_rel_tol: float = 2e-3,
    position_tol_m: float = 2e-3,
) -> None:
    """Reject runtime camera metadata that is incompatible with ``profile``.

    Runtime values may differ by floating-point serialization but not by sensor rig.
    A frame with an explicit ``profile_id`` must match exactly. Otherwise baseline,
    intrinsics, image dimensions, and fixed-camera positions establish compatibility.
    """
    explicit = frame.raw.get("profile_id") if getattr(frame, "raw", None) else None
    if explicit is not None and explicit != profile.profile_id:
        raise MixedProfileError(
            f"sensor frame profile_id {explicit!r} does not match selected {profile.profile_id!r}"
        )

    expected_optics = profile.cameras["optics"]
    resolution_policy = expected_optics.get("resolution_policy", "exact")
    expected_names = {c["name"] for c in profile.cameras["entries"]}
    actual_names = {c.name for c in frame.cameras}
    if expected_names != actual_names:
        raise MixedProfileError(
            f"camera set mismatch for {profile.profile_id}: "
            f"missing={sorted(expected_names - actual_names)}, extra={sorted(actual_names - expected_names)}"
        )

    front = profile.data["stereo"]["front"]
    if frame.stereo_pair and tuple(frame.stereo_pair) != (front["left"], front["right"]):
        raise MixedProfileError(
            f"front stereo identity {frame.stereo_pair!r} does not match "
            f"{(front['left'], front['right'])!r}"
        )
    if frame.stereo_baseline_m is None or not math.isclose(
        float(frame.stereo_baseline_m), float(front["baseline_m"]), abs_tol=baseline_tol_m
    ):
        raise MixedProfileError(
            f"front baseline {frame.stereo_baseline_m!r} does not match "
            f"{profile.profile_id} value {front['baseline_m']}"
        )

    for actual in frame.cameras:
        expected = profile.camera(actual.name)
        if resolution_policy == "exact":
            expected_size = (int(expected_optics["width_px"]), int(expected_optics["height_px"]))
            if (actual.width, actual.height) != expected_size:
                raise MixedProfileError(
                    f"camera {actual.name} dimensions {(actual.width, actual.height)} "
                    f"do not match {expected_size}"
                )
        elif resolution_policy == "configurable":
            max_width, max_height = map(int, expected_optics["maximum_resolution_px"])
            if actual.width <= 0 or actual.height <= 0 or actual.width > max_width or actual.height > max_height:
                raise MixedProfileError(
                    f"camera {actual.name} dimensions {(actual.width, actual.height)} exceed "
                    f"profile maximum {(max_width, max_height)}"
                )
        else:
            raise ProfileError(f"unsupported resolution_policy {resolution_policy!r}")
        expected_fx = (actual.width * 0.5) / math.tan(
            math.radians(float(expected_optics["hfov_deg"])) * 0.5
        )
        if not math.isclose(actual.fx, expected_fx, rel_tol=focal_rel_tol):
            raise MixedProfileError(
                f"camera {actual.name} fx {actual.fx} does not match profile-derived {expected_fx}"
            )
        if expected.get("transform_mode") == "articulated":
            continue
        expected_position = _vec3(expected["position_m"], f"camera {actual.name} position")
        if expected.get("position_frame") == "body":
            expected_position = np.array(
                [expected_position[0], expected_position[2], -expected_position[1]]
            )
        if not np.allclose(actual.extrinsic_pos_m, expected_position, atol=position_tol_m):
            raise MixedProfileError(
                f"camera {actual.name} position {actual.extrinsic_pos_m.tolist()} does not match "
                f"{profile.profile_id} position {expected_position.tolist()}"
            )
