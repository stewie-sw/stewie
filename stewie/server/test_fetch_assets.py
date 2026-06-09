"""Item 4 (fetch): the DEM is fetched + checksum-verified, never bundled/fabricated. file:// mirror
exercises the full download->verify->place path with no network."""
import os

import pytest

from stewie.server import fetch_assets as FA

_REAL = FA.dem_dest_dir()                         # the repo's committed real DEM dir
_NAMES = {a["name"] for a in FA.load_manifest()["assets"]}


def test_manifest_matches_committed_dem():
    assert FA.is_present()                        # committed DEM matches the manifest checksums (real bytes)


def test_is_present_false_for_empty_root(tmp_path):
    assert FA.is_present(repo_root=str(tmp_path)) is False


@pytest.mark.skipif(not os.path.isdir(_REAL), reason="real DEM dir absent")
def test_fetch_from_file_mirror_verifies_and_places(tmp_path):
    src = "file://" + os.path.abspath(_REAL)       # mirror = the real DEM dir
    got = FA.fetch(src, repo_root=str(tmp_path))
    assert set(got) == _NAMES and FA.is_present(repo_root=str(tmp_path))
    assert FA.fetch(src, repo_root=str(tmp_path)) == []      # idempotent: nothing re-downloaded


def test_fetch_rejects_checksum_mismatch(tmp_path):
    mirror = tmp_path / "mirror"; mirror.mkdir()
    for a in FA.load_manifest()["assets"]:
        (mirror / a["name"]).write_bytes(b"not the real DEM")   # corrupt mirror
    with pytest.raises(ValueError, match="checksum mismatch"):
        FA.fetch("file://" + str(mirror), repo_root=str(tmp_path / "dest"))
