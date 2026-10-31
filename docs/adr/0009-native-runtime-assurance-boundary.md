# 0009: Native-runtime assurance boundary

Date: 2026-10-15. Status: isolated candidate, not deployed or flight-qualified.

## Context

The user requires realistic rover operation and training without fabricated terrain or measurements.
The available Haworth DEM resolves one-metre heights. Vehicle-specific soil, actuator, sensor, and excavation calibration was not located.
The previous streamed runtime generated fine terrain and random rocks. Its frame rate and physics timestep also disagreed.

## Options

1. Retain generated detail. This conflicts with the standing data rule.
2. Interpolate a finer grid. This cannot supply measured contact-scale geometry or establish excavation validity.
3. Preserve native samples and refuse unresolved operations. This exposes limitations instead of concealing them.

## Decision

Choose native terrain, bundle clasts, and a timestep derived from the configured frame rate.
Refuse excavation when the grid does not resolve the drum footprint.
Use the existing 15-degree nominal slope specification for streamed route planning, rather than the previous 25-degree limit.
Preserve every planned grid waypoint. Refuse invalid, oversized, outside, or incomplete missions.
Introduce `haworth_pad_a_native` instead of changing the world behind the retired `haworth_pad_a` identity.

## Why

Numerical detail is not physical evidence. A coarser honest runtime is preferable to an unsupported claim of realism.
The nominal operating envelope is a more conservative planning boundary than extrapolation beyond a published slope test.
A new scenario identity prevents old generated-world recordings from being silently presented as native-world recordings.

## Consequences

Native driving, timing, transport stopping, route handoff, paging, and journal recovery can be exercised with existing inputs.
Fine-resolution excavation qualification needs measured terrain and target-vehicle calibration.
The native identity is not backward-compatible with the retired scenario. Old recordings remain unchanged and require separate provenance review.
The actor-local watchdog is not an independent safety controller. Renderer acknowledgments do not prove fresh browser intent.
Route planning is not route-following qualification. The full renderer, sensor-only policy loop, and hardware path remain unqualified.

## Owner acceptance and integration, 2026-10-15

Aaron accepted the recommendation to qualify native-terrain operation and retire unsupported
fine-excavation claims. PX-09 through PX-14 lose their completed verification status.
Their former positive excavation tests are replaced by refusal and unchanged-state checks;
arm geometry, command wiring, and native drive telemetry checks remain.
The generated scenario name is retired without rewriting existing recordings.

Integration uses commit 94281504 as its base. Journal recovery retains the existing shared helper
for the world log, observed twin, and mission lineage, with durable backups before tail repair.
The world reader additionally validates stored sequence, previous hash, and world hash.

Native resolution refusal applies to socket commands, direct dig/dump methods, and AutoDig.
These guards establish the operation boundary, not a physically validated excavation model.
