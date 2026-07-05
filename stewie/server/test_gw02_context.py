"""[REQ:GW-02] the unified PRD2 workspace context: the React workspace state declares the full field set
(the mission-lifecycle branch/release/run/time cursor + the spatial CRS/frame/selection) beyond the RF-02/FR-02
fields, and the routeable subset round-trips through the URL — one URL restores the whole view. Source-parsed
against the committed frontend + the design-doc context field list (PRD2 L134-155)."""
import os

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _f(*p: str) -> str:
    with open(os.path.join(_ROOT, "frontend", "src", *p), encoding="utf-8") as fh:
        return fh.read()


def test_gw02_workspace_declares_the_full_prd2_context():  # [REQ:GW-02]
    ws = _f("workspace.ts")
    for field in ("siteCrs", "localFrame", "fleet", "selectedEntity", "selectedLayers",
                  "timeCursor", "branch", "release", "run"):
        assert f"{field}:" in ws, f"workspace context is missing the PRD2 field {field}"


def test_gw02_context_is_url_routeable():  # [REQ:GW-02]
    ws = _f("workspace.ts")
    for field in ("siteCrs", "localFrame", "fleet", "selectedEntity", "timeCursor", "branch", "release", "run"):
        assert f'"{field}"' in ws, f"{field} is not URL-routeable (missing from ROUTEABLE)"
    # the array field (selectedLayers) round-trips as a comma-joined `layers` param
    assert 'p.set("layers"' in ws and 'params.get("layers")' in ws
