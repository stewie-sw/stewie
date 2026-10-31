//! lunar-intervals against the SPICE oracle (`visibility_windows`: the real Haworth-centre horizon from
//! `horizon_profiles`, Sun and Earth from spiceypy `spkcpo` LT+S, disk fraction above the known horizon,
//! crossings bisected to 0.1 s over 60 days), plus invariants on the window list.

use lunar_ephem::{Body, Ephemeris, Utc};
use lunar_frames::{LatLon, Sphere};
use lunar_horizon::Horizon;
use lunar_intervals::{Verdict, VisibilityConfig, crossings, visibility_windows};

fn moon() -> Sphere {
    let reg: serde_json::Value =
        serde_json::from_str(include_str!("../../stewie-contracts/fixtures/bodies.json")).unwrap();
    Sphere::new(reg["moon"]["ellipsoid_radius_m"].as_f64().unwrap()).unwrap()
}

fn oracle() -> serde_json::Value {
    stewie_oracle::load("visibility_windows").unwrap().payload
}

fn horizon_from_fixture(p: &serde_json::Value) -> Horizon {
    let elev: Vec<Option<f64>> = p["elev_deg"]
        .as_array()
        .unwrap()
        .iter()
        .map(serde_json::Value::as_f64)
        .collect();
    let n = elev.len();
    #[allow(clippy::cast_precision_loss)]
    let az = (0..n).map(|k| 360.0 * k as f64 / n as f64).collect();
    Horizon {
        az_deg: az,
        elev_deg: elev,
        reach_m: p["reach_m"]
            .as_array()
            .unwrap()
            .iter()
            .map(|v| v.as_f64().unwrap())
            .collect(),
        complete: vec![false; n],
        sources: vec![p["tile"].as_str().unwrap().to_owned()],
    }
}

fn body(name: &str) -> Body {
    match name {
        "SUN" => Body::Sun,
        "EARTH" => Body::Earth,
        other => panic!("unknown body {other}"),
    }
}

#[test]
fn fraction_crossings_match_spice_within_one_second() {
    let fx = oracle();
    let e = Ephemeris::bundled().unwrap();
    let h = horizon_from_fixture(&fx["horizon"]);
    let site = LatLon {
        lat_deg: fx["site"]["lat_deg"].as_f64().unwrap(),
        lon_deg: fx["site"]["lon_deg"].as_f64().unwrap(),
    };
    let t0 = e.tdb(&Utc::parse_iso8601(fx["start_utc"].as_str().unwrap()).unwrap());
    let t1 = e.tdb(&Utc::parse_iso8601(fx["end_utc"].as_str().unwrap()).unwrap());
    let cfg = VisibilityConfig {
        sample_s: fx["sample_s"].as_f64().unwrap(),
        tolerance_s: 0.1,
        eye_height_m: fx["eye_m"].as_f64().unwrap(),
        ground_height_m: fx["ground_m"].as_f64().unwrap(),
        moon: moon(),
    };
    for case in fx["cases"].as_array().unwrap() {
        let b = body(case["body"].as_str().unwrap());
        let got = crossings(&e, &h, site, b, t0, t1, &cfg).unwrap();
        let want: Vec<f64> = case["crossings_tdb"]
            .as_array()
            .unwrap()
            .iter()
            .map(|v| v.as_f64().unwrap())
            .collect();
        assert_eq!(got.len(), want.len(), "{b:?} crossing count");
        for (g, w) in got.iter().zip(&want) {
            assert!((g.tdb - w).abs() < 1.0, "{b:?}: {} vs {w}", g.tdb);
        }
    }
}

#[test]
fn windows_are_sorted_disjoint_and_never_lit_in_an_incomplete_sector() {
    let fx = oracle();
    let e = Ephemeris::bundled().unwrap();
    let h = horizon_from_fixture(&fx["horizon"]);
    let site = LatLon {
        lat_deg: fx["site"]["lat_deg"].as_f64().unwrap(),
        lon_deg: fx["site"]["lon_deg"].as_f64().unwrap(),
    };
    let t0 = e.tdb(&Utc::parse_iso8601(fx["start_utc"].as_str().unwrap()).unwrap());
    let t1 = e.tdb(&Utc::parse_iso8601(fx["end_utc"].as_str().unwrap()).unwrap());
    let cfg = VisibilityConfig {
        sample_s: 600.0,
        tolerance_s: 0.1,
        eye_height_m: 1.5,
        ground_height_m: fx["ground_m"].as_f64().unwrap(),
        moon: moon(),
    };
    let w = visibility_windows(&e, &h, site, Body::Sun, t0, t1, &cfg).unwrap();
    assert!(!w.is_empty());
    assert!((w[0].start_tdb - t0).abs() < 1e-9 && (w[w.len() - 1].end_tdb - t1).abs() < 1e-9);
    for pair in w.windows(2) {
        assert!(
            (pair[0].end_tdb - pair[1].start_tdb).abs() < 1e-9,
            "contiguous"
        );
        assert!(
            pair[0].verdict != pair[1].verdict,
            "adjacent windows differ"
        );
    }
    // the fixture horizon reaches only ~5-7 km, so no sector is complete: nothing may be called Lit (R7)
    assert!(w.iter().all(|x| x.verdict != Verdict::Lit));
    assert!(
        w.iter().any(|x| x.verdict == Verdict::Shadow)
            && w.iter().any(|x| x.verdict == Verdict::Unknown)
    );
}

#[test]
fn a_span_outside_the_ephemeris_is_an_error() {
    let fx = oracle();
    let e = Ephemeris::bundled().unwrap();
    let h = horizon_from_fixture(&fx["horizon"]);
    let site = LatLon {
        lat_deg: -86.0,
        lon_deg: 0.0,
    };
    let cfg = VisibilityConfig {
        sample_s: 600.0,
        tolerance_s: 0.1,
        eye_height_m: 1.5,
        ground_height_m: 0.0,
        moon: moon(),
    };
    let t = e.tdb(&Utc::parse_iso8601("2037-01-01T00:00:00Z").unwrap());
    assert!(visibility_windows(&e, &h, site, Body::Sun, t, t + 86_400.0, &cfg).is_err());
}

#[test]
fn a_complete_horizon_yields_lit_windows() {
    let hz = stewie_oracle::load("horizon_stacked").unwrap().payload;
    let n = hz["elev_deg"].as_array().unwrap().len();
    let reach: Vec<f64> = hz["reach_m"]
        .as_array()
        .unwrap()
        .iter()
        .map(|v| v.as_f64().unwrap())
        .collect();
    let max = hz["max_range_m"].as_f64().unwrap();
    #[allow(clippy::cast_precision_loss)]
    let h = Horizon {
        az_deg: (0..n).map(|k| 360.0 * k as f64 / n as f64).collect(),
        elev_deg: hz["elev_deg"]
            .as_array()
            .unwrap()
            .iter()
            .map(serde_json::Value::as_f64)
            .collect(),
        complete: reach.iter().map(|r| *r >= max).collect(),
        reach_m: reach,
        sources: vec!["haworth_10km_5m".into(), "ldem_16".into()],
    };
    let e = Ephemeris::bundled().unwrap();
    let site = LatLon {
        lat_deg: hz["lat_deg"].as_f64().unwrap(),
        lon_deg: hz["lon_deg"].as_f64().unwrap(),
    };
    let cfg = VisibilityConfig {
        sample_s: 600.0,
        tolerance_s: 0.1,
        eye_height_m: 1.5,
        ground_height_m: hz["ground_m"].as_f64().unwrap(),
        moon: moon(),
    };
    let t0 = e.tdb(&Utc::parse_iso8601("2027-01-01T00:00:00Z").unwrap());
    let w = visibility_windows(&e, &h, site, Body::Sun, t0, t0 + 60.0 * 86_400.0, &cfg).unwrap();
    assert!(
        w.iter().any(|x| x.verdict == Verdict::Lit),
        "a complete horizon must allow Lit"
    );
    assert!(w.iter().any(|x| x.verdict == Verdict::Shadow));
}
