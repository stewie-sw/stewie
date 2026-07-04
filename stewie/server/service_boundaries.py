"""[REQ:EG-09] Backend service-separation manifest + the import-boundary DAG (PRD §29.2).

The backend is organized into BOUNDED services. This module is the DOCUMENTED ownership manifest that assigns
each backend module to a service, plus the AST-based import-graph builder the EG-09 guard test uses to assert
the services form a DAG (no cross-service back-edges) and that the ROS2 egress lives in exactly one service.

The layering is three tiers, and the DAG is asserted over the SERVICE tier:
  * ROOT   -- the app composition root (``server.py``): mounts every router; may import anything (a source).
  * SERVICE -- the bounded services below: the routers (world/mission/asset/physics/sim/execution/...) and the
    ROS2 bridge (execution). A service may import CORE freely and ROOT never; it must NOT import another
    service's private module (that is the cross-service back-edge EG-09 forbids). The two historical
    reach-throughs (``routers.plan.heavy_quota`` reached by gis_export; ``routers.twin._terrain_lock`` reached
    by executive) were relocated to CORE (``deps`` / ``world_state``) so this tier is now acyclic.
  * CORE   -- shared infrastructure (``deps``/``state``/``services``/``world_state``/``ratelimit``/``schemas``
    /...): the leaf every service may depend on. CORE must not import a SERVICE (it is a sink).

SERVICE ASSIGNMENT is a design choice (the §29.2 taxonomy over the 35 routers); it is spelled out in
``_ROUTER_SERVICE`` below and is meant to be reviewed/adjusted -- the guard test re-derives the graph from
whatever this manifest says, so a re-assignment is a one-line change here, not a test rewrite.
"""
from __future__ import annotations

import ast
import pathlib

_SERVER = pathlib.Path(__file__).resolve().parent            # stewie/server
_BRIDGE = _SERVER.parent / "bridge"                          # stewie/bridge (the execution ROS2 seam)

CORE = "core"
ROOT = "root"

#: the twelve bounded services (§29.2) the routers map onto. `execution` also owns the ROS2 bridge.
SERVICES: tuple[str, ...] = ("config", "auth", "world", "mission", "asset", "physics", "sim",
                             "execution", "reconcile", "training", "audit", "admin")

#: per-ROUTER service ownership (stewie/server/routers/<name>.py). Unlisted routers default to CORE-adjacent
#: read surfaces (health/pages/program) -> treated as `admin`/`audit` read services. Reviewable design choice.
_ROUTER_SERVICE: dict[str, str] = {
    "config": "config", "schema": "config", "profiles": "config", "models": "physics",
    "auth": "auth", "session": "auth", "invites": "auth", "operators_admin": "auth",
    "twin": "world", "world": "world", "dem": "world", "layers": "world", "tiles": "world",
    "gis_export": "world", "ogc": "world", "solar": "world", "ephemeris": "world", "siteplan": "world",
    "nav": "world", "structures": "world",
    "plan": "mission", "missions": "mission", "sample_missions": "mission", "construction": "mission",
    "assets": "asset", "fleet": "asset",
    "perception": "sim", "figures": "sim",
    "rc": "execution", "executive": "execution",
    "evidence": "audit", "program": "audit",
    "admin_ops": "admin", "health": "admin", "pages": "admin",
}


#: server-level (non-router) modules that belong to a SERVICE rather than shared CORE -- a module that
#: consumes the ROS2 bridge is execution-domain (ros_evidence records ROS autonomy evidence; session reads
#: ROS telemetry), not shared infra. Unlisted server modules are shared CORE (deps/state/services/...).
_SERVER_MODULE_SERVICE: dict[str, str] = {"ros_evidence": "execution", "session": "execution"}


def service_of(module: str) -> str:
    """Map a dotted ``stewie...`` module name to its service (or CORE/ROOT). Unknown -> CORE (a leaf)."""
    if module == "stewie.server.server":
        return ROOT
    if module.startswith("stewie.bridge"):
        return "execution"                                   # the whole ROS2 bridge is the execution service
    if module.startswith("stewie.server.routers."):
        return _ROUTER_SERVICE.get(module.rsplit(".", 1)[1], "admin")
    if module.startswith("stewie.server."):
        return _SERVER_MODULE_SERVICE.get(module.rsplit(".", 1)[1], CORE)
    return CORE                                              # everything else is a shared leaf


def _module_name(path: pathlib.Path) -> str:
    """The dotted stewie... module name for a file under stewie/server or stewie/bridge."""
    rel = path.relative_to(_SERVER.parent.parent).with_suffix("")   # from repo/stewie/..
    return ".".join(rel.parts)


def _imports(path: pathlib.Path) -> set[str]:
    """The set of ``stewie.server`` / ``stewie.bridge`` modules `path` imports (top-level AND function-local
    -- both count for the boundary; the whole point is that no reach-through hides in a lazy import)."""
    out: set[str] = set()
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and (
                node.module.startswith("stewie.server") or node.module.startswith("stewie.bridge")):
            out.add(node.module)
        elif isinstance(node, ast.Import):
            out.update(a.name for a in node.names
                       if a.name.startswith("stewie.server") or a.name.startswith("stewie.bridge"))
    return out


def build_service_graph() -> dict[str, set[str]]:
    """The SERVICE import graph: an edge ``s -> t`` iff some module owned by service ``s`` imports a module
    owned by a DIFFERENT service ``t``. Excludes self-edges. Nodes are services + CORE + ROOT."""
    graph: dict[str, set[str]] = {}
    for path in sorted([*_SERVER.rglob("*.py"), *_BRIDGE.glob("*.py")]):
        if path.name.startswith("test_") or path.name == "__init__.py":
            continue
        src = service_of(_module_name(path))
        for imp in _imports(path):
            dst = service_of(imp)
            if dst != src:
                graph.setdefault(src, set()).add(dst)
        graph.setdefault(src, set())
    return graph


def find_cycle(graph: dict[str, set[str]]) -> list[str] | None:
    """A cycle in the service graph as an ordered node list, or None if the graph is a DAG (DFS 3-color)."""
    WHITE, GREY, BLACK = 0, 1, 2
    color = dict.fromkeys(graph, WHITE)
    stack: list[str] = []

    def visit(n: str) -> list[str] | None:
        color[n] = GREY
        stack.append(n)
        for m in sorted(graph.get(n, ())):
            if color.get(m, WHITE) == GREY:
                return stack[stack.index(m):] + [m]
            if color.get(m, WHITE) == WHITE and (c := visit(m)):
                return c
        color[n] = BLACK
        stack.pop()
        return None

    for node in sorted(graph):
        if color.get(node, WHITE) == WHITE and (cyc := visit(node)):
            return cyc
    return None


def rclpy_importers() -> set[str]:
    """Every stewie module that imports ``rclpy`` (the ROS2 client) -- must be within the execution service."""
    importers: set[str] = set()
    for path in sorted((_SERVER.parent).rglob("*.py")):      # scan all of stewie/
        if path.name.startswith("test_"):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import) and any(a.name.split(".")[0] == "rclpy" for a in node.names):
                importers.add(_module_name(path) if path.is_relative_to(_SERVER.parent) else path.name)
            elif isinstance(node, ast.ImportFrom) and node.module and node.module.split(".")[0] == "rclpy":
                importers.add(_module_name(path) if path.is_relative_to(_SERVER.parent) else path.name)
    return importers
