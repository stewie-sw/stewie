# STEWIE Mission Workflows — Interaction Design (v1, 2026-07-07)

> Polished web version (artifact): https://claude.ai/code/artifact/85dd1409-daa8-4954-a5b7-ee03b8e569ee
> How to turn STEWIE's pieces (map, layers, inspector, evidence, physics authority) into fluid
> task-flows organized around the decisions a mission planner makes, not the tools underneath.

## Three commitments that govern every call

1. **Map-anchored** — the map is the shared context and the primary *input surface*, not a viewport
   beside the UI. Every workflow starts and ends on it.
2. **Task-driven** — organize by the planner's *goal (a verb)*, not by tool/layer. The ConOps spine
   (Plan · Rehearse · Validate · Release · Execute · Report) is already this.
3. **Evidence-backed** — every step emits provenance · confidence · freshness. STEWIE's differentiator
   *and* the trust layer that makes GeoAI usable.

## The loop that underlies every geospatial decision

`SELECT (where) → ANALYZE (what / what-if) → DECIDE (afforded actions) → EXECUTE (authority) → VERIFY (evidence)`

Make it explicit; keep a clean hand-off between stages *on the map*. Don't collapse into one dense
screen; don't scatter across disconnected tools.

## The top three decisions, run through the loop

### D1 — Site a landing pad or structure (owner: mission planner)
| Stage | STEWIE today |
|---|---|
| Select | Draw a candidate footprint on the site DEM (5 m polar / 1 m Haworth). |
| Analyze | Inspector reads per-cell slope/bearing/traversability + confidence/freshness; SD-01 verdicts volume/mass/flatness. |
| Decide | "Plan pad here" enabled/disabled with PSR / over-slope / bearing reasons inline. |
| Execute | Cut/fill orders run through the conserved authority; as-built mutates the twin. |
| Verify | EV-01 bundle reproduces inputs + layers + flatness acceptance. |

**Make it fluid:** (a) a "Site assessment" mode chaining draw → inspect → verdict in one gesture
(binds GW-08 + GW-07 + SD-01); (b) the SD-01 verdict drapes on the drawn polygon, not only a side
panel; (c) the "plan here" action is contextual to the selection with its refusal reason.

### D2 — Route a traverse or haul (owner: mobility lead)
| Stage | STEWIE today |
|---|---|
| Select | Pick start + goal (or a waypoint chain). |
| Analyze | Cost/hazard/traffic layers + routed path; terramechanics slip/sinkage risk per leg. |
| Decide | Accept/adjust; forward-compare shows alternatives side by side. |
| Execute | Traverse plan runs; drive loop re-hazards a leg crossing a fresh cut/fill. |
| Verify | Predicted vs replayed slip/energy in the report when telemetry exists. |

**Make it fluid:** (a) live route on drag (path + cost update as you nudge waypoints); (b) cost
inspectable per leg (slope/hazard/traffic/energy breakdown + provenance); (c) forward-compare on the
map with a delta readout (energy, slip-risk, makespan).

### D3 — Approve a construction task (owner: director/planner) — the differentiator
| Stage | STEWIE today |
|---|---|
| Select | A cut/fill/berm order at a location. |
| Analyze | Terramechanics feasibility **and** the self-made-hazard risk (P6 observed-vs-truth: will this dig create a hazard the rover can't perceive?). |
| Decide | Approve/defer/reroute — the loop's recommendation + the human override, both logged. |
| Execute | The mutation applies through the conserved authority (mass-exact). |
| Verify | The observed-vs-truth divergence map + the evidence bundle. |

**Make it fluid:** (a) self-made-hazard **preview before execution** (P6 divergence as a "what your
own dig does to what you can see" overlay, visible at decide time); (b) recommend → override in one
control with the override reason captured; (c) the before → execute → observe → divergence sequence
*is* the report artifact.

## Cross-cutting principles

- **One question per panel** (Layers / Inspector / Eng panel each answer one).
- **Progressive disclosure** — map + current-task controls by default; detail on demand.
- **Contextual actions** — affordances appear where/when relevant, with refusal reasons.
- **GeoAI trust layer** — every prediction carries source · confidence · uncertainty + honest "no
  data"; explainable on click; AI recommends, human commits.
- **Composable analysis** — derived layers whose derivation is inspectable.
- **State is visible** — selected / authoritative / live-vs-prior always legible; encode state in form.

## What to change first (build order)

1. **Selection → contextual action rail** (GW-07 inspector as the standard click target; hang
   affordances + refusal reasons off the selection). Every Decide stage depends on it.
2. **Drape derived results on the map** (SD-01 verdicts, cost breakdowns, P6 divergence on their
   geometry) — makes Analyze → Decide continuous.
3. **Mode-chained gestures** ("Site assessment", "route") chain the loop into one flow.
4. **Forward-compare + evidence as first-class outputs** — close the loop for D2/D3.

Test each end-to-end: if a planner can't get goal → decision → evidence without leaving the map, the
workflow isn't done.

---
Anchored to GW-07 / GW-08 / SD-01 / P6 / EV-01 in the live §7.B matrix. Not committed (awaiting Aaron's review).
