"""[REQ:AC-01] the generated TypeScript API client stays in sync with the live FastAPI OpenAPI (a new/renamed
backend route reds the --check drift gate), every router-owned route is covered by the committed client, and
mutating methods are flagged. Real: the client is regenerated from the actual app.openapi(), never a fixture."""
import re

from scripts import gen_ts_api_client as GEN

from stewie.server import route_registry as REG
from stewie.server.server import app


def _live_spec():
    return app.openapi()


def _committed_client_paths() -> set[str]:
    with open(GEN._OUT, encoding="utf-8") as fh:
        return set(re.findall(r"path: '([^']+)'", fh.read()))


def test_committed_client_in_sync_with_openapi():   # [REQ:AC-01] the drift gate
    assert GEN.main(["--check"]) == 0, "api_client.ts drifted from the FastAPI OpenAPI; run gen_ts_api_client.py"


def test_every_router_owned_route_is_covered():     # [REQ:AC-01] coverage
    gap = REG.coverage_gap(_live_spec(), _committed_client_paths())
    assert gap == [], f"router-owned routes missing from the client (add route or exempt): {gap}"


def test_static_infra_routes_are_exempt_not_router_owned():  # [REQ:AC-01] exemptions are explicit
    assert REG.is_exempt("/healthz") and REG.is_exempt("/") and REG.is_exempt("/assets/x.js")
    assert "/healthz" not in REG.router_owned_paths(_live_spec())


def test_mutating_methods_flagged_read_methods_not():  # [REQ:AC-01] mutatesAuthority derivation
    routes = GEN._routes_from_openapi(_live_spec())
    assert any(r["mutates"] for r in routes if r["method"] == "POST")
    assert all(not r["mutates"] for r in routes if r["method"] == "GET")


def test_regeneration_is_deterministic():           # [REQ:AC-01] stable output (no spurious drift)
    spec = _live_spec()
    assert GEN.render(spec) == GEN.render(spec)
