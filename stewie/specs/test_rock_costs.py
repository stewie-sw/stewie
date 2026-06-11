"""Unified planner cost from classified rocks: D/E -> keep-outs, A/B/C traversable; loc-class bonus."""
import math

from stewie.specs import rock_costs as RC
from dart import rock_taxonomy as RT


def test_only_hazard_classes_become_keepouts():
    rocks = [(10, 0, RT.classify(0.05)), (12, 0, RT.classify(0.10)), (14, 0, RT.classify(0.25)),
             (16, 0, RT.classify(0.40)), (18, 0, RT.classify(0.70))]   # A B C D E
    ko = RC.rock_keepouts(rocks)
    assert len(ko) == 2 and all(k["r"] > 0 for k in ko)                # only D + E


def test_nav_cost_monotonic():
    assert RC.nav_cost("A") == 0.0 < RC.nav_cost("C") < RC.nav_cost("D")
    assert math.isinf(RC.nav_cost("E"))


def test_localization_value_rewards_persistent_landmarks():
    assert RC.localization_value("L2") > RC.localization_value("L1") > RC.localization_value("L0")


def test_soft_cost_excludes_hard_rocks():
    rocks = [(5, 0, RT.classify(0.10)), (5, 0, RT.classify(0.70))]     # B (soft) + E (keep-out, excluded)
    assert RC.traverse_cost(rocks, 5, 0, radius_m=1.0) == RC.nav_cost("B")
