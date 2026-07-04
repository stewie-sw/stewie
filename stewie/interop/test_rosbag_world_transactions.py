"""[REQ:BA-06] world-transaction events <-> rosbag2 round-trip with EVENT COUNT preserved. The bag I/O is
container-gated (rosbag2_py) and SKIPS on the CPU-only host (verified in stewie-gazebo); the serialization
half (real WorldTransaction -> event dict -> JSON -> dict) is tested on-host on REAL transactions built from
real conserved-physics state + a real Haworth DEM tile (never synthetic)."""
import importlib.util
import json
import os

import numpy as np
import pytest

from stewie.interop.rosbag_world_transactions import (
    event_to_json,
    json_to_event,
    world_transaction_to_event,
)

_HAVE_ROSBAG = importlib.util.find_spec("rosbag2_py") is not None
_DEM = "samples/lunar_dem/haworth_10km_5m"


def _real_transactions(n: int = 5):
    from stewie.contracts import BeliefState, PlanResult
    from stewie.physics.column_state import ColumnState
    from stewie.twin import envelope as E
    from stewie.twin import versioned as vt
    meta = json.load(open(os.path.join(_DEM, "metadata.json")))["grid"]
    z = np.fromfile(os.path.join(_DEM, "heightmap.rf32"), dtype="<f4").reshape(meta["height"], meta["width"])
    tile = z[:32, :32].astype(float) - float(z[:32, :32].min())      # REAL Haworth relief (de-based, real data)
    twin = vt.TwinStore(tile, cell_m=float(meta["cell_m"]))
    plan = PlanResult(plan_id="pad-001", feasible=True, n_orders=3, vehicles=1, makespan_s=420.0, energy_j=1.2e6)
    belief = BeliefState(vehicle_id="ipex", row=4.0, col=5.0, yaw_rad=0.1, pos_sigma_m=0.3)
    log = E.TransactionLog()
    return [log.commit(authority=ColumnState(width=16, height=16, cell_m=0.5), twin=twin, plan=plan,
                       belief=belief, mission=f"m{i}", site="haworth", body="moon", mission_t_s=float(i),
                       provenance="SIM as-built") for i in range(n)]


def test_ba06_world_transaction_event_serialization_roundtrip():  # [REQ:BA-06] (on-host, real data)
    events = [world_transaction_to_event(t) for t in _real_transactions(5)]
    assert len(events) == 5 and all(isinstance(e, dict) and "chain_hash" in e for e in events)
    back = [json_to_event(event_to_json(e)) for e in events]      # the payload the rosbag carries
    assert back == events


@pytest.mark.skipif(
    not _HAVE_ROSBAG,
    reason="[REQ:BA-06] rosbag2_py needed for the bag I/O (container-gated; verified in stewie-gazebo)",
)
def test_ba06_rosbag_world_transactions_roundtrip_preserves_count(tmp_path):  # [REQ:BA-06]
    from stewie.interop.rosbag_world_transactions import read_events_from_rosbag, write_events_to_rosbag
    events = [world_transaction_to_event(t) for t in _real_transactions(7)]
    uri = str(tmp_path / "bag")
    assert write_events_to_rosbag(events, uri) == 7
    assert len(read_events_from_rosbag(uri)) == 7                 # EVENT COUNT preserved through the bag
