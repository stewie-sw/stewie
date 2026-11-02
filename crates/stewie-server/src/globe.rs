//! The globe drapes (RW-55b17b; Python `gis_layers.render_globe`, `_tile_geo`, `_reproject`): each analysis layer of
//! a site's tile resampled from the tile's south-polar stereographic frame onto a north-up selenographic lon/lat
//! grid by nearest neighbour, transparent outside the tile's true footprint, with the geographic bounding box the
//! globe drapes it over. The static kinds are cached in memory (FIFO, as the Python's); the traffic and
//! changed-terrain drapes change as runs fold and are never cached.

use std::collections::VecDeque;
use std::sync::{Arc, Mutex};

use lunar_frames::{LatLon, PolarStereographic};
use serde_json::{Map, Value, json};

/// The selenographic bounding box of a tile-frame extent.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Bbox {
    pub south: f64,
    pub north: f64,
    pub west: f64,
    pub east: f64,
}

impl Bbox {
    #[must_use]
    pub fn to_json(&self) -> Map<String, Value> {
        let Value::Object(m) =
            json!({"south": self.south, "north": self.north, "west": self.west, "east": self.east})
        else {
            unreachable!("a json object literal")
        };
        m
    }
}

/// Python `_geographic_bbox_of_extent`: the extent's boundary ring (64 points a side, the projection bows the
/// edges) inverted to lon/lat, its min/max box (off-pole tiles; one that encloses the pole would need a split box).
#[must_use]
pub fn geographic_bbox(proj: &PolarStereographic, (x0, y0, x1, y1): (f64, f64, f64, f64)) -> Bbox {
    let t = crate::dem_routes::linspace(0.0, 1.0, 64);
    let ring = t
        .iter()
        .map(|t| (x0 + (x1 - x0) * t, y0))
        .chain(t.iter().map(|t| (x1, y0 + (y1 - y0) * t)))
        .chain(t.iter().map(|t| (x1 - (x1 - x0) * t, y1)))
        .chain(t.iter().map(|t| (x0, y1 - (y1 - y0) * t)));
    let mut b = Bbox {
        south: f64::INFINITY,
        north: f64::NEG_INFINITY,
        west: f64::INFINITY,
        east: f64::NEG_INFINITY,
    };
    for (x, y) in ring {
        let ll = proj.inverse(x, y);
        b.south = b.south.min(ll.lat_deg);
        b.north = b.north.max(ll.lat_deg);
        b.west = b.west.min(ll.lon_deg);
        b.east = b.east.max(ll.lon_deg);
    }
    b
}

/// A geographic drape: north-up RGBA, its width and height, and its box.
pub type Drape = (Vec<u8>, usize, usize, Bbox);

/// Python `_reproject`: resample `src` (`sw` x `sh` RGBA, north-up over the tile-frame `extent`) onto a lon/lat grid
/// `out_px` rows high and as wide as the box's aspect at its mid latitude (64..=4096), nearest neighbour, zero outside
/// the source.
#[must_use]
#[allow(
    clippy::cast_possible_truncation,
    clippy::cast_sign_loss,
    clippy::cast_precision_loss,
    clippy::many_single_char_names,
    clippy::manual_midpoint
)] // pixel indices; the Python's H, W, b; its (south + north) / 2, bit for bit
pub fn reproject(
    proj: &PolarStereographic,
    src: &[u8],
    (sw, sh): (usize, usize),
    extent: (f64, f64, f64, f64),
    out_px: usize,
) -> Drape {
    let (x0, y0, x1, y1) = extent;
    let b = geographic_bbox(proj, extent);
    let h = out_px;
    let aspect = (out_px as f64) * (b.east - b.west) / (b.north - b.south).max(1e-9)
        * ((b.south + b.north) / 2.0).to_radians().cos();
    // int() truncates toward zero
    let w = (aspect.trunc() as i64).clamp(64, 4096) as usize;
    let lons = crate::dem_routes::linspace(b.west, b.east, w);
    let lats = crate::dem_routes::linspace(b.north, b.south, h);
    let mut out = vec![0u8; w * h * 4];
    let (cmax, rmax) = ((sw - 1) as f64, (sh - 1) as f64);
    for (r, &lat) in lats.iter().enumerate() {
        for (c, &lon) in lons.iter().enumerate() {
            let Ok((x, y)) = proj.forward(LatLon {
                lat_deg: lat,
                lon_deg: lon,
            }) else {
                continue;
            };
            let col = (x - x0) / (x1 - x0) * cmax;
            let row = (y1 - y) / (y1 - y0) * rmax;
            if !((0.0..=cmax).contains(&col) && (0.0..=rmax).contains(&row)) {
                continue;
            }
            let (ci, ri) = (
                col.round_ties_even() as usize,
                row.round_ties_even() as usize,
            );
            let s = (ri * sw + ci) * 4;
            out[(r * w + c) * 4..(r * w + c) * 4 + 4].copy_from_slice(&src[s..s + 4]);
        }
    }
    (out, w, h, b)
}

/// The site reference grid (#54): site-frame lines every 100 m (alpha 80) and 500 m (alpha 170) over the 10 km tile on
/// a 1000-pixel raster, in the operator's colour.
#[must_use]
#[allow(
    clippy::cast_possible_truncation,
    clippy::cast_sign_loss,
    clippy::cast_precision_loss,
    clippy::many_single_char_names
)] // pixel indices; the Python's r, g, b, i, a
pub fn grid_rgba(color: &str) -> Vec<u8> {
    const N: usize = 1000;
    let ch = |k: usize| u8::from_str_radix(color.get(k..k + 2).unwrap_or(""), 16).ok();
    let [r, g, b] = match (ch(0), ch(2), ch(4)) {
        (Some(r), Some(g), Some(b)) => [r, g, b],
        _ => [0x39, 0xff, 0x14],
    };
    let mut px = vec![0u8; N * N * 4];
    for m in (0..=10_000).step_by(100) {
        let i = ((f64::from(m) / 10_000.0 * N as f64) as usize).min(N - 1);
        let a = if m % 500 == 0 { 170 } else { 80 };
        for k in 0..N {
            for at in [(i * N + k) * 4, (k * N + i) * 4] {
                px[at..at + 3].copy_from_slice(&[r, g, b]);
                px[at + 3] = px[at + 3].max(a);
            }
        }
    }
    px
}

/// A rendered drape and its box (with the live drapes' extra fields).
pub type Rendered = Arc<(Drape, Map<String, Value>)>;

/// A bounded FIFO cache of rendered static drapes (Python `_GLOBE_CACHE`, 256 entries).
#[derive(Debug, Default)]
pub struct Cache {
    entries: Mutex<VecDeque<(String, Rendered)>>,
}

impl Cache {
    const MAX: usize = 256;

    pub fn get(&self, key: &str) -> Option<Rendered> {
        let e = self
            .entries
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        e.iter().find(|(k, _)| k == key).map(|(_, v)| v.clone())
    }

    pub fn put(&self, key: String, v: Rendered) {
        let mut e = self
            .entries
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        if !e.iter().any(|(k, _)| *k == key) {
            e.push_back((key, v));
        }
        while e.len() > Self::MAX {
            e.pop_front();
        }
    }
}

#[cfg(test)]
mod tests {
    use super::grid_rgba;

    #[test]
    fn the_grid_draws_major_and_minor_lines_in_the_chosen_colour() {
        let px = grid_rgba("ff0000");
        // row 0 is a major (m = 0) line, row 10 a minor one; a cell between lines is empty
        assert_eq!(&px[0..4], &[255, 0, 0, 170]);
        assert_eq!(
            &px[(10 * 1000 + 3) * 4..(10 * 1000 + 3) * 4 + 4],
            &[255, 0, 0, 80]
        );
        assert_eq!(
            &px[(5 * 1000 + 3) * 4..(5 * 1000 + 3) * 4 + 4],
            &[0, 0, 0, 0]
        );
    }
}
