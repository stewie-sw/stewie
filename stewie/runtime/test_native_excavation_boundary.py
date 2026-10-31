"""Native Haworth operation refuses unresolved excavation without changing the world.

The 1 m SfS source cannot resolve either supported IPEx drum. These checks replace
positive excavation acceptance on generated 2–5 cm terrain, retired on 2026-10-15.
"""
from pathlib import Path

import numpy as np
import pytest

from stewie.runtime.test_viz2_runtime import Client
from stewie.runtime.viz2_runtime import Viz2Runtime

BUNDLE = Path(__file__).resolve().parents[2] / "samples/lunar_dem/haworth_sfs_2km_1m"


@pytest.mark.parametrize("drum", ["small", "medium"])
def test_unresolved_mutation_entry_points_preserve_native_world(tmp_path, drum):
    rt = Viz2Runtime(str(BUNDLE), session_dir=str(tmp_path), drum=drum)
    before = {name: field.copy() for name, field in rt.window_fields().items()}
    ledgers = (rt.ws.cut_total_kg, rt.ws.placed_total_kg, rt.ws.inventory_kg, rt._dig_energy_j)
    for operation, arguments in ((rt._apply_dig, {}), (rt._apply_dump, {}),
                                 (rt.autodig_trench, {"target_kg_per_pass": rt._drum_capacity_kg})):
        with pytest.raises(ValueError, match="does not resolve the drum footprint"):
            operation(**arguments)
        assert (rt.ws.cut_total_kg, rt.ws.placed_total_kg, rt.ws.inventory_kg, rt._dig_energy_j) == ledgers
        for name, field in before.items():
            assert np.array_equal(field, rt.window_fields()[name]), name


@pytest.mark.parametrize("cell_m", [0.02, 0.05])
def test_artificial_resolution_cannot_reenable_excavation(tmp_path, cell_m):
    with pytest.raises(ValueError, match="native DEM resolution"):
        Viz2Runtime(str(BUNDLE), session_dir=str(tmp_path), fine_cell_m=cell_m)
    assert not list(tmp_path.iterdir())


def test_socket_refuses_dig_and_dump_and_keeps_session_usable(tmp_path):
    with Viz2Runtime(str(BUNDLE), session_dir=str(tmp_path)) as rt:
        assert rt.wait_ready(10)
        client = Client(rt.port)
        try:
            assert client.handshake(rt.token)["ok"]
            for command in ("dig", "dump"):
                client._send({"cmd": command})
                refused = None
                for _ in range(15):
                    frame = client._recv_one()
                    if frame.get("type") == "command_refused":
                        refused = frame
                        break
                    client.ack(frame["seq"])
                assert refused is not None
                assert refused["cmd"] == command
                assert "does not resolve" in refused["reason"]
            client.twist(0.0, 0.0)
            assert client.drain(seconds=0.2)
            assert rt.ws.cut_total_kg == rt.ws.placed_total_kg == rt.ws.inventory_kg == 0
            assert not rt._pending_dig and not rt._pending_dump
        finally:
            client.close()
