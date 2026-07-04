"""[REQ:MP-08] Capability matching (PRD §30).

Select the asset for a task: match the task's required capabilities (an MP-05 ``Task``) against the available
assets' capabilities (the real ``stewie.specs.vehicles.Vehicle.capabilities`` + any mounted ``Tool`` grants),
honoring an assignment rule. An unmet required capability BLOCKS assignment (``CapabilityUnmet``); a met set
yields an MP-05 ``Assignment``. The rule: the most SPECIALIZED covering asset wins (fewest extra capabilities),
so a dedicated hauler is chosen over a generalist when both can do the job.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

from stewie.contracts.planning_model import Assignment, Task

if TYPE_CHECKING:
    from stewie.specs.vehicles import Tool, Vehicle


class CapabilityUnmet(Exception):
    """Raised when NO available asset covers a task's required capabilities (blocks assignment)."""


def effective_capabilities(vehicle: Vehicle, tools: Iterable[Tool] = ()) -> frozenset[str]:
    """A vehicle's capabilities INCLUDING those granted by mounted tools: ``Vehicle.capabilities`` ∪ each
    ``Tool.capability``. A bare IPEx cannot sinter; with the sinter tool mounted it can."""
    caps = set(vehicle.capabilities)
    caps.update(t.capability for t in tools)
    return frozenset(caps)


def match_task(task: Task, assets: Iterable[tuple[str, Iterable[str]]]) -> Assignment:
    """Match a Task's required capabilities against `assets` (each an ``(asset_id, capabilities)`` pair).

    RULE: the most SPECIALIZED covering asset wins -- the covering asset with the fewest EXTRA capabilities
    beyond what the task requires (ties broken by input order). Raises ``CapabilityUnmet`` if no asset covers
    ALL required capabilities. Returns an MP-05 ``Assignment`` recording the asset + the capabilities it met.
    """
    required = frozenset(task.required_capabilities)
    covering = [(aid, frozenset(caps)) for aid, caps in assets if required <= frozenset(caps)]
    if not covering:
        raise CapabilityUnmet(
            f"no asset covers task {task.task_id!r} required capabilities {sorted(required)}")
    aid, _caps = min(covering, key=lambda ac: len(ac[1] - required))
    return Assignment(assignment_id=f"assign:{task.task_id}:{aid}", task_id=task.task_id, asset_id=aid,
                      capabilities_met=tuple(sorted(required)))
