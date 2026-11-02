//! Request metrics and the FS-10 budgets (RW-55b18; Python `services.record_request`, `record_latency`,
//! `record_resource`, `latency_snapshot`, `resource_budget_snapshot`): every response counted by status and matched
//! route template, each route's recent latencies against its engineering budget, and the declared resource budgets
//! fed by real measurements (process memory and CPU, response bytes, work-area tile bytes); the GPU and
//! model-inference classes have no live source on this host and stay declared.

use std::collections::{BTreeMap, HashMap, VecDeque};
use std::sync::Mutex;

use serde_json::{Map, Value, json};

/// The recent samples each route and resource class keeps.
const WINDOW: usize = 256;
const DEFAULT_BUDGET_MS: f64 = 1000.0;

/// Per-route latency budgets [ms]: targets grounded in each route's nature, not measurements.
const LATENCY_BUDGETS_MS: [(&str, f64); 11] = [
    ("/plan", 30000.0),
    ("/session/{sid}/scorecard", 30000.0),
    ("/figure/{key}", 8000.0),
    ("/layers", 3000.0),
    ("/world", 1500.0),
    ("/structure", 1500.0),
    ("/contracts/schema", 300.0),
    ("/ephemeris", 200.0),
    ("/sense", 200.0),
    ("/healthz", 100.0),
    ("/metrics", 100.0),
];

/// The declared resource budgets: class, the subsystem it governs, budget, unit, where its measurement comes from.
const RESOURCE_BUDGETS: [(&str, &str, f64, &str, &str); 6] = [
    (
        "memory",
        "navigation_estimation",
        2048.0,
        "MB",
        "process RSS (resource.getrusage)",
    ),
    (
        "cpu",
        "fleet_solve",
        60.0,
        "cpu_seconds",
        "process CPU time (resource.getrusage)",
    ),
    (
        "gpu",
        "map_render",
        33.0,
        "ms_per_frame",
        "gated: needs a GPU render host (no live source here)",
    ),
    (
        "bandwidth",
        "cockpit_mobile",
        512.0,
        "KB_per_response",
        "HTTP response bytes (server middleware)",
    ),
    (
        "tile_cache",
        "map_render",
        4096.0,
        "KB_per_tile",
        "rendered work-area tile PNG byte size (/dem/workarea.png)",
    ),
    (
        "model_inference",
        "plan",
        50.0,
        "ms",
        "gated: no learned model deployed (ML-01/FS-12)",
    ),
];

/// A route's latency budget [ms].
#[must_use]
pub fn budget_for(route: &str) -> f64 {
    LATENCY_BUDGETS_MS
        .iter()
        .find(|(r, _)| *r == route)
        .map_or(DEFAULT_BUDGET_MS, |(_, b)| *b)
}

#[derive(Debug, Default)]
struct Inner {
    total: u64,
    by_status: BTreeMap<String, u64>,
    by_route: BTreeMap<String, u64>,
    latency: HashMap<String, VecDeque<f64>>,
    resources: HashMap<&'static str, VecDeque<f64>>,
}

/// The counters, under one lock so a snapshot is consistent.
#[derive(Debug, Default)]
pub struct Metrics {
    inner: Mutex<Inner>,
}

fn push(buf: &mut VecDeque<f64>, v: f64) {
    if buf.len() == WINDOW {
        buf.pop_front();
    }
    buf.push_back(v);
}

/// Python `_pct`: the sorted sample at `int(q * n)`.
#[allow(
    clippy::cast_precision_loss,
    clippy::cast_possible_truncation,
    clippy::cast_sign_loss
)] // sample indices
fn pct(sorted: &[f64], q: f64) -> f64 {
    sorted
        .get(((q * sorted.len() as f64) as usize).min(sorted.len().saturating_sub(1)))
        .copied()
        .unwrap_or(0.0)
}

impl Metrics {
    fn lock(&self) -> std::sync::MutexGuard<'_, Inner> {
        self.inner
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
    }

    /// One response: its status, matched route template, latency [ms] and body size [bytes] when known.
    pub fn record(&self, status: u16, route: &str, ms: f64, bytes: Option<u64>) {
        let mut m = self.lock();
        m.total += 1;
        *m.by_status.entry(status.to_string()).or_default() += 1;
        *m.by_route.entry(route.to_owned()).or_default() += 1;
        push(m.latency.entry(route.to_owned()).or_default(), ms);
        drop(m);
        if let Some(b) = bytes.filter(|b| *b > 0) {
            #[allow(clippy::cast_precision_loss)] // a response size
            self.resource("bandwidth", b as f64 / 1024.0);
        }
    }

    /// One real measurement of a declared resource class (an undeclared class is ignored).
    pub fn resource(&self, class: &str, value: f64) {
        if let Some((name, ..)) = RESOURCE_BUDGETS.iter().find(|(c, ..)| *c == class) {
            push(self.lock().resources.entry(name).or_default(), value);
        }
    }

    /// The process's peak resident memory [MB] and CPU time [s] (Python `sample_process_resources`), from
    /// `/proc/self` (`VmHWM`, the peak RSS `getrusage` reports, and `utime + stime` in the fixed 100 Hz `USER_HZ`
    /// ticks); none off Linux, as the Python's off POSIX.
    pub fn sample_process(&self) {
        let peak_kb = std::fs::read_to_string("/proc/self/status")
            .ok()
            .and_then(|s| {
                s.lines()
                    .find_map(|l| l.strip_prefix("VmHWM:"))
                    .and_then(|v| v.trim().trim_end_matches("kB").trim().parse::<f64>().ok())
            });
        // utime and stime are the 14th and 15th fields, counted after the parenthesised command name
        let ticks = std::fs::read_to_string("/proc/self/stat")
            .ok()
            .and_then(|s| {
                let rest = s.rsplit_once(')')?.1;
                let f: Vec<&str> = rest.split_whitespace().collect();
                Some(f.get(11)?.parse::<f64>().ok()? + f.get(12)?.parse::<f64>().ok()?)
            });
        if let Some(kb) = peak_kb {
            self.resource("memory", kb / 1024.0);
        }
        if let Some(t) = ticks {
            self.resource("cpu", t / 100.0);
        }
    }

    /// The `/metrics` body after its uptime: the counters, the per-route latency summary, the resource budgets.
    #[must_use]
    pub fn snapshot(&self) -> Map<String, Value> {
        let m = self.lock();
        let r = stewie_twin::numpy::round;
        let latency: Map<String, Value> = m
            .latency
            .iter()
            .filter(|(_, v)| !v.is_empty())
            .map(|(route, v)| {
                let mut s: Vec<f64> = v.iter().copied().collect();
                s.sort_by(f64::total_cmp);
                let (b, p95) = (budget_for(route), pct(&s, 0.95));
                let row = json!({"count": s.len(), "p50": r(pct(&s, 0.5), 1), "p95": r(p95, 1),
                                 "max": r(s[s.len() - 1], 1), "budget_ms": b, "over_budget": p95 > b});
                (route.clone(), row)
            })
            .collect();
        let budgets: Map<String, Value> = RESOURCE_BUDGETS
            .iter()
            .map(|&(class, subsystem, budget, unit, live_source)| {
                let mut s: Vec<f64> = m
                    .resources
                    .get(class)
                    .map(|v| v.iter().copied().collect())
                    .unwrap_or_default();
                s.sort_by(f64::total_cmp);
                let mut row = json!({"subsystem": subsystem, "budget": budget, "unit": unit,
                                     "live_source": live_source, "count": s.len()});
                if let Some(&max) = s.last() {
                    let p95 = pct(&s, 0.95);
                    row["p95"] = json!(r(p95, 1));
                    row["max"] = json!(r(max, 1));
                    row["over_budget"] = json!(p95 > budget);
                } else {
                    row["p95"] = Value::Null;
                    row["max"] = Value::Null;
                    row["over_budget"] = json!(false);
                }
                (class.to_owned(), row)
            })
            .collect();
        let mut out = Map::new();
        out.insert("requests_total".into(), json!(m.total));
        out.insert("by_status".into(), json!(m.by_status));
        out.insert("by_route".into(), json!(m.by_route));
        out.insert("latency".into(), Value::Object(latency));
        out.insert("budgets".into(), Value::Object(budgets));
        out
    }
}
