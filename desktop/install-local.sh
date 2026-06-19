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
