"""Telemetry injection layer — the mission-link constraint model (STEWIE P21 / beta B2).

The operator-trainee receives ONLY what survives this layer: a token-bucket downlink budget,
seeded packet drop (counted, reported), uplink command latency, and a camera byte budget. The
director path bypasses it entirely (B3). Pure python + numpy; deterministic under ``seed``; the
ROS2 bridge (B1) wires it between the sim topics and the operator topics.

Profiles are JSON (see ``profiles/``): ``ideal.json`` disables every constraint for quick testing;
``mission_default.json`` carries [ASSUMPTION]-tagged placeholders until the rover team supplies the
real link budget (atomic plan B2.1 [DECISION]).
"""
from __future__ import annotations

import io
import json
import os
from dataclasses import dataclass, field

import numpy as np

_ALLOWED = {"downlink_kbps", "uplink_latency_ms", "drop_prob", "camera_fps",
            "camera_max_bytes", "provenance"}


@dataclass(frozen=True)
class LinkProfile:
    """One mission link budget. ``None``/0 fields mean UNCONSTRAINED (the ideal profile)."""
    downlink_kbps: float | None = None
    uplink_latency_ms: float = 0.0
    drop_prob: float = 0.0
    camera_fps: float | None = None
    camera_max_bytes: int | None = None
    provenance: str = ""

    def __post_init__(self):
        if self.downlink_kbps is not None and self.downlink_kbps <= 0:
            raise ValueError("downlink_kbps must be > 0 or None")
        if not (0.0 <= self.drop_prob < 1.0):
            raise ValueError("drop_prob must be in [0, 1)")
        if self.uplink_latency_ms < 0:
            raise ValueError("uplink_latency_ms must be >= 0")


def load_profile(path: str) -> LinkProfile:
    doc = json.load(open(path))
    unknown = set(doc) - _ALLOWED
    if unknown:
        raise ValueError(f"unknown link-profile keys {sorted(unknown)} in {os.path.basename(path)}")
    return LinkProfile(**doc)


@dataclass
class TelemetryLink:
    """Stateful link simulator: one instance per operator session.

    try_send(payload_bytes, t_s)  -> bool   (downlink: budget + drop; False = not delivered)
    send_command(cmd, t_s) / poll_commands(t_s)  (uplink: latency-delayed delivery, in order)
    fit_camera_frame(gray_image)  -> (png_bytes, meta)  (downscale until the byte budget fits)
    stats: {"sent", "dropped", "rate_limited", "bytes_delivered"}
    """
    profile: LinkProfile
    seed: int = 0
    _rng: np.random.Generator = field(init=False)
    _tokens: float = field(init=False, default=0.0)
    _last_t: float | None = field(init=False, default=None)
    _uplink: list = field(init=False, default_factory=list)
    stats: dict = field(init=False)

    def __post_init__(self):
        self._rng = np.random.default_rng(self.seed)
        self.stats = {"sent": 0, "dropped": 0, "rate_limited": 0, "bytes_delivered": 0}
        if self.profile.downlink_kbps:
            self._tokens = self.profile.downlink_kbps * 125.0   # burst capacity: 1 s of budget

    def _refill(self, t_s: float) -> None:
        if self.profile.downlink_kbps is None:
            return
        cap = self.profile.downlink_kbps * 125.0               # bytes per second
        if self._last_t is not None and t_s > self._last_t:
            self._tokens = min(cap, self._tokens + (t_s - self._last_t) * cap)
        self._last_t = t_s if self._last_t is None else max(self._last_t, t_s)

    def try_send(self, payload_bytes: int, t_s: float) -> bool:
        self._refill(t_s)
        if self.profile.downlink_kbps is not None:
            if payload_bytes > self._tokens:
                self.stats["rate_limited"] += 1
                return False
        if self.profile.drop_prob > 0.0 and self._rng.random() < self.profile.drop_prob:
            self.stats["dropped"] += 1
            return False
        if self.profile.downlink_kbps is not None:
            self._tokens -= payload_bytes
        self.stats["sent"] += 1
        self.stats["bytes_delivered"] += int(payload_bytes)
        return True

    def send_command(self, cmd: dict, t_s: float) -> None:
        self._uplink.append((t_s + self.profile.uplink_latency_ms / 1000.0, cmd))

    def poll_commands(self, t_s: float) -> list:
        due = [c for arrive, c in self._uplink if arrive <= t_s]
        self._uplink = [(a, c) for a, c in self._uplink if a > t_s]
        return due

    def fit_camera_frame(self, gray) -> tuple:
        """PNG-encode a grayscale frame, halving resolution until the byte budget fits."""
        from imageio.v3 import imwrite
        img = np.asarray(gray)
        scale = 1.0
        while True:
            buf = io.BytesIO()
            imwrite(buf, img.astype(np.uint8), extension=".png")
            blob = buf.getvalue()
            if self.profile.camera_max_bytes is None or len(blob) <= self.profile.camera_max_bytes \
                    or min(img.shape[:2]) <= 16:
                return blob, {"format": "png", "scale": scale, "bytes": len(blob)}
            img = img[::2, ::2]
            scale *= 0.5
