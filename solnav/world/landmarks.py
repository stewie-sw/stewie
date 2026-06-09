"""Persistent-vs-mutable landmark hierarchy (L1).

IMMUTABLE anchors -- crater rims, ridgelines, peaks, large boulders -- survive excavation and are the
ONLY safe global-localization references for an excavator that is actively destroying its local terrain.
MUTABLE features -- small rocks, spoil piles, trenches, berms -- are local-planning-only and must NEVER
be used as global anchors. Extracted from the orbital DEM (L0): topographic local maxima (peaks/rims) with
prominence, size-gated so only kilometer-/large-scale features are tagged immutable. Real DEM only.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.ndimage import maximum_filter, median_filter, minimum_filter


@dataclass(frozen=True)
class Landmark:
    id: int
    x: float
    y: float
    z: float
    kind: str            # peak | rim | ridge | boulder
    immutable: bool      # True = safe global anchor (survives excavation)
    prominence_m: float
    scale_m: float

    @property
    def is_global_anchor(self) -> bool:
        return self.immutable


def extract_persistent_landmarks(dem, dem_origin=(0.0, 0.0), *, neighborhood_m: float = 150.0,
                                 min_prominence_m: float = 20.0, immutable_scale_m: float = 100.0,
                                 max_landmarks: int = 200) -> list:
    """Topographic local maxima of the orbital DEM as IMMUTABLE anchors (peaks/rims). prominence =
    peak height above the local neighborhood minimum; immutable iff prominence >= min_prominence_m AND
    the feature scale (the neighborhood) >= immutable_scale_m -- i.e. far larger than any excavation
    footprint, so it survives terrain change. Returns the strongest landmarks, prominence-sorted."""
    z = np.asarray(dem[0], dtype=float)
    cell = float(dem[1])
    ox, oy = dem_origin
    # local maxima on a SMALL window (samples the crater rim / ridge crests, not just the single global
    # peak); prominence measured at the larger neighborhood scale (the immutability scale).
    peak_win = max(3, int(round(min(neighborhood_m / 4.0, 75.0) / cell)) | 1)
    big_win = max(3, int(round(neighborhood_m / cell)) | 1)
    locmax = (z == maximum_filter(z, size=peak_win))
    prominence = z - minimum_filter(z, size=big_win)
    # a real crest must also RISE above its surroundings -- otherwise FLAT ground beside a deep pit
    # ties maximum_filter and "prominence" merely measures the pit's depth, minting a bogus anchor on
    # featureless terrain (audit 2026-06-09). The MEDIAN is robust to the pit pulling the window down:
    # flat pit-edge cells sit AT their window median (excluded); true crests rise above it.
    rises = z >= median_filter(z, size=peak_win) + 0.1 * min_prominence_m
    rs, cs = np.where(locmax & (prominence >= min_prominence_m) & rises)
    cand = sorted(((float(prominence[r, c]), int(r), int(c)) for r, c in zip(rs, cs)), reverse=True)
    out = []
    immut = neighborhood_m >= immutable_scale_m
    for i, (prom, r, c) in enumerate(cand[:max_landmarks]):
        out.append(Landmark(id=i, x=c * cell + ox, y=r * cell + oy, z=float(z[r, c]),
                            kind="rim/peak", immutable=immut, prominence_m=prom, scale_m=neighborhood_m))
    return out


def split_by_persistence(landmarks) -> tuple:
    """Partition into (immutable global anchors, mutable local-only) -- the localization hierarchy."""
    immutable = [m for m in landmarks if m.immutable]
    mutable = [m for m in landmarks if not m.immutable]
    return immutable, mutable
