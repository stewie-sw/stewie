#!/usr/bin/env bash
# Headless Godot launcher for STEWIE viz2 (Phase A: the driveable scene foundation).
# Mirrors render.sh: xvfb gives a real X server so the NVIDIA Vulkan ICD attaches and
# actually renders (--headless silently disables the rendering driver, so the per-frame
# `await frame_post_draw` in the capture coroutine would hang forever — NEVER pass it).
#
# Runs res://viz2.tscn (the viz2 scene), NOT the frozen sidecar. Everything after `--` is a
# viz2_root.gd user arg (OS.get_cmdline_user_args). Headless N-frame verification capture:
#   bash viz2.sh -- --auto 8 --size 1280x720
# Interactive drive on a real display (WASD / gamepad):
#   GODOT=<godot> "$GODOT" --rendering-driver vulkan --path . res://viz2.tscn
set -euo pipefail

GODOT="${GODOT:-$(dirname "$(readlink -f "$0")")/../.tools/godot/Godot_v4.6.3-stable_linux.x86_64}"
PROJECT_DIR="$(dirname "$(readlink -f "$0")")"

cd "$PROJECT_DIR"
# Virtual screen must be >= the requested --size, else the window (and render) is clamped.
XVFB_SCREEN="${XVFB_SCREEN:-1920x1080x24}"
exec xvfb-run -a --server-args="-screen 0 ${XVFB_SCREEN}" \
    "$GODOT" --rendering-driver vulkan --path "$PROJECT_DIR" res://viz2.tscn "$@"
