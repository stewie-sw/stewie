"""Sourced drum limits only. Native DEM cells do not resolve runtime excavation."""
from __future__ import annotations


from stewie.specs.ipex_specs import (
    DRUM_CAPACITY_KG,
    REGOLITH_PER_CYCLE_KG,
)

def test_drum_capacity_keeps_a_cycle_inside_the_rds_envelope() -> None:
    """[REQ:PX-09] The sourced single-drum capacity is below the 30 kg/cycle RDS envelope.
    This checks constants, not native-runtime excavation or two-drum throughput."""
    for drum, cap in DRUM_CAPACITY_KG.items():
        assert float(cap) <= REGOLITH_PER_CYCLE_KG, (
            f"the {drum} drum's {cap} kg hold exceeds the {REGOLITH_PER_CYCLE_KG} kg/cycle RDS envelope")
