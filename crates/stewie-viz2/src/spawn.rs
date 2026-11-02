//! [REQ:AS-15] Where a session starts when the operator chose no section (Python
//! `Viz2Runtime._flattest_interior_spawn`): the flattest interior spot of the real DEM, not the tile's blind centre,
//! which on a crater tile is often a wall steep enough to entrap the rover at t = 0. The slope is numpy's `gradient`
//! of the base height, smoothed by scipy's 9-cell `uniform_filter` (edges `nearest`), with a 6% interior margin.

/// numpy `gradient(h, cell)` along one axis of a row-major `rows x cols` grid: central differences inside,
/// one-sided first-order differences at the edges.
fn gradient(h: &[f64], rows: usize, cols: usize, cell: f64, along_rows: bool) -> Vec<f64> {
    let at = |r: usize, c: usize| h[r * cols + c];
    let n = if along_rows { rows } else { cols };
    let mut out = vec![0.0; h.len()];
    for r in 0..rows {
        for c in 0..cols {
            let i = if along_rows { r } else { c };
            let get = |k: usize| if along_rows { at(k, c) } else { at(r, k) };
            out[r * cols + c] = if n < 2 {
                0.0
            } else if i == 0 {
                (get(1) - get(0)) / cell
            } else if i == n - 1 {
                (get(n - 1) - get(n - 2)) / cell
            } else {
                (get(i + 1) - get(i - 1)) / (2.0 * cell)
            };
        }
    }
    out
}

/// scipy `uniform_filter1d(line, size, mode="nearest")` in its own running-sum form (the rounding the argmin sees).
#[must_use]
#[allow(clippy::cast_precision_loss)] // a 9-cell window
pub fn uniform_1d(line: &[f64], size: usize) -> Vec<f64> {
    let n = line.len();
    let left = size / 2;
    let ext = |k: usize| line[k.saturating_sub(left).min(n - 1)];
    let sz = size as f64;
    // the raw window sum, moved by (entering - leaving), divided only on output (scipy 1.17's rounding)
    let mut tmp: f64 = (0..size).map(ext).fold(0.0, |a, x| a + x);
    let mut out = Vec::with_capacity(n);
    out.push(tmp / sz);
    for l in 1..n {
        tmp += ext(l + size - 1) - ext(l - 1);
        out.push(tmp / sz);
    }
    out
}

/// scipy `uniform_filter(a, size, mode="nearest")`: the 1-D filter along rows (axis 0), then along columns.
fn uniform_filter(a: &[f64], rows: usize, cols: usize, size: usize) -> Vec<f64> {
    let mut t = vec![0.0; a.len()];
    for c in 0..cols {
        let col: Vec<f64> = (0..rows).map(|r| a[r * cols + c]).collect();
        for (r, v) in uniform_1d(&col, size).into_iter().enumerate() {
            t[r * cols + c] = v;
        }
    }
    t.chunks(cols)
        .flat_map(|row| uniform_1d(row, size))
        .collect()
}

/// The flattest interior base cell `(row, col)` of a row-major base height grid: the region-mean `tan(slope)`
/// minimum, the first in row-major order, keeping a `round(0.06 * min(rows, cols))` margin (at least one cell).
#[must_use]
#[allow(
    clippy::cast_precision_loss,
    clippy::cast_possible_truncation,
    clippy::cast_sign_loss
)] // grid sizes
pub fn flattest_interior_rc(h: &[f64], rows: usize, cols: usize, cell_m: f64) -> (usize, usize) {
    let gy = gradient(h, rows, cols, cell_m, true);
    let gx = gradient(h, rows, cols, cell_m, false);
    let slope: Vec<f64> = gx.iter().zip(&gy).map(|(x, y)| x.hypot(*y)).collect();
    let mut sm = uniform_filter(&slope, rows, cols, 9);
    let m = ((0.06 * rows.min(cols) as f64).round_ties_even() as usize).max(1);
    let big = sm.iter().copied().fold(f64::NEG_INFINITY, f64::max) + 1.0;
    for r in 0..rows {
        for c in 0..cols {
            if r < m || r + m >= rows || c < m || c + m >= cols {
                sm[r * cols + c] = big;
            }
        }
    }
    let (i, _) =
        sm.iter().enumerate().fold(
            (0, f64::INFINITY),
            |best, (i, &v)| if v < best.1 { (i, v) } else { best },
        );
    (i / cols, i % cols)
}

#[cfg(test)]
mod tests {
    #[test]
    fn a_tie_takes_the_first_interior_cell_as_numpy_argmin() {
        // SYNTHETIC flat grid (labelled): every slope is zero, so the first interior cell in row-major order wins
        assert_eq!(
            super::flattest_interior_rc(&[7.0; 400], 20, 20, 1.0),
            (1, 1)
        );
    }
}
