# Structure-first / site-plan base authoring — design pass (2026-06-23)

The user asked: *"can we plan out the base with drop-in locations etc shapes and then design around
it instead of just waypoints?"* — i.e. compose a base from **placed structures** (a landing pad here,
a habitat foundation there, a berm around it), and have the system **design around them**, rather than
authoring one cut/fill/drive operation at a time.

This is a **design pass**, not an implementation. The headline finding: **the per-structure half is
already built and live** — the real new work is *shapes* (drawn/oriented footprints) and the
*cross-structure layout layer*.

## Where we are (CONFIRMED from the code)

| Capability | Status | Evidence |
|---|---|---|
| **Drop a structure at a location → real mass-balanced operations** | ✅ **live in the cockpit** | `cockpit.js:3602` (`qstruct.onclick` — "place a named structure → mass-balanced orders"), `:3547` (place-point prompt) |
| **8 parametric structure templates** (landing pad, habitat foundation, blast berm, crater fill, borrow pit, haul road, solar pad, trench) | ✅ | `leap/structures.py` `STRUCTURES` / `decompose(name, x, y, **params)` |
| **Per-structure mass conservation** (consuming structures pair the fill with an exact-volume borrow cut + lunar swell `RHO_BANK/RHO_LOOSE≈1.48`) | ✅ | `leap/structures.py:47–96` |
| **Custom structure templates** (save your own parametric structure, reuse from the Catalog) | ✅ | `stewie/server/routers/structures.py` (`/structures/custom/...`), `cockpit.js:4473–4533` |
| **Expand a template at (x,y) → order dicts** | ✅ live route | `GET /structures/custom/{name}/expand?x=&y=` |
| **The contract already speaks shapes** (circle / axis-aligned rect / polygon) | ✅ (for keep-outs) | `KeepOutRegion` + `_exactly_one_shape` validator, `mission_ops.py:249–297` |
| **Draw shapes on the map** | ✅ (raw footprints / keep-outs) | `footprint_geom.js`, `keepout_geom.js`, `plan_geom.js`, `navplot.js` |
| **DEM-coordinate siting** | ✅ | `latlon_to_dem_origin` (IAU_2015:30135) |
| **Whole-footprint slope gate** | ✅ (I11) | `validate_plan` rejects a build if any footprint cell is too steep |
| **Structure orders → release lifecycle** | ✅ (just built) | `intent_from_orders` → `run_lifecycle` → `POST /executive/release-plan` |

So **"plan with drop-in structures instead of waypoints" is ~80 % already true**: you place a structure,
it lowers to conserved cut/fill operations, and (now) it releases through the mission lifecycle.

## The two real gaps

### Gap A — *shapes*, not just a dropped point

Today a structure is placed at a **point** `(x,y)` with **scalar params** (`side_m`, `length_m`,
`height_m`); the template computes its own internal geometry (e.g. `landing_pad` puts the berm at
`x + side/2 + …` along **+x**, always). You cannot:

- **draw the footprint** (drag a pad's extent, sketch a berm as a polyline, set a haul road A→B),
- **orient** it (rotate the pad, aim the solar pad at the sun, run the road along a chosen heading).

The drawing primitives exist (`footprint_geom` / `keepout_geom` / `plan_geom`) but they author **raw
footprints**, not a **typed structure's footprint + heading**. Gap A = bind a drawn/oriented footprint
to a structure's params, so "shape" drives the decomposition. Bounded, no new algorithm.

### Gap B — *"design around it"*: the site / layout layer (the genuinely new work)

Today every structure is **independent and self-balancing** — it carries its **own** paired borrow cut.
A five-structure base therefore digs **five separate borrow pits** and has no relationship between assets.
"Design around it" is the **base-level** reasoning that does not exist yet (the archived
`building_taxonomy.md §4` "Mission/Task Planner — planner not built"):

1. **Global mass routing** — pair the *whole base's* sources↔sinks (one borrow pit feeds three fills;
   the pad's cut surplus feeds the berm) to minimise haul, instead of one borrow pit per structure.
   (This is the CraterGrader-style site-level transport problem flagged in `building_taxonomy.md §7.3`.)
2. **Inter-structure clearances / adjacencies / keep-outs** — minimum spacing, "borrow pit not inside
   the pad", solar pad oriented to the sun, road endpoints snapped to asset edges. (Per-structure
   keep-outs + slope-gate exist; *inter-structure* layout constraints do not.)
3. **Build ordering across structures** — foundations before walls; a source cut before the fill it feeds.
4. **Auto haul-roads** connecting the sited structures.
5. **Design *around* the fixed assets** — pin the habitat + pad; let the solver place the shared borrow
   pits + roads + grading around them.

Gap B is a **new planning tier above the Objective/order layer** — a real algorithm, genuinely
underspecified, with one product-defining fork (below).

## The model (target)

```
SitePlan { body, dem_origin (lat/lon),
           structures: [ PlacedStructure { type, pose:(x,y,heading), footprint, params, priority, pinned } ],
           constraints: { clearances, keepouts, build-order rules },
           routing-policy }
   --(layout solver, Gap B)-->  resolved placements + global source/sink routing + roads + build order
   --(decompose, EXISTS)----->  mass-balanced cut/fill/sinter order dicts   (leap/structures.py)
   --(intent_from_orders, EXISTS)-->  MissionIntent  -->  release lifecycle  (just built)
```

The bottom two arrows already exist. Gap A enriches `PlacedStructure` (footprint + heading). Gap B is
the `SitePlan → resolved layout` solver.

## The one fork for the user — how much does the system DESIGN for you?

This is the product-defining decision for Gap B, and it should be made before the solver is built:

- **Validate-and-advise** — you place + orient every structure; the solver *checks* clearances/slope,
  *pairs* base-wide mass sources↔sinks, *orders* the build, and *suggests* haul-roads. You keep
  placement authority; the system keeps you honest and routes material. (Smallest new algorithm; highest
  operator control; matches the "operator authors, system validates" rail already in the contract.)
- **Auto-layout** — you declare *what* to build + site constraints (sun direction, keep-outs, the pad
  must be ≤X m from the habitat); the solver *places, orients, routes, and balances* the whole base.
  (Biggest new algorithm — a constrained layout optimiser; most "magic"; needs an objective function and
  is the part most prone to producing an un-physical or unwanted plan.)
- **Plumbing-first** — defer the solver; first finish Gap A (drawn/oriented footprints) + wire the
  existing structure-drop cleanly through `intent_from_orders` → release, so the *manual* base-from-
  structures workflow is end-to-end solid. Then revisit B with that foundation.

## Build path (once the fork is chosen)

- **Slice 1 (invariant to the fork, reuses real code):** `PlacedStructure` in the contract path +
  structure-drop → `intent_from_orders` → release round-trip, TDD. Needed regardless of B.
- **Slice 2 (Gap A):** drawn/oriented footprints (bind `footprint_geom`/`plan_geom` to a typed
  structure + heading param). Cockpit + a couple of template signature extensions.
- **Slice 3 (Gap B, gated on the fork):** the site-plan solver at the chosen autonomy level —
  global mass routing first (the highest-value piece), then clearances, build-order, auto-roads.

## Rails (do NOT break)

- **The conserved authority stays the sole terrain mutator.** The solver only *plans*; `column_state`
  mutates. Mass balance must hold **across the whole base** (global source↔sink), not just per structure.
- **This is command authority, not a view preference** — site-plan authoring + release stay role-gated
  (director to release), unlike the FS-21 view-customization layer.
- **No fabricated layout.** If the solver cannot place/route feasibly (mass can't balance, no clear
  corridor, slope-gate fails), it must say so honestly — never emit a plan that doesn't conserve mass or
  that sites a build on an obstacle.
- **Reuse, don't re-build.** `leap/structures.py` decomposition, `intent_from_orders`, the release
  lifecycle, the slope-gate, and DEM siting all exist — Slice 3 is the only genuinely new algorithm.
