"""S-05 / A-05 regression: the operator account store must FAIL CLOSED on corruption.

The audit found `operators._load()` returned an empty store on any JSON/IO/schema error, which then
let `auth.is_allowed` fall back to the hardcoded/env allowlist -- so a corrupt or partially-restored
file silently REACTIVATED fallback director access, and the next write could overwrite the damaged
file with an incomplete account set.

Fix verified here:
 - first-run ABSENCE (no file) is still the empty store (back-compat: a clean deploy works),
 - but a CORRUPT/unreadable/schema-invalid file RAISES (fail closed), QUARANTINES the bad file
   (so a later write cannot clobber it), and is observable,
 - and a bootstrap-completed MARKER, once written, makes a subsequently-missing store ALSO fail
   closed (fallback identities cannot reappear after enrollment).

Run: PYTHONPATH=. <venv>/bin/python -m pytest stewie/server/test_account_store_failclosed.py -q
"""
from __future__ import annotations

import importlib
import os

import pytest


@pytest.fixture()
def ops(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    from stewie.server import operators as OPS
    importlib.reload(OPS)
    return OPS


def test_absent_store_is_first_run_empty(ops):
    """No file at all = a clean deploy. The store is empty and the caller may use the env allowlist."""
    assert ops.list_all() == []
    assert ops.exists("anyone@example.com") is False


def test_corrupt_json_fails_closed_and_quarantines(ops):
    """A truncated/garbage JSON document must RAISE (not collapse to empty) and the bad file must be
    moved aside so a later write cannot overwrite an incomplete account set."""
    p = ops._path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f:
        f.write('{"version": 1, "operators": {"a@b.co": {"role": "director"')   # truncated -> invalid
    with pytest.raises(ops.AccountStoreError):
        ops.exists("a@b.co")
    # the corrupt file is quarantined (renamed), not silently deleted, and the original path no longer
    # holds the broken document
    quarantined = [n for n in os.listdir(os.path.dirname(p)) if n.startswith("operators.json.corrupt")]
    assert quarantined, "corrupt store was not quarantined"


def test_schema_invalid_store_fails_closed(ops):
    """A structurally-valid JSON that is the WRONG shape (no 'operators' mapping) must also fail
    closed rather than be treated as an empty store."""
    p = ops._path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f:
        f.write('["not", "an", "object"]')
    with pytest.raises(ops.AccountStoreError):
        ops.list_all()


def test_bootstrap_marker_makes_a_missing_store_fail_closed(ops):
    """Once an account exists (bootstrap completed), a SUBSEQUENTLY missing store must NOT silently
    revert to first-run empty (which would re-enable fallback directors). It fails closed."""
    ops.register("a@b.co", "long-enough-password")        # writes the store + sets the marker
    p = ops._path()
    os.remove(p)                                          # simulate accidental deletion / partial restore
    with pytest.raises(ops.AccountStoreError):
        ops.list_all()


def test_corrupt_store_denies_fallback_director_at_the_auth_boundary(ops, monkeypatch):  # [REQ:FS-11]
    """The end-to-end S-05 guarantee: with a CORRUPT store, auth.is_allowed for a default-allowlist
    director must NOT fall back to True -- it must propagate the fail-closed error (so a corrupt disk
    cannot reactivate a fallback director). Before the fix, _load() collapsed to empty and is_allowed
    returned the allowlist membership (True)."""
    from stewie.server import auth as AUTH
    importlib.reload(AUTH)
    p = ops._path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f:
        f.write("{ this is not json")
    with pytest.raises(ops.AccountStoreError):
        AUTH.is_allowed("mccardle.john@gmail.com")        # a default-allowlist director
