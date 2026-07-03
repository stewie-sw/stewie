# stewie-bodies

Sourced per-body surface/regolith **terramechanics constants** for the STEWIE lunar-construction
environment: Moon, Mars, Ceres, Bennu, Phobos, Earth, and the GMRO BP-1 test bed. Every value is tagged
MEASURED / ESTIMATED / UNKNOWN with its citation (systematic review: `docs/bodies_sysrev.md`); nothing is
fabricated. **Zero STEWIE dependency** — pure-stdlib data + `get_body` / `body_in_regime`, so it is citable
and installable on its own. The body→`TerramechanicsParams` conversion lives in `stewie-forge`, not here.
