# UltraBuild installation

**Artifact ID:** `ART-INSTALLATION`
**Producer node:** `INT-010`
**Consumers:** `ORCH-001`, `VERT-010`, `DISS-010`
**Status:** `complete_for_bounded_prototype`

UltraBuild requires Python 3.11 or newer. For the exact repository development environment:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/pip install --require-hashes -r requirements-dev.lock
.venv/bin/pip install -e packages/stewie-bodies --no-deps
.venv/bin/pip install -e packages/stewie-forge --no-deps
.venv/bin/pip install -e . --no-deps
```

`stewie-bodies` is a separately built workspace distribution and is intentionally excluded from the
third-party hash lock. The root package declares it as an unconditional dependency.

For a wheelhouse installation, build both required distributions:

```bash
python -m build --wheel --outdir /tmp/stewie-wheelhouse packages/stewie-bodies
python -m build --wheel --outdir /tmp/stewie-wheelhouse .
python3 -m venv /tmp/stewie-installed
/tmp/stewie-installed/bin/pip install \
  --find-links /tmp/stewie-wheelhouse 'stewie[ultrabuild]==0.1.0'
```

Verify the installation:

```bash
.venv/bin/stewie-ultrabuild demo --output /tmp/stewie-demo
.venv/bin/stewie-ultrabuild verify \
  --database /tmp/stewie-demo/world-state.sqlite3 \
  --payloads /tmp/stewie-demo/payloads
```

The `ultrabuild` extra adds JSON Schema validation. The opt-in clean-wheel regression builds both
workspace wheels, installs only the root requirement from the wheelhouse, and executes the installed
entry point outside the source tree.
