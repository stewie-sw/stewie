//! The contourpy port against contourpy itself (`contour_cases`): on the real work-area hazard masks and height
//! windows, and on the oracle's SYNTHETIC seeded grids, every polygon's points (exact), ring offsets and order.

use serde_json::Value;
use stewie_server::contour::filled;

fn floats(v: &Value) -> Vec<f64> {
    v.as_array()
        .unwrap()
        .iter()
        .map(|x| x.as_f64().unwrap())
        .collect()
}

#[test]
fn filled_contours_are_contourpys() {
    let fx = stewie_oracle::load("contour_cases").unwrap().payload;
    let (mut polys, mut holes) = (0, 0);
    for c in fx["cases"].as_array().unwrap() {
        let name = c["name"].as_str().unwrap();
        let got = filled(
            &floats(&c["xs"]),
            &floats(&c["ys"]),
            &floats(&c["z"]),
            c["lower"].as_f64().unwrap(),
            c["upper"].as_f64().unwrap(),
        )
        .unwrap();
        let want = c["polygons"].as_array().unwrap();
        assert_eq!(got.len(), want.len(), "{name}: polygon count");
        for (k, ((pts, offs), w)) in got.iter().zip(want).enumerate() {
            let wo: Vec<usize> = w["offsets"]
                .as_array()
                .unwrap()
                .iter()
                .map(|o| usize::try_from(o.as_u64().unwrap()).unwrap())
                .collect();
            assert_eq!(offs, &wo, "{name} polygon {k}: ring offsets");
            let wp: Vec<[f64; 2]> = w["points"]
                .as_array()
                .unwrap()
                .iter()
                .map(|p| [p[0].as_f64().unwrap(), p[1].as_f64().unwrap()])
                .collect();
            assert_eq!(pts, &wp, "{name} polygon {k}: points");
            polys += 1;
            holes += wo.len() - 2;
        }
    }
    assert!(
        polys > 300 && holes > 100,
        "vacuity: {polys} polygons, {holes} holes"
    );
}
