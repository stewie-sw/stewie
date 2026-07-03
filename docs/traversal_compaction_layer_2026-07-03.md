# Traversal-compaction / multipass "traffic" layer — design note (2026-07-03)

**Idea (Aaron):** record the rovers' ACTUAL driven paths, accumulated on top of each other over time, to map
road-compression mechanics — a Google-Maps-traffic-style color layer showing where the surface has been
compacted and sheared by repeated traffic. Emergent lunar haul-road / civil-infrastructure mapping from
traversal history: "we know compression and shear in certain areas."

## Grounding: this is the multipass effect

In off-road mobility the Nth wheel pass over a cell has different resistance than the 1st. Repeated loading
**compacts** the regolith (density rises toward a limit → firmer, LESS sinkage), while repeated **slip
shears/remolds** it (churned → MORE sinkage, ruts, entrapment risk). Lunar haul roads are a real ISRU
concern — you WANT to build and reuse compacted routes for efficient regolith transport, and you want to
AVOID over-sheared/rutted ground. The layer must encode BOTH regimes, not a single "traffic = bad" scale.

## What STEWIE already has (verified 2026-07-03)

- Per-cell `density` in the conserved authority; `physical_compaction_field` / `physical_compaction_target_density`
  raise density under wheel load + slip, mass-conserving. Single-pass compaction physics EXISTS, and repeated
  passes asymptote toward a target density — so the multipass compaction *curve* is implicitly present.
- The as-built terrain (with its compacted density) is recorded in `stewie/twin/terrain_memory.py` + the
  world-transaction log.
- Costmap layers include `sinkage` + `slip` (both density-dependent) but there is **no explicit
  traversal/traffic layer and no accumulated-shear layer**.

## What is NEW (the feature to build)

1. **Traversal-accumulation layer** — per-cell weighted count of rover passes over time (the "traffic
   density"), accumulated across a mission and across the twin's history.
2. **Accumulated shear / remolding** — repeated slip degrades the surface distinctly from normal compaction;
   track accumulated shear strain per cell; over-sheared cells become rutted / entrapment-prone.
3. **FR-10 world layers** surfacing both (`traffic` / `compaction_state` / `shear_state`) — queryable +
   visualizable as a traffic-color heat layer (green fresh → firm compacted road → red over-sheared/rutted).
4. **Planning use** — a costmap term that PREFERS established firm-compacted routes (lower sinkage cost, so
   the rover reuses its own haul roads = emergent infrastructure) and AVOIDS over-sheared/rutted cells. This
   is the civil-infrastructure / traffic-pattern behavior.

## Honest scope / cautions

- Write to the twin authority (conserved, provenance-tracked), never client-side.
- Shear-remolding parameters for lunar regolith are `[UNKNOWN]`/`[ESTIMATED]` — provenance-tag them; validate
  the multipass curve against any available data (NASA LTV / RASSOR multipass tests) or flag it as modeled.
- Tier-2 analytical (the fast numpy authority) predicts the accumulation; Tier-3 Chrono can validate the
  multipass/shear under dynamic wheel-soil contact.
- Fits the extensibility seams: the accumulation model is a `PhysicsBackend` responsibility; the layers are
  FR-10 `WorldLayer`s; the traffic viz is a GL/DW frontend surface.

## Tracking

- PRD row **TW-11 (P2)**. Design owner: Aaron. Not started. This is a research-grade contribution
  (multipass terramechanics → emergent lunar haul-road mapping), suitable for the dissertation and a demo.
