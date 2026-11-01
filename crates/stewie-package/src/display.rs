//! Display tiles for the polar map (RW-71c, D-R104): a hillshade pyramid of a polar-stereographic tier, cut into
//! 256-pixel folder tiles (`z/x/y.png`, grayscale with alpha) on the tier's own grid, plus a self-describing index
//! (`tiles.json`: projection, extent, origin, resolutions, tile size, the source layer and every tile's SHA-256).
//! The native zoom is one tile pixel per DEM pixel; each coarser zoom averages 2 x 2 pixels of the next. The Sun for
//! the shade is the cartographic convention (azimuth 315 deg, elevation 45 deg): a display aid, not illumination.

use std::fmt::Write as _;

use serde_json::{Value, json};
use sha2::{Digest, Sha256};

/// Tile edge [px].
pub const TILE: usize = 256;
/// The display shade's Sun (cartographic convention, not lunar illumination).
pub const SHADE_AZ_DEG: f64 = 315.0;
pub const SHADE_EL_DEG: f64 = 45.0;

/// A projected raster: row-major heights [m], `rows` x `cols` pixels of `cell_m`, pixel (0, 0)'s centre at
/// (`easting0`, `northing0`), rows running south.
#[derive(Debug, Clone, PartialEq)]
pub struct Raster {
    pub heights: Vec<f64>,
    pub rows: usize,
    pub cols: usize,
    pub cell_m: f64,
    pub easting0: f64,
    pub northing0: f64,
}

/// Hillshade of each pixel (0..=255) from central differences (one-sided at the edges, as numpy's gradient),
/// north up: `255 * max(0, n . s)` for the surface normal `n` and the Sun direction `s`.
#[must_use]
pub fn hillshade(r: &Raster) -> Vec<u8> {
    let (az, el) = (SHADE_AZ_DEG.to_radians(), SHADE_EL_DEG.to_radians());
    let sun = (el.cos() * az.sin(), el.cos() * az.cos(), el.sin()); // east, north, up
    let at = |row: usize, col: usize| r.heights[row * r.cols + col];
    let grad = |a: f64, b: f64, span: f64| (b - a) / (span * r.cell_m);
    (0..r.rows * r.cols)
        .map(|i| {
            let (row, col) = (i / r.cols, i % r.cols);
            let east_slope = match col {
                _ if r.cols < 2 => 0.0,
                0 => grad(at(row, 0), at(row, 1), 1.0),
                c if c == r.cols - 1 => grad(at(row, c - 1), at(row, c), 1.0),
                c => grad(at(row, c - 1), at(row, c + 1), 2.0),
            };
            // rows run south, so northward is decreasing row
            let north_slope = -match row {
                _ if r.rows < 2 => 0.0,
                0 => grad(at(0, col), at(1, col), 1.0),
                q if q == r.rows - 1 => grad(at(q - 1, col), at(q, col), 1.0),
                q => grad(at(q - 1, col), at(q + 1, col), 2.0),
            };
            let norm = (east_slope * east_slope + north_slope * north_slope + 1.0).sqrt();
            let lit = (-east_slope * sun.0 - north_slope * sun.1 + sun.2) / norm;
            // round half up of a value in [0, 255]
            #[allow(clippy::cast_possible_truncation, clippy::cast_sign_loss)]
            let v = (255.0 * lit.max(0.0) + 0.5).floor().min(255.0) as u8;
            v
        })
        .collect()
}

/// One encoded tile: zoom, column, row (south from the north-west corner) and its PNG bytes.
pub type Tile = (usize, usize, usize, Vec<u8>);

/// One zoom level: `size` x `size` pixels of (shade, alpha), alpha 0 outside the data.
struct Level {
    size: usize,
    px: Vec<(u8, u8)>,
}

fn sha256_hex(b: &[u8]) -> String {
    Sha256::digest(b).iter().fold(String::new(), |mut s, x| {
        let _ = write!(s, "{x:02x}");
        s
    })
}

/// Encode one grayscale-with-alpha tile as PNG.
///
/// # Errors
/// The encoder's refusal.
pub fn encode_png(pixels: &[(u8, u8)]) -> Result<Vec<u8>, String> {
    let mut out = Vec::new();
    {
        let side = u32::try_from(TILE).map_err(|e| e.to_string())?;
        let mut enc = png::Encoder::new(&mut out, side, side);
        enc.set_color(png::ColorType::GrayscaleAlpha);
        enc.set_depth(png::BitDepth::Eight);
        // png's own fdeflate: the bytes do not depend on which flate2 backend the build's feature
        // unification picked (the workspace's zip enables zlib-rs), so tile hashes reproduce in every build
        enc.set_compression(png::Compression::Fast);
        let mut w = enc.write_header().map_err(|e| e.to_string())?;
        let flat: Vec<u8> = pixels.iter().flat_map(|&(g, a)| [g, a]).collect();
        w.write_image_data(&flat).map_err(|e| e.to_string())?;
    }
    Ok(out)
}

/// The pyramid of `r` as encoded tiles `(z, x, y, png)` and its index. The native zoom covers the raster padded to
/// a power-of-two number of tiles; tile (x, y) counts east and south from the grid's north-west corner.
///
/// # Errors
/// A raster with no pixels, or a PNG the encoder refuses.
#[allow(clippy::cast_precision_loss)]
pub fn pyramid(r: &Raster, source: &Value) -> Result<(Vec<Tile>, Value), String> {
    if r.rows == 0 || r.cols == 0 {
        return Err("an empty raster has no tiles".to_owned());
    }
    let shade = hillshade(r);
    let tiles_side = r.rows.max(r.cols).div_ceil(TILE).next_power_of_two();
    let max_z = tiles_side.trailing_zeros() as usize;
    let size = tiles_side * TILE;
    let mut px = vec![(0_u8, 0_u8); size * size];
    for row in 0..r.rows {
        for col in 0..r.cols {
            px[row * size + col] = (shade[row * r.cols + col], 255);
        }
    }
    let mut levels = vec![Level { size, px }];
    while levels[levels.len() - 1].size > TILE {
        let fine = &levels[levels.len() - 1];
        let half = fine.size / 2;
        let mut coarse = vec![(0_u8, 0_u8); half * half];
        for row in 0..half {
            for col in 0..half {
                // the mean of the data pixels of the 2 x 2 block (round half up); transparent when none
                let block = [(0, 0), (0, 1), (1, 0), (1, 1)]
                    .map(|(dr, dc)| fine.px[(2 * row + dr) * fine.size + 2 * col + dc]);
                let data: Vec<u32> = block
                    .iter()
                    .filter(|p| p.1 > 0)
                    .map(|p| u32::from(p.0))
                    .collect();
                if let Ok(n) = u32::try_from(data.len())
                    && n > 0
                {
                    let mean = (data.iter().sum::<u32>() * 2 + n) / (2 * n);
                    coarse[row * half + col] = (u8::try_from(mean).unwrap_or(255), 255);
                }
            }
        }
        levels.push(Level {
            size: half,
            px: coarse,
        });
    }
    levels.reverse(); // z = 0 first
    let mut tiles = Vec::new();
    let mut hashes = serde_json::Map::new();
    for (z, level) in levels.iter().enumerate() {
        let n = level.size / TILE;
        for ty in 0..n {
            for tx in 0..n {
                let mut tile = Vec::with_capacity(TILE * TILE);
                for row in 0..TILE {
                    let start = (ty * TILE + row) * level.size + tx * TILE;
                    tile.extend_from_slice(&level.px[start..start + TILE]);
                }
                if tile.iter().all(|p| p.1 == 0) {
                    continue; // nothing of the tier in this tile
                }
                let bytes = encode_png(&tile)?;
                hashes.insert(format!("{z}/{tx}/{ty}"), json!(sha256_hex(&bytes)));
                tiles.push((z, tx, ty, bytes));
            }
        }
    }
    // the grid's north-west corner: half a pixel beyond pixel (0, 0)'s centre
    let (west, north) = (r.easting0 - r.cell_m / 2.0, r.northing0 + r.cell_m / 2.0);
    let span = size as f64 * r.cell_m;
    let resolutions: Vec<f64> = (0..=max_z)
        .map(|z| r.cell_m * f64::from(1_u32 << (max_z - z)))
        .collect();
    let index = json!({
        "schema_version": "1.0",
        "tile_size": TILE,
        "extent": [west, north - span, west + span, north],
        "origin": [west, north],
        "resolutions": resolutions,
        "max_zoom": max_z,
        "shade_sun": {"az_deg": SHADE_AZ_DEG, "el_deg": SHADE_EL_DEG},
        "source": source,
        "tiles": hashes,
    });
    Ok((tiles, index))
}

/// The raster of a polar tier, as the pyramid takes it.
#[must_use]
pub fn polar_raster(g: &lunar_dem::PolarGrid) -> Raster {
    use lunar_dem::TerrainSource as _;
    let (rows, cols) = g.shape();
    let (easting0, northing0) = g.first_pixel_en();
    Raster {
        heights: g.heights(),
        rows,
        cols,
        cell_m: g.resolution_m(),
        easting0,
        northing0,
    }
}

/// Render the display tiles of the polar tier `img`/`lbl` into `out_dir` (`z/x/y.png` and `tiles.json`, written
/// fresh). `crs` names the map projection the tier's grid is in. Returns the tile count.
///
/// # Errors
/// An unreadable tier, an empty raster, or an I/O failure.
pub fn write_polar_tiles(
    (img, lbl): (&std::path::Path, &std::path::Path),
    sphere: lunar_frames::Sphere,
    crs: &str,
    out_dir: &std::path::Path,
) -> Result<usize, String> {
    let grid = lunar_dem::PolarGrid::open(img, lbl, sphere).map_err(|e| e.to_string())?;
    let bytes = std::fs::read(img).map_err(|e| format!("{}: {e}", img.display()))?;
    let id = img
        .file_stem()
        .map_or_else(String::new, |n| n.to_string_lossy().into_owned());
    let source = json!({"layer": id, "image_sha256": sha256_hex(&bytes), "crs": crs,
                        "resolution_m": polar_raster(&grid).cell_m});
    let (tiles, index) = pyramid(&polar_raster(&grid), &source)?;
    if out_dir.exists() {
        std::fs::remove_dir_all(out_dir).map_err(|e| format!("{}: {e}", out_dir.display()))?;
    }
    for (z, x, y, png) in &tiles {
        let dir = out_dir.join(z.to_string()).join(x.to_string());
        std::fs::create_dir_all(&dir).map_err(|e| format!("{}: {e}", dir.display()))?;
        std::fs::write(dir.join(format!("{y}.png")), png).map_err(|e| e.to_string())?;
    }
    let text = serde_json::to_string_pretty(&index).map_err(|e| e.to_string())?;
    std::fs::write(out_dir.join("tiles.json"), text + "\n").map_err(|e| e.to_string())?;
    Ok(tiles.len())
}

/// The index without its tile hashes, plus where each site falls at the native zoom (tile and pixel within it),
/// for the web map's cross-check of its own projection.
///
/// # Errors
/// A site the projection refuses.
#[allow(clippy::cast_possible_truncation, clippy::cast_sign_loss)]
pub fn grid_fixture(
    index: &Value,
    proj: &lunar_frames::PolarStereographic,
    sites: &Value,
) -> Result<Value, String> {
    let mut grid = index.clone();
    if let Some(o) = grid.as_object_mut() {
        o.remove("tiles");
    }
    let num = |v: &Value| v.as_f64().ok_or("index: not a number");
    let (west, north) = (num(&index["origin"][0])?, num(&index["origin"][1])?);
    let z = index["max_zoom"].as_u64().ok_or("index: no max_zoom")?;
    let res = num(&index["resolutions"][usize::try_from(z).map_err(|e| e.to_string())?])?;
    let mut placed = Vec::new();
    for (name, s) in sites.as_object().ok_or("sites: not an object")? {
        let ll = lunar_frames::LatLon {
            lat_deg: num(&s["lat_deg"])?,
            lon_deg: num(&s["lon_deg"])?,
        };
        let (e, n) = proj.forward(ll).map_err(|e| e.to_string())?;
        let (px, py) = (
            ((e - west) / res).floor() as usize,
            ((north - n) / res).floor() as usize,
        );
        placed.push(
            json!({"name": name, "lon_deg": ll.lon_deg, "lat_deg": ll.lat_deg, "xy": [e, n],
                           "tile": [z, px / TILE, py / TILE], "pixel": [px % TILE, py % TILE]}),
        );
    }
    Ok(json!({"grid": grid, "sites": placed}))
}
