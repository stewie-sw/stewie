# STEWIE packaging strategy — monorepo workspace, two public packages (2026-07-03)

**Decision (Aaron + Claude + Codex).** STEWIE remains ONE repo. It becomes a **uv/hatch workspace** exposing
multiple installable distributions for development ergonomics, but only the two low-coupling research
artifacts — **`stewie-forge`** and **`stewie-bodies`** — are prepared for public PyPI release and citation.
DART, LODE, LEAP, and `stewie-core` remain **internal** workspace packages because their coupling is
architectural, not accidental.

> STEWIE will remain a monorepo workspace. The project will expose multiple installable Python distributions
> for development ergonomics, but only the two low-coupling research artifacts — `stewie-forge` and
> `stewie-bodies` — will be prepared for public release and citation. DART, LODE, LEAP, and `stewie-core`
> remain internal workspace packages because their coupling is architectural rather than accidental.

Governing rule: **if a package needs the STEWIE world model, runtime server, ROS graph, or layer manifest to
make sense, keep it internal. If a planetary-robotics researcher could use it without STEWIE, publish it.**
Today that means `bodies` and `forge` are publishable; everything else stays workspace-internal.

## Progress (2026-07-03)

Phase 1 of the extraction is landed on `feat/platform-restructure` (committed, NOT pushed, NOT deployed;
`main` untouched):

- **Edges broken.** BD-04 inverted the `bodies → physics` edge: the body → `TerramechanicsParams`
  conversion moved to `stewie/physics/body_params.py` (physics → bodies direction), and
  `stewie/specs/bodies.py` imports no `stewie.physics` at module level. PX-04 added the `PhysicsBackend`
  protocol + `Tier2NumpyBackend` (`stewie/physics/backend.py`, byte-identical passthrough). PX-05 added an
  executable production-physics import guard (`scripts/test_import_boundaries.py`). AP-01 broke the
  `core ↔ dart/leap` cycle: the composing runtime loops + routers now import dart/leap lazily / under
  `TYPE_CHECKING`. **The dependency graph is now acyclic.**
- **Workspace skeleton (PO-16).** Additive `[tool.uv.workspace]` in the root `pyproject.toml` (dev tooling
  only; build backend stays setuptools; Docker + editable install unchanged) + the `packages/README.md` DAG
  declaration + a forge import-DAG guard test.
- **`stewie-bodies` extracted (PO-17).** The pure-stdlib body/regolith registry now ships as a standalone
  zero-dependency package at `packages/stewie-bodies/` (own `pyproject.toml`); `stewie/specs/bodies.py` is a
  verbatim re-export shim (every caller unchanged) that keeps the physics-dependent `params_for_body`
  wrapper. Verified through the Docker backend image build (built + in-container import smoke passed); the
  dev venv, `deploy/Dockerfile.backend`, and CI (×4 jobs) install surfaces are updated.
- **Next: PO-18** extract `stewie-forge`; then Stage 3 publishes `stewie-bodies` + `stewie-forge`.

## Target repo structure

```
stewie/                       # repo (GitHub name stays "stewie")
  pyproject.toml              # workspace root: uv/hatch, shared lint/type/test, NO runtime code
  uv.lock · README · LICENSE · CITATION.cff
  packages/
    stewie-core/    src/stewie_core/    {contracts, runtime(base), twin}      # internal
    stewie-dart/    src/stewie_dart/    {perception, navigation, autonomy, sensors}   # internal
    stewie-lode/    src/stewie_lode/    {mapping, planning, traversability, world}     # internal
    stewie-leap/    src/stewie_leap/    {localization, estimation, fusion}    # internal (maybe later)
    stewie-bodies/  src/stewie_bodies/  {body_profile, registry, units, data/*.yaml}   # PUBLIC/citable
    stewie-forge/   src/stewie_forge/   {planetgroundhog/*, terramechanics/*, backends/*, costmaps/*}  # PUBLIC/citable
  apps/       {api-server, operator-console, notebooks}   # compose packages; never imported BY packages
  ros2/       {stewie_msgs, stewie_bringup, stewie_description}
  simulation/ {gazebo, chrono, scenarios}
  godot/      {project.godot, scenes}
  data/       {lunar, mars, earth, samples}
  tests/      {integration, system}
  .github/workflows/ {test, build, publish}
```

## Target dependency DAG (a strict, acyclic layering)

```
stewie-bodies   → numpy/scipy only              (base; NO STEWIE dep)
stewie-forge    → bodies + numeric only         (analytical physics; Chrono is [chrono] extra)
stewie-leap     → core, bodies, forge
stewie-lode     → core, bodies, forge, leap
stewie-dart     → core, leap, lode
stewie-core     → contracts/twin/base-runtime   (must NOT import dart/lode/leap)
apps/*          → import packages, never the reverse
```

## ⚠ Current dependency reality — three edges to break FIRST (measured 2026-07-03)

The DAG above is the target; the current code violates it in three specific places. Contract-first
extraction must fix these BEFORE any folder move, or the split creates import cycles.

**Update (2026-07-03): all three edges are now broken (BD-04, PX-05, AP-01); see the Progress section above.**

1. **`bodies → forge` is inverted.** `stewie/specs/bodies.py:29` does `from stewie.physics.terramechanics
   import TerramechanicsParams`. Bodies must have ZERO STEWIE deps. **Fix:** `BodyProfile` carries only raw
   regolith params (the Bekker tuple, cohesion, density, provenance); `forge` builds `TerramechanicsParams`
   FROM a `BodyProfile`. Invert the edge → `forge` depends on `bodies`, never the reverse.
2. **`core ↔ dart/leap` cycle.** `stewie/runtime/nav_loop.py:16` + `replay_loop.py:27` import
   `dart.hazard_map`; `stewie/server/routers/evidence.py` + `siteplan.py` import `dart`/`leap` — while
   dart/leap import core back. **Fix:** these are ORCHESTRATION/API code that COMPOSE the subsystems, i.e.
   they belong in `apps/api-server`, NOT in `stewie-core`. Move the composing runtime loops + the composing
   routers to the app layer; `stewie-core` keeps only contracts + twin + base-runtime primitives that
   dart/lode/leap depend on. (This matches the `apps/api-server` box in the structure — the server is an app,
   not core.)
3. **The terramechanics destined for `forge` imports dart/leap.** `stewie/physics/*` pulls
   `dart.articulated_*`, `leap.skill_env`, etc. Only the pure geotech (`forge/bearing.py` — already math-only,
   zero deps) and the Bekker/sinkage/slip/compaction primitives are clean. **Fix:** extract ONLY the
   dart/leap-free geotech + terramechanics into `stewie-forge`; leave the coupled physics (postures,
   excavation-state that reach into dart/leap) in `stewie-core` or the owning subsystem.

These three fixes ARE the substance of Stage 1 (the PX/BD refactor). They are principled, not messy —
`forge/bearing.py` is already pure, and inverting `bodies↔forge` is one clean interface change.

## Contract-first extraction sequence

The order is: **contracts → tests → folder move → package metadata → publish.** Define + test the public
interfaces first; the folder move is then mechanical and verified.

- **Phase 0 — freeze boundaries.** Write `docs/packaging_strategy.md` (this) + `docs/interface_contracts.md`
  (the public APIs + dependency rules). Fix names: `stewie-bodies`, `stewie-forge`. Mark DART/LODE/LEAP/core
  internal. Record the three edges above as the acceptance for Stage 1.
- **Stage 1 — PX/BD refactor (breaks the edges).** Extract the `PhysicsBackend` protocol (into `forge`, not
  core — it is physics) + the `BodyProfile`/registry. Make gravity/body/soil/regolith explicit. **Break edge
  #1 (invert bodies↔forge), edge #3 (pull dart/leap-free geotech into forge).** Gate: every current physics/
  planner/costmap test still green through the new interfaces; `bodies` imports nothing STEWIE; `forge`
  imports only `bodies` + numpy/scipy.
- **Stage 2 — workspace packaging.** Convert to uv/hatch workspace: shared version, shared lint/type/test,
  root has NO runtime code; each package gets its own `pyproject.toml` + `src/` + `tests/` + `README`.
  **Break edge #2 (move composing runtime/routers to `apps/api-server`).** Gate: `import` graph is acyclic
  in the target direction; editable installs per package work.
- **Stage 3 — publish only the clean packages.** `stewie-bodies 0.1.0`, then `stewie-forge 0.1.0`. NOT
  core/dart/lode/leap.
- **Stage 4 — keep the coupled core integrated.** Do NOT split DART/LODE/LEAP/core into independent repos; do
  NOT re-decompose into the 7 domains.

## PyPI + citation

- Public names: `stewie-bodies` (planetary body + regolith profiles), `stewie-forge` (planetary geotech /
  terramechanics). Optional later aliases: `planetary-bodies`, `planetgroundhog`.
- Each public package ships `README` + `CITATION.cff` + a Zenodo DOI + an examples notebook + a minimal docs
  site. Versioning: one monorepo version overall; **semver applies to the public `forge`/`bodies` APIs only.**
- GitHub repo stays `stewie`; publish workflow builds ONLY `packages/stewie-bodies` + `packages/stewie-forge`.

Sequencing note: this is Stage 1-4 of the packaging track; it composes with — does not replace — the GeoLibre
frontend rewrite (`geolibre_rewrite_plan_2026-07-03.md`). Stage 1 (PX/BD) is shared with the rewrite's
parallel physics/body track, so it is done once and serves both. Interface contracts:
`docs/interface_contracts.md`.

## 7. Implementation order, version ladder, scope guards (2026-07-03)

Exact order (contract-first): (1) workspace skeleton → (2) move body constants → `stewie-bodies` → (3) move
the dart/leap-free geotech → `stewie-forge` → (4) replace direct imports with the public interfaces → (5)
contract tests → (6) examples → (7) docs → (8) CI (import-boundary + build + smoke) → (9) publish
`stewie-bodies` → (10) publish `stewie-forge`. **Steps 2-4 ARE the three edge-breaks in §"Current dependency
reality".**

MVP public API — concept-first, body-aware, formula-transparent (users import CONCEPTS, not folders):

```python
from stewie_bodies import get_body
from stewie_forge import estimate_sinkage, estimate_excavation_energy
moon = get_body("moon")
estimate_sinkage(body=moon, load_n=120.0, contact_area_m2=0.04)   # regolith defaults to body.regolith
```
`from stewie_forge import estimate_sinkage` — NEVER `from stewie_forge.terramechanics.bekker_wong import ...`.

Import-boundary policy (a CI test enforces this — it is HOW the three edges stay broken):
- ALLOWED: `forge→bodies` · `lode/leap→forge` · `dart→leap` · `apps→everything`.
- FORBIDDEN: `bodies→anything-STEWIE` · `forge→ROS/Gazebo/Godot/GeoLibre` · `core→dart/lode/leap` ·
  `public→internal`.
Optional integrations behind extras: `[chrono]`, `[geo]`=geopandas/rasterio/shapely, `[dev]`, `[docs]`,
`[notebooks]`.

Version ladder: `0.1.x` experimental · `0.2.x` stable BodyProfile+RegolithProfile · `0.3.x` stable analytical
forge formulas · `0.4.x` costmap API · `1.0.0` = cited dissertation baseline. Semver applies to the public API
ONLY.

### Two decisions on the research-ecosystem layer

- **`stewie-specs` (language-independent schemas): DEFER.** pydantic already EXPORTS JSON Schema from the
  BodyProfile / RegolithProfile / result dataclasses for free — so the interop "common language" for
  ROS2/GeoLibre/Chrono comes from the Python models with ONE source of truth. A separate hand-authored specs
  package adds a SECOND source of truth (drift risk) and only earns its keep WHEN a non-Python (Rust/C++)
  consumer implements the schema independently. Until then, pydantic-schema-export IS the spec. Revisit when a
  second-language consumer appears.
- **Research ecosystem (datasets / benchmarks / planet-registry / papers): right north star, not buildable
  yet.** It is earned by shipping bodies + forge + a software paper FIRST — a benchmark cannot precede the
  library it evaluates, and a dataset DOI follows real use. Record the vision; act only on Stage 1. Do NOT
  scaffold the six speculative planning docs / example stubs / publish-CI for packages that do not exist yet —
  write each WHEN its stage arrives (release_plan/citation/checklist in Stage 3, CI in Stage 2).
  Over-scaffolding now is the fragmentation this strategy exists to prevent.

## 8. Publication tracks + dissertation framing (2026-07-03)

Core claim (framing of record): **STEWIE is not only a simulator — it is a planetary construction research
stack: a GIS world model + body-aware geotechnics + terramechanics validation + ROS2 autonomy + digital-twin
visualization + reproducible benchmarks.**

Five publishable tracks, sequenced by what is SHIPPABLE (not by ambition):

- **A — `stewie-bodies`** — software paper "A Planetary Body and Regolith Profile Registry for Robotics
  Simulation"; PyPI + DOI + docs. **Shippable now** from the existing `bodies.py`.
- **B — `stewie-forge` / PlanetGroundhog** — software paper "Body-Aware Geotechnical and Terramechanics
  Models for Planetary Construction"; PyPI + validation notebook + DOI. **Shippable now** from `forge` +
  `terramechanics`.
- **C — benchmark** — "Benchmarking Planetary Excavation and Traversability Under Low-Gravity Regolith";
  datasets + scenarios + metrics. **Needs A+B first** — a benchmark cannot precede the library it evaluates.
- **D — STEWIE** — journal "A GIS-Physics-Robotics Digital Twin for Autonomous Lunar Construction";
  integrated system + demonstrations.
- **E — ARGUS** — "Articulated Rover Geometry for Unified State Estimation in Lunar Excavation Rovers";
  **THE dissertation contribution.**

Dissertation chapters (minimum viable): 1 problem/motivation · 2 related work · 3 STEWIE architecture ·
4 stewie-bodies · 5 stewie-forge/PlanetGroundhog · 6 ARGUS localization · 7 experiments + benchmark ·
8 conclusions.

★ **EFFORT-ALLOCATION GUARD:** ARGUS (E) is the dissertation contribution; bodies/forge/STEWIE (A/B/D) are
supporting, citable INFRASTRUCTURE. Foreground the ARGUS research, background the infra — a committee wants a
novel state-estimation contribution, not "I built a lot of software." The packaging/ecosystem work is a
high-value side-product; it must not displace ARGUS research time. Publish A/B as quick citable wins from
already-working code, then spend the bulk on ARGUS.

## 9. Deferred / post-dissertation scope (2026-07-03) — recorded as VISION, not plan

None of this is built before a shipped bodies/forge + ARGUS. Captured so it is not lost, explicitly deferred:

- **Website/citation surfaces.** `stewie.dev` + `/docs`,`/forge`,`/bodies`,`/benchmarks`,`/data`,`/papers`
  now; promote to subdomains (`forge.`,`bodies.`,`benchmarks.`) only when a surface has independent
  users/docs/releases/citations. Repos separate engineering · subdomains separate audiences · PyPI separates
  reusable code · DOIs separate citable artifacts. Low-stakes; keep the monorepo.
- **Mission Operations Center UI** (multi-panel Godot/RViz/GeoLibre/Forge grid + mission clock + color-code +
  synchronized playback + phase workspaces Survey→Analyze→Plan→Rehearse→Execute→Reconcile): strong FUTURE
  operator vision that MOSTLY already exists as the ConOps cockpit spine. ⚠ CONTRADICTION to resolve: "Godot as
  the mission-control shell embedding the others" conflicts with the DECIDED GeoLibre 2D **web** operator UI.
  Pick one operator shell — the web cockpit is decided; Godot stays a specialized sim/render sidecar. Do not
  build both.
- **Capability-based heterogeneous fleet** (Mission→Task→Capability→Asset; RobotProfile/AssetProfile;
  capability matrix + plugins; World→Assets→Capabilities): a sound GENERALIZATION of STEWIE's existing
  multi-vehicle planner, but far beyond the single-articulated-rover dissertation. Post-dissertation scope —
  record, do NOT build now; it would gold-plate infra while ARGUS waits.

Guard: no new planning artifacts until Stage 1 has shipped code.
