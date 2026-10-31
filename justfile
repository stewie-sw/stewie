# STEWIE task runner. `just check` runs the Rust gate exactly as CI does.
check: fmt-check clippy test no-stubs

fmt-check:
    cargo fmt --all --check

clippy:
    cargo clippy --workspace --all-targets -- -D warnings

test:
    cargo test --workspace

no-stubs:
    cargo run -q -p xtask -- no-stubs
