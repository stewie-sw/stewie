"""[REQ:EV-01] The EVIDENCE/REPORT BUNDLE reproduces -- from the EXISTING persisted sources -- a mission's
plan inputs + selected layers + runtime profile + world transactions + audit trail, and shows the
host-gated ROS/Gazebo/RViz/Godot run captures HONESTLY as 'not captured' (never fabricated). A single
bundle_sha attests the assembly. Driven by a REAL director SIM run (populates the world log + EG-07 audit +
report artifacts); the bundle is then read from the PUBLIC GET /evidence/bundle."""
from fastapi.testclient import TestClient

_ORDERS = [{"kind": "cut", "x": 10.0, "y": 10.0, "action": "dig pad", "footprint_m2": 4.0, "depth_m": 0.3}]


def _client(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("STEWIE_API_KEY", raising=False)
    monkeypatch.setenv("STEWIE_DEV_OPEN", "1")                    # dev-open -> director-authed (drives the SIM run)
    import stewie.server.server as SRV
    return TestClient(SRV.app)


def _seed_sim_run(c):
    r = c.post("/executive/run", json={"orders": _ORDERS, "site": "haworth"})
    assert r.status_code == 200, r.text
    return r.json()


def test_ev01_bundle_reproduces_all_persisted_axes(monkeypatch, tmp_path):  # [REQ:EV-01]
    c = _client(monkeypatch, tmp_path)
    _seed_sim_run(c)                                             # REAL run: world log + audit + report on disk

    b = c.get("/evidence/bundle?site=haworth")
    assert b.status_code == 200, b.text
    j = b.json()
    assert j["ok"] is True and j["site"] == "haworth"

    # 1. plan inputs -- the SIM run committed a record_plan transaction (carries plan_id + mission).
    pi = j["plan_inputs"]
    assert pi["n_plans"] >= 1, "the SIM run's released plan was not reproduced from the world log"
    assert all(t.get("plan_id") for t in pi["plan_transactions"])
    assert pi["n_reports"] >= 1, "the persisted mission-control report artifact was not surfaced"
    assert all(rp["pdf"].startswith("/reports/") for rp in pi["reports"])

    # 2. selected layers -- LY-01 planning-eligible layers (each with GW-03 confidence) + DT-05 freshness.
    sl = j["selected_layers"]
    assert sl["n_planning_layers"] > 0 and sl["catalog_count"] > 0
    assert all("confidence" in ly and ly["confidence"].get("cls") for ly in sl["planning_layers"])
    assert sl["freshness"] is not None
    assert sl["freshness"]["provenance_class"] in ("observed", "prior")
    assert sl["freshness"]["dem_source"]                         # a real dart.dem_sources bundle id

    # 3. runtime profile (RT-01) -- the SIM authority profile + the 7-profile escalation registry.
    rp = j["runtime_profile"]
    assert rp["active_profile_id"] == "desktop_sil"
    assert rp["active_profile"]["evidence_class"] == "forecast"
    assert rp["active_profile"]["can_execute"] is False          # the SIM path holds no live command authority
    assert len(rp["registry"]) == 7 and rp["count"] == 7

    # 4. world transactions (DT-03) -- the linked timeline that proves what ran, chain intact.
    wt = j["world_transactions"]
    assert wt["count"] >= 1 and wt["verified"] is True
    assert wt["returned"] >= 1 and wt["transactions"]

    # 5. audit trail (EG-07) -- the tamper-evident executive chain carrying the SIM run.
    au = j["audit"]["executive"]
    assert au["verified"] is True and au["count"] >= 1
    assert any(r["action"] == "executive.run" for r in au["records"])

    # single evidence artifact: a deterministic content hash over the whole assembly.
    assert isinstance(j["bundle_sha"], str) and len(j["bundle_sha"]) == 64
    assert c.get("/evidence/bundle?site=haworth").json()["bundle_sha"] == j["bundle_sha"]  # same state -> same sha
    assert j["reproduced"] == ["plan_inputs", "selected_layers", "runtime_profile",
                               "world_transactions", "audit"]


def test_ev01_host_gated_captures_shown_not_fabricated(monkeypatch, tmp_path):  # [REQ:EV-01]
    c = _client(monkeypatch, tmp_path)
    _seed_sim_run(c)
    j = c.get("/evidence/bundle?site=haworth").json()

    art = j["artifacts"]
    # the committed-config ROS/Gazebo/RViz evidence is REAL + surfaced (FS-27 contract).
    assert "lifecycle_nodes" in art["ros_gazebo_rviz"] and "gazebo_worlds" in art["ros_gazebo_rviz"]
    # every live run CAPTURE (bag/recording/rviz/godot) is host-gated -> captured:false WITH a reason, never faked.
    kinds = {cap["kind"] for cap in art["captures"]}
    assert kinds == {"ros_bag", "gazebo_recording", "rviz_capture", "godot_frames"}
    for cap in art["captures"]:
        assert cap["captured"] is False, f"{cap['kind']} must not be fabricated"
        assert cap.get("reason") and "host-gated" in cap["reason"]
        assert "paths" not in cap                                # no fabricated artifact paths
    assert j["host_gated"] == ["ros_bag", "gazebo_recording", "rviz_capture", "godot_frames"]


def test_ev01_mission_filter_and_edit_session_audit(monkeypatch, tmp_path):  # [REQ:EV-01]
    c = _client(monkeypatch, tmp_path)
    _seed_sim_run(c)

    # a bogus edit-session id is reported honestly as not-found (never faked).
    jb = c.get("/evidence/bundle?site=haworth&session=nope-not-a-session").json()
    assert jb["audit"]["edit_session"]["found"] is False

    # a REAL edit session's GW-08 audit tail attaches when its id is passed.
    sid = c.post("/edit/session").json()["session"]
    kr = c.post(f"/edit/session/{sid}/keepout",
                json={"kind": "polygon", "ring": [[0, 0], [0, 5], [5, 5], [5, 0]]})
    assert kr.status_code == 200, kr.text
    js = c.get(f"/evidence/bundle?site=haworth&session={sid}").json()
    es = js["audit"]["edit_session"]
    assert es["found"] is True and es["session"] == sid
    assert es["version"] >= 1 and es["audit"]                    # the versioned create/modify audit tail

    # the mission filter narrows the plan/world/audit records to one mission id.
    jm = c.get("/evidence/bundle?site=haworth&mission=cockpit-run").json()
    for t in jm["world_transactions"]["transactions"]:
        assert (t.get("mission") or "") == "cockpit-run"
    for r in jm["audit"]["executive"]["records"]:
        assert "cockpit-run" in str(r.get("location", ""))
