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
#
# SYNTHETIC procedural site (rendered IDENTICALLY to a real bundle via the uniform --site loader):
#   bash viz2.sh -- --auto 6 --site out/procedural_sandbox/<name>
#
# 2 cm-FINE toggle on a REAL bundle (--fine on|off). This pre-generates a REAL DEM window at 2 cm
# fine (conservation-bounded fbm overlay) or base resolution via scripts/generate_fine_window.py,
# then renders it through the SAME uniform --site loader (the frozen seams are untouched):
#   STEWIE_PY=/path/to/venv/python bash viz2.sh --fine on  --fine-site samples/lunar_dem/haworth_sfs_2km_1m -- --auto 6
#   STEWIE_PY=/path/to/venv/python bash viz2.sh --fine off --fine-site samples/lunar_dem/haworth_sfs_2km_1m -- --auto 6
# Extra fine knobs: --fine-window-cells N  --fine-center-rc r,c  --fine-seed N  --fine-nu0 X .
# The fbm engine needs numpy/scipy, so point $STEWIE_PY at the runtime venv (default: python3).
set -euo pipefail

GODOT="${GODOT:-$(dirname "$(readlink -f "$0")")/../.tools/godot/Godot_v4.6.3-stable_linux.x86_64}"
PROJECT_DIR="$(dirname "$(readlink -f "$0")")"
REPO_ROOT="$(readlink -f "$PROJECT_DIR/../..")"
STEWIE_PY="${STEWIE_PY:-python3}"

# --- optional --fine on|off pre-pass (leader args BEFORE the `--` separator) ---------------------
# Parse launcher-level flags up to `--`; everything from `--` onward is passed to viz2_root.gd
# verbatim (with a --site <generated window> injected when --fine is used).
FINE_MODE=""
FINE_SITE=""
FINE_WINDOW_CELLS="24"
FINE_CENTER_RC=""
FINE_SEED="0"
FINE_NU0=""
GODOT_ARGS=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        --) shift; GODOT_ARGS+=("$@"); break ;;
        --fine) FINE_MODE="$2"; shift 2 ;;
        --fine-site) FINE_SITE="$2"; shift 2 ;;
        --fine-window-cells) FINE_WINDOW_CELLS="$2"; shift 2 ;;
        --fine-center-rc) FINE_CENTER_RC="$2"; shift 2 ;;
        --fine-seed) FINE_SEED="$2"; shift 2 ;;
        --fine-nu0) FINE_NU0="$2"; shift 2 ;;
        *) GODOT_ARGS+=("$1"); shift ;;
    esac
done

if [[ -n "$FINE_MODE" ]]; then
    if [[ "$FINE_MODE" != "on" && "$FINE_MODE" != "off" ]]; then
        echo "viz2.sh: --fine expects on|off (got '$FINE_MODE')" >&2; exit 2
    fi
    if [[ -z "$FINE_SITE" ]]; then
        echo "viz2.sh: --fine requires --fine-site <real bundle dir>" >&2; exit 2
    fi
    GEN_ARGS=(--site "$FINE_SITE" --mode "$FINE_MODE" --window-cells "$FINE_WINDOW_CELLS"
              --seed "$FINE_SEED" --name "viz2_fine_${FINE_MODE}")
    [[ -n "$FINE_CENTER_RC" ]] && GEN_ARGS+=(--center-rc "$FINE_CENTER_RC")
    [[ -n "$FINE_NU0" ]] && GEN_ARGS+=(--fbm-nu0 "$FINE_NU0")
    echo "viz2.sh: --fine $FINE_MODE -> generating window bundle via generate_fine_window.py" >&2
    # The generator prints the output bundle dir on its LAST stdout line.
    FINE_OUT="$(cd "$REPO_ROOT" && PYTHONPATH="$REPO_ROOT:$REPO_ROOT/packages/stewie-bodies:$REPO_ROOT/packages/stewie-forge${PYTHONPATH:+:$PYTHONPATH}" \
        "$STEWIE_PY" scripts/generate_fine_window.py "${GEN_ARGS[@]}" | tee /dev/stderr | tail -1)"
    if [[ -z "$FINE_OUT" || ! -d "$FINE_OUT" ]]; then
        echo "viz2.sh: fine-window generation failed (no bundle dir)" >&2; exit 3
    fi
    echo "viz2.sh: --fine $FINE_MODE bundle -> $FINE_OUT" >&2
    GODOT_ARGS+=(--site "$FINE_OUT")
fi

cd "$PROJECT_DIR"
# Virtual screen must be >= the requested --size, else the window (and render) is clamped.
XVFB_SCREEN="${XVFB_SCREEN:-1920x1080x24}"
exec xvfb-run -a --server-args="-screen 0 ${XVFB_SCREEN}" \
    "$GODOT" --rendering-driver vulkan --path "$PROJECT_DIR" res://viz2.tscn -- "${GODOT_ARGS[@]}"
