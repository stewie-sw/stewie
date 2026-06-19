"""[REQ:AS-14] map structured ROS diagnostics + autonomy events to the observability ledger (§25
Phase 12).

Turns the autonomy graph's diagnostics (lifecycle, latency, dropped frames, QoS warnings, command
eligibility, SAFE events, faults) into ledger events carrying a severity + the FS-19 correlation id,
and redacts BOTH secrets AND evaluation-truth fields before emission:

  * secrets    -- password/token/api_key/key/... (mirrors services._REDACT_KEYS; never store a credential)
  * truth      -- the I3/UI-11 eval-only signals an estimator/operator log must never carry: the
                  autonomy_contract truth channels (/stewie/truth/*) + rover/lander/camera_poses_in_world
                  + the seen-vs-actual gap.

Every failure path maps to a FAILURE_EVENTS kind, so a logged autonomy failure always lands a ledger
event; no secret or truth-denied field ever reaches it. Pure logic; the server ledger (services.log_event)
is the durable sink for the HTTP side and already redacts secrets -- this adds the truth guard + the ROS
diagnostics taxonomy.
"""
from __future__ import annotations

from stewie.bridge import autonomy_contract as AC

_SECRET_KEYS = {"password", "passwd", "pass", "token", "api_key", "apikey", "key", "secret",
                "authorization", "cookie", "session_token"}

# truth-denied: eval-only signals (sensor_io._FORBIDDEN_RUNTIME_KEYS + the TRUTH_TOPICS + the UI-11 gap)
_TRUTH_KEYS = ({"rover", "lander", "camera_poses_in_world", "truth", "ground_truth", "gt",
                "true_pose", "true_dem", "true_clasts", "seen_vs_actual", "truth_pose"}
               | {t.strip("/").replace("/", "_") for t in AC.TRUTH_TOPICS})

# AS-14 failure-path event kinds -> default severity (every failure path has a ledger event)
FAILURE_EVENTS = {
    "lifecycle_error": "error", "latency_breach": "warn", "dropped_frame": "warn",
    "qos_warning": "warn", "command_ineligible": "warn", "safe_event": "critical", "fault": "critical",
}


def _redact(obj):
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            kl = str(k).lower()
            if kl in _SECRET_KEYS:
                out[k] = "[redacted]"
            elif kl in _TRUTH_KEYS:
                out[k] = "[truth-denied]"           # eval-only: WHAT flowed is logged, never the value
            else:
                out[k] = _redact(v)
        return out
    if isinstance(obj, (list, tuple)):
        return [_redact(v) for v in obj]
    return obj


def is_failure(event: str) -> bool:
    return event in FAILURE_EVENTS


def ledger_event(source: str, event: str, *, correlation_id: str, severity: str | None = None,
                 **fields) -> dict:
    """Build a ledger event for a ROS diagnostic / autonomy event. severity defaults from the failure
    taxonomy (else 'info'). Field values are stripped of secrets + truth-denied signals."""
    return {
        "source": source,
        "event": event,
        "severity": severity or FAILURE_EVENTS.get(event, "info"),
        "correlation_id": correlation_id,
        "fields": _redact(fields),
    }
