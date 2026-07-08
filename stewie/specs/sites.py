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
    Site("de_gerlache_rim", "de Gerlache Rim (Site11)", -88.4138, -69.3063, artemis_candidate=True,
         bundle_dir=_bundle("de_gerlache_rim_10km_5m"),
         note="PGDA Product 78 Site11; 10 km / 5 m tile, imported 2026-07-07"),
    Site("nobile_rim", "Nobile Rim 1 (Site06)", -85.484, 39.965, artemis_candidate=True,
         bundle_dir=_bundle("nobile_rim1_10km_5m"),
         note="PGDA Product 78 Site06; max-relief 10 km tile, imported 2026-06-10"),
    Site("malapert_massif", "Malapert Massif (Site23)", -85.6471, -1.7347, artemis_candidate=True,
         bundle_dir=_bundle("malapert_massif_10km_5m"),
         note="PGDA Product 78 Site23; 10 km / 5 m tile, imported 2026-07-07"),
    Site("leibnitz_beta", "Leibnitz Beta Plateau (Site20)", -85.5017, 28.4444, artemis_candidate=True,
         bundle_dir=_bundle("leibnitz_beta_10km_5m"),
         note="PGDA Product 78 Site20; 10 km / 5 m tile, imported 2026-07-07"),
    Site("amundsen_rim", "Amundsen Rim", -84.4, 69.0, artemis_candidate=True),
    Site("faustini_rim", "Faustini Rim A", -87.0, 77.0, artemis_candidate=True),
    Site("peak_near_shackleton", "Peak near Shackleton (Site07)", -88.9953, 113.2011, artemis_candidate=True,
         bundle_dir=_bundle("peak_near_shackleton_10km_5m"),
         note="PGDA Product 78 Site07; 10 km / 5 m tile, imported 2026-07-07"),
    Site("connecting_ridge", "Connecting Ridge (Site01)", -89.2920, -117.7676, artemis_candidate=True,
         bundle_dir=_bundle("connecting_ridge_10km_5m"),
         note="PGDA Product 78 Site01; 10 km / 5 m tile, imported 2026-07-07"),
    Site("nobile_rim2", "Nobile Rim 2 (DM2)", -84.0382, 58.3314, artemis_candidate=True,
         bundle_dir=_bundle("nobile_rim2_10km_5m"),
         note="PGDA Product 78 DM2; 10 km / 5 m tile, imported 2026-07-07"),
    Site("shoemaker", "Shoemaker Crater", -87.0462, 56.8443, artemis_candidate=True,
         bundle_dir=_bundle("shoemaker_10km_5m"),
         note="PGDA Product 78 Shoemaker; 10 km / 5 m tile, imported 2026-07-07"),
)}


def get_site(name: str) -> Site:
    return SITES[name]


def site_latlon(name: str) -> tuple:
    """#274: the (lat_deg, lon_deg) of a site for solar geometry, falling back to Haworth for an unknown
    name. Used by the raster-overlay + globe-layer sun resolution so mission-time shadows follow the
    CHOSEN site (REG-01) instead of a hardcoded Haworth latitude -- mirrors ephemeris.py's correct usage
    (both lat AND lon feed sun_az_el's hour angle)."""
    if name and name.startswith("adhoc_"):
        # PLAN ANYWHERE (#30): an ad-hoc site's sun geometry must use ITS OWN lat/lon, not fall back to
        # Haworth -- else off-site shadows/illumination are computed at the wrong latitude. Deferred import
        # to avoid a sites<->adhoc_dem cycle.
        from stewie.terrain.adhoc_dem import parse_adhoc_site
        return parse_adhoc_site(name)
    s = SITES.get(name) or SITES["haworth"]
    return s.lat_deg, s.lon_deg


def site_rows() -> list:
    """UI rows: name, label, center, candidate flag, and the HONEST imported state."""
    return [{"name": s.name, "label": s.label, "lat": s.lat_deg, "lon": s.lon_deg,
             "artemis_candidate": s.artemis_candidate, "imported": s.bundle_dir is not None,
             "note": s.note} for s in SITES.values()]
