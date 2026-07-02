#!/usr/bin/env bash
# Install the STEWIE desktop app for the current user on THIS machine.
#
# Local install: the AppImage carries the Electron shell; the Python sidecar runs from the repo's
# .venv (STEWIE_REPO baked into the .desktop launcher). This is the single-machine install -- a fully
# self-contained, ship-to-other-machines bundle (relocatable Python) is the separate packaging step.
#
# Reverse it:  rm ~/.local/bin/stewie-desktop ~/.local/share/applications/stewie.desktop
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
APP="$REPO/desktop/dist/STEWIE-0.1.0.AppImage"
[ -f "$APP" ] || { echo "AppImage not built -- run:  (cd '$REPO/desktop' && npm install && npm run dist)"; exit 1; }
[ -x "$REPO/.venv/bin/stewie-serve" ] || { echo "repo .venv sidecar missing at $REPO/.venv/bin/stewie-serve"; exit 1; }

# Preflight: the sidecar must actually import its server. A .venv without the stewie package passes
# the -x check above but dies at launch (real first-launch failure: 40 s health timeout, opaque
# dialog). Run from a NEUTRAL cwd with the same env main.js uses, so a repo-cwd import can't mask it.
if ! (cd / && env -u PYTHONPATH PYTHONNOUSERSITE=1 "$REPO/.venv/bin/python" -c "import stewie.server.server"); then
  echo "sidecar preflight FAILED: $REPO/.venv/bin/python cannot import stewie.server.server"
  echo "fix it, then re-run this script:"
  echo "  cd $REPO && PYTHONNOUSERSITE=1 .venv/bin/python -m pip install -e .[server] --no-deps"
  exit 1
fi

mkdir -p "$HOME/.local/bin" "$HOME/.local/share/applications"
install -m755 "$APP" "$HOME/.local/bin/stewie-desktop"

cat > "$HOME/.local/share/applications/stewie.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=STEWIE
Comment=STEWIE lunar digital-twin & mission-planning cockpit
Exec=env STEWIE_REPO=$REPO $HOME/.local/bin/stewie-desktop
Icon=stewie
Categories=Science;Engineering;
Terminal=false
EOF

update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
echo "installed:"
echo "  binary   ~/.local/bin/stewie-desktop"
echo "  launcher ~/.local/share/applications/stewie.desktop  (STEWIE_REPO=$REPO)"
echo "run from the app menu (STEWIE) or:  STEWIE_REPO=$REPO ~/.local/bin/stewie-desktop"
