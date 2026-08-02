"""[AR-002] The release ceremony must be authenticated, multi-actor, and verifiable offline.

The 2026-07-16 review: `SignedRevision.signed_by` receives the ROLE LITERAL ("director"), not an
authenticated identity, key id, signature or time -- and `run_lifecycle` advances analyze -> rehearse
-> review -> release in one loop, so ONE HTTP actor populates all four nominal transitions and mints a
live-looking token. "The hash is useful for content identity, but calling it a signature overstates
the security property."

These tests pin the substrate against the review's own acceptance criteria:

  * every required transition carries a durable actor identity and evidence;
  * policy forbids self-approval;
  * signature verification works OFFLINE from an exported artifact;
  * key rotation and revocation behave;
  * duplicate release of an identical intent produces a DISTINCT approval event without mutating the
    content artifact.

Run: <venv>/bin/python -m pytest stewie/contracts/test_attestation.py -q
"""
from __future__ import annotations

import json

import pytest

from stewie.contracts import attestation as A

pytest.importorskip("cryptography", reason="AR-002 signing requires the optional 'cryptography' dep")

_ARTIFACT = "a" * 64


def _actor(name, transition, keys, *, decision="approve", artifact=_ARTIFACT, ts=1000.0):
    """Mint + sign one attestation as `name`, using that actor's own key."""
    sk, pk, kid = keys[name]
    att = A.Attestation(
        artifact_hash=artifact, transition=transition, actor_id=name,
        actor_role_at_time=A.ROLE_FOR_TRANSITION[transition], decision=decision,
        timestamp=ts, key_id=kid, evidence_hashes=(A.evidence_hash({"t": transition}),))
    return A.sign(att, sk)


@pytest.fixture()
def keys():
    out = {}
    for name in ("alice", "bob", "carol", "dave"):
        sk, pk = A.generate_keypair()
        out[name] = (sk, pk, f"key.{name}.v1")
    return out


@pytest.fixture()
def keyring(keys):
    kr = A.Keyring()
    for _n, (_sk, pk, kid) in keys.items():
        kr.add(kid, pk)
    return kr


def _full_ceremony(keys):
    return [_actor("alice", "analyze", keys), _actor("bob", "rehearse", keys),
            _actor("carol", "review", keys), _actor("dave", "release", keys)]


# ---- signature + offline verification ---------------------------------------------------------

def test_a_signed_attestation_verifies(keys, keyring):
    ok, why = A.verify(_actor("alice", "analyze", keys), keyring)
    assert ok, why


def test_tampering_with_any_field_breaks_the_signature(keys, keyring):
    """A signature that survived edits would be no better than the content hash it replaces."""
    import dataclasses
    att = _actor("alice", "analyze", keys)
    for fld, val in (("actor_id", "mallory"), ("decision", "reject"),
                     ("artifact_hash", "b" * 64), ("transition", "release")):
        ok, _ = A.verify(dataclasses.replace(att, **{fld: val}), keyring)
        assert ok is False, f"tampering with {fld} did not invalidate the signature"


def test_verification_is_offline_from_an_exported_artifact(keys, keyring, tmp_path):
    """The acceptance criterion: export, carry away, verify with no DB, no network, no secret."""
    bundle = {"attestations": [a.to_dict() for a in _full_ceremony(keys)],
              "keyring": keyring.to_dict()}
    p = tmp_path / "ceremony.json"
    p.write_text(json.dumps(bundle))

    loaded = json.loads(p.read_text())
    kr = A.Keyring.from_dict(loaded["keyring"])
    atts = [A.Attestation.from_dict(d) for d in loaded["attestations"]]
    assert all(A.verify(a, kr)[0] for a in atts)
    ok, why = A.check_ceremony(atts, _ARTIFACT, kr)
    assert ok, why
    # and the private halves are nowhere in the exported artifact
    for _n, (sk, _pk, _kid) in keys.items():
        assert sk.hex() not in p.read_text(), "a private key leaked into the exported bundle"


# ---- key rotation + revocation ------------------------------------------------------------------

def test_a_revoked_key_verifies_nothing(keys, keyring):
    att = _actor("dave", "release", keys)
    assert A.verify(att, keyring)[0] is True
    keyring.revoke(keys["dave"][2])
    ok, why = A.verify(att, keyring)
    assert ok is False and "revoked" in why


def test_rotation_keeps_the_old_key_verifying_until_revoked(keys, keyring):
    """Rotation must not silently invalidate history; revocation is the deliberate act that does."""
    old = _actor("dave", "release", keys)
    sk2, pk2 = A.generate_keypair()
    keyring.add("key.dave.v2", pk2)
    assert A.verify(old, keyring)[0] is True          # v1 still verifies after v2 exists
    keyring.revoke(keys["dave"][2])
    assert A.verify(old, keyring)[0] is False


def test_an_unknown_key_is_refused(keys, keyring):
    import dataclasses
    att = dataclasses.replace(_actor("alice", "analyze", keys), key_id="key.nobody.v1")
    ok, why = A.verify(att, keyring)
    assert ok is False and "unknown key" in why


def test_an_unimplemented_algorithm_is_refused_not_guessed(keys, keyring):
    import dataclasses
    att = dataclasses.replace(_actor("alice", "analyze", keys), algorithm="rsa-pkcs1")
    ok, why = A.verify(att, keyring)
    assert ok is False and "unsupported algorithm" in why


# ---- the ceremony policy ------------------------------------------------------------------------

def test_a_full_four_actor_ceremony_passes(keys, keyring):
    ok, why = A.check_ceremony(_full_ceremony(keys), _ARTIFACT, keyring)
    assert ok, why


def test_the_one_actor_advance_all_is_refused(keys, keyring):
    """THE core AR-002 defect: one actor driving analyze->rehearse->review->release."""
    solo = [_actor("alice", t, keys) for t in A.REQUIRED_TRANSITIONS]
    ok, why = A.check_ceremony(solo, _ARTIFACT, keyring)
    assert ok is False
    assert "self-approval" in why or "distinct actors" in why


def test_self_approval_is_refused_even_with_role_stacking_allowed(keys, keyring):
    """Role stacking is an explicit policy carve-out; reviewing your own release is never one."""
    atts = [_actor("alice", "analyze", keys), _actor("alice", "rehearse", keys),
            _actor("carol", "review", keys), _actor("carol", "release", keys)]
    ok, why = A.check_ceremony(atts, _ARTIFACT, keyring, allow_role_stacking=True)
    assert ok is False and "self-approval" in why


def test_role_stacking_is_allowed_when_explicitly_permitted(keys, keyring):
    atts = [_actor("alice", "analyze", keys), _actor("alice", "rehearse", keys),
            _actor("carol", "review", keys), _actor("dave", "release", keys)]
    assert A.check_ceremony(atts, _ARTIFACT, keyring, allow_role_stacking=True)[0] is True
    ok, why = A.check_ceremony(atts, _ARTIFACT, keyring)          # default: strict
    assert ok is False and "distinct actors" in why


def test_a_missing_transition_is_refused(keys, keyring):
    atts = [a for a in _full_ceremony(keys) if a.transition != "review"]
    ok, why = A.check_ceremony(atts, _ARTIFACT, keyring)
    assert ok is False and "review" in why


def test_an_attestation_for_another_artifact_does_not_count(keys, keyring):
    """A signature over a different plan is not consent to this one."""
    atts = _full_ceremony(keys)[:-1] + [_actor("dave", "release", keys, artifact="b" * 64)]
    ok, why = A.check_ceremony(atts, _ARTIFACT, keyring)
    assert ok is False and "different artifact" in why


def test_a_rejection_blocks_the_ceremony(keys, keyring):
    atts = _full_ceremony(keys)[:2] + [_actor("carol", "review", keys, decision="reject"),
                                       _actor("dave", "release", keys)]
    ok, why = A.check_ceremony(atts, _ARTIFACT, keyring)
    assert ok is False and "reject" in why


def test_the_wrong_role_for_a_transition_is_refused(keys, keyring):
    import dataclasses
    bad = dataclasses.replace(_actor("dave", "release", keys), actor_role_at_time="planner")
    signed = A.sign(bad, keys["dave"][0])             # correctly signed, but wrong role asserted
    atts = _full_ceremony(keys)[:-1] + [signed]
    ok, why = A.check_ceremony(atts, _ARTIFACT, keyring)
    assert ok is False and "requires 'director'" in why


def test_duplicate_release_of_identical_intent_is_a_distinct_event(keys, keyring):
    """The review's last criterion: re-releasing the same content makes a NEW approval event and does
    not mutate the artifact."""
    first = _actor("dave", "release", keys, ts=1000.0)
    second = _actor("dave", "release", keys, ts=2000.0)
    assert first.artifact_hash == second.artifact_hash      # same content artifact, unmutated
    assert first.signature != second.signature              # distinct authenticated events
    assert A.verify(first, keyring)[0] and A.verify(second, keyring)[0]
    # and presenting both in one ceremony is a duplicate, not a stronger approval
    atts = _full_ceremony(keys) + [second]
    ok, why = A.check_ceremony(atts, _ARTIFACT, keyring)
    assert ok is False and "duplicate" in why
