"""[REQ:MT-01] the large-file / tracked-artifact policy gate: the current tree passes (every oversized
tracked binary is allowlisted with a disposition), a NEW oversized non-allowlisted binary is flagged
(fails CI), and CI actually runs the gate. Growth of the tracked payload is reported (MT-05 consumes it).
The DEM externalization the row also calls for (manifest+fetch) is the remaining follow-on."""
import os

from scripts import check_tracked_artifacts as GATE


def test_current_tree_passes_the_policy_no_unlisted_large_binaries():
    r = GATE.scan()
    assert r["violations"] == [], (
        "unlisted large tracked binaries: " + ", ".join(f"{p} ({n // 1048576}MB)" for p, n in r["violations"]))
    # the baseline is fully accounted: every oversized file matches exactly one allowlist entry.
    assert r["oversized"], "expected the known large fixtures (DEM bundles) to be present"
    for path, _ in r["oversized"]:
        assert GATE.is_allowlisted(path), f"{path} is oversized but not allowlisted"


def test_a_new_oversized_binary_would_be_flagged(monkeypatch):
    # empty the allowlist -> the REAL oversized DEM bundles now surface as violations, proving the gate
    # flags any oversized tracked binary that is not explicitly allowlisted (no synthetic file created).
    monkeypatch.setattr(GATE, "ALLOWLIST", ())
    r = GATE.scan()
    assert r["violations"], "the gate must flag oversized tracked binaries when they are not allowlisted"
    assert len(r["violations"]) == len(r["oversized"])


def test_is_allowlisted_matches_the_known_fixtures_not_arbitrary_paths():
    assert GATE.is_allowlisted("samples/lunar_dem/haworth_10km_5m/heightmap.rf32")
    assert GATE.is_allowlisted("stewie/godot/assets/rassor_nasa/rassor.glb")
    assert not GATE.is_allowlisted("data/some_new_model.bin")   # a new large binary is NOT pre-allowed
    assert not GATE.is_allowlisted("stewie/server/huge_blob.npz")


def test_total_payload_is_reported():
    r = GATE.scan()
    assert r["total_bytes"] > 0
    assert r["total_bytes"] < 1024 * 1024 * 1024   # sanity: tracked payload is well under 1 GB


def test_ci_runs_the_large_file_gate():
    ci = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      ".github", "workflows", "ci.yml")
    with open(ci, encoding="utf-8") as fh:
        text = fh.read()
    assert "check_tracked_artifacts.py" in text, "CI must run the MT-01 large-file policy gate"
