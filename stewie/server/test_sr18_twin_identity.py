"""SR-18 [REQ:DT-01]: a world transaction must record the identity of the twin it actually mutated.

`state.world_state_service()` builds the service from the zero-arg `state.twin` accessor, so
`_twin_obj()` always resolved the DEFAULT (haworth) twin. But `/twin/resync` mutates
`state.twin(req.site)`. A resync at any other site therefore advanced that site's twin while the
committed DT-01 transaction recorded the DEFAULT twin's version and hash.

Reproduced by the 2026-07-28 review: two resyncs at `site='shackleton_rim'` advanced that twin
0 -> 1 -> 2, while both transactions recorded `twin_version=0, twin_hash=genesis`, and
`same twin_hash across two materially different world states` was True. `/world/transaction` and the
PG-01 projection sink then ASSERT the observed twin was unchanged while it was mutated twice --
falsifying `envelope._world_sha`'s documented claim to be "a function of EVERY source so mutating any
one moves the sha".

Run: <venv>/bin/python -m pytest stewie/server/test_sr18_twin_identity.py -q
"""
from __future__ import annotations

import importlib

import numpy as np
import pytest


@pytest.fixture()
def st(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    from stewie.server import state as ST
    importlib.reload(ST)
    yield ST
    ST._TWIN = None
    ST._TWINS.clear()


def _advance(twin, seed):
    twin.apply_patch(np.full((3, 3), float(seed)), origin_rc=(0, 0), provenance=f"resync-{seed}")


def test_commit_records_the_mutated_twins_identity_not_the_default(st):
    """The core: a non-default twin's version/hash must reach the transaction."""
    from stewie.server.world_state import WorldStateService

    default_twin = st.twin()                       # untouched throughout
    other = st.twin("shackleton_rim")
    svc = WorldStateService(twin=st.twin, journal_path=None)

    _advance(other, 1)
    txn1 = svc.record_resync(provenance="r1", site="shackleton_rim", twin=other)
    _advance(other, 2)
    txn2 = svc.record_resync(provenance="r2", site="shackleton_rim", twin=other)

    assert txn1.twin_version == 1 and txn2.twin_version == 2, (
        f"recorded versions {txn1.twin_version}/{txn2.twin_version}; the mutated twin went 1 -> 2")
    assert txn1.twin_hash != txn2.twin_hash, (
        "the same twin_hash spans two materially different world states")
    assert txn2.twin_hash != "genesis"
    assert default_twin.version == 0, "the default twin was never touched, yet it was the one recorded"


def test_without_the_explicit_twin_the_default_binding_is_still_used(st):
    """Non-vacuity: this is exactly the pre-fix behaviour, and it is what the route used to do."""
    from stewie.server.world_state import WorldStateService

    other = st.twin("shackleton_rim")
    svc = WorldStateService(twin=st.twin, journal_path=None)
    _advance(other, 1)
    txn = svc.record_resync(provenance="r1", site="shackleton_rim")     # no twin= -> default binding
    assert txn.twin_version == 0 and txn.twin_hash == "genesis", (
        "the default binding no longer resolves to the untouched default twin -- guard is vacuous")


def test_the_default_site_path_is_unchanged(st):
    """Back-compat: a resync at the default site behaves exactly as before."""
    from stewie.server.world_state import WorldStateService

    tw = st.twin()
    svc = WorldStateService(twin=st.twin, journal_path=None)
    _advance(tw, 1)
    txn = svc.record_resync(provenance="r1", site="haworth", twin=tw)
    assert txn.twin_version == 1 and txn.twin_hash != "genesis"


def test_each_site_records_its_own_twins_identity(st):
    """Each transaction must carry the identity of ITS OWN twin.

    Deliberately NOT asserting that two sites have different hashes: the twin hash is a content hash of
    the event chain, so two sites given identical patches on identical bases legitimately share one --
    my first version of this test asserted that and was wrong. The requirement is correspondence, not
    distinctness.
    """
    from stewie.server.world_state import WorldStateService

    a, b = st.twin("shackleton_rim"), st.twin("nobile_rim")
    svc = WorldStateService(twin=st.twin, journal_path=None)
    _advance(a, 1)
    _advance(b, 7)                                  # different content -> different chain
    ta = svc.record_resync(provenance="a", site="shackleton_rim", twin=a)
    tb = svc.record_resync(provenance="b", site="nobile_rim", twin=b)
    assert (ta.twin_version, ta.twin_hash) == a.identity(), "site A recorded another twin's identity"
    assert (tb.twin_version, tb.twin_hash) == b.identity(), "site B recorded another twin's identity"
