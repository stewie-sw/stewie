"""#173: the charger registry (surface recharge stations) -- well-formed, accessible, vehicle-associated.

Real registry values only: the surface recharge power is the [CALIB] ipex_specs.RECHARGE_POWER_W that the
planner already uses, surfaced through the registry as the single source -- not a newly fabricated number.
"""
import dataclasses

import pytest

from stewie.specs import ipex_specs as S
from stewie.specs import vehicles as V


def test_registry_well_formed_and_frozen():
    assert V.CHARGERS and V.DEFAULT_CHARGER in V.CHARGERS
    for name, c in V.CHARGERS.items():
        assert c.name == name and c.label
        assert c.recharge_power_w > 0 and c.concurrent >= 1
        assert isinstance(c.serves, tuple) and c.serves
        assert c.provenance                                   # every value provenance-tagged (no bare fabrication)
    with pytest.raises(dataclasses.FrozenInstanceError):      # frozen like the other registry models
        V.CHARGERS["surface_pad"].recharge_power_w = 1.0


def test_surface_pad_power_is_the_sourced_calib_value():
    # the pad's power IS the planner's [CALIB] recharge constant -- registry = single source, not a new value
    assert V.get_charger("surface_pad").recharge_power_w == S.RECHARGE_POWER_W


def test_get_charger_idempotent_and_unknown_raises():
    assert V.get_charger("surface_pad").name == "surface_pad"
    assert V.get_charger(V.get_charger("surface_pad")).name == "surface_pad"   # idempotent on a Charger
    with pytest.raises(KeyError):
        V.get_charger("warp_core")


def test_chargers_for_vehicle_association():
    # '*' chargers serve any vehicle; the serves-association is the per-vehicle expandability hook (#173)
    served = V.chargers_for_vehicle(V.DEFAULT_VEHICLE)
    assert served and all(isinstance(c, V.Charger) for c in served)
    assert any(c.name == "surface_pad" for c in served)
    # a charger restricted to a specific platform is NOT returned for an unrelated one
    only_ez = V.Charger("only_ez", "EZ dock", recharge_power_w=100.0, serves=("ez_rassor",), provenance="test")
    V.CHARGERS["only_ez"] = only_ez
    try:
        assert only_ez not in V.chargers_for_vehicle("ipex")
        assert only_ez in V.chargers_for_vehicle("ez_rassor")
    finally:
        del V.CHARGERS["only_ez"]
