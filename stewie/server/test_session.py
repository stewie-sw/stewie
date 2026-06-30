"""B3: operator/director split sessions over the real closed-loop executive.

One server-side session = one run_closed_loop execution recorded leg-by-leg. The OPERATOR view is
telemetry-constrained (through stewie.bridge.telemetry) and truth-denylisted; the DIRECTOR view
(API-key gated) carries the full record + the seen-vs-actual debrief. Fast-forward never alters the
link accounting (B3.4).
"""
import importlib

import pytest
from fastapi.testclient import TestClient

TRUTH_DENY = {"true_J", "slip", "slope_deg", "true_energy_J"}


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_API_KEY", "director-key")
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    import stewie.server.server as srv
    importlib.reload(srv)
    yield TestClient(srv.app)
    # the reload baked the monkeypatched env (REPORTS under tmp_path, auth key) into the CACHED
    # module -- later tests then 404 on reports (caught 2026-06-10: a cross-file ordering leak).
    # Undo the env FIRST, then restore a clean module for whoever imports it next.
    monkeypatch.undo()
    importlib.reload(srv)


def _mission():
    return {"name": "b3 session", "body": "moon", "charger": [0, 0],
            "orders": [{"action": "cut", "kind": "cut", "x": 8, "y": 6, "footprint_m2": 16,
                        "depth_m": 0.05, "label": "pad"},
                       {"action": "fill", "kind": "fill", "x": 16, "y": 10, "footprint_m2": 12,
                        "depth_m": 0.2, "label": "berm"}],
            "profile": "mission_default"}


def test_session_start_runs_the_real_loop(client):
    r = client.post("/session/start", json=_mission(), headers={"X-API-Key": "director-key"})
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["ok"] and s["n_legs"] > 0 and "session_id" in s


def test_session_start_runs_the_registry_mutation_under_a_lock(client, monkeypatch):  # #295
    """Concurrent POST /session/start must not corrupt _SESSIONS: the evict+insert read-modify-write runs
    under _SESSIONS_LOCK, so one thread's _evict iteration cannot collide with another's insert ('dictionary
    changed size during iteration' -> 500). Deterministic guard: the lock is HELD while _evict runs."""
    from stewie.server import session as S
    held = []
    orig = S._evict

    def spy(now):
        held.append(S._SESSIONS_LOCK.locked())
        return orig(now)
    monkeypatch.setattr(S, "_evict", spy)
    r = client.post("/session/start", json=_mission(), headers={"X-API-Key": "director-key"})
    assert r.status_code == 200, r.text
    assert held and all(held), "session.start's registry RMW ran WITHOUT _SESSIONS_LOCK (#295)"


def test_operator_view_is_truth_denylisted_and_link_constrained(client):
    sid = client.post("/session/start", json=_mission(),
                      headers={"X-API-Key": "director-key"}).json()["session_id"]
    op = client.get(f"/session/{sid}/operator")            # operator URL is OPEN (B3 contract)
    assert op.status_code == 200
    doc = op.json()
    for leg in doc["legs"]:
        assert not (TRUTH_DENY & set(leg)), f"truth leaked to the operator: {TRUTH_DENY & set(leg)}"
    assert doc["link"]["profile"] == "mission_default"
    assert doc["link"]["stats"]["sent"] + doc["link"]["stats"]["dropped"] >= doc["n_legs_total"] - 1


def test_debrief_requires_director_key_and_shows_divergence(client):
    sid = client.post("/session/start", json=_mission(),
                      headers={"X-API-Key": "director-key"}).json()["session_id"]
    assert client.get(f"/session/{sid}/debrief").status_code == 401
    d = client.get(f"/session/{sid}/debrief", headers={"X-API-Key": "director-key"})
    assert d.status_code == 200
    doc = d.json()
    assert len(doc["legs"]) == doc["n_legs_total"]
    leg = doc["legs"][0]
    assert "true_J" in leg and "nominal_J" in leg          # both tracks present
    assert "energy_divergence_J" in doc and doc["energy_divergence_J"] >= 0.0


def test_fast_forward_does_not_touch_link_accounting(client):
    sid = client.post("/session/start", json=_mission(),
                      headers={"X-API-Key": "director-key"}).json()["session_id"]
    before = client.get(f"/session/{sid}/operator").json()["link"]["stats"]
    client.get(f"/session/{sid}/debrief", params={"fast_forward": 10},
               headers={"X-API-Key": "director-key"})
    after = client.get(f"/session/{sid}/operator").json()["link"]["stats"]
    assert before == after


def test_unknown_session_404(client):
    assert client.get("/session/nope/operator").status_code == 404


def test_mission_summary_artifact(client):
    sid = client.post("/session/start", json=_mission(),
                      headers={"X-API-Key": "director-key"}).json()["session_id"]
    r = client.get(f"/session/{sid}/summary", headers={"X-API-Key": "director-key"})
    assert r.status_code == 200
    md = r.text
    for token in ("# Mission summary", "legs", "energy", "link", "divergence"):
        assert token in md, f"summary missing {token!r}"
    # the artifact persists for the debrief record
    import stewie.specs.config as CFG, os
    files = os.listdir(os.path.join(CFG.data_dir(), "sessions"))
    assert any(sid in f for f in files)


def test_summary_covers_route_and_slip_from_a_real_haworth_run():
    """B4.2 (spec): the per-run summary covers route, energy, comm drops, SLIP EVENTS, and
    seen-vs-actual divergence. Grounded on the real Haworth DEM (no synthetic terrain): the slip
    and pose figures are the closed-loop physics outputs for each leg, not authored numbers."""
    import json
    import os

    from lode import mission_planner as MP

    scen = os.path.join(os.path.dirname(__file__), "scenarios", "shadowed_traverse.json")
    doc = json.load(open(scen))
    profile = doc.pop("profile", "ideal")
    doc.pop("teaching_point", None)
    doc.pop("provenance", None)
    mission = MP.mission_from_dict(doc)
    dem = MP.load_haworth_dem()
    origin = MP.flattest_anchor(dem)
    s = SESMOD.Session.run(mission, profile=profile, dem=dem, dem_origin=origin)

    md = SESMOD.summary_markdown(s)
    # all five spec sections present (route, energy, comm drops, slip events, divergence)
    for heading in ("## Route", "## Energy", "## Link", "## Slip events", "## Divergence"):
        assert heading in md, f"summary missing section {heading!r}"
    # route reports the real routed drive distance: the GoTo waypoint polylines from the plan IR
    # (this run detours around the keep-outs, so the path is longer than the crow flies)
    import math
    drive_m = 0.0
    for a in s.record["plan_ir"]["actions"]:
        wp = a.get("waypoints") or []
        drive_m += sum(math.dist(wp[i], wp[i + 1]) for i in range(len(wp) - 1))
    assert drive_m > 0.0
    assert f"{drive_m:.1f}" in md, "the summary must report the real routed drive distance"
    # slip section names the worst-slip leg with its real slip fraction (a closed-loop physics output)
    worst = max(s.record["legs"], key=lambda l_: l_["slip"])
    assert f"{worst['slip']:.3f}" in md, "the worst-slip leg's real slip fraction must appear"
    assert worst["leg"] in md
    # divergence figure is the same one the debrief reports (single source of truth)
    assert f"{s.debrief_view()['energy_divergence_J']:.1f}" in md


def test_t42_sessions_stamp_one_sun_state(client):
    """Navigation T4.2: a session carries mission_t0; operator AND director views stamp the SAME sun
    (az/el from the one solar authority at that time) -- camera frames, shadow layers, and the
    debrief all agree on lighting."""
    r = client.post("/session/start", json={**_mission(), "mission_t0_s": 600000},
                    headers={"X-API-Key": "director-key"})
    sid = r.json()["session_id"]
    op = client.get(f"/session/{sid}/operator").json()
    db = client.get(f"/session/{sid}/debrief", headers={"X-API-Key": "director-key"}).json()
    assert op["sun"] == db["sun"]                         # one sun state, both views
    assert op["sun"]["mission_t0_s"] == 600000
    from stewie.specs.solar import sun_az_el
    az, el = sun_az_el(-87.45, 600000.0)
    assert op["sun"]["az_deg"] == pytest.approx(az) and op["sun"]["el_deg"] == pytest.approx(el)


def test_operator_legs_carry_downlink_latency(client):
    """#67 [REQ:PO-03]: the operator sees telemetry at sent + downlink latency, never sooner."""
    r = client.post("/session/start", headers={"X-API-Key": "director-key"},
                    json={"name": "lat", "body": "moon", "charger": [0, 0], "profile": "mission_default",
                          "orders": [{"action": "a", "kind": "cut", "x": 10, "y": 0,
                                      "footprint_m2": 16, "depth_m": 0.05},
                                     {"action": "b", "kind": "fill", "x": 20, "y": 0,
                                      "footprint_m2": 16, "depth_m": 0.05}]})
    sid = r.json()["session_id"]
    op = client.get(f"/session/{sid}/operator").json()
    assert op["legs"], "the link should deliver at least one leg"
    for leg in op["legs"]:
        assert leg["visible_at_s"] >= leg["sent_at_s"] + 2.6 - 1e-9   # the 2600 ms downlink


def test_session_scorecard_a_board(client, monkeypatch):
    """#80: the trainer A-board -- autonomy-run KPIs from the session record. Operators see the
    public board; the divergence (truth) is director-only (separated for gating)."""
    K = {"X-API-Key": "director-key"}                      # the fixture's key
    monkeypatch.setenv("STEWIE_ALLOWED_OPERATORS", "aaron.w.storey80@gmail.com, trainee@gmail.com")
    monkeypatch.setenv("STEWIE_DIRECTORS", "aaron.w.storey80@gmail.com")
    r = client.post("/session/start", headers=K,
                    json={"name": "sc", "body": "moon", "charger": [0, 0], "profile": "comm_dropout",
                          "orders": [{"action": "a", "kind": "cut", "x": 12, "y": 0,
                                      "footprint_m2": 16, "depth_m": 0.05},
                                     {"action": "b", "kind": "fill", "x": 28, "y": 6,
                                      "footprint_m2": 16, "depth_m": 0.05}]})
    sid = r.json()["session_id"]
    # DIRECTOR (api-key) sees the full board incl. truth divergence
    dboard = client.get(f"/session/{sid}/scorecard", headers=K).json()["scorecard"]
    for k in ("completed", "objectives_total", "recharges", "replans", "legs_delivered",
              "legs_missed", "comm_delivered_frac", "energy_MJ"):
        assert k in dboard, f"missing scorecard KPI {k}"
    assert 0.0 <= dboard["comm_delivered_frac"] <= 1.0
    assert "energy_divergence_J" in dboard                 # director sees truth
    # OPERATOR (trainee token) sees only the public board -- truth is gated out
    tok = client.post("/auth/login", json={"email": "trainee@gmail.com"}, headers=K).json()["token"]
    oboard = client.get(f"/session/{sid}/scorecard",
                        headers={"Authorization": f"Bearer {tok}"}).json()["scorecard"]
    assert "comm_delivered_frac" in oboard and "energy_divergence_J" not in oboard


def test_scorecard_carries_makespan_vs_optimal_from_forward_compare(client):
    """TR-01: the A-board scores the run's makespan against the best alternative the planner can
    find (forward_compare over the same mission). makespan_s is the run's actual plant time; the
    optimal is the head of the ranked candidate futures; the ratio is run/optimal (>= 1.0 when the
    chosen plan is not the fastest). Grounded entirely on the real planner -- no authored numbers."""
    K = {"X-API-Key": "director-key"}
    sid = client.post("/session/start", json=_mission(), headers=K).json()["session_id"]
    board = client.get(f"/session/{sid}/scorecard", headers=K).json()["scorecard"]
    for k in ("makespan_s", "optimal_s", "makespan_ratio"):
        assert k in board, f"missing makespan KPI {k}"
    assert board["makespan_s"] > 0.0 and board["optimal_s"] > 0.0
    # the run can be no faster than the best alternative the planner found -> ratio >= 1 (-eps)
    assert board["makespan_ratio"] >= 1.0 - 1e-6
    # ratio is run/optimal (each field rounded for display -> compare within rounding tolerance)
    assert board["makespan_ratio"] == pytest.approx(board["makespan_s"] / board["optimal_s"], abs=1e-3)


def test_scorecard_record_persists_to_data_dir(client):
    """TR-01: requesting the scorecard persists a per-session JSON record under data_dir/sessions/
    that OUTLIVES the in-memory session (the durable trainer record). It carries the public board,
    the truth divergence, the makespan-vs-optimal block, and the session id."""
    import json
    import os

    import stewie.specs.config as CFG
    K = {"X-API-Key": "director-key"}
    sid = client.post("/session/start", json=_mission(), headers=K).json()["session_id"]
    client.get(f"/session/{sid}/scorecard", headers=K)
    path = os.path.join(CFG.data_dir(), "sessions", f"scorecard_{sid}.json")
    assert os.path.exists(path), "the scorecard record must persist to data_dir/sessions/"
    rec = json.load(open(path))
    assert rec["session_id"] == sid
    assert rec["public"]["legs_total"] >= 0 and "energy_MJ" in rec["public"]
    assert "energy_divergence_J" in rec["truth"]              # the durable record keeps truth
    assert rec["makespan"]["makespan_ratio"] >= 1.0 - 1e-6


def test_scorecard_record_survives_session_eviction():
    """TR-01: the durable record is read from disk, so a director can pull the scorecard for a
    session that has already been evicted from the live store (load_scorecard_record(sid))."""
    import os

    from lode import mission_planner as MP
    scen = os.path.join(os.path.dirname(__file__), "scenarios", "shadowed_traverse.json")
    import json
    doc = json.load(open(scen))
    profile = doc.pop("profile", "ideal")
    doc.pop("teaching_point", None)
    doc.pop("provenance", None)
    mission = MP.mission_from_dict(doc)
    dem = MP.load_haworth_dem()
    origin = MP.flattest_anchor(dem)
    s = SESMOD.Session.run(mission, profile=profile, dem=dem, dem_origin=origin,
                           objective="time")
    path = SESMOD.persist_scorecard(s)
    assert os.path.exists(path)
    loaded = SESMOD.load_scorecard_record(s.session_id)
    assert loaded is not None and loaded["session_id"] == s.session_id
    assert loaded["makespan"]["makespan_s"] > 0.0


def test_cockpit_metrics_pane_surfaces_the_scorecard():
    """TR-01: the A-board has a cockpit surface -- a #scorecard-board container in the Metrics pane
    (#execview) plus a renderScorecardBoard() that fetches /session/.../scorecard and shows the
    makespan-vs-optimal KPIs. (cockpit.js is string-tested like the other cockpit panes here.)"""
    import os
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    html = open(os.path.join(root, "stewie", "server", "index.html")).read()
    js = open(os.path.join(root, "stewie", "server", "web", "assets", "cockpit.js")).read()
    # the Metrics pane (#execview) carries the scorecard surface
    ev = html[html.index('id="execview"'):]
    assert 'id="scorecard-board"' in ev, "no #scorecard-board in the Metrics pane (#execview)"
    assert 'id="sc-chips"' in ev, "no #sc-chips slot for the KPI chips"
    # the cockpit wires it: a renderer that reads /session/.../scorecard + shows makespan-vs-optimal
    assert "renderScorecardBoard" in js, "cockpit does not render the scorecard board"
    assert "/scorecard" in js and "makespan_ratio" in js, "the board does not surface makespan-vs-optimal"


def test_pose_divergence_is_believed_vs_true_and_director_gated_in_scorecard(client, monkeypatch):
    """TR-02: the scorecard truth block carries the believed-vs-true POSE divergence (mean/max), built
    from each leg's believed (bx,by) vs true (tx,ty) pose. It is director-only (MO-04 magenta) -- an
    operator never sees it."""
    monkeypatch.setenv("STEWIE_ALLOWED_OPERATORS", "aaron.w.storey80@gmail.com, trainee@gmail.com")
    monkeypatch.setenv("STEWIE_DIRECTORS", "aaron.w.storey80@gmail.com")
    K = {"X-API-Key": "director-key"}
    sid = client.post("/session/start", json=_mission(), headers=K).json()["session_id"]
    dboard = client.get(f"/session/{sid}/scorecard", headers=K).json()["scorecard"]
    assert "pose_divergence_mean_m" in dboard and "pose_divergence_max_m" in dboard
    assert dboard["pose_divergence_mean_m"] >= 0.0 and dboard["pose_divergence_max_m"] >= dboard["pose_divergence_mean_m"]
    # operator (trainee token) is gated out of the truth pose divergence
    tok = client.post("/auth/login", json={"email": "trainee@gmail.com"}, headers=K).json()["token"]
    oboard = client.get(f"/session/{sid}/scorecard",
                        headers={"Authorization": f"Bearer {tok}"}).json()["scorecard"]
    assert "pose_divergence_mean_m" not in oboard


def test_divergence_route_is_director_only_and_returns_per_leg_pose(client):
    """TR-02: GET /session/{sid}/divergence is director-gated and returns the per-leg believed-vs-true
    pose track + the mean/max aggregate (the truth board's data)."""
    K = {"X-API-Key": "director-key"}
    sid = client.post("/session/start", json=_mission(), headers=K).json()["session_id"]
    assert client.get(f"/session/{sid}/divergence").status_code == 401   # operator-open? no -> director only
    d = client.get(f"/session/{sid}/divergence", headers=K)
    assert d.status_code == 200, d.text
    div = d.json()["divergence"]
    assert "per_leg" in div and "mean_m" in div and "max_m" in div
    for leg in div["per_leg"]:
        for k in ("leg", "err_m", "bx", "by", "tx", "ty"):
            assert k in leg, f"divergence leg missing {k}"
        assert leg["err_m"] >= 0.0


def test_trainer_history_lists_real_recorded_sessions_and_gates_truth(client, monkeypatch):
    """TR-03 (PROGRAM board): /trainer/history lists every persisted scorecard record (real recorded
    sessions). Operators see the public board + makespan; only directors see the per-session truth
    block. Honest empty list before any session is recorded."""
    monkeypatch.setenv("STEWIE_ALLOWED_OPERATORS", "aaron.w.storey80@gmail.com, trainee@gmail.com")
    monkeypatch.setenv("STEWIE_DIRECTORS", "aaron.w.storey80@gmail.com")
    K = {"X-API-Key": "director-key"}
    # empty state before any scorecard is persisted
    h0 = client.get("/trainer/history", headers=K).json()
    assert h0["ok"] and h0["count"] == 0 and h0["sessions"] == []
    # record two real sessions (requesting the scorecard persists the durable record)
    sids = []
    for _ in range(2):
        sid = client.post("/session/start", json=_mission(), headers=K).json()["session_id"]
        client.get(f"/session/{sid}/scorecard", headers=K)
        sids.append(sid)
    h = client.get("/trainer/history", headers=K).json()
    assert h["count"] == 2 and h["is_director"] is True
    listed = {row["session_id"] for row in h["sessions"]}
    assert set(sids) <= listed
    row = h["sessions"][0]
    assert "makespan_ratio" in row["makespan"] and "energy_MJ" in row["public"]
    assert "truth" in row and "pose_divergence_mean_m" in row["truth"]   # director sees truth
    # operator (trainee) sees the history but NOT the truth block
    tok = client.post("/auth/login", json={"email": "trainee@gmail.com"}, headers=K).json()["token"]
    ho = client.get("/trainer/history", headers={"Authorization": f"Bearer {tok}"}).json()
    assert ho["count"] == 2 and ho["is_director"] is False
    assert all("truth" not in row for row in ho["sessions"])


def test_trainer_history_requires_auth(client):
    """TR-03: the program board is not open -- an unauthenticated caller is rejected (auth configured)."""
    assert client.get("/trainer/history").status_code == 401


def test_cockpit_trainer_pane_surfaces_the_three_boards():
    """TR-02/03/04: the Trainer dashboard has a cockpit surface -- a #pane_trainer with the PROGRAM
    (#trainerprogram), DIRECTOR truth (#trainertruth, hidden for non-directors), and DEBRIEF scrubber
    (#trainerdebrief) sections, a director-gated Trainer vtab (data-minrole=operator), the pure
    trainer_boards.js module loaded + stamped, and the cockpit wiring (loadTrainer + the three board
    builders + the real routes)."""
    import os
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    html = open(os.path.join(root, "stewie", "server", "index.html")).read()
    js = open(os.path.join(root, "stewie", "server", "web", "assets", "cockpit.js")).read()
    tb = open(os.path.join(root, "stewie", "server", "web", "assets", "trainer_boards.js")).read()
    # the Trainer tab is gated to operator+ (the truth board is further director-gated server-side)
    assert 'id="vtab-trainer"' in html and 'data-view="trainer"' in html
    assert 'data-minrole="operator"' in html[html.index('id="vtab-trainer"'):html.index('id="vtab-trainer"') + 300]
    # the pane carries the three boards
    pane = html[html.index('id="pane_trainer"'):]
    for slot in ('id="trainerprogram"', 'id="trainertruth"', 'id="trainerdebrief"',
                 'id="trainerdebriefsel"', 'id="trainerstep"'):
        assert slot in pane, f"no {slot} in the Trainer pane (#pane_trainer)"
    # the pure module is loaded (CSP-safe external asset) + stamped (content-hash ?v=, not the 0-stub)
    assert "trainer_boards.js?v=" in html
    assert "trainer_boards.js?v=0000000000000" not in html, "trainer_boards.js was not stamped"
    # the cockpit wires the boards from the REAL routes
    assert "loadTrainer" in js and "/trainer/history" in js and "/debrief" in js
    # the pure module exposes the three builders + the MO-04 truth color
    for fn in ("programBoardHTML", "truthBoardHTML", "debriefScrubberHTML"):
        assert fn in tb, f"trainer_boards.js missing {fn}"


import stewie.server.session as SESMOD  # noqa: E402  (mechanism tests on the module-global store)


def _mk_session(sid):
    """A minimal real Session (structural fixture: _evict/get read only id + the created stamp)."""
    import os as _os

    from stewie.bridge import telemetry as _tl
    prof = _tl.load_profile(_os.path.join(SESMOD._PROFILES, "ideal.json"))
    return SESMOD.Session(session_id=sid, profile_name="ideal",
                          record={"legs": [], "completed": True, "recharges": 0, "replans": 0},
                          link=_tl.TelemetryLink(prof, seed=0))


def test_m09_expired_session_is_evicted(monkeypatch):
    """Audit M-09: a session older than the TTL is dropped on the next eviction pass; get() -> None."""
    clock = {"t": 1000.0}
    monkeypatch.setattr(SESMOD, "_now", lambda: clock["t"])
    monkeypatch.setattr(SESMOD, "_SESSIONS", {})
    old = _mk_session("oldsid")
    old.created_monotonic_s = clock["t"]
    SESMOD._SESSIONS["oldsid"] = old
    assert SESMOD.get("oldsid") is old                       # present while fresh
    clock["t"] = 1000.0 + SESMOD._SESSION_TTL_S + 1.0        # advance past the TTL
    SESMOD._evict(clock["t"])
    assert SESMOD.get("oldsid") is None                      # expired -> evicted -> 404 path


def test_m09_active_session_survives_and_cap_holds(monkeypatch):
    """Audit M-09: the store is capped oldest-first while an in-TTL active session is never evicted."""
    clock = {"t": 0.0}
    monkeypatch.setattr(SESMOD, "_now", lambda: clock["t"])
    monkeypatch.setattr(SESMOD, "_SESSIONS", {})
    monkeypatch.setattr(SESMOD, "_SESSION_MAX", 4)           # small cap for the test
    for i in range(SESMOD._SESSION_MAX + 3):                 # insert CAP+3, each 1 s apart, all in TTL
        clock["t"] = float(i)
        s = _mk_session(f"s{i}")
        SESMOD._evict(clock["t"])
        s.created_monotonic_s = clock["t"]
        SESMOD._SESSIONS[s.session_id] = s
        if len(SESMOD._SESSIONS) > SESMOD._SESSION_MAX:
            SESMOD._evict(clock["t"])
    assert len(SESMOD._SESSIONS) <= SESMOD._SESSION_MAX
    assert SESMOD.get(f"s{SESMOD._SESSION_MAX + 2}") is not None   # newest (active) survived
    assert SESMOD.get("s0") is None                               # oldest dropped first
