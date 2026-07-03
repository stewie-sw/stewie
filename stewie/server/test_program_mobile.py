"""[REQ:FS-26] the public /program board must fit the mobile viewport (no horizontal body scroll at
390 px). The runtime proof is the Playwright assertion in scripts/ui_smoke.mjs (a CI-gated browser
check: at 390 px `document.scrollingElement.scrollWidth <= innerWidth`). This python gate cites the row
and pins BOTH halves of that guarantee so neither can silently regress: (a) the smoke actually makes
the 390 px overflow assertion, and (b) program.html carries the CSS that enforces it -- grid children
zero their min-width and wide single-line content (the ConOps spine, provenance) wraps or self-scrolls
rather than pushing the page body. The cockpit half of FS-26 is now enforced by the FR-20 mobile
command-surface harness (test_fr20_mobile_smoke.py: no body overflow + controls fit at 320/360/390/430/768),
asserted below so neither half can silently regress."""
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SMOKE = _HERE.parents[1] / "scripts" / "ui_smoke.mjs"
_PROGRAM = _HERE / "web" / "program.html"


def test_ui_smoke_asserts_program_fits_the_mobile_viewport():
    smoke = _SMOKE.read_text(encoding="utf-8")
    assert "FS-26" in smoke, "the ui-smoke tier must carry the [FS-26] mobile-overflow check"
    assert "setViewportSize" in smoke and "390" in smoke, "the check must run at the 390 px phone width"
    assert "scrollWidth" in smoke and "innerWidth" in smoke, (
        "the check must assert scrollWidth <= innerWidth (no horizontal body overflow)")


def test_program_html_carries_the_no_horizontal_overflow_guard():
    css = _PROGRAM.read_text(encoding="utf-8")
    # the min-width:auto -> min-content overflow is the root cause; the guard zeroes it and makes the
    # wide single-line surfaces wrap / self-scroll instead of expanding the page body.
    assert "min-width: 0" in css, "grid/flex children must zero their min-width so they can shrink"
    assert "overflow-wrap: anywhere" in css, "long provenance/summary strings must wrap"
    assert "#program-spine" in css and "overflow-x: auto" in css, (
        "the ConOps spine must self-scroll, not push the body")


def test_cockpit_half_is_enforced_by_the_fr20_mobile_harness():  # [REQ:FS-26]
    # the cockpit half of FS-26 (key controls must not overflow/clip on phones) is now closed: the FR-20
    # mobile command-surface harness asserts no body overflow + control fit across the phone/tablet widths.
    harness = (_HERE / "test_fr20_mobile_smoke.py").read_text(encoding="utf-8")
    for w in ("320", "768"):
        assert w in harness, f"the FR-20 cockpit harness must cover the {w} px viewport"
    assert "scrollWidth" in harness and "overflow" in harness, \
        "the FR-20 harness must assert the cockpit has no body horizontal overflow"
