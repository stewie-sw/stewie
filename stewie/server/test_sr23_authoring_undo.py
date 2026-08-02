"""SR-23: every authoring mutation must snapshot, and undo must re-render what it restores.

Three cockpit mutation sites changed ORDERS / KEEPOUTS / ANNOTATIONS without calling
`snapshotAuthoring()`: `deleteSelectedPin`, the keep-out list's per-row delete, and the `koadd` form.
Because `renderQueue` -> `persistDraft` -> `PUT /draft`, the damage was written to the durable
per-owner server draft.

The reproduction from the 2026-07-28 review: place order A (snapshot S1), place order B (snapshot S2),
add keep-out K through the form (NO snapshot), press Ctrl+Z -> `undoAuthoring` pops S2 -> **order B is
destroyed** with only "undone" in the status line. Separately `undoAuthoring` restored all three
collections but called `renderQueue()` only, so `#kolist` kept listing deleted keep-outs with stale ✕
indices and a subsequent ✕ removed the wrong entry.

ON THE FORM OF THIS TEST. `cockpit.js` is a browser module with no DOM-free entry point, so this
checks source STRUCTURE -- but per FUNCTION BODY, not file-wide. The existing UI-14 test
(`test_ui14_queue_table.py:41`) is a literal whole-file grep, which passes no matter how broken an
individual body is; that is precisely why this defect survived. Extracting the specific body and
asserting the call appears inside IT is the strongest check available without a DOM, and it fails if
a snapshot is removed from any one site.

Run: <venv>/bin/python -m pytest stewie/server/test_sr23_authoring_undo.py -q
"""
from __future__ import annotations

import os
import re

import pytest

_COCKPIT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web", "assets", "cockpit.js")


def _src() -> str:
    with open(_COCKPIT, encoding="utf-8") as fh:
        return fh.read()


def _function_body(src: str, name: str) -> str:
    """The brace-balanced body of `function <name>(...) { ... }`."""
    m = re.search(rf"function\s+{re.escape(name)}\s*\([^)]*\)\s*\{{", src)
    assert m, f"function {name} not found in cockpit.js"
    i = m.end() - 1
    depth = 0
    for j in range(i, len(src)):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                return src[i:j + 1]
    pytest.fail(f"unbalanced braces extracting {name}")


def test_delete_selected_pin_snapshots_before_mutating():
    """It splices ORDERS/KEEPOUTS/ANNOTATIONS -- without a snapshot the next undo eats other work."""
    body = _function_body(_src(), "deleteSelectedPin")
    assert "snapshotAuthoring()" in body, (
        "deleteSelectedPin mutates the authoring collections with no undo snapshot")
    assert "ORDERS.splice" in body, "body extraction is wrong -- this guard would be vacuous"


def test_undo_rerenders_every_surface_it_restores():
    """undoAuthoring restores ORDERS + KEEPOUTS + ANNOTATIONS; rendering only the queue leaves
    #kolist showing deleted keep-outs with stale ✕ indices."""
    body = _function_body(_src(), "undoAuthoring")
    for coll, render in (("KEEPOUTS", "renderKeepouts"), ("ORDERS", "renderQueue")):
        assert coll in body, f"undoAuthoring no longer restores {coll} -- re-check this test"
        assert render in body, f"undoAuthoring restores {coll} but never calls {render}"


def test_the_keepout_row_delete_snapshots():
    """The per-row ✕ in #kolist."""
    src = _src()
    m = re.search(r'mkbtn\("✕",\s*\(\)\s*=>\s*\{([^}]*KEEPOUTS\.splice[^}]*)\}', src)
    assert m, "the keep-out row delete handler was not found -- re-check this test"
    assert "snapshotAuthoring()" in m.group(1), "the keep-out row ✕ mutates KEEPOUTS with no snapshot"


def test_the_koadd_form_snapshots():
    """The add-keep-out form: the exact site in the review's reproduction."""
    src = _src()
    i = src.index('qel("koadd").onclick')
    window = src[i:i + 700]
    assert "KEEPOUTS.push" in window, "koadd handler shape changed -- re-check this test"
    push_at = window.index("KEEPOUTS.push")
    assert "snapshotAuthoring()" in window[:push_at], (
        "the koadd form pushes a keep-out with no undo snapshot taken first")


def test_every_authoring_collection_mutation_is_snapshotted():
    """Sweep: no un-snapshotted splice/push of an authoring collection anywhere in the file.

    Scoped to the same line or the statement immediately before it, which is how every correct site in
    this file is written. Deliberately excludes `undoAuthoring` itself, which legitimately rewrites the
    collections while RESTORING them.
    """
    src = _src()
    undo = _function_body(src, "undoAuthoring")
    offenders = []
    lines = src.splitlines()
    for n, line in enumerate(lines):
        if not re.search(r"\b(ORDERS|KEEPOUTS|ANNOTATIONS)\.(splice|push)\(", line):
            continue
        # A wholesale REPLACE -- `X.length = 0; ...forEach(push)` -- is a state LOAD (open a draft,
        # load a mission, import a plan), not a user edit, and correctly takes no undo snapshot.
        # Only INCREMENTAL edits are in scope here.
        if ".length = 0" in line or "forEach(" in line:
            continue
        if line.strip() in undo:
            continue
        # Window covers the enclosing guard clause: `deleteSelectedPin` snapshots at the top of the
        # function, several statements above its ANNOTATIONS splice.
        context = "\n".join(lines[max(0, n - 12):n + 1])
        if "snapshotAuthoring()" not in context:
            offenders.append(f"{n + 1}: {line.strip()[:90]}")
    assert not offenders, "authoring mutations without an undo snapshot:\n  " + "\n  ".join(offenders)
