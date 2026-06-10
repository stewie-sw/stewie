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

_SAMPLES = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "samples", "lunar_dem")


def _bundle(name: str) -> str | None:
    d = os.path.join(_SAMPLES, name)
    return d if os.path.isdir(d) else None


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
         bundle_dir=_bundle("haworth_10km_5m"),
         note="the imported 10 km / 5 m LOLA bundle; the committed STEWIE work site"),
    # centers below are the BUNDLES' true tile centers (world_bounds inverse-projected)
    Site("shackleton_rim", "Shackleton rim (Site04)", -89.823, 158.213, artemis_candidate=True,
         bundle_dir=_bundle("shackleton_rim_10km_5m"),
         note="PGDA Product 78 Site04; max-relief 10 km tile (4.4 km relief), imported 2026-06-10"),
    Site("de_gerlache_rim", "de Gerlache Rim 1/2", -88.5, -68.0, artemis_candidate=True),
    Site("nobile_rim", "Nobile Rim 1 (Site06)", -85.484, 39.965, artemis_candidate=True,
         bundle_dir=_bundle("nobile_rim1_10km_5m"),
         note="PGDA Product 78 Site06; max-relief 10 km tile, imported 2026-06-10"),
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
