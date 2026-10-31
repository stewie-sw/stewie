//! lunar-ephem against SPICE (stewie-oracle `ephem_topocentric`: 10,000 random epochs 2026-2035 at three
//! catalog sites, `str2et` and `spkcpo` LT+S in `MOON_ME_DE440_ME421`). Requirement R3: Sun and Earth
//! directions within 0.005 deg of SPICE.

use lunar_ephem::{Body, EphemError, Ephemeris, Utc, az_el};
use lunar_frames::{LatLon, Sphere, body_fixed};

fn eph() -> Ephemeris {
    Ephemeris::bundled().unwrap()
}

fn angle_deg(a: [f64; 3], b: [f64; 3]) -> f64 {
    let dot = a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
    let cross = [
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    ];
    (cross[0].hypot(cross[1]).hypot(cross[2]))
        .atan2(dot)
        .to_degrees()
}

fn vec3(v: &serde_json::Value) -> [f64; 3] {
    let a = v.as_array().unwrap();
    [
        a[0].as_f64().unwrap(),
        a[1].as_f64().unwrap(),
        a[2].as_f64().unwrap(),
    ]
}

#[test]
fn utc_to_tdb_matches_spice_str2et() {
    let fx = stewie_oracle::load("ephem_topocentric").unwrap().payload;
    let e = eph();
    let mut worst = 0.0f64;
    for s in fx["samples"].as_array().unwrap() {
        let utc = Utc::parse_iso8601(s["utc"].as_str().unwrap()).unwrap();
        worst = worst.max((e.tdb(&utc) - s["tdb"].as_f64().unwrap()).abs());
    }
    assert!(worst < 1e-6, "worst UTC->TDB error {worst} s");
}

#[test]
fn sun_and_earth_directions_match_spice_within_r3() {
    let fx = stewie_oracle::load("ephem_topocentric").unwrap().payload;
    let e = eph();
    let moon = Sphere::new(fx["moon_radius_km"].as_f64().unwrap() * 1000.0).unwrap();
    let (mut worst_sun, mut worst_earth, mut n) = (0.0f64, 0.0f64, 0);
    for s in fx["samples"].as_array().unwrap() {
        let site = &fx["sites"][s["site"].as_str().unwrap()];
        let ll = LatLon {
            lat_deg: site["lat_deg"].as_f64().unwrap(),
            lon_deg: site["lon_deg"].as_f64().unwrap(),
        };
        let obs = body_fixed(moon, ll, 0.0);
        let tdb = s["tdb"].as_f64().unwrap();
        let sun = e.apparent_from(Body::Sun, tdb, obs).unwrap();
        let earth = e.apparent_from(Body::Earth, tdb, obs).unwrap();
        worst_sun = worst_sun.max(angle_deg(sun, vec3(&s["sun_m"])));
        worst_earth = worst_earth.max(angle_deg(earth, vec3(&s["earth_m"])));
        n += 1;
    }
    assert_eq!(n, 10_000);
    assert!(
        worst_sun < 0.005 && worst_earth < 0.005,
        "sun {worst_sun} deg, earth {worst_earth} deg"
    );
    eprintln!("R3 worst: sun {worst_sun:e} deg, earth {worst_earth:e} deg");
    // Tripwire at 2x the measured worst (sun 6.8e-8 deg, earth 5.1e-6 deg on 2026-10-31) so a regression is
    // visible long before R3 fails. The earth residual is not yet explained (open item in DECISIONS D-R29).
    assert!(
        worst_sun < 1e-5 && worst_earth < 1e-5,
        "sun {worst_sun} deg, earth {worst_earth} deg"
    );
}

#[test]
fn az_el_of_spice_vectors_agree_with_ours() {
    let fx = stewie_oracle::load("ephem_topocentric").unwrap().payload;
    let e = eph();
    let moon = Sphere::new(fx["moon_radius_km"].as_f64().unwrap() * 1000.0).unwrap();
    for s in fx["samples"].as_array().unwrap().iter().take(500) {
        let site = &fx["sites"][s["site"].as_str().unwrap()];
        let ll = LatLon {
            lat_deg: site["lat_deg"].as_f64().unwrap(),
            lon_deg: site["lon_deg"].as_f64().unwrap(),
        };
        let ours = az_el(
            e.apparent_from(
                Body::Sun,
                s["tdb"].as_f64().unwrap(),
                body_fixed(moon, ll, 0.0),
            )
            .unwrap(),
            ll,
        );
        let spice = az_el(vec3(&s["sun_m"]), ll);
        assert!((ours.el_deg - spice.el_deg).abs() < 1e-5);
        assert!(((ours.az_deg - spice.az_deg + 540.0) % 360.0 - 180.0).abs() < 1e-3);
        assert!((0.0..360.0).contains(&ours.az_deg) && (-90.0..=90.0).contains(&ours.el_deg));
    }
}

#[test]
fn epochs_outside_the_packed_span_are_errors_not_values() {
    let e = eph();
    for iso in ["2025-12-31T23:59:00Z", "2036-01-01T00:01:00Z"] {
        let tdb = e.tdb(&Utc::parse_iso8601(iso).unwrap());
        assert!(
            matches!(
                e.position(Body::Sun, tdb),
                Err(EphemError::OutOfSpan { .. })
            ),
            "{iso}"
        );
    }
}

#[test]
fn a_tampered_package_is_refused() {
    let dir = std::env::temp_dir().join(format!("lunar-ephem-tamper-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).unwrap();
    let data = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("data");
    std::fs::copy(
        data.join("moon_de440_2026_2035.json"),
        dir.join("moon_de440_2026_2035.json"),
    )
    .unwrap();
    let mut bin = std::fs::read(data.join("moon_de440_2026_2035.bin")).unwrap();
    bin[1000] ^= 0x01; // synthetic one-bit corruption
    std::fs::write(dir.join("moon_de440_2026_2035.bin"), bin).unwrap();
    assert!(matches!(
        Ephemeris::load(&dir, "moon_de440_2026_2035"),
        Err(EphemError::Integrity { .. })
    ));
}

#[test]
fn malformed_utc_is_rejected() {
    for bad in [
        "2026-13-01T00:00:00Z",
        "2026-02-30T00:00:00Z",
        "2026-01-01 00:00:00",
        "2026-01-01T24:00:00Z",
        "",
    ] {
        assert!(Utc::parse_iso8601(bad).is_err(), "{bad:?}");
    }
}
