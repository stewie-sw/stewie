"""[REQ:SD-01] SD-01 third acceptance clause -- a before/after terrain transaction influences the NEXT plan.

The Surface-Design loop must let a STRUCTURE mutate the twin's terrain (the conserved, mass-conserving
cut/fill folded into the site's TerrainMemory by the SIM execute->remember loop,
``routers/executive.py::_remember_sim_terrain``) so that a SUBSEQUENT ``/plan`` reads the AS-BUILT surface
rather than the pristine DEM.

This proves the loop END-TO-END on the REAL Haworth LOLA tile (no synthetic terrain):

    place a cut pad -> POST /executive/run (fold the conserved as-built delta into TerrainMemory)
      -> the twin reflects the cut (/twin/terrain)
      -> the surface the planner reads (state.as_built_dem, the exact call at routers/plan.py:306) now
         reflects the cut, ONLY at the worked cells, mass-conserved (the volume-conserving imprint equals
         the conserved authority's recorded net_volume)
      -> /world/terrain_view now declares AS_BUILT cells + an advanced version
      -> a next /plan runs on the modified surface.

Clauses 1+2 of SD-01 (per-structure constructability evidence + material/DEM-resolution/uncertainty) are
proven separately in ``test_sd01_constructability.py`` (commit 67e3083). Together the three clauses cover
the full SD-01 acceptance.
"""
from __future__ import annotations

import importlib

import numpy as np
import pytest
from fastapi.testclient import TestClient

H = {"X-API-Key": "test-key"}

# a Surface-Design cut pad order: dig a 2x2 m pad 0.3 m deep in the site's build frame. A cut removes
# material to the drum, so it LOWERS the terrain -- a clean, deterministic before/after signal.
_CUT_PAD = [{"kind": "cut", "x": 10.0, "y": 10.0, "action": "dig pad", "footprint_m2": 4.0, "depth_m": 0.3}]


@pytest.fixture()
def client(monkeypatch, tmp_path):
    """A fresh app over a fresh per-test data dir (its own empty TerrainMemory), the same fixture shape
    as test_sim_run_transactions -- DEV_OPEN + an API key, twin/WSS reset so the run starts from genesis."""
    monkeypatch.setenv("STEWIE_API_KEY", "test-key")
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("STEWIE_DEV_OPEN", "1")
    from stewie.server import state as S
    monkeypatch.setattr(S, "_TWIN", None)
    monkeypatch.setattr(S, "_WSS", None)
    import stewie.server.server as srv
    importlib.reload(srv)
    yield TestClient(srv.app)
    monkeypatch.undo()
    importlib.reload(srv)


def test_sd01_before_after_terrain_transaction_influences_next_plan(client):
    """[REQ:SD-01] The full third clause: a structure's cut folds into the twin and a subsequent plan
    reads the modified terrain, mass-conservingly, on the real Haworth DEM."""
    from stewie.server import state as S

    dem, origin = S.moon_dem("haworth")
    z0, cell = dem
    z0 = np.asarray(z0, dtype=float)

    # BEFORE any build: the surface the /plan route reads (routers/plan.py:306 -> state.as_built_dem) is
    # the pristine DEM, and the composed planning view declares NO as-built cells.
    z_before, _ = S.as_built_dem("haworth", (z0.copy(), cell), origin)
    assert np.array_equal(z_before, z0), "no build yet -> the plan surface must be the pristine DEM"
    tv0 = client.get("/world/terrain_view?site=haworth", headers=H).json()
    assert tv0["provenance"]["as_built_version"] == 0
    assert tv0["provenance"]["cells"]["as_built"] == 0

    # EXECUTE the cut pad as a SIM run: the execute->remember loop folds the conserved as-built cut/fill
    # into the site's TerrainMemory (the fold only happens on a non-safed run).
    r = client.post("/executive/run", headers=H, json={"orders": _CUT_PAD, "site": "haworth"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True and body["label"] == "sim" and body["safed"] is False

    # the TWIN reflects the structure's cut/fill -- a before/after terrain transaction was recorded.
    tm = client.get("/twin/terrain/haworth", headers=H).json()
    assert tm["recorded"] is True and tm["version"] >= 1 and tm["chain_valid"] is True
    assert tm["max_cut_m"] > 0.0, "a cut pad must lower the terrain (max_cut_m > 0)"
    assert tm["net_volume_m3"] < 0.0, "a cut removes material to the drum -> net terrain volume drops"

    # a SUBSEQUENT plan reads the MODIFIED terrain: the SAME state.as_built_dem the /plan route uses now
    # reflects the cut -- ONLY at the worked cells (isclose == compose_terrain_view's AS_BUILT test), and
    # there strictly LOWER (a cut), byte-identical pristine everywhere else.
    z_after, cell_after = S.as_built_dem("haworth", (z0.copy(), cell), origin)
    assert cell_after == cell
    changed = ~np.isclose(z_after, z0)
    assert changed.any(), "the as-built cut must change the surface the next plan reads"
    assert np.all((z_after - z0)[changed] < 0.0), "a cut pad only LOWERS the surface it reads"
    assert np.array_equal(z_after[~changed], z0[~changed]), "unworked cells stay pristine"

    # MASS-CONSERVING (not an ad-hoc height edit): the imprinted net volume equals the conserved
    # authority's recorded net_volume_m3 -- the volume-conserving coarse-DEM downsample
    # (TerrainMemory.imprint_on_dem_resampled) preserves the mass the conserved ColumnState actually moved.
    imprint_net_m3 = float((z_after - z0).sum()) * cell * cell
    assert np.isclose(imprint_net_m3, tm["net_volume_m3"], rtol=1e-4, atol=1e-3), (
        f"imprint net {imprint_net_m3} != conserved authority net {tm['net_volume_m3']}")

    # the composed planning surface now declares AS_BUILT cells + an advanced version (the exact cells the
    # as-built diff touched -- the provenance the cockpit/planner read).
    tv1 = client.get("/world/terrain_view?site=haworth", headers=H).json()
    assert tv1["provenance"]["as_built_version"] >= 1
    assert tv1["provenance"]["cells"]["as_built"] == int(changed.sum()) >= 1

    # and the NEXT /plan at the site runs on the modified surface (the plan path reads as_built; 200/ok).
    nxt = client.post("/plan", headers=H, json={"name": "next-plan", "body": "moon",
                                                "site": "haworth", "orders": _CUT_PAD})
    assert nxt.status_code == 200 and nxt.json()["ok"] is True


def test_sd01_terrain_transaction_is_reversible(client):
    """[REQ:SD-01] The folded terrain transaction is REVERSIBLE (DT-03 compensating()): _remember_sim_terrain
    wraps its world-log commit in ``compensating(lambda: TM.restore_site(..., prior))``, so a failed commit
    restores the prior TerrainMemory byte-for-byte. Prove the snapshot/restore the loop relies on round-trips
    the folded state (version + cumulative delta + chain integrity) after a further mutation."""
    from stewie.specs.config import data_dir
    from stewie.twin import terrain_memory as TM

    r = client.post("/executive/run", headers=H, json={"orders": _CUT_PAD, "site": "haworth"})
    assert r.status_code == 200, r.text

    snap = TM.snapshot_site(data_dir(), "haworth")
    assert snap is not None, "the fold must have persisted a TerrainMemory to snapshot"
    folded = TM.load_site(data_dir(), "haworth")
    v0, d0 = folded.version, folded.cumulative_delta()

    # a further mutation (as a subsequent fold would apply), then a compensating restore to the snapshot.
    folded.apply(np.zeros((folded.rows, folded.cols)), mission="reverse-probe")
    TM.save_site(data_dir(), folded)
    assert TM.load_site(data_dir(), "haworth").version == v0 + 1
    TM.restore_site(data_dir(), "haworth", snap)

    restored = TM.load_site(data_dir(), "haworth")
    assert restored.version == v0, "restore must revert the version to the pre-mutation fold"
    assert np.array_equal(restored.cumulative_delta(), d0), "restore must revert the terrain delta exactly"
    assert restored.verify_chain(), "the restored memory's hash chain must still verify"
