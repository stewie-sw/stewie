"""[REQ:MP-08] Capability matching: a task's required capabilities × available assets → an assignment. An
unmet required capability blocks assignment; a met set yields an assignment honoring the rules; a mounted tool
grants its capability (a bare IPEx cannot sinter; with the sinter tool it can)."""
import pytest

from stewie.contracts.capability_matching import (
    CapabilityUnmet,
    effective_capabilities,
    match_task,
)
from stewie.contracts.planning_model import Assignment, Task
from stewie.specs import vehicles as V


def test_mp08_met_capability_set_yields_an_assignment():  # [REQ:MP-08]
    task = Task(task_id="t1", mission_id="m1", kind="dig", required_capabilities=("excavate", "haul"))
    assets = [("ipex-1", frozenset({"drive", "excavate", "haul", "dump"}))]
    a = match_task(task, assets)
    assert isinstance(a, Assignment)
    assert a.task_id == "t1" and a.asset_id == "ipex-1"
    assert set(a.capabilities_met) == {"excavate", "haul"}


def test_mp08_unmet_required_capability_blocks_assignment():  # [REQ:MP-08]
    task = Task(task_id="t2", mission_id="m1", kind="sinter", required_capabilities=("sinter",))
    assets = [("ipex-1", frozenset({"drive", "excavate", "haul"}))]      # no asset can sinter
    with pytest.raises(CapabilityUnmet):
        match_task(task, assets)


def test_mp08_rule_prefers_the_most_specialized_covering_asset():  # [REQ:MP-08]
    task = Task(task_id="t3", mission_id="m1", kind="haul", required_capabilities=("haul",))
    generalist = ("all-1", frozenset({"drive", "excavate", "haul", "dump", "grade"}))
    specialist = ("hauler-1", frozenset({"drive", "haul"}))
    a = match_task(task, [generalist, specialist])
    assert a.asset_id == "hauler-1"                                      # fewest extra capabilities wins


def test_mp08_effective_capabilities_include_mounted_tools():  # [REQ:MP-08]
    ipex = V.VEHICLES["ipex"]
    sinter_tool = V.TOOLS["sinter"]
    assert "sinter" not in effective_capabilities(ipex)                 # a bare IPEx cannot sinter
    assert "sinter" in effective_capabilities(ipex, tools=(sinter_tool,))  # the mounted tool grants it


def test_mp08_a_task_needing_the_tool_matches_only_the_tooled_asset():  # [REQ:MP-08]
    ipex = V.VEHICLES["ipex"]
    task = Task(task_id="t4", mission_id="m1", kind="sinter", required_capabilities=("sinter",))
    tooled = ("ipex-tooled", effective_capabilities(ipex, tools=(V.TOOLS["sinter"],)))
    bare = ("ipex-bare", effective_capabilities(ipex))
    assert match_task(task, [bare, tooled]).asset_id == "ipex-tooled"
    with pytest.raises(CapabilityUnmet):
        match_task(task, [bare])
