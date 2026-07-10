"""[dispatch-audit R7b] Cockpit run-binding static gate.

The cockpit tracks the signed revision from /executive/release-plan (RELEASED_REV), but its two
/executive/run POSTs sent only the mutable order queue -- so a released plan was re-run from the browser's
orders, not bound to the immutable signed revision (the R2/F1 defect at the frontend). This gate makes the
production cockpit prove that BOTH run POSTs attach ``revision_hash`` from the released revision's
content_hash when one is released, so the backend executes the SIGNED plan.

Static source gate (mirrors test_cockpit_state_routing.py [REQ:FS-16]): the cockpit JS is pure and node-
tested, but this asserts the wiring exists in the shipped bundle.
"""
from __future__ import annotations

import re
from pathlib import Path

_COCKPIT = Path(__file__).parent / "web" / "assets" / "cockpit.js"


def _read() -> str:
    return _COCKPIT.read_text(encoding="utf-8")


def test_run_posts_bind_the_released_revision():  # [dispatch-audit R7b]
    src = _read()
    # the revision hash is sourced from the released revision (not fabricated), and used as revision_hash.
    assert "RELEASED_REV.content_hash" in src, "the run POST does not source the hash from the released revision"
    assert "revision_hash" in src, "no revision_hash binding in the cockpit"

    # EACH /executive/run POST must bind revision_hash near its call site (within the body it builds), so a
    # released plan runs the SIGNED revision (R2/F1); a bare orders POST would re-run mutable browser state.
    run_posts = [m.start() for m in re.finditer(r'fetch\("/executive/run"', src)]
    assert len(run_posts) >= 2, f"expected both cockpit run POSTs, found {len(run_posts)}"
    for pos in run_posts:
        window = src[max(0, pos - 600):pos + 200]
        assert "revision_hash" in window, f"a /executive/run POST at {pos} does not bind revision_hash"
