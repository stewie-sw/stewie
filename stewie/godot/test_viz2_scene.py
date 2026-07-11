"""[REQ:] STEWIE viz2 Phase A — scene/input/postures wiring gate.

Real-file regression for the Phase-A deliverables (design plan v4 tasks A4/A5/A6):
the viz2 scene + launcher exist and are consistent, the InputMap declares the viz2_*
drive actions on WASD *and* gamepad, the drive script reads them through the InputMap
(no raw key polling), the A6 postures-path fix points at the real file, and the merged
1 m Haworth SfS bundle is present with self-consistent raster sizes.

No synthetic data: every assertion is against a real on-disk artifact.
Run: pytest stewie/godot/test_viz2_scene.py  (gate on exit code).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

# code/stewie/godot/test_viz2_scene.py -> parents[2] == code/
_REPO = Path(__file__).resolve().parents[2]
_GODOT = _REPO / "stewie" / "godot"
_BUNDLE = _REPO / "samples" / "lunar_dem" / "haworth_sfs_2km_1m"

_ACTIONS = [
    "viz2_forward",
    "viz2_back",
    "viz2_left",
    "viz2_right",
    "viz2_brake",
    "viz2_dig",
    "viz2_dump",
]


def test_viz2_scene_files_exist():
    """[REQ: A4] viz2 scene, root script, and launcher are present; launcher is executable."""
    tscn = _GODOT / "viz2.tscn"
    root = _GODOT / "viz2_root.gd"
    sh = _GODOT / "viz2.sh"
    assert tscn.is_file(), f"missing {tscn}"
    assert root.is_file(), f"missing {root}"
    assert sh.is_file(), f"missing {sh}"
    # viz2.tscn must instantiate viz2_root.gd
    assert "res://viz2_root.gd" in tscn.read_text(), "viz2.tscn does not reference viz2_root.gd"
    # launcher must be executable and run the viz2 scene headless via vulkan (mirrors render.sh)
    assert sh.stat().st_mode & 0o111, "viz2.sh is not executable"
    sh_txt = sh.read_text()
    assert "res://viz2.tscn" in sh_txt, "viz2.sh does not launch res://viz2.tscn"
    assert "--rendering-driver vulkan" in sh_txt, "viz2.sh must use the vulkan driver (render.sh parity)"
    assert "xvfb-run" in sh_txt, "viz2.sh must attach xvfb (render.sh parity)"


def test_viz2_root_loads_the_real_site_and_frozen_seams():
    """[REQ: A4] viz2_root reads the 1 m Haworth bundle through the frozen loader + TerrainNode,
    and assembles the rover from the real MIT glbs (no synthetic terrain / no reinvented loader)."""
    txt = (_GODOT / "viz2_root.gd").read_text()
    assert "haworth_sfs_2km_1m" in txt, "viz2_root must default to the 1 m Haworth bundle"
    assert 'preload("res://state_fields.gd")' in txt, "must reuse the frozen state_fields.gd loader"
    assert 'preload("res://terrain.gd")' in txt, "must build terrain via the frozen terrain.gd TerrainNode"
    for glb in ("rover_body.glb", "wheel.glb", "drum.glb", "drum_arm.glb"):
        assert glb in txt, f"rover assembly must reference {glb}"
        assert (_GODOT / "assets" / glb).is_file(), f"missing real asset assets/{glb}"


def test_viz2_carries_mit_notice():
    """[REQ: A4] The EZ-RASSOR MIT attribution rides along with the reused meshes (ezrassor_assets.md §1)."""
    txt = (_GODOT / "viz2_root.gd").read_text()
    assert "MIT" in txt and "Florida Space Institute" in txt, "viz2_root must carry the EZ-RASSOR MIT notice"


def _parse_input_actions(project_godot: str) -> dict[str, str]:
    """Return {action_name: block_text} for every action defined in the [input] section."""
    m = re.search(r"^\[input\]\s*$(.*)", project_godot, re.MULTILINE | re.DOTALL)
    assert m, "project.godot has no [input] section"
    section = m.group(1)
    # Stop at the next top-level [section] header if any.
    nxt = re.search(r"^\[[a-zA-Z]", section, re.MULTILINE)
    if nxt:
        section = section[: nxt.start()]
    blocks: dict[str, str] = {}
    for am in re.finditer(r"^([A-Za-z0-9_]+)=\{(.*?)^\}", section, re.MULTILINE | re.DOTALL):
        blocks[am.group(1)] = am.group(2)
    return blocks


def test_inputmap_declares_all_viz2_actions_on_key_and_gamepad():
    """[REQ: A5] project.godot InputMap declares every viz2_* action, each bound to a keyboard
    event AND a gamepad (joypad axis/button) event."""
    blocks = _parse_input_actions((_GODOT / "project.godot").read_text())
    for act in _ACTIONS:
        assert act in blocks, f"InputMap missing action {act}"
        body = blocks[act]
        assert "InputEventKey" in body, f"{act} has no keyboard binding"
        assert ("InputEventJoypadMotion" in body) or ("InputEventJoypadButton" in body), (
            f"{act} has no gamepad binding"
        )


def test_viz2_reads_actions_not_raw_keys():
    """[REQ: A5] viz2_root drives from the InputMap actions, never from raw key polling."""
    txt = (_GODOT / "viz2_root.gd").read_text()
    assert "Input.get_action_strength" in txt, "viz2_root must read analog action strength"
    assert "is_action_pressed" in txt, "viz2_root must read the brake action"
    assert "is_key_pressed" not in txt, "viz2_root must NOT poll raw keys (Input.is_key_pressed)"
    for act in _ACTIONS:
        assert act in txt, f"viz2_root never reads action {act}"
    assert "--auto" in txt, "viz2_root must expose the --auto N headless-render flag"


def test_a6_postures_path_fixed_and_target_exists():
    """[REQ: A6] drive_controller postures path points at the REAL physics/data file, and the
    stale terrain_authority/ path is gone."""
    txt = (_GODOT / "drive_controller.gd").read_text()
    assert "../physics/data/ipex_postures.json" in txt, "A6 fix not applied"
    assert "../terrain_authority/data/ipex_postures.json" not in txt, "stale postures path still present"
    assert (_REPO / "stewie" / "physics" / "data" / "ipex_postures.json").is_file(), (
        "the corrected postures target does not exist"
    )


def test_haworth_bundle_present_and_rasters_consistent():
    """[REQ: A4] The merged 1 m Haworth SfS bundle exists; metadata grid is 2000² @ 1 m and the
    float32 / uint8 raster byte-sizes match width*height (the frozen loader's own invariant)."""
    meta_path = _BUNDLE / "metadata.json"
    assert meta_path.is_file(), f"missing merged bundle metadata {meta_path}"
    meta = json.loads(meta_path.read_text())
    grid = meta["grid"]
    w, h = int(grid["width"]), int(grid["height"])
    assert (w, h) == (2000, 2000), f"unexpected grid {w}x{h}"
    assert float(grid["cell_m"]) == 1.0, "expected 1 m cells"
    for name in ("heightmap.rf32", "mass_areal.rf32", "density.rf32", "disturbance.rf32"):
        p = _BUNDLE / name
        assert p.is_file(), f"missing raster {p}"
        assert p.stat().st_size == w * h * 4, f"{name} size != w*h*4"
    r8 = _BUNDLE / "state_label.r8"
    assert r8.is_file() and r8.stat().st_size == w * h, "state_label.r8 size != w*h"
