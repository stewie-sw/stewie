"""#49: the SITE REGISTRY -- Haworth + the NASA Artemis III candidate regions as real entries.

Haworth carries the imported 10 km / 5 m LOLA bundle; the other candidates are REAL registry
records (name, selenographic center, candidate status) whose DEM bundles are NOT yet imported --
the registry says so honestly instead of pretending. All Artemis III candidates are SOUTH-polar.
"""
from stewie.specs import sites as S


def test_haworth_is_the_one_imported_site():
    h = S.get_site("haworth")
    assert h.bundle_dir and h.lat_deg < -86.0
    imported = [s for s in S.SITES.values() if s.bundle_dir]
    assert [s.name for s in imported] == ["haworth"]


def test_artemis_candidates_are_south_polar_and_unimported():
    cands = [s for s in S.SITES.values() if s.artemis_candidate]
    assert len(cands) >= 8
    assert all(s.lat_deg < -80.0 for s in cands)           # all south-polar (no N-pole candidates)
    for s in cands:
        if s.name != "haworth":
            assert s.bundle_dir is None                    # honest: not imported yet


def test_registry_serves_the_ui():
    rows = S.site_rows()
    assert any(r["name"] == "haworth" and r["imported"] for r in rows)
    assert any(r["name"] == "shackleton_rim" and not r["imported"] for r in rows)
