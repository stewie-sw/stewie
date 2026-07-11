#!/usr/bin/env bash
# STEWIE viz2 Phase B3 — the END-TO-END LIVE launcher.
#
# Starts the Viz2Runtime (python, the sole conserved mutator) then a HEADLESS Godot client that
# drives the EZ-RASSOR THROUGH it on real conserved terramechanics — the rover moves on the
# runtime's physics and the ruts carve into the terrain LIVE (the window mesh vertex-displaces from
# the live patched height texture). Captures land in $OUT_DIR.
#
# Mirrors viz2.sh: xvfb gives a real X server so the NVIDIA Vulkan ICD attaches and actually renders
# (--headless silently disables the driver, so the per-frame `await frame_post_draw` would hang).
#
#   bash viz2_live.sh                 # defaults: haworth_sfs_2km_1m, 12 capture frames
#   FRAMES=16 bash viz2_live.sh       # more captured frames
#   GODOT=/path/to/godot bash viz2_live.sh
set -euo pipefail

HERE="$(dirname "$(readlink -f "$0")")"                 # stewie/godot
REPO_ROOT="$(cd "$HERE/../.." && pwd)"                   # repo/worktree root
GODOT="${GODOT:-$HERE/.tools/godot/Godot_v4.6.3-stable_linux.x86_64}"
BUNDLE="${BUNDLE:-$REPO_ROOT/samples/lunar_dem/haworth_sfs_2km_1m}"
SESSION_DIR="${SESSION_DIR:-$(mktemp -d /tmp/viz2_live.XXXXXX)}"
OUT_DIR="${OUT_DIR:-$REPO_ROOT/out/viz2/live}"
FRAMES="${FRAMES:-12}"
XVFB_SCREEN="${XVFB_SCREEN:-1920x1080x24}"
PY="${PY:-$REPO_ROOT/.venv/bin/python}"
export PYTHONPATH="$REPO_ROOT:$REPO_ROOT/packages/stewie-bodies:$REPO_ROOT/packages/stewie-forge${PYTHONPATH:+:$PYTHONPATH}"

mkdir -p "$OUT_DIR"
echo "viz2_live: session=$SESSION_DIR out=$OUT_DIR bundle=$BUNDLE frames=$FRAMES"

# 1) start the runtime (background); it writes the 0600 token file into SESSION_DIR
"$PY" "$REPO_ROOT/stewie/runtime/viz2_serve.py" \
    --bundle "$BUNDLE" --session-dir "$SESSION_DIR" --seconds 90 &
SERVE_PID=$!
cleanup() { touch "$SESSION_DIR/STOP" 2>/dev/null || true; kill "$SERVE_PID" 2>/dev/null || true; }
trap cleanup EXIT

# 2) wait for the runtime's token file
for _ in $(seq 1 200); do
    [ -f "$SESSION_DIR/viz2_session.json" ] && break
    sleep 0.05
done
if [ ! -f "$SESSION_DIR/viz2_session.json" ]; then
    echo "viz2_live: runtime never wrote the token file" >&2
    exit 2
fi

# 3) the Godot client, headless on the GPU, drives THROUGH the runtime + captures
xvfb-run -a --server-args="-screen 0 ${XVFB_SCREEN}" \
    "$GODOT" --rendering-driver vulkan --path "$HERE" res://viz2.tscn -- \
    --live --session-dir "$SESSION_DIR" --site "$BUNDLE" --out "$OUT_DIR" --auto "$FRAMES" --size 1280x720

# 4) stop the runtime + report the captures
touch "$SESSION_DIR/STOP"
wait "$SERVE_PID" 2>/dev/null || true
echo "viz2_live: done — captures in $OUT_DIR"
ls -la "$OUT_DIR"
