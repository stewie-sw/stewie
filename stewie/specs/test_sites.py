"""#49: the SITE REGISTRY -- Haworth + the NASA Artemis III candidate regions as real entries.

Haworth carries the imported 10 km / 5 m LOLA bundle; the other candidates are REAL registry
records (name, selenographic center, candidate status) whose DEM bundles are NOT yet imported --
the registry says so honestly instead of pretending. All Artemis III candidates are SOUTH-polar.
"""
from stewie.specs import sites as S


def test_three_sites_are_imported():
    h = S.get_site("haworth")
    assert h.bundle_dir and h.lat_deg < -86.0
    imported = sorted(s.name for s in S.SITES.values() if s.bundle_dir)
    assert imported == ["haworth", "nobile_rim", "shackleton_rim"]   # 2026-06-10 imports


def test_artemis_candidates_are_south_polar_and_unimported():
    cands = [s for s in S.SITES.values() if s.artemis_candidate]
    assert len(cands) >= 8
    assert all(s.lat_deg < -80.0 for s in cands)           # all south-polar (no N-pole candidates)
    unimported = [s for s in cands if s.bundle_dir is None]
    assert len(unimported) >= 5                            # honest: most candidates still lack bundles


def test_registry_serves_the_ui():
    rows = S.site_rows()
    assert any(r["name"] == "haworth" and r["imported"] for r in rows)
    assert any(r["name"] == "shackleton_rim" and r["imported"] for r in rows)   # imported 2026-06-10
    assert any(r["name"] == "malapert_massif" and not r["imported"] for r in rows)
