//! The serialized viz2 session actor (Python `Viz2Runtime`): one conserved, windowed terrain session whose single
//! actor iteration drains the command mailbox, drives the deadman, steps the world on the latest twist, writes the
//! generation's patch manifest and publishes its telemetry frame. The transport (51e2) only enqueues commands and
//! drains frames; this core never reads a clock of its own, so a pinned clock steps it exactly.
//!
//! On real data every `dig` and `dump` is refused at ingest, as in the Python: the native cell (1 m or 5 m) does
//! not resolve the drum, and generated terrain is not permitted. The construction refuses a bundle that would
//! resolve it, because the excavation path is not ported (D-R185).

use std::collections::{BTreeMap, VecDeque};
use std::path::{Path, PathBuf};

use serde_json::{Map, Value, json};
use sha2::{Digest as _, Sha256};
use stewie_contracts::stream::{PROTOCOL_VERSION, StreamSession};
use stewie_physics::arm::{ARM_OFFSET_MAX_RAD, ARM_OFFSET_MIN_RAD, dig_engagement};
use stewie_physics::drum_sensor::{DrumSensor, ErrorBands};
use stewie_physics::worksite::{Setup, WorkSite};

/// A bucket drum the IPEx profile carries (the large one belongs to RASSOR).
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Drum {
    pub width_m: f64,
    /// The sourced hold of ONE drum [kg]; the vehicle carries two.
    pub capacity_kg: f64,
    pub scoop_height_m: f64,
}

/// The sourced and calibrated figures the runtime reports.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Calib {
    pub drum: Drum,
    /// The anti-bridging bite: a pass cuts at most this fraction of the scoop opening.
    pub max_cut_depth_frac: f64,
    /// The grounded electrical dig energy [J/kg].
    pub dig_energy_per_kg: f64,
    pub fdc_baseline_a: f64,
    pub fdc_slope_a_per_kg: f64,
    pub bands: ErrorBands,
}

/// The session options (the Python constructor's keywords and defaults).
#[derive(Debug, Clone, PartialEq)]
pub struct Options {
    pub model_id: Option<String>,
    pub body: String,
    pub tile_base_cells: usize,
    /// The operator's section [m]; `None` takes the flattest interior spot.
    pub start_xy: Option<(f64, f64)>,
    pub start_yaw: f64,
    pub rate_hz: f64,
    pub ack_deadline_s: f64,
    pub window: usize,
    pub keyframe_interval: u64,
    pub retain_generations: u64,
}

impl Default for Options {
    fn default() -> Self {
        Self {
            model_id: None,
            body: "moon".to_owned(),
            tile_base_cells: 4,
            start_xy: None,
            start_yaw: 0.0,
            rate_hz: 15.0,
            ack_deadline_s: 2.0,
            window: 64,
            keyframe_interval: 90,
            retain_generations: 256,
        }
    }
}

/// One queued command: the session epoch it arrived on, when it was received, and the message.
#[derive(Debug, Clone, PartialEq)]
struct Inbound {
    epoch: u64,
    received_at: f64,
    msg: Map<String, Value>,
}

/// The actor.
#[derive(Debug)]
pub struct Runtime {
    pub ws: WorkSite,
    pub start_xy: (f64, f64),
    pub dt: f64,
    pub session_dir: PathBuf,
    pub generations_dir: PathBuf,
    opts: Options,
    calib: Calib,
    sensor: DrumSensor,
    /// The body's surface gravity, which the IMU's specific force carries [m/s^2].
    gravity_ms2: f64,
    max_cut_per_pass_m: f64,
    window_shape: (usize, usize),
    inbound: VecDeque<Inbound>,
    outbound: VecDeque<(u64, Value)>,
    current_epoch: u64,
    epoch_counter: u64,
    session: Option<StreamSession>,
    outbound_open: bool,
    latest_twist: (f64, f64),
    last_twist_at: Option<f64>,
    simulation_t_s: f64,
    safe_stopped: bool,
    force_keyframe: bool,
    pub rejected_stale: u64,
    pub rejected_bounds: u64,
    arm_front_offset_rad: f64,
    arm_back_offset_rad: f64,
    dist_actual_m: f64,
    dist_wheel_m: f64,
    slope_sum_deg: f64,
    slope_n: u64,
    prev_v_achieved: f64,
    imu_gyro_z: f64,
    imu_accel_long: f64,
    imu_accel_lat: f64,
    generation: u64,
    last_acked_gen: u64,
    last_keyframe_gen: u64,
    pending: Vec<(u64, [usize; 4])>,
    seq_to_gen: BTreeMap<i64, u64>,
    latest_keyframe_dir: Option<PathBuf>,
}

/// Write `data` to `path` through a `.tmp` sibling and an atomic rename (Python `atomic_write_bytes`).
fn atomic_write(path: &Path, data: &[u8]) -> Result<(), String> {
    let mut tmp = path.as_os_str().to_owned();
    tmp.push(".tmp");
    std::fs::write(&tmp, data).map_err(|e| format!("{}: {e}", path.display()))?;
    std::fs::rename(&tmp, path).map_err(|e| format!("{}: {e}", path.display()))
}

/// Lower-case hex.
fn hex(bytes: &[u8]) -> String {
    use std::fmt::Write as _;
    bytes.iter().fold(String::new(), |mut out, b| {
        let _ = write!(out, "{b:02x}");
        out
    })
}

/// Python `isinstance(x, (int, float)) and math.isfinite(x)` on a JSON value (a bool is an int).
fn finite_number(v: &Value) -> Option<f64> {
    match v {
        Value::Number(n) => n.as_f64().filter(|x| x.is_finite()),
        Value::Bool(b) => Some(f64::from(u8::from(*b))),
        _ => None,
    }
}

/// Python `int(v)` on an ack's `seq` (a float truncated, numeric text read); `None` where it raises.
#[allow(clippy::cast_possible_truncation)] // Python's int() truncates
fn py_int(v: &Value) -> Option<i64> {
    match v {
        Value::Number(n) => n.as_i64().or_else(|| {
            n.as_f64()
                .filter(|x| x.is_finite())
                .map(|x| x.trunc() as i64)
        }),
        Value::Bool(b) => Some(i64::from(*b)),
        Value::String(s) => {
            let t = s.trim();
            let b = t.as_bytes();
            let grouped = b.iter().enumerate().all(|(i, c)| {
                *c != b'_'
                    || (i > 0
                        && i + 1 < b.len()
                        && b[i - 1].is_ascii_digit()
                        && b[i + 1].is_ascii_digit())
            });
            grouped
                .then(|| t.replace('_', ""))
                .and_then(|t| t.parse().ok())
        }
        _ => None,
    }
}

/// The bundle checks: native resolution only, a native cell that cannot resolve the drum (the excavation path is
/// not ported, D-R185), and a clast list (empty: the window-local rock field is not ported either).
fn check_bundle(bundle_dir: &Path, setup: &Setup, calib: &Calib) -> Result<(), String> {
    let meta: Value = serde_json::from_slice(
        &std::fs::read(bundle_dir.join("metadata.json"))
            .map_err(|e| format!("{}: {e}", bundle_dir.display()))?,
    )
    .map_err(|e| e.to_string())?;
    let native = meta["grid"]["cell_m"]
        .as_f64()
        .ok_or("bundle metadata has no grid cell_m")?;
    if setup.fine_cell_m.is_some_and(|f| (f - native).abs() > 0.0) {
        return Err(
            "runtime requires native DEM resolution; generated terrain is not permitted".to_owned(),
        );
    }
    if native <= calib.drum.width_m {
        return Err(format!(
            "the native {native} m cell resolves the {} m drum: the excavation path is not ported (D-R185)",
            calib.drum.width_m
        ));
    }
    let clasts = meta
        .get("clasts")
        .and_then(Value::as_array)
        .ok_or("bundle clasts must be a list")?;
    if !clasts.is_empty() {
        return Err(
            "bundle carries clasts: the window-local rock field is not ported (D-R185)".to_owned(),
        );
    }
    Ok(())
}

/// [REQ:AS-15] The flattest interior spot of the session's base, in world metres.
fn flattest_spawn_xy(ws: &WorkSite) -> (f64, f64) {
    let base = ws.base();
    let (r, c) = crate::spawn::flattest_interior_rc(
        &base.derive_height(),
        base.height(),
        base.width(),
        ws.base_cell_m(),
    );
    let w = ws.world();
    #[allow(clippy::cast_precision_loss)] // grid indices
    (
        w[0] + c as f64 * ws.base_cell_m(),
        w[1] + r as f64 * ws.base_cell_m(),
    )
}

impl Runtime {
    /// The session over a real bundle: the LIVE model resolved first (fail closed), then the clock, the native
    /// resolution, the excavation scope and the clasts checked, the conserved world built, the rover seated, and
    /// the session directory laid out.
    ///
    /// # Errors
    /// A refused model; a bad clock; a bundle that is unreadable, not at native resolution, fine enough to resolve
    /// the drum, or carrying clasts; a world the physics refuses; an unwritable session directory.
    pub fn new(
        bundle_dir: &Path,
        session_dir: &Path,
        opts: Options,
        setup: Setup,
        calib: Calib,
    ) -> Result<Self, String> {
        let (reg, _) = stewie_physics::soil::bundled();
        stewie_physics::model_control::resolve_live_backend(
            opts.model_id.as_deref(),
            Some(&opts.body),
            &reg,
        )?;
        let gravity_ms2 = reg
            .get(&opts.body)
            .map(|b| b.g)
            .ok_or("the body registry has no such body")?;
        if !opts.rate_hz.is_finite() || opts.rate_hz <= 0.0 {
            return Err("rate_hz must be finite and positive".to_owned());
        }
        if !opts.ack_deadline_s.is_finite() || opts.ack_deadline_s <= 0.0 {
            return Err("ack_deadline_s must be finite and positive".to_owned());
        }
        check_bundle(bundle_dir, &setup, &calib)?;
        let mut ws = WorkSite::from_bundle(
            bundle_dir,
            Setup {
                tile_base_cells: opts.tile_base_cells,
                fine_cell_m: None,
                ..setup
            },
        )
        .map_err(|e| e.to_string())?;
        let start_xy = opts.start_xy.unwrap_or_else(|| flattest_spawn_xy(&ws));
        ws.recenter(start_xy, 1).map_err(|e| e.to_string())?;
        ws.set_pose(Some(start_xy), opts.start_yaw)
            .map_err(|e| e.to_string())?;
        let generations_dir = session_dir.join("generations");
        std::fs::create_dir_all(&generations_dir)
            .map_err(|e| format!("{}: {e}", generations_dir.display()))?;
        atomic_write(&session_dir.join("clasts.json"), b"{\"clasts\": []}")?;
        let hold = 2.0 * calib.drum.capacity_kg;
        let fills: Vec<f64> = [0.0, 0.25, 0.5, 0.75, 1.0]
            .iter()
            .map(|f| f * hold)
            .collect();
        let sensor = DrumSensor::calibrated(
            &fills,
            calib.fdc_baseline_a,
            calib.fdc_slope_a_per_kg,
            hold,
            calib.bands,
        )?;
        let fine = ws.fine().ok_or("no window after the recenter")?;
        let window_shape = (fine.height(), fine.width());
        Ok(Self {
            start_xy,
            dt: 1.0 / opts.rate_hz,
            session_dir: session_dir.to_owned(),
            generations_dir,
            max_cut_per_pass_m: calib.max_cut_depth_frac * calib.drum.scoop_height_m,
            sensor,
            gravity_ms2,
            calib,
            window_shape,
            ws,
            opts,
            inbound: VecDeque::new(),
            outbound: VecDeque::new(),
            current_epoch: 0,
            epoch_counter: 0,
            session: None,
            outbound_open: false,
            latest_twist: (0.0, 0.0),
            last_twist_at: None,
            simulation_t_s: 0.0,
            safe_stopped: false,
            force_keyframe: false,
            rejected_stale: 0,
            rejected_bounds: 0,
            arm_front_offset_rad: 0.0,
            arm_back_offset_rad: 0.0,
            dist_actual_m: 0.0,
            dist_wheel_m: 0.0,
            slope_sum_deg: 0.0,
            slope_n: 0,
            prev_v_achieved: 0.0,
            imu_gyro_z: 0.0,
            imu_accel_long: 0.0,
            imu_accel_lat: 0.0,
            generation: 0,
            last_acked_gen: 0,
            last_keyframe_gen: 0,
            pending: Vec::new(),
            seq_to_gen: BTreeMap::new(),
            latest_keyframe_dir: None,
        })
    }

    /// The active window `(rows, cols)`.
    #[must_use]
    pub fn window_shape(&self) -> (usize, usize) {
        self.window_shape
    }

    #[must_use]
    pub fn generation(&self) -> u64 {
        self.generation
    }

    #[must_use]
    pub fn last_acked_gen(&self) -> u64 {
        self.last_acked_gen
    }

    #[must_use]
    pub fn current_epoch(&self) -> u64 {
        self.current_epoch
    }

    #[must_use]
    pub fn safe_stopped(&self) -> bool {
        self.safe_stopped
    }

    /// A fresh session (epoch) superseding any prior one: a new stream (a tripped one is never reset), the held
    /// safe-stop cleared, the twist zeroed, and a keyframe forced.
    ///
    /// # Errors
    /// A stream the options cannot build (a zero window or a non-positive ack deadline).
    pub fn register_session(&mut self) -> Result<u64, String> {
        self.epoch_counter += 1;
        self.session = Some(StreamSession::new(
            self.opts.window,
            self.opts.ack_deadline_s,
        )?);
        self.current_epoch = self.epoch_counter;
        self.outbound_open = true;
        self.latest_twist = (0.0, 0.0);
        self.last_twist_at = None;
        self.safe_stopped = false;
        self.force_keyframe = true;
        Ok(self.current_epoch)
    }

    /// Queue a command from session `epoch`, received at `received_at`; `false` when the mailbox is full.
    pub fn enqueue(&mut self, epoch: u64, received_at: f64, msg: Map<String, Value>) -> bool {
        if self.inbound.len() >= self.opts.window {
            return false;
        }
        self.inbound.push_back(Inbound {
            epoch,
            received_at,
            msg,
        });
        true
    }

    /// The frames published since the last call, each with the epoch whose connection carries it.
    pub fn take_outbound(&mut self) -> Vec<(u64, Value)> {
        self.outbound.drain(..).collect()
    }

    fn publish(&mut self, epoch: u64, frame: Value) {
        self.outbound.push_back((epoch, frame));
    }

    /// One actor iteration at `t0`; `false` when a deadman or command-expiry trip ended it.
    ///
    /// # Errors
    /// A world step or a manifest write that fails.
    pub fn actor_once(&mut self, t0: f64) -> Result<bool, String> {
        self.drain_inbound(t0);
        let force_kf = std::mem::take(&mut self.force_keyframe);
        let (v, omega) = if self.safe_stopped {
            (0.0, 0.0)
        } else {
            self.latest_twist
        };
        let epoch = self.current_epoch;
        let Some(sess) = self.session.as_mut() else {
            return Ok(true);
        };
        if sess.tick(t0) {
            self.trip(epoch, "deadman_link_stall");
            return Ok(false);
        }
        if (v != 0.0 || omega != 0.0)
            && self
                .last_twist_at
                .is_some_and(|at| t0 - at >= self.opts.ack_deadline_s)
        {
            self.trip(epoch, "command_expired");
            return Ok(false);
        }
        self.step_and_publish(epoch, t0, v, omega, force_kf)?;
        Ok(true)
    }

    /// The terminal safe-stop: hold the rover (twist zero), send the notice out of band, close the session.
    fn trip(&mut self, epoch: u64, reason: &str) {
        if epoch == self.current_epoch {
            self.safe_stopped = true;
            self.latest_twist = (0.0, 0.0);
        }
        self.publish(
            epoch,
            json!({"type": "safe_stop", "reason": reason, "epoch": epoch}),
        );
        if epoch == self.current_epoch {
            self.session = None;
            self.outbound_open = false;
        }
    }

    /// Apply the queued commands of the current epoch (at most a window's worth); a superseded epoch's or a
    /// too-old command (an ack excepted) is dropped and counted.
    fn drain_inbound(&mut self, now: f64) {
        for _ in 0..self.opts.window {
            let Some(Inbound {
                epoch,
                received_at,
                msg,
            }) = self.inbound.pop_front()
            else {
                return;
            };
            if epoch != self.current_epoch {
                self.rejected_stale += 1;
                continue;
            }
            let cmd = msg.get("cmd").map_or_else(String::new, |c| match c {
                Value::String(s) => s.clone(),
                other => stewie_twin::pyjson::repr(other),
            });
            if cmd != "ack" && now - received_at >= self.opts.ack_deadline_s {
                self.rejected_stale += 1;
                continue;
            }
            match cmd.as_str() {
                "twist" => self.ingest_twist(&msg, received_at),
                "arm" => self.ingest_arm(&msg),
                "dig" | "dump" => {
                    // construction refused a bundle that resolves the drum, so every excavation is refused here
                    self.rejected_bounds += 1;
                    if self.outbound_open {
                        self.publish(
                            epoch,
                            json!({"type": "command_refused", "cmd": cmd,
                                   "reason": "native terrain does not resolve the drum footprint"}),
                        );
                    }
                }
                "ack" => {
                    let Some(sess) = self.session.as_mut() else {
                        continue;
                    };
                    let Some(seq) = msg.get("seq").filter(|s| !s.is_null()).and_then(py_int) else {
                        continue;
                    };
                    sess.ack(seq);
                    if let Some(&gen_no) = self.seq_to_gen.get(&seq)
                        && gen_no > self.last_acked_gen
                    {
                        self.last_acked_gen = gen_no;
                    }
                }
                _ => {}
            }
        }
    }

    /// M-04: a non-finite or over-bound twist is refused, never applied.
    fn ingest_twist(&mut self, msg: &Map<String, Value>, received_at: f64) {
        let get = |k: &str| msg.get(k).map_or(Some(0.0), finite_number);
        let (Some(v), Some(omega)) = (get("v"), get("omega")) else {
            self.rejected_bounds += 1;
            return;
        };
        if v.abs() > self.ws.v_max || omega.abs() > self.ws.omega_max {
            self.rejected_bounds += 1;
            return;
        }
        if !self.safe_stopped {
            self.latest_twist = (v, omega);
            self.last_twist_at = Some(received_at);
        }
    }

    /// [REQ:PX-10] The operator's arm offsets: a non-number is refused (the last good pose kept), a wild one clamps.
    fn ingest_arm(&mut self, msg: &Map<String, Value>) {
        for (key, front) in [("front", true), ("back", false)] {
            let Some(raw) = msg.get(key) else { continue };
            let Some(x) = finite_number(raw) else {
                self.rejected_bounds += 1;
                continue;
            };
            let x = x.clamp(ARM_OFFSET_MIN_RAD, ARM_OFFSET_MAX_RAD);
            if front {
                self.arm_front_offset_rad = x;
            } else {
                self.arm_back_offset_rad = x;
            }
        }
    }

    #[allow(clippy::too_many_lines)] // one telemetry frame, key by key as the Python's
    fn step_and_publish(
        &mut self,
        epoch: u64,
        now: f64,
        v: f64,
        omega: f64,
        force_kf: bool,
    ) -> Result<(), String> {
        let rep = self
            .ws
            .step(v, omega, self.dt, 0.0)
            .map_err(|e| e.to_string())?;
        let t = &rep.drive;
        self.simulation_t_s += self.dt;
        self.accumulate_metrics(t.v_achieved, v, t.omega_achieved, t.slope_rad);
        let dirty = vec![rep.dirty];
        let keyframe = force_kf
            || rep.recentered
            || (self.generation + 1 - self.last_keyframe_gen) >= self.opts.keyframe_interval;
        let gen_no = self.advance_generation(&dirty, keyframe)?;
        let base = self.ws.baseline_virgin_kg();
        let residual_frac = if base == 0.0 {
            0.0
        } else {
            self.ws.conservation_residual() / base
        };
        let inventory = self.ws.inventory_kg();
        let current = self.sensor.current(inventory)?;
        let inferred = self.sensor.infer(current);
        let cap = self.calib.drum.capacity_kg;
        let origin = self.ws.window_origin().map(|(x, y)| json!([x, y]));
        #[allow(clippy::cast_precision_loss)] // a tick count
        let avg_slope_deg = self.slope_sum_deg / self.slope_n.max(1) as f64;
        let telem = json!({
            "rc": [t.rc.0, t.rc.1], "yaw": t.yaw, "v_cmd": v, "omega_cmd": omega,
            "omega_achieved": t.omega_achieved, "track_m": null, "v_achieved": t.v_achieved, "slip": t.slip,
            "entrapped": t.entrapped, "slope_rad": t.slope_rad, "sinkage_m": t.sinkage_m,
            "contact_len_m": t.contact_len_m,
            "bounds_clamped": rep.bounds_clamped, "recentered": rep.recentered,
            "pose_xy": [rep.pose_xy.0, rep.pose_xy.1], "window_world_origin": origin,
            "simulation_t_s": self.simulation_t_s, "step_dt_s": self.dt,
            "cut_total_kg": self.ws.cut_total_kg(), "placed_total_kg": self.ws.placed_total_kg(),
            "inventory_kg": inventory,
            "dig_energy_j": 0.0, "dig_energy_per_kg": self.calib.dig_energy_per_kg,
            "dig_j_per_kg": self.calib.dig_energy_per_kg, "dig_reaction_n": 0.0,
            "drum_capacity_kg": cap, "drum_fill_frac": if cap > 0.0 { (inventory / cap).min(1.0) } else { 0.0 },
            "drum_full": false, "max_cut_per_pass_m": self.max_cut_per_pass_m,
            "drum_current_a": current, "drum_mass_inferred_kg": inferred,
            "should_offload": self.sensor.offload(inferred).offload,
            "arm_front_offset_rad": self.arm_front_offset_rad, "arm_back_offset_rad": self.arm_back_offset_rad,
            "dig_engagement": dig_engagement(self.arm_front_offset_rad),
            "dist_actual_m": self.dist_actual_m, "wheel_odo_m": self.dist_wheel_m,
            "odometry_error_m": self.dist_wheel_m - self.dist_actual_m,
            "avg_slope_deg": avg_slope_deg,
            "imu_gyro_z": self.imu_gyro_z, "imu_accel_long": self.imu_accel_long,
            "imu_accel_lat": self.imu_accel_lat,
        });
        let payload = json!({"type": "telemetry", "generation": gen_no, "keyframe": keyframe, "telem": telem,
                             "dirty": dirty, "residual_frac": residual_frac, "safe_stop": self.safe_stopped});
        let sess = self.session.as_mut().ok_or("no session")?;
        if let Some(frame) = sess.send(payload, now) {
            if let Some(seq) = frame["seq"].as_i64() {
                self.seq_to_gen.insert(seq, gen_no);
            }
            self.publish(epoch, frame);
        }
        // the deadman is driven every iteration, independent of any inbound read (NB-3)
        if self.session.as_mut().is_some_and(|s| s.tick(now)) {
            self.trip(epoch, "deadman_link_stall");
        }
        Ok(())
    }

    /// #31/#32: the slip-blind wheel odometry against the ground truth, the mean grade, and the deterministic IMU
    /// (specific force: the body acceleration plus gravity along the incline, and the centripetal term).
    fn accumulate_metrics(&mut self, va: f64, vc: f64, omega: f64, slope: f64) {
        if !(va.is_finite() && vc.is_finite() && omega.is_finite() && slope.is_finite()) {
            return;
        }
        self.dist_actual_m += va.abs() * self.dt;
        self.dist_wheel_m += vc.abs() * self.dt;
        self.slope_sum_deg += slope.abs().to_degrees();
        self.slope_n += 1;
        self.imu_gyro_z = omega;
        self.imu_accel_long =
            (va - self.prev_v_achieved) / self.dt.max(1e-6) + self.gravity_ms2 * slope.sin();
        self.imu_accel_lat = omega * va;
        self.prev_v_achieved = va;
    }

    /// Advance the generation and write its manifest over the union of the dirty regions since the coverage floor
    /// (the later of the consumer's last ack and the last keyframe), or the whole window on a keyframe.
    fn advance_generation(&mut self, dirty: &[[usize; 4]], keyframe: bool) -> Result<u64, String> {
        self.generation += 1;
        let gen_no = self.generation;
        self.pending.extend(dirty.iter().map(|b| (gen_no, *b)));
        if keyframe {
            self.last_keyframe_gen = gen_no;
        }
        let floor = self
            .last_acked_gen
            .max(if keyframe { 0 } else { self.last_keyframe_gen });
        self.pending.retain(|(g, _)| *g > floor);
        let (h, w) = self.window_shape;
        let bbox = if keyframe {
            self.pending.clear();
            [0, 0, h, w]
        } else {
            let lo = |i: usize| self.pending.iter().map(|(_, b)| b[i]).min().unwrap_or(0);
            let hi = |i: usize| self.pending.iter().map(|(_, b)| b[i]).max().unwrap_or(0);
            [lo(0), lo(1), hi(2).min(h), hi(3).min(w)]
        };
        self.write_manifest(gen_no, bbox, keyframe, dirty)?;
        self.prune_generations(gen_no);
        Ok(gen_no)
    }

    fn write_manifest(
        &mut self,
        gen_no: u64,
        bbox: [usize; 4],
        keyframe: bool,
        dirty: &[[usize; 4]],
    ) -> Result<(), String> {
        let [r0, c0, r1, c1] = bbox;
        let gdir = self.generations_dir.join(format!("gen_{gen_no:08}"));
        std::fs::create_dir_all(&gdir).map_err(|e| format!("{}: {e}", gdir.display()))?;
        let fine = self.ws.fine().ok_or("no window")?;
        let w = fine.width();
        let f = fine.fields();
        let height = fine.derive_height();
        let diff = self.ws.diff_field().map_err(|e| e.to_string())?;
        let f32s = |a: &[f64]| -> Vec<u8> {
            (r0..r1)
                .flat_map(|r| (c0..c1).map(move |c| r * w + c))
                .flat_map(|i| {
                    #[allow(clippy::cast_possible_truncation)] // the wire is float32
                    (a[i] as f32).to_le_bytes()
                })
                .collect()
        };
        let mut fields: Vec<(&str, &str, &str, Vec<u8>)> = vec![
            ("height", "<f4", "height.rf32", f32s(&height)),
            ("density", "<f4", "density.rf32", f32s(&f.density)),
            (
                "state_label",
                "u1",
                "state_label.r8",
                (r0..r1)
                    .flat_map(|r| (c0..c1).map(move |c| r * w + c))
                    .map(|i| f.state_label[i])
                    .collect(),
            ),
            (
                "disturbance",
                "<f4",
                "disturbance.rf32",
                f32s(&f.disturbance),
            ),
            ("diff", "<f4", "diff.rf32", f32s(&diff)),
        ];
        if keyframe {
            fields.push(("mass_areal", "<f4", "mass_areal.rf32", f32s(&f.mass_areal)));
        }
        let mut meta = Map::new();
        for (name, dtype, file, data) in fields {
            atomic_write(&gdir.join(file), &data)?;
            let digest = hex(&Sha256::digest(&data));
            meta.insert(
                name.to_owned(),
                json!({"file": file, "dtype": dtype, "shape": [r1 - r0, c1 - c0], "digest": digest}),
            );
        }
        let manifest = json!({
            "protocol_version": PROTOCOL_VERSION, "generation": gen_no, "keyframe": keyframe,
            "window_world_origin": self.ws.window_origin().map(|(x, y)| json!([x, y])),
            "fine_cell_m": self.ws.fine_cell_m(), "bbox_rc": bbox, "shape": [r1 - r0, c1 - c0],
            "fields": meta, "dirty": dirty,
        });
        // the manifest is written last: its presence commits every crop beside it
        let text = stewie_twin::pyjson::dumps(&manifest).map_err(|e| format!("{e:?}"))?;
        atomic_write(&gdir.join("manifest.json"), text.as_bytes())?;
        if keyframe {
            self.latest_keyframe_dir = Some(gdir);
        }
        Ok(())
    }

    /// Keep the last `retain_generations` generation directories, never the newest keyframe's.
    fn prune_generations(&self, gen_no: u64) {
        let Some(old) = gen_no
            .checked_sub(self.opts.retain_generations)
            .filter(|o| *o >= 1)
        else {
            return;
        };
        let gdir = self.generations_dir.join(format!("gen_{old:08}"));
        if self.latest_keyframe_dir.as_ref() == Some(&gdir) {
            return;
        }
        // an ephemeral per-tick directory: a failure to remove leaves it for the session teardown
        let _ = std::fs::remove_dir_all(&gdir);
    }
}
