"""DEM source registry (TW-01/02/03, M11): the catalog of REAL public lunar Digital Elevation Models
selectable as STEWIE base layers. One source of truth for the cockpit layer selector, the ingest
dispatch, and the THIRD_PARTY provenance/license audit (#124).

Discipline (no synthetic terrain): the 11 real PGDA Product-78 site tiles carved into
samples/lunar_dem (#43: Haworth + 10 Artemis III candidates) are bundled; every other product is
REAL-DATA-GATED -- you supply a downloaded file (path/env), exactly like dart.dem_import and the
Katwijk loaders. Lunar framing is invariant: MOON_ME, mean radius R = 1737400 m (NOT an Earth datum);
products are either south-polar stereographic (IAU_2015:30135) or simple-cylindrical (equirectangular).

`ingest` is HONEST about per-source readiness:
  - dem_import   : ingested today (dart.dem_import parses the GeoTIFF in the polar same-frame lane)
  - reproject    : needs non-polar reprojection into the local metric frame (TW-02, partial)
  - gdal_cub     : ISIS .cub -> needs GDAL/ISIS conversion before ingest (gated)
  - render_only  : visualization product, NOT metric-controlled -> not offered for mission planning
"""
from __future__ import annotations

from dataclasses import dataclass

_MOON_ME_RADIUS_M = 1737400        # mean lunar radius (MOON_ME); the lunar vertical datum

# R-M7 (A3a): the LRO NAC Shape-from-Shading (photoclinometry) citation, verified against
# design/DEM_CROSSREF_2026-06-11.md row 4 (Alexandrov & Beyer 2018, Earth & Space Sci. 5, 652).
# This is the SfS DEM's authoritative provenance -- it is NOT the LOLA Product-78 (Barker/Mazarico)
# citation the LOLA tiles carry (a different instrument + method entirely). Shared by the 1 m source
# row and the committed 2 km drive-site crop so both name the same product + method.
_SFS_CITATION = ("USGS Astrogeology LRO NAC photoclinometry (Shape-from-Shading) DEM 1 m; "
                 "method Alexandrov & Beyer 2018 (Earth & Space Sci. 5:652)")


@dataclass(frozen=True)
class DemSource:
    id: str
    name: str
    instrument: str
    resolution_m: float
    coverage: str
    crs: str                       # south_polar_stereographic | simple_cylindrical | render_only
    fmt: str                       # geotiff_cog | isis_cub | png_set
    access_url: str
    license: str
    ingest: str                    # dem_import | reproject | gdal_cub | render_only
    bundled: bool = False
    body: str = "moon"
    frame_radius_m: int = _MOON_ME_RADIUS_M
    notes: str = ""
    #: R-M7 (A3a): the authoritative product/method citation. Additive + default-empty, so every
    #: pre-existing row and its tests are unaffected until populated. Carried verbatim into a built
    #: bundle's ``dem_provenance.citation`` (scripts/build_from_dem.build_from_source), so the map's
    #: "About this DEM" provenance is machine-sourced from the registry, not hand-typed per bundle.
    citation: str = ""

    @property
    def planning_grade(self) -> bool:
        """True iff the product is metric-controlled and thus valid for MISSION PLANNING (a render-only
        visualization product is for display, never for siting/feasibility)."""
        return self.crs != "render_only" and self.ingest != "render_only"


# Provenance: USGS Astropedia, NASA PGDA, NASA PDS Geosciences Node, NASA SVS, LROC (all public-domain
# US-government data; verify each product's page for the authoritative citation before redistribution).
_CATALOG: tuple[DemSource, ...] = (
    DemSource(
        id="haworth_10km_5m", name="Haworth 10 km tile (bundled default)",
        instrument="LOLA + LROC NAC SfS", resolution_m=5.0, coverage="Haworth crater, ~10 km",
        crs="south_polar_stereographic", fmt="geotiff_cog",
        access_url="https://astrogeology.usgs.gov/search/map/moon_lro_lola_dem_118m",
        license="public domain (US Gov)", ingest="dem_import", bundled=True,
        notes="The shipped sample STEWIE loads by default (state.moon_dem). Real LOLA/NAC-derived."),
    DemSource(
        id="nobile_rim1_10km_5m", name="Nobile Rim 1 (Site06) 10 km tile",
        instrument="LOLA", resolution_m=5.0, coverage="Nobile Rim 1 (Artemis III candidate), ~10 km",
        crs="south_polar_stereographic", fmt="geotiff_cog",
        access_url="https://pgda.gsfc.nasa.gov/products/78",
        license="public domain (US Gov)", ingest="dem_import", bundled=True,
        notes="PGDA Product 78 Site06; real LOLA polar-stereographic 10 km / 5 m tile carved by "
              "scripts/build_from_dem.py (Lane A), imported 2026-06-10. See stewie.specs.sites."),
    DemSource(
        id="shackleton_rim_10km_5m", name="Shackleton Rim (Site04) 10 km tile",
        instrument="LOLA", resolution_m=5.0, coverage="Shackleton crater rim (Artemis III candidate), ~10 km",
        crs="south_polar_stereographic", fmt="geotiff_cog",
        access_url="https://pgda.gsfc.nasa.gov/products/78",
        license="public domain (US Gov)", ingest="dem_import", bundled=True,
        notes="PGDA Product 78 Site04; real LOLA polar-stereographic max-relief 10 km / 5 m tile "
              "(~4.4 km relief) carved by scripts/build_from_dem.py (Lane A), imported 2026-06-10."),
    # These 8 Artemis-candidate tiles are real LOLA products available via the host bake / pending the
    # host-mount (task #76); their 47 MB DEM bundles are NOT repo-committed, so bundled=False (the flag is
    # metadata-only: a cockpit badge + a /dem/sources field, it does NOT gate site serving). Only the three
    # committed tiles above (haworth, nobile_rim1, shackleton_rim) ship a real on-disk bundle. planning_grade
    # stays True (it is derived from crs/ingest, independent of bundled).
    DemSource(
        id="connecting_ridge_10km_5m", name="Connecting Ridge (Site01) 10 km tile",
        instrument="LOLA", resolution_m=5.0, coverage="Connecting Ridge (Artemis III candidate), ~10 km",
        crs="south_polar_stereographic", fmt="geotiff_cog",
        access_url="https://pgda.gsfc.nasa.gov/products/78",
        license="public domain (US Gov)", ingest="dem_import", bundled=False,
        notes="PGDA Product 78 Site01; real LOLA polar-stereographic 10 km / 5 m tile carved by "
              "scripts/build_from_dem.py (Lane A), imported 2026-07-07. See stewie.specs.sites."),
    DemSource(
        id="de_gerlache_rim_10km_5m", name="de Gerlache Rim (Site11) 10 km tile",
        instrument="LOLA", resolution_m=5.0, coverage="de Gerlache Rim (Artemis III candidate), ~10 km",
        crs="south_polar_stereographic", fmt="geotiff_cog",
        access_url="https://pgda.gsfc.nasa.gov/products/78",
        license="public domain (US Gov)", ingest="dem_import", bundled=False,
        notes="PGDA Product 78 Site11; real LOLA polar-stereographic 10 km / 5 m tile carved by "
              "scripts/build_from_dem.py (Lane A), imported 2026-07-07. See stewie.specs.sites."),
    DemSource(
        id="leibnitz_beta_10km_5m", name="Leibnitz Beta Plateau (Site20) 10 km tile",
        instrument="LOLA", resolution_m=5.0, coverage="Leibnitz Beta Plateau (Artemis III candidate), ~10 km",
        crs="south_polar_stereographic", fmt="geotiff_cog",
        access_url="https://pgda.gsfc.nasa.gov/products/78",
        license="public domain (US Gov)", ingest="dem_import", bundled=False,
        notes="PGDA Product 78 Site20; real LOLA polar-stereographic 10 km / 5 m tile carved by "
              "scripts/build_from_dem.py (Lane A), imported 2026-07-07. See stewie.specs.sites."),
    DemSource(
        id="malapert_massif_10km_5m", name="Malapert Massif (Site23) 10 km tile",
        instrument="LOLA", resolution_m=5.0, coverage="Malapert Massif (Artemis III candidate), ~10 km",
        crs="south_polar_stereographic", fmt="geotiff_cog",
        access_url="https://pgda.gsfc.nasa.gov/products/78",
        license="public domain (US Gov)", ingest="dem_import", bundled=False,
        notes="PGDA Product 78 Site23; real LOLA polar-stereographic 10 km / 5 m tile carved by "
              "scripts/build_from_dem.py (Lane A), imported 2026-07-07. See stewie.specs.sites."),
    DemSource(
        id="nobile_rim2_10km_5m", name="Nobile Rim 2 (DM2) 10 km tile",
        instrument="LOLA", resolution_m=5.0, coverage="Nobile Rim 2 (Artemis III candidate), ~10 km",
        crs="south_polar_stereographic", fmt="geotiff_cog",
        access_url="https://pgda.gsfc.nasa.gov/products/78",
        license="public domain (US Gov)", ingest="dem_import", bundled=False,
        notes="PGDA Product 78 DM2; real LOLA polar-stereographic 10 km / 5 m tile carved by "
              "scripts/build_from_dem.py (Lane A), imported 2026-07-07. See stewie.specs.sites."),
    DemSource(
        id="peak_near_shackleton_10km_5m", name="Peak near Shackleton (Site07) 10 km tile",
        instrument="LOLA", resolution_m=5.0, coverage="Peak near Shackleton (Artemis III candidate), ~10 km",
        crs="south_polar_stereographic", fmt="geotiff_cog",
        access_url="https://pgda.gsfc.nasa.gov/products/78",
        license="public domain (US Gov)", ingest="dem_import", bundled=False,
        notes="PGDA Product 78 Site07; real LOLA polar-stereographic 10 km / 5 m tile carved by "
              "scripts/build_from_dem.py (Lane A), imported 2026-07-07. See stewie.specs.sites."),
    DemSource(
        id="shoemaker_10km_5m", name="Shoemaker Crater 10 km tile",
        instrument="LOLA", resolution_m=5.0, coverage="Shoemaker Crater (Artemis III candidate), ~10 km",
        crs="south_polar_stereographic", fmt="geotiff_cog",
        access_url="https://pgda.gsfc.nasa.gov/products/78",
        license="public domain (US Gov)", ingest="dem_import", bundled=False,
        notes="PGDA Product 78 Shoemaker; real LOLA polar-stereographic 10 km / 5 m tile carved by "
              "scripts/build_from_dem.py (Lane A), imported 2026-07-07. See stewie.specs.sites."),
    DemSource(
        id="de_gerlache_kocher_10km_5m", name="de Gerlache-Kocher Massif (Site42) 10 km tile",
        instrument="LOLA", resolution_m=5.0,
        coverage="de Gerlache-Kocher Massif (Artemis III candidate), ~10 km",
        crs="south_polar_stereographic", fmt="geotiff_cog",
        access_url="https://pgda.gsfc.nasa.gov/products/78",
        license="public domain (US Gov)", ingest="dem_import", bundled=False,
        notes="PGDA Product 78 Site42; real LOLA polar-stereographic max-relief 10 km / 5 m tile "
              "carved by scripts/build_from_dem.py (Lane A), imported 2026-07-09. See stewie.specs.sites."),
    DemSource(
        id="pgda_sp_cog", name="PGDA Lunar South Pole LOLA (COG)",
        instrument="LOLA", resolution_m=5.0, coverage="south pole, large-area",
        crs="south_polar_stereographic", fmt="geotiff_cog",
        access_url="https://pgda.gsfc.nasa.gov/products/78",
        license="public domain (US Gov)", ingest="dem_import",
        notes="Cloud-optimized GeoTIFFs, south-polar stereographic X/Y m, MOON_ME -- the product "
              "dem_import already parses same-frame (no reprojection)."),
    DemSource(
        id="lola_sp", name="LRO LOLA South Pole DEM",
        instrument="LOLA", resolution_m=60.0, coverage="±60°→pole regional",
        crs="south_polar_stereographic", fmt="geotiff_cog",
        access_url="https://pgda.gsfc.nasa.gov/products/90",
        license="public domain (US Gov)", ingest="dem_import",
        notes="LOLA polar DEM (Barker et al. ~512 ppd / ~60 m); polar same-frame lane."),
    DemSource(
        id="lola_global_118m", name="Moon LRO LOLA DEM 118 m (global)",
        instrument="LOLA", resolution_m=118.0, coverage="global ±90°",
        crs="simple_cylindrical", fmt="geotiff_cog",
        access_url="https://astrogeology.usgs.gov/search/map/moon_lro_lola_dem_118m",
        license="public domain (US Gov)", ingest="reproject",
        notes="Smith et al. 2010. Equirectangular global -> needs non-polar reprojection (TW-02) + "
              "windowed/tiled access (TW-03) for product paths."),
    DemSource(
        id="lroc_nac_sfs_1m", name="LRO NAC Photoclinometry (SfS) DEM 1 m",
        instrument="LROC NAC", resolution_m=1.0, coverage="local site (e.g. Haworth)",
        crs="south_polar_stereographic", fmt="geotiff_cog",
        access_url="https://astrogeology.usgs.gov/search/map/lunar_lro_nac_haworth_photoclinometry_dem_1m",
        license="public domain (US Gov)", ingest="dem_import", citation=_SFS_CITATION,
        notes="Absolutely controlled (registered to the global geodetic frame). High-res local detail "
              "above the coarse polar backbone -- register to the global frame on import. Method is "
              "photoclinometry / Shape-from-Shading (Alexandrov & Beyer 2018), NOT LOLA altimetry."),
    DemSource(
        id="haworth_sfs_2km_1m", name="Haworth SfS 2 km drive-site tile (1 m)",
        instrument="LROC NAC", resolution_m=1.0, coverage="Haworth crater drive site, ~2 km",
        crs="south_polar_stereographic", fmt="geotiff_cog",
        access_url="https://astrogeology.usgs.gov/search/map/lunar_lro_nac_haworth_photoclinometry_dem_1m",
        license="public domain (US Gov)", ingest="dem_import", bundled=True, citation=_SFS_CITATION,
        notes="Real LRO NAC Shape-from-Shading (photoclinometry) 1 m DEM; a 2 km @ 1 m crop taken "
              "INSIDE the SfS footprint (Haworth) by scripts/build_from_dem.py --source-id "
              "lroc_nac_sfs_1m, imported 2026-07-10. The driveable viz2 work-site base (SfS method "
              "Alexandrov & Beyer 2018) -- NOT a LOLA Product-78 tile. See stewie.specs.sites."),
    DemSource(
        id="pds_radar_sp", name="PDS Lunar Radar Altimetry South Pole DEM",
        instrument="Mini-RF / radar altimetry", resolution_m=150.0, coverage="south pole",
        crs="south_polar_stereographic", fmt="isis_cub",
        access_url="https://pds-geosciences.wustl.edu/",
        license="public domain (US Gov)", ingest="gdal_cub",
        notes="200 ppd (~150 m). Often distributed as ISIS .cub -> GDAL/ISIS conversion before ingest."),
    DemSource(
        id="cgi_moon_kit", name="NASA SVS CGI Moon Kit (visualization)",
        instrument="LOLA + LROC (rendered)", resolution_m=64.0, coverage="global (display)",
        crs="render_only", fmt="png_set",
        access_url="https://svs.gsfc.nasa.gov/4720",
        license="public domain (US Gov)", ingest="render_only",
        notes="Color + elevation maps optimized for 3D rendering software -- DISPLAY only, NOT "
              "metric-controlled; never use for siting/feasibility."),
)


def list_dem_sources() -> list[DemSource]:
    """The full lunar DEM catalog (bundled + real-data-gated)."""
    return list(_CATALOG)


def dem_source(source_id: str) -> DemSource:
    """The catalog entry for `source_id`, or KeyError if it is not a known lunar DEM product."""
    for s in _CATALOG:
        if s.id == source_id:
            return s
    raise KeyError(f"unknown lunar DEM source {source_id!r}; known: {[s.id for s in _CATALOG]}")
