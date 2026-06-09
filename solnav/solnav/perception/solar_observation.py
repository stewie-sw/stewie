"""Direct-Sun/ephemeris fallback observation contract for G2."""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class SolarObservation:
    azimuth_deg: float
    elevation_deg: float
    variance_azimuth_deg2: float
    variance_elevation_deg2: float
    source: str
    covariance_calibrated: bool
    sample_id: str
    coordinate_frame: str = "GODOT_WORLD"
    provenance: str = "RUNTIME_PARAMETER"

    def __post_init__(self):
        values = (
            self.azimuth_deg,
            self.elevation_deg,
            self.variance_azimuth_deg2,
            self.variance_elevation_deg2,
        )
        if not all(math.isfinite(value) for value in values):
            raise ValueError("solar observation values must be finite")
        if not 0.0 < self.elevation_deg < 90.0:
            raise ValueError("solar elevation must be in (0, 90) degrees")
        if self.variance_azimuth_deg2 < 0.0 or self.variance_elevation_deg2 < 0.0:
            raise ValueError("solar variances must be nonnegative")
        if self.source not in {"DIRECT_IMAGE", "EPHEMERIS_FALLBACK"}:
            raise ValueError("unsupported solar observation source")
        if not self.sample_id:
            raise ValueError("solar sample_id is required")



def _nonneg(v, name):
    if float(v) < 0.0:
        raise ValueError(f"{name} must be >= 0 (got {v})")
    return float(v)
def ephemeris_fallback(
    azimuth_deg: float,
    elevation_deg: float,
    *,
    sample_id: str,
    sigma_azimuth_deg: float,
    sigma_elevation_deg: float,
    covariance_calibrated: bool = False,
) -> SolarObservation:
    """Declare an ephemeris-only fallback without pretending it is image-derived."""

    return SolarObservation(
        azimuth_deg=float(azimuth_deg) % 360.0,
        elevation_deg=float(elevation_deg),
        variance_azimuth_deg2=_nonneg(sigma_azimuth_deg, "sigma_azimuth_deg") ** 2,
        variance_elevation_deg2=_nonneg(sigma_elevation_deg, "sigma_elevation_deg") ** 2,
        source="EPHEMERIS_FALLBACK",
        covariance_calibrated=bool(covariance_calibrated),
        sample_id=sample_id,
    )
