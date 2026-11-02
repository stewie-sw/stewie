//! RW-51c: the articulation-parallax fix on the committed real two-posture Godot render pair equals the Python's
//! (`render_pair_cases`) for every camera of the rig and three seed drifts: the same confident features, the same
//! RANSAC consensus (numpy's `default_rng(0)` draws), the fix to 1e-9, or the same refusal.

use serde_json::Value;
use stewie_perceive::parallax::{Camera, Gray, Heightfield, localize_on_render_pair};

fn repo() -> std::path::PathBuf {
    stewie_oracle::repo_root()
}

fn gray(path: &std::path::Path) -> Gray {
    let mut reader = png::Decoder::new(std::io::BufReader::new(std::fs::File::open(path).unwrap()))
        .read_info()
        .unwrap();
    let mut buf = vec![0; reader.output_buffer_size().unwrap()];
    let info = reader.next_frame(&mut buf).unwrap();
    assert_eq!(
        info.color_type,
        png::ColorType::Rgb,
        "the committed pair is RGB"
    );
    Gray {
        // PIL's convert("L")
        px: buf[..info.buffer_size()]
            .chunks_exact(3)
            .map(|p| {
                f64::from(
                    (u32::from(p[0]) * 19595
                        + u32::from(p[1]) * 38470
                        + u32::from(p[2]) * 7471
                        + 0x8000)
                        >> 16,
                )
            })
            .collect(),
        width: info.width as usize,
        height: info.height as usize,
    }
}

fn close(got: f64, want: &Value, what: &str) {
    let want = want.as_f64().unwrap();
    assert!(
        (got - want).abs() <= 1e-9 * want.abs().max(1.0),
        "{what}: {got} vs {want}"
    );
}

#[test]
fn the_render_pair_fix_equals_the_pythons() {
    let fx = stewie_oracle::load("render_pair_cases").unwrap().payload;
    let dir = repo().join("stewie/godot/out/parallax");
    let read = |n: &str| -> Value {
        serde_json::from_str(&std::fs::read_to_string(dir.join(n)).unwrap()).unwrap()
    };
    let (a, b) = (read("A_sensors.json"), read("B_sensors.json"));
    let scene = repo().join("samples/crater_boulders");
    let raw = std::fs::read(scene.join("heightmap.rf32")).unwrap();
    let terrain = Heightfield {
        z: raw
            .chunks_exact(4)
            .map(|b| f64::from(f32::from_le_bytes([b[0], b[1], b[2], b[3]])))
            .collect(),
        width: 256,
        height: 256,
        cell_m: 0.02,
    };
    let dh = b["rover"]["position_m"][1].as_f64().unwrap()
        - a["rover"]["position_m"][1].as_f64().unwrap();
    let true_xy = [
        a["rover"]["position_m"][0].as_f64().unwrap(),
        a["rover"]["position_m"][2].as_f64().unwrap(),
    ];
    let (mut fixes, mut refusals) = (0, 0);
    for case in fx["cases"].as_array().unwrap() {
        let name = case["camera"].as_str().unwrap();
        let drift = case["drift_m"].as_f64().unwrap();
        let tag = format!("{name} drift {drift}");
        let meta = a["cameras"]
            .as_array()
            .unwrap()
            .iter()
            .find(|m| m["name"] == name)
            .unwrap();
        let f = |k: &str| meta["intrinsics"][k].as_f64().unwrap();
        let v3 = |k: &str, i: usize| meta["pose_in_world"][k][i].as_f64().unwrap();
        let cam = Camera {
            fx: f("fx"),
            fy: f("fy"),
            cx: f("cx"),
            cy: f("cy"),
            position: [
                v3("position_m", 0),
                v3("position_m", 1),
                v3("position_m", 2),
            ],
            quat_xyzw: [
                v3("quaternion_xyzw", 0),
                v3("quaternion_xyzw", 1),
                v3("quaternion_xyzw", 2),
                v3("quaternion_xyzw", 3),
            ],
        };
        let got = localize_on_render_pair(
            &gray(&dir.join("A").join(format!("{name}.png"))),
            &gray(&dir.join("B").join(format!("{name}.png"))),
            &terrain,
            &cam,
            dh,
            true_xy,
            drift,
        );
        if let Some(why) = case.get("error") {
            assert_eq!(got.unwrap_err(), why.as_str().unwrap(), "{tag}");
            refusals += 1;
            continue;
        }
        let got = got.unwrap();
        let want = &case["result"];
        assert_eq!(
            got.n_features,
            usize::try_from(want["n_features"].as_u64().unwrap()).unwrap(),
            "{tag}"
        );
        assert_eq!(
            got.inlier_ranges.len(),
            usize::try_from(want["n_inliers"].as_u64().unwrap()).unwrap(),
            "{tag}"
        );
        for i in 0..2 {
            close(got.fix_xy[i], &want["fix_xy"][i], &format!("{tag} fix"));
            close(got.seed_xy[i], &want["seed_xy"][i], &format!("{tag} seed"));
        }
        let r = |x: f64, n: i32| (x * 10f64.powi(n)).round() / 10f64.powi(n);
        close(
            r(got.fix_sigma_m, 3),
            &want["fix_sigma_m"],
            &format!("{tag} sigma"),
        );
        for (l, w) in got
            .inlier_landmarks
            .iter()
            .zip(want["landmarks_xy"].as_array().unwrap())
        {
            close(r(l[0], 2), &w[0], &format!("{tag} landmark x"));
            close(r(l[1], 2), &w[1], &format!("{tag} landmark y"));
        }
        fixes += 1;
    }
    // vacuity: both answers are exercised
    assert_eq!((fixes, refusals), (12, 12));
}
