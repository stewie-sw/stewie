#!/usr/bin/env bash
# P1.7 headless 3D render proof (see render_3d_proof.py). Runs the layout-3D render
# under a GL-capable display: xvfb provides OpenGL 4.5 via llvmpipe (software) on
# this host; the NVIDIA GPU is only reachable via Vulkan under a bare Xvfb, not
# GLX, so the terrain is software-rendered (correct, just slower). Writes
# proof/<site>_3d.png. Usage: ./render_3d_proof.sh [Site01 Site04 ...]
set -euo pipefail
cd "$(dirname "$0")"
if [ "$#" -eq 0 ]; then
  set -- Site01 Site04 Site07 Site11 Site20
fi
exec env -u QT_QPA_PLATFORM xvfb-run -a --server-args="-screen 0 1600x1200x24" \
  /usr/bin/python3 render_3d_proof.py "$@"
