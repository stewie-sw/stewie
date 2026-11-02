//! Value rasters as tiled `GeoTIFF` (RW-55b20b; Python `lode.gis_export.value_raster_cog`, `_array_to_cog`, which
//! write through rasterio/GDAL 3.10): one band north-up on the site DEM's grid in `IAU_2015:30135`, 256-pixel
//! tiles, deflate, with overviews at 2, 4, 8 and 16. The overviews follow GDAL's arithmetic so a client reads the
//! same pyramid: a continuous `float32` band is averaged level from the level above, four output pixels at a time as
//! `((a00 + a10) + (a01 + a11)) * 0.25` and the row's remainder as `(((a00 + a01) + a10) + a11) * 0.25`, in `f32`;
//! a class band takes each block's top-left value. The georeferencing tags are GDAL's encoding of the CRS.

use std::io::Write as _;

/// GDAL's `GeoKeyDirectory` for `IAU_2015:30135` (the Moon 2015 sphere, south polar stereographic).
const GEO_KEYS: [u16; 84] = [
    1, 1, 0, 20, 1024, 0, 1, 1, 1025, 0, 1, 1, 1026, 34737, 46, 0, 2048, 0, 1, 32767, 2049, 34737,
    134, 46, 2050, 0, 1, 32767, 2054, 0, 1, 9102, 2056, 0, 1, 32767, 2057, 34736, 1, 5, 2058,
    34736, 1, 6, 2061, 34736, 1, 7, 3072, 0, 1, 32767, 3074, 0, 1, 32767, 3075, 0, 1, 15, 3076, 0,
    1, 9001, 3081, 34736, 1, 0, 3082, 34736, 1, 3, 3083, 34736, 1, 4, 3092, 34736, 1, 2, 3095,
    34736, 1, 1,
];
/// Its `GeoDoubleParams`: origin latitude, central meridian, scale, false easting and northing, the sphere's axes.
const GEO_DOUBLES: [f64; 8] = [-90.0, 0.0, 1.0, 0.0, 0.0, 1_737_400.0, 1_737_400.0, 0.0];
/// Its `GeoAsciiParams` (the citations, NUL-terminated).
const GEO_ASCII: &str = "Moon (2015) - Sphere / Ocentric / South Polar|GCS Name = Moon (2015) - Sphere / Ocentric|Datum = \
                         Moon (2015) - Sphere|Ellipsoid = Moon (2015) - Sphere|Primem = Reference Meridian||\0";
const TILE: usize = 256;
const LEVELS: [usize; 4] = [2, 4, 8, 16];

/// One band.
#[derive(Debug, Clone, PartialEq)]
pub enum Band {
    /// A continuous field (averaged overviews).
    F32(Vec<f32>),
    /// Integer classes (nearest overviews).
    I32(Vec<i32>),
}

impl Band {
    /// The band halved in each axis, as GDAL builds the next overview.
    fn halve(&self, w: usize, h: usize) -> Self {
        let (w2, h2) = (w / 2, h / 2);
        match self {
            Self::F32(a) => {
                let chunk = w2 / 4 * 4;
                let mut out = Vec::with_capacity(w2 * h2);
                for y in 0..h2 {
                    let (r0, r1) = (2 * y * w, (2 * y + 1) * w);
                    for x in 0..w2 {
                        let (a00, a01, a10, a11) = (
                            a[r0 + 2 * x],
                            a[r0 + 2 * x + 1],
                            a[r1 + 2 * x],
                            a[r1 + 2 * x + 1],
                        );
                        out.push(if x < chunk {
                            ((a00 + a10) + (a01 + a11)) * 0.25
                        } else {
                            (((a00 + a01) + a10) + a11) * 0.25
                        });
                    }
                }
                Self::F32(out)
            }
            Self::I32(a) => Self::I32(
                (0..h2)
                    .flat_map(|y| (0..w2).map(move |x| a[2 * y * w + 2 * x]))
                    .collect(),
            ),
        }
    }

    /// The tiles of a `w` x `h` band, row-major, each 256 x 256 (zero beyond the edge), little-endian.
    fn tiles(&self, w: usize, h: usize) -> Vec<Vec<u8>> {
        let px = |i: usize| match self {
            Self::F32(a) => a[i].to_le_bytes(),
            Self::I32(a) => a[i].to_le_bytes(),
        };
        let mut out = Vec::new();
        for ty in 0..h.div_ceil(TILE) {
            for tx in 0..w.div_ceil(TILE) {
                let mut t = vec![0u8; TILE * TILE * 4];
                for y in 0..TILE.min(h - ty * TILE) {
                    for x in 0..TILE.min(w - tx * TILE) {
                        let at = (y * TILE + x) * 4;
                        t[at..at + 4].copy_from_slice(&px((ty * TILE + y) * w + tx * TILE + x));
                    }
                }
                out.push(t);
            }
        }
        out
    }
}

/// The band and its overviews at 2, 4, 8 and 16, each from the level above, with their sizes.
#[must_use]
pub fn pyramid(band: Band, w: usize, h: usize) -> Vec<(Band, usize, usize)> {
    let mut levels = vec![(band, w, h)];
    for _ in LEVELS {
        let (b, lw, lh) = &levels[levels.len() - 1];
        let next = b.halve(*lw, *lh);
        let (nw, nh) = (lw / 2, lh / 2);
        levels.push((next, nw, nh));
    }
    levels
}

/// One IFD entry: tag, type, count, value bytes.
struct Entry(u16, u16, u32, Vec<u8>);

fn shorts(v: &[u16]) -> Vec<u8> {
    v.iter().flat_map(|x| x.to_le_bytes()).collect()
}
fn longs(v: &[u32]) -> Vec<u8> {
    v.iter().flat_map(|x| x.to_le_bytes()).collect()
}
fn doubles(v: &[f64]) -> Vec<u8> {
    v.iter().flat_map(|x| x.to_le_bytes()).collect()
}
fn ascii(s: &str) -> Entry {
    let b = s.as_bytes().to_vec();
    #[allow(clippy::cast_possible_truncation)] // a short tag string
    Entry(0, 2, b.len() as u32, b)
}

/// Where a raster sits: the west edge, the north edge and the cell [m] of the tile frame.
#[derive(Debug, Clone, Copy)]
pub struct Georef {
    pub x0: f64,
    pub y1: f64,
    pub cell_m: f64,
}

/// The tiled `GeoTIFF` of a `w` x `h` band and its overviews; `nodata` the `GDAL_NODATA` text, when there is one.
///
/// # Errors
/// A band whose sides do not halve evenly through the pyramid (every imported site's 2000 x 2000 tile does), or a
/// file too large for a classic TIFF.
#[allow(
    clippy::too_many_lines,
    clippy::cast_possible_truncation,
    clippy::many_single_char_names
)] // one file; offsets checked under 4 GiB; w, h, n, e, k
pub fn write(
    band: Band,
    w: usize,
    h: usize,
    geo: Georef,
    nodata: Option<&str>,
) -> Result<Vec<u8>, String> {
    // shortcut: an evenly halving pyramid only (GDAL rounds an odd side up); every imported tile is 2000 px square
    if !w.is_multiple_of(16) || !h.is_multiple_of(16) {
        return Err(format!(
            "a {w} x {h} raster does not halve evenly to its 1/16 overview"
        ));
    }
    let (float, resampling) = match band {
        Band::F32(_) => (true, "average"),
        Band::I32(_) => (false, "nearest"),
    };
    let levels = pyramid(band, w, h);
    // the tile data first, then each level's directory and its out-of-line values
    let mut file: Vec<u8> = b"II*\0\0\0\0\0".to_vec();
    let mut tile_spans: Vec<(Vec<u32>, Vec<u32>)> = Vec::new();
    for (b, lw, lh) in &levels {
        let (mut offs, mut lens) = (Vec::new(), Vec::new());
        for t in b.tiles(*lw, *lh) {
            let mut z = flate2::write::ZlibEncoder::new(Vec::new(), flate2::Compression::new(6));
            z.write_all(&t).map_err(|e| e.to_string())?;
            let packed = z.finish().map_err(|e| e.to_string())?;
            offs.push(u32::try_from(file.len()).map_err(|_| "a GeoTIFF over 4 GiB")?);
            lens.push(packed.len() as u32);
            file.extend_from_slice(&packed);
        }
        tile_spans.push((offs, lens));
    }
    let overview_meta = format!(
        "<GDALMetadata><Item name=\"RESAMPLING\" sample=\"0\">{}</Item></GDALMetadata>\0",
        resampling.to_uppercase()
    );
    let base_meta = format!(
        "<GDALMetadata>\n  <Item name=\"resampling\" domain=\"rio_overview\">{resampling}</Item>\n</GDALMetadata>\n\0"
    );
    let mut next_ifd_slot = 4usize;
    for (k, (_, lw, lh)) in levels.iter().enumerate() {
        let (offs, lens) = &tile_spans[k];
        let n = offs.len() as u32;
        let mut e: Vec<Entry> = Vec::new();
        if k > 0 {
            e.push(Entry(254, 4, 1, longs(&[1])));
        }
        e.push(Entry(256, 3, 1, shorts(&[*lw as u16])));
        e.push(Entry(257, 3, 1, shorts(&[*lh as u16])));
        e.push(Entry(258, 3, 1, shorts(&[32])));
        e.push(Entry(259, 3, 1, shorts(&[8])));
        e.push(Entry(262, 3, 1, shorts(&[1])));
        e.push(Entry(277, 3, 1, shorts(&[1])));
        e.push(Entry(284, 3, 1, shorts(&[1])));
        e.push(Entry(317, 3, 1, shorts(&[1])));
        e.push(Entry(322, 3, 1, shorts(&[TILE as u16])));
        e.push(Entry(323, 3, 1, shorts(&[TILE as u16])));
        e.push(Entry(324, 4, n, longs(offs)));
        e.push(Entry(325, 4, n, longs(lens)));
        e.push(Entry(339, 3, 1, shorts(&[if float { 3 } else { 2 }])));
        if k == 0 {
            e.push(Entry(33550, 12, 3, doubles(&[geo.cell_m, geo.cell_m, 0.0])));
            e.push(Entry(
                33922,
                12,
                6,
                doubles(&[0.0, 0.0, 0.0, geo.x0, geo.y1, 0.0]),
            ));
            e.push(Entry(34735, 3, GEO_KEYS.len() as u32, shorts(&GEO_KEYS)));
            e.push(Entry(
                34736,
                12,
                GEO_DOUBLES.len() as u32,
                doubles(&GEO_DOUBLES),
            ));
            let Entry(_, t, c, v) = ascii(GEO_ASCII);
            e.push(Entry(34737, t, c, v));
        }
        let Entry(_, t, c, v) = ascii(if k == 0 { &base_meta } else { &overview_meta });
        e.push(Entry(42112, t, c, v));
        if let Some(nd) = nodata {
            let Entry(_, t, c, v) = ascii(&format!("{nd}\0"));
            e.push(Entry(42113, t, c, v));
        }
        // word-align the directory, link it from the previous one
        if file.len() % 2 == 1 {
            file.push(0);
        }
        let at = u32::try_from(file.len()).map_err(|_| "a GeoTIFF over 4 GiB")?;
        file[next_ifd_slot..next_ifd_slot + 4].copy_from_slice(&at.to_le_bytes());
        let extra_start = file.len() + 2 + e.len() * 12 + 4;
        let mut extra: Vec<u8> = Vec::new();
        file.extend_from_slice(&(e.len() as u16).to_le_bytes());
        for Entry(tag, typ, count, val) in &e {
            file.extend_from_slice(&tag.to_le_bytes());
            file.extend_from_slice(&typ.to_le_bytes());
            file.extend_from_slice(&count.to_le_bytes());
            if val.len() <= 4 {
                let mut v = val.clone();
                v.resize(4, 0);
                file.extend_from_slice(&v);
            } else {
                if extra.len() % 2 == 1 {
                    extra.push(0);
                }
                let off =
                    u32::try_from(extra_start + extra.len()).map_err(|_| "a GeoTIFF over 4 GiB")?;
                file.extend_from_slice(&off.to_le_bytes());
                extra.extend_from_slice(val);
            }
        }
        next_ifd_slot = file.len();
        file.extend_from_slice(&[0, 0, 0, 0]);
        file.extend_from_slice(&extra);
    }
    Ok(file)
}

/// The slope field [deg] of a DEM as `float32` (Python `slope_value_array`: `slope_deg_map` on the DEM cast to
/// `float32`, numpy's `gradient` dividing in `f32`, then `hypotf`, `atanf` and the `f32` degrees factor).
#[must_use]
#[allow(clippy::cast_possible_truncation)] // the Python's float32 cast
pub fn slope_f32(z: &[f64], w: usize, h: usize, cell: f64) -> Vec<f32> {
    let z: Vec<f32> = z.iter().map(|v| *v as f32).collect();
    let (dx, dx2) = (cell as f32, (2.0 * cell) as f32);
    let at = |r: usize, c: usize| z[r * w + c];
    let deg = 180.0_f32 / std::f32::consts::PI;
    let mut out = Vec::with_capacity(z.len());
    for r in 0..h {
        for c in 0..w {
            let gx = if c == 0 {
                (at(r, 1) - at(r, 0)) / dx
            } else if c == w - 1 {
                (at(r, c) - at(r, c - 1)) / dx
            } else {
                (at(r, c + 1) - at(r, c - 1)) / dx2
            };
            let gy = if r == 0 {
                (at(1, c) - at(0, c)) / dx
            } else if r == h - 1 {
                (at(r, c) - at(r - 1, c)) / dx
            } else {
                (at(r + 1, c) - at(r - 1, c)) / dx2
            };
            out.push(gx.hypot(gy).atan() * deg);
        }
    }
    out
}

/// Map algebra reclassify (Python `reclassify`): a value's class is how many breaks are at or below it; a
/// non-finite value is the `-1` nodata class.
#[must_use]
pub fn reclassify(a: &[f32], breaks: &[f64]) -> Vec<i32> {
    a.iter()
        .map(|&v| {
            if v.is_finite() {
                #[allow(clippy::cast_possible_truncation, clippy::cast_possible_wrap)]
                // at most 32 breaks
                let k = breaks.iter().filter(|b| **b <= f64::from(v)).count() as i32;
                k
            } else {
                -1
            }
        })
        .collect()
}
