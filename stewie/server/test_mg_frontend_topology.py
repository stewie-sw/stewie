"""[REQ:MG-01][REQ:MG-02] The frontend topology of RECORD — and the retirement that the MG rows govern.

MG-01/MG-02 governed an `/app -> /app2` vanilla-cockpit-to-React migration WITH per-pane parity gates. That
migration was **never adopted**: there is no `/app2`, and the strangler-fig React rewrite was reverted after
it black-screened on Cesium init (`55c44c6`). So these rows are resolved by a DECISION, not a build, and the
honest thing to verify is that the decision HELD and the real surfaces still serve.

REAL TOPOLOGY (asserted below against the live FastAPI app + the route registry):
  * `/`      -- the vanilla cockpit / OpenLayers viewer shell (served, MG-01: "stays served")
  * `/app`   -- the React SPA fallback (served; React Router owns client-side routing under it)
  * `/ide`   -- the QWC2/OpenLayers workbench = the PRODUCT FRONT DOOR (served by the artemis edge, a
                separate surface, NOT a pane-by-pane flip of the vanilla cockpit)
  * `/app2`  -- DOES NOT EXIST. The migration target was never built (MG-02 retirement).

MG-01's other half -- "its smoke tests keep passing" -- is carried by the mobile command-surface smoke gate
[REQ:FR-20] (`test_fr20_mobile_smoke.py`), which boots the real cockpit across five viewports.
"""
from __future__ import annotations

import stewie.server.server as srv
from stewie.server import route_registry as RR


def _paths() -> set[str]:
    return {getattr(r, "path", None) for r in srv.app.routes}


def test_the_vanilla_cockpit_and_react_shell_both_stay_served():  # [REQ:MG-01]
    paths = _paths()
    assert "/" in paths, "the vanilla cockpit / viewer shell is no longer served (MG-01 regressed)"
    assert "/app" in paths, "the React SPA shell is no longer served"
    # both are registered as static/infra shells (not part of the typed API surface) -- the topology of record
    assert RR.is_exempt("/") and RR.is_exempt("/app"), \
        "the cockpit shells are not exempt static routes -- the route registry disagrees with the topology"


def test_the_retired_app2_migration_target_was_never_built():  # [REQ:MG-02]
    paths = _paths()
    assert not any((p or "").startswith("/app2") for p in paths), (
        "an /app2 route exists -- the vanilla->React per-pane migration these rows retired was adopted after "
        "all; re-open MG-01/MG-02")
    # and the router-owned API surface never referenced a /app2 either
    assert "/app2" not in RR.EXEMPT_EXACT and "/app2/" not in RR.EXEMPT_PREFIX


def test_the_product_front_door_is_the_ide_not_a_flipped_cockpit_pane():  # [REQ:MG-02]
    # /ide (QWC2) is served by the artemis edge, a SEPARATE surface -- so it is deliberately NOT a FastAPI
    # app route here. The decision of record: the product front door is the workbench, not a pane-by-pane
    # React flip of the vanilla cockpit. Assert the vanilla cockpit was NOT itself replaced pane-by-pane
    # (its shell still serves the vanilla index, unchanged).
    assert "/ide" not in _paths(), \
        "/ide became a FastAPI app route -- it is meant to be the artemis-edge QWC2 workbench, a separate surface"
