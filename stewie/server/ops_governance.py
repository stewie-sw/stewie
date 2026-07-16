"""[REQ:PO-15] Operations governance beyond account admin (frontend-100 audit finding 7 / review finding 7).

The maintenance/ops surface -- twin snapshot, snapshot retention, off-host replication -- was a set of
MANUAL director endpoints (``routers/admin_ops.py``) with no declared recovery policy and no monitored
signal that the backups are actually current. Account admin (``routers/operators_admin.py``) already has
its own review surface (``/events``, per-user history, last-director protection); this module is its
OPS-side sibling, adding the two backend pieces that finding named:

  1. A DECLARED retention / RPO policy (``RetentionPolicy``): the recovery-point objective (the max
     acceptable age of the freshest backup) plus the snapshot retention ladder, as typed, env-overridable
     data. The RPO is an operational POLICY TARGET (like the FS-10 per-route latency budgets in
     ``services.py``: a chosen target grounded in the machinery, not a measured value). The default
     snapshot RPO is ``cadence.SOL_SECONDS`` -- the ``SnapshotScheduler``'s own per-sol trigger is the
     worst-case interval between scheduled snapshots, so it is the natural snapshot RPO; a deployment
     tightens it via ``$STEWIE_SNAPSHOT_RPO_S`` / ``$STEWIE_REPLICA_RPO_S``. The retention ladder mirrors
     ``backup.apply_retention``'s enforced defaults so the declared policy cannot drift from what runs.

  2. A MONITORED last-success / age signal (``backup_status``): read from the REAL backup artifacts on
     disk -- the newest snapshot's and the newest off-host replica file's mtime is the last time that job
     actually succeeded -- compared against the policy RPO. ``degraded`` trips when a monitored job is
     absent or its freshest artifact is older than its RPO. This is the "is the scheduled backup keeping
     us inside the RPO?" signal that a cron / systemd timer running ``python -m stewie.twin.backup``
     (W-3) is enforced against; the manual endpoints stay, but they are now measured, not assumed.

The ops-action audit trail (``recent_ops_events``) surfaces the maintenance actions (twin/backup/gates)
and EXCLUDES account-admin actions, so this is governance BEYOND account admin. The director-only
``GET /admin/ops/governance`` route (``routers/admin_ops.py``) bundles the policy, the monitored status,
and the audit trail into one review surface.
"""
from __future__ import annotations

import json as _json
import os
import time
from dataclasses import asdict, dataclass

from stewie.specs import config as CFG
from stewie.twin import backup as _backup
from stewie.twin.cadence import SOL_SECONDS

#: the ops maintenance actions (twin snapshot/retention, backup replicate, gate validation). The
#: ``admin.operator.*`` account-admin actions are deliberately NOT here -- this is ops governance
#: BEYOND account admin, whose trail already lives in ``/events``.
OPS_ACTION_PREFIXES: tuple[str, ...] = ("admin.twin.", "admin.backup.", "admin.gates.")


@dataclass(frozen=True)
class RetentionPolicy:
    """The declared recovery policy: the RPO (max acceptable age of the freshest backup) per job, plus
    the snapshot retention ladder. ``keep_recent`` / ``ladder`` mirror ``backup.apply_retention``."""
    snapshot_rpo_s: float
    replica_rpo_s: float
    keep_recent: int
    ladder: int


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        v = float(raw)
    except ValueError:
        return default
    return v if v > 0 else default


def default_policy() -> RetentionPolicy:
    """The active policy: RPOs from env (default ``SOL_SECONDS`` -- the SnapshotScheduler's per-sol
    trigger) and the retention ladder read live off ``backup.apply_retention``'s signature defaults so
    the declared ladder can never drift from the one actually enforced."""
    import inspect
    sig = inspect.signature(_backup.apply_retention)
    return RetentionPolicy(
        snapshot_rpo_s=_env_float("STEWIE_SNAPSHOT_RPO_S", SOL_SECONDS),
        replica_rpo_s=_env_float("STEWIE_REPLICA_RPO_S", SOL_SECONDS),
        keep_recent=int(sig.parameters["keep_recent"].default),
        ladder=int(sig.parameters["ladder"].default),
    )


def _replica_dir() -> str:
    """The off-host replica destination, mirroring ``routers/admin_ops.admin_replicate``."""
    return os.environ.get("STEWIE_BACKUP_DIR", os.path.join(CFG.data_dir(), "replica"))


def _newest_snapshot_mtime(snaps_dir: str) -> float | None:
    """The mtime of the newest ``twin_v*`` snapshot artifact = the last snapshot success, or None."""
    if not os.path.isdir(snaps_dir):
        return None
    best: float | None = None
    for n in os.listdir(snaps_dir):
        if not n.startswith("twin_v") or n.startswith("."):
            continue
        m = os.path.getmtime(os.path.join(snaps_dir, n))
        if best is None or m > best:
            best = m
    return best


def _newest_tree_mtime(root: str) -> float | None:
    """The mtime of the newest file anywhere under ``root`` = the last time the replica was written
    (replicate mirrors a tree), or None if the replica does not exist / is empty."""
    if not os.path.isdir(root):
        return None
    best: float | None = None
    for dirpath, _dirs, files in os.walk(root):
        for f in files:
            m = os.path.getmtime(os.path.join(dirpath, f))
            if best is None or m > best:
                best = m
    return best


def _job_status(last_success_ts: float | None, rpo_s: float, now_s: float) -> dict:
    """One monitored job's signal: presence, last-success time, age, and whether it is inside the RPO.
    An absent artifact is present=False + within_rpo=False (a never-run backup is a governance gap)."""
    if last_success_ts is None:
        return {"present": False, "last_success_ts": None, "age_s": None,
                "rpo_s": rpo_s, "within_rpo": False}
    age = max(0.0, now_s - last_success_ts)
    return {"present": True, "last_success_ts": round(last_success_ts, 3), "age_s": round(age, 3),
            "rpo_s": rpo_s, "within_rpo": age <= rpo_s}


def backup_status(now_s: float | None = None) -> dict:
    """The monitored last-success/age signal for the backup/replication jobs, against the declared
    policy. ``degraded`` is True iff ANY monitored job is absent or overdue (age > its RPO). ``now_s``
    is injectable for determinism; it defaults to wall-clock."""
    now = time.time() if now_s is None else float(now_s)
    policy = default_policy()
    data = CFG.data_dir()
    snap_ts = _newest_snapshot_mtime(os.path.join(data, "snapshots"))
    rep_ts = _newest_tree_mtime(_replica_dir())
    jobs = {
        "snapshot": _job_status(snap_ts, policy.snapshot_rpo_s, now),
        "replica": _job_status(rep_ts, policy.replica_rpo_s, now),
    }
    degraded = any(not j["within_rpo"] for j in jobs.values())
    return {"policy": asdict(policy), "jobs": jobs, "degraded": degraded,
            "checked_at": round(now, 3)}


def recent_ops_events(n: int = 20) -> list[dict]:
    """The newest-first tail of the OPS maintenance-action audit trail (twin/backup/gates), read from the
    same durable ``events.jsonl`` ledger the account-admin ``/events`` view uses, but filtered to the ops
    actions. Account-admin (``admin.operator.*``) actions are excluded -- governance BEYOND account admin.
    The whole ledger is scanned so sparse ops actions in a busy log are not lost in the unfiltered tail."""
    cap = max(1, min(int(n), 500))
    path = os.path.join(CFG.data_dir(), "events.jsonl")
    out: list[dict] = []
    if not os.path.exists(path):
        return out
    lines = open(path).read().splitlines()
    for ln in reversed(lines):                                # newest-first
        try:
            ev = _json.loads(ln)
        except ValueError:
            continue
        if str(ev.get("action", "")).startswith(OPS_ACTION_PREFIXES):
            out.append(ev)
            if len(out) >= cap:
                break
    return out


__all__ = ["RetentionPolicy", "OPS_ACTION_PREFIXES", "default_policy", "backup_status",
           "recent_ops_events"]
