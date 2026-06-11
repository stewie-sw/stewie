"""#79 slice: the berm-building autonomy state machine (gated cut-haul-fill cycle)."""
from lode.berm_fsm import BermObs, run, step


def test_one_cycle_builds_to_target():
    """#79: LOAD -> HAUL -> DUMP -> GRADE -> DONE when one drum load meets the berm target."""
    obs = [BermObs(drum_kg=5, at_site=False, placed_kg=0, target_kg=25, stable=True),    # cutting
           BermObs(drum_kg=28, at_site=False, placed_kg=0, target_kg=25, stable=True),   # full -> HAUL
           BermObs(drum_kg=28, at_site=True, placed_kg=0, target_kg=25, stable=True),    # at site -> DUMP
           BermObs(drum_kg=0, at_site=True, placed_kg=28, target_kg=25, stable=True),    # target met -> GRADE
           BermObs(drum_kg=0, at_site=True, placed_kg=28, target_kg=25, stable=True)]    # GRADE -> DONE
    out = run(obs)
    assert out["built"] and out["final"] == "DONE"
    assert [t["to"] for t in out["trace"]] == ["HAUL", "DUMP", "GRADE", "DONE"]


def test_under_target_loops_back_to_load():
    """a partial dump (berm still under target) routes DUMP -> LOAD to cut more."""
    s, reason = step("DUMP", BermObs(drum_kg=0, at_site=True, placed_kg=10, target_kg=25, stable=True))
    assert s == "LOAD" and "under target" in reason


def test_instability_aborts_before_dump():
    """[#59 gate] a tip-over risk aborts -- never dump while unstable."""
    s, reason = step("HAUL", BermObs(drum_kg=28, at_site=True, placed_kg=0, target_kg=25, stable=False))
    assert s == "ABORT" and "unstable" in reason


def test_low_drum_keeps_loading():
    s, _ = step("LOAD", BermObs(drum_kg=5, at_site=False, placed_kg=0, target_kg=25, stable=True))
    assert s == "LOAD"
