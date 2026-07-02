"""[REQ:FS-30] the cockpit must not stack two rows of the same ConOps phase labels. The top tab bar
(Plan/Rehearse/Validate/Release/Execute/Report) and the mission-pipeline #stepper used to BOTH render
Rehearse/Validate/Release/Execute/Report -- two rows of the same words, a real duplication a user
flagged (Screenshot_20260702_131756). The fix: #stepper is the PLAN micro-wizard (Site->Fleet->Orders->
Solve, the sub-steps that exist nowhere else) plus a single "-> Rehearse" hand-off cue; the downstream
phases' done/current progress rides as a dot ON each phase tab (renderStepper's PHASE_TAB loop). This
gate pins BOTH halves so the duplication cannot silently return."""
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_INDEX = _HERE / "index.html"
_COCKPIT = _HERE / "web" / "assets" / "cockpit.js"

# the downstream ConOps phases -- each must live on the tab bar, NEVER also as its own #stepper chip.
_DOWNSTREAM_PHASE_STEPS = ("validate", "release", "execute", "review")


def test_stepper_does_not_duplicate_the_downstream_phase_tabs():
    html = _INDEX.read_text(encoding="utf-8")
    start = html.index('id="stepscroll"')
    # bound on the #guidebtn that immediately follows the stepscroll span (an inner <span class="dot">
    # per chip makes a naive </span> search truncate the block).
    end = html.index('id="guidebtn"', start)
    stepscroll = html[start:end]
    for step in _DOWNSTREAM_PHASE_STEPS:
        assert f'data-step="{step}"' not in stepscroll, (
            f"#stepper still renders a '{step}' chip -- that phase already lives on the tab bar; the "
            "stacked duplicate row is back")
    # the Plan micro-wizard sub-steps (which exist nowhere else) MUST stay in the stepper.
    for sub in ("site", "fleet", "orders", "solve"):
        assert f'data-step="{sub}"' in stepscroll, f"the Plan sub-step '{sub}' must stay in #stepper"
    # a single hand-off cue to the Rehearse tab replaces the removed downstream chips.
    assert "handoff" in stepscroll and "Rehearse" in stepscroll


def test_phase_progress_rides_on_the_tabs():
    js = _COCKPIT.read_text(encoding="utf-8")
    # the de-dup moved phase done/current state onto the tabs via a PHASE_TAB map + a .pdot per phase tab.
    assert "PHASE_TAB" in js, "renderStepper must map phase progress onto the tabs (PHASE_TAB)"
    assert "pdot" in js and "pcurrent" in js and "pdone" in js, (
        "each phase tab must carry a progress dot (pdone/pcurrent) so nothing is lost when the "
        "duplicated stepper chips are removed")
