# STEWIE task runner. `just check` runs the Rust gate exactly as CI does.
check: fmt-check clippy test no-stubs

# Regenerate every oracle fixture; CI fails if the committed fixtures differ.
oracle:
    PYTHONNOUSERSITE=1 .venv/bin/python pipeline/fetch.py
    cd pipeline && PYTHONNOUSERSITE=1 ../.venv/bin/python ephem_pack.py
    cd oracle && PYTHONNOUSERSITE=1 ../.venv/bin/python build_fixtures.py

fmt-check:
    cargo fmt --all --check

clippy:
    cargo clippy --workspace --all-targets -- -D warnings

test:
    cargo test --workspace

no-stubs:
    cargo run -q -p xtask -- no-stubs
