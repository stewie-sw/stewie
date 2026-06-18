#!/usr/bin/env bash
# Headless Godot render wrapper for foss_ipex.
# Uses xvfb because --headless disables the real rendering driver (no frame_post_draw).
# The NVIDIA Vulkan ICD attaches to xvfb's X server and does the actual rendering.
# NEVER pass --headless yourself -- it silently disables rendering and the per-frame
# `await frame_post_draw` in the capture coroutines then hangs forever.
#
# The default main_scene is render_test.tscn (the smoke cube); to drive the sensor capture
# you MUST run res://sidecar.tscn explicitly, and the 8-camera rig (--cameras) needs the
# rover root, so include it in --layers. Single-station 8-cam egress (~1-2 s on an RTX 3090):
#   bash render.sh res://sidecar.tscn -- --scene <abs scene dir> --cameras \
#        --layers terrain,clasts,rover --rover-rc <r,c> --sun-elev 8 --sun-azim 215 --size 1024x768
set -euo pipefail

GODOT="${GODOT:-$(dirname "$(readlink -f "$0")")/../.tools/godot/Godot_v4.6.3-stable_linux.x86_64}"
PROJECT_DIR="$(dirname "$(readlink -f "$0")")"

cd "$PROJECT_DIR"
# Virtual screen must be >= the requested --size, else the window (and render) is clamped.
# Default 1920x1080 so 1080p renders fit; override with XVFB_SCREEN for larger.
XVFB_SCREEN="${XVFB_SCREEN:-1920x1080x24}"
exec xvfb-run -a --server-args="-screen 0 ${XVFB_SCREEN}" \
    "$GODOT" --rendering-driver vulkan "$@"
