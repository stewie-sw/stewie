# ML for planetary mining — design lessons for STEWIE fleet autonomy

Source: Cook & Samareh, *Machine Learning For Planetary Mining Applications*, NASA/TM-2020-220439
(NASA Langley, Jan 2020), full 23-page pass incl. Figs 1-8. This is the research grounding for the
multi-rover mission-autonomy layer (assign one/many rovers to an area to best complete mission
priorities; the algorithm chooses the efficient allocation). Reviewed 2026-06-17.

## The domain (their setup, = our fleet-autonomy problem)

A team of **scout rovers** generates a discrete **grid-map of resource (regolith) distribution** over
an area, from an imperfect satellite prior they confirm by drilling/sampling. This is structurally the
problem the user posed: N rovers assigned to an area, maximizing a mission priority (coverage of
high-value cells), with the planner/policy choosing how.

- **State per agent**: (x, y, heading) + distances to nearest 3 resources + distance to nearest other
  agent + self location + drilled-here? + distance to nearest **frontier** (an unchecked cell adjacent
  to a found-resource cell). Frontier-following is the coverage primitive.
- **Actions**: high-level set abstracted from low-level thrust/turn/drill -> {move-to-suspected-resource,
  move-to-frontier, drill-here}. The abstraction is what makes the learning tractable.
- **Reward**: SPARSE, episode-end GLOBAL = fraction of the resource map correctly filled
  (Σ found concentration / Σ true concentration). Encourages cooperative coverage, not racing.

## The actionable findings (Figs 3-8) — what they mean for our allocator

1. **Fleet size is the dominant lever, by a large margin** (Fig 4 linear-model coef ~0.29 for #agents
   vs ~0 for every other factor; R²=0.78). More rovers -> faster area coverage. => the allocator's
   first decision is HOW MANY rovers for an area.
2. **Scale the fleet to the AREA, with diminishing returns.** Resource SIZE (area to cover) hurts
   **quadratically**; SPREAD (travel distance) hurts **linearly** (Fig 7, R²=0.83). Easy/small area
   saturates at ~6 agents; a large/spread area is still under-resourced at 20 (Fig 8). => recommend a
   fleet size from area extent + a diminishing-returns curve, not a fixed count.
3. **The prior map is a GUIDE, not truth.** Performance is almost insensitive to satellite-prior
   inaccuracy (Fig 4 ~0 coef; Fig 6: even 4:1 fake:real resource groups, the team still maps it). =>
   matches "the map acts as a general guide"; the rover confirms by sampling. Robust by design.
4. **Global reward + HOMOGENEOUS policy** (one policy copied to every agent) is the stable, easy-to-
   train baseline (sidesteps the multi-agent **credit-assignment problem**). **Per-agent identity /
   heterogeneous** policies unlock MORE performance at higher agent counts (Fig 5) at the cost of
   harder training. => start homogeneous + a global mission-completion reward; add agent-identity when
   scaling the fleet.
5. **Sensor noise slightly HELPS** (more robust policies); **agent failure** (15%) is the biggest single
   loss but the team degrades gracefully (the redundancy argument). Methods (policy gradient / DQN /
   neuroevolution) tied in quality; **neuroevolution** had the least variance under the sparse reward.
6. **§5 — RL for the physical scout** handles unforeseen failures a hand-tuned controller cannot (wheel
   lodged between rocks -> learn to reverse). The autonomy argument for learning over scripting.

## How this maps onto STEWIE's existing pieces

- The optimizer foundation: `lode/scheduler_env.py` (multi-objective allocation) + `plan_multi`
  (site-exclusive multi-vehicle, efficiency-ranked makespan) + `lode/resync.forward_compare`
  (re-sim candidates, rank). The TM says: make **fleet size** the headline decision variable, reward
  on **global mission completion %**, and size the fleet to **area (quadratic) + spread (linear)**.
- "Assign one/many rovers to an area by priority" = a **mission profile** -> priority-weighted cell/task
  set -> the allocator picks the rover count + assignment that maximizes the global completion reward
  under the per-rover **geofence** (keep-in radius) + **charger compatibility** constraints.
- Frontier-following + sample-to-confirm is the coverage primitive to add to the area-scout task.

## Honest scope note

This TM is a SCOUTING/mapping study (drive + sample), not excavation force modelling; its lessons are
about MULTI-AGENT ALLOCATION + REWARD DESIGN, which is exactly the fleet-autonomy layer. STEWIE's
construction/excavation physics is separate (the conserved authority + the drum models). The fleet
autonomy should reuse the global-reward / fleet-size-to-area lessons here; it does not change the
physics layer.
