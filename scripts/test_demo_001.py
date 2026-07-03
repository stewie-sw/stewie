"""[REQ:DE-01] Demo 001 vertical slice: proves the platform loop runs end-to-end from existing code, is
deterministic, and the evidence artifact carries every stage's typed payload. Real conserved authority + real
body constants -- no synthetic values."""
import demo_001  # scripts/ sibling (pytest prepend mode)


def test_de01_slice_runs_end_to_end_with_every_stage_payload():  # [REQ:DE-01]
    a = demo_001.run_demo_001()
    # body/profile -> conserved backend
    assert a["body"] == "moon"
    assert a["backend"]["authority_class"] == "conserved" and a["backend"]["conserves_mass"] is True
    # plan
    assert a["plan"]["plan_id"] and "totals" in a["plan"]
    # conserved execution + world/terrain-memory transaction
    assert a["world_transaction"]["n"] >= 2 and a["world_transaction"]["authority_sha"]
    assert "SIM" not in a["world_transaction"]["latest_provenance"]   # this is a real released-plan txn
    # RegolithVolumeEstimate reconcile: a real dig moved real conserved mass
    assert a["reconcile"]["mass_moved_kg"] > 0.0
    assert a["reconcile"]["volume"] and a["reconcile"]["acceptance"]
    assert a["content_sha"]


def test_de01_is_deterministic():  # [REQ:DE-01]
    assert demo_001.run_demo_001()["content_sha"] == demo_001.run_demo_001()["content_sha"]
