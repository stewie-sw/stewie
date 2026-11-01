//! The illumination route-cost layer against the Python oracle `illumination_cases`, on a real 60x60 window of the
//! Haworth route window. At the real Haworth epochs the Sun comes from the Rust DE440 ephemeris (rewired, RW-15) and
//! matches the SPICE-derived angles the Python used; at fixed angles every branch (Sun down, grazing, high) is
//! reached. The anchors and the map-uncertainty field are SYNTHETIC (labelled in the oracle).

use lunar_ephem::{AzEl, Ephemeris, Utc};
use lunar_frames::{LatLon, Sphere, body_fixed};
use serde_json::Value;
use stewie_traverse::costmap::Illumination;
use stewie_traverse::illumination::{
    Heightmap, IlluminationWeights, illumination_cost, sun_at, viewshed,
};

fn f(v: &Value) -> f64 {
    v.as_f64().unwrap()
}

fn indices(v: &Value) -> Vec<usize> {
    v.as_array()
        .unwrap()
        .iter()
        .map(|x| usize::try_from(x.as_u64().unwrap()).unwrap())
        .collect()
}

#[test]
#[allow(clippy::too_many_lines)] // the window, the Sun, then every term of every case
fn the_illumination_cost_is_the_pythons_under_the_rust_sun() {
    let fx = stewie_oracle::load("illumination_cases").unwrap().payload;
    let tc = stewie_oracle::load("trips_cases").unwrap().payload;
    let heights: Vec<f64> = stewie_oracle::load("route_cases").unwrap().payload["z"]
        .as_array()
        .unwrap()
        .iter()
        .map(f)
        .collect();
    let route_side = usize::try_from(tc["window"][2].as_u64().unwrap()).unwrap();
    let w = &fx["window"];
    let (r0, c0, n) = (
        usize::try_from(w[0].as_u64().unwrap()).unwrap(),
        usize::try_from(w[1].as_u64().unwrap()).unwrap(),
        usize::try_from(w[2].as_u64().unwrap()).unwrap(),
    );
    let window: Vec<f64> = (r0..r0 + n)
        .flat_map(|r| {
            heights[r * route_side + c0..r * route_side + c0 + n]
                .iter()
                .copied()
        })
        .collect();
    let map = Heightmap {
        z: &window,
        width: n,
        height: n,
        cell_m: f(&fx["cell_m"]),
        origin: (0.0, 0.0),
    };
    let wj = &fx["weights"];
    let weights = IlluminationWeights {
        shadow: f(&wj["shadow"]),
        saturation: f(&wj["saturation"]),
        map_uncertainty: f(&wj["map_uncertainty"]),
        visibility: f(&wj["visibility"]),
        grazing_el_deg: f(&wj["grazing_el_deg"]),
    };
    let anchors: Vec<(f64, f64)> = fx["anchors"]
        .as_array()
        .unwrap()
        .iter()
        .map(|a| (f(&a[0]), f(&a[1])))
        .collect();
    let los = viewshed(&map, &anchors, 1.5, 0.0);
    let want_los: Vec<bool> = fx["los"]
        .as_array()
        .unwrap()
        .iter()
        .map(|v| v.as_bool().unwrap())
        .collect();
    assert_eq!(los, want_los, "the viewshed is the Python's");
    let mu: Vec<f64> = fx["map_uncertainty"]
        .as_array()
        .unwrap()
        .iter()
        .map(f)
        .collect();
    // the Sun at Haworth from the packed ephemeris, the site on the sphere (as the oracle's SPICE observer)
    let eph = Ephemeris::bundled().unwrap();
    let ec = stewie_oracle::load("ephem_topocentric").unwrap().payload;
    let site = LatLon {
        lat_deg: f(&ec["sites"]["haworth"]["lat_deg"]),
        lon_deg: f(&ec["sites"]["haworth"]["lon_deg"]),
    };
    let moon = Sphere::new(f(&ec["moon_radius_km"]) * 1000.0).unwrap();
    let position = body_fixed(moon, site, 0.0);
    let mut rewired = 0;
    for c in fx["cases"].as_array().unwrap() {
        let s = &c["sun"];
        let tag = format!("{} {}", s, c["variant"]);
        let python_sun = AzEl {
            az_deg: f(&s["az_deg"]),
            el_deg: f(&s["el_deg"]),
        };
        let sun = match s["utc"].as_str() {
            Some(utc) => {
                let rust = sun_at(&eph, site, position, &Utc::parse_iso8601(utc).unwrap()).unwrap();
                // the rewire: the Rust ephemeris gives the Python's SPICE angles
                assert!(
                    (rust.az_deg - python_sun.az_deg).abs() < 1e-6,
                    "{tag} azimuth {}",
                    rust.az_deg
                );
                assert!(
                    (rust.el_deg - python_sun.el_deg).abs() < 1e-6,
                    "{tag} elevation {}",
                    rust.el_deg
                );
                rewired += 1;
                rust
            }
            None => python_sun,
        };
        // the grazing term is linear in elevation, so it carries the ephemeris' < 1e-6 deg difference
        let tol = if s["utc"].is_string() { 1e-6 } else { 1e-12 };
        let variant = c["variant"].as_str().unwrap();
        let (los_in, mu_in) = match variant {
            "plain" => (None, None),
            "anchors" => (Some(los.as_slice()), None),
            _ => (Some(los.as_slice()), Some(mu.as_slice())),
        };
        let got = illumination_cost(&map, sun, 500.0, mu_in, los_in, &weights).unwrap();
        let Illumination::Terms {
            shadow_hazard,
            saturation,
            visibility,
            ..
        } = &got.layer
        else {
            panic!("{tag}: terms expected");
        };
        let shadowed: Vec<usize> = (0..n * n).filter(|&i| shadow_hazard[i] > 0.0).collect();
        assert_eq!(shadowed, indices(&c["shadowed"]), "{tag} shadows");
        for i in 0..n * n {
            let want = if shadow_hazard[i] > 0.0 {
                0.0
            } else {
                f(&c["saturation_lit"])
            };
            assert!((saturation[i] - want).abs() < tol, "{tag} saturation {i}");
        }
        let blind: Vec<usize> = (0..n * n).filter(|&i| visibility[i] > 0.0).collect();
        assert_eq!(blind, indices(&c["blind"]), "{tag} visibility");
        if let Some(total) = c.get("total").and_then(Value::as_array) {
            for (i, (g, e)) in got.total.iter().zip(total).enumerate() {
                assert!((g - f(e)).abs() <= tol, "{tag} total {i}");
            }
        }
    }
    assert!(rewired >= 3, "vacuity: real epochs drive the Sun");
}

#[test]
fn solar_fallbacks_are_declared_as_the_python_does() {
    use stewie_traverse::illumination::{
        SolarObservation, ephemeris_fallback, ephemeris_fallback_at,
    };
    let fx = stewie_oracle::load("solar_cases").unwrap().payload;
    let eph = Ephemeris::bundled().unwrap();
    let ec = stewie_oracle::load("ephem_topocentric").unwrap().payload;
    let site = LatLon {
        lat_deg: f(&ec["sites"]["haworth"]["lat_deg"]),
        lon_deg: f(&ec["sites"]["haworth"]["lon_deg"]),
    };
    let position = body_fixed(
        Sphere::new(f(&ec["moon_radius_km"]) * 1000.0).unwrap(),
        site,
        0.0,
    );
    let check = |o: &SolarObservation, w: &Value, tol: f64, tag: &str| {
        for (g, k) in [
            (o.azimuth_deg, "azimuth_deg"),
            (o.elevation_deg, "elevation_deg"),
            (o.variance_azimuth_deg2, "variance_azimuth_deg2"),
            (o.variance_elevation_deg2, "variance_elevation_deg2"),
        ] {
            assert!((g - f(&w[k])).abs() <= tol, "{tag} {k}: {g}");
        }
        assert_eq!(
            o.source.name(),
            w["source"].as_str().unwrap(),
            "{tag} source"
        );
        assert_eq!(
            o.covariance_calibrated,
            w["covariance_calibrated"].as_bool().unwrap(),
            "{tag} calibrated"
        );
        assert_eq!(o.sample_id, w["sample_id"].as_str().unwrap(), "{tag} id");
        assert_eq!(
            o.coordinate_frame,
            w["coordinate_frame"].as_str().unwrap(),
            "{tag} frame"
        );
        assert_eq!(
            o.provenance,
            w["provenance"].as_str().unwrap(),
            "{tag} provenance"
        );
    };
    let mut from_ephemeris = 0;
    for c in fx["cases"].as_array().unwrap() {
        let s = &c["sun"];
        let sid = c["sample_id"].as_str().unwrap();
        let sig = (f(&c["sigmas"][0]), f(&c["sigmas"][1]));
        let sun = AzEl {
            az_deg: f(&s["az_deg"]),
            el_deg: f(&s["el_deg"]),
        };
        let o = ephemeris_fallback(sun, sid, sig, c["calibrated"].as_bool().unwrap()).unwrap();
        check(&o, &c["observation"], 1e-12, sid);
        if let Some(utc) = s["utc"].as_str() {
            let r = ephemeris_fallback_at(
                &eph,
                (site, position),
                &Utc::parse_iso8601(utc).unwrap(),
                sid,
                sig,
            )
            .unwrap();
            check(
                &r,
                &c["observation"],
                1e-6,
                &format!("{sid} from the Rust ephemeris"),
            );
            from_ephemeris += 1;
        }
    }
    assert!(
        from_ephemeris >= 2,
        "vacuity: fallbacks built from the Rust ephemeris"
    );
    for r in fx["refusals"].as_array().unwrap() {
        let sun = AzEl {
            az_deg: f(&r["az_deg"]),
            el_deg: f(&r["el_deg"]),
        };
        let err = ephemeris_fallback(
            sun,
            r["sample_id"].as_str().unwrap(),
            (f(&r["sigmas"][0]), f(&r["sigmas"][1])),
            false,
        )
        .unwrap_err();
        assert_eq!(err, r["error"].as_str().unwrap());
    }
}
