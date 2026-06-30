"""#273: the planner's FLAT per-metre drive ENERGY is the gravity-aware lunar tractive draw
(ipex_specs.lunar_drive_power_w at the body's g), NOT the Earth-test Table-3 motor draw (~40 W,
veh.drive_power_w) which over-estimates the lunar flat-drive ~6x. Grounded physics F = m*g*(crr*cos th
+ sin th) (crr + drivetrain efficiency are tagged estimates); drive_power_w stays the raw spec (offload).
Both the module default (drive_energy_per_m) AND the per-body plan_context are fixed, so they agree.
"""
import math

from lode import mission_planner as MP
from lode.planner_constants import DRIVE_J_PER_M, DRIVE_SPEED_MS
from lode.planner_model import body_gravity
from stewie.specs import ipex_specs


def _mission(body):
    return MP.mission_from_dict({"name": "e", "body": body, "charger": [0, 0], "orders": [
        {"action": "cut", "kind": "cut", "x": 40, "y": 30, "footprint_m2": 36, "depth_m": 0.04}]})


def test_module_default_drive_energy_is_lunar_not_earth_test():
    # the module constant (Moon default) is the grounded lunar value, ~6x below the Earth-test motor draw
    earth_test = ipex_specs.drive_power_w() / DRIVE_SPEED_MS
    assert DRIVE_J_PER_M < earth_test / 3.0, (
        f"module DRIVE_J_PER_M still ~Earth-test ({DRIVE_J_PER_M:.1f} vs {earth_test:.1f} J/m) (#273)")
    assert math.isclose(DRIVE_J_PER_M, ipex_specs.lunar_drive_power_w(slope_deg=0.0) / DRIVE_SPEED_MS, rel_tol=1e-9)


def test_plan_context_flat_drive_is_lunar_and_matches_the_module_default():
    ctx = MP.plan_context(_mission("moon"))
    # ipex Moon mission: the per-body context == the module Moon default (byte-identical, no split)
    assert math.isclose(ctx.drive_j_per_m, DRIVE_J_PER_M, rel_tol=1e-9), "per-body vs module-default split (#273)"
    expect = ipex_specs.lunar_drive_power_w(
        slope_deg=0.0, mass_kg=ctx.rover_mass_kg, g_ms2=body_gravity("moon")) / DRIVE_SPEED_MS
    assert math.isclose(ctx.drive_j_per_m, expect, rel_tol=1e-9)


def test_drive_energy_scales_with_body_gravity():
    moon = MP.plan_context(_mission("moon")).drive_j_per_m
    mars = MP.plan_context(_mission("mars")).drive_j_per_m
    assert mars > moon, "a higher-gravity body must cost MORE flat-drive energy (gravity-aware) (#273)"
    # same vehicle/crr/efficiency/speed -> the ratio is exactly the gravity ratio
    assert math.isclose(mars / moon, body_gravity("mars") / body_gravity("moon"), rel_tol=1e-6)
