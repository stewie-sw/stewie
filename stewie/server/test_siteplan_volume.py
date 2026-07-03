"""[REQ:FR-13] the /siteplan/volume route emits the RegolithVolumeEstimate for a mission: a conserved,
uncertainty-carrying moved-regolith estimate cross-checked against the authority mass + drum, linked to a
world transaction -- the backend the cockpit/report volume surface consumes."""
import os

from stewie.server.routers.siteplan import VolumeRequest, siteplan_volume
from stewie.specs import constants as K

_SRV = os.path.dirname(os.path.abspath(__file__))

_ORDERS = [{"action": "src", "kind": "cut", "x": 5.0, "y": 5.0, "footprint_m2": 1.0, "depth_m": 0.013}]


def test_volume_route_returns_a_conserved_uncertainty_carrying_estimate():  # [REQ:FR-13]
    r = siteplan_volume(VolumeRequest(orders=_ORDERS, density_kg_m3=K.RHO_SURFACE, density_frac=0.1),
                        _auth="tester")
    assert r["ok"] is True
    v = r["volume"]
    assert v["observed_mass_kg"] > 0.0
    assert v["lower_kg"] <= v["observed_mass_kg"] <= v["upper_kg"]      # uncertainty band brackets it
    assert v["uncertainty_kg"] > 0.0
    assert v["agreement_conserved"] is True                             # conservation cross-check agrees
    assert v["confidence_class"] in ("high", "medium", "low")
    assert v["acceptance"] in ("accepted", "review")
    assert v["transaction_id"].startswith("plan:")                      # linked to the plan transaction


def test_volume_route_drum_cross_check_and_bad_input():  # [REQ:FR-13]
    # a matching drum inference -> both cross-checks agree -> accepted.
    r = siteplan_volume(VolumeRequest(orders=_ORDERS, density_kg_m3=K.RHO_SURFACE, density_frac=0.1,
                                      drum_inferred_kg=25.0), _auth="tester")
    assert r["volume"]["agreement_drum"] is True
    # a malformed order -> honest 400, not a crash.
    bad = siteplan_volume(VolumeRequest(orders=[{"action": "nonsense"}], density_kg_m3=K.RHO_SURFACE),
                          _auth="tester")
    assert getattr(bad, "status_code", 200) == 400 or bad.get("ok") is False


def test_cockpit_renders_the_volume_evidence_in_the_report_pane():  # [REQ:FR-13]
    # the render is WIRED: the Report pane carries the #volumeevidence container + the pure render module,
    # and cockpit.js fetches /siteplan/volume and renders it via the module.
    idx = open(os.path.join(_SRV, "index.html"), encoding="utf-8").read()
    cj = open(os.path.join(_SRV, "web", "assets", "cockpit.js"), encoding="utf-8").read()
    assert 'id="volumeevidence"' in idx, "no #volumeevidence container in the Report pane"
    assert "volume_evidence_html.js" in idx, "the volume-evidence render module is not loaded"
    assert "loadVolumeEvidence" in cj and "/siteplan/volume" in cj and "volumeEvidenceHTML" in cj, \
        "cockpit.js does not fetch + render the volume evidence"
