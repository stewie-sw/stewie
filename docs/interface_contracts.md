# STEWIE interface contracts — freeze before extraction (2026-07-03)

Contract-first rule: these public APIs + dependency rules are frozen FIRST; tests are written against them;
only THEN do folders move. The two publishable packages (`stewie-bodies`, `stewie-forge`) are the ones whose
contracts must be stable and semver'd. Companion: `docs/packaging_strategy.md`.

## 1. Public API — `stewie-bodies` (zero STEWIE deps)

```python
@dataclass(frozen=True)
class RegolithProfile:
    bulk_density_kg_m3: float | None
    cohesion_pa: float | None
    friction_deg: float | None
    repose_deg: float | None
    bekker: tuple[float, float, float] | None    # (k_c, k_phi, n) — RAW params, no forge dependency
    provenance: dict[str, str]                    # per-field MEASURED/ESTIMATED/ANALOG/UNKNOWN/CALIB
    regime: str                                   # "gravity-loaded" | "microgravity"

@dataclass(frozen=True)
class BodyProfile:
    id: str                                       # "moon"
    label: str
    gravity_m_s2: float
    regolith: RegolithProfile
    ellipsoid_radius_m: float | None
    crs: str | None                               # e.g. IAU_2015:30100
    reference_frame: str
    provenance: str

# functions
def get_body(body_id: str) -> BodyProfile: ...
def list_bodies() -> list[str]: ...
def register_body(profile: BodyProfile, *, source: str, replace: bool = False) -> None: ...
```

Data ships as YAML under `stewie_bodies/data/` (moon/mars/earth/asteroid...). **No numeric field may be
fabricated** — missing = `None` + provenance. `AtmosphereProfile` + `GravityModel` are optional extensions
(atmosphere is `None`/0 for airless bodies).

## 2. Public API — `stewie-forge` / PlanetGroundhog (deps: `stewie-bodies` + numpy/scipy)

```python
@dataclass(frozen=True)
class TerrainCell:                       # the analytical input unit
    slope_deg: float
    density_kg_m3: float | None
    roughness_m: float
    # ...body/regolith comes from a BodyProfile passed alongside

@dataclass(frozen=True)
class SinkageResult:      sinkage_m: float; pressure_pa: float; provenance: str
@dataclass(frozen=True)
class SlipResult:         slip: float; sinkage_m: float | None; traction_ok: bool; labels: tuple[str, ...]
@dataclass(frozen=True)
class BearingResult:      ultimate_pa: float; allowable_pa: float; factor_of_safety: float; provenance: str
@dataclass(frozen=True)
class ExcavationResult:   energy_j_per_kg: float; resistance_n: float; provenance: str
@dataclass(frozen=True)
class TraversabilityResult: cost: float; passable: bool; blocking: str
@dataclass(frozen=True)
class CostMap:            cost: "np.ndarray"; passable: "np.ndarray"; per_layer: dict[str, "np.ndarray"]

# analytical entrypoints (body-aware; every one takes a BodyProfile)
def estimate_sinkage(cell: TerrainCell, body: BodyProfile, load_n: float) -> SinkageResult: ...
def estimate_slip_risk(cell: TerrainCell, body: BodyProfile, *, payload_kg: float) -> SlipResult: ...
def estimate_bearing_capacity(cell: TerrainCell, body: BodyProfile, width_m: float) -> BearingResult: ...
def estimate_excavation_energy(volume_m3: float, body: BodyProfile) -> ExcavationResult: ...
def make_traversability_costmap(cells, body: BodyProfile) -> CostMap: ...

# earth-pressure — the one genuine Groundhog gap (active/passive/at-rest, body-aware, regime-flagged)
def earth_pressure(cell: TerrainCell, body: BodyProfile, *, state: str) -> float: ...

# backend seam (lives in forge, not core — it IS physics)
class PhysicsBackend(Protocol):
    def info(self) -> "PhysicsBackendInfo": ...        # id, authority_class, conserves_mass, modes, ...
    def supports(self, *, body: BodyProfile, mode: str, allow_analog: bool = False) -> "SupportVerdict": ...
    def resolve_soil_params(self, *, body: BodyProfile, allow_analog: bool = False) -> "SoilParams": ...
    def wheel_static_sinkage(self, ...) -> SinkageResult: ...
    def slip_equilibrium(self, ...) -> SlipResult: ...
    def allowable_bearing(self, ...) -> BearingResult: ...
    def conserves_mass(self) -> bool: ...
# AnalyticalBackend (Tier-2 numpy, default) and ChronoBackend (optional extra) implement it.
```

Rule: **`stewie-forge` MUST run without Chrono.** Chrono is an optional extra: `pip install stewie-forge[chrono]`;
`ChronoBackend` reports `conserves_mass=False` (geometry-oracle) until a mass-conservation acceptance passes,
and cannot be selected for release/execute authority while false.

## 3. Dependency rules (enforced, not aspirational)

- `bodies` imports NOTHING from STEWIE (numpy/scipy only). **Invert the current `bodies→terramechanics`
  edge** (`stewie/specs/bodies.py:29`) so `forge` depends on `bodies`.
- `forge` imports only `bodies` + the numeric stack. No dart/lode/leap/core. (Pull only the dart/leap-free
  geotech/terramechanics in; `forge/bearing.py` is already pure.)
- `core` imports NO dart/lode/leap. **Move the composing runtime loops (`nav_loop`, `replay_loop`) + the
  composing routers (`evidence`, `siteplan`) to `apps/api-server`** to break the current `core↔dart/leap`
  cycle.
- `apps/*` import packages; packages never import apps.
- A CI contract test asserts the acyclic import direction and fails on a back-edge.

## 4. Versioning policy

- One monorepo version overall. Semver applies to the **public `forge`/`bodies` APIs only** (the frozen
  contracts above). Internal packages (core/dart/lode/leap) move with the monorepo, no external semver
  promise.

## 5. Test gates

- Unit tests per package (own `tests/`).
- **Contract tests** across the interfaces: every `PhysicsBackend` impl satisfies the protocol; `bodies`
  round-trips YAML↔`BodyProfile`.
- **Golden planetary examples** (the citable proof): Moon g ≈ 1.62, Mars ≈ 3.71, Earth ≈ 9.80665 m/s²; a
  known bearing/sinkage worked example per body, provenance-tagged; microgravity bodies refuse Bekker unless
  `allow_analog=True`.
- Integration tests for ROS/Godot/Gazebo run SEPARATELY (not in the pure-package unit gate).

## 6. Citation / release assets (public packages only)

`README` + `CITATION.cff` + Zenodo DOI + an examples notebook + a minimal docs site, per public package.
First releases: `stewie-bodies 0.1.0`, `stewie-forge 0.1.0`. The publish workflow builds ONLY those two.
