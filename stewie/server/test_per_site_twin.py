"""[REQ:DT-04] the observed digital twin + its world journal are keyed by (site, depth-source profile),
not hard-coded to Haworth. A second imported site accumulates and reloads its OWN observed twin,
independent of Haworth -- verified here on a real second DEM bundle (shackleton_rim, a 2000x2000 imported
tile on disk), plus a per-source key. Backward-compat: the default (haworth, stereo_sgbm) twin keeps its
own global + haworth.journal."""
import importlib

import numpy as np
import pytest

_SECOND_SITE = "shackleton_rim"     # a real imported DEM bundle distinct from haworth (verified on disk)


@pytest.fixture()
def state(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    from stewie.server import state as S
    importlib.reload(S)
    monkeypatch.setattr(S, "_TWIN", None)
    monkeypatch.setattr(S, "_TWINS", {})
    yield S


def test_a_second_site_has_an_independent_observed_twin(state):
    S = state
    haw = S.twin("haworth")
    shk = S.twin(_SECOND_SITE)
    assert haw is not shk                                 # independent instances, not the one global twin
    # real, distinct base DEMs (both imported 2000x2000 tiles; different terrain)
    assert haw.base.shape == shk.base.shape == (2000, 2000)
    assert not np.array_equal(haw.base, shk.base)
    # patch ONLY the second site's observed twin
    shk.apply_patch(np.full((3, 3), float(shk.base[10, 10]) + 5.0), origin_rc=(10, 10), provenance="dt04")
    assert shk.observed_mask()[10:13, 10:13].all()
    assert not haw.observed_mask().any(), "the haworth twin must be untouched by a second-site resync"


def test_the_second_site_reloads_its_own_observed_twin_durably(state, monkeypatch):
    S = state
    shk = S.twin(_SECOND_SITE)
    shk.apply_patch(np.full((3, 3), float(shk.base[20, 20]) + 7.0), origin_rc=(20, 20), provenance="dt04")
    assert shk.observed_mask()[20:23, 20:23].all()
    # cold reload: clear both caches and rebuild -> the second site restores from ITS OWN journal.
    monkeypatch.setattr(S, "_TWIN", None)
    monkeypatch.setattr(S, "_TWINS", {})
    shk2 = S.twin(_SECOND_SITE)
    assert shk2 is not shk
    assert shk2.observed_mask()[20:23, 20:23].all(), "the second site's patch must persist in its journal"
    # and a freshly-built haworth twin never saw that patch (separate journal).
    haw = S.twin("haworth")
    assert not haw.observed_mask().any()


def test_per_source_key_forks_the_twin(state):
    S = state
    a = S.twin("haworth", "stereo_sgbm")     # the default source -> the _TWIN global
    b = S.twin("haworth", "lidar")           # a different depth-source profile -> its own twin + journal
    assert a is not b
    b.apply_patch(np.full((2, 2), float(b.base[5, 5]) + 3.0), origin_rc=(5, 5), provenance="dt04")
    assert b.observed_mask()[5:7, 5:7].all()
    assert not a.observed_mask().any(), "the default-source twin must be independent of the lidar-source twin"


def test_journals_are_written_per_site_under_the_twin_dir(state, tmp_path):
    S = state
    S.twin("haworth").apply_patch(np.full((2, 2), 1.0), origin_rc=(0, 0), provenance="dt04")
    S.twin(_SECOND_SITE).apply_patch(np.full((2, 2), 1.0), origin_rc=(0, 0), provenance="dt04")
    twindir = tmp_path / "twin"
    names = {p.name for p in twindir.glob("*.journal")}
    assert "haworth.journal" in names                     # the default keeps its historical filename
    assert any("shackleton" in n for n in names)          # the second site has its own journal file
