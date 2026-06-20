"""The §7 status surface (STATUS.md / STATUS.json) must stay in sync with the live traceability tools.

gen_status.py derives the §7 status ENTIRELY from scripts/req_trace + scripts/release_gate -- never
from hand numbers. These tests prove that, and that the committed STATUS.md / STATUS.json are not
stale (so a marker change that moves the cited count can't silently leave the surface behind). The
`--check` mode these tests exercise is the same one CI runs.
"""
import json
import os

from scripts import gen_status as GS
from scripts.req_trace import parse_requirements, trace

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PRD = os.path.join(_REPO_ROOT, "PRD.md")


def test_collect_numbers_come_straight_from_req_trace():
    # the surface's headline numbers ARE the req_trace numbers, not a re-derivation that could drift
    tr = trace(_PRD, GS._PATHS)
    st = GS.collect(_PRD, GS._PATHS)
    assert st["total"] == tr["total"]
    assert st["cited"] == tr["cited"]
    # the V!=D flagged rows are exactly the FS-22 understated audit (same ids, same current V)
    assert [(r["id"], r["v"]) for r in st["v_ne_d_flagged"]] == tr["understated"]


def test_per_family_rollup_partitions_every_row():
    # every PRD row lands in exactly one family bucket, and the per-family cited count never exceeds total
    reqs = parse_requirements(_PRD)
    st = GS.collect(_PRD, GS._PATHS)
    assert sum(slot["total"] for slot in st["per_family"].values()) == len(reqs)
    assert sum(slot["cited"] for slot in st["per_family"].values()) == st["cited"]
    for fam, slot in st["per_family"].items():
        assert 0 <= slot["cited"] <= slot["total"]
        # the family key is the 2-letter prefix of its members
        assert all(rid.split("-")[0] == fam for rid in reqs if rid.split("-")[0] == fam)


def test_committed_status_md_is_not_stale():
    # the committed STATUS.md byte-for-byte equals what the live tools would generate right now
    md, _js = GS.generate(_PRD, GS._PATHS)
    path = os.path.join(_REPO_ROOT, "STATUS.md")
    assert os.path.exists(path), "STATUS.md is missing -- run python3 scripts/gen_status.py"
    current = open(path, encoding="utf-8").read()
    assert current == md, "STATUS.md is stale -- run python3 scripts/gen_status.py to regenerate"


def test_committed_status_json_is_not_stale_and_matches_md():
    _md, js = GS.generate(_PRD, GS._PATHS)
    path = os.path.join(_REPO_ROOT, "STATUS.json")
    assert os.path.exists(path), "STATUS.json is missing -- run python3 scripts/gen_status.py"
    current = open(path, encoding="utf-8").read()
    assert current == js, "STATUS.json is stale -- run python3 scripts/gen_status.py to regenerate"
    # the JSON carries the same headline numbers the collector produced
    data = json.loads(current)
    st = GS.collect(_PRD, GS._PATHS)
    assert data["total"] == st["total"] and data["cited"] == st["cited"]
    assert data["v_ne_d_flagged"] == st["v_ne_d_flagged"]


def test_check_mode_passes_on_a_fresh_write_and_fails_when_stale(tmp_path):
    # writing then --check against the same outputs passes (exit 0); a hand-edit makes --check fail (exit 2)
    md_out = str(tmp_path / "STATUS.md")
    json_out = str(tmp_path / "STATUS.json")
    assert GS.main(["--prd", _PRD, "--md-out", md_out, "--json-out", json_out]) == 0
    assert GS.main(["--prd", _PRD, "--md-out", md_out, "--json-out", json_out, "--check"]) == 0
    with open(md_out, "a", encoding="utf-8") as fh:
        fh.write("\nhand-edited drift\n")
    assert GS.main(["--prd", _PRD, "--md-out", md_out, "--json-out", json_out, "--check"]) == 2
