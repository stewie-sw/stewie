"""[REQ:DT-04] SR-03: one site must resolve to exactly ONE observed twin, and two DIFFERENT sites must
never share a journal.

The 2026-07-28 review found `state.twin()` dispatched on the RAW site string while `_build_twin` derived
the journal filename through `_safe_site()`. So `twin("Haworth")` missed the default fast path, got its
own store object and its own lock, and then wrote the SAME `haworth.journal` as the default twin. Two
writers, one append-only journal -> interleaved versions -> `TwinStore.from_journal` raises
`ValueError: replay hash mismatch` on the next cold restore, permanently. `/twin/version` and
`/twin/history` 500 and every plan silently drops the observed layer.

The mirror-image defect: `_safe_site` mapped every non-alphanumeric run to "_", so the distinct ad-hoc
sites `adhoc_-88.5_-25.5` and `adhoc_88.5_25.5` (opposite hemispheres) both sanitized to one stem --
one site's observed patches served as another's.

`world_state.py` already fixed this class for TerrainMemory (#282); the twin path had not.

Run: <venv>/bin/python -m pytest stewie/server/test_twin_site_normalization.py -q
"""
from __future__ import annotations

import importlib
import json

import pytest


@pytest.fixture()
def st(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    from stewie.server import state as ST
    importlib.reload(ST)
    yield ST
    ST._TWIN = None
    ST._TWINS.clear()


@pytest.mark.parametrize("spelling", ["Haworth", "HAWORTH", " haworth ", "haworth "])
def test_case_and_whitespace_resolve_to_the_default_twin(st, spelling):
    """The SR-03 core: a re-spelled default site must be the SAME object, not a second writer on one journal."""
    canonical = st.twin()
    assert st.twin(spelling) is canonical, (
        f"{spelling!r} built a SECOND store over the same journal -> guaranteed replay hash mismatch")


def test_respelled_site_does_not_fork_the_journal(st, tmp_path):
    """Two spellings must produce exactly one journal file, with one writer."""
    st.twin("haworth")
    st.twin("Haworth")
    jdir = tmp_path / "twin"
    journals = sorted(p.name for p in jdir.glob("*.journal")) if jdir.exists() else []
    assert journals.count("haworth.journal") <= 1
    stores = {id(st.twin("haworth")), id(st.twin("Haworth")), id(st.twin(" HAWORTH "))}
    assert len(stores) == 1, "one site resolved to multiple TwinStore objects"


def test_source_spelling_also_normalizes(st):
    """(site, source) is the DT-04 key -- a re-spelled SOURCE must not fork it either."""
    a = st.twin("haworth", "Stereo_SGBM")
    b = st.twin("haworth", "stereo_sgbm")
    assert a is b


def test_boundary_underscores_do_not_alias_a_canonical_site_or_source(st):
    """Trimming filename punctuation must not collapse a distinct open-world identifier."""
    canonical = st.twin("haworth", "stereo_sgbm")
    odd_site = st.twin("_haworth_", "stereo_sgbm")
    odd_source = st.twin("haworth", "_stereo_sgbm_")
    assert odd_site is not canonical
    assert odd_source is not canonical
    assert len({
        canonical.journal_path,
        odd_site.journal_path,
        odd_source.journal_path,
    }) == 3


@pytest.mark.parametrize("source", ["Stereo_SGBM", "_stereo_sgbm_"])
def test_raw_source_legacy_filename_is_not_orphaned_behind_default_cache(st, tmp_path, source):
    """The old raw source comparison wrote a second default-source path for case-only spellings."""
    st.twin("haworth", "stereo_sgbm")  # populate the canonical default cache first
    legacy = tmp_path / "twin" / "haworth__stereo_sgbm.journal"
    legacy.write_text("")

    with pytest.raises(st.TwinJournalMigrationRequired, match="raw-source legacy"):
        st.twin("haworth", source)


def test_distinct_adhoc_sites_do_not_collide(st):
    """Opposite-hemisphere ad-hoc sites must NOT share a store: sanitizing away the sign is data loss."""
    north = st.twin("adhoc_88500_25500")
    south = st.twin("adhoc_-88500_-25500")
    assert north is not south, "two distinct sites collapsed onto one observed twin"


def test_distinct_adhoc_sites_get_distinct_journals(st):
    """The on-disk consequence of the collision: distinct sites must be bound to distinct journal paths.

    Asserted on the resolved `journal_path`, not on file existence -- `TwinStore` creates the file
    lazily on the first edit, so an unwritten store has no file yet. The binding is the property that
    matters: two sites sharing one path is the corruption, whether or not either has written yet.
    """
    north = st.twin("adhoc_88500_25500").journal_path
    south = st.twin("adhoc_-88500_-25500").journal_path
    assert north and south
    assert north != south, f"two distinct sites bound to one journal: {north}"


def test_default_journal_filename_is_unchanged(st):
    """Back-compat: the default twin must keep its `haworth.journal` (existing durable state on disk)."""
    assert st.twin().journal_path.endswith("/haworth.journal")
    assert st.twin("Haworth").journal_path.endswith("/haworth.journal")


@pytest.mark.parametrize("site", ["adhoc_88500_25500", "adhoc_-88500_-25500"])
def test_ambiguous_legacy_journal_requires_explicit_migration(st, tmp_path, site):
    """Do not silently orphan or adopt history written under the old collision-prone filename."""
    legacy_dir = tmp_path / "twin"
    legacy_dir.mkdir()
    legacy = legacy_dir / "adhoc_88500_25500.journal"
    legacy.write_text("")

    with pytest.raises(st.TwinJournalMigrationRequired, match="migrate/quarantine"):
        st.twin(site)


def test_old_and_new_journals_still_require_legacy_resolution(st, tmp_path):
    """A new-path file is not evidence that the colliding legacy file was consciously resolved."""
    site = "adhoc_-88500_-25500"
    twin_dir = tmp_path / "twin"
    twin_dir.mkdir()
    legacy = twin_dir / "adhoc_88500_25500.journal"
    legacy.write_text("")
    new = twin_dir / f"{st._safe_site(site)}.journal"
    new.write_text("")
    new.with_name(new.name + ".identity.json").write_text(json.dumps({
        "schema": st._TWIN_IDENTITY_SCHEMA,
        "site": site,
        "source": st.DEFAULT_TWIN_SOURCE,
    }))

    with pytest.raises(st.TwinJournalMigrationRequired, match="no identity marker"):
        st.twin(site)


def test_fresh_adhoc_journal_gets_a_durable_identity_epoch(st):
    """New collision-safe paths carry explicit ownership so a restart can distinguish sign variants."""
    site = "adhoc_-88500_-25500"
    journal = st.twin(site).journal_path
    marker = journal + ".identity.json"
    with open(marker, encoding="utf-8") as f:
        identity = json.load(f)
    assert identity == {
        "schema": st._TWIN_IDENTITY_SCHEMA,
        "site": site,
        "source": st.DEFAULT_TWIN_SOURCE,
    }
    st._TWINS.clear()
    assert st.twin(site).journal_path == journal
