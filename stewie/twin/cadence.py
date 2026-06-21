"""W-2 cadence (PRD 6.2): scheduled-snapshot TRIGGERS + a TIME-based retention ladder.

The W-2 row of PRD 6.2 asks for "scheduled snapshots (per sol + per N events) with a retention
ladder (hourly->daily->weekly)". ``backup.py`` already writes restorable snapshots and prunes them
by a VERSION-based ladder (keep recent N + every ladder-th version). This module adds the two pieces
that row names but ``backup.py`` does not provide:

  1. ``SnapshotScheduler`` -- WHEN to snapshot: a per-sol elapsed trigger OR a per-N-events trigger,
     measured against the last snapshot. PURE: the mission timestamp + event count are passed in
     (no wall-clock call inside the logic, mirroring the twin/envelope determinism discipline).
  2. ``snapshot_at`` / ``snapshot_time`` -- stamp each snapshot with its mission time on disk (an
     extra ``mission_t_s`` array in the same npz ``backup.snapshot`` writes, so ``backup.restore``
     stays byte-compatible) so the ladder can read it back instead of consulting a clock.
  3. ``select_retained`` / ``apply_time_retention`` -- the TIME-based hourly->daily->weekly ladder.
     ``select_retained`` is a pure function of (snapshot times, ``now_t_s``); ``apply_time_retention``
     deletes the non-retained files. Bucketing: keep one snapshot per HOUR for the most recent
     ``keep_hourly`` hours, then one per DAY for the next ``keep_daily`` days, then one per WEEK for
     the next ``keep_weekly`` weeks; within a bucket the NEWEST snapshot survives.

This complements ``backup.apply_retention`` (version cadence): a deployment can run either or both.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

import numpy as np

from stewie.twin import backup as _backup
from stewie.twin.versioned import TwinStore

# one lunar synodic day in seconds (the default "sol" cadence unit; overridable per body)
SOL_SECONDS = 86400.0 * 29.53


# ---- (1) WHEN to snapshot ------------------------------------------------------------------------
@dataclass(frozen=True)
class SnapshotScheduler:
    """Decide whether a snapshot is DUE, deterministically. A snapshot fires when EITHER trigger
    trips relative to the last snapshot: a full sol of mission time has elapsed, OR ``every_n_events``
    twin events have accrued. All inputs are passed in -- the scheduler never reads a clock."""
    sol_seconds: float = SOL_SECONDS
    every_n_events: int = 50

    def due(self, *, mission_t_s: float, n_events: int, last_snap_t_s: float,
            last_snap_events: int) -> bool:
        """True iff a snapshot should be taken now. ``mission_t_s`` / ``n_events`` are the current
        mission time + total twin event count; ``last_snap_t_s`` / ``last_snap_events`` are those
        values at the previous snapshot (0 / 0 if none yet)."""
        if self.sol_seconds <= 0 or self.every_n_events <= 0:
            raise ValueError("sol_seconds and every_n_events must be positive")
        elapsed = float(mission_t_s) - float(last_snap_t_s)
        events_since = int(n_events) - int(last_snap_events)
        return elapsed >= self.sol_seconds or events_since >= self.every_n_events


# ---- (2) timestamped snapshots -------------------------------------------------------------------
def snapshot_at(tw: TwinStore, snaps_dir: str, *, mission_t_s: float) -> str:
    """Write a restorable snapshot (via ``backup.snapshot``) and stamp it with ``mission_t_s`` so the
    time ladder can read the mission time back off disk. The stamp is an extra ``mission_t_s`` array
    appended to the same npz ``backup.snapshot`` produced -- ``backup.restore`` ignores it, so the
    snapshot stays byte-compatible with the version ladder + every existing restore path."""
    path = _backup.snapshot(tw, snaps_dir)
    z = dict(np.load(path))
    z["mission_t_s"] = np.array([float(mission_t_s)], dtype=np.float64)
    # rewrite atomically (dot-temp + os.replace), mirroring backup.snapshot's crash-safety
    tmp = os.path.join(os.path.dirname(path), f".{os.path.basename(path)}.tmp")
    try:
        with open(tmp, "wb") as fh:
            np.savez_compressed(fh, **z)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    return path


def snapshot_time(path: str) -> float:
    """Read a snapshot's stamped mission time (written by ``snapshot_at``)."""
    z = np.load(path)
    if "mission_t_s" not in z.files:
        raise ValueError(f"{path} has no mission_t_s stamp (not written by snapshot_at)")
    return float(z["mission_t_s"][0])


# ---- (3) the TIME-based hourly->daily->weekly retention ladder -----------------------------------
def select_retained(times: dict[str, float], *, now_t_s: float, keep_hourly: int, keep_daily: int,
                    keep_weekly: int, hour_s: float = 3600.0, day_s: float = 86400.0,
                    week_s: float = 7.0 * 86400.0) -> set[str]:
    """The keep-set: a PURE function of (snapshot name -> mission time) and ``now_t_s``.

    Tiered by age = ``now_t_s - t``:
      * age < ``keep_hourly`` hours  -> one survivor per HOUR bucket,
      * else age < ``keep_hourly`` h + ``keep_daily`` days -> one per DAY bucket,
      * else age < that + ``keep_weekly`` weeks -> one per WEEK bucket,
      * older than the weekly window -> pruned.
    Within any bucket the NEWEST (largest t) snapshot survives. Ties on t keep the lexicographically
    smallest name so the choice is fully determined."""
    if not times:
        return set()
    hourly_horizon = keep_hourly * hour_s
    daily_horizon = hourly_horizon + keep_daily * day_s
    weekly_horizon = daily_horizon + keep_weekly * week_s

    # bucket key: (tier_rank, bucket_index). tier_rank orders hourly<daily<weekly so a name can't
    # land in two tiers; bucket_index is the integer bucket within that tier (by age).
    buckets: dict[tuple[int, int], tuple[float, str]] = {}
    for name, t in times.items():
        age = now_t_s - t
        if age < 0:
            age = 0.0                                     # a future-stamped snapshot counts as newest
        if age < hourly_horizon:
            key = (0, int(age // hour_s))
        elif age < daily_horizon:
            key = (1, int((age - hourly_horizon) // day_s))
        elif age < weekly_horizon:
            key = (2, int((age - daily_horizon) // week_s))
        else:
            continue                                       # beyond the ladder -> prune
        cur = buckets.get(key)
        # newest wins; on an exact t tie, the lexicographically smaller name wins (determinism)
        if cur is None or t > cur[0] or (t == cur[0] and name < cur[1]):
            buckets[key] = (t, name)
    return {name for _, name in buckets.values()}


def apply_time_retention(snaps_dir: str, *, now_t_s: float, keep_hourly: int = 24,
                         keep_daily: int = 7, keep_weekly: int = 4, hour_s: float = 3600.0,
                         day_s: float = 86400.0, week_s: float = 7.0 * 86400.0) -> list[str]:
    """Prune ``snaps_dir`` to the time-ladder keep-set (``select_retained``) and return the kept
    filenames. Only ``twin_v*`` snapshots stamped by ``snapshot_at`` participate; an unstamped
    ``twin_v`` file (e.g. a bare ``backup.snapshot``) is left untouched (never silently deleted)."""
    names = [n for n in os.listdir(snaps_dir) if n.startswith("twin_v") and not n.startswith(".")]
    stamped: dict[str, float] = {}
    unstamped: list[str] = []
    for n in names:
        try:
            stamped[n] = snapshot_time(os.path.join(snaps_dir, n))
        except ValueError:
            unstamped.append(n)
    keep = select_retained(stamped, now_t_s=now_t_s, keep_hourly=keep_hourly, keep_daily=keep_daily,
                           keep_weekly=keep_weekly, hour_s=hour_s, day_s=day_s, week_s=week_s)
    for n in stamped:
        if n not in keep:
            os.unlink(os.path.join(snaps_dir, n))
    return sorted(keep) + sorted(unstamped)


__all__ = ["SnapshotScheduler", "snapshot_at", "snapshot_time", "select_retained",
           "apply_time_retention", "SOL_SECONDS"]
