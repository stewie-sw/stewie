#!/usr/bin/env bash
# STEWIE viz2 pixel-stream server launcher (standalone; NOT stewie/server).
#
# Starts the FastAPI stream app (stewie.stream.app:app) on 0.0.0.0:PORT. Each browser that opens
# ws://<host>:PORT/ws spawns its OWN Viz2Runtime + headless Godot (xvfb+vulkan) on the host GPU and
# streams JPEG frames back live. TAILNET-PRIVATE: bind 0.0.0.0 and reach it over Tailscale; no auth (v1).
#
#   bash scripts/run_viz2_stream.sh                 # 0.0.0.0:8900
#   PORT=8901 bash scripts/run_viz2_stream.sh
#   STEWIE_GODOT=/path/to/Godot bash scripts/run_viz2_stream.sh
#
# Then open http://<tailscale-host>:8900/  (WASD/arrows drive; dig/dump buttons; sun az/el sliders).
set -euo pipefail

HERE="$(dirname "$(readlink -f "$0")")"          # scripts/
REPO_ROOT="$(cd "$HERE/.." && pwd)"              # repo / worktree root
PY="${PY:-$REPO_ROOT/.venv/bin/python}"
PORT="${PORT:-8900}"
HOST="${HOST:-0.0.0.0}"

export PYTHONPATH="$REPO_ROOT:$REPO_ROOT/packages/stewie-bodies:$REPO_ROOT/packages/stewie-forge${PYTHONPATH:+:$PYTHONPATH}"
# Godot binary + project (the .tools/godot symlink is gitignored; default to the shared host tool).
export STEWIE_GODOT="${STEWIE_GODOT:-/mnt/projects/tools/Godot_v4.6.3-stable_linux.x86_64}"
export STEWIE_GODOT_PROJECT="${STEWIE_GODOT_PROJECT:-$REPO_ROOT/stewie/godot}"

echo "viz2-stream: http://${HOST}:${PORT}/  (WS /ws)  godot=${STEWIE_GODOT}"
exec "$PY" -m uvicorn stewie.stream.app:app --host "$HOST" --port "$PORT" --ws websockets
