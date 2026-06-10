"""#49: the site registry -- where STEWIE can plan, and what data each site carries.

Haworth is the IMPORTED site (the 10 km / 5 m LOLA polar-stereographic bundle under
samples/lunar_dem/haworth_10km_5m). The other entries are the NASA Artemis III candidate
regions (the 2022 announcement, refined 2024) -- REAL records with selenographic centers,
whose DEM bundles are NOT yet imported; ``bundle_dir is None`` says so honestly. Import path:
the same dem_import pipeline that produced the Haworth bundle (LOLA polar products via PGDA /
PDS; see docs/map_reference.md for the sources).

Centers are approximate region centers (degrees, selenographic) for globe navigation -- the
authoritative landing-area polygons live with NASA; a bundle import pins the exact tile.
"""
from __future__ import annotations

import dataclasses
import os

_HAWORTH_BUNDLE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "samples", "lunar_dem", "haworth_10km_5m")


@dataclasses.dataclass(frozen=True)
class Site:
    name: str
    label: str
    lat_deg: float
    lon_deg: float
    artemis_candidate: bool = False
    #: the imported DEM bundle directory, or None (NOT imported -- the honest state)
    bundle_dir: str | None = None
    note: str = ""


SITES: dict = {s.name: s for s in (
    Site("haworth", "Haworth (work site)", -86.33, -25.51, artemis_candidate=True,
         bundle_dir=_HAWORTH_BUNDLE if os.path.isdir(_HAWORTH_BUNDLE) else None,
         note="the imported 10 km / 5 m LOLA bundle; the committed STEWIE work site"),
    Site("shackleton_rim", "Shackleton rim / Connecting Ridge", -89.7, -137.0, artemis_candidate=True,
         note="near-continuous illumination ridge between Shackleton and de Gerlache"),
    Site("de_gerlache_rim", "de Gerlache Rim 1/2", -88.5, -68.0, artemis_candidate=True),
    Site("nobile_rim", "Nobile Rim 1/2", -85.2, 36.0, artemis_candidate=True,
         note="the Artemis III VIPER-adjacent region"),
    Site("malapert_massif", "Malapert Massif", -85.9, -2.0, artemis_candidate=True),
    Site("leibnitz_beta", "Leibnitz Beta Plateau", -85.4, 31.0, artemis_candidate=True),
    Site("amundsen_rim", "Amundsen Rim", -84.4, 69.0, artemis_candidate=True),
    Site("faustini_rim", "Faustini Rim A", -87.0, 77.0, artemis_candidate=True),
    Site("peak_near_shackleton", "Peak near Shackleton", -88.8, -114.0, artemis_candidate=True),
)}


def get_site(name: str) -> Site:
    return SITES[name]


def site_rows() -> list:
    """UI rows: name, label, center, candidate flag, and the HONEST imported state."""
    return [{"name": s.name, "label": s.label, "lat": s.lat_deg, "lon": s.lon_deg,
             "artemis_candidate": s.artemis_candidate, "imported": s.bundle_dir is not None,
             "note": s.note} for s in SITES.values()]
