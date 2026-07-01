"""FS-15 / FS-18 parity gate: the cockpit's typed frontend adapters (`web/assets/adapters.js`) map the
REAL FS-02 spine contracts (`stewie.contracts`), with NO invented fields. adapters.js is JS (not importable
here), so this test reads it as text and asserts, for every contract the adapter layer consumes:

  1. every snake_case field the adapter reads is an actual field on the Pydantic contract (catches the
     adapter reading a field the backend never had / renamed -- the fabrication / drift failure mode), and
  2. that field name literally appears in adapters.js (catches this map drifting from the JS), and
  3. every spine contract has a normalizer function in adapters.js (the adapter layer is COMPLETE), and
  4. ModelArtifact still exposes the canonical `deployment_ready` property that the JS `deploymentReady`
     derivation mirrors (so the ML-01 gate cannot silently change under the mirror).

This is why adapters.js is trustworthy: it is provably faithful to the typed source of truth.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import stewie.server.server as SRV
from stewie import contracts as C

_ADAPTERS_JS = Path(__file__).parent / "web" / "assets" / "adapters.js"

# contract class -> (its normalizer function in adapters.js, the contract fields that normalizer reads).
# The field lists are exactly what each normalizer consumes; every name here is a real contract field.
_ADAPTER_FIELDS: dict[type, tuple[str, list[str]]] = {
    C.EphemerisObservation: ("normalizeEphemeris", [
        "mission_t_s", "site_lat_deg", "site_lon_deg", "frame",
        "sun_az_deg", "sun_el_deg", "azimuth_convention", "uncertainty_deg", "source"]),
    C.WorldState: ("normalizeWorld", [
        "body", "frame", "rows", "cols", "cell_m", "datum_radius_m",
        "dem_source", "observed_fraction", "mutated"]),
    C.VehicleState: ("normalizeVehicle", [
        "vehicle_id", "role", "row", "col", "yaw_rad", "soc", "slip", "sinkage_m", "entrapped", "status"]),
    C.FleetState: ("normalizeFleet", ["vehicles", "reservations", "conflicts"]),
    C.ResourceReservation: ("normalizeFleet", ["resource_id", "vehicle_id", "t_start", "t_end"]),
    C.BeliefState: ("normalizeBelief", [
        "vehicle_id", "row", "col", "yaw_rad", "pos_sigma_m", "yaw_sigma_rad",
        "localized", "last_relocalization_t_s"]),
    C.PlanResult: ("normalizePlanResult", [
        "plan_id", "feasible", "n_orders", "vehicles", "makespan_s", "energy_j",
        "mass_moved_kg", "blocked_legs", "recharges", "drum_cycles", "cut_passes", "resolved_algorithm"]),
    C.ExecutionEvent: ("normalizeExecutionEvent", ["t_s", "vehicle_id", "kind", "detail", "outcome"]),
    C.TimelineFrame: ("normalizeTimelineFrame", [
        "t0", "t1", "phase", "x0", "y0", "x1", "y1", "batt0_frac", "batt1_frac", "cum_mass_kg"]),
    C.LocalizationFix: ("normalizeLocalizationFix", ["est", "true", "sigma", "fix"]),
    C.NavFactor: ("normalizeNavFactor", [
        "factor_id", "kind", "keyframe_i", "keyframe_j", "residual", "information", "accepted"]),
    C.PerceptionState: ("normalizePerception", [
        "source_profile", "frame_id", "point_topic", "point_count", "valid_fraction",
        "range_min_m", "range_max_m", "covariance_m", "panorama_cameras", "shadow_landmarks",
        "accepted_factors", "no_truth", "evidence_class"]),
    C.ModelArtifact: ("normalizeModelArtifact", [
        "model_id", "name", "version", "task", "dataset_lineage", "eval_split",
        "input_schema", "output_schema", "latency_budget_ms", "memory_budget_mb",
        "calibrated", "ood_detector", "fallback", "quantization", "rollback_to", "command_path"]),
    C.ConstructionSkill: ("normalizeSkill", [
        "skill_id", "name", "kind", "version", "n_steps", "closed_loop", "approved", "acceptance_note"]),
}


def _js() -> str:
    return _ADAPTERS_JS.read_text(encoding="utf-8")


def test_every_adapter_field_is_a_real_contract_field():  # [REQ:FS-15]
    # no fabricated fields: every name an adapter reads is an actual field on the Pydantic contract
    for contract, (_fn, fields) in _ADAPTER_FIELDS.items():
        model_fields = set(contract.model_fields)
        for f in fields:
            assert f in model_fields, f"{contract.__name__}: adapter reads '{f}' which is not a contract field"


def test_every_mapped_field_appears_in_adapters_js():  # [REQ:FS-18]
    # the map cannot silently drift from the JS: each field the map claims the adapter reads is in the file
    js = _js()
    for contract, (_fn, fields) in _ADAPTER_FIELDS.items():
        for f in fields:
            assert f in js, f"{contract.__name__}: field '{f}' is mapped but not present in adapters.js"


def test_every_spine_contract_has_a_normalizer():
    # the adapter layer is COMPLETE: every consumed spine contract has its normalizer function in adapters.js
    js = _js()
    for contract, (fn, _fields) in _ADAPTER_FIELDS.items():
        assert f"function {fn}(" in js, f"{contract.__name__}: no '{fn}' normalizer in adapters.js"


_WEB = _ADAPTERS_JS.parent
# FS-15 X (integration): a cockpit work area must CONSUME its normalized view model, not raw backend JSON.
# This maps each PRODUCTION cockpit module (NOT a *.test.js) to the view model it is required to call. Only
# the in-repo /plan-path contracts are listed: PlanResult (dashboard/CONOPS), TimelineFrame (Gantt/rover
# HUD), and LocalizationFix (nav-mission) have live data sources in the product path and are wired. The
# remaining FS-02 spine view models (Ephemeris/World/Vehicle/Fleet-live/Belief/ExecutionEvent/NavFactor/
# ModelArtifact/ConstructionSkill) target LIVE-RUNTIME or registry sources that are render/ROS/telemetry-
# gated (e.g. the Fleet ROSTER pane renders the static vehicle REGISTRY from /fleet, a different shape than
# the FleetState contract), so their pane wiring is tracked with those gated rows, not asserted here.
_PANE_CONSUMES = {
    "cockpit.js": ["normalizePlanResult", "normalizeLocalizationFix", "normalizePerception"],
    "rover_hud.js": ["normalizeTimelineFrame"],
}


def test_plan_path_panes_consume_view_models():  # [REQ:FS-15]
    # FS-15: the wired cockpit work areas read the NORMALIZED view model (STEWIE_ADAPTERS.normalize*),
    # never raw backend JSON. Regression guard: a pane silently reverting to raw fields fails here.
    for fname, fns in _PANE_CONSUMES.items():
        src = (_WEB / fname).read_text(encoding="utf-8")
        for fn in fns:
            assert f".{fn}(" in src, f"FS-15: {fname} no longer consumes the {fn} view model (raw-JSON regression?)"


def test_pane_view_models_are_real_adapters():  # [REQ:FS-15]
    # every view model a pane is asserted to consume must actually be a normalizer exported by adapters.js
    js = _js()
    for fns in _PANE_CONSUMES.values():
        for fn in fns:
            assert f"function {fn}(" in js, f"FS-15: pane consumes {fn} but adapters.js exports no such normalizer"


def test_model_artifact_keeps_the_canonical_deployment_ready_rule():
    # the JS deploymentReady MIRRORS this property; if the backend rule changes, the mirror must be revisited
    assert isinstance(getattr(C.ModelArtifact, "deployment_ready", None), property), (
        "ModelArtifact.deployment_ready property is gone -- the adapters.js deploymentReady mirror is now stale")
    # the real gate: a fully-declared model is deployment_ready; an undeclared one is not (the JS mirrors this)
    ready = C.ModelArtifact(model_id="m", name="n", version="1", task="terrain_assess",
                            dataset_lineage="d", eval_split="s", input_schema="WorldState",
                            output_schema="Traversability", latency_budget_ms=50, memory_budget_mb=512,
                            calibrated=True, ood_detector=True, fallback="costmap")
    assert ready.deployment_ready is True
    undeclared = C.ModelArtifact(model_id="m", name="n", version="1", task="rock_classify",
                                 dataset_lineage="d", eval_split="s")
    assert undeclared.deployment_ready is False


# ---------------------------------------------------------------------------------------------------------
# FS-18 route-to-pane CONTRACT GATE. Every work-area view the cockpit wires (a `data-view="..."` tab or
# profile-menu item in index.html) must be accounted for here, and every GET route -> pane connection must
# carry its full artifact set: (1) a committed schema fixture for the route's response shape, (2) this
# backend test asserting the LIVE route still matches that fixture, (3) a node test covering the pure JS
# adapter/renderer module, and (4) the served-page wiring (pane container + module load order + the
# per-pane python test that cites route and container). Wiring a NEW data-view without registering its
# artifacts fails test_every_wired_view_is_registered_in_the_pane_gate -- that is the gate.
# ---------------------------------------------------------------------------------------------------------

_SERVER = Path(__file__).parent
_INDEX = _SERVER / "index.html"
_COCKPIT = _WEB / "cockpit.js"
_FIXDIR = _SERVER / "fixtures" / "pane_contracts"

# GET route -> pane connections (cockpit loadPane fetches the route, the pure renderer builds the HTML).
# Each entry lists the FULL artifact set the FS-18 acceptance demands for a wired connection.
_ROUTE_PANES: dict[str, dict[str, str]] = {
    "fleet": {"route": "/fleet", "pane_id": "pane_fleet",
              "backend_test": "test_fleet_pane.py",
              "renderer": "fleet_render.js", "renderer_test": "fleet_render.test.js",
              "render_global": "STEWIE_FLEET_RENDER"},
    "construction": {"route": "/construction", "pane_id": "pane_construction",
                     "backend_test": "test_construction_pane.py",
                     "renderer": "construction_render.js", "renderer_test": "construction_render.test.js",
                     "render_global": "STEWIE_CONSTRUCTION_RENDER"},
    "models": {"route": "/models", "pane_id": "pane_models",
               "backend_test": "test_models_pane.py",
               "renderer": "models_render.js", "renderer_test": "models_render.test.js",
               "render_global": "STEWIE_MODELS_RENDER"},
    "trainer": {"route": "/trainer/history", "pane_id": "pane_trainer",
                "backend_test": "test_session.py",
                "renderer": "trainer_boards.js", "renderer_test": "trainer_boards.test.js",
                "render_global": "STEWIE_TRAINER_BOARDS"},
}

# Wired views whose pane surface is a composite/action/chrome view, NOT a single GET route -> renderer
# connection. Each is owned by its own requirement row + test file (named here so the claim is checkable):
#   plan      -- the default globe work area (FS-15/FS-16; consumes normalizePlanResult, asserted above)
#   rehearse  -- POST /resync/compare candidate compare (test_batch_ui.py, rehearse_render.test.js)
#   validate  -- sub-tab delegator to the nav/perception views (FS-16, test_cockpit_state_routing.py)
#   release   -- director sign-off POSTing /executive/release-plan (MO-02, test_executive_route.py)
#   metrics   -- Execute forecast/telemetry canvas (TR-01, test_session.py)
#   report    -- DT-01 world-state report over the /world/* routes (test_world_terrain_view.py)
#   settings / system / admin -- profile-menu chrome (FS-20, test_profile_menu_chrome.py)
_SHELL_VIEWS = frozenset({"plan", "rehearse", "validate", "release", "metrics", "report",
                          "settings", "system", "admin"})

# Views ABSENT from cockpit.js VIEW_PANE: setView handles them by delegation, not a pane div. The value is
# the literal delegation evidence that must stay present in cockpit.js.
_DELEGATED_VIEWS = {
    "plan": 'if (name === "plan") { showSiteDem();',       # Plan restores the globe inset work area
    "validate": '_validateSub || "nav"',                    # Validate delegates to its nav/perception sub-tab
    "system": "LAST_SYSTEM_VIEW",                           # System reopens the remembered sub-view cluster
}


def _wired_views() -> set[str]:
    return set(re.findall(r'data-view="([a-z_]+)"', _INDEX.read_text(encoding="utf-8")))


def _view_pane_map() -> dict[str, str]:
    m = re.search(r"const VIEW_PANE = \{(.*?)\};", _COCKPIT.read_text(encoding="utf-8"), re.S)
    assert m, "cockpit.js lost its VIEW_PANE view -> pane map"
    return dict(re.findall(r'(\w+):\s*"([\w-]+)"', m.group(1)))


def test_every_wired_view_is_registered_in_the_pane_gate():
    """[REQ:FS-18] the gate is SYSTEMATIC: the set of wired data-view tabs/menu items in the served page
    must equal the registered route-connections + shell views. A new pane wired without landing its
    contract artifacts (fixture + backend test + adapter test + served-page test) fails here."""
    wired, registered = _wired_views(), set(_ROUTE_PANES) | _SHELL_VIEWS
    assert wired - registered == set(), (
        f"wired pane(s) {sorted(wired - registered)} are not registered in the FS-18 contract gate -- "
        "add the schema fixture + backend/adapter/served-page tests and register the connection")
    assert registered - wired == set(), (
        f"gate registers {sorted(registered - wired)} but index.html no longer wires them -- prune the registry")


def test_every_wired_view_reaches_a_served_pane():  # [REQ:FS-18]
    """[REQ:FS-18] served-page leg: every wired view lands somewhere real -- either VIEW_PANE routes it to
    a pane container that exists in index.html, or setView carries the documented delegation."""
    html, js = _INDEX.read_text(encoding="utf-8"), _COCKPIT.read_text(encoding="utf-8")
    vp = _view_pane_map()
    for view in sorted(_wired_views()):
        if view in vp:
            assert f'id="{vp[view]}"' in html, f"{view}: VIEW_PANE targets #{vp[view]} but index.html has no such container"
        else:
            assert view in _DELEGATED_VIEWS, f"{view}: not in VIEW_PANE and no registered setView delegation"
            assert _DELEGATED_VIEWS[view] in js, f"{view}: setView lost its delegation ({_DELEGATED_VIEWS[view]!r})"


def test_route_pane_connections_carry_all_artifact_layers():  # [REQ:FS-18]
    """[REQ:FS-18] artifact checklist per GET route -> pane connection: the cockpit fetches the route, a
    backend test cites route + pane container, the pure renderer module is loaded before cockpit.js and
    sets its global, its node test requires the module, and the schema fixture is committed."""
    html, js = _INDEX.read_text(encoding="utf-8"), _COCKPIT.read_text(encoding="utf-8")
    i_cockpit = html.find("/assets/cockpit.js")
    for view, c in _ROUTE_PANES.items():
        assert f'fetch("{c["route"]}"' in js, f"{view}: cockpit.js no longer fetches {c['route']}"
        backend = (_SERVER / c["backend_test"]).read_text(encoding="utf-8")
        assert c["route"] in backend and c["pane_id"] in backend, (
            f"{view}: {c['backend_test']} does not cite both the route ({c['route']}) and the pane container")
        renderer = (_WEB / c["renderer"]).read_text(encoding="utf-8")
        assert c["render_global"] in renderer, f"{view}: {c['renderer']} does not set window.{c['render_global']}"
        i_mod = html.find(f"/assets/{c['renderer']}")
        assert -1 < i_mod < i_cockpit, f"{view}: {c['renderer']} must be loaded by index.html BEFORE cockpit.js"
        node_test = (_WEB / c["renderer_test"]).read_text(encoding="utf-8")
        assert f'require("./{c["renderer"]}")' in node_test, (
            f"{view}: {c['renderer_test']} does not exercise the {c['renderer']} module")
        assert (_FIXDIR / f"{view}.json").is_file(), (
            f"{view}: no committed schema fixture at fixtures/pane_contracts/{view}.json")


def _merge_shapes(a, b):
    """Merge two item shapes into the contract EVERY item honors: common dict keys (a template list may
    carry per-kind extras -- e.g. /construction defaults differ per structure), int|float -> float, and
    genuinely mixed kinds -> 'null' (constrains nothing rather than inventing a type)."""
    if isinstance(a, dict) and isinstance(b, dict):
        return {k: _merge_shapes(a[k], b[k]) for k in sorted(set(a) & set(b))}
    if isinstance(a, list) and isinstance(b, list):
        if not a or not b:
            return a or b                                  # an empty capture cannot constrain the items
        return [_merge_shapes(a[0], b[0])]
    if a == b:
        return a
    if {a, b} == {"int", "float"}:
        return "float"
    return "null"


def _shape_of(v):
    """Recursive shape of a REAL route response: dicts keep their keys, lists keep the merged shape all
    their items share, scalars reduce to a type name. This is what the committed fixture freezes."""
    if isinstance(v, dict):
        return {k: _shape_of(v[k]) for k in sorted(v)}
    if isinstance(v, list):
        shapes = [_shape_of(item) for item in v]
        if not shapes:
            return []
        merged = shapes[0]
        for s in shapes[1:]:
            merged = _merge_shapes(merged, s)
        return [merged]
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, int):
        return "int"
    if isinstance(v, float):
        return "float"
    if v is None:
        return "null"
    return "str"


def _conformance_errors(v, shape, path: str) -> list[str]:
    """Drift check, additive-tolerant: every fixture key must still exist with the fixture's type (extra
    NEW fields are allowed -- adding is contract-safe, renaming/removing/retyping is what breaks panes).
    A live None passes anywhere (optional field); a 'null'-captured shape constrains nothing; a live int
    satisfies a 'float' capture (whole-valued floats serialize as ints)."""
    if v is None or shape == "null":
        return []
    if isinstance(shape, dict):
        if not isinstance(v, dict):
            return [f"{path}: expected object, got {type(v).__name__}"]
        errs = []
        for k, sub in shape.items():
            if k not in v:
                errs.append(f"{path}.{k}: field disappeared from the live response")
            else:
                errs.extend(_conformance_errors(v[k], sub, f"{path}.{k}"))
        return errs
    if isinstance(shape, list):
        if not isinstance(v, list):
            return [f"{path}: expected array, got {type(v).__name__}"]
        if not shape:
            return []
        return [e for i, item in enumerate(v) for e in _conformance_errors(item, shape[0], f"{path}[{i}]")]
    got = _shape_of(v)
    if got == shape or (shape == "float" and got == "int"):
        return []
    return [f"{path}: expected {shape}, got {got}"]


@pytest.fixture()
def pane_client(monkeypatch):
    monkeypatch.delenv("STEWIE_API_KEY", raising=False)
    monkeypatch.setenv("STEWIE_DEV_OPEN", "1")            # loopback in-process -> require_auth = dev-open (director)
    return TestClient(SRV.app)


def test_pane_routes_match_their_committed_schema_fixtures(pane_client):
    """[REQ:FS-18] backend-contract leg: each pane route's LIVE response (real registries / real persisted
    records under the isolated data dir) still conforms to its committed schema fixture. The fixture is a
    capture of the real response shape, never hand-invented; after a DELIBERATE contract change regenerate
    with STEWIE_WRITE_PANE_FIXTURES=1 (then re-review the adapter + renderer against the new shape)."""
    regen = os.environ.get("STEWIE_WRITE_PANE_FIXTURES") == "1"
    for view, c in _ROUTE_PANES.items():
        r = pane_client.get(c["route"])
        assert r.status_code == 200, f"{view}: GET {c['route']} -> {r.status_code}: {r.text[:200]}"
        body = r.json()
        fixture = _FIXDIR / f"{view}.json"
        if regen:
            _FIXDIR.mkdir(parents=True, exist_ok=True)
            fixture.write_text(json.dumps({
                "pane": view, "route": c["route"],
                "provenance": "captured from the live dev-open TestClient response (real registries, "
                              "isolated data dir); regenerate via STEWIE_WRITE_PANE_FIXTURES=1 pytest",
                "shape": _shape_of(body)}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        assert fixture.is_file(), f"{view}: schema fixture missing -- run once with STEWIE_WRITE_PANE_FIXTURES=1"
        fx = json.loads(fixture.read_text(encoding="utf-8"))
        assert fx["route"] == c["route"], f"{view}: fixture pins {fx['route']}, the registry wires {c['route']}"
        errs = _conformance_errors(body, fx["shape"], view)
        assert not errs, f"{view}: GET {c['route']} drifted from its committed schema fixture:\n  " + "\n  ".join(errs)
