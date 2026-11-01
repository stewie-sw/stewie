//! The polar map's display tiles (RW-71c, D-R104) against the REAL 240 m south polar tier: the package's tiles are
//! exactly what the generator makes from the tier, every catalog site lands on data, the native shade is the tier's
//! own hillshade (checked against an independent slope-aspect formula), and each coarser pixel is the mean of its
//! four children.

use std::path::{Path, PathBuf};

use lunar_dem::PolarGrid;
use lunar_frames::{LatLon, PolarStereographic, Sphere};
use serde_json::Value;
use sha2::{Digest, Sha256};
use stewie_package::display::{TILE, polar_raster, pyramid};

fn moon() -> Sphere {
    let reg: Value =
        serde_json::from_str(include_str!("../../stewie-contracts/fixtures/bodies.json")).unwrap();
    Sphere::new(reg["moon"]["ellipsoid_radius_m"].as_f64().unwrap()).unwrap()
}

fn root() -> PathBuf {
    stewie_oracle::repo_root()
}

fn hex(b: &[u8]) -> String {
    Sha256::digest(b).iter().fold(String::new(), |mut s, x| {
        use std::fmt::Write as _;
        let _ = write!(s, "{x:02x}");
        s
    })
}

/// A tile's (shade, alpha) pixels.
fn decode(path: &Path) -> Vec<(u8, u8)> {
    let dec = png::Decoder::new(std::io::BufReader::new(std::fs::File::open(path).unwrap()));
    let mut reader = dec.read_info().unwrap();
    let mut buf = vec![0; reader.output_buffer_size().unwrap()];
    let info = reader.next_frame(&mut buf).unwrap();
    assert_eq!(info.color_type, png::ColorType::GrayscaleAlpha);
    buf[..info.buffer_size()]
        .chunks(2)
        .map(|p| (p[0], p[1]))
        .collect()
}

#[test]
#[allow(
    clippy::too_many_lines,
    clippy::cast_precision_loss,
    clippy::cast_possible_truncation,
    clippy::cast_sign_loss
)]
fn display_tiles_are_the_tiers_own_hillshade() {
    let terrain = root().join(".cache/terrain");
    let grid = PolarGrid::open(
        &terrain.join("ldem_75s_240m.img"),
        &terrain.join("ldem_75s_240m.lbl"),
        moon(),
    )
    .unwrap();
    let dir = root().join(".cache/package/south_polar_sites/display");
    let index: Value =
        serde_json::from_str(&std::fs::read_to_string(dir.join("tiles.json")).unwrap()).unwrap();
    // the package holds exactly what the generator makes from the tier
    let raster = polar_raster(&grid);
    let (tiles, regenerated) = pyramid(&raster, &index["source"]).unwrap();
    assert_eq!(regenerated, index, "the index regenerates byte for byte");
    let hashes = index["tiles"].as_object().unwrap();
    assert_eq!(tiles.len(), hashes.len());
    for (z, x, y, png) in &tiles {
        let path = dir.join(format!("{z}/{x}/{y}.png"));
        let on_disk = std::fs::read(&path).unwrap();
        assert_eq!(&on_disk, png, "{} is the generator's", path.display());
        assert_eq!(
            hashes[&format!("{z}/{x}/{y}")].as_str().unwrap(),
            hex(&on_disk),
            "{z}/{x}/{y} hash"
        );
    }
    let max_z = usize::try_from(index["max_zoom"].as_u64().unwrap()).unwrap();
    let (west, north) = (
        index["origin"][0].as_f64().unwrap(),
        index["origin"][1].as_f64().unwrap(),
    );
    let cell = raster.cell_m;
    // every catalog site falls on data at the native zoom, at the tier pixel under it
    let sites: Value =
        serde_json::from_str(include_str!("../../stewie-contracts/fixtures/sites.json")).unwrap();
    let proj = PolarStereographic::south(moon());
    let shade = stewie_package::display::hillshade(&raster);
    let mut checked = 0;
    for s in sites.as_object().unwrap().values() {
        let ll = LatLon {
            lat_deg: s["lat_deg"].as_f64().unwrap(),
            lon_deg: s["lon_deg"].as_f64().unwrap(),
        };
        let (e, n) = proj.forward(ll).unwrap();
        let (px, py) = (
            ((e - west) / cell).floor() as usize,
            ((north - n) / cell).floor() as usize,
        );
        let (tx, ty) = (px / TILE, py / TILE);
        let pixels = decode(&dir.join(format!("{max_z}/{tx}/{ty}.png")));
        let (shade_px, alpha) = pixels[(py % TILE) * TILE + px % TILE];
        assert_eq!(alpha, 255, "{} lands on data", s["name"]);
        assert_eq!(
            shade_px,
            shade[py * raster.cols + px],
            "{} shade",
            s["name"]
        );
        checked += 1;
    }
    assert!(checked >= 10, "vacuity: the catalog's sites");
    // the shade is the hillshade of the tier: an independent slope-aspect formula agrees within one grey level
    let (sun_az, sun_zen) = (315_f64.to_radians(), 45_f64.to_radians());
    for &(row, col) in &[
        (400, 400),
        (1906, 1906),
        (1000, 2900),
        (3000, 700),
        (2500, 2500),
    ] {
        let z = |r: usize, c: usize| raster.heights[r * raster.cols + c];
        let dzdx = (z(row, col + 1) - z(row, col - 1)) / (2.0 * cell);
        let dzdy_north = (z(row - 1, col) - z(row + 1, col)) / (2.0 * cell);
        let slope = dzdx.hypot(dzdy_north).atan();
        // aspect: the downhill direction, clockwise from north
        let aspect = (-dzdx).atan2(-dzdy_north);
        let lit =
            sun_zen.cos() * slope.cos() + sun_zen.sin() * slope.sin() * (sun_az - aspect).cos();
        let want = 255.0 * lit.max(0.0);
        let got = f64::from(shade[row * raster.cols + col]);
        assert!(
            (got - want).abs() <= 1.0,
            "pixel ({row},{col}): {got} vs {want}"
        );
    }
    // each coarser pixel is the mean of its four children (all inside the data here)
    let child = decode(&dir.join(format!("{max_z}/2/2.png")));
    let (cx, cy) = (2 / 2, 2 / 2);
    let parent = decode(&dir.join(format!("{}/{cx}/{cy}.png", max_z - 1)));
    for (pr, pc) in [(0, 0), (10, 37), (127, 127)] {
        let kids = [(0, 0), (0, 1), (1, 0), (1, 1)]
            .map(|(dr, dc)| u32::from(child[(2 * pr + dr) * TILE + 2 * pc + dc].0));
        let mean = (kids.iter().sum::<u32>() * 2 + 4) / 8;
        assert_eq!(
            u32::from(parent[pr * TILE + pc].0),
            mean,
            "parent pixel ({pr},{pc})"
        );
    }
}
