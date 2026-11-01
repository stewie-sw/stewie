//! The flattest buildable anchor (RW-55b3) against the Python oracle (`flattest_cases`): on every real bundled DEM
//! at the planner's 20 m window, and on Haworth at windows giving odd, even and unit kernels, the anchor is the
//! same cell exactly (the `SciPy` running mean reproduced bit for bit, so no near-tie flips the argmin).

use lunar_dem::{DemTile, flattest_anchor, uniform_filter_nearest};
use lunar_frames::Sphere;
use serde_json::Value;

fn moon() -> Sphere {
    let reg: Value =
        serde_json::from_str(include_str!("../../stewie-contracts/fixtures/bodies.json")).unwrap();
    Sphere::new(reg["moon"]["ellipsoid_radius_m"].as_f64().unwrap()).unwrap()
}

#[test]
fn every_bundle_anchors_where_the_python_does() {
    let fx = stewie_oracle::load("flattest_cases").unwrap().payload;
    let cases = fx["cases"].as_array().unwrap();
    assert!(cases.len() >= 10, "vacuity: the bundled sites");
    for c in cases {
        let name = c["bundle"].as_str().unwrap();
        let dir = stewie_oracle::repo_root()
            .join("samples/lunar_dem")
            .join(name);
        let t = DemTile::open(&dir, moon()).unwrap();
        let w = c["window_m"].as_f64().unwrap();
        let got = flattest_anchor(&t.heights_f64(), t.width(), t.height(), t.cell_m(), w);
        let want = (c["x"].as_f64().unwrap(), c["y"].as_f64().unwrap());
        assert_eq!(got, want, "{name} at {w} m");
    }
}

#[test]
#[allow(clippy::many_single_char_names, clippy::cast_precision_loss)] // grid indices and a small kernel
fn the_running_mean_matches_the_naive_mean_away_from_the_edges() {
    // SYNTHETIC grid (labelled): a ramp with a spike; interior windows must equal the plain window average
    let (w, h) = (9, 7);
    let v: Vec<f64> = (0..w * h)
        .map(|i| {
            if i == 31 {
                50.0
            } else {
                f64::from(u32::try_from(i).unwrap()) * 0.5
            }
        })
        .collect();
    for size in [1, 2, 3, 4] {
        let out = uniform_filter_nearest(&v, w, h, size);
        let (b, a) = (size / 2, size - size / 2 - 1);
        for r in b..h - a {
            for c in b..w - a {
                let mut s = 0.0;
                for rr in r - b..=r + a {
                    for cc in c - b..=c + a {
                        s += v[rr * w + cc];
                    }
                }
                let naive = s / (size * size) as f64;
                assert!(
                    (out[r * w + c] - naive).abs() < 1e-9,
                    "size {size} at {r},{c}"
                );
            }
        }
    }
}

#[test]
fn a_tie_anchors_at_the_first_cell_as_numpy_argmin() {
    // SYNTHETIC flat grid (labelled): every window mean is zero, so the anchor is the first cell
    let z = vec![1.25; 6 * 5];
    assert_eq!(flattest_anchor(&z, 6, 5, 2.0, 4.0), (0.0, 0.0));
}
