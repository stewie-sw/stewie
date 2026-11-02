//! [REQ:RT-06] [REQ:RT-07] The public stream runs under `godot_sim`: it must be unable to command a real rover. As
//! the Python's AST guard proved its module could not name a real-rover egress, the Rust makes it structural: the
//! `stewie-stream` binary's dependency closure (from `cargo metadata`) holds no rover-command (`stewie-server`),
//! plan-lowering (`stewie-plan`), plugin-host (`stewie-plugins`, which can start the ROS 2 plugin) or ROS crate.
//! A positive control checks the walk does see such a dependency where one exists.

use std::collections::{BTreeSet, HashMap};

use serde_json::Value;

/// The names in a package's normal (non-dev) dependency closure.
fn closure(meta: &Value, root: &str) -> BTreeSet<String> {
    let name_of: HashMap<&str, &str> = meta["packages"]
        .as_array()
        .unwrap()
        .iter()
        .map(|p| (p["id"].as_str().unwrap(), p["name"].as_str().unwrap()))
        .collect();
    let nodes: HashMap<&str, &Value> = meta["resolve"]["nodes"]
        .as_array()
        .unwrap()
        .iter()
        .map(|n| (n["id"].as_str().unwrap(), n))
        .collect();
    let start = name_of
        .iter()
        .find(|(_, n)| **n == root)
        .map(|(id, _)| *id)
        .unwrap();
    let (mut seen, mut todo) = (BTreeSet::new(), vec![start]);
    while let Some(id) = todo.pop() {
        if !seen.insert(id) {
            continue;
        }
        for d in nodes[id]["deps"].as_array().unwrap() {
            // a dep reached only as a dev- or build-dependency is not linked into the binary
            if d["dep_kinds"]
                .as_array()
                .unwrap()
                .iter()
                .any(|k| k["kind"].is_null())
            {
                todo.push(d["pkg"].as_str().unwrap());
            }
        }
    }
    seen.into_iter().map(|id| name_of[id].to_owned()).collect()
}

fn forbidden(names: &BTreeSet<String>) -> Vec<&String> {
    names
        .iter()
        .filter(|n| {
            ["stewie-server", "stewie-plan", "stewie-plugins", "r2r"].contains(&n.as_str())
                || n.starts_with("ros")
                || n.starts_with("rcl")
                || n.contains("-ros")
                || n.contains("ros2")
        })
        .collect()
}

#[test]
fn the_stream_links_no_real_rover_egress() {
    let out =
        std::process::Command::new(std::env::var("CARGO").unwrap_or_else(|_| "cargo".to_owned()))
            .args([
                "metadata",
                "--format-version",
                "1",
                "--offline",
                "--manifest-path",
            ])
            .arg(stewie_oracle::repo_root().join("Cargo.toml"))
            .output()
            .unwrap();
    assert!(
        out.status.success(),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
    let meta: Value = serde_json::from_slice(&out.stdout).unwrap();
    let stream = closure(&meta, "stewie-stream");
    assert!(
        stream.contains("stewie-twin") && stream.contains("axum"),
        "vacuity: the walk reaches real deps"
    );
    assert_eq!(forbidden(&stream), Vec::<&String>::new());
    // positive control: the rover-command server's closure is seen to hold them
    let server = closure(&meta, "stewie-server");
    assert!(forbidden(&server).len() >= 3, "{:?}", forbidden(&server));
}
