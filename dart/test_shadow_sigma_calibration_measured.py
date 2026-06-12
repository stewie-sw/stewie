"""The dated shadow-sigma artifacts must REGENERATE byte-identically from their committed
generator (never hand-edited; the nb06 / G9 gate-replay discipline)."""
import glob
import json
import os

import pytest

from dart.shadow_sigma_calibration_measured import (
    build_envelope_artifact,
    build_measured_artifact,
    haworth_window,
    render_xcheck_paths,
)

_VALIDATION = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "stewie", "eval", "validation")
_CE3_DIR = os.environ.get("STEWIE_CE3_DIR", "/mnt/projects/datasets/lunar_ce3/yolo/images")
CE3 = sorted(glob.glob(os.path.join(_CE3_DIR, "**", "*.png"), recursive=True))
_DATE = "2026-06-11"


def _serialized(art: dict) -> str:
    return json.dumps(art, indent=1, sort_keys=True) + "\n"


def _committed(name: str) -> str:
    with open(os.path.join(_VALIDATION, name)) as f:
        return f.read()


def test_envelope_artifact_regenerates_byte_identically():
    art = build_envelope_artifact(haworth_window(), date=_DATE)
    assert _serialized(art) == _committed(f"shadow_sigma_calibration_{_DATE}.json")


@pytest.mark.skipif(len(CE3) < 5, reason="CE-3 imagery not present")
@pytest.mark.skipif(len(render_xcheck_paths()) < 3, reason="Godot renders not present")
def test_measured_artifact_regenerates_byte_identically():
    art = build_measured_artifact(haworth_window(), CE3, date=_DATE)
    assert _serialized(art) == _committed(f"shadow_sigma_calibration_MEASURED_{_DATE}.json")
