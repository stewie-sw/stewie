"""The /program board must serve the committed section-7 snapshot honestly: the page ships, the
snapshot round-trips with its provenance + a full bucket partition, and the payload is the byte-for-byte
committed artifact (no runtime reinterpretation the generator's tests didn't already vet)."""
from __future__ import annotations

import json
import os

from fastapi.testclient import TestClient

from stewie.server.routers.program import _SNAPSHOT
from stewie.server.server import app

client = TestClient(app)


def test_program_page_serves_the_board_html():
    r = client.get("/program")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert "program_board.js" in r.text          # the page boots the external module (CSP: no inline JS)
    assert "program-summary" in r.text           # the board mount points exist


def test_program_snapshot_is_the_committed_artifact():
    r = client.get("/program/snapshot")
    assert r.status_code == 200
    body = r.json()
    with open(_SNAPSHOT, encoding="utf-8") as fh:
        assert body == json.load(fh)
    assert os.path.exists(_SNAPSHOT)


def test_program_snapshot_shape_and_partition():
    body = client.get("/program/snapshot").json()
    s = body["summary"]
    assert s["total"] == len(body["rows"]) >= 180
    assert sum(s["buckets"].values()) == s["total"]
    assert body["workflow_spine"] == ["Plan", "Rehearse", "Validate", "Release", "Execute", "Report"]
    for key in ("prd_commit", "prd_sha256", "specs_sha256"):
        assert body["provenance"][key]
