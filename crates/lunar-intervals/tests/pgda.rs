//! Requirement R5 (RW-61): long-run solar visibility from the engine agrees with PGDA product 69
//! (`AVGVISIB_85S_060M_201608`, Mazarico et al. 2011) within the protocol tolerance at every catalog site the
//! map covers. Terrain is the real LOLA stack (`LDEM_85S_40M` > `LDEM_75S_240M` > `LDEM_16`); the observer is the
//! PGDA pixel centre; "visible" is any part of the solar disk above the terrain horizon, as in the product.

use lunar_dem::{GlobalGrid, PolarGrid, Resolved, TerrainSource, TerrainStack};
use lunar_ephem::{Body, Ephemeris, Utc};
use lunar_frames::{LatLon, Sphere};
use lunar_horizon::{HorizonConfig, horizon};
use lunar_intervals::{VisibilityConfig, verdict_fractions};

fn moon() -> Sphere {
    let reg: serde_json::Value =
        serde_json::from_str(include_str!("../../stewie-contracts/fixtures/bodies.json")).unwrap();
    Sphere::new(reg["moon"]["ellipsoid_radius_m"].as_f64().unwrap()).unwrap()
}

fn south_polar_stack() -> TerrainStack {
    let d = stewie_oracle::repo_root().join(".cache/terrain");
    let polar = |n: &str| {
        Box::new(
            PolarGrid::open(
                &d.join(format!("{n}.img")),
                &d.join(format!("{n}.lbl")),
                moon(),
            )
            .unwrap(),
        ) as Box<dyn TerrainSource>
    };
    TerrainStack::new(vec![
        (1, polar("ldem_85s_40m")),
        (2, polar("ldem_75s_240m")),
        (
            3,
            Box::new(
                GlobalGrid::open(&d.join("ldem_16.img"), &d.join("ldem_16.lbl"), moon()).unwrap(),
            ),
        ),
    ])
}

/// Run the R5 protocol on `stack`; `near_tier` is the 40 m source each observer must stand on.
#[allow(clippy::cast_possible_truncation, clippy::cast_sign_loss)]
fn r5_on(stack: &TerrainStack, near_tier: &dyn Fn(&str, &str) -> bool) {
    let fx = stewie_oracle::load("pgda_avgvisib").unwrap().payload;
    let p = &fx["protocol"];
    let num = |k: &str| p[k].as_f64().unwrap();
    let eph = Ephemeris::bundled().unwrap();
    let t0 = eph.tdb(&Utc::parse_iso8601(p["start_utc"].as_str().unwrap()).unwrap());
    let t1 = t0 + num("span_days") * 86_400.0;
    let hcfg = HorizonConfig {
        n_az: num("n_az") as usize,
        max_range_m: num("max_range_m"),
        step_m: num("step_m"),
        eye_height_m: num("eye_m"),
        start_m: num("start_m"),
    };
    let sites = fx["sites"].as_array().unwrap();
    assert_eq!(sites.len(), 12, "catalog sites inside the 85S map");
    // vacuity guard: agreement on permanently shadowed pixels alone would prove nothing
    let sunlit = sites
        .iter()
        .filter(|s| s["visibility"].as_f64().unwrap() > 0.1)
        .count();
    assert!(
        sunlit >= 8,
        "only {sunlit} sites with PGDA visibility above 10%"
    );
    let mut failures = Vec::new();
    for s in sites {
        let name = s["name"].as_str().unwrap();
        let at = LatLon {
            lat_deg: s["pixel"]["lat_deg"].as_f64().unwrap(),
            lon_deg: s["pixel"]["lon_deg"].as_f64().unwrap(),
        };
        let Resolved::Covered { height_m, source } = stack.resolve(at) else {
            panic!("{name}: not covered");
        };
        assert!(
            near_tier(&source.id, name),
            "{name}: observer on {}",
            source.id
        );
        let h = horizon(stack, at, &hcfg).unwrap();
        assert!(h.complete.iter().all(|&c| c), "{name}: every ray complete");
        let cfg = VisibilityConfig {
            sample_s: num("step_s"),
            tolerance_s: 1.0,
            eye_height_m: num("eye_m"),
            ground_height_m: height_m,
            moon: moon(),
        };
        let f = verdict_fractions(&eph, &h, at, Body::Sun, t0, t1, &cfg).unwrap();
        assert!(
            f.unknown == 0.0,
            "{name}: complete horizon leaves nothing unknown"
        );
        let want = s["visibility"].as_f64().unwrap();
        println!(
            "{name:22} engine {:.3} pgda {want:.3} d {:+.3}",
            f.lit,
            f.lit - want
        );
        if (f.lit - want).abs() > num("tolerance") {
            failures.push(format!("{name}: engine {:.3} vs PGDA {want:.3}", f.lit));
        }
    }
    assert!(failures.is_empty(), "outside R5 tolerance: {failures:#?}");
}

#[test]
fn long_run_sun_visibility_matches_pgda_product_69() {
    r5_on(&south_polar_stack(), &|id, _| id == "ldem_85s_40m");
}

/// The device package (40 m crops around each site over the 240 m tier and `LDEM_16`) must still pass R5:
/// it is what the browser and tablet answer with (D-R47).
#[test]
fn the_device_package_also_meets_r5() {
    let pkg = stewie_package::Package::open(
        &stewie_oracle::repo_root().join(".cache/package/south_polar_sites"),
        moon(),
    )
    .unwrap();
    // crops overlap (Haworth and its SFS site); any 40 m crop is an exact subset of the full grid
    r5_on(pkg.stack(), &|id, _| id.starts_with("ldem_85s_40m_"));
}
