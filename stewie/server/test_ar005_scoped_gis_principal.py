"""[REQ:AR-005] The public GIS proxy no longer confers DIRECTOR authority through a shared key. An anonymous
/ide user is a scoped GUEST planner principal (identity "gis-anon", role "guest": plan/read only, its own
audit actor + quota), asserted by nginx via a DISTINCT scoped key (X-Stewie-Anon-Key) -- never the
director-equivalent X-API-Key. These gates prove no anonymous director identity, and that the scoped
principal reaches the read/plan routes but NOT the operator/director routes the director-key injection used
to hand it. Real endpoints; the credentials are injected as headers exactly as the deployed nginx does."""
from fastapi.testclient import TestClient

from stewie.server import auth as AUTH
from stewie.server.server import app

_DIRECTOR_KEY = "director-secret-key-ar005"
_ANON_KEY = "gis-anon-scoped-key-ar005"


def _client(monkeypatch) -> TestClient:
    monkeypatch.setenv("STEWIE_API_KEY", _DIRECTOR_KEY)
    monkeypatch.setenv("STEWIE_GIS_ANON_KEY", _ANON_KEY)
    return TestClient(app, base_url="http://127.0.0.1")


def test_ar005_scoped_principal_resolves_to_guest_never_director():  # [REQ:AR-005]
    """The core acceptance: the anonymous GIS principal is GUEST, never director."""
    assert AUTH.role_of("gis-anon") == "guest"
    assert AUTH.role_of("gis-anon") != "director"
    # a director-equivalent identity is unchanged (regression guard)
    assert AUTH.role_of("api-key") == "director"


def test_ar005_scoped_key_reaches_read_plan_but_not_operator_or_director(monkeypatch):  # [REQ:AR-005]
    c = _client(monkeypatch)
    anon = {"X-Stewie-Anon-Key": _ANON_KEY}
    director = {"X-API-Key": _DIRECTOR_KEY}
    # the scoped planner reaches a public read route (require_auth) ...
    assert c.get("/dem/site_meta?site=haworth", headers=anon).status_code == 200
    # ... but is REFUSED the operator route (/construction) and the director route (/resync/compare) that the
    # director-key injection used to expose to anonymous users.
    assert c.get("/construction", headers=anon).status_code == 403
    assert c.post("/resync/compare", json={}, headers=anon).status_code == 403
    # the real director key still reaches the operator route (unchanged behaviour)
    assert c.get("/construction", headers=director).status_code == 200


def test_ar005_anon_key_is_not_the_director_key(monkeypatch):  # [REQ:AR-005]
    """Presenting the scoped anon key as X-API-Key does NOT authenticate as the director automation identity
    -- the two credentials are distinct and non-interchangeable."""
    c = _client(monkeypatch)
    r = c.get("/construction", headers={"X-API-Key": _ANON_KEY})   # anon key in the director slot
    assert r.status_code in (401, 403)                             # never authorized as director


def test_ar005_no_anon_key_configured_fails_closed(monkeypatch):  # [REQ:AR-005]
    """With no STEWIE_GIS_ANON_KEY configured, the anon-principal header grants nothing (the public routes
    stay auth-required)."""
    monkeypatch.setenv("STEWIE_API_KEY", _DIRECTOR_KEY)
    monkeypatch.delenv("STEWIE_GIS_ANON_KEY", raising=False)
    c = TestClient(app, base_url="http://127.0.0.1")
    r = c.get("/dem/site_meta?site=haworth", headers={"X-Stewie-Anon-Key": "anything"})
    assert r.status_code == 401
