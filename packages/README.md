# packages/ — STEWIE monorepo workspace (uv/hatch)

One repo, one shared version, multiple installable distributions. Only TWO are prepared for public PyPI +
citation; the rest stay INTERNAL workspace packages (coupling is architectural). Design:
`../docs/packaging_strategy.md` + `../docs/interface_contracts.md`.

Import DAG (enforced by `scripts/test_import_boundaries.py`):

```
stewie-bodies  -> numpy/scipy only            (NO STEWIE dep)          PUBLIC
stewie-forge   -> stewie-bodies + numeric      (PhysicsBackend, geotech) PUBLIC
stewie-leap    -> core + bodies + forge                                 internal
stewie-lode    -> core + bodies + forge + leap                          internal
stewie-dart    -> core + leap + lode                                    internal
stewie-core    -> contracts/twin/base-runtime  (NO dart/lode/leap)      internal
apps/*         -> import packages, never the reverse
```

Progress (2026-07-03): the three edges are broken (BD-04 / PX-05 / AP-01) and the PO-16 uv workspace
skeleton is in place. **`stewie-bodies` is EXTRACTED** (PO-17): it ships here as a standalone
zero-dependency package, with `stewie/specs/bodies.py` reduced to a verbatim re-export shim (every caller
unchanged), verified through the Docker backend image build (in-container import smoke passed).
**PO-18 `stewie-forge` is next**; the remaining members land here as their rows execute.
