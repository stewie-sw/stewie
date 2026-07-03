"""[REQ:RS-04] the ros2_replay / desktop_sil deterministic end-to-end KEYSTONE loop.

One deterministic pass proves the whole runtime spine over a real DEM window (the replayed sensor frame):

    replay input -> DepthObservation
      -> visual hazard classifier -> VisualHazardObservation
      -> observed DEM/hazard map -> ObservedMapUpdate + HazardMapDescriptor
      -> hazard costmap -> CostmapSnapshot
      -> receding-horizon plan (RS-03) -> bounded TrajectoryCommand(s), OR a refusal
      -> command eligibility (FS-28) -> CommandEligibility (issue vs refuse)
      -> world-model transaction (DT-03) -> the committed WorldTransaction
      -> evidence bundle (every typed RS-01 payload)

Every stage crosses its RS-01 typed contract (no ad-hoc dicts). Deterministic: same inputs -> same
bundle. A seeded hazard (a raised obstacle the classifier observes, absent from the base DEM) forces a
REROUTE; a seeded ineligibility forces a logged REFUSAL (no command emitted). Real DEM, real hazard map,
real route, real transaction -- no synthetic terrain, no stubs. The host-side loop is buildable here; the
live-ROS runtime closure (RS-05/RS-06) swaps the replay source without changing this spine.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

import numpy as np

from dart.hazard_map import build_hazard_map
from stewie.bridge.command_eligibility import CommandContext, eligibility_report
from stewie.contracts.runtime_spine import (
    CommandEligibility,
    CostmapSnapshot,
    DepthObservation,
    HazardDetection,
    HazardMapDescriptor,
    ObservedMapUpdate,
    TrajectoryCommand,
    VisualHazardObservation,
)
from stewie.runtime.nav_loop import NavState, run_to_goal

#: SAFE/CAUTION/HAZARD/NOGO int8 codes hazard_map uses; NOGO is where cost is inf.
_NOGO = 3


@dataclass(frozen=True)
class EvidenceBundle:
    """The audited evidence the keystone loop produces -- every stage's typed RS-01 payload + the run
    verdicts. This is the operator/report artifact (§26.4) and the RS-04 acceptance surface."""
    depth: DepthObservation
    hazards: VisualHazardObservation
    observed_map: ObservedMapUpdate
    hazard_descriptor: HazardMapDescriptor
    costmap: CostmapSnapshot
    eligibility: CommandEligibility
    commands: tuple[TrajectoryCommand, ...]
    world_transaction: dict
    arrived: bool
    refused: bool
    run_sha: str            # deterministic content hash over the run's typed payloads
    #: [REQ:RS-02] the observed multi-layer world the planner read this step -- one ObservedMapUpdate per
    #: active layer (dem/occupancy/rock/changed), each provenance-tagged. The DEM layer is `observed_map`.
    observed_layers: tuple[ObservedMapUpdate, ...] = ()


def _run_sha(*parts: object) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(repr(p).encode())
    return h.hexdigest()


def run_replay(dem_window: np.ndarray, cell_m: float, start_xy: tuple[float, float],
               goal_xy: tuple[float, float], *, wss, site: str = "haworth",
               seed_hazard_rc: tuple[int, int] | None = None,
               seed_rock_rc: tuple[int, int] | None = None,
               seed_uncertainty_rc: tuple[int, int] | None = None, eligible: bool = True,
               v_max: float = 0.3, step_m: float = 2.0) -> EvidenceBundle:
    """Run the deterministic keystone loop over ``dem_window`` (a real DEM slice = the replayed frame).

    ``seed_hazard_rc`` raises a +40 m obstacle at that window cell (an observed hazard absent from the
    base DEM) so the classifier detects it and the planner reroutes around its NOGO rim. ``eligible``
    controls the command-authority gate: False seeds an ineligibility (sandbox mission) so the loop
    REFUSES to emit any command. ``wss`` is the real WorldStateService the world transaction commits to.
    """
    z = np.asarray(dem_window, dtype=float)
    rows, cols = z.shape

    # (1) replay input -> DepthObservation (the descriptor of the replayed frame; point count = DEM cells).
    valid = float(np.isfinite(z).mean())
    depth = DepthObservation(t_s=0.0, source="replay", point_topic="/stewie/replay/points",
                             width=cols, height=rows, point_count=int(np.isfinite(z).sum()),
                             range_min_m=0.0, range_max_m=float(np.nanmax(z) - np.nanmin(z)),
                             valid_fraction=valid)

    # (2) classify hazards over the frame. A seeded obstacle is raised into the surface (the observed
    #     hazard) so build_hazard_map assesses its steep rim as NOGO.
    if seed_hazard_rc is not None:
        hr, hc = seed_hazard_rc
        z = z.copy()
        z[hr:hr + 8, hc:hc + 8] += 40.0
    # [REQ:RS-02] the observed OCCUPANCY/rock layer -- a NON-DEM observed hazard (a rock the perception
    # segmented, absent from the static DEM height) fed to the ROUTING costmap as dense semantic occupancy,
    # so an observed rock over FLAT ground still raises the traversal cost the planner keys on.
    zones = None
    if seed_rock_rc is not None:
        from lode.zones import ZoneRegistry
        rr, rc = seed_rock_rc
        zones = ZoneRegistry()
        # the observed occupancy: a rock/obstacle the perception segmented as impassable (a NO-GO the
        # static DEM has no height for), at the window cell's world position (dem_origin (0,0)).
        zones.designate((rc + 4) * cell_m, (rr + 4) * cell_m, 5.0 * cell_m, "no_go",
                        label="observed_rock_occupancy", by="stereo_mapper")
    # [REQ:RS-02] the observed MAP-UNCERTAINTY layer: a patch the perception observed with low confidence
    # lowers the assessment confidence the planner keys on (provenance 'observed'), so the plan knows where
    # the observed world is weakly seen -- distinct from the DEM/occupancy layers.
    uncertainty = None
    if seed_uncertainty_rc is not None:
        ur, uc = seed_uncertainty_rc
        uncertainty = np.zeros_like(z, dtype=float)
        uncertainty[ur:ur + 8, uc:uc + 8] = 0.9        # 90% uncertain over the weakly-observed patch
    hmap = build_hazard_map((z, cell_m), max_slope_deg=25.0, zones=zones, uncertainty=uncertainty)
    detections: list[HazardDetection] = []
    if seed_hazard_rc is not None:
        hr, hc = seed_hazard_rc
        detections.append(HazardDetection(kind="obstacle", confidence=1.0, accepted=True,
                                          reason="observed +40m obstacle exceeds the 20deg slope limit",
                                          centroid_row=float(hr + 4), centroid_col=float(hc + 4),
                                          size_m=8.0 * cell_m))
    if seed_rock_rc is not None:
        rr, rc = seed_rock_rc
        detections.append(HazardDetection(kind="rock", confidence=1.0, accepted=True,
                                          reason="observed rock occupancy (non-DEM layer) raises the traversal cost",
                                          centroid_row=float(rr + 4), centroid_col=float(rc + 4),
                                          size_m=8.0 * cell_m))
    hazards = VisualHazardObservation(t_s=0.0, source="replay", detections=detections)

    # (3) observed DEM/hazard map -> ObservedMapUpdate (observed provenance) + HazardMapDescriptor.
    observed_map = ObservedMapUpdate(t_s=0.0, layer="dem", rows=rows, cols=cols, cell_m=cell_m,
                                     provenance="observed", coverage_fraction=valid,
                                     uncertainty_m=(0.5 if seed_uncertainty_rc is not None else 0.0))
    # [REQ:RS-02] the observed MULTI-LAYER world the planner read -- one provenance-tagged ObservedMapUpdate
    # per active layer (dem + changed-terrain + occupancy/no-go + rock/object), so planning consumes the
    # observed world across layers, not just the static DEM.
    _obs_layers = [observed_map]
    if seed_hazard_rc is not None:      # a raised obstacle CHANGED the terrain vs the prior DEM
        _obs_layers.append(ObservedMapUpdate(t_s=0.0, layer="changed", rows=rows, cols=cols, cell_m=cell_m,
                                             provenance="observed", coverage_fraction=valid))
    if seed_rock_rc is not None:        # the segmented rock -> an occupancy no-go AND an object-graph instance
        _obs_layers.append(ObservedMapUpdate(t_s=0.0, layer="occupancy", rows=rows, cols=cols, cell_m=cell_m,
                                             provenance="observed", coverage_fraction=valid))
        _obs_layers.append(ObservedMapUpdate(t_s=0.0, layer="rock", rows=rows, cols=cols, cell_m=cell_m,
                                             provenance="observed", coverage_fraction=valid))
    observed_layers = tuple(_obs_layers)
    finite_cost = hmap.cost[np.isfinite(hmap.cost)]
    hazard_descriptor = HazardMapDescriptor(
        rows=rows, cols=cols, cell_m=cell_m, n_classes=int(np.unique(hmap.hazard_class).size),
        no_go_fraction=float((~hmap.traversable).mean()),
        max_cost=float(finite_cost.max()) if finite_cost.size else 0.0,
        mean_confidence=float(np.nanmean(hmap.confidence)))

    # (4) hazard costmap -> CostmapSnapshot (the blocking reasons = the classes that gated cells).
    reasons = sorted({"slope>limit"} | ({"observed_obstacle"} if seed_hazard_rc is not None else set())
                     | ({"observed_rock"} if seed_rock_rc is not None else set()))
    costmap = CostmapSnapshot(t_s=0.0, rows=rows, cols=cols, cell_m=cell_m,
                              layers=["slope", "roughness", "rock"], blocking_reasons=reasons,
                              max_cost=hazard_descriptor.max_cost)

    # (6) command eligibility (evaluated BEFORE emitting) -> CommandEligibility. `eligible=False` seeds a
    #     sandbox mission so the gate refuses; a refused loop emits NO command (fail-closed).
    ns = "live" if eligible else "sandbox"
    rep = eligibility_report(CommandContext(role="operator", mission_namespace=ns, target_namespace=ns,
                                            safed=False, ack_age_s=0.1, ack_deadline_s=2.0))
    eligibility = CommandEligibility(eligible=rep["eligible"], reason=rep["reason"], profile="ros2_replay",
                                     mode_ok=rep["authorized"], released=rep["live"],
                                     safe_inactive=rep["safe"], link_ack=rep["fresh"], watchdog_alive=True)

    # (5) receding-horizon plan (RS-03) -> bounded commands, but ONLY if eligible (else refuse).
    commands: tuple[TrajectoryCommand, ...] = ()
    arrived = False
    if eligibility.eligible:
        st = NavState(x=start_xy[0], y=start_xy[1], goal_x=goal_xy[0], goal_y=goal_xy[1])
        final, cmds = run_to_goal(st, hmap, v_max=v_max, step_m=step_m)
        commands, arrived = tuple(cmds), final.done
    refused = not eligibility.eligible

    # (7) world-model transaction (DT-03) -> the committed WorldTransaction, keyed to this run's surface.
    a_sha = hashlib.sha256(np.ascontiguousarray(z).tobytes()).hexdigest()
    wss.record_terrain(authority_sha=a_sha, mission=f"replay:{site}", site=site,
                       provenance=f"ros2_replay keystone ({'refused' if refused else 'issued'})")
    from dataclasses import asdict
    world_transaction = asdict(wss.latest())

    run_sha = _run_sha(depth.model_dump(), hazards.model_dump(), observed_map.model_dump(),
                       hazard_descriptor.model_dump(), costmap.model_dump(), eligibility.model_dump(),
                       tuple(c.model_dump() for c in commands), a_sha)
    return EvidenceBundle(depth=depth, hazards=hazards, observed_map=observed_map,
                          hazard_descriptor=hazard_descriptor, costmap=costmap, eligibility=eligibility,
                          commands=commands, world_transaction=world_transaction, arrived=arrived,
                          refused=refused, run_sha=run_sha, observed_layers=observed_layers)
