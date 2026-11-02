//! The remote-control contract (RW-55c; Python `stewie.bridge.rc_contract`, `command_eligibility` and
//! `autonomy_contract.teleop_authority`): the command set (`GoTo` / Safe / `SetSim`), the kinematic sim backend that
//! executes a `GoTo` and emits Pose and Leg telemetry, the SF-01 safing watchdog (the dead-man switch that safes the
//! backend when commands stop), the AS-12 command-eligibility interlock and the SF-02 teleop authority.

use serde_json::{Value, json};

use crate::operators::role_rank;

/// `Safe.reason`: the operator asked.
pub const SAFE_REASON_OPERATOR: i64 = 0;
/// `Safe.reason`: the SF-01 command-timeout trip.
pub const SAFE_REASON_WATCHDOG: i64 = 1;

/// A drive-to-waypoint command, in grid cells.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct GoTo {
    pub leg_id: i64,
    pub goal_row: f64,
    pub goal_col: f64,
    pub v_max_mps: f64,
    pub goal_radius_cells: f64,
}

/// A command to the rover.
#[derive(Debug, Clone, Copy, PartialEq)]
pub enum Command {
    GoTo(GoTo),
    /// All-stop, with its reason code.
    Safe(i64),
    /// The sim's time-acceleration factor (a director-only training toggle).
    SetSim(f64),
}

/// The kinematic sim backend (Python `SimBackend`): a `GoTo` steps a unicycle toward the goal, one `dt_s` per poll,
/// never overshooting; Safe halts it; `SetSim` scales the step. The route never sets a terminal heading, so the
/// Python's turn-in-place branch has no caller here.
#[derive(Debug, Clone)]
pub struct SimBackend {
    row: f64,
    col: f64,
    yaw: f64,
    pub cell_m: f64,
    dt_s: f64,
    time_factor: f64,
    goal: Option<GoTo>,
    leg_id: i64,
    out: Vec<Value>,
    safed: bool,
}

impl Default for SimBackend {
    /// At the grid origin, 1 m cells, 1 s per step.
    fn default() -> Self {
        Self {
            row: 0.0,
            col: 0.0,
            yaw: 0.0,
            cell_m: 1.0,
            dt_s: 1.0,
            time_factor: 1.0,
            goal: None,
            leg_id: 0,
            out: Vec::new(),
            safed: false,
        }
    }
}

impl SimBackend {
    pub fn submit(&mut self, cmd: Command) {
        match cmd {
            Command::GoTo(g) => {
                self.goal = Some(g);
                self.leg_id = g.leg_id;
                self.safed = false;
            }
            Command::Safe(_) => {
                self.goal = None;
                self.safed = true;
            }
            Command::SetSim(f) => self.time_factor = f.max(1e-6),
        }
    }

    /// Step toward the goal (when one is held and the rover is not safed), then drain the telemetry.
    pub fn poll(&mut self) -> Vec<Value> {
        if !self.safed {
            self.step();
        }
        std::mem::take(&mut self.out)
    }

    fn step(&mut self) {
        let Some(g) = self.goal else {
            return;
        };
        let (drow, dcol) = (g.goal_row - self.row, g.goal_col - self.col);
        let dist = drow.hypot(dcol);
        if dist <= g.goal_radius_cells {
            self.out.push(json!({"leg_id": self.leg_id, "status": 0, "commanded_dist_m": 0.0,
                                 "achieved_dist_m": 0.0, "energy_J": 0.0, "mass_kg": 0.0, "final_row": self.row,
                                 "final_col": self.col, "kind": "leg"}));
            self.goal = None;
            return;
        }
        let step = ((g.v_max_mps * self.dt_s * self.time_factor) / self.cell_m).min(dist);
        self.row += step * drow / dist;
        self.col += step * dcol / dist;
        self.yaw = drow.atan2(dcol);
        self.out.push(json!({"leg_id": self.leg_id, "row": self.row, "col": self.col, "yaw_rad": self.yaw,
                             "v_achieved_mps": g.v_max_mps * self.time_factor, "slip": 0.0, "sinkage_m": 0.0,
                             "slope_rad": 0.0, "soc": 1.0, "entrapped": false, "kind": "pose"}));
    }
}

/// SF-01: a motion command while the watchdog is tripped.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WatchdogTripped;

impl std::fmt::Display for WatchdogTripped {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(
            "SF-01 watchdog is tripped (safed after a command-timeout/comms dropout); an explicit operator re-arm \
             is required before motion commands are accepted",
        )
    }
}

/// SF-01 (Python `SafingWatchdog`): every command feeds it; a tick past `deadline_s` since the last feed safes the
/// backend once and latches `tripped`, which only a deliberate re-arm clears.
#[derive(Debug, Clone)]
pub struct SafingWatchdog {
    pub backend: SimBackend,
    pub deadline_s: f64,
    last_feed: Option<f64>,
    pub tripped: bool,
}

impl SafingWatchdog {
    #[must_use]
    pub fn new(backend: SimBackend, deadline_s: f64) -> Self {
        Self {
            backend,
            deadline_s,
            last_feed: None,
            tripped: false,
        }
    }

    /// The operator's re-arm: the only way motion resumes after a safe-stop.
    pub fn rearm(&mut self, now: f64) {
        self.last_feed = Some(now);
        self.tripped = false;
    }

    /// Seconds since the last feed; 0 before the first.
    #[must_use]
    pub fn seconds_idle(&self, now: f64) -> f64 {
        self.last_feed.map_or(0.0, |t| (now - t).max(0.0))
    }

    /// Forward `cmd` and feed the timer.
    ///
    /// # Errors
    /// A motion command while tripped (a Safe is always accepted, without re-arming).
    pub fn submit(&mut self, cmd: Command, now: f64) -> Result<(), WatchdogTripped> {
        if self.tripped && !matches!(cmd, Command::Safe(_)) {
            return Err(WatchdogTripped);
        }
        self.backend.submit(cmd);
        self.last_feed = Some(now);
        Ok(())
    }

    /// Advance the clock: true when tripped, safing the backend on the transition.
    pub fn tick(&mut self, now: f64) -> bool {
        if !self.tripped && self.last_feed.is_some_and(|t| now - t > self.deadline_s) {
            self.backend.submit(Command::Safe(SAFE_REASON_WATCHDOG));
            self.tripped = true;
        }
        self.tripped
    }
}

/// The context a command is judged in (Python `CommandContext`).
#[derive(Debug, Clone, Copy)]
pub struct CommandContext<'a> {
    pub role: Option<&'a str>,
    pub mission_namespace: Option<&'a str>,
    pub target_namespace: Option<&'a str>,
    pub safed: bool,
    pub ack_age_s: f64,
    pub ack_deadline_s: f64,
}

/// AS-12: eligible only when every gate passes, else the first failing gate's reason. Only the `live` namespace's
/// mode grants `command_real_robot` (EG-02).
#[must_use]
pub fn command_eligible(ctx: &CommandContext<'_>) -> (bool, &'static str) {
    if role_rank(ctx.role) < role_rank(Some("operator")) {
        return (false, "unauthorized_role");
    }
    if ctx.mission_namespace != Some("live") {
        return (false, "unauthorized_sandbox");
    }
    if ctx.safed {
        return (false, "unsafe_safed");
    }
    // a NaN age is stale too
    if ctx
        .ack_age_s
        .partial_cmp(&ctx.ack_deadline_s)
        .is_none_or(std::cmp::Ordering::is_gt)
    {
        return (false, "stale_link");
    }
    if ctx.target_namespace != ctx.mission_namespace {
        return (false, "namespace_conflict");
    }
    (true, "eligible")
}

/// FS-28: every gate's own verdict beside the overall one (Python `eligibility_report`).
#[must_use]
pub fn eligibility_report(ctx: &CommandContext<'_>) -> Value {
    let (ok, reason) = command_eligible(ctx);
    json!({"eligible": ok, "reason": reason, "authorized": role_rank(ctx.role) >= role_rank(Some("operator")),
           "live": ctx.mission_namespace == Some("live"), "safe": !ctx.safed,
           "fresh": ctx.ack_age_s <= ctx.ack_deadline_s, "namespaced": ctx.target_namespace == ctx.mission_namespace})
}

/// SF-02: mission-less teleop is allowed only on a dev, bench or test runnable profile with the explicit grant.
#[must_use]
pub fn teleop_authority(profile: &str, grant: bool) -> (bool, &'static str) {
    if !matches!(
        profile.trim().to_lowercase().as_str(),
        "dev" | "bench" | "test"
    ) {
        return (false, "live_profile_teleop_refused");
    }
    if !grant {
        return (false, "teleop_not_granted");
    }
    (true, "teleop_granted")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_eligibility_gates_fail_in_order() {
        let ctx = CommandContext {
            role: Some("operator"),
            mission_namespace: Some("live"),
            target_namespace: Some("live"),
            safed: false,
            ack_age_s: 1.0,
            ack_deadline_s: 2.0,
        };
        assert_eq!(command_eligible(&ctx), (true, "eligible"));
        let with = |f: &dyn Fn(&mut CommandContext<'static>)| {
            let mut c = ctx;
            f(&mut c);
            command_eligible(&c).1
        };
        assert_eq!(with(&|c| c.role = Some("guest")), "unauthorized_role");
        assert_eq!(with(&|c| c.role = None), "unauthorized_role");
        assert_eq!(
            with(&|c| c.mission_namespace = Some("sandbox")),
            "unauthorized_sandbox"
        );
        assert_eq!(
            with(&|c| c.mission_namespace = None),
            "unauthorized_sandbox"
        );
        assert_eq!(with(&|c| c.safed = true), "unsafe_safed");
        assert_eq!(with(&|c| c.ack_age_s = 2.5), "stale_link");
        assert_eq!(with(&|c| c.ack_age_s = f64::NAN), "stale_link");
        assert_eq!(
            with(&|c| c.target_namespace = Some("sandbox")),
            "namespace_conflict"
        );
        assert_eq!(teleop_authority(" Bench ", true), (true, "teleop_granted"));
        assert_eq!(
            teleop_authority("dev", false),
            (false, "teleop_not_granted")
        );
        assert_eq!(
            teleop_authority("live", true),
            (false, "live_profile_teleop_refused")
        );
    }
}
