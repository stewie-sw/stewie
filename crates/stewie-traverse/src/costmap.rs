//! Slope and hazard costmaps (Python `slope_costmap`, `negative_obstacle_mask`, keep-outs).

/// The 3x3 drop-off hazard: a cell more than `max_drop_m` above its lowest neighbour (edges clamp, as
/// scipy `minimum_filter(mode="nearest")`) overlooks a fall, even when it is flat itself.
#[must_use]
#[allow(clippy::cast_possible_wrap, clippy::cast_sign_loss)] // grid sizes are far below isize::MAX
pub fn negative_obstacle_mask(
    z: &[f64],
    width: usize,
    height: usize,
    max_drop_m: f64,
) -> Vec<bool> {
    if max_drop_m <= 0.0 {
        return vec![false; z.len()];
    }
    let (cols, rows) = (width as isize, height as isize);
    (0..z.len())
        .map(|i| {
            let (row, col) = ((i / width) as isize, (i % width) as isize);
            let mut low = f64::INFINITY;
            for dr in -1..=1 {
                for dc in -1..=1 {
                    let (rr, cc) = ((row + dr).clamp(0, rows - 1), (col + dc).clamp(0, cols - 1));
                    low = low.min(z[(rr * cols + cc) as usize]);
                }
            }
            z[i] - low > max_drop_m
        })
        .collect()
}

/// An optional illumination layer: the bare total, or the four separable sub-terms with their weights
/// (`shadow`, `saturation`, `map_uncertainty`, `visibility`; a missing weight is 1).
#[derive(Debug, Clone, PartialEq)]
pub enum Illumination {
    Total(Vec<f64>),
    Terms {
        shadow_hazard: Vec<f64>,
        saturation: Vec<f64>,
        map_uncertainty: Vec<f64>,
        visibility: Vec<f64>,
        weights: [f64; 4],
    },
}

#[derive(Debug, Clone, PartialEq)]
pub struct CostmapOptions<'a> {
    pub max_slope_deg: f64,
    pub slip_alpha: f64,
    pub max_drop_m: Option<f64>,
    pub illumination: Option<(&'a Illumination, f64)>,
    pub map_uncertainty: Option<(&'a [f64], f64)>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct Costmap {
    pub cost: Vec<f64>,
    pub passable: Vec<bool>,
    /// Each weighted contribution; they sum to `cost` in this order.
    pub terms: Vec<(&'static str, Vec<f64>)>,
}

/// Per-cell traversal cost and passability over a row-major height grid.
///
/// # Errors
/// A layer whose length differs from the grid.
pub fn slope_costmap(
    z: &[f64],
    width: usize,
    height: usize,
    cell_m: f64,
    o: &CostmapOptions<'_>,
) -> Result<Costmap, String> {
    let slope = lunar_dem::slope_deg_grid(z, width, height, cell_m);
    let mut passable: Vec<bool> = slope.iter().map(|&s| s <= o.max_slope_deg).collect();
    if let Some(drop) = o.max_drop_m {
        for (p, hole) in passable
            .iter_mut()
            .zip(negative_obstacle_mask(z, width, height, drop))
        {
            *p &= !hole;
        }
    }
    let slope_term: Vec<f64> = slope
        .iter()
        .map(|&s| 1.0 + o.slip_alpha * s.min(89.0).to_radians().tan())
        .collect();
    let mut cost = slope_term.clone();
    let mut terms = vec![("slope", slope_term)];
    let check = |name: &str, layer: &[f64]| {
        if layer.len() == z.len() {
            Ok(())
        } else {
            Err(format!(
                "{name} has {} cells, the costmap {}",
                layer.len(),
                z.len()
            ))
        }
    };
    if let Some((illum, gain)) = o.illumination {
        match illum {
            Illumination::Total(t) => {
                check("illumination", t)?;
                let c: Vec<f64> = t.iter().map(|v| gain * v).collect();
                cost.iter_mut().zip(&c).for_each(|(a, b)| *a += b);
                terms.push(("illum", c));
            }
            Illumination::Terms {
                shadow_hazard,
                saturation,
                map_uncertainty,
                visibility,
                weights,
            } => {
                let mut total = vec![0.0; z.len()];
                for (k, (name, layer)) in [
                    ("shadow_hazard", shadow_hazard),
                    ("saturation", saturation),
                    ("map_uncertainty", map_uncertainty),
                    ("visibility", visibility),
                ]
                .into_iter()
                .enumerate()
                {
                    check(name, layer)?;
                    let c: Vec<f64> = layer.iter().map(|v| gain * weights[k] * v).collect();
                    total.iter_mut().zip(&c).for_each(|(a, b)| *a += b);
                    terms.push((name, c));
                }
                cost.iter_mut().zip(&total).for_each(|(a, b)| *a += b);
            }
        }
    }
    if let Some((mu, gain)) = o.map_uncertainty {
        check("map uncertainty", mu)?;
        let c: Vec<f64> = mu.iter().map(|v| gain * v).collect();
        cost.iter_mut().zip(&c).for_each(|(a, b)| *a += b);
        terms.push(("map_unc", c));
    }
    Ok(Costmap {
        cost,
        passable,
        terms,
    })
}

/// A keep-out in the local order frame [m]: a circle, an axis-aligned rectangle, or a polygon.
#[derive(Debug, Clone, PartialEq)]
pub enum Keepout {
    Circle { x: f64, y: f64, r: f64 },
    Rect { x0: f64, y0: f64, x1: f64, y1: f64 },
    Polygon(Vec<(f64, f64)>),
}

/// Even-odd ray-casting point-in-polygon (affine-invariant, so crop-cell coordinates work too).
#[must_use]
pub fn point_in_polygon(x: f64, y: f64, pts: &[(f64, f64)]) -> bool {
    let mut inside = false;
    let mut j = pts.len() - 1;
    for i in 0..pts.len() {
        let ((xi, yi), (xj, yj)) = (pts[i], pts[j]);
        if (yi > y) != (yj > y) && x < (xj - xi) * (y - yi) / (yj - yi) + xi {
            inside = !inside;
        }
        j = i;
    }
    inside
}

impl Keepout {
    /// True if the local-frame point lies inside (the build-on-obstacle check).
    #[must_use]
    pub fn contains(&self, x: f64, y: f64) -> bool {
        match self {
            Keepout::Polygon(p) => point_in_polygon(x, y, p),
            Keepout::Rect { x0, y0, x1, y1 } => {
                x0.min(*x1) <= x && x <= x0.max(*x1) && y0.min(*y1) <= y && y <= y0.max(*y1)
            }
            Keepout::Circle { x: cx, y: cy, r } => (x - cx).powi(2) + (y - cy).powi(2) <= r * r,
        }
    }
}

/// Python `int()`: truncate toward zero.
#[allow(clippy::cast_possible_truncation)]
fn trunc(v: f64) -> i64 {
    v as i64
}

/// Mark cells of a crop (starting at base row `r0`, col `c0`) inside any keep-out impassable. `origin`
/// maps the local frame into DEM metres.
#[allow(
    clippy::cast_possible_wrap,
    clippy::cast_sign_loss,
    clippy::cast_precision_loss,
    clippy::cast_possible_truncation
)]
pub fn apply_keepouts(
    passable: &mut [bool],
    width: usize,
    height: usize,
    cell_m: f64,
    (r0, c0): (usize, usize),
    (ox, oy): (f64, f64),
    keepouts: &[Keepout],
) {
    let (w, h) = (width as i64, height as i64);
    let (r0, c0) = (r0 as f64, c0 as f64);
    let mut block = |r: i64, c: i64| passable[(r * w + c) as usize] = false;
    for k in keepouts {
        match k {
            Keepout::Polygon(pts) => {
                let cells: Vec<(f64, f64)> = pts
                    .iter()
                    .map(|&(px, py)| ((ox + px) / cell_m - c0, (oy + py) / cell_m - r0))
                    .collect();
                let (cmin, cmax) = cells
                    .iter()
                    .fold((f64::INFINITY, f64::NEG_INFINITY), |a, p| {
                        (a.0.min(p.0), a.1.max(p.0))
                    });
                let (rmin, rmax) = cells
                    .iter()
                    .fold((f64::INFINITY, f64::NEG_INFINITY), |a, p| {
                        (a.0.min(p.1), a.1.max(p.1))
                    });
                for r in trunc(rmin).max(0)..(trunc(rmax) + 1).min(h) {
                    for c in trunc(cmin).max(0)..(trunc(cmax) + 1).min(w) {
                        if point_in_polygon(c as f64 + 0.5, r as f64 + 0.5, &cells) {
                            block(r, c);
                        }
                    }
                }
            }
            Keepout::Rect { x0, y0, x1, y1 } => {
                let (xa, xb) = (x0.min(*x1), x0.max(*x1));
                let (ya, yb) = (y0.min(*y1), y0.max(*y1));
                let (clo, chi) = (
                    trunc((ox + xa) / cell_m - c0).max(0),
                    (trunc((ox + xb) / cell_m - c0) + 1).min(w),
                );
                let (rlo, rhi) = (
                    trunc((oy + ya) / cell_m - r0).max(0),
                    (trunc((oy + yb) / cell_m - r0) + 1).min(h),
                );
                for r in rlo..rhi.max(rlo) {
                    for c in clo..chi.max(clo) {
                        block(r, c);
                    }
                }
            }
            Keepout::Circle { x, y, r } => {
                let (kc, kr, rad) = ((ox + x) / cell_m - c0, (oy + y) / cell_m - r0, r / cell_m);
                for rr in trunc(kr - rad).max(0)..(trunc(kr + rad) + 1).min(h) {
                    for cc in trunc(kc - rad).max(0)..(trunc(kc + rad) + 1).min(w) {
                        if (rr as f64 - kr).powi(2) + (cc as f64 - kc).powi(2) <= rad * rad {
                            block(rr, cc);
                        }
                    }
                }
            }
        }
    }
}

/// Crop every layer of an illumination input with `crop` (the same window as the costmap).
pub(crate) fn crop_illumination(
    il: &Illumination,
    crop: &impl Fn(&[f64]) -> Vec<f64>,
) -> Illumination {
    match il {
        Illumination::Total(t) => Illumination::Total(crop(t)),
        Illumination::Terms {
            shadow_hazard,
            saturation,
            map_uncertainty,
            visibility,
            weights,
        } => Illumination::Terms {
            shadow_hazard: crop(shadow_hazard),
            saturation: crop(saturation),
            map_uncertainty: crop(map_uncertainty),
            visibility: crop(visibility),
            weights: *weights,
        },
    }
}
