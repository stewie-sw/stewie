"""CT-04 [REQ:CT-04] (PRD 7.2): scene publication writes verified rasters ATOMICALLY and emits
metadata.json LAST as the commit marker.

A focused acceptance test on the real ``stewie.twin.io_fields`` seam against the real committed
``samples/flat_compact`` scene (no fabricated fields). The byte-exact round-trip characterization
lives in ``test_io_fields.py``; this is the dedicated CT-04 commit-marker + atomicity citation, kept
in its own file so the traceability citation commits independently of in-flight edits to
``test_io_fields.py``.
"""
from __future__ import annotations

import json
import os

import pytest

from stewie.twin.io_fields import load_scene, save_scene

_SCENE = os.path.join(os.path.dirname(__file__), os.pardir, os.pardir, "samples", "flat_compact")


def _real_scene():
    if not (os.path.isdir(_SCENE) and os.path.exists(os.path.join(_SCENE, "metadata.json"))):
        pytest.skip(f"real sample scene absent: {_SCENE}")
    return load_scene(_SCENE)


def test_ct04_metadata_is_the_atomic_commit_marker(tmp_path):  # [REQ:CT-04]
    """Publishing the real scene leaves NO .tmp siblings (each raster os.replace'd into place),
    writes metadata.json as the commit marker that parses back to the published metadata, and the
    marker is load-gating: with rasters present but the marker removed (a crash mid-publish), the
    scene does not load a half-written snapshot."""
    fields, meta = _real_scene()
    out = str(tmp_path / "publish")
    save_scene(out, fields, meta)
    # atomic publication: nothing half-written left behind
    assert [f for f in os.listdir(out) if f.endswith(".tmp")] == []
    # metadata.json is the commit marker and round-trips to the published metadata
    mpath = os.path.join(out, "metadata.json")
    assert os.path.exists(mpath)
    with open(mpath) as fh:
        assert json.load(fh) == meta
    # commit-marker semantics: rasters present but marker gone -> the scene is treated as incomplete
    os.remove(mpath)
    assert os.path.exists(os.path.join(out, "heightmap.rf32"))
    with pytest.raises(FileNotFoundError):
        load_scene(out)
