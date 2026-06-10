"""Operational lunar-rock semantics for excavation + navigation (NOT geology).

A detected rock is binned SIMULTANEOUSLY along three operational axes, because the same object means
different things to different subsystems -- a 70 cm boulder is a NAV hazard, an excellent LOCALIZATION
landmark, and an EXCAVATION avoid. Bins are grounded in IPEx mobility (7.5 cm step-over clearance).

Height comes from shadow geometry H = L*tan(e) (south-pole grazing sun is a natural height sensor) or
stereo; the DEM residual (dem_cross: local-minus-orbital) gives protrusion + a localization cue. This is
the size->semantics layer of the physics-informed estimator that feeds the planner (terrain + rock +
localization + energy cost). No geology classes, no synthetic data.
"""
# PROVENANCE: SolNav dissertation (A. Storey) -- moved from solnav/perception/rock_taxonomy.py, 2026-06-09 (M2)
from __future__ import annotations

import math
from dataclasses import dataclass

IPEX_STEP_OVER_M = 0.075    # physical clearance: IPEx clears obstacles up to 7.5 cm [SCHULER24]
AVOID_THRESHOLD_M = 0.07    # OPERATIONAL avoid line: avoid anything above 7 cm (0.5 cm margin under clearance)

# --- operational bins (STEWIE rock taxonomy), diameter in metres; upper edge exclusive -----------------------
# Navigation: can I drive over it?  A=traversable (<= 7 cm) ... E=no-go. Anything above 7 cm => avoid.
NAV_BINS = ((AVOID_THRESHOLD_M, "A"), (0.15, "B"), (0.30, "C"), (0.50, "D"), (math.inf, "E"))
# Localization: is it a usable landmark?  L0=ignore, L1=candidate, L2=persistent
LOC_BINS = ((0.15, "L0"), (0.50, "L1"), (math.inf, "L2"))
# Excavation: can I dig/handle it?  E0=regolith (<= 7 cm) E1=movable E2=difficult E3=avoid
EXC_BINS = ((AVOID_THRESHOLD_M, "E0"), (0.20, "E1"), (0.50, "E2"), (math.inf, "E3"))

NAV_MEANING = {"A": "traversable (enters regolith model)", "B": "minor obstacle; wheel interaction",
               "C": "traversability consideration; local replanning", "D": "significant obstacle",
               "E": "major obstacle; no-go for normal traverse"}
LOC_MEANING = {"L0": "ignore", "L1": "candidate landmark", "L2": "persistent landmark"}
EXC_MEANING = {"E0": "regolith", "E1": "movable", "E2": "difficult", "E3": "avoid / special handling"}


def _bin(diameter_m: float, bins) -> str:
    for thr, label in bins:
        if diameter_m < thr:
            return label
    return bins[-1][1]


@dataclass(frozen=True)
class Rock:
    """A rock as an operational world-model record (not a geology label)."""
    diameter_m: float
    height_m: float
    volume_m3: float
    confidence: float
    nav_class: str        # A..E (drive-over?)
    loc_class: str        # L0..L2 (landmark?)
    excav_class: str      # E0..E3 (dig/handle?)
    height_source: str = "unknown"   # "shadow" | "stereo" | "aspect_default"
    provenance: str = "RUNTIME_DERIVED"

    @property
    def is_obstacle(self) -> bool:
        """Avoid: the rock is above the 7 cm operational avoid threshold (any nav class except A)."""
        return self.nav_class != "A"

    def as_dict(self) -> dict:
        return {"diameter_m": round(self.diameter_m, 3), "height_m": round(self.height_m, 3),
                "volume_m3": round(self.volume_m3, 4), "confidence": round(self.confidence, 3),
                "nav_class": self.nav_class, "loc_class": self.loc_class, "excav_class": self.excav_class,
                "is_obstacle": self.is_obstacle, "height_source": self.height_source}

    def meanings(self) -> dict:
        return {"navigation": NAV_MEANING[self.nav_class], "localization": LOC_MEANING[self.loc_class],
                "excavation": EXC_MEANING[self.excav_class]}


def shadow_height_m(shadow_length_m: float, sun_elevation_deg: float) -> float:
    """Rock height from its cast-shadow length under known solar elevation: H = L * tan(e). At the south
    pole (e ~ 0-5 deg) shadows are long -> a natural height sensor that can beat stereo in deep shadow."""
    if sun_elevation_deg <= 0:
        raise ValueError("sun elevation must be > 0 to size by shadow")
    return float(shadow_length_m) * math.tan(math.radians(sun_elevation_deg))


def ellipsoid_volume_m3(diameter_m: float, height_m: float) -> float:
    """Spoil/obstacle volume as a half-buried oblate ellipsoid (semi-axes d/2, d/2, height)."""
    a = diameter_m / 2.0
    return (4.0 / 3.0) * math.pi * a * a * max(height_m, 1e-3) / 2.0


def classify(diameter_m: float, *, height_m: float | None = None, confidence: float = 1.0,
             height_source: str = "aspect_default") -> Rock:
    """Bin a sized rock into its navigation / localization / excavation classes simultaneously. If height
    is unknown, assume a typical lunar boulder aspect (h ~ 0.6 d). The NAVIGATION bin keys on the
    GOVERNING obstacle dimension max(diameter, height): step-over clearance is a HEIGHT constraint, so a
    known-tall narrow rock (h > 7.5 cm, d < 7 cm) must NOT bin as drive-over class A (audit 2026-06-09).
    Localization/excavation stay diameter-keyed (visibility / spoil volume are width-driven)."""
    h = height_m if height_m is not None else 0.6 * diameter_m
    nav_dim = max(diameter_m, h)
    return Rock(diameter_m=float(diameter_m), height_m=float(h),
                volume_m3=ellipsoid_volume_m3(diameter_m, h), confidence=float(confidence),
                nav_class=_bin(nav_dim, NAV_BINS), loc_class=_bin(diameter_m, LOC_BINS),
                excav_class=_bin(diameter_m, EXC_BINS),
                height_source=(height_source if height_m is not None else "aspect_default"))


def from_detection_px(box_xyxy, score: float, m_per_px: float, *, shadow_length_px: float | None = None,
                      sun_elevation_deg: float | None = None) -> Rock:
    """Build a Rock from a detector box on a calibrated image. Diameter = larger box side * m_per_px;
    height from the shadow (if a shadow length + solar elevation are given) else aspect-default."""
    x0, y0, x1, y1 = box_xyxy
    if x1 <= x0 or y1 <= y0 or m_per_px <= 0:
        raise ValueError(f"degenerate detection box {box_xyxy} / m_per_px={m_per_px} -- a reversed box "
                         "would silently bin as a tiny traversable rock (audit L24)")
    diameter_m = max(x1 - x0, y1 - y0) * m_per_px
    h_m, src = None, "aspect_default"
    # explicit None/positivity tests (audit L23) + a ZERO-length shadow means NO shadow was found --
    # falling through to the aspect default instead of a meaningless 0 m "shadow" height (audit M18)
    if shadow_length_px is not None and shadow_length_px > 0 and \
            sun_elevation_deg is not None and sun_elevation_deg > 0:
        h_m = shadow_height_m(shadow_length_px * m_per_px, sun_elevation_deg); src = "shadow"
    return classify(diameter_m, height_m=h_m, confidence=score, height_source=src)
