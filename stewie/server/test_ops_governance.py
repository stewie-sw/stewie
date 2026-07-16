"""[REQ:PO-15] Operations governance beyond account admin (frontend-100 audit finding 7).

The backup / retention / replication maintenance ops were MANUAL director endpoints with no declared
recovery policy and no monitored signal that the backups are actually current. This proves the two
backend pieces that finding named: a DECLARED retention/RPO policy, and a MONITORED last-success/age
signal read from the REAL backup artifacts on disk, bundled with the ops-action audit trail behind a
director-only review route (the ops sibling of the account-admin /events surface).

Snapshots here are REAL artifacts written by ``stewie.twin.backup.snapshot`` over a tiny TwinStore
fixture (a 4x4 ramp elevation grid); the timing/presence logic under test is content-agnostic. No
value is fabricated -- ages are set with ``os.utime`` and read back off the real files.
"""
import importlib
import inspect
import os

import numpy as np
import pytest
from fastapi.testclient import TestClient

from stewie.twin import backup as BK
from stewie.twin.versioned import TwinStore


def _tiny_store() -> TwinStore:
    # a real (tiny) elevation grid -- a monotone ramp, not random noise; the backup-timing logic does
    # not read the values, only the file mtimes the snapshot writes.
    base = np.arange(16, dtype=np.float64).reshape(4, 4)
    return TwinStore(base, cell_m=1.0)


def _write_snapshot(data_dir: str) -> str:
    return BK.snapshot(_tiny_store(), os.path.join(data_dir, "snapshots"))


# ---- (1) the DECLARED retention / RPO policy -----------------------------------------------------
def test_po15_policy_is_declared_with_positive_rpo(monkeypatch, tmp_path):
    """[REQ:PO-15] The retention/RPO policy exists as typed data with positive recovery objectives and a
    retention ladder that mirrors the enforced backup.apply_retention defaults (no drift)."""
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("STEWIE_SNAPSHOT_RPO_S", raising=False)
    monkeypatch.delenv("STEWIE_REPLICA_RPO_S", raising=False)
    from stewie.server import ops_governance as OG
    importlib.reload(OG)
    p = OG.default_policy()
    assert p.snapshot_rpo_s > 0 and p.replica_rpo_s > 0
    # the declared ladder must equal what apply_retention ACTUALLY enforces, or the policy lies.
    sig = inspect.signature(BK.apply_retention)
    assert p.keep_recent == sig.parameters["keep_recent"].default
    assert p.ladder == sig.parameters["ladder"].default


def test_po15_policy_rpo_is_env_overridable(monkeypatch, tmp_path):
    """[REQ:PO-15] A deployment can tighten the RPO via env (the scheduled job's cadence is a deployment
    choice), so the monitored signal is checked against the operator's real objective."""
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("STEWIE_SNAPSHOT_RPO_S", "1800")
    monkeypatch.setenv("STEWIE_REPLICA_RPO_S", "900")
    from stewie.server import ops_governance as OG
    importlib.reload(OG)
    p = OG.default_policy()
    assert p.snapshot_rpo_s == 1800.0 and p.replica_rpo_s == 900.0


# ---- (2) the MONITORED last-success / age signal (from the REAL artifacts) ------------------------
def test_po15_fresh_snapshot_is_within_rpo(monkeypatch, tmp_path):
    """[REQ:PO-15] A snapshot that just landed reports present + within_rpo with a small age, read from
    the real file's mtime."""
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("STEWIE_SNAPSHOT_RPO_S", "3600")
    from stewie.server import ops_governance as OG
    importlib.reload(OG)
    _write_snapshot(str(tmp_path))
    st = OG.backup_status()
    snap = st["jobs"]["snapshot"]
    assert snap["present"] is True
    assert snap["within_rpo"] is True
    assert snap["last_success_ts"] is not None and 0 <= snap["age_s"] < 3600


def test_po15_stale_snapshot_trips_degraded(monkeypatch, tmp_path):
    """[REQ:PO-15] THE monitor: a snapshot older than the RPO reports within_rpo False and the overall
    status goes degraded -- the 'is the scheduled backup keeping us inside the RPO?' signal."""
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("STEWIE_SNAPSHOT_RPO_S", "3600")
    monkeypatch.setenv("STEWIE_REPLICA_RPO_S", "3600")
    from stewie.server import ops_governance as OG
    importlib.reload(OG)
    path = _write_snapshot(str(tmp_path))
    # age the real snapshot artifact well past the RPO (2 hours old vs a 1 hour RPO)
    old = os.path.getmtime(path) - 7200
    os.utime(path, (old, old))
    st = OG.backup_status(now_s=os.path.getmtime(path) + 7200)
    snap = st["jobs"]["snapshot"]
    assert snap["present"] is True
    assert snap["within_rpo"] is False
    assert snap["age_s"] >= 7200
    assert st["degraded"] is True


def test_po15_absent_backups_are_degraded(monkeypatch, tmp_path):
    """[REQ:PO-15] No backups at all -> not present, degraded (a fresh install with no backup taken is a
    visible governance gap, not a silent green)."""
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    from stewie.server import ops_governance as OG
    importlib.reload(OG)
    st = OG.backup_status()
    assert st["jobs"]["snapshot"]["present"] is False
    assert st["jobs"]["replica"]["present"] is False
    assert st["degraded"] is True


def test_po15_replica_success_is_monitored(monkeypatch, tmp_path):
    """[REQ:PO-15] The off-host replica job's freshness is monitored from the real replica artifacts
    (STEWIE_BACKUP_DIR), so a stalled replication (RPO breach) is visible."""
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("STEWIE_BACKUP_DIR", str(tmp_path / "replica"))
    monkeypatch.setenv("STEWIE_REPLICA_RPO_S", "3600")
    from stewie.server import ops_governance as OG
    importlib.reload(OG)
    _write_snapshot(str(tmp_path))
    out = BK.replicate(str(tmp_path), str(tmp_path / "replica"))
    assert out["ok"]
    st = OG.backup_status()
    rep = st["jobs"]["replica"]
    assert rep["present"] is True and rep["within_rpo"] is True


# ---- (3) the ops-action audit trail (beyond account admin) ---------------------------------------
def test_po15_recent_ops_excludes_account_admin(monkeypatch, tmp_path):
    """[REQ:PO-15] The ops-governance audit trail surfaces the maintenance actions (twin/backup/gates)
    and EXCLUDES account-admin actions (operator create/delete) -- governance BEYOND account admin."""
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    from stewie.server import services as SVC
    from stewie.server import ops_governance as OG
    importlib.reload(OG)
    SVC.log_event("dir@x", "admin.twin.snapshot", "twin_v000001.npz")
    SVC.log_event("dir@x", "admin.operator.delete", "bob@x")     # account admin -> must NOT appear
    SVC.log_event("dir@x", "admin.backup.replicate", "/replica")
    actions = [e["action"] for e in OG.recent_ops_events(50)]
    assert "admin.twin.snapshot" in actions
    assert "admin.backup.replicate" in actions
    assert "admin.operator.delete" not in actions


# ---- (4) the director-only review route ----------------------------------------------------------
@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_API_KEY", "test-key")
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("STEWIE_BACKUP_DIR", str(tmp_path / "replica"))
    monkeypatch.setenv("STEWIE_SNAPSHOT_RPO_S", "3600")
    import stewie.server.server as srv
    importlib.reload(srv)
    yield TestClient(srv.app)
    monkeypatch.undo()
    importlib.reload(srv)


_H = {"X-API-Key": "test-key"}


def test_po15_governance_route_bundles_policy_status_and_audit(client):
    """[REQ:PO-15] GET /admin/ops/governance returns the declared policy + the monitored per-job
    last-success/age signal + the recent ops-action audit trail, after a real snapshot."""
    assert client.post("/admin/twin/snapshot", headers=_H).status_code == 200
    r = client.get("/admin/ops/governance", headers=_H)
    assert r.status_code == 200
    d = r.json()
    assert d["ok"] is True
    assert d["policy"]["snapshot_rpo_s"] == 3600.0
    assert d["jobs"]["snapshot"]["present"] is True
    assert "within_rpo" in d["jobs"]["snapshot"]
    assert isinstance(d["recent_ops"], list)
    # the snapshot we just took is in the ops audit trail
    assert any(e["action"] == "admin.twin.snapshot" for e in d["recent_ops"])


def test_po15_governance_route_is_director_gated(client):
    """[REQ:PO-15] The ops-governance review carries operator/mission mutation history -> director-only."""
    assert client.get("/admin/ops/governance").status_code == 401
