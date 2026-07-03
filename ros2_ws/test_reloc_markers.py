"""[REQ:AS-09] the relocalization MarkerArray publisher: accepted standstill fixes become RViz markers
(matched landmarks + covariance ellipse); rejected fixes produce none; and mission.rviz displays the topic
so the relocalization factors are visible in RViz (they are already in the cockpit via navplot)."""
import importlib.util
import os

_HERE = os.path.dirname(__file__)
_NODE = os.path.join(_HERE, "src", "stewie_localization", "stewie_localization", "node.py")
_RVIZ = os.path.join(_HERE, "src", "stewie_rviz", "rviz", "mission.rviz")


def _mod():
    spec = importlib.util.spec_from_file_location("stewie_localization_node", _NODE)
    assert spec and spec.loader, f"cannot load {_NODE}"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_only_accepted_reloc_factors_become_markers_with_landmarks_and_covariance():  # [REQ:AS-09]
    mod = _mod()
    fixes = [
        {"accepted": True, "position_xy": (10.0, 5.0), "landmarks_xy": [(0, 0), (10, 0), (5, 8)],
         "cov_post": [[0.04, 0.0], [0.0, 0.09]]},
        {"accepted": False, "position_xy": (1.0, 1.0), "landmarks_xy": [(0, 0), (1, 0)],
         "cov_post": [[1.0, 0.0], [0.0, 1.0]]},
    ]
    markers = mod.RelocMarkers.factors_to_markers(fixes)
    ns = [m["ns"] for m in markers]
    # the REJECTED factor produced NO markers (not inserted into the graph -> not shown as accepted evidence).
    assert ns.count("reloc_landmarks") == 1 and ns.count("reloc_covariance") == 1
    lm = next(m for m in markers if m["ns"] == "reloc_landmarks")
    assert lm["type"] == "SPHERE_LIST" and len(lm["points"]) == 3   # the 3 matched landmarks
    cov = next(m for m in markers if m["ns"] == "reloc_covariance")
    # the ellipse full-axes = 2*sigma = 2*sqrt(variance): {2*0.2, 2*0.3} = {0.4, 0.6} (order-agnostic).
    axes = {round(cov["scale"][0], 2), round(cov["scale"][1], 2)}
    assert axes == {0.4, 0.6}, f"covariance ellipse axes {axes} do not reflect the posterior covariance"


def test_mission_rviz_displays_the_relocalization_marker_topic():  # [REQ:AS-09]
    mod = _mod()
    rviz = open(_RVIZ, encoding="utf-8").read()
    assert mod.RELOC_MARKERS_TOPIC in rviz, "mission.rviz does not display the relocalization marker topic"
    # the topic is bound to a MarkerArray display (so RViz renders the reloc factors).
    idx = rviz.index(mod.RELOC_MARKERS_TOPIC)
    assert "rviz_default_plugins/MarkerArray" in rviz[max(0, idx - 400):idx]
