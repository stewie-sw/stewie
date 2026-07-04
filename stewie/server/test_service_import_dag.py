"""[REQ:EG-09] The backend service-separation import-DAG guard: the bounded services form a DAG (no
cross-service back-edges), CORE is a sink, and the ROS2 egress lives in exactly one service (execution)."""
import pathlib

from stewie.server.service_boundaries import (
    CORE,
    SERVICES,
    build_service_graph,
    find_cycle,
    rclpy_importers,
    service_of,
)

_ROUTERS = pathlib.Path(__file__).resolve().parent / "routers"


def test_eg09_service_graph_is_acyclic():  # [REQ:EG-09]
    cycle = find_cycle(build_service_graph())
    assert cycle is None, f"cross-service import cycle (back-edge): {' -> '.join(cycle)}"


def test_eg09_core_is_a_sink():  # [REQ:EG-09]
    # CORE (shared infra) must not import a SERVICE -- it is the leaf every service depends on.
    graph = build_service_graph()
    leaked = graph.get(CORE, set()) & set(SERVICES)
    assert not leaked, f"CORE imports a service (layering inversion): {sorted(leaked)}"


def test_eg09_rclpy_egress_is_execution_only():  # [REQ:EG-09]
    importers = rclpy_importers()
    assert importers, "expected the ROS2 bridge to import rclpy (the egress seam must exist)"
    for mod in importers:
        assert service_of(mod) == "execution", f"rclpy imported outside the execution service: {mod}"


def test_eg09_relocated_reachthroughs_are_gone():  # [REQ:EG-09]
    # the two historical cross-service back-edges were relocated to CORE (regression guard):
    assert "from stewie.server.routers.plan import" not in (_ROUTERS / "gis_export.py").read_text(), \
        "gis_export still reaches into routers.plan (heavy_quota should come from deps)"
    assert "from stewie.server.routers.twin import" not in (_ROUTERS / "executive.py").read_text(), \
        "executive still reaches into routers.twin (_terrain_lock should come from world_state)"
