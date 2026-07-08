"""#49: the SITE REGISTRY -- Haworth + the NASA Artemis III candidate regions as real entries.

Haworth carries the imported 10 km / 5 m LOLA bundle; the other candidates are REAL registry
records (name, selenographic center, candidate status) whose DEM bundles are NOT yet imported --
the registry says so honestly instead of pretending. All Artemis III candidates are SOUTH-polar.
"""
from stewie.specs import sites as S


def test_imported_sites_carry_real_bundles():
    h = S.get_site("haworth")
    assert h.bundle_dir and h.lat_deg < -86.0
    imported = sorted(s.name for s in S.SITES.values() if s.bundle_dir)
    # 2026-06-10 (haworth/nobile_rim/shackleton_rim) + the 2026-07-07 PGDA Product-78 batch (Site01/07/11/
    # 20/23, DM2, Shoemaker). amundsen_rim + faustini_rim have no fetched tile yet -> still unimported.
    assert imported == ["connecting_ridge", "de_gerlache_rim", "haworth", "leibnitz_beta",
                        "malapert_massif", "nobile_rim", "nobile_rim2", "peak_near_shackleton",
                        "shackleton_rim", "shoemaker"]


def test_artemis_candidates_are_south_polar():
    cands = [s for s in S.SITES.values() if s.artemis_candidate]
    assert len(cands) >= 8
    assert all(s.lat_deg < -80.0 for s in cands)           # all south-polar (no N-pole candidates)
    # 2026-07-07: most candidates now carry real PGDA Product-78 bundles; the registry still reports the
    # not-yet-fetched ones honestly (no fabricated DEM) rather than pretending they are imported.
    unimported = {s.name for s in cands if s.bundle_dir is None}
    assert len(unimported) >= 1
    assert unimported <= {"amundsen_rim", "faustini_rim"}


def test_registry_serves_the_ui():
    rows = S.site_rows()
    assert any(r["name"] == "haworth" and r["imported"] for r in rows)
    assert any(r["name"] == "shackleton_rim" and r["imported"] for r in rows)   # imported 2026-06-10
    assert any(r["name"] == "malapert_massif" and r["imported"] for r in rows)     # imported 2026-07-07 (Site23)
    assert any(r["name"] == "amundsen_rim" and not r["imported"] for r in rows)     # no PGDA tile fetched yet
