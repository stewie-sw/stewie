"""[AR-002] Authenticated multi-actor attestations for the release ceremony.

The 2026-07-16 review found `SignedRevision` stores a deterministic SHA-256 content hash plus a
`signed_by` string that receives the ROLE LITERAL ("director") -- not an authenticated identity, key
id, signature or time. `run_lifecycle` then advances analyze -> rehearse -> review -> release in one
loop, so a single HTTP actor causes the system to populate nominal planner/operator/reviewer/director
transitions and mint a live-looking token. As the review put it: a content digest proves equality only
when obtained through a trusted channel; it does not prove which person approved it.

This module supplies the substrate the review specified:

    Attestation = artifact_hash + transition + actor_id + actor_role_at_time
                  + evidence_hashes + decision + timestamp + key_id + signature

Design notes, and their limits, stated plainly:

* **Asymmetric by requirement, not preference.** The acceptance criterion is that signature
  verification works OFFLINE from an exported artifact. HMAC cannot satisfy that -- verifying it
  requires the signing secret, so anyone who can verify can also forge. Signing is Ed25519.
* **`cryptography` is an OPTIONAL dependency** (it is installed here but is NOT in
  `requirements-dev.lock`). When absent, signing and verification RAISE rather than degrading to a
  keyed hash, because a keyed hash that calls itself a signature is the exact overstatement AR-002
  is about. Callers fail closed; tests skip loudly.
* **Crypto agility** is recorded, not assumed: every attestation carries `algorithm` and `key_id`, and
  verification refuses an algorithm it does not implement rather than guessing.

NOT SUPPLIED HERE, and therefore still open on AR-002: key custody and the operational signing
service, the approval-ceremony UI, and enforcement on the live release route. Those are deployment
decisions, not library code. What is here is the record format, the signature, offline verification,
key rotation/revocation, and the separation-of-duties policy -- all independently testable.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from typing import Iterable, Mapping

#: The transitions a release ceremony requires, and the role each is performed AS.
REQUIRED_TRANSITIONS: tuple[str, ...] = ("analyze", "rehearse", "review", "release")
ROLE_FOR_TRANSITION: Mapping[str, str] = {
    "analyze": "planner", "rehearse": "operator", "review": "reviewer", "release": "director",
}

ALGORITHM_ED25519 = "ed25519"


class AttestationError(RuntimeError):
    """Signing or verification could not be performed as specified (never a silent downgrade)."""


@dataclass(frozen=True)
class Attestation:
    """One authenticated decision by one actor about one artifact. Frozen: re-deciding makes a NEW
    attestation, it never edits an existing one."""
    artifact_hash: str
    transition: str
    actor_id: str
    actor_role_at_time: str
    decision: str                      # "approve" | "reject"
    timestamp: float
    key_id: str
    algorithm: str = ALGORITHM_ED25519
    evidence_hashes: tuple[str, ...] = field(default_factory=tuple)
    signature: str = ""                # hex; empty until signed

    def signing_payload(self) -> bytes:
        """The canonical bytes that are signed. Excludes `signature` (it cannot cover itself) and is
        key-order stable, so an exported artifact verifies byte-for-byte on another machine."""
        body = {
            "artifact_hash": self.artifact_hash, "transition": self.transition,
            "actor_id": self.actor_id, "actor_role_at_time": self.actor_role_at_time,
            "decision": self.decision, "timestamp": self.timestamp,
            "key_id": self.key_id, "algorithm": self.algorithm,
            "evidence_hashes": list(self.evidence_hashes),
        }
        return json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")

    def to_dict(self) -> dict:
        d = {k: getattr(self, k) for k in (
            "artifact_hash", "transition", "actor_id", "actor_role_at_time", "decision",
            "timestamp", "key_id", "algorithm", "signature")}
        d["evidence_hashes"] = list(self.evidence_hashes)
        return d

    @staticmethod
    def from_dict(d: Mapping) -> "Attestation":
        return Attestation(
            artifact_hash=str(d["artifact_hash"]), transition=str(d["transition"]),
            actor_id=str(d["actor_id"]), actor_role_at_time=str(d["actor_role_at_time"]),
            decision=str(d["decision"]), timestamp=float(d["timestamp"]),
            key_id=str(d["key_id"]), algorithm=str(d.get("algorithm", ALGORITHM_ED25519)),
            evidence_hashes=tuple(str(h) for h in d.get("evidence_hashes", ())),
            signature=str(d.get("signature", "")))


def _ed25519():
    try:
        from cryptography.hazmat.primitives.asymmetric import ed25519
    except ImportError as e:                      # optional dep -- fail closed, never downgrade
        raise AttestationError(
            "ed25519 signing requires the 'cryptography' package; refusing to substitute a keyed hash, "
            "which cannot be verified offline and is not a signature") from e
    return ed25519


def generate_keypair() -> tuple[bytes, bytes]:
    """(private_bytes, public_bytes) raw Ed25519. Custody of the private half is a deployment concern."""
    ed = _ed25519()
    sk = ed.Ed25519PrivateKey.generate()
    from cryptography.hazmat.primitives import serialization as _ser
    return (sk.private_bytes(_ser.Encoding.Raw, _ser.PrivateFormat.Raw, _ser.NoEncryption()),
            sk.public_key().public_bytes(_ser.Encoding.Raw, _ser.PublicFormat.Raw))


def sign(att: Attestation, private_key: bytes) -> Attestation:
    """Return a signed copy. The attestation's own `key_id` identifies which public key verifies it."""
    if att.algorithm != ALGORITHM_ED25519:
        raise AttestationError(f"unsupported signing algorithm {att.algorithm!r}")
    ed = _ed25519()
    sk = ed.Ed25519PrivateKey.from_private_bytes(private_key)
    return replace(att, signature=sk.sign(att.signing_payload()).hex())


@dataclass
class Keyring:
    """Public keys by id, plus revocations. Verification is OFFLINE: this and the exported
    attestations are all that is needed -- no database, no network, no signing secret."""
    keys: dict[str, bytes] = field(default_factory=dict)
    revoked: set[str] = field(default_factory=set)

    def add(self, key_id: str, public_key: bytes) -> None:
        self.keys[key_id] = public_key

    def revoke(self, key_id: str) -> None:
        """A revoked key verifies NOTHING further. Deliberately not time-scoped: without a trusted
        timestamp authority, 'valid before revocation' is a claim this system cannot make honestly."""
        self.revoked.add(key_id)

    def to_dict(self) -> dict:
        return {"keys": {k: v.hex() for k, v in self.keys.items()}, "revoked": sorted(self.revoked)}

    @staticmethod
    def from_dict(d: Mapping) -> "Keyring":
        return Keyring(keys={k: bytes.fromhex(v) for k, v in dict(d.get("keys", {})).items()},
                       revoked=set(d.get("revoked", ())))


def verify(att: Attestation, keyring: Keyring) -> tuple[bool, str]:
    """(ok, reason). Offline: needs only the attestation and the public keyring."""
    if att.algorithm != ALGORITHM_ED25519:
        return False, f"unsupported algorithm {att.algorithm!r}"
    if not att.signature:
        return False, "unsigned"
    if att.key_id in keyring.revoked:
        return False, f"key {att.key_id!r} is revoked"
    pub = keyring.keys.get(att.key_id)
    if pub is None:
        return False, f"unknown key {att.key_id!r}"
    ed = _ed25519()
    try:
        ed.Ed25519PublicKey.from_public_bytes(pub).verify(bytes.fromhex(att.signature),
                                                          att.signing_payload())
    except Exception:                      # noqa: BLE001 -- InvalidSignature or malformed input
        return False, "signature does not verify"
    return True, "ok"


def evidence_hash(payload) -> str:
    """Stable content hash for an evidence object, so an attestation binds WHAT was reviewed."""
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def check_ceremony(attestations: Iterable[Attestation], artifact_hash: str, keyring: Keyring,
                   *, allow_role_stacking: bool = False) -> tuple[bool, str]:
    """Is this a valid multi-actor release ceremony for `artifact_hash`?

    Enforced:
      * every required transition present, approved, and cryptographically verified;
      * every attestation bound to THIS artifact (a signature over another plan is not consent to this one);
      * the role asserted matches the role the transition requires;
      * NO SELF-APPROVAL -- the actor who releases must not be the actor who reviewed.

    `allow_role_stacking` models the review's explicit carve-out: a small mission may let one person
    hold several roles, but it must be a deliberate policy choice, and even then it must produce
    separate authenticated decisions. Self-approval of one's own review stays forbidden either way,
    because that is the check that makes review mean anything.
    """
    atts = list(attestations)
    by_transition: dict[str, Attestation] = {}
    for a in atts:
        if a.artifact_hash != artifact_hash:
            return False, f"attestation for a different artifact: {a.artifact_hash[:12]}"
        ok, why = verify(a, keyring)
        if not ok:
            return False, f"{a.transition}: {why}"
        if a.decision != "approve":
            return False, f"{a.transition}: decision is {a.decision!r}"
        expected = ROLE_FOR_TRANSITION.get(a.transition)
        if expected and a.actor_role_at_time != expected:
            return False, (f"{a.transition}: performed as {a.actor_role_at_time!r}, "
                           f"requires {expected!r}")
        if a.transition in by_transition:
            return False, f"duplicate attestation for {a.transition}"
        by_transition[a.transition] = a

    missing = [t for t in REQUIRED_TRANSITIONS if t not in by_transition]
    if missing:
        return False, f"missing attestations: {missing}"

    reviewer = by_transition["review"].actor_id
    releaser = by_transition["release"].actor_id
    if reviewer == releaser:
        return False, (f"self-approval: {releaser!r} both reviewed and released -- separation of duties "
                       "requires a second actor for release")
    if not allow_role_stacking:
        actors = {a.actor_id for a in by_transition.values()}
        if len(actors) < len(REQUIRED_TRANSITIONS):
            return False, (f"{len(actors)} distinct actors for {len(REQUIRED_TRANSITIONS)} transitions; "
                           "set allow_role_stacking to permit one person holding several roles")
    return True, "ok"
