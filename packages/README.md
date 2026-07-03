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

Extraction order (edges already broken — BD-04/PX-05/AP-01): PO-17 `stewie-bodies` → PO-18 `stewie-forge`.
Members land here as those rows execute; until then this is the declared skeleton (no source has moved).
