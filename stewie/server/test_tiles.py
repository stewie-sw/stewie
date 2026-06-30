"""tiles router (3D Tiles reconstruction-twin serving): serves tileset.json + .pnts with correct
content-types from STEWIE_TILES_DIR, 404s missing files, and refuses path traversal. Direct-call (no
TestClient lifespan) so it is fast + deterministic."""
import os

from stewie.server.routers import tiles as T


def _mk(tmp_path):
    d = tmp_path / "twin"
    d.mkdir()
    (d / "tileset.json").write_text('{"asset":{"version":"1.0"}}')
    (d / "points.pnts").write_bytes(b"pnts\x01\x00\x00\x00")
    return os.path.realpath(str(tmp_path))


def test_serves_tileset_and_pnts_with_content_types(tmp_path, monkeypatch):
    monkeypatch.setattr(T, "_TILES_DIR", _mk(tmp_path))
    r = T.get_tile("twin", "tileset.json")
    assert getattr(r, "status_code", 200) == 200 and r.media_type == "application/json"
    r2 = T.get_tile("twin", "points.pnts")
    assert getattr(r2, "status_code", 200) == 200 and r2.media_type == "application/octet-stream"


def test_404_on_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(T, "_TILES_DIR", _mk(tmp_path))
    assert T.get_tile("twin", "nope.pnts").status_code == 404


def test_400_on_path_traversal(tmp_path, monkeypatch):
    monkeypatch.setattr(T, "_TILES_DIR", _mk(tmp_path))
    assert T.get_tile("twin", "../../../../etc/passwd").status_code == 400


def test_400_on_name_traversal_escaping_the_tiles_dir(tmp_path, monkeypatch):  # #302
    """name='..' previously moved the guard's containment dir UP a level (the guard recomputed its base
    from the attacker-controlled {name}), so a file one level ABOVE the tiles dir was served. The guard
    must pin to the FIXED _TILES_DIR. Faithful proof: a secret sits one level up from the tiles dir."""
    tiles = tmp_path / "colmap"; (tiles / "twin").mkdir(parents=True)
    (tiles / "twin" / "tileset.json").write_text("{}")
    (tmp_path / "secret.txt").write_text("TOPSECRET")              # one level UP from _TILES_DIR
    monkeypatch.setattr(T, "_TILES_DIR", os.path.realpath(str(tiles)))
    r = T.get_tile("..", "secret.txt")                             # would resolve to tmp_path/secret.txt
    assert getattr(r, "status_code", 200) == 400, "name='..' escaped the tiles dir (#302)"
    assert T.get_tile("twin", "tileset.json").status_code == 200   # the legit nested path still serves
