"""FS-23: the architecture-review traceability ledger.

The ledger is GENERATED from the live tree (never hand-maintained): per PRD §7 row it emits the row's
route / module / adapter / test / log links + the list of MISSING link kinds, and flags a row that has no
route/test evidence as incomplete -- so it exposes gaps without ever implying a half-wired row is done.
"""
from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
import arch_ledger as A  # noqa: E402
import req_trace  # noqa: E402

_REPO = os.path.dirname(_HERE)
_PRD = os.path.join(_REPO, "PRD.md")


def test_ledger_covers_every_section7_row_with_the_five_link_kinds():  # [REQ:FS-23]
    ledger = A.build_ledger(_PRD)
    rows = req_trace.parse_requirements(_PRD)
    assert set(ledger) == set(rows), "the ledger does not cover exactly the §7 rows"
    for rid, d in ledger.items():
        assert set(d["links"]) == set(A._LINK_KINDS), f"{rid}: link kinds are not route/module/adapter/test/log"
        assert set(d["counts"]) == set(A._LINK_KINDS)
        assert d["missing"] == [k for k in A._LINK_KINDS if not d["links"][k]], f"{rid}: missing list is wrong"
        assert isinstance(d["incomplete"], bool)


def test_ledger_is_generated_from_the_live_tree_not_hand_maintained():  # [REQ:FS-23]
    ledger = A.build_ledger(_PRD)
    # FS-24's test link must point at the very file that cites it -- proof the ledger read the live tree.
    fs24_tests = ledger["FS-24"]["links"]["test"]
    assert any("test_cockpit_modularization.py" in t for t in fs24_tests), \
        "FS-24 test link is not the real citing file -> the ledger is not generated from the tree"
    # FS-10's module link points at the real implementing module (services.py), route at the router.
    assert any("services.py" in m for m in ledger["FS-10"]["links"]["module"])
    assert any("routers/health.py" in r for r in ledger["FS-10"]["links"]["route"])
    # every emitted link is a real file:line in this checkout (nothing invented).
    for kind in ("route", "module", "adapter", "test"):
        for link in ledger["FS-10"]["links"][kind]:
            path = link.rsplit(":", 1)[0]
            assert os.path.isfile(os.path.join(_REPO, path)), f"ledger cites a non-existent file {path}"


def test_ledger_flags_a_row_with_no_route_or_test_as_incomplete():  # [REQ:FS-23]
    ledger = A.build_ledger(_PRD)
    # the incomplete flag is exactly: unverified (no test) OR unwired (no route/module/adapter).
    for rid, d in ledger.items():
        c = d["counts"]
        has_test = c["test"] > 0
        has_impl = (c["route"] + c["module"] + c["adapter"]) > 0
        assert d["incomplete"] == (not (has_test and has_impl)), f"{rid}: incomplete flag inconsistent"
    # the ledger actually surfaces gaps (it is not vacuously all-green), and every flagged row is a real gap.
    incomplete = [r for r, d in ledger.items() if d["incomplete"]]
    assert incomplete, "the ledger flags nothing incomplete -- it would imply everything is done"
    for rid in incomplete:
        c = ledger[rid]["counts"]
        assert c["test"] == 0 or (c["route"] + c["module"] + c["adapter"]) == 0, \
            f"{rid} flagged incomplete but has both a test and an implementation link"


def test_a_fully_wired_and_verified_row_is_traced_not_incomplete():  # [REQ:FS-23]
    ledger = A.build_ledger(_PRD)
    # FS-10 ships an implementing module + route + a citing test -> traced, missing only the FE adapter
    # (a backend budget row has no front-end view, which the missing-link list states honestly).
    fs10 = ledger["FS-10"]
    assert fs10["incomplete"] is False
    assert "adapter" in fs10["missing"], "FS-10 should honestly report no FE adapter link"
    # summarize agrees with the per-row flags.
    s = A.summarize(ledger)
    assert s["rows"] == len(ledger)
    assert s["traced"] + s["incomplete"] == s["rows"]
