//! Snapshot cadence (Python `stewie.twin.cadence`, W-2): when to snapshot (a full sol of mission time elapsed,
//! or N events accrued, since the last one), snapshots stamped with their mission time, and the time retention
//! ladder (one per hour, then per day, then per week; the newest in each bucket survives). Every input is
//! passed in: nothing here reads a clock, and the sol length is the mission's (it is not in the body registry).

use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::path::{Path, PathBuf};

use crate::TwinError;
use crate::backup::{snapshot_arrays, snapshot_paths, snapshot_version, write_arrays};
use crate::numpy::{self, Array};
use crate::twin_store::TwinStore;

fn bad(m: impl Into<String>) -> TwinError {
    TwinError::Invalid(m.into())
}

/// When a snapshot is due.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Scheduler {
    pub sol_seconds: f64,
    pub every_n_events: u64,
}

impl Scheduler {
    /// True when a full sol has elapsed or `every_n_events` events have accrued since the last snapshot.
    ///
    /// # Errors
    /// A non-positive sol or event count.
    pub fn due(
        &self,
        mission_t_s: f64,
        n_events: u64,
        last_snap_t_s: f64,
        last_snap_events: u64,
    ) -> Result<bool, TwinError> {
        if self.sol_seconds.is_nan() || self.sol_seconds <= 0.0 || self.every_n_events == 0 {
            return Err(bad("sol_seconds and every_n_events must be positive"));
        }
        Ok(mission_t_s - last_snap_t_s >= self.sol_seconds
            || n_events.saturating_sub(last_snap_events) >= self.every_n_events)
    }
}

/// A snapshot of `tw` in `dir` stamped with `mission_t_s` (an extra `mission_t_s` array the restore ignores).
///
/// # Errors
/// An I/O failure.
pub fn snapshot_at(tw: &TwinStore, dir: &Path, mission_t_s: f64) -> Result<PathBuf, TwinError> {
    let (path, tmp) = snapshot_paths(dir, tw.version());
    let mut arrays = snapshot_arrays(tw)?;
    arrays.push((
        "mission_t_s",
        Array::F64 {
            shape: vec![1],
            data: vec![mission_t_s],
        },
    ));
    write_arrays(&path, &tmp, &arrays)?;
    Ok(path)
}

/// A snapshot's stamped mission time, or `None` for an unstamped snapshot.
///
/// # Errors
/// An unreadable or malformed file.
pub fn snapshot_time(path: &Path) -> Result<Option<f64>, TwinError> {
    let a = numpy::read_npz(fs::File::open(path).map_err(TwinError::Io)?)?;
    Ok(match a.get("mission_t_s") {
        Some(Array::F64 { data, .. }) => data.first().copied(),
        _ => None,
    })
}

/// The time ladder's widths [s].
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Ladder {
    pub keep_hourly: u32,
    pub keep_daily: u32,
    pub keep_weekly: u32,
    pub hour_s: f64,
    pub day_s: f64,
    pub week_s: f64,
}

/// The names to keep from `times` (name to mission time) at `now_t_s`: by age, one per hour for
/// `keep_hourly` hours, then one per day for `keep_daily` days, then one per week for `keep_weekly` weeks;
/// older ones go. In a bucket the newest survives, and on an exact tie the smaller name. A future time counts
/// as age 0.
#[must_use]
#[allow(clippy::cast_possible_truncation)] // a bucket index
pub fn select_retained(
    times: &BTreeMap<String, f64>,
    now_t_s: f64,
    l: &Ladder,
) -> BTreeSet<String> {
    let hourly = f64::from(l.keep_hourly) * l.hour_s;
    let daily = hourly + f64::from(l.keep_daily) * l.day_s;
    let weekly = daily + f64::from(l.keep_weekly) * l.week_s;
    let mut buckets: BTreeMap<(u8, i64), (f64, &str)> = BTreeMap::new();
    for (name, &t) in times {
        let age = (now_t_s - t).max(0.0);
        let key = if age < hourly {
            (0, (age / l.hour_s).floor() as i64)
        } else if age < daily {
            (1, ((age - hourly) / l.day_s).floor() as i64)
        } else if age < weekly {
            (2, ((age - daily) / l.week_s).floor() as i64)
        } else {
            continue;
        };
        // newest wins; on an exact tie of times the smaller name wins (the Python's determinism rule)
        let newer = |cur: &(f64, &str)| {
            t.total_cmp(&cur.0)
                .then_with(|| cur.1.cmp(name.as_str()))
                .is_gt()
        };
        if buckets.get(&key).is_none_or(newer) {
            buckets.insert(key, (t, name));
        }
    }
    buckets.values().map(|(_, n)| (*n).to_owned()).collect()
}

/// Prune `dir` to [`select_retained`] over its stamped `twin_v*` snapshots; an unstamped snapshot is never
/// deleted. Returns the kept stamped names (sorted) followed by the unstamped ones (sorted).
///
/// # Errors
/// An I/O failure or a malformed snapshot.
pub fn apply_time_retention(
    dir: &Path,
    now_t_s: f64,
    l: &Ladder,
) -> Result<Vec<String>, TwinError> {
    let mut stamped = BTreeMap::new();
    let mut unstamped = Vec::new();
    for e in fs::read_dir(dir).map_err(TwinError::Io)? {
        let name = e
            .map_err(TwinError::Io)?
            .file_name()
            .to_string_lossy()
            .into_owned();
        if snapshot_version(&name).is_none() {
            continue;
        }
        match snapshot_time(&dir.join(&name))? {
            Some(t) => {
                stamped.insert(name, t);
            }
            None => unstamped.push(name),
        }
    }
    let keep = select_retained(&stamped, now_t_s, l);
    for name in stamped.keys().filter(|n| !keep.contains(*n)) {
        fs::remove_file(dir.join(name)).map_err(TwinError::Io)?;
    }
    unstamped.sort();
    Ok(keep.into_iter().chain(unstamped).collect())
}
