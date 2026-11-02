//! The battery-aware simulation of an ordered trip list (Python `lode.planner_sim._simulate`, RW-33c2): the
//! sequencer scores every candidate order with it. The rover starts full at the charger; a drive to a work site
//! keeps the reserve margin (recharging first when it would not), a drive home may draw into the reserve but
//! never below zero; work is drawn in chunks above the reserve, recharging and returning as needed; mission-clock
//! windows make the rover wait or mark the action impossible; a rover that cannot go on is stranded, and only
//! the work it actually finished is credited. Inter-site legs use the routed distance.
//!
//! The Python's thermal derating reads a mission temperature that its own boundary never sets, so the derate is
//! always 1 there; it is not modelled here.

use crate::balance::Routes;
use crate::mission::Mission;
use crate::trips::{Context, Trip, TripKind, window_gate};

/// One timeline span.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Span {
    pub t0: f64,
    pub t1: f64,
    pub kind: SpanKind,
    pub batt0: f64,
    pub batt1: f64,
    pub mass_kg: f64,
    pub speed: f64,
    pub from: (f64, f64),
    pub to: (f64, f64),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SpanKind {
    Drive,
    Wait,
    Charge,
    Dig,
    Offload,
}

/// When each trip started and ended.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct TripTimes {
    pub trip: usize,
    pub t_start: f64,
    pub t_end: f64,
}

/// The order-dependent totals.
#[derive(Debug, Clone, PartialEq)]
pub struct Core {
    pub time_s: f64,
    pub mass_kg: f64,
    pub energy_j: f64,
    pub charges: u64,
    /// Inter-site drive plus every trip's haul shuttle [m].
    pub distance_m: f64,
    pub avg_power_w: f64,
    pub feasible: bool,
    pub infeasible_reasons: Vec<String>,
}

fn straight(a: (f64, f64), b: (f64, f64)) -> f64 {
    (a.0 - b.0).hypot(a.1 - b.1)
}

struct Sim<'m, 'r, 'a> {
    m: &'m Mission,
    ctx: Context,
    routes: &'r mut Routes<'a>,
    full: f64,
    reserve: f64,
    pos: (f64, f64),
    batt: f64,
    t: f64,
    cum_mass: f64,
    cum_energy: f64,
    charges: u64,
    tl: Vec<Span>,
    infeasible: Vec<String>,
}

impl Sim<'_, '_, '_> {
    fn rd(&mut self, a: (f64, f64), b: (f64, f64)) -> Result<f64, String> {
        self.routes.distance(a, b)
    }

    fn park(&mut self, kind: SpanKind, until: f64, batt1: f64, at: (f64, f64)) {
        self.tl.push(Span {
            t0: self.t,
            t1: until,
            kind,
            batt0: self.batt,
            batt1,
            mass_kg: 0.0,
            speed: 0.0,
            from: at,
            to: at,
        });
    }

    /// A raw drive leg the caller has made sure fits.
    fn leg(&mut self, to: (f64, f64)) -> Result<(), String> {
        let d = self.rd(self.pos, to)?;
        if d <= 1e-9 {
            return Ok(());
        }
        let (e, dur) = (d * self.ctx.drive_j_per_m, d / self.ctx.drive_speed_ms);
        self.tl.push(Span {
            t0: self.t,
            t1: self.t + dur,
            kind: SpanKind::Drive,
            batt0: self.batt,
            batt1: self.batt - e,
            mass_kg: 0.0,
            speed: self.ctx.drive_speed_ms,
            from: self.pos,
            to,
        });
        self.pos = to;
        self.batt -= e;
        self.t += dur;
        self.cum_energy += e;
        Ok(())
    }

    /// Return to the charger and refill; false when stranded or no recharge window remains.
    fn charge(&mut self) -> Result<bool, String> {
        let charger = self.m.charger;
        if straight(self.pos, charger) > 1e-9
            && self.rd(self.pos, charger)? * self.ctx.drive_j_per_m > self.batt + 1e-6
        {
            self.infeasible.push(format!(
                "stranded at ({:.0},{:.0}): cannot reach the charger to recharge on the remaining charge",
                self.pos.0, self.pos.1
            ));
            return Ok(false);
        }
        self.leg(charger)?;
        let (start, wait, reason) = window_gate(&self.m.mission_windows, "recharge", self.t);
        if let Some(r) = reason {
            self.infeasible.push(format!("recharge at charger: {r}"));
            return Ok(false);
        }
        if wait > 0.0 {
            self.park(SpanKind::Wait, start, self.batt, self.pos);
            self.t = start;
        }
        let dur = (self.full - self.batt) / self.ctx.charge_w;
        self.park(SpanKind::Charge, self.t + dur, self.full, self.pos);
        self.batt = self.full;
        self.t += dur;
        self.charges += 1;
        Ok(true)
    }

    /// A reserve-aware drive; false when the leg is infeasible (skipped and recorded).
    fn drive(&mut self, to: (f64, f64)) -> Result<bool, String> {
        let d = self.rd(self.pos, to)?;
        if d <= 1e-9 {
            return Ok(true);
        }
        let e = d * self.ctx.drive_j_per_m;
        let usable = self.full - self.reserve;
        let going_home = straight(to, self.m.charger) <= 1e-9;
        if !going_home && e > self.batt - self.reserve {
            let from_charger = self.rd(self.m.charger, to)? * self.ctx.drive_j_per_m;
            if from_charger > usable {
                self.infeasible.push(format!(
                    "leg to ({:.0},{:.0}) needs {:.0} kJ; a full charge reaches only {:.0} kJ above reserve",
                    to.0,
                    to.1,
                    e / 1e3,
                    usable / 1e3
                ));
                return Ok(false);
            }
            if !self.charge()? {
                return Ok(false);
            }
        }
        if e > self.batt + 1e-6 {
            self.infeasible.push(format!(
                "stranded at ({:.0},{:.0}): cannot reach ({:.0},{:.0}) on the remaining {:.0} kJ",
                self.pos.0,
                self.pos.1,
                to.0,
                to.1,
                self.batt / 1e3
            ));
            return Ok(false);
        }
        self.leg(to)?;
        Ok(true)
    }

    /// Draw a trip's work at its site in chunks above the reserve; credit only what was finished.
    fn spend(
        &mut self,
        kind: SpanKind,
        label: &str,
        work_e: f64,
        work_t: f64,
        at: (f64, f64),
        trip: &Trip,
    ) -> Result<(), String> {
        let e = work_e + trip.haul_e + trip.lift_e;
        let dur = work_t + trip.haul_m / self.ctx.drive_speed_ms;
        let (start, wait, reason) = window_gate(&self.m.mission_windows, "work", self.t);
        if let Some(r) = reason {
            self.infeasible
                .push(format!("{label} at ({:.0},{:.0}): {r}", at.0, at.1));
            return Ok(());
        }
        if wait > 0.0 {
            self.park(SpanKind::Wait, start, self.batt, at);
            self.t = start;
        }
        let (mut spent, mut completed) = (0.0, true);
        while spent < e - 1e-6 {
            let usable = self.batt - self.reserve;
            if usable <= 1e-3 {
                if !self.charge()? || !self.drive(at)? {
                    completed = false;
                    break;
                }
                continue;
            }
            let chunk = (e - spent).min(usable);
            let cd = if e > 0.0 { dur * (chunk / e) } else { 0.0 };
            self.tl.push(Span {
                t0: self.t,
                t1: self.t + cd,
                kind,
                batt0: self.batt,
                batt1: self.batt - chunk,
                mass_kg: if e > 0.0 {
                    trip.mass_kg * (chunk / e)
                } else {
                    0.0
                },
                speed: 0.0,
                from: at,
                to: at,
            });
            self.batt -= chunk;
            self.t += cd;
            spent += chunk;
        }
        if completed {
            self.cum_mass += trip.mass_kg;
            self.cum_energy += e;
        } else {
            self.cum_mass += if e > 1e-9 {
                trip.mass_kg * (spent / e)
            } else {
                0.0
            };
            self.cum_energy += spent;
        }
        Ok(())
    }
}

/// Simulate `order` (indices into `trips`) for the mission with the vehicle context. Returns the timeline, each
/// trip's times (in order), and the totals.
///
/// # Errors
/// The router's refusal.
pub fn simulate(
    m: &Mission,
    trips: &[Trip],
    order: &[usize],
    ctx: &Context,
    routes: &mut Routes<'_>,
) -> Result<(Vec<Span>, Vec<TripTimes>, Core), String> {
    let full = ctx.battery_j;
    let mut s = Sim {
        m,
        ctx: *ctx,
        routes,
        full,
        reserve: ctx.reserve_frac * full,
        pos: m.charger,
        batt: full,
        t: 0.0,
        cum_mass: 0.0,
        cum_energy: 0.0,
        charges: 0,
        tl: Vec::new(),
        infeasible: Vec::new(),
    };
    let mut times = Vec::with_capacity(order.len());
    for &k in order {
        let tr = &trips[k];
        let t0 = s.t;
        let (start, wait, reason) = window_gate(&m.mission_windows, "drive", s.t);
        if let Some(r) = reason {
            s.infeasible.push(format!(
                "transit to ({:.0},{:.0}): {r}",
                tr.site.0, tr.site.1
            ));
            times.push(TripTimes {
                trip: k,
                t_start: t0,
                t_end: s.t,
            });
            continue;
        }
        if wait > 0.0 {
            let at = s.pos;
            s.park(SpanKind::Wait, start, s.batt, at);
            s.t = start;
        }
        if s.drive(tr.site)? {
            if tr.kind == TripKind::Import {
                s.spend(
                    SpanKind::Offload,
                    "offload",
                    tr.offload_e,
                    tr.offload_t,
                    tr.site,
                    tr,
                )?;
            } else {
                s.spend(SpanKind::Dig, "dig", tr.dig_e, tr.dig_t, tr.site, tr)?;
            }
        }
        times.push(TripTimes {
            trip: k,
            t_start: t0,
            t_end: s.t,
        });
    }
    s.drive(m.charger)?;
    // Python `sum` starts at +0.0 (an idle fleet rover drives 0.0 m, not -0.0)
    let drive_m: f64 =
        s.tl.iter()
            .map(|p| (p.t1 - p.t0) * p.speed)
            .fold(0.0, |a, b| a + b);
    let haul_m: f64 = order
        .iter()
        .map(|&k| trips[k].haul_m)
        .fold(0.0, |a, b| a + b);
    let core = Core {
        time_s: s.t,
        mass_kg: s.cum_mass,
        energy_j: s.cum_energy,
        charges: s.charges,
        distance_m: drive_m + haul_m,
        avg_power_w: if s.t > 1e-9 { s.cum_energy / s.t } else { 0.0 },
        feasible: s.infeasible.is_empty(),
        infeasible_reasons: s.infeasible,
    };
    Ok((s.tl, times, core))
}
