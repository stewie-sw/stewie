//! Contours (RW-55b5c-3, RW-55b17a): a port of contourpy 1.3.3's serial algorithm (`base_impl.h`) for the case the
//! server uses, an unmasked grid in one chunk with linear interpolation and no quad subdivision: filled between two
//! levels with the `OuterOffset` output (each outer ring with its holes), and lines at one level with the
//! `Separate` output (each line its own points). Every start flag, the boundary and
//! interior walks, the start clearing of the counting pass and the `LOOK_N` / `LOOK_S` hole pairing follow the C++, so
//! the polygons, their order, their start points and their direction are contourpy's. Without a mask, the corner
//! and N-boundary hole starts cannot arise, so their branches are absent.

/// One cache item's flags (contourpy's `MASK_*`).
const Z_LEVEL: u32 = 0b11;
const MIDDLE_SHIFT: u32 = 2;
const BOUNDARY_E: u32 = 1 << 4;
const BOUNDARY_N: u32 = 1 << 5;
const EXISTS_QUAD: u32 = 1 << 6;
const START_E: u32 = 1 << 11;
const START_N: u32 = 1 << 12;
const START_BOUNDARY_E: u32 = 1 << 13;
const START_BOUNDARY_N: u32 = 1 << 14;
const START_BOUNDARY_S: u32 = 1 << 15;
const START_BOUNDARY_W: u32 = 1 << 16;
const ANY_START: u32 =
    START_E | START_N | START_BOUNDARY_E | START_BOUNDARY_N | START_BOUNDARY_S | START_BOUNDARY_W;
const LOOK_N: u32 = 1 << 19;
const LOOK_S: u32 = 1 << 20;

/// A walk's place: the quad, the forward and left steps (in point indices), which level it follows, and whether
/// it runs along the domain boundary.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
struct Loc {
    quad: i64,
    forward: i64,
    left: i64,
    is_upper: bool,
    on_boundary: bool,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Turn {
    Left,
    Right,
    Straight,
}

/// One outer ring and its holes: the points, and each ring's start offset into them (with the end appended).
pub type Polygon = (Vec<[f64; 2]>, Vec<usize>);

struct Gen<'a> {
    xs: &'a [f64],
    ys: &'a [f64],
    z: &'a [f64],
    nx: i64,
    cache: Vec<u32>,
    /// Filled contours (two levels) or lines (one).
    filled: bool,
    lower: f64,
    upper: f64,
    pass: u8,
    points: Vec<[f64; 2]>,
    line_offsets: Vec<usize>,
    outer_offsets: Vec<usize>,
    line_count: usize,
    look_up: Vec<i64>,
}

#[allow(clippy::similar_names)] // contourpy's z_nw, z_ne, z_sw, z_se
impl Gen<'_> {
    #[allow(clippy::cast_sign_loss)] // indices the walk keeps inside the grid
    fn c(&self, i: i64) -> u32 {
        usize::try_from(i)
            .ok()
            .and_then(|i| self.cache.get(i))
            .copied()
            .unwrap_or(0)
    }
    fn set(&mut self, i: i64, f: u32) {
        if let Some(c) = usize::try_from(i).ok().and_then(|i| self.cache.get_mut(i)) {
            *c |= f;
        }
    }
    fn clear(&mut self, i: i64, f: u32) {
        if let Some(c) = usize::try_from(i).ok().and_then(|i| self.cache.get_mut(i)) {
            *c &= !f;
        }
    }
    fn zl(&self, p: i64) -> u32 {
        self.c(p) & Z_LEVEL
    }
    fn middle(&self, q: i64) -> u32 {
        (self.c(q) >> MIDDLE_SHIFT) & Z_LEVEL
    }
    fn boundary_s(&self, q: i64) -> bool {
        self.c(q - self.nx) & BOUNDARY_N != 0
    }
    fn boundary_w(&self, q: i64) -> bool {
        self.c(q - 1) & BOUNDARY_E != 0
    }
    fn zlevel(&self, v: f64) -> u32 {
        if self.filled && v > self.upper {
            2
        } else {
            u32::from(v > self.lower)
        }
    }
    #[allow(clippy::cast_sign_loss, clippy::cast_possible_truncation)] // in-grid point indices
    fn zv(&self, p: i64) -> f64 {
        self.z[p as usize]
    }
    #[allow(clippy::cast_sign_loss, clippy::cast_possible_truncation)] // in-grid point indices
    fn xy(&self, p: i64) -> [f64; 2] {
        let nx = self.nx as usize;
        let p = p as usize;
        [self.xs[p % nx], self.ys[p / nx]]
    }
    fn set_middle(&mut self, q: i64) -> u32 {
        let nx = self.nx;
        let m = 0.25 * (self.zv(q - nx - 1) + self.zv(q - nx) + self.zv(q - 1) + self.zv(q));
        let level = self.zlevel(m);
        self.set(q, level << MIDDLE_SHIFT);
        level
    }
    fn interp(&self, p0: i64, p1: i64, is_upper: bool) -> [f64; 2] {
        let (z0, z1) = (self.zv(p0), self.zv(p1));
        let level = if is_upper { self.upper } else { self.lower };
        let frac = (z1 - level) / (z1 - z0);
        let (a, b) = (self.xy(p0), self.xy(p1));
        [
            a[0] * frac + b[0] * (1.0 - frac),
            a[1] * frac + b[1] * (1.0 - frac),
        ]
    }

    /// contourpy `init_cache_grid` (no mask) then `init_cache_levels_and_starts` (filled, whole domain).
    #[allow(clippy::too_many_lines)] // contourpy's start table
    fn init(&mut self, ny: i64) {
        let nx = self.nx;
        for j in 0..ny {
            for i in 0..nx {
                let mut f = 0;
                if i > 0 && j > 0 {
                    f |= EXISTS_QUAD;
                }
                if (i % (nx - 1) == 0 || i == nx - 1) && j > 0 {
                    f |= BOUNDARY_E;
                }
                if (j % (ny - 1) == 0 || j == ny - 1) && i > 0 {
                    f |= BOUNDARY_N;
                }
                self.cache.push(f);
            }
        }
        for j in 0..ny {
            let (mut z_nw, mut z_sw) = (0, 0);
            for i in 0..nx {
                let quad = i + j * nx;
                let z_se = if j == 0 { 0 } else { self.zl(quad - nx) };
                let z_ne = self.zlevel(self.zv(quad));
                self.set(quad, z_ne);
                if self.c(quad) & EXISTS_QUAD != 0 && !self.filled {
                    self.line_starts(quad, [z_nw, z_ne, z_sw, z_se]);
                } else if self.c(quad) & EXISTS_QUAD != 0 {
                    let (bs, bw) = (self.boundary_s(quad), self.boundary_w(quad));
                    let mut f = 0;
                    let sides = |f: &mut u32| {
                        if bs {
                            *f |= START_BOUNDARY_S;
                        }
                        if bw {
                            *f |= START_BOUNDARY_W;
                        }
                    };
                    match (z_nw << 6) | (z_ne << 4) | (z_sw << 2) | z_se {
                        1 | 2 | 17 | 18 | 34 | 68 | 84..=86 | 102 | 136 | 152 | 153 | 168 | 169 => {
                            if bs {
                                f |= START_BOUNDARY_S;
                            }
                        }
                        4 | 5 | 6 | 8 | 9 | 21 | 22 | 25 | 38 | 72 | 98 | 132 | 145 | 148 | 149
                        | 161 | 162 | 164 | 165 | 166 | 81 | 82 | 88 | 89 => sides(&mut f),
                        10 | 26 | 42 | 64 | 106 | 128 | 144 | 160 | 80 | 90 => {
                            if bw {
                                f |= START_BOUNDARY_W;
                            }
                        }
                        16 | 154 => f |= START_N,
                        20 | 24 => {
                            let m = self.set_middle(quad);
                            sides(&mut f);
                            if m == 0 {
                                f |= START_N;
                            }
                        }
                        32 | 138 => f |= START_E | START_N,
                        33 | 69 | 70 | 100 | 101 | 137 => {
                            if bs {
                                f |= START_BOUNDARY_S;
                            }
                            f |= START_E;
                        }
                        36 => {
                            let m = self.set_middle(quad);
                            sides(&mut f);
                            if m == 0 {
                                f |= START_N;
                            }
                            f |= START_E;
                        }
                        37 | 73 | 97 | 133 => {
                            sides(&mut f);
                            f |= START_E;
                        }
                        40 => {
                            let m = self.set_middle(quad);
                            sides(&mut f);
                            if m < 2 {
                                f |= START_E;
                            }
                            if m == 0 {
                                f |= START_N;
                            }
                        }
                        41 | 104 | 105 => {
                            let m = self.set_middle(quad);
                            sides(&mut f);
                            if m < 2 {
                                f |= START_E;
                            }
                        }
                        65 | 66 | 129 => {
                            let m = self.set_middle(quad);
                            sides(&mut f);
                            if m > 0 {
                                f |= START_E;
                            }
                        }
                        74 | 96 => {
                            if bw {
                                f |= START_BOUNDARY_W;
                            }
                            f |= START_E;
                        }
                        130 => {
                            let m = self.set_middle(quad);
                            sides(&mut f);
                            if m > 0 {
                                f |= START_E;
                            }
                            if m == 2 {
                                f |= START_N;
                            }
                        }
                        134 => {
                            let m = self.set_middle(quad);
                            sides(&mut f);
                            if m == 2 {
                                f |= START_N;
                            }
                            f |= START_E;
                        }
                        146 | 150 => {
                            let m = self.set_middle(quad);
                            sides(&mut f);
                            if m == 2 {
                                f |= START_N;
                            }
                        }
                        _ => {}
                    }
                    self.set(quad, f);
                }
                z_nw = z_ne;
                z_sw = z_se;
            }
        }
    }

    /// contourpy `init_cache_levels_and_starts`' line starts of one quad from its corners' levels (0 or 1).
    fn line_starts(&mut self, quad: i64, [z_nw, z_ne, z_sw, z_se]: [u32; 4]) {
        let c = self.c(quad);
        let (be, bn) = (c & BOUNDARY_E != 0, c & BOUNDARY_N != 0);
        let (bs, bw) = (self.boundary_s(quad), self.boundary_w(quad));
        let mut f = 0;
        match (z_nw << 3) | (z_ne << 2) | (z_sw << 1) | z_se {
            1 | 3 if be => f |= START_BOUNDARY_E,
            2 | 10 | 14 if bs => f |= START_BOUNDARY_S,
            4 => {
                if bn {
                    f |= START_BOUNDARY_N;
                } else if !be {
                    f |= START_N;
                }
            }
            5 | 7 if bn => f |= START_BOUNDARY_N,
            6 => {
                let m = self.set_middle(quad);
                if bn {
                    f |= START_BOUNDARY_N;
                } else if !be && m == 0 {
                    f |= START_N;
                }
                if bs {
                    f |= START_BOUNDARY_S;
                }
            }
            8 | 12 | 13 if bw => f |= START_BOUNDARY_W,
            9 => {
                let m = self.set_middle(quad);
                if be {
                    f |= START_BOUNDARY_E;
                } else if !bn && m == 1 {
                    f |= START_E;
                }
                if bw {
                    f |= START_BOUNDARY_W;
                }
            }
            11 => {
                if be {
                    f |= START_BOUNDARY_E;
                } else if !bn {
                    f |= START_E;
                }
            }
            _ => {}
        }
        self.set(quad, f);
    }

    /// contourpy `set_look_flags`: mark the hole start, then walk S to where the outer that encloses it passes.
    fn set_look_flags(&mut self, hole_start: i64) {
        self.set(hole_start, LOOK_S);
        let mut quad = hole_start;
        loop {
            if self.boundary_s(quad) || self.zl(quad - self.nx) != 1 {
                self.set(quad, LOOK_N);
                return;
            }
            quad -= self.nx;
        }
    }

    /// contourpy `move_to_next_boundary_edge`, the E/S/W/N edges only.
    fn next_boundary_edge(&self, quad: &mut i64, forward: &mut i64, left: &mut i64) {
        let nx = self.nx;
        let mut edge: i64 = if *forward > 0 {
            if *forward == nx {
                1
            } else {
                *quad -= nx;
                3
            }
        } else if *forward == -nx {
            *quad -= nx + 1;
            5
        } else {
            *quad -= 1;
            7
        };
        loop {
            match edge {
                1 if self.c(*quad) & BOUNDARY_N != 0 => {
                    (*forward, *left) = (-1, -nx);
                    return;
                }
                3 if self.c(*quad + nx) & BOUNDARY_E != 0 => {
                    *quad += nx;
                    (*forward, *left) = (nx, -1);
                    return;
                }
                5 if self.c(*quad + 1) & BOUNDARY_N != 0 => {
                    *quad += nx + 1;
                    (*forward, *left) = (1, nx);
                    return;
                }
                7 if self.c(*quad) & BOUNDARY_E != 0 => {
                    *quad += 1;
                    (*forward, *left) = (-nx, 1);
                    return;
                }
                _ => {}
            }
            edge = (edge + 2) % 8;
        }
    }

    /// contourpy `follow_boundary`.
    fn follow_boundary(&mut self, loc: &mut Loc, start: &Loc, count: &mut usize) -> bool {
        let nx = self.nx;
        let (mut quad, mut forward, mut left) = (loc.quad, loc.forward, loc.left);
        let mut start_point = if forward > 0 {
            if forward == nx {
                quad - nx
            } else {
                quad - nx - 1
            }
        } else if forward == -nx {
            quad - 1
        } else {
            quad
        };
        let mut end_point = start_point + forward;
        let mut end_z = self.zl(end_point);
        *count += 1;
        if self.pass > 0 {
            let p = if self.zl(start_point) == 1 {
                self.xy(start_point)
            } else {
                self.interp(start_point, end_point, loc.is_upper)
            };
            self.points.push(p);
        }
        let mut finished = false;
        loop {
            if quad == start.quad && forward == start.forward && left == start.left {
                if start.on_boundary && *count > 1 {
                    finished = true;
                    break;
                }
            } else if self.pass == 0 {
                if left == nx {
                    self.clear(quad, START_BOUNDARY_S);
                } else if forward == -nx {
                    self.clear(quad, START_BOUNDARY_W);
                }
            }
            if end_z != 1 {
                loc.is_upper = end_z == 2;
                (forward, left) = (left, -forward);
                break;
            }
            *count += 1;
            if self.pass > 0 {
                self.points.push(self.xy(end_point));
                if self.c(quad) & LOOK_N != 0 && (left == nx || left == nx + 1 || forward == nx + 1)
                {
                    self.look_up.push(quad);
                }
            }
            self.next_boundary_edge(&mut quad, &mut forward, &mut left);
            start_point = end_point;
            end_point = start_point + forward;
            end_z = self.zl(end_point);
        }
        (loc.quad, loc.forward, loc.left) = (quad, forward, left);
        finished
    }

    /// contourpy `follow_interior`, for a grid whose every interior quad exists.
    #[allow(clippy::too_many_lines)] // one walk, as the C++
    fn follow_interior(&mut self, loc: &mut Loc, start: &Loc, count: &mut usize) -> bool {
        let nx = self.nx;
        let (mut quad, mut forward, mut left, is_upper) =
            (loc.quad, loc.forward, loc.left, loc.is_upper);
        let mut left_point = if forward > 0 {
            if forward == nx {
                quad - nx - 1
            } else {
                quad - 1
            }
        } else if forward == -nx {
            quad
        } else {
            quad - nx
        };
        let mut right_point = left_point - left;
        let mut finished = false;
        loop {
            if self.pass > 0 {
                let p = self.interp(left_point, right_point, is_upper);
                self.points.push(p);
            }
            *count += 1;
            if quad == start.quad
                && forward == start.forward
                && left == start.left
                && is_upper == start.is_upper
                && !start.on_boundary
                && *count > 1
            {
                finished = true;
                break;
            }
            let (opp_l, opp_r) = (left_point + forward, right_point + forward);
            let (z_l, z_r) = (self.zl(opp_l), self.zl(opp_r));
            let z_test = if is_upper { 2 } else { 0 };
            let mut turn = Turn::Right;
            if self.c(quad) & EXISTS_QUAD != 0 {
                if z_l == z_test {
                    if z_r == z_test || self.middle(quad) == z_test {
                        turn = Turn::Left;
                    }
                } else if z_r == z_test {
                    turn = Turn::Straight;
                }
            }
            if self.pass == 0
                && !(quad == start.quad && forward == start.forward && left == start.left)
            {
                let cq = self.c(quad);
                let z_ne = self.zl(quad);
                let z_nw = self.zl(quad - 1);
                if cq & START_E != 0
                    && forward == -1
                    && left == -nx
                    && turn == Turn::Right
                    && (if is_upper { z_ne > 0 } else { z_ne < 2 })
                {
                    self.clear(quad, START_E);
                    if !self.filled && quad < start.quad {
                        // a line: contourpy stops counting where an earlier start already walked this strip
                        break;
                    }
                } else if cq & START_N != 0
                    && forward == -nx
                    && left == 1
                    && turn == Turn::Left
                    && (if is_upper { z_nw > 0 } else { z_nw < 2 })
                {
                    self.clear(quad, START_N);
                    if !self.filled && quad < start.quad {
                        break;
                    }
                }
            }
            match turn {
                Turn::Left => {
                    (forward, left) = (left, -forward);
                    right_point = opp_l;
                }
                Turn::Right => {
                    (forward, left) = (-left, forward);
                    left_point = opp_r;
                }
                Turn::Straight => {
                    left_point = opp_l;
                    right_point = opp_r;
                }
            }
            if self.pass > 0 && self.c(quad) & LOOK_N != 0 && forward == 1 {
                let z_ne = self.zl(quad);
                if self.c(quad) & LOOK_S == 0 || (if is_upper { z_ne < 2 } else { z_ne > 0 }) {
                    self.look_up.push(quad);
                }
            }
            let reached = if forward > 0 {
                let f = if forward == 1 { BOUNDARY_E } else { BOUNDARY_N };
                self.c(quad) & f != 0
            } else if forward == -1 {
                self.boundary_w(quad)
            } else {
                self.boundary_s(quad)
            };
            if reached {
                (forward, left) = (left, -forward);
                if !self.filled {
                    // a line ends on the boundary edge it reaches
                    *count += 1;
                    if self.pass > 0 {
                        let p = self.interp(left_point, right_point, false);
                        self.points.push(p);
                    }
                }
                break;
            }
            quad += forward;
        }
        (loc.quad, loc.forward, loc.left, loc.is_upper) = (quad, forward, left, is_upper);
        finished
    }

    /// contourpy `line`: one line from a start. The counting pass only clears the interior starts a strip passes
    /// (contourpy's counts size its buffers, which a `Vec` does not need), so the output pass draws each line once.
    fn line(&mut self, start: Loc) {
        let mut loc = start;
        let first = self.points.len();
        self.follow_interior(&mut loc, &start, &mut 0);
        if self.pass > 0 {
            self.line_offsets.push(first);
        }
    }

    /// contourpy `closed_line`: alternate boundary and interior walks until back at the start.
    fn closed_line(&mut self, start: Loc, hole: bool) {
        let mut loc = start;
        let mut count = 0;
        if hole && self.pass == 0 {
            self.set_look_flags(start.quad);
        }
        loop {
            let done = if loc.on_boundary {
                self.follow_boundary(&mut loc, &start, &mut count)
            } else {
                self.follow_interior(&mut loc, &start, &mut count)
            };
            loc.on_boundary = !loc.on_boundary;
            if done {
                break;
            }
        }
        if self.pass > 0 {
            self.line_offsets.push(self.points.len() - count);
            if !hole {
                self.outer_offsets.push(self.line_count);
            }
        }
        self.line_count += 1;
    }

    /// contourpy `closed_line_wrapper`: in the output pass, an outer is followed by the holes its walk looked up.
    fn closed_line_wrapper(&mut self, start: Loc, hole: bool) -> Result<(), String> {
        if self.pass == 0 {
            self.closed_line(start, hole);
            return Ok(());
        }
        self.look_up.clear();
        self.closed_line(start, hole);
        let mut i = 0;
        while i < self.look_up.len() {
            let mut quad = self.look_up[i];
            while self.c(quad) & LOOK_S == 0 {
                quad += self.nx;
            }
            if self.c(quad) & START_E == 0 {
                return Err("contour: a hole start other than START_E needs a mask".to_owned());
            }
            let is_upper = self.zl(quad) > 0;
            self.closed_line(
                Loc {
                    quad,
                    forward: -1,
                    left: -self.nx,
                    is_upper,
                    on_boundary: false,
                },
                true,
            );
            i += 1;
        }
        Ok(())
    }
}

/// Filled contours of `z` (`ys.len()` rows of `xs.len()` points, row-major) for `lower < z <= upper`, as
/// contourpy's `filled(lower, upper)` with `fill_type="OuterOffset"`: per outer ring, its points and its rings'
/// offsets (holes after the outer).
///
/// # Errors
/// A grid smaller than 2 x 2 or a `z` of another size.
#[allow(clippy::cast_possible_wrap)] // grid sizes
pub fn filled(
    xs: &[f64],
    ys: &[f64],
    z: &[f64],
    lower: f64,
    upper: f64,
) -> Result<Vec<Polygon>, String> {
    let (nx, ny) = (xs.len(), ys.len());
    if nx < 2 || ny < 2 || z.len() != nx * ny {
        return Err(format!(
            "contour: a {ny} x {nx} grid needs at least 2 x 2 points and {} z values (got {})",
            nx * ny,
            z.len()
        ));
    }
    let mut g = Gen {
        xs,
        ys,
        z,
        nx: nx as i64,
        cache: Vec::with_capacity(nx * ny),
        filled: true,
        lower,
        upper,
        pass: 0,
        points: Vec::new(),
        line_offsets: Vec::new(),
        outer_offsets: Vec::new(),
        line_count: 0,
        look_up: Vec::new(),
    };
    g.init(ny as i64);
    let n = g.nx;
    for pass in 0..2 {
        g.pass = pass;
        g.line_count = 0;
        let ignore_holes = pass == 1;
        for quad in 0..(nx * ny) as i64 {
            if g.c(quad) & ANY_START == 0 {
                continue;
            }
            // each flag is re-read: a walk from an earlier start in this quad may have cleared it
            if g.c(quad) & START_BOUNDARY_S != 0 {
                let is_upper = g.zl(quad - n - 1) == 2;
                g.closed_line_wrapper(
                    Loc {
                        quad,
                        forward: 1,
                        left: n,
                        is_upper,
                        on_boundary: true,
                    },
                    false,
                )?;
            }
            if g.c(quad) & START_BOUNDARY_W != 0 {
                let is_upper = g.zl(quad - 1) == 2;
                g.closed_line_wrapper(
                    Loc {
                        quad,
                        forward: -n,
                        left: 1,
                        is_upper,
                        on_boundary: true,
                    },
                    false,
                )?;
            }
            if g.c(quad) & START_N != 0 {
                let is_upper = g.zl(quad - 1) > 0;
                g.closed_line_wrapper(
                    Loc {
                        quad,
                        forward: -n,
                        left: 1,
                        is_upper,
                        on_boundary: false,
                    },
                    false,
                )?;
            }
            if ignore_holes {
                continue;
            }
            if g.c(quad) & START_E != 0 {
                let is_upper = g.zl(quad) > 0;
                g.closed_line_wrapper(
                    Loc {
                        quad,
                        forward: -1,
                        left: -n,
                        is_upper,
                        on_boundary: false,
                    },
                    true,
                )?;
            }
        }
    }
    g.line_offsets.push(g.points.len());
    g.outer_offsets.push(g.line_count);
    let mut out = Vec::with_capacity(g.outer_offsets.len().saturating_sub(1));
    for w in g.outer_offsets.windows(2) {
        let (p0, p1) = (g.line_offsets[w[0]], g.line_offsets[w[1]]);
        let offsets = g.line_offsets[w[0]..=w[1]].iter().map(|o| o - p0).collect();
        out.push((g.points[p0..p1].to_vec(), offsets));
    }
    Ok(out)
}

/// Contour lines of `z` (`ys.len()` rows of `xs.len()` points, row-major) at `level`, as contourpy's `lines(level)`
/// with `line_type="Separate"`: each line its own points, in contourpy's order and direction; a closed loop ends on
/// its first point.
///
/// # Errors
/// A grid smaller than 2 x 2 or a `z` of another size.
#[allow(clippy::cast_possible_wrap)] // grid sizes
pub fn lines(xs: &[f64], ys: &[f64], z: &[f64], level: f64) -> Result<Vec<Vec<[f64; 2]>>, String> {
    let (nx, ny) = (xs.len(), ys.len());
    if nx < 2 || ny < 2 || z.len() != nx * ny {
        return Err(format!(
            "contour: a {ny} x {nx} grid needs at least 2 x 2 points and {} z values (got {})",
            nx * ny,
            z.len()
        ));
    }
    let mut g = Gen {
        xs,
        ys,
        z,
        nx: nx as i64,
        cache: Vec::with_capacity(nx * ny),
        filled: false,
        lower: level,
        upper: level,
        pass: 0,
        points: Vec::new(),
        line_offsets: Vec::new(),
        outer_offsets: Vec::new(),
        line_count: 0,
        look_up: Vec::new(),
    };
    g.init(ny as i64);
    let n = g.nx;
    let at = |quad, forward, left, on_boundary| Loc {
        quad,
        forward,
        left,
        is_upper: false,
        on_boundary,
    };
    for pass in 0..2 {
        g.pass = pass;
        for quad in 0..(nx * ny) as i64 {
            if g.c(quad) & ANY_START == 0 {
                continue;
            }
            // each flag is re-read: a walk from an earlier start may have cleared it
            for (flag, forward, left, on_boundary) in [
                (START_BOUNDARY_S, n, -1, true),
                (START_BOUNDARY_W, 1, n, true),
                (START_BOUNDARY_E, -1, -n, true),
                (START_BOUNDARY_N, -n, 1, true),
                (START_E, -1, -n, false),
                (START_N, -n, 1, false),
            ] {
                if g.c(quad) & flag != 0 {
                    g.line(at(quad, forward, left, on_boundary));
                }
            }
        }
    }
    g.line_offsets.push(g.points.len());
    Ok(g.line_offsets
        .windows(2)
        .map(|w| g.points[w[0]..w[1]].to_vec())
        .collect())
}
