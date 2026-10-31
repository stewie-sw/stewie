# STEWIE IDE — Council synthesis: organizing the workspace for workflows (2026-07-07)

> Six expert-persona agents (UI/UX + information architect · robotics/autonomy engineer · physics/
> terramechanics engineer · civil/construction mission planner · GIS analyst · systems/software architect)
> each audited the real `config.json`/plugins/routes of the artemis QWC2 IDE against the ConOps workflow.
> This is the synthesis + a prioritized plan. Every persona worked from code at `file:line`; findings below
> are the convergent core.

## One-line synthesis

**STEWIE's backend is genuinely excellent; the gap is organizational + frontend-surfacing.** The physics is
conserved and fully attributed, the evidence-only/command boundary is enforced, the plugin/bridge split is
clean, GW-02 is a well-built reducer, and the earthwork math (volume/mass balance, Terzaghi/Vesic bearing,
repose, flatness) is real. But the **front door (the QWC2 IDE) has no shared workspace spine, a flat menu,
mutually-exclusive panels, and it throws away ~70% of what the backend computes.** "Organize for workflows" =
give the IDE one workspace context every panel reads, section the menu, let key panels coexist, and surface
the backend the frontend is discarding.

## The unifying narrative (what all six saw)

Read across the six lenses, three findings recur:

1. **The spine exists but lives in the wrong frontend.** GW-02 (the unified workspace context — mission/site/
   body/mode/profile/frame/selection/layers/branch/run/role) is a clean pure reducer in the **React `/app`
   cockpit** (`frontend/src/workspace.ts`), but the **QWC2 IDE front door doesn't consume it** — every plugin
   hardcodes `site='haworth'` (`MissionLayers.jsx:37`, `MissionPlan.jsx:129`, `MissionEvidence.jsx:46`, …).
   Zero references to `workspace.ts` from `gis/qwc2/`. **This is the root cause of "not organized for
   workflows":** N panels drift out of agreement because there is no shared context. *(systems-architect;
   corroborated by every other lens hitting the per-plugin `haworth` tax.)*

2. **Rich backend, unplugged frontend.** The same shape appears in three places: **physics** — the PhysicsBackend
   / terramechanics-spine / physics-attribution registries are world-class on the wire, but the four `/physics/*`
   endpoints are **never called by the IDE** (`route_terms` cost decomposition, PH-02 attribution, the moduli
   readout — all computed, none rendered). **Autonomy** — the command path (`/rc/*`, teleop, SAFE, eligibility)
   exists but lives in the **old cockpit**, so the operator's monitor→teleop→diagnose→recover loop crosses a
   deployment boundary. **Civil** — the earthwork analyses (bearing, repose, cut/fill balance) are computed but
   buried per-structure, never aggregated to a site view. The backend is ahead of the screen everywhere.

3. **The menu + panels don't express the work.** The Map & Tools menu is a **flat 21-entry list** with only one
   group; four layer entries compete; icons collide; the ConOps spine (Plan·Rehearse·Validate·Release·Execute·
   Report) — STEWIE's whole story — **has no home in the menu**; and every panel is a mutually-exclusive
   `setCurrentTask` so you cannot inspect a cell while seeing the layer tree. *(UI/UX; echoed by autonomy, GIS,
   civil.)*

## The six lenses (one finding each)

- **UI/UX** — the menu is flat; **sectioning is a pure `config.json` change** (QWC2's `AppMenu` already renders
  any `subitems` array as a collapsible labeled group — the existing "Tools" entry proves it). Proposed six
  workflow sections. The one real component change: let Inspector/Layers/Command-Authority **persist and
  coexist**.
- **Systems-architect** — the plugin/bridge split + evidence-only boundary + single command seam are genuinely
  clean; **the coherence problem is GW-02 living in `/app`, not `/ide`.** Lift it into a QWC2 store slice every
  plugin reads. Add the triple-registration consistency test; add router `prefix=`/`tags=`.
- **Physics** — the attribution model is the strongest "never a black box" substrate reviewed, but unplugged.
  Build one **Analyze ▸ Terramechanics inspector** (3 tiers mirroring `/physics/authority` + `/physics/
  terramechanics-spine` + `/world/point`), render `route_terms`, add a `backend·calibration` chip to every
  physics value.
- **Autonomy** — the IDE is evidence-only; **teleop/execute/recover live in the old cockpit.** Add a persistent
  **runtime-context rail** (RT-01 profile + `/rc/eligibility`, makes the command boundary visible) and an
  in-IDE **command console** (`/rc/command` + `/rc/telemetry/stream`), gated by the active profile's
  `can_execute`.
- **Civil** — the earthwork **engine is strong and honest**; the work is organizational: re-sequence the palette
  **Survey → Design → Route**, promote a first-class **Analyze panel with a site-wide cut/fill balance**, add
  the four missing civil views (control points, cross-section, mass-haul diagram, working LOS), and a **cut-vs-
  fill hatch** symbology.
- **GIS** — two competing layer trees → unify into one lifecycle-first tree + a **"My Layers/Imports"** group;
  fix the **Earth-CRS import trap** (delete the Swisstopo EPSG:2056 preset, guard imports, drop EPSG:4326 from
  the coordinate readout); **wire the lunar graticule** (QWC2 ships `GraticuleLayer` but nothing uses it) in
  dual mode — selenographic lon/lat + a polar metric km grid with range rings.

## Prioritized action plan (synthesized)

Ordered by leverage × reversibility (cheap/high-value first):

| # | Action | Why / source | Maps to |
|---|---|---|---|
| **1** | **Section the Map & Tools menu** into 6 workflow groups (View&Navigate · Layers&Legend · Inspect&Analyze · Design&Plan · Mission Lifecycle · Rover&Runtime + utility tail). **Pure `config.json` data change.** Fix icon collisions; add ConOps entry points (Rehearse/Validate/Release); demote the Program board; remove/wire the orphaned LayerCatalog + inert Editing/TimeManager. | The direct ask; low-risk, high-value; all lenses converge on these clusters | **#42** |
| **2** | **Lift GW-02 into a QWC2 shared store slice** (`gis/qwc2/js/mission/workspaceContext.js`, port `workspace.ts`); every `Mission*` plugin reads site/mission/body/mode/profile/branch/run from it; delete the per-plugin `haworth` constants; route it through the permalink so one URL restores the IDE. | The root-cause structural fix; unblocks coherence for everything after | — (new: GW-02-in-IDE) |
| **3** | **Make Inspector + Layers + Command-Authority persist & coexist** (dock alongside instead of mutually-exclusive `setCurrentTask`). | The one real component change; "one question per panel, all visible" | — |
| **4** | **Wire the lunar graticule** (dual mode) + **fix the Earth-CRS import trap** + pin the coordinate readout to IAU_2015:30100. | Small, real correctness bug + the gridlines ask | **#40** |
| **5** | **Surface the backend the frontend discards:** the **Analyze ▸ Terramechanics inspector** (physics attribution + spine terms + per-cell readout) + `route_terms` decomposition + the **runtime-context rail** + in-IDE **command console**. | Rich-backend/thin-frontend theme (physics + autonomy) | — |
| **6** | **Civil workflow**: re-sequence the palette Survey→Design→Route; a first-class **Analyze panel** with site-wide cut/fill balance; **cut-vs-fill hatch** + control points + cross-section + mass-haul. | Civil planner; the earthwork math already exists | **#41** |
| **7** | **User-layers subsystem** + unify the two layer trees + "My Layers/Imports" group. | GIS + the earlier LY-01 gap | **#44** |

Cross-cutting cleanups (fold into the above): the triple-registration consistency test (systems), router `prefix=`/`tags=` (systems), the RT-04 glyph drift (autonomy), and disabling the declared-but-dead `terrain.los`/`terrain.comms` layers until they have producers (civil/physics).

## The concrete #42 deliverable — the six sections

Replace the flat `menuItems` with six `subitems` groups (the proven "Tools" pattern), ordered by the loop
*orient → read → analyze → author → commit → run/prove*:

1. **View & Navigate** — Whole Moon, Layer Catalog, Basemap/Theme, Overview, Locate, Bookmark, Share
2. **Layers & Legend** — Mission Layers (primary), Legend, (stock LayerTree demoted/nested)
3. **Inspect & Analyze** — Inspector, Identify, Measure, Height Profile, Routing, Compare, Time, **Analyze▸Terramechanics** (new)
4. **Design & Plan** — Mission Plan, Draw/Redline, Editing, Feature Form, Attribute Table
5. **Mission Lifecycle** — Command-Authority, Plan, **Rehearse**, **Validate**, **Release** (new entries), Execute, Report
6. **Rover & Runtime** — Runtime-context rail, Rover HUD, Eng Panel, **Command console** (new), Evidence/Report, Asset Library

Utility tail (role-gated): Program board, Settings, Help.

---
*Synthesis of six council-agent reports (2026-07-07). The backend excellence and the frontend/organization gap
are confirmed at file:line across the reports; the section taxonomy + priority order are design judgment for
Aaron's call. Companion to `STEWIE_workflow_design_2026-07-07.md`.*
