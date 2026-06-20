"""B3.3 replay/debrief record -- ``SessionRecord`` (PRD 6.1 artifact 9, P22/P23 intern beta).

A training session's recorded legs: for every step BOTH the simulator TRUTH state and the
operator-DELIVERED view (``seen``, ``None`` when the link held the leg back), plus the delivery
verdict and the reason. The debrief scrubs seen-vs-actual divergence over this record; ``replay``
reproduces the recorded run from the record ALONE (a view over the artifact, not a recomputation, per
PRD 6.1: "Reports, Plan IR, playback ... must be views over these artifacts"). The record is
hash-anchored (sha256 over the ordered steps) so a tampered leg is detectable, and round-trips
through JSON. Pure-python; no ROS2 required.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field


@dataclass
class SessionStep:
    """One recorded leg: the truth at ``t_s`` and what the operator actually saw (``seen``)."""
    t_s: float
    truth: dict
    seen: dict | None                                      # None == not delivered to the operator
    delivered: bool
    reason: str = ""                                       # "" delivered; else dropped/rate_limited/...


@dataclass
class SessionRecord:
    """A recorded training session: the link profile + seed it ran under, and the ordered legs."""
    profile_name: str
    seed: int
    steps: list = field(default_factory=list)

    def record_step(self, *, t_s: float, truth: dict, seen: dict | None, delivered: bool,
                    reason: str = "") -> None:
        """Append one leg. ``truth`` is always recorded; ``seen`` is the delivered operator view
        (must be None exactly when ``delivered`` is False -- the record must not claim the operator
        saw a leg the link dropped)."""
        if delivered and seen is None:
            raise ValueError("a delivered leg must record the operator-seen view")
        if not delivered and seen is not None:
            raise ValueError("a non-delivered leg must record seen=None")
        self.steps.append(SessionStep(t_s=float(t_s), truth=truth, seen=seen,
                                      delivered=bool(delivered), reason=reason))

    def debrief(self) -> dict:
        """The seen-vs-actual divergence summary (the debrief surface)."""
        n = len(self.steps)
        delivered = sum(1 for s in self.steps if s.delivered)
        return {"steps": n, "delivered": delivered, "not_delivered": n - delivered,
                "delivery_fraction": (delivered / n) if n else 0.0,
                "profile_name": self.profile_name, "seed": self.seed}

    def content_hash(self) -> str:
        """sha256 over the ordered steps -- a stable anchor; any edited leg changes it."""
        payload = json.dumps([asdict(s) for s in self.steps], sort_keys=True,
                             separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def to_json(self) -> str:
        return json.dumps({"profile_name": self.profile_name, "seed": self.seed,
                           "steps": [asdict(s) for s in self.steps]}, sort_keys=True)

    @classmethod
    def from_json(cls, blob: str) -> "SessionRecord":
        doc = json.loads(blob)
        rec = cls(profile_name=doc["profile_name"], seed=int(doc["seed"]))
        rec.steps = [SessionStep(**s) for s in doc["steps"]]
        return rec


def replay(record: SessionRecord) -> list:
    """Reproduce the recorded run from the record alone: the ordered legs exactly as recorded.

    This is a VIEW over the artifact (not a recomputation): a debrief scrubber, playback head, or a
    seen-vs-actual diff iterates the returned steps and reads ``truth`` vs ``seen``. Returns a fresh
    list of ``SessionStep`` copies so a consumer scrubbing the playback cannot mutate the record.
    """
    return [SessionStep(t_s=s.t_s, truth=dict(s.truth),
                        seen=(dict(s.seen) if s.seen is not None else None),
                        delivered=s.delivered, reason=s.reason)
            for s in record.steps]
