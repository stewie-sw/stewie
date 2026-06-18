"""NV-12: a versioned streaming command/telemetry session for the live ROS2 / Space ROS link.

Every frame carries (``protocol_version``, a monotonic ``seq``, a ``timestamp``); a BOUNDED un-acked
window applies BACKPRESSURE (frames beyond the window are refused + counted -- a command channel never
silently drops); and an SF-01-tied SAFE-STOP trips when the link STALLS (the oldest un-acked frame goes
un-acked past ``ack_deadline_s``). Consumer ``ack`` is cumulative and is the link heartbeat.

Pure + deterministic: the caller supplies ``now`` (the ``SafingWatchdog`` pattern -- no wall clock), so
the session is fully testable without ROS2 (the bridge's rclpy-optional convention). The live node feeds
real timestamps + consumer acks and wires ``on_safe_stop`` to submit ``RC.Safe(SAFE_REASON_LINK_STALL)``
through the same backend the SF-01 command-timeout watchdog uses. NV-11's lowered messages publish on
this session, so a stalled downlink/uplink safes the rover.
"""
from __future__ import annotations

from collections.abc import Callable

PROTOCOL_VERSION = "1.0"


class StreamSession:
    """A versioned, sequence-numbered, back-pressured command/telemetry stream with an SF-01 safe-stop."""

    def __init__(self, *, window: int = 64, ack_deadline_s: float = 2.0,
                 on_safe_stop: Callable[[], None] | None = None) -> None:
        if window < 1:
            raise ValueError(f"window must be >= 1 (got {window})")
        if ack_deadline_s <= 0:
            raise ValueError(f"ack_deadline_s must be > 0 (got {ack_deadline_s})")
        self.window = int(window)
        self.ack_deadline_s = float(ack_deadline_s)
        self._on_safe_stop = on_safe_stop
        self.seq = 0                                       # next sequence number to assign
        self.last_ack = -1                                 # highest cumulatively-acked seq
        self.refused = 0                                   # frames refused by backpressure
        self.tripped = False
        self._sent_t: dict[int, float] = {}                # un-acked seq -> send timestamp

    def send(self, payload, *, now: float):
        """Frame + enqueue a payload. Returns the versioned frame dict, or None when BACKPRESSURE refuses
        it (the un-acked window is full -- the caller must wait for acks; commands are never dropped)."""
        if self.tripped:
            return None
        if len(self._sent_t) >= self.window:
            self.refused += 1
            return None
        f = {"v": PROTOCOL_VERSION, "seq": self.seq, "t": float(now), "payload": payload}
        self._sent_t[self.seq] = float(now)
        self.seq += 1
        return f

    def ack(self, seq: int) -> None:
        """Cumulative consumer ack up through ``seq`` -- clears the un-acked window (the link heartbeat)."""
        if seq <= self.last_ack:
            return
        for s in [k for k in self._sent_t if k <= seq]:
            self._sent_t.pop(s, None)
        self.last_ack = seq

    def tick(self, *, now: float) -> bool:
        """Trip the SAFE-STOP if the oldest un-acked frame has gone un-acked past ``ack_deadline_s``
        (the link stalled). Idempotent once tripped; fires ``on_safe_stop`` exactly once. Returns tripped."""
        if self.tripped:
            return True
        if self._sent_t and (now - min(self._sent_t.values())) > self.ack_deadline_s:
            self.tripped = True
            if self._on_safe_stop is not None:
                self._on_safe_stop()
        return self.tripped

    @property
    def outstanding(self) -> int:
        """Frames sent but not yet acked (the live backpressure depth)."""
        return len(self._sent_t)

    def status(self) -> dict:
        return {"version": PROTOCOL_VERSION, "seq": self.seq, "last_ack": self.last_ack,
                "outstanding": self.outstanding, "window": self.window,
                "refused": self.refused, "tripped": self.tripped}
