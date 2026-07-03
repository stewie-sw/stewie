"""[REQ:EG-03] DB/branch isolation by mode: each mode resolves a physically separate store root; no non-LIVE
session reaches the live store; writing the live store requires LIVE authority; a real save under a non-LIVE
mode never lands in the live store."""
import os

import pytest

from stewie.contracts.governance import EnvironmentMode, ModeAuthorityError
from stewie.twin import terrain_memory as TM
from stewie.twin.store_isolation import (
    load_site_for_mode,
    require_live_store_write,
    save_site_for_mode,
    store_key,
    store_root,
)


def test_eg03_only_live_maps_to_the_live_store():  # [REQ:EG-03]
    assert store_key(EnvironmentMode.LIVE) == "live"
    for m in EnvironmentMode:
        if m is not EnvironmentMode.LIVE:
            assert store_key(m) != "live"


def test_eg03_store_roots_distinct_live_separate_and_pure():  # [REQ:EG-03]
    roots = {m: store_root(m, "/data") for m in EnvironmentMode}
    live = roots[EnvironmentMode.LIVE]
    assert all(roots[m] != live for m in EnvironmentMode if m is not EnvironmentMode.LIVE)
    assert store_root(EnvironmentMode.LIVE, "/data") == live                     # pure


def test_eg03_live_store_write_requires_live_mode():  # [REQ:EG-03]
    require_live_store_write(EnvironmentMode.LIVE)                                # ok
    for m in (EnvironmentMode.DEV, EnvironmentMode.TRAINING, EnvironmentMode.REHEARSAL,
              EnvironmentMode.REPLAY, EnvironmentMode.ARCHIVE):
        with pytest.raises(ModeAuthorityError):
            require_live_store_write(m)


def test_eg03_save_isolates_to_the_mode_store(tmp_path):  # [REQ:EG-03]
    mem = TM.TerrainMemory(site="haworth", rows=4, cols=4, cell_m=0.5)           # empty (opaque) terrain
    p = save_site_for_mode(EnvironmentMode.TRAINING, str(tmp_path), mem)
    assert os.path.join("training", "terrain_memory") in p                       # under the training store
    assert os.sep + "live" + os.sep not in p                                     # never the live store
    # round-trips from the SAME mode store, but is absent from the live store (isolation proven)
    assert load_site_for_mode(EnvironmentMode.TRAINING, str(tmp_path), "haworth") is not None
    assert load_site_for_mode(EnvironmentMode.LIVE, str(tmp_path), "haworth") is None
