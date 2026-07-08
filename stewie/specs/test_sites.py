"""#49: the SITE REGISTRY -- Haworth + the NASA Artemis III candidate regions as real entries.

Haworth carries the imported 10 km / 5 m LOLA bundle; the other candidates are REAL registry
records (name, selenographic center, candidate status) whose DEM bundles are NOT yet imported --
the registry says so honestly instead of pretending. All Artemis III candidates are SOUTH-polar.
"""
from stewie.specs import sites as S


def test_committed_bundles_are_imported():
    h = S.get_site("haworth")
    assert h.bundle_dir and h.lat_deg < -86.0
    # `bundle_dir` resolves to the on-disk path IFF the bundle is present (sites._bundle), so the imported
    # set is env-dependent: the 3 bundles committed to git are present on ANY checkout, while the 7 PGDA
    # Product-78 sites (Site01/07/11/20/23, DM2, Shoemaker) are host-built / fetched-on-install (MT-01: their
    # ~66 MB rasters are NOT committed), so they are imported where present but honestly absent on a bare
    # checkout / CI. Assert the always-present committed set as a subset (the registry never fabricates).
    imported = {s.name for s in S.SITES.values() if s.bundle_dir}
    assert {"haworth", "nobile_rim", "shackleton_rim"} <= imported


def test_artemis_candidates_are_south_polar():
    cands = [s for s in S.SITES.values() if s.artemis_candidate]
    assert len(cands) >= 8
    assert all(s.lat_deg < -80.0 for s in cands)           # all south-polar (no N-pole candidates)
    # the registry carries the PGDA Product-78 sites as ENTRIES regardless of whether their host-built bundle
    # is present on this checkout (config vs disk are separate concerns).
    names = {s.name for s in cands}
    assert {"malapert_massif", "leibnitz_beta", "peak_near_shackleton", "connecting_ridge"} <= names


def test_registry_serves_the_ui():
    rows = S.site_rows()
    assert any(r["name"] == "haworth" and r["imported"] for r in rows)
    assert any(r["name"] == "shackleton_rim" and r["imported"] for r in rows)   # committed bundle
    # amundsen_rim carries no bundle name at all -> never imported. The PGDA Product-78 sites are registered
    # but their `imported` flag is env-dependent (host-built bundle), so it is not asserted here.
    assert any(r["name"] == "amundsen_rim" and not r["imported"] for r in rows)
    assert {"malapert_massif", "connecting_ridge", "shoemaker"} <= {r["name"] for r in rows}
