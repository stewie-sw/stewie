"""[REQ:IN-02] Enforced raw/derived/belief/world/mission layer-tier taxonomy.

Every LY-01 catalog entry carries a closed ``tier in {raw, derived, belief, world, mission}`` beside its
``source_class`` (source_class = where the data came from; tier = what it may be used for). The enforced
invariants (design/STEWIE_autodig_ingest_design_2026-07-08.md ss5.2/5.3):

  * a raw-tier layer may never be planning- or release-eligible (raw sensor streams are never planning-valid);
  * a belief-tier layer that IS planning/release eligible must carry declared uncertainty;
  * a tier is *promoted* only forward one rung along raw -> derived -> belief -> world, and only through an
    EG-08 ACCEPTED reconciliation proposal (a belief->world promotion without an accepted proposal is refused).

Grounded in the REAL committed catalog (stewie/server/layer_catalog.json) -- no synthetic catalog.
"""
import json
import os

import pytest
from fastapi.testclient import TestClient

from stewie.contracts.reconciliation import Proposal, ReconcileState
from stewie.server import layer_tier as LT
from stewie.server.server import app

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_CATALOG = os.path.join(_ROOT, "stewie", "server", "layer_catalog.json")


def _catalog_layers() -> list[dict]:
    with open(_CATALOG, encoding="utf-8") as fh:
        return json.load(fh)["layers"]


# --- 1. every catalog layer carries a valid, closed-set tier -----------------------------------------

def test_all_catalog_layers_carry_a_valid_tier():  # [REQ:IN-02]
    layers = _catalog_layers()
    assert len(layers) == 68
    for ly in layers:
        t = LT.layer_tier(ly)
        assert t in LT.TIERS, f"{ly['id']} -> {t!r} not in closed tier set {LT.TIERS}"
    # the closed set is exactly the five named tiers
    assert LT.TIERS == frozenset({"raw", "derived", "belief", "world", "mission"})


def test_committed_catalog_validates_clean():  # [REQ:IN-02]
    # the WHOLE committed catalog must satisfy the enforcement (no raw layer is planning/release eligible,
    # every planning-eligible belief layer carries uncertainty). Returns the id->tier map.
    tiers = LT.validate_catalog(_catalog_layers())
    assert len(tiers) == 68
    assert set(tiers.values()) <= LT.TIERS


def test_tier_anchors_match_the_design_mapping():  # [REQ:IN-02]
    by = {ly["id"]: ly for ly in _catalog_layers()}
    # design ss5.2: /world = approved terrain state (base.dem); /mission = plans + design intent + executed
    # changes; /belief = terrain-confidence / traversability / robot-pose estimates.
    assert LT.layer_tier(by["base.dem"]) == "world"
    assert LT.layer_tier(by["mission.waypoints"]) == "mission"
    assert LT.layer_tier(by["design.cut"]) == "mission"
    assert LT.layer_tier(by["map.changed_terrain"]) == "mission"      # an executed excavation change
    assert LT.layer_tier(by["hazard.rocks"]) == "belief"
    assert LT.layer_tier(by["robot.pose"]) == "belief"
    assert LT.layer_tier(by["physics.sinkage"]) == "belief"           # a terramechanics estimate w/ uncertainty
    assert LT.layer_tier(by["runtime.gazebo_truth"]) == "raw"         # an unprocessed sim-truth stream


# --- 2. a raw-tier layer marked planning-valid FAILS validation --------------------------------------

def test_raw_layer_marked_planning_eligible_fails_validation():  # [REQ:IN-02]
    raw_planning = {"id": "raw.stereo_left", "domain": "raw", "source_class": "live",
                    "planning_eligible": True, "release_execute_eligible": False}
    assert LT.layer_tier(raw_planning) == "raw"
    with pytest.raises(LT.LayerTierError):
        LT.validate_layer(raw_planning)


def test_raw_layer_marked_release_eligible_fails_validation():  # [REQ:IN-02]
    raw_release = {"id": "raw.imu", "domain": "raw", "source_class": "live",
                   "planning_eligible": False, "release_execute_eligible": True}
    with pytest.raises(LT.LayerTierError):
        LT.validate_layer(raw_release)


def test_raw_sensor_stream_not_planning_eligible_is_valid():  # [REQ:IN-02]
    raw_ok = {"id": "raw.imu", "domain": "raw", "source_class": "live",
              "planning_eligible": False, "release_execute_eligible": False}
    assert LT.validate_layer(raw_ok) == "raw"


def test_belief_planning_layer_must_carry_declared_uncertainty():  # [REQ:IN-02]
    # a belief-tier layer WITH declared uncertainty may be planning-eligible; the honesty helper must be
    # truthful about the empty-provenance case.
    ok = {"id": "map.mystery", "domain": "map", "source_class": "belief",
          "planning_eligible": True, "release_execute_eligible": False}
    assert LT.layer_tier(ok) == "belief"
    assert LT.carries_uncertainty(ok) is True   # 'belief' IS a declared-uncertainty provenance
    LT.validate_layer(ok)                        # belief WITH declared uncertainty planning-eligible is fine
    naked = {"id": "x", "domain": "map", "source_class": "",
             "planning_eligible": True, "release_execute_eligible": False}
    assert LT.carries_uncertainty(naked) is False


def test_carries_uncertainty_stays_consistent_with_gw03_confidence():  # [REQ:IN-02]
    # DRIFT GUARD: layer_tier mirrors the GW-03 provenance vocabulary rather than importing it (so CORE stays a
    # sink, EG-09). This asserts the mirror agrees with the real GW-03 classifier over the whole catalog:
    # a layer "carries declared uncertainty" iff its GW-03 confidence class is not 'unknown'.
    from stewie.server.routers.world import layer_confidence
    for ly in _catalog_layers():
        expected = layer_confidence(ly.get("source_class", "")).get("cls") != "unknown"
        assert LT.carries_uncertainty(ly) is expected, ly["id"]


# --- 3. promotion advances one rung, only through an EG-08 ACCEPTED proposal --------------------------

def _accepted() -> Proposal:
    return Proposal(proposal_id="p1", state=ReconcileState.ACCEPTED, confidence=0.9)


def _proposed() -> Proposal:
    return Proposal(proposal_id="p1", state=ReconcileState.PROPOSED, confidence=0.9)


def test_promotion_advances_one_rung_via_accepted_proposal():  # [REQ:IN-02]
    assert LT.promote_tier("raw", "derived", _accepted()) == "derived"
    assert LT.promote_tier("derived", "belief", _accepted()) == "belief"
    assert LT.promote_tier("belief", "world", _accepted()) == "world"


def test_belief_to_world_promotion_without_accepted_proposal_refused():  # [REQ:IN-02]
    with pytest.raises(LT.TierPromotionError):
        LT.promote_tier("belief", "world", None)
    with pytest.raises(LT.TierPromotionError):
        LT.promote_tier("belief", "world", _proposed())   # not yet ACCEPTED


def test_promotion_refuses_skips_downgrades_and_off_ladder():  # [REQ:IN-02]
    with pytest.raises(LT.TierPromotionError):
        LT.promote_tier("raw", "belief", _accepted())      # skips a rung
    with pytest.raises(LT.TierPromotionError):
        LT.promote_tier("world", "belief", _accepted())    # downgrade
    with pytest.raises(LT.TierPromotionError):
        LT.promote_tier("belief", "mission", _accepted())  # mission is not on the promotion ladder
    with pytest.raises(LT.TierPromotionError):
        LT.promote_tier("world", "world", _accepted())     # no advance


# --- 4. the served catalog surface annotates the tier beside source_class ----------------------------

def test_served_catalog_annotates_tier(monkeypatch):  # [REQ:IN-02]
    monkeypatch.setenv("STEWIE_DEV_OPEN", "1")
    c = TestClient(app, base_url="http://127.0.0.1")
    j = c.get("/world/layer-catalog").json()
    assert j["count"] == 68
    for ly in j["layers"]:
        assert ly.get("tier") in LT.TIERS, f"{ly['id']} served without a valid tier"
        # tier travels BESIDE source_class, never replaces it
        assert "source_class" in ly
