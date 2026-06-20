"""B2.x telemetry injector -- the operator-bound message pipe over the link constraint layer (P21/P23).

Where ``telemetry.TelemetryLink`` is the per-packet link primitive (token bucket, drop, latency,
per-sol budget), the ``TelemetryInjector`` drives a STREAM of operator-bound messages through it and
publishes the running link accounting on a stats channel. It is what sits between the simulation's
telemetry topics and the operator-trainee view: every operator-bound message is rate-limited to the
profile's bytes/s, seeded-dropped (drops COUNTED on the stats channel), and stamped with the downlink
visibility time; operator commands are uplink-latency delayed. The director path never runs through it.

Two named mission profiles back it (see ``profiles/``): ``ideal`` disables every constraint;
``mission_default`` carries [ASSUMPTION]-tagged placeholders until the rover team supplies the real
link budget (B2.1 [DECISION]). Pure-python + numpy; deterministic under ``seed``.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from stewie.bridge.telemetry import LinkProfile, TelemetryLink, load_profile

_PROFILE_DIR = os.path.join(os.path.dirname(__file__), "profiles")


@dataclass(frozen=True)
class OperatorMessage:
    """One operator-bound telemetry message offered to the link at ``t_s``.

    ``payload_bytes`` is the on-the-wire size the link budget draws against; ``body`` is the decoded
    content the operator sees IF it is delivered (pose, status, image meta -- never truth-denylisted
    fields, which the director path handles separately).
    """
    t_s: float
    payload_bytes: int
    kind: str = "telem"
    body: dict = field(default_factory=dict)


@dataclass
class InjectResult:
    """The fate of one injected message: delivered (with its operator-visibility time) or not, with
    the reason it was held back (``dropped`` | ``rate_limited`` | ``stranded``)."""
    message: OperatorMessage
    delivered: bool
    reason: str = ""                                        # "" when delivered
    visible_at: float | None = None                        # operator-visibility time when delivered


@dataclass
class StatsChannel:
    """The published link-accounting topic: running totals over the injected stream. Every message
    lands in exactly one of {delivered, dropped, rate_limited, stranded}; ``injected`` is their sum."""
    injected: int = 0
    delivered: int = 0
    dropped: int = 0
    rate_limited: int = 0
    stranded: int = 0
    bytes_delivered: int = 0

    def snapshot(self) -> dict:
        return {"injected": self.injected, "delivered": self.delivered, "dropped": self.dropped,
                "rate_limited": self.rate_limited, "stranded": self.stranded,
                "bytes_delivered": self.bytes_delivered}


@dataclass
class TelemetryInjector:
    """Drives a stream of operator-bound messages through one ``TelemetryLink`` and publishes the
    link accounting on ``stats_channel``. One instance per operator session; deterministic under
    ``seed`` (the link's drop RNG is seeded from it)."""
    profile: LinkProfile
    seed: int = 0
    _link: TelemetryLink = field(init=False)
    stats_channel: StatsChannel = field(init=False, default_factory=StatsChannel)

    def __post_init__(self):
        self._link = TelemetryLink(self.profile, seed=self.seed)

    @classmethod
    def from_profile_name(cls, name: str, *, seed: int = 0) -> "TelemetryInjector":
        """Build from a named profile in ``profiles/`` (``ideal`` / ``mission_default`` / ...)."""
        path = os.path.join(_PROFILE_DIR, f"{name}.json")
        if not os.path.exists(path):
            raise FileNotFoundError(f"no link profile {name!r} in {_PROFILE_DIR}")
        return cls(load_profile(path), seed=seed)

    def inject_one(self, msg: OperatorMessage) -> InjectResult:
        """Offer one operator-bound message to the link. Updates the stats channel and returns its
        fate. ``deliver_at`` resolves drop / rate-limit / per-sol-budget in one accounting step."""
        self.stats_channel.injected += 1
        before = dict(self._link.stats)
        visible = self._link.deliver_at(msg.payload_bytes, msg.t_s, name=msg.kind)
        if visible is not None:
            self.stats_channel.delivered += 1
            self.stats_channel.bytes_delivered += int(msg.payload_bytes)
            return InjectResult(message=msg, delivered=True, reason="", visible_at=visible)
        # not delivered: name WHY from the link's own counters (never a silent drop)
        if self._link.stats["dropped"] > before["dropped"]:
            self.stats_channel.dropped += 1
            reason = "dropped"
        elif self._link.stats["stranded"] > before["stranded"]:
            self.stats_channel.stranded += 1
            reason = "stranded"
        else:
            self.stats_channel.rate_limited += 1
            reason = "rate_limited"
        return InjectResult(message=msg, delivered=False, reason=reason, visible_at=None)

    def inject(self, msgs: list[OperatorMessage]) -> list[InjectResult]:
        """Inject a stream in order (the link is stateful: bucket refill + per-sol ledger advance)."""
        return [self.inject_one(m) for m in msgs]

    def send_command(self, cmd: dict, t_s: float) -> None:
        """Queue an operator command on the uplink (latency-delayed delivery, in order)."""
        self._link.send_command(cmd, t_s)

    def poll_commands(self, t_s: float) -> list:
        """Commands whose uplink latency has elapsed by ``t_s`` (delivered once, in order)."""
        return self._link.poll_commands(t_s)

    def reset_sol(self) -> None:
        """New sol: the per-sol byte ledger resets (the stranded log on the link persists)."""
        self._link.reset_sol()
