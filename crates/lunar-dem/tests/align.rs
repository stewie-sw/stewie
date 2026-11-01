//! Alignment to LOLA tracks (RW-60c, navigator N32, D-R105) on REAL data: the pinned LOLA RDR extracts of
//! `pipeline/lola_tracks.json` against the package's LOLA tiers. Every tier aligns within a pixel and its threshold;
//! a copy of the 40 m tier shifted by known offsets is recovered within 1 pixel and 0.5 m; a copy shifted by five
//! pixels, and the 1.9 km global grid passed off as a 40 m source, are refused.

use std::path::PathBuf;

use lunar_dem::align::{Alignment, Shot, admits, align, max_residual_rms_m, parse_shots};
use lunar_dem::{GlobalGrid, PolarGrid, TerrainSource};
use lunar_frames::{LatLon, Sphere};

fn moon() -> Sphere {
    let reg: serde_json::Value =
        serde_json::from_str(include_str!("../../stewie-contracts/fixtures/bodies.json")).unwrap();
    Sphere::new(reg["moon"]["ellipsoid_radius_m"].as_f64().unwrap()).unwrap()
}

fn root() -> PathBuf {
    stewie_oracle::repo_root()
}

fn shots(name: &str) -> Vec<Shot> {
    parse_shots(&std::fs::read_to_string(root().join(format!(".cache/lola/{name}.csv"))).unwrap())
        .unwrap()
}

fn polar(name: &str) -> PolarGrid {
    let t = root().join(".cache/terrain");
    PolarGrid::open(
        &t.join(format!("{name}.img")),
        &t.join(format!("{name}.lbl")),
        moon(),
    )
    .unwrap()
}

/// A source seen through a known horizontal shift and vertical offset, or relabelled with another resolution:
/// the test's way of making a misaligned or overstated copy of real terrain.
#[derive(Debug)]
struct Altered<'a> {
    inner: &'a dyn TerrainSource,
    shift_m: (f64, f64),
    offset_m: f64,
    resolution_m: f64,
}

impl TerrainSource for Altered<'_> {
    fn id(&self) -> &'static str {
        "altered copy"
    }
    fn citation(&self) -> &str {
        self.inner.citation()
    }
    fn resolution_m(&self) -> f64 {
        self.resolution_m
    }
    fn sphere(&self) -> Sphere {
        self.inner.sphere()
    }
    fn sample_latlon(&self, ll: LatLon) -> Option<f64> {
        // the copy's terrain at p is the real terrain at p moved back by the shift
        let r = self.inner.sphere().radius_m();
        let back = LatLon {
            lat_deg: ll.lat_deg - (self.shift_m.1 / r).to_degrees(),
            lon_deg: ll.lon_deg
                - (self.shift_m.0 / (r * ll.lat_deg.to_radians().cos())).to_degrees(),
        };
        self.inner.sample_latlon(back).map(|z| z + self.offset_m)
    }
}

fn report(name: &str, a: &Alignment, res: f64) {
    eprintln!(
        "{name}: shift ({:.1}, {:.1}) m, offset {:.2} m, rms {:.2} m (threshold {:.1} m), {} shots, {} set aside",
        a.shift_east_m,
        a.shift_north_m,
        a.vertical_offset_m,
        a.residual_rms_m,
        max_residual_rms_m(res),
        a.shots_used,
        a.shots_rejected
    );
}

#[test]
fn every_package_tier_sits_in_the_lola_frame() {
    let south = shots("haworth_south");
    let north = shots("peary_north");
    let equator = shots("hadley_equatorial");
    assert!(south.len() > 100_000 && north.len() > 100_000 && equator.len() > 100_000);
    let t = root().join(".cache/terrain");
    let global = GlobalGrid::open(&t.join("ldem_16.img"), &t.join("ldem_16.lbl"), moon()).unwrap();
    let tiers: [(&str, Box<dyn TerrainSource>, &[Shot]); 4] = [
        ("ldem_85s_40m", Box::new(polar("ldem_85s_40m")), &south),
        ("ldem_75s_240m", Box::new(polar("ldem_75s_240m")), &south),
        ("ldem_75n_240m", Box::new(polar("ldem_75n_240m")), &north),
        ("ldem_16", Box::new(global), &equator),
    ];
    for (name, src, s) in &tiers {
        let a = align(src.as_ref(), s, 3, 1000).unwrap();
        report(name, &a, src.resolution_m());
        assert!(admits(&a, src.resolution_m()), "{name} enters the stack");
    }
}

#[test]
fn a_shifted_copy_is_recovered_and_a_misplaced_one_refused() {
    let south = shots("haworth_south");
    let tier = polar("ldem_85s_40m");
    let cell = tier.resolution_m();
    let base = align(&tier, &south, 2, 1000).unwrap();
    let (shift, dz) = ((37.0, -55.0), 2.0);
    let copy = Altered {
        inner: &tier,
        shift_m: shift,
        offset_m: dz,
        resolution_m: cell,
    };
    let a = align(&copy, &south, 4, 1000).unwrap();
    report("shifted copy", &a, cell);
    let (ge, gn) = (
        a.shift_east_m - base.shift_east_m,
        a.shift_north_m - base.shift_north_m,
    );
    // N32 asks for a pixel; the eighth-pixel refinement gets within a quarter
    assert!(
        (ge - shift.0).hypot(gn - shift.1) <= cell / 4.0,
        "shift recovered within a quarter pixel: ({ge:.1}, {gn:.1})"
    );
    let gz = base.vertical_offset_m - a.vertical_offset_m;
    assert!(
        (gz - dz).abs() <= 0.5,
        "vertical offset recovered within 0.5 m: {gz:.2}"
    );
    // five pixels off: aligned, but not admitted
    let far = Altered {
        inner: &tier,
        shift_m: (5.0 * cell, 0.0),
        offset_m: 0.0,
        resolution_m: cell,
    };
    let f = align(&far, &south, 8, 1000).unwrap();
    report("five-pixel copy", &f, cell);
    assert!(
        !admits(&f, cell),
        "a source five pixels off the LOLA frame is refused"
    );
    // the 1.9 km global grid claiming 40 m: within a pixel, but its residual is far over the 40 m threshold
    let t = root().join(".cache/terrain");
    let global = GlobalGrid::open(&t.join("ldem_16.img"), &t.join("ldem_16.lbl"), moon()).unwrap();
    let equator = shots("hadley_equatorial");
    let coarse = Altered {
        inner: &global,
        shift_m: (0.0, 0.0),
        offset_m: 0.0,
        resolution_m: 40.0,
    };
    let c = align(&coarse, &equator, 2, 1000).unwrap();
    report("coarse as 40 m", &c, 40.0);
    assert!(
        c.residual_rms_m > max_residual_rms_m(40.0),
        "overstated resolution shows in the residual"
    );
    assert!(!admits(&c, 40.0));
}

#[test]
fn shot_rows_parse_to_signed_longitudes() {
    // SYNTHETIC rows in the ODE simple-topography layout (labelled): east longitudes past 180 become negative
    let csv = "Pt_Longitude, Pt_Latitude, Topography\n 355.0079727, -87.4515666,   -3313.98\n 2.5, 26.1, -1520.5\n";
    let s = parse_shots(csv).unwrap();
    assert!(
        (s[0].lon_deg - (355.007_972_7 - 360.0)).abs() < 1e-12
            && (s[0].height_m + 3313.98).abs() < 1e-12
    );
    assert!((s[1].lon_deg - 2.5).abs() < 1e-12 && (s[1].lat_deg - 26.1).abs() < 1e-12);
    assert!(
        parse_shots("lon,lat,h\n1,2,3\n").is_err(),
        "an unexpected header is refused"
    );
    assert!(
        parse_shots("Pt_Longitude, Pt_Latitude, Topography\n1,2\n").is_err(),
        "a short row is refused"
    );
}
