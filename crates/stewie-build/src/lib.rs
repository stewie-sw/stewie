//! LEAP construction (RW-34a): composite structures (landing pad, habitat foundation, blast berm, crater fill,
//! borrow pit, haul road, solar pad, trench) decomposed into the planner's primitive cut and fill orders, and the
//! validate-and-advise site plan over a base layout (Python `leap.structures`, `leap.siteplan`).
//!
//! A consuming structure pairs its fill with a cut whose bank mass equals the fill's loose mass (the swell is bank
//! over loose density), so a self-balanced structure nets zero. The site plan reports the base-wide mass economy, a
//! greedy nearest-source routing, footprint clearances, a sources-first build order and advisories; it never moves
//! a structure. Clearances below the minimum gap are advised as well as overlaps (D-R101). Densities come from the
//! soil baseline contract. The Python's reinforcement-learning environments and challenge harness are not ported
//! (D-R101).

use serde_json::{Map, Value, json};

/// Bank (in-situ, cut) and loose (placed fill) regolith densities [kg/m^3].
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Densities {
    pub bank: f64,
    pub loose: f64,
}

impl Densities {
    /// Loose fill volume per bank cut volume.
    #[must_use]
    pub fn swell(&self) -> f64 {
        self.bank / self.loose
    }
}

/// The structure templates, in name order.
pub const STRUCTURES: [&str; 8] = [
    "blast_berm",
    "borrow_pit",
    "crater_fill",
    "habitat_foundation",
    "haul_road",
    "landing_pad",
    "solar_pad",
    "trench",
];

fn py_float(x: f64) -> String {
    stewie_twin::pyjson::float_repr(x).unwrap_or_else(|_| x.to_string())
}

/// One order dict, as `mission_from_dict` takes it; a cut declares the bank density it is costed at.
fn order(
    d: &Densities,
    action: &str,
    kind: &str,
    at: (f64, f64),
    footprint_m2: f64,
    depth_m: f64,
    note: &str,
) -> Value {
    let mut o = json!({"action": action, "kind": kind, "x": at.0, "y": at.1, "footprint_m2": footprint_m2,
                       "depth_m": depth_m, "note": note});
    if kind == "cut" {
        o["insitu_density_kg_m3"] = json!(d.bank);
    }
    o
}

/// A template's parameters: the given ones, else the template defaults; each must be positive.
struct Params<'a> {
    given: &'a Map<String, Value>,
    known: &'static [&'static str],
}

impl Params<'_> {
    fn get(&self, name: &str, default: f64) -> Result<f64, String> {
        let (v, shown) = match self.given.get(name) {
            None => (default, py_float(default)),
            // echo the value as given, as the Python does (an integer stays an integer)
            Some(v) => (
                v.as_f64()
                    .ok_or_else(|| format!("{name} must be a number (got {v})"))?,
                v.to_string(),
            ),
        };
        if v > 0.0 {
            Ok(v)
        } else {
            Err(format!(
                "{name} must be > 0 (got {shown}) (audit L21: zero divided; negative silently inverted the cut/fill \
                 volume balance)"
            ))
        }
    }

    fn check_names(&self, structure: &str) -> Result<(), String> {
        match self
            .given
            .keys()
            .find(|k| !self.known.contains(&k.as_str()))
        {
            Some(k) => Err(format!(
                "{structure}() got an unexpected keyword argument '{k}'"
            )),
            None => Ok(()),
        }
    }
}

/// The cut and fill orders for structure `name` at local `(x, y)` [m] with `params` (template defaults otherwise).
///
/// # Errors
/// An unknown structure or parameter, or a parameter that is not positive.
#[allow(clippy::too_many_lines, clippy::many_single_char_names)] // one arm per template; x, y, d as the Python
pub fn decompose(
    name: &str,
    x: f64,
    y: f64,
    params: &Map<String, Value>,
    d: &Densities,
) -> Result<Vec<Value>, String> {
    let known: &'static [&'static str] = match name {
        "landing_pad" => &["side_m", "cut_depth_m", "berm_height_m"],
        "habitat_foundation" => &["side_m", "cut_depth_m", "fill_height_m"],
        "blast_berm" => &["length_m", "width_m", "height_m", "borrow_depth_m"],
        "crater_fill" => &["radius_m", "depth_m", "borrow_depth_m"],
        "borrow_pit" => &["side_m", "depth_m"],
        "haul_road" => &["length_m", "width_m", "cut_depth_m"],
        "solar_pad" => &["side_m", "cut_depth_m"],
        "trench" => &["length_m", "width_m", "depth_m"],
        _ => {
            let list: Vec<String> = STRUCTURES.iter().map(|s| format!("'{s}'")).collect();
            return Err(format!(
                "unknown structure '{name}'; known: [{}]",
                list.join(", ")
            ));
        }
    };
    let p = Params {
        given: params,
        known,
    };
    p.check_names(name)?;
    let swell = d.swell();
    Ok(match name {
        "landing_pad" | "habitat_foundation" => {
            let pad = name == "landing_pad";
            let side = p.get("side_m", if pad { 6.0 } else { 5.0 })?;
            let cut = p.get("cut_depth_m", if pad { 0.05 } else { 0.06 })?;
            let rise = p.get(
                if pad {
                    "berm_height_m"
                } else {
                    "fill_height_m"
                },
                if pad { 0.12 } else { 0.06 },
            )?;
            let fill_vol = side * side * cut * swell;
            let fill_at = (x + side / 2.0 + (fill_vol / rise).sqrt() / 2.0 + 2.0, y);
            if pad {
                vec![
                    order(
                        d,
                        "Level landing pad",
                        "cut",
                        (x, y),
                        side * side,
                        cut,
                        &format!("{side:.0}x{side:.0} m"),
                    ),
                    order(
                        d,
                        "Perimeter blast berm",
                        "fill",
                        fill_at,
                        fill_vol / rise,
                        rise,
                        "from pad cut (bulked)",
                    ),
                ]
            } else {
                vec![
                    order(
                        d,
                        "Cut habitat footing",
                        "cut",
                        (x, y),
                        side * side,
                        cut,
                        "",
                    ),
                    order(
                        d,
                        "Compacted foundation fill",
                        "fill",
                        fill_at,
                        fill_vol / rise,
                        rise,
                        "from footing cut (bulked)",
                    ),
                ]
            }
        }
        "blast_berm" => {
            let (len, wid) = (p.get("length_m", 15.0)?, p.get("width_m", 3.0)?);
            let (h, bd) = (p.get("height_m", 0.5)?, p.get("borrow_depth_m", 0.3)?);
            let borrow = len * wid * h / swell;
            vec![
                order(
                    d,
                    "Borrow pit (berm)",
                    "cut",
                    (x - (wid / 2.0 + (borrow / bd).sqrt() / 2.0 + 2.0), y),
                    borrow / bd,
                    bd,
                    "source",
                ),
                order(
                    d,
                    "Blast berm",
                    "fill",
                    (x, y),
                    len * wid,
                    h,
                    "ridge to spec",
                ),
            ]
        }
        "crater_fill" => {
            let (r, depth, bd) = (
                p.get("radius_m", 8.0)?,
                p.get("depth_m", 0.4)?,
                p.get("borrow_depth_m", 0.3)?,
            );
            let area = std::f64::consts::PI * r * r;
            let borrow = area * depth / swell;
            vec![
                order(
                    d,
                    "Borrow pit (crater)",
                    "cut",
                    (x - (r + (borrow / bd).sqrt() / 2.0 + 2.0), y),
                    borrow / bd,
                    bd,
                    "source",
                ),
                order(d, "Crater fill", "fill", (x, y), area, depth, "to grade"),
            ]
        }
        "borrow_pit" => {
            let (side, depth) = (p.get("side_m", 6.0)?, p.get("depth_m", 0.3)?);
            vec![order(
                d,
                "Borrow pit",
                "cut",
                (x, y),
                side * side,
                depth,
                "material source",
            )]
        }
        "haul_road" => {
            let (len, wid, cut) = (
                p.get("length_m", 30.0)?,
                p.get("width_m", 2.0)?,
                p.get("cut_depth_m", 0.03)?,
            );
            vec![order(
                d,
                "Grade haul road",
                "cut",
                (x, y),
                len * wid,
                cut,
                &format!("{len:.0}x{wid:.0} m corridor"),
            )]
        }
        "solar_pad" => {
            let (side, cut) = (p.get("side_m", 8.0)?, p.get("cut_depth_m", 0.04)?);
            vec![order(
                d,
                "Level solar pad",
                "cut",
                (x, y),
                side * side,
                cut,
                "flat, low-obstruction",
            )]
        }
        _ => {
            let (len, wid, depth) = (
                p.get("length_m", 12.0)?,
                p.get("width_m", 1.0)?,
                p.get("depth_m", 0.4)?,
            );
            vec![order(
                d,
                "Excavate trench",
                "cut",
                (x, y),
                len * wid,
                depth,
                "utility/footing trench",
            )]
        }
    })
}

/// One structure the operator placed: a template, a site coordinate (local m) and its parameters.
#[derive(Debug, Clone, PartialEq)]
pub struct Placed {
    pub name: String,
    pub x: f64,
    pub y: f64,
    pub params: Map<String, Value>,
}

/// A routed flow from a source cut to a sink fill.
#[derive(Debug, Clone, PartialEq)]
pub struct Pairing {
    pub source: usize,
    pub sink: usize,
    pub source_xy: (f64, f64),
    pub sink_xy: (f64, f64),
    pub mass_kg: f64,
    pub haul_dist_m: f64,
}

/// Two placed structures' bounding-disk relation.
#[derive(Debug, Clone, PartialEq)]
pub struct Clearance {
    pub i: usize,
    pub j: usize,
    /// Centre distance minus both bounding radii; below zero they overlap.
    pub gap_m: f64,
    pub overlap: bool,
}

/// The site-plan report.
#[derive(Debug, Clone, PartialEq)]
pub struct SitePlan {
    pub total_cut_mass_kg: f64,
    pub total_fill_mass_kg: f64,
    /// Cut minus fill: above zero a surplus to spoil, below a deficit to import.
    pub net_mass_kg: f64,
    pub pairings: Vec<Pairing>,
    pub total_haul_work_kg_m: f64,
    pub clearances: Vec<Clearance>,
    /// Order indices, every cut before every fill.
    pub build_order: Vec<usize>,
    pub advisories: Vec<String>,
}

struct Ord {
    structure: usize,
    cut: bool,
    at: (f64, f64),
    footprint_m2: f64,
    mass_kg: f64,
}

fn dist(a: (f64, f64), b: (f64, f64)) -> f64 {
    (a.0 - b.0).hypot(a.1 - b.1)
}

/// `n` to whole units with thousands separators (Python `f"{n:,.0f}"`).
fn thousands(n: f64) -> String {
    let s = format!("{n:.0}");
    let (sign, digits) = s.strip_prefix('-').map_or(("", s.as_str()), |d| ("-", d));
    let mut out = String::new();
    for (k, ch) in digits.chars().enumerate() {
        if k > 0 && (digits.len() - k) % 3 == 0 {
            out.push(',');
        }
        out.push(ch);
    }
    format!("{sign}{out}")
}

/// Validate and advise over a base layout.
///
/// # Errors
/// An unknown structure or parameter, or a parameter that is not positive.
#[allow(clippy::too_many_lines)] // the Python's report, step by step
pub fn analyze_siteplan(
    placed: &[Placed],
    min_gap_m: f64,
    d: &Densities,
) -> Result<SitePlan, String> {
    let mut orders = Vec::new();
    for (s, p) in placed.iter().enumerate() {
        for o in decompose(&p.name, p.x, p.y, &p.params, d)? {
            let cut = o["kind"] == "cut";
            let (fp, depth) = (
                o["footprint_m2"].as_f64().unwrap_or(0.0),
                o["depth_m"].as_f64().unwrap_or(0.0),
            );
            orders.push(Ord {
                structure: s,
                cut,
                at: (
                    o["x"].as_f64().unwrap_or(0.0),
                    o["y"].as_f64().unwrap_or(0.0),
                ),
                footprint_m2: fp,
                mass_kg: (if cut { d.bank } else { d.loose }) * fp * depth,
            });
        }
    }
    let total_cut: f64 = orders.iter().filter(|o| o.cut).map(|o| o.mass_kg).sum();
    let total_fill: f64 = orders.iter().filter(|o| !o.cut).map(|o| o.mass_kg).sum();
    let net = total_cut - total_fill;
    // greedy routing: the largest fill first, each from its nearest sources with supply left
    let mut remaining: Vec<f64> = orders
        .iter()
        .map(|o| if o.cut { o.mass_kg } else { 0.0 })
        .collect();
    let mut sinks: Vec<usize> = (0..orders.len()).filter(|&k| !orders[k].cut).collect();
    sinks.sort_by(|&a, &b| orders[b].mass_kg.total_cmp(&orders[a].mass_kg));
    let (mut pairings, mut work) = (Vec::new(), 0.0);
    for sink in sinks {
        let mut demand = orders[sink].mass_kg;
        let mut sources: Vec<usize> = (0..orders.len()).filter(|&k| orders[k].cut).collect();
        sources.sort_by(|&a, &b| {
            dist(orders[a].at, orders[sink].at).total_cmp(&dist(orders[b].at, orders[sink].at))
        });
        for src in sources {
            if demand <= 1e-12 {
                break;
            }
            if remaining[src] <= 1e-12 {
                continue;
            }
            let take = remaining[src].min(demand);
            let haul = dist(orders[src].at, orders[sink].at);
            pairings.push(Pairing {
                source: src,
                sink,
                source_xy: orders[src].at,
                sink_xy: orders[sink].at,
                mass_kg: take,
                haul_dist_m: haul,
            });
            remaining[src] -= take;
            demand -= take;
            work += take * haul;
        }
    }
    // bounding disks from each structure's summed footprint
    let radius = |s: usize| {
        let fp: f64 = orders
            .iter()
            .filter(|o| o.structure == s)
            .map(|o| o.footprint_m2)
            .sum();
        if fp > 0.0 {
            (fp / std::f64::consts::PI).sqrt()
        } else {
            0.0
        }
    };
    let mut clearances = Vec::new();
    for i in 0..placed.len() {
        for j in i + 1..placed.len() {
            let gap = dist((placed[i].x, placed[i].y), (placed[j].x, placed[j].y))
                - radius(i)
                - radius(j);
            clearances.push(Clearance {
                i,
                j,
                gap_m: gap,
                overlap: gap < 0.0,
            });
        }
    }
    let build_order: Vec<usize> = (0..orders.len())
        .filter(|&k| orders[k].cut)
        .chain((0..orders.len()).filter(|&k| !orders[k].cut))
        .collect();
    let mut advisories = Vec::new();
    let tol = 1e-6 * total_cut.max(1.0);
    if net > tol {
        advisories.push(format!(
            "base has a {} kg material surplus -- route the surplus cut to a spoil pile or an export sink (it is not \
             consumed by any fill).",
            thousands(net)
        ));
    } else if net < -tol {
        advisories.push(format!(
            "base has a {} kg material deficit -- the fills demand more than the cuts yield; add a borrow pit or \
             import material.",
            thousands(-net)
        ));
    }
    let (n_src, n_sink) = (
        orders.iter().filter(|o| o.cut).count(),
        orders.iter().filter(|o| !o.cut).count(),
    );
    if n_src >= 2 && n_sink >= 1 {
        advisories.push(format!(
            "{n_src} cut sources feed {n_sink} fill(s) -- route base-wide (one borrow pit can feed several fills) to \
             cut total haul rather than one pit per structure."
        ));
    }
    for c in clearances.iter().filter(|c| c.overlap) {
        advisories.push(format!(
            "structures #{} ({}) and #{} ({}) overlap (gap {:.1} m) -- adjust placement so footprints clear by >= \
             {min_gap_m:.1} m.",
            c.i, placed[c.i].name, c.j, placed[c.j].name, c.gap_m
        ));
    }
    // D-R101: a clearance below the minimum gap is advised too (the Python reports only overlaps)
    for c in clearances
        .iter()
        .filter(|c| !c.overlap && c.gap_m < min_gap_m)
    {
        advisories.push(format!(
            "structures #{} ({}) and #{} ({}) are only {:.1} m apart -- footprints should clear by >= {min_gap_m:.1} m.",
            c.i, placed[c.i].name, c.j, placed[c.j].name, c.gap_m
        ));
    }
    Ok(SitePlan {
        total_cut_mass_kg: total_cut,
        total_fill_mass_kg: total_fill,
        net_mass_kg: net,
        pairings,
        total_haul_work_kg_m: work,
        clearances,
        build_order,
        advisories,
    })
}
